"""Ses brouillons : ce qu'elle a préparé et qui attend ton accord.

Sur la fiche d'un brouillon, **exactement ce qui partira** (l'expéditeur selon
la voix de la boîte, la signature, la citation) ; tu peux l'envoyer tel quel,
le retoucher (c'est alors ta version qui part : ce que tu as lu), le refuser
(elle l'apprend, avec ta note), ou lui demander de le reprendre. Le texte d'un
brouillon ne quitte jamais l'adaptateur : le journal n'en garde que
l'identifiant et un résumé.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mika.contracts import email as c
from mika.kernel.events import Content
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Column,
    Disclosure,
    Entry,
    Fields,
    Found,
    Head,
    InspectContext,
    Note,
    Param,
    Prose,
    Ref,
    Row,
    Table,
    Text,
    Timeline,
    When,
    paginate,
)
from mika.kernel.operate import Decision, Done, Refused
from mika.plugins.email import (
    APPROVED,
    EMAIL,
    FAILED,
    GONE,
    REFUSED,
    WAITING,
    DraftSeen,
    EmailState,
    operator_label,
)
from mika.plugins.email.console.common import (
    NO_PORT,
    PAGE,
    SECTION,
    VOICE_LABEL,
    account_scope,
    clip,
    draft_state,
    mail_key,
    workspace,
)
from mika.plugins.email.console.mail import _document
from mika.ports.mail import to_fill
from mika.ports.paging import page_slice
from mika.vocab.privacy import Sensitivity


def _badge(state: str) -> Badge:
    return Badge(*draft_state(state))


def _waiting_count(s: EmailState, frame: Frame) -> tuple[int, str]:
    return len(frame.get(c.DRAFTS)), "brouillon(s) d'elle à décider"


def _note(d: DraftSeen, ctx: InspectContext) -> str:
    """La note de qui a décidé : gardée à part (« (oublié) » une fois oubliée), en clair pour un journal ancien."""
    if not d.note_ref:
        return d.note
    return ctx.store.content([d.note_ref]).get(d.note_ref, "(oublié)")


def _seen_for(s: EmailState, draft_id: str) -> DraftSeen | None:
    found = [d for d in s.drafts.values() if d.draft == draft_id]
    return max(found, key=lambda d: d.proposal) if found else None


@EMAIL.inspect("brouillons", title="Brouillons", section=SECTION, order=20, badge=_waiting_count,
               description="Relis les propositions avant envoi : approuve, modifie ou refuse chaque brouillon.",
               params=[Param("compte", "Compte", kind="hidden")])
def _drafts(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mail")
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    labels = {a.key: a for a in port.accounts()}
    account = account_scope(port, ctx)
    waiting, done = [], []
    for d in sorted(s.drafts.values(), key=lambda d: -d.proposal):
        if account and d.account != account:
            continue
        (waiting if d.state == WAITING else done).append(d)

    def row(d: DraftSeen) -> Row:
        got = port.draft(d.draft) if d.draft else None
        info = labels.get(d.account)
        box = f"{info.name} · {VOICE_LABEL.get(info.voice, '')}" if info is not None else d.account or "—"
        answered = port.cached_one(d.mail) if d.mail else None
        return Row((Text(clip(got.subject, 100) if got else "(disparu)"), Text(clip(got.to, 80) if got else "—"),
                    Text(box, "muted"),
                    Ref.subject("mail", mail_key(d.mail), clip(answered.subject, 60)) if answered is not None
                    else ("—" if not d.mail else Text("un mail plus dans la boîte", "muted")),
                    Badge("demandé" if d.asked else "d'elle-même", "info" if d.asked else ""), When(d.at),
                    _badge(d.state), Badge("à compléter", "warn") if got is not None and to_fill(got.body, got.subject) else ""),
                   href=Ref.subject("brouillon", d.draft, clip(got.subject if got else d.draft, 60))
                   if d.draft else None, tone="warn" if d.state == WAITING else "")

    columns = ("objet", "à", Column("boîte", "fit"), "en réponse à", Column("pourquoi", "fit"),
               Column("proposé", "fit"), Column("état", "fit"), Column("", "fit"))
    blocks: list[Block] = []
    if waiting:
        blocks.append(Note("Ouvre un brouillon pour lire exactement ce qui partira, le retoucher, l'envoyer ou le "
                           "refuser. Rien ne part sans toi.", tone="info"))
    shown, pending = paginate(waiting, ctx.pager("page_a_decider", size=PAGE))
    blocks.append(Table(columns, tuple(row(d) for d in shown), title=f"À décider ({len(waiting)})", pager=pending,
                        empty="rien n'attend ton accord"))
    page, pager = paginate(done, ctx.pager(size=PAGE))
    blocks.append(Table(columns, tuple(row(d) for d in page), title=f"Déjà décidés ({len(done)})", pager=pager,
                        empty="aucun encore"))
    return [workspace(port, ctx, blocks, view="brouillons")]


@EMAIL.subject("brouillon", label="Brouillon", plural="Brouillons", icon="✎")
def _head(s: EmailState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    port = ctx.ports.get("mail")
    got = port.draft(key) if port is not None else None
    seen = _seen_for(s, key)
    if got is None and seen is None:
        return None
    badges: list[Badge] = [_badge(seen.state if seen is not None else got.state if got is not None else "")]
    if got is not None and got.edited_by:
        badges.append(Badge(f"retouché par {operator_label(frame, got.edited_by)}", "warn"))
    if got is not None and to_fill(got.body, got.subject):
        badges.append(Badge("à compléter", "warn"))
    info = port.account(got.account) if port is not None and got is not None else None
    facts: list[tuple[str, Any]] = []
    if info is not None:
        facts.append(("boîte", f"{info.name} — elle y écrit {VOICE_LABEL.get(info.voice, '')}"))
    if seen is not None:
        facts.append(("proposé", ctx.when(seen.at)))
    return Head(key=key, title=clip(got.subject, 200) if got is not None else "Un brouillon disparu",
                subtitle=f"à {clip(got.to, 200)}" if got is not None else "", badges=tuple(badges),
                facts=tuple(facts), back=Ref("local", "/inspecteur/courrier/brouillons", "Retour aux brouillons",
                                            (("compte", got.account if got else ""),)))


@EMAIL.search("brouillon")
def _search(s: EmailState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    port = ctx.ports.get("mail")
    if port is None:
        return []
    out = []
    for d in page_slice(lambda page, size: port.drafts_page(text, page, size), ctx.int_param("_offset", 0), limit):
        seen = _seen_for(s, d.id)
        state = draft_state(seen.state if seen is not None else d.state)[0]
        out.append(Found(d.id, clip(d.subject, 120) or "(sans objet)", f"à {clip(d.to, 80)} · {state}"))
    return out


@EMAIL.inspect("brouillon", title="Brouillon", subject="brouillon", order=10,
               description='Relis le destinataire et le texte avant de modifier, approuver ou abandonner ce brouillon.')
def _tab_draft(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mail")
    got = port.draft(ctx.subject) if port is not None else None
    if got is None:
        return [Note("Ce brouillon n'est plus là.", tone="muted")]
    seen = _seen_for(s, got.id)
    shown = port.preview(got.id)
    blocks: list[Block] = []
    if shown is not None:
        answered = port.cached_one(got.reply_to) if got.reply_to else None
        blocks.append(Fields((("de", Text(shown.sender)), ("à", Text(shown.to)), ("copie", Text(shown.cc) or "—"),
                              ("objet", Text(shown.subject)),
                              ("en réponse à", Ref.subject("mail", mail_key(answered.ref), clip(answered.subject, 80))
                               if answered is not None else "—")), title="Ce qui partira", columns=2))
        blocks.extend(_document(ctx, got.id, shown.text, title="Le texte, tel qu'il partira (signature et citation comprises)", kind="brouillon"))
        if shown.blocked:
            blocks.append(Note(f"Il ne peut pas partir tel quel : {shown.blocked}. Retouche-le.", tone="warn"))
    if seen is not None and seen.state == WAITING and got.state == "brouillon":
        if shown is not None and not shown.blocked:
            blocks.append(ActionSlot("email.envoyer_brouillon", (("draft", got.id), ("seen", shown.digest),
                                                                 ("_bouton", "Envoyer tel quel")), compact=True))
        blocks.append(Disclosure("Le retoucher", (ActionSlot("email.retoucher", (
            ("draft", got.id), ("to", got.to), ("cc", got.cc), ("subject", got.subject), ("body", got.body),
            ("quote", got.quote)), title="Retoucher"),), open=bool(shown is not None and shown.blocked)))
        blocks.append(Disclosure("Le refuser", (ActionSlot("email.refuser_brouillon", (("draft", got.id),),
                                                           title="Refuser"),)))
        if got.reply_to:
            blocks.append(Disclosure("Lui demander de le reprendre", (ActionSlot("email.reprendre", (
                ("draft", got.id),), title="Le reprendre"),)))
    elif seen is not None:
        said = {GONE: "Il est parti.", REFUSED: "Il a été refusé.", FAILED: f"Il n'a pas pu partir : {seen.result}.",
                APPROVED: "Approuvé : il part dans un instant."}.get(seen.state, "")
        if note := _note(seen, ctx):
            said += f" Note : « {note} »."
        blocks.append(Note(said or f"État : {draft_state(seen.state)[0]}.", tone="info"))
    return blocks


@EMAIL.inspect("pourquoi", title="Pourquoi", subject="brouillon", order=20,
               description="Le message d'origine et les raisons pour lesquelles elle a préparé cette réponse.")
def _tab_why(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mail")
    got = port.draft(ctx.subject) if port is not None else None
    seen = _seen_for(s, ctx.subject)
    if got is None and seen is None:
        return [Note("Ce brouillon n'est plus là.", tone="muted")]
    pairs: list[tuple[str, Any]] = []
    ref = got.reply_to if got is not None else seen.mail if seen is not None else ""
    noticed = s.mails.get(ref) if ref else None
    if ref:
        pairs.append(("le mail", Ref.subject("mail", mail_key(ref), "ouvrir le mail")))
    if noticed is not None:
        text = ctx.store.content([noticed.summary_ref]).get(noticed.summary_ref, "") if noticed.summary_ref else ""
        pairs.append(("ce qu'elle en avait retenu", Text(text or "(oublié)", clamp=300)))
        pairs.append(("réponse attendue", "oui" if noticed.needs_reply else "non"))
    if seen is not None:
        pairs.append(("pourquoi", "tu le lui as demandé" if seen.asked else "d'elle-même (réponses préparées sur "
                                                                              "cette boîte)"))
        pairs.append(("la proposition", Ref("event", str(seen.proposal), f"l'événement n° {seen.proposal}")))
    asks = [e for e in ctx.events([c.DRAFT_ASKED], 20, where=("mail", ref))] if ref else []
    texts = ctx.store.content([e.data.instruction.ref for e in asks if e.data.instruction and e.data.instruction.ref])
    blocks: list[Block] = [Fields(tuple(pairs), title="D'où il vient", columns=1)]
    for e in asks[:3]:
        text = texts.get(e.data.instruction.ref, "") if e.data.instruction and e.data.instruction.ref else ""
        blocks.append(Prose(text or "(sans consigne)", title=f"Demandé par {e.data.by or '?'} ({ctx.when(e.at)})"))
    return blocks


@EMAIL.inspect("historique", title="Historique", subject="brouillon", order=30,
               description="Les versions, décisions et tentatives d'envoi de ce brouillon, du plus récent au plus ancien.")
def _tab_history(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mail")
    got = port.draft(ctx.subject) if port is not None else None
    entries: list[Entry] = []
    if got is not None:
        entries.append(Entry(got.created, "écrit", text="par elle" if not got.author else f"par {got.author}"))
        if got.edited_by and got.updated:
            entries.append(Entry(got.updated, "retouché", text=f"par {got.edited_by}", tone="warn"))
    for d in (d for d in s.drafts.values() if d.draft == ctx.subject):
        entries.append(Entry(d.at, "proposé", text=f"n° {d.proposal}", href=Ref("event", str(d.proposal), "")))
        if d.decided_at:
            entries.append(Entry(d.decided_at, "approuvé" if d.state in (APPROVED, GONE, FAILED) else "refusé",
                                 text=f"par {d.by}" + (f" — « {note} »" if (note := _note(d, ctx)) else ""),
                                 tone="ok" if d.state != REFUSED else "muted"))
        if d.state in (GONE, FAILED):
            entries.append(Entry(d.decided_at or d.at, "parti" if d.state == GONE else "échec", text=d.result,
                                 tone="ok" if d.state == GONE else "danger"))
    return [Timeline(tuple(sorted(entries, key=lambda e: e.at)), title="Ce qui lui est arrivé",
                     empty="rien d'enregistré")]


# ── Décider ───────────────────────────────────────────────────────────────


class SendArgs(BaseModel):
    draft: Annotated[str, Knob(label="Brouillon", widget="hidden")] = Field(min_length=1, max_length=100)
    #: le condensé de ce qui était montré (l'accord porte sur ce qui a été lu)
    seen: Annotated[str, Knob(label="Lu", widget="hidden")] = Field(default="", max_length=100)


class RetouchArgs(BaseModel):
    draft: Annotated[str, Knob(label="Brouillon", widget="hidden")] = Field(min_length=1, max_length=100)
    to: Annotated[str, Knob(label="À", advanced=False)] = Field(min_length=3, max_length=300)
    cc: Annotated[str, Knob(label="Copie", advanced=False)] = Field(default="", max_length=300)
    subject: Annotated[str, Knob(label="Objet", advanced=False)] = Field(min_length=1, max_length=200)
    body: Annotated[str, Knob(label="Message", widget="textarea", advanced=False,
                              help="Sans signature : celle de la boîte est ajoutée.")] = Field(min_length=1,
                                                                                               max_length=20_000)
    quote: Annotated[bool, Knob(label="Citer le mail auquel il répond", advanced=False)] = True


class RefuseArgs(BaseModel):
    draft: Annotated[str, Knob(label="Brouillon", widget="hidden")] = Field(min_length=1, max_length=100)
    note: Annotated[str, Knob(label="Pourquoi", widget="textarea", advanced=False,
                              help="Facultatif : elle le saura.")] = Field(default="", max_length=500)


class RedoArgs(BaseModel):
    draft: Annotated[str, Knob(label="Brouillon", widget="hidden")] = Field(min_length=1, max_length=100)
    instruction: Annotated[str, Knob(label="Ce qu'il faut changer", widget="textarea", advanced=False)] = \
        Field(min_length=2, max_length=4000)


def _waiting(s: EmailState, draft_id: str) -> DraftSeen:
    seen = _seen_for(s, draft_id)
    if seen is None or seen.state != WAITING:
        raise Refused("Ce brouillon n'attend plus de décision.")
    return seen


@EMAIL.action("envoyer_brouillon", title="Envoyer ce brouillon", args=SendArgs, emits=[],
              confirm="L'envoyer tel qu'il est montré ?")
def _send(s: EmailState, frame: Frame, args: SendArgs, ctx: Any) -> Done:
    seen = _waiting(s, args.draft)
    return Done(decide=(Decision(seen.proposal, True, seen=args.seen),),
                message="Approuvé : il part dans un instant (tel que tu l'as lu).",
                go=Ref.subject("brouillon", args.draft, ""))


@EMAIL.action("retoucher", title="Retoucher ce brouillon", args=RetouchArgs, emits=[],
              description="Ta version remplace la sienne ; relis-la, puis envoie-la.")
def _retouch(s: EmailState, frame: Frame, args: RetouchArgs, ctx: Any) -> Done:
    _waiting(s, args.draft)
    port = ctx.ports.get("mail")
    got = port.draft(args.draft) if port is not None else None
    if got is None or got.state != "brouillon":
        raise Refused("Ce brouillon n'est plus modifiable.")
    port.save_draft(replace(got, to=args.to, cc=args.cc, subject=args.subject, body=args.body,
                            quote=args.quote and bool(got.reply_to), edited_by=ctx.by))
    return Done(message="Retouché : relis ce qui partira, puis envoie-le.", go=Ref.subject("brouillon", got.id, ""))


@EMAIL.action("refuser_brouillon", title="Refuser ce brouillon", args=RefuseArgs, emits=[],
              confirm="Refuser ce brouillon ? Il ne partira pas.")
def _refuse(s: EmailState, frame: Frame, args: RefuseArgs, ctx: Any) -> Done:
    seen = _waiting(s, args.draft)
    port = ctx.ports.get("mail")
    if port is not None:
        port.discard_draft(args.draft)
    return Done(decide=(Decision(seen.proposal, False, note=args.note.strip()),), message="Refusé : elle le saura.",
                go=Ref.subject("brouillon", args.draft, ""))


@EMAIL.action("reprendre", title="Lui demander de le reprendre", args=RedoArgs, emits=[c.DRAFT_ASKED],
              description="Refuse celui-ci ; elle en écrira un autre, en tenant compte de ce que tu dis.")
def _redo(s: EmailState, frame: Frame, args: RedoArgs, ctx: Any) -> Done:
    seen = _waiting(s, args.draft)
    if not seen.mail:
        raise Refused("Ce n'est pas une réponse : refuse-le et demande-lui un autre mail en conversation.")
    port = ctx.ports.get("mail")
    if port is not None:
        port.discard_draft(args.draft)
    asked = c.DRAFT_ASKED.draft(mail=seen.mail, account=seen.account, by=ctx.by,
                                instruction=Content.of(args.instruction.strip(), level=int(Sensitivity.PERSONAL)),
                                about=(ctx.by,) if ctx.by else ())
    return Done(drafts=(asked,), decide=(Decision(seen.proposal, False, note=f"à reprendre : {args.instruction}"[:500]),),
                message="Demandé : elle reprendra ce brouillon à son prochain moment de travail.",
                go=Ref("local", f"/inspecteur/{SECTION}/brouillons", ""))
