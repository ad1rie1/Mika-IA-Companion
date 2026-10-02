"""Fournisseur Claude : l'API Messages d'Anthropic, un appel par requête.

Contrat :

- préfixe en cache : les outils (triés par nom) puis ``system_stable``, marqué
  ``cache_control`` — à défaut de système, la dernière déclaration d'outil ; un
  second point sur le dernier message avant le tour final, pour qu'une
  conversation qui s'allonge relise son préfixe. Deux points au plus (l'API en
  accepte quatre) ;
- ``system_volatile`` suit le préfixe stable, hors cache, sauf s'il voyage déjà
  en tête du dernier tour utilisateur (dans le système, il change à chaque tour
  et le cache des messages, rendus après lui, n'est plus jamais relu) ;
- appels d'outils de l'assistant → blocs ``tool_use`` ; résultats consécutifs
  → UN tour utilisateur de blocs ``tool_result`` (``is_error`` honoré) ;
- les blocs de réflexion d'un tour outillé reviennent tels que reçus (l'API les
  exige inchangés) : mémoire bornée, indexée par les identifiants d'appels ;
  sans elle, le tour est reconstruit sans réflexion ;
- ``temperature`` n'est jamais envoyée aux modèles qui la refusent ; un 400 qui
  la nomme est rejoué une fois sans elle, et le refus mémorisé par modèle ;
- ``tool_use`` coupé par ``max_tokens`` → ``truncated_tool_call`` ; refus →
  ``stop="refusal"`` **sans aucun appel d'outil** (un ``tool_use`` porté par un
  refus n'est jamais exécuté) ; jetons de cache comptés à part (``cache_read``,
  ``cache_write``), hors ``input_tokens`` ;
- ``pause_turn`` (la boucle serveur — recherche d'outils — s'est mise en pause)
  est reprise, au plus ``PAUSE_RESUMES`` fois, en renvoyant le tour tel quel :
  une pause n'est pas une fin ;
- au premier plan (priorité 0), une seule nouvelle tentative du SDK au lieu de
  deux : la passerelle borne déjà l'appel et a un repli ;
- outils à la demande (``ToolDecl.deferred``) : ``defer_loading`` et l'outil de
  recherche d'outils (BM25) ; le point de cache des outils ne va jamais sur un
  outil différé (400) ; les blocs de la recherche (``server_tool_use``,
  ``tool_search_tool_result``) reviennent tels quels au tour suivant, par la
  même mémoire que la réflexion.
"""

from __future__ import annotations

import copy
import logging
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from typing import Any

from mika.kernel.prompt import CONTEXT_FOOTER, CONTEXT_HEADER
from mika.ports.llm import LLMRequest, LLMResponse, Message, ToolCall, Usage

try:
    import anthropic
except ImportError:  # pragma: no cover — extra « llm » absent
    anthropic = None

log = logging.getLogger("mika.llm.claude")

#: Modèles qui refusent les paramètres d'échantillonnage (400) : Opus 4.7+, Sonnet 5, Fable, Mythos.
NO_SAMPLING_PREFIXES = (
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-fable",
    "claude-mythos",
)
CACHE_TTLS = ("5m", "1h")
#: Tours outillés dont la réflexion reste disponible pour le rejeu.
REPLAY_CAPACITY = 256
#: reprises d'un tour mis en pause par la boucle serveur
PAUSE_RESUMES = 3
#: tentatives du SDK pour un appel au premier plan (sa valeur par défaut : 2)
FOREGROUND_RETRIES = 1

_STOPS = {
    "end_turn": "end",
    "stop_sequence": "end",
    "pause_turn": "end",  # encore en pause après PAUSE_RESUMES reprises : ce qui a été dit
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "model_context_window_exceeded": "max_tokens",
    "refusal": "refusal",
}
_THINKING = frozenset({"thinking", "redacted_thinking"})
#: la recherche d'outils côté serveur : les outils différés se chargent quand le modèle les cherche
SEARCH_TOOL = {"type": "tool_search_tool_bm25_20251119", "name": "tool_search_tool_bm25"}
#: des blocs produits par le serveur, à rendre inchangés au tour suivant
_SERVER = frozenset({"server_tool_use", "tool_search_tool_result"})


class ClaudeBackend:
    """L'API Messages d'Anthropic : un appel par requête, aucune boucle."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        cache_ttl: str = "5m",
        temperature: float | None = None,
        name: str = "claude",
        client: Any = None,
    ) -> None:
        if cache_ttl not in CACHE_TTLS:
            raise ValueError(f"cache_ttl inconnu : {cache_ttl!r} (attendu : {' ou '.join(CACHE_TTLS)})")
        if client is None:
            if anthropic is None:
                raise RuntimeError("ClaudeBackend exige le paquet « anthropic » (extra « llm »).")
            client = anthropic.AsyncAnthropic(api_key=api_key or None)
        self.name = name
        self.model = model
        self.cache_ttl = cache_ttl
        self.temperature = temperature
        self._client = client
        self._no_temperature: set[str] = set()
        self._replays: OrderedDict[tuple[str, ...], tuple[dict[str, Any], ...]] = OrderedDict()

    # ── Requête ──────────────────────────────────────────────────────────

    def cache_mark(self) -> dict[str, str]:
        mark = {"type": "ephemeral"}
        if self.cache_ttl != "5m":
            mark["ttl"] = self.cache_ttl
        return mark

    def payload(self, req: LLMRequest) -> dict[str, Any]:
        """Le corps de ``messages.create``, hors ``temperature`` (décidée à l'envoi)."""
        decls = sorted(req.tools, key=lambda t: t.name)
        tools = [_tool(t) for t in decls]
        if any(t.deferred for t in decls):
            tools.insert(0, dict(SEARCH_TOOL))
        system: list[dict[str, Any]] = []
        if req.system_stable.strip():
            system.append({"type": "text", "text": req.system_stable, "cache_control": self.cache_mark()})
        elif tools:
            # un outil différé ne peut pas porter le point de cache : le dernier chargé d'emblée
            loaded = [t for t in tools if not t.get("defer_loading")]
            loaded[-1]["cache_control"] = self.cache_mark()
        volatile = _volatile_system(req)
        if volatile:
            system.append({"type": "text", "text": volatile})
        messages = self._messages(req.messages)
        if len(messages) >= 2:
            _mark_last_block(messages[-2], self.cache_mark())
        body: dict[str, Any] = {"model": self.model, "max_tokens": req.max_tokens, "messages": messages}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = tools
        return body

    def _messages(self, msgs: Sequence[Message]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for m in msgs:
            if m.role == "tool":
                results.append(_tool_result(m))
                continue
            if results:
                out.append({"role": "user", "content": results})
                results = []
            if m.role == "assistant":
                blocks = self._assistant_blocks(m)
            elif m.role == "user":
                blocks = [{"type": "image", "source": {"type": "base64", "media_type": i.mime, "data": i.data}}
                          for i in m.images] + _text_blocks(m.content)
            else:
                log.warning("rôle de message inconnu ignoré : %r", m.role)
                continue
            if blocks:
                out.append({"role": m.role, "content": blocks})
        if results:
            out.append({"role": "user", "content": results})
        return out

    def _assistant_blocks(self, m: Message) -> list[dict[str, Any]]:
        replay = self._replay_for(m)
        if replay is not None:
            return replay
        blocks = _text_blocks(m.content)
        blocks.extend(
            {"type": "tool_use", "id": c.id, "name": c.name, "input": _plain(c.args)} for c in m.tool_calls
        )
        return blocks

    # ── Rejeu de la réflexion ────────────────────────────────────────────

    def _remember(self, blocks: list[dict[str, Any]]) -> None:
        key = tuple(b["id"] for b in blocks if b["type"] == "tool_use")
        self._replays[key] = tuple(blocks)
        self._replays.move_to_end(key)
        while len(self._replays) > REPLAY_CAPACITY:
            self._replays.popitem(last=False)

    def _replay_for(self, m: Message) -> list[dict[str, Any]] | None:
        """Le tour tel que le modèle l'a produit, s'il est mémorisé et que le message le reprend à l'identique."""
        if not m.tool_calls:
            return None
        key = tuple(c.id for c in m.tool_calls)
        blocks = self._replays.get(key)
        if blocks is None:
            return None
        text = "".join(b["text"] for b in blocks if b["type"] == "text")
        uses = [(b["id"], b["name"], b["input"]) for b in blocks if b["type"] == "tool_use"]
        if text != m.content or uses != [(c.id, c.name, _plain(c.args)) for c in m.tool_calls]:
            return None
        self._replays.move_to_end(key)
        return copy.deepcopy(list(blocks))

    # ── Appel ────────────────────────────────────────────────────────────

    async def complete(self, req: LLMRequest) -> LLMResponse:
        body = self.payload(req)
        client = self._client_for(req)
        parts = [await self._create(body, client)]
        while getattr(parts[-1], "stop_reason", None) == "pause_turn" and len(parts) <= PAUSE_RESUMES:
            # la boucle serveur reprend d'elle-même sur le tour renvoyé tel quel (pas de « continue »)
            turn = {"role": "assistant", "content": [_dump(b) for b in getattr(parts[-1], "content", None) or ()]}
            body = {**body, "messages": [*body["messages"], turn]}
            parts.append(await self._create(body, client))
        return self._read(parts)

    def _client_for(self, req: LLMRequest) -> Any:
        """Au premier plan, moins de tentatives : la passerelle borne l'appel et sait se replier."""
        with_options = getattr(self._client, "with_options", None)
        if req.priority == 0 and callable(with_options):
            return with_options(max_retries=FOREGROUND_RETRIES)
        return self._client

    async def _create(self, body: dict[str, Any], client: Any = None) -> Any:
        client = client if client is not None else self._client
        kwargs = dict(body)
        if self.temperature is not None and self._accepts_temperature():
            kwargs["temperature"] = self.temperature
        try:
            return await client.messages.create(**kwargs)
        except Exception as exc:
            if "temperature" not in kwargs or not _rejects(exc, "temperature"):
                raise
            self._no_temperature.add(self.model)
            log.info("%s refuse « temperature » : mémorisé, plus jamais envoyée", self.model)
            del kwargs["temperature"]
            return await client.messages.create(**kwargs)

    def _accepts_temperature(self) -> bool:
        return not self.model.startswith(NO_SAMPLING_PREFIXES) and self.model not in self._no_temperature

    # ── Réponse ──────────────────────────────────────────────────────────

    def _read(self, parts: Any) -> LLMResponse:
        """Une réponse : un tour, ou un tour et ses reprises après pause (``Sequence``)."""
        parts = list(parts) if isinstance(parts, (list, tuple)) else [parts]
        texts: list[str] = []
        calls: list[ToolCall] = []
        replay: list[dict[str, Any]] = []
        thought = False
        resp = parts[-1]
        for block in (b for part in parts for b in (getattr(part, "content", None) or ())):
            kind = getattr(block, "type", None)
            if kind in _SERVER:
                thought = True  # à rejouer tel quel, comme une réflexion
                replay.append(_dump(block))
            elif kind == "text":
                texts.append(block.text)
                if block.text:
                    replay.append({"type": "text", "text": block.text})
            elif kind == "tool_use":
                args = _plain(block.input) if isinstance(block.input, Mapping) else {"_raw": str(block.input)}
                calls.append(ToolCall(block.id, block.name, args))
                replay.append({"type": "tool_use", "id": block.id, "name": block.name, "input": args})
            elif kind == "thinking":
                thought = True
                replay.append({"type": "thinking", "thinking": block.thinking, "signature": block.signature})
            elif kind == "redacted_thinking":
                thought = True
                replay.append({"type": "redacted_thinking", "data": block.data})
        reason = getattr(resp, "stop_reason", None)
        if reason == "refusal":
            log.warning("%s refuse de poursuivre (stop_details=%s)", self.model, getattr(resp, "stop_details", None))
        stop = _STOPS.get(reason or "", "end")
        usage = _sum([_usage(getattr(p, "usage", None)) for p in parts])
        model = getattr(resp, "model", None) or self.model
        text = "".join(texts)
        if stop == "refusal":
            # un refus n'exécute rien : un tool_use qu'il porterait (entrée partielle, ou ce que la
            # sauvegarde a coupé) n'est pas une décision du modèle
            return LLMResponse(text, (), "refusal", usage, model)
        if stop == "max_tokens" and calls:
            return LLMResponse(text, stop="max_tokens", usage=usage, model=model, truncated_tool_call=True)
        if calls and thought:
            self._remember(replay)
        return LLMResponse(text, tuple(calls), stop, usage, model)


def _plain(value: Any) -> Any:
    """Copie sérialisable en JSON : mappings → dict, séquences → list, ordre conservé."""
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _tool(t: Any) -> dict[str, Any]:
    decl = {"name": t.name, "description": t.description, "input_schema": _plain(t.schema)}
    if t.deferred:
        decl["defer_loading"] = True
    return decl


def _dump(block: Any) -> dict[str, Any]:
    """Un bloc de réponse tel quel, sérialisable (champs vides omis)."""
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", exclude_none=True)
    return _plain(block)


def _volatile_system(req: LLMRequest) -> str:
    """Le bloc volatile à ajouter au système ; vide s'il voyage déjà dans le dernier tour utilisateur."""
    volatile = req.system_volatile
    if not volatile.strip():
        return ""
    framed = f"{CONTEXT_HEADER}\n{volatile}\n{CONTEXT_FOOTER}"
    for m in reversed(req.messages):
        if m.role == "user":
            return "" if framed in m.content else volatile
    return volatile


def _text_blocks(text: str) -> list[dict[str, Any]]:
    """Un bloc texte, ou aucun : l'API refuse un bloc vide."""
    return [{"type": "text", "text": text}] if text.strip() else []


def _tool_result(m: Message) -> dict[str, Any]:
    block: dict[str, Any] = {"type": "tool_result", "tool_use_id": m.tool_call_id or ""}
    if m.content.strip():
        block["content"] = m.content
    if m.is_error:
        block["is_error"] = True
    return block


def _mark_last_block(message: dict[str, Any], mark: Mapping[str, str]) -> None:
    """Point de cache sur le dernier bloc marquable du message (ni réflexion, ni bloc serveur)."""
    content = message["content"]
    for i in range(len(content) - 1, -1, -1):
        if content[i].get("type") not in _THINKING and content[i].get("type") not in _SERVER:
            content[i] = {**content[i], "cache_control": dict(mark)}
            return


def _rejects(exc: BaseException, param: str) -> bool:
    """Un 400 qui nomme ``param`` : le modèle refuse ce paramètre."""
    return getattr(exc, "status_code", None) == 400 and param in str(exc)


def _sum(usages: Sequence[Usage]) -> Usage:
    return Usage(sum(u.input_tokens for u in usages), sum(u.output_tokens for u in usages),
                 sum(u.cache_read for u in usages), sum(u.cache_write for u in usages))


def _usage(u: Any) -> Usage:
    def n(attr: str) -> int:
        value = getattr(u, attr, 0)
        return value if isinstance(value, int) else 0

    return Usage(
        input_tokens=n("input_tokens"),
        output_tokens=n("output_tokens"),
        cache_read=n("cache_read_input_tokens"),
        cache_write=n("cache_creation_input_tokens"),
    )
