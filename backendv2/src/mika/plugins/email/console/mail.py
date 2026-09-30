"""La fiche d'un mail (reçu ou parti) : le message, le fil, ce qu'elle en sait —
et ce qu'on peut en faire : répondre, lui faire rédiger une réponse, ranger
(lu, suivi, archivé, déplacé, corbeille), sur le serveur."""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mika.contracts import attention as attention_c
from mika.contracts import email as c
from mika.kernel import forms
from mika.kernel.events import Content
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Disclosure,
    Entry,
    Fields,
    Found,
    Head,
    InspectContext,
    Meter,
    Note,
    Prose,
    Ref,
    Text,
    Timeline,
    When,
    paginate,
)
from mika.kernel.operate import Done, Refused
from mika.plugins.email import (
    EMAIL,
    READ,
    WAITING,
    EmailState,
    Seen,
    name_of,
    params_of,
)
from mika.plugins.email.console.common import (
    BODY_SHOWN,
    CACHE_SHOWN,
    FOLD,
    NO_MAIL,
    PAGE,
    UNKNOWN,
    author,
    can_send,
    clip,
    draft_state,
    fold,
    gone,
    important,
    mail_key,
    pertinence,
    resolve,
    resolve_state,
    state_badge,
    unread,
)
from mika.ports.mail import forward_subject, reply_recipients, reply_subject
from mika.vocab.affect import emotion_cell
from mika.vocab.privacy import Sensitivity


def _badges(seen: Seen | None, mail: Any, frame: Frame) -> tuple[Badge, ...]:
    p = params_of(frame)
    out = [state_badge(seen, mail, p)]
    if mail is not None and mail.flagged:
        out.append(Badge("suivi", "warn"))
    if mail is not None and mail.answered:
        out.append(Badge("répondu", "ok"))
    if seen is None:
        out.append(Badge("pas remarqué", "muted"))
        return tuple(out)
    out.append(Badge("remarqué", "info"))
    if seen.mentioned:
        out.append(Badge("signalé à sa propriétaire", "info"))
    if seen.needs_reply:
        out.append(Badge("réponse attendue", "warn"))
    out.append(Badge(f"pertinence {seen.importance:.2f}", "warn" if important(seen, p) else ""))
    return tuple(out)


@EMAIL.subject("mail", label="Mail", plural="Mails", icon="✉")
def _head(s: EmailState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    port = ctx.ports.get("mail")
    ref = resolve(s, port, key)
    if ref is None:
        return None
    sent = port.sent_mail(ref) if port is not None else None
    if sent is not None or ref in s.sent:
        known = s.sent.get(ref)
        by = sent.by if sent is not None else known.by if known is not None else ""
        edited = bool(known and known.edited)
        title = clip(sent.subject, 200) if sent is not None else "Un mail parti de sa boîte"
        to = sent.to if sent is not None else known.to if known is not None else ""
        facts = (("parti", ctx.when(sent.date) if sent is not None and sent.date else "—"),)
        return Head(key=mail_key(ref), title=title or "(sans objet)", subtitle=f"à {clip(to, 200)}",
                    badges=(Badge("parti de sa boîte", "info"), author(frame, by, edited=edited)), facts=facts)
    m = port.cached_one(ref) if port is not None else None
    seen = s.mails.get(ref)
    if m is not None:
        title, sender = clip(m.subject, 200) or "(sans objet)", m.sender
    elif seen is not None:
        title, sender = f"Un mail de {clip(name_of(seen.sender), 80)}", seen.sender
    else:
        return None
    facts: list[tuple[str, Any]] = [("reçu", ctx.when(m.date) if m is not None and m.date else "—")]
    if m is not None and (m.account or m.folder):
        facts.append(("où", f"{m.account or 'sa boîte'} · {m.folder}"))
    if seen is not None:
        facts.append(("remarqué", ctx.when(seen.at)))
    if m is None:
        facts.append(("dans la boîte", "plus maintenant" if port is not None else "courrier non branché"))
    return Head(key=mail_key(ref), title=title, subtitle=clip(sender, 200), badges=_badges(seen, m, frame),
                facts=tuple(facts))


@EMAIL.search("mail")
def _search(s: EmailState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    port = ctx.ports.get("mail")
    query = fold(text)
    out: list[Found] = []
    shown: set[str] = set()
    for m in port.cached(CACHE_SHOWN) if port is not None else ():
        if query and query not in fold(f"{m.subject} {m.sender}"):
            continue
        shown.add(m.ref)
        out.append(Found(mail_key(m.ref), clip(m.subject) or "(sans objet)",
                         clip(m.sender, 80) + (f" · reçu {ctx.when(m.date)}" if m.date else "")))
        if len(out) >= limit:
            return out
    for m in gone(port):
        if query and query not in fold(f"{m.subject} {m.to}"):
            continue
        shown.add(m.message_id)
        out.append(Found(mail_key(m.message_id), clip(m.subject) or "(sans objet)",
                         f"à {clip(m.to, 80)}" + (f" · parti {ctx.when(m.date)}" if m.date else "")))
        if len(out) >= limit:
            return out
    for k, seen in sorted(s.mails.items(), key=lambda kv: -kv[1].seq):
        if k in shown or (query and query not in fold(seen.sender)):
            continue
        out.append(Found(mail_key(k), f"Un mail de {clip(name_of(seen.sender), 80)}", f"remarqué {ctx.when(seen.at)}"))
        if len(out) >= limit:
            break
    return out


def _asked(s: EmailState, ctx: InspectContext, port: Any) -> tuple[str | None, Note | None]:
    """Le mail de la fiche (ou d'un ancien lien ``?id=``), ou ce qu'il faut en dire."""
    key = ctx.subject or ctx.param("id")
    if not key:
        return None, Note(NO_MAIL, tone="muted")
    ref = resolve(s, port, key)
    return (ref, None) if ref is not None else (None, Note(UNKNOWN, tone="muted"))


def _body(text: str, what: str) -> Block:
    if not text.strip():
        return Note("Le message n'a pas de texte lisible.", tone="muted")
    cut = f", coupé à {BODY_SHOWN} caractères" if len(text) > BODY_SHOWN else ""
    return Prose(text[:BODY_SHOWN], title=f"{what} ({len(text)} caractères{cut})", clamp=FOLD)


def _forwarded(m: Any) -> str:
    head = f"De : {m.sender}\nObjet : {m.subject}\nÀ : {m.to}"
    return f"\n\n---------- Message transféré ----------\n{head}\n\n{m.body[:6000]}"


@EMAIL.inspect("message", title="Message", subject="mail", subject_param="id", order=10)
def _tab_message(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mail")
    ref, note = _asked(s, ctx, port)
    if ref is None:
        return [note or Note(UNKNOWN, tone="muted")]
    if port is None:
        return [Note("Courrier non branché : le texte du mail n'est pas disponible (seulement ce qu'elle en a "
                     "remarqué).", tone="muted")]
    sent = port.sent_mail(ref)
    if sent is not None:
        return [Fields((("à", Text(clip(sent.to, 300))), ("copie", Text(clip(sent.cc, 300)) if sent.cc else "—"),
                        ("objet", Text(clip(sent.subject, 500) or "(sans objet)")),
                        ("parti", When(sent.date, relative=False) if sent.date else None),
                        ("de la boîte", sent.account or "—"), ("écrit par", author(frame, sent.by)),
                        ("en réponse à", Text(clip(sent.in_reply_to, 300) or "—", kind="mono")),
                        ("brouillon", Ref.subject("brouillon", sent.draft, sent.draft) if sent.draft else "—"),
                        ("identifiant", Text(clip(sent.message_id, 300), kind="mono"))), title="En-têtes",
                       columns=2),
                _body(sent.body, "Ce qui est parti")]
    m = port.cached_one(ref)
    if m is None:
        return [Note("Ce mail n'est plus dans la boîte : seul ce qu'elle en a remarqué reste.", tone="muted")]
    pairs: list[tuple[str, Any]] = [
        ("de", Text(clip(m.sender, 300))), ("adresse", Text(m.address or "—", kind="mono")),
        ("à", Text(clip(m.to, 300) or "—")), ("copie", Text(clip(m.cc, 300)) if m.cc else "—"),
        ("répondre à", Text(clip(m.reply_to, 300)) if m.reply_to else "—"),
        ("objet", Text(clip(m.subject, 500) or "(sans objet)")),
        ("reçu", When(m.date, relative=False) if m.date else None),
        ("où", f"{m.account or 'sa boîte'} · {m.folder}"),
        ("envoi de masse", "oui" if m.bulk else "non"),
        ("en réponse à", Text(clip(m.in_reply_to, 300) or "—", kind="mono")),
        ("identifiant", Text(clip(m.message_id, 300), kind="mono")),
    ]
    if m.attachments:
        pairs.append(("pièces jointes", Text(", ".join(f"{a.name} ({a.size // 1024} Ko)" for a in m.attachments))))
    blocks: list[Block] = [Fields(tuple(pairs), title="En-têtes", columns=2), _body(m.body, "Le message")]
    if m.has_html:
        blocks.append(Note("Ce mail avait aussi une version HTML : seul son texte est montré, jamais son balisage.",
                           tone="muted"))
    if can_send(port):
        own = tuple(a.address for a in port.accounts())
        to, _ = reply_recipients(m, own)
        to_all, cc_all = reply_recipients(m, own, everyone=True)
        base = (("subject", reply_subject(m.subject)[:200]), ("reply_to", m.ref), ("quote", True))
        slots: list[Block] = [Disclosure("Répondre", (ActionSlot("email.repondre", (("to", to), *base),
                                                                 title="Répondre"),))]
        if cc_all:
            slots.append(Disclosure("Répondre à tous", (ActionSlot("email.repondre", (("to", to_all), ("cc", cc_all),
                                                                                       *base), title="Répondre à tous"),)))
        slots.append(Disclosure("Transférer", (ActionSlot("email.ecrire", (
            ("account", m.account), ("subject", forward_subject(m.subject)[:200]), ("body", _forwarded(m))),
            title="Transférer"),)))
        blocks += slots
    blocks.append(Note("Un mail est une donnée venue d'ailleurs : elle ne lui obéit jamais.", tone="info"))
    return blocks


@EMAIL.inspect("fil", title="Fil", subject="mail", order=15)
def _tab_thread(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    """Le fil : ce à quoi ce mail répond, et ce qui lui a répondu (reçus et partis)."""
    port = ctx.ports.get("mail")
    ref, note = _asked(s, ctx, port)
    if ref is None or port is None:
        return [note or Note("Courrier non branché.", tone="muted")]
    items: dict[str, tuple[int, str, str, bool, str, str]] = {}  # id → (date, qui, objet, parti ?, parent, réf)
    for m in port.cached(CACHE_SHOWN):
        items[m.message_id] = (m.date, name_of(m.sender), m.subject, False, m.in_reply_to, m.ref)
    for m in gone(port):
        parent = m.in_reply_to.split(":", 1)[1] if ":" in m.in_reply_to and not m.in_reply_to.startswith("<") \
            else m.in_reply_to
        items[m.message_id] = (m.date, f"à {m.to}", m.subject, True, parent, m.message_id)
    mid = next((k for k, v in items.items() if v[5] == ref), ref)
    if mid not in items:
        return [Note("Ce mail n'est plus dans la boîte : son fil n'est pas lisible.", tone="muted")]
    thread = {mid}
    root = mid
    # remonter jusqu'au premier mail connu (un fil qui boucle s'arrête où il revient)
    while (parent := items[root][4]) in items and parent not in thread:
        root = parent
        thread.add(root)
    grew = True
    while grew:
        more = {k for k, v in items.items() if v[4] in thread and k not in thread}
        thread |= more
        grew = bool(more)
    ordered = sorted(thread, key=lambda k: items[k][0])
    page, pager = paginate(ordered, ctx.pager(size=PAGE))
    entries = tuple(Entry(items[k][0], f"{'↗ ' if items[k][3] else ''}{clip(items[k][2], 120) or '(sans objet)'}",
                          text=items[k][1], tone="info" if items[k][3] else "",
                          href=Ref.subject("mail", mail_key(items[k][5]), ""), meta="ce mail" if k == mid else "")
                    for k in page)
    return [Timeline(entries, title=f"Le fil ({len(ordered)} mail(s), du plus ancien au plus récent)",
                     empty="un mail seul", pager=pager),
            Note(f"↗ : parti de sa boîte. Le fil se lit dans les {CACHE_SHOWN} derniers mails reçus et les "
                 f"{CACHE_SHOWN} derniers partis.", tone="muted")]


@EMAIL.inspect("remarque", title="Ce qu'elle en sait", subject="mail", order=20)
def _tab_noticed(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mail")
    ref, note = _asked(s, ctx, port)
    if ref is None:
        return [note or Note(UNKNOWN, tone="muted")]
    sent = s.sent.get(ref)
    if sent is not None:
        text = ctx.store.content([sent.summary_ref]).get(sent.summary_ref, "") if sent.summary_ref else ""
        felt = next(iter(ctx.events([attention_c.NOTICED], 1, where=("signal", sent.seq))), None)
        pairs: list[tuple[str, Any]] = [("écrit par", author(frame, sent.by, edited=sent.edited)),
                                        ("elle l'a su", When(sent.at))]
        if felt is not None:
            pairs.append(("ce que son attention en a gardé", Meter(felt.data.weight, f"{felt.data.weight:.2f}")))
        pairs.append(("au journal", Ref("event", str(sent.seq), f"l'événement n° {sent.seq}")))
        return [Fields(tuple(pairs), title="Ce qu'elle en sait", columns=2),
                Prose(text, title="Ce qu'on lui en a dit") if text else Note("(oublié)", tone="muted")]
    if port is not None and port.sent_mail(ref) is not None:
        return [Note("Parti de sa boîte : elle le sait par son journal d'épisodes.", tone="muted")]
    seen = s.mails.get(ref)
    blocks: list[Block] = []
    drafted = [d for d in s.drafts.values() if d.mail == ref]
    if drafted:
        latest = max(drafted, key=lambda d: d.proposal)
        blocks.append(Fields((("brouillon de réponse", Ref.subject("brouillon", latest.draft, latest.draft)),
                              ("où il en est", Badge(*draft_state(latest.state)))), title="Sa réponse"))
    ask = s.asked.get(ref)
    if ask is not None:
        blocks.append(Note(f"Tu lui as demandé d'y répondre ({ctx.when(ask.at)}) : elle le fera à son prochain "
                           "moment de travail (au réveil si elle dort).", tone="info"))
    if seen is None:
        return [*blocks, Note("Elle ne l'a pas (ou plus) remarqué : il est dans la boîte, sans plus.", tone="muted")]
    p = params_of(frame)
    text = ctx.store.content([seen.summary_ref]).get(seen.summary_ref, "") if seen.summary_ref else ""
    signal = next(iter(ctx.events([c.NOTICED], 1, where=("mail", ref))), None)
    felt = next(iter(ctx.events([attention_c.NOTICED], 1, where=("signal", seen.seq))), None)
    pairs = [
        ("remarqué", When(seen.at)), ("pertinence estimée", pertinence(seen)),
        ("important", "oui" if important(seen, p) else "non"),
        ("réponse attendue", "oui" if seen.needs_reply else "non"), ("état", state_badge(seen, None, p)),
    ]
    if signal is not None:
        pairs.append(("ce que ça pourrait lui faire", emotion_cell(signal.data.emotion, signal.data.intensity or None)))
    if felt is not None:
        pairs.append(("ce que son attention en a gardé", Meter(felt.data.weight, f"{felt.data.weight:.2f}")))
    pairs.append(("au journal", Ref("event", str(seen.seq), f"l'événement n° {seen.seq}")))
    blocks.append(Fields(tuple(pairs), title="Ce qu'elle en a remarqué", columns=2))
    blocks.append(Prose(text, title="Ce qu'elle en a retenu") if text else
                  Note("Ce qu'elle en avait retenu a été oublié.", tone="muted"))
    return blocks


# ── Agir sur un mail (sur le serveur ; elle le sait quand ça la concerne) ─


class NoArgs(BaseModel):
    pass


class AskArgs(BaseModel):
    instruction: Annotated[str, Knob(label="Ce que tu veux y dire", widget="textarea", advanced=False,
                                     help="Facultatif : l'idée de la réponse. Elle l'écrit dans la voix de la "
                                          "boîte ; rien ne part sans ton accord.")] = \
        Field(default="", max_length=4000)


class MoveArgs(BaseModel):
    folder: Annotated[str, Knob(label="Vers", widget="select", advanced=False)] = Field(min_length=1, max_length=300)


def _mail_of(s: EmailState, ports: Any, key: str) -> Any:
    port = ports.get("mail") if ports is not None else None
    ref = resolve(s, port, key) if port is not None else None
    return port.cached_one(ref) if ref is not None else None


def _port(ctx: Any) -> Any:
    port = ctx.ports.get("mail")
    if port is None:
        raise Refused("Courrier non branché.")
    return port


def _read_draft(s: EmailState, ref: str, by: str, how: str) -> tuple[Any, ...]:
    """Elle n'en parlera plus : l'opérateur l'a lu, rangé ou jeté."""
    seen = s.mails.get(ref)
    return (READ.draft(mail=ref, by=by, how=how),) if seen is not None and not seen.read else ()


async def _server(ctx: Any, s: EmailState, verb: str) -> Done:
    port = _port(ctx)
    m = _mail_of(s, ctx.ports, ctx.subject)
    if m is None:
        ref = resolve_state(s, ctx.subject)
        if ref is not None and verb in ("lu",):  # plus dans le cache : elle seule en sait quelque chose
            return Done(drafts=_read_draft(s, ref, ctx.by, "lu"), message="Classé comme lu.")
        raise Refused("Ce mail n'est plus dans la boîte.")
    try:
        if verb == "lu":
            await port.set_flags(m.ref, seen=True)
            return Done(drafts=_read_draft(s, m.ref, ctx.by, "lu"), message="Marqué comme lu : elle n'en parlera plus.")
        if verb == "non_lu":
            await port.set_flags(m.ref, seen=False)
            return Done(message="Marqué non lu (sur le serveur ; elle, l'a déjà vu).")
        if verb in ("suivre", "ne_plus_suivre"):
            await port.set_flags(m.ref, flagged=verb == "suivre")
            return Done(message="Suivi." if verb == "suivre" else "Plus suivi.")
        if verb == "archiver":
            where = await port.archive(m.ref)
            return Done(drafts=_read_draft(s, m.ref, ctx.by, "archivé"), message=f"Archivé dans « {where} ».")
        if verb == "corbeille":
            where = await port.trash(m.ref)
            return Done(drafts=_read_draft(s, m.ref, ctx.by, "corbeille"), message=f"Mis dans « {where} ».")
        if verb == "supprimer":
            await port.delete(m.ref)
            return Done(drafts=_read_draft(s, m.ref, ctx.by, "supprimé"), message="Supprimé définitivement.")
    except (OSError, RuntimeError, ValueError) as exc:  # une erreur IMAP est une OSError ou une ImapError
        raise Refused(f"Le serveur a refusé : {exc}"[:300]) from None
    raise Refused("Geste inconnu.")


def _is(pred: Any) -> Any:
    def available(s: EmailState, frame: Frame, key: str, ports: Any = None) -> bool:
        m = _mail_of(s, ports, key)
        return bool(pred(s, m, resolve_state(s, key)))

    return available


def _unread(s: EmailState, m: Any, ref: str | None) -> bool:
    return unread(m, s.mails.get(m.ref)) if m is not None else (ref is not None and not s.mails[ref].read)


@EMAIL.action("classer", title="Marquer comme lu", args=NoArgs, emits=[READ], subject="mail", order=40,
              description="Sur le serveur aussi ; elle n'en parlera plus.", available=_is(_unread))
async def _mark_read(s: EmailState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    return await _server(ctx, s, "lu")


@EMAIL.action("non_lu", title="Marquer non lu", args=NoArgs, emits=[], subject="mail", order=41,
              available=_is(lambda s, m, ref: m is not None and m.seen))
async def _mark_unread(s: EmailState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    return await _server(ctx, s, "non_lu")


@EMAIL.action("suivre", title="Suivre", args=NoArgs, emits=[], subject="mail", order=42,
              description="Un drapeau sur le serveur.", available=_is(lambda s, m, ref: m is not None and not m.flagged))
async def _flag(s: EmailState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    return await _server(ctx, s, "suivre")


@EMAIL.action("ne_plus_suivre", title="Ne plus suivre", args=NoArgs, emits=[], subject="mail", order=43,
              available=_is(lambda s, m, ref: m is not None and m.flagged))
async def _unflag(s: EmailState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    return await _server(ctx, s, "ne_plus_suivre")


@EMAIL.action("archiver", title="Archiver", args=NoArgs, emits=[READ], subject="mail", order=45,
              available=_is(lambda s, m, ref: m is not None))
async def _archive(s: EmailState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    return await _server(ctx, s, "archiver")


def _folder_fields(s: EmailState, frame: Frame, key: str, fixed: Any, ports: Any = None) -> list[Any]:
    m = _mail_of(s, ports, key)
    port = ports.get("mail") if ports is not None else None
    folders = [f for f in port.folders(m.account) if f.name != m.folder] if m is not None and port is not None else []
    base = forms.describe(MoveArgs)
    return [dataclasses.replace(f, choices=tuple((x.name, x.label if x.label == x.name else f"{x.label} ({x.name})")
                                                 for x in folders)) if f.path == "folder" else f for f in base]


@EMAIL.action("deplacer", title="Déplacer", args=MoveArgs, emits=[READ], subject="mail", order=46,
              fields=_folder_fields, available=_is(lambda s, m, ref: m is not None))
async def _move(s: EmailState, frame: Frame, args: Any, ctx: Any) -> Done:
    port = _port(ctx)
    m = _mail_of(s, ctx.ports, ctx.subject)
    if m is None:
        raise Refused("Ce mail n'est plus dans la boîte.")
    folder = str(args.get("folder", "") if isinstance(args, dict) else args.folder)
    try:
        where = await port.move(m.ref, folder)
    except (OSError, RuntimeError, ValueError) as exc:
        raise Refused(f"Le serveur a refusé : {exc}"[:300]) from None
    return Done(drafts=_read_draft(s, m.ref, ctx.by, "déplacé"), message=f"Déplacé dans « {where} ».")


def _in_trash(s: EmailState, m: Any, ports: Any) -> bool:
    port = ports.get("mail") if ports is not None else None
    if m is None or port is None:
        return False
    return any(f.name == m.folder and f.role == "trash" for f in port.folders(m.account))


@EMAIL.action("corbeille", title="Corbeille", args=NoArgs, emits=[READ], subject="mail", order=47, danger=True,
              confirm="Mettre ce mail à la corbeille ?",
              available=lambda s, frame, key, ports=None: (m := _mail_of(s, ports, key)) is not None
              and not _in_trash(s, m, ports))
async def _trash(s: EmailState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    return await _server(ctx, s, "corbeille")


@EMAIL.action("supprimer", title="Supprimer définitivement", args=NoArgs, emits=[READ], subject="mail", order=48,
              danger=True, retype=True, confirm="Supprimer définitivement ce mail du serveur ?",
              available=lambda s, frame, key, ports=None: _in_trash(s, _mail_of(s, ports, key), ports))
async def _delete(s: EmailState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    return await _server(ctx, s, "supprimer")


def _can_ask(s: EmailState, frame: Frame, key: str, ports: Any = None) -> bool:
    port = ports.get("mail") if ports is not None else None
    ref = resolve(s, port, key) if port is not None else resolve_state(s, key)
    if ref is None or ref in s.asked or (port is not None and port.sent_mail(ref) is not None):
        return False
    return not any(d.mail == ref and d.state == WAITING for d in s.drafts.values()) and can_send(port)


@EMAIL.action("rediger", title="Lui faire rédiger une réponse", args=AskArgs, emits=[c.DRAFT_ASKED], subject="mail",
              order=30, available=_can_ask,
              description="Elle l'écrit dans la voix de la boîte, à son prochain moment de travail ; le brouillon "
                          "attendra ton accord (Courrier › Brouillons).")
def _ask(s: EmailState, frame: Frame, args: AskArgs, ctx: Any) -> Done:
    port = ctx.ports.get("mail")
    ref = resolve(s, port, ctx.subject) if port is not None else None
    if ref is None:
        raise Refused("Ce mail n'est plus dans la boîte.")
    m = port.cached_one(ref)
    instruction = Content.of(args.instruction.strip(), level=int(Sensitivity.PERSONAL)) \
        if args.instruction.strip() else None
    draft = c.DRAFT_ASKED.draft(mail=ref, account=m.account if m is not None else "", by=ctx.by,
                                instruction=instruction, about=(ctx.by,) if ctx.by else ())
    return Done(drafts=(draft,), message="Demandé : elle préparera la réponse à son prochain moment de travail ; "
                                         "tu la trouveras dans Brouillons.")

