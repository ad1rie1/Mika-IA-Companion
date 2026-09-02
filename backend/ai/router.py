"""AI Router — maps function roles to *declared models*.

Each function in the system (conversation, email triage, memory extraction,
etc.) is assigned to a role. A role points to a **declared model** by its
internal name. A declared model is a row of ``ai.models`` config carrying
(internal_name, provider, model_id, temperature).

The UI prevents free-text editing: declared models come from the provider
SDKs, and roles pick only among declared internal names.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextvars import ContextVar
from enum import Enum

from ai.providers import AIProvider
from ai.providers.claude import ClaudeProvider
from ai.providers.gemini_provider import GeminiProvider
from ai.providers.glm_provider import GLMProvider
from ai.providers.ollama_cloud_provider import OllamaCloudProvider
from ai.providers.ollama_provider import OllamaProvider
from ai.providers.openai_provider import OpenAIProvider
from ai.quota import (
    current_project_id,
    estimate_tokens_from_chars,
    quota_tracker,
    _reset_usage,
    _restore_usage,
    _take_usage,
)
from utils.degradation import degradations

logger = logging.getLogger(__name__)

# Borne appliquée quand ``ai.call_timeout_seconds`` est illisible — une lecture
# de configuration peut précéder une base accessible. Jamais « pas de borne » :
# l'absence de borne est exactement ce que ce réglage existe pour empêcher.
FALLBACK_CALL_TIMEOUT_S = 120.0


class AIRole(str, Enum):
    """Each distinct AI function in the system."""

    CONVERSATION = "conversation"
    CONVERSATION_TOOLS = "conversation_tools"  # Claude-only (MCP)
    EMAIL_TRIAGE = "email_triage"
    SIGNAL_INTERPRETATION = "signal_interpretation"
    MEMORY_EXTRACTION = "memory_extraction"
    VALIDITY_CHECK = "validity_check"
    # Vision captioning — takes an image attachment and returns a
    # textual description. Used by the vision preprocessor so non-text
    # perceptions can flow through the text pipeline.
    VISION_CAPTION = "vision_caption"
    # Inner monologue — turns "what she's about to do" + "what just came
    # back" into the short murmured reaction she thinks out loud. Small and
    # cheap by design: it fires far more often than a conversation turn.
    INNER_VOICE = "inner_voice"
    # Pré-passe de rappel dirigé : planifie les recherches mémoire d'un tour
    # (souvenirs, connaissances, échanges passés) + note de focus. Petit
    # modèle rapide ; non mappé = passe désactivée (fail-open sur le rappel
    # spéculatif) — le défaut sain en local.
    PREPARATION = "preparation"
    # Compaction conversationnelle : replie les segments anciens du fil en
    # résumé roulant, hors tour (lot B). Non mappé = compaction désactivée.
    COMPACTION = "compaction"
    # Travail de projet : la boucle outillée qui écrit, exécute et teste dans
    # l'atelier d'un projet. Distinct de `conversation_tools` parce que ce
    # n'est pas une conversation — pas d'émotion, pas d'interlocuteur, un
    # cadre professionnel — et distinct de `memory_extraction`, que le
    # lanceur empruntait faute de mieux : un petit modèle suffit à remplir un
    # JSON, il ne suffit pas à tenir une boucle d'outils. Non mappé = repli
    # sur `memory_extraction`, donc une installation existante ne casse pas.
    PROJECT_WORK = "project_work"


# Config-key prefixes that carry a provider's credentials. A change under one
# of these evicts that provider's cached instance (see _invalidate_provider).
_PROVIDER_CONFIG_PREFIXES = (
    "ai.claude.", "ai.openai.", "ai.gemini.", "ai.glm.", "ai.ollama.",
    # Distinct from "ai.ollama." — prefix matching is a plain startswith and
    # "ai.ollama_cloud.api_key" does not begin with "ai.ollama.", so the two
    # providers are evicted independently rather than in lockstep.
    "ai.ollama_cloud.",
)

# Concurrence autorisée par provider quand la configuration est illisible.
# 0 = illimité.
#
# Un serveur local n'a qu'un seul emplacement d'exécution : deux appels n'y
# tournent pas en parallèle, ils font la queue, et ce temps de queue est
# compté *à l'intérieur* du timeout de chacun — un tour utilisateur rend
# alors le texte de repli sans que rien ne distingue « modèle trop lent » de
# « modèle occupé ailleurs ». Les émetteurs sont nombreux et sur leur propre
# cadence (conscience, consolidateur, sommeil, runner de projets, cron des
# modules, voix intérieure) et aucun ne passe par la ``TurnQueue``, qui ne
# sérialise que les tours de conversation entre eux.
#
# Le réglage effectif est ``ai.<provider>.max_concurrent_calls``, déclaré
# pour *tous* les providers (voir ai/config_schema.py) : chez un hébergé le
# parallélisme est réel, mais il est facturé et contingenté, et une rafale
# de boucles de fond suffit à dépasser une limite de débit. Seul le défaut
# diffère — 1 pour ollama, illimité ailleurs.
#
# Ce qui suit n'est pas ce défaut-là : c'est la ceinture appliquée quand la
# configuration est *illisible*, pour qu'une base momentanément inaccessible
# ne restaure pas le comportement que le plafond existe pour empêcher. Un
# provider absent d'ici retombe alors sur « illimité », c'est-à-dire sur ce
# qu'il faisait avant l'existence du sémaphore.
_PROVIDER_FALLBACK_CONCURRENCY: dict[str, int] = {
    "ollama": 1,
}

# Providers dont le créneau est déjà tenu par l'appel en cours. Un outil MCP
# peut relancer le modèle depuis l'intérieur de la boucle d'outils
# (``files_analyze_image`` décrit une image pendant que la conversation
# attend) : sans cette garde, l'appel imbriqué attendrait un créneau que son
# propre appelant détient, jusqu'au timeout.
_held_providers: ContextVar[frozenset[str]] = ContextVar(
    "ai_held_providers", default=frozenset()
)

# Maps provider name → class
_PROVIDER_CLASSES: dict[str, type] = {
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "glm": GLMProvider,
    "ollama": OllamaProvider,
    "ollama_cloud": OllamaCloudProvider,
}


def _load_declared_models() -> dict[str, dict]:
    """Return {internal_name: {provider, model_id, temperature}} from ai.models rows.

    Disabled rows are excluded — useful to park a model temporarily
    without losing its config.
    """
    from configs.service import config_service
    try:
        rows = config_service.list_rows("ai.models", decrypt_secrets=False)
    except KeyError:
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        if not row.get("enabled", True):
            continue
        payload = row.get("payload") or {}
        name = (payload.get("internal_name") or "").strip()
        if not name:
            continue
        provider = (payload.get("provider") or "").strip().lower()
        model_id = (payload.get("model_id") or "").strip()
        if not provider or not model_id:
            continue
        try:
            temperature = float(payload.get("temperature", 0.7))
        except (TypeError, ValueError):
            temperature = 0.7
        # ``max_tokens`` est optionnel sur les lignes existantes (le champ a
        # été ajouté après coup) : absent ou invalide → None, et le provider
        # garde son défaut de signature.
        try:
            raw_mt = payload.get("max_tokens")
            max_tokens = int(raw_mt) if raw_mt not in (None, "") else None
        except (TypeError, ValueError):
            max_tokens = None
        if max_tokens is not None and max_tokens <= 0:
            max_tokens = None
        # ``context_window`` : 0 (défaut du champ) ou invalide → None, et le
        # budget de contexte reste sur les planchers fixes.
        try:
            raw_cw = payload.get("context_window")
            context_window = int(raw_cw) if raw_cw not in (None, "") else None
        except (TypeError, ValueError):
            context_window = None
        if context_window is not None and context_window <= 0:
            context_window = None
        out[name] = {
            "provider": provider,
            "model_id": model_id,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "context_window": context_window,
        }
    return out


class UnconfiguredRoleError(RuntimeError):
    """Raised when a role is requested but has no valid declared model."""


class AIRouter:
    """Routes AI completion requests to the provider+model of a declared model.

    Providers are instantiated lazily on first use. If a provider's
    dependencies are missing (e.g. openai package not installed),
    the error surfaces only when that provider is actually needed.
    """

    def __init__(self):
        self._providers: dict[str, AIProvider] = {}
        self._role_to_internal: dict[AIRole, str] = {}
        # Table des modèles déclarés, mémorisée. ``list_rows`` est la seule
        # lecture de configuration sans cache, et ``_resolve`` est sur le
        # chemin de TOUT appel IA : un SELECT par appel, confié depuis un
        # contexte async au pool mono-worker de ``configs.service``, boucle
        # ASGI en attente. Invalidée par ``on_change("ai.models")``.
        self._declared_models: dict[str, dict] | None = None
        # Créneaux d'exécution par provider, créés à la première demande :
        # une primitive asyncio se lie à sa boucle, et aucune ne tourne ici.
        self._semaphores: dict[str, asyncio.Semaphore | None] = {}
        self._semaphore_loop: asyncio.AbstractEventLoop | None = None
        self._load_config()

    # ── Configuration loading ───────────────────────────────────

    def _load_config(self):
        """Read role → internal_name mappings from the config service."""
        from configs.service import config_service

        # Dérivée de l'énumération, jamais recopiée : la table écrite à la
        # main listait dix rôles sur onze. ``project_work`` avait sa ligne
        # dans le tableau de bord et ``_reload_role`` le prenait bien au
        # changement à chaud — mais au démarrage il n'était pas lu, donc
        # chaque redémarrage renvoyait le lanceur de projets sur
        # ``memory_extraction`` sans rien dire. La clé suit ``role.value``,
        # exactement comme ``_reload_role`` la décode.
        role_keys = {role: f"ai.role.{role.value}" for role in AIRole}
        for role, cfg_key in role_keys.items():
            name = (config_service.get(cfg_key, default="") or "").strip()
            if name:
                self._role_to_internal[role] = name

        config_service.on_change("ai.role.", lambda k, v: self._reload_role(k, v))
        # ``add_row`` / ``update_row`` / ``delete_row`` invalident puis
        # notifient, dans cet ordre : une relecture déclenchée ici voit bien
        # la table d'après.
        config_service.on_change("ai.models", lambda k, v: self._invalidate_declared_models())
        # Providers read their credentials once, in __init__, and were cached
        # forever: rotating a leaked API key in the admin returned
        # {"ok": true} while the process kept authenticating with the old one.
        # Evict on any provider-credential change so the next call re-reads.
        for prefix in _PROVIDER_CONFIG_PREFIXES:
            config_service.on_change(
                prefix, lambda k, v, p=prefix: self._invalidate_provider(p, k)
            )

    def _invalidate_provider(self, prefix: str, key: str) -> None:
        """Drop the cached instance whose credentials just changed."""
        provider_name = prefix.removeprefix("ai.").rstrip(".")
        if self._providers.pop(provider_name, None) is not None:
            logger.info(
                "Provider '%s' evicted after %s changed — credentials will be "
                "re-read on the next call", provider_name, key,
            )

    def _invalidate_declared_models(self) -> None:
        """Oublie la table mémorisée — la prochaine résolution la relit."""
        self._declared_models = None
        logger.info(
            "Modèles déclarés invalidés — ai.models sera relu à la prochaine résolution"
        )

    def _get_declared_models(self) -> dict[str, dict]:
        """Modèles déclarés, relus au plus une fois par changement de config.

        Un résultat vide n'est délibérément pas mémorisé : il vaut aussi bien
        « rien n'est encore déclaré » (installation neuve — l'appelant lèvera
        ``UnconfiguredRoleError`` de toute façon) qu'une base momentanément
        illisible, et figer ce second cas condamnerait tous les appels
        suivants jusqu'à la prochaine écriture de configuration.
        """
        cached = self._declared_models
        if cached is not None:
            return cached
        loaded = _load_declared_models()
        if loaded:
            self._declared_models = loaded
        return loaded

    def _reload_role(self, key: str, value):
        role_key = key.split("ai.role.", 1)[-1]
        try:
            role = AIRole(role_key)
        except ValueError:
            return
        self._role_to_internal[role] = (value or "").strip()
        logger.info(
            "AI Router role reloaded: %s → %s",
            role.value, self._role_to_internal[role] or "(vide)",
        )

    # ── Resolution ───────────────────────────────────────────────

    def _resolve(self, role: AIRole) -> tuple[str, str, float, str]:
        """Role → (provider, model_id, temperature, internal_name).

        Raises UnconfiguredRoleError if the role is missing or points to
        an unknown / disabled declared model.
        """
        internal_name = self._role_to_internal.get(role, "").strip()
        if not internal_name:
            raise UnconfiguredRoleError(
                f"Aucun modèle déclaré n'est associé au rôle '{role.value}'. "
                "Déclare un modèle dans Configuration > Déclaration des modèles "
                "puis mappe-le dans IA · Rôles."
            )
        declared = self._get_declared_models()
        entry = declared.get(internal_name)
        if entry is None:
            raise UnconfiguredRoleError(
                f"Le rôle '{role.value}' pointe sur '{internal_name}' "
                "qui n'est pas (ou plus) déclaré."
            )
        return entry["provider"], entry["model_id"], entry["temperature"], internal_name

    def _get_provider(self, provider_name: str) -> AIProvider:
        """Get or lazily create a provider instance."""
        if provider_name not in self._providers:
            cls = _PROVIDER_CLASSES.get(provider_name)
            if cls is None:
                available = ", ".join(_PROVIDER_CLASSES.keys())
                raise ValueError(
                    f"Provider inconnu '{provider_name}'. "
                    f"Disponibles : {available}"
                )
            self._providers[provider_name] = cls()
            logger.info("Provider '%s' initialisé", provider_name)
        return self._providers[provider_name]

    def reset_provider(self, provider_name: str) -> None:
        """Drop a cached provider so the next call re-reads its credentials."""
        self._providers.pop(provider_name, None)

    def provider_by_name(self, provider_name: str) -> AIProvider:
        """Public access to a (cached) provider instance by registry name.

        For capability-specific call sites (e.g. Whisper transcription)
        that need a provider outside the role system. Benefits from the
        same cache + credential-change eviction as role-routed calls.
        Raises when the provider is unknown or its credentials are missing.
        """
        return self._get_provider(provider_name)

    def resolve(self, role: AIRole) -> tuple[str, str, float, str]:
        """Public alias of ``_resolve`` for callers that need provider/model/temp."""
        return self._resolve(role)

    def get_provider(self, role: AIRole) -> AIProvider:
        """Return a (cached, lazily-instantiated) provider instance for ``role``."""
        provider_name, _, _, _ = self._resolve(role)
        return self._get_provider(provider_name)

    def get_model(self, role: AIRole) -> str:
        """Return the model_id configured for a role."""
        _, model, _, _ = self._resolve(role)
        return model

    def get_provider_name(self, role: AIRole) -> str:
        """Return the provider name configured for a role."""
        provider, _, _, _ = self._resolve(role)
        return provider

    # ── Sérialisation par provider ───────────────────────────────

    def _concurrency_limit(self, provider_name: str) -> int:
        """Appels simultanés autorisés pour ce provider (0 = illimité)."""
        from configs.service import config_service

        fallback = _PROVIDER_FALLBACK_CONCURRENCY.get(provider_name, 0)
        try:
            return max(0, int(config_service.get(
                f"ai.{provider_name}.max_concurrent_calls", default=fallback
            )))
        except Exception:
            return fallback

    def _provider_semaphore(self, provider_name: str) -> asyncio.Semaphore | None:
        """Le créneau du provider, ou None quand il n'est pas plafonné."""
        loop = asyncio.get_running_loop()
        if loop is not self._semaphore_loop:
            # Un sémaphore asyncio s'attache à la boucle sur laquelle il
            # attend : garder ceux d'une boucle disparue (tests, commande de
            # gestion) lèverait « bound to a different event loop » à la
            # première contention.
            self._semaphores = {}
            self._semaphore_loop = loop
        if provider_name not in self._semaphores:
            limit = self._concurrency_limit(provider_name)
            self._semaphores[provider_name] = (
                asyncio.Semaphore(limit) if limit > 0 else None
            )
            if limit > 0:
                logger.info(
                    "Provider '%s' plafonné à %d appel(s) simultané(s)",
                    provider_name, limit,
                )
        return self._semaphores[provider_name]

    # ── Completion ───────────────────────────────────────────────

    def _call_timeout(self, override: float | None) -> float:
        """Borne temporelle d'un appel routé, en secondes.

        La borne appartient au routeur, pas à la discipline de l'appelant :
        la moitié des sites d'appel l'oubliaient, et tous vivaient dans une
        boucle de fond sans superviseur. Le SDK Ollama construit son client
        httpx avec ``timeout=None`` — un serveur qui accepte la connexion et
        ne répond jamais (modèle en cours de chargement en VRAM, GPU bloqué,
        conteneur suspendu) laissait la coroutine en attente pour la durée du
        processus. Le tick cron qui la portait ne revenait alors jamais, et
        comme un tick qui en chevauche un autre est *sauté*, le module cessait
        définitivement de travailler — sans exception, sans trace.

        ``ai.call_timeout_seconds`` (« Timeout appel IA » dans la
        configuration) n'était lu qu'au tour de conversation : c'est ici qu'il
        vaut pour tous. Un appelant qui passe ``timeout=`` garde la main, et
        ceux qui gardent leur propre ``wait_for`` plus court gagnent toujours.
        """
        if override is not None:
            return float(override)
        from configs.service import config_service
        try:
            value = float(config_service.get("ai.call_timeout_seconds"))
        except Exception:
            return FALLBACK_CALL_TIMEOUT_S
        return value if value > 0 else FALLBACK_CALL_TIMEOUT_S

    async def _metered_call(
        self,
        role: AIRole,
        system_prompt: str,
        user_prompt: str,
        invoke,
        timeout: float | None = None,
        extra_prompt_chars: int = 0,
        calibrate: bool = True,
    ):
        """Séquence commune à TOUT appel routé, outillé ou non.

        Résolution du rôle → contrôle de quota → appel → relevé d'usage →
        comptabilisation → log unifié.
        ``invoke(provider, model, temperature, max_tokens)`` exécute l'appel
        réel et renvoie ``(valeur_rendue, texte_produit)`` ; le texte ne sert
        qu'à estimer les tokens de sortie quand le provider n'a pas remonté
        son usage réel. ``max_tokens`` vient de la ligne du modèle déclaré
        (None = défaut du provider).

        Factorisé plutôt que recopié : le chemin outillé contournait le
        routeur, donc ni les plafonds, ni la température déclarée, ni la
        trace ne s'appliquaient au plus gros consommateur du système.

        C'est aussi le point de passage unique où le créneau d'exécution du
        provider est réservé : l'attente et la génération sont mesurées
        séparément, faute de quoi un tour passé à faire la queue derrière
        une génération de fond est indiscernable d'un modèle lent. Les deux
        se partagent une seule borne, celle du routeur : attendre son tour
        est du temps passé dans l'appel, pas du temps offert en plus.
        """
        provider_name, model, temperature, internal_name = self._resolve(role)
        provider = self._get_provider(provider_name)
        # Lu sur le cache mémoïsé que ``_resolve`` vient de chauffer — jamais
        # une relecture : un ``_resolve`` substitué (tests) ou une table vide
        # donnent simplement None, c'est-à-dire le défaut du provider.
        max_tokens = ((self._declared_models or {}).get(internal_name) or {}).get(
            "max_tokens"
        )

        # ``extra_prompt_chars`` porte ce qui n'apparaît dans aucun des deux
        # prompts mais part quand même sur le réseau — les déclarations
        # d'outils, ~6 500 tokens pour les neuf modules. Sans lui, le contrôle
        # de quota pré-appel minorait systématiquement le chemin le plus cher.
        prompt_chars = len(system_prompt) + len(user_prompt) + extra_prompt_chars
        timeout_s = self._call_timeout(timeout)

        project_id = current_project_id.get()

        expected_in = estimate_tokens_from_chars(prompt_chars)
        expected_total = expected_in + 512
        quota_tracker.check(
            role=role.value,
            project_id=project_id,
            expected_tokens=expected_total,
        )

        logger.debug(
            "AI call START  role=%s internal=%s provider=%s model=%s prompt_chars=%d project=%s",
            role.value, internal_name, provider_name, model, prompt_chars, project_id,
        )

        # Réservation du créneau. Un appel imbriqué réutilise celui de son
        # appelant : il tourne déjà *dans* le créneau qu'il attendrait.
        #
        # L'attente entre dans la borne du routeur au lieu de s'y ajouter :
        # un appel routé se termine dans ``ai.call_timeout_seconds``, qu'il
        # ait passé ce temps à générer ou à faire la queue. C'est déjà ce que
        # mesurait le tour de conversation, dont le ``wait_for`` englobe
        # l'appel entier ; les boucles de fond, elles, n'auraient eu aucune
        # borne sur cette attente-ci — celle-là même que la borne du routeur
        # existe pour empêcher.
        semaphore = self._provider_semaphore(provider_name)
        held = _held_providers.get()
        slot_token = None
        t_wait = time.monotonic()
        if semaphore is not None and provider_name not in held:
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout=timeout_s)
            except BaseException:
                # Le timeout de l'appelant — ou celui du routeur — peut
                # tomber pendant l'attente : sans cette trace, un tour mort
                # en file est indiscernable d'un modèle qui n'a pas fini de
                # générer.
                logger.warning(
                    "AI call ABANDON role=%s provider=%s — créneau jamais "
                    "obtenu après %.0f ms d'attente (borne %.0f s)",
                    role.value, provider_name,
                    (time.monotonic() - t_wait) * 1000, timeout_s,
                )
                raise
            slot_token = _held_providers.set(held | {provider_name})
        t_call = time.monotonic()
        wait_ms = (t_call - t_wait) * 1000
        remaining_s = max(0.0, timeout_s - (t_call - t_wait))

        # L'usage se cumule d'un tour d'outils à l'autre : on ouvre une
        # fenêtre de relevé vierge pour ne pas facturer le reliquat d'un
        # appel précédent. Une *fenêtre*, pas une remise à zéro : un outil
        # MCP relance le routeur depuis l'intérieur de la boucle d'outils, et
        # une remise à zéro plate y effaçait ce que la boucle englobante
        # avait déjà cumulé (OpenAI, GLM, Ollama et Gemini remontent leur
        # usage itération par itération). Le jeton rend au ``finally`` le
        # relevé de l'appelant tel qu'il était.
        usage_token = _reset_usage()

        try:
            result, text = await asyncio.wait_for(
                invoke(provider, model, temperature, max_tokens),
                timeout=remaining_s,
            )
            elapsed_ms = (time.monotonic() - t_call) * 1000

            usage = _take_usage()
            if usage:
                tokens_in, tokens_out, cache_read, cache_write = _split_usage(usage)
                # Calibration chars→tokens sur l'usage RÉEL uniquement, et
                # jamais sur une boucle d'outils (son usage cumule les
                # itérations et les lectures de cache — l'échantillon serait
                # faux par construction). Le prompt réel est la somme : un
                # jeton lu depuis le cache est un jeton du prompt.
                if calibrate:
                    try:
                        from ai.calibration import calibration
                        calibration.record(
                            provider_name, prompt_chars,
                            tokens_in + cache_read + cache_write,
                        )
                    except Exception:
                        pass
            else:
                tokens_in = expected_in
                tokens_out = estimate_tokens_from_chars(len(text))
                cache_read = cache_write = 0

            cost_usd = quota_tracker.record(
                role=role.value,
                provider=provider_name,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                project_id=project_id,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
            )

            logger.info(
                "AI call OK     role=%-22s internal=%-18s provider=%-7s model=%-30s "
                "prompt=%5d chars  response=%5d chars  tok=%d/%d  cache=%d/%d  "
                "$%.5f  %7.0f ms (attente %.0f ms)",
                role.value, internal_name, provider_name, model,
                prompt_chars, len(text),
                tokens_in, tokens_out, cache_read, cache_write,
                cost_usd, elapsed_ms, wait_ms,
            )
            return result

        except asyncio.TimeoutError:
            # Dit à voix haute : une boucle de fond qui se fige silencieusement
            # est indiscernable d'une boucle qui n'a rien à faire. L'attente
            # figure à part : une borne dépassée après avoir passé l'essentiel
            # du budget en file ne se répare pas en allongeant la borne.
            elapsed_ms = (time.monotonic() - t_call) * 1000
            logger.warning(
                "AI call TIMEOUT role=%-22s internal=%-18s provider=%-7s model=%-30s "
                "prompt=%5d chars  %7.0f ms  (borne %.0f s, attente %.0f ms)",
                role.value, internal_name, provider_name, model,
                prompt_chars, elapsed_ms, timeout_s, wait_ms,
            )
            self._record_partial_usage(
                role, provider_name, model, project_id, note="TIMEOUT",
            )
            raise

        except Exception:
            elapsed_ms = (time.monotonic() - t_call) * 1000
            logger.error(
                "AI call FAILED role=%-22s internal=%-18s provider=%-7s model=%-30s "
                "prompt=%5d chars  %7.0f ms (attente %.0f ms)",
                role.value, internal_name, provider_name, model,
                prompt_chars, elapsed_ms, wait_ms,
            )
            self._record_partial_usage(
                role, provider_name, model, project_id, note="FAILED",
            )
            raise

        finally:
            if slot_token is not None:
                _held_providers.reset(slot_token)
                semaphore.release()
            _restore_usage(usage_token)

    def _record_partial_usage(
        self, role: AIRole, provider_name: str, model: str, project_id, *, note: str,
    ) -> None:
        """Comptabilise ce qu'un appel raté a quand même consommé.

        Un timeout tombe souvent *après* que le provider a répondu à une ou
        plusieurs itérations de sa boucle d'outils, et une exception peut
        suivre une génération complète (un handler qui lève hors boucle, un
        4xx au second tour) : ces jetons ont été facturés. Ils restaient dans
        le ContextVar jusqu'à la fenêtre de l'appel suivant, qui les
        effaçait — le quota ne voyait jamais un appel raté, et un modèle en
        timeout permanent consommait sans borne sous un compteur immobile.
        Jamais une exception : la comptabilité ne doit pas masquer l'erreur
        d'origine, qui est en train de remonter.
        """
        try:
            usage = _take_usage()
        except Exception as exc:
            degradations.record("ai.router.partial_usage", exc)
            return
        if not usage:
            return
        tokens_in, tokens_out, cache_read, cache_write = _split_usage(usage)
        if not (tokens_in or tokens_out or cache_read or cache_write):
            return
        try:
            cost_usd = quota_tracker.record(
                role=role.value,
                provider=provider_name,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                project_id=project_id,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
            )
        except Exception as exc:
            degradations.record("ai.router.partial_usage", exc)
            return
        logger.warning(
            "AI call %s — usage partiel comptabilisé role=%s provider=%s "
            "model=%s tok=%d/%d cache=%d/%d $%.5f",
            note, role.value, provider_name, model,
            tokens_in, tokens_out, cache_read, cache_write, cost_usd,
        )

    async def complete(
        self,
        role: AIRole,
        system_prompt: str,
        user_prompt: str,
        **kwargs,
    ) -> str:
        """Route a completion request to the configured provider+model.

        Wraps every call with unified logging: timing, role, provider,
        model, prompt size, and response size — et une borne temporelle
        (``timeout=`` explicite, sinon ``ai.call_timeout_seconds``).
        """
        timeout = kwargs.pop("timeout", None)

        async def _invoke(provider, model, temperature, max_tokens):
            # Role-configured temperature wins unless the caller overrides it.
            kwargs.setdefault("temperature", temperature)
            if max_tokens is not None:
                kwargs.setdefault("max_tokens", max_tokens)
            text = await provider.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                **kwargs,
            )
            return text, text

        return await self._metered_call(
            role, system_prompt, user_prompt, _invoke, timeout=timeout,
        )

    async def complete_with_tools(
        self,
        role: AIRole,
        system_prompt: str,
        user_prompt: str,
        tools: list,
        **kwargs,
    ) -> tuple[str, list[str]]:
        """Route a tool-enabled completion, metered exactly like ``complete``.

        Renvoie ``(texte, noms_des_outils_appelés)``. La boucle d'outils est
        interne au provider ; ce qui compte ici est qu'elle soit encadrée par
        le quota, comptabilisée dans son intégralité, et bornée dans le temps.
        """
        timeout = kwargs.pop("timeout", None)

        async def _invoke(provider, model, temperature, max_tokens):
            # Même règle que ``complete`` : la température du modèle déclaré
            # s'applique, sauf si l'appelant en impose une.
            kwargs.setdefault("temperature", temperature)
            if max_tokens is not None:
                kwargs.setdefault("max_tokens", max_tokens)
            text, called = await provider.complete_with_tools(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                tools=tools or [],
                **kwargs,
            )
            return (text, called), text

        return await self._metered_call(
            role, system_prompt, user_prompt, _invoke, timeout=timeout,
            extra_prompt_chars=_tools_prompt_chars(tools),
            calibrate=False,
        )

    # ── Structured conversation turns ────────────────────────────

    async def chat(self, role: AIRole, prompt, **kwargs) -> str:
        """Route a structured ``ChatPrompt`` turn.

        Providers exposing ``complete_chat`` receive the structured form
        (cacheable prefix + real message turns); the others get the exact
        legacy two-string shape, so the fallback providers are untouched.
        """
        timeout = kwargs.pop("timeout", None)
        system_est, user_est = prompt.legacy_pair()

        async def _invoke(provider, model, temperature, max_tokens):
            kwargs.setdefault("temperature", temperature)
            if max_tokens is not None:
                kwargs.setdefault("max_tokens", max_tokens)
            if hasattr(provider, "complete_chat"):
                text = await provider.complete_chat(
                    prompt=prompt, model=model, **kwargs,
                )
            else:
                text = await provider.complete(
                    system_prompt=system_est,
                    user_prompt=user_est,
                    model=model,
                    **kwargs,
                )
            return text, text

        return await self._metered_call(
            role, system_est, user_est, _invoke, timeout=timeout,
        )

    async def chat_with_tools(
        self, role: AIRole, prompt, tools: list, **kwargs,
    ) -> tuple[str, list[str]]:
        """Route a tool-enabled structured turn, metered like the rest."""
        timeout = kwargs.pop("timeout", None)
        system_est, user_est = prompt.legacy_pair()

        async def _invoke(provider, model, temperature, max_tokens):
            kwargs.setdefault("temperature", temperature)
            if max_tokens is not None:
                kwargs.setdefault("max_tokens", max_tokens)
            if hasattr(provider, "complete_chat_with_tools"):
                text, called = await provider.complete_chat_with_tools(
                    prompt=prompt, model=model, tools=tools or [], **kwargs,
                )
            else:
                text, called = await provider.complete_with_tools(
                    system_prompt=system_est,
                    user_prompt=user_est,
                    model=model,
                    tools=tools or [],
                    **kwargs,
                )
            return (text, called), text

        return await self._metered_call(
            role, system_est, user_est, _invoke, timeout=timeout,
            extra_prompt_chars=_tools_prompt_chars(tools),
            calibrate=False,
        )


def _split_usage(usage: dict) -> tuple[int, int, int, int]:
    """``(in, out, cache_read, cache_write)`` depuis le relevé du provider.

    Les clés de cache sont optionnelles : seul Claude les remonte, les autres
    providers ne posent que ``in``/``out``.
    """
    return (
        int(usage.get("in", 0) or 0),
        int(usage.get("out", 0) or 0),
        int(usage.get("cache_read", 0) or 0),
        int(usage.get("cache_write", 0) or 0),
    )


def _tools_prompt_chars(tools: list) -> int:
    """Approximate character weight of the tool declarations.

    Name + description + serialized JSON schema — the payload every provider
    re-sends with the request. Defensive: an exotic tool object without the
    expected surface simply doesn't count, it never breaks the call.
    """
    import json

    total = 0
    for t in tools or []:
        try:
            total += len(getattr(t, "name", "") or "")
            total += len(getattr(t, "description", "") or "")
            total += len(json.dumps(t.to_json_schema(), ensure_ascii=False))
        except Exception:
            continue
    return total


ai_router = AIRouter()
