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
- **Demander** : un objectif qui bloque ou attend quelque chose, à qui l'a confié
  (ou à une propriétaire) ; un projet à elle arrêté par des pannes, à une
  propriétaire, pour qu'on le relance (ADR 0143).
- **Le cadrage** (ADR 0145) : un projet né en conversation a d'abord sa séance
  de cadrage (sujet ``frame:<id>``), qui écrit son plan ; son plan se dit à qui
  l'a demandé (``plan:<id>``) — ses questions, qui attendent sa réponse, ou ce
  qu'elle va faire.
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
    achieved_at,
    busy,
    daily_cap,
    frame_subject,
    in_window,
    next_due,
    nudged,
    outgoing,
    params,
    pass_untold,
    pick,
    plan_subject,
    rank,
    run_bundles,
    runs_today,
    stall_subject,
    subject_of,
    window_opens,
)
from mika.kernel import schedule
from mika.kernel.arbitration import Candidate, Modulation, RowView
from mika.kernel.clock import DAY, HOUR
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, floor
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import Kind, project_of, project_target
from mika.vocab.phrasebook import phrase

FULL, SUMMARY, MENTION = "full", "summary", "mention"
_RANK = {level: i for i, level in enumerate(social_c.CLOSENESS_LEVELS)}


def kind_of(p: Project) -> str:
    """L'épisode d'une exécution : sa voix à elle, ou l'impersonnel."""
    return Kind.WORK if p.mode == c.PERSONA else Kind.JOB


def _still(project: int) -> Guard:
    """L'exécution ne vaut que tant que le projet est actif."""
    return Guard("projet actif", predicate=lambda view, p=project: view.get(c.STATUS(p)) == c.ACTIVE)


def frame_at(p: Project, s: ProjectsState, frame: Frame) -> int | None:
    """Quand sa séance de cadrage peut partir (ADR 0145) : à cadrer, dès que possible — sous l'espacement et le
    plafond du jour, sans attendre son agenda ni sa plage (ils règlent son travail, pas sa réflexion)."""
    if p.status != c.ACTIVE or p.plan_state != c.TO_FRAME or busy(s, p.id) or outgoing(p, frame.now):
        return None
    pm = params(frame.env.params_of("projects", frame.root))
    if p.frame_silent >= pm.silent_before_blocked:  # ses séances n'aboutissent pas : « tenir » l'arrête (ADR 0161)
        return None
    at = max(frame.now, p.tried_at + pm.run_spacing_us if p.tried_at else p.created_at)
    if runs_today(p, frame.now) >= daily_cap(p, pm):
        at = max(at, min(t for t in p.runs_at if frame.now - t < DAY) + DAY)
    return at


def next_run_at(p: Project, s: ProjectsState, frame: Frame) -> int | None:
    """Quand ce projet peut avoir sa prochaine exécution (``None`` : pas en vue) — sa séance de cadrage d'abord."""
    pm = params(frame.env.params_of("projects", frame.root))
    now = frame.now
    if p.plan_state == c.TO_FRAME:
        return frame_at(p, s, frame)
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
        evidence = max(0.0, min(12.0, pm.run_evidence + pm.priority_step * rank(p)))
        if p.plan_state == c.TO_FRAME:  # sa séance de cadrage : aucun objectif, le projet entier (ADR 0145)
            subject = frame_subject(p.id)
        else:
            target = pick(p, frame.now, pm)
            if target is None:
                continue
            subject = subject_of(p.id, target.id)
        out.append(Candidate(
            kind_of(p), project_target(p.id), c.RUN, round(evidence, 4), resources=frozenset({c.run_lease(p.id)}),
            guards=(_still(p.id),), args=FrozenDict({"bundles": ",".join(run_bundles(p)), "subject": subject})))
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
    if p.plan_state == c.PROPOSED:
        return "son plan attend la réponse de qui l'a demandé (« Valider le plan », ou en conversation)"
    if p.plan_state == c.TO_FRAME:
        at = frame_at(p, s, frame)
        return "" if at is not None and at <= now else "sa séance de cadrage attend l'espacement ou le plafond du jour"
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
        return "elle dort : en mode « elle-même », elle y travaille éveillée"
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
    """Un ponctuel mené à bout, ou le passage d'un constant qui a produit (un bilan de la semaine, ADR 0145), jugé
    notable et pas encore raconté."""
    if o.kind == c.CONSTANT:
        return (pass_untold(o) and o.share_attempts < pm.share_attempts and o.pass_notable >= pm.share_notable_from
                and now - o.passed_at <= pm.share_within_us)
    return (o.kind == c.ONCE and o.status == c.DONE and not o.shared
            and o.share_attempts < pm.share_attempts and o.notable >= pm.share_notable_from
            and now - o.closed_at <= pm.share_within_us)


def untold(p: Project, now: int, pm: Any) -> list[Objective]:
    """Ce qu'elle a mené à bout dans ce projet sans l'avoir encore raconté, du plus ancien au plus récent : ce
    qu'un récit dit d'une fois."""
    return sorted((o for o in p.objectives if _shareable(o, p, now, pm)), key=lambda o: (achieved_at(o), o.id))


def _settled(p: Project, s: ProjectsState, frame: Frame, last: Objective, pm: Any) -> bool:
    """Le travail s'est-il posé ? Rien ne tourne ni ne sort de l'atelier, et aucune exécution n'est due avant un
    moment — ou le dernier objectif fini attend déjà depuis ce moment (une exécution due que rien ne lance ne
    retient pas le récit)."""
    if busy(s, p.id) or outgoing(p, frame.now):
        return False
    if frame.now - achieved_at(last) >= pm.share_settle_us:
        return True
    at = next_run_at(p, s, frame)
    return at is None or at - frame.now >= pm.share_settle_us


def _reader(p: Project, frame: Frame) -> tuple[str, str] | None:
    """À qui rendre compte d'un projet impersonnel, ou dire qu'on a besoin d'aide : qui l'a confié (s'il s'occupe
    d'elle), ou qui le lui a demandé, sinon quelqu'un qui s'occupe d'elle — jamais une amie : c'est un travail."""
    candidates = [x for x in dict.fromkeys((p.owner, p.asked_by)) if x]
    candidates += [o for o in frame.get(identity_c.OWNERS) if o not in candidates]
    for person in candidates:
        if frame.get(identity_c.IS_OWNER(person)) or (person == p.owner and p.authority == c.USER):
            address = _address(frame, person)
            if address is not None:
                return person, address
    return None


def _who_words(frame: Frame, person: str, address: str) -> str:
    name = _name(frame, person) or _name(frame, address)
    return f"« {name} »" if name else phrase("expression.person.unnamed")


@PROJECTS.propose(kinds=[Kind.INITIATIVE], reasons={c.SHARE: (0.0, 10.0)},
                  reads=[identity_c.OWNERS, identity_c.IS_OWNER, social_c.CLOSENESS, identity_c.HANDLES,
                         identity_c.REACHABLE, presence_c.PRESENT, identity_c.IDENTITY])
def _share(s: ProjectsState, frame: Frame) -> list[Candidate]:
    """Raconter ce qu'elle a mené à bout (mode Mika, à la mesure du lien) ; en mode impersonnel, un compte rendu
    factuel à qui l'a confié. Un point quand le travail se pose, pas un message par objectif coché : le récit dit
    tout ce qui a été mené à bout depuis le précédent, sous le sujet du dernier fini. Le brief dit ce qui la pousse,
    pas combien en dire : ce qu'elle en sait est déjà à la mesure du lien (la section du sujet, ``share``) — ADR
    0154."""
    pm = params(frame.env.params_of("projects", frame.root))
    out, seen = [], set()
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
            _person, address, level = chosen
            brief = phrase("projects.brief.share")
        else:
            reader = _reader(p, frame)
            if reader is None:
                continue
            _person, address = reader
            level = FULL
            brief = phrase("projects.brief.report")
        if address in seen:  # un récit à la fois par personne : les autres projets suivront (une seule envie)
            continue
        seen.add(address)
        out.append(Candidate(
            Kind.INITIATIVE, address, c.SHARE, pm.share_evidence, resources=frozenset({floor(address)}),
            args=FrozenDict({"brief:projects": brief, "subject": subject_of(p.id, told[-1].id), "share": level})))
    return out


def plan_reader(p: Project, frame: Frame) -> tuple[str, str] | None:
    """À qui dire son plan : qui a demandé le projet (s'il s'occupe d'elle), sinon une propriétaire — et où."""
    candidates = [x for x in (p.asked_by, p.owner) if x]
    candidates += [o for o in frame.get(identity_c.OWNERS) if o not in candidates]
    for person in candidates:
        if frame.get(identity_c.IS_OWNER(person)):
            address = _address(frame, person)
            if address is not None:
                return person, address
    return None


def plan_due(p: Project, now: int, pm: Any) -> str:
    """Son plan est-il à dire maintenant (ADR 0145) ? ``ask`` (la première fois), ``remind`` (une fois, un jour sans
    réponse à un plan qui attend), ``""`` sinon."""
    if p.status != c.ACTIVE or not p.plan_at or not p.plan_tell or p.plan_state not in (c.PROPOSED, c.PLANNED):
        return ""
    if not p.plan_asked:
        return "ask" if p.plan_attempts < pm.share_attempts else ""
    if p.plan_state == c.PROPOSED and not p.plan_reminded and now - p.plan_asked_at >= DAY:
        return "remind"
    return ""


@PROJECTS.propose(kinds=[Kind.INITIATIVE], reasons={c.PLAN: (0.0, 10.0)},
                  reads=[identity_c.OWNERS, identity_c.IS_OWNER, identity_c.HANDLES, identity_c.REACHABLE,
                         presence_c.PRESENT, identity_c.IDENTITY])
def _plan(s: ProjectsState, frame: Frame) -> list[Candidate]:
    """« Voilà comment je vois ça » : son plan, à qui a demandé le projet — ses questions et ce qu'elle recommande
    (il attend sa réponse), ou ce qu'elle va faire (elle s'y met) ; une relance au bout d'un jour sans réponse, une
    seule (ADR 0145). Une demande à la fois par personne, comme ses demandes d'aide."""
    pm = params(frame.env.params_of("projects", frame.root))
    out, seen = [], set()
    for p in sorted(s.projects.values(), key=lambda p: p.id):
        due = plan_due(p, frame.now, pm)
        if not due:
            continue
        reader = plan_reader(p, frame)
        if reader is None:
            continue
        person, address = reader
        if address in seen:
            continue
        seen.add(address)
        who = _who_words(frame, person, address)
        if p.plan_state != c.PROPOSED and p.plan_version > 1:  # un plan revu : ce qui change, et pourquoi
            brief = phrase("projects.brief.plan.changed", who=who)
        elif p.plan_state != c.PROPOSED:
            brief = phrase("projects.brief.plan.start", who=who)
        elif due == "remind":
            brief = phrase("projects.brief.plan.remind", who=who)
        else:
            brief = phrase("projects.brief.plan.ask", who=who)
        out.append(Candidate(
            Kind.INITIATIVE, address, c.PLAN, pm.need_evidence, resources=frozenset({floor(address)}),
            args=FrozenDict({"brief:projects": brief, "subject": plan_subject(p.id), "share": FULL})))
    return out


def _needy(o: Objective, now: int, pm: Any) -> bool:
    """Un objectif pour lequel il lui faut quelqu'un : bloqué depuis peu, ou ouvert avec un besoin dit."""
    if o.asked or o.ask_attempts >= pm.share_attempts:
        return False
    if o.status == c.BLOCKED and o.kind == c.ONCE:
        return now - o.closed_at <= pm.share_within_us
    return o.status == c.OPEN and bool(o.need_ref)


def _stalled(p: Project, now: int, pm: Any) -> bool:
    """Un projet à elle mis en pause par des pannes depuis peu, qu'elle n'a pas encore dit (ADR 0143) — ou un projet
    qu'on lui a demandé et dont le cadrage n'aboutit pas : qui l'a demandé attend son plan (ADR 0161)."""
    return p.status == c.PAUSED and (p.authority == c.SELF or unplanned_stall(p)) and bool(p.stalled_at) \
        and not p.stall_asked and p.stall_attempts < pm.share_attempts and now - p.stalled_at <= pm.share_within_us


def unplanned_stall(p: Project) -> bool:
    """Arrêté pendant son cadrage, faute de plan (pas d'une panne de la machine)."""
    return p.plan_state == c.TO_FRAME and p.frame_silent > 0 and bool(p.stalled_at)


@PROJECTS.propose(kinds=[Kind.INITIATIVE], reasons={c.NEED: (0.0, 10.0)},
                  reads=[identity_c.OWNERS, identity_c.IS_OWNER, identity_c.HANDLES, identity_c.REACHABLE,
                         presence_c.PRESENT, identity_c.IDENTITY])
def _need(s: ProjectsState, frame: Frame) -> list[Candidate]:
    """« J'ai besoin de toi pour… » : un objectif bloque, ou attend quelque chose (une clé, un accord, un outil) — elle
    le dit à qui l'a confié, ou, pour un projet à elle, à qui s'occupe d'elle (une fois, quelques tentatives au
    plus), dans les deux modes. Un projet à elle qui bloquait faute d'un accès ne demandait rien (ADR 0104). Un
    projet à elle arrêté par des pannes se dit de même : « il ne tourne plus, tu peux le relancer ? » — la machine a
    lâché, pas elle (ADR 0143)."""
    pm = params(frame.env.params_of("projects", frame.root))
    out, seen = [], set()
    for p in sorted(s.projects.values(), key=lambda p: p.id):
        o = next((x for x in p.objectives if _needy(x, frame.now, pm)), None) if p.status == c.ACTIVE else None
        if o is None and not _stalled(p, frame.now, pm):
            continue
        reader = _reader(p, frame)
        if reader is None:
            continue
        person, address = reader
        who = _who_words(frame, person, address)
        if o is not None:
            subject, brief = subject_of(p.id, o.id), phrase("projects.brief.need", who=who)
        elif unplanned_stall(p):
            subject, brief = stall_subject(p.id), phrase("projects.brief.unframed", who=who)
        else:
            subject, brief = stall_subject(p.id), phrase("projects.brief.stalled", who=who)
        if address in seen:
            # une demande à la fois par personne : deux projets qui attendent ne font pas une envie double — un
            # message n'en porte qu'une, et la seconde partait huit secondes après la première (sonde du 2026-10-13)
            continue
        seen.add(address)
        out.append(Candidate(
            Kind.INITIATIVE, address, c.NEED, pm.need_evidence, resources=frozenset({floor(address)}),
            args=FrozenDict({"brief:projects": brief, "subject": subject, "share": FULL})))
    return out
