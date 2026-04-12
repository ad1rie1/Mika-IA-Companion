"""AI provider abstraction layer.

Each provider lives in its own module and uses its native Python SDK.
The Protocol defines the common interface; the router uses it to
dispatch completion requests.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AIProvider(Protocol):
    """Minimal interface for AI text completion providers.

    Every provider must implement ``complete()`` — single-turn,
    no streaming, no tools.  Just system prompt + user prompt → text.
    """

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str: ...
