"""Ce que la composition donne aux tableaux de droits (ADR 0131, 0133, 0134) — ceux de l'inspecteur (Réglages › Canaux,
Outils › Ce qu'elle peut faire, par ``InspectorDeps``), d'un service (``app/domains/tools/console/subject.py``),
d'un projet (``domains/projects/console/subject.py``) — et à la page « Droits » (``rights.py``) : les personnes qu'une ligne peut
nommer, les instances de chaque canal, la fiche d'une famille d'outils venue d'ailleurs, les choix de leurs
sélecteurs (ceux du cadre commun, ``vocab.access``). Une seule liste, une seule règle pour tous. Les comptes d'un canal
sont ceux que sa part dit (``app/me/accounts.py``) : ce module n'en nomme aucun."""

from __future__ import annotations

from mika.app.me import accounts as channels
from mika.app.me import outside
from mika.contracts import identity as identity_c
from mika.faculties.identity.faculty import known_as
from mika.faculties.identity.faculty import people as people_of
from mika.inspector.pages.rights_tables import Instances, canal_choices, canal_instances, who_choices
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI
from mika.vocab.access import KEEPS, POLICIES, PRIVATE, TOGETHER, WEB, canal_key
from mika.vocab.people import ACCOUNT_PREFIX


def capitalized(options: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    """Des choix (clé, libellé), le libellé avec une majuscule en tête, pour un sélecteur."""
    return tuple((k, label[:1].upper() + label[1:]) for k, label in options)


#: ce qu'une ligne fait d'un outil, dans un sélecteur d'un tableau dessiné (un service, un projet) : les mots des
#: familles (``vocab.access.POLICIES``, ADR 0134), jamais une recopie
POLICY_CHOICES = capitalized(POLICIES)
#: ce qu'elle garde de ce qu'un outil rend, dans un sélecteur (``vocab.access.KEEPS``)
KEEP_CHOICES = capitalized(KEEPS)


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
    """Les instances de chaque type de canal : le chat web (en privé, en salon), chaque compte d'un canal qui en a —
    chaque boîte de courrier, chaque compte Teams (ADR 0186 : son tableau, comme une boîte), tels que leurs réglages
    les tiennent (``AccountsPart.configured``, dans l'ordre des canaux) —, et celles qu'un tableau réglé nomme déjà."""
    out: Instances = {WEB: [(f"{WEB}:{PRIVATE}", "en privé"), (f"{WEB}:{TOGETHER}", "en salon")]}
    settings = ui.deps.settings
    for canal, found in channels.parts().items():
        try:
            held = found.configured(settings) if settings is not None else {}
        except (AttributeError, TypeError, ValueError):  # des comptes illisibles : aucune instance, le type reste
            held = {}
        out[canal] = [(f"{canal}:{key}", a.label or key) for key, a in sorted(held.items())]
    for key in sorted(settings.canals().tables) if settings is not None else ():
        kind, instance = canal_key(key)
        if instance and key not in {k for k, _ in out.get(kind, ())}:
            out.setdefault(kind, []).append((key, instance))
    return out


def family_href(bundle: str) -> str:
    """L'adresse de la fiche où se règlent les droits d'une famille d'outils venue d'ailleurs (un service, une app) :
    celle que dit la part de sa sorte (``OutsidePart.fiche``), par le début de son lot ; vide pour toute autre."""
    kind, _, name = bundle.partition(".")
    fiche = next((p.fiche for p in outside.parts().values() if p.bundle == f"{kind}."), None)
    return subject_url(fiche[0], name, fiche[1]) if fiche is not None else ""


__all__ = ["canal_choices", "canal_instances", "family_href", "instances_from_settings", "people_with_accounts",
           "who_choices"]
