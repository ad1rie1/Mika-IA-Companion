"""La console en MCP : lire Mika depuis un agent (le Claude Code de sa propriétaire).

Lecture seule, comme la console : les vues que les facultés déclarent
(``@f.inspect``), les fiches d'objets (personne, poignée, but, app, mail…) et
la recherche. Aucune action d'opérateur ici (elles passent par la console, avec
leur jeton à usage unique). Servie sous ``/mcp/console``, sur la boucle locale
seulement, derrière un jeton d'opérateur (``mika mcp token``) ; sans jeton
défini, le point n'existe pas (404).

Rien ici ne nomme une faculté : les vues et leurs paramètres se découvrent par
``lister_vues`` (par exemple ``memory/souvenirs`` avec ``q`` pour chercher un
souvenir).
"""

from __future__ import annotations

import hmac
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

from mika.adapters.mcp.protocol import Outcome, Tool, asgi, bearer, loopback
from mika.inspector.text import cell, render
from mika.kernel.clock import US
from mika.kernel.inspect import Head, Note
from mika.runtime.inspection import Inspection

if TYPE_CHECKING:
    from mika.runtime.bootstrap import Kernel

PREFIX = "/mcp/console"
PARAMS = {"type": "object", "additionalProperties": {"type": "string"},
          "description": "les paramètres de la vue (ceux que liste lister_vues), plus « page » et « taille »"}

TOOLS = (
    Tool("lister_vues", "Les vues de la console de Mika (mémoire, esprit, liens, travail, exploitation…) : leur "
         "clé « propriétaire/nom », leur titre, leurs paramètres. Les fiches d'objets aussi (sortes et onglets).",
         {"type": "object", "properties": {"section": {"type": "string", "description": "ne lister que cette "
                                                                                        "section"}}},
         read_only=True),
    Tool("vue", "Lire une vue de la console, par sa clé (ex. « memory/souvenirs » avec {\"q\": \"chat\"}).",
         {"type": "object", "properties": {"cle": {"type": "string"}, "params": PARAMS}, "required": ["cle"]},
         read_only=True),
    Tool("chercher", "Chercher un objet (personne, poignée, but, app, mail…) par un mot : rend les fiches trouvées.",
         {"type": "object", "properties": {"texte": {"type": "string"}, "sorte": {"type": "string"}},
          "required": ["texte"]}, read_only=True),
    Tool("fiche", "Lire la fiche d'un objet : son en-tête, ses onglets, et un onglet (le premier par défaut).",
         {"type": "object", "properties": {"sorte": {"type": "string"}, "cle": {"type": "string"},
                                           "onglet": {"type": "string"}, "params": PARAMS},
          "required": ["sorte", "cle"]}, read_only=True),
)


class ConsoleHost:
    """Les outils de lecture, pour un noyau."""

    name = "mika-console"

    def __init__(self, kernel: Kernel) -> None:
        self.kernel = kernel
        self.inspection = Inspection(kernel, sampler=kernel.series.read)

    def tools(self) -> Sequence[Tool]:
        return TOOLS

    def when(self, t: int) -> str:
        frame = self.kernel.mind.frame()
        return datetime.fromtimestamp(t / US, frame.env.tz_of(frame.root)).strftime("%d/%m/%Y %H:%M:%S")

    def text(self, blocks: Sequence[Any]) -> str:
        return render(blocks, self.when, self.kernel.mind.clock.now()) or "(rien)"

    async def call(self, name: str, arguments: Mapping[str, Any]) -> Outcome:
        params = {str(k): str(v) for k, v in (arguments.get("params") or {}).items()} \
            if isinstance(arguments.get("params"), Mapping) else {}
        if name == "lister_vues":
            return Outcome(self._catalogue(str(arguments.get("section") or "")))
        if name == "vue":
            owner, _, view = str(arguments.get("cle") or "").partition("/")
            spec = self.inspection.find(owner, view)
            if spec is None or spec.subject:
                return Outcome(f"vue inconnue : {arguments.get('cle')} (voir lister_vues)", is_error=True)
            return Outcome(f"# {spec.title}\n" + self.text(await self.inspection.arun(spec, params, self.when)))
        if name == "chercher":
            return Outcome(self._search(str(arguments.get("texte") or ""), str(arguments.get("sorte") or "")))
        if name == "fiche":
            return await self._fiche(str(arguments.get("sorte") or ""), str(arguments.get("cle") or ""),
                                     str(arguments.get("onglet") or ""), params)
        return Outcome(f"outil inconnu : {name}", is_error=True)

    def _catalogue(self, section: str) -> str:
        lines = []
        for v in self.inspection.views():
            if v.hidden or v.subject or (section and v.section != section):
                continue
            params = ", ".join(p.name for p in v.typed)
            lines.append(f"- {v.owner}/{v.name} — {v.title} [{v.section or '—'}]" + (f" ; paramètres : {params}"
                                                                                       if params else ""))
        if not section:
            lines.append("\nFiches (outil « fiche ») :")
            for kind, spec in sorted(self.kernel.registry.subjects.items()):
                tabs = ", ".join(t.name for t in self.inspection.tabs(kind))
                lines.append(f"- {kind} — {spec.label} ; onglets : {tabs or '—'}")
        return "\n".join(lines) or "aucune vue"

    def _search(self, text: str, kind: str) -> str:
        if not text.strip():
            return "un mot à chercher, s'il te plaît"
        kinds = [kind] if kind else sorted(self.kernel.registry.subjects)
        lines = [f"- fiche:{k}/{f.key} — {f.title}{(' (' + f.subtitle + ')') if f.subtitle else ''}"
                 for k in kinds for f in self.inspection.search(k, text, 20)]
        return "\n".join(lines) or "rien trouvé"

    async def _fiche(self, kind: str, key: str, tab: str, params: dict[str, str]) -> Outcome:
        spec = self.inspection.subject(kind)
        if spec is None:
            return Outcome(f"sorte inconnue : {kind} (voir lister_vues)", is_error=True)
        head = self.inspection.head(kind, key, self.when)
        if head is None:
            return Outcome(f"aucun objet {kind} « {key} »", is_error=True)
        lines: list[str] = []
        subject = key
        if isinstance(head, Head):
            subject = head.key
            now = self.kernel.mind.clock.now()
            lines.append(f"# {head.title}" + (f" — {head.subtitle}" if head.subtitle else ""))
            lines += [f"- {label} : {cell(value, self.when, now)}" for label, value in head.facts]
        elif isinstance(head, Note):
            lines.append(head.text)
        tabs = self.inspection.tabs(kind)
        if not tabs:
            return Outcome("\n".join(lines))
        current = next((t for t in tabs if t.name == tab), tabs[0])
        lines.append("Onglets : " + ", ".join(("*" + t.name + "*") if t is current else t.name for t in tabs))
        lines.append(f"\n## {current.title}")
        lines.append(self.text(await self.inspection.arun(current, params, self.when, subject=subject)))
        return Outcome("\n".join(lines))


def console_app(kernel: Kernel, token: Callable[[], str]) -> Callable[..., Any]:
    """Le point MCP de la console : boucle locale, jeton d'opérateur ; sans jeton défini, 404."""
    host = ConsoleHost(kernel)

    def resolve(scope: Mapping[str, Any]) -> Any:
        if not loopback(scope):
            return 403
        expected = token()
        if not expected:
            return 404
        if not hmac.compare_digest(bearer(scope), expected):
            return 401
        return host

    return asgi(resolve)
