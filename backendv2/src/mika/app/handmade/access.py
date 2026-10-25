"""Ce que partagent les tableaux de lignes d'accès dessinés (ADR 0131, 0133) — d'un service (``servers.py``), d'un
projet (``projects.py``) — et la page « Droits » (``rights.py``) : les personnes qu'une ligne peut nommer, et ses
sources à cocher."""

from __future__ import annotations

from mika.contracts import identity as identity_c
from mika.faculties.identity.faculty import known_as
from mika.faculties.identity.inspect import people as people_of
from mika.inspector.pages.droits_tables import canal_choices, canal_instances, who_choices
from mika.inspector.ui import UI
from mika.vocab.people import ACCOUNT_PREFIX


def people_with_accounts(ui: UI) -> list[dict[str, str]]:
    """Les personnes qu'une ligne peut nommer : celles qui ont un compte (seules à pouvoir être authentifiées), par
    leur nom — jamais une propriétaire, que sa source à elle (« Toi ») désigne déjà."""
    frame = ui.kernel.mind.frame()
    try:
        s = frame.state("identity")
    except KeyError:
        return []
    out = [{"key": person, "name": known_as(s, person)} for person, handles in people_of(s, frame).items()
           if any(str(h).startswith(ACCOUNT_PREFIX) for h in (*handles, person))
           and not frame.get(identity_c.IS_OWNER(person))]
    return sorted(out, key=lambda p: p["name"].casefold())


__all__ = ["canal_choices", "canal_instances", "people_with_accounts", "who_choices"]
