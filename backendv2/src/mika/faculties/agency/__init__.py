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
  Envers quelqu'un qui ne répond pas : plus d'initiative ordinaire tant qu'il
  n'a pas écrit (une relance douce, puis rien) ; des mois plus tard, une
  prise de nouvelles, une seule (``ONCE_MORE``, ADR 0058).
- **Se raviser** : un murmure « sans suite » (elle allait écrire à quelqu'un,
  puis non) arrête l'initiative qu'il précédait.
- La salutation et le rappel promis ne sont pas concernés — saluer
  quelqu'un qui arrive, tenir parole, ce n'est pas « prendre la parole » ;
  prévenir (un mail important, un projet confié qui bloque) n'est pas
  relancer, et être ignorée n'y change rien : seule la période réfractaire de
  base et le plafond du jour s'y appliquent. Ce qui est dû, ce qui prévient et
  ce qui salue est déclaré une fois, dans le contrat (``agency.OWED``,
  ``INFORMS``, ``GREETS``).
- **La consigne dit une raison** : la plus forte (d'après les preuves de la
  ligne choisie), et au plus une seconde, « et aussi » — on écrit pour une
  raison, pas pour toutes (HUM-10).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import affect as affect_c
from mika.contracts import agency as c
from mika.contracts import attention as attention_c
from mika.contracts import expression as expression_c
from mika.contracts import identity as identity_c
from mika.contracts import needs as needs_c
from mika.contracts import others as others_c
from mika.contracts import presence as presence_c
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
from mika.vocab.phrasebook import phrase

KEEP = 32
#: au plus tant d'épisodes en cours retenus (corrélation → raisons)
OPENINGS_KEPT = 16
#: les fins d'épisode qui laissent une hésitation (une abstention, une panne) ; une initiative supplantée —
#: la personne a écrit entre-temps — n'en laisse pas : c'est la réponse qui parle
HESITANT = frozenset({"abstained", "failed", "timeout"})
#: au-delà de tant de fois sa durée, la période réfractaire ne pèse plus rien (e^-3 du recul initial)
REFRACTORY_SPAN = 3
#: ce qui la concerne, elle — prendre de ses nouvelles parce qu'on s'inquiète, lui demander comment s'est passé ce
#: qu'elle avait de prévu, revenir sur ce qui pèse entre vous, lui rendre ce qu'on a fait de ce qui la concernait —
#: et tout ce qui la prévient (``c.INFORMS``) : ça n'attend pas que son dernier message ait trouvé sa réponse (mais
#: une initiative restée sans réponse, si — sauf pour prévenir). Ce qui vient de Mika (l'envie de parler, son
#: humeur, le manque) attend. Déclaré dans le contrat (``c.FOR_THEM``) : ``social`` le lit aussi.
ABOUT_THEM = c.INFORMS | c.FOR_THEM
#: ce qui ne relance pas même quelqu'un qui ne répond plus : lui souhaiter son anniversaire le jour même (un vœu
#: n'attend pas de réponse, et ne pas le faire se remarque plus que de le faire)
NOT_A_NUDGE = frozenset({others_c.CELEBRATE})


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
    hesitation_max_us: Annotated[int, Knob(
        label="Hésitation la plus longue", group="Période réfractaire", lo=0, hi=24 * HOUR,
        help="Envers la même personne, chaque hésitation d'affilée (un silence, une panne) dure le double de la "
             "précédente, jusqu'à cette durée ; elle repart de zéro quand elle a fini par lui écrire.")] = 6 * HOUR
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
    farewell_quiet_us: Annotated[int, Knob(
        label="Après un au revoir", group="Ne pas harceler", lo=0, hi=DAY,
        help="Quand la personne a clos la conversation (« bonne nuit », « je file »), pas d'initiative ordinaire vers "
             "elle pendant cette durée, même si elle reste connectée — « t'es encore là ? » dix minutes après un au "
             "revoir ne se fait pas. Ce qui est dû ou prévient passe.")] = 4 * HOUR
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
    #: envers qui elle a hésité d'affilée (une abstention, une panne) : adresse → (quand, combien de fois)
    hesitations: FrozenDict[str, tuple[int, int]] = field(default_factory=FrozenDict)


AGENCY = Faculty("agency", state=AgencyState, init=lambda p: AgencyState(), params=AgencyParams, state_version=3)
#: les adresses dont on garde les hésitations, au plus
HESITATIONS_KEPT = 64


def _params(p: AgencyParams | None) -> AgencyParams:
    return p if p is not None else AgencyParams()


def _uncounted(reasons: Any) -> bool:
    """Saluer qui arrive, dire un rappel promis : ce n'est pas « prendre la
    parole » — ni le plafond ni la période réfractaire ne s'y appliquent
    (``c.NOT_SPEAKING_UP``)."""
    return bool(c.NOT_SPEAKING_UP & set(reasons))


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
    if not d.visible or _uncounted(reason.split(",")):
        return s
    if d.target and d.target in s.hesitations:
        s = replace(s, hesitations=s.hesitations.delete(d.target))  # elle a fini par lui écrire : tout repart
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
    if e.data.kind != Kind.INITIATIVE or _uncounted(reason.split(",")) or e.data.outcome not in HESITANT:
        return s
    target = e.data.target
    if not target:
        return replace(s, hesitated_at=e.at)
    # d'affilée envers la même personne, chaque hésitation dure le double de la précédente : une envie de lui écrire
    # qui finit toujours en silence (ou en panne) ne se remet pas en route toutes les dix minutes (audit L2 du
    # 2026-10-03 : quatre cents essais par jour vers une amie, tous en abstention)
    _at, n = s.hesitations.get(target, (0, 0))
    hesitations = s.hesitations.set(target, (e.at, n + 1))
    if len(hesitations) > HESITATIONS_KEPT:
        hesitations = FrozenDict(sorted(hesitations.items(), key=lambda kv: kv[1][0])[-HESITATIONS_KEPT:])
    return replace(s, hesitated_at=e.at, hesitations=hesitations)


def length(s: AgencyState, p: AgencyParams, ignored: int) -> int:
    """La période réfractaire : tirée à l'acte, allongée par les ignorées d'affilée."""
    base = s.refractory_us or p.refractory_us
    return min(p.max_refractory_us, round(base * p.ignored_backoff ** max(0, ignored)))


def reading(s: AgencyState, now: int, p: AgencyParams, tz: Any, ignored: int = 0) -> c.AgencyReading:
    today = local(now, tz).date()
    count = sum(1 for t in s.initiatives if local(t, tz).date() == today)
    last = s.initiatives[-1] if s.initiatives else 0
    until = last + REFRACTORY_SPAN * length(s, p, ignored) if last else 0
    base = last + REFRACTORY_SPAN * length(s, p, 0) if last else 0
    return c.AgencyReading(count, last, until, s.murmured_at, s.hesitated_at, base)


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
    if _uncounted(row.reasons):
        return Modulation()
    return restraint(frame, None if row.target in (Anyone.ANY, Anyone.NONE) else row.target, row.reasons)


@AGENCY.modulate(kinds=[Kind.INITIATIVE], reads=[presence_c.COMPOSING])
def _composing(s: AgencyState, frame: Frame, row: RowView) -> Modulation:
    """Elle ne prend pas d'elle-même la parole vers quelqu'un qui est en train de lui écrire : elle attend son
    message, et y répondra. Saluer, tenir parole, prévenir attendent aussi — la saisie est bornée
    (``presence.COMPOSING_MAX_US``), ce n'est qu'un instant."""
    if row.target in (Anyone.ANY, Anyone.NONE) or frame.get(presence_c.COMPOSING(row.target)) is None:
        return Modulation()
    return Modulation(veto=c.COMPOSING)


def follow_up_after(frame: Frame, person: str, p: AgencyParams) -> int:
    """Le délai avant une relance douce : au moins un jour, et au moins deux
    fois le rythme de la relation."""
    rhythm = frame.get(social_c.CONTACT(person)).rhythm_days
    return max(p.follow_up_min_us, round(p.follow_up_rhythms * rhythm * DAY))


def harassing(frame: Frame, target: str, reasons: Any, p: AgencyParams) -> str | None:
    """Ne pas harceler (ADR 0033) : après une initiative restée sans réponse,
    plus d'initiative ordinaire vers la personne tant qu'elle n'a pas écrit —
    sauf une relance douce, après un long délai (compté depuis la lecture quand
    son application la dit ; jamais avant qu'elle l'ait lue), vers une amie ou une proche ;
    après deux, plus rien — sinon, des mois plus tard, prendre de ses nouvelles
    une seule fois (``ONCE_MORE``, ADR 0058). Si son dernier message (réponse comprise) attend
    encore, quelques heures de retenue — davantage s'il posait une question ;
    ce qui concerne la personne elle-même (``ABOUT_THEM``) n'attend pas la fin
    de cette retenue-là ; ce qui vient de Mika (l'envie de parler, son humeur,
    le manque), si. Rend le veto, ou ``None``."""
    if not is_identifiable(target) or (c.INFORMS | NOT_A_NUDGE) & set(reasons):
        return None  # prévenir n'est pas relancer ; souhaiter un anniversaire non plus
    person = frame.get(identity_c.PERSON(target))
    mine = frame.get(attention_c.AWAITING(person))
    if c.ONCE_MORE & set(reasons):
        # des mois plus tard, une prise de nouvelles, une seule : dite, elle compte une initiative de plus (ADR 0058)
        return None if mine.initiatives <= c.GIVE_UP_AFTER else c.UNANSWERED
    if mine.initiatives >= c.GIVE_UP_AFTER:
        return c.UNANSWERED
    if mine.initiatives == 1:
        if mine.unseen:
            return c.UNANSWERED  # elle ne l'a pas encore lu (son application le dit) : on ne relance pas
        friendly = frame.get(social_c.CLOSENESS(person)) in (social_c.FRIEND, social_c.CLOSE)
        # le délai d'une relance se compte depuis la lecture, quand on la sait
        if friendly and frame.now - max(mine.last_initiative_at, mine.seen_at) >= follow_up_after(frame, person, p):
            return None  # la relance douce (la consigne le lui dit)
        return c.UNANSWERED
    if mine.closed_at and frame.now - mine.closed_at < p.farewell_quiet_us:
        return c.FAREWELL  # on s'est quittées : pas de « t'es encore là ? »
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
    # prévenir de ce qui ne peut pas attendre : être ignorée n'y change rien (ni l'allongement, ni l'envie moindre,
    # ni s'être ravisée de lui écrire pour autre chose) — le plafond et la période de base, si (ADR 0044, 0047)
    informs = bool(c.INFORMS & set(reasons))
    if target:
        renounced = frame.get(c.RENOUNCED(target))
        if renounced and frame.now - renounced < p.renounce_hold_us and not informs:
            return Modulation(veto=c.CHANGED_MIND)
        veto = harassing(frame, target, reasons, p)
        if veto is not None:
            return Modulation(veto=veto)
    shift = 0.0
    if target and is_identifiable(target) and not informs and not c.ONCE_MORE & set(reasons):
        mine = frame.get(attention_c.AWAITING(frame.get(identity_c.PERSON(target))))
        shift += p.ignored_shift * min(3, mine.ignored)
    until = (r.base_until or r.refractory_until) if informs else r.refractory_until
    if r.last_initiative_at and until > frame.now:
        tau = max(1, (until - r.last_initiative_at) / REFRACTORY_SPAN)
        shift += p.refractory_shift * math.exp(-(frame.now - r.last_initiative_at) / tau)
    if r.hesitated_at and p.hesitation_us and frame.now - r.hesitated_at < p.hesitation_us:
        shift += p.hesitation_shift * (1.0 - (frame.now - r.hesitated_at) / p.hesitation_us)
    if target and not informs:
        at, n = frame.state("agency").hesitations.get(target, (0, 0))
        span = hesitation_span(n, p)
        if n >= 2 and frame.now - at < span:
            # la première hésitation, c'est la courte d'au-dessus ; à partir de la deuxième, envers elle, ça dure
            return Modulation(veto=c.HESITATING)
    return Modulation(shift=shift) if shift else Modulation()


def hesitation_span(n: int, p: AgencyParams) -> int:
    """Combien de temps elle laisse passer après sa n-ième hésitation d'affilée envers quelqu'un : la courte
    hésitation, doublée à chaque fois, bornée."""
    if n <= 0 or not p.hesitation_us:
        return 0
    return min(p.hesitation_max_us, p.hesitation_us * 2 ** min(n - 1, 20))


# ── La consigne d'une initiative ──────────────────────────────────────────


def _name(frame: Frame, person: str) -> str:
    name = frame.get(identity_c.IDENTITY(person)).name
    return f"« {name} »" if name else phrase("expression.person.unnamed")


def holding_back(frame: Frame, target: str, reasons: Any) -> str | None:
    """Ce qu'elle se dit avant d'écrire à quelqu'un qui ne lui a pas répondu :
    une relance douce, ou ne pas revenir sur ce qui est resté sans réponse."""
    if not is_identifiable(target) or _uncounted(reasons):
        return None
    person = frame.get(identity_c.PERSON(target))
    mine = frame.get(attention_c.AWAITING(person))
    tz = frame.env.tz_of(frame.root)
    who = _name(frame, person)
    if mine.initiatives:
        return phrase("agency.brief.nudge", who=who, when=when_fr(mine.last_initiative_at, frame.now, tz))
    if mine.unanswered:
        when = when_fr(mine.last_out, frame.now, tz)
        if mine.asked:
            return phrase("agency.brief.unanswered_question", who=who, when=when)
        return phrase("agency.brief.unanswered", who=who, when=when)
    return None


def _overflow(frame: Frame, reasons: Any) -> str | None:
    """Une humeur qui déborde (une raison « pour quiconque est là », dont la
    consigne ne voyage pas avec la ligne) : la dire telle qu'elle est."""
    if affect_c.MOOD_OVERFLOW not in reasons:
        return None
    felt = A.FR.get(frame.get(affect_c.MOOD).felt, "")
    return phrase("affect.overflow.brief", feeling=felt) if felt else phrase("affect.overflow.brief_unnamed")


def _urge(frame: Frame, target: str | None, reasons: Any) -> str | None:
    """Quand ce sont ses envies qui la poussent : de quoi parler, ou rien."""
    if not {needs_c.NEED_SOCIAL, needs_c.NEED_EXPRESSION} & set(reasons):
        return None
    social = needs_c.NEED_SOCIAL in reasons
    want = phrase("agency.brief.want_company") if social else phrase("agency.brief.want_to_say")
    matter = frame.get(needs_c.MATTER(target)) if target else None
    if matter is not None:
        # la section où elle la trouve, sous son titre (``needs``)
        return phrase("agency.brief.from_matter", want=want, section=phrase("needs.matter.title"))
    return phrase("agency.brief.no_matter", want=want)


#: une seconde raison ne se dit (« et aussi ») que si elle pèse au moins cette part de la plus forte
SECOND_REASON_SHARE = 0.5


def _weights(req: Any) -> tuple[dict[str, float], set[str]]:
    """Ce que pèse chaque faculté dans la ligne choisie (la somme de ses preuves), et celles qui y portent ce qui
    est dû ou ce qui prévient (``OWED``, ``INFORMS``) : ce qu'on ne tait jamais au profit d'une autre raison."""
    selected = getattr(req, "selected", None)
    out: dict[str, float] = {}
    firm: set[str] = set()
    for source, reason, evidence in getattr(selected, "parts", ()) or ():
        out[source] = out.get(source, 0.0) + float(evidence)
        if reason in c.OWED | c.INFORMS:
            firm.add(source)
    return out, firm


def motives(frame: Frame, req: Any) -> list[str]:
    """Ce qui la pousse à écrire, la raison la plus forte d'abord, et au plus une seconde : on écrit pour une
    raison, pas pour toutes — trois consignes côte à côte donnent un message qui veut tout faire (« coucou, ça va
    pas fort, j'ai rêvassé sur le café, bref »), ou qui récite ses motifs (HUM-10). La force d'une raison, c'est
    ce que sa faculté a apporté de preuves à la ligne choisie."""
    ep = frame.episode
    args = ep.attrs.get("args") if ep is not None else None
    reasons = tuple(ep.attrs.get("reasons") or ()) if ep is not None else ()
    target = ep.target if ep is not None else None
    weights, firm = _weights(req)
    # (tenir parole ou prévenir, poids, ordre, consigne)
    found: list[tuple[bool, float, int, str]] = []
    if args:
        for i, (key, value) in enumerate(args.items()):
            owner = str(key)[len("brief:"):]
            if str(key).startswith("brief:") and value:
                found.append((owner in firm, weights.get(owner, 0.0), i, str(value)))
    extras = ((_overflow(frame, reasons), affect_c.OWNER), (_urge(frame, target, reasons), needs_c.OWNER))
    for i, (extra, owner) in enumerate(extras, start=len(found)):
        if extra is not None:
            found.append((False, weights.get(owner, 0.0), i, extra))
    found.sort(key=lambda f: (not f[0], -f[1], f[2]))
    if not found:
        return []
    if not weights:  # une initiative que l'arbitre n'a pas choisie (aucune preuve à comparer) : tout se dit
        return [text for _f, _w, _i, text in found]
    # ce qui est dû ou prévient se dit toujours ; sinon, la plus forte, et une seconde si elle pèse assez
    kept = [f for f in found if f[0]] or [found[0]]
    rest = [f for f in found if f not in kept]
    if len(kept) == 1 and rest and rest[0][1] >= SECOND_REASON_SHARE * max(kept[0][1], 1e-9):
        kept.append(rest[0])
    return [text if n == 0 else phrase("agency.brief.also", motive=_continued(text))
            for n, (_f, _w, _i, text) in enumerate(kept)]


#: les premiers mots qui se mettent en minuscule à la suite d'« Et aussi : » (jamais un nom)
_LOWERED = frozenset({"tu", "ton", "ta", "tes", "ce", "cette", "ça", "il", "elle", "un", "une", "le", "la", "les",
                      "quelque", "quelqu'un", "personne"})


def _continued(text: str) -> str:
    head = text.split(" ", 1)[0]
    return text[:1].lower() + text[1:] if head.lower() in _LOWERED else text


def brief(frame: Frame, req: Any) -> str:
    """Le dernier tour d'une initiative : personne ne lui a écrit, c'est elle
    qui parle — et pourquoi : la raison la plus forte, au plus une seconde ;
    quand ce sont ses envies, de quoi parler ; et si la personne ne lui a pas
    répondu, la retenue que ça demande."""
    ep = frame.episode
    reasons = tuple(ep.attrs.get("reasons") or ()) if ep is not None else ()
    target = ep.target if ep is not None else None
    lines = [f"- {m}" for m in motives(frame, req)]
    if not lines:
        lines.append(f"- {phrase('agency.brief.nothing')}")
    held = holding_back(frame, target, reasons) if target else None
    if held is not None:
        lines.append(f"- {held}")
    why = "\n".join(lines)
    opening = phrase("agency.brief.opening_to", who=_name(frame, frame.get(identity_c.PERSON(target)))) \
        if target and is_identifiable(target) else phrase("agency.brief.opening")
    return f"{opening}\n{phrase('agency.brief.pushing')}\n{why}\n{phrase('agency.brief.silence')}"


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
    what = "\n".join(lines) if lines else f"- {phrase('agency.task.anything')}"
    return f"{phrase('agency.task.opening')}\n{phrase('agency.task.todo')}\n{what}\n{phrase('agency.task.done')}"


# ── Inspection ────────────────────────────────────────────────────────────

from mika.faculties.agency import inspect as _inspect  # noqa: E402,F401 — contributions : sa vue
