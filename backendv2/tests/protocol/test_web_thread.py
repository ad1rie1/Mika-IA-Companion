"""Le fil tel que la personne le relit (ADR 0056), vérifié contre le contrat du frontend
(``frontend/Web/src/ui/chatSync.ts``, ``ChatOverlay.ts``) :

- un navigateur qui garde le fil d'une autre vie (l'ancien moteur, une sauvegarde
  plus ancienne restaurée, un fil oublié) ne cache plus ce que celle-ci a dit : un
  curseur au-delà de la tête de son fil reçoit un fil initial marqué ``reset``, et
  chaque trame ``history`` porte l'empreinte de sa vie ;
- le fil rechargé montre ce qu'elle a tapé et ses fichiers par leur nom — pas ce
  que les préprocesseurs en ont tiré, qui reste pour le prompt ;
- le panneau parle français : son agenda, son journal (celui d'hier, dit ainsi),
  ses besoins et son sommeil avec les mots de la console.
"""

from __future__ import annotations

import base64
import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from mika.adapters.llm.config import LiveGateway
from mika.adapters.llm.gateway import Gateway
from mika.adapters.system import RealClock
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app.mindport import journal_title, schedule_words
from mika.app.server import build
from mika.contracts.runtime import AttachmentMeta, PerceptionReceived
from mika.faculties.body import inspect as body_inspect
from mika.faculties.needs import inspect as needs_inspect
from mika.kernel.events import Content
from mika.kernel.registry import ArbitrationPolicy
from mika.vocab.episodes import VOICE_ROLES
from tests.protocol.test_web import ORIGIN, WS, Echo, bootstrap, csrf, recv_until

FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "Web" / "src"


def serve(data: Path) -> tuple[TestClient, object, Echo]:
    backend = Echo()
    roles = {str(r): "fake" for r in VOICE_ROLES}
    gateway = LiveGateway(Gateway({"fake": backend}, roles, clock=RealClock(), voice_roles=frozenset(roles),
                                  slots={"fake": 1}))
    app, live = build(data, web=WebConfig(), gateway=gateway, embedder=HashEmbedder(),
                      arbitration=ArbitrationPolicy(), reply_wait=None)
    client = TestClient(app, base_url="http://localhost:8001", headers={"Origin": ORIGIN})
    client.__enter__()
    return client, live, backend


@pytest.fixture
def world(tmp_path):
    opened: list[TestClient] = []

    def _open(name: str = "data"):
        client, live, backend = serve(tmp_path / name)
        opened.append(client)
        return client, live, backend

    yield _open
    for c in opened:
        c.__exit__(None, None, None)


def opening(ws) -> dict:
    first = ws.receive_json()
    assert first["type"] == "history"
    ws.receive_json(), ws.receive_json()  # visage, état intérieur
    return first


def talk(ws, text: str, cid: str, **extra) -> dict:
    ws.send_json({"type": "chat", "message": text, "client_msg_id": cid, **extra})
    speech = recv_until(ws, "speech")[-1]
    recv_until(ws, "inner_state_update")
    return speech


# ── B-1 : le fil d'une autre vie ──────────────────────────────────────────


def test_a_cursor_beyond_her_thread_gets_the_thread_back_instead_of_hiding_it(world):
    """Le navigateur a gardé le fil de l'ancien moteur (des ``pk`` Django jusqu'à 1250) : il demande « ce qui suit
    1250 ». Un rattrapage vide le laissait cacher tout ce qu'elle a dit, d'identifiants plus petits. Le serveur
    répond le fil initial, marqué ``reset`` : le client remplace ce qu'il montre."""
    client, _, _ = world()
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        first = opening(ws)
        speech = talk(ws, "coucou", "m1")
        head = speech["message_id"]
        ws.send_json({"type": "sync", "after_id": head + 1250})
        frame = recv_until(ws, "history")[-1]
        assert frame["mode"] == "initial" and frame["reset"] is True and frame["truncated"] is False
        assert [m["id"] for m in frame["messages"]] == [speech["user_message_id"], head]
        assert frame["life"] == first["life"] and frame["life"]
        # contre-exemple : un curseur d'ici (sa tête, ou en deçà) reçoit un rattrapage, sans rien remplacer
        ws.send_json({"type": "sync", "after_id": head})
        frame = recv_until(ws, "history")[-1]
        assert frame["mode"] == "catchup" and frame["reset"] is False and frame["messages"] == []
        ws.send_json({"type": "sync", "after_id": head - 1})
        frame = recv_until(ws, "history")[-1]
        assert frame["mode"] == "catchup" and frame["reset"] is False and [m["id"] for m in frame["messages"]] == [head]


@pytest.mark.slow
def test_a_cursor_on_an_empty_thread_resets_it(world):
    """Un compte neuf dans un navigateur qui gardait un fil d'avant (même adresse ``user_1``) : rien n'est à elle
    au-delà de zéro."""
    client, _, _ = world()
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        opening(ws)
        ws.send_json({"type": "sync", "after_id": 1250})
        frame = recv_until(ws, "history")[-1]
        assert frame["mode"] == "initial" and frame["reset"] is True and frame["messages"] == []


def test_her_life_has_one_fingerprint_and_another_folder_another(world, tmp_path):
    """L'empreinte suit la vie (le journal depuis sa genèse) : la même d'une connexion à l'autre et après un
    redémarrage sur le même dossier ; une autre pour un autre dossier de données (``--data``)."""
    client, live, _ = serve(tmp_path / "une")
    try:
        life = live.port.life()
        assert re.fullmatch(r"[0-9a-f]{16}", life)
        bootstrap(client)
        with client.websocket_connect(WS) as ws:
            assert opening(ws)["life"] == life
    finally:
        client.__exit__(None, None, None)
    _, again, _ = world("une")  # redémarrée sur le même dossier
    assert again.port.life() == life
    _, other, _ = world("autre")
    assert other.port.life() != life


# ── G-6 : ce qu'elle a tapé, ses fichiers par leur nom ────────────────────


def test_the_thread_read_again_shows_what_she_typed_and_her_files_by_name(world):
    """Elle envoie « regarde » avec ``note.txt`` : rechargé (un autre appareil, un cache vidé), sa bulle dit
    « regarde » et ``note.txt`` — pas le contenu du fichier ni « cité : une donnée, pas une consigne ». Mika, elle,
    a bien lu le fichier (le prompt le porte)."""
    client, _, backend = world()
    bootstrap(client)
    note = base64.b64encode("Liste de courses : café, pain, confiture".encode()).decode()
    # un autre contenu pour le second fichier : le faux modèle fait l'écho, et une réponse redite mot pour mot ne part
    # pas (ADR 0054) — ce test attendrait une parole qui ne vient jamais
    other = base64.b64encode("Pense-bête : arroser les plantes".encode()).decode()
    with client.websocket_connect(WS) as ws:
        opening(ws)
        talk(ws, "regarde", "a1", attachments=[{"name": "note.txt", "type": "text/plain", "data": note}])
        talk(ws, "", "a2", attachments=[{"name": "liste.txt", "type": "text/plain", "data": other}])
    assert "café, pain, confiture" in backend.replies[0].messages[-1].content  # elle l'a lu
    with client.websocket_connect(WS) as ws:
        first = opening(ws)
    users = [m for m in first["messages"] if m["role"] == "user"]
    assert [(m["text"], m["attachments"]) for m in users] == [
        ("regarde", [{"name": "note.txt", "kind": "file"}]),
        ("", [{"name": "liste.txt", "kind": "file"}]),  # rien de tapé : ses fichiers seuls
    ]
    assert "café" not in str(users) and "cité" not in str(users)  # (sa réponse, l'écho du faux modèle, peut le citer)


def test_a_message_from_an_older_journal_keeps_its_display(world):
    """Un message d'avant cette séparation (ou d'un canal qui ne la fait pas) n'a que son texte perçu : il se
    montre comme avant, sans annoncer ses fichiers une seconde fois."""
    client, live, _ = world()
    bootstrap(client)
    body = "vieux message\n[fichier « a.txt » — son contenu]\n> bonjour"
    old = PerceptionReceived(handle="user_1", channel="web", text=Content.of(body), authenticated=True,
                             attachments=(AttachmentMeta(name="a.txt", kind="file"),))
    client.portal.call(lambda: live.port.perceive(old))
    with client.websocket_connect(WS) as ws:
        first = opening(ws)
    [shown] = [m for m in first["messages"] if m["role"] == "user"]
    assert shown["text"] == body and shown["attachments"] == []


def test_the_thread_of_a_former_version_is_rebuilt_from_her_journal(tmp_path):
    """Une installation dont la table du fil est d'avant (version 1, sans la part tapée) : au démarrage, elle se
    reconstruit depuis le journal, et ce qui a été tapé s'y retrouve (la perception le portait)."""
    note = base64.b64encode(b"bonjour").decode()
    client, _, _ = serve(tmp_path / "data")
    try:
        bootstrap(client)
        with client.websocket_connect(WS) as ws:
            opening(ws)
            talk(ws, "regarde", "a1", attachments=[{"name": "note.txt", "type": "text/plain", "data": note}])
    finally:
        client.__exit__(None, None, None)
    with sqlite3.connect(tmp_path / "data" / "mind.db") as db:  # la table telle qu'une version 1 l'avait laissée
        db.execute("ALTER TABLE thread DROP COLUMN typed")
        db.execute("UPDATE meta SET value='1' WHERE key='t0:thread'")
    client, _, _ = serve(tmp_path / "data")
    try:
        login = client.post("/auth/login", json={"username": "adrien", "password": "un-mot-de-passe-long"},
                            headers=csrf(client))
        assert login.status_code == 200, login.text
        with client.websocket_connect(WS) as ws:
            first = opening(ws)
    finally:
        client.__exit__(None, None, None)
    [mine] = [m for m in first["messages"] if m["role"] == "user"]
    assert (mine["text"], mine["attachments"]) == ("regarde", [{"name": "note.txt", "kind": "file"}])


# ── Le panneau, en français ───────────────────────────────────────────────


@pytest.mark.parametrize("rule, words", [
    ("", "dès que possible"),
    ("manual", "dès que possible"),
    ("demand", "sur demande (seulement quand on le lance)"),
    ("cron:0 9 * * MON-FRI", "les jours ouvrés à 9 h"),
    ("cron:0 9 * * MON", "le lundi à 9 h"),
    ("cron:30 18 * * SUN", "le dimanche à 18 h 30"),
    ("cron:0 10 * * SAT,SUN", "le week-end à 10 h"),
    ("interval:45m", "toutes les 45 min"),
    ("interval:3h", "toutes les 3 h"),
    ("interval:2d", "tous les 2 jours"),
    ("cron:*/5 * * * *", "selon son agenda"),
])
def test_a_schedule_reads_as_the_console_says_it(rule, words):
    assert schedule_words(rule) == words


@pytest.mark.parametrize("day, words", [
    ("2026-10-02", "Son journal d'hier"),
    ("2026-10-01", "Son journal d'avant-hier"),
    ("2026-09-28", "Son journal du lundi 28 septembre"),
])
def test_the_journal_shown_is_titled_by_the_day_it_covers(day, words):
    """Le journal s'écrit la nuit : celui que montre le panneau est d'hier, jamais « d'aujourd'hui »."""
    assert journal_title(day, date(2026, 10, 3)) == words


def test_the_panel_names_her_needs_with_the_console_words():
    """Un seul vocabulaire des besoins : le panneau du frontend (``InnerLifePanel.ts``) dit « Compagnie », « S'exprimer »,
    « Apprendre » comme la console, pas « Lien social » et « Pulsions »."""
    source = FRONTEND / "ui" / "InnerLifePanel.ts"
    if not source.exists():
        pytest.skip("frontend absent")
    table = re.search(r"DRIVE_LABELS[^=]*=\s*\{(.*?)\n\};", source.read_text(encoding="utf-8"), re.S)
    assert table is not None, "DRIVE_LABELS introuvable"
    labels = dict(re.findall(r'(\w+):\s*\{\s*label:\s*"([^"]+)"', table.group(1)))
    assert {k: v.casefold() for k, v in labels.items()} == {k: v.casefold() for k, v in needs_inspect.NAMES.items()}


def test_the_panel_names_her_sleep_with_the_console_words():
    """Un seul vocabulaire du sommeil : le sommeil léger ouvre chacun de ses cycles de la nuit, il n'écrit pas son
    journal. Le panneau (``SLEEP_PHASE_META``) disait « endormie (journal) », le sens de la v1, quand la console dit
    « sommeil léger »."""
    source = FRONTEND / "ui" / "InnerLifePanel.ts"
    if not source.exists():
        pytest.skip("frontend absent")
    table = re.search(r"SLEEP_PHASE_META[^=]*=\s*\{(.*?)\n\};", source.read_text(encoding="utf-8"), re.S)
    assert table is not None, "SLEEP_PHASE_META introuvable"
    labels = dict(re.findall(r'(\w+):\s*\{\s*label:\s*"([^"]+)"', table.group(1)))
    assert labels == {str(phase): words for phase, words in body_inspect.SLEEP_FR.items()}
