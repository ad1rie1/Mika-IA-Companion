"""Claude provider — uses the Anthropic Python SDK (anthropic.AsyncAnthropic).

For simple completions (no tools), we use the native Messages API directly.
The claude_agent_sdk is only used in client.py for MCP tool support.
"""

from __future__ import annotations

import logging
import os

from django.conf import settings

logger = logging.getLogger(__name__)


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

        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": content}],
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
