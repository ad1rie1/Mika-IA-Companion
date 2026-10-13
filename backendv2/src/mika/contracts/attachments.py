"""Contrat de ``attachments`` : ce qu'on lui envoie dans une conversation (ADR 0106).

Une photo, un document, un message vocal, joints à un message. Au bord, elle en perçoit tout de suite l'essentiel
(``ports.preprocess``) ; ici, la pièce **reste** : ses octets hors du journal (le port ``attachments``, comme les
fichiers qu'elle envoie, ADR 0062), sa fiche au journal — son nom et ce qu'elle y a lu sont des contenus, effaçables.

- Le message qui la porte la désigne (``AttachmentMeta.file``, ``contracts.runtime``) : la même pièce renvoyée par
  la même adresse est la même pièce, portée par deux messages.
- ``attachments.kept`` : la pièce lue de près, en fond, juste après le message (une photo décrite en détail, son
  texte visible ; le texte d'un document ; la transcription d'un vocal), et ce qu'elle a de sensible.
- **Un lien n'est pas une source.** Les sources d'un souvenir, d'une croyance, d'un moment restent des messages ;
  ses pièces sont **en plus**, et il peut y en avoir plusieurs — dans les deux sens : une pièce nourrit plusieurs
  éléments, un élément s'appuie sur plusieurs pièces. Un lien naît de la relecture (``pieces`` des événements de la
  mémoire) ou d'elle-même, plus tard (``attachments.linked``, son outil).
- ``attachments.expired`` : des pièces retirées (trop vieilles, ou la place d'une personne dépassée) ; leurs octets
  s'effacent, ce qu'elle en avait lu reste.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Content, Payload, event_type

OWNER = "attachments"
#: la projection T0 : une ligne par pièce lue (ce que lisent ses outils, la console, le téléchargement)
TABLE = "received_files"
#: quels messages portent quelles pièces (une pièce renvoyée : deux messages)
CARRIED = "received_messages"
#: les liens entre une pièce et ce qu'elle sait (souvenir, croyance, moment)
LINKS = "received_links"
#: le port des octets, et l'index des vecteurs des pièces (à part de celui de la mémoire : son rapprochement retire
#: toute clé qui n'est pas à elle)
PORT = "attachments"
VECTORS = "attachment_vectors"

# sortes
IMAGE, AUDIO, FILE = "image", "audio", "file"
KINDS = (IMAGE, AUDIO, FILE)
# qui a fait un lien
BY_REREAD, BY_HER = "reread", "her"
# raisons d'un retrait
RETENTION, BUDGET = "retention", "budget"
REASONS = (RETENTION, BUDGET)


class Kept(Payload):
    """Une pièce reçue, lue de près. ``file`` : 32 caractères hexadécimaux, la clé de ses octets ; ``message`` : le
    ``seq`` du premier message qui l'a portée, ``index`` sa place dans ce message (à partir de 1). ``seen`` : ce
    qu'elle y a lu (``None`` : rien de lisible) ; ``read`` : elle a vraiment pu la lire ; ``stored`` : ses octets
    sont gardés. ``sensitivity`` : personnelle en privé, anodine dans un salon public, une confidence quand la
    lecture l'a jugée intime (une photo intime, des papiers)."""

    file: str
    message: int
    index: int = 1
    handle: str
    room: str | None = None
    public: bool = False
    name: Content
    mime: str
    size: int = 0
    digest: str = ""
    kind: str = FILE
    seen: Content | None = None
    read: bool = False
    stored: bool = True
    sensitivity: int = 1
    #: la personne derrière l'adresse, quand elle est connue : l'oubli l'atteint aussi
    about: tuple[str, ...] = ()


class Linked(Payload):
    """Elle relie (ou délie, ``removed``) une pièce à ce qu'elle sait : ``item``, le ``seq`` d'un souvenir, d'une
    croyance ou d'un moment."""

    file: str
    item: int
    by: str = BY_HER
    removed: bool = False


class Expired(Payload):
    """Des pièces d'une adresse retirées : leurs octets s'effacent, leur ligne et ce qu'elle en a lu restent."""

    files: tuple[str, ...]
    handle: str
    reason: str = RETENTION


KEPT = event_type("attachments.kept", OWNER, Kept, public=True, content=("name", "seen"),
                  subjects=("handle", "about"))
LINKED = event_type("attachments.linked", OWNER, Linked, public=True)
EXPIRED = event_type("attachments.expired", OWNER, Expired, public=True, subjects=("handle",))
ALL = (KEPT, LINKED, EXPIRED)


@dataclass(frozen=True, slots=True)
class KeptView:
    """Une pièce encore gardée pour une adresse (la place, la rétention)."""

    file: str
    at: int
    size: int
    stored: bool = True
