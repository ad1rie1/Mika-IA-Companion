"""Gemini provider — uses the official ``google-genai`` Python SDK.

The previous ``google-generativeai`` package is deprecated in favour of
``google-genai`` (``from google import genai``). The new SDK ships a
unified ``Client`` with an async companion at ``client.aio``, which we
use directly instead of offloading the sync API to a thread.

The SDK handles Google's endpoint, so no base URL is required.

Le tour outillé part d'un ``ChatPrompt`` traduit en ``contents`` et entre
dans la boucle générique (``_tool_loop``) par ``_AdaptateurGemini``. Le fil
de départ décide de tout ce qui compte (préfixe cacheable, fidélité des
rôles) ; la boucle, elle, ne fait qu'y empiler ses allers-retours.
"""

from __future__ import annotations

import logging

from old.backend.ai.providers._tool_loop import (
    AdaptateurOutils,
    AppelOutil,
    Issue,
    Reponse,
    executer_la_boucle,
)
from old.backend.utils.degradation import degradations

logger = logging.getLogger(__name__)


def _contents_from_chat_prompt(prompt) -> list:
    """Fil de départ pour un ``ChatPrompt``.

    Gemini nomme ``model`` ce que le reste du dépôt appelle ``assistant``, et
    n'accepte aucun autre rôle. Le premier élément de ``contents`` ne peut pas
    être un tour ``model`` — ``chat_messages()`` garantit déjà l'inverse (il
    ouvre sur un marqueur de reprise quand l'historique commence par Mika),
    donc rien n'est re-vérifié ici.
    """
    from google.genai import types

    return [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part.from_text(text=m["content"])],
        )
        for m in prompt.chat_messages()
    ]


class GeminiProvider:
    """Google Gemini via the ``google-genai`` SDK."""

    def __init__(self):
        try:
            from google import genai
        except ImportError as exc:
            raise ImportError(
                "Le provider Gemini nécessite le package 'google-genai' "
                "(l'ancien 'google-generativeai' est deprecated). "
                "Installez-le avec : pip install google-genai"
            ) from exc

        from old.backend.configs.service import config_service

        api_key = config_service.get("ai.gemini.api_key", default="") or None
        if not api_key:
            raise ValueError(
                "GeminiProvider nécessite ai.gemini.api_key "
                "(éditeur Configuration > Fournisseur IA)."
            )

        # The async surface lives on ``client.aio`` — same API shape as
        # the sync one, so we stash it directly for callers.
        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        logger.info("GeminiProvider initialisé (SDK google-genai)")

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        attachments: list | None = None,
    ) -> str:
        from google.genai import types

        parts: list = []
        if attachments:
            import base64
            for att in attachments:
                if getattr(att, "category", None) == "image":
                    parts.append(types.Part.from_bytes(
                        data=base64.b64decode(att.data),
                        mime_type=att.media_type,
                    ))
        parts.append(types.Part.from_text(text=user_prompt))

        config = types.GenerateContentConfig(
            system_instruction=system_prompt or None,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        resp = await self._client.aio.models.generate_content(
            model=model,
            contents=parts,
            config=config,
        )
        _record_gemini_usage(resp)
        return (resp.text or "").strip()

    async def complete_chat(
        self,
        prompt,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> str:
        """Tour structuré : ``system_instruction`` + de vrais tours."""
        from google.genai import types

        contents = _contents_from_chat_prompt(prompt)

        config = types.GenerateContentConfig(
            system_instruction=prompt.system_stable or None,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        resp = await self._client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
        _record_gemini_usage(resp)
        return (resp.text or "").strip()

    async def list_models(self) -> list[dict]:
        """List Gemini models that support content generation."""
        out: list[dict] = []
        pager = await self._client.aio.models.list()
        async for m in pager:
            # New SDK exposes ``supported_actions`` instead of the
            # deprecated ``supported_generation_methods``.
            actions = getattr(m, "supported_actions", None) or []
            if actions and "generateContent" not in actions:
                continue
            # ``name`` is already the bare model id (e.g. "gemini-2.0-flash")
            # or prefixed by "models/" depending on the SDK minor version.
            raw = m.name or ""
            mid = raw.split("/", 1)[-1] if "/" in raw else raw
            if not mid:
                continue
            label = getattr(m, "display_name", None) or mid
            out.append({"id": mid, "label": label})
        out.sort(key=lambda x: x["id"])
        return out

    async def test(self) -> dict:
        from old.backend.ai.providers import default_test
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

        C'est le tour le plus cher du système : les déclarations d'outils
        repartent à chaque aller-retour de la boucle. Amorcée sur
        l'aplatissement, chaque itération présentait un préfixe différent ;
        ici ``system_instruction`` et les tours d'historique ne bougent ni
        pendant la boucle, ni d'un tour à l'autre.
        """
        return await executer_la_boucle(
            _AdaptateurGemini(
                self,
                system_instruction=prompt.system_stable or None,
                contents=_contents_from_chat_prompt(prompt),
                model=model,
                tools=tools,
                temperature=temperature,
            ),
            tools=tools,
            max_tokens=max_tokens,
            max_turns=max_turns,
        )


class _AdaptateurGemini(AdaptateurOutils):
    """La boucle d'outils vue par ``generate_content``.

    Gemini uses a different shape than OpenAI: tools are wrapped in
    ``types.Tool(function_declarations=[...])`` and tool results are sent
    back as ``Part.from_function_response``, all the results of one round
    in a single ``user`` content.
    """

    LABEL = "Gemini"

    def __init__(
        self, provider: GeminiProvider, *, system_instruction: str | None,
        contents: list, model: str, tools: list, temperature: float,
    ) -> None:
        from google.genai import types

        self._client = provider._client
        self._system_instruction = system_instruction
        self._model = model
        self._temperature = temperature
        # Le fil appartient à l'appelant : la boucle y empile ses allers-retours.
        self.fil = list(contents)
        declarations = [
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters=t.to_json_schema(),
            )
            for t in tools
        ]
        self._tools = (
            [types.Tool(function_declarations=declarations)] if declarations else None
        )

    async def appeler(self, max_tokens: int):
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=self._system_instruction,
            temperature=self._temperature,
            max_output_tokens=max_tokens,
            tools=self._tools,
        )
        resp = await self._client.aio.models.generate_content(
            model=self._model,
            contents=self.fil,
            config=config,
        )
        _record_gemini_usage(resp)
        return resp

    def lire(self, resp) -> Reponse:
        function_calls = getattr(resp, "function_calls", None) or []
        if not function_calls:
            return Reponse(texte=(resp.text or "").strip())
        return Reponse(appels=[
            AppelOutil(name=fc.name, arguments=dict(fc.args) if fc.args else {})
            for fc in function_calls
        ])

    def rejouer_le_tour(self, resp, reponse: Reponse) -> None:
        # Replay the model turn (the Content holding function_call parts).
        try:
            self.fil.append(resp.candidates[0].content)
        except (AttributeError, IndexError) as exc:
            degradations.record(
                "ai.providers.gemini._AdaptateurGemini.rejouer_le_tour model turn", exc,
            )

    def rendre_les_resultats(self, issues: list[Issue]) -> None:
        from google.genai import types

        parts = [
            types.Part.from_function_response(
                name=issue.appel.name, response=_charge_utile(issue),
            )
            for issue in issues
        ]
        self.fil.append(types.Content(role="user", parts=parts))


def _charge_utile(issue: Issue) -> dict:
    """La ``response`` d'une ``function_response`` : toujours un dict JSON-able."""
    import json

    if issue.erreur is not None:
        payload: dict = {"error": issue.erreur}
    elif isinstance(issue.resultat, dict):
        payload = issue.resultat
    else:
        payload = {"result": issue.resultat}
    try:
        json.dumps(payload, default=str)
    except (TypeError, ValueError):  # ValueError : référence circulaire
        payload = {"result": str(payload)}
    return payload


def _record_gemini_usage(resp) -> None:
    """Surface Gemini usage_metadata to the quota tracker."""
    try:
        from old.backend.ai.quota import set_usage
        usage = getattr(resp, "usage_metadata", None)
        if usage is not None:
            set_usage(
                input_tokens=int(getattr(usage, "prompt_token_count", 0) or 0),
                output_tokens=int(getattr(usage, "candidates_token_count", 0) or 0),
            )
    except Exception as exc:
        degradations.record("ai.providers.gemini usage", exc)
