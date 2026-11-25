"""Le câblage d'un domaine (ADR 0310) : ce que le serveur construit pour lui, sans le nommer.

``server.build()`` tient un ``Wiring`` et le passe au module de câblage de chaque fiche (``Domain.wiring``), qui y lit
ce dont il a besoin (le dossier de données, les réglages, l'horloge, ses bases) et y pose ce qu'il apporte :

- ``wire(w)``, avant le noyau : ses adaptateurs et ses portes, rangés dans ``w.ports`` (les ports du noyau, par leur
  nom), ``w.web`` (ce que l'application web reçoit par nom — ses portes HTTP : ``adapters/web/app.py::create_app``) et
  ``w.parts`` (ses objets vivants, par le nom du domaine : ``Live.parts``) ;
- ``bind(w)``, facultatif, une fois le noyau construit : ce qui a besoin de son port d'entrée (``w.port``).

Un domaine lit ce qu'un autre a posé par son nom (``w.ports["mail"]``), dans l'ordre des fiches ; il le déclare
(``Domain.needs``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Wiring:
    #: le dossier de données
    data: Path
    #: les réglages du serveur (un domaine y prend les siens : ``settings.of(SesRéglages)``)
    settings: Any
    #: l'horloge du serveur
    clock: Any
    #: où vit chaque base (``schema.targets``), par son nom
    bases: Mapping[str, Any]
    #: les ports du noyau, par leur nom : ce que le domaine y pose
    ports: dict[str, Any]
    #: ce que l'application web reçoit, par nom (ses portes HTTP)
    web: dict[str, Any] = field(default_factory=dict)
    #: les objets vivants de chaque domaine, par son nom
    parts: dict[str, Any] = field(default_factory=dict)
    #: le port d'entrée du noyau, une fois le noyau construit (pour ``bind``)
    port: Any = None
