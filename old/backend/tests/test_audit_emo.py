"""Audit 2026-09-16, section 4 — Émotion et pulsions (EMO).

Un test par constat, vu rouge sur le code d'avant. Le fil directeur est
REF-02 : **l'humeur de fond se nomme par son écart au repos**, jamais dans
l'absolu. Le repos vaut ``default_mood × 0,15 + teinte circadienne`` (norme
0,27–0,50, toujours positif), si bien qu'un petit pas négatif de la vie
intérieure — ennui, blocage, solitude — s'ajoutait à un repos deux fois plus
long et lisait « à peine amusée ». Aucune émotion négative de sa propre vie
n'atteignait le prompt ni les portes de la conscience.

Le repos circadien est figé (comme les deux tests jadis instables l'ont
appris) sauf là où le défaut EST la teinte : ces tests-là posent une teinte
d'après-midi explicite.
"""
from __future__ import annotations

import ast
import inspect
import time
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async

from old.backend.emotion import pad
from old.backend.emotion.engine import EmotionEngine
from old.backend.emotion.state import DECLARED_WINDOW_S, GlobalMood, PersonMood, Temperament
from old.backend.emotion.types import Emotion, EmotionData
from old.backend.emotion import circadian

#: Une teinte d'après-midi : le repos a ``amused`` pour plus proche voisin
#: (norme ~0,48), le cas de l'audit à 14 h.
TEINTE_APRES_MIDI = (0.25, 0.20, 0.15)


@pytest.fixture(autouse=True)
def _repos_fixe():
    with patch.object(circadian, "phase_bias", return_value=(0.0, 0.0, 0.0)):
        yield


def _moteur(**temperament) -> EmotionEngine:
    engine = EmotionEngine()
    engine.temperament = Temperament(**temperament)
    engine._recompute_params()
    engine._initialized = True
    engine.global_mood.dynamic.position = engine._home_vector()
    engine.global_mood.home = engine._home_vector()
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


def _apres_midi():
    return patch.object(circadian, "phase_bias", return_value=TEINTE_APRES_MIDI)


# ===================================================================
# EMO-09 / REF-02 — la vie intérieure se nomme, par écart au repos
# ===================================================================

class TestLibelleParEcartAuRepos:

    def test_au_repos_l_ecart_ne_lit_rien(self):
        with _apres_midi():
            engine = _moteur()
            assert engine.global_mood.felt() == (Emotion.NEUTRAL, 0.0)
            assert engine.global_mood.overflow_intensity == 0.0
            assert "comme d'habitude" in engine.get_global_mood_context()

    def test_un_pas_vers_une_ancre_se_nomme_par_cette_ancre(self):
        """Comparé aux ancres brutes, l'écart d'un pas vers ``bored`` lisait
        ``melancholic``, vers ``frustrated`` ``disgusted``, vers ``sad``
        ``lonely`` : le rayon ``ancre − repos`` n'est pas l'ancre. Les
        directions se comparent donc aux rayons."""
        with _apres_midi():
            engine = _moteur()
            home = engine._home_vector()
            for emotion in (Emotion.BORED, Emotion.FRUSTRATED, Emotion.SAD,
                            Emotion.LONELY, Emotion.EXCITED, Emotion.HAPPY):
                cible = pad.EMOTION_ANCHORS[emotion]
                position = pad.add(home, pad.scale(pad.sub(cible, home), 0.3))
                assert pad.label_from_home(position, home)[0] is emotion, emotion

    def test_l_ennui_tenu_se_lit_lasse(self):
        """Avant : douze ``bored 0.4`` demi-horaires → « à peine amusée »
        (point fixe à 0,155 du repos). Maintenant, dosé en plateau (0,2 par
        dix minutes), il se tient à « légèrement lasse »."""
        with _apres_midi():
            engine = _moteur()
            for _ in range(12):
                engine.process_emotion(EmotionData(Emotion.BORED, 0.2), "conscience_mika")
                _avancer(engine, 600.0)
            prose = engine.get_global_mood_context()
        assert "lasse" in prose, prose
        assert "comme d'habitude" not in prose
        assert engine.global_mood.felt()[0] is Emotion.BORED

    def test_un_chantier_bloque_se_lit_frustree(self):
        """Avant : « légèrement excitée »."""
        with _apres_midi():
            engine = _moteur()
            engine.process_emotion(EmotionData(Emotion.FRUSTRATED, 0.35), "conscience_mika")
            prose = engine.get_global_mood_context()
        assert "frustrée" in prose, prose
        assert "excitée" not in prose

    def test_la_solitude_se_lit_seule(self):
        """Avant : « joueuse »."""
        with _apres_midi():
            engine = _moteur()
            engine.process_emotion(EmotionData(Emotion.LONELY, 0.3), "conscience_mika")
            prose = engine.get_global_mood_context()
        assert "seule" in prose, prose

    def test_le_repos_reste_physique(self):
        """Seul le LIBELLÉ change : l'oscillateur revient toujours au repos
        circadien, la face (position absolue) garde la teinte de l'heure."""
        with _apres_midi():
            engine = _moteur()
            home = engine._home_vector()
            engine.process_emotion(EmotionData(Emotion.SAD, 0.8), "conscience_mika")
            _avancer(engine, 4 * 3600.0)
            assert pad.distance(engine.global_mood.dynamic.position, home) < 0.02
            assert pad.pad_to_label(home)[0] is not Emotion.NEUTRAL

    def test_sans_repos_connu_l_origine_fait_office_de_repos(self):
        """Un ``GlobalMood`` nu (tests, doubles) garde sa lecture d'avant."""
        mood = GlobalMood()
        mood.dynamic.position = pad.label_to_pad(Emotion.SAD, 0.8)
        assert mood.felt()[0] is Emotion.SAD
        assert mood.overflow_intensity == pytest.approx(0.8)

    def test_la_nuance_parle_de_la_meme_geometrie(self):
        """Le blend du prompt se décompose sur l'écart et les rayons."""
        with _apres_midi():
            engine = _moteur()
            home = engine._home_vector()
            engine.global_mood.dynamic.position = pad.add(
                home,
                pad.add(
                    pad.scale(pad.sub(pad.EMOTION_ANCHORS[Emotion.SAD], home), 0.4),
                    pad.scale(pad.sub(pad.EMOTION_ANCHORS[Emotion.ANGRY], home), 0.3),
                ),
            )
            position = engine.global_mood.dynamic.position
            blend = pad.pad_to_blend(position, top_k=2, home=home)
            dominante, _ = pad.label_from_home(position, home)
        noms = {e for e, _ in blend}
        assert Emotion.NEUTRAL not in noms
        assert blend[0][0] is dominante
        assert pad.valence(dominante) < 0
        # Un rayon court (« pensive » pointe vers l'origine depuis un repos
        # positif) n'attrape pas le résidu de toute humeur sombre.
        assert Emotion.THINKING not in noms


# ===================================================================
# EMO-07 / EMO-08 / DEF-22 — les portes se franchissent par la tristesse,
# pas par l'anodin
# ===================================================================

class TestPortesDeLaConscience:

    def _tours(self, emotion, n=8, pid="web_x"):
        with _apres_midi():
            engine = _moteur()
            lectures = []
            for _ in range(n):
                engine.process_emotion(EmotionData(emotion, 0.8), pid)
                lectures.append(engine.global_mood.overflow_intensity)
                _avancer(engine, 90.0)
        return lectures

    def test_la_tristesse_de_quelqu_un_finit_par_deborder(self):
        """Avant : ``sad 0.8`` plafonnait à 0,64 sous la porte 0,7 — la
        tristesse ne pouvait structurellement pas la faire parler."""
        from old.backend.conscience.scoring import ScoringTuning

        porte = ScoringTuning().mood_gate
        assert max(self._tours(Emotion.SAD)) > porte
        assert max(self._tours(Emotion.ANGRY)) > porte

    def test_une_joie_ordinaire_ne_deborde_pas(self):
        """Le repos est déjà à mi-chemin de ``happy`` : la joie est son état
        normal, pas un débordement."""
        from old.backend.conscience.scoring import ScoringTuning

        assert max(self._tours(Emotion.HAPPY)) < ScoringTuning().mood_gate

    def test_les_etats_positifs_anodins_ne_franchissent_plus_la_porte(self):
        """Avant : le repos lisait 0,38–0,53 ; ``hopeful 0.25`` → 0,61 et
        ``surprised 0.35`` → 0,72, la porte franchie par une révision de
        croyance."""
        with _apres_midi():
            engine = _moteur()
            engine.process_emotion(EmotionData(Emotion.HOPEFUL, 0.25), "conscience_mika")
            assert engine.global_mood.overflow_intensity < 0.2
            engine.process_emotion(EmotionData(Emotion.SURPRISED, 0.35), "conscience_mika")
            assert engine.global_mood.overflow_intensity < 0.35

    def test_la_porte_vaut_0_6(self):
        from old.backend.conscience.scoring import ScoringTuning

        assert ScoringTuning().mood_gate == pytest.approx(0.6)

    def test_une_heure_de_conversation_banale_ne_deborde_pas(self):
        with _apres_midi():
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
                emotion, force = cycle[index % len(cycle)]
                engine.process_emotion(EmotionData(emotion, force), "p")
                pic = max(pic, engine.global_mood.overflow_intensity)
                _avancer(engine, 60.0)
        assert pic < 0.6, pic

    def test_la_conscience_lit_le_nom_ressenti(self):
        """``DecisionContext.global_mood`` porte l'écart, pas la teinte."""
        from old.backend.conscience.engine import _humeur_ressentie

        with _apres_midi():
            engine = _moteur()
            engine.process_emotion(EmotionData(Emotion.SAD, 0.6), "conscience_mika")
            assert engine.global_mood.emotion is not Emotion.SAD, "prémisse : l'absolu ment"
            assert _humeur_ressentie(engine.global_mood) == "sad"
        # Un double sans ``felt_emotion`` retombe sur ``emotion``.
        assert _humeur_ressentie(SimpleNamespace(emotion=Emotion.HAPPY)) == "happy"
        assert _humeur_ressentie(SimpleNamespace()) == ""

    def test_le_contexte_de_decision_passe_par_l_humeur_ressentie(self):
        from old.backend.conscience import engine as conscience_engine_module

        tree = ast.parse(inspect.getsource(conscience_engine_module))
        appels = {
            n.func.id
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "_humeur_ressentie" in appels

    def test_la_congruence_d_entree_lit_l_ecart(self):
        """Au repos (positif dans l'absolu), un signal positif pesait +15 %
        sans qu'elle ressente rien."""
        from old.backend.conscience.engine import ConscienceEngine

        e = ConscienceEngine.__new__(ConscienceEngine)
        with _apres_midi():
            engine = _moteur()
        with patch("conscience.perception.emotion_engine", engine):
            assert e._colorer_par_l_humeur(0.5, "happy") == pytest.approx(0.5)
            engine.process_emotion(EmotionData(Emotion.EXCITED, 0.8), "conscience_mika")
            assert e._colorer_par_l_humeur(0.5, "excited") > 0.5


# ===================================================================
# EMO-03 — elle ne s'excite plus avec ses propres actes
# ===================================================================

class TestSesPropresActes:

    def test_la_balise_d_un_monologue_passe_par_la_diffusion(self):
        """Avant : gain personne (0,51) × I vers l'ancre pleine → 0,73 de
        débordement pour un ``[EMOTION:excited:0.8]`` dit dans le vide."""
        from old.backend.conscience.scoring import ScoringTuning

        with _apres_midi():
            engine = _moteur()
            engine.process_emotion(
                EmotionData(Emotion.EXCITED, 0.8), "conscience_mika", declared=True,
            )
            declaree = engine.global_mood.overflow_intensity

            engine = _moteur()
            engine.process_emotion(EmotionData(Emotion.EXCITED, 0.8), "conscience_mika")
            programmee = engine.global_mood.overflow_intensity

        assert declaree < ScoringTuning().mood_gate
        assert declaree < programmee

    def test_les_impulsions_programmees_gardent_le_pas_dose(self):
        with _apres_midi():
            engine = _moteur()
            engine.process_emotion(EmotionData(Emotion.FRUSTRATED, 0.35), "conscience_mika")
            assert engine.global_mood.felt()[0] is Emotion.FRUSTRATED
            assert engine.global_mood.overflow_intensity > 0.1

    def test_declared_ne_change_rien_pour_une_personne(self):
        a, b = _moteur(), _moteur()
        a.process_emotion(EmotionData(Emotion.SAD, 0.8), "web_p")
        b.process_emotion(EmotionData(Emotion.SAD, 0.8), "web_p", declared=True)
        assert a.global_mood.dynamic.position == b.global_mood.dynamic.position
        assert a.person_moods["web_p"].dynamic.position == b.person_moods["web_p"].dynamic.position

    def test_le_processeur_declare_la_balise(self):
        from old.backend.pipeline import processor

        tree = ast.parse(inspect.getsource(processor))
        appels = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "process_emotion"
        ]
        declares = [
            n for n in appels
            if any(k.arg == "declared" and getattr(k.value, "value", None) is True
                   for k in n.keywords)
        ]
        assert declares, "la balise du tour doit passer declared=True"

    # ── REF-03 : les deux voies d'un identifiant interne, pinées une à une ──

    def test_la_balise_declaree_suit_exactement_la_diffusion_d_une_personne(self):
        """``declared=True`` sous ``conscience_mika`` N'EST PAS une troisième
        voie : c'est la diffusion personne → fond ordinaire, au chiffre près.
        Le fond bouge autant que si quelqu'un d'autre avait déclaré la
        même balise."""
        with _apres_midi():
            elle, autre = _moteur(), _moteur()
            elle.process_emotion(
                EmotionData(Emotion.EXCITED, 0.8), "conscience_mika", declared=True,
            )
            autre.process_emotion(EmotionData(Emotion.EXCITED, 0.8), "web_p")
        assert elle.global_mood.dynamic.position == autre.global_mood.dynamic.position

    def test_a_diffusion_nulle_la_balise_declaree_ne_touche_pas_le_fond(self):
        """La diffusion ordinaire passe par la porte ``global_bleed`` (« à 0
        elle compartimente entièrement ») ; la voie programmée, elle, l'ignore
        (``test_a_diffusion_nulle_elle_ressent_quand_meme_pour_elle_meme``).
        C'est la différence observable entre les deux voies."""
        with _apres_midi():
            engine = _moteur(global_bleed=0.0)
            repos = engine.global_mood.dynamic.position
            engine.process_emotion(
                EmotionData(Emotion.EXCITED, 0.8), "conscience_mika", declared=True,
            )
            assert engine.global_mood.dynamic.position == repos

            engine.process_emotion(EmotionData(Emotion.EXCITED, 0.8), "conscience_mika")
            assert engine.global_mood.dynamic.position != repos

    def test_la_vie_interieure_ne_se_declare_jamais(self):
        """Ennui, blocage, fierté, révision, solitude, espoir, soulagement :
        toute impulsion programmée par ``conscience/`` passe SANS ``declared``,
        donc par ``_feel_for_herself``. Parcourt le paquet entier, quel que
        soit le découpage de ses fichiers."""
        import pathlib

        import old.backend.conscience as conscience

        racine = pathlib.Path(conscience.__file__).parent
        appels = []
        for fichier in racine.rglob("*.py"):
            tree = ast.parse(fichier.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                if (
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "process_emotion"
                ):
                    appels.append((fichier.name, n))
        assert appels, "aucune impulsion programmée trouvée dans conscience/"
        internes = [
            (f, n) for f, n in appels
            if any(getattr(a, "value", None) == "conscience_mika" for a in n.args)
        ]
        assert internes, "la conscience doit ressentir sous conscience_mika"
        declares = [
            f"{f}:{n.lineno}" for f, n in appels
            if any(k.arg == "declared" for k in n.keywords)
        ]
        assert not declares, f"une impulsion de la vie intérieure se déclare : {declares}"


# ===================================================================
# EMO-01 — l'humeur de fond survit à un arrêt brutal
# ===================================================================

@pytest.mark.django_db(transaction=True)
class TestFondRestaure:

    @pytest.fixture(autouse=True)
    def _base(self):
        from old.backend.memory.models import Conversation, EmotionalSummary, EmotionSnapshot

        EmotionSnapshot.objects.all().delete()
        EmotionalSummary.objects.all().delete()
        self.conversation = Conversation.objects.create()
        yield
        EmotionSnapshot.objects.all().delete()
        EmotionalSummary.objects.all().delete()

    async def _ecrire(self, pid, emotion, intensite, global_emotion, global_intensite,
                      age_s=0.0, declared=True):
        from django.utils import timezone
        from old.backend.memory.models import EmotionSnapshot

        def _w():
            row = EmotionSnapshot.objects.create(
                conversation=self.conversation, person_id=pid,
                primary_emotion=emotion, primary_intensity=intensite,
                global_emotion=global_emotion, global_intensity=global_intensite,
                declared=declared,
            )
            EmotionSnapshot.objects.filter(pk=row.pk).update(
                created_at=timezone.now() - timedelta(seconds=age_s),
            )
        await sync_to_async(_w)()

    async def test_sans_ligne_d_arret_le_fond_se_relit_sur_le_dernier_releve(self):
        """Crash, OOM, SIGKILL : aucune ligne ``__global__`` fraîche, mais le
        relevé de tour porte ``global_emotion``."""
        await self._ecrire("web_a", "happy", 0.5, "sad", 0.7, age_s=60)
        engine = _moteur()
        assert await engine._restore_state() is True
        assert engine.global_mood.felt()[0] in (Emotion.SAD, Emotion.LONELY)

    async def test_le_releve_le_plus_recent_gagne(self):
        await self._ecrire("__global__", "sad", 0.7, "sad", 0.7, age_s=3600, declared=False)
        await self._ecrire("web_a", "happy", 0.5, "excited", 0.8, age_s=30)
        engine = _moteur()
        await engine._restore_state()
        assert engine.global_mood.felt()[0] in (Emotion.EXCITED, Emotion.PLAYFUL, Emotion.HAPPY)

    async def test_les_non_personnes_ne_sont_pas_rechargees(self):
        """EMO-02 : des relevés d'``anon_*`` / ``conscience_mika`` écrits
        avant la garde ne reviennent pas en RAM."""
        await self._ecrire("anon_1234", "angry", 0.8, "happy", 0.3)
        await self._ecrire("conscience_mika", "angry", 0.8, "happy", 0.3)
        await self._ecrire("web_a", "happy", 0.5, "happy", 0.3)
        engine = _moteur()
        await engine._restore_state()
        assert "anon_1234" not in engine.person_moods
        assert "conscience_mika" not in engine.person_moods
        assert "web_a" in engine.person_moods

    async def test_l_ancre_est_restauree_avec_la_position(self):
        """EMO-13 : jusqu'à la première lecture, ``_apply_decay`` ramenait la
        stance d'un ami vers le repos d'un inconnu."""
        for _ in range(4):
            await self._ecrire("web_a", "frustrated", 0.6, "happy", 0.3, age_s=120)
        engine = _moteur()
        await engine._restore_state()
        mood = engine.person_moods["web_a"]
        assert mood.anchor is not None
        assert pad.distance(mood.anchor, engine._home_vector()) > 0.05

    async def test_une_ligne_d_arret_est_une_position(self):
        """EMO-14 : ``_save_state`` écrit ``declared=False`` et la
        restauration prend la ligne telle quelle."""
        from old.backend.memory import manager as manager_module
        from old.backend.memory.models import EmotionSnapshot

        engine = _moteur()
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "web_a")
        position = engine.person_moods["web_a"].dynamic.position
        faux = SimpleNamespace(conversation=self.conversation)
        with patch.object(manager_module, "memory_manager", faux):
            await engine._save_state()
        lignes = await sync_to_async(
            lambda: list(EmotionSnapshot.objects.values_list("person_id", "declared"))
        )()
        assert ("__global__", False) in lignes and ("web_a", False) in lignes

        neuf = _moteur()
        await neuf._restore_state()
        restauree = neuf.person_moods["web_a"].dynamic.position
        # Pas de cliquet rejoué : la ligne portait l'étiquette de la position.
        etiquette = pad.label_to_pad(*pad.pad_to_label(position))
        assert pad.distance(restauree, etiquette) < 0.1

    async def test_un_releve_de_non_personne_n_est_jamais_ecrit(self):
        """EMO-02, à l'écriture."""
        from old.backend.memory import manager as manager_module
        from old.backend.memory.models import EmotionSnapshot

        engine = _moteur()
        faux = SimpleNamespace(conversation=self.conversation)
        with patch.object(manager_module, "memory_manager", faux):
            await engine.save_snapshot("anon_zz", EmotionData(Emotion.HAPPY, 0.5))
            await engine.save_snapshot("conscience_mika", EmotionData(Emotion.HAPPY, 0.5))
            await engine.save_snapshot("web_ok", EmotionData(Emotion.HAPPY, 0.5))
        pids = await sync_to_async(
            lambda: sorted(EmotionSnapshot.objects.values_list("person_id", flat=True))
        )()
        assert pids == ["web_ok"]

    async def test_l_agregation_ignore_les_non_personnes(self):
        from old.backend.memory.models import EmotionalSummary
        from old.backend.memory.storage.consolidator import MemoryConsolidator

        await self._ecrire("anon_zz", "happy", 0.5, "happy", 0.3)
        await self._ecrire("web_ok", "happy", 0.5, "happy", 0.3)
        c = MemoryConsolidator.__new__(MemoryConsolidator)
        c.vector_store = MagicMock()
        c.extractor = MagicMock()
        await c._aggregate_emotion_snapshots()
        pids = await sync_to_async(
            lambda: sorted(EmotionalSummary.objects.values_list("person_id", flat=True).distinct())
        )()
        assert "anon_zz" not in pids
        assert "web_ok" in pids


# ===================================================================
# EMO-04 / EMO-05 / EMO-12 / EMO-15 — ponctuels
# ===================================================================

class TestPonctuels:

    def test_snapshot_moods_est_une_copie(self):
        engine = _moteur()
        engine.process_emotion(EmotionData(Emotion.HAPPY, 0.5), "a")
        copie = engine.snapshot_moods()
        engine.person_moods["b"] = PersonMood(person_id="b")
        assert [pid for pid, _ in copie] == ["a"]
        assert engine.get_analytics()["persons_tracked"] == 2

    def test_la_vue_d_administration_itere_sur_la_copie(self):
        from old.backend.GestionSysteme.views import inner

        tree = ast.parse(inspect.getsource(inner))
        attrs = {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        }
        assert "snapshot_moods" in attrs
        # Plus aucune itération directe sur le dict vivant.
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr == "person_moods":
                pytest.fail("views/inner.py itère encore sur person_moods")

    def test_un_temperament_illisible_est_compte(self):
        from old.backend.emotion.state import load_temperament
        from old.backend.utils.degradation import degradations

        degradations.reset()
        with patch("configs.service.config_service.get", side_effect=RuntimeError("db locked")):
            t = load_temperament()
        assert t == Temperament()
        assert degradations.count_for("emotion.state.load_temperament") >= 1

    def test_un_inconnu_commence_au_repos(self):
        """EMO-12 : créé à l'origine, l'oscillateur dérivait vingt minutes
        vers la teinte de l'heure — visage neutre → joueuse après connexion."""
        with _apres_midi():
            engine = _moteur()
            mood = engine._get_person_mood("anon_neuf")
            assert pad.distance(mood.dynamic.position, engine._home_vector()) < 1e-9
            avant = engine.compute_message_emotion("anon_neuf").emotion
            _avancer(engine, 1200.0)
            assert engine.compute_message_emotion("anon_neuf").emotion is avant

    def test_au_dela_de_dix_tau_la_passe_pose_le_repos(self):
        """EMO-15 : une hibernation de cinq heures laissait 17 % de l'écart
        au fond (plafond d'une heure, sous-amortissement)."""
        engine = _moteur()
        home = engine._home_vector()
        engine.global_mood.dynamic.position = pad.label_to_pad(Emotion.SAD, 0.8)
        engine.global_mood.dynamic.velocity = (0.1, 0.1, 0.1)
        engine.global_mood.last_update = time.time() - 5 * 3600.0
        engine._apply_decay()
        assert pad.distance(engine.global_mood.dynamic.position, home) < 1e-9
        assert engine.global_mood.dynamic.velocity == pad.zero()

    def test_le_rattrapage_vaut_trois_heures(self):
        from old.backend.emotion import physics

        assert physics._MAX_ADVANCE_SECONDS == pytest.approx(10800.0)

    def test_la_fenetre_declaree_couvre_le_retour_au_repos(self):
        """EMO-06 / DEF-04 : à 700 s la position lisait encore « determined »
        après une colère ; la fenêtre tient jusqu'au repos."""
        assert DECLARED_WINDOW_S == pytest.approx(1200.0)
        engine = _moteur()
        engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "p")
        mood = engine._get_person_mood("p")
        mood.last_declared_at = time.time() - 10_000
        _avancer(engine, 700.0)
        prose = engine.get_person_affect_context("p")
        assert "déterminée" not in prose and "joueuse" not in prose, prose
        assert prose == "" or "en colère" in prose, prose


# ===================================================================
# La stance envers quelqu'un : écart au repos propre, et le fond installé
# ===================================================================

class TestStanceParEcart:

    def test_apres_la_fenetre_la_stance_dit_encore_l_emotion_qui_l_a_creee(self):
        with _apres_midi():
            engine = _moteur()
            engine.process_emotion(EmotionData(Emotion.ANGRY, 0.8), "p")
            mood = engine._get_person_mood("p")
            mood.last_declared_at = time.time() - 10_000
            _avancer(engine, 300.0)
            prose = engine.get_person_affect_context("p")
        assert "en colère" in prose, prose

    def test_un_fond_installe_se_dit_meme_au_repos(self):
        """L'ancre entrait dans la physique et dans le choix du destinataire,
        jamais dans la prose : une brouille installée et un inconnu se
        décrivaient de la même phrase dès que l'instant était calme."""
        with _apres_midi():
            engine = _moteur()
            mood = engine._get_person_mood("p")
            mood.anchor = pad.label_to_pad(Emotion.FRUSTRATED, 0.6)
            mood.dynamic.position = engine._person_home(mood)
            prose = engine.get_person_affect_context("p")
        assert "fond" in prose and "frustrée" in prose, prose

    def test_un_inconnu_n_a_toujours_pas_de_stance(self):
        with _apres_midi():
            engine = _moteur()
            assert engine.get_person_affect_context("inconnu") == ""
            _avancer(engine, 600.0)
            assert engine.get_person_affect_context("inconnu") == ""


# ===================================================================
# DEF-06 / DEF-17 — la saignée et l'ennui se voient
# ===================================================================

class TestDosagesVisibles:

    def test_la_saignee_d_une_rumination_atteint_le_prompt(self):
        """À 0,15, « Je bloque sur… » (0,35) versait ``frustrated 0.05`` par
        dix minutes : régime permanent à 7 % de l'écart, sous la tolérance."""
        from old.backend.conscience import ruminations

        part = ruminations._RUMINATION_BLEED_INTENSITY
        assert part == pytest.approx(0.35)
        with _apres_midi():
            engine = _moteur()
            for _ in range(24):
                engine.process_emotion(
                    EmotionData(Emotion.FRUSTRATED, 0.35 * part), "conscience_mika",
                )
                _avancer(engine, 600.0)
            prose = engine.get_global_mood_context()
        assert "frustrée" in prose, prose

    def test_l_ennui_est_un_etat_tenu(self):
        from old.backend.conscience import affects

        assert affects._ENNUI_INTENSITE == pytest.approx(0.2)
        assert affects._ENNUI_INTERVAL_S == pytest.approx(600.0)
        with _apres_midi():
            engine = _moteur()
            ecarts = []
            for _ in range(12):
                engine.process_emotion(EmotionData(Emotion.BORED, 0.2), "conscience_mika")
                _avancer(engine, 600.0)
                ecarts.append(engine.global_mood.overflow_intensity)
        # Un plateau : après la montée, l'écart ne retombe plus sous la
        # tolérance entre deux impulsions.
        assert min(ecarts[6:]) > 0.1


# ===================================================================
# EMO-11 / REF-05 — la solitude, c'est quelqu'un qui manque
# ===================================================================

class TestSolitudeRelative:

    def _moteur(self):
        from old.backend.conscience.engine import ConscienceEngine

        e = ConscienceEngine.__new__(ConscienceEngine)
        e._threshold = 0.5
        e._dernier_ennui = 0.0
        e._manque_verifie_le = 0.0
        e._manque_present = False
        return e

    def _ctx(self, **kw):
        from old.backend.conscience.types import DecisionContext

        base = dict(
            pending_observations=[], global_mood="curious", global_intensity=0.3,
            idle_seconds=3 * 3600, in_cooldown=False, max_pertinence=0.0,
            weighted_urgency=0.0,
        )
        base.update(kw)
        return DecisionContext(**base)

    async def _vide(self, e, social=0.1):
        from old.backend.drives.state import DriveKind

        with patch("conscience.affects.emotion_engine") as moteur, patch(
            "conscience.affects.drive_engine",
        ) as de:
            de.states = {DriveKind.SOCIAL: SimpleNamespace(tension=social)}
            await e._peut_etre_s_ennuyer(self._ctx(), travaux=[])
        return moteur

    async def test_quelqu_un_qui_manque_rend_le_vide_solitaire(self):
        """SOCIAL bas (≈ 18 h de silence avant l'ancienne solitude), mais un
        ami quotidien muet depuis trois jours : c'est de la solitude."""
        e = self._moteur()
        e.memory = SimpleNamespace(who_misses_contact=AsyncMock(return_value=[{"name": "Alice"}]))
        moteur = await self._vide(e, social=0.1)
        data, personne = moteur.process_emotion.call_args.args
        assert data.emotion is Emotion.LONELY
        assert personne == "conscience_mika"

    async def test_sans_manque_ni_tension_c_est_de_l_ennui(self):
        e = self._moteur()
        e.memory = SimpleNamespace(who_misses_contact=AsyncMock(return_value=[]))
        moteur = await self._vide(e, social=0.1)
        data, _ = moteur.process_emotion.call_args.args
        assert data.emotion is Emotion.BORED

    async def test_le_manque_n_est_verifie_qu_une_fois_par_demi_heure(self):
        e = self._moteur()
        e.memory = SimpleNamespace(who_misses_contact=AsyncMock(return_value=[]))
        await self._vide(e)
        e._dernier_ennui = 0.0
        await self._vide(e)
        assert e.memory.who_misses_contact.await_count == 1

    async def test_une_memoire_en_panne_ne_casse_pas_l_ennui(self):
        e = self._moteur()
        e.memory = SimpleNamespace(who_misses_contact=AsyncMock(side_effect=RuntimeError("db")))
        moteur = await self._vide(e, social=0.1)
        data, _ = moteur.process_emotion.call_args.args
        assert data.emotion is Emotion.BORED


# ===================================================================
# EMO-10 / REF-04 / DEF-01..03 — la fatigue est du temps, pas des messages
# ===================================================================

class TestFatigueHumaine:

    def test_les_anciennes_cles_par_evenement_ont_disparu(self):
        from old.backend.configs.registry import registry

        assert registry.get("drives.rest.pressure_per_event") is None
        assert registry.get("drives.rest.max_gain_per_update") is None
        assert registry.get("drives.rest.growth_per_active_hour") is not None

    def test_le_coucher_n_avance_que_d_une_heure(self):
        from old.backend.memory.sleep import EARLY_NIGHT_MAX_ADVANCE_HOURS

        assert EARLY_NIGHT_MAX_ADVANCE_HOURS == 1

    def test_la_decroissance_vaut_0_72_par_heure(self):
        from old.backend.drives.engine import _REST_NATURAL_DECAY

        assert _REST_NATURAL_DECAY == pytest.approx(0.0002)
