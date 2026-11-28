"""Une connexion gardée longtemps (``adapters.database.Kept``) se referme même coupée par le serveur.

Le 2026-10-14, sur le portable : après une nuit sans un mot, MariaDB avait coupé la connexion de lecture du magasin
(``wait_timeout``, 8 h) ; à l'arrêt, son ``rollback`` levait « MySQL server has gone away » et interrompait tout
l'arrêt. Une connexion coupée n'a plus rien à annuler.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

from mika.adapters.database import Kept


class Gone:
    """Une connexion que le serveur a coupée : la refermer lève, comme PyMySQL sur un tuyau rompu."""

    closed = False

    def close(self) -> None:
        self.closed = True
        raise OperationalError("ROLLBACK", None, BrokenPipeError(32, "Broken pipe"))


class Alive:
    closed = False

    def close(self) -> None:
        self.closed = True


def test_a_connection_cut_by_the_server_closes_without_failing_the_shutdown():
    gone = Gone()
    Kept(gone).close()  # ne lève pas
    assert gone.closed
    alive = Alive()
    Kept(alive).close()
    assert alive.closed


def test_anything_else_than_a_database_error_still_raises():
    class Broken:
        def close(self) -> None:
            raise RuntimeError("un vrai défaut")

    with pytest.raises(RuntimeError):
        Kept(Broken()).close()
