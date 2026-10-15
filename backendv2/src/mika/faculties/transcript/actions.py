"""Juger une de ses réponses (ADR 0113) : son opératrice dit, depuis le chat ou la console, si elle était adaptée —
et, si elle veut, ce qu'elle aurait dû dire ou pourquoi. Le fil le garde à côté du message ; aucune faculté ne le
vit (``transcript.judged`` n'est pas public)."""

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
