"""Non-régression des correctifs de la vie intérieure.

Chaque classe correspond à un défaut trouvé par l'audit adverse et réparé.
Les tests décrivent le comportement VOULU ; ils remplacent les tests d'audit
temporaires qui, eux, affirmaient les défauts.

Le fil conducteur des huit correctifs est le même : **un état écrit par un
sous-système était relu par un autre qui lui donnait un sens différent**. On
nomme désormais la nature de chaque valeur partagée — une durée est une durée,
une déclaration est une déclaration, un curseur ne bouge que sur un succès.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone
from unittest.mock import AsyncMock, MagicMock

from emotion import circadian, pad
from emotion.types import Emotion, EmotionData


# ══════════════════════════════════════════════════════════════════════
# 1. La pensée vieillit en heures, pas en tours de boucle
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestRuminationEnTempsReel:
    """`intensity *= 0.95` par cycle de 30 s tuait une pensée en 22 minutes,
    alors que tous ses lecteurs raisonnent en heures — la digestion nocturne
    exige 120 minutes d'âge. L'intersection était vide : la phase de guérison
    du sommeil profond n'a jamais eu quoi que ce soit à digérer."""

    @staticmethod
    async def _rumination(intensite=0.8, emotion="frustrated", age_h=0.0):
        from conscience.models import Rumination

        r = await sync_to_async(Rumination.objects.create)(
            summary="j'ai peut-etre ete trop seche", themes=[],
            intensity=intensite, emotion=emotion, status="active",
        )
        if age_h:
            quand = timezone.now() - timedelta(hours=age_h)
            await sync_to_async(
                lambda: Rumination.objects.filter(pk=r.pk).update(
                    created_at=quand, decayed_at=quand)
            )()
        return r

    async def test_une_pensee_fraiche_ne_vieillit_pas_avec_les_cycles(self):
        """Cinquante tours de boucle d'affilée ne consomment rien."""
        from conscience.engine import conscience_engine

        r = await self._rumination(intensite=0.9)
        for _ in range(50):
            await conscience_engine._decay_ruminations()

        await sync_to_async(r.refresh_from_db)()
        assert r.status == "active"
        assert r.intensity == pytest.approx(0.9, abs=1e-3)

    async def test_la_demi_vie_est_bien_celle_annoncee(self):
        from conscience.engine import conscience_engine

        r = await self._rumination(intensite=0.8, age_h=6.0)
        await conscience_engine._decay_ruminations()
        await sync_to_async(r.refresh_from_db)()
        assert r.intensity == pytest.approx(0.4, abs=0.005)

    async def test_les_petits_ticks_ne_perdent_pas_le_temps_ecoule(self):
        """`decayed_at` n'avance qu'à l'écriture : repasser vingt fois sur la
        même ancre donne exactement le même résultat qu'un seul passage."""
        from conscience.engine import conscience_engine

        r = await self._rumination(intensite=0.8, age_h=6.0)
        for _ in range(20):
            await conscience_engine._decay_ruminations()
        await sync_to_async(r.refresh_from_db)()
        assert r.intensity == pytest.approx(0.4, abs=0.01)

    async def test_la_nuit_trouve_enfin_quelque_chose_a_digerer(self):
        """Le bout en bout : une contrariété du soir est encore là à 3 h."""
        from conscience.models import Rumination
        from memory.sleep import sleep_cycle

        # Les lignes des autres tests de la classe sont fraîches (âge 0) et
        # ne franchissent donc pas le filtre d'âge de la digestion.
        r = await self._rumination(intensite=0.8, emotion="frustrated", age_h=2.5)
        traitees = await sleep_cycle._digest_ruminations()

        await sync_to_async(r.refresh_from_db)()
        assert traitees >= 1, "la phase de guérison ne doit plus tourner à vide"
        assert r.emotion == "relieved", "dérive frustrated → relieved"
        assert r.status == "active"
        assert await sync_to_async(
            Rumination.objects.filter(pk=r.pk).exists)()

    async def test_le_saignement_dans_l_humeur_est_espace(self):
        """Une pensée teinte l'humeur, elle ne la matraque pas : maintenant
        qu'elle vit des heures, saigner à chaque cycle de 30 s clouerait
        l'humeur globale sur son émotion toute la soirée."""
        from conscience.engine import conscience_engine

        conscience_engine._rumination_bleed_at.clear()
        appels = []
        conscience_engine._bleed_ruminations([("frustrated", 0.8)])
        appels.append(len(conscience_engine._rumination_bleed_at))
        for _ in range(10):
            conscience_engine._bleed_ruminations([("frustrated", 0.8)])
        assert appels[0] == 1
        # Dix passes de plus n'ont pas reversé : l'espacement tient.
        assert len(conscience_engine._rumination_bleed_at) == 1


@pytest.mark.django_db
class TestCourseDigestionConscience:
    """La décroissance lisait son lot, gardait la main sur la boucle, puis
    écrivait : la digestion nocturne pouvait s'intercaler entre les deux et
    voir son `faded` réécrit en `active`. Lecture, calcul et écriture tiennent
    désormais dans un seul appel synchrone, que `sync_to_async` sérialise sur
    le même thread d'exécuteur que la digestion."""

    async def test_la_conscience_ne_ressuscite_plus_une_pensee_digeree(self, monkeypatch):
        from conscience.engine import conscience_engine
        from conscience.models import Rumination
        from memory.sleep import sleep_cycle

        def _setup():
            r = Rumination.objects.create(
                summary="pensee a digerer", themes=[], intensity=0.16,
                emotion="", status="active")
            vieux = timezone.now() - timedelta(hours=3)
            Rumination.objects.filter(pk=r.pk).update(
                created_at=vieux, updated_at=vieux, decayed_at=vieux)
            return r.pk

        pk = await sync_to_async(_setup)()
        vrai = sync_to_async
        intercale = {"fait": False}

        def _patched(fn, **kw):
            async def _runner(*a, **k):
                # On force la digestion nocturne à s'exécuter pendant la passe
                # de la conscience — l'entrelacement que le vrai système peut
                # produire, et que l'ancien code perdait.
                if getattr(fn, "__name__", "") == "_passe" and not intercale["fait"]:
                    intercale["fait"] = True
                    await sleep_cycle._digest_ruminations()
                return await vrai(fn, **kw)(*a, **k)
            return _runner

        monkeypatch.setattr("conscience.engine.sync_to_async", _patched)
        await conscience_engine._decay_ruminations()

        final = await vrai(
            lambda: Rumination.objects.values("status").get(pk=pk))()
        assert final["status"] == "faded", (
            "une pensée fanée par la nuit ne doit pas repasser active"
        )


# ══════════════════════════════════════════════════════════════════════
# 2. Ce qu'elle déclare est ce qu'on lui renvoie
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestEmotionDeclaree:
    """L'impulsion ne parcourt que la moitié de la distance à l'ancre
    déclarée ; le vecteur mélangé qui en résulte a souvent pour plus proche
    voisin une TROISIÈME émotion. Le prompt du tour suivant annonçait donc un
    sentiment qu'elle n'avait jamais prononcé."""

    @staticmethod
    def _moteur():
        from emotion.engine import EmotionEngine
        from emotion.state import Temperament

        m = EmotionEngine()
        m.temperament = Temperament()
        m._recompute_params()
        return m

    @pytest.mark.parametrize("depart,declaree", [
        (Emotion.MELANCHOLIC, Emotion.EMBARRASSED),
        (Emotion.SAD, Emotion.HAPPY),
        (Emotion.ANGRY, Emotion.GRATEFUL),
        (Emotion.EXCITED, Emotion.ANXIOUS),
        (Emotion.LONELY, Emotion.AMUSED),
    ])
    def test_le_prompt_nomme_l_emotion_declaree(self, depart, declaree):
        from GestionSysteme.formatting import emotion_fr
        from emotion.state import PersonMood

        m = self._moteur()
        mood = PersonMood(person_id="p")
        mood.dynamic.position = pad.label_to_pad(depart, 0.45)
        m.person_moods["p"] = mood

        m.process_emotion(EmotionData(declaree, 0.8), "p")
        texte = m.get_person_affect_context("p")
        assert emotion_fr(declaree.value) in texte

    def test_l_intensite_declaree_n_est_pas_ecrasee(self):
        m = self._moteur()
        m.process_emotion(EmotionData(Emotion.AMUSED, 0.8), "p")
        assert "tres" in m.get_person_affect_context("p")

    def test_passee_la_fenetre_c_est_l_oscillateur_qui_reprend(self):
        """La balise dit ce qu'elle a éprouvé en écrivant ; passé son temps
        de validité, c'est la position qui dit où en est la relation."""
        from emotion.state import DECLARED_WINDOW_S, PersonMood

        mood = PersonMood(person_id="p")
        mood.dynamic.position = pad.label_to_pad(Emotion.MELANCHOLIC, 0.6)
        mood.last_declared = (Emotion.HAPPY, 0.8)
        mood.last_declared_at = time.time() - (DECLARED_WINDOW_S + 10)
        texte = mood.to_prompt_description()
        assert "contente" not in texte

    def test_une_declaration_faible_n_est_plus_avalee(self):
        """Un tour qui déclare `[EMOTION:thinking:0.4]` a un ressenti, même si
        le vecteur correspondant est court : se taire perdait ce dont on est
        le plus sûr."""
        m = self._moteur()
        m.process_emotion(EmotionData(Emotion.THINKING, 0.35), "p")
        assert m.get_person_affect_context("p") != ""


# ══════════════════════════════════════════════════════════════════════
# 3. L'oubli déplace, il ne détruit pas
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestSouvenirEndormi:

    @staticmethod
    async def _decay():
        from memory.storage.consolidator import MemoryConsolidator

        c = MemoryConsolidator(MagicMock(), MagicMock())
        c._index = AsyncMock(return_value=None)
        from memory.storage import consolidator as mod
        original = mod.vector_call
        mod.vector_call = lambda f: AsyncMock(return_value=None)
        try:
            await c._decay_souvenirs()
        finally:
            mod.vector_call = original

    async def test_un_souvenir_de_soixante_jours_existe_encore(self):
        from memory.models import Souvenir
        from memory.storage.consolidator import _dormant_floor

        vieux = timezone.now() - timedelta(days=60)
        s = await sync_to_async(Souvenir.objects.create)(
            content="Thomas m'a annonce qu'il se marie", emotion="happy",
            importance=1.0, occurred_at=vieux)
        await sync_to_async(
            lambda: Souvenir.objects.filter(pk=s.pk).update(decayed_at=vieux))()

        await self._decay()
        assert await sync_to_async(Souvenir.objects.filter(pk=s.pk).exists)()
        await sync_to_async(s.refresh_from_db)()
        assert s.importance < 0.1, "il est sorti du rappel spontané"
        assert s.importance >= _dormant_floor(0.1)


@pytest.mark.django_db
class TestImportanceMesuree:
    """`importance` était écrite 1.0 en dur pour tout le monde alors que le
    retriever la promeut en poids de rang — le poids ne départageait donc rien
    à la naissance et faisait doublon avec la récence."""

    async def test_l_extraction_decide_de_l_importance(self):
        from memory.models import Souvenir
        from memory.storage.consolidator import MemoryConsolidator

        c = MemoryConsolidator(MagicMock(), MagicMock())
        c._index = AsyncMock(return_value=None)
        await c.store_extractions([
            {"type": "souvenir", "content": "il m'a dit qu'il partait",
             "emotion": "sad", "importance": 0.95},
            {"type": "souvenir", "content": "on a parle de la meteo",
             "emotion": "neutral", "importance": 0.15},
        ], interlocutors=[])

        valeurs = {
            s.content: s.importance
            async for s in Souvenir.objects.all()
        }
        assert valeurs["il m'a dit qu'il partait"] == pytest.approx(0.95)
        assert valeurs["on a parle de la meteo"] == pytest.approx(0.15)

    def test_une_extraction_muette_prend_le_milieu_du_bareme(self):
        from memory.storage.consolidator import DEFAULT_IMPORTANCE, _extracted_importance

        assert _extracted_importance({}) == DEFAULT_IMPORTANCE
        assert _extracted_importance({"importance": "n'importe quoi"}) == DEFAULT_IMPORTANCE
        assert _extracted_importance({"importance": 3.0}) == 1.0
        assert _extracted_importance({"importance": 0.0}) == 0.05

    def test_le_bareme_est_donne_au_modele(self):
        from memory.extraction.extractor import EXTRACTION_PROMPT_TEMPLATE

        assert "importance" in EXTRACTION_PROMPT_TEMPLATE


# ══════════════════════════════════════════════════════════════════════
# 4. Une stance envers quelqu'un guérit, et survit au redémarrage
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestAncrePersonne:

    @staticmethod
    def _brouille(monkeypatch, tours=40):
        from emotion.engine import EmotionEngine
        from emotion.state import Temperament

        monkeypatch.setattr(circadian, "phase_bias", lambda *a, **k: (0.0, 0.0, 0.0))
        m = EmotionEngine()
        m.temperament = Temperament()
        m._recompute_params()
        for _ in range(tours):
            m.process_emotion(EmotionData(Emotion.FRUSTRATED, 0.6), "p")
            mood = m.person_moods["p"]
            m._note_anchor(mood, pad.label_to_pad(Emotion.FRUSTRATED, 0.6))
            mood.last_update = time.time() - 90
            m.global_mood.last_update = time.time() - 90
            m._apply_decay()
        return m

    def test_le_temps_seul_emousse_la_rancune(self, monkeypatch):
        """Deux écrivains déplaçaient l'ancre — un relevé, une réhydratation —
        et aucun ne la ramenait vers le neutre : une brouille était encore là
        mot pour mot 24 h plus tard."""
        m = self._brouille(monkeypatch)
        mood = m.person_moods["p"]
        depart = pad.norm(mood.anchor)

        for _ in range(14 * 24):  # deux semaines de silence, heure par heure
            mood.last_update = time.time() - 3600
            m.global_mood.last_update = time.time() - 3600
            m._apply_decay()

        assert pad.norm(mood.anchor) < depart * 0.4

    def test_une_conversation_pese_bien_plus_que_le_temps(self, monkeypatch):
        """La guérison doit être LENTE devant les mots, sinon l'attachement ne
        se construirait jamais."""
        m = self._brouille(monkeypatch, tours=5)
        mood = m.person_moods["p"]
        avant = pad.norm(mood.anchor)

        m._heal_anchor(mood, m._home_vector(), dt=3600.0)  # une heure
        apres_temps = pad.norm(mood.anchor)
        m._note_anchor(mood, pad.label_to_pad(Emotion.HAPPY, 0.8))  # un tour
        apres_mot = pad.norm(mood.anchor)

        assert abs(avant - apres_temps) < abs(apres_temps - apres_mot)

    async def test_l_ancre_est_recalculee_apres_un_redemarrage(self):
        """`_restore_state` repeuple `person_moods` sans ancre, et
        `ensure_person_loaded` — la seule à savoir la recalculer — sortait
        immédiatement parce que la personne était déjà en RAM."""
        from emotion.engine import EmotionEngine
        from memory.models import Conversation, EmotionSnapshot

        pid = "web_ancre_boot"

        def _semer():
            conv = Conversation.objects.create()
            for _ in range(6):
                EmotionSnapshot.objects.create(
                    conversation=conv, person_id=pid,
                    primary_emotion="frustrated", primary_intensity=0.6,
                    global_emotion="happy", global_intensity=0.3)

        await sync_to_async(_semer)()
        m = EmotionEngine()
        assert await m._restore_state() is True
        assert pid in m.person_moods

        await m.ensure_person_loaded(pid)
        assert m.person_moods[pid].anchor is not None


# ══════════════════════════════════════════════════════════════════════
# 5. Elle réessaie plus tard, elle ne répète pas toutes les cinq minutes
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestInitiativeEspacee:
    """Inactivité +0.30, « on m'ignore » −0.30, pulsions +0.50 : la somme vaut
    exactement le seuil, comparé avec `>=`. Aucun nombre de messages sans
    réponse ne pouvait la faire taire, et le cooldown étant constant, elle
    dépensait ses cinq initiatives du jour en vingt minutes."""

    @staticmethod
    def _ctx(**kw):
        from conscience.types import DecisionContext

        base = dict(
            pending_observations=[], global_mood="hopeful", global_intensity=0.3,
            idle_seconds=43_748, in_cooldown=False, max_pertinence=0.0,
            weighted_urgency=0.0, drive_bonus=0.50, drive_summary="", energy=1.0,
        )
        base.update(kw)
        return DecisionContext(**base)

    def test_l_attente_s_allonge_a_chaque_relance_ignoree(self):
        from conscience.engine import ConscienceEngine

        e = ConscienceEngine()
        e._cooldown_seconds = 300
        attentes = [e._effective_cooldown(n) for n in range(5)]
        assert attentes == sorted(attentes)
        assert attentes[3] > 4 * attentes[0]

    def test_l_attente_est_plafonnee(self):
        from conscience.engine import ConscienceEngine

        e = ConscienceEngine()
        e._cooldown_seconds = 300
        assert e._effective_cooldown(50) == e._COOLDOWN_MAX_S

    def test_les_cinq_relances_s_etalent_sur_des_heures(self):
        from conscience.scoring import compute_decision_score
        from conscience.engine import ConscienceEngine

        e = ConscienceEngine()
        e._cooldown_seconds = 300
        greeted = {"morning", "afternoon", "evening", "night"}
        actes, ignores, acts_today = [], 0, 0
        for minute in range(0, 24 * 60, 5):
            attente = e._effective_cooldown(ignores) / 60
            en_cd = bool(actes) and (minute - actes[-1]) < attente
            score, _, _, _ = compute_decision_score(
                self._ctx(idle_seconds=43_448 + minute * 60, in_cooldown=en_cd,
                          acts_today=acts_today, consecutive_ignored_acts=ignores),
                greeted_periods=greeted, greeted_date=date.today())
            if score >= 0.5:
                actes.append(minute)
                acts_today += 1
                ignores += 1

        assert len(actes) <= 5
        assert actes[-1] - actes[0] >= 180, "au moins trois heures d'étalement"


# ══════════════════════════════════════════════════════════════════════
# 6. Le curseur n'avance que sur un succès réel
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestCheckpointConsolidateur:

    @staticmethod
    def _conso(extractions):
        from memory.storage.consolidator import MemoryConsolidator

        c = MemoryConsolidator(MagicMock(), MagicMock())
        c._index = AsyncMock(return_value=None)
        c.extractor = MagicMock()
        c.extractor.analyze_messages = AsyncMock(return_value=extractions)
        c._resolve_interlocutors = AsyncMock(return_value=[])
        return c

    async def test_un_echec_total_gele_la_fenetre(self):
        c = self._conso([{"type": "souvenir", "content": "a"},
                         {"type": "souvenir", "content": "b"}])

        async def _boom(*a, **k):
            raise RuntimeError("database is locked")

        c._store_souvenir = _boom
        msgs = [{"id": i, "role": "user", "content": "x", "created_at": None}
                for i in (1, 2, 3)]
        counts, through = await c._extract_and_store(msgs)
        assert through is None, "la fenêtre doit rester relisable"
        assert counts["echouees"] == counts["tentees"] == 2

    async def test_un_echec_partiel_n_empoisonne_pas_la_fenetre(self):
        c = self._conso([{"type": "souvenir", "content": "a"},
                         {"type": "souvenir", "content": "b"}])
        appels = {"n": 0}

        async def _parfois(*a, **k):
            appels["n"] += 1
            if appels["n"] == 1:
                raise RuntimeError("celle-ci est malformee")
            return "souvenirs"

        c._store_souvenir = _parfois
        msgs = [{"id": 7, "role": "user", "content": "x", "created_at": None}]
        _counts, through = await c._extract_and_store(msgs)
        assert through == 7

    async def test_une_fenetre_sans_rien_a_retenir_avance(self):
        """« Rien d'important » et « tout a échoué » ne doivent pas se
        confondre : le premier cas est le fonctionnement normal."""
        c = self._conso([])
        msgs = [{"id": 12, "role": "user", "content": "salut", "created_at": None}]
        _counts, through = await c._extract_and_store(msgs)
        assert through == 12

    async def test_entites_en_liste_de_chaines_sont_tolerees(self):
        """Un petit modèle local rend régulièrement `["Thomas"]` là où le
        gabarit demande des objets ; l'indexation directe levait alors une
        TypeError sur la PREMIÈRE entité de CHAQUE extraction."""
        from memory.models import Souvenir

        c = self._conso([])
        counts = await c.store_extractions([
            {"type": "souvenir", "content": "on a ri", "emotion": "happy",
             "importance": 0.6, "themes": ["rire"], "entities": ["Thomas"]},
        ], interlocutors=[])
        assert counts["echouees"] == 0
        assert counts["souvenirs"] == 1
        assert await sync_to_async(
            Souvenir.objects.filter(content="on a ri").exists)()


# ══════════════════════════════════════════════════════════════════════
# 7. Ce qu'on a compilé sur quelqu'un ne se raconte pas à un inconnu
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestFrontiereIntime:

    @staticmethod
    async def _entite(nom):
        from memory.models import Entity

        e, _ = await sync_to_async(Entity.objects.get_or_create)(
            name=nom, entity_type="person")
        return e

    @staticmethod
    async def _souvenir(contenu, emotion="sad"):
        from memory.models import Souvenir

        return await sync_to_async(Souvenir.objects.create)(
            content=contenu, emotion=emotion, importance=0.9,
            occurred_at=timezone.now())

    async def test_la_confidence_d_un_tiers_ne_sort_pas_sous_le_seuil(self):
        from memory.retrieval.retriever import MemoryRetriever

        alice = await self._entite("AliceConf")
        s = await self._souvenir("AliceConf m'a confie qu'elle a rechute")
        await sync_to_async(s.entities.set)([alice])

        vs = MagicMock()
        vs.search_souvenirs.return_value = [
            {"id": str(s.pk), "content": s.content, "distance": 0.1, "metadata": {}}]
        vs.search_connaissances.return_value = []
        r = MemoryRetriever(vs)

        assert "rechute" in await r.retrieve("sante", person_id="web_bob")
        assert "rechute" not in await r.retrieve(
            "sante", person_id="web_bob", disclose_others=False)

    async def test_les_voies_non_lexicales_sont_filtrees_aussi(self):
        from memory.models import Theme
        from memory.retrieval.retriever import MemoryRetriever

        theme, _ = await sync_to_async(Theme.objects.get_or_create)(name="santeconf")
        alice = await self._entite("AliceAssoc")
        lie = await self._souvenir("AliceAssoc ne dort plus")
        await sync_to_async(lie.themes.set)([theme])
        await sync_to_async(lie.entities.set)([alice])

        r = MemoryRetriever(MagicMock())
        ancre = [{"id": 999_999, "themes": ["santeconf"], "entities": []}]
        assert len(await r._associative_expansion(ancre, set())) == 1
        assert await r._associative_expansion(
            ancre, set(), disclose_others=False) == []

    async def test_on_ne_l_ampute_pas_de_sa_propre_memoire(self):
        """Ce qui concerne la personne EN FACE, et ce qu'elle a vécu seule,
        continuent de remonter porte fermée."""
        from memory.retrieval.retriever import MemoryRetriever

        bob = await self._entite("BobPropre")
        avec = await self._souvenir("BobPropre et moi avons ri", emotion="happy")
        await sync_to_async(avec.entities.set)([bob])
        seule = await self._souvenir("j'ai regarde la pluie", emotion="melancholic")

        r = MemoryRetriever(MagicMock())
        for s, nom in ((avec, "BobPropre"), (seule, "")):
            charges = await r._enrich_souvenirs(
                [{"id": str(s.pk), "content": s.content,
                  "distance": 0.1, "metadata": {}}],
                boost_name=nom, disclose_others=False)
            assert len(charges) == 1

    async def test_le_journal_garde_son_fil_sans_nommer_les_gens(self):
        from memory.models import DailyJournal
        from pipeline.context import _fetch_journal_context

        hier = (timezone.now() - timedelta(days=1)).date()
        await sync_to_async(DailyJournal.objects.update_or_create)(
            date=hier, defaults=dict(
                narrative="Thomas m'a raconte que sa mere etait hospitalisee.",
                persons_interacted=["Thomas"], dominant_emotion="sad"))

        ouvert = await _fetch_journal_context(may_disclose=True)
        ferme = await _fetch_journal_context(may_disclose=False)

        assert "Thomas" in ouvert
        assert "Thomas" not in ferme
        assert "quelqu'un" in ferme
        assert "hospitalisee" in ferme, "le fil reste le sien"


# ══════════════════════════════════════════════════════════════════════
# 8. Deuxième passe — ce qui reste après les huit premiers correctifs
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestHumeurGlobaleReactive:
    """`--- TON ETAT EMOTIONNEL ACTUEL ---` est le dernier bloc affectif avant
    la mémoire, donc celui que le modèle lit le plus fort — et c'était le plus
    lent de tous à bouger. À gain fixe, il annonçait encore « contente, comme
    d'habitude » au sixième tour d'une conversation qui finit en larmes."""

    @staticmethod
    def _moteur(monkeypatch, temperament=None):
        from emotion.engine import EmotionEngine
        from emotion.state import Temperament

        monkeypatch.setattr(circadian, "phase_bias", lambda *a, **k: (0.0, 0.0, 0.0))
        m = EmotionEngine()
        m.temperament = temperament or Temperament()
        m._recompute_params()
        return m

    def test_une_detresse_est_remarquee_des_le_premier_tour_triste(self, monkeypatch):
        m = self._moteur(monkeypatch)
        for emo, force in ((Emotion.CURIOUS, 0.3), (Emotion.THINKING, 0.4),
                           (Emotion.CONFUSED, 0.6), (Emotion.SAD, 0.7)):
            m.process_emotion(EmotionData(emo, force), "p")
            m.global_mood.last_update = time.time() - 60
            for mo in m.person_moods.values():
                mo.last_update = time.time() - 60
            m._apply_decay()
        assert "comme d'habitude" not in m.get_global_mood_context()

    def test_le_gain_suit_l_intensite_declaree(self, monkeypatch):
        m = self._moteur(monkeypatch)
        faible = m._global_impulse_params(0.2).impulse_gain
        forte = m._global_impulse_params(0.95).impulse_gain
        assert faible < forte

    def test_un_temperament_stoique_compartimente_toujours(self, monkeypatch):
        """`global_bleed` promet « à 0 elle compartimente entièrement » : la
        modulation reste RELATIVE au tempérament et ne peut pas passer
        par-dessus le curseur."""
        from emotion.state import Temperament

        stoique = Temperament(volatility=0.2, intensity_base=0.3,
                              recovery_speed=0.8, default_mood=Emotion.NEUTRAL,
                              global_bleed=0.1)
        m = self._moteur(monkeypatch, stoique)
        expansif = self._moteur(monkeypatch)
        assert (m._global_impulse_params(1.0).impulse_gain
                < expansif._global_impulse_params(1.0).impulse_gain)

    def test_un_bleed_nul_reste_nul(self, monkeypatch):
        from emotion.state import Temperament

        m = self._moteur(monkeypatch, Temperament(global_bleed=0.0))
        assert m._global_impulse_params(1.0).impulse_gain == 0.0


@pytest.mark.django_db
class TestRappelDimensionneAuContexte:
    """5 souvenirs et 10 connaissances étaient les valeurs d'un petit modèle
    local. Derrière 256k, `_budget_cap()` accorde ~25 000 caractères au bloc
    mémoire et le rappel en remplissait ~2 000."""

    @staticmethod
    def _retriever():
        from memory.retrieval.retriever import MemoryRetriever

        return MemoryRetriever(MagicMock())

    def test_sans_fenetre_declaree_les_reglages_sont_intacts(self):
        from unittest.mock import patch
        from memory.retrieval.retriever import MemoryRetriever

        r = self._retriever()
        with patch.object(MemoryRetriever, "_budget_cap", return_value=4000):
            assert r._comptes_adaptes() == (5, 10)

    def test_une_grande_fenetre_lui_rend_de_la_memoire(self):
        from unittest.mock import patch
        from memory.retrieval.retriever import MemoryRetriever

        r = self._retriever()
        with patch.object(MemoryRetriever, "_budget_cap", return_value=25_768):
            souvenirs, connaissances = r._comptes_adaptes()
        assert souvenirs > 5 and connaissances > 10
        assert souvenirs <= MemoryRetriever.MAX_SOUVENIRS

    def test_le_rappel_reste_un_rappel_pas_un_dossier(self):
        from unittest.mock import patch
        from memory.retrieval.retriever import MemoryRetriever

        r = self._retriever()
        with patch.object(MemoryRetriever, "_budget_cap", return_value=1_000_000):
            souvenirs, connaissances = r._comptes_adaptes()
        assert souvenirs == MemoryRetriever.MAX_SOUVENIRS
        assert connaissances == MemoryRetriever.MAX_CONNAISSANCES


class TestProsodie:
    """Les jetons sont pour la VOIX : le frontend les cale sur l'audio, la
    base et Telegram recevaient des didascalies."""

    def test_le_frontend_garde_tout_la_base_non(self):
        from emotion.types import extract_emotion, strip_prosody

        brut = ("[EMOTION:embarrassed:0.8] Ah... [PAUSE] ouais. [SIGH] Desolee. "
                "[PAUSE:300] Voila ! [LAUGH] Promis. [BREATH] Bon.")
        pour_la_voix, emo = extract_emotion(brut)
        pour_la_base = strip_prosody(pour_la_voix)

        assert emo is not None
        for jeton in ("[PAUSE]", "[SIGH]", "[LAUGH]", "[BREATH]", "[PAUSE:300]"):
            assert jeton in pour_la_voix
            assert jeton not in pour_la_base

    def test_la_ponctuation_francaise_est_respectee(self):
        from emotion.types import strip_prosody

        assert strip_prosody("Voila ! [LAUGH] Promis.") == "Voila ! Promis."
        assert "  " not in strip_prosody("Desolee. [SIGH] Bon.")

    def test_un_texte_sans_jeton_est_inchange(self):
        from emotion.types import strip_prosody

        texte = "Rien de special ici, juste une phrase."
        assert strip_prosody(texte) == texte


@pytest.mark.django_db
class TestEngagementsQuiTiennent:
    """Les cinq PLUS RÉCENTS étaient récités : dès la sixième promesse, les
    trois premières quittaient le prompt pour toujours puis mouraient en
    `dropped` sans avoir jamais été dites."""

    async def test_le_plus_ancien_ne_disparait_plus(self):
        from memory import read
        from memory.models import Commitment, Entity

        e = await sync_to_async(Entity.objects.create)(
            name="ThomasEngagements", entity_type="person")
        maintenant = timezone.now()
        for description, age in (("le tout premier truc", 25), ("le deuxieme", 20),
                                 ("le troisieme", 15), ("un recent", 1),
                                 ("un autre recent", 0), ("le tout dernier", 0)):
            c = await sync_to_async(Commitment.objects.create)(
                person=e, description=description, status="pending")
            await sync_to_async(
                lambda pk=c.pk, a=age: Commitment.objects.filter(pk=pk).update(
                    created_at=maintenant - timedelta(days=a)))()

        lignes = await read.pending_commitments_for(e)
        assert any("le tout premier truc" in l for l in lignes)
        assert any("semaines" in l for l in lignes), "l'ancienneté est dite"

    async def test_une_echeance_proche_passe_devant(self):
        from memory import read
        from memory.models import Commitment, Entity

        e = await sync_to_async(Entity.objects.create)(
            name="ThomasEcheance", entity_type="person")
        await sync_to_async(Commitment.objects.create)(
            person=e, description="sans echeance", status="pending")
        await sync_to_async(Commitment.objects.create)(
            person=e, description="pour demain", status="pending",
            due_at=timezone.now() + timedelta(days=1))

        lignes = await read.pending_commitments_for(e)
        assert "pour demain" in lignes[0]


class TestFenetreConnue:
    """`context_window` est facultatif sur la ligne modèle, et une install
    réelle le laisse vide : le budget rendait `None` et TOUT retombait sur les
    16 384 tokens de repli. Un modèle à 256k était piloté comme un 16k —
    historique élagué, rappel bridé — sans que rien ne le signale."""

    def test_les_modeles_courants_sont_reconnus(self):
        from ai.budget import known_window_for

        assert known_window_for("gemma4:31b") == 262_144
        assert known_window_for("GEMMA4:12B") == 262_144
        assert known_window_for("claude-opus-5") == 200_000

    def test_un_modele_inconnu_ne_se_voit_rien_inventer(self):
        from ai.budget import known_window_for

        assert known_window_for("un-modele-jamais-vu") is None
        assert known_window_for("") is None
        assert known_window_for(None) is None

    def test_la_ligne_modele_reste_la_source_de_verite(self):
        """Une valeur déclarée gagne sur la table — y compris plus petite."""
        from unittest.mock import patch

        from ai.budget import budget_for
        from ai.router import AIRole

        declare = {"conv": {"provider": "ollama_cloud", "model_id": "gemma4:31b",
                            "context_window": 8192, "max_tokens": None}}
        with patch("ai.router.ai_router.resolve",
                   return_value=("ollama_cloud", "gemma4:31b", 1.0, "conv")), \
             patch("ai.router.ai_router._get_declared_models", return_value=declare):
            budget = budget_for(AIRole.CONVERSATION, tools_chars=0)
        assert budget is not None
        assert budget.window_room() < 8192


@pytest.mark.django_db
class TestDemarrageRefuseSansMemoireLongue:
    """Sans magasin vectoriel il n'y a ni souvenir, ni connaissance, ni
    engagement, ni self-narrative, ni fiche de personne, ni réorganisation
    nocturne — définitivement, puisque `_initialized` était posé quand même.
    L'échec n'était que journalisé : l'installation paraissait tourner
    normalement pendant qu'elle perdait sa journée."""

    async def test_le_demarrage_est_refuse(self):
        from unittest.mock import patch

        from memory.manager import MemoryManager, MemoryUnavailable

        m = MemoryManager()
        with patch("memory.storage.VectorStore",
                   side_effect=RuntimeError("dossier corrompu")):
            with pytest.raises(MemoryUnavailable) as capture:
                await m.initialize()

        message = str(capture.value)
        assert "CHROMA_PERSIST_DIR" in message
        assert "MEMORY_REQUIRE_VECTOR_STORE=0" in message
        assert not m._initialized, (
            "un démarrage refusé ne doit pas se marquer initialisé"
        )

    async def test_le_repli_explicite_reste_possible(self):
        from unittest.mock import patch

        from django.test import override_settings

        from memory.manager import MemoryManager

        m = MemoryManager()
        with override_settings(MEMORY_REQUIRE_VECTOR_STORE=False), \
             patch("memory.storage.VectorStore",
                   side_effect=RuntimeError("dossier corrompu")):
            await m.initialize()

        assert m._initialized and m.retriever is None

    async def test_l_echec_est_compte_au_registre(self):
        """Même en repli explicite, la page santé doit le voir."""
        from unittest.mock import patch

        from django.test import override_settings

        from memory.manager import MemoryManager
        from utils.degradation import degradations

        def _compteur():
            return next(
                (e["count"] for e in degradations.snapshot()
                 if e["label"] == "memoire: vector store indisponible"), 0,
            )

        avant = _compteur()
        m = MemoryManager()
        with override_settings(MEMORY_REQUIRE_VECTOR_STORE=False), \
             patch("memory.storage.VectorStore", side_effect=RuntimeError("boom")):
            await m.initialize()
        assert _compteur() > avant

    def test_le_lifespan_laisse_remonter(self):
        """Le refus n'a d'effet que si le démarrage ASGI ne l'attrape pas.

        Vérifié en vrai par ailleurs (uvicorn sort en code 3, « Application
        startup failed ») ; ce test empêche qu'un `try/except` bien intentionné
        soit ajouté autour de l'appel.
        """
        import ast
        import pathlib

        source = pathlib.Path("backend/config/asgi.py").read_text()
        arbre = ast.parse(source)
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Try):
                continue
            corps = ast.dump(ast.Module(body=noeud.body, type_ignores=[]))
            assert "memory_manager" not in corps or "initialize" not in corps, (
                "memory_manager.initialize() doit rester hors try/except dans "
                "le lifespan, sinon le refus de démarrage est avalé"
            )
