"""Les réglages d'exploitation, déclarés : ce qu'un opérateur décide, et où.

Chaque section apporte un modèle (le formulaire en sort), sa valeur actuelle
et de quoi l'enregistrer ; la console les rend toutes de la même façon
(``inspector/pages/settings_form.py``). Un enregistrement qui échoue au
rechargement est défait : on ne laisse pas une configuration à moitié prise.

Les réglages d'un plugin vivent là où l'on s'en sert, derrière la roue de sa
destination (``SettingsPage.home``, ADR 0173, 0206) : Courrier, Teams, Réveils
par API › Paramètres, Ses outils › Paramètres des services, et dans Ses sens les
flux suivis, l'accès des appareils, la transcription ; ils s'enregistrent
toujours sous Réglages. « Configuration des plugins » en est la vue d'ensemble.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mika.app.settings_sections import connections, intelligence, map_phone, persona, plugins
from mika.app.settings_sections.common import parameters
from mika.app.settings_sections.plugins import PLUGINS
from mika.inspector.catalog import SettingsSection, SettingsTab

if TYPE_CHECKING:
    from mika.app.server import Live

__all__ = ["PLUGINS", "RUBRICS", "parameters", "sections"]

#: les rubriques de l'annuaire des réglages, dans l'ordre ; chacune porte le nom de ce qu'elle contient (ADR 0197) :
#: « Canaux » ne nomme que les tableaux de droits par canal (ADR 0134), et Dépôts Git, joint par Connexions extérieures,
#: s'y range sous ce nom. Leurs clés ne sont pas des adresses : les anciennes (« canaux », « sens ») restent des
#: adresses d'enregistrement dans ``inspector/pages/routes.py`` (LEGACY_POSTS)
RUBRICS = (SettingsTab("intelligence", "Intelligence"), SettingsTab("personnage", "Personnage"),
           SettingsTab("carte-telephone", "Carte et téléphone"), SettingsTab("plugins", "Plugins"),
           SettingsTab("connexions", "Connexions extérieures"))


def sections(live: Live) -> tuple[SettingsSection, ...]:
    """Toutes les sections, une rubrique après l'autre ; en tête, la vue d'ensemble des plugins, qui lit leurs pages."""
    declared = (*intelligence.sections(live), *persona.sections(live), *map_phone.sections(live),
                *connections.sections(live), *plugins.sections(live))
    return (plugins.overview(live, declared), *declared)
