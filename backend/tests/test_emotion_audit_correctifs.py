"""Les cinq défauts confirmés par l'audit affectif — corrigés, et épinglés.

Chaque classe porte un défaut, et chaque test a été vu ROUGE sur le code
d'avant (les chiffres « avant » sont mesurés, aux défauts du registre) :

1. **Le premier relevé posait l'ancre à 100 %.** ``_note_anchor`` retournait
   ``_clamp_anchor(position)`` quand l'ancre était ``None`` ; α = 0,15 ne
   valait qu'à partir du second relevé. Un seul ``[EMOTION:angry:0.8]``
   envers un inconnu : ancre au plafond (0,7), « légèrement en colère » une
   heure plus tard, encore teintée après trois jours. Même poids 1 pour une
   ligne seule dans ``_anchor_from_snapshots``.
2. **Éviction + réhydratation ressuscitaient une émotion digérée.** La
   position était reconstruite depuis la valeur DÉCLARÉE du relevé, vieillie
   sur une droite de deux jours alors que τ vaut ~11,6 min. Vivant à 1 h :
   ``hopeful 0.11`` ; réhydraté : ``angry 0.73`` ; à 12 h encore ``angry
   0.56``.
3. **Le repos se racontait comme un écart, et chaque inconnu avait une
   stance.** Le repos vaut ``default_mood × 0.15 + teinte circadienne``,
   dont le plus proche voisin n'est jamais ``default_mood`` : « légèrement
   joueuse, alors que normalement tu es plutôt contente » toute la journée ;
   et la stance d'un inconnu, mesurée depuis l'origine, franchissait 0,1 en
   rejoignant ce repos.
4. **La vie intérieure n'atteignait jamais l'humeur de fond.** Huit ``bored
   0.25`` demi-horaires → ``hopeful 0.07`` ; un chantier bloqué
   (``frustrated 0.35``) → valence −0,04.
5. **La famille triste ne pouvait ni déborder ni compter comme détresse** :
   ``sad`` à son ancre pleine lisait 0,73, ``frustrated`` 0,65,
   ``melancholic`` 0,62 — sous les portes 0,7 et 0,55.

Le repos circadien est figé à zéro (comme les deux tests jadis instables
l'ont appris) sauf là où le défaut EST la teinte : ces tests-là posent une
teinte d'après-midi explicite.
"""
from __future__ import annotations

import dataclasses
import time
from datetime import timedelta

import pytest
from unittest.mock import patch

from emotion import circadian, pad
from emotion import engine as engine_module
from emotion.engine import EmotionEngine
from emotion.state import GlobalMood, Temperament
from emotion.types import Emotion, EmotionData

#: Une teinte d'après-midi : le repos qui en résulte a ``playful`` pour plus
#: proche voisin (norme ~0,5), soit exactement le cas de l'audit à 14 h.
TEINTE_APRES_MIDI = (0.245, 0.21, 0.175)


@pytest.fixture(autouse=True)
def _repos_fixe():
    with patch.object(circadian, "phase_bias", return_value=(0.0, 0.0, 0.0)):
        yield


def _moteur(**temperament) -> EmotionEngine:
    engine = EmotionEngine()
    engine.temperament = Temperament(**temperament)
    engine._recompute_params()
    engine._initialized = True
    return engine


def _avancer(engine: EmotionEngine, secondes: float) -> None:
    restant = secondes
    while restant > 0.0:
        pas = min(restant, 3600.0)
        maintenant = time.time()
        for mood in engine.person_moods.values():
            mood.last_update = maintenant - pas
        engine.global_mood.last_update = maintenant - pas
        engine._apply_decay()
        restant -= pas


def _progression(depuis: pad.Vec3, vers: pad.Vec3, position: pad.Vec3) -> float:
    """Part du chemin ``depuis → vers`` parcourue par ``position``."""
    return 1.0 - pad.distance(position, vers) / pad.distance(depuis, vers)


class _Ligne:
    def __init__(self, nom: str, intensite: float):
        self.primary_emotion = nom
        self.primary_intensity = intensite


# ===================================================================
# 1 — le premier relevé
# ===================================================================

class TestPremierReleve:

    def test_un_seul_tour_en_colere_teinte_a_peine_l_ancre(self):
        """Avant : ancre à 0,72 du repos, repos personnel lu ``angry``."""
        engine = _moteur()
        mood = engine._get_person_mood("p")
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "p")
        engine._note_anchor(mood, pad.label_to_pad(Emotion.ANGRY, 0.8))

        home = engine._home_vector()
        assert pad.distance(mood.anchor, home) < 0.25, mood.anchor
        repos, _ = pad.pad_to_label(engine._person_home(mood))
        assert pad.valence(repos) >= 0.0, (
            f"un seul tour ne fait pas un repos en colère : {repos.value}"
        )

    def test_le_premier_releve_pese_autant_que_les_suivants(self):
        """Même fraction du chemin restant à chaque fondu, le premier compris."""
        engine = _moteur()
        mood = engine._get_person_mood("p")
        home = engine._home_vector()
        cible = pad.label_to_pad(Emotion.ANGRY, 0.8)

        engine._note_anchor(mood, cible)
        premiere = pad.distance(mood.anchor, home) / pad.distance(cible, home)
        depart = mood.anchor
        engine._note_anchor(mood, cible)
        seconde = pad.distance(mood.anchor, depart) / pad.distance(cible, depart)

        assert 0.0 < premiere < 0.5
        assert premiere == pytest.approx(seconde, abs=1e-6)

    def test_une_ligne_seule_pese_alpha_a_la_rehydratation(self):
        """Une ligne reconstruit la même ancre qu'un premier relevé fondu."""
        engine = _moteur()
        home = engine._home_vector()

        seule = engine._anchor_from_snapshots([_Ligne("angry", 0.8)])
        mood = engine._get_person_mood("p")
        engine._note_anchor(mood, pad.label_to_pad(Emotion.ANGRY, 0.8))

        assert seule == pytest.approx(mood.anchor, abs=1e-9)
        assert pad.distance(seule, home) < 0.25

    def test_vingt_lignes_pesent_plus_qu_une(self):
        """Le poids du relevé monte avec le nombre de lignes concordantes."""
        engine = _moteur()
        home = engine._home_vector()
        une = engine._anchor_from_snapshots([_Ligne("angry", 0.8)])
        vingt = engine._anchor_from_snapshots([_Ligne("angry", 0.8)] * 20)

        assert pad.distance(vingt, home) > pad.distance(une, home) * 3
        assert pad.dot(vingt, pad.EMOTION_ANCHORS[Emotion.ANGRY]) > 0


# ===================================================================
# 2 — réhydratation et redémarrage
# ===================================================================

class TestPositionVieillie:

    def test_est_l_oscillateur_lui_meme(self):
        """Pas une formule à côté de la physique : la même intégration que
        la boucle, depuis le relevé au repos."""
        engine = _moteur()
        home = (0.1, 0.0, 0.0)
        cible = (1.1, 0.0, 0.0)
        params = engine._person_params
        tau = engine._person_tau()

        assert EmotionEngine._aged_position(cible, home, 0.0, params) == pytest.approx(cible)

        apres_tau = EmotionEngine._aged_position(cible, home, tau, params)
        restant = pad.distance(apres_tau, home) / pad.distance(cible, home)
        assert 0.2 < restant < 0.6, restant  # l'enveloppe e⁻¹, oscillation comprise

        loin = EmotionEngine._aged_position(cible, home, 10 * tau, params)
        assert pad.distance(loin, home) < 1e-3

        mood = engine._get_person_mood("p")
        mood.dynamic.position = cible
        with patch.object(engine, "_home_vector", return_value=home):
            _avancer(engine, 3600.0)
        assert EmotionEngine._aged_position(cible, home, 3600.0, params) == pytest.approx(
            mood.dynamic.position, abs=1e-9,
        )

    def test_la_constante_de_temps_est_celle_de_la_boucle(self):
        """Même τ que l'enveloppe posée par ``_recompute_params`` (~11,6 min
        au tempérament par défaut, le global deux fois plus lent)."""
        engine = _moteur()
        assert 600.0 < engine._person_tau() < 800.0
        assert engine._global_tau() == pytest.approx(2.0 * engine._person_tau())


@pytest.mark.django_db(transaction=True)
class TestRehydratation:

    @pytest.fixture(autouse=True)
    def _conversation(self, monkeypatch):
        import memory.manager as manager_module
        from memory.models import Conversation, EmotionalSummary, EmotionSnapshot

        EmotionSnapshot.objects.all().delete()
        EmotionalSummary.objects.all().delete()
        conversation = Conversation.objects.create()

        class _Faux:
            pass

        faux = _Faux()
        faux.conversation = conversation
        monkeypatch.setattr(manager_module, "memory_manager", faux)
        yield conversation
        EmotionSnapshot.objects.all().delete()
        EmotionalSummary.objects.all().delete()

    async def _releve_vieux_de(self, engine, pid, emotion, intensite, secondes):
        from asgiref.sync import sync_to_async
        from django.utils import timezone
        from memory.models import EmotionSnapshot

        await engine.save_snapshot(pid, EmotionData(emotion, intensite))
        engine._last_snapshot_time.pop(pid, None)
        await sync_to_async(
            lambda: EmotionSnapshot.objects.filter(person_id=pid).update(
                created_at=timezone.now() - timedelta(seconds=secondes),
            )
        )()

    async def test_une_heure_plus_tard_elle_lit_ce_que_l_oscillateur_vivant_lirait(self):
        """Avant : vivant ``hopeful 0.11``, réhydraté ``angry 0.73``."""
        vivant = _moteur()
        vivant.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "web_r")
        vivant._note_anchor(
            vivant._get_person_mood("web_r"), pad.label_to_pad(Emotion.ANGRY, 0.8),
        )
        _avancer(vivant, 3600.0)
        attendu = vivant._get_person_mood("web_r").dynamic.position

        engine = _moteur()
        await self._releve_vieux_de(engine, "web_r", Emotion.ANGRY, 0.8, 3600)
        engine.person_moods.pop("web_r", None)
        await engine.ensure_person_loaded("web_r")

        restaure = engine.person_moods["web_r"].dynamic.position
        assert pad.distance(restaure, attendu) < 0.05, (restaure, attendu)
        label, _ = pad.pad_to_label(restaure)
        assert pad.valence(label) >= 0.0, label

    async def test_douze_heures_plus_tard_rien_ne_ressuscite(self):
        """Avant : encore ``angry 0.56``."""
        engine = _moteur()
        await self._releve_vieux_de(engine, "web_r", Emotion.ANGRY, 0.8, 12 * 3600)
        engine.person_moods.pop("web_r", None)
        await engine.ensure_person_loaded("web_r")

        mood = engine.person_moods["web_r"]
        assert pad.distance(mood.dynamic.position, engine._person_home(mood)) < 0.02
        assert mood.anchor is not None, "l'ancre, elle, survit — c'est son rôle"

    async def test_un_releve_de_l_instant_restaure_la_position_pas_la_balise(self):
        """L'autre bord : redémarrage juste après le tour, rien n'est perdu —
        mais ce qui est restauré est ce que l'oscillateur VIVANT tenait après
        le tour (le cliquet ne parcourt que ~51 % du chemin), pas la balise
        ``angry 0.8`` elle-même, que la position n'avait jamais atteinte."""
        vivant = _moteur()
        vivant.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "web_r")
        attendu = vivant._get_person_mood("web_r").dynamic.position

        engine = _moteur()
        await self._releve_vieux_de(engine, "web_r", Emotion.ANGRY, 0.8, 0)
        engine.person_moods.pop("web_r", None)
        await engine.ensure_person_loaded("web_r")

        restaure = engine.person_moods["web_r"].dynamic.position
        assert pad.distance(restaure, attendu) < 0.08, (restaure, attendu)
        assert pad.pad_to_label(restaure)[0] is Emotion.ANGRY
        assert pad.distance(restaure, pad.label_to_pad(Emotion.ANGRY, 0.8)) > 0.2

    async def test_un_releve_existant_prime_sur_le_resume_quotidien(self):
        """Un relevé apaisé n'est pas « trop vieux » : retomber sur le résumé
        de la veille ressuscitait l'émotion dominante d'hier."""
        from asgiref.sync import sync_to_async
        from datetime import date
        from memory.models import EmotionalSummary

        engine = _moteur()
        await sync_to_async(EmotionalSummary.objects.create)(
            person_id="web_r", period_type="daily",
            period_start=date.today() - timedelta(days=1),
            dominant_emotion="sad", dominant_intensity=0.9,
        )
        await self._releve_vieux_de(engine, "web_r", Emotion.HAPPY, 0.5, 3 * 3600)
        engine.person_moods.pop("web_r", None)
        await engine.ensure_person_loaded("web_r")

        mood = engine.person_moods["web_r"]
        label, _ = pad.pad_to_label(mood.dynamic.position)
        assert pad.valence(label) >= 0.0, label
        assert pad.distance(mood.dynamic.position, engine._person_home(mood)) < 0.02

    async def test_le_redemarrage_vieillit_selon_l_oscillateur(self, _conversation):
        """Même règle pour ``_restore_state`` — humeur de fond comprise."""
        from asgiref.sync import sync_to_async
        from django.utils import timezone
        from memory.models import EmotionSnapshot

        # Ce que l'oscillateur vivant lirait une heure après un relevé
        # ``angry 0.8`` : le fond est deux fois plus lent (τ ≈ 23 min), il
        # garde donc ~7 % de la colère ; la stance, elle, est au repos.
        vivant = _moteur()
        vivant.global_mood.dynamic.position = pad.label_to_pad(Emotion.ANGRY, 0.8)
        vivant._get_person_mood("web_r").dynamic.position = pad.label_to_pad(
            Emotion.ANGRY, 0.8,
        )
        _avancer(vivant, 3600.0)

        engine = _moteur()
        home = engine._home_vector()

        def _ecrire():
            for pid, emo in (("__global__", "angry"), ("web_r", "angry")):
                EmotionSnapshot.objects.create(
                    conversation=_conversation, person_id=pid,
                    primary_emotion=emo, primary_intensity=0.8,
                    global_emotion="angry", global_intensity=0.8,
                )
            EmotionSnapshot.objects.update(
                created_at=timezone.now() - timedelta(hours=1),
            )

        await sync_to_async(_ecrire)()
        await engine._restore_state()

        assert pad.distance(
            engine.global_mood.dynamic.position,
            vivant.global_mood.dynamic.position,
        ) < 0.03
        assert pad.valence(engine.global_mood.emotion) >= 0.0
        assert "web_r" in engine.person_moods
        # Au repos PROPRE de la personne : l'ancre est recalculée au
        # redémarrage (une ligne, fondue à α depuis le repos commun), et la
        # position y est ramenée — plus vers le repos de tout le monde.
        mood = engine.person_moods["web_r"]
        assert mood.anchor is not None
        assert pad.distance(mood.dynamic.position, engine._person_home(mood)) < 0.02
        assert pad.distance(mood.dynamic.position, home) < 0.15


# ===================================================================
# 3 — le repos raconté, et l'inconnu
# ===================================================================

class TestReposRaconte:

    def test_au_repos_l_humeur_de_fond_se_dit_comme_d_habitude(self):
        """Avant : « légèrement joueuse, alors que normalement tu es plutôt
        contente » — toute la journée, sans que rien ne se soit passé."""
        with patch.object(circadian, "phase_bias", return_value=TEINTE_APRES_MIDI):
            engine = _moteur()
            home = engine._home_vector()
            assert pad.pad_to_label(home)[0] is not Emotion.HAPPY, "prémisse"
            engine.global_mood.dynamic.position = home

            prose = engine.get_global_mood_context()

        assert "comme d'habitude" in prose, prose
        assert "alors que normalement" not in prose, prose

    def test_un_ecart_reel_est_toujours_raconte(self):
        with patch.object(circadian, "phase_bias", return_value=TEINTE_APRES_MIDI):
            engine = _moteur()
            home = engine._home_vector()
            engine.global_mood.dynamic.position = pad.add(
                home, pad.label_to_pad(Emotion.SAD, 0.6),
            )
            prose = engine.get_global_mood_context()
        assert "comme d'habitude" not in prose, prose

    def test_sans_repos_fourni_l_origine_fait_office_de_repos(self):
        """L'appel isolé (tests, prose hors moteur) garde son sens d'avant."""
        mood = GlobalMood()
        mood.dynamic.position = pad.label_to_pad(Emotion.HAPPY, 0.02)
        assert "comme d'habitude" in mood.to_prompt_description(Emotion.HAPPY)
        mood.dynamic.position = pad.label_to_pad(Emotion.HAPPY, 0.95)
        assert "nettement plus" in mood.to_prompt_description(Emotion.HAPPY)

    def test_un_inconnu_n_a_pas_de_stance_meme_apres_derive(self):
        """Avant : « Envers cette personne, tu te sens a peine joueuse »
        dix minutes après la première lecture — l'oscillateur créé à
        l'origine avait rejoint le repos, et la norme brute dépassait 0,1."""
        with patch.object(circadian, "phase_bias", return_value=TEINTE_APRES_MIDI):
            engine = _moteur()
            assert engine.get_person_affect_context("inconnu") == ""
            _avancer(engine, 600.0)
            assert pad.norm(engine.person_moods["inconnu"].dynamic.position) > 0.1
            assert engine.get_person_affect_context("inconnu") == ""

    def test_une_stance_revenue_au_repos_se_tait(self):
        with patch.object(circadian, "phase_bias", return_value=TEINTE_APRES_MIDI):
            engine = _moteur()
            engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "p")
            assert engine.get_person_affect_context("p")

            mood = engine._get_person_mood("p")
            mood.last_declared_at = time.time() - 10_000  # fenêtre déclarée close
            _avancer(engine, 3 * 3600.0)
            assert pad.distance(
                mood.dynamic.position, engine._person_home(mood),
            ) < engine_module.REST_TOLERANCE
            assert engine.get_person_affect_context("p") == ""

    def test_une_stance_vivante_se_dit_toujours(self):
        engine = _moteur()
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "p")
        mood = engine._get_person_mood("p")
        mood.last_declared_at = time.time() - 10_000
        assert "en colère" in engine.get_person_affect_context("p")


# ===================================================================
# 4 — la vie intérieure sur l'humeur de fond
# ===================================================================

class TestVieInterieure:

    def _au_repos(self) -> tuple[EmotionEngine, pad.Vec3]:
        engine = _moteur()
        home = engine._home_vector()
        engine.global_mood.dynamic.position = home
        return engine, home

    def _huit_tints(self, intensite: float) -> tuple[EmotionEngine, pad.Vec3]:
        engine, home = self._au_repos()
        for index in range(8):
            engine.process_emotion(EmotionData(Emotion.BORED, intensite), "conscience_mika")
            if index < 7:
                _avancer(engine, 1800.0)
        return engine, home

    def test_huit_ennuis_demi_horaires_atteignent_l_humeur_de_fond(self):
        """Avant : ``hopeful 0.07`` — le neutre visé, puis le repos, et le
        bloc du prompt disant « comme d'habitude » pendant toute l'après-midi.

        Après : 20 % du chemin vers l'ennui, un libellé d'arousal négatif
        (``nostalgic``), et un bloc qui raconte un écart. Pas ``bored`` pour
        autant : à 30 min d'espacement contre τ_global = 23 min, huit
        impulsions à 0,25 en valent ~1,4 — c'est une calibration entre les
        constantes de la conscience et ``emotion.global_tau_factor``, que le
        test suivant montre franchissable.
        """
        engine, home = self._huit_tints(0.25)
        position = engine.global_mood.dynamic.position

        assert _progression(home, pad.EMOTION_ANCHORS[Emotion.BORED], position) >= 0.15
        assert pad.EMOTION_ANCHORS[engine.global_mood.emotion][1] <= 0.0, (
            f"un libellé encore éveillé : {engine.global_mood.emotion.value}"
        )
        assert "comme d'habitude" not in engine.get_global_mood_context()

    def test_un_ennui_un_peu_plus_appuye_se_nomme(self):
        """La même cadence à 0,4 lit ``bored`` : la voie est ouverte, la dose
        appartient à la conscience."""
        engine, _ = self._huit_tints(0.4)
        assert engine.global_mood.emotion in (Emotion.BORED, Emotion.LONELY), (
            engine.global_mood.emotion
        )

    def test_un_blocage_deplace_visiblement_la_valence(self):
        """Avant : 5 % du chemin, valence −0,04."""
        engine, home = self._au_repos()
        engine.process_emotion(EmotionData(Emotion.FRUSTRATED, 0.35), "conscience_mika")
        position = engine.global_mood.dynamic.position

        assert _progression(home, pad.EMOTION_ANCHORS[Emotion.FRUSTRATED], position) >= 0.15
        assert position[0] - home[0] <= -0.1

    def test_la_direction_est_celle_de_l_emotion_et_non_du_neutre(self):
        """Une intensité faible dose le pas, elle ne rapproche pas la cible
        de l'origine : une ``lonely 0.25`` tire vers ``lonely``."""
        engine, home = self._au_repos()
        engine.process_emotion(EmotionData(Emotion.LONELY, 0.25), "conscience_mika")
        deplacement = pad.sub(engine.global_mood.dynamic.position, home)
        vers_l_ancre = pad.sub(pad.EMOTION_ANCHORS[Emotion.LONELY], home)
        cos = pad.dot(deplacement, vers_l_ancre) / (
            pad.norm(deplacement) * pad.norm(vers_l_ancre)
        )
        assert cos == pytest.approx(1.0, abs=1e-6)

    def test_une_intensite_plus_forte_fait_un_pas_plus_grand(self):
        engine_a, home = self._au_repos()
        engine_b, _ = self._au_repos()
        engine_a.process_emotion(EmotionData(Emotion.PROUD, 0.4), "conscience_mika")
        engine_b.process_emotion(EmotionData(Emotion.PROUD, 0.9), "conscience_mika")
        assert (
            pad.distance(engine_b.global_mood.dynamic.position, home)
            > pad.distance(engine_a.global_mood.dynamic.position, home)
        )

    def test_la_diffusion_des_personnes_n_a_pas_bouge(self):
        """Les chiffres relationnels sont épinglés ailleurs ; ici on vérifie
        que le chemin d'une personne reste, à l'octet près, la diffusion."""
        from emotion.dynamics import apply_impulse

        engine, home = self._au_repos()
        cible = pad.label_to_pad(Emotion.HAPPY, 0.7)
        attendu = apply_impulse(home, cible, engine._global_impulse_params(0.7))
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.7), "web_quelqu_un")
        assert engine.global_mood.dynamic.position == pytest.approx(attendu)

    def test_un_pas_leger_reste_leger(self):
        """L'échec d'un tour pulse ``anxious 0.1`` sur elle-même : 5 % du
        chemin, pas un saut — même si un réglage aberrant porte le gain de
        personne hors de [0, 1], il est borné AVANT d'être dosé."""
        engine, home = self._au_repos()
        engine.process_emotion(EmotionData(Emotion.ANXIOUS, 0.1), "conscience_mika")
        assert _progression(
            home, pad.EMOTION_ANCHORS[Emotion.ANXIOUS], engine.global_mood.dynamic.position,
        ) == pytest.approx(0.1 * min(1.0, engine._person_params.impulse_gain), abs=1e-6)

        aberrant, home = self._au_repos()
        with patch.object(
            aberrant, "_person_impulse_params",
            return_value=dataclasses.replace(aberrant._person_params, impulse_gain=30.0),
        ):
            aberrant.process_emotion(EmotionData(Emotion.ANXIOUS, 0.1), "conscience_mika")
        assert _progression(
            home, pad.EMOTION_ANCHORS[Emotion.ANXIOUS], aberrant.global_mood.dynamic.position,
        ) == pytest.approx(0.1, abs=1e-6)

    def test_a_diffusion_nulle_elle_ressent_quand_meme_pour_elle_meme(self):
        """« À 0 elle compartimente entièrement » parle des personnes : sa
        propre vie n'a rien à compartimenter."""
        engine = _moteur(global_bleed=0.0)
        home = engine._home_vector()
        engine.global_mood.dynamic.position = home
        engine.process_emotion(EmotionData(Emotion.SAD, 0.5), "conscience_mika")
        assert pad.distance(engine.global_mood.dynamic.position, home) > 0.1

    def test_sa_stance_envers_elle_meme_reste_enregistree(self):
        """L'oscillateur « envers elle-même » part du repos comme tous les
        autres : c'est l'ÉCART au repos qui vire au négatif."""
        engine, _ = self._au_repos()
        repos = engine._home_vector()
        engine.process_emotion(EmotionData(Emotion.FRUSTRATED, 0.35), "conscience_mika")
        position = engine.person_moods["conscience_mika"].dynamic.position
        assert position[0] < repos[0] - 0.05


# ===================================================================
# 5 — l'intensité de débordement
# ===================================================================

class TestDebordement:

    FAMILLE_TRISTE = (
        Emotion.SAD, Emotion.FRUSTRATED, Emotion.MELANCHOLIC,
        Emotion.LONELY, Emotion.BORED,
    )

    def test_la_famille_triste_atteint_la_porte_de_debordement(self):
        """Avant : sad 0,73, frustrated 0,65, melancholic 0,62, bored 0,56."""
        for emotion in self.FAMILLE_TRISTE:
            ancre = pad.EMOTION_ANCHORS[emotion]
            assert pad.overflow_intensity(ancre) >= 0.7, emotion

    def test_l_intensite_declaree_se_relit_telle_quelle(self):
        """L'inverse de ``label_to_pad`` : ``sad × 0.8`` lit 0,8."""
        mood = GlobalMood()
        mood.dynamic.position = pad.label_to_pad(Emotion.SAD, 0.8)
        assert mood.overflow_intensity == pytest.approx(0.8)
        assert mood.intensity < 0.7, "l'échelle d'affichage, elle, n'a pas bougé"

    def test_la_detresse_est_atteignable(self):
        mood = GlobalMood()
        mood.dynamic.position = pad.label_to_pad(Emotion.SAD, 0.6)
        assert pad.valence(mood.emotion) <= -0.35
        assert mood.overflow_intensity >= 0.55

    def test_une_emotion_courte_ne_deborde_jamais(self):
        """``thinking`` (0,245) ou ``nostalgic`` (0,30) sont courtes par
        construction : rapportées à leur propre ancre, une humeur ordinaire
        dans leur cône aurait lu 1,0."""
        for emotion in (Emotion.THINKING, Emotion.NOSTALGIC):
            assert pad.overflow_intensity(pad.EMOTION_ANCHORS[emotion]) < 0.5
        dans_le_cone = pad.scale(pad.EMOTION_ANCHORS[Emotion.THINKING], 0.3 / 0.245)
        assert pad.overflow_intensity(dans_le_cone) < 0.7

    def test_une_heure_de_conversation_banale_ne_deborde_pas(self):
        """La porte de ``conscience/scoring.py`` reste calibrée sur la
        nouvelle échelle : le cycle de ``test_affect_echelle_temps``."""
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
            pic = max(pic, engine.global_mood.overflow_intensity)
            _avancer(engine, 60.0)
        assert pic < 0.7, pic

    def test_l_echelle_d_affichage_n_a_pas_bouge(self):
        """``pad_to_label`` garde la norme maximale : trames, blend, gestes et
        fiches lisent la même chose qu'avant."""
        _, intensite = pad.pad_to_label(pad.EMOTION_ANCHORS[Emotion.SAD])
        assert intensite == pytest.approx(0.73, abs=0.01)
        _, pleine = pad.pad_to_label(pad.EMOTION_ANCHORS[Emotion.EXCITED])
        assert pleine == pytest.approx(1.0)
