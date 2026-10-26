"""Les modèles qu'un fournisseur propose (le bouton « charger » de la console), et
ce qu'il dit de celui qu'on a choisi (sa fenêtre, sa plus longue réponse — ADR 0136).

Un appel HTTP court, sur demande seulement (jamais au rendu d'une page). Un
fournisseur injoignable ou une clé refusée donnent un message en français,
jamais une exception : c'est justement quand on vient réparer la
configuration qu'il ne répond pas. La clé n'apparaît dans aucun message.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

import httpx

from mika.adapters.llm.config import BackendSpec, LLMConfig, ModelLimits, tokens_fr

TIMEOUT_S = 8.0
LIMIT = 500
#: ce que ``claude --model`` comprend sans rien demander ; vide : le modèle par défaut de la CLI
CLAUDE_CODE_MODELS = ("fable", "haiku", "opus", "sonnet")
#: où les fournisseurs disent la fenêtre d'un modèle et sa plus longue réponse (l'API Claude, OpenRouter, vLLM,
#: LM Studio, Groq) ; Ollama la dit dans ``/api/show`` (``<architecture>.context_length``)
WINDOW_KEYS = ("max_input_tokens", "context_length", "max_model_len", "max_context_length", "context_window")
OUTPUT_KEYS = ("max_tokens", "max_completion_tokens", "max_output_tokens")
#: au-delà, un nombre de jetons dit par un fournisseur n'est pas cru
MAX_TOKENS = 10_000_000


class ListingFailed(Exception):
    """Le fournisseur n'a pas donné sa liste (message en français, sans secret)."""


def _endpoint(spec: BackendSpec) -> tuple[str, dict[str, str], str]:
    """(adresse, en-têtes, format de la réponse)."""
    if spec.kind == "claude":
        return ("https://api.anthropic.com/v1/models?limit=1000", _anthropic_headers(spec), "data")
    if spec.kind == "openai":
        return f"{_openai_base(spec)}/models", _bearer(spec), "data"
    return f"{_ollama_host(spec)}/api/tags", _ollama_headers(spec), "models"


def _anthropic_headers(spec: BackendSpec) -> dict[str, str]:
    return {"x-api-key": spec.api_key, "anthropic-version": "2023-06-01"}


def _bearer(spec: BackendSpec) -> dict[str, str]:
    return {"Authorization": f"Bearer {spec.api_key}"} if spec.api_key else {}


def _openai_base(spec: BackendSpec) -> str:
    return (spec.base_url or "https://api.openai.com/v1").rstrip("/")


def _ollama_host(spec: BackendSpec) -> str:
    return (spec.host or ("https://ollama.com" if spec.kind == "ollama_cloud" else "http://localhost:11434")).rstrip("/")


def _ollama_headers(spec: BackendSpec) -> dict[str, str]:
    return _bearer(spec) if spec.kind == "ollama_cloud" else {}


def _count(value: Any) -> int:
    """Un nombre de jetons plausible, sinon 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 < value <= MAX_TOKENS else 0


def _limits_of(item: Any) -> ModelLimits:
    """Ce qu'une fiche de modèle dit de sa fenêtre et de sa réponse (0 : rien)."""
    if not isinstance(item, dict):
        return ModelLimits()
    top = item.get("top_provider") if isinstance(item.get("top_provider"), dict) else {}
    window = next((n for k in WINDOW_KEYS if (n := _count(item.get(k)))), 0) or _count(top.get("context_length"))
    output = next((n for k in OUTPUT_KEYS if (n := _count(item.get(k)))), 0) or \
        _count(top.get("max_completion_tokens"))
    return ModelLimits(window, output)


def _entries(payload: Any, shape: str) -> list[tuple[str, ModelLimits]]:
    items = payload.get(shape) if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ListingFailed("Réponse inattendue du fournisseur.")
    found: dict[str, ModelLimits] = {}
    for item in items[:LIMIT]:
        if isinstance(item, dict):
            name = item.get("id") or item.get("name") or item.get("model")
            if isinstance(name, str) and name.strip():
                found.setdefault(name.strip()[:200], _limits_of(item))
    return sorted(found.items())


@asynccontextmanager
async def _http(client: httpx.AsyncClient | None) -> AsyncIterator[httpx.AsyncClient]:
    if client is not None:
        yield client
        return
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False) as own:
        yield own


async def _fetch(http: httpx.AsyncClient, url: str, headers: dict[str, str], body: Any = None) -> Any:
    """La réponse JSON du fournisseur (``body`` : en POST) ; lève ``ListingFailed``."""
    try:
        response = await (http.post(url, headers=headers, json=body) if body is not None
                          else http.get(url, headers=headers))
    except httpx.HTTPError as exc:
        raise ListingFailed(f"Fournisseur injoignable ({type(exc).__name__}).") from None
    if response.status_code in (401, 403):
        raise ListingFailed("Clé refusée par le fournisseur.")
    if response.status_code >= 400:
        raise ListingFailed(f"Le fournisseur a répondu {response.status_code}.")
    try:
        return response.json()
    except ValueError:
        raise ListingFailed("Réponse illisible du fournisseur.") from None


async def list_models(spec: BackendSpec, *,
                      client: httpx.AsyncClient | None = None) -> list[tuple[str, ModelLimits]]:
    """Les identifiants de modèles du fournisseur, chacun avec ce que la liste en dit (l'API Claude y donne
    fenêtre et réponse, Ollama rien) ; lève ``ListingFailed``."""
    if spec.kind == "claude_code":
        # la CLI choisit : ses alias suffisent, sans réseau
        return [(name, ModelLimits()) for name in CLAUDE_CODE_MODELS]
    if spec.kind in ("claude",) and not spec.api_key:
        raise ListingFailed("Il faut une clé d'API pour lister les modèles.")
    url, headers, shape = _endpoint(spec)
    async with _http(client) as http:
        return _entries(await _fetch(http, url, headers), shape)


async def model_limits(spec: BackendSpec, *, client: httpx.AsyncClient | None = None) -> ModelLimits:
    """Ce que le fournisseur dit du modèle choisi (0 : il ne le dit pas) ; lève ``ListingFailed``. Claude Code
    n'est pas interrogé : la CLI choisit son modèle derrière un alias."""
    if spec.kind == "claude_code" or not spec.model:
        return ModelLimits()
    if spec.kind == "claude" and not spec.api_key:
        raise ListingFailed("Il faut une clé d'API pour lire le modèle.")
    async with _http(client) as http:
        if spec.kind == "claude":
            url = f"https://api.anthropic.com/v1/models/{quote(spec.model, safe='')}"
            return _limits_of(await _fetch(http, url, _anthropic_headers(spec)))
        if spec.kind == "openai":
            found = dict(_entries(await _fetch(http, f"{_openai_base(spec)}/models", _bearer(spec)), "data"))
            return found.get(spec.model, ModelLimits())
        shown = await _fetch(http, f"{_ollama_host(spec)}/api/show", _ollama_headers(spec), {"model": spec.model})
    info = shown.get("model_info") if isinstance(shown, dict) else None
    window = next((n for k, v in info.items() if k.endswith(".context_length") and (n := _count(v))), 0) \
        if isinstance(info, dict) else 0
    return ModelLimits(window=window)


async def settle_limits(cfg: LLMConfig, read: Callable[[BackendSpec], Awaitable[ModelLimits]] = model_limits
                        ) -> tuple[LLMConfig, list[str]]:
    """Chaque fournisseur dont le modèle n'a pas encore été demandé l'est (tous en même temps, chacun borné par
    ``TIMEOUT_S``), et sa fiche le garde, contexte et sortie ramenés dessous (``BackendSpec.fitted``). Un
    fournisseur qui ne répond pas garde sa fiche telle quelle : il sera redemandé au prochain enregistrement.
    Rend la configuration et ce qui a été lu ou changé, en mots."""
    asked = {n: s for n, s in cfg.backends.items() if s.model and s.detected_for != s.detection_key}
    if not asked:
        return cfg, []

    async def one(spec: BackendSpec) -> ModelLimits | str:
        try:
            return await read(spec)
        except ListingFailed as exc:
            return str(exc).rstrip(".")

    got = await asyncio.gather(*(one(s) for s in asked.values()))
    backends = dict(cfg.backends)
    notes = []
    for (name, spec), limits in zip(asked.items(), got, strict=True):
        if isinstance(limits, str):
            notes.append(f"« {name} » : fenêtre du modèle non lue ({limits}) ; elle le sera au prochain "
                         "enregistrement.")
            continue
        backends[name], said = spec.fitted(limits)
        if limits.window:
            said.insert(0, f"fenêtre du modèle {tokens_fr(limits.window)} jetons"
                           + (f", réponse {tokens_fr(limits.output)}" if limits.output else ""))
        if said:
            notes.append(f"« {name} » : {' ; '.join(said)}.")
    return cfg.model_copy(update={"backends": backends}), notes
