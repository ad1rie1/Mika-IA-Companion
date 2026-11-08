"""Teams, pour qui est connecté (ADR 0187, 0189, 0191) : ses comptes, leurs conversations et leurs fils, les réponses
qu'elle y prépare ; écrire soi-même, lui demander une réponse, décider des siennes.

Un compte est à qui est connecté quand il est à son nom (``personne:<clé>``), ou « à toi » et qu'elle est une de ses
propriétaires (ADR 0186) ; ceux d'elle restent à la console. Une conversation se désigne par son compte et son
identifiant (``<compte>~<id>``), un message par sa référence ; hors de ses comptes, rien n'existe. Ce qu'elle écrit
elle-même part par l'extension de son compte, sous son nom, sans accord à demander (``teams.ecrire``) — et les
réponses de Mika qui attendaient un accord dans la discussion ne partiront plus : le plugin les refuse, pas cette
couche (ADR 0199) ; ce qu'elle décide d'une réponse de Mika passe par les actions de la console, en son nom.
Une conversation s'appelle comme dans Teams, sinon (un tête-à-tête) comme l'autre personne (``port.title``).
"""

from __future__ import annotations

from typing import Any

from starlette.routing import Route

from mika.app.moi import Call, Denied, MeApi, done, form, missing
from mika.plugins import teams as teams_p
from mika.plugins.teams import UNDER_WAY, WAITING, DraftSeen, TeamsState, latest, under_way
from mika.ports.teams import (
    FAILED,
    PLACED,
    QUEUED,
    SENDING,
    UNUSED,
    AccountInfo,
    Message,
    conversation_key,
    split_conversation_key,
    to_fill,
)
from mika.vocab.access import PERSON, SHARE_PREPARE, SHARE_READ, SHARE_USE, reaches

#: le niveau de qui est connecté sur un compte : le sien ; sinon, ce qu'on lui en partage (ADR 0188)
OWN = "proprietaire"
#: ce que dit un partage qui n'atteint pas le geste demandé
TOO_LOW = {SHARE_READ: "Ce compte t'est partagé en lecture : tu le lis, sans y écrire.",
           SHARE_PREPARE: "Ce compte t'est partagé en lecture et préparation : elle peut t'y préparer des réponses, que "
                          "son propriétaire approuve."}
#: au plus tant de conversations, de messages d'un fil, de réponses
LIMIT = 100
#: ce que tu as écrit et qui n'est pas parti se montre encore ce temps-là (µs)
RECENT_US = 24 * 3600 * 1_000_000
SNIPPET = 160


# ── à qui ──


def accounts(call: Call) -> dict[str, tuple[AccountInfo, str]]:
    port = call.port("teams")
    if port is None:
        return {}
    p = teams_p.params_of(call.frame)
    me, mine = call.me, PERSON + call.me.person
    out: dict[str, tuple[AccountInfo, str]] = {}
    for a in port.accounts():
        owner = p.owners.get(a.key, "")
        if (not owner and me.owner) or owner == mine:
            out[a.key] = (a, OWN)
        elif level := p.shares.get(a.key, {}).get(mine, ""):
            out[a.key] = (a, level)
    return out


def _level(call: Call, account: str, need: str) -> None:
    """Son niveau sur ce compte ouvre-t-il ce geste ? (sinon : introuvable, ou refusé)"""
    found = accounts(call).get(account)
    if found is None:
        raise missing()
    if found[1] != OWN and not reaches(found[1], need):
        raise Denied(403, TOO_LOW.get(found[1], "Ce compte ne t'est pas ouvert pour cela."))


def owned(call: Call, account: str) -> AccountInfo:
    """Un compte à elle (le régler, sa clé, décider de ses réponses) : un partage n'y suffit pas."""
    found = accounts(call).get(account)
    if found is None:
        raise missing()
    if found[1] != OWN:
        raise Denied(403, "Seul son propriétaire règle ce compte et décide de ce qui en part.")
    return found[0]


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


def _state(call: Call) -> TeamsState:
    return call.frame.state(teams_p.TEAMS.name)


# ── ce qui se montre ──


def _ms(us: int) -> int:
    return us // 1000 if us else 0


def _snippet(text: str) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= SNIPPET else flat[: SNIPPET - 1] + "…"


def message_json(m: Message) -> dict[str, Any]:
    return {"ref": m.ref, "author": m.author, "author_id": m.author_id, "at": _ms(m.at), "text": m.text,
            "own": m.own, "mentions_me": m.mentions_me}


def _notes(call: Call, seens: list[DraftSeen]) -> dict[str, str]:
    """Les notes de qui a décidé, relues d'un coup : elles sont gardées à part (l'oubli les atteint). Seulement sur un
    compte à qui est connecté : ce que son propriétaire a dit à Mika en refusant ne se lit pas par un partage."""
    mine = accounts(call)
    refs = [d.note_ref for d in seens if d.note_ref and mine.get(d.account, (None, ""))[1] == OWN]
    store = call.port("store") if refs else None
    return dict(store.content(refs)) if store is not None else {}


def _reply_json(call: Call, seen: DraftSeen, notes: dict[str, str]) -> dict[str, Any]:
    """Une réponse qu'elle a proposée, et ce qu'elle est devenue ; exactement ce qui partira tant qu'elle attend.
    ``answered`` : la personne du compte a répondu autrement dans la discussion — elle ne partira pas (ADR 0199)."""
    port = call.port("teams")
    kept = port.draft(seen.draft)
    preview = port.preview(seen.draft, her=teams_p.her(call.frame)) if seen.state == WAITING else None
    return {"id": seen.draft, "account": seen.account, "conversation": conversation_key(seen.account, seen.conversation),
            "in_reply_to": seen.message, "state": seen.state, "mode": seen.mode, "at": _ms(seen.at),
            "decided_at": _ms(seen.decided_at), "by": seen.by,
            "note": (notes.get(seen.note_ref) or "") if seen.note_ref else seen.note, "asked": seen.asked,
            "edited": seen.edited, "expires": _ms(seen.expires), "answered": bool(seen.answered),
            "title": port.title(seen.account, seen.conversation) if port is not None else "",
            "body": kept.body if kept is not None else "", "sent_text": kept.sent_text if kept is not None else "",
            "to_fill": bool(kept and to_fill(kept.body)),
            "preview": {"text": preview.text, "digest": preview.digest, "blocked": preview.blocked}
            if preview is not None else None}


def _account_json(call: Call, a: AccountInfo, level: str) -> dict[str, Any]:
    keys = call.port("teams_keys")
    key = keys.key_state(a.key) if keys is not None else None
    s = _state(call)
    waiting = sum(1 for d in s.drafts.values() if d.account == a.key and d.state == WAITING and not d.answered) \
        if level == OWN or reaches(level, SHARE_PREPARE) else 0
    return {"key": a.key, "name": a.name, "level": level, "enabled": a.enabled, "last_batch": _ms(a.last_batch),
            "self_name": a.self_name, "extension_key": {"hint": key.hint, "created_at": _ms(key.created_at)}
            if key is not None and level == OWN else None, "drafts_waiting": waiting,
            # un compte partagé se montre à son nom (ADR 0188)
            "owner_name": teams_p.writer_of(call.frame, a.key) if level != OWN else "",
            # « à toi » : commun à ses propriétaires (on ne le leur partage pas : il est déjà à elles)
            "common": level == OWN and not teams_p.params_of(call.frame).owners.get(a.key, "")}


# ── lire ──


async def list_accounts(call: Call) -> dict[str, Any]:
    p = teams_p.params_of(call.frame)
    return {"plugged": call.port("teams") is not None, "enabled": p.enabled,
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
    s = _state(call)
    out = []
    for conv in port.conversations(call.number("size", 50, high=LIMIT), text=call.arg("q", limit=100),
                                   accounts=keys):
        last = port.thread(conv.account, conv.id, 1)
        level = mine[conv.account][1]
        # sa réponse en chemin : pas pour qui ne fait que lire ce compte (ADR 0188)
        # (une réponse à laquelle on a répondu autrement n'est plus en chemin : elle va être refusée, ADR 0199)
        pending = next((d for d in s.drafts.values() if d.account == conv.account and d.conversation == conv.id
                        and d.state in UNDER_WAY and not d.answered), None) \
            if level == OWN or reaches(level, SHARE_PREPARE) else None
        out.append({"key": conversation_key(conv.account, conv.id), "account": conv.account, "title": conv.title,
                    "kind": conv.kind, "last_at": _ms(conv.last_at), "messages": conv.messages,
                    "last": {**message_json(last[-1]), "text": _snippet(last[-1].text)} if last else None,
                    "her": {"state": pending.state, "draft": pending.draft} if pending is not None else None})
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
    s = _state(call)
    level = accounts(call)[account][1]
    # ses réponses ici, en chemin ou demandées : pas pour qui ne fait que lire ce compte (ADR 0188 : elles sont
    # l'affaire de son propriétaire)
    prepares = level == OWN or reaches(level, SHARE_PREPARE)
    replies = sorted((d for d in s.drafts.values() if d.account == account and d.conversation == conversation),
                     key=lambda d: -d.proposal)[:10] if prepares else []
    # ce que tu as écrit toi-même (ADR 0189) : en file, en cours d'envoi, posé — il revient dans le fil une fois
    # parti ; ce qui n'est pas parti à temps se règle ici, et se montre encore un jour (« pas parti »)
    now = call.kernel.mind.clock.now()
    port.expire_written(account, now)
    pending = [{"id": d.id, "body": d.body, "at": _ms(d.created), "state": d.state, "by": d.author,
                "reason": d.reason}
               for d in port.drafts(LIMIT, accounts=[account])
               # les tiens seulement : sur un compte partagé, celui d'un autre revient dans le fil une fois parti
               if d.conversation == conversation and d.author == call.me.handle
               and (d.state in (QUEUED, SENDING, PLACED) or (
                   d.state in (UNUSED, FAILED) and now - d.updated < RECENT_US))]
    # une demande en cours : pas une dont ses essais sont épuisés (elle y a renoncé ; « Préremplir » la relance), ni
    # une qu'elle ne prendra pas (Teams coupé, ce compte décoché : ses tâches l'écartent)
    p = teams_p.params_of(call.frame)
    asked = prepares and p.enabled and account not in p.accounts_off and any(
        a.account == account and a.conversation == conversation and s.attempts.get(ref, 0) < p.draft_attempts_max
        for ref, a in s.asked.items())
    conv = port.conversation(account, conversation)
    notes = _notes(call, replies)
    # son nom, comme dans la liste : celui de Teams, sinon (un tête-à-tête) l'autre personne
    return {"key": conversation_key(account, conversation), "account": account,
            "title": port.title(account, conversation), "kind": conv.kind,
            "messages": [message_json(m) for m in found], "more": more,
            "replies": [_reply_json(call, d, notes) for d in replies], "pending": pending[::-1],
            "under_way": prepares and under_way(s, account, conversation),
            "asked": asked}


async def replies(call: Call) -> dict[str, Any]:
    """Ses réponses dans tes comptes (ADR 0191), la plus récente d'abord."""
    mine = accounts(call)
    s = _state(call)
    shown = [d for d in sorted(s.drafts.values(), key=lambda d: -d.proposal)
             if d.account in mine and (mine[d.account][1] == OWN or reaches(mine[d.account][1], SHARE_PREPARE))][:LIMIT]
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
    """« Préremplir avec Mika » : elle prépare une réponse à ce message à son prochain moment de travail ; elle
    suivra le mode du compte (posée dans Teams, ou à ton accord). Une réponse déjà en chemin se rend telle quelle."""
    m = _message(call, call.arg("message", limit=400))
    _level(call, m.account, SHARE_PREPARE)
    p = teams_p.params_of(call.frame)
    if not p.enabled or m.account in p.accounts_off:  # elle ne s'y mettrait jamais : on ne lui demande rien
        raise Denied(409, "Teams est désactivé : elle n'y prépare rien." if not p.enabled else
                     "Ce compte Teams est décoché : elle n'y prépare rien.")
    s = _state(call)
    pending = next((d for d in s.drafts.values() if d.account == m.account and d.conversation == m.conversation
                    and d.state in UNDER_WAY), None)
    if pending is not None:
        return {"ok": True, "message": "Une réponse est déjà en chemin.", "draft": pending.draft, "asked": False}
    if m.ref in s.asked and s.attempts.get(m.ref, 0) < p.draft_attempts_max:
        return {"ok": True, "message": "Elle y travaille déjà.", "draft": "", "asked": True}
    got = await call.act("teams.rediger", form(fixed={"message": m.ref}, instruction=call.arg("instruction", limit=4000)),
                         subject=conversation_key(m.account, m.conversation))
    return done(got, draft="", asked=True)


def _reply_mine(call: Call, draft_id: str) -> DraftSeen:
    """Une de ses réponses, dans un compte à elle : c'est le propriétaire qui en décide (ADR 0188, 0191)."""
    seen = latest(_state(call), draft_id) if draft_id else None
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
    return sum(1 for d in _state(call).drafts.values()
               if d.state == WAITING and not d.answered and mine.get(d.account, (None, ""))[1] == OWN)


def routes(api: MeApi) -> list[Route]:
    r = api.route
    return [r("/teams/accounts", list_accounts), r("/teams/conversations", conversations),
            r("/teams/thread", thread), r("/teams/replies", replies),
            r("/teams/send", send, write=True), r("/teams/prefill", prefill, write=True),
            r("/teams/reply/send", reply_send, write=True), r("/teams/reply/edit", reply_edit, write=True),
            r("/teams/reply/refuse", reply_refuse, write=True), r("/teams/reply/redo", reply_redo, write=True)]
