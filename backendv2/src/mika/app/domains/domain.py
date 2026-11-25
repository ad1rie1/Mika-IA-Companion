"""La fiche d'un domaine (ADR 0310) : ce que la couche ``app`` sait de lui, dit en un seul endroit.

Un domaine est un sujet que plusieurs couches servent chacune à sa place — le courrier a son plugin, son adaptateur,
son contrat, son port — et que ``app`` relie : ses réglages, son câblage, son module de ``/api/moi``, sa part du
direct, ses pages de console, sa commande. Sa fiche est un ``Domain`` écrit à la main, dans le ``__init__.py`` de son
dossier (``app/domains/<nom>/``). Le cadre d'``app`` lit les fiches (``mika.app.domains.DOMAINS``) ; il ne nomme
aucun domaine.

Une fiche *inscrit* ce que le domaine apporte ; elle ne dessine ni ne génère rien : chaque page garde son gabarit,
chaque route son module. Tout champ est facultatif : un domaine ne dit que ce qu'il a.

**Une fiche n'importe rien d'``app``.** Elle ne prend aux couches du dessous que de quoi se dire (une
``Destination``, un ``MenuLink`` : ``inspector.catalog``). Elle nomme les modules de ses parts (``api="mika.app.domains.contacts.api"``) ; le
cadre les importe au moment d'assembler (``part``), et y lit un nom convenu :

- ``settings`` : ``SETTINGS``, la classe de ses réglages (une ``app/settings.py::SettingsPart``). Le domaine la prend
  lui-même par ``settings.of(SaClasse)`` ; une page du cadre qui croise plusieurs domaines, par son nom
  (``settings.named("teams")``) ;
- ``api`` : ``routes(api)``, ses routes de ``/api/moi`` ; et, s'il compte quelque chose pour la barre du haut,
  ``COUNTERS`` (son nom → ``count(call)``) ;
- ``live`` : ``LIVE``, une ``LivePart`` ;
- ``sharing`` : ``SHARING``, une ``SharingPart`` : ce qui se partage chez lui (``app/me/sharing.py`` réunit les
  parts) ;
- ``accounts`` : ``ACCOUNTS``, une ``AccountsPart`` : les comptes de son canal (``app/me/accounts.py`` réunit les
  parts) ;
- ``outside`` : ``OUTSIDE``, une ``OutsidePart`` : une sorte de ressource dont les outils viennent d'ailleurs
  (``app/me/outside.py`` réunit les parts) ;
- ``console`` : ``CONSOLE``, une ``ConsolePart`` ;
- ``port`` : ``PORT``, une ``PortPart`` : ses méthodes du port d'entrée, que ``app/mindport.py::KernelPort`` mêle aux
  siennes ;
- ``wiring`` : ``wire(w)``, ce que le serveur construit pour lui avant le noyau (ses adaptateurs, ses portes), et,
  facultatif, ``bind(w)``, ce qui a besoin du noyau (``app/wiring.py::Wiring``) ;
- ``cli`` : ``add(sub)``, sa commande et ses sous-commandes dans l'analyseur de ``mika`` ;
- ``backup`` : ce qu'une sauvegarde ne prend pas de ses dossiers — ``UNSAVED``, des chemins du dossier de données
  (un dossier, ou un sous-dossier : ils se rebâtissent ou se retéléchargent), et ``SAVED``, les fichiers gardés quand
  même sous un dossier qu'elle ne prend pas (``app/backup.py``) ;
- ``preview`` : ``preview(live, now, people)``, ce qu'il ajoute à la vie fictive de ``mika console apercu`` une fois
  les gens de la démonstration en place (``people`` : le moyen de communication de chacun, par son nom de compte) —
  elle rend les adresses de ses pages à exporter.

Le registre (``mika.app.domains``) est donc une feuille de l'arbre des imports : n'importe quel module d'``app`` peut
le lire, aucun import ne peut tourner en rond par lui. ``tests/architecture/test_frame_names_no_domain.py`` le
garde, et vérifie que chaque part nommée existe et porte son nom convenu.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
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
    #: règle d'une touche → les niveaux de la personne sur ce qu'elle y a : ``levels(call)`` rend chaque propriétaire
    #: (une boîte, un compte) et son niveau (le sien, ce qu'on lui partage : lire, préparer, s'en servir). Le service
    #: y applique ce que la touche demande (``Touch.need``)
    levels: Mapping[str, Callable[..., Mapping[str, str]]] = field(default_factory=dict)
    #: règle d'une touche → son propre jugement, quand ni ``seen`` ni ``levels`` ne la disent (un agenda est à elle
    #: par son compte ou par un partage encore ouvert) : ``judge(reader, touch)`` rend (la regarde-t-elle ?, les
    #: clés qu'elle peut en voir nommées). ``reader.call`` est ce qu'une route de son espace lirait,
    #: ``reader.channel`` le canal de ses clients ; ``reader.once(nom, lire, vide)`` ne lit qu'une fois par personne
    #: et par envoi
    judge: Mapping[str, Callable[..., tuple[bool, tuple[str, ...]]]] = field(default_factory=dict)
    #: port du noyau → ses comptes tels que ses réglages les disent : ``listed(port)``, lu une fois par envoi sur la
    #: boucle d'événements (leur lecture passe par la base du journal, que seule la boucle lit) ; les règles les
    #: relisent ensuite dans un fil, par ce même nom de port
    listed: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    #: règle d'une touche → le propriétaire d'une clé qu'elle nomme : ``owner_of(topic, key)`` (le compte d'une
    #: conversation, la boîte d'une référence) ; sans cela, une clé est son propre propriétaire
    owner_of: Mapping[str, Callable[..., str]] = field(default_factory=dict)
    #: un effet du moteur proposé, décidé ou parti (un brouillon, une réponse offerte, une écriture) est-il le sien ?
    #: ``effects(proposal, frame, kernel, event)`` rend ses touches, ou ``None`` : ce n'est pas à lui. Il le
    #: reconnaît par sa proposition (ce que sa tranche en garde) ou par l'événement même (son contexte). Une
    #: proposition n'est qu'à un domaine ; le service les interroge dans l'ordre des fiches
    effects: Callable[..., list[Any] | None] | None = None
    #: propriétaire d'une tâche (``vocab.episodes.task_of``) → où elle en est d'une réponse (ADR 0306) :
    #: ``work(ref, frame, kernel)`` rend les touches de cette tâche, au départ et à la fin de son épisode
    tasks: Mapping[str, Callable[..., list[Any]]] = field(default_factory=dict)
    #: ce que le départ ou la fin d'un épisode change chez lui quand ce n'est la tâche de personne (une exécution
    #: d'un projet) : ``episodes(kind, target, frame, kernel)`` rend ses touches — aucune, le plus souvent
    episodes: Callable[..., list[Any]] | None = None


@dataclass(frozen=True, slots=True)
class SharingPart:
    """Ce qui se partage chez lui (ADR 0188) : une sorte de ressource — une boîte, un compte Teams, un service, un
    agenda —, que son propriétaire partage avec une personne qui a un compte. Les partages (``app/me/sharing.py``)
    réunissent les parts, dans l'ordre de leurs sortes (``KINDS``) ; ils n'en connaissent aucune."""

    #: la sorte, telle que l'API la dit (« mail », « teams », « mcp », « agenda ») ; sa place :
    #: ``app/me/sharing.py::KINDS``
    kind: str
    #: sa sorte en mots, telle que la console la nomme (« boîte », « compte Teams », « service », « agenda »)
    word: str
    #: tous ses partages rangés, ressource par ressource : ``every(settings, names)`` rend des
    #: ``app/me/sharing.py::Shared`` (``names`` : ce que ``names`` a lu, ou ``None``)
    every: Callable[..., list[Any]]
    #: son propriétaire partage, change ou retire (``POST /api/moi/shares/set``) : ``share(call, settings, key,
    #: person, level)``, asynchrone — ce que sa sorte vérifie (la ressource est à qui demande, ce niveau lui va), puis
    #: l'écriture ; il lève ``Denied``. Ce qui vaut pour toutes les sortes (qui reçoit, le niveau, des réglages
    #: branchés) est jugé avant, par le cadre, qui lui passe les réglages (``settings``)
    share: Callable[..., Awaitable[None]]
    #: ranger ou retirer un partage sans juger qui demande (l'opérateur qui le retire dans Réglages › Droits ›
    #: Partages) : ``write(settings, reconfigure, key, person, level, check)``, asynchrone (``check`` juge sa fiche
    #: relue, sous le verrou des réglages) ; ``None`` : il ne se range pas ainsi (un service se règle sur ses lignes
    #: d'accès), et la console ne le retire pas
    write: Callable[..., Awaitable[None]] | None = None
    #: qui partage, par son nom, dit à qui reçoit : ``sharer(frame, shared, name)`` (qui décide d'une boîte, qui écrit
    #: d'un compte Teams) ; ``None`` : le nom de son propriétaire
    sharer: Callable[..., str] | None = None
    #: une de ses clés fait au plus tant de caractères
    key_limit: int = 40
    #: le nom de ses ressources quand ses réglages ne le tiennent pas (un agenda : sa base le dit) : ``names(port)``
    #: (``port`` : un port du noyau, par son nom — ``Call.port``) rend le nom de chacune par sa clé, lu avant ``every``
    names: Callable[..., Mapping[str, str]] | None = None


@dataclass(frozen=True, slots=True)
class AccountsPart:
    """Les comptes de son canal (ADR 0185, 0186, 0207) : ses boîtes, ses comptes Teams — ceux d'une personne, à qui
    est chacun, et comment la console les montre. La règle d'envoi d'un compte (``app/me/settings.py``), la matrice de
    l'écran Outils (``app/me/rights.py``) et l'onglet Comptes de la fiche d'une personne (``app/handmade/person/``)
    réunissent les parts, dans l'ordre de leurs canaux (``app/me/accounts.py::CHANNELS``) ; ils n'en connaissent
    aucune."""

    #: son canal, tel que le moteur le dit (``vocab.access`` : « courrier », « teams ») : un de ses comptes est le canal
    #: « <canal>:<clé> », dont la règle dit comment part ce qu'elle y prépare ; sa place :
    #: ``app/me/accounts.py::CHANNELS``
    canal: str
    #: sa sorte de ressource, telle que l'API la dit (« mail », « teams »)
    kind: str
    #: la famille de ses outils (« email », « teams ») : la matrice mène de chacun de ses comptes à elle
    family: str
    #: les comptes de qui est connecté : ``held(call)`` rend, par clé, le compte et son niveau — les siens, puis ceux
    #: qu'on lui partage
    held: Callable[..., Mapping[str, tuple[Any, str]]]
    #: un compte à elle (le régler, décider de ce qui en part : un partage n'y suffit pas) : ``owned(call, key)`` le
    #: rend, ou lève ``Denied``
    owned: Callable[..., Any]
    #: ce que la matrice dit d'un de ses comptes, après sa clé et sa sorte : ``shown(info)`` (son nom ; une boîte, aussi
    #: son adresse)
    shown: Callable[..., Mapping[str, Any]]
    #: ses comptes tels que ses réglages les tiennent, par clé (chacun dit à qui il est : ``owner``) :
    #: ``configured(settings)``
    configured: Callable[..., Mapping[str, Any]]
    #: l'onglet que sa faculté remplit sur la fiche d'une personne (son ancre dans Comptes, que le premier canal porte)
    tab: str
    #: son nom, en sous-onglet de Comptes
    label: str
    #: ce que dit la liste de ses comptes : la colonne qui nomme un compte, puis celles qui sont ses étiquettes
    noun: str
    badges: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OutsidePart:
    """Une sorte de ressource dont les outils viennent d'ailleurs (ADR 0192, 0219) : un service MCP, une app de la
    Forge. Ses outils sont rangés sous sa famille à elle (``mcp.<service>``, ``forge_apps.<app>``), et leur ligne est
    celle de leur ressource, que sa faculté déclare (``RightsSpec.grants``). L'écran Outils (``app/me/rights.py``) et
    Réglages › Droits (``app/handmade/rights.py``) réunissent les parts (``app/me/outside.py``), chacun dans l'ordre de
    sa page ; ils n'en connaissent aucune."""

    #: la sorte de ses droits, la fin de la clé de son ``RightsSpec`` (« services », « apps ») : son groupe dans l'écran
    #: Outils ; sa place : ``app/me/outside.py::OUTSIDE``
    sort: str
    #: le début du nom de la famille de ses outils (« mcp. », « forge_apps. ») : ses outils ne sont pas à elle
    bundle: str
    #: son groupe dans l'écran Outils, en mots (« Services », « Apps de la Forge »)
    title: str
    #: pourquoi une case, quand on ne sait pas redire sa ligne : ses accès, en mots (« les accès de ce service »)
    why: str
    #: ce qu'il lit une fois par lecture de la matrice : ``seen(kernel, frame)`` (les outils qu'offrent ses services et
    #: leur état ; les apps forgées) — ce que ses autres lectures reçoivent (``seen``)
    seen: Callable[..., Any]
    #: (l'outil chez elle, sa ressource) d'une de ses lignes : ``tool(seen, g)`` ; un outil vide : il n'est pas offert
    tool: Callable[..., tuple[str, str]]
    #: la lecture même de sa ligne, pour la redire à la personne : ``allowance(seen, frame, g, resource, tool, acts,
    #: audience, kind, rights, close)`` rend une ``vocab.rights.Allowance``, ou ``None``
    allowance: Callable[..., Any]
    #: le nom d'une de ses ressources, dit à la personne : ``name(seen, resource)``
    name: Callable[..., str]
    #: à quoi elle lui sert : ``about(seen, resource)`` (vide : rien à en dire)
    about: Callable[..., str]
    #: sa ligne dans Réglages › Droits, pour une de ses familles (``<bundle><nom>``) : ``row(frame, nom)`` rend son
    #: libellé et la clé du détail de ses accès
    row: Callable[..., tuple[str, str]]


@dataclass(frozen=True, slots=True)
class QueuePart:
    """Sa part de la file « À valider » (ADR 0177) : ce qu'il y inscrit, et ce qu'il dit d'une demande d'accord.
    La file (``app/handmade/waiting.py``) et les sources d'une demande (``app/handmade/approval_sources.py``)
    réunissent les parts ; elles n'en connaissent aucune."""

    #: ses onglets de la file (des ``inspector.ui.QueueTab``) : les demandes de ses capacités, ses sortes d'éléments ;
    #: leur place : leur ``order``
    tabs: tuple[Any, ...] = ()
    #: ce qui, chez lui, attend une décision sans être une demande d'envoi (les rapprochements de l'annuaire) :
    #: ``items(ui)``, asynchrone, rend des ``inspector.ui.QueueItem``
    items: Callable[..., Awaitable[list[Any]]] | None = None
    #: … et ``count(ui, kinds)`` les compte (``kinds`` : les sortes voulues ; ``None`` : toutes)
    count: Callable[..., int] | None = None
    #: les feuilles de ce qu'il dessine dans la liseuse de la file (les deux fiches côte à côte d'un rapprochement) ;
    #: la file les charge toutes, dans l'ordre des fiches, chacune une fois
    styles: tuple[str, ...] = ()
    #: ses vues qui montrent, dans sa destination, les mêmes demandes que la file (« destination/onglet ») : l'accueil
    #: ne les compte pas une seconde fois
    covers: tuple[str, ...] = ()
    #: les vues (propriétaire, vue) de ce qui attend chez lui hors des demandes d'envoi : la console en MCP les sert
    #: sous « la file « À valider » »
    views: tuple[tuple[str, str], ...] = ()
    #: capacité → la source d'une demande, en liens : ``sources(ui, args)`` rend (texte, adresse), du plus proche au
    #: plus large (le brouillon puis la boîte d'un mail)
    sources: Mapping[str, Callable[..., list[tuple[str, str]]]] = field(default_factory=dict)
    #: un canal qui pose son nom en contexte d'une demande (contexte → son mot : « Teams », « courrier ») : jamais une
    #: personne
    channels: Mapping[str, str] = field(default_factory=dict)
    #: le préfixe du contexte d'une demande (« mcp » dans ``mcp:agenda``) → ce qu'elle concerne : ``concern(ui,
    #: reste)`` rend un ``approval_sources.Concern`` (sa fiche, le texte de son lien), ou ``None`` : pas à lui
    contexts: Mapping[str, Callable[..., Any]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PersonPart:
    """Sa part de la fiche d'une personne (``app/handmade/person/``) : les onglets qu'il y dessine, ce qu'il y
    compte. La fiche réunit les parts ; elle n'en connaît aucune."""

    #: onglet de sa barre → ce qui le dessine : ``draw(ui, key, blocks, query)`` (les données restent celles de sa
    #: faculté ou de son plugin)
    tabs: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    #: ceux de ses onglets qui posent aussi les formulaires de la console : ``draw(ui, key, blocks, query, forms)``
    formed: tuple[str, ...] = ()
    #: onglet → ce qu'il y compte : ``count(look, who)``, qui s'ajoute à ce que le cadre y compte déjà
    counts: Mapping[str, Callable[..., int]] = field(default_factory=dict)
    #: ses onglets à taire pour cette personne : ``hidden(ui, key)`` rend leurs noms
    hidden: Callable[..., Sequence[str]] | None = None
    #: ses routes sous la fiche : ``routes(ui, outbound)`` rend des ``Route`` (le GPX d'un voyage)
    routes: Callable[..., list[Any]] | None = None
    #: ce qu'elle a chez lui sans être le compte d'un canal (les services qu'elle a branchés) : un sous-onglet de
    #: Comptes, après ceux des canaux — (son ancre, son nom, ``held(look, who)``), où ``held`` rend ses lignes, que le
    #: gabarit de Comptes dessine sous cette ancre ; elles comptent dans Comptes, et le montrent à qui n'a pas de boîte
    owned: tuple[str, str, Callable[..., list[Any]]] | None = None


@dataclass(frozen=True, slots=True)
class TablePart:
    """Un tableau de droits qu'il règle dans Réglages › Droits plutôt que sur la page de sa ressource (ADR 0309, lot 5 :
    celui d'un agenda) : « Modifier », sur le détail des accès d'une de ses ressources, l'ouvre à la place de sa
    lecture. La page (``app/handmade/rights.py``, son onglet : ``app/handmade/tabs/settings.py``) réunit les parts ;
    elle n'en connaît aucune."""

    #: le début de la clé de ses ressources, telle que ses droits la disent (« agenda: »)
    prefix: str
    #: où mène « Modifier » sur le détail des accès d'une de ses ressources : ``edit(key)``
    edit: Callable[[str], str]
    #: le tableau d'une de ses ressources, à régler : ``editor(ui, key, csrf)`` rend ce que dessine
    #: ``handmade/droits/tableau.html``, ou ``None`` (pas une des siennes)
    editor: Callable[..., Any]
    #: où son formulaire s'enregistre : ``routes(ui)`` rend des ``Route``
    routes: Callable[..., list[Any]]


@dataclass(frozen=True, slots=True)
class ConsolePart:
    """Sa part de la console : ce qu'il y *inscrit*. Chaque page garde son gabarit et sa feuille, écrits à la main
    (ADR 0121, 0177) ; rien ici n'en dessine une."""

    #: sorte d'objet (``Inspection.subject``) → sa fiche dessinée (une ``inspector.ui.Overview``)
    overviews: Mapping[str, Any] = field(default_factory=dict)
    #: « destination/onglet » → la forme dessinée de cet onglet (une ``inspector.ui.Drawn``, ADR 0177)
    drawn: Mapping[str, Any] = field(default_factory=dict)
    #: ses rubriques de réglages : ``sections(live)`` rend des ``inspector.catalog.SettingsSection`` (leur place dans
    #: leur rubrique : leur ``order``)
    sections: Callable[..., tuple[Any, ...]] | None = None
    #: sa part de la file « À valider »
    queue: QueuePart | None = None
    #: sa part de la fiche d'une personne
    person: PersonPart | None = None
    #: le tableau de droits qu'il règle dans Réglages › Droits
    table: TablePart | None = None
    #: où mène, dans la console, la ressource d'un de ses partages (sa fiche ; un compte Teams, son extension) :
    #: ``shared(s)`` (``s`` : un ``app/me/sharing.py::Shared`` de sa sorte) — Réglages › Droits › Partages et l'onglet
    #: Comptes de la fiche d'une personne la lisent (``app/handmade/rights.py::share_consoles``)
    shared: Callable[..., str] | None = None
    #: où se retire un de ses partages que la console ne retire pas elle-même (sa part des partages n'a pas
    #: d'écriture, ``SharingPart.write`` : un service se règle sur ses lignes d'accès) : ``unshared(s)`` rend son
    #: adresse
    unshared: Callable[..., str] | None = None


@dataclass(frozen=True, slots=True)
class PortPart:
    """Sa part du port d'entrée (``app/mindport.py::KernelPort``, qui tient ``contracts/entry.py::MindPort``) : ce
    que ses portes et ses écrans demandent au noyau. Le port réunit les parts ; il n'en connaît aucune. Il les lit à
    son import (il en fait une classe) : une part n'importe donc pas ``mika.app.mindport``."""

    #: ses méthodes du port d'entrée : une classe que ``KernelPort`` mêle aux siennes (elles lisent ``self.kernel``
    #: et ``self._store``, comme les autres) : de vraies méthodes, que le contrat voit comme celles du port. Deux parts
    #: n'ont pas une même méthode, et aucune ne reprend une méthode du port
    #: (``tests/architecture/test_frame_names_no_domain.py``)
    methods: type | None = None
    #: ce qu'il ajoute à ce que le panneau d'une personne dit, pour une propriétaire, du travail en cours
    #: (``KernelPort.person_panel``) : ``work(port, frame)`` rend un dictionnaire
    work: Callable[..., Mapping[str, Any]] | None = None


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
    #: les modules de ses entités rangées dans une base du cœur (le journal d'une app, dans ``views``) : les importer
    #: remplit la ``MetaData`` de cette base
    models: tuple[str, ...] = ()
    #: ses dossiers du dossier de données, et ce que chacun garde, en mots (Système › Stockage et sauvegardes) : des
    #: textes affichés, sans numéro de décision
    places: Mapping[str, str] = field(default_factory=dict)
    #: le module de ce qu'il dit à la sauvegarde de ses dossiers (``UNSAVED``, ``SAVED``)
    backup: str | None = None
    #: le module de son câblage (``wire``, ``bind``)
    wiring: str | None = None
    #: le module de ses réglages (``SETTINGS`` : sa ``SettingsPart``), pour qui les prend par le nom du domaine
    settings: str | None = None
    #: le module de son API par personne (``routes``, ``COUNTERS``)
    api: str | None = None
    #: le module de sa part du direct (``LIVE``)
    live: str | None = None
    #: le module de ce qu'il partage (``SHARING`` : sa ``SharingPart``)
    sharing: str | None = None
    #: le module des comptes de son canal (``ACCOUNTS`` : son ``AccountsPart``)
    accounts: str | None = None
    #: le module de ce qui vient d'ailleurs chez lui (``OUTSIDE`` : son ``OutsidePart``)
    outside: str | None = None
    #: le module de sa part de la console (``CONSOLE``)
    console: str | None = None
    #: le module de sa part du port d'entrée (``PORT`` : sa ``PortPart``)
    port: str | None = None
    #: le module de ce qu'il ajoute à l'aperçu de la console (``preview``)
    preview: str | None = None
    #: le module de sa commande (``add``)
    cli: str | None = None
    #: sa destination dans la console (une ``inspector.catalog.Destination``) : ce qu'elle est. Où elle est rangée
    #: se dit dans la carte de la console (``app/console.py``), qui la prend ici par le nom du domaine
    destination: Any = None
    #: son lien dans le menu de la console (une ``inspector.catalog.MenuLink``) ; sa place : ``app/console_menu.py``
    menu: Any = None
    #: sa ligne dans Réglages › Configuration des plugins, par plugin : ce qui s'y règle, ses rubriques de réglages,
    #: où l'on s'en sert (nom, « destination/onglet ») ; sa place : ``app/settings_sections/plugins.py::ORDER``
    plugins: Mapping[str, tuple[str, tuple[str, ...], tuple[str, str] | None]] = field(default_factory=dict)
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
