"""La documentation de ses projets, par MCP, pour une personne (ADR 0289) : le point ``/mcp/moi``.

Qui a accès à la documentation d'un projet la lit et l'écrit par MCP **sans rien régler** : un outil (un assistant de
code) présente un **jeton de compte** (``Authorization: Bearer mw_…``) et agit comme la personne de ce compte, avec
ses droits et rien de plus — ceux que les routes de son espace appliquent (``api.docs.reads``, ``writes`` : les
lignes d'accès du projet, relues à chaque appel). Il ne voit que la documentation des projets qui la lui ouvrent ; un
projet qu'elle ne voit pas répond comme un projet inconnu.

- **Le jeton.** Celui d'un outil (client ``tool`` : ``mika token create --client tool``, ou la console) n'ouvre que
  ce point. Celui d'un téléphone y écrit aussi ; celui d'un écran n'y fait que lire, comme partout (ADR 0235).
- **Ses outils** : ``doc_lister`` (ses projets, ou les pages et les images de l'un), ``doc_lire``, ``doc_chercher``,
  ``doc_ecrire``, ``doc_image``. Chacun rend du JSON — ce que servent les routes de son espace, par les mêmes
  fonctions.
- **Une écriture** passe par l'action de la faculté (auditée ``moi.projects.doc_…``), et se dit « par MCP » dans
  l'historique de la page, avec le nom du jeton. Elle nomme la version lue (``base``) : rien n'est écrasé.
- **La porte** : ``PER_MINUTE`` appels par minute et par compte (429) ; pas de jeton, ou un jeton qui ne vaut rien :
  401. Rien n'y est réservé à la boucle locale : le jeton est celui d'une personne, comme sur son API ; le mandataire
  ne relaie ce point que si on le lui dit.
- **Ce que la borne compte** (ADR 0292) : **chaque appel d'outil**, pas chaque requête — un lot de messages
  (``protocol.BATCH_MAX`` au plus) paie un passage par appel, et celui qui dépasse répond « trop d'appels » sans rien
  faire ; et **les écritures** (une page, une image) : ``WRITES_PER_DAY`` par projet sur vingt-quatre heures, tous
  comptes confondus — un outil qui boucle n'écrit pas des centaines de versions de 100 000 caractères au journal.
  Le compte des écritures est gardé en mémoire : il repart de zéro au redémarrage.
- **Le jeton sert** : son usage est noté ici (au plus une fois par minute), comme sur l'API — la liste des jetons le
  montre, et un jeton d'outil qui sert n'est pas pris pour un jeton abandonné.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from mika.adapters.mcp.protocol import Outcome, Tool, asgi, bearer
from mika.adapters.web.accounts import CLIENT_SCREEN, Account, Accounts
from mika.adapters.web.gate import SlidingWindow, one_line
from mika.app.domains.projects.api import docs as pages
from mika.app.domains.projects.api.projects import Reach, Scene, audience_at, reach
from mika.app.me.api import Denied, form, me_of
from mika.faculties.projects import docs, links
from mika.faculties.projects import inspect_docs as words
from mika.ports.mail import File
from mika.runtime.bootstrap import Kernel
from mika.runtime.operations import SPACE, perform

PREFIX = "/mcp/moi"
#: au-delà, un compte attend la minute suivante (429) : un outil qui boucle ne la noie pas. Chaque appel d'outil
#: compte, aussi dans un lot (ADR 0292)
PER_MINUTE = 120
#: les écritures par MCP dans la documentation d'un projet (une page enregistrée, une image ajoutée), au plus, sur
#: vingt-quatre heures glissantes et tous comptes confondus (ADR 0292)
WRITES_PER_DAY = 200
DAY_S = 24 * 3600.0
#: l'usage d'un jeton se note au plus une fois par ce délai (secondes) : pas une écriture en base par appel
USE_NOTED_S = 60.0
TOO_MANY = "Trop d'appels d'affilée : attends une minute avant de réessayer."
TOO_MANY_WRITES = (f"Ce projet a déjà reçu {WRITES_PER_DAY} écritures par MCP en vingt-quatre heures : sa "
                   "documentation n'en prend plus d'ici pour l'instant. Rien n'a été écrit.")
#: le canal par où un outil arrive : celui d'un client natif de la personne (``projects.audience_of``)
CHANNEL = "mobile"
UNKNOWN = "Projet introuvable, ou sa documentation ne t'est pas ouverte."
READS_ONLY = "Ce jeton ne fait que lire : écrire demande le jeton d'un outil (client « tool »)."
_PROJECT = {"type": "integer", "description": "le numéro du projet (doc_lister, sans projet, les donne)"}
_PATH = {"type": "string", "description": "le chemin de la page, relatif à l'espace, en « .md » (« accueil.md », "
                                          "« guide/installation.md »)"}

TOOLS = (
    Tool("doc_lister", "Sans projet : les projets dont la documentation t'est ouverte (leur numéro, leur titre, si tu "
         "peux l'écrire). Avec un projet : les pages de sa documentation (chemin, titre, version, dernière "
         "modification) et ses images. La documentation d'un projet est un espace à part de son dépôt.",
         {"type": "object", "properties": {"projet": _PROJECT}}, read_only=True),
    Tool("doc_lire", "Lire une page de la documentation d'un projet : son Markdown, sa version (à redonner dans "
         "« base » pour l'écrire), qui l'a modifiée en dernier. Avec « version », une version gardée.",
         {"type": "object", "properties": {"projet": _PROJECT, "chemin": _PATH,
                                           "version": {"type": "integer", "description": "une version gardée"}},
          "required": ["projet", "chemin"]}, read_only=True),
    Tool("doc_chercher", "Chercher des mots dans la documentation d'un projet (chemins et textes) : les pages "
         "trouvées, avec le passage.",
         {"type": "object", "properties": {"projet": _PROJECT, "mots": {"type": "string"}},
          "required": ["projet", "mots"]}, read_only=True),
    Tool("doc_ecrire", "Écrire une page de la documentation d'un projet : son texte entier, en Markdown, et un mot "
         "sur ce qui a changé. Une version de plus est gardée (ce n'est pas un commit). « base » : la version lue "
         "(0 pour une page nouvelle) — si la page a changé depuis, rien n'est écrasé : relis-la.",
         {"type": "object", "properties": {"projet": _PROJECT, "chemin": _PATH, "texte": {"type": "string"},
                                           "mot": {"type": "string", "description": "ce qui a changé, en un mot"},
                                           "base": {"type": "integer"}},
          "required": ["projet", "chemin", "texte", "base"]}),
    Tool("doc_image", "Téléverser une image (PNG, JPEG, GIF, WebP) dans la documentation d'un projet : une page la "
         "cite ensuite par « images/<nom> ».",
         {"type": "object", "properties": {"projet": _PROJECT, "nom": {"type": "string"},
                                           "base64": {"type": "string", "description": "ses octets, en base64"}},
          "required": ["projet", "nom", "base64"]}),
)
WRITING = frozenset({"doc_ecrire", "doc_image"})


def _json(data: Any) -> Outcome:
    return Outcome(json.dumps(data, ensure_ascii=False, indent=1))


def _no(message: str) -> Outcome:
    return Outcome(message, is_error=True)


class PersonHost:
    """Les outils de documentation, pour un jeton de compte : la personne de ce compte, ses droits."""

    name = "mika-documentation"

    def __init__(self, kernel: Kernel, account: Account, *, writes: bool, label: str,
                 spend: Callable[[], bool] | None = None, write: Callable[[int], bool] | None = None) -> None:
        self.kernel, self.account, self.writes, self.label = kernel, account, writes, label
        #: la porte, pour chaque appel après le premier (la requête a payé le sien), et pour chaque écriture
        self._spend, self._write = spend, write
        self._paid = 1

    def tools(self) -> Sequence[Tool]:
        return TOOLS if self.writes else tuple(t for t in TOOLS if t.name not in WRITING)

    def scene(self) -> Scene:
        """Ce qu'un appel lit une fois : ce qu'elle vit, et qui demande — la personne du compte, par ``CHANNEL``."""
        frame = self.kernel.mind.frame()
        me = me_of(frame, self.account)
        return Scene(None, frame, frame.state("projects"), links.world_of(frame),  # type: ignore[arg-type]
                     audience_at(frame, me, CHANNEL), me.person)

    def _opened(self, sc: Scene, raw: Any, *, write: bool = False) -> Reach:
        """Le projet nommé, si sa documentation lui est ouverte ; sinon le même refus qu'un projet inconnu."""
        p = sc.s.projects.get(raw) if isinstance(raw, int) and not isinstance(raw, bool) else None
        r = reach(sc, p) if p is not None else None
        if r is None or not r.see or not pages.reads(sc, r):
            raise Denied(404, UNKNOWN)
        pages.guard(sc, r, write=write)
        return r

    def _listed(self, sc: Scene) -> dict[str, Any]:
        store = self.kernel.mind.store
        found = [r for r in (reach(sc, p) for p in sc.s.projects.values()) if r.see and pages.reads(sc, r)]
        titles = store.content([r.p.title_ref for r in found if r.p.title_ref])
        return {"projects": [{"id": r.p.id, "title": titles.get(r.p.title_ref, ""), "pages": len(r.p.docs.pages),
                              "write": pages.writes(sc, r) and self.writes} for r in found]}

    async def call(self, name: str, arguments: Mapping[str, Any]) -> Outcome:
        if name not in {t.name for t in TOOLS}:
            return _no(f"outil inconnu : {name}")
        if name in WRITING and not self.writes:
            return _no(READS_ONLY)
        # chaque appel compte (ADR 0292) : le premier est celui que la requête a payé à la porte, les suivants d'un
        # même lot paient le leur
        if self._paid:
            self._paid -= 1
        elif self._spend is not None and not self._spend():
            return _no(TOO_MANY)
        try:
            return await self._call(name, arguments)
        except Denied as exc:
            return _no(exc.message)

    async def _call(self, name: str, args: Mapping[str, Any]) -> Outcome:
        sc, store = self.scene(), self.kernel.mind.store
        if name == "doc_lister" and not args.get("projet"):
            return _json(self._listed(sc))
        r = self._opened(sc, args.get("projet"), write=name in WRITING)
        if name in WRITING and self._write is not None and not self._write(r.p.id):
            return _no(TOO_MANY_WRITES)
        if name == "doc_lister":
            got = pages.space(sc, r, store)
            return _json({**got, "rights": {"read": True, "write": got["rights"]["write"] and self.writes}})
        if name == "doc_chercher":
            return _json(pages.search(sc, r, store, str(args.get("mots") or "")[:120]))
        if name == "doc_image":
            try:
                data = base64.b64decode(str(args.get("base64") or ""), validate=True)
            except (binascii.Error, ValueError):
                return _no("« base64 » : les octets de l'image, en base64.")
            sent = File(one_line(str(args.get("nom") or ""), 120), "", data)
            got = await perform(self.kernel, words.IMAGE,
                                form(fixed={"via": docs.MCP, "tool": self.label}, name=sent.name),
                                by=self.account.handle, subject=str(r.p.id), via=SPACE, files=(sent,))
            if not got.ok:
                return _no(got.message)
            name = pages.added_image(self.kernel, r.p.id, got.seqs)
            # une image que l'état n'a pas gardée n'est pas « ajoutée » ; son nom vient de ce qui a été écrit
            return Outcome(words.IMAGE_ADDED.format(name=name)) if name else _no(words.IMAGE_LOST)
        path = pages.path_of(str(args.get("chemin") or ""))
        if name == "doc_lire":
            number = args.get("version")
            if isinstance(number, int) and not isinstance(number, bool) and number > 0:
                return _json(pages.read_version(sc, r, store, path, number))
            return _json(pages.read_page(sc, r, store, path))
        text, base = args.get("texte"), args.get("base")
        if not isinstance(text, str) or len(text) > docs.PAGE_CHARS:
            return _no(words.TOO_LONG)
        if not isinstance(base, int) or isinstance(base, bool) or base < 0:
            return _no(pages.BASE_NEEDED)
        pages.stale(sc, r, store, path, base)  # une version périmée : qui l'a écrite, par la règle des noms
        got = await perform(self.kernel, words.WRITE,
                            form(fixed={"via": docs.MCP, "tool": self.label}, path=path, text=text, base=base,
                                 word=one_line(str(args.get("mot") or ""), docs.WORD_MAX)),
                            by=self.account.handle, subject=str(r.p.id), via=SPACE)
        if got.ok and not got.deduped and not docs.landed(store, r.p.id, path, got.seqs):
            return _no(words.OVERTAKEN)  # écrite au même instant par quelqu'un d'autre : rien n'est écrasé
        return Outcome(got.message, is_error=not got.ok)


class DocsPoint:
    """Le point MCP d'une personne : sa porte (``app``)."""

    def __init__(self, kernel: Kernel, accounts: Accounts) -> None:
        self.kernel, self.accounts = kernel, accounts
        self._minute = SlidingWindow(PER_MINUTE, 60.0)
        self._writes = SlidingWindow(WRITES_PER_DAY, DAY_S)
        #: quand l'usage de chaque jeton a été noté pour la dernière fois (horloge monotone)
        self._noted: dict[int, float] = {}

    async def _host(self, scope: Mapping[str, Any]) -> Any:
        raw = bearer(scope)
        found = self.accounts.token(raw, tool=True)
        if found is None:
            return 401
        account, token_id = found
        key = f"compte:{account.id}"
        if not self._minute.allow(key=key):
            return 429
        now = time.monotonic()
        if now - self._noted.get(token_id, -USE_NOTED_S) >= USE_NOTED_S:
            # un jeton d'outil qui sert se voit servir (ADR 0292) : sinon il passe pour abandonné
            if len(self._noted) > 10_000:
                self._noted.clear()
            self._noted[token_id] = now
            await self.accounts.use_token(raw, tool=True)
        label = next((t.label for t in self.accounts.tokens(account.id) if t.id == token_id), "")
        return PersonHost(self.kernel, account, writes=self.accounts.token_client(token_id) != CLIENT_SCREEN,
                          label=one_line(label, docs.TOOL_MAX), spend=lambda: self._minute.allow(key=key),
                          write=lambda project: self._writes.allow(key=f"projet:{project}"))

    def app(self) -> Callable[..., Any]:
        return asgi(self._host)
