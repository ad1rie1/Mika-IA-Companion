"""Ce qu'une personne a d'un projet, dans son espace (ADR 0282, 0286, 0288, 0290) : la base de l'API des projets
(``projects.py``, ``activity.py``, ``code.py``, ``docs.py``, ``manage.py``), de son point MCP (``../docs_mcp.py``) et
du direct (``../live.py``). Ce module n'importe jamais ``projects.py`` : c'est lui qui le lit.

**Ce qu'elle a d'un projet** (``reach``) compose la plus serrée de deux lectures du moteur :

- ce que ses lignes d'accès lui donnent hors de toute conversation (``todo.reach`` : son projet en entier ; celui
  d'un autre selon ``links.given_to`` — seule une ligne qui la désigne ouvre, la ligne par défaut jamais) ;
- ce que la conversation lui en dirait par le canal de son client (``access.sees``, ``access.steering`` : ses deux
  portes), au niveau qu'elle en entend (``tracker.reader_of`` : la règle de « TES PROJETS »).

Chaque droit suppose le précédent : le voir (``see``), son détail (``detail``), le piloter (``steer``), le trancher
(``settles``) ; ses fichiers et ses diffs demandent en plus le droit sur eux (``reads_files``). ``opened_project`` est
la porte des routes d'un projet : un projet qu'elle ne voit pas est introuvable (404), un détail qu'elle n'a pas,
refusé (403).

**Les refus, et leur ordre.** Chaque refus est le texte que rend sa route (« Les refus, en mots »), et l'ordre où une
garde les essaie compte : ce qui ferme le plus d'abord — le détail (``ONLY_SEEN``), puis le pilotage
(``NOT_STEERED``), puis la modification (``NEEDS_EDIT``), puis qui tranche (``NOT_MERGER``, ``NOT_FRAMER``). Ce que
l'écran dit d'avance (``edit_refusal``, ``frame_refusal``, ``merge_refusal``, ``objective_can``, ``milestone_can`` ;
« À faire » dans ``projects.py``) est le refus même de la route, dans le même ordre : rien qu'elle n'apprendrait pas en
essayant.

**Qui a écrit** un élément ou une note se dit par sa sorte (``author_kind``) et en mots (``author_fields``) : le nom
d'une autre personne seulement si sa voix le dit à tous (qui s'occupe d'elle, ``identity.keepers``) ou si ce qui
concerne cette personne s'entend d'ici, au niveau de l'élément (``nameable`` : ``vocab.privacy.hearable``) ; celui
d'un autre projet, seulement si elle le voit (``writing_projects``). Un texte venu d'ailleurs se dit tel
(``outside_text``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from mika.adapters.web.session import native_token
from mika.app.me.api import Call, Denied, missing, person_of
from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.projects import access, links, merge, milestones, todo, tracker
from mika.faculties.projects.faculty import (
    Objective,
    Project,
    ProjectsState,
    detail_level,
    milestones_of,
    written,
)
from mika.faculties.projects.inspect_merge import BLOCK_WORDS
from mika.faculties.projects.inspect_milestones import HELD_WORDS
from mika.kernel.frame import Audience
from mika.vocab.access import CHANGES, STEER_EDIT, STEER_NO, STEER_RANK, tighten
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust, hearable

# ── Ses bornes, et qui a écrit, en mots ───────────────────────────────────

#: un texte rendu : sa borne (un plan, le texte d'un ticket, une note), et celle d'une ligne
TEXT_SHOWN, LINE_SHOWN = 8000, 240
#: qui a écrit un élément ou une note (``author_kind``) : elle, la personne connectée, une autre personne, un autre
#: projet, quelqu'un chez l'hôte du dépôt
BY_HER, BY_YOU, BY_OTHER, BY_PROJECT, BY_HOST = "self", "you", "person", "project", "host"
YOU_WORDS, OTHER_WORDS, HOST_WORDS = "toi", "une autre personne", "quelqu'un chez l'hôte du dépôt"
PROJECT_WORDS, NAMED_PROJECT_WORDS = "un autre projet", "le projet « {title} »"

# ── Les refus, en mots ────────────────────────────────────────────────────

ONLY_SEEN = "Ce projet ne t'est ouvert qu'à voir : son détail reste à son propriétaire."
NOT_STEERED = "Tu ne pilotes pas ce projet : tu peux le lire, pas y changer quoi que ce soit."
NEEDS_EDIT = ("Sur ce projet, ce geste demande l'accord de son propriétaire : demande-le-lui dans le chat, elle le lui "
              "proposera.")
NOT_SETTLER = "Seul le propriétaire du projet, ou qui s'occupe d'elle, tranche ici."
NOT_PLAN_ASKER = "Seule la personne qui a demandé ce projet, ou qui s'occupe d'elle, répond à son plan."
NOT_LINKER = "Seul le propriétaire du projet pose ce qu'il lit."
NOT_DECIDER = "Cet accord n'est pas le tien : il attend quelqu'un qui s'occupe d'elle."
UNREADABLE = "Cet élément ne se lit pas d'ici."
AT_CONSOLE = "Ce geste ne se fait pas d'ici : il se fait dans la console."
NOT_MERGER = "Seul le propriétaire du projet, ou qui s'occupe d'elle, fusionne une pull request."
NOT_FRAMER = ("Seul le propriétaire du projet, ou qui s'occupe d'elle, change son cadre : tu le pilotes, tu ne le "
              "règles pas.")
#: l'onglet de ce qu'un projet lit et de qui le lit (ADR 0290 : « Liens » s'appelle « Dépendances »), en mots
LINK_LABELS = {"title": "Dépendances", "reads": "Il dépend de", "readers": "Dépendent de lui",
               "asks": "Ses demandes"}
NO_FILES = "Ce projet ne t'ouvre pas ses fichiers : tu en lis les titres et les états, pas le contenu ni les diffs."
#: le geste d'une pull request prête (ADR 0288) : la route qui la fusionne, et ses mots
MERGE_ROUTE, MERGE_GESTURE = "code/pull/fusionner", "Fusionner"
NOT_READ_YET = "Ses demandes n'entrent directement que chez un projet qu'il lit déjà : {projects}."
PLAN_MOVED = "Le plan du ticket #{number} n'est plus celui que tu as lu : relis-le dans son fil, puis valide-le."
SEEN_NEEDED = "Dis ce que tu as lu : « seen », le condensé de son aperçu."


# ── Ce qu'elle a d'un projet ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Scene:
    """Ce qu'une requête lit une fois : ce qu'elle vit, ses projets, le monde des règles, et qui regarde."""

    call: Call
    frame: Any
    s: ProjectsState
    world: links.World
    audience: Audience
    person: str

    @property
    def keeper(self) -> bool:
        """Elle s'occupe d'elle : « ton accord », dans une ligne d'accès, c'est le sien (ADR 0133)."""
        return self.world.keeper(self.person)


@dataclass(frozen=True, slots=True)
class Reach:
    """Ce que la personne a d'un projet : le voir (son titre, son état), son détail, le piloter (``STEERS``), le
    trancher (ses tickets, ses points d'arrêt), et ce qu'elle lit de son registre (``reader``)."""

    p: Project
    own: bool
    see: bool
    detail: bool
    steer: str
    reader: tracker.Reader

    @property
    def settles(self) -> bool:
        return self.steer in CHANGES and self.reader.settles


def audience_of(call: Call) -> Audience:
    """L'audience de qui est connecté, par le canal de son client (le chat web, l'app du téléphone), telle que le
    pipeline la lirait en tête-à-tête : son niveau est celui que son lien lui ouvre (``identity.DISCLOSURE``)."""
    return audience_at(call.frame, call.me, "mobile" if native_token(call.request.headers) else "web")


def audience_at(frame: Any, me: Any, channel: str) -> Audience:
    """L'audience d'une personne connue par son compte (``Me``), par ce canal, en tête-à-tête — pour une requête de
    son espace, et pour un outil qui présente son jeton au point MCP (ADR 0289)."""
    d = frame.get(identity_c.DISCLOSURE((me.handle, channel, False)))
    return Audience(persons=(me.handle,), channel=channel, room=None, public=False, level=int(d.level),
                    witness_level=int(d.witness_level), private_ok=bool(d.own_file),
                    trust=ChannelTrust.AUTHENTICATED.value, name=me.name, person=me.person,
                    owner=bool(frame.get(identity_c.SPEAKS_AS_OWNER(me.handle))), tied_level=int(d.tied_level),
                    veiled_level=int(d.veiled_level), untied_level=int(d.untied_level))


def scene(call: Call) -> Scene:
    frame = call.frame
    return Scene(call, frame, frame.state("projects"), links.world_of(frame), audience_of(call), call.me.person)


def reach(sc: Scene, p: Project) -> Reach:
    """Ce qu'elle a de ce projet : la plus serrée de ce que ses lignes lui donnent hors de toute conversation et de
    ce que la conversation lui en dirait par ce canal, au niveau qu'elle en entend."""
    grant = todo.reach(p, sc.person, sc.world)
    reader = tracker.reader_of(sc.frame, p, sc.person, sc.audience)
    see = grant.see and access.sees(p, sc.audience, Kind.REPLY, sc.frame) and p.sensitivity <= reader.level
    steer = tighten(grant.steer, access.steering(p, sc.audience, Kind.REPLY, sc.frame), STEER_RANK) if see \
        else STEER_NO
    detail = see and steer != STEER_NO and detail_level(p) <= reader.level
    return Reach(p, todo.owns(p, sc.person, sc.world), see, detail, steer if detail else STEER_NO, reader)


def reads_files(sc: Scene, r: Reach) -> bool:
    """Lit-elle le contenu de ses fichiers et ses diffs (ADR 0288) ? Son détail, et le droit sur ses fichiers — celui
    de ses lignes d'accès hors de toute conversation (``todo.reach``) et par le canal de son client
    (``access.shares_files``) —, au niveau de ce que le projet écrit."""
    p = r.p
    return r.detail and todo.reach(p, sc.person, sc.world).files and written(p) <= r.reader.level \
        and access.shares_files(p, sc.audience, Kind.REPLY, sc.frame)


def merge_refusal(r: Reach, o: Objective | None, now: int = 0) -> str:
    """Pourquoi elle ne peut pas fusionner la pull request de cet objectif (vide : elle le peut) — le refus même de
    ``POST …/code/pull/fusionner``, dans son ordre : la piloter, la trancher, puis ce que la pull request en dit
    (``now`` : l'instant, pour une pull request fraîche dont l'hôte n'a pas encore dit les vérifications)."""
    if r.steer not in CHANGES:
        return NOT_STEERED
    if not r.reader.settles:
        return NOT_MERGER
    block = merge.blocked(r.p, o, now) if o is not None else merge.NO_PULL
    return BLOCK_WORDS[block] if block else ""


def edit_refusal(r: Reach) -> str:
    """Pourquoi elle ne change ni ses objectifs, ni ses jalons, ni ses tickets, ni ses décisions (vide : elle le
    peut ; ADR 0290) : cela demande de le piloter en modification — le refus même de ces routes, dit d'avance."""
    if not r.detail:
        return ONLY_SEEN
    return "" if r.steer == STEER_EDIT else NOT_STEERED if r.steer not in CHANGES else NEEDS_EDIT


def frame_refusal(r: Reach) -> str:
    """Pourquoi elle ne change pas le cadre de ce projet — ses réglages, ses outils, son dépôt, l'archiver (vide :
    elle le peut ; ADR 0290) : le piloter en modification, et en être le propriétaire ou s'occuper d'elle
    (``tracker.frames``, que ``Reader.settles`` lit déjà)."""
    return edit_refusal(r) or ("" if r.reader.settles else NOT_FRAMER)


def objective_can(r: Reach, o: Objective) -> dict[str, Any]:
    """Ce qu'elle peut faire d'un objectif ici : la garde de ses routes, dite d'avance."""
    why = edit_refusal(r)
    can, once = not why, o.kind == c.ONCE
    living = o.status in (c.OPEN, c.BLOCKED)
    return {"modify": can and o.status != c.DROPPED, "reopen": can and o.status in (c.DONE, c.BLOCKED),
            "done": can and once and living, "drop": can and o.status != c.DROPPED,
            "milestone": can and once and living and len(milestones_of(o)) < c.MILESTONES_MAX, "why": why}


def milestone_can(r: Reach, m: Any) -> dict[str, Any]:
    """Ce qu'elle peut faire d'un jalon ici : le modifier, le retirer — et sinon pourquoi (atteint ou retiré, il ne
    bouge plus ; un point d'arrêt et un jalon tenu restent à qui tranche, ADR 0278)."""
    why = edit_refusal(r)
    held = "" if why else milestones.undoing(m, r.reader.settles)
    why = why or (HELD_WORDS.get(held, HELD_WORDS["other"]) if held else "")
    return {"modify": not why, "drop": not why, "why": why}


def reaches(sc: Scene) -> dict[int, Reach]:
    """Ses projets : ceux qu'elle voit, par numéro."""
    found = ((p.id, reach(sc, p)) for p in sc.s.projects.values())
    return {pid: r for pid, r in found if r.see}


def store_of(call: Call) -> Any:
    return call.kernel.mind.store


def texts_of(call: Call, refs: Iterable[str]) -> dict[str, str]:
    wanted = [r for r in dict.fromkeys(refs) if r]
    return dict(store_of(call).content(wanted)) if wanted else {}


def person_name(sc: Scene, person: str | None) -> str:
    return (identity_c.person_name(sc.frame, person) or "") if person else ""


def opened_project(call: Call, *, detail: bool = True) -> tuple[Scene, Reach]:
    """Le projet que nomme le chemin, s'il est à elle ou qu'on le lui laisse voir : sinon introuvable. ``detail`` :
    la route lit ou change son détail — le voir n'y suffit pas (403)."""
    sc = scene(call)
    p = sc.s.projects.get(int(call.request.path_params["project"]))
    r = reach(sc, p) if p is not None else None
    if r is None or not r.see:
        raise missing()
    if detail and not r.detail:
        raise Denied(403, ONLY_SEEN)
    return sc, r


def must_steer(r: Reach, *, edit: bool = False) -> None:
    """La garde des outils de conversation : y changer quelque chose demande de le piloter, sur accord ou en
    modification ; ``edit`` — le geste ne se fait qu'en modification (sur accord, il se demande dans le chat)."""
    if r.steer not in CHANGES:
        raise Denied(403, NOT_STEERED)
    if edit and r.steer != STEER_EDIT:
        raise Denied(403, NEEDS_EDIT)


def answers_plan(sc: Scene, r: Reach) -> bool:
    """Qui répond à son plan (``project_steer``) : qui l'a demandé, ou qui s'occupe d'elle."""
    return r.steer in CHANGES and (sc.person == r.p.asked_by or sc.keeper)


def decides(sc: Scene, r: Reach, proposal: int) -> bool:
    """Un accord est celui de qui s'occupe d'elle (« ton accord », ADR 0133) ; une carte adressée à quelqu'un
    (``runtime.DECIDER``) n'est qu'à lui."""
    if not r.detail or not sc.keeper:
        return False
    pending = sc.frame.state("runtime").effects.get(proposal)
    decider = rt.proposal_args(pending.args_json).get(rt.DECIDER) if pending is not None else None
    return not decider or decider == sc.call.me.handle


# ── Qui a écrit, et ce qui vient d'ailleurs ───────────────────────────────


def outside_text(text: str, limit: int = TEXT_SHOWN) -> dict[str, Any] | None:
    """Un texte venu d'ailleurs (un commentaire de l'hôte, la fin d'un journal, la sortie d'une commande) : le
    client le présente comme tel, jamais comme un mot d'elle ni du propriétaire."""
    return {"text": text[:limit], "outside": True} if text else None


def nameable(sc: Scene, person: str, level: int) -> bool:
    """A-t-elle le droit de savoir le nom de cette autre personne ? Deux lectures du moteur, aucune d'ici : qui
    s'occupe d'elle est nommé à tous par sa voix (``identity.keepers``) ; pour toute autre, « elle a écrit ceci » la
    concerne, et ne se dit que si ce qui concerne autrui s'entend d'ici au niveau de l'élément (``privacy.hearable``,
    appelée comme ``tracker.reader_of`` le fait pour le projet)."""
    aud = sc.audience
    return sc.world.keeper(person) or hearable((person,), level, sc.person, aud.level, aud.witness_level,
                                               aud.private_ok)


def writing_projects(sc: Scene, authors: Iterable[str]) -> dict[int, str]:
    """Les projets qui ont écrit (une demande d'un projet à un autre) et qu'elle voit elle-même : leur titre, par
    numéro. Les autres ne se nomment pas."""
    asked = {pid for a in authors if (pid := c.asking_project(a))}
    seen = [p for pid in sorted(asked) if (p := sc.s.projects.get(pid)) is not None and reach(sc, p).see]
    texts = texts_of(sc.call, [p.title_ref for p in seen])
    return {p.id: texts.get(p.title_ref, "") for p in seen}


def author_fields(sc: Scene, titles: Mapping[int, str], author: str, by: str, level: int, *,
            veiled: bool = False) -> dict[str, str]:
    """Qui a écrit un élément ou une note : sa sorte (``author_kind`` — elle, la personne connectée, une autre
    personne, un autre projet, l'hôte du dépôt) et ses mots (``author``). Une autre personne n'est nommée que si elle
    a le droit de le savoir (``nameable``), un autre projet que si elle le voit (``titles`` : ``writing_projects``) ; rien
    n'est nommé d'un élément qu'elle ne lit pas. Le compte de qui écrit chez l'hôte n'est jamais ici."""
    if author == c.BY_SELF:
        return {"author_kind": BY_HER, "author": self_c.name_of(sc.frame.get(self_c.PERSONA))}
    if author == c.BY_HOST:
        return {"author_kind": BY_HOST, "author": HOST_WORDS}
    if project := c.asking_project(author):
        title = "" if veiled else titles.get(project, "")
        return {"author_kind": BY_PROJECT, "author": NAMED_PROJECT_WORDS.format(title=title) if title else PROJECT_WORDS}
    person = person_of(sc.frame, by) if by else ""
    if person and person == sc.person:
        return {"author_kind": BY_YOU, "author": YOU_WORDS}
    known = bool(person) and not veiled and nameable(sc, person, level)
    name = (identity_c.person_name(sc.frame, by) or person_name(sc, person)) if known else ""
    return {"author_kind": BY_OTHER, "author": name or OTHER_WORDS}
