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
from typing import Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import agency as c
from mika.contracts import attention as attention_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.kernel.arbitration import Modulation, RowView
from mika.kernel.clock import DAY, HOUR, MINUTE, local
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Fields, InspectContext, Table
from mika.vocab.episodes import Kind

KEEP = 32


class AgencyParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    daily_cap: int = 5
    refractory_us: int = 30 * MINUTE
    refractory_shift: float = -3.0
    jitter: float = 0.15
    ignored_backoff: float = 2.5
    max_refractory_us: int = 6 * 3600 * 1_000_000
    ignored_shift: float = -1.0


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


# ── Inspection ────────────────────────────────────────────────────────────

#: ses dernières prises de parole d'elle-même, relues dans le fil
SPOKEN_SHOWN = 20


def _who(frame: Frame, key: str) -> str:
    if not key:
        return "quiconque était là"
    name = frame.get(identity_c.IDENTITY(key)).name
    return f"« {name} » ({key})" if name else key


def _restraint_fr(frame: Frame) -> str:
    m = restraint(frame)
    if m.veto == c.DAILY_CAP:
        return "retenues : le plafond du jour est atteint"
    if m.veto is not None:
        return f"retenues : {m.veto}"
    return f"plus rares (décalage {m.shift:+.1f})" if m.shift else "libres"


def _spoken(frame: Frame, ctx: InspectContext) -> tuple[tuple[str, str, str, str], ...]:
    """Ce qu'elle a dit d'elle-même (salutations et rappels compris), et si la
    personne lui a écrit depuis."""
    if ctx.store is None:
        return ()
    t = transcript_c.THREAD_TABLE
    rows = ctx.store.query_mind(
        f"SELECT m.at, m.person, m.text, (SELECT MIN(u.at) FROM {t} u WHERE u.role='user' AND u.person=m.person "
        f"AND u.id>m.id) FROM {t} m WHERE m.role='assistant' AND m.kind=? ORDER BY m.id DESC LIMIT ?",
        (str(Kind.INITIATIVE), SPOKEN_SHOWN))
    out = []
    for at, person, text, answered_at in rows:
        person = str(person or "")
        answered = "—" if not person else f"oui, {ctx.when(int(answered_at))}" if answered_at else "pas encore"
        excerpt = str(text or "")
        out.append((ctx.when(int(at)), _who(frame, person),
                    excerpt if len(excerpt) <= 160 else excerpt[:159] + "…", answered))
    return tuple(out)


@AGENCY.inspect("initiatives", title="Initiatives")
def _inspect(s: AgencyState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _params(frame.env.params_of("agency", frame.root))
    r = frame.get(c.AGENCY)
    ignored = frame.get(attention_c.IGNORED)
    now = frame.now
    if r.refractory_until > now:
        refractory = f"jusqu'à {ctx.when(r.refractory_until)}"
    else:
        refractory = f"terminée depuis {ctx.when(r.refractory_until)}" if r.refractory_until else "—"
    stretch = min(p.max_refractory_us, (s.refractory_us or p.refractory_us) * p.ignored_backoff ** max(0, ignored))
    counted = tuple((ctx.when(t), "oui" if local(t, frame.env.tz_of(frame.root)).date() == frame.local().date()
                     else "non") for t in reversed(s.initiatives))
    return [
        Fields((
            ("aujourd'hui", f"{r.initiatives_today} / {p.daily_cap}"
             + (" — plafond atteint" if r.initiatives_today >= p.daily_cap else "")),
            ("dernière initiative comptée", ctx.when(r.last_initiative_at) if r.last_initiative_at else "—"),
            ("période réfractaire", refractory),
            ("durée tirée à la dernière", f"{(s.refractory_us or p.refractory_us) / MINUTE:.0f} min"),
            ("ignorées d'affilée", f"{ignored} (période allongée à {stretch / MINUTE:.0f} min, "
                                   f"au plus {p.max_refractory_us / HOUR:.0f} h)" if ignored else "0"),
            ("initiatives ordinaires", _restraint_fr(frame)),
            ("saluer, dire un rappel promis", "hors budget"),
            ("dernier murmure", ctx.when(r.murmured_at) if r.murmured_at else "—"),
        ), title="Son budget"),
        Table(("quand", "aujourd'hui"), counted, title="Initiatives comptées (dernières 24 h)",
              empty="aucune initiative comptée"),
        Table(("quand", "à qui", "ce qu'elle a dit", "on lui a répondu"), _spoken(frame, ctx),
              title="Ce qu'elle a dit d'elle-même", empty="elle n'a encore rien dit d'elle-même"),
    ]
