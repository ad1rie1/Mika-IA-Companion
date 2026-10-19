"""Contrat du plugin ``location`` : où est la personne qui lui écrit, quand son téléphone le lui dit (ADR 0119).

Ce n'est **pas un signal** : rien ne s'en remarque, rien n'en naît, aucune faculté ne le lit. C'est une donnée
qu'une personne donne d'elle-même, depuis son téléphone (un réglage coupé par défaut, l'application ouverte
seulement) : ses coordonnées et le nom du lieu sont des contenus — effaçables —, son adresse et sa personne pour
sujets. Elle ne la regarde qu'en tête-à-tête avec cette personne, pour elle seule (``location_where``), et chaque
regard se voit : le message qu'elle écrit emporte la référence de la position regardée (``note_ref``), que l'écran
montre en petite bulle.
"""

from __future__ import annotations

from mika.kernel.events import Content, Payload, event_type

OWNER = "location"
#: la sorte des petites bulles qui disent qu'elle a regardé où était la personne (``MessageNote.kind``)
NOTE_KIND = "location"
#: le préfixe des références que ses messages emportent (``ToolResult.attach``) : ``location:<seq>``
NOTE_PREFIX = "location:"


class Located(Payload):
    """Où était la personne, d'après son téléphone. ``coords`` : « latitude,longitude » (six décimales) ;
    ``label`` : le nom du lieu que le téléphone a trouvé (une rue, une ville), s'il en a trouvé un ;
    ``accuracy_m`` : sa précision (0 : inconnue) ; ``fixed_at`` : quand le téléphone l'a mesurée (horloge du noyau)."""

    handle: str
    person: str
    coords: Content
    label: Content | None = None
    accuracy_m: int = 0
    fixed_at: int


class Cleared(Payload):
    """La personne ne lui dit plus où elle est (le réglage coupé) : sa dernière position s'efface."""

    handle: str
    person: str


LOCATED = event_type("location.located", OWNER, Located, content=("coords", "label"), subjects=("handle", "person"))
CLEARED = event_type("location.cleared", OWNER, Cleared, subjects=("handle", "person"))
ALL = (LOCATED, CLEARED)


def note_ref(seq: int) -> str:
    """La référence qu'emporte un de ses messages quand elle a regardé la position ``seq``."""
    return f"{NOTE_PREFIX}{seq}"


def note_seq(ref: str) -> int | None:
    """La position que désigne une référence emportée par un de ses messages (``None`` : pas une des nôtres)."""
    if not isinstance(ref, str) or not ref.startswith(NOTE_PREFIX):
        return None
    tail = ref[len(NOTE_PREFIX):]
    return int(tail) if tail.isdigit() and len(tail) <= 18 else None
