"""La console en MCP : lire Mika depuis un agent (le Claude Code de sa propriétaire).

Lecture seule, comme la console : les vues que les facultés déclarent
(``@f.inspect``), les fiches d'objets (personne, adresse, but, app, mail…) et
la recherche ; et, servies par les pages de la console elle-même (``PAGES``,
une liste blanche), la santé, les processus, les anomalies, les sorties, les
coûts, la chronologie, les épisodes, les choix de l'arbitre, « Que
ferait-elle ? », « À traiter » — plus « pourquoi a-t-elle dit ça ? »
(``pourquoi``). Jamais une page à formulaires (approbations, réglages,
comptes), et aucune action d'opérateur ici (elles passent par la console, avec
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
from mika.inspector.catalog import Builtin
from mika.inspector.text import cell, render
from mika.kernel.clock import US
from mika.kernel.inspect import Filters, Head, Note, int_query
from mika.runtime.inspection import Inspection

if TYPE_CHECKING:
    from mika.inspector.app import ConsolePages
    from mika.runtime.bootstrap import Kernel

PREFIX = "/mcp/console"
PARAMS = {"type": "object", "additionalProperties": {"type": "string"},
          "description": "les paramètres de la vue (ceux que liste lister_vues), plus « page » et « taille »"}

#: les pages de la console servies en lecture (la clé de leur onglet ; « destination/onglet » pour l'outil ``vue``) :
#: des blocs seulement. Jamais une page à formulaires (approbations, réglages, comptes) : ni formulaire, ni action,
#: ni secret par ce point
PAGES = ("accueil.a_traiter", "systeme.sante", "systeme.processus", "systeme.anomalies", "systeme.sorties",
         "systeme.appels", "systeme.chronologie", "decisions.episodes", "decisions.selections", "decisions.envers")

TOOLS = (
    Tool("lister_vues", "Les vues de la console de Mika (mémoire, esprit, liens, travail, exploitation…) : leur "
         "clé « propriétaire/nom », leur titre, leurs paramètres ; et les pages de la console servies ici (santé, "
         "processus, sorties, épisodes, « que ferait-elle ? »…), clé « destination/onglet ». Les fiches d'objets "
         "aussi (sortes et onglets).",
         {"type": "object", "properties": {"section": {"type": "string", "description": "ne lister que cette "
                                                                                        "section"}}},
         read_only=True),
    Tool("vue", "Lire une vue de la console, par sa clé (ex. « memory/souvenirs » avec {\"q\": \"chat\"}, "
         "« systeme/sante », « decisions/envers » avec {\"personne\": \"Chloé\"}).",
         {"type": "object", "properties": {"cle": {"type": "string"}, "params": PARAMS}, "required": ["cle"]},
         read_only=True),
    Tool("pourquoi", "« Pourquoi a-t-elle dit ça ? » : une de ses paroles expliquée, par son numéro (celui d'un lien "
         "« parole:… ») — à qui, ce qui l'a fait parler (le message, ou le calcul de l'arbitre), les sections de son "
         "prompt, les souvenirs rappelés, les outils.",
         {"type": "object", "properties": {"seq": {"type": "integer", "description": "le numéro de la parole"}},
          "required": ["seq"]}, read_only=True),
    Tool("chercher", "Chercher un objet (personne, adresse, but, app, mail…) par un mot : rend les fiches trouvées.",
         {"type": "object", "properties": {"texte": {"type": "string"}, "sorte": {"type": "string"}},
          "required": ["texte"]}, read_only=True),
    Tool("fiche", "Lire la fiche d'un objet : son en-tête, ses onglets, et un onglet (le premier par défaut).",
         {"type": "object", "properties": {"sorte": {"type": "string"}, "cle": {"type": "string"},
                                           "onglet": {"type": "string"}, "params": PARAMS},
          "required": ["sorte", "cle"]}, read_only=True),
)


class ConsoleHost:
    """Les outils de lecture, pour un noyau ; avec les pages de la console (``ConsolePages``), aussi celles de
    ``PAGES`` et « pourquoi », lues par la même ``Inspection`` que la console."""

    name = "mika-console"

    def __init__(self, kernel: Kernel, pages: ConsolePages | None = None) -> None:
        self.kernel = kernel
        self.pages = pages
        self.inspection = pages.ui.inspection if pages is not None else Inspection(kernel, sampler=kernel.series.read)

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
            tab = self._pages().get(f"{owner}.{view}")
            if tab is not None:
                return await self._page(f"{owner}.{view}", tab.title, params)
            spec = self.inspection.find(owner, view)
            if spec is None or spec.subject:
                return Outcome(f"vue inconnue : {arguments.get('cle')} (voir lister_vues)", is_error=True)
            return Outcome(f"# {spec.title}\n" + self.text(await self.inspection.arun(spec, params, self.when)))
        if name == "pourquoi":
            return self._why(arguments.get("seq"))
        if name == "chercher":
            return Outcome(self._search(str(arguments.get("texte") or ""), str(arguments.get("sorte") or "")))
        if name == "fiche":
            return await self._fiche(str(arguments.get("sorte") or ""), str(arguments.get("cle") or ""),
                                     str(arguments.get("onglet") or ""), params)
        return Outcome(f"outil inconnu : {name}", is_error=True)

    def _pages(self) -> dict[str, Builtin]:
        """Les pages de ``PAGES`` que cette console sert, par clé d'onglet (aucune sans ses pages)."""
        if self.pages is None:
            return {}
        return {key: tab for key in PAGES if (tab := self.pages.tab(key)) is not None}

    async def _page(self, key: str, title: str, params: dict[str, str]) -> Outcome:
        """Une page de la console, en texte : ses blocs (jamais son panneau), puis ses filtres."""
        got = await self.pages.read(key, params) if self.pages is not None else None
        if got is None:
            return Outcome(f"vue inconnue : {key.replace('.', '/', 1)} (voir lister_vues)", is_error=True)
        blocks, filters = got
        if filters:
            blocks = [*blocks, Filters(filters, tuple(params.items()))]
        return Outcome(f"# {title}\n" + self.text(blocks))

    def _why(self, raw: Any) -> Outcome:
        """« Pourquoi a-t-elle dit ça ? » : la page d'une parole, en texte."""
        if self.pages is None:
            return Outcome("« pourquoi » n'est pas servi ici : la console n'est pas branchée", is_error=True)
        got = self.pages.why(int_query(str(raw if raw is not None else "").removeprefix("parole:"), 0))
        if got is None:
            return Outcome(f"le n° {raw} n'est pas une de ses paroles", is_error=True)
        now = self.kernel.mind.clock.now()
        lines = [f"# {got['title']}", got["subtitle"]]
        lines += [f"- {label} : {cell(value, self.when, now)}" for label, value in got["facts"]]
        lines.append(self.text(got["blocks"]))
        return Outcome("\n".join(lines))

    def _catalogue(self, section: str) -> str:
        lines = []
        for key, tab in self._pages().items():
            destination, _, slug = key.partition(".")
            if section and destination != section:
                continue
            lines.append(f"- {destination}/{slug} — {tab.title} [{destination}]"
                         + (f" : {tab.description}" if tab.description else ""))
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


def console_app(kernel: Kernel, token: Callable[[], str], pages: ConsolePages | None = None) -> Callable[..., Any]:
    """Le point MCP de la console : boucle locale, jeton d'opérateur ; sans jeton défini, 404. ``pages`` : celles
    de la console (``inspector.app.assemble``), pour servir aussi ``PAGES`` et « pourquoi »."""
    host = ConsoleHost(kernel, pages)

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
