"""APIs de rappel épisodique — résolution par identité, deux temps verbatim."""

from __future__ import annotations

import pytest

from identity.models import Identity, IdentityHandle
from memory.episodic import api
from memory.episodic.api import ExchangeHit
from memory.models import Conversation, Entity, Message

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _clean_tables():
    Message.objects.all().delete()
    Conversation.objects.all().delete()
    IdentityHandle.objects.all().delete()
    Identity.objects.all().delete()
    Entity.objects.filter(name="Thomas").delete()
    yield


async def _bound_identity():
    entity = await Entity.objects.acreate(name="Thomas", entity_type="person")
    identity = await Identity.objects.acreate(display_name="Thomas", entity=entity)
    await IdentityHandle.objects.acreate(
        identity=identity, channel="web", person_id="web_abc",
    )
    await IdentityHandle.objects.acreate(
        identity=identity, channel="telegram", person_id="tg_42",
    )
    return identity


class TestResolvePersonHandles:

    async def test_entity_name_resolves_to_every_handle(self):
        await _bound_identity()
        handles = await api.resolve_person_handles("Thomas")
        assert handles == ["tg_42", "web_abc"]

    async def test_raw_handle_widens_to_the_whole_identity(self):
        """Une question posée sur Telegram retrouve les échanges web."""
        await _bound_identity()
        handles = await api.resolve_person_handles("tg_42")
        assert handles == ["tg_42", "web_abc"]

    async def test_unbound_visitor_falls_back_to_the_literal(self):
        handles = await api.resolve_person_handles("web_inconnu")
        assert handles == ["web_inconnu"]


class _FakeStore:
    def __init__(self, pages):
        self.pages = pages
        self.calls: list[dict] = []

    def search_exchanges(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        return self.pages.pop(0) if self.pages else []


def _raw(chunk_id, distance, handle="web_abc", content="Lui: x\nMika: y"):
    return {
        "id": chunk_id,
        "content": content,
        "distance": distance,
        "metadata": {
            "conversation_id": 1,
            "first_message_id": int(chunk_id),
            "last_message_id": int(chunk_id) + 1,
            "handle": handle,
            "ts": 1000.0,
        },
    }


class TestSearchExchanges:

    async def test_hits_are_parsed_and_sorted(self, monkeypatch):
        store = _FakeStore([[_raw("10", 0.4), _raw("20", 0.1)]])
        monkeypatch.setattr(api, "_store", lambda: store)
        hits = await api.search_exchanges("le projet", handles=["web_abc"], n=5)
        assert [h.chunk_id for h in hits] == ["20", "10"]
        assert store.calls[0]["handles"] == ["web_abc"]

    async def test_proper_noun_pass_merges_with_a_bonus(self, monkeypatch):
        store = _FakeStore([
            [_raw("10", 0.40)],           # passe vectorielle
            [_raw("10", 0.40)],           # passe contains → bonus
        ])
        monkeypatch.setattr(api, "_store", lambda: store)
        hits = await api.search_exchanges("le chat", proper_nouns=["Félix"])
        assert store.calls[1]["contains"] == "Félix"
        assert hits[0].distance == pytest.approx(0.35)

    async def test_no_store_yields_empty(self, monkeypatch):
        monkeypatch.setattr(api, "_store", lambda: None)
        assert await api.search_exchanges("x") == []


class TestVerbatim:

    async def test_fetch_verbatim_returns_neighbors_excluding_machinery(self):
        conv = await Conversation.objects.acreate()
        rows = []
        for i, (role, content, internal) in enumerate([
            ("user", "avant-2", False),
            ("user", "brief interne", True),
            ("user", "avant-1", False),
            ("user", "ancre", False),
            ("assistant", "après-1", False),
            ("user", "après-2", False),
        ]):
            rows.append(await Message.objects.acreate(
                conversation=conv, role=role, content=content,
                is_internal=internal, person_id="web_abc",
            ))
        out = await api.fetch_verbatim(rows[3].pk, radius=2)
        assert out["conversation_id"] == conv.pk
        contents = [m["content"] for m in out["messages"]]
        assert contents == ["avant-2", "avant-1", "ancre", "après-1", "après-2"]

    async def test_missing_anchor_is_empty_not_an_error(self):
        out = await api.fetch_verbatim(999_999)
        assert out == {"conversation_id": None, "messages": []}

    async def test_expand_hit_returns_the_chunk_range_plus_radius(self):
        conv = await Conversation.objects.acreate()
        rows = []
        for content in ["a", "b", "c", "d"]:
            rows.append(await Message.objects.acreate(
                conversation=conv, role="user", content=content,
                person_id="web_abc",
            ))
        hit = ExchangeHit(
            chunk_id=str(rows[1].pk), content="", handle="web_abc",
            conversation_id=conv.pk,
            first_message_id=rows[1].pk, last_message_id=rows[2].pk,
            ts=0.0, distance=0.2,
        )
        out = await api.expand_hit(hit, radius=1)
        assert [m["content"] for m in out["messages"]] == ["a", "b", "c", "d"]
