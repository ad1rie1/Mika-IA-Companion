"""La console de Teams (Ses canaux › Teams) : ses conversations, ses réponses, l'extension.

Sur la fiche d'une réponse, **exactement ce qui partira** (la signature comprise) ; quand elle attend ton accord
(mode « après ton accord »), tu peux l'envoyer telle quelle, la retoucher (c'est alors ta version qui part : ce que
tu as lu), la refuser (elle l'apprend, avec ta note), ou lui demander de la reprendre. Sur la fiche d'une
conversation, tu peux lui demander de préparer une réponse au dernier message reçu.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mika.contracts import teams as c
from mika.kernel.events import Content
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Column,
    Disclosure,
    Fields,
    Head,
    InspectContext,
    Note,
    Prose,
    Ref,
    Row,
    Table,
    Text,
    When,
    paginate,
)
from mika.kernel.operate import Decision, Done, Refused
from mika.plugins.teams import (
    APPROVED,
    FAILED,
    GONE,
    PLACED,
    QUEUED,
    REFUSED,
    TEAMS,
    UNUSED,
    WAITING,
    DraftSeen,
    TeamsState,
    latest,
    params_of,
    under_way,
)
from mika.ports.teams import MODES, to_fill
from mika.vocab.privacy import Sensitivity

SECTION = "teams"
PAGE = 25
NO_PORT = "Teams n'est pas branché ici."
KIND_LABEL = {"dm": "tête-à-tête", "group": "groupe", "channel": "canal", "meeting": "réunion", "other": "—"}
STATE_LABEL = {WAITING: ("attend ton accord", "warn"), APPROVED: ("approuvée", "info"), REFUSED: ("refusée", ""),
               QUEUED: ("en file", "info"), PLACED: ("posée dans Teams", "info"), GONE: ("partie", "ok"),
               UNUSED: ("pas servie", ""), FAILED: ("échec", "danger")}
MODE_LABEL = dict(MODES)


def _badge(state: str) -> Badge:
    label, tone = STATE_LABEL.get(state, (state, ""))
    return Badge(label, tone)


def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _waiting_count(s: TeamsState, frame: Frame) -> tuple[int, str]:
    return sum(1 for d in s.drafts.values() if d.state == WAITING), "réponse(s) Teams à décider"


def _to_answer(s: TeamsState, conversation: str) -> int:
    return sum(1 for m in s.messages.values() if m.conversation == conversation and m.needs_reply and not m.answered)


@TEAMS.inspect("conversations", title="Conversations", section=SECTION, order=10,
               description="Les conversations Teams que l'extension lui a apportées, la plus récente d'abord.")
def _conversations(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("teams")
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    if not port.configured():
        return [Note("L'extension n'a encore rien apporté. Installe-la dans le navigateur où tu ouvres Teams, "
                     "colle sa clé (Configuration › Sens › Teams), et ouvre Teams.", tone="info")]
    found = port.conversations(200)
    page, pager = paginate(found, ctx.pager(size=PAGE))
    rows = tuple(Row((Text(_clip(port.title(conv.id), 80) or "sans nom"), Text(KIND_LABEL.get(conv.kind, "—"), "muted"),
                      conv.messages, Badge(f"{n} question(s)", "warn") if (n := _to_answer(s, conv.id)) else "",
                      When(conv.last_at)),
                     href=Ref.subject("conversation_teams", conv.id, _clip(port.title(conv.id), 60) or "sans nom"))
                 for conv in page)
    return [Table(("conversation", Column("sorte", "fit"), Column("messages", "num"), Column("", "fit"),
                   Column("le dernier", "fit")), rows, title=f"Conversations ({len(found)})", pager=pager,
                  empty="aucune conversation")]


@TEAMS.inspect("reponses", title="Réponses", section=SECTION, order=20, badge=_waiting_count,
               description="Ce qu'elle a préparé à ta place, et ce que c'est devenu.")
def _replies(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("teams")
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    drafts = sorted(s.drafts.values(), key=lambda d: (d.state != WAITING, -d.proposal))
    page, pager = paginate(drafts, ctx.pager(size=PAGE))

    def row(d: DraftSeen) -> Row:
        got = port.draft(d.draft)
        return Row((Text(_clip(port.title(d.conversation), 60) or "—"), Text(_clip(got.body, 120) if got else "(disparue)"),
                    Badge("demandée" if d.asked else "d'elle-même", "info" if d.asked else ""), When(d.at),
                    _badge(d.state), Badge("retouchée", "warn") if d.edited else ""),
                   href=Ref.subject("reponse_teams", d.draft, _clip(port.title(d.conversation), 60) or d.draft),
                   tone="warn" if d.state == WAITING else "")

    mode = params_of(frame).mode
    return [Note(f"Mode : {MODE_LABEL.get(mode, mode)} (Configuration › Sens › Teams).", tone="info"),
            Table(("conversation", "réponse", Column("pourquoi", "fit"), Column("proposée", "fit"),
                   Column("état", "fit"), Column("", "fit")), tuple(row(d) for d in page),
                  title=f"Réponses ({len(drafts)})", pager=pager, empty="aucune réponse préparée")]


@TEAMS.inspect("extension", title="Extension", section=SECTION, order=30,
               description="Ce que l'extension de navigateur a apporté, et comment la brancher.")
def _extension(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("teams")
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    owner_id, owner_name = port.owner()
    pairs: list[tuple[str, Any]] = [
        ("dernier envoi de l'extension", When(port.last_batch()) if port.configured() else "jamais"),
        ("ton nom dans Teams", owner_name or "pas encore vu"), ("ton identifiant Teams", owner_id or "pas encore vu"),
        ("messages remarqués (en tête)", len(s.messages)),
        ("clé, mode, signature", Ref("local", "/inspecteur/reglages/teams", "Configuration › Sens › Teams")),
    ]
    return [Fields(tuple(pairs), title="L'extension", columns=1),
            Note("L'extension (frontend/Extension) lit ce que Teams web reçoit dans ton navigateur et l'apporte ici ; "
                 "elle relève ce qui doit repartir (un brouillon à poser, un message à envoyer). Rien ne parle à "
                 "Microsoft depuis ce serveur.", tone="muted")]


# ── Une conversation ──────────────────────────────────────────────────────


@TEAMS.subject("conversation_teams", label="Conversation Teams", plural="Conversations Teams", icon="✆")
def _conversation_head(s: TeamsState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    port = ctx.ports.get("teams")
    found = port.conversation(key) if port is not None else None
    if found is None:
        return None
    return Head(key=key, title=_clip(port.title(key), 200) or "Une conversation", subtitle=KIND_LABEL.get(found.kind, ""),
                facts=(("messages", str(found.messages)), ("le dernier", ctx.when(found.last_at))),
                back=Ref("local", f"/inspecteur/{SECTION}/conversations", "Retour aux conversations"))


@TEAMS.inspect("fil", title="Fil", subject="conversation_teams", order=10,
               description="Les derniers messages, du plus ancien au plus récent.")
def _thread(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("teams")
    if port is None or port.conversation(ctx.subject) is None:
        return [Note("Cette conversation n'est plus là.", tone="muted")]
    thread = port.thread(ctx.subject, 60)
    rows = tuple(Row((When(m.at), Text("toi" if m.own else _clip(m.author, 60)), Text(m.text, clamp=600),
                      Badge("question", "warn") if (seen := s.messages.get(m.ref)) and seen.needs_reply else "")
                     ) for m in thread)
    blocks: list[Block] = [Table((Column("quand", "fit"), Column("qui", "fit"), "message", Column("", "fit")), rows,
                                 title="Le fil", empty="aucun message")]
    received = [m for m in thread if not m.own]
    if received and not under_way(s, ctx.subject):
        last = received[-1]
        blocks.append(Disclosure("Lui demander de préparer une réponse", (ActionSlot("teams.rediger", (
            ("message", last.ref),), title="Préparer une réponse au dernier message"),)))
    return blocks


# ── Une réponse ───────────────────────────────────────────────────────────


@TEAMS.subject("reponse_teams", label="Réponse Teams", plural="Réponses Teams", icon="✎")
def _reply_head(s: TeamsState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    port = ctx.ports.get("teams")
    got = port.draft(key) if port is not None else None
    seen = latest(s, key)
    if got is None and seen is None:
        return None
    badges = [_badge(seen.state)] if seen is not None else []
    if got is not None and to_fill(got.body):
        badges.append(Badge("à compléter", "warn"))
    title = _clip(port.title(got.conversation), 120) if got is not None and port is not None else ""
    return Head(key=key, title=f"Réponse dans « {title or 'une conversation'} »", badges=tuple(badges),
                facts=(("proposée", ctx.when(seen.at)),) if seen is not None else (),
                back=Ref("local", f"/inspecteur/{SECTION}/reponses", "Retour aux réponses"))


@TEAMS.inspect("reponse", title="Réponse", subject="reponse_teams", order=10,
               description="Exactement ce qui part (ou est parti), et ce que tu peux en faire.")
def _reply(s: TeamsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("teams")
    got = port.draft(ctx.subject) if port is not None else None
    if got is None:
        return [Note("Cette réponse n'est plus là.", tone="muted")]
    seen = latest(s, got.id)
    shown = port.preview(got.id)
    answered = port.message(got.reply_to) if got.reply_to else None
    pairs: list[tuple[str, Any]] = [
        ("conversation", Ref.subject("conversation_teams", got.conversation, _clip(port.title(got.conversation), 80)
                                     or "ouvrir")),
        ("en réponse à", Text(f"{answered.author} : {_clip(answered.text, 200)}") if answered is not None else "—"),
        ("mode", MODE_LABEL.get(seen.mode, seen.mode) if seen is not None else "—"),
    ]
    if got.sent_text and got.edited:
        pairs.append(("ce qui est vraiment parti", Text(got.sent_text, clamp=600)))
    if got.reason:
        pairs.append(("pourquoi", got.reason))
    blocks: list[Block] = [Fields(tuple(pairs), title="Où elle va", columns=1)]
    text = got.final or (shown.text if shown is not None else got.body)
    blocks.append(Prose(text, title="Le texte, tel qu'il part (signature comprise)"))
    if seen is not None and seen.state == WAITING and got.state == "brouillon":
        if shown is not None and not shown.blocked:
            blocks.append(ActionSlot("teams.envoyer", (("draft", got.id), ("seen", shown.digest),
                                                       ("_bouton", "Envoyer telle quelle")), compact=True))
        elif shown is not None:
            blocks.append(Note(f"Elle ne peut pas partir telle quelle : {shown.blocked}. Retouche-la.", tone="warn"))
        blocks.append(Disclosure("La retoucher", (ActionSlot("teams.retoucher", (("draft", got.id), ("body", got.body)),
                                                             title="Retoucher"),), open=bool(shown and shown.blocked)))
        blocks.append(Disclosure("La refuser", (ActionSlot("teams.refuser", (("draft", got.id),), title="Refuser"),)))
        if got.reply_to:
            blocks.append(Disclosure("Lui demander de la reprendre", (ActionSlot("teams.reprendre", (
                ("draft", got.id),), title="La reprendre"),)))
    elif seen is not None:
        label = STATE_LABEL.get(seen.state, (seen.state, ""))[0]
        note = ""
        if seen.note_ref:
            note = ctx.store.content([seen.note_ref]).get(seen.note_ref, "(oublié)")
        blocks.append(Note(f"État : {label}." + (f" Note : « {note or seen.note} »." if note or seen.note else ""),
                           tone="info"))
    return blocks


# ── Décider, demander ─────────────────────────────────────────────────────


class SendArgs(BaseModel):
    draft: Annotated[str, Knob(label="Réponse", widget="hidden")] = Field(min_length=1, max_length=100)
    #: le condensé de ce qui était montré (l'accord porte sur ce qui a été lu)
    seen: Annotated[str, Knob(label="Lu", widget="hidden")] = Field(default="", max_length=100)


class RetouchArgs(BaseModel):
    draft: Annotated[str, Knob(label="Réponse", widget="hidden")] = Field(min_length=1, max_length=100)
    body: Annotated[str, Knob(label="Message", widget="textarea", advanced=False,
                              help="Sans signature : elle est ajoutée.")] = Field(min_length=1, max_length=4000)


class RefuseArgs(BaseModel):
    draft: Annotated[str, Knob(label="Réponse", widget="hidden")] = Field(min_length=1, max_length=100)
    note: Annotated[str, Knob(label="Pourquoi", widget="textarea", advanced=False,
                              help="Facultatif : elle le saura.")] = Field(default="", max_length=500)


class RedoArgs(BaseModel):
    draft: Annotated[str, Knob(label="Réponse", widget="hidden")] = Field(min_length=1, max_length=100)
    instruction: Annotated[str, Knob(label="Ce qu'il faut changer", widget="textarea", advanced=False)] = \
        Field(min_length=2, max_length=4000)


class AskArgs(BaseModel):
    message: Annotated[str, Knob(label="Message", widget="hidden")] = Field(min_length=1, max_length=40)
    instruction: Annotated[str, Knob(label="Ce qu'il faut y dire", widget="textarea", advanced=False,
                                     help="Facultatif : sinon, elle répond comme elle l'entend.")] = \
        Field(default="", max_length=4000)


def _waiting(s: TeamsState, draft_id: str) -> DraftSeen:
    seen = latest(s, draft_id)
    if seen is None or seen.state != WAITING:
        raise Refused("Cette réponse n'attend plus de décision.")
    return seen


@TEAMS.action("envoyer", title="Envoyer cette réponse", args=SendArgs, emits=[],
              confirm="L'envoyer dans Teams, sous ton nom, telle qu'elle est montrée ?")
def _send(s: TeamsState, frame: Frame, args: SendArgs, ctx: Any) -> Done:
    seen = _waiting(s, args.draft)
    return Done(decide=(Decision(seen.proposal, True, seen=args.seen),),
                message="Approuvée : l'extension l'enverra (telle que tu l'as lue).",
                go=Ref.subject("reponse_teams", args.draft, ""))


@TEAMS.action("retoucher", title="Retoucher cette réponse", args=RetouchArgs, emits=[],
              description="Ta version remplace la sienne ; relis-la, puis envoie-la.")
def _retouch(s: TeamsState, frame: Frame, args: RetouchArgs, ctx: Any) -> Done:
    _waiting(s, args.draft)
    port = ctx.ports.get("teams")
    got = port.draft(args.draft) if port is not None else None
    if got is None or got.state != "brouillon":
        raise Refused("Cette réponse n'est plus modifiable.")
    port.save_draft(replace(got, body=args.body.strip(), edited_by=ctx.by))
    return Done(message="Retouchée : relis ce qui partira, puis envoie-la.", go=Ref.subject("reponse_teams", got.id, ""))


@TEAMS.action("refuser", title="Refuser cette réponse", args=RefuseArgs, emits=[],
              confirm="Refuser cette réponse ? Elle ne partira pas.")
def _refuse(s: TeamsState, frame: Frame, args: RefuseArgs, ctx: Any) -> Done:
    seen = _waiting(s, args.draft)
    port = ctx.ports.get("teams")
    if port is not None:
        port.discard_draft(args.draft)
    return Done(decide=(Decision(seen.proposal, False, note=args.note.strip()),), message="Refusée : elle le saura.",
                go=Ref.subject("reponse_teams", args.draft, ""))


@TEAMS.action("reprendre", title="Lui demander de la reprendre", args=RedoArgs, emits=[c.DRAFT_ASKED],
              description="Refuse celle-ci ; elle en écrira une autre, en tenant compte de ce que tu dis.")
def _redo(s: TeamsState, frame: Frame, args: RedoArgs, ctx: Any) -> Done:
    seen = _waiting(s, args.draft)
    if not seen.message:
        raise Refused("Ce n'est pas une réponse à un message : refuse-la.")
    port = ctx.ports.get("teams")
    if port is not None:
        port.discard_draft(args.draft)
    asked = c.DRAFT_ASKED.draft(message=seen.message, conversation=seen.conversation, by=ctx.by,
                                instruction=Content.of(args.instruction.strip(), level=int(Sensitivity.PERSONAL)),
                                about=(ctx.by,) if ctx.by else ())
    return Done(drafts=(asked,), decide=(Decision(seen.proposal, False, note=f"à reprendre : {args.instruction}"[:500]),),
                message="Demandé : elle la reprendra à son prochain moment de travail.",
                go=Ref("local", f"/inspecteur/{SECTION}/reponses", ""))


@TEAMS.action("rediger", title="Lui demander une réponse", args=AskArgs, emits=[c.DRAFT_ASKED],
              subject="conversation_teams",
              description="Elle préparera une réponse au dernier message reçu, selon le mode réglé.")
def _ask(s: TeamsState, frame: Frame, args: AskArgs, ctx: Any) -> Done:
    port = ctx.ports.get("teams")
    m = port.message(args.message) if port is not None else None
    if m is None:
        raise Refused("Ce message n'est plus là.")
    if under_way(s, m.conversation) or m.ref in s.asked:
        raise Refused("Une réponse est déjà en chemin dans cette conversation.")
    instruction = args.instruction.strip()
    asked = c.DRAFT_ASKED.draft(message=m.ref, conversation=m.conversation, by=ctx.by,
                                instruction=Content.of(instruction, level=int(Sensitivity.PERSONAL)) if instruction
                                else None, about=(ctx.by,) if ctx.by else ())
    return Done(drafts=(asked,), message="Demandé : elle la préparera à son prochain moment de travail.",
                go=Ref("local", f"/inspecteur/{SECTION}/reponses", ""))
