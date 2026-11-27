"""Se connecter à Google Agenda et à Microsoft Graph (ADR 0309, lot 2 ; 0318) : le jeton de renouvellement d'un
compte d'agenda, scellé dans les réglages à part des comptes (``AgendaGrants`` : ``app/domains/agenda/settings.py``,
la clé ``agenda_oauth``), et le jeton d'accès, en mémoire, renouvelé avant sa fin.

Se connecter n'est pas à l'agenda : les deux moteurs sont au cadre (``adapters/signin/``, ADR 0318), et le courrier
prend le même code d'appareil. Restent ici ce qui est à l'agenda : ses portées, sa route de retour, ses mots (ceux qui
nomment la fiche du compte), ses connexions rangées par compte et par sorte (``AgendaGrants``, prêtées aux moteurs par
``_KindGrants``), et les deux fabriques qui leur donnent tout cela.

- **Microsoft** (``microsoft_signin``) : le code d'appareil du cadre (``adapters/signin/microsoft.py``,
  ``MicrosoftSignIn``, ADR 0166), une instance à part : la portée de Graph (``Calendars.ReadWrite`` et
  ``offline_access`` : un jeton à part de celui d'une boîte IMAP), les connexions des comptes d'agenda, ses mots.
  L'application est celle de l'instance, que le courrier partage (ADR 0238 : un réglage du cadre,
  ``app/connections.py``), ou celle que le compte déclare (``oauth_client_id``), dans son annuaire (``oauth_tenant``).
- **Google** (``google_signin``) : OAuth 2 avec PKCE (``adapters/signin/google.py``, ``GoogleSignIn``) — Google refuse
  le code d'appareil pour l'agenda —, par l'application Google du serveur (``GoogleApplication``, réglée par un
  opérateur) : la portée de l'agenda (``GOOGLE_SCOPE``, vérifiée à la fin : Google laisse décocher chaque case du
  consentement), son retour pour un client « Application Web » (``RETURN_PATH``, la route de son API par personne),
  ses mots, et ses erreurs (``AgendaError`` ; à reconnecter : ``SignInNeeded``), que ses routes et ses fournisseurs
  attrapent.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import httpx

from mika.adapters.agenda.cloud import USER_AGENT, SignInNeeded
from mika.adapters.signin.google import GoogleApplication, GoogleSignIn
from mika.adapters.signin.grants import Grant
from mika.adapters.signin.microsoft import MicrosoftSignIn
from mika.ports.agenda import GOOGLE, MICROSOFT, AgendaError

# ── Microsoft ───────────────────────────────────────────────────────────────

#: les agendas par Microsoft Graph, et un jeton de renouvellement
MICROSOFT_SCOPES = "offline_access https://graph.microsoft.com/Calendars.ReadWrite"
MICROSOFT_NOT_SIGNED_IN = "pas encore connecté à Microsoft : « Se connecter à Microsoft » sur la fiche du compte"
MICROSOFT_NO_APPLICATION = ("aucune application Microsoft déclarée : celle de l'instance, que le courrier partage, se "
                            "règle dans Courrier › Paramètres › Compte Microsoft (ou mika mail application) ; un "
                            "compte peut déclarer la sienne")


class AgendaGrants(Protocol):
    """Où les connexions des comptes d'agenda se gardent, scellées (les réglages), par compte et par sorte."""

    def agenda_grant(self, account: str, kind: str) -> Grant | None: ...

    async def save_agenda_grant(self, account: str, grant: Grant, kind: str) -> None: ...


class _KindGrants:
    """Les connexions d'une sorte de compte d'agenda, sous la forme que lisent les connexions du cadre
    (``adapters/signin/grants.py::GrantStore``)."""

    def __init__(self, grants: AgendaGrants, kind: str) -> None:
        self._grants = grants
        self._kind = kind

    def mail_grant(self, account: str) -> Grant | None:
        return self._grants.agenda_grant(account, self._kind)

    async def save_mail_grant(self, account: str, grant: Grant) -> None:
        await self._grants.save_agenda_grant(account, grant, self._kind)


def microsoft_signin(grants: AgendaGrants | None, application: Callable[[], str] = lambda: "", *,
                     transport: httpx.AsyncBaseTransport | None = None, **more: Any) -> MicrosoftSignIn:
    """Les connexions Microsoft des comptes d'agenda : le code d'appareil du cadre, à la portée de Graph
    (``start(compte, connexion)``, ``state``, ``token``, ``drop``) ; ``application`` : celle de l'instance."""
    return MicrosoftSignIn(_KindGrants(grants, MICROSOFT) if grants is not None else None, transport=transport,
                           application=application, scopes=MICROSOFT_SCOPES, not_signed_in=MICROSOFT_NOT_SIGNED_IN,
                           no_application=MICROSOFT_NO_APPLICATION, label="agenda", **more)


# ── Google ──────────────────────────────────────────────────────────────────

#: lire et écrire ses agendas (leur liste, leurs événements, en créer)
GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar"
#: où un client « Application Web » revient, sous l'origine HTTPS du serveur (la route est celle du lot 4)
RETURN_PATH = "/api/moi/agenda/google/retour"

GOOGLE_NOT_SIGNED_IN = "pas encore connecté à Google : « Se connecter à Google » sur la fiche du compte"
GOOGLE_NO_CALENDAR = ("Google n'a pas donné l'accès à l'agenda (sa case n'était pas cochée) : recommence et coche-la")


def google_signin(grants: AgendaGrants | None, application: Callable[[], GoogleApplication | None], *,
                  transport: httpx.AsyncBaseTransport | None = None, **more: Any) -> GoogleSignIn:
    """Les connexions Google des comptes d'agenda : le parcours du cadre (PKCE), à la portée de l'agenda, revenant à
    sa route, dans ses mots et ses erreurs (``start``, ``finish``, ``state``, ``token``, ``drop``, ``revoke``) ;
    ``application`` : celle du serveur."""
    return GoogleSignIn(_KindGrants(grants, GOOGLE) if grants is not None else None, application,
                        scope=GOOGLE_SCOPE, return_path=RETURN_PATH, not_signed_in=GOOGLE_NOT_SIGNED_IN,
                        no_scope=GOOGLE_NO_CALENDAR, refused=AgendaError, needed=SignInNeeded,
                        user_agent=USER_AGENT, transport=transport, **more)


__all__ = ["GOOGLE_NOT_SIGNED_IN", "GOOGLE_SCOPE", "MICROSOFT_NOT_SIGNED_IN", "MICROSOFT_NO_APPLICATION",
           "MICROSOFT_SCOPES", "RETURN_PATH", "AgendaGrants", "google_signin", "microsoft_signin"]
