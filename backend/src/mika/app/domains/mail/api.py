"""Mail, pour qui est connecté (ADR 0187, 0191) : ses boîtes, leurs dossiers et leurs messages, ce qu'elle en sait,
ses brouillons à relire, ses envoyés et ses contacts ; écrire, répondre, transférer, ranger, lui demander une réponse,
décider de ses brouillons.

Une boîte est à qui est connecté quand elle est à son nom (``personne:<clé>``), ou « à toi » (sans propriétaire
nommé) et qu'elle est une de ses propriétaires (ADR 0185) ; celles d'elle restent à la console. Un mail, un brouillon,
un envoi sont à la boîte qu'ils désignent : hors de ses boîtes, rien n'existe. Ce qui se fait passe par les actions du
courrier (``plugins/email/inspect``), au nom de la personne — ce qu'elle écrit part tout de suite et elle le sait
(``email.sent``), comme depuis la console.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from starlette.responses import Response
from starlette.routing import Route

from mika.adapters.web.app import safe_mime
from mika.app.connections import ConnectionSettings
from mika.app.domains.mail import account_settings
from mika.app.me.api import Call, Denied, MeApiBase, done, form, missing
from mika.app.me.common import allows, held_by, millis, only_owner, opened, snippet, work_of
from mika.contracts import email as email_c
from mika.inspector.framed import FRAME_CSP, FRAME_CSP_REMOTE, framed_html
from mika.plugins import email as email_p
from mika.plugins.email import WAITING, EmailState, Seen, exhausted, name_of
from mika.plugins.email.inspect.common import important, mail_key
from mika.ports.drafts import to_fill
from mika.ports.mail import AccountInfo, Contact, Mail, MailQuery, Sent, addresses, split_ref
from mika.vocab.access import SHARE_PREPARE, SHARE_READ, SHARE_USE
from mika.vocab.ownership import OWNED

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
#: le geste qui range dans un dossier de la boîte (``folder``) : l'action « Déplacer », mail par mail (ADR 0200)
MOVE = "move"
#: une image distante dans un mail HTML : ce que le cadre masque tant qu'on ne les permet pas (ADR 0175)
REMOTE_IMAGE = re.compile(r"""<img\b[^>]*\bsrc\s*=\s*["']?\s*https?:|url\(\s*["']?\s*https?:""", re.I)


# ── à qui ──


def boxes(call: Call) -> dict[str, tuple[AccountInfo, str]]:
    """Ses boîtes, par clé : la boîte et son niveau — les siennes, puis celles qu'on lui partage (ADR 0188)."""
    return held_by(call, call.port("mail"), email_p.params_of)


#: ce que dit un partage qui n'atteint pas le geste demandé
TOO_LOW = {SHARE_READ: "Cette boîte t'est partagée en lecture : tu la lis, sans y écrire ni la ranger.",
           SHARE_PREPARE: "Cette boîte t'est partagée en lecture et préparation : elle peut t'y préparer des réponses, "
                          "que son propriétaire approuve."}


def _box(call: Call, key: str, need: str = SHARE_USE) -> AccountInfo:
    return opened(boxes(call).get(key), need, TOO_LOW, "Cette boîte ne t'est pas ouverte pour cela.")


def owned(call: Call, key: str) -> AccountInfo:
    """Une boîte à elle (la régler, décider de ses brouillons) : un partage n'y suffit pas."""
    return only_owner(boxes(call).get(key), "Seul son propriétaire règle cette boîte et décide de ce qui en part.")


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
    """Un mail reçu ou parti d'une de ses boîtes, entier : un mail relevé en partie se complète sur le serveur
    (``document`` rend la copie gardée quand elle est complète, sans le joindre). Si le serveur ne la donne pas, la
    copie gardée se montre telle quelle (``complete`` le dit) : un mail gardé se lit serveur coupé. Un mail que la
    boîte n'a plus : introuvable ; un serveur muet sans copie gardée : 502 (jamais une panne non dite)."""
    port = _mail_port(call)
    _ref_mine(call, ref, need)
    kept = port.cached_one(ref)
    try:
        found = await port.document(ref) or kept
    except (ValueError, FileNotFoundError):
        if kept is None:
            raise missing() from None
        found = kept
    except (OSError, RuntimeError):  # une erreur IMAP est une RuntimeError (``ImapError``) ou une OSError
        if kept is None:
            raise Denied(502, "Le serveur de cette boîte n'a pas répondu : réessaie plus tard.") from None
        found = kept
    if isinstance(found, Sent):  # un envoi, tel que certains ports le rendent : le même mail, vu de sa boîte
        info = port.account(found.account)
        found = Mail(found.message_id, info.address if info is not None else "", info.address if info else "",
                     found.subject, found.date, found.body, to=found.to, cc=found.cc, account=found.account,
                     attachments=found.attachments, seen=True)
    if found is None or found.account not in boxes(call):
        raise missing()
    return found


def state(call: Call) -> EmailState:
    """Ce que le courrier sait de sa vie (``EmailState``) : ses mails remarqués, ses envois, ses brouillons, ses
    demandes. Les réglages de ses boîtes le lisent aussi (``account_settings.py``, les clés qui ont laissé une trace)."""
    return call.frame.state(email_p.EMAIL.name)


def _copies(port: Any, m: Mail) -> tuple[bool, bool]:
    """``(sent, received)`` : parti de sa boîte (un envoi qu'elle sait, ou rangé dans son dossier « Envoyés »), et une
    copie reçue ailleurs que là (en copie à soi). Un mail parti sans copie reçue se transfère ; une copie reçue se
    répond."""
    cached = port.cached_one(m.ref)
    role = next((f.role for f in port.folders(cached.account) if f.name == cached.folder), "") if cached else ""
    return port.sent_mail(m.ref) is not None or role == "sent", cached is not None and role != "sent"


# ── ce qui se montre ──


def _people(field: str, names: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Les personnes d'un en-tête ; un nom absent se complète de ``names`` (les correspondants de la boîte)."""
    known = names or {}
    return [{"name": name or known.get(address.lower(), ""), "address": address}
            for name, address in addresses(field or "")]


def _names(port: Any, key: str) -> dict[str, str]:
    """Les noms connus des correspondants récents d'une boîte, par adresse : ce qu'un envoi, un brouillon montrent à
    la place d'une adresse nue, comme la réception."""
    return {c.address.lower(): c.name for c in port.contacts_page(key, "", 1, PAGE_MAX).items if c.name}


def _keys(mine: dict[str, tuple[AccountInfo, str]], box: str) -> tuple[str, ...]:
    """Les boîtes d'une vue : celle qu'on demande ; sinon les tiennes et celles qu'on te partage pour préparer ou t'en
    servir. Une boîte qu'on ne te partage qu'en lecture ne compte dans aucune vue commune (ADR 0200) : on l'ouvre à
    part, sous « Partagée avec toi »."""
    if box:
        if box not in mine:
            raise missing()
        return (box,)
    return tuple(key for key, (_, level) in mine.items() if level != SHARE_READ)


def _her(s: EmailState, ref: str, p: Any, level: str = OWNED, folder: str = "") -> dict[str, Any] | None:
    """Ce qu'elle a fait de ce mail : remarqué, jugé important, lu de son côté (à part de ton non-lu, ADR 0175), une
    réponse qu'elle prépare ou qu'on lui a demandée — sauf pour qui ne fait que lire la boîte (ADR 0188) : les réponses
    en préparation sont l'affaire de son propriétaire ; ce que tes consignes de tri en ont fait (ADR 0243) : prévenir,
    et le dossier où elles l'ont rangé, tant qu'il y est (``folder`` : là où il est)."""
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
            "draft": waiting.draft if waiting is not None else "", "asked": asked,
            "alert": bool(seen is not None and seen.alert),
            "filed": seen.file_to if seen is not None and seen.file_to and seen.file_to == folder else ""}


def _work(call: Call, s: EmailState, ref: str, her: dict[str, Any] | None, level: str) -> dict[str, Any] | None:
    """Où elle en est d'une réponse à ce mail (ADR 0306) : demandée (``her.asked``) et pas commencée, elle s'y met
    depuis la demande ; sa tâche en cours, ce que le pipeline en tient. Rien pour qui ne fait que lire la boîte."""
    if not allows(level, SHARE_PREPARE):
        return None
    ask = s.asked.get(ref) if her is not None and her["asked"] else None
    return work_of(call, email_p.EMAIL.name, lambda r: r == ref, ask.at if ask is not None else 0)


async def progress(call: Call) -> dict[str, Any]:
    """Où elle en est d'une réponse à ce mail, en direct (ADR 0306) : ce qu'un client relit toutes les deux secondes
    tant qu'elle y travaille, sans relire le mail (ni joindre son serveur) — ``work``, ``asked``, et le brouillon qui
    attend (``draft``), dès qu'il est arrivé."""
    ref = _ref_mine(call, call.arg("ref", limit=400))
    s, p = state(call), email_p.params_of(call.frame)
    level = boxes(call)[split_ref(ref)[0]][1]
    her = _her(s, ref, p, level)
    return {"work": _work(call, s, ref, her, level), "asked": bool(her and her["asked"]),
            "draft": her["draft"] if her is not None else ""}


#: ce que son tri a fait d'un mail remarqué, dit aux clients (ADR 0240)
TRIAGE_SHOWN = {email_c.TRIAGE_MODEL: "read", email_c.TRIAGE_FALLBACK: "guessed", email_c.TRIAGE_BULK: "bulk"}


def triage_of(s: EmailState, ref: str, waiting: frozenset[str]) -> str:
    """Son tri et ce mail : ``read`` (le modèle l'a lu), ``guessed`` (le repli seul), ``bulk`` (un envoi en masse,
    jamais montré au modèle), ``waiting`` (relevé, pas encore trié : au relevé suivant) ; vide sinon (un mail d'avant
    sa boîte, d'un dossier qu'elle ne relève pas, ou remarqué avant que le journal le dise)."""
    seen = s.mails.get(ref)
    if seen is not None:
        return TRIAGE_SHOWN.get(seen.triage, "")
    return "waiting" if ref in waiting else ""


def row(m: Mail, s: EmailState, p: Any, level: str = OWNED, waiting: frozenset[str] = frozenset()) -> dict[str, Any]:
    return {"ref": m.ref, "box": m.account, "folder": m.folder,
            "from": {"name": name_of(m.sender) or m.address, "address": m.address}, "to": _people(m.to),
            "subject": m.subject, "snippet": snippet(m.body, SNIPPET), "date": millis(m.date), "seen": m.seen,
            "flagged": m.flagged, "answered": m.answered, "attachments": len(m.attachments), "html": m.has_html,
            "bulk": m.bulk, "her": _her(s, m.ref, p, level, m.folder), "triage": triage_of(s, m.ref, waiting)}


def _box_json(call: Call, a: AccountInfo, level: str) -> dict[str, Any]:
    port = call.port("mail")
    status = port.status(a.key)
    folders = [{"name": f.name, "label": f.label, "role": f.role, "polled": f.polled, "total": f.total,
                "unseen": f.unseen} for f in port.folders(a.key)]
    s = state(call)
    waiting = sum(1 for d in s.drafts.values() if d.account == a.key and d.state == WAITING) \
        if allows(level, SHARE_PREPARE) else 0
    return {"key": a.key, "name": a.name, "address": a.address, "level": level, "ready": a.ready,
            "voice": a.voice,
            "can_send": a.can_send, "enabled": a.enabled, "signature": a.signature,
            "last_poll": millis(status.last_poll), "error": status.error, "folders": folders, "drafts_waiting": waiting,
            # une boîte partagée se montre à son nom (« Boîte de Léa », ADR 0188)
            "owner_name": email_p.approver_name(call.frame, a.key) if level != OWNED else "",
            # « à toi » : commune à ses propriétaires (on ne la leur partage pas : elle est déjà à elles)
            "common": level == OWNED and not email_p.params_of(call.frame).owners.get(a.key, "")}


# ── lire ──


async def list_boxes(call: Call) -> dict[str, Any]:
    p = email_p.params_of(call.frame)
    found = [_box_json(call, a, level) for a, level in boxes(call).values()]
    # l'instance a son application Microsoft : une boîte Microsoft n'a pas à donner la sienne (ADR 0238)
    settings = call.api.settings
    return {"boxes": found, "read_on_open": p.read_on_open, "plugged": call.port("mail") is not None,
            "microsoft_app": settings is not None and bool(settings.of(ConnectionSettings).microsoft_application())}


async def messages(call: Call) -> dict[str, Any]:
    port = _mail_port(call)
    mine = boxes(call)
    keys = _keys(mine, call.arg("box", limit=40))
    listed = call.arg("state", limit=20)
    if listed not in STATES:
        raise Denied(400, "« state » : unread, flagged, noticed ou needs_reply.")
    page, size = call.number("page", 1), call.number("size", 25, high=PAGE_MAX)
    s, p = state(call), email_p.params_of(call.frame)
    if not keys:
        return {"items": [], "total": 0, "page": 1, "size": size}
    refs = tuple(k for k, seen in s.mails.items() if seen.account in keys
                 and (listed == "noticed" or (seen.needs_reply and not seen.read))) \
        if listed in ("noticed", "needs_reply") else None
    query = MailQuery(accounts=keys, folder=call.arg("folder", limit=300), text=call.arg("q", limit=200).strip(),
                      seen=False if listed == "unread" else None, flagged=True if listed == "flagged" else None,
                      refs=refs)
    got = port.messages_page(query, page, size)
    waiting = port.waiting()
    return {"items": [row(m, s, p, mine.get(m.account, (None, OWNED))[1], waiting) for m in got.items],
            "total": got.total,
            "page": got.number, "size": got.size}


async def message(call: Call) -> dict[str, Any]:
    """Un mail entier : ses en-têtes, son texte, ses pièces, s'il a un HTML (servi à part, dans son cadre), ses
    images distantes, ce qu'elle en sait, et où elle en est d'une réponse qu'elle y prépare (``work``, ADR 0306)."""
    m = await _mail(call, call.arg("ref"))
    port = call.port("mail")
    s, p = state(call), email_p.params_of(call.frame)
    level = boxes(call)[m.account][1]
    her = _her(s, m.ref, p, level, m.folder)
    seen = s.mails.get(m.ref)
    if her is not None and seen is not None and seen.summary_ref:
        store = call.port("store")
        her["summary"] = store.content([seen.summary_ref]).get(seen.summary_ref, "") if store is not None else ""
    remote = bool(m.html) and bool(REMOTE_IMAGE.search(m.html[:400_000]))
    sent, received = _copies(port, m)
    work = _work(call, s, m.ref, her, level)
    return {**row(m, s, p, level, port.waiting()), "her": her, "work": work, "cc": _people(m.cc), "reply_to": m.reply_to, "in_reply_to": m.in_reply_to,
            "body": m.body, "complete": m.complete, "sent": sent, "received": received,
            "attachments": [{"part": str(i), "name": a.name, "mime": a.mime, "size": a.size}
                            for i, a in enumerate(m.attachments)],
            "images": {"remote": remote, "shown": remote and call.me.owner and port.images_shown(m.address)}}


def _frame_csp(api: MeApiBase, remote: bool) -> str:
    """La politique du cadre de la console, posable par le client web (ses origines), pas par une autre page."""
    base = FRAME_CSP_REMOTE if remote else FRAME_CSP
    return base.replace("frame-ancestors 'self'", "frame-ancestors 'self' " + " ".join(api.origins)) \
        if api.origins else base


def frame_route(api: MeApiBase) -> Any:
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
    name = "".join(ch for ch in got.name.replace("\\", "/").rsplit("/", 1)[-1] if ch.isprintable())[:200]
    # la sorte qu'elle annonce, si elle est sûre (la liste du serveur web, ``safe_mime``) ; toujours en pièce jointe
    return Response(got.data, media_type=safe_mime(got.mime), headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name or "piece", safe=""),
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
        "Content-Security-Policy": "sandbox; default-src 'none'"})


async def drafts(call: Call) -> dict[str, Any]:
    """Ses brouillons dans tes boîtes (ADR 0191) : ce qui attend ta décision, exactement ce qui partira, puis ce qui
    est décidé — le plus récent d'abord. Dans une boîte qu'on te partage, seulement si ton partage prépare (ADR 0188) :
    ils attendent alors l'accord de son propriétaire."""
    port = _mail_port(call)
    mine = boxes(call)
    s = state(call)
    out = []
    names: dict[str, dict[str, str]] = {}
    # la note de qui a décidé est gardée à part (l'oubli l'atteint) : relue d'un coup, et seulement sur une boîte à
    # qui est connecté — ce que son propriétaire a dit à Mika en refusant ne se lit pas par un partage (comme Teams)
    listed = [d for d in sorted(s.drafts.values(), key=lambda d: (-d.at, -d.proposal))
              if d.account in mine and allows(mine[d.account][1], SHARE_PREPARE)][:PAGE_MAX]
    refs = [d.note_ref for d in listed if d.note_ref and mine[d.account][1] == OWNED]
    store = call.port("store") if refs else None
    notes = dict(store.content(refs)) if store is not None else {}
    for d in listed:
        if d.account not in names:
            names[d.account] = _names(port, d.account)
        kept = port.draft(d.draft)
        preview = port.preview(d.draft) if d.state == WAITING else None
        original = port.cached_one(d.mail) if d.mail else None
        out.append({
            "id": d.draft, "box": d.account, "state": d.state, "at": millis(d.at), "decided_at": millis(d.decided_at),
            "by": d.by, "note": (notes.get(d.note_ref) or "") if d.note_ref else d.note, "in_reply_to": d.mail,
            "asked": d.asked,
            "voice": mine[d.account][0].voice, "decides": mine[d.account][1] == OWNED,
            "original": {"subject": original.subject, "from": name_of(original.sender) or original.address}
            if original is not None else None,
            "to": kept.to if kept else "", "cc": kept.cc if kept else "", "subject": kept.subject if kept else "",
            # ses destinataires, leur nom connu à côté de leur adresse (``to`` reste ce qu'on retouche)
            "to_people": _people(kept.to if kept else "", names[d.account]),
            "body": kept.body if kept else "", "quote": kept.quote if kept else False,
            "edited": bool(kept and kept.edited_by),
            "preview": {"sender": preview.sender, "to": preview.to, "cc": preview.cc, "subject": preview.subject,
                        "text": preview.text, "digest": preview.digest, "blocked": preview.blocked}
            if preview is not None else None,
            "to_fill": bool(kept and to_fill(kept.subject, kept.body)),
        })
    return {"items": out}


async def sent(call: Call) -> dict[str, Any]:
    """Ce qui est parti de ses boîtes ; ses destinataires à leur nom quand la boîte le connaît."""
    port = _mail_port(call)
    keys = _keys(boxes(call), call.arg("box", limit=40))
    # boîte par boîte : une page prise sur tout le serveur laisserait de côté ses envois derrière ceux des autres
    found = [x for key in keys for x in port.sent_mails(PAGE_MAX, account=key) if x.account == key]
    items = sorted(found, key=lambda x: -x.date)[:PAGE_MAX]
    names = {key: _names(port, key) for key in {x.account for x in items}}
    return {"items": [{"ref": x.ref, "box": x.account, "to": _people(x.to, names[x.account]),
                       "cc": _people(x.cc, names[x.account]), "subject": x.subject, "snippet": snippet(x.body, SNIPPET),
                       "date": millis(x.date), "by": x.by, "draft": x.draft, "attachments": len(x.attachments)}
                      for x in items]}


async def contacts(call: Call) -> dict[str, Any]:
    """Ses correspondants (ceux du courrier relevé), pour écrire : cherchés par nom ou adresse. Un correspondant de
    plusieurs boîtes en fait une seule fiche : ses mails reçus et envoyés comptés dans toutes, son dernier échange, le
    premier nom connu."""
    port = _mail_port(call)
    keys = _keys(boxes(call), call.arg("box", limit=40))
    text = call.arg("q", limit=100).strip()
    size = call.number("size", 25, high=PAGE_MAX)
    found: dict[str, Contact] = {}
    for key in keys:
        for c in port.contacts_page(key, text, 1, size).items:
            known = found.get(c.address)
            found[c.address] = c if known is None else Contact(
                c.address, known.name or c.name, known.received + c.received, known.sent + c.sent,
                max(known.last, c.last))
    ordered = sorted(found.values(), key=lambda c: (-c.last, c.address))[:size]
    return {"items": [{"address": c.address, "name": c.name, "received": c.received, "sent": c.sent,
                       "last": millis(c.last)} for c in ordered]}


# ── écrire, ranger ──


def _sendable(call: Call, key: str) -> AccountInfo:
    box = _box(call, key, SHARE_USE)
    if not box.can_send:
        raise Denied(409, "Cette boîte ne peut pas envoyer : sa connexion n'est pas prête (Paramètres › Comptes mail).")
    return box


async def send(call: Call) -> dict[str, Any]:
    """Un mail nouveau, depuis une de ses boîtes : il part tout de suite, et elle le sait. En ``multipart``, avec ses
    pièces (ADR 0214) : l'action du courrier les juge et les joint."""
    box = _sendable(call, call.arg("box", limit=40))
    got = await call.act("email.ecrire", form(account=box.key, to=call.arg("to", limit=300),
                                              cc=call.arg("cc", limit=300), bcc=call.arg("bcc", limit=300),
                                              subject=call.arg("subject", limit=200),
                                              body=call.arg("body", limit=20_000)))
    return done(got)


async def reply(call: Call) -> dict[str, Any]:
    """Une réponse, depuis la boîte du mail reçu (pas à un mail qui n'est qu'un envoi de ta boîte : on le transfère).
    L'action du courrier refuse dans le même geste ses brouillons qui attendaient pour ce mail (elle le sait), quel
    que soit qui répond : une réponse est partie, une seconde ne partira pas. C'est la seule fois où un partage touche
    aux brouillons du propriétaire : répondre demande « s'en servir », le niveau qui agit comme lui (ADR 0188)."""
    m = await _mail(call, call.arg("ref"))
    sent, received = _copies(call.port("mail"), m)
    if sent and not received:  # parti de sa boîte, sans copie reçue : on le transfère
        raise Denied(409, "On ne répond pas à un mail parti de ta boîte : transfère-le, ou réponds au mail reçu.")
    _sendable(call, m.account)
    got = await call.act("email.repondre", form(to=call.arg("to", limit=300), cc=call.arg("cc", limit=300),
                                                bcc=call.arg("bcc", limit=300), subject=call.arg("subject", limit=200),
                                                body=call.arg("body", limit=20_000), quote=call.flag("quote"),
                                                fixed={"reply_to": m.ref}))
    return done(got)


async def forward(call: Call) -> dict[str, Any]:
    m = await _mail(call, call.arg("ref"))
    _sendable(call, m.account)
    got = await call.act("email.transferer", form(fixed={"original": m.ref}, to=call.arg("to", limit=300),
                                                  cc=call.arg("cc", limit=300), bcc=call.arg("bcc", limit=300),
                                                  subject=call.arg("subject", limit=200),
                                                  body=call.arg("body", limit=20_000),
                                                  attachments=call.flag("attachments")))
    return done(got)


async def tidy(call: Call) -> dict[str, Any]:
    """Un geste sur des mails de ses boîtes (sur le serveur) : lu, non lu, archiver, suivre, ne plus suivre,
    corbeille ; ou les déplacer dans un dossier de leur boîte (``move``, avec ``folder``). Tous demandent « s'en
    servir »."""
    name = call.arg("gesture", limit=20)
    gesture = GESTURES.get(name)
    if gesture is None and name != MOVE:
        raise Denied(400, "« gesture » : read, unread, archive, flag, unflag, trash ou move.")
    refs = [_ref_mine(call, r, SHARE_USE) for r in call.strings("refs")]
    if not refs:
        raise Denied(400, "« refs » : au moins un mail.")
    if gesture is None:
        return await _move(call, refs, call.arg("folder", limit=300))
    got = await call.act("email.ranger", form(mails=[mail_key(r) for r in refs], geste=gesture))
    return done(got)


async def _move(call: Call, refs: list[str], folder: str) -> dict[str, Any]:
    """Les déplacer dans un dossier de leur boîte (ADR 0200, 0302) : toute la sélection en une action (« Ranger la
    sélection », geste ``deplacer``), en une session IMAP, auditée comme faite depuis son espace. Un mail déjà dans ce
    dossier y reste."""
    accounts = {split_ref(r)[0] for r in refs}
    if len(accounts) != 1:
        raise Denied(400, "« refs » : des mails d'une même boîte (chacune a ses dossiers).")
    port = _mail_port(call)
    target = next((f for f in port.folders(accounts.pop()) if f.name == folder), None) if folder else None
    if target is None:
        raise Denied(400, "« folder » : un dossier de leur boîte.", {"folder": "un dossier de leur boîte"})
    todo = [r for r in dict.fromkeys(refs) if (kept := port.cached_one(r)) is None or kept.folder != folder]
    if not todo:
        return {"ok": True, "message": f"Déjà dans « {target.label or target.name} ».", "deduped": False, "moved": 0}
    got = await call.act("email.ranger", form(mails=[mail_key(r) for r in todo], geste="deplacer", dossier=folder))
    moved = sum(1 for r in todo if (now := port.cached_one(r)) is not None and now.folder == folder)
    return done(got, moved=moved)


async def prefill(call: Call) -> dict[str, Any]:
    """« Préremplir avec Mika » (ADR 0191) : elle écrit une réponse à ce mail tout de suite, même endormie (ADR 0306 ; où
    elle en est : ``work``), dans ses brouillons ; la saisie la reprend quand elle arrive. Une demande en cours, ou un brouillon qui attend déjà,
    se rendent tels quels. Jamais pour un mail parti de ta boîte, même si une copie t'en est revenue : on y répond
    soi-même."""
    m = await _mail(call, call.arg("ref"), SHARE_PREPARE)
    if _copies(call.port("mail"), m)[0]:
        raise Denied(409, "Ce mail est parti de ta boîte : elle n'y prépare pas de réponse.")
    s, p = state(call), email_p.params_of(call.frame)
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
    """Pour la barre du haut, ce qui attend ta décision (ADR 0200), comme Teams et Téléphone : ses brouillons qui
    attendent, dans tes boîtes seulement (dans une boîte partagée, c'est son propriétaire qui décide). Les non-lus ont
    leurs compteurs, dossier par dossier, dans Mail."""
    if call.port("mail") is None:
        return 0
    mine = boxes(call)
    return sum(1 for d in state(call).drafts.values()
               if d.state == WAITING and mine.get(d.account, (None, ""))[1] == OWNED)


#: ce qu'il compte pour la barre du haut
COUNTERS = {"mail": count}


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    return [r("/mail/boxes", list_boxes), r("/mail/messages", messages), r("/mail/message", message), r("/mail/work", progress),
            r("/mail/frame", frame_route(api), raw=True), r("/mail/file", file, raw=True),
            r("/mail/drafts", drafts), r("/mail/sent", sent), r("/mail/contacts", contacts),
            r("/mail/send", send, write=True, upload=True), r("/mail/reply", reply, write=True, upload=True),
            r("/mail/forward", forward, write=True, upload=True), r("/mail/tidy", tidy, write=True),
            r("/mail/prefill", prefill, write=True), r("/mail/images", images, write=True),
            r("/mail/poll", poll, write=True), r("/mail/draft/send", draft_send, write=True),
            r("/mail/draft/edit", draft_edit, write=True), r("/mail/draft/refuse", draft_refuse, write=True),
            r("/mail/draft/redo", draft_redo, write=True), *account_settings.routes(api)]
