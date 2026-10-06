"""Contrat de ``memory`` : ce qu'elle garde de ce qu'elle a vécu.

Quatre sortes de choses retenues, chacune un événement dont le ``seq`` est
l'identifiant (stable, référencé par la provenance des énoncés) :

- un **souvenir** (``remembered``) : un épisode vécu, à la première personne ;
- une **croyance** (``believed``) : un fait sur quelqu'un, sur le monde ou sur
  elle-même, avec sa confiance, son origine (on me l'a dit, je l'ai vu, j'en
  déduis) et qui l'a dit — la même chose redite par la même personne ne la
  rend pas plus sûre ; dite par une autre, si ;
- une **promesse** (``promise_noticed``) qu'elle a faite à quelqu'un ;
- un **événement de la vie de quelqu'un** (``event_noted``) : ce qui va lui
  arriver (« un entretien chez Ubisoft jeudi »), pour qu'elle y pense au bon
  moment — et lui en demande des nouvelles après ; ou une **situation en
  cours** (« son chat Moustache est malade », ``ongoing``), dont on prend des
  nouvelles tant qu'elle dure — et qui **prend fin** quand la personne dit
  qu'elle est finie (``situation_ended`` : « on a fini le déménagement »).

Qu'un moment ait été **repris** (``moment_followed``) est un jugement
enregistré : ce qu'elle a dit, ou ce que la personne lui en a dit elle-même,
le reprend en mots, une fois le moment passé — pas seulement « il était sous
ses yeux ». Une promesse **datée** se tient au moment dit
(``KEEP_PROMISE``, une raison **due**, ``agency.OWED``) : dite à l'heure, elle
est tenue (``promise_resolved``, ``by=KEPT_BY``) ; jamais la veille. Un rappel
demandé existe une fois : programmé (``goals``), il remplace la promesse
(``by=REMINDER_BY``).

Un moment dit ce qu'il pèse (``importance`` : ``IMPORTANT_MOMENT`` et plus, il
compte) et s'il se fête (``festive`` : un anniversaire se souhaite le jour
même). ``HARD_TIMES`` dit quand quelque chose de grave a touché quelqu'un ces
derniers jours : le banal de sa vie se tait (ADR 0052). Un moment peut revenir
**chaque année** (``yearly`` : un anniversaire, la date d'un deuil) : elle s'en
souvient sans qu'on le lui redise, et le jour d'une date lourde
(``heavy_date``) est un jour difficile.

Chacune porte sa sensibilité (``vocab.privacy.Sensitivity``), les messages
d'où elle vient, **qui le lui a confié** (``told_by`` : les auteurs de ces
messages) et **qui l'a entendu** (``heard_by`` : les personnes de la
conversation, un salon en compte plusieurs). Ce qu'une personne a demandé
explicitement de ne répéter à personne est un **secret** (``secret``) : il ne
ressort que devant celle qui l'a confié. Les textes sont des ``Content`` :
effaçables par l'oubli, qui atteint aussi ce qu'une personne a confié.

Une croyance peut n'appartenir qu'à elle et à la personne qu'elle concerne
(``between_us`` : comment elle l'appelle, le surnom qu'elle lui donne, leurs
blagues) : la colonne ``between_us`` de ``memory_items`` le dit à qui lit le
lien (``social``, son registre avec une amie). Jamais devant une inconnue ni en
public quand ça s'est dit en privé (ADR 0055).
"""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey

OWNER = "memory"

TOLD = "told"  # quelqu'un le lui a dit
OBSERVED = "observed"  # elle l'a vu, vécu
INFERRED = "inferred"  # elle en déduit

HONORED = "honored"
DROPPED = "dropped"
#: qui règle une promesse restée sans nouvelles bien après son échéance
EXPIRED_BY = "échéance"
#: qui règle une promesse qu'elle a tenue au moment dit, en le disant (une initiative ``KEEP_PROMISE``)
KEPT_BY = "parole"
#: qui règle une promesse qu'un rappel programmé (``goals``, l'outil ``goal_remind``) porte désormais : un rappel
#: demandé existe une fois et une seule (ADR 0052)
REMINDER_BY = "rappel"

#: À partir de cette importance, un moment de la vie de quelqu'un compte (un entretien, un examen, un départ, une
#: opération) : envers une amie, c'est la première chose qu'on demande après. En dessous (un rendez-vous de
#: routine, une sortie), on peut en reparler si ça vient — et, quand quelque chose de grave la touche, ça se tait.
IMPORTANT_MOMENT = 0.7
#: Une date qui revient chaque année sans se fêter, et qui pèse au moins autant (la date d'un deuil), est une **date
#: lourde** : ce jour-là, chaque année, quelque chose de grave la touche (``HARD_TIMES``) — ni fête, ni « comment ça
#: s'est passé ? ».
HEAVY_DATE = 0.9

#: Raison de preuve d'initiative : tenir une promesse datée au moment dit (« je te demanderai jeudi soir comment
#: ça s'est passé » : jeudi soir, elle le demande). C'est **dû** (``agency.OWED``), jamais une relance.
KEEP_PROMISE = "keep_promise"

SOUVENIR = "souvenir"
BELIEF = "belief"
PROMISE = "promise"
EVENT = "event"
CHUNK = "chunk"
#: un échange dans un salon (un groupe) : retrouvé dans ce salon, jamais en privé (ADR 0059)
ROOM_CHUNK = "room_chunk"


class Remembered(Payload):
    text: Content
    about: tuple[str, ...] = ()
    sensitivity: int = 1
    importance: float = 0.5
    emotion: str | None = None
    sources: tuple[int, ...] = ()
    call_id: str = ""
    #: qui le lui a confié (les auteurs des messages sources) ; vide : elle l'a vécu, observé
    told_by: tuple[str, ...] = ()
    #: qui était là quand ça s'est dit (la personne d'un fil privé, les présents d'un salon)
    heard_by: tuple[str, ...] = ()
    #: « dis-le à personne » : ne ressort que devant qui l'a confié
    secret: bool = False


class Believed(Payload):
    text: Content
    about: tuple[str, ...] = ()
    sensitivity: int = 1
    importance: float = 0.5
    confidence: float = 0.7
    origin: str = TOLD
    source: str | None = None
    replaces: int | None = None
    sources: tuple[int, ...] = ()
    call_id: str = ""
    told_by: tuple[str, ...] = ()
    heard_by: tuple[str, ...] = ()
    secret: bool = False
    #: ce qu'elle a raconté d'elle-même (sa vie de tous les jours) : une note
    #: anodine, de peu d'importance, qui s'efface en quelques jours — assez pour
    #: ne pas se contredire d'un jour à l'autre
    about_self: bool = False
    #: … sauf ce qui la définit : un goût, un avis, un fait de sa vie (« les ramen, mon plat préféré ») — elle
    #: s'en souvient longtemps, et quand elle change d'avis, la nouvelle croyance remplace l'ancienne
    durable: bool = False
    #: ce qui n'appartient qu'à elle et à la personne (``about``) : comment elle l'appelle (« Sam m'appelle
    #: Mikachu »), le surnom qu'elle lui donne, leurs blagues, leurs expressions — de première main (ADR 0055)
    between_us: bool = False


class Reinforced(Payload):
    """Ce qui était déjà retenu revient : il s'estompe moins vite. Une croyance
    corroborée (redite par quelqu'un qui ne l'avait pas encore dite) gagne en
    confiance. Ce qui revient peut être plus sensible qu'avant (la sensibilité
    garde la plus haute), concerner d'autres personnes, avoir d'autres
    confidents ou devenir un secret (les ensembles s'unissent) ; ``replaces``
    remplace une croyance contredite par celle qu'on renforce."""

    item: int
    corroborated: bool = False
    source: str | None = None
    sources: tuple[int, ...] = ()
    sensitivity: int | None = None
    about: tuple[str, ...] = ()
    told_by: tuple[str, ...] = ()
    heard_by: tuple[str, ...] = ()
    secret: bool = False
    replaces: int | None = None
    #: ce qui revient se révèle n'appartenir qu'à elles deux (un surnom) : ça le reste (ADR 0055)
    between_us: bool = False


class PromiseNoticed(Payload):
    text: Content
    to: str
    due: int | None = None
    sensitivity: int = 1
    sources: tuple[int, ...] = ()
    call_id: str = ""
    #: l'échéance n'a pas été dite : c'est l'horizon au-delà duquel une
    #: promesse vague s'oublie (une pensée d'abord, puis l'abandon)
    implicit_due: bool = False
    #: un jour sans heure (« je t'envoie ça jeudi ») : elle peut le tenir dans la journée ; ``due`` est alors la
    #: fin de cette journée-là (18 h). Faux dans un journal plus ancien : l'échéance s'y lit comme une heure.
    all_day: bool = False


class PromiseResolved(Payload):
    promise: int
    status: str  # HONORED | DROPPED
    by: str = "consolidation"


class EventNoted(Payload):
    """Ce qui va arriver dans la vie de quelqu'un (« jeudi, son entretien chez
    Ubisoft ») : ``when`` l'instant (le jour seulement si ``all_day``). Une
    situation en cours (``ongoing`` : « son chat Moustache est malade ») a
    pour ``when`` le jour où elle a commencé, ou celui où elle l'a apprise."""

    text: Content
    when: int
    about: tuple[str, ...] = ()
    all_day: bool = True
    sensitivity: int = 2
    sources: tuple[int, ...] = ()
    told_by: tuple[str, ...] = ()
    heard_by: tuple[str, ...] = ()
    secret: bool = False
    #: un événement noté plus tôt dont la date a changé — ou, à la même date, qu'un tiers avait annoncé et que la
    #: personne a dit elle-même
    replaces: int | None = None
    call_id: str = ""
    #: une situation qui dure (un chat malade, un déménagement), pas un moment daté
    ongoing: bool = False
    #: ce que le moment pèse dans sa vie (``IMPORTANT_MOMENT`` et plus : il compte) ; dans un journal plus ancien,
    #: où rien ne le disait, il compte — comme alors
    importance: float = 0.7
    #: un moment qui se fête (un anniversaire, un mariage, une crémaillère) : il se souhaite le jour même, sans
    #: « bonne chance » la veille ni « comment ça s'est passé » le lendemain (faux dans un journal plus ancien)
    festive: bool = False
    #: une date qui revient chaque année (un anniversaire de naissance, de mariage, la date d'un deuil) : ``when`` est
    #: l'une de ses occurrences, ``LIFE_EVENTS`` rend la prochaine — sans qu'on la lui redise (faux dans un journal
    #: plus ancien : un moment n'arrivait qu'une fois)
    yearly: bool = False


class MomentFollowed(Payload):
    """Un moment de la vie de quelqu'un a été repris en mots, une fois passé :
    elle lui en a demandé des nouvelles, ou la personne lui en a parlé
    d'elle-même. Un jugement enregistré (des radicaux en commun avec le moment,
    son nom mis à part) — jamais « elle l'avait sous les yeux »."""

    event: int
    #: la personne qui en a parlé (sa clé), ou ``""`` quand c'est elle qui l'a repris
    by: str = ""


class SituationEnded(Payload):
    """Une situation qui durait dans la vie de quelqu'un (``event_noted``, ``ongoing``) est finie, de la bouche de
    la personne : « on a fini le déménagement », « on a dû l'endormir ce matin ». Le jugement de la relecture (comme
    une croyance qu'elle remplace), jamais des mots-clés : elle n'en parle plus au présent."""

    event: int
    call_id: str = ""


class Consolidated(Payload):
    """Le point de contrôle : tout ce qui précède ``upto`` a été relu."""

    upto: int
    produced: int = 0
    failed: bool = False
    call_id: str = ""
    model: str = ""


class NightSorted(Payload):
    """La nuit, les souvenirs du jour presque identiques à un autre s'y fondent
    (``(gardé, fondu)``) : le gardé prend la plus haute importance et la plus
    haute sensibilité des deux, et les personnes de l'un et de l'autre."""

    night: str
    merges: tuple[tuple[int, int], ...] = ()


#: un élément retenu se soumet à l'oubli de ceux qu'il concerne et de ceux qui l'ont confié
_SUBJECTS = ("about", "told_by")

REMEMBERED = event_type("memory.remembered", OWNER, Remembered, public=True, content=("text",), subjects=_SUBJECTS)
BELIEVED = event_type("memory.believed", OWNER, Believed, public=True, content=("text",), subjects=_SUBJECTS)
REINFORCED = event_type("memory.reinforced", OWNER, Reinforced, public=True)
PROMISE_NOTICED = event_type("memory.promise_noticed", OWNER, PromiseNoticed, public=True, content=("text",),
                             subjects=("to",))
PROMISE_RESOLVED = event_type("memory.promise_resolved", OWNER, PromiseResolved, public=True)
EVENT_NOTED = event_type("memory.event_noted", OWNER, EventNoted, public=True, content=("text",), subjects=_SUBJECTS)
MOMENT_FOLLOWED = event_type("memory.moment_followed", OWNER, MomentFollowed, public=True, subjects=("by",))
SITUATION_ENDED = event_type("memory.situation_ended", OWNER, SituationEnded, public=True)
CONSOLIDATED = event_type("memory.consolidated", OWNER, Consolidated, public=True)
NIGHT_SORTED = event_type("memory.night_sorted", OWNER, NightSorted, public=True)
ALL = (REMEMBERED, BELIEVED, REINFORCED, PROMISE_NOTICED, PROMISE_RESOLVED, EVENT_NOTED, MOMENT_FOLLOWED, SITUATION_ENDED,
       CONSOLIDATED, NIGHT_SORTED)


@dataclass(frozen=True, slots=True)
class PendingPromise:
    id: int
    to: str
    due: int | None
    at: int
    implicit_due: bool = False
    #: un jour sans heure : à tenir dans la journée
    all_day: bool = False


@dataclass(frozen=True, slots=True)
class LifeEvent:
    """Un moment de la vie de quelqu'un qu'elle a noté. ``text_ref`` : son
    texte (un contenu, effaçable) ; ``followed_at`` : la dernière fois qu'il a
    été repris en mots, une fois passé — elle lui en a demandé des nouvelles,
    ou la personne lui en a parlé (0 : jamais). ``ongoing`` : une situation qui
    dure (``when`` : depuis quand) ; ``ended_at`` : quand la personne a dit
    qu'elle était finie (0 : elle dure encore)."""

    id: int
    about: tuple[str, ...]
    when: int
    all_day: bool
    sensitivity: int
    told_by: tuple[str, ...]
    text_ref: str
    secret: bool = False
    followed_at: int = 0
    ongoing: bool = False
    #: ce qu'il pèse (``IMPORTANT_MOMENT`` et plus : il compte) ; un moment qui se fête (souhaité le jour même)
    importance: float = 0.7
    festive: bool = False
    #: une situation finie, de la bouche de la personne : elle n'est plus « en ce moment », ni à redemander
    ended_at: int = 0
    #: une date qui revient chaque année : ``LIFE_EVENTS`` la rend à sa prochaine occurrence (``when``), et
    #: ``followed_at`` à 0 tant que cette occurrence-là n'a pas été reprise
    yearly: bool = False


def heavy_date(ev: LifeEvent) -> bool:
    """Une date lourde : elle revient chaque année, ne se fête pas et pèse au moins ``HEAVY_DATE`` (la date d'un
    deuil)."""
    return ev.yearly and not ev.festive and ev.importance >= HEAVY_DATE


#: Le dernier message relu par la consolidation.
CHECKPOINT = FactKey("memory.checkpoint", type=int)
#: Les promesses en cours envers une personne.
PROMISES_TO = FactFamily("memory.promises_to", arg=str, type=tuple)
#: Les moments de la vie d'une personne qu'elle a notés — à venir, et passés
#: depuis peu (quelques jours) ; les situations en cours (deux semaines, une
#: situation finie gardée avec ``ended_at``) —, triés par date (``LifeEvent``). Forme close :
#: c'est au lecteur de comparer ``when`` à son instant (« c'était hier : et
#: alors, cet entretien ? »). Ce qui la concerne seulement : un moment qu'un
#: tiers a raconté porte ce tiers dans ``told_by``, à respecter avant d'en parler.
#: Une date qui revient chaque année y est toujours, à sa prochaine occurrence
#: (ou à celle qui vient de passer, quelques jours) : la seule lecture qui
#: dépende de l'instant.
LIFE_EVENTS = FactFamily("memory.life_events", arg=str, type=tuple)
#: Quelque chose de grave l'a touchée ces derniers jours (un deuil, une rupture, une maladie — ce qu'elle a lu de
#: grave dans ses messages, ou ce qui l'a elle-même profondément attristée pour elle) — ou c'est aujourd'hui que
#: revient une date lourde qu'elle a confiée elle-même (``heavy_date``) : l'instant, 0 sinon. Un
#: moment banal de sa vie se tait alors (ni « comment s'est passé ton dentiste ? » le lendemain d'un deuil, ni
#: « bonne chance » pour un rendez-vous de routine) ; ce qui compte passe après des nouvelles d'elle.
HARD_TIMES = FactFamily("memory.hard_times", arg=str, type=int, time_varying=True)

ITEMS_TABLE = "memory_items"
CHUNKS_TABLE = "memory_chunks"
#: Qui concerne chaque élément (``item``, ``person``) : les clés de ``memory_items.about``, une par ligne, indexées
#: par personne. « Ce qu'elle sait d'Alice » se lit sans parcourir toute la mémoire (ADR 0059) ; une clé telle
#: qu'elle a été notée (une adresse, ``name:…``), jamais résolue.
ABOUT_TABLE = "memory_about"
#: Combien de fois la mémoire a oublié quelqu'un (une ligne, ``n``) : ce qui dit à l'index des vecteurs, qui n'est
#: qu'un cache, de se rapprocher de ce qui reste — sans relire toute la mémoire à chaque énoncé (ADR 0059).
FORGETS_TABLE = "memory_forgets"
#: À qui elle a répété quoi (``item``, ``handle``, ``at``) : d'après la
#: provenance de ce qu'elle a dit. Ce qu'elle a raconté à Bob, Bob le sait.
TOLD_TABLE = "memory_told"
