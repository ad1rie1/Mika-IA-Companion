"""Intégration conscience ↔ étage épisodique.

- `recall_for_context` interroge la mémoire en multi-requêtes (fini la
  concaténation « q1 q2 q3 » dont l'embedding moyen ne ressemblait à rien).
- `who_is_concerned` gagne l'évidence épisodique : un échange récent sur le
  sujet désigne son auteur, via la couche identité, jamais par nom.
- Les entités de l'interprétation sont persistées dans raw_data.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from conscience.memory_bridge import MemoryBridge
from memory.episodic.api import ExchangeHit


class TestRecallMultiQuery:

    async def test_each_summary_is_its_own_query(self):
        bridge = MemoryBridge()
        with patch("memory.manager.memory_manager.get_memory_context_multi",
                   AsyncMock(return_value="bloc")) as mock:
            out = await bridge.recall_for_context(["q1", "q2", "q3", "q4"])
        assert out == "bloc"
        assert mock.call_args.args[0] == ["q1", "q2", "q3"]

    async def test_empty_queries_short_circuit(self):
        bridge = MemoryBridge()
        assert await bridge.recall_for_context([]) == ""


class TestExchangeEvidence:

    def _hit(self, handle, distance=0.2):
        return ExchangeHit("1", "Lui: x", handle, 1, 1, 2, 0.0, distance)

    async def test_recent_exchange_designates_its_author(self):
        bridge = MemoryBridge()
        entity = type("E", (), {"name": "Thomas"})()
        scores: dict = {}
        with patch("memory.episodic.api.search_exchanges",
                   AsyncMock(return_value=[self._hit("web_abc")])), \
             patch("identity.resolver.identity_resolver.entity_for_person",
                   AsyncMock(return_value=entity)):
            await bridge._merge_exchange_evidence("le projet fusée", scores, 5)
        assert scores["Thomas"] == pytest.approx(0.8 * 1.2)

    async def test_unbound_or_internal_handles_contribute_nothing(self):
        bridge = MemoryBridge()
        scores: dict = {}
        hits = [self._hit(""), self._hit("conscience_mika"), self._hit("web_x")]
        with patch("memory.episodic.api.search_exchanges",
                   AsyncMock(return_value=hits)), \
             patch("identity.resolver.identity_resolver.entity_for_person",
                   AsyncMock(return_value=None)):
            await bridge._merge_exchange_evidence("sujet", scores, 5)
        assert scores == {}

    async def test_episodic_failure_never_breaks_the_routing(self):
        bridge = MemoryBridge()
        scores = {"Alice": 0.5}
        with patch("memory.episodic.api.search_exchanges",
                   AsyncMock(side_effect=RuntimeError("chroma down"))):
            await bridge._merge_exchange_evidence("sujet", scores, 5)
        assert scores == {"Alice": 0.5}


@pytest.mark.django_db
class TestObservationEntities:

    async def test_interpreted_entities_land_in_raw_data(self):
        from conscience.engine import ConscienceEngine
        from conscience.types import InterpretedSignal
        from modules.types import ModuleEvent

        engine = ConscienceEngine.__new__(ConscienceEngine)
        signal = InterpretedSignal(
            summary="Thomas parle du chat",
            category="communication",
            pertinence=0.6,
            emotional_reaction="curious",
            emotional_intensity=0.3,
            themes=["animaux"],
            entities=["Thomas", "Félix"],
        )
        event = ModuleEvent(event_type="chat.message", source_module="web", data={})
        obs = await engine._store_observation(event, signal)
        assert obs.raw_data["entities"] == ["Thomas", "Félix"]
        assert obs.raw_data["themes"] == ["animaux"]
