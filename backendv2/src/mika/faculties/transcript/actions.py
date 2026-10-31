"""Juger une de ses réponses (ADR 0113) : son opératrice dit, depuis le chat ou la console, si elle était adaptée —
et, si elle veut, ce qu'elle aurait dû dire ou pourquoi. Le fil le garde à côté du message ; aucune faculté ne le
vit (``transcript.judged`` n'est pas public).

Régler un fil de travail (ADR 0164) : son opératrice lui donne, depuis le chat, un titre, une petite description —
ce que Mika relit en tête de ce fil —, ou l'archive. Le réglage entier à chaque fois ; le dernier vaut."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from mika.contracts import transcript as c
from mika.faculties.transcript import TRANSCRIPT, TranscriptState
from mika.kernel.events import Content
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.operate import ActionContext, Done, Refused
from mika.vocab.privacy import Sensitivity

#: ce que dit un commentaire, au plus
COMMENT_MAX = 2000

#: retirer son avis (une valeur à part : un champ vide se lit comme absent)
WITHDRAW = "retire"
VERDICT_CHOICES = ((c.VERDICT_OK, "adaptée"), (c.VERDICT_KO, "pas adaptée"), (WITHDRAW, "retirer mon avis"))


class JudgeArgs(BaseModel):
    seq: Annotated[int, Knob(widget="hidden")] = Field(gt=0)
    verdict: Annotated[Literal["ok", "ko", "retire"], Knob(label="Sa réponse était", choices=VERDICT_CHOICES,
                                                     advanced=False)] = "ok"
    comment: Annotated[str, Knob(label="Ce qu'elle aurait dû dire, ou pourquoi", widget="textarea", advanced=False,
                                 help="facultatif")] = Field("", max_length=COMMENT_MAX)


@TRANSCRIPT.action("juger", title="Juger sa réponse", args=JudgeArgs, emits=[c.JUDGED], section="fil", inline=True,
                   description="Dire si sa réponse était adaptée, et ce qu'elle aurait dû dire : un exemple pour sa voix.")
def _judge(s: TranscriptState, frame: Frame, args: JudgeArgs, ctx: ActionContext) -> Done:
    t = c.thread_table()
    rows = ctx.store.query_mind(select(t.c.person).where(t.c.id == args.seq, t.c.role == "assistant"))
    if not rows:
        raise Refused("Ce message n'est pas une de ses réponses, ou il a été oublié.")
    verdict = "" if args.verdict == WITHDRAW else args.verdict
    comment = args.comment.strip()
    draft = c.JUDGED.draft(
        seq=args.seq, verdict=verdict, by=ctx.by, person=str(rows[0][0] or ""),
        comment=Content.of(comment, level=int(Sensitivity.PERSONAL)) if comment and verdict else None)
    said = {c.VERDICT_OK: "Noté : sa réponse était adaptée.", c.VERDICT_KO: "Noté : sa réponse n'était pas adaptée."}
    return Done(drafts=(draft,), message=said.get(verdict, "Ton avis est retiré."))


#: le titre d'un fil de travail, sa description : au plus
STRAND_TITLE_MAX = 120
STRAND_DESCRIPTION_MAX = 2000


class StrandArgs(BaseModel):
    strand: Annotated[str, Knob(widget="hidden")] = Field(min_length=1, max_length=c.STRAND_MAX,
                                                          pattern=r"^[A-Za-z0-9_-]+$")
    title: Annotated[str, Knob(label="Titre", advanced=False, help="facultatif")] = Field(
        "", max_length=STRAND_TITLE_MAX)
    description: Annotated[str, Knob(label="De quoi parle ce fil", widget="textarea", advanced=False,
                                     help="ce qu'elle relit en tête de ce fil, à chaque message ; facultatif")] = Field(
        "", max_length=STRAND_DESCRIPTION_MAX)
    archived: Annotated[bool, Knob(label="Archivé", advanced=False)] = False


@TRANSCRIPT.action("regler_fil", title="Régler un fil de travail", args=StrandArgs, emits=[c.STRAND_SET],
                   section="fil", inline=True,
                   description="Le titre et la petite description d'un fil de travail du mode pro, ou l'archiver.")
def _set_strand(s: TranscriptState, frame: Frame, args: StrandArgs, ctx: ActionContext) -> Done:
    if not ctx.by:
        raise Refused("Un fil de travail se règle par celle à qui il est.")
    level = int(Sensitivity.PERSONAL)
    draft = c.STRAND_SET.draft(
        person=ctx.by, strand=args.strand, title=Content.of(" ".join(args.title.split()), level=level),
        description=Content.of(args.description.strip(), level=level), archived=args.archived)
    return Done(drafts=(draft,), message="Le fil est archivé." if args.archived else "Le fil est réglé.")
