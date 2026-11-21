"""La demande d'un projet à un autre (ADR 0271).

- une demande ne va qu'à un projet lu, dont le lien donne au propriétaire du demandeur le pilotage sur accord ou en
  modification ; un lien suspendu ne demande rien ;
- elle naît « proposée » par défaut, « non lue » en mode direct — un mode réglé lien par lien, que la matrice du
  projet visé puis le niveau de ce qu'il écrit referment ;
- trois demandes par exécution, cinq demandes ouvertes par lien, vingt gardées ; une même demande ne s'empile pas ;
- le demandeur suit l'étape de son ticket ; fermée — traitée, puis écartée —, elle réveille l'objectif qui l'a
  ouverte, quand le lien donne encore le détail ; un même événement porte deux nouvelles sans en perdre une ;
- sur un vrai noyau : son outil et ses refus, la console qui règle le mode direct ; puis un parcours entier à deux
  propriétaires, de la demande au ticket traité — ce que le ticket porte pour l'oubli, qui entend quoi, ce que le
  demandeur lit, et ce qu'il n'en lit plus quand le droit est repris.
"""

from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects import asks, links, tracker, triggers
from mika.faculties.projects.demands import AskArgs, key_of, project_ask
from mika.faculties.projects.faculty import (
    ASKS_KEPT,
    LINKS_SET,
    PROJECTS,
    STIRRED,
    Objective,
    ProjectsState,
    Run,
    Stir,
    _handed_back,
    _links_set,
    _stirred,
    objective_at,
    subject_of,
    written,
)
from mika.faculties.projects.inspect import ASKS_TITLE, READERS_TITLE, READS_TITLE
from mika.faculties.projects.prompt import _asks, _asks_section, _links_section, _stirs_section, _texts
from mika.faculties.projects.rhythm import stirred_due
from mika.faculties.projects.tools import BOOKKEEPING, ReportArgs, report_run
from mika.faculties.projects.tracker import ITEM_ADDED, ITEM_CHANGED, WriteArgs, project_item
from mika.faculties.projects.triage import StepArgs, ticket_step
from mika.faculties.shares.tools import may_share
from mika.kernel.clock import HOUR
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import EpisodeRef, Frame
from mika.kernel.inspect import Fields
from mika.kernel.state import FrozenDict
from mika.runtime.operations import dynamic_fields, perform
from mika.runtime.tools import ToolContext
from mika.vocab.access import OWNER, PERSON, STEER_ASK, STEER_EDIT, STEER_NO, STEER_READ
from mika.vocab.episodes import Kind, project_target
from mika.vocab.phrasebook import phrase
from tests.fixtures.mika import connect
from tests.unit.test_goals_console import nested
from tests.unit.test_project_access import facing, set_access, talking
from tests.unit.test_project_links import (
    CONFIDENCE,
    PERSONAL,
    PM,
    WORLD,
    _cx,
    _ev,
    _line,
    _project,
    _read,
    _state,
)
from tests.unit.test_project_links_audience import (
    _audience,
    _confidence,
    _facing,
    _heard,
    _text_refs,
    _told,
    _view,
)
from tests.unit.test_project_milestones import reach_all
from tests.unit.test_project_tracker import _run
from tests.unit.test_projects import _run_context, create, events, form, live, wait
from tests.unit.test_projects_console import tab, tables

T = c.TICKETS
T0 = 1_000 * HOUR
_N = itertools.count(1)


def _words(got) -> str:
    return got.content if isinstance(got, ToolResult) else got


# ── Les règles, pures ──────────────────────────────────────────────────────
# Adrien s'occupe d'elle : son projet (n° 2) lit « le site » de Bea (n° 1), que Bea lui partage par une ligne.


def _pair(steer: str = STEER_ASK, **asker) -> ProjectsState:
    site = _project(1, owner="bea", access=(_line(OWNER, see=True, steer=steer),))
    return _read(_state(site, _project(2, **asker), _project(3, owner="bea")), 2, 1)


def _reading(s: ProjectsState, target: int = 1):
    return next((r for r in links.readings(s, s.projects[2], WORLD) if r.id == target), None)


def _ask(s: ProjectsState, n: int, at: int = 0, run: str = "run", origin: int = 0, **fields) -> ProjectsState:
    """La demande n° ``n`` du projet 2 au projet 1, telle que le réducteur la lit."""
    at = at or next(_N)
    data = ITEM_ADDED.payload(project=1, list_name=T, key=f"p2-t-{n}", title=Content(ref=f"{at}.title"),
                              proposed=True, author=c.item_author(2), origin=origin, **fields)
    return tracker._item_added(s, _ev(data, at, correlation=run), _cx())


def _step(s: ProjectsState, n: int, was: str, at: int, **fields) -> ProjectsState:
    data = ITEM_CHANGED.payload(project=1, list_name=T, key=f"p2-t-{n}", was=was, **fields)
    return tracker._item_changed(s, _ev(data, at), _cx())


def test_a_request_only_goes_to_a_project_read_whose_link_gives_steering():
    s = _pair()
    assert asks.refusal(s.projects[2], _reading(s, 3), "run") == asks.UNREAD  # le n° 3 n'est pas lu
    assert asks.refusal(s.projects[2], _reading(s), "run") == ""  # sur l'accord de son propriétaire
    assert asks.refusal(s.projects[2], _reading(_pair(STEER_EDIT)), "run") == ""
    for steer in (STEER_READ, STEER_NO):  # le lire, ou seulement le voir, ne donne pas de lui demander
        closed = _pair(steer)
        assert asks.refusal(closed.projects[2], _reading(closed), "run") == asks.NO_RIGHT
    # un lien suspendu ne demande rien : le projet visé est archivé, ou ses lignes ne le laissent plus voir
    archived = replace(s, projects=s.projects.set(1, replace(s.projects[1], status=c.ARCHIVED)))
    assert asks.refusal(archived.projects[2], _reading(archived), "run") == asks.SUSPENDED
    hidden = replace(s, projects=s.projects.set(1, replace(s.projects[1], access=(_line(PERSON + "bea", see=True),))))
    assert asks.refusal(hidden.projects[2], _reading(hidden), "run") == asks.SUSPENDED
    with pytest.raises(triggers.BadTrigger):  # la cause d'une demande fermée ne se déclare sur aucun objectif
        triggers.parse(triggers.ask_key(1))
    assert triggers.asked(triggers.ask_key(7)) == 7 and triggers.asked("item:tickets") == 0


def test_a_request_is_born_proposed_and_direct_only_while_the_link_the_matrix_and_the_level_allow_it():
    s = _pair(STEER_EDIT)
    site, grant = s.projects[1], _reading(s).grant
    assert asks.mode(s.projects[2], site, grant) == asks.PROPOSED  # par défaut, même quand la matrice donne tout
    # le propriétaire du demandeur règle le mode direct sur son lien ; il ne tient qu'à un lien posé
    s = _links_set(s, _ev(LINKS_SET.payload(project=2, reads=(1,), direct=(1, 3), by="adrien")), _cx())
    y = s.projects[2]
    assert y.direct == (1,) and asks.mode(y, site, grant) == asks.DIRECT
    assert _read(s, 2, 1).projects[2].direct == (1,)  # un lien reposé sans rien en dire (un plan) le garde
    assert _read(s, 2).projects[2].direct == ()  # un lien retiré le perd
    # fermé par la matrice : elle ne donne plus que l'accord
    on_approval = _reading(_pair(STEER_ASK)).grant
    assert asks.indirect(y, site, on_approval) == asks.MATRIX and asks.mode(y, site, on_approval) == asks.PROPOSED
    # fermé par le niveau : ce qu'écrit le demandeur est plus confidentiel que ce qu'écrit le projet visé
    secret = replace(y, sensitivity=CONFIDENCE)
    assert written(secret) > written(site)
    assert asks.indirect(secret, site, grant) == asks.LEVEL and asks.mode(secret, site, grant) == asks.PROPOSED
    # … et rouvert quand le projet visé est au moins aussi confidentiel
    assert asks.mode(secret, replace(site, sensitivity=CONFIDENCE), grant) == asks.DIRECT
    assert asks.mode(y, site, _reading(_pair(STEER_READ)).grant) == ""  # sans droit de demander : rien


def test_three_requests_per_run_five_open_per_link_and_twenty_kept():
    s = _pair()
    for n in (1, 2, 3):
        s = _ask(s, n, run="run-1")
    assert asks.refusal(s.projects[2], _reading(s), "run-1") == asks.PER_RUN
    assert asks.refusal(s.projects[2], _reading(s), "run-2") == ""  # une autre exécution a les siennes
    s = _ask(_ask(s, 4, run="run-2"), 5, run="run-2")
    assert asks.open_to(s.projects[2], 1) == 5
    assert asks.refusal(s.projects[2], _reading(s), "run-3") == asks.PER_LINK
    # une demande fermée libère sa place sur le lien
    s = _step(s, 1, c.STAGE_PROPOSED, 50, closed=c.DROPPED, author=c.BY_PERSON, by="bea")
    assert asks.open_to(s.projects[2], 1) == 4 and asks.refusal(s.projects[2], _reading(s), "run-3") == ""
    # le même ticket ne se suit pas deux fois ; un ticket d'elle, ou d'une personne, n'est la demande de personne
    assert _ask(s, 2).projects[2].asks == s.projects[2].asks
    mine = tracker._item_added(s, _ev(ITEM_ADDED.payload(project=1, list_name=T, key="t-x",
                                                         title=Content(ref="x.title")), 60), _cx())
    assert mine.projects[2].asks == s.projects[2].asks and mine.projects[1].asks == ()
    # vingt au plus : la fermée tombe d'abord, puis les plus anciennes
    for n in range(6, 6 + ASKS_KEPT):
        s = _ask(s, n, at=100 + n)
    kept = s.projects[2].asks
    assert len(kept) == ASKS_KEPT and all(asks.opened(a) for a in kept)
    assert [a.number for a in kept][:2] == [6, 7] and kept[-1].number == 5 + ASKS_KEPT


def test_the_asker_follows_its_request_and_its_closing_wakes_the_objective_that_opened_it():
    constant = Objective(id=1, text_ref="o1", kind=c.CONSTANT, at=T0, waiting_until=T0 + 9 * HOUR)
    once = Objective(id=2, text_ref="o2", at=T0, waiting_until=T0 + 9 * HOUR)
    s = _ask(_ask(_pair(objectives=(constant, once)), 1, at=T0 + 1, origin=1), 2, at=T0 + 2, origin=2)
    first, second = s.projects[2].asks
    assert (first.target, first.key, first.number, first.objective, first.run) == (1, "p2-t-1", 1, 1, "run")
    assert (first.status, second.number, second.objective) == (c.STAGE_PROPOSED, 2, 2)
    assert asks.state(first.status) == asks.PENDING and s.projects[1].asks == ()
    # son propriétaire l'accepte, elle le prend : le demandeur suit, rien ne le réveille
    s = _step(s, 1, c.STAGE_PROPOSED, T0 + 3, accepted=True, author=c.BY_PERSON, by="bea")
    assert asks.state(s.projects[2].asks[0].status) == asks.ACCEPTED
    s = _step(s, 1, c.STAGE_UNREAD, T0 + 4, taken=True)
    assert asks.state(s.projects[2].asks[0].status) == asks.WORKING and s.heard == ()
    # traitée, avec sa note : une nouvelle à juger, qui nomme le projet visé et le ticket — aucun texte
    s = _step(s, 1, c.STAGE_ANALYSIS, T0 + 5, closed=c.DONE, note=Content(ref="5.note"))
    done = s.projects[2].asks[0]
    assert (asks.state(done.status), done.closed_at, done.note_seq) == (asks.DONE, T0 + 5, T0 + 5)
    [news] = s.heard
    assert (news.key, news.detail, news.project) == ("ask:1", "#1", 1)
    assert asks.roused(s, news, WORLD) == ((2, 1),)  # l'objectif qui l'a ouverte, et lui seul
    # un lien qui ne donne plus le détail ne réveille rien
    title_only = replace(s, projects=s.projects.set(1, replace(s.projects[1], access=(_line(OWNER, see=True),))))
    assert asks.roused(title_only, news, WORLD) == ()
    unlinked = _read(s, 2)
    assert asks.roused(unlinked, news, WORLD) == ()
    # jugée : le constant n'attend plus et devient dû par cette cause ; la nouvelle quitte la file
    woken = _stirred(s, _ev(STIRRED.payload(news=news.seq, key=news.key, targets=((2, 1),)), T0 + 6), _cx())
    o = objective_at(woken.projects[2], 1)
    assert woken.heard == () and o.waiting_until == 0 and stirred_due(o, PM) is not None
    assert [(x.key, x.detail) for x in o.stirred] == [("ask:1", "#1")]
    # une exécution qui n'a pas eu lieu lui rend cette cause, qu'il ne déclare pourtant pas
    back = _handed_back(replace(o, stirred=()), Run(2, 1, "run", stirred=(Stir(T0 + 5, "ask:1", "#1"),)))
    assert [x.key for x in back.stirred] == ["ask:1"]
    # jugée sans éveil (le lien ne donnait plus rien) : la nouvelle quitte la file, personne n'est réveillé
    silent = _stirred(s, _ev(STIRRED.payload(news=news.seq, key=news.key), T0 + 6), _cx())
    assert silent.heard == () and objective_at(silent.projects[2], 1).waiting_until == T0 + 9 * HOUR
    # un autre objectif que celui qui l'a ouverte ne se réveille pas, même nommé
    other = _stirred(s, _ev(STIRRED.payload(news=news.seq, key=news.key, targets=((2, 2),)), T0 + 6), _cx())
    assert objective_at(other.projects[2], 2).waiting_until == T0 + 9 * HOUR
    # écartée avec sa raison : le ponctuel qui attendait n'attend plus — il ne garde pas de cause
    s = _step(woken, 2, c.STAGE_PROPOSED, T0 + 7, closed=c.DROPPED, note=Content(ref="7.note"), author=c.BY_PERSON,
              by="bea")
    dropped = s.projects[2].asks[1]
    assert (asks.state(dropped.status), dropped.note_seq) == (asks.DROPPED, T0 + 7)
    [gone] = s.heard
    s = _stirred(s, _ev(STIRRED.payload(news=gone.seq, key=gone.key, targets=asks.roused(s, gone, WORLD)), T0 + 8),
                 _cx())
    lifted = objective_at(s.projects[2], 2)
    assert (lifted.waiting_until, lifted.stirred) == (0, ())
    # rouverte chez le projet visé : elle se suit de nouveau, sans rien réveiller
    s = _step(s, 2, c.STAGE_DISMISSED, T0 + 9, closed="", author=c.BY_OPERATOR, by="user_1")
    again = s.projects[2].asks[1]
    assert (asks.state(again.status), again.closed_at, again.note_seq, s.heard) == (asks.ACCEPTED, 0, 0, ())


def test_one_event_carries_two_pieces_of_news_and_neither_is_lost():
    """Le ticket qu'une personne écarte éveille « Traiter les tickets » chez le projet visé **et** réveille le
    demandeur : deux nouvelles du même événement, chacune jugée sous son déclencheur."""
    treats = Objective(id=1, text_ref="o1", kind=c.CONSTANT, at=T0, on=(triggers.item_key(T),), only_on_event=True)
    asker = Objective(id=1, text_ref="o1", kind=c.CONSTANT, at=T0)
    s = _pair(objectives=(asker,))
    s = replace(s, projects=s.projects.set(1, replace(s.projects[1], objectives=(treats,))))
    s = _ask(s, 1, at=T0 + 1, origin=1)
    assert [h.key for h in s.heard] == ["item:tickets"]  # la demande elle-même est un ticket d'un autre qu'elle
    s = _stirred(s, _ev(STIRRED.payload(news=T0 + 1, key="item:tickets", targets=((1, 1),)), T0 + 2), _cx())
    s = _step(s, 1, c.STAGE_PROPOSED, T0 + 3, closed=c.DROPPED, author=c.BY_PERSON, by="bea")
    assert [(h.seq, h.key) for h in s.heard] == [(T0 + 3, "ask:1"), (T0 + 3, "item:tickets")]
    one = _stirred(s, _ev(STIRRED.payload(news=T0 + 3, key="ask:1", targets=((2, 1),)), T0 + 4), _cx())
    assert [h.key for h in one.heard] == ["item:tickets"]
    assert [x.key for x in objective_at(one.projects[2], 1).stirred] == ["ask:1"]
    both = _stirred(one, _ev(STIRRED.payload(news=T0 + 3, key="item:tickets", targets=((1, 1),)), T0 + 4), _cx())
    assert both.heard == () and [x.key for x in objective_at(both.projects[1], 1).stirred][-1] == "item:tickets"
    # un journal d'avant ne nomme pas son déclencheur : il juge la seule nouvelle que portait son événement
    old = _stirred(one, _ev(STIRRED.payload(news=T0 + 3, targets=((1, 1),)), T0 + 4), _cx())
    assert old.heard == ()
    stirs = next(x for x in PROJECTS.processes if x.name == "projects.stirs")
    assert ITEM_CHANGED.name in set(stirs.wake_on)


# ── Sur un vrai noyau ──────────────────────────────────────────────────────

ASK = {"text": "Le site n'a pas de sitemap : les moteurs ne trouvent pas la page Tarifs.",
       "done_when": "sitemap.xml existe à la racine et liste chaque page.",
       "why": "Le produit a une page Tarifs que personne ne trouve."}


def _asking(kernel, pid: int, oid: int, episode: str = "") -> ToolContext:
    """Un appel de ``project_ask`` pendant une exécution du projet ``pid`` — ``episode`` : la même exécution d'un
    appel à l'autre."""
    mind, n = kernel.mind, next(_N)
    name = episode or f"ep-demande-{n}"
    ref = EpisodeRef(name, Kind.WORK, target=project_target(pid), attrs=FrozenDict({"subject": subject_of(pid, oid)}))
    frame = Frame(mind.frame().root, mind.clock.now(), mind.registry, facing("user_1", owner=True), ref)
    return ToolContext(mind, mind.registry.tools["project_ask"], f"demande-{n}", name, frame, ports=kernel.ports)


def _state_of(kernel) -> ProjectsState:
    return kernel.mind.frame().state("projects")


def _oid(kernel, pid: int) -> int:
    return _state_of(kernel).projects[pid].objectives[0].id


def _run_frame(kernel, pid: int, oid: int) -> Frame:
    mind = kernel.mind
    ref = EpisodeRef("ep-demandes", Kind.WORK, target=project_target(pid),
                     attrs=FrozenDict({"subject": subject_of(pid, oid)}))
    return Frame(mind.frame().root, mind.clock.now(), mind.registry, facing("user_1", owner=True), ref)


async def _asks_read(kernel, pid: int, oid: int):
    """« TES DEMANDES AUX AUTRES PROJETS », telle que la lit l'exécution de cet objectif."""
    frame = _run_frame(kernel, pid, oid)
    s = frame.state("projects")
    return _asks_section(s, frame, {"projects_asks": await _asks(s, frame, kernel.ports)})


async def _links_read(kernel, pid: int, oid: int) -> str:
    frame = _run_frame(kernel, pid, oid)
    s = frame.state("projects")
    return _links_section(s, frame, {"projects": await _texts(s, frame, kernel.ports)}).content


async def _link(kernel, reader: int, nonce: str, *targets: int, direct: tuple[int, ...] = (), by: str = "user_1"):
    ticked = {f"lit_{t}": "on" for t in targets} | {f"direct_{t}": "on" for t in direct}
    return await perform(kernel, "projects.liens", form(**ticked), by=by, subject=str(reader), nonce=nonce)


def test_her_run_asks_a_project_read_within_what_its_link_allows(tmp_path):
    async def scenario(kernel, llm):
        site = await create(kernel, "p1", title="Le site", objectives="Écrire la page d'accueil")
        other = await create(kernel, "p2", title="Un autre", objectives="Ne rien faire")
        y = await create(kernel, "p3", title="Faire connaître", constants="Veiller à la cohérence", cadence_hours="24")
        oid, store = _oid(kernel, y), kernel.ports["store"]
        out = {"site": site, "y": y, "oid": oid}

        async def ask(target: int, title: str, episode: str = "", **more):
            return await project_ask(AskArgs(project=target, title=title, **{**ASK, **more}),
                                     _asking(kernel, y, oid, episode))

        async def lines(steer: str, nonce: str):
            assert (await set_access(kernel, site, {"who": [OWNER], "see": True, "steer": steer}, nonce=nonce)).ok

        out["unlinked"] = await ask(site, "Ajouter un sitemap")
        assert (await _link(kernel, y, "l1", site)).ok
        out["other"] = await ask(other, "Ajouter un sitemap")
        # le lire ne donne pas de lui demander
        await lines("lecture", "a1")
        out["read_only"] = await ask(site, "Ajouter un sitemap")
        out["no_hint"] = await _links_read(kernel, y, oid)
        # sur l'accord de son propriétaire : elle naît proposée ; la même ne s'empile pas
        await lines("accord", "a2")
        out["hint"] = await _links_read(kernel, y, oid)
        out["proposed"] = await ask(site, "Ajouter un sitemap", kind="idea", priority="high")
        out["first"] = tracker.ticket(store, site, 1)
        out["twice"] = await ask(site, "  ajouter un  SITEMAP ")
        out["tickets"] = tracker.total(store, site, T)
        # le mode direct : refusé tant que la matrice ne donne pas la modification, puis réglé sur le lien
        spec = kernel.registry.actions["projects.liens"]
        out["fields_closed"] = {f.path: f.label for f in dynamic_fields(kernel, spec, str(y), {})}
        out["direct_refused"] = await _link(kernel, y, "l2", site, direct=(site,))
        await lines("modification", "a3")
        out["fields_open"] = {f.path: f.label for f in dynamic_fields(kernel, spec, str(y), {})}
        out["direct_set"] = await _link(kernel, y, "l3", site, direct=(site,))
        out["stranger"] = await _link(kernel, y, "l4", site, by="user_9")
        out["hint_direct"] = await _links_read(kernel, y, oid)
        out["direct"] = await ask(site, "Corriger le titre de la page d'accueil", "ep-une")
        out["second"] = tracker.ticket(store, site, 2)
        # fermé par la matrice : le lien le règle toujours, la matrice ne donne plus que l'accord
        await lines("accord", "a4")
        out["by_matrix"] = await ask(site, "Demande trois", "ep-une")
        out["third"] = tracker.ticket(store, site, 3)
        # fermé par le niveau : ce qu'écrit le demandeur devient une confidence, pas ce qu'écrit le site
        await lines("modification", "a5")
        await _confidence(kernel, y)
        out["by_level"] = await ask(site, "Demande quatre", "ep-une")
        out["fourth"] = tracker.ticket(store, site, 4)
        # trois par exécution ; cinq demandes ouvertes par lien
        out["per_run"] = await ask(site, "Demande cinq", "ep-une")
        out["fifth"] = await ask(site, "Demande cinq")
        out["per_link"] = await ask(site, "Demande six")
        out["added"] = [e for e in events(kernel, ITEM_ADDED) if e.data.project == site]
        out["asks"] = _state_of(kernel).projects[y].asks
        out["site_asks"] = _state_of(kernel).projects[site].asks
        out["site_items"] = [x for x in _state_of(kernel).projects[site].board.items if x.list_name == T]
        out["reads"] = tables(await tab(kernel, "liens", str(y)))
        out["spec"] = kernel.registry.tools["project_ask"]
        return out

    out = live(tmp_path, scenario)
    site, y, oid = out["site"], out["y"], out["oid"]
    for refused, said in (("unlinked", "ne lit pas le projet"), ("other", f"(il lit : n° {site})"),
                          ("read_only", "pas lui adresser de demande"), ("twice", "existe déjà : c'est le ticket #1"),
                          ("per_run", "Trois demandes par exécution"), ("per_link", "déjà 5 demandes ouvertes")):
        assert not out[refused].ok and said in out[refused].content, (refused, out[refused])
    assert "(il n'en lit aucun)" in out["unlinked"].content and "Rien n'a été ouvert" in out["read_only"].content
    assert "en attente de l'accord" in out["twice"].content and out["tickets"] == 1  # la même, sans casse ni espaces
    # proposée par défaut : son ticket dit le projet demandeur, sa sorte, sa priorité, son critère et son pourquoi
    assert "proposé : elle attend l'accord de son propriétaire" in _words(out["proposed"])
    first = out["first"]
    assert (first.item.status, first.item.author, first.item.kind, first.item.priority) == \
        (c.STAGE_PROPOSED, c.item_author(y), c.IDEA, c.HIGH)
    assert first.item.key == key_of(y, "Ajouter un sitemap") and first.title == "Ajouter un sitemap"
    assert ASK["text"] in first.body and "Ce sera fait quand : sitemap.xml" in first.body
    assert "Pourquoi : Le produit a une page Tarifs" in first.body
    # ce que le lien donne de demander se lit sous le projet lu
    assert "project_ask" not in out["no_hint"] and "qui attend l'accord de son propriétaire" in out["hint"]
    assert "elle entre directement dans ses tickets" in out["hint_direct"]
    # le mode direct se règle sur le lien posé, par le propriétaire du demandeur, quand il vaudrait
    assert f"direct_{site}" in out["fields_closed"] and "sans effet pour l'instant" in out["fields_closed"][f"direct_{site}"]
    assert not out["direct_refused"].ok and "ne donnent pas la modification" in out["direct_refused"].message
    assert "sans effet" not in out["fields_open"][f"direct_{site}"]
    assert out["direct_set"].ok and f"directement chez : n° {site}" in out["direct_set"].message
    assert not out["stranger"].ok and "propriétaire" in out["stranger"].message
    assert "elle est entre ses mains" in _words(out["direct"])
    assert (out["second"].item.status, out["second"].item.proposed) == (c.STAGE_UNREAD, False)
    # la matrice, puis le niveau, referment le mode direct : la demande naît proposée
    for closed in ("third", "fourth"):
        assert out[closed].item.status == c.STAGE_PROPOSED, closed
    assert "proposé" in _words(out["by_matrix"]) and "proposé" in _words(out["by_level"])
    # elle s'écrit au niveau le plus haut des deux projets, et dit l'objectif d'où elle part
    levels = [(e.data.title.level, e.data.text.level, e.data.origin) for e in out["added"]]
    assert levels[:3] == [(PERSONAL, PERSONAL, oid)] * 3 and levels[3:] == [(CONFIDENCE, CONFIDENCE, oid)] * 2
    # … et le ticket garde ce niveau, dans la projection comme dans l'état : c'est lui qui décide de qui l'entend
    # (ADR 0272) — qui n'entend du site que le personnel n'en lit ni le titre ni le texte, même une fois accepté
    assert (out["first"].item.level, out["fourth"].item.level) == (PERSONAL, CONFIDENCE)
    assert [x.level for x in out["site_items"]] == [PERSONAL] * 3 + [CONFIDENCE] * 2
    accepted = replace(out["fourth"].item, proposed=False, status=c.STAGE_UNREAD)
    personal, confident = tracker.Reader(level=PERSONAL), tracker.Reader(level=CONFIDENCE)
    assert tracker.veiled(personal, accepted) == tracker.LEVEL_VEIL and tracker.veiled(confident, accepted) == ""
    assert tracker.veiled(personal, replace(out["first"].item, proposed=False, status=c.STAGE_UNREAD)) == ""
    assert not isinstance(out["fifth"], ToolResult), out["fifth"]
    # le demandeur suit ses cinq demandes ; le projet visé n'en suit aucune
    assert [(a.target, a.number, a.objective) for a in out["asks"]] == [(site, n, oid) for n in range(1, 6)]
    assert [a.run for a in out["asks"]][1:4] == ["ep-une"] * 3 and out["site_asks"] == ()
    # sa fiche : comment naîtrait une demande sur chaque lien, et ses demandes
    [link] = out["reads"][READS_TITLE].rows
    assert link[4].text.startswith("sur l'accord")  # le lien règle le direct, le niveau le referme
    rows = out["reads"][ASKS_TITLE].rows
    assert len(rows) == 5 and rows[-1][0].text == f"n° {site} · #1" and rows[-1][1].text == "en attente d'accord"
    assert rows[-2][1].text == "acceptée, pas encore lue" and rows[0][3].text == f"n° {oid}"
    assert out["reads"][READERS_TITLE].rows == ()
    assert out["spec"].bundle == "projects" and Kind.WORK in out["spec"].episodes and "project_ask" in BOOKKEEPING


PLAN = {"what": "plan", "changes": "Ajouter sitemap.xml à la racine du site", "where": "site/sitemap.xml",
        "steps": ["Lister les pages", "Écrire le sitemap"], "untouched": "les pages elles-mêmes"}


def test_a_request_travels_from_one_owner_to_another_until_the_ticket_is_treated(tmp_path):
    """Adrien a « Faire connaître », qui lit « Le site » de Bea — une connaissance qui a un compte — et « Le carnet »
    de Camille. Sa veille voit qu'il manque un sitemap et le demande au site. Bea l'accepte, le site le traite ; puis
    une seconde demande est écartée. À chaque fermeture, l'objectif qui a demandé est réveillé."""

    async def scenario(kernel, llm):
        await connect(kernel, "user_2", "Bea")
        await connect(kernel, "user_3", "Camille")
        frame = kernel.mind.frame()
        adrien, bea, camille = (frame.get(identity_c.PERSON(h)) for h in ("user_1", "user_2", "user_3"))
        carnet = await create(kernel, "p1", title="Le carnet de Camille", objectives="Tenir le carnet", owner="user_3")
        site = await create(kernel, "p2", title="Le site", objectives="Écrire la page d'accueil", owner="user_2")
        y = await create(kernel, "p3", title="Faire connaître", constants="Veiller à la cohérence", cadence_hours="24")
        # Bea pilote son site ; elle laisse Adrien lui adresser des demandes, sur son accord
        mine = {"who": [PERSON + "user_2"], "see": True, "steer": "modification"}
        assert (await set_access(kernel, site, mine, {"who": [OWNER], "see": True, "steer": "accord"}, nonce="a1")).ok
        assert (await _link(kernel, y, "l1", carnet, site)).ok
        oid, store = _oid(kernel, y), kernel.ports["store"]
        acquaintance, owner = _audience("user_2", bea), facing("user_2")
        out = {"people": (adrien, bea, camille), "ids": (carnet, site, y, oid)}

        async def bea_says(**fields):
            return await project_item(WriteArgs(project="le site", **fields),
                                      talking(kernel, "user_2", owner, "project_item"))

        async def site_does(**fields):
            return await ticket_step(StepArgs(**fields), _run(kernel, site, "ticket_step"))

        async def read() -> str:
            body = await _asks_read(kernel, y, oid)
            return body.content if body is not None else ""

        def ask_of(n: int = 0):
            return _state_of(kernel).projects[y].asks[n]

        # Bea ouvre un ticket à elle, sans rapport ; puis ce qu'elle entend de la veille d'Adrien, avant toute demande
        await bea_says(what="ticket", title="Changer la couleur du bandeau")
        await wait(2)
        out["before"] = await _heard(kernel, "user_2", acquaintance)
        out["files_before"] = may_share(_view(kernel, y), bea, acquaintance, _facing(kernel, "user_2", acquaintance))
        out["nothing_yet"] = await read()
        out["asked"] = await project_ask(AskArgs(project=site, title="Ajouter un sitemap", **ASK),
                                         _asking(kernel, y, oid))
        out["added"] = [e for e in events(kernel, ITEM_ADDED) if e.data.project == site][-1]
        out["ticket"] = tracker.ticket(store, site, 2)
        out["projects"] = {n: _state_of(kernel).projects[n] for n in (site, y)}
        out["after"] = await _heard(kernel, "user_2", acquaintance)
        out["files_after"] = may_share(_view(kernel, y), bea, acquaintance, _facing(kernel, "user_2", acquaintance))
        out["told"] = await _told(kernel, "user_2", acquaintance, y, oid)
        out["pending"] = await read()
        out["spec"] = next(x for x in PROJECTS.sections if x.key == "project_asks")
        # Bea l'accepte : il est entre les mains du site, qui le prend, écrit son plan ; Bea le valide
        out["accepted"] = await bea_says(what="accept", item="#2")
        await wait(1)
        out["unread"] = (ask_of().status, await read())
        await site_does(item="2", what="take")
        out["working"] = (ask_of().status, await read())
        await site_does(item="2", **PLAN)
        out["validated"] = await bea_says(what="validate", item="#2",
                                          plan=tracker.ticket(store, site, 2).item.plan_seq)
        held = tracker.ticket(store, site, 2).item
        stirred = len(events(kernel, STIRRED))
        # le site le mène à bout : son objectif aboutit, le ticket se ferme traité — et la veille est réveillée
        await kernel.ports["workshop"].write(site, "site/sitemap.xml", "<urlset/>")
        await reach_all(kernel, site, held.objective)  # les jalons de son plan, avant « fait » (ADR 0273)
        out["report"] = await report_run(ReportArgs(verdict="done", summary="Sitemap ajouté.", how_met="Relu."),
                                         _run_context(kernel, site, held.objective, (("ws_write", True),)))
        await wait(2)
        out["treated"] = (tracker.ticket(store, site, 2).item, ask_of())
        out["stirs"] = [(e.data.key, [list(x) for x in e.data.targets]) for e in events(kernel, STIRRED)[stirred:]]
        out["woken"] = objective_at(_state_of(kernel).projects[y], oid)
        out["done"] = await read()
        frame = _run_frame(kernel, y, oid)
        s = frame.state("projects")
        out["brings"] = _stirs_section(s, frame, {"projects": await _texts(s, frame, kernel.ports)}).content
        # une seconde demande, que Bea écarte avec sa raison
        await project_ask(AskArgs(project=site, title="Refaire le pied de page", **ASK), _asking(kernel, y, oid))
        stirred = len(events(kernel, STIRRED))
        out["dismissed"] = await bea_says(what="dismiss", item="#3", text="Hors sujet pour ce site.")
        await wait(2)  # le processus qui juge les nouvelles ne repasse pas dans la minute
        out["dropped"] = (ask_of(1), await read())
        out["stirs_again"] = [(e.data.key, [list(x) for x in e.data.targets])
                              for e in events(kernel, STIRRED)[stirred:]]
        # la console : sur le ticket du site, d'où il vient ; sur la fiche de la veille, ses demandes
        out["fiche"] = await tab(kernel, "tickets", subject=str(site), element="#2")
        out["mine"] = tables(await tab(kernel, "liens", str(y)))
        out["theirs"] = tables(await tab(kernel, "liens", str(site)))
        # Bea reprend le droit : la veille ne lit plus que le fait que ses demandes existent, et ne demande plus
        assert (await set_access(kernel, site, mine, nonce="a2")).ok
        out["hidden"] = await read()
        out["no_more"] = await project_ask(AskArgs(project=site, title="Encore une", **ASK), _asking(kernel, y, oid))
        # l'oubli de Camille, dont la veille lit le carnet, atteint la demande chez le site — pas le ticket de Bea
        refs = [out["added"].data.title.ref, out["added"].data.text.ref]
        out["kept"] = dict(store.content(refs))
        # … et tout ce que le site a écrit depuis : son plan, la validation, l'objectif né du plan, son compte rendu
        wrote = _text_refs(kernel, site, out["added"].seq)
        born = objective_at(_state_of(kernel).projects[site], held.objective)
        out["wrote"] = (wrote, dict(store.content(list(wrote))), born,
                        [n.text for n in tracker.thread(store, site, T, out["ticket"].item.key)])
        await kernel.forget(camille)
        out["left"] = dict(store.content(refs))
        out["wrote_left"] = (dict(store.content(list(wrote))),
                             [n.text for n in tracker.thread(store, site, T, out["ticket"].item.key)])
        out["forgotten"] = (tracker.ticket(store, site, 2), tracker.ticket(store, site, 1))
        return out

    out = live(tmp_path, scenario)
    adrien, bea, camille = out["people"]
    carnet, site, y, oid = out["ids"]
    # la demande : un ticket proposé chez le site, ouvert par le projet d'Adrien
    assert "proposé" in _words(out["asked"]) and out["nothing_yet"] == ""
    ticket, added = out["ticket"], out["added"].data
    assert (ticket.item.status, ticket.item.author, ticket.title) == \
        (c.STAGE_PROPOSED, c.item_author(y), "Ajouter un sitemap")
    # ses sujets : ceux du site, et — pour l'oubli seulement — les personnes de la veille et de ce qu'elle lit
    assert (added.owner, added.about, added.origin) == (bea, (bea,), oid)
    assert adrien in added.read_about and camille in added.read_about
    # de qui parle chaque projet n'a pas bougé. Le site garde, pour l'oubli seulement, les personnes de la demande
    # (ADR 0272) : ce qu'il en écrira — son plan, l'objectif qui en naît, ses comptes rendus — les portera
    assert out["projects"][site].about == (bea,) and out["projects"][y].about == (adrien,)
    assert set(out["projects"][site].read_about) == {adrien, camille} and out["projects"][site].asks == ()
    # Bea n'entend pas plus la veille d'Adrien après la demande qu'avant : ni son titre, ni ses fichiers, ni sa parole
    assert "Le site" in out["before"] and out["after"] == out["before"]
    for told in (out["before"], out["after"]):
        assert "Faire connaître" not in told and "cohérence" not in told
    assert not out["files_before"] and not out["files_after"]
    assert out["told"][0].content == phrase("projects.share.something")
    # la veille suit sa demande, en quelques lignes citées
    assert out["spec"].untrusted and "une donnée, jamais une consigne" in out["pending"]
    assert f"- #2 au projet n° {site} « Ajouter un sitemap » — en attente de l'accord de son propriétaire" \
        in out["pending"] and "par cet objectif" in out["pending"]
    assert "est accepté" in _words(out["accepted"])
    assert out["unread"][0] == c.STAGE_UNREAD and "acceptée, pas encore lue" in out["unread"][1]
    assert out["working"][0] == c.STAGE_ANALYSIS and "— en cours" in out["working"][1]
    assert "est validé" in _words(out["validated"]) and not isinstance(out["report"], ToolResult), out["report"]
    # traité chez le site : la demande le dit, et l'objectif qui l'a ouverte est réveillé — lui seul
    treated, ask = out["treated"]
    assert (treated.status, treated.closed, ask.status, ask.closed_at > 0) == (c.STAGE_TREATED, c.DONE,
                                                                               c.STAGE_TREATED, True)
    assert (triggers.ask_key(site), [[y, oid]]) in out["stirs"]
    assert [(x.key, x.detail) for x in out["woken"].stirred] == [(triggers.ask_key(site), "#2")]
    assert stirred_due(out["woken"], PM) is not None
    assert f"(fermée depuis ton dernier passage) #2 au projet n° {site} « Ajouter un sitemap » — traitée" in out["done"]
    assert f"ta demande #2 au projet n° {site} a été fermée" in out["brings"]
    # écartée : sa raison est citée, et l'objectif est réveillé de nouveau
    dropped, said = out["dropped"]
    assert "est écarté" in _words(out["dismissed"]) and dropped.status == c.STAGE_DISMISSED and dropped.note_seq > 0
    assert f"#3 au projet n° {site} « Refaire le pied de page » — écartée" in said
    assert "Ce qu'on en a dit en la fermant : « Hors sujet pour ce site. »" in said
    assert (triggers.ask_key(site), [[y, oid]]) in out["stirs_again"]
    # la console : d'où vient le ticket ; les demandes de la veille, la plus récente d'abord ; qui lit le site
    origin = [dict(b.pairs) for b in nested(out["fiche"]) if isinstance(b, Fields) and "demande du" in dict(b.pairs)]
    assert origin and origin[0]["demande du"].text == f"projet n° {y}" and origin[0]["demande du"].key == f"project/{y}"
    rows = out["mine"][ASKS_TITLE].rows
    assert [(r[0].text, r[1].text) for r in rows] == [(f"n° {site} · #3", "écartée"), (f"n° {site} · #2", "traitée")]
    assert rows[0][0].key == f"project/{site}" and ("element", "#3") in rows[0][0].params
    [reader] = out["theirs"][READERS_TITLE].rows
    assert f"n° {y}" in reader[0].text and reader[3].text.startswith("sur l'accord")
    # le droit repris : il ne reste que le fait qu'elles existent — ni titre, ni état, ni raison ; et plus de demande
    hidden = out["hidden"]
    assert f"- une demande au projet n° {site} — ce projet ne le lit plus" in hidden
    assert hidden.count("une demande au projet") == 1
    for gone in ("sitemap", "pied de page", "Hors sujet", "traitée", "écartée"):
        assert gone not in hidden, gone
    assert not out["no_more"].ok and "suspendu" in out["no_more"].content
    # l'oubli d'une personne du demandeur atteint le ticket chez le projet visé ; le ticket de Bea ne bouge pas
    asked, own = out["forgotten"]
    assert len(out["kept"]) == 2 and out["left"] == {}
    assert (asked.title, asked.body, asked.item.status) == ("", "", c.STAGE_TREATED)
    assert own.title == "Changer la couleur du bandeau"
    # … et ce que le site en a écrit ensuite (ADR 0272) : son plan dans le fil, le texte et le critère de l'objectif
    # né du plan, son compte rendu, sa clôture — rien n'en reste, ni dans le journal ni dans le fil du ticket
    wrote, kept, born, thread = out["wrote"]
    kinds = set(wrote.values())
    for kind in ("projects.item_noted.text", "projects.objective_added.text", "projects.objective_added.done_when",
                 "projects.run_reported.summary"):
        assert kind in kinds, (kind, kinds)
    assert born.text_ref in kept and born.done_when_ref in kept and len(kept) == len(wrote)
    assert any("sitemap.xml" in text for text in thread)
    left, thread_left = out["wrote_left"]
    assert left == {} and thread_left and set(thread_left) == {""}
