"""L'échelle de temps de l'affect, et ce qui en dépend.

L'audit du 2026-08-09 a mesuré que l'oscillateur PAD revenait au repos en
~27 s alors qu'un tour dure 30 à 120 s : l'émotion n'existait donc qu'*entre*
les tours, jamais *dans* un tour. Et comme une impulsion ne posait qu'une
vitesse, tout ce qui lit la POSITION — le prompt, le relevé ``EmotionSnapshot``,
la fiche affect, les gestes du frontend — lisait l'état de repos au moment
précis où quelque chose venait de se passer.

Ce que ces tests protègent :

- une dispute de dix tours se lit comme une dispute, et monte ;
- une vexation isolée reste lisible une dizaine de minutes ;
- le cliquet ne s'emballe pas — il ne dépasse jamais la cible ;
- le curseur « vitesse de récupération » change réellement l'enveloppe de
  retour (il ne réglait que la raideur, donc rien de ce qu'il annonce) ;
- le point de repos d'une stance est propre à la personne ;
- le facteur « débordement d'humeur » de ``conscience/scoring.py`` est
  numériquement atteignable, sans l'être pour autant sur une conversation
  ordinaire ;
- ce que la balise ``[EMOTION:]`` déclare est ce qui part dans la trame et ce
  qui se persiste.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from unittest.mock import patch

from old.backend.emotion import pad
from old.backend.emotion.engine import EmotionEngine, TurnEmotionView
from old.backend.emotion.physics import ANCHOR_MAX_NORM
from old.backend.emotion.state import Temperament
from old.backend.emotion.types import Emotion, EmotionData
from old.backend.emotion import circadian, dynamics
from old.backend.utils.degradation import degradations


@pytest.fixture(autouse=True)
def _repos_fixe():
    """Le repos circadien dépend de l'heure de la passe ; ici il ne bouge pas."""
    with patch.object(circadian, "phase_bias", return_value=(0.0, 0.0, 0.0)):
        yield


def _moteur(**temperament) -> EmotionEngine:
    engine = EmotionEngine()
    engine.temperament = Temperament(**temperament)
    engine._recompute_params()
    engine._initialized = True
    return engine


def _avancer(engine: EmotionEngine, secondes: float) -> None:
    """Faire passer le temps, comme la boucle de decay du moteur."""
    restant = secondes
    while restant > 0.0:
        pas = min(restant, 3600.0)
        maintenant = time.time()
        for mood in engine.person_moods.values():
            mood.last_update = maintenant - pas
        engine.global_mood.last_update = maintenant - pas
        engine._apply_decay()
        restant -= pas


def _compte(label: str) -> int:
    for ligne in degradations.snapshot():
        if ligne["label"] == label:
            return ligne["count"]
    return 0


# ===================================================================
# B2 — l'échelle de temps
# ===================================================================

class TestEchelleDeTemps:

    def test_dix_tours_de_dispute_restent_lisibles(self):
        """Le scénario de l'audit : dix ``[EMOTION:angry:0.8]`` à 45 s.

        Sur l'ancien code chaque tour lisait ``happy 0.11`` — l'oscillateur
        était rentré au repos entre deux répliques.
        """
        engine = _moteur()
        lectures = []

        for tour in range(10):
            if tour:
                _avancer(engine, 45.0)
            lectures.append(
                pad.pad_to_label(engine._get_person_mood("p").dynamic.position)
            )
            engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "p")

        # Le premier tour lit une relation vierge ; à partir du deuxième,
        # ce qui vient de se dire est encore là.
        etiquettes = [label for label, _ in lectures[1:]]
        assert set(etiquettes) == {Emotion.ANGRY}, etiquettes

        intensites = [round(value, 3) for _, value in lectures[1:]]
        assert intensites[0] > 0.3
        assert intensites[3] > intensites[0], intensites
        assert max(intensites) > 0.6, intensites

    def test_le_cliquet_monte_puis_plafonne(self):
        engine = _moteur()
        vus = []
        for _ in range(8):
            engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "p")
            vus.append(pad.norm(engine._get_person_mood("p").dynamic.position))

        assert all(b > a for a, b in zip(vus, vus[1:])), vus
        cible = pad.norm(pad.label_to_pad(Emotion.ANGRY, 0.8))
        assert vus[-1] <= cible + 1e-9, \
            "le cliquet ne doit jamais dépasser la cible de la balise"

    def test_une_impulsion_opposee_redescend_la_position(self):
        engine = _moteur()
        for _ in range(3):
            engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "p")

        position = engine._get_person_mood("p").dynamic.position
        avant = pad.distance(position, pad.label_to_pad(Emotion.RELIEVED, 0.8))
        engine.process_emotion(EmotionData(Emotion.RELIEVED, 0.8), "p")
        apres = pad.distance(
            engine._get_person_mood("p").dynamic.position,
            pad.label_to_pad(Emotion.RELIEVED, 0.8),
        )
        assert apres < avant

    def test_le_cliquet_ne_s_emballe_pas(self):
        engine = _moteur()
        alternance = [
            Emotion.ANGRY, Emotion.EXCITED, Emotion.SCARED, Emotion.LOVE,
        ]
        for index in range(200):
            engine.process_emotion(
                EmotionData(alternance[index % 4], 1.0), "p",
            )
            for composante in engine._get_person_mood("p").dynamic.position:
                assert -1.2 <= composante <= 1.2

    def test_une_vexation_reste_lisible_quinze_minutes(self):
        """Cible de l'arbitrage : une vexation se lit encore 10 à 30 min après."""
        engine = _moteur()
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.7), "p")
        _avancer(engine, 600.0)

        label, intensite = pad.pad_to_label(
            engine._get_person_mood("p").dynamic.position
        )
        assert label is Emotion.ANGRY, label
        assert intensite >= 0.15, intensite

    def test_le_rattrapage_couvre_une_hibernation(self):
        """Le plafond de rattrapage était de 30 s, soit 4 τ à l'ancienne échelle.

        À τ ≈ 11 min il figeait l'état d'une machine qui a dormi.
        """
        engine = _moteur()
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.9), "p")
        _avancer(engine, 3600.0)

        mood = engine._get_person_mood("p")
        assert pad.distance(mood.dynamic.position, engine._person_home(mood)) < 0.1


# ===================================================================
# B2 — peak_projection (contrat C2-iii)
# ===================================================================

class TestProjection:

    def test_peak_projection_est_pure_et_bornee(self):
        engine = _moteur()
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "p")
        mood = engine._get_person_mood("p")
        home = engine._person_home(mood)

        avant = (mood.dynamic.position, mood.dynamic.velocity)
        projete = dynamics.peak_projection(
            mood.dynamic.position, mood.dynamic.velocity, home,
            engine._person_params,
        )
        assert (mood.dynamic.position, mood.dynamic.velocity) == avant

        # En simple relaxation, le sommet est la position courante.
        assert projete == mood.dynamic.position

    def test_peak_projection_suit_une_vitesse_qui_eloigne(self):
        engine = _moteur()
        mood = engine._get_person_mood("p")
        home = pad.zero()
        mood.dynamic.position = (0.2, 0.0, 0.0)
        mood.dynamic.velocity = (0.05, 0.0, 0.0)

        projete = dynamics.peak_projection(
            mood.dynamic.position, mood.dynamic.velocity, home,
            engine._person_params,
        )
        assert pad.norm(projete) > pad.norm(mood.dynamic.position)


# ===================================================================
# C2 — turn_emotion_view
# ===================================================================

class TestVueDuTour:

    async def test_turn_emotion_view_prefere_le_tag(self):
        engine = _moteur()
        declare = EmotionData(Emotion.ANGRY, 0.8)
        engine.process_emotion(declare, "p")

        vue = await engine.turn_emotion_view("p", declare)

        assert isinstance(vue, TurnEmotionView)
        assert vue.emotion == "angry"
        assert vue.intensity == pytest.approx(0.8)
        assert vue.declared is True
        assert vue.blend and vue.blend[0][0] == "angry", vue.blend
        assert len(vue.blend) <= 2

    async def test_turn_emotion_view_sans_tag_lit_l_oscillateur(self):
        engine = _moteur()
        engine.process_emotion(EmotionData(Emotion.GRATEFUL, 0.7), "p")

        vue = await engine.turn_emotion_view("p", None)
        courant = engine.compute_message_emotion("p")

        assert vue.declared is False
        assert vue.emotion == courant.emotion.value
        assert vue.intensity == pytest.approx(courant.intensity)

    async def test_turn_emotion_view_ne_leve_jamais(self, monkeypatch):
        engine = _moteur()
        avant = _compte("emotion: vue du tour")

        def _explose(_person_id):
            raise RuntimeError("oscillateur injoignable")

        monkeypatch.setattr(engine, "_get_person_mood", _explose)

        vue = await engine.turn_emotion_view("p", EmotionData(Emotion.SAD, 0.6))

        assert vue.emotion == "sad"
        assert vue.declared is True
        assert _compte("emotion: vue du tour") > avant

    async def test_la_trame_ne_se_contredit_pas(self):
        """``emotion`` et ``blend[0]`` partent ensemble dans la trame speech,
        et la porte d'ambivalence des gestes lit ce couple."""
        engine = _moteur()
        for _ in range(4):
            engine.process_emotion(EmotionData(Emotion.HAPPY, 0.9), "p")

        vue = await engine.turn_emotion_view("p", EmotionData(Emotion.SAD, 0.7))
        assert vue.blend[0][0] == vue.emotion


# ===================================================================
# S1 — un tour sans balise ne touche à rien
# ===================================================================

class TestBaliseAbsente:

    def test_un_tour_sans_tag_ne_touche_pas_l_oscillateur(self):
        from old.backend.emotion.types import extract_emotion

        engine = _moteur()
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.7), "p")
        mood = engine._get_person_mood("p")
        fige = (mood.dynamic.position, mood.dynamic.velocity)

        texte, declare = extract_emotion("bon, et sinon tu fais quoi demain")
        assert declare is None

        # Un appelant correct saute ``process_emotion``.
        if declare is not None:  # pragma: no cover - garde de lisibilité
            engine.process_emotion(declare, "p")

        assert (mood.dynamic.position, mood.dynamic.velocity) == fige


# ===================================================================
# S4 — le débordement d'humeur globale
# ===================================================================

class TestDebordementGlobal:

    def test_le_debordement_d_humeur_est_atteignable(self):
        engine = _moteur()
        pic = 0.0
        for _ in range(40):
            engine.process_emotion(EmotionData(Emotion.ANGRY, 1.0), "p")
            pic = max(pic, engine.global_mood.intensity)
            _avancer(engine, 30.0)

        assert pic > 0.70, (
            "Facteur 3 de conscience/scoring.py (global_intensity > 0.7) : "
            f"inatteignable, pic mesuré {pic:.3f}"
        )

    def test_une_conversation_ordinaire_ne_deborde_pas(self):
        engine = _moteur()
        cycle = [
            (Emotion.CURIOUS, 0.5), (Emotion.AMUSED, 0.6),
            (Emotion.THINKING, 0.4), (Emotion.FRUSTRATED, 0.5),
            (Emotion.HAPPY, 0.7), (Emotion.SURPRISED, 0.5),
            (Emotion.NOSTALGIC, 0.4), (Emotion.SAD, 0.5),
            (Emotion.HOPEFUL, 0.6), (Emotion.PLAYFUL, 0.7),
        ]
        pic = 0.0
        for index in range(60):
            emotion, intensite = cycle[index % len(cycle)]
            engine.process_emotion(EmotionData(emotion, intensite), "p")
            pic = max(pic, engine.global_mood.intensity)
            _avancer(engine, 60.0)

        assert pic < 0.70, (
            "une heure de conversation banale ne doit pas déclencher le "
            f"facteur de débordement, pic mesuré {pic:.3f}"
        )

    def test_le_gain_global_n_a_pas_de_plancher(self):
        """Le plancher ``max(0.05, …)`` faisait fuiter 5 % de la cible pleine
        même à diffusion nulle, ce que dément la description du curseur."""
        assert _moteur(global_bleed=0.0)._global_params.impulse_gain == 0.0
        assert _moteur(global_bleed=0.02)._global_params.impulse_gain < 0.05

    def test_a_diffusion_nulle_le_global_ne_bouge_pas(self):
        engine = _moteur(global_bleed=0.0)
        avant = engine.global_mood.dynamic.position

        for _ in range(5):
            engine.process_emotion(EmotionData(Emotion.ANGRY, 1.0), "p")

        assert engine.global_mood.dynamic.position == avant, \
            "« à 0 elle compartimente entièrement » (emotion/config_schema.py)"


# ===================================================================
# S5 — l'enveloppe de retour et l'ancrage personnel
# ===================================================================

class TestEnveloppeEtAncrage:

    def test_le_curseur_de_recuperation_change_l_enveloppe(self):
        """Il ne réglait que la raideur : le taux de décroissance était
        rigoureusement identique de 0.05 à 1.0 (mesuré à cinq décimales)."""
        restants = {}
        for recovery in (0.05, 1.0):
            engine = _moteur(recovery_speed=recovery)
            engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "p")
            _avancer(engine, 600.0)
            _, intensite = pad.pad_to_label(
                engine._get_person_mood("p").dynamic.position
            )
            restants[recovery] = intensite

        assert restants[0.05] > restants[1.0] * 2.0, restants

    def test_la_stance_revient_vers_l_ancrage_personnel(self):
        engine = _moteur()
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.5), "ancree")
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.5), "vierge")

        frustre = pad.label_to_pad(Emotion.FRUSTRATED, 0.6)
        engine._get_person_mood("ancree").anchor = frustre

        _avancer(engine, 7200.0)

        ancree = engine._get_person_mood("ancree").dynamic.position
        vierge = engine._get_person_mood("vierge").dynamic.position

        assert pad.dot(ancree, frustre) > pad.dot(vierge, frustre)
        assert pad.distance(vierge, engine._home_vector()) < 0.05

    def test_l_ancrage_ne_s_emballe_pas(self):
        engine = _moteur()
        mood = engine._get_person_mood("p")
        mood.dynamic.position = pad.label_to_pad(Emotion.ANGRY, 1.0)

        normes = []
        for _ in range(60):
            engine._note_anchor(mood, mood.dynamic.position)
            normes.append(pad.norm(mood.anchor))

        assert normes[-1] <= ANCHOR_MAX_NORM + 1e-9
        assert normes[-1] >= normes[-2] - 1e-9
        assert abs(normes[-1] - normes[-2]) < 1e-3, "l'EMA doit converger"

    def test_l_ancrage_ne_bloque_pas_le_chemin_chaud(self, monkeypatch):
        """``get_person_affect_context`` et ``compute_message_emotion`` sont
        appelées dans le tour : aucune requête ne doit s'y glisser."""
        import old.backend.memory.models as models_module

        engine = _moteur()
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "p")

        class _BaseInjoignable:
            def __getattr__(self, name):
                raise AssertionError("aucune lecture ORM sur le chemin chaud")

        monkeypatch.setattr(
            models_module.EmotionSnapshot, "objects", _BaseInjoignable(),
        )

        assert engine.get_person_affect_context("p")
        assert engine.compute_message_emotion("p") is not None

    def test_une_lecture_d_ancrage_ratee_est_comptee(self):
        engine = _moteur()
        avant = _compte("emotion.physics.anchor_from_rows")

        class _LigneIllisible:
            @property
            def primary_emotion(self):
                raise RuntimeError("colonne corrompue")

        assert engine._anchor_from_snapshots([_LigneIllisible()]) is None
        assert _compte("emotion.physics.anchor_from_rows") > avant

    def test_une_emotion_inconnue_en_base_est_ignoree_sans_bruit(self):
        engine = _moteur()

        class _Ligne:
            def __init__(self, nom, intensite):
                self.primary_emotion = nom
                self.primary_intensity = intensite

        ancrage = engine._anchor_from_snapshots([
            _Ligne("spaghetti", 0.9), _Ligne("angry", 0.8),
        ])
        assert ancrage is not None
        assert pad.dot(ancrage, pad.EMOTION_ANCHORS[Emotion.ANGRY]) > 0

    def test_le_marqueur_bien_ancree_ne_lit_plus_la_vitesse(self):
        """La vitesse ne porte plus l'impulsion : les seuils qui la lisaient
        (``speed > 0.3``) ne pouvaient plus être franchis."""
        engine = _moteur()
        for _ in range(2):
            engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "construite")
        assert "bien ancree" in engine.get_person_affect_context("construite")

        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.25), "passagere")
        assert "bien ancree" not in engine.get_person_affect_context("passagere")


# ===================================================================
# S3 — l'amplitude dans la direction du tempérament
# ===================================================================

class TestProseHumeur:

    def _humeur(self, emotion: Emotion, intensite: float):
        from old.backend.emotion.state import GlobalMood

        mood = GlobalMood()
        mood.dynamic.position = pad.label_to_pad(emotion, intensite)
        return mood

    def test_l_amplitude_dans_le_temperament_n_est_plus_muette(self):
        discrete = self._humeur(Emotion.HAPPY, 0.15)
        franche = self._humeur(Emotion.HAPPY, 0.95)

        assert (
            discrete.to_prompt_description(Emotion.HAPPY)
            != franche.to_prompt_description(Emotion.HAPPY)
        )

    def test_une_humeur_plate_dit_comme_d_habitude(self):
        plate = self._humeur(Emotion.HAPPY, 0.02)
        assert "comme d'habitude" in plate.to_prompt_description(Emotion.HAPPY)

    def test_une_humeur_marquee_le_dit(self):
        franche = self._humeur(Emotion.HAPPY, 0.95)
        assert "nettement plus" in franche.to_prompt_description(Emotion.HAPPY)


# ===================================================================
# S2 — le relevé persiste ce que le tour a déclaré
# ===================================================================

@pytest.mark.django_db(transaction=True)
class TestReleve:

    @pytest.fixture(autouse=True)
    def _conversation(self, monkeypatch):
        import old.backend.memory.manager as manager_module
        from old.backend.memory.models import Conversation, EmotionSnapshot

        EmotionSnapshot.objects.all().delete()
        conversation = Conversation.objects.create()

        class _Faux:
            pass

        faux = _Faux()
        faux.conversation = conversation
        monkeypatch.setattr(manager_module, "memory_manager", faux)
        yield conversation

    async def _lignes(self):
        from asgiref.sync import sync_to_async
        from old.backend.memory.models import EmotionSnapshot

        return await sync_to_async(lambda: list(EmotionSnapshot.objects.all()))()

    async def test_le_releve_persiste_l_emotion_du_tag(self):
        engine = _moteur()
        await engine.save_snapshot("p", EmotionData(Emotion.ANGRY, 0.85))

        lignes = await self._lignes()
        assert len(lignes) == 1
        assert lignes[0].primary_emotion == "angry"
        assert lignes[0].primary_intensity == pytest.approx(0.85)

    async def test_sans_tag_le_releve_lit_l_oscillateur(self):
        engine = _moteur()
        engine.process_emotion(EmotionData(Emotion.GRATEFUL, 0.9), "p")
        attendu = pad.pad_to_label(engine._get_person_mood("p").dynamic.position)

        await engine.save_snapshot("p")

        lignes = await self._lignes()
        assert lignes[0].primary_emotion == attendu[0].value
        assert lignes[0].primary_intensity == pytest.approx(attendu[1])

    async def test_le_throttle_part_de_l_ecriture(self):
        engine = _moteur()
        entree = time.time()
        await engine.save_snapshot("p", EmotionData(Emotion.ANGRY, 0.8))

        assert engine._last_snapshot_time["p"] >= entree

    async def test_une_ecriture_ratee_ne_ferme_pas_la_fenetre(self, monkeypatch):
        from old.backend.memory.models import EmotionSnapshot

        engine = _moteur()
        avant = _compte("emotion.persistence.save_person_snapshot")
        vrai_create = EmotionSnapshot.objects.create
        appels = {"n": 0}

        def _create(**kwargs):
            appels["n"] += 1
            if appels["n"] == 1:
                raise RuntimeError("base indisponible")
            return vrai_create(**kwargs)

        monkeypatch.setattr(EmotionSnapshot.objects, "create", _create)

        await engine.save_snapshot("p", EmotionData(Emotion.ANGRY, 0.8))
        assert "p" not in engine._last_snapshot_time
        assert _compte("emotion.persistence.save_person_snapshot") > avant

        await engine.save_snapshot("p", EmotionData(Emotion.ANGRY, 0.8))
        assert len(await self._lignes()) == 1

    async def test_deux_appels_concurrents_n_ecrivent_qu_une_ligne(self):
        engine = _moteur()
        await asyncio.gather(
            engine.save_snapshot("p", EmotionData(Emotion.ANGRY, 0.8)),
            engine.save_snapshot("p", EmotionData(Emotion.ANGRY, 0.8)),
        )
        assert len(await self._lignes()) == 1

    async def test_le_releve_du_tag_alimente_l_ancrage(self):
        engine = _moteur()
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "p")
        assert engine._get_person_mood("p").anchor is None

        await engine.save_snapshot("p", EmotionData(Emotion.ANGRY, 0.8))

        ancrage = engine._get_person_mood("p").anchor
        assert ancrage is not None
        assert pad.dot(ancrage, pad.EMOTION_ANCHORS[Emotion.ANGRY]) > 0

    async def test_l_ancrage_est_amorce_a_l_hydratation(self):
        engine = _moteur()
        for _ in range(3):
            await engine.save_snapshot("web_ancre", EmotionData(Emotion.SAD, 0.7))
            engine._last_snapshot_time.pop("web_ancre", None)

        engine.person_moods.pop("web_ancre", None)
        await engine.ensure_person_loaded("web_ancre")

        mood = engine.person_moods.get("web_ancre")
        assert mood is not None
        assert mood.anchor is not None
        assert pad.dot(mood.anchor, pad.EMOTION_ANCHORS[Emotion.SAD]) > 0

    async def test_une_base_injoignable_ne_leve_pas_a_l_hydratation(self, monkeypatch):
        from old.backend.memory.models import EmotionSnapshot

        engine = _moteur()
        avant = _compte("emotion.persistence.ensure_person_loaded")

        class _Injoignable:
            def filter(self, **kwargs):
                raise RuntimeError("base indisponible")

        monkeypatch.setattr(EmotionSnapshot, "objects", _Injoignable())

        await engine.ensure_person_loaded("web_absent")

        assert "web_absent" not in engine.person_moods
        assert _compte("emotion.persistence.ensure_person_loaded") > avant
