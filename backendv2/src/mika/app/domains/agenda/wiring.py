"""Le câblage de l'agenda (ADR 0309, 0310) : sa base, qui est le port ``agenda`` du noyau (ses événements hors du
journal) ; ses fournisseurs, le port ``agenda_providers`` (un abonnement iCal, un serveur CalDAV, Google Agenda,
Outlook.com et Microsoft 365) ; ce que la console change d'un compte, le port ``agenda_desk``. Le direct écoute sa
base. Une fois le noyau construit, ce guichet reçoit de quoi rejournaliser les paramètres, et la connexion Google ou
Microsoft d'un compte se dit au direct (``bind``). Ses réglages donnent aux paramètres du plugin ses comptes et leurs
agendas (``inputs``).

Ses comptes, leurs connexions et l'application Google du serveur sont ses réglages (``settings.py``) ; Microsoft
entre par l'application du courrier (``MailSettings.mail_application``, ADR 0238)."""

from __future__ import annotations

from typing import Any

from mika.adapters.agenda import (
    AgendaStore,
    CalDavProvider,
    GoogleProvider,
    GoogleSignIn,
    IcalProvider,
    MicrosoftProvider,
    Providers,
    Web,
    microsoft_signin,
)
from mika.app.domains.agenda.live import signed
from mika.app.domains.agenda.settings import AgendaSettings
from mika.app.domains.agenda.store import AgendaSettingsDesk
from mika.app.domains.mail.settings import MailSettings
from mika.app.wiring import Wiring

#: ses fournisseurs ; ce que la console change d'un compte (``ports/agenda.py::AgendaDesk``)
PROVIDERS, DESK = "agenda_providers", "agenda_desk"


def wire(w: Wiring) -> None:
    """Avant le noyau : sa base, ses fournisseurs et le guichet de la console, dans les ports du noyau."""
    outside, settings, clock, bases = w.ports, w.settings, w.clock, w.bases
    own = settings.of(AgendaSettings)
    # l'agenda (ADR 0309) : ses événements hors du journal (ceux du système y font foi, ceux d'un fournisseur en sont
    # la copie), et ses fournisseurs avec les comptes des réglages, relus à chaque usage
    outside["agenda"] = AgendaStore(bases["agenda"], now=clock.now)
    outside["agenda_providers"] = Providers(outside["agenda"], own.agenda_connections)
    # un abonnement iCal (une adresse .ics, en lecture seule) et un serveur CalDAV (ADR 0309, lot 1) ; une redirection
    # ou une adresse donnée par le serveur qui quitte son hôte ne mène qu'à Internet
    agenda_web = Web()
    outside["agenda_providers"].add(IcalProvider(agenda_web, now=clock.now))
    outside["agenda_providers"].add(CalDavProvider(agenda_web, now=clock.now))
    # Google Agenda et Outlook.com / Microsoft 365 (ADR 0309, lot 2) : leurs connexions scellées à part des comptes ;
    # Google par l'application Google du serveur (réglée par un opérateur), Microsoft par celle du courrier (ADR 0238),
    # chacun joignant ses hôtes seulement. Leurs parcours de connexion : ``.signin`` de chacun (lot 4 : l'API)
    outside["agenda_providers"].add(GoogleProvider(GoogleSignIn(own, own.google_application, now=clock.now),
                                                   now=clock.now))
    outside["agenda_providers"].add(MicrosoftProvider(microsoft_signin(own, settings.of(MailSettings).mail_application),
                                                      now=clock.now))
    # ce que la console change d'un compte d'agenda (ADR 0309, lot 5) : le décocher, ne plus suivre un de ses agendas,
    # oublier sa connexion — jamais une écriture dans un agenda
    outside[DESK] = AgendaSettingsDesk(own, outside["agenda_providers"])
    # le direct (ADR 0308) : sa base prévient de ses écritures validées
    w.watched.append(outside["agenda"])


def bind(w: Wiring) -> None:
    """Une fois le noyau construit : ce que la console change d'un compte rejournalise les paramètres du plugin
    (``Live.reconfigure``) ; la connexion Google ou Microsoft d'un compte (ADR 0309, lot 4 : connecté, refusé, échu)
    se dit au direct — lu à l'appel : il naît après."""
    w.ports[DESK].reconfigure = w.live.reconfigure
    for kind in ("google", "microsoft"):
        agenda_signin = getattr(w.ports[PROVIDERS].of(kind), "signin", None)
        if agenda_signin is not None:
            agenda_signin.on_state = lambda account: signed(w.live.changes, account)


def inputs(settings: Any) -> dict[str, dict[str, Any]]:
    """Ce que ses réglages donnent aux paramètres du plugin ``agenda``."""
    # ses comptes d'agenda et leurs agendas (ADR 0309) : à qui, partagés avec qui, masqués, leur rappel
    return {"agenda": settings.of(AgendaSettings).agenda().params()}
