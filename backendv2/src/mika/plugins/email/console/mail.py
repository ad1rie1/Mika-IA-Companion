"""La fiche d'un mail (reçu ou parti) : le message, le fil, ce qu'elle en sait —
et ce qu'on peut en faire : répondre, lui faire rédiger une réponse, ranger
(lu, suivi, archivé, déplacé, corbeille), sur le serveur."""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any
from urllib.parse import quote

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
    Download,
    Entry,
    Fields,
    Found,
    Head,
    InspectContext,
    Meter,
    Nav,
    NavItem,
    Note,
    Pager,
    Prose,
    Ref,
    Table,
    Text,
    Timeline,
    Toolbar,
    When,
)
from mika.kernel.operate import Done, Refused
from mika.plugins.email import (
    EMAIL,
    READ,
    WAITING,
    EmailState,
    Seen,
    exhausted,
    name_of,
    params_of,
)
from mika.plugins.email.console.common import (
    NO_MAIL,
    PAGE,
    UNKNOWN,
    author,
    box_link,
    clip,
    draft_state,
    fold,
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
    if mail is not None and getattr(mail, "twin", False):
        out.append(Badge("identifiant en double : un autre mail porte le même Message-ID, méfiance", "danger"))
    if mail is not None and mail.flagged:
        out.append(Badge("suivi", "warn"))
    if mail is not None and mail.answered:
        out.append(Badge("répondu", "ok"))
    if seen is None:
        return tuple(out)
    if seen.mentioned:
        out.append(Badge("signalé à sa propriétaire", "info"))
    if seen.needs_reply:
        out.append(Badge("réponse attendue", "warn"))
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
                    badges=(Badge("parti de sa boîte", "info"), author(frame, by, edited=edited)), facts=facts, back=Ref("local", "/inspecteur/courrier/envoyes", "Retour aux envoyés",
                                        (("compte", sent.account if sent else ""),)), automatic_actions=False)
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
        info = port.account(m.account) if port is not None else None
        facts.append(("compte", info.name if info else m.account or "sa boîte"))
        facts.append(("à", Text(m.to or "—")))
    if m is None:
        facts.append(("dans la boîte", "plus maintenant" if port is not None else "courrier non branché"))
    return Head(key=mail_key(ref), title=title, subtitle=clip(sender, 200), badges=_badges(seen, m, frame),
                facts=tuple(facts), back=box_link("Retour aux messages", account=m.account if m else "",
                                                  folder=m.folder if m else ""), automatic_actions=False)


@EMAIL.search("mail")
def _search(s: EmailState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    port = ctx.ports.get("mail")
    query = fold(text)
    offset = max(0, ctx.int_param("_offset", 0))
    hits = port.search_page(text, limit, offset) if port is not None else []
    out = [Found(mail_key(m.ref), clip(m.subject) or "(sans objet)",
                 clip(m.who, 80) + (f" · {ctx.when(m.date)}" if m.date else "")) for m in hits]
    if len(out) >= limit:
        return out
    count = port.search_count(text) if port is not None else 0
    missing = [(k, seen) for k, seen in sorted(s.mails.items(), key=lambda kv: -kv[1].seq)
               if (not query or query in fold(seen.sender)) and
               (port is None or port.cached_one(k) is None and port.sent_mail(k) is None)]
    start = max(0, offset - count)
    out.extend(Found(mail_key(k), f"Un mail de {clip(name_of(seen.sender), 80)}", f"remarqué {ctx.when(seen.at)}")
               for k, seen in missing[start:start + limit - len(out)])
    return out


def _asked(s: EmailState, ctx: InspectContext, port: Any) -> tuple[str | None, Note | None]:
    """Le mail de la fiche (ou d'un ancien lien ``?id=``), ou ce qu'il faut en dire."""
    key = ctx.subject or ctx.param("id")
    if not key:
        return None, Note(NO_MAIL, tone="muted")
    ref = resolve(s, port, key)
    return (ref, None) if ref is not None else (None, Note(UNKNOWN, tone="muted"))


def _body(text: str, what: str, html: str = "") -> Block:
    if not text.strip() and not html:
        return Note("Ce message ne contient pas de texte.", tone="muted")
    return Prose(text, title=what, reading=True, html=html)


def _download_link(ref: str, part: str, label: str) -> Ref:
    return Ref("local", "/inspecteur/telecharger/mail/" + quote(mail_key(ref), safe=""), label,
               (("fichier", part),))


@EMAIL.download("mail")
async def _download(s: EmailState, frame: Frame, ctx: InspectContext, key: str, part: str) -> Download | Note:
    port = ctx.ports.get("mail")
    ref, _ = _asked(s, ctx, port)
    if port is None or ref is None or not (part in ("source", "texte") or part.isdecimal() and len(part) <= 5):
        return Note("Ce fichier n'est pas disponible.", tone="warn")
    try:
        file = await port.file(ref, part)
    except (OSError, RuntimeError, ValueError):
        return Note("Impossible de récupérer ce fichier. Vérifie la connexion du compte et la présence du message sur le serveur.", tone="warn")
    return Download(file.name, file.data)


def _document(ctx: InspectContext, ref: str, text: str, title: str = "", html: str = "", *, kind: str = "mail") -> list[Block]:
    size = 50_000
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary < 0:
                boundary = text.rfind(" ", start + size // 2, end)
            if boundary >= 0:
                end = boundary + 1
        parts.append(text[start:end])
        start = end
    pages = max(1, len(parts))
    page = max(1, min(pages, ctx.int_param("page_texte", 1)))
    blocks: list[Block] = []
    if pages > 1 or len(html) > 200_000:
        html = ""
        blocks.append(Note(f"Message long : lecture en texte, partie {page} sur {pages}." +
                           (" Le téléchargement contient le message entier." if kind == "mail" else ""), tone="info"))
    blocks.append(_body(parts[page - 1] if parts else "", title, html))
    links = []
    context = tuple((k, v) for k, v in ctx.params.items() if k != "page_texte")
    for number, label in ((page - 1, "Partie précédente"), (page + 1, "Partie suivante")):
        if 1 <= number <= pages:
            links.append(NavItem(label, Ref("subject", f"{kind}/{mail_key(ref)}", label,
                                           (*context, ("page_texte", str(number))))))
    if kind == "mail":
        links.extend((NavItem("Télécharger le texte complet", _download_link(ref, "texte", "Texte complet")),
                      NavItem("Télécharger le message (.eml)", _download_link(ref, "source", "Message original"))))
    if links:
        blocks.append(Nav(tuple(links)))
    return blocks


def _files(ref: str, attachments: tuple) -> list[Block]:
    return [Table(("Fichier", "Taille", "Type"), tuple(
        (_download_link(ref, str(i), a.name), f"{max(1, a.size // 1024)} Ko", a.mime)
        for i, a in enumerate(attachments)), title="Pièces jointes")] if attachments else []


@EMAIL.inspect("message", title="Message", subject="mail", subject_param="id", order=10,
               description='Lis le contenu du message et choisis la suite : répondre, ranger ou marquer comme lu.')
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
        info = port.account(sent.account)
        actions = [Toolbar((ActionSlot("email.transferer", (("original", sent.ref),
                            ("subject", forward_subject(sent.subject)[:200])), title="Transférer", presentation="button"),))] if info and info.can_send else []
        return [*actions, *_document(ctx, sent.ref, sent.body, "Message envoyé"), *_files(sent.ref, sent.attachments),
                Disclosure("Détails de l'envoi", (Fields((("À", Text(sent.to)), ("Copie", Text(sent.cc or "—")),
                    ("Compte", sent.account or "—"), ("Écrit par", author(frame, sent.by)),
                    ("Date", When(sent.date, relative=False) if sent.date else None),
                    ("Identifiant", Text(sent.message_id, kind="mono"))), columns=2),))]
    m = port.cached_one(ref)
    if m is None:
        return [Note("Ce mail n'est plus dans la boîte : seul ce qu'elle en a remarqué reste.", tone="muted")]
    info = port.account(m.account)
    pairs: list[tuple[str, Any]] = [("De", Text(m.sender)), ("À", Text(m.to or "—"))]
    if m.cc:
        pairs.append(("Copie", Text(m.cc)))
    pairs += [("Date", When(m.date, relative=False) if m.date else "—"),
              ("Compte", info.name if info else m.account or "—")]
    blocks: list[Block] = []
    slots: list[Block] = []
    if info is not None and info.can_send:
        own = tuple(a.address for a in port.accounts())
        # lisibles et relisibles tels quels : « "Dupré, Élodie" <elodie@…> » reste une seule adresse
        to, _ = reply_recipients(m, own)
        to_all, cc_all = reply_recipients(m, own, everyone=True)
        base = (("subject", reply_subject(m.subject)[:200]), ("reply_to", m.ref), ("quote", True), ("_bouton", "Envoyer la réponse"))
        slots.append(ActionSlot("email.repondre", (("to", to), *base), title="Répondre", presentation="button"))
        if cc_all:
            slots.append(ActionSlot("email.repondre", (("to", to_all), ("cc", cc_all), *base),
                                    title="Répondre à tous", presentation="button"))
        slots.append(ActionSlot("email.transferer", (
            ("original", m.ref), ("subject", forward_subject(m.subject)[:200]), ("_bouton", "Transférer le message")),
            title="Transférer", presentation="button"))
    slots.append(ActionSlot("email.archiver", presentation="button"))
    slots.append(Disclosure("Plus d’actions", (Toolbar((
        ActionSlot("email.classer" if unread(m, s.mails.get(ref)) else "email.non_lu", presentation="button"),
        ActionSlot("email.ne_plus_suivre" if m.flagged else "email.suivre", presentation="button"),
        ActionSlot("email.deplacer", presentation="button"),
        ActionSlot("email.rediger", title="Lui faire préparer une réponse", presentation="button"),
        ActionSlot("email.corbeille", presentation="button"), ActionSlot("email.supprimer", presentation="button"),
    )),)))
    blocks.append(Toolbar(tuple(slots)))
    if not m.complete:
        blocks.extend((Note("Ce message provient d'un ancien cache : son contenu peut être incomplet. Charge le message intégral pour le lire en entier.", tone="warn"),
                       ActionSlot("email.completer", title="Charger le message intégral", presentation="button")))
    blocks.extend(_document(ctx, m.ref, m.body, html=m.html))
    blocks.extend(_files(m.ref, m.attachments))
    blocks.append(Disclosure("Détails du message", (Fields((*pairs,
        ("Dossier", m.folder), ("Répondre à", m.reply_to or m.sender),
        ("Identifiant", Text(m.message_id, "mono")),
        ("En réponse à", Text(m.in_reply_to or "—", "mono")),
    )),)))
    return blocks


@EMAIL.inspect("fil", title="Fil", subject="mail", order=15,
               description="Les messages de cette conversation, dans leur ordre d'échange.")
def _tab_thread(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    """Le fil : ce à quoi ce mail répond, et ce qui lui a répondu (reçus et partis)."""
    port = ctx.ports.get("mail")
    ref, note = _asked(s, ctx, port)
    if ref is None or port is None:
        return [note or Note("Courrier non branché.", tone="muted")]
    request = ctx.pager(size=PAGE)
    result = port.thread_page(ref, request.number, request.size)
    pager = Pager(number=result.number, size=result.size, total=result.total)
    entries = tuple(Entry(m.date, f"{'↗ ' if m.sent else ''}{clip(m.subject, 120) or '(sans objet)'}",
                          text=m.who, tone="info" if m.sent else "",
                          href=Ref.subject("mail", mail_key(m.ref), ""), meta="ce mail" if m.ref == ref else "")
                    for m in result.items)
    return [Timeline(entries, title=f"Le fil ({result.total} mail(s), du plus ancien au plus récent)",
                     empty="Aucun message de cette conversation n'est disponible.", pager=pager),
            Note("Tous les messages conservés de ce compte, reçus et envoyés. ↗ : message envoyé.", tone="muted")]


@EMAIL.inspect("remarque", title="Ce qu'elle en sait", subject="mail", order=20,
               description="Ce qu'elle a retenu de ce message et les événements associés.")
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
    if ask is not None and exhausted(s, ref, params_of(frame)):
        blocks.append(Note(f"Tu lui as demandé d'y répondre ({ctx.when(ask.at)}), mais elle n'y est pas arrivée "
                           f"({s.attempts.get(ref, 0)} essais) : la demande est close. Tu peux la relancer "
                           "(« Lui faire préparer une réponse »).", tone="warn"))
    elif ask is not None:
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


@EMAIL.action("completer", title="Charger le message intégral", args=NoArgs, emits=[], subject="mail",
              description="Récupère le contenu complet depuis le serveur du compte.")
async def _complete(s: EmailState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    port = _port(ctx)
    ref = resolve(s, port, ctx.subject)
    try:
        m = await port.document(ref) if ref else None
    except (OSError, RuntimeError, ValueError):
        raise Refused("Le message n'a pas pu être récupéré. Vérifie la connexion du compte.") from None
    if m is None:
        raise Refused("Ce message n'est plus disponible.")
    return Done(message="Le message intégral est disponible.", go=Ref.subject("mail", mail_key(ref), m.subject))


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
    """Offert quand la boîte **de ce mail** peut envoyer, qu'aucun brouillon n'attend déjà, et qu'aucune
    demande n'est en cours — une demande dont tous les essais ont échoué est close : on peut la relancer."""
    port = ports.get("mail") if ports is not None else None
    ref = resolve(s, port, key) if port is not None else resolve_state(s, key)
    if ref is None or (port is not None and port.sent_mail(ref) is not None):
        return False
    if ref in s.asked and not exhausted(s, ref, params_of(frame)):
        return False
    if any(d.mail == ref and d.state == WAITING for d in s.drafts.values()):
        return False
    m = port.cached_one(ref) if port is not None else None
    info = port.account(m.account) if port is not None and m is not None else None
    return info is not None and info.can_send


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
