"""The identity layer end-to-end: handles, claims, and being convinced.

The regression under all of this: ``link_entity`` existed but nothing ever
called it, so every ``Identity`` row carried ``entity_id = NULL`` and the
per-person memory lookup (``entity__name=person_id``) could never match.
Memory accumulated under "Thomas" while the prompt asked about
"web_6f3e22ccb0ae". These tests pin the three ways that link now gets made.
"""
from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from identity.resolver import identity_resolver
from identity.trust import Certainty, ChannelTrust

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _clean():
    from identity.models import Identity, IdentityClaim, IdentityHandle
    from memory.models import Connaissance, Entity, Souvenir
    IdentityClaim.objects.all().delete()
    IdentityHandle.objects.all().delete()
    Identity.objects.all().delete()
    Souvenir.objects.all().delete()
    Connaissance.objects.all().delete()
    Entity.objects.all().delete()
    yield


async def _handle(person_id: str, channel: str = "telegram",
                  trust: ChannelTrust = ChannelTrust.ACCOUNT):
    return await identity_resolver.link_handle(
        person_id=person_id, channel=channel, kind="module", trust=trust,
    )


class TestHandleRegistration:

    async def test_link_handle_is_idempotent(self):
        from identity.models import Identity, IdentityHandle

        for _ in range(3):
            await _handle("tg_1")

        assert await sync_to_async(IdentityHandle.objects.count)() == 1
        assert await sync_to_async(Identity.objects.count)() == 1

    async def test_trust_can_be_raised_never_silently_lowered(self):
        """An anonymous visitor who logs in keeps the stronger trust.

        Downgrading on a later weaker connection would strip a handle Mika
        legitimately verified, and with it her ability to reach that person
        proactively.
        """
        from identity.models import IdentityHandle

        await _handle("web_1", channel="web", trust=ChannelTrust.PUBLIC)
        await _handle("web_1", channel="web", trust=ChannelTrust.AUTHENTICATED)
        await _handle("web_1", channel="web", trust=ChannelTrust.PUBLIC)

        handle = await sync_to_async(
            lambda: IdentityHandle.objects.get(person_id="web_1")
        )()
        assert handle.trust == ChannelTrust.AUTHENTICATED.value


class TestAuthenticatedBinding:
    """The one path with no deliberation: the transport proved it."""

    async def test_binds_entity_and_maxes_certainty(self):
        from memory.models import Entity

        await _handle("user_7", channel="web", trust=ChannelTrust.AUTHENTICATED)
        identity = await identity_resolver.bind_authenticated(
            "user_7", "web", "Alice",
        )

        assert identity is not None
        assert identity.certainty == float(Certainty.VERIFIED)
        entity = await sync_to_async(lambda: identity.entity)()
        assert entity.name == "Alice"
        assert await sync_to_async(
            lambda: Entity.objects.filter(entity_type="person").count()
        )() == 1

    async def test_entity_for_person_resolves_through_the_handle(self):
        """The lookup that replaces ``entity__name=person_id``."""
        await _handle("user_7", channel="web", trust=ChannelTrust.AUTHENTICATED)
        await identity_resolver.bind_authenticated("user_7", "web", "Alice")

        entity = await identity_resolver.entity_for_person("user_7")
        assert entity is not None
        assert entity.name == "Alice"

    async def test_unbound_handle_resolves_to_nothing(self):
        await _handle("tg_stranger")
        assert await identity_resolver.entity_for_person("tg_stranger") is None

    async def test_records_an_accepted_claim_for_the_ledger(self):
        from identity.models import IdentityClaim

        await _handle("user_7", channel="web", trust=ChannelTrust.AUTHENTICATED)
        await identity_resolver.bind_authenticated("user_7", "web", "Alice")

        claim = await sync_to_async(
            lambda: IdentityClaim.objects.filter(claimed_name="Alice").first()
        )()
        assert claim is not None
        assert claim.status == IdentityClaim.Status.ACCEPTED
        assert claim.kind == IdentityClaim.Kind.AUTHENTICATED


class TestPassiveIngestion:

    async def test_self_introduction_files_a_pending_claim(self):
        from identity.models import IdentityClaim

        await _handle("tg_42")
        claim = await identity_resolver.ingest_message(
            "tg_42", "salut, moi c'est Thomas !", channel="telegram",
        )

        assert claim is not None and claim.name == "Thomas"
        row = await sync_to_async(
            lambda: IdentityClaim.objects.filter(claimed_name="Thomas").first()
        )()
        assert row is not None
        assert row.status == IdentityClaim.Status.PENDING

    async def test_a_claim_alone_binds_nothing(self):
        """Saying a name must not, on its own, make Mika believe it."""
        await _handle("tg_42")
        await identity_resolver.ingest_message(
            "tg_42", "moi c'est Thomas", channel="telegram",
        )
        assert await identity_resolver.entity_for_person("tg_42") is None

    async def test_repeating_the_claim_does_not_stack_rows(self):
        from identity.models import IdentityClaim

        await _handle("tg_42")
        for _ in range(4):
            await identity_resolver.ingest_message(
                "tg_42", "je m'appelle Thomas", channel="telegram",
            )
        count = await sync_to_async(
            lambda: IdentityClaim.objects.filter(claimed_name="Thomas").count()
        )()
        assert count == 1

    async def test_ordinary_message_files_nothing(self):
        from identity.models import IdentityClaim

        await _handle("tg_42")
        assert await identity_resolver.ingest_message(
            "tg_42", "tu as vu le match hier ?", channel="telegram",
        ) is None
        assert await sync_to_async(IdentityClaim.objects.count)() == 0

    async def test_internal_person_ids_are_never_identified(self):
        for pid in ("conscience_mika", "__global__", "anonymous", ""):
            assert await identity_resolver.ingest_message(
                pid, "moi c'est Thomas",
            ) is None

    async def test_authenticated_name_updates_display_only(self):
        """On a proven session a name is a preference, not evidence."""
        from identity.models import Identity, IdentityClaim

        await _handle("user_7", channel="web", trust=ChannelTrust.AUTHENTICATED)
        await identity_resolver.bind_authenticated("user_7", "web", "Alice")
        await identity_resolver.ingest_message(
            "user_7", "appelle-moi Lili, moi c'est Lili", channel="web",
            authenticated=True,
        )

        identity = await sync_to_async(
            lambda: Identity.objects.select_related("entity").first()
        )()
        assert identity.display_name == "Lili"
        # Still bound to the account's entity; certainty untouched.
        assert identity.entity.name == "Alice"
        assert identity.certainty == float(Certainty.VERIFIED)
        pending = await sync_to_async(
            lambda: IdentityClaim.objects.filter(status="pending").count()
        )()
        assert pending == 0


class TestBeingConvinced:
    """"Se laisser convaincre" — the deliberate half."""

    async def _pending_claim_id(self, person_id="tg_42", name="Thomas"):
        from identity.models import IdentityClaim

        await identity_resolver.ingest_message(
            person_id, f"moi c'est {name}", channel="telegram",
        )
        return await sync_to_async(
            lambda: IdentityClaim.objects.get(
                claimed_name=name, status=IdentityClaim.Status.PENDING,
            ).pk
        )()

    async def test_accepting_binds_the_entity(self):
        await _handle("tg_42")
        claim_id = await self._pending_claim_id()

        result = await identity_resolver.accept_claim(
            claim_id, reason="il connaissait le concert",
            evidence_kind="shared_memory",
        )
        assert result["ok"] is True

        entity = await identity_resolver.entity_for_person("tg_42")
        assert entity is not None and entity.name == "Thomas"

    async def test_accepting_on_a_public_channel_is_capped(self):
        """A public room can never produce a binding as strong as a DM.

        The same accepted claim lands lower here than it would in a private
        exchange, and no amount of further evidence closes the gap.
        """
        await _handle("tg_group", trust=ChannelTrust.PUBLIC)
        claim_id = await self._pending_claim_id("tg_group", "Julie")

        result = await identity_resolver.accept_claim(
            claim_id, evidence_kind="shared_memory",
        )
        assert result["ok"] is True
        assert result["certainty"] <= float(Certainty.CORROBORATED)

        # Pile on more corroboration: it saturates at the channel ceiling
        # rather than climbing toward BOUND.
        for _ in range(5):
            final = await identity_resolver.record_evidence(
                "tg_group", kind="shared_memory", detail="encore un detail juste",
            )
        assert final["certainty"] == float(Certainty.CORROBORATED)
        assert final["certainty"] < float(Certainty.BOUND)

    async def test_accepting_with_proof_actually_unlocks_disclosure(self):
        """Believing someone has to *mean* something.

        Accepting a claim scores the assertion AND the corroboration; scoring
        only the latter left Mika bound to a person whose history she still
        wasn't allowed to recall — believed on paper, amnesiac in practice.
        """
        from identity.trust import ChannelTrust as CT, may_disclose_private_context

        await _handle("tg_dm", trust=CT.ACCOUNT)
        claim_id = await self._pending_claim_id("tg_dm", "Julie")

        result = await identity_resolver.accept_claim(
            claim_id, evidence_kind="shared_memory",
        )
        assert may_disclose_private_context(result["certainty"], CT.ACCOUNT)

        ctx = await identity_resolver.resolve_context("tg_dm", channel="telegram")
        assert ctx.may_disclose is True
        assert ctx.known_as == "Julie"

    async def test_accepting_without_proof_binds_but_stays_guarded(self):
        """Choosing to play along is not the same as being convinced."""
        from identity.trust import ChannelTrust as CT, may_disclose_private_context

        await _handle("tg_dm2", trust=CT.ACCOUNT)
        claim_id = await self._pending_claim_id("tg_dm2", "Marc")

        result = await identity_resolver.accept_claim(claim_id, reason="pourquoi pas")
        assert result["ok"] is True
        assert not may_disclose_private_context(result["certainty"], CT.ACCOUNT)

    async def test_saturation_sets_the_capped_flag(self):
        await _handle("tg_group2", trust=ChannelTrust.PUBLIC)
        await identity_resolver.record_evidence(
            "tg_group2", kind="shared_memory", detail="un detail juste",
            name="Julie",
        )
        claim_id = await self._pending_claim_id("tg_group2", "Julie")
        result = await identity_resolver.accept_claim(
            claim_id, evidence_kind="shared_memory",
        )
        assert result["capped_by_channel"] is True

    async def test_rejecting_leaves_nothing_bound(self):
        from identity.models import IdentityClaim

        await _handle("tg_42")
        claim_id = await self._pending_claim_id()

        result = await identity_resolver.reject_claim(
            claim_id, reason="il s'est trompé sur tout",
        )
        assert result["ok"] is True
        assert await identity_resolver.entity_for_person("tg_42") is None

        claim = await sync_to_async(lambda: IdentityClaim.objects.get(pk=claim_id))()
        assert claim.status == IdentityClaim.Status.REJECTED

    async def test_a_claim_cannot_be_resolved_twice(self):
        await _handle("tg_42")
        claim_id = await self._pending_claim_id()
        await identity_resolver.accept_claim(claim_id)
        again = await identity_resolver.accept_claim(claim_id)
        assert again["ok"] is False

    async def test_unknown_claim_id_is_reported_not_raised(self):
        result = await identity_resolver.accept_claim(999_999)
        assert result["ok"] is False


class TestDoubtAndRevocation:

    async def test_denial_unbinds_immediately(self):
        """Being told "I'm not Thomas" must not wait for deliberation.

        If she is calling a stranger by a friend's name, everything
        downstream — the profile, the commitments, the shared history — is
        already wrong.
        """
        await _handle("tg_42")
        await identity_resolver.link_entity("tg_42", "Thomas")
        assert await identity_resolver.entity_for_person("tg_42") is not None

        await identity_resolver.ingest_message(
            "tg_42", "euh, je ne suis pas Thomas", channel="telegram",
        )
        assert await identity_resolver.entity_for_person("tg_42") is None

    async def test_denial_of_another_name_lowers_without_unbinding(self):
        await _handle("tg_42")
        await identity_resolver.link_entity("tg_42", "Thomas")

        await identity_resolver.ingest_message(
            "tg_42", "je ne suis pas Julie", channel="telegram",
        )
        entity = await identity_resolver.entity_for_person("tg_42")
        assert entity is not None and entity.name == "Thomas"

    async def test_contradiction_below_threshold_unbinds(self):
        await _handle("tg_42")
        await identity_resolver.link_entity("tg_42", "Thomas")

        # Two contradictions from BOUND (0.85): 0.85 → 0.50 → 0.15
        await identity_resolver.record_evidence(
            "tg_42", kind="contradicted", detail="ne connait pas sa propre soeur",
        )
        result = await identity_resolver.record_evidence(
            "tg_42", kind="contradicted", detail="se trompe de ville",
        )
        assert result["unbound"] is True
        assert await identity_resolver.entity_for_person("tg_42") is None

    async def test_revoke_drops_everything(self):
        await _handle("tg_42")
        await identity_resolver.link_entity("tg_42", "Thomas")

        result = await identity_resolver.revoke("tg_42", reason="je n'y crois plus")
        assert result["ok"] is True
        assert result["certainty"] == 0.0
        assert await identity_resolver.entity_for_person("tg_42") is None

    async def test_evidence_on_unknown_handle_is_reported(self):
        result = await identity_resolver.record_evidence(
            "tg_nobody", kind="shared_memory", detail="peu importe",
        )
        assert result["ok"] is False


class TestResolveContext:

    async def test_unknown_visitor_discloses_nothing(self):
        ctx = await identity_resolver.resolve_context("tg_new", channel="telegram")
        assert ctx.is_identified is False
        assert ctx.may_disclose is False
        assert ctx.description

    async def test_authenticated_context_is_certain(self):
        await _handle("user_7", channel="web", trust=ChannelTrust.AUTHENTICATED)
        await identity_resolver.bind_authenticated("user_7", "web", "Alice")

        ctx = await identity_resolver.resolve_context(
            "user_7", channel="frontend", authenticated=True,
        )
        assert ctx.trust is ChannelTrust.AUTHENTICATED
        assert ctx.certainty == float(Certainty.VERIFIED)
        assert ctx.may_disclose is True
        assert ctx.known_as == "Alice"

    async def test_pending_claims_are_surfaced(self):
        await _handle("tg_42")
        await identity_resolver.ingest_message(
            "tg_42", "moi c'est Thomas", channel="telegram",
        )
        ctx = await identity_resolver.resolve_context("tg_42", channel="telegram")
        assert len(ctx.pending_claims) == 1
        assert ctx.pending_claims[0]["name"] == "Thomas"

    async def test_a_pending_claim_reads_as_claimed_not_guessed(self):
        """She was told a name; describing that as a hunch would be wrong.

        The claim is deliberately unscored until she accepts it, which left
        the raw certainty at the channel floor and produced "tu crois deviner
        que c'est cette personne" — both vague about the name she was just
        given, and wrong about how she came by it.
        """
        await _handle("tg_42")
        await identity_resolver.ingest_message(
            "tg_42", "salut, moi c'est Thomas", channel="telegram",
        )
        ctx = await identity_resolver.resolve_context("tg_42", channel="telegram")

        assert "Thomas" in ctx.description
        assert "affirme" in ctx.description
        # Wording changed; the guarantee did not.
        assert ctx.may_disclose is False
        assert ctx.is_identified is False

    async def test_public_room_overrides_a_private_binding(self):
        """Known in DMs is not known in a group."""
        await _handle("tg_42")
        await identity_resolver.link_entity("tg_42", "Thomas")

        private = await identity_resolver.resolve_context("tg_42", channel="telegram")
        public = await identity_resolver.resolve_context(
            "tg_42", channel="telegram", is_public=True,
        )
        assert private.may_disclose is True
        assert public.may_disclose is False

    async def test_internal_ids_short_circuit(self):
        ctx = await identity_resolver.resolve_context("conscience_mika")
        assert ctx.is_internal
        assert ctx.trust is ChannelTrust.INTERNAL
        assert ctx.may_disclose is False


class TestCorroborationLookup:

    async def test_scores_against_what_memory_holds(self):
        from memory.models import Connaissance, Entity

        entity = await sync_to_async(Entity.objects.create)(
            name="Thomas", entity_type="person",
        )
        conn = await sync_to_async(Connaissance.objects.create)(
            content="Thomas était au festival de guitare à Toulouse",
        )
        await sync_to_async(conn.entities.set)([entity])

        score, reason = await identity_resolver.check_corroboration(
            "tg_42", "le festival de guitare à Toulouse, quel souvenir", "Thomas",
        )
        assert score > 0.0
        assert "recoupe" in reason

    async def test_unknown_name_scores_zero(self):
        score, _ = await identity_resolver.check_corroboration(
            "tg_42", "peu importe ce que je dis", "Personne",
        )
        assert score == 0.0


class TestConcernRouting:
    """``handles_for_entity_names`` — dead until entities were actually bound."""

    async def test_resolves_a_bound_person_to_their_handles(self):
        await _handle("tg_42")
        await identity_resolver.link_entity("tg_42", "Thomas")

        mapping = await identity_resolver.handles_for_entity_names(["Thomas"])
        assert "Thomas" in mapping
        assert mapping["Thomas"][0]["person_id"] == "tg_42"

    async def test_unbound_person_resolves_to_nothing(self):
        await _handle("tg_42")
        assert await identity_resolver.handles_for_entity_names(["Thomas"]) == {}
