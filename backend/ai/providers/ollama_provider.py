"""Ollama provider — uses the official ``ollama`` Python SDK.

Runs models locally via the Ollama server (default: localhost:11434).
No API key required.
"""

from __future__ import annotations

import logging

from ai.providers._tool_loop import (
    AdaptateurOutils,
    AppelOutil,
    Issue,
    Reponse,
    contenu_json,
    executer_la_boucle,
)

logger = logging.getLogger(__name__)


class OllamaProvider:
    """Local model provider via the official ``ollama.AsyncClient``.

    The server address comes from ``ai.ollama.base_url`` in the dashboard
    (default: http://localhost:11434).

    Three class attributes are the whole seam ``OllamaCloudProvider``
    needs: the protocol is identical on both sides — same SDK, same
    ``/api/tags``, same tool shape — only the endpoint, the credentials
    and the generation budget differ. Subclassing keeps one tool loop
    rather than two that drift.
    """

    #: Config-key namespace holding this provider's endpoint + policy.
    CONFIG_PREFIX = "ai.ollama"
    DEFAULT_HOST = "http://localhost:11434"
    #: Cap applied when the config is unreadable — a config read can precede
    #: a reachable database, and the unbounded default is what this prevents.
    FALLBACK_MAX_REPLY_TOKENS = 768

    def __init__(self):
        try:
            from ollama import AsyncClient
        except ImportError:
            raise ImportError(
                "Le provider Ollama nécessite le package 'ollama'. "
                "Installez-le avec : pip install ollama"
            )

        from configs.service import config_service
        host = config_service.get(
            f"{self.CONFIG_PREFIX}.base_url", default=self.DEFAULT_HOST
        )
        if not host:
            host = self.DEFAULT_HOST

        self._host = host
        self._client = AsyncClient(host=host, headers=self._headers())

        logger.info("%s initialisé (host=%s)", type(self).__name__, host)

    def _headers(self) -> dict:
        """Extra HTTP headers for every call. A local server needs none."""
        return {}

    # -- Generation policy ---------------------------------------------------
    #
    # Two knobs that decide whether a local model answers at all.
    #
    # `think`: the reasoning models now shipped by Ollama (gemma4, qwen3,
    # deepseek-r1) reason by DEFAULT, and that reasoning is generated before
    # the first word of the reply. Measured on gemma4:12b, RTX 3060, fully
    # in VRAM at ~30 tok/s: "coucou" answered in 1.5 s with thinking off and
    # 27 s with it on. With a real system prompt and 34 tool declarations the
    # same turn ran past 2000 generated tokens and was still going when the
    # 120 s timeout fired — every reply was the fallback.
    #
    # `num_predict`: the caller's default `max_tokens=4096` was handed
    # straight through, so a model that does not stop has a 4096-token rope.
    # At the ~19 tok/s a long context degrades to, that is 219 s — a turn
    # that CANNOT finish inside any sane timeout. The cap is the belt: even
    # with thinking re-enabled, a turn is bounded.

    def _generation_options(self, max_tokens: int, temperature: float) -> dict:
        from configs.service import config_service

        cap = max_tokens
        try:
            cap = min(max_tokens, int(
                config_service.get(f"{self.CONFIG_PREFIX}.max_reply_tokens")
            ))
        except Exception:
            # An unreadable config must not silently restore the unbounded
            # behaviour this cap exists to prevent.
            cap = min(max_tokens, self.FALLBACK_MAX_REPLY_TOKENS)
        return {"num_predict": cap, "temperature": temperature}

    def _thinking(self) -> bool:
        from configs.service import config_service

        try:
            return bool(config_service.get(f"{self.CONFIG_PREFIX}.thinking"))
        except Exception:
            return False

    async def _chat(self, **kwargs):
        """Call the SDK, degrading gracefully when `think` is unsupported.

        Not every model accepts the parameter, and older Ollama servers
        reject it outright. A provider that cannot talk to half the local
        models is worse than one that occasionally lets a model reason.

        Seul un refus *du paramètre* est repris : ``think`` est toujours
        envoyé, donc l'ancienne garde « pas de think → relever » ne
        filtrait rien, et n'importe quelle exception — timeout, connexion
        refusée, modèle absent — rejouait la génération entière une seconde
        fois, au double du prix, en ne laissant remonter que la seconde
        erreur.
        """
        try:
            return await self._client.chat(**kwargs)
        except Exception as exc:
            if "think" not in kwargs or not _is_think_rejection(exc):
                raise
            logger.debug(
                "Ollama rejected think=%s (%s) — retrying without it",
                kwargs.get("think"), exc,
            )
            kwargs.pop("think", None)
            return await self._client.chat(**kwargs)

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        attachments: list | None = None,
    ) -> str:
        user_message: dict = {"role": "user", "content": user_prompt}

        # Ollama supports vision when the selected model is multimodal
        # (llava, bakllava, llama3.2-vision, qwen2-vl, ...). The SDK
        # takes base64-encoded bytes via the `images` message field.
        # If the model is not vision-capable, Ollama will simply ignore
        # the images — we log it so it's visible but don't fail.
        if attachments:
            image_b64s = [
                a.data for a in attachments
                if getattr(a, "category", None) == "image" and a.data
            ]
            if image_b64s:
                user_message["images"] = image_b64s
                logger.debug(
                    "OllamaProvider: sending %d image(s) to model=%s",
                    len(image_b64s), model,
                )

        response = await self._chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                user_message,
            ],
            think=self._thinking(),
            options=self._generation_options(max_tokens, temperature),
        )

        _record_ollama_usage(response)
        return response.message.content or ""

    async def complete_chat(
        self,
        prompt,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Structured turn — the local path's real win is the KV cache.

        Ollama reuses the KV cache of the previous request as long as the
        prompt prefix is byte-identical. The flattened form rebuilt the
        whole prompt every turn (volatile system + re-serialized history),
        so a slow local model re-prefilled everything at ~19 tok/s; with
        the stable system + history prefix, only the newest exchange and
        the per-turn state get prefilled.
        """
        messages = [{"role": "system", "content": prompt.system_stable}]
        messages.extend(prompt.chat_messages())

        response = await self._chat(
            model=model,
            messages=messages,
            think=self._thinking(),
            options=self._generation_options(max_tokens, temperature),
        )

        _record_ollama_usage(response)
        return response.message.content or ""

    async def list_models(self) -> list[dict]:
        """List models available on the configured Ollama server.

        The ollama SDK exposes this, but some releases disagree on the
        return shape; we go through plain HTTP to stay version-agnostic
        and keep a single representation.
        """
        import httpx
        url = f"{self._host.rstrip('/')}/api/tags"
        async with httpx.AsyncClient(timeout=10.0, headers=self._headers()) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        out = []
        for m in data.get("models", []):
            mid = m.get("name") or m.get("model") or ""
            if mid:
                out.append({"id": mid, "label": mid})
        return out

    async def test(self) -> dict:
        from ai.providers import default_test
        return await default_test(self)

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
        """Tour outillé structuré — la boucle générique, amorcée sur de vrais tours.

        C'est ici que le cache KV compte le plus : la boucle rappelle le
        modèle à chaque aller-retour d'outil, et un préfixe reconstruit à
        chaque fois se re-préremplit intégralement, déclarations d'outils
        comprises, aux ~19 tok/s auxquels un contexte long descend.

        If the selected model isn't tool-capable, Ollama returns a plain
        response with no ``tool_calls`` — the loop returns the text as-is,
        so the call degrades gracefully instead of looping.
        """
        messages = [{"role": "system", "content": prompt.system_stable}]
        messages.extend(prompt.chat_messages())
        return await executer_la_boucle(
            _AdaptateurOllama(
                self, messages=messages, model=model, tools=tools,
                temperature=temperature,
            ),
            tools=tools,
            max_tokens=max_tokens,
            max_turns=max_turns,
        )


class _AdaptateurOllama(AdaptateurOutils):
    """La boucle d'outils vue par ``/api/chat``.

    La politique de génération (``think``, ``num_predict``) s'applique à
    chaque aller-retour, comme sur l'appel simple.
    """

    LABEL = "Ollama"

    def __init__(
        self, provider: OllamaProvider, *, messages: list[dict], model: str,
        tools: list, temperature: float,
    ) -> None:
        self._provider = provider
        self._model = model
        self._temperature = temperature
        # Le fil appartient à l'appelant : la boucle y empile ses tours.
        self.fil = list(messages)
        self._serialises = _serialize_tools_for_ollama(tools) if tools else None

    async def appeler(self, max_tokens: int):
        kwargs = {
            "model": self._model,
            "messages": self.fil,
            "think": self._provider._thinking(),
            "options": self._provider._generation_options(max_tokens, self._temperature),
        }
        if self._serialises:
            kwargs["tools"] = self._serialises
        response = await self._provider._chat(**kwargs)
        _record_ollama_usage(response)
        return response

    def lire(self, response) -> Reponse:
        msg = response.message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            return Reponse(texte=msg.content or "")
        # Ollama already parses arguments to a dict — the loop guards the
        # string case anyway.
        return Reponse(appels=[
            AppelOutil(name=tc.function.name, arguments=tc.function.arguments)
            for tc in tool_calls
        ])

    def rejouer_le_tour(self, response, reponse: Reponse) -> None:
        msg = response.message
        self.fil.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in (getattr(msg, "tool_calls", None) or [])
            ],
        })

    def rendre_les_resultats(self, issues: list[Issue]) -> None:
        for issue in issues:
            self.fil.append(_tool_message(issue.appel.name, contenu_json(issue)))


def _is_think_rejection(exc: BaseException) -> bool:
    """Le serveur a-t-il refusé le paramètre ``think`` lui-même ?

    Compte ce qui désigne le paramètre : un message qui le nomme, ou un 400
    du serveur — un paramètre inconnu est une requête malformée, tout autre
    statut (404 modèle absent, 500, connexion) dit autre chose et remonte
    tel quel.
    """
    if "think" in str(exc).lower():
        return True
    try:
        from ollama import ResponseError
    except ImportError:
        return False
    return isinstance(exc, ResponseError) and getattr(exc, "status_code", None) == 400


def _tool_message(name: str, content: str) -> dict:
    """Le tour ``tool`` tel que le SDK l'attend.

    Le champ du SDK est ``tool_name`` : envoyé sous ``name``, pydantic
    l'ignorait sans un mot et le modèle recevait un résultat orphelin, sans
    savoir quel outil avait répondu. Et un contenu vide voyage comme un
    texte explicite : un ``{"role": "tool"}`` sans contenu est un message
    sans résultat, que le modèle lit comme un outil qui n'a rien dit.
    """
    return {
        "role": "tool",
        "tool_name": name,
        "content": content or "(résultat vide)",
    }


def _record_ollama_usage(response) -> None:
    """Surface Ollama's prompt_eval_count / eval_count to the quota tracker.

    Ollama exposes these on the top-level response object (not on
    ``message``), and only after the full response is generated.
    """
    try:
        from ai.quota import set_usage
        tokens_in = int(getattr(response, "prompt_eval_count", 0) or 0)
        tokens_out = int(getattr(response, "eval_count", 0) or 0)
        if tokens_in or tokens_out:
            set_usage(input_tokens=tokens_in, output_tokens=tokens_out)
    except Exception:
        pass


def _serialize_tools_for_ollama(tools: list) -> list[dict]:
    """Convert ModuleTool list → Ollama ``tools`` parameter shape.

    Same shape as OpenAI's ``tools`` param — Ollama deliberately mirrored
    it — but kept local to this module so it doesn't drift if Ollama
    diverges later.
    """
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
