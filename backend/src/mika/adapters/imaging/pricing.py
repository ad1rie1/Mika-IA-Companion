"""Ce que coûte une image, en dollars.

``gpt-image-*`` se paie au jeton — texte et images en entrée, image en sortie —,
et l'API rend le décompte ; ``dall-e-*`` se paie à l'image, selon la qualité et
la taille. Un identifiant correspond à une clé du tableau s'il est la clé, ou la
clé suivie d'une date (``gpt-image-1-2025-04-23``) : jamais par simple préfixe,
un modèle plus récent (``gpt-image-1.5``) n'hérite pas d'un tarif qui n'est pas
le sien. Un serveur à soi est gratuit ; un modèle inconnu chez un fournisseur
payant est compté 0 $ et dit une fois au journal.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from mika.ports.imaging import ImageResult

log = logging.getLogger("mika.imaging.pricing")

#: dollars par million de jetons : (texte en entrée, image en entrée, image en sortie)
TOKEN_PRICES_PER_MILLION: Mapping[str, tuple[float, float, float]] = {
    "gpt-image-1": (5.0, 10.0, 40.0),
    "gpt-image-1-mini": (2.0, 2.5, 8.0),
}
#: dollars par image : (qualité, taille) → prix ; « * » : toute autre taille
PER_IMAGE: Mapping[str, Mapping[tuple[str, str], float]] = {
    "dall-e-3": {("standard", "1024x1024"): 0.04, ("standard", "*"): 0.08,
                 ("hd", "1024x1024"): 0.08, ("hd", "*"): 0.12},
    "dall-e-2": {("standard", "1024x1024"): 0.02, ("standard", "512x512"): 0.018,
                 ("standard", "256x256"): 0.016, ("standard", "*"): 0.02},
}
#: les types de fournisseur qu'on ne paie pas à l'image (un serveur à soi, un faux pour les essais)
FREE_KINDS = frozenset({"openai_compatible", "sdcpp", "fake"})

_unpriced_warned: set[str] = set()


def _key(table: Mapping[str, object], model: str) -> str | None:
    if model in table:
        return model
    dated = [k for k in table if model.startswith(f"{k}-20")]
    return max(dated, key=len) if dated else None


def price_usd(result: ImageResult, *, kind: str) -> float:
    """Le coût d'un résultat ``ok`` chez un fournisseur de type ``kind`` (un refus ou une panne : 0)."""
    if not result.ok or kind in FREE_KINDS:
        return 0.0
    model = result.model.strip().lower()
    key = _key(TOKEN_PRICES_PER_MILLION, model)
    if key is not None:
        text, image, out = TOKEN_PRICES_PER_MILLION[key]
        u = result.usage
        return (u.text_tokens * text + u.image_tokens * image + u.output_tokens * out) / 1_000_000
    key = _key(PER_IMAGE, model)
    if key is not None:
        table = PER_IMAGE[key]
        quality = result.quality or "standard"
        each = table.get((quality, result.size), table.get((quality, "*"), table.get(("standard", "*"), 0.0)))
        return each * len(result.images)
    if model not in _unpriced_warned:
        _unpriced_warned.add(model)
        log.warning("aucun tarif connu pour le modèle d'images %r (%s) : compté 0 $", result.model, kind)
    return 0.0
