"""Ce qu'on garde d'une connexion, quel que soit le fournisseur (ADR 0166, 0309, 0318) : le jeton de renouvellement,
et l'application et l'annuaire qui l'ont délivré (``Grant``) ; et où chaque domaine le garde, scellé (``GrantStore``).

Les connexions de Microsoft (``microsoft.py``) et de Google (``google.py``) le lisent toutes deux ; chaque domaine
garde ses jetons dans ses réglages, sous sa clé (``mail_oauth`` pour une boîte, ``agenda_oauth`` pour un compte
d'agenda), et les leur prête sous cette forme. Aucun jeton n'entre dans un journal ni dans un message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Grant:
    """Ce qu'on garde d'une connexion : le jeton de renouvellement, et l'application et l'annuaire qui l'ont délivré."""

    refresh: str
    client_id: str
    tenant: str

    def fits(self, client_id: str, tenant: str) -> bool:
        return self.client_id == client_id and self.tenant == tenant


class GrantStore(Protocol):
    """Où les connexions se gardent, scellées (les réglages). Ses deux méthodes gardent le nom qu'elles avaient quand
    seul le courrier s'en servait : ``app/domains/mail/settings.py::MailSettings`` les porte telles quelles ; un
    autre domaine les prête par une enveloppe (``adapters/agenda/oauth.py::_KindGrants``)."""

    def mail_grant(self, account: str) -> Grant | None: ...

    async def save_mail_grant(self, account: str, grant: Grant) -> None: ...


__all__ = ["Grant", "GrantStore"]
