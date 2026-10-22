"""Parcours d'opérateur hors courrier, avec des états utiles et des filtres réels."""

from __future__ import annotations

import html
import re
import shutil
from pathlib import Path

from mika.contracts import attention, goals, memory
from mika.contracts import runtime as rt
from mika.inspector.pages import decisions
from mika.inspector.ui import STATIC
from mika.kernel.events import Content, Origin
from tests.fixtures.console_html import ConsoleHTML
from tests.fixtures.mika import connect
from tests.protocol.test_inspector_pages import converse
from tests.protocol.test_web import bootstrap, world  # noqa: F401


def page(client, url, out: Path | None = None):
    response = client.get(url)
    assert response.status_code == 200, (url, response.status_code)
    assert "Cette vue a échoué" not in response.text and "Bloc inconnu" not in response.text, url
    ConsoleHTML(response.text).check()
    if out is not None:
        out.mkdir(exist_ok=True)
        name = re.sub(r"[^a-zA-Z0-9_-]+", "_", url.removeprefix("/inspecteur/")).strip("_") or "accueil"
        body = response.text.replace('/inspecteur/static/', 'static/')
        body = body.replace('method="post"', 'method="dialog"').replace(' data-vitals="/inspecteur/_vitals"', '')
        (out / (name + '.html')).write_text(body)
    return html.unescape(response.text)


def append(client, kernel, drafts, owner="runtime"):
    return client.portal.call(lambda: kernel.mind.append(drafts, emitter=owner, correlation="console-review",
                                                        origin=Origin.GENESIS))


def headers(body):
    return re.findall(r'<th\b[^>]*>([^<]*)</th>', body)


def test_connected_apps_are_paged_and_each_revocation_keeps_its_own_token(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    account = client.portal.call(live.accounts.all)[0]
    async def seed():
        return [await live.accounts.create_token(account.id, f"Écran {n:02}") for n in range(14)]
    tokens = client.portal.call(seed)
    base = f"/inspecteur/reglages/comptes?compte={account.id}"
    first = page(client, base)
    assert "14 au total" in first and first.count('name="action" value="revoke_token"') == 12
    next_url = html.unescape(re.search(r'<a href="([^"]+)" rel="next">', first).group(1))
    assert f"compte={account.id}" in next_url and "page_apps=2" in next_url
    last = page(client, "/inspecteur/reglages/comptes" + next_url)
    assert last.count('name="action" value="revoke_token"') == 2
    def ids(body):
        return set(re.findall(r'name="token" value="(\d+)"', body))
    assert not ids(first) & ids(last)
    assert ids(first) | ids(last) == {str(t.id) for t, _ in tokens}
    assert all(secret not in first + last for _, secret in tokens)
    assert all(not t.revoked for t in client.portal.call(live.accounts.tokens))


def test_reading_pages_show_content_keep_details_and_search_names(world, tmp_path):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    client.portal.call(connect, kernel, "alice", "Alice")
    client.portal.call(connect, kernel, "bob", "Bob")
    append(client, kernel, [rt.PERCEPTION_RECEIVED.draft(handle=who, channel="web", addressed=False,
        text=Content.of(f"{who} : un message en deux paragraphes.\n\nSuite du message {n}."))
        for n in range(61) for who in ("alice", "bob")])
    append(client, kernel, [memory.REMEMBERED.draft(text=Content.of(f"Souvenir {n} : Alice prépare son exposition."),
        about=("alice",), sensitivity=1, importance=0.6) for n in range(61)], "memory")
    append(client, kernel, [attention.THOUGHT_BORN.draft(text=Content.of("L'exposition d'Alice approche."),
        emotion="curious", intensity=0.5, origin="exchange", about=("alice",))], "attention")
    opened = append(client, kernel, [goals.GOAL_OPENED.draft(kind=goals.PROJECT, authority=goals.USER,
        title=Content.of("Préparer les visuels de l'exposition"), owner="alice", bundles=("goals",), max_steps=8,
        source="console-review")], "goals")
    out = tmp_path / "review"
    out.mkdir()
    shutil.copytree(STATIC, out / "static")
    messages = page(client, "/inspecteur/fil/messages?handle=Alice", out)
    assert "alice : un message" in messages and "bob : un message" not in messages
    # la conversation est dessinée (ADR 0121) : le message entier, son numéro, et la même liste en tableau à un clic
    assert 'class="now-card person-chat"' in messages and "Suite du message" in messages and "n° " in messages
    assert 'href="?handle=Alice&amp;vue_pg1=table"' in messages or 'href="?handle=Alice&vue_pg1=table"' in messages
    table = page(client, "/inspecteur/fil/messages?handle=Alice&vue_pg1=table", out)
    assert "épisode" not in headers(table) and "texte" in headers(table)
    assert "alice : un message" in table and "bob : un message" not in table
    assert "Informations complémentaires" in table
    next_url = html.unescape(re.search(r'<a href="([^"]+)" rel="next">', messages).group(1))
    tail = page(client, "/inspecteur/fil/messages" + next_url, out)
    assert "Plus récents" in tail and "alice : un message" in tail
    memories = page(client, "/inspecteur/memoire/souvenirs?person=Alice&page=2", out)
    assert "Souvenir 0 : Alice" in memories and "importance" not in headers(memories)
    assert "Informations complémentaires" in memories and "importance" in memories
    none = page(client, "/inspecteur/memoire/souvenirs?q=aucun-resultat")
    assert "aucun résultat pour ces filtres" in none and "Souvenir 0" not in none
    for url in ("personnes/personnes", "identites/annuaire", "pensees/pensees", "buts/projets",
                "buts/vivants", "buts/clos", "vie/humeur", "vie/postures", "vie/needs", "vie/rythme", "vie/soi",
                "pensees/remarque", "pensees/attentes", "pensees/nuits", "memoire/croyances", "memoire/promesses",
                "memoire/consolidation", "personnes/liens", "personnes/presents", "identites/revendications",
                "identites/politique", "fil/questions", "decisions/maintenant", "decisions/en_cours",
                "decisions/initiatives", "decisions/selections", "decisions/episodes", "decisions/echeances",
                "sens/flux", "sens/camera", "sens/appareils", "apps", "systeme/sante", "systeme/processus",
                "systeme/anomalies", "systeme/sorties", "systeme/passerelle", "systeme/appels", "systeme/stockage",
                "systeme/chronologie", "systeme/operations", "systeme/etat", "systeme/contributions",
                "systeme/vues", "systeme/simulations"):
        page(client, "/inspecteur/" + url, out)
    for spec in live.kernel.registry.inspectors:
        if spec.subject == "person":
            page(client, "/inspecteur/fiche/person/alice?onglet=" + spec.name, out)
        elif spec.subject == "goal":
            page(client, f"/inspecteur/fiche/goal/{opened.seqs[0]}?onglet=" + spec.name, out)
    fiche = page(client, "/inspecteur/fiche/person/alice?onglet=memoire&page_souvenir=2&avant=20&q=exposition")
    tabs = re.search(r'<nav class="tabs".*?</nav>', fiche, re.S).group()
    assert "page_souvenir" not in tabs and "avant=" not in tabs and "q=exposition" in tabs


def test_sparse_episode_filters_can_continue_after_the_scan_budget(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    monkeypatch.setattr(decisions, "EPISODE_SCAN", 2)
    monkeypatch.setattr(decisions, "EPISODE_SCAN_BATCHES", 1)
    append(client, live.kernel, [rt.EPISODE_ENDED.draft(kind="REPLY", outcome=state, target="alice", detail=detail)
        for state, detail in (("failed", "Échec ancien à retrouver"), ("ok", "Réussi 1"), ("ok", "Réussi 2"))])
    body = page(client, "/inspecteur/decisions/episodes?sorte=REPLY&issue=failed")
    assert "La recherche continue" in body
    next_url = html.unescape(re.search(r'<a href="([^"]+)" rel="next">', body).group(1))
    tail = page(client, "/inspecteur/decisions/episodes" + next_url)
    assert "Échec ancien à retrouver" in tail and "Réussi 1" not in tail
    assert "Plus récents" in tail


def test_empty_outbox_filter_does_not_show_successful_deliveries(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    converse(client)
    all_ = page(client, "/inspecteur/systeme/sorties")
    assert "parti" in all_
    failed = page(client, "/inspecteur/systeme/sorties?etat=failed")
    assert "Aucun effet." in failed and "une parole à livrer" not in failed
    assert "État inconnu" in page(client, "/inspecteur/systeme/sorties?etat=inconnu")


def test_last_thought_and_night_history_pages_keep_the_return_path(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    for view in ("pensees", "remarque", "attentes", "nuits"):
        body = page(client, f"/inspecteur/pensees/{view}?avant=1&pile=0,90")
        assert "Plus récents" in body, view


def test_pending_approvals_are_paged_and_each_card_keeps_its_proposal(world, tmp_path):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    append(client, live.kernel, [rt.EFFECT_PROPOSED.draft(capability="review.fictive", owner="review",
        args_json="{}", summary=Content.of(f"Proposition de revue {n:02}"), context="test") for n in range(23)])
    body = page(client, "/inspecteur/approbations/en_attente", tmp_path / "review")
    assert body.count('class="approve-form"') == 20
    tail = page(client, "/inspecteur/approbations/en_attente?page=2", tmp_path / "review")
    assert tail.count('class="approve-form"') == 3 and "Précédente" in tail
    def ids(s):
        return set(re.findall(r'name="proposal" value="(\d+)"', s))
    assert len(ids(body) | ids(tail)) == 23 and not ids(body) & ids(tail)


def test_large_episode_keeps_its_outcome_and_every_event_accessible(world, tmp_path):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    drafts = [rt.EPISODE_STARTED.draft(kind="REPLY", target="alice", reason="Un long échange")]
    drafts += [rt.PERCEPTION_RECEIVED.draft(handle="alice", channel="web", addressed=False,
               text=Content.of(f"Étape de l'épisode {i:03}")) for i in range(550)]
    drafts += [rt.EPISODE_ENDED.draft(kind="REPLY", outcome="done", detail="FIN ÉPISODE LONG")]
    append(client, live.kernel, drafts)
    url = '/inspecteur/episode/console-review'
    summary = page(client, url, tmp_path / 'review')
    assert 'FIN ÉPISODE LONG' in summary and 'Résultat de l’épisode' in summary
    first = page(client, url + '?onglet=deroule', tmp_path / 'review')
    assert '552 au total' in first and 'en cours ou interrompu' not in first
    assert 'FIN ÉPISODE LONG' not in first
    tail = page(client, url + '?page=23', tmp_path / 'review')
    assert 'FIN ÉPISODE LONG' in tail and 'Précédente' in tail
    assert 'runtime.episode.ended' in tail or rt.EPISODE_ENDED.name in tail


def test_activity_keeps_open_work_pending_question_and_recent_failure_separate(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    async def seed():
        kernel.scheduler.stop()
        await kernel.scheduler.cancel_all()
        question = await kernel.mind.append([rt.PERCEPTION_RECEIVED.draft(handle='user_1', channel='web',
            text=Content.of('Une question encore en attente'))], emitter='runtime', origin=Origin.EXTERNAL,
            correlation='activity-pending')
        await kernel.mind.append([rt.EPISODE_STARTED.draft(kind='REPLY', target='user_1', reply_to=question.seqs[0])],
            emitter='runtime', origin=Origin.GENESIS, correlation='activity-open')
        await kernel.mind.append([rt.EPISODE_STARTED.draft(kind='TASK'),
            rt.EPISODE_ENDED.draft(kind='TASK', outcome='failed', detail='Service momentanément indisponible')],
            emitter='runtime', origin=Origin.GENESIS, correlation='activity-failed')
    client.portal.call(seed)
    before = client.portal.call(lambda: kernel.mind.head)
    body = page(client, '/inspecteur/decisions/en_cours')
    # dessinée (ADR 0121) : ce qu'elle fait, ce qui attend, ce qu'elle vient de faire
    assert 'Relevé ' in body and 'Actualiser' in body and 'Sorties à vérifier' in body
    assert 'En ce moment' in body and 'Ce qui attend' in body and "Ce qu'elle vient de faire" in body
    assert 'Elle répond à' in body and 'Suivre cet épisode' in body
    assert '/inspecteur/episode/activity-open' in body and '/inspecteur/episode/activity-failed' in body
    assert 'Toutes les questions sans réponse' in body and 'Service momentanément indisponible' in body
    assert client.portal.call(lambda: kernel.mind.head) == before
    history = page(client, '/inspecteur/decisions/episodes?issue=failed')
    assert 'person-list' in history and 'Service momentanément indisponible' in history  # dessinée (ADR 0121)
    table = page(client, '/inspecteur/decisions/episodes?issue=failed&vue_pg1=table')
    assert 'person-list' not in table and 'Service momentanément indisponible' in table
