"""La documentation d'un projet, pour qui est connecté (ADR 0289) : l'arbre de ses pages, une page et son
historique, la recherche, ses images — et ses gestes : enregistrer une version, revenir à l'une d'elles, créer,
renommer, déplacer, supprimer une page, téléverser ou retirer une image.

**Aucune règle n'est d'ici**, comme pour le reste de ses projets (``projects.py``, dont vient ce qu'elle a d'un
projet) :

- **la lire** (``reads``) : le détail du projet, au niveau de ce qu'il écrit, et sa documentation — ouverte d'office
  à qui le projet appartient ; à une autre personne par ses lignes d'accès, hors de toute conversation
  (``todo.reach`` : seule une ligne qui la désigne ouvre) et par le canal de son client (``access.shares_docs``) ;
- **l'écrire** (``writes``) : la lire, et piloter le projet en modification, en être le propriétaire, ou s'occuper
  d'elle ;
- un projet qu'elle ne voit pas : introuvable (404) ; qu'elle voit sans lire sa documentation : 403, en mots.

Chaque geste passe par l'action que la faculté déclare pour lui (``inspect_docs`` ; auditée
``moi.projects.doc_…``), après cette garde. Une écriture nomme la version lue (``base``) : si la page a changé
depuis, 409, rien n'est écrasé. Un chemin est relatif à l'espace : absolu, ou qui remonte, il est refusé (400).
Ce que servent ces routes, le point MCP d'une personne le sert aussi, par les mêmes fonctions (``docs_mcp.py``).
Le contrat, route par route : ``docs/protocole-moi.md``, § 11.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from starlette.responses import Response
from starlette.routing import Route

from mika.app.domains.projects.api.projects import (
    BY_HER,
    BY_YOU,
    PATH,
    Reach,
    Scene,
    _author,
    _nameable,
    _opened,
    scene,
)
from mika.app.me.api import Call, Denied, MeApiBase, done, form, missing, person_of
from mika.app.me.common import millis
from mika.faculties.projects import access, docs, todo
from mika.faculties.projects import inspect_docs as words
from mika.faculties.projects.faculty import DOC_IMAGES_MAX, DOC_PAGES_MAX, DOC_VERSIONS_KEPT, written
from mika.vocab.access import STEER_EDIT
from mika.vocab.episodes import Kind

#: où vivent ses routes : sous la fiche du projet
DOC = PATH + "/{project:int}/documentation"
#: ce qu'une recherche rend, au plus
FOUND = 20

# ── Les refus, en mots ────────────────────────────────────────────────────

NO_DOCS = "Ce projet ne t'ouvre pas sa documentation : tu en lis le détail, pas ses pages ni ses images."
READ_ONLY = ("Tu lis la documentation de ce projet sans pouvoir l'écrire : l'écrire demande de le piloter en "
             "modification.")
BASE_NEEDED = "Dis la version que tu as lue : « base », son numéro (0 pour une page nouvelle)."
NO_VERSION = "Cette version de la page n'est plus gardée."
FORGOTTEN = "Le texte de cette version n'est plus là : il a été oublié."
VIA_WORDS = {docs.RUN: "pendant une exécution", docs.WEB: "dans le navigateur", docs.MCP: "un outil, par MCP",
             docs.CONSOLE: "depuis la console"}
LIMITS = {"page_chars": docs.PAGE_CHARS, "pages": DOC_PAGES_MAX, "versions": DOC_VERSIONS_KEPT,
          "path_chars": docs.PATH_MAX, "depth": docs.DEPTH_MAX, "word_chars": docs.WORD_MAX,
          "image_bytes": docs.IMAGE_BYTES, "images": DOC_IMAGES_MAX, "space_bytes": docs.SPACE_BYTES,
          "image_kinds": sorted(set(docs.MIMES.values()))}


# ── Ce qu'elle a de la documentation d'un projet ──────────────────────────


def reads(sc: Scene, r: Reach) -> bool:
    """Lit-elle la documentation de ce projet ? Son détail, au niveau de ce qu'il écrit ; puis : il est à elle, ou
    ses lignes d'accès lui donnent sa documentation hors de toute conversation et par le canal de son client."""
    p = r.p
    if not r.detail or written(p) > r.reader.level:
        return False
    if r.own:
        return True
    return todo.reach(p, sc.person, sc.world).documentation \
        and access.shares_docs(p, sc.audience, Kind.REPLY, sc.frame)


def writes(sc: Scene, r: Reach) -> bool:
    """L'écrit-elle ? La lire, et : le piloter en modification, en être le propriétaire, ou s'occuper d'elle."""
    return reads(sc, r) and (r.own or sc.keeper or r.steer == STEER_EDIT)


def guard(sc: Scene, r: Reach, *, write: bool = False) -> None:
    """La garde de toute lecture et de toute écriture de la documentation, pour une route comme pour le point MCP."""
    if not reads(sc, r):
        raise Denied(403, NO_DOCS)
    if write and not writes(sc, r):
        raise Denied(403, READ_ONLY)


def _docs(call: Call, *, write: bool = False) -> tuple[Scene, Reach]:
    sc, r = _opened(call)
    guard(sc, r, write=write)
    return sc, r


def path_of(raw: str, field: str = "path") -> str:
    """Un chemin de page tel qu'on l'a écrit, s'il ne sort pas de l'espace ; sinon 400."""
    path = docs.page_path(raw.strip())
    if path is None:
        raise Denied(400, words.BAD_PATH, {field: "un chemin de page, relatif, en « .md »"})
    return path


# ── Ce qu'on en sert ──────────────────────────────────────────────────────


def _by(sc: Scene, r: Reach, x: Any) -> dict[str, Any]:
    """Qui a écrit une version ou ajouté une image : sa sorte et ses mots (``projects._author`` : une autre personne
    n'est nommée que si elle a le droit de le savoir), et par où — un outil par MCP se dit, avec le nom de son
    jeton."""
    tool = getattr(x, "tool", "")
    # le nom d'un jeton est celui que sa personne lui a donné : il ne se sert qu'à elle, ou à qui a le droit de la
    # nommer (ADR 0292) — la même règle que son nom
    person = person_of(sc.frame, x.by) if x.by else ""
    named = bool(person) and (person == sc.person or _nameable(sc, person, written(r.p)))
    return {**_author(sc, {}, x.author, x.by, written(r.p)), "via": x.via, "via_label": VIA_WORDS.get(x.via, ""),
            "tool": tool if x.via == docs.MCP and named else ""}


def stale(sc: Scene, r: Reach, store: Any, path: str, base: int) -> None:
    """Le refus d'une écriture partie d'une version périmée (409), composé ici : qui a écrit la dernière version n'y
    est nommé — et son jeton — que par la règle des autres auteurs (``_by``). L'action le refuse aussi, sans nom."""
    x = docs.page(store, r.p.id, path)
    if x is None or not base or base == x.version:
        return
    by = _by(sc, r, x)
    who = "par elle" if by["author_kind"] == BY_HER else "par toi" if by["author_kind"] == BY_YOU else \
        f"par {by['author']}"
    if by["tool"]:
        who += f", par MCP (« {by['tool']} »)"
    raise Denied(409, words.MOVED_ON.format(version=x.version, who=who))


def added_image(kernel: Any, project: int, seqs: Any) -> str:
    """Le nom de l'image que ces événements ont ajoutée et que l'état garde ; vide : rien n'a été gardé (ADR 0292).
    Lu dans le journal et dans l'état, jamais dans le message d'une réponse."""
    mind = kernel.mind
    p = mind.frame().state("projects").projects.get(project)
    for raw in mind.store.get_events(list(seqs or ())):
        e = mind.decode(raw)
        if e.type.name == docs.DOC_IMAGE_ADDED.name and p is not None \
                and docs.image_kept(p.docs, e.data.name, e.data.file):
            return str(e.data.name)
    return ""


def page_json(sc: Scene, r: Reach, x: docs.Page) -> dict[str, Any]:
    return {"path": x.path, "name": x.path.rsplit("/", 1)[-1], "folder": x.path.rpartition("/")[0],
            "title": x.title, "version": x.version, "at": millis(x.at), "created_at": millis(x.created_at),
            "chars": x.chars, "images": list(x.images), **_by(sc, r, x)}


def version_json(sc: Scene, r: Reach, x: docs.Version, current: int) -> dict[str, Any]:
    return {"n": x.n, "at": millis(x.at), "word": x.word, "restored": x.restored, "chars": x.chars,
            "current": x.n == current, **_by(sc, r, x)}


def image_json(sc: Scene, r: Reach, x: Any, used: Mapping[str, list[str]]) -> dict[str, Any]:
    return {"name": x.name, "path": docs.IMAGES_DIR + x.name, "size": x.size, "mime": x.mime, "at": millis(x.at),
            "used_by": used.get(x.name, []), **_by(sc, r, x)}


def space(sc: Scene, r: Reach, store: Any) -> dict[str, Any]:
    """L'espace en entier : ses droits, ses bornes, l'arbre de ses pages (à plat, par chemin ; ses dossiers à côté),
    ses images."""
    p = r.p
    pages = docs.tree(store, p.id)
    folders = sorted({"/".join(parts[:i]) for parts in (x.path.split("/")[:-1] for x in pages)
                      for i in range(1, len(parts) + 1)})
    used: dict[str, list[str]] = {}
    for x in pages:
        for name in x.images:
            used.setdefault(name, []).append(x.path)
    return {"project": p.id, "rights": {"read": True, "write": writes(sc, r)}, "limits": LIMITS,
            "pages": [page_json(sc, r, x) for x in pages], "folders": folders,
            "images": [image_json(sc, r, i, used) for i in sorted(p.docs.images, key=lambda i: -i.at)],
            "space_used": docs.space_used(p.docs)}


def read_page(sc: Scene, r: Reach, store: Any, path: str) -> dict[str, Any]:
    """Une page : son Markdown, sa dernière modification (qui, par où, quand), ce qu'elle cite."""
    x = docs.page(store, r.p.id, path)
    if x is None:
        raise missing()
    text = docs.text_of(store, x.seq)
    return {**page_json(sc, r, x), "text": text or "", "forgotten": text is None,
            "can": {"write": writes(sc, r)}}


def history(sc: Scene, r: Reach, store: Any, path: str) -> dict[str, Any]:
    x = docs.page(store, r.p.id, path)
    if x is None:
        raise missing()
    return {"path": x.path, "version": x.version, "kept": DOC_VERSIONS_KEPT,
            "versions": [version_json(sc, r, v, x.version) for v in docs.versions(store, r.p.id, path)]}


def read_version(sc: Scene, r: Reach, store: Any, path: str, number: int) -> dict[str, Any]:
    x = docs.page(store, r.p.id, path)
    v = docs.version(store, r.p.id, path, number) if x is not None else None
    if x is None or v is None:
        raise missing()
    text = docs.text_of(store, v.seq)
    return {"path": x.path, **version_json(sc, r, v, x.version), "text": text or "", "forgotten": text is None}


def search(sc: Scene, r: Reach, store: Any, said: str) -> dict[str, Any]:
    out = []
    for x in docs.found(store, r.p.id, said, FOUND):
        text = docs.text_of(store, x.seq) or ""
        out.append({**page_json(sc, r, x), "excerpt": docs.excerpt(text, said) if text else ""})
    return {"q": said, "items": out}


# ── Lire ──────────────────────────────────────────────────────────────────


def _store(call: Call) -> Any:
    return call.kernel.mind.store


async def overview(call: Call) -> dict[str, Any]:
    sc, r = _docs(call)
    return space(sc, r, _store(call))


async def one_page(call: Call) -> dict[str, Any]:
    sc, r = _docs(call)
    return read_page(sc, r, _store(call), path_of(call.arg("path", limit=docs.PATH_MAX)))


async def page_history(call: Call) -> dict[str, Any]:
    sc, r = _docs(call)
    return history(sc, r, _store(call), path_of(call.arg("path", limit=docs.PATH_MAX)))


async def one_version(call: Call) -> dict[str, Any]:
    sc, r = _docs(call)
    return read_version(sc, r, _store(call), path_of(call.arg("path", limit=docs.PATH_MAX)),
                        call.number("n", 0, low=0))


async def find(call: Call) -> dict[str, Any]:
    sc, r = _docs(call)
    return search(sc, r, _store(call), call.arg("q", limit=120))


async def images(call: Call) -> dict[str, Any]:
    sc, r = _docs(call)
    got = space(sc, r, _store(call))
    return {"items": got["images"], "space_used": got["space_used"], "limits": LIMITS}


async def image(call: Call) -> Response:
    """Les octets d'une image, à qui peut lire la documentation — servie comme une image et rien d'autre."""
    _, r = _docs(call)
    found = docs.image_at(r.p.docs, call.arg("name", limit=120))
    port = call.port(docs.PORT)
    data = await port.read(found.file, docs.IMAGE_BYTES) if found is not None and port is not None else None
    if found is None or data is None:
        raise missing()
    return Response(data, media_type=docs.mime_of(found.name), headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Content-Disposition": f'inline; filename="{found.name}"'})


# ── Écrire ────────────────────────────────────────────────────────────────


def _base(call: Call) -> int:
    if call.data.get("base") is None and call.request.query_params.get("base") is None:
        raise Denied(400, BASE_NEEDED, {"base": "valeur requise"})
    return call.number("base", 0, low=0)


async def _act(call: Call, r: Reach, key: str, fixed: Mapping[str, Any] | None = None,
               **values: Any) -> dict[str, Any]:
    """L'action de la faculté, au nom de la personne ; ``fixed`` : ce que la route pose et que personne ne tape."""
    hidden = {"via": docs.WEB, **{k: str(v) for k, v in (fixed or {}).items()}}
    return done(await call.act(key, form(fixed=hidden, **values), subject=str(r.p.id)))


async def _write(call: Call, r: Reach, path: str, base: int, fixed: Mapping[str, Any] | None = None,
                 **values: Any) -> dict[str, Any]:
    """Une version de plus, partie de ``base`` — et, une fois écrite, la preuve qu'elle est bien la dernière : deux
    écritures arrivées au même instant ne valent pas toutes deux, et la seconde doit le savoir (409)."""
    hidden = {"via": docs.WEB, **{k: str(v) for k, v in (fixed or {}).items()}}
    # la redite d'un envoi déjà fait (une coupure, puis le client réessaie avec la même clé) ne se juge pas contre la
    # version que le premier envoi a écrite : l'action la reconnaît et ne refait rien (``deduped``)
    if not call.repeated():
        stale(scene(call), r, _store(call), path, base)
    outcome = await call.act(words.WRITE, form(fixed=hidden, path=path, base=base, **values), subject=str(r.p.id))
    got = done(outcome)
    if not outcome.deduped and not docs.landed(_store(call), r.p.id, path, outcome.seqs):
        raise Denied(409, words.OVERTAKEN)
    return {**got, "path": path, "version": base + 1}


async def save(call: Call) -> dict[str, Any]:
    """Enregistrer une version (``base`` : celle qu'on a lue ; 0 : une page nouvelle)."""
    _, r = _docs(call, write=True)
    path = path_of(call.arg("path", limit=docs.PATH_MAX))
    base = _base(call)
    return await _write(call, r, path, base, text=call.arg("text", limit=docs.PAGE_CHARS),
                        word=call.arg("word", limit=docs.WORD_MAX))


async def restore(call: Call) -> dict[str, Any]:
    """Revenir à une version : son texte redevient celui de la page, dans une version de plus."""
    _, r = _docs(call, write=True)
    path = path_of(call.arg("path", limit=docs.PATH_MAX))
    base, number = _base(call), call.number("version", 0, low=0)
    v = docs.version(_store(call), r.p.id, path, number)
    if v is None:
        raise Denied(404, NO_VERSION)
    text = docs.text_of(_store(call), v.seq)
    if text is None:
        raise Denied(409, FORGOTTEN)
    return await _write(call, r, path, base, fixed={"restored": number}, text=text,
                        word=f"Retour à la version {number}")


async def move(call: Call) -> dict[str, Any]:
    """Renommer ou déplacer : un autre chemin, ses versions la suivent."""
    _, r = _docs(call, write=True)
    path, to = path_of(call.arg("path", limit=docs.PATH_MAX)), path_of(call.arg("to", limit=docs.PATH_MAX), "to")
    return {**await _act(call, r, words.MOVE, path=path, to=to), "path": to}


async def remove(call: Call) -> dict[str, Any]:
    _, r = _docs(call, write=True)
    return await _act(call, r, words.REMOVE, path=path_of(call.arg("path", limit=docs.PATH_MAX)))


async def upload(call: Call) -> dict[str, Any]:
    """Téléverser une image (``multipart/form-data``, un fichier) : elle rejoint les images de l'espace."""
    _, r = _docs(call, write=True)

    async def make() -> dict[str, Any]:
        outcome = await call.act(words.IMAGE, form(fixed={"via": docs.WEB}, name=call.arg("name", limit=120)),
                                 subject=str(r.p.id))
        got = done(outcome)
        # son nom se lit dans ce qui a été écrit, pas dans le message ; et l'ajout dit vrai : une image que l'état
        # n'a pas gardée n'est pas « ajoutée » (409)
        name = added_image(call.kernel, r.p.id, outcome.seqs)
        if not name and not outcome.deduped:
            raise Denied(409, words.IMAGE_LOST)
        # un envoi redit dont la première réponse n'est plus en mémoire (un redémarrage) : rien n'a été refait, et
        # son nom ne se devine pas — il se lit dans la liste des images
        return {**got, "name": name, "path": docs.IMAGES_DIR + name if name else ""}

    # un envoi redit (la même clé d'envoi) rend la même réponse, avec le même nom, sans rien refaire
    return await call.once(make)


async def drop_image(call: Call) -> dict[str, Any]:
    _, r = _docs(call, write=True)
    return await _act(call, r, words.IMAGE_REMOVE, name=call.arg("name", limit=120))


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    return [r(DOC, overview), r(DOC + "/page", one_page), r(DOC + "/historique", page_history),
            r(DOC + "/version", one_version), r(DOC + "/chercher", find), r(DOC + "/images", images),
            r(DOC + "/image", image, raw=True),
            r(DOC + "/page/enregistrer", save, write=True, upload=True),
            r(DOC + "/page/revenir", restore, write=True), r(DOC + "/page/deplacer", move, write=True),
            r(DOC + "/page/supprimer", remove, write=True),
            r(DOC + "/image/televerser", upload, write=True, upload=True),
            r(DOC + "/image/retirer", drop_image, write=True)]
