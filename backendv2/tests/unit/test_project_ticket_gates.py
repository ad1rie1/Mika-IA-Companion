"""Ce qu'un ticket laisse lire, valider et oublier (ADR 0272) : les garde-fous du registre.

- un élément garde le niveau de ses textes : en conversation, son titre, son texte et ses notes ne se disent qu'à qui
  entend ce niveau ; le texte d'une demande encore proposée, qu'à qui peut la trancher ; ce que le projet visé en
  écrit ensuite est au moins de ce niveau ;
- un ticket proposé ne se lit qu'en une ligne sans texte pendant une exécution, et elle ne le ferme pas ;
- une validation par elle ne vaut qu'une fois, pour un ticket qui n'a ni objectif ni diff compté ; un ticket qui a
  dépassé sa borne le garde, et un « fait » ne s'écrit pas tant qu'il attend le propriétaire ;
- les fichiers de dépendances se reconnaissent à leur forme et à leur dossier ; un chemin accentué se lit tel quel ;
- un ticket rouvert que l'état ne gardait plus revient avec son numéro : son objectif le retrouve ;
- « Traiter les tickets » revient à une cadence de secours tant qu'un ticket a la main chez elle, et ne naît qu'une
  fois ;
- un objectif rouvert après la fermeture de son ticket est retiré de nouveau, sans que le processus tourne à vide ;
- une validation nomme le plan lu : un plan réécrit entre-temps ne se valide pas à sa place.

L'oubli de ce que le projet visé écrit sur une demande est gardé par le parcours entier de ``test_project_asks``.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from mika.adapters.workshop import BwrapWorkshop
from mika.contracts import projects as c
from mika.faculties.projects import faculty, rhythm, tickets, tracker, triage, triggers
from mika.faculties.projects.demands import AskArgs, project_ask
from mika.faculties.projects.faculty import (
    ITEMS_RECENT,
    NUDGED,
    OBJECTIVE_ADDED,
    OBJECTIVE_CHANGED,
    Item,
    Objective,
    objective_at,
)
from mika.faculties.projects.prompt import _items, _items_section
from mika.faculties.projects.tools import ReportArgs, report_run
from mika.faculties.projects.tracker import ITEM_NOTED
from mika.faculties.projects.tracker_tools import (
    AddArgs,
    ChangeArgs,
    ItemArg,
    ListArgs,
    ReadArgs,
    WriteArgs,
    items_add,
    items_change,
    items_list,
    project_item,
    project_items,
)
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult
from mika.runtime.operations import perform
from mika.vocab.access import OWNER, PERSON
from tests.fixtures.mika import connect
from tests.unit.test_project_access import facing, set_access, talking
from tests.unit.test_project_asks import ASK, _asking, _link, _oid, _run_frame, _state_of
from tests.unit.test_project_links import CONFIDENCE, PERSONAL, PM, _cx, _ev, _project, _state
from tests.unit.test_project_links_audience import _confidence, _heard
from tests.unit.test_project_milestones import reach_all
from tests.unit.test_project_tickets import PLAN, K, _do, _entry, _note, _plan, _step, _ticket
from tests.unit.test_project_tracker import _add, _board, _run
from tests.unit.test_projects import _run_context, create, events, live, row_form, wait

T = c.TICKETS
ADRIEN = {"author": c.BY_PERSON, "by": "adrien"}


def _words(got) -> str:
    return got.content if isinstance(got, ToolResult) else got


def _objective(s, number: int, at: int, **fields):
    data = OBJECTIVE_ADDED.payload(project=1, objective=number, text=Content(ref=f"{at}.text"), **fields)
    return faculty._objective_added(s, _ev(data, at), _cx())


# ── Les règles, pures ──────────────────────────────────────────────────────


def test_a_proposed_ticket_is_never_closed_as_treated_before_it_is_accepted():
    s = _add(_state(_project(1)), T, K, at=10, proposed=True, author=c.BY_PERSON, by="bea")
    assert _step(s, c.STAGE_PROPOSED, 11, closed=c.DONE) is s  # elle, avant tout accord
    assert _step(s, c.STAGE_PROPOSED, 12, closed=c.DONE, author=c.BY_OPERATOR, by="adrien") is s
    assert _ticket(_step(s, c.STAGE_PROPOSED, 13, closed=c.DROPPED, **ADRIEN)).status == c.STAGE_DISMISSED
    # accepté puis fermé dans le même geste : l'accord y est
    assert _ticket(_step(s, c.STAGE_PROPOSED, 14, accepted=True, closed=c.DONE, **ADRIEN)).status == c.STAGE_TREATED


def test_an_item_keeps_the_level_of_its_texts_and_what_is_written_on_it_is_at_least_that_level():
    p = _project(1)
    assert tracker.adding(p, T, K, "Un titre", text="Un texte", level=CONFIDENCE).data.title.level == CONFIDENCE
    data = tracker.ITEM_ADDED.payload(project=1, list_name=T, key=K, title=Content(ref="1.title", level=PERSONAL),
                                      text=Content(ref="1.text", level=CONFIDENCE), author=c.item_author(2))
    item = tracker.added(data, 10, 1, 1)
    assert item.level == CONFIDENCE and faculty.written_on(p, item) == CONFIDENCE > faculty.written(p)
    # une note, un changement, le plan validé et l'objectif qui en naît : au niveau de l'élément, avec ses sujets
    asked = replace(item, by="zoe", person="paul", plan_seq=5, status=c.STAGE_VALIDATION)
    note = tracker.noting(p, asked, "Une note").data
    change = tracker.changing(p, asked, note="Parce que.", title="Un autre titre").data
    assert (note.text.level, change.note.level, change.title.level) == (CONFIDENCE,) * 3
    assert set(note.read_about) == set(change.read_about) == {"zoe", "paul"}
    changed, born, *posed = tracker.validating(p, asked, "Changer ceci\n\nJalons :\n1. un", comment="Vas-y.",
                                               **ADRIEN)
    # les jalons du plan naissent avec l'objectif, au même niveau et avec les mêmes sujets (ADR 0273)
    assert [(m.data.objective, m.data.milestone, m.data.text.text, m.data.text.level, set(m.data.read_about))
            for m in posed] == [(born.data.objective, 1, "un", CONFIDENCE, {"zoe", "paul"})]
    assert (changed.data.plan, changed.data.number, changed.data.level) == (5, 1, CONFIDENCE)
    assert (born.data.text.level, born.data.done_when.level, born.data.brief.level) == (CONFIDENCE,) * 3
    assert set(born.data.read_about) == {"zoe", "paul"}
    # un texte changé relève le niveau de l'élément, jamais ne le baisse
    low = tracker.added(tracker.ITEM_ADDED.payload(project=1, list_name="suivi", key="a",
                                                   title=Content(ref="2.title", level=PERSONAL)), 10, 2, 0)
    raised = tracker.changed(low, tracker.ITEM_CHANGED.payload(
        project=1, list_name="suivi", key="a", was=low.status, text=Content(ref="3.text", level=CONFIDENCE)), 11, 3)
    assert (low.level, raised.level) == (PERSONAL, CONFIDENCE)


def test_who_reads_an_item_is_judged_on_its_level_and_on_whether_it_is_still_proposed():
    hers = Item(T, K, number=3, status=c.STAGE_PROPOSED, proposed=True, author=c.BY_PERSON, by="bea",
                level=PERSONAL)
    asked = replace(hers, author=c.item_author(2), by="", level=CONFIDENCE)
    friend, owner = tracker.Reader(level=PERSONAL), tracker.Reader(level=CONFIDENCE, settles=True)
    # pendant une exécution, un ticket proposé n'est pas encore à elle : une ligne, sans titre
    assert tracker.veiled(tracker.RUN, hers) == tracker.veiled(tracker.RUN, asked) == tracker.PROPOSED_VEIL
    assert tracker.veiled(tracker.RUN, replace(asked, proposed=False, status=c.STAGE_UNREAD)) == ""
    # en conversation : le ticket proposé d'une personne se lit ; la demande d'un projet, par qui peut la trancher
    assert tracker.veiled(friend, hers) == "" and tracker.veiled(owner, asked) == ""
    assert tracker.veiled(tracker.Reader(level=CONFIDENCE), asked) == tracker.PROPOSED_VEIL
    assert tracker.veiled(friend, replace(asked, proposed=False, status=c.STAGE_UNREAD)) == tracker.LEVEL_VEIL
    assert tracker.veiled(tracker.Reader(level=-1), replace(hers, level=0, status=c.STAGE_UNREAD)) == tracker.LEVEL_VEIL


def test_a_request_pours_its_people_into_the_target_for_forgetting_only_and_down_to_its_readers():
    site = _project(1, owner="bea", about=("bea",))
    reader = _project(3, owner="dan", about=("dan",), reads=(1,))
    s = _state(site, _project(2), reader)
    data = tracker.ITEM_ADDED.payload(project=1, list_name=T, key="p2-t-1", title=Content(ref="5.title"),
                                      proposed=True, author=c.item_author(2), owner="bea", about=("bea",),
                                      read_about=("adrien", "camille", "bea"))
    after = tracker._item_added(s, _ev(data, 5), _cx())
    assert after.projects[1].read_about == ("adrien", "camille")  # jamais ses propres personnes
    assert after.projects[1].about == ("bea",) and after.projects[1].read_level == site.read_level
    assert set(after.projects[3].read_about) >= {"adrien", "camille", "bea"}  # de lecteur en lecteur
    assert after.projects[3].about == ("dan",)
    # le ticket d'une personne ne verse rien : ses sujets sont sur ce qui s'écrit sur lui
    person = data.model_copy(update={"key": "t-9", "author": c.BY_PERSON, "by": "zoe", "read_about": ()})
    assert tracker._item_added(s, _ev(person, 6), _cx()).projects[1].read_about == ()


def test_a_reopened_ticket_the_state_no_longer_kept_comes_back_with_its_number_and_keeps_its_objective():
    s = _add(_state(_project(1)), T, K, at=10, author=c.BY_PERSON, by="bea")
    s = _step(s, c.STAGE_UNREAD, 11, closed=c.DONE)
    for i in range(ITEMS_RECENT + 1):  # quarante éléments touchés depuis : il sort de l'état
        s = _add(s, "suivi", f"k{i}", at=100 + i)
    assert tracker.held(_board(s), T, K) is None
    seen = Item(T, K, number=1, status=c.STAGE_TREATED, closed=c.DONE, level=CONFIDENCE)  # lu dans la projection
    draft = tracker.changing(s.projects[1], seen, author=c.BY_OPERATOR, by="adrien", closed="").data
    assert (draft.number, draft.level, draft.was) == (1, CONFIDENCE, c.STAGE_TREATED)
    s = tracker._item_changed(s, _ev(draft, 200), _cx())
    item = _ticket(s)
    assert (item.number, item.level, item.status, item.known) == (1, CONFIDENCE, c.STAGE_UNREAD, False)
    # son plan validé : l'objectif naît avec ``ticket=1`` et retrouve son ticket — rien ne le retire
    s = _note(s, 210, kind=c.NOTE_PLAN)
    s = _step(s, c.STAGE_VALIDATION, 220, validated=True, plan=210, objective=1, **ADRIEN)
    s = _objective(s, 1, 220, ticket=1)
    p, o = s.projects[1], objective_at(s.projects[1], 1)
    assert _ticket(s).status == c.STAGE_WORKING and faculty.ticket_held(p, o) is _ticket(s)
    assert triage.follow_ups(s) == [] and triage.orphans(s) == []
    assert faculty.written_for(p, o) == CONFIDENCE
    asking = _note(s, 230, kind=c.NOTE_QUESTION)  # sa question retient son objectif : il se compare au bon numéro
    assert rhythm.held_back(asking.projects[1], o) and not rhythm.held_back(p, o)


def test_she_validates_a_small_plan_once_and_a_ticket_that_outgrew_its_bound_waits_for_its_owner():
    s = _add(_state(_project(1)), T, K, at=10)
    s = _note(s, 20, kind=c.NOTE_PLAN, small=True)
    s = _step(s, c.STAGE_VALIDATION, 21, validated=True, objective=1)  # par elle : le plan du même geste
    assert (_ticket(s).status, _ticket(s).validated_by) == (c.STAGE_WORKING, c.BY_SELF)
    s = _step(s, c.STAGE_WORKING, 30, diff_files=10, diff_lines=5, outgrown=tickets.FILES)
    item = _ticket(s)
    assert (item.status, item.outgrown, item.small, item.validated_at, item.objective, item.diff_files) == \
        (c.STAGE_VALIDATION, True, False, 0, 1, 10)
    assert not tickets.self_validates(item)
    # un second plan, redit « petit » : il ne se revalide pas seul — rien ne change, l'objectif reste retenu
    s = _note(s, 40, kind=c.NOTE_PLAN, small=True)
    assert _step(s, c.STAGE_VALIDATION, 41, validated=True) is s
    s = _step(s, c.STAGE_VALIDATION, 42, validated=True, plan=40, **ADRIEN)  # le propriétaire, lui, le valide
    item = _ticket(s)
    assert (item.status, item.validated_by, item.outgrown) == (c.STAGE_WORKING, "adrien", True)
    assert not triage.bounded(item)  # validé par lui : plus de borne
    # un diff déjà compté suffit, même sans dépassement ; un ticket qui a déjà son objectif aussi
    counted = Item(T, K, number=1, status=c.STAGE_VALIDATION, plan_seq=5, diff_lines=3)
    assert not tickets.self_validates(counted) and not tickets.self_validates(replace(counted, diff_lines=0, objective=2))
    assert tickets.self_validates(replace(counted, diff_lines=0))
    assert not tickets.reset(item).outgrown  # rouvert, il repart de rien


def test_a_validation_names_the_plan_it_validates_and_holds_only_if_it_is_still_the_tickets_plan():
    s = _add(_state(_project(1)), T, K, at=10, author=c.BY_PERSON, by="bea")
    s = _note(s, 20, kind=c.NOTE_PLAN)  # le plan A, que le propriétaire lit
    s = _note(s, 30, kind=c.NOTE_PLAN)  # réécrit : le plan B — l'étape reste « en attente de validation »
    assert (_ticket(s).status, _ticket(s).plan_seq) == (c.STAGE_VALIDATION, 30)
    # valider le plan A ne vaut plus : ni validation, ni objectif attaché
    assert _step(s, c.STAGE_VALIDATION, 31, validated=True, plan=20, objective=1, **ADRIEN) is s
    late = _objective(s, 1, 31, ticket=1)  # l'objectif écrit avec elle n'a pas lieu d'être : il sera retiré
    assert [(o.id, item.number) for _, o, item in triage.orphans(late)] == [(1, 1)]
    done = _step(s, c.STAGE_VALIDATION, 32, validated=True, plan=30, objective=1, **ADRIEN)
    assert (_ticket(done).status, _ticket(done).objective) == (c.STAGE_WORKING, 1)
    # la garde du numéro d'objectif : libre tant qu'aucun objectif ne l'a pris
    guard = tracker.free_number(s.projects[1], _ticket(s))
    key = c.OBJECTIVE_STATUS((1, 1))
    assert guard.predicate({key: ""}) and not guard.predicate({key: c.OPEN})
    assert tracker.free_number(late.projects[1], replace(_ticket(s), objective=1)) is None  # il garde le sien


def test_dependency_files_are_known_by_their_shape_and_their_folder():
    for path in ("requirements/base.txt", "api/requirements/prod.in", "environment.yaml", "environment.dev.yml",
                 "Pipfile", "sub/Pipfile.lock", "web/pnpm-lock.yaml", "flake.lock", "PACKAGE.JSON", "go.work",
                 "app/bun.lockb", "gradle.lockfile", "pyproject.toml", "constraints/ci.txt"):
        assert tickets.dependency(path), path
        assert tickets.oversize([path], 1, 1, tickets.Bounds()) == tickets.DEPENDENCIES, path
    for path in ("docs/notes.txt", "src/requirements.py", "site/tarifs.html", "locksmith.py", "data/lock.json"):
        assert not tickets.dependency(path), path
    # un fichier protégé au nom accentué correspond à son motif, lu tel quel
    assert tickets.oversize(tickets.touched(["déploiement/run.sh"]), 1, 1,
                            tickets.Bounds(protected=("déploiement/",))) == tickets.PROTECTED


def test_the_workshop_reads_an_accented_path_as_it_is(tmp_path):
    ws = BwrapWorkshop(tmp_path)

    async def scenario():
        await ws.write(1, "notes.md", "un\n")
        await ws.commit(1, "premier pas")
        await ws.write(1, "déploiement/été.sh", "echo\n")
        return await ws.pending(1)

    assert asyncio.run(scenario()) == ["déploiement/été.sh"]  # pas en octal, entre guillemets


def test_the_objective_that_treats_tickets_comes_back_on_a_fallback_cadence_while_a_ticket_is_in_her_hands():
    key = triggers.item_key(T)
    s = _objective(_state(_project(1)), 1, 5, kind=c.CONSTANT, author="self", on=(key,), only_on_event=True)
    o = objective_at(s.projects[1], 1)
    assert s.projects[1].triage == 1 and rhythm.due_at(s.projects[1], o, PM) == rhythm.NEVER  # aucun ticket
    s = _add(s, T, K, at=10, author=c.BY_PERSON, by="bea")
    # elle est passée (« continue », « wait », rien) : ses causes sont parties avec ce passage — il reste dû
    passed = replace(o, last_run_at=1_000, stirred=())
    p = faculty.with_objective(s.projects[1], passed)
    assert rhythm.tickets_in_hand(p) and rhythm.due_at(p, passed, PM) == 1_000 + PM.constant_cadence_us
    assert rhythm.next_due(p, PM) == 1_000 + PM.constant_cadence_us
    waiting = replace(passed, waiting_until=1_000 + 2 * PM.constant_cadence_us)  # l'attente qu'elle a demandée vaut
    assert rhythm.due_at(p, waiting, PM) == waiting.waiting_until
    # un ticket en analyse (son objectif retiré : il lui revient sans cause) la retient aussi ; ce qui attend le
    # propriétaire, non
    analysis = _step(s, c.STAGE_UNREAD, 20, taken=True)
    assert rhythm.due_at(faculty.with_objective(analysis.projects[1], passed), passed, PM) < rhythm.NEVER
    planned = _note(analysis, 30, kind=c.NOTE_PLAN)
    assert rhythm.due_at(faculty.with_objective(planned.projects[1], passed), passed, PM) == rhythm.NEVER
    # un constant sans cadence qui n'attend pas les tickets ne revient pas de lui-même
    other = Objective(2, "2.text", kind=c.CONSTANT, on=("app:veille",), only_on_event=True, last_run_at=1_000)
    assert rhythm.due_at(p, other, PM) == rhythm.NEVER


def test_the_objective_that_treats_tickets_is_born_once_with_its_first_ticket_as_its_cause():
    key = triggers.item_key(T)
    s = _add(_state(_project(1)), T, K, at=10, author=c.BY_PERSON, by="bea")
    assert [p.id for p, _ in triage.births(s)] == [1]
    s = _objective(s, 1, 20, kind=c.CONSTANT, author="self", on=(key,), only_on_event=True)
    o = objective_at(s.projects[1], 1)
    assert [(x.key, x.detail, x.at) for x in o.stirred] == [(key, "#1", 20)]  # sa cause, sans « lancer maintenant »
    assert rhythm.stirred_due(o, PM) == 20 + PM.stir_settle_us and s.projects[1].nudged_at == 0
    assert s.projects[1].triage == 1 and triage.births(s) == []
    # on lui ôte son déclencheur dans la console, ou on le retire : il n'en naît pas un second
    data = OBJECTIVE_CHANGED.payload(project=1, objective=1, on=(), only_on_event=False)
    bare = faculty._objective_changed(s, _ev(data, 30), _cx())
    assert objective_at(bare.projects[1], 1).on == () and bare.projects[1].triage == 1
    assert triage.births(_add(bare, T, "t-2", at=40, author=c.BY_PERSON, by="bea")) == []
    gone = faculty._objective_changed(s, _ev(OBJECTIVE_CHANGED.payload(project=1, objective=1, status=c.DROPPED), 30),
                                      _cx())
    assert triage.births(gone) == []
    # un ticket qu'elle a ouvert elle-même, en analyse, lui pose sa cause de même (ADR 0280) : les constats de son
    # audit n'attendent pas le ticket d'un autre ; un ticket proposé, lui, attend l'accord du propriétaire
    mine = _add(_state(_project(1)), T, K, at=10)
    assert [p.id for p, _ in triage.births(mine)] == [1]
    own = _objective(mine, 1, 20, kind=c.CONSTANT, on=(key,), only_on_event=True)
    assert [(x.key, x.detail) for x in objective_at(own.projects[1], 1).stirred] == [(key, "#1")]
    proposed = _add(_state(_project(1)), T, K, at=10, author=c.BY_PERSON, by="bea", proposed=True)
    assert triage.births(proposed) == []
    waiting = _objective(proposed, 1, 20, kind=c.CONSTANT, on=(key,), only_on_event=True)
    assert objective_at(waiting.projects[1], 1).stirred == ()


def test_an_objective_reopened_after_its_ticket_closed_is_retired_again_under_a_guard_not_a_key():
    s = _add(_state(_project(1)), T, K, at=10, author=c.BY_PERSON, by="bea")
    s = _note(s, 20, kind=c.NOTE_PLAN)
    s = _objective(_step(s, c.STAGE_VALIDATION, 21, validated=True, plan=20, objective=1, **ADRIEN), 1, 21, ticket=1)
    s = _step(s, c.STAGE_WORKING, 30, closed=c.DROPPED, **ADRIEN)
    [(p, o, item)] = triage.orphans(s)
    draft = triage.retiring(p, o, item)
    assert draft.dedupe_key is None and (draft.data.objective, draft.data.status) == (1, c.DROPPED)
    retired = faculty._objective_changed(s, _ev(draft.data, 31), _cx())
    assert triage.orphans(retired) == [] and triage.follow_ups(retired) == []
    # l'opérateur le rouvre : le même retrait se réécrit — une clé faite du ticket et de l'objectif l'aurait avalé
    again = faculty._objective_changed(retired, _ev(OBJECTIVE_CHANGED.payload(project=1, objective=1, status=c.OPEN),
                                                    40), _cx())
    assert [(x.id, i.number) for _, x, i in triage.orphans(again)] == [(1, 1)]
    guard = triage.still_alive(((1, 1),))
    key = c.OBJECTIVE_STATUS((1, 1))
    assert guard.predicate({key: c.OPEN}) and not guard.predicate({key: c.DROPPED})


def test_a_note_is_counted_by_the_state_as_by_the_projection_even_when_its_text_no_longer_reads():
    s = _add(_state(_project(1)), T, K, at=10)
    data = ITEM_NOTED.payload(project=1, list_name=T, key=K, text=Content(text=""), kind=c.NOTE_QUESTION)
    after = tracker._item_noted(s, _ev(data, 20), _cx())
    assert (_ticket(after).notes, _ticket(after).status) == (1, c.STAGE_DECISION)


# ── Sur un vrai noyau ──────────────────────────────────────────────────────


def test_a_request_from_a_more_confidential_project_is_read_only_by_who_hears_its_level(tmp_path):
    """« La veille » d'Adrien est une confidence et lit « Le site », personnel, que Zoé pilote en lecture seule.
    Son exécution ouvre une demande chez le site : Zoé n'en lit ni le titre ni le texte, proposée comme acceptée ;
    le site ne la travaille pas avant l'accord ; ce qu'il en écrit ensuite reste au niveau de la demande."""

    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Zoé")
        site = await create(kernel, "p1", title="Le site", objectives="Écrire la page d'accueil")
        veille = await create(kernel, "p2", title="La veille", constants="Veiller à la cohérence", cadence_hours="24")
        assert (await set_access(kernel, site, {"who": [OWNER], "see": True, "steer": "modification"},
                                 {"who": [PERSON + "user_2"], "see": True, "steer": "lecture"}, nonce="a1")).ok
        assert (await _link(kernel, veille, "l1", site)).ok
        await _confidence(kernel, veille)
        oid, store = _oid(kernel, veille), kernel.ports["store"]
        # Zoé entend du site le personnel ; « proche » entendrait tout, sans pouvoir rien trancher
        zoe = replace(facing("user_2"), level=PERSONAL, witness_level=PERSONAL)
        close, adrien = facing("user_2"), facing("user_1", owner=True)
        out = {"site": site}

        async def reads(handle: str, audience, **fields) -> str:
            return _words(await project_items(ReadArgs(project="le site", list_name="tickets", **fields),
                                              talking(kernel, handle, audience, "project_items")))

        async def her_list(**fields) -> str:
            return _words(await items_list(ListArgs(list_name="tickets", **fields), _run(kernel, site, "items_list")))

        async def registry() -> tuple[str, int]:
            frame = _run_frame(kernel, site, 1)
            s = frame.state("projects")
            body = _items_section(s, frame, {"projects_items": await _items(s, frame, kernel.ports)})
            return (body.content, body.level) if body is not None else ("", 0)

        await items_add(AddArgs(list_name="tickets", items=[ItemArg(title="Relire le README")]),
                        _run(kernel, site, "items_add"))
        out["zoe_before"] = await _heard(kernel, "user_2", zoe)
        out["asked"] = await project_ask(AskArgs(project=site, title="Corriger la page Tarifs", **ASK),
                                         _asking(kernel, veille, oid))
        out["item"] = _entry(kernel, site, 2).item
        # proposée : en conversation, seul qui peut la trancher la lit
        out["zoe_list"], out["zoe_detail"] = await reads("user_2", zoe), await reads("user_2", zoe, item="#2")
        out["close_detail"] = await reads("user_2", close, item="#2")
        out["owner_detail"] = await reads("user_1", adrien, item="#2")
        out["zoe_search"] = await reads("user_2", zoe, search="Tarifs")
        out["owner_search"] = await reads("user_1", adrien, search="Tarifs")
        # proposée : pendant une exécution du site, une ligne sans titre ni texte, et elle ne la ferme pas
        out["run_list"], out["run_detail"] = await her_list(), await her_list(item="2")
        out["run_search"] = await her_list(search="Tarifs")
        out["registry"] = await registry()
        out["closed"] = await items_change(ChangeArgs(list_name="tickets", item="2", close="done", note="Fait."),
                                           _run(kernel, site, "items_change"))
        out["renamed"] = await items_change(ChangeArgs(list_name="tickets", item="2", title="Autre chose"),
                                            _run(kernel, site, "items_change"))
        out["still"] = _entry(kernel, site, 2)
        # acceptée : Zoé n'entend toujours pas son niveau ; une proche, si ; l'exécution du site la lit
        await project_item(WriteArgs(project="le site", what="accept", item="#2"),
                           talking(kernel, "user_1", adrien, "project_item"))
        out["zoe_after"] = (await reads("user_2", zoe), await reads("user_2", zoe, item="#2"),
                            await reads("user_2", zoe, search="Tarifs"))
        out["close_after"] = await reads("user_2", close, item="#2")
        out["run_after"] = await her_list(item="2")
        out["registry_after"] = await registry()
        # ce que le site en écrit ensuite : son plan, l'objectif né du plan, son compte rendu — au niveau de la demande
        out["planned"] = await _do(kernel, site, item="2", **PLAN)
        out["validated"] = await project_item(
            WriteArgs(project="le site", what="validate", item="#2", plan=_plan(kernel, site, 2)),
            talking(kernel, "user_1", adrien, "project_item"))
        held = _entry(kernel, site, 2).item
        await kernel.ports["workshop"].write(site, "site/tarifs.html", "<p>90 €</p>")
        await report_run(ReportArgs(verdict="continue", summary="Prix corrigé à moitié."),
                         _run_context(kernel, site, held.objective, (("ws_write", True),)))
        out["note"] = [e.data.text.level for e in events(kernel, ITEM_NOTED) if e.data.project == site]
        out["born"] = [(e.data.text.level, e.data.done_when.level) for e in events(kernel, OBJECTIVE_ADDED)
                       if e.data.project == site and e.data.ticket]
        out["reports"] = [e.data.summary.level for e in events(kernel, c.RUN_REPORTED) if e.data.project == site]
        out["zoe_hears"] = await _heard(kernel, "user_2", zoe)
        out["owner_hears"] = await _heard(kernel, "user_1", adrien)
        out["thread"] = [n.text for n in tracker.thread(store, site, T, held.key)]
        return out

    out = live(tmp_path, scenario)
    assert "proposé" in _words(out["asked"]) and out["item"].level == CONFIDENCE
    title, text = "Corriger la page Tarifs", "sitemap"
    # Zoé : une ligne qui dit qu'une demande attend, sans rien de son contenu — en liste, en détail, en recherche
    for said in (out["zoe_list"], out["zoe_detail"], out["zoe_search"], out["close_detail"]):
        assert title not in said and text not in said and "Pourquoi" not in said, said
    assert "#2 [proposé] — une demande de le projet n°" in out["zoe_list"] and "Relire le README" in out["zoe_list"]
    assert "#2 [proposé]" in out["zoe_detail"] and "#2" not in out["zoe_search"]
    # qui peut la trancher la lit en entier
    assert title in out["owner_detail"] and "Pourquoi : Le produit a une page Tarifs" in out["owner_detail"]
    assert title in out["owner_search"]
    # l'exécution du site, avant tout accord : « #2 proposé, attend son accord », rien d'autre
    for said in (out["run_list"], out["run_detail"], out["registry"][0]):
        assert "#2 proposé, attend son accord" in said and title not in said and text not in said, said
    assert "#2" not in out["run_search"] and out["registry"][1] == PERSONAL
    for refused in (out["closed"], out["renamed"]):
        assert not refused.ok and "n'est pas à toi" in refused.content
    assert (out["still"].item.status, out["still"].title) == (c.STAGE_PROPOSED, title)
    # acceptée : son niveau décide — Zoé n'en lit rien, une proche la lit, l'exécution aussi (à ce niveau)
    for said in out["zoe_after"]:
        assert title not in said and text not in said, said
    assert "#2 [non lu] — son contenu ne peut pas se dire ici" in out["zoe_after"][0]
    assert "#2" not in out["zoe_after"][2]
    assert title in out["close_after"] and title in out["run_after"]
    assert title in out["registry_after"][0] and out["registry_after"][1] == CONFIDENCE
    assert "attend que" in _words(out["planned"]) and "est validé" in _words(out["validated"]), out["validated"]
    # ce que le site écrit sur la demande garde son niveau ; son compte rendu ne se dit pas à qui n'entend que le site
    assert out["note"] == [CONFIDENCE] and out["born"] == [(CONFIDENCE, CONFIDENCE)]
    assert out["reports"] == [CONFIDENCE] and any(out["thread"])
    # … et le détail du site (ce qui vient : l'objectif né de la demande) ne se dit plus à qui n'entend que le site
    assert "Le site" in out["zoe_before"] and "prochain objectif" in out["zoe_before"]
    assert "Le site" in out["zoe_hears"] and "prochain objectif" not in out["zoe_hears"]
    assert "Le site" in out["owner_hears"] and out["owner_hears"].count("prochain objectif") == 2


def test_a_second_small_plan_after_the_bound_waits_and_a_report_without_a_commit_is_not_done(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le site", objectives="Écrire la page d'accueil")
        assert (await perform(kernel, "projects.tickets_regler", row_form(
            {}, ticket_review=c.REVIEW_LARGE, small_files="3", small_lines="40", protected=""), by="user_1",
            subject=str(pid), nonce="r1")).ok
        await items_add(AddArgs(list_name="tickets", items=[ItemArg(title="Corriger un prix")]),
                        _run(kernel, pid, "items_add"))
        out = {"first": await _do(kernel, pid, item="1", **{**PLAN, "small": True})}
        oid = _entry(kernel, pid, 1).item.objective
        port = kernel.ports["workshop"]
        for name in ("a.py", "b.py", "package.json"):  # un fichier de dépendances : pas petit
            await port.write(pid, name, "x = 1\n")
        await reach_all(kernel, pid, oid)  # les jalons de son plan atteints : il ne reste que la borne (ADR 0273)
        out["outgrown"] = await report_run(ReportArgs(verdict="done", summary="Fait.", how_met="Vu."),
                                           _run_context(kernel, pid, oid, (("ws_write", True),)))
        out["after_bound"] = _entry(kernel, pid, 1).item
        # une autre exécution réécrit son plan, « petit » : il ne se revalide pas seul
        out["second"] = await _do(kernel, pid, item="1", **{**PLAN, "small": True, "changes": "Presque rien"})
        out["after_plan"] = _entry(kernel, pid, 1).item
        # l'exécution suivante n'a rien à enregistrer : « fait » ne passe pas tant que le ticket attend
        out["bare"] = await report_run(ReportArgs(verdict="done", summary="Rien de plus.", how_met="Vu."),
                                       _run_context(kernel, pid, oid, (("ws_write", True),)))
        await wait(2)
        out["objective"] = objective_at(_state_of(kernel).projects[pid], oid)
        out["ticket"] = _entry(kernel, pid, 1).item
        out["verdicts"] = [(e.data.verdict, bool(e.data.commit)) for e in events(kernel, c.RUN_REPORTED)
                           if e.data.objective == oid]
        return out

    out = live(tmp_path, scenario)
    assert "validé comme petit" in out["first"] and "n'est pas petit" in _words(out["outgrown"])
    assert (out["after_bound"].status, out["after_bound"].outgrown) == (c.STAGE_VALIDATION, True)
    assert "attend que" in out["second"] and "validé comme petit" not in out["second"]
    after = out["after_plan"]
    assert (after.status, after.validated_at, after.small, after.outgrown) == (c.STAGE_VALIDATION, 0, True, True)
    assert "pas comme « fait »" in _words(out["bare"]) and "en attente de validation" in _words(out["bare"])
    assert out["verdicts"] == [(c.CONTINUE, True), (c.CONTINUE, False)]
    assert out["objective"].status == c.OPEN and out["ticket"].status == c.STAGE_VALIDATION


def test_a_plan_rewritten_before_its_validation_is_not_validated_in_place_of_the_one_that_was_read(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le site", objectives="Écrire la page d'accueil")
        adrien = facing("user_1", owner=True)
        await perform(kernel, "projects.ticket_ouvrir", row_form({}, title="La page Tarifs est fausse", kind="bug",
                                                                 priority="normal"),
                      by="user_1", subject=str(pid), nonce="t1")

        async def says(**fields):
            return await project_item(WriteArgs(project="le site", item="#1", **fields),
                                      talking(kernel, "user_1", adrien, "project_item"))

        async def settle(nonce: str, plan: int):
            return await perform(kernel, "projects.ticket_trancher", row_form(
                {"item": "1", "plan": str(plan)}, verdict="validate"), by="user_1", subject=str(pid), nonce=nonce)

        await _do(kernel, pid, item="1", **PLAN)
        first = _plan(kernel, pid, 1)
        out = {"read": _words(await project_items(ReadArgs(project="le site", list_name="tickets", item="#1"),
                                                  talking(kernel, "user_1", adrien, "project_items"))),
               "first": first}
        # une exécution le réécrit entre-temps : l'étape reste « en attente de validation »
        await _do(kernel, pid, item="1", **{**PLAN, "changes": "Refaire toute la page Tarifs"})
        second = out["second"] = _plan(kernel, pid, 1)
        out["unnamed"] = await says(what="validate")
        out["stale"] = await says(what="validate", plan=first)
        out["console_stale"] = await settle("s1", first)
        out["waiting"] = (_entry(kernel, pid, 1).item, [o.ticket for o in _state_of(kernel).projects[pid].objectives])
        out["validated"] = await says(what="validate", plan=second)
        ticket = out["ticket"] = _entry(kernel, pid, 1).item
        born = objective_at(_state_of(kernel).projects[pid], ticket.objective)
        out["text"] = kernel.ports["store"].content([born.text_ref])[born.text_ref]
        return out

    out = live(tmp_path, scenario)
    first, second = out["first"], out["second"]
    assert second > first and f"plan n° {first} de toi, à valider" in out["read"]
    for refused in (out["unnamed"], out["stale"]):
        assert not refused.ok and f"plan n° {second}" in refused.content and f"plan={second}" in refused.content
        assert "Refaire toute la page Tarifs" in refused.content  # le plan d'aujourd'hui est montré
    assert not out["console_stale"].ok and f"n° {second}" in out["console_stale"].message
    waiting, born = out["waiting"]
    assert (waiting.status, waiting.plan_seq, waiting.objective) == (c.STAGE_VALIDATION, second, 0) and 1 not in born
    assert "est validé" in _words(out["validated"]) and out["ticket"].status == c.STAGE_WORKING
    assert "Refaire toute la page Tarifs" in out["text"]


def test_an_objective_reopened_after_its_ticket_is_retired_again_and_the_process_comes_to_rest(tmp_path):
    async def scenario(kernel, llm):
        pid = await create(kernel, "p1", title="Le site", objectives="Écrire la page d'accueil")

        async def settle(nonce: str, verdict: str, plan: int = 0, **values: str):
            got = await perform(kernel, "projects.ticket_trancher", row_form(
                {"item": "1", "plan": str(plan)}, verdict=verdict, **values), by="user_1", subject=str(pid),
                nonce=nonce)
            assert got.ok, got

        await perform(kernel, "projects.ticket_ouvrir", row_form({}, title="La page Tarifs est fausse", kind="bug",
                                                                 priority="normal"),
                      by="user_1", subject=str(pid), nonce="t1")
        await _do(kernel, pid, item="1", **PLAN)
        await settle("s1", "validate", _plan(kernel, pid, 1))
        oid = _entry(kernel, pid, 1).item.objective
        await settle("s2", "dismiss", reason="Finalement non.")
        await wait(2)
        out = {"dropped": [objective_at(_state_of(kernel).projects[pid], oid).status]}
        for n in range(2):  # l'opérateur le rouvre, deux fois : il est retiré chaque fois
            got = await perform(kernel, "projects.objectif_statut", row_form({"objective": str(oid), "status": c.OPEN}),
                                by="user_1", subject=str(pid), nonce=f"o{n}")
            assert got.ok, got
            await wait(2)
            out["dropped"].append(objective_at(_state_of(kernel).projects[pid], oid).status)
        frame = kernel.mind.frame()
        out["due"] = triage.Tickets().next_due(frame.state("projects"), frame, frame.now)
        out["retired"] = [e for e in events(kernel, OBJECTIVE_CHANGED)
                          if e.data.objective == oid and e.data.status == c.DROPPED and e.data.by == c.BY_SELF]
        out["nudged"] = events(kernel, NUDGED)
        return out

    out = live(tmp_path, scenario)
    assert out["dropped"] == [c.DROPPED] * 3 and len(out["retired"]) == 3
    assert out["due"] is None and out["nudged"] == []  # plus rien à faire : il ne repart pas chaque minute
