"""Ce que la trousse d'un acte de conscience garantit.

Chaque test épingle une **propriété**, jamais une valeur d'ambiance : le
module remplace `_pick_relevant_modules`, dont le défaut n'était pas un
mauvais chiffre mais un silence — une trousse vide et un prompt qui annonçait
tout. Les tests sont donc écrits contre ce silence.

Aucune base, aucun registre : le module est pur et le poids des modules lui
est injecté. Un test qui aurait besoin de `module_manager` mesurerait quels
modules tournent sur la machine qui l'exécute, pas la politique déclarée.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from dataclasses import FrozenInstanceError

import pytest

from conscience import trousse as t
from conscience.trousse import (
    CURIOSITE,
    SOCIAL,
    SOCLE,
    Trousse,
    TrousseTuning,
    modules_pour_source,
    preparer,
    resume_capacites,
    souhaits,
)


def poids_fixe(valeur: int):
    """Un `poids` qui rend la même chose pour tous — la forme la plus neutre."""
    return lambda nom: valeur


def poids_par_nom(table: dict[str, int], defaut: int = 0):
    return lambda nom: table.get(nom, defaut)


# ── B1 : un acte endogène ne part jamais les mains vides ──────────────────


class TestSocleInconditionnel:

    def test_sans_source_ni_pulsion_le_socle_est_quand_meme_la(self):
        """Le défaut d'origine : les cinq déclencheurs les plus fréquents
        (inactivité, salutation, humeur, pulsion, rumination) ne créent
        aucune Observation, donc l'ancienne dérivation rendait []."""
        trousse = preparer(poids=poids_fixe(100))
        assert list(trousse.modules) == SOCLE

    def test_le_socle_est_en_tete_quoi_qu_il_arrive(self):
        trousse = preparer(
            sources=["email", "rss"],
            demandes=["forge"],
            poids=poids_fixe(10),
        )
        assert list(trousse.modules)[: len(SOCLE)] == SOCLE

    def test_le_socle_passe_meme_s_il_depasse_le_plafond_a_lui_seul(self):
        """Le couper, c'est retomber sur B1 par une autre porte."""
        trousse = preparer(
            poids=poids_fixe(50_000),
            tuning=TrousseTuning(plafond_caracteres=10),
        )
        assert list(trousse.modules) == SOCLE
        assert trousse.ecartes == ()

    def test_le_socle_est_une_liste_pas_un_tuple(self):
        """La garde AST de `test_config_rapatriement` compare
        `item.default == repli` : `["a"] != ("a",)`. Un tuple ici casserait
        la suite le jour de la déclaration, très loin de sa cause."""
        for constante in (SOCLE, CURIOSITE, SOCIAL):
            assert isinstance(constante, list)


# ── B2 : une source n'est pas un nom de module ────────────────────────────


class TestSourcesQuiNeSontPasDesModules:

    @pytest.mark.parametrize(
        "source",
        ["frontend", "telegram", "pipeline", "conscience", "wake", "web_connect"],
    )
    def test_un_emetteur_qui_n_est_pas_un_module_n_ouvre_rien(self, source):
        """`Observation.source` vaut `event.source_module` ; ces noms-là
        n'existent pas au registre et `tools_for` les jetait sans un mot."""
        assert modules_pour_source(source) == ()
        trousse = preparer(sources=[source], poids=poids_fixe(10))
        assert list(trousse.modules) == SOCLE

    def test_une_source_de_module_ouvre_bien_son_module(self):
        assert modules_pour_source("email") == ("email",)
        trousse = preparer(sources=["email"], poids=poids_fixe(10))
        assert "email" in trousse.modules

    def test_une_source_forgee_se_coupe_sur_le_slash(self):
        """Le host relaie sous `forge/<app>` ; ce sont les outils du host qui
        servent à lire l'app, l'app n'en expose aucun."""
        assert modules_pour_source("forge/agenda") == ("forge",)
        assert modules_pour_source("forge/mon-app/bizarre") == ("forge",)

    def test_une_source_inconnue_du_registre_est_comptee_pas_avalee(self):
        """C'est tout le correctif : un nom qui ne mène à rien doit être
        visible quelque part."""
        trousse = preparer(
            sources=["discord"],
            poids=poids_fixe(10),
            disponibles=SOCLE,
        )
        assert "discord" in trousse.inconnus
        assert "discord" not in trousse.modules
        assert "discord" not in trousse.ecartes

    def test_sans_registre_fourni_rien_n_est_declare_inconnu(self):
        """`disponibles=None` veut dire « je ne sais pas qui est enregistré » :
        inventer un verdict dans ce cas serait pire que de s'abstenir."""
        trousse = preparer(sources=["discord"], poids=poids_fixe(10))
        assert trousse.inconnus == ()
        assert "discord" in trousse.modules

    def test_les_trois_listes_sont_disjointes_et_exhaustives(self):
        voulus = souhaits(
            sources=["email", "discord", "frontend"],
            drives={"curiosity": 1.0, "social": 1.0},
            demandes=["forge"],
        )
        trousse = preparer(
            sources=["email", "discord", "frontend"],
            drives={"curiosity": 1.0, "social": 1.0},
            demandes=["forge"],
            poids=poids_fixe(3000),
            disponibles=SOCLE + CURIOSITE + SOCIAL + ["email", "forge"],
        )
        classes = list(trousse.modules) + list(trousse.ecartes) + list(trousse.inconnus)
        assert sorted(classes) == sorted(voulus)
        assert len(classes) == len(set(classes))


# ── H1 : la pulsion doit ouvrir quelque chose, pas juste pousser un score ─


class TestPulsions:

    def test_sous_la_porte_une_pulsion_n_elargit_rien(self):
        porte = TrousseTuning().porte_pulsion
        trousse = preparer(
            drives={"curiosity": porte - 0.01, "social": porte - 0.01},
            poids=poids_fixe(10),
        )
        assert list(trousse.modules) == SOCLE

    def test_au_dessus_de_la_porte_la_curiosite_ouvre_de_quoi_trouver_un_sujet(self):
        """H1 : la pulsion montait, poussait le score, produisait une phrase —
        et rien ne choisissait jamais de sujet."""
        trousse = preparer(
            drives={"curiosity": TrousseTuning().porte_pulsion},
            poids=poids_fixe(10),
        )
        for nom in CURIOSITE:
            assert nom in trousse.modules

    def test_social_et_curiosite_sont_independantes(self):
        trousse = preparer(drives={"social": 1.0}, poids=poids_fixe(10))
        for nom in SOCIAL:
            assert nom in trousse.modules
        for nom in CURIOSITE:
            assert nom not in trousse.modules

    def test_la_porte_se_calibre_sous_le_plafond_heuristique_de_l_interprete(self):
        """`PERTINENCE_RSS_MATCHED` (0.55) plafonne le chemin sans LLM : une
        porte au-dessus serait une porte qu'aucun signal heuristique ne
        franchit, c'est-à-dire une porte fermée."""
        from conscience.interpreter import PERTINENCE_RSS_MATCHED

        assert TrousseTuning().porte_pulsion < PERTINENCE_RSS_MATCHED

    def test_les_pulsions_se_lisent_sous_leurs_deux_formes(self):
        """Le moteur passe `drive_engine.states` : clés `DriveKind`, valeurs
        `DriveState`. Une transcription de plus entre ce qui est mesuré et ce
        qui décide est une occasion de dérive de plus."""
        from drives.state import DriveKind, DriveState

        etats = {DriveKind.CURIOSITY: DriveState(kind=DriveKind.CURIOSITY, tension=0.9)}
        trousse = preparer(drives=etats, poids=poids_fixe(10))
        for nom in CURIOSITE:
            assert nom in trousse.modules

    def test_une_pulsion_illisible_vaut_repos_et_ne_leve_pas(self):
        """Chemin chaud, boucle non supervisée : élargir dans le doute coûte
        du prompt, lever tue la boucle pour la vie du process."""
        trousse = preparer(drives={"curiosity": object()}, poids=poids_fixe(10))
        assert list(trousse.modules) == SOCLE


# ── Le plafond ────────────────────────────────────────────────────────────


class TestPlafond:

    def test_le_plafond_se_consomme_module_par_module_jamais_outil_par_outil(self):
        """Une demi-trousse est un piège : `send_email` sans
        `list_recent_emails` fait conclure au modèle qu'il peut écrire à
        l'aveugle. Donc le poids retenu est toujours une somme de poids
        entiers de modules."""
        poids = {"conscience_tools": 1000, "memory_tools": 900, "email": 2000, "rss": 400}
        trousse = preparer(
            sources=["email", "rss"],
            poids=poids_par_nom(poids),
            tuning=TrousseTuning(plafond_caracteres=2500),
        )
        assert trousse.caracteres == sum(poids[n] for n in trousse.modules)

    def test_ce_qui_ne_tient_pas_est_ecarte_pas_tronque(self):
        trousse = preparer(
            sources=["email"],
            poids=poids_par_nom({"email": 9999}, defaut=100),
            tuning=TrousseTuning(plafond_caracteres=1000),
        )
        assert "email" in trousse.ecartes
        assert "email" not in trousse.modules

    def test_un_petit_module_passe_derriere_un_gros_refuse(self):
        """Sinon un seul module obèse affame en silence tout ce qui le suit."""
        trousse = preparer(
            sources=["forge", "rss"],
            poids=poids_par_nom(
                {"conscience_tools": 100, "memory_tools": 100,
                 "forge": 9000, "rss": 300},
            ),
            tuning=TrousseTuning(plafond_caracteres=1000),
        )
        assert "forge" in trousse.ecartes
        assert "rss" in trousse.modules

    def test_un_poids_illisible_fait_ecarter_plutot_que_supposer_gratuit(self):
        """Zéro voudrait dire « ne coûte rien » et ferait passer sous le
        plafond un module dont on ne sait rien."""
        def poids(nom):
            if nom == "email":
                raise RuntimeError("module arrêté")
            return 100

        trousse = preparer(sources=["email"], poids=poids)
        assert "email" in trousse.ecartes
        assert trousse.caracteres == 200

    def test_le_plafond_par_defaut_laisse_passer_le_socle_largement(self):
        """Mesures du dépôt : socle 2 919 caractères de déclaration, dix
        modules 20 559. Le plafond doit trancher entre les deux, franchement
        du côté du socle."""
        socle_mesure = 2919
        tous_mesures = 20559
        plafond = TrousseTuning().plafond_caracteres
        assert plafond > 2 * socle_mesure
        assert plafond < tous_mesures

    def test_preparer_ne_leve_jamais_sur_des_entrees_absurdes(self):
        """C4 : rien ne supervise la boucle de décision."""
        trousse = preparer(
            sources=[None, "", "forge/", 42],
            drives={None: None},
            demandes=[None, "  "],
            poids=poids_fixe(10),
        )
        assert isinstance(trousse, Trousse)
        assert list(trousse.modules)[: len(SOCLE)] == SOCLE


# ── L'ordre voulu ─────────────────────────────────────────────────────────


class TestSouhaits:

    def test_dedupliqué_en_gardant_le_rang_le_plus_fort(self):
        voulus = souhaits(
            sources=["memory_tools", "email"],
            demandes=["email"],
        )
        assert len(voulus) == len(set(voulus))
        # `email` est demandé ET source : il garde le rang de la demande.
        assert voulus.index("email") < voulus.index("conscience_tools") + len(SOCLE) + 1

    def test_l_ordre_suit_le_rang_declare_et_ne_bouge_pas(self):
        """L'ordre EST la politique de priorité, donc il s'épingle.

        La version précédente comparait ``souhaits(**args) == souhaits(**args)``
        : deux appels identiques dans le même processus, ce qui ne pouvait
        échouer que sur un itérateur d'ensemble — et l'ordre d'itération d'un
        ``set`` est stable à insertion égale, donc l'assertion ne mesurait
        pratiquement rien. Surtout, elle ne disait rien de l'ordre *voulu*,
        alors que c'est lui qui décide qui survit sous plafond serré :
        socle → demandes → sources → pulsions.
        """
        args = dict(
            sources=["rss", "email", "forge/x"],
            drives={"curiosity": 1.0, "social": 1.0},
            demandes=["files"],
        )
        voulus = souhaits(**args)

        # Le socle d'abord, dans son ordre déclaré.
        assert voulus[: len(SOCLE)] == list(SOCLE)
        # Puis l'intention formée (une demande explicite), avant tout le reste.
        assert voulus[len(SOCLE)] == "files"
        # Puis les sources, dans l'ordre où elles sont arrivées…
        assert voulus.index("rss") < voulus.index("email") < voulus.index("forge")
        # …et les pulsions en dernier : `identity_tools` n'est ouvert que par
        # SOCIAL, il doit donc fermer la marche derrière toutes les sources.
        assert voulus.index("forge") < voulus.index("identity_tools")
        # Aucun doublon : `email` est à la fois source et extension SOCIAL.
        assert len(voulus) == len(set(voulus))
        # Et c'est reproductible : rien ne dépend d'un état de processus.
        assert souhaits(**args) == voulus

    def test_une_demande_explicite_prime_sur_une_pulsion(self):
        """Une action programmée qui nomme un module est une intention déjà
        formée ; une pulsion est une humeur. Sous plafond serré, c'est cet
        ordre qui décide qui survit."""
        voulus = souhaits(demandes=["forge"], drives={"curiosity": 1.0})
        assert voulus.index("forge") < voulus.index(CURIOSITE[0])


# ── B3 : le prompt ne promet plus ce qu'il ne fournit pas ─────────────────


class TestBlocEnMain:

    def test_une_trousse_vide_le_dit_au_lieu_de_se_taire(self):
        """Taire la trousse vide est ce qui produisait des réponses où elle
        annonce un envoi de mail qui n'a jamais eu lieu."""
        bloc = Trousse().bloc_en_main()
        assert bloc
        assert "aucun outil" in bloc.lower()

    def test_le_bloc_nomme_exactement_les_modules_retenus(self):
        trousse = preparer(sources=["email"], poids=poids_fixe(10))
        bloc = trousse.bloc_en_main()
        for nom in trousse.modules:
            assert nom in bloc

    def test_le_bloc_borne_explicitement_le_tour(self):
        bloc = preparer(poids=poids_fixe(10)).bloc_en_main(["memory_search"])
        assert "memory_search" in bloc
        assert "ce tour" in bloc.lower()


class TestResumeCapacites:

    def test_il_ne_nomme_jamais_un_outil_individuel(self):
        """Un nom d'outil est un nom appelable : le poser sans fournir la
        déclaration, c'est inviter un appel qui échouera en silence (M2)."""
        trousse = preparer(
            sources=["email"],
            poids=poids_par_nom({"email": 9999}, defaut=10),
            tuning=TrousseTuning(plafond_caracteres=100),
        )
        bloc = resume_capacites(trousse, {"email": "Lire et envoyer des mails"})
        assert "email" in bloc
        for outil in ("send_email", "list_recent_emails", "trigger_wake"):
            assert outil not in bloc

    def test_il_n_annonce_aucun_moyen_d_ouvrir_ce_qu_il_nomme(self):
        """Le piège : aucun outil d'intention n'existe dans le dépôt. Dire
        « demande-les et tu les auras » serait B3 d'un cran au-dessus."""
        trousse = Trousse(modules=("memory_tools",), ecartes=("email", "rss"))
        bloc = resume_capacites(trousse).lower()
        for promesse in ("charge", "active", "ouvre-", "demande-les", "réclame"):
            assert promesse not in bloc

    def test_il_ne_nomme_jamais_un_module_deja_en_main(self):
        """Les deux blocs ne doivent pas se contredire dans le même prompt."""
        trousse = Trousse(modules=("memory_tools", "email"), ecartes=())
        bloc = resume_capacites(trousse, disponibles=["email", "rss"])
        assert "rss" in bloc
        assert "email" not in bloc

    def test_rien_ailleurs_ne_produit_aucun_bloc(self):
        trousse = Trousse(modules=("memory_tools",))
        assert resume_capacites(trousse, disponibles=["memory_tools"]) == ""

    def test_il_lit_les_deux_formes_de_capacites(self):
        """`collect_capabilities()` rend `{module: [ModuleCapability]}` ; une
        table de phrases est plus commode à écrire. Les deux passent, pour que
        le branchement côté moteur tienne en une ligne."""
        from modules.types import ModuleCapability

        trousse = Trousse(modules=(), ecartes=("email",))
        depuis_objets = resume_capacites(
            trousse, {"email": [ModuleCapability(description="Lire des mails")]},
        )
        depuis_texte = resume_capacites(trousse, {"email": "Lire des mails"})
        assert "Lire des mails" in depuis_objets
        assert "Lire des mails" in depuis_texte


# ── Pureté et calibration déclarée ────────────────────────────────────────


class TestPurete:

    def test_le_module_n_importe_ni_registre_ni_configuration(self):
        """C2 : un test qui lirait la configuration mesurerait la base de la
        machine qui l'exécute. Et le module doit rester importable sans
        registre d'applications Django."""
        source = pathlib.Path(t.__file__).read_text(encoding="utf-8")
        arbre = ast.parse(source)
        importes = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                importes.update(a.name for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                importes.add(noeud.module)
        for interdit in ("modules.manager", "configs.service", "configs.runtime",
                         "django.db", "conscience.models"):
            assert interdit not in importes

    def test_aucune_lecture_de_configuration(self):
        source = inspect.getsource(t)
        for appel in ("cfg_int(", "cfg_float(", "cfg_bool(", "cfg_str(",
                      "cfg_list(", "config_service"):
            assert appel not in source

    def test_le_reglage_est_gele_et_ses_defauts_sont_les_constantes(self):
        reglage = TrousseTuning()
        assert reglage.plafond_caracteres == t.PLAFOND_CARACTERES
        assert reglage.porte_pulsion == t.PORTE_PULSION
        with pytest.raises(FrozenInstanceError):
            reglage.plafond_caracteres = 1

    def test_la_trousse_est_gelee(self):
        # `FrozenInstanceError` et non `Exception` : sur une dataclasse gelée,
        # une faute de frappe dans le nom du champ lèverait elle aussi, et le
        # test passerait sans jamais avoir touché au gel.
        trousse = Trousse()
        with pytest.raises(FrozenInstanceError):
            trousse.modules = ("x",)

    def test_les_emetteurs_non_modules_sont_declares_explicitement(self):
        """Les mapper vers rien EST le correctif : « on connaît cette source,
        elle n'ouvre rien » n'est pas la même chose que « on ne la connaît
        pas », et seule la seconde doit remonter dans `inconnus`."""
        for source in ("frontend", "telegram", "pipeline", "conscience", "wake"):
            assert source in t._SOURCES_VERS_MODULES
            assert t._SOURCES_VERS_MODULES[source] == ()


# ── Le module est pur, mais les noms qu'il cite doivent exister ───────────


class TestLesNomsCitesExistent:
    """Le seul point où la pureté laisse passer une faute de frappe.

    `SOCLE`, `CURIOSITE`, `SOCIAL` et la table des sources nomment des modules
    en dur. Un module pur ne peut pas lire le registre pour les vérifier — ce
    serait la lecture que `TestPurete` interdit — donc rien, jusqu'ici, ne
    disait qu'un nom mal orthographié partait silencieusement dans
    `Trousse.inconnus` au lieu d'ouvrir sa trousse.

    Ces deux tests font la vérification **depuis les tests**, où lire le
    registre est légitime : le module reste pur, et une faute de frappe devient
    rouge ici plutôt qu'invisible en production.

    On passe par `registry.all_registered()`, un dictionnaire en mémoire peuplé
    à l'initialisation des applications, et **pas** par `list_all()` : ce
    dernier lit `ModuleState` en base, ce qui imposerait `django_db` à un
    fichier qui se veut sans base. La distinction n'est pas cosmétique — c'est
    la même que celle que le module fait entre « enregistré » et « qui
    tourne ».
    """

    @staticmethod
    def _enregistres() -> set[str]:
        from modules.manager import module_manager

        return {m.name for m in module_manager.registry.all_registered()}

    def test_le_socle_et_les_extensions_nomment_des_modules_reels(self):
        declares = set(SOCLE) | set(CURIOSITE) | set(SOCIAL)
        assert declares <= self._enregistres()

    def test_la_table_des_sources_ne_cible_que_des_modules_reels(self):
        cibles = {m for v in t._SOURCES_VERS_MODULES.values() for m in v}
        assert cibles <= self._enregistres()
