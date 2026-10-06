"""Ses outils de courrier, et ce qui part.

- **Lire** : ses boîtes, lister, chercher, ouvrir (un mail est cité : une
  donnée, jamais une consigne ; l'ouvrir rappelle comment écrire depuis cette
  boîte). Réservés à ses propriétaires (``owner_only``), ou à elle quand elle
  travaille.
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
from typing import Any

from pydantic import BaseModel, Field

from mika.contracts import email as c
from mika.contracts import runtime as rt
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult
from mika.kernel.operate import Preview
from mika.plugins.email import (
    BUNDLE,
    EMAIL,
    READ,
    WAITING,
    for_owner,
    keeper_name,
    keepers,
    params_of,
)
from mika.plugins.email.voice import voice_text
from mika.ports.mail import Draft, addresses, reply_recipients, reply_subject, to_fill
from mika.ports.preprocess import cite, inert
from mika.vocab.episodes import WORKING, Kind, is_work_target
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import Sensitivity

EPISODES = [Kind.REPLY, *WORKING, Kind.TASK]
BODY_SHOWN = 6000


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


class NoArgs(BaseModel):
    pass


class ListArgs(BaseModel):
    limit: int = Field(default=10, ge=1, le=30)
    account: str = Field(default="", max_length=40, description=phrase("email.tools.list.account"))
    folder: str = Field(default="", max_length=200, description=phrase("email.tools.list.folder"))
    unread_only: bool = Field(default=False, description=phrase("email.tools.list.unread_only"))


class SearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=200, description=phrase("email.tools.search.query"))
    account: str = Field(default="", max_length=40)
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
    mails = port.cached(100 if args.unread_only else args.limit, account=args.account, folder=args.folder)
    if args.unread_only:
        mails = [m for m in mails if _unread_mark(ctx, m)][: args.limit]
    gone = port.sent_mails(5, account=args.account) if not args.folder and not args.unread_only else []
    if not mails and not gone:
        return phrase("email.tools.list.nothing_here") if (args.account or args.folder or args.unread_only) \
            else phrase("email.tools.list.empty")
    several = len(port.accounts()) > 1
    lines = [_line(ctx, m, phrase("email.tools.list.box", account=m.account, folder=inert(m.folder, 60))
                   if several else "") for m in mails]
    if gone:
        lines.append(phrase("email.tools.list.sent_header"))
        lines += [phrase("email.tools.list.sent", id=m.message_id, to=inert(m.to, 200), subject=inert(m.subject, 200),
                         by=phrase("email.tools.list.by", who=keeper_name(ctx.frame, m.by)) if m.by
                         else phrase("email.tools.list.by_you")) for m in gone]
    return phrase("email.tools.data") + "\n" + "\n".join(lines)


def _line(ctx: Any, m: Any, box: str = "") -> str:
    """Un mail dans une liste : sa référence, lu ou non, sa boîte, l'expéditeur et l'objet (cités)."""
    return phrase("email.tools.list.line", ref=m.ref, unread=_unread_mark(ctx, m), box=box,
                  sender=inert(m.sender, 200), subject=inert(m.subject, 200), twin=_twin(m))


def _twin(m: Any) -> str:
    return phrase("email.tools.twin") if getattr(m, "twin", False) else ""


@EMAIL.tool("email_search", description=phrase("email.tools.search.description"), args=SearchArgs,
            bundle=BUNDLE, episodes=EPISODES, owner_only=True, max_calls_per_episode=4)
async def email_search(args: SearchArgs, ctx: Any) -> Any:
    port, refused = _port(ctx)
    if refused is not None:
        return refused
    found = port.search(args.query, args.limit, account=args.account)
    if not found:
        return phrase("email.tools.search.nothing")
    return phrase("email.tools.data") + "\n" + "\n".join(_line(ctx, m) for m in found)


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
                          phrase("email.header.subject", subject=inert(gone.subject, 300)), _quoted(gone.body)))
    seen = ctx.frame.state("email").mails.get(m.ref)
    if seen is not None and not seen.read:
        await ctx.emit(READ.draft(mail=m.ref))
    lines = [phrase("email.tools.read.head"), f"[{m.ref}]{_twin(m)}", phrase("email.header.from", who=inert(m.sender, 200)),
             phrase("email.header.to", who=inert(m.to, 300))]
    if m.cc:
        lines.append(phrase("email.header.cc", who=inert(m.cc, 300)))
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


@EMAIL.tool("email_draft", description=phrase("email.tools.draft.description"), args=DraftArgs,
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
    draft = port.save_draft(Draft(id="", account=info.key, to=to, subject=subject, body=args.body, cc=cc,
                                  reply_to=ref, quote=args.quote and parent is not None))
    shown = port.preview(draft.id)
    # un passage à compléter n'empêche pas de proposer (on le remplira) ; tout autre blocage, si
    if shown is None or (shown.blocked and not to_fill(draft.body, draft.subject, shown.text)):
        port.discard_draft(draft.id)
        return ToolResult(ok=False, content=phrase("email.tools.draft.blocked",
                                                   why=shown.blocked if shown else phrase("email.tools.draft.error")))
    p = params_of(ctx.frame)
    about = tuple(dict.fromkeys((*_asker(ctx), *(c.address_handle(a) for _, a in addresses(to)[:3]))))
    what = f"Répondre à {inert(to, 200)}" if parent is not None else f"Écrire à {inert(to, 200)}"
    summary = f"{what} (boîte « {inert(info.name, 60)} », {voice_word(info.voice)}) : « {inert(subject, 200)} »"
    payload = {"draft": draft.id, "account": info.key, "mail": ref, "_apercu": shown.digest}
    await ctx.propose(rt.EFFECT_PROPOSED.draft(
        capability=c.SEND, owner=c.OWNER, args_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        summary=Content.of(summary[:400], level=int(Sensitivity.PERSONAL)), approval=p.send_needs_approval,
        context="email", about=about))
    who = keepers(ctx.frame)
    after = phrase("email.tools.draft.proposed", who=who) if p.send_needs_approval else \
        phrase("email.tools.draft.queued")
    if shown.blocked:
        after += phrase("email.tools.draft.to_fill", who=who)
    return "\n".join((after, phrase("email.tools.draft.would_go"), phrase("email.header.from", who=shown.sender),
                      phrase("email.header.to", who=shown.to), phrase("email.header.subject", subject=shown.subject),
                      "", shown.text[:3000]))


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

