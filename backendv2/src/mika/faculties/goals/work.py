"""Ce que les buts apportent à l'arbitrage : avancer d'un pas, dire un
rappel à l'heure, raconter ce qu'elle a mené à bout.

- **Un pas** (``STEP``, cible ``goal:<id>``) : l'envie d'une exploration le
  porte (elle s'use) ; un projet confié, son agenda. Un pas à la fois par but
  (bail de l'atelier), espacés, au plus quatre dans l'heure. Aucun pour un but
  suspendu (et un pas en cours est supplanté : sa garde voit « en pause »).
- **Un rappel** se dit à l'heure : l'ordinaire reste sous la barre de réveil
  (il attend qu'elle se réveille), l'urgent la passe ; suspendu, il se tait.
- **Raconter** : à qui, et combien, dépend du lien — jamais d'un appel au
  modèle. La personne que ça concerne si elle est amie ou proche, sinon sa
  propriétaire ; à la propriétaire tout, à une proche l'essentiel, à une amie
  une simple mention ; à personne d'autre.
"""

from __future__ import annotations

from mika.contracts import body as body_c
from mika.contracts import goals as c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import social as social_c
from mika.faculties.goals.faculty import GOALS, Goal, GoalsState, desire, live, params, status
from mika.kernel import schedule
from mika.kernel.arbitration import Candidate, Modulation, RowView
from mika.kernel.clock import HOUR
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, floor, workshop
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import Kind, goal_target

#: au-dessus de la barre de réveil : un rappel urgent la réveille
URGENT_EVIDENCE = body_c.WAKE_BAR + 2.0
FULL, SUMMARY, MENTION = "full", "summary", "mention"
STEP_MAY_SEE = (c.ACTIVE, c.WAITING, c.ACHIEVED, c.STUCK)
_RANK = {level: i for i, level in enumerate(social_c.CLOSENESS_LEVELS)}


def _still(goal: int, wanted: tuple[str, ...]) -> Guard:
    """L'épisode ne vaut que tant que le but est dans cet état."""
    return Guard("but", predicate=lambda view, g=goal: view.get(c.STATUS(g)) in wanted)


def next_step_at(g: Goal, s: GoalsState, frame: Frame) -> int | None:
    """Quand ce but peut avancer d'un pas (``None`` : pas maintenant)."""
    p = params(frame.env.params_of("goals", frame.root))
    if g.kind not in (c.EXPLORATION, c.PROJECT) or status(g, frame.now) != c.ACTIVE:
        return None if status(g, frame.now) != c.WAITING else g.waiting_until
    if g.steps >= g.max_steps or any(r.goal == g.id and r.purpose == "step" for r in s.running.values()):
        return None
    spacing = p.project_spacing_us if g.kind == c.PROJECT else p.step_spacing_us
    at = g.last_step_at + spacing if g.last_step_at else g.opened_at
    if g.kind == c.PROJECT and g.schedule:
        rule = schedule.read(g.schedule)
        if rule.kind != "manual":
            due = schedule.next_after(rule, g.last_step_at or g.opened_at, frame.env.tz_of(frame.root))
            if due is None:
                return None
            at = max(at, due)
    return at


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
        if g.kind == c.PROJECT:
            evidence = p.project_evidence
        else:
            evidence = min(12.0, p.work_base + p.work_per_desire * desire(g, frame.now, p))
        out.append(Candidate(
            Kind.STEP, goal_target(g.id), c.WORK, round(evidence, 4), resources=frozenset({workshop(str(g.id))}),
            # le pas lui-même peut conclure (abouti, bloqué, en attente) : seule une fin venue d'ailleurs le supplante
            guards=(_still(g.id, STEP_MAY_SEE),),
            args=FrozenDict({"bundles": ",".join(g.bundles), "subject": goal_target(g.id)})))
    return out


@GOALS.modulate(kinds=[Kind.STEP])
def _hourly(s: GoalsState, frame: Frame, row: RowView) -> Modulation:
    """Au plus quelques pas dans l'heure, tous buts confondus : le travail
    silencieux coûte des appels au modèle, et ne passe pas par le budget
    d'initiatives."""
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


@GOALS.propose(kinds=[Kind.INITIATIVE], reasons={c.REMIND: (0.0, URGENT_EVIDENCE)}, reads=[c.STATUS])
def _remind(s: GoalsState, frame: Frame) -> list[Candidate]:
    p = params(frame.env.params_of("goals", frame.root))
    out = []
    for g in sorted(s.goals.values(), key=lambda g: g.id):
        if g.kind != c.REMINDER or status(g, frame.now) != c.ACTIVE or g.delivered or not g.address:
            continue
        if g.due is None or g.due > frame.now or g.retry_at > frame.now or g.attempts >= p.remind_attempts:
            continue
        if frame.now - g.due > p.remind_too_late_us:
            continue
        who = _name(frame, g.address)
        brief = (f"C'est l'heure du rappel que {f'« {who} »' if who else 'cette personne'} t'a demandé (le détail "
                 "est plus haut, « LE RAPPEL ») : rappelle-le-lui, simplement, à ta façon.")
        out.append(Candidate(
            Kind.INITIATIVE, g.address, c.REMIND, URGENT_EVIDENCE if g.urgent else p.remind_evidence,
            resources=frozenset({floor(g.address)}), guards=(_still(g.id, (c.ACTIVE,)),),
            args=FrozenDict({"brief:goals": brief, "subject": goal_target(g.id)})))
    return out


def confidant(g: Goal, frame: Frame) -> tuple[str, str, str] | None:
    """(personne, poignée, niveau de récit) — ou personne. La personne que ça
    concerne d'abord (si elle est amie, proche ou propriétaire), sinon une
    propriétaire joignable ; jamais quelqu'un qui n'est ni l'un ni l'autre."""
    candidates: list[str] = []
    if g.owner:
        candidates.append(g.owner)
    candidates += [a for a in g.about if a not in candidates]
    if not g.about or g.kind == c.PROJECT:
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
        chosen = confidant(g, frame)
        if chosen is None:
            continue
        person, address, level = chosen
        who = f"« {_name(frame, person) or _name(frame, address)} »" if (_name(frame, person) or _name(frame, address)) \
            else "cette personne"
        brief = {
            FULL: f"Tu as mené à bout quelque chose (« CE QUE TU AS MENÉ À BOUT », plus haut) : raconte-le à {who}, "
                  "simplement, comme on partage une bonne nouvelle.",
            SUMMARY: f"Tu as mené à bout quelque chose qui te tenait à cœur : dis-le en deux mots à {who}, sans "
                     "entrer dans tous les détails.",
            MENTION: f"Tu as fini quelque chose qui te tenait à cœur : tu peux le mentionner à {who} en passant, "
                     "sans entrer dans le détail.",
        }[level]
        out.append(Candidate(
            Kind.INITIATIVE, address, c.SHARE, p.share_evidence, resources=frozenset({floor(address)}),
            guards=(_still(g.id, (c.ACHIEVED,)),),
            args=FrozenDict({"brief:goals": brief, "subject": goal_target(g.id), "share": level})))
    return out
