"""Piloter un projet depuis sa fiche, par intentions.

- le cadre d'un projet confié se **modifie** (pré-rempli de ce qu'il est) et le pas
  suivant lit le nouveau cadre ; une exploration qu'elle a entreprise se pilote
  mais ne se réécrit pas ; un budget de pas déjà dépassé est refusé ;
- un projet bloqué se **rouvre** : il refait un pas, sans qu'elle en ressente rien ;
- « **avancer maintenant** » passe devant l'agenda, jamais devant le plafond horaire ;
- le **plan de travail** se tient à deux : l'opérateur pose et coche des tâches,
  elle les coche et en ajoute par ses outils ; le panneau compte les vraies tâches ;
- **décider** depuis la fiche est la même décision que la page Approbations, une fois ;
- **déposer** un fichier le met dans son atelier, enregistré à part, et le pas suivant
  le sait ; un chemin qui sort de l'atelier est refusé ;
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
from mika.faculties.goals.faculty import (
    GOAL_DEPOSITED,
    GOAL_REFRAMED,
    GOAL_REOPENED,
    TASK_ADDED,
    TASK_CHANGED,
    TASK_REMOVED,
    params,
)
from mika.inspector.pages.routes import per_row
from mika.kernel.clock import MINUTE, US
from mika.kernel.events import Content, Origin
from mika.kernel.forms import Upload
from mika.kernel.inspect import ActionSlot, Download
from mika.runtime.inspection import Inspection
from mika.runtime.operations import initial_values, offered, perform
from mika.sim.llm.persona import _section
from tests.unit.test_goals_console import (
    Atelier,
    events,
    explore,
    field,
    flat,
    form,
    live,
    nested,
    steps_of,
    tab,
)


def row_form(fixed: dict[str, str], **values: str) -> dict[str, list[str]]:
    """Ce que poste un formulaire posé sur une ligne : ses valeurs cachées en ``_fixes`` (la tâche, la
    demande), comme la page les rend, et ses champs visibles en ``_champs``."""
    return {**form(**values), "_fixes": list(fixed), **{k: [v] for k, v in fixed.items()}}


async def _confide(kernel, **values: str) -> str:
    fields = {"title": "Un script de bonjour", "details": "Écrire bonjour.py.", "schedule": "manual", **values}
    got = await perform(kernel, "goals.confier", form(("approval",), **fields), by="user_1",
                        nonce=f"c-{fields['title']}")
    assert got.ok, got
    return str(events(kernel, goals_c.GOAL_OPENED)[-1].seq)


def _prompt(llm, title: str = "") -> str:
    """La section « CE À QUOI TU TRAVAILLES » du dernier pas envoyé au modèle (pour ce titre, s'il est donné)."""
    for req in reversed(llm.calls):
        work = _section(req, "CE À QUOI TU TRAVAILLES")
        if work and title in work:
            return work
    return ""


async def _until(kernel, predicate, minutes: int = 180) -> None:
    for _ in range(minutes):
        if predicate():
            return
        await asyncio.sleep(MINUTE / US)
    await kernel.lanes.join()


# ── Modifier le cadre ─────────────────────────────────────────────────────


def test_a_confided_project_is_reframed_and_the_next_step_reads_the_new_frame(tmp_path):
    async def scenario(kernel, llm):
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        await connect(kernel, "user_2", "Bea")
        llm.step_mode = "plan"
        gid = await _confide(kernel, title="Ranger les notes", details="Les classer par date.", schedule="interval:2h",
                             due="2026-10-02 18:00")
        spec = kernel.registry.actions["goals.modifier"]
        out = {"initial": initial_values(kernel, spec, gid)}
        out["unchanged"] = await perform(kernel, "goals.modifier", form(("approval",), **{
            k: str(v) for k, v in out["initial"].items() if k != "approval"}), by="user_1", subject=gid, nonce="m0")
        out["bad"] = await perform(kernel, "goals.modifier", form(
            ("approval",), title=" ", owner="personne_x", schedule="tous les jours", due="hier"),
            by="user_1", subject=gid, nonce="m1")
        out["ok"] = await perform(kernel, "goals.modifier", form(
            title="Ranger les notes de Bea", details="Les classer par sujet, pas par date.", owner="user_2",
            due="", schedule="manual", max_steps="20", priority="high", approval="on"),
            by="user_1", subject=gid, nonce="m2")
        g = kernel.mind.frame().state("goals").goals[int(gid)]
        out["goal"] = (g.owner, g.due, g.schedule, g.max_steps, g.priority, g.about)
        await _until(kernel, lambda: events(kernel, goals_c.STEP_REPORTED))
        out["prompt"] = _prompt(llm)
        out["reframed"] = events(kernel, GOAL_REFRAMED)
        explo = str(await explore(kernel))
        out["explo"] = {k: offered(kernel, kernel.registry.actions[f"goals.{k}"], explo)
                        for k in ("modifier", "priorite", "avancer", "tache_ajouter")}
        out["carnet"] = await tab(kernel, "carnet", gid)
        out["policy"] = await tab(kernel, "politique", explo)
        return out

    out = live(tmp_path, scenario)
    initial = out["initial"]
    # pré-rempli de ce qu'il est : ses textes, son échéance comme la relit un champ date et heure, sa liberté
    assert initial["title"] == "Ranger les notes" and initial["details"] == "Les classer par date."
    assert initial["due"] == "2026-10-02T18:00" and initial["schedule"] == "interval:2h"
    assert initial["approval"] is False and initial["owner"] == "user_1" and initial["priority"] == "normal"
    assert not out["unchanged"].ok and "Rien n'a changé" in out["unchanged"].message
    assert not out["bad"].ok and set(out["bad"].errors) == {"title", "owner", "schedule", "due"}
    assert out["ok"].ok, out["ok"]
    assert out["goal"] == ("user_2", None, "manual", 20, "high", ("user_2",))
    [reframed] = out["reframed"]
    assert reframed.origin is Origin.EXTERNAL and reframed.data.by == "user_1" and reframed.data.clear_due
    # le pas suivant lit le nouveau cadre, et sa priorité
    assert "Les classer par sujet, pas par date." in out["prompt"] and "Ranger les notes de Bea" in out["prompt"]
    assert "Les classer par date." not in out["prompt"] and "Priorité : haute." in out["prompt"]
    # une exploration se pilote (priorité, avancer, plan) mais ne se réécrit pas
    assert out["explo"] == {"modifier": False, "priorite": True, "avancer": True, "tache_ajouter": True}
    assert "ne se réécrit pas" in flat(out["policy"])
    assert any(isinstance(b, ActionSlot) and b.action == "goals.priorite" for b in out["policy"])
    # le carnet dit ce qui a changé, et qui l'a changé
    assert "cadre modifié" in flat(out["carnet"]) and "priorité : haute" in flat(out["carnet"])


def test_a_budget_already_spent_is_refused_and_zero_means_the_default_everywhere(tmp_path):
    async def scenario(kernel, llm):
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        llm.step_mode = "plan"
        gid = await _confide(kernel, max_steps="3")
        await _until(kernel, lambda: len(steps_of(kernel, int(gid))) >= 2)
        steps = kernel.mind.frame().state("goals").goals[int(gid)].steps
        spent = await perform(kernel, "goals.modifier", form(title="Un script de bonjour", details="Écrire bonjour.py.",
                                                             schedule="manual", max_steps=str(steps)),
                              by="user_1", subject=gid, nonce="b1")
        # un projet ouvert de l'extérieur avec 0 pas au plus : la valeur par défaut, pas « jamais »
        zero = await kernel.mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.PROJECT, authority=goals_c.USER, title=Content.of("Sans budget", level=1),
            bundles=("goals",), max_steps=0, schedule="manual", source="test", sensitivity=1)],
            emitter="goals", correlation="t", origin=Origin.GENESIS)
        zid = zero.seqs[-1]
        await _until(kernel, lambda: steps_of(kernel, zid), minutes=60)
        return spent, steps_of(kernel, zid), await tab(kernel, "resume", str(zid))

    spent, zero_steps, resume = live(tmp_path, scenario)
    assert not spent.ok and "déjà fait" in spent.errors["max_steps"]
    assert zero_steps  # il avance
    assert field(resume, "séances faites").endswith(f"sur {params(None).project_steps}")  # la fiche dit la même chose


# ── Rouvrir ───────────────────────────────────────────────────────────────


def test_a_blocked_project_reopens_takes_a_step_and_she_feels_nothing_about_it(tmp_path):
    async def scenario(kernel, llm):
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        llm.step_mode = "stuck"
        gid = await _confide(kernel)
        await _until(kernel, lambda: events(kernel, goals_c.GOAL_CLOSED))
        spec = kernel.registry.actions["goals.rouvrir"]
        out = {"closed": kernel.mind.frame().get(goals_c.STATUS(int(gid))), "offered": offered(kernel, spec, gid)}
        before = (kernel.mind.frame().get(self_c.ESTEEM), kernel.mind.head)
        out["reopen"] = await perform(kernel, "goals.rouvrir", form(extra="3", instruction="Commence par le test."),
                                      by="user_1", subject=gid, nonce="r1")
        g = kernel.mind.frame().state("goals").goals[int(gid)]
        out["after"] = (kernel.mind.frame().get(goals_c.STATUS(int(gid))), g.silent, g.steps, g.max_steps,
                        g.instructions != ())
        out["esteem"] = (before[0], kernel.mind.frame().get(self_c.ESTEEM))
        written = [e.type for e in kernel.mind.store.read() if e.seq > before[1]]
        out["written"] = written
        llm.step_mode = "honest"
        steps_before = len(steps_of(kernel, int(gid)))
        await _until(kernel, lambda: len(steps_of(kernel, int(gid))) > steps_before)
        out["stepped"] = len(steps_of(kernel, int(gid))) > steps_before
        out["prompt"] = _prompt(llm)
        done = await kernel.mind.append([goals_c.GOAL_CLOSED.draft(
            goal=int(gid), status=goals_c.ACHIEVED, kind=goals_c.PROJECT, authority=goals_c.USER,
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
    assert out["stepped"] and "Commence par le test." in out["prompt"]
    assert out["achieved_offered"] is False  # un abouti ne se rouvre pas


# ── Avancer maintenant ────────────────────────────────────────────────────


def test_advance_now_skips_the_schedule_but_never_the_hourly_cap(tmp_path):
    async def scenario(kernel, llm):
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        llm.step_mode = "plan"
        gid = await _confide(kernel, schedule="cron:0 9 * * MON")  # lundi 14 h : prochain créneau lundi prochain
        await asyncio.sleep(30 * MINUTE / US)
        idle = len(steps_of(kernel, int(gid)))
        spec = kernel.registry.actions["goals.avancer"]
        frame = kernel.mind.frame()
        s = frame.state("goals")
        g = s.goals[int(gid)]
        why = work.why_not_now(g, s, frame)
        capped = work.why_not_now(g, replace(s, steps_at=(frame.now,) * params(None).steps_per_hour), frame)
        got = await perform(kernel, "goals.avancer", form(), by="user_1", subject=gid, nonce="a1")
        again = offered(kernel, spec, gid)
        await _until(kernel, lambda: steps_of(kernel, int(gid)), minutes=10)
        return idle, why, capped, got, again, steps_of(kernel, int(gid))

    idle, why, capped, got, again, stepped = live(tmp_path, scenario)
    assert idle == 0 and why.startswith("pas encore")  # l'agenda le fixe à lundi prochain, et la fiche le dit
    assert capped.startswith("plafond atteint")
    assert got.ok and not again  # demandé une fois : plus offert jusqu'au pas
    assert stepped  # un pas, sans attendre lundi


# ── Le plan de travail ────────────────────────────────────────────────────


def test_the_plan_is_kept_by_the_operator_and_by_her(tmp_path):
    async def scenario(kernel, llm):
        from mika.app.mindport import KernelPort
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        llm.step_mode = "plan"
        gid = await _confide(kernel)
        await perform(kernel, "goals.pause", form(), by="user_1", subject=gid, nonce="p")  # le plan d'abord
        for i, text in enumerate(("Lire le cahier des charges", "Écrire le squelette", "Tester")):
            got = await perform(kernel, "goals.tache_ajouter", form(text=text), by="user_1", subject=gid,
                                nonce=f"t{i}")
            assert got.ok, got
        out = {"status": await perform(kernel, "goals.tache_statut", row_form({"task": "3", "status": "blocked"}),
                                       by="user_1", subject=gid, nonce="s1"),
               "same": await perform(kernel, "goals.tache_statut", row_form({"task": "3", "status": "blocked"}),
                                     by="user_1", subject=gid, nonce="s2"),
               "edit": await perform(kernel, "goals.tache_modifier", row_form({"task": "3"}, text="Tester à la main",
                                                                  note="il manque un jeu de données"),
                                     by="user_1", subject=gid, nonce="e1"),
               "gone": await perform(kernel, "goals.tache_statut", row_form({"task": "9", "status": "done"}),
                                     by="user_1", subject=gid, nonce="s3")}
        await perform(kernel, "goals.reprendre", form(), by="user_1", subject=gid, nonce="r")
        await _until(kernel, lambda: events(kernel, goals_c.STEP_REPORTED))
        out["prompt"] = _prompt(llm)
        [view] = [v for v in kernel.mind.frame().get(goals_c.LIVE) if v.id == int(gid)]
        out["view"] = (view.tasks_total, view.tasks_done, view.tasks_blocked)
        out["panel"] = KernelPort(kernel)._work(kernel.mind.frame())["projects"]
        out["removed"] = await perform(kernel, "goals.tache_retirer", row_form({"task": "2"}), by="user_1", subject=gid,
                                       nonce="x1")
        out["resume"] = await tab(kernel, "resume", gid)
        out["by"] = [(e.data.task, e.data.author) for e in events(kernel, TASK_ADDED, TASK_CHANGED, TASK_REMOVED)]
        specs = kernel.registry.actions
        out["per_row"] = {k: per_row(specs[f"goals.{k}"]) for k in ("tache_statut", "approuver", "modifier", "avancer")}
        return out

    out = live(tmp_path, scenario)
    assert out["status"].ok and not out["same"].ok and out["edit"].ok and not out["gone"].ok
    # elle lit le plan (demandé d'abord), en coche une et en ajoute une
    assert "Ton plan de travail" in out["prompt"] and "(demandée) Lire le cahier des charges" in out["prompt"]
    assert "il manque un jeu de données" in out["prompt"]
    assert out["view"] == (4, 1, 1)
    [project] = out["panel"]
    assert (project["tasks_total"], project["tasks_done"], project["tasks_blocked"]) == (4, 1, 1)
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
    assert out["per_row"] == {"tache_statut": True, "approuver": True, "modifier": False, "avancer": False}


# ── Décider depuis la fiche ───────────────────────────────────────────────


def test_deciding_from_the_fiche_is_the_approvals_decision_once(tmp_path):
    atelier = Atelier()

    async def scenario(kernel, llm):
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        gid = await _confide(kernel)
        await perform(kernel, "goals.pause", form(), by="user_1", subject=gid, nonce="p")

        async def propose(what: str) -> int:
            got = await kernel.mind.append([rt.EFFECT_PROPOSED.draft(
                capability="goals.networked", owner="goals", args_json=f'{{"goal": {gid}, "argv": ["true"]}}',
                summary=Content.of(what, level=0), approval=True, context=f"goal:{gid}")], emitter="runtime",
                correlation="t", origin=Origin.TOOL)
            return got.seqs[-1]

        yes, no = await propose("installer requests"), await propose("télécharger un jeu de données")
        resume = await tab(kernel, "resume", gid)
        out = {"resume": resume,
               "yes": await perform(kernel, "goals.approuver", row_form({"proposal": str(yes)}), by="user_1", subject=gid,
                                    nonce="y"),
               "twice": await perform(kernel, "goals.approuver", row_form({"proposal": str(yes)}), by="user_1",
                                      subject=gid, nonce="y2"),
               "no": await perform(kernel, "goals.refuser", row_form({"proposal": str(no)}, note="pas de réseau"),
                                   by="user_1", subject=gid, nonce="n"),
               "offered": offered(kernel, kernel.registry.actions["goals.approuver"], gid)}
        await kernel.lanes.join()
        out["resolved"] = [(e.data.proposal, e.data.approved, e.data.by, e.data.note)
                           for e in events(kernel, rt.EFFECT_RESOLVED)]
        out["ids"] = (yes, no)
        return out

    out = live(tmp_path, scenario, ports={"workshop": atelier})
    yes, no = out["ids"]
    assert "À décider (2)" in flat(out["resume"]) and "installer requests" in flat(out["resume"])
    assert out["yes"].ok and out["no"].ok
    assert not out["twice"].ok  # une décision ne se prend qu'une fois
    assert out["resolved"] == [(yes, True, "user_1", ""), (no, False, "user_1", "pas de réseau")]
    assert out["offered"] is False  # plus rien à décider


# ── Déposer un fichier ────────────────────────────────────────────────────


def test_a_deposited_file_lands_in_the_workshop_and_the_next_step_knows(tmp_path):
    atelier = Atelier()

    async def scenario(kernel, llm):
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        llm.step_mode = "plan"
        gid = await _confide(kernel)
        await perform(kernel, "goals.pause", form(), by="user_1", subject=gid, nonce="p")

        def upload(**values):
            data = {"_champs": ["file", "folder", "note"], "folder": [values.get("folder", "")],
                    "note": [values.get("note", "")]}
            if "file" in values:
                data["file"] = [values["file"]]
            return data

        out = {
            "none": await perform(kernel, "goals.deposer", upload(), by="user_1", subject=gid, nonce="d0"),
            "big": await perform(kernel, "goals.deposer", upload(file=Upload(name="x.bin", too_big=True)),
                                 by="user_1", subject=gid, nonce="d1"),
            "escape": await perform(kernel, "goals.deposer", upload(file=Upload(name="x.csv", data=b"a"),
                                                                     folder="../ailleurs"),
                                    by="user_1", subject=gid, nonce="d2"),
            "ok": await perform(kernel, "goals.deposer", upload(file=Upload(name="../../donnees.csv", data=b"a,b\n1,2"),
                                                                 folder="entree", note="Les mesures de mars."),
                                by="user_1", subject=gid, nonce="d3"),
        }
        await perform(kernel, "goals.reprendre", form(), by="user_1", subject=gid, nonce="r")
        await _until(kernel, lambda: events(kernel, goals_c.STEP_REPORTED))
        out["prompt"] = _prompt(llm)
        out["events"] = events(kernel, GOAL_DEPOSITED)
        out["download"] = await Inspection(kernel).download("goal", gid, "entree/donnees.csv")
        out["outside"] = await Inspection(kernel).download("goal", gid, "../mind.db")
        out["atelier"] = await tab(kernel, "atelier", gid, fichier="entree/donnees.csv")
        out["gid"] = int(gid)
        return out

    out = live(tmp_path, scenario, ports={"workshop": atelier})
    assert not out["none"].ok and "file" in out["none"].errors
    assert not out["big"].ok and "trop gros" in out["big"].errors["file"]
    assert not out["escape"].ok
    assert out["ok"].ok, out["ok"]
    # le nom perd ses dossiers : il arrive où on l'a dit, et nulle part ailleurs
    assert atelier.files[out["gid"]]["entree/donnees.csv"] == "a,b\n1,2"
    assert atelier.commits[out["gid"]][1][1] == "apport de l'opérateur : entree/donnees.csv"
    [deposited] = out["events"]
    assert deposited.data.name == "entree/donnees.csv" and deposited.data.size == 7
    assert "entree/donnees.csv" in out["prompt"] and "Les mesures de mars." in out["prompt"]
    assert isinstance(out["download"], Download) and out["download"].data == b"a,b\n1,2"
    assert out["download"].name == "donnees.csv" and not isinstance(out["outside"], Download)
    assert "a,b\n1,2" in flat(out["atelier"])  # ouvert sur la fiche


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


# ── La console : pré-remplir, aller sur ce qu'on a créé ───────────────────


def test_a_confided_project_leads_to_its_own_fiche(tmp_path):
    async def scenario(kernel, llm):
        from tests.fixtures.mika import connect

        await connect(kernel, "user_1", "Adrien", operator=True)
        got = await perform(kernel, "goals.confier", form(("approval",), title="Un projet", schedule="manual"),
                            by="user_1", nonce="c")
        return got, str(events(kernel, goals_c.GOAL_OPENED)[-1].seq)

    got, gid = live(tmp_path, scenario)
    assert got.go is not None and got.go.key == f"goal/{gid}"  # confié : on arrive sur sa fiche
