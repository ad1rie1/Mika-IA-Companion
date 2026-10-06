"""La faculté ``memory`` : sa tranche, ses paramètres, ses réducteurs, ses faits.

La tranche ne garde que des résumés (point de contrôle, messages pas encore
relus, promesses en cours et ce qu'elle a fait pour les tenir, moments de la
vie des autres à venir ou tout juste passés, situations en cours (et quand la
personne a dit qu'elles étaient finies), dates qui reviennent chaque année (jamais
évincées par l'âge : le fait ``LIFE_EVENTS`` les rend à leur prochaine
occurrence), la dernière
fois que quelque chose de grave a touché chacun) ; les
éléments retenus vivent dans la projection T0 ``memory_items`` et leurs
vecteurs dans l'index (un cache).

Qu'un moment ait été repris ne se déduit plus de ce qu'elle avait sous les
yeux : c'est un jugement enregistré (``moment_followed``, ``life.py``).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field, replace
from datetime import datetime, time
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import expression as expression_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import others as others_c
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR, MINUTE, instant, local
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict
from mika.vocab.affect import Declared, Emotion, emotion_of, valence
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable

PENDING_CAP = 500
#: les moments de la vie des autres gardés dans la tranche, au plus
EVENTS_CAP = 300
#: … et, à part, les dates qui reviennent chaque année : elles ne vieillissent pas, et les anniversaires de tout son
#: cercle ne chassent pas l'entretien de jeudi
YEARLY_CAP = 300
#: les initiatives en cours qui tiennent une promesse (corrélation → promesse), au plus
KEEPING_KEPT = 16
#: le sujet d'une initiative qui tient une promesse : ``promise:<id>``
PROMISE_SUBJECT = "promise:"
#: les personnes que quelque chose de grave a touchées, retenues au plus (les plus récentes)
HARD_KEPT = 64


def promise_of(subject: str | None) -> int | None:
    """La promesse que tient une initiative (``promise:12``), ou ``None``."""
    if not subject or not subject.startswith(PROMISE_SUBJECT) or not subject[len(PROMISE_SUBJECT):].isdigit():
        return None
    return int(subject[len(PROMISE_SUBJECT):])


class MemoryParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # consolidation : une fenêtre mûre (assez de messages) ou calme (plus rien depuis un moment)
    min_messages: Annotated[int, Knob(
        label="Messages pour une relecture", group="Consolidation", lo=1, hi=50,
        help="La conversation se relit (le modèle en tire souvenirs, croyances et promesses) dès qu'autant de "
             "messages de personnes attendent. Plus bas : davantage d'appels, sur des fenêtres plus courtes.")] = 6
    quiet_us: Annotated[int, Knob(
        label="Calme avant relecture", group="Consolidation", lo=MINUTE, hi=2 * HOUR,
        help="Sinon, elle se relit après ce délai sans nouveau message. Une question qui attend encore sa "
             "réponse n'est jamais relue sans elle.")] = 5 * MINUTE
    max_window: Annotated[int, Knob(
        label="Messages lus par relecture", group="Consolidation", lo=10, hi=300,
        help="Au plus autant de messages par appel d'extraction ; le reste attend la relecture suivante. Trop "
             "grand : un appel long et coûteux ; trop petit : un retard qui s'accumule.")] = 80
    retry_us: Annotated[int, Knob(
        label="Délai avant de réessayer", group="Consolidation", lo=MINUTE, hi=6 * HOUR,
        help="Après un appel d'extraction qui échoue (panne, réponse illisible), pas de nouvel essai avant ce "
             "délai : aucune rafale d'appels quand le fournisseur ne répond pas.")] = 10 * MINUTE
    max_attempts: Annotated[int, Knob(
        label="Essais avant d'abandonner", group="Consolidation", lo=1, hi=10,
        help="Après autant de réponses illisibles sur la même fenêtre, elle est abandonnée et le point de "
             "contrôle avance : ces messages ne deviendront jamais des souvenirs.")] = 3
    dedup_similarity: Annotated[float, Knob(
        label="Seuil de doublon", group="Consolidation", lo=0.5, hi=1.0, step=0.01,
        help="Un souvenir ou une croyance extraits au moins aussi proches (similarité des vecteurs) d'un élément "
             "existant le renforcent au lieu d'en créer un jumeau. Trop bas : des faits distincts fusionnent.")] = 0.92
    # rappel
    recall_k: Annotated[int, Knob(
        label="Candidats cherchés", group="Rappel", lo=5, hi=200,
        help="Combien d'éléments (souvenirs, croyances, échanges passés) la recherche vectorielle remonte à chaque "
             "tour de conversation, avant le tri.")] = 40
    recall_floor: Annotated[float, Knob(
        label="Pertinence minimale", group="Rappel", lo=0.0, hi=1.5, step=0.01,
        help="Sous cette pertinence avec la conversation (la similarité des vecteurs, plus jusqu'à 0,35 quand "
             "l'élément contient les mots qui portent le sujet), un candidat ne revient pas tout seul ; la recherche "
             "délibérée (outil memory_search) tolère 20 % de moins. Trop bas : des souvenirs au hasard à chaque "
             "tour.")] = 0.45
    recall_margin: Annotated[float, Knob(
        label="Écart au meilleur candidat", group="Rappel", lo=0.0, hi=1.5, step=0.01,
        help="Quand un élément colle de très près à la conversation, ce qui en reste à plus de cet écart (en "
             "pertinence) ne revient pas : le rappel suit le sujet. Trop serré : deux souvenirs du même sujet, l'un "
             "mot pour mot et l'autre en partie, ne reviennent plus ensemble.")] = 0.5
    context_messages: Annotated[int, Knob(
        label="Messages qui orientent le rappel", group="Rappel", lo=1, hi=6,
        help="Le rappel cherche d'après le dernier message, et aussi d'après les quelques précédents de la même "
             "personne (ou du salon) : « et lui, il va mieux ? » se comprend avec ce qui précède.")] = 3
    strong_cue: Annotated[float, Knob(
        label="Indice qui réveille", group="Rappel", lo=0.3, hi=1.5, step=0.01,
        help="Un souvenir endormi revient quand même si la conversation lui est au moins aussi pertinente (ses "
             "mots, presque tous) : on n'oublie pas vraiment, il faut juste le bon indice.")] = 0.75
    max_souvenirs: Annotated[int, Knob(
        label="Souvenirs rappelés", group="Rappel", lo=0, hi=30,
        help="Au plus autant de souvenirs montrés au modèle à chaque tour, les mieux classés d'abord (pertinence, "
             "ce qu'il en reste, la personne en face).")] = 5
    max_beliefs: Annotated[int, Knob(
        label="Croyances rappelées", group="Rappel", lo=0, hi=40,
        help="Au plus autant de croyances (ce qu'elle sait) montrées au modèle à chaque tour.")] = 8
    max_chunks: Annotated[int, Knob(
        label="Échanges passés rappelés", group="Rappel", lo=0, hi=15,
        help="Au plus autant d'extraits d'échanges anciens, cités mot pour mot, parmi ceux que la personne a le "
             "droit d'entendre.")] = 3
    max_unsaid: Annotated[int, Knob(
        label="Ce qu'elle sait sans pouvoir le dire", group="Rappel", lo=0, hi=5,
        help="Quand la conversation touche ce qu'une autre personne lui a confié et qui ne se dit pas ici, elle "
             "sait au moins qu'elle sait — une ligne vague, sans rien du contenu (« Alice t'a confié des choses "
             "en privé : ce n'est pas à toi d'en parler »), au plus pour autant de personnes. Jamais en public.")] = 2
    max_promises: Annotated[int, Knob(
        label="Promesses montrées", group="Promesses", lo=1, hi=20,
        help="Au plus autant de promesses en cours dans « ce que tu lui as promis », les plus proches de leur "
             "échéance d'abord.")] = 5
    promise_horizon_days: Annotated[float, Knob(
        label="Échéance d'une promesse vague (jours)", group="Promesses", lo=1, hi=90,
        help="Une promesse faite sans date (« je te dirai ») reçoit cette échéance : passée, elle y repense, "
             "puis l'abandonne si rien ne vient.")] = 14.0
    promise_drop_days: Annotated[float, Knob(
        label="Abandon après l'échéance (jours)", group="Promesses", lo=0, hi=60,
        help="Une promesse ni tenue ni abandonnée s'oublie (abandonnée) ce temps après son échéance : rien ne "
             "reste dû pour toujours.")] = 7.0
    # tenir parole au moment dit : c'est dû (``agency.OWED``)
    promise_lead_us: Annotated[int, Knob(
        label="Tenir une promesse : un peu avant l'heure dite", group="Tenir parole", lo=0, hi=3 * HOUR,
        help="« Je te demanderai jeudi à 20 h comment ça s'est passé » : l'envie de le faire monte à partir de ce "
             "délai avant l'heure dite, et elle le fait d'elle-même — c'est dû, comme un rappel : ni budget, ni "
             "retenue, ni rancune. Une promesse sans date ne déclenche rien.")] = 30 * MINUTE
    promise_day_start_min: Annotated[int, Knob(
        label="Une promesse pour un jour : à partir de", group="Tenir parole", lo=0, hi=24 * 60,
        help="« Je t'envoie ça jeudi » (un jour sans heure) se tient dans la journée, à partir de cette heure "
             "locale (minutes depuis minuit) et avant le soir.")] = 10 * 60
    promise_day_end_min: Annotated[int, Knob(
        label="Une promesse pour un jour : son échéance", group="Tenir parole", lo=12 * 60, hi=24 * 60 - 1,
        help="… et son échéance est cette heure-là (minutes depuis minuit) : l'envie de la tenir est pleine à "
             "mi-chemin entre le début ci-dessus et cette heure, et elle peut encore la tenir « au plus tard après "
             "l'heure » au-delà — quelqu'un qu'elle ne voit que le soir l'entend quand même. En conversation, ce "
             "jour-là, c'est le moment de le faire dès le matin.")] = 20 * 60
    keep_evidence: Annotated[float, Knob(
        label="Tenir une promesse : preuve pleine", group="Tenir parole", lo=0.0, hi=12.0, step=0.5,
        help="La preuve (log-odds) à l'heure dite ; elle monte depuis 2 au début de la fenêtre (elle le fait à un "
             "moment ou à un autre de la fenêtre, pas à heure fixe). Au-dessus du seuil d'initiative (9), elle "
             "écrit seule.")] = 10.5
    keep_late_us: Annotated[int, Knob(
        label="Tenir une promesse : au plus tard après l'heure", group="Tenir parole", lo=0, hi=DAY,
        help="Passé ce délai après l'heure dite, elle ne le fait plus d'elle-même : elle sait qu'elle ne l'a pas "
             "fait (une pensée, après le délai de grâce de l'attention).")] = 2 * HOUR
    keep_attempts: Annotated[int, Knob(
        label="Tenir une promesse : essais", group="Tenir parole", lo=1, hi=5,
        help="Après autant d'essais qui n'ont rien dit (un silence choisi, une panne), elle ne le refait plus "
             "d'elle-même. Une initiative devancée (la personne a écrit) n'est pas un essai.")] = 2
    keep_retry_us: Annotated[int, Knob(
        label="Tenir une promesse : délai entre essais", group="Tenir parole", lo=MINUTE, hi=2 * HOUR,
        help="Après un essai qui n'a rien dit, pas de nouvel essai avant ce délai (multiplié par le nombre "
             "d'essais).")] = 10 * MINUTE
    event_ahead_days: Annotated[float, Knob(
        label="Moments à venir montrés (jours)", group="La vie des autres", lo=1, hi=60,
        help="Ce qui va arriver à la personne à qui elle parle (un entretien, un départ) lui revient quand c'est "
             "dans moins de tant de jours.")] = 7.0
    event_recent_days: Annotated[float, Knob(
        label="Moments passés à suivre (jours)", group="La vie des autres", lo=1, hi=30,
        help="Un moment passé depuis moins de tant de jours, dont elles n'ont pas encore reparlé (ni elle en lui "
             "demandant, ni la personne en le racontant), lui revient pour qu'elle demande comment ça s'est passé ; "
             "au-delà, il n'est plus suivi.")] = 3.0
    situation_days: Annotated[float, Knob(
        label="Situations en cours suivies (jours)", group="La vie des autres", lo=1, hi=60,
        help="Une situation qui dure dans la vie de quelqu'un (« mon chat Moustache est malade ») lui revient, "
             "pour qu'elle en prenne des nouvelles, pendant tant de jours après qu'elle a commencé.")] = 14.0
    situation_reask_days: Annotated[float, Knob(
        label="Situation : redemander après (jours)", group="La vie des autres", lo=0.5, hi=30, step=0.5,
        help="Après en avoir reparlé, elle ne redemande pas des nouvelles d'une situation avant tant de jours.")] = 3.0
    hard_days: Annotated[float, Knob(
        label="Quelque chose de grave : pendant (jours)", group="La vie des autres", lo=0, hi=30, step=0.5,
        help="Après un deuil, une rupture, une maladie (ce qu'elle a lu de grave dans ses messages, ou ce qui l'a "
             "profondément attristée pour la personne), les moments banals de sa vie se taisent pendant tant de "
             "jours — ni « comment s'est passé ton dentiste ? », ni « bonne chance » pour une course — et ce qui "
             "compte passe après des nouvelles d'elle. 0 : jamais.")] = 5.0
    hard_reply_from: Annotated[float, Knob(
        label="Grave : ce qui l'attriste au moins à ce point", group="La vie des autres", lo=0.3, hi=1.0, step=0.05,
        help="Une réponse, en privé, où elle se dit triste au moins à ce point (sa balise d'émotion) dit que ce "
             "que la personne lui a confié est grave, même sans un mot qui le nomme (« Pixel est parti »).")] = 0.75
    # oubli : l'importance s'estompe à la lecture, jamais par balayage
    dormant: Annotated[float, Knob(
        label="Seuil d'endormissement", group="Oubli", lo=0.0, hi=0.5, step=0.01,
        help="Un souvenir dont l'importance restante passe sous ce seuil ne revient plus tout seul. Il n'est pas "
             "effacé : la recherche délibérée le retrouve encore.")] = 0.03
    base_half_life_days: Annotated[float, Knob(
        label="Demi-vie de base (jours)", group="Oubli", lo=0.25, hi=90,
        help="La demi-vie d'un souvenir sans importance ; s'y ajoute la part due à l'importance (ci-dessous), et "
             "chaque rappel l'allonge de 25 % (jusqu'à quatre).")] = 3.0
    importance_half_life_days: Annotated[float, Knob(
        label="Demi-vie due à l'importance (jours)", group="Oubli", lo=0, hi=365,
        help="Ce qu'un souvenir d'importance 1 gagne de demi-vie en plus de la base (proportionnellement en "
             "dessous) : ce qui a compté s'efface bien plus lentement.")] = 27.0
    belief_half_life_days: Annotated[float, Knob(
        label="Demi-vie d'une croyance (jours)", group="Oubli", lo=7, hi=3650,
        help="La confiance d'une croyance diminue de moitié en ce temps si rien ne la renforce.")] = 180.0
    self_half_life_days: Annotated[float, Knob(
        label="Demi-vie de ce qu'elle raconte d'elle (jours)", group="Oubli", lo=0.5, hi=60,
        help="Ce qu'elle improvise sur sa vie (« j'ai ressorti mon fer à souder ») est gardé comme une note "
             "anodine qui s'efface en ce temps : assez pour ne pas se contredire d'un jour à l'autre, pas "
             "assez pour s'inventer un passé.")] = 3.0
    self_durable_half_life_days: Annotated[float, Knob(
        label="Demi-vie de ses goûts et avis (jours)", group="Oubli", lo=30, hi=3650,
        help="Ce qu'elle a dit de ce qu'elle aime, de ce qu'elle pense, de sa vie (« mon plat préféré, c'est les "
             "ramen ») tient bien plus longtemps : on ne change pas de plat préféré toutes les semaines. Quand elle "
             "change d'avis, la nouvelle croyance remplace l'ancienne.")] = 365.0
    bond_memory_gain: Annotated[float, Knob(
        label="Ce qui dure avec quelqu'un à qui elle tient", group="Oubli", lo=0.0, hi=5.0, step=0.1,
        help="Un souvenir vécu avec quelqu'un à qui elle tient s'endort moins vite : sa demi-vie est multipliée par "
             "1 + ce gain × l'attachement (une proche compte au moins pour 1, une amie pour ½). 0 : comme avec "
             "n'importe qui.")] = 2.0
    landmark_importance: Annotated[float, Knob(
        label="Importance d'un moment marquant", group="Oubli", lo=0.5, hi=1.0, step=0.01,
        help="Un souvenir au moins aussi important ne s'endort jamais tout à fait (ci-dessous) : un deuil, un "
             "mariage restent à portée.")] = 0.9
    landmark_floor: Annotated[float, Knob(
        label="Ce qui reste d'un moment marquant", group="Oubli", lo=0.0, hi=0.5, step=0.01,
        help="Ce qu'il en reste ne descend jamais sous cette valeur ; au-dessus du seuil d'endormissement, il "
             "peut toujours revenir tout seul.")] = 0.05
    min_belief_confidence: Annotated[float, Knob(
        label="Confiance minimale", group="Oubli", lo=0.0, hi=0.9, step=0.01,
        help="Une croyance dont la confiance restante passe sous ce seuil ne revient plus toute seule "
             "(elle reste trouvable par la recherche délibérée).")] = 0.3
    # au rappel : la personne en face, l'anti-répétition
    person_boost: Annotated[float, Knob(
        label="Bonus de la personne en face", group="Rappel", lo=1.0, hi=3.0, step=0.05,
        help="Au rappel, un élément qui concerne la personne en face pèse autant de fois plus. Il ne fait "
             "qu'avancer ce qui est déjà admissible : il n'ouvre rien.")] = 1.25
    repetition_us: Annotated[int, Knob(
        label="Fenêtre anti-répétition", group="Rappel", lo=0, hi=12 * HOUR,
        help="Un élément déjà rappelé depuis moins longtemps que ça est pénalisé (ci-dessous), pour que le rappel "
             "tourne au lieu de resservir les mêmes souvenirs à chaque tour.")] = 30 * MINUTE
    repetition_penalty: Annotated[float, Knob(
        label="Pénalité de répétition", group="Rappel", lo=0.0, hi=1.0, step=0.05,
        help="Le poids d'un élément rappelé récemment est multiplié par ce facteur (1 : aucune pénalité).")] = 0.6
    max_self_said: Annotated[int, Knob(
        label="Ce qu'elle a déjà dit d'elle", group="Rappel", lo=0, hi=8,
        help="Quand on lui parle d'elle (« c'est quoi ton plat préféré ? »), au plus autant de ce qu'elle a déjà "
             "dit de ses goûts, de ses avis, de sa vie lui revient (« CE QUE TU AS DÉJÀ DIT DE TOI ») — les plus "
             "proches du message : elle ne se contredit pas.")] = 3
    person_recall_days: Annotated[float, Knob(
        label="Sa vie à elle : depuis (jours)", group="Rappel", lo=1, hi=90,
        help="Au premier mot d'une conversation (« salut ! »), ou quand elle écrit d'elle-même à quelqu'un, ce que "
             "cette personne lui a raconté de sa vie depuis moins de tant de jours lui revient — « et Moustache, il "
             "va mieux ? » —, sa fiche seulement si elle est ouverte. Une politesse ne réveille rien d'autre.")] = 14.0
    max_person_items: Annotated[int, Knob(
        label="Sa vie à elle : au plus", group="Rappel", lo=0, hi=10,
        help="Au plus autant de ces éléments (les plus importants et les plus frais d'abord).")] = 3
    # la nuit
    night_after_sleep_us: Annotated[int, Knob(
        label="Tri de la nuit après", group="La nuit", lo=0, hi=10 * HOUR,
        help="Une fois par nuit, ce temps après l'endormissement, elle fusionne les souvenirs presque identiques "
             "de la journée. Plus long que son sommeil : pas de tri cette nuit-là.")] = 3 * HOUR
    night_merge_similarity: Annotated[float, Knob(
        label="Similarité pour fusionner", group="La nuit", lo=0.5, hi=1.0, step=0.01,
        help="Deux souvenirs du jour au moins aussi proches se fusionnent pendant le tri. Trop bas : des "
             "moments distincts se confondent.")] = 0.9
    night_max_merges: Annotated[int, Knob(
        label="Fusions par nuit au plus", group="La nuit", lo=0, hi=200,
        help="Au plus autant de fusions par nuit (0 : aucun tri).")] = 20


@dataclass(frozen=True, slots=True)
class Reflection:
    """Une pensée restée forte, digérée cette nuit : un souvenir à écrire."""

    thought: int
    text_ref: str
    about: tuple[str, ...]
    sensitivity: int
    emotion: str


@dataclass(frozen=True, slots=True)
class Keeping:
    """Ce qu'elle a fait pour tenir une promesse : les essais qui n'ont rien dit, et quand réessayer."""

    attempts: int = 0
    retry_at: int = 0


@dataclass(frozen=True, slots=True)
class MemoryState:
    checkpoint: int = 0
    #: messages de personnes pas encore relus (``seq``), les plus récents
    pending: tuple[int, ...] = field(default_factory=tuple)
    #: parmi eux, ceux qui ne lui étaient pas adressés (un salon : on parle entre soi)
    unaddressed: tuple[int, ...] = field(default_factory=tuple)
    last_message_at: int = 0
    items: int = 0
    chunks: int = 0
    promises: FrozenDict[int, c.PendingPromise] = field(default_factory=FrozenDict)
    #: tenir une promesse au moment dit : les initiatives en cours (corrélation → (promesse, départ)), les essais,
    #: et les promesses qu'elle vient de tenir en le disant (le règlement suit, par ``memory.promises``)
    keeping: FrozenDict[str, tuple[int, int]] = field(default_factory=FrozenDict)
    tries: FrozenDict[int, Keeping] = field(default_factory=FrozenDict)
    kept: tuple[int, ...] = ()
    #: les moments de la vie des autres, à venir ou passés depuis peu ; les situations en cours
    events: FrozenDict[int, c.LifeEvent] = field(default_factory=FrozenDict)
    #: personne → la dernière fois que quelque chose de grave l'a touchée (un deuil, une rupture…)
    hard: FrozenDict[str, int] = field(default_factory=FrozenDict)
    reflections: tuple[Reflection, ...] = ()
    sorted_night: str = ""
    #: la dernière relecture journalisée (``seq``, instant), et les fenêtres
    #: abandonnées après trop d'échecs (combien, la dernière) : pour l'inspecteur
    consolidated_seq: int = 0
    consolidated_at: int = 0
    given_up: int = 0
    given_up_seq: int = 0


#: v4 : un moment repris est un jugement enregistré (``moment_followed``), plus « elle l'avait sous les yeux » ;
#: les situations en cours ; tenir une promesse au moment dit.
#: v5 : l'importance d'un moment, ce qui se fête, et ce qui touche gravement quelqu'un (ADR 0052).
#: v6 : une situation en cours prend fin quand la personne dit qu'elle est finie (``situation_ended``).
#: v7 : une date qui revient chaque année (``yearly``) n'est jamais évincée par l'âge, et a son propre plafond.
MEMORY = Faculty("memory", state=MemoryState, init=lambda p: MemoryState(), params=MemoryParams, state_version=7)
MEMORY.declare(*c.ALL)


def params(p: MemoryParams | None) -> MemoryParams:
    return p if p is not None else MemoryParams()


@MEMORY.reducer(rt.PERCEPTION_RECEIVED)
def _perceived(s: MemoryState, e, cx) -> MemoryState:
    unaddressed = s.unaddressed if e.data.addressed else (*s.unaddressed, e.seq)[-PENDING_CAP:]
    return replace(s, pending=(*s.pending, e.seq)[-PENDING_CAP:], unaddressed=unaddressed, last_message_at=e.at)


def _hard(s: MemoryState, person: str, at: int) -> MemoryState:
    """Quelque chose de grave touche cette personne, à cet instant."""
    if not is_identifiable(person) or s.hard.get(person, 0) >= at:
        return s
    hard = s.hard.set(person, at)
    if len(hard) > HARD_KEPT:
        hard = FrozenDict(sorted(hard.items(), key=lambda kv: (kv[1], kv[0]))[-HARD_KEPT:])
    return replace(s, hard=hard)


@MEMORY.reducer(rt.UTTERANCE, reads=[identity_c.PERSON])
def _uttered(s: MemoryState, e, cx) -> MemoryState:
    """Ce qu'elle dit : un échange de plus à indexer — et, quand c'est l'initiative qui tient une promesse, la
    promesse est tenue (dite au moment dit ; ``memory.promises`` la règle). Qu'elle ait repris un moment de la vie
    de la personne ne se lit pas ici : c'est un jugement sur ses mots (``life.py``). Quand elle répond, en privé,
    profondément triste pour quelqu'un, ce qu'il lui a confié est grave (« Pixel est parti » : aucun mot ne le
    nomme, sa peine le dit)."""
    d = e.data
    if not d.visible:
        return s
    keeping = s.keeping.get(e.correlation)
    if keeping is not None:
        s = replace(s, keeping=s.keeping.delete(e.correlation))
        if keeping[0] in s.promises and keeping[0] not in s.kept:
            s = replace(s, kept=(*s.kept, keeping[0]))
    if d.kind == Kind.REPLY and d.target and d.room is None and is_identifiable(d.target):
        declared = Declared.decode(d.annotation(expression_c.EMOTION_ANNOTATION))
        if declared is not None and declared.emotion == Emotion.SAD \
                and declared.intensity >= params(cx.params).hard_reply_from:
            s = _hard(s, cx.facts.get(identity_c.PERSON(d.target)) or d.target, e.at)
    return replace(s, last_message_at=e.at, chunks=s.chunks + (1 if d.target and d.reply_to else 0))


@MEMORY.reducer(others_c.READ)
def _read_grave(s: MemoryState, e, cx) -> MemoryState:
    """Ce qu'elle a lu de grave dans un message (un deuil, une maladie, une rupture, une perte de travail, des mots
    de détresse) touche la personne qui l'a écrit."""
    return _hard(s, e.data.person, e.at) if e.data.grave else s


@MEMORY.reducer(rt.EPISODE_STARTED)
def _started(s: MemoryState, e, cx) -> MemoryState:
    """Une initiative part pour tenir une promesse (son sujet : ``promise:<id>``)."""
    d = e.data
    promise = promise_of(d.subject) if d.kind == Kind.INITIATIVE else None
    if promise is None or promise not in s.promises:
        return s
    keeping = s.keeping.set(e.correlation, (promise, e.at))
    if len(keeping) > KEEPING_KEPT:  # des épisodes jamais réglés : les identifiants sont chronologiques
        keeping = FrozenDict(sorted(keeping.items())[-KEEPING_KEPT:])
    return replace(s, keeping=keeping)


@MEMORY.reducer(rt.EPISODE_ENDED, reads=[agency_c.RENOUNCED])
def _ended(s: MemoryState, e, cx) -> MemoryState:
    """L'initiative qui devait tenir une promesse finit sans l'avoir dite : un silence choisi, une panne sont un
    essai (réessayer plus tard, pas indéfiniment) ; devancée, interrompue, ou un murmure sans suite (elle s'est
    ravisée), ce n'en est pas un (``agency.tried``)."""
    keeping = s.keeping.get(e.correlation)
    if keeping is None:
        return s
    s = replace(s, keeping=s.keeping.delete(e.correlation))
    promise, started = keeping
    if promise not in s.promises:
        return s
    p = params(cx.params)
    t = s.tries.get(promise) or Keeping()
    renounced = cx.facts.get(agency_c.RENOUNCED(e.data.target)) if e.data.target else 0
    if agency_c.tried(e.data.outcome, started, renounced):
        n = t.attempts + 1
        t = Keeping(n, e.at + p.keep_retry_us * n)
    else:
        t = replace(t, retry_at=e.at + p.keep_retry_us)
    return replace(s, tries=s.tries.set(promise, t))


@MEMORY.reducer(c.MOMENT_FOLLOWED)
def _followed(s: MemoryState, e, cx) -> MemoryState:
    """Un moment repris en mots, une fois passé : elle lui en a demandé des nouvelles, ou la personne lui en a
    parlé d'elle-même."""
    ev = s.events.get(e.data.event)
    return replace(s, events=s.events.set(ev.id, replace(ev, followed_at=e.at))) if ev is not None else s


@MEMORY.reducer(c.SITUATION_ENDED)
def _situation_ended(s: MemoryState, e, cx) -> MemoryState:
    """Une situation qui durait est finie, de la bouche de la personne (« on a fini le déménagement », « on a dû
    l'endormir ») : elle reste notée, mais n'est plus « en ce moment ». La première fin dite compte."""
    ev = s.events.get(e.data.event)
    if ev is None or not ev.ongoing or ev.ended_at:
        return s
    return replace(s, events=s.events.set(ev.id, replace(ev, ended_at=e.at)))


@MEMORY.reducer(c.CONSOLIDATED)
def _consolidated(s: MemoryState, e, cx) -> MemoryState:
    upto = max(s.checkpoint, e.data.upto)
    s = replace(s, checkpoint=upto, pending=tuple(q for q in s.pending if q > upto),
                unaddressed=tuple(q for q in s.unaddressed if q > upto), consolidated_seq=e.seq, consolidated_at=e.at)
    return replace(s, given_up=s.given_up + 1, given_up_seq=e.seq) if e.data.failed else s


@MEMORY.reducer(c.EVENT_NOTED)
def _noted(s: MemoryState, e, cx) -> MemoryState:
    """Un moment de la vie de quelqu'un : gardé tant qu'il est à venir ou passé
    depuis peu ; une situation en cours, quelques semaines ; une date qui
    revient chaque année, toujours ; les plus anciens partent d'abord. Le même
    moment renoté à la même date (la personne l'a dit elle-même après un tiers)
    reste repris s'il l'était ; une date qui change repart de zéro. Une
    situation finie, renotée, reste finie."""
    d = e.data
    p = params(cx.params)
    keep_until = e.at - round(p.event_recent_days * DAY)
    keep_ongoing = e.at - round(p.situation_days * DAY)
    old = s.events.get(d.replaces) if d.replaces is not None else None
    followed = old.followed_at if old is not None and old.when == d.when else 0
    ended = old.ended_at if old is not None and old.ongoing and d.ongoing else 0
    events = s.events.delete(d.replaces) if d.replaces is not None else s.events
    events = events.set(e.seq, c.LifeEvent(e.seq, tuple(d.about), d.when, d.all_day, d.sensitivity,
                                           tuple(d.told_by), d.text.ref or "", d.secret, followed_at=followed,
                                           ongoing=d.ongoing, importance=d.importance, festive=d.festive,
                                           ended_at=ended, yearly=d.yearly and not d.ongoing))
    stale = [ev.id for ev in events.values()
             if not ev.yearly and ev.when < (keep_ongoing if ev.ongoing else keep_until)]
    for i in stale:
        events = events.delete(i)
    once = [ev for ev in events.values() if not ev.yearly]
    if len(once) > EVENTS_CAP:
        for ev in sorted(once, key=lambda x: (x.when, x.id))[: len(once) - EVENTS_CAP]:
            events = events.delete(ev.id)
    yearly = [ev for ev in events.values() if ev.yearly]
    if len(yearly) > YEARLY_CAP:  # la date d'une occurrence ne dit pas son âge : les plus anciennement notées partent
        for ev in sorted(yearly, key=lambda x: x.id)[: len(yearly) - YEARLY_CAP]:
            events = events.delete(ev.id)
    return replace(s, items=s.items + 1, events=events)


@MEMORY.reducer(c.REMEMBERED, c.BELIEVED)
def _retained(s: MemoryState, e, cx) -> MemoryState:
    """Un élément retenu de plus. Un souvenir marquant et douloureux (un deuil vécu avec quelqu'un) dit aussi que
    quelque chose de grave touche les personnes qu'il concerne."""
    d = e.data
    reflections = tuple(r for r in s.reflections if d.call_id != f"réflexion:{r.thought}")
    s = replace(s, items=s.items + 1, reflections=reflections)
    if e.type.name == c.REMEMBERED.name and d.importance >= params(cx.params).landmark_importance:
        felt = emotion_of(d.emotion)
        if felt is not None and valence(felt) < 0:
            for person in d.about:
                s = _hard(s, person, e.at)
    return s


@MEMORY.reducer(attention_c.DIGESTED)
def _digested(s: MemoryState, e, cx) -> MemoryState:
    """Ce qui est resté fort toute la journée, repensé la nuit, devient un souvenir."""
    new = tuple(Reflection(i.thought, i.text_ref, tuple(i.about), i.sensitivity, i.emotion)
                for i in e.data.items if i.reflective and i.text_ref)
    return replace(s, reflections=(*s.reflections, *new)[-20:]) if new else s


@MEMORY.reducer(c.NIGHT_SORTED)
def _sorted(s: MemoryState, e, cx) -> MemoryState:
    return replace(s, sorted_night=e.data.night)


@MEMORY.reducer(c.PROMISE_NOTICED)
def _promised(s: MemoryState, e, cx) -> MemoryState:
    """Une promesse sans échéance (le journal d'avant l'horizon des promesses
    vagues) reçoit celle d'une promesse vague : rien n'est dû pour toujours."""
    due, implicit = e.data.due, e.data.implicit_due
    if due is None:
        due, implicit = e.at + round(params(cx.params).promise_horizon_days * DAY), True
    promise = c.PendingPromise(e.seq, e.data.to, due, e.at, implicit, all_day=e.data.all_day and not implicit)
    return replace(s, items=s.items + 1, promises=s.promises.set(e.seq, promise))


@MEMORY.reducer(c.PROMISE_RESOLVED)
def _resolved(s: MemoryState, e, cx) -> MemoryState:
    promise = e.data.promise
    return replace(s, promises=s.promises.delete(promise), tries=s.tries.delete(promise),
                   kept=tuple(k for k in s.kept if k != promise))


@MEMORY.fact(c.CHECKPOINT)
def _checkpoint(s: MemoryState, cx) -> int:
    return s.checkpoint


def _speaks_for(cx, key: str, person: str) -> bool:
    """Une clé notée alors (une adresse, ``name:…``) désigne cette personne maintenant : une adresse reliée depuis à
    quelqu'un, un nom qu'un opérateur a relié à une personne parlent pour elle (ADR 0035, 0048)."""
    return key == person or (cx.facts.get(identity_c.PERSON(key)) or key) == person


@MEMORY.fact(c.PROMISES_TO, reads=[identity_c.PERSON])
def _promises_to(s: MemoryState, cx, person: str) -> tuple[c.PendingPromise, ...]:
    return tuple(p for p in s.promises.values() if _speaks_for(cx, p.to, person))


def day_of(t: int, tz: ZoneInfo) -> int:
    """Minuit (heure locale) du jour de cet instant."""
    return instant(datetime.combine(local(t, tz).date(), time(0, 0), tzinfo=tz))


def occurrence(ev: c.LifeEvent, now: int, tz: ZoneInfo, p: MemoryParams) -> c.LifeEvent:
    """Ce moment tel qu'il se présente à ``now`` : lui-même — sauf une date qui revient chaque année, passée depuis
    plus de ``event_recent_days`` : alors sa prochaine occurrence, le même jour à la même heure (un 29 février, le 28
    les autres années), jamais avant celle qui a été notée. L'avoir repris l'an dernier, ce n'est pas l'avoir repris
    cette année : ``followed_at`` d'avant le début de cette occurrence-là repart de zéro."""
    keep = round(p.event_recent_days * DAY)
    if not ev.yearly or now <= ev.when + keep:
        return ev
    first = local(ev.when, tz)
    for year in range(local(now, tz).year - 1, local(now, tz).year + 2):
        try:
            moment = first.replace(year=year)
        except ValueError:  # un 29 février, une année qui n'en a pas
            moment = first.replace(year=year, day=28)
        at = instant(moment)
        if at > ev.when and now <= at + keep:
            return replace(ev, when=at, followed_at=ev.followed_at if ev.followed_at >= day_of(at, tz) else 0)
    return ev


def events_at(s: MemoryState, now: int, tz: ZoneInfo, p: MemoryParams) -> list[c.LifeEvent]:
    """Les moments notés, tels qu'ils se présentent à ``now`` (une date qui revient chaque année : sa prochaine
    occurrence)."""
    return [occurrence(ev, now, tz, p) for ev in s.events.values()]


@MEMORY.fact(c.LIFE_EVENTS, reads=[identity_c.PERSON])
def _life_events(s: MemoryState, cx, person: str) -> tuple[c.LifeEvent, ...]:
    p = params(cx.params)
    events = (occurrence(ev, cx.now, cx.tz, p) for ev in s.events.values()
              if any(_speaks_for(cx, k, person) for k in ev.about))
    return tuple(sorted(events, key=lambda ev: (ev.when, ev.id)))


def hard_since(s: MemoryState, keys: Collection[str], now: int, p: MemoryParams) -> int:
    """Quand quelque chose de grave a touché cette personne (l'une des clés qui la désignent), s'il y a moins de
    ``hard_days`` ; 0 sinon."""
    at = max((s.hard.get(k, 0) for k in keys), default=0)
    return at if at and 0 <= now - at <= round(p.hard_days * DAY) else 0


def heavy_day(s: MemoryState, cx, person: str, p: MemoryParams) -> int:
    """Le début de la journée, quand c'est aujourd'hui que revient une date lourde de cette personne (la date d'un
    deuil) qu'elle lui a confiée elle-même ; 0 sinon. Ce qu'un tiers en a dit ne fait pas d'elle quelqu'un de touché
    aux yeux de Mika."""
    today = day_of(cx.now, cx.tz)
    for ev in s.events.values():
        if not ev.yearly or not ev.told_by or not any(_speaks_for(cx, k, person) for k in ev.about) \
                or not all(_speaks_for(cx, t, person) for t in ev.told_by):
            continue
        this_year = occurrence(ev, cx.now, cx.tz, p)
        if c.heavy_date(this_year) and day_of(this_year.when, cx.tz) == today:
            return today
    return 0


@MEMORY.fact(c.HARD_TIMES, reads=[identity_c.PERSON])
def _hard_times(s: MemoryState, cx, person: str) -> int:
    p = params(cx.params)
    return max(hard_since(s, [k for k in s.hard if _speaks_for(cx, k, person)], cx.now, p),
               heavy_day(s, cx, person, p))
