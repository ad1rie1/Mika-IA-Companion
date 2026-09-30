"""``agency`` : combien elle prend la parole d'elle-même.

- Un plafond quotidien (politique, pas caractère).
- Une période réfractaire après chaque initiative : parler d'elle-même rend
  la suivante moins probable pendant un moment, sans l'interdire. Sa durée
  est tirée à l'acte (±15 %, enregistré : le rejeu retombe sur la même) —
  un métronome se reconnaît.
- **Être ignorée l'espace** : chaque initiative restée sans réponse (d'affilée)
  allonge la période réfractaire (×2,5, jusqu'à six heures) et abaisse
  l'envie de recommencer.
- La salutation et le rappel promis ne sont pas concernés — saluer
  quelqu'un qui arrive, tenir parole, ce n'est pas « prendre la parole ».
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import agency as c
from mika.contracts import attention as attention_c
from mika.contracts import goals as goals_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.kernel.arbitration import Modulation, RowView
from mika.kernel.clock import DAY, HOUR, MINUTE, local
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.vocab.episodes import Kind

KEEP = 32


class AgencyParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    daily_cap: Annotated[int, Knob(
        label="Initiatives par jour", group="Plafond", lo=0, hi=50,
        help="Au-delà, plus aucune initiative ordinaire ce jour-là (heure locale). Saluer quelqu'un qui arrive "
             "et dire un rappel promis n'en font pas partie.")] = 5
    refractory_us: Annotated[int, Knob(
        label="Période réfractaire", group="Période réfractaire", lo=0, hi=6 * HOUR,
        help="Après chaque initiative, la suivante est moins probable pendant cette durée (tirée à ± la gigue, "
             "allongée par les initiatives ignorées) ; jamais interdite.")] = 30 * MINUTE
    refractory_shift: Annotated[float, Knob(
        label="Recul juste après une initiative", group="Période réfractaire", lo=-20, hi=0, step=0.5,
        help="Recul (log-odds) juste après une initiative, qui s'efface linéairement jusqu'à la fin de la "
             "période.")] = -3.0
    jitter: Annotated[float, Knob(
        label="Gigue de la période", group="Période réfractaire", lo=0, hi=0.5, step=0.01,
        help="La durée est tirée à ± cette part à chaque initiative (enregistrée : le rejeu retombe sur la "
             "même) — un métronome se reconnaît.")] = 0.15
    ignored_backoff: Annotated[float, Knob(
        label="Allongement par initiative ignorée", group="Initiatives ignorées", lo=1, hi=5, step=0.1,
        help="Chaque initiative restée sans réponse d'affilée multiplie la période réfractaire par ce facteur "
             "(jusqu'au maximum ci-dessous) : être ignorée l'espace.")] = 2.5
    max_refractory_us: Annotated[int, Knob(
        label="Période réfractaire maximale", group="Initiatives ignorées", lo=10 * MINUTE, hi=2 * DAY,
        help="La période réfractaire, allongée par les initiatives ignorées, ne dépasse jamais cette "
             "durée.")] = 6 * 3600 * 1_000_000
    ignored_shift: Annotated[float, Knob(
        label="Recul par initiative ignorée", group="Initiatives ignorées", lo=-10, hi=0, step=0.5,
        help="Recul (log-odds) par initiative restée sans réponse d'affilée (trois au plus comptées), en plus "
             "de la période réfractaire.")] = -1.0


@dataclass(frozen=True, slots=True)
class AgencyState:
    #: Instants des initiatives dites (hors salutations), les plus récentes.
    initiatives: tuple[int, ...] = field(default_factory=tuple)
    #: la durée réfractaire tirée à la dernière initiative (avant l'allongement par les ignorées)
    refractory_us: int = 0
    murmured_at: int = 0


AGENCY = Faculty("agency", state=AgencyState, init=lambda p: AgencyState(), params=AgencyParams)


def _params(p: AgencyParams | None) -> AgencyParams:
    return p if p is not None else AgencyParams()


@AGENCY.reducer(rt.EPISODE_STARTED)
def _started(s: AgencyState, e, cx) -> AgencyState:
    d = e.data
    if d.kind == Kind.MURMUR:
        return replace(s, murmured_at=e.at)
    if d.kind != Kind.INITIATIVE or _owed(d.reason.split(",")):
        return s
    p = _params(cx.params)
    kept = tuple(t for t in s.initiatives if e.at - t < DAY)
    jittered = round(p.refractory_us * (1.0 + p.jitter * (2.0 * cx.rng.random() - 1.0)))
    return replace(s, initiatives=(*kept, e.at)[-KEEP:], refractory_us=jittered)


def reading(s: AgencyState, now: int, p: AgencyParams, tz: Any, ignored: int = 0) -> c.AgencyReading:
    today = local(now, tz).date()
    count = sum(1 for t in s.initiatives if local(t, tz).date() == today)
    last = s.initiatives[-1] if s.initiatives else 0
    base = s.refractory_us or p.refractory_us
    length = min(p.max_refractory_us, round(base * p.ignored_backoff ** max(0, ignored)))
    return c.AgencyReading(count, last, last + length if last else 0, s.murmured_at)


@AGENCY.fact(c.AGENCY, reads=[attention_c.IGNORED])
def _agency(s: AgencyState, cx) -> c.AgencyReading:
    return reading(s, cx.now, _params(cx.params), cx.tz, cx.facts.get(attention_c.IGNORED))


def _owed(reasons: Any) -> bool:
    """Saluer qui arrive, dire un rappel promis : ce n'est pas « prendre la
    parole » — ni le plafond ni la période réfractaire ne s'y appliquent."""
    return social_c.GREETING in reasons or goals_c.REMIND in reasons


@AGENCY.modulate(kinds=[Kind.INITIATIVE], reads=[c.AGENCY, attention_c.IGNORED])
def _budget(s: AgencyState, frame: Frame, row: RowView) -> Modulation:
    if _owed(row.reasons):
        return Modulation()
    return restraint(frame)


def restraint(frame: Frame) -> Modulation:
    """Ce que le budget fait à une initiative ordinaire à l'instant : le
    plafond du jour, la période réfractaire, les initiatives ignorées."""
    p = _params(frame.env.params_of("agency", frame.root))
    r = frame.get(c.AGENCY)
    if r.initiatives_today >= p.daily_cap:
        return Modulation(veto=c.DAILY_CAP)
    shift = p.ignored_shift * min(3, frame.get(attention_c.IGNORED))
    if r.refractory_until > frame.now:
        span = max(1, r.refractory_until - r.last_initiative_at)
        shift += p.refractory_shift * (r.refractory_until - frame.now) / span
    return Modulation(shift=shift) if shift else Modulation()


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


def task_brief(frame: Frame, req: Any) -> str:
    """Le tour d'une tâche silencieuse (``Kind.TASK``) : personne ne lit ce qu'elle
    écrit ici ; ce qu'elle a à faire est dit par la faculté qui la lui confie."""
    lines: list[str] = []
    ep = frame.episode
    args = ep.attrs.get("args") if ep is not None else None
    if args:
        for key, value in args.items():
            if str(key).startswith("brief:") and value:
                lines.append(f"- {value}")
    what = "\n".join(lines) if lines else "- Fais ce qu'on attend de toi, avec tes outils."
    return ("(Personne ne te parle : c'est une tâche, pour toi seule — personne ne lit ce que tu écris ici.)\n"
            f"Ce que tu as à faire :\n{what}\n"
            "Quand c'est fait, dis-le en une phrase.")


# ── Inspection ────────────────────────────────────────────────────────────

from mika.faculties.agency import inspect as _inspect  # noqa: E402,F401 — contributions : sa vue
