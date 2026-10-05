"""Ce que les projets apportent à l'arbitrage : une exécution quand elle est
due, et raconter ce qu'elle a mené à bout (mode Mika seulement).

- **Une exécution** (``WORK`` en mode Mika, ``JOB`` en mode impersonnel ; cible
  ``project:<id>``) part quand un objectif est dû, dans la plage de travail,
  selon l'agenda et l'espacement, sous le plafond du jour du projet et le
  plafond horaire commun. « Lancer maintenant » passe l'agenda, l'espacement
  et la plage, jamais les plafonds. En mode Mika, son corps la retient
  pendant qu'elle dort (``body``) ; en mode impersonnel, non.
- **Raconter** : à qui lui a confié le projet (ou à une propriétaire), à la
  mesure du lien — jamais d'un appel au modèle. Un point quand le travail
  s'est posé (rien en cours, rien de dû avant un moment), qui dit d'une fois
  tout ce qui a été mené à bout depuis le précédent.
"""

from __future__ import annotations

from typing import Any

from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import projects as c
from mika.contracts import social as social_c
from mika.faculties.projects.faculty import (
    ON_DEMAND,
    PROJECTS,
    Objective,
    Project,
    ProjectsState,
    busy,
    daily_cap,
    in_window,
    next_due,
    nudged,
    outgoing,
    params,
    pick,
    rank,
    runs_today,
    subject_of,
    window_opens,
)
from mika.kernel import schedule
from mika.kernel.arbitration import Candidate, Modulation, RowView
from mika.kernel.clock import DAY, HOUR
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, floor, workshop
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import Kind, project_of, project_target

FULL, SUMMARY, MENTION = "full", "summary", "mention"
_RANK = {level: i for i, level in enumerate(social_c.CLOSENESS_LEVELS)}


def kind_of(p: Project) -> str:
    """L'épisode d'une exécution : sa voix à elle, ou l'impersonnel."""
    return Kind.WORK if p.mode == c.PERSONA else Kind.JOB


def _still(project: int) -> Guard:
    """L'exécution ne vaut que tant que le projet est actif."""
    return Guard("projet actif", predicate=lambda view, p=project: view.get(c.STATUS(p)) == c.ACTIVE)


def next_run_at(p: Project, s: ProjectsState, frame: Frame) -> int | None:
    """Quand ce projet peut avoir sa prochaine exécution (``None`` : pas en vue)."""
    pm = params(frame.env.params_of("projects", frame.root))
    now = frame.now
    if p.status != c.ACTIVE or busy(s, p.id) or not p.objectives or outgoing(p, now):
        return None
    if p.schedule == ON_DEMAND and not nudged(p):  # « sur demande » : il ne part que quand on le lance
        return None
    target = pick(p, now, pm)
    if target is None:
        due = next_due(p, pm)
        if due is None or due <= now:
            return None
        at = due
    else:
        at = now
    # l'espacement court depuis la dernière tentative : une exécution qui n'a pas eu lieu (crédit rendu) ne
    # consomme ni l'agenda ni « lancer maintenant », mais ne se relance pas en boucle non plus
    spaced = p.tried_at + pm.run_spacing_us if p.tried_at else p.created_at
    if nudged(p) and target is not None:
        return max(p.nudged_at, at, spaced if p.tried_at > p.nudged_at else 0)
    at = max(at, spaced)
    if p.schedule and p.schedule != ON_DEMAND:
        rule = schedule.read(p.schedule)
        if rule.kind != "manual":
            due = schedule.next_after(rule, p.last_run_at or p.created_at, frame.env.tz_of(frame.root))
            if due is None:
                return None
            at = max(at, due)
    if runs_today(p, now) >= daily_cap(p, pm):  # la plus ancienne des dernières 24 h libère une place
        at = max(at, min(t for t in p.runs_at if now - t < DAY) + DAY)
    opens = window_opens(p, at, frame.env.tz_of(frame.root))
    return opens


@PROJECTS.propose(kinds=[Kind.WORK, Kind.JOB], reasons={c.RUN: (0.0, 12.0)}, reads=[c.STATUS])
def _run(s: ProjectsState, frame: Frame) -> list[Candidate]:
    pm = params(frame.env.params_of("projects", frame.root))
    out = []
    for p in sorted(s.projects.values(), key=lambda p: p.id):
        at = next_run_at(p, s, frame)
        if at is None or at > frame.now:
            continue
        if runs_today(p, frame.now) >= daily_cap(p, pm):
            continue
        target = pick(p, frame.now, pm)
        if target is None:
            continue
        evidence = max(0.0, min(12.0, pm.run_evidence + pm.priority_step * rank(p)))
        out.append(Candidate(
            kind_of(p), project_target(p.id), c.RUN, round(evidence, 4), resources=frozenset({workshop(f"projet-{p.id}")}),
            guards=(_still(p.id),),
            args=FrozenDict({"bundles": ",".join(p.bundles), "subject": subject_of(p.id, target.id)})))
    return out


@PROJECTS.modulate(kinds=[Kind.WORK, Kind.JOB])
def _hourly(s: ProjectsState, frame: Frame, row: RowView) -> Modulation:
    """Au plus quelques exécutions dans l'heure, tous projets confondus : chacune coûte des appels au modèle."""
    if project_of(row.target) is None:
        return Modulation()
    pm = params(frame.env.params_of("projects", frame.root))
    recent = sum(1 for t in s.runs_at if frame.now - t < HOUR)
    return Modulation(veto=c.RUN_CAP) if recent >= pm.runs_per_hour else Modulation()


def why_not_now(p: Project, s: ProjectsState, frame: Frame) -> str:
    """Pourquoi ce projet n'a pas d'exécution maintenant, en mots (vide : il peut en avoir une)."""
    pm = params(frame.env.params_of("projects", frame.root))
    now = frame.now
    tz = frame.env.tz_of(frame.root)
    if p.status == c.ARCHIVED:
        return "il est archivé"
    if p.status == c.PAUSED:
        return f"il est en pause{f' ({p.pause_reason})' if p.pause_reason else ''} : reprends-le"
    if busy(s, p.id):
        return "une exécution est en cours"
    if outgoing(p, now):
        return "une commande, un envoi ou une récupération sont en route : l'atelier les attend"
    if not p.objectives or not any(o.status == c.OPEN for o in p.objectives):
        return "aucun objectif ouvert : ajoutes-en un"
    if p.schedule == ON_DEMAND and not nudged(p):
        return "il avance sur demande : « Lancer maintenant »"
    if pick(p, now, pm) is None:
        due = next_due(p, pm)
        return "rien n'est dû : ses objectifs constants attendent leur cadence" + \
            (" ou une attente se termine" if due else "")
    if runs_today(p, now) >= daily_cap(p, pm):
        return f"plafond du jour atteint ({daily_cap(p, pm)} exécutions sur 24 h)"
    if sum(1 for t in s.runs_at if now - t < HOUR) >= pm.runs_per_hour:
        return f"plafond atteint : {pm.runs_per_hour} exécutions par heure, tous projets confondus"
    if p.mode == c.PERSONA and frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
        return "elle dort : en mode Mika, elle y travaille éveillée"
    if not nudged(p) and not in_window(p, now, tz):
        return "hors de sa plage de travail"
    at = next_run_at(p, s, frame)
    if at is None:
        return "son agenda ne lui donne plus de créneau"
    if at > now:
        return "pas encore : son agenda ou l'espacement des exécutions la fixe plus tard"
    return ""


# ── Raconter ce qu'elle a mené à bout ─────────────────────────────────────


def _name(frame: Frame, key: str | None) -> str:
    return frame.get(identity_c.IDENTITY(key)).name if key else ""


def _address(frame: Frame, person: str) -> str | None:
    handles = frame.get(identity_c.HANDLES(person)) or (person,)
    present = [h for h in frame.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    reachable = frame.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else None


def confidant(p: Project, frame: Frame) -> tuple[str, str, str] | None:
    """(personne, adresse, niveau de récit) — ou personne : qui lui a confié le projet d'abord (une
    propriétaire entend tout, une proche l'essentiel, une amie une mention), sinon une propriétaire."""
    candidates: list[str] = [p.owner] if p.owner else []
    candidates += [o for o in frame.get(identity_c.OWNERS) if o not in candidates]
    for person in candidates:
        if frame.get(identity_c.IS_OWNER(person)):
            level = FULL
        else:
            closeness = frame.get(social_c.CLOSENESS(person))
            if person != p.owner or _RANK.get(closeness, 0) < _RANK[social_c.FRIEND]:
                continue
            level = SUMMARY if closeness == social_c.CLOSE else MENTION
        address = _address(frame, person)
        if address is not None:
            return person, address, level
    return None


def _shareable(o: Objective, p: Project, now: int, pm) -> bool:
    return (o.kind == c.ONCE and o.status == c.DONE and not o.shared
            and o.share_attempts < pm.share_attempts and o.notable >= pm.share_notable_from
            and now - o.closed_at <= pm.share_within_us)


def untold(p: Project, now: int, pm: Any) -> list[Objective]:
    """Ce qu'elle a mené à bout dans ce projet sans l'avoir encore raconté, du plus ancien au plus récent : ce
    qu'un récit dit d'une fois."""
    return sorted((o for o in p.objectives if _shareable(o, p, now, pm)), key=lambda o: (o.closed_at, o.id))


def _settled(p: Project, s: ProjectsState, frame: Frame, last: Objective, pm: Any) -> bool:
    """Le travail s'est-il posé ? Rien ne tourne ni ne sort de l'atelier, et aucune exécution n'est due avant un
    moment — ou le dernier objectif fini attend déjà depuis ce moment (une exécution due que rien ne lance ne
    retient pas le récit)."""
    if busy(s, p.id) or outgoing(p, frame.now):
        return False
    if frame.now - last.closed_at >= pm.share_settle_us:
        return True
    at = next_run_at(p, s, frame)
    return at is None or at - frame.now >= pm.share_settle_us


def _reader(p: Project, frame: Frame) -> tuple[str, str] | None:
    """À qui rendre compte d'un projet impersonnel, ou dire qu'on a besoin d'aide : qui l'a confié (s'il s'occupe
    d'elle), sinon quelqu'un qui s'occupe d'elle — jamais une amie : c'est un travail."""
    candidates = [p.owner] if p.owner else []
    candidates += [o for o in frame.get(identity_c.OWNERS) if o not in candidates]
    for person in candidates:
        if frame.get(identity_c.IS_OWNER(person)) or (person == p.owner and p.authority == c.USER):
            address = _address(frame, person)
            if address is not None:
                return person, address
    return None


def _who_words(frame: Frame, person: str, address: str) -> str:
    name = _name(frame, person) or _name(frame, address)
    return f"« {name} »" if name else "cette personne"


#: ce qu'elle se dit avant de raconter : rien du contenu (le murmure s'entend), aucune référence à une section
SHARE_BRIEFS = {
    FULL: "Tu as mené à bout quelque chose dans un de tes projets : raconte-le à {who}, simplement.",
    SUMMARY: "Tu as fini quelque chose dans un de tes projets : dis-le en deux mots à {who}.",
    MENTION: "Tu as fini quelque chose dans un de tes projets : tu peux le mentionner à {who} en passant, sans "
             "entrer dans le détail.",
}
REPORT_BRIEF = ("Un projet qu'on t'a confié a avancé : fais-en un compte rendu factuel à {who}, en une ou deux phrases "
                "— c'est un travail, pas une fierté.")
NEED_BRIEF = ("Un projet qu'on t'a confié n'avance plus sans un coup de main de {who} : dis-le-lui simplement — ce qui "
              "bloque, et ce qu'il te faudrait.")


@PROJECTS.propose(kinds=[Kind.INITIATIVE], reasons={c.SHARE: (0.0, 10.0)},
                  reads=[identity_c.OWNERS, identity_c.IS_OWNER, social_c.CLOSENESS, identity_c.HANDLES,
                         identity_c.REACHABLE, presence_c.PRESENT, identity_c.IDENTITY])
def _share(s: ProjectsState, frame: Frame) -> list[Candidate]:
    """Raconter ce qu'elle a mené à bout (mode Mika, à la mesure du lien) ; en mode impersonnel, un compte rendu
    factuel à qui l'a confié. Un point quand le travail se pose, pas un message par objectif coché : le récit dit
    tout ce qui a été mené à bout depuis le précédent, sous le sujet du dernier fini."""
    pm = params(frame.env.params_of("projects", frame.root))
    out = []
    for p in sorted(s.projects.values(), key=lambda p: p.id):
        if p.status != c.ACTIVE:  # en pause ou archivé : on n'en parle plus de soi-même
            continue
        told = untold(p, frame.now, pm)
        if not told or not _settled(p, s, frame, told[-1], pm):
            continue
        if p.mode == c.PERSONA:
            chosen = confidant(p, frame)
            if chosen is None:
                continue
            person, address, level = chosen
            brief = SHARE_BRIEFS[level].format(who=_who_words(frame, person, address))
        else:
            reader = _reader(p, frame)
            if reader is None:
                continue
            person, address = reader
            level = FULL
            brief = REPORT_BRIEF.format(who=_who_words(frame, person, address))
        out.append(Candidate(
            Kind.INITIATIVE, address, c.SHARE, pm.share_evidence, resources=frozenset({floor(address)}),
            args=FrozenDict({"brief:projects": brief, "subject": subject_of(p.id, told[-1].id), "share": level})))
    return out


def _needy(o: Objective, now: int, pm: Any) -> bool:
    """Un objectif pour lequel il lui faut quelqu'un : bloqué depuis peu, ou ouvert avec un besoin dit."""
    if o.asked or o.ask_attempts >= pm.share_attempts:
        return False
    if o.status == c.BLOCKED and o.kind == c.ONCE:
        return now - o.closed_at <= pm.share_within_us
    return o.status == c.OPEN and bool(o.need_ref)


@PROJECTS.propose(kinds=[Kind.INITIATIVE], reasons={c.NEED: (0.0, 10.0)},
                  reads=[identity_c.OWNERS, identity_c.IS_OWNER, identity_c.HANDLES, identity_c.REACHABLE,
                         presence_c.PRESENT, identity_c.IDENTITY])
def _need(s: ProjectsState, frame: Frame) -> list[Candidate]:
    """« J'ai besoin de toi pour… » : un objectif d'un projet confié bloque, ou attend quelque chose de qui l'a
    confié — elle le lui dit (une fois, quelques tentatives au plus), dans les deux modes."""
    pm = params(frame.env.params_of("projects", frame.root))
    out = []
    for p in sorted(s.projects.values(), key=lambda p: p.id):
        if p.status != c.ACTIVE or p.authority != c.USER:
            continue
        o = next((x for x in p.objectives if _needy(x, frame.now, pm)), None)
        reader = _reader(p, frame) if o is not None else None
        if o is None or reader is None:
            continue
        person, address = reader
        out.append(Candidate(
            Kind.INITIATIVE, address, c.NEED, pm.need_evidence, resources=frozenset({floor(address)}),
            args=FrozenDict({"brief:projects": NEED_BRIEF.format(who=_who_words(frame, person, address)),
                             "subject": subject_of(p.id, o.id), "share": FULL})))
    return out
