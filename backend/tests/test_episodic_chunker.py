"""Chunker épisodique — le découpage des messages en paires d'échange.

Pur (aucune I/O) : ces tests pinnent les règles qui font la qualité de la
recherche — un handle par chunk, fusion bornée, queue non appariée retenue
puis flushée, verbatim jamais coupé en deux.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone

from memory.episodic.chunker import MESSAGE_TEXT_CAP, build_chunks

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=dt_timezone.utc)


def _msg(i, role, content, handle="web_a", conv=1, age_s=3600):
    return {
        "id": i,
        "role": role,
        "content": content,
        "created_at": NOW - timedelta(seconds=age_s),
        "source": "frontend",
        "person_id": handle,
        "conversation_id": conv,
    }


class TestPairing:

    def test_simple_exchange_becomes_one_chunk(self):
        chunks, consumed = build_chunks([
            _msg(1, "user", "salut, ça va ?"),
            _msg(2, "assistant", "coucou ! oui et toi ?"),
        ], now=NOW)
        assert consumed is None
        assert len(chunks) == 1
        c = chunks[0]
        assert c.first_message_id == 1 and c.last_message_id == 2
        assert c.handle == "web_a"
        assert c.text == "Lui: salut, ça va ?\nMika: coucou ! oui et toi ?"
        assert c.chunk_id == "1"

    def test_double_text_same_handle_is_one_pair(self):
        chunks, _ = build_chunks([
            _msg(1, "user", "attends"),
            _msg(2, "user", "en fait j'ai une question"),
            _msg(3, "assistant", "vas-y !"),
        ], now=NOW)
        assert len(chunks) == 1
        assert chunks[0].text.count("Lui:") == 2
        assert chunks[0].last_message_id == 3

    def test_handle_switch_closes_the_pair(self):
        """A/B/A → trois chunks, jamais un chunk mixte."""
        chunks, _ = build_chunks([
            _msg(1, "user", "question de A", handle="web_a"),
            _msg(2, "user", "question de B", handle="web_b"),
            _msg(3, "user", "re-question de A", handle="web_a", age_s=7200),
        ], now=NOW)
        assert [c.handle for c in chunks] == ["web_a", "web_b", "web_a"]

    def test_mika_initiative_gets_internal_handle_blanked(self):
        chunks, _ = build_chunks([
            _msg(1, "assistant", "tiens, je pensais à un truc", handle="conscience_mika"),
        ], now=NOW)
        assert len(chunks) == 1
        assert chunks[0].handle == ""
        assert chunks[0].text.startswith("Mika:")

    def test_mika_greeting_to_a_real_person_keeps_the_handle(self):
        chunks, _ = build_chunks([
            _msg(1, "assistant", "re-coucou toi !", handle="web_a"),
        ], now=NOW)
        assert chunks[0].handle == "web_a"

    def test_alien_roles_and_empty_contents_are_skipped(self):
        chunks, _ = build_chunks([
            _msg(1, "system", "config"),
            _msg(2, "user", "   "),
        ], now=NOW)
        assert chunks == []


class TestTailRule:

    def test_fresh_unanswered_question_is_held_back(self):
        """Le checkpoint recule devant elle : la paire s'indexera entière."""
        chunks, consumed = build_chunks([
            _msg(1, "user", "q1"),
            _msg(2, "assistant", "r1"),
            _msg(5, "user", "et sinon ?", age_s=30),
        ], now=NOW)
        assert len(chunks) == 1
        assert consumed == 4

    def test_stale_unanswered_question_is_flushed_alone(self):
        chunks, consumed = build_chunks([
            _msg(5, "user", "tu es là ?", age_s=3600),
        ], now=NOW, flush_age_s=600)
        assert consumed is None
        assert len(chunks) == 1
        assert chunks[0].text == "Lui: tu es là ?"


class TestMerging:

    def test_consecutive_pairs_same_handle_merge_up_to_max_chars(self):
        chunks, _ = build_chunks([
            _msg(1, "user", "a"), _msg(2, "assistant", "b"),
            _msg(3, "user", "c"), _msg(4, "assistant", "d"),
        ], now=NOW, max_chars=600)
        assert len(chunks) == 1
        assert chunks[0].first_message_id == 1
        assert chunks[0].last_message_id == 4

    def test_merge_stops_at_max_chars(self):
        long = "x" * 300
        chunks, _ = build_chunks([
            _msg(1, "user", long), _msg(2, "assistant", long),
            _msg(3, "user", long), _msg(4, "assistant", long),
        ], now=NOW, max_chars=600)
        assert len(chunks) == 2

    def test_merge_never_crosses_conversations(self):
        chunks, _ = build_chunks([
            _msg(1, "user", "a", conv=1), _msg(2, "assistant", "b", conv=1),
            _msg(3, "user", "c", conv=2), _msg(4, "assistant", "d", conv=2),
        ], now=NOW)
        assert len(chunks) == 2

    def test_oversized_pair_is_never_split_but_messages_are_capped(self):
        bomb = "y" * (MESSAGE_TEXT_CAP * 2)
        chunks, _ = build_chunks([
            _msg(1, "user", bomb),
            _msg(2, "assistant", "ok"),
        ], now=NOW, max_chars=600)
        assert len(chunks) == 1
        assert "…[tronqué]" in chunks[0].text
        assert len(chunks[0].text) < MESSAGE_TEXT_CAP + 100

    def test_ts_is_the_first_message_epoch(self):
        chunks, _ = build_chunks([
            _msg(1, "user", "a", age_s=100),
            _msg(2, "assistant", "b", age_s=90),
        ], now=NOW)
        assert chunks[0].ts == (NOW - timedelta(seconds=100)).timestamp()
