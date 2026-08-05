"""Live emotion sync — pushing the oscillators to the frontend between turns.

The PAD oscillators advance every second (``emotion.engine._decay_loop``):
the state relaxes toward a home vector that itself drifts with the circadian
phase, ruminations bleed into the global mood, and the impulse from a reply
decays over minutes. **None of that ever reached the browser.** The only
frame carrying an emotion was ``speech``, so the face, the gaze/hand mood and
the emotion readout froze on the last thing Mika said until she said the next
thing — hours, on a quiet afternoon. ``inner_state_update`` did not help: it
carries drives, sleep phase, journal, dream, projects — no emotion at all.

This loop closes that gap, and it is deliberately **not** part of the 1s
physics tick: the oscillator moves continuously but imperceptibly, so pushing
every step would mean a frame per second per client to say nothing. A frame
goes out only when the state actually moved — a different dominant emotion, a
different ambivalence pair, or an intensity change past ``MIN_INTENSITY_DELTA``
— checked every ``emotion.sync_interval`` seconds.

Per person, not global: what a client is shown is ``compute_message_emotion``
for *its own* person_id (60% the mood toward that person, 40% Mika's own),
exactly what a ``speech`` frame carries. Two people connected see two
different faces, the same way they get two different replies.
"""

from __future__ import annotations

import logging

from utils.periodic import PeriodicLoop

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL = 3.0

# Below this, a re-render would show the same rounded percentage and move the
# blend shapes by less than the breathing pulse already does.
MIN_INTENSITY_DELTA = 0.04


class EmotionSync:
    """Watches the oscillators and pushes what changed to each client."""

    def __init__(self) -> None:
        self._loop = PeriodicLoop("emotion sync", self.tick, DEFAULT_INTERVAL)
        # person_id -> last frame sent, as (label, intensity, blend labels).
        self._last_sent: dict[str, tuple[str, float, tuple[str, ...]]] = {}
        # Persons whose mood was hydrated from DB before we first read it.
        self._hydrated: set[str] = set()

    @property
    def is_running(self) -> bool:
        return self._loop.is_running

    async def start(self) -> None:
        interval = DEFAULT_INTERVAL
        try:
            from configs.service import config_service

            interval = float(config_service.get("emotion.sync_interval"))
        except Exception:
            # An unreadable config must not cost the sync: the default
            # cadence is a display refresh rate, not a policy.
            logger.debug("emotion.sync_interval unreadable, using default")
        await self._loop.start(interval)

    async def stop(self) -> None:
        await self._loop.stop()
        self._last_sent.clear()
        self._hydrated.clear()

    def forget(self, person_id: str) -> None:
        """Drop what we remember having sent to this person.

        Called on disconnect. The tick prunes on its own too, but only when
        it happens to run after the presence entry is gone: a client that
        drops and comes back inside one interval would keep its stale memo
        and receive nothing until the mood next moved. Making it explicit
        turns "usually resynced" into "resynced".

        Also called by ``emotion_engine`` when it evicts an idle oscillator:
        ``_hydrated`` describes a mood that is no longer in RAM, and leaving
        it set would make the next read skip ``ensure_person_loaded`` and
        start again from the origin.
        """
        self._last_sent.pop(person_id, None)
        self._hydrated.discard(person_id)

    def note_pushed(self, person_id: str) -> None:
        """Record that someone else just sent this person their current mood.

        The consumer pushes one frame itself on connect, so a client that
        reconnects into a calm moment isn't left on a stale face waiting for
        a mood that may never move. Without telling the loop, that frame is
        invisible to it: the person is unknown, ``_moved`` answers "yes, first
        sync", and the very same state goes out again within one interval.
        """
        try:
            from emotion.engine import emotion_engine

            msg = emotion_engine.compute_message_emotion(person_id)
        except Exception:
            logger.debug("emotion sync: could not record pushed state", exc_info=True)
            return
        self._last_sent[person_id] = (
            msg.emotion.value,
            msg.intensity,
            tuple(e.value for e, _ in msg.blend),
        )
        self._hydrated.add(person_id)

    async def tick(self) -> None:
        """One pass: for every connected client, push its emotion if it moved."""
        from communication.presence import presence_registry

        listeners = {
            i.person_id: i
            for i in presence_registry.reachable()
            if i.is_consumer
        }

        # Forget whoever left. A reconnecting client is then unknown again and
        # gets a frame on the next tick instead of waiting — possibly forever
        # — for a mood that may already be exactly where it was.
        for person_id in list(self._last_sent):
            if person_id not in listeners:
                self._last_sent.pop(person_id, None)
                self._hydrated.discard(person_id)

        for person_id, target in listeners.items():
            await self._sync_person(person_id, target.delivery_ref)

    async def _sync_person(self, person_id: str, group: str) -> None:
        from emotion.engine import emotion_engine
        from pipeline.broadcast import broadcast_emotion_update

        if person_id not in self._hydrated:
            # Reading a mood CREATES it at the origin, and
            # ``ensure_person_loaded`` is a no-op for anyone already in RAM —
            # so reading first would permanently lose the mood stored for
            # someone who reconnects before saying anything.
            await emotion_engine.ensure_person_loaded(person_id)
            self._hydrated.add(person_id)

        msg = emotion_engine.compute_message_emotion(person_id)
        signature = (
            msg.emotion.value,
            msg.intensity,
            tuple(e.value for e, _ in msg.blend),
        )
        if not self._moved(person_id, signature):
            return

        self._last_sent[person_id] = signature
        await broadcast_emotion_update(person_id, group=group)

    def _moved(
        self, person_id: str, signature: tuple[str, float, tuple[str, ...]],
    ) -> bool:
        """Is this worth a frame? Unknown person → yes (first sync)."""
        previous = self._last_sent.get(person_id)
        if previous is None:
            return True
        label, intensity, blend = signature
        prev_label, prev_intensity, prev_blend = previous
        return (
            label != prev_label
            or blend != prev_blend
            or abs(intensity - prev_intensity) >= MIN_INTENSITY_DELTA
        )


# Module-level singleton, consistent with the other engine loops.
emotion_sync = EmotionSync()
