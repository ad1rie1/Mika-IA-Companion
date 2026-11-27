"""Entrer dans une boîte Microsoft sans mot de passe : XOAUTH2 (ADR 0166, 0318).

Hotmail, Outlook.com et Live refusent le mot de passe en IMAP et en SMTP. On y entre avec un jeton d'accès, que
présente le mécanisme SASL ``XOAUTH2`` (``answer``) ; Microsoft 365 aussi, si son administrateur le permet.

Se connecter n'est pas au courrier : le code d'appareil, le renouvellement, les refus de Microsoft en mots et
l'application qu'on présente sont au cadre (``adapters/signin/microsoft.py::MicrosoftSignIn``, ADR 0318). Restent
ici ce qui est à lui : sa portée (``SCOPES`` : lire et ranger par IMAP, envoyer par SMTP), ses mots (``NOT_SIGNED_IN``,
``NO_APPLICATION`` : ils nomment la fiche de la boîte et ses réglages), la réponse ``XOAUTH2`` d'IMAP et de SMTP, et
les connexions de ses boîtes (``mail_signin``). Leurs jetons sont gardés dans ses réglages, scellés, sous
``mail_oauth`` (``app/domains/mail/settings.py``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from mika.adapters.signin.grants import Grant
from mika.adapters.signin.microsoft import MicrosoftSignIn

#: lire et ranger (IMAP), envoyer (SMTP), et un jeton de renouvellement (``offline_access``)
SCOPES = "offline_access https://outlook.office.com/IMAP.AccessAsUser.All https://outlook.office.com/SMTP.Send"

NOT_SIGNED_IN = "pas encore connectée à Microsoft : « Se connecter à Microsoft » sur la fiche de la boîte"
NO_APPLICATION = ("aucune application Microsoft déclarée (son identifiant, le client ID, se donne pour toute "
                  "l'instance dans Courrier › Paramètres › Compte Microsoft, ou dans les réglages de la boîte)")


def xoauth2(user: str, token: str) -> str:
    """La réponse SASL ``XOAUTH2``, avant son base64."""
    return f"user={user}\x01auth=Bearer {token}\x01\x01"


def answer(user: str, token: str) -> Callable[..., str]:
    """De quoi répondre au serveur (``imaplib.authenticate``, ``smtplib.auth``) : la réponse ``XOAUTH2`` la première
    fois ; si le serveur renvoie un défi (son erreur, en JSON), une réponse vide, qui clôt l'échange par un refus."""
    said = False

    def respond(challenge: bytes | None = None) -> str:
        nonlocal said
        if said:
            return ""
        said = True
        return xoauth2(user, token)

    return respond


class MailGrants(Protocol):
    """Où les connexions des boîtes se gardent, scellées (les réglages du courrier), par boîte."""

    def mail_grant(self, account: str) -> Grant | None: ...

    async def save_mail_grant(self, account: str, grant: Grant) -> None: ...


class _BoxGrants:
    """Les connexions des boîtes, sous la forme que lisent les connexions du cadre
    (``adapters/signin/grants.py::GrantStore``)."""

    def __init__(self, grants: MailGrants) -> None:
        self._grants = grants

    def grant(self, account: str) -> Grant | None:
        return self._grants.mail_grant(account)

    async def save_grant(self, account: str, grant: Grant) -> None:
        await self._grants.save_mail_grant(account, grant)


def mail_signin(grants: MailGrants | None = None, application: Callable[[], str] = lambda: "",
                **more: Any) -> MicrosoftSignIn:
    """Les connexions Microsoft des boîtes : le code d'appareil du cadre, à la portée d'IMAP et de SMTP, dans les mots
    du courrier (``start(boîte, compte)``, ``state``, ``token``, ``drop``) ; ``application`` : celle de l'instance."""
    return MicrosoftSignIn(_BoxGrants(grants) if grants is not None else None, application=application, scopes=SCOPES,
                           not_signed_in=NOT_SIGNED_IN, no_application=NO_APPLICATION, label="courrier", **more)
