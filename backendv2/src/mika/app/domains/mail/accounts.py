"""Les comptes du courrier (ADR 0185, 0207, 0310) : ses boîtes — sa part des comptes d'un canal
(``app/me/accounts.py``).

Une boîte est le canal « courrier:<clé> » : sa règle dit comment part ce qu'elle y prépare, que sa propriétaire règle
depuis son espace (``app/me/settings.py::rules_save``). La matrice de l'écran Outils montre les siennes, avec leur
adresse (``app/me/rights.py``) ; l'onglet Comptes de la fiche d'une personne, sous « Courrier », la liste que le plugin
en dresse (l'onglet ``boites``, qui porte les autres canaux).
"""

from __future__ import annotations

from typing import Any

from mika.app.domains.domain import AccountsPart
from mika.app.domains.mail import api as mail_me
from mika.ports.mail import AccountInfo
from mika.vocab.access import MAIL


def shown(info: AccountInfo) -> dict[str, Any]:
    """Ce que la matrice dit d'une boîte : son nom, son adresse."""
    return {"title": info.name, "address": info.address}


def configured(settings: Any) -> dict[str, Any]:
    """Ses boîtes telles que les réglages les tiennent, par clé."""
    return settings.named("mail").email().accounts


ACCOUNTS = AccountsPart(MAIL, kind="mail", family="email", held=mail_me.boxes, owned=mail_me.owned, shown=shown,
                        configured=configured, tab="boites", label="Courrier", noun="boîte",
                        badges=("état", "elle y écrit"))
