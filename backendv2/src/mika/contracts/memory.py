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
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, model_validator

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey
from mika.vocab.affect import facets
from mika.vocab.lineage import Restriction

OWNER = "memory"

TOLD = "told"  # quelqu'un le lui a dit
OBSERVED = "observed"  # elle l'a vu, vécu
INFERRED = "inferred"  # elle en déduit
#: l'origine d'un souvenir né d'un mensonge qu'elle a dit (colonne ``origin`` des éléments)
LIED = "lied"

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


#: Une restriction héritée (les sources d'une réflexion de nuit) : toutes doivent autoriser la diffusion. Le type
#: vit dans ``vocab.lineage`` (``Restriction``), partagé par tous les textes qui dérivent de ce qu'elle sait.
Disclosure = Restriction


#: Un ressenti à plusieurs facettes (ADR 0083) : des émotions parmi les 29 et leur intensité, de 0 à 1, la plus forte
#: d'abord — « colère 0,8, dégoût 0,4 ». Jugé par la relecture ; un ressenti d'un seul mot se lit comme une facette.
Feelings = Annotated[tuple[tuple[str, float], ...], BeforeValidator(facets)]


class Remembered(Payload):
    text: Content
    constraints: tuple[Disclosure, ...] = ()
    internal_only: bool = False
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
    #: un souvenir né d'un mensonge qu'elle a dit (``LIED``) : ce qu'elle a affirmé de faux, à qui
    lie: bool = False
    #: ce que la personne concernée en ressent, et ce qu'elle-même en ressent (``emotion`` : sa facette la plus
    #: forte), jugés par la relecture (ADR 0083)
    felt: Feelings = ()
    empathy: Feelings = ()

    @model_validator(mode="after")
    def _inherited_subjects(self):
        about = tuple(sorted({*self.about, *(key for rule in self.constraints for key in (*rule.about, *rule.told_by))}))
        if about != self.about:
            object.__setattr__(self, "about", about)
        return self


class Relation(Payload):
    subject: str
    other: str
    kind: Literal["friend", "family", "partner", "colleague", "acquaintance", "hostile"]
    status: Literal["active", "ended", "uncertain"] = "uncertain"


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
    #: Une affirmation rapportée n'est pas un fait vérifié ; une opinion appartient à son auteur.
    knowledge_kind: Literal["claim", "opinion", "preference", "hypothesis"] = "claim"
    holder: str | None = None
    relations: tuple[Relation, ...] = ()
    #: une croyance qu'elle contredit sans la remplacer (une source moins sûre) : les deux restent, elle doute
    #: (ADR 0081)
    contests: int | None = None
    #: de première main : la personne concernée qui parle d'elle-même, ou un témoin qui l'a vu
    first_hand: bool = False
    #: depuis quand c'est vrai (dit par la personne : « depuis lundi ») ; ``None`` : depuis qu'on le lui a dit
    as_of: int | None = None
    #: jusqu'à quand c'est vrai, quand c'est dit (« jusqu'à la fin du mois ») ; ``None`` : jusqu'à preuve du contraire
    valid_until: int | None = None
    #: ce que la personne concernée en ressent, et ce qu'elle-même en ressent — de l'empathie, selon ce qu'elle
    #: sait et pense (ADR 0083) ; jugés par la relecture, une des 29 émotions
    felt: Feelings = ()
    empathy: Feelings = ()

    @model_validator(mode="after")
    def _relation_subjects(self):
        # Les deux extrémités sont des sujets du contenu, même hors consolidation.
        about = tuple(sorted({*self.about, *(key for relation in self.relations
                                             for key in (relation.subject, relation.other))}))
        if about != self.about:
            object.__setattr__(self, "about", about)
        return self


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


class Attested(Payload):
    """Quelqu'un lui redit ce qu'elle croit déjà (ADR 0080) : un **témoignage** de plus sur la même proposition, avec
    ses propres droits — qui le lui a dit, qui l'a entendu, à quel point c'est sensible, si on lui a demandé de le
    garder pour soi. Ce que la même personne redit ne la rend pas plus sûre ; une autre, si. Elle peut en parler là
    où un témoignage le permet, en l'attribuant à ce témoin.

    ``restricts`` : rien de nouveau n'est dit, on lui demande la discrétion (« garde-le pour toi ») — sur le
    témoignage de qui la demande, ou sur **tous** (``everyone``) quand c'est la personne concernée qui la demande.
    Contrairement à un ancien renforcement (``reinforced``), un témoignage ouvre la diffusion que ses droits
    permettent."""

    item: int
    told_by: tuple[str, ...] = ()
    heard_by: tuple[str, ...] = ()
    source: str | None = None
    origin: str = TOLD
    confidence: float = 0.8
    sensitivity: int = 1
    secret: bool = False
    between_us: bool = False
    sources: tuple[int, ...] = ()
    about: tuple[str, ...] = ()
    relations: tuple[Relation, ...] = ()
    #: ce qu'elle redit d'elle-même (une note sur elle)
    about_self: bool = False
    restricts: bool = False
    everyone: bool = False
    #: une croyance que celle-ci remplace (la confirmer en la désignant comme remplacée la confirme) — ou, dite de
    #: nouveau après avoir été remplacée, celle qui l'avait remplacée (elle y revient, ADR 0081)
    replaces: int | None = None
    #: une croyance que ce témoignage conteste sans la remplacer (ADR 0081)
    contests: int | None = None
    first_hand: bool = False
    call_id: str = ""
    #: ce que la personne concernée en ressent, quand c'est elle qui le dit (ADR 0083) : son mot l'emporte
    felt: Feelings = ()


class Joined(Payload):
    """La nuit, des croyances dites pareil par des personnes différentes (des doublons d'avant les témoignages) se
    réunissent : ``(gardée, jointe)`` — la jointe devient un témoignage de la gardée."""

    night: str
    pairs: tuple[tuple[int, int], ...] = ()


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
    #: une situation finie qui recommence (« il est de nouveau malade ») : celle qu'elle rouvre — le même fil, une
    #: autre fois (ADR 0079)
    recurs: int | None = None
    #: ce que la personne en ressent (l'attendre avec joie, le redouter), et ce qu'elle-même en ressent pour elle
    #: (ADR 0083)
    felt: Feelings = ()
    empathy: Feelings = ()


class MomentFollowed(Payload):
    """Un moment de la vie de quelqu'un a été repris en mots, une fois passé :
    elle lui en a demandé des nouvelles, ou la personne lui en a parlé
    d'elle-même. Un jugement enregistré (des radicaux en commun avec le moment,
    son nom mis à part) — jamais « elle l'avait sous les yeux »."""

    event: int
    #: la personne qui en a parlé (sa clé), ou ``""`` quand c'est elle qui l'a repris
    by: str = ""
    #: le fil du moment (``LifeEvent.thread``) et l'instant de l'occurrence reprise : un moment redit entre-temps
    #: (la personne l'a dit elle-même) garde le suivi ; déplacé à une autre date, non (0 : un journal d'avant)
    thread: int = 0
    occurrence: int = 0


class SituationEnded(Payload):
    """Une situation qui durait dans la vie de quelqu'un (``event_noted``, ``ongoing``) est finie, de la bouche de
    la personne : « on a fini le déménagement », « on a dû l'endormir ce matin ». Le jugement de la relecture (comme
    une croyance qu'elle remplace), jamais des mots-clés : elle n'en parle plus au présent."""

    event: int
    call_id: str = ""


class ExtractionDeferred(Payload):
    """Un passage à reprendre ; les données du modèle restent effaçables."""

    key: int
    messages: tuple[int, ...] = ()
    #: parmi eux, ce qui ne lui était pas adressé (un salon) : la reprise le relit pareil
    aside: tuple[int, ...] = ()
    about: tuple[str, ...] = ()
    attempts: int = 1
    retry_at: int = 0
    status: Literal["queued", "review", "resolved"] = "queued"
    failure_code: Literal["invalid_output", "invalid_items", "provider_error", "budget_exceeded", "operator_retry"] = "invalid_output"
    detail: Content


class Consolidated(Payload):
    """Le point de contrôle : tout ce qui précède ``upto`` a été traité ou inscrit dans la file de reprises."""

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
BELIEVED = event_type("memory.believed", OWNER, Believed, public=True, content=("text",), subjects=(*_SUBJECTS, "holder"))
REINFORCED = event_type("memory.reinforced", OWNER, Reinforced, public=True)
PROMISE_NOTICED = event_type("memory.promise_noticed", OWNER, PromiseNoticed, public=True, content=("text",),
                             subjects=("to",))
PROMISE_RESOLVED = event_type("memory.promise_resolved", OWNER, PromiseResolved, public=True)
EVENT_NOTED = event_type("memory.event_noted", OWNER, EventNoted, public=True, content=("text",), subjects=_SUBJECTS)
MOMENT_FOLLOWED = event_type("memory.moment_followed", OWNER, MomentFollowed, public=True, subjects=("by",))
SITUATION_ENDED = event_type("memory.situation_ended", OWNER, SituationEnded, public=True)
EXTRACTION_DEFERRED = event_type("memory.extraction_deferred", OWNER, ExtractionDeferred, public=True,
                                 content=("detail",), subjects=("about",))
CONSOLIDATED = event_type("memory.consolidated", OWNER, Consolidated, public=True)
NIGHT_SORTED = event_type("memory.night_sorted", OWNER, NightSorted, public=True)
ATTESTED = event_type("memory.attested", OWNER, Attested, public=True, subjects=_SUBJECTS)
JOINED = event_type("memory.joined", OWNER, Joined, public=True)
ALL = (REMEMBERED, BELIEVED, REINFORCED, PROMISE_NOTICED, PROMISE_RESOLVED, EVENT_NOTED, MOMENT_FOLLOWED, SITUATION_ENDED,
       CONSOLIDATED, NIGHT_SORTED, EXTRACTION_DEFERRED, ATTESTED, JOINED)


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
    #: le fil du moment : le même quand il est reporté, redit, ou qu'une situation finie recommence — le
    #: premier ``seq`` qui l'a noté (0 : un moment d'avant, son propre ``id``). Ce qu'on en a dit se range sous lui.
    thread: int = 0
    #: la situation finie qu'il rouvre (0 : aucune)
    recurs: int = 0
    #: ce que la personne en ressent, ce qu'elle-même en ressent (ADR 0083) ; vide : rien de dit
    felt: tuple[tuple[str, float], ...] = ()
    empathy: tuple[tuple[str, float], ...] = ()

    @property
    def key(self) -> int:
        """Le fil du moment (son ``id`` dans un journal d'avant)."""
        return self.thread or self.id


def heavy_date(ev: LifeEvent) -> bool:
    """Une date lourde : elle revient chaque année, ne se fête pas et pèse au moins ``HEAVY_DATE`` (la date d'un
    deuil)."""
    return ev.yearly and not ev.festive and ev.importance >= HEAVY_DATE


# ── Ce qui se retire (ADR 0082) ────────────────────────────────────────────
#
# Un texte tiré de ce qu'elle sait (un portrait, son récit, une pensée, un rêve, son journal) dépend de ses sources.
# Quand l'une est remplacée, devient secrète, est contestée, jointe à une autre ou finie, ce qui en dérive le sait :
# **une seule définition**, lue par chaque faculté sur les événements de la mémoire qu'elle réduit déjà — aucun
# événement de plus à émettre, et le journal d'avant se rejoue avec.

SUPERSEDED, SECRET, CONTESTED, JOINED_TO, ENDED = "superseded", "secret", "contested", "joined", "ended"
#: ce qui ne peut plus se dire comme avant : ce qui en dérive se tait tout de suite (puis se réécrit)
PRIVATE_REASONS = frozenset({SECRET})


@dataclass(frozen=True, slots=True)
class Withdrawal:
    """Un élément de sa mémoire qui se retire : remplacé (``by`` : par quoi), devenu secret, contesté, joint à un autre
    (``by`` : le gardé), ou une situation finie."""

    item: int
    reason: str
    by: int | None = None


def withdrawals(name: str, d: Any, seq: int) -> tuple[Withdrawal, ...]:
    """Ce qu'un événement de la mémoire retire (vide : rien). Les facultés qui gardent un texte dérivé réduisent
    ``WITHDRAWING`` et appellent ceci."""
    out: list[Withdrawal] = []
    replaces = getattr(d, "replaces", None)
    if name == ATTESTED.name:
        if d.secret:
            out.append(Withdrawal(d.item, SECRET))
        if replaces is not None and replaces != d.item:
            out.append(Withdrawal(replaces, SUPERSEDED, d.item))
        if d.contests is not None:
            out.append(Withdrawal(d.contests, CONTESTED, d.item))
    elif name == REINFORCED.name:
        if d.secret:
            out.append(Withdrawal(d.item, SECRET))
        if replaces is not None and replaces != d.item:
            out.append(Withdrawal(replaces, SUPERSEDED, d.item))
    elif name in (BELIEVED.name, EVENT_NOTED.name):
        if replaces is not None:
            out.append(Withdrawal(replaces, SUPERSEDED, seq))
        if getattr(d, "contests", None) is not None:
            out.append(Withdrawal(d.contests, CONTESTED, seq))
        if getattr(d, "recurs", None) is not None:
            out.append(Withdrawal(d.recurs, SUPERSEDED, seq))
    elif name == JOINED.name:
        out += [Withdrawal(drop, JOINED_TO, keep) for keep, drop in d.pairs]
    elif name == NIGHT_SORTED.name:
        out += [Withdrawal(drop, JOINED_TO, keep) for keep, drop in d.merges]
    elif name == SITUATION_ENDED.name:
        out.append(Withdrawal(d.event, ENDED))
    return tuple(out)


#: Les événements de la mémoire qui peuvent retirer quelque chose (``withdrawals``).
WITHDRAWING = (BELIEVED, ATTESTED, REINFORCED, EVENT_NOTED, JOINED, NIGHT_SORTED, SITUATION_ENDED)


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
#: Le fil d'un moment, d'après n'importe lequel de ses numéros (un moment reporté, redit, revenu) — son ``id`` si
#: aucun autre ne l'a remplacé. Lu par ce qui range ce qu'elle en a dit (``others``).
MOMENT_THREAD = FactFamily("memory.moment_thread", arg=int, type=int)
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

# ── La porte (ADR 0077…) : ce que les autres facultés lisent de ce qu'elle sait ──
#
# Les tables ci-dessus sont à la mémoire ; ailleurs, on ne lit que ces **vues** (un test d'architecture le vérifie),
# et on passe chaque ligne par le verdict commun (``vocab.knowledge.known_of`` → ``Known.lineage`` →
# ``vocab.lineage.admits``) : une faculté qui refait son propre filtre finit par fuir.

#: Ce qu'elle sait et tient encore pour sien : souvenirs, croyances, promesses, moments — ni ce qu'une autre croyance
#: a remplacé, ni ce que la nuit a fondu dans un autre. Les promesses tenues ou abandonnées, les situations finies y
#: restent (c'est de l'histoire, toujours vraie). Colonnes : ``KNOWN_COLUMNS``.
KNOWLEDGE_VIEW = "memory_knowledge"
#: Qui concerne ce qu'elle sait (``item``, ``person``), indexé par personne — les mêmes lignes que ``KNOWLEDGE_VIEW``.
KNOWLEDGE_ABOUT_VIEW = "memory_knowledge_about"
#: Ce qu'elle a cru et ne croit plus (remplacé, fondu), lu par identifiant : « je croyais que… ».
FORMER_VIEW = "memory_former"
#: À qui elle a répété quoi (``item``, ``handle``, ``at``).
RETOLD_VIEW = "memory_retold"
#: Tout, statut compris, pour la console, le simulateur et l'application — jamais pour une faculté ou un plugin.
LEDGER_VIEW = "memory_ledger"
#: Ce que chaque élément de ``KNOWLEDGE_VIEW`` fait ressentir (``item``, ``whose``, ``emotion``, ``intensity``) :
#: à la personne concernée (``THEIRS``) ou à elle (``HERS``) — « ce qui t'énerve » se cherche par l'émotion
#: (ADR 0083). Les mêmes droits que l'élément : on lit l'élément, puis le verdict.
FEELINGS_VIEW = "memory_knowledge_feelings"
#: La table qu'elle lit (dans la mémoire seulement) ; qui ressent : la personne concernée, ou elle
FEELINGS_TABLE = "memory_feelings"
THEIRS = "theirs"
HERS = "hers"
#: Les colonnes de ``KNOWLEDGE_VIEW`` et ``FORMER_VIEW``. ``told_by``, ``heard_by``, ``secret``, ``sensitivity``
#: disent l'enveloppe la plus stricte de l'élément : on ne décide jamais dessus à la main, on passe par le verdict.
KNOWN_COLUMNS = ("id", "kind", "text", "about", "sensitivity", "importance", "confidence", "origin", "source",
                 "emotion", "born_at", "touched_at", "status", "recipient", "due", "sources", "told_by", "heard_by",
                 "secret", "about_self", "between_us", "knowledge_kind", "holder", "constraints", "internal_only")
#: Les statuts qui sortent de ce qu'elle sait (``FORMER_VIEW``) : remplacée, fondue la nuit dans un souvenir, jointe
#: la nuit à la même croyance dite par un autre (ADR 0080).
FORMER_STATUSES = ("superseded", "merged", "joined")
#: « SELECT <KNOWN_COLUMNS> FROM <vue> » : à compléter d'un ``WHERE`` ; chaque ligne se lit par
#: ``vocab.knowledge.knowns(rows, KNOWN_COLUMNS)``.
SELECT_KNOWN = f"SELECT {', '.join(KNOWN_COLUMNS)} FROM {KNOWLEDGE_VIEW}"
SELECT_FORMER = f"SELECT {', '.join(KNOWN_COLUMNS)} FROM {FORMER_VIEW}"


class LifeRecalled(Payload):
    items: tuple[LifeEvent, ...] = ()
    daily: bool = False


LIFE_RECALLED = event_type("memory.life_recalled", OWNER, LifeRecalled, public=True)
ALL = (*ALL, LIFE_RECALLED)
LIFE_TABLE = "memory_life"
