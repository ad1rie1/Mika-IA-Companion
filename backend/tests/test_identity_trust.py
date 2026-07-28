"""Trust policy — pure functions, no DB, no engine.

Covers the two rules the rest of the identity layer leans on:

  1. a channel grants a floor and imposes a ceiling on certainty
  2. disclosing someone's private history needs corroboration, and never
     happens in a public room

Everything here is deliberately testable without a running system, because
this is where being wrong is expensive: over-trust means Mika recounts what
one person confided to whoever happens to hold a handle bearing their name.
"""
from __future__ import annotations

import pytest

from identity.trust import (
    Certainty,
    ChannelTrust,
    apply_evidence,
    ceiling_for,
    channel_trust,
    clamp,
    describe_fr,
    evaluate,
    floor_for,
    label_for,
    may_disclose_private_context,
    normalize_channel,
)


class TestChannelClassification:

    def test_authenticated_wins_over_everything(self):
        assert channel_trust(
            channel="telegram", authenticated=True, is_group=True,
        ) is ChannelTrust.AUTHENTICATED

    def test_telegram_dm_is_an_account(self):
        assert channel_trust(channel="telegram") is ChannelTrust.ACCOUNT

    def test_group_downgrades_to_public(self):
        assert channel_trust(
            channel="telegram", is_group=True,
        ) is ChannelTrust.PUBLIC

    def test_unauthenticated_web_proves_nothing(self):
        assert channel_trust(channel="web") is ChannelTrust.PUBLIC

    def test_internal_channels_are_not_people(self):
        for name in ("conscience", "internal", "module_email"):
            assert channel_trust(channel=name) is ChannelTrust.INTERNAL

    def test_unknown_channel_defaults_to_public(self):
        """An unnamed transport is assumed to guarantee nothing."""
        assert channel_trust(channel="carrier_pigeon") is ChannelTrust.PUBLIC

    def test_perception_source_aliases_resolve(self):
        """The pipeline says "frontend"; the handle lives on "web"."""
        assert normalize_channel("frontend") == "web"
        assert normalize_channel("FRONTEND") == "web"
        assert normalize_channel("telegram") == "telegram"


class TestCeilingsAndFloors:

    def test_authenticated_starts_and_stays_certain(self):
        assert floor_for(ChannelTrust.AUTHENTICATED) == float(Certainty.VERIFIED)
        assert ceiling_for(ChannelTrust.AUTHENTICATED) == float(Certainty.VERIFIED)

    def test_public_can_never_reach_bound(self):
        """No amount of talking makes a public claim as good as a login."""
        certainty = 0.0
        for _ in range(20):
            certainty = apply_evidence(
                certainty, "shared_memory", trust=ChannelTrust.PUBLIC,
            )
        assert certainty <= float(Certainty.CORROBORATED)
        assert certainty < float(Certainty.BOUND)

    def test_account_channel_caps_below_verified(self):
        certainty = 0.0
        for _ in range(20):
            certainty = apply_evidence(
                certainty, "shared_memory", trust=ChannelTrust.ACCOUNT,
            )
        assert certainty == float(Certainty.BOUND)
        assert certainty < float(Certainty.VERIFIED)

    def test_clamp_never_goes_negative(self):
        assert clamp(-5.0, trust=ChannelTrust.ACCOUNT) == 0.0


class TestEvidence:

    def test_self_declaration_alone_is_not_enough_to_disclose(self):
        """Saying a name is cheap, so it must not unlock a history."""
        certainty = apply_evidence(0.0, "self_declared", trust=ChannelTrust.ACCOUNT)
        assert not may_disclose_private_context(certainty, ChannelTrust.ACCOUNT)

    def test_shared_memory_moves_more_than_a_bare_claim(self):
        claimed = apply_evidence(0.0, "self_declared", trust=ChannelTrust.ACCOUNT)
        proven = apply_evidence(0.0, "shared_memory", trust=ChannelTrust.ACCOUNT)
        assert proven > claimed

    def test_claim_plus_corroboration_clears_the_bar(self):
        certainty = apply_evidence(0.0, "self_declared", trust=ChannelTrust.ACCOUNT)
        certainty = apply_evidence(certainty, "shared_memory", trust=ChannelTrust.ACCOUNT)
        assert may_disclose_private_context(certainty, ChannelTrust.ACCOUNT)

    def test_denial_subtracts(self):
        certainty = apply_evidence(0.8, "denied", trust=ChannelTrust.ACCOUNT)
        assert certainty < 0.8

    def test_revocation_zeroes_it_out(self):
        assert apply_evidence(0.85, "revoked", trust=ChannelTrust.ACCOUNT) == 0.0

    def test_unknown_evidence_kind_is_inert(self):
        """Tool args come from an LLM; a typo must not raise or move anything."""
        assert apply_evidence(0.5, "vibes", trust=ChannelTrust.ACCOUNT) == 0.5

    def test_corroboration_alone_is_not_identification(self):
        """Knowing a fact about Thomas doesn't make you Thomas.

        Without someone actually claiming the name, a shared memory is just a
        topic they happen to know about.
        """
        certainty = apply_evidence(0.0, "shared_memory", trust=ChannelTrust.ACCOUNT)
        assert not may_disclose_private_context(certainty, ChannelTrust.ACCOUNT)

    def test_weights_are_calibrated_against_the_disclosure_bar(self):
        """Guards the calibration the weights were chosen for.

        Changing a weight without revisiting the threshold is exactly how a
        bare claim quietly becomes enough to unlock a private history.
        """
        from identity.trust import EVIDENCE_WEIGHTS, PRIVATE_CONTEXT_THRESHOLD

        claim = EVIDENCE_WEIGHTS["self_declared"]
        proof = EVIDENCE_WEIGHTS["shared_memory"]
        assert claim < PRIVATE_CONTEXT_THRESHOLD, "une affirmation seule suffirait"
        assert proof < PRIVATE_CONTEXT_THRESHOLD, "une preuve sans nom suffirait"
        assert claim + proof >= PRIVATE_CONTEXT_THRESHOLD, (
            "dire qui on est ET le prouver doit convaincre Mika"
        )


class TestDisclosure:

    def test_public_room_never_discloses_even_when_certain(self):
        """The risk in a group isn't mistaken identity — it's the audience."""
        assert not may_disclose_private_context(1.0, ChannelTrust.PUBLIC)

    def test_authenticated_always_discloses(self):
        assert may_disclose_private_context(
            float(Certainty.VERIFIED), ChannelTrust.AUTHENTICATED,
        )

    def test_internal_never_discloses(self):
        assert not may_disclose_private_context(1.0, ChannelTrust.INTERNAL)

    @pytest.mark.parametrize("certainty,expected", [
        (float(Certainty.UNKNOWN), False),
        (float(Certainty.SUSPECTED), False),
        (float(Certainty.CLAIMED), False),
        (float(Certainty.CORROBORATED), True),
        (float(Certainty.BOUND), True),
    ])
    def test_account_threshold_is_corroboration(self, certainty, expected):
        assert may_disclose_private_context(
            certainty, ChannelTrust.ACCOUNT,
        ) is expected


class TestLabelling:

    def test_label_picks_the_level_at_or_below(self):
        assert label_for(0.0) is Certainty.UNKNOWN
        assert label_for(0.30) is Certainty.SUSPECTED
        assert label_for(0.50) is Certainty.CLAIMED
        assert label_for(0.75) is Certainty.CORROBORATED
        assert label_for(1.0) is Certainty.VERIFIED

    def test_description_never_prints_a_number(self):
        """Prompt text must read as a feeling, not a confidence score, or the
        model starts quoting percentages back at the user."""
        for certainty in (0.0, 0.25, 0.45, 0.7, 0.85, 1.0):
            for trust in ChannelTrust:
                text = describe_fr(certainty, trust, "Thomas")
                assert "%" not in text
                assert str(certainty) not in text

    def test_unknown_description_warns_against_assuming(self):
        text = describe_fr(0.0, ChannelTrust.PUBLIC)
        assert "ne suppose rien" in text

    def test_claimed_description_advises_reserve(self):
        text = describe_fr(float(Certainty.CLAIMED), ChannelTrust.ACCOUNT, "Thomas")
        assert "affirme" in text
        assert "confié" in text or "confie" in text

    def test_evaluate_bundles_a_coherent_decision(self):
        decision = evaluate(float(Certainty.BOUND), ChannelTrust.ACCOUNT, "Alice")
        assert decision.certainty == float(Certainty.BOUND)
        assert decision.level is Certainty.BOUND
        assert decision.may_disclose is True
        assert decision.is_confident is True
        assert "Alice" in decision.description

    def test_evaluate_clamps_to_the_channel(self):
        decision = evaluate(1.0, ChannelTrust.PUBLIC, "Alice")
        assert decision.certainty == float(Certainty.CORROBORATED)
        assert decision.may_disclose is False
