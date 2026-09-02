"""Shared tool-calling loop for OpenAI-compatible endpoints.

Both ``OpenAIProvider`` and ``GLMProvider`` hit an OpenAI-compatible
``/chat/completions`` surface, so the tool-loop (serialize tools,
ping/pong tool_calls, append tool results, stop when no more calls)
is identical. Keeping it here prevents divergence.

The caller passes:
  - an already-configured ``AsyncOpenAI`` client
  - the model id
  - the thread to start from, as a ``messages`` array
  - a list of provider-agnostic ``ModuleTool`` objects

and gets back ``(assistant_text, tool_names_called_in_order)``.

Le fil de départ arrive **déjà construit** : c'est ce qui permet au tour
outillé de partir de la forme structurée (préfixe stable en système, vrais
tours d'historique, état du tour dans le dernier tour user) au lieu de
l'aplatissement à deux chaînes. Deux amorces, un seul corps —
``run_openai_tool_loop_from_pair`` reste là pour le chemin non structuré
(``AIRouter.complete_with_tools``), qui ne connaît que deux chaînes.
"""

from __future__ import annotations

import json
import logging

from utils.degradation import degradations

logger = logging.getLogger(__name__)


class ParamMemo:
    """Ce que chaque modèle a refusé, mémorisé par instance de provider.

    Miroir de ``ClaudeProvider._create_message`` : un modèle de raisonnement
    (série o, gpt-5) refuse ``max_tokens`` en 400 — « use
    'max_completion_tokens' instead » — et refuse ``temperature`` hors de sa
    valeur par défaut. Sans reprise, chaque rôle mappé sur un tel modèle
    échouait à chaque appel ; sans mémo, chaque appel paierait la requête
    condamnée avant la bonne, et chaque itération de la boucle d'outils
    avec lui.
    """

    def __init__(self) -> None:
        #: modèle → nom du paramètre de plafond accepté (absent = ``max_tokens``)
        self.token_param: dict[str, str] = {}
        #: modèles dont le serveur a refusé ``temperature``
        self.no_temperature: set[str] = set()


def memo_for(owner) -> ParamMemo:
    """Le mémo de ce provider, créé à la demande.

    ``getattr`` défensif : des tests (et d'éventuels usages ad hoc)
    construisent le provider via ``__new__`` sans passer par ``__init__``.
    """
    memo = getattr(owner, "_param_memo", None)
    if memo is None:
        memo = ParamMemo()
        try:
            owner._param_memo = memo
        except Exception:  # noqa: BLE001 — un objet figé garde un mémo jetable
            pass
    return memo


async def create_chat_completion(
    client,
    memo: ParamMemo | None,
    *,
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    **extra,
):
    """Un ``chat.completions.create``, paramètres de génération repris au 400.

    ``max_tokens`` reste le **premier** essai : les serveurs compatibles
    OpenAI tiers (Groq, vLLM, LM Studio, Zhipu) ne connaissent souvent que
    ce nom, et c'est le cas commun. Deux reprises au plus, une par
    paramètre, chacune mémorisée pour le modèle : ``max_tokens`` →
    ``max_completion_tokens`` quand le refus nomme le premier, ``temperature``
    retirée quand il la nomme. Toute autre erreur remonte intacte.
    """
    try:
        from openai import BadRequestError
    except ImportError:  # pragma: no cover — le provider n'existerait pas
        BadRequestError = ()  # type: ignore[assignment]

    memo = memo if memo is not None else ParamMemo()
    token_param = memo.token_param.get(model, "max_tokens")
    send_temperature = model not in memo.no_temperature
    renamed = False
    dropped = False

    while True:
        kwargs = {"model": model, "messages": messages, token_param: max_tokens}
        if send_temperature:
            kwargs["temperature"] = temperature
        kwargs.update(extra)
        try:
            return await client.chat.completions.create(**kwargs)
        except BadRequestError as exc:
            text = str(exc)
            if token_param == "max_tokens" and not renamed and "max_tokens" in text:
                renamed = True
                token_param = "max_completion_tokens"
                memo.token_param[model] = token_param
                logger.info(
                    "Le modèle %s refuse `max_tokens` — `max_completion_tokens` "
                    "mémorisé pour cette instance.", model,
                )
                continue
            if send_temperature and not dropped and "temperature" in text:
                dropped = True
                send_temperature = False
                memo.no_temperature.add(model)
                logger.info(
                    "Le modèle %s refuse `temperature` — mémorisé, plus "
                    "jamais envoyée pour cette instance.", model,
                )
                continue
            raise


def messages_from_pair(system_prompt: str, user_prompt: str) -> list[dict]:
    """Fil de départ pour un appel à deux chaînes."""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def messages_from_chat_prompt(prompt) -> list[dict]:
    """Fil de départ pour un ``ChatPrompt``.

    Même rendu que ``complete_chat`` : le préfixe stable en système, puis de
    vrais tours ``{role, content}``. La boucle d'outils n'ajoute qu'à la fin,
    donc ce préfixe reste identique octet pour octet d'un aller-retour à
    l'autre — ce sur quoi les back-ends compatibles OpenAI indexent leur
    cache de préfixe automatique.
    """
    return [
        {"role": "system", "content": prompt.system_stable},
        *prompt.chat_messages(),
    ]


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


async def run_openai_tool_loop_from_pair(
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
    memo: ParamMemo | None = None,
) -> tuple[str, list[str]]:
    """Amorce à deux chaînes du même corps de boucle."""
    return await run_openai_tool_loop(
        client=client,
        provider_label=provider_label,
        messages=messages_from_pair(system_prompt, user_prompt),
        model=model,
        tools=tools,
        max_tokens=max_tokens,
        temperature=temperature,
        max_turns=max_turns,
        memo=memo,
    )


async def run_openai_tool_loop(
    *,
    client,
    provider_label: str,
    messages: list[dict],
    model: str,
    tools: list,
    max_tokens: int,
    temperature: float,
    max_turns: int,
    memo: ParamMemo | None = None,
) -> tuple[str, list[str]]:
    """Run a ping/pong tool loop against an OpenAI-compatible endpoint.

    When ``tools`` is empty the loop collapses to a single completion.

    Also surfaces per-turn token usage to ``ai.quota.set_usage`` so the
    quota tracker sees real numbers instead of char-estimates.

    ``memo`` est celui du provider appelant : un paramètre refusé au premier
    tour ne doit pas être re-tenté à chaque itération de la boucle.
    """
    from ai.quota import set_usage

    # Le fil appartient à l'appelant : la boucle y empile ses allers-retours.
    messages = list(messages)

    tools_by_name = {t.name: t for t in tools}
    serialized = _serialize_tools(tools) if tools else None

    called: list[str] = []
    final_text = ""

    for turn in range(max_turns):
        extra = {"tools": serialized} if serialized else {}
        response = await create_chat_completion(
            client, memo,
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **extra,
        )

        usage = getattr(response, "usage", None)
        if usage is not None:
            try:
                set_usage(
                    input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                )
            except Exception as exc:
                degradations.record(
                    "ai.providers._openai_tools.run_openai_tool_loop usage", exc,
                )

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
