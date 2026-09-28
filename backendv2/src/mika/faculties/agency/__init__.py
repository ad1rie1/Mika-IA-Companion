"""``agency`` : combien elle prend la parole d'elle-même.

Un plafond quotidien (politique, pas caractère) et une période réfractaire
après chaque initiative : parler d'elle-même rend la suivante moins probable
pendant un moment, sans l'interdire. La salutation n'est pas concernée —
saluer quelqu'un qui arrive n'est pas « prendre la parole ».
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import agency as c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.kernel.arbitration import Modulation, RowView
from mika.kernel.clock import DAY, MINUTE, local
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Frame
from mika.vocab.episodes import Kind

KEEP = 32


class AgencyParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    daily_cap: int = 5
    refractory_us: int = 30 * MINUTE
    refractory_shift: float = -3.0


@dataclass(frozen=True, slots=True)
class AgencyState:
    #: Instants des initiatives dites (hors salutations), les plus récentes.
    initiatives: tuple[int, ...] = field(default_factory=tuple)


AGENCY = Faculty("agency", state=AgencyState, init=lambda p: AgencyState(), params=AgencyParams)


def _params(p: AgencyParams | None) -> AgencyParams:
    return p if p is not None else AgencyParams()


@AGENCY.reducer(rt.EPISODE_STARTED)
def _started(s: AgencyState, e, cx) -> AgencyState:
    d = e.data
    if d.kind != Kind.INITIATIVE or social_c.GREETING in d.reason.split(","):
        return s
    kept = tuple(t for t in s.initiatives if e.at - t < DAY)
    return replace(s, initiatives=(*kept, e.at)[-KEEP:])


def reading(s: AgencyState, now: int, p: AgencyParams, tz: Any) -> c.AgencyReading:
    today = local(now, tz).date()
    count = sum(1 for t in s.initiatives if local(t, tz).date() == today)
    last = s.initiatives[-1] if s.initiatives else 0
    return c.AgencyReading(count, last, last + p.refractory_us if last else 0)


@AGENCY.fact(c.AGENCY)
def _agency(s: AgencyState, cx) -> c.AgencyReading:
    return reading(s, cx.now, _params(cx.params), cx.tz)


@AGENCY.modulate(kinds=[Kind.INITIATIVE], reads=[c.AGENCY])
def _budget(s: AgencyState, frame: Frame, row: RowView) -> Modulation:
    if social_c.GREETING in row.reasons:
        return Modulation()
    p = _params(frame.env.params_of("agency", frame.root))
    r = frame.get(c.AGENCY)
    if r.initiatives_today >= p.daily_cap:
        return Modulation(veto=c.DAILY_CAP)
    if r.refractory_until > frame.now:
        remaining = (r.refractory_until - frame.now) / p.refractory_us
        return Modulation(shift=p.refractory_shift * remaining)
    return Modulation()


def brief(frame: Frame, req: Any) -> str:
    """Le dernier tour d'une initiative : personne ne lui a écrit, c'est elle
    qui parle — et pourquoi, dit par chaque faculté qui l'y pousse."""
    lines: list[str] = []
    ep = frame.episode
    args = ep.attrs.get("args") if ep is not None else None
    if args:
        for key, value in args.items():
            if str(key).startswith("brief:") and value:
                lines.append(f"- {value}")
    why = "\n".join(lines) if lines else "- Tu as simplement envie de dire quelque chose."
    return ("(Personne ne vient de t'écrire : c'est toi qui prends la parole.)\n"
            f"Ce qui te pousse à parler :\n{why}\n"
            "Si finalement tu n'as rien à dire, réponds exactement [SILENCE].")
