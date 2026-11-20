"""Les liens de lecture entre projets (ADR 0257) : un projet en lit d'autres, sans jamais y écrire.

- le réducteur garde ce qui tient : des projets qui existent, jamais lui-même, quatre au plus — et aucun lien qui
  fermerait une boucle, quelle que soit la suite des événements ;
- un projet lit ceux du même propriétaire ; celui d'un autre, seulement si une ligne d'accès le lui partage (la
  ligne par défaut n'ouvre pas un lien) ;
- ce que le lien donne se lit dans les lignes d'accès du projet lu : elles ouvrent (son titre, puis son détail, ses
  fichiers, lui adresser une demande), réduisent et coupent ; hors de toute conversation, la ligne la plus serrée
  décide ; un projet qui n'est plus visible suspend le lien, sans le retirer ;
- la confidentialité suit le lien : ce que le lecteur écrit prend le niveau et les sujets de ce qu'il lit, de
  lecteur en lecteur, et retirer un lien ne retire rien ;
- une exécution lit, de chaque projet lié, ce que la matrice donne — et tait le reste ;
- un plan demande un lien : il se pose quand le propriétaire du projet valide le plan, pas quand un autre le valide.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects import links
from mika.faculties.projects.faculty import (
    LINKS_MAX,
    LINKS_SET,
    NOTED,
    PLAN_ANSWERED,
    PLAN_PROPOSED,
    PROJECTS,
    REFRAMED,
    Project,
    ProjectsState,
    _links_set,
    _plan_proposed,
    _reframed,
    frame_subject,
    linked,
    objectives_of,
    opened,
    reaches,
    written,
)
from mika.faculties.projects.faculty import params as projects_params
from mika.faculties.projects.inspect import READERS_TITLE, READS_TITLE
from mika.faculties.projects.prompt import _link_refs, _links_section, _run_section, _texts
from mika.faculties.projects.steer import SteerArgs, project_steer
from mika.faculties.projects.tools import (
    CreateArgs,
    DecideArgs,
    NoteArgs,
    PlanArgs,
    ReportArgs,
    create_project,
    project_decide,
    project_note,
    project_plan,
    report_run,
)
from mika.kernel.events import Content, Origin
from mika.kernel.state import FrozenDict
from mika.runtime.operations import dynamic_fields, perform
from mika.vocab.access import (
    ACCOUNT,
    ALONE,
    AT_OWNER,
    CLOSE,
    EVERYONE,
    INTERNAL,
    OWNER,
    PERSON,
    SELF,
    STEER_ASK,
    STEER_EDIT,
    STEER_NO,
    STEER_READ,
    WORK,
)
from mika.vocab.canals import CanalRule, Canals, CanalTable
from mika.vocab.episodes import Kind, project_target
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from tests.fixtures.mika import connect, said
from tests.unit.test_project_access import set_access
from tests.unit.test_projects import create, events, form, live
from tests.unit.test_projects_console import tab, tables
from tests.unit.test_projects_framing import _asked_project, _ctx

PM = projects_params(None)
PERSONAL, CONFIDENCE = int(Sensitivity.PERSONAL), int(Sensitivity.CONFIDENCE)
#: Adrien s'occupe d'elle ; Bea a un compte, sans plus
WORLD = links.World(keeper={"adrien"}.__contains__)


def _cx():
    return SimpleNamespace(params=PM, facts=SimpleNamespace(get=lambda key: None))


def _ev(data, at: int = 0, correlation: str = "e"):
    return SimpleNamespace(correlation=correlation, at=at, seq=at, data=data)


def _project(pid: int, owner: str | None = "adrien", **fields) -> Project:
    """Un projet confié à ``owner`` (``None`` : un projet à elle), jamais réglé."""
    authority = c.USER if owner else c.SELF
    about = fields.pop("about", (owner,) if owner else ())
    return Project(id=pid, title_ref=f"t{pid}", authority=authority, created_at=0, owner=owner, about=about, **fields)


def _state(*projects: Project) -> ProjectsState:
    return ProjectsState(projects=FrozenDict({p.id: p for p in projects}))


def _read(s: ProjectsState, reader: int, *reads: int) -> ProjectsState:
    return _links_set(s, _ev(LINKS_SET.payload(project=reader, reads=reads, by="adrien")), _cx())


def _line(*who: str, **columns) -> c.ProjectAccess:
    return c.ProjectAccess(who=who, **columns)


# ── Le réducteur, et la règle sans boucle ──────────────────────────────────


def test_the_reducer_keeps_what_can_be_read_and_ignores_the_rest():
    """Total : un projet inconnu, lui-même, un doublon et ce qui dépasse quatre liens sont ignorés, sans erreur."""
    s = _state(*(_project(i) for i in range(1, 8)))
    s = _read(s, 1, 2, 2, 99, 1, 3, 4, 5, 6, 7)
    assert s.projects[1].reads == (2, 3, 4, 5) and len(s.projects[1].reads) == LINKS_MAX == 4
    assert _read(s, 99, 1, 2) is s  # un projet inconnu : rien ne change
    assert _read(s, 1).projects[1].reads == ()  # tout retirer : la liste vide
    assert PROJECTS.state_version >= 13  # rien à convertir : l'état se reconstruit du journal


def test_links_never_form_a_loop():
    """1 lit 2, 2 lit 3 : 3 ne peut lire ni 1 ni 2 — le réducteur ignore le lien, et la règle le dit à qui le pose."""
    s = _read(_read(_state(*(_project(i) for i in (1, 2, 3, 4))), 1, 2), 2, 3)
    assert reaches(s.projects, 1, 3) and not reaches(s.projects, 3, 1)
    assert _read(s, 3, 1).projects[3].reads == ()  # il fermerait la boucle : ignoré
    assert _read(s, 3, 1, 4, 2).projects[3].reads == (4,)  # le reste de la liste tient
    assert _read(s, 2, 2).projects[2].reads == ()  # jamais lui-même
    assert linked(s.projects, 3, (1, 2, 4)) == (4,)
    three = s.projects[3]
    assert links.refusal(s, three, 1, WORLD) == links.LOOP and links.refusal(s, three, 2, WORLD) == links.LOOP
    assert links.refusal(s, three, 3, WORLD) == links.ITSELF and links.refusal(s, three, 99, WORLD) == links.UNKNOWN
    assert links.refusal(s, three, 4, WORLD) == ""
    assert [t.id for t in links.candidates(s, three, WORLD)] == [4]  # ce qu'on lui propose : sans boucle possible


@settings(max_examples=150, deadline=None)
@given(st.lists(st.tuples(st.integers(1, 6), st.lists(st.integers(0, 7), max_size=6)), max_size=40))
def test_whatever_the_events_no_project_ever_reads_itself_through_others(steps):
    """La propriété : après n'importe quelle suite de ``links_set``, suivre les liens d'un projet n'y ramène jamais."""
    s = _state(*(_project(i) for i in range(1, 7)))
    for reader, asked in steps:
        s = _read(s, reader, *asked)
        for p in s.projects.values():
            assert len(p.reads) <= LINKS_MAX and len(set(p.reads)) == len(p.reads)
            assert not any(reaches(s.projects, target, p.id) for target in p.reads), (p.id, p.reads)


# ── Quels projets un projet peut lire ──────────────────────────────────────


def test_a_project_of_another_owner_is_readable_only_when_a_line_shares_it():
    produit, site = _project(1), _project(2)  # à Adrien, jamais réglés
    de_bea, a_elle, archive = _project(3, "bea"), _project(4, None), _project(5, status=c.ARCHIVED)
    s = _state(produit, site, de_bea, a_elle, archive)
    # le même propriétaire : toujours ; un projet à elle lit ceux qu'on lui laisse (la ligne « elle seule »)
    assert links.refusal(s, site, produit.id, WORLD) == ""
    assert links.refusal(s, a_elle, produit.id, WORLD) == "" and links.refusal(s, produit, a_elle.id, WORLD) == ""
    # un autre propriétaire, sans ligne qui le désigne : la ligne par défaut (« les autres le voient ») ne partage rien
    assert links.refusal(s, de_bea, produit.id, WORLD) == links.UNSHARED
    assert [t.id for t in links.candidates(s, de_bea, WORLD)] == []
    opened_by_default = replace(produit, access=(), default_access=_line(see=True, steer=STEER_EDIT, files=True))
    assert links.refusal(_state(opened_by_default, de_bea), de_bea, 1, WORLD) == links.UNSHARED
    # une ligne qui la nomme le lui partage ; « tout le monde » aussi
    for who in (PERSON + "bea", EVERYONE):
        shared = replace(produit, access=(*c.UNSET, _line(who, see=True)), default_access=c.UNSET_DEFAULT)
        assert links.refusal(_state(shared, de_bea), de_bea, 1, WORLD) == "", who
    # jamais un projet archivé
    assert links.refusal(s, site, archive.id, WORLD) == links.ARCHIVED
    # qui pose un lien : son propriétaire ; pour un projet à elle, quelqu'un qui s'occupe d'elle
    assert links.may_link(de_bea, "bea", WORLD) and not links.may_link(de_bea, "adrien", WORLD)
    assert links.may_link(a_elle, "adrien", WORLD) and not links.may_link(a_elle, "bea", WORLD)
    assert not links.may_link(produit, "", WORLD)


def test_at_most_four_links_and_a_link_already_set_stays_even_suspended():
    s = _state(*(_project(i) for i in range(1, 8)))
    assert links.chosen(s, s.projects[1], (2, 3, 4, 5, 6), WORLD) == ((2, 3, 4, 5), ((6, links.FULL),))
    s = _read(s, 1, 2, 3)
    hidden = replace(s.projects[2], access=(_line(OWNER),), default_access=c.CLOSED)  # Adrien ne le voit plus
    s = _state(*(hidden if p.id == 2 else p for p in s.projects.values()))
    assert links.refusal(s, s.projects[4], 2, WORLD) == ""  # le même propriétaire : il peut encore le lier…
    assert links.grant(s.projects[4], s.projects[2], WORLD) == links.NOTHING  # … mais le lien ne donnerait rien
    assert links.chosen(s, s.projects[1], (2, 3, 4), WORLD) == ((2, 3, 4), ())  # déjà posé : il reste


# ── Ce que le lien donne ───────────────────────────────────────────────────


def test_the_matrix_opens_what_a_link_gives_step_by_step():
    """Le voir : son titre et son état. Le piloter, au moins en lecture seule : son détail. Ses fichiers : la vue de
    son atelier. Le piloter sur accord ou en modification : lui adresser une demande."""
    def given_to_bea(**columns) -> links.Grant:
        return links.granted((_line(PERSON + "bea", **columns),), ACCOUNT, "bea")

    nothing = links.granted(c.UNSET, ACCOUNT, "bea")  # aucune ligne ne la désigne
    assert nothing == links.NOTHING and not (nothing.see or nothing.detail or nothing.view) and nothing.ask == STEER_NO
    seen = given_to_bea(see=True)
    assert seen.see and not seen.detail and not seen.view and seen.ask == STEER_NO
    read = given_to_bea(see=True, steer=STEER_READ)
    assert read.detail and not read.view and read.ask == STEER_NO
    files = given_to_bea(see=True, steer=STEER_READ, files=True)
    assert files.detail and files.view
    assert given_to_bea(see=True, steer=STEER_ASK).ask == STEER_ASK
    assert given_to_bea(see=True, steer=STEER_EDIT).ask == STEER_EDIT
    # sans le voir, rien — même si le reste est coché
    assert given_to_bea(steer=STEER_EDIT, files=True) == links.NOTHING
    # un projet jamais réglé : une de ses propriétaires et elle seule ont tout ; qui l'a confié, ses fichiers et
    # l'accord du propriétaire
    assert links.granted(c.UNSET, AT_OWNER) == links.Grant(True, STEER_EDIT, True)
    assert links.granted(c.UNSET, WORK) == links.Grant(True, STEER_EDIT, True)
    confided = (*c.UNSET, _line(PERSON + "bea", see=True, steer=STEER_ASK, files=True))
    assert links.granted(confided, ACCOUNT, "bea") == links.Grant(True, STEER_ASK, True)


def test_outside_any_conversation_the_tightest_line_decides():
    """Une exécution n'a ni canal ni personne en face : le propriétaire du lecteur n'a que ce que les lignes lui
    donnent par tous les canaux et à tout moment."""
    bea = PERSON + "bea"
    wide, narrow = dict(see=True, steer=STEER_EDIT, files=True), dict(see=True)
    # ouverte sur le chat web seulement, puis réduite partout : le lien n'a que le réduit
    assert links.granted((_line(bea, canal=("web",), **wide), _line(bea, **narrow)), ACCOUNT, "bea") == \
        links.Grant(True, STEER_NO, False)
    # réduite quand elle répond, ouverte sinon : selon le moment, l'une ou l'autre déciderait — la plus serrée
    assert links.granted((_line(bea, when=("conversation",), **narrow), _line(bea, **wide)), ACCOUNT, "bea") == \
        links.Grant(True, STEER_NO, False)
    # fermée par un canal : rien, même si une ligne ouvre plus bas
    assert links.granted((_line(bea, canal=("web",)), _line(bea, **wide)), ACCOUNT, "bea") == links.NOTHING
    # aucune ligne qui vaille partout et toujours : rien (la ligne par défaut n'ouvre pas un lien)
    assert links.granted((_line(bea, canal=("web",), **wide),), ACCOUNT, "bea") == links.NOTHING
    assert links.granted((_line(bea, when=("conversation",), **wide),), ACCOUNT, "bea") == links.NOTHING
    # la première ligne qui vaut partout décide : ce qui la suit ne compte plus
    assert links.granted((_line(bea, **wide), _line(bea)), ACCOUNT, "bea") == links.Grant(True, STEER_EDIT, True)
    # « tes proches » : seulement si elle l'est
    close = (_line(CLOSE, see=True, steer=STEER_READ),)
    assert links.granted(close, ACCOUNT, "bea", {"bea"}.__contains__).detail
    assert links.granted(close, ACCOUNT, "bea") == links.NOTHING
    # un projet à elle : la ligne qui la désigne par « elle seule » ; sans elle, rien
    assert links.granted((_line(OWNER, **wide),), WORK) == links.NOTHING
    assert links.granted((_line(SELF, canal=(INTERNAL,), see=True, steer=STEER_READ),), WORK).detail
    # la porte du canal « elle seule » serre encore le pilotage et les fichiers (les deux portes)
    shut = Canals(tables={INTERNAL: CanalTable(lines=(CanalRule(
        who=(SELF,), canal=(INTERNAL,), reply="seule", read=ALONE, act=ALONE, steer=STEER_READ, files=False),))})
    assert links.granted((_line(bea, **wide),), ACCOUNT, "bea", through=links.door(shut)) == \
        links.Grant(True, STEER_READ, False)
    assert links.granted((_line(bea, **wide),), ACCOUNT, "bea", through=links.door(None)) == \
        links.Grant(True, STEER_EDIT, True)  # jamais réglé : elle seule passe tout


def test_a_right_taken_back_cuts_the_link_and_an_invisible_project_suspends_it():
    produit, de_bea = _project(1), _project(2, "bea")
    shared = replace(produit, access=(*c.UNSET, _line(PERSON + "bea", see=True, steer=STEER_READ, files=True)),
                     default_access=c.UNSET_DEFAULT)
    s = _read(_state(shared, de_bea), 2, 1)
    [reading] = links.readings(s, s.projects[2], WORLD)
    assert not reading.suspended and reading.grant.detail and links.views_workshop(s, 2, 1, WORLD)
    assert [(r.id, g.detail) for r, g in links.readers(s, s.projects[1], WORLD)] == [(2, True)]  # « Qui le lit »

    def with_line(*lines: c.ProjectAccess) -> ProjectsState:
        return _state(replace(s.projects[1], access=(*c.UNSET, *lines)), s.projects[2])

    # réduit : plus que le titre ; ses fichiers retirés : plus de vue de l'atelier
    reduced = with_line(_line(PERSON + "bea", see=True))
    [reading] = links.readings(reduced, reduced.projects[2], WORLD)
    assert not reading.suspended and not reading.grant.detail and not links.views_workshop(reduced, 2, 1, WORLD)
    # coupé : le lien reste posé, il ne donne plus rien
    cut = with_line()
    [reading] = links.readings(cut, cut.projects[2], WORLD)
    assert reading.suspended and reading.grant == links.NOTHING and cut.projects[2].reads == (1,)
    assert [g.see for _, g in links.readers(cut, cut.projects[1], WORLD)] == [False]
    # archivé : suspendu aussi ; restauré, il revient
    archived = _state(replace(s.projects[1], status=c.ARCHIVED), s.projects[2])
    assert links.readings(archived, archived.projects[2], WORLD)[0].suspended
    assert not links.readings(s, s.projects[2], WORLD)[0].suspended
    # la vue de l'atelier : seulement pour un projet qu'il lit
    assert not links.views_workshop(s, 1, 2, WORLD) and not links.views_workshop(s, 2, 99, WORLD)


# ── La confidentialité suit le lien ────────────────────────────────────────


def test_what_the_reader_writes_takes_the_level_and_the_subjects_of_what_it_reads():
    produit = _project(1, about=("adrien", "carla"), sensitivity=CONFIDENCE)
    veille, bilan = _project(2, "bea", sensitivity=PERSONAL), _project(3, "dan")
    s = _state(produit, veille, bilan)
    assert written(s.projects[2]) == PERSONAL
    s = _read(s, 3, 2)  # le bilan lit la veille, avant que la veille ne lise le produit
    assert s.projects[3].about == ("dan", "bea") and written(s.projects[3]) == PERSONAL
    s = _read(s, 2, 1)
    reader = s.projects[2]
    # ses sujets reçoivent le propriétaire et les sujets du projet lu ; ce qu'il écrit prend son niveau
    assert reader.about == ("bea", "adrien", "carla") and reader.read_about == ("adrien", "carla")
    assert reader.read_level == written(produit) == CONFIDENCE and written(reader) == CONFIDENCE
    assert reader.sensitivity == PERSONAL  # son cadre à lui ne change pas
    # de lecteur en lecteur : le bilan, qui lit la veille, les reçoit aussi
    assert s.projects[3].about == ("dan", "bea", "adrien", "carla") and written(s.projects[3]) == CONFIDENCE
    # retirer le lien ne retire rien : ce qu'elle en a lu est déjà dans ses notes
    gone = _read(s, 2)
    assert gone.projects[2].reads == () and gone.projects[2].about == reader.about
    assert written(gone.projects[2]) == CONFIDENCE and gone.projects[2].read_about == ("adrien", "carla")


def test_a_change_in_the_project_read_reaches_its_readers():
    s = _read(_read(_state(_project(1), _project(2, "bea"), _project(3, "dan")), 2, 1), 3, 2)
    assert written(s.projects[3]) == PERSONAL
    # le projet lu devient plus sensible : ce qu'écrivent ses lecteurs suit
    raised = _reframed(s, _ev(REFRAMED.payload(project=1, sensitivity=CONFIDENCE)), _cx())
    assert written(raised.projects[2]) == written(raised.projects[3]) == CONFIDENCE
    # il change de propriétaire : ses lecteurs reçoivent le nouveau sujet
    moved = _reframed(s, _ev(REFRAMED.payload(project=1, set_owner=True, owner="eve", about=("eve",))), _cx())
    assert "eve" in moved.projects[2].about and "eve" in moved.projects[3].about
    # le lecteur change de « pour qui » : les sujets venus de ses lectures restent
    again = _reframed(s, _ev(REFRAMED.payload(project=2, set_owner=True, owner="fay", about=("fay",))), _cx())
    assert again.projects[2].about == ("fay", "adrien") and again.projects[2].owner == "fay"
    assert "fay" in again.projects[3].about  # et son propre lecteur le reçoit à son tour


def test_what_she_writes_in_the_reader_carries_the_subjects_and_the_level(tmp_path):
    """Dans un vrai noyau : un projet de Bea, lu par un projet d'Adrien — ce qu'elle note et conclut ensuite chez
    Adrien nomme Bea parmi ses sujets, au niveau de ce qu'elle a lu : l'oubli de Bea l'atteindra."""

    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Bea")
        frame = kernel.mind.frame()
        bea = frame.get(identity_c.PERSON("user_2"))
        theirs = await create(kernel, "p1", title="Le carnet de Bea", objectives="Tenir le carnet", owner="user_2")
        mine = await create(kernel, "p2", title="La veille", constants="Veiller", cadence_hours="24")
        before = kernel.mind.frame().state("projects").projects[mine]
        got = await perform(kernel, "projects.liens", form(**{f"lit_{theirs}": "on"}), by="user_1", subject=str(mine),
                            nonce="l1")
        [oid] = [o.id for o in before.objectives]
        subject = f"objective:{mine}:{oid}"
        await project_note(NoteArgs(text="le carnet avance bien"),
                           _ctx(kernel, "project_note", Kind.WORK, project_target(mine), subject=subject))
        await report_run(ReportArgs(verdict=c.CONTINUE, summary="Lu le carnet de Bea."),
                         _ctx(kernel, "report_run", Kind.WORK, project_target(mine), subject=subject))
        after = kernel.mind.frame().state("projects")
        return got, bea, before, after.projects[mine], after.projects[theirs], \
            [e for e in events(kernel, NOTED) if e.data.project == mine][-1], \
            [e for e in events(kernel, c.RUN_REPORTED) if e.data.project == mine][-1], events(kernel, LINKS_SET)

    got, bea, before, reader, target, noted, reported, set_ = live(tmp_path, scenario)
    assert got.ok, got
    assert [e.data.reads for e in set_] == [(target.id,)] and set_[0].data.by == "user_1"
    assert bea not in before.about and bea in reader.about and reader.reads == (target.id,)
    assert written(reader) >= written(target) >= PERSONAL
    assert bea in noted.data.about and bea in reported.data.about  # l'oubli de Bea atteint ce qu'elle écrit ensuite
    assert noted.data.text.level == reported.data.summary.level == written(reader)


# ── La console : ce qu'il lit, qui le lit ──────────────────────────────────


def test_the_fiche_sets_what_it_reads_and_shows_who_reads_it(tmp_path):
    async def scenario(kernel, llm):
        produit = await create(kernel, "p1", title="Le produit", objectives="Écrire le module")
        connaitre = await create(kernel, "p2", title="Faire connaître", objectives="Écrire un article")
        spec = kernel.registry.actions["projects.liens"]
        out = {"fields": {f.path: f.label for f in dynamic_fields(kernel, spec, str(connaitre), {})}}
        out["none"] = await perform(kernel, "projects.liens", form(), by="user_1", subject=str(connaitre), nonce="l0")
        out["set"] = await perform(kernel, "projects.liens", form(**{f"lit_{produit}": "on"}), by="user_1",
                                   subject=str(connaitre), nonce="l1")
        out["reads"] = kernel.mind.frame().state("projects").projects[connaitre].reads
        # dans l'autre sens, il fermerait une boucle : la case n'est même pas proposée
        out["back"] = {f.path for f in dynamic_fields(kernel, spec, str(produit), {})}
        out["loop"] = await perform(kernel, "projects.liens", form(**{f"lit_{connaitre}": "on"}), by="user_1",
                                    subject=str(produit), nonce="l2")
        out["stranger"] = await perform(kernel, "projects.liens", form(), by="user_9", subject=str(connaitre),
                                        nonce="l3")
        out["reader"] = tables(await tab(kernel, "comportement", str(connaitre)))
        out["read"] = tables(await tab(kernel, "comportement", str(produit)))
        out["unset"] = await perform(kernel, "projects.liens", form((f"lit_{produit}",)), by="user_1",
                                     subject=str(connaitre), nonce="l4")
        out["end"] = kernel.mind.frame().state("projects").projects[connaitre].reads
        return produit, connaitre, out

    produit, connaitre, out = live(tmp_path, scenario)
    assert out["fields"] == {f"lit_{produit}": f"n° {produit} — Le produit"}
    assert not out["none"].ok and "Rien n'a changé" in out["none"].message
    assert out["set"].ok and f"n° {produit}" in out["set"].message and out["reads"] == (produit,)
    assert out["back"] == set() and not out["loop"].ok  # aucune boucle à cocher
    assert not out["stranger"].ok and "propriétaire" in out["stranger"].message  # seul son propriétaire le pose
    [row] = out["reader"][READS_TITLE].rows  # « Ce qu'il lit » : le produit, et tout ce que le lien donne
    assert f"n° {produit} — Le produit" in row[0].text and "ses comptes rendus" in row[2].text
    assert out["reader"][READERS_TITLE].rows == ()
    [who] = out["read"][READERS_TITLE].rows  # « Qui le lit », sur la fiche du projet lu
    assert f"n° {connaitre} — Faire connaître" in who[0].text and who[1].text == "Adrien"
    assert out["read"][READS_TITLE].rows == ()
    assert out["unset"].ok and out["end"] == ()


# ── Ce qu'une exécution lit des projets liés ───────────────────────────────


async def _worked(kernel, pid: int, oid: int, *summaries: str) -> None:
    for text in summaries:
        await report_run(ReportArgs(verdict=c.CONTINUE, summary=text),
                         _ctx(kernel, "report_run", Kind.WORK, project_target(pid), subject=f"objective:{pid}:{oid}"))


async def _links_text(kernel, pid: int) -> tuple[str | None, dict[str, str]]:
    """La section « CE QUE CE PROJET LIT » d'une exécution de ce projet, avec les textes que son enrichisseur a lus."""
    run = _ctx(kernel, "report_run", Kind.WORK, project_target(pid))
    s = run.frame.state("projects")
    enriched = await _texts(s, run.frame, kernel.ports)
    body = _links_section(s, run.frame, {"projects": enriched})
    return (body.content if body is not None else None), dict(enriched["texts"])


def test_a_run_reads_of_each_linked_project_what_the_matrix_gives(tmp_path):
    async def scenario(kernel, llm):
        produit = await create(kernel, "p1", title="Le produit", objectives="Écrire le module\nLe documenter")
        connaitre = await create(kernel, "p2", title="Faire connaître", objectives="Écrire un article")
        first = kernel.mind.frame().state("projects").projects[produit].objectives[0].id
        await _worked(kernel, produit, first, "Le squelette est posé.", "Les tests passent.", "La version 2 est prête.")
        await project_decide(DecideArgs(title="Le langage", choice="Python", reason="déjà dans l'équipe"),
                             _ctx(kernel, "project_decide", Kind.WORK, project_target(produit)))
        out = {"alone": await _links_text(kernel, connaitre)}
        got = await perform(kernel, "projects.liens", form(**{f"lit_{produit}": "on"}), by="user_1",
                            subject=str(connaitre), nonce="l1")
        assert got.ok, got
        out["full"] = await _links_text(kernel, connaitre)
        # son propriétaire ne laisse plus que le voir : le titre et l'état, rien de son détail
        await set_access(kernel, produit, {"who": [OWNER], "see": True}, nonce="a1")
        out["seen"] = await _links_text(kernel, connaitre)
        frame = kernel.mind.frame()
        out["refs"] = _link_refs(frame.state("projects"), frame, frame.state("projects").projects[connaitre])
        # il ne le laisse plus voir : le lien est suspendu, en une ligne
        await set_access(kernel, produit, {"who": [OWNER]}, nonce="a2")
        out["cut"] = await _links_text(kernel, connaitre)
        out["reads"] = kernel.mind.frame().state("projects").projects[connaitre].reads
        # il le rouvre : la lecture revient à l'exécution suivante
        await set_access(kernel, produit, {"who": [OWNER], "see": True, "steer": "lecture"}, nonce="a3")
        out["back"] = await _links_text(kernel, connaitre)
        return produit, kernel.mind.frame().state("projects").projects[produit], out

    produit, p, out = live(tmp_path, scenario)
    assert out["alone"][0] is None  # il ne lit rien : pas de section
    full, texts = out["full"]
    assert phrase("projects.links.head") in full and f"Projet n° {produit} « Le produit » — actif" in full
    assert "0 objectif(s) sur 2 atteints" in full and "Sa dernière exécution" not in full  # jamais lancé par l'arbitre
    assert phrase("projects.links.never_run") in full
    # ses deux derniers comptes rendus, dans l'ordre — pas le plus ancien
    assert "Le squelette est posé." not in full and "Le squelette est posé." not in texts.values()
    assert full.index("Les tests passent.") < full.index("La version 2 est prête.")
    assert "D1 Le langage : Python (parce que : déjà dans l'équipe)" in full  # ses décisions en vigueur
    assert "[ponctuel, ouvert] Écrire le module" in full and "[ponctuel, ouvert] Le documenter" in full
    # ses lignes donnent aussi ses fichiers : la vue de son atelier, dite ici sans avoir été posée (ADR 0260 ; ce
    # qu'elle montre est gardé par ``test_project_workshop_views.py``)
    assert phrase("projects.links.view.later", path=f"liens/{produit}/") in full
    # réduit au titre : ni compte rendu, ni décision, ni objectif — et leurs textes ne sont même pas lus
    seen, seen_texts = out["seen"]
    assert f"Projet n° {produit} « Le produit »" in seen and phrase("projects.links.title_only") in seen
    for hidden in ("Les tests passent.", "La version 2 est prête.", "Python", "Écrire le module"):
        assert hidden not in seen and hidden not in seen_texts.values(), hidden
    assert out["refs"] == [p.title_ref]
    # coupé : le lien reste posé, il se dit en une ligne, et le titre lui-même se tait
    cut, cut_texts = out["cut"]
    assert phrase("projects.links.suspended", id=produit) in cut and "Le produit" not in cut
    assert "Le produit" not in cut_texts.values() and out["reads"] == (produit,)
    assert "Les tests passent." in out["back"][0]


# ── Un plan demande un lien ────────────────────────────────────────────────

PLAN = {"aim": "Faire connaître le produit.", "deliverables": "Un article par semaine.",
        "approach": "Je lis où en est le produit, puis j'écris.",
        "steps": [{"text": "Écrire un article", "kind": "constant", "cadence_hours": 168}]}


def test_a_plan_asks_to_read_a_project_and_the_link_is_set_when_its_owner_approves(tmp_path):
    async def scenario(kernel, llm):
        produit = await create(kernel, "p1", title="Le produit", objectives="Écrire le module")
        cache = await create(kernel, "p2", title="Un projet rangé", objectives="Ranger")
        await perform(kernel, "projects.archiver", form(), by="user_1", subject=str(cache), nonce="x1")
        pid = await _asked_project(kernel)  # un projet à elle, demandé par Adrien : il naît à cadrer
        framing = _ctx(kernel, "project_plan", Kind.WORK, project_target(pid), subject=frame_subject(pid))
        s = framing.frame.state("projects")
        out = {"frame": _run_section(s, framing.frame, {"projects": await _texts(s, framing.frame, kernel.ports)})}
        out["bad"] = await project_plan(PlanArgs.model_validate({**PLAN, "reads": [cache, pid, 999]}), framing)
        out["plan"] = await project_plan(PlanArgs.model_validate({**PLAN, "reads": [produit]}), framing)
        out["waiting"] = kernel.mind.frame().state("projects").projects[pid]
        yes = await kernel.perceive(said("user_1", "vas-y, ça me va"))
        out["approved"] = await project_steer(SteerArgs(project=str(pid), what="approve"),
                                              _ctx(kernel, "project_steer", Kind.REPLY, "user_1", reply_to=yes.seq))
        out["after"] = kernel.mind.frame().state("projects").projects[pid]
        out["adrien"] = kernel.mind.frame().get(identity_c.PERSON("user_1"))
        return produit, cache, pid, out, events(kernel, PLAN_PROPOSED), events(kernel, LINKS_SET), \
            events(kernel, PLAN_ANSWERED)

    produit, cache, pid, out, plans, set_, answers = live(tmp_path, scenario)
    # la séance de cadrage voit ce qu'il peut demander à lire, par son numéro et son titre — pas un projet archivé
    shown = out["frame"].content.split(phrase("projects.frame.readable"), 1)[1]
    assert f"- n° {produit} « Le produit »" in shown and "Un projet rangé" not in shown
    # ce qui ne peut pas être lu fait refuser le plan, avec sa raison
    assert not out["bad"].ok and f"n° {cache} ne peut pas être lu : il est archivé" in out["bad"].content
    assert f"n° {pid} ne peut pas être lu : c'est ce projet lui-même" in out["bad"].content
    assert "n° 999 ne peut pas être lu : il n'existe pas" in out["bad"].content
    # sans question, il attend quand même : ce qu'il demande à lire revient à son propriétaire
    [plan] = plans
    assert plan.data.reads == (produit,) and not plan.data.approved
    assert out["plan"].ends and phrase("projects.tools.plan.reads_wait") in out["plan"].content
    waiting = out["waiting"]
    assert waiting.plan_state == c.PROPOSED and waiting.plan_reads == (produit,) and waiting.reads == ()
    # Adrien le valide : le lien se pose avec le plan, à son nom
    after = out["after"]
    assert after.plan_state == c.PLANNED and after.reads == (produit,)
    assert [(e.data.project, e.data.reads, e.data.by) for e in set_] == [(pid, (produit,), out["adrien"])]
    assert answers[-1].seq < set_[0].seq  # dans le même geste, la réponse puis le lien
    assert "C'est parti" in out["approved"] and f"Il lit maintenant : n° {produit} « Le produit »" in out["approved"]


def test_a_plan_approved_by_someone_who_is_not_its_owner_sets_no_link_and_says_so(tmp_path):
    """Un projet de Bea, demandé par elle : son plan demande à lire le produit d'Adrien, qu'il lui a partagé. Adrien
    valide le plan dans la console : ce n'est pas son projet, le lien ne se pose pas — et le suivi le dit."""

    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Bea")
        produit = await create(kernel, "p1", title="Le produit", objectives="Écrire le module")
        bea = kernel.mind.frame().get(identity_c.PERSON("user_2"))
        made = await kernel.mind.append([opened(
            title="Le guide de Bea", description="", authority=c.USER, mode=c.PERSONA, owner=bea, address="user_2",
            about=(bea,), level=PERSONAL, source="tool", request="écris-moi un guide", asked_by=bea, framing=True)],
            emitter="projects", correlation="bea", origin=Origin.GENESIS)
        pid = made.seqs[-1]
        await kernel.mind.append(objectives_of(pid, ["Écrire le guide"], [], author="owner", owner=bea, about=(bea,),
                                               level=PERSONAL), emitter="projects", correlation="bea",
                                 origin=Origin.GENESIS)
        framing = _ctx(kernel, "project_plan", Kind.WORK, project_target(pid), subject=frame_subject(pid))
        out = {"unshared": await project_plan(PlanArgs.model_validate({**PLAN, "reads": [produit]}), framing)}
        # Adrien le lui partage : une ligne qui la nomme
        await set_access(kernel, produit, {"who": [OWNER], "see": True, "steer": "modification", "files": True},
                         {"who": [PERSON + bea], "see": True, "steer": "lecture"}, nonce="a1")
        framing = _ctx(kernel, "project_plan", Kind.WORK, project_target(pid), subject=frame_subject(pid))
        out["plan"] = await project_plan(PlanArgs.model_validate({**PLAN, "reads": [produit]}), framing)
        out["waiting"] = kernel.mind.frame().state("projects").projects[pid]
        out["said"] = await perform(kernel, "projects.plan_valider", form(), by="user_1", subject=str(pid),
                                    nonce="v1")
        frame = kernel.mind.frame()
        s = frame.state("projects")
        out["after"] = s.projects[pid]
        out["hers"] = links.approved(replace(s, projects=s.projects.set(pid, out["waiting"])), out["waiting"], bea,
                                     links.world_of(frame))
        return produit, bea, out, events(kernel, LINKS_SET)

    produit, bea, out, set_ = live(tmp_path, scenario)
    # tant que rien ne le lui partage, son plan ne peut pas le demander
    assert not out["unshared"].ok
    assert f"n° {produit} ne peut pas être lu : son propriétaire ne le laisse pas voir à ce projet" in \
        out["unshared"].content
    assert out["plan"].ends and out["waiting"].plan_state == c.PROPOSED and out["waiting"].plan_reads == (produit,)
    # validé par Adrien, qui n'en est pas le propriétaire : le plan part, le lien non
    assert out["said"].ok and "n'est pas lié" in out["said"].message and f"n° {produit}" in out["said"].message
    assert out["said"].tone == "warn"
    assert out["after"].plan_state == c.PLANNED and out["after"].reads == () and set_ == []
    assert out["after"].plan_reads == (produit,)  # la fiche montre encore ce que le plan demande
    # validé par Bea, il se serait posé
    assert out["hers"].added == (produit,) and out["hers"].reads == (produit,) and not out["hers"].denied


def test_what_a_plan_asks_to_read_is_set_by_who_may_and_only_while_it_holds():
    """La règle pure : sans rien à lier, rien ; lié par qui peut ; refusé si le projet ne peut plus être lu."""
    produit, de_bea = _project(1), _project(2, "bea")
    shared = replace(produit, access=(*c.UNSET, _line(PERSON + "bea", see=True)))
    s = _state(shared, de_bea)
    assert links.approved(s, de_bea, "bea", WORLD) == links.Approved()  # son plan ne demande rien
    data = PLAN_PROPOSED.payload(project=2, plan=Content(ref="plan"), reads=(1, 2, 1, 9))
    asking = _plan_proposed(s, _ev(data), _cx()).projects[2]
    assert asking.plan_reads == (1, 9)  # ni lui-même, ni deux fois
    s = _state(shared, asking)
    got = links.approved(s, asking, "bea", WORLD)
    assert got.added == (1,) and got.reads == (1,) and got.refused == ((9, links.UNKNOWN),)
    denied = links.approved(s, asking, "adrien", WORLD)
    assert denied.denied and denied.pending == (1, 9) and denied.added == () and denied.reads == ()
    # déjà lié : plus rien à poser
    assert links.approved(_read(s, 2, 1), _read(s, 2, 1).projects[2], "bea", WORLD).added == ()


def test_a_project_confided_in_conversation_reads_what_its_owner_asks(tmp_path):
    async def scenario(kernel, llm):
        produit = await create(kernel, "p1", title="Le produit", objectives="Écrire le module")
        site = await create(kernel, "p2", title="Le site vitrine", objectives="Le mettre en ligne")
        asked = await kernel.perceive(said("user_1", "crée un projet pour faire connaître le produit : il lit le "
                                                     "produit et le site"))
        here = _ctx(kernel, "create_project", Kind.REPLY, "user_1", reply_to=asked.seq)
        back = await create_project(CreateArgs(title="Faire connaître", objectives=["Écrire un article"],
                                               reads=[produit, "le site vitrine", "un projet inconnu"]), here)
        if asked.reply is not None:
            await asked.reply
        pid = events(kernel, c.PROJECT_CREATED)[-1].seq
        return produit, site, back, kernel.mind.frame().state("projects").projects[pid], events(kernel, LINKS_SET)

    produit, site, back, p, set_ = live(tmp_path, scenario)
    assert p.reads == (produit, site) and [e.data.reads for e in set_] == [(produit, site)]
    assert f"Il lit : n° {produit} « Le produit », n° {site} « Le site vitrine »." in back
    assert "Aucun projet à lire ne correspond à « un projet inconnu »" in back  # il naît quand même, et le dit
    assert "naît à cadrer" in back
