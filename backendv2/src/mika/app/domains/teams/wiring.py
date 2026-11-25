"""Le câblage de Teams (ADR 0069, 0186, 0246, 0308, 0310) : son cache, qui est le port ``teams`` du noyau (ce que
l'extension pousse, ses brouillons et la boîte d'envoi, hors du journal) ; sa porte de ``/api/teams/…``, qui est aussi
le port ``teams_keys`` (ses clés, une par compte) ; l'extension à télécharger, que l'API par personne sert. Le direct
écoute son cache ; la porte reçoit, une fois le noyau construit, son port d'entrée et de quoi dire la présence de
l'extension de chaque compte. Ses réglages donnent aux paramètres du plugin ses comptes, leurs propriétaires et leurs
partages (``inputs``)."""

from __future__ import annotations

from typing import Any

from mika.adapters.teams import TeamsStore
from mika.app.domains.teams.desk import TeamsDesk
from mika.app.domains.teams.extension import EXTENSION_DIR
from mika.app.wiring import Wiring

NAME = "teams"
#: ses clés, une par compte (ADR 0186) : la console les crée et les retire par ce port
KEYS = "teams_keys"


def wire(w: Wiring) -> None:
    # Teams (ADR 0069) : ce que l'extension pousse, ses brouillons et la file (hors du journal), et la porte
    store = w.ports[NAME] = TeamsStore(w.settings.teams, w.bases["teams"], now=w.clock.now)
    # ses clés, une par compte (ADR 0186) : la console les crée et les retire par ce port
    desk = w.ports[KEYS] = w.parts[NAME] = w.web[NAME] = TeamsDesk(w.settings, w.clock.now, store)
    # l'extension de Teams (ADR 0246), servie en zip à qui est connecté
    w.me["extension"] = EXTENSION_DIR
    # le direct (ADR 0308) : son cache prévient de ses écritures validées — et la boîte d'envoi réveille l'extension
    w.watched.append(store)
    store.on_change(desk.store_changed)


def bind(w: Wiring) -> None:
    """Une fois le noyau construit : son port d'entrée ; et la présence de l'extension d'un compte (ses comptes, aux
    écrans qui les lisent), dite au direct — lu à l'appel : il naît après."""
    desk = w.parts[NAME]
    desk.port = w.port
    desk.on_presence = lambda account: w.live.changes.presence(account)


def inputs(settings: Any) -> dict[str, dict[str, Any]]:
    """Ce que ses réglages donnent aux paramètres du plugin ``teams`` : actif ou non, les tableaux de ses canaux (ADR
    0134 : ce qu'elle envoie à ta place), ses comptes."""
    canaux = settings.canals().model_dump(mode="json")
    teams = settings.teams()
    # à qui est chaque compte Teams (ADR 0186 ; vide : à toi) : ses outils ne lui montrent que ceux de qui est en face
    return {"teams": {"enabled": teams.enabled, "canaux": canaux,
                      "owners": {k: a.owner for k, a in sorted(teams.accounts.items())},
                      "shares": {k: dict(sorted(a.shares.items())) for k, a in sorted(teams.accounts.items())
                                 if a.shares},
                      "accounts_off": sorted(k for k, a in teams.accounts.items() if not a.enabled)}}
