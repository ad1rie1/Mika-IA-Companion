"""Comptes de conversation, opérateurs, propriétaires (``identity/roles.py``).

Avant : tout ``user_*`` était propriétaire (``is_owner``) et le portail
``/api/`` n'exigeait qu'un compte. Un login créé dans *Accès · Comptes* pour
parler à Mika approuvait un envoi d'e-mail, effaçait une app forgée, lançait
la boucle d'outils d'un atelier, lisait les E/S brutes de l'IA et tous les
fichiers déposés (SEC-01, SEC-10). Ces tests pinnent la séparation.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import Client

from GestionSysteme import middleware
from identity import roles

MDP = "Motdepasse-Long-42"


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _portail_actif(settings):
    settings.CONSUMER_REQUIRE_AUTH = True
    roles.invalidate()
    yield
    roles.invalidate()


@pytest.fixture
def invite(db):
    """Un compte de conversation : authentifié, pas ``is_staff``."""
    return get_user_model().objects.create_user(username="invite", password=MDP)


@pytest.fixture
def operateur(db):
    return get_user_model().objects.create_user(
        username="ops", password=MDP, is_staff=True,
    )


@pytest.fixture
def client_invite(invite):
    c = Client()
    assert c.login(username="invite", password=MDP)
    return c


@pytest.fixture
def client_operateur(operateur):
    c = Client()
    assert c.login(username="ops", password=MDP)
    return c


def _pid(user) -> str:
    return f"user_{user.pk}"


# ── Les trois niveaux ────────────────────────────────────────────


@pytest.mark.django_db
class TestNiveaux:

    def test_un_compte_de_conversation_n_est_ni_operateur_ni_proprietaire(self, invite):
        pid = _pid(invite)
        assert roles.is_chat_account(pid) is True
        assert roles.is_operator(pid) is False
        assert roles.is_owner(pid) is False

    def test_un_operateur_est_les_trois(self, operateur):
        pid = _pid(operateur)
        assert roles.is_chat_account(pid) is True
        assert roles.is_operator(pid) is True
        assert roles.is_owner(pid) is True

    def test_un_operateur_desactive_ne_l_est_plus(self, operateur):
        operateur.is_active = False
        operateur.save()
        assert roles.is_operator(_pid(operateur)) is False

    def test_owner_person_ids_fait_un_proprietaire_sans_compte(self, settings):
        settings.OWNER_PERSON_IDS = ["tg_4242"]
        assert roles.is_owner("tg_4242") is True
        assert roles.is_operator("tg_4242") is False
        assert roles.is_owner("tg_4243") is False

    @pytest.mark.parametrize("pid", ["conscience_mika", "conscience", "module_email"])
    def test_les_canaux_internes_gardent_leur_statut(self, pid):
        assert roles.is_owner(pid) is True
        assert roles.is_operator(pid) is False
        assert roles.is_chat_account(pid) is False

    @pytest.mark.parametrize("pid", ["", "anon_abcd", "tg_1", "user_", "user_x", "user_1x"])
    def test_ce_qui_n_est_pas_un_compte(self, pid):
        assert roles.is_chat_account(pid) is False
        assert roles.is_operator(pid) is False
        assert roles.is_owner(pid) is False

    def test_depuis_un_request_user(self, invite, operateur, settings):
        assert roles.person_id_of(AnonymousUser()) == ""
        assert roles.person_id_of(invite) == _pid(invite)
        assert roles.is_operator_user(AnonymousUser()) is False
        assert roles.is_operator_user(invite) is False
        assert roles.is_operator_user(operateur) is True
        assert roles.is_owner_user(invite) is False
        assert roles.is_owner_user(operateur) is True
        settings.OWNER_PERSON_IDS = [_pid(invite)]
        assert roles.is_owner_user(invite) is True

    def test_les_deux_lectures_s_accordent(self, invite, operateur):
        for user in (invite, operateur):
            assert roles.is_operator(_pid(user)) == roles.is_operator_user(user)
            assert roles.is_owner(_pid(user)) == roles.is_owner_user(user)


# ── Le cache ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCacheDesOperateurs:

    def test_une_promotion_est_vue_sans_attendre_la_peremption(self, invite):
        pid = _pid(invite)
        assert roles.is_operator(pid) is False          # cache chargé, pk absent
        invite.is_staff = True
        invite.save()                                    # post_save → invalidate
        assert roles.is_operator(pid) is True

    def test_une_retrogradation_aussi(self, operateur):
        pid = _pid(operateur)
        assert roles.is_operator(pid) is True
        operateur.is_staff = False
        operateur.save()
        assert roles.is_operator(pid) is False

    def test_une_suppression_aussi(self, operateur):
        pid = _pid(operateur)
        assert roles.is_operator(pid) is True
        operateur.delete()
        assert roles.is_operator(pid) is False

    def test_entre_deux_ecritures_la_base_n_est_pas_relue(self, operateur, monkeypatch):
        appels = []
        vraie = roles._requete

        def comptee():
            appels.append(1)
            return vraie()

        monkeypatch.setattr(roles, "_requete", comptee)
        roles.invalidate()
        pid = _pid(operateur)
        for _ in range(20):
            assert roles.is_operator(pid) is True
        assert len(appels) == 1

    def test_une_lecture_en_echec_ferme_la_porte_et_ne_martele_pas(self, operateur, monkeypatch):
        appels = []

        def cassee():
            appels.append(1)
            raise RuntimeError("database is locked")

        monkeypatch.setattr(roles, "_requete", cassee)
        roles.invalidate()
        pid = _pid(operateur)
        for _ in range(5):
            assert roles.is_operator(pid) is False
        assert len(appels) == 1

    def test_la_peremption_finit_par_relire(self, operateur, monkeypatch):
        pid = _pid(operateur)
        assert roles.is_operator(pid) is True
        # Modification « hors processus » : pas de signal.
        get_user_model().objects.filter(pk=operateur.pk).update(is_staff=False)
        assert roles.is_operator(pid) is True            # encore en cache
        monkeypatch.setattr(roles, "CACHE_TTL_S", 0.0)
        assert roles.is_operator(pid) is False


@pytest.mark.django_db(transaction=True)
class TestCacheDepuisUneCoroutine:
    """``is_owner`` est appelé en synchrone depuis des coroutines (contexte,
    fichiers, confident) : la lecture ne doit ni lever
    ``SynchronousOnlyOperation`` ni rendre faux pour un opérateur."""

    async def test_un_operateur_est_reconnu_sur_la_boucle(self):
        from asgiref.sync import sync_to_async

        user = await sync_to_async(get_user_model().objects.create_user)(
            username="ops-async", password=MDP, is_staff=True,
        )
        roles.invalidate()
        assert roles.is_owner(_pid(user)) is True
        assert roles.is_operator(_pid(user)) is True
        await sync_to_async(user.delete)()


# ── Le portail HTTP ──────────────────────────────────────────────


ROUTES_ADMIN = [
    ("post", "/api/projects/pending/999999/approve"),
    ("post", "/api/projects/pending/999999/reject"),
    ("post", "/api/projects/create"),
    ("delete", "/api/projects/999999"),
    ("post", "/api/projects/999999/advance"),
    ("get", "/api/projects/999999/history?full=1"),
    ("post", "/api/projects/999999/tasks"),
    ("get", "/api/projects/"),
    ("post", "/api/modules/forge/command"),
    ("get", "/api/modules/forge/source?name=x"),
    ("get", "/api/modules/forge/logs"),
    ("post", "/api/modules/wake/now"),
    ("get", "/api/ai/quota/"),
    ("get", "/api/dev/sleep/status"),
]


@pytest.mark.django_db
class TestPortailOperateur:

    @pytest.mark.parametrize("methode,url", ROUTES_ADMIN)
    def test_un_compte_de_conversation_est_refuse_en_403(self, client_invite, settings, methode, url):
        settings.DEBUG = True
        resp = getattr(client_invite, methode)(url)
        assert resp.status_code == 403, url
        assert resp["Content-Type"].startswith("application/json")
        assert resp.json()["error"]

    @pytest.mark.parametrize("methode,url", ROUTES_ADMIN)
    def test_un_anonyme_est_refuse_en_401(self, settings, methode, url):
        settings.DEBUG = True
        resp = getattr(Client(), methode)(url)
        assert resp.status_code == 401, url

    @pytest.mark.parametrize("methode,url", ROUTES_ADMIN)
    def test_un_operateur_atteint_la_vue(self, client_operateur, settings, methode, url):
        """Le portail laisse passer : ce que la vue répond ensuite (404 sur
        un id inventé, 400 sur un corps vide…) est son affaire."""
        settings.DEBUG = True
        if methode == "post":
            resp = client_operateur.post(url, data="{}", content_type="application/json")
        else:
            resp = getattr(client_operateur, methode)(url)
        assert resp.status_code not in (401, 403), url

    def test_l_historique_brut_de_l_ia_est_reserve_a_l_operateur(
        self, client_invite, client_operateur,
    ):
        from projects.models import Project, ProjectPromptHistory
        p = Project.objects.create(title="secret")
        ProjectPromptHistory.objects.create(
            project=p, system_prompt="SYSTEME-CONFIDENTIEL", user_prompt="u",
            raw_response="r", parsed_output={}, outcome="ok", duration_ms=1,
        )
        url = f"/api/projects/{p.pk}/history?full=1"
        refuse = client_invite.get(url)
        assert refuse.status_code == 403
        assert b"SYSTEME-CONFIDENTIEL" not in refuse.content
        ok = client_operateur.get(url)
        assert ok.status_code == 200
        assert ok.json()["history"][0]["system_prompt"] == "SYSTEME-CONFIDENTIEL"

    def test_supprimer_un_projet_exige_l_operateur(self, client_invite, client_operateur):
        from projects.models import Project
        p = Project.objects.create(title="a garder")
        assert client_invite.delete(f"/api/projects/{p.pk}").status_code == 403
        assert Project.objects.filter(pk=p.pk).exists()
        assert client_operateur.delete(f"/api/projects/{p.pk}").status_code == 200
        assert not Project.objects.filter(pk=p.pk).exists()

    def test_un_prefixe_declare_conversation_reste_ouvert(self, client_invite, monkeypatch):
        """Le mécanisme d'allow-list, vide aujourd'hui : déclaré, un préfixe
        s'ouvre à tout compte sans toucher à la vue."""
        monkeypatch.setattr(middleware, "CHAT_API_PREFIXES", ("/api/projects/",))
        assert client_invite.get("/api/projects/").status_code == 200
        assert client_invite.get("/api/ai/quota/").status_code == 403

    def test_le_prefixe_gestion_api_reste_au_personnel(self, client_invite, settings):
        settings.DASHBOARD_REQUIRE_AUTH = True
        resp = client_invite.get("/gestion/api/vitaux")
        assert resp.status_code == 401
        assert resp["Content-Type"].startswith("application/json")

    def test_portail_eteint_rien_ne_change(self, client_invite, settings):
        settings.CONSUMER_REQUIRE_AUTH = False
        assert client_invite.get("/api/projects/").status_code == 200

    def test_whoami_dit_le_niveau(self, client_invite, client_operateur):
        assert client_invite.get("/auth/whoami").json()["operator"] is False
        assert client_operateur.get("/auth/whoami").json()["operator"] is True


# ── Les fichiers ─────────────────────────────────────────────────


def _fichier(file_id: str, person_id: str) -> dict:
    return {
        "id": file_id, "name": f"{file_id}.txt", "type": "text/plain",
        "category": "document", "size_label": "1 Ko", "path": "/nulle/part",
        "person_id": person_id, "uploaded_at": "2026-09-17T10:00:00",
        "deleted": False,
    }


@pytest.fixture
def registre_fichiers(invite, operateur):
    from files.service import files_service
    from pipeline.tracing import set_current_person_id

    sauvegarde = dict(files_service._registry)
    files_service._registry.clear()
    files_service.register_file(_fichier("mien", _pid(invite)))
    files_service.register_file(_fichier("autrui", "user_999999"))
    files_service.register_file(_fichier("tg", "tg_77"))
    yield files_service
    files_service._registry.clear()
    files_service._registry.update(sauvegarde)
    set_current_person_id("")


@pytest.mark.django_db
class TestFichiersParNiveau:

    def _visibles(self, service, pid) -> set[str]:
        from pipeline.tracing import set_current_person_id
        set_current_person_id(pid)
        return {
            k for k, r in service._registry.items() if service._may_access(r)
        }

    def test_un_compte_de_conversation_ne_voit_que_les_siens(self, registre_fichiers, invite):
        assert self._visibles(registre_fichiers, _pid(invite)) == {"mien"}

    def test_l_operateur_voit_tout(self, registre_fichiers, operateur):
        assert self._visibles(registre_fichiers, _pid(operateur)) == {"mien", "autrui", "tg"}

    def test_un_proprietaire_sans_compte_voit_tout(self, registre_fichiers, settings):
        settings.OWNER_PERSON_IDS = ["tg_77"]
        assert self._visibles(registre_fichiers, "tg_77") == {"mien", "autrui", "tg"}

    def test_un_contact_externe_ne_voit_que_les_siens(self, registre_fichiers):
        assert self._visibles(registre_fichiers, "tg_77") == {"tg"}

    def test_personne_en_portee_ne_voit_rien(self, registre_fichiers):
        assert self._visibles(registre_fichiers, "") == set()


@pytest.mark.django_db(transaction=True)
class TestFichiersDepuisLesOutils:
    """Les ``op_*`` sont des coroutines : le filtre y tourne sur la boucle."""

    async def test_files_list_filtre_par_niveau(self):
        from asgiref.sync import sync_to_async
        from files.service import files_service
        from pipeline.tracing import set_current_person_id

        User = get_user_model()
        inv = await sync_to_async(User.objects.create_user)(
            username="inv-async", password=MDP,
        )
        ops = await sync_to_async(User.objects.create_user)(
            username="ops-async2", password=MDP, is_staff=True,
        )
        roles.invalidate()
        sauvegarde = dict(files_service._registry)
        files_service._registry.clear()
        files_service.register_file(_fichier("mien", _pid(inv)))
        files_service.register_file(_fichier("autrui", "user_999999"))
        try:
            set_current_person_id(_pid(inv))
            vus = await files_service.op_list()
            assert {f["id"] for f in vus["files"]} == {"mien"}
            lu = await files_service.op_read("autrui")
            assert lu == {"error": "Fichier introuvable."}

            set_current_person_id(_pid(ops))
            vus = await files_service.op_list()
            assert {f["id"] for f in vus["files"]} == {"mien", "autrui"}
        finally:
            set_current_person_id("")
            files_service._registry.clear()
            files_service._registry.update(sauvegarde)
            await sync_to_async(inv.delete)()
            await sync_to_async(ops.delete)()


# ── L'écran Accès · Comptes ──────────────────────────────────────


class TestEcranComptes:

    def test_le_drapeau_is_staff_se_lit_operateur(self):
        from GestionSysteme.config_schema import CONFIG_SCHEMA
        item = next(i for i in CONFIG_SCHEMA if getattr(i, "key", "") == "accounts.users")
        champ = next(f for f in item.record.fields if f.key == "is_staff")
        assert champ.label == "Opérateur"
        assert "conversation" in champ.hint

    def test_l_ancien_alias_du_manager_est_parti(self):
        import modules.manager as manager
        assert not hasattr(manager, "_is_owner")
