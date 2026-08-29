"""« Choisir ce qu'elle a envie de faire, aller au bout, en garder trace. »

Quatre câblages qui manquaient pour que la boucle de vie fonctionne en agent :

1. **La trousse d'un chantier se fige à l'ouverture** (`Graine.modules` →
   `Travail.modules` → demandes du pas). Sans ça, la trousse d'un pas se
   dérivait de la tension de pulsion du moment — que le premier pas réussi
   fait retomber (`on_act` assouvit la curiosité de 0.5) : le chantier
   perdait ses mains en cours de route.
2. **Une action programmée nomme ses modules** (`ScheduledAction.modules`),
   et l'acte qui l'honore les charge en demande explicite. Le paramètre
   `demandes` de la trousse n'avait aucun appelant.
3. **Un acte endogène peut choisir un destinataire** : le signal se lit sur
   les ruminations quand aucune observation n'existe, et les personnes
   présentes restent candidates quand la mémoire ne désigne personne.
4. **Un chantier abouti laisse un souvenir**, et les chantiers vivent dans le
   prompt (`--- CE QUE TU AS EN TRAIN ---`).

`transaction=True` sur les classes qui écrivent : les écritures passent par
`sync_to_async` sur un thread d'exécuteur, hors de la transaction de test.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone as tz

from conscience.types import DecisionContext


def _engine():
    from conscience.engine import ConscienceEngine

    e = ConscienceEngine.__new__(ConscienceEngine)
    e._threshold = 0.5
    return e


def _ctx(**kw) -> DecisionContext:
    base = dict(
        pending_observations=[], global_mood="curious", global_intensity=0.3,
        idle_seconds=600, in_cooldown=False, max_pertinence=0.0,
        weighted_urgency=0.0,
    )
    base.update(kw)
    return DecisionContext(**base)


class _Obs:
    """Une Observation réduite à ce que la récolte lui demande."""

    def __init__(self, pk=1, source="rss", pertinence=0.6,
                 resume="un article sur les modèles de diffusion", themes=()):
        self.pk = pk
        self.source = source
        self.pertinence = pertinence
        self.summary = resume
        self.themes = list(themes)
        self.raw_data = {"themes": list(themes)}


# ---------------------------------------------------------------------------
# 1a. La graine emporte ses modules (module pur)
# ---------------------------------------------------------------------------


class TestGraineEmporteSesModules:

    def test_une_observation_emporte_le_module_de_sa_source(self):
        from conscience.conduite import recolter_graines

        graines = recolter_graines(observations=[_Obs(source="rss")])
        assert graines[0].modules == ("rss",)

    def test_une_source_qui_n_est_pas_un_module_n_emporte_rien(self):
        """`frontend` est un canal, pas un module : la table de traduction le
        dit explicitement, et la graine ne doit pas transporter un nom que le
        registre ne servira jamais."""
        from conscience.conduite import recolter_graines

        graines = recolter_graines(observations=[_Obs(source="frontend")])
        assert graines[0].modules == ()

    def test_la_curiosite_emporte_ses_surfaces_d_exploration(self):
        """Figées à la récolte : c'est ce qui survit à la retombée de la
        pulsion après le premier pas réussi."""
        from conscience.conduite import CURIOSITE, recolter_graines

        graines = recolter_graines(pulsions=[("curiosity", 0.9)])
        assert graines[0].modules == tuple(CURIOSITE)

    def test_l_expression_part_avec_le_socle_seul(self):
        from conscience.conduite import recolter_graines

        graines = recolter_graines(pulsions=[("expression", 0.9)])
        assert graines[0].modules == ()

    def test_une_pensee_n_emporte_rien(self):
        from conscience.conduite import recolter_graines

        graines = recolter_graines(
            pensees=[{"id": 3, "summary": "le concert", "intensity": 0.6}]
        )
        assert graines[0].modules == ()


# ---------------------------------------------------------------------------
# 1b. Le pas recharge la trousse du chantier, pas l'humeur du moment
# ---------------------------------------------------------------------------


class TestTrousseDuChantier:

    def _moteur(self, disponibles):
        e = _engine()
        e._poids_module = lambda nom: 100
        e._modules_enregistres = lambda: list(disponibles)
        return e

    def test_le_chantier_garde_ses_mains_pulsion_retombee(self):
        """Le scénario exact du défaut : curiosité à zéro (le premier pas
        l'a assouvie), et le chantier RSS doit quand même repartir avec
        `rss` — parce que c'est LE CHANTIER qui le demande."""
        e = self._moteur(["conscience_tools", "memory_tools", "rss"])
        row = SimpleNamespace(modules=["rss"])
        with patch("conscience.engine.drive_engine") as de:
            de.states = {}
            trousse = e._preparer_trousse_travail(row)
        assert "rss" in trousse.modules
        assert "conscience_tools" in trousse.modules
        assert "memory_tools" in trousse.modules

    def test_un_module_fantome_est_compte_pas_charge(self):
        e = self._moteur(["conscience_tools", "memory_tools"])
        row = SimpleNamespace(modules=["fantome"])
        with patch("conscience.engine.drive_engine") as de:
            de.states = {}
            trousse = e._preparer_trousse_travail(row)
        assert "fantome" not in trousse.modules
        assert "fantome" in trousse.inconnus

    def test_un_chantier_sans_trousse_part_avec_le_socle(self):
        """Les lignes d'avant la migration ont `modules=[]` : le pas doit
        se comporter exactement comme avant le lot."""
        e = self._moteur(["conscience_tools", "memory_tools"])
        row = SimpleNamespace(modules=[])
        with patch("conscience.engine.drive_engine") as de:
            de.states = {}
            trousse = e._preparer_trousse_travail(row)
        assert set(trousse.modules) == {"conscience_tools", "memory_tools"}


# ---------------------------------------------------------------------------
# 2. Les actions programmées passent leurs modules en demande explicite
# ---------------------------------------------------------------------------


class TestDemandesDesActionsProgrammees:

    def test_une_action_due_charge_les_modules_qu_elle_nomme(self):
        e = _engine()
        e._poids_module = lambda nom: 100
        e._modules_enregistres = lambda: [
            "conscience_tools", "memory_tools", "email",
        ]
        action = SimpleNamespace(prompt="vérifier mes mails", modules=["email"])
        ctx = _ctx(scheduled_actions=[action])
        with patch("conscience.engine.drive_engine") as de:
            de.states = {}
            trousse = e._preparer_trousse(ctx)
        assert "email" in trousse.modules

    def test_une_vieille_action_sans_champ_ne_casse_rien(self):
        """`getattr(..., None)` : une ligne d'avant la migration, ou un stub
        de test, n'a pas l'attribut."""
        e = _engine()
        e._poids_module = lambda nom: 100
        e._modules_enregistres = lambda: ["conscience_tools", "memory_tools"]
        action = SimpleNamespace(prompt="dire bonjour")  # pas de .modules
        ctx = _ctx(scheduled_actions=[action])
        with patch("conscience.engine.drive_engine") as de:
            de.states = {}
            trousse = e._preparer_trousse(ctx)
        assert set(trousse.modules) == {"conscience_tools", "memory_tools"}


@pytest.mark.django_db(transaction=True)
class TestOutilScheduleActionModules:

    async def test_l_outil_persiste_les_modules_nettoyes(self):
        from conscience.models import ScheduledAction
        from conscience.module import ConscienceToolsModule

        m = ConscienceToolsModule()
        await m._tool_schedule_action({
            "prompt": "vérifier mes mails",
            "delay_minutes": 10,
            "modules": ["email", " rss ", "", "a", "b", "c", "d"],
        })
        row = await sync_to_async(
            lambda: ScheduledAction.objects.latest("created_at")
        )()
        # Nettoyés, et bornés à 5 : un argument de modèle n'est jamais cru
        # sur parole.
        assert row.modules[:2] == ["email", "rss"]
        assert len(row.modules) <= 5

    async def test_sans_argument_le_champ_reste_vide(self):
        from conscience.models import ScheduledAction
        from conscience.module import ConscienceToolsModule

        m = ConscienceToolsModule()
        await m._tool_schedule_action({
            "prompt": "dire bonjour", "delay_minutes": 5,
        })
        row = await sync_to_async(
            lambda: ScheduledAction.objects.latest("created_at")
        )()
        assert row.modules == []


# ---------------------------------------------------------------------------
# 3. Le destinataire d'un acte endogène
# ---------------------------------------------------------------------------


class TestDestinataireEndogene:

    def _memoire(self, candidats):
        return SimpleNamespace(who_is_concerned=AsyncMock(return_value=candidats))

    async def test_les_ruminations_font_signal_quand_rien_n_est_observe(self):
        """Les cinq déclencheurs endogènes ne créent aucune Observation : le
        signal doit alors se lire sur ce qui lui trotte dans la tête."""
        e = _engine()
        e.memory = self._memoire([
            {"name": "Thomas",
             "handles": [{"person_id": "web_1", "channel": "web"}]},
        ])
        ctx = _ctx(rumination_lignes=[
            {"id": 1, "summary": "le concert de Thomas", "intensity": 0.6},
        ])
        with patch(
            "ai.client.ai_client.complete",
            new=AsyncMock(return_value="[TO:web_1]"),
        ):
            cible = await e._select_recipient(ctx)
        assert cible == "web_1"
        signal = e.memory.who_is_concerned.await_args.args[0]
        assert "concert" in signal

    async def test_une_personne_presente_reste_candidate(self):
        """Quand la mémoire ne désigne personne, saluer qui est là plutôt que
        parler dans le vide. La tuyauterie interne et les sockets anonymes ne
        sont pas des personnes à saluer."""
        e = _engine()
        e.memory = self._memoire([])
        presents = [
            SimpleNamespace(person_id="conscience_mika", channel="web",
                            kind="consumer", display_name=""),
            SimpleNamespace(person_id="anon_42", channel="web",
                            kind="consumer", display_name=""),
            SimpleNamespace(person_id="web_42", channel="web",
                            kind="consumer", display_name="Adrien"),
        ]
        with patch(
            "communication.presence.presence_registry.reachable",
            return_value=presents,
        ), patch(
            "ai.client.ai_client.complete",
            new=AsyncMock(return_value="[TO:web_42]"),
        ) as complete:
            ctx = _ctx(rumination_lignes=[
                {"id": 1, "summary": "envie de parler", "intensity": 0.5},
            ])
            cible = await e._select_recipient(ctx)
        assert cible == "web_42"
        # La passe de confirmation n'a vu QUE la personne identifiable.
        prompt_envoye = complete.await_args.kwargs["user_prompt"]
        assert "web_42" in prompt_envoye
        assert "anon_42" not in prompt_envoye
        assert "conscience_mika" not in prompt_envoye

    async def test_personne_nulle_part_aucun_appel_llm(self):
        e = _engine()
        e.memory = self._memoire([])
        with patch(
            "communication.presence.presence_registry.reachable",
            return_value=[],
        ), patch(
            "ai.client.ai_client.complete", new=AsyncMock(),
        ) as complete:
            cible = await e._select_recipient(_ctx())
        assert cible is None
        complete.assert_not_awaited()

    async def test_le_dernier_mot_reste_au_modele(self):
        """`[TO:none]` est une réponse valide : la présence propose, elle
        n'impose pas."""
        e = _engine()
        e.memory = self._memoire([])
        presents = [SimpleNamespace(person_id="web_42", channel="web",
                                    kind="consumer", display_name="Adrien")]
        with patch(
            "communication.presence.presence_registry.reachable",
            return_value=presents,
        ), patch(
            "ai.client.ai_client.complete",
            new=AsyncMock(return_value="[TO:none]"),
        ):
            assert await e._select_recipient(_ctx()) is None


# ---------------------------------------------------------------------------
# 4a. Un chantier abouti laisse un souvenir
# ---------------------------------------------------------------------------


VERDICT_FINI = (
    "J'ai lu les trois articles et j'en retiens deux idées.\n\n"
    "--- VERDICT ---\n"
    '{"etat": "fini", "resume": "trois articles lus", "motif": "", "delai_s": 0}\n'
    "--- FIN VERDICT ---"
)


async def _travail(**kw):
    from conscience.models import Travail

    champs = dict(
        titre="lire ce qui se dit sur les modèles de diffusion",
        origine=Travail.Origine.OBSERVATION, reference="7",
        envie=0.8, ancre_envie=tz.now(), pas_max=3,
    )
    champs.update(kw)
    return await sync_to_async(Travail.objects.create)(**champs)


@pytest.mark.django_db(transaction=True)
class TestChantierAboutiLaisseUnSouvenir:

    @pytest.fixture(autouse=True)
    def _purger(self):
        from conscience.models import Rumination, Travail
        Travail.objects.all().delete()
        Rumination.objects.all().delete()
        yield
        Travail.objects.all().delete()
        Rumination.objects.all().delete()

    async def test_fini_memorise_titre_et_essence(self):
        from conscience.verdict import lire_verdict

        row = await _travail()
        e = _engine()
        e.memory = SimpleNamespace(remember_completed_work=AsyncMock())
        verdict = lire_verdict(VERDICT_FINI)
        await e._appliquer_verdict(row.pk, verdict, "trois articles lus", "")

        e.memory.remember_completed_work.assert_awaited_once()
        titre, essence = e.memory.remember_completed_work.await_args.args
        assert titre == row.titre
        assert essence == "trois articles lus"

    async def test_un_pas_intermediaire_ne_memorise_rien(self):
        from conscience.verdict import lire_verdict

        row = await _travail()
        e = _engine()
        e.memory = SimpleNamespace(remember_completed_work=AsyncMock())
        verdict = lire_verdict('--- VERDICT ---\n{"etat": "continue"}\n--- FIN VERDICT ---')
        await e._appliquer_verdict(row.pk, verdict, "j'avance", "")
        e.memory.remember_completed_work.assert_not_awaited()

    async def test_le_pont_compose_un_souvenir_premiere_personne(self):
        from conscience.memory_bridge import MemoryBridge

        bridge = MemoryBridge()
        with patch("memory.manager.memory_manager") as mm:
            mm.create_souvenir = AsyncMock()
            await bridge.remember_completed_work(
                "lire les news", "deux idées retenues",
            )
        contenu = mm.create_souvenir.await_args.kwargs["content"]
        assert contenu.startswith("J'ai mené au bout")
        assert "lire les news" in contenu
        assert "deux idées retenues" in contenu
        assert mm.create_souvenir.await_args.kwargs["emotion"] == "proud"

    async def test_un_titre_vide_ne_fabrique_pas_de_souvenir(self):
        from conscience.memory_bridge import MemoryBridge

        bridge = MemoryBridge()
        with patch("memory.manager.memory_manager") as mm:
            mm.create_souvenir = AsyncMock()
            assert await bridge.remember_completed_work("", "essence") is None
        mm.create_souvenir.assert_not_awaited()


# ---------------------------------------------------------------------------
# 4a-bis. Attendre n'est plus un cul-de-sac
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestAttenteAvecEcheance:
    """Le verdict ATTENDRE posait `en_attente_de_reponse` que rien ne relevait
    jamais, et `delai_s` — soigneusement borné par le lecteur — n'avait aucun
    consommateur : « attendre » signifiait « se faner jusqu'à l'abandon »."""

    @pytest.fixture(autouse=True)
    def _purger(self):
        from conscience.models import Travail
        Travail.objects.all().delete()
        yield
        Travail.objects.all().delete()

    async def test_attendre_pose_le_drapeau_et_son_echeance(self):
        from conscience.verdict import lire_verdict

        row = await _travail()
        e = _engine()
        avant = tz.now()
        verdict = lire_verdict("Je repasse plus tard. [SUITE:attendre:600]")
        await e._appliquer_verdict(row.pk, verdict, "je repasse", "")

        row = await sync_to_async(type(row).objects.get)(pk=row.pk)
        assert row.en_attente_de_reponse is True
        assert row.reprendre_le is not None
        ecart = (row.reprendre_le - avant).total_seconds()
        assert 590 <= ecart <= 660

    async def test_l_echeance_passee_le_chantier_redevient_candidat(self):
        from datetime import timedelta

        row = await _travail(
            en_attente_de_reponse=True,
            reprendre_le=tz.now() - timedelta(seconds=5),
        )
        e = _engine()
        vivants, _ = await e._travaux_en_cours(tz.now())
        assert vivants[0].en_attente_de_reponse is False
        row = await sync_to_async(type(row).objects.get)(pk=row.pk)
        assert row.en_attente_de_reponse is False
        assert row.reprendre_le is None

    async def test_avant_l_echeance_l_attente_tient(self):
        from datetime import timedelta

        await _travail(
            en_attente_de_reponse=True,
            reprendre_le=tz.now() + timedelta(hours=1),
        )
        e = _engine()
        vivants, _ = await e._travaux_en_cours(tz.now())
        assert vivants[0].en_attente_de_reponse is True

    async def test_un_drapeau_sans_echeance_est_releve(self):
        """Les lignes d'avant la migration — le cul-de-sac historique — se
        débloquent au premier passage plutôt que de se faner."""
        await _travail(en_attente_de_reponse=True, reprendre_le=None)
        e = _engine()
        vivants, _ = await e._travaux_en_cours(tz.now())
        assert vivants[0].en_attente_de_reponse is False


# ---------------------------------------------------------------------------
# 4b. Les chantiers vivent dans le prompt
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestBlocTravauxDansLePrompt:

    @pytest.fixture(autouse=True)
    def _purger(self):
        from conscience.models import Travail
        Travail.objects.all().delete()
        yield
        Travail.objects.all().delete()

    async def test_en_cours_et_abouti_du_jour(self):
        from pipeline.context import _fetch_travaux_context

        await _travail(pas_effectues=2, pas_max=3)
        await _travail(
            titre="réparer mon application « meteo »",
            statut="aboutie",
        )
        bloc = await _fetch_travaux_context()
        assert "modèles de diffusion" in bloc
        assert "presque au bout" in bloc
        assert "mene au bout aujourd'hui" in bloc
        assert "meteo" in bloc

    async def test_sans_chantier_le_bloc_est_vide(self):
        from pipeline.context import _fetch_travaux_context

        assert await _fetch_travaux_context() == ""

    async def test_aucun_nombre_machine_dans_le_bloc(self):
        """Même règle que le bloc identité : le prompt dit un état, jamais un
        couple (valeur, ancre) que la décroissance rend faux une seconde
        plus tard."""
        await _travail(envie=0.8, pas_effectues=1, pas_max=5)
        from pipeline.context import _fetch_travaux_context

        bloc = await _fetch_travaux_context()
        assert "0.8" not in bloc
        assert "1/5" not in bloc

    def test_la_couche_est_rendue_sous_son_entete(self):
        from pipeline.context import ConversationContext
        from pipeline.prompt import build_system_prompt

        rendu = build_system_prompt(
            ConversationContext(travaux_context="<travaux>")
        )
        assert "--- CE QUE TU AS EN TRAIN ---" in rendu
        assert "<travaux>" in rendu


# ---------------------------------------------------------------------------
# 1c. L'ouverture persiste la trousse
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestOuvertureFigeLaTrousse:

    @pytest.fixture(autouse=True)
    def _purger(self):
        from conscience.models import Travail
        Travail.objects.all().delete()
        yield
        Travail.objects.all().delete()

    async def test_les_modules_de_la_graine_sont_ecrits(self):
        from conscience.conduite import Graine
        from conscience.models import Travail

        e = _engine()
        graine = Graine(
            origine="pulsion", reference="rss:un titre",
            intitule="lire ce qui se dit sur un titre", poids=0.7,
            modules=("rss",),
        )
        assert await e._ouvrir_travail(graine)
        row = await sync_to_async(Travail.objects.latest)("created_at")
        assert row.modules == ["rss"]


# ---------------------------------------------------------------------------
# 5. La forge propose ses applications cassées
# ---------------------------------------------------------------------------


class TestForgeProposeSujets:

    def test_les_apps_cassees_deviennent_des_sujets(self):
        from modules.plugins.forge.module import ForgeModule

        m = ForgeModule.__new__(ForgeModule)
        m._load_errors = {"meteo": "SyntaxError: invalid syntax"}
        m._breaker_notified = {"radio"}
        sujets = m.propose_sujets()
        assert any("meteo" in s and "réparer" in s for s in sujets)
        assert any("radio" in s for s in sujets)

    def test_une_app_cassee_des_deux_facons_n_apparait_qu_une_fois(self):
        from modules.plugins.forge.module import ForgeModule

        m = ForgeModule.__new__(ForgeModule)
        m._load_errors = {"meteo": "boom"}
        m._breaker_notified = {"meteo"}
        assert sum("meteo" in s for s in m.propose_sujets()) == 1

    def test_rien_de_casse_rien_a_proposer(self):
        from modules.plugins.forge.module import ForgeModule

        m = ForgeModule.__new__(ForgeModule)
        m._load_errors = {}
        m._breaker_notified = set()
        assert m.propose_sujets() == []


class TestEmailProposeSujets:

    def test_le_courrier_en_attente_est_un_sujet(self):
        """Même source RAM que `get_context` : lisible depuis la boucle."""
        from modules.plugins.email.module import EmailModule

        m = EmailModule.__new__(EmailModule)
        m._unread_counts = {"perso": 3, "boulot": 0}
        sujets = m.propose_sujets()
        assert len(sujets) == 1
        assert "perso" in sujets[0] and "3" in sujets[0]

    def test_boite_vide_rien_a_proposer(self):
        from modules.plugins.email.module import EmailModule

        m = EmailModule.__new__(EmailModule)
        m._unread_counts = {}
        assert m.propose_sujets() == []
