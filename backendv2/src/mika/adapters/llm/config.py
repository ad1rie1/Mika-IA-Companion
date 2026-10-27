"""Configurer les modèles : fournisseurs déclarés, rôles routés, passerelle
rechargeable à chaud.

Une installation neuve n'a aucun modèle : chaque tour échoue proprement
(« aucun modèle associé au rôle… ») jusqu'à ce qu'on en déclare un. Le
**premier fournisseur déclaré sert « répondre » d'office** (tous les autres
rôles y retombent déjà) : déclarer un fournisseur suffit pour qu'elle parle,
il n'y a pas de seconde étape à oublier. « Configurée » veut dire « elle peut
répondre » — le rôle ``reply`` se résout —, jamais seulement « un fournisseur
existe ». Les clés ne passent jamais par ce module en clair ailleurs qu'à la
construction du client.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mika.adapters.llm.claude import THINKING_OUTPUT_TOKENS
from mika.adapters.llm.gateway import TRACES_KEPT, Gateway, LLMTrace, Trial, UnconfiguredRole
from mika.kernel import forms
from mika.kernel.clock import Clock
from mika.kernel.forms import Knob
from mika.ports.llm import LLMBackend, LLMRequest, LLMResponse, MissingPersona
from mika.ports.llm_budget import LLMLimits
from mika.vocab.episodes import FALLBACKS, TRIAL_ROLE, VOICE_ROLES, Role

#: le seul rôle qu'il faut servir : tout ce qui parle, et les utilitaires, y retombent
REPLY = str(Role.REPLY)
#: les rôles qui existent (une route vers un autre nom ne servirait jamais rien)
ROLES = tuple(str(r) for r in Role)
#: les types de fournisseur dont le modèle réfléchit (l'API Claude sur une famille 5.x, la CLI) : leur sortie réserve
#: jusqu'à ``THINKING_OUTPUT_TOKENS``, au plus la moitié du contexte déclaré — sans contexte dit, le leur est
#: ``THINKING_CONTEXT_TOKENS`` plutôt que le défaut commun, qui leur laisserait la moitié de leur prompt
THINKING_KINDS = frozenset({"claude", "claude_code"})
THINKING_CONTEXT_TOKENS = 40_000
#: le plus petit contexte qu'un fournisseur peut déclarer (une fenêtre lue plus petite n'est pas gardée)
MIN_CONTEXT_TOKENS = 2_000

log = logging.getLogger("mika.llm.config")

Kind = Literal["claude", "claude_code", "openai", "ollama", "ollama_cloud"]


_KINDS = (("claude", "Claude (Anthropic)"), ("claude_code", "Claude Code (la CLI, son login)"),
          ("openai", "Compatible OpenAI"), ("ollama", "Ollama (local)"), ("ollama_cloud", "Ollama Cloud"))
_AUTHS = (("abonnement", "le login de la CLI (abonnement)"), ("cle_api", "une clé d'API Console"))
#: le nom d'un type de fournisseur, pour un opérateur (« Ollama Cloud »)
KIND_LABELS = {"claude": "Claude, par l'API", "claude_code": "Claude Code (la CLI)", "openai": "Compatible OpenAI",
               "ollama": "Ollama, sur cette machine", "ollama_cloud": "Ollama Cloud"}


def tokens_fr(n: int) -> str:
    """Un nombre de jetons tel qu'on le lit (« 1 000 000 »)."""
    return f"{n:,}".replace(",", " ")


@dataclass(frozen=True, slots=True)
class ModelLimits:
    """Ce qu'accepte un modèle, dit par son fournisseur : sa fenêtre et sa plus longue réponse, en jetons (0 : il
    ne le dit pas)."""

    window: int = 0
    output: int = 0


class BackendSpec(BaseModel):
    """Un fournisseur de modèles déclaré (les bornes et libellés servent au
    formulaire de la console ; la validation reste celle du modèle).

    Le formulaire ne montre que ce qui sert au type choisi : la clé d'API d'un
    service hébergé (ou de Claude Code sur une clé), le modèle choisi dans la liste
    du fournisseur. Ce que le SDK ou la CLI savent déjà
    (adresse, hôte, commande, dossier) est rangé dans « Options avancées »."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Annotated[Kind, Knob(label="Type", help="Le service qui fait tourner le modèle. Claude Code passe par la "
                                             "CLI et son propre login (jamais un jeton) ; Ollama tourne sur ta "
                                             "machine.", group="Le fournisseur", choices=_KINDS, advanced=False,
                               order=10)]
    model: Annotated[str, Knob(label="Modèle", help="Choisi dans la liste que propose le fournisseur (elle se "
                                              "charge d'elle-même une fois le fournisseur enregistré).",
                               group="Le fournisseur", loader="models", advanced=False, order=20)]
    context_tokens: Annotated[int, Knob(label="Contexte (jetons)",
        help="Ce que chaque appel envoie au plus : entrée, outils et réserve de sortie. Elle le remplit (le fil, "
             "les résultats d'outils) : c'est un budget, jamais plus que la fenêtre du modèle. Un modèle qui "
             "réfléchit (Claude 5.x, Fable) réserve jusqu'à 16 384 jetons de sortie — au plus la moitié du "
             "contexte : compter 40 000 au moins pour lui laisser son prompt entier.",
        lo=MIN_CONTEXT_TOKENS, hi=1_000_000, step=1_000, group="Budgets", advanced=False, order=21)] = \
        Field(default=24_000, ge=MIN_CONTEXT_TOKENS, le=1_000_000)
    max_output_tokens: Annotated[int, Knob(label="Sortie max. (jetons)",
        help="Plafond de chaque réponse, tous rôles confondus, jamais plus que la réponse du modèle. 0 : la "
             "limite demandée par le rôle.",
        lo=0, hi=65_536, group="Budgets", advanced=False, order=22)] = Field(default=0, ge=0, le=65_536)
    chars_per_token: Annotated[float, Knob(label="Caractères par jeton estimé",
        help="Estimation du contexte. Réduire cette valeur pour réserver davantage de place.",
        lo=1.0, hi=4.0, step=0.1, group="Budgets", order=23)] = Field(default=3.6, ge=1.0, le=4.0)
    # ce que le fournisseur dit du modèle choisi, lu quand la fiche s'enregistre (ADR 0136) : des bornes, jamais
    # des valeurs proposées — elle remplit le contexte qu'on lui déclare, et Ollama en fait sa mémoire
    detected_window: Annotated[int, Knob(label="Fenêtre du modèle (jetons)",
        help="Lue chez le fournisseur quand la fiche s'enregistre : le contexte n'en dépasse jamais (plus grand, "
             "il y est ramené). 0 : inconnue — Claude Code, ou un fournisseur qui ne la dit pas.",
        lo=0, hi=10_000_000, group="Budgets", readonly=True, advanced=False, order=24)] = Field(default=0, ge=0)
    detected_output: Annotated[int, Knob(label="Réponse du modèle (jetons)",
        help="Sa plus longue réponse, lue avec sa fenêtre : la sortie max. n'en dépasse jamais. 0 : inconnue.",
        lo=0, hi=10_000_000, group="Budgets", readonly=True, advanced=False, order=25)] = Field(default=0, ge=0)
    detected_for: Annotated[str, Knob(label="Lu pour", help="Le type et le modèle dont la fenêtre a été lue (vide : "
                                      "pas encore demandé) ; un autre modèle les oublie.", widget="hidden",
                                      readonly=True, order=26)] = ""

    auth: Annotated[Literal["abonnement", "cle_api"], Knob(
        label="Connexion", help="Le serveur ne voit jamais le login : la CLI s'authentifie elle-même. Avec une clé d'API "
                                "Console, la clé se déclare juste dessous.", group="Connexion", choices=_AUTHS,
        advanced=False, order=25, only=(("kind", ("claude_code",)),))] = "abonnement"
    api_key: Annotated[str, Knob(label="Clé d'API", help="Chiffrée au repos, jamais réaffichée. Vide : inchangée.",
                                 group="Connexion", secret=True, advanced=False, order=30,
                                 only_any=((("kind", ("claude", "openai", "ollama_cloud")),),
                                           (("kind", ("claude_code",)), ("auth", ("cle_api",)))))] = ""
    workspace: Annotated[str, Knob(label="Espace de travail", help="L'identifiant de l'espace de travail (wrkspc_…) "
                                   "quand la clé n'est attachée à aucun (une clé « sk-ant-usr- »). Vide : celui de la "
                                   "clé.", group="Connexion", order=31, only=(("kind", ("claude",)),))] = ""
    base_url: Annotated[str, Knob(label="Adresse du serveur", help="Seulement pour un serveur compatible OpenAI "
                                                                   "qui n'est pas OpenAI. Vide : OpenAI.",
                                  group="Options avancées", order=40, only=(("kind", ("openai",)),))] = ""
    host: Annotated[str, Knob(label="Hôte", help="Vide : http://localhost:11434 en local, https://ollama.com pour "
                                                "le cloud — il n'y a presque jamais à y toucher.",
                              group="Options avancées", order=40, only=(("kind", ("ollama", "ollama_cloud")),))] = ""
    slots: Annotated[int, Knob(label="Créneaux", help="Appels simultanés (0 : 1 en local, 4 hébergé).", lo=0, hi=32,
                               group="Options avancées", order=50)] = Field(default=0, ge=0, le=32)
    temperature: Annotated[float | None, Knob(label="Température", help="Vide : celle du fournisseur.", lo=0.0,
                                              hi=2.0, step=0.05, group="Options avancées", order=60,
                                              only=(("kind", ("claude", "openai", "ollama", "ollama_cloud")),))] \
        = None
    cache_ttl: Annotated[Literal["5m", "1h"], Knob(label="Durée du cache", help="Combien de temps l'API garde le "
                                                   "début du prompt en cache : une heure coûte plus à l'écriture, "
                                                   "moins quand elle parle souvent.",
                                                   choices=(("5m", "5 minutes"), ("1h", "1 heure")),
                                                   group="Options avancées", order=70,
                                                   only=(("kind", ("claude",)),))] = "5m"
    think: Annotated[bool, Knob(label="Laisser réfléchir", help="Les modèles à raisonnement (lents en local).",
                                group="Options avancées", order=80, only=(("kind", ("ollama", "ollama_cloud")),))] \
        = False
    max_reply_tokens: Annotated[int, Knob(label="Réponse max. (jetons)", help="0 : défaut du type (768 en local, "
                                          "2048 dans le cloud).", lo=0, hi=65_536, group="Options avancées",
                                          order=90, only=(("kind", ("ollama", "ollama_cloud")),))] = \
        Field(default=0, ge=0)
    claude_bin: Annotated[str, Knob(label="Commande claude", help="Vide : « claude » dans le PATH, sinon "
                                                                  "~/.local/bin/claude.", group="Options avancées",
                                    order=100, only=(("kind", ("claude_code",)),))] = ""
    config_dir: Annotated[str, Knob(label="Dossier de la CLI", help="Vide : la CLI telle que tu l'as connectée. "
                                                                    "Rempli : un dossier à part, où tu te "
                                                                    "connectes avec « mika claude-code login ».",
                                    group="Options avancées", order=110, only=(("kind", ("claude_code",)),))] = ""
    effort: Annotated[str, Knob(label="Effort de réflexion", help="Combien le modèle réfléchit avant de répondre "
                                "(--effort de la CLI ; par l'API, la réflexion adaptative à cet effort). Vide : le "
                                "défaut de la CLI, et pas de réflexion par l'API.",
                                choices=(("", "défaut de la CLI"), ("low", "faible"), ("medium", "moyen"),
                                         ("high", "élevé"), ("xhigh", "très élevé"), ("max", "maximal")),
                                group="Options avancées", order=115, only=(("kind", ("claude_code", "claude")),))] = ""
    quota_ceiling: Annotated[float, Knob(label="Réserve d'abonnement", help="Au-delà de cet usage de "
                                         "l'abonnement, ses appels de fond sont suspendus (la conversation "
                                         "n'est jamais retenue). 0,8 = 80 % ; 0 : pas de réserve.", lo=0.0,
                                         hi=1.0, step=0.05, group="Options avancées", order=120,
                                         only=(("kind", ("claude_code",)),))] = \
        Field(default=0.8, ge=0.0, le=1.0)

    @model_validator(mode="before")
    @classmethod
    def _room_to_think(cls, data: Any) -> Any:
        """Un fournisseur Claude sans contexte déclaré en reçoit ``THINKING_CONTEXT_TOKENS`` : son modèle réserve
        jusqu'à 16 384 jetons de sortie, et le défaut commun (24 000) ne lui laissait que la moitié de son prompt
        (audit du 2026-10-26). Une valeur dite n'est jamais changée ; ``build_gateway`` la dit si elle est courte."""
        if isinstance(data, Mapping) and data.get("kind") in THINKING_KINDS and "context_tokens" not in data:
            return {**data, "context_tokens": THINKING_CONTEXT_TOKENS}
        return data

    @model_validator(mode="before")
    @classmethod
    def _retired_fallback(cls, data: Any) -> Any:
        # Une ancienne fiche reste lisible ; la prochaine sauvegarde retire l'option.
        if isinstance(data, Mapping) and "fallback" in data:
            return {k: v for k, v in data.items() if k != "fallback"}
        return data

    @model_validator(mode="before")
    @classmethod
    def _detected_follows_model(cls, data: Any) -> Any:
        """Ce qui a été lu d'un modèle ne vaut que pour lui : un autre modèle (ou le même nom chez un autre type de
        fournisseur) oublie sa fenêtre et sa réponse, relues au prochain enregistrement."""
        if isinstance(data, Mapping) and data.get("detected_for") and \
                data["detected_for"] != f"{data.get('kind')}:{data.get('model')}":
            return {**data, "detected_window": 0, "detected_output": 0, "detected_for": ""}
        return data

    @model_validator(mode="after")
    def _output_fits_context(self):
        if self.max_output_tokens >= self.context_tokens:
            raise ValueError("la sortie maximale doit être inférieure au contexte du fournisseur")
        return self

    @model_validator(mode="after")
    def _within_model(self):
        if self.detected_window and self.context_tokens > self.detected_window:
            raise ValueError(f"le contexte ({tokens_fr(self.context_tokens)} jetons) dépasse la fenêtre de ce modèle "
                             f"({tokens_fr(self.detected_window)})")
        if self.detected_output and self.max_output_tokens > self.detected_output:
            raise ValueError(f"la sortie maximale ({tokens_fr(self.max_output_tokens)} jetons) dépasse la plus "
                             f"longue réponse de ce modèle ({tokens_fr(self.detected_output)})")
        return self

    @property
    def limits(self) -> LLMLimits:
        return LLMLimits(self.context_tokens, self.max_output_tokens, self.chars_per_token)

    @property
    def detection_key(self) -> str:
        """Ce dont ``detected_for`` garde la trace : le type de fournisseur et le modèle."""
        return f"{self.kind}:{self.model}"

    def fitted(self, got: ModelLimits) -> tuple[BackendSpec, list[str]]:
        """La fiche avec ce que son fournisseur dit du modèle : sa fenêtre et sa réponse gardées, le contexte et la
        sortie max. ramenés dessous s'ils les dépassent — jamais relevés (ADR 0136). Rend aussi ce qui a changé, en
        mots. Une fenêtre plus petite que ``MIN_CONTEXT_TOKENS`` n'est pas gardée."""
        window = got.window if got.window >= MIN_CONTEXT_TOKENS else 0
        raw = {**self.model_dump(), "detected_window": window, "detected_output": got.output,
               "detected_for": self.detection_key}
        said = []
        if got.window and not window:
            said.append(f"sa fenêtre lue ({tokens_fr(got.window)} jetons) est trop petite pour elle : pas gardée")
        if window and self.context_tokens > window:
            raw["context_tokens"] = window
            said.append(f"contexte ramené à {tokens_fr(window)} jetons, la fenêtre du modèle")
        output = min(self.max_output_tokens, got.output) if got.output else self.max_output_tokens
        if output >= raw["context_tokens"]:
            output = raw["context_tokens"] // 2
        if output != self.max_output_tokens:
            raw["max_output_tokens"] = output
            said.append(f"sortie max. ramenée à {tokens_fr(output)} jetons")
        return BackendSpec.model_validate(raw), said

    @property
    def local(self) -> bool:
        return self.kind == "ollama"

    def redacted(self) -> dict[str, Any]:
        """Ce qui se montre de lui : la clé masquée, et seulement les champs qui servent à son type (la
        connexion d'un abonnement Claude Code ne se lit pas sur un Ollama)."""
        data = self.model_dump()
        data["api_key"] = "••••" if self.api_key else ""
        shown = {f.path for f in forms.describe(BackendSpec) if forms.visible(f, data)}
        return {k: v for k, v in data.items() if k in shown}


#: les rôles, en français (voix d'abord)
ROLE_LABELS = {"reply": "répondre (voix)", "initiative": "prendre la parole (voix)", "step": "travailler (voix)",
               "murmur": "murmurer (voix)", "journal": "tenir son journal (voix)", "dream": "rêver (voix)",
               "narrative": "se raconter (voix)", "extract": "retenir (mémoire)", "validate": "vérifier",
               "profile": "comprendre les gens", "interpret": "interpréter", "triage": "trier le courrier",
               "caption": "décrire une image", "compact": "résumer le fil", "plan": "planifier",
               "project": "travailler sur un projet (voix)", "job": "exécuter un projet (impersonnel)",
               "polish": "rendre naturel (voix, seconde passe)", "pro": "répondre en mode pro (voix)",
               "character": "écrire son caractère (d'après sa matrice)",
               TRIAL_ROLE: "rejouer une parole (essai de la console)"}


class LLMConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backends: Annotated[dict[str, BackendSpec], Knob(
        label="Fournisseurs", help="Les services déclarés ; les rôles désignent l'un d'eux par son nom.",
        advanced=False, order=10)] = \
        Field(default_factory=dict)
    #: rôle → nom de fournisseur déclaré
    routes: Annotated[dict[str, str], Knob(
        label="Rôles", help="Quel fournisseur sert chaque rôle. Les rôles « voix » reçoivent sa persona ; un rôle "
                             "sans fournisseur retombe sur son rôle de repli.",
        keys=tuple((str(r), ROLE_LABELS.get(str(r), str(r))) for r in Role), choices_from="backends",
        advanced=False, order=20)] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _provider_budgets(cls, data: Any) -> Any:
        """Migration de l'ancien budget global ; une valeur explicite du fournisseur est prioritaire."""
        if not isinstance(data, Mapping) or "context_tokens" not in data:
            return data
        data = dict(data)
        legacy = data.pop("context_tokens")
        backends = {}
        for name, spec in (data.get("backends") or {}).items():
            raw = spec.model_dump(exclude_unset=True) if isinstance(spec, BackendSpec) else dict(spec)
            backends[name] = {"context_tokens": legacy, **raw}
        return {**data, "backends": backends}

    @model_validator(mode="before")
    @classmethod
    def _reply_served(cls, data: Any) -> Any:
        """Le premier fournisseur déclaré sert « répondre » d'office : un fournisseur sans rôle donnait une
        configuration « valide » où chaque tour échouait. Un choix explicite (vers un fournisseur déclaré)
        n'est jamais changé ; un fournisseur retiré qui servait « répondre » passe la main au premier qui
        reste."""
        if not isinstance(data, Mapping):
            return data
        backends = data.get("backends") or {}
        routes = data.get("routes") or {}
        if not isinstance(backends, Mapping) or not isinstance(routes, Mapping) or not backends:
            return data
        if routes.get(REPLY) in backends:
            return data
        return {**data, "routes": {**dict(routes), REPLY: str(next(iter(backends)))}}

    def problems(self) -> list[str]:
        out = []
        for role, name in self.routes.items():
            if role not in ROLES:
                out.append(f"le rôle « {role} » n'existe pas (les rôles : {', '.join(ROLES)}) — seul « {REPLY} » "
                           "est nécessaire, les autres y retombent")
            elif name not in self.backends:
                out.append(f"le rôle « {role} » vise un fournisseur inconnu : {name}")
        if self.backends and REPLY not in self.routes:
            out.append(f"aucun fournisseur ne sert « {REPLY} » (répondre) : chaque tour échouerait")
        for name, spec in self.backends.items():
            if spec.kind == "claude_code" and spec.auth == "cle_api" and not spec.api_key:
                out.append(f"le fournisseur « {name} » (clé d'API) n'a pas de clé")
        return out


#: une issue d'appel (``LLMTrace.outcome`` : ``timeout``, ``error:<classe>``) en mots, par ce que dit le nom
_FAILURES_FR = (("Connect", "connexion impossible"), ("Timeout", "délai dépassé"),
                ("Authentication", "clé refusée"), ("Permission", "accès refusé"),
                ("RateLimit", "limite de débit ou quota atteints"), ("NotFound", "modèle introuvable"),
                ("Quota", "quota atteint"))


def failure_fr(outcome: str) -> str:
    """Pourquoi un appel a échoué, en mots (« connexion impossible », « délai dépassé »)."""
    if outcome == "timeout":
        return "délai dépassé"
    if outcome == "expired":
        return "plus de temps devant l'épisode"
    name = outcome.partition(":")[2] if outcome.startswith("error:") else outcome
    for marker, text in _FAILURES_FR:
        if marker.lower() in name.lower():
            return text
    return f"erreur {name}" if name else "erreur"


def build_backend(name: str, spec: BackendSpec, *, relay: Any = None, relay_base: Any = None,
                  work_dir: Any = None) -> LLMBackend:
    # imports ici : chaque fournisseur tire son SDK, qui peut manquer (extra « llm »)
    if spec.kind == "claude_code":
        from mika.adapters.llm.claude_code import ClaudeCodeBackend  # noqa: PLC0415
        from mika.adapters.mcp.relay import Relay  # noqa: PLC0415

        # « is None », pas « or » : un relais sans session est vide, donc faux (``__len__``),
        # et « or » en créait un autre, jamais monté — la CLI recevait 404 sur le sien
        return ClaudeCodeBackend(spec.model, relay=relay if relay is not None else Relay(),
                                 relay_base=relay_base, name=name,
                                 auth=spec.auth, api_key=spec.api_key, claude_bin=spec.claude_bin,
                                 config_dir=spec.config_dir, work_dir=work_dir, quota_ceiling=spec.quota_ceiling,
                                 effort=spec.effort)
    if spec.kind == "claude":
        from mika.adapters.llm.claude import ClaudeBackend  # noqa: PLC0415

        return ClaudeBackend(spec.api_key, spec.model, cache_ttl=spec.cache_ttl, temperature=spec.temperature,
                             name=name, workspace=spec.workspace, effort=spec.effort)
    if spec.kind == "openai":
        from mika.adapters.llm.openai_compat import OpenAICompatBackend  # noqa: PLC0415

        return OpenAICompatBackend(spec.api_key, spec.model, base_url=spec.base_url or None,
                                   temperature=spec.temperature, name=name)
    if spec.kind == "ollama":
        from mika.adapters.llm.ollama import OllamaBackend  # noqa: PLC0415

        return OllamaBackend(spec.model, host=spec.host or "http://localhost:11434", think=spec.think,
                             max_reply_tokens=spec.max_output_tokens or spec.max_reply_tokens or 768,
                             temperature=spec.temperature, name=name, context_tokens=spec.context_tokens)
    from mika.adapters.llm.ollama import OllamaCloudBackend  # noqa: PLC0415

    return OllamaCloudBackend(spec.model, spec.api_key, host=spec.host or "https://ollama.com", think=spec.think,
                              max_reply_tokens=spec.max_output_tokens or spec.max_reply_tokens or 2048,
                              temperature=spec.temperature,
                              name=name, context_tokens=spec.context_tokens)


def price_kind(spec: BackendSpec) -> str:
    """Le tarif d'un fournisseur : Claude Code sur l'abonnement ne se paie pas au jeton."""
    if spec.kind == "claude_code":
        return "claude_code" if spec.auth == "abonnement" else "claude"
    return spec.kind


def build_gateway(cfg: LLMConfig, clock: Clock, *, on_trace: Callable[[LLMTrace], None] | None = None,
                  make: Callable[[str, BackendSpec], LLMBackend] | None = None, relay: Any = None,
                  relay_base: Any = None, work_dir: Any = None) -> Gateway:
    if make is None:
        def make(name: str, spec: BackendSpec) -> LLMBackend:
            return build_backend(name, spec, relay=relay, relay_base=relay_base, work_dir=work_dir)
    backends = {name: make(name, spec) for name, spec in sorted(cfg.backends.items())}
    for name, spec in sorted(cfg.backends.items()):
        if spec.kind in THINKING_KINDS and spec.context_tokens // 2 < THINKING_OUTPUT_TOKENS:
            log.warning("fournisseur « %s » : un contexte de %d jetons ne laisse que %d jetons à son prompt — son "
                        "modèle réserve jusqu'à %d jetons de sortie, au plus la moitié du contexte ; compter %d au "
                        "moins (réglage « Contexte »)", name, spec.context_tokens,
                        spec.context_tokens - spec.context_tokens // 2, THINKING_OUTPUT_TOKENS,
                        THINKING_CONTEXT_TOKENS)
    slots = {name: spec.slots or (1 if spec.local else 4) for name, spec in cfg.backends.items()}
    preempt = frozenset(name for name, spec in cfg.backends.items() if slots[name] == 1)
    return Gateway(backends, dict(cfg.routes), clock=clock, voice_roles=frozenset(str(r) for r in VOICE_ROLES),
                   fallbacks={str(k): str(v) for k, v in FALLBACKS.items()}, slots=slots, preempt=preempt,
                   on_trace=on_trace, pricing={n: (price_kind(s), s.cache_ttl) for n, s in cfg.backends.items()},
                   limits={n: s.limits for n, s in cfg.backends.items()})


class LiveGateway:
    """La passerelle en service, remplaçable sans redémarrer (nouvelle clé,
    nouveau modèle). Sans configuration, tout appel échoue proprement. Une boucle
    d'outils ouverte finit sur la passerelle où elle a commencé : remplacée, celle-ci
    sert encore ses boucles (et ses appels en cours), puis s'efface (ADR 0142)."""

    def __init__(self, gateway: Gateway | None = None) -> None:
        self._inner = gateway
        #: les passerelles remplacées qui tiennent encore quelque chose (``Gateway.busy``)
        self._retired: list[Gateway] = []
        self.traces: deque[LLMTrace] = deque(maxlen=TRACES_KEPT)

    def set(self, gateway: Gateway | None) -> None:
        old, self._inner = self._inner, gateway
        if old is not None and old is not gateway:
            self._retired.append(old)
        self._prune()

    def _prune(self) -> None:
        self._retired = [g for g in self._retired if g.busy()]

    def _serving(self, req: LLMRequest) -> Gateway | None:
        """La passerelle de ``req`` : celle d'avant qui tient sa boucle ouverte, sinon celle en service."""
        return next((g for g in self._retired if g.continues(req)), self._inner)

    def budget(self, role: str, max_tokens: int):
        return self._inner.budget(role, max_tokens) if self._inner is not None else LLMLimits().budget(max_tokens)

    @property
    def configured(self) -> bool:
        """Peut-elle parler ? Le rôle « répondre » se résout vers un fournisseur déclaré. Un fournisseur
        déclaré sans rôle ne suffit pas : chaque tour échouerait."""
        return bool(self.serving(REPLY))

    def serving(self, role: str) -> str:
        """Le fournisseur qui sert vraiment ce rôle (replis compris) ; « » : aucun."""
        if self._inner is None:
            return ""
        try:
            return self._inner.resolve(role)
        except UnconfiguredRole:
            return ""

    def held(self, role: str, priority: int = 1) -> str:
        """Un appel de ce rôle serait-il refusé d'avance (``Gateway.held``) ? « » : il passerait."""
        return self._inner.held(role, priority) if self._inner is not None else ""

    def holding(self) -> list[tuple[str, str]]:
        """Les fournisseurs qui refusent en ce moment leurs appels de fond (``Gateway.holding``)."""
        return self._inner.holding() if self._inner is not None else []

    def failing(self, role: str, now: int, window_us: int) -> tuple[str, int, str] | None:
        """Le fournisseur de ce rôle ne répond plus : ses derniers appels (dans ``window_us``) ont tous échoué,
        sans un succès depuis. Rend ``(fournisseur, depuis quand, cause)`` — la cause en mots —, ou ``None``
        (il répond, ou personne ne l'a appelé récemment). Une annulation ou une préemption ne compte pas :
        ce n'est pas le fournisseur qui a manqué."""
        since, backend, cause = 0, "", ""
        for tr in reversed(list(self.traces)):  # une copie : un appel peut s'ajouter pendant la lecture
            if tr.role != role or tr.outcome in ("cancelled", "preempted"):
                continue
            if now - tr.at > window_us or tr.outcome == "ok":
                break
            since, backend, cause = tr.at, backend or tr.backend, cause or failure_fr(tr.outcome)
        return (backend, since, cause) if since else None

    def routes(self) -> Mapping[str, str]:
        return dict(self._inner.routes) if self._inner is not None else {}

    def status(self) -> list[dict[str, Any]]:
        """L'état vivant de chaque fournisseur (vide sans configuration)."""
        return self._inner.status() if self._inner is not None else []

    def resolution(self) -> dict[str, str]:
        """Rôle → fournisseur qui le sert vraiment (« » : aucun)."""
        roles = [str(r) for r in Role]
        return self._inner.resolution(roles) if self._inner is not None else dict.fromkeys(roles, "")

    def is_voice(self, role: str) -> bool:
        return role in {str(r) for r in VOICE_ROLES}

    def defers_tools(self, role: str) -> bool:
        """Le fournisseur de ce rôle sait-il différer des outils (``Gateway.defers_tools``) ? Sans configuration :
        oui (l'appel échouera de toute façon). Sans ce relais, le pipeline n'avait rien à demander et concluait
        « oui » : Ollama recevait tous ses outils *et* « ils ne sont pas chargés, cherche-les » (2026-10-04)."""
        return self._inner.defers_tools(role) if self._inner is not None else True

    async def call(self, req: LLMRequest) -> LLMResponse:
        if self.is_voice(req.role) and req.persona is None:
            raise MissingPersona(f"le rôle voix « {req.role} » exige une persona")
        gateway = self._serving(req)
        if gateway is None:
            raise UnconfiguredRole(req.role)
        try:
            return await gateway.call(req)
        finally:
            self._prune()

    async def try_on(self, name: str, req: LLMRequest) -> Trial:
        """Un essai de la console sur le fournisseur ``name`` (voir ``Gateway.try_on``)."""
        if self._inner is None:
            return Trial(name, error="aucun modèle n'est configuré")
        return await self._inner.try_on(name, req)

    def release(self, call_id: str) -> None:
        """La boucle d'outils ``call_id`` est finie (voir ``Gateway.release``), où qu'elle ait tourné."""
        for gateway in (*self._retired, self._inner):
            if gateway is not None:
                gateway.release(call_id)
        self._prune()

    async def aclose(self) -> None:
        """Arrête ce que les fournisseurs tiennent encore (les CLI de Claude Code), ceux d'avant compris."""
        for gateway in (*self._retired, self._inner):
            for backend in (gateway.backends.values() if gateway is not None else ()):
                close = getattr(backend, "aclose", None)
                if close is not None:
                    await close()
