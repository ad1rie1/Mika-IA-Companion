"""Piloter un but depuis sa fiche, par intentions (ses projets : ``test_projects_console.py``).

- une exploration qu'elle a entreprise se **pilote** (priorité, avancer, plan, pause,
  consigne) mais ne se **réécrit** pas ;
- une exploration bloquée se **rouvre** : elle refait un pas, sans qu'elle en ressente rien ;
- « **avancer maintenant** » passe devant l'espacement, jamais devant le plafond horaire ;
- le **plan de travail** se tient à deux : l'opérateur pose et coche des tâches,
  elle les coche et en ajoute par ses outils ;
- la **priorité** déplace la preuve d'un pas ; un budget à 0 veut dire « la valeur par
  défaut » partout.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from mika.contracts import goals as goals_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.faculties.goals import work
from mika.faculties.goals.faculty import GOAL_REOPENED, TASK_ADDED, TASK_CHANGED, TASK_REMOVED, params
from mika.inspector.pages.routes import per_row
from mika.kernel.clock import MINUTE, US
from mika.kernel.events import Content, Origin
from mika.kernel.inspect import ActionSlot
from mika.runtime.operations import offered, perform
from mika.sim.llm.persona import _section
from tests.unit.test_goals_console import events, explore, field, flat, form, live, nested, steps_of, tab


def row_form(fixed: dict[str, str], **values: str) -> dict[str, list[str]]:
    """Ce que poste un formulaire posé sur une ligne : ses valeurs cachées en ``_fixes`` (la tâche, la
    demande), comme la page les rend, et ses champs visibles en ``_champs``."""
    return {**form(**values), "_fixes": list(fixed), **{k: [v] for k, v in fixed.items()}}


def _prompt(llm, title: str = "") -> str:
    """La section « CE À QUOI TU TRAVAILLES » de la dernière séance envoyée au modèle."""
    for req in reversed(llm.calls):
        work_ = _section(req, "CE À QUOI TU TRAVAILLES")
        if work_ and title in work_:
            return work_
    return ""


async def _until(kernel, predicate, minutes: int = 180) -> None:
    for _ in range(minutes):
        if predicate():
            return
        await asyncio.sleep(MINUTE / US)
    await kernel.lanes.join()


# ── Piloter sans réécrire ─────────────────────────────────────────────────


def test_an_exploration_is_driven_but_never_rewritten(tmp_path):
    async def scenario(kernel, llm):
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        gid = str(await explore(kernel))
        actions = {k for k in kernel.registry.actions if k.startswith("goals.")}
        offered_ = {k: offered(kernel, kernel.registry.actions[f"goals.{k}"], gid)
                    for k in ("priorite", "avancer", "tache_ajouter", "consigne", "pause", "reprogrammer")}
        return actions, offered_, await tab(kernel, "politique", gid)

    actions, offered_, policy = live(tmp_path, scenario)
    assert not {"goals.modifier", "goals.confier", "goals.deposer", "goals.approuver"} & actions  # aux projets
    assert offered_ == {"priorite": True, "avancer": True, "tache_ajouter": True, "consigne": True, "pause": True,
                        "reprogrammer": False}
    assert "ne se réécrit pas" in flat(policy)
    assert any(isinstance(b, ActionSlot) and b.action == "goals.priorite" for b in policy)


def test_zero_steps_means_the_default_everywhere(tmp_path):
    async def scenario(kernel, llm):
        zero = await kernel.mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.EXPLORATION, authority=goals_c.SELF, title=Content.of("Explorer : sans budget", level=0),
            bundles=("goals",), max_steps=0, source="test", sensitivity=0, desire=1.0)],
            emitter="goals", correlation="t", origin=Origin.GENESIS)
        zid = zero.seqs[-1]
        await _until(kernel, lambda: steps_of(kernel, zid), minutes=60)
        frame = kernel.mind.frame()
        default = params(frame.env.params_of("goals", frame.root)).exploration_steps  # celui de son tempérament
        return steps_of(kernel, zid), await tab(kernel, "resume", str(zid)), default

    zero_steps, resume, default = live(tmp_path, scenario, mode="plan")
    assert zero_steps  # il avance
    assert field(resume, "séances faites").endswith(f"sur {default}")  # la fiche dit la même chose


# ── Rouvrir ───────────────────────────────────────────────────────────────


def test_a_blocked_exploration_reopens_takes_a_step_and_she_feels_nothing_about_it(tmp_path):
    async def scenario(kernel, llm):
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        llm.step_mode = "stuck"
        gid = str(await explore(kernel))
        await _until(kernel, lambda: events(kernel, goals_c.GOAL_CLOSED))
        spec = kernel.registry.actions["goals.rouvrir"]
        out = {"closed": kernel.mind.frame().get(goals_c.STATUS(int(gid))), "offered": offered(kernel, spec, gid)}
        before = (kernel.mind.frame().get(self_c.ESTEEM), kernel.mind.head)
        out["reopen"] = await perform(kernel, "goals.rouvrir", form(extra="3", instruction="Commence par les années 80."),
                                      by="user_1", subject=gid, nonce="r1")
        g = kernel.mind.frame().state("goals").goals[int(gid)]
        out["after"] = (kernel.mind.frame().get(goals_c.STATUS(int(gid))), g.silent, g.steps, g.max_steps,
                        g.instructions != ())
        out["esteem"] = (before[0], kernel.mind.frame().get(self_c.ESTEEM))
        out["written"] = [e.type for e in kernel.mind.store.read() if e.seq > before[1]]
        llm.step_mode = "honest"
        steps_before = len(steps_of(kernel, int(gid)))
        await _until(kernel, lambda: len(steps_of(kernel, int(gid))) > steps_before)
        out["stepped"] = len(steps_of(kernel, int(gid))) > steps_before
        out["prompt"] = _prompt(llm)
        done = await kernel.mind.append([goals_c.GOAL_CLOSED.draft(
            goal=int(gid), status=goals_c.ACHIEVED, kind=goals_c.EXPLORATION, authority=goals_c.SELF,
            title=Content.of("x"))], emitter="goals", correlation="t", origin=Origin.GENESIS)
        out["achieved_offered"] = offered(kernel, spec, gid) if done.seqs else None
        return out

    out = live(tmp_path, scenario)
    assert out["closed"] == goals_c.STUCK and out["offered"]
    assert out["reopen"].ok, out["reopen"]
    status_, silent, steps, most, instructed = out["after"]
    assert status_ == goals_c.ACTIVE and silent == 0 and most >= steps + 3 and instructed
    assert out["esteem"][0] == out["esteem"][1]  # rouvrir n'émeut pas : ni fierté, ni frustration
    assert {GOAL_REOPENED.name, "goals.amended", rt.OPERATED.name} <= set(out["written"])
    assert not any(t.startswith("affect.") for t in out["written"])
    assert out["stepped"] and "Commence par les années 80." in out["prompt"]
    assert out["achieved_offered"] is False  # un abouti ne se rouvre pas


# ── Avancer maintenant ────────────────────────────────────────────────────


def test_advance_now_skips_the_spacing_but_never_the_hourly_cap(tmp_path):
    async def scenario(kernel, llm):
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        gid = await explore(kernel)
        await _until(kernel, lambda: steps_of(kernel, gid), minutes=30)
        await kernel.lanes.join()
        first = len(steps_of(kernel, gid))
        spec = kernel.registry.actions["goals.avancer"]
        frame = kernel.mind.frame()
        s = frame.state("goals")
        g = s.goals[gid]
        why = work.why_not_now(g, s, frame)
        capped = work.why_not_now(g, replace(s, steps_at=(frame.now,) * params(None).steps_per_hour), frame)
        got = await perform(kernel, "goals.avancer", form(), by="user_1", subject=str(gid), nonce="a1")
        again = offered(kernel, spec, str(gid))
        await _until(kernel, lambda: len(steps_of(kernel, gid)) > first, minutes=10)
        return first, why, capped, got, again, len(steps_of(kernel, gid))

    first, why, capped, got, again, after = live(tmp_path, scenario, mode="plan")
    assert first == 1 and why.startswith("pas encore")  # l'espacement la fixe plus tard, et la fiche le dit
    assert capped.startswith("plafond atteint")
    assert got.ok and not again  # demandé une fois : plus offert jusqu'au pas
    assert after > first  # une séance, sans attendre l'espacement


# ── Le plan de travail ────────────────────────────────────────────────────


def test_the_plan_is_kept_by_the_operator_and_by_her(tmp_path):
    async def scenario(kernel, llm):
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        llm.step_mode = "plan"
        gid = str(await explore(kernel))
        await perform(kernel, "goals.pause", form(), by="user_1", subject=gid, nonce="p")  # le plan d'abord
        for i, text in enumerate(("Lister les consoles", "Trouver les meilleurs jeux", "Tester un émulateur")):
            got = await perform(kernel, "goals.tache_ajouter", form(text=text), by="user_1", subject=gid,
                                nonce=f"t{i}")
            assert got.ok, got
        out = {"status": await perform(kernel, "goals.tache_statut", row_form({"task": "3", "status": "blocked"}),
                                       by="user_1", subject=gid, nonce="s1"),
               "same": await perform(kernel, "goals.tache_statut", row_form({"task": "3", "status": "blocked"}),
                                     by="user_1", subject=gid, nonce="s2"),
               "edit": await perform(kernel, "goals.tache_modifier", row_form({"task": "3"}, text="Tester à la main",
                                                                  note="il manque une manette"),
                                     by="user_1", subject=gid, nonce="e1"),
               "gone": await perform(kernel, "goals.tache_statut", row_form({"task": "9", "status": "done"}),
                                     by="user_1", subject=gid, nonce="s3")}
        await perform(kernel, "goals.reprendre", form(), by="user_1", subject=gid, nonce="r")
        await _until(kernel, lambda: events(kernel, goals_c.STEP_REPORTED))
        out["prompt"] = _prompt(llm)
        [view] = [v for v in kernel.mind.frame().get(goals_c.LIVE) if v.id == int(gid)]
        out["view"] = (view.tasks_total, view.tasks_done, view.tasks_blocked)
        out["removed"] = await perform(kernel, "goals.tache_retirer", row_form({"task": "2"}), by="user_1", subject=gid,
                                       nonce="x1")
        out["resume"] = await tab(kernel, "resume", gid)
        out["by"] = [(e.data.task, e.data.author) for e in events(kernel, TASK_ADDED, TASK_CHANGED, TASK_REMOVED)]
        specs = kernel.registry.actions
        out["per_row"] = {k: per_row(specs[f"goals.{k}"]) for k in ("tache_statut", "avancer", "consigne")}
        return out

    out = live(tmp_path, scenario)
    assert out["status"].ok and not out["same"].ok and out["edit"].ok and not out["gone"].ok
    # elle lit le plan (demandé d'abord), en coche une et en ajoute une
    assert "Ton plan de travail" in out["prompt"] and "(demandée) Lister les consoles" in out["prompt"]
    assert "il manque une manette" in out["prompt"]
    assert out["view"] == (4, 1, 1)
    assert ("1", "self") in [(str(t), a) for t, a in out["by"]] and (4, "self") in out["by"]
    assert out["removed"].ok
    plan = next(b for b in nested(out["resume"]) if getattr(b, "title", "").startswith("Plan de travail"))
    assert plan.title == "Plan de travail (1 / 3 faites)"
    row = next(r for r in plan.rows if r.cells[0] == 3)
    slots = [b for b in nested(row.detail) if isinstance(b, ActionSlot)]
    assert {dict(b.initial).get("status") for b in slots if b.action == "goals.tache_statut"} == {
        "todo", "doing", "done"}  # tous sauf le sien (bloquée)
    assert any(b.action == "goals.tache_ajouter" for b in nested(out["resume"]) if isinstance(b, ActionSlot))
    # une action par ligne ne se propose pas en tête de page ; les autres, si
    assert out["per_row"] == {"tache_statut": True, "avancer": False, "consigne": False}


# ── La priorité ───────────────────────────────────────────────────────────


def test_a_higher_priority_weighs_more_among_goals_that_can_step(tmp_path):
    async def scenario(kernel, llm):
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        a, b = await explore(kernel, "Explorer : A"), await explore(kernel, "Explorer : B")
        got = await perform(kernel, "goals.priorite", form(priority="high"), by="user_1", subject=str(b), nonce="h")
        same = await perform(kernel, "goals.priorite", form(priority="high"), by="user_1", subject=str(b), nonce="h2")
        frame = kernel.mind.frame()
        evidence = {c.target: c.evidence for c in work._work(frame.state("goals"), frame)}
        return got, same, evidence[f"goal:{a}"], evidence[f"goal:{b}"]

    got, same, low, high = live(tmp_path, scenario)
    assert got.ok and not same.ok
    assert high == min(12.0, low + params(None).priority_step)


def test_editing_a_task_never_writes_the_forgotten_mark_and_an_emptied_note_is_erased(tmp_path):
    """« Modifier la tâche » part du vrai texte : renvoyer la mention « (oublié) » ne la réécrit pas comme du texte,
    et vider la note l'efface (CON-19)."""
    async def scenario(kernel, llm):
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        gid = str(await explore(kernel))
        await perform(kernel, "goals.pause", form(), by="user_1", subject=gid, nonce="p")
        await perform(kernel, "goals.tache_ajouter", form(text="Lister les consoles"), by="user_1", subject=gid,
                      nonce="t1")
        await perform(kernel, "goals.tache_modifier", row_form({"task": "1"}, text="Lister les consoles",
                                                               note="il en manque deux"),
                      by="user_1", subject=gid, nonce="e1")
        out = {"forgotten": await perform(kernel, "goals.tache_modifier",
                                          row_form({"task": "1"}, text="(oublié)", note="il en manque deux"),
                                          by="user_1", subject=gid, nonce="e2")}
        out["cleared"] = await perform(kernel, "goals.tache_modifier", row_form({"task": "1"},
                                                                                text="Lister les consoles", note=""),
                                       by="user_1", subject=gid, nonce="e3")
        g = kernel.mind.frame().state("goals").goals[int(gid)]
        texts = kernel.mind.store.content([g.tasks[0].text_ref])
        out["task"] = (texts.get(g.tasks[0].text_ref), g.tasks[0].note_ref)
        out["resume"] = await tab(kernel, "resume", gid)
        return out

    out = live(tmp_path, scenario)
    assert not out["forgotten"].ok  # « (oublié) » n'est pas un texte : rien n'a changé
    assert out["cleared"].ok and out["task"] == ("Lister les consoles", "")  # la note vidée est effacée
    plan = next(b for b in nested(out["resume"]) if getattr(b, "title", "").startswith("Plan de travail"))
    [row] = plan.rows
    [slot] = [b for b in nested(row.detail) if isinstance(b, ActionSlot) and b.action == "goals.tache_modifier"]
    assert dict(slot.initial) == {"task": "1", "text": "Lister les consoles", "note": ""}  # le vrai texte
