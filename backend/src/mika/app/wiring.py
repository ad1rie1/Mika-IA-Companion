"""Le câblage d'un domaine (ADR 0310) : ce que le serveur construit pour lui, sans le nommer.

``server.build()`` tient un ``Wiring`` et le passe au module de câblage de chaque fiche (``Domain.wiring``), qui y lit
ce dont il a besoin (le dossier de données, les réglages, l'horloge, ses bases, son nom à elle, si le serveur sert
pour de bon) et y pose ce qu'il apporte :

- ``wire(w)``, avant le noyau : ses adaptateurs et ses portes, rangés dans ``w.ports`` (les ports du noyau, par leur
  nom), ``w.web`` (ce que l'application web reçoit par nom — ses portes HTTP : ``adapters/web/app.py::create_app``),
  ``w.me`` (ce que l'API par personne reçoit par nom : ``app/me/api.py::MeApiBase``), ``w.parts`` (ses objets
  vivants, par le nom du domaine : ``Live.parts``) et ``w.watched`` (ses bases tenues à côté du journal, que le
  direct écoute) ;
- ``bind(w)``, facultatif, une fois le noyau construit : ce qui a besoin de son port d'entrée (``w.port`` ; le
  noyau : ``w.port.kernel``), du serveur vivant (``w.live`` : ses comptes, son registre des appels, de quoi se
  reconfigurer) ou des
  notifications des téléphones (``w.push``). Ce qu'il signale de lui-même au direct passe par
  ``w.live.changes.add(touches)``, lu à l'appel (le direct naît après lui). Il peut encore poser des routes (``w.routes`` : des montages de
  l'application web, à côté de ceux du serveur) et ce que la console reçoit par nom (``w.inspector`` :
  ``inspector.ui.InspectorDeps``) : l'application et la console s'assemblent après lui ;
- ``inputs(settings)``, facultatif : ce que ses réglages d'exploitation donnent aux paramètres de ses plugins —
  propriétaire → valeurs —, relu à chaque (re)configuration (``server.Live.inputs``) ;
- ``start(w)``, ``stop(w)``, ``release(w)``, facultatifs et asynchrones, dans le cycle de vie du serveur : ``start``
  une fois sa vie relue, ses réglages ouverts et le direct en marche, juste avant qu'elle vive (une relève, une
  connexion tenue, des serveurs à joindre) ; ``stop`` dès l'arrêt, avant le direct ; ``release`` une fois ses
  épisodes annulés (ce qu'on ferme en dernier : des connexions, des fichiers). Les arrêts vont dans l'ordre
  inverse des fiches.

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
    #: le magasin de son journal (``adapters.store_sql.SqlStore``) : ses contenus, pour qui doit en relire
    store: Any = None
    #: ce que l'application web reçoit, par nom (ses portes HTTP)
    web: dict[str, Any] = field(default_factory=dict)
    #: les objets vivants de chaque domaine, par son nom
    parts: dict[str, Any] = field(default_factory=dict)
    #: ce que l'API par personne reçoit, par nom
    me: dict[str, Any] = field(default_factory=dict)
    #: ses bases tenues à côté du journal qui préviennent de leurs écritures (``on_change``) : le direct les écoute
    watched: list[Any] = field(default_factory=list)
    #: des routes de plus pour l'application web (des montages), posées par ``bind``
    routes: list[Any] = field(default_factory=list)
    #: ce que la console reçoit, par nom (``InspectorDeps``), posé par ``bind``
    inspector: dict[str, Any] = field(default_factory=dict)
    #: son nom, celui de la persona en vigueur (journalisée), lu à l'appel : ce que signent ses mails et ses
    #: enregistrements d'atelier — un adaptateur ne lit pas sa persona lui-même (ADR 0070)
    her: Any = None
    #: le serveur sert pour de bon (``serve``) : un domaine peut alors joindre le dehors de lui-même (le courrier en
    #: direct, ADR 0308). Un test ou l'aperçu qui monte le serveur ne joint ainsi rien sans le dire
    serving: bool = False
    #: une fois le noyau construit (pour ``bind``) : son port d'entrée, le serveur vivant (``server.Live``), les
    #: notifications des téléphones (``adapters.web.push.MobilePush``)
    port: Any = None
    live: Any = None
    push: Any = None
