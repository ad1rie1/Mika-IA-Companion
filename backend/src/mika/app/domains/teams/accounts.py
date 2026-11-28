"""Les comptes de Teams (ADR 0186, 0207, 0310) : ses comptes — sa part des comptes d'un canal
(``app/me/accounts.py``).

Un compte est le canal « teams:<clé> » : sa règle dit comment part ce qu'elle y prépare, que sa propriétaire règle
depuis son espace (``app/me/settings.py::rules_save``) — des brouillons compris, posés dans Teams —, sous le geste qui
règle son compte (``audit``). La matrice de l'écran Outils montre les siens
(``app/me/rights.py``) ; l'onglet Comptes de la fiche d'une personne, sous « Teams », la liste que le plugin en dresse
— sans boîte, l'onglet ``teams`` reste à lui.
"""

from __future__ import annotations

from typing import Any

from mika.app.domains.domain import AccountsPart
from mika.app.domains.teams import api as teams_me
from mika.ports.teams import AccountInfo
from mika.vocab.access import TEAMS


def shown(info: AccountInfo) -> dict[str, Any]:
    """Ce que la matrice dit d'un compte Teams : son nom."""
    return {"title": info.name}


def configured(settings: Any) -> dict[str, Any]:
    """Ses comptes tels que les réglages les tiennent, par clé."""
    return settings.named("teams").teams().accounts


ACCOUNTS = AccountsPart(TEAMS, kind="teams", family="teams", held=teams_me.accounts, owned=teams_me.owned,
                        shown=shown, configured=configured, audit="moi.compte_teams", subject_kind="compte_teams",
                        yours="ton compte", tab="teams", label="Teams", noun="compte", badges=("état",))
