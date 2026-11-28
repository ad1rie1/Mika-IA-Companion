"""Les initiatives d'``others`` : écrire à quelqu'un d'elle-même, selon ce que l'expérience lui a appris.

- **À l'heure où la personne répond** (``_receptive``) : ses initiatives vers elle se décalent vers les moments de la
  journée où ses messages trouvent une réponse (``faculty.receptivity``), jamais une salutation ni un rappel promis.
- **Cinq propositions**, qui partagent leur cadre (où lui écrire, ses heures, comment le brief la nomme, la candidate
  elle-même) : prendre de ses nouvelles quand elle n'avait pas l'air bien (``check_in``) ; l'encourager la veille de
  ce qu'elle avait de prévu (``cheer``) ; demander comment ça s'est passé (``follow_up``) ; le lui souhaiter, le jour
  de ce qui se fête (``celebrate``) ; penser à elle le jour d'une date lourde (``remembrance``).

Ce qu'elle a appris de chacun (son ton, ses heures, ses inquiétudes, ce dont elle a déjà parlé) est dans
``faculty.py`` ; ce module n'en écrit rien, il le lit.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any

from mika.contracts import agency as agency_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import others as c
from mika.contracts import presence as presence_c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.others.faculty import (
    MOMENT_SUBJECT,
    OTHERS,
    OthersParams,
    OthersState,
    band_of,
    heard,
    params,
    receptivity,
)
from mika.kernel.arbitration import Candidate, Modulation, RowView
from mika.kernel.clock import DAY, HOUR, instant, within_daily_window
from mika.kernel.frame import Frame
from mika.kernel.guards import floor
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import phrase


@OTHERS.modulate(kinds=[Kind.INITIATIVE], reads=[identity_c.PERSON])
def _receptive(s: OthersState, frame: Frame, row: RowView) -> Modulation:
    """Écrire à quelqu'un à une heure où il répond d'habitude, plutôt qu'à une
    heure où ses messages restent sans réponse. Ni une salutation (quelqu'un
    arrive), ni un rappel promis n'en dépendent (``agency.NOT_SPEAKING_UP``)."""
    if row.target in ("any", "none") or not is_identifiable(row.target):
        return Modulation()
    if agency_c.NOT_SPEAKING_UP & set(row.reasons):
        return Modulation()
    p = params(frame.env.params_of("others", frame.root))
    person = frame.get(identity_c.PERSON(row.target))
    shift = receptivity(s, person, band_of(frame.local().hour), p)[3]
    return Modulation(shift=shift) if shift else Modulation()


# Les cinq propositions qui suivent (prendre de ses nouvelles, l'encourager, demander comment ça s'est passé, le lui
# souhaiter, penser à elle le jour d'une date lourde) partagent leur cadre : où lui écrire
# (``identity.reach_now`` : une adresse présente d'abord, sinon une conversation privée où l'on peut lui écrire
# d'elle-même), ses heures, comment le brief la nomme, et la candidate elle-même. Chacune ne garde que sa sélection,
# son brief et sa preuve.


def _in_checkin_hours(frame: Frame, p: OthersParams) -> bool:
    """Dans ses heures pour prendre des nouvelles (de ``checkin_day_start_min`` à ``checkin_day_end_min``, heure
    locale). L'encouragement de la veille a sa propre fenêtre (``_cheer_window``)."""
    local = frame.local()
    return within_daily_window(local.hour * 60 + local.minute, p.checkin_day_start_min, p.checkin_day_end_min)


def _who(frame: Frame, person: str, address: str) -> str:
    """Comment le brief la nomme : son nom entre guillemets (celui de la personne, sinon celui de l'adresse où elle
    lui écrit), sinon le repli de sa voix (``others.initiative.someone``)."""
    name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(address)).name
    return f"« {name} »" if name else phrase("others.initiative.someone")


def capitalized(text: str) -> str:
    """En tête de phrase : la première lettre en majuscule, le reste tel quel (un nom entre guillemets ne change pas ;
    seul le repli de la voix en prend une)."""
    return text[:1].upper() + text[1:]


def _moment_candidate(reason: str, address: str, evidence: float, brief: str, frame: Frame, person: str,
                      ev: memory_c.LifeEvent | None = None) -> Candidate:
    """L'initiative vers elle : à cette adresse, la parole avec elle pour ressource, devancée si elle écrit
    entre-temps sur n'importe laquelle de ses adresses (``identity.heard_since_guard`` : on lui répond, on ne la
    relance pas), et le moment dont elle parle pour sujet quand il y en a un (la prise de nouvelles n'en a pas)."""
    args = {"brief:others": brief}
    if ev is not None:
        args["subject"] = f"{MOMENT_SUBJECT}{ev.key}"
    return Candidate(Kind.INITIATIVE, address, reason, round(evidence, 3), resources=frozenset({floor(address)}),
                     guards=(identity_c.heard_since_guard(frame, person),), args=FrozenDict(args))


@OTHERS.propose(kinds=[Kind.INITIATIVE], reasons={c.CHECK_IN: (0.0, 12.0)},
                reads=[identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY, presence_c.PRESENT,
                       social_c.CLOSENESS, transcript_c.LAST_FROM])
def _check_in(s: OthersState, frame: Frame) -> list[Candidate]:
    """Quelqu'un qui n'avait pas l'air bien, et plus rien depuis : quelques
    heures plus tard, elle prend de ses nouvelles — au cran de leur lien
    (``concern_by_closeness``, ADR 0150 : une amie, entière ; une connaissance,
    rarement)."""
    if not s.concerns:
        return []
    p = params(frame.env.params_of("others", frame.root))
    if not _in_checkin_hours(frame, p):
        return []
    out: list[Candidate] = []
    for person, (_message, at, opens) in sorted(s.concerns.items()):
        if frame.now < opens or frame.now - at > p.checkin_until_us:
            continue
        share = p.concern_by_closeness.get(frame.get(social_c.CLOSENESS(person)), 0.0)
        if share <= 0:
            continue
        address = identity_c.reach_now(frame, person)
        if address is None:
            continue
        brief = phrase("others.initiative.check_in", who=capitalized(_who(frame, person, address)))
        ramp = min(1.0, (frame.now - opens) / p.checkin_ramp_us)
        evidence = (p.checkin_evidence_start + (p.checkin_evidence - p.checkin_evidence_start) * ramp) * share
        out.append(_moment_candidate(c.CHECK_IN, address, evidence, brief, frame, person))
    return out


def _at(day: date, minutes: int, tz: Any) -> int:
    return instant(datetime.combine(day, time(minutes // 60 % 24, minutes % 60), tzinfo=tz))


#: une conversation depuis midi, la veille, était l'occasion de l'encourager
CHEER_QUIET_FROM_MIN = 12 * 60


def _cheer_window(ev: memory_c.LifeEvent, frame: Frame, p: OthersParams) -> tuple[int, int] | None:
    """Quand lui souhaiter bonne chance : (début, depuis quand une conversation en tenait lieu). La veille au
    soir ; ou le matin même, pour un moment à une heure dite l'après-midi (jusqu'à deux heures avant). Si elles
    se sont parlé depuis midi la veille, la conversation en était l'occasion. ``None`` : pas pour un moment déjà
    là, ni pour une situation, ni pour ce qui se fête (un anniversaire ne se souhaite pas « bonne chance » : il se
    souhaite le jour même), ni pour une date qui revient chaque année (pas de « bonne chance » pour la date d'un
    deuil)."""
    if ev.ongoing or ev.festive or ev.yearly or ev.vague or ev.when <= frame.now or ev.outcome:
        return None  # une période (« en novembre ») n'a pas de veille (ADR 0084) ; ni ce qui n'aura pas lieu
    tz = frame.env.tz_of(frame.root)
    day = frame.local(ev.when).date()
    eve = date.fromordinal(day.toordinal() - 1)
    quiet = _at(eve, CHEER_QUIET_FROM_MIN, tz)
    start, end = _at(eve, p.cheer_eve_start_min, tz), _at(eve, p.checkin_day_end_min, tz)
    if start <= frame.now <= end:
        return start, quiet
    if not ev.all_day and frame.local(ev.when).hour >= 12:
        morning = _at(day, p.checkin_day_start_min, tz)
        if morning <= frame.now <= ev.when - 2 * HOUR:
            return morning, quiet
    return None


def _hard(frame: Frame, person: str) -> bool:
    """Quelque chose de grave la touche ces jours-ci (un deuil, une rupture) : le banal se tait."""
    return frame.get(memory_c.HARD_TIMES(person)) > 0


def _minor(ev: memory_c.LifeEvent) -> bool:
    """Un moment ordinaire (un rendez-vous de routine, une sortie) : ni important, ni à fêter."""
    return not ev.festive and ev.importance < memory_c.IMPORTANT_MOMENT


@OTHERS.propose(kinds=[Kind.INITIATIVE], reasons={c.CHEER: (0.0, 12.0)},
                reads=[identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY, presence_c.PRESENT,
                       social_c.CIRCLE, social_c.KNOWN, social_c.CLOSENESS, transcript_c.LAST_FROM, memory_c.LIFE_EVENTS,
                       memory_c.HARD_TIMES])
def _cheer(s: OthersState, frame: Frame) -> list[Candidate]:
    """Une amie lui avait dit ce qui l'attendait (« demain, mon entretien chez Ubisoft ») : la veille au soir, un
    mot pour l'encourager — si elles ne se sont pas déjà parlé depuis midi (la conversation en était
    l'occasion), une fois. Plus faible que demander comment ça s'est passé : elle le fait si elle y pense.
    Seulement ce que la personne lui a dit elle-même ; rien d'ordinaire quand quelque chose de grave la touche
    ces jours-ci (pas de « bonne chance chez le dentiste » le lendemain d'un deuil). Au cran de leur lien
    (``care_by_closeness``, ADR 0150) ; seules celles qu'elle connaît sont passées en revue (``_reviewed``, un tri bon
    marché) : les inconnues de passage ne coûtent rien ici."""
    p = params(frame.env.params_of("others", frame.root))
    out: list[Candidate] = []
    for person in sorted(set(_reviewed(frame, p.care_by_closeness)).intersection(heard(s))):
        share = p.care_by_closeness.get(frame.get(social_c.CLOSENESS(person)), 0.0)
        if share <= 0:
            continue
        last = identity_c.last_heard(frame, person)
        hard = _hard(frame, person)
        # une fois par date : redit le même soir, il est déjà encouragé ; déplacé, il l'est pour la nouvelle veille
        due = [(ev, w) for ev in frame.get(memory_c.LIFE_EVENTS(person))
               if set(ev.told_by) <= {person} and not (hard and _minor(ev))
               and s.spoke.get(ev.key, 0) < _day_start(ev.when, frame) - DAY
               and (w := _cheer_window(ev, frame, p)) is not None and last < w[1]]
        address = identity_c.reach_now(frame, person) if due else None
        if address is None:
            continue
        ev, (start, _end) = due[0]  # le plus proche
        soon = phrase("others.initiative.tomorrow") if frame.local(ev.when).date() > frame.local().date() else \
            phrase("others.initiative.later")
        brief = phrase("others.initiative.cheer", who=capitalized(_who(frame, person, address)), soon=soon)
        ramp = min(1.0, (frame.now - start) / p.checkin_ramp_us)
        evidence = (p.checkin_evidence_start + (p.cheer_evidence - p.checkin_evidence_start) * ramp) * share
        out.append(_moment_candidate(c.CHEER, address, evidence, brief, frame, person, ev))
    return out


def _reviewed(frame: Frame, table: Mapping[str, float]) -> tuple[str, ...]:
    """Celles qu'une attention passe en revue : ses amies et ses proches (``CIRCLE``), et ses connaissances quand la
    table leur laisse quelque chose (``KNOWN``, ADR 0150) — jamais les inconnues de passage."""
    return frame.get(social_c.KNOWN if table.get(social_c.ACQUAINTANCE, 0.0) > 0 else social_c.CIRCLE)


def _day_start(t: int, frame: Frame) -> int:
    return _at(frame.local(t).date(), 0, frame.env.tz_of(frame.root))


def _follow_from(ev: memory_c.LifeEvent, frame: Frame, p: OthersParams) -> int:
    """À partir de quand demander comment ça s'est passé : quelques heures après ; un moment qui se fête, pas
    avant le lendemain (le jour même, ce sont ses vœux)."""
    if ev.festive:
        return max(ev.when, _day_start(ev.when, frame) + DAY + HOUR)  # le lendemain (une heure de marge : l'heure d'été)
    return ev.when + p.followup_after_us


@OTHERS.propose(kinds=[Kind.INITIATIVE], reasons={c.FOLLOW_UP: (0.0, 12.0)},
                reads=[identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY, presence_c.PRESENT,
                       social_c.CIRCLE, social_c.KNOWN, social_c.CLOSENESS, transcript_c.LAST_FROM, memory_c.LIFE_EVENTS,
                       memory_c.HARD_TIMES])
def _follow_up(s: OthersState, frame: Frame) -> list[Candidate]:
    """Une amie lui avait dit ce qui l'attendait (un entretien jeudi à 14 h) : quelques heures après, si elles
    n'en ont pas reparlé, elle a envie de savoir comment ça s'est passé — « alors, cet entretien ? ». Seulement
    ce que la personne lui a dit elle-même (ce qu'un tiers a raconté d'elle, le lui demander trahirait le tiers),
    une fois par moment. Si la personne lui a écrit depuis, c'était l'occasion : la conversation (« CE QUI SE
    PASSE DANS SA VIE ») s'en charge, pas une initiative de plus.

    Gradué (ADR 0052) : ce qui compte (un entretien, un examen) avec insistance ; un moment ordinaire, si elle y
    pense ; quand quelque chose de grave la touche ces jours-ci, l'ordinaire se tait et ce qui compte passe
    après des nouvelles d'elle. Ce qui se fête : pas de « comment ça s'est passé » si elle l'a souhaité le jour
    même — sinon, le lendemain, un mot même en retard. Une date qui revient chaque année sans se fêter (la date d'un
    deuil) ne se demande jamais : ce n'est pas quelque chose qui « s'est passé »."""
    p = params(frame.env.params_of("others", frame.root))
    if not _in_checkin_hours(frame, p):
        return []
    out: list[Candidate] = []
    for person in sorted(set(_reviewed(frame, p.care_by_closeness)).intersection(heard(s))):
        share = p.care_by_closeness.get(frame.get(social_c.CLOSENESS(person)), 0.0)
        if share <= 0:
            continue
        last = identity_c.last_heard(frame, person)
        hard = _hard(frame, person)
        due = [ev for ev in frame.get(memory_c.LIFE_EVENTS(person))
               if not ev.ongoing and not ev.vague and not ev.followed_at and set(ev.told_by) <= {person}
               and ev.outcome not in (memory_c.CANCELLED, memory_c.MOVED)  # annulé : rien à demander (ADR 0086)
               and not (hard and _minor(ev)) and (ev.festive or not ev.yearly)
               and s.spoke.get(ev.key, 0) < (_day_start(ev.when, frame) if ev.festive else ev.when)
               and last <= ev.when and _follow_from(ev, frame, p) <= frame.now <= ev.when + p.followup_until_us]
        address = identity_c.reach_now(frame, person) if due else None
        if address is None:
            continue
        ev = due[-1]  # le plus récent
        who = _who(frame, person, address)
        if ev.festive:
            brief = phrase("others.initiative.follow_up_festive", who=who)
        else:
            brief = phrase("others.initiative.follow_up", who=capitalized(who))
        full = p.followup_minor_evidence if (_minor(ev) or ev.festive or hard) else p.followup_evidence
        ramp = min(1.0, (frame.now - _follow_from(ev, frame, p)) / p.checkin_ramp_us)
        evidence = (min(full, p.checkin_evidence_start) + (full - min(full, p.checkin_evidence_start)) * ramp) * share
        out.append(_moment_candidate(c.FOLLOW_UP, address, evidence, brief, frame, person, ev))
    return out


@OTHERS.propose(kinds=[Kind.INITIATIVE], reasons={c.CELEBRATE: (0.0, 12.0)},
                reads=[identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY, presence_c.PRESENT,
                       social_c.CIRCLE, social_c.KNOWN, social_c.CLOSENESS, transcript_c.LAST_FROM, memory_c.LIFE_EVENTS,
                       memory_c.HARD_TIMES])
def _celebrate(s: OthersState, frame: Frame) -> list[Candidate]:
    """Le jour d'un anniversaire, d'un mariage qu'une amie lui avait annoncé : elle le lui souhaite, d'elle-même,
    une fois, dans ses heures pour prendre des nouvelles — plus fort qu'une question (sonde réelle du 2026-10-03 :
    le samedi des 30 ans de Sam, son initiative de 11 h était un « prendre des nouvelles », le « joyeux
    anniversaire » n'est venu qu'à la réponse suivante). Qu'elle l'ait souhaité en répondant (ses mots reprennent
    le moment) suffit : rien de plus. Quand quelque chose de grave la touche ces jours-ci, le brief le dit aussi —
    un fait ; ce qu'elle en fait est à elle (ADR 0154)."""
    p = params(frame.env.params_of("others", frame.root))
    if not _in_checkin_hours(frame, p):
        return []
    today = _day_start(frame.now, frame)
    out: list[Candidate] = []
    for person in sorted(set(_reviewed(frame, p.care_by_closeness)).intersection(heard(s))):
        share = p.care_by_closeness.get(frame.get(social_c.CLOSENESS(person)), 0.0)
        if share <= 0:
            continue
        due = [ev for ev in frame.get(memory_c.LIFE_EVENTS(person))
               if ev.festive and not ev.ongoing and not ev.vague and not ev.followed_at and set(ev.told_by) <= {person}
               and _day_start(ev.when, frame) == today and s.spoke.get(ev.key, 0) < today]
        address = identity_c.reach_now(frame, person) if due else None
        if address is None:
            continue
        ev = due[0]
        # ce qui pèse ces jours-ci, la section le dit (« CE QUI SE PASSE DANS SA VIE », en privé) : pas le motif
        brief = phrase("others.initiative.celebrate", who=_who(frame, person, address))
        # si la personne écrit entre-temps, c'est sa réponse qui le lui souhaite (« souhaite-le-lui si ce n'est pas
        # fait »), pas une initiative de plus : la garde de ``_moment_candidate``
        out.append(_moment_candidate(c.CELEBRATE, address, p.celebrate_evidence * share, brief, frame, person, ev))
    return out


@OTHERS.propose(kinds=[Kind.INITIATIVE], reasons={c.REMEMBRANCE: (0.0, 12.0)},
                reads=[identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY, presence_c.PRESENT,
                       social_c.CIRCLE, social_c.KNOWN, social_c.CLOSENESS, transcript_c.LAST_FROM, memory_c.LIFE_EVENTS])
def _remember(s: OthersState, frame: Frame) -> list[Candidate]:
    """Le jour où revient une date lourde qu'une proche lui a confiée elle-même (« demain, ça fera un an que mon père
    est parti ») : l'envie de lui écrire, d'elle-même, une fois, dans ses heures pour prendre des nouvelles — le
    brief dit le jour, pas le ton (ADR 0154). Au cran de leur lien (``remembrance_by_closeness``, ADR 0150), d'abord une proche seulement : une
    amie, ce jour-là, n'en reçoit rien d'elle-même (si elles se parlent, « CE QUI SE PASSE DANS SA VIE » le lui dit). Si elles se sont déjà parlé aujourd'hui, la conversation en était
    l'occasion ; ce qu'elle en a repris en mots aussi."""
    p = params(frame.env.params_of("others", frame.root))
    if not _in_checkin_hours(frame, p):
        return []
    today = _day_start(frame.now, frame)
    out: list[Candidate] = []
    for person in sorted(set(_reviewed(frame, p.remembrance_by_closeness)).intersection(heard(s))):
        share = p.remembrance_by_closeness.get(frame.get(social_c.CLOSENESS(person)), 0.0)
        if share <= 0 or identity_c.last_heard(frame, person) >= today:
            continue
        due = [ev for ev in frame.get(memory_c.LIFE_EVENTS(person))
               if memory_c.heavy_date(ev) and not ev.followed_at and set(ev.told_by) <= {person}
               and _day_start(ev.when, frame) == today and s.spoke.get(ev.key, 0) < today]
        address = identity_c.reach_now(frame, person) if due else None
        if address is None:
            continue
        ev = due[0]
        brief = phrase("others.initiative.remembrance", who=_who(frame, person, address))
        out.append(_moment_candidate(c.REMEMBRANCE, address, p.remembrance_evidence * share, brief, frame, person,
                                     ev))
    return out

