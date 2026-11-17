"""La synthèse distingue faits gardés, problèmes actuels et détails techniques."""

from __future__ import annotations

import ast
import html
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from mika.app.console import FACULTY_LABELS
from mika.app.handmade.tabs import system as system_tabs
from mika.contracts import runtime as rt
from mika.inspector.pages import system as system_pages
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.kernel.state import FrozenDict
from mika.runtime import health
from tests.protocol.test_console_workflows import page
from tests.protocol.test_web import bootstrap, world  # noqa: F401


def stop(client, kernel):
    async def halt():
        kernel.scheduler.stop()
        await kernel.scheduler.cancel_all()
    client.portal.call(halt)


def test_processes_put_current_failures_first_and_keep_the_full_error_in_details(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    stop(client, live.kernel)
    sched = live.kernel.scheduler
    broken = sched.specs[-1].name
    monkeypatch.setitem(sched.consecutive, broken, 4)
    monkeypatch.setitem(sched.last_error, broken, (live.kernel.mind.clock.now(), "RuntimeError('incident précis')"))
    body = page(client, "/inspecteur/systeme/processus")
    # la page est dessinée (ADR 0121) : ce qui échoue en tête, son erreur en clair, avant la carte de chaque faculté
    assert 'class="now-card sys-trouble"' in body
    first = body.split('class="now-card sys-trouble"')[1].split("Par faculté")[0]
    assert "4 échecs d'affilée" in first
    assert "incident précis" in first and broken in first
    assert '<details class="now-card person-fold"><summary>Historique des échecs' in body  # dessiné aussi
    older = page(client, "/inspecteur/systeme/processus?avant=1&pile=0,90")
    assert '<details class="now-card person-fold" open><summary>Historique des échecs' in older and "Plus récents" in older


def test_anomalies_have_one_clear_empty_state_and_do_not_hide_an_existing_incident(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    stop(client, live.kernel)
    body = page(client, "/inspecteur/systeme/anomalies")
    assert "Aucune anomalie enregistrée depuis le démarrage" in body
    assert "opérations normales" in body
    monkeypatch.setattr(live.kernel.mind, "anomalies", ["Erreur de réduction à examiner"])
    body = page(client, "/inspecteur/systeme/anomalies")
    assert "Aucune anomalie enregistrée depuis le démarrage" not in body
    assert "Erreur de réduction à examiner" in body and 'class="sys-an-list"' in body  # dans sa forme, ADR 0177


# ── Réparer là où la panne se voit (ADR 0234 ; audit du 2026-11-05, C8-04) ──────────────────────────────────────────


def _post(client, url: str, data: dict, **kw):
    return client.post(url, data={"csrf": client.cookies.get("csrftoken"), **data}, **kw)


def _audited(client, kernel, action: str) -> list[dict]:
    found = client.portal.call(lambda: kernel.mind.store.latest([rt.OPERATED.name], 20))
    return [d for d in (json.loads(e.data) for e in found) if d["action"] == action]


def _taint(mind, monkeypatch, marks: dict[str, int]) -> None:
    monkeypatch.setattr(mind, "_root", replace(mind.root, tainted=FrozenDict(marks)))


def test_a_tainted_slice_is_rebuilt_online_where_it_shows_and_the_gesture_is_audited(world, monkeypatch):  # noqa: F811
    """Une tranche corrompue a « Reconstruire » dans Anomalies et dans son sous-onglet de Diagnostic avancé ; sa
    confirmation dit qu'elle relit tout le journal et qu'elle ne sert qu'avec un réducteur corrigé. Le geste la
    reconstruit en ligne (``Mind.rebuild``) : la marque tombe, le message dit qu'elle est saine, l'audit est écrit.
    Sans jeton, ou sans opérateur, rien ne se fait ; une tranche saine n'a rien à reconstruire. Avant, la console
    renvoyait au terminal, serveur arrêté."""
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    stop(client, kernel)
    mind = kernel.mind
    _taint(mind, monkeypatch, {"memory": 42})
    for url, where in (("/inspecteur/systeme/anomalies", 'aria-labelledby="sys-an-tainted-title"'),
                       ("/inspecteur/systeme/etat", 'id="st-memory"')):
        body = html.unescape(page(client, url))
        mine = body[body.index(where):]
        form = mine[mine.index('<form method="post" action="/inspecteur/systeme/etat">'):]
        form = form[:form.index("</form>")]
        assert 'name="faculte" value="memory"' in form and ">Reconstruire</button>" in form
        assert "relit tout le journal" in form and "une fois son réducteur corrigé" in form
        assert 'name="csrf" value="' in form and f'name="_retour" value="{url}"' in form
    # sans jeton : refusé, la marque reste
    bad = client.post("/inspecteur/systeme/etat", data={"faculte": "memory", "_retour": "/inspecteur/systeme/etat"})
    assert "Jeton de formulaire invalide" in html.unescape(bad.text) and mind.root.tainted.get("memory") == 42
    assert not _audited(client, kernel, "console.systeme.reconstruire")
    done = _post(client, "/inspecteur/systeme/etat", {"faculte": "memory", "_retour": "/inspecteur/systeme/anomalies"})
    said = html.unescape(done.text)
    assert done.status_code == 200 and "reconstruite : la tranche est saine" in said and "événements relus" in said
    assert "memory" not in mind.root.tainted
    [audit] = _audited(client, kernel, "console.systeme.reconstruire")
    assert (audit["subject_kind"], audit["subject"], audit["outcome"], audit["by"]) == ("tranche", "memory", "done",
                                                                                        "user_1")
    gestures = html.unescape(page(client, "/inspecteur/systeme/operations"))  # sous son titre, la tranche par son nom
    assert re.search(r"Tranche reconstruite(?:</a>)? <span class=\"now-muted\">sur</span> <span[^>]*>" + FACULTY_LABELS["memory"],
                     gestures), gestures[gestures.index("sys-jr-what"):][:400]
    assert ">Reconstruire</button>" not in page(client, "/inspecteur/systeme/anomalies")  # plus rien de corrompu
    again = _post(client, "/inspecteur/systeme/etat", {"faculte": "memory"})
    assert "Rien à reconstruire" in html.unescape(again.text)
    # sans opérateur : renvoyé à la connexion, rien ne se fait
    _taint(mind, monkeypatch, {"memory": 42})
    client.cookies.delete("sessionid")
    gone = _post(client, "/inspecteur/systeme/etat", {"faculte": "memory"}, follow_redirects=False)
    assert gone.status_code == 303 and gone.headers["location"].endswith("/inspecteur/connexion")
    assert mind.root.tainted.get("memory") == 42


def test_a_rebuild_that_still_raises_says_where_and_what_to_do(world, monkeypatch):  # noqa: F811
    """Avec le même code, le rejeu lève au même événement : le message dit « encore corrompue au n° N » et quoi faire
    (corriger, redémarrer, reconstruire), les tranches qu'elle lit qui ne rejouent pas à l'identique ; l'audit dit
    « échouée ». Une tranche volatile ne se reconstruit pas : pas de bouton, et le geste est refusé."""
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    stop(client, kernel)
    mind = kernel.mind
    _taint(mind, monkeypatch, {"memory": 42})

    async def still(owners, **kw):
        mind._root = replace(mind.root, tainted=FrozenDict({"memory": 77}))
        return {"closure": ["memory", "social"], "mismatches": ["social"], "replayed": 12, "gaps": []}

    monkeypatch.setattr(mind, "rebuild", still)
    said = html.unescape(_post(client, "/inspecteur/systeme/etat", {"faculte": "memory"}).text)
    assert "encore corrompue au n° 77" in said and "corrige-le, redémarre, puis reconstruis" in said
    assert f"Une tranche qu'elle lit ne rejoue pas à l'identique : {FACULTY_LABELS['social']}" in said
    [audit] = _audited(client, kernel, "console.systeme.reconstruire")
    assert audit["outcome"] == "failed"
    volatile = next(n for n, f in kernel.registry.faculties.items() if f.volatile)
    _taint(mind, monkeypatch, {volatile: 5})
    body = page(client, "/inspecteur/systeme/anomalies")
    assert f'name="faculte" value="{volatile}"' not in body and "ne se rejoue pas depuis le journal" in body
    refused = html.unescape(_post(client, "/inspecteur/systeme/etat", {"faculte": volatile}).text)
    assert "Pas reconstruite" in refused and mind.root.tainted.get(volatile) == 5


def test_a_failing_process_can_be_retried_now_never_a_held_one(world, monkeypatch):  # noqa: F811
    """« Ce qui ne va pas » de Processus : un processus en échec a « Réessayer maintenant » ; le geste efface son
    recul et l'audite. Un processus retenu pour une rafale n'a pas de bouton, et le geste le refuse : la garde est là
    pour ça — même s'il est aussi en échec (sa ligne dit pourquoi ; avant, le bouton y était, et le geste effaçait la
    retenue avec le recul). Sans jeton, rien ne se fait. Avant, un processus en échec attendait son recul, jusqu'à une
    heure."""
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    stop(client, kernel)
    sched, now = kernel.scheduler, kernel.mind.clock.now()
    broken, held, stormed = sched.specs[-1].name, sched.specs[-2].name, sched.specs[-3].name
    monkeypatch.setitem(sched.consecutive, broken, 4)
    monkeypatch.setitem(sched.last_error, broken, (now, "RuntimeError('incident précis')"))
    monkeypatch.setitem(sched.not_before, broken, now + 3600 * 1_000_000)
    for name in (held, stormed):  # retenus pour une rafale (``_storming`` : la retenue à part, et dans le recul)
        monkeypatch.setitem(sched.storms, name, 1)
        monkeypatch.setitem(sched.held_until, name, now + 600 * 1_000_000)
        monkeypatch.setitem(sched.not_before, name, now + 600 * 1_000_000)
    # en échec *et* retenu : une rafale après un échec, ou une échéance qui lève pendant la retenue
    monkeypatch.setitem(sched.consecutive, stormed, 2)
    body = page(client, "/inspecteur/systeme/processus")
    trouble = body.split('class="now-card sys-trouble"')[1].split("Par faculté")[0]
    assert trouble.count(">Réessayer maintenant</button>") == 1
    assert f'name="processus" value="{broken}"' in trouble and f'name="processus" value="{held}"' not in trouble
    assert f'name="processus" value="{stormed}"' not in trouble
    assert trouble.count("Retenu pour une rafale : il ne se réessaie pas") == 1  # sur celui en échec, qui le dit
    assert 'action="/inspecteur/systeme/processus"' in trouble
    bad = client.post("/inspecteur/systeme/processus", data={"processus": broken})
    assert "Jeton de formulaire invalide" in html.unescape(bad.text) and broken in sched.not_before
    refused = html.unescape(_post(client, "/inspecteur/systeme/processus", {"processus": held}).text)
    assert "Pas relancé" in refused and sched.not_before[held] > now
    refused = html.unescape(_post(client, "/inspecteur/systeme/processus", {"processus": stormed}).text)
    assert "retenu pour une rafale — la retenue ne se force pas" in refused
    assert sched.not_before[stormed] == now + 600 * 1_000_000  # rien touché : la retenue tient
    done = html.unescape(_post(client, "/inspecteur/systeme/processus", {"processus": broken}).text)
    assert "relancé : son recul est effacé" in done and broken not in sched.not_before
    [audit] = _audited(client, kernel, "console.systeme.reessayer")
    assert (audit["subject_kind"], audit["subject"], audit["outcome"]) == ("processus", broken, "done")


def test_health_prioritizes_failed_checks_keeps_details_and_links_without_actions(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    stop(client, live.kernel)
    report = health.Health("ready", (
        health.Check("journal", "ok", "Journal sain"),
        health.Check("outbox", "degraded", "Envoi non livré", ("Erreur de livraison <script>alert(1)</script>",)),
        health.Check("loops", "ko", "Une boucle arrêtée"),
    ))
    monkeypatch.setattr(health, "report", lambda _: report)
    before = live.kernel.mind.head
    body = page(client, "/inspecteur/systeme/sante")
    assert "Une panne demande ton attention" in body and "Relevé à" in body
    assert body.index("Une boucle arrêtée") < body.index("Envoi non livré") < body.index("Journal sain")
    # dessinée (ADR 0121) : une tuile par contrôle, celui qui va bien après les autres ; puis, à état égal, les deux
    # tuiles de la console qui ne sont pas des contrôles (les sauvegardes, aucune notée ici : à faire ; les anomalies)
    assert body.count('<li class="sys-check tone-') == 5 and body.count('<li class="sys-check tone-ok">') == 2
    assert body.index("Envoi non livré") < body.index("aucune sauvegarde notée") < body.index("Journal sain")
    assert 'href="/inspecteur/systeme/sorties"' in body
    # les boucles du noyau : aucune page ne les montre, leur tuile ne mène pas à Processus (qui dirait « tout passe »)
    loops = tile(body, "Boucles de fonctionnement")
    assert "systeme/processus" not in loops and "Ouvrir le diagnostic" not in loops
    assert "<summary>Le détail</summary>" in body and "Erreur de livraison" in body
    assert "<script>alert(1)</script>" not in client.get("/inspecteur/systeme/sante").text
    # ses projections, dessinées : une jauge (combien sont à jour), une ligne par projection
    assert "Sonde publique" in body and "Ses projections" in body and 'class="sys-gauge' in body
    assert body.count('class="sys-proj-row') == len(live.kernel.registry.projectors)
    assert live.kernel.mind.head == before


def tile(body: str, name: str) -> str:
    """La tuile de la santé qui porte ce nom (son ``<li>``)."""
    found = [x for x in body.split('<li class="sys-check ')[1:] if f"<h3>{name}</h3>" in x]
    assert len(found) == 1, name
    return found[0].split("</li>")[0]


def test_health_shows_backups_and_anomalies_as_tiles_never_in_the_public_probe(world, monkeypatch):  # noqa: F811
    """Santé générale repère aussi ce que l'accueil signale : une sauvegarde à faire et les anomalies depuis le
    démarrage (celles de ses évaluations et réductions, et de l'arbitre), en tuiles de la même forme, comptées au
    bilan. Ce ne sont pas des contrôles : ``/health`` ne les publie pas. Avant : « 10 sans problème » pendant que
    Stockage disait « aucune sauvegarde notée » (audit du 2026-11-05, C8-02)."""
    client, live, _ = world
    bootstrap(client)
    stop(client, live.kernel)
    checks = tuple(health.Check(name, health.OK, f"{name} va bien") for name in
                   ("journal", "slices", "loops", "projections", "processes", "outbox", "llm", "lanes", "config",
                    "ports"))
    monkeypatch.setattr(health, "report", lambda _: health.Health("ready", checks))
    body = page(client, "/inspecteur/systeme/sante")
    saves = tile(body, "Sauvegardes")
    assert saves.startswith("tone-warn") and "À faire" in saves and "aucune sauvegarde notée" in saves
    assert 'href="/inspecteur/systeme/stockage#sys-store-saves"' in saves  # leur carte sur la page
    calm = tile(body, "Anomalies depuis le démarrage")
    assert calm.startswith("tone-ok") and 'href="/inspecteur/systeme/anomalies"' in calm
    # un point à examiner en reste un : le bilan le compte, et son titre ne dit plus « tout au vert »
    assert "1 point demande ton attention" in body and "Tous les contrôles sont au vert" not in body
    assert '<span class="now-num">11</span> sans problème' in body and '<span class="now-num">1</span> à examiner' in body
    monkeypatch.setattr(live.kernel.mind, "anomalies", ["réduction en échec", "évaluation en échec"])
    monkeypatch.setattr(live.kernel.arbiter, "anomalies", ["raison non déclarée"])
    body = page(client, "/inspecteur/systeme/sante")
    loud = tile(body, "Anomalies depuis le démarrage")
    assert loud.startswith("tone-warn") and "À examiner" in loud
    assert "2 évaluations ou réductions échouées ; 1 anomalie de l’arbitre" in loud
    assert "2 points demandent ton attention" in body and '<span class="now-num">2</span> à examiner' in body
    # la console en MCP les voit (la vue) ; la sonde publique, jamais
    table = page(client, "/inspecteur/systeme/sante?vue_pg1=table")
    assert 'class="sys-checks"' not in table and "Sauvegardes" in table and "1 anomalie de l’arbitre" in table
    public = client.get("/health").json()
    assert set(public["checks"]) == set(c.name for c in checks) and public["status"] == "ok"


def test_the_health_page_reads_its_view_never_the_report_nor_the_registry():
    """La page dessinée de la santé lit les blocs de sa vue (``health_page``) : ses tuiles, ses projections, sa
    quarantaine, ses vues lentes. Elle ne rappelle ni le rapport de santé ni le registre, la file des projections ou
    les mesures de la console (avant : le rapport se calculait deux fois par page, C8-05)."""
    tree = ast.parse(Path(system_tabs.__file__).read_text(encoding="utf-8"))
    drawn = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in
             ("health", "projections", "_tile", "_probe")]
    assert {"health", "projections"} <= {fn.name for fn in drawn}
    touched = sorted({node.attr for fn in drawn for node in ast.walk(fn) if isinstance(node, ast.Attribute)
                      and node.attr in ("report", "registry", "projectors", "projections", "lag", "quarantined",
                                        "slow", "inspection")})
    assert touched == []


@pytest.mark.parametrize("phase", ["ready", "starting"])
def test_health_distinguishes_all_clear_from_checks_not_available(world, monkeypatch, phase):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    checks = (health.Check("journal", "ok", "Journal sain"),) if phase == "ready" else ()
    monkeypatch.setattr(health, "report", lambda _: health.Health(phase, checks))
    # une sauvegarde récente : sans elle, sa tuile serait un point à examiner
    monkeypatch.setattr(system_pages, "backup_state", lambda ui: ("ok", "il y a 2 h"))
    body = page(client, "/inspecteur/systeme/sante")
    if phase == "ready":
        # un contrôle et les deux tuiles de la console, qui n'en sont pas : trois points vérifiés (avant : « les 3
        # contrôles », et « les 12 contrôles de santé » dans le panneau du repli et de la console en MCP)
        assert "Tous les contrôles sont au vert" in body and "Aucun problème sur les 3 points vérifiés." in body
        table = page(client, "/inspecteur/systeme/sante?vue_pg1=table")
        assert 'class="sys-checks"' not in table and "Aucun problème sur les 3 points vérifiés." in table
        assert "contrôles de santé." not in table
        assert '<li class="sys-check tone-ok">' in body and "Journal sain" in body  # sa tuile (ADR 0121)
        assert "il y a 2 h" in tile(body, "Sauvegardes")
    else:
        assert "Démarrage en cours" in body and "Les contrôles complets seront disponibles" in body
        assert "Tous les contrôles sont au vert" not in body and 'class="sys-health-counts"' not in body


def test_episode_summary_reads_cause_and_latest_speeches_without_losing_full_history(world):  # noqa: F811
    client, live, backend = world
    bootstrap(client)
    kernel = live.kernel
    stop(client, kernel)
    async def seed():
        question = await kernel.mind.append([rt.PERCEPTION_RECEIVED.draft(handle="user_1", channel="web",
            text=Content.of("Message à relire <script>alert(1)</script>"))], emitter="runtime", origin=Origin.EXTERNAL,
            correlation="diagnostic-question")
        drafts = [rt.EPISODE_STARTED.draft(kind="REPLY", target="user_1", reply_to=question.seqs[0])]
        voice = VoiceProvenance(call_id="diagnostic", persona_hash="fictive", role="reply", model="fake")
        drafts += [rt.UTTERANCE.draft(kind="REPLY", target="user_1", voice=voice,
                                     text=Content.of(f"Parole de diagnostic {n}")) for n in range(5)]
        drafts += [rt.EPISODE_ENDED.draft(kind="REPLY", outcome="done", detail="Réponse de diagnostic terminée")]
        await kernel.mind.append(drafts, emitter="runtime", origin=Origin.GENESIS, correlation="diagnostic-episode")
    client.portal.call(seed)
    before, calls = kernel.mind.head, len(backend.calls)
    url = "/inspecteur/episode/diagnostic-episode"
    body = page(client, url)
    assert "Réponse de diagnostic terminée" in body and "Message déclencheur" in body and "Message à relire" in body
    assert "Parole de diagnostic 0" not in body and "Parole de diagnostic 1" not in body
    assert all(f"Parole de diagnostic {n}" in body for n in range(2, 5))
    assert "3 dernières paroles sur 5" in body and "Paroles produites" in body
    assert '<script>alert(1)</script>' not in client.get(url).text
    assert re.search(r'onglet=resume" aria-current="page"', body)
    speeches = page(client, url + "?onglet=dit")
    assert all(f"Parole de diagnostic {n}" in speeches for n in range(5))
    assert 'class="episode-speeches"' in speeches  # la page d'un épisode est dessinée (ADR 0121)
    journal = page(client, url + "?onglet=deroule")
    assert 'class="now-feed episode-feed"' in journal and "7 au total" in journal
    table = page(client, url + "?onglet=deroule&vue_pg1=table")
    assert 'person-list' not in table and 'class="hm-table"' in table and "7 au total" in table
    assert kernel.mind.head == before and len(backend.calls) == calls


@pytest.mark.parametrize("ended", [False, True])
def test_incomplete_episode_summary_does_not_invent_duration_or_delivery(world, ended):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    stop(client, kernel)
    draft = rt.EPISODE_ENDED.draft(kind="TASK", outcome="failed", detail="Service indisponible") if ended else \
        rt.EPISODE_STARTED.draft(kind="TASK")
    client.portal.call(lambda: kernel.mind.append([draft], emitter="runtime", origin=Origin.GENESIS,
                                                 correlation="incomplete-episode"))
    body = page(client, "/inspecteur/episode/incomplete-episode")
    assert "fin ou début absent" in body and "Aucune parole n’est enregistrée" in body
    if ended:
        assert "Service indisponible" in body and "son déclencheur ne peut pas être retrouvé" in body
    else:
        assert "Aucune fin n’est enregistrée" in body and "Vérifier l’activité actuelle" in body
