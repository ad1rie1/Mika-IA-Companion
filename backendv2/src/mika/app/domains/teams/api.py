"""Teams, pour qui est connecté (ADR 0187, 0189, 0191) : ses comptes, leurs conversations et leurs fils, les réponses
qu'elle y prépare ; écrire soi-même, lui demander une réponse, décider des siennes.

Un compte est à qui est connecté quand il est à son nom (``personne:<clé>``), ou « à toi » et qu'elle est une de ses
propriétaires (ADR 0186) ; ceux d'elle restent à la console. Une conversation se désigne par son compte et son
identifiant (``<compte>~<id>``), un message par sa référence ; hors de ses comptes, rien n'existe. Ce qu'elle écrit
elle-même part par l'extension de son compte, sous son nom, sans accord à demander (``teams.ecrire``) — et les
réponses de Mika qui attendaient un accord dans la discussion ne partiront plus : le plugin les refuse, pas cette
couche (ADR 0199) ; ce qu'elle décide d'une réponse de Mika passe par les actions de la console, en son nom.
Une conversation s'appelle comme dans Teams, sinon (un tête-à-tête) comme l'autre personne (``port.title``).

Les réactions d'un message (ADR 0300) se lisent avec lui, chaque personne sous le nom que le compte lui connaît (elle
est dans la conversation : qui la lit la voit) ; la photo de profil d'une personne se sert à qui peut lire le compte où
elle a été vue (``GET …/teams/photo``), son adresse donnée là où une personne paraît (``photo``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from starlette.responses import Response
from starlette.routing import Route

from mika.app.domains.teams import account_settings
from mika.app.domains.teams.extension import download, version_of
from mika.app.me.api import PREFIX, Call, Denied, MeApiBase, done, form, missing
from mika.app.me.common import allows, held_by, millis, only_owner, opened, snippet, work_of
from mika.plugins import teams as teams_p
from mika.plugins.teams import (
    UNDER_WAY,
    WAITING,
    DraftSeen,
    TeamsState,
    asked_still,
    latest,
    pending_draft,
    under_way,
)
from mika.plugins.teams.inspect import not_preparing
from mika.ports.drafts import to_fill
from mika.ports.teams import (
    FAILED,
    GONE,
    PLACED,
    QUEUED,
    SENDING,
    UNUSED,
    AccountInfo,
    Draft,
    Message,
    MessageImage,
    Reaction,
    conversation_key,
    emoji_of,
    person_key,
    split_conversation_key,
)
from mika.vocab.access import SHARE_PREPARE, SHARE_READ, SHARE_USE
from mika.vocab.ownership import OWNED

#: ce que dit un partage qui n'atteint pas le geste demandé
TOO_LOW = {SHARE_READ: "Ce compte t'est partagé en lecture : tu le lis, sans y écrire.",
           SHARE_PREPARE: "Ce compte t'est partagé en lecture et préparation : elle peut t'y préparer des réponses, que "
                          "son propriétaire approuve."}
#: au plus tant de conversations, de messages d'un fil, de réponses
LIMIT = 100
#: ce que tu as écrit et qui n'est pas parti se montre encore ce temps-là (µs)
RECENT_US = 24 * 3600 * 1_000_000
#: ce que tu as écrit et qui est parti reste dans le fil, marqué parti, jusqu'à ce que son jumeau y arrive par
#: l'extension — au plus ce temps-là (µs) : sans elle, il reviendra avec son lot suivant (ADR 0308)
SENT_KEPT_US = 5 * 60 * 1_000_000
#: son jumeau (ADR 0251) : un message de toi, le même texte aux espaces près, à moins de deux minutes de son départ
TWIN_US = 120 * 1_000_000
SNIPPET = 160


# ── à qui ──


def accounts(call: Call) -> dict[str, tuple[AccountInfo, str]]:
    """Ses comptes, par clé : le compte et son niveau — les siens, puis ceux qu'on lui partage (ADR 0188)."""
    return held_by(call, call.port("teams"), teams_p.params_of)


def _level(call: Call, account: str, need: str) -> None:
    """Son niveau sur ce compte ouvre-t-il ce geste ? (sinon : introuvable, ou refusé)"""
    opened(accounts(call).get(account), need, TOO_LOW, "Ce compte ne t'est pas ouvert pour cela.")


def owned(call: Call, account: str) -> AccountInfo:
    """Un compte à elle (le régler, sa clé, décider de ses réponses) : un partage n'y suffit pas."""
    return only_owner(accounts(call).get(account), "Seul son propriétaire règle ce compte et décide de ce qui en part.")


def _port(call: Call) -> Any:
    port = call.port("teams")
    if port is None:
        raise Denied(503, "Teams n'est pas branché.")
    return port


def _conversation(call: Call, key: str) -> tuple[str, str]:
    """Une conversation d'un de ses comptes (``<compte>~<id>``), sinon : introuvable."""
    account, conversation = split_conversation_key(key)
    if account not in accounts(call) or _port(call).conversation(account, conversation) is None:
        raise missing()
    return account, conversation


def _message(call: Call, ref: str) -> Message:
    m = _port(call).message(ref) if ref else None
    if m is None or m.account not in accounts(call):
        raise missing()
    return m


def state(call: Call) -> TeamsState:
    """Ce que Teams sait de sa vie (``TeamsState``) : ses brouillons, les messages vus, ses demandes. Les réglages de
    ses comptes le lisent aussi (``account_settings.py``, les clés qui ont laissé une trace)."""
    return call.frame.state(teams_p.TEAMS.name)


# ── ce qui se montre ──


def photo_url(account: str, person: str, etag: str) -> str:
    """L'adresse de la photo de profil d'une personne (ADR 0300) : ``GET …/teams/photo`` ; ``v`` change avec la photo
    (le navigateur la garde un jour)."""
    version = hashlib.sha256(etag.encode()).hexdigest()[:12]
    return f"{PREFIX}/teams/photo?{urlencode({'account': account, 'person': person, 'v': version})}"


def photos_in(port: Any, account: str, people: Sequence[str]) -> dict[str, str]:
    """Les photos de ces personnes (leurs identifiants Teams) gardées sous ce compte : identifiant en minuscules → son
    adresse. Une requête, quel que soit leur nombre."""
    found = port.photos_of([person_key(p) for p in people if p], accounts=[account]) if port is not None else {}
    return {person: photo_url(acct, person, etag) for person, (acct, etag) in found.items()}


def photo_in(photos: Mapping[str, str] | None, person: str) -> str:
    """L'adresse de la photo de cette personne parmi ``photos`` (``photos_in``), vide sans photo ou sans personne."""
    return (photos or {}).get(person_key(person), "") if person else ""


def reaction_json(r: Reaction) -> dict[str, Any]:
    """Une réaction (ADR 0300) : sa clé de Teams, son emoji (vide : inconnu, le client montre la clé), combien, la
    tienne (la personne du compte), et les noms de qui l'a posée que le compte connaît (dix au plus, sans elle)."""
    return {"key": r.key, "emoji": emoji_of(r.key), "count": r.count, "mine": r.mine,
            "names": [n for n in r.names if n]}


def message_json(m: Message, images: Sequence[MessageImage] = (), photos: Mapping[str, str] | None = None) \
        -> dict[str, Any]:
    """Un message ; ``images`` : les siennes (ADR 0258), sans leurs octets — ``GET …/teams/image`` les sert ; ses
    réactions (ADR 0300) ; ``photo`` : l'adresse de la photo de son auteur (``photos`` : par identifiant en minuscules),
    vide sans photo."""
    return {"ref": m.ref, "author": m.author, "author_id": m.author_id, "at": millis(m.at), "text": m.text,
            "own": m.own, "mentions_me": m.mentions_me,
            "images": [{"id": i.image, "position": i.position, "mime": i.mime, "seen": i.seen} for i in images],
            "reactions": [reaction_json(r) for r in m.reactions],
            "photo": photo_in(photos, m.author_id),
            # le message qu'il cite (ADR 0305) : son auteur, un extrait, sa référence chez elle (vide : pas chez elle)
            "quote": {"author": m.quote.author, "author_id": m.quote.author_id, "preview": m.quote.preview,
                      "at": m.quote.at, "ref": m.quote.ref} if m.quote is not None else None}


def _notes(call: Call, seens: list[DraftSeen]) -> dict[str, str]:
    """Les notes de qui a décidé, relues d'un coup : elles sont gardées à part (l'oubli les atteint). Seulement sur un
    compte à qui est connecté : ce que son propriétaire a dit à Mika en refusant ne se lit pas par un partage."""
    mine = accounts(call)
    refs = [d.note_ref for d in seens if d.note_ref and mine.get(d.account, (None, ""))[1] == OWNED]
    store = call.port("store") if refs else None
    return dict(store.content(refs)) if store is not None else {}


def _reply_json(call: Call, seen: DraftSeen, notes: dict[str, str]) -> dict[str, Any]:
    """Une réponse qu'elle a proposée, et ce qu'elle est devenue ; exactement ce qui partira tant qu'elle attend.
    ``answered`` : la personne du compte a répondu autrement dans la discussion — elle ne partira pas (ADR 0199)."""
    port = call.port("teams")
    kept = port.draft(seen.draft)
    preview = port.preview(seen.draft, her=teams_p.her(call.frame)) if seen.state == WAITING else None
    return {"id": seen.draft, "account": seen.account, "conversation": conversation_key(seen.account, seen.conversation),
            "in_reply_to": seen.message, "state": seen.state, "mode": seen.mode, "at": millis(seen.at),
            "decided_at": millis(seen.decided_at), "by": seen.by,
            "note": (notes.get(seen.note_ref) or "") if seen.note_ref else seen.note, "asked": seen.asked,
            "edited": seen.edited, "expires": millis(seen.expires), "answered": bool(seen.answered),
            "title": port.title(seen.account, seen.conversation) if port is not None else "",
            "body": kept.body if kept is not None else "", "sent_text": kept.sent_text if kept is not None else "",
            "to_fill": bool(kept and to_fill(kept.body)),
            "preview": {"text": preview.text, "digest": preview.digest, "blocked": preview.blocked}
            if preview is not None else None}


def _account_json(call: Call, a: AccountInfo, level: str) -> dict[str, Any]:
    keys = call.port("teams_keys")
    key = keys.key_state(a.key) if keys is not None else None
    s = state(call)
    waiting = sum(1 for d in s.drafts.values() if d.account == a.key and d.state == WAITING and not d.answered) \
        if allows(level, SHARE_PREPARE) else 0
    # la dernière fois que son extension s'est manifestée (un relevé, la connexion en direct, un lot) : un compte calme
    # n'est pas un compte sans extension
    contact = keys.last_contact(a.key) if keys is not None else 0
    return {"key": a.key, "name": a.name, "level": level, "enabled": a.enabled, "last_batch": millis(a.last_batch),
            "last_seen": millis(max(a.last_batch, contact)),
            "self_name": a.self_name, "extension_key": {"hint": key.hint, "created_at": millis(key.created_at)}
            if key is not None and level == OWNED else None, "drafts_waiting": waiting,
            # un compte partagé se montre à son nom (ADR 0188)
            "owner_name": teams_p.writer_of(call.frame, a.key) if level != OWNED else "",
            # « à toi » : commun à ses propriétaires (on ne le leur partage pas : il est déjà à elles)
            "common": level == OWNED and not teams_p.params_of(call.frame).owners.get(a.key, "")}


# ── lire ──


async def list_accounts(call: Call) -> dict[str, Any]:
    p = teams_p.params_of(call.frame)
    version = version_of(call.api.extension)
    return {"plugged": call.port("teams") is not None, "enabled": p.enabled,
            # l'extension à télécharger (ADR 0246), si elle est à côté du serveur
            "extension": {"version": version} if version is not None else None,
            "accounts": [_account_json(call, a, level) for a, level in accounts(call).values()]}


async def conversations(call: Call) -> dict[str, Any]:
    """Ses conversations, la plus récente d'abord : leur dernier message, et une réponse d'elle en chemin."""
    port = _port(call)
    mine = accounts(call)
    account = call.arg("account", limit=40)
    if account and account not in mine:
        raise missing()
    keys = [account] if account else list(mine)
    if not keys:
        return {"items": []}
    # sa réponse en chemin, par conversation (une réponse à laquelle on a répondu autrement n'est plus en chemin : elle
    # va être refusée, ADR 0199)
    pending: dict[tuple[str, str], DraftSeen] = {}
    for d in state(call).drafts.values():
        if d.state in UNDER_WAY and not d.answered:
            pending.setdefault((d.account, d.conversation), d)
    found = port.conversations(call.number("size", 50, high=LIMIT), text=call.arg("q", limit=100), accounts=keys)
    lasts = port.last_messages([(conv.account, conv.id) for conv in found])
    # l'autre personne de chaque tête-à-tête : sa photo est celle de la conversation (ADR 0300), même quand le dernier
    # message est de toi
    others = port.others([(conv.account, conv.id) for conv in found])
    # la photo de l'auteur de chaque dernier message, et celle de chaque autre personne, une requête par compte
    authors: dict[str, list[str]] = {}
    for (acct, _cid), m in lasts.items():
        authors.setdefault(acct, []).append(m.author_id)
    for (acct, _cid), person in others.items():
        authors.setdefault(acct, []).append(person)
    photos = {acct: photos_in(port, acct, ids) for acct, ids in authors.items()}
    out = []
    for conv in found:
        last = lasts.get((conv.account, conv.id))
        # sa réponse en chemin : pas pour qui ne fait que lire ce compte (ADR 0188)
        hers = pending.get((conv.account, conv.id)) if allows(mine[conv.account][1], SHARE_PREPARE) else None
        out.append({"key": conversation_key(conv.account, conv.id), "account": conv.account, "title": conv.title,
                    "kind": conv.kind,
                    "photo": photo_in(photos.get(conv.account), others.get((conv.account, conv.id), "")),
                    "last_at": millis(conv.last_at), "messages": conv.messages,
                    "last": {**message_json(last, photos=photos.get(conv.account)),
                             "text": snippet(last.text, SNIPPET)} if last is not None else None,
                    "her": {"state": hers.state, "draft": hers.draft} if hers is not None else None})
    return {"items": out}


async def thread(call: Call) -> dict[str, Any]:
    """Le fil d'une conversation (les plus récents ; ``before`` : avant cet instant, en ms), et ses réponses à elle."""
    account, conversation = _conversation(call, call.arg("conversation", limit=400))
    port = call.port("teams")
    before = call.number("before", 0, low=0, high=10**15) * 1000
    size = call.number("size", 50, high=LIMIT)
    found = port.thread(account, conversation, size + 1, before=before)
    more = len(found) > size
    found = found[-size:]
    s = state(call)
    level = accounts(call)[account][1]
    # ses réponses ici, en chemin ou demandées : pas pour qui ne fait que lire ce compte (ADR 0188 : elles sont
    # l'affaire de son propriétaire)
    prepares = allows(level, SHARE_PREPARE)
    replies = sorted((d for d in s.drafts.values() if d.account == account and d.conversation == conversation),
                     key=lambda d: -d.proposal)[:10] if prepares else []
    # ce que tu as écrit toi-même (ADR 0189) : en file, en cours d'envoi, posé, puis parti tant que son jumeau n'est
    # pas revenu dans le fil par l'extension (au bout du fil seulement) ; ce qui n'est pas parti à temps se règle ici,
    # et se montre encore un jour (« pas parti »)
    now = call.kernel.mind.clock.now()
    port.expire_written(account, now)
    landed = [m for m in found if m.own] if not before else None
    pending = [{"id": d.id, "body": d.body, "at": millis(d.created), "state": d.state, "by": d.author,
                "reason": d.reason}
               for d in port.drafts(LIMIT, accounts=[account])
               # les tiens seulement : sur un compte partagé, celui d'un autre revient dans le fil une fois parti
               if d.conversation == conversation and d.author == call.me.handle
               and (d.state in (QUEUED, SENDING, PLACED) or (
                   d.state in (UNUSED, FAILED) and now - d.updated < RECENT_US) or (
                   d.state == GONE and landed is not None and now - d.sent_at < SENT_KEPT_US
                   and not _came_back(d, landed)))]
    # une demande en cours : pas une dont ses essais sont épuisés (elle y a renoncé ; « Préremplir » la relance), ni
    # une qu'elle ne prendra pas (Teams coupé, ce compte décoché : ses tâches l'écartent) — les aides du plugin
    # (``asked_still``, ``not_preparing``), jamais leur règle recopiée (audit du 2026-11-05, K10-03)
    asked, work = _asked_work(call, s, account, conversation, prepares)
    conv = port.conversation(account, conversation)
    notes = _notes(call, replies)
    images: dict[str, list[MessageImage]] = {}
    for i in port.images_of([m.ref for m in found]):
        images.setdefault(i.ref, []).append(i)
    # la photo de chaque auteur (ADR 0300), et celle de la conversation (l'autre personne d'un tête-à-tête), d'un coup
    other = port.others([(account, conversation)]).get((account, conversation), "")
    photos = photos_in(port, account, [*(m.author_id for m in found), other])
    # son nom, comme dans la liste : celui de Teams, sinon (un tête-à-tête) l'autre personne
    return {"key": conversation_key(account, conversation), "account": account,
            "title": port.title(account, conversation), "kind": conv.kind, "photo": photo_in(photos, other),
            "messages": [message_json(m, images.get(m.ref, ()), photos) for m in found], "more": more,
            "replies": [_reply_json(call, d, notes) for d in replies], "pending": pending[::-1],
            "under_way": prepares and under_way(s, account, conversation),
            "asked": asked, "work": work}


def _came_back(d: Draft, landed: Sequence[Message]) -> bool:
    """Ce que tu as écrit est-il revenu dans le fil, par l'extension ? Son jumeau (ADR 0251) : un de tes messages, le
    même texte aux espaces près (ce qui est parti, ce qui était en file, ou ce que tu as écrit), à moins de deux
    minutes de son départ."""
    said = {" ".join(t.split()) for t in (d.sent_text, d.final, d.body) if t}
    return any(abs(m.at - d.sent_at) <= TWIN_US and " ".join(m.text.split()) in said for m in landed)


def _asked_work(call: Call, s: TeamsState, account: str, conversation: str,
                prepares: bool) -> tuple[bool, dict[str, Any] | None]:
    """Une réponse demandée ici, et où elle en est (ADR 0306) — qu'on la lui ait demandée ou qu'elle s'y soit mise
    d'elle-même. Une demande en cours : pas une dont ses essais sont épuisés (elle y a renoncé ; « Préremplir » la
    relance), ni une qu'elle ne prendra pas (Teams coupé, ce compte décoché : ses tâches l'écartent) — les aides du
    plugin (``asked_still``, ``not_preparing``), jamais leur règle recopiée (audit du 2026-11-05, K10-03). Rien pour
    qui ne fait que lire le compte (``prepares`` faux : ADR 0188)."""
    if not prepares:
        return False, None
    p = teams_p.params_of(call.frame)
    here = [(ref, a.at) for ref, a in s.asked.items() if a.account == account and a.conversation == conversation]
    live = [at for ref, at in here if asked_still(s, ref, p)] if not not_preparing(p, account) else []

    def ours(ref: str) -> bool:
        m = s.messages.get(ref)
        return any(ref == r for r, _ in here) or (m is not None and m.account == account
                                                    and m.conversation == conversation)

    return bool(live), work_of(call, teams_p.TEAMS.name, ours, max(live, default=0))


async def progress(call: Call) -> dict[str, Any]:
    """Où elle en est d'une réponse dans cette conversation, en direct (ADR 0306) : ce qu'un client relit toutes les
    deux secondes tant qu'elle y travaille, sans relire le fil — ``work``, ``asked``, ``under_way``."""
    account, conversation = _conversation(call, call.arg("conversation", limit=400))
    s = state(call)
    prepares = allows(accounts(call)[account][1], SHARE_PREPARE)
    asked, work = _asked_work(call, s, account, conversation, prepares)
    return {"work": work, "asked": asked, "under_way": prepares and under_way(s, account, conversation)}


async def replies(call: Call) -> dict[str, Any]:
    """Ses réponses dans tes comptes (ADR 0191), la plus récente d'abord."""
    mine = accounts(call)
    s = state(call)
    shown = [d for d in sorted(s.drafts.values(), key=lambda d: -d.proposal)
             if d.account in mine and allows(mine[d.account][1], SHARE_PREPARE)][:LIMIT]
    notes = _notes(call, shown)
    return {"items": [_reply_json(call, d, notes) for d in shown]}


# ── écrire, décider ──


async def send(call: Call) -> dict[str, Any]:
    """Ton message (ADR 0189) : il part par l'extension de ton compte, sous ton nom, sans accord à demander."""
    key = call.arg("conversation", limit=400)
    _level(call, _conversation(call, key)[0], SHARE_USE)
    reply_to = call.arg("reply_to", limit=400)
    if reply_to:
        _message(call, reply_to)
    got = await call.act("teams.ecrire", form(fixed={"conversation": key, "reply_to": reply_to},
                                              body=call.arg("body", limit=4000)))
    return done(got)


async def prefill(call: Call) -> dict[str, Any]:
    """« Préremplir avec Mika » : elle prépare une réponse à ce message tout de suite, même endormie (ADR 0306 ; où elle
    en est : ``work`` du fil) ; elle suivra le mode du compte (posée dans Teams, ou à ton accord). Une réponse déjà en chemin se rend telle quelle.

    Les gardes sont celles de l'action ``teams.rediger``, lues par les aides du plugin (``not_preparing``,
    ``pending_draft``, ``asked_still`` : audit du 2026-11-05, K10-03) ; seul apport d'ici, une réponse « ok » qui dit
    où en est la demande plutôt que le refus de l'action quand une réponse est en chemin ou déjà demandée."""
    m = _message(call, call.arg("message", limit=400))
    _level(call, m.account, SHARE_PREPARE)
    p = teams_p.params_of(call.frame)
    said = not_preparing(p, m.account)
    if said:  # elle ne s'y mettrait jamais : on ne lui demande rien
        raise Denied(409, said)
    s = state(call)
    pending = pending_draft(s, m.account, m.conversation)
    if pending is not None:
        return {"ok": True, "message": "Une réponse est déjà en chemin.", "draft": pending.draft, "asked": False}
    if asked_still(s, m.ref, p):
        return {"ok": True, "message": "Elle y travaille déjà.", "draft": "", "asked": True}
    got = await call.act("teams.rediger", form(fixed={"message": m.ref}, instruction=call.arg("instruction", limit=4000)),
                         subject=conversation_key(m.account, m.conversation))
    return done(got, draft="", asked=True)


def _reply_mine(call: Call, draft_id: str) -> DraftSeen:
    """Une de ses réponses, dans un compte à elle : c'est le propriétaire qui en décide (ADR 0188, 0191)."""
    seen = latest(state(call), draft_id) if draft_id else None
    if seen is None or seen.account not in accounts(call):
        raise missing()
    owned(call, seen.account)
    return seen


async def reply_send(call: Call) -> dict[str, Any]:
    seen = _reply_mine(call, call.arg("id", limit=100))
    return done(await call.act("teams.envoyer", form(fixed={"draft": seen.draft, "seen": call.arg("seen", limit=100)})))


async def reply_edit(call: Call) -> dict[str, Any]:
    seen = _reply_mine(call, call.arg("id", limit=100))
    return done(await call.act("teams.retoucher", form(fixed={"draft": seen.draft},
                                                       body=call.arg("body", limit=4000))))


async def reply_refuse(call: Call) -> dict[str, Any]:
    seen = _reply_mine(call, call.arg("id", limit=100))
    return done(await call.act("teams.refuser", form(fixed={"draft": seen.draft}, note=call.arg("note", limit=500))))


async def reply_redo(call: Call) -> dict[str, Any]:
    seen = _reply_mine(call, call.arg("id", limit=100))
    return done(await call.act("teams.reprendre", form(fixed={"draft": seen.draft},
                                                       instruction=call.arg("instruction", limit=4000))))


def count(call: Call) -> int:
    """Pour la barre du haut : ses réponses qui attendent ta décision (pas une à laquelle on a répondu autrement)."""
    mine = accounts(call)
    return sum(1 for d in state(call).drafts.values()
               if d.state == WAITING and not d.answered and mine.get(d.account, (None, ""))[1] == OWNED)


#: ce qu'il compte pour la barre du haut
COUNTERS = {"teams": count}


async def image(call: Call) -> Response:
    """``GET …/teams/image?message=&image=`` : les octets d'une image d'un message (ADR 0258), à qui peut lire son
    compte ; inconnue : 404. Gardée dans le navigateur un jour (elle ne change pas)."""
    m = _message(call, call.arg("message", limit=40))
    found = _port(call).image_bytes(m.ref, call.arg("image", limit=200))
    if found is None:
        raise missing()
    mime, data = found
    return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=86400",
                                                    "X-Content-Type-Options": "nosniff"})


async def photo(call: Call) -> Response:
    """``GET …/teams/photo?account=&person=`` (ou ``conversation=`` : le compte de cette conversation) : la photo de
    profil d'une personne (ADR 0300), à qui peut lire ce compte — elle n'y est gardée que pour une personne qu'il a
    vue (ses messages, une mention), comme le fil ; inconnue, ou un compte qui n'est pas à toi : 404. Gardée un jour
    dans le navigateur (son adresse change avec elle)."""
    conversation = call.arg("conversation", limit=400)
    account = _conversation(call, conversation)[0] if conversation else call.arg("account", limit=40)
    if account not in accounts(call):
        raise missing()
    found = _port(call).photo(account, person_key(call.arg("person", limit=200)))
    if found is None:
        raise missing()
    return Response(found.data, media_type=found.mime, headers={"Cache-Control": "private, max-age=86400",
                                                                "X-Content-Type-Options": "nosniff"})


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    return [r("/teams/accounts", list_accounts), r("/teams/extension", download, raw=True),
            r("/teams/image", image, raw=True), r("/teams/photo", photo, raw=True),
            r("/teams/conversations", conversations),
            r("/teams/thread", thread), r("/teams/work", progress), r("/teams/replies", replies),
            r("/teams/send", send, write=True), r("/teams/prefill", prefill, write=True),
            r("/teams/reply/send", reply_send, write=True), r("/teams/reply/edit", reply_edit, write=True),
            r("/teams/reply/refuse", reply_refuse, write=True), r("/teams/reply/redo", reply_redo, write=True),
            *account_settings.routes(api)]
