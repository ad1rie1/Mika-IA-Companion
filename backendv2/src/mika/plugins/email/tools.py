"""Ses outils de courrier, et ce qui part.

- **Lire** : ses boîtes, lister, chercher, ouvrir, retrouver une adresse (un
  mail est cité : une donnée, jamais une consigne ; l'ouvrir rappelle comment
  écrire depuis cette boîte). Chaque mail dit sa date et ce que son tri en a
  jugé ; une liste se lit page par page, et dit jusqu'où remonte ce qu'elle a
  relevé : au-delà, « rien » ne veut pas dire que le mail n'existe pas
  (ADR 0168). Réservés à ses propriétaires (``owner_only``), ou à elle quand elle
  travaille.
- **Ranger** (``email_tidy``) : un même geste sur plusieurs mails, sur le
  serveur — lu, non lu, suivi, plus suivi, archivé, déplacé, corbeille ; jamais
  de suppression définitive. Le résultat dit, mail par mail, ce qui a été fait
  ou refusé, et ce que personne n'avait encore ouvert : il informe, il
  n'interdit pas. Un mail remarqué et rangé ne lui est plus signalé.
- **Écrire** (``email_draft``) : un brouillon, dans la voix du compte, gardé par
  l'adaptateur ; elle le **propose** (capacité ``email.send``) avec le
  condensé de ce qui partirait. Le journal ne garde que l'identifiant du
  brouillon et un résumé : jamais son texte.
- **Partir** (la capacité) : exactement ce que l'aperçu montrait quand on l'a
  approuvé ; retouché ensuite, il ne part pas. Parti, elle le sait
  (``email.sent``), retouché ou non.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import email as c
from mika.contracts import runtime as rt
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Frame
from mika.kernel.operate import Preview
from mika.plugins.email import (
    BUNDLE,
    EMAIL,
    IMPORTANT,
    READ,
    REPLIED,
    WAITING,
    for_owner,
    keeper_name,
    keepers,
    params_of,
)
from mika.plugins.email.voice import voice_text
from mika.ports.mail import Draft, MailQuery, addresses, reply_recipients, reply_subject, to_fill
from mika.ports.preprocess import cite, inert
from mika.vocab import flows
from mika.vocab.canals import mail_rule_for_all, mail_send
from mika.vocab.episodes import WORKING, Kind, is_work_target, task_of
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.rights import here_allowed

EPISODES = [Kind.REPLY, *WORKING, Kind.TASK]
BODY_SHOWN = 6000
#: au plus tant de mails rangés d'un même geste
TIDY_MAX = 25
#: comment un mail qu'elle avait remarqué quitte ses non-lus quand elle le range (``Seen.how``, les mêmes mots que la
#: console) ; marquer non lu, suivre, ne plus suivre : il n'en quitte rien
TIDY_HOW = {"read": "lu", "archive": "archivé", "move": "déplacé", "trash": "corbeille"}
#: ce qu'un geste a donné pour un mail : fait à l'instant, déjà ainsi, refusé
DONE, ALREADY, REFUSED = "done", "already", "refused"
#: une page plus loin que la dernière : ``Page.bounds`` la ramène à la dernière (le mail le plus ancien relevé)
LAST_PAGE = 10**9


def voice_word(voice: str) -> str:
    """Sa voix dans une boîte, en quelques mots (« en ton nom ») ; rien pour une voix inconnue."""
    return family("email.voice_word").get(voice, "")


def _port(ctx: Any) -> tuple[Any, ToolResult | None]:
    port = ctx.ports.get("mail")
    if port is None:
        return None, ToolResult(ok=False, content=phrase("email.tools.no_box"))
    if not for_owner(ctx.frame):
        return None, ToolResult(ok=False, content=phrase("email.tools.private"))
    return port, None


def _unread_mark(ctx: Any, m: Any) -> str:
    seen = ctx.frame.state("email").mails.get(m.ref)
    unread = not m.seen and (seen is None or not seen.read)
    return phrase("email.tools.unread") if unread else ""


def when(frame: Frame, at: int) -> str:
    """Quand un mail est arrivé, daté (« aujourd'hui 10 h 05 », « le 12/10 9 h 14 », « le 03/02/2025 ») : de quoi
    juger son âge sans calcul."""
    if at <= 0:
        return phrase("email.tools.when.unknown")
    then, today = frame.local(at), frame.local().date()
    days = (today - then.date()).days
    hm = {"hour": then.hour, "minute": f"{then.minute:02d}"}
    if days == 0:
        return phrase("email.tools.when.today", **hm)
    if days == 1:
        return phrase("email.tools.when.yesterday", **hm)
    dm = {"day": f"{then.day:02d}", "month": f"{then.month:02d}"}
    if then.year == today.year:
        return phrase("email.tools.when.date", **dm, **hm)
    return phrase("email.tools.when.year", **dm, year=then.year)


def _unread(ctx: Any, query: MailQuery) -> MailQuery:
    """Ce qui n'est pas lu : ni sur le serveur, ni par elle (``_unread_mark``)."""
    read = tuple(k for k, seen in ctx.frame.state("email").mails.items() if seen.read)
    return replace(query, seen=False, exclude=read)


def _covered(ctx: Any, port: Any, account: str, folder: str) -> str:
    """Jusqu'où remonte ce qu'elle a relevé (le mail le plus ancien du cache, par boîte) : au-delà, elle ne trouve
    rien, et ce n'est pas que rien n'existe."""
    boxes = [a.key for a in port.accounts() if not account or a.key == account]
    since = []
    for key in boxes:
        oldest = port.messages_page(MailQuery(account=key, folder=folder), LAST_PAGE, 1).items
        if oldest:
            at = when(ctx.frame, oldest[0].date)
            since.append(phrase("email.tools.covered.box", when=at, account=key) if len(boxes) > 1 else at)
    if not since:
        return ""
    return phrase("email.tools.covered.line", since=", ".join(since), who=keepers(ctx.frame))


def _page(ctx: Any, port: Any, query: MailQuery, number: int, size: int) -> tuple[list[str], str, bool] | None:
    """Une page de mails : ses lignes, où l'on est s'il y a plusieurs pages, et si c'est la dernière ; ``None``
    au-delà de la dernière."""
    got = port.messages_page(query, number, size)
    if number > got.number and got.total:
        return None
    pages = max(1, -(-got.total // got.size))
    several = len(port.accounts()) > 1
    lines = [_line(ctx, m, phrase("email.tools.list.box", account=m.account, folder=inert(m.folder, 60))
                   if several else "") for m in got.items]
    if pages == 1:
        return lines, "", True
    if got.number < pages:
        return lines, phrase("email.tools.page.more", number=got.number, pages=pages, total=got.total,
                             next=got.number + 1), False
    return lines, phrase("email.tools.page.last", number=got.number, pages=pages, total=got.total), True


class NoArgs(BaseModel):
    pass


class ListArgs(BaseModel):
    limit: int = Field(default=10, ge=1, le=30)
    page: int = Field(default=1, ge=1, le=200, description=phrase("email.tools.page.arg"))
    account: str = Field(default="", max_length=40, description=phrase("email.tools.list.account"))
    folder: str = Field(default="", max_length=200, description=phrase("email.tools.list.folder"))
    unread_only: bool = Field(default=False, description=phrase("email.tools.list.unread_only"))


class SearchArgs(BaseModel):
    query: str = Field(default="", max_length=200, description=phrase("email.tools.search.query"))
    sender: str = Field(default="", max_length=200, description=phrase("email.tools.search.sender"))
    account: str = Field(default="", max_length=40, description=phrase("email.tools.list.account"))
    folder: str = Field(default="", max_length=200, description=phrase("email.tools.list.folder"))
    unread_only: bool = Field(default=False, description=phrase("email.tools.list.unread_only"))
    limit: int = Field(default=10, ge=1, le=30)
    page: int = Field(default=1, ge=1, le=200, description=phrase("email.tools.page.arg"))


class ContactsArgs(BaseModel):
    query: str = Field(default="", max_length=200, description=phrase("email.tools.contacts.query"))
    account: str = Field(default="", max_length=40, description=phrase("email.tools.list.account"))
    limit: int = Field(default=10, ge=1, le=30)


class ReadArgs(BaseModel):
    mail: str = Field(min_length=1, max_length=400, description=phrase("email.tools.read.mail"))


class DraftArgs(BaseModel):
    mail: str = Field(default="", max_length=400, description=phrase("email.tools.draft.mail"))
    body: str = Field(min_length=1, max_length=8000, description=phrase("email.tools.draft.body"))
    to: str = Field(default="", max_length=300, description=phrase("email.tools.draft.to"))
    subject: str = Field(default="", max_length=200, description=phrase("email.tools.draft.subject"))
    account: str = Field(default="", max_length=40, description=phrase("email.tools.draft.account"))
    reply_all: bool = Field(default=False, description=phrase("email.tools.draft.reply_all"))
    quote: bool = Field(default=True, description=phrase("email.tools.draft.quote"))


class TidyArgs(BaseModel):
    mails: list[Annotated[str, Field(min_length=1, max_length=400)]] = Field(
        min_length=1, max_length=TIDY_MAX, description=phrase("email.tools.tidy.mails"))
    action: Literal["read", "unread", "flag", "unflag", "archive", "move", "trash"] = Field(
        description=phrase("email.tools.tidy.action"))
    folder: str = Field(default="", max_length=300, description=phrase("email.tools.tidy.folder"))


@EMAIL.tool("email_accounts", description=phrase("email.tools.accounts.description"), args=NoArgs, bundle=BUNDLE, episodes=EPISODES, owner_only=True)
async def email_accounts(args: NoArgs, ctx: Any) -> Any:
    port, refused = _port(ctx)
    if refused is not None:
        return refused
    accounts = port.accounts()
    if not accounts:
        return phrase("email.tools.accounts.none")
    lines = []
    for a in accounts:
        folders = [f for f in port.folders(a.key) if f.polled or f.unseen]
        counts = ", ".join(phrase("email.tools.accounts.folder", folder=f.label, count=f.unseen)
                           for f in folders[:6]) or phrase("email.tools.accounts.nothing_known")
        state = "" if a.ready else phrase("email.tools.accounts.not_ready")
        lines.append(phrase("email.tools.accounts.line", key=a.key, name=a.name, address=a.address, state=state,
                            voice=voice_word(a.voice), counts=counts))
    return "\n".join(lines)


@EMAIL.tool("email_list", description=phrase("email.tools.list.description"), args=ListArgs,
            bundle=BUNDLE, episodes=EPISODES, owner_only=True)
async def email_list(args: ListArgs, ctx: Any) -> Any:
    port, refused = _port(ctx)
    if refused is not None:
        return refused
    query = MailQuery(account=args.account, folder=args.folder)
    page = _page(ctx, port, _unread(ctx, query) if args.unread_only else query, args.page, args.limit)
    if page is None:
        return phrase("email.tools.page.past")
    lines, where, last = page
    first = args.page == 1 and not args.folder and not args.unread_only
    gone = port.sent_mails(5, account=args.account) if first else []
    covered = _covered(ctx, port, args.account, args.folder) if last else ""
    if not lines and not gone:
        empty = phrase("email.tools.list.nothing_here") if (args.account or args.folder or args.unread_only) \
            else phrase("email.tools.list.empty")
        return "\n".join(t for t in (empty, covered) if t)
    if gone:
        lines.append(phrase("email.tools.list.sent_header"))
        lines += [phrase("email.tools.list.sent", id=m.message_id, when=when(ctx.frame, m.date), to=inert(m.to, 200),
                         subject=inert(m.subject, 200),
                         by=phrase("email.tools.list.by", who=keeper_name(ctx.frame, m.by)) if m.by
                         else phrase("email.tools.list.by_you")) for m in gone]
    return "\n".join(t for t in (phrase("email.tools.data"), *lines, where, covered) if t)


def _line(ctx: Any, m: Any, box: str = "") -> str:
    """Un mail dans une liste : sa référence, sa date, lu ou non, sa boîte, l'expéditeur et l'objet (cités), puis ce
    que son tri en a jugé et ce qu'il porte."""
    return phrase("email.tools.list.line", ref=m.ref, when=when(ctx.frame, m.date), unread=_unread_mark(ctx, m),
                  box=box, sender=inert(m.sender, 200), subject=inert(m.subject, 200), marks=_marks(ctx, m),
                  twin=_twin(m))


def _marks(ctx: Any, m: Any) -> str:
    """Ce que son tri a jugé d'un mail (important, une réponse attendue) et ce que le serveur en dit (répondu, suivi,
    des pièces jointes) : de quoi trier sans tout rouvrir."""
    seen = ctx.frame.state("email").mails.get(m.ref)
    out = phrase("email.unread.important") if seen is not None and seen.importance >= IMPORTANT else ""
    if m.answered or (seen is not None and seen.how == REPLIED):
        out += phrase("email.tools.marks.answered")
    elif seen is not None and seen.needs_reply:
        out += phrase("email.unread.needs_reply")
    if m.flagged:
        out += phrase("email.tools.marks.flagged")
    if m.attachments:
        out += phrase("email.tools.marks.attachments", count=len(m.attachments))
    return out


def _twin(m: Any) -> str:
    return phrase("email.tools.twin") if getattr(m, "twin", False) else ""


@EMAIL.tool("email_search", description=phrase("email.tools.search.description"), args=SearchArgs,
            bundle=BUNDLE, episodes=EPISODES, owner_only=True, max_calls_per_episode=4)
async def email_search(args: SearchArgs, ctx: Any) -> Any:
    port, refused = _port(ctx)
    if refused is not None:
        return refused
    if len(args.query.strip()) < 2 and len(args.sender.strip()) < 2:
        return ToolResult(ok=False, content=phrase("email.tools.search.what"))
    query = MailQuery(account=args.account, folder=args.folder, text=args.query, sender=args.sender)
    page = _page(ctx, port, _unread(ctx, query) if args.unread_only else query, args.page, args.limit)
    if page is None:
        return phrase("email.tools.page.past")
    lines, where, _ = page
    covered = _covered(ctx, port, args.account, args.folder)
    if not lines:
        return "\n".join(t for t in (phrase("email.tools.search.nothing"), covered) if t)
    return "\n".join(t for t in (phrase("email.tools.data"), *lines, where, covered) if t)


@EMAIL.tool("email_contacts", description=phrase("email.tools.contacts.description"), args=ContactsArgs,
            bundle=BUNDLE, episodes=EPISODES, owner_only=True, max_calls_per_episode=4)
async def email_contacts(args: ContactsArgs, ctx: Any) -> Any:
    port, refused = _port(ctx)
    if refused is not None:
        return refused
    found = port.contacts_page(args.account, args.query, 1, args.limit).items
    if not found:
        return phrase("email.tools.contacts.nothing")
    return "\n".join((phrase("email.tools.data"), *(
        phrase("email.tools.contacts.line", name=inert(c.name, 120) or phrase("email.tools.contacts.no_name"),
               address=inert(c.address, 200), received=c.received, sent=c.sent, when=when(ctx.frame, c.last))
        for c in found)))


def _quoted(text: str) -> str:
    return cite(text, BODY_SHOWN)


@EMAIL.tool("email_read", description=phrase("email.tools.read.description"), args=ReadArgs, bundle=BUNDLE,
            episodes=EPISODES, max_calls_per_episode=5, owner_only=True)
async def email_read(args: ReadArgs, ctx: Any) -> Any:
    port, refused = _port(ctx)
    if refused is not None:
        return refused
    ref = args.mail.strip().strip("[]")
    m = await port.get(ref)
    if m is None:
        gone = port.sent_mail(ref)
        if gone is None:
            return ToolResult(ok=False, content=phrase("email.tools.not_found"))
        author = phrase("email.tools.read.author", who=keeper_name(ctx.frame, gone.by)) if gone.by else \
            phrase("email.tools.read.author_you")
        return "\n".join((phrase("email.tools.read.sent_head", author=author),
                          phrase("email.header.to", who=inert(gone.to, 300)),
                          phrase("email.header.date", when=when(ctx.frame, gone.date)),
                          phrase("email.header.subject", subject=inert(gone.subject, 300)), _quoted(gone.body)))
    seen = ctx.frame.state("email").mails.get(m.ref)
    if seen is not None and not seen.read:
        await ctx.emit(READ.draft(mail=m.ref))
    lines = [phrase("email.tools.read.head"), f"[{m.ref}]{_twin(m)}", phrase("email.header.from", who=inert(m.sender, 200)),
             phrase("email.header.to", who=inert(m.to, 300))]
    if m.cc:
        lines.append(phrase("email.header.cc", who=inert(m.cc, 300)))
    lines.append(phrase("email.header.date", when=when(ctx.frame, m.date)))
    lines.append(phrase("email.header.subject", subject=inert(m.subject, 300)))
    if m.attachments:
        lines.append(phrase("email.header.attachments", files=", ".join(inert(a.name, 80) for a in m.attachments[:10])))
    out = "\n".join([*lines, _quoted(m.body)])
    info = port.account(m.account)
    if info is not None:  # ce qui suit n'est pas le mail : c'est ta façon d'écrire depuis cette boîte
        out += f"\n\n{phrase('email.tools.read.reply_how', ref=m.ref)}\n{voice_text(info)}"
    return out


def _asker(ctx: Any) -> tuple[str, ...]:
    """La personne à qui elle parlait en l'écrivant (le résumé peut la citer)."""
    ep = ctx.frame.episode
    target = ep.target if ep is not None else ""
    return (target,) if target and is_identifiable(target) and not is_work_target(target) else ()


@EMAIL.tool("email_draft", acts=True, description=phrase("email.tools.draft.description"), args=DraftArgs,
            bundle=BUNDLE, episodes=EPISODES, max_calls_per_episode=2, owner_only=True)
async def email_draft(args: DraftArgs, ctx: Any) -> Any:
    port, refused = _port(ctx)
    if refused is not None:
        return refused
    ref = args.mail.strip().strip("[]")
    parent = await port.get(ref) if ref else None
    if ref and parent is None:
        return ToolResult(ok=False, content=phrase("email.tools.not_found"))
    if parent is not None:
        ref = parent.ref
        waiting = [d for d in ctx.frame.state("email").drafts.values() if d.mail == ref and d.state == WAITING]
        if waiting:
            return ToolResult(ok=False, content=phrase("email.tools.draft.waiting", who=keepers(ctx.frame)))
    key = args.account or (parent.account if parent is not None else "")
    accounts = port.accounts()
    info = next((a for a in accounts if a.key == key), None) if key or parent is not None \
        else next((a for a in accounts if a.can_send), None)
    if info is None:
        return ToolResult(ok=False, content=phrase("email.tools.draft.unknown_box") if key else
                          phrase("email.tools.draft.no_box"))
    to, cc = args.to, ""
    if parent is not None and not to:
        to, cc = reply_recipients(parent, tuple(a.address for a in accounts), everyone=args.reply_all)
    subject = args.subject or (reply_subject(parent.subject) if parent is not None else "")
    if not to or not subject:
        return ToolResult(ok=False, content=phrase("email.tools.draft.incomplete"))
    # récrit par l'autrice de sa boîte, s'il y en a une (ADR 0124) : ce qu'elle a écrit, dans les codes de ce flux
    about = f"{inert(parent.sender, 120)} — {inert(parent.subject, 200)}\n{cite(parent.body, 2000)}" if parent else ""
    body = await flows.written(ctx, flows.mail(info.key), args.body, about)
    draft = port.save_draft(Draft(id="", account=info.key, to=to, subject=subject, body=body, cc=cc,
                                  reply_to=ref, quote=args.quote and parent is not None))
    shown = port.preview(draft.id)
    # un passage à compléter n'empêche pas de proposer (on le remplira) ; tout autre blocage, si
    if shown is None or (shown.blocked and not to_fill(draft.body, draft.subject, shown.text)):
        port.discard_draft(draft.id)
        return ToolResult(ok=False, content=phrase("email.tools.draft.blocked",
                                                   why=shown.blocked if shown else phrase("email.tools.draft.error")))
    p = params_of(ctx.frame)
    # la ligne de sa boîte (ADR 0132, 0134) : il ne part seul que si chaque destinataire le permet, et jamais avec
    # un passage à compléter
    rule = mail_rule_for_all(p.canaux, info.key, (a for _, a in addresses(f"{to},{cc}")))
    needs_approval = mail_send(rule) != "seule" or bool(shown.blocked)
    about = tuple(dict.fromkeys((*_asker(ctx), *(c.address_handle(a) for _, a in addresses(to)[:3]))))
    what = f"Répondre à {inert(to, 200)}" if parent is not None else f"Écrire à {inert(to, 200)}"
    summary = f"{what} (boîte « {inert(info.name, 60)} », {voice_word(info.voice)}) : « {inert(subject, 200)} »"
    payload = {"draft": draft.id, "account": info.key, "mail": ref, "_apercu": shown.digest}
    await ctx.propose(rt.EFFECT_PROPOSED.draft(
        capability=c.SEND, owner=c.OWNER, args_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        summary=Content.of(summary[:400], level=int(Sensitivity.PERSONAL)), approval=needs_approval,
        context="email", about=about))
    who = keepers(ctx.frame)
    after = phrase("email.tools.draft.proposed", who=who) if needs_approval else \
        phrase("email.tools.draft.queued")
    if shown.blocked:
        after += phrase("email.tools.draft.to_fill", who=who)
    # un brouillon préparé prouve qu'une exécution a produit (ADR 0104)
    return ToolResult(content="\n".join((after, phrase("email.tools.draft.would_go"),
                                         phrase("email.header.from", who=shown.sender),
                                         phrase("email.header.to", who=shown.to),
                                         phrase("email.header.subject", subject=shown.subject), "",
                                         shown.text[:3000])), proof=True)


# ── Ranger ────────────────────────────────────────────────────────────────


def _may_tidy(frame: Frame) -> bool:
    """Ranger ici : ce que ses droits laissent de cet outil qui agit (la règle de la porte d'offre, revérifiée à
    l'exécution) ; elle seule, avec sa boîte, ou dans une de ses tâches de courrier."""
    return here_allowed(frame, BUNDLE, "email_tidy", acts=True,
                        tasks=lambda target: (task_of(target) or ("", ""))[0] == EMAIL.name)


def _folder_named(folders: list[Any], wanted: str) -> Any:
    """Le dossier demandé : par son nom sur le serveur, sinon par son nom ou son libellé (« Archives ») sans tenir
    compte de la casse ; ``None`` s'il n'existe pas dans cette boîte."""
    exact = next((f for f in folders if f.name == wanted), None)
    if exact is not None:
        return exact
    folded = wanted.casefold()
    return next((f for f in folders if folded in (f.name.casefold(), f.label.casefold())), None)


def _folders_line(account: str, folders: list[Any]) -> str:
    """Les dossiers d'une boîte (leur libellé et leur nom sur le serveur) : où l'on peut ranger."""
    named = [inert(f.name, 80) if f.label == f.name else
             phrase("email.tools.tidy.folder_named", label=inert(f.label, 60), name=inert(f.name, 80))
             for f in folders]
    return phrase("email.tools.tidy.folders", account=account,
                  folders=", ".join(named) or phrase("email.tools.tidy.no_folders"))


def _refusal(exc: Exception) -> str:
    """Ce que le serveur a répondu, dit comme une donnée (une réponse IMAP peut porter ce qu'elle veut)."""
    return phrase("email.tools.tidy.refused", why=inert(str(exc), 200) or type(exc).__name__)


async def _gesture(port: Any, ref: str, action: str, folder: str) -> str:
    """Un geste sur un mail, sur le serveur ; rend le dossier d'arrivée quand il en change (sinon rien). Jamais de
    suppression définitive : ``port.delete`` n'est pas un geste d'elle."""
    if action == "unread":
        await port.set_flags(ref, seen=False)
        return ""
    if action in ("flag", "unflag"):
        await port.set_flags(ref, flagged=action == "flag")
        return ""
    if action == "archive":
        return str(await port.archive(ref))
    if action == "trash":
        return str(await port.trash(ref))
    return str(await port.move(ref, folder))


@EMAIL.tool("email_tidy", acts=True, description=phrase("email.tools.tidy.description"), args=TidyArgs,
            bundle=BUNDLE, episodes=EPISODES, max_calls_per_episode=6, owner_only=True)
async def email_tidy(args: TidyArgs, ctx: Any) -> Any:
    port, refused = _port(ctx)
    if refused is not None:
        return refused
    if not _may_tidy(ctx.frame):
        return ToolResult(ok=False, content=phrase("email.tools.tidy.not_here"))
    action, wanted = args.action, args.folder.strip()
    if action == "move" and not wanted:
        return ToolResult(ok=False, content=phrase("email.tools.tidy.which_folder"))
    mails: dict[str, Any] = {}
    missing: list[str] = []
    for given in dict.fromkeys(r.strip().strip("[]").strip() for r in args.mails):
        m = await port.get(given) if given else None
        if m is not None:
            mails.setdefault(m.ref, m)
        elif given:
            missing.append(phrase("email.tools.tidy.sent", ref=inert(given, 200)) if port.sent_mail(given) is not None
                           else phrase("email.tools.tidy.not_found", ref=inert(given, 200)))
    boxes: dict[str, list[Any]] = {}
    outcome: dict[str, tuple[str, str]] = {}  # réf → (ce qui en est dit, ce que ça a donné)
    targets: dict[str, str] = {}
    lost: set[str] = set()  # les boîtes où le dossier demandé n'existe pas
    todo: list[Any] = []
    already = family("email.tools.tidy.already")
    for m in mails.values():
        if m.account not in boxes:
            boxes[m.account] = port.folders(m.account)
        folders = boxes[m.account]
        role = next((f.role for f in folders if f.name == m.folder), "")
        if action == "move":
            target = _folder_named(folders, wanted)
            if target is None:
                lost.add(m.account)
                outcome[m.ref] = (phrase("email.tools.tidy.unknown_folder", folder=inert(wanted, 80)), REFUSED)
                continue
            targets[m.ref] = target.name
        there = {"read": m.seen, "unread": not m.seen, "flag": m.flagged, "unflag": not m.flagged,
                 "archive": role == "archive", "trash": role == "trash", "move": targets.get(m.ref) == m.folder}
        if there[action]:
            outcome[m.ref] = (already[action], ALREADY)
        else:
            todo.append(m)
    done = family("email.tools.tidy.done")
    if action == "read" and todo:
        # par lot : une session par boîte et par dossier ; ce que le serveur n'a pas pris se relit dans le cache
        try:
            await port.mark_seen([m.ref for m in todo])
        except (OSError, RuntimeError, ValueError) as exc:  # une erreur IMAP est une OSError ou une ImapError
            outcome.update((m.ref, (_refusal(exc), REFUSED)) for m in todo)
        else:
            for m in todo:
                now = await port.get(m.ref)
                outcome[m.ref] = (done["read"], DONE) if now is not None and now.seen else \
                    (phrase("email.tools.tidy.missed"), REFUSED)
    else:
        for m in todo:
            try:
                where = await _gesture(port, m.ref, action, targets.get(m.ref, ""))
            except (OSError, RuntimeError, ValueError) as exc:
                outcome[m.ref] = (_refusal(exc), REFUSED)
                continue
            into = phrase("email.tools.tidy.into", folder=inert(where, 80)) if where else ""
            outcome[m.ref] = (done[action] + into, DONE)
    # elle n'en parlera plus : un mail qu'elle avait remarqué et pas lu, lu ou rangé par elle (``by`` vide)
    state, how, who = ctx.frame.state("email"), TIDY_HOW.get(action, ""), keepers(ctx.frame)
    quiet, lines = [], []
    for m in mails.values():
        said, result = outcome[m.ref]
        seen = state.mails.get(m.ref)
        if how and result != REFUSED and seen is not None and not seen.read:
            quiet.append(READ.draft(mail=m.ref, how=how))
        # ce que personne n'avait encore ouvert sur le serveur : elle le sait, et en fait ce qu'elle veut
        unseen = phrase("email.tools.tidy.unseen", who=who) if how and result == DONE and not m.seen else ""
        lines.append(phrase("email.tools.tidy.line", ref=m.ref, sender=inert(m.sender, 200),
                            subject=inert(m.subject, 200), outcome=said, unseen=unseen))
    if quiet:
        await ctx.emit(*quiet)
    lines += missing
    lines += [_folders_line(account, boxes[account]) for account in sorted(lost)]
    results = [result for _, result in outcome.values()]
    # ranger prouve qu'une exécution a produit, quand un mail a changé (ADR 0104)
    return ToolResult(ok=any(r != REFUSED for r in results), content="\n".join((phrase("email.tools.data"), *lines)),
                      proof=DONE in results)


# ── Ce qui part ───────────────────────────────────────────────────────────


def _legacy_digest(args: Mapping[str, Any]) -> str:
    kept = {k: v for k, v in args.items() if not str(k).startswith("_")}
    return hashlib.sha256(json.dumps(kept, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]


def preview(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Preview | None:
    """Exactement ce qui partirait (l'en-tête, le texte avec sa signature et sa citation)."""
    port = ports.get("mail")
    if port is None:
        return None
    draft_id = str(args.get("draft") or "")
    if not draft_id:  # une proposition d'avant les brouillons : ses arguments disent tout
        text = f"À : {args.get('to', '')}\nObjet : {args.get('subject', '')}\n\n{args.get('body', '')}"
        return Preview(text, _legacy_digest(args))
    shown = port.preview(draft_id)
    draft = port.draft(draft_id)
    if shown is None or draft is None:
        return Preview("(ce brouillon n'existe plus)", "", blocked="ce brouillon n'existe plus")
    if draft.state != "brouillon":
        return Preview("(ce brouillon n'est plus à envoyer)", shown.digest, blocked="il est déjà parti ou abandonné")
    head = [f"De : {shown.sender}", f"À : {shown.to}"] + ([f"Cc : {shown.cc}"] if shown.cc else [])
    head.append(f"Objet : {shown.subject}")
    if draft.edited_by:
        head.append(f"(retouché par {draft.edited_by})")
    return Preview("\n".join(head) + "\n\n" + shown.text, shown.digest, shown.blocked)


@EMAIL.capability("send", description="Envoyer un mail (un brouillon, après accord).", preview=preview)
async def send(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port = ports.get("mail")
    if port is None:
        return False, "pas de boîte aux lettres"
    draft_id = str(args.get("draft") or "")
    try:
        if draft_id:
            sent = await port.send_draft(draft_id, digest=str(args.get("_apercu") or ""))
        else:
            sent = await port.send(str(args.get("to", "")), str(args.get("subject", "")), str(args.get("body", "")),
                                   str(args.get("reply_to") or ""))
    except (OSError, RuntimeError, ValueError) as exc:  # une erreur SMTP est une OSError
        return False, str(exc)[:300] or type(exc).__name__
    return True, f"envoyé ({sent})"


@EMAIL.effect(rt.EFFECT_EXECUTED)
async def _gone(ev: Any, ports: Mapping[str, Any]) -> list[Any] | None:
    """Son brouillon est parti : elle le sait (retouché par son opérateur, ou tel qu'elle l'avait écrit)."""
    frame_of, port = ports.get("frame"), ports.get("mail")
    if frame_of is None or port is None or not ev.data.ok:
        return None
    frame = frame_of()
    seen = frame.state("email").drafts.get(ev.data.proposal)
    draft = port.draft(seen.draft) if seen is not None and seen.draft else None
    if draft is None or not draft.sent_id:
        return None
    edited = bool(draft.edited_by)
    first = next(iter(addresses(draft.to)), ("", ""))
    who = first[0] or first[1] or draft.to
    summary = phrase("email.tools.sent", who=inert(who, 120), subject=inert(draft.subject, 200),
                     edited=phrase("email.tools.edited", name=keeper_name(frame, draft.edited_by)) if edited else "")
    return [c.SENT.draft(
        source="email", kind=c.SENT_KIND, summary=Content.of(summary[:400], level=int(Sensitivity.PERSONAL)),
        pertinence=0.55 if edited else 0.35, sensitivity=int(Sensitivity.PERSONAL), bundle=BUNDLE,
        mail=draft.sent_id, to=draft.to[:200], address=first[1], by=seen.by if seen is not None else "",
        in_reply_to=draft.reply_to, account=draft.account, draft=draft.id, edited=edited,
        about=tuple(h for h in (c.address_handle(first[1]),) if h), dedupe_key=f"sent:{draft.sent_id}")]

