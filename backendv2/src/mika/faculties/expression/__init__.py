"""``expression`` : comment ce qu'elle ressent sort d'elle.

- la balise : l'analyse de la balise à facettes ``[EMOTION: sad 0.6, love 0.3]`` (ADR 0093 ; l'ancienne forme
  ``[EMOTION:sad:0.6]`` est encore lue) qu'elle écrit en fin de réponse (retirée du texte, gardée en annotation de
  l'énoncé), de sa lecture de la personne (``[EN_FACE: …]``) et de sa marque de mensonge (``[MENSONGE: …]``), et le
  fait qu'elle ait posé une question (on en attend la réponse) ;
- la consigne de style (parler comme on parle, une échelle d'intensité, ce qu'est le bloc d'état interne : sa tête à
  elle, jamais citée), « COMMENT TU ÉCRIS ICI » (les codes d'écriture de l'autrice du chat) et « TA RÉPONSE » (le
  dernier mot avant son message) ;
- ce qu'elle se répète : ses derniers messages relus, ce qu'on l'entendrait redire, dit comme des faits dans « CE QUE
  TU TE RÉPÈTES » (ADR 0154) ;
- la seconde passe : une autrice écrit la suite du fil à partir de son premier jet, et seuls ses messages à elle
  partent (ADR 0114) ;
- le murmure : parfois, avant d'écrire à quelqu'un qui la regarde, une pensée à mi-voix — et parfois elle se ravise ;
- la livraison : un énoncé commité part vers les transports par la file de sortie, avec l'émotion à montrer et la
  voix à prendre.

Carte des modules (le sens de leurs imports : ``faculty`` et ``tags`` ne lisent aucun autre module d'expression ;
``style``, ``habits``, ``murmur`` et ``delivery`` lisent ``faculty`` ; ``polish`` lit ``tags``) :

- ``faculty`` : ses réglages (``ExpressionParams``), son état (``ExpressionState`` : à qui elle allait écrire quand
  elle s'est murmuré quelque chose) et la faculté (``EXPRESSION``) ;
- ``tags`` : la balise, sa lecture de la personne et sa marque de mensonge, lues et retirées du texte (``parse``),
  recalculées sur un texte récrit (``reannotate``) ;
- ``style`` : la consigne de style (``style``), celle du mode pro (``pro_style``), et les sections ``style``,
  ``form`` (« COMMENT TU ÉCRIS ICI ») et ``answer`` (« TA RÉPONSE ») ;
- ``habits`` : ce qu'elle se répète (``repeats``, ``asking_in_a_row``, ``said_of_herself``, ``pending_question``),
  les enrichisseurs qui relisent le fil (``own_words``, ``own_openings``, ``last_heard``) et la section ``habits``
  (« CE QUE TU TE RÉPÈTES ») ;
- ``polish`` : la seconde passe de l'autrice sur sa réponse (``polish``, ``authored``) et sur un brouillon d'outil
  (``polish_draft``, ADR 0124) ;
- ``murmur`` : le prélude ``murmur``, pourquoi elle écrit dit en clair (``why``), et le réducteur qui retient à qui
  elle allait écrire ;
- ``delivery`` : l'effet qui livre un énoncé commité (sur ``rt.UTTERANCE``) et ce que la trame montre de son émotion
  (``emotion_view``).

Le paquet donne ses noms publics ; ``style``, ``polish`` et ``murmur`` y sont les fonctions, pas les modules du même
nom : un nom privé se prend à son module (``from mika.faculties.expression.habits import _own_openings``).
"""

from __future__ import annotations

# l'ordre des modules est celui de leurs contributions (les sections style, form, answer puis habits)
# isort: off
from mika.faculties.expression.faculty import EXPRESSION, ExpressionParams, ExpressionState
from mika.faculties.expression.tags import parse, reannotate
from mika.faculties.expression.style import pro_style, style
from mika.faculties.expression.habits import asking_in_a_row, pending_question, repeats, said_of_herself
from mika.faculties.expression.polish import authored, polish, polish_draft
from mika.faculties.expression.murmur import murmur, why
from mika.faculties.expression.delivery import emotion_view
# isort: on

__all__ = [
    "EXPRESSION",
    "ExpressionParams",
    "ExpressionState",
    "asking_in_a_row",
    "authored",
    "emotion_view",
    "murmur",
    "parse",
    "pending_question",
    "polish",
    "polish_draft",
    "pro_style",
    "reannotate",
    "repeats",
    "said_of_herself",
    "style",
    "why",
]
