"""Le parcours d'un ticket (ADR 0270) : ses règles, pures.

Un ticket ne reçoit jamais d'étape : il porte des faits (``faculty.Item``), et son étape s'en déduit ici, en un seul
endroit (``stage``). Chaque geste pose un fait — un ``item_changed`` (``stepped``) ou une note du fil qui a une sorte
(``noted`` : sa question, son plan) — et le réducteur comme la projection appliquent ces mêmes règles
(``tracker.changed``, ``tracker._item_noted``).

| Étape | Les faits qui la disent | À qui la main |
|---|---|---|
| proposé | ``proposed`` | le propriétaire |
| non lu | rien d'autre (un autre qu'elle l'a ouvert) | elle |
| en analyse | ``taken_at`` (elle l'a pris — ou elle l'a ouvert elle-même : il naît pris, ADR 0280) | elle |
| en attente de décision | ``asked_at`` (sa question) ou ``dismissal_at`` (elle propose de l'écarter) | le propriétaire |
| en attente de validation | ``plan_seq`` (son plan est dans le fil) | le propriétaire |
| validé, en cours | ``validated_at`` et ``objective`` | elle (le propriétaire si ``stuck``) |
| validé, en attente de PR | les mêmes, et ``pull`` « attendue » (son projet passe par des pull requests, ADR 0274) | elle (le propriétaire si ``stuck``) |
| PR prête, en attente de fusion | les mêmes, et ``pull`` « prête » (ouverte chez l'hôte) | le propriétaire |
| traité, écarté | ``closed`` | personne |

Les retours se déduisent de même : une note d'un autre qu'elle lève sa question (en analyse) ; un plan refusé efface
le plan (en analyse) ; un petit ticket qui dépasse sa borne perd sa validation et garde son plan (en attente de
validation) ; rouvrir un ticket remet tout son parcours à zéro (``reset``) — un ticket fermé que l'état ne garde plus
se redit depuis son étape seule, et les deux côtés doivent retomber sur les mêmes faits.

Ce qu'une validation suppose (ADR 0272, ``stepped``) : elle nomme le plan qu'elle valide (la note qui le porte), et
ne vaut que si c'est encore celui du ticket ; par elle (un petit ticket), elle ne vaut que pour un ticket qui n'a
encore ni objectif ni diff compté et n'a jamais dépassé sa borne (``self_validates``) — ensuite, seul le propriétaire
valide.

La borne d'un petit ticket (``oversize``) et la forme d'un plan (``plan_text``, ``plan_parts``) sont ici aussi. Les
gestes — son outil d'exécution, le processus qui suit l'objectif d'un ticket, la borne mesurée au compte rendu — sont
dans ``triage.py`` ; la validation en conversation et les brouillons, dans ``tracker.py``.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from mika.contracts import projects as c
from mika.faculties.projects.faculty import SMALL_FILES, SMALL_LINES, Item, Project
from mika.vocab.phrasebook import phrase

# ── L'étape, et à qui la main ─────────────────────────────────────────────


def stage(item: Item) -> str:
    """L'étape d'un ticket, déduite de ses faits — le seul endroit qui la dit."""
    if item.closed == c.DROPPED:
        return c.STAGE_DISMISSED
    if item.closed:
        return c.STAGE_TREATED
    if item.proposed:
        return c.STAGE_PROPOSED
    if item.asked_at or item.dismissal_at:
        return c.STAGE_DECISION
    if item.validated_at and item.objective:
        # sur un projet qui passe par des pull requests (ADR 0274), ce que le ticket dit de celle de son objectif :
        # prête (ouverte chez l'hôte, la main est au propriétaire), ou attendue — elle y travaille, ou elle lui est
        # revenue. Sans ce fait : validé, en cours
        if item.pull == c.PULL_READY:
            return c.STAGE_PR_READY
        return c.STAGE_PR_PENDING if item.pull == c.PULL_AWAITED else c.STAGE_WORKING
    if item.plan_seq:
        return c.STAGE_VALIDATION
    return c.STAGE_ANALYSIS if item.taken_at else c.STAGE_UNREAD


#: qui doit agir à chaque étape : elle, le propriétaire du projet, ou personne (un ticket fermé)
HANDS = {
    c.STAGE_PROPOSED: c.ACTOR_OWNER, c.STAGE_UNREAD: c.ACTOR_SELF, c.STAGE_ANALYSIS: c.ACTOR_SELF,
    c.STAGE_DECISION: c.ACTOR_OWNER, c.STAGE_VALIDATION: c.ACTOR_OWNER, c.STAGE_WORKING: c.ACTOR_SELF,
    c.STAGE_PR_PENDING: c.ACTOR_SELF, c.STAGE_PR_READY: c.ACTOR_OWNER, c.STAGE_TREATED: "", c.STAGE_DISMISSED: "",
}
#: les étapes où elle a la main, et celles où le propriétaire l'a
HERS = tuple(st for st, who in HANDS.items() if who == c.ACTOR_SELF)
OWNERS = tuple(st for st, who in HANDS.items() if who == c.ACTOR_OWNER)


def hand(item: Item) -> str:
    """À qui est la main sur ce ticket (``ACTOR_SELF``, ``ACTOR_OWNER``, ``""`` : personne) — son étape le dit ;
    un ticket validé dont l'objectif bloque attend le propriétaire."""
    if item.stuck and item.status in (c.STAGE_WORKING, c.STAGE_PR_PENDING):
        return c.ACTOR_OWNER
    return HANDS.get(item.status, "")


def waits(item: Item) -> bool:
    """Ce ticket attend le propriétaire avant que son objectif reparte : sa question, sa validation."""
    return item.status in (c.STAGE_DECISION, c.STAGE_VALIDATION)


# ── Le parcours en six étapes (ADR 0293) ──────────────────────────────────

#: les six étapes que le propriétaire a données, dans leur ordre : non lu, en analyse, validation, pull request,
#: fusion, traité. Les étapes fines (``stage``) restent : chacune tombe dans l'une des six, dont elle est la précision
STEP_UNREAD, STEP_ANALYSIS, STEP_VALIDATION, STEP_PULL, STEP_MERGE, STEP_TREATED = (
    "unread", "analysis", "validation", "pull", "merge", "treated")
JOURNEY = (STEP_UNREAD, STEP_ANALYSIS, STEP_VALIDATION, STEP_PULL, STEP_MERGE, STEP_TREATED)
#: l'état d'une étape : passée, en cours, à venir, sautée (elle ne vaut pas pour ce ticket)
PASSED, CURRENT, AHEAD, SKIPPED = "done", "current", "todo", "skipped"
#: les deux étapes que saute un ticket qui ne passe pas par une pull request
CODE_STEPS = (STEP_PULL, STEP_MERGE)
#: où tombe chaque étape fine — sauf « validé, en cours », qui dépend du ticket (``step_of``), et « écarté », qui n'est
#: plus sur le parcours
_PLACE = {c.STAGE_PROPOSED: STEP_UNREAD, c.STAGE_UNREAD: STEP_UNREAD, c.STAGE_ANALYSIS: STEP_ANALYSIS,
          c.STAGE_DECISION: STEP_ANALYSIS, c.STAGE_VALIDATION: STEP_VALIDATION, c.STAGE_PR_PENDING: STEP_PULL,
          c.STAGE_PR_READY: STEP_MERGE, c.STAGE_TREATED: STEP_TREATED}


def step_of(fine: str, through_pull: bool) -> str:
    """L'étape du parcours où tombe une étape fine (vide : écarté, il n'y est plus). Proposé, il n'est pas encore
    lu ; sa question posée, il est encore en analyse ; « validé, en cours », elle prépare sa pull request s'il passe
    par là (``through_pull``), sinon il n'attend plus que d'être traité."""
    if fine == c.STAGE_WORKING:
        return STEP_PULL if through_pull else STEP_TREATED
    return _PLACE.get(fine, "")


def through_pull(item: Item, by_pulls: bool) -> bool:
    """Ce ticket passe-t-il par une pull request et sa fusion ? Ouvert : son projet le dit (``by_pulls``, ADR 0274),
    ou il en a déjà une. Fermé : seulement s'il en a eu une — traité sans code (une réponse dans son fil, un projet
    au flux direct) ou écarté, il a sauté ces deux étapes."""
    had = bool(item.pull_number) or item.pull != c.PULL_NONE
    return had if item.closed else by_pulls or had


@dataclass(frozen=True, slots=True)
class Journey:
    """Le parcours d'un ticket en six étapes : chacune avec son état (``PASSED``, ``CURRENT``, ``AHEAD``,
    ``SKIPPED``), celle où il est (vide : fermé), s'il passe par une pull request (sinon ``CODE_STEPS`` sont
    sautées), et comment il a fini (vide : ouvert ; traité ; écarté)."""

    steps: tuple[tuple[str, str], ...]
    current: str = ""
    through_pull: bool = True
    ended: str = ""


def journey(item: Item, by_pulls: bool = False) -> Journey:
    """Le parcours en six étapes d'un ticket, déduit de son étape fine et de ses faits — le seul endroit qui le dit
    (ADR 0293). Ouvert : ce qui précède son étape est passé, ce qui suit est à venir. Fermé : une étape n'est passée
    que si un fait le dit (pris, son plan validé, une pull request) ; les autres sont sautées — un ticket écarté
    saute aussi « traité »."""
    coded = through_pull(item, by_pulls)
    if not item.closed:
        at = step_of(item.status, coded) or STEP_UNREAD
        here = JOURNEY.index(at)
        steps = tuple((step, SKIPPED if step in CODE_STEPS and not coded else
                       PASSED if n < here else CURRENT if n == here else AHEAD) for n, step in enumerate(JOURNEY))
        return Journey(steps, at, coded)
    treated = item.closed != c.DROPPED
    reached = {STEP_UNREAD: True, STEP_ANALYSIS: bool(item.taken_at or item.plan_seq or item.validated_at),
               STEP_VALIDATION: bool(item.validated_at), STEP_PULL: coded, STEP_MERGE: coded and treated,
               STEP_TREATED: treated}
    return Journey(tuple((step, PASSED if reached[step] else SKIPPED) for step in JOURNEY), "", coded,
                   c.STAGE_TREATED if treated else c.STAGE_DISMISSED)


# ── Les faits qu'un geste pose ────────────────────────────────────────────


def reset(item: Item) -> Item:
    """Un ticket rouvert repart de rien : ni pris, ni question, ni plan, ni validation, ni objectif. Il garde son
    issue (ADR 0275) : un ticket ne se publie qu'une fois."""
    return replace(item, taken_at=0, asked_at=0, dismissal_at=0, plan_seq=0, small=False, validated_at=0,
                   validated_by="", stuck=False, objective=0, diff_files=0, diff_lines=0, outgrown=False,
                   pull=c.PULL_NONE, pull_number=0)


def self_validates(item: Item) -> bool:
    """Peut-elle valider elle-même le plan de ce ticket (un petit ticket, ADR 0270) ? Seulement s'il n'a encore ni
    objectif ni diff compté, et n'a jamais dépassé sa borne (ADR 0272) : un second plan « petit » écrit après un
    dépassement ne se revalide pas seul — le propriétaire le valide."""
    return not (item.objective or item.diff_files or item.diff_lines or item.outgrown)


def validates(item: Item, d: Any, by: str) -> bool:
    """Cette validation vaut-elle pour ce ticket ? Il a un plan pas encore validé, et l'objectif qui le portera
    (celui que ce changement pose, ou celui qu'il a déjà) ; elle nomme le plan qu'elle valide, et c'est encore le
    sien (``plan`` : 0, un journal d'avant, ne nomme rien) ; par elle, seulement tant qu'elle le peut
    (``self_validates``)."""
    if not (d.validated and item.plan_seq and not item.validated_at):
        return False
    if not (item.objective or (d.objective or 0) > 0):
        return False
    if d.plan and d.plan != item.plan_seq:
        return False
    return by != c.BY_SELF or self_validates(item)


def stepped(item: Item, d: Any, at: int, by: str) -> tuple[Item, list[str]]:
    """Le ticket après les faits de parcours que porte ce changement (``tracker.ItemChanged``), et leurs codes. Un
    ticket fermé ou proposé n'a pas de parcours : rien ne change. Chaque fait a sa condition — le réducteur reste
    total, et un geste arrivé trop tard ne fait rien."""
    new, what = item, []
    if new.closed or new.proposed:
        return new, what
    if d.taken and not new.taken_at:
        new = replace(new, taken_at=at)
        what.append("taken")
    if d.dismissal and not new.dismissal_at and not new.validated_at:
        new = replace(new, dismissal_at=at, taken_at=new.taken_at or at)
        what.append("dismissal")
    if validates(new, d, by):
        # un plan ne se valide qu'avec l'objectif qui le porte : celui que ce changement pose, ou celui qu'il a déjà
        new = replace(new, validated_at=at, validated_by=by, asked_at=0, dismissal_at=0)
        what.append("validated")
    elif d.refused and new.plan_seq and not new.validated_at:
        # le plan refusé s'efface, et l'objectif qu'un petit ticket avait déjà aussi : elle le reprend en analyse
        new = replace(new, plan_seq=0, small=False, asked_at=0, dismissal_at=0, objective=0, stuck=False)
        what.append("refused")
    if d.stuck is not None and new.validated_at and new.objective and bool(d.stuck) != new.stuck:
        new = replace(new, stuck=bool(d.stuck))
        what.append("stuck" if new.stuck else "unstuck")
    if new.validated_at and d.measured:
        # le diff entier de sa branche face à sa base (ADR 0274) : la mesure remplace, elle ne s'ajoute pas
        new = replace(new, diff_files=max(0, d.diff_files), diff_lines=max(0, d.diff_lines))
    elif new.validated_at and (d.diff_files > 0 or d.diff_lines > 0):  # ce qu'une exécution de son objectif a changé
        new = replace(new, diff_files=new.diff_files + max(0, d.diff_files),
                      diff_lines=new.diff_lines + max(0, d.diff_lines))
    if d.pull in c.PULLS and new.validated_at and (new.objective or (d.objective or 0) > 0) and \
            (d.pull, d.pull_number or new.pull_number) != (new.pull, new.pull_number):
        # ce qu'il dit de la pull request de son objectif (ADR 0274) : attendue, prête, fusionnée — ou plus rien
        # (son projet ne passe plus par là)
        new = replace(new, pull=d.pull, pull_number=d.pull_number or new.pull_number)
        what.append(f"pull:{d.pull or 'none'}")
    if d.outgrown and new.validated_at and new.small:
        # pris comme petit, il ne l'était pas : sa validation tombe, son plan et son objectif restent — et il garde
        # le fait d'avoir dépassé sa borne : elle ne le revalidera pas elle-même
        new = replace(new, validated_at=0, validated_by="", small=False, stuck=False, outgrown=True,
                      pull=c.PULL_NONE)
        what.append(f"outgrown:{d.outgrown}")
    return new, what


def coherent(item: Item) -> Item:
    """Sans objectif, pas de validation : un plan validé dont l'objectif a été retiré est à refaire (en analyse)."""
    if item.validated_at and not item.objective:
        return replace(item, validated_at=0, validated_by="", plan_seq=0, small=False, stuck=False,
                       pull=c.PULL_NONE, pull_number=0)
    return item


def measured(before: Item, after: Item) -> bool:
    """Ce que les exécutions de son objectif ont changé a bougé (un fait compté, sans code de changement)."""
    return (before.diff_files, before.diff_lines) != (after.diff_files, after.diff_lines)


def noted(item: Item, d: Any, at: int, seq: int) -> Item:
    """Le ticket après une note de son fil (``tracker.ItemNoted``). Une note à elle qui a une sorte pose un fait :
    sa question (elle attend une réponse), son plan (il attend sa validation — et remplace le précédent, tant qu'il
    n'est pas validé). Une note d'un autre qu'elle est la réponse à ce qu'elle attendait : sa question, ou sa
    proposition de l'écarter — sauf un commentaire venu de l'hôte, qui ne répond à rien (ADR 0275). Un ticket fermé
    ou proposé ne change pas."""
    if item.list_name != c.TICKETS or item.closed or item.proposed:
        return item
    if d.author == c.BY_HOST:
        # un commentaire fait chez l'hôte (ADR 0275) est le mot d'un inconnu : il ne lève pas une question posée au
        # propriétaire, et ne répond à rien
        return item
    if d.author != c.BY_SELF:
        return replace(item, asked_at=0, dismissal_at=0) if item.asked_at or item.dismissal_at else item
    if d.kind == c.NOTE_QUESTION:
        return replace(item, asked_at=at, taken_at=item.taken_at or at)
    if d.kind == c.NOTE_PLAN and not item.validated_at:
        return replace(item, plan_seq=seq, small=bool(d.small), taken_at=item.taken_at or at, asked_at=0,
                       dismissal_at=0)
    return item


# ── La forme d'un plan ────────────────────────────────────────────────────

#: les jalons d'un plan, au plus, et la longueur de chacun : du texte dans le fil du ticket, puis — son plan validé —
#: les jalons de l'objectif qui en naît (ADR 0273), d'où leur nombre
STEPS_MAX, STEP_MAX = c.MILESTONES_MAX, 200
PLAN_PART_MAX = 500
#: un jalon tel que ``plan_text`` l'écrit : « 2. Le corriger »
_STEP = re.compile(r"^\d+\. (.+)$")


def _line(text: str) -> str:
    return " ".join((text or "").split())


def plan_text(changes: str, where: str, steps: Iterable[str], untouched: str, small: bool) -> str:
    """Le plan d'un ticket, tel qu'il s'écrit dans son fil : d'abord ce qu'elle va changer et où (ce qui deviendra
    le texte de l'objectif), puis, après une ligne vide, ses jalons, ce qu'elle ne touchera pas et si elle le juge
    petit (ce qui deviendra son critère)."""
    head = phrase("projects.tickets.plan.head", changes=_line(changes), where=_line(where)) if _line(where) else \
        _line(changes)
    rest = []
    kept = [_line(x)[:STEP_MAX] for x in steps if _line(x)][:STEPS_MAX]
    if kept:
        rest.append(phrase("projects.tickets.plan.steps") + "\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(kept, 1)))
    if _line(untouched):
        rest.append(phrase("projects.tickets.plan.untouched", text=_line(untouched)))
    rest.append(phrase("projects.tickets.plan.small") if small else phrase("projects.tickets.plan.large"))
    return head + "\n\n" + "\n".join(rest)


def plan_parts(text: str) -> tuple[str, str]:
    """Un plan relu : (ce qu'elle va changer et où, ses jalons et ses limites)."""
    head, _, rest = (text or "").strip().partition("\n\n")
    return head.strip(), rest.strip()


def plan_steps(text: str) -> tuple[str, ...]:
    """Les jalons d'un plan relu, dans leur ordre (ADR 0273) : les lignes numérotées que ``plan_text`` a écrites
    sous son titre des jalons — ce qui devient les jalons de l'objectif quand le plan est validé. Un plan sans
    jalons, ou qui ne se lit plus : aucun."""
    rows = plan_parts(text)[1].split("\n")
    head = phrase("projects.tickets.plan.steps")
    if head not in rows:
        return ()
    out: list[str] = []
    for row in rows[rows.index(head) + 1:]:
        found = _STEP.match(row)
        if found is None:
            break
        out.append(found.group(1).strip())
    return tuple(out[:STEPS_MAX])


# ── La borne d'un petit ticket ────────────────────────────────────────────

#: les fichiers de dépendances et leurs verrous : y toucher n'est jamais petit (comparés au nom du fichier, sans
#: casse). Les verrous se reconnaissent à leur forme (``*.lock``, ``*-lock.*``, ``*.lockfile``), pas à une liste
DEPENDENCY_FILES = (
    "pyproject.toml", "requirements*.txt", "requirements*.in", "constraints*.txt", "constraints*.in", "setup.py",
    "setup.cfg", "pipfile", "environment*.yml", "environment*.yaml", "conda*.yml", "conda*.yaml", "package.json",
    "npm-shrinkwrap.json", "cargo.toml", "go.mod", "go.sum", "go.work", "gemfile", "*.gemspec", "composer.json",
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "*.csproj", "*.fsproj",
    "directory.packages.props", "pubspec.yaml", "mix.exs", "deno.json", "deno.jsonc",
    "*.lock", "*-lock.json", "*-lock.yaml", "*-lock.yml", "*.lockb", "*.lockfile", "*.lock.json",
)
#: les dossiers où l'on range ses dépendances par environnement (``requirements/base.txt``) : tout fichier de
#: ces sortes y est un fichier de dépendances, quel que soit son nom
DEPENDENCY_FOLDERS = ("requirements", "constraints")
DEPENDENCY_SUFFIXES = (".txt", ".in", ".pip")
#: pourquoi un ticket n'est pas petit (les clés de ``projects.tickets.oversize`` dans sa voix)
FILES, LINES, DEPENDENCIES, PROTECTED = "files", "lines", "dependencies", "protected"


@dataclass(frozen=True, slots=True)
class Bounds:
    """La borne d'un petit ticket : des fichiers et des lignes changées au plus, et les fichiers protégés."""

    files: int = SMALL_FILES
    lines: int = SMALL_LINES
    protected: tuple[str, ...] = ()


def bounds(p: Project) -> Bounds:
    """La borne de ce projet : la sienne, sinon celle par défaut."""
    return Bounds(p.small_files or SMALL_FILES, p.small_lines or SMALL_LINES, p.protected)


def touched(pending: Iterable[str]) -> tuple[str, ...]:
    """Les chemins qu'une exécution a changés, tels que l'atelier les dit avant de les enregistrer : chacun une
    fois, un renommage (« avant -> après ») compté pour ses deux chemins."""
    out: list[str] = []
    for raw in pending:
        out += [x.strip().strip('"') for x in str(raw).split(" -> ") if x.strip().strip('"')]
    return tuple(dict.fromkeys(out))


def _matches(path: str, patterns: Sequence[str], *, names_only: bool = False) -> bool:
    """Ce chemin tombe-t-il sous un de ces motifs — par son nom, par son chemin entier, ou sous un dossier nommé ?"""
    name = path.rsplit("/", 1)[-1]
    for raw in patterns:
        pattern = raw.strip().removeprefix("./")
        if not pattern:
            continue
        if fnmatch.fnmatchcase(name, pattern):
            return True
        if names_only:
            continue
        folder = pattern.rstrip("/")
        if fnmatch.fnmatchcase(path, pattern) or path == folder or path.startswith(folder + "/"):
            return True
    return False


def dependency(path: str) -> bool:
    """Ce chemin est-il un fichier de dépendances ou un verrou ? Par son nom (sans casse), ou par le dossier où il
    est rangé (``requirements/base.txt``)."""
    lowered = path.strip().lower()
    if _matches(lowered, DEPENDENCY_FILES, names_only=True):
        return True
    *folders, name = lowered.split("/")
    return any(x in DEPENDENCY_FOLDERS for x in folders) and name.endswith(DEPENDENCY_SUFFIXES)


def oversize(paths: Sequence[str], files: int, lines: int, b: Bounds) -> str:
    """Pourquoi ce ticket n'est pas petit, ou ``""``. ``paths`` : ce que cette exécution a changé ; ``files`` et
    ``lines`` : ce que les exécutions de son objectif ont changé en tout, elle comprise."""
    if any(dependency(x) for x in paths):
        return DEPENDENCIES
    if any(_matches(x, b.protected) for x in paths):
        return PROTECTED
    if files > b.files:
        return FILES
    return LINES if lines > b.lines else ""
