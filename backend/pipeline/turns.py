"""Turn queue — running a conversation turn off the socket's read loop.

Why this exists, mechanically. Channels dispatches a consumer's messages
**one at a time**: ``await_many_dispatch`` awaits each handler before
reading the next frame. The WebSocket consumer awaited the whole pipeline
inside ``receive()``, so for the duration of a turn — up to
``ai.call_timeout_seconds``, and on a local model routinely all of it —
that connection was deaf. It could not answer a keepalive, could not serve
a catch-up, could not accept the next message. A client with a liveness
watchdog therefore concluded the socket was dead in the middle of every
slow turn and reconnected, which is the opposite of what a keepalive is
for.

Detaching with a bare ``create_task`` per message would trade that for two
worse problems: several turns for the same person running at once, whose
replies can come back out of order, and several concurrent LLM calls —
disastrous against a local server with one execution slot, where they do
not run in parallel, they queue while each blocks the socket that is
waiting for it.

So: a queue with a small, fixed pool. Turns stay strictly ordered, the
read loop stays free, and the reply reaches its recipient the way it
always did — ``broadcast_to_websocket`` sends to the *person's* group, not
to the socket that asked. That indirection already existed and is what
makes this cheap: **a turn never needed the connection that started it.**

What this deliberately does NOT do: serialise every LLM call in the
process. The conscience, the project runner and the sleep cycle call the
model from their own loops and do not pass through here. "Never two calls
at once on a one-slot backend" is a different problem with a different
home, and it lives there now: ``AIRouter`` holds a per-provider semaphore
(``ai.<provider>.max_concurrent_calls``, declared for every provider —
default 1 for ollama, unbounded elsewhere) around every routed call. This
queue orders the *turns*; that semaphore orders the *calls*.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

DEFAULT_WORKERS = 1

# Bound on the backlog. Reached only if turns arrive faster than they can be
# answered, which for a personal install means something is already wrong;
# refusing loudly beats accumulating an hour of replies nobody waits for.
MAX_PENDING = 100

# Ceiling on how many interrupted turns a boot will replay. A restart in the
# middle of a busy minute should resume a conversation, not open with a
# burst of stale answers to questions the person has moved on from.
MAX_RESUMED = 10


class TurnQueue:
    """Serialises conversation turns, off the connection that requested them."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue | None = None
        self._workers: list[asyncio.Task] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._inflight = 0
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def is_running(self) -> bool:
        return bool(self._workers) and not self._loop_changed()

    def _loop_changed(self) -> bool:
        """Are our workers stranded on an event loop that is no longer ours?

        A module-level singleton outlives any single loop. The server has
        exactly one, so this never fires in production — but a test suite
        gives each test its own, and workers left over from the previous
        one are tasks that will never run again, sitting on a queue nobody
        drains. Without this check, ``submit`` sees a non-empty worker list,
        declines to start, and the caller waits forever for a turn that has
        no one to process it.
        """
        if self._loop is None:
            return False
        try:
            return asyncio.get_running_loop() is not self._loop
        except RuntimeError:
            return False

    def _reset_if_stranded(self) -> None:
        if not self._loop_changed():
            return
        logger.debug("Turn queue: event loop changed, rebuilding the pool")
        self._workers = []
        self._queue = None
        self._loop = None
        self._inflight = 0
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def pending(self) -> int:
        return self._queue.qsize() if self._queue else 0

    async def start(self, workers: int | None = None) -> None:
        """Spin up the pool. Idempotent."""
        self._reset_if_stranded()
        if self._workers:
            return
        self._loop = asyncio.get_running_loop()
        if workers is None:
            workers = self._configured_workers()
        # Never replace a queue that already holds work: submit() creates one
        # eagerly when it lazily starts the pool, and swapping it here would
        # drop exactly the perception that triggered the start.
        if self._queue is None:
            self._queue = asyncio.Queue(maxsize=MAX_PENDING)
        self._workers = [
            asyncio.create_task(self._run(), name=f"turn-worker-{i}")
            for i in range(max(1, workers))
        ]
        logger.info("Turn queue started (%d worker(s))", len(self._workers))

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                logger.debug("Turn worker exited with an error", exc_info=True)
        self._workers = []
        self._queue = None
        self._loop = None
        self._inflight = 0
        self._idle.set()

    @staticmethod
    def _configured_workers() -> int:
        from configs.service import config_service

        try:
            return max(1, int(config_service.get("pipeline.turn_workers")))
        except Exception:
            # An unreadable config must not leave the pipeline unable to
            # answer: one worker is the safe shape, not the absent one.
            return DEFAULT_WORKERS

    def submit(self, perception) -> bool:
        """Hand a perception to the pool. Never blocks, never raises.

        Returns False when the backlog is full — the caller can say so
        instead of leaving the sender waiting on an answer that was never
        going to come.

        Lazily starts the pool so a perception submitted before the ASGI
        lifespan ran (or in a test) is processed rather than dropped.
        """
        self._reset_if_stranded()
        if not self._workers:
            # The queue has to exist before the put below, and start() is a
            # coroutine we cannot await from here — so create the queue now
            # and let start() adopt it rather than build its own.
            if self._queue is None:
                self._queue = asyncio.Queue(maxsize=MAX_PENDING)
            try:
                asyncio.get_running_loop().create_task(self.start())
            except RuntimeError:
                # No loop: a caller outside async context. The work is
                # queued and will be picked up when the pool does start.
                logger.debug("submit() outside a running loop — queued only")

        try:
            self._queue.put_nowait(perception)
        except asyncio.QueueFull:
            logger.warning(
                "Turn queue full (%d) — refusing turn from %s",
                MAX_PENDING, getattr(perception, "person_id", "?"),
            )
            return False
        self._idle.clear()
        return True

    async def drain(self) -> None:
        """Wait until the backlog is empty and nothing is in flight.

        For tests and for shutdown. Not used by the request path: the whole
        point is that nobody waits on a turn.
        """
        self._reset_if_stranded()
        if self._queue is None:
            return
        if not self._workers:
            # Nothing will ever call task_done() — joining would hang.
            await self.start()
        await self._queue.join()
        await self._idle.wait()

    async def _run(self) -> None:
        assert self._queue is not None
        queue = self._queue
        while True:
            perception = await queue.get()
            self._inflight += 1
            self._idle.clear()
            try:
                await self._process(perception)
            finally:
                self._inflight -= 1
                queue.task_done()
                if self._inflight == 0 and queue.empty():
                    self._idle.set()

    async def _process(self, perception) -> None:
        """One turn. An exception here must never take the worker down.

        Nothing supervises this pool. A single malformed perception ending
        the only worker would silently stop every conversation on the
        install until the next restart, with no error anyone would see.
        """
        from pipeline.router import perceive

        try:
            await perceive(perception)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Turn failed for %s (source=%s)",
                getattr(perception, "person_id", "?"),
                getattr(perception, "source", "?"),
            )


# Module-level singleton, consistent with the other engine components.
turn_queue = TurnQueue()


async def resume_interrupted_turns() -> int:
    """Re-queue questions that were written down but never answered.

    ``Message.awaiting_reply`` is set when a question is persisted and
    cleared when its reply is. A row still carrying it at boot means the
    process died mid-turn — the exact case the split persistence was
    introduced to make visible.

    The flag is cleared as the turn is re-queued, not when it succeeds. A
    turn that dies the same way twice would otherwise be replayed at every
    boot for the life of the install, and a crash loop is a worse failure
    than one unanswered message.

    The persisted text is already preprocessed — vision captions and
    transcripts were inlined before it was written — so replaying it as
    plain text is faithful and skips re-running the preprocessors over
    media that may no longer be on disk.
    """
    from memory.models import Message
    from pipeline.perception import Intent, Perception

    try:
        rows = [
            row
            async for row in Message.objects.filter(
                awaiting_reply=True, role="user", is_internal=False,
            ).order_by("pk")[:MAX_RESUMED]
        ]
    except Exception:
        logger.exception("Could not look for interrupted turns")
        return 0

    if not rows:
        return 0

    ids = [row.pk for row in rows]
    # Cleared first, so a failure to submit cannot leave a row that is
    # replayed forever.
    await Message.objects.filter(pk__in=ids).aupdate(awaiting_reply=False)

    resumed = 0
    for row in rows:
        perception = Perception.from_text(
            row.content,
            source=row.source or "frontend",
            person_id=row.person_id,
            intent=Intent.REQUEST_RESPONSE,
            metadata={"resumed": True, "original_message_id": row.pk},
        )
        if turn_queue.submit(perception):
            resumed += 1

    logger.info("Resumed %d interrupted turn(s) after restart", resumed)
    return resumed
