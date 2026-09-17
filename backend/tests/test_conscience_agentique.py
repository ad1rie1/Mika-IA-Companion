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
        with patch("conscience.travaux.drive_engine") as de:
            de.states = {}
            trousse = e._preparer_trousse_travail(row)
        assert "rss" in trousse.modules
        assert "conscience_tools" in trousse.modules
        assert "memory_tools" in trousse.modules

    def test_un_module_fantome_est_compte_pas_charge(self):
        e = self._moteur(["conscience_tools", "memory_tools"])
        row = SimpleNamespace(modules=["fantome"])
        with patch("conscience.travaux.drive_engine") as de:
            de.states = {}
            trousse = e._preparer_trousse_travail(row)
        assert "fantome" not in trousse.modules
        assert "fantome" in trousse.inconnus

    def test_un_chantier_sans_trousse_part_avec_le_socle(self):
        """Les lignes d'avant la migration ont `modules=[]` : le pas doit
        se comporter exactement comme avant le lot."""
        e = self._moteur(["conscience_tools", "memory_tools"])
        row = SimpleNamespace(modules=[])
        with patch("conscience.travaux.drive_engine") as de:
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
        with patch("conscience.acte.drive_engine") as de:
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
        with patch("conscience.acte.drive_engine") as de:
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

    async def test_la_liste_montre_les_outils_promis(self):
        """Sans eux dans la liste, elle ne peut pas relire ce qu'elle s'est
        promis d'avoir en main quand le rendez-vous sonnera."""
        from conscience.module import ConscienceToolsModule

        m = ConscienceToolsModule()
        await m._tool_schedule_action({
            "prompt": "vérifier mes mails", "delay_minutes": 10,
            "modules": ["email"],
        })
        reponse = await m._tool_list_scheduled({})
        texte = reponse["content"][0]["text"]
        assert "outils: email" in texte

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
        return SimpleNamespace(
            who_is_concerned=AsyncMock(return_value=candidats),
            who_misses_contact=AsyncMock(return_value=[]),
        )

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

    async def test_un_handle_module_n_est_pas_une_presence(self):
        """`reachable()` contient aussi les handles Telegram, réinscrits à
        chaque boot : les compter « présents » court-circuiterait le manque
        en permanence — le propriétaire serait « là » à chaque acte, sans
        rythme ni anti-double-texte. Présent = un socket vivant."""
        e = _engine()
        e.memory = self._memoire([])
        module_handle = SimpleNamespace(
            person_id="tg_9", channel="telegram", kind="module",
            display_name="Adrien",
        )
        with patch(
            "communication.presence.presence_registry.reachable",
            return_value=[module_handle],
        ), patch(
            "ai.client.ai_client.complete", new=AsyncMock(),
        ) as complete:
            cible = await e._select_recipient(_ctx())
        assert cible is None
        complete.assert_not_awaited()
        # C'est bien le maillon du manque qui a eu la main, pas la présence.
        e.memory.who_misses_contact.assert_awaited_once()

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

    async def test_fini_se_ressent_pas_seulement_se_memorise(self):
        """Sans l'impulsion, le souvenir disait « proud » pendant que le
        visage et l'humeur n'en savaient rien — se souvenir d'avoir été
        fière sans l'avoir jamais été."""
        from conscience.verdict import lire_verdict
        from emotion.types import Emotion

        row = await _travail()
        e = _engine()
        e.memory = SimpleNamespace(remember_completed_work=AsyncMock())
        verdict = lire_verdict(VERDICT_FINI)
        with patch("conscience.travaux.emotion_engine") as moteur:
            await e._appliquer_verdict(row.pk, verdict, "trois articles lus", "")
        moteur.process_emotion.assert_called_once()
        data, personne = moteur.process_emotion.call_args.args
        assert data.emotion is Emotion.PROUD
        assert personne == "conscience_mika"

    async def test_un_pas_intermediaire_ne_ressent_rien(self):
        from conscience.verdict import lire_verdict

        row = await _travail()
        e = _engine()
        e.memory = SimpleNamespace(remember_completed_work=AsyncMock())
        verdict = lire_verdict('--- VERDICT ---\n{"etat": "continue"}\n--- FIN VERDICT ---')
        with patch("conscience.travaux.emotion_engine") as moteur:
            await e._appliquer_verdict(row.pk, verdict, "j'avance", "")
        moteur.process_emotion.assert_not_called()

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
# 3-bis. Reprendre des nouvelles de qui lui manque
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestQuiLuiManque:
    """Le manque v2 : le silence se mesure au rythme propre du lien, elle
    pense à UNE personne, préfère les proches au fond chaud, et ne
    double-texte jamais. La date du dernier échange se lit sur `Message` via
    les handles, jamais sur `PersonProfile.last_interaction_at` (écrit à la
    régénération de fiche seulement — « sans nouvelles depuis 12 jours » à
    propos de quelqu'un qui a écrit hier rend le personnage bête)."""

    @pytest.fixture(autouse=True)
    def _purger(self):
        from conscience.models import Rumination
        from memory.models import Conversation, Entity, Message, PersonProfile
        for model in (Message, Conversation, PersonProfile, Entity, Rumination):
            model.objects.all().delete()
        yield
        for model in (Message, Conversation, PersonProfile, Entity, Rumination):
            model.objects.all().delete()

    async def _amie(self, nom="Alice", closeness="friend"):
        from memory.models import Entity, PersonProfile

        entity = await sync_to_async(Entity.objects.create)(
            name=nom, entity_type="person",
        )
        await sync_to_async(PersonProfile.objects.create)(
            entity=entity, closeness=closeness,
        )
        return entity

    async def _messages(self, person_id, jours, role="user"):
        """Un message par entrée de `jours` (en jours d'ancienneté)."""
        from datetime import timedelta

        from memory.models import Conversation, Message

        conv = await sync_to_async(Conversation.objects.create)()
        for il_y_a in jours:
            msg = await sync_to_async(Message.objects.create)(
                conversation=conv, role=role, content="salut",
                person_id=person_id,
            )
            # `created_at` est auto_now_add : on antidate par update().
            await sync_to_async(
                lambda pk=msg.pk, j=il_y_a: Message.objects.filter(pk=pk).update(
                    created_at=tz.now() - timedelta(days=j),
                )
            )()

    def _handles(self, mapping):
        return AsyncMock(return_value={
            nom: [{"person_id": pid, "channel": "telegram", "kind": "module"}]
            for nom, pid in mapping.items()
        })

    async def test_une_amie_silencieuse_est_candidate_avec_sa_note(self):
        """Historique trop mince pour un rythme mesuré → repli ami (7 j),
        facteur 1.5 → 12 jours de silence manquent."""
        from conscience.memory_bridge import MemoryBridge

        await self._amie("Alice")
        await self._messages("tg_9", [12])
        bridge = MemoryBridge()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._handles({"Alice": "tg_9"}),
        ):
            candidats = await bridge.who_misses_contact()
        assert len(candidats) == 1
        assert candidats[0]["name"] == "Alice"
        assert "12 jour" in candidats[0]["note"]

    async def test_un_echange_recent_ne_manque_pas(self):
        from conscience.memory_bridge import MemoryBridge

        await self._amie("Alice")
        await self._messages("tg_9", [1])
        bridge = MemoryBridge()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._handles({"Alice": "tg_9"}),
        ):
            assert await bridge.who_misses_contact() == []

    async def test_jamais_parle_rien_a_reprendre(self):
        from conscience.memory_bridge import MemoryBridge

        await self._amie("Alice")
        bridge = MemoryBridge()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._handles({"Alice": "tg_9"}),
        ):
            assert await bridge.who_misses_contact() == []

    async def test_une_simple_connaissance_n_est_pas_relancee(self):
        """« Reprendre des nouvelles » suppose une relation : les fiches
        `stranger`/`acquaintance` ne sont pas des gens qu'on relance."""
        from conscience.memory_bridge import MemoryBridge

        await self._amie("Bob", closeness="acquaintance")
        await self._messages("tg_7", [30])
        bridge = MemoryBridge()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._handles({"Bob": "tg_7"}),
        ):
            assert await bridge.who_misses_contact() == []

    async def test_le_rythme_du_lien_decide_pas_un_seuil_global(self):
        """Le cœur du modèle : même silence, deux verdicts. Alice écrivait
        tous les jours — 6 jours de silence, elle manque. Bob écrit toutes
        les trois semaines — 20 jours de silence, c'est son rythme normal."""
        from conscience.memory_bridge import MemoryBridge

        await self._amie("Alice")
        await self._messages("tg_a", list(range(6, 16)))   # 10 jours actifs, écart 1
        await self._amie("Bob")
        await self._messages("tg_b", [60, 40, 20])         # écart médian 20

        bridge = MemoryBridge()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._handles({"Alice": "tg_a", "Bob": "tg_b"}),
        ):
            candidats = await bridge.who_misses_contact(n=5)
        assert [c["name"] for c in candidats] == ["Alice"]

    async def test_on_pense_a_une_personne_la_plus_proche(self):
        """n=1 par défaut, et la proche gagne : repli 3 j contre 7 j, plus le
        poids de closeness — au même silence, c'est à elle qu'on pense."""
        from conscience.memory_bridge import MemoryBridge

        await self._amie("Alice", closeness="friend")
        await self._messages("tg_a", [12])
        await self._amie("Carla", closeness="close")
        await self._messages("tg_c", [12])

        bridge = MemoryBridge()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._handles({"Alice": "tg_a", "Carla": "tg_c"}),
        ):
            candidats = await bridge.who_misses_contact()
        assert [c["name"] for c in candidats] == ["Carla"]

    async def test_elle_ne_double_texte_pas(self):
        """Son dernier message est resté sans réponse : la personne n'est
        re-proposée qu'après un silence bien plus long (facteur × relance),
        jamais le lendemain."""
        from conscience.memory_bridge import MemoryBridge

        await self._amie("Alice")
        await self._messages("tg_9", [50])                     # elle a reçu, il y a 50 j
        await self._messages("tg_9", [2], role="assistant")    # elle a relancé avant-hier

        bridge = MemoryBridge()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._handles({"Alice": "tg_9"}),
        ):
            assert await bridge.who_misses_contact() == []

    async def test_apres_un_vrai_moment_elle_peut_retenter(self):
        """La relance ignorée n'exile pas pour toujours : passé
        rythme × facteur × relance (7 × 1.5 × 3 = 31.5 j), elle peut y
        repenser."""
        from conscience.memory_bridge import MemoryBridge

        await self._amie("Alice")
        await self._messages("tg_9", [50])
        await self._messages("tg_9", [40], role="assistant")

        bridge = MemoryBridge()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._handles({"Alice": "tg_9"}),
        ):
            candidats = await bridge.who_misses_contact()
        assert [c["name"] for c in candidats] == ["Alice"]

    async def test_son_propre_brief_ne_compte_pas_comme_un_mot_recu(self):
        """Le brief interne d'un acte adressé à Alice est un `role="user"`
        sous SON person_id : sans l'exclusion `is_internal`, le ping de Mika
        remettrait le silence à zéro — « sans nouvelles depuis 2 jours »
        à propos de quelqu'un muet depuis 50."""
        from datetime import timedelta

        from memory.models import Conversation, Message
        from conscience.memory_bridge import MemoryBridge

        await self._amie("Alice")
        await self._messages("tg_9", [50])          # son vrai dernier mot
        # Le brief d'un acte d'avant-hier, machinerie sous son person_id.
        conv = await sync_to_async(Conversation.objects.create)()
        brief = await sync_to_async(Message.objects.create)(
            conversation=conv, role="user", content="[brief interne]",
            person_id="tg_9", is_internal=True,
        )
        await sync_to_async(
            lambda: Message.objects.filter(pk=brief.pk).update(
                created_at=tz.now() - timedelta(days=2),
            )
        )()

        bridge = MemoryBridge()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._handles({"Alice": "tg_9"}),
        ):
            candidats = await bridge.who_misses_contact()
        assert len(candidats) == 1
        assert "50 jour" in candidats[0]["note"]

    async def test_le_manque_hors_d_atteinte_devient_une_pensee(self):
        """Une amie qui manque mais n'a aucun handle joignable ne s'évapore
        plus : « j'aimerais avoir des nouvelles d'Alice » devient une
        rumination — dicible à qui EST là, sous la porte de graine (pas de
        chantier pour un injoignable)."""
        from conscience.memory_bridge import MemoryBridge
        from conscience.models import Rumination

        await self._amie("Alice")
        await self._messages("web_9", [12])
        bridge = MemoryBridge()
        handles = AsyncMock(return_value={
            # kind consumer et personne connectée : hors d'atteinte.
            "Alice": [{"person_id": "web_9", "channel": "web",
                       "kind": "consumer"}],
        })
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=handles,
        ):
            candidats = await bridge.who_misses_contact()
        assert candidats == []
        pensee = await sync_to_async(
            lambda: Rumination.objects.filter(status="active").first()
        )()
        assert pensee is not None
        assert "Alice" in pensee.summary and "12 jour" in pensee.summary
        assert pensee.emotion == "nostalgic"
        assert pensee.intensity < 0.40  # sous la porte de graine

    async def test_la_pensee_pour_un_absent_ne_se_repete_pas(self):
        from conscience.memory_bridge import MemoryBridge
        from conscience.models import Rumination

        bridge = MemoryBridge()
        assert await bridge._penser_a_l_absent("Alice", 12) is True
        assert await bridge._penser_a_l_absent("Alice", 13) is False
        n = await sync_to_async(
            lambda: Rumination.objects.filter(status="active").count()
        )()
        assert n == 1

    async def test_le_fond_chaud_departage(self):
        """« Plus on aime bien quelqu'un, plus on a envie de lui parler À
        ELLE » : à silence et closeness égaux, l'ancre affective chaude
        l'emporte."""
        from conscience.memory_bridge import MemoryBridge

        await self._amie("Tiede", closeness="friend")
        await self._messages("tg_t", [12])
        await self._amie("Chaude", closeness="friend")
        await self._messages("tg_c", [12])

        # La chaleur est lue par ``emotion_engine.chaleur_envers`` (la
        # composante plaisir de l'ancre, dans [0, 1]) — le même bord que la
        # divulgation graduée du tour.
        faux_moteur = SimpleNamespace(
            chaleur_envers=AsyncMock(side_effect=lambda pid: 0.8 if pid == "tg_c" else 0.0),
        )
        bridge = MemoryBridge()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._handles({"Tiede": "tg_t", "Chaude": "tg_c"}),
        ), patch("emotion.engine.emotion_engine", faux_moteur):
            candidats = await bridge.who_misses_contact(n=2)
        assert [c["name"] for c in candidats] == ["Chaude", "Tiede"]

    async def test_le_manque_est_le_troisieme_maillon(self):
        """Chaîne complète : mémoire vide, personne présente → l'amie qui
        manque est proposée, sa note dans le prompt, et le modèle tranche."""
        e = _engine()
        e.memory = SimpleNamespace(
            who_is_concerned=AsyncMock(return_value=[]),
            who_misses_contact=AsyncMock(return_value=[{
                "name": "Alice", "score": 1.4,
                "handles": [{"person_id": "tg_9", "channel": "telegram",
                             "kind": "module"}],
                "note": "sans nouvelles depuis 12 jour(s)",
            }]),
        )
        with patch(
            "communication.presence.presence_registry.reachable",
            return_value=[],
        ), patch(
            "ai.client.ai_client.complete",
            new=AsyncMock(return_value="[TO:tg_9]"),
        ) as complete:
            ctx = _ctx(rumination_lignes=[
                {"id": 1, "summary": "envie de compagnie", "intensity": 0.5},
            ])
            cible = await e._select_recipient(ctx)
        assert cible == "tg_9"
        prompt_envoye = complete.await_args.kwargs["user_prompt"]
        assert "sans nouvelles depuis 12 jour(s)" in prompt_envoye


class TestIntentionParPulsion:
    """Le murmure d'un débordement SOCIAL disait « aller voir quelque chose
    de nouveau » — une envie d'explorer au moment précis où elle voulait
    quelqu'un. L'intention se spécialise par la pulsion dominante."""

    def _ctx_pulsion(self, e, nom, tension=0.9):
        from drives.state import DriveKind

        kind = DriveKind(nom)
        etat = SimpleNamespace(tension=tension)
        patcher = patch("conscience.intention.drive_engine")
        de = patcher.start()
        de.pulsion_saillante.return_value = kind
        de.states = {kind: etat}
        return patcher, _ctx()

    def test_social_veut_quelqu_un(self):
        e = _engine()
        patcher, ctx = self._ctx_pulsion(e, "social")
        try:
            assert e._intention_de_lacte(ctx) == "reprendre des nouvelles de quelqu'un"
        finally:
            patcher.stop()

    def test_la_curiosite_garde_son_intention_d_avant(self):
        e = _engine()
        patcher, ctx = self._ctx_pulsion(e, "curiosity")
        try:
            assert e._intention_de_lacte(ctx) == "aller voir quelque chose de nouveau"
        finally:
            patcher.stop()


class TestAnticipation:
    """Le futur cesse d'être un calendrier sans affect : un chantier à un pas
    du bout ou un rendez-vous proche et prioritaire glissent vers l'espoir."""

    def _moteur(self):
        e = _engine()
        e._dernier_espoir = 0.0
        return e

    def _chantier_presque_fini(self):
        from conscience.conduite import TravailEnCours

        return TravailEnCours(
            identifiant=1, titre="lire les news", envie=0.6,
            pas_effectues=4, pas_max=5,
        )

    async def test_un_chantier_presque_au_bout_donne_de_l_espoir(self):
        from emotion.types import Emotion

        e = self._moteur()
        with patch("conscience.affects.emotion_engine") as moteur:
            await e._peut_etre_esperer(_ctx(), [self._chantier_presque_fini()])
        data, personne = moteur.process_emotion.call_args.args
        assert data.emotion is Emotion.HOPEFUL
        assert personne == "conscience_mika"

    async def test_un_rendez_vous_proche_et_prioritaire_aussi(self):
        from emotion.types import Emotion

        e = self._moteur()
        e._get_upcoming_actions = AsyncMock(return_value=[
            (SimpleNamespace(priority=0.9, prompt="appeler"), 30),
        ])
        with patch("conscience.affects.emotion_engine") as moteur:
            await e._peut_etre_esperer(_ctx(), [])
        data, _ = moteur.process_emotion.call_args.args
        assert data.emotion is Emotion.HOPEFUL

    async def test_un_pense_bete_lointain_ou_tiede_ne_fait_rien(self):
        e = self._moteur()
        e._get_upcoming_actions = AsyncMock(return_value=[
            (SimpleNamespace(priority=0.9, prompt="loin"), 300),
            (SimpleNamespace(priority=0.3, prompt="tiede"), 10),
        ])
        with patch("conscience.affects.emotion_engine") as moteur:
            await e._peut_etre_esperer(_ctx(), [])
        moteur.process_emotion.assert_not_called()

    async def test_un_chantier_en_attente_n_espere_pas(self):
        """Presque au bout mais bloqué sur quelqu'un : ce n'est pas de
        l'espoir, c'est de l'attente — déjà couverte ailleurs."""
        from conscience.conduite import TravailEnCours

        e = self._moteur()
        e._get_upcoming_actions = AsyncMock(return_value=[])
        gele = TravailEnCours(
            identifiant=1, titre="t", envie=0.6,
            pas_effectues=4, pas_max=5, en_attente_de_reponse=True,
        )
        with patch("conscience.affects.emotion_engine") as moteur:
            await e._peut_etre_esperer(_ctx(), [gele])
        moteur.process_emotion.assert_not_called()

    async def test_l_espoir_est_espace(self):
        e = self._moteur()
        with patch("conscience.affects.emotion_engine") as moteur:
            await e._peut_etre_esperer(_ctx(), [self._chantier_presque_fini()])
            await e._peut_etre_esperer(_ctx(), [self._chantier_presque_fini()])
        assert moteur.process_emotion.call_count == 1


class TestGigueDuCooldown:
    """Un métronome se remarque : la gigue, tirée une fois par acte,
    désynchronise les relances sans jamais dépasser le plafond."""

    def _moteur(self):
        e = _engine()
        e._cooldown_seconds = 300
        return e

    def test_la_gigue_s_applique_au_silence(self):
        e = self._moteur()
        e._gigue_cooldown = 1.2
        assert e._effective_cooldown(0) == 300 * 1.2

    def test_le_plafond_reste_une_promesse(self):
        e = self._moteur()
        e._gigue_cooldown = 1.5
        assert e._effective_cooldown(50) == e._COOLDOWN_MAX_S

    def test_le_tirage_reste_dans_l_amplitude(self):
        e = self._moteur()
        for _ in range(20):
            e._tirer_gigue_cooldown()
            assert 0.85 <= e._gigue_cooldown <= 1.15

    def test_sans_tirage_l_exactitude_historique_tient(self):
        """Attribut de classe à 1.0 : un moteur construit par `__new__` —
        comme tous ceux des tests existants — garde les valeurs exactes."""
        e = self._moteur()
        assert e._effective_cooldown(0) == 300.0


class TestEnnuiEtSolitude:
    """Le vide prolongé a une couleur — et pas la même selon ce qui manque :
    rien à faire → `bored` ; quelqu'un (SOCIAL haut) → `lonely`, que la vie
    interne ne produisait nulle part. S'ennuyer n'est pas se sentir seule."""

    def _moteur(self):
        e = _engine()
        e._dernier_ennui = 0.0
        return e

    async def _vide(self, e, ctx, travaux=(), social=0.1):
        """Un tour de vide avec la tension SOCIAL contrôlée."""
        from drives.state import DriveKind

        with patch("conscience.affects.emotion_engine") as moteur, patch(
            "conscience.affects.drive_engine",
        ) as de:
            de.states = {DriveKind.SOCIAL: SimpleNamespace(tension=social)}
            await e._peut_etre_s_ennuyer(ctx, travaux=list(travaux))
        return moteur

    async def test_le_vide_sans_manque_social_glisse_vers_l_ennui(self):
        from emotion.types import Emotion

        e = self._moteur()
        moteur = await self._vide(e, _ctx(idle_seconds=3 * 3600), social=0.1)
        data, personne = moteur.process_emotion.call_args.args
        assert data.emotion is Emotion.BORED
        assert personne == "conscience_mika"

    async def test_le_vide_avec_envie_de_compagnie_est_de_la_solitude(self):
        from emotion.types import Emotion

        e = self._moteur()
        moteur = await self._vide(e, _ctx(idle_seconds=3 * 3600), social=0.8)
        data, personne = moteur.process_emotion.call_args.args
        assert data.emotion is Emotion.LONELY
        assert personne == "conscience_mika"

    async def test_travailler_n_est_pas_s_ennuyer(self):
        e = self._moteur()
        moteur = await self._vide(e, _ctx(idle_seconds=3 * 3600), travaux=[object()])
        moteur.process_emotion.assert_not_called()

    async def test_dormir_n_est_pas_s_ennuyer(self):
        e = self._moteur()
        moteur = await self._vide(
            e, _ctx(idle_seconds=3 * 3600, sleep_phase="deep_sleep"),
        )
        moteur.process_emotion.assert_not_called()

    async def test_le_vide_teinte_il_ne_matraque_pas(self):
        """Une impulsion par dix minutes au plus — pas une par tour de 30 s."""
        from drives.state import DriveKind

        e = self._moteur()
        ctx = _ctx(idle_seconds=3 * 3600)
        with patch("conscience.affects.emotion_engine") as moteur, patch(
            "conscience.affects.drive_engine",
        ) as de:
            de.states = {DriveKind.SOCIAL: SimpleNamespace(tension=0.1)}
            await e._peut_etre_s_ennuyer(ctx, travaux=[])
            await e._peut_etre_s_ennuyer(ctx, travaux=[])
        assert moteur.process_emotion.call_count == 1

    async def test_une_conversation_recente_n_ennuie_pas(self):
        e = self._moteur()
        moteur = await self._vide(e, _ctx(idle_seconds=600))
        moteur.process_emotion.assert_not_called()


@pytest.mark.django_db(transaction=True)
class TestLaCroyanceQuiSEffondre:
    """Cesser de croire coûte : la secousse (surprise) puis le résidu (une
    pensée confuse « je croyais que… ») — elle habite la transition au lieu
    d'affirmer une chose lundi et son contraire mardi sans un mot."""

    @pytest.fixture(autouse=True)
    def _purger(self):
        from conscience.models import Rumination
        Rumination.objects.all().delete()
        yield
        Rumination.objects.all().delete()

    async def test_la_revision_se_ressent_et_se_raconte(self):
        from conscience.memory_bridge import MemoryBridge
        from conscience.models import Rumination
        from emotion.types import Emotion

        bridge = MemoryBridge()
        with patch("emotion.engine.emotion_engine") as moteur:
            await bridge._ressentir_la_revision(
                "Thomas travaille chez Dassault",
            )
        data, personne = moteur.process_emotion.call_args.args
        assert data.emotion is Emotion.SURPRISED
        assert personne == "conscience_mika"

        pensee = await sync_to_async(
            lambda: Rumination.objects.filter(status="active").first()
        )()
        assert pensee is not None
        assert "Je croyais que" in pensee.summary
        assert "Dassault" in pensee.summary
        assert pensee.emotion == "confused"
        assert pensee.intensity < 0.40  # sous la porte de graine

    async def test_la_meme_revision_ne_se_rumine_pas_en_double(self):
        from conscience.memory_bridge import MemoryBridge
        from conscience.models import Rumination

        bridge = MemoryBridge()
        with patch("emotion.engine.emotion_engine"):
            await bridge._ressentir_la_revision("le ciel est vert")
            await bridge._ressentir_la_revision("le ciel est vert")
        n = await sync_to_async(
            lambda: Rumination.objects.filter(status="active").count()
        )()
        assert n == 1

    async def test_l_invalidation_declenche_le_ressenti(self):
        """Le câblage : `check_contradictions` appelle `_ressentir_la_revision`
        exactement quand une connaissance tombe."""
        import ast
        import inspect
        import textwrap

        from conscience.memory_bridge import MemoryBridge

        arbre = ast.parse(textwrap.dedent(
            inspect.getsource(MemoryBridge.check_contradictions)
        ))
        appels = {
            n.func.attr for n in ast.walk(arbre)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "_ressentir_la_revision" in appels
        assert "invalidate_connaissance" in appels


@pytest.mark.django_db(transaction=True)
class TestLEchecFaitMal:
    """L'asymétrie centrale du dossier psychologique : seul le FINI produisait
    un affect. Un blocage frustre ET devient une pensée (qui dérivera,
    saignera et sera digérée — la tuyauterie du regret existe) ; un abandon
    teinte de mélancolie, sans rumination : l'envie s'est éteinte
    d'elle-même, c'est sa définition."""

    @pytest.fixture(autouse=True)
    def _purger(self):
        from conscience.models import Rumination, Travail
        Travail.objects.all().delete()
        Rumination.objects.all().delete()
        yield
        Travail.objects.all().delete()
        Rumination.objects.all().delete()

    async def test_un_blocage_frustre_et_devient_une_pensee(self):
        from conscience.models import Rumination
        from conscience.verdict import lire_verdict
        from emotion.types import Emotion

        row = await _travail()
        e = _engine()
        verdict = lire_verdict(
            '--- VERDICT ---\n'
            '{"etat": "bloque", "motif": "il me manque la clef API"}\n'
            '--- FIN VERDICT ---'
        )
        with patch("conscience.travaux.emotion_engine") as moteur:
            await e._appliquer_verdict(row.pk, verdict, "je n'y arrive pas", "")

        data, personne = moteur.process_emotion.call_args.args
        assert data.emotion is Emotion.FRUSTRATED
        assert personne == "conscience_mika"

        pensee = await sync_to_async(
            lambda: Rumination.objects.filter(status="active").first()
        )()
        assert pensee is not None
        assert "Je bloque sur" in pensee.summary
        assert "clef API" in pensee.summary
        assert pensee.emotion == "frustrated"

    async def test_les_pas_epuises_frustrent_aussi(self):
        """Un CONTINUE sur le dernier pas bloque le chantier — même douleur
        que le blocage déclaré : le but est obstrué dans les deux cas."""
        from conscience.verdict import lire_verdict
        from emotion.types import Emotion

        row = await _travail(pas_effectues=3, pas_max=3)
        e = _engine()
        verdict = lire_verdict(
            '--- VERDICT ---\n{"etat": "continue"}\n--- FIN VERDICT ---'
        )
        with patch("conscience.travaux.emotion_engine") as moteur:
            await e._appliquer_verdict(row.pk, verdict, "encore un peu", "")
        data, _ = moteur.process_emotion.call_args.args
        assert data.emotion is Emotion.FRUSTRATED

    async def test_un_abandon_teinte_de_melancolie_sans_rumination(self):
        from datetime import timedelta

        from conscience.models import Rumination
        from emotion.types import Emotion

        await _travail(envie=0.05, ancre_envie=tz.now() - timedelta(hours=48))
        e = _engine()
        with patch("conscience.travaux.emotion_engine") as moteur:
            vivants, _ = await e._travaux_en_cours(tz.now())
        assert vivants == []
        data, personne = moteur.process_emotion.call_args.args
        assert data.emotion is Emotion.MELANCHOLIC
        assert personne == "conscience_mika"
        n = await sync_to_async(
            lambda: Rumination.objects.filter(status="active").count()
        )()
        assert n == 0

    async def test_un_pas_qui_continue_ne_fait_rien_ressentir(self):
        from conscience.verdict import lire_verdict

        row = await _travail()
        e = _engine()
        verdict = lire_verdict(
            '--- VERDICT ---\n{"etat": "continue"}\n--- FIN VERDICT ---'
        )
        with patch("conscience.travaux.emotion_engine") as moteur:
            await e._appliquer_verdict(row.pk, verdict, "j'avance", "")
        moteur.process_emotion.assert_not_called()


class TestNiveauDeRecit:
    """La table des confidences (`conscience/recit.py`, pure) : le degré de
    détail suit le lien, à la manière d'un humain — l'owner reçoit tout, le
    proche du même domaine aussi, l'ami la mention, l'inconnu rien."""

    def test_la_table_des_liens(self):
        from conscience.recit import NiveauRecit, niveau_de_recit

        assert niveau_de_recit(est_owner=True) is NiveauRecit.INTEGRAL
        assert niveau_de_recit(closeness="close", concerne=True) is NiveauRecit.INTEGRAL
        assert niveau_de_recit(closeness="close") is NiveauRecit.ESSENTIEL
        assert niveau_de_recit(closeness="friend", concerne=True) is NiveauRecit.ESSENTIEL
        assert niveau_de_recit(closeness="friend") is NiveauRecit.MENTION
        assert niveau_de_recit(closeness="acquaintance") is NiveauRecit.RIEN
        assert niveau_de_recit() is NiveauRecit.RIEN

    def test_la_mention_ne_fuit_jamais_le_contenu(self):
        """C'est la définition du niveau : le titre est ce qu'un ami reçoit,
        le contenu ne sort pas par un gabarit."""
        from conscience.recit import NiveauRecit, composer_recit

        texte = composer_recit(
            NiveauRecit.MENTION,
            dit="Alice m'a confié un secret que j'ai recoupé",
            resume="secret recoupé",
            titre="creuser un sujet",
        )
        assert "creuser un sujet" in texte
        assert "secret" not in texte

    def test_l_essentiel_prefere_le_resume_du_verdict(self):
        from conscience.recit import NiveauRecit, composer_recit

        texte = composer_recit(
            NiveauRecit.ESSENTIEL,
            dit="long journal de pas " * 30,
            resume="deux idées retenues",
            titre="lire les news",
        )
        assert "deux idées retenues" in texte
        assert "long journal" not in texte

    def test_l_integral_est_le_recit_complet(self):
        from conscience.recit import NiveauRecit, composer_recit

        assert composer_recit(
            NiveauRecit.INTEGRAL, dit="tout le récit", titre="t",
        ) == "tout le récit"


class TestRecitAdresse:
    """Un chantier fini notable est raconté à QUELQU'UN quand un lien le
    permet — persona SPEAKING, Telegram possible — et gradué selon le lien.
    Personne d'assez lié → le murmure global d'avant, mot pour mot."""

    def _confident(self, niveau, pid="tg_9"):
        from conscience.recit import NiveauRecit

        return {"person_id": pid, "channel": "telegram",
                "concerne": True, "niveau": NiveauRecit(niveau)}

    async def _dire(self, e, verdict_txt, confident):
        from conscience.verdict import lire_verdict

        verdict = lire_verdict(verdict_txt)
        with patch(
            "conscience.travaux._choisir_confident",
            new=AsyncMock(return_value=confident),
        ), patch(
            "pipeline.broadcast.broadcast_to_websocket", new=AsyncMock(),
        ) as diffusion:
            await e._peut_etre_dire_le_travail(
                verdict, "voilà ce que j'ai fait", "un titre", ("theme",),
            )
        return diffusion

    async def test_le_recit_part_vers_sa_personne(self):
        e = _engine()
        e._derniere_diffusion_travail = None
        diffusion = await self._dire(
            e,
            '--- VERDICT ---\n{"etat": "fini", "resume": "ok"}\n--- FIN VERDICT ---',
            self._confident("integral"),
        )
        diffusion.assert_awaited_once()
        assert diffusion.await_args.kwargs["person_id"] == "tg_9"
        sortie = diffusion.await_args.args[0]
        assert sortie.text == "voilà ce que j'ai fait"

    async def test_un_ami_recoit_la_mention_pas_le_contenu(self):
        e = _engine()
        e._derniere_diffusion_travail = None
        diffusion = await self._dire(
            e,
            '--- VERDICT ---\n{"etat": "fini", "resume": "secret"}\n--- FIN VERDICT ---',
            self._confident("mention"),
        )
        sortie = diffusion.await_args.args[0]
        assert "un titre" in sortie.text
        assert "voilà ce que j'ai fait" not in sortie.text

    async def test_sans_confident_le_murmure_global_d_avant(self):
        e = _engine()
        e._derniere_diffusion_travail = None
        diffusion = await self._dire(
            e,
            '--- VERDICT ---\n{"etat": "fini", "resume": "ok"}\n--- FIN VERDICT ---',
            None,
        )
        diffusion.assert_awaited_once()
        assert diffusion.await_args.kwargs["person_id"] is None
        assert diffusion.await_args.args[0].text == "voilà ce que j'ai fait"

    async def test_les_gardes_passent_avant_le_confident(self):
        """Un fini peu notable ne cherche même pas à qui parler : les gardes
        décident SI on raconte, le confident À QUI et COMBIEN."""
        from conscience.verdict import lire_verdict

        e = _engine()
        verdict = lire_verdict(
            '--- VERDICT ---\n{"etat": "fini", "notable": 0.2}\n--- FIN VERDICT ---'
        )
        with patch(
            "conscience.travaux._choisir_confident", new=AsyncMock(),
        ) as choix, patch(
            "pipeline.broadcast.broadcast_to_websocket", new=AsyncMock(),
        ) as diffusion:
            await e._peut_etre_dire_le_travail(verdict, "ok", "t", ())
        choix.assert_not_awaited()
        diffusion.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
class TestChoixDuConfident:
    """Owner > proche concerné > proche > ami concerné > ami ; un handle
    module quelconque n'entre jamais (surface de spam) sauf owner ou
    concerné par le sujet."""

    def _moteur(self, concernes=()):
        e = _engine()
        e.memory = SimpleNamespace(
            who_is_concerned=AsyncMock(return_value=list(concernes)),
        )
        return e

    async def test_l_owner_gagne_et_recoit_tout(self):
        from conscience.recit import NiveauRecit
        from conscience.travaux import _choisir_confident

        e = self._moteur()
        presents = [SimpleNamespace(person_id="tg_owner", channel="telegram",
                                    kind="module")]
        with patch(
            "communication.presence.presence_registry.reachable",
            return_value=presents,
        ), patch(
            "conscience.travaux._closeness_de",
            new=AsyncMock(return_value=""),
        ), patch(
            "modules.collectors.is_owner",
            side_effect=lambda pid: pid == "tg_owner",
        ):
            confident = await _choisir_confident(e, "un titre", ())
        assert confident["person_id"] == "tg_owner"
        assert confident["niveau"] is NiveauRecit.INTEGRAL

    async def test_un_module_non_owner_non_concerne_n_entre_pas(self):
        from conscience.travaux import _choisir_confident

        e = self._moteur()
        presents = [SimpleNamespace(person_id="tg_inconnu", channel="telegram",
                                    kind="module")]
        with patch(
            "communication.presence.presence_registry.reachable",
            return_value=presents,
        ), patch(
            "modules.collectors.is_owner", return_value=False,
        ):
            assert await _choisir_confident(e, "un titre", ()) is None

    async def test_le_concerne_du_meme_domaine_est_trouve(self):
        from conscience.recit import NiveauRecit
        from conscience.travaux import _choisir_confident

        e = self._moteur(concernes=[{
            "name": "Alice",
            "handles": [{"person_id": "tg_a", "channel": "telegram",
                         "kind": "module"}],
        }])
        with patch(
            "communication.presence.presence_registry.reachable",
            return_value=[],
        ), patch(
            "conscience.travaux._closeness_de",
            new=AsyncMock(return_value="friend"),
        ), patch(
            "modules.collectors.is_owner", return_value=False,
        ):
            confident = await _choisir_confident(e, "un titre", ("vrm",))
        assert confident["person_id"] == "tg_a"
        assert confident["niveau"] is NiveauRecit.ESSENTIEL

    async def test_une_simple_connaissance_ne_recoit_rien(self):
        from conscience.travaux import _choisir_confident

        e = self._moteur(concernes=[{
            "name": "Bob",
            "handles": [{"person_id": "tg_b", "channel": "telegram",
                         "kind": "module"}],
        }])
        with patch(
            "communication.presence.presence_registry.reachable",
            return_value=[],
        ), patch(
            "conscience.travaux._closeness_de",
            new=AsyncMock(return_value="acquaintance"),
        ), patch(
            "modules.collectors.is_owner", return_value=False,
        ):
            assert await _choisir_confident(e, "un titre", ()) is None


class TestNotabiliteDeLaDiffusion:
    """Un chantier fini n'est plus décrété notable d'office : le verdict
    peut se juger (« notable: 0.2 ») et finir en silence."""

    async def test_un_fini_juge_peu_notable_reste_muet(self):
        from conscience.verdict import lire_verdict

        e = _engine()
        verdict = lire_verdict(
            '--- VERDICT ---\n'
            '{"etat": "fini", "resume": "ok", "notable": 0.2}\n'
            '--- FIN VERDICT ---'
        )
        with patch(
            "pipeline.broadcast.broadcast_to_websocket", new=AsyncMock(),
        ) as diffusion:
            await e._peut_etre_dire_le_travail(verdict, "ok", "un titre")
        diffusion.assert_not_awaited()

    async def test_sans_avis_le_comportement_d_avant_tient(self):
        from conscience.verdict import lire_verdict

        e = _engine()
        e._derniere_diffusion_travail = None
        verdict = lire_verdict(
            '--- VERDICT ---\n{"etat": "fini", "resume": "ok"}\n--- FIN VERDICT ---'
        )
        with patch(
            "pipeline.broadcast.broadcast_to_websocket", new=AsyncMock(),
        ) as diffusion:
            await e._peut_etre_dire_le_travail(verdict, "ok", "un titre")
        diffusion.assert_awaited_once()


@pytest.mark.django_db(transaction=True)
class TestIntegrationAffective:
    """Les mocks prouvent l'appel ; ceci prouve que l'impulsion ATTERRIT
    dans la physique PAD — la symétrie affective mesurée sur un vrai moteur
    émotionnel, pas sur un bouchon."""

    @pytest.fixture(autouse=True)
    def _purger(self):
        from conscience.models import Rumination, Travail
        Travail.objects.all().delete()
        Rumination.objects.all().delete()
        yield
        Travail.objects.all().delete()
        Rumination.objects.all().delete()

    def _moteur_emotionnel(self):
        from tests.conftest import TEMPERAMENT_DEFAULT, _make_engine

        return _make_engine(TEMPERAMENT_DEFAULT)

    async def test_le_blocage_deplace_vraiment_l_humeur(self):
        from conscience.verdict import lire_verdict

        emo = self._moteur_emotionnel()
        row = await _travail()
        e = _engine()
        verdict = lire_verdict(
            '--- VERDICT ---\n{"etat": "bloque", "motif": "mur"}\n--- FIN VERDICT ---'
        )
        with patch("conscience.travaux.emotion_engine", emo):
            await e._appliquer_verdict(row.pk, verdict, "je bloque", "")

        # Sa position PAD envers elle-même a dérivé vers le négatif depuis
        # le repos : la frustration s'est réellement inscrite, elle ne s'est
        # pas perdue dans un appel bouchonné.
        position = emo.person_moods["conscience_mika"].dynamic.position
        assert position[0] < emo._home_vector()[0] - 0.05

    async def test_l_aboutissement_deplace_vers_le_positif(self):
        from conscience.verdict import lire_verdict

        emo = self._moteur_emotionnel()
        row = await _travail()
        e = _engine()
        e.memory = SimpleNamespace(remember_completed_work=AsyncMock())
        verdict = lire_verdict(
            '--- VERDICT ---\n{"etat": "fini", "resume": "ok"}\n--- FIN VERDICT ---'
        )
        with patch("conscience.travaux.emotion_engine", emo):
            await e._appliquer_verdict(row.pk, verdict, "voilà", "")
        position = emo.person_moods["conscience_mika"].dynamic.position
        assert position[0] > 0.05

    async def test_l_espoir_atterrit_aussi(self):
        from conscience.conduite import TravailEnCours

        emo = self._moteur_emotionnel()
        e = _engine()
        e._dernier_espoir = 0.0
        presque = TravailEnCours(
            identifiant=1, titre="t", envie=0.6, pas_effectues=4, pas_max=5,
        )
        with patch("conscience.affects.emotion_engine", emo):
            await e._peut_etre_esperer(_ctx(), [presque])
        position = emo.person_moods["conscience_mika"].dynamic.position
        assert position[0] > 0.02


@pytest.mark.django_db(transaction=True)
class TestLesAttentesSeRealisent:
    """L'embryon du modèle d'attentes : deux prédictions que le système
    tenait déjà — l'attente nominative, la pensée pour l'absent — se
    RESSENTENT enfin quand elles se réalisent, au lieu d'être des UPDATE."""

    @pytest.fixture(autouse=True)
    def _purger(self):
        from conscience.models import Rumination, Travail
        from memory.models import Conversation, Message
        for model in (Rumination, Travail, Message, Conversation):
            model.objects.all().delete()
        yield
        for model in (Rumination, Travail, Message, Conversation):
            model.objects.all().delete()

    async def _message(self, person_id, il_y_a_min=5, interne=False):
        from datetime import timedelta

        from memory.models import Conversation, Message

        conv = await sync_to_async(Conversation.objects.create)()
        msg = await sync_to_async(Message.objects.create)(
            conversation=conv, role="user", content="me revoilà",
            person_id=person_id, is_internal=interne,
        )
        await sync_to_async(
            lambda: Message.objects.filter(pk=msg.pk).update(
                created_at=tz.now() - timedelta(minutes=il_y_a_min),
            )
        )()

    async def _pensee_nostalgique(self, nom="Alice", il_y_a_min=60):
        from datetime import timedelta

        from conscience.models import Rumination

        r = await sync_to_async(Rumination.objects.create)(
            summary=f"J'aimerais bien avoir des nouvelles de {nom}.",
            themes=[nom], intensity=0.3, emotion="nostalgic", status="active",
        )
        await sync_to_async(
            lambda: Rumination.objects.filter(pk=r.pk).update(
                created_at=tz.now() - timedelta(minutes=il_y_a_min),
            )
        )()
        return r

    def _resolveur(self, mapping):
        return AsyncMock(return_value={
            nom: [{"person_id": pid, "channel": "telegram", "kind": "module"}]
            for nom, pid in mapping.items()
        })

    async def test_la_reponse_attendue_soulage(self):
        """L'attente nominative exaucée pulse `relieved` — « enfin »."""
        from datetime import timedelta

        from emotion.types import Emotion

        await _travail(
            en_attente_de_reponse=True,
            reprendre_le=tz.now() + timedelta(hours=6),
            attend_qui="Adrien",
            dernier_pas_le=tz.now() - timedelta(minutes=30),
        )
        await self._message("tg_9", il_y_a_min=5)
        e = _engine()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._resolveur({"Adrien": "tg_9"}),
        ), patch("conscience.travaux.emotion_engine") as moteur:
            await e._travaux_en_cours(tz.now())
        emotions = [c.args[0].emotion for c in moteur.process_emotion.call_args_list]
        assert Emotion.RELIEVED in emotions

    async def test_le_retour_d_un_absent_rejouit_et_resout(self):
        from conscience.models import Rumination
        from emotion.types import Emotion

        pensee = await self._pensee_nostalgique("Alice", il_y_a_min=60)
        await self._message("tg_a", il_y_a_min=5)
        e = _engine()
        e._dernier_retour_scan = 0.0
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._resolveur({"Alice": "tg_a"}),
        ), patch("conscience.ruminations.emotion_engine") as moteur:
            await e._le_retour_d_un_absent()
        data, personne = moteur.process_emotion.call_args.args
        assert data.emotion is Emotion.HAPPY
        assert personne == "conscience_mika"
        pensee = await sync_to_async(Rumination.objects.get)(pk=pensee.pk)
        assert pensee.status == "resolved"

    async def test_un_message_d_avant_la_pensee_n_est_pas_un_retour(self):
        from conscience.models import Rumination

        pensee = await self._pensee_nostalgique("Alice", il_y_a_min=30)
        await self._message("tg_a", il_y_a_min=60)
        e = _engine()
        e._dernier_retour_scan = 0.0
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._resolveur({"Alice": "tg_a"}),
        ), patch("conscience.ruminations.emotion_engine") as moteur:
            await e._le_retour_d_un_absent()
        moteur.process_emotion.assert_not_called()
        pensee = await sync_to_async(Rumination.objects.get)(pk=pensee.pk)
        assert pensee.status == "active"

    async def test_son_propre_brief_n_est_pas_le_retour(self):
        from conscience.models import Rumination

        pensee = await self._pensee_nostalgique("Alice", il_y_a_min=60)
        await self._message("tg_a", il_y_a_min=5, interne=True)
        e = _engine()
        e._dernier_retour_scan = 0.0
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._resolveur({"Alice": "tg_a"}),
        ), patch("conscience.ruminations.emotion_engine") as moteur:
            await e._le_retour_d_un_absent()
        moteur.process_emotion.assert_not_called()

    async def test_le_scan_est_etrangle(self):
        import time as _t

        e = _engine()
        e._dernier_retour_scan = _t.monotonic()
        with patch("conscience.ruminations.emotion_engine") as moteur:
            await e._le_retour_d_un_absent()
        moteur.process_emotion.assert_not_called()


class TestEstimeDeSoiPhysique:
    """La variable lente entre le tempérament (fixe) et l'humeur (rapide) :
    rappel vers 0.5 en demi-vie de 3 jours, coups petits et bornés — un seul
    échec ne fait pas une dépression, c'est l'accumulation qui compte."""

    def test_le_rappel_vers_le_neutre(self):
        from datetime import datetime, timedelta

        from conscience.estime import valeur_courante

        t0 = datetime(2026, 8, 30, 12, 0)
        # Après une demi-vie (72 h), la moitié de l'écart au neutre est rendue.
        assert valeur_courante(0.9, t0, t0 + timedelta(hours=72)) == pytest.approx(0.7)
        assert valeur_courante(0.1, t0, t0 + timedelta(hours=72)) == pytest.approx(0.3)

    def test_lire_ne_facture_rien(self):
        from datetime import datetime

        from conscience.estime import valeur_courante

        t0 = datetime(2026, 8, 30, 12, 0)
        assert valeur_courante(0.9, t0, t0) == 0.9

    def test_les_bornes_tiennent(self):
        from conscience.estime import PLAFOND, PLANCHER, _borner

        assert _borner(1.4) == PLAFOND
        assert _borner(-0.2) == PLANCHER

    def test_une_ancre_malformee_ne_tue_pas(self):
        from datetime import datetime

        from conscience.estime import valeur_courante

        assert valeur_courante(0.8, "pas une date", datetime.now()) == 0.8


@pytest.mark.django_db(transaction=True)
class TestEstimeDeSoiVecue:
    """Les coups s'accumulent, persistent, et colorent — sans jamais toucher
    le score de décision."""

    @pytest.fixture(autouse=True)
    def _purger(self):
        from conscience.models import EstimeDeSoi, Rumination, Travail
        for model in (EstimeDeSoi, Rumination, Travail):
            model.objects.all().delete()
        yield
        for model in (EstimeDeSoi, Rumination, Travail):
            model.objects.all().delete()

    async def test_les_coups_s_accumulent_et_persistent(self):
        from conscience import estime

        v1 = await estime.ressentir(estime.COUP_TRAVAIL_ABOUTI, "test")
        v2 = await estime.ressentir(estime.COUP_TRAVAIL_ABOUTI, "test")
        assert v2 > v1 > estime.BASELINE
        assert await estime.lire() == pytest.approx(v2, abs=1e-3)

    async def test_un_aboutissement_remonte_un_blocage_entame(self):
        from conscience import estime
        from conscience.verdict import lire_verdict

        row = await _travail()
        e = _engine()
        e.memory = SimpleNamespace(remember_completed_work=AsyncMock())
        verdict = lire_verdict(
            '--- VERDICT ---\n{"etat": "fini", "resume": "ok"}\n--- FIN VERDICT ---'
        )
        with patch("conscience.travaux.emotion_engine"):
            await e._appliquer_verdict(row.pk, verdict, "voilà", "")
        assert await estime.lire() > estime.BASELINE

        row2 = await _travail()
        bloque = lire_verdict(
            '--- VERDICT ---\n{"etat": "bloque", "motif": "mur"}\n--- FIN VERDICT ---'
        )
        haut = await estime.lire()
        with patch("conscience.travaux.emotion_engine"):
            await e._appliquer_verdict(row2.pk, bloque, "je bloque", "")
        assert await estime.lire() < haut

    async def test_ignoree_entame_au_changement_jamais_en_boucle(self):
        import time as _t

        from conscience import estime

        e = _engine()
        e._ignores_vus = 0
        e._last_action_time = _t.time() - 3600  # fenêtre écoulée
        await e._suivre_l_estime_sociale(_ctx(consecutive_ignored_acts=1))
        apres_un = await estime.lire()
        assert apres_un < estime.BASELINE
        # Le même compte relu ne recoûte rien.
        await e._suivre_l_estime_sociale(_ctx(consecutive_ignored_acts=1))
        assert await estime.lire() == pytest.approx(apres_un, abs=1e-3)

    async def test_une_reponse_qui_rompt_la_serie_repare(self):
        import time as _t

        from conscience import estime

        e = _engine()
        e._ignores_vus = 2
        e._last_action_time = _t.time() - 3600
        await e._suivre_l_estime_sociale(_ctx(consecutive_ignored_acts=0))
        assert await estime.lire() > estime.BASELINE

    async def test_pendant_la_fenetre_aucun_jugement(self):
        """`_introspect` compte « ignoré » l'acte d'il y a une minute — juger
        pendant la fenêtre prendrait un coup à CHAQUE initiative."""
        import time as _t

        from conscience import estime

        e = _engine()
        e._ignores_vus = 0
        e._last_action_time = _t.time()  # elle vient d'agir
        await e._suivre_l_estime_sociale(_ctx(consecutive_ignored_acts=1))
        assert await estime.lire() == estime.BASELINE

    async def test_le_doute_baisse_le_seuil_de_l_audit(self):
        """Basse estime → elle se rejoue plus : le premier effet
        comportemental de la valeur propre — hors du score de décision.
        Intensité 0.5 : sous le seuil nominal (0.55), mais le doute l'abaisse
        (~0.43) — le tour se rejoue quand même."""
        from conscience.models import EstimeDeSoi, Rumination

        await sync_to_async(EstimeDeSoi.objects.create)(
            valeur=0.1, ancre=tz.now(),
        )
        e = _engine()
        await e.post_action_audit("j'ai dit un truc sec", "angry", 0.5, "web_1")
        n = await sync_to_async(
            lambda: Rumination.objects.filter(status="active").count()
        )()
        assert n == 1

    async def test_l_assurance_remonte_le_seuil(self):
        """Sûre d'elle (0.95), un tour à 0.6 — au-dessus du nominal — ne se
        rejoue plus (~0.685)."""
        from conscience.models import EstimeDeSoi, Rumination

        await sync_to_async(EstimeDeSoi.objects.create)(
            valeur=0.95, ancre=tz.now(),
        )
        e = _engine()
        await e.post_action_audit("j'ai dit un truc sec", "angry", 0.6, "web_1")
        n = await sync_to_async(
            lambda: Rumination.objects.filter(status="active").count()
        )()
        assert n == 0

    def test_la_ligne_de_prompt_dit_un_sentiment_jamais_un_nombre(self):
        from conscience.estime import ligne_de_prompt

        assert "doutes" in ligne_de_prompt(0.2)
        assert "sûre de toi" in ligne_de_prompt(0.8)
        assert ligne_de_prompt(0.5) == ""
        for v in (0.2, 0.5, 0.8):
            assert "0." not in ligne_de_prompt(v)


class TestHabituationPerceptive:
    """Le répété s'efface : le quarantième titre du même flux ne pèse pas
    comme le premier. Fenêtre 10 min, amortissement 0.85^n, plancher 0.4."""

    def _moteur(self):
        e = _engine()
        e._habituation = {}
        return e

    def test_le_premier_signal_pese_plein(self):
        e = self._moteur()
        assert e._habituer("rss", "rss.new_entry", 0.55) == 0.55

    def test_la_repetition_s_amortit(self):
        e = self._moteur()
        e._habituer("rss", "rss.new_entry", 0.55)
        deuxieme = e._habituer("rss", "rss.new_entry", 0.55)
        troisieme = e._habituer("rss", "rss.new_entry", 0.55)
        assert deuxieme == pytest.approx(0.55 * 0.85)
        assert troisieme == pytest.approx(0.55 * 0.85 ** 2)

    def test_le_plancher_tient(self):
        """Du fond sonore, pas du néant."""
        e = self._moteur()
        for _ in range(15):
            dernier = e._habituer("forge", "forge.app.tick", 0.2)
        assert dernier == pytest.approx(0.2 * 0.4)

    def test_deux_types_s_habituent_separement(self):
        e = self._moteur()
        e._habituer("rss", "rss.new_entry", 0.55)
        assert e._habituer("email", "email.received", 0.7) == 0.7

    def test_la_fenetre_expiree_rend_l_attention(self):
        import time as _t

        e = self._moteur()
        e._habituation[("rss", "rss.new_entry")] = [_t.monotonic() - 700]
        assert e._habituer("rss", "rss.new_entry", 0.55) == 0.55


class TestCongruenceDEntree:
    """L'affect devient un filtre d'entrée : un signal qui va dans le sens de
    l'humeur pèse un peu plus — borné ±15 %, amorti ×0.5 en humeur négative
    (le même anti-spirale que le rappel congruent)."""

    def _moteur_avec_humeur(self, position):
        e = _engine()
        faux = SimpleNamespace(
            global_mood=SimpleNamespace(
                dynamic=SimpleNamespace(position=position),
            ),
        )
        return e, patch("conscience.perception.emotion_engine", faux)

    def test_un_signal_congruent_pese_un_peu_plus(self):
        from emotion import pad
        from emotion.types import Emotion

        ancre = pad.EMOTION_ANCHORS[Emotion.EXCITED]
        e, patcheur = self._moteur_avec_humeur(ancre)  # humeur pile dessus
        with patcheur:
            module = e._colorer_par_l_humeur(0.5, "excited")
        assert module == pytest.approx(0.5 * 1.15)

    def test_un_signal_incongruent_ne_bouge_pas(self):
        """Jamais d'atténuation : la congruence amplifie, elle ne censure
        pas — même règle que la résonance de tempérament."""
        from emotion import pad
        from emotion.types import Emotion

        e, patcheur = self._moteur_avec_humeur(
            pad.EMOTION_ANCHORS[Emotion.EXCITED],
        )
        with patcheur:
            assert e._colorer_par_l_humeur(0.5, "sad") == 0.5

    def test_l_humeur_negative_est_amortie(self):
        """« Sombre → signaux sombres plus pertinents → plus sombre » ne doit
        pas s'auto-entretenir : poids divisé par deux."""
        from emotion import pad
        from emotion.types import Emotion

        ancre = pad.EMOTION_ANCHORS[Emotion.SAD]
        e, patcheur = self._moteur_avec_humeur(ancre)
        with patcheur:
            module = e._colorer_par_l_humeur(0.5, "sad")
        assert module == pytest.approx(0.5 * (1 + 0.15 * 0.5))

    def test_un_signal_sans_emotion_ne_bouge_pas(self):
        e = _engine()
        assert e._colorer_par_l_humeur(0.5, "") == 0.5

    def test_jamais_au_dessus_de_un(self):
        from emotion import pad
        from emotion.types import Emotion

        e, patcheur = self._moteur_avec_humeur(
            pad.EMOTION_ANCHORS[Emotion.EXCITED],
        )
        with patcheur:
            assert e._colorer_par_l_humeur(0.95, "excited") == 1.0


class TestReconfort:
    """La régulation émotionnelle est sociale : une humeur sombre qui DURE
    pousse vers le proche auprès de qui elle se sent bien — avant le manque,
    et sans ses portes (avoir parlé hier n'empêche pas d'y aller ce soir)."""

    def _moteur_en_detresse(self):
        import time as _t

        e = _engine()
        e._detresse_depuis = _t.monotonic() - 1000
        return e

    def test_un_pic_sombre_n_est_pas_une_detresse(self):
        e = _engine()
        e._detresse_depuis = 0.0
        e._suivre_la_detresse(_ctx(global_mood="sad", global_intensity=0.7))
        assert e._detresse_depuis > 0
        assert e._detresse_soutenue() is False  # pas encore la durée

    def test_l_eclaircie_remet_le_compteur(self):
        import time as _t

        e = _engine()
        e._detresse_depuis = _t.monotonic() - 1000
        e._suivre_la_detresse(_ctx(global_mood="happy", global_intensity=0.6))
        assert e._detresse_depuis == 0.0
        assert e._detresse_soutenue() is False

    def test_sombre_et_durable_est_une_detresse(self):
        e = self._moteur_en_detresse()
        e._suivre_la_detresse(_ctx(global_mood="sad", global_intensity=0.7))
        assert e._detresse_soutenue() is True

    async def test_la_detresse_va_vers_le_reconfortant_pas_le_manquant(self):
        e = self._moteur_en_detresse()
        e.memory = SimpleNamespace(
            who_is_concerned=AsyncMock(return_value=[]),
            who_comforts=AsyncMock(return_value=[{
                "name": "Adrien", "score": 2.1,
                "handles": [{"person_id": "tg_9", "channel": "telegram",
                             "kind": "module"}],
                "note": "tu ne te sens pas bien — c'est quelqu'un auprès de "
                        "qui tu te sens bien",
            }]),
            who_misses_contact=AsyncMock(return_value=[]),
        )
        with patch(
            "communication.presence.presence_registry.reachable",
            return_value=[],
        ), patch(
            "ai.client.ai_client.complete",
            new=AsyncMock(return_value="[TO:tg_9]"),
        ) as complete:
            cible = await e._select_recipient(_ctx())
        assert cible == "tg_9"
        e.memory.who_comforts.assert_awaited_once()
        e.memory.who_misses_contact.assert_not_awaited()
        assert "auprès de qui tu te sens bien" in complete.await_args.kwargs["user_prompt"]

    async def test_sans_detresse_le_reconfort_ne_se_consulte_pas(self):
        e = _engine()
        e._detresse_depuis = 0.0
        e.memory = SimpleNamespace(
            who_is_concerned=AsyncMock(return_value=[]),
            who_comforts=AsyncMock(return_value=[]),
            who_misses_contact=AsyncMock(return_value=[]),
        )
        with patch(
            "communication.presence.presence_registry.reachable",
            return_value=[],
        ):
            await e._select_recipient(_ctx())
        e.memory.who_comforts.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
class TestWhoComforts:
    """Le réconfortant se classe au lien × la chaleur de l'ancre — sans
    aucune des portes du manque : pas de rythme, pas de silence minimal."""

    @pytest.fixture(autouse=True)
    def _purger(self):
        from memory.models import Entity, PersonProfile
        for model in (PersonProfile, Entity):
            model.objects.all().delete()
        yield
        for model in (PersonProfile, Entity):
            model.objects.all().delete()

    async def _amie(self, nom, closeness="friend"):
        from memory.models import Entity, PersonProfile

        entity = await sync_to_async(Entity.objects.create)(
            name=nom, entity_type="person",
        )
        await sync_to_async(PersonProfile.objects.create)(
            entity=entity, closeness=closeness,
        )

    async def test_le_fond_chaud_gagne_sans_condition_de_silence(self):
        """Aucun Message en base : le réconfort ne regarde pas le rythme du
        lien, seulement le lien et la chaleur."""
        from conscience.memory_bridge import MemoryBridge

        await self._amie("Tiede")
        await self._amie("Chaude")
        handles = AsyncMock(return_value={
            "Tiede": [{"person_id": "tg_t", "channel": "telegram",
                       "kind": "module"}],
            "Chaude": [{"person_id": "tg_c", "channel": "telegram",
                        "kind": "module"}],
        })
        faux_moteur = SimpleNamespace(
            chaleur_envers=AsyncMock(side_effect=lambda pid: 0.8 if pid == "tg_c" else 0.0),
        )
        bridge = MemoryBridge()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=handles,
        ), patch("emotion.engine.emotion_engine", faux_moteur):
            resultats = await bridge.who_comforts(n=2)
        assert [r["name"] for r in resultats] == ["Chaude", "Tiede"]
        assert "auprès de qui tu te sens bien" in resultats[0]["note"]

    async def test_personne_de_lie_personne_a_voir(self):
        from conscience.memory_bridge import MemoryBridge

        bridge = MemoryBridge()
        assert await bridge.who_comforts() == []


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


@pytest.mark.django_db(transaction=True)
class TestAttenteNominative:
    """« J'attends la réponse d'Adrien » n'est plus la même attente aveugle
    que « je reprends dans une heure » : un message de la personne nommée
    relève l'attente avant l'échéance. Résolution par la couche identité au
    réveil — jamais par égalité de nom à l'écriture."""

    @pytest.fixture(autouse=True)
    def _purger(self):
        from conscience.models import Travail
        from memory.models import Conversation, Message
        for model in (Travail, Message, Conversation):
            model.objects.all().delete()
        yield
        for model in (Travail, Message, Conversation):
            model.objects.all().delete()

    async def _attente(self, qui="Adrien", pas_il_y_a_min=30):
        from datetime import timedelta

        return await _travail(
            en_attente_de_reponse=True,
            reprendre_le=tz.now() + timedelta(hours=6),
            attend_qui=qui,
            dernier_pas_le=tz.now() - timedelta(minutes=pas_il_y_a_min),
        )

    async def _message(self, person_id, il_y_a_min=5, interne=False):
        from datetime import timedelta

        from memory.models import Conversation, Message

        conv = await sync_to_async(Conversation.objects.create)()
        msg = await sync_to_async(Message.objects.create)(
            conversation=conv, role="user", content="me voilà",
            person_id=person_id, is_internal=interne,
        )
        await sync_to_async(
            lambda: Message.objects.filter(pk=msg.pk).update(
                created_at=tz.now() - timedelta(minutes=il_y_a_min),
            )
        )()

    def _resolveur(self, mapping):
        return AsyncMock(return_value={
            nom: [{"person_id": pid, "channel": "telegram", "kind": "module"}]
            for nom, pid in mapping.items()
        })

    async def test_le_verdict_ecrit_qui_il_attend(self):
        from conscience.verdict import lire_verdict

        row = await _travail()
        e = _engine()
        verdict = lire_verdict(
            '--- VERDICT ---\n'
            '{"etat": "attendre", "delai_s": 600, "qui": "Adrien"}\n'
            '--- FIN VERDICT ---'
        )
        await e._appliquer_verdict(row.pk, verdict, "je lui ai demandé", "")
        row = await sync_to_async(type(row).objects.get)(pk=row.pk)
        assert row.attend_qui == "Adrien"
        assert row.en_attente_de_reponse is True

    async def test_un_message_de_la_personne_releve_l_attente(self):
        from conscience.models import Travail

        row = await self._attente("Adrien")
        await self._message("tg_9", il_y_a_min=5)
        e = _engine()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._resolveur({"Adrien": "tg_9"}),
        ):
            vivants, _ = await e._travaux_en_cours(tz.now())
        assert vivants[0].en_attente_de_reponse is False
        row = await sync_to_async(Travail.objects.get)(pk=row.pk)
        assert row.attend_qui == ""

    async def test_quelqu_un_d_autre_ne_releve_rien(self):
        row = await self._attente("Adrien")
        await self._message("tg_autre", il_y_a_min=5)
        e = _engine()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._resolveur({"Adrien": "tg_9"}),
        ):
            vivants, _ = await e._travaux_en_cours(tz.now())
        assert vivants[0].en_attente_de_reponse is True

    async def test_un_message_d_avant_le_pas_ne_compte_pas(self):
        """La question a été posée APRÈS ce message : il n'y répond pas."""
        row = await self._attente("Adrien", pas_il_y_a_min=30)
        await self._message("tg_9", il_y_a_min=60)
        e = _engine()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._resolveur({"Adrien": "tg_9"}),
        ):
            vivants, _ = await e._travaux_en_cours(tz.now())
        assert vivants[0].en_attente_de_reponse is True

    async def test_le_brief_interne_n_est_pas_une_reponse(self):
        """Son propre pas persiste un rôle user sous le person_id visé :
        sans l'exclusion, elle se répondrait à elle-même."""
        row = await self._attente("Adrien")
        await self._message("tg_9", il_y_a_min=5, interne=True)
        e = _engine()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=self._resolveur({"Adrien": "tg_9"}),
        ):
            vivants, _ = await e._travaux_en_cours(tz.now())
        assert vivants[0].en_attente_de_reponse is True

    async def test_un_person_id_direct_marche_aussi(self):
        """Le modèle écrit parfois le handle qu'il a sous les yeux : égalité
        de TRANSPORT, pas l'égalité de nom que la couche identité remplace."""
        row = await self._attente("tg_9")
        await self._message("tg_9", il_y_a_min=5)
        e = _engine()
        with patch(
            "identity.resolver.identity_resolver.handles_for_entity_names",
            new=AsyncMock(return_value={}),
        ):
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


@pytest.mark.django_db(transaction=True)
class TestMemoireProposeSujets:
    """La curiosité épistémique : une connaissance érodée — crue à moitié,
    pas invalidée — est un doute qui a un objet. Servie en RAM depuis un
    recompte cron, comme le contrat de `propose_sujets` l'exige."""

    @pytest.fixture(autouse=True)
    def _purger(self):
        from memory.models import Connaissance
        Connaissance.objects.all().delete()
        yield
        Connaissance.objects.all().delete()

    def _module(self):
        import logging

        from memory.module import MemoryToolsModule

        m = MemoryToolsModule.__new__(MemoryToolsModule)
        m._sujets = []
        m.logger = logging.getLogger("test.memory_tools")
        return m

    async def _connaissance(self, contenu, confidence, valide=True):
        from memory.models import Connaissance

        return await sync_to_async(Connaissance.objects.create)(
            content=contenu, confidence=confidence, is_valid=valide,
        )

    async def test_une_connaissance_erodee_devient_un_doute(self):
        await self._connaissance("Thomas travaille chez Dassault", 0.4)
        m = self._module()
        await sync_to_async(m._rafraichir_sujets)()
        sujets = m.propose_sujets()
        assert len(sujets) == 1
        assert "toujours vrai" in sujets[0] and "Dassault" in sujets[0]

    async def test_la_bande_de_confiance_est_fermee_des_deux_cotes(self):
        """Sous 0.25 le doute n'a plus d'objet, au-dessus de 0.55 la
        croyance se porte bien, et l'invalidée n'est plus une croyance."""
        await self._connaissance("presque morte", 0.1)
        await self._connaissance("bien portante", 0.9)
        await self._connaissance("invalidee", 0.4, valide=False)
        m = self._module()
        await sync_to_async(m._rafraichir_sujets)()
        assert m.propose_sujets() == []

    async def test_le_reservoir_est_borne(self):
        for i in range(5):
            await self._connaissance(f"croyance {i}", 0.4)
        m = self._module()
        await sync_to_async(m._rafraichir_sujets)()
        assert len(m.propose_sujets()) == 2

    def test_proposer_ne_paie_aucune_requete(self):
        """Lecture RAM pure — appelable depuis la boucle de décision."""
        m = self._module()
        m._sujets = ["vérifier un truc"]
        assert m.propose_sujets() == ["vérifier un truc"]

    async def test_un_recompte_rate_garde_le_dernier_reservoir(self):
        """Vider sur panne rendrait la panne indiscernable d'une mémoire
        sereine."""
        m = self._module()
        m._sujets = ["vérifier un truc"]
        with patch(
            "memory.models.Connaissance.objects",
        ) as objets:
            objets.filter.side_effect = RuntimeError("base fermée")
            await sync_to_async(m._rafraichir_sujets)()
        assert m.propose_sujets() == ["vérifier un truc"]


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


class TestSalutationsCircadiennes:
    """Les fenêtres de salutation dérivent du profil circadien — les cinq
    clés `conscience.greeting.*` cohabitaient avec `personality.circadian.*`,
    deux sources de vérité pour « quand commence son matin » : un personnage
    nocturne saluait « le matin » à 7 h en dormant."""

    def _profil(self, matin=6, soir=18, nuit=23):
        from emotion.circadian import CircadianPhase, CircadianProfile

        return CircadianProfile(phase_hours={
            CircadianPhase.MORNING: matin,
            CircadianPhase.AFTERNOON: 12,
            CircadianPhase.EVENING: soir,
            CircadianPhase.NIGHT: nuit,
        })

    def test_un_personnage_nocturne_salue_son_matin_a_lui(self):
        e = _engine()
        with patch(
            "config.personality.Personality.circadian_profile",
            new=property(lambda s: self._profil(matin=11)),
        ):
            fenetres = e._fenetres_de_salutation()
        assert fenetres[0] == 11 and fenetres[1] == 14

    def test_les_durees_des_fenetres_sont_celles_d_avant(self):
        """Le profil dit QUAND ; la durée d'un bonjour (3 h / 2 h) est une
        politique du lecteur et reproduit les fenêtres historiques."""
        e = _engine()
        with patch(
            "config.personality.Personality.circadian_profile",
            new=property(lambda s: self._profil()),
        ):
            fenetres = e._fenetres_de_salutation()
        assert fenetres == (6, 9, 18, 20, 23)

    def test_un_profil_illisible_retombe_sur_l_historique(self):
        from conscience.scoring import ScoringTuning

        e = _engine()
        with patch(
            "config.personality.Personality.circadian_profile",
            new=property(lambda s: (_ for _ in ()).throw(RuntimeError("boom"))),
        ):
            fenetres = e._fenetres_de_salutation()
        d = ScoringTuning()
        assert fenetres == (
            d.morning_start, d.morning_end,
            d.evening_start, d.evening_end, d.night_start,
        )

    def test_le_scoring_recoit_les_fenetres_du_profil(self):
        e = _engine()
        with patch(
            "config.personality.Personality.circadian_profile",
            new=property(lambda s: self._profil(matin=11)),
        ):
            t = e._scoring_tuning()
        assert t.morning_start == 11 and t.morning_end == 14
