"""Le portail ``/api/`` suit le réglage du socket.

Les routes JSON du frontend exécutent des choses irréversibles (approuver une
action en attente = envoyer un e-mail, effacer un module forgé), et rien ne
les protégeait alors que le WebSocket refusait déjà l'anonyme. Depuis
``identity/roles.py``, elles exigent un *opérateur* (``is_staff``) — le
détail par route est dans ``test_roles_comptes.py``.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

MDP = "Motdepasse-Long-42"


@pytest.fixture
def anonyme():
    return Client()


@pytest.fixture
def connecte(db):
    """Un compte de conversation : authentifié, pas ``is_staff``."""
    User = get_user_model()
    User.objects.create_user(username="invite", password=MDP)
    c = Client()
    assert c.login(username="invite", password=MDP)
    return c


@pytest.fixture
def operateur(db):
    User = get_user_model()
    User.objects.create_user(username="ops", password=MDP, is_staff=True)
    c = Client()
    assert c.login(username="ops", password=MDP)
    return c


@pytest.mark.django_db
class TestPortailApi:

    def test_un_anonyme_est_refuse_en_401_json(self, anonyme, settings):
        settings.CONSUMER_REQUIRE_AUTH = True
        resp = anonyme.get("/api/projects/")
        assert resp.status_code == 401
        assert resp["Content-Type"].startswith("application/json")
        assert resp.json()["error"]

    def test_le_refus_precede_la_vue(self, anonyme, settings):
        """Une action inexistante rendrait 404 : le 401 prouve que la vue
        n'a même pas été appelée — le portail ne dépend pas de ce que la vue
        fait ou ne fait pas."""
        settings.CONSUMER_REQUIRE_AUTH = True
        resp = anonyme.post("/api/projects/pending/999999/approve")
        assert resp.status_code == 401

    def test_les_endpoints_de_dev_sont_couverts(self, anonyme, settings):
        settings.CONSUMER_REQUIRE_AUTH = True
        settings.DEBUG = True
        assert anonyme.get("/api/dev/sleep/status").status_code == 401

    def test_un_compte_de_conversation_est_refuse_en_403_json(self, connecte, settings):
        """Authentifié mais pas opérateur : 403, pas 401, et toujours du
        JSON. Il suffisait d'un compte — n'importe quel login créé dans
        *Accès · Comptes* administrait (``test_roles_comptes.py``)."""
        settings.CONSUMER_REQUIRE_AUTH = True
        resp = connecte.get("/api/projects/")
        assert resp.status_code == 403
        assert resp["Content-Type"].startswith("application/json")
        assert resp.json()["error"]

    def test_un_operateur_passe(self, operateur, settings):
        settings.CONSUMER_REQUIRE_AUTH = True
        assert operateur.get("/api/projects/").status_code == 200

    def test_les_routes_d_ouverture_de_session_restent_publiques(self, anonyme, settings):
        settings.CONSUMER_REQUIRE_AUTH = True
        assert anonyme.get("/auth/whoami").status_code == 200
        assert anonyme.get("/health").status_code == 200

    def test_le_reglage_du_socket_commande_aussi_le_portail(self, anonyme, settings):
        settings.CONSUMER_REQUIRE_AUTH = False
        assert anonyme.get("/api/projects/").status_code == 200

    def test_les_vitaux_du_dashboard_refusent_en_json_pas_en_redirection(self, anonyme, settings):
        settings.DASHBOARD_REQUIRE_AUTH = True
        resp = anonyme.get("/gestion/api/vitaux")
        assert resp.status_code == 401
        assert resp["Content-Type"].startswith("application/json")
