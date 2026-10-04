"""Contrat de ``shares`` : les fichiers qu'elle envoie à la personne à qui elle parle (ADR 0062).

Un texte qu'elle écrit en parlant (une liste, une note, du code, un tableau) ou un fichier d'un de ses projets.
Les **octets vivent hors du journal** (le port ``shares``, comme les brouillons du courrier, ADR 0027) : le
journal ne garde que ce qu'il faut pour raconter, rendre et oublier — l'identifiant, le nom (un contenu,
effaçable), la taille, l'empreinte. Un fichier part **avec** un message : l'outil le prépare, l'énoncé qui suit
l'emporte (``Utterance.attachments``, des références opaques pour le reste du moteur).

- ``shares.shared`` : un fichier préparé pour ``target`` (une adresse). Tant qu'aucun message ne l'a emporté, il
  « n'est pas parti » (une réponse supplantée, une abstention) ; la rétention finit par le retirer.
- ``shares.expired`` : des fichiers retirés (trop vieux, ou la place d'une personne dépassée) ; leurs octets sont
  effacés après le commit. La ligne reste, « retiré ».

Un fichier peut aussi venir d'ailleurs (ADR 0061) : un propriétaire qui produit un fichier pour quelqu'un (un dessin,
qui prend des minutes) en dépose les octets dans le même port et lève **son** événement public, dont la charge utile
dérive de ``ProducedFile`` ; ``shares`` le traite comme les siens — même ligne, même départ avec un message, même
rétention, même oubli. Le message qui l'emporte, c'est l'outil du producteur qui le joint (``ToolResult.attach``).
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily

OWNER = "shares"
#: la projection T0 : une ligne par fichier préparé (ce que rendent l'écran, le téléchargement et la console)
TABLE = "shared_files"

# sortes et origines
FILE, IMAGE = "file", "image"
KINDS = (FILE, IMAGE)
WRITTEN, PROJECT, DRAWN = "written", "project", "drawn"
ORIGINS = (WRITTEN, PROJECT, DRAWN)
# raisons d'un retrait
RETENTION, BUDGET = "retention", "budget"
REASONS = (RETENTION, BUDGET)


class Shared(Payload):
    """Un fichier préparé pour une personne. ``file`` : 32 caractères hexadécimaux, la clé des octets (déterministe :
    un même appel recomposé redonne le même fichier) ; ``digest`` : leur SHA-256 (ce qu'on rend est ce qui a été
    écrit). ``path`` : son chemin dans l'atelier, pour un fichier de projet."""

    file: str
    target: str
    name: Content
    mime: str
    size: int
    digest: str
    kind: str = FILE
    origin: str = WRITTEN
    project: int | None = None
    path: Content | None = None
    #: les personnes qu'il concerne (celle à qui il part, celles du projet) : l'oubli les atteint
    about: tuple[str, ...] = ()


class ProducedFile(Payload):
    """La forme d'un fichier produit ailleurs pour une personne (voir l'en-tête) : ses octets sont déjà dans le
    port ``shares`` sous ``file``, avec ``target`` et ``about`` pour sujets. Le producteur déclare son événement
    public avec ``content=("name", …)`` et ``subjects=("target", "about")``."""

    file: str
    target: str
    name: Content
    mime: str
    size: int
    digest: str
    kind: str = FILE
    origin: str = DRAWN
    about: tuple[str, ...] = ()


class Expired(Payload):
    """Des fichiers d'une personne retirés : leurs octets s'effacent, la ligne reste (« retiré »)."""

    files: tuple[str, ...]
    target: str
    reason: str = RETENTION


SHARED = event_type("shares.shared", OWNER, Shared, public=True, content=("name", "path"),
                    subjects=("target", "about"))
EXPIRED = event_type("shares.expired", OWNER, Expired, public=True, subjects=("target",))
ALL = (SHARED, EXPIRED)


@dataclass(frozen=True, slots=True)
class SentView:
    """Un fichier encore gardé pour une adresse. ``message`` : le ``seq`` du message qui l'a emporté (0 : il n'est
    pas parti)."""

    file: str
    at: int
    size: int
    name_ref: str
    kind: str = FILE
    origin: str = WRITTEN
    project: int | None = None
    message: int = 0


#: Combien de fichiers elle a préparés pour cette adresse sur les dernières 24 heures (glissantes).
SENT_TODAY = FactFamily("shares.sent_today", arg=str, type=int, time_varying=True)
#: Les fichiers encore gardés pour cette adresse, du plus ancien au plus récent (``SentView``).
RECENT = FactFamily("shares.recent", arg=str, type=tuple)
