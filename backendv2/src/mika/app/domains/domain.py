"""La fiche d'un domaine (ADR 0310) : ce que la couche ``app`` sait de lui, dit en un seul endroit.

Un domaine est un sujet que plusieurs couches servent chacune à sa place — le courrier a son plugin, son adaptateur,
son contrat, son port — et que ``app`` relie : ses réglages, son câblage, son module de ``/api/moi``, sa part du
direct, ses pages de console, sa commande. Sa fiche est un ``Domain`` écrit à la main, dans le ``__init__.py`` de son
dossier (``app/domains/<nom>/``). Le cadre d'``app`` lit les fiches (``mika.app.domains.DOMAINS``) ; il ne nomme
aucun domaine.

Une fiche *inscrit* ce que le domaine apporte ; elle ne dessine ni ne génère rien : chaque page garde son gabarit,
chaque route son module. Tout champ est facultatif : un domaine ne dit que ce qu'il a.

**Une fiche n'importe rien.** Elle nomme les modules de ses parts (``api="mika.app.domains.contacts.api"``) ; le
cadre les importe au moment d'assembler (``part``), et y lit un nom convenu :

- ``api`` : ``routes(api)``, ses routes de ``/api/moi`` ; et, s'il compte quelque chose pour la barre du haut,
  ``COUNTERS`` (son nom → ``count(call)``) ;
- ``live`` : ``LIVE``, une ``LivePart`` ;
- ``console`` : ``CONSOLE``, une ``ConsolePart`` ;
- ``wiring`` : ``wire(w)``, ce que le serveur construit pour lui avant le noyau (ses adaptateurs, ses portes), et,
  facultatif, ``bind(w)``, ce qui a besoin du noyau (``app/wiring.py::Wiring``) ;
- ``preview`` : ``preview(live, now, people)``, ce qu'il ajoute à la vie fictive de ``mika console apercu`` une fois
  les gens de la démonstration en place (``people`` : le moyen de communication de chacun, par son nom de compte) —
  elle rend les adresses de ses pages à exporter.

Le registre (``mika.app.domains``) est donc une feuille de l'arbre des imports : n'importe quel module d'``app`` peut
le lire, aucun import ne peut tourner en rond par lui. ``tests/architecture/test_frame_names_no_domain.py`` le
garde, et vérifie que chaque part nommée existe et porte son nom convenu.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Base:
    """La base d'un domaine, tenue à côté du journal. Le schéma, les migrations et la sauvegarde la trouvent ici :
    aucun d'eux ne la nomme."""

    #: son nom, celui que son paquet déclare (``ports.sql.database``) : c'est aussi son fichier (``<nom>.db``), sa
    #: base sur le serveur, son dossier de migrations (``app/migrations/<nom>/``) et sa clé dans une archive — le
    #: changer, c'est perdre la base à la restauration
    name: str
    #: le module qui déclare ses entités : l'importer remplit sa ``MetaData``
    models: str
    #: ce qu'elle garde, en mots (Système › Stockage et sauvegardes) : un texte affiché, sans numéro de décision
    place: str


@dataclass(frozen=True, slots=True)
class LivePart:
    """Sa part du direct (ADR 0308) : comment ce qui lui arrive devient des touches (``app/me/touches.py``), et ce
    que chaque personne en voit. Le service (``app/me/changes.py``) réunit les parts ; il n'en connaît aucune."""

    #: propriétaire d'événements → sa traduction : ``translate(événement, frame, kernel)`` rend des touches
    events: Mapping[str, Callable[..., list[Any]]] = field(default_factory=dict)
    #: propriétaire → les sujets que change le réglage de ses paramètres (``kernel.params_changed``), à toutes
    params: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: clé d'un réglage tenu hors du journal (``Settings._put``) → les sujets qu'il change, à toutes
    saved: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: sujet d'une base tenue à côté (``ports.changes.Change.topic``) → sa traduction : ``translate(change)``
    changes: Mapping[str, Callable[..., list[Any]]] = field(default_factory=dict)
    #: règle d'une touche (``Touch.rule``) → ce que la personne en voit : ``seen(call)`` rend les propriétaires
    #: (des comptes, des sources) dont ce qui change la regarde
    seen: Mapping[str, Callable[..., frozenset[str]]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConsolePart:
    """Sa part de la console : ce qu'il y *inscrit*. Chaque page garde son gabarit et sa feuille, écrits à la main
    (ADR 0121, 0177) ; rien ici n'en dessine une."""

    #: sorte d'objet (``Inspection.subject``) → sa fiche dessinée (une ``inspector.ui.Overview``)
    overviews: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Domain:
    #: son nom : celui de son dossier, et sa clé partout où le cadre range par domaine
    name: str
    #: les domaines dont il lit quelque chose (l'agenda lit l'application Microsoft du courrier) : une dépendance
    #: dite ici, jamais cachée — son dossier ne nomme un autre domaine que s'il est dans cette liste, et un besoin
    #: qui ne sert plus se retire (``tests/architecture/test_frame_names_no_domain.py``)
    needs: tuple[str, ...] = ()
    #: sa base à côté du journal, s'il en tient une
    base: Base | None = None
    #: le module de son câblage (``wire``, ``bind``)
    wiring: str | None = None
    #: le module de son API par personne (``routes``, ``COUNTERS``)
    api: str | None = None
    #: le module de sa part du direct (``LIVE``)
    live: str | None = None
    #: le module de sa part de la console (``CONSOLE``)
    console: str | None = None
    #: le module de ce qu'il ajoute à l'aperçu de la console (``preview``)
    preview: str | None = None
    #: ses noms en français dans la console, par sorte de libellé (``inspector.catalog.Labels`` : ``faculties``,
    #: ``sections``, ``processes``, ``events``…) puis par clé ; la carte de la console les réunit
    #: (``app/console.py``), et un nom dit deux fois y est refusé
    labels: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


def part(module: str | None, name: str, default: Any = None) -> Any:
    """Une part d'un domaine, lue dans son module au moment d'assembler : le nom convenu ``name`` du module que sa
    fiche nomme. Sans module, ou sans ce nom quand il est facultatif (``default`` donné) : ``default``."""
    if module is None:
        return default
    found = importlib.import_module(module)
    return getattr(found, name) if default is None else getattr(found, name, default)
