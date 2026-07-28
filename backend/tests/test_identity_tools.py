"""The MCP surface Mika uses to decide who she is talking to.

These handlers are the *active* half of identification: passive detection
only ever files a claim, and nothing binds until she calls one of these.
"""
from __future__ import annotations

import pytest
from asgiref.sync import sync_to_async

from identity.module import IdentityToolsModule
from identity.resolver import identity_resolver
from identity.trust import ChannelTrust
from pipeline.tracing import set_current_person_id

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _clean():
    from identity.models import Identity, IdentityClaim, IdentityHandle
    from memory.models import Connaissance, Entity
    IdentityClaim.objects.all().delete()
    IdentityHandle.objects.all().delete()
    Identity.objects.all().delete()
    Connaissance.objects.all().delete()
    Entity.objects.all().delete()
    set_current_person_id("")
    yield
    set_current_person_id("")


def _text(result: dict) -> str:
    return result["content"][0]["text"]


async def _claim_from(person_id: str, message: str, trust=ChannelTrust.ACCOUNT):
    from identity.models import IdentityClaim

    await identity_resolver.link_handle(
        person_id=person_id, channel="telegram", kind="module", trust=trust,
    )
    await identity_resolver.ingest_message(person_id, message, channel="telegram")
    return await sync_to_async(
        lambda: IdentityClaim.objects.filter(status="pending").first()
    )()


class TestToolSurface:

    def test_exposes_the_expected_tools(self):
        names = {t.name for t in IdentityToolsModule().return_tools()}
        assert names == {
            "identity_whoami_with",
            "identity_accept_claim",
            "identity_reject_claim",
            "identity_record_evidence",
            "identity_check_story",
            "identity_forget_binding",
        }

    def test_every_tool_has_a_schema(self):
        for tool in IdentityToolsModule().return_tools():
            schema = tool.to_json_schema()
            assert schema["type"] == "object"
            assert tool.description


class TestWhoamiWith:

    async def test_uses_the_ambient_person_when_none_given(self):
        """Mika never passes a person_id — from inside a turn it's implicit."""
        await _claim_from("tg_7", "moi c'est Thomas")
        set_current_person_id("tg_7")

        body = _text(await IdentityToolsModule()._whoami_with({}))
        assert "tg_7" in body
        assert "Thomas" in body

    async def test_reports_no_person_in_scope(self):
        body = _text(await IdentityToolsModule()._whoami_with({}))
        assert "ne sais pas" in body

    async def test_lists_pending_claims_with_their_ids(self):
        claim = await _claim_from("tg_7", "je m'appelle Thomas")
        set_current_person_id("tg_7")

        body = _text(await IdentityToolsModule()._whoami_with({}))
        assert f"#{claim.pk}" in body
        assert "identity_accept_claim" in body

    async def test_warns_when_private_context_is_off_limits(self):
        await _claim_from("tg_7", "moi c'est Thomas")
        set_current_person_id("tg_7")

        body = _text(await IdentityToolsModule()._whoami_with({}))
        assert "ne devrais PAS" in body

    async def test_authenticated_person_reads_as_certain(self):
        await identity_resolver.link_handle(
            person_id="user_1", channel="web", kind="consumer",
            trust=ChannelTrust.AUTHENTICATED,
        )
        await identity_resolver.bind_authenticated("user_1", "web", "Alice")
        set_current_person_id("user_1")

        body = _text(await IdentityToolsModule()._whoami_with({}))
        assert "Alice" in body
        assert "authentifiee" in body
        assert "Tu peux evoquer" in body


class TestAcceptReject:

    async def test_accepting_binds_and_says_so(self):
        claim = await _claim_from("tg_7", "moi c'est Thomas")
        result = await IdentityToolsModule()._accept_claim({
            "claim_id": claim.pk,
            "reason": "il connaissait le concert",
            "evidence_kind": "shared_memory",
        })
        assert "Thomas" in _text(result)
        assert await identity_resolver.entity_for_person("tg_7") is not None

    async def test_accepting_on_public_mentions_the_reserve(self):
        await identity_resolver.link_handle(
            person_id="tg_pub", channel="telegram", kind="module",
            trust=ChannelTrust.PUBLIC,
        )
        await identity_resolver.record_evidence(
            "tg_pub", kind="shared_memory", detail="un detail juste", name="Julie",
        )
        await identity_resolver.ingest_message(
            "tg_pub", "moi c'est Julie", channel="telegram",
        )
        from identity.models import IdentityClaim
        claim = await sync_to_async(
            lambda: IdentityClaim.objects.filter(status="pending").first()
        )()

        result = await IdentityToolsModule()._accept_claim({
            "claim_id": claim.pk, "evidence_kind": "shared_memory",
        })
        assert "public" in _text(result)

    async def test_rejecting_reports_the_name(self):
        claim = await _claim_from("tg_7", "moi c'est Thomas")
        result = await IdentityToolsModule()._reject_claim({
            "claim_id": claim.pk, "reason": "trop d'incoherences",
        })
        assert "Thomas" in _text(result)
        assert await identity_resolver.entity_for_person("tg_7") is None

    async def test_bad_claim_id_is_answered_not_raised(self):
        result = await IdentityToolsModule()._accept_claim({"claim_id": "abc"})
        assert "invalide" in _text(result)

    async def test_missing_claim_is_answered_not_raised(self):
        result = await IdentityToolsModule()._accept_claim({"claim_id": 999_999})
        assert "Impossible" in _text(result)


class TestEvidence:

    async def test_records_corroboration_and_reports_the_level(self):
        await _claim_from("tg_7", "moi c'est Thomas")
        await identity_resolver.link_entity("tg_7", "Thomas")
        set_current_person_id("tg_7")

        result = await IdentityToolsModule()._record_evidence({
            "kind": "shared_memory",
            "detail": "elle a parle du concert dont seule Thomas savait",
        })
        assert "Thomas" in _text(result)

    async def test_contradiction_can_unbind_and_says_so(self):
        await _claim_from("tg_7", "moi c'est Thomas")
        await identity_resolver.link_entity("tg_7", "Thomas")
        set_current_person_id("tg_7")

        module = IdentityToolsModule()
        await module._record_evidence(
            {"kind": "contradicted", "detail": "se trompe de ville"},
        )
        result = await module._record_evidence(
            {"kind": "contradicted", "detail": "ne connait pas sa soeur"},
        )
        assert "coupe le lien" in _text(result)
        assert await identity_resolver.entity_for_person("tg_7") is None

    async def test_unknown_evidence_kind_is_refused(self):
        set_current_person_id("tg_7")
        result = await IdentityToolsModule()._record_evidence(
            {"kind": "vibes", "detail": "je le sens bien"},
        )
        assert "inconnu" in _text(result)

    async def test_empty_detail_is_refused(self):
        set_current_person_id("tg_7")
        result = await IdentityToolsModule()._record_evidence(
            {"kind": "shared_memory", "detail": "   "},
        )
        assert "Precise" in _text(result)


class TestCheckStory:

    async def test_no_overlap_is_reported_as_inconclusive(self):
        set_current_person_id("tg_7")
        result = await IdentityToolsModule()._check_story({
            "name": "Thomas", "message": "il fait beau aujourd'hui",
        })
        body = _text(result)
        assert "Rien" in body
        assert "ne prouve pas que c'est faux" in body

    async def test_overlap_is_reported_as_an_indication(self):
        from memory.models import Connaissance, Entity

        entity = await sync_to_async(Entity.objects.create)(
            name="Thomas", entity_type="person",
        )
        conn = await sync_to_async(Connaissance.objects.create)(
            content="Thomas etait au festival de guitare a Toulouse",
        )
        await sync_to_async(conn.entities.set)([entity])
        set_current_person_id("tg_7")

        result = await IdentityToolsModule()._check_story({
            "name": "Thomas",
            "message": "le festival de guitare a Toulouse, quel souvenir",
        })
        body = _text(result)
        assert "Indice" in body
        assert "shared_memory" in body

    async def test_missing_arguments_are_refused(self):
        result = await IdentityToolsModule()._check_story({"name": "", "message": ""})
        assert "il me faut" in _text(result).lower()


class TestForgetBinding:

    async def test_unbinds_and_explains(self):
        await _claim_from("tg_7", "moi c'est Thomas")
        await identity_resolver.link_entity("tg_7", "Thomas")
        set_current_person_id("tg_7")

        result = await IdentityToolsModule()._forget_binding(
            {"reason": "ce n'etait pas lui"},
        )
        assert "defait" in _text(result)
        assert await identity_resolver.entity_for_person("tg_7") is None

    async def test_without_a_person_in_scope(self):
        result = await IdentityToolsModule()._forget_binding({"reason": "x"})
        assert "ne sais pas" in _text(result)
