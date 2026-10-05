"""La faculté ``attention`` : sa tranche, ses réducteurs, ses faits, ce que ses
événements font ressentir.

- **Pensées** : ce qu'il en reste suit une demi-vie (``intensité ·
  ½^(Δ/demi-vie)``, lu à l'instant) ; en parler à la personne concernée la
  divise par deux ; une pensée trop faible s'éteint.
- **Un échange qui marque** (une émotion déclarée forte, ou nettement
  négative) laisse une pensée — une seule par personne à la fois : un
  deuxième tour chargé avec la même personne ravive la pensée existante au
  lieu d'en créer une autre, et il n'y a jamais plus de trois pensées nées
  d'échanges en même temps (douze insultes ne font pas douze ruminations).
- **Attentes** : écrire d'elle-même à quelqu'un fait attendre sa réponse
  (vingt minutes sur l'application, une heure par message — plus, quand elle
  a appris que cette personne met plus longtemps : ``others``) ; quelqu'un
  qui lui manque fait attendre son retour ; une promesse datée fait attendre
  d'elle-même qu'elle la tienne.
- **Inquiétude** : quelqu'un qui compte et qui n'avait pas l'air comme
  d'habitude (``others``) laisse une pensée — la même règle qu'un échange qui
  marque : une par personne à la fois.
- **Une promesse non tenue** à son échéance laisse une pensée (« j'avais
  promis… »), qui pousse à le lui dire ; la tenir, même en retard, l'apaise.
- **Le fil avec chacun** (``AWAITING``) : ce qu'elle a écrit depuis le
  dernier message de la personne, si son dernier mot posait une question,
  combien d'initiatives sont restées sans réponse. La retenue s'en sert ; la
  personne écrit, tout repart de zéro.
- **Ignorée, elle le ressent** : une initiative restée sans réponse laisse
  une pensée (« Adrien ne m'a pas répondu »), un léger pincement — jamais
  une relance. Une réponse tardive ne compte comme réponse que dans trois
  fois le délai attendu (ADR 0033) — par messagerie, dans les jours qui
  suivent. Le délai court sur les heures où la personne écrit d'habitude
  (``others.hours``) : la nuit de l'autre n'est pas un silence.
- **Une conversation qui se clôt** (« bonne nuit », « à demain », ou la
  personne qui s'en va juste après sa réponse) ne laisse rien « sans
  réponse » : on s'est quittées, on ne l'ignore pas.
- **Seule** : plus d'un jour sans que personne ne lui écrive, une pensée
  (« Personne ne m'a parlé depuis hier ») — pas avant l'heure où une amie
  qui écrit presque chaque jour passe d'habitude (on l'attend, on n'est pas
  seule). Elle met des mots sur le vide que ``needs`` lui fait sentir, sans
  le faire ressentir une seconde fois (ADR 0058).
- **Une amie qui lui manque** et à qui elle n'écrit pas (injoignable, ou qui
  ne répond plus) : une pensée, puis d'autres, de plus en plus rares à mesure
  que le silence double, et de moins en moins fortes (ADR 0058).
- **Un bel échange** reste en tête : le lendemain, s'il n'y a pas eu d'autre
  contact, il peut donner envie de lui en reparler (« encore bravo pour le
  poste ! ») — une raison faible.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import agency as agency_c
from mika.contracts import attention as c
from mika.contracts import expression as expression_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import others as others_c
from mika.contracts import presence as presence_c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict
from mika.vocab import affect as A
from mika.vocab import privacy
from mika.vocab.affect import Appraisal, Declared, Emotion
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable


class AttentionParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    half_life_us: Annotated[int, Knob(
        label="Demi-vie d'une pensée", group="Pensées", lo=30 * MINUTE, hi=3 * DAY,
        help="Une pensée perd la moitié de son intensité en ce temps. Plus long : des ruminations qui durent des "
             "jours ; plus court : rien ne lui reste en tête.")] = 6 * HOUR
    fade_below: Annotated[float, Knob(
        label="Seuil d'extinction", group="Pensées", lo=0.01, hi=0.5, step=0.01,
        help="Une pensée dont l'intensité passe sous ce seuil s'éteint : elle ne se lit plus nulle part.")] = 0.1
    max_thoughts: Annotated[int, Knob(
        label="Pensées vivantes au plus", group="Pensées", lo=1, hi=30,
        help="Au-delà, les plus faibles s'effacent quand une nouvelle naît.")] = 8
    # un échange qui marque
    marking_intensity: Annotated[float, Knob(
        label="Intensité qui marque", group="Un échange qui marque", lo=0.0, hi=1.0, step=0.05,
        help="Une réponse qu'elle donne avec une émotion déclarée au moins aussi intense laisse une pensée sur "
             "la personne.")] = 0.75
    marking_valence: Annotated[float, Knob(
        label="Valence qui marque", group="Un échange qui marque", lo=-1.0, hi=0.0, step=0.05,
        help="Une réponse dont l'émotion déclarée est au moins aussi négative (valence) marque aussi, dès "
             "l'intensité minimale. Près de 0 : presque tout échange un peu tendu laisse une pensée.")] = -0.2
    marking_min_intensity: Annotated[float, Knob(
        label="Intensité minimale", group="Un échange qui marque", lo=0.0, hi=1.0, step=0.05,
        help="Sous cette intensité déclarée, aucun échange ne marque, même négatif.")] = 0.5
    birth_factor: Annotated[float, Knob(
        label="Force à la naissance", group="Un échange qui marque", lo=0.0, hi=1.0, step=0.05,
        help="La pensée naît à cette fraction de l'intensité déclarée ; un nouvel échange marquant avec la même "
             "personne la ravive jusque-là.")] = 0.7
    exchange_spacing_us: Annotated[int, Knob(
        label="Espacement des échanges", group="Un échange qui marque", lo=MINUTE, hi=6 * HOUR,
        help="Dans ce délai, un nouvel échange marquant avec la même personne ravive sa pensée au lieu d'en créer "
             "une ; au-delà, lui reparler divise par deux ce qui la concerne.")] = 30 * MINUTE
    exchange_settle_us: Annotated[int, Knob(
        label="Laisser l'échange se poser", group="Un échange qui marque", lo=0, hi=2 * HOUR,
        help="Une pensée née d'un échange naît quand la personne n'a plus rien écrit depuis ce délai, et du moment "
             "le plus marquant de l'échange — pas du premier message un peu chargé (« bon ben voilà » plutôt que "
             "« je crois que j'ai tout raté »).")] = 10 * MINUTE
    exchange_cap: Annotated[int, Knob(
        label="Pensées d'échanges à la fois", group="Un échange qui marque", lo=0, hi=10,
        help="Jamais plus de pensées nées d'échanges en même temps (une par personne) : douze insultes ne font "
             "pas douze ruminations.")] = 3
    # une croyance révisée, un manque, un but bloqué
    revision_intensity: Annotated[float, Knob(
        label="Croyance révisée", group="Révision, manque, blocage", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité de la pensée de confusion quand une croyance en remplace une autre (« je croyais "
             "que… »).")] = 0.3
    blocked_intensity: Annotated[float, Knob(
        label="But bloqué", group="Révision, manque, blocage", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité de la pensée de frustration (« je bloque sur… ») quand un de ses buts bloque.")] = 0.35
    missing_intensity: Annotated[float, Knob(
        label="Quelqu'un qui manque", group="Révision, manque, blocage", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité de la pensée nostalgique pour une personne qui lui manque et qu'elle ne peut pas "
             "joindre (une à la fois).")] = 0.3
    missing_check_us: Annotated[int, Knob(
        label="Vérifier les manques toutes les", group="Révision, manque, blocage", lo=5 * MINUTE, hi=12 * HOUR,
        help="Éveillée, elle se demande à ce rythme qui lui manque sans qu'elle puisse le joindre.")] = 30 * MINUTE
    missing_fading: Annotated[float, Knob(
        label="Un manque qui dure : chaque pensée plus faible de", group="Révision, manque, blocage", lo=0.3, hi=1.0,
        step=0.05,
        help="Quelqu'un qui lui manque et qu'elle ne peut (ou ne veut plus) relancer lui revient en tête de plus en "
             "plus rarement : une pensée quand son silence atteint quatre fois son rythme, puis huit, seize… "
             "Chacune est plus faible que la précédente de ce facteur (jamais sous le seuil d'extinction).")] = 0.8
    # y repenser
    dwell_every_us: Annotated[int, Knob(
        label="Y repenser au plus toutes les", group="Y repenser", lo=5 * MINUTE, hi=12 * HOUR,
        help="Éveillée, elle revient à sa pensée la plus forte au plus à ce rythme, et en ressent un peu "
             "l'émotion à chaque fois.")] = 30 * MINUTE
    dwell_from: Annotated[float, Knob(
        label="Y repenser dès", group="Y repenser", lo=0.0, hi=1.0, step=0.05,
        help="Seule une pensée au moins aussi intense lui revient en tête.")] = 0.3
    dwell_factor: Annotated[float, Knob(
        label="Émotion en y repensant", group="Y repenser", lo=0.0, hi=1.0, step=0.05,
        help="La fraction de l'intensité de la pensée qu'elle ressent quand elle y repense.")] = 0.3
    birth_appraisal_factor: Annotated[float, Knob(
        label="Émotion quand une pensée naît", group="Y repenser", lo=0.0, hi=1.0, step=0.05,
        help="La fraction de l'intensité d'une pensée qu'elle ressent au moment où elle naît.")] = 0.5
    # attentes
    reply_window_us: Annotated[int, Knob(
        label="Délai de réponse attendu", group="Attentes", lo=MINUTE, hi=6 * HOUR,
        help="Après une initiative (pas une salutation ni un rappel), elle attend une réponse ; passé ce délai, "
             "elle compte comme ignorée : son estime baisse et elle se fait plus réservée.")] = 20 * MINUTE
    reply_window_message_us: Annotated[int, Knob(
        label="Délai de réponse (messagerie)", group="Attentes", lo=5 * MINUTE, hi=DAY,
        help="Le même délai sur une messagerie (un compte extérieur), où un message se lit quand on y pense, pas "
             "quand il arrive : une amie qui n'a pas répondu en une heure, le soir, ne l'ignore pas.")] = 3 * HOUR
    reply_learned_after: Annotated[int, Knob(
        label="Délais mesurés avant d'en tenir compte", group="Attentes", lo=1, hi=50,
        help="Après tant de réponses mesurées de la même personne sur le même canal, elle attend à la mesure de "
             "son délai habituel (jamais moins que le délai ci-dessus).")] = 3
    reply_window_factor: Annotated[float, Knob(
        label="Attendre tant de fois son délai habituel", group="Attentes", lo=1.0, hi=10.0, step=0.5,
        help="Une personne qui répond d'habitude en deux heures n'ignore pas un message au bout de trois : "
             "elle attend ce multiple de son délai habituel.")] = 2.0
    reply_window_max_us: Annotated[int, Knob(
        label="Délai de réponse attendu au plus", group="Attentes", lo=HOUR, hi=7 * DAY,
        help="Même appris, le délai attendu ne dépasse jamais cette durée.")] = DAY
    promise_grace_us: Annotated[int, Knob(
        label="Délai de grâce d'une promesse", group="Promesses", lo=0, hi=3 * DAY,
        help="Une promesse datée n'est tenue pour manquée que ce délai après son échéance.")] = 2 * HOUR
    promise_intensity: Annotated[float, Knob(
        label="Une promesse non tenue", group="Promesses", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité de la pensée (« j'avais promis… ») quand une promesse passe son échéance sans être "
             "tenue ; assez forte, elle pousse à le dire à la personne.")] = 0.55
    unanswered_intensity: Annotated[float, Knob(
        label="Une initiative restée sans réponse", group="Révision, manque, blocage", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité de la pensée (« Adrien ne m'a pas répondu ») quand une initiative reste sans réponse : un "
             "léger pincement, qui ne pousse jamais à lui réécrire.")] = 0.25
    question_unanswered_us: Annotated[int, Knob(
        label="Une question restée sans réponse, après", group="Révision, manque, blocage", lo=30 * MINUTE,
        hi=3 * DAY,
        help="Éveillée, quand la question qu'elle a posée à quelqu'un reste sans réponse depuis cette durée alors "
             "que la personne est restée là (connectée sans interruption), elle le ressent aussi (« … n'a pas répondu "
             "à ma question ») — sans lui réécrire pour autant. Quelqu'un qui est parti n'ignore personne.")] = 6 * HOUR
    late_reply_factor: Annotated[float, Knob(
        label="Une réponse tardive compte pendant", group="Attentes", lo=1.0, hi=10.0, step=0.5,
        help="Une réponse qui arrive après le délai attendu compte encore comme réponse à son initiative tant "
             "qu'elle arrive dans ce multiple du délai (compté depuis l'initiative) ; plus tard, la personne écrit, "
             "mais ce n'est plus une réponse.")] = 3.0
    late_reply_message_us: Annotated[int, Knob(
        label="Une réponse tardive (messagerie) compte pendant", group="Attentes", lo=HOUR, hi=14 * DAY,
        help="Par messagerie, on répond quand on y pense : le premier message de la personne dans ce délai après "
             "son initiative compte encore comme une réponse (s'il est plus long que le multiple ci-dessus).")] = \
        3 * DAY
    reply_quiet_extra_us: Annotated[int, Knob(
        label="La nuit de l'autre : au plus", group="Attentes", lo=0, hi=3 * DAY,
        help="Le délai de réponse ne court que pendant les heures où la personne écrit d'habitude (apprises, sinon "
             "hors d'une nuit supposée) : un message de 21 h 30 à quelqu'un qui écrit le matin attend le matin. Les "
             "heures creuses ne l'allongent jamais de plus que ça.")] = DAY
    closing_left_us: Annotated[int, Knob(
        label="Partie juste après sa réponse", group="Attentes", lo=0, hi=2 * HOUR,
        help="Quand la personne quitte l'application dans ce délai après sa réponse, la conversation s'est close : "
             "son dernier message n'est pas « sans réponse » (comme après « bonne nuit »).")] = 15 * MINUTE
    alone_after_us: Annotated[int, Knob(
        label="Seule après", group="Révision, manque, blocage", lo=6 * HOUR, hi=7 * DAY,
        help="Éveillée, quand personne ne lui a écrit depuis cette durée, une pensée naît (« Personne ne m'a "
             "parlé depuis hier »), une de plus par jour de silence.")] = DAY
    alone_intensity: Annotated[float, Knob(
        label="Personne ne lui parle", group="Révision, manque, blocage", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité de cette pensée de solitude.")] = 0.35
    alone_margin_us: Annotated[int, Knob(
        label="Seule : attendre une amie de tant", group="Révision, manque, blocage", lo=0, hi=12 * HOUR,
        help="Une amie ou une proche qui écrit presque chaque jour à peu près à la même heure : elle ne se sent pas "
             "seule avant ce délai après l'heure où elle passe d'habitude — on l'attend ; c'est quand elle ne vient "
             "pas qu'on se sent seule.")] = 2 * HOUR
    alone_daily_rhythm_days: Annotated[float, Knob(
        label="Seule : une amie de tous les jours, rythme d'au plus (jours)", group="Révision, manque, blocage",
        lo=1.0, hi=7.0, step=0.5,
        help="… une amie dont le rythme (l'écart habituel entre deux jours où elle écrit) ne dépasse pas tant de "
             "jours.")] = 1.5
    remorse_from: Annotated[float, Knob(
        label="Avoir été dure : une colère d'au moins", group="Révision, manque, blocage", lo=0.1, hi=1.0, step=0.05,
        help="Quand elle répond à une amie ou une proche avec de la colère, de l'agacement ou du dégoût au moins "
             "aussi intenses (sa balise d'émotion), une pensée lui reste (« J'ai été dure avec Alice ») — l'envie de "
             "revenir vers elle. Jamais envers une inconnue : un troll n'appelle pas d'excuses.")] = 0.6
    remorse_intensity: Annotated[float, Knob(
        label="Avoir été dure : intensité", group="Révision, manque, blocage", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité de cette pensée (gênée) à sa naissance.")] = 0.55
    concern_intensity: Annotated[float, Knob(
        label="Quelqu'un qui n'avait pas l'air bien", group="Révision, manque, blocage", lo=0.0, hi=1.0, step=0.05,
        help="L'intensité de la pensée quand une amie ou une proche n'avait pas l'air comme d'habitude (un "
             "message nettement plus sombre que ce qu'elle attendait d'elle).")] = 0.45
    # la nuit : les pensées de la veille s'allègent (÷3) et se calment
    digest_after_sleep_us: Annotated[int, Knob(
        label="Digérer après", group="La nuit", lo=0, hi=10 * HOUR,
        help="Une fois par nuit, ce temps après l'endormissement, ses pensées s'allègent et leur couleur se calme. "
             "Plus long que son sommeil : pas de digestion cette nuit-là.")] = 3 * HOUR
    digest_min_age_us: Annotated[int, Knob(
        label="Âge minimal pour digérer", group="La nuit", lo=0, hi=DAY,
        help="Une pensée plus récente que ça n'est pas digérée cette nuit (elle attend la suivante).")] = 2 * HOUR
    digest_factor: Annotated[float, Knob(
        label="Ce qu'il en reste au matin", group="La nuit", lo=0.0, hi=1.0, step=0.01,
        help="L'intensité d'une pensée digérée est multipliée par ce facteur (1 : la nuit n'allège rien).")] = 1 / 3
    reflective_from: Annotated[float, Knob(
        label="Souvenir réfléchi dès", group="La nuit", lo=0.0, hi=1.0, step=0.05,
        help="Une pensée encore au moins aussi forte à la digestion devient un souvenir réfléchi (« après y avoir "
             "repensé cette nuit… »).")] = 0.25
    # ce que signalent les sources extérieures : l'habituation (la même source,
    # la même sorte, à répétition, se remarque de moins en moins) et le dosage
    # (une source ne fait pas plus qu'une petite émotion en dix minutes)
    habituation_window_us: Annotated[int, Knob(
        label="Fenêtre d'habituation", group="Signaux extérieurs", lo=MINUTE, hi=2 * HOUR,
        help="Les signaux d'une même source et d'une même sorte répétés dans cette fenêtre se remarquent de moins "
             "en moins ; c'est aussi la fenêtre du dosage de l'émotion.")] = 10 * MINUTE
    habituation_factor: Annotated[float, Knob(
        label="Facteur d'habituation", group="Signaux extérieurs", lo=0.0, hi=1.0, step=0.01,
        help="Le poids d'un signal est multiplié par ce facteur à chaque répétition dans la fenêtre (1 : aucune "
             "habituation).")] = 0.85
    habituation_floor: Annotated[float, Knob(
        label="Plancher d'habituation", group="Signaux extérieurs", lo=0.0, hi=1.0, step=0.05,
        help="Le poids d'un signal répété ne descend jamais sous ce plancher : le quarantième titre est un bruit "
             "de fond, pas rien.")] = 0.4
    dose_cap: Annotated[float, Knob(
        label="Émotion par source au plus", group="Signaux extérieurs", lo=0.0, hi=2.0, step=0.05,
        help="L'émotion cumulée qu'une même source peut lui faire ressentir dans la fenêtre : un flux est une "
             "source d'émotion, pas quinze.")] = 0.6
    signal_thought_from: Annotated[float, Knob(
        label="Pensée née d'un signal dès", group="Signaux extérieurs", lo=0.0, hi=1.0, step=0.05,
        help="Un signal dont la pertinence (après habituation) atteint ce seuil devient une pensée : ce qu'elle a "
             "lu ou vu lui reste en tête.")] = 0.6
    signal_thought_factor: Annotated[float, Knob(
        label="Force d'une pensée de signal", group="Signaux extérieurs", lo=0.0, hi=1.0, step=0.05,
        help="Son intensité : la pertinence retenue multipliée par ce facteur, dans la limite du plafond.")] = 0.7
    signal_thought_max: Annotated[float, Knob(
        label="Plafond d'une pensée de signal", group="Signaux extérieurs", lo=0.0, hi=1.0, step=0.05,
        help="Une pensée née d'un signal ne dépasse jamais cette intensité.")] = 0.6
    signals_kept: Annotated[int, Knob(
        label="Signaux en attente au plus", group="Signaux extérieurs", lo=4, hi=256,
        help="Au plus autant de signaux attendent d'être remarqués ; au-delà, les plus anciens sont oubliés sans "
             "avoir été vus.")] = 32
    # une pensée qui insiste pousse à en reparler (log-odds)
    thought_from: Annotated[float, Knob(
        label="Envie d'en reparler dès", group="Relancer", lo=0.0, hi=0.95, step=0.05,
        help="Une pensée négative (inquiétude, peine, colère…) sur une personne qui n'est pas une étrangère, au "
             "moins aussi intense, lui donne envie de lui en reparler.")] = 0.4
    insist_after_us: Annotated[int, Knob(
        label="Y revenir au plus tôt après", group="Relancer", lo=0, hi=DAY,
        help="Une pensée sur quelqu'un ne pousse à lui en reparler qu'après ce délai depuis l'échange qui l'a fait "
             "naître ou raviver : on ne relance pas vingt minutes après s'être parlé.")] = 2 * HOUR
    thought_evidence: Annotated[float, Knob(
        label="Poids de l'envie d'en reparler", group="Relancer", lo=0.0, hi=4.0, step=0.1,
        help="La preuve (log-odds) qu'une telle pensée apporte à une initiative, pleine à mi-chemin entre le seuil "
             "et 1. L'arbitrage la plafonne à 4, loin du seuil d'initiative (9).")] = 4.0
    glad_after_us: Annotated[int, Knob(
        label="Un bel échange : y repenser après", group="Relancer", lo=HOUR, hi=3 * DAY,
        help="Un échange qui l'a rendue heureuse avec une amie ou une proche (« j'ai eu le poste !! ») : passé ce "
             "délai, s'il n'y a pas eu d'autre contact, elle peut avoir envie de lui en reparler (« encore bravo, "
             "j'y repensais ce matin ! »).")] = 12 * HOUR
    glad_until_us: Annotated[int, Knob(
        label="Un bel échange : jusqu'à", group="Relancer", lo=2 * HOUR, hi=7 * DAY,
        help="Au-delà, ce n'est plus d'actualité.")] = 36 * HOUR
    glad_evidence: Annotated[float, Knob(
        label="Poids d'un bel échange", group="Relancer", lo=0.0, hi=4.0, step=0.1,
        help="La preuve (log-odds) de cette envie : faible — elle le fait si elle y pense, pas à coup sûr.")] = 2.5


@dataclass(frozen=True, slots=True)
class Thought:
    id: int
    text_ref: str
    emotion: str
    intensity: float  # à ``touched_at``
    touched_at: int
    born_at: int
    origin: str
    about: tuple[str, ...] = ()
    sensitivity: int = 2
    bundle: str = ""
    source: int | None = None  # le message, la promesse… d'où elle vient


@dataclass(frozen=True, slots=True)
class SignalHeard:
    """Un signal qui attend d'être remarqué."""

    seq: int
    source: str
    kind: str
    summary_ref: str
    pertinence: float
    emotion: str
    intensity: float
    about: tuple[str, ...]
    sensitivity: int
    bundle: str
    at: int


@dataclass(frozen=True, slots=True)
class Heard:
    """Un signal remarqué récemment (habituation, dosage)."""

    at: int
    source: str
    kind: str
    intensity: float
    #: pour l'inspecteur : le signal, ce que la source en estimait, le poids après habituation
    signal: int = 0
    pertinence: float = 0.0
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class Pending:
    """Un échange qui a marqué, une croyance révisée : la pensée reste à écrire."""

    source: int
    origin: str
    person: str | None
    emotion: str
    intensity: float
    at: int
    public: bool = False
    extra: int | None = None  # la croyance remplacée
    ref: str = ""  # un texte déjà écrit (le titre d'un but bloqué)
    about: tuple[str, ...] = ()
    sensitivity: int = 2


@dataclass(frozen=True, slots=True)
class Expectation:
    kind: str
    person: str
    since: int
    deadline: int | None
    ref: int | None = None  # la promesse (``PROMISE``)
    channel: str = ""  # le canal de l'initiative (``REPLY``) : une messagerie se lit quand on y pense


@dataclass(frozen=True, slots=True)
class Exchange:
    """Le fil avec une personne, de son côté à elle (voir ``AwaitingReading``)."""

    last_in: int = 0
    last_out: int = 0
    asked: bool = False
    owed: bool = False
    initiatives: int = 0
    last_initiative_at: int = 0
    ignored: int = 0
    unanswered: bool = False
    #: elle a déjà ressenti ce silence-là (une pensée « … ne m'a pas répondu »)
    felt: bool = False
    #: le dernier message de la personne clôt la conversation (« bonne nuit ») : y répondre n'attend rien
    closing: bool = False
    #: quand la conversation s'est close (« bonne nuit » lu, sa réponse, ou la personne partie juste après)
    closed_at: int = 0


@dataclass(frozen=True, slots=True)
class Late:
    """Une réponse attendue qui n'est pas venue à temps : elle compte encore jusqu'à ``until``."""

    since: int
    until: int


@dataclass(frozen=True, slots=True)
class AttentionState:
    thoughts: FrozenDict[int, Thought] = field(default_factory=FrozenDict)
    pending: tuple[Pending, ...] = ()
    expectations: FrozenDict[str, Expectation] = field(default_factory=FrozenDict)
    #: les initiatives en cours (corrélation → raisons) : une salutation n'attend pas de réponse
    openings: FrozenDict[str, str] = field(default_factory=FrozenDict)
    ignored: int = 0
    #: les personnes dont la réponse n'est pas venue à temps : une réponse tardive compte encore, un temps
    late: FrozenDict[str, Late] = field(default_factory=FrozenDict)
    dwelt_at: int = 0
    digested_night: str = ""
    signals: tuple[SignalHeard, ...] = ()
    heard: tuple[Heard, ...] = ()
    #: le fil avec chacun (par personne)
    exchanges: FrozenDict[str, Exchange] = field(default_factory=FrozenDict)
    #: le dernier message qu'on lui a adressé, de qui que ce soit
    last_contact: int = 0
    #: la dernière pensée de solitude (« personne ne m'a parlé depuis… »)
    alone_at: int = 0
    #: quand la personne a, pour la dernière fois, recoupé le sujet de ce qui la concerne ou retrouvé son ton
    eased: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: un bel échange avec quelqu'un (personne → (la pensée, quand elle est née)) : le lendemain, l'envie d'en
    #: reparler, s'il n'y a pas eu d'autre contact
    glad: FrozenDict[str, tuple[int, int]] = field(default_factory=FrozenDict)
    #: la dernière pensée de manque pour chacun (personne → quand) : la suivante attend que son silence ait doublé
    missing: FrozenDict[str, int] = field(default_factory=FrozenDict)


#: v5 : une conversation close (« bonne nuit ») n'est pas « sans réponse » ; le délai de réponse court sur les
#: heures de la personne (le canal est retenu avec l'attente) ; un bel échange reste en tête.
#: v6 : la dernière pensée de manque de chacun (un manque qui dure revient de plus en plus rarement, ADR 0058).
#: v7 : un message qui clôt (« bonne nuit ») close la conversation dès sa lecture, même si elle se tait.
ATTENTION = Faculty("attention", state=AttentionState, init=lambda p: AttentionState(), params=AttentionParams,
                    state_version=7)
#: les manques dont on retient la dernière pensée (les plus récents)
MISSING_KEPT = 64

#: Les pensées nées d'une relation : une par personne à la fois, trois au plus.
RELATIONAL = (c.EXCHANGE, c.CONCERN)
#: un « bel échange » : une bonne nouvelle partagée (« j'ai eu le poste !! ») — la joie, l'enthousiasme, la fierté
#: pour elle, le soulagement ; pas la tendresse d'un soir ordinaire (elle n'appelle pas un « j'y repensais »)
GLAD = frozenset({Emotion.HAPPY.value, Emotion.EXCITED.value, Emotion.PROUD.value, Emotion.RELIEVED.value,
                  Emotion.GRATEFUL.value, Emotion.HOPEFUL.value})
ATTENTION.declare(*c.ALL)


def params(p: AttentionParams | None) -> AttentionParams:
    return p if p is not None else AttentionParams()


def current(t: Thought, now: int, p: AttentionParams) -> float:
    return t.intensity * 0.5 ** (max(0, now - t.touched_at) / p.half_life_us)


def _alive(s: AttentionState, now: int, p: AttentionParams) -> FrozenDict[int, Thought]:
    """Les pensées encore vivantes, au plus ``max_thoughts`` (les plus faibles s'effacent)."""
    kept = sorted(((current(t, now, p), t) for t in s.thoughts.values() if current(t, now, p) >= p.fade_below),
                  key=lambda x: (-x[0], x[1].id))[: p.max_thoughts]
    return FrozenDict({t.id: t for _, t in kept})


def _marking(declared: Declared, p: AttentionParams) -> bool:
    if declared.intensity < p.marking_min_intensity:
        return False
    return declared.intensity >= p.marking_intensity or A.valence(declared.emotion) <= p.marking_valence


def expectation_key(kind: str, person: str, ref: int | None = None) -> str:
    """Une attente par personne (sa réponse, son retour) ; une par promesse."""
    return f"{kind}:{ref}" if kind == c.PROMISE else f"{kind}:{person}"


def _expect(s: AttentionState, kind: str, person: str, since: int, deadline: int | None,
            ref: int | None = None) -> AttentionState:
    return replace(s, expectations=s.expectations.set(expectation_key(kind, person, ref),
                                                      Expectation(kind, person, since, deadline, ref)))


def _relational(s: AttentionState, person: str, emotion: str, intensity: float, source: int, origin: str, at: int,
                p: AttentionParams, public: bool = False) -> AttentionState:
    """Une pensée née d'une relation — un échange qui marque, une inquiétude :
    une par personne à la fois (une nouvelle ravive celle qui est là), trois
    au plus en même temps."""
    alive = _alive(s, at, p)
    same = sorted((t for t in alive.values() if t.origin in RELATIONAL and person in t.about
                   and at - t.touched_at < p.exchange_spacing_us), key=lambda t: t.id)
    if same:
        t = same[0]
        stronger = max(current(t, at, p), intensity)
        return replace(s, thoughts=s.thoughts.set(t.id, replace(t, intensity=stronger, touched_at=at)))
    waiting = next((q for q in s.pending if q.person == person and q.origin == origin), None)
    if waiting is not None:
        # l'échange ne s'est pas encore posé : la pensée naîtra de son moment le plus marquant
        if intensity <= waiting.intensity:
            return s
        stronger = replace(waiting, source=source, emotion=emotion, intensity=round(intensity, 3), at=at,
                           public=public)
        return replace(s, pending=tuple(stronger if q is waiting else q for q in s.pending))
    born = sum(1 for t in alive.values() if t.origin in RELATIONAL)
    queued = sum(1 for q in s.pending if q.origin in RELATIONAL)
    if born + queued >= p.exchange_cap or any(q.person == person for q in s.pending):
        return s
    return replace(s, pending=(*s.pending, Pending(source, origin, person, emotion, round(intensity, 3), at,
                                                   public=public)))


# ── Réducteurs ────────────────────────────────────────────────────────────


def owed(reasons: Any) -> bool:
    """Saluer qui arrive, dire un rappel promis : ce n'est pas prendre la parole pour qu'on lui réponde
    (``agency.NOT_SPEAKING_UP``, déclaré une fois)."""
    return bool(agency_c.NOT_SPEAKING_UP & set(reasons))


def _wrote_to(s: AttentionState, person: str, at: int, *, asked: bool, due: bool, ordinary: bool,
              reply: bool = False) -> AttentionState:
    ex = s.exchanges.get(person) or Exchange()
    # répondre à « bonne nuit » ne laisse rien en suspens : la conversation s'est close
    closed = reply and ex.closing and ex.last_in > ex.last_out
    ex = replace(ex, last_out=at, asked=asked and not closed, owed=due,
                 initiatives=ex.initiatives + (1 if ordinary else 0),
                 last_initiative_at=at if ordinary else ex.last_initiative_at, unanswered=not closed,
                 closed_at=at if closed else 0)
    return replace(s, exchanges=s.exchanges.set(person, ex))


#: ce qu'elle déclare quand elle est dure avec quelqu'un
HARSH = frozenset({Emotion.ANGRY, Emotion.FRUSTRATED, Emotion.DISGUSTED})


def _remorse(s: AttentionState, person: str, source: int, at: int, p: AttentionParams) -> AttentionState:
    """Elle a été dure avec une amie : une pensée (« J'ai été dure avec Alice »), une seule par personne à la fois
    — une dispute qui dure la ravive, elle n'en crée pas dix."""
    alive = [t for t in _alive(s, at, p).values() if t.origin == c.REMORSE and person in t.about]
    if alive:
        t = min(alive, key=lambda t: t.id)
        return replace(s, thoughts=s.thoughts.set(t.id, replace(t, intensity=max(current(t, at, p),
                                                                                  p.remorse_intensity), touched_at=at)))
    if p.remorse_intensity <= 0 or any(q.origin == c.REMORSE and q.person == person for q in s.pending):
        return s
    return replace(s, pending=(*s.pending, Pending(source, c.REMORSE, person, Emotion.EMBARRASSED.value,
                                                   p.remorse_intensity, at)))


@ATTENTION.reducer(rt.UTTERANCE, reads=[identity_c.PERSON, others_c.REPLY_DELAY, others_c.HOURS, social_c.CLOSENESS])
def _uttered(s: AttentionState, e, cx) -> AttentionState:
    d = e.data
    if not d.visible or not d.target or not is_identifiable(d.target):
        return s
    p = params(cx.params)
    person = cx.facts.get(identity_c.PERSON(d.target))
    # y revenir avec la personne soulage — pas l'échange même qui l'a fait naître ou raviver ; une inquiétude,
    # un échange qui a marqué, seulement si la personne en a reparlé ou a retrouvé son ton (« ok » n'apaise rien)
    thoughts = s.thoughts
    for t in s.thoughts.values():
        if person not in t.about or e.at - t.touched_at < p.exchange_spacing_us:
            continue
        if t.origin in RELATIONAL and s.eased.get(person, 0) <= t.touched_at:
            continue
        thoughts = thoughts.set(t.id, replace(t, intensity=current(t, e.at, p) / 2, touched_at=e.at))
    s = replace(s, thoughts=thoughts)
    due = False
    if d.kind == Kind.INITIATIVE:
        reasons = s.openings.get(e.correlation, "").split(",")
        s = replace(s, openings=s.openings.delete(e.correlation))
        # dû (saluer, tenir parole) ou un simple encouragement : rien n'est attendu en retour
        due = owed(reasons) or bool(others_c.WELL_WISHES & set(reasons))
        if not due:
            deadline = reply_deadline(cx, person, d.channel or "", e.at, p)
            s = replace(s, expectations=s.expectations.set(
                expectation_key(c.REPLY, person), Expectation(c.REPLY, person, e.at, deadline, channel=d.channel or "")))
    if d.room is None:  # le fil privé avec la personne (un salon n'est pas une conversation à deux)
        s = _wrote_to(s, person, e.at, asked=d.annotation(expression_c.QUESTION_ANNOTATION) is not None, due=due,
                      ordinary=d.kind == Kind.INITIATIVE and not due, reply=d.kind == Kind.REPLY)
    if s.glad.get(person, (0, e.at))[1] < e.at - p.exchange_spacing_us:
        s = replace(s, glad=s.glad.delete(person))  # elle lui a reparlé depuis : l'envie s'est dite, ou est passée
    declared = Declared.decode(d.annotation(expression_c.EMOTION_ANNOTATION))
    if d.kind == Kind.REPLY and d.room is None and declared is not None and declared.emotion in HARSH \
            and declared.intensity >= p.remorse_from \
            and cx.facts.get(social_c.CLOSENESS(person)) in (social_c.FRIEND, social_c.CLOSE):
        s = _remorse(s, person, d.reply_to or e.seq, e.at, p)
    if d.kind != Kind.REPLY or declared is None or not _marking(declared, p):
        return s
    # un échange qui marque : une pensée par personne à la fois
    return _relational(s, person, declared.emotion.value, declared.intensity * p.birth_factor, d.reply_to or e.seq,
                       c.EXCHANGE, e.at, p, public=d.room is not None)


def reply_window(cx: Any, person: str, channel: str, p: AttentionParams) -> int:
    """Combien de temps attendre sa réponse : le délai du canal, ou — quand elle
    a appris que cette personne met plus longtemps — un multiple de son délai
    habituel (borné). Jamais moins que le délai du canal : répondre vite
    d'habitude ne rend pas impatiente."""
    window = p.reply_window_message_us if privacy.is_messaging(channel) else p.reply_window_us
    learned = cx.facts.get(others_c.REPLY_DELAY((person, channel)))
    if learned.samples >= p.reply_learned_after:
        window = max(window, min(p.reply_window_max_us, round(learned.median_us * p.reply_window_factor)))
    return window


def active_deadline(since: int, window: int, active: tuple[bool, ...], hour_of: Any, cap: int) -> int:
    """L'instant où ``window`` de temps s'est écoulé **pendant les heures actives** de la personne (``active[h]``,
    heure locale ``hour_of(t)``), à partir de ``since`` ; jamais au-delà de ``cap``. Les fuseaux à heure ronde
    suivent les heures UTC : on avance d'heure pleine en heure pleine."""
    t, left = since, window
    while left > 0 and t < cap:
        nxt = (t // HOUR + 1) * HOUR
        if active[hour_of(t) % 24]:
            if nxt - t >= left:
                return t + left
            left -= nxt - t
        t = nxt
    return min(t, cap)


def reply_deadline(cx: Any, person: str, channel: str, since: int, p: AttentionParams) -> int:
    """Quand elle se sentira ignorée : le délai attendu, compté sur les heures où la personne écrit d'habitude —
    une initiative de 21 h 30 à quelqu'un qui écrit le matin attend le matin ; la nuit de l'autre n'est pas un
    silence. Les heures creuses ne l'allongent jamais de plus que ``reply_quiet_extra_us``."""
    window = reply_window(cx, person, channel, p)
    hours = cx.facts.get(others_c.HOURS(person))
    if len(hours.active) != 24 or all(hours.active):
        return since + window
    return active_deadline(since, window, hours.active, lambda t: cx.local(t).hour,
                           since + window + p.reply_quiet_extra_us)


@ATTENTION.reducer(rt.PERCEPTION_RECEIVED, reads=[identity_c.PERSON])
def _heard_from(s: AttentionState, e, cx) -> AttentionState:
    """La personne écrit : le fil repart de zéro (elle n'attend plus rien
    d'elle), ce qu'elle ressentait de son silence s'éteint — et elle n'est plus
    seule. Une réponse qui arrive trop tard pour compter n'est plus attendue."""
    d = e.data
    if not d.addressed or not is_identifiable(d.handle):
        return s
    person = cx.facts.get(identity_c.PERSON(d.handle))
    before = s.exchanges.get(person) or Exchange()
    thoughts = s.thoughts
    for t in s.thoughts.values():
        if (t.origin == c.UNANSWERED and person in t.about) or t.origin == c.ALONE:
            thoughts = thoughts.delete(t.id)
    late = s.late
    stale = late.get(person)
    if stale is not None and e.at > stale.until:
        late = late.delete(person)  # elle écrit, mais ce n'est plus une réponse à son initiative
    return replace(s, exchanges=s.exchanges.set(person, Exchange(last_in=e.at, last_out=before.last_out)),
                   thoughts=thoughts, late=late, last_contact=e.at, glad=s.glad.delete(person),
                   pending=tuple(q for q in s.pending if not (q.origin == c.UNANSWERED and q.person == person)))


@ATTENTION.reducer(presence_c.DISCONNECTED, reads=[identity_c.PERSON])
def _left(s: AttentionState, e, cx) -> AttentionState:
    """La personne s'en va juste après sa réponse : la conversation s'est close, son dernier message n'attend
    plus rien (on se reparlera) — comme après « bonne nuit »."""
    person = cx.facts.get(identity_c.PERSON(e.data.handle)) or e.data.handle
    ex = s.exchanges.get(person)
    if ex is None or not ex.unanswered or ex.initiatives or ex.last_out <= ex.last_in:
        return s
    if e.at - ex.last_out > params(cx.params).closing_left_us:
        return s
    return replace(s, exchanges=s.exchanges.set(person, replace(ex, unanswered=False, asked=False, closed_at=e.at)))


#: l'indice d'un message de deux mots (« ok », « bof ») : il ne dit pas que ça va mieux
SHORT_CUE = "un message très court"
#: le ton est revenu quand il ne tombe pas plus bas que ça sous ce qu'elle attendait de la personne
TONE_BACK = 0.1


@ATTENTION.reducer(others_c.READ)
def _worried(s: AttentionState, e, cx) -> AttentionState:
    """Quelqu'un qui compte n'avait pas l'air comme d'habitude : ça lui reste
    en tête (une pensée, comme un échange qui marque). Un message où la
    personne a retrouvé son ton (pas deux mots, pas plus sombre que d'habitude)
    permettra, en lui répondant, d'alléger ce qui la concerne."""
    d = e.data
    if d.closing and d.person in s.exchanges:
        # « bonne nuit », « à demain » : la conversation se clôt ; y répondre n'attendra rien — et la clôture vaut
        # dès maintenant, même si elle ne répond pas (« [SILENCE] » après avoir déjà dit bonne nuit)
        s = replace(s, exchanges=s.exchanges.set(d.person, replace(s.exchanges[d.person], closing=True,
                                                                   closed_at=e.at)))
    if not d.concern:
        if d.valence >= 0 and d.valence >= d.expected - TONE_BACK and SHORT_CUE not in d.cues:
            return replace(s, eased=s.eased.set(d.person, e.at))
        return s
    p = params(cx.params)
    return _relational(s, d.person, Emotion.ANXIOUS.value, p.concern_intensity, d.message, c.CONCERN, e.at, p,
                       public=d.public)


@ATTENTION.reducer(memory_c.PROMISE_NOTICED)
def _promised(s: AttentionState, e, cx) -> AttentionState:
    """Une promesse datée : elle attend d'elle-même de la tenir."""
    d = e.data
    if d.due is None or not d.to:
        return s
    p = params(cx.params)
    return _expect(s, c.PROMISE, d.to, e.at, d.due + p.promise_grace_us, ref=e.seq)


@ATTENTION.reducer(memory_c.PROMISE_RESOLVED)
def _resolved(s: AttentionState, e, cx) -> AttentionState:
    """Tenue (ou abandonnée d'un commun accord) : plus rien à attendre, et la
    pensée d'une promesse manquée s'éteint — elle l'a fait."""
    promise = e.data.promise
    thoughts = s.thoughts
    for t in s.thoughts.values():
        if t.origin == c.PROMISE and t.source == promise:
            thoughts = thoughts.delete(t.id)
    return replace(s, expectations=s.expectations.delete(expectation_key(c.PROMISE, "", promise)), thoughts=thoughts,
                   pending=tuple(q for q in s.pending if not (q.origin == c.PROMISE and q.source == promise)))


@ATTENTION.reducer(memory_c.BELIEVED)
def _revised(s: AttentionState, e, cx) -> AttentionState:
    """Cesser de croire quelque chose coûte : une pensée de confusion. Changer d'avis elle-même (« au fond, je
    préfère les lasagnes ») n'est pas une confusion."""
    if e.data.replaces is None or e.data.about_self:
        return s
    p = params(cx.params)
    return replace(s, pending=(*s.pending, Pending(e.seq, c.REVISION, None, Emotion.CONFUSED.value,
                                                   p.revision_intensity, e.at, extra=e.data.replaces)))


@ATTENTION.reducer(goals_c.GOAL_CLOSED)
def _goal_closed(s: AttentionState, e, cx) -> AttentionState:
    """Ce qu'elle a mené à bout apaise la pensée d'où c'était venu (elle
    l'oublie parce qu'elle l'a fait, pas parce que le temps a passé). Bloquer
    n'apaise rien : l'ancienne pensée reste ce qu'elle est, et le blocage en
    devient une autre."""
    d = e.data
    p = params(cx.params)
    source = int(d.source.split(":", 1)[1]) if d.source.startswith("thought:") and d.source[8:].isdigit() else None
    if source is not None and source in s.thoughts and d.status == goals_c.ACHIEVED:
        s = replace(s, thoughts=s.thoughts.delete(source))
    if d.status != goals_c.STUCK or d.kind == goals_c.REMINDER:
        return s
    pending = Pending(e.seq, c.BLOCKED, d.owner, Emotion.FRUSTRATED.value, p.blocked_intensity, e.at,
                      ref=d.title.ref or "", about=tuple(d.about), sensitivity=d.sensitivity)
    return replace(s, pending=(*s.pending, pending))


@ATTENTION.reducer(projects_c.OBJECTIVE_CLOSED)
def _project_blocked(s: AttentionState, e, cx) -> AttentionState:
    """Bloquer sur un objectif d'un projet où c'est elle qui travaille devient une pensée (« Je bloque
    sur… ») ; en mode impersonnel, ce n'est pas elle : rien (ADR 0031)."""
    d = e.data
    if d.mode != projects_c.PERSONA or d.status != projects_c.BLOCKED:
        return s
    p = params(cx.params)
    pending = Pending(e.seq, c.BLOCKED, d.owner, Emotion.FRUSTRATED.value, p.blocked_intensity, e.at,
                      ref=d.title.ref or "", about=tuple(d.about), sensitivity=d.sensitivity)
    return replace(s, pending=(*s.pending, pending))


@ATTENTION.reducer(rt.EPISODE_STARTED, reads=[identity_c.PERSON])
def _reaching_out(s: AttentionState, e, cx) -> AttentionState:
    """Prendre la parole d'elle-même : on retient pourquoi (une salutation
    n'attend pas de réponse) ; relancer quelqu'un qui manque : on attend son retour."""
    d = e.data
    if d.kind != Kind.INITIATIVE or not d.target:
        return s
    openings = s.openings.set(e.correlation, d.reason)
    if len(openings) > 16:  # des épisodes qui n'ont jamais parlé (abstention, supplantés)
        openings = FrozenDict(sorted(openings.items())[-16:])  # les identifiants d'épisode sont chronologiques
    s = replace(s, openings=openings)
    if not {social_c.RECONTACT, social_c.CHAT, social_c.REKINDLE} & set(d.reason.split(",")):
        return s
    return _expect(s, c.RETURN, cx.facts.get(identity_c.PERSON(d.target)), e.at, None)


@ATTENTION.reducer(c.THOUGHT_BORN)
def _born(s: AttentionState, e, cx) -> AttentionState:
    d = e.data
    p = params(cx.params)
    thought = Thought(e.seq, d.text.ref or "", d.emotion, d.intensity, e.at, e.at, d.origin, tuple(d.about),
                      d.sensitivity, d.bundle, d.source)
    s = replace(s, thoughts=_alive(replace(s, thoughts=s.thoughts.set(e.seq, thought)), e.at, p),
                pending=tuple(q for q in s.pending if q.source != d.source or q.origin != d.origin))
    if d.origin == c.MISSING and d.about:
        s = _expect(s, c.RETURN, d.about[0], e.at, None)
        missing = s.missing.set(d.about[0], e.at)
        if len(missing) > MISSING_KEPT:
            missing = FrozenDict(sorted(missing.items(), key=lambda kv: (kv[1], kv[0]))[-MISSING_KEPT:])
        s = replace(s, missing=missing)
    if d.origin == c.ALONE:
        s = replace(s, alone_at=e.at)
    if d.origin == c.UNANSWERED and d.about and d.about[0] in s.exchanges:
        s = replace(s, exchanges=s.exchanges.set(d.about[0], replace(s.exchanges[d.about[0]], felt=True)))
    if d.origin == c.EXCHANGE and len(d.about) == 1 and d.emotion in GLAD:
        # un bel échange : le lendemain, elle pourra avoir envie de lui en reparler (les anciens s'oublient)
        glad = FrozenDict({k: v for k, v in s.glad.items() if e.at - v[1] < p.glad_until_us})
        s = replace(s, glad=glad.set(d.about[0], (e.seq, e.at)))
    return s


@ATTENTION.reducer(shapes=[c.Signal])
def _signaled(s: AttentionState, e, cx) -> AttentionState:
    """Une source extérieure lui signale quelque chose : elle le remarquera
    (la veille dose l'émotion et l'habituation)."""
    d = e.data
    p = params(cx.params)
    heard = SignalHeard(e.seq, d.source, d.kind, d.summary.ref or "", d.pertinence, d.emotion, d.intensity,
                        tuple(d.about), d.sensitivity, d.bundle, e.at)
    return replace(s, signals=(*s.signals, heard)[-p.signals_kept:])


@ATTENTION.reducer(c.NOTICED)
def _noticed(s: AttentionState, e, cx) -> AttentionState:
    d = e.data
    p = params(cx.params)
    heard = tuple(h for h in s.heard if e.at - h.at < p.habituation_window_us)
    pertinence = next((x.pertinence for x in s.signals if x.seq == d.signal), 0.0)
    return replace(s, signals=tuple(x for x in s.signals if x.seq != d.signal),
                   heard=(*heard, Heard(e.at, d.source, d.kind, d.intensity, d.signal, pertinence, d.weight))[-64:])


def habituation(s: AttentionState, source: str, kind: str, now: int, p: AttentionParams,
                extra: tuple[Heard, ...] = ()) -> tuple[float, float]:
    """(poids, émotion encore permise) pour un signal de cette source, maintenant."""
    recent = [h for h in (*s.heard, *extra) if now - h.at < p.habituation_window_us]
    n = sum(1 for h in recent if h.source == source and h.kind == kind)
    used = sum(h.intensity for h in recent if h.source == source)
    return max(p.habituation_floor, p.habituation_factor ** n), max(0.0, p.dose_cap - used)


@ATTENTION.reducer(c.TOUCHED)
def _touched(s: AttentionState, e, cx) -> AttentionState:
    """La personne a reparlé de ce qui la concernait : lui répondre l'allègera."""
    return replace(s, eased=s.eased.set(e.data.person, e.at)) if e.data.thoughts else s


@ATTENTION.reducer(c.DIGESTED)
def _digested(s: AttentionState, e, cx) -> AttentionState:
    thoughts = s.thoughts
    for item in e.data.items:
        t = thoughts.get(item.thought)
        if t is not None:
            thoughts = thoughts.set(t.id, replace(t, intensity=item.after, touched_at=e.at, emotion=item.emotion))
    return replace(s, thoughts=thoughts, digested_night=e.data.night)


@ATTENTION.reducer(c.DWELT)
def _dwelt(s: AttentionState, e, cx) -> AttentionState:
    return replace(s, dwelt_at=e.at)


@ATTENTION.reducer(c.EXPECTATION_MET)
def _met(s: AttentionState, e, cx) -> AttentionState:
    d = e.data
    s = replace(s, expectations=s.expectations.delete(expectation_key(d.kind, d.person, d.ref)))
    if d.kind == c.PROMISE:
        return s
    if d.kind == c.REPLY:
        return replace(s, ignored=0, late=s.late.delete(d.person))
    # quelqu'un qui manquait revient : le manque s'éteint (parce qu'il est là, pas parce que le temps a passé)
    thoughts = s.thoughts
    for t in s.thoughts.values():
        if t.origin == c.MISSING and d.person in t.about:
            thoughts = thoughts.delete(t.id)
    return replace(s, thoughts=thoughts)


@ATTENTION.reducer(c.EXPECTATION_MISSED)
def _missed(s: AttentionState, e, cx) -> AttentionState:
    d = e.data
    p = params(cx.params)
    key = expectation_key(d.kind, d.person, d.ref)
    expected = s.expectations.get(key)
    s = replace(s, expectations=s.expectations.delete(key))
    if d.kind == c.PROMISE and d.ref is not None:
        # sa parole pas tenue : ça la travaille (le texte de la promesse, jamais inventé)
        return replace(s, pending=(*s.pending, Pending(d.ref, c.PROMISE, d.person, Emotion.EMBARRASSED.value,
                                                       p.promise_intensity, e.at)))
    if d.kind != c.REPLY:
        return s
    # une réponse tardive compte encore, mais pas indéfiniment : trois fois le délai attendu — par messagerie, on
    # répond quand on y pense : dans les jours qui suivent
    window = (expected.deadline - expected.since) if expected is not None and expected.deadline else p.reply_window_us
    until = round(window * p.late_reply_factor)
    if expected is not None and privacy.is_messaging(expected.channel):
        until = max(until, p.late_reply_message_us)
    late = Late(d.since, d.since + until)
    ex = s.exchanges.get(d.person) or Exchange()
    s = replace(s, ignored=s.ignored + 1, late=s.late.set(d.person, late),
                exchanges=s.exchanges.set(d.person, replace(ex, ignored=ex.ignored + 1)))
    return _felt_ignored(s, d.person, e.seq, e.at, p)


def _felt_ignored(s: AttentionState, person: str, source: int, at: int, p: AttentionParams) -> AttentionState:
    """Ignorée par quelqu'un : une pensée (« … ne m'a pas répondu »), une seule
    par personne — une deuxième initiative sans réponse la ravive."""
    alive = [t for t in _alive(s, at, p).values() if t.origin == c.UNANSWERED and person in t.about]
    if alive:
        t = min(alive, key=lambda t: t.id)
        stronger = max(current(t, at, p), p.unanswered_intensity)
        return replace(s, thoughts=s.thoughts.set(t.id, replace(t, intensity=stronger, touched_at=at)))
    if any(q.origin == c.UNANSWERED and q.person == person for q in s.pending) or p.unanswered_intensity <= 0:
        return s
    return replace(s, pending=(*s.pending, Pending(source, c.UNANSWERED, person, Emotion.SAD.value,
                                                   p.unanswered_intensity, at)))


# ── Faits ─────────────────────────────────────────────────────────────────


def readings(s: AttentionState, now: int, p: AttentionParams) -> tuple[c.ThoughtReading, ...]:
    out = [c.ThoughtReading(t.id, t.text_ref, t.emotion, round(current(t, now, p), 4), t.origin, t.about,
                            t.sensitivity, t.born_at, t.bundle)
           for t in s.thoughts.values() if current(t, now, p) >= p.fade_below]
    return tuple(sorted(out, key=lambda r: (-r.intensity, r.id)))


@ATTENTION.fact(c.THOUGHTS)
def _thoughts(s: AttentionState, cx) -> tuple[c.ThoughtReading, ...]:
    return readings(s, cx.now, params(cx.params))


@ATTENTION.fact(c.IGNORED)
def _ignored(s: AttentionState, cx) -> int:
    return s.ignored


def awaiting(s: AttentionState, person: str) -> c.AwaitingReading:
    ex = s.exchanges.get(person) or Exchange()
    return c.AwaitingReading(person, ex.last_in, ex.last_out, ex.asked, ex.owed, ex.initiatives,
                             ex.last_initiative_at, ex.ignored, ex.unanswered, ex.closed_at)


@ATTENTION.fact(c.AWAITING)
def _awaiting(s: AttentionState, cx, person: str) -> c.AwaitingReading:
    return awaiting(s, person)


# ── Ce que ses événements font ressentir ──────────────────────────────────


def _emotion(name: str) -> Emotion:
    return A.emotion_of(name) or Emotion.THINKING


#: les pensées qui disent un état déjà ressenti ailleurs : « Personne ne m'a parlé depuis hier » met des mots sur
#: le vide que ``needs`` lui fait déjà sentir (``needs.felt``, borné) — le ressentir une seconde fois serait compter
#: deux fois la même solitude (S07, ADR 0058)
NAMES_A_FEELING = frozenset({c.ALONE})


@ATTENTION.appraisal(c.THOUGHT_BORN)
def _birth_felt(e, cx) -> Appraisal | None:
    if e.data.origin in NAMES_A_FEELING:
        return None
    p = params(cx.params)
    return Appraisal(_emotion(e.data.emotion), e.data.intensity * p.birth_appraisal_factor, reason=e.data.origin,
                     relational=e.data.origin == c.EXCHANGE)


@ATTENTION.appraisal(c.NOTICED)
def _noticed_felt(e, cx) -> Appraisal | None:
    """Ce qu'elle remarque la touche un peu — déjà dosé, habitué."""
    d = e.data
    if not d.emotion or d.intensity <= 0:
        return None
    return Appraisal(_emotion(d.emotion), d.intensity, reason=d.source)


@ATTENTION.appraisal(c.DWELT)
def _dwell_felt(e, cx) -> Appraisal | None:
    if e.data.origin in NAMES_A_FEELING:
        return None
    p = params(cx.params)
    return Appraisal(_emotion(e.data.emotion), e.data.intensity * p.dwell_factor, reason="elle y repense",
                     relational=e.data.origin == c.EXCHANGE)


@ATTENTION.appraisal(c.EXPECTATION_MET)
def _met_felt(e, cx) -> list[Appraisal]:
    if e.data.kind == c.RETURN:
        # enfin : de la joie, pour elle et envers la personne revenue
        return [Appraisal(Emotion.HAPPY, 0.4, reason="retour"),
                Appraisal(Emotion.HAPPY, 0.4, toward=e.data.person, reason="retour")]
    return [Appraisal(Emotion.RELIEVED, 0.25, reason="réponse")]


# Ce que la digestion a apaisé se ressent au réveil, pas en pleine nuit (une teinte posée à 3 h
# s'efface avant le matin) : c'est ``self.woke_with`` qui le porte (ADR 0036).


@ATTENTION.appraisal(c.EXPECTATION_MISSED)
def _missed_felt(e, cx) -> Appraisal | None:
    if e.data.kind == c.PROMISE:
        return Appraisal(Emotion.EMBARRASSED, 0.3, reason="promesse non tenue")
    return Appraisal(Emotion.SAD, 0.15, reason="sans réponse") if e.data.kind == c.REPLY else None

