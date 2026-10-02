"""Le harnais des tests de mémoire : un modèle scripté qui consolide selon la
conversation qu'on lui montre (une par appel), et de quoi lire ce qu'elle a
gardé et ce qu'on lui a montré pour parler à chacun."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

from mika.contracts import memory as memory_c
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from tests.fixtures.mika import said

SIX = ["un", "deux", "trois", "quatre", "cinq", "six"]
REPLY = "d'accord [EMOTION:happy:0.4]"


class Script:
    """Répond en conversation (``reply`` : un texte, ou une fonction du dernier
    message qui rend un texte ou ``None``), et consolide chaque conversation
    selon ``extract`` : une fonction du texte montré au modèle, qui rend les
    arguments de ``record_memories`` (ou ``None`` : rien à retenir)."""

    def __init__(self, extract: Callable[[str], dict[str, Any] | None] | None = None,
                 reply: Callable[[str], str | None] | str = REPLY) -> None:
        self.extract = extract
        self.reply = reply
        self.calls: list[LLMRequest] = []

    def __call__(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        if req.role == "extract":
            args = (self.extract(req.messages[-1].content) if self.extract else None) or {}
            return LLMResponse("", tool_calls=(ToolCall("x", "record_memories", args),), stop="tool_use")
        if callable(self.reply):
            text = self.reply(message_of(req))
            if text is not None:
                return LLMResponse(text)
            return LLMResponse(REPLY)
        return LLMResponse(self.reply)

    def extracts(self) -> list[str]:
        return [r.messages[-1].content for r in self.calls if r.role == "extract"]

    def prompts(self, handle: str, roles: tuple[str, ...] = ("reply", "initiative")) -> list[str]:
        """Tout ce qui a été montré au modèle pour parler à ``handle``."""
        return [r.system_stable + "\n".join(m.content for m in r.messages) for r in self.calls
                if r.role in roles and r.meta.get("target") == handle]

    def replies(self, handle: str) -> list[str]:
        """Ce qui a été montré au modèle pour répondre à ``handle``."""
        return self.prompts(handle, ("reply",))


def message_of(req: LLMRequest) -> str:
    last = req.messages[-1].content if req.messages else ""
    return last.rsplit("--- FIN ETAT INTERNE ---", 1)[-1].strip()


def token(prompt: str, name: str) -> str:
    """Le jeton d'une personne dans la conversation montrée (« Alice [P1] » → « [P1] »)."""
    m = re.search(rf"{re.escape(name)} (\[P\d+\])", prompt)
    return m.group(1) if m else name


def seq_of(prompt: str, needle: str) -> list[int]:
    """Les numéros des messages qui contiennent ``needle``."""
    return [int(m.group(1)) for m in re.finditer(r"^\[#(\d+)\] [^\n]*$", prompt, re.M) if needle in m.group(0)]


def section(prompt: str, title: str) -> str:
    """Le texte d'une section (vide si elle n'y est pas)."""
    marker = f"--- {title} ---"
    if marker not in prompt:
        return ""
    return prompt.split(marker, 1)[1].split("\n--- ", 1)[0]


async def chat(kernel: Any, handle: str, lines: list[str], gap_s: float = 60, **kw: Any) -> None:
    for text in lines:
        p = await kernel.perceive(said(handle, text, **kw))
        if p.reply is not None:  # ce qui ne lui est pas adressé n'attend pas de réponse
            await p.reply
        await asyncio.sleep(gap_s)


def kept(kernel: Any) -> list[dict[str, Any]]:
    """Ce qu'elle a gardé, ligne par ligne (les listes décodées)."""
    cols = ("id", "kind", "text", "about", "told_by", "heard_by", "secret", "sensitivity", "status", "confidence",
            "recalls", "due", "about_self", "informants")
    rows = kernel.mind.store.query_mind(f"SELECT {','.join(cols)} FROM {memory_c.ITEMS_TABLE} ORDER BY id")
    out = []
    for r in rows:
        d = dict(zip(cols, r, strict=True))
        for k in ("about", "told_by", "heard_by", "informants"):
            d[k] = json.loads(d[k] or "[]")
        out.append(d)
    return out
