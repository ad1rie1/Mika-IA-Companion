"""Ce qui déclenche un objectif (ADR 0265) : un constant devient dû par un événement, pas seulement par sa cadence.

- un déclencheur s'écrit comme un agenda : vérifié, normalisé, quatre au plus — et seul un constant en a ;
- un déclencheur entre projets suit le lien de lecture : un projet non lu est refusé, le projet lui-même aussi ; les
  liens ne formant jamais de boucle, les déclencheurs non plus ;
- chaque sorte pose sa cause : le commit d'un projet lu, un de ses objectifs abouti, le signal d'une app du projet ;
  un réveil par API vise l'objectif qui le déclare, et son exécution porte son sujet ;
- les réducteurs ne jugent aucun droit : ils notent ce qui arrive, le processus ``projects.stirs`` le juge. Un lien
  suspendu, ou qui ne laisse voir que le titre, ne déclenche rien — ni alors, ni une fois le droit rendu ;
- le rythme : dû au plus tôt de la cadence et du déclenchement ; un déclenchement attend que le travail se pose (un
  délai après la dernière cause, une heure au plus après la première) ; cinq causes rapprochées ne font qu'un passage,
  qui les voit toutes ; un constant sans cadence ne passe que sur événement ;
- les causes partent avec l'exécution qui vise l'objectif, et lui reviennent si elle n'a pas eu lieu ;
- l'exécution lit ce qui l'amène : l'empreinte courte d'un commit et le numéro de son projet, le titre d'un objectif
  abouti si le lien le donne encore, rien d'un projet que le lien ne donne plus.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mika.contracts import forge as forge_c
from mika.contracts import projects as c
from mika.contracts import runtime as rt
from mika.contracts import wakeup as wakeup_c
from mika.faculties.projects import triggers
from mika.faculties.projects.faculty import (
    BASE_SEEN,
    HEARD_KEPT,
    LINKS_SET,
    OBJECTIVE_ADDED,
    OBJECTIVE_CHANGED,
    PULL_CAPABILITY,
    STIR_MAX_WAIT,
    STIRRED,
    STIRS_KEPT,
    Heard,
    Objective,
    ProjectsState,
    Run,
    Stir,
    _app_signaled,
    _base_seen,
    _ended,
    _executed,
    _links_set,
    _objective_added,
    _objective_changed,
    _objective_closed,
    _reported,
    _started,
    _stirred,
    declared,
    hear_if_listening,
    listening,
    objective_of,
    stirring,
    subject_of,
    wake_aim,
)
from mika.faculties.projects.faculty import params as projects_params
from mika.faculties.projects.framing_tools import PlanArgs, _plan_problems
from mika.faculties.projects.prompt import _objective_line, _stirs_section, _texts
from mika.faculties.projects.rhythm import NEVER, due_at, next_due, pick, stirred_due
from mika.faculties.projects.tend import stirs_of
from mika.faculties.projects.tools import (
    ConstantArg,
    CreateArgs,
    ObjectiveArgs,
    ReportArgs,
    _constants,
    bad_trigger,
    project_objective_add,
    report_run,
)
from mika.faculties.projects.triggers import trigger_words, triggers_said
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content, Origin
from mika.plugins.forge import WRITTEN, outcomes, signal_draft
from mika.plugins.forge import params as forge_params
from mika.plugins.wakeup import DONE as WAKE_DONE
from mika.runtime.operations import perform
from mika.vocab.access import OWNER
from mika.vocab.episodes import Kind, project_target
from mika.vocab.phrasebook import family, phrase
from tests.fixtures.atelier import Atelier
from tests.unit import test_wakeup as waking
from tests.unit.test_project_access import set_access
from tests.unit.test_project_links import _cx, _ev, _project, _read, _state
from tests.unit.test_projects import create, events, form, live, row_form, runs, wait
from tests.unit.test_projects_console import tab, tables
from tests.unit.test_projects_framing import _ctx

PM = projects_params(None)
SETTLE = PM.stir_settle_us
T0 = 1_000 * HOUR
_N = itertools.count(1)


def _constant(oid: int = 1, **fields) -> Objective:
    return Objective(id=oid, text_ref=f"o{oid}", kind=c.CONSTANT, **fields)


def _with(s: ProjectsState, pid: int, *objectives: Objective) -> ProjectsState:
    return replace(s, projects=s.projects.set(pid, replace(s.projects[pid], objectives=objectives)))


def _chain() -> ProjectsState:
    """Le produit (1), et le site (2) qui le lit : son objectif n° 1, un constant que déclenchent les commits et les
    objectifs aboutis du produit."""
    s = _read(_state(_project(1), _project(2)), 2, 1)
    s = _with(s, 1, Objective(id=1, text_ref="o1"))
    return _with(s, 2, _constant(1, at=T0, on=(triggers.commit_key(1), triggers.done_key(1))))


def _commit(s: ProjectsState, at: int, sha: str = "abcdef0123456789", project: int = 1) -> ProjectsState:
    """Une exécution du projet rend compte et laisse un commit."""
    data = c.RUN_REPORTED.payload(project=project, objective=1, verdict=c.CONTINUE, summary=Content.of("fait"),
                                  commit=sha)
    return _reported(s, _ev(data, at), _cx())


def _judged(s: ProjectsState, *targets: tuple[int, int], at: int = 0) -> ProjectsState:
    """Le processus a jugé la plus ancienne nouvelle : elle éveille ces objectifs."""
    return _stirred(s, _ev(STIRRED.payload(news=s.heard[0].seq, targets=targets), at), _cx())


def _stirs(o: Objective) -> list[tuple[int, str, str]]:
    return [(x.at, x.key, x.detail) for x in o.stirred]


# ── La grammaire ───────────────────────────────────────────────────────────


def test_a_trigger_is_written_like_a_schedule_checked_and_normalised():
    assert triggers.checked([" Project:#3:Commit ", "app:veille", "", "wake:deploy-prod", "project:3:commit"]) == (
        "project:3:commit", "app:veille", "wake:deploy-prod")
    # les sortes, dites une seule fois (``item`` : ce qui bouge dans une liste du registre, ADR 0268)
    assert set(triggers.SORTS) == {triggers.PROJECT, triggers.APP, triggers.WAKE, triggers.ITEM}
    for text, why in (("alarm:porte", triggers.SORT), ("commit", triggers.SORT), ("project:x:commit", triggers.NUMBER),
                      ("project:0:commit", triggers.NUMBER), ("project:3", triggers.EVENT),
                      ("project:3:push", triggers.EVENT), ("app:Ma veille", triggers.NAMED), ("wake:", triggers.NAMED)):
        with pytest.raises(triggers.BadTrigger) as refused:
            triggers.checked([text])
        assert refused.value.why == why, text
    with pytest.raises(triggers.BadTrigger) as many:
        triggers.checked([f"app:a{i}" for i in range(triggers.TRIGGERS_MAX + 1)])
    assert many.value.why == triggers.TOO_MANY
    # le réducteur reste total : ce qui ne se lit pas est ignoré, comme ce qui dépasse
    assert triggers.kept(["n'importe quoi", "project:4:done", "project:4:done", "app:"]) == ("project:4:done",)
    assert len(triggers.kept([f"app:a{i}" for i in range(9)])) == triggers.TRIGGERS_MAX
    assert triggers.read("project:4:done") == triggers.Trigger(triggers.PROJECT, 4, triggers.DONE)
    assert triggers.read("rien") is None


def test_every_refusal_has_its_words_and_every_sort_says_itself():
    codes = {triggers.SORT, triggers.NUMBER, triggers.EVENT, triggers.NAMED, triggers.TOO_MANY, triggers.ITSELF,
             triggers.UNREAD, triggers.NOT_CONSTANT, triggers.NOTHING}
    assert set(family("projects.triggers.refused")) == codes
    assert "« app:Ma veille »" in bad_trigger(triggers.BadTrigger(triggers.NAMED, "app:Ma veille"))
    assert "«" not in bad_trigger(triggers.BadTrigger(triggers.NOTHING))  # rien d'écrit à citer
    said = [trigger_words(k) for k in ("project:3:commit", "project:3:done", "app:veille", "wake:deploy")]
    assert said == ["la base du projet n° 3 qui avance", "un objectif abouti du projet n° 3", "un signal de l'app veille",
                    "le réveil par API « deploy »"]
    assert triggers_said(()) == "" and "passe aussi sur" in triggers_said(("app:veille",))
    assert "passe sur" in triggers_said(("app:veille",), True) and "aussi" not in triggers_said(("app:veille",), True)


# ── Un déclencheur entre projets suit le lien ──────────────────────────────


def test_a_trigger_on_a_project_that_is_not_read_is_refused():
    wanted = ["project:1:commit"]
    with pytest.raises(triggers.BadTrigger) as unread:
        triggers.accepted(2, (), True, wanted)
    assert unread.value.why == triggers.UNREAD
    assert triggers.accepted(2, (1,), True, wanted) == ("project:1:commit",)  # lu : accepté
    with pytest.raises(triggers.BadTrigger) as itself:
        triggers.accepted(2, (1, 2), True, ["project:2:done"])
    assert itself.value.why == triggers.ITSELF  # son propre travail le relancerait sans fin
    with pytest.raises(triggers.BadTrigger) as once:
        triggers.accepted(2, (1,), False, wanted)
    assert once.value.why == triggers.NOT_CONSTANT  # seul un constant en a
    with pytest.raises(triggers.BadTrigger) as bare:
        triggers.accepted(2, (1,), True, [], True)
    assert bare.value.why == triggers.NOTHING  # sans cadence, il lui en faut un
    assert triggers.accepted(2, (), True, ["app:veille", "wake:deploy"], True) == ("app:veille", "wake:deploy")
    assert triggers.accepted(2, (), False, []) == ()


def test_the_reducer_keeps_what_holds_and_never_a_trigger_on_the_project_itself():
    s = _read(_state(_project(1), _project(2)), 2, 1)
    add = OBJECTIVE_ADDED.payload(project=2, objective=1, text=Content(ref="t"), kind=c.CONSTANT, only_on_event=True,
                                  on=("project:2:commit", "du vent", "project:1:commit", "project:1:commit", "app:x"))
    [o] = _objective_added(s, _ev(add, T0), _cx()).projects[2].objectives
    assert o.on == ("project:1:commit", "app:x") and o.only_on_event  # lui-même, l'illisible et le doublon : ignorés
    # un ponctuel n'en a pas, et « sur événement seulement » ne vaut qu'avec un déclencheur
    once = OBJECTIVE_ADDED.payload(project=2, objective=1, text=Content(ref="t"), on=("app:x",), only_on_event=True)
    [o] = _objective_added(s, _ev(once, T0), _cx()).projects[2].objectives
    assert (o.on, o.only_on_event) == ((), False)
    bare = OBJECTIVE_ADDED.payload(project=2, objective=1, text=Content(ref="t"), kind=c.CONSTANT, only_on_event=True)
    [o] = _objective_added(s, _ev(bare, T0), _cx()).projects[2].objectives
    assert (o.on, o.only_on_event) == ((), False)
    assert declared(2, c.CONSTANT, ("project:9:done",)) == ("project:9:done",)  # un projet pas encore lu : gardé, inerte


def test_changing_an_objective_keeps_drops_or_rewrites_what_fires_it():
    s = _judged(_commit(_chain(), T0 + HOUR), (2, 1))
    assert _stirs(s.projects[2].objectives[0]) == [(T0 + HOUR, "project:1:commit", "abcdef0123456789")]

    def changed(**fields) -> Objective:
        data = OBJECTIVE_CHANGED.payload(project=2, objective=1, **fields)
        return _objective_changed(s, _ev(data, T0 + 2 * HOUR), _cx()).projects[2].objectives[0]

    assert changed(cadence_us=2 * HOUR).on == ("project:1:commit", "project:1:done")  # inchangés quand on n'en dit rien
    assert changed(cadence_us=2 * HOUR).stirred  # et sa cause reste
    only_done = changed(on=("project:1:done",))
    assert only_done.on == ("project:1:done",) and only_done.stirred == () and only_done.stirred_at == 0
    assert changed(only_on_event=True).only_on_event and not changed(on=(), only_on_event=True).only_on_event
    once = changed(kind=c.ONCE)  # devenu ponctuel : plus de déclencheur, plus de cause
    assert (once.on, once.only_on_event, once.stirred) == ((), False, ())
    assert changed(status=c.BLOCKED).stirred == ()  # mis de côté : ce qui l'attendait tombe


@settings(max_examples=120, deadline=None)
@given(st.lists(st.tuples(st.integers(1, 6), st.lists(st.integers(0, 7), max_size=6)), max_size=30),
       st.integers(1, 6))
def test_triggers_never_form_a_loop(steps, first):
    """La propriété : quels que soient les liens posés, chaque projet réagissant aux commits de tout ce qu'il lit
    (et demandant, en vain, à réagir aux autres et à lui-même), un commit ne revient jamais éveiller le projet d'où
    il est parti — la cascade s'éteint."""
    s = _state(*(_project(i) for i in range(1, 7)))
    for reader, asked in steps:
        s = _links_set(s, _ev(LINKS_SET.payload(project=reader, reads=tuple(asked), by="adrien")), _cx())
    for p in list(s.projects.values()):
        others = [n for n in range(1, 7) if n not in p.reads][:triggers.TRIGGERS_MAX]  # lui-même en fait partie
        s = _with(s, p.id, _constant(1, on=declared(p.id, c.CONSTANT, map(triggers.commit_key, p.reads))),
                  _constant(2, on=declared(p.id, c.CONSTANT, map(triggers.commit_key, others))))

    def woken_by(source: int) -> set[int]:
        key = triggers.commit_key(source)
        for p in s.projects.values():
            assert triggers.commit_key(p.id) not in p.objectives[1].on  # jamais lui-même, dès le réducteur
            assert not stirring(p, p.objectives[1], key)  # un projet qu'il ne lit pas ne l'éveille jamais
        return {p.id for p in s.projects.values() if stirring(p, p.objectives[0], key)}

    woken, frontier, rounds = set(), {first}, 0
    while frontier:
        rounds += 1
        assert rounds <= len(s.projects), "une cascade plus longue que le nombre de projets : une boucle"
        reached = set()
        for source in frontier:
            for reader in woken_by(source):
                assert source in s.projects[reader].reads  # un déclencheur suit un lien posé
                reached.add(reader)
        assert first not in reached  # jamais de retour au départ
        frontier = reached - woken
        woken |= reached


# ── Qui pose une cause ─────────────────────────────────────────────────────


def test_a_sort_of_one_more_only_needs_its_line_and_fires_in_the_project_where_it_happened(monkeypatch):
    """Ce qu'une sorte de plus demande — comme le registre l'a fait pour ``item:<liste>`` (ADR 0268) : une ligne dans
    ``SORTS``, une nouvelle notée avec son projet — la grammaire, la règle du réducteur et le jugement du processus
    la prennent sans rien réécrire."""
    monkeypatch.setitem(triggers.SORTS, "alarm", triggers._named("alarm"))
    assert triggers.accepted(2, (), True, ["Alarm:porte"]) == ("alarm:porte",)
    s = _with(_state(_project(1), _project(2)), 1, _constant(1, on=("alarm:porte",)))
    s = _with(s, 2, _constant(1, on=("alarm:porte",)))
    s = hear_if_listening(s, _ev(None, T0 + 5), "alarm:porte", "12", project=2)
    assert s.heard == (Heard(T0 + 5, T0 + 5, "alarm:porte", "12", 2),)
    assert stirs_of(s, None, s.heard[0]) == ((2, 1),)  # son projet seulement : l'autre « porte » dort
    stirred = _judged(s, (2, 1))
    assert _stirs(stirred.projects[2].objectives[0]) == [(T0 + 5, "alarm:porte", "12")]
    assert stirred.projects[1].objectives[0].stirred == ()
    assert trigger_words("alarm:porte") == "alarm:porte"  # ses mots restent à écrire, avec sa sorte


def test_the_reducers_note_what_happens_and_judge_nothing():
    """Un commit, un objectif abouti, le signal d'une app : notés seulement si un objectif les attend, sans rien
    lire de ce qu'un lien donne — c'est le processus qui écrit ``projects.stirred``."""
    s = _chain()
    quiet = c.RUN_REPORTED.payload(project=1, objective=1, verdict=c.CONTINUE, summary=Content.of("rien de neuf"))
    assert _reported(s, _ev(quiet, T0 + 1), _cx()).heard == ()  # sans commit : rien
    assert _commit(s, T0 + 2, project=2).heard == ()  # personne ne lit le site : rien
    s = _commit(s, T0 + 3, "c0ffee1234")
    assert s.heard == (Heard(T0 + 3, T0 + 3, "project:1:commit", "c0ffee1234", 1),)
    assert s.projects[2].objectives[0].stirred == ()  # noté, pas encore jugé
    closed = c.OBJECTIVE_CLOSED.payload(project=1, objective=1, status=c.DONE, title=Content.of("Écrire le module"))
    s = _objective_closed(s, _ev(closed, T0 + 4), _cx())
    assert [(h.key, h.detail) for h in s.heard] == [("project:1:commit", "c0ffee1234"), ("project:1:done", "1")]
    blocked = c.OBJECTIVE_CLOSED.payload(project=2, objective=1, status=c.BLOCKED, title=Content.of("x"))
    assert _objective_closed(s, _ev(blocked, T0 + 5), _cx()).heard == s.heard  # bloqué n'est pas abouti
    # une app : notée si un objectif l'attend, d'où qu'elle vienne — son projet se lit plus tard
    signal = signal_draft("veille", "le site est en ligne", 0.6, "").data
    assert _app_signaled(s, _ev(signal, T0 + 6), _cx()).heard == s.heard
    apps = _with(s, 2, _constant(1, on=("app:veille",)))
    assert _app_signaled(apps, _ev(signal, T0 + 6), _cx()).heard[-1] == Heard(T0 + 6, T0 + 6, "app:veille", "app")
    # la file reste bornée
    for i in range(HEARD_KEPT + 5):
        s = _commit(s, T0 + 10 + i, f"{i:040x}")
    assert len(s.heard) == HEARD_KEPT


def test_a_reader_wakes_when_the_base_moves_never_at_the_commit_of_a_working_branch():
    """Ce que le banc de la chaîne a montré (ADR 0280) : ``project:<n>:commit`` veut dire « la base du projet lu a
    avancé ». En flux direct, le commit d'une exécution ; en flux par pull request, ce qu'une récupération ramène —
    la fusion acceptée —, jamais le commit d'une branche de travail, que la vue du lecteur ne montre pas."""
    direct = _commit(_chain(), T0 + 1, "a" * 40)
    assert [(h.key, h.detail) for h in direct.heard] == [("project:1:commit", "a" * 40)]
    assert direct.projects[1].base_commit == "a" * 40
    # le même commit redit ne fait pas avancer la base
    assert _commit(direct, T0 + 2, "a" * 40).heard == direct.heard
    # flux par pull request : le commit d'une exécution est sur sa branche de travail
    s = _chain()
    s = replace(s, projects=s.projects.set(1, replace(s.projects[1], remote="https://github.com/moi/produit.git",
                                                      flow=c.FLOW_PR)))
    worked = _commit(s, T0 + 1, "b" * 40)
    assert worked.heard == () and worked.projects[1].base_commit == "" and worked.projects[1].last_commit == "b" * 40
    # une récupération aboutie : la base est à relire — une récupération en échec, ou un envoi, non
    s = replace(worked, proposals=worked.proposals.set(7, (1, PULL_CAPABILITY)))
    failed = _executed(s, _ev(rt.EFFECT_EXECUTED.payload(proposal=7, ok=False, result="refusé"), T0 + 2), _cx())
    assert not failed.projects[1].base_unread
    pulled = _executed(s, _ev(rt.EFFECT_EXECUTED.payload(proposal=7, ok=True, result="avance"), T0 + 2), _cx())
    assert pulled.projects[1].base_unread and pulled.heard == ()
    # la base relue a avancé : c'est cela qu'un lecteur attend
    seen = _base_seen(pulled, _ev(BASE_SEEN.payload(project=1, commit="c" * 40), T0 + 3), _cx())
    assert seen.heard == (Heard(T0 + 3, T0 + 3, "project:1:commit", "c" * 40, 1),)
    assert (seen.projects[1].base_commit, seen.projects[1].base_unread) == ("c" * 40, False)
    # relue au même commit (une récupération qui ne ramène rien), ou illisible : rien, et plus rien n'attend
    again = replace(seen, projects=seen.projects.set(1, replace(seen.projects[1], base_unread=True)))
    for commit in ("c" * 40, ""):
        same = _base_seen(again, _ev(BASE_SEEN.payload(project=1, commit=commit), T0 + 4), _cx())
        assert same.heard == seen.heard and not same.projects[1].base_unread
        assert same.projects[1].base_commit == "c" * 40
    # total : un projet inconnu ne change rien
    assert _base_seen(seen, _ev(BASE_SEEN.payload(project=99, commit="d" * 40), T0 + 5), _cx()) == seen


def test_a_judged_news_leaves_the_queue_and_stirs_only_what_still_holds():
    s = _commit(_chain(), T0 + HOUR, "c0ffee1234")
    stirred = _judged(s, (2, 1), (2, 1), (2, 99), (99, 1), (1, 1))
    assert stirred.heard == ()
    [o] = stirred.projects[2].objectives
    assert _stirs(o) == [(T0 + HOUR, "project:1:commit", "c0ffee1234")] and o.stirred_at == T0 + HOUR  # une fois
    assert stirred.projects[1].objectives[0].stirred == ()  # le produit ne se déclenche pas lui-même
    # aucun objectif éveillé (un lien qui ne donne plus rien) : la nouvelle part quand même, pour de bon
    silent = _judged(s)
    assert silent.heard == () and silent.projects[2].objectives[0].stirred == ()
    assert _stirred(silent, _ev(STIRRED.payload(news=T0 + HOUR, targets=((2, 1),))), _cx()) == silent  # déjà partie
    # le lien retiré entre-temps, l'objectif mis de côté, le déclencheur retiré : ignoré
    unlinked = _judged(_read(s, 2), (2, 1))
    assert unlinked.projects[2].objectives[0].stirred == ()
    aside = _judged(_with(s, 2, replace(s.projects[2].objectives[0], status=c.BLOCKED)), (2, 1))
    assert aside.projects[2].objectives[0].stirred == ()
    assert not stirring(s.projects[2], replace(s.projects[2].objectives[0], on=("project:1:done",)), "project:1:commit")
    assert listening(s, "project:1:commit") and not listening(s, "project:2:commit")


def test_an_objective_keeps_eight_causes_and_the_instant_of_the_first():
    s = _chain()
    for i in range(STIRS_KEPT + 3):
        s = _judged(_commit(s, T0 + i * MINUTE, f"sha{i:02d}"), (2, 1))
    [o] = s.projects[2].objectives
    assert len(o.stirred) == STIRS_KEPT == 8 and o.stirred_more == 3
    assert [x.detail for x in o.stirred] == [f"sha{i:02d}" for i in range(3, STIRS_KEPT + 3)]  # les plus récentes
    assert o.stirred_at == T0  # la première, même tombée de la liste : le plafond se compte depuis elle


# ── Le rythme ──────────────────────────────────────────────────────────────


def test_a_stirred_constant_is_due_when_the_work_has_settled_an_hour_at_most_after_the_first_cause():
    p = _chain().projects[2]
    [o] = p.objectives
    assert due_at(p, o, PM) == T0 + DAY and stirred_due(o, PM) is None  # sa cadence seule
    one = replace(o, stirred=(Stir(T0 + HOUR, "project:1:commit", "a"),), stirred_at=T0 + HOUR)
    assert SETTLE == 15 * MINUTE and due_at(p, one, PM) == T0 + HOUR + SETTLE  # le plus tôt des deux
    assert pick(p, T0 + HOUR + SETTLE - 1, PM) is None
    # chaque cause repousse le passage… jusqu'à une heure après la première
    at, causes = T0 + HOUR, []
    for _ in range(8):
        causes.append(Stir(at, "project:1:commit", "a"))
        busy = replace(o, stirred=tuple(causes), stirred_at=T0 + HOUR)
        assert due_at(p, busy, PM) == min(at + SETTLE, T0 + HOUR + STIR_MAX_WAIT)
        at += 10 * MINUTE
    assert due_at(p, busy, PM) == T0 + 2 * HOUR  # le plafond : huit causes en 70 minutes ne l'ont pas repoussé au-delà
    # le plafond tient même quand la première cause est tombée de la liste
    late = replace(o, stirred=(Stir(T0 + 3 * HOUR, "project:1:commit", "z"),), stirred_at=T0 + HOUR, stirred_more=20)
    assert due_at(p, late, PM) == T0 + 2 * HOUR
    # une attente qu'elle a demandée tient toujours ; sa cadence passe devant quand elle tombe plus tôt
    assert due_at(p, replace(one, waiting_until=T0 + 5 * HOUR), PM) == T0 + 5 * HOUR
    soon = replace(one, cadence_us=HOUR, passed_at=T0)
    assert due_at(p, soon, PM) == T0 + HOUR


def test_five_causes_in_a_row_make_one_pass_that_sees_them_all():
    s = _chain()
    for i in range(5):  # cinq commits, à trois minutes d'intervalle
        s = _judged(_commit(s, T0 + HOUR + i * 3 * MINUTE, f"sha{i}"), (2, 1))
    last = T0 + HOUR + 12 * MINUTE
    p = s.projects[2]
    assert next_due(p, PM) == last + SETTLE
    assert pick(p, last + SETTLE - 1, PM) is None and pick(p, last + SETTLE, PM).id == 1
    start = rt.EPISODE_STARTED.payload(kind=Kind.WORK, target=project_target(2), subject=subject_of(2, 1))
    s = _started(s, _ev(start, last + SETTLE, "run-1"), _cx())
    run, [o] = s.running["run-1"], s.projects[2].objectives
    assert [x.detail for x in run.stirred] == [f"sha{i}" for i in range(5)] and run.stirred_at == T0 + HOUR
    assert o.stirred == () and o.stirred_at == 0  # parties avec l'exécution : un seul passage
    assert pick(s.projects[2], last + 2 * HOUR, PM) is None and next_due(s.projects[2], PM) == T0 + DAY


def test_a_constant_without_a_cadence_only_passes_on_an_event():
    s = _with(_chain(), 2, _constant(1, at=T0, on=("project:1:commit",), only_on_event=True))
    p = s.projects[2]
    assert due_at(p, p.objectives[0], PM) == NEVER and next_due(p, PM) is None
    assert pick(p, T0 + 400 * DAY, PM) is None  # sa cadence ne le ramène jamais
    s = _judged(_commit(s, T0 + 400 * DAY), (2, 1))
    p = s.projects[2]
    assert next_due(p, PM) == T0 + 400 * DAY + SETTLE and pick(p, T0 + 400 * DAY + SETTLE, PM).id == 1
    # « lancer maintenant » le fait passer quand même : c'est une demande, pas sa cadence
    nudged = replace(_chain().projects[2], nudged_at=T0 + 1, objectives=(replace(p.objectives[0], stirred=()),))
    assert pick(nudged, T0 + 2, PM).id == 1
    line = _objective_line(p.objectives[0], {"o1": "Relire la cohérence"}, PM, T0 + 400 * DAY)
    assert "constant, sans cadence" in line and "passe sur : la base du projet n° 1 qui avance" in line


# ── Les causes partent avec l'exécution, et lui reviennent si elle n'a pas eu lieu ─


def _run_of(s: ProjectsState, at: int, key: str = "run-1") -> ProjectsState:
    start = rt.EPISODE_STARTED.payload(kind=Kind.WORK, target=project_target(2), subject=subject_of(2, 1))
    return _started(s, _ev(start, at, key), _cx())


def _end_of(s: ProjectsState, at: int, outcome: str, key: str = "run-1") -> ProjectsState:
    end = rt.EPISODE_ENDED.payload(kind=Kind.WORK, outcome=outcome, target=project_target(2))
    return _ended(s, _ev(end, at, key), _cx())


def test_the_causes_leave_with_the_run_and_a_run_that_did_not_happen_gives_them_back():
    s = _judged(_commit(_chain(), T0 + HOUR, "sha0"), (2, 1))
    s = _run_of(_judged(_commit(s, T0 + HOUR + MINUTE, "sha1"), (2, 1)), T0 + 2 * HOUR)
    assert s.projects[2].objectives[0].stirred == () and len(s.running["run-1"].stirred) == 2
    # un commit arrive pendant l'exécution : c'est une cause de plus, pour le passage suivant
    during = _judged(_commit(s, T0 + 2 * HOUR + MINUTE, "sha2"), (2, 1))
    for outcome in ("failed", "timeout", "superseded", "preempted", "cancelled", "interrupted"):
        back = _end_of(during, T0 + 2 * HOUR + 5 * MINUTE, outcome).projects[2].objectives[0]
        assert [x.detail for x in back.stirred] == ["sha0", "sha1", "sha2"], outcome  # rendues, dans l'ordre
        assert back.stirred_at == T0 + HOUR and back.runs == 0
        assert due_at(during.projects[2], back, PM) <= T0 + 2 * HOUR + MINUTE + SETTLE  # le passage reste dû
    # elle a travaillé (sans conclure, ou en rendant compte) : elle les a vues, il ne reste que celle d'après
    silent = _end_of(during, T0 + 2 * HOUR + 5 * MINUTE, "done").projects[2].objectives[0]
    assert [x.detail for x in silent.stirred] == ["sha2"] and silent.stirred_at == T0 + 2 * HOUR + MINUTE
    report = c.RUN_REPORTED.payload(project=2, objective=1, verdict=c.DONE, summary=Content.of("relu"))
    told = _end_of(_reported(during, _ev(report, T0 + 2 * HOUR + 4 * MINUTE, "run-1"), _cx()), T0 + 2 * HOUR + 5 * MINUTE,
                   "failed").projects[2].objectives[0]
    assert [x.detail for x in told.stirred] == ["sha2"] and told.passes == 1
    # rendues à un objectif qui ne les déclare plus : rien
    dropped = _objective_changed(during, _ev(OBJECTIVE_CHANGED.payload(project=2, objective=1, on=()), T0 + 3 * HOUR),
                                 _cx())
    assert _end_of(dropped, T0 + 3 * HOUR + 1, "failed").projects[2].objectives[0].stirred == ()
    # trop de causes rendues : les plus récentes, et le compte de celles qui tombent
    full = replace(during, running=during.running.set("run-1", replace(
        during.running["run-1"], stirred=tuple(Stir(T0 + i, "project:1:commit", f"old{i}") for i in range(STIRS_KEPT)),
        stirred_at=T0)))
    crowded = _end_of(full, T0 + 3 * HOUR, "failed").projects[2].objectives[0]
    assert len(crowded.stirred) == STIRS_KEPT and crowded.stirred[-1].detail == "sha2" and crowded.stirred_more == 1
    assert isinstance(full.running["run-1"], Run) and crowded.stirred_at == T0


# ── Un réveil vise un objectif ─────────────────────────────────────────────


def test_a_wake_aims_at_the_open_constant_that_declares_it():
    p = replace(_project(1), objectives=(Objective(id=1, text_ref="o1"), _constant(2, on=("wake:serre",)),
                                         _constant(3, on=("wake:serre", "wake:porte"))))
    assert wake_aim(p, "serre").id == 2 and wake_aim(p, "porte").id == 3 and wake_aim(p, "cave") is None
    aside = replace(p, objectives=(p.objectives[0], replace(p.objectives[1], status=c.BLOCKED), p.objectives[2]))
    assert wake_aim(aside, "serre").id == 3  # le premier **ouvert**
    assert wake_aim(replace(p, plan_state=c.TO_FRAME), "serre") is None  # sans plan qui vaille, aucun objectif visé
    # le sujet de l'exécution porte l'appel et ce qu'il vise : chacun y relit le sien
    subject = wakeup_c.subject(41, subject_of(1, 2))
    assert subject == "wakeup:41@objective:1:2"
    assert wakeup_c.call_of(subject) == 41 and wakeup_c.aim_of(subject) == "objective:1:2"
    assert objective_of(subject) == (1, 2) and objective_of(wakeup_c.subject(41)) is None
    assert wakeup_c.subject(41) == "wakeup:41" and wakeup_c.aim_of("wakeup:41") == ""
    assert wakeup_c.aim_of("objective:1:2") == "" and wakeup_c.call_of("wakeup:dire:41") is None


def test_a_wake_on_a_project_runs_the_objective_that_declares_it(tmp_path):
    """Dans un vrai noyau : un réveil « serre » sur un projet, un constant qui le déclare — l'exécution que le réveil
    lance vise cet objectif, son compte rendu compte pour son passage, et l'agenda du projet ne bouge pas."""

    async def scenario(kernel, llm):
        pid = await waking.new_project(kernel)
        added = await perform(kernel, "projects.objectif_ajouter", form(
            text="Réagir à l'alerte de la serre", kind="constant", cadence_hours="0", on="wake:serre",
            only_on_event="on"), by="user_1", subject=str(pid), nonce="o1")
        frame = kernel.mind.frame()
        aim = frame.get(c.WAKE_AIM((pid, "serre"))), frame.get(c.WAKE_AIM((pid, "porte")))
        seq = await waking.wake(kernel, project=pid, plain=True, bundles=())
        await waking.settle(kernel, lambda: waking.call(kernel, seq).status == WAKE_DONE, limit=2 * HOUR)
        started = [e for e in waking.of(kernel, rt.EPISODE_STARTED) if wakeup_c.call_of(e.data.subject) == seq]
        reported = [e for e in waking.of(kernel, c.RUN_REPORTED) if e.data.project == pid]
        return pid, added, aim, seq, started, reported, kernel.mind.frame().state("projects").projects[pid], \
            waking.wakes(llm, roles=("job",))

    pid, added, aim, seq, started, reported, project, reqs = waking.live(tmp_path, scenario,
                                                                         ports={"workshop": Atelier()})
    assert added.ok, added
    assert aim == (f"objective:{pid}:2", "")
    assert [s.data.subject for s in started] == [f"wakeup:{seq}@objective:{pid}:2"]
    assert [(s.data.kind, s.data.target) for s in started] == [(Kind.JOB, f"project:{pid}")]
    assert [r.data.objective for r in reported] == [2]  # son compte rendu est celui de l'objectif visé
    aimed = project.objectives[1]
    assert (aimed.on, aimed.only_on_event, aimed.runs, aimed.passes) == (("wake:serre",), True, 1, 1)
    assert project.last_run_at == 0 and project.tried_at == 0  # comme avant : l'agenda du projet n'a pas bougé
    state, _ = waking.split(reqs[0])
    assert phrase("projects.stirs.title") in state and phrase("projects.stirs.woken") in state
    assert phrase("projects.run.target") in state and "Réagir à l'alerte de la serre" in state
    assert "CE QU'ON TE DEMANDE" in state  # les sections du réveil sont toujours là


# ── Dans un vrai noyau : un commit du produit rend dû un objectif du site ──


async def _chain_live(kernel, on: str = "commit", cadence: str = "720") -> tuple[int, int]:
    """Le produit (sur demande : il ne part jamais seul) et le site, qui le lit ; l'objectif constant du site, que
    déclenche le produit."""
    produit = await create(kernel, "p1", title="Le produit", objectives="Écrire le module", schedule="demand")
    site = await create(kernel, "p2", title="Le site", constants="Relire la cohérence du site",
                        cadence_hours=cadence)
    got = await perform(kernel, "projects.liens", form(**{f"lit_{produit}": "on"}), by="user_1", subject=str(site),
                        nonce="l1")
    assert got.ok, got
    got = await perform(kernel, "projects.objectif_modifier", row_form(
        {"objective": "1"}, text="Relire la cohérence du site", kind="constant", cadence_hours=cadence,
        on=f"project:{produit}:{on}"), by="user_1", subject=str(site), nonce="o1")
    assert got.ok, got
    return produit, site


async def _work(kernel, pid: int, verdict: str = c.CONTINUE, summary: str = "Le module avance.") -> str:
    """Une exécution du projet écrit dans son atelier et rend compte : elle laisse un commit."""
    await kernel.ports["workshop"].write(pid, "module.py", f"version = {next(_N)}\n")
    await report_run(ReportArgs(verdict=verdict, summary=summary, how_met="le module est écrit"),
                     _ctx(kernel, "report_run", Kind.WORK, project_target(pid), subject=f"objective:{pid}:1"))
    return events(kernel, c.RUN_REPORTED)[-1].data.commit


def _objective(kernel, pid: int, oid: int = 1) -> Objective:
    return next(o for o in kernel.mind.frame().state("projects").projects[pid].objectives if o.id == oid)


def _amenee(llm) -> list[str]:
    """Ce que chaque exécution a lu de ce qui l'amène."""
    title = phrase("projects.stirs.title")
    return [text.split(title, 1)[1].split("\n\n", 1)[0] for r in llm.calls if r.role in ("project", "job")
            for text in [r.messages[-1].content] if title in text]


def test_a_commit_in_the_product_makes_the_site_pass_once_within_the_quarter_of_an_hour(tmp_path):
    async def scenario(kernel, llm):
        produit, site = await _chain_live(kernel)
        before = len(runs(kernel, site))
        await wait(90)  # sa cadence d'un mois : rien ne part de lui-même
        idle = len(runs(kernel, site))
        sha = await _work(kernel, produit)
        at = kernel.mind.clock.now()
        await wait(2)
        waiting = _objective(kernel, site)
        await wait(6 * 60)
        await kernel.lanes.join()
        return produit, site, before, idle, sha, at, waiting, runs(kernel, site), events(kernel, STIRRED), \
            _objective(kernel, site), _amenee(llm), kernel.mind.frame().state("projects")

    produit, site, before, idle, sha, at, waiting, started, stirred, after, read, s = live(tmp_path, scenario)
    assert before == idle == 0 and sha
    # le processus a jugé la nouvelle, et l'objectif attend que le travail se pose
    assert [(e.data.targets, e.origin) for e in stirred] == [(((site, 1),), Origin.PROCESS)]
    assert _stirs(waiting) == [(at, f"project:{produit}:commit", sha)] and s.heard == ()
    # un seul passage, dans le quart d'heure qui suit le délai d'attente
    assert len(started) == 1 and started[0].data.subject == subject_of(site, 1)
    assert at + SETTLE <= started[0].at <= at + SETTLE + 15 * MINUTE, (started[0].at - at) / MINUTE
    assert after.stirred == () and after.passes == 1  # la cause est partie avec lui
    [lines] = read
    assert phrase("projects.stirs.commit", ago="15 min", id=produit, sha=sha[:7]) in lines
    assert phrase("projects.stirs.see_links") in lines


def test_five_commits_in_a_row_make_one_pass_of_the_site_that_reads_them_all(tmp_path):
    async def scenario(kernel, llm):
        produit, site = await _chain_live(kernel)
        shas = []
        for _ in range(5):
            shas.append(await _work(kernel, produit))
            await wait(3)
        await wait(4 * 60)
        await kernel.lanes.join()
        return produit, site, shas, runs(kernel, site), _amenee(llm), _objective(kernel, site)

    produit, site, shas, started, read, after = live(tmp_path, scenario)
    assert len(set(shas)) == 5 and len(started) == 1 and after.passes == 1
    [lines] = read
    assert [line.count(f"au commit {sha[:7]} ") for sha in shas for line in [lines]] == [1] * 5
    assert lines.index(shas[0][:7]) < lines.index(shas[4][:7])  # de la plus ancienne à la plus récente


def test_a_suspended_link_fires_nothing_then_or_later(tmp_path):
    """Le propriétaire du produit ne laisse plus que son titre, puis plus rien : ses commits n'éveillent plus le site
    — et ce qui est arrivé pendant ce temps ne l'éveille pas non plus une fois le droit rendu."""

    async def scenario(kernel, llm):
        produit, site = await _chain_live(kernel)
        out = {}
        await set_access(kernel, produit, {"who": [OWNER], "see": True}, nonce="a1")  # son titre, pas son détail
        await _work(kernel, produit)
        await wait(2)
        out["title_only"] = _objective(kernel, site).stirred
        await set_access(kernel, produit, {"who": [OWNER]}, nonce="a2")  # plus visible : le lien est suspendu
        await _work(kernel, produit)
        await wait(2)
        out["suspended"] = _objective(kernel, site).stirred
        out["judged"] = [e.data.targets for e in events(kernel, STIRRED)]
        await set_access(kernel, produit, {"who": [OWNER], "see": True, "steer": "lecture"}, nonce="a3")
        await wait(3 * 60)
        out["later"] = (_objective(kernel, site).stirred, len(runs(kernel, site)), kernel.mind.frame().state("projects").heard)
        sha = await _work(kernel, produit)  # le lien redonne le détail : le commit suivant, lui, déclenche
        await wait(2)
        out["again"] = [x.detail for x in _objective(kernel, site).stirred] == [sha]
        return out

    out = live(tmp_path, scenario)
    assert out["title_only"] == () and out["suspended"] == ()
    assert out["judged"] == [(), ()]  # deux nouvelles entendues, jugées, sans personne à éveiller
    assert out["later"] == ((), 0, ())  # rien n'est resté en attente du droit
    assert out["again"]


def test_an_objective_done_in_the_product_fires_the_site_which_reads_its_title_while_the_link_gives_it(tmp_path):
    async def scenario(kernel, llm):
        produit, site = await _chain_live(kernel, on="done")
        await _work(kernel, produit, c.DONE, "Le module est écrit.")
        await wait(2)
        cause = _objective(kernel, site).stirred
        run = _ctx(kernel, "report_run", Kind.WORK, project_target(site), subject=f"objective:{site}:1")
        s = run.frame.state("projects")
        enriched = await _texts(s, run.frame, kernel.ports)
        full = _stirs_section(s, run.frame, {"projects": enriched})
        # le droit est repris avant le passage : la cause reste, ce qu'on en dit se relit au moment de le dire
        await set_access(kernel, produit, {"who": [OWNER], "see": True}, nonce="a1")
        run = _ctx(kernel, "report_run", Kind.WORK, project_target(site), subject=f"objective:{site}:1")
        s = run.frame.state("projects")
        hidden_texts = await _texts(s, run.frame, kernel.ports)
        hidden = _stirs_section(s, run.frame, {"projects": hidden_texts})
        closed = events(kernel, c.OBJECTIVE_CLOSED)
        return produit, site, cause, full, hidden, dict(hidden_texts["texts"]), closed

    produit, site, cause, full, hidden, hidden_texts, closed = live(tmp_path, scenario)
    assert [e.data.status for e in closed] == [c.DONE]
    assert [(x.key, x.detail) for x in cause] == [(f"project:{produit}:done", "1")]
    assert f"le projet n° {produit} a mené à bout son objectif n° 1 : « Écrire le module »" in full.content
    assert phrase("projects.stirs.foreign") in full.content  # un titre venu d'ailleurs : une donnée
    assert f"project:{produit}" in full.provenance and full.level >= 1
    # le lien ne donne plus que le titre du projet : ni le titre de l'objectif, ni son numéro
    assert "Écrire le module" not in hidden.content and "Écrire le module" not in hidden_texts.values()
    assert phrase("projects.stirs.unread", ago="2 min", id=produit) in hidden.content
    assert hidden.provenance == (f"project:{site}",)


def test_a_signal_of_an_app_of_the_project_fires_its_objective_and_another_projects_app_does_not(tmp_path):
    async def scenario(kernel, llm):
        produit, site = await _chain_live(kernel)
        got = await perform(kernel, "projects.objectif_ajouter", form(
            text="Réagir à ce que la veille signale", kind="constant", cadence_hours="0",
            on="app:veille\napp:ailleurs", only_on_event="on"), by="user_1", subject=str(site), nonce="o2")
        assert got.ok, got

        async def app(name: str, project: int) -> None:
            await kernel.mind.append([WRITTEN.draft(app=name, version=1, title=name.title(), project=project)],
                                     emitter="forge", correlation="genese", origin=Origin.GENESIS)

        await app("veille", site)
        await app("ailleurs", produit)  # une app d'un autre projet : elle n'éveille pas le site
        for name in ("ailleurs", "veille"):
            await kernel.mind.append([signal_draft(name, "le site ne répond plus", 0.7, "")], emitter="forge",
                                     correlation=f"signal-{name}", origin=Origin.PROCESS)
        at = kernel.mind.clock.now()
        await wait(2)
        waiting = _objective(kernel, site, 2)
        run = _ctx(kernel, "report_run", Kind.WORK, project_target(site), subject=f"objective:{site}:2")
        section = _stirs_section(run.frame.state("projects"), run.frame, {})
        row = tables(await tab(kernel, "objectifs", str(site)))["Ses objectifs"].rows[-1]
        return site, at, waiting, [e.data.targets for e in events(kernel, STIRRED)], section.content, row

    site, at, waiting, judged, section, row = live(tmp_path, scenario)
    assert sorted(judged) == [(), ((site, 2),)]
    assert _stirs(waiting) == [(at, "app:veille", forge_c.APP_SIGNAL)]
    assert phrase("projects.stirs.app", ago="2 min", name="veille") in section and "ailleurs" not in section
    rhythm = row.cells[4]  # la console dit ce qui le déclenche, et ce qui attend
    assert "sans cadence" in rhythm and "déclenché par un signal de l'app veille, un signal de l'app ailleurs" in rhythm
    assert "1 cause en attente" in rhythm


def test_a_signal_an_app_queues_wakes_the_objective_that_listens_without_waiting_for_its_triage(tmp_path):
    """Ce que le banc de la chaîne a montré (ADR 0280) : six signaux mis en file pendant une panne du site, aucun
    passage — le déclencheur n'entendait que le signal public (une panne de l'app, ce qu'elle garde en tête après le
    tri). Un signal qu'une app d'un projet met en file éveille l'objectif qui l'écoute, par un fait public de la
    Forge qui ne dit que le nom de l'app."""
    async def scenario(kernel, llm):
        produit, site = await _chain_live(kernel)
        got = await perform(kernel, "projects.objectif_ajouter", form(
            text="Réagir quand le site ne répond plus", kind="constant", cadence_hours="0",
            on="app:veille\napp:libre", only_on_event="on"), by="user_1", subject=str(site), nonce="o2")
        assert got.ok, got
        for name, project in (("veille", site), ("libre", 0)):  # une app sans projet n'éveille rien
            await kernel.mind.append([WRITTEN.draft(app=name, version=1, title=name.title(), project=project,
                                                    signals=(20, 5, 60))],
                                     emitter="forge", correlation="genese", origin=Origin.GENESIS)
        frame = kernel.mind.frame()
        call = SimpleNamespace(ok=True, error="", emits=(), signals=(("le site répond 503", 0.9, ""),) * 3)
        for name in ("libre", "veille", "veille"):
            app = frame.state("forge").apps[name]
            drafts = outcomes(name, app, [call], frame.now, forge_params(frame.env.params_of("forge", frame.root)))
            await kernel.mind.append(drafts, emitter="forge", correlation=f"appel-{name}", origin=Origin.PROCESS)
        at = kernel.mind.clock.now()
        await wait(2)
        waiting = _objective(kernel, site, 2)
        run = _ctx(kernel, "report_run", Kind.WORK, project_target(site), subject=f"objective:{site}:2")
        section = _stirs_section(run.frame.state("projects"), run.frame, {})
        await wait(60)
        await kernel.lanes.join()
        started = [e for e in runs(kernel, site) if e.data.subject == subject_of(site, 2)]
        return site, at, waiting, events(kernel, forge_c.QUEUED), events(kernel, forge_c.RAISED), \
            events(kernel, forge_c.SIGNALED), section.content, started

    site, at, waiting, queued, raised, signaled, section, started = live(tmp_path, scenario)
    # neuf signaux en file, aucun signal public : ni panne, ni tri
    assert len(queued) == 9 and signaled == []
    # un fait public par lot d'appels d'une app qui vit dans un projet — et il ne dit que son nom
    assert [e.data.model_dump() for e in raised] == [{"app": "veille"}, {"app": "veille"}]
    assert forge_c.RAISED.public and not forge_c.QUEUED.public
    assert _stirs(waiting) == [(at, "app:veille", forge_c.APP_QUEUED)] * 2
    assert phrase("projects.stirs.app_queued", ago="2 min", name="veille") in section and "503" not in section
    assert len(started) == 1  # deux lots rapprochés : un seul passage, qui les voit tous


# ── Ses outils et la console ───────────────────────────────────────────────


def test_her_tools_and_the_console_refuse_a_trigger_on_a_project_that_is_not_read(tmp_path):
    async def scenario(kernel, llm):
        produit = await create(kernel, "p1", title="Le produit", objectives="Écrire le module", schedule="demand")
        site = await create(kernel, "p2", title="Le site", objectives="Écrire la page", schedule="demand")
        wanted = [f"project:{produit}:commit"]
        out = {}

        async def add(**args):
            return await project_objective_add(ObjectiveArgs(text="Relire la cohérence", kind="constant", **args),
                                               _ctx(kernel, "project_objective_add", Kind.WORK, project_target(site)))

        def console(nonce: str, **fields: str):
            return perform(kernel, "projects.objectif_ajouter", form(
                ("only_on_event",), text="Suivre le produit", kind="constant", cadence_hours="0", **fields),
                by="user_1", subject=str(site), nonce=nonce)

        out["unread"] = await add(on=wanted)
        out["console_unread"] = await console("c1", on=wanted[0])
        out["itself"] = await add(on=[f"project:{site}:done"])
        out["bare"] = await add(only_on_event=True)
        out["once"] = await project_objective_add(
            ObjectiveArgs(text="Une fois", on=["app:veille"]),
            _ctx(kernel, "project_objective_add", Kind.WORK, project_target(site)))
        out["before"] = len(kernel.mind.frame().state("projects").projects[site].objectives)
        got = await perform(kernel, "projects.liens", form(**{f"lit_{produit}": "on"}), by="user_1", subject=str(site),
                            nonce="l1")
        assert got.ok, got
        out["read"] = await add(on=[*wanted, "wake:deploy"], only_on_event=True)
        out["console_read"] = await console("c2", on=f"{wanted[0]}\napp:veille")
        out["console_once"] = await perform(kernel, "projects.objectif_ajouter", form(
            ("only_on_event",), text="Une fois", kind="once", cadence_hours="0", on="app:veille"), by="user_1",
            subject=str(site), nonce="c3")
        # « Modifier l'objectif » : retirer un déclencheur, puis rien de plus à changer ; un ponctuel n'en prend pas
        out["edit"] = await perform(kernel, "projects.objectif_modifier", row_form(
            {"objective": "3"}, text="Suivre le produit", kind="constant", cadence_hours="0", on="app:veille",
            only_on_event="on"), by="user_1", subject=str(site), nonce="e1")
        out["edit_same"] = await perform(kernel, "projects.objectif_modifier", row_form(
            {"objective": "3"}, text="Suivre le produit", kind="constant", cadence_hours="0", on="app:veille",
            only_on_event="on"), by="user_1", subject=str(site), nonce="e2")
        out["edit_once"] = await perform(kernel, "projects.objectif_modifier", row_form(
            {"objective": "1"}, text="Écrire la page", kind="once", cadence_hours="0", on="app:veille"),
            by="user_1", subject=str(site), nonce="e3")
        return produit, out, kernel.mind.frame().state("projects").projects[site]

    produit, out, p = live(tmp_path, scenario)
    words = family("projects.triggers.refused")
    for key, why in (("unread", triggers.UNREAD), ("itself", triggers.ITSELF), ("bare", triggers.NOTHING),
                     ("once", triggers.NOT_CONSTANT)):
        assert not out[key].ok and words[why] in out[key].content, key
    assert not out["console_unread"].ok and words[triggers.UNREAD] in str(out["console_unread"].errors)
    assert not out["console_once"].ok and words[triggers.NOT_CONSTANT] in str(out["console_once"].errors)
    assert out["before"] == 1  # rien n'a été écrit par les refus
    assert f"passe sur : la base du projet n° {produit} qui avance, le réveil par API « deploy »" in out["read"]
    assert out["console_read"].ok
    assert out["edit"].ok and not out["edit_same"].ok and "Rien n'a changé" in out["edit_same"].message
    assert not out["edit_once"].ok and words[triggers.NOT_CONSTANT] in str(out["edit_once"].errors)
    assert [(o.on, o.only_on_event) for o in p.objectives[1:]] == [
        ((f"project:{produit}:commit", "wake:deploy"), True), (("app:veille",), True)]


def test_a_plan_and_a_project_born_in_conversation_carry_what_fires_their_constants():
    p = replace(_project(2), objectives=(Objective(id=1, text_ref="o1"),))
    steps = PlanArgs(aim="a", deliverables="d", approach="x", steps=[
        {"text": "Relire le site", "kind": "constant", "on": ["project:1:commit"]},
        {"text": "Une page", "done_when": "elle est en ligne", "on": ["app:veille"]}]).steps
    unread, once = _plan_problems(p, steps)
    assert "étape 1" in unread and family("projects.triggers.refused")[triggers.UNREAD] in unread
    assert "étape 2" in once and family("projects.triggers.refused")[triggers.NOT_CONSTANT] in once
    # un projet que ce plan demande à lire : accepté, il ne déclenchera qu'une fois le lien posé
    assert _plan_problems(p, steps[:1], {1}) == []
    assert _plan_problems(replace(p, reads=(1,)), steps[:1]) == []
    # à la création, le projet n'existe pas encore : un déclencheur n'y nomme qu'un projet donné à lire en même temps
    args = CreateArgs(title="Le site", reads=[1, "le produit"], constants=[
        "Un bilan", ConstantArg(text="Relire", cadence_hours=24, on=["Project:1:Commit", "app:veille"],
                                only_on_event=True)])
    assert _constants(args.constants, {1}) == [
        "Un bilan", ("Relire", 24 * HOUR, ("project:1:commit", "app:veille"), True, False)]
    with pytest.raises(triggers.BadTrigger) as unread:
        _constants(args.constants)
    assert unread.value.why == triggers.UNREAD
