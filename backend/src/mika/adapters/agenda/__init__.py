"""L'agenda (ADR 0309) : sa base (``store``), le fournisseur Système (``system``), les comptes des réglages
(``config``), et les fournisseurs par sorte (``Providers``, le port ``agenda_providers``).

Les fournisseurs du dehors s'y ajoutent (``Providers.add``, par le serveur) : l'abonnement iCal (``ical``) et CalDAV
(``caldav``), sur un même format iCalendar (``ics``) et une même façon de joindre un serveur (``http``) ; Google
Agenda (``google``) et Microsoft Graph (``graph``), sur une même API JSON (``cloud``) et leurs connexions (``oauth`` :
la portée et les mots de l'agenda, sur les moteurs du cadre, ``adapters/signin/`` — Google par PKCE, Microsoft par
le code d'appareil, ADR 0318). Un compte d'une sorte sans fournisseur ne se synchronise pas.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from mika.adapters.agenda.caldav import SERVICES, CalDavProvider, CalDavService
from mika.adapters.agenda.cloud import SignInNeeded
from mika.adapters.agenda.config import AgendaAccount, AgendaConfig, CalendarSetting
from mika.adapters.agenda.google import GoogleProvider
from mika.adapters.agenda.graph import MicrosoftProvider
from mika.adapters.agenda.http import Web, server_host, server_url
from mika.adapters.agenda.ical import IcalProvider
from mika.adapters.agenda.oauth import AgendaGrants, google_signin, microsoft_signin
from mika.adapters.agenda.store import AgendaStore
from mika.adapters.agenda.system import SystemProvider
from mika.ports.agenda import SYSTEM, CalendarProvider, Connection, system_person
from mika.vocab.access import PERSON


class Providers:
    """Le port ``agenda_providers`` : un fournisseur par sorte, et les comptes que les réglages déclarent (relus à
    chaque usage : ``connections``, posé par le serveur)."""

    def __init__(self, store: AgendaStore, connections: Callable[[], Sequence[Connection]] = tuple) -> None:
        self.store = store
        self._connections = connections
        self.system = SystemProvider(store)
        self._by_kind: dict[str, CalendarProvider] = {SYSTEM: self.system}

    def add(self, provider: CalendarProvider) -> None:
        """Un fournisseur de plus (ou à la place de celui de sa sorte)."""
        self._by_kind[provider.kind] = provider

    def of(self, kind: str) -> CalendarProvider | None:
        return self._by_kind.get(kind)

    def connections(self) -> list[Connection]:
        return list(self._connections())

    def connection(self, key: str) -> Connection | None:
        for c in self.connections():
            if c.key == key:
                return c
        person = system_person(key)
        return Connection(key=key, kind=SYSTEM, owner=PERSON + person) if person else None


__all__ = ["SERVICES", "AgendaAccount", "AgendaConfig", "AgendaGrants", "AgendaStore", "CalDavProvider",
           "CalDavService", "CalendarSetting", "GoogleProvider", "IcalProvider", "MicrosoftProvider", "Providers",
           "SignInNeeded", "SystemProvider", "Web", "google_signin", "microsoft_signin", "server_host", "server_url"]
