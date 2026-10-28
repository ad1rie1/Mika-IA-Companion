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
from functools import cache
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, model_validator
from sqlalchemy import BigInteger, Column, Double, Index, Select, Table, select

from mika.kernel.events import Content, Payload, event_type
from mika.kernel.facts import FactFamily, FactKey
from mika.ports.sql import HANDLE_MAX, Key, LongText, projection_table, view_table
from mika.vocab.affect import facets
from mika.vocab.lineage import Restriction

OWNER = "memory"

TOLD = "told"  # quelqu'un le lui a dit
OBSERVED = "observed"  # elle l'a vu, vécu
INFERRED = "inferred"  # elle en déduit
#: elle l'a lu (un article, une page, un titre) : une source comme une autre, au plus comme un témoin qui rapporte
#: (ADR 0085)
READ = "read"
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
    #: les pièces jointes d'où il vient (leurs clés, ``contracts.attachments``, ADR 0106) — **en plus** de ses messages
    #: sources, et il peut y en avoir plusieurs : une photo, un document, un vocal qui le montre ou le dit
    pieces: tuple[str, ...] = ()
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
    #: un moment vécu à travers quelqu'un (ADR 0086), dit en bref et sans personne — « un concert de jazz » : ni
    #: prénom, ni lieu ni date précis (ADR 0087)
    gist: Content | None = None
    #: la même chose, racontée sans qu'on puisse reconnaître la personne (ADR 0091), comme ``Believed.veiled``
    veiled: Content | None = None

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
    #: les pièces jointes d'où il vient (leurs clés, ``contracts.attachments``, ADR 0106) — **en plus** de ses messages
    #: sources, et il peut y en avoir plusieurs : une photo, un document, un vocal qui le montre ou le dit
    pieces: tuple[str, ...] = ()
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
    knowledge_kind: Literal["claim", "opinion", "preference", "hypothesis", "prediction"] = "claim"
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
    #: une prévision (``knowledge_kind`` « prediction », ADR 0084) : quand c'est attendu (``expected`` : le début,
    #: ``expected_until`` : la fin, ``expected_precision`` : ``vocab.timespan``) et à quel point (0 à 1)
    expected: int | None = None
    expected_until: int | None = None
    expected_precision: str = ""
    likelihood: float | None = None
    #: la même chose, racontée sans qu'on puisse reconnaître la personne (ADR 0091) : écrite par la relecture, sans
    #: prénom, lieu précis, employeur, nom d'animal, date ni nombre — un récit sans nom à qui ne la connaît pas
    veiled: Content | None = None

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
    #: les pièces jointes d'où il vient (leurs clés, ``contracts.attachments``, ADR 0106) — **en plus** de ses messages
    #: sources, et il peut y en avoir plusieurs : une photo, un document, un vocal qui le montre ou le dit
    pieces: tuple[str, ...] = ()
    sensitivity: int | None = None
    about: tuple[str, ...] = ()
    told_by: tuple[str, ...] = ()
    heard_by: tuple[str, ...] = ()
    secret: bool = False
    replaces: int | None = None
    #: ce qui revient se révèle n'appartenir qu'à elles deux (un surnom) : ça le reste (ADR 0055)
    between_us: bool = False
    #: rien n'est redit, on lui demande la discrétion (« garde-le pour toi ») : l'élément se ferme sans durer
    #: davantage — ni importance de plus, ni oubli remis à zéro
    restricts: bool = False


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
    #: les pièces jointes d'où il vient (leurs clés, ``contracts.attachments``, ADR 0106) — **en plus** de ses messages
    #: sources, et il peut y en avoir plusieurs : une photo, un document, un vocal qui le montre ou le dit
    pieces: tuple[str, ...] = ()
    about: tuple[str, ...] = ()
    relations: tuple[Relation, ...] = ()
    #: ce qu'elle redit d'elle-même (une note sur elle)
    about_self: bool = False
    #: une note sur elle redite comme ce qui la définit (un goût, un avis, un fait de sa vie) : elle le devient, de
    #: cette sorte (``knowledge_kind``), et tient des mois — jamais l'inverse (ADR 0087)
    durable: bool = False
    knowledge_kind: Literal["claim", "opinion", "preference", "hypothesis", "prediction"] | None = None
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


class Reading(Payload):
    """Ce qu'elle a lu (ADR 0085), d'où que ce soit : ``source`` (« rss:<flux> », « web:<hôte> », « mcp:<serveur> »),
    ``ref`` (l'article, la page), son titre et un extrait — venus d'ailleurs, donc inertes et bornés —, et jusqu'où
    elle l'a lu (un titre et son chapeau, un article, une page). Le monde n'est la vie de personne : aucun sujet ;
    ce qu'elle en garde se décide la nuit (``memory.reread``).

    ``asked_by`` : lu en conversation, à la demande de cette adresse (ADR 0110). Ce qu'on cherchait est à cette
    personne : la recherche elle-même n'est pas gardée, le texte lu s'efface avec elle (son sujet), et la nuit n'en
    retient que les nouvelles et les faits publics, comme entendus par elle. Vide : lu pour elle-même."""

    source: str
    ref: str = ""
    title: Content
    excerpt: Content | None = None
    depth: Literal["headline", "article", "page"] = "headline"
    asked_by: str = ""


class Relayed(Payload):
    """Un message reçu par quelqu'un ailleurs que chez elle — sur son téléphone —, qu'elle lit parce que cette personne
    le lui montre (ADR 0120). La forme qu'écoute la mémoire, sans connaître le plugin qui l'apporte : elle relit la
    conversation une fois posée (``memory.relayed``), comme une de celles qu'elle a eues, sauf qu'elle n'y était pas.

    ``recipient`` : la personne qui l'a reçu (sa clé de personne) ; ``handle`` : l'adresse qui l'a apporté ;
    ``source`` : l'appli (« whatsapp », « messages ») ; ``thread`` : la conversation (une clé opaque) ; ``sender`` :
    la clé de qui l'a écrit (vide quand c'est la personne elle-même, ``own``) ; ``sender_name``, ``title`` (le nom du
    groupe) et ``text`` : venus d'ailleurs, des contenus personnels ; ``sent_at`` : son heure (µs)."""

    recipient: str
    handle: str
    source: str
    thread: str
    sender: str = ""
    sender_name: Content | None = None
    title: Content | None = None
    group: bool = False
    own: bool = False
    text: Content
    sent_at: int = 0


class RelayedRead(Payload):
    """Une conversation reçue ailleurs a été relue (ADR 0120) : ses messages (``seqs``) ne l'attendent plus.
    ``failed`` : la relecture a échoué trop de fois, on la laisse ; l'appel au modèle qui l'a faite."""

    seqs: tuple[int, ...] = ()
    produced: int = 0
    failed: bool = False
    call_id: str = ""
    model: str = ""


class Confronted(Payload):
    """La nuit, deux croyances sur la même personne, dites par des témoins différents, qui se contredisent (ADR
    0085) : ``supersedes`` (nouvelle, ancienne) — la plus sûre l'emporte ; ``contests`` — elle doute, les deux
    restent."""

    night: str
    supersedes: tuple[tuple[int, int], ...] = ()
    contests: tuple[tuple[int, int], ...] = ()


class Reread(Payload):
    """La relecture de la nuit est faite (ADR 0085) : ses lectures jusqu'à ``upto`` (le ``seq`` de la dernière),
    combien de lectures et de paires confrontées ; l'appel au modèle qui l'a faite (aucun : rien à relire)."""

    night: str
    upto: int = 0
    readings: int = 0
    pairs: int = 0
    call_id: str = ""
    model: str = ""


class Joined(Payload):
    """La nuit, des croyances dites pareil par des personnes différentes (des doublons d'avant les témoignages) se
    réunissent : ``(gardée, jointe)`` — la jointe devient un témoignage de la gardée. ``mute`` : jugées « la même
    chose » sans être les mêmes mots (la relecture, ADR 0085), ses témoignages comptent pour la confiance, jamais pour
    ce qui peut se dire — un témoin ne parle que pour les mots qu'il a dits (la rumeur de Bob ne laisse pas redire à
    Bob ce qu'Alice a confié)."""

    night: str
    pairs: tuple[tuple[int, int], ...] = ()
    mute: bool = False


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
    #: la tenir demande un travail (fabriquer, chercher, suivre quelque chose), pas seulement un mot à dire : ``goals``
    #: le met en route (ADR 0104). Faux dans un journal plus ancien.
    work: bool = False


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
    #: les pièces jointes d'où il vient (leurs clés, ``contracts.attachments``, ADR 0106) — **en plus** de ses messages
    #: sources, et il peut y en avoir plusieurs : une photo, un document, un vocal qui le montre ou le dit
    pieces: tuple[str, ...] = ()
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
    #: une période plutôt qu'un jour (ADR 0084) : sa fin (``when`` : son début) et sa précision (``vocab.timespan`` :
    #: un mois, une saison, une année, une période ; vide : un jour, comme avant)
    until: int | None = None
    precision: str = ""
    #: ``world`` : ce qui arrive dans le monde (des élections, la sortie d'un film, un jour férié) — la vie de
    #: personne, ``about`` vide ; toujours dit par quelqu'un (``told_by``), qu'on peut oublier
    scope: Literal["person", "world"] = "person"
    #: un moment de quelqu'un qu'elle vivra à travers lui (« samedi Sam m'emmène au salon, il me montrera ») : ses
    #: moments à elle passent par ses relations (ADR 0084)
    shared: bool = False
    #: une date publique officielle (un scrutin, un jour férié)
    official: bool = False
    #: sa vraisemblance (0 à 1), d'après d'où elle vient et ce qui en a été dit (``faculties.memory.likelihood``) ;
    #: ``None`` dans un journal plus ancien : la règle de sa nature
    likelihood: float | None = None


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

#: comment un moment a tourné (ADR 0086) : il a eu lieu, il est annulé, déplacé, ou personne ne l'a jamais dit
HAPPENED, CANCELLED, MOVED, UNKNOWN = "happened", "cancelled", "moved", "unknown"
OUTCOMES = (HAPPENED, CANCELLED, MOVED, UNKNOWN)
#: ce qui est arrivé, au regard d'un moment attendu : il a eu lieu (1), il n'a pas eu lieu (0) ; déplacé, il n'a pas
#: eu lieu ce jour-là, mais il aura lieu (à moitié) — ne pas savoir n'a pas de valeur
OUTCOME_VALUE = {HAPPENED: 1.0, CANCELLED: 0.0, MOVED: 0.5}
#: de quelle sorte était l'annonce (``Resolved.nature``, ADR 0084) : de la bouche de la personne, rapportée par un
#: autre ou le monde, une date officielle, une prévision
FIRST_HAND, REPORTED, OFFICIAL, PREDICTION = "first_hand", "reported", "official", "prediction"


class Resolved(Payload):
    """Comment un moment a tourné (ADR 0086), et ce qu'elle en attendait : constaté par la personne concernée
    (``by``), par ce qu'elle a lu (« rss:… »), ou faute de nouvelles une fois l'échéance passée (``by`` vide,
    ``unknown``). ``likelihood`` : ce qu'elle en attendait ; ``surprise`` : l'écart à cette attente, pesé par ce que
    le moment compte (``faculties.memory.likelihood.surprise``) ; ``nature`` et ``teller`` : de quelle sorte était
    l'annonce et qui l'avait faite — ce qu'elle en apprend ; ``valence`` : comment elle l'attendait (plus de zéro :
    avec espoir, moins : avec crainte)."""

    event: int
    thread: int = 0
    outcome: Literal["happened", "cancelled", "moved", "unknown"]
    by: str = ""
    likelihood: float | None = None
    importance: float = 0.7
    surprise: float = 0.0
    nature: str = ""
    teller: str = ""
    shared: bool = False
    valence: float = 0.0
    about: tuple[str, ...] = ()
    sources: tuple[int, ...] = ()
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

REMEMBERED = event_type("memory.remembered", OWNER, Remembered, public=True, content=("text", "gist", "veiled"),
                        subjects=_SUBJECTS)
BELIEVED = event_type("memory.believed", OWNER, Believed, public=True, content=("text", "veiled"),
                      subjects=(*_SUBJECTS, "holder"))
REINFORCED = event_type("memory.reinforced", OWNER, Reinforced, public=True)
PROMISE_NOTICED = event_type("memory.promise_noticed", OWNER, PromiseNoticed, public=True, content=("text",),
                             subjects=("to",))
PROMISE_RESOLVED = event_type("memory.promise_resolved", OWNER, PromiseResolved, public=True)
EVENT_NOTED = event_type("memory.event_noted", OWNER, EventNoted, public=True, content=("text",), subjects=_SUBJECTS)
MOMENT_FOLLOWED = event_type("memory.moment_followed", OWNER, MomentFollowed, public=True, subjects=("by",))
SITUATION_ENDED = event_type("memory.situation_ended", OWNER, SituationEnded, public=True)
RESOLVED = event_type("memory.resolved", OWNER, Resolved, public=True, subjects=("about", "by", "teller"))
EXTRACTION_DEFERRED = event_type("memory.extraction_deferred", OWNER, ExtractionDeferred, public=True,
                                 content=("detail",), subjects=("about",))
CONSOLIDATED = event_type("memory.consolidated", OWNER, Consolidated, public=True)
NIGHT_SORTED = event_type("memory.night_sorted", OWNER, NightSorted, public=True)
ATTESTED = event_type("memory.attested", OWNER, Attested, public=True, subjects=_SUBJECTS)
JOINED = event_type("memory.joined", OWNER, Joined, public=True)
CONFRONTED = event_type("memory.confronted", OWNER, Confronted, public=True)
REREAD = event_type("memory.reread", OWNER, Reread, public=True)
RELAYED_READ = event_type("memory.relayed_read", OWNER, RelayedRead, public=True)


class Delicate(Payload):
    """Ce qu'elle sait d'une personne et qui touche un de ses sujets délicats (son portrait : ``social.SENSITIVE``) :
    une confidence, où qu'on le lise — la porte de la mémoire le dit à toutes les facultés (ses pensées, ses buts,
    son journal), plus seulement au rappel qui le recalculait seul (ADR 0099). Jamais abaissé."""

    person: str
    items: tuple[int, ...] = ()
    level: int = 3


DELICATE = event_type("memory.delicate", OWNER, Delicate, public=True, subjects=("person",))
ALL = (REMEMBERED, BELIEVED, REINFORCED, PROMISE_NOTICED, PROMISE_RESOLVED, EVENT_NOTED, MOMENT_FOLLOWED, SITUATION_ENDED,
       CONSOLIDATED, NIGHT_SORTED, EXTRACTION_DEFERRED, ATTESTED, JOINED, CONFRONTED, REREAD, RESOLVED, DELICATE,
       RELAYED_READ)


@dataclass(frozen=True, slots=True)
class PendingPromise:
    id: int
    to: str
    due: int | None
    at: int
    implicit_due: bool = False
    #: un jour sans heure : à tenir dans la journée
    all_day: bool = False
    #: une promesse de travail (``PromiseNoticed.work``), son texte (un contenu, effaçable) et sa sensibilité
    work: bool = False
    text_ref: str = ""
    sensitivity: int = 2


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
    #: une période (ADR 0084) : sa fin (0 : un jour) et sa précision ; ``world`` : ce qui arrive dans le monde ;
    #: ``shared`` : un moment de quelqu'un qu'elle vivra à travers lui ; ``official`` : une date publique ;
    #: ``likelihood`` : sa vraisemblance (``None`` : la règle de sa nature)
    until: int = 0
    precision: str = ""
    scope: str = "person"
    shared: bool = False
    official: bool = False
    likelihood: float | None = None
    #: comment il a tourné (``HAPPENED``…, vide : pas encore su) et quand on l'a su (ADR 0086)
    outcome: str = ""
    resolved_at: int = 0

    @property
    def key(self) -> int:
        """Le fil du moment (son ``id`` dans un journal d'avant)."""
        return self.thread or self.id

    @property
    def vague(self) -> bool:
        """Plus large qu'un jour (« en novembre ») : ni la veille ni le lendemain n'ont de sens (ADR 0084)."""
        return bool(self.precision)

    @property
    def ends(self) -> int:
        """La fin du moment : celle de sa période, sinon le moment lui-même."""
        return self.until or self.when


def life_event_of(seq: int, d: EventNoted, *, followed_at: int = 0, ended_at: int = 0, thread: int = 0) -> LifeEvent:
    """Le moment tel qu'il est gardé, d'après ce qui l'a noté — une seule façon, pour la tranche et l'archive."""
    return LifeEvent(seq, tuple(d.about), d.when, d.all_day, d.sensitivity, tuple(d.told_by), d.text.ref or "",
                     d.secret, followed_at=followed_at, ongoing=d.ongoing, importance=d.importance,
                     festive=d.festive, ended_at=ended_at, yearly=d.yearly and not d.ongoing, thread=thread,
                     recurs=d.recurs or 0, felt=tuple(d.felt), empathy=tuple(d.empathy), until=d.until or 0,
                     precision=d.precision, scope=d.scope, shared=d.shared, official=d.official,
                     likelihood=d.likelihood)


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
#: devenu une confidence parce qu'il touche un sujet délicat de la personne (``memory.delicate``, ADR 0099)
DELICATE_TOPIC = "delicate"
#: ce qui ne peut plus se dire comme avant : ce qui en dérive se tait tout de suite (puis se réécrit) — un texte
#: dérivé garde la sensibilité de ses sources telle qu'elle était quand il s'est écrit
PRIVATE_REASONS = frozenset({SECRET, DELICATE_TOPIC})


@dataclass(frozen=True, slots=True)
class Withdrawal:
    """Un élément de sa mémoire qui se retire : remplacé (``by`` : par quoi), devenu secret, devenu une confidence (un
    sujet délicat), contesté, joint à un autre (``by`` : le gardé), ou une situation finie."""

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
    elif name == CONFRONTED.name:
        out += [Withdrawal(old, SUPERSEDED, new) for new, old in d.supersedes]
        # la nuit les a confrontées : elle doute de l'une comme de l'autre
        out += [w for a, b in d.contests for w in (Withdrawal(b, CONTESTED, a), Withdrawal(a, CONTESTED, b))]
    elif name == NIGHT_SORTED.name:
        out += [Withdrawal(drop, JOINED_TO, keep) for keep, drop in d.merges]
    elif name == SITUATION_ENDED.name:
        out.append(Withdrawal(d.event, ENDED))
    elif name == RESOLVED.name and d.outcome in (CANCELLED, MOVED):
        out.append(Withdrawal(d.event, ENDED))  # « son entretien jeudi » ne tient plus
    elif name == DELICATE.name:
        # devenu une confidence : ce qui le reprenait à la sensibilité d'avant se tait aussi (ADR 0099)
        out += [Withdrawal(item, DELICATE_TOPIC) for item in d.items]
    return tuple(out)


#: Les événements de la mémoire qui peuvent retirer quelque chose (``withdrawals``).
WITHDRAWING = (BELIEVED, ATTESTED, REINFORCED, EVENT_NOTED, JOINED, NIGHT_SORTED, SITUATION_ENDED, CONFRONTED,
               RESOLVED, DELICATE)


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
#: Ce qu'elle voit venir (ADR 0084) : les moments du monde et ceux qu'elle vivra à travers quelqu'un, pas finis, à
#: venir ou en cours (``LifeEvent``, les plus proches d'abord) — sans verdict : qui le lit le juge pour son audience.
AHEAD = FactKey("memory.ahead", type=tuple, time_varying=True)
#: la portée d'un moment : la vie d'une personne, ou le monde (ADR 0084)
PERSON_SCOPE, WORLD = "person", "world"
#: Ce qui approche (ADR 0086) : tous les moments — de quelqu'un, du monde, partagés — à venir d'ici quelques jours
#: (``upcoming_days``), ni finis ni tranchés, les plus proches d'abord : ce qu'elle peut attendre avec espoir ou
#: crainte (``attention``). Sans verdict : rien ne s'en dit, ça se ressent.
UPCOMING = FactKey("memory.upcoming", type=tuple, time_varying=True)
#: Ce qu'elle voudrait vérifier (ADR 0086) : les moments du monde passés depuis peu dont elle ne sait pas comment ils
#: ont tourné, et qui lui tiennent à cœur (importants, ou qu'elle attendait avec un sentiment) — les plus importants
#: d'abord. Lu par ``goals`` (une exploration de vérification, bornée par semaine).
TO_CHECK = FactKey("memory.to_check", type=tuple, time_varying=True)
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


@cache
def chunks_table(sfx: str = "") -> Table:
    """``memory_chunks`` (suffixée de sa version) : un échange par réponse visible — ce qu'on lui a dit (tout le tour)
    et ce qu'elle a répondu ; la console relit l'échange d'où vient un souvenir (ADR 0101 : déclarée pour les deux
    moteurs, hors des migrations). ``person`` et ``room`` sont des clés bornées à ``HANDLE_MAX`` (la projection y range
    une valeur plus longue par ``fit``)."""
    name = f"{CHUNKS_TABLE}{sfx}"
    return projection_table(
        name,
        Column("id", BigInteger, primary_key=True, autoincrement=False),
        Column("person", Key(HANDLE_MAX), nullable=False),
        Column("question", BigInteger),
        Column("user_text", LongText, nullable=False),
        Column("reply_text", LongText, nullable=False),
        Column("at", BigInteger, nullable=False),
        Column("room", Key(HANDLE_MAX)),
        # ses échanges dans le temps (« ce que je t'ai dit lundi »), et ceux d'un salon
        Index(f"{name}_person_at", "person", "at"),
        Index(f"{name}_room_at", "room", "at"),
    )

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
#: Chaque énoncé qui lui montrait un récit sans nom (``item``, ``handle``, ``utterance`` : le numéro de l'énoncé, qui
#: est aussi la ligne de sa réponse dans le fil, ``at``) : ce qu'elle a vraiment dit se juge à la lecture, sur sa
#: réponse (ADR 0092) — le prompt montre, il ne dit pas.
TOLD_LINES_TABLE = "memory_told_lines"

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
#: À qui elle a répété quoi (``item``, ``handle``, ``at``, ``veiled``) — ``veiled`` : seulement sans nommer personne
#: (ADR 0091) ; la personne ne sait pas de qui il s'agit, mais elle le sait, elle.
RETOLD_VIEW = "memory_retold"
#: la provenance d'un élément raconté sans nommer personne (``veiled:<élément>``, ADR 0091) — celle d'un élément
#: montré nommé est ``memory:<élément>``
VEILED_PROVENANCE = "veiled:"
#: Ce qu'elle pensait d'elle-même et dont elle a changé (ADR 0087) : ses notes à elle seulement, de la remplacée
#: (``was``, ``was_text``) à celle qu'elle tient maintenant (``item``, ``text``, ``knowledge_kind``), avec l'enveloppe
#: la plus stricte des deux (``sensitivity``, ``secret``) et quand elle a changé (``changed_at``).
SELF_CHANGES_VIEW = "memory_self_changes"
SELF_CHANGES_COLUMNS = ("was", "was_text", "item", "text", "knowledge_kind", "sensitivity", "secret", "changed_at")
#: Ce qu'elle a vécu à travers quelqu'un (ADR 0086) et qui se dit en bref, sans personne (ADR 0087) : les colonnes de
#: ``KNOWLEDGE_VIEW`` et ``gist`` (« un concert de jazz »). Les mêmes droits que l'élément : on passe par le verdict.
LIVED_VIEW = "memory_lived"
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

# ── Les colonnes des vues (ADR 0101) : on les lit par des requêtes (``select(KNOWLEDGE.c.text)``), compilées pour le
# moteur. Les vues elles-mêmes se créent dans la mémoire (``faculties.memory.projections``), sur ses tables.

#: toutes les colonnes d'un élément, dans l'ordre de sa table : celles de ``LEDGER_VIEW`` — ``folded`` : son texte
#: replié (``fold_text`` : casse et accents ignorés), ce qu'on y cherche pareil sur les deux moteurs (un ``LIKE`` sur
#: ``text`` ignore la casse ASCII sous SQLite, pas sous MariaDB)
LEDGER_COLUMNS = ("id", "kind", "text", "about", "sensitivity", "importance", "confidence", "origin", "source",
                  "emotion", "born_at", "touched_at", "recalled_at", "recalls", "status", "replaces", "recipient",
                  "due", "sources", "told_by", "heard_by", "secret", "informants", "about_self", "shown_at",
                  "between_us", "knowledge_kind", "holder", "constraints", "internal_only", "fingerprint",
                  "superseded_by", "superseded_at", "as_of", "valid_until", "felt", "empathy", "until", "precision",
                  "likelihood", "gist", "veiled", "felt_from", "folded")
#: la borne d'une sorte d'élément et d'un statut (``souvenir``, ``superseded``…), clés indexées
KIND_MAX = STATUS_MAX = 32
_INTEGERS = frozenset({"id", "sensitivity", "born_at", "touched_at", "recalled_at", "recalls", "replaces", "due",
                       "secret", "about_self", "shown_at", "between_us", "internal_only", "superseded_by",
                       "superseded_at", "as_of", "valid_until", "until", "felt_from", "item", "at", "was",
                       "changed_at"})
_REALS = frozenset({"importance", "confidence", "likelihood", "intensity"})
_KEYS = {"kind": KIND_MAX, "status": STATUS_MAX, "fingerprint": 64, "person": HANDLE_MAX, "handle": HANDLE_MAX}


def _column(name: str) -> Column[Any]:
    kind: Any = BigInteger if name in _INTEGERS else Double if name in _REALS else \
        Key(_KEYS[name]) if name in _KEYS else LongText
    return Column(name, kind)


def _view(name: str, columns: tuple[str, ...], **kinds: Any) -> Table:
    """Une vue de ces colonnes, typées par leur nom (``kinds`` : celles qui, ici, veulent dire autre chose)."""
    return view_table(name, *(Column(n, kinds[n]) if n in kinds else _column(n) for n in columns))


KNOWLEDGE = _view(KNOWLEDGE_VIEW, KNOWN_COLUMNS)
KNOWLEDGE_ABOUT = _view(KNOWLEDGE_ABOUT_VIEW, ("item", "person"))
FORMER = _view(FORMER_VIEW, KNOWN_COLUMNS)
#: ``veiled`` y est un drapeau (seulement sans nommer personne) ; dans un élément, le texte raconté sans nom
RETOLD = _view(RETOLD_VIEW, ("item", "handle", "at", "veiled"), veiled=BigInteger)
SELF_CHANGES = _view(SELF_CHANGES_VIEW, SELF_CHANGES_COLUMNS)
LIVED = _view(LIVED_VIEW, (*KNOWN_COLUMNS, "gist"))
LEDGER = _view(LEDGER_VIEW, LEDGER_COLUMNS)
FEELINGS = view_table(FEELINGS_VIEW, Column("item", BigInteger), Column("whose", Key(16)), Column("emotion", Key(64)),
                      Column("intensity", Double))


def select_known(view: Table | None = None) -> Select[Any]:
    """``SELECT <KNOWN_COLUMNS> FROM <vue>`` (``KNOWLEDGE`` par défaut ; ``FORMER``, ``LIVED``) : à compléter d'un
    ``.where`` ; chaque ligne se lit par ``vocab.knowledge.knowns(rows, KNOWN_COLUMNS)``."""
    v = KNOWLEDGE if view is None else view
    return select(*(v.c[n] for n in KNOWN_COLUMNS))


def concerning(view: Table, keys: Any) -> Any:
    """La condition « l'élément de cette vue concerne l'une de ces clés » (``KNOWLEDGE_ABOUT``, indexée par
    personne) : ``view.c.id IN (SELECT item FROM memory_knowledge_about WHERE person IN (…))``."""
    return view.c.id.in_(select(KNOWLEDGE_ABOUT.c.item).where(KNOWLEDGE_ABOUT.c.person.in_(list(keys))))


class LifeRecalled(Payload):
    items: tuple[LifeEvent, ...] = ()
    daily: bool = False


LIFE_RECALLED = event_type("memory.life_recalled", OWNER, LifeRecalled, public=True)
ALL = (*ALL, LIFE_RECALLED)
LIFE_TABLE = "memory_life"
