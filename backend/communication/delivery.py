"""Registry of outbound delivery channels.

``presence_registry`` records *where* a person is reachable (``channel``
names such as ``"telegram"`` or ``"email"``); this registry records *who
can actually send* on such a channel.

Most channels are modules, so ``module_manager`` resolves them. But a
communication channel is not necessarily a module — ``TelegramChannel``
lives in ``communication/channels/`` and is never registered with the
module manager. Without this registry, resolving its deliverer silently
failed and the caller fell back to a global broadcast, showing a message
composed *for one person* to every connected browser.

A deliverer only needs ``is_running`` and ``async deliver(output, target)
-> bool`` — see the ``Deliverable`` protocol below.
"""
from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

_channels: dict[str, Any] = {}


@runtime_checkable
class Deliverable(Protocol):
    """Something that can push a message to a person on its own transport.

    Structural, and that is the point: this used to be a ``deliver()`` method
    on ``BaseModule`` returning ``False``. No module ever implemented it —
    the only implementer in the codebase is ``TelegramChannel``, which is not
    a module at all. A capability declared on a class none of whose subclasses
    have it, whose default answer was the only answer anyone ever received.

    Now the capability lives where delivery lives, and is checked by asking
    the object rather than by inheriting from anything: a future Discord
    channel, or a module that genuinely can initiate contact, simply grows
    the method.
    """

    is_running: bool

    async def deliver(self, output, interlocutor) -> bool: ...


def can_deliver(channel: Any) -> bool:
    """Whether this deliverer actually implements outbound delivery."""
    return callable(getattr(channel, "deliver", None))


def register_channel(name: str, channel: Any) -> None:
    """Declare that ``channel`` can deliver to targets tagged ``name``."""
    _channels[name] = channel


def unregister_channel(name: str) -> None:
    _channels.pop(name, None)


def get_channel(name: str) -> Any | None:
    """Resolve a deliverer: registered channel first, then modules."""
    channel = _channels.get(name)
    if channel is not None:
        return channel
    try:
        from modules.manager import module_manager

        return module_manager.get_module(name)
    except Exception:  # pragma: no cover - defensive, modules app optional
        logger.debug("module lookup failed for delivery channel %s", name)
        return None


def voice_sink_of(channel: Any) -> str | None:
    """Which ``VoiceSink`` this deliverer speaks through, if any.

    A channel opts into voice by exposing ``VOICE_SINK``. Absent attribute
    means text-only, which is the default for every existing channel.
    """
    return getattr(channel, "VOICE_SINK", None)


async def deliver_voice(channel: Any, clip, output, target) -> bool:
    """Hand a rendered clip to a channel, if it accepts one.

    Returns False when the channel has no voice path, so the caller falls
    back to text delivery rather than dropping the message.
    """
    send = getattr(channel, "deliver_voice", None)
    if send is None:
        return False
    try:
        return bool(await send(clip, output, target))
    except Exception:
        logger.exception("Channel voice delivery failed")
        return False
