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

from old.backend.ai.cadence import (
    DISJONCTEUR_ECHECS,
    DISJONCTEUR_REPOS_S,
    BudgetDeFondEpuise,
    _comptes as _comptes_de_fond,
    appelant_de_fond,
    cadence_de_fond,
    disjoncteurs,
    est_panne_de_transport,
    est_role_de_fond,
)
from old.backend.ai.providers import AIProvider
from old.backend.ai.providers.claude import ClaudeProvider
from old.backend.ai.providers.gemini_provider import GeminiProvider
from old.backend.ai.providers.glm_provider import GLMProvider
from old.backend.ai.providers.ollama_cloud_provider import OllamaCloudProvider
from old.backend.ai.providers.ollama_provider import OllamaProvider
from old.backend.ai.providers.openai_provider import OpenAIProvider
from old.backend.ai.quota import (
    current_project_id,
    estimate_tokens_from_chars,
    quota_tracker,
    _reset_usage,
    _restore_usage,
    _take_usage,
)
from old.backend.utils.degradation import degradations

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


#: Les rôles dont personne n'attend la réponse — dérivés de l'énumération,
#: jamais recopiés : un rôle ajouté demain est de fond tant qu'il n'est pas
#: nommé dans ``cadence.ROLES_AU_SERVICE_D_UN_HUMAIN``. Un pas de chantier ou
#: un acte de la conscience passe par ``conversation_tools`` et n'est donc
#: pas reconnu ici : l'appelant pose ``cadence.en_fond()``.
ROLES_DE_FOND: frozenset[AIRole] = frozenset(
    role for role in AIRole if est_role_de_fond(role.value)
)


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

# Appels de fond par heure quand ``ai.<provider>.appels_de_fond_par_heure``
# est illisible. 0 = illimité. Même logique que la concurrence : le champ
# existe pour les six providers, seul le défaut est propre au local.
#
# 30/h pour ollama : à ~15–60 s par génération de fond sur une carte
# grand public, c'est au plus un quart d'heure de créneau par heure réservé
# à la vie intérieure — le reste reste libre pour la conversation. Une heure
# chargée en consomme nominalement dix à vingt (extraction, pas de chantier
# plafonnés à quatre, tri des mails, voix intérieure) ; 30 laisse de la
# marge et borne un emballement (un projet sur ``interval:30s`` en ferait
# 120). Chez un hébergé le parallélisme est réel et la dépense est déjà
# plafonnée en jetons par ``ai/quota.py`` : illimité, donc rien ne change.
_PROVIDER_FALLBACK_BUDGET_DE_FOND: dict[str, int] = {
    "ollama": 30,
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
    from old.backend.configs.service import config_service
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
    """Raised when a role is requested but has no valid declared model.

    ``role`` porte le rôle manquant : le texte de repli servi à l'utilisateur
    doit pouvoir le nommer, sinon « Mon IA n'a pas de modèle associé » ne dit
    pas *lequel* — et la doc invitait à ne mapper que ``conversation`` alors
    que le tour part sur ``conversation_tools`` dès qu'un module est actif.
    """

    def __init__(self, message: str, role: "AIRole | None" = None):
        super().__init__(message)
        self.role = role


# Rôles qui, non mappés, retombent sur un autre rôle plutôt que de lever.
# ``conversation_tools`` est le tour NOMINAL (les modules SYSTEM garantissent
# une liste d'outils non vide), donc l'exiger en plus de ``conversation``
# laissait une install fraîche muette avec un message qui ne nommait pas le
# rôle manquant. Le repli est logué une fois par process.
_ROLE_FALLBACKS: dict[AIRole, AIRole] = {
    AIRole.CONVERSATION_TOOLS: AIRole.CONVERSATION,
}
# Portée process (pas instance) : les tests construisent le routeur par
# ``__new__`` sans passer par ``__init__``.
_fallbacks_logged: set[AIRole] = set()


class CacheStats:
    """Agrégat RAM du cache de prompt, par rôle.

    Les quatre chiffres (entrée, sortie, lu depuis le cache, écrit dans le
    cache) figuraient dans chaque ligne « AI call OK » et nulle part ailleurs :
    impossible de savoir, sans grep des logs, si le préfixe stable est
    réellement relu d'un tour à l'autre — la seule mesure qui dise si le
    TTL de 5 min (``ai.claude.cache_ttl``) suffit à la cadence d'un compagnon.
    Portée process, jamais persisté : c'est un instrument, pas une archive.
    """

    def __init__(self):
        self._by_role: dict[str, dict[str, int]] = {}

    def record(
        self, role_value: str, *, tokens_in: int, cache_read: int, cache_write: int,
    ) -> None:
        row = self._by_role.setdefault(
            str(role_value),
            {"calls": 0, "tokens_in": 0, "cache_read": 0, "cache_write": 0},
        )
        row["calls"] += 1
        row["tokens_in"] += max(0, int(tokens_in or 0))
        row["cache_read"] += max(0, int(cache_read or 0))
        row["cache_write"] += max(0, int(cache_write or 0))

    def snapshot(self) -> list[dict]:
        """Une ligne par rôle, avec le taux de relecture du prompt.

        ``hit_ratio`` = lu depuis le cache ÷ (entrée + lu + écrit) — la part
        du prompt qui a coûté 0,1× plutôt que 1× ou 1,25×.
        """
        out = []
        for role_value, row in sorted(self._by_role.items()):
            prompt_total = row["tokens_in"] + row["cache_read"] + row["cache_write"]
            out.append({
                "role": role_value,
                **row,
                "hit_ratio": (row["cache_read"] / prompt_total) if prompt_total else 0.0,
            })
        return out

    def reset(self) -> None:
        self._by_role.clear()


cache_stats = CacheStats()


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
        from old.backend.configs.service import config_service

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
            fallback = _ROLE_FALLBACKS.get(role)
            if fallback is not None and self._role_to_internal.get(fallback, "").strip():
                if role not in _fallbacks_logged:
                    _fallbacks_logged.add(role)
                    logger.info(
                        "Rôle '%s' non mappé : repli sur le modèle du rôle '%s'",
                        role.value, fallback.value,
                    )
                return self._resolve(fallback)
            raise UnconfiguredRoleError(
                f"Aucun modèle déclaré n'est associé au rôle '{role.value}'. "
                "Déclare un modèle dans Configuration > Déclaration des modèles "
                "puis mappe-le dans IA · Rôles.",
                role=role,
            )
        declared = self._get_declared_models()
        entry = declared.get(internal_name)
        if entry is None:
            raise UnconfiguredRoleError(
                f"Le rôle '{role.value}' pointe sur '{internal_name}' "
                "qui n'est pas (ou plus) déclaré.",
                role=role,
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
        from old.backend.configs.service import config_service

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

    # ── Cadence de fond et disjoncteur ───────────────────────────

    def _budget_de_fond(self, provider_name: str) -> int:
        """Appels de fond par heure pour ce provider (0 = illimité)."""
        from old.backend.configs.runtime import cfg_int

        return cfg_int(
            f"ai.{provider_name}.appels_de_fond_par_heure",
            _PROVIDER_FALLBACK_BUDGET_DE_FOND.get(provider_name, 0), mini=0,
        )

    def _reglage_disjoncteur(self, provider_name: str) -> tuple[int, float]:
        """``(échecs consécutifs avant ouverture, repos en s)``. 0 échec = jamais."""
        from old.backend.configs.runtime import cfg_float, cfg_int

        return (
            cfg_int(f"ai.{provider_name}.disjoncteur.echecs",
                    DISJONCTEUR_ECHECS, mini=0),
            cfg_float(f"ai.{provider_name}.disjoncteur.repos_s",
                      DISJONCTEUR_REPOS_S, mini=1.0),
        )

    @staticmethod
    def _est_appel_de_fond(role: AIRole) -> bool:
        return role in ROLES_DE_FOND or appelant_de_fond()

    def budget_de_fond_disponible(self, role: AIRole) -> bool:
        """Reste-t-il un appel de fond dans l'heure chez le provider de ce rôle ?

        À consulter AVANT de bâtir un prompt cher (un pas de chantier
        réserve son pas, un acte choisit son destinataire et rappelle sa
        mémoire). Un rôle non résolu répond oui : l'appel réel dira
        pourquoi il échoue, avec sa vraie raison. Un non est compté comme un
        refus — un consommateur qui diffère sans tenter ne doit pas rendre
        le plafond invisible sur Santé.
        """
        try:
            provider_name = self._resolve(role)[0]
        except Exception:
            return True
        try:
            self._exiger_budget_de_fond(provider_name, role.value, reserver=False)
        except BudgetDeFondEpuise as refus:
            cadence_de_fond.refuser(provider_name, role.value)
            degradations.record("ai.router: appel de fond différé", refus)
            return False
        return True

    def _exiger_budget_de_fond(self, provider_name: str, role_value: str,
                               *, reserver: bool) -> None:
        """Lève ``BudgetDeFondEpuise`` si le plafond horaire est atteint.

        ``reserver=True`` compte l'appel (ou le refus) dans la foulée, sous
        le verrou du compteur : deux appels ne partagent pas le dernier
        créneau de l'heure.
        """
        plafond = self._budget_de_fond(provider_name)
        accepte = (
            cadence_de_fond.reserver(provider_name, role_value, plafond)
            if reserver else cadence_de_fond.disponible(provider_name, plafond)
        )
        if not accepte:
            raise BudgetDeFondEpuise(
                provider_name, role_value,
                cadence_de_fond.utilises(provider_name), plafond,
            )

    def cadence_stats(self) -> dict:
        """Les deux instruments pour Système › Santé, tous providers listés."""
        noms = tuple(_PROVIDER_CLASSES)
        return {
            "fond": cadence_de_fond.snapshot(
                plafond=self._budget_de_fond, providers=noms,
            ),
            "disjoncteurs": disjoncteurs.snapshot(
                reglage=self._reglage_disjoncteur, providers=noms,
            ),
        }

    def _noter_reponse(self, provider_name: str, exc: BaseException | None) -> None:
        """Verdict du disjoncteur après un appel : panne de transport ou réponse.

        Une exception qui n'est pas une panne de transport (400, réponse
        vide, quota) est une *réponse* : elle rompt la série au même titre
        qu'un succès.
        """
        try:
            if exc is not None and est_panne_de_transport(exc):
                seuil, repos_s = self._reglage_disjoncteur(provider_name)
                if disjoncteurs.echec(provider_name, exc, seuil=seuil, repos_s=repos_s):
                    # Visible sur Santé (état, ouvertures) ; le registre de
                    # dégradation, lui, compte les appels que les
                    # consommateurs avalent — pas la décision de couper.
                    logger.error(
                        "Disjoncteur OUVERT provider=%s — %d panne(s) de "
                        "transport consécutive(s), repos %.0f s : tout appel "
                        "échoue immédiatement", provider_name, seuil, repos_s,
                    )
            else:
                disjoncteurs.succes(provider_name)
        except Exception as err:
            degradations.record("ai.router.disjoncteur", err)

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
        from old.backend.configs.service import config_service
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

        # Disjoncteur d'abord : un provider ouvert refuse sans rien consommer
        # — ni créneau, ni budget de fond. Lève ``ProviderIndisponible``.
        essai = disjoncteurs.verifier(provider_name)

        # Budget d'appels de fond, AVANT le créneau : un appel refusé ne fait
        # pas la queue. Un appel imbriqué (outil relançant le modèle depuis
        # la boucle) tourne dans l'appel déjà compté — compté une fois.
        compte_token = None
        deja_comptes = _comptes_de_fond.get()
        if self._est_appel_de_fond(role) and provider_name not in deja_comptes:
            try:
                self._exiger_budget_de_fond(provider_name, role.value, reserver=True)
            except BudgetDeFondEpuise as refus:
                if essai:
                    disjoncteurs.liberer_essai(provider_name)
                degradations.record("ai.router: appel de fond refusé", refus)
                logger.info("AI call REFUSÉ %s", refus)
                raise
            compte_token = _comptes_de_fond.set(deja_comptes | {provider_name})

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
            except BaseException as exc:
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
                if compte_token is not None:
                    _comptes_de_fond.reset(compte_token)
                # Un créneau jamais obtenu dans la borne est la signature
                # d'un provider figé qui tient le créneau : une panne de
                # transport pour le disjoncteur. Une annulation n'en est pas
                # une — l'essai est simplement rendu.
                if isinstance(exc, asyncio.TimeoutError):
                    self._noter_reponse(provider_name, exc)
                elif essai:
                    disjoncteurs.liberer_essai(provider_name)
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
                        from old.backend.ai.calibration import calibration
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
            try:
                cache_stats.record(
                    role.value, tokens_in=tokens_in,
                    cache_read=cache_read, cache_write=cache_write,
                )
            except Exception as exc:
                degradations.record("ai.router.cache_stats", exc)

            logger.info(
                "AI call OK     role=%-22s internal=%-18s provider=%-7s model=%-30s "
                "prompt=%5d chars  response=%5d chars  tok=%d/%d  cache=%d/%d  "
                "$%.5f  %7.0f ms (attente %.0f ms)",
                role.value, internal_name, provider_name, model,
                prompt_chars, len(text),
                tokens_in, tokens_out, cache_read, cache_write,
                cost_usd, elapsed_ms, wait_ms,
            )
            self._noter_reponse(provider_name, None)
            return result

        except asyncio.TimeoutError as exc:
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
            self._noter_reponse(provider_name, exc)
            raise

        except asyncio.CancelledError:
            # L'annulation vient de l'extérieur — un ``wait_for`` plus court
            # chez l'appelant, un SIGTERM pendant le tour, une tâche
            # moissonnée à l'arrêt. Elle n'est pas une ``Exception`` : sans
            # cette branche, une boucle d'outils annulée à l'itération six
            # comptait pour zéro, exactement le cas où les plafonds servent.
            # Le tour de conversation vivait dans ce cas en permanence tant
            # que le processeur posait sa propre borne autour du routeur.
            elapsed_ms = (time.monotonic() - t_call) * 1000
            logger.warning(
                "AI call ANNULÉ role=%-22s internal=%-18s provider=%-7s model=%-30s "
                "prompt=%5d chars  %7.0f ms (attente %.0f ms)",
                role.value, internal_name, provider_name, model,
                prompt_chars, elapsed_ms, wait_ms,
            )
            self._record_partial_usage(
                role, provider_name, model, project_id, note="ANNULÉ",
            )
            # Aucun verdict : l'annulation ne dit rien du provider.
            if essai:
                disjoncteurs.liberer_essai(provider_name)
            raise

        except Exception as exc:
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
            self._noter_reponse(provider_name, exc)
            raise

        finally:
            if slot_token is not None:
                _held_providers.reset(slot_token)
                semaphore.release()
            if compte_token is not None:
                _comptes_de_fond.reset(compte_token)
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
        # Une image compte en jetons sans compter en caractères : calibrer
        # chars→tokens sur un appel de vision polluait le ratio de tout le
        # provider (un prompt long + une petite image passait le filtre
        # [1, 12]) et rétrécissait le budget L3 de la conversation.
        calibrate = not bool(kwargs.get("attachments"))

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
            calibrate=calibrate,
        )

    # ── Structured conversation turns ────────────────────────────

    async def chat(self, role: AIRole, prompt, **kwargs) -> str:
        """Route a structured ``ChatPrompt`` turn.

        Every provider consumes the structured form (cacheable prefix + real
        message turns); ``legacy_pair()`` only serves the router's own
        character estimate.
        """
        timeout = kwargs.pop("timeout", None)
        system_est, user_est = prompt.legacy_pair()

        async def _invoke(provider, model, temperature, max_tokens):
            kwargs.setdefault("temperature", temperature)
            if max_tokens is not None:
                kwargs.setdefault("max_tokens", max_tokens)
            text = await provider.complete_chat(prompt=prompt, model=model, **kwargs)
            return text, text

        return await self._metered_call(
            role, system_est, user_est, _invoke, timeout=timeout,
        )

    async def chat_with_tools(
        self, role: AIRole, prompt, tools: list, **kwargs,
    ) -> tuple[str, list[str]]:
        """Route a tool-enabled structured turn, metered like the rest.

        Renvoie ``(texte, noms_des_outils_appelés)``. La boucle d'outils est
        interne au provider ; ce qui compte ici est qu'elle soit encadrée par
        le quota, comptabilisée dans son intégralité, et bornée dans le temps.
        """
        timeout = kwargs.pop("timeout", None)
        system_est, user_est = prompt.legacy_pair()

        async def _invoke(provider, model, temperature, max_tokens):
            kwargs.setdefault("temperature", temperature)
            if max_tokens is not None:
                kwargs.setdefault("max_tokens", max_tokens)
            text, called = await provider.complete_chat_with_tools(
                prompt=prompt, model=model, tools=tools or [], **kwargs,
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
