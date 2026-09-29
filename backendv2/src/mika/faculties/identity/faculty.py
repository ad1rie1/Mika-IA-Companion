"""La faculté ``identity`` : poignées, revendications, preuves, liaisons ; ses
réducteurs et ses faits (voir ``__init__`` pour la politique)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import affect as affect_c
from mika.contracts import identity as c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.kernel.faculty import Faculty
from mika.kernel.state import FrozenDict
from mika.vocab import privacy
from mika.vocab.people import clean_display_name, is_identifiable, is_internal, same_name
from mika.vocab.privacy import ChannelTrust, Disclosure

_TRUST_ORDER = {ChannelTrust.INTERNAL: 0, ChannelTrust.PUBLIC: 1, ChannelTrust.ACCOUNT: 2,
                ChannelTrust.AUTHENTICATED: 3}
_PUSH_CHANNELS = frozenset({"telegram"})


class IdentityParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Poignées de propriétaires sans compte opérateur (un Telegram, par exemple).
    owners: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Claim:
    name: str
    target: str | None
    certainty: float  # enregistrée, avant le plafond du transport
    at: int
    used: tuple[str, ...] = ()  # preuves déjà comptées (identiques : non cumulables)


@dataclass(frozen=True, slots=True)
class Handle:
    channel: str
    trust: ChannelTrust
    first_seen: int
    name: str = ""
    authenticated: bool = False
    operator: bool = False
    push: bool = False
    #: La personne pour laquelle cette poignée parle, si ce n'est pas elle-même.
    person: str | None = None
    certainty: float = 0.0  # de la liaison
    via: str = ""
    claim: Claim | None = None


@dataclass(frozen=True, slots=True)
class IdentityState:
    handles: FrozenDict[str, Handle] = field(default_factory=FrozenDict)


IDENTITY = Faculty("identity", state=IdentityState, init=lambda p: IdentityState(), params=IdentityParams)
IDENTITY.declare(*c.ALL)


def _params(p: IdentityParams | None) -> IdentityParams:
    return p if p is not None else IdentityParams()


# ── Ce qu'on voit passer ──────────────────────────────────────────────────


def _seen(s: IdentityState, handle: str, at: int, *, channel: str, authenticated: bool, public: bool,
          name: str, operator: bool | None) -> IdentityState:
    if not handle or is_internal(handle):
        return s
    # ce que prouve le transport, indépendamment de l'auditoire : un compte
    # Telegram reste un compte dans un groupe (c'est la salle qui est publique)
    trust = privacy.channel_trust(channel, authenticated=authenticated)
    current = s.handles.get(handle)
    if current is None:
        current = Handle(channel=privacy.normalize_channel(channel), trust=trust, first_seen=at)
    if _TRUST_ORDER[trust] > _TRUST_ORDER[current.trust]:
        current = replace(current, trust=trust)  # monte, ne descend jamais
    if privacy.normalize_channel(channel) in _PUSH_CHANNELS and not public and not current.push:
        current = replace(current, push=True)  # une conversation privée : on peut lui écrire
    cleaned = clean_display_name(name)
    if authenticated:
        current = replace(current, authenticated=True, name=cleaned or current.name)
        if operator is not None:
            current = replace(current, operator=operator)
    elif cleaned and not current.name:
        current = replace(current, name=cleaned)
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


# ── Revendications, preuves, liaisons ─────────────────────────────────────


def _unbound(h: Handle) -> Handle:
    return replace(h, person=None, certainty=0.0, via="")


@IDENTITY.reducer(c.CLAIMED)
def _claimed(s: IdentityState, e, cx) -> IdentityState:
    d = e.data
    h = s.handles.get(d.handle)
    name = clean_display_name(d.name)
    if h is None or h.authenticated or not name:
        return s  # une session prouve déjà qui parle : « je suis Thomas » y est une blague
    if d.target == d.handle:
        # personne d'autre ne porte ce nom : elle se présente
        h = replace(_unbound(h) if h.person else h, name=name, claim=None)
    elif d.target is not None and d.target == h.person:
        return s  # elle le savait déjà
    else:
        trust = ChannelTrust.PUBLIC if d.public else h.trust
        base = privacy.apply_evidence(privacy.FLOORS[trust], "self_declared", trust)
        # une autre identité revendiquée défait la liaison en cours : la
        # certitude gagnée pour l'une ne vaut rien pour l'autre
        h = replace(_unbound(h), claim=Claim(name, d.target, base, e.at, ("self_declared",)))
    return replace(s, handles=s.handles.set(d.handle, h))


def _apply(h: Handle, e: Any) -> Handle:
    d = e.data
    bar = privacy.POLICY.private_threshold
    if d.kind == c.SHARED_MEMORY:
        claim = h.claim
        if claim is None or claim.target is None or claim.target == h.person:
            return h
        mark = f"item:{d.item}"
        if c.SHARED_MEMORY in claim.used or mark in claim.used:
            return h  # la même sorte de preuve ne compte qu'une fois
        certainty = privacy.apply_evidence(claim.certainty, c.SHARED_MEMORY, h.trust)
        claim = replace(claim, certainty=certainty, used=(*claim.used, c.SHARED_MEMORY, mark))
        if certainty >= bar:
            return replace(h, person=claim.target, certainty=certainty, via="corroborated", name=claim.name,
                           claim=None)
        return replace(h, claim=claim)
    if d.kind == c.DENIED:
        if h.person and same_name(d.name, h.name):
            certainty = privacy.apply_evidence(h.certainty, c.DENIED, h.trust)
            h = _unbound(h) if certainty < bar else replace(h, certainty=certainty)
            return replace(h, name="") if h.person is None else h
        if h.claim and same_name(d.name, h.claim.name):
            return replace(h, claim=None)
        if same_name(d.name, h.name):
            return replace(h, name="")
        return h  # « c'est pas grave » : aucun nom qu'elle lui connaisse
    if d.kind == c.CONTRADICTED:
        if h.person:
            certainty = privacy.apply_evidence(h.certainty, c.CONTRADICTED, h.trust)
            return _unbound(h) if certainty < bar else replace(h, certainty=certainty)
        if h.claim:
            certainty = privacy.apply_evidence(h.claim.certainty, c.CONTRADICTED, h.trust)
            floor = privacy.FLOORS[h.trust]
            return replace(h, claim=None if certainty <= floor else replace(h.claim, certainty=certainty))
        return h
    if d.kind == c.REVOKED:
        return replace(_unbound(h), claim=None)
    return h


@IDENTITY.reducer(c.EVIDENCE)
def _evidence(s: IdentityState, e, cx) -> IdentityState:
    h = s.handles.get(e.data.handle)
    if h is None or h.authenticated:
        return s
    return replace(s, handles=s.handles.set(e.data.handle, _apply(h, e)))


@IDENTITY.reducer(c.LINKED)
def _linked(s: IdentityState, e, cx) -> IdentityState:
    d = e.data
    if not d.handle or is_internal(d.handle):
        return s
    h = s.handles.get(d.handle)
    if h is None:
        # l'opérateur peut relier une poignée avant qu'elle ait écrit
        channel = "telegram" if d.handle.startswith("tg_") else "web"
        h = Handle(channel=channel, trust=privacy.channel_trust(channel), first_seen=e.at)
    if d.person is None or d.person == d.handle:
        h = replace(_unbound(h), claim=None)
    else:
        root = _root(s, d.person)
        if root == d.handle:
            return s
        h = replace(h, person=root, certainty=privacy.BOUND, via="operator", claim=None)
    return replace(s, handles=s.handles.set(d.handle, h))


# ── Lectures ──────────────────────────────────────────────────────────────


def _root(s: IdentityState, key: str) -> str:
    """La clé de personne d'une poignée (jamais de chaîne : une liaison vise
    toujours une personne racine)."""
    h = s.handles.get(key)
    return h.person if h is not None and h.person else key


def handles_of(s: IdentityState, person: str) -> tuple[str, ...]:
    out = {k for k, h in s.handles.items() if (h.person or k) == person}
    return tuple(sorted(out))


def _first_seen(s: IdentityState, person: str, fallback: int) -> int:
    seen = [s.handles[k].first_seen for k in handles_of(s, person) if k in s.handles]
    return min(seen) if seen else fallback


def _name_of(s: IdentityState, person: str) -> str:
    h = s.handles.get(person)
    if h is not None and h.name:
        return h.name
    if person.startswith("name:"):
        return person[5:].title()
    for k in handles_of(s, person):
        if s.handles[k].name:
            return s.handles[k].name
    return ""


def resolve_target(s: IdentityState, handle: str, name: str) -> str | None:
    """Qui « Alice » désigne-t-il ? Une seule personne connue sous ce nom →
    elle ; aucune → la poignée elle-même (elle se présente) ; plusieurs →
    ``None`` (on ne peut pas savoir laquelle). Ne fondent une personne que
    les poignées qui se prouvent (compte, liaison) ; une revendication en
    attente n'en fonde aucune."""
    found: set[str] = set()
    for key, h in s.handles.items():
        if key == handle:
            continue
        if not (h.authenticated or h.person or h.trust is ChannelTrust.ACCOUNT):
            continue
        if h.claim is not None and not h.person:
            continue
        person = h.person or key
        if person != handle and same_name(name, _name_of(s, person)):
            found.add(person)
    if not found:
        return handle
    return found.pop() if len(found) == 1 else None


def _certainty(h: Handle, trust: ChannelTrust) -> float:
    if h.authenticated:
        return privacy.VERIFIED
    if h.person:
        return privacy.effective(h.certainty, trust)
    # elle-même : aussi sûre que son transport prouve la continuité du compte
    return privacy.CEILINGS[trust] if trust is ChannelTrust.ACCOUNT else privacy.effective(0.0, trust)


def view_of(s: IdentityState, handle: str, now: int = 0) -> c.IdentityView:
    h = s.handles.get(handle)
    if h is None:
        trust = ChannelTrust.INTERNAL if is_internal(handle) else ChannelTrust.PUBLIC
        return c.IdentityView(handle, handle, "", trust, 0.0, False, False, False)
    claim = h.claim
    if claim is not None and now and now - claim.at > privacy.POLICY.pending_claim_ttl_days * 86_400_000_000:
        claim = None  # une revendication jamais confirmée s'éteint
    person = h.person or handle
    return c.IdentityView(
        handle=handle, person=person, name=h.name, trust=h.trust, certainty=_certainty(h, h.trust),
        authenticated=h.authenticated, operator=h.operator, known=True, bound=bool(h.person),
        claim=claim.name if claim else "", claim_certainty=privacy.effective(claim.certainty, h.trust) if claim else 0.0,
        claim_target=claim.target if claim else None, channel=h.channel, push=h.push,
        first_seen=_first_seen(s, person, h.first_seen),
    )


@IDENTITY.fact(c.PERSON)
def _person(s: IdentityState, cx, handle: str) -> str:
    return _root(s, handle) or handle


@IDENTITY.fact(c.IDENTITY)
def _identity(s: IdentityState, cx, handle: str) -> c.IdentityView:
    return view_of(s, handle, cx.now)


@IDENTITY.fact(c.HANDLES)
def _handles(s: IdentityState, cx, person: str) -> tuple[str, ...]:
    return handles_of(s, person)


@IDENTITY.fact(c.REACHABLE)
def _reachable(s: IdentityState, cx, person: str) -> tuple[str, ...]:
    return tuple(k for k in handles_of(s, person) if s.handles[k].push)


@IDENTITY.fact(c.IS_OWNER)
def _is_owner(s: IdentityState, cx, person: str) -> bool:
    owners = set(_params(cx.params).owners)
    for k in handles_of(s, person) or (person,):
        h = s.handles.get(k)
        if k in owners or (h is not None and h.authenticated and h.operator):
            return True
    return False


@IDENTITY.fact(c.DISCLOSURE, reads=[affect_c.WARMTH, social_c.CLOSENESS])
def _disclosure(s: IdentityState, cx, arg: tuple[Any, ...]) -> Disclosure:
    try:
        handle, channel, public = arg
    except (TypeError, ValueError):
        return privacy.CLOSED
    if not isinstance(handle, str) or is_internal(handle):
        return privacy.CLOSED
    h = s.handles.get(handle)
    if h is None:
        trust = privacy.channel_trust(channel)
        return privacy.decide(privacy.effective(0.0, trust), trust, public=bool(public))
    person = _root(s, handle)
    identifiable = is_identifiable(handle)
    warmth = cx.facts.get(affect_c.WARMTH(person)) if identifiable else 0.0
    closeness = cx.facts.get(social_c.CLOSENESS(person)) if identifiable else ""
    return privacy.decide(_certainty(h, h.trust), h.trust, closeness=closeness, warmth=warmth,
                          public=bool(public) or h.trust is ChannelTrust.PUBLIC)


@IDENTITY.invariant("calibration de la confiance")
def _calibration(params: Any) -> str | None:
    return privacy.POLICY.check()


def known_as(s: IdentityState, person: str) -> str:
    """Le nom sous lequel elle connaît une personne (repli : la clé)."""
    return _name_of(s, person) or person
