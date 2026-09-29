"""La faculté ``social`` : sa tranche, ses paramètres, ses réducteurs, ses faits."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace

from pydantic import BaseModel, ConfigDict

from mika.contracts import affect as affect_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import social as c
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import Faculty
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import Kind
from mika.vocab.people import fold, is_identifiable

KEEP_DAYS = 64


class SocialParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # le rythme d'une relation : l'écart médian entre les jours où la personne écrit
    rhythm_window_days: int = 90
    rhythm_min_days: float = 1.0
    rhythm_max_days: float = 30.0
    rhythm_min_gaps: int = 2
    fallback_close_days: float = 3.0
    fallback_friend_days: float = 7.0
    fallback_other_days: float = 14.0
    # la proximité naît de l'histoire vécue (jours distincts, messages reçus) et
    # de ce qu'elle a installé (le regard d'``affect`` : jamais amie d'une rancune)
    acquaintance_days: int = 2  # s'être parlé deux jours différents…
    acquaintance_messages: int = 20  # … ou longuement : dix minutes d'insultes ne font pas une connaissance
    friend_days: int = 3
    friend_messages: int = 15
    close_days: int = 7
    close_messages: int = 50
    #: proche : de la chaleur installée — ou une longue histoire (un chagrin partagé n'éloigne pas)
    close_regard: float = 0.1
    close_long_days: int = 14
    # reprendre contact : un silence d'une fois et demie son rythme
    recontact_factor: float = 1.5
    recontact_evidence: float = 10.5
    # chercher du réconfort : une humeur nettement sombre
    comfort_evidence: float = 10.0
    distress_valence: float = -0.35
    distress_intensity: float = 0.5
    comfort_spacing_us: int = 6 * HOUR
    # l'envie de discuter : une amie ou un proche joignable, plus silencieuse que d'habitude
    chat_after_us: int = 4 * HOUR
    chat_ratio: float = 1.0
    chat_friend: float = 1.5
    chat_close: float = 2.5
    chat_warmth: float = 1.0
    # ses heures pour écrire d'elle-même à quelqu'un d'absent (heure locale, minutes)
    day_start_min: int = 10 * 60
    day_end_min: int = 20 * 60 + 30
    # initiatives restées sans réponse : chaque nouvelle vers la même personne attend plus
    ignored_shift: float = -1.0
    # une rancune (hostilité installée) : ni amitié, ni initiative vers elle
    grudge: float = 0.2
    # profils : relus quand assez de nouveau est su, au plus une fois par jour
    profile_min_items: int = 3
    profile_interval_us: int = DAY
    profile_max_items: int = 30
    profile_per_run: int = 2
    profile_retry_us: int = 30 * MINUTE


@dataclass(frozen=True, slots=True)
class Contact:
    days: tuple[int, ...] = ()  # jours locaux (ordinaux) où la personne a écrit
    inbound: int = 0
    first_in: int = 0
    last_in: int = 0
    last_out: int = 0
    unanswered: int = 0  # ses initiatives depuis le dernier message de la personne


@dataclass(frozen=True, slots=True)
class Profile:
    summary_ref: str
    tone: str = ""
    interests: tuple[str, ...] = ()
    sensitive: tuple[str, ...] = ()
    revised_at: int = 0
    upto: int = 0
    mentions_at: int = 0  # combien d'éléments de mémoire la concernaient à la relecture


@dataclass(frozen=True, slots=True)
class SocialState:
    greeted: FrozenDict[str, int] = field(default_factory=FrozenDict)
    contacts: FrozenDict[str, Contact] = field(default_factory=FrozenDict)
    profiles: FrozenDict[str, Profile] = field(default_factory=FrozenDict)
    declared: FrozenDict[str, str] = field(default_factory=FrozenDict)  # proximité déclarée par un opérateur
    mentions: FrozenDict[str, int] = field(default_factory=FrozenDict)  # éléments de mémoire la concernant
    comforted_at: int = 0  # la dernière fois qu'elle est allée chercher du réconfort


SOCIAL = Faculty("social", state=SocialState, init=lambda p: SocialState(), params=SocialParams)
SOCIAL.declare(*c.ALL)


def params(p: SocialParams | None) -> SocialParams:
    return p if p is not None else SocialParams()


# ── Réducteurs ────────────────────────────────────────────────────────────


@SOCIAL.reducer(rt.EPISODE_STARTED, reads=[identity_c.PERSON])
def _started(s: SocialState, e, cx) -> SocialState:
    d = e.data
    reasons = d.reason.split(",")
    if d.kind != Kind.INITIATIVE or not d.target:
        return s
    if c.COMFORT in reasons:
        s = replace(s, comforted_at=e.at)  # on va vers une personne, pas vers toutes à la suite
    if c.GREETING in reasons:
        s = replace(s, greeted=s.greeted.set(cx.facts.get(identity_c.PERSON(d.target)), e.at))
    return s


@SOCIAL.reducer(rt.PERCEPTION_RECEIVED, reads=[identity_c.PERSON])
def _received(s: SocialState, e, cx) -> SocialState:
    d = e.data
    if not d.addressed or not is_identifiable(d.handle):
        return s  # entendu dans un groupe sans lui être adressé : ce n'est pas un contact
    person = cx.facts.get(identity_c.PERSON(d.handle))
    ct = s.contacts.get(person) or Contact()
    day = cx.local(e.at).date().toordinal()
    days = ct.days if ct.days and ct.days[-1] == day else (*ct.days, day)[-KEEP_DAYS:]
    ct = replace(ct, days=days, inbound=ct.inbound + 1, first_in=ct.first_in or e.at, last_in=e.at, unanswered=0)
    return replace(s, contacts=s.contacts.set(person, ct))


@SOCIAL.reducer(rt.UTTERANCE, reads=[identity_c.PERSON])
def _uttered(s: SocialState, e, cx) -> SocialState:
    d = e.data
    if not d.visible or not d.target or not is_identifiable(d.target):
        return s
    person = cx.facts.get(identity_c.PERSON(d.target))
    ct = s.contacts.get(person) or Contact()
    ct = replace(ct, last_out=e.at, unanswered=ct.unanswered + (1 if d.kind == Kind.INITIATIVE else 0))
    return replace(s, contacts=s.contacts.set(person, ct))


@SOCIAL.reducer(memory_c.REMEMBERED, memory_c.BELIEVED)
def _mentioned(s: SocialState, e, cx) -> SocialState:
    mentions = s.mentions
    for person in e.data.about:
        mentions = mentions.set(person, mentions.get(person, 0) + 1)
    return replace(s, mentions=mentions)


@SOCIAL.reducer(c.PROFILE_REVISED)
def _profiled(s: SocialState, e, cx) -> SocialState:
    d = e.data
    profile = Profile(summary_ref=d.summary.ref or "", tone=d.tone,
                      interests=tuple(d.interests), sensitive=tuple(d.sensitive), revised_at=e.at, upto=d.upto,
                      mentions_at=s.mentions.get(d.person, 0))
    return replace(s, profiles=s.profiles.set(d.person, profile))


@SOCIAL.reducer(c.CLOSENESS_SET)
def _declared(s: SocialState, e, cx) -> SocialState:
    d = e.data
    if d.closeness not in c.CLOSENESS_LEVELS:
        return replace(s, declared=s.declared.delete(d.person))
    return replace(s, declared=s.declared.set(d.person, d.closeness))


# ── Lectures ──────────────────────────────────────────────────────────────


def lived(ct: Contact | None, regard: float, p: SocialParams, hostility: float = 0.0) -> str:
    """Ce que leur histoire a fait d'elles : on devient amies en passant du
    temps ensemble, sans rancune — pas en le disant (ni parce qu'un modèle
    l'a jugé) ; proches, avec de la chaleur ou une longue histoire."""
    if ct is None or not ct.days:
        return c.STRANGER
    days, n = len(ct.days), ct.inbound
    friendly = hostility < p.grudge
    if friendly and days >= p.close_days and n >= p.close_messages and \
            (regard >= p.close_regard or days >= p.close_long_days):
        return c.CLOSE
    if friendly and days >= p.friend_days and n >= p.friend_messages:
        return c.FRIEND
    if days >= p.acquaintance_days or n >= p.acquaintance_messages:
        return c.ACQUAINTANCE
    return c.STRANGER


def closeness(s: SocialState, person: str, regard: float, p: SocialParams, hostility: float = 0.0) -> str:
    """Déclarée par un opérateur, sinon vécue."""
    declared = s.declared.get(person)
    return declared if declared is not None else lived(s.contacts.get(person), regard, p, hostility)


def rhythm(ct: Contact, now_day: int, level: str, p: SocialParams) -> tuple[float, bool]:
    """L'écart habituel entre deux jours de contact : mesuré sur leur
    histoire récente, sinon un repli selon la proximité."""
    recent = [d for d in ct.days if now_day - d <= p.rhythm_window_days]
    gaps = [b - a for a, b in zip(recent, recent[1:], strict=False)]
    if len(gaps) >= p.rhythm_min_gaps:
        value = float(statistics.median(gaps))
        return max(p.rhythm_min_days, min(p.rhythm_max_days, value)), True
    fallback = {c.CLOSE: p.fallback_close_days, c.FRIEND: p.fallback_friend_days}.get(level, p.fallback_other_days)
    return fallback, False


def contact_reading(s: SocialState, person: str, now: int, now_day: int, level: str,
                    p: SocialParams) -> c.ContactReading:
    ct = s.contacts.get(person) or Contact()
    days, measured = rhythm(ct, now_day, level, p)
    ratio = (now - ct.last_in) / (days * DAY) if ct.last_in else 0.0
    return c.ContactReading(person, len(ct.days), ct.inbound, ct.first_in, ct.last_in, ct.last_out, days, measured,
                            ct.unanswered, max(0.0, ratio))


@SOCIAL.fact(c.GREETED)
def _greeted(s: SocialState, cx, person: str) -> int:
    return s.greeted.get(person, 0)


@SOCIAL.fact(c.CLOSENESS, reads=[affect_c.REGARD, affect_c.HOSTILITY])
def _closeness(s: SocialState, cx, person: str) -> str:
    return closeness(s, person, cx.facts.get(affect_c.REGARD(person)), params(cx.params),
                     cx.facts.get(affect_c.HOSTILITY(person)))


@SOCIAL.fact(c.CONTACT, reads=[c.CLOSENESS])
def _contact(s: SocialState, cx, person: str) -> c.ContactReading:
    return contact_reading(s, person, cx.now, cx.local(cx.now).date().toordinal(), cx.facts.get(c.CLOSENESS(person)),
                           params(cx.params))


@SOCIAL.fact(c.SENSITIVE)
def _sensitive(s: SocialState, cx, person: str) -> tuple[str, ...]:
    profile = s.profiles.get(person)
    return tuple(fold(t) for t in profile.sensitive) if profile else ()


@SOCIAL.fact(c.MISSED, reads=[c.CONTACT, c.CLOSENESS])
def _missed(s: SocialState, cx) -> tuple[tuple[str, float], ...]:
    p = params(cx.params)
    out = []
    for person in s.contacts.keys():
        if not is_identifiable(person) or person.startswith("name:"):
            continue
        if cx.facts.get(c.CLOSENESS(person)) not in (c.FRIEND, c.CLOSE):
            continue
        ratio = cx.facts.get(c.CONTACT(person)).silence_ratio
        if ratio >= p.recontact_factor:
            out.append((person, round(ratio, 3)))
    return tuple(sorted(out, key=lambda x: (-x[1], x[0])))
