"""La synthèse distingue faits gardés, problèmes actuels et détails techniques."""

from __future__ import annotations

import re

import pytest

from mika.contracts import runtime as rt
from mika.kernel.events import Content, Origin, VoiceProvenance
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
    assert "Erreur de réduction à examiner" in body and 'class="now-card person-list' in body  # dessinée, ADR 0121


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
    # dessinée (ADR 0121) : une tuile par contrôle, celui qui va bien après les autres
    assert body.count('<li class="sys-check tone-') == 3 and '<li class="sys-check tone-ok">' in body
    assert 'href="/inspecteur/systeme/sorties"' in body and 'href="/inspecteur/systeme/processus"' in body
    assert "<summary>Le détail</summary>" in body and "Erreur de livraison" in body
    assert "<script>alert(1)</script>" not in client.get("/inspecteur/systeme/sante").text
    # ses projections, dessinées : une jauge (combien sont à jour), une ligne par projection
    assert "Sonde publique" in body and "Ses projections" in body and 'class="sys-gauge' in body
    assert body.count('class="sys-proj-row') == len(live.kernel.registry.projectors)
    assert live.kernel.mind.head == before


@pytest.mark.parametrize("phase", ["ready", "starting"])
def test_health_distinguishes_all_clear_from_checks_not_available(world, monkeypatch, phase):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    checks = (health.Check("journal", "ok", "Journal sain"),) if phase == "ready" else ()
    monkeypatch.setattr(health, "report", lambda _: health.Health(phase, checks))
    body = page(client, "/inspecteur/systeme/sante")
    if phase == "ready":
        assert "Tous les contrôles sont au vert" in body
        assert '<li class="sys-check tone-ok">' in body and "Journal sain" in body  # sa tuile (ADR 0121)
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
