"""Fournisseurs Ollama : le serveur local, et Ollama Cloud (https://ollama.com, clé en bearer).

Même protocole des deux côtés (``/api/chat``, outils au format ``function``) ;
seuls l'hôte, l'authentification et le plafond de réponse diffèrent.

Contrat :

- ``think`` coupé par défaut : un modèle de raisonnement réfléchit sinon avant
  le premier mot de sa réponse (mesuré sur gemma4:12b : 1,5 s sans, 27 s avec) ;
- ``num_predict`` = le plus petit de ``max_reply_tokens`` et du ``max_tokens``
  de la requête : un modèle qui ne s'arrête pas ne tient pas un tour ouvert —
  sauf quand la passerelle redemande une sortie coupée (``RETRY_AFTER_CUT``) :
  le plafond propre est alors levé, sinon la reprise serait coupée au même mot ;
- un délai explicite côté client HTTP (``HTTP_TIMEOUT_S``) : la passerelle borne
  l'appel, mais un serveur muet ne doit pas tenir une connexion sans limite ;
- un refus du paramètre ``think`` (message qui le nomme, ou 400) est rejoué une
  fois sans lui — aucune autre erreur n'est rejouée ;
- résultats d'outils sous ``tool_name`` (le champ du SDK : ``name`` serait
  ignoré sans un mot), jamais vides ; une erreur voyage comme ``{"error": …}`` ;
- Ollama ne numérote pas ses appels : chacun reçoit un identifiant unique ;
- ``done_reason == "length"`` avec un appel d'outil → ``truncated_tool_call``.
"""

from __future__ import annotations

import logging
from typing import Any

from mika.adapters.llm.openai_compat import (
    decode_args,
    function_tools,
    new_call_id,
    plain,
    system_text,
    tool_content,
)
from mika.ports.llm import RETRY_AFTER_CUT, LLMRequest, LLMResponse, ToolCall, Usage

try:
    import ollama
except ImportError:  # pragma: no cover — extra « llm » absent
    ollama = None

log = logging.getLogger("mika.llm.ollama")

#: délai du client HTTP (secondes) : au-delà de tout délai de la passerelle, jamais infini
HTTP_TIMEOUT_S = 900.0


def ollama_messages(req: LLMRequest) -> list[dict[str, Any]]:
    """La conversation au format ``/api/chat``."""
    out: list[dict[str, Any]] = []
    system = system_text(req)
    if system:
        out.append({"role": "system", "content": system})
    for m in req.messages:
        if m.role == "user":
            user: dict[str, Any] = {"role": "user", "content": m.content}
            if m.images:
                user["images"] = [i.data for i in m.images]
            out.append(user)
        elif m.role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.content}
            if m.tool_calls:
                msg["tool_calls"] = [
                    {"function": {"name": c.name, "arguments": plain(c.args)}} for c in m.tool_calls
                ]
            out.append(msg)
        elif m.role == "tool":
            msg = {"role": "tool", "content": tool_content(m)}
            if m.name:
                msg["tool_name"] = m.name
            out.append(msg)
        else:
            log.warning("rôle de message inconnu ignoré : %r", m.role)
    return out


class OllamaBackend:
    """Un serveur Ollama : un appel ``/api/chat`` par requête, aucune boucle."""

    #: il ne sait pas différer des outils (pas de recherche d'outils) : tous partent déclarés
    defers_tools = False

    def __init__(
        self,
        model: str,
        *,
        host: str = "http://localhost:11434",
        think: bool = False,
        max_reply_tokens: int = 768,
        temperature: float | None = None,
        name: str = "ollama",
        client: Any = None,
    ) -> None:
        if max_reply_tokens < 1:
            raise ValueError(f"max_reply_tokens doit être positif (reçu {max_reply_tokens})")
        self.name = name
        self.model = model
        self.host = host
        self.think = think
        self.max_reply_tokens = max_reply_tokens
        self.temperature = temperature
        if client is None:
            if ollama is None:
                raise RuntimeError(f"{type(self).__name__} exige le paquet « ollama » (extra « llm »).")
            client = ollama.AsyncClient(host=host, headers=self.headers, timeout=HTTP_TIMEOUT_S)
        self._client = client

    @property
    def headers(self) -> dict[str, str]:
        """En-têtes HTTP de chaque appel ; un serveur local n'en demande aucun."""
        return {}

    def payload(self, req: LLMRequest) -> dict[str, Any]:
        """Les arguments de ``AsyncClient.chat``."""
        cap = req.max_tokens if req.meta.get(RETRY_AFTER_CUT) else min(req.max_tokens, self.max_reply_tokens)
        options: dict[str, Any] = {"num_predict": cap}
        if self.temperature is not None:
            options["temperature"] = self.temperature
        body: dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages(req),
            "think": self.think,
            "options": options,
        }
        if req.tools:
            body["tools"] = function_tools(req.tools)
        return body

    async def complete(self, req: LLMRequest) -> LLMResponse:
        return self._read(await self._chat(self.payload(req)))

    async def _chat(self, body: dict[str, Any]) -> Any:
        try:
            return await self._client.chat(**body)
        except Exception as exc:
            if "think" not in body or not self._rejects_think(exc):
                raise
            log.info("%s refuse think=%s (%s) : nouvel essai sans", self.model, body["think"], exc)
            return await self._client.chat(**{k: v for k, v in body.items() if k != "think"})

    def _rejects_think(self, exc: BaseException) -> bool:
        """Le serveur refuse-t-il le paramètre ``think`` lui-même ?

        Un message qui nomme la réflexion (le nom du modèle retiré : un modèle
        « …-thinking » absent n'est pas un refus du paramètre), ou un 400 —
        un paramètre inconnu est une requête malformée. Tout autre statut
        (404, 500, connexion) dit autre chose et remonte tel quel.
        """
        message = str(exc).lower().replace(self.model.lower(), "")
        if "think" in message:
            return True
        return ollama is not None and isinstance(exc, ollama.ResponseError) and exc.status_code == 400

    def _read(self, resp: Any) -> LLMResponse:
        msg = getattr(resp, "message", None)
        text = getattr(msg, "content", None) or ""
        raw_calls = list(getattr(msg, "tool_calls", None) or [])
        usage = Usage(
            input_tokens=int(getattr(resp, "prompt_eval_count", 0) or 0),
            output_tokens=int(getattr(resp, "eval_count", 0) or 0),
        )
        model = getattr(resp, "model", None) or self.model
        cut = getattr(resp, "done_reason", None) == "length"
        if cut and raw_calls:
            return LLMResponse(text, stop="max_tokens", usage=usage, model=model, truncated_tool_call=True)
        calls = tuple(
            ToolCall(new_call_id(), tc.function.name, decode_args(tc.function.arguments)) for tc in raw_calls
        )
        stop = "max_tokens" if cut else ("tool_use" if calls else "end")
        return LLMResponse(text, calls, stop, usage, model)


class OllamaCloudBackend(OllamaBackend):
    """Ollama hébergé : clé d'API en bearer, plafond de réponse plus large (génération rapide).

    Les identifiants de modèles hébergés ne portent pas de suffixe ``-cloud``
    (``gpt-oss:120b``, ``kimi-k3``…) : cette forme désigne le relais par un
    serveur local. Sans clé, aucun en-tête n'est envoyé et le premier appel
    échoue en 401.
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        host: str = "https://ollama.com",
        think: bool = False,
        max_reply_tokens: int = 2048,
        temperature: float | None = None,
        name: str = "ollama_cloud",
        client: Any = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        super().__init__(
            model, host=host, think=think, max_reply_tokens=max_reply_tokens,
            temperature=temperature, name=name, client=client,
        )

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
