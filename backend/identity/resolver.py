"""IdentityResolver — async R/W interface over the identity layer.

Turns the names conversation teaches into deliverable handles, and vice-versa.
All ORM access is wrapped in ``sync_to_async`` (called from the async pipeline).
"""

from __future__ import annotations

import logging

from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


class IdentityResolver:
    """Links transport handles ↔ canonical identities ↔ memory entities."""

    async def link_handle(
        self,
        person_id: str,
        channel: str,
        kind: str = "module",
        delivery_ref: str = "",
        display_name: str = "",
    ):
        """Persist that ``person_id`` is reachable on ``channel``.

        Upserts the handle (keyed by channel+person_id) and ensures it is
        attached to an Identity. Returns the Identity, or None on failure.
        Called when a consumer connects or a module sees a user.
        """
        return await sync_to_async(self._link_handle_sync)(
            person_id, channel, kind, delivery_ref, display_name
        )

    def _link_handle_sync(self, person_id, channel, kind, delivery_ref, display_name):
        from identity.models import Identity, IdentityHandle

        try:
            handle = IdentityHandle.objects.filter(
                channel=channel, person_id=person_id
            ).select_related("identity").first()

            if handle:
                if delivery_ref:
                    handle.delivery_ref = delivery_ref
                if display_name:
                    handle.display_name = display_name
                handle.save(update_fields=["delivery_ref", "display_name", "last_seen"])
                return handle.identity

            identity = Identity.objects.create(display_name=display_name)
            IdentityHandle.objects.create(
                identity=identity,
                channel=channel,
                person_id=person_id,
                kind=kind,
                delivery_ref=delivery_ref,
                display_name=display_name,
            )
            return identity
        except Exception:
            logger.warning(
                "link_handle failed for %s@%s", person_id, channel, exc_info=True
            )
            return None

    async def link_entity(self, person_id: str, entity_name: str):
        """Bind an identity (by one of its handles) to a memory person-entity.

        This is how "the handle tg_123" becomes known as "the person Bob" in
        memory, enabling concern-based routing from entity names to handles.
        """
        return await sync_to_async(self._link_entity_sync)(person_id, entity_name)

    def _link_entity_sync(self, person_id, entity_name):
        from identity.models import IdentityHandle
        from memory.models import Entity

        try:
            handle = IdentityHandle.objects.select_related("identity").filter(
                person_id=person_id
            ).first()
            if not handle:
                return None
            entity, _ = Entity.objects.get_or_create(
                name=entity_name, entity_type="person"
            )
            identity = handle.identity
            identity.entity = entity
            if not identity.display_name:
                identity.display_name = entity_name
            identity.save(update_fields=["entity", "display_name", "last_seen"])
            return identity
        except Exception:
            logger.warning(
                "link_entity failed for %s/%s", person_id, entity_name, exc_info=True
            )
            return None

    async def handles_for_person(self, person_id: str) -> list[dict]:
        """All persisted handles for the identity owning ``person_id``."""
        return await sync_to_async(self._handles_for_person_sync)(person_id)

    def _handles_for_person_sync(self, person_id) -> list[dict]:
        from identity.models import IdentityHandle

        handle = IdentityHandle.objects.select_related("identity").filter(
            person_id=person_id
        ).first()
        if not handle:
            return []
        return [
            {
                "person_id": h.person_id,
                "channel": h.channel,
                "kind": h.kind,
                "delivery_ref": h.delivery_ref,
                "display_name": h.display_name,
            }
            for h in handle.identity.handles.all()
        ]

    async def handles_for_entity_names(self, names: list[str]) -> dict[str, list[dict]]:
        """Map each person-entity name → its reachable handles (durable view).

        Used by concern-based routing: memory says "X is concerned", this returns
        how to reach X. Reachability *now* is then filtered via the presence
        registry by the caller.
        """
        if not names:
            return {}
        return await sync_to_async(self._handles_for_entity_names_sync)(names)

    def _handles_for_entity_names_sync(self, names) -> dict[str, list[dict]]:
        from identity.models import Identity

        out: dict[str, list[dict]] = {}
        identities = Identity.objects.filter(
            entity__name__in=names, entity__entity_type="person"
        ).select_related("entity").prefetch_related("handles")
        for ident in identities:
            key = ident.entity.name if ident.entity else ident.display_name
            handles = [
                {
                    "person_id": h.person_id,
                    "channel": h.channel,
                    "kind": h.kind,
                    "delivery_ref": h.delivery_ref,
                    "display_name": h.display_name,
                }
                for h in ident.handles.all()
            ]
            out.setdefault(key, []).extend(handles)
        return out


identity_resolver = IdentityResolver()
