"""L'inspecteur complet (M8) : chaque page s'ouvre, chaque vue de faculté se
rend, chaque formulaire exige son jeton, et les réglages font ce qu'ils disent
— persona et tempérament journalisés, surcharges validées, comptes sans
verrouillage, approbations, apps forgées configurées."""

from __future__ import annotations

import html
import json
import re

from mika.app.console import NAVIGATION
from mika.contracts import runtime as rt
from mika.kernel.events import Content, Origin
from mika.runtime import inspection
from tests.protocol.test_web import WS, bootstrap, recv_until, world  # noqa: F401 — fixture partagée


def html_of(r) -> str:
    return html.unescape(r.text)


def token(client) -> str:
    return client.cookies.get("csrftoken")


def post(client, path: str, **data: str):
    return client.post(path, data={"csrf": token(client), **data})


def converse(client) -> None:
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "message": "raconte-moi ta journée", "client_msg_id": "p1"})
        recv_until(ws, "speech")


def test_every_page_and_every_faculty_view_opens(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    converse(client)
    views = client.portal.call(inspection.views, live.kernel)
    assert len(views) >= 20  # chaque faculté déclare les siennes
    for group in NAVIGATION:
        for d in group.items:
            base = "/inspecteur/" if d.key == "accueil" else f"/inspecteur/{d.key}"
            r = client.get(base)
            assert r.status_code == 200 and d.label in html_of(r), (d.key, r.status_code)
            slugs = [k.split(".", 1)[1] for k in d.builtin] + [v.name for v in views if v.section == d.key]
            for slug in slugs if d.layout == "tabs" else ():
                r = client.get(f"{base}/{slug}", follow_redirects=True)
                page = html_of(r)
                assert r.status_code == 200 and "a échoué" not in page, (d.key, slug, r.status_code)
    for v in views:
        r = client.get(f"/inspecteur/facultes/{v.owner}/{v.name}")
        assert r.status_code == 200 and "Cette vue a échoué" not in html_of(r), (v.owner, v.name)
    listed = html_of(client.get("/inspecteur/systeme/vues"))
    assert all(v.title in listed for v in views)
    assert client.get("/inspecteur/facultes/nobody/nothing").status_code == 404
    assert client.get("/inspecteur/nulle-part").status_code == 404


def test_why_did_she_say_that(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    converse(client)
    ended = client.portal.call(lambda: live.kernel.mind.store.latest([rt.EPISODE_ENDED.name], 1))[0]
    said = html_of(client.get(f"/inspecteur/episode/{ended.correlation}?onglet=dit"))
    assert "Ce qu'elle a dit" in said and "ce que le prompt lui montrait" in said
    decision = html_of(client.get(f"/inspecteur/episode/{ended.correlation}?onglet=decision"))
    assert "en réponse à" in decision
    cause = re.search(r'/inspecteur/evenement/(\d+)">message n°', decision)
    event = html_of(client.get(f"/inspecteur/evenement/{cause.group(1)}"))
    assert "réduit par" in event and "transcript" in event and "A déclenché" in event
    assert client.get("/inspecteur/evenement/999999").status_code == 404
    # un filtre qui ressemble à du SQL ne casse rien
    assert client.get("/inspecteur/systeme/chronologie?type=%25'%20OR%201=1--&correlation=x").status_code == 200


def test_health_is_public_but_says_only_names_and_states(world):  # noqa: F811
    client, live, _ = world
    r = client.get("/health")
    body = r.json()
    assert r.status_code == 200 and body["ready"] is True and body["status"] in ("ok", "degraded")
    assert set(body["checks"]) >= {"journal", "slices", "loops", "projections", "processes", "outbox", "llm"}
    assert set(body["checks"].values()) <= {"ok", "degraded", "ko"}
    assert r.headers["cache-control"] == "no-store"
    bootstrap(client)
    detail = html_of(client.get("/inspecteur/systeme/sante"))
    assert "Processus" in detail and "Sonde publique" in detail


def test_every_form_needs_its_token(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    head = client.portal.call(lambda: live.kernel.mind.head)
    for path in ("modeles", "personnalite", "parametres", "canaux", "sens", "comptes"):
        r = client.post(f"/inspecteur/reglages/{path}", data={"_section": "personnage", "_champs": "name",
                                                              "name": "Pirate", "action": "create"})
        assert r.status_code in (200, 403) and "Jeton de formulaire invalide" in html_of(r), path
    refused = client.post("/inspecteur/approbations", data={"proposal": "1", "decision": "approve"})
    assert "Jeton de formulaire invalide" in html_of(refused)
    assert client.portal.call(lambda: live.kernel.mind.head) == head  # rien n'a été écrit
    assert client.portal.call(live.settings.persona_yaml) is None


def test_accounts_are_managed_without_ever_locking_out(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    client.get("/inspecteur/reglages/comptes")
    weak = post(client, "/inspecteur/reglages/comptes", action="create", username="bea", password="12345678")
    assert "numérique" in html_of(weak)
    created = post(client, "/inspecteur/reglages/comptes", action="create", username="bea", password="longue-phrase-secrete")
    assert "Compte créé" in html_of(created) and "user_2" in html_of(created)
    alone = post(client, "/inspecteur/reglages/comptes", action="update", account="1", active="on")  # sans « opérateur »
    assert "dernier opérateur actif" in html_of(alone)
    accounts = client.portal.call(live.accounts.all)
    assert accounts[0].operator and not accounts[1].operator


def test_an_operator_approves_from_the_inspector(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    draft = rt.EFFECT_PROPOSED.draft(capability="email.send", owner="email",
                                     args_json=json.dumps({"to": "alice@exemple.fr", "subject": "Coucou"}),
                                     summary=Content.of("Envoyer à alice@exemple.fr : « Coucou »"),
                                     context="email")
    commit = client.portal.call(lambda: kernel.mind.append([draft], emitter="runtime", correlation="test",
                                                           origin=Origin.EXTERNAL))
    proposal = commit.seqs[-1]
    page = html_of(client.get("/inspecteur/approbations"))
    assert "alice@exemple.fr" in page and "Approuver" in page  # ce qui partira, tel quel
    r = post(client, "/inspecteur/approbations", proposal=str(proposal), decision="approve", note="ok")
    assert r.status_code == 200 and "Approuvé" in html_of(r) and "Rien n'attend ton accord" in html_of(r)
    resolved = client.portal.call(lambda: kernel.mind.store.latest([rt.EFFECT_RESOLVED.name], 5))
    assert resolved and json.loads(resolved[0].data)["by"] == "user_1"
    again = post(client, "/inspecteur/approbations", proposal=str(proposal), decision="reject")
    assert "déjà décidée" in html_of(again)


def test_reports_are_listed_and_never_escape_their_folder(tmp_path):
    from starlette.testclient import TestClient

    from mika.adapters.llm.config import LiveGateway
    from mika.adapters.vectors import HashEmbedder
    from mika.adapters.web.app import WebConfig
    from mika.app.server import build
    from tests.protocol.test_web import ORIGIN

    reports = tmp_path / "rapports"
    reports.mkdir()
    (reports / "rapide.md").write_text("# Voie rapide\nS01 ✔", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("à ne pas lire", encoding="utf-8")
    app, _ = build(tmp_path / "data", web=WebConfig(), gateway=LiveGateway(), embedder=HashEmbedder(),
                   reports=reports)
    with TestClient(app, base_url="http://localhost:8001", headers={"Origin": ORIGIN}) as client:
        bootstrap(client)
        listing = html_of(client.get("/inspecteur/systeme/simulations"))
        assert "rapide.md" in listing
        assert "S01" in html_of(client.get("/inspecteur/systeme/simulations?fichier=rapide.md"))
        escaped = html_of(client.get("/inspecteur/systeme/simulations?fichier=../secret.txt"))
        assert "à ne pas lire" not in escaped and "Fichier inconnu" in escaped
        # sans modèle : la santé le dit, elle répond quand même
        health = client.get("/health").json()
        assert health["status"] == "degraded" and health["checks"]["llm"] == "degraded"


def test_the_old_forge_settings_address_leads_to_the_apps(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    r = client.get("/inspecteur/reglages/apps", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/inspecteur/apps"
    assert client.get("/inspecteur/forge", follow_redirects=False).headers["location"] == "/inspecteur/apps"


def test_a_backup_taken_while_she_talks_is_consistent(world, tmp_path):  # noqa: F811
    import threading
    from pathlib import Path

    from mika.app import backup

    client, live, _ = world
    bootstrap(client)
    data = Path(live.kernel.mind.store.mind_path).parent
    done: list = []
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        worker = threading.Thread(target=lambda: done.append(backup.backup(data, tmp_path / "archives")))
        for i in range(4):
            ws.send_json({"type": "chat", "message": f"message {i}", "client_msg_id": f"b{i}"})
            if i == 1:
                worker.start()
            recv_until(ws, "speech")
        worker.join(timeout=120)
    [made] = done
    head = client.portal.call(lambda: live.kernel.mind.head)
    assert 0 < made.head <= head  # une copie cohérente, prise en marche
    assert backup.verify(made.archive).state == made.state
