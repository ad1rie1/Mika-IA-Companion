"""Configurer les images : fournisseurs déclarés, rôles routés, passerelle
rechargeable à chaud — comme les modèles de langage (``adapters/llm/config.py``).

**Désactivée tant que rien n'est branché** : sans fournisseur, la génération
d'images n'existe pas (``LiveImaging.configured`` est faux, toute demande rend
``unconfigured``). Le premier fournisseur déclaré sert « dessiner » d'office,
et les autres rôles y retombent : déclarer un fournisseur suffit à l'activer.
Les clés ne passent en clair qu'à la construction du client.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mika.adapters.imaging.gateway import TRACES_KEPT, ImageGateway, ImageTrace, UnconfiguredImageRole
from mika.adapters.imaging.openai_images import OpenAIImagesBackend, is_loopback
from mika.adapters.imaging.sdcpp import DEFAULT_STEPS, SdCppBackend
from mika.kernel import forms
from mika.kernel.clock import Clock
from mika.kernel.forms import Knob
from mika.ports.imaging import DRAW, ROLE_LABELS, ROLES, UNCONFIGURED, ImageBackend, ImageRequest, ImageResult

Kind = Literal["openai", "openai_compatible", "sdcpp"]

_KINDS = (("openai", "OpenAI (API Images)"), ("sdcpp", "stable-diffusion.cpp (ton serveur local)"),
          ("openai_compatible", "Compatible OpenAI (un autre serveur d'images)"))
#: les types qui désignent un serveur par son adresse
_SERVERS = ("openai_compatible", "sdcpp")
_MODERATIONS = (("auto", "standard"), ("low", "moins stricte"))


class ImageBackendSpec(BaseModel):
    """Un fournisseur d'images déclaré (les libellés servent au formulaire de la console)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Annotated[Kind, Knob(label="Type", help="OpenAI (son API Images) ; ton serveur local stable-diffusion.cpp "
                                                  "(services/mika-images) ; ou tout serveur qui parle la langue "
                                                  "d'OpenAI (/v1/images/generations).",
                               group="Le fournisseur", choices=_KINDS, advanced=False, order=10)]
    model: Annotated[str, Knob(label="Modèle", help="Choisi dans la liste que propose le fournisseur (elle se "
                                                    "charge une fois la clé ou l'adresse renseignée).",
                               group="Le fournisseur", loader="image_models", advanced=False, order=20)]
    api_key: Annotated[str, Knob(label="Clé d'API", help="Chiffrée au repos, jamais réaffichée. Vide : inchangée "
                                                         "(un serveur à toi n'en demande souvent pas).",
                                 group="Connexion", secret=True, advanced=False, order=30)] = ""
    base_url: Annotated[str, Knob(label="Adresse du serveur", help="http://127.0.0.1:8190 pour le serveur local "
                                                                   "(/v1 au bout pour un serveur compatible OpenAI).",
                                  group="Connexion", advanced=False, order=32, only=(("kind", _SERVERS),))] = ""
    fallback: Annotated[str, Knob(label="Repli", help="Le fournisseur qui prend le relais quand celui-ci tombe en "
                                                      "panne ou ne sait pas faire ce qu'on demande (partir d'une "
                                                      "image…). Un refus de modération n'y repart pas.",
                                  group="Connexion", choices_from="backends", advanced=False, order=35)] = ""
    adult: Annotated[bool, Knob(label="Accepte le contenu pour adultes", help="Seulement pour un serveur à toi : "
                                                                             "un service hébergé le refuse.",
                                group="Le fournisseur", advanced=False, order=25, only=(("kind", _SERVERS),))] = False
    moderation: Annotated[Literal["auto", "low"], Knob(
        label="Modération", help="La sévérité de la modération d'OpenAI (gpt-image).", choices=_MODERATIONS,
        group="Options avancées", order=40, only=(("kind", ("openai",)),))] = "auto"
    steps_draft: Annotated[int, Knob(label="Pas (brouillon)", help="Plus de pas : plus fin, plus long (≈ 6 s le pas "
                                                                   "en 768² sur une RTX 3060).", lo=1, hi=100,
                                     group="Génération", order=45, only=(("kind", ("sdcpp",)),))] = \
        Field(default=DEFAULT_STEPS["draft"], ge=1, le=100)
    steps_normal: Annotated[int, Knob(label="Pas (normale)", help="≈ 11 s le pas en 1024² sur une RTX 3060.", lo=1,
                                      hi=100, group="Génération", order=46, only=(("kind", ("sdcpp",)),))] = \
        Field(default=DEFAULT_STEPS["normal"], ge=1, le=100)
    steps_high: Annotated[int, Knob(label="Pas (haute)", help="La qualité haute est aussi plus grande (1280²).", lo=1,
                                    hi=100, group="Génération", order=47, only=(("kind", ("sdcpp",)),))] = \
        Field(default=DEFAULT_STEPS["high"], ge=1, le=100)
    slots: Annotated[int, Knob(label="Créneaux", help="Images en même temps (0 : 1 sur un serveur local, 2 "
                                                      "ailleurs).", lo=0, hi=8, group="Options avancées",
                               order=50)] = Field(default=0, ge=0, le=8)

    @property
    def local(self) -> bool:
        return self.kind in _SERVERS and is_loopback(self.base_url)

    def redacted(self) -> dict[str, Any]:
        """Ce qui se montre de lui : la clé masquée, et seulement les champs qui servent à son type."""
        data = self.model_dump()
        data["api_key"] = "••••" if self.api_key else ""
        shown = {f.path for f in forms.describe(ImageBackendSpec) if forms.visible(f, data)}
        return {k: v for k, v in data.items() if k in shown}


class ImagingConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backends: Annotated[dict[str, ImageBackendSpec], Knob(
        label="Fournisseurs d'images", help="Les services déclarés ; les rôles désignent l'un d'eux par son nom. "
                                            "Aucun : elle ne génère pas d'images.", advanced=False, order=10)] = \
        Field(default_factory=dict)
    #: rôle → nom de fournisseur déclaré
    routes: Annotated[dict[str, str], Knob(
        label="Rôles", help="Quel fournisseur sert chaque rôle ; un rôle sans fournisseur retombe sur « dessiner ».",
        keys=tuple((r, ROLE_LABELS[r]) for r in ROLES), choices_from="backends", advanced=False, order=20)] = \
        Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _draw_served(cls, data: Any) -> Any:
        """Le premier fournisseur déclaré sert « dessiner » d'office ; un choix explicite vers un fournisseur
        déclaré n'est jamais changé."""
        if not isinstance(data, Mapping):
            return data
        backends = data.get("backends") or {}
        routes = data.get("routes") or {}
        if not isinstance(backends, Mapping) or not isinstance(routes, Mapping) or not backends:
            return data
        if routes.get(DRAW) in backends:
            return data
        return {**data, "routes": {**dict(routes), DRAW: str(next(iter(backends)))}}

    @property
    def enabled(self) -> bool:
        return self.routes.get(DRAW, "") in self.backends

    def problems(self) -> list[str]:
        out = []
        for role, name in self.routes.items():
            if role not in ROLES:
                out.append(f"le rôle d'images « {role} » n'existe pas (les rôles : {', '.join(ROLES)})")
            elif name not in self.backends:
                out.append(f"le rôle d'images « {role} » vise un fournisseur inconnu : {name}")
        for name, spec in self.backends.items():
            if spec.fallback and spec.fallback not in self.backends:
                out.append(f"le fournisseur d'images « {name} » se replie sur un inconnu : {spec.fallback}")
            elif spec.fallback == name:
                out.append(f"le fournisseur d'images « {name} » ne peut pas être son propre repli")
            if spec.kind == "openai" and not spec.api_key:
                out.append(f"le fournisseur d'images « {name} » (OpenAI) n'a pas de clé")
            if spec.kind in _SERVERS and not spec.base_url.startswith(("http://", "https://")):
                out.append(f"le fournisseur d'images « {name} » n'a pas d'adresse de serveur (http://…/v1)")
            if not spec.model.strip():
                out.append(f"le fournisseur d'images « {name} » n'a pas de modèle")
        return out


def build_backend(name: str, spec: ImageBackendSpec) -> ImageBackend:
    if spec.kind == "sdcpp":
        return SdCppBackend(spec.base_url, name=name, model=spec.model, adult=spec.adult,
                            steps={"draft": spec.steps_draft, "normal": spec.steps_normal, "high": spec.steps_high})
    return OpenAIImagesBackend(spec.api_key, spec.model, base_url=spec.base_url or None,
                               compatible=spec.kind == "openai_compatible", moderation=spec.moderation,
                               adult=spec.adult, name=name)


def build_gateway(cfg: ImagingConfig, clock: Clock, *, on_trace: Callable[[ImageTrace], None] | None = None,
                  make: Callable[[str, ImageBackendSpec], ImageBackend] | None = None) -> ImageGateway:
    make = make or build_backend
    backends = {name: make(name, spec) for name, spec in sorted(cfg.backends.items())}
    slots = {name: spec.slots or (1 if backends[name].caps.local else 2) for name, spec in cfg.backends.items()}
    return ImageGateway(backends, dict(cfg.routes), clock=clock, slots=slots,
                        preempt=frozenset(name for name, n in slots.items() if n == 1),
                        backend_fallbacks={n: s.fallback for n, s in cfg.backends.items() if s.fallback},
                        kinds={n: s.kind for n, s in cfg.backends.items()}, on_trace=on_trace)


class LiveImaging:
    """La génération d'images en service, remplaçable sans redémarrer. Sans
    configuration, elle n'existe pas : ``configured`` est faux et toute demande
    rend ``unconfigured``."""

    def __init__(self, gateway: ImageGateway | None = None) -> None:
        self._inner = gateway
        self.traces: deque[ImageTrace] = deque(maxlen=TRACES_KEPT)

    def set(self, gateway: ImageGateway | None) -> None:
        self._inner = gateway

    @property
    def configured(self) -> bool:
        return bool(self.serving(DRAW))

    def serving(self, role: str) -> str:
        """Le fournisseur qui sert ce rôle (« retoucher » et « ses dessins » retombent sur « dessiner ») ; « » :
        aucun."""
        if self._inner is None:
            return ""
        try:
            return self._inner.resolve(role)
        except UnconfiguredImageRole:
            return ""

    def can(self, role: str, *, refs: int = 0, adult: bool = False) -> bool:
        return self._inner is not None and self._inner.can(role, refs=refs, adult=adult)

    def routes(self) -> Mapping[str, str]:
        return dict(self._inner.routes) if self._inner is not None else {}

    def resolution(self) -> dict[str, str]:
        return self._inner.resolution(ROLES) if self._inner is not None else dict.fromkeys(ROLES, "")

    def status(self) -> list[dict[str, Any]]:
        return self._inner.status() if self._inner is not None else []

    async def generate(self, req: ImageRequest) -> ImageResult:
        if self._inner is None:
            return ImageResult(UNCONFIGURED, reason="aucun fournisseur d'images n'est branché")
        return await self._inner.generate(req)

    async def aclose(self) -> None:
        for backend in (self._inner.backends.values() if self._inner is not None else ()):
            close = getattr(backend, "aclose", None)
            if close is not None:
                await close()
