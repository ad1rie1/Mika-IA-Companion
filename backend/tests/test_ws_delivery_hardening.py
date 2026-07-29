"""What a live socket is owed — presence, greeting, refusals, replay.

Every test here pins a way the round trip could stay *silently* broken:
the socket is open, the client believes it is connected, and nothing ever
comes back. That failure mode has no error anywhere, which is why each of
these is worth a test rather than a comment.

Grouped by the bug they close:

- ``TestPresenceIsPerConnection`` — the registry is keyed by *person*, so a
  second tab shared one entry with the first and the first tab's disconnect
  erased it. ``broadcast_to_websocket`` then resolved nothing and stayed
  silent by design, so the surviving tab never received another word.
- ``TestGreetingIsPerPerson`` — ``_greeted`` only knew about one socket, and
  sockets are cheap.
- ``TestRefusalsAreSpokenOnce`` — a refused message must say why, exactly
  once.
- ``TestReplayedTurnIsNotRewritten`` — a turn resumed after a restart already
  has its question in the database.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from communication.presence import presence_registry

from .test_ws_sync_protocol import _frames, _make_consumer, _submits


def _consumer(person_id: str, channel_name: str):
    c = _make_consumer(person_id)
    c.channel_name = channel_name
    return c


# ── Presence ─────────────────────────────────────────────────────────


class TestPresenceIsPerConnection:

    def teardown_method(self):
        presence_registry.unregister("web_two_tabs", "web")

    def test_a_second_connection_does_not_replace_the_first(self):
        presence_registry.register(
            "web_two_tabs", "web", "consumer", "grp", connection_id="ch1",
        )
        entry = presence_registry.register(
            "web_two_tabs", "web", "consumer", "grp", connection_id="ch2",
        )
        assert entry.connections == {"ch1", "ch2"}

    def test_closing_one_tab_leaves_the_other_reachable(self):
        """The whole point. One entry, two sockets, one goes away.

        Before, the survivor stayed connected and in its group while the
        registry forgot it existed — and a person who resolves to nothing is
        deliberately *not* broadcast to, so the reply was dropped rather than
        misdelivered. Silent, and lasting until the page was reloaded.
        """
        presence_registry.register(
            "web_two_tabs", "web", "consumer", "grp", connection_id="ch1",
        )
        presence_registry.register(
            "web_two_tabs", "web", "consumer", "grp", connection_id="ch2",
        )
        presence_registry.unregister("web_two_tabs", "web", connection_id="ch1")

        assert presence_registry.resolve("web_two_tabs") != []

        presence_registry.unregister("web_two_tabs", "web", connection_id="ch2")
        assert presence_registry.resolve("web_two_tabs") == []

    def test_a_late_disconnect_cannot_erase_its_replacement(self):
        """The single-tab version of the same race.

        ``reconnectNow()`` opens the replacement socket before the dying
        one's ``disconnect`` is dispatched, so the stale unregister arrived
        *after* the new registration.
        """
        presence_registry.register(
            "web_two_tabs", "web", "consumer", "grp", connection_id="old",
        )
        presence_registry.register(
            "web_two_tabs", "web", "consumer", "grp", connection_id="new",
        )
        presence_registry.unregister("web_two_tabs", "web", connection_id="old")
        assert presence_registry.resolve("web_two_tabs") != []

    def test_an_unscoped_unregister_still_evicts(self):
        """Modules and tests hold no connection id — their call must still work."""
        presence_registry.register("web_two_tabs", "web", "consumer", "grp")
        presence_registry.unregister("web_two_tabs", "web")
        assert presence_registry.resolve("web_two_tabs") == []


@pytest.mark.asyncio
class TestConsumerDisconnectIsScoped:

    async def test_one_consumer_leaving_keeps_the_person_deliverable(self):
        pid = "web_scoped_disconnect"
        a = _consumer(pid, "ch_a")
        b = _consumer(pid, "ch_b")
        for c in (a, b):
            presence_registry.register(
                pid, "web", "consumer", c._group, connection_id=c.channel_name,
            )
        try:
            await a.disconnect(1000)
            assert presence_registry.resolve_on(pid, "web") is not None
            await b.disconnect(1000)
            assert presence_registry.resolve_on(pid, "web") is None
        finally:
            presence_registry.unregister(pid, "web")

    async def test_the_emotion_memo_survives_while_a_tab_remains(self):
        """Forgetting resyncs a reconnecting client; here nobody reconnected.

        Dropping the memo while another tab is still listening just buys it a
        redundant frame carrying a mood it is already displaying.
        """
        from emotion.sync import emotion_sync

        pid = "web_scoped_memo"
        emotion_sync._last_sent[pid] = ("neutral", 0.0, ())
        a = _consumer(pid, "ch_a")
        b = _consumer(pid, "ch_b")
        for c in (a, b):
            presence_registry.register(
                pid, "web", "consumer", c._group, connection_id=c.channel_name,
            )
        try:
            await a.disconnect(1000)
            assert pid in emotion_sync._last_sent
            await b.disconnect(1000)
            assert pid not in emotion_sync._last_sent
        finally:
            presence_registry.unregister(pid, "web")
            emotion_sync.forget(pid)


# ── Greeting ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestGreetingIsPerPerson:

    def setup_method(self):
        from communication.channels import web_frontend

        web_frontend._last_greeted.clear()

    def teardown_method(self):
        from communication.channels import web_frontend

        web_frontend._last_greeted.clear()

    async def test_a_reconnect_does_not_greet_again(self):
        """A socket is not an arrival.

        Each reconnect — a laptop waking, a proxy reaping an idle
        connection, the client's own watchdog — used to spend a full LLM
        turn on another hello, persist it, and hold the single turn worker
        while a real question queued behind it.
        """
        pid = "web_greeted_once"
        first = _consumer(pid, "ch1")
        first._greeted = False
        second = _consumer(pid, "ch2")
        second._greeted = False

        with _submits() as seen:
            first._schedule_greeting()
            second._schedule_greeting()

        assert len(seen) == 1
        # The second connection still considers the matter settled, so its
        # first chat turn does not try again either.
        assert second._greeted is True

    async def test_the_greeting_memo_does_not_grow_forever(self):
        """One `web_*` id per browser, for the life of the process.

        An entry older than the cooldown answers nothing — the next greeting
        is allowed either way — so it is only ballast.
        """
        import time as _time

        from communication.channels import web_frontend

        now = _time.monotonic()
        stale = now - web_frontend.GREETING_COOLDOWN_SECONDS - 1
        for i in range(web_frontend._GREETED_MAX_TRACKED + 10):
            web_frontend._last_greeted[f"web_old_{i}"] = stale
        web_frontend._last_greeted["web_recent"] = now

        web_frontend._prune_greeted(now)

        assert web_frontend._last_greeted == {"web_recent": now}

    async def test_a_refused_greeting_does_not_burn_the_flag(self):
        """A full backlog must not cost the person their greeting."""
        from communication.channels import web_frontend

        c = _consumer("web_greet_refused", "ch1")
        c._greeted = False
        with patch.object(web_frontend.turn_queue, "submit", return_value=False):
            c._schedule_greeting()
        assert c._greeted is False

        with _submits() as seen:
            c._schedule_greeting()
        assert len(seen) == 1


# ── Refusals ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRefusalsAreSpokenOnce:

    async def test_rejected_attachments_do_not_become_an_empty_turn(self):
        """The empty-message guard tested the raw list, not the valid one.

        Three oversized files with no caption passed it, came back as zero
        valid attachments, and sent ``User: `` into the pipeline — while the
        sender had been told "accepted" and never learned their files were
        dropped.
        """
        c = _make_consumer()
        oversize = {"name": "huge.png", "type": "image/png", "data": "A" * 8_000_000}
        with _submits() as seen:
            await c.receive(text_data=json.dumps({
                "type": "chat", "message": "  ", "attachments": [oversize],
                "client_msg_id": "c1",
            }))

        assert seen == []
        assert [a["status"] for a in _frames(c, "ack")] == ["attachments_rejected"]

    async def test_a_caption_survives_its_rejected_attachments(self):
        """Only the *empty* case is refused: the words were still said."""
        c = _make_consumer()
        oversize = {"name": "huge.png", "type": "image/png", "data": "A" * 8_000_000}
        with _submits() as seen:
            await c.receive(text_data=json.dumps({
                "type": "chat", "message": "regarde ça", "attachments": [oversize],
                "client_msg_id": "c1",
            }))

        assert len(seen) == 1
        assert seen[0].text == "regarde ça"
        assert [a["status"] for a in _frames(c, "ack")] == ["accepted"]

    async def test_an_over_long_message_is_refused_not_silently_cut(self):
        """Truncating left two different sentences, one marked delivered.

        The browser kept showing what it painted; the server held a shorter
        version. Nothing ever reconciled them.
        """
        from communication.channels import web_frontend

        c = _make_consumer()
        with _submits() as seen:
            await c.receive(text_data=json.dumps({
                "type": "chat",
                "message": "x" * (web_frontend.MAX_MESSAGE_LENGTH + 1),
                "client_msg_id": "c1",
            }))

        assert seen == []
        assert [a["status"] for a in _frames(c, "ack")] == ["too_long"]

    async def test_control_frames_are_rate_limited_too(self):
        """A catch-up runs a query; an identify re-persists a handle.

        Only ``chat`` was capped, which amounted to charging for the frames
        that contain words.
        """
        from communication.channels import web_frontend

        c = _make_consumer()
        c._control_timestamps = []
        with patch.object(
            c, "_send_history", new=AsyncMock(),
        ) as history:
            for _ in range(web_frontend.RATE_LIMIT_MAX_CONTROL + 5):
                await c.receive(text_data=json.dumps({
                    "type": "sync", "after_id": 0,
                }))

        assert history.await_count == web_frontend.RATE_LIMIT_MAX_CONTROL

    async def test_a_chat_is_not_starved_by_the_control_budget(self):
        """The two windows are separate: syncing must not cost you a turn."""
        from communication.channels import web_frontend

        c = _make_consumer()
        c._control_timestamps = []
        c._msg_timestamps = []
        with patch.object(c, "_send_history", new=AsyncMock()):
            for _ in range(web_frontend.RATE_LIMIT_MAX_CONTROL + 5):
                await c.receive(text_data=json.dumps({"type": "sync"}))

        with _submits() as seen:
            await c.receive(text_data=json.dumps({
                "type": "chat", "message": "coucou", "client_msg_id": "c1",
            }))
        assert len(seen) == 1


# ── Replay ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestReplayedTurnIsNotRewritten:

    async def test_a_resumed_turn_reuses_its_existing_question_row(self):
        """It was found *by* that row — writing it again duplicates it.

        Duplicated on the person's fiche, duplicated for the consolidator,
        and duplicated on screen: the merge only adopts bubbles with no id
        yet, and the original already had one.
        """
        from configs.service import config_service
        from pipeline import processor
        from pipeline.perception import Perception

        from .test_pipeline_error import _fake_context

        perception = Perception.from_text(
            "et le deuxième alors ?",
            source="frontend",
            person_id="web_resumed",
            metadata={"resumed": True, "original_message_id": 77},
        )

        with patch.object(config_service, "get", return_value=60), \
             patch.object(processor, "gather_context",
                          new=AsyncMock(return_value=_fake_context())), \
             patch.object(processor, "call_ai_and_parse",
                          new=AsyncMock(return_value=("voilà", _neutral(), []))), \
             patch.object(processor.emotion_engine, "ensure_person_loaded",
                          new=AsyncMock()), \
             patch.object(processor.identity_resolver, "ingest_message",
                          new=AsyncMock()), \
             patch.object(processor, "persist_user_message",
                          new=AsyncMock(return_value=1)) as persist_q, \
             patch.object(processor, "persist_assistant_message",
                          new=AsyncMock(return_value=2)) as persist_a, \
             patch.object(processor, "emit_communication_event", new=AsyncMock()), \
             patch.object(processor, "publish_turn_completed", new=AsyncMock()), \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            output = await processor.process_message(perception)

        persist_q.assert_not_called()
        # The reply still closes the original question, or `awaiting_reply`
        # stays set and the same turn is replayed at every boot.
        assert persist_a.call_args.kwargs["replying_to"] == 77
        assert output.user_message_id == 77

    async def test_an_ordinary_turn_still_writes_its_question(self):
        """The guard keys on the metadata, not on anything ambient."""
        from configs.service import config_service
        from pipeline import processor
        from pipeline.perception import Perception

        from .test_pipeline_error import _fake_context

        perception = Perception.from_text(
            "coucou", source="frontend", person_id="web_fresh",
        )

        with patch.object(config_service, "get", return_value=60), \
             patch.object(processor, "gather_context",
                          new=AsyncMock(return_value=_fake_context())), \
             patch.object(processor, "call_ai_and_parse",
                          new=AsyncMock(return_value=("salut", _neutral(), []))), \
             patch.object(processor.emotion_engine, "ensure_person_loaded",
                          new=AsyncMock()), \
             patch.object(processor.identity_resolver, "ingest_message",
                          new=AsyncMock()), \
             patch.object(processor, "persist_user_message",
                          new=AsyncMock(return_value=9)) as persist_q, \
             patch.object(processor, "persist_assistant_message",
                          new=AsyncMock(return_value=10)), \
             patch.object(processor, "emit_communication_event", new=AsyncMock()), \
             patch.object(processor, "publish_turn_completed", new=AsyncMock()), \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            output = await processor.process_message(perception)

        persist_q.assert_called_once()
        assert output.user_message_id == 9


def _neutral():
    from emotion.types import Emotion, EmotionData

    return EmotionData(emotion=Emotion.NEUTRAL, intensity=0.0)


@pytest.mark.asyncio
class TestEveryConnectionIsHandedItsState:
    """The handover is deferred for an anonymous socket, never skipped.

    ``anon_*`` is a uuid minted at connect, so it can have no history and
    reading its mood would create an oscillator for an id the handshake is
    about to discard. But a claim can be *refused* — a reserved prefix, a
    malformed id — and then the connection stays anonymous, so a deferral
    keyed on "did we rebind?" would hand it nothing at all.
    """

    async def test_a_refused_claim_still_gets_its_thread(self):
        c = _consumer("anon_deadbeef", "ch1")
        c._state_sent = False
        c._control_timestamps = []
        c.authenticated = False
        with patch.object(c, "_send_history", new=AsyncMock()) as history, \
             patch.object(c, "_push_emotion_now", new=AsyncMock()), \
             patch.object(c, "_register_presence", new=AsyncMock()):
            # "user_" is reserved for backend-authenticated identities.
            await c.receive(text_data=json.dumps({
                "type": "identify", "person_id": "user_42",
            }))

        assert c.person_id == "anon_deadbeef"
        history.assert_awaited_once()

    async def test_the_handover_happens_once_per_connection(self):
        c = _consumer("web_known", "ch1")
        c._state_sent = True          # connect already did it
        c._control_timestamps = []
        with patch.object(c, "_send_history", new=AsyncMock()) as history, \
             patch.object(c, "_push_emotion_now", new=AsyncMock()), \
             patch.object(c, "_register_presence", new=AsyncMock()):
            await c.receive(text_data=json.dumps({
                "type": "identify", "person_id": "web_known",
            }))

        history.assert_not_awaited()


# ── What an attachment leaves behind ─────────────────────────────────


class TestAttachmentsSurvivePreprocessing:
    """``attachments_meta`` is the only trace a file leaves in the thread.

    It was always empty. Preprocessing runs in the *router*, before the
    processor is reached, and it does not annotate a part — it replaces it:
    an image Part becomes ``Part(kind="text", content="[image: …]")``. So a
    filter on ``kind != "text"`` matched nothing, every upload persisted an
    empty list, and the history frame shipped ``attachments: []`` — a
    reloaded thread had no idea a file had ever been sent.
    """

    def test_a_preprocessed_image_is_still_reported_as_an_attachment(self):
        from pipeline.perception import Intent, Modality, Part, Perception
        from pipeline.processor import _serialize_attachments_meta

        # Exactly what vision.process() hands back.
        captioned = Part(
            kind="text",
            content="[image: un chat roux dort sur un canapé]",
            metadata={
                "name": "chat.png",
                "original_kind": "image",
                "original_mime_type": "image/png",
                "preprocessor": "vision",
            },
        )
        perception = Perception(
            modality=Modality.MIXED,
            intent=Intent.REQUEST_RESPONSE,
            parts=[Part(kind="text", content="regarde ça"), captioned],
            source="frontend",
            person_id="web_att",
        )

        meta = _serialize_attachments_meta(perception)
        assert len(meta) == 1
        assert meta[0]["kind"] == "image"
        assert meta[0]["mime_type"] == "image/png"
        assert meta[0]["name"] == "chat.png"

    def test_ordinary_text_contributes_nothing(self):
        from pipeline.perception import Perception
        from pipeline.processor import _serialize_attachments_meta

        perception = Perception.from_text(
            "juste des mots", source="frontend", person_id="web_att",
        )
        assert _serialize_attachments_meta(perception) == []

    def test_a_failed_preprocessor_still_counts_as_an_attachment(self):
        """Its placeholder carries the same marker — a file was sent."""
        from pipeline.perception import Modality, Part, Perception
        from pipeline.perception import Intent
        from pipeline.processor import _serialize_attachments_meta

        placeholder = Part(
            kind="text",
            content="[image non disponible]",
            metadata={"original_kind": "image", "error": True},
        )
        perception = Perception(
            modality=Modality.MIXED, intent=Intent.REQUEST_RESPONSE,
            parts=[placeholder], source="frontend", person_id="web_att",
        )
        meta = _serialize_attachments_meta(perception)
        assert [m["kind"] for m in meta] == ["image"]


# ── Who an inner-state refresh is about ──────────────────────────────


@pytest.mark.asyncio
class TestInnerStateStatesItsScope:
    """"Nothing to report" and "not about anyone" arrived identically.

    Sections with nothing to say are omitted from the payload, and the panel
    clears what it is handed nothing for — right for an empty section, wrong
    for an absent scope. So every sleep-phase transition wiped the identity
    block from every open browser until the next reply.
    """

    async def test_a_global_refresh_declares_it_is_about_nobody(self):
        from pipeline.broadcast import _collect_inner_state

        state = await _collect_inner_state(None)
        assert state["person_scope"] is False
        assert "identity" not in state

    async def test_a_throwaway_socket_is_not_a_person_either(self):
        from pipeline.broadcast import _collect_inner_state

        state = await _collect_inner_state("anon_deadbeef")
        assert state["person_scope"] is False

    async def test_a_person_scoped_refresh_goes_to_their_group_only(self):
        """The parameter always existed and the send was always global.

        Unused so far, and pointed straight at the leak
        ``broadcast_to_websocket`` was fixed for: the payload carries that
        person's profile and commitments.
        """
        from unittest.mock import AsyncMock, MagicMock

        from pipeline import broadcast

        layer = MagicMock()
        layer.group_send = AsyncMock()
        with patch.object(broadcast, "get_channel_layer", return_value=layer), \
             patch.object(broadcast, "_collect_inner_state",
                          new=AsyncMock(return_value={"person_scope": True})):
            await broadcast.broadcast_inner_state_update("web_scoped")

        group = layer.group_send.await_args[0][0]
        assert group != broadcast.BROADCAST_GROUP
        assert "web_scoped" in group

    async def test_an_unscoped_refresh_still_reaches_everyone(self):
        from unittest.mock import AsyncMock, MagicMock

        from pipeline import broadcast

        layer = MagicMock()
        layer.group_send = AsyncMock()
        with patch.object(broadcast, "get_channel_layer", return_value=layer), \
             patch.object(broadcast, "_collect_inner_state",
                          new=AsyncMock(return_value={"person_scope": False})):
            await broadcast.broadcast_inner_state_update()

        assert layer.group_send.await_args[0][0] == broadcast.BROADCAST_GROUP
