"""Ce que la composition donne aux tableaux de droits (ADR 0131, 0133, 0134) — ceux de l'inspecteur (Réglages › Canaux,
Outils › Ce qu'elle peut faire, par ``InspectorDeps``), d'un service (``servers.py``), d'un projet (``projects.py``) — et
à la page « Droits » (``rights.py``) : les personnes qu'une ligne peut nommer, les instances de chaque canal, la fiche
d'une famille d'outils venue d'ailleurs. Une seule liste, une seule règle pour tous."""

from __future__ import annotations

from mika.contracts import identity as identity_c
from mika.faculties.identity.faculty import known_as
from mika.faculties.identity.inspect import people as people_of
from mika.inspector.pages.droits_tables import Instances, canal_choices, canal_instances, who_choices
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import UI
from mika.vocab.access import MAIL, PRIVATE, TEAMS, TOGETHER, WEB, canal_key
from mika.vocab.people import ACCOUNT_PREFIX

#: la fiche qui règle une famille d'outils venue d'ailleurs, par le début de son lot : sa sorte, son onglet des droits
FAMILY_FICHES = {"mcp": ("serveur", "fait"), "forge_apps": ("app", "acces")}


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


def instances_from_settings(ui: UI) -> Instances:
    """Les instances de chaque type de canal : le chat web (en privé, en salon), chaque boîte de courrier, chaque compte
    Teams (ADR 0186 : son tableau, comme une boîte), et celles qu'un tableau réglé nomme déjà."""
    out: Instances = {WEB: [(f"{WEB}:{PRIVATE}", "en privé"), (f"{WEB}:{TOGETHER}", "en salon")]}
    settings = ui.deps.settings
    try:
        boxes = settings.email().accounts if settings is not None else {}
    except (AttributeError, TypeError, ValueError):  # des boîtes illisibles : aucune instance, le type reste
        boxes = {}
    out[MAIL] = [(f"{MAIL}:{key}", a.label or key) for key, a in sorted(boxes.items())]
    teams = settings.teams().accounts if settings is not None else {}
    out[TEAMS] = [(f"{TEAMS}:{key}", a.label or key) for key, a in sorted(teams.items())]
    for key in sorted(settings.canals().tables) if settings is not None else ():
        kind, instance = canal_key(key)
        if instance and key not in {k for k, _ in out.get(kind, ())}:
            out.setdefault(kind, []).append((key, instance))
    return out


def family_href(bundle: str) -> str:
    """L'adresse de la fiche où se règlent les droits d'une famille d'outils venue d'ailleurs (un service, une app) ;
    vide pour toute autre."""
    kind, _, name = bundle.partition(".")
    fiche = FAMILY_FICHES.get(kind)
    return fiche_url(fiche[0], name, fiche[1]) if fiche is not None else ""


__all__ = ["canal_choices", "canal_instances", "family_href", "instances_from_settings", "people_with_accounts",
           "who_choices"]
