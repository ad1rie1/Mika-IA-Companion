"""``agency`` : combien elle prend la parole d'elle-même.

- Un plafond quotidien (politique, pas caractère), compté à ce qu'elle a
  **dit** : un silence, une panne, une initiative supplantée ne consomment
  rien (ADR 0033). Une abstention laisse seulement une courte hésitation.
- Une période réfractaire après chaque initiative dite : parler d'elle-même
  rend la suivante bien moins probable sur le moment, et ça s'efface
  (exponentiellement) — sans jamais l'interdire. Sa durée est tirée à l'acte
  (±15 %, enregistrée : le rejeu retombe sur la même) — un métronome se
  reconnaît.
- **Être ignorée l'espace** : chaque initiative restée sans réponse (d'affilée,
  toutes personnes) allonge la période réfractaire (×2,5, jusqu'à six
  heures) ; envers la personne même, chacune abaisse l'envie de recommencer.
  La retenue envers quelqu'un qui ne répond pas (plus d'initiative ordinaire
  tant qu'il n'a pas écrit) est celle de ``social``.
- **Se raviser** : un murmure « sans suite » (elle allait écrire à quelqu'un,
  puis non) arrête l'initiative qu'il précédait.
- La salutation et le rappel promis ne sont pas concernés — saluer
  quelqu'un qui arrive, tenir parole, ce n'est pas « prendre la parole ».
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import affect as affect_c
from mika.contracts import agency as c
from mika.contracts import attention as attention_c
from mika.contracts import email as email_c
from mika.contracts import expression as expression_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import needs as needs_c
from mika.contracts import others as others_c
from mika.contracts import presence as presence_c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.kernel.arbitration import Anyone, Candidate, Modulation, RowView
from mika.kernel.clock import DAY, HOUR, MINUTE, local
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.state import FrozenDict
from mika.vocab import affect as A
from mika.vocab.days import when_fr
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable, is_internal

KEEP = 32
#: au plus tant d'épisodes en cours retenus (corrélation → raisons)
OPENINGS_KEPT = 16
#: les fins d'épisode qui laissent une hésitation (une abstention, une panne) ; une initiative supplantée —
#: la personne a écrit entre-temps — n'en laisse pas : c'est la réponse qui parle
HESITANT = frozenset({"abstained", "failed", "timeout"})
#: au-delà de tant de fois sa durée, la période réfractaire ne pèse plus rien (e^-3 du recul initial)
REFRACTORY_SPAN = 3
#: ce qui la concerne, elle — prendre de ses nouvelles parce qu'on s'inquiète, revenir sur ce qui pèse entre vous,
#: lui rendre ce qu'on a fait de ce qui la concernait, lui dire que le projet qu'elle lui a confié bloque sans elle,
#: lui signaler un mail pour elle : ça n'attend pas que son dernier message ait trouvé sa réponse (mais une
#: initiative restée sans réponse, si). Ce qui vient de Mika (l'envie de parler, son humeur, le manque) attend.
ABOUT_THEM = frozenset({others_c.CHECK_IN, attention_c.THOUGHT, goals_c.SHARE, projects_c.SHARE, projects_c.NEED,
                        email_c.MENTION})
#: prévenir de ce qui ne peut pas attendre — un mail important arrivé pour sa propriétaire — n'est pas relancer
#: quelqu'un : l'annonce passe même après une initiative restée sans réponse (elle est déjà bornée par sa source :
#: une fois par mail, au-dessus d'un seuil d'importance) ; le plafond du jour et le recul s'y appliquent toujours
INFORMS = frozenset({email_c.MENTION})


class AgencyParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    daily_cap: Annotated[int, Knob(
        label="Initiatives par jour", group="Plafond", lo=0, hi=50,
        help="Au-delà, plus aucune initiative ordinaire ce jour-là (heure locale). Ne compte que ce qu'elle a "
             "réellement dit ; saluer quelqu'un qui arrive et dire un rappel promis n'en font pas partie.")] = 5
    refractory_us: Annotated[int, Knob(
        label="Période réfractaire", group="Période réfractaire", lo=0, hi=6 * HOUR,
        help="Après chaque initiative dite, le recul s'efface avec ce temps caractéristique (tiré à ± la gigue, "
             "allongé par les initiatives ignorées) ; jamais une interdiction.")] = 30 * MINUTE
    refractory_shift: Annotated[float, Knob(
        label="Recul juste après une initiative", group="Période réfractaire", lo=-20, hi=0, step=0.5,
        help="Recul (log-odds) juste après une initiative, qui s'efface exponentiellement (divisé par e à chaque "
             "période).")] = -8.0
    jitter: Annotated[float, Knob(
        label="Gigue de la période", group="Période réfractaire", lo=0, hi=0.5, step=0.01,
        help="La durée est tirée à ± cette part à chaque initiative (enregistrée : le rejeu retombe sur la "
             "même) — un métronome se reconnaît.")] = 0.15
    hesitation_us: Annotated[int, Knob(
        label="Hésitation", group="Période réfractaire", lo=0, hi=2 * HOUR,
        help="Après une initiative à laquelle elle a renoncé (un silence, un murmure sans suite) ou qui n'a pas "
             "pu partir (une panne), la suivante est moins probable pendant cette durée ; rien n'est "
             "consommé.")] = 10 * MINUTE
    hesitation_shift: Annotated[float, Knob(
        label="Recul d'une hésitation", group="Période réfractaire", lo=-10, hi=0, step=0.5,
        help="Recul (log-odds) juste après une hésitation, qui s'efface linéairement.")] = -4.0
    renounce_hold_us: Annotated[int, Knob(
        label="Après s'être ravisée", group="Période réfractaire", lo=0, hi=12 * HOUR,
        help="Elle allait écrire à quelqu'un et s'est ravisée (un murmure sans suite) : pas d'initiative "
             "ordinaire vers cette personne pendant cette durée.")] = HOUR
    ignored_backoff: Annotated[float, Knob(
        label="Allongement par initiative ignorée", group="Initiatives ignorées", lo=1, hi=5, step=0.1,
        help="Chaque initiative restée sans réponse d'affilée (toutes personnes) multiplie la période "
             "réfractaire par ce facteur (jusqu'au maximum ci-dessous) : être ignorée l'espace.")] = 2.5
    max_refractory_us: Annotated[int, Knob(
        label="Période réfractaire maximale", group="Initiatives ignorées", lo=10 * MINUTE, hi=2 * DAY,
        help="La période réfractaire, allongée par les initiatives ignorées, ne dépasse jamais cette "
             "durée.")] = 6 * 3600 * 1_000_000
    ignored_shift: Annotated[float, Knob(
        label="Recul par initiative ignorée", group="Initiatives ignorées", lo=-10, hi=0, step=0.5,
        help="Recul (log-odds) par initiative restée sans réponse vers la même personne (trois au plus "
             "comptées), en plus de la période réfractaire.")] = -2.0
    # ne pas harceler : envers une personne qui ne répond pas
    quiet_after_reply_us: Annotated[int, Knob(
        label="Après un message resté sans réponse", group="Ne pas harceler", lo=0, hi=2 * DAY,
        help="Quand son dernier message à quelqu'un (une réponse, une salutation) est resté sans réponse, pas "
             "d'initiative ordinaire vers cette personne pendant cette durée.")] = 4 * HOUR
    quiet_after_question_us: Annotated[int, Knob(
        label="Après une question restée sans réponse", group="Ne pas harceler", lo=0, hi=3 * DAY,
        help="Le même délai quand ce dernier message lui posait une question : on ne repose pas la question, "
             "on attend. Une prise de nouvelles après une inquiétude n'attend pas autant.")] = 12 * HOUR
    follow_up_min_us: Annotated[int, Knob(
        label="Relance douce : au plus tôt après", group="Ne pas harceler", lo=HOUR, hi=14 * DAY,
        help="Après une initiative restée sans réponse, plus rien vers la personne tant qu'elle n'a pas écrit — "
             "sauf une relance douce, vers une amie ou une proche, pas avant ce délai…")] = DAY
    follow_up_rhythms: Annotated[float, Knob(
        label="Relance douce : au moins tant de fois son rythme", group="Ne pas harceler", lo=1, hi=10, step=0.5,
        help="… ni avant ce multiple du rythme habituel de la relation (on n'écrit pas deux fois en deux jours à "
             "quelqu'un qui écrit une fois par semaine). Après deux initiatives sans réponse : plus rien.")] = 2.0


@dataclass(frozen=True, slots=True)
class AgencyState:
    #: Instants des initiatives ordinaires dites (hors salutations et rappels), les plus récentes.
    initiatives: tuple[int, ...] = field(default_factory=tuple)
    #: la durée réfractaire tirée à la dernière initiative (avant l'allongement par les ignorées)
    refractory_us: int = 0
    murmured_at: int = 0
    #: les initiatives et murmures en cours : corrélation → raisons (on compte à l'énoncé, pas au départ)
    openings: FrozenDict[str, str] = field(default_factory=FrozenDict)
    hesitated_at: int = 0
    #: les adresses auxquelles elle allait écrire, puis s'est ravisée (adresse → quand)
    renounced: FrozenDict[str, int] = field(default_factory=FrozenDict)


AGENCY = Faculty("agency", state=AgencyState, init=lambda p: AgencyState(), params=AgencyParams, state_version=2)


def _params(p: AgencyParams | None) -> AgencyParams:
    return p if p is not None else AgencyParams()


def _owed(reasons: Any) -> bool:
    """Saluer qui arrive, dire un rappel promis : ce n'est pas « prendre la
    parole » — ni le plafond ni la période réfractaire ne s'y appliquent."""
    return social_c.GREETING in reasons or goals_c.REMIND in reasons


def murmur_reason(reason: str) -> tuple[str, str]:
    """(sorte de murmure, adresse visée) d'après la raison d'un épisode de murmure."""
    tag, _, target = reason.partition(":")
    return tag, target


@AGENCY.reducer(rt.EPISODE_STARTED)
def _started(s: AgencyState, e, cx) -> AgencyState:
    d = e.data
    if d.kind == Kind.MURMUR:
        s = replace(s, murmured_at=e.at)
    elif d.kind != Kind.INITIATIVE:
        return s
    openings = s.openings.set(e.correlation, d.reason)
    if len(openings) > OPENINGS_KEPT:  # des épisodes jamais réglés : les identifiants sont chronologiques
        openings = FrozenDict(sorted(openings.items())[-OPENINGS_KEPT:])
    return replace(s, openings=openings)


@AGENCY.reducer(rt.UTTERANCE)
def _said(s: AgencyState, e, cx) -> AgencyState:
    """Une initiative dite compte (et ouvre la période réfractaire) ; un murmure
    sans suite la fait se raviser."""
    d = e.data
    if d.kind not in (Kind.INITIATIVE, Kind.MURMUR) or e.correlation not in s.openings:
        return s
    reason = s.openings[e.correlation]
    s = replace(s, openings=s.openings.delete(e.correlation))
    if d.kind == Kind.MURMUR:
        tag, target = murmur_reason(reason)
        if tag == expression_c.MURMUR_ADRIFT and target:
            return replace(s, renounced=s.renounced.set(target, e.at), hesitated_at=e.at)
        return s
    if not d.visible or _owed(reason.split(",")):
        return s
    p = _params(cx.params)
    kept = tuple(t for t in s.initiatives if e.at - t < DAY)
    jittered = round(p.refractory_us * (1.0 + p.jitter * (2.0 * cx.rng.random() - 1.0)))
    return replace(s, initiatives=(*kept, e.at)[-KEEP:], refractory_us=jittered)


@AGENCY.reducer(rt.EPISODE_ENDED)
def _ended(s: AgencyState, e, cx) -> AgencyState:
    """Une initiative ordinaire qui finit sans avoir rien dit : rien de consommé ;
    une abstention ou une panne laisse une courte hésitation."""
    reason = s.openings.get(e.correlation)
    if reason is None:
        return s
    s = replace(s, openings=s.openings.delete(e.correlation))
    if e.data.kind != Kind.INITIATIVE or _owed(reason.split(",")) or e.data.outcome not in HESITANT:
        return s
    return replace(s, hesitated_at=e.at)


def length(s: AgencyState, p: AgencyParams, ignored: int) -> int:
    """La période réfractaire : tirée à l'acte, allongée par les ignorées d'affilée."""
    base = s.refractory_us or p.refractory_us
    return min(p.max_refractory_us, round(base * p.ignored_backoff ** max(0, ignored)))


def reading(s: AgencyState, now: int, p: AgencyParams, tz: Any, ignored: int = 0) -> c.AgencyReading:
    today = local(now, tz).date()
    count = sum(1 for t in s.initiatives if local(t, tz).date() == today)
    last = s.initiatives[-1] if s.initiatives else 0
    until = last + REFRACTORY_SPAN * length(s, p, ignored) if last else 0
    return c.AgencyReading(count, last, until, s.murmured_at, s.hesitated_at)


@AGENCY.fact(c.AGENCY, reads=[attention_c.IGNORED])
def _agency(s: AgencyState, cx) -> c.AgencyReading:
    return reading(s, cx.now, _params(cx.params), cx.tz, cx.facts.get(attention_c.IGNORED))


@AGENCY.fact(c.RENOUNCED)
def _renounced(s: AgencyState, cx, handle: str) -> int:
    return s.renounced.get(handle, 0)


@AGENCY.propose(kinds=[Kind.INITIATIVE], reasons={c.SECOND_THOUGHTS: (0.0, 0.0)},
                reads=[presence_c.PRESENT, c.RENOUNCED])
def _second_thoughts(s: AgencyState, frame: Frame) -> list[Candidate]:
    """Vers chaque adresse présente (là où un murmure peut se dire), sans preuve :
    la garde « elle s'est ravisée » — un murmure sans suite arrête l'initiative
    qu'il précédait (elle est devancée avant de partir)."""
    return [Candidate(Kind.INITIATIVE, handle, c.SECOND_THOUGHTS, 0.0,
                      guards=(Guard("se raviser", reads=(c.RENOUNCED(handle),)),))
            for handle in frame.get(presence_c.PRESENT) if not is_internal(handle)]


@AGENCY.modulate(kinds=[Kind.INITIATIVE], reads=[c.AGENCY, c.RENOUNCED, attention_c.AWAITING, identity_c.PERSON,
                                                 social_c.CLOSENESS, social_c.CONTACT])
def _budget(s: AgencyState, frame: Frame, row: RowView) -> Modulation:
    if _owed(row.reasons):
        return Modulation()
    return restraint(frame, None if row.target in (Anyone.ANY, Anyone.NONE) else row.target, row.reasons)


def follow_up_after(frame: Frame, person: str, p: AgencyParams) -> int:
    """Le délai avant une relance douce : au moins un jour, et au moins deux
    fois le rythme de la relation."""
    rhythm = frame.get(social_c.CONTACT(person)).rhythm_days
    return max(p.follow_up_min_us, round(p.follow_up_rhythms * rhythm * DAY))


def harassing(frame: Frame, target: str, reasons: Any, p: AgencyParams) -> str | None:
    """Ne pas harceler (ADR 0033) : après une initiative restée sans réponse,
    plus d'initiative ordinaire vers la personne tant qu'elle n'a pas écrit —
    sauf une relance douce, après un long délai, vers une amie ou une proche ;
    après deux, plus rien. Si son dernier message (réponse comprise) attend
    encore, quelques heures de retenue — davantage s'il posait une question ;
    ce qui concerne la personne elle-même (``ABOUT_THEM``) n'attend pas la fin
    de cette retenue-là ; ce qui vient de Mika (l'envie de parler, son humeur,
    le manque), si. Rend le veto, ou ``None``."""
    if not is_identifiable(target) or INFORMS & set(reasons):
        return None
    person = frame.get(identity_c.PERSON(target))
    mine = frame.get(attention_c.AWAITING(person))
    if mine.initiatives >= 2:
        return c.UNANSWERED
    if mine.initiatives == 1:
        friendly = frame.get(social_c.CLOSENESS(person)) in (social_c.FRIEND, social_c.CLOSE)
        if friendly and frame.now - mine.last_initiative_at >= follow_up_after(frame, person, p):
            return None  # la relance douce (la consigne le lui dit)
        return c.UNANSWERED
    if mine.unanswered and not ABOUT_THEM & set(reasons):
        quiet = p.quiet_after_question_us if mine.asked and not mine.owed else p.quiet_after_reply_us
        if frame.now - mine.last_out < quiet:
            return c.AWAITING_REPLY
    return None


def restraint(frame: Frame, target: str | None = None, reasons: Any = ()) -> Modulation:
    """Ce que le budget fait à une initiative ordinaire à l'instant : le
    plafond du jour, la retenue envers quelqu'un qui ne répond pas, la période
    réfractaire, une hésitation, et — envers cette personne — les initiatives
    restées sans réponse."""
    p = _params(frame.env.params_of("agency", frame.root))
    r = frame.get(c.AGENCY)
    if r.initiatives_today >= p.daily_cap:
        return Modulation(veto=c.DAILY_CAP)
    if target:
        renounced = frame.get(c.RENOUNCED(target))
        if renounced and frame.now - renounced < p.renounce_hold_us:
            return Modulation(veto=c.CHANGED_MIND)
        veto = harassing(frame, target, reasons, p)
        if veto is not None:
            return Modulation(veto=veto)
    shift = 0.0
    if target and is_identifiable(target):
        mine = frame.get(attention_c.AWAITING(frame.get(identity_c.PERSON(target))))
        shift += p.ignored_shift * min(3, mine.ignored)
    if r.last_initiative_at and r.refractory_until > frame.now:
        tau = max(1, (r.refractory_until - r.last_initiative_at) / REFRACTORY_SPAN)
        shift += p.refractory_shift * math.exp(-(frame.now - r.last_initiative_at) / tau)
    if r.hesitated_at and p.hesitation_us and frame.now - r.hesitated_at < p.hesitation_us:
        shift += p.hesitation_shift * (1.0 - (frame.now - r.hesitated_at) / p.hesitation_us)
    return Modulation(shift=shift) if shift else Modulation()


# ── La consigne d'une initiative ──────────────────────────────────────────


def _name(frame: Frame, person: str) -> str:
    name = frame.get(identity_c.IDENTITY(person)).name
    return f"« {name} »" if name else "cette personne"


def holding_back(frame: Frame, target: str, reasons: Any) -> str | None:
    """Ce qu'elle se dit avant d'écrire à quelqu'un qui ne lui a pas répondu :
    une relance douce, ou ne pas revenir sur ce qui est resté sans réponse."""
    if not is_identifiable(target) or _owed(reasons):
        return None
    person = frame.get(identity_c.PERSON(target))
    mine = frame.get(attention_c.AWAITING(person))
    tz = frame.env.tz_of(frame.root)
    who = _name(frame, person)
    if mine.initiatives:
        when = when_fr(mine.last_initiative_at, frame.now, tz)
        return (f"Tu as déjà écrit à {who} {when}, et pas de réponse depuis. Si tu lui réécris, que ce soit une "
                "relance douce : un mot léger, sans reproche, sans redemander ni te justifier — et rien du tout "
                "si tu n'en as pas vraiment envie.")
    if mine.unanswered:
        when = when_fr(mine.last_out, frame.now, tz)
        asked = " (tu lui posais une question)" if mine.asked else ""
        return (f"Ton dernier message à {who}, {when}, est resté sans réponse{asked}. Ne reviens pas dessus et ne "
                "lui reproche rien : si tu lui écris, pars d'autre chose, simplement.")
    return None


def _overflow(frame: Frame, reasons: Any) -> str | None:
    """Une humeur qui déborde (une raison « pour quiconque est là », dont la
    consigne ne voyage pas avec la ligne) : la dire telle qu'elle est."""
    if affect_c.MOOD_OVERFLOW not in reasons:
        return None
    felt = A.FR.get(frame.get(affect_c.MOOD).felt, "")
    return (f"Ton humeur déborde un peu ({felt}) : tu as envie d'en parler, ou juste de parler." if felt else
            "Ton humeur déborde un peu : tu as envie d'en parler, ou juste de parler.")


def _urge(frame: Frame, target: str | None, reasons: Any) -> str | None:
    """Quand ce sont ses envies qui la poussent : de quoi parler, ou rien."""
    if not {needs_c.NEED_SOCIAL, needs_c.NEED_EXPRESSION} & set(reasons):
        return None
    social = needs_c.NEED_SOCIAL in reasons
    want = "Tu as envie de compagnie, de parler un peu" if social else "Tu as envie de dire quelque chose"
    matter = frame.get(needs_c.MATTER(target)) if target else None
    if matter is not None:
        return (f"{want} : pars de ce dont tu pourrais lui parler (plus haut, sous CE DONT TU POURRAIS PARLER), "
                "simplement — pas d'un quoi-de-neuf dans le vide.")
    return (f"{want}, sans rien de précis en tête. Un mot simple suffit, sans forcer — et si rien de vrai ne "
            "vient, ne dis rien.")


def brief(frame: Frame, req: Any) -> str:
    """Le dernier tour d'une initiative : personne ne lui a écrit, c'est elle
    qui parle — et pourquoi, dit par chaque faculté qui l'y pousse ; quand ce
    sont ses envies, de quoi parler ; et si la personne ne lui a pas répondu,
    la retenue que ça demande."""
    lines: list[str] = []
    ep = frame.episode
    args = ep.attrs.get("args") if ep is not None else None
    reasons = tuple(ep.attrs.get("reasons") or ()) if ep is not None else ()
    target = ep.target if ep is not None else None
    if args:
        for key, value in args.items():
            if str(key).startswith("brief:") and value:
                lines.append(f"- {value}")
    for extra in (_overflow(frame, reasons), _urge(frame, target, reasons)):
        if extra is not None:
            lines.append(f"- {extra}")
    if not lines:
        lines.append("- Rien de précis ne te pousse : écris seulement si quelque chose de vrai te vient.")
    held = holding_back(frame, target, reasons) if target else None
    if held is not None:
        lines.append(f"- {held}")
    why = "\n".join(lines)
    to = f", et tu écris à {_name(frame, frame.get(identity_c.PERSON(target)))}" \
        if target and is_identifiable(target) else ""
    return (f"(Personne ne vient de t'écrire : c'est toi qui prends la parole{to}.)\n"
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
