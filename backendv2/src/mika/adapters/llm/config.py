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

from collections import deque
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mika.adapters.llm.gateway import TRACES_KEPT, Gateway, LLMTrace, UnconfiguredRole
from mika.kernel import forms
from mika.kernel.clock import Clock
from mika.kernel.forms import Knob
from mika.ports.llm import LLMBackend, LLMRequest, LLMResponse, MissingPersona
from mika.vocab.episodes import FALLBACKS, VOICE_ROLES, Role

#: le seul rôle qu'il faut servir : tout ce qui parle, et les utilitaires, y retombent
REPLY = str(Role.REPLY)
#: les rôles qui existent (une route vers un autre nom ne servirait jamais rien)
ROLES = tuple(str(r) for r in Role)

Kind = Literal["claude", "claude_code", "openai", "ollama", "ollama_cloud"]


_KINDS = (("claude", "Claude (Anthropic)"), ("claude_code", "Claude Code (la CLI, son login)"),
          ("openai", "Compatible OpenAI"), ("ollama", "Ollama (local)"), ("ollama_cloud", "Ollama Cloud"))
_AUTHS = (("abonnement", "le login de la CLI (abonnement)"), ("cle_api", "une clé d'API Console"))


class BackendSpec(BaseModel):
    """Un fournisseur de modèles déclaré (les bornes et libellés servent au
    formulaire de la console ; la validation reste celle du modèle).

    Le formulaire ne montre que ce qui sert au type choisi : la clé d'API d'un
    service hébergé (ou de Claude Code sur une clé), le modèle choisi dans la liste
    du fournisseur, le repli parmi les autres. Ce que le SDK ou la CLI savent déjà
    (adresse, hôte, commande, dossier) est rangé dans « Options avancées »."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Annotated[Kind, Knob(label="Type", help="Le service qui fait tourner le modèle. Claude Code passe par la "
                                             "CLI et son propre login (jamais un jeton) ; Ollama tourne sur ta "
                                             "machine.", group="Le fournisseur", choices=_KINDS, advanced=False,
                               order=10)]
    model: Annotated[str, Knob(label="Modèle", help="Choisi dans la liste que propose le fournisseur (elle se "
                                              "charge d'elle-même une fois le fournisseur enregistré).",
                               group="Le fournisseur", loader="models", advanced=False, order=20)]
    auth: Annotated[Literal["abonnement", "cle_api"], Knob(
        label="Connexion", help="Le serveur ne voit jamais le login : la CLI s'authentifie elle-même. Avec une clé d'API "
                                "Console, la clé se déclare juste dessous.", group="Connexion", choices=_AUTHS,
        advanced=False, order=25, only=(("kind", ("claude_code",)),))] = "abonnement"
    api_key: Annotated[str, Knob(label="Clé d'API", help="Chiffrée au repos, jamais réaffichée. Vide : inchangée.",
                                 group="Connexion", secret=True, advanced=False, order=30,
                                 only_any=((("kind", ("claude", "openai", "ollama_cloud")),),
                                           (("kind", ("claude_code",)), ("auth", ("cle_api",)))))] = ""
    fallback: Annotated[str, Knob(label="Repli", help="Le fournisseur qui prend le relais quand celui-ci échoue "
                                                      "(non connecté, quota, panne). Aucun : l'appel échoue.",
                                  group="Connexion", choices_from="backends", advanced=False, order=35)] = ""
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
    quota_ceiling: Annotated[float, Knob(label="Réserve d'abonnement", help="Au-delà de cet usage de "
                                         "l'abonnement, ses appels de fond passent au repli (la conversation "
                                         "n'est jamais retenue). 0,8 = 80 % ; 0 : pas de réserve.", lo=0.0,
                                         hi=1.0, step=0.05, group="Options avancées", order=120,
                                         only=(("kind", ("claude_code",)),))] = \
        Field(default=0.8, ge=0.0, le=1.0)

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
               "project": "travailler sur un projet (voix)", "job": "exécuter un projet (impersonnel)"}


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
    context_tokens: Annotated[int, Knob(label="Contexte (jetons)", help="La fenêtre que le prompt peut remplir : "
                                        "persona, fil, souvenirs. Au-delà, le plus ancien du fil est replié et les "
                                        "citations extérieures coupées d'abord.", lo=2_000, hi=1_000_000,
                                        step=1_000, advanced=False, order=30)] = Field(default=24_000, ge=2_000)

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
            if spec.fallback and spec.fallback not in self.backends:
                out.append(f"le fournisseur « {name} » se replie sur un inconnu : {spec.fallback}")
            elif spec.fallback == name:
                out.append(f"le fournisseur « {name} » ne peut pas être son propre repli")
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
                                 config_dir=spec.config_dir, work_dir=work_dir, quota_ceiling=spec.quota_ceiling)
    if spec.kind == "claude":
        from mika.adapters.llm.claude import ClaudeBackend  # noqa: PLC0415

        return ClaudeBackend(spec.api_key, spec.model, cache_ttl=spec.cache_ttl, temperature=spec.temperature,
                             name=name)
    if spec.kind == "openai":
        from mika.adapters.llm.openai_compat import OpenAICompatBackend  # noqa: PLC0415

        return OpenAICompatBackend(spec.api_key, spec.model, base_url=spec.base_url or None,
                                   temperature=spec.temperature, name=name)
    if spec.kind == "ollama":
        from mika.adapters.llm.ollama import OllamaBackend  # noqa: PLC0415

        return OllamaBackend(spec.model, host=spec.host or "http://localhost:11434", think=spec.think,
                             max_reply_tokens=spec.max_reply_tokens or 768, temperature=spec.temperature, name=name)
    from mika.adapters.llm.ollama import OllamaCloudBackend  # noqa: PLC0415

    return OllamaCloudBackend(spec.model, spec.api_key, host=spec.host or "https://ollama.com", think=spec.think,
                              max_reply_tokens=spec.max_reply_tokens or 2048, temperature=spec.temperature,
                              name=name)


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
    slots = {name: spec.slots or (1 if spec.local else 4) for name, spec in cfg.backends.items()}
    preempt = frozenset(name for name, spec in cfg.backends.items() if slots[name] == 1)
    return Gateway(backends, dict(cfg.routes), clock=clock, voice_roles=frozenset(str(r) for r in VOICE_ROLES),
                   fallbacks={str(k): str(v) for k, v in FALLBACKS.items()}, slots=slots, preempt=preempt,
                   on_trace=on_trace, pricing={n: (price_kind(s), s.cache_ttl) for n, s in cfg.backends.items()},
                   backend_fallbacks={n: s.fallback for n, s in cfg.backends.items() if s.fallback})


class LiveGateway:
    """La passerelle en service, remplaçable sans redémarrer (nouvelle clé,
    nouveau modèle). Sans configuration, tout appel échoue proprement."""

    def __init__(self, gateway: Gateway | None = None) -> None:
        self._inner = gateway
        self.traces: deque[LLMTrace] = deque(maxlen=TRACES_KEPT)

    def set(self, gateway: Gateway | None) -> None:
        self._inner = gateway

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
        if self._inner is None:
            raise UnconfiguredRole(req.role)
        return await self._inner.call(req)

    def release(self, call_id: str) -> None:
        """La boucle d'outils ``call_id`` est finie (voir ``Gateway.release``)."""
        if self._inner is not None:
            self._inner.release(call_id)

    async def aclose(self) -> None:
        """Arrête ce que les fournisseurs tiennent encore (les CLI de Claude Code)."""
        for backend in (self._inner.backends.values() if self._inner is not None else ()):
            close = getattr(backend, "aclose", None)
            if close is not None:
                await close()
