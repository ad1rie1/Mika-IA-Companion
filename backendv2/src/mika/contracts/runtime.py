"""Contrat du runtime : perceptions, épisodes, effets externes."""

from __future__ import annotations

from dataclasses import dataclass

from mika.kernel.events import Content, Payload, VoiceProvenance, event_type
from mika.kernel.facts import FactKey

OWNER = "runtime"
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


class EpisodeStarted(Payload):
    kind: str
    target: str | None = None
    trigger: str = ""
    reason: str = ""
    reply_to: int | None = None
    #: ce sur quoi porte l'épisode quand ce n'est pas sa cible (``goal:12`` pour
    #: un rappel adressé à quelqu'un) : son propriétaire le reconnaît
    subject: str | None = None


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


PERCEPTION_RECEIVED = event_type(
    "perception.received", OWNER, PerceptionReceived, public=True, content=("text",), subjects=("handle",)
)
EPISODE_STARTED = event_type("episode.started", OWNER, EpisodeStarted, public=True)
UTTERANCE = event_type(
    "episode.utterance", OWNER, Utterance, public=True, content=("text",), subjects=("target",), authored=True
)
EPISODE_ENDED = event_type("episode.ended", OWNER, EpisodeEnded, public=True)
PROCESS_FAILED = event_type("runtime.process_failed", OWNER, ProcessFailed, public=True)
EFFECT_PROPOSED = event_type("effect.proposed", OWNER, EffectProposed, public=True, content=("summary",))
EFFECT_RESOLVED = event_type("effect.resolved", OWNER, EffectResolved, public=True)
EFFECT_EXECUTED = event_type("effect.executed", OWNER, EffectExecuted, public=True)

ALL = (
    PERCEPTION_RECEIVED, EPISODE_STARTED, UTTERANCE, EPISODE_ENDED, PROCESS_FAILED,
    EFFECT_PROPOSED, EFFECT_RESOLVED, EFFECT_EXECUTED,
)

#: Les messages (``seq``) qui attendent encore leur réponse.
AWAITING = FactKey("runtime.awaiting", type=tuple, doc="perceptions sans réponse encore réglée")


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
