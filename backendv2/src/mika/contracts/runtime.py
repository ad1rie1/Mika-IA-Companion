"""Contrat du runtime : perceptions, épisodes, effets externes."""

from __future__ import annotations

from mika.kernel.events import Content, Payload, VoiceProvenance, event_type

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


class EpisodeStarted(Payload):
    kind: str
    target: str | None = None
    trigger: str = ""
    reason: str = ""
    reply_to: int | None = None


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
