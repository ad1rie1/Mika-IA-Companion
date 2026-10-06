"""Ce que les buts apportent à l'arbitrage : avancer d'un pas, dire un
rappel à l'heure, raconter ce qu'elle a mené à bout.

- **Un pas** (``STEP``, cible ``goal:<id>``) : l'envie d'une exploration le
  porte (elle s'use). Un pas à la fois par but, espacés, au plus quatre dans
  l'heure. Aucun pour un but suspendu (et un pas en cours est supplanté : sa
  garde voit « en pause »). Les projets ont leurs exécutions à eux (``projects``).
- **Un rappel** se dit à l'heure : l'ordinaire reste sous la barre de réveil
  (il attend qu'elle se réveille), l'urgent la passe ; suspendu, il se tait.
  Il part **là où la personne est à l'échéance** (connectée, sinon joignable),
  pas à l'adresse figée au moment de la demande.
- **Raconter** : à qui, et combien, dépend du lien — jamais d'un appel au
  modèle. La personne que ça concerne si elle est amie ou proche, sinon sa
  propriétaire ; à la propriétaire tout, à une proche l'essentiel, à une amie
  une simple mention ; à personne d'autre. Une inquiétude pour quelqu'un n'est
  pas une bonne nouvelle : à cette personne-là, elle prend de ses nouvelles. La
  consigne ne renvoie à aucune section (le murmure qui précède l'entend aussi)
  et ne dit rien du contenu.
"""

from __future__ import annotations

from mika.contracts import body as body_c
from mika.contracts import goals as c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import social as social_c
from mika.faculties.goals.faculty import (
    GOALS,
    Goal,
    GoalsState,
    budget,
    desire,
    live,
    musing,
    params,
    rank,
    status,
)
from mika.kernel.arbitration import Candidate, Modulation, RowView
from mika.kernel.clock import HOUR
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, floor, workshop
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import Kind, goal_of, goal_target
from mika.vocab.phrasebook import phrase

#: au-dessus de la barre de réveil : un rappel urgent la réveille
URGENT_EVIDENCE = body_c.WAKE_BAR + 2.0
FULL, SUMMARY, MENTION = "full", "summary", "mention"
STEP_MAY_SEE = (c.ACTIVE, c.WAITING, c.ACHIEVED, c.STUCK)
_RANK = {level: i for i, level in enumerate(social_c.CLOSENESS_LEVELS)}


def _still(goal: int, wanted: tuple[str, ...]) -> Guard:
    """L'épisode ne vaut que tant que le but est dans cet état."""
    return Guard("but", predicate=lambda view, g=goal: view.get(c.STATUS(g)) in wanted)


def next_step_at(g: Goal, s: GoalsState, frame: Frame) -> int | None:
    """Quand ce but peut avancer d'un pas (``None`` : pas maintenant). « Avancer maintenant »
    (``nudged_at``, tant qu'aucun pas n'est parti depuis) passe avant l'espacement."""
    p = params(frame.env.params_of("goals", frame.root))
    if g.kind != c.EXPLORATION or status(g, frame.now) != c.ACTIVE:
        return None if g.kind != c.EXPLORATION or status(g, frame.now) != c.WAITING else g.waiting_until
    if g.steps >= budget(g, p) or any(r.goal == g.id and r.purpose == "step" for r in s.running.values()):
        return None
    if g.nudged_at > g.last_step_at:
        return g.nudged_at
    return g.last_step_at + p.step_spacing_us if g.last_step_at else g.opened_at


@GOALS.propose(kinds=[Kind.STEP], reasons={c.WORK: (0.0, 12.0)}, reads=[c.STATUS])
def _work(s: GoalsState, frame: Frame) -> list[Candidate]:
    p = params(frame.env.params_of("goals", frame.root))
    out = []
    for g in sorted(s.goals.values(), key=lambda g: g.id):
        if not live(g, frame.now):
            continue
        at = next_step_at(g, s, frame)
        if at is None or at > frame.now:
            continue
        evidence = p.work_base + p.work_per_desire * desire(g, frame.now, p)
        evidence = max(0.0, min(12.0, evidence + p.priority_step * rank(g)))
        out.append(Candidate(
            Kind.STEP, goal_target(g.id), c.WORK, round(evidence, 4), resources=frozenset({workshop(str(g.id))}),
            # le pas lui-même peut conclure (abouti, bloqué, en attente) : seule une fin venue d'ailleurs le supplante
            guards=(_still(g.id, STEP_MAY_SEE),),
            args=FrozenDict({"bundles": ",".join(g.bundles), "subject": goal_target(g.id)})))
    return out


def why_not_now(g: Goal, s: GoalsState, frame: Frame) -> str:
    """Pourquoi ce but n'a pas de séance maintenant, en mots (vide : il peut en avoir une)."""
    p = params(frame.env.params_of("goals", frame.root))
    now = frame.now
    st = status(g, now)
    if g.kind == c.REMINDER:
        return "un rappel n'a pas de séance de travail : il se dit à l'heure"
    if g.kind != c.EXPLORATION:
        return "un ancien projet (avant les projets à part) : il n'a plus de séance"
    if st in c.CLOSED_STATUSES:
        return "il est clos"
    if st == c.PAUSED:
        return "il est en pause : reprends-le"
    if st == c.WAITING:
        whom = f"la réponse de {_name(frame, g.wait_for) or g.wait_for}" if g.wait_for else "un délai"
        return f"elle attend {whom}"
    if any(r.goal == g.id and r.purpose == "step" for r in s.running.values()):
        return "une séance est en cours"
    if g.steps >= budget(g, p):
        return f"au bout de ses séances ({g.steps} sur {budget(g, p)})"
    if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
        return "elle dort : aucune séance la nuit"
    at = next_step_at(g, s, frame)
    if at is None:
        return "plus de créneau"
    if sum(1 for t in s.steps_at if now - t < HOUR) >= p.steps_per_hour:
        return f"plafond atteint : {p.steps_per_hour} séances par heure, tous buts confondus"
    if at > now:
        return "pas encore : l'espacement des séances la fixe plus tard"
    return ""


@GOALS.modulate(kinds=[Kind.STEP])
def _hourly(s: GoalsState, frame: Frame, row: RowView) -> Modulation:
    """Au plus quelques pas dans l'heure, tous buts confondus : le travail
    silencieux coûte des appels au modèle, et ne passe pas par le budget
    d'initiatives. (Les exécutions des projets ont leur propre plafond.)"""
    if goal_of(row.target) is None:
        return Modulation()
    p = params(frame.env.params_of("goals", frame.root))
    recent = sum(1 for t in s.steps_at if frame.now - t < HOUR)
    return Modulation(veto=c.STEP_CAP) if recent >= p.steps_per_hour else Modulation()


def _name(frame: Frame, key: str | None) -> str:
    if not key:
        return ""
    return frame.get(identity_c.IDENTITY(key)).name


def _address(frame: Frame, person: str) -> str | None:
    handles = frame.get(identity_c.HANDLES(person)) or (person,)
    present = [h for h in frame.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    reachable = frame.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else None


def remind_address(g: Goal, frame: Frame) -> str | None:
    """Où dire un rappel à l'échéance : là où la personne est maintenant (connectée, sinon joignable), sinon
    l'adresse d'où venait la demande."""
    return (_address(frame, g.owner) if g.owner else None) or g.address


@GOALS.propose(kinds=[Kind.INITIATIVE], reasons={c.REMIND: (0.0, URGENT_EVIDENCE)},
               reads=[c.STATUS, identity_c.HANDLES, identity_c.REACHABLE, presence_c.PRESENT, identity_c.IDENTITY])
def _remind(s: GoalsState, frame: Frame) -> list[Candidate]:
    p = params(frame.env.params_of("goals", frame.root))
    out = []
    for g in sorted(s.goals.values(), key=lambda g: g.id):
        if g.kind != c.REMINDER or status(g, frame.now) != c.ACTIVE or g.delivered:
            continue
        if g.due is None or g.due > frame.now or g.retry_at > frame.now or g.attempts >= p.remind_attempts:
            continue
        if frame.now - g.due > p.remind_too_late_us:
            continue
        address = remind_address(g, frame)
        if not address:
            continue
        who = _name(frame, g.owner) or _name(frame, address)
        brief = phrase("goals.brief.remind", who=f"« {who} »" if who else phrase("expression.person.unnamed"))
        out.append(Candidate(
            Kind.INITIATIVE, address, c.REMIND, URGENT_EVIDENCE if g.urgent else p.remind_evidence,
            resources=frozenset({floor(address)}), guards=(_still(g.id, (c.ACTIVE,)),),
            args=FrozenDict({"brief:goals": brief, "subject": goal_target(g.id)})))
    return out


def confidant(g: Goal, frame: Frame) -> tuple[str, str, str] | None:
    """(personne, adresse, niveau de récit) — ou personne. La personne que ça
    concerne d'abord (si elle est amie, proche ou propriétaire), sinon une
    propriétaire joignable ; jamais quelqu'un qui n'est ni l'un ni l'autre."""
    candidates: list[str] = []
    if g.owner:
        candidates.append(g.owner)
    candidates += [a for a in g.about if a not in candidates]
    if not g.about:
        candidates += [o for o in frame.get(identity_c.OWNERS) if o not in candidates]
    for person in candidates:
        concerned = person == g.owner or person in g.about
        if frame.get(identity_c.IS_OWNER(person)) and (concerned or not g.about):
            level = FULL
        else:
            closeness = frame.get(social_c.CLOSENESS(person))
            if not concerned or _RANK.get(closeness, 0) < _RANK[social_c.FRIEND]:
                continue
            level = SUMMARY if closeness == social_c.CLOSE else MENTION
        address = _address(frame, person)
        if address is not None:
            return person, address, level
    return None


def worry_of(g: Goal, person: str | None) -> bool:
    """Ce but est-il une inquiétude pour cette personne-là (ce qu'elle lui a confié) ? Alors ce n'est pas un
    résultat à lui annoncer."""
    worry = g.origin == c.FROM_EXCHANGE or (not g.origin and g.source.startswith("thought:"))
    return worry and person is not None and (person == g.owner or person in g.about)


def share_brief(g: Goal, person: str, address: str, level: str, frame: Frame) -> str:
    """Ce qu'elle se dit avant de raconter, selon d'où venait le but : une inquiétude pour quelqu'un n'est pas un
    résultat à annoncer à cette personne-là (elle prend de ses nouvelles). La consigne ne renvoie à aucune section
    et ne dit rien du contenu (le murmure qui la précède s'entend)."""
    name = _name(frame, person) or _name(frame, address)
    who = f"« {name} »" if name else phrase("expression.person.unnamed")
    if worry_of(g, person):
        return phrase("goals.brief.worry", who=who)
    if level == FULL:
        return phrase("goals.brief.share.full", who=who)
    if level == SUMMARY:
        return phrase("goals.brief.share.summary", who=who)
    return phrase("goals.brief.share.mention", who=who)


@GOALS.propose(kinds=[Kind.INITIATIVE], reasons={c.SHARE: (0.0, 10.0)},
               reads=[identity_c.OWNERS, identity_c.IS_OWNER, social_c.CLOSENESS, identity_c.HANDLES,
                      identity_c.REACHABLE, presence_c.PRESENT, identity_c.IDENTITY])
def _share(s: GoalsState, frame: Frame) -> list[Candidate]:
    p = params(frame.env.params_of("goals", frame.root))
    out = []
    for g in sorted(s.goals.values(), key=lambda g: g.id):
        if g.status != c.ACHIEVED or g.kind == c.REMINDER or g.shared or g.share_attempts >= p.share_attempts:
            continue
        if g.notable < p.share_notable_from or frame.now - g.closed_at > p.share_within_us:
            continue
        if musing(g):  # une rêverie n'est pas une nouvelle : rien de neuf n'est arrivé
            continue
        chosen = confidant(g, frame)
        if chosen is None:
            continue
        person, address, level = chosen
        brief = share_brief(g, person, address, level, frame)
        out.append(Candidate(
            Kind.INITIATIVE, address, c.SHARE, p.share_evidence, resources=frozenset({floor(address)}),
            guards=(_still(g.id, (c.ACHIEVED,)),),
            args=FrozenDict({"brief:goals": brief, "subject": goal_target(g.id), "share": level})))
    return out
