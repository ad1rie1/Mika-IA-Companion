"""Ollama Cloud provider — the hosted endpoint at https://ollama.com.

A **separate provider**, not an API key grafted onto the local one, because
the two are separate machines with separate catalogues and separate budgets:
a declared model row names one or the other, and both can be declared at
once (a small local model on ``inner_voice``, a 400B hosted one on
``conversation``). Sharing ``ai.ollama.*`` would have made the local knobs —
``max_reply_tokens`` at 768, calibrated for an RTX 3060 — govern a hosted
model that generates two orders of magnitude faster.

The protocol is otherwise identical: same SDK, same ``/api/chat``, same
``/api/tags``, same tool-calling shape. Hence a subclass overriding three
class attributes plus authentication, rather than a second tool loop.

Three things measured against the live endpoint (2026-07-29), because each
one would otherwise be a plausible wrong guess:

- **``GET /api/tags`` is public.** It returns the hosted catalogue with no
  credential at all, which is convenient (the "charger la liste" button works
  before the key is set) and a trap for ``test()``: the default probe is
  ``list_models()``, so an unconfigured provider would have reported
  ``{"ok": true}``. Asserting a door opens proves nothing about the key.
- **``GET /api/ps`` is the credential probe.** It answers 401
  ``{"error": "unauthorized"}`` with no key *and* with a bad one, so a 200
  is the cheapest real proof the key is accepted — no generation, no quota.
- **Hosted model ids carry no ``-cloud`` suffix.** The catalogue lists
  ``gpt-oss:120b``, ``kimi-k3``, ``glm-5.2``. The ``…-cloud`` form belongs to
  the *other* route, where a local ``ollama`` proxies to the hosted one; used
  here it names a model that does not exist.
"""

from __future__ import annotations

import logging

from ai.providers.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)


class OllamaCloudProvider(OllamaProvider):
    """Hosted Ollama models, authenticated by API key."""

    CONFIG_PREFIX = "ai.ollama_cloud"
    DEFAULT_HOST = "https://ollama.com"
    # Generation is fast enough on the hosted side that the local 768-token
    # belt would truncate ordinary replies. Still bounded: the point of the
    # cap is that a model which never stops cannot hold a turn open forever.
    FALLBACK_MAX_REPLY_TOKENS = 2048

    def _api_key(self) -> str:
        from configs.service import config_service

        try:
            return (config_service.get(
                f"{self.CONFIG_PREFIX}.api_key", default=""
            ) or "").strip()
        except Exception:
            # A config read can precede a reachable database. An absent key
            # yields an unauthenticated client whose first call says so
            # plainly, which beats refusing to instantiate the provider.
            return ""

    def _headers(self) -> dict:
        key = self._api_key()
        return {"Authorization": f"Bearer {key}"} if key else {}

    async def test(self) -> dict:
        """Probe the credential, not merely the endpoint.

        ``/api/tags`` answers without authentication, so the inherited
        ``default_test`` would call an unconfigured provider healthy.
        """
        import httpx

        if not self._api_key():
            return {
                "ok": False, "model_count": 0,
                "error": (
                    "Aucune clé d'API. Configuration > IA · Providers > "
                    "Ollama Cloud (clé à créer sur ollama.com/settings/keys)."
                ),
            }

        url = f"{self._host.rstrip('/')}/api/ps"
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=self._headers()) as client:
                resp = await client.get(url)
        except Exception as exc:  # noqa: BLE001 — surfaced to the user
            return {"ok": False, "model_count": 0,
                    "error": f"{self._host} injoignable : {exc}"}

        # Only an explicit rejection is a failure. A host that doesn't serve
        # /api/ps (a self-hosted gateway, a future version) answers 404 or
        # 405, which says nothing about the credential — don't read it as bad.
        if resp.status_code in (401, 403):
            return {"ok": False, "model_count": 0,
                    "error": f"Clé refusée par {self._host} ({resp.status_code})."}

        try:
            models = await self.list_models()
        except Exception as exc:  # noqa: BLE001
            return {"ok": True, "model_count": 0,
                    "error": f"Clé acceptée, catalogue illisible : {exc}"}
        return {"ok": True, "model_count": len(models)}
