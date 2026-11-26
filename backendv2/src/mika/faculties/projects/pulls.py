"""Les pull requests d'un projet (ADR 0274) : leurs faits, ce qui les propose, les ouvre et les relit.

Un projet au flux ``pr`` (``faculty.by_pulls``) travaille **une branche par travail** : l'atelier s'y place au départ
de chaque exécution (l'enrichisseur ``projects_tree`` de ``prompt.py``), ``report_run`` s'y replace avant
d'enregistrer (``tools.py``), et sa branche de base ne reçoit que ce qui est récupéré du distant. Leur forme (les
champs d'``Objective``) et les lectures que tous en font sont dans ``faculty.py``. Ici :

- **Leurs faits** (ADR 0313) : ``projects.pull_seen`` (ce que l'hôte dit de la pull request), ``projects.checks_seen``
  (de ses vérifications), ``projects.base_seen`` (la base de l'atelier, relue), leurs charges utiles et leurs
  réducteurs. Fusionnée, l'objectif est clos pour de bon (``_accepted``) ; refusée, en conflit, ses vérifications en
  échec, un ponctuel abouti se rouvre (``faculty.sent_back``, que la relecture lit aussi) ; la base qui avance
  éveille un lecteur (``faculty.with_base``, que lit aussi le compte rendu d'une exécution en flux direct).

- **La proposition** (le processus ``projects.pulls``, ``due``) : quand un ponctuel a conclu « fait », ou qu'un
  passage de constant s'est achevé, sur une branche qui porte un commit que sa pull request n'a pas, la pull request
  se propose — sur accord selon le projet. Trois essais en échec au plus, puis elle attend un nouveau commit.
- **La capacité** ``projects.pull_request`` : elle pousse la branche de travail, puis l'ouvre chez l'hôte
  (``RepoHost.open_pull`` : une déjà ouverte est retrouvée, jamais doublée). **Jamais la base, jamais une fusion** :
  ni cette capacité ni aucune autre n'en a le moyen.
- **Son texte** (``compose``) sort de la machine : neutre comme un message de commit. Il se compose au moment de
  l'aperçu et au moment de partir, à partir de l'état — les arguments de la proposition ne portent aucun texte, ce
  que l'oubli efface n'y reste donc pas. Les jalons cités (``milestones.cited``) n'y entrent que si un accord est
  requis (le propriétaire lit ce qui part), et une ligne qui nomme une personne du projet se réduit à son état.
  L'accord épingle le tout : si le texte ou la branche ont changé depuis, rien ne part.
- **La base** (le même processus, ``unread_bases``, ADR 0280) : après chaque récupération aboutie, il relit dans
  l'atelier le commit au bout de la branche de base et le pose (``projects.base_seen``). Une base qui a avancé — la
  fusion acceptée d'une pull request, ou ce qu'un autre a poussé chez l'hôte — est ce qu'un projet lecteur peut
  enfin voir : c'est elle qui éveille ``project:<n>:commit``, jamais le commit d'une branche de travail.
- **Le suivi** (le même processus, ``tracked``) : chaque pull request ouverte est relue chez l'hôte, dix minutes au
  moins entre deux lectures, et ce qui a changé devient un fait (``projects.pull_seen``). Ce que l'hôte en dit est le
  texte d'un inconnu : un contenu effaçable, cité à l'exécution dans une section non fiable (``project_pull``).
  Seul qui a un rôle sur le dépôt y demande ou y lève des changements (ADR 0278) : le port ne rend que leurs
  relectures (``Pull.review``) ; le mot d'un compte sans rôle se cite, dit comme tel, et ne rouvre rien. Une pull
  request que l'hôte ne sait pas dire — il est en panne, il ne la connaît pas encore — se redemande à un rythme
  qui s'allonge (``retry_in``), plafonné.
- **Ses vérifications** (ADR 0275, ``checked``) : dans la même passe, pour le commit de la pull request, l'hôte dit
  où en est sa CI — un fait de plus (``projects.checks_seen``). Un échec rouvre l'objectif une fois par commit en
  échec, la fin du journal gardée comme le mot de l'hôte : citée, jamais une consigne. L'outil ``checks_log`` la
  relit. Un dépôt sans CI, ou des vérifications qui ne se lisent pas, ne bloquent rien.
- **Sa relecture** (ADR 0276, ``reread``) : entre ``due`` et ``proposal``. Quand le projet en demande une, la
  proposition n'a lieu qu'avec un verdict favorable pour le commit au bout de la branche ; sans lui, la passe demande
  la relecture de ce commit-là (``projects.review_asked``) — une fois —, et ``compose`` refuse ce qui n'a pas été
  relu. L'aperçu porte le verdict : qui a relu, quel commit.
- **Où elle en est, pour qui la regarde** (``pull_stage`` : proposée, ouverte, prête à fusionner, fusionnée,
  fermée), celles d'un projet (``pulled``, ``pull_order``) et ce qui en nomme une dans une adresse (``pull_key``,
  ``pull_named``) : des règles pures, que lisent l'onglet Code de la console (``inspect_code.py``) et l'API par
  personne.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.faculties.projects import merge, milestones, tracker
from mika.faculties.projects.atelier import SEEN_KEY, commits_listed
from mika.faculties.projects.capability_common import effect_project, hosted_remote, pin_of, project_refusal
from mika.faculties.projects.faculty import (
    BASE_REQUEST,
    INHERITED,
    PROJECTS,
    PULL_REQUEST_CAPABILITY,
    PULL_TRIES_MAX,
    REFRAMED,
    WORK_PREFIX,
    Objective,
    Project,
    ProjectsState,
    by_pulls,
    concluded,
    handed_over,
    inherited_for,
    milestones_of,
    objective_at,
    objective_of,
    repo_page,
    rereads,
    review_holds,
    sent_back,
    subjects_of,
    ticket_held,
    with_base,
    with_objective,
    with_project,
    writes_pulls,
    written_for,
)
from mika.faculties.projects.inspect_pulls import CANNOT, DESCRIPTION, OPENED, PREVIEW, SUMMARY
from mika.faculties.projects.inspect_reviews import UNREVIEWED, review_line
from mika.faculties.projects.merge import MERGE_ANSWERED
from mika.faculties.projects.review import REVIEW_ASKED, REVIEWED
from mika.faculties.projects.tool_common import gone_reply, running_project
from mika.faculties.projects.tools import TAKE_BASE
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.events import Content, Draft, Payload
from mika.kernel.faculty import CatchUp, ToolResult, Zone
from mika.kernel.frame import Frame
from mika.kernel.operate import Preview
from mika.kernel.prompt import SectionBody
from mika.kernel.text import clipped
from mika.ports.workshop import (
    BASE_BRANCH,
    CHECKS_FAILED,
    CHECKS_PASSED,
    CHECKS_PENDING,
    CHECKS_STATES,
    PULL_CLOSED,
    PULL_MERGED,
    PULL_OPEN,
    PULL_STATES,
    REVIEW_CHANGES,
    Pull,
    Span,
    describe,
)
from mika.vocab.episodes import PROJECT_KINDS, project_of, project_target
from mika.vocab.phrasebook import family, phrase

RUNS = list(PROJECT_KINDS)
#: entre deux lectures de l'hôte, au moins ; et l'écart minimal entre deux passes qui ont encore à faire
POLL_US = 10 * MINUTE
RETRY_US = MINUTE
#: une pull request que l'hôte n'a encore jamais su dire : l'écart avant de la redemander double à chaque lecture
#: sans réponse, jusqu'à ce plafond (ADR 0278) — pas une demande par minute tant qu'il est en panne
RETRY_MAX_US = HOUR
#: ce qu'une exécution lit, au plus, de ce que l'hôte dit de sa pull request (caractères)
SAID_SHOWN = 800
#: les fichiers qu'un aperçu nomme, au plus
FILES_SHOWN = 30
#: ce qu'on garde, au plus, de ce que l'hôte dit d'un échec de ses vérifications — leurs noms, puis la fin du
#: journal (caractères) ; ce que l'outil ``checks_log`` en rend
CHECKS_SAID_MAX, LOG_SHOWN = 1500, 3000

# ── Ce qui est dû ─────────────────────────────────────────────────────────


def due(s: ProjectsState) -> list[tuple[Project, Objective]]:
    """Les objectifs dont la pull request est à proposer : leur travail est conclu sur une branche qui porte un
    commit que leur pull request n'a pas, rien n'est déjà proposé, et les essais ne sont pas épuisés."""
    out = []
    for p in sorted(s.projects.values(), key=lambda p: p.id):
        if p.status == c.ARCHIVED or not by_pulls(p):
            continue
        out += [(p, o) for o in p.objectives if o.branch and o.unsent and concluded(o) and not o.pull_proposal
                and o.pull_tries < PULL_TRIES_MAX]
    return out


def tracked(s: ProjectsState) -> list[tuple[Project, Objective]]:
    """Les pull requests à relire chez l'hôte : celles qui y sont ouvertes."""
    out = []
    for p in sorted(s.projects.values(), key=lambda p: p.id):
        if p.status == c.ARCHIVED or not by_pulls(p):
            continue
        out += [(p, o) for o in p.objectives if o.branch and o.pull_state == PULL_OPEN]
    return out


def unread_bases(s: ProjectsState) -> list[Project]:
    """Les projets dont une récupération vient d'aboutir sans que leur base ait été relue (ADR 0280)."""
    return [p for p in sorted(s.projects.values(), key=lambda p: p.id) if p.base_unread]


def retry_in(failed: int) -> int:
    """L'écart avant de redemander à l'hôte une pull request qu'il n'a encore jamais su dire, après ``failed``
    lectures de suite sans réponse : une minute, puis le double à chaque fois, une heure au plus."""
    return min(RETRY_US << min(max(0, failed - 1), 16), RETRY_MAX_US) if failed > 0 else RETRY_US


def pull_url(p: Project, o: Objective) -> str:
    """La page de sa pull request chez l'hôte, composée du dépôt et de son numéro (jamais reprise d'une réponse)."""
    return f"{repo_page(p)}/pull/{o.pull}" if p.remote and o.pull else ""


# ── Où elle en est, pour qui la regarde ───────────────────────────────────

#: où en est une pull request, pour qui la regarde : proposée (elle attend un accord avant de partir), ouverte,
#: prête à fusionner, fusionnée, fermée
PROPOSED, OPEN, READY, MERGED, CLOSED = "proposed", "open", "ready", "merged", "closed"
PULL_ORDER = {READY: 0, OPEN: 1, PROPOSED: 2, MERGED: 3, CLOSED: 4}


def pull_stage(p: Project, o: Objective) -> str:
    """Où en est la pull request de cet objectif : proposée, ouverte, prête à fusionner (rien ne la retient,
    ``merge.blocked``), fusionnée, fermée."""
    if o.pull_state == PULL_MERGED:
        return MERGED
    if o.pull_state == PULL_CLOSED:
        return CLOSED
    if o.pull_state != PULL_OPEN:
        return PROPOSED
    return OPEN if merge.blocked(p, o) else READY


def pulled(p: Project) -> list[Objective]:
    """Ses objectifs qui ont une pull request — proposée, ouverte, fusionnée ou fermée."""
    return [o for o in p.objectives if o.pull_state or o.pull or o.pull_proposal] if by_pulls(p) else []


def pull_key(o: Objective) -> str:
    """Ce qui nomme une pull request dans une adresse : son numéro, ou ``o<objectif>`` quand elle n'en a pas encore."""
    return str(o.pull) if o.pull else f"o{o.id}"


def pull_named(p: Project, key: str) -> Objective | None:
    """La pull request qu'une adresse nomme (``pull_key``)."""
    key = (key or "").strip()
    if key.isdecimal():
        return next((o for o in pulled(p) if o.pull == int(key)), None)
    if key[:1] == "o" and key[1:].isdecimal():
        return next((o for o in pulled(p) if o.id == int(key[1:]) and not o.pull), None)
    return None


def pull_order(p: Project) -> list[Objective]:
    """Ses pull requests, les prêtes d'abord, puis les ouvertes, les proposées, les fusionnées et les fermées ; les plus
    récentes d'abord dans chacune."""
    return sorted(pulled(p), key=lambda o: (PULL_ORDER[pull_stage(p, o)], -o.pull_at, -o.id))


# ── Sa relecture, avant de la proposer ────────────────────────────────────

#: ce que la relecture dit d'un commit à proposer : il part ; une relecture est à demander ; elle est en route, ou
#: l'a refusé — rien à faire d'ici
PASS, ASK, WAIT = "pass", "ask", "wait"


def reread(p: Project, o: Objective, head: str) -> str:
    """Où en est la relecture du commit au bout de la branche d'un objectif (ADR 0276). Le projet n'en demande
    pas : il part. Un verdict favorable ne vaut que pour ce commit-là — si la branche a bougé depuis, il ne vaut
    plus, et une relecture se demande pour le nouveau. Jamais deux pour le même commit : ni celui qu'on attend
    déjà, ni celui qu'une relecture a refusé ; et aucune quand la main est au propriétaire."""
    if not rereads(p, o) or review_holds(o, head):
        return PASS
    if head in (o.review_due, o.reviewed) or handed_over(o):
        return WAIT
    return ASK


def parked(p: Project, o: Objective) -> bool:
    """La proposition de cet objectif attend-elle sa relecture sans que la passe ait rien à y faire ? Son dernier
    commit a sa relecture demandée, ou refusée, ou la main est au propriétaire : un verdict, ou un nouveau commit,
    réveillera la passe — elle ne relit pas l'atelier chaque minute en attendant."""
    if not rereads(p, o) or not o.commit or review_holds(o, o.commit):
        return False
    return handed_over(o) or o.commit in (o.review_due, o.reviewed)


# ── Son texte : ce qui sort de la machine ─────────────────────────────────


def named(frame: Frame | None, p: Project, o: Objective | None = None, more: Sequence[str] = ()) -> tuple[str, ...]:
    """Les noms qu'un texte qui sort ne porte pas : ceux des personnes du projet — pour qui il est, de qui il parle,
    celles des projets qu'il lit, qui s'occupe d'elle, qui a validé un des jalons de l'objectif ``o`` ; et ``more``,
    d'autres personnes (leurs clés) — celles d'un ticket (ADR 0278)."""
    if frame is None:
        return ()
    people = {*subjects_of(p), *(frame.get(identity_c.OWNERS) or ()), *(m.reached_by for m in milestones_of(o)),
              *more}
    names = {identity_c.person_name(frame, who) for who in people if who and who not in (c.BY_SELF, c.BY_OPERATOR)}
    return tuple(sorted(n for n in names if len(n) >= 2))


def names_someone(text: str, names: Sequence[str]) -> bool:
    """Ce texte porte-t-il un de ces noms, en entier (sans casse) ?"""
    low = text.casefold()
    return any(re.search(rf"(?<!\w){re.escape(n.casefold())}(?!\w)", low) for n in names)


def title_of(o: Objective) -> str:
    """Le titre d'une pull request : des numéros, comme un message de commit."""
    if o.kind == c.CONSTANT:
        return phrase("projects.pull.text.title_round", objective=o.id, round=o.pulls_merged + 1)
    if o.ticket:
        return phrase("projects.pull.text.title_ticket", objective=o.id, ticket=o.ticket)
    return phrase("projects.pull.text.title", objective=o.id)


def body_of(o: Objective, branch: str, span: Span, cited: Sequence[str] | None, names: Sequence[str]) -> str:
    """Le texte d'une pull request. ``cited`` : ses jalons avec leur preuve (``milestones.cited``), ou ``None`` quand
    personne ne lira ce texte avant qu'il parte — chaque jalon n'y est alors que son numéro et son état, comme toute
    ligne qui nommerait une personne du projet."""
    rows = [phrase("projects.pull.text.head", objective=o.id, branch=branch)]
    if o.ticket:
        rows.append(phrase("projects.pull.text.ticket", ticket=o.ticket))
    alive = milestones_of(o)
    if alive:
        states = family("projects.milestones.states")
        rows += ["", phrase("projects.pull.text.milestones")]
        for i, m in enumerate(alive):
            line = cited[i] if cited is not None and i < len(cited) else ""
            bare = phrase("projects.pull.text.milestone_bare", id=m.id, state=states.get(m.status, m.status))
            rows.append("- " + (line if line and not names_someone(line, names) else bare))
    rows += ["", phrase("projects.pull.text.span", files=len(span.files), insertions=span.insertions,
                        deletions=span.deletions, commits=len(span.commits)),
             "", phrase("projects.pull.text.foot")]
    return "\n".join(rows)


@dataclass(frozen=True, slots=True)
class Made:
    """Une pull request telle qu'elle partirait maintenant : son titre, son texte, ce que sa branche change, les
    jalons et leurs preuves (ce que le propriétaire en voit), et le condensé qui épingle le tout."""

    title: str
    body: str
    span: Span
    cited: tuple[str, ...]
    ticket: str
    digest: str
    #: ce que la relecture indépendante a dit du commit qui part (ADR 0276) : qui a relu, quel commit
    review: str = ""


async def compose(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Made | str:
    """La pull request que ces arguments ouvriraient, composée maintenant à partir de l'état — ou pourquoi elle ne
    peut pas partir. Les arguments ne portent que des numéros, des branches et un commit."""
    frame = ports["frame"]() if "frame" in ports else None
    port, store = ports.get("workshop"), ports.get("store")
    pid, oid = args.get("project"), args.get("objective")
    p = frame.state("projects").projects.get(pid) if frame is not None and isinstance(pid, int) else None
    o = objective_at(p, oid) if p is not None and isinstance(oid, int) else None
    if p is None or o is None or port is None:
        return CANNOT["missing"]
    url, base, head = str(args.get("url") or ""), str(args.get("base") or ""), str(args.get("head") or "")
    if not by_pulls(p) or url != p.remote or base != p.branch:
        return CANNOT["moved"]
    if not head.startswith(WORK_PREFIX) or head in (base, BASE_BRANCH):
        return CANNOT["not_work"]
    span = await port.span(p.id, head)
    if span is None or not span.commits:
        return CANNOT["empty"]
    sha = str(args.get("sha") or "")
    if sha and span.head != sha:
        return CANNOT["shifted"]
    if reread(p, o, span.head) != PASS:
        return UNREVIEWED  # rien ne sort sans verdict quand le projet le demande (ADR 0276)
    texts = store.content(milestones.refs(o)) if store is not None else {}
    cited = tuple(milestones.cited(o, texts))
    title = title_of(o)
    body = body_of(o, head, span, cited if args.get("full") else None, named(frame, p, o))
    item = ticket_held(p, o)
    ticket = ""
    if item is not None:
        said = store.content([item.title_ref]).get(item.title_ref, "") if store is not None and item.title_ref else ""
        ticket = PREVIEW["ticket"].format(number=item.number, title=clipped(said, 120) or PREVIEW["forgotten"],
                                          stage=tracker.status_words(c.TICKETS, item.status))
    return Made(title, body, span, cited, ticket,
                pin_of(url=url, base=base, head=head, sha=span.head, title=title, body=body),
                review_line(p, o, span.head))


# ── La capacité ───────────────────────────────────────────────────────────

async def pull_request_preview(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Preview | None:
    """Exactement ce qui partirait : la branche et le commit, le titre, le texte, les jalons et leurs preuves, le
    ticket traité, l'étendue du diff face à la base. Le condensé épingle le commit, le titre et le texte."""
    pid = args.get("project")
    if not isinstance(pid, int):
        return None
    made = await compose(args, ports)
    if isinstance(made, str):
        return Preview(PREVIEW["cannot"].format(why=made), pin_of(why=made), made)
    url, base, head = str(args.get("url") or ""), str(args.get("base") or ""), str(args.get("head") or "")
    blocked = project_refusal(ports, pid).removeprefix("refusé : ")
    if not blocked and not writes_pulls(ports, url):
        blocked = CANNOT["no_host"]
    hosted = await hosted_remote(ports, url, base) if not blocked else None
    if hosted is not None and not hosted.head:
        blocked = CANNOT["no_base"].format(base=base)
    span = made.span
    files = ", ".join(span.files[:FILES_SHOWN]) + (" …" if len(span.files) > FILES_SHOWN else "")
    counted = f"{len(span.files)} fichier{'s' if len(span.files) > 1 else ''}"
    rows = [PREVIEW["what"].format(url=url, head=head, base=base, sha=span.head[:12]), "",
            PREVIEW["title"].format(title=made.title), "", PREVIEW["body"], made.body, "",
            PREVIEW["milestones"] if made.cited else PREVIEW["no_milestones"], *(f"- {x}" for x in made.cited)]
    if made.cited and not args.get("full"):
        rows.append(PREVIEW["kept"])
    rows += ["", made.ticket or PREVIEW["no_ticket"], "", made.review, "",
             commits_listed(PREVIEW["span"].format(files=counted, insertions=span.insertions, deletions=span.deletions),
                     span.commits),
             PREVIEW["files"].format(files=files)]
    return Preview("\n".join(rows), made.digest, blocked)


@PROJECTS.capability(PULL_REQUEST_CAPABILITY, description=DESCRIPTION, preview=pull_request_preview)
async def pull_request(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port, host = ports.get("workshop"), ports.get("repo_host")
    pid = effect_project(args, context)
    if port is None or pid is None:
        return False, "atelier introuvable"
    if why := project_refusal(ports, pid):
        return False, why
    made = await compose(args, ports)
    if isinstance(made, str):
        return False, f"refusé : {made}"
    seen = str(args.get(SEEN_KEY) or "")
    if seen and seen != made.digest:
        return False, f"refusé : {CANNOT['changed']}"
    url, base, head = str(args.get("url") or ""), str(args.get("base") or ""), str(args.get("head") or "")
    if host is None or not writes_pulls(ports, url):
        return False, f"refusé : {CANNOT['no_host']}"
    # la branche de travail part d'abord — elle seule : ``compose`` a refusé la base
    pushed = await port.push(pid, url, head, made.span.head)
    if not pushed.ok:
        return False, describe(pushed, 3000)
    opened = await host.open_pull(url, head=head, base=base, title=made.title, body=made.body)
    if opened.error or opened.state != PULL_OPEN:
        return False, "refusé : " + CANNOT["unopened"].format(why=opened.error or CANNOT["unsaid"])
    return True, OPENED.format(number=opened.number, url=opened.url)


def proposal(p: Project, o: Objective, span: Span) -> Draft[Any]:
    """La proposition d'ouvrir la pull request d'un objectif. Ses arguments ne portent que des numéros, des branches
    et le commit épinglé ; ``full`` : un accord est requis, les jalons cités partiront donc sous les yeux du
    propriétaire. Son résumé ne dit rien de plus."""
    args = {"project": p.id, "objective": o.id, "url": p.remote, "base": p.branch, "head": o.branch,
            "sha": span.head, "full": bool(p.approval)}
    summary = SUMMARY.format(objective=o.id, project=p.id, head=o.branch, base=p.branch, url=p.remote,
                             commits=len(span.commits))
    return rt.EFFECT_PROPOSED.draft(
        capability=PULL_REQUEST_CAPABILITY, owner=PROJECTS.name, context=project_target(p.id), approval=p.approval,
        args_json=json.dumps(args), summary=Content.of(summary[:600], level=written_for(p, o)),
        about=subjects_of(p))


# ── Ses faits et leurs réducteurs (ADR 0313) ──────────────────────────────


class PullSeen(Payload):
    """Ce que l'hôte dit de la pull request d'un objectif, lu à un instant (ADR 0274) : un fait arrivé, daté — pas
    un état qu'on recalcule. ``said`` : ce qu'il en dit (une relecture, un commentaire), le texte d'un inconnu —
    précédé du nom de son compte là-bas, dans le même contenu : l'oubli efface l'un avec l'autre."""

    project: int
    objective: int
    #: son numéro chez l'hôte, la branche qu'elle porte, son état (``PULL_STATES``) et si sa relecture demande des
    #: changements
    number: int = 0
    branch: str = ""
    state: str = ""
    changes: bool = False
    #: quand la relecture qui demande des changements a été rendue chez l'hôte (µs ; 0 : il ne le dit pas)
    review_at: int = 0
    said: Content | None = None
    #: quand l'hôte dit l'avoir mise à jour (µs ; 0 : il ne le dit pas)
    updated: int = 0
    #: l'hôte la dit impossible à fusionner — sa branche est en conflit avec la base —, ou fusionnable (ADR 0280) ;
    #: ``None`` : il ne le dit pas (ou pas encore) — ce qu'on en savait reste
    conflicts: bool | None = None
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


class BaseSeen(Payload):
    """Le commit au bout de la branche de base d'un atelier, lu après une récupération aboutie (ADR 0280) : un fait
    arrivé — ce que l'atelier avait à cet instant —, pas un état qu'on recalcule. ``commit`` vide : la base ne se
    lisait pas."""

    project: int
    commit: str = ""


class ChecksSeen(Payload):
    """Ce que l'hôte dit des vérifications du commit d'une pull request, lu à un instant (ADR 0275) : un fait
    arrivé, daté. ``said`` : d'un échec, les vérifications qui ont échoué et la fin du journal — le texte d'un
    inconnu, borné, que l'oubli atteint."""

    project: int
    objective: int
    sha: str = ""
    #: ``CHECKS_STATES`` du port
    state: str = ""
    said: Content | None = None
    #: quand l'hôte dit la dernière achevée (µs ; 0 : il ne le dit pas)
    updated: int = 0
    owner: str | None = None
    about: tuple[str, ...] = ()
    read_about: tuple[str, ...] = ()


PULL_SEEN = PROJECTS.event("pull_seen", PullSeen, content=("said",), subjects=("owner", "about", INHERITED))
CHECKS_SEEN = PROJECTS.event("checks_seen", ChecksSeen, content=("said",), subjects=("owner", "about", INHERITED))
BASE_SEEN = PROJECTS.event("base_seen", BaseSeen)


@PROJECTS.reducer(PULL_SEEN)
def _pull_seen(s: ProjectsState, e, cx) -> ProjectsState:
    """Ce que l'hôte dit de la pull request d'un objectif (ADR 0274). Fusionnée : l'objectif est clos pour de bon
    — un ponctuel rouvert entre-temps aussi (``_accepted``, ADR 0277) —, sa branche a fait son temps, et la base se
    récupère (une demande, que ``projects.remote`` propose). Fermée sans fusion, ou des changements demandés : un
    ponctuel abouti se rouvre, avec le mot de l'hôte sous les yeux de l'exécution qui vient. Impossible à fusionner
    (ADR 0280 : sa branche est en conflit avec la base) : elle n'est pas prête, et l'objectif se rouvre de même —
    une fois, quand l'hôte le dit pour la première fois ; il ne se rouvrira de nouveau qu'après que l'hôte l'a
    redite fusionnable. Total : un objectif inconnu, un état inconnu ne changent rien."""
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None or d.state not in PULL_STATES:
        return s
    if o.pull_state == PULL_MERGED and d.branch == o.branch:
        # déjà fusionnée, la même branche : rien ne se compte deux fois. Mais une fusion redite — sa branche,
        # reprise depuis, est entrée dans la base hors de sa vue — lève « à envoyer » : sans cela la passe la
        # redirait chaque minute, sans fin (ADR 0277)
        if d.state != PULL_MERGED or not (o.unsent or o.pull_tries):
            return s
        return with_project(s, with_objective(p, _accepted(replace(o, unsent=False, pull_tries=0), e.at)))
    said = d.said.ref or "" if d.said is not None else ""
    changes = d.changes and d.state == PULL_OPEN
    # un refus ne compte qu'une fois : une fermeture qu'on n'avait pas vue, une relecture plus récente que la dernière
    # (après un nouvel envoi, l'hôte redit la même relecture tant que personne n'a relu : elle ne rouvre rien)
    # ce que l'hôte dit de sa fusion ne vaut que pour une pull request ouverte ; s'il n'en dit rien, ce qu'on en
    # savait reste — il le recalcule après chaque envoi, et « je ne sais pas encore » ne lève pas un conflit
    conflicts = d.state == PULL_OPEN and (o.pull_conflicts if d.conflicts is None else d.conflicts)
    back = (d.state == PULL_CLOSED and o.pull_state != PULL_CLOSED) or (changes and (
        d.review_at > o.pull_review_at if d.review_at else not o.pull_changes)) or (
        conflicts and not o.pull_conflicts)
    o = replace(o, pull=d.number or o.pull, pull_state=d.state, pull_changes=changes,
                pull_review_at=max(o.pull_review_at, d.review_at), pull_at=e.at,
                pull_said_ref=said or o.pull_said_ref)
    fresh = conflicts and not o.pull_conflicts  # ``o`` : tel qu'il était avant ce que l'hôte vient de dire
    o = replace(o, pull_conflicts=conflicts)
    if d.state == PULL_MERGED:
        # fusionnée : plus aucune demande de fusion n'attend, et un refus d'avant ne se dit plus (ADR 0288)
        o = _accepted(replace(o, unsent=False, pull_tries=0, pulls_merged=o.pulls_merged + 1, merge_asked_at=0,
                              merge_refused=""), e.at)
    elif back:
        o = sent_back(o)
    if (d.state == PULL_MERGED or fresh) and p.remote and p.status != c.ARCHIVED:
        # la base se récupère avant l'exécution suivante : une demande, proposée sans accord (``tend.waiting``) —
        # après une fusion, et quand l'hôte dit la pull request en conflit (ADR 0280) : sa base a avancé, et
        # l'outil qui la ramène dans la branche de travail ne ramène que ce que l'atelier en a
        p = replace(p, requests=(*p.requests, (e.seq, BASE_REQUEST))[-4:])
    return with_project(s, with_objective(p, o))


def _accepted(o: Objective, at: int) -> Objective:
    """Sa pull request est fusionnée : ce qui est accepté chez l'hôte est clos pour de bon (ADR 0274, 0277). Un
    ponctuel que l'hôte ou une relecture avait rouvert — ou qui bloquait — est clos : sans cela son ticket restait
    « en attente de PR », « fait » se refusait faute de nouveau commit, et ses exécutions tournaient jusqu'au
    blocage. Plus aucune relecture ne l'attend : celle qui était demandée tombe. Tout autre objectif ne bouge
    pas."""
    o = replace(o, review_due="", review_tries=0)
    if o.kind != c.ONCE or o.status not in (c.OPEN, c.BLOCKED):
        return o
    return replace(o, status=c.DONE, closed_at=at, waiting_until=0, need_ref="", asked=False, ask_attempts=0)


@PROJECTS.reducer(CHECKS_SEEN)
def _checks_seen(s: ProjectsState, e, cx) -> ProjectsState:
    """Ce que l'hôte dit des vérifications du commit d'une pull request (ADR 0275). En échec : un ponctuel abouti se
    rouvre — une fois par commit en échec, pas à chaque lecture, ni quand « en cours » s'est intercalé entre deux
    échecs du même commit (``checks_failed_sha``, ADR 0278) —, la fin du journal sous les yeux de l'exécution qui
    vient. Total : un objectif inconnu, un état inconnu ne changent rien."""
    d = e.data
    p = s.projects.get(d.project)
    o = objective_at(p, d.objective) if p is not None else None
    if p is None or o is None or d.state not in CHECKS_STATES:
        return s
    failed = d.state == CHECKS_FAILED
    failed_anew = failed and d.sha != o.checks_failed_sha
    said = d.said.ref or "" if d.said is not None else ""
    o = replace(o, checks=d.state, checks_sha=d.sha, checks_at=e.at,
                checks_failed_sha=d.sha if failed else o.checks_failed_sha,
                checks_said_ref=said or (o.checks_said_ref if failed else ""))
    return with_project(s, with_objective(p, sent_back(o) if failed_anew else o))


@PROJECTS.reducer(BASE_SEEN)
def _base_seen(s: ProjectsState, e, cx) -> ProjectsState:
    """La base d'un atelier, relue après une récupération (ADR 0280) : la fusion acceptée d'une pull request, ou
    toute récupération qui ramène autre chose, fait avancer ce qu'un projet lecteur voit — c'est cela qui l'éveille,
    pas le commit d'une branche de travail. Une base qui n'a pas bougé n'éveille rien. Total : un projet inconnu ne
    change rien."""
    p = s.projects.get(e.data.project)
    if p is None:
        return s
    s = with_project(s, replace(p, base_unread=False)) if p.base_unread else s
    return with_base(s, e, p.id, e.data.commit)


# ── Ce que l'hôte en dit ──────────────────────────────────────────────────


def seen_fact(p: Project, o: Objective, seen: Pull) -> Draft[Any] | None:
    """Le fait que pose une lecture de l'hôte, ou rien : il n'a pas répondu, il ne connaît aucune pull request pour
    cette branche, ou il ne dit rien de neuf. Ce qu'il en dit n'est gardé que lorsqu'il la renvoie — une relecture
    qui demande des changements, une fermeture sans fusion : le texte d'un inconnu, au niveau de ce qu'elle écrit
    sur cet objectif, avec ses sujets."""
    if seen.error or seen.state not in PULL_STATES:
        return None
    changes = seen.state == PULL_OPEN and seen.review == REVIEW_CHANGES
    # ce qu'il dit de sa fusion (ADR 0280) : en conflit avec la base, fusionnable, ou rien — et rien ne change rien
    conflicts = None if seen.state != PULL_OPEN or seen.mergeable is None else not seen.mergeable
    known = (seen.number, seen.state, changes) == (o.pull, o.pull_state, o.pull_changes) and bool(o.pull_at) \
        and conflicts in (None, o.pull_conflicts)
    if known and not (changes and seen.review_at > o.pull_review_at):
        return None
    back = changes or seen.state == PULL_CLOSED
    # le nom du compte qui l'a écrit là-bas entre dans le même contenu : l'oubli efface l'un avec l'autre ; un compte
    # sans rôle sur le dépôt est dit tel (ADR 0278) — son mot se cite, il ne pèse pas celui de qui tient le dépôt
    who = seen.said_by.strip()[:80]
    if who and not seen.said_role:
        who = phrase("projects.pull.run.no_role", name=who)
    said = f"{who} : {seen.said.strip()}" if who else seen.said.strip()
    return PULL_SEEN.draft(
        project=p.id, objective=o.id, number=seen.number, branch=o.branch, state=seen.state, changes=changes,
        review_at=seen.review_at if changes else 0,
        said=Content.of(said, level=written_for(p, o)) if back and seen.said.strip() else None,
        updated=seen.at, conflicts=conflicts, owner=p.owner, about=p.about, read_about=inherited_for(p, o))


def absorbed(p: Project, o: Objective) -> Draft[Any]:
    """Sa branche n'a plus rien que la base n'ait : son travail y est déjà entré (une fusion faite hors de sa vue,
    puis la base récupérée). Il n'y a plus rien à proposer."""
    return PULL_SEEN.draft(project=p.id, objective=o.id, number=o.pull, branch=o.branch, state=PULL_MERGED,
                           owner=p.owner, about=p.about, read_about=inherited_for(p, o))


async def checked(host: Any, p: Project, o: Objective, seen: Pull) -> Draft[Any] | None:
    """Le fait que posent les vérifications du commit d'une pull request ouverte (ADR 0275), ou rien : l'hôte ne
    sait pas les dire, il n'a pas répondu, ou il ne dit rien de neuf pour ce commit. D'un échec, on garde les
    vérifications qui ont échoué et la fin du journal de la première — le texte d'un inconnu, borné, au niveau de ce
    qu'elle écrit sur cet objectif, avec ses sujets : il sera cité à l'exécution, jamais donné pour une consigne."""
    read = getattr(host, "checks", None)
    if not callable(read) or seen.error or seen.state != PULL_OPEN or not seen.sha:
        return None
    got = await read(p.remote, seen.sha)
    if got.error or got.state not in CHECKS_STATES or (seen.sha, got.state) == (o.checks_sha, o.checks):
        return None
    said = ""
    if got.state == CHECKS_FAILED:
        log = getattr(host, "check_log", None)
        tail = (await log(p.remote, seen.sha)).tail if callable(log) else ""
        names = ", ".join(x.strip() for x in got.failed if x.strip())
        # la fin compte : c'est là que l'échec se dit
        said = "\n".join(x for x in (names, tail.strip()[-(CHECKS_SAID_MAX - len(names)):]) if x)
    return CHECKS_SEEN.draft(
        project=p.id, objective=o.id, sha=seen.sha, state=got.state,
        said=Content.of(said, level=written_for(p, o)) if said else None, updated=got.at, owner=p.owner,
        about=p.about, read_about=inherited_for(p, o))


@PROJECTS.process("projects.pulls", wake_on=[c.RUN_REPORTED, c.OBJECTIVE_CLOSED, PULL_SEEN, REFRAMED, REVIEWED,
                                             MERGE_ANSWERED, rt.EFFECT_EXECUTED, rt.EFFECT_RESOLVED],
                  catch_up=CatchUp.ONCE, max_quantum_s=3600, priority=45)
class Pulls:
    """Proposer la pull request d'un travail conclu, puis la suivre chez l'hôte (ADR 0274). Rien ne part d'ici : une
    proposition est une capacité, exécutée après le commit du journal, avec ou sans accord selon le projet ; une
    lecture de l'hôte ne fait qu'écrire ce qu'il dit. Il ne fusionne rien : quand une personne a fusionné d'ici
    (ADR 0288), la réponse de l'hôte le réveille, et il relit la pull request aussitôt — c'est cette relecture, comme
    pour toute fusion faite chez l'hôte, qui clôt l'objectif."""

    def __init__(self) -> None:
        #: par pull request (projet, objectif) que l'hôte n'a pas encore su dire : ses lectures de suite sans
        #: réponse, et l'heure de la dernière. Gardé en mémoire seulement : cela ne borne que les appels à l'hôte,
        #: rien ne s'en déduit — au redémarrage, elle se redemande une fois, puis recule de nouveau
        self._unread: dict[tuple[int, int], tuple[int, int]] = {}

    def _again_at(self, p: Project, o: Objective, last_run: int) -> int:
        """Quand redemander à l'hôte une pull request jamais lue : aussitôt la première fois (son numéro), puis à
        un écart qui s'allonge tant qu'il ne sait pas la dire."""
        failed, at = self._unread.get((p.id, o.id), (0, 0))
        return at + retry_in(failed) if failed else last_run + RETRY_US

    def next_due(self, s: ProjectsState, frame: Frame, last_run: int | None) -> int | None:
        opened = tracked(s)
        waiting = [x for x in due(s) if not parked(*x)]  # ce qui attend sa relecture ne demande rien à la passe
        bases = unread_bases(s)
        if not (waiting or opened or bases):
            return None
        if last_run is None:
            return frame.now
        # une pull request qui vient de s'ouvrir se lit aussitôt (son numéro) ; ensuite, à un rythme borné
        at = last_run + (RETRY_US if waiting or bases else POLL_US)
        unread = [self._again_at(p, o, last_run) for p, o in opened if not o.pull_at]
        # une fusion faite d'ici que l'hôte vient d'accepter (ADR 0288) : il se relit aussitôt — une fois ; s'il ne
        # la dit pas encore fusionnée, à l'écart court
        merged = [o.merge_answered_at for _, o in opened if o.merge_answered_at > o.pull_at and not o.merge_refused]
        if merged:
            unread.append(frame.now if last_run < min(merged) else last_run + RETRY_US)
        # une réponse perdue, une demande interrompue (ADR 0292) : on ne sait pas si la fusion a eu lieu — l'hôte
        # se relit aussitôt, une fois, puis à l'écart court le temps d'une pull request fraîche
        unsure = [o.merge_answered_at for _, o in opened if merge.unsure(o)]
        if unsure and last_run < max(unsure):
            unread.append(frame.now)
        elif any(frame.now - at_ < merge.CHECKS_GRACE_US for at_ in unsure):
            unread.append(last_run + RETRY_US)
        # une pull request fraîche dont l'hôte ne dit encore aucune vérification (ADR 0292) : il vient de recevoir
        # son commit et ne les a pas créées — elle se relit à l'écart court, pas dix minutes plus tard
        if any(o.pull_at and merge.unchecked(o, frame.now) for _, o in opened):
            unread.append(last_run + RETRY_US)
        return max(frame.now, min([at, *unread]))

    async def run(self, ctx: Any) -> None:
        s: ProjectsState = ctx.state
        port, host = ctx.ports.get("workshop"), ctx.ports.get("repo_host")
        proposals: list[Draft[Any]] = []
        facts: list[Draft[Any]] = []
        for p in unread_bases(s):
            # une récupération vient d'aboutir : où est la base maintenant (ADR 0280) ? Le fait se pose même si elle
            # ne se lit pas — rien n'attend alors pour toujours —, et le réducteur dit si elle a avancé
            sha = await port.base(p.id) if port is not None and port.exists(p.id) else ""
            facts.append(BASE_SEEN.draft(project=p.id, commit=sha))
        for p, o in due(s):
            span = await port.span(p.id, o.branch) if port is not None and port.exists(p.id) else None
            if span is None:
                continue  # l'atelier ne se lit pas pour l'instant : la passe suivante réessaiera
            if not span.commits:
                facts.append(absorbed(p, o))
                continue
            # sa relecture d'abord (ADR 0276) : la proposition ne part qu'avec un verdict favorable pour ce commit
            step = reread(p, o, span.head)
            if step == PASS:
                proposals.append(proposal(p, o, span))
            elif step == ASK:
                facts.append(REVIEW_ASKED.draft(project=p.id, objective=o.id, sha=span.head, owner=p.owner,
                                                about=p.about))
        now = ctx.now
        for p, o in tracked(s) if host is not None else ():
            if not host.handles(p.remote):
                continue
            key = (p.id, o.id)
            if not o.pull_at and key in self._unread and now < self._again_at(p, o, now):
                continue  # l'hôte ne savait pas la dire : pas avant que son écart soit passé
            seen = await host.pull(p.remote, o.branch)
            if seen.error or seen.state not in PULL_STATES:
                # en panne, ou il ne la connaît pas (encore) : une lecture sans réponse de plus
                self._unread[key] = (self._unread.get(key, (0, 0))[0] + 1, now)
            else:
                self._unread.pop(key, None)
            # ce qu'il dit de la pull request, puis — dans la même passe, pour son commit — de ses vérifications
            facts += [x for x in (seen_fact(p, o, seen), await checked(host, p, o, seen)) if x is not None]
        for key in [k for k in self._unread if k not in {(p.id, o.id) for p, o in tracked(s)}]:
            del self._unread[key]  # plus suivie (fusionnée, fermée, archivée) : rien à retenir
        if facts:
            await ctx.emit(*facts)
        if proposals:
            await ctx.emit(*proposals, emitter=rt.OWNER)


# ── Ce que l'exécution en lit ─────────────────────────────────────────────


def state_words(o: Objective) -> str:
    """Où en est la pull request d'un objectif, en une phrase (vide : son projet n'en a pas encore proposé)."""
    if o.pull_proposal:
        return phrase("projects.pull.run.proposed")
    if o.pull_state == PULL_MERGED:
        return phrase("projects.pull.run.merged", n=o.pull)
    if o.pull_state == PULL_CLOSED:
        return phrase("projects.pull.run.closed", n=o.pull)
    if o.pull_state == PULL_OPEN and o.pull_changes:
        return phrase("projects.pull.run.changes", n=o.pull)
    if o.pull_state == PULL_OPEN:
        return phrase("projects.pull.run.open", n=o.pull) if o.pull else phrase("projects.pull.run.opening")
    return ""


def checks_words(o: Objective) -> str:
    """Où en sont les vérifications du commit de sa pull request, en une phrase (vide : rien à en dire — pas de
    pull request ouverte, pas de CI, ou elles ne se lisent pas)."""
    if o.pull_state != PULL_OPEN or not o.checks_sha:
        return ""
    sha = o.checks_sha[:12]
    if o.checks == CHECKS_FAILED:
        return phrase("projects.pull.run.checks_failed", sha=sha)
    if o.checks == CHECKS_PENDING:
        return phrase("projects.pull.run.checks_pending", sha=sha)
    return phrase("projects.pull.run.checks_passed", sha=sha) if o.checks == CHECKS_PASSED else ""


def run_lines(o: Objective | None, placed: Mapping[str, Any], said: str, failure: str = "") -> list[str]:
    """Ce que lit l'exécution d'un projet qui passe par des pull requests : sa branche, d'où elle part, ce qui a été
    rangé, et où en est la pull request de son objectif — avec, quand elle lui est revenue, ce que l'hôte en dit,
    cité ; si l'hôte la dit impossible à fusionner, comment en sortir (ADR 0280) ; puis ses vérifications (ADR 0275)
    et, en échec, la fin du journal (``failure``), citée elle aussi. Borné : huit lignes, les mots de l'hôte
    coupés."""
    lines = []
    if placed.get("name"):
        lines.append(phrase("projects.pull.run.branch", branch=placed["name"], base=str(placed.get("base") or "")[:12],
                            ahead=int(placed.get("ahead") or 0)))
        if placed.get("created"):
            lines.append(phrase("projects.pull.run.created"))
    elif placed.get("why"):
        lines.append(phrase("projects.pull.run.unplaced", why=clipped(str(placed["why"]), 200)))
    if placed.get("stowed"):
        lines.append(phrase("projects.pull.run.stowed", branch=placed.get("stowed_on") or "?",
                            sha=str(placed["stowed"])[:12]))
    if o is None:
        return lines
    lines.append(state_words(o) or phrase("projects.pull.run.none"))
    if said.strip() and (o.pull_state == PULL_CLOSED or o.pull_changes):
        lines.append(f"{phrase('projects.pull.run.said')}\n« {clipped(said, SAID_SHOWN)} »")
    if o.pull_state == PULL_OPEN and o.pull_conflicts:
        # l'hôte la dit impossible à fusionner : sa branche est en conflit avec la base — et la sortie existe
        lines.append(phrase("projects.pull.run.conflicts", tool=TAKE_BASE))
    if judged := checks_words(o):
        lines.append(judged)
        if failure.strip() and o.checks == CHECKS_FAILED:
            lines.append(f"{phrase('projects.pull.run.checks_said')}\n« {failure.strip()[-CHECKS_SAID_MAX:]} »")
    return lines


@PROJECTS.section("project_pull", zone=Zone.VOLATILE, episodes=RUNS, trim_rank=80, untrusted=True,
                  floor_chars=400, title=phrase("projects.pull.title"))
def _pull_section(s: ProjectsState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """La branche où cette exécution travaille, la pull request de son objectif (ADR 0274) et ses vérifications
    (ADR 0275). Non fiable : elle cite ce que l'hôte dit — une relecture, la fin du journal d'un échec : le texte
    d'un inconnu sur un dépôt peut-être public, une donnée, jamais une consigne."""
    ep = frame.episode
    pid = project_of(ep.target) if ep is not None else None
    p = s.projects.get(pid) if pid is not None else None
    if p is None or not by_pulls(p):
        return None
    got = objective_of(ep.attrs.get("subject")) if ep is not None else None
    o = objective_at(p, got[1]) if got is not None and got[0] == p.id else None
    placed = (enrich.get("projects_tree") or {}).get("branch") or {}
    texts = (enrich.get("projects") or {}).get("texts") or {}
    said = texts.get(o.pull_said_ref, "") if o is not None and o.pull_said_ref else ""
    failure = texts.get(o.checks_said_ref, "") if o is not None and o.checks_said_ref else ""
    lines = run_lines(o, placed, said, failure)
    if not lines:
        return None
    return SectionBody("\n".join(lines), level=written_for(p, o), provenance=(f"project:{p.id}",))


# ── Relire la fin du journal d'un échec ───────────────────────────────────

CHECKS_LOG = "checks_log"


class LogArgs(BaseModel):
    pass


@PROJECTS.tool(CHECKS_LOG, description=phrase("projects.tools.checks.description"),
               label=phrase("projects.tools.checks.label"), args=LogArgs, bundle="projects", episodes=RUNS,
               max_calls_per_episode=3)
async def checks_log(args: LogArgs, ctx: Any) -> Any:
    """La fin du journal de la vérification en échec du commit de sa pull request (ADR 0275), relue chez l'hôte :
    une lecture du dépôt déclaré, rien n'y part. Ce qu'elle rend est le texte d'un inconnu — une vérification écrit
    ce qu'elle veut dans son journal — : cité, annoncé comme une donnée."""
    got = running_project(ctx)
    if got is None:
        return gone_reply()
    p, o = got
    host = ctx.ports.get("repo_host")
    read = getattr(host, "check_log", None)
    if o is None or not by_pulls(p) or o.checks != CHECKS_FAILED or not o.checks_sha or not callable(read):
        return ToolResult(ok=False, content=phrase("projects.tools.checks.none"))
    log = await read(p.remote, o.checks_sha)
    if log.error or not log.tail.strip():
        return ToolResult(ok=False, content=phrase("projects.tools.checks.unread"))
    return phrase("projects.tools.checks.log", name=clipped(log.name, 80), sha=o.checks_sha[:12],
                  tail=log.tail.strip()[-LOG_SHOWN:])


__all__ = ["Made", "checks_words", "compose", "due", "pull_url", "retry_in", "state_words", "tracked"]
