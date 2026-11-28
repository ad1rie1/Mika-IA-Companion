"""Contrat du plugin ``imaging`` : les dessins qu'elle fait pour quelqu'un (ADR 0063).

Un dessin prend des minutes : on le lui demande en conversation, elle répond qu'elle s'y met, un processus le
génère (port ``imaging``, ADR 0061), et c'est un message suivant — une initiative due, ou sa réponse si la
personne écrit entre-temps — qui l'emporte. Les octets vont dans le port ``shares`` et ``imaging.drawn`` dérive
de ``shares.ProducedFile`` : la faculté ``shares`` le range comme ses fichiers (même départ, rétention, oubli).

- ``imaging.requested`` : une demande acceptée — le prompt qu'elle a écrit (un contenu, effaçable), la proportion,
  la qualité, et si c'est un contenu pour adultes (permis seulement à sa propriétaire, en privé, et seulement vers
  un fournisseur qui l'accepte) ;
- ``imaging.drawn`` : le dessin est prêt — le fichier (dans ``shares``), ce qu'elle voit de son dessin (``caption``,
  pour en parler sans l'avoir sous les yeux), ce qu'il a coûté ;
- ``imaging.failed`` : il n'a pas pu se faire (un refus de modération, une panne, aucun fournisseur) — elle le dit.
"""

from __future__ import annotations

from mika.contracts.shares import DRAWN as DRAWN_ORIGIN
from mika.contracts.shares import IMAGE, ProducedFile
from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily

OWNER = "imaging"
#: le lot d'outils (dessiner, montrer un dessin)
BUNDLE = "imaging"

#: Raison (dû) : un dessin promis est prêt — le montrer à la personne.
DELIVER = "drawing_ready"
#: Raison (dû) : un dessin promis n'a pas pu se faire — le lui dire.
COULD_NOT = "drawing_failed"

# l'état d'un dessin : demandé (en cours), prêt, montré (un message l'a emporté), raté, raté et dit
WAITING, READY, SHOWN, MISSED, TOLD = "waiting", "ready", "shown", "missed", "told"
#: Où en est ce dessin (``job``) ; « » : inconnu. Ce que gardent les épisodes qui le montrent ou le disent.
STATUS = FactFamily("imaging.status", arg=str, type=str)

# issues d'un échec (celles de la passerelle, ``ports.imaging``)
REFUSED, FAILED_, TIMEOUT, UNSUPPORTED, UNCONFIGURED, TOO_BIG = (
    "refused", "failed", "timeout", "unsupported", "unconfigured", "too_big")


class Requested(Payload):
    """Une demande acceptée. ``job`` : son identifiant (déterministe : un appel recomposé retombe dessus) ;
    ``target`` : l'adresse d'où elle vient ; ``person`` : la personne derrière (le dessin peut partir sur une autre
    de ses adresses) ; ``prompt`` : ce qu'elle a écrit pour le fournisseur."""

    job: str
    target: str
    person: str = ""
    prompt: Content
    aspect: str = "square"
    quality: str = "draft"
    adult: bool = False
    #: la demande vient de sa propriétaire : un refus d'un service hébergé peut repartir vers le serveur local
    owner: bool = False
    about: tuple[str, ...] = ()


class Drawn(ProducedFile):
    """Le dessin est prêt (ses octets sont dans ``shares``, sous ``file``)."""

    job: str
    person: str = ""
    kind: str = IMAGE
    origin: str = DRAWN_ORIGIN
    #: ce qu'elle voit de son dessin (décrit par le rôle ``caption``) ; absent si elle n'a pas pu le regarder
    caption: Content | None = None
    backend: str = ""
    model: str = ""
    #: la taille réellement demandée au fournisseur (« 1536x864 ») et le temps qu'il a pris
    pixels: str = ""
    seconds: float = 0.0
    cost_usd: float = 0.0


class Failed(Payload):
    """Le dessin n'a pas pu se faire. ``outcome`` : un code (ci-dessus) ; ``reason`` : ce que le fournisseur en a dit
    (un contenu : un message de modération peut citer la demande)."""

    job: str
    target: str
    person: str = ""
    outcome: str
    reason: Content | None = None


REQUESTED = event_type("imaging.requested", OWNER, Requested, content=("prompt",), subjects=("target", "person", "about"))
DRAWN = event_type("imaging.drawn", OWNER, Drawn, public=True, content=("name", "caption"),
                   subjects=("target", "person", "about"))
FAILED = event_type("imaging.failed", OWNER, Failed, content=("reason",), subjects=("target", "person"))
ALL = (REQUESTED, DRAWN, FAILED)
