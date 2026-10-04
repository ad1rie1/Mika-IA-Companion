"""Le port des images : demander une image à un fournisseur, quel qu'il soit.

Comme pour les modèles de langage (``ports/llm.py``), un fournisseur ne fait que
traduire une demande générique vers son API et revenir ; le routage par rôle, les
replis, les créneaux et les traces vivent dans la passerelle
(``adapters/imaging``). Une demande dit ce qu'elle veut — une proportion, une
qualité —, jamais des pixels : chaque fournisseur la traduit vers ce qu'il sait
faire (trois tailles chez OpenAI, tout multiple de 64 sur un serveur à soi).

Un fournisseur déclare ce qu'il sait faire (``ImageCaps``) ; la passerelle ne lui
envoie jamais une demande qu'il ne peut pas servir (partir d'images de
référence, un contenu qu'il n'accepte pas). Ce qu'il ne sait pas faire mais qui
n'empêche rien (une graine, un prompt négatif, un fond transparent) est ignoré.

Un **refus** (la modération d'un service hébergé) est une réponse, pas une
panne. La passerelle ne lève pas : chaque demande rend un ``ImageResult`` dont
l'issue dit ce qui s'est passé (``ok``, ``refused``, ``failed``, ``timeout``,
``unsupported``, ``unconfigured``) et, sinon ``ok``, pourquoi, en français.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

#: les rôles : un dessin demandé, une retouche d'images reçues, ses dessins à elle (en fond)
DRAW, EDIT, OWN = "draw", "edit", "own"
ROLES = (DRAW, EDIT, OWN)
ROLE_LABELS: Mapping[str, str] = {DRAW: "dessiner (une demande)", EDIT: "retoucher une image",
                                  OWN: "ses dessins à elle (en fond)"}
#: un rôle sans fournisseur retombe sur celui-ci
ROLE_FALLBACKS: Mapping[str, str] = {EDIT: DRAW, OWN: DRAW}

#: les proportions qu'on peut demander (largeur : hauteur)
ASPECTS: Mapping[str, float] = {"square": 1.0, "portrait": 2 / 3, "landscape": 3 / 2, "wide": 16 / 9}
#: les qualités (chaque fournisseur les traduit : low/medium/high, standard/hd, un nombre de pixels)
QUALITIES = ("draft", "normal", "high")

#: les issues
OK = "ok"
REFUSED = "refused"
FAILED = "failed"
TIMEOUT = "timeout"
UNSUPPORTED = "unsupported"
UNCONFIGURED = "unconfigured"

#: la plus grande image qu'on accepte d'un fournisseur (octets)
MAX_IMAGE_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Picture:
    """Une image : en référence d'une demande, ou rendue par un fournisseur."""

    mime: str
    data: bytes
    width: int = 0
    height: int = 0


@dataclass(frozen=True, slots=True)
class ImageCaps:
    """Ce qu'un fournisseur sait faire."""

    #: partir d'images de référence (retoucher, combiner)
    edit: bool = False
    #: combien d'images de référence au plus
    max_refs: int = 0
    transparent: bool = False
    negative: bool = False
    seed: bool = False
    #: accepte un contenu pour adultes (un service hébergé le refuse : seulement un serveur à soi)
    adult: bool = False
    #: tourne sur la machine (rien ne sort, gratuit)
    local: bool = False


@dataclass(frozen=True, slots=True)
class ImageRequest:
    role: str
    call_id: str
    prompt: str
    aspect: str = "square"
    quality: str = "normal"
    refs: tuple[Picture, ...] = ()
    negative: str = ""
    seed: int | None = None
    transparent: bool = False
    #: un contenu pour adultes : seulement vers un fournisseur qui l'accepte (``ImageCaps.adult``)
    adult: bool = False
    #: un refus d'un service hébergé peut repartir vers un fournisseur local de la chaîne
    refusal_fallback: bool = False
    lane: str = "background"  # "conversation" | "background"
    priority: int = 1
    meta: Mapping[str, Any] = field(default_factory=dict)


def unmet(caps: ImageCaps, req: ImageRequest) -> str:
    """Pourquoi ce fournisseur ne peut pas servir cette demande, en mots ; « » : il le peut."""
    if req.refs and not caps.edit:
        return "ne sait pas partir d'une image"
    if len(req.refs) > caps.max_refs and caps.edit:
        return f"accepte {caps.max_refs} image(s) de référence au plus"
    if req.adult and not caps.adult:
        return "n'accepte pas ce contenu"
    return ""


@dataclass(frozen=True, slots=True)
class ImageUsage:
    """Les jetons qu'un fournisseur a comptés (zéro : il ne compte pas au jeton)."""

    text_tokens: int = 0
    image_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True, slots=True)
class ImageResult:
    outcome: str
    images: tuple[Picture, ...] = ()
    #: sinon ``ok`` : pourquoi, en français (le message d'une modération, « délai dépassé »…)
    reason: str = ""
    backend: str = ""
    model: str = ""
    #: la taille et la qualité réellement demandées au fournisseur (« 1024x1536 », « high »)
    size: str = ""
    quality: str = ""
    #: le prompt tel que le fournisseur l'a réécrit, s'il le dit
    revised_prompt: str = ""
    usage: ImageUsage = ImageUsage()
    cost_usd: float = 0.0

    @property
    def ok(self) -> bool:
        return self.outcome == OK and bool(self.images)


class ImageBackend(Protocol):
    """Un fournisseur : rend ``ok`` (au moins une image) ou ``refused`` ; lève pour une
    panne (la passerelle la compte et passe au repli). Facultatifs : ``status()``,
    ``aclose()``."""

    name: str
    caps: ImageCaps

    async def generate(self, req: ImageRequest) -> ImageResult: ...


class ImagingPort(Protocol):
    """La génération d'images telle que la voient les facultés : désactivée tant
    qu'aucun fournisseur n'est branché (``configured`` faux, ``serving`` vide)."""

    @property
    def configured(self) -> bool: ...

    def serving(self, role: str) -> str: ...

    def can(self, role: str, *, refs: int = 0, adult: bool = False) -> bool: ...

    async def generate(self, req: ImageRequest) -> ImageResult: ...
