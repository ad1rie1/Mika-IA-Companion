"""Téléphone, pour qui est connecté (ADR 0187, 0190) : ses téléphones (les jetons de son application), les messages
que l'application a lus dans ses notifications, rangés par conversation, les réponses que Mika y a proposées, sa
dernière position, et l'application elle-même à télécharger.

Tout est à elle seule : ses messages sont ceux de son adresse ou de sa personne, sa position celle que son téléphone
a donnée, ses téléphones les jetons ``mobile`` de son compte — qu'elle révoque elle-même. Les textes sont des contenus
(ce qu'on lui écrit, les noms) : lus à la demande, jamais dans la tranche.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from starlette.responses import FileResponse, Response
from starlette.routing import Route

from mika.adapters.maps import NONE as NO_MAP
from mika.adapters.maps import MapUnavailable
from mika.adapters.web.accounts import CLIENT_MOBILE
from mika.app.moi import PREFIX, Call, Denied, MeApi, missing
from mika.contracts import phone as phone_c
from mika.plugins import location as location_p
from mika.plugins import phone as phone_p
from mika.plugins.phone import UNDER_WAY, Msg, Offer, PhoneState, app_name
from mika.runtime.operations import audit

#: au plus tant de conversations, de messages d'un fil
LIMIT = 100
SNIPPET = 160
#: le nom sous lequel l'application se télécharge
APK_NAME = "mika.apk"
#: d'une carte réglée qui ne se lit pas, ce qu'une personne lit : ce qui ne va pas (un fichier du serveur, une archive
#: à refaire, un serveur de carte muet) ne se dit qu'à qui peut y remédier, comme ``NOT_READY`` de ``carte.py``
MAP_NOT_READY = "La carte n'est pas encore prête sur ce serveur."


def _ms(us: int) -> int:
    return us // 1000 if us else 0


def _snippet(text: str) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= SNIPPET else flat[: SNIPPET - 1] + "…"


def _state(call: Call) -> PhoneState:
    return call.frame.state(phone_p.PHONE.name)


def _mine(call: Call) -> list[Msg]:
    """Ses messages : ceux de son adresse, ou de sa personne (le téléphone et le navigateur d'une même personne)."""
    me = call.me
    return [m for m in _state(call).messages.values() if m.handle == me.handle or m.person == me.person]


def _texts(call: Call, refs: Iterable[str]) -> dict[str, str]:
    wanted = [r for r in dict.fromkeys(refs) if r]
    store = call.port("store")
    return store.content(wanted) if wanted and store is not None else {}


def _key(m: Msg) -> str:
    """Une conversation : son appli et son fil (``<appli>|<fil>``)."""
    return f"{m.source}|{m.thread}"


def _message_json(m: Msg, texts: dict[str, str]) -> dict[str, Any]:
    return {"id": phone_c.message_ref(m.seq), "at": _ms(m.at), "own": m.own,
            "sender": texts.get(m.name_ref, "") if not m.own else "", "text": texts.get(m.text_ref, "")}


def _offer_json(o: Offer, texts: dict[str, str]) -> dict[str, Any]:
    return {"id": o.seq, "state": o.state, "at": _ms(o.at), "expires": _ms(o.expires), "decided_at": _ms(o.decided_at),
            "reason": o.reason, "reply_to": phone_c.message_ref(o.reply_to) if o.reply_to else "",
            "text": texts.get(o.body_ref, "")}


def _offers(call: Call, keys: set[str]) -> list[Offer]:
    me = call.me
    return [o for o in _state(call).offers.values() if (o.handle == me.handle or o.person == me.person)
            and f"{o.source}|{o.thread}" in keys]


# ── lire ──


async def conversations(call: Call) -> dict[str, Any]:
    """Ses conversations, la plus récente d'abord : l'appli, le titre (le groupe, sinon qui écrit), le dernier
    message, et une réponse de Mika en chemin."""
    by: dict[str, list[Msg]] = {}
    for m in _mine(call):
        by.setdefault(_key(m), []).append(m)
    ordered = sorted(by.items(), key=lambda kv: -max(m.at for m in kv[1]))[:call.number("size", 50, high=LIMIT)]
    lasts = {k: max(ms, key=lambda m: (m.at, m.seq)) for k, ms in ordered}
    named = {k: next((m for m in sorted(ms, key=lambda m: -m.at) if not m.own and m.name_ref), None)
             for k, ms in ordered}
    texts = _texts(call, [*(m.text_ref for m in lasts.values()), *(m.title_ref for m in lasts.values()),
                          *(m.name_ref for m in named.values() if m is not None)])
    pending = {f"{o.source}|{o.thread}": o for o in _offers(call, set(lasts)) if o.state in UNDER_WAY}
    out = []
    for key, ms in ordered:
        last, who = lasts[key], named[key]
        title = texts.get(last.title_ref, "") if last.group else ""
        out.append({"key": key, "app": last.source, "app_name": app_name(last.source), "group": last.group,
                    "title": title or (texts.get(who.name_ref, "") if who is not None else ""),
                    "count": len(ms), "last_at": _ms(last.at),
                    "last": {**_message_json(last, texts), "text": _snippet(texts.get(last.text_ref, ""))},
                    "her": {"state": pending[key].state, "id": pending[key].seq} if key in pending else None})
    return {"items": out}


async def thread(call: Call) -> dict[str, Any]:
    key = call.arg("conversation", limit=400)
    found = sorted((m for m in _mine(call) if _key(m) == key), key=lambda m: (m.at, m.seq))
    if not found:
        raise missing()
    size = call.number("size", 50, high=LIMIT)
    shown = found[-size:]
    offers = sorted(_offers(call, {key}), key=lambda o: -o.seq)[:10]
    texts = _texts(call, [*(m.text_ref for m in shown), *(m.name_ref for m in shown), shown[-1].title_ref,
                          *(o.body_ref for o in offers)])
    last = shown[-1]
    return {"key": key, "app": last.source, "app_name": app_name(last.source), "group": last.group,
            "title": texts.get(last.title_ref, "") if last.group else "",
            "messages": [_message_json(m, texts) for m in shown], "more": len(found) > size,
            "offers": [_offer_json(o, texts) for o in offers]}


async def phones(call: Call) -> dict[str, Any]:
    """Ses téléphones : les jetons de son application, révoqués compris (jamais leur secret)."""
    tokens = [t for t in call.api.accounts.tokens(call.me.account.id) if t.client == CLIENT_MOBILE]
    return {"items": [{"id": t.id, "label": t.label, "created_at": t.created_at * 1000,
                       "last_used": (t.last_used or 0) * 1000, "revoked": t.revoked, "push": t.push}
                      for t in sorted(tokens, key=lambda t: (t.revoked, -(t.last_used or 0), -t.id))],
            "apk": call.api.apk is not None and call.api.apk.is_file()}


async def position(call: Call) -> dict[str, Any]:
    """Sa dernière position, si son téléphone l'a donnée (l'application ouverte, qu'elle l'a permis) et que rien ne
    l'a effacée : ses coordonnées, le lieu, la précision, quand."""
    fix = location_p.last_for(call.frame.state(location_p.LOCATION.name), call.frame, call.me.handle)
    if fix is None:
        return {"known": False}
    texts = _texts(call, [fix.coords_ref, fix.label_ref])
    lat, _, lon = texts.get(fix.coords_ref, "").partition(",")
    try:
        coords = {"lat": float(lat), "lon": float(lon)}
    except ValueError:
        coords = None
    return {"known": True, "coords": coords, "label": texts.get(fix.label_ref, ""), "accuracy_m": fix.accuracy_m,
            "at": _ms(fix.fixed_at)}


async def apk(call: Call) -> Response:
    """L'application du téléphone (ADR 0190), à qui est connecté : sa session, ou un jeton de son compte (celui de
    son téléphone, pour se mettre à jour) — jamais par un lien public."""
    path = call.api.apk
    if path is None or not path.is_file():
        raise Denied(404, "L'application n'est pas encore déposée sur le serveur.")
    return FileResponse(path, media_type="application/vnd.android.package-archive", filename=APK_NAME,
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


# ── la carte de sa position (ADR 0193) ──
MAP = "/phone/map"
#: ce que le navigateur garde d'une tuile, d'une police ou d'une planche d'icônes : pour lui seul, un jour — sous une
#: adresse qui porte la version de la source (``?v=``, ou ``~<version>/`` pour les icônes : MapLibre ajoute leur fin
#: au chemin), qu'une autre source change ; les routes l'acceptent et l'ignorent
MAP_CACHE = "private, max-age=86400"
#: le début du segment de version d'une adresse d'icônes (« sprites/~1a2b3c4d5e6f/v4/light.json »)
VERSION_MARK = "~"


def _maps(call: Call) -> Any:
    maps = call.api.maps
    if maps is None or maps.config().source == NO_MAP:
        raise Denied(404, "Aucune carte n'est réglée : le plan dessiné.")
    return maps


def _map_trouble(call: Call, reason: str) -> str:
    return reason if call.me.operator else MAP_NOT_READY


async def map_info(call: Call) -> dict[str, Any]:
    """Ce que le client sait de la carte : prête ou non (et pourquoi), ses tuiles, sa zone, ses polices et ses icônes
    — toutes servies par ce serveur, jamais une adresse du dehors."""
    maps = call.api.maps
    if maps is None:
        return {"ready": False, "reason": "La carte n'est pas branchée sur ce serveur."}
    got = await maps.info()
    reason = got.reason
    if reason and maps.config().source != NO_MAP:  # rien de réglé n'est pas une panne : tout le monde le lit tel quel
        reason = _map_trouble(call, reason)
    base = PREFIX + MAP
    # la version de la source dans chaque adresse : le navigateur ne ressert pas, d'une carte remplacée (un autre
    # fichier, des images au lieu de vecteurs), ce qu'il gardait de l'autre
    query = f"?v={got.version}" if got.version else ""
    sprites = f"{base}/sprites/{VERSION_MARK}{got.version}/v4" if got.version else f"{base}/sprites/v4"
    return {"ready": got.ready, "reason": reason, "kind": got.kind, "minzoom": got.minzoom,
            "maxzoom": got.maxzoom, "bounds": list(got.bounds) if got.bounds is not None else None,
            "attribution": got.attribution, "tiles": f"{base}/tiles/{{z}}/{{x}}/{{y}}{query}",
            "glyphs": f"{base}/fonts/{{fontstack}}/{{range}}.pbf{query}" if got.fonts else None,
            "sprite": sprites if got.sprites else None}


async def map_tile(call: Call) -> Response:
    """Une tuile, telle que l'archive la garde (compressée : le navigateur l'ouvre) ; aucune là : 204, une tuile
    vide."""
    p = call.request.path_params
    try:
        tile = await _maps(call).tile(p["z"], p["x"], p["y"])
    except MapUnavailable as exc:
        raise Denied(503, _map_trouble(call, str(exc))) from None
    if tile is None:
        return Response(status_code=204, headers={"Cache-Control": MAP_CACHE})
    headers = {"Cache-Control": MAP_CACHE, "X-Content-Type-Options": "nosniff"}
    if tile.encoding:
        headers["Content-Encoding"] = tile.encoding
    return Response(tile.data, media_type=tile.media, headers=headers)


def _asset(path: Any, media: str) -> Response:
    if path is None:
        raise missing()
    return FileResponse(path, media_type=media, headers={"Cache-Control": MAP_CACHE, "X-Content-Type-Options": "nosniff"})


async def map_font(call: Call) -> Response:
    """Une plage de glyphes d'une police de la carte : la première de la pile qui est là."""
    p = call.request.path_params
    maps = _maps(call)
    found = next((got for font in str(p["fontstack"]).split(",")[:4]
                  if (got := maps.asset("fonts", f"{font.strip()}/{p['range']}")) is not None), None)
    return _asset(found, "application/x-protobuf")


async def map_sprite(call: Call) -> Response:
    """Une planche d'icônes de la carte (son image, ou ce qu'elle range où) ; le segment de version qui la précède
    (``~<version>/``) est accepté et ignoré."""
    rel = str(call.request.path_params["path"])
    if rel.startswith(VERSION_MARK):
        rel = rel.partition("/")[2]
    media = "application/json" if rel.endswith(".json") else "image/png" if rel.endswith(".png") else ""
    return _asset(_maps(call).asset("sprites", rel) if media else None, media)


# ── ses téléphones ──


async def revoke(call: Call) -> dict[str, Any]:
    """Révoquer un de ses téléphones : il ne vaut plus rien, ses connexions se ferment, ses messages restent."""
    wanted = call.number("id", 0, low=0)
    mine = {t.id: t for t in call.api.accounts.tokens(call.me.account.id) if t.client == CLIENT_MOBILE}
    if wanted not in mine:
        raise missing()
    if mine[wanted].revoked:
        raise Denied(409, "Ce téléphone est déjà révoqué.")
    await call.api.accounts.revoke_token(wanted)
    await audit(call.kernel, "moi.telephone_revoque", by=call.me.handle, subject_kind="jeton", subject=str(wanted))
    return {"ok": True, "message": "Révoqué : ce téléphone ne reçoit plus rien."}


def count(call: Call) -> int:
    """Pour la barre du haut : les réponses de Mika qui attendent ton geste sur le téléphone."""
    me = call.me
    return sum(1 for o in _state(call).offers.values() if (o.handle == me.handle or o.person == me.person)
               and o.state == phone_c.OFFERED)


def routes(api: MeApi) -> list[Route]:
    r = api.route
    return [r("/phone/conversations", conversations), r("/phone/thread", thread), r("/phone/phones", phones),
            r("/phone/position", position), r("/phone/apk", apk, raw=True), r("/phone/revoke", revoke, write=True),
            r(MAP, map_info), r(MAP + "/tiles/{z:int}/{x:int}/{y:int}", map_tile, raw=True),
            r(MAP + "/fonts/{fontstack}/{range}", map_font, raw=True),
            r(MAP + "/sprites/{path:path}", map_sprite, raw=True)]
