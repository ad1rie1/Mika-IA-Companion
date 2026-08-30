"""Tests for the intrinsic drive system (drives/).

Drives model Mika's inner motivational pulls: curiosity, social contact,
self-expression, and need for rest. They grow with time when unsatisfied
and decay when the corresponding action happens.

Tests:
- Tension growth over simulated time
- Satisfaction reduces tension correctly
- Dominant drive identification
- Prompt context generation
- Scoring contribution (including negative REST contribution)
- on_act / on_conversation / on_observation signal mapping
- REST drive grows with activity and decays during idle
"""
from __future__ import annotations

import time
from datetime import timedelta

import pytest

from drives.engine import DriveEngine
from drives.state import (
    DEFAULT_PARAMS,
    DriveKind,
    dominant_drive,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _backdate(engine: DriveEngine, seconds: float) -> None:
    """Pretend `seconds` have passed by rewinding every drive's clocks.

    `last_satisfied` recule aussi : SOCIAL croît désormais en temps
    logarithmique depuis le dernier assouvissement, pas par accumulation
    d'incréments depuis `last_update`.
    """
    past = time.time() - seconds
    for state in engine.states.values():
        state.last_update = past
        state.last_satisfied = past


@pytest.fixture
def engine() -> DriveEngine:
    """Fresh DriveEngine at zero tension."""
    return DriveEngine()


# ---------------------------------------------------------------------------
# Tension growth
# ---------------------------------------------------------------------------

class TestTensionGrowth:

    def test_all_drives_start_at_zero(self, engine):
        for kind in DriveKind:
            assert engine.states[kind].tension == 0.0

    def test_curiosity_monte_des_les_premieres_minutes(self, engine):
        """~0.21 au bout de 300 s, en temps logarithmique.

        Le nom disait « linearly » et la docstring « 0.0008/s » : les deux sont
        faux depuis le passage en log-temps, et la valeur attendue est restée
        juste par coïncidence. Un test dont le nom ment survit aux relectures
        en racontant l'inverse de ce que fait le code.
        """
        _backdate(engine, 300.0)
        engine.update()
        tension = engine.states[DriveKind.CURIOSITY].tension
        assert 0.20 < tension < 0.30

    def test_aucune_pulsion_positive_ne_sature_en_une_heure(self, engine):
        """Le pin change une seconde fois, et pour la même raison qu'à P7.

        Il affirmait alors que CURIOSITY valait exactement 1.0 au bout d'une
        heure — ce qui était vrai, et qui était le défaut : sa propriété
        (« SOCIAL est la seule qui a encore quelque chose à dire ») ne tenait
        qu'à la saturation des deux autres. Elle est maintenant vraie de
        personne, ce qui est mieux : les poids de CURIOSITY et EXPRESSION
        somment à 0.55, au-delà du plafond du Facteur 9 (+0.50), si bien que
        leur saturation figeait ce facteur sur une constante passé la
        demi-heure. Aucune des trois ne doit plus être au plafond à une heure.
        """
        _backdate(engine, 3600.0)
        engine.update()
        for kind in (DriveKind.CURIOSITY, DriveKind.SOCIAL, DriveKind.EXPRESSION):
            assert engine.states[kind].tension < 1.0, kind
        # …et elles restent ordonnées par leur horizon : l'expression (9 h)
        # devant la curiosité (12 h), toutes deux devant l'absence (30 j).
        assert (
            engine.states[DriveKind.EXPRESSION].tension
            > engine.states[DriveKind.CURIOSITY].tension
            > engine.states[DriveKind.SOCIAL].tension
        )

    def test_tension_clamps_at_one(self, engine):
        _backdate(engine, 10_000.0)  # way beyond saturation
        engine.update()
        for kind in (DriveKind.CURIOSITY, DriveKind.SOCIAL, DriveKind.EXPRESSION):
            assert engine.states[kind].tension <= 1.0

    def test_rest_does_not_grow_without_activity(self, engine):
        """REST only grows when Mika has been active — pure idle shouldn't stress her."""
        _backdate(engine, 500.0)
        engine.update()
        assert engine.states[DriveKind.REST].tension < 0.05

    def test_update_is_idempotent(self, engine):
        """Calling update() twice in a row doesn't double-count."""
        _backdate(engine, 100.0)
        engine.update()
        t1 = engine.states[DriveKind.CURIOSITY].tension
        engine.update()
        t2 = engine.states[DriveKind.CURIOSITY].tension
        assert abs(t1 - t2) < 0.01


# ---------------------------------------------------------------------------
# Satisfaction
# ---------------------------------------------------------------------------

class TestSatisfaction:

    def test_satisfy_reduces_tension(self, engine):
        # 6 h et non 10 min : en temps logarithmique SOCIAL n'est qu'à 0.12
        # au bout de 600 s, sous le seuil que l'assertion suivante impose.
        _backdate(engine, 6 * 3600.0)
        engine.update()
        before = engine.states[DriveKind.SOCIAL].tension
        assert before > 0.3

        engine.satisfy(DriveKind.SOCIAL, 1.0)
        after = engine.states[DriveKind.SOCIAL].tension
        assert after < before

    def test_full_satisfy_applies_decay_on_satisfy(self, engine):
        """amount=1.0 should apply the full decay_on_satisfy factor."""
        engine.states[DriveKind.SOCIAL].tension = 1.0
        engine.satisfy(DriveKind.SOCIAL, 1.0)
        # decay_on_satisfy=0.7 → remaining 30% of 1.0 = 0.3
        assert abs(engine.states[DriveKind.SOCIAL].tension - 0.3) < 0.01

    def test_partial_satisfy_relieves_partially(self, engine):
        engine.states[DriveKind.SOCIAL].tension = 1.0
        engine.satisfy(DriveKind.SOCIAL, 0.5)
        # Applies 0.5 × 0.7 = 0.35 decay → remaining 65% of 1.0 = 0.65
        assert 0.6 < engine.states[DriveKind.SOCIAL].tension < 0.7

    def test_satisfy_never_goes_below_zero(self, engine):
        engine.states[DriveKind.SOCIAL].tension = 0.1
        engine.satisfy(DriveKind.SOCIAL, 1.0)
        assert engine.states[DriveKind.SOCIAL].tension >= 0.0


# ---------------------------------------------------------------------------
# Dominant drive
# ---------------------------------------------------------------------------

class TestDominantDrive:

    def test_no_dominant_when_all_quiet(self, engine):
        engine.update()
        assert engine.get_dominant() is None

    def test_highest_tension_is_dominant(self, engine):
        engine.states[DriveKind.CURIOSITY].tension = 0.3
        engine.states[DriveKind.SOCIAL].tension = 0.6
        engine.states[DriveKind.EXPRESSION].tension = 0.4
        engine.update()
        dom = engine.get_dominant()
        assert dom is not None
        assert dom.kind is DriveKind.SOCIAL

    def test_dominant_requires_minimum_tension(self, engine):
        """Everyone at 0.1 → below the noise floor (0.2)."""
        for state in engine.states.values():
            state.tension = 0.1
        assert dominant_drive(engine.states) is None


# ---------------------------------------------------------------------------
# Prompt context
# ---------------------------------------------------------------------------

class TestPromptContext:

    def test_empty_context_when_all_below_threshold(self, engine):
        """No drives active → no prompt injection."""
        engine.update()
        assert engine.get_context() == ""

    def test_active_drives_appear_in_french(self, engine):
        """Le pin passe du LEXIQUE à la PROPRIÉTÉ.

        Il cherchait « contact », « reconnue » ou « echanger », les mots exacts
        de l'une des douze phrases figées. Avec 112 variantes tirées, un pin
        sur trois mots est un pari qui rougit au hasard — et il rougirait pour
        une raison qui n'apprend rien. Ce qu'on veut vraiment savoir, c'est
        qu'une pulsion saillante est dite, et qu'elle est dite en français.
        """
        engine.states[DriveKind.SOCIAL].tension = 0.7
        engine.update()
        ctx = engine.get_context()
        assert ctx
        from drives.phrasing import PREFIXE_PROMPT
        assert ctx.startswith(PREFIXE_PROMPT)
        assert len(ctx) > len(PREFIXE_PROMPT) + 10

    def test_intensity_adverbs_scale_correctly(self, engine):
        """Deux tensions éloignées ne tombent pas dans le même palier.

        Mesuré sur `palier_pour` plutôt que sur deux rendus comparés : le
        tirage est amorti, donc deux appels successifs diffèrent déjà par la
        variante choisie — l'ancienne assertion aurait passé même si les
        paliers avaient fusionné.
        """
        from drives.phrasing import palier_pour

        assert palier_pour(0.40) is not palier_pour(0.85)

    def test_top_three_cap_on_description(self, engine):
        """Au plus trois pulsions dites, même quand les quatre sont au plafond.

        Le comptage des « tu » est abandonné : il était déjà faux dès qu'une
        variante commence par « il y a » ou « l'envie de », et le vivier en
        contient. On compte les phrases, ce qui est la propriété.
        """
        from drives.phrasing import MAX_PULSIONS_DITES, PREFIXE_PROMPT

        for kind in DriveKind:
            engine.states[kind].tension = 0.95
        engine.update()
        ctx = engine.get_context()
        corps = ctx[len(PREFIXE_PROMPT):]
        assert 0 < corps.count(".") <= MAX_PULSIONS_DITES


# ---------------------------------------------------------------------------
# Scoring contribution
# ---------------------------------------------------------------------------

class TestScoringContribution:

    def test_no_contribution_when_all_quiet(self, engine):
        engine.update()
        bonus, summary = engine.conscience_contribution()
        assert abs(bonus) < 0.01

    def test_strong_social_drive_contributes_positively(self, engine):
        engine.states[DriveKind.SOCIAL].tension = 0.9
        bonus, summary = engine.conscience_contribution()
        assert bonus > 0.15
        assert "social" in summary

    def test_rest_drive_contributes_negatively(self, engine):
        """High fatigue should reduce the urge to act."""
        engine.states[DriveKind.REST].tension = 0.9
        bonus, summary = engine.conscience_contribution()
        assert bonus < 0
        assert "rest" in summary

    def test_rest_vs_expression_can_cancel(self, engine):
        """Tired but with something to say → small net effect."""
        engine.states[DriveKind.REST].tension = 0.8
        engine.states[DriveKind.EXPRESSION].tension = 0.8
        bonus, _ = engine.conscience_contribution()
        # They're not exactly equal (weights differ) but bounded.
        assert abs(bonus) < 0.25


# ---------------------------------------------------------------------------
# Activity → REST drive
# ---------------------------------------------------------------------------

class TestRestDrive:

    def test_act_raises_rest_pressure(self, engine):
        assert engine.states[DriveKind.REST].tension == 0.0
        for _ in range(5):
            engine.on_act(had_tools=False, word_count=20)
        engine.update()
        assert engine.states[DriveKind.REST].tension > 0.1

    def test_observation_raises_rest_pressure(self, engine):
        for _ in range(3):
            engine.on_observation(pertinence=0.8)
        engine.update()
        assert engine.states[DriveKind.REST].tension > 0.05

    def test_long_messages_tire_more(self, engine):
        # Short message
        e1 = DriveEngine()
        e1.on_act(word_count=5)
        e1.update()
        t_short = e1.states[DriveKind.REST].tension

        # Long message
        e2 = DriveEngine()
        e2.on_act(word_count=200)
        e2.update()
        t_long = e2.states[DriveKind.REST].tension

        assert t_long > t_short

    def test_rest_decays_during_idle(self, engine):
        engine.states[DriveKind.REST].tension = 0.6
        _backdate(engine, 600.0)  # 10 min of idle
        engine.update()
        assert engine.states[DriveKind.REST].tension < 0.6


# ---------------------------------------------------------------------------
# Signal routing
# ---------------------------------------------------------------------------

class TestSignalRouting:

    def test_conversation_satisfies_social_and_curiosity(self, engine):
        engine.states[DriveKind.SOCIAL].tension = 1.0
        engine.states[DriveKind.CURIOSITY].tension = 1.0
        engine.on_conversation(from_person=True)
        assert engine.states[DriveKind.SOCIAL].tension < 1.0
        assert engine.states[DriveKind.CURIOSITY].tension < 1.0

    def test_act_satisfies_expression(self, engine):
        engine.states[DriveKind.EXPRESSION].tension = 1.0
        engine.on_act(had_tools=False, word_count=10)
        assert engine.states[DriveKind.EXPRESSION].tension < 0.5

    def test_act_with_tools_also_satisfies_curiosity(self, engine):
        engine.states[DriveKind.CURIOSITY].tension = 1.0
        engine.states[DriveKind.EXPRESSION].tension = 1.0
        engine.on_act(had_tools=True, word_count=10)
        assert engine.states[DriveKind.CURIOSITY].tension < 1.0

    def test_high_pertinence_observation_feeds_curiosity(self, engine):
        engine.states[DriveKind.CURIOSITY].tension = 1.0
        engine.on_observation(pertinence=0.9)
        # Feeds curiosity (satisfies it) only when pertinence > 0.6
        assert engine.states[DriveKind.CURIOSITY].tension < 1.0

    def test_low_pertinence_observation_does_not_feed_curiosity(self, engine):
        engine.states[DriveKind.CURIOSITY].tension = 0.5
        engine.on_observation(pertinence=0.3)
        # Below threshold — no satisfaction, only REST pressure
        assert engine.states[DriveKind.CURIOSITY].tension >= 0.5


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

class TestReset:

    def test_reset_clears_all_tensions(self, engine):
        for state in engine.states.values():
            state.tension = 0.8
        engine.reset()
        for state in engine.states.values():
            assert state.tension == 0.0

    def test_reset_clears_activity_history(self, engine):
        engine.on_act(word_count=100)
        engine.on_act(word_count=100)
        engine.reset()
        assert engine._activity == []


# ---------------------------------------------------------------------------
# Reactive reply (on_reply)
# ---------------------------------------------------------------------------

class TestOnReply:
    """Answering someone is speech too: partial EXPRESSION relief +
    activity. Before on_reply existed, a Mika who chatted all day kept
    full expression tension, as if she had been silent."""

    def test_reply_relieves_expression_partially(self, engine):
        engine.states[DriveKind.EXPRESSION].tension = 1.0
        engine.on_reply(word_count=30)
        after = engine.states[DriveKind.EXPRESSION].tension
        assert after < 1.0
        # Partial: less relief than a spontaneous act (amount 1.0)
        spontaneous = DriveEngine()
        spontaneous.states[DriveKind.EXPRESSION].tension = 1.0
        spontaneous.on_act()
        assert after > spontaneous.states[DriveKind.EXPRESSION].tension

    def test_reply_registers_activity_for_rest(self, engine):
        engine.on_reply(word_count=80)
        engine.update()
        assert engine.states[DriveKind.REST].tension > 0.0


# ---------------------------------------------------------------------------
# Échelles de temps (SOCIAL en temps logarithmique)
# ---------------------------------------------------------------------------

class TestEchellesDeTemps:
    """Trois semaines d'absence valaient vingt-cinq minutes : SOCIAL saturait
    en 16 min 40, après quoi une heure, un jour et trois semaines rendaient la
    même ligne de prompt et le même facteur de scoring. Si le modèle disait
    « tu m'as manqué », rien dans la mécanique ne le justifiait."""

    @staticmethod
    def _apres(seconds: float) -> DriveEngine:
        e = DriveEngine()
        _backdate(e, seconds)
        e.update()
        return e

    def test_une_heure_et_trois_semaines_ne_se_lisent_pas_pareil(self):
        une_heure = self._apres(3600.0)
        trois_semaines = self._apres(21 * 86400.0)

        from drives.phrasing import palier_pour

        t1 = une_heure.states[DriveKind.SOCIAL].tension
        t2 = trois_semaines.states[DriveKind.SOCIAL].tension
        assert t2 - t1 >= 0.5
        # Sur le PALIER et non sur deux rendus comparés : le tirage est amorti,
        # donc deux rendus diffèrent de toute façon par la variante choisie.
        # C'est le palier qui porte « ça ne se lit pas pareil ».
        assert palier_pour(t1) is not palier_pour(t2)

    def test_social_est_monotone_et_bornee(self):
        echelles = [300.0, 3600.0, 86400.0, 7 * 86400.0, 21 * 86400.0]
        tensions = [
            self._apres(s).states[DriveKind.SOCIAL].tension for s in echelles
        ]
        assert tensions == sorted(tensions)
        assert tensions[0] < tensions[-1] <= 1.0

    def test_un_echange_remet_l_horloge_a_zero(self):
        e = self._apres(21 * 86400.0)
        avant = e.states[DriveKind.SOCIAL].tension
        e.on_conversation(from_person=True)
        e.update()
        assert e.states[DriveKind.SOCIAL].tension < avant

    def test_la_croissance_lineaire_reste_disponible_pour_rest(self):
        """Le mécanisme reste opt-in : `growth_horizon = 0` garde l'ancien calcul.

        Le test visait CURIOSITY, qui vient de passer en log-temps — son nom
        mentait donc désormais, et un test dont le nom ment est pire qu'un test
        rouge. La propriété qu'il mesure (l'opt-in existe et se lit sur la
        table) n'a pas disparu : REST la porte, avec l'avantage de ne pas
        risquer de rebasculer au prochain calibrage, sa croissance venant de
        l'activité et non du temps.
        """
        assert DEFAULT_PARAMS[DriveKind.REST].growth_horizon == 0.0
        assert DEFAULT_PARAMS[DriveKind.REST].growth_tau == 0.0

    def test_curiosity_et_expression_sont_en_log_temps(self):
        """Les deux pulsions désaturées déclarent bien un horizon.

        Sans horizon non nul dans la table, `params_for` ne relit ni tau ni
        horizon depuis la configuration (`drives/state.py`) : les ConfigItem
        déclarés seraient inertes, et la croissance resterait linéaire tout en
        affichant des réglages qui ne pilotent rien.
        """
        for kind, horizon in (
            (DriveKind.CURIOSITY, 12 * 3600.0),
            (DriveKind.EXPRESSION, 9 * 3600.0),
        ):
            assert DEFAULT_PARAMS[kind].growth_rate == 0.0, kind
            assert DEFAULT_PARAMS[kind].growth_horizon == horizon, kind
            assert DEFAULT_PARAMS[kind].growth_tau > 0.0, kind

    def test_la_curiosite_ne_sature_plus_en_vingt_minutes(self):
        """Le défaut mesuré : 0.0008/s la mettait à 1.0 en 20 min 50."""
        e = self._apres(1260.0)  # 21 min
        assert 0.35 < e.states[DriveKind.CURIOSITY].tension < 0.50
        # …et elle continue de monter bien après, au lieu d'être plafonnée.
        tard = self._apres(3600.0)
        assert (
            tard.states[DriveKind.CURIOSITY].tension
            > e.states[DriveKind.CURIOSITY].tension
        )


class TestLogGrowth:

    def test_zero_au_depart_un_a_l_horizon_jamais_plus(self):
        from drives.state import log_growth

        assert log_growth(0.0, 300.0, 1000.0) == 0.0
        assert log_growth(1000.0, 300.0, 1000.0) == pytest.approx(1.0)
        assert log_growth(10_000.0, 300.0, 1000.0) == 1.0

    def test_parametres_absents_valent_zero(self):
        from drives.state import log_growth

        assert log_growth(500.0, 0.0, 1000.0) == 0.0
        assert log_growth(500.0, 300.0, 0.0) == 0.0


# ---------------------------------------------------------------------------
# Persistance
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestPersistance:
    """L'état en RAM pur n'était pas une nuance de fatigue perdue : le gate du
    cycle de sommeil lisait REST, donc tout redémarrage du soir supprimait la
    nuit mentale, et SOCIAL ne pouvait rien dire d'une absence dont
    l'horodatage disparaissait au boot."""

    @pytest.fixture(autouse=True)
    def _clean(self):
        from drives.models import DriveSnapshot
        DriveSnapshot.objects.all().delete()
        yield
        DriveSnapshot.objects.all().delete()

    async def test_un_redemarrage_retrouve_les_tensions(self):
        source = DriveEngine()
        source.states[DriveKind.REST].tension = 0.72
        await source.save_state()

        neuf = DriveEngine()
        assert neuf.states[DriveKind.REST].tension == 0.0
        await neuf.restore_state()
        assert neuf.states[DriveKind.REST].tension == pytest.approx(0.72, abs=0.01)

    async def test_le_temps_d_arret_est_rejoue(self):
        """On ne se réveille pas avec la tension exacte de la veille : les
        horodatages sont reposés, `update()` rejoue l'écoulement."""
        from asgiref.sync import sync_to_async
        from django.utils import timezone as tz

        from drives.models import DriveSnapshot

        source = DriveEngine()
        source.states[DriveKind.REST].tension = 0.9
        await source.save_state()
        await sync_to_async(
            lambda: DriveSnapshot.objects.filter(kind=DriveKind.REST.value).update(
                saved_at=tz.now() - timedelta(hours=1)
            )
        )()

        neuf = DriveEngine()
        await neuf.restore_state()
        # Une heure de décroissance naturelle (0.0001/s) sur la valeur relue.
        assert neuf.states[DriveKind.REST].tension == pytest.approx(0.54, abs=0.02)

    async def test_une_base_vide_laisse_l_etat_a_zero(self):
        neuf = DriveEngine()
        await neuf.restore_state()
        for state in neuf.states.values():
            assert state.tension < 0.01


class TestRafaleDeSignauxPassifs:
    """Une rafale d'observations ne doit pas saturer la fatigue.

    ``conscience.observe()`` appelle ``on_observation()`` pour CHAQUE signal
    externe, et un relevé RSS de neuf flux en produit une centaine d'un coup.
    Mesuré sur un premier démarrage réel : 119 entrées × 0.04 × 0.42 = +2.00
    de tension d'un seul tenant, REST écrêté à 1.00 quarante secondes après
    le boot sans qu'elle ait rien fait — énergie plafonnée à 0.7 × circadien
    toute la journée, brouillard de fatigue dans le prompt à toute heure, et
    coucher rabattu sur son plancher de 21 h tous les soirs.
    """

    def test_une_rafale_ne_sature_pas_la_fatigue(self):
        e = DriveEngine()
        for _ in range(119):
            e.on_observation(0.42)
        e.update()

        assert e.states[DriveKind.REST].tension < 0.5, (
            "un seul relevé RSS suffisait à épingler REST au maximum"
        )

    def test_une_conversation_ordinaire_fatigue_toujours(self):
        """Le plafond borne les rafales, il n'annule pas le modèle : parler
        reste ce qui la fatigue."""
        e = DriveEngine()
        for _ in range(8):
            e.on_reply(word_count=40)
            e.update()

        assert e.states[DriveKind.REST].tension > 0.3

    def test_l_excedent_n_est_pas_reporte(self):
        """Une rafale est UN moment de charge. Reporter l'excédent l'étalerait
        sur les passes suivantes — soit exactement la saturation qu'on borne."""
        e = DriveEngine()
        for _ in range(200):
            e.on_observation(0.5)
        e.update()
        apres_la_rafale = e.states[DriveKind.REST].tension
        e.update()

        assert e.states[DriveKind.REST].tension <= apres_la_rafale
