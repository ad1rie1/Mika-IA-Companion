"""Les portes à clé du transport web (ADR 0213) : les réveils par API (``/api/wake/…``), l'extension Teams
(``/api/teams/…``) et l'application du téléphone (``/api/phone/…``).

Chaque porte garde l'ordre de ses contrôles : 404 si elle n'est pas branchée, puis l'origine, puis l'adresse qui a trop
échoué (``door_refusal``, Teams et réveils), puis la clé ; le téléphone passe par son jeton (``phone_of``,
``adapters/web/auth_routes.py``). Ce que la porte a décidé se dit en HTTP par une seule table (``GATE_STATUS``,
``gate_reply``). La machinerie (empreintes, fenêtres glissantes, nettoyage) est dans ``adapters/web/gate.py`` ; la
réponse de clé reste à chaque porte. ``door_routes`` rend leurs huit routes — dont la boîte d'envoi de Teams en
direct, une WebSocket (``/api/teams/live``, ADR 0251) —, que ``create_app`` (``adapters/web/app.py``) monte à leur
place.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from mika.adapters.web.accounts import Accounts
from mika.adapters.web.auth_routes import phone_of
from mika.adapters.web.body import PayloadTooLarge, json_object, parsed, read_bounded
from mika.adapters.web.gate import KEY_MAX, SlidingWindow, token_digest
from mika.adapters.web.session import bearer, native_token
from mika.ports import gate as gate_p
from mika.ports import phone as phone_p
from mika.ports import teams as teams_p
from mika.ports import wakeup as wakeup_p

if TYPE_CHECKING:
    from mika.adapters.web.app import WebConfig

#: un réveil par API (ADR 0068) : la taille d'une requête au plus (le JSON d'un service, GitHub par exemple, ADR 0117),
#: et les échecs d'authentification tolérés par IP
WAKE_MAX_BYTES = 512 * 1024
WAKE_FAILURES = (20, 60.0)
#: ce que dit chaque issue d'une porte, en HTTP (admis : 202 quand ce qu'on reçoit se traitera plus tard, ``gate_reply``)
GATE_STATUS = {gate_p.ACCEPTED: 200, gate_p.IGNORED: 200, gate_p.INVALID: 400, gate_p.UNKNOWN: 401,
               gate_p.FORBIDDEN: 403, gate_p.DISABLED: 403, gate_p.MISSING: 404, gate_p.CONFLICT: 409,
               gate_p.REFUSED: 409, gate_p.BUSY: 429}
#: ce que les services de webhooks envoient (ADR 0117), le premier présent l'emporte : la clé recopiée telle quelle
#: (le « secret token » de GitLab), la signature du corps par la clé, l'évènement, l'identifiant de la livraison (qui
#: sert de clé d'idempotence : une livraison rejouée rend le même appel)
WAKE_KEY_HEADERS = ("x-gitlab-token",)
WAKE_SIGNATURE_HEADERS = ("x-hub-signature-256", "x-gitea-signature", "x-forgejo-signature", "x-signature-256")
WAKE_EVENT_HEADERS = ("x-github-event", "x-gitea-event", "x-forgejo-event", "x-gitlab-event")
WAKE_DELIVERY_HEADERS = ("idempotency-key", "x-github-delivery", "x-gitea-delivery", "x-forgejo-delivery")


def first_header(headers: Any, names: tuple[str, ...], limit: int = 200) -> str:
    """Le premier de ces en-têtes qui est là, réduit à ses caractères imprimables et borné (vide : aucun)."""
    for name in names:
        value = "".join(ch for ch in (headers.get(name) or "") if ch.isprintable()).strip()
        if value:
            return value[:limit]
    return ""
#: l'extension Teams (ADR 0069) : la taille d'un lot au plus, les échecs de clé tolérés par IP
TEAMS_MAX_BYTES = 512 * 1024
#: une image d'un message (ADR 0258) : 8 Mo d'octets, en base64, et son enveloppe
TEAMS_IMAGE_MAX_BYTES = 12 * 1024 * 1024
#: un lot du téléphone (ADR 0120), au plus : 200 messages de 4 000 caractères
PHONE_MAX_BYTES = 2 * 1024 * 1024
TEAMS_FAILURES = (20, 60.0)
#: les origines d'une extension de navigateur : une page web ne peut pas s'en réclamer
EXTENSION_ORIGINS = ("chrome-extension://", "moz-extension://")
#: la boîte d'envoi en direct (``/api/teams/live``, ADR 0251) : le délai pour se présenter (sa clé, dans le premier
#: message, jamais dans l'adresse), la relecture de la boîte, le signe de vie quand rien ne change (il garde aussi
#: éveillé le service de l'extension), et les connexions ouvertes par compte au plus
LIVE_HELLO_S = 10.0
LIVE_EVERY_S = 1.0
LIVE_PING_S = 20.0
LIVE_PER_ACCOUNT = 4
#: les connexions pas encore présentées, par adresse et au total (une trame se lit avant toute clé)
LIVE_UNKNOWN_PER_IP = 2
LIVE_UNKNOWN_MAX = 16
#: une clé de l'extension telle que le serveur les crée (``new_key`` : le préfixe puis du base64 d'URL)
LIVE_KEY = re.compile(r"mtk_[A-Za-z0-9_-]{1,196}")
#: comment une connexion en direct se ferme (les codes 4xxx d'une application, sur le modèle des statuts HTTP)
LIVE_CLOSE = {gate_p.UNKNOWN: 4401, gate_p.DISABLED: 4403, gate_p.FORBIDDEN: 4403, gate_p.BUSY: 4429,
              gate_p.INVALID: 4400}


def gate_reply(got: gate_p.GateResult, headers: dict[str, str], *, accepted: int = 200) -> JSONResponse:
    """Ce qu'une porte a décidé, en HTTP : ce qu'elle rend si elle admet (``accepted`` : son statut), son message sinon,
    et l'attente d'un refus de cadence."""
    status = accepted if got.outcome == gate_p.ACCEPTED else GATE_STATUS.get(got.outcome, 400)
    if got.outcome == gate_p.BUSY and got.retry_after:
        headers = {**headers, "Retry-After": str(got.retry_after)}
    if status < 300:
        return JSONResponse({"ok": True, **got.data}, status_code=status, headers=headers)
    return JSONResponse({"error": got.message or "Refusé."}, status_code=status, headers=headers)


def door_refusal(request: Request, failures: SlidingWindow, headers: Mapping[str, str], *,
                 origin_ok: Callable[[str], bool]) -> JSONResponse | None:
    """Les deux refus qu'une porte à clé du réseau (Teams, réveils) oppose avant de juger sa clé : une origine qu'elle
    n'admet pas (``origin_ok`` ; sans ``Origin``, aucune à juger), 403 ; puis une adresse qui a trop échoué dans sa
    fenêtre ``failures``, 429, à réessayer dans une minute. ``None`` : la porte poursuit ses propres contrôles. La
    machinerie est commune, la réponse de clé reste à chaque porte (ADR 0213)."""
    origin = request.headers.get("origin")
    if origin is not None and not origin_ok(origin):
        return JSONResponse({"error": "Origine refusée."}, status_code=403, headers=headers)
    ip = request.client.host if request.client else "?"
    if failures.blocked(f"ip:{ip}"):
        return JSONResponse({"error": "Trop de tentatives."}, status_code=429, headers={**headers, "Retry-After": "60"})
    return None


def door_routes(cfg: WebConfig, accounts: Accounts, *, wakeup: wakeup_p.WakeGate | None,
                teams: teams_p.TeamsGate | None, phone: phone_p.PhoneGate | None) -> list[BaseRoute]:
    """Les routes des portes, dans l'ordre où ``create_app`` les monte (dont la boîte d'envoi de Teams en direct) ;
    chaque appel a ses deux fenêtres d'échecs (réveils, Teams)."""
    wake_failures = SlidingWindow(*WAKE_FAILURES)
    teams_failures = SlidingWindow(*TEAMS_FAILURES)
    #: les connexions en direct ouvertes, par empreinte de clé (la plus ancienne d'abord), et celles qui ne se sont
    #: pas encore présentées, par adresse
    live_open: dict[str, list[WebSocket]] = {}
    unknown: dict[str, int] = {}

    async def wake(request: Request) -> Response:
        """Un réveil par API (ADR 0068, 0117) : ``{"text": "…", "context": …}`` ou le JSON d'un service ; sa clé en
        ``Authorization: Bearer`` (ou ``X-Gitlab-Token``), ou le corps signé par elle (``X-Hub-Signature-256``) ; une
        clé d'idempotence facultative (``Idempotency-Key``, sinon l'identifiant de la livraison). Réveil inconnu et
        mauvaise clé : le même 401 (et trop d'échecs d'une même adresse : 429) ; désactivé : 403 ; rien à lire :
        400 ; trop d'appels : 429 ; son projet n'est pas actif : 409 ; un « ping » : 200 ; reçu : 202. Rien n'est
        journalisé avant que la porte l'ait admis."""
        headers = {"Cache-Control": "no-store"}
        if wakeup is None:
            return JSONResponse({"error": "Les réveils par API ne sont pas branchés."}, status_code=404,
                                headers=headers)
        refused = door_refusal(request, wake_failures, headers, origin_ok=lambda origin: origin in cfg.origins)
        if refused is not None:
            return refused
        ip = request.client.host if request.client else "?"
        try:
            raw = await read_bounded(request, WAKE_MAX_BYTES)  # borné aussi sans Content-Length : il signe ce corps
        except PayloadTooLarge:
            return JSONResponse({"error": "Requête trop grande."}, status_code=413, headers=headers)
        data = parsed(raw) if raw else None  # un réveil admet un texte : illisible, ce n'est pas un refus
        h = request.headers
        got = await wakeup(wakeup_p.WakeRequest(
            name=request.path_params["name"][:60], key=bearer(h.get("authorization")) or first_header(h, WAKE_KEY_HEADERS),
            body=raw, data=data, signature=first_header(h, WAKE_SIGNATURE_HEADERS),
            event=first_header(h, WAKE_EVENT_HEADERS, 60), idempotency=first_header(h, WAKE_DELIVERY_HEADERS)))
        if got.outcome == gate_p.UNKNOWN:
            wake_failures.fail(f"ip:{ip}")
        return gate_reply(got, headers, accepted=202)

    async def teams_call(request: Request, kind: str) -> Response:
        """L'extension Teams (ADR 0069) : ``POST /api/teams/inbox`` (un lot de messages), ``GET /api/teams/outbox``
        (ce qui doit repartir), ``POST /api/teams/outbox/<id>`` (un accusé), ``POST /api/teams/image`` (une image
        d'un message, ADR 0258 : son message pas encore arrivé, 404), ``POST /api/teams/photo`` (la photo de profil
        d'une personne, ADR 0300 : une personne que ce compte ne connaît pas, 404). Sa clé en ``Authorization: Bearer`` ;
        une origine d'extension, ou aucune (une page web, jamais). Clé absente ou fausse : le même 401 (et trop
        d'échecs d'une même adresse : 429) ; Teams désactivé : 403 ; requête illisible : 400 ; trop de requêtes :
        429 ; élément inconnu : 404 ; accusé impossible : 409. Rien n'est rangé avant que la porte l'ait admis."""
        headers = {"Cache-Control": "no-store"}
        if teams is None:
            return JSONResponse({"error": "Teams n'est pas branché."}, status_code=404, headers=headers)
        refused = door_refusal(request, teams_failures, headers,
                               origin_ok=lambda origin: origin.startswith(EXTENSION_ORIGINS) or origin in cfg.origins)
        if refused is not None:
            return refused
        ip = request.client.host if request.client else "?"
        key = bearer(request.headers.get("authorization"))
        if not key.startswith(teams_p.KEY_PREFIX) or len(key) > KEY_MAX:  # sans clé valable, le corps n'est pas lu
            teams_failures.fail(f"ip:{ip}")
            return JSONResponse({"error": "Clé refusée."}, status_code=401, headers=headers)
        data: dict[str, Any] = {}
        if request.method == "POST":
            got_body = await json_object(request, TEAMS_IMAGE_MAX_BYTES if kind == "image" else TEAMS_MAX_BYTES,
                                         headers)
            if isinstance(got_body, JSONResponse):
                return got_body
            data = got_body
        if kind == "inbox":
            got = await teams.inbox(key, data)
        elif kind == "outbox":
            got = await teams.outbox(key)
        elif kind == "image":
            got = await teams.image(key, data)
        elif kind == "photo":
            got = await teams.photo(key, data)
        else:
            got = await teams.ack(key, request.path_params["item"][:40], data)
        if got.outcome == gate_p.UNKNOWN:
            teams_failures.fail(f"ip:{ip}")
        return gate_reply(got, headers, accepted=202 if kind in ("inbox", "image", "photo") else 200)

    async def teams_inbox(request: Request) -> Response:
        return await teams_call(request, "inbox")

    async def teams_image(request: Request) -> Response:
        return await teams_call(request, "image")

    async def teams_photo(request: Request) -> Response:
        return await teams_call(request, "photo")

    async def phone_call(request: Request, kind: str) -> Response:
        """L'application du téléphone (ADR 0120) : ``POST /api/phone/inbox`` (les messages qu'elle a lus dans ses
        notifications), ``POST /api/phone/settled`` (ce que sont devenues les réponses proposées). Sous son jeton
        (``mw_…``, client ``mobile``, sans ``Origin``) : jeton absent ou faux, 401 ; pas l'application du téléphone,
        pas une propriétaire, ou coupé, 403 ; illisible, 400 ; trop grand, 413 ; trop de requêtes ou pas prête, 429.
        Rien ne s'écrit avant que la porte l'ait admis."""
        headers = {"Cache-Control": "no-store"}
        if phone is None:
            return JSONResponse({"error": "Les messages du téléphone ne sont pas branchés."}, status_code=404,
                                headers=headers)
        found = phone_of(request, accounts)
        if isinstance(found, JSONResponse):
            return found
        data = await json_object(request, PHONE_MAX_BYTES, headers)
        if isinstance(data, JSONResponse):
            return data
        handle = found[0].handle
        got = await (phone.inbox(handle, data) if kind == "inbox" else phone.settled(handle, data))
        if got.outcome == gate_p.ACCEPTED:
            # admis par la porte : son dernier usage noté (un téléphone qui ne fait que pousser ses messages dit quand
            # on l'a vu, ADR 0190) — jamais avant qu'elle l'ait admis
            await accounts.use_token(native_token(request.headers))
        return gate_reply(got, headers)

    async def phone_inbox(request: Request) -> Response:
        return await phone_call(request, "inbox")

    async def phone_settled(request: Request) -> Response:
        return await phone_call(request, "settled")

    async def teams_outbox(request: Request) -> Response:
        return await teams_call(request, "outbox")

    async def teams_ack(request: Request) -> Response:
        return await teams_call(request, "ack")

    async def teams_live(ws: WebSocket) -> None:
        """La boîte d'envoi de Teams en direct (ADR 0251) : l'extension se présente par ``{"type": "hello", "key":
        "mtk_…"}`` dans les ``LIVE_HELLO_S`` secondes ; admise comme un relevé (la clé, l'état, la minute), elle reçoit
        ``{"type": "outbox", "items": […]}`` tout de suite, puis à chaque changement de la boîte (relue chaque seconde,
        la clé revérifiée), et ``{"type": "ping"}`` quand rien ne change pendant ``LIVE_PING_S``. Ce qu'elle envoie
        ensuite est lu et ignoré (ses signes de vie). Les accusés restent en HTTP.

        Une connexion qui ne s'est pas encore présentée est acceptée avant toute clé : elles sont plafonnées par
        adresse et au total (``LIVE_UNKNOWN_PER_IP``, ``LIVE_UNKNOWN_MAX``), avant d'être acceptées. Chaque refus
        accepte d'abord la connexion, pour que son code arrive au navigateur (fermée avant, elle ne dit qu'un 1006) :
        4400 (rien de lisible), 4401 (clé refusée), 4403 (origine, Teams ou ce compte coupés), 4404 (Teams pas
        branché), 4408 (pas présentée à temps), 4429 (trop d'échecs ou d'inconnues de cette adresse). Au-delà de
        ``LIVE_PER_ACCOUNT`` connexions d'une clé, la plus ancienne cède sa place (4409) : une connexion morte d'un
        sommeil ne bloque pas la nouvelle."""
        origin = ws.headers.get("origin")
        ip = ws.client.host if ws.client else "?"

        async def refuse(code: int) -> None:
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                if ws.client_state.name == "CONNECTING":
                    await ws.accept()
                await ws.close(code=code)

        if teams is None:
            await refuse(4404)
            return
        if origin is not None and not (origin.startswith(EXTENSION_ORIGINS) or origin in cfg.origins):
            await refuse(4403)
            return
        if teams_failures.blocked(f"ip:{ip}") or unknown.get(ip, 0) >= LIVE_UNKNOWN_PER_IP \
                or sum(unknown.values()) >= LIVE_UNKNOWN_MAX:
            await refuse(4429)
            return
        unknown[ip] = unknown.get(ip, 0) + 1
        try:
            await ws.accept()
            raw = await asyncio.wait_for(ws.receive_text(), LIVE_HELLO_S)
        except TimeoutError:
            await refuse(4408)
            return
        except (WebSocketDisconnect, RuntimeError, KeyError):
            return  # partie avant de se présenter (ou un message binaire)
        finally:
            unknown[ip] -= 1
            if unknown[ip] <= 0:
                unknown.pop(ip, None)
        try:
            hello = json.loads(raw) if len(raw) <= 4096 else None
        except ValueError:
            hello = None
        key = str(hello.get("key") or "") if isinstance(hello, dict) and hello.get("type") == "hello" else ""
        if not LIVE_KEY.fullmatch(key) or len(key) > KEY_MAX:
            teams_failures.fail(f"ip:{ip}")
            await refuse(4401 if isinstance(hello, dict) else 4400)
            return
        mine = token_digest(key)  # jamais la clé en clair comme index
        # la plus ancienne cède sa place, avant que la nouvelle ne compte dans la minute
        while len(live_open.get(mine, [])) >= LIVE_PER_ACCOUNT:
            oldest = live_open[mine].pop(0)
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                await oldest.close(code=4409)
        got = await teams.live(key)
        if got.outcome != gate_p.ACCEPTED:
            if got.outcome == gate_p.UNKNOWN:
                teams_failures.fail(f"ip:{ip}")
            await refuse(LIVE_CLOSE.get(got.outcome, 4400))
            return
        live_open.setdefault(mine, []).append(ws)

        async def drain() -> None:
            """Ce que l'extension envoie après s'être présentée : lu, ignoré ; rend la main quand elle part."""
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                while (await ws.receive())["type"] != "websocket.disconnect":
                    pass

        listening = asyncio.ensure_future(drain())
        loop = asyncio.get_running_loop()
        try:
            items = got.data.get("items", [])
            await ws.send_json({"type": "outbox", "items": items})
            last, quiet_since = json.dumps(items, sort_keys=True), loop.time()
            while not listening.done():
                await asyncio.wait({listening}, timeout=LIVE_EVERY_S)
                if listening.done() or ws not in live_open.get(mine, []):
                    break  # partie, ou remplacée par une plus récente
                now = await teams.live_items(key)
                if now.outcome != gate_p.ACCEPTED:
                    await ws.close(code=LIVE_CLOSE.get(now.outcome, 4400))
                    break
                items = now.data.get("items", [])
                seen = json.dumps(items, sort_keys=True)
                if seen != last:
                    await ws.send_json({"type": "outbox", "items": items})
                    last, quiet_since = seen, loop.time()
                elif loop.time() - quiet_since >= LIVE_PING_S:
                    await ws.send_json({"type": "ping"})
                    quiet_since = loop.time()
        except (WebSocketDisconnect, RuntimeError):
            pass  # partie pendant un envoi
        finally:
            listening.cancel()
            open_now = live_open.get(mine, [])
            if ws in open_now:
                open_now.remove(ws)
            if not open_now:
                live_open.pop(mine, None)

    return [
        Route("/api/wake/{name:str}", wake, methods=["POST"]),
        Route("/api/teams/inbox", teams_inbox, methods=["POST"]),
        Route("/api/teams/image", teams_image, methods=["POST"]),
        Route("/api/teams/photo", teams_photo, methods=["POST"]),
        Route("/api/teams/outbox", teams_outbox, methods=["GET"]),
        Route("/api/teams/outbox/{item:str}", teams_ack, methods=["POST"]),
        WebSocketRoute("/api/teams/live", teams_live),
        Route("/api/phone/inbox", phone_inbox, methods=["POST"]),
        Route("/api/phone/settled", phone_settled, methods=["POST"]),
    ]
