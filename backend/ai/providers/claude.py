"""Claude provider — uses the Anthropic Python SDK (anthropic.AsyncAnthropic).

Conversation turns go through the native Messages API with **prompt
caching**: the stable prefix (personality + self-concept + identity) is a
system block marked ``cache_control``, the short-term history rides as real
message turns with a breakpoint on its last block, and the per-turn state is
embedded in the final user turn — after every breakpoint, so it never
invalidates what is cached. Tool-enabled turns run a native tool loop on the
same API (tools render before system, so the ~6 500 tokens of declarations
are covered by the same cached prefix, across iterations *and* across turns).

The claude_agent_sdk (CLI subprocess) survives only as a fallback for
credentials the raw API refuses — an OAuth token whose entitlements are
CLI-only. The switch happens on a **401 before any side effect** (such a
credential fails on the very first request) and covers tooled and untooled
turns alike, for the instance's lifetime; a credential rotation recreates
the instance and retries native. A 403 never switches (possibly transient,
and the CLI would fail the same way), and an auth error after a tool
already ran propagates — replaying the turn would re-run the side effects.
"""

from __future__ import annotations

import json
import logging
import os

from django.conf import settings

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


def _model_accepts_temperature(model: str) -> bool:
    return not model.startswith(_NO_SAMPLING_PREFIXES)


class _NativeAuthRejected(Exception):
    """Raised when the Messages API rejects the credentials **before any
    side effect** — the only situation where replaying the turn through the
    claude_agent_sdk CLI is safe. An auth error after a tool already ran
    must propagate instead: a replay would re-send the email."""


class ClaudeProvider:
    """Anthropic Claude via the official ``anthropic`` Python SDK.

    Supports both API key and OAuth token authentication.
    Uses ``anthropic.AsyncAnthropic.messages.create()`` for completions.
    """

    def __init__(self):
        from anthropic import AsyncAnthropic
        from configs.service import config_service

        api_key = config_service.get("ai.claude.api_key", default="") or None
        auth_token = config_service.get("ai.claude.oauth_token", default="") or None

        if not api_key and not auth_token:
            raise ValueError(
                "ClaudeProvider nécessite ai.claude.api_key ou ai.claude.oauth_token "
                "(éditeur Configuration > IA · Providers)."
            )

        # The anthropic SDK supports both api_key and auth_token kwargs.
        # auth_token is used for OAuth-based access (Claude.ai sessions).
        # claude_agent_sdk (used by complete_with_tools) ne lit ses
        # identifiants que dans l'environnement du sous-processus CLI, qu'il
        # construit par ``{**os.environ, **options.env, ...}``. On porte donc
        # l'identifiant dans ``options.env`` (voir _run_tool_loop), jamais
        # dans os.environ.
        if auth_token:
            self._agent_env = {"CLAUDE_CODE_OAUTH_TOKEN": auth_token}
            self._client = AsyncAnthropic(auth_token=auth_token)
        else:
            self._agent_env = {"ANTHROPIC_API_KEY": api_key}
            self._client = AsyncAnthropic(api_key=api_key)

        # Une variable posée dans os.environ est globale au processus et
        # survit à l'éviction de l'instance : après une rotation OAuth → clé
        # d'API, CLAUDE_CODE_OAUTH_TOKEN gardait le jeton révoqué et restait
        # prioritaire côté CLI (tous les tours outillés en 401 pendant que
        # test() répondait ok). On purge les deux variables pour que
        # l'environnement ne contredise jamais la configuration courante —
        # et qu'un secret retiré de la base ne subsiste pas en clair dans
        # chaque sous-processus engendré.
        for var in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"):
            os.environ.pop(var, None)

        # Bascule mémorisée : si l'API Messages refuse ces identifiants en
        # 401 (jeton OAuth aux droits CLI seulement), tous les tours —
        # outillés ou non — repassent par claude_agent_sdk pour la durée de
        # vie de l'instance. Une rotation d'identifiants recrée l'instance
        # et retente le natif. Un 403 (permission/plafond de dépense) ne
        # bascule jamais : il peut être transitoire, et le CLI échouerait
        # pareil.
        self._force_agent_sdk_tools = False
        # Modèles dont le serveur a refusé ``temperature`` alors qu'ils ne
        # figurent pas dans _NO_SAMPLING_PREFIXES (id futur) : mémorisés pour
        # ne pas payer une requête condamnée + un retry à chaque appel.
        self._no_temperature_models: set[str] = set()

        logger.info("ClaudeProvider initialisé (auth=%s)", "oauth" if auth_token else "api_key")

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
        try:
            from ai.quota import set_usage
            usage = getattr(response, "usage", None)
            if usage is not None:
                set_usage(
                    input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                    output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                )
        except Exception:
            pass

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
        """Conversation turn with prompt caching and real message turns.

        Same auth fallback as the tooled path: a pure completion has no side
        effect, so a 401 can always be replayed through the CLI loop.
        """
        if self._force_agent_sdk_tools:
            text, _ = await self._tools_via_agent_sdk(prompt, model, [], max_turns=1)
            return text

        from anthropic import AuthenticationError

        system, messages = self._chat_payload(prompt)
        try:
            response = await self._create_message(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                temperature=temperature,
            )
        except AuthenticationError:
            self._switch_to_agent_sdk("complete_chat")
            text, _ = await self._tools_via_agent_sdk(prompt, model, [], max_turns=1)
            return text
        totals = {"in": 0, "out": 0}
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

        Falls back to the claude_agent_sdk CLI loop when the raw API rejects
        the configured credentials **in 401 and before any tool ran** (OAuth
        token with CLI-only entitlements — the failure shows on the very
        first request). An auth error *after* a tool executed propagates:
        replaying the turn would re-run its side effects.
        """
        if not tools:
            # complete_chat porte lui-même la bascule agent-SDK.
            text = await self.complete_chat(
                prompt, model=model, max_tokens=max_tokens, temperature=temperature,
            )
            return text, []
        if self._force_agent_sdk_tools:
            return await self._tools_via_agent_sdk(prompt, model, tools, max_turns)

        try:
            return await self._native_tool_loop(
                prompt=prompt,
                model=model,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
                max_turns=max_turns,
            )
        except _NativeAuthRejected:
            self._switch_to_agent_sdk("boucle d'outils")
            return await self._tools_via_agent_sdk(prompt, model, tools, max_turns)

    def _switch_to_agent_sdk(self, where: str) -> None:
        logger.warning(
            "L'API Messages refuse les identifiants (401, %s) — bascule sur "
            "claude_agent_sdk pour la durée de vie du provider.", where,
        )
        self._force_agent_sdk_tools = True

    async def _native_tool_loop(
        self,
        *,
        prompt,
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

        from anthropic import AuthenticationError

        system, messages = self._chat_payload(prompt)
        totals = {"in": 0, "out": 0}
        texts: list[str] = []
        calls: list[str] = []
        # Only the *newest* tool_result carries a cache breakpoint: markers
        # accumulate across iterations otherwise, and the API caps them at 4
        # per request.
        marked_result: dict | None = None

        try:
            for _ in range(max_turns):
                try:
                    response = await self._create_message(
                        model=model,
                        max_tokens=max_tokens,
                        system=system,
                        messages=messages,
                        tools=tool_defs,
                        temperature=temperature,
                    )
                except AuthenticationError:
                    if not calls:
                        # Rien n'a encore tourné : rejouer le tour via le CLI
                        # est sans risque. Après un premier outil exécuté, on
                        # laisse remonter — un replay renverrait l'email.
                        raise _NativeAuthRejected() from None
                    raise
                self._accumulate_usage(getattr(response, "usage", None), totals)

                turn_text = "".join(
                    b.text for b in response.content if b.type == "text"
                )
                if turn_text:
                    texts.append(turn_text)

                tool_uses = [b for b in response.content if b.type == "tool_use"]
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
                results[-1]["cache_control"] = dict(_CACHE_MARK)
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

    async def _tools_via_agent_sdk(
        self, prompt, model: str, tools: list, max_turns: int,
    ) -> tuple[str, list[str]]:
        """Legacy CLI loop, fed with the flattened two-string shape."""
        system_prompt, user_prompt = prompt.legacy_pair()
        mcp_server = self._build_mcp_server(tools)
        return await self._run_tool_loop(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            mcp_server=mcp_server,
            tool_names=[t.name for t in tools],
            max_turns=max_turns,
            env=self._agent_env,
        )

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
            "cache_control": dict(_CACHE_MARK),
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
                    block["cache_control"] = dict(_CACHE_MARK)
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

        Cache tokens count as input: they are consumed tokens, and on the
        tooled path they carry the bulk of the prompt (system + tools,
        reused iteration after iteration).
        """
        if usage is None:
            return
        totals["in"] += (
            int(getattr(usage, "input_tokens", 0) or 0)
            + int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
            + int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        )
        totals["out"] += int(getattr(usage, "output_tokens", 0) or 0)

    @staticmethod
    def _flush_usage(totals: dict) -> None:
        """Surface the accumulated usage to the quota tracker (best-effort)."""
        try:
            from ai.quota import set_usage
            if totals["in"] or totals["out"]:
                set_usage(input_tokens=totals["in"], output_tokens=totals["out"])
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

    # ── Tool-enabled completion (via MCP, Claude-specific) ───────
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
        """Tool-enabled completion.

        Accepts a list of provider-agnostic ``ModuleTool`` objects —
        each exposing ``name``, ``description``, ``to_json_schema()``
        and an async ``handler``. The Claude-specific MCP plumbing
        (server construction, tool loop, stream parsing) is an internal
        implementation detail and never leaks out.

        Returns ``(assistant_text, tool_names_called_in_order)``.
        """
        mcp_server = self._build_mcp_server(tools)
        return await self._run_tool_loop(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            mcp_server=mcp_server,
            tool_names=[t.name for t in tools],
            max_turns=max_turns,
            env=self._agent_env,
        )

    @staticmethod
    def _build_mcp_server(tools: list):
        """Wrap ``tools`` into an in-process Claude-MCP server.

        Encapsulated here so ``claude_agent_sdk`` never escapes the
        provider boundary. Returns ``None`` when ``tools`` is empty so
        the tool loop falls back to a plain text completion.
        """
        from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server

        if not tools:
            return None
        sdk_tools = [
            SdkMcpTool(
                name=t.name,
                description=t.description,
                input_schema=t.to_json_schema(),
                handler=t.handler,
            )
            for t in tools
        ]
        return create_sdk_mcp_server(
            name="vtuber_modules", version="1.0.0", tools=sdk_tools,
        )

    @staticmethod
    async def _run_tool_loop(
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        mcp_server,
        tool_names: list[str],
        max_turns: int,
        env: dict[str, str],
    ) -> tuple[str, list[str]]:
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
            query,
        )
        from claude_agent_sdk.types import ClaudeAgentOptions

        mcp_servers: dict = {}
        allowed_tools: list[str] = []
        if mcp_server is not None:
            mcp_servers["vtuber_modules"] = mcp_server
            allowed_tools = [f"mcp__vtuber_modules__{n}" for n in tool_names]

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=model,
            max_turns=max_turns,
            mcp_servers=mcp_servers,
            allowed_tools=allowed_tools,
            permission_mode="bypassPermissions",
            # Écrase os.environ dans la fusion faite par le transport, donc
            # l'identifiant transmis au CLI est toujours celui que la
            # configuration déclare à cet instant.
            env=dict(env),
        )

        async def _prompt_stream():
            yield {
                "type": "user",
                "session_id": "",
                "message": {"role": "user", "content": user_prompt},
                "parent_tool_use_id": None,
            }

        response_stream = query(prompt=_prompt_stream(), options=options)

        raw_text = ""
        calls: list[str] = []
        async for msg in response_stream:
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        raw_text += block.text
                    elif isinstance(block, ToolUseBlock):
                        logger.info(
                            "Claude called tool: %s (input=%s)",
                            block.name, str(block.input)[:200],
                        )
                        calls.append(block.name)
            elif isinstance(msg, ResultMessage):
                _record_claude_usage(msg)
        if calls:
            logger.info("Tools used in this turn: %s", calls)
        return raw_text, calls


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


def _record_claude_usage(result) -> None:
    """Remonte au compteur de quota l'usage de la boucle d'outils.

    ``ResultMessage`` clôt la session du CLI et porte le **cumul** de tous
    les tours. Sans cette remontée, le routeur ne trouvait rien dans le
    contexte d'usage et retombait sur son estimation de repli — la seule
    taille des prompts système et utilisateur. Or c'est de très loin le
    chemin le plus cher : les déclarations d'outils pèsent quelques
    milliers de tokens et sont renvoyées à *chaque* itération, jusqu'à
    ``max_turns``. Le poste dominant se comptait donc pour une fraction de
    lui-même, et le plafond se vérifiait contre ce chiffre minoré.

    Les tokens de cache sont comptés en entrée : ce sont bien des tokens
    consommés, et c'est par eux que passe l'essentiel d'un prompt outillé
    (prompt système + outils, réutilisés tour après tour).
    """
    try:
        from ai.quota import set_usage
        usage = getattr(result, "usage", None) or {}
        tokens_in = (
            int(usage.get("input_tokens", 0) or 0)
            + int(usage.get("cache_creation_input_tokens", 0) or 0)
            + int(usage.get("cache_read_input_tokens", 0) or 0)
        )
        tokens_out = int(usage.get("output_tokens", 0) or 0)
        if tokens_in or tokens_out:
            set_usage(input_tokens=tokens_in, output_tokens=tokens_out)
    except Exception:
        pass
