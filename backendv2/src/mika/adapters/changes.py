"""Ce qu'une base tenue à côté du journal dit de ses écritures (ADR 0308) : ce qu'une méthode note pendant une écriture
(``note``) part à ses écouteurs une fois la transaction validée (la sortie de ``writing`` sans erreur) — jamais avant,
et rien d'une écriture annulée. Une note faite hors d'une écriture part aussitôt.

Une base sérialise ses écritures sous son verrou : une seule est en cours à la fois, dans un seul fil d'exécution
(``writing`` se tient sous ce verrou). Une note d'un autre fil, faite hors de toute écriture, ne se mêle pas à celle
en cours. Un écouteur est appelé dans le fil qui a écrit (la relève IMAP tourne dans le sien) : à lui d'en revenir
sur sa boucle. Un écouteur qui lève ne défait pas une écriture validée : c'est dit au journal, et les suivants sont
prévenus quand même.

Un travail fait de nombreuses écritures (un passage de l'historique, le rangement d'un dossier) peut les **retenir**
(``held``) : ce que valident ses écritures, dans ce fil, part une fois à la fin du bloc, chaque changement une seule
fois — même si le bloc lève, car ce qui a été validé a eu lieu.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from mika.ports.changes import Change

log = logging.getLogger("mika.changes")

Listener = Callable[[Change], None]


class Changes:
    """Les écouteurs d'une base, et ce qu'elle a noté pendant l'écriture en cours."""

    def __init__(self) -> None:
        self._listeners: list[Listener] = []
        self._pending: list[Change] = []
        self._depth = 0
        #: le fil de l'écriture en cours (0 : aucune)
        self._thread = 0
        #: par fil qui les retient (``held``), ce que ses écritures validées ont dit
        self._held: dict[int, list[Change]] = {}

    def listen(self, fn: Listener) -> None:
        self._listeners.append(fn)

    @contextmanager
    def writing(self) -> Iterator[None]:
        """Une écriture : ce qui s'y note part à sa validation, à la sortie de la plus extérieure, si rien n'a levé."""
        if self._depth == 0:
            self._thread = threading.get_ident()
        self._depth += 1
        done = False
        try:
            yield
            done = True
        finally:
            self._depth -= 1
            if self._depth == 0:
                said, self._pending, self._thread = self._pending, [], 0
                if done:
                    for change in said:
                        self._tell(change)

    @contextmanager
    def held(self) -> Iterator[None]:
        """Ce que les écritures de ce fil valident pendant le bloc part une fois, à sa fin (même s'il lève : ce qui a
        été validé a eu lieu) ; un bloc dans un autre ne retient rien de plus."""
        me = threading.get_ident()
        if me in self._held:
            yield
            return
        self._held[me] = []
        try:
            yield
        finally:
            said = self._held.pop(me)
            for change in said:
                self._tell(change)

    def note(self, change: Change) -> None:
        """Ce que l'écriture en cours change ; hors d'une écriture de ce fil, dit aussitôt."""
        if self._depth and self._thread == threading.get_ident():
            if change not in self._pending:
                self._pending.append(change)
            return
        self._tell(change)

    def _tell(self, change: Change) -> None:
        kept = self._held.get(threading.get_ident())
        if kept is not None:
            if change not in kept:
                kept.append(change)
            return
        for fn in tuple(self._listeners):
            try:
                fn(change)
            except Exception:  # un écouteur en panne ne défait pas une écriture validée, ni ne prive les autres
                log.exception("un écouteur des changements a échoué (%s)", change.topic)
