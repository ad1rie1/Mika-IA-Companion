"""Calibrage de la conscience — les portes, les pentes et les sorties.

Ce que ce fichier épingle tient en une phrase : **une porte doit être
franchissable par le signal qu'elle prétend filtrer**.

Le chemin d'interprétation sans appel LLM couvre tout ce qui est volumineux
(chat, Telegram, RSS, modules forgés) et ne produit au mieux que 0.55. En face,
six mécanismes attendaient 0.5, 0.6, 0.7, 0.8 ou 0.85. Seul ``email.received``,
qui paie un appel LLM, pouvait les franchir : sur une installation sans compte
mail — celle par défaut — rien ne devenait jamais une pensée, aucun souvenir
n'était ravivé, rien ne la réveillait entre deux cycles.

Les tests ci-dessous mesurent la calibration **déclarée** : ils lisent les
tables et les fonctions pures, jamais ``config_service``, dont le cache est
amorcé sur la vraie ``data/vtuber.db``. Un test qui la consulterait mesurerait
les réglages de la machine qui l'exécute.
"""

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from conscience.scoring import ScoringTuning, compute_decision_score
from conscience.types import DecisionContext


# ---------------------------------------------------------------------------
# Aides
# ---------------------------------------------------------------------------

_TOUTES_SALUTATIONS = {"morning", "evening", "night"}


def _contexte(**kw) -> DecisionContext:
    base = dict(
        pending_observations=[],
        global_mood="neutral",
        global_intensity=0.0,
        idle_seconds=0.0,
        in_cooldown=False,
        max_pertinence=0.0,
        weighted_urgency=0.0,
        scheduled_actions=[],
        consecutive_waits=0,
        acts_today=0,
        consecutive_ignored_acts=0,
        sleep_phase="awake",
    )
    base.update(kw)
    return DecisionContext(**base)


def _score(ctx, tuning=None):
    """Score, salutations déjà dépensées.

    Sans cette isolation, une exécution à 7 h, 18 h ou 23 h ajoute +0.35 et
    fait passer des tests qui ne mesurent pas ça.
    """
    note, motif, _, _ = compute_decision_score(
        ctx, set(_TOUTES_SALUTATIONS), date.today(), tuning,
    )
    return note, motif


def _action(priorite: float):
    """Une action programmée réduite à ce que le scoring lui demande."""
    return SimpleNamespace(priority=priorite)


# ===========================================================================
# 1. Les portes sont franchissables par le signal qu'elles filtrent
# ===========================================================================

class TestPortesFranchissables:

    def test_le_plafond_heuristique_franchit_les_portes_vivantes(self):
        """0.55 (RSS apparié) passe promotion, ravivement et curiosité."""
        from conscience.entretien import BOOST_PERTINENCE
        from conscience.ruminations import PROMOTION_PERTINENCE
        from conscience.interpreter import PERTINENCE_RSS_MATCHED
        from drives.engine import _OBSERVATION_CURIOSITY_GATE

        plafond = PERTINENCE_RSS_MATCHED
        assert plafond == 0.55

        for nom, porte in (
            ("promotion en pensée", PROMOTION_PERTINENCE),
            ("ravivement de souvenirs", BOOST_PERTINENCE),
            ("assouvissement de la curiosité", _OBSERVATION_CURIOSITY_GATE),
        ):
            assert porte <= plafond, (
                f"« {nom} » est à {porte}, au-dessus du plafond du chemin sans "
                f"LLM ({plafond}) : sur une installation sans compte mail, ce "
                "mécanisme ne se déclencherait jamais."
            )

    def test_les_portes_cheres_restent_hors_de_portee_de_l_heuristique(self):
        """Deux portes doivent RESTER hautes, et c'est délibéré.

        La vérification de cohérence coûte jusqu'à cinq appels IA ; le réveil
        nocturne coûte une nuit. Les banaliser en descendant tout serait le
        défaut symétrique de celui qu'on répare.
        """
        from conscience.entretien import CONTRADICTION_PERTINENCE
        from conscience.interpreter import PERTINENCE_RSS_MATCHED
        from conscience.scoring import SLEEP_WAKE_PERTINENCE

        for nom, porte in (
            ("vérification de cohérence", CONTRADICTION_PERTINENCE),
            ("réveil nocturne", SLEEP_WAKE_PERTINENCE),
        ):
            assert porte > PERTINENCE_RSS_MATCHED, nom

    def test_chat_et_telegram_restent_sous_toutes_les_portes(self):
        """Aucune des six pertinences non appariées n'a été remontée.

        Rien ne dit qu'un message de chat vaut davantage qu'avant : seule la
        pertinence portant un intérêt *apparié* a bougé.
        """
        from conscience.entretien import BOOST_PERTINENCE
        from conscience.ruminations import PROMOTION_PERTINENCE
        from conscience.interpreter import (
            PERTINENCE_CHAT_MESSAGE,
            PERTINENCE_FALLBACK,
            PERTINENCE_FORGE_EVENT,
            PERTINENCE_RSS_UNMATCHED,
            PERTINENCE_TELEGRAM_MESSAGE,
        )

        assert PERTINENCE_CHAT_MESSAGE == 0.3
        assert PERTINENCE_TELEGRAM_MESSAGE == 0.4
        for pertinence in (
            PERTINENCE_CHAT_MESSAGE, PERTINENCE_TELEGRAM_MESSAGE,
            PERTINENCE_RSS_UNMATCHED, PERTINENCE_FORGE_EVENT,
            PERTINENCE_FALLBACK,
        ):
            assert pertinence < min(PROMOTION_PERTINENCE, BOOST_PERTINENCE)

    def test_un_chat_pese_toujours_zero_dans_l_urgence_accumulee(self):
        """Porte stricte à 0.3, pertinence d'un chat exactement 0.3.

        Ce n'est pas réparé ici — c'est *déclaré*, pour que le prochain qui
        touche à l'une des deux valeurs voie l'égalité. Le rendre réglable sans
        le corriger est délibéré : monter la pertinence d'un chat ferait entrer
        le volume le plus élevé du système dans le facteur d'urgence.
        """
        from conscience.engine import URGENCY_OBSERVATION_GATE
        from conscience.interpreter import PERTINENCE_CHAT_MESSAGE

        assert PERTINENCE_CHAT_MESSAGE == URGENCY_OBSERVATION_GATE
        assert not (PERTINENCE_CHAT_MESSAGE > URGENCY_OBSERVATION_GATE)


# ===========================================================================
# 2. La barre du réveil est la même des deux côtés
# ===========================================================================

class TestBarreDeReveil:

    def test_l_egalite_reveille(self):
        """`scoring` compare avec `>=` ; le fast-path aussi, désormais.

        Une pertinence pile sur la barre réveillait la décision sans que le
        fast-path la déclenche : selon le chemin emprunté, le même signal
        obtenait deux réponses différentes.
        """
        import inspect

        from conscience import perception

        source = inspect.getsource(perception.observe)
        assert "signal.pertinence >= cfg_float(" in source, (
            "le fast-path doit comparer avec >=, comme le veto de sommeil"
        )

    def test_pile_sur_la_barre_le_veto_de_sommeil_se_leve(self):
        t = ScoringTuning()
        ctx = _contexte(
            sleep_phase="deep_sleep", max_pertinence=t.sleep_wake_pertinence,
        )
        note, motif = _score(ctx)
        assert "asleep" not in motif
        assert note > 0.0

    def test_juste_en_dessous_elle_dort(self):
        t = ScoringTuning()
        ctx = _contexte(
            sleep_phase="deep_sleep",
            max_pertinence=t.sleep_wake_pertinence - 0.01,
        )
        note, motif = _score(ctx)
        assert note == 0.0
        assert "asleep" in motif


# ===========================================================================
# 3. Une action programmée ne réveille que si elle est prioritaire
# ===========================================================================

class TestReveilParActionProgrammee:

    def test_une_action_ordinaire_ne_reveille_plus(self):
        """`_poll_scheduled_actions` remonte TOUT ce qui est dû.

        La simple existence d'une ligne levait le veto : un « pense à relire ce
        brouillon » programmé pour 23 h la réveillait comme une urgence.
        """
        ctx = _contexte(sleep_phase="deep_sleep", scheduled_actions=[_action(0.5)])
        note, motif = _score(ctx)
        assert note == 0.0
        assert "asleep" in motif

    def test_une_action_prioritaire_reveille(self):
        t = ScoringTuning()
        ctx = _contexte(
            sleep_phase="deep_sleep",
            scheduled_actions=[_action(t.sleep_wake_scheduled_priority)],
        )
        note, motif = _score(ctx)
        assert "asleep" not in motif

    def test_la_priorite_la_plus_haute_du_lot_decide(self):
        t = ScoringTuning()
        ctx = _contexte(
            sleep_phase="deep_sleep",
            scheduled_actions=[
                _action(0.1), _action(t.sleep_wake_scheduled_priority), _action(0.2),
            ],
        )
        _, motif = _score(ctx)
        assert "asleep" not in motif

    def test_en_journee_toute_action_due_compte_encore(self):
        """Le durcissement ne vise QUE la nuit — rien ne change de jour."""
        ctx = _contexte(scheduled_actions=[_action(0.5)])
        note, motif = _score(ctx)
        assert "scheduled(1)" in motif
        assert note > 0.0


# ===========================================================================
# 4. Le frein quotidien a une sortie
# ===========================================================================

class TestFreinQuotidien:

    def _contexte_freine(self, idle: float) -> DecisionContext:
        # Assez de signal pour que le score dépasse franchement le plancher de
        # suppression (0.1) une fois le frein levé : sans quoi le test passerait
        # ou échouerait pour la mauvaise raison — un score naturellement bas,
        # pas un frein qui tient.
        return _contexte(
            acts_today=5, consecutive_ignored_acts=3,
            max_pertinence=0.95, global_intensity=0.9, idle_seconds=idle,
        )

    def test_le_frein_tient_dans_le_silence(self):
        t = ScoringTuning()
        note, motif = _score(
            self._contexte_freine(t.suppress_release_idle_seconds + 1)
        )
        assert "suppressed" in motif
        assert note <= t.suppressed_score

    def test_quelqu_un_qui_parle_leve_le_frein(self):
        """La seule sortie possible.

        Les deux autres conditions ne peuvent se défaire d'elles-mêmes :
        `consecutive_ignored` ne retombe qu'en produisant un acte suivi d'une
        réponse, ce que la suppression interdit. Le verrou ne s'ouvrait donc
        qu'au changement de jour — et l'utilisateur qui arrivait à 18 h ne
        débloquait rien.
        """
        t = ScoringTuning()
        note, motif = _score(
            self._contexte_freine(t.suppress_release_idle_seconds - 1)
        )
        assert "suppressed" not in motif
        assert note > t.suppressed_score

    def test_la_sortie_est_exactement_sur_la_barre(self):
        t = ScoringTuning()
        _, motif = _score(self._contexte_freine(t.suppress_release_idle_seconds))
        assert "suppressed" in motif, "la barre elle-même freine encore"


# ===========================================================================
# 5. « On m'ignore » compte dès la première
# ===========================================================================

class TestIgnoree:

    def test_la_premiere_relance_sans_reponse_coute_deja(self):
        """Le backoff du délai comptait déjà dès la première.

        Les deux moitiés du même mécanisme ne partaient pas au même moment :
        la pénalité de score attendait la deuxième, si bien que les trois
        premiers actes de la journée tombaient en une demi-heure.
        """
        t = ScoringTuning()
        assert t.ignored_min_acts == 1
        note, motif = _score(_contexte(consecutive_ignored_acts=1, idle_seconds=0.0))
        assert "ignored" in motif
        assert note == pytest.approx(-t.ignored_per_act)

    def test_zero_relance_ignoree_ne_coute_rien(self):
        _, motif = _score(_contexte(consecutive_ignored_acts=0))
        assert "ignored" not in motif


# ===========================================================================
# 6. Les pulsions positives ne saturent plus en vingt minutes
# ===========================================================================

class TestDesaturationDesPulsions:

    def _apres(self, secondes: float):
        from drives.engine import DriveEngine
        from drives.state import DriveKind

        moteur = DriveEngine()
        for etat in moteur.states.values():
            etat.last_update -= secondes
            etat.last_satisfied -= secondes
        moteur.update()
        return moteur, DriveKind

    def test_a_trente_minutes_aucune_n_est_au_plafond(self):
        """Le défaut mesuré : 0.0008/s et 0.0007/s saturaient à 20 min 50 et
        23 min 49. Or les poids de CURIOSITY et EXPRESSION somment à 0.55,
        au-delà du plafond du Facteur 9 (+0.50) : passé la demi-heure, ce
        facteur valait la constante +0.50 quoi qu'il arrive, et ni une heure ni
        trois jours de silence ne changeaient plus rien au score.
        """
        moteur, DriveKind = self._apres(1800.0)
        for kind in (DriveKind.CURIOSITY, DriveKind.EXPRESSION, DriveKind.SOCIAL):
            assert moteur.states[kind].tension < 1.0, kind

    def test_le_plafond_reste_atteignable_a_l_horizon(self):
        """Désaturer n'est pas rendre inatteignable."""
        moteur, DriveKind = self._apres(13 * 3600.0)
        assert moteur.states[DriveKind.CURIOSITY].tension == pytest.approx(1.0)
        assert moteur.states[DriveKind.EXPRESSION].tension == pytest.approx(1.0)

    def test_la_courbe_informe_encore_entre_une_heure_et_six(self):
        """La propriété pour laquelle le log-temps existe."""
        une_heure, DriveKind = self._apres(3600.0)
        six_heures, _ = self._apres(6 * 3600.0)
        assert (
            six_heures.states[DriveKind.CURIOSITY].tension
            > une_heure.states[DriveKind.CURIOSITY].tension + 0.10
        )


# ===========================================================================
# 7. La pression des pensées ne sature plus à deux
# ===========================================================================

class TestPressionDesPensees:

    def test_deux_pensees_a_un_demi_ne_saturent_plus(self):
        from conscience.ruminations import RUMINATION_PRESSION_PLEINE

        assert RUMINATION_PRESSION_PLEINE > 1.0, (
            "la somme était comparée à 1.0 : deux pensées à 0.5 saturaient "
            "déjà le Facteur 10, et une promotion plus ouverte en aurait fait "
            "l'état permanent"
        )
        assert (0.5 + 0.5) / RUMINATION_PRESSION_PLEINE < 0.5

    def test_la_pression_pleine_reste_atteignable(self):
        from conscience.ruminations import PROMOTION_ACTIVES_MAX, RUMINATION_PRESSION_PLEINE

        # Le plafond de pensées actives doit pouvoir produire une pression
        # pleine, sinon le Facteur 10 ne peut jamais donner son maximum.
        assert PROMOTION_ACTIVES_MAX * 1.0 >= RUMINATION_PRESSION_PLEINE


# ===========================================================================
# 8. Une seule horloge
# ===========================================================================

class TestHorlogeLocale:

    def test_la_journee_commence_a_minuit_local(self):
        """`timezone.now().replace(hour=0)` rend minuit UTC sous USE_TZ=True.

        Deux heures d'écart l'été à Paris : un acte pris entre minuit et 02 h
        était imputé à la veille, puis jamais décompté du jour qui s'ouvrait.
        """
        from conscience.read import debut_du_jour_local

        debut = debut_du_jour_local()
        assert (debut.hour, debut.minute, debut.second) == (0, 0, 0)
        assert debut.date() == datetime.now().date()

    def test_elle_est_comparable_a_un_created_at(self):
        """Le retour doit être *aware* : il borne un champ `auto_now_add`."""
        from django.conf import settings
        from django.utils import timezone as tz

        from conscience.read import debut_du_jour_local

        debut = debut_du_jour_local()
        if settings.USE_TZ:
            assert debut.tzinfo is not None
            assert debut <= tz.now()

    def test_le_moteur_ne_recalcule_plus_minuit_lui_meme(self):
        import inspect

        from conscience import introspection

        source = inspect.getsource(introspection.introspect)
        assert "debut_du_jour_local()" in source
        assert "replace(hour=0" not in source, (
            "minuit se calcule dans la couche de lecture, en un seul endroit"
        )


# ===========================================================================
# 9. Un acte nocturne se réveille pour de bon
# ===========================================================================

class TestReveilReel:

    def test_la_grace_empeche_de_se_rendormir_aussitot(self):
        """L'inactivité ne compte que ce que les AUTRES font.

        Un acte endogène laisse `_last_activity` intact, à dessein. La nuit,
        une initiative la réveillait donc un tick, puis la porte la rendormait
        60 s plus tard — pendant qu'elle parlait.
        """
        from memory.sleep import SleepCycle

        cycle = SleepCycle()
        assert cycle._dernier_reveil == 0.0
        cycle.note_interaction()
        assert cycle._dernier_reveil > 0.0

    @pytest.mark.asyncio
    async def test_pendant_la_grace_elle_ne_se_rendort_pas(self):
        from unittest.mock import patch

        from memory.sleep import SleepCycle

        cycle = SleepCycle()
        cycle.note_interaction()
        with patch("conscience.engine.conscience_engine") as faux:
            faux.get_idle_seconds.return_value = 100_000.0  # très au-delà
            assert await cycle._is_eligible_to_sleep() is False

    @pytest.mark.asyncio
    async def test_passee_la_grace_l_inactivite_reprend_la_main(self):
        from unittest.mock import patch

        from memory.sleep import ENDOGENOUS_WAKE_GRACE_SECONDS, SleepCycle

        cycle = SleepCycle()
        cycle.note_interaction()
        cycle._dernier_reveil -= ENDOGENOUS_WAKE_GRACE_SECONDS + 1
        with patch("conscience.engine.conscience_engine") as faux:
            faux.get_idle_seconds.return_value = 100_000.0
            assert await cycle._is_eligible_to_sleep() is True

    def test_eveillee_elle_a_le_droit_de_parler(self):
        """La conséquence qui rendait le défaut visible à l'écran.

        Persona SPEAKING et non INNER : `pipeline/voice.py` laisse
        délibérément passer une pensée murmurée la nuit — « c'est ce qui rend
        la nuit habitée plutôt que muette ». Ce qu'il refuse, c'est la parole
        *adressée* en sommeil, et c'est précisément ce que produit un acte de
        conscience visant une personne (`persona_for_source("conscience",
        addressed=True)`). Le message s'affichait, muet, prononcé par
        quelqu'un que l'avatar montrait endormi.
        """
        from memory.sleep import SleepCycle, SleepPhase
        from pipeline.voice import VoicePersona, VoiceSink, decide_voice

        cycle = SleepCycle()
        cycle._phase = SleepPhase.DEEP_SLEEP
        muette = decide_voice(
            VoiceSink.SCREEN, hour=3, sleep_phase=cycle.phase,
            persona=VoicePersona.SPEAKING,
        )
        assert muette.speak is False
        assert "asleep" in muette.reason

        cycle.note_interaction()
        assert cycle.phase == SleepPhase.AWAKE
        parlante = decide_voice(
            VoiceSink.SCREEN, hour=3, sleep_phase=cycle.phase,
            persona=VoicePersona.SPEAKING,
        )
        assert parlante.speak is True

    def test_un_acte_adresse_porte_bien_la_persona_qui_se_tait(self):
        """Le maillon qui relie les deux : sans lui, le test ci-dessus
        mesurerait une combinaison que le moteur ne produit jamais."""
        from pipeline.voice import VoicePersona, persona_for_source

        assert persona_for_source("conscience", addressed=True) == \
            VoicePersona.SPEAKING

    def test_la_branche_act_reveille_le_cycle(self):
        """`_act` appelle `process_message` en direct, jamais `perceive()` —
        seul appelant de `note_interaction()`."""
        import inspect

        from conscience import engine as moteur

        # Sur l'AST, pas sur le texte : les commentaires du moteur citent
        # `note_activity()` pour dire de ne PAS l'appeler, et une recherche
        # textuelle prendrait cette mise en garde pour l'infraction.
        import ast
        import textwrap

        source = textwrap.dedent(
            inspect.getsource(moteur.ConscienceEngine._decide_inner)
        )
        appels = {
            noeud.func.attr
            for noeud in ast.walk(ast.parse(source))
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
        }
        assert "note_interaction" in appels
        assert "note_activity" not in appels, (
            "note_activity dirait « quelqu'un s'est manifesté » : sa propre "
            "initiative remettrait son inactivité à zéro et supprimerait le "
            "Facteur 4"
        )
