"""Le câblage de l'annuaire (ADR 0298, 0308, 0310) : sa base, qui est le port ``contacts`` du noyau — tous ceux
qu'elle connaît, même sans leur avoir parlé, tirés de Teams et du courrier par le plugin ``contacts`` (hors du
journal). Le direct écoute sa base."""

from __future__ import annotations

from mika.adapters.contacts import ContactsStore
from mika.app.wiring import Wiring

NAME = "contacts"


def wire(w: Wiring) -> None:
    """Avant le noyau : sa base, le port ``contacts``."""
    store = w.ports[NAME] = ContactsStore(w.bases["contacts"], now=w.clock.now)
    # le direct (ADR 0308) : sa base prévient de ses écritures validées
    w.watched.append(store)
