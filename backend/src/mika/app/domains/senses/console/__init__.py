"""La part de ses sens dans la console (ADR 0310) : les onglets dessinés de Ses sens (``tabs.py`` — Flux RSS, Caméra,
Dessins, Appareils, et aussi Messages du téléphone et Localisation, rangés dans la même destination), sa rubrique de
réglages (``settings.py`` : ses flux suivis) et leurs gabarits (``templates/``), sous les noms et aux adresses qu'ils
avaient dans l'inspecteur. Les morceaux des pages du téléphone et de la localisation, ils les lisent chez leur
domaine (``app/domains/phone/console/messages.py``, ``app/domains/maps/console/location.py``). Ce qu'ils partagent
avec d'autres domaines reste dans l'inspecteur : la barre de titre
(``handmade/sens/head.html``), les morceaux des pages du téléphone et de la localisation
(``handmade/sens/macros.html``), ceux de leur forme (``handmade/sens/_sens.html``) et leur feuille
(``handmade/sens.css``).
"""

from __future__ import annotations

from pathlib import Path

from mika.app.domains.domain import ConsolePart
from mika.app.domains.senses.console.settings import sections
from mika.app.domains.senses.console.tabs import TABS
from mika.inspector.ui import console_folder

console_folder(Path(__file__).parent)

CONSOLE = ConsolePart(drawn=TABS, sections=sections)
