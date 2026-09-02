"""Correctifs du sous-système projets — un défaut constaté, un test qui le tenait.

* **Tempête de relances** — une forme inattendue dans le JSON du modèle
  (``"task_updates": "aucune"``) levait hors de tout chemin gardé ; l'échéance
  n'avançait jamais, et le modèle était rappelé à chaque tick, sans plafond.
* **Atelier attaché au titre** — le dossier s'appelait ``<id>-<slug du
  titre>`` ; renommer un projet détachait son travail.
* **Cron de repli** — jour de la semaine lu en numérotation Python (lundi = 0)
  au lieu de cron (dimanche = 0) ; pas et plages hors du jour rendaient None.
* **Règle ``event:`` comparée brute** — nettoyée à la lecture, cherchée telle
  quelle en base : une espace de fin rendait le projet sourd.
* **Destinataire hors contacts** — ``Project.contacts`` n'était lu par
  personne à l'exécution d'un ``send_email`` approuvé.
* **Redirection ouverte** — ``retour`` allait droit dans ``redirect()``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from projects import workspace
from projects.schedule import _fallback_cron_next


@pytest.fixture(autouse=True)
def _api_sans_portail(settings):
    """Ces tests exercent la logique des vues, pas le portail ``/api/``."""
    settings.CONSUMER_REQUIRE_AUTH = False


@pytest.fixture
def ateliers(tmp_path, monkeypatch) -> Path:
    racine = tmp_path / "ateliers"
    monkeypatch.setattr(workspace, "racine_des_ateliers", lambda: racine)
    return racine


def _historique_actif(size: int = 10):
    """Le lanceur lit la taille du tampon dans ``config_service``."""
    from configs.service import config_service
    real_get = config_service.get

    def _fake_get(key, default=None):
        if key == "projects.prompt_history_size":
            return size
        return real_get(key, default=default)

    return patch.object(config_service, "get", side_effect=_fake_get)


# ── 1. Tempête de relances ────────────────────────────────────────


@pytest.mark.django_db
class TestTempeteDeRelances:

    async def _projet_du(self, titre: str):
        from projects.models import Project
        return await sync_to_async(Project.objects.create)(
            title=titre, status=Project.Status.ACTIVE,
            schedule_rule="interval:5m",
            next_run_at=timezone.now() - timedelta(minutes=1),
        )

    async def test_une_forme_inattendue_est_ignoree_et_l_echeance_avance(self, ateliers):
        """``"aucune"`` n'est pas une liste de mises à jour ; l'itérer donnait
        ses lettres, et ``"a".get`` levait hors de tout chemin gardé."""
        from projects.models import Project
        from projects.runner import project_runner

        projet = await self._projet_du("Relance")

        async def bavard(*, role, prompt, tools, **kw):
            return (
                '{"summary": "rien", "task_updates": "aucune", '
                '"new_tasks": "aucune", "proposed_action": "non"}'
            ), []

        avant = timezone.now()
        with patch("projects.runner.ai_router.chat_with_tools",
                   new=AsyncMock(side_effect=bavard)), _historique_actif():
            ok = await project_runner._advance(projet.id)

        assert ok
        projet = await sync_to_async(Project.objects.get)(pk=projet.id)
        assert projet.last_run_at is not None and projet.last_run_at >= avant
        assert projet.next_run_at is not None and projet.next_run_at > avant

    async def test_une_application_qui_leve_avance_quand_meme_l_echeance(self, ateliers):
        """Ce qui a été dit est gardé (``apply_error``), ce qui n'a pas pu en
        être fait est nommé — et le projet n'est plus dû à la seconde même."""
        from projects.models import Project, ProjectPromptHistory
        from projects.runner import project_runner

        projet = await self._projet_du("Application en échec")

        async def repond(*, role, prompt, tools, **kw):
            return '{"summary": "fait"}', []

        avant = timezone.now()
        with patch("projects.runner.ai_router.chat_with_tools",
                   new=AsyncMock(side_effect=repond)), \
             patch.object(project_runner, "_apply_structured",
                          new=AsyncMock(side_effect=RuntimeError("forme imprévue"))), \
             _historique_actif():
            ok = await project_runner._advance(projet.id)

        assert ok is False
        projet = await sync_to_async(Project.objects.get)(pk=projet.id)
        assert projet.next_run_at is not None and projet.next_run_at > avant
        derniere = await sync_to_async(
            lambda: ProjectPromptHistory.objects.filter(project_id=projet.id)
            .order_by("-id").first()
        )()
        assert derniere is not None
        assert derniere.outcome == "apply_error"
        assert derniere.parsed_output == {"summary": "fait"}

    async def test_un_tick_qui_leve_avant_l_application_avance_aussi(self, ateliers):
        """Le tick attrapait l'exception, la journalisait, et laissait
        ``next_run_at`` dans le passé : le projet était rappelé à chaque
        passage du lanceur."""
        from projects.models import Project
        from projects.runner import project_runner

        projet = await self._projet_du("Lève avant")

        avant = timezone.now()
        with patch.object(project_runner, "_advance",
                          new=AsyncMock(side_effect=RuntimeError("atelier illisible"))):
            await project_runner._tick_inner()

        projet = await sync_to_async(Project.objects.get)(pk=projet.id)
        assert projet.next_run_at is not None and projet.next_run_at > avant

    def test_les_entrees_sont_filtrees_sans_etre_interpretees(self):
        from projects.runner import _entrees

        assert _entrees({"task_updates": "aucune"}, "task_updates", 1) == []
        assert _entrees({"task_updates": None}, "task_updates", 1) == []
        assert _entrees({"task_updates": {"id": 3, "status": "done"}}, "task_updates", 1) \
            == [{"id": 3, "status": "done"}]
        assert _entrees(
            {"new_tasks": [{"description": "a"}, "b", 3, None]}, "new_tasks", 1,
        ) == [{"description": "a"}]


# ── 2. L'atelier suit l'identifiant, pas le titre ─────────────────


class TestAtelierSuitLeProjet:

    def test_renommer_un_projet_garde_son_atelier(self, ateliers):
        avant = workspace.atelier_de(7, "Convertisseur CSV")
        avant.ecrire("main.py", "print('x')\n")

        apres = workspace.atelier_de(7, "Convertisseur CSV vers JSON")

        assert apres.racine == avant.racine
        assert (apres.racine / "main.py").is_file()
        assert not (ateliers / "7-convertisseur-csv-vers-json").exists()
        lu = workspace.atelier_existant(7, "Encore un autre titre")
        assert lu is not None and lu.racine == avant.racine

    def test_la_corbeille_emporte_le_travail_apres_renommage(self, ateliers):
        """La suppression ne mettait en corbeille que le dossier neuf — vide —
        et laissait le travail orphelin sous l'ancien nom."""
        atelier = workspace.atelier_de(8, "Ancien titre")
        atelier.ecrire("garde-moi.txt", "du travail")

        destination = workspace.mettre_en_corbeille(8, "Nouveau titre")

        assert destination
        assert not atelier.racine.exists()
        assert (Path(destination) / "garde-moi.txt").read_text(encoding="utf-8") == "du travail"

    def test_un_identifiant_ne_capture_pas_ses_voisins(self, ateliers):
        """``1-`` n'est pas un préfixe de ``12-``, et inversement."""
        un = workspace.atelier_de(1, "Un")
        douze = workspace.atelier_de(12, "Douze")
        assert un.racine != douze.racine
        assert workspace.atelier_existant(1, "Un renommé").racine.name == "1-un"
        assert workspace.atelier_existant(12, "Douze renommé").racine.name == "12-douze"

    def test_sans_dossier_le_nom_suit_le_titre_courant(self, ateliers):
        assert workspace.atelier_existant(3, "Jamais écrit") is None
        assert workspace.atelier_de(3, "Premier titre").racine.name == "3-premier-titre"


# ── 3. Cron de repli ──────────────────────────────────────────────


MERCREDI = datetime(2026, 9, 2, 10, 0)   # weekday() == 2
SAMEDI = datetime(2026, 9, 5, 10, 0)     # weekday() == 5


class TestCronDeRepli:
    """Dates concrètes : 2026-09-02 est un mercredi, 09-06 un dimanche."""

    def test_zero_est_dimanche_pas_lundi(self):
        prochain = _fallback_cron_next("0 9 * * 0", MERCREDI)
        assert prochain == datetime(2026, 9, 6, 9, 0)
        assert prochain.weekday() == 6

    def test_sept_est_aussi_dimanche(self):
        assert _fallback_cron_next("0 9 * * 7", MERCREDI) == datetime(2026, 9, 6, 9, 0)

    def test_un_a_cinq_couvre_lundi_a_vendredi(self):
        """Lu en numérotation Python, ``1-5`` couvrait mardi-samedi : depuis
        un samedi 10 h, la prochaine occurrence tombait le mardi."""
        assert _fallback_cron_next("0 9 * * 1-5", SAMEDI) == datetime(2026, 9, 7, 9, 0)

    def test_les_noms_de_jours_restent_compris(self):
        assert _fallback_cron_next("0 9 * * MON-FRI", SAMEDI) == datetime(2026, 9, 7, 9, 0)
        assert _fallback_cron_next("30 8 * * SAT,SUN", MERCREDI) == datetime(2026, 9, 5, 8, 30)

    def test_un_pas_sur_les_minutes(self):
        assert _fallback_cron_next("*/5 * * * *", datetime(2026, 9, 2, 10, 2)) \
            == datetime(2026, 9, 2, 10, 5)

    def test_une_plage_avec_pas_sur_les_heures(self):
        assert _fallback_cron_next("0 9-17/4 * * *", MERCREDI) == datetime(2026, 9, 2, 13, 0)

    def test_un_pas_sur_le_jour_du_mois(self):
        assert _fallback_cron_next("0 0 */10 * *", MERCREDI) == datetime(2026, 9, 11, 0, 0)

    def test_un_nom_de_mois(self):
        assert _fallback_cron_next("0 12 1 OCT *", MERCREDI) == datetime(2026, 10, 1, 12, 0)

    def test_une_forme_illisible_rend_none_en_le_disant(self, caplog):
        assert _fallback_cron_next("0 9 * * LUN", MERCREDI) is None
        assert _fallback_cron_next("0 25 * * *", MERCREDI) is None

    @pytest.mark.parametrize("expr", [
        "0 9 * * 0", "0 9 * * 7", "0 9 * * 1-5", "0 9 * * MON-FRI",
        "*/15 * * * *", "0 9-17/4 * * *", "30 8 * * SAT,SUN", "0 0 1 * *",
    ])
    def test_les_deux_analyseurs_s_accordent(self, expr):
        """croniter est la référence ; le repli ne doit jamais en diverger sur
        les formes qu'il accepte — sinon la cadence change selon l'installation."""
        croniter = pytest.importorskip("croniter").croniter
        for depart in (MERCREDI, SAMEDI, datetime(2026, 9, 2, 10, 2)):
            attendu = croniter(expr, depart.replace(second=0, microsecond=0)).get_next(datetime)
            assert _fallback_cron_next(expr, depart) == attendu, (expr, depart)


# ── 4. La règle « event: » est comparée parsée ────────────────────


@pytest.mark.django_db(transaction=True)
class TestRegleEvenementNettoyee:

    @pytest.fixture(autouse=True)
    def _clean(self):
        from projects.models import Project
        Project.objects.all().delete()
        yield

    async def test_une_regle_avec_des_espaces_est_quand_meme_reveillee(self):
        """Stockée avec une espace de fin, la règle se lisait « event:x » et
        n'était jamais trouvée par la recherche exacte du lanceur."""
        from projects.models import Project
        from projects.runner import project_runner

        p = await sync_to_async(Project.objects.create)(
            title="Veille", schedule_rule="  Event:email.received ", next_run_at=None,
        )
        await project_runner.notify_event("email.received")
        refreshed = await sync_to_async(Project.objects.get)(pk=p.pk)
        assert refreshed.next_run_at is not None

    async def test_un_autre_evenement_ne_reveille_pas(self):
        from projects.models import Project
        from projects.runner import project_runner

        p = await sync_to_async(Project.objects.create)(
            title="Veille", schedule_rule="event:email.received", next_run_at=None,
        )
        await project_runner.notify_event("email.received.bis")
        refreshed = await sync_to_async(Project.objects.get)(pk=p.pk)
        assert refreshed.next_run_at is None

    def test_l_api_nettoie_la_regle_a_la_creation(self, client: Client):
        from projects.models import Project

        resp = client.post(
            "/api/projects/create",
            data=json.dumps({"title": "Espaces", "schedule_rule": "  event:email.received "}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert Project.objects.get(pk=resp.json()["project"]["id"]).schedule_rule \
            == "event:email.received"

    def test_l_api_nettoie_la_regle_a_la_modification(self, client: Client):
        from projects.models import Project

        p = Project.objects.create(title="Espaces")
        resp = client.patch(
            f"/api/projects/{p.pk}",
            data=json.dumps({"schedule_rule": " interval:5m "}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        p.refresh_from_db()
        assert p.schedule_rule == "interval:5m"
        assert p.next_run_at is not None

    async def test_l_outil_nettoie_la_regle(self):
        from projects.models import Project
        from projects.tools import ProjectToolsModule

        mod = ProjectToolsModule()
        await mod._tool_create({"title": "Outil", "schedule_rule": " event:email.received "})
        p = await sync_to_async(lambda: Project.objects.get(title="Outil"))()
        assert p.schedule_rule == "event:email.received"

        await mod._tool_update_project({"project_id": p.pk, "schedule_rule": " interval:1h "})
        p = await sync_to_async(lambda: Project.objects.get(pk=p.pk))()
        assert p.schedule_rule == "interval:1h"


# ── 5. Un envoi approuvé reste dans les contacts du projet ────────


@pytest.mark.django_db
class TestDestinataireDansLesContacts:

    def _action(self, contacts, to):
        from projects.models import Project, ProjectPendingAction

        p = Project.objects.create(title="Courrier", contacts=contacts, requires_approval=True)
        return ProjectPendingAction.objects.create(
            project=p, proposal="écrire",
            payload={"kind": "send_email", "to": to, "subject": "s", "body": "b"},
        )

    def _approuver(self, client: Client, action_id: int, envois: list):
        class _FauxEmail:
            async def send_email(self, *, to, subject, body, account_id=None):
                envois.append(to)
                return True, f"Email sent to {to}"

        with patch("modules.manager.module_manager") as mm, \
             patch("pipeline.broadcast.broadcast_inner_state_update", new=AsyncMock()):
            mm.get_module.return_value = _FauxEmail()
            return client.post(
                f"/api/projects/pending/{action_id}/approve",
                data="{}", content_type="application/json",
            )

    def test_hors_contacts_est_refuse_sans_envoyer(self, client: Client):
        from projects.models import ProjectPendingAction

        a = self._action(["alice@example.org"], "bob@example.org")
        envois: list = []
        resp = self._approuver(client, a.pk, envois)

        assert resp.status_code == 200
        a.refresh_from_db()
        assert a.status == ProjectPendingAction.Status.FAILED
        assert envois == []
        assert "contacts" in a.execution_result
        assert "bob@example.org" in a.execution_result

    def test_dans_les_contacts_part(self, client: Client):
        from projects.models import ProjectPendingAction

        a = self._action(["Alice@Example.org"], "alice@example.org")
        envois: list = []
        self._approuver(client, a.pk, envois)

        a.refresh_from_db()
        assert a.status == ProjectPendingAction.Status.EXECUTED
        assert envois == ["alice@example.org"]

    def test_sans_contact_declare_le_perimetre_ne_contraint_pas(self, client: Client):
        from projects.models import ProjectPendingAction

        a = self._action([], "n-importe-qui@example.org")
        envois: list = []
        self._approuver(client, a.pk, envois)

        a.refresh_from_db()
        assert a.status == ProjectPendingAction.Status.EXECUTED
        assert envois == ["n-importe-qui@example.org"]

    def test_l_ecran_du_tableau_de_bord_refuse_pareil(self, client: Client):
        """Les deux chemins d'approbation partagent l'exécuteur : le refus
        n'a pas à être réimplémenté, seulement constaté."""
        from projects.models import ProjectPendingAction

        a = self._action(["alice@example.org"], "bob@example.org")
        envois: list = []
        with patch("modules.manager.module_manager") as mm:
            mm.get_module.return_value = type("M", (), {
                "send_email": AsyncMock(side_effect=lambda **k: envois.append(k) or (True, "ok")),
            })()
            client.post(
                reverse("gestionsysteme:project-pending-action", args=[a.pk]),
                {"decision": "approuver"},
            )
        a.refresh_from_db()
        assert a.status == ProjectPendingAction.Status.FAILED
        assert envois == []


# ── 6. Le retour d'une action de projet ne sort jamais du site ────


@pytest.fixture
def action_en_attente(db):
    from projects.models import Project, ProjectPendingAction

    p = Project.objects.create(title="Redirection")
    return ProjectPendingAction.objects.create(project=p, proposal="p", payload={})


@pytest.mark.parametrize("hostile", [
    "https://evil.test/phishing",
    "//evil.test/phishing",
    "http://evil.test",
])
def test_le_retour_d_une_action_de_projet_ne_sort_jamais_du_site(
    client: Client, action_en_attente, hostile,
):
    """Le contrôle existait pour les identités ; les projets refaisaient le
    ``redirect(back)`` brut à quatre endroits."""
    from projects.models import ProjectPendingAction

    response = client.post(
        reverse("gestionsysteme:project-pending-action", args=[action_en_attente.pk]),
        {"decision": "rejeter", "retour": hostile},
    )
    assert response.status_code == 302
    assert response["Location"] == reverse("gestionsysteme:projects-tab", args=["attente"])
    action_en_attente.refresh_from_db()
    assert action_en_attente.status == ProjectPendingAction.Status.REJECTED


def test_un_retour_legitime_est_preserve_filtres_compris(client: Client, action_en_attente):
    retour = reverse(
        "gestionsysteme:project-detail", args=[action_en_attente.project_id],
    ) + "?page=2"
    response = client.post(
        reverse("gestionsysteme:project-pending-action", args=[action_en_attente.pk]),
        {"decision": "rejeter", "retour": retour},
    )
    assert response.status_code == 302
    assert response["Location"] == retour


def test_le_controle_de_retour_est_partage_entre_les_ecrans():
    """Une seconde copie est celle qu'on oublie de corriger : les deux vues
    doivent appeler la même fonction, pas deux fonctions du même nom."""
    from GestionSysteme.retour import retour_sur
    from GestionSysteme.views import projects as vues_projets, social as vues_social

    assert vues_projets.retour_sur is retour_sur
    assert vues_social._safe_back is retour_sur
