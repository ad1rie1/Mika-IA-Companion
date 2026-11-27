"""Où en est une connexion à un compte Microsoft ou Google (ADR 0166, 0309, 0318) : faite, en attente, à faire.

Se connecter n'est à aucun domaine : le courrier (une boîte Microsoft) et l'agenda (un compte Google ou Microsoft) le
disent dans ces mots, que leurs ports, leurs écrans et l'API par personne rendent tels quels. Le moteur de connexion
est au cadre (``adapters/signin/``) ; ce port ne lit aucun autre port.
"""

from __future__ import annotations

from dataclasses import dataclass

#: les états d'une connexion : faite, un code (ou une adresse de consentement) qui attend d'être entré chez le
#: fournisseur, à faire (jamais faite, ou qui ne vaut plus)
SIGNED_IN, SIGNIN_PENDING, SIGNIN_NEEDED = "connectee", "en_attente", "a_faire"


@dataclass(frozen=True, slots=True)
class SignIn:
    """Où en est la connexion d'un compte qui entre par Microsoft ou par Google (OAuth2 : une boîte, ADR 0166 ; un
    compte d'agenda, ADR 0309)."""

    #: ``SIGNED_IN``, ``SIGNIN_PENDING`` ou ``SIGNIN_NEEDED``
    state: str
    #: en attente : le code à entrer, la page du fournisseur où l'entrer (ou l'adresse de consentement), jusqu'à quand
    #: (µs)
    code: str = ""
    url: str = ""
    until: int = 0
    #: pourquoi il n'est pas (ou plus) connecté, en français (vide : rien à dire)
    error: str = ""


__all__ = ["SIGNED_IN", "SIGNIN_NEEDED", "SIGNIN_PENDING", "SignIn"]
