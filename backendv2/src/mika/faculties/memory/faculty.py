"""La faculté ``memory`` : sa tranche, ses paramètres, ses réducteurs, ses faits.

La tranche ne garde que des résumés (point de contrôle, messages pas encore
relus, promesses en cours) ; les éléments retenus vivent dans la projection
T0 ``memory_items`` et leurs vecteurs dans l'index (un cache).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Annotated

from pydantic import BaseModel, ConfigDict

from mika.contracts import attention as attention_c
from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict

PENDING_CAP = 500


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
        label="Similarité minimale", group="Rappel", lo=0.0, hi=0.9, step=0.01,
        help="Sous cette similarité avec la conversation, un candidat ne revient pas tout seul ; la recherche "
             "délibérée (outil memory_search) tolère 20 % de moins.")] = 0.25
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
class MemoryState:
    checkpoint: int = 0
    #: messages de personnes pas encore relus (``seq``), les plus récents
    pending: tuple[int, ...] = field(default_factory=tuple)
    last_message_at: int = 0
    items: int = 0
    chunks: int = 0
    promises: FrozenDict[int, c.PendingPromise] = field(default_factory=FrozenDict)
    reflections: tuple[Reflection, ...] = ()
    sorted_night: str = ""
    #: la dernière relecture journalisée (``seq``, instant), et les fenêtres
    #: abandonnées après trop d'échecs (combien, la dernière) : pour l'inspecteur
    consolidated_seq: int = 0
    consolidated_at: int = 0
    given_up: int = 0
    given_up_seq: int = 0


MEMORY = Faculty("memory", state=MemoryState, init=lambda p: MemoryState(), params=MemoryParams, state_version=2)
MEMORY.declare(*c.ALL)


def params(p: MemoryParams | None) -> MemoryParams:
    return p if p is not None else MemoryParams()


@MEMORY.reducer(rt.PERCEPTION_RECEIVED)
def _perceived(s: MemoryState, e, cx) -> MemoryState:
    return replace(s, pending=(*s.pending, e.seq)[-PENDING_CAP:], last_message_at=e.at)


@MEMORY.reducer(rt.UTTERANCE)
def _uttered(s: MemoryState, e, cx) -> MemoryState:
    if not e.data.visible:
        return s
    return replace(s, last_message_at=e.at, chunks=s.chunks + (1 if e.data.target and e.data.reply_to else 0))


@MEMORY.reducer(c.CONSOLIDATED)
def _consolidated(s: MemoryState, e, cx) -> MemoryState:
    upto = max(s.checkpoint, e.data.upto)
    s = replace(s, checkpoint=upto, pending=tuple(q for q in s.pending if q > upto), consolidated_seq=e.seq,
                consolidated_at=e.at)
    return replace(s, given_up=s.given_up + 1, given_up_seq=e.seq) if e.data.failed else s


@MEMORY.reducer(c.REMEMBERED, c.BELIEVED)
def _retained(s: MemoryState, e, cx) -> MemoryState:
    reflections = tuple(r for r in s.reflections if e.data.call_id != f"réflexion:{r.thought}")
    return replace(s, items=s.items + 1, reflections=reflections)


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
    promise = c.PendingPromise(e.seq, e.data.to, e.data.due, e.at)
    return replace(s, items=s.items + 1, promises=s.promises.set(e.seq, promise))


@MEMORY.reducer(c.PROMISE_RESOLVED)
def _resolved(s: MemoryState, e, cx) -> MemoryState:
    return replace(s, promises=s.promises.delete(e.data.promise))


@MEMORY.fact(c.CHECKPOINT)
def _checkpoint(s: MemoryState, cx) -> int:
    return s.checkpoint


@MEMORY.fact(c.PROMISES_TO)
def _promises_to(s: MemoryState, cx, person: str) -> tuple[c.PendingPromise, ...]:
    return tuple(p for p in s.promises.values() if p.to == person)
