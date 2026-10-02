"""Fournisseur compatible OpenAI (``/chat/completions``) : OpenAI, GLM, vLLM, Groq…

Contrat :

- un seul message système : le préfixe stable, puis le bloc volatile s'il ne
  voyage pas déjà en tête du dernier tour utilisateur (certains serveurs
  compatibles n'acceptent qu'un système, au début) ;
- appels d'outils de l'assistant → ``tool_calls`` (arguments en JSON) ; chaque
  résultat → un tour ``tool`` ; une erreur voyage comme ``{"error": …}``, un
  résultat vide comme un texte explicite ;
- déclarations triées par nom : préfixe stable pour le cache automatique ;
- ``max_tokens`` d'abord ; un 400 qui refuse ce **nom** → ``max_completion_tokens``
  (un 400 sur sa valeur, « trop grand », ne fait rien changer) ; un 400 qui nomme
  ``temperature`` → sans elle ; chaque refus est mémorisé par modèle
  (``ParamMemo``), une reprise au plus par paramètre ;
- au premier plan, une seule nouvelle tentative du SDK au lieu de deux ;
- ``finish_reason == "length"`` avec un appel entamé → ``truncated_tool_call`` ;
  des arguments illisibles → ``{"_raw": texte}``, que la validation du runtime
  renvoie au modèle comme une erreur ;
- ``input_tokens`` exclut les jetons lus (``cache_read``) ou écrits
  (``cache_write``) en cache, comptés à part.

Les aides de forme ``function`` servent aussi au fournisseur Ollama.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from mika.kernel.prompt import CONTEXT_FOOTER, CONTEXT_HEADER
from mika.ports.llm import LLMRequest, LLMResponse, Message, ToolCall, ToolDecl, Usage

try:
    import openai
except ImportError:  # pragma: no cover — extra « llm » absent
    openai = None

log = logging.getLogger("mika.llm.openai")

GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
RAW_ARGS_KEY = "_raw"
EMPTY_TOOL_RESULT = "(résultat vide)"

_FINISH = {
    "stop": "end",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}


# ── Aides partagées (forme « function ») ──────────────────────────────────


def plain(value: Any) -> Any:
    """Copie sérialisable en JSON : mappings → dict, séquences → list, ordre conservé."""
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def volatile_system(req: LLMRequest) -> str:
    """Le bloc volatile à ajouter au système ; vide s'il voyage déjà dans le dernier tour utilisateur."""
    volatile = req.system_volatile
    if not volatile.strip():
        return ""
    framed = f"{CONTEXT_HEADER}\n{volatile}\n{CONTEXT_FOOTER}"
    for m in reversed(req.messages):
        if m.role == "user":
            return "" if framed in m.content else volatile
    return volatile


def system_text(req: LLMRequest) -> str:
    """Le système en un texte : préfixe stable intact, puis le volatile éventuel."""
    return "\n\n".join(p for p in (req.system_stable, volatile_system(req)) if p.strip())


def function_tools(tools: Sequence[ToolDecl]) -> list[dict[str, Any]]:
    """Déclarations au format ``function``, triées par nom."""
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": plain(t.schema)},
        }
        for t in sorted(tools, key=lambda t: t.name)
    ]


def decode_args(raw: Any) -> dict[str, Any]:
    """Arguments d'un appel : un objet JSON, sinon ``{"_raw": texte}`` — jamais d'exception."""
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return plain(raw)
    if not isinstance(raw, str):
        return {RAW_ARGS_KEY: str(raw)}
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {RAW_ARGS_KEY: raw}
    if value is None:
        return {}
    return plain(value) if isinstance(value, Mapping) else {RAW_ARGS_KEY: raw}


def encode_args(args: Mapping[str, Any]) -> str:
    """Arguments rejoués au modèle ; des arguments illisibles repartent tels qu'il les a écrits."""
    raw = args.get(RAW_ARGS_KEY) if len(args) == 1 else None
    return raw if isinstance(raw, str) else json.dumps(plain(args), ensure_ascii=False)


def tool_content(m: Message) -> str:
    """Contenu d'un tour ``tool`` : jamais vide ; une erreur voyage comme ``{"error": …}``."""
    text = m.content if m.content.strip() else EMPTY_TOOL_RESULT
    return json.dumps({"error": text}, ensure_ascii=False) if m.is_error else text


def new_call_id() -> str:
    """Identifiant d'appel quand le serveur n'en donne pas : unique, il sert de clé de dédoublonnage."""
    return f"call_{uuid.uuid4().hex}"


def rejects(exc: BaseException, param: str) -> bool:
    """Un 400 qui nomme ``param`` : le serveur refuse ce paramètre."""
    return getattr(exc, "status_code", None) == 400 and param in str(exc)


#: ce qu'un serveur dit quand il ne connaît pas un paramètre (et non quand sa valeur déplaît)
_UNSUPPORTED = ("unsupported", "not supported", "unknown parameter", "unrecognized", "unexpected keyword",
                "extra inputs are not permitted", "max_completion_tokens")


def rejects_name(exc: BaseException, param: str) -> bool:
    """Un 400 qui refuse le **nom** ``param`` (« Unsupported parameter: 'max_tokens' … use
    'max_completion_tokens' ») — pas sa valeur (« max_tokens is too large ») : sinon
    une valeur trop grande faisait changer de paramètre à vie."""
    text = str(exc).lower()
    return rejects(exc, param) and any(marker in text for marker in _UNSUPPORTED)


#: tentatives du SDK pour un appel au premier plan (sa valeur par défaut : 2)
FOREGROUND_RETRIES = 1


def count(obj: Any, attr: str) -> int:
    value = getattr(obj, attr, 0) if obj is not None else 0
    return value if isinstance(value, int) else 0


# ── Le fournisseur ────────────────────────────────────────────────────────


class ParamMemo:
    """Ce que chaque modèle a refusé : le nom de son plafond de sortie, ``temperature``."""

    def __init__(self) -> None:
        #: modèle → paramètre de plafond accepté (absent = ``max_tokens``)
        self.token_param: dict[str, str] = {}
        #: modèles qui refusent ``temperature``
        self.no_temperature: set[str] = set()


def chat_messages(req: LLMRequest) -> list[dict[str, Any]]:
    """La conversation au format ``/chat/completions``."""
    out: list[dict[str, Any]] = []
    system = system_text(req)
    if system:
        out.append({"role": "system", "content": system})
    for m in req.messages:
        if m.role == "user" and m.images:
            parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
            parts += [{"type": "image_url", "image_url": {"url": f"data:{i.mime};base64,{i.data}"}} for i in m.images]
            out.append({"role": "user", "content": parts})
        elif m.role == "user":
            out.append({"role": "user", "content": m.content})
        elif m.role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.content}
            if m.tool_calls:
                msg["tool_calls"] = [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name, "arguments": encode_args(c.args)}}
                    for c in m.tool_calls
                ]
            out.append(msg)
        elif m.role == "tool":
            out.append({"role": "tool", "tool_call_id": m.tool_call_id or "", "content": tool_content(m)})
        else:
            log.warning("rôle de message inconnu ignoré : %r", m.role)
    return out


class OpenAICompatBackend:
    """Un endpoint ``/chat/completions`` : un appel par requête, aucune boucle."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str | None = None,
        temperature: float | None = None,
        name: str = "openai",
        client: Any = None,
    ) -> None:
        if client is None:
            if openai is None:
                raise RuntimeError("OpenAICompatBackend exige le paquet « openai » (extra « llm »).")
            client = openai.AsyncOpenAI(api_key=api_key or None, base_url=base_url or None)
        self.name = name
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.memo = ParamMemo()
        self._client = client

    def payload(self, req: LLMRequest) -> dict[str, Any]:
        """Le corps de requête, hors plafond de sortie et ``temperature`` (négociés à l'envoi)."""
        body: dict[str, Any] = {"model": self.model, "messages": chat_messages(req)}
        if req.tools:
            body["tools"] = function_tools(req.tools)
        return body

    async def complete(self, req: LLMRequest) -> LLMResponse:
        client = self._client
        with_options = getattr(client, "with_options", None)
        if req.priority == 0 and callable(with_options):  # la passerelle borne l'appel et sait se replier
            client = with_options(max_retries=FOREGROUND_RETRIES)
        return self._read(await self._create(self.payload(req), req.max_tokens, client))

    async def _create(self, body: dict[str, Any], max_tokens: int, client: Any = None) -> Any:
        client = client if client is not None else self._client
        memo = self.memo
        token_param = memo.token_param.get(self.model, "max_tokens")
        send_temperature = self.temperature is not None and self.model not in memo.no_temperature
        renamed = dropped = False
        while True:
            kwargs = {**body, token_param: max_tokens}
            if send_temperature:
                kwargs["temperature"] = self.temperature
            try:
                return await client.chat.completions.create(**kwargs)
            except Exception as exc:
                if token_param == "max_tokens" and not renamed and rejects_name(exc, "max_tokens"):
                    renamed = True
                    token_param = memo.token_param[self.model] = "max_completion_tokens"
                    log.info("%s refuse « max_tokens » : « max_completion_tokens » mémorisé", self.model)
                    continue
                if send_temperature and not dropped and rejects(exc, "temperature"):
                    dropped, send_temperature = True, False
                    memo.no_temperature.add(self.model)
                    log.info("%s refuse « temperature » : mémorisé, plus jamais envoyée", self.model)
                    continue
                raise

    def _read(self, resp: Any) -> LLMResponse:
        usage = _usage(getattr(resp, "usage", None))
        model = getattr(resp, "model", None) or self.model
        choices = getattr(resp, "choices", None) or []
        if not choices:
            return LLMResponse("", usage=usage, model=model)
        choice = choices[0]
        msg = choice.message
        finish = getattr(choice, "finish_reason", None)
        text = getattr(msg, "content", None) or ""
        raw_calls = list(getattr(msg, "tool_calls", None) or [])
        if finish == "length" and raw_calls:
            return LLMResponse(text, stop="max_tokens", usage=usage, model=model, truncated_tool_call=True)
        refusal = getattr(msg, "refusal", None)
        if refusal or finish == "content_filter":
            log.warning("%s refuse de répondre (finish=%s) : %s", model, finish, refusal)
            return LLMResponse(text, stop="refusal", usage=usage, model=model)
        calls = tuple(
            ToolCall(tc.id or new_call_id(), tc.function.name, decode_args(tc.function.arguments))
            for tc in raw_calls
            if getattr(tc, "function", None) is not None
        )
        stop = "tool_use" if calls else _FINISH.get(finish or "", "end")
        return LLMResponse(text, calls, stop, usage, model)


def _usage(u: Any) -> Usage:
    details = getattr(u, "prompt_tokens_details", None) if u is not None else None
    cached = count(details, "cached_tokens")
    written = count(details, "cache_write_tokens")
    return Usage(
        input_tokens=max(0, count(u, "prompt_tokens") - cached - written),
        output_tokens=count(u, "completion_tokens"),
        cache_read=cached,
        cache_write=written,
    )
