"""Téléphone, pour qui est connecté (ADR 0187, 0190) : ses téléphones (les jetons de son application), les messages
que l'application a lus dans ses notifications, rangés par conversation, les réponses que Mika y a proposées, sa
dernière position, et l'application elle-même à télécharger. Le fond de carte sur lequel sa position se montre est
celui de tous les écrans : il est servi avec la carte (``maps.py``, ADR 0229).

Tout est à elle seule : ses messages sont ceux de son adresse ou de sa personne, sa position celle que son téléphone
a donnée, ses téléphones les jetons ``mobile`` de son compte — qu'elle révoque elle-même. Les textes sont des contenus
(ce qu'on lui écrit, les noms) : lus à la demande, jamais dans la tranche.
"""

from __future__ import annotations

from typing import Any

from starlette.responses import FileResponse, Response
from starlette.routing import Route

from mika.adapters.web.accounts import CLIENT_MOBILE
from mika.app.me.api import Call, Denied, MeApiBase, missing
from mika.app.me.common import millis, snippet, texts_of
from mika.contracts import phone as phone_c
from mika.plugins import location as location_p
from mika.plugins import phone as phone_p
from mika.plugins.phone import SETTLED_STATES, UNDER_WAY, Msg, Offer, PhoneState, app_name
from mika.runtime.operations import audit

#: au plus tant de conversations, de messages d'un fil
LIMIT = 100
SNIPPET = 160
#: le nom sous lequel l'application se télécharge
APK_NAME = "mika.apk"


def _state(call: Call) -> PhoneState:
    return call.frame.state(phone_p.PHONE.name)


def _mine(call: Call) -> list[Msg]:
    """Ses messages : ceux de son adresse, ou de sa personne (le téléphone et le navigateur d'une même personne)."""
    me = call.me
    return [m for m in _state(call).messages.values() if m.handle == me.handle or m.person == me.person]


def _key(m: Msg) -> str:
    """Une conversation : son appli et son fil (``<appli>|<fil>``)."""
    return f"{m.source}|{m.thread}"


def _message_json(m: Msg, texts: dict[str, str]) -> dict[str, Any]:
    return {"id": phone_c.message_ref(m.seq), "at": millis(m.at), "own": m.own,
            "sender": texts.get(m.name_ref, "") if not m.own else "", "text": texts.get(m.text_ref, "")}


def _offer_json(o: Offer, texts: dict[str, str]) -> dict[str, Any]:
    return {"id": o.seq, "state": o.state, "at": millis(o.at), "expires": millis(o.expires), "decided_at": millis(o.decided_at),
            "reason": o.reason, "reply_to": phone_c.message_ref(o.reply_to) if o.reply_to else "",
            "text": texts.get(o.body_ref, "")}


def _offers(call: Call, keys: set[str]) -> list[Offer]:
    me = call.me
    return [o for o in _state(call).offers.values() if (o.handle == me.handle or o.person == me.person)
            and f"{o.source}|{o.thread}" in keys]


def _her(offers: list[Offer], received: Msg | None) -> dict[str, Any] | None:
    """La réponse de Mika qui compte pour une conversation : sa réponse en chemin (la plus récente), même si un message
    est arrivé depuis — elle attend ton geste ; sinon sa dernière réponse réglée, si elle a été proposée après le
    dernier message reçu (``received``) — une réponse à un message d'avant n'est plus une nouvelle ; sinon rien."""
    latest = sorted(offers, key=lambda o: -o.seq)
    chosen = next((o for o in latest if o.state in UNDER_WAY), None)
    if chosen is None:
        settled = next((o for o in latest if o.state in SETTLED_STATES), None)
        if settled is not None and (received is None or settled.at > received.at):
            chosen = settled
    if chosen is None:
        return None
    return {"state": chosen.state, "id": chosen.seq, "decided_at": millis(chosen.decided_at)}


# ── lire ──


async def conversations(call: Call) -> dict[str, Any]:
    """Ses conversations, la plus récente d'abord : l'appli, le titre (le groupe, sinon qui écrit), le dernier
    message, et la réponse de Mika qui y compte (``her`` : son sort, son ``seq``, quand il s'est réglé) — sa réponse
    en chemin, toujours, même si un message est arrivé depuis ; sinon sa dernière réponse réglée (partie, copiée,
    laissée, en échec, expirée…), seulement si elle a été proposée après le dernier message reçu ; sinon ``None``."""
    by: dict[str, list[Msg]] = {}
    for m in _mine(call):
        by.setdefault(_key(m), []).append(m)
    ordered = sorted(by.items(), key=lambda kv: -max(m.at for m in kv[1]))[:call.number("size", 50, high=LIMIT)]
    lasts = {k: max(ms, key=lambda m: (m.at, m.seq)) for k, ms in ordered}
    named = {k: next((m for m in sorted(ms, key=lambda m: -m.at) if not m.own and m.name_ref), None)
             for k, ms in ordered}
    texts = texts_of(call, [*(m.text_ref for m in lasts.values()), *(m.title_ref for m in lasts.values()),
                          *(m.name_ref for m in named.values() if m is not None)])
    offers: dict[str, list[Offer]] = {}
    for o in _offers(call, set(lasts)):
        offers.setdefault(f"{o.source}|{o.thread}", []).append(o)
    received = {k: max((m for m in ms if not m.own), key=lambda m: (m.at, m.seq), default=None) for k, ms in ordered}
    out = []
    for key, ms in ordered:
        last, who = lasts[key], named[key]
        title = texts.get(last.title_ref, "") if last.group else ""
        out.append({"key": key, "app": last.source, "app_name": app_name(last.source), "group": last.group,
                    "title": title or (texts.get(who.name_ref, "") if who is not None else ""),
                    "count": len(ms), "last_at": millis(last.at),
                    "last": {**_message_json(last, texts), "text": snippet(texts.get(last.text_ref, ""), SNIPPET)},
                    "her": _her(offers.get(key, []), received[key])})
    return {"items": out}


async def thread(call: Call) -> dict[str, Any]:
    key = call.arg("conversation", limit=400)
    found = sorted((m for m in _mine(call) if _key(m) == key), key=lambda m: (m.at, m.seq))
    if not found:
        raise missing()
    size = call.number("size", 50, high=LIMIT)
    shown = found[-size:]
    offers = sorted(_offers(call, {key}), key=lambda o: -o.seq)[:10]
    texts = texts_of(call, [*(m.text_ref for m in shown), *(m.name_ref for m in shown), shown[-1].title_ref,
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
    texts = texts_of(call, [fix.coords_ref, fix.label_ref])
    lat, _, lon = texts.get(fix.coords_ref, "").partition(",")
    try:
        coords = {"lat": float(lat), "lon": float(lon)}
    except ValueError:
        coords = None
    return {"known": True, "coords": coords, "label": texts.get(fix.label_ref, ""), "accuracy_m": fix.accuracy_m,
            "at": millis(fix.fixed_at)}


async def apk(call: Call) -> Response:
    """L'application du téléphone (ADR 0190), à qui est connecté : sa session, ou un jeton de son compte (celui de
    son téléphone, pour se mettre à jour) — jamais par un lien public."""
    path = call.api.apk
    if path is None or not path.is_file():
        raise Denied(404, "L'application n'est pas encore déposée sur le serveur.")
    return FileResponse(path, media_type="application/vnd.android.package-archive", filename=APK_NAME,
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


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


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    return [r("/phone/conversations", conversations), r("/phone/thread", thread), r("/phone/phones", phones),
            r("/phone/position", position), r("/phone/apk", apk, raw=True), r("/phone/revoke", revoke, write=True)]
