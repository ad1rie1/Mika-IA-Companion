"""Contrat du runtime : perceptions, épisodes, effets externes."""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Content, Payload, VoiceProvenance, event_type
from mika.kernel.facts import FactFamily, FactKey

OWNER = "runtime"
#: dans les arguments d'un effet proposé (ADR 0064) : l'adresse de la personne qui en décide **dans le chat** (une
#: carte d'accord, à elle seule), et l'instant (µs) au-delà duquel la carte ne vaut plus
DECIDER = "_decider"
EXPIRES = "_expires"
NAMESPACES = ("perception", "episode", "effect", "runtime")


class AttachmentMeta(Payload):
    name: str
    kind: str
    mime: str = ""
    extracted: bool = False
    error: str | None = None


class PerceptionReceived(Payload):
    handle: str
    channel: str
    text: Content
    room: str | None = None
    authenticated: bool = False
    public: bool = False
    reply_ref: str | None = None
    client_msg_id: str | None = None
    display_name: str = ""
    attachments: tuple[AttachmentMeta, ...] = ()
    #: Adressé à elle ? Dans un salon, elle entend tout mais ne répond qu'à ce
    #: qui lui parle (son nom, une réponse à son message) ; en privé, toujours.
    addressed: bool = True
    #: Avec des pièces jointes : combien de caractères, au début de ``text``, la personne a tapés — la suite est
    #: ce que ses fichiers lui ont donné à percevoir (pour le prompt, jamais pour la bulle qu'elle relit).
    #: ``None`` : rien à séparer (pas de pièce jointe, ou un journal plus ancien, qui garde son affichage).
    typed_chars: int | None = None


class EpisodeStarted(Payload):
    kind: str
    target: str | None = None
    trigger: str = ""
    reason: str = ""
    reply_to: int | None = None
    #: ce sur quoi porte l'épisode quand ce n'est pas sa cible (``goal:12`` pour
    #: un rappel adressé à quelqu'un) : son propriétaire le reconnaît
    subject: str | None = None
    #: le ``seq`` exact de l'événement ``kernel.selected`` qui a choisi cet épisode (une initiative, un pas) ;
    #: ``None`` pour ce que personne n'a choisi (une réponse) — et dans un journal plus ancien
    selected: int | None = None


class ToolOutcome(Payload):
    name: str
    ok: bool


class Utterance(Payload):
    kind: str
    text: Content
    voice: VoiceProvenance
    target: str | None = None
    channel: str | None = None
    room: str | None = None
    reply_to: int | None = None
    visible: bool = True
    annotations: tuple[tuple[str, str], ...] = ()
    tools: tuple[ToolOutcome, ...] = ()
    sections: tuple[str, ...] = ()
    #: ce que le prompt lui montrait (souvenirs, contenus) : ``"memory:12"``…
    provenance: tuple[str, ...] = ()
    #: les messages que cet énoncé règle : tout le tour de la personne (ses messages encore sans réponse, de la
    #: même adresse et du même salon, jusqu'à ``reply_to`` compris — une rafale reçoit une seule réponse qui les
    #: a tous lus). Vide dans un journal plus ancien : l'énoncé ne réglait alors que ``reply_to``.
    answers: tuple[int, ...] = ()
    #: ce qui part avec ce message : des références opaques que ses outils ont posées (``ToolResult.attach`` — un
    #: fichier préparé pour la personne). Le runtime et le transport les portent sans savoir ce qu'elles désignent ;
    #: leur propriétaire les reconnaît (un fichier « est parti » avec ce message).
    attachments: tuple[str, ...] = ()
    #: les personnes que le texte peut nommer quand ``target`` n'en désigne aucune (un murmure qui pense à
    #: celle à qui elle va écrire) : l'oubli l'atteint. Vide dans un journal plus ancien.
    about: tuple[str, ...] = ()

    def annotation(self, key: str) -> str | None:
        for k, v in self.annotations:
            if k == key:
                return v
        return None


class EpisodeEnded(Payload):
    kind: str
    outcome: str
    target: str | None = None
    reply_to: int | None = None
    detail: str = ""
    guard: str | None = None
    changed: tuple[str, ...] = ()
    #: les messages que cette fin laisse sans réponse, pour de bon (elle a choisi de se taire, la réponse a
    #: échoué, les tentatives sont épuisées, il est trop tard) : une intention de la fin, pas un état
    #: recalculé. ``None`` dans un journal plus ancien : la règle d'alors (issue × tentatives) s'y applique.
    #: Le transport l'apprend par la file de sortie (``ports.delivery`` : ``reply_abstained`` si elle s'est
    #: tue, ``reply_failed`` sinon, pour le dernier message du tour).
    unanswered: tuple[int, ...] | None = None


class ProcessFailed(Payload):
    process: str
    error: str


class EffectProposed(Payload):
    capability: str
    owner: str
    args_json: str
    summary: Content
    approval: bool = True
    context: str = ""
    #: les personnes que le résumé peut citer (l'oubli l'atteint)
    about: tuple[str, ...] = ()


class EffectResolved(Payload):
    proposal: int
    approved: bool
    note: str = ""
    by: str = ""
    #: recopiés de la proposition : l'exécuteur n'a pas à relire le journal
    capability: str = ""
    owner: str = ""
    args_json: str = "{}"
    context: str = ""


class EffectExecuted(Payload):
    proposal: int
    ok: bool
    result: str = ""


class Operated(Payload):
    """Une action d'opérateur passée par la console (l'audit) : laquelle, par qui,
    sur quel objet, ce qu'elle a écrit. Aucun contenu : l'oubli n'a rien à y chercher."""

    action: str
    by: str
    subject_kind: str = ""
    subject: str = ""
    seqs: tuple[int, ...] = ()
    #: ``done`` | ``refused`` | ``superseded`` | ``failed``
    outcome: str = "done"


PERCEPTION_RECEIVED = event_type(
    "perception.received", OWNER, PerceptionReceived, public=True, content=("text",), subjects=("handle",)
)
EPISODE_STARTED = event_type("episode.started", OWNER, EpisodeStarted, public=True)
UTTERANCE = event_type(
    "episode.utterance", OWNER, Utterance, public=True, content=("text",), subjects=("target", "about"),
    authored=True
)
EPISODE_ENDED = event_type("episode.ended", OWNER, EpisodeEnded, public=True)
PROCESS_FAILED = event_type("runtime.process_failed", OWNER, ProcessFailed, public=True)
EFFECT_PROPOSED = event_type("effect.proposed", OWNER, EffectProposed, public=True, content=("summary",),
                             subjects=("about",))
EFFECT_RESOLVED = event_type("effect.resolved", OWNER, EffectResolved, public=True)
EFFECT_EXECUTED = event_type("effect.executed", OWNER, EffectExecuted, public=True)

OPERATED = event_type("runtime.operated", OWNER, Operated, public=True)
ALL = (
    PERCEPTION_RECEIVED, EPISODE_STARTED, UTTERANCE, EPISODE_ENDED, PROCESS_FAILED,
    EFFECT_PROPOSED, EFFECT_RESOLVED, EFFECT_EXECUTED, OPERATED,
)

#: Les messages (``seq``) qui attendent encore leur réponse.
AWAITING = FactKey("runtime.awaiting", type=tuple, doc="perceptions sans réponse encore réglée")
#: Le tour en cours d'une adresse en un lieu, ``TURN((adresse, salon))`` (salon ``None`` en privé) : ses
#: messages encore sans réponse, du plus ancien au plus récent. Une réponse règle le tour entier ; un nouveau
#: message du même tour supplante la réponse en train de s'écrire (elle sera recomposée en le lisant).
TURN = FactFamily("runtime.turn", arg=tuple, type=tuple,
                  doc="les messages sans réponse d'une adresse en un lieu (adresse, salon)")



@dataclass(frozen=True, slots=True)
class PendingEffectView:
    """Un effet externe qui attend l'accord d'un opérateur."""

    proposal: int
    capability: str
    owner: str
    context: str
    summary_ref: str
    at: int


#: Les effets proposés qui attendent un accord, du plus ancien au plus récent.
PENDING_EFFECTS = FactKey("runtime.pending_effects", type=tuple)
