"""Le journal d'appels d'outils.

Ce que ces tests épinglent n'est pas un format de chaîne mais cinq propriétés
sans lesquelles le carnet remplacerait une cécité par une autre :

  * un journal imbriqué rend le sien à son appelant en sortant ;
  * noter sans journal ouvert est un cas *normal*, silencieux et sans coût ;
  * la borne de volume limite la mémoire et **jamais** l'arithmétique ;
  * un handler qui tourne dans un thread d'exécuteur écrit dans le journal de
    son appelant — c'est là que vivent la moitié des outils du dépôt ;
  * l'extrait d'un échec survit jusqu'au résumé, faute de quoi on retombe sur
    exactement le défaut qu'on répare (trois plantages indiscernables de
    trois réussites).

Aucune base de données : le module est pur, ses tests aussi.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import FrozenInstanceError

import pytest

from old.backend.utils.tool_trace import (
    AUCUN_APPEL,
    MAX_APPELS_RETENUS,
    MAX_EXTRAIT,
    AppelOutil,
    JournalOutils,
    borne_extrait,
    journal_courant,
    journal_outils,
    noter,
    noter_appel,
)


def _ok(nom: str = "memory_search", **kw) -> AppelOutil:
    return AppelOutil(nom=nom, ok=True, **kw)


def _rate(nom: str = "memory_search", extrait: str = "boum", **kw) -> AppelOutil:
    return AppelOutil(nom=nom, ok=False, extrait=extrait, **kw)


# ---------------------------------------------------------------------------
# 1. La ligne de journal
# ---------------------------------------------------------------------------


class TestAppelOutil:

    def test_une_ligne_notee_ne_se_reecrit_plus(self):
        """Un constat est gelé : rien en aval n'a à corriger un appel fini."""
        appel = _ok()
        with pytest.raises(FrozenInstanceError):
            appel.nom = "autre_chose"  # type: ignore[misc]

    def test_un_extrait_est_borne_des_la_construction(self):
        """Borné à l'écriture seulement, l'appelant qui garde l'objet
        tiendrait les 40 ko que le journal a refusés."""
        appel = _rate(extrait="x" * (MAX_EXTRAIT * 10))
        assert len(appel.extrait) == MAX_EXTRAIT
        assert appel.extrait.endswith("…")

    def test_un_extrait_court_passe_intact(self):
        assert _rate(extrait="base verrouillée").extrait == "base verrouillée"

    def test_un_extrait_tient_sur_une_ligne(self):
        """Sa destination est une ligne de log ; un saut de ligne y casse
        autant la lecture que le grep."""
        appel = _rate(extrait="Traceback\n  File x\n\nValueError: nope")
        assert "\n" not in appel.extrait
        assert "ValueError: nope" in appel.extrait

    def test_une_duree_absurde_ne_fait_pas_lever(self):
        """Le site d'exécution est déjà en train de gérer une erreur ; il ne
        doit pas gagner une seconde raison de planter."""
        assert AppelOutil(nom="t", ms="douze").ms == 0.0  # type: ignore[arg-type]
        assert AppelOutil(nom="t", ms=float("nan")).ms == 0.0
        assert AppelOutil(nom="t", ms=-5).ms == 0.0

    def test_borne_extrait_survit_a_un_objet_hostile(self):
        class Hostile:
            def __str__(self):
                raise RuntimeError("non")

        assert borne_extrait(Hostile()) == "<extrait illisible>"


# ---------------------------------------------------------------------------
# 2. Le journal : compter et retenir sont deux choses
# ---------------------------------------------------------------------------


class TestJournal:

    def test_reussites_et_echecs_sont_distingues(self):
        """La propriété que tout le reste sert : trois plantages ne valent
        pas trois réussites."""
        journal = JournalOutils()
        journal.noter(_ok("a"))
        journal.noter(_rate("b"))
        journal.noter(_rate("c"))
        assert journal.total == 3
        assert journal.reussites == 1
        assert journal.echecs == 2
        assert journal.rate() is True

    def test_la_borne_limite_la_memoire_jamais_l_arithmetique(self):
        journal = JournalOutils(max_appels=4)
        for i in range(50):
            journal.noter(_rate(f"outil_{i}"))
        assert len(journal.appels) == 4
        assert journal.total == 50
        assert journal.echecs == 50
        assert journal.tronques == 46

    def test_le_resume_avoue_ce_qu_il_ne_detaille_pas(self):
        journal = JournalOutils(max_appels=2)
        for i in range(9):
            journal.noter(_ok(f"outil_{i}"))
        resume = journal.resume()
        assert "9 appels" in resume
        assert "7 non détaillés" in resume

    def test_la_borne_par_defaut_est_une_constante_de_module(self):
        journal = JournalOutils()
        for i in range(MAX_APPELS_RETENUS + 5):
            journal.noter(_ok(f"outil_{i}"))
        assert len(journal.appels) == MAX_APPELS_RETENUS

    def test_un_journal_ouvert_et_vide_n_est_pas_une_absence(self):
        """« Elle n'a appelé aucun outil » et « personne ne regardait » sont
        deux faits différents et doivent le rester."""
        journal = JournalOutils()
        assert journal.resume() == AUCUN_APPEL
        assert bool(journal) is True
        assert len(journal) == 0

    def test_le_resume_nomme_l_outil_qui_a_echoue_avec_son_extrait(self):
        journal = JournalOutils()
        journal.noter(_ok("memory_recent_souvenirs"))
        journal.noter(_rate("memory_search", extrait="database is locked", ms=12))
        resume = journal.resume()
        assert "memory_search" in resume
        assert "database is locked" in resume
        assert "1 échec" in resume

    def test_un_tour_sans_echec_nomme_quand_meme_les_outils(self):
        """Second usage du carnet : dans un log, « elle a cherché en mémoire »
        et « elle n'a rien fait » doivent se lire différemment."""
        journal = JournalOutils()
        journal.noter(_ok("memory_search"))
        journal.noter(_ok("memory_search"))
        resume = journal.resume()
        assert "memory_search" in resume
        assert resume.count("memory_search") == 1  # dédoublonné
        assert "0 échec" in resume

    def test_les_durees_s_additionnent(self):
        journal = JournalOutils()
        journal.noter(_ok("a", ms=10.5))
        journal.noter(_rate("b", ms=1.5))
        assert journal.ms == 12.0
        assert "12 ms" in journal.resume()

    def test_la_forme_ecran_porte_les_memes_chiffres_que_la_ligne(self):
        journal = JournalOutils(max_appels=1)
        journal.noter(_ok("a"))
        journal.noter(_rate("b", extrait="nope"))
        charge = journal.as_dict()
        assert charge["total"] == 2
        assert charge["echecs"] == 1
        assert charge["tronques"] == 1
        assert len(charge["appels"]) == 1
        assert charge["resume"] == journal.resume()
        assert charge["appels"][0]["nom"] == "a"


# ---------------------------------------------------------------------------
# 3. Portée : imbrication, absence, tâches concurrentes
# ---------------------------------------------------------------------------


class TestPortee:

    def test_un_journal_imbrique_rend_le_sien_a_son_appelant(self):
        """Un outil peut rappeler le modèle (`files_analyze_image`) : le
        journal intérieur ne doit ni voler les notes de l'extérieur, ni
        éteindre la trace en sortant."""
        with journal_outils() as dehors:
            noter(_ok("dehors_avant"))
            with journal_outils() as dedans:
                noter(_ok("dedans"))
                assert journal_courant() is dedans
            assert journal_courant() is dehors
            noter(_ok("dehors_apres"))

        assert [a.nom for a in dehors.appels] == ["dehors_avant", "dehors_apres"]
        assert [a.nom for a in dedans.appels] == ["dedans"]

    def test_sortir_du_dernier_journal_ne_laisse_rien_derriere(self):
        with journal_outils():
            pass
        assert journal_courant() is None

    def test_noter_sans_journal_ouvert_ne_leve_pas(self):
        """Le module est appelé depuis `_wrap_handler`, donc depuis TOUS les
        chemins d'outils — conversation comprise, où personne n'ouvre de
        journal. Lever ici ferait tomber un appel d'outil parce que sa trace
        n'avait nulle part où aller.
        """
        assert journal_courant() is None
        assert noter(_rate("memory_search")) is False
        assert noter_appel("memory_search", ok=False, extrait="boum") is False

    def test_une_exception_dans_le_bloc_restaure_quand_meme(self):
        with pytest.raises(RuntimeError):
            with journal_outils():
                raise RuntimeError("le tour a planté")
        assert journal_courant() is None

    def test_un_journal_reste_lisible_apres_la_sortie(self):
        """Le lecteur est l'appelant, et il lit *après* le bloc."""
        with journal_outils() as journal:
            noter(_rate("forge_test_module", extrait="ForgeTimeout"))
        assert journal.echecs == 1
        assert "ForgeTimeout" in journal.resume()

    async def test_deux_taches_concurrentes_ne_melangent_pas_leurs_journaux(self):
        """Les six boucles de fond appellent des outils pendant qu'un tour de
        conversation en appelle : une variable de module les mélangerait."""
        vus: dict[str, JournalOutils] = {}

        async def tour(nom: str):
            with journal_outils() as journal:
                await asyncio.sleep(0)
                noter(_ok(nom))
                await asyncio.sleep(0)
                noter(_ok(nom))
                vus[nom] = journal

        with journal_outils() as parent:
            await asyncio.gather(tour("a"), tour("b"))
            assert journal_courant() is parent

        assert parent.total == 0
        assert [a.nom for a in vus["a"].appels] == ["a", "a"]
        assert [a.nom for a in vus["b"].appels] == ["b", "b"]


# ---------------------------------------------------------------------------
# 4. Threads : là où vit la moitié des handlers
# ---------------------------------------------------------------------------


class TestThreads:

    async def test_un_handler_dans_un_thread_d_executeur_ecrit_chez_son_appelant(self):
        """`asyncio.to_thread` recopie le contexte : le ContextVar suit, et le
        journal étant *mutable et partagé*, ce que le thread y ajoute revient.
        Une réaffectation du ContextVar, elle, ne remonterait jamais."""
        with journal_outils() as journal:
            def handler_synchrone():
                assert journal_courant() is journal
                noter(_rate("memory_search", extrait="database is locked"))

            await asyncio.to_thread(handler_synchrone)

        assert journal.echecs == 1
        assert "database is locked" in journal.resume()

    @pytest.mark.parametrize("thread_sensitive", [True, False])
    async def test_un_handler_passe_par_sync_to_async_ecrit_chez_son_appelant(
        self, thread_sensitive,
    ):
        """Le chemin réel du dépôt, et non seulement `asyncio.to_thread`.

        Les handlers d'outils du dépôt franchissent la frontière sync/async par
        `sync_to_async`, pas par `to_thread` — et `thread_sensitive=True`, le
        défaut, les sérialise sur un thread exécuteur *partagé et réutilisé*,
        ce qui est précisément la configuration où l'on pouvait craindre qu'un
        contexte traîne ou se perde. C'est le seul endroit où la trace pouvait
        disparaître en silence : un journal qui ne voit rien est
        indistinguable d'un tour sans appel d'outil.

        asgiref recopie le contexte courant dans les deux modes. On l'épingle
        plutôt que de l'espérer : le jour où cette propriété change, c'est ce
        test qui doit rougir, pas un compteur d'échecs resté à zéro en
        production.
        """
        from asgiref.sync import sync_to_async

        with journal_outils() as journal:
            def handler_synchrone():
                assert journal_courant() is journal
                noter(_rate("memory_search", extrait="database is locked"))

            await sync_to_async(
                handler_synchrone, thread_sensitive=thread_sensitive,
            )()

        assert journal.echecs == 1
        assert "database is locked" in journal.resume()

    def test_un_thread_sans_contexte_herite_ne_leve_pas(self):
        """Un `threading.Thread` nu démarre avec un contexte vierge : il n'y a
        pas de journal, et noter doit y être un non-événement."""
        resultats: list[object] = []

        with journal_outils() as journal:
            def sans_contexte():
                resultats.append(journal_courant())
                resultats.append(noter(_ok("memory_search")))

            fil = threading.Thread(target=sans_contexte)
            fil.start()
            fil.join()

        assert resultats == [None, False]
        assert journal.total == 0

    def test_ecritures_concurrentes_ne_perdent_aucun_compte(self):
        """Producteur et lecteur ne sont pas sur le même thread ; c'est la
        cohérence entre « combien » et « lesquels » qui fait la valeur du
        carnet."""
        journal = JournalOutils(max_appels=1000)

        def travail(indice: int):
            for i in range(50):
                journal.noter(_ok(f"outil_{indice}_{i}"))

        fils = [threading.Thread(target=travail, args=(n,)) for n in range(8)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join()

        assert journal.total == 400
        assert journal.reussites == 400
        assert len(journal.appels) == 400
        assert journal.notes_perdues == 0


# ---------------------------------------------------------------------------
# 5. La forme courte, celle que le site d'exécution utilisera
# ---------------------------------------------------------------------------


class TestNoterAppel:

    def test_elle_note_la_meme_chose_que_la_forme_longue(self):
        with journal_outils() as journal:
            noter_appel("memory_search", ok=False, extrait="Outil inconnu", ms=3)
        (appel,) = journal.appels
        assert appel.nom == "memory_search"
        assert appel.ok is False
        assert appel.extrait == "Outil inconnu"
        assert appel.ms == 3.0

    def test_elle_accepte_un_extrait_non_textuel(self):
        """Un handler MCP rend un dict ; le site d'exécution ne doit pas avoir
        à le formater pour tracer."""
        with journal_outils() as journal:
            noter_appel("files_analyze_image", ok=False, extrait={"isError": True})
        assert "isError" in journal.appels[0].extrait

    def test_elle_ne_leve_pas_sur_un_nom_absurde(self):
        with journal_outils() as journal:
            assert noter_appel(None) is True  # type: ignore[arg-type]
        assert journal.total == 1
