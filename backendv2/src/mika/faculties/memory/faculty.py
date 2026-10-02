"""La faculté ``memory`` : sa tranche, ses paramètres, ses réducteurs, ses faits.

La tranche ne garde que des résumés (point de contrôle, messages pas encore
relus, promesses en cours, moments de la vie des autres à venir ou tout juste
passés) ; les éléments retenus vivent dans la projection T0 ``memory_items``
et leurs vecteurs dans l'index (un cache).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Annotated

from pydantic import BaseModel, ConfigDict

from mika.contracts import attention as attention_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict

PENDING_CAP = 500
#: les moments de la vie des autres gardés dans la tranche, au plus
EVENTS_CAP = 300


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
    event_ahead_days: Annotated[float, Knob(
        label="Moments à venir montrés (jours)", group="La vie des autres", lo=1, hi=60,
        help="Ce qui va arriver à la personne à qui elle parle (un entretien, un départ) lui revient quand c'est "
             "dans moins de tant de jours.")] = 7.0
    event_recent_days: Annotated[float, Knob(
        label="Moments passés à suivre (jours)", group="La vie des autres", lo=1, hi=30,
        help="Un moment passé depuis moins de tant de jours, dont elle n'a pas encore reparlé avec la personne, "
             "lui revient pour qu'elle demande comment ça s'est passé ; au-delà, il n'est plus suivi.")] = 3.0
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
    #: parmi eux, ceux qui ne lui étaient pas adressés (un salon : on parle entre soi)
    unaddressed: tuple[int, ...] = field(default_factory=tuple)
    last_message_at: int = 0
    items: int = 0
    chunks: int = 0
    promises: FrozenDict[int, c.PendingPromise] = field(default_factory=FrozenDict)
    #: les moments de la vie des autres, à venir ou passés depuis peu
    events: FrozenDict[int, c.LifeEvent] = field(default_factory=FrozenDict)
    reflections: tuple[Reflection, ...] = ()
    sorted_night: str = ""
    #: la dernière relecture journalisée (``seq``, instant), et les fenêtres
    #: abandonnées après trop d'échecs (combien, la dernière) : pour l'inspecteur
    consolidated_seq: int = 0
    consolidated_at: int = 0
    given_up: int = 0
    given_up_seq: int = 0


MEMORY = Faculty("memory", state=MemoryState, init=lambda p: MemoryState(), params=MemoryParams, state_version=3)
MEMORY.declare(*c.ALL)


def params(p: MemoryParams | None) -> MemoryParams:
    return p if p is not None else MemoryParams()


@MEMORY.reducer(rt.PERCEPTION_RECEIVED)
def _perceived(s: MemoryState, e, cx) -> MemoryState:
    unaddressed = s.unaddressed if e.data.addressed else (*s.unaddressed, e.seq)[-PENDING_CAP:]
    return replace(s, pending=(*s.pending, e.seq)[-PENDING_CAP:], unaddressed=unaddressed, last_message_at=e.at)


@MEMORY.reducer(rt.UTTERANCE, reads=[identity_c.PERSON])
def _uttered(s: MemoryState, e, cx) -> MemoryState:
    d = e.data
    if not d.visible:
        return s
    s = replace(s, last_message_at=e.at, chunks=s.chunks + (1 if d.target and d.reply_to else 0))
    return _followed(s, d, e.at, cx) if d.target and s.events else s


def _followed(s: MemoryState, d, at: int, cx) -> MemoryState:
    """Un moment passé qu'elle avait sous les yeux en parlant à la personne
    qu'il concerne : elle a pu lui en demander des nouvelles."""
    shown = {int(p.split(":", 1)[1]) for p in d.provenance if p.startswith("memory:") and p[7:].isdigit()}
    hits = [ev for i in shown if (ev := s.events.get(i)) is not None and ev.when <= at]
    if not hits:
        return s
    person = cx.facts.get(identity_c.PERSON(d.target)) or d.target
    events = s.events
    for ev in hits:
        if person in ev.about:
            events = events.set(ev.id, replace(ev, followed_at=at))
    return replace(s, events=events)


@MEMORY.reducer(c.CONSOLIDATED)
def _consolidated(s: MemoryState, e, cx) -> MemoryState:
    upto = max(s.checkpoint, e.data.upto)
    s = replace(s, checkpoint=upto, pending=tuple(q for q in s.pending if q > upto),
                unaddressed=tuple(q for q in s.unaddressed if q > upto), consolidated_seq=e.seq, consolidated_at=e.at)
    return replace(s, given_up=s.given_up + 1, given_up_seq=e.seq) if e.data.failed else s


@MEMORY.reducer(c.EVENT_NOTED)
def _noted(s: MemoryState, e, cx) -> MemoryState:
    """Un moment de la vie de quelqu'un : gardé tant qu'il est à venir ou passé
    depuis peu ; les plus anciens partent d'abord."""
    d = e.data
    p = params(cx.params)
    keep_until = e.at - round(p.event_recent_days * DAY)
    events = s.events.delete(d.replaces) if d.replaces is not None else s.events
    events = events.set(e.seq, c.LifeEvent(e.seq, tuple(d.about), d.when, d.all_day, d.sensitivity,
                                           tuple(d.told_by), d.text.ref or "", d.secret))
    stale = [ev.id for ev in events.values() if ev.when < keep_until]
    for i in stale:
        events = events.delete(i)
    if len(events) > EVENTS_CAP:
        for ev in sorted(events.values(), key=lambda x: (x.when, x.id))[: len(events) - EVENTS_CAP]:
            events = events.delete(ev.id)
    return replace(s, items=s.items + 1, events=events)


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
    """Une promesse sans échéance (le journal d'avant l'horizon des promesses
    vagues) reçoit celle d'une promesse vague : rien n'est dû pour toujours."""
    due, implicit = e.data.due, e.data.implicit_due
    if due is None:
        due, implicit = e.at + round(params(cx.params).promise_horizon_days * DAY), True
    promise = c.PendingPromise(e.seq, e.data.to, due, e.at, implicit)
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


@MEMORY.fact(c.LIFE_EVENTS)
def _life_events(s: MemoryState, cx, person: str) -> tuple[c.LifeEvent, ...]:
    return tuple(sorted((ev for ev in s.events.values() if person in ev.about), key=lambda ev: (ev.when, ev.id)))
