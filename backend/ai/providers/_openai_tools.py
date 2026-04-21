"""Shared tool-calling loop for OpenAI-compatible endpoints.

Both ``OpenAIProvider`` and ``GLMProvider`` hit an OpenAI-compatible
``/chat/completions`` surface, so the tool-loop (serialize tools,
ping/pong tool_calls, append tool results, stop when no more calls)
is identical. Keeping it here prevents divergence.

The caller passes:
  - an already-configured ``AsyncOpenAI`` client
  - the model id
  - the system/user prompts
  - a list of provider-agnostic ``ModuleTool`` objects

and gets back ``(assistant_text, tool_names_called_in_order)``.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def _serialize_tools(tools: list) -> list[dict]:
    """Convert ``ModuleTool`` list → OpenAI ``tools`` parameter shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.to_json_schema(),
            },
        }
        for t in tools
    ]


async def _run_handler(tool, raw_args: str) -> str:
    """Invoke a ``ModuleTool.handler`` with parsed JSON args.

    Errors in the handler are surfaced as tool content so the model
    sees them and can recover, instead of bubbling up and killing
    the whole turn.
    """
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"invalid JSON arguments: {exc}"})
    try:
        result = await tool.handler(args)
    except Exception as exc:  # noqa: BLE001 — forward to the model
        logger.warning("Tool '%s' handler raised: %s", tool.name, exc)
        return json.dumps({"error": str(exc)})
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except TypeError:
        return json.dumps({"result": str(result)})


async def run_openai_tool_loop(
    *,
    client,
    provider_label: str,
    system_prompt: str,
    user_prompt: str,
    model: str,
    tools: list,
    max_tokens: int,
    temperature: float,
    max_turns: int,
) -> tuple[str, list[str]]:
    """Run a ping/pong tool loop against an OpenAI-compatible endpoint.

    When ``tools`` is empty the loop collapses to a single completion.

    Also surfaces per-turn token usage to ``ai.quota.set_usage`` so the
    quota tracker sees real numbers instead of char-estimates.
    """
    from ai.quota import set_usage

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    tools_by_name = {t.name: t for t in tools}
    serialized = _serialize_tools(tools) if tools else None

    called: list[str] = []
    final_text = ""

    for turn in range(max_turns):
        kwargs = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if serialized:
            kwargs["tools"] = serialized

        response = await client.chat.completions.create(**kwargs)

        usage = getattr(response, "usage", None)
        if usage is not None:
            try:
                set_usage(
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
            except Exception:
                pass

        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []

        if not tool_calls:
            final_text = msg.content or ""
            break

        # Replay the assistant turn (content + tool_calls) into the thread.
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            name = tc.function.name
            tool = tools_by_name.get(name)
            if tool is None:
                content = json.dumps({"error": f"unknown tool '{name}'"})
            else:
                logger.info(
                    "%s called tool: %s (input=%s)",
                    provider_label, name, (tc.function.arguments or "")[:200],
                )
                content = await _run_handler(tool, tc.function.arguments or "")
                called.append(name)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": content,
            })
    else:
        # Loop exhausted without a tool-free response — surface whatever
        # text the model produced in the last turn (may be empty).
        final_text = final_text or "[max_turns atteint avant réponse finale]"

    if called:
        logger.info("%s tools used in this turn: %s", provider_label, called)
    return final_text, called
