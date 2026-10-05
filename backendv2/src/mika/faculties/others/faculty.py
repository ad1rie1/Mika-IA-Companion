"""La faculté ``others`` : ce qu'elle devine des autres.

- **Le ton habituel** d'une personne se construit message après message (une
  moyenne lente, qui part d'une neutralité supposée : trois premiers messages
  ne font pas un caractère) ; **l'état du moment** suit ses derniers messages
  et s'efface vers l'habituel quand elle se tait (demi-vie).
- **La surprise** est l'écart entre le ton attendu (l'état du moment juste
  avant le message) et le ton lu, pondéré par ce qu'elle la connaît : on ne
  s'étonne pas d'une inconnue — la connaître demande des messages *et* un
  lien (une connaissance au moins : dix minutes d'insultes n'en font pas une). Nettement plus sombre que d'habitude, chez une
  amie ou une proche : elle s'inquiète (et l'attention en garde une pensée).
- **Ses délais de réponse** se mesurent entre une initiative (pas une
  salutation, pas un rappel) et le message suivant de la personne, par classe
  de canal ; l'attention s'en sert pour ne pas se croire ignorée trop tôt.
- **Les heures où elle répond** : les attentes comblées ou déçues, rangées
  par moment de la journée, font une probabilité (bêta, avec un a priori) ;
  l'écart à l'a priori, en log-odds borné, module ses initiatives vers elle à
  cette heure-là. Elle apprend quand écrire à Alice.
- **Prendre de ses nouvelles** : une amie ou une proche dont le dernier
  message l'a inquiétée, et qui n'a rien écrit de plus léger depuis — passé
  quelques heures (et pas trop), en journée, elle lui écrit. Une fois : lui
  écrire (cette prise de nouvelles, ou la pensée inquiète qui l'a poussée à
  lui écrire avant), ou un vrai message d'elle qui va mieux, éteint l'inquiétude.
- **Ce qu'une amie avait de prévu** : la veille au soir (ou le matin même,
  pour un moment l'après-midi), un mot pour l'encourager, si elle ne lui a pas
  déjà parlé ce soir-là ; quelques heures après, si elle n'a pas eu de
  nouvelles d'elle depuis et qu'elles n'en ont pas reparlé, « alors, ça s'est
  passé comment ? ». Une fois chacun (l'initiative qui le dit porte le moment
  pour sujet). Jamais ce qu'un tiers a raconté d'elle. Avec insistance pour ce
  qui compte, si elle y pense pour l'ordinaire ; quand quelque chose de grave
  la touche ces jours-ci (``memory.hard_times`` : un deuil, une rupture),
  l'ordinaire se tait et ce qui compte passe après des nouvelles d'elle.
- **Ce qui se fête** (un anniversaire, un mariage) : ni « bonne chance » la
  veille, ses vœux le jour même, d'elle-même, une fois ; « comment ça s'est
  passé » le lendemain seulement si elle ne l'a pas souhaité (ADR 0052).
- **Les heures où elle écrit** : chaque message lu, rangé à son heure ; une
  fois assez de jours vus, on sait quand elle dort et quand elle passe.
- **« Bonne nuit »** : un message qui clôt la conversation se lit comme tel.

Tout se déduit du journal : les lectures de ton sont des jugements
enregistrés (``others.read``), le reste des événements publics des autres.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import expression as expression_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import others as c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.faculties.others.tone import closing, measure
from mika.kernel.arbitration import Candidate, Modulation, RowView
from mika.kernel.clock import DAY, HOUR, MINUTE, instant, within_daily_window
from mika.kernel.events import Draft
from mika.kernel.faculty import Faculty, Zone
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, floor
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.vocab import privacy
from mika.vocab.affect import Appraisal, Declared, Emotion, emotion_of
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.people import is_identifiable
from mika.vocab.temperament import Temperament, lerp
from mika.vocab.words import SALUTATIONS, fold

#: Combien d'initiatives en cours on retient (des épisodes qui n'ont jamais parlé s'y oublient).
OPENINGS_KEPT = 16
#: Combien de réponses tardives on sait reconnaître.
MISSED_KEPT = 64
#: Les (jour, heure) où chacun a écrit, retenus au plus (distincts) : de quoi apprendre ses heures.
HOURS_KEPT = 96
#: Les moments dont elle a parlé d'elle-même (encourager, demander comment ça s'est passé), retenus au plus.
SPOKE_KEPT = 128
#: le sujet d'une initiative qui porte sur un moment de la vie de quelqu'un : ``moment:<id>``
MOMENT_SUBJECT = "moment:"


def moment_of(subject: str | None) -> int | None:
    if not subject or not subject.startswith(MOMENT_SUBJECT) or not subject[len(MOMENT_SUBJECT):].isdigit():
        return None
    return int(subject[len(MOMENT_SUBJECT):])


class OthersParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # son ton habituel, son état du moment
    usual_weight: Annotated[float, Knob(
        label="Poids d'un message dans le ton habituel", group="Ce qu'elle devine de son ton", lo=0.01, hi=0.5,
        step=0.01, help="Le ton habituel d'une personne bouge d'autant à chaque message. Plus haut : un mauvais "
                        "jour change vite ce qu'elle attend d'elle ; plus bas : il faut des semaines.")] = 0.08
    usual_prior: Annotated[int, Knob(
        label="Messages neutres supposés au départ", group="Ce qu'elle devine de son ton", lo=0, hi=20,
        help="Avant de la connaître, elle lui prête autant de messages neutres : trois premiers messages "
             "tristes ne font pas une personne triste.")] = 2
    recent_weight: Annotated[float, Knob(
        label="Poids d'un message dans l'état du moment", group="Ce qu'elle devine de son ton", lo=0.05, hi=1.0,
        step=0.05, help="L'état du moment qu'elle lui prête suit chaque message d'autant (1 : le dernier message "
                        "seul).")] = 0.5
    recent_half_life_us: Annotated[int, Knob(
        label="L'état du moment s'efface en", group="Ce qu'elle devine de son ton", lo=10 * MINUTE, hi=3 * DAY,
        help="Sans nouveau message, ce qu'elle lui prête revient vers son ton habituel avec cette demi-vie.")] = \
        3 * HOUR
    confident_after: Annotated[int, Knob(
        label="La connaître après (messages)", group="Ce qu'elle devine de son ton", lo=1, hi=100,
        help="Après tant de messages lus, elle sait assez de son ton pour s'étonner d'un écart et le dire.")] = 8
    notable_deviation: Annotated[float, Knob(
        label="Écart qui se remarque", group="Ce qu'elle devine de son ton", lo=0.05, hi=1.0, step=0.05,
        help="Un écart au ton habituel au moins aussi grand se dit dans le prompt (« ça ne lui ressemble pas »), "
             "seulement en privé.")] = 0.25
    # la surprise
    surprise_from: Annotated[float, Knob(
        label="Surprise à partir de", group="Surprise et inquiétude", lo=0.05, hi=2.0, step=0.05,
        help="Un écart entre le ton attendu et le ton lu (pondéré par ce qu'elle la connaît) au moins aussi grand "
             "la surprend.")] = 0.45
    surprise_gain: Annotated[float, Knob(
        label="Force de la surprise", group="Surprise et inquiétude", lo=0.0, hi=1.0, step=0.05,
        help="La surprise ressentie vaut l'écart multiplié par ce facteur (dérivé de la réactivité).")] = 0.5
    surprise_max: Annotated[float, Knob(
        label="Surprise au plus", group="Surprise et inquiétude", lo=0.0, hi=1.0, step=0.05,
        help="Une surprise ne dépasse jamais cette intensité : un étonnement, pas un choc.")] = 0.4
    concern_below: Annotated[float, Knob(
        label="Inquiétude : ton au plus", group="Surprise et inquiétude", lo=-1.0, hi=0.0, step=0.05,
        help="Elle s'inquiète pour une amie ou une proche dont le message est au moins aussi lourd…")] = -0.3
    concern_drop: Annotated[float, Knob(
        label="Inquiétude : plus sombre que d'habitude de", group="Surprise et inquiétude", lo=0.05, hi=2.0,
        step=0.05, help="… et plus sombre que ce qu'elle attendait d'elle d'au moins autant : un message lourd de "
                        "quelqu'un qui râle toujours ne l'inquiète pas.")] = 0.45
    concern_confidence: Annotated[float, Knob(
        label="Inquiétude : la connaître au moins", group="Surprise et inquiétude", lo=0.0, hi=1.0, step=0.05,
        help="La part de « la connaître » qu'il faut pour s'inquiéter d'un écart (1 : tous les messages "
             "ci-dessus).")] = 0.5
    worry_intensity: Annotated[float, Knob(
        label="Inquiétude ressentie", group="Surprise et inquiétude", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité de l'inquiétude qu'elle ressent sur le moment (suit la contagion du tempérament).")] = 0.2
    # ses délais de réponse
    delay_samples: Annotated[int, Knob(
        label="Délais retenus", group="Ses délais de réponse", lo=3, hi=50,
        help="Les derniers délais de réponse retenus par personne et par canal ; le délai habituel est leur "
             "médiane.")] = 9
    delay_max_us: Annotated[int, Knob(
        label="Délai au-delà duquel ce n'est plus une réponse", group="Ses délais de réponse", lo=HOUR,
        hi=14 * DAY, help="Un message qui arrive plus tard n'est pas compté comme une réponse à son initiative.")] = \
        2 * DAY
    # les heures où elle répond
    receptivity_prior_answered: Annotated[float, Knob(
        label="A priori : initiatives comblées", group="Les heures où elle répond", lo=0.1, hi=20, step=0.1,
        help="Avant d'avoir rien vu, elle fait comme si tant d'initiatives à cette heure avaient reçu une "
             "réponse…")] = 2.0
    receptivity_prior_missed: Annotated[float, Knob(
        label="A priori : initiatives sans réponse", group="Les heures où elle répond", lo=0.1, hi=20, step=0.1,
        help="… et tant d'autres, aucune. Plus l'a priori est gros, plus il faut d'expérience pour la faire "
             "changer d'heure.")] = 1.0
    receptivity_min_observations: Annotated[int, Knob(
        label="Observations avant d'en tenir compte", group="Les heures où elle répond", lo=1, hi=20,
        help="En deçà de tant d'initiatives à cette heure-là, rien ne change.")] = 2
    receptivity_max_shift: Annotated[float, Knob(
        label="Poids au plus", group="Les heures où elle répond", lo=0.0, hi=4.0, step=0.1,
        help="L'expérience rend une initiative à cette heure plus ou moins probable d'au plus tant (log-odds ; "
             "le seuil d'initiative est à 9).")] = 1.5
    # prendre de ses nouvelles
    checkin_after_us: Annotated[int, Knob(
        label="Prendre de ses nouvelles après", group="Prendre de ses nouvelles", lo=30 * MINUTE, hi=2 * DAY,
        help="Une amie dont le dernier message l'a inquiétée et qui n'a rien écrit depuis : passé ce délai, elle "
             "a envie de prendre de ses nouvelles.")] = 3 * HOUR
    checkin_jitter: Annotated[float, Knob(
        label="Variation de ce délai", group="Prendre de ses nouvelles", lo=0.0, hi=3.0, step=0.1,
        help="Le délai est allongé d'une part tirée au hasard, jusqu'à cette fraction (1 : de trois à six "
             "heures) : on n'écrit pas à heure fixe. Le tirage est enregistré avec l'inquiétude.")] = 1.0
    checkin_until_us: Annotated[int, Knob(
        label="… et jusqu'à", group="Prendre de ses nouvelles", lo=HOUR, hi=7 * DAY,
        help="Au-delà, l'inquiétude est passée (c'est le manque qui prendra le relais, à son rythme).")] = 30 * HOUR
    checkin_evidence_start: Annotated[float, Knob(
        label="Envie de prendre des nouvelles, au début", group="Prendre de ses nouvelles", lo=0.0, hi=12.0,
        step=0.5, help="Preuve d'initiative (log-odds) quand le délai ci-dessus vient de passer : elle y pense, "
                       "sans urgence. Elle monte ensuite jusqu'à la preuve pleine.")] = 2.0
    checkin_evidence: Annotated[float, Knob(
        label="Preuve d'une prise de nouvelles", group="Prendre de ses nouvelles", lo=0.0, hi=12.0, step=0.5,
        help="La preuve pleine (log-odds). Au-dessus du seuil d'initiative (9), elle écrit seule ; la retenue "
             "(rancune, pas deux messages de suite sans réponse) s'applique.")] = 9.5
    checkin_ramp_us: Annotated[int, Knob(
        label="L'envie monte en", group="Prendre de ses nouvelles", lo=MINUTE, hi=DAY,
        help="Le temps pour passer de l'envie du début à la preuve pleine : l'heure où elle écrit varie, comme "
             "chez quelqu'un qui y repense de plus en plus.")] = 3 * HOUR
    checkin_day_start_min: Annotated[int, Knob(
        label="Prendre des nouvelles : à partir de", group="Prendre de ses nouvelles", lo=0, hi=24 * 60,
        help="Heure locale (minutes depuis minuit) à partir de laquelle elle écrit pour prendre des nouvelles.")] = \
        9 * 60
    checkin_day_end_min: Annotated[int, Knob(
        label="Prendre des nouvelles : jusqu'à", group="Prendre de ses nouvelles", lo=0, hi=24 * 60,
        help="Heure locale après laquelle elle ne le fait plus (avant le début : la plage passe minuit).")] = 22 * 60
    # demander comment ça s'est passé
    followup_after_us: Annotated[int, Knob(
        label="Demander comment ça s'est passé après", group="Demander comment ça s'est passé", lo=0, hi=2 * DAY,
        help="Ce qu'une amie lui avait dit de prévu (un entretien, un examen) : passé l'heure dite (18 h pour un "
             "jour sans heure) et ce délai, elle a envie de savoir comment ça s'est passé — sauf si elles en ont "
             "déjà reparlé.")] = 2 * HOUR
    followup_until_us: Annotated[int, Knob(
        label="… et jusqu'à", group="Demander comment ça s'est passé", lo=HOUR, hi=7 * DAY,
        help="Au-delà, ce n'est plus d'actualité : elle n'y revient pas d'elle-même.")] = 36 * HOUR
    followup_evidence: Annotated[float, Knob(
        label="Preuve d'une telle question", group="Demander comment ça s'est passé", lo=0.0, hi=12.0, step=0.5,
        help="La preuve pleine (log-odds) pour un moment qui compte (un entretien, un examen) ; elle monte comme "
             "pour une prise de nouvelles. La retenue (pas deux messages de suite sans réponse) s'applique.")] = 9.5
    followup_minor_evidence: Annotated[float, Knob(
        label="… pour un moment ordinaire", group="Demander comment ça s'est passé", lo=0.0, hi=12.0, step=0.5,
        help="Pour un moment ordinaire (un rendez-vous de routine, une sortie) — ou pour ce qui compte quand "
             "quelque chose de grave la touche ces jours-ci, après des nouvelles d'elle —, elle le demande si elle "
             "y pense : sous le seuil d'initiative (9). Un moment ordinaire, ces jours-là, ne se demande pas du "
             "tout.")] = 6.0
    celebrate_evidence: Annotated[float, Knob(
        label="Souhaiter ce qui se fête : preuve", group="Demander comment ça s'est passé", lo=0.0, hi=12.0,
        step=0.5, help="Le jour d'un anniversaire, d'un mariage (ce que la personne lui avait annoncé), l'envie de "
                       "le lui souhaiter, une fois, dans ses heures pour prendre des nouvelles : plus forte qu'une "
                       "question (au-dessus du seuil d'initiative, 9, elle écrit seule).")] = 10.0
    cheer_evidence: Annotated[float, Knob(
        label="Encourager la veille : preuve", group="Demander comment ça s'est passé", lo=0.0, hi=12.0, step=0.5,
        help="La veille au soir (ou le matin même, pour un moment l'après-midi), l'envie de lui souhaiter bonne "
             "chance : plus faible que demander comment ça s'est passé — elle le fait si elle y pense. Monte depuis "
             "l'envie du début, comme une prise de nouvelles.")] = 6.0
    cheer_eve_start_min: Annotated[int, Knob(
        label="Encourager la veille : à partir de", group="Demander comment ça s'est passé", lo=0, hi=24 * 60,
        help="Heure locale (minutes depuis minuit) à partir de laquelle, la veille, elle peut lui souhaiter bonne "
             "chance (jusqu'à la fin de ses heures pour prendre des nouvelles). Si elles se sont parlé depuis, la "
             "conversation en était l'occasion.")] = 18 * 60
    # les heures où elle écrit
    hours_min_days: Annotated[int, Knob(
        label="Ses heures : jours vus avant d'en tenir compte", group="Les heures où elle écrit", lo=2, hi=30,
        help="Après tant de jours où la personne a écrit, elle sait à quelles heures elle écrit (et quand elle "
             "dort) ; avant, elle lui prête une nuit ordinaire (ci-dessous).")] = 4
    assumed_night_start_min: Annotated[int, Knob(
        label="Nuit supposée : à partir de", group="Les heures où elle écrit", lo=0, hi=24 * 60,
        help="Avant de connaître ses heures, elle suppose que la personne dort à partir de cette heure locale…")] = \
        23 * 60
    assumed_night_end_min: Annotated[int, Knob(
        label="Nuit supposée : jusqu'à", group="Les heures où elle écrit", lo=0, hi=24 * 60,
        help="… et jusqu'à celle-ci : sa nuit n'est pas un silence.")] = 8 * 60
    receptivity_late_weight: Annotated[float, Knob(
        label="Une réponse tardive compte pour", group="Les heures où elle répond", lo=0.0, hi=1.0, step=0.05,
        help="Une réponse arrivée après le délai attendu rattrape d'autant l'initiative restée sans réponse.")] = 0.5
    # ce qui la rassure, ce qui l'inquiète aussi
    relief_min_words: Annotated[int, Knob(
        label="Rassurée : un message d'au moins (mots)", group="Surprise et inquiétude", lo=1, hi=20,
        help="Un « ok » ne la rassure pas : un message plus léger d'au moins tant de mots, revenu à peu près à son "
             "ton habituel, éteint l'inquiétude (un message franchement joyeux aussi, quelle que soit sa "
             "longueur).")] = 3
    relief_margin: Annotated[float, Knob(
        label="Rassurée : ton habituel, à tant près", group="Surprise et inquiétude", lo=0.0, hi=1.0, step=0.05,
        help="Le message qui rassure est au plus aussi en dessous de son ton habituel.")] = 0.3
    relief_valence: Annotated[float, Knob(
        label="Rassurée : un message franchement léger dès", group="Surprise et inquiétude", lo=0.0, hi=1.0,
        step=0.05, help="Un message au moins aussi léger rassure, même court.")] = 0.3
    declared_concern_from: Annotated[float, Knob(
        label="S'inquiéter de sa propre réponse dès", group="Surprise et inquiétude", lo=0.1, hi=1.0, step=0.05,
        help="Quand elle répond à une amie triste, anxieuse ou effrayée au moins à ce point (sa balise d'émotion), "
             "c'est que le message l'a inquiétée — même si les mots ne le disaient pas : elle prendra de ses "
             "nouvelles. Pas chez quelqu'un dont c'est le ton habituel.")] = 0.6
    # la contagion : son ton du moment la colore un peu, selon leur proximité
    contagion_gain: Annotated[float, Knob(
        label="Contagion : force", group="Contagion", lo=0.0, hi=0.5, step=0.01,
        help="Le ton du moment de quelqu'un la colore d'autant (× l'intensité du ton × la proximité : rien d'une "
             "inconnue, la moitié d'une connaissance, tout d'une proche). Elle s'allège avec quelqu'un de joyeux, "
             "se tend avec quelqu'un de stressé.")] = 0.12
    contagion_from: Annotated[float, Knob(
        label="Contagion : un ton d'au moins", group="Contagion", lo=0.0, hi=1.0, step=0.05,
        help="Un message plus neutre que ça ne la colore pas.")] = 0.25
    contagion_cap: Annotated[float, Knob(
        label="Contagion : au plus, par fenêtre", group="Contagion", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité cumulée qu'une même personne peut lui transmettre dans la fenêtre ci-dessous : une "
             "conversation agitée la colore, elle ne la submerge pas.")] = 0.3
    contagion_window_us: Annotated[int, Knob(
        label="Contagion : fenêtre", group="Contagion", lo=MINUTE, hi=DAY,
        help="La fenêtre du plafond ci-dessus.")] = 10 * MINUTE


def derive(t: Temperament, overrides: Any = None) -> OthersParams:
    """La réactivité règle la force de la surprise (au milieu : 0,5)."""
    values: dict[str, Any] = {"surprise_gain": round(lerp(0.3, 0.7, t.reactivity), 3)}
    values.update(dict(overrides or {}))
    return OthersParams(**values)


@dataclass(frozen=True, slots=True)
class Model:
    """Ce qu'elle devine du ton d'une personne."""

    observed: int = 0
    usual_valence: float = 0.0
    usual_arousal: float = 0.3
    recent_valence: float = 0.0  # à ``last_at``
    recent_arousal: float = 0.3
    last_at: int = 0
    last_message: int = 0
    last_cues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OthersState:
    people: FrozenDict[str, Model] = field(default_factory=FrozenDict)
    #: les initiatives en cours (corrélation → raisons) : une salutation n'attend pas de réponse
    openings: FrozenDict[str, str] = field(default_factory=FrozenDict)
    #: personne → (instant de son initiative, classe de canal) : elle attend sa réponse
    awaiting: FrozenDict[str, tuple[int, str]] = field(default_factory=FrozenDict)
    #: « personne|classe » → derniers délais de réponse (µs)
    delays: FrozenDict[str, tuple[int, ...]] = field(default_factory=FrozenDict)
    #: « personne|moment » → (comblées, sans réponse)
    answers: FrozenDict[str, tuple[float, float]] = field(default_factory=FrozenDict)
    #: les attentes déçues (« personne:depuis ») : une réponse tardive les rattrape
    missed: tuple[str, ...] = ()
    #: personne → (message qui l'a inquiétée, quand, à partir de quand prendre de ses nouvelles)
    concerns: FrozenDict[str, tuple[int, int, int]] = field(default_factory=FrozenDict)
    #: personne → (début de la fenêtre, contagion déjà reçue dans la fenêtre)
    contagion: FrozenDict[str, tuple[int, float]] = field(default_factory=FrozenDict)
    #: personne → les (jour local, heure locale) où elle a écrit, distincts, les plus récents
    hours: FrozenDict[str, tuple[tuple[int, int], ...]] = field(default_factory=FrozenDict)
    #: les initiatives en cours qui portent sur un moment de la vie de quelqu'un (corrélation → moment)
    moments: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: moment → quand elle en a parlé d'elle-même (encourager, demander comment ça s'est passé) : une fois chacun
    spoke: FrozenDict[int, int] = field(default_factory=FrozenDict)


#: v2 : ce qui rassure se juge à la lecture ; sa propre réponse peut l'inquiéter ; la contagion.
#: v3 : les heures où chacun écrit ; encourager la veille, demander après — une fois chacun.
OTHERS = Faculty("others", state=OthersState, init=lambda p: OthersState(), params=OthersParams, derive=derive,
                 state_version=3)
OTHERS.declare(*c.ALL)


def params(p: OthersParams | None) -> OthersParams:
    return p if p is not None else OthersParams()


def channel_class(channel: str) -> str:
    """Par messagerie, on lit quand on y pense ; à l'écran, on répond en minutes."""
    return c.MESSAGE if privacy.is_messaging(channel) else c.SCREEN


def band_of(hour: int) -> str:
    """Le moment de la journée d'une heure locale."""
    if hour < 6:
        return c.NIGHT
    if hour < 12:
        return c.MORNING
    if hour < 18:
        return c.AFTERNOON
    return c.EVENING


def current(m: Model, now: int, p: OthersParams) -> tuple[float, float]:
    """L'état du moment qu'elle lui prête : les derniers messages, effacés vers
    l'habituel avec le temps."""
    if not m.observed:
        return m.usual_valence, m.usual_arousal
    fade = 0.5 ** (max(0, now - m.last_at) / p.recent_half_life_us)
    return (m.usual_valence + (m.recent_valence - m.usual_valence) * fade,
            m.usual_arousal + (m.recent_arousal - m.usual_arousal) * fade)


def confidence(m: Model, p: OthersParams, closeness: str = social_c.ACQUAINTANCE) -> float:
    """Ce qu'elle la connaît : assez de messages lus, et un lien. Une inconnue,
    même bavarde, ne lui a encore rien appris de ce qui lui ressemble."""
    if closeness == social_c.STRANGER:
        return 0.0
    return min(1.0, m.observed / p.confident_after)


def learn(m: Model, valence: float, arousal: float, message: int, cues: tuple[str, ...], at: int,
          p: OthersParams) -> Model:
    """Un message de plus : l'habituel bouge un peu (moyenne qui part d'une
    neutralité supposée), l'état du moment beaucoup."""
    now_v, now_a = current(m, at, p)
    weight = max(p.usual_weight, 1.0 / (m.observed + 1 + p.usual_prior))
    return Model(
        observed=m.observed + 1,
        usual_valence=round(m.usual_valence + weight * (valence - m.usual_valence), 5),
        usual_arousal=round(m.usual_arousal + weight * (arousal - m.usual_arousal), 5),
        recent_valence=round(now_v + p.recent_weight * (valence - now_v), 5),
        recent_arousal=round(now_a + p.recent_weight * (arousal - now_a), 5),
        last_at=at, last_message=message, last_cues=cues,
    )


def model_of(s: OthersState, person: str, handles: Any) -> Model | None:
    """Ce qu'elle devine de son ton, appris sous toutes les adresses de la personne (``identity.HANDLES``) : une
    adresse reliée depuis à elle n'emporte pas ce qu'elle en avait appris. L'habituel se réunit au poids des messages
    lus ; l'état du moment est celui du dernier message, par quelque adresse qu'il soit arrivé."""
    parts = [s.people[k] for k in sorted({person, *handles}) if k in s.people]
    if len(parts) <= 1:
        return parts[0] if parts else None
    observed = sum(m.observed for m in parts)
    latest = max(parts, key=lambda m: (m.last_at, m.last_message))
    if not observed:
        return latest
    return replace(latest, observed=observed,
                   usual_valence=round(sum(m.usual_valence * m.observed for m in parts) / observed, 5),
                   usual_arousal=round(sum(m.usual_arousal * m.observed for m in parts) / observed, 5))


def reading(s: OthersState, person: str, now: int, p: OthersParams,
            closeness: str = social_c.ACQUAINTANCE) -> c.MindReading:
    m = s.people.get(person) or Model()
    v, a = current(m, now, p)
    return c.MindReading(person, m.observed, round(m.usual_valence, 3), round(m.usual_arousal, 3), round(v, 3),
                         round(a, 3), round(v - m.usual_valence, 3), round(confidence(m, p, closeness), 3),
                         m.last_at, m.last_message, m.last_cues)


def _logit(x: float) -> float:
    x = min(1 - 1e-6, max(1e-6, x))
    return math.log(x / (1 - x))


def receptivity(s: OthersState, person: str, band: str, p: OthersParams) -> tuple[float, float, float, float]:
    """(comblées, sans réponse, probabilité estimée, décalage en log-odds) pour
    une initiative vers cette personne à ce moment de la journée."""
    answered, missed = s.answers.get(f"{person}|{band}", (0.0, 0.0))
    a0, m0 = p.receptivity_prior_answered, p.receptivity_prior_missed
    estimate = (answered + a0) / (answered + missed + a0 + m0)
    if answered + missed < p.receptivity_min_observations:
        return answered, missed, estimate, 0.0
    shift = _logit(estimate) - _logit(a0 / (a0 + m0))
    bound = p.receptivity_max_shift
    return answered, missed, estimate, round(max(-bound, min(bound, shift)), 4)


# ── Lire un message à son arrivée ─────────────────────────────────────────


@OTHERS.interpret(rt.PERCEPTION_RECEIVED)
def _read(s: OthersState, frame: Frame, ev: Any, ports: Any) -> list[Draft[Any]]:
    """Ce qu'elle lit dans la forme d'un message, et ce qu'elle en attendait —
    journalisé avant la réponse : sa réponse voit déjà la surprise. Ce qui la
    rassure tient compte de ce qu'elle sait de grave dans sa vie
    (``memory.hard_times``)."""
    d = ev.data
    text = d.text.text or ""
    if not d.addressed or not is_identifiable(d.handle) or not text.strip():
        return []
    p = params(frame.env.params_of("others", frame.root))
    person = frame.get(identity_c.PERSON(d.handle))
    tone = measure(text)
    m = s.people.get(person) or Model()
    expected, _ = current(m, ev.at, p)
    level = frame.get(social_c.CLOSENESS(person))
    known = confidence(m, p, level)
    close = level in (social_c.FRIEND, social_c.CLOSE)
    # un événement grave inquiète venant d'une amie, quel que soit son ton habituel ; un message lourd, seulement
    # s'il tranche avec ce qu'elle attendait d'elle
    concern = close and (tone.grave or (known >= p.concern_confidence and tone.valence <= p.concern_below
                                        and expected - tone.valence >= p.concern_drop))
    contagion, emotion = _contagion(s, person, tone, level, ev.at, p)
    hard = is_identifiable(person) and frame.get(memory_c.HARD_TIMES(person)) > 0
    return [c.READ.draft(person=person, handle=d.handle, message=ev.seq, valence=tone.valence, arousal=tone.arousal,
                         cues=tone.cues, expected=round(expected, 3), confidence=round(known, 3),
                         surprise=round(abs(tone.valence - expected) * known, 3), concern=concern,
                         public=bool(d.public or d.room), grave=tone.grave,
                         relief=reassuring(m, tone.valence, text, p, hard=hard), contagion=contagion,
                         contagion_emotion=emotion, closing=closing(text) and not d.room)]


def reassuring(m: Model, valence: float, text: str, p: OthersParams, *, hard: bool = False) -> bool:
    """Ce message la rassure-t-il sur une inquiétude ? Pas un « ok » : un message
    plus léger, assez long, revenu à peu près à son ton habituel — ou franchement
    léger, quelle que soit sa longueur. Quand quelque chose de grave la touche ces
    jours-ci (un deuil), ou pour un « bonne nuit », seulement franchement léger :
    « je vais essayer de dormir », le soir où son chat est mort, ne rassure de rien
    (sonde réelle du 2026-10-03 : le lendemain, pas de nouvelles prises)."""
    if valence <= p.concern_below:
        return False
    if valence >= p.relief_valence:
        return True
    if hard or closing(text):
        return False
    return len(text.split()) >= p.relief_min_words and valence >= m.usual_valence - p.relief_margin


#: L'intensité de la contagion selon leur proximité : rien d'une inconnue, tout d'une proche.
CONTAGION_BY_CLOSENESS = {social_c.STRANGER: 0.0, social_c.ACQUAINTANCE: 0.5, social_c.FRIEND: 0.8,
                          social_c.CLOSE: 1.0}


def _contagion(s: OthersState, person: str, tone: Any, level: str, at: int, p: OthersParams) -> tuple[float, str]:
    """Ce que son ton du moment lui transmet : une émotion (joie, tension, peine)
    et une petite intensité, proportionnée à leur proximité, plafonnée par fenêtre."""
    if abs(tone.valence) < p.contagion_from:
        return 0.0, ""
    raw = p.contagion_gain * abs(tone.valence) * CONTAGION_BY_CLOSENESS.get(level, 0.0)
    start, used = s.contagion.get(person, (at, 0.0))
    if at - start >= p.contagion_window_us:
        used = 0.0
    intensity = round(max(0.0, min(raw, p.contagion_cap - used)), 3)
    if intensity < 0.01:
        return 0.0, ""
    if tone.valence > 0:
        return intensity, Emotion.HAPPY.value
    return intensity, (Emotion.ANXIOUS if tone.arousal >= 0.5 else Emotion.SAD).value


# ── Réducteurs ────────────────────────────────────────────────────────────


@OTHERS.reducer(c.READ)
def _learned(s: OthersState, e, cx) -> OthersState:
    d = e.data
    p = params(cx.params)
    m = learn(s.people.get(d.person) or Model(), d.valence, d.arousal, d.message, tuple(d.cues), e.at, p)
    s = replace(s, people=s.people.set(d.person, m))
    moment = cx.local(e.at)
    seen = (moment.date().toordinal(), moment.hour)
    pairs = s.hours.get(d.person, ())
    if seen not in pairs:  # une heure d'un jour compte une fois, quel que soit le nombre de messages
        s = replace(s, hours=s.hours.set(d.person, (*pairs, seen)[-HOURS_KEPT:]))
    if d.contagion > 0:
        start, used = s.contagion.get(d.person, (e.at, 0.0))
        if e.at - start >= p.contagion_window_us:
            start, used = e.at, 0.0
        s = replace(s, contagion=s.contagion.set(d.person, (start, round(used + d.contagion, 4))))
    if d.concern:
        opens = e.at + round(p.checkin_after_us * (1.0 + p.checkin_jitter * cx.rng.random()))
        return replace(s, concerns=s.concerns.set(d.person, (d.message, e.at, opens)))
    # elle va mieux : plus d'inquiétude — un vrai message plus léger, pas un « ok » (lecture d'avant ce
    # jugement : n'importe quel message pas lourd)
    relieved = d.relief if d.relief is not None else d.valence > p.concern_below
    if d.person in s.concerns and relieved:
        return replace(s, concerns=s.concerns.delete(d.person))
    return s


@OTHERS.reducer(rt.EPISODE_STARTED)
def _reaching_out(s: OthersState, e, cx) -> OthersState:
    d = e.data
    if d.kind != Kind.INITIATIVE or not d.target:
        return s
    openings = s.openings.set(e.correlation, d.reason)
    if len(openings) > OPENINGS_KEPT:  # les identifiants d'épisode sont chronologiques
        openings = FrozenDict(sorted(openings.items())[-OPENINGS_KEPT:])
    s = replace(s, openings=openings)
    moment = moment_of(d.subject)
    if moment is None:
        return s
    moments = s.moments.set(e.correlation, moment)
    if len(moments) > OPENINGS_KEPT:
        moments = FrozenDict(sorted(moments.items())[-OPENINGS_KEPT:])
    return replace(s, moments=moments)


#: Ce qu'elle déclare en répondant et qui dit qu'elle s'inquiète pour la personne.
WORRIED = frozenset({Emotion.SAD, Emotion.ANXIOUS, Emotion.SCARED})


def _worried_reply(s: OthersState, e: Any, cx: Any) -> OthersState:
    """Elle répond à une amie avec de la tristesse, de l'anxiété ou de la peur :
    le message l'a inquiétée, même si les mots ne le disaient pas (« ma mère est
    partie ce matin »). Pas chez quelqu'un dont c'est le ton habituel, ni une
    inquiétude déjà là."""
    d = e.data
    declared = Declared.decode(d.annotation(expression_c.EMOTION_ANNOTATION))
    p = params(cx.params)
    if declared is None or declared.emotion not in WORRIED or declared.intensity < p.declared_concern_from:
        return s
    person = cx.facts.get(identity_c.PERSON(d.target))
    if person in s.concerns or cx.facts.get(social_c.CLOSENESS(person)) not in (social_c.FRIEND, social_c.CLOSE):
        return s
    m = s.people.get(person)
    if m is not None and m.usual_valence <= p.concern_below:
        return s  # elle râle toujours : sa propre peine pour elle ne dit rien de neuf
    opens = e.at + round(p.checkin_after_us * (1.0 + p.checkin_jitter * cx.rng.random()))
    return replace(s, concerns=s.concerns.set(person, (d.reply_to or e.seq, e.at, opens)))


#: Ce qui, dans une initiative vers elle, est déjà prendre de ses nouvelles : la prise de nouvelles,
#: ou la pensée qui pèse entre elles (« tu repenses à votre dernier échange… prendre de ses nouvelles »)
#: — deux chemins vers le même geste ; le premier qui part éteint l'inquiétude, l'autre n'en refait pas un second.
REACHED = frozenset({c.CHECK_IN, attention_c.THOUGHT})


@OTHERS.reducer(rt.UTTERANCE, reads=[identity_c.PERSON, social_c.CLOSENESS])
def _wrote(s: OthersState, e, cx) -> OthersState:
    """Elle écrit d'elle-même à quelqu'un : on mesurera le temps qu'il met à
    répondre (pas à une salutation ni à un rappel : ce n'était pas une
    question). Elle lui répond, inquiète : elle prendra de ses nouvelles."""
    d = e.data
    if d.kind == Kind.REPLY and d.visible and d.target and is_identifiable(d.target) and d.room is None:
        return _worried_reply(s, e, cx)
    moment = s.moments.get(e.correlation)
    if moment is not None:
        s = replace(s, moments=s.moments.delete(e.correlation))
        if d.visible:  # elle l'a dit (encourager, demander comment ça s'est passé) : une fois
            spoke = s.spoke.set(moment, e.at)
            if len(spoke) > SPOKE_KEPT:  # les identifiants de moment sont chronologiques
                spoke = FrozenDict(sorted(spoke.items())[-SPOKE_KEPT:])
            s = replace(s, spoke=spoke)
    if d.kind != Kind.INITIATIVE or not d.visible or not d.target or not is_identifiable(d.target):
        return s
    reasons = s.openings.get(e.correlation, "").split(",")
    s = replace(s, openings=s.openings.delete(e.correlation))
    person = cx.facts.get(identity_c.PERSON(d.target))
    if REACHED & set(reasons):
        s = replace(s, concerns=s.concerns.delete(person))  # c'est fait : elle a pris de ses nouvelles
    if (agency_c.NOT_SPEAKING_UP | c.WELL_WISHES) & set(reasons):
        return s  # rien n'est attendu en retour : pas un délai de réponse à mesurer
    return replace(s, awaiting=s.awaiting.set(person, (e.at, channel_class(d.channel))))


@OTHERS.reducer(rt.PERCEPTION_RECEIVED, reads=[identity_c.PERSON])
def _answered(s: OthersState, e, cx) -> OthersState:
    d = e.data
    if not d.addressed or not is_identifiable(d.handle):
        return s
    person = cx.facts.get(identity_c.PERSON(d.handle))
    pending = s.awaiting.get(person)
    if pending is None:
        return s
    since, klass = pending
    s = replace(s, awaiting=s.awaiting.delete(person))
    delay = e.at - since
    p = params(cx.params)
    if delay < 0 or delay > p.delay_max_us:
        return s
    key = f"{person}|{klass}"
    samples = (*s.delays.get(key, ()), delay)[-p.delay_samples:]
    return replace(s, delays=s.delays.set(key, samples))


@OTHERS.reducer(attention_c.EXPECTATION_MET, attention_c.EXPECTATION_MISSED)
def _outcome(s: OthersState, e, cx) -> OthersState:
    """Une initiative comblée ou restée sans réponse, rangée au moment de la
    journée où elle l'a écrite. Une réponse tardive rattrape en partie."""
    d = e.data
    if d.kind != attention_c.REPLY:
        return s
    p = params(cx.params)
    band = band_of(cx.local(d.since).hour)
    key = f"{d.person}|{band}"
    answered, missed = s.answers.get(key, (0.0, 0.0))
    mark = f"{d.person}:{d.since}"
    if e.type.name == attention_c.EXPECTATION_MISSED.name:
        return replace(s, answers=s.answers.set(key, (answered, missed + 1.0)),
                       missed=(*s.missed, mark)[-MISSED_KEPT:])
    if mark in s.missed:  # tardive : la moitié du chemin
        w = p.receptivity_late_weight
        return replace(s, answers=s.answers.set(key, (answered + w, max(0.0, missed - w))),
                       missed=tuple(x for x in s.missed if x != mark))
    return replace(s, answers=s.answers.set(key, (answered + 1.0, missed)))


# ── Faits ─────────────────────────────────────────────────────────────────


@OTHERS.fact(c.MIND, reads=[social_c.CLOSENESS, identity_c.HANDLES])
def _mind(s: OthersState, cx, person: str) -> c.MindReading:
    m = model_of(s, person, cx.facts.get(identity_c.HANDLES(person)))  # une adresse reliée apporte ce qu'elle a appris
    if m is not None and m is not s.people.get(person):
        s = replace(s, people=s.people.set(person, m))
    return reading(s, person, cx.now, params(cx.params), cx.facts.get(social_c.CLOSENESS(person)))


@OTHERS.fact(c.REPLY_DELAY)
def _reply_delay(s: OthersState, cx, arg: tuple[str, str]) -> c.DelayReading:
    person, channel = arg
    samples = s.delays.get(f"{person}|{channel_class(channel)}", ())
    return c.DelayReading(len(samples), int(statistics.median(samples)) if samples else 0)


def hours_reading(pairs: tuple[tuple[int, int], ...], p: OthersParams) -> c.HoursReading:
    """Les heures où elle écrit : une heure est « à elle » quand elle a écrit à cette heure-là, ou juste à côté,
    un jour au moins ; son heure habituelle, celle où elle a écrit le plus de jours. Tant que trop peu de jours
    sont vus, une nuit ordinaire (supposée) — jamais rien d'appris sur trois messages."""
    days = len({day for day, _h in pairs})
    if days < p.hours_min_days:
        night = tuple(within_daily_window(h * 60 + 30, p.assumed_night_start_min, p.assumed_night_end_min)
                      for h in range(24))
        return c.HoursReading(days, tuple(not n for n in night), False, None)
    counts = [0] * 24
    for _day, h in set(pairs):
        counts[h % 24] += 1
    active = tuple(counts[(h - 1) % 24] + counts[h] + counts[(h + 1) % 24] > 0 for h in range(24))
    usual = max(range(24), key=lambda h: (counts[h], -h))
    return c.HoursReading(days, active, True, usual)


@OTHERS.fact(c.HOURS)
def _hours(s: OthersState, cx, person: str) -> c.HoursReading:
    return hours_reading(s.hours.get(person, ()), params(cx.params))


# ── Ce que ses lectures lui font ressentir ────────────────────────────────


@OTHERS.appraisal(c.READ)
def _read_felt(e, cx) -> list[Appraisal]:
    d = e.data
    p = params(cx.params)
    out: list[Appraisal] = []
    if d.surprise >= p.surprise_from:
        out.append(Appraisal(Emotion.SURPRISED, min(p.surprise_max, d.surprise * p.surprise_gain),
                             reason="surprise"))
    if d.concern:
        # s'inquiéter pour quelqu'un suit la contagion du tempérament
        out.append(Appraisal(Emotion.ANXIOUS, p.worry_intensity, reason="inquiétude", relational=True))
    emotion = emotion_of(d.contagion_emotion) if d.contagion > 0 else None
    if emotion is not None:
        # son ton du moment la colore un peu : un nombre et une émotion, jamais un mot du message
        out.append(Appraisal(emotion, d.contagion, reason="contagion", relational=True))
    return out


# ── Ses initiatives, selon ce que l'expérience lui a appris ───────────────


@OTHERS.modulate(kinds=[Kind.INITIATIVE], reads=[identity_c.PERSON])
def _receptive(s: OthersState, frame: Frame, row: RowView) -> Modulation:
    """Écrire à quelqu'un à une heure où il répond d'habitude, plutôt qu'à une
    heure où ses messages restent sans réponse. Ni une salutation (quelqu'un
    arrive), ni un rappel promis n'en dépendent (``agency.NOT_SPEAKING_UP``)."""
    if row.target in ("any", "none") or not is_identifiable(row.target):
        return Modulation()
    if agency_c.NOT_SPEAKING_UP & set(row.reasons):
        return Modulation()
    p = params(frame.env.params_of("others", frame.root))
    person = frame.get(identity_c.PERSON(row.target))
    shift = receptivity(s, person, band_of(frame.local().hour), p)[3]
    return Modulation(shift=shift) if shift else Modulation()


def _address(frame: Frame, person: str) -> str | None:
    """Où lui écrire : une adresse présente d'abord, sinon une conversation
    privée où l'on peut lui écrire d'elle-même."""
    handles = frame.get(identity_c.HANDLES(person))
    present = [h for h in frame.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    reachable = frame.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else None


@OTHERS.propose(kinds=[Kind.INITIATIVE], reasons={c.CHECK_IN: (0.0, 12.0)},
                reads=[identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY, presence_c.PRESENT,
                       social_c.CLOSENESS, transcript_c.LAST_FROM])
def _check_in(s: OthersState, frame: Frame) -> list[Candidate]:
    """Une amie qui n'avait pas l'air bien, et plus rien depuis : quelques
    heures plus tard, elle prend de ses nouvelles."""
    if not s.concerns:
        return []
    p = params(frame.env.params_of("others", frame.root))
    local = frame.local()
    if not within_daily_window(local.hour * 60 + local.minute, p.checkin_day_start_min, p.checkin_day_end_min):
        return []
    out: list[Candidate] = []
    for person, (_message, at, opens) in sorted(s.concerns.items()):
        if frame.now < opens or frame.now - at > p.checkin_until_us:
            continue
        if frame.get(social_c.CLOSENESS(person)) not in (social_c.FRIEND, social_c.CLOSE):
            continue
        address = _address(frame, person)
        if address is None:
            continue
        name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(address)).name
        who = f"« {name} »" if name else "cette personne"
        brief = (f"{who[0].upper()}{who[1:]} n'avait pas l'air bien la dernière fois que vous vous êtes parlé, et "
                 "tu n'as pas eu de nouvelles depuis. Tu as envie de savoir comment ça va : un mot simple et doux, "
                 "sans insister ni jouer les psys.")
        handles = frame.get(identity_c.HANDLES(person)) or (person,)
        guard = Guard("pas de nouvelles", reads=tuple(transcript_c.LAST_FROM(h) for h in handles))
        ramp = min(1.0, (frame.now - opens) / p.checkin_ramp_us)
        evidence = p.checkin_evidence_start + (p.checkin_evidence - p.checkin_evidence_start) * ramp
        out.append(Candidate(Kind.INITIATIVE, address, c.CHECK_IN, round(evidence, 3),
                             resources=frozenset({floor(address)}), guards=(guard,),
                             args=FrozenDict({"brief:others": brief})))
    return out


def _last_from(frame: Frame, person: str) -> int:
    handles = frame.get(identity_c.HANDLES(person)) or (person,)
    return max(frame.get(transcript_c.LAST_FROM(h)) for h in handles)


def _at(day: date, minutes: int, tz: Any) -> int:
    return instant(datetime.combine(day, time(minutes // 60 % 24, minutes % 60), tzinfo=tz))


#: une conversation depuis midi, la veille, était l'occasion de l'encourager
CHEER_QUIET_FROM_MIN = 12 * 60


def _cheer_window(ev: memory_c.LifeEvent, frame: Frame, p: OthersParams) -> tuple[int, int] | None:
    """Quand lui souhaiter bonne chance : (début, depuis quand une conversation en tenait lieu). La veille au
    soir ; ou le matin même, pour un moment à une heure dite l'après-midi (jusqu'à deux heures avant). Si elles
    se sont parlé depuis midi la veille, la conversation en était l'occasion. ``None`` : pas pour un moment déjà
    là, ni pour une situation, ni pour ce qui se fête (un anniversaire ne se souhaite pas « bonne chance » : il se
    souhaite le jour même)."""
    if ev.ongoing or ev.festive or ev.when <= frame.now:
        return None
    tz = frame.env.tz_of(frame.root)
    day = frame.local(ev.when).date()
    eve = date.fromordinal(day.toordinal() - 1)
    quiet = _at(eve, CHEER_QUIET_FROM_MIN, tz)
    start, end = _at(eve, p.cheer_eve_start_min, tz), _at(eve, p.checkin_day_end_min, tz)
    if start <= frame.now <= end:
        return start, quiet
    if not ev.all_day and frame.local(ev.when).hour >= 12:
        morning = _at(day, p.checkin_day_start_min, tz)
        if morning <= frame.now <= ev.when - 2 * HOUR:
            return morning, quiet
    return None


def _hard(frame: Frame, person: str) -> bool:
    """Quelque chose de grave la touche ces jours-ci (un deuil, une rupture) : le banal se tait."""
    return frame.get(memory_c.HARD_TIMES(person)) > 0


def _minor(ev: memory_c.LifeEvent) -> bool:
    """Un moment ordinaire (un rendez-vous de routine, une sortie) : ni important, ni à fêter."""
    return not ev.festive and ev.importance < memory_c.IMPORTANT_MOMENT


@OTHERS.propose(kinds=[Kind.INITIATIVE], reasons={c.CHEER: (0.0, 12.0)},
                reads=[identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY, presence_c.PRESENT,
                       social_c.CIRCLE, social_c.CLOSENESS, transcript_c.LAST_FROM, memory_c.LIFE_EVENTS,
                       memory_c.HARD_TIMES])
def _cheer(s: OthersState, frame: Frame) -> list[Candidate]:
    """Une amie lui avait dit ce qui l'attendait (« demain, mon entretien chez Ubisoft ») : la veille au soir, un
    mot pour l'encourager — si elles ne se sont pas déjà parlé depuis midi (la conversation en était
    l'occasion), une fois. Plus faible que demander comment ça s'est passé : elle le fait si elle y pense.
    Seulement ce que la personne lui a dit elle-même ; rien d'ordinaire quand quelque chose de grave la touche
    ces jours-ci (pas de « bonne chance chez le dentiste » le lendemain d'un deuil). Seules ses amies sont
    passées en revue (``social.CIRCLE``, un tri bon marché) : les inconnues de passage ne coûtent rien ici."""
    p = params(frame.env.params_of("others", frame.root))
    out: list[Candidate] = []
    circle = set(frame.get(social_c.CIRCLE))
    for person in sorted(circle.intersection(s.people.keys())):
        if frame.get(social_c.CLOSENESS(person)) not in (social_c.FRIEND, social_c.CLOSE):
            continue
        last = _last_from(frame, person)
        hard = _hard(frame, person)
        due = [(ev, w) for ev in frame.get(memory_c.LIFE_EVENTS(person))
               if ev.id not in s.spoke and set(ev.told_by) <= {person} and not (hard and _minor(ev))
               and (w := _cheer_window(ev, frame, p)) is not None and last < w[1]]
        address = _address(frame, person) if due else None
        if address is None:
            continue
        ev, (start, _end) = due[0]  # le plus proche
        name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(address)).name
        who = f"« {name} »" if name else "cette personne"
        soon = "demain" if frame.local(ev.when).date() > frame.local().date() else "tout à l'heure"
        brief = (f"{who[0].upper()}{who[1:]} a quelque chose d'important {soon} (tu le vois dans « CE QUI SE PASSE "
                 "DANS SA VIE ») : si tu y penses, un petit mot pour l'encourager — simple, sans en faire une "
                 "affaire.")
        handles = frame.get(identity_c.HANDLES(person)) or (person,)
        guard = Guard("pas de nouvelles", reads=tuple(transcript_c.LAST_FROM(h) for h in handles))
        ramp = min(1.0, (frame.now - start) / p.checkin_ramp_us)
        evidence = p.checkin_evidence_start + (p.cheer_evidence - p.checkin_evidence_start) * ramp
        out.append(Candidate(Kind.INITIATIVE, address, c.CHEER, round(evidence, 3),
                             resources=frozenset({floor(address)}), guards=(guard,),
                             args=FrozenDict({"brief:others": brief, "subject": f"{MOMENT_SUBJECT}{ev.id}"})))
    return out


def _day_start(t: int, frame: Frame) -> int:
    return _at(frame.local(t).date(), 0, frame.env.tz_of(frame.root))


def _follow_from(ev: memory_c.LifeEvent, frame: Frame, p: OthersParams) -> int:
    """À partir de quand demander comment ça s'est passé : quelques heures après ; un moment qui se fête, pas
    avant le lendemain (le jour même, ce sont ses vœux)."""
    if ev.festive:
        return max(ev.when, _day_start(ev.when, frame) + DAY + HOUR)  # le lendemain (une heure de marge : l'heure d'été)
    return ev.when + p.followup_after_us


@OTHERS.propose(kinds=[Kind.INITIATIVE], reasons={c.FOLLOW_UP: (0.0, 12.0)},
                reads=[identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY, presence_c.PRESENT,
                       social_c.CIRCLE, social_c.CLOSENESS, transcript_c.LAST_FROM, memory_c.LIFE_EVENTS,
                       memory_c.HARD_TIMES])
def _follow_up(s: OthersState, frame: Frame) -> list[Candidate]:
    """Une amie lui avait dit ce qui l'attendait (un entretien jeudi à 14 h) : quelques heures après, si elles
    n'en ont pas reparlé, elle a envie de savoir comment ça s'est passé — « alors, cet entretien ? ». Seulement
    ce que la personne lui a dit elle-même (ce qu'un tiers a raconté d'elle, le lui demander trahirait le tiers),
    une fois par moment. Si la personne lui a écrit depuis, c'était l'occasion : la conversation (« CE QUI SE
    PASSE DANS SA VIE ») s'en charge, pas une initiative de plus.

    Gradué (ADR 0052) : ce qui compte (un entretien, un examen) avec insistance ; un moment ordinaire, si elle y
    pense ; quand quelque chose de grave la touche ces jours-ci, l'ordinaire se tait et ce qui compte passe
    après des nouvelles d'elle. Ce qui se fête : pas de « comment ça s'est passé » si elle l'a souhaité le jour
    même — sinon, le lendemain, un mot même en retard."""
    p = params(frame.env.params_of("others", frame.root))
    local = frame.local()
    if not within_daily_window(local.hour * 60 + local.minute, p.checkin_day_start_min, p.checkin_day_end_min):
        return []
    out: list[Candidate] = []
    for person in sorted(set(frame.get(social_c.CIRCLE)).intersection(s.people.keys())):  # ses amies (ADR 0058)
        if frame.get(social_c.CLOSENESS(person)) not in (social_c.FRIEND, social_c.CLOSE):
            continue
        last = _last_from(frame, person)
        hard = _hard(frame, person)
        due = [ev for ev in frame.get(memory_c.LIFE_EVENTS(person))
               if not ev.ongoing and not ev.followed_at and set(ev.told_by) <= {person}
               and not (hard and _minor(ev))
               and s.spoke.get(ev.id, 0) < (_day_start(ev.when, frame) if ev.festive else ev.when)
               and last <= ev.when and _follow_from(ev, frame, p) <= frame.now <= ev.when + p.followup_until_us]
        address = _address(frame, person) if due else None
        if address is None:
            continue
        ev = due[-1]  # le plus récent
        name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(address)).name
        who = f"« {name} »" if name else "cette personne"
        if ev.festive:
            brief = (f"C'était un jour qui se fêtait pour {who} (tu le vois dans « CE QUI SE PASSE DANS SA VIE ») et "
                     "tu ne le lui as pas souhaité : si tu y penses, un mot, même en retard — simple, sans en faire "
                     "une affaire.")
        else:
            brief = (f"{who[0].upper()}{who[1:]} t'avait parlé de quelque chose de prévu (tu le vois dans « CE QUI "
                     "SE PASSE DANS SA VIE ») : c'est passé, et tu as envie de savoir comment ça s'est passé. Un mot "
                     "simple et spontané, comme on demande des nouvelles à quelqu'un qu'on aime bien — sans en faire "
                     "une affaire.")
            if hard:
                brief += " Mais ces jours-ci sont durs pour cette personne : d'abord, comment ça va."
        handles = frame.get(identity_c.HANDLES(person)) or (person,)
        guard = Guard("pas de nouvelles", reads=tuple(transcript_c.LAST_FROM(h) for h in handles))
        full = p.followup_minor_evidence if (_minor(ev) or ev.festive or hard) else p.followup_evidence
        ramp = min(1.0, (frame.now - _follow_from(ev, frame, p)) / p.checkin_ramp_us)
        evidence = min(full, p.checkin_evidence_start) + (full - min(full, p.checkin_evidence_start)) * ramp
        out.append(Candidate(Kind.INITIATIVE, address, c.FOLLOW_UP, round(evidence, 3),
                             resources=frozenset({floor(address)}), guards=(guard,),
                             args=FrozenDict({"brief:others": brief, "subject": f"{MOMENT_SUBJECT}{ev.id}"})))
    return out


@OTHERS.propose(kinds=[Kind.INITIATIVE], reasons={c.CELEBRATE: (0.0, 12.0)},
                reads=[identity_c.HANDLES, identity_c.REACHABLE, identity_c.IDENTITY, presence_c.PRESENT,
                       social_c.CIRCLE, social_c.CLOSENESS, transcript_c.LAST_FROM, memory_c.LIFE_EVENTS,
                       memory_c.HARD_TIMES])
def _celebrate(s: OthersState, frame: Frame) -> list[Candidate]:
    """Le jour d'un anniversaire, d'un mariage qu'une amie lui avait annoncé : elle le lui souhaite, d'elle-même,
    une fois, dans ses heures pour prendre des nouvelles — plus fort qu'une question (sonde réelle du 2026-10-03 :
    le samedi des 30 ans de Sam, son initiative de 11 h était un « prendre des nouvelles », le « joyeux
    anniversaire » n'est venu qu'à la réponse suivante). Qu'elle l'ait souhaité en répondant (ses mots reprennent
    le moment) suffit : rien de plus. Quand quelque chose de grave la touche ces jours-ci, avec douceur."""
    p = params(frame.env.params_of("others", frame.root))
    local = frame.local()
    if not within_daily_window(local.hour * 60 + local.minute, p.checkin_day_start_min, p.checkin_day_end_min):
        return []
    today = _day_start(frame.now, frame)
    out: list[Candidate] = []
    for person in sorted(set(frame.get(social_c.CIRCLE)).intersection(s.people.keys())):  # ses amies (ADR 0058)
        if frame.get(social_c.CLOSENESS(person)) not in (social_c.FRIEND, social_c.CLOSE):
            continue
        due = [ev for ev in frame.get(memory_c.LIFE_EVENTS(person))
               if ev.festive and not ev.ongoing and not ev.followed_at and set(ev.told_by) <= {person}
               and _day_start(ev.when, frame) == today and s.spoke.get(ev.id, 0) < today]
        address = _address(frame, person) if due else None
        if address is None:
            continue
        ev = due[0]
        name = frame.get(identity_c.IDENTITY(person)).name or frame.get(identity_c.IDENTITY(address)).name
        who = f"« {name} »" if name else "cette personne"
        brief = (f"Aujourd'hui, c'est un jour qui se fête pour {who} (tu le vois dans « CE QUI SE PASSE DANS SA "
                 "VIE ») : souhaite-le-lui, chaleureusement et simplement.")
        if _hard(frame, person):
            brief += " Avec douceur : ces jours-ci sont durs pour cette personne, pas de grande fête."
        # si la personne écrit entre-temps, c'est sa réponse qui le lui souhaite (« souhaite-le-lui si ce n'est pas
        # fait »), pas une initiative de plus
        handles = frame.get(identity_c.HANDLES(person)) or (person,)
        guard = Guard("pas de nouvelles", reads=tuple(transcript_c.LAST_FROM(h) for h in handles))
        out.append(Candidate(Kind.INITIATIVE, address, c.CELEBRATE, p.celebrate_evidence,
                             resources=frozenset({floor(address)}), guards=(guard,),
                             args=FrozenDict({"brief:others": brief, "subject": f"{MOMENT_SUBJECT}{ev.id}"})))
    return out


# ── Prompt ────────────────────────────────────────────────────────────────


#: les messages de la personne relus pour sentir qu'elle ne répond plus que par quelques mots
CURT_RUN = 3
#: … dans cette conversation (au-delà, une autre conversation a commencé)
CURT_SPAN_US = 30 * MINUTE
CURT_LINE = ("Depuis quelques messages, {who} ne te répond que par quelques mots : pas trop envie de parler. Fais "
             "court — pas de question, pas de proposition, pas de discours pour remonter le moral ; un mot doux, "
             "et laisse-lui la porte ouverte.")


@OTHERS.enricher("their_last_words", episodes=[Kind.REPLY], deadline_ms=300)
async def _their_last_words(s: OthersState, frame: Frame, ports: Any) -> tuple[str, ...] | None:
    """Ses derniers messages dans cette conversation (de la même adresse, au même endroit), du plus ancien au plus
    récent, jusqu'au message auquel elle répond."""
    store, ep = ports.get("store"), frame.episode
    reply_to = ep.attrs.get("reply_to") if ep is not None else None
    if store is None or ep is None or not ep.target or reply_to is None:
        return None
    room = ep.attrs.get("room")
    where, arg = ("room=?", room) if room else ("room IS NULL", None)
    args = (ep.target, reply_to, frame.now - CURT_SPAN_US) + ((arg,) if room else ())
    rows = store.query_mind(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE person=? AND role='user' AND id<=? "
                            f"AND at>=? AND {where} ORDER BY id DESC LIMIT ?", (*args, CURT_RUN))
    return tuple(str(r[0] or "") for r in reversed(rows))


def _few_words(text: str) -> bool:
    """Trois mots au plus, ni question ni bonjour (un bonjour est court par nature)."""
    tokens = re.findall(r"\w+", fold(text))
    return bool(tokens) and len(tokens) <= 3 and not text.strip().endswith("?") and tokens[0] not in SALUTATIONS


def curt(words: tuple[str, ...]) -> bool:
    """Trois messages d'affilée réduits à quelques mots (« ouais », « bof », « je sais pas ») : elle ne dit plus
    grand-chose."""
    return len(words) >= CURT_RUN and all(_few_words(w) for w in words[-CURT_RUN:])


@OTHERS.section("their_state", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, after=["who"], trim_rank=40,
                title="CE QUE TU PERÇOIS DE SON ÉTAT", reads=[identity_c.PERSON, identity_c.IDENTITY, c.MIND])
def _their_state(s: OthersState, frame: Frame, enrich: Any) -> SectionBody | None:
    """Les indices du message auquel elle répond — et, en privé, ce qui tranche
    avec le ton habituel de la personne. Jamais un nombre."""
    ep, aud = frame.episode, frame.audience
    if ep is None or not ep.target or not is_identifiable(ep.target):
        return None
    p = params(frame.env.params_of("others", frame.root))
    person = frame.get(identity_c.PERSON(ep.target))
    r = frame.get(c.MIND(person))
    lines: list[str] = []
    if ep.kind == Kind.REPLY and r.last_cues and r.last_message == ep.attrs.get("reply_to"):
        lines.append("Dans son message : " + " ; ".join(r.last_cues) + ".")
    if aud is not None and aud.private_ok and r.confidence >= 1.0:
        name = frame.get(identity_c.IDENTITY(person)).name
        who = f"« {name} »" if name else "cette personne"
        if r.deviation <= -p.notable_deviation:
            lines.append(f"Ça ne ressemble pas à {who} : d'habitude, le ton est plus léger que ça.")
        elif r.deviation >= p.notable_deviation:
            lines.append(f"{who[0].upper()}{who[1:]} a l'air d'humeur plus légère que d'habitude.")
        if r.current_arousal - r.usual_arousal >= p.notable_deviation:
            lines.append("Le ton est plus vif, plus agité que d'habitude.")
    if ep.kind == Kind.REPLY and curt(enrich.get("their_last_words") or ()):
        # sonde réelle du 2026-10-03 : à « ouais », « bof », « je sais pas », « laisse tomber », de longs messages
        # pleins de questions et d'idées pour se changer les idées
        name = frame.get(identity_c.IDENTITY(person)).name
        lines.append(CURT_LINE.format(who=f"« {name} »" if name else "cette personne"))
    if not lines:
        return None
    lines.append("C'est un indice, pas une certitude.")
    return SectionBody("\n".join(lines))
