"""Mail, pour qui est connecté (ADR 0187, 0191) : ses boîtes, leurs dossiers et leurs messages, ce qu'elle en sait,
ses brouillons à relire, ses envoyés et ses contacts ; écrire, répondre, transférer, ranger, lui demander une réponse,
décider de ses brouillons.

Une boîte est à qui est connecté quand elle est à son nom (``personne:<clé>``), ou « à toi » (sans propriétaire
nommé) et qu'elle est une de ses propriétaires (ADR 0185) ; celles d'elle restent à la console. Un mail, un brouillon,
un envoi sont à la boîte qu'ils désignent : hors de ses boîtes, rien n'existe. Ce qui se fait passe par les actions du
courrier (``plugins/email/console``), au nom de la personne — ce qu'elle écrit part tout de suite et elle le sait
(``email.sent``), comme depuis la console.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from starlette.responses import Response
from starlette.routing import Route

from mika.app.moi import Call, Denied, MeApi, done, form, missing
from mika.inspector.framed import FRAME_CSP, FRAME_CSP_REMOTE, framed_html
from mika.plugins import email as email_p
from mika.plugins.email import WAITING, EmailState, Seen, exhausted, name_of
from mika.plugins.email.console.common import important, mail_key
from mika.ports.mail import AccountInfo, Mail, MailQuery, Sent, addresses, split_ref, to_fill
from mika.runtime.operations import perform
from mika.vocab.access import PERSON, SHARE_PREPARE, SHARE_READ, SHARE_USE, reaches

#: le niveau de qui est connecté sur une boîte : la sienne ; sinon, ce qu'on lui en partage (ADR 0188 : ``lire``,
#: ``preparer``, ``servir``)
OWN = "proprietaire"
#: ce que dit une liste : au plus tant de lignes par page
PAGE_MAX = 100
#: le début d'un mail dans une liste
SNIPPET = 180
#: les états d'une liste (« où elle est passée » : ce qu'elle a remarqué ; « réponse attendue » : ce qu'elle juge
#: appeler une réponse)
STATES = ("", "unread", "flagged", "noticed", "needs_reply")
#: les gestes de « ranger », tels que l'action du courrier les nomme
GESTURES = {"read": "lu", "unread": "non_lu", "archive": "archiver", "flag": "suivre", "unflag": "ne_plus_suivre",
            "trash": "corbeille"}
#: une image distante dans un mail HTML : ce que le cadre masque tant qu'on ne les permet pas (ADR 0175)
REMOTE_IMAGE = re.compile(r"""<img\b[^>]*\bsrc\s*=\s*["']?\s*https?:|url\(\s*["']?\s*https?:""", re.I)
#: les sortes qu'une pièce peut annoncer telles quelles ; les autres partent en ``application/octet-stream``
SAFE_MIMES = frozenset({"text/plain", "text/csv", "application/json", "image/png", "image/jpeg", "image/webp",
                        "image/gif", "application/pdf"})


# ── à qui ──


def boxes(call: Call) -> dict[str, tuple[AccountInfo, str]]:
    """Ses boîtes, par clé : la boîte et son niveau — les siennes, puis celles qu'on lui partage (ADR 0188)."""
    port = call.port("mail")
    if port is None:
        return {}
    p = email_p.params_of(call.frame)
    me, mine = call.me, PERSON + call.me.person
    out: dict[str, tuple[AccountInfo, str]] = {}
    for a in port.accounts():
        owner = p.owners.get(a.key, "")
        if (not owner and me.owner) or owner == mine:
            out[a.key] = (a, OWN)
        elif level := p.shares.get(a.key, {}).get(mine, ""):
            out[a.key] = (a, level)
    return out


def allows(level: str, need: str) -> bool:
    """Son niveau sur une boîte ouvre-t-il ce geste ? La sienne, tout ; un partage, ce qu'il atteint."""
    return level == OWN or reaches(level, need)


#: ce que dit un partage qui n'atteint pas le geste demandé
TOO_LOW = {SHARE_READ: "Cette boîte t'est partagée en lecture : tu la lis, sans y écrire ni la ranger.",
           SHARE_PREPARE: "Cette boîte t'est partagée en lecture et préparation : elle peut t'y préparer des réponses, "
                          "que son propriétaire approuve."}


def _box(call: Call, key: str, need: str = SHARE_USE) -> AccountInfo:
    found = boxes(call).get(key)
    if found is None:
        raise missing()
    if not allows(found[1], need):
        raise Denied(403, TOO_LOW.get(found[1], "Cette boîte ne t'est pas ouverte pour cela."))
    return found[0]


def owned(call: Call, key: str) -> AccountInfo:
    """Une boîte à elle (la régler, décider de ses brouillons) : un partage n'y suffit pas."""
    found = boxes(call).get(key)
    if found is None:
        raise missing()
    if found[1] != OWN:
        raise Denied(403, "Seul son propriétaire règle cette boîte et décide de ce qui en part.")
    return found[0]


def _mail_port(call: Call) -> Any:
    port = call.port("mail")
    if port is None:
        raise Denied(503, "Le courrier n'est pas branché.")
    return port


def _ref_mine(call: Call, ref: str, need: str = SHARE_READ) -> str:
    """Une référence de mail dans une de ses boîtes, à ce niveau (sinon : introuvable, ou refusé)."""
    if not ref:
        raise missing()
    _box(call, split_ref(ref)[0], need)
    return ref


async def _mail(call: Call, ref: str, need: str = SHARE_READ) -> Mail:
    """Un mail reçu ou parti d'une de ses boîtes. Un mail que la boîte n'a plus : introuvable ; un serveur muet :
    502 (jamais une panne non dite)."""
    port = _mail_port(call)
    _ref_mine(call, ref, need)
    try:
        found = port.cached_one(ref) or await port.document(ref)
    except (ValueError, FileNotFoundError):
        raise missing() from None
    except (OSError, RuntimeError):  # une erreur IMAP est une RuntimeError (``ImapError``) ou une OSError
        raise Denied(502, "Le serveur de cette boîte n'a pas répondu : réessaie plus tard.") from None
    if isinstance(found, Sent):  # un envoi, tel que certains ports le rendent : le même mail, vu de sa boîte
        info = port.account(found.account)
        found = Mail(found.message_id, info.address if info is not None else "", info.address if info else "",
                     found.subject, found.date, found.body, to=found.to, cc=found.cc, account=found.account,
                     attachments=found.attachments, seen=True)
    if found is None or found.account not in boxes(call):
        raise missing()
    return found


def _state(call: Call) -> EmailState:
    return call.frame.state(email_p.EMAIL.name)


def _copies(port: Any, m: Mail) -> tuple[bool, bool]:
    """``(sent, received)`` : parti de sa boîte (un envoi qu'elle sait, ou rangé dans son dossier « Envoyés »), et une
    copie reçue ailleurs que là (en copie à soi). Un mail parti sans copie reçue se transfère ; une copie reçue se
    répond."""
    cached = port.cached_one(m.ref)
    role = next((f.role for f in port.folders(cached.account) if f.name == cached.folder), "") if cached else ""
    return port.sent_mail(m.ref) is not None or role == "sent", cached is not None and role != "sent"


# ── ce qui se montre ──


def _ms(us: int) -> int:
    return us // 1000 if us else 0


def _people(field: str) -> list[dict[str, str]]:
    return [{"name": name, "address": address} for name, address in addresses(field or "")]


def _snippet(text: str) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= SNIPPET else flat[: SNIPPET - 1] + "…"


def _her(s: EmailState, ref: str, p: Any, level: str = OWN) -> dict[str, Any] | None:
    """Ce qu'elle a fait de ce mail : remarqué, jugé important, lu de son côté (à part de ton non-lu, ADR 0175), une
    réponse qu'elle prépare ou qu'on lui a demandée — sauf pour qui ne fait que lire la boîte (ADR 0188) : les réponses
    en préparation sont l'affaire de son propriétaire."""
    seen: Seen | None = s.mails.get(ref)
    prepares = allows(level, SHARE_PREPARE)
    waiting = next((d for d in s.drafts.values() if d.mail == ref and d.state == WAITING), None) if prepares else None
    asked = prepares and ref in s.asked and not exhausted(s, ref, p)
    if seen is None and waiting is None and not asked:
        return None
    return {"noticed": seen is not None, "important": bool(seen is not None and important(seen, p)),
            "needs_reply": bool(seen is not None and seen.needs_reply),
            "read": bool(seen is not None and seen.read and seen.by_her),
            "how": seen.how if seen is not None and seen.by_her else "",
            "draft": waiting.draft if waiting is not None else "", "asked": asked}


def row(m: Mail, s: EmailState, p: Any, level: str = OWN) -> dict[str, Any]:
    return {"ref": m.ref, "box": m.account, "folder": m.folder,
            "from": {"name": name_of(m.sender) or m.address, "address": m.address}, "to": _people(m.to),
            "subject": m.subject, "snippet": _snippet(m.body), "date": _ms(m.date), "seen": m.seen,
            "flagged": m.flagged, "answered": m.answered, "attachments": len(m.attachments), "html": m.has_html,
            "bulk": m.bulk, "her": _her(s, m.ref, p, level)}


def _box_json(call: Call, a: AccountInfo, level: str) -> dict[str, Any]:
    port = call.port("mail")
    status = port.status(a.key)
    folders = [{"name": f.name, "label": f.label, "role": f.role, "polled": f.polled, "total": f.total,
                "unseen": f.unseen} for f in port.folders(a.key)]
    s = _state(call)
    waiting = sum(1 for d in s.drafts.values() if d.account == a.key and d.state == WAITING) \
        if allows(level, SHARE_PREPARE) else 0
    return {"key": a.key, "name": a.name, "address": a.address, "level": level, "ready": a.ready,
            "voice": a.voice,
            "can_send": a.can_send, "enabled": a.enabled, "signature": a.signature,
            "last_poll": _ms(status.last_poll), "error": status.error, "folders": folders, "drafts_waiting": waiting,
            # une boîte partagée se montre à son nom (« Boîte de Léa », ADR 0188)
            "owner_name": email_p.approver_name(call.frame, a.key) if level != OWN else "",
            # « à toi » : commune à ses propriétaires (on ne la leur partage pas : elle est déjà à elles)
            "common": level == OWN and not email_p.params_of(call.frame).owners.get(a.key, "")}


# ── lire ──


async def list_boxes(call: Call) -> dict[str, Any]:
    p = email_p.params_of(call.frame)
    found = [_box_json(call, a, level) for a, level in boxes(call).values()]
    return {"boxes": found, "read_on_open": p.read_on_open, "plugged": call.port("mail") is not None}


async def messages(call: Call) -> dict[str, Any]:
    port = _mail_port(call)
    mine = boxes(call)
    box = call.arg("box", limit=40)
    if box and box not in mine:
        raise missing()
    keys = (box,) if box else tuple(mine)
    state = call.arg("state", limit=20)
    if state not in STATES:
        raise Denied(400, "« state » : unread, flagged, noticed ou needs_reply.")
    page, size = call.number("page", 1), call.number("size", 25, high=PAGE_MAX)
    s, p = _state(call), email_p.params_of(call.frame)
    if not keys:
        return {"items": [], "total": 0, "page": 1, "size": size}
    refs = tuple(k for k, seen in s.mails.items() if seen.account in keys
                 and (state == "noticed" or (seen.needs_reply and not seen.read))) \
        if state in ("noticed", "needs_reply") else None
    query = MailQuery(accounts=keys, folder=call.arg("folder", limit=300), text=call.arg("q", limit=200).strip(),
                      seen=False if state == "unread" else None, flagged=True if state == "flagged" else None,
                      refs=refs)
    got = port.messages_page(query, page, size)
    return {"items": [row(m, s, p, mine.get(m.account, (None, OWN))[1]) for m in got.items], "total": got.total,
            "page": got.number, "size": got.size}


async def message(call: Call) -> dict[str, Any]:
    """Un mail entier : ses en-têtes, son texte, ses pièces, s'il a un HTML (servi à part, dans son cadre), ses
    images distantes, et ce qu'elle en sait."""
    m = await _mail(call, call.arg("ref"))
    port = call.port("mail")
    s, p = _state(call), email_p.params_of(call.frame)
    level = boxes(call)[m.account][1]
    her = _her(s, m.ref, p, level)
    seen = s.mails.get(m.ref)
    if her is not None and seen is not None and seen.summary_ref:
        store = call.port("store")
        her["summary"] = store.content([seen.summary_ref]).get(seen.summary_ref, "") if store is not None else ""
    remote = bool(m.html) and bool(REMOTE_IMAGE.search(m.html[:400_000]))
    sent, received = _copies(port, m)
    return {**row(m, s, p, level), "her": her, "cc": _people(m.cc), "reply_to": m.reply_to, "in_reply_to": m.in_reply_to,
            "body": m.body, "complete": m.complete, "sent": sent, "received": received,
            "attachments": [{"part": str(i), "name": a.name, "mime": a.mime, "size": a.size}
                            for i, a in enumerate(m.attachments)],
            "images": {"remote": remote, "shown": remote and call.me.owner and port.images_shown(m.address)}}


def _frame_csp(api: MeApi, remote: bool) -> str:
    """La politique du cadre de la console, posable par le client web (ses origines), pas par une autre page."""
    base = FRAME_CSP_REMOTE if remote else FRAME_CSP
    return base.replace("frame-ancestors 'self'", "frame-ancestors 'self' " + " ".join(api.origins)) \
        if api.origins else base


def frame_route(api: MeApi) -> Any:
    async def frame(call: Call) -> Response:
        """Le HTML d'un mail, purgé, dans son document isolé (ADR 0169) ; ses images distantes seulement si on les a
        permises, pour cette fois (``images=1``) ou pour son expéditeur."""
        m = await _mail(call, call.arg("ref"))
        if not m.html:
            raise missing()
        port = call.port("mail")
        remote = call.flag("images") or (call.me.owner and port.images_shown(m.address))
        page = framed_html(m.html, tuple(port.inline_images(m.ref)), remote=remote)
        return Response(page, media_type="text/html; charset=utf-8", headers={
            "Content-Security-Policy": _frame_csp(api, remote), "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "Cache-Control": "no-store"})

    return frame


async def file(call: Call) -> Response:
    """Une pièce jointe (son numéro, ``part``), toujours en téléchargement, jamais rendue dans une page."""
    m = await _mail(call, call.arg("ref"))
    part = call.arg("part", limit=5)
    if not part.isdecimal() or int(part) >= len(m.attachments):
        raise missing()
    try:
        got = await call.port("mail").file(m.ref, part)
    except FileNotFoundError:
        raise missing() from None
    except (OSError, RuntimeError, ValueError):
        raise Denied(502, "Cette pièce n'a pas pu être récupérée : vérifie la connexion de la boîte.") from None
    base = str(got.mime or "").split(";", 1)[0].strip().lower()
    name = "".join(ch for ch in got.name.replace("\\", "/").rsplit("/", 1)[-1] if ch.isprintable())[:200]
    return Response(got.data, media_type=base if base in SAFE_MIMES else "application/octet-stream", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name or "piece", safe=""),
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
        "Content-Security-Policy": "sandbox; default-src 'none'"})


async def drafts(call: Call) -> dict[str, Any]:
    """Ses brouillons dans tes boîtes (ADR 0191) : ce qui attend ta décision, exactement ce qui partira, puis ce qui
    est décidé — le plus récent d'abord. Dans une boîte qu'on te partage, seulement si ton partage prépare (ADR 0188) :
    ils attendent alors l'accord de son propriétaire."""
    port = _mail_port(call)
    mine = boxes(call)
    s = _state(call)
    out = []
    for d in sorted(s.drafts.values(), key=lambda d: (-d.at, -d.proposal)):
        if d.account not in mine or not allows(mine[d.account][1], SHARE_PREPARE):
            continue
        kept = port.draft(d.draft)
        preview = port.preview(d.draft) if d.state == WAITING else None
        original = port.cached_one(d.mail) if d.mail else None
        out.append({
            "id": d.draft, "box": d.account, "state": d.state, "at": _ms(d.at), "decided_at": _ms(d.decided_at),
            "by": d.by, "note": d.note, "in_reply_to": d.mail, "asked": d.asked,
            "voice": mine[d.account][0].voice, "decides": mine[d.account][1] == OWN,
            "original": {"subject": original.subject, "from": name_of(original.sender) or original.address}
            if original is not None else None,
            "to": kept.to if kept else "", "cc": kept.cc if kept else "", "subject": kept.subject if kept else "",
            "body": kept.body if kept else "", "quote": kept.quote if kept else False,
            "edited": bool(kept and kept.edited_by),
            "preview": {"sender": preview.sender, "to": preview.to, "cc": preview.cc, "subject": preview.subject,
                        "text": preview.text, "digest": preview.digest, "blocked": preview.blocked}
            if preview is not None else None,
            "to_fill": bool(kept and to_fill(kept.subject, kept.body)),
        })
        if len(out) >= PAGE_MAX:
            break
    return {"items": out}


async def sent(call: Call) -> dict[str, Any]:
    port = _mail_port(call)
    mine = boxes(call)
    box = call.arg("box", limit=40)
    if box and box not in mine:
        raise missing()
    # boîte par boîte : une page prise sur tout le serveur laisserait de côté ses envois derrière ceux des autres
    found = [x for key in ([box] if box else list(mine)) for x in port.sent_mails(PAGE_MAX, account=key)
             if x.account == key]
    items = sorted(found, key=lambda x: -x.date)[:PAGE_MAX]
    return {"items": [{"ref": x.ref, "box": x.account, "to": _people(x.to), "cc": _people(x.cc),
                       "subject": x.subject, "snippet": _snippet(x.body), "date": _ms(x.date), "by": x.by,
                       "draft": x.draft, "attachments": len(x.attachments)} for x in items]}


async def contacts(call: Call) -> dict[str, Any]:
    """Ses correspondants (ceux du courrier relevé), pour écrire : cherchés par nom ou adresse."""
    port = _mail_port(call)
    mine = boxes(call)
    box = call.arg("box", limit=40)
    if box and box not in mine:
        raise missing()
    keys = [box] if box else list(mine)
    text = call.arg("q", limit=100).strip()
    size = call.number("size", 25, high=PAGE_MAX)
    found: dict[str, Any] = {}
    for key in keys:
        for c in port.contacts_page(key, text, 1, size).items:
            known = found.get(c.address)
            if known is None or c.last > known.last:
                found[c.address] = c
    ordered = sorted(found.values(), key=lambda c: (-c.last, c.address))[:size]
    return {"items": [{"address": c.address, "name": c.name, "received": c.received, "sent": c.sent,
                       "last": _ms(c.last)} for c in ordered]}


# ── écrire, ranger ──


def _sendable(call: Call, key: str) -> AccountInfo:
    box = _box(call, key, SHARE_USE)
    if not box.can_send:
        raise Denied(409, "Cette boîte ne peut pas envoyer : sa connexion n'est pas prête (Paramètres › Comptes mail).")
    return box


async def send(call: Call) -> dict[str, Any]:
    """Un mail nouveau, depuis une de ses boîtes : il part tout de suite, et elle le sait."""
    box = _sendable(call, call.arg("box", limit=40))
    got = await call.act("email.ecrire", form(account=box.key, to=call.arg("to", limit=300),
                                              cc=call.arg("cc", limit=300), subject=call.arg("subject", limit=200),
                                              body=call.arg("body", limit=20_000)))
    return done(got)


#: ce qu'elle apprend d'un brouillon devenu sans objet : quelqu'un a répondu lui-même
ANSWERED = "Répondu autrement, depuis le client : ce brouillon n'a plus lieu d'être."


async def reply(call: Call) -> dict[str, Any]:
    """Une réponse, depuis la boîte du mail reçu (pas à un mail qui n'est qu'un envoi de ta boîte : on le transfère).
    Ses brouillons qui attendaient pour ce mail sont alors refusés (elle le sait), quel que soit qui répond : une
    réponse est partie, une seconde ne partira pas. C'est la seule fois où un partage touche aux brouillons du
    propriétaire : répondre demande « s'en servir », le niveau qui agit comme lui (ADR 0188)."""
    m = await _mail(call, call.arg("ref"))
    sent, received = _copies(call.port("mail"), m)
    if sent and not received:  # parti de sa boîte, sans copie reçue : on le transfère
        raise Denied(409, "On ne répond pas à un mail parti de ta boîte : transfère-le, ou réponds au mail reçu.")
    _sendable(call, m.account)
    got = await call.act("email.repondre", form(to=call.arg("to", limit=300), cc=call.arg("cc", limit=300),
                                                subject=call.arg("subject", limit=200),
                                                body=call.arg("body", limit=20_000), quote=call.flag("quote"),
                                                fixed={"reply_to": m.ref}))
    answer = done(got)
    # ses brouillons pour ce mail ne partiront plus : la réponse est partie
    for d in [d for d in _state(call).drafts.values() if d.mail == m.ref and d.state == WAITING]:
        await perform(call.kernel, "email.refuser_brouillon", form(fixed={"draft": d.draft}, note=ANSWERED),
                      by=call.me.handle)
    return answer


async def forward(call: Call) -> dict[str, Any]:
    m = await _mail(call, call.arg("ref"))
    _sendable(call, m.account)
    got = await call.act("email.transferer", form(fixed={"original": m.ref}, to=call.arg("to", limit=300),
                                                  cc=call.arg("cc", limit=300), subject=call.arg("subject", limit=200),
                                                  body=call.arg("body", limit=20_000),
                                                  attachments=call.flag("attachments")))
    return done(got)


async def tidy(call: Call) -> dict[str, Any]:
    """Un geste sur des mails de ses boîtes (sur le serveur) : lu, non lu, archiver, suivre, ne plus suivre,
    corbeille."""
    gesture = GESTURES.get(call.arg("gesture", limit=20))
    if gesture is None:
        raise Denied(400, "« gesture » : read, unread, archive, flag, unflag ou trash.")
    refs = [_ref_mine(call, r, SHARE_USE) for r in call.strings("refs")]
    if not refs:
        raise Denied(400, "« refs » : au moins un mail.")
    got = await call.act("email.ranger", form(mails=[mail_key(r) for r in refs], geste=gesture))
    return done(got)


async def prefill(call: Call) -> dict[str, Any]:
    """« Préremplir avec Mika » (ADR 0191) : elle écrit une réponse à ce mail à son prochain moment de travail, dans
    ses brouillons ; la saisie la reprend quand elle arrive. Une demande en cours, ou un brouillon qui attend déjà,
    se rendent tels quels. Jamais pour un mail parti de ta boîte, même si une copie t'en est revenue : on y répond
    soi-même."""
    m = await _mail(call, call.arg("ref"), SHARE_PREPARE)
    if _copies(call.port("mail"), m)[0]:
        raise Denied(409, "Ce mail est parti de ta boîte : elle n'y prépare pas de réponse.")
    s, p = _state(call), email_p.params_of(call.frame)
    waiting = next((d for d in s.drafts.values() if d.mail == m.ref and d.state == WAITING), None)
    if waiting is not None:
        return {"ok": True, "message": "Elle a déjà préparé une réponse.", "draft": waiting.draft, "asked": False}
    if m.ref in s.asked and not exhausted(s, m.ref, p):
        return {"ok": True, "message": "Elle y travaille déjà.", "draft": "", "asked": True}
    if not _box(call, m.account, SHARE_PREPARE).can_send:
        raise Denied(409, "Cette boîte ne peut pas envoyer : sa connexion n'est pas prête (Paramètres › Comptes mail).")
    got = await call.act("email.rediger", form(instruction=call.arg("instruction", limit=4000)),
                         subject=mail_key(m.ref))
    return done(got, draft="", asked=True)


def _draft_mine(call: Call, draft_id: str) -> Any:
    """Un de ses brouillons, dans une boîte à elle : c'est le propriétaire qui en décide (ADR 0188, 0191)."""
    port = _mail_port(call)
    d = port.draft(draft_id) if draft_id else None
    if d is None or d.account not in boxes(call):
        raise missing()
    owned(call, d.account)
    return d


async def draft_send(call: Call) -> dict[str, Any]:
    """L'envoyer tel qu'il était montré (``seen`` : le condensé de l'aperçu lu) ; un ``[À COMPLÉTER`` le bloque."""
    d = _draft_mine(call, call.arg("id", limit=100))
    got = await call.act("email.envoyer_brouillon", form(fixed={"draft": d.id, "seen": call.arg("seen", limit=100)}))
    return done(got)


async def draft_edit(call: Call) -> dict[str, Any]:
    d = _draft_mine(call, call.arg("id", limit=100))
    got = await call.act("email.retoucher", form(fixed={"draft": d.id}, to=call.arg("to", limit=300),
                                                 cc=call.arg("cc", limit=300),
                                                 subject=call.arg("subject", limit=200),
                                                 body=call.arg("body", limit=20_000), quote=call.flag("quote")))
    return done(got)


async def draft_refuse(call: Call) -> dict[str, Any]:
    d = _draft_mine(call, call.arg("id", limit=100))
    got = await call.act("email.refuser_brouillon", form(fixed={"draft": d.id}, note=call.arg("note", limit=500)))
    return done(got)


async def draft_redo(call: Call) -> dict[str, Any]:
    d = _draft_mine(call, call.arg("id", limit=100))
    got = await call.act("email.reprendre", form(fixed={"draft": d.id},
                                                 instruction=call.arg("instruction", limit=4000)))
    return done(got)


async def images(call: Call) -> dict[str, Any]:
    """Les images distantes de cet expéditeur : toujours (``shown``), ou plus jamais (ADR 0175). La liste est celle du
    serveur, la même pour tous ses lecteurs : seule une de ses propriétaires la règle (une autre personne charge ses
    images « cette fois », ``/mail/frame?images=1``, sans rien décider pour les autres)."""
    if not call.me.owner:
        raise Denied(403, "Afficher toujours les images d'un expéditeur se règle pour tout le serveur : c'est l'affaire "
                          "de ses propriétaires. Tu peux les afficher cette fois.")
    m = await _mail(call, call.arg("ref"), SHARE_USE)
    key = "email.images" if call.flag("shown") else "email.images_masquer"
    got = await call.act(key, form(), subject=mail_key(m.ref))
    return done(got)


async def poll(call: Call) -> dict[str, Any]:
    box = _box(call, call.arg("box", limit=40), SHARE_USE)
    call.probe()
    got = await call.act("email.relever_compte", form(), subject=box.key)
    return done(got)


def count(call: Call) -> int:
    """Pour la barre du haut : les non-lus de la réception de ses boîtes, et ses brouillons qui attendent ta décision —
    dans tes boîtes seulement (dans une boîte partagée, c'est son propriétaire qui décide)."""
    port = call.port("mail")
    if port is None:
        return 0
    mine = boxes(call)
    unseen = sum(f.unseen for key in mine for f in port.folders(key) if f.role == "inbox" or f.name == "INBOX")
    s = _state(call)
    return unseen + sum(1 for d in s.drafts.values() if d.state == WAITING and mine.get(d.account, (None, ""))[1] == OWN)


def routes(api: MeApi) -> list[Route]:
    r = api.route
    return [r("/mail/boxes", list_boxes), r("/mail/messages", messages), r("/mail/message", message),
            r("/mail/frame", frame_route(api), raw=True), r("/mail/file", file, raw=True),
            r("/mail/drafts", drafts), r("/mail/sent", sent), r("/mail/contacts", contacts),
            r("/mail/send", send, write=True), r("/mail/reply", reply, write=True),
            r("/mail/forward", forward, write=True), r("/mail/tidy", tidy, write=True),
            r("/mail/prefill", prefill, write=True), r("/mail/images", images, write=True),
            r("/mail/poll", poll, write=True), r("/mail/draft/send", draft_send, write=True),
            r("/mail/draft/edit", draft_edit, write=True), r("/mail/draft/refuse", draft_refuse, write=True),
            r("/mail/draft/redo", draft_redo, write=True)]
