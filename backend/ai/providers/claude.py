"""Claude provider — uses the Anthropic Python SDK (anthropic.AsyncAnthropic).

Conversation turns go through the native Messages API with **prompt
caching**: the stable prefix (personality + self-concept + identity) is a
system block marked ``cache_control``, the short-term history rides as real
message turns with a breakpoint on its last block, and the per-turn state is
embedded in the final user turn — after every breakpoint, so it never
invalidates what is cached. Tool-enabled turns run a native tool loop on the
same API (tools render before system, so the ~6 500 tokens of declarations
are covered by the same cached prefix, across iterations *and* across turns).

The Messages API is the only path. The ``claude_agent_sdk`` CLI subprocess,
authenticated by a Claude.ai OAuth token, is no longer supported by
Anthropic and has been removed: authentication is an API key, and a
401/403 is an ordinary authentication error that propagates — no fallback
can mask it any more.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Sampling parameters are rejected (HTTP 400) from Opus 4.7 onward, on
# Sonnet 5 and on the Fable/Mythos tier. Prompting is the steering mechanism
# there; sending the declared-model temperature would fail every call.
_NO_SAMPLING_PREFIXES = (
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-fable",
    "claude-mythos",
)

_CACHE_MARK = {"type": "ephemeral"}
# TTL accepté par l'API à côté de « ephemeral » (5 min implicite). Toute autre
# valeur lue en configuration retombe sur le marqueur nu : un TTL inconnu
# ferait rejeter chaque requête, ce qui coûte plus qu'un cache non prolongé.
_CACHE_TTL_ALLOWED = ("1h",)


def _cache_mark() -> dict:
    """Le marqueur ``cache_control`` du tour, TTL compris.

    Le cache de 5 min est dimensionné pour un chat serré ; un compagnon a des
    silences de 5 à 60 min, après lesquels personnalité + self-concept + les
    ~6 500 tokens d'outils sont réécrits à 1,25×. ``ai.claude.cache_ttl`` à
    « 1h » écrit à 2× mais relit à 0,1× pendant une heure — rentable dès la
    troisième lecture. Lu à chaque appel (``hot_reload``), jamais mis en
    cache ici : le marqueur est copié dans chaque bloc.
    """
    try:
        from configs.service import config_service

        ttl = str(config_service.get("ai.claude.cache_ttl") or "").strip()
    except Exception:
        ttl = ""
    if ttl in _CACHE_TTL_ALLOWED:
        return {"type": "ephemeral", "ttl": ttl}
    return dict(_CACHE_MARK)

# Plafond du second essai quand une réponse est tronquée en plein appel
# d'outil (``stop_reason == "max_tokens"`` avec un bloc ``tool_use``).
# Doubler sans borne finirait au-delà de ce que le SDK accepte hors
# streaming — son garde-fou de délai se déclenche vers 21 000 jetons de
# sortie.
_TOOL_CALL_CAP_CEILING = 16384
# Ce que le texte rendu porte quand même le second essai n'a pas suffi :
# l'appel n'a pas eu lieu, et le dire vaut mieux qu'une réponse qui s'arrête
# net comme si le modèle avait fini.
_TRUNCATED_TOOL_CALL_MARKER = "[réponse tronquée avant l'appel d'outil]"


def _new_totals() -> dict:
    return {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}


def _model_accepts_temperature(model: str) -> bool:
    return not model.startswith(_NO_SAMPLING_PREFIXES)


class ClaudeProvider:
    """Anthropic Claude via the official ``anthropic`` Python SDK.

    Authenticated by API key, exclusively.
    Uses ``anthropic.AsyncAnthropic.messages.create()`` for completions.
    """

    def __init__(self):
        from anthropic import AsyncAnthropic
        from configs.service import config_service

        api_key = config_service.get("ai.claude.api_key", default="") or None

        if not api_key:
            raise ValueError(
                "ClaudeProvider nécessite une clé d'API Anthropic : saisis-la "
                "dans Configuration → IA · Claude (champ « Clé d'API »). Les "
                "jetons OAuth Claude.ai ne sont plus acceptés."
            )

        self._client = AsyncAnthropic(api_key=api_key)

        # Modèles dont le serveur a refusé ``temperature`` alors qu'ils ne
        # figurent pas dans _NO_SAMPLING_PREFIXES (id futur) : mémorisés pour
        # ne pas payer une requête condamnée + un retry à chaque appel.
        self._no_temperature_models: set[str] = set()

        logger.info("ClaudeProvider initialisé (auth=clé d'API)")

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        attachments: list | None = None,
    ) -> str:
        # Build content: image blocks first, then text
        if attachments:
            content: list | str = []
            for att in attachments:
                if att.category == "image":
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": att.media_type,
                            "data": att.data,
                        },
                    })
            content.append({"type": "text", "text": user_prompt})
        else:
            content = user_prompt

        # Même passage gardé que le chemin conversationnel : les modèles
        # récents (Opus 4.7+, Sonnet 5, Fable) refusent ``temperature`` en
        # 400 — sans le garde, chaque rôle non conversationnel mappé sur un
        # de ces modèles (extraction, inner_voice, caption…) échouait à
        # chaque appel pendant que le chat, lui, marchait.
        response = await self._create_message(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
            temperature=temperature,
        )

        # Surface native token usage to the quota tracker. No-op when this
        # call wasn't routed through AIRouter (e.g. ad-hoc provider use).
        totals = _new_totals()
        self._accumulate_usage(getattr(response, "usage", None), totals)
        self._flush_usage(totals)

        parts = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)

        return "".join(parts)

    # ── Structured conversation turns (ChatPrompt) ───────────────

    async def complete_chat(
        self,
        prompt,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Conversation turn with prompt caching and real message turns."""
        system, messages = self._chat_payload(prompt)
        response = await self._create_message(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            temperature=temperature,
        )
        totals = _new_totals()
        self._accumulate_usage(getattr(response, "usage", None), totals)
        self._flush_usage(totals)
        return "".join(b.text for b in response.content if b.type == "text")

    async def complete_chat_with_tools(
        self,
        prompt,
        model: str,
        tools: list,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        *,
        max_turns: int = 10,
    ) -> tuple[str, list[str]]:
        """Tool-enabled turn on the native Messages API.

        The tool declarations render *before* the system prompt, so the
        cache breakpoint on the stable system block covers them too: the
        ~6 500 tokens of declarations are written to cache once and read at
        ~0.1× afterwards — across loop iterations and across turns — instead
        of being re-billed at full price on every iteration.
        """
        if not tools:
            text = await self.complete_chat(
                prompt, model=model, max_tokens=max_tokens, temperature=temperature,
            )
            return text, []

        system, messages = self._chat_payload(prompt)
        return await self._native_tool_loop(
            system=system,
            messages=messages,
            model=model,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            max_turns=max_turns,
        )

    async def _native_tool_loop(
        self,
        *,
        system,
        messages: list[dict],
        model: str,
        tools: list,
        max_tokens: int,
        temperature: float,
        max_turns: int,
    ) -> tuple[str, list[str]]:
        # Sorted so the serialized declarations are byte-stable from one
        # request to the next — a reordered tool list is a different prefix
        # and silently invalidates the whole cache.
        tool_defs = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.to_json_schema(),
            }
            for t in sorted(tools, key=lambda t: t.name)
        ]
        handlers = {t.name: t.handler for t in tools}

        totals = _new_totals()
        texts: list[str] = []
        calls: list[str] = []
        # Only the *newest* tool_result carries a cache breakpoint: markers
        # accumulate across iterations otherwise, and the API caps them at 4
        # per request.
        marked_result: dict | None = None
        cap = max_tokens
        cap_raised = False

        try:
            for _ in range(max_turns):
                response = await self._create_message(
                    model=model,
                    max_tokens=cap,
                    system=system,
                    messages=messages,
                    tools=tool_defs,
                    temperature=temperature,
                )
                self._accumulate_usage(getattr(response, "usage", None), totals)
                tool_uses = [b for b in response.content if b.type == "tool_use"]

                if (
                    response.stop_reason == "max_tokens"
                    and tool_uses
                    and not cap_raised
                    and cap < _TOOL_CALL_CAP_CEILING
                ):
                    # Tronquée en plein appel d'outil : le bloc ``tool_use``
                    # est là, mais la sortie s'est arrêtée avant sa fin. La
                    # boucle sortait comme si le modèle avait fini — l'appel
                    # disparaissait sans un mot. Cette itération est rejouée
                    # une fois avec un plafond doublé (borné) ; le texte de
                    # l'essai tronqué n'est pas gardé, celui-ci le remplace.
                    cap_raised = True
                    cap = min(cap * 2, _TOOL_CALL_CAP_CEILING)
                    logger.warning(
                        "Claude: réponse tronquée (max_tokens) en plein appel "
                        "d'outil sur %s — nouvel essai avec max_tokens=%d",
                        model, cap,
                    )
                    response = await self._create_message(
                        model=model,
                        max_tokens=cap,
                        system=system,
                        messages=messages,
                        tools=tool_defs,
                        temperature=temperature,
                    )
                    self._accumulate_usage(getattr(response, "usage", None), totals)
                    tool_uses = [b for b in response.content if b.type == "tool_use"]

                turn_text = "".join(
                    b.text for b in response.content if b.type == "text"
                )
                if turn_text:
                    texts.append(turn_text)

                if response.stop_reason == "refusal":
                    # Un refus n'est pas une fin de tour ordinaire : il
                    # porte une catégorie, et c'est elle qu'on veut lire
                    # dans le journal quand une réponse manque.
                    logger.warning(
                        "Claude a refusé de poursuivre (stop_reason=refusal, "
                        "stop_details=%s)",
                        getattr(response, "stop_details", None),
                    )
                    break
                if response.stop_reason == "max_tokens" and tool_uses:
                    logger.warning(
                        "Claude: appel d'outil encore tronqué à max_tokens=%d "
                        "sur %s — l'appel n'a pas eu lieu", cap, model,
                    )
                    texts.append(_TRUNCATED_TOOL_CALL_MARKER)
                    break
                if response.stop_reason != "tool_use" or not tool_uses:
                    break

                messages.append({"role": "assistant", "content": response.content})

                if marked_result is not None:
                    marked_result.pop("cache_control", None)

                results = []
                for block in tool_uses:
                    calls.append(block.name)
                    logger.info(
                        "Claude called tool: %s (input=%s)",
                        block.name, str(block.input)[:200],
                    )
                    results.append(await self._execute_tool(handlers, block))
                results[-1]["cache_control"] = _cache_mark()
                marked_result = results[-1]
                messages.append({"role": "user", "content": results})
            else:
                logger.warning(
                    "Boucle d'outils Claude: max_turns=%d atteint sans réponse finale",
                    max_turns,
                )
        finally:
            self._flush_usage(totals)

        if calls:
            logger.info("Tools used in this turn: %s", calls)
        return "\n\n".join(texts), calls

    @staticmethod
    async def _execute_tool(handlers: dict, block) -> dict:
        """Run one tool call; an error becomes an ``is_error`` result, never a raise."""
        result: dict = {"type": "tool_result", "tool_use_id": block.id}
        handler = handlers.get(block.name)
        if handler is None:
            result["content"] = f"Outil inconnu: {block.name}"
            result["is_error"] = True
            return result
        try:
            out = await handler(dict(block.input or {}))
        except Exception as exc:  # noqa: BLE001 — l'erreur retourne au modèle
            logger.exception("Outil %s en erreur", block.name)
            result["content"] = f"Erreur outil {block.name}: {exc}"
            result["is_error"] = True
            return result
        result["content"] = _tool_result_text(out)
        # Les handlers du repo parlent MCP et signalent l'échec en camelCase
        # (``isError``) ; on accepte aussi le snake_case par tolérance.
        if isinstance(out, dict) and (out.get("isError") or out.get("is_error")):
            result["is_error"] = True
        return result

    # ── Payload construction & plumbing ──────────────────────────

    @staticmethod
    def _chat_payload(prompt) -> tuple[list[dict], list[dict]]:
        """(system blocks, messages) with the two standing cache breakpoints.

        Breakpoint 1 — the stable system block: covers the tool declarations
        (rendered before system) plus personality/self-concept/identity.
        Breakpoint 2 — the last history message: the conversation prefix up
        to the previous exchange is read from cache; only the newest exchange
        and the per-turn state (embedded in the final user turn, *after* the
        breakpoints) are billed at full price.
        """
        system = [{
            "type": "text",
            "text": prompt.system_stable,
            "cache_control": _cache_mark(),
        }]
        chat = prompt.chat_messages()
        last_history_idx = len(chat) - 2
        messages: list[dict] = []
        for i, m in enumerate(chat):
            if i < len(chat) - 1:
                # Every history turn is rendered as an explicit text block:
                # last turn's breakpoint moves one position back on the next
                # request, and the prefix only matches byte-for-byte if the
                # block keeps the same shape with or without its marker.
                block: dict = {"type": "text", "text": m["content"]}
                if i == last_history_idx:
                    block["cache_control"] = _cache_mark()
                messages.append({"role": m["role"], "content": [block]})
            else:
                # Final user turn — per-turn state + message, after every
                # breakpoint, so it can stay a plain string.
                messages.append({"role": m["role"], "content": m["content"]})
        return system, messages

    async def _create_message(
        self,
        *,
        model: str,
        max_tokens: int,
        system,
        messages,
        tools: list | None = None,
        temperature: float | None = None,
    ):
        """One ``messages.create`` call, sampling params gated per model.

        Opus 4.7+/Sonnet 5/Fable reject ``temperature`` outright; older
        models keep honouring the declared-model value. A 400 naming the
        parameter is retried once without it **and memoized**: an unknown
        future model id pays the doomed request one single time per provider
        instance, not on every call and every tool-loop iteration.
        """
        from anthropic import BadRequestError

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        # ``getattr`` défensif : des tests (et d'éventuels usages ad hoc)
        # construisent le provider via ``__new__`` sans passer par __init__.
        no_temp = getattr(self, "_no_temperature_models", None)
        if no_temp is None:
            no_temp = self._no_temperature_models = set()
        if (
            temperature is not None
            and _model_accepts_temperature(model)
            and model not in no_temp
        ):
            kwargs["temperature"] = temperature
        try:
            return await self._client.messages.create(**kwargs)
        except BadRequestError as exc:
            if "temperature" in kwargs and "temperature" in str(exc):
                no_temp.add(model)
                logger.info(
                    "Le modèle %s refuse `temperature` — mémorisé, plus "
                    "jamais envoyé pour cette instance.", model,
                )
                kwargs.pop("temperature")
                return await self._client.messages.create(**kwargs)
            raise

    @staticmethod
    def _accumulate_usage(usage, totals: dict) -> None:
        """Add one response's usage to the running totals.

        Les jetons de cache sont comptés **à part** : ce sont des jetons
        consommés — ils comptent dans le quota, et sur le chemin outillé ils
        portent l'essentiel du prompt (système + outils, relus itération
        après itération) — mais fondus dans ``in`` ils se facturaient au
        tarif d'entrée plein, dix fois le prix réel d'une lecture de cache.
        """
        if usage is None:
            return
        totals["in"] += int(getattr(usage, "input_tokens", 0) or 0)
        totals["out"] += int(getattr(usage, "output_tokens", 0) or 0)
        totals["cache_read"] += int(
            getattr(usage, "cache_read_input_tokens", 0) or 0
        )
        totals["cache_write"] += int(
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        )

    @staticmethod
    def _flush_usage(totals: dict) -> None:
        """Surface the accumulated usage to the quota tracker (best-effort)."""
        try:
            from ai.quota import set_usage
            if any(totals.values()):
                set_usage(
                    input_tokens=totals["in"],
                    output_tokens=totals["out"],
                    cache_read_tokens=totals["cache_read"],
                    cache_write_tokens=totals["cache_write"],
                )
        except Exception:
            pass

    async def list_models(self) -> list[dict]:
        """List Claude models reachable with the configured credentials."""
        page = await self._client.models.list(limit=100)
        out = []
        for m in page.data:
            out.append({
                "id": m.id,
                "label": getattr(m, "display_name", None) or m.id,
            })
        return out

    async def test(self) -> dict:
        from ai.providers import default_test
        return await default_test(self)

    # ── Tool-enabled completion (flattened two-string shape) ─────
    async def complete_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        tools: list,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        *,
        max_turns: int = 10,
    ) -> tuple[str, list[str]]:
        """Tool-enabled completion from a plain (system, user) pair.

        Accepts a list of provider-agnostic ``ModuleTool`` objects — each
        exposing ``name``, ``description``, ``to_json_schema()`` and an
        async ``handler``. Runs the same native Messages loop as the
        structured path; only the payload differs.

        Returns ``(assistant_text, tool_names_called_in_order)``.
        """
        if not tools:
            text = await self.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return text, []

        # Pas de ``cache_control`` ici, contrairement au chemin structuré :
        # ce prompt système est le rendu aplati, état par tour compris, donc
        # le préfixe change à chaque appel. Marquer le bloc paierait l'
        # écriture en cache (1,25×) pour une lecture qui n'arriverait jamais.
        return await self._native_tool_loop(
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            model=model,
            tools=tools,
            max_tokens=max_tokens,
            temperature=temperature,
            max_turns=max_turns,
        )


def _tool_result_text(out) -> str:
    """Normalise a module-tool handler result into tool_result text.

    Handlers were written for the MCP shape (``{"content": [{"type": "text",
    "text": ...}]}``); anything else is serialized defensively — a tool
    result must never crash the turn.
    """
    if isinstance(out, dict):
        content = out.get("content")
        if isinstance(content, list):
            texts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            if texts:
                return "\n".join(texts)
        if isinstance(content, str) and content:
            return content
        try:
            return json.dumps(out, ensure_ascii=False, default=str)
        except Exception:
            return str(out)
    return "" if out is None else str(out)

