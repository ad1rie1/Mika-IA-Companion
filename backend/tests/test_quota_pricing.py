"""La table de tarifs, et ce qu'un jeton de cache coûte vraiment.

Le défaut confirmé : la table s'arrêtait à Opus 4.7 / Sonnet 4.6, donc
Fable, Mythos et toute la série 5 ne correspondaient à rien et tournaient à
$0 sur le tableau de bord — indiscernables d'un modèle local. Et le
provider Claude fondait ``cache_read`` / ``cache_creation`` dans ``in``, que
le compteur facturait au tarif d'entrée plein : dix fois le prix réel d'une
lecture de cache, sur le poste le plus lourd du système.

Les ids et tarifs viennent du skill ``claude-api`` (cache du 2026-06-24),
jamais de mémoire.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from ai import quota
from ai.quota import (
    QuotaTracker,
    _lookup_cache_pricing,
    _lookup_pricing,
    _usage_ctx,
)

pytestmark = pytest.mark.usefixtures("config_hors_base")

# (id, entrée $/M, sortie $/M) — les modèles servis au relevé du skill.
_MODELES_COURANTS = [
    ("claude-fable-5-1", 10.0, 50.0),
    ("claude-mythos-5-1", 10.0, 50.0),
    ("claude-fable-5", 10.0, 50.0),
    ("claude-opus-5", 5.0, 25.0),
    ("claude-opus-4-8", 5.0, 25.0),
    ("claude-opus-4-7", 5.0, 25.0),
    ("claude-opus-4-6", 5.0, 25.0),
    ("claude-sonnet-5", 2.0, 10.0),
    ("claude-sonnet-4-6", 3.0, 15.0),
    ("claude-haiku-4-5", 1.0, 5.0),
]


@pytest.fixture(autouse=True)
def _etat_vierge():
    quota._unpriced_warned.clear()
    _usage_ctx.set(None)
    yield
    quota._unpriced_warned.clear()
    _usage_ctx.set(None)


class TestTableDesTarifs:

    @pytest.mark.parametrize("model_id,entree,sortie", _MODELES_COURANTS)
    def test_chaque_modele_courant_a_son_tarif(self, model_id, entree, sortie):
        in_rate, out_rate = _lookup_pricing("claude", model_id)
        assert in_rate == pytest.approx(entree / 1_000_000)
        assert out_rate == pytest.approx(sortie / 1_000_000)

    def test_les_familles_5_ne_retombent_plus_a_zero(self):
        """Le défaut, tel qu'il se voyait : un id de la série 5 valait $0."""
        for model_id in ("claude-opus-5", "claude-sonnet-5", "claude-fable-5-1"):
            assert _lookup_pricing("claude", model_id)[0] > 0

    def test_un_opus_4_x_inconnu_suit_le_tarif_courant_de_la_famille(self):
        assert _lookup_pricing("claude", "claude-opus-4-9")[0] == pytest.approx(5 / 1_000_000)

    def test_les_opus_4_0_et_4_1_gardent_leur_ancien_tarif(self):
        assert _lookup_pricing("claude", "claude-opus-4-1")[0] == pytest.approx(15 / 1_000_000)
        assert _lookup_pricing("claude", "claude-opus-4-0")[1] == pytest.approx(75 / 1_000_000)


class TestJetonsDeCache:

    def test_lecture_a_un_dixieme_ecriture_a_cinq_quarts(self):
        in_rate, _ = _lookup_pricing("claude", "claude-opus-5")
        read, write = _lookup_cache_pricing("claude", "claude-opus-5")
        assert read == pytest.approx(in_rate * 0.1)
        assert write == pytest.approx(in_rate * 1.25)

    def test_fable_5_1_lit_son_cache_au_tarif_publie(self):
        """$0,25/M, soit 0,025× — l'exception publiée, pas le taux général."""
        read, write = _lookup_cache_pricing("claude", "claude-fable-5-1")
        assert read == pytest.approx(0.25 / 1_000_000)
        assert write == pytest.approx(10.0 * 1.25 / 1_000_000)
        # Fable 5, lui, reste au taux général ($1/M).
        assert _lookup_cache_pricing("claude", "claude-fable-5")[0] == pytest.approx(1.0 / 1_000_000)

    def test_un_modele_gratuit_a_un_cache_gratuit(self):
        assert _lookup_cache_pricing("ollama", "gemma4:12b") == (0.0, 0.0)

    def test_record_facture_le_cache_a_son_tarif_et_le_compte_dans_le_quota(self):
        tracker = QuotaTracker()
        cost = tracker.record(
            role="conversation_tools", provider="claude", model="claude-opus-5",
            tokens_in=1000, tokens_out=100,
            cache_read_tokens=10_000, cache_write_tokens=1000,
        )
        attendu = (
            1000 * 5 / 1e6            # entrée pleine
            + 100 * 25 / 1e6          # sortie
            + 10_000 * 0.5 / 1e6      # lecture de cache à 0,1×
            + 1000 * 6.25 / 1e6       # écriture de cache à 1,25×
        )
        assert cost == pytest.approx(attendu)
        # Avant : 11 000 jetons d'entrée à $5/M = $0,055 rien que pour
        # l'entrée. Le vrai chiffre est presque quatre fois moindre.
        assert cost < 11_000 * 5 / 1e6
        snap = tracker.snapshot()
        assert snap.roles["conversation_tools"]["tokens_day"] == 12_100

    def test_record_sans_cache_est_inchange(self):
        tracker = QuotaTracker()
        cost = tracker.record(
            role="conversation", provider="claude", model="claude-sonnet-5",
            tokens_in=1000, tokens_out=1000,
        )
        assert cost == pytest.approx((2.0 + 10.0) / 1000)


class TestLeProviderClaudeSepareLeCache:

    def test_accumulate_garde_les_trois_postes_distincts(self):
        from ai.providers.claude import ClaudeProvider, _new_totals

        usage = SimpleNamespace(
            input_tokens=100, output_tokens=20,
            cache_read_input_tokens=5000, cache_creation_input_tokens=700,
        )
        totals = _new_totals()
        ClaudeProvider._accumulate_usage(usage, totals)
        assert totals == {"in": 100, "out": 20, "cache_read": 5000, "cache_write": 700}

    def test_flush_remonte_les_jetons_de_cache_au_routeur(self):
        from ai.providers.claude import ClaudeProvider

        ClaudeProvider._flush_usage(
            {"in": 100, "out": 20, "cache_read": 5000, "cache_write": 700},
        )
        assert _usage_ctx.get() == {
            "in": 100, "out": 20, "cache_read": 5000, "cache_write": 700,
        }

    def test_un_cache_seul_est_quand_meme_remonte(self):
        """Un tour entièrement servi par le cache a ``in == 0`` : avant, le
        garde ``in or out`` suffisait parce que le cache était fondu dedans."""
        from ai.providers.claude import ClaudeProvider

        ClaudeProvider._flush_usage(
            {"in": 0, "out": 0, "cache_read": 5000, "cache_write": 0},
        )
        assert _usage_ctx.get()["cache_read"] == 5000


class TestModeleSansTarif:

    def test_un_provider_payant_sans_tarif_le_dit_une_fois(self, caplog):
        with caplog.at_level(logging.WARNING, logger="ai.quota"):
            assert _lookup_pricing("openai", "gpt-inconnu") == (0.0, 0.0)
            _lookup_pricing("openai", "gpt-inconnu")
            _lookup_pricing("openai", "gpt-inconnu")
        avert = [r for r in caplog.records if "gpt-inconnu" in r.getMessage()]
        assert len(avert) == 1
        assert avert[0].levelno == logging.WARNING

    def test_chaque_paire_provider_modele_a_son_propre_avertissement(self, caplog):
        with caplog.at_level(logging.WARNING, logger="ai.quota"):
            _lookup_pricing("openai", "a-inconnu")
            _lookup_pricing("glm", "b-inconnu")
        assert len([r for r in caplog.records if "inconnu" in r.getMessage()]) == 2

    def test_ollama_ne_previent_jamais(self, caplog):
        """Un modèle local n'a pas de tarif : ce n'est pas un trou de table."""
        with caplog.at_level(logging.WARNING, logger="ai.quota"):
            _lookup_pricing("ollama", "gemma4:12b")
            _lookup_pricing("ollama_cloud", "gpt-oss:120b")
        assert caplog.records == []
