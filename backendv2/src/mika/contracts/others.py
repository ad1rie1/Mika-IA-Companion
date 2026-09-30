"""Contrat d'``others`` : ce qu'elle devine des autres, à partir de ce qu'ils font.

Pour chaque personne, un modèle appris de leur histoire, jamais d'un jugement
de modèle de langage :

- **son ton habituel** et **son état du moment**, lus dans la forme de ses
  messages (mots, ponctuation, majuscules, émojis) — l'état du moment
  s'efface vers l'habituel quand elle se tait ;
- **la surprise** : l'écart entre le ton qu'elle attendait de cette personne
  et celui qu'elle lit, pondéré par ce qu'elle la connaît. Un message lourd de
  quelqu'un qui râle toujours ne surprend pas ; le même, d'une amie d'humeur
  légère, oui — et l'inquiète ;
- **ses délais de réponse** à ses messages, par canal : on n'est pas « ignorée »
  par quelqu'un qui répond toujours le soir ;
- **les heures où elle répond** : chaque initiative restée sans réponse, ou
  comblée, à une heure donnée, rend la suivante à cette heure-là plus ou moins
  probable ;
- **prendre de ses nouvelles** : une amie qui n'avait pas l'air bien et qui
  n'a plus rien dit depuis, quelques heures plus tard, elle lui écrit.

Chaque lecture d'un message est un jugement enregistré (``others.read``) :
le rejeu retombe exactement sur le même modèle.
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Payload, event_type
from mika.kernel.facts import FactFamily

OWNER = "others"

#: Les classes de canal : à l'écran (on répond en minutes) ou par messagerie
#: (on lit quand on y pense).
SCREEN, MESSAGE = "screen", "message"
#: Les moments de la journée où elle écrit d'elle-même (heure locale).
NIGHT, MORNING, AFTERNOON, EVENING = "night", "morning", "afternoon", "evening"
BANDS = (NIGHT, MORNING, AFTERNOON, EVENING)
#: Raison de preuve d'initiative : prendre des nouvelles de quelqu'un qui n'avait pas l'air bien.
CHECK_IN = "check_in"


class ToneRead(Payload):
    """Ce qu'elle lit dans la forme d'un message, et ce qu'elle en attendait."""

    person: str
    handle: str
    message: int
    valence: float  # [-1, 1] : lourd … léger
    arousal: float  # [0, 1] : posé … agité
    #: les indices lus (des étiquettes écrites par le code, jamais le texte du message)
    cues: tuple[str, ...] = ()
    #: le ton qu'elle attendait de cette personne, avant ce message
    expected: float = 0.0
    #: ce qu'elle la connaît (0 : pas du tout, 1 : assez pour attendre quelque chose)
    confidence: float = 0.0
    #: |lu − attendu| × confiance
    surprise: float = 0.0
    #: nettement plus sombre que d'habitude, chez quelqu'un qui compte : elle s'inquiète
    concern: bool = False
    public: bool = False


READ = event_type("others.read", OWNER, ToneRead, public=True, subjects=("person",))
ALL = (READ,)


@dataclass(frozen=True, slots=True)
class MindReading:
    """Ce qu'elle devine d'une personne, à l'instant."""

    person: str
    observed: int  # messages lus
    usual_valence: float
    usual_arousal: float
    current_valence: float  # l'état du moment, qui s'efface vers l'habituel
    current_arousal: float
    deviation: float  # état du moment − habituel (valence)
    confidence: float
    last_at: int
    last_message: int
    last_cues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DelayReading:
    """Ses délais de réponse à ses messages, sur une classe de canal."""

    samples: int
    median_us: int  # 0 sans mesure


#: ``MIND(personne)``.
MIND = FactFamily("others.mind", arg=str, type=MindReading, time_varying=True)
#: ``REPLY_DELAY((personne, canal))`` — le canal tel que le transport le nomme
#: (« web », « telegram ») ; la classe (écran, messagerie) est tranchée ici.
REPLY_DELAY = FactFamily("others.reply_delay", arg=tuple, type=DelayReading)
