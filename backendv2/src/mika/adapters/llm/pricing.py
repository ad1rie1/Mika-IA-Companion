"""Prix d'un appel en dollars, d'après une table par famille de modèles.

Tarifs par million de jetons (entrée, sortie). Un identifiant absent retombe
sur la famille du plus long préfixe (``claude-opus-4-7`` → ``claude-opus-4`` →
``claude-opus``). Aucune famille → 0 $ et un avertissement par modèle : un 0 $
muet se confond avec un modèle local. Tout fournisseur ``ollama*`` coûte 0 $
(local : l'électricité ; hébergé : un abonnement, pas l'usage).

Cache (familles Claude) : lecture à 0,1× l'entrée, sauf tarif publié à part ;
écriture à 1,25× (TTL 5 min) ou 2× (TTL 1 h). Ailleurs, faute de tarif de cache
dans la table, les jetons de cache se paient au tarif d'entrée (jamais sous-estimé).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from mika.ports.llm import Usage

log = logging.getLogger("mika.llm.pricing")

#: (entrée, sortie) en $ par million de jetons. Claude : tarifs publiés par Anthropic (vérifiés le
#: 2026-10-01, y compris les identifiants datés et les modèles 3.x retirés : un registre peut encore en
#: porter) ; OpenAI : grille publique standard (même date). Les autres serveurs compatibles (GLM, DeepSeek…)
#: changent de grille trop souvent pour une table figée : non chiffrés, et dits (un avertissement par modèle).
PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    # Fable / Mythos — même palier
    "claude-fable": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-fable-5-1": (10.0, 50.0),
    "claude-mythos": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-mythos-5-1": (10.0, 50.0),
    # Opus — 5 $/25 $ depuis 4.5 ; 4.0/4.1 gardent l'ancien tarif (identifiant daté compris) ; 5.5 moins cher
    "claude-opus": (5.0, 25.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-4": (5.0, 25.0),
    "claude-opus-4-0": (15.0, 75.0),
    "claude-opus-4-20250514": (15.0, 75.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    # Sonnet — 5.x à 2 $/10 $, la génération 4.x à 3 $/15 $
    "claude-sonnet": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    # Haiku
    "claude-haiku": (1.0, 5.0),
    "claude-haiku-4": (1.0, 5.0),
    "claude-haiku-4-5": (1.0, 5.0),
    # génération 3 (retirée ou dépréciée)
    "claude-3-opus": (15.0, 75.0),
    "claude-3-7-sonnet": (3.0, 15.0),
    "claude-3-5-sonnet": (3.0, 15.0),
    "claude-3-5-haiku": (0.8, 4.0),
    "claude-3-haiku": (0.25, 1.25),
    # OpenAI
    "gpt-5": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-5-nano": (0.05, 0.4),
    "gpt-5.1": (1.25, 10.0),
    "gpt-5.2": (1.75, 14.0),
    # les variantes « pro » ne sont pas leur famille au rabais : sans leur ligne, le plus long préfixe
    # (gpt-5, o3, o1) les compterait dix fois moins cher
    "gpt-5-pro": (15.0, 120.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "gpt-4.1-nano": (0.1, 0.4),
    "o1": (15.0, 60.0),
    "o1-mini": (3.0, 12.0),
    "o1-pro": (150.0, 600.0),
    "o3": (2.0, 8.0),
    "o3-mini": (1.1, 4.4),
    "o3-pro": (20.0, 80.0),
    "o4-mini": (1.1, 4.4),
}

#: Lectures de cache publiées à part ($ par million) : Fable 5.1 / Mythos 5.1 à 0,025×, Opus 5.5 à 0,05×.
CACHE_READ_PER_MILLION: dict[str, float] = {
    "claude-fable-5-1": 0.25,
    "claude-mythos-5-1": 0.25,
    "claude-opus-5-5": 0.20,
}
CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = {"5m": 1.25, "1h": 2.0}
_CACHE_PRICED_FAMILY = "claude-"

_unpriced_warned: set[str] = set()


def _family(table: Mapping[str, object], model: str) -> str | None:
    """Clé exacte, sinon le plus long préfixe ; None quand rien ne correspond."""
    if model in table:
        return model
    matches = [k for k in table if model.startswith(k)]
    return max(matches, key=len) if matches else None


#: payés autrement qu'au jeton (Claude Code sur l'abonnement de l'utilisateur)
FREE_PROVIDERS = frozenset({"claude_code"})


def price_usd(model: str, usage: Usage, *, provider: str = "", cache_ttl: str = "5m") -> float:
    """Coût en dollars d'un appel ; ``provider`` est le nom du fournisseur (``ollama*`` et Claude Code
    sur l'abonnement : gratuits au jeton)."""
    if cache_ttl not in CACHE_WRITE_MULTIPLIER:
        raise ValueError(f"cache_ttl inconnu : {cache_ttl!r}")
    if provider.strip().lower().startswith("ollama") or provider.strip().lower() in FREE_PROVIDERS:
        return 0.0
    norm = model.strip().lower()
    key = _family(PRICING_PER_MILLION, norm)
    if key is None:
        if norm not in _unpriced_warned:
            _unpriced_warned.add(norm)
            log.warning("aucun tarif connu pour %r (fournisseur %r) : compté 0 $", model, provider or "?")
        return 0.0
    in_rate, out_rate = PRICING_PER_MILLION[key]
    if norm.startswith(_CACHE_PRICED_FAMILY):
        override = _family(CACHE_READ_PER_MILLION, norm)
        read_rate = CACHE_READ_PER_MILLION[override] if override else in_rate * CACHE_READ_MULTIPLIER
        write_rate = in_rate * CACHE_WRITE_MULTIPLIER[cache_ttl]
    else:
        read_rate = write_rate = in_rate
    return (
        usage.input_tokens * in_rate
        + usage.output_tokens * out_rate
        + usage.cache_read * read_rate
        + usage.cache_write * write_rate
    ) / 1_000_000
