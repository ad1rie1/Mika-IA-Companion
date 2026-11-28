"""Ce qu'elle sait d'elle et ce qui la passionne, dit en mots (ADR 0088, 0089) : des tendances, jamais une obligation
ni un nombre. Sans section ni réducteur : le récit (``narrative``) et « CE QUE TU SAIS DE TOI » (``model``) les
disent pareil, et l'ordre de leurs sections ne dépend pas de qui importe ce module."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from mika.contracts import self_ as c
from mika.vocab.interests import ASLEEP, PERSONA, VIVID, InterestView, subject_of
from mika.vocab.phrasebook import phrase

#: ce qu'elle sait d'elle, dit en mots (des tendances, jamais une obligation ni un nombre)
KNOWN_LINES: dict[str, Callable[[], str]] = {
    c.PROMISES_KEPT: lambda: phrase("self.knows.promises_kept"),
    c.PROMISES_SLIP: lambda: phrase("self.knows.promises_slip"),
    c.FINISHING_DONE: lambda: phrase("self.knows.finishing_done"),
    c.FINISHING_STRUGGLE: lambda: phrase("self.knows.finishing_struggle"),
    c.FORESIGHT_RIGHT: lambda: phrase("self.knows.foresight_right"),
    c.FORESIGHT_OFF: lambda: phrase("self.knows.foresight_off"),
}

#: ses centres d'intérêt dits dans son prompt : les plus vifs, ceux de sa persona qui se sont endormis — au plus tant
PASSIONS_SHOWN = 2


def passion_lines(views: Sequence[InterestView], labels: Mapping[str, str]) -> list[str]:
    """Ce qui la passionne en ce moment, et ce de sa persona qui l'intéresse moins qu'avant — en mots."""
    def subject(i: InterestView) -> str:
        return subject_of(i.line) if i.line else labels.get(i.key, "")

    vivid = [x for x in (subject(i) for i in views if i.level == VIVID) if x][:PASSIONS_SHOWN]
    asleep = [x for x in (subject(i) for i in views if i.level == ASLEEP and i.origin == PERSONA) if x][
        :PASSIONS_SHOWN]
    lines = [phrase("self.knows.passion", subjects=", ".join(vivid))] if vivid else []
    return lines + ([phrase("self.knows.asleep", subjects=", ".join(asleep))] if asleep else [])
