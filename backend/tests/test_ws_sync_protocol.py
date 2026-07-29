"""The WebSocket synchronisation protocol — history, catch-up, ack, keepalive.

What this exists to prevent, concretely: a reply is broadcast with
``group_send``, which drops silently when the group has no member. The
browser painted its own bubble before sending and kept its thread in
``localStorage``, so a tab that was disconnected for any reason — a server
restart, a timeout, a sleeping laptop — showed the user's message and never
the answer, permanently, while the database held both. Every test below
pins one link of the chain that closes that hole.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest


def _make_consumer(person_id: str = "web_sync"):
    from communication.channels.web_frontend import WebSocketConsumer

    c = WebSocketConsumer.__new__(WebSocketConsumer)
    c.person_id = person_id
    c.display_name = None
    c._greeted = True          # not what these tests are about
    c.authenticated = False
    c._group = f"vtuber_person_{person_id}"
    c.channel_name = "test_ch"
    c.channel_layer = AsyncMock()
    c._msg_timestamps = []
    c.send = AsyncMock()
    return c


def _frames(consumer, frame_type: str) -> list[dict]:
    """Every frame of one type the consumer wrote to the socket."""
    out = []
    for call in consumer.send.await_args_list:
        raw = call.kwargs.get("text_data") or (call.args[0] if call.args else "")
        if not raw:
            continue
        payload = json.loads(raw)
        if payload.get("type") == frame_type:
            out.append(payload)
    return out


@contextmanager
def _submits():
    """Capture what the consumer hands the turn pool, without running it.

    The consumer's job stops at submitting: it no longer awaits the
    pipeline, so a test that patched ``perceive`` would be asserting on a
    collaborator the consumer never calls.
    """
    from communication.channels import web_frontend

    seen: list = []
    with patch.object(
        web_frontend.turn_queue, "submit",
        side_effect=lambda p: (seen.append(p), True)[1],
    ):
        yield seen


async def _make_message(person_id: str, role: str, content: str, *, internal=False):
    from memory.models import Conversation, Message

    conv = await Conversation.objects.acreate()
    return await Message.objects.acreate(
        conversation=conv, role=role, content=content,
        person_id=person_id, is_internal=internal,
    )


# ── The read layer ───────────────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestHistoryReads:

    async def test_recent_returns_oldest_first(self):
        from communication import history

        for i in range(3):
            await _make_message("p1", "user", f"m{i}")

        rows = await history.recent_for("p1")
        assert [r["text"] for r in rows] == ["m0", "m1", "m2"]

    async def test_internal_scaffolding_never_reaches_the_client(self):
        """The greeting brief and a failed turn's fallback were said by nobody.

        Same rule the model's own rehydrated buffer applies. If the two
        disagreed, the client would display sentences Mika has no memory of
        saying — and, for the fallback, invite her to say them again.
        """
        from communication import history

        await _make_message("p2", "user", "brief interne", internal=True)
        await _make_message("p2", "assistant", "vraie reponse")

        rows = await history.recent_for("p2")
        assert [r["text"] for r in rows] == ["vraie reponse"]

    async def test_a_reply_to_an_internal_trigger_is_kept(self):
        """The flag is a property of the message, not of the side it sits on.

        "Hey ! Bienvenue bienvenue" answers a brief Mika wrote to herself.
        The brief is machinery; the greeting is something she actually said,
        and dropping it would blank the thread on every fresh connection.
        """
        from communication import history

        await _make_message("p3", "user", "Un visiteur vient de se connecter",
                            internal=True)
        await _make_message("p3", "assistant", "Hey ! Bienvenue bienvenue")

        rows = await history.recent_for("p3")
        assert [r["role"] for r in rows] == ["assistant"]

    async def test_history_is_scoped_to_the_person(self):
        from communication import history

        await _make_message("alice", "user", "secret d'alice")
        await _make_message("bob", "user", "bonjour")

        rows = await history.recent_for("bob")
        assert [r["text"] for r in rows] == ["bonjour"]

    async def test_after_returns_only_what_is_newer(self):
        from communication import history

        first = await _make_message("p4", "user", "avant")
        await _make_message("p4", "assistant", "apres")

        rows, truncated = await history.after_for("p4", first.pk)
        assert [r["text"] for r in rows] == ["apres"]
        assert truncated is False

    async def test_after_with_nothing_missed_is_empty(self):
        from communication import history

        last = await _make_message("p5", "user", "seul")
        rows, truncated = await history.after_for("p5", last.pk)
        assert rows == []
        assert truncated is False

    async def test_a_wide_gap_is_capped_and_says_so(self):
        """A silent cap would be the same bug wearing a success mask.

        Dropping the oldest of a gap is fine; letting the client believe it
        received everything would advance its cursor past messages it never
        rendered, and the hole would never be revisited.
        """
        from communication import history

        for i in range(6):
            await _make_message("p6", "user", f"m{i}")

        rows, truncated = await history.after_for("p6", 0, limit=4)
        assert truncated is True
        assert len(rows) == 4
        # The tail is kept — that is what the user is looking at.
        assert [r["text"] for r in rows] == ["m2", "m3", "m4", "m5"]

    async def test_unknown_person_is_empty_not_an_error(self):
        from communication import history

        assert await history.recent_for("jamais_vu") == []
        assert await history.after_for("", 0) == ([], False)


# ── The consumer's frames ────────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestConsumerFrames:

    async def test_sync_answers_with_the_diff(self):
        c = _make_consumer("web_diff")
        first = await _make_message("web_diff", "user", "vu")
        await _make_message("web_diff", "assistant", "manque")

        await c.receive(text_data=json.dumps({
            "type": "sync", "after_id": first.pk,
        }))

        [frame] = _frames(c, "history")
        assert frame["mode"] == "catchup"
        assert [m["text"] for m in frame["messages"]] == ["manque"]

    async def test_sync_without_a_cursor_falls_back_to_the_window(self):
        """A client with no trustworthy cursor asks for the tail, not a diff.

        `after_id: 0` is the honest answer after a cleared cache or a first
        visit; treating it as "everything since row zero" would ship the
        whole table.
        """
        c = _make_consumer("web_fresh")
        await _make_message("web_fresh", "user", "coucou")

        await c.receive(text_data=json.dumps({"type": "sync", "after_id": 0}))

        [frame] = _frames(c, "history")
        assert [m["text"] for m in frame["messages"]] == ["coucou"]

    async def test_a_garbage_cursor_is_treated_as_no_cursor(self):
        c = _make_consumer("web_junk")
        await _make_message("web_junk", "user", "salut")

        await c.receive(text_data=json.dumps({
            "type": "sync", "after_id": "not-a-number",
        }))

        [frame] = _frames(c, "history")
        assert [m["text"] for m in frame["messages"]] == ["salut"]

    async def test_last_id_is_the_cursor_the_client_should_keep(self):
        c = _make_consumer("web_cursor")
        await _make_message("web_cursor", "user", "un")
        last = await _make_message("web_cursor", "assistant", "deux")

        await c.receive(text_data=json.dumps({"type": "sync", "after_id": 0}))

        [frame] = _frames(c, "history")
        assert frame["last_id"] == last.pk

    async def test_an_empty_catchup_preserves_the_cursor(self):
        """Nothing missed must not reset the client to zero.

        With `last_id` back at 0 the next reconnect would re-request the
        whole window and re-render a thread the user is already reading.
        """
        c = _make_consumer("web_uptodate")
        last = await _make_message("web_uptodate", "user", "a jour")

        await c.receive(text_data=json.dumps({
            "type": "sync", "after_id": last.pk,
        }))

        [frame] = _frames(c, "history")
        assert frame["messages"] == []
        assert frame["last_id"] == last.pk


@pytest.mark.asyncio
class TestAckAndKeepalive:

    async def test_ping_is_answered(self):
        """The browser cannot see protocol-level pongs, so this is the only
        proof of life it can get — and the only thing that distinguishes a
        live socket from one that reads OPEN and swallows everything."""
        c = _make_consumer()
        await c.receive(text_data=json.dumps({"type": "ping", "t": 42}))

        [pong] = _frames(c, "pong")
        assert pong["t"] == 42

    async def test_the_socket_answers_a_ping_while_a_turn_is_running(self):
        """The property the whole detachment exists for.

        Channels dispatches a consumer's frames one at a time, so awaiting
        the pipeline in ``receive`` made the connection deaf for the entire
        turn — up to ``ai.call_timeout_seconds``. A client with a liveness
        watchdog then concluded the socket was dead in the middle of every
        slow turn, which is the opposite of what a keepalive is for.
        """
        from pipeline.turns import turn_queue

        release = asyncio.Event()

        async def slow(_p):
            await release.wait()

        c = _make_consumer()
        await turn_queue.start(workers=1)
        try:
            with patch("pipeline.router.perceive", new=slow):
                await c.receive(text_data=json.dumps({
                    "type": "chat", "message": "coucou", "client_msg_id": "c0",
                }))
                # The turn is in flight; the socket must still answer.
                await asyncio.sleep(0)
                await c.receive(text_data=json.dumps({"type": "ping", "t": 7}))
                assert [f["t"] for f in _frames(c, "pong")] == [7]
                release.set()
                await asyncio.wait_for(turn_queue.drain(), timeout=5)
        finally:
            await turn_queue.stop()

    async def test_a_chat_is_acknowledged_before_it_is_answered(self):
        """"The server has it" and "she answered" are different facts."""
        c = _make_consumer()
        with _submits() as seen:
            await c.receive(text_data=json.dumps({
                "type": "chat", "message": "coucou", "client_msg_id": "c1",
            }))

        assert len(seen) == 1
        [ack] = _frames(c, "ack")
        assert ack == {"type": "ack", "client_msg_id": "c1", "status": "accepted"}

    async def test_the_ack_reports_the_submission_rather_than_predicting_it(self):
        """One ack, emitted once the pool has actually taken the turn.

        The ack used to be sent first, on the reasoning that a turn can take
        a minute and the bubble must not stay indistinguishable from one
        sitting in the outbox. True — but ``submit`` does not take a minute,
        it never blocks, so nothing is gained by answering before it and
        something is lost: a refused turn got "accepted" immediately
        followed by "overloaded" for the same id. The property that mattered
        is the one asserted above — the ack precedes the *answer*, which it
        still does, because ``receive`` returns before the worker runs.
        """
        from communication.channels import web_frontend

        order: list[str] = []
        c = _make_consumer()
        original = c.send

        async def recording_send(*args, **kwargs):
            raw = kwargs.get("text_data") or (args[0] if args else "")
            if raw and json.loads(raw).get("type") == "ack":
                order.append("ack")
            return await original(*args, **kwargs)

        c.send = recording_send
        with patch.object(web_frontend.turn_queue, "submit",
                          side_effect=lambda _p: order.append("submit") or True):
            await c.receive(text_data=json.dumps({
                "type": "chat", "message": "hello", "client_msg_id": "c2",
            }))

        assert order == ["submit", "ack"]

    async def test_a_rate_limited_message_is_refused_out_loud(self):
        """Silently dropping it leaves a bubble that looks delivered forever."""
        from communication.channels import web_frontend

        c = _make_consumer()
        c._msg_timestamps = []
        with _submits() as seen:
            for i in range(web_frontend.RATE_LIMIT_MAX_MESSAGES + 1):
                await c.receive(text_data=json.dumps({
                    "type": "chat", "message": "spam", "client_msg_id": f"c{i}",
                }))

        statuses = [a["status"] for a in _frames(c, "ack")]
        assert "rate_limited" in statuses
        # The refused one never reached the queue.
        assert len(seen) == len(statuses) - 1

    async def test_a_full_queue_is_reported_to_the_sender(self):
        """A backlog that cannot take the turn must not read as accepted."""
        from communication.channels import web_frontend

        c = _make_consumer()
        with patch.object(web_frontend.turn_queue, "submit", return_value=False):
            await c.receive(text_data=json.dumps({
                "type": "chat", "message": "coucou", "client_msg_id": "c3",
            }))

        # Exactly one, and it is the refusal. Two acks for one message — the
        # optimistic "accepted" followed by the truth — made the first one a
        # claim the server had not earned.
        assert [a["status"] for a in _frames(c, "ack")] == ["overloaded"]

    async def test_an_unlabelled_message_gets_no_ack(self):
        """An ack with nothing to match against is noise on the wire."""
        c = _make_consumer()
        with _submits():
            await c.receive(text_data=json.dumps({
                "type": "chat", "message": "coucou",
            }))
        assert _frames(c, "ack") == []

    async def test_the_client_id_travels_to_the_perception(self):
        """Without it the reply cannot be matched to the bubble that caused it,
        and a history merge paints the message a second time."""
        c = _make_consumer()
        with _submits() as seen:
            await c.receive(text_data=json.dumps({
                "type": "chat", "message": "coucou", "client_msg_id": "c9",
            }))

        assert seen[0].metadata["client_msg_id"] == "c9"

    async def test_an_oversized_client_id_is_bounded(self):
        from communication.channels import web_frontend

        c = _make_consumer()
        with _submits() as seen:
            await c.receive(text_data=json.dumps({
                "type": "chat", "message": "coucou", "client_msg_id": "x" * 500,
            }))

        assert (
            len(seen[0].metadata["client_msg_id"])
            == web_frontend.MAX_CLIENT_MSG_ID_LENGTH
        )


# ── The ids the client synchronises on ───────────────────────────────


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestPersistenceCursors:

    async def test_persist_returns_both_row_ids(self):
        """The cursor has to come from the write itself.

        Re-querying afterwards would race the six background loops writing
        to the same table and could hand back somebody else's row.
        """
        from memory.manager import memory_manager
        from memory.models import Conversation, Message
        from pipeline.broadcast import persist_to_memory

        memory_manager.conversation = await Conversation.objects.acreate()
        memory_manager._initialized = True
        try:
            user_id, assistant_id = await persist_to_memory(
                message="question", response="reponse",
                source="frontend", person_id="web_ids",
            )
        finally:
            memory_manager._initialized = False
            memory_manager.conversation = None

        assert user_id is not None and assistant_id is not None
        assert assistant_id > user_id
        assert await Message.objects.filter(pk=assistant_id).aexists()

    async def test_no_conversation_yields_no_ids_rather_than_fake_ones(self):
        """A message the server did not record must not advance the cursor."""
        from memory.manager import memory_manager
        from pipeline.broadcast import persist_to_memory

        memory_manager._initialized = False
        memory_manager.conversation = None

        assert await persist_to_memory(
            message="q", response="r", source="frontend", person_id="web_none",
        ) == (None, None)


@pytest.mark.asyncio
class TestSpeechCarriesTheCursors:

    async def test_the_broadcast_payload_exposes_the_ids(self):
        """Without them on the live frame the cursor would only advance at
        the next reconnect, so every reconnect would re-request the whole
        window instead of a small diff."""
        from communication.presence import person_group, presence_registry
        from pipeline import broadcast
        from pipeline.processor import SpeechOutput
        from emotion.types import Emotion, EmotionData

        sent: list = []

        class FakeLayer:
            async def group_send(self, group, payload):
                sent.append((group, payload))

        output = SpeechOutput(
            text="voila", emotion_data=EmotionData(emotion=Emotion.NEUTRAL,
                                                   intensity=0.0),
            emotion_name="neutral", emotion_intensity=0.0, emotion_state={},
            tool_calls=[], message_id=77, user_message_id=76,
            client_msg_id="c-abc",
        )

        presence_registry.register(
            person_id="web_x", channel="web", kind="consumer",
            delivery_ref=person_group("web_x"),
        )
        try:
            with patch.object(broadcast, "get_channel_layer",
                              return_value=FakeLayer()), \
                 patch.object(broadcast, "_collect_inner_state",
                              new=AsyncMock(return_value={})):
                await broadcast.broadcast_to_websocket(output, "frontend",
                                                       person_id="web_x")
        finally:
            presence_registry.unregister("web_x", "web")

        [(_group, payload)] = sent
        data = payload["data"]
        assert data["message_id"] == 77
        assert data["user_message_id"] == 76
        assert data["client_msg_id"] == "c-abc"
