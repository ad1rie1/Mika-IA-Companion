"""``identity`` : qui est derrière chaque poignée, et ce que ça ouvre.

En M1 : les poignées vues (connexion, message), la liaison d'un compte
authentifié (la session le prouve : certitude pleine), la divulgation par
audience et la ligne « qui tu as en face ». Les revendications, preuves et
démentis arrivent en M3. Dans le doute, tout se ferme.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import identity as c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.kernel.faculty import Faculty, Zone
from mika.kernel.frame import CLOSED as CLOSED_AUDIENCE
from mika.kernel.frame import Audience, Frame
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.vocab import privacy
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.people import clean_display_name, is_identifiable, is_internal
from mika.vocab.privacy import ChannelTrust, Disclosure

_TRUST_ORDER = {ChannelTrust.INTERNAL: 0, ChannelTrust.PUBLIC: 1, ChannelTrust.ACCOUNT: 2,
                ChannelTrust.AUTHENTICATED: 3}


@dataclass(frozen=True, slots=True)
class Handle:
    channel: str
    trust: ChannelTrust
    first_seen: int
    name: str = ""
    authenticated: bool = False
    operator: bool = False
    certainty: float = 0.0
    person: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityState:
    handles: FrozenDict[str, Handle] = field(default_factory=FrozenDict)


IDENTITY = Faculty("identity", state=IdentityState, init=lambda p: IdentityState())


def _seen(s: IdentityState, handle: str, at: int, *, channel: str, authenticated: bool, public: bool,
          name: str, operator: bool | None) -> IdentityState:
    if not handle or is_internal(handle):
        return s
    trust = privacy.channel_trust(channel, authenticated=authenticated, public=public)
    current = s.handles.get(handle)
    if current is None:
        current = Handle(channel=privacy.normalize_channel(channel), trust=trust, first_seen=at)
    # la confiance d'une poignée monte, ne descend jamais (un message en salon
    # public ne fait pas oublier qu'elle s'est connectée)
    if _TRUST_ORDER[trust] > _TRUST_ORDER[current.trust]:
        current = replace(current, trust=trust)
    cleaned = clean_display_name(name)
    if authenticated:
        current = replace(current, authenticated=True, certainty=privacy.VERIFIED, person=handle,
                          name=cleaned or current.name)
        if operator is not None:
            current = replace(current, operator=operator)
    elif cleaned and not current.authenticated:
        current = replace(current, name=cleaned)
    if current.certainty < privacy.FLOORS[current.trust]:
        current = replace(current, certainty=privacy.FLOORS[current.trust])
    return replace(s, handles=s.handles.set(handle, current))


@IDENTITY.reducer(presence_c.CONNECTED)
def _connected(s: IdentityState, e, cx) -> IdentityState:
    d = e.data
    return _seen(s, d.handle, e.at, channel=d.channel, authenticated=d.authenticated, public=d.public,
                 name=d.display_name, operator=d.operator if d.authenticated else None)


@IDENTITY.reducer(rt.PERCEPTION_RECEIVED)
def _perceived(s: IdentityState, e, cx) -> IdentityState:
    d = e.data
    return _seen(s, d.handle, e.at, channel=d.channel, authenticated=d.authenticated, public=d.public,
                 name=d.display_name, operator=None)


def _view(s: IdentityState, handle: str, *, channel: str | None = None, public: bool = False) -> c.IdentityView:
    h = s.handles.get(handle)
    if h is None:
        trust = privacy.channel_trust(channel or "", public=public)
        return c.IdentityView(handle, handle, "", trust, privacy.effective(0.0, trust), False, False, False)
    turn_channel = channel or h.channel
    trust = privacy.channel_trust(turn_channel, authenticated=h.authenticated and not public, public=public)
    if not h.authenticated and not public and _TRUST_ORDER[h.trust] > _TRUST_ORDER[trust]:
        trust = h.trust
    return c.IdentityView(
        handle=handle, person=h.person or handle, name=h.name, trust=trust,
        certainty=privacy.effective(h.certainty, trust), authenticated=h.authenticated,
        operator=h.operator, known=True,
    )


@IDENTITY.fact(c.PERSON)
def _person(s: IdentityState, cx, handle: str) -> str:
    h = s.handles.get(handle)
    return (h.person if h is not None and h.person else handle) or handle


@IDENTITY.fact(c.IDENTITY)
def _identity(s: IdentityState, cx, handle: str) -> c.IdentityView:
    return _view(s, handle)


@IDENTITY.fact(c.DISCLOSURE, reads=[affect_c.WARMTH])
def _disclosure(s: IdentityState, cx, arg: tuple[Any, ...]) -> Disclosure:
    try:
        handle, channel, public = arg
    except (TypeError, ValueError):
        return privacy.CLOSED
    if not isinstance(handle, str) or is_internal(handle):
        return privacy.CLOSED
    view = _view(s, handle, channel=channel, public=bool(public))
    warmth = cx.facts.get(affect_c.WARMTH(view.person)) if is_identifiable(handle) else 0.0
    return privacy.decide(view.certainty, view.trust, warmth=warmth, public=bool(public))


@IDENTITY.invariant("calibration de la confiance")
def _calibration(params: Any) -> str | None:
    return privacy.POLICY.check()


@IDENTITY.section("who", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=90, floor_chars=400,
                  title="QUI TU AS EN FACE")
def _who(s: IdentityState, frame: Frame, enrich: Any) -> SectionBody | None:
    aud = frame.audience
    ep = frame.episode
    if aud is None or ep is None or not ep.target:
        return None
    trust = ChannelTrust(aud.trust) if aud.trust in ChannelTrust.__members__.values() else ChannelTrust.PUBLIC
    return SectionBody(privacy.describe_fr(aud.certainty, trust, aud.name))


def audience_for(frame: Frame, req: Any) -> Audience:
    """L'audience d'un épisode, résolue une fois au bord. Toute panne → fermée."""
    target = getattr(req, "target", None)
    kind = getattr(req, "kind", "")
    if not target:
        if kind in (Kind.REPLY, Kind.INITIATIVE):
            return CLOSED_AUDIENCE
        # un épisode sans destinataire (pas de travail, murmure, journal) : personne n'écoute
        d = privacy.EVERYTHING
        return Audience(persons=(), channel="internal", public=False, level=int(d.level),
                        witness_level=int(d.witness_level), private_ok=True, trust=ChannelTrust.INTERNAL.value)
    s: IdentityState = frame.state("identity")
    room = getattr(req, "room", None)
    public = room is not None
    h = s.handles.get(target)
    channel = getattr(req, "channel", None) or (h.channel if h else "web")
    view = _view(s, target, channel=channel, public=public)
    d = frame.get(c.DISCLOSURE((target, channel, public)))
    return Audience(
        persons=(target,), channel=channel, room=room, public=public or view.trust is ChannelTrust.PUBLIC,
        level=int(d.level), witness_level=int(d.witness_level), private_ok=d.own_file, trust=view.trust.value,
        certainty=view.certainty, name=view.name,
    )
