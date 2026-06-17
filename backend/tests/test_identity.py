"""Tests for the identity layer: handle persistence and entity-name resolution."""

import pytest
from asgiref.sync import sync_to_async

from identity.resolver import identity_resolver


@pytest.mark.django_db(transaction=True)
class TestLinkHandle:

    async def test_creates_identity_and_handle(self):
        from identity.models import Identity, IdentityHandle

        identity = await identity_resolver.link_handle(
            person_id="tg_1", channel="telegram", kind="module",
            delivery_ref="555", display_name="Bob",
        )
        assert identity is not None
        assert await sync_to_async(Identity.objects.count)() == 1
        handle = await sync_to_async(
            lambda: IdentityHandle.objects.get(person_id="tg_1")
        )()
        assert handle.channel == "telegram"
        assert handle.delivery_ref == "555"

    async def test_refresh_updates_handle_no_duplicate(self):
        from identity.models import Identity, IdentityHandle

        await identity_resolver.link_handle(
            person_id="tg_1", channel="telegram", delivery_ref="111"
        )
        await identity_resolver.link_handle(
            person_id="tg_1", channel="telegram", delivery_ref="222"
        )
        assert await sync_to_async(IdentityHandle.objects.count)() == 1
        assert await sync_to_async(Identity.objects.count)() == 1
        handle = await sync_to_async(
            lambda: IdentityHandle.objects.get(person_id="tg_1")
        )()
        assert handle.delivery_ref == "222"

    async def test_handles_for_person_multichannel(self):
        # Same person reachable on two channels → both handles share one identity
        # only if linked; here they are separate identities unless merged. We test
        # that handles_for_person returns the handles of the owning identity.
        ident = await identity_resolver.link_handle(
            person_id="user_7", channel="web", kind="consumer", delivery_ref="grp"
        )
        # attach a second handle to the SAME identity directly
        from identity.models import IdentityHandle

        await sync_to_async(IdentityHandle.objects.create)(
            identity=ident, channel="telegram", person_id="tg_7",
            kind="module", delivery_ref="999",
        )
        handles = await identity_resolver.handles_for_person("user_7")
        channels = {h["channel"] for h in handles}
        assert channels == {"web", "telegram"}


@pytest.mark.django_db(transaction=True)
class TestEntityResolution:

    async def test_link_entity_then_resolve_to_handles(self):
        await identity_resolver.link_handle(
            person_id="tg_1", channel="telegram", delivery_ref="555"
        )
        await identity_resolver.link_entity("tg_1", "Bob")

        mapping = await identity_resolver.handles_for_entity_names(["Bob"])
        assert "Bob" in mapping
        person_ids = {h["person_id"] for h in mapping["Bob"]}
        assert "tg_1" in person_ids

    async def test_unknown_entity_name_empty(self):
        mapping = await identity_resolver.handles_for_entity_names(["Nobody"])
        assert mapping == {}

    async def test_link_entity_sets_display_name(self):
        from identity.models import Identity

        ident = await identity_resolver.link_handle(
            person_id="tg_2", channel="telegram", delivery_ref="1"
        )
        await identity_resolver.link_entity("tg_2", "Alice")
        refreshed = await sync_to_async(Identity.objects.get)(pk=ident.pk)
        assert refreshed.display_name == "Alice"
