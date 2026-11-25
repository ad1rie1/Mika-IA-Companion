"""Ses services MCP, pour qui est connecté (ADR 0192) : ceux qu'elle a branchés, à elle — leur état, leurs outils,
leurs lignes d'accès — ; en brancher un, le tester, choisir ses outils, le régler, le retirer. Et ceux qu'une autre
personne lui partage (ADR 0188), en lecture : à quoi ils servent, leur état, leurs outils servis, son niveau, à qui ils
sont — jamais leur adresse ni leurs en-têtes.

Un service branché ici est à la personne (``McpServer.owner``) et naît avec une seule ligne d'accès, la sienne
(un outil qui lit : elle s'en sert ; un outil qui agit : elle lui demande ; ce qu'elle y lit reste une confidence),
la ligne par défaut fermée ; ses outils arrivent coupés, à choisir un par un (ADR 0129). Ce que Mika en offre reste
calculé par le moteur des droits. Une personne branche un service **distant**, par son adresse https ; lancer une
commande sur la machine (un service local) reste aux opérateurs, dans la console. La console voit tous les services.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import ValidationError
from starlette.routing import Route

from mika.adapters.mcp.config import McpServer
from mika.app.domains.tools.settings import ToolsSettings
from mika.app.me.api import Call, Denied, MeApiBase, missing, refused
from mika.app.me.common import own_room
from mika.app.me.hosts import public_only, url_host
from mika.contracts import identity as identity_c
from mika.contracts import self_ as self_c
from mika.runtime.operations import audit
from mika.vocab.access import (
    KEEP_WORDS,
    PERSON,
    POLICY_WORDS,
    SELF,
    SHARE_READ,
    SHARE_USE,
    SOURCE_WORDS,
    SOURCE_WORDS_OTHER,
    when_words,
    who_words,
)

#: le nom d'un service : il entre dans le nom de ses outils (``mcp_<nom>_<outil>``)
NAME = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
#: ce qu'une personne règle d'un de ses services
FIELDS = ("purpose", "when_to_use", "enabled", "url", "secret_headers")
#: retirer ses en-têtes gardés (``values.clear_headers``) : vide, un champ secret les garde (ADR 0236)
CLEAR_HEADERS = "clear_headers"
#: ce qu'on choisit pour un outil (ADR 0129) : coupé, servi en lecture, servi en action
CHOICES = ("non", "lecture", "action")
#: le port d'une adresse qui n'en dit pas
DEFAULT_PORTS = {"https": 443, "http": 80}
#: ce que dit le refus d'une adresse changée sans ses en-têtes (ADR 0236)
HEADERS_FOLLOW = ("L'adresse a changé : redonne ses en-têtes secrets, ou retire-les. Ils ne partent pas vers un "
                  "autre serveur.")
HEADERS_FIELD = "à redonner : l'adresse a changé (ou à retirer)"


def _port(call: Call) -> Any:
    port = call.port("mcp")
    if port is None or call.api.settings is None:
        raise Denied(503, "Les services ne sont pas branchés.")
    return port


def mine(call: Call) -> dict[str, McpServer]:
    """Ses services : ceux qui sont à son nom."""
    if call.api.settings is None:
        return {}
    me = PERSON + call.me.person
    return {n: s for n, s in call.api.settings.of(ToolsSettings).mcp().servers.items() if s.owner == me}


def shared(spec: McpServer) -> dict[str, tuple[str, Any]]:
    """Les partages d'un service (ADR 0188, 0192) : chaque ligne d'accès d'une seule personne (« personne:<clé> ») autre
    que son propriétaire — celle qu'un partage ajoute —, par personne : son niveau (lire : ses outils qui lisent ; s'en
    servir : aussi ceux qui agissent) et sa ligne. Un partage n'en écrit qu'une ; s'il y en avait plusieurs, la
    dernière. La seule lecture de cette règle : ce qu'on lui partage (``received``), Paramètres › Partages et la
    console (``sharing.py::service_shares``), la fiche d'une personne la lisent ici."""
    out: dict[str, tuple[str, Any]] = {}
    for line in spec.access:
        if len(line.who) == 1 and line.who[0].startswith(PERSON) and line.who[0] != spec.owner:
            out[line.who[0]] = (SHARE_USE if line.act != "non" else SHARE_READ, line)
    return out


def received(call: Call) -> dict[str, tuple[McpServer, str, Any]]:
    """Les services qu'une autre personne lui partage (ADR 0188, 0192) : à quelqu'un d'autre qu'elle, avec une ligne
    d'accès pour elle seule (``shared``). Par nom : le service, son niveau et sa ligne."""
    if call.api.settings is None:
        return {}
    me = PERSON + call.me.person
    out: dict[str, tuple[McpServer, str, Any]] = {}
    for n, s in call.api.settings.of(ToolsSettings).mcp().servers.items():
        if s.owner and s.owner != me and me in (lines := shared(s)):
            out[n] = (s, *lines[me])
    return out


def _service(call: Call, name: str) -> McpServer:
    found = mine(call).get(name)
    if found is None:
        raise missing()
    return found


def _line_json(a: Any, call: Call) -> dict[str, Any]:
    """Une ligne d'accès, en codes et en mots ; ``mine`` : elle ne désigne que toi (ta ligne, pas un partage) — le
    client la reconnaît ainsi, jamais à un nom (deux personnes peuvent porter le même)."""
    frame = call.frame

    def name(key: str) -> str:
        view = frame.get(identity_c.IDENTITY(key))
        return getattr(view, "name", "") or (call.me.name if key == call.me.person else key)

    sources = SOURCE_WORDS if call.me.owner else SOURCE_WORDS_OTHER
    return {"who": who_words(a.who, name, sources=sources) if a.who else "", "when": when_words(a.when),
            "mine": tuple(a.who) == (PERSON + call.me.person,),
            "read": a.read,
            "act": a.act, "keep": a.keep, "read_words": POLICY_WORDS.get(a.read, a.read),
            "act_words": POLICY_WORDS.get(a.act, a.act), "keep_words": KEEP_WORDS.get(a.keep, a.keep),
            "tools": list(a.tools)}


def _service_json(call: Call, name: str, spec: McpServer) -> dict[str, Any]:
    st = call.port("mcp").status(name)
    live = {t.remote: t for t in st.live} if st is not None else {}
    reviews = st.reviews if st is not None else {}
    tools = []
    for remote in sorted({*live, *reviews}):
        r, t = reviews.get(remote), live.get(remote)
        tools.append({"remote": remote, "name": r.name if r is not None else "",
                      "description": (t.description if t is not None else "") or (r.description if r else ""),
                      "choice": (r.nature if r is not None and r.enabled else "non") if r is not None else "",
                      "new": r is None, "changed": st is not None and remote in st.changed})
    return {"name": name, "purpose": spec.purpose, "when_to_use": spec.when_to_use, "enabled": spec.enabled,
            "url": spec.url, "headers": bool(spec.secret_headers.strip()),
            "state": st.state if st is not None else "jamais", "detail": st.detail if st is not None else "",
            "tools": tools,
            "access": [_line_json(a, call) for a in (st.access if st is not None else ())],
            "default": _line_json(st.default, call) if st is not None else None}


def _owner_name(call: Call, owner: str) -> str:
    """À qui est un service, en mots : une personne par son nom, elle par le sien."""
    if owner == SELF:
        return self_c.name_of(call.frame.get(self_c.PERSONA))
    key = owner[len(PERSON):] if owner.startswith(PERSON) else owner
    view = call.frame.get(identity_c.IDENTITY(key))
    return getattr(view, "name", "") or key


def _received_json(call: Call, name: str, spec: McpServer, level: str, line: Any) -> dict[str, Any]:
    """Un service qu'on lui partage, en lecture : à quoi il sert, son état, ses outils servis (ni coupés, ni changés
    depuis leur choix — suspendus —, ni retirés par le service), son niveau, sa ligne (ce qu'elle en fait pour elle) et
    à qui il est. Ni son adresse, ni ses en-têtes, ni le détail d'une panne (il peut nommer l'adresse)."""
    st = call.port("mcp").status(name)
    reviews = st.reviews if st is not None else {}
    off = {*st.changed, *st.missing} if st is not None else set()
    tools = [{"remote": remote, "name": r.name, "description": r.description, "choice": r.nature}
             for remote, r in sorted(reviews.items()) if r.enabled and remote not in off]
    return {"name": name, "purpose": spec.purpose, "enabled": spec.enabled,
            "state": st.state if st is not None else "jamais", "tools": tools, "level": level,
            "line": _line_json(line, call), "owner_name": _owner_name(call, spec.owner)}


async def services(call: Call) -> dict[str, Any]:
    """Ses services (``items``), et ceux qu'on lui partage (``received``, en lecture)."""
    port = call.port("mcp")
    if port is None:
        return {"plugged": False, "items": [], "received": []}
    return {"plugged": True, "items": [_service_json(call, n, s) for n, s in sorted(mine(call).items())],
            "received": [_received_json(call, n, s, level, line)
                         for n, (s, level, line) in sorted(received(call).items())]}


async def plug(call: Call) -> dict[str, Any]:
    """Brancher un service distant à soi : son nom, à quoi il sert, son adresse https, ses en-têtes (un secret). Redit
    avec la même clé d'envoi, rien ne se refait."""
    return await call.once(lambda: _plug(call))


async def _plug(call: Call) -> dict[str, Any]:
    port = _port(call)
    own_room(call, len(mine(call)))
    name = call.arg("name", limit=24).strip().lower()
    if not NAME.fullmatch(name):
        raise Denied(400, "Un nom court : des minuscules, chiffres et _, en commençant par une lettre.",
                     {"name": "des minuscules, chiffres et _"})
    url = call.arg("url", limit=500).strip()
    if not url.lower().startswith("https://"):
        raise Denied(400, "Une adresse https (l'adresse MCP « streamable HTTP » du service).",
                     {"url": "une adresse https://…"})
    await public_only(call, {"url": url_host(url)})
    person = PERSON + call.me.person
    spec = {"purpose": call.arg("purpose", limit=1024).strip(), "when_to_use": call.arg("when_to_use", limit=1024),
            "transport": "distant", "url": url, "auth": "aucune",
            "secret_headers": call.arg("headers", limit=8000), "owner": person,
            # sa seule ligne : elle (ADR 0192) ; la ligne par défaut reste fermée
            "access": [{"who": [person], "read": "seule", "act": "carte", "keep": "prive"}]}
    try:
        McpServer.model_validate(spec)
        await port.plug(name, spec)
    except (ValidationError, ValueError) as exc:
        raise refused(exc) from None
    await audit(call.kernel, "moi.service_branche", by=call.me.handle, subject_kind="serveur", subject=name)
    return {"ok": True, "message": f"« {name} » branché : teste-le, puis choisis ses outils.", "name": name}


async def test(call: Call) -> dict[str, Any]:
    name = call.arg("name", limit=24)
    _service(call, name)
    call.probe()
    ok, said = await _port(call).test(name)
    return {"ok": ok, "message": said}


async def tools(call: Call) -> dict[str, Any]:
    """Choisir ses outils (ADR 0129) : ``{"<outil>": "non" | "lecture" | "action"}`` — coupé, ou servi. Un outil
    nouveau ou changé se décide tel que le serveur le propose maintenant (``decide``) ; un outil déjà choisi change de
    choix sur sa ligne (``review``), sa description gardée."""
    name = call.arg("name", limit=24)
    _service(call, name)
    raw = call.data.get("choices")
    if not isinstance(raw, dict) or not all(isinstance(v, str) and v in CHOICES for v in raw.values()):
        raise Denied(400, "« choices » : pour chaque outil, non, lecture ou action.")
    port = _port(call)
    st = port.status(name)
    fresh = set(st.new) | set(st.changed) if st is not None else set()
    reviews = st.reviews if st is not None else {}
    choices = {str(k)[:200]: v for k, v in raw.items()}
    try:
        done = await port.decide(name, {k: v for k, v in choices.items() if k in fresh}, by=call.me.handle) \
            if any(k in fresh for k in choices) else {}
        for remote, choice in choices.items():
            if remote in fresh:
                continue
            if remote not in reviews:
                raise ValueError(f"« {remote[:60]} » : le service ne propose pas cet outil")
            await port.review(name, remote, enabled=choice != "non", nature="action" if choice == "action" else
                              "lecture", description=reviews[remote].description, by=call.me.handle)
            done = {**done, remote: choice}
    except ValueError as exc:
        raise Denied(400, str(exc)) from None
    await audit(call.kernel, "moi.service_outils", by=call.me.handle, subject_kind="serveur", subject=name)
    return {"ok": True, "message": "Ses outils sont choisis.", "decided": done}


def _origin(url: str) -> tuple[str, str, int | None]:
    """Où une adresse mène : son schéma, son hôte, son port (celui du schéma s'il n'en dit pas)."""
    try:
        parts = urlsplit(url.strip())
        scheme = parts.scheme.lower()
        return scheme, (parts.hostname or "").lower(), parts.port or DEFAULT_PORTS.get(scheme)
    except ValueError:  # un port illisible : l'adresse entière tient lieu d'hôte, comparée telle quelle
        return "", url.strip().lower(), None


def _headers_follow(spec: McpServer, changes: dict[str, Any]) -> dict[str, Any]:
    """Des en-têtes gardés ne partent jamais vers un autre serveur (ADR 0236) : une adresse qui mène ailleurs (un autre
    hôte, schéma ou port) les redemande — redonnés, ou retirés — ; sinon 400 sur leur champ, comme le mot de passe
    d'une boîte (``domains/mail/box_settings.py::_kept_secrets``). Sans en-têtes gardés, rien ne se redemande. Jugé sur la fiche relue sous
    le verrou des réglages (``McpSettingsStore.settle``)."""
    moved = "url" in changes and _origin(str(changes["url"])) != _origin(spec.url)
    if moved and spec.secret_headers.strip() and "secret_headers" not in changes:
        raise Denied(400, HEADERS_FOLLOW, {"secret_headers": HEADERS_FIELD})
    return changes


async def save(call: Call) -> dict[str, Any]:
    """Régler un de ses services : à quoi il sert, quand y penser, actif, son adresse, ses en-têtes (laissés vides,
    ils restent ; ``clear_headers`` les retire). Une adresse qui mène ailleurs redemande ses en-têtes gardés
    (ADR 0236)."""
    name = call.arg("name", limit=24)
    _service(call, name)
    raw = call.data.get("values")
    if not isinstance(raw, dict) or set(raw) - {*FIELDS, CLEAR_HEADERS}:
        raise Denied(400, f"« values » : {', '.join((*FIELDS, CLEAR_HEADERS))}.")
    clear = raw.get(CLEAR_HEADERS, False)
    if not isinstance(clear, bool):
        raise Denied(400, "« clear_headers » : vrai ou faux.", {CLEAR_HEADERS: "vrai ou faux"})
    changes = {k: v for k, v in raw.items() if k != CLEAR_HEADERS and not (k == "secret_headers" and not v)}
    if clear and "secret_headers" not in changes:
        changes["secret_headers"] = ""  # retirés : rien ne partira plus, ni ici ni ailleurs
    if "url" in changes and not str(changes["url"]).lower().startswith("https://"):
        raise Denied(400, "Une adresse https.", {"url": "une adresse https://…"})
    if "url" in changes:
        await public_only(call, {"url": url_host(str(changes["url"]))})
    try:
        await _port(call).settle(name, lambda spec: _headers_follow(spec, changes))
    except (ValidationError, ValueError) as exc:
        raise refused(exc) from None
    await audit(call.kernel, "moi.service", by=call.me.handle, subject_kind="serveur", subject=name)
    return {"ok": True, "message": "Service réglé."}


async def remove(call: Call) -> dict[str, Any]:
    """Retirer un de ses services : il n'est plus joint ni offert ; ce qu'elle y a lu reste dans sa vie."""
    name = call.arg("name", limit=24)
    _service(call, name)
    try:  # sa fiche retirée sous ``Settings.writing`` (``McpSettingsStore.remove``), puis ses sessions fermées
        await _port(call).unplug(name)
    except ValueError as exc:
        raise refused(exc) from None
    await audit(call.kernel, "moi.service_retire", by=call.me.handle, subject_kind="serveur", subject=name)
    return {"ok": True, "message": "Service retiré."}


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    return [r("/mcp/services", services), r("/mcp/plug", plug, write=True), r("/mcp/test", test, write=True),
            r("/mcp/tools", tools, write=True), r("/mcp/save", save, write=True), r("/mcp/remove", remove, write=True)]
