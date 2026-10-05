"""La faculté ``identity`` : adresses, revendications, preuves, liaisons ; ses
réducteurs et ses faits (voir ``__init__`` pour la politique)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import affect as affect_c
from mika.contracts import identity as c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.kernel.clock import DAY, US
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict
from mika.vocab import privacy
from mika.vocab.people import clean_display_name, is_identifiable, is_internal, same_name
from mika.vocab.privacy import ChannelTrust, Disclosure

_TRUST_ORDER = {ChannelTrust.INTERNAL: 0, ChannelTrust.PUBLIC: 1, ChannelTrust.ACCOUNT: 2,
                ChannelTrust.AUTHENTICATED: 3}
#: Les canaux qui prouvent un compte : seuls ceux-là peuvent porter les droits d'une propriétaire.
_PROVEN = frozenset({ChannelTrust.ACCOUNT, ChannelTrust.AUTHENTICATED})
#: Au plus tant de souvenirs recoupés retenus sur une revendication en attente.
HINTS_KEPT = 4


class IdentityParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Adresses de propriétaires sans compte opérateur (un compte du chat, par exemple).
    owners: Annotated[tuple[str, ...], Knob(
        label="Propriétaires (adresses)", group="Propriétaires",
        help="Une adresse par ligne (ex. user_3) traitée comme la propriétaire, sans compte opérateur : récit "
             "complet de ses travaux, outils réservés (forge, caméra…). Seulement sur un canal qui prouve le "
             "compte, et jamais dans un salon public.")] = ()
    #: Deux preuves de recoupement : sur deux messages au moins aussi espacés.
    proof_spacing_us: Annotated[int, Knob(
        label="Recoupement : écart entre les deux preuves", group="Être convaincue", lo=0, hi=DAY,
        help="Pour qu'on la croie sans compte, quelqu'un qui dit être une personne qu'elle connaît doit recouper "
             "ce que seule cette personne savait sur deux messages différents, au moins aussi espacés (dont un "
             "avec un détail rare : un nom propre, un nombre, une date). Jamais dans le message où elle se "
             "présente.")] = 30 * US


@dataclass(frozen=True, slots=True)
class Hint:
    """Un souvenir recoupé, en attente de sa seconde preuve."""

    item: int
    message: int
    at: int
    rare: bool = False


@dataclass(frozen=True, slots=True)
class Claim:
    name: str
    target: str | None
    certainty: float  # enregistrée, avant le plafond du transport
    at: int
    used: tuple[str, ...] = ()  # preuves déjà comptées (identiques : non cumulables)
    #: les premières preuves d'un recoupement (il en faut deux, sur deux messages)
    hints: tuple[Hint, ...] = ()


@dataclass(frozen=True, slots=True)
class Handle:
    channel: str
    trust: ChannelTrust
    first_seen: int
    name: str = ""
    authenticated: bool = False
    operator: bool = False
    push: bool = False
    #: La personne pour laquelle cette adresse parle, si ce n'est pas elle-même.
    person: str | None = None
    certainty: float = 0.0  # de la liaison
    via: str = ""
    claim: Claim | None = None


@dataclass(frozen=True, slots=True)
class IdentityState:
    handles: FrozenDict[str, Handle] = field(default_factory=FrozenDict)
    #: les personnes connues d'abord de nom (``name:alice`` → sa clé), reliées par un opérateur
    names: FrozenDict[str, str] = field(default_factory=FrozenDict)
    #: chaque personne → ses adresses (triées) : celles qui parlent pour elle, et elle-même quand c'est une adresse.
    #: Un index tenu par les réducteurs (``_put``) : « les adresses d'Alice » se lit sans parcourir toutes les
    #: adresses connues — avec trois cents inconnues de passage, chaque calcul de proximité le faisait (ADR 0059).
    by_person: FrozenDict[str, tuple[str, ...]] = field(default_factory=FrozenDict)
    #: les adresses d'une session d'opérateur (triées), tenues de même : « qui sont ses propriétaires ? » ne
    #: parcourt pas toutes les adresses à chaque passage de l'ordonnanceur (ADR 0059)
    operators: tuple[str, ...] = ()


#: une personne connue seulement de nom (une clé de la mémoire)
NAMED = "name:"

#: v2 : revendications à deux preuves, démentis jugés à la lecture, une session ne se relie jamais.
#: v3 : les noms reliés (ADR 0048).
#: v4 : l'index personne → adresses (``by_person``) et les sessions d'opérateur (``operators``), ADR 0059 —
#: reconstruits depuis la genèse.
#: v5 : ``first_seen`` date la première fois qu'elle a été vue (connexion, message), plus la création d'un
#: compte ni une liaison d'opérateur — reconstruit depuis la genèse.
IDENTITY = Faculty("identity", state=IdentityState, init=lambda p: IdentityState(), params=IdentityParams,
                   state_version=5)
IDENTITY.declare(*c.ALL)


def _params(p: IdentityParams | None) -> IdentityParams:
    return p if p is not None else IdentityParams()


def _put(s: IdentityState, handle: str, h: Handle) -> IdentityState:
    """Range une adresse, et tient l'index personne → adresses : une adresse qui change de personne (liée,
    déliée) quitte l'une et rejoint l'autre ; une personne sans plus aucune adresse sort de l'index."""
    old = s.handles.get(handle)
    before = (old.person or handle) if old is not None else None
    after = h.person or handle
    by_person = s.by_person
    if before != after:
        if before is not None:
            left = tuple(k for k in by_person.get(before, ()) if k != handle)
            by_person = by_person.set(before, left) if left else by_person.delete(before)
        by_person = by_person.set(after, tuple(sorted({*by_person.get(after, ()), handle})))
    operators = s.operators
    if (h.authenticated and h.operator) != (handle in operators):
        operators = tuple(sorted({*operators, handle} if h.authenticated and h.operator else
                                 set(operators) - {handle}))
    return replace(s, handles=s.handles.set(handle, h), by_person=by_person, operators=operators)


# ── Ce qu'on voit passer ──────────────────────────────────────────────────


def _seen(s: IdentityState, handle: str, at: int, *, channel: str, authenticated: bool, public: bool,
          name: str, operator: bool | None) -> IdentityState:
    """``at`` à 0 : l'adresse existe sans avoir été vue (un compte créé) — ``first_seen`` attend sa
    première connexion ou son premier message, sinon elle « se connaîtraient » depuis la création du compte."""
    if not handle or is_internal(handle):
        return s
    # ce que prouve le transport, indépendamment de l'auditoire : un compte
    # extérieur reste un compte dans un salon (c'est la salle qui est publique)
    trust = privacy.channel_trust(channel, authenticated=authenticated)
    current = s.handles.get(handle)
    if current is None:
        current = Handle(channel=privacy.normalize_channel(channel), trust=trust, first_seen=at)
    elif not current.first_seen and at:
        current = replace(current, first_seen=at)
    if _TRUST_ORDER[trust] > _TRUST_ORDER[current.trust]:
        current = replace(current, trust=trust)  # monte, ne descend jamais
    if privacy.is_messaging(channel) and not public and not authenticated and not current.push:
        # une conversation privée sur un compte extérieur : on peut lui écrire. Un compte du système, lui, n'est
        # joignable que par ce que dit ``identity.registered`` (une application qui reçoit hors ligne) : ça se
        # retire quand l'application part, ce qu'une adresse vue une fois ne dirait jamais
        current = replace(current, push=True)
    cleaned = clean_display_name(name)
    if authenticated:
        # une session prouve qui écrit : elle parle pour elle-même, jamais pour une autre
        current = replace(_unbound(current), authenticated=True, name=cleaned or current.name, claim=None)
        if operator is not None:
            current = replace(current, operator=operator)
    elif cleaned and not current.name:
        current = replace(current, name=cleaned)
    return _put(s, handle, current)


@IDENTITY.reducer(presence_c.CONNECTED)
def _connected(s: IdentityState, e, cx) -> IdentityState:
    d = e.data
    return _seen(s, d.handle, e.at, channel=d.channel, authenticated=d.authenticated, public=d.public,
                 name=d.display_name, operator=d.operator if d.authenticated else None)


@IDENTITY.reducer(c.REGISTERED)
def _registered(s: IdentityState, e, cx) -> IdentityState:
    """Un compte : une personne authentifiée sous son nom. Le nom du compte fait foi (un
    renommage s'applique) ; un compte désactivé n'est plus opérateur, ni joignable."""
    d = e.data
    # authentifiée : ``_seen`` prend le nom donné s'il en est un (un renommage s'applique). Un compte existe,
    # il n'est pas vu pour autant : ``first_seen`` attend sa première connexion
    s = _seen(s, d.handle, 0, channel=privacy.WEB, authenticated=True, public=False, name=d.name,
              operator=d.operator and d.active)
    current = s.handles.get(d.handle)
    if d.messaging is None or current is None:
        return s  # un journal d'avant l'application : rien n'est dit de la joignabilité
    # une application qui reçoit hors ligne (ADR 0062) : on peut lui écrire absente, sur ce canal ; plus
    # d'application : plus de joignabilité — le canal redevient l'écran
    reachable = bool(d.messaging) and d.active
    channel = privacy.normalize_channel(d.messaging) if reachable else privacy.WEB
    if (current.push, current.channel) == (reachable, channel):
        return s
    return _put(s, d.handle, replace(current, push=reachable, channel=channel))


@IDENTITY.reducer(rt.PERCEPTION_RECEIVED)
def _perceived(s: IdentityState, e, cx) -> IdentityState:
    d = e.data
    return _seen(s, d.handle, e.at, channel=d.channel, authenticated=d.authenticated, public=d.public,
                 name=d.display_name, operator=None)


# ── Revendications, preuves, liaisons ─────────────────────────────────────


def _unbound(h: Handle) -> Handle:
    return replace(h, person=None, certainty=0.0, via="")


def _claim_of(h: Handle, name: str, target: str | None, at: int, public: bool) -> Claim:
    trust = ChannelTrust.PUBLIC if public else h.trust
    base = privacy.apply_evidence(privacy.FLOORS[trust], "self_declared", trust)
    return Claim(name, target, base, at, ("self_declared",))


@IDENTITY.reducer(c.CLAIMED)
def _claimed(s: IdentityState, e, cx) -> IdentityState:
    d = e.data
    h = s.handles.get(d.handle)
    name = clean_display_name(d.name)
    if h is None or h.authenticated or not name:
        return s  # une session prouve déjà qui parle : « je suis Thomas » y est une blague
    if h.claim is not None and h.claim.target == d.target and same_name(name, h.claim.name) \
            and live_claim(h, e.at) is not None:
        return s  # elle le redit : la revendication en cours, et ses preuves, restent
    if d.target == d.handle:
        # personne d'autre ne porte ce nom : elle se présente. Une adresse liée ou déjà nommée
        # autrement ne se délie ni ne se renomme sur une phrase (« moi c'est pizza ce soir ») :
        # c'est une revendication, qui n'ouvre rien et ne défait rien
        if h.person or (h.name and not same_name(name, h.name)):
            h = replace(h, claim=_claim_of(h, name, d.handle, e.at, d.public))
        else:
            h = replace(h, name=h.name or name, claim=None)
    elif d.target is not None and d.target == h.person:
        return s  # elle le savait déjà
    else:
        # une autre identité revendiquée défait la liaison en cours : la
        # certitude gagnée pour l'une ne vaut rien pour l'autre
        h = replace(_unbound(h), claim=_claim_of(h, name, d.target, e.at, d.public))
    return _put(s, d.handle, h)


def aims_elsewhere(h: Handle, handle: str, claim: Claim | None = None) -> bool:
    """Sa revendication vise-t-elle une autre personne qu'elle connaît ? (Pas un simple
    nom qu'elle se donne — celui-là vise l'adresse elle-même — ni la personne liée.)"""
    claim = h.claim if claim is None else claim
    return claim is not None and claim.target is not None and claim.target not in (handle, h.person)


def denial_target(h: Handle, name: str, now: int = 0, person_name: str = "") -> str:
    """Ce que vise un démenti (« je ne suis pas Alice ») : sa liaison si c'est le
    nom de la personne liée (celui de l'adresse, ou ``person_name``, celui sous
    lequel elle connaît la personne), sa revendication si c'est le nom
    revendiqué, le nom qu'elle lui prête ; rien sinon (« c'est pas grave »)."""
    if h.person and (same_name(name, h.name) or (person_name and same_name(name, person_name))):
        return c.DENIES_BINDING
    if h.claim is not None and same_name(name, h.claim.name) and live_claim(h, now) is not None:
        return c.DENIES_CLAIM
    if h.name and same_name(name, h.name):
        return c.DENIES_NAME
    return ""


def _hinted(h: Handle, e: Any) -> Handle:
    d = e.data
    claim = h.claim
    if claim is None or not aims_elsewhere(h, d.handle) or d.item is None:
        return h
    if any(x.item == d.item for x in claim.hints):
        return h
    hint = Hint(int(d.item), int(d.message or 0), e.at, bool(d.rare))
    return replace(h, claim=replace(claim, hints=(*claim.hints, hint)[-HINTS_KEPT:]))


def _apply(h: Handle, e: Any) -> Handle:
    d = e.data
    bar = privacy.POLICY.private_threshold
    if d.kind == c.SHARED_HINT:
        return _hinted(h, e)
    if d.kind == c.SHARED_MEMORY:
        claim = h.claim
        if claim is None or not aims_elsewhere(h, d.handle):
            return h
        mark = f"item:{d.item}"
        if c.SHARED_MEMORY in claim.used or mark in claim.used:
            return h  # la même sorte de preuve ne compte qu'une fois
        certainty = privacy.apply_evidence(claim.certainty, c.SHARED_MEMORY, h.trust)
        claim = replace(claim, certainty=certainty, used=(*claim.used, c.SHARED_MEMORY, mark))
        if certainty >= bar:
            return replace(h, person=claim.target, certainty=certainty, via=c.VIA_CORROBORATED, name=claim.name,
                           claim=None)
        return replace(h, claim=claim)
    if d.kind == c.VOUCHED:
        # un opérateur se porte garant de la revendication : une preuve de plus,
        # pesée comme les autres (seule, elle ne franchit pas la barre en public)
        claim = h.claim
        if claim is None or not aims_elsewhere(h, d.handle) or c.VOUCHED in claim.used:
            return h
        certainty = privacy.apply_evidence(claim.certainty, c.VOUCHED, h.trust)
        claim = replace(claim, certainty=certainty, used=(*claim.used, c.VOUCHED))
        if certainty >= bar:
            return replace(h, person=claim.target, certainty=certainty, via=c.VIA_VOUCHED, name=claim.name,
                           claim=None)
        return replace(h, claim=claim)
    if d.kind == c.DENIED:
        target = d.denies or (denial_target(h, d.legacy_name) if d.legacy_name else "")
        if target == c.DENIES_BINDING and h.person:
            certainty = privacy.apply_evidence(h.certainty, c.DENIED, h.trust)
            h = _unbound(h) if certainty < bar else replace(h, certainty=certainty)
            return replace(h, name="") if h.person is None else h
        if target == c.DENIES_CLAIM and h.claim is not None:
            return replace(h, claim=None)
        if target == c.DENIES_NAME and h.name:
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
    return _put(s, e.data.handle, _apply(h, e))


@IDENTITY.reducer(c.LINKED)
def _linked(s: IdentityState, e, cx) -> IdentityState:
    d = e.data
    if not d.handle or is_internal(d.handle):
        return s
    h = s.handles.get(d.handle)
    if h is None:
        # l'opérateur peut relier une adresse avant qu'elle ait écrit : pas encore vue
        channel = privacy.channel_of(d.handle)
        h = Handle(channel=channel, trust=privacy.channel_trust(channel), first_seen=0)
    if h.authenticated:
        return s  # une session parle pour elle-même : on ne la relie à personne
    if d.person is None or d.person == d.handle:
        h = replace(_unbound(h), claim=None)
    else:
        root = _root(s, d.person)
        if root == d.handle:
            return s
        h = replace(h, person=root, certainty=privacy.BOUND, via=c.VIA_OPERATOR, claim=None)
    return _put(s, d.handle, h)


@IDENTITY.reducer(c.NAME_BOUND)
def _name_bound(s: IdentityState, e, cx) -> IdentityState:
    d = e.data
    if not d.name.startswith(NAMED):
        return s
    if d.person is None:
        return replace(s, names=s.names.delete(d.name)) if d.name in s.names else s
    person = _root(s, d.person)
    if person.startswith(NAMED) or is_internal(person):
        return s
    return replace(s, names=s.names.set(d.name, person))


# ── Lectures ──────────────────────────────────────────────────────────────


def _root(s: IdentityState, key: str) -> str:
    """La clé de personne d'une adresse (jamais de chaîne : une liaison vise
    toujours une personne racine) ; un nom relié par un opérateur, sa personne."""
    if key.startswith(NAMED):
        return s.names.get(key, key)
    h = s.handles.get(key)
    return h.person if h is not None and h.person else key


def handles_of(s: IdentityState, person: str) -> tuple[str, ...]:
    """Les adresses d'une personne (triées) : celles qui parlent pour elle, et elle-même si c'est une adresse."""
    return s.by_person.get(person, ())


def confirmed(h: Handle) -> bool:
    """Une adresse qui parle pour elle-même, ou reliée par une décision d'opérateur."""
    return not h.person or h.via in c.CONFIRMED_VIA


def thread_of(s: IdentityState, handle: str) -> tuple[str, ...]:
    """Les adresses dont le fil verbatim peut se montrer à qui écrit par ``handle``."""
    h = s.handles.get(handle)
    if h is not None and not confirmed(h):
        return (handle,)  # par simple recoupement : son propre fil, rien de plus tant qu'on n'a pas confirmé
    person = _root(s, handle)
    out = {handle, person} | {k for k in handles_of(s, person) if confirmed(s.handles[k])}
    return tuple(sorted(out))


def _first_seen(s: IdentityState, person: str, fallback: int) -> int:
    """La première fois qu'elle a été vue, toutes adresses ; 0 : jamais encore (un compte créé, une adresse
    reliée avant d'avoir écrit)."""
    seen = [s.handles[k].first_seen for k in handles_of(s, person) if k in s.handles and s.handles[k].first_seen]
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
    elle ; aucune → l'adresse elle-même (elle se présente) ; plusieurs →
    ``None`` (on ne peut pas savoir laquelle). Ne fondent une personne que
    les adresses qui se prouvent (compte, liaison) ; une revendication en
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


def live_claim(h: Handle, now: int) -> Claim | None:
    """Sa revendication, si elle ne s'est pas éteinte (jamais confirmée à temps)."""
    claim = h.claim
    if claim is not None and now and now - claim.at > privacy.POLICY.pending_claim_ttl_days * DAY:
        return None
    return claim


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
    claim = live_claim(h, now)  # une revendication jamais confirmée s'éteint
    person = h.person or handle
    return c.IdentityView(
        handle=handle, person=person, name=h.name, trust=h.trust, certainty=_certainty(h, h.trust),
        authenticated=h.authenticated, operator=h.operator, known=True, bound=bool(h.person),
        claim=claim.name if claim else "", claim_certainty=privacy.effective(claim.certainty, h.trust) if claim else 0.0,
        claim_target=claim.target if claim else None, channel=h.channel, push=h.push,
        first_seen=_first_seen(s, person, h.first_seen), via=h.via if h.person else "",
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
    return tuple(k for k in handles_of(s, person) if s.handles[k].push and confirmed(s.handles[k]))


@IDENTITY.fact(c.THREAD)
def _thread(s: IdentityState, cx, handle: str) -> tuple[str, ...]:
    return thread_of(s, handle)


def proves_owner(key: str, h: Handle | None, declared: set[str] | frozenset[str]) -> bool:
    """Cette adresse prouve-t-elle d'elle-même être une propriétaire ? Une session
    d'opérateur, ou une adresse déclarée sur un canal qui prouve le compte."""
    if h is None:
        return False
    if h.authenticated and h.operator:
        return True
    return key in declared and h.trust in _PROVEN


def owner_person(s: IdentityState, person: str, declared: set[str] | frozenset[str]) -> bool:
    """La personne est-elle une propriétaire : une de ses adresses le prouve (ou une adresse
    déclarée qui n'a encore jamais écrit)."""
    for k in handles_of(s, person) or (person,):
        h = s.handles.get(k)
        if proves_owner(k, h, declared) or (h is None and k in declared):
            return True
    return False


def speaks_as_owner(s: IdentityState, handle: str, declared: set[str] | frozenset[str]) -> bool:
    """Qui écrit par cette adresse a-t-il les droits d'une propriétaire ? Elle le
    prouve elle-même, ou un opérateur l'a reliée à une propriétaire sur un canal
    qui prouve le compte. Jamais une liaison par recoupement ou garantie."""
    h = s.handles.get(handle)
    if h is None or is_internal(handle) or not is_identifiable(handle) or h.trust not in _PROVEN:
        return False
    if proves_owner(handle, h, declared):
        return True
    return bool(h.person) and h.via == c.VIA_OPERATOR and owner_person(s, h.person, declared)


@IDENTITY.fact(c.IS_OWNER)
def _is_owner(s: IdentityState, cx, person: str) -> bool:
    return owner_person(s, person, set(_params(cx.params).owners))


@IDENTITY.fact(c.SPEAKS_AS_OWNER)
def _speaks_as_owner(s: IdentityState, cx, handle: str) -> bool:
    return speaks_as_owner(s, handle, set(_params(cx.params).owners))


@IDENTITY.fact(c.OWNERS)
def _owners(s: IdentityState, cx) -> tuple[str, ...]:
    declared = set(_params(cx.params).owners)
    # les adresses qui le prouvent : une session d'opérateur, ou une adresse déclarée (seulement elles)
    proving = [*s.operators, *(k for k in declared if proves_owner(k, s.handles.get(k), declared))]
    out = {_root(s, k) for k in proving}
    out |= {k for k in declared if k not in s.handles}
    return tuple(sorted(out))


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
