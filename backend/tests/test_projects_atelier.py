"""L'atelier d'un projet : confinement, frontière d'exécution, trousse, lanceur.

Le chemin d'avance du lanceur n'était couvert par AUCUN test avant ce fichier
— ni l'appel au modèle, ni ce qui en découle. C'est le cœur du sous-système,
et c'est là qu'un projet logiciel se bloquait sans que rien ne le dise.

Ce qui est épinglé ici tient en une phrase par famille :

* **Confinement** — sortir de l'atelier est impossible depuis la trousse, y
  compris par un lien symbolique, qui est le cas qu'une comparaison de
  chaînes laisse passer.
* **Frontière** — pas de shell, exécutables déclarés, et surtout un
  environnement RECONSTRUIT : le processus du serveur porte les secrets de
  l'installation, les hériter les remettrait à un script écrit par un modèle.
* **Trousse** — un handler ne lève jamais ; il raconte l'échec au modèle.
* **Lanceur** — il appelle la boucle d'outils, et n'enregistre que les tours
  qui ont réellement produit quelque chose.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from projects import execution, workspace
from projects.execution import ExecResult, run_bounded
from projects.workspace import Atelier, HorsAtelier


@pytest.fixture(autouse=True)
def _sans_namespace(monkeypatch):
    """Neutralise la coupure réseau opportuniste.

    Sa disponibilité dépend du noyau de la machine : un test qui en dépend
    passe ici et échoue ailleurs. Ce qui doit être épinglé, c'est que son
    absence est DITE — pas qu'elle est présente.
    """
    monkeypatch.setattr(execution, "_prefixe_reseau", [])


@pytest.fixture
def atelier(tmp_path) -> Atelier:
    racine = tmp_path / "atelier"
    racine.mkdir()
    return Atelier(project_id=1, racine=racine)


# ── Confinement ───────────────────────────────────────────────────


class TestConfinement:

    def test_un_chemin_relatif_ordinaire_passe(self, atelier):
        cible = atelier.chemin("src/main.py")
        assert cible.is_relative_to(atelier.racine)

    def test_remonter_est_refuse(self, atelier):
        with pytest.raises(HorsAtelier):
            atelier.chemin("../../etc/passwd")

    def test_un_chemin_absolu_est_refuse(self, atelier):
        with pytest.raises(HorsAtelier):
            atelier.chemin("/etc/passwd")

    def test_un_lien_symbolique_sortant_est_refuse(self, atelier, tmp_path):
        """Le cas qu'une comparaison de chaînes laisse passer.

        `atelier/evasion` commence bien par la racine ; ce n'est qu'en le
        résolvant qu'on voit qu'il pointe ailleurs.
        """
        dehors = tmp_path / "dehors"
        dehors.mkdir()
        (dehors / "secret.txt").write_text("x", encoding="utf-8")
        (atelier.racine / "evasion").symlink_to(dehors)

        with pytest.raises(HorsAtelier):
            atelier.chemin("evasion/secret.txt")

    def test_le_git_de_l_atelier_ne_s_ecrit_pas(self, atelier):
        atelier.chemin(".git/config")  # lisible
        with pytest.raises(HorsAtelier):
            atelier.chemin(".git/config", pour_ecriture=True)

    def test_ecrire_lire_editer(self, atelier):
        atelier.ecrire("src/a.py", "x = 1\ny = 2\n")
        assert atelier.lire("src/a.py") == "x = 1\ny = 2\n"
        atelier.remplacer("src/a.py", "y = 2", "y = 3")
        assert "y = 3" in atelier.lire("src/a.py")

    def test_une_edition_ambigue_echoue_plutot_que_de_deviner(self, atelier):
        """Une édition « à peu près » sur du code produit un fichier plausible
        et faux, ce qui coûte plus cher que l'échec."""
        atelier.ecrire("a.py", "n = 0\nn = 0\n")
        with pytest.raises(ValueError, match="2 fois"):
            atelier.remplacer("a.py", "n = 0", "n = 1")

    def test_une_edition_sans_cible_echoue(self, atelier):
        atelier.ecrire("a.py", "n = 0\n")
        with pytest.raises(ValueError, match="introuvable"):
            atelier.remplacer("a.py", "absent", "x")

    def test_l_arborescence_masque_les_organes(self, atelier):
        atelier.ecrire("code.py", "x")
        (atelier.racine / ".git").mkdir()
        (atelier.racine / ".git" / "HEAD").write_text("ref", encoding="utf-8")
        (atelier.racine / execution.HOME_DIRNAME).mkdir()
        (atelier.racine / execution.HOME_DIRNAME / "cache").write_text("c", encoding="utf-8")

        listing = "\n".join(atelier.arborescence())
        assert "code.py" in listing
        assert ".git" not in listing
        assert execution.HOME_DIRNAME not in listing


# ── Frontière d'exécution ─────────────────────────────────────────


class TestFrontiere:

    async def test_une_commande_hors_liste_est_refusee_en_le_disant(self, atelier):
        r = await run_bounded(racine=atelier.racine, argv=["curl", "https://exemple.test"])
        assert r.refused
        assert "curl" in r.refused
        assert "python" in r.refused, "le refus doit dire ce qui est disponible"
        assert r.returncode is None, "la commande ne doit pas avoir été lancée"

    async def test_une_commande_autorisee_tourne_dans_l_atelier(self, atelier):
        atelier.ecrire("bonjour.txt", "coucou")
        r = await run_bounded(
            racine=atelier.racine,
            argv=["python3", "-c", "print(open('bonjour.txt').read())"],
        )
        assert r.ok, r.stderr
        assert "coucou" in r.stdout

    async def test_les_secrets_du_serveur_n_atteignent_pas_le_processus(
        self, atelier, monkeypatch,
    ):
        """La borne la plus importante du dispositif.

        Le processus du serveur porte ``CONFIG_ENCRYPTION_KEY`` et
        ``DJANGO_SECRET_KEY`` dans son environnement, et le comportement PAR
        DÉFAUT de ``create_subprocess_exec`` est d'hériter : ce serait remettre
        les secrets de l'installation à un script écrit par un modèle.
        """
        monkeypatch.setenv("CONFIG_ENCRYPTION_KEY", "SECRET-DU-SERVEUR")
        monkeypatch.setenv("DJANGO_SECRET_KEY", "AUTRE-SECRET")

        r = await run_bounded(
            racine=atelier.racine,
            argv=["python3", "-c", "import os; print(sorted(os.environ))"],
        )
        assert r.ok, r.stderr
        assert "CONFIG_ENCRYPTION_KEY" not in r.stdout
        assert "DJANGO_SECRET_KEY" not in r.stdout
        assert "MIKA_ATELIER" in r.stdout, "l'environnement construit doit être là"

    async def test_le_home_du_processus_est_dans_l_atelier(self, atelier):
        r = await run_bounded(
            racine=atelier.racine,
            argv=["python3", "-c", "import os; print(os.environ['HOME'])"],
        )
        assert r.ok, r.stderr
        assert str(atelier.racine) in r.stdout

    async def test_l_entree_est_fermee(self, atelier):
        """Sans stdin fermé, un `input()` oublié bloque tout le délai."""
        r = await run_bounded(
            racine=atelier.racine,
            argv=["python3", "-c", "import sys; print(sys.stdin.read() == '')"],
            timeout_s=15,
        )
        assert r.ok, r.stderr
        assert "True" in r.stdout

    async def test_le_delai_tue_toute_la_descendance(self, atelier):
        """Tuer le seul enfant laisserait ses petits-enfants tourner."""
        script = (
            "import subprocess, sys, time\n"
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "open('petit-fils.pid', 'w').write(str(p.pid))\n"
            "time.sleep(60)\n"
        )
        r = await run_bounded(
            racine=atelier.racine, argv=["python3", "-c", script], timeout_s=3,
        )
        assert r.timed_out

        pid_file = atelier.racine / "petit-fils.pid"
        if pid_file.exists():  # l'enfant a eu le temps de le lancer
            pid = int(pid_file.read_text().strip())
            with pytest.raises(OSError):
                for _ in range(40):
                    os.kill(pid, 0)  # lève dès que le processus est parti
                    import time as _t

                    _t.sleep(0.1)

    async def test_la_sortie_est_plafonnee(self, atelier):
        r = await run_bounded(
            racine=atelier.racine,
            argv=["python3", "-c", "print('a' * 300000)"],
        )
        assert r.ok, r.stderr
        assert r.truncated
        assert len(r.stdout) < 100_000

    async def test_une_commande_vide_est_refusee_sans_lancer_de_shell(self, atelier):
        r = await run_bounded(racine=atelier.racine, argv=[])
        assert r.refused

    async def test_l_absence_de_coupure_reseau_est_dite(self, atelier, monkeypatch):
        """Prétendre couper sans couper serait pire que ne rien faire."""
        monkeypatch.setattr(execution, "_prefixe_reseau", [])
        r = await run_bounded(racine=atelier.racine, argv=["python3", "-c", "pass"])
        assert any("réseau NON coupé" in n for n in r.notes)


# ── Trousse ───────────────────────────────────────────────────────


class TestTrousse:

    def _outil(self, trousse, nom):
        return next(t for t in trousse if t.name == nom)

    async def test_un_chemin_hors_atelier_est_raconte_pas_leve(self, atelier):
        """Une exception qui remonte tuerait le tour ; une phrase le fait
        avancer."""
        from projects.toolkit import construire_trousse

        trousse = construire_trousse(atelier)
        r = await self._outil(trousse, "project_read_file").handler(
            {"chemin": "../../etc/passwd"},
        )
        texte = r["content"][0]["text"]
        assert "hors de l'atelier" in texte

    async def test_ecrire_puis_lister(self, atelier):
        from projects.toolkit import construire_trousse

        trousse = construire_trousse(atelier)
        await self._outil(trousse, "project_write_file").handler(
            {"chemin": "src/outil.py", "contenu": "print('ok')\n"},
        )
        listing = (await self._outil(trousse, "project_list_files").handler({}))
        assert "src/outil.py" in listing["content"][0]["text"]

    async def test_tester_sans_commande_declaree_le_dit(self, atelier):
        from projects.toolkit import construire_trousse

        trousse = construire_trousse(atelier, commande_de_test="")
        r = await self._outil(trousse, "project_test").handler({})
        assert "déclarée" in r["content"][0]["text"]

    async def test_la_commande_de_test_du_projet_est_utilisee(self, atelier):
        from projects.toolkit import construire_trousse

        trousse = construire_trousse(atelier, commande_de_test="python3 -c print(7*6)")
        r = await self._outil(trousse, "project_test").handler({})
        assert "42" in r["content"][0]["text"]

    async def test_la_trousse_ne_prend_aucun_identifiant_de_projet(self, atelier):
        """La portée est portée par la fermeture, pas par un argument à
        valider : le modèle ne peut pas désigner l'atelier d'un autre projet,
        même par erreur."""
        from projects.toolkit import construire_trousse

        for outil in construire_trousse(atelier):
            noms = {p.name for p in outil.parameters}
            assert "project_id" not in noms
            assert "projet" not in noms


# ── Lanceur ───────────────────────────────────────────────────────


@pytest.mark.django_db
class TestLanceurOutille:

    def test_le_role_retombe_quand_il_n_est_pas_mappe(self):
        """Exiger le mappage casserait toute installation qui met à jour, au
        moment précis où ses projets se mettent à travailler."""
        from ai.router import AIRole, UnconfiguredRoleError, ai_router
        from projects.runner import project_runner

        with patch.object(
            ai_router, "_resolve", side_effect=UnconfiguredRoleError("pas mappé"),
        ):
            assert project_runner._role_de_travail() is AIRole.MEMORY_EXTRACTION

    def test_le_role_dedie_est_pris_quand_il_existe(self):
        from ai.router import AIRole, ai_router
        from projects.runner import project_runner

        with patch.object(ai_router, "_resolve", return_value=("p", "m", 0.7, "n")):
            assert project_runner._role_de_travail() is AIRole.PROJECT_WORK

    async def test_une_avance_passe_par_la_boucle_d_outils(self, tmp_path, monkeypatch):
        """Le lanceur appelait ``complete`` — une complétion texte, aucun
        outil transmis. Il ne pouvait donc rien faire, seulement décrire."""
        from asgiref.sync import sync_to_async

        from projects.models import Project
        from projects.runner import project_runner

        monkeypatch.setattr(
            workspace, "racine_des_ateliers", lambda: tmp_path / "ateliers",
        )
        projet = await sync_to_async(Project.objects.create)(
            title="Atelier d'essai", status=Project.Status.ACTIVE,
        )

        appel = {}

        async def faux_chat_with_tools(*, role, prompt, tools, **kw):
            appel["role"] = role
            appel["outils"] = [t.name for t in tools]
            appel["systeme"] = prompt.system_stable
            return '{"summary": "rien fait"}', []

        with patch("projects.runner.ai_router.chat_with_tools",
                   new=AsyncMock(side_effect=faux_chat_with_tools)), \
             patch("projects.runner.ai_router.complete",
                   new=AsyncMock(side_effect=AssertionError(
                       "le lanceur ne doit plus passer par la complétion texte"))):
            ok = await project_runner._advance(projet.id)

        assert ok
        assert "project_write_file" in appel["outils"]
        assert "project_run" in appel["outils"]
        assert "TON ATELIER" in appel["systeme"]

    async def test_un_tour_sans_modification_ne_produit_pas_de_commit(
        self, tmp_path, monkeypatch,
    ):
        """Un historique où chaque tick laisse une trace ne se relit plus — et
        c'est la relecture qu'on cherche."""
        from asgiref.sync import sync_to_async

        from projects.models import Project, ProjectLog
        from projects.runner import project_runner

        monkeypatch.setattr(
            workspace, "racine_des_ateliers", lambda: tmp_path / "ateliers",
        )
        projet = await sync_to_async(Project.objects.create)(
            title="Sans écriture", status=Project.Status.ACTIVE,
        )

        async def rien(*, role, prompt, tools, **kw):
            return '{"summary": "j\'ai réfléchi"}', []

        with patch("projects.runner.ai_router.chat_with_tools",
                   new=AsyncMock(side_effect=rien)):
            await project_runner._advance(projet.id)

        commits = await sync_to_async(
            lambda: list(ProjectLog.objects.filter(
                project_id=projet.id, action="committed",
            ))
        )()
        assert commits == []

    async def test_un_tour_qui_ecrit_est_enregistre(self, tmp_path, monkeypatch):
        from asgiref.sync import sync_to_async

        from projects.models import Project, ProjectLog
        from projects.runner import project_runner

        monkeypatch.setattr(
            workspace, "racine_des_ateliers", lambda: tmp_path / "ateliers",
        )
        projet = await sync_to_async(Project.objects.create)(
            title="Avec écriture", status=Project.Status.ACTIVE,
        )

        async def ecrit(*, role, prompt, tools, **kw):
            outil = next(t for t in tools if t.name == "project_write_file")
            await outil.handler({"chemin": "csv2json.py", "contenu": "import csv\n"})
            return '{"summary": "premier jet du convertisseur"}', ["project_write_file"]

        with patch("projects.runner.ai_router.chat_with_tools",
                   new=AsyncMock(side_effect=ecrit)):
            await project_runner._advance(projet.id)

        atelier = workspace.atelier_existant(projet.id, projet.title)
        assert atelier is not None
        assert (atelier.racine / "csv2json.py").is_file()

        commits = await sync_to_async(
            lambda: [l.summary for l in ProjectLog.objects.filter(
                project_id=projet.id, action="committed",
            )]
        )()
        assert len(commits) == 1
        assert "convertisseur" in commits[0]


# ── Corbeille ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCorbeille:

    def test_supprimer_un_projet_deplace_son_atelier(self, tmp_path, monkeypatch):
        """Supprimer un projet supprimait des lignes en base. Il supprime
        maintenant du travail, et le travail ne se jette pas sur un clic."""
        monkeypatch.setattr(
            workspace, "racine_des_ateliers", lambda: tmp_path / "ateliers",
        )
        atelier = workspace.atelier_de(7, "Mon projet")
        atelier.ecrire("garde-moi.txt", "du travail")

        destination = workspace.mettre_en_corbeille(7, "Mon projet")

        assert destination
        assert not atelier.racine.exists()
        assert (Path(destination) / "garde-moi.txt").read_text(encoding="utf-8") == "du travail"

    def test_sans_atelier_il_n_y_a_rien_a_jeter(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            workspace, "racine_des_ateliers", lambda: tmp_path / "ateliers",
        )
        assert workspace.mettre_en_corbeille(99, "Jamais écrit") == ""
