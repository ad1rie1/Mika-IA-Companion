"""Contrat du plugin ``wakeup`` : les réveils par API (ADR 0068).

Un opérateur déclare des **réveils** : chacun a sa terminaison d'URL (``POST /api/wake/<nom>``), sa clé, et ce qu'il
lui fait faire — un projet (ou aucun), le mode impersonnel, ses outils, des consignes, s'il passe outre son sommeil,
et à qui rendre compte. Un appel porte un texte : la **matière** de son travail, jamais une consigne (cité) ; les
consignes de l'opérateur priment.

``wakeup.called`` fige ce réglage au moment de l'appel (changer un réveil ne réécrit pas un appel reçu). Il est
public : le corps le lit (un réveil qui passe outre son sommeil la tire du sommeil, ``body.roused``), et un appel sur
un projet devient une exécution de ce projet. Ce que l'appel a donné revient à qui il faut le dire, par une
initiative due (``wakeup_done``, dans ``agency.OWED``).
"""

from __future__ import annotations

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily

OWNER = "wakeup"
#: la raison d'un épisode de réveil : un appel à traiter
WAKE = "wakeup"
#: la raison de l'initiative due : dire ce qu'un réveil a donné
DONE = "wakeup_done"
#: le sujet d'un épisode qui traite un appel (``wakeup:<seq>``), et la provenance de ce qu'une section en montre
PREFIX = "wakeup:"
#: personne à prévenir ; ses propriétaires (sinon : l'adresse d'un compte, ``user_<id>``)
NOBODY, OWNERS = "personne", "proprietaire"


def subject(call: int) -> str:
    return f"{PREFIX}{call}"


def call_of(subject: str | None) -> int | None:
    """Le ``seq`` de l'appel qu'un sujet d'épisode traite, sinon ``None``."""
    if not subject or not subject.startswith(PREFIX):
        return None
    tail = subject[len(PREFIX):]
    return int(tail) if tail.isdigit() else None


class Called(Payload):
    """Un appel reçu par un réveil, avec le réglage du réveil à cet instant."""

    endpoint: str
    #: à quoi sert le réveil (ce que l'opérateur en a dit)
    label: str = ""
    #: ce que l'appel apporte : une donnée venue d'ailleurs
    text: Content
    #: les consignes de l'opérateur (elles priment sur le texte)
    instructions: Content | None = None
    #: le mode impersonnel (sans persona, sans affect)
    plain: bool = False
    #: le projet sur lequel il travaille (0 : aucun)
    project: int = 0
    #: les lots d'outils qu'il lui donne
    bundles: tuple[str, ...] = ()
    #: il passe outre son sommeil (il la réveille, comme le message d'une proche)
    rouse: bool = False
    #: à qui rendre compte : ``NOBODY``, ``OWNERS`` ou l'adresse d'un compte
    notify: str = NOBODY
    #: au-delà, un appel resté en attente n'est plus traité (0 : jamais)
    expires_at: int = 0
    #: la personne à qui il rend compte, quand c'est un compte (l'oubli l'atteint)
    about: tuple[str, ...] = ()


CALLED = event_type("wakeup.called", OWNER, Called, public=True, content=("text", "instructions"),
                    subjects=("about",))
ALL = (CALLED,)

#: l'état d'un appel (``""`` : inconnu) — la garde d'un épisode qui le traite le lit : il ne vaut plus quand l'appel
#: expire ou est annulé (son propre compte rendu ne le fait pas tomber)
STATUS = FactFamily("wakeup.status", arg=int, type=str, doc="l'état d'un appel")
#: ce que l'appel a donné n'est pas encore dit à qui doit le savoir
UNTOLD = FactFamily("wakeup.untold", arg=int, type=bool, doc="le compte rendu d'un réveil pas encore dit")
#: les appels d'un réveil pas encore traités (en attente ou en cours) : la porte HTTP refuse au-delà d'un plafond
PENDING = FactFamily("wakeup.pending", arg=str, type=int, doc="les appels d'un réveil en attente ou en cours")
