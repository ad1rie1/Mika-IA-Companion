"""Trust policy — how sure Mika is about *who* she is talking to.

Two orthogonal notions live here, and conflating them is the mistake this
module exists to prevent:

**Channel trust** is a property of the *transport*. A Django session cookie
proves the browser holds credentials we issued; a Telegram ``tg_<id>`` proves
only that the same account came back; a message in a public group proves
nothing at all. Channel trust is a ceiling — no amount of conversation makes
a public-room claim as good as an authenticated session.

**Identity certainty** is a property of the *link* between a handle and a
person Mika knows by name. It starts at whatever the channel affords and
moves as evidence accumulates: someone says a name, mentions something only
that person would know, or Mika simply decides to believe them.

Everything here is a pure function over primitives, so the whole policy is
unit-testable without a database, a request, or a running engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ChannelTrust(str, Enum):
    """What the transport itself can prove about the sender."""

    #: Credentials we issued and verified this request (Django session).
    AUTHENTICATED = "authenticated"
    #: A stable account handle on a private 1:1 transport (Telegram DM).
    #: The account is consistent across sessions; who holds it is not proven.
    ACCOUNT = "account"
    #: A shared/public space — group chat, public channel, open room. Anyone
    #: can say anything, including that they are someone else.
    PUBLIC = "public"
    #: Server-internal (conscience, module notifications). Not a person.
    INTERNAL = "internal"


class Certainty(float, Enum):
    """How sure Mika is that this handle is the person she thinks it is.

    Ordered, and used as a plain float in scoring — ``Certainty.CLAIMED +
    0.1`` is meaningful. The labels exist so prompts and logs can say
    something human instead of printing 0.45.
    """

    UNKNOWN = 0.0
    #: Passive hint only: a name appeared, the style matches, the timing fits.
    SUSPECTED = 0.25
    #: They said who they are. Nothing corroborates it yet.
    CLAIMED = 0.45
    #: The claim lines up with something Mika already knew about that person.
    CORROBORATED = 0.70
    #: Mika decided to believe it and bound the handle. Durable across sessions.
    BOUND = 0.85
    #: Proven by the transport (authenticated session). Not a judgement call.
    VERIFIED = 1.0


#: Certainty a channel grants on its own, before any conversation happens.
_CHANNEL_FLOOR: dict[ChannelTrust, float] = {
    ChannelTrust.AUTHENTICATED: Certainty.VERIFIED,
    ChannelTrust.ACCOUNT: Certainty.SUSPECTED,
    ChannelTrust.PUBLIC: Certainty.UNKNOWN,
    ChannelTrust.INTERNAL: Certainty.UNKNOWN,
}

#: Certainty a channel can never be pushed above, whatever is said on it.
#: A public room caps below BOUND on purpose: Mika may act on a public claim,
#: but she should never treat it as settled the way she treats a login.
_CHANNEL_CEILING: dict[ChannelTrust, float] = {
    ChannelTrust.AUTHENTICATED: Certainty.VERIFIED,
    ChannelTrust.ACCOUNT: Certainty.BOUND,
    ChannelTrust.PUBLIC: Certainty.CORROBORATED,
    ChannelTrust.INTERNAL: Certainty.UNKNOWN,
}

#: Weight added to certainty per accepted piece of evidence, by kind.
#:
#: Calibrated against ``PRIVATE_CONTEXT_THRESHOLD`` (0.70): a bare claim must
#: never reach it alone, and "they said who they are AND proved something only
#: that person would know" must land exactly on it. That pair is what being
#: convinced looks like on a channel with no login.
EVIDENCE_WEIGHTS: dict[str, float] = {
    # "je suis Thomas" — cheap to say, so cheap in weight.
    "self_declared": 0.20,
    # A name Mika inferred without being told (mentioned in third person,
    # signature, module metadata).
    "passive_inference": 0.10,
    # They referenced something Mika only knows about that specific person.
    # The strongest evidence available without a transport that can prove it.
    "shared_memory": 0.50,
    # Someone Mika already trusts vouched for them. Weighty, but a friend's
    # word is still not the same as knowing something only you could know.
    "vouched": 0.35,
    # The transport proved it.
    "authenticated": 1.0,
}

#: Evidence that *lowers* certainty. Doubt is evidence too.
COUNTER_EVIDENCE_WEIGHTS: dict[str, float] = {
    # They got a shared fact wrong.
    "contradicted": -0.35,
    # They denied being the person Mika assumed.
    "denied": -0.50,
    # Mika explicitly stopped believing.
    "revoked": -1.0,
}


def channel_trust(
    *, channel: str, authenticated: bool = False, is_group: bool = False,
) -> ChannelTrust:
    """Classify a transport.

    ``channel`` is the transport name ("web", "telegram", …); the two flags
    are what the adapter knows about *this* connection. An authenticated
    session wins over everything — that is the point of authenticating.
    """
    if authenticated:
        return ChannelTrust.AUTHENTICATED
    name = normalize_channel(channel)
    if name in _INTERNAL_CHANNELS:
        return ChannelTrust.INTERNAL
    if is_group:
        return ChannelTrust.PUBLIC
    if name in _ACCOUNT_CHANNELS:
        return ChannelTrust.ACCOUNT
    # Unknown transports are treated as public: assume the worst about a
    # channel whose guarantees nobody has written down yet.
    return ChannelTrust.PUBLIC


#: Transports where a persistent account id is issued by the platform.
_ACCOUNT_CHANNELS = frozenset({"telegram", "discord", "signal", "email"})
#: Not people — Mika's own loops and module callbacks.
_INTERNAL_CHANNELS = frozenset({
    "conscience", "internal", "module", "system", "drive", "rumination",
    "web_connect", "module_email", "module_wake",
})

#: Perception ``source`` values → the channel a handle is registered under.
#: The pipeline labels a browser turn "frontend" while the handle lives on
#: "web"; without this the two never line up.
_CHANNEL_ALIASES = {
    "frontend": "web",
    "websocket": "web",
    "ws": "web",
}


def normalize_channel(channel: str) -> str:
    """Map a perception source onto its canonical channel name."""
    name = (channel or "").strip().lower()
    return _CHANNEL_ALIASES.get(name, name)


def floor_for(trust: ChannelTrust) -> float:
    """Certainty this channel grants before anything is said."""
    return float(_CHANNEL_FLOOR.get(trust, Certainty.UNKNOWN))


def ceiling_for(trust: ChannelTrust) -> float:
    """Hard cap on certainty for this channel, whatever the evidence."""
    return float(_CHANNEL_CEILING.get(trust, Certainty.UNKNOWN))


def apply_evidence(current: float, kind: str, *, trust: ChannelTrust) -> float:
    """Return the new certainty after one piece of evidence.

    Unknown evidence kinds contribute nothing rather than raising: this runs
    on LLM-supplied tool arguments, and a typo must not break a turn.
    """
    delta = EVIDENCE_WEIGHTS.get(kind)
    if delta is None:
        delta = COUNTER_EVIDENCE_WEIGHTS.get(kind, 0.0)
    return clamp(current + delta, trust=trust)


def clamp(value: float, *, trust: ChannelTrust) -> float:
    """Bound a certainty into [0, channel ceiling]."""
    return max(0.0, min(float(value), ceiling_for(trust)))


def label_for(certainty: float) -> Certainty:
    """Nearest named level at or below ``certainty`` (for prompts and logs)."""
    best = Certainty.UNKNOWN
    for level in Certainty:
        if certainty >= float(level) and float(level) >= float(best):
            best = level
    return best


#: Above this, Mika addresses the person as themselves without hedging.
CONFIDENT_THRESHOLD = float(Certainty.CORROBORATED)
#: Minimum certainty to surface private per-person context. Deliberately set
#: *above* CLAIMED: someone typing a name is not a reason to read them that
#: person's history. Something has to corroborate it first.
PRIVATE_CONTEXT_THRESHOLD = float(Certainty.CORROBORATED)


def may_disclose_private_context(certainty: float, trust: ChannelTrust) -> bool:
    """Whether per-person memory (profile, commitments, shared history) may
    be injected into the prompt for this interlocutor.

    The asymmetry is deliberate: being wrong about *who* someone is costs
    little when Mika only greets them, and costs a lot when she recounts what
    someone else told her in confidence. So the bar is not "probably them" but
    "something confirmed it".

    A public room never clears it, at any certainty. Even when Mika is sure
    who is speaking, a group chat is the wrong place to bring up what that
    person told her privately — the risk there isn't mistaken identity, it's
    an audience. She can still greet them warmly and talk normally; she just
    doesn't read out their file.
    """
    if trust is ChannelTrust.INTERNAL:
        return False
    if trust is ChannelTrust.PUBLIC:
        return False
    if trust is ChannelTrust.AUTHENTICATED:
        return True
    return certainty >= PRIVATE_CONTEXT_THRESHOLD


def describe_fr(certainty: float, trust: ChannelTrust, name: str = "") -> str:
    """One French line telling Mika how sure she is, and what that implies.

    This is prompt text, not a debug string: it has to read as a feeling
    ("tu crois reconnaître…") rather than a confidence score, or the model
    will start narrating percentages back at the user.
    """
    who = name or "cette personne"

    if trust is ChannelTrust.AUTHENTICATED:
        return (
            f"Tu sais avec certitude que tu parles a {who} : la personne s'est "
            f"connectee avec son compte. Aucun doute a avoir."
        )

    level = label_for(certainty)
    public = trust is ChannelTrust.PUBLIC
    where = " et vous etes dans un espace public ou n'importe qui peut parler" if public else ""

    if level is Certainty.UNKNOWN:
        return (
            f"Tu ne sais pas qui est cette personne{where}. Reste accueillante "
            f"mais ne suppose rien d'elle, et ne lui raconte rien de personnel "
            f"sur qui que ce soit."
        )
    if level is Certainty.SUSPECTED:
        return (
            f"Tu crois deviner que c'est {who}, sans en etre sure{where}. "
            f"Tu peux le mentionner comme une intuition, pas comme un fait."
        )
    if level is Certainty.CLAIMED:
        return (
            f"Quelqu'un affirme etre {who}, mais rien ne le confirme{where}. "
            f"Tu peux jouer le jeu poliment tout en gardant une reserve : "
            f"evite de lui raconter ce que {who} t'avait confie, tant que tu "
            f"n'en es pas plus sure."
        )
    if level is Certainty.CORROBORATED:
        return (
            f"Tu penses vraiment que c'est {who} : ce qui a ete dit recoupe ce "
            f"que tu sais d'elle/lui{where}. Il te reste une petite reserve."
        )
    return (
        f"Tu reconnais {who} — tu as decide de la/le croire et tu as reliee "
        f"ce contact a ta memoire{where}."
    )


@dataclass(frozen=True)
class TrustDecision:
    """Outcome of evaluating an interlocutor, ready for the prompt layer."""

    certainty: float
    trust: ChannelTrust
    level: Certainty
    may_disclose: bool
    description: str

    @property
    def is_confident(self) -> bool:
        return self.certainty >= CONFIDENT_THRESHOLD


def evaluate(certainty: float, trust: ChannelTrust, name: str = "") -> TrustDecision:
    """Bundle a raw certainty into everything downstream layers need."""
    bounded = clamp(certainty, trust=trust)
    return TrustDecision(
        certainty=bounded,
        trust=trust,
        level=label_for(bounded),
        may_disclose=may_disclose_private_context(bounded, trust),
        description=describe_fr(bounded, trust, name),
    )
