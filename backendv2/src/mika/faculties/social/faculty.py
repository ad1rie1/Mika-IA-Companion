"""La faculté ``social`` : sa tranche, ses paramètres, ses réducteurs, ses faits."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict

from mika.contracts import affect as affect_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import social as c
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import Kind
from mika.vocab.people import fold, is_identifiable
from mika.vocab.temperament import Temperament, lerp

KEEP_DAYS = 64


class SocialParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # le rythme d'une relation : l'écart médian entre les jours où la personne écrit
    rhythm_window_days: Annotated[int, Knob(
        label="Fenêtre du rythme (jours)", group="Rythme d'une relation", lo=7, hi=365,
        help="Seuls les jours de contact de cette fenêtre servent à mesurer l'écart habituel entre deux jours où "
             "la personne écrit (64 jours de contact distincts au plus sont gardés).")] = 90
    rhythm_min_days: Annotated[float, Knob(
        label="Rythme mesuré minimal (jours)", group="Rythme d'une relation", lo=0.5, hi=14, step=0.5,
        help="Le rythme mesuré n'est jamais plus court : une personne qui écrit tous les jours ne manque pas "
             "au bout de quelques heures.")] = 1.0
    rhythm_max_days: Annotated[float, Knob(
        label="Rythme mesuré maximal (jours)", group="Rythme d'une relation", lo=7, hi=180, step=1,
        help="Le rythme mesuré n'est jamais plus long : au-delà, même une relation espacée finit par lui "
             "manquer.")] = 30.0
    rhythm_min_gaps: Annotated[int, Knob(
        label="Écarts pour mesurer un rythme", group="Rythme d'une relation", lo=1, hi=20,
        help="Combien d'écarts entre jours de contact il faut dans la fenêtre pour mesurer un rythme ; en deçà, "
             "le rythme supposé selon la proximité s'applique.")] = 2
    fallback_close_days: Annotated[float, Knob(
        label="Rythme supposé : proche (jours)", group="Rythme d'une relation", lo=0.5, hi=30, step=0.5,
        help="L'écart habituel prêté à une personne proche tant que son rythme n'est pas mesurable.")] = 3.0
    fallback_friend_days: Annotated[float, Knob(
        label="Rythme supposé : amie (jours)", group="Rythme d'une relation", lo=1, hi=60, step=0.5,
        help="L'écart habituel prêté à une amie tant que son rythme n'est pas mesurable.")] = 7.0
    fallback_other_days: Annotated[float, Knob(
        label="Rythme supposé : les autres (jours)", group="Rythme d'une relation", lo=1, hi=90, step=0.5,
        help="Celui prêté à une connaissance ou une inconnue. Il ne change que la lecture (fiche, silence ÷ "
             "rythme) : elle ne relance que ses amies et ses proches.")] = 14.0
    # la proximité naît de l'histoire vécue (jours distincts, messages reçus) et
    # de ce qu'elle a installé (le regard d'``affect`` : jamais amie d'une rancune)
    # s'être parlé deux jours différents…
    acquaintance_days: Annotated[int, Knob(
        label="Connaissance : jours de contact", group="Proximité vécue", lo=1, hi=30,
        help="S'être parlé tant de jours différents fait d'une inconnue une connaissance (ou assez de messages, "
             "ci-dessous).")] = 2
    # … ou longuement : dix minutes d'insultes ne font pas une connaissance
    acquaintance_messages: Annotated[int, Knob(
        label="Connaissance : messages reçus", group="Proximité vécue", lo=1, hi=500,
        help="… ou avoir reçu tant de messages d'elle, même en un seul jour.")] = 20
    friend_days: Annotated[int, Knob(
        label="Amie : jours de contact", group="Proximité vécue", lo=1, hi=60,
        help="Jours de contact distincts pour devenir amie (avec assez de messages, et sans rancune).")] = 3
    friend_messages: Annotated[int, Knob(
        label="Amie : messages reçus", group="Proximité vécue", lo=1, hi=1000,
        help="Messages reçus pour devenir amie (avec assez de jours de contact, et sans rancune).")] = 15
    close_days: Annotated[int, Knob(
        label="Proche : jours de contact", group="Proximité vécue", lo=1, hi=120,
        help="Jours de contact distincts pour devenir proche (avec assez de messages, sans rancune, et de la "
             "chaleur installée ou une longue histoire).")] = 7
    close_messages: Annotated[int, Knob(
        label="Proche : messages reçus", group="Proximité vécue", lo=1, hi=2000,
        help="Messages reçus pour devenir proche.")] = 50
    #: proche : de la chaleur installée — ou une longue histoire (un chagrin partagé n'éloigne pas)
    close_regard: Annotated[float, Knob(
        label="Proche : chaleur installée", group="Proximité vécue", lo=0, hi=1, step=0.01,
        help="Le regard installé (affect : 0 au repos, 1 chaleur pleine) qu'il faut pour devenir proche — "
             "sauf longue histoire (ci-dessous).")] = 0.1
    close_long_days: Annotated[int, Knob(
        label="Proche : longue histoire (jours)", group="Proximité vécue", lo=1, hi=365,
        help="Au-delà de tant de jours de contact, on devient proche même sans chaleur installée : un chagrin "
             "partagé n'éloigne pas.")] = 14
    # reprendre contact : un silence d'une fois et demie son rythme
    recontact_factor: Annotated[float, Knob(
        label="Manque : silence ÷ rythme", group="Reprendre contact", lo=1, hi=10, step=0.1,
        help="Une amie ou un proche lui manque quand son silence dépasse tant de fois son rythme habituel : elle "
             "a envie de reprendre des nouvelles, et le manque nourrit ses pensées.")] = 1.5
    recontact_evidence: Annotated[float, Knob(
        label="Preuve d'une relance", group="Reprendre contact", lo=0, hi=12, step=0.5,
        help="Preuve d'initiative (log-odds) d'un manque. Au-dessus du seuil d'initiative (9 par défaut), une "
             "relance part seule ; plafonnée à 12 par l'arbitrage.")] = 10.5
    # chercher du réconfort : une humeur nettement sombre
    comfort_evidence: Annotated[float, Knob(
        label="Preuve d'une recherche de réconfort", group="Réconfort", lo=0, hi=12, step=0.5,
        help="Preuve d'initiative (log-odds) pour écrire, quand elle va mal, à la personne auprès de qui elle se "
             "sent le mieux ; plafonnée à 12 par l'arbitrage.")] = 10.0
    distress_valence: Annotated[float, Knob(
        label="Détresse : valence au plus", group="Réconfort", lo=-1, hi=0, step=0.05,
        help="Elle cherche du réconfort quand la valence de son humeur ressentie tombe à ce niveau ou "
             "plus bas (et que l'intensité suit).")] = -0.35
    distress_intensity: Annotated[float, Knob(
        label="Détresse : intensité au moins", group="Réconfort", lo=0, hi=1, step=0.05,
        help="L'intensité ressentie qu'il faut, avec la valence ci-dessus, pour parler de détresse.")] = 0.5
    comfort_spacing_us: Annotated[int, Knob(
        label="Espacement du réconfort", group="Réconfort", lo=30 * MINUTE, hi=3 * DAY,
        help="Pas deux recherches de réconfort plus rapprochées, ni vers quelqu'un à qui elle a écrit "
             "depuis moins longtemps : on va vers une personne, pas vers toutes à la suite.")] = 6 * HOUR
    # l'envie de discuter : une amie ou un proche joignable, plus silencieuse que d'habitude
    chat_after_us: Annotated[int, Knob(
        label="Envie de discuter : silence minimal", group="Envie de discuter", lo=30 * MINUTE, hi=3 * DAY,
        help="Il faut au moins ce silence (dans un sens comme dans l'autre) avec une amie ou un proche pour "
             "avoir envie de lui écrire sans raison particulière.")] = 4 * HOUR
    chat_ratio: Annotated[float, Knob(
        label="Envie de discuter : silence ÷ rythme", group="Envie de discuter", lo=0, hi=10, step=0.1,
        help="… et un silence d'au moins tant de fois son rythme habituel (au-delà du seuil de manque, c'est "
             "une relance).")] = 1.0
    chat_friend: Annotated[float, Knob(
        label="Envie de discuter : preuve (amie)", group="Envie de discuter", lo=0, hi=3.5, step=0.1,
        help="Preuve d'initiative (log-odds) de l'envie de discuter avec une amie : peu de chose seule, assez "
             "quand le besoin de compagnie s'y ajoute. Plafonnée à 3,5 chaleur comprise.")] = 1.5
    chat_close: Annotated[float, Knob(
        label="Envie de discuter : preuve (proche)", group="Envie de discuter", lo=0, hi=3.5, step=0.1,
        help="La même preuve envers un proche. Plafonnée à 3,5 chaleur comprise.")] = 2.5
    chat_warmth: Annotated[float, Knob(
        label="Envie de discuter : poids de la chaleur", group="Envie de discuter", lo=0, hi=3.5, step=0.1,
        help="S'ajoute à la preuve, multiplié par la chaleur installée envers la personne (0 à 1).")] = 1.0
    # ses heures pour écrire d'elle-même à quelqu'un d'absent (heure locale, minutes)
    day_start_min: Annotated[int, Knob(
        label="Écrire d'elle-même : à partir de", group="Heures d'initiative", lo=0, hi=24 * 60,
        help="Heure locale (10 h = 10:00) à partir de laquelle elle relance, cherche du réconfort ou écrit "
             "pour discuter. Les salutations n'en dépendent pas.")] = 10 * 60
    day_end_min: Annotated[int, Knob(
        label="Écrire d'elle-même : jusqu'à", group="Heures d'initiative", lo=0, hi=24 * 60,
        help="Heure locale après laquelle elle ne le fait plus. Avant le début, la plage passe minuit (un "
             "tempérament nocturne : de 18 h à 1 h).")] = 20 * 60 + 30
    # initiatives restées sans réponse : chaque nouvelle vers la même personne attend plus
    ignored_shift: Annotated[float, Knob(
        label="Recul par initiative sans réponse", group="Retenue", lo=-10, hi=0, step=0.5,
        help="Envers quelqu'un de présent, chaque initiative restée sans réponse rend la suivante moins probable "
             "d'autant (log-odds) ; envers quelqu'un d'absent, c'est un veto.")] = -1.0
    # une rancune (hostilité installée) : ni amitié, ni initiative vers elle
    grudge: Annotated[float, Knob(
        label="Seuil de rancune", group="Retenue", lo=0.05, hi=1, step=0.05,
        help="À partir de cette hostilité installée (affect), ni amitié ni initiative vers la personne. Plus "
             "bas : la moindre contrariété coupe les ponts.")] = 0.2
    # profils : relus quand assez de nouveau est su, au plus une fois par jour
    profile_min_items: Annotated[int, Knob(
        label="Fiche : éléments nouveaux", group="Fiches", lo=1, hi=50,
        help="Sa fiche d'une personne n'est relue (appel au modèle) qu'après tant de souvenirs ou croyances "
             "nouveaux la concernant.")] = 3
    profile_interval_us: Annotated[int, Knob(
        label="Fiche : intervalle minimal", group="Fiches", lo=HOUR, hi=30 * DAY,
        help="Pas deux relectures de la même fiche plus rapprochées.")] = DAY
    profile_max_items: Annotated[int, Knob(
        label="Fiche : éléments relus", group="Fiches", lo=5, hi=200,
        help="Combien de ses souvenirs et croyances sur la personne (les plus importants) le modèle relit.")] = 30
    profile_per_run: Annotated[int, Knob(
        label="Fiches par passage", group="Fiches", lo=1, hi=10,
        help="Combien de fiches au plus une passe relit (les plus en retard d'abord) : les appels restent "
             "rares.")] = 2
    profile_retry_us: Annotated[int, Knob(
        label="Fiche : délai entre passes", group="Fiches", lo=MINUTE, hi=DAY,
        help="Délai avant la passe suivante quand d'autres fiches attendent ou qu'un appel a échoué : pas de "
             "rafale d'appels au modèle.")] = 30 * MINUTE


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


def derive(t: Temperament, overrides: Any = None) -> SocialParams:
    """L'optimisme recule le seuil de la détresse : une optimiste tient plus
    longtemps avant d'aller chercher du réconfort (au milieu : −0,35, la valeur
    d'avant). Les surcharges sont posées par ``runtime/params.py``."""
    values: dict[str, Any] = {"distress_valence": round(lerp(-0.2, -0.5, t.optimism), 3)}
    values.update(dict(overrides or {}))
    return SocialParams(**values)


SOCIAL = Faculty("social", state=SocialState, init=lambda p: SocialState(), params=SocialParams, derive=derive)
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


def grudging(hostility: float, p: SocialParams) -> bool:
    """Une rancune : une hostilité **installée** qui atteint le seuil. Sans
    hostilité du tout, il n'y a rien à garder contre personne — même un seuil
    à zéro (une surcharge passée, un réglage extrême) ne coupe pas les ponts
    avec tout le monde."""
    return hostility > 0.0 and hostility >= p.grudge


def lived(ct: Contact | None, regard: float, p: SocialParams, hostility: float = 0.0) -> str:
    """Ce que leur histoire a fait d'elles : on devient amies en passant du
    temps ensemble, sans rancune — pas en le disant (ni parce qu'un modèle
    l'a jugé) ; proches, avec de la chaleur ou une longue histoire."""
    if ct is None or not ct.days:
        return c.STRANGER
    days, n = len(ct.days), ct.inbound
    friendly = not grudging(hostility, p)
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
