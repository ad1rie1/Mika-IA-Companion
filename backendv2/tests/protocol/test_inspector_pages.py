"""L'inspecteur complet (M8) : chaque page s'ouvre, chaque vue de faculté se
rend, chaque formulaire exige son jeton, et les réglages font ce qu'ils disent
— persona et tempérament journalisés, surcharges validées, comptes sans
verrouillage, approbations, apps forgées configurées."""

from __future__ import annotations

import html
import json
import re
import shutil

import pytest

from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.inspector.ui import MENU
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
    for _group, items in MENU:
        for path, label in items:
            r = client.get("/inspecteur" + path)
            assert r.status_code == 200, (path, r.status_code)
            assert label in html_of(r)
    views = client.portal.call(inspection.views, live.kernel)
    assert len(views) >= 20  # chaque faculté déclare les siennes
    for v in views:
        r = client.get(f"/inspecteur/facultes/{v.owner}/{v.name}")
        assert r.status_code == 200 and "Cette vue a échoué" not in html_of(r), (v.owner, v.name)
    listed = html_of(client.get("/inspecteur/facultes"))
    assert all(v.title in listed for v in views)
    assert client.get("/inspecteur/facultes/nobody/nothing").status_code == 404


def test_why_did_she_say_that(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    converse(client)
    ended = client.portal.call(lambda: live.kernel.mind.store.latest([rt.EPISODE_ENDED.name], 1))[0]
    page = html_of(client.get(f"/inspecteur/episode/{ended.correlation}"))
    assert "Ce qu'elle a dit" in page and "en réponse à" in page and "perception.received" in page
    assert "ce que le prompt lui montrait" in page
    cause = re.search(r'/inspecteur/evenement/(\d+)">perception\.received', page)
    event = html_of(client.get(f"/inspecteur/evenement/{cause.group(1)}"))
    assert "réduit par" in event and "transcript" in event and "a déclenché" in event
    assert client.get("/inspecteur/evenement/999999").status_code == 404
    # un filtre qui ressemble à du SQL ne casse rien
    assert client.get("/inspecteur/chronologie?type=%25'%20OR%201=1--&correlation=x").status_code == 200


def test_health_is_public_but_says_only_names_and_states(world):  # noqa: F811
    client, live, _ = world
    r = client.get("/health")
    body = r.json()
    assert r.status_code == 200 and body["ready"] is True and body["status"] in ("ok", "degraded")
    assert set(body["checks"]) >= {"journal", "slices", "loops", "projections", "processes", "outbox", "llm"}
    assert set(body["checks"].values()) <= {"ok", "degraded", "ko"}
    assert r.headers["cache-control"] == "no-store"
    bootstrap(client)
    detail = html_of(client.get("/inspecteur/sante"))
    assert "Processus" in detail and "Sonde publique" in detail


def test_every_form_needs_its_token(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    head = client.portal.call(lambda: live.kernel.mind.head)
    for path in ("/modeles", "/persona", "/parametres", "/canaux", "/sens", "/forge", "/comptes", "/approbations"):
        r = client.post("/inspecteur" + path, data={"action": "save", "persona": "name: Pirate"})
        assert r.status_code == 200 and "Jeton de formulaire invalide" in html_of(r), path
    assert client.portal.call(lambda: live.kernel.mind.head) == head  # rien n'a été écrit


def test_persona_is_edited_validated_journaled_and_can_return_to_the_file(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    client.get("/inspecteur/persona")
    kernel = live.kernel

    def revisions() -> list:
        return client.portal.call(lambda: kernel.mind.store.latest([self_c.PERSONA_REVISED.name], 50))

    before = len(revisions())
    refused = post(client, "/inspecteur/persona", action="save", persona="name: Mika\ncouleur: bleue\n")
    assert "Persona refusée" in html_of(refused) and len(revisions()) == before  # champ inconnu : rien ne change
    broken = post(client, "/inspecteur/persona", action="save", persona="name: [Mika\n")
    assert "YAML illisible" in html_of(broken)
    text = client.portal.call(lambda: live.persona()).model_dump(mode="json")
    text["name"] = "Mikaela"
    saved = post(client, "/inspecteur/persona", action="save", persona=json.dumps(text))  # le JSON est du YAML
    assert "Persona enregistrée" in html_of(saved)
    assert client.portal.call(lambda: kernel.mind.frame().get(self_c.PERSONA)).name == "Mikaela"
    assert len(revisions()) == before + 1
    back = post(client, "/inspecteur/persona", action="file")
    assert "Retour au fichier" in html_of(back)
    assert client.portal.call(lambda: kernel.mind.frame().get(self_c.PERSONA)).name == "Mika"


def test_temperament_and_overrides_rederive_the_parameters(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    client.get("/inspecteur/parametres")
    kernel = live.kernel

    def needs():
        return client.portal.call(lambda: kernel.mind.frame().env.params_of("needs", kernel.mind.root))

    sliders = {k: "0.5" for k in ("reactivity", "resilience", "contagion", "optimism", "curiosity",
                                  "perseverance", "chronotype")}
    before = needs().tau_social_h
    r = post(client, "/inspecteur/parametres", action="temperament", sociability="0.9", background="curious",
             **sliders)
    assert "Tempérament enregistré" in html_of(r)
    assert needs().tau_social_h < before  # plus sociable : le besoin de compagnie revient plus vite
    doc = client.portal.call(lambda: kernel.mind.frame().get(self_c.PERSONA))
    assert doc.temperament.sociability == 0.9 and doc.temperament.background.value == "curious"
    unknown = post(client, "/inspecteur/parametres", action="overrides", faculty="needs", values="pas_un_reglage: 3")
    assert "Surcharge refusée" in html_of(unknown)
    ok = post(client, "/inspecteur/parametres", action="overrides", faculty="needs", values="lonely_from: 0.65")
    assert "Surcharges enregistrées" in html_of(ok) and needs().lonely_from == 0.65
    assert client.portal.call(live.settings.overrides) == {"needs": {"lonely_from": 0.65}}


def test_accounts_are_managed_without_ever_locking_out(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    client.get("/inspecteur/comptes")
    weak = post(client, "/inspecteur/comptes", action="create", username="bea", password="12345678")
    assert "numérique" in html_of(weak)
    created = post(client, "/inspecteur/comptes", action="create", username="bea", password="longue-phrase-secrete")
    assert "Compte créé" in html_of(created) and "user_2" in html_of(created)
    alone = post(client, "/inspecteur/comptes", action="update", account="1", active="on")  # sans « opérateur »
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
        listing = html_of(client.get("/inspecteur/rapports"))
        assert "rapide.md" in listing
        assert "S01" in html_of(client.get("/inspecteur/rapports?fichier=rapide.md"))
        escaped = html_of(client.get("/inspecteur/rapports?fichier=../secret.txt"))
        assert "à ne pas lire" not in escaped and "Fichier inconnu" in escaped
        # sans modèle : la santé le dit, elle répond quand même
        health = client.get("/health").json()
        assert health["status"] == "degraded" and health["checks"]["llm"] == "degraded"


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")
def test_an_operator_configures_a_forged_app(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    forge = live.kernel.ports["forge"]
    manifest = "title: Seuil\nconfig:\n  seuil: 3\n  actif: false\n"
    code = "def view(api):\n    return [api.config('seuil'), api.config('actif')]\n"
    client.portal.call(forge.write, "seuil", manifest, code)
    page = html_of(client.get("/inspecteur/forge"))
    assert "Seuil" in page and "seuil" in page
    bad = post(client, "/inspecteur/forge", action="config", app="seuil", cfg_seuil="beaucoup")
    assert "attend une valeur du type int" in html_of(bad)
    ok = post(client, "/inspecteur/forge", action="config", app="seuil", cfg_seuil="7", cfg_actif="on")
    assert "Réglages de l'app enregistrés" in html_of(ok)
    result = client.portal.call(forge.call, "seuil", "view")
    assert result.ok and result.value == [7, True]  # l'app lit le réglage de l'opérateur
    unknown = post(client, "/inspecteur/forge", action="config", app="inconnue", cfg_seuil="1")
    assert "App inconnue" in html_of(unknown)


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
