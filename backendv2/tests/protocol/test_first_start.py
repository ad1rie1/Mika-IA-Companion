"""La première fois, et ce qu'on voit quand ça ne va pas (ADR 0057).

Un audit a branché un serveur neuf et suivi le chemin d'une personne qui l'installe : huit étapes, dont trois
pièges silencieux. Ce qui est vérifié ici, par ce qu'une personne ferait :

- déclarer un fournisseur suffit pour qu'elle parle (le premier sert « répondre » d'office) ; « configuré » veut
  dire « elle peut répondre », jamais seulement « un fournisseur existe » ;
- un fournisseur qui ne répond plus se voit sur ``/health`` et dans « À traiter », pas seulement au fil des
  derniers épisodes ;
- ``/`` mène à la console ; la console crée le premier compte, et dit à un compte du chat qu'il ne l'ouvre pas ;
- un fichier de persona invalide se dit en français (le fichier, la ligne, la cause) et elle démarre sur sa
  dernière persona gardée au journal ;
- la ligne de commande de première fois : de l'aide, des rôles qui existent, un mot de passe jamais en argument.
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from mika.adapters.llm.config import BackendSpec, LiveGateway, LLMConfig, build_gateway
from mika.adapters.llm.gateway import Gateway, UnconfiguredRole
from mika.adapters.system import RealClock
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app import cli
from mika.app import persona as persona_file
from mika.app.server import build
from mika.kernel.registry import ArbitrationPolicy
from mika.ports.llm import LLMResponse
from mika.vocab.episodes import FALLBACKS, VOICE_ROLES
from tests.fixtures.mika import PERSONA_PATH
from tests.protocol.test_web_edges import WS, Fake, bootstrap, opening, second_session, until

ORIGIN = "http://localhost:3000"
OLLAMA = BackendSpec(kind="ollama", model="gemma4:12b")


class Down(Fake):
    """Un Ollama arrêté : chaque réponse échoue à la connexion."""

    def __init__(self) -> None:
        super().__init__(fail=ConnectionError("Failed to connect to Ollama"))


def server(tmp_path: Path, backend, *, routes: dict[str, str] | None = None, persona: Path = PERSONA_PATH):
    """Le vrai serveur, sur un fournisseur fourni ; chaque appel laisse sa trace, comme en service."""
    sink: list = []
    gateway = LiveGateway(Gateway({"local": backend}, routes if routes is not None else {"reply": "local"},
                                  clock=RealClock(), voice_roles=frozenset(str(r) for r in VOICE_ROLES),
                                  fallbacks={str(k): str(v) for k, v in FALLBACKS.items()}, slots={"local": 4},
                                  on_trace=lambda tr: [f(tr) for f in sink]))
    app, live = build(tmp_path / "data", web=WebConfig(), gateway=gateway, embedder=HashEmbedder(),
                      arbitration=ArbitrationPolicy(), reply_wait=None, persona=persona)
    sink.append(live.trace)
    return app, live


def client_of(app) -> TestClient:
    return TestClient(app, base_url="http://localhost:8001", headers={"Origin": ORIGIN})


# ── B-3 : configuré veut dire « elle peut répondre » ──────────────────────


def test_the_first_provider_declared_serves_reply_without_a_second_step():
    """Un fournisseur ajouté, sans toucher à « Qui sert quoi » : elle parle. Avant, la configuration se disait
    « configurée », ``/health`` disait ``ok``, et chaque tour échouait (« aucun modèle associé au rôle reply »)."""
    cfg = LLMConfig(backends={"local": OLLAMA})
    assert cfg.routes == {"reply": "local"} and cfg.problems() == []
    live = LiveGateway(build_gateway(cfg, RealClock(), make=lambda name, spec: Fake()))
    assert live.configured and live.serving("reply") == "local"
    assert live.serving("extract") == "local"  # les autres rôles y retombent
    chosen = LLMConfig(backends={"claude": BackendSpec(kind="claude", model="claude-sonnet-5"), "local": OLLAMA},
                       routes={"reply": "local"})
    assert chosen.routes["reply"] == "local"  # un choix explicite n'est jamais changé
    gone = LLMConfig(backends={"claude": chosen.backends["claude"]}, routes={"reply": "local"})
    assert gone.routes["reply"] == "claude"  # celui qui répondait est retiré : le premier qui reste prend la main


def test_configured_means_reply_resolves_and_problems_name_what_would_break():
    """Contre-exemple de l'ancien « configuré » : une passerelle existe, mais rien ne sert « répondre »."""
    unrouted = LiveGateway(Gateway({"local": Fake()}, {"extract": "local"}, clock=RealClock()))
    assert not unrouted.configured and unrouted.serving("reply") == ""
    assert not LiveGateway().configured
    junk = LLMConfig.model_construct(backends={"local": OLLAMA}, routes={"reponse": "local"}, context_tokens=24_000)
    problems = junk.problems()
    assert any("« reponse » n'existe pas" in p for p in problems)
    assert any("aucun fournisseur ne sert « reply »" in p for p in problems)


def test_the_cli_routes_only_roles_that_exist_and_says_who_replies(tmp_path, capsys):
    data = tmp_path / "v2"
    assert cli.main(["--data", str(data), "llm", "backend", "local", "--kind", "ollama", "--model", "gemma4"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["répondre"] == "local" and shown["routes"] == {"reply": "local"}
    assert "auth" not in shown["backends"]["local"]  # la connexion d'un abonnement Claude Code, pas d'un Ollama
    with pytest.raises(SystemExit) as refused:
        cli.main(["--data", str(data), "llm", "route", "local", "reponse"])
    assert refused.value.code == 2  # un rôle qui n'existe pas : refusé, rien n'est gardé
    assert cli.main(["--data", str(data), "llm", "route", "local", "dream"]) == 0
    assert json.loads(capsys.readouterr().out)["routes"] == {"reply": "local", "dream": "local"}


# ── G-2 : un fournisseur qui ne répond plus se voit ───────────────────────


def test_a_provider_that_stopped_answering_shows_on_health_and_the_dashboard(tmp_path):
    """Un Ollama arrêté : la configuration est juste, mais chaque réponse échoue. ``/health`` restait ``ok`` et le
    tableau de bord « Rien ne demande ton attention » ; seul le fil des épisodes le montrait. Contre-exemple : tant
    que personne ne l'a appelé, rien ne dit qu'il est en panne."""
    app, live = server(tmp_path, Down())
    with client_of(app) as client:
        bootstrap(client)
        assert client.get("/health").json()["checks"]["llm"] == "ok"
        assert "Réponses en échec" not in client.get("/inspecteur/").text
        with client.websocket_connect(WS) as ws:
            opening(ws)
            ws.send_json({"type": "chat", "message": "coucou", "client_msg_id": "c1"})
            until(ws, "ack")
            assert until(ws, "ack")[-1]["status"] == "no_reply"
        health = client.get("/health").json()
        assert health["checks"]["llm"] == "degraded" and health["status"] == "degraded"
        page = client.get("/inspecteur/").text
        assert "Réponses en échec" in page
        assert "le fournisseur « local » ne répond pas (connexion impossible)" in page


# ── G-7 : une porte d'entrée ─────────────────────────────────────────────


def test_the_root_leads_to_the_console_which_creates_the_first_account(tmp_path):
    """``/`` répondait « Not Found » ; la page de connexion ne savait que « Identifiant / Mot de passe » sur une
    installation sans compte. Elle crée désormais le compte opérateur, avec les mêmes règles que
    ``/auth/bootstrap`` — et une seule fois."""
    app, _live = server(tmp_path, Fake())
    with client_of(app) as client:
        root = client.get("/", follow_redirects=False)
        assert root.status_code in (302, 303, 307) and root.headers["location"] == "/inspecteur/"
        door = client.get("/inspecteur/connexion")
        assert "Créer le compte opérateur" in door.text
        token = client.cookies.get("csrftoken")
        weak = client.post("/inspecteur/connexion", data={"csrf": token, "username": "adrien", "password": "12345678",
                                                         "password2": "12345678"})
        assert weak.status_code == 400 and "Créer le compte opérateur" in weak.text
        typo = client.post("/inspecteur/connexion", data={"csrf": token, "username": "adrien",
                                                         "password": "un-mot-de-passe-long",
                                                         "password2": "un-mot-de-passe-lonG"})
        assert typo.status_code == 400 and "pas les mêmes" in typo.text
        made = client.post("/inspecteur/connexion", data={"csrf": token, "username": "adrien",
                                                         "password": "un-mot-de-passe-long",
                                                         "password2": "un-mot-de-passe-long"},
                           follow_redirects=False)
        assert made.status_code == 303 and made.headers["location"] == "/inspecteur/"
        assert client.get("/inspecteur/").status_code == 200  # connectée, opératrice
        assert client.get("/auth/whoami").json()["operator"] is True  # le même compte ouvre le chat
        client.cookies.clear()
        again = client.get("/inspecteur/connexion")
        assert "Créer le compte opérateur" not in again.text and "Se connecter" in again.text


def test_a_chat_account_is_told_it_does_not_open_the_console(tmp_path):
    """Un compte du chat qui ouvre ``/inspecteur/`` était renvoyé à la connexion sans un mot."""
    app, live = server(tmp_path, Fake())
    with client_of(app) as client:
        bootstrap(client)
        key = second_session(client, live, "bea")
        client.cookies.clear()
        client.cookies.set("sessionid", key)
        door = client.get("/inspecteur/", follow_redirects=True)
        assert "Ce compte (bea) n'ouvre pas la console" in html.unescape(door.text)


# ── R-3 : une persona invalide ne fait pas tomber le démarrage ─────────────


BROKEN = "  - Elle ne fait pas de live : elle préfère les vidéos.\n"


def _broken_persona(tmp_path: Path) -> Path:
    text = PERSONA_PATH.read_text(encoding="utf-8")
    assert "\nfacts:\n" in text
    broken = text.replace("\nfacts:\n", "\nfacts:\n" + BROKEN, 1)
    path = tmp_path / "mika.yaml"
    path.write_text(broken, encoding="utf-8")
    return path


def test_an_invalid_persona_is_said_in_french_with_its_line_and_cause(tmp_path):
    """« Elle ne fait pas de live : … » : YAML y lit une clé. Avant : une trace pydantic en anglais
    (« facts.0 Input should be a valid string »)."""
    path = _broken_persona(tmp_path)
    line = path.read_text(encoding="utf-8").splitlines().index(BROKEN.rstrip("\n")) + 1
    with pytest.raises(persona_file.PersonaInvalid) as got:
        persona_file.read(path)
    problem = got.value.problem
    assert f"ligne {line}" in problem and "guillemets" in problem and "Input should" not in problem
    tab = tmp_path / "tab.yaml"
    tab.write_text("name: Mika\ntraits:\n\t- curieuse\n", encoding="utf-8")
    with pytest.raises(persona_file.PersonaInvalid) as got:
        persona_file.read(tab)
    assert "ligne 3" in got.value.problem and "tabulation" in got.value.problem
    problem, blocking = persona_file.startup(tmp_path / "neuf", path)  # la toute première fois : rien de gardé
    assert blocking and f"ligne {line}" in problem and "première fois" in problem
    assert persona_file.startup(tmp_path / "neuf", PERSONA_PATH) == ("", False)


def test_with_an_invalid_persona_file_she_starts_on_the_last_persona_kept_in_her_journal(tmp_path, caplog):
    """Une fois sa persona journalisée, un fichier cassé ne l'arrête plus : elle démarre dessus, et la console comme
    le journal disent pourquoi. Contre-exemple : la toute première fois, sans rien de gardé, le démarrage est
    refusé — en le disant, sans trace."""
    app, _live = server(tmp_path, Fake())
    with client_of(app):
        pass  # premier démarrage : sa persona est journalisée
    broken = _broken_persona(tmp_path)
    assert persona_file.startup(tmp_path / "data", broken) == ("", False)
    app, live = server(tmp_path, Fake(), persona=broken)
    caplog.set_level(logging.WARNING, logger="mika.server")
    with client_of(app) as client:
        assert client.get("/health").json()["ready"] is True
        assert client.portal.call(live.persona).name == "Mika"
        assert "guillemets" in live.persona_problem
        bootstrap(client)
        page = client.get("/inspecteur/reglages/identite").text
        assert "le fichier ne se lit pas" in page and "guillemets" in page
    assert any("dernière persona gardée au journal" in r.getMessage() for r in caplog.records)


# ── G-11 : la ligne de commande de première fois ───────────────────────────


def test_the_cli_tells_the_first_steps_and_never_wants_a_password_in_argument(tmp_path, capsys, monkeypatch):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    text = capsys.readouterr().out
    assert "Premiers pas" in text and "/inspecteur/" in text and "lancer Mika" in text
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return "un-mot-de-passe-long"

    monkeypatch.setattr(cli.getpass, "getpass", ask)
    assert cli.main(["--data", str(tmp_path / "v2"), "account", "adrien", "--operator"]) == 0
    assert len(asked) == 2 and json.loads(capsys.readouterr().out)["operator"] is True
    answers = iter(["un-mot-de-passe-long", "pas-le-meme-mot-de-passe"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))
    assert cli.main(["--data", str(tmp_path / "v2"), "account", "bea"]) == 1  # deux saisies différentes : rien


# ── Cosmétique de la console ──────────────────────────────────────────────


class Turns(Fake):
    """Elle répond au premier message, se tait au second."""

    def __init__(self) -> None:
        super().__init__()
        self.replies = 0

    async def complete(self, req):
        if req.role != "reply":
            return await super().complete(req)
        self.replies += 1
        return LLMResponse("d'accord [EMOTION:happy:0.6]" if self.replies == 1 else "[SILENCE]")


def test_the_console_answers_what_an_operator_asks(tmp_path):
    """La colonne « réponse » était vide pour toute question répondue (on croyait qu'elle n'avait pas répondu) ;
    un Ollama se lisait « Connexion : le login de la CLI (abonnement) » ; deux processus s'appelaient
    « arbitre · arbitre » ; la recherche promettait les messages sans les chercher."""
    app, live = server(tmp_path, Turns())
    with client_of(app) as client:
        bootstrap(client)
        with client.websocket_connect(WS) as ws:
            opening(ws)
            ws.send_json({"type": "chat", "message": "salut, ça va ?", "client_msg_id": "c1"})
            assert [f for f in until(ws, "speech") if f["type"] == "speech"][-1]["text"]
            ws.send_json({"type": "chat", "message": "bon, à plus", "client_msg_id": "c2"})
            assert not [f for f in until(ws, "speech") if f["type"] == "speech"][-1]["text"]  # elle s'est tue
        messages = html.unescape(client.get("/inspecteur/fil/messages").text)
        assert "répondue → n°" in messages and "sans réponse" in messages
        client.portal.call(lambda: live.settings.save_llm(LLMConfig(backends={"local": OLLAMA})))
        providers = html.unescape(client.get("/inspecteur/reglages/fournisseurs").text)
        assert "gemma4:12b" in providers and "login de la CLI" not in providers
        processes = html.unescape(client.get("/inspecteur/systeme/processus").text)
        assert "arbitre · arbitre" not in processes and "Décider d'agir" in processes
        search = html.unescape(client.get("/inspecteur/recherche?q=salut").text)
        assert "« salut » dans messages" in search and "q=salut" in search


def test_the_veto_after_her_answer_says_she_is_the_one_waiting(tmp_path):
    """G-9 : juste après sa réponse à Adrien, « Que ferait-elle ? » disait « son dernier message attend encore une
    réponse » — on comprenait qu'elle n'avait pas répondu, alors que c'est elle qui attend."""
    app, _live = server(tmp_path, Fake())
    with client_of(app) as client:
        bootstrap(client)
        with client.websocket_connect(WS) as ws:
            opening(ws)
            ws.send_json({"type": "chat", "message": "coucou, tu vas bien ?", "client_msg_id": "c1"})
            assert [f for f in until(ws, "speech") if f["type"] == "speech"][-1]["text"]
        envers = html.unescape(client.get("/inspecteur/decisions/envers?personne=user_1").text)
        assert "Elle attend sa réponse (elle a écrit en dernier)" in envers
        assert "son dernier message attend" not in envers.lower()


def test_unconfigured_detail_is_said_with_the_role_in_french():
    """Le nom interne du rôle ne fuit plus dans les épisodes de la console (« aucun modèle associé au rôle
    « reply » »)."""
    from mika.inspector import names

    shown = names.detail(f"UnconfiguredRole: {UnconfiguredRole('reply')}")
    assert "« répondre »" in shown and "reply" not in shown
