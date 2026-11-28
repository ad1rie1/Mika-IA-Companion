"""Une panne de fournisseur d'images, dite en français (jamais un secret)."""

from __future__ import annotations


class ImagingError(Exception):
    """Une panne (connexion, clé refusée, réponse illisible) : son message est montré tel quel."""


def failure_fr(exc: BaseException) -> str:
    """Pourquoi un appel a échoué, en mots."""
    if isinstance(exc, ImagingError):
        return str(exc) or "erreur du fournisseur"
    if isinstance(exc, TimeoutError):
        return "délai dépassé"
    name = type(exc).__name__
    if "Connect" in name:
        return "connexion impossible"
    if "Timeout" in name:
        return "le fournisseur n'a pas répondu à temps"
    return f"erreur {name}"
