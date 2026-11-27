"""La faculté ``memory`` : sa tranche, ses réducteurs, ses faits ; ses réglages sont dans ``params.py``.

La tranche ne garde que des résumés (point de contrôle, messages pas encore
relus, promesses en cours et ce qu'elle a fait pour les tenir, moments de la
vie des autres à venir ou tout juste passés, situations en cours (et quand la
personne a dit qu'elles étaient finies), dates qui reviennent chaque année (jamais
évincées par l'âge : le fait ``LIFE_EVENTS`` les rend à leur prochaine
occurrence), la dernière
fois que quelque chose de grave a touché chacun) ; les
éléments retenus vivent dans la projection T0 ``memory_items`` et leurs
vecteurs dans l'index (un cache).

Qu'un moment ait été repris ne se déduit plus de ce qu'elle avait sous les
yeux : c'est un jugement enregistré (``moment_followed``, ``life.py``).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field, replace
from datetime import datetime, time
from zoneinfo import ZoneInfo

from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import expression as expression_c
from mika.contracts import identity as identity_c
from mika.contracts import mcp as mcp_c
from mika.contracts import memory as c
from mika.contracts import others as others_c
from mika.contracts import rss as rss_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.memory.params import MemoryParams, params
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.clock import DAY, HOUR, instant, local
from mika.kernel.faculty import Faculty
from mika.kernel.state import FrozenDict
from mika.vocab import causes
from mika.vocab.affect import Appraisal, Declared, Emotion, emotion_of, facets_valence, valence
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable

PENDING_CAP = 500
#: les messages reçus ailleurs (son téléphone, ADR 0120) qui attendent d'être relus, au plus
RELAYED_CAP = 2000
#: les initiatives en cours qui tiennent une promesse (corrélation → promesse), au plus
KEEPING_KEPT = 16
#: le sujet d'une initiative qui tient une promesse : ``promise:<id>``
PROMISE_SUBJECT = "promise:"
#: les personnes que quelque chose de grave a touchées, retenues au plus (les plus récentes)
HARD_KEPT = 64


def promise_of(subject: str | None) -> int | None:
    """La promesse que tient une initiative (``promise:12``), ou ``None``."""
    if not subject or not subject.startswith(PROMISE_SUBJECT) or not subject[len(PROMISE_SUBJECT):].isdigit():
        return None
    return int(subject[len(PROMISE_SUBJECT):])


@dataclass(frozen=True, slots=True)
class Reflection:
    """Une pensée restée forte, digérée cette nuit : un souvenir à écrire."""

    thought: int
    text_ref: str
    about: tuple[str, ...]
    sensitivity: int
    emotion: str


@dataclass(frozen=True, slots=True)
class Keeping:
    """Ce qu'elle a fait pour tenir une promesse : les essais qui n'ont rien dit, et quand réessayer."""

    attempts: int = 0
    retry_at: int = 0


@dataclass(frozen=True, slots=True)
class MemoryState:
    checkpoint: int = 0
    #: le dernier passage inscrit à la file de reprises (``seq``, 0 : jamais) : la consolidation relit la file
    #: quand il change (une reprise demandée par un opérateur, un passage différé)
    deferred_seq: int = 0
    life_seen: bool = False
    life_refreshed_at: int = 0
    #: messages de personnes pas encore relus (``seq``), les plus récents
    pending: tuple[int, ...] = field(default_factory=tuple)
    #: parmi eux, ceux qui ne lui étaient pas adressés (un salon : on parle entre soi)
    unaddressed: tuple[int, ...] = field(default_factory=tuple)
    last_message_at: int = 0
    items: int = 0
    index_revision: int = 0
    chunks: int = 0
    promises: FrozenDict[int, c.PendingPromise] = field(default_factory=FrozenDict)
    #: tenir une promesse au moment dit : les initiatives en cours (corrélation → (promesse, départ)), les essais,
    #: et les promesses qu'elle vient de tenir en le disant (le règlement suit, par ``memory.promises``)
    keeping: FrozenDict[str, tuple[int, int]] = field(default_factory=FrozenDict)
    tries: FrozenDict[int, Keeping] = field(default_factory=FrozenDict)
    kept: tuple[int, ...] = ()
    #: les moments de la vie des autres, à venir ou passés depuis peu ; les situations en cours
    events: FrozenDict[int, c.LifeEvent] = field(default_factory=FrozenDict)
    #: le fil de chaque moment qui n'est pas le sien (reporté, redit, revenu : numéro → fil), et le numéro sous
    #: lequel chaque fil est noté maintenant (fil → numéro) (ADR 0079)
    threads: FrozenDict[int, int] = field(default_factory=FrozenDict)
    heads: FrozenDict[int, int] = field(default_factory=FrozenDict)
    #: personne → la dernière fois que quelque chose de grave l'a touchée (un deuil, une rupture…)
    hard: FrozenDict[str, int] = field(default_factory=FrozenDict)
    reflections: tuple[Reflection, ...] = ()
    #: ses mensonges pas encore retenus (le ``seq`` de l'énoncé) : chacun devient un souvenir (``memory.lies``)
    lies: tuple[int, ...] = ()
    sorted_night: str = ""
    #: sa dernière lecture (``seq`` : ``rss.read``, ``mcp.consulted``) et la dernière nuit relue (ADR 0085)
    readings_upto: int = 0
    reread_night: str = ""
    #: ce qu'elle a vu de chacun qui annonce des moments : (tenus, reportés ou annulés) ; et ses attentes par sorte
    #: d'annonce : (combien, somme des carrés des écarts) — ce qu'elle apprend de ce qui arrive (ADR 0086)
    track: FrozenDict[str, tuple[int, int]] = field(default_factory=FrozenDict)
    calibration: FrozenDict[str, tuple[int, float]] = field(default_factory=FrozenDict)
    #: la dernière relecture journalisée (``seq``, instant), et les fenêtres
    #: abandonnées après trop d'échecs (combien, la dernière) : pour l'inspecteur
    consolidated_seq: int = 0
    consolidated_at: int = 0
    given_up: int = 0
    given_up_seq: int = 0
    #: les messages reçus ailleurs qu'on lui montre (``Relayed``, ADR 0120) pas encore relus (``seq``), l'arrivée du
    #: plus ancien d'entre eux et celle du dernier
    relayed: tuple[int, ...] = ()
    relayed_since: int = 0
    relayed_at: int = 0


#: v4 : un moment repris est un jugement enregistré (``moment_followed``), plus « elle l'avait sous les yeux » ;
#: les situations en cours ; tenir une promesse au moment dit.
#: v5 : l'importance d'un moment, ce qui se fête, et ce qui touche gravement quelqu'un (ADR 0052).
#: v6 : une situation en cours prend fin quand la personne dit qu'elle est finie (``situation_ended``).
#: v7 : une date qui revient chaque année (``yearly``) n'est jamais évincée par l'âge, et a son propre plafond.
#: v10 : la file de reprises (``deferred_seq``) ; situations et dates archivées en SQL, la tranche en est le cache.
#: v11 : ses mensonges à retenir (``lies``, ADR 0076).
#: v12 : les fils des moments (``threads``, ``heads``) : reporté, redit, revenu, un moment reste le même (ADR 0079).
#: v16 : comment un moment a tourné (``outcome``), ce qu'elle apprend de qui annonce (``track``) et de ses attentes
#: (``calibration``) (ADR 0086).
#: v17 : l'oubli d'une personne emporte ce qu'elle lui avait promis et ce qui l'a touchée de grave ; un moment déplacé
#: compte à moitié dans ses attentes (``OUTCOME_VALUE``), comme dans la surprise.
#: v18 : les messages reçus ailleurs qui attendent d'être relus (``relayed``, ADR 0120).
MEMORY = Faculty("memory", state=MemoryState, init=lambda p: MemoryState(), params=MemoryParams, state_version=18)
MEMORY.declare(*c.ALL)


@MEMORY.reducer(rt.PERCEPTION_RECEIVED)
def _perceived(s: MemoryState, e, cx) -> MemoryState:
    unaddressed = s.unaddressed if e.data.addressed else (*s.unaddressed, e.seq)[-PENDING_CAP:]
    return replace(s, pending=(*s.pending, e.seq)[-PENDING_CAP:], unaddressed=unaddressed, last_message_at=e.at)


@MEMORY.reducer(shapes=[c.Relayed])
def _relayed(s: MemoryState, e, cx) -> MemoryState:
    """Un message reçu ailleurs, que la personne lui montre (ADR 0120) : elle le relira avec sa conversation, une
    fois posée (``memory.relayed``)."""
    if e.seq in s.relayed:
        return s
    since = s.relayed_since if s.relayed else e.at
    return replace(s, relayed=(*s.relayed, e.seq)[-RELAYED_CAP:], relayed_since=since, relayed_at=e.at)


@MEMORY.reducer(c.RELAYED_READ)
def _relayed_read(s: MemoryState, e, cx) -> MemoryState:
    done = set(e.data.seqs)
    left = tuple(q for q in s.relayed if q not in done)
    return replace(s, relayed=left, relayed_since=s.relayed_since if left else 0)


def _hard(s: MemoryState, person: str, at: int) -> MemoryState:
    """Quelque chose de grave touche cette personne, à cet instant."""
    if not is_identifiable(person) or s.hard.get(person, 0) >= at:
        return s
    hard = s.hard.set(person, at)
    if len(hard) > HARD_KEPT:
        hard = FrozenDict(sorted(hard.items(), key=lambda kv: (kv[1], kv[0]))[-HARD_KEPT:])
    return replace(s, hard=hard)


#: au plus tant de mensonges en attente d'être retenus ; la marque de leur souvenir (``call_id`` : ``mensonge:<seq>``)
LIES_KEPT, LIE_MARK = 20, "mensonge"
#: la marque du souvenir qu'une réflexion devient la nuit (``call_id`` : ``réflexion:<pensée>``), posée par
#: ``night.Reflect`` et relue ici : à son retour, la réflexion n'est plus à écrire. La valeur ne change pas, les
#: souvenirs déjà au journal la portent
REFLECTION_MARK = "réflexion"


@MEMORY.reducer(rt.UTTERANCE, reads=[identity_c.PERSON])
def _uttered(s: MemoryState, e, cx) -> MemoryState:
    """Ce qu'elle dit : un échange de plus à indexer — et, quand c'est l'initiative qui tient une promesse, la
    promesse est tenue (dite au moment dit ; ``memory.promises`` la règle). Qu'elle ait repris un moment de la vie
    de la personne ne se lit pas ici : c'est un jugement sur ses mots (``life.py``). Quand elle répond, en privé,
    profondément triste pour quelqu'un, ce qu'il lui a confié est grave (« Pixel est parti » : aucun mot ne le
    nomme, sa peine le dit)."""
    d = e.data
    if not d.visible:
        return s
    keeping = s.keeping.get(e.correlation)
    if keeping is not None:
        s = replace(s, keeping=s.keeping.delete(e.correlation))
        if keeping[0] in s.promises and keeping[0] not in s.kept:
            s = replace(s, kept=(*s.kept, keeping[0]))
    if d.target and is_identifiable(d.target) and d.annotation(expression_c.LIE_ANNOTATION) is not None \
            and e.seq not in s.lies:
        s = replace(s, lies=(*s.lies, e.seq)[-LIES_KEPT:])  # un mensonge : il deviendra un souvenir
    if d.kind == Kind.REPLY and d.target and d.room is None and is_identifiable(d.target):
        declared = Declared.decode(d.annotation(expression_c.EMOTION_ANNOTATION))
        floor = params(cx.params).hard_reply_from
        if declared is not None and any(e_ == Emotion.SAD.value and x >= floor for e_, x in declared.all):
            resolve, _ = identity_c.resolvers(cx.facts.get)
            s = _hard(s, resolve(d.target), e.at)
    return replace(s, last_message_at=e.at, chunks=s.chunks + (1 if d.target and d.reply_to else 0))


@MEMORY.reducer(others_c.READ)
def _read_grave(s: MemoryState, e, cx) -> MemoryState:
    """Ce qu'elle a lu de grave dans un message (un deuil, une maladie, une rupture, une perte de travail, des mots
    de détresse) touche la personne qui l'a écrit."""
    return _hard(s, e.data.person, e.at) if e.data.grave else s


@MEMORY.reducer(rt.EPISODE_STARTED)
def _started(s: MemoryState, e, cx) -> MemoryState:
    """Une initiative part pour tenir une promesse (son sujet : ``promise:<id>``)."""
    d = e.data
    promise = promise_of(d.subject) if d.kind == Kind.INITIATIVE else None
    if promise is None or promise not in s.promises:
        return s
    keeping = s.keeping.set(e.correlation, (promise, e.at))
    if len(keeping) > KEEPING_KEPT:  # des épisodes jamais réglés : les identifiants sont chronologiques
        keeping = FrozenDict(sorted(keeping.items())[-KEEPING_KEPT:])
    return replace(s, keeping=keeping)


@MEMORY.reducer(rt.EPISODE_ENDED, reads=[agency_c.RENOUNCED])
def _ended(s: MemoryState, e, cx) -> MemoryState:
    """L'initiative qui devait tenir une promesse finit sans l'avoir dite : un silence choisi, une panne sont un
    essai (réessayer plus tard, pas indéfiniment) ; devancée, interrompue, ou un murmure sans suite (elle s'est
    ravisée), ce n'en est pas un (``agency.tried``)."""
    keeping = s.keeping.get(e.correlation)
    if keeping is None:
        return s
    s = replace(s, keeping=s.keeping.delete(e.correlation))
    promise, started = keeping
    if promise not in s.promises:
        return s
    p = params(cx.params)
    t = s.tries.get(promise) or Keeping()
    renounced = cx.facts.get(agency_c.RENOUNCED(e.data.target)) if e.data.target else 0
    if agency_c.tried(e.data.outcome, started, renounced):
        n = t.attempts + 1
        t = Keeping(n, e.at + p.keep_retry_us * n)
    else:
        t = replace(t, retry_at=e.at + p.keep_retry_us)
    return replace(s, tries=s.tries.set(promise, t))


@MEMORY.reducer(c.MOMENT_FOLLOWED)
def _followed(s: MemoryState, e, cx) -> MemoryState:
    """Un moment repris en mots, une fois passé : elle lui en a demandé des nouvelles, ou la personne lui en a
    parlé d'elle-même. Redit entre-temps (le même jour), le moment garde le suivi ; déplacé à une autre date, ce
    n'est plus l'occurrence reprise (ADR 0079)."""
    d = e.data
    ev = s.events.get(d.event)
    if ev is None:
        head = s.heads.get(d.thread or thread_of(s, d.event))
        ev = s.events.get(head) if head is not None else None
        if ev is None or (d.occurrence and ev.when != d.occurrence and not ev.yearly):
            return s
    return replace(s, events=s.events.set(ev.id, replace(ev, followed_at=e.at)))


def thread_of(s: MemoryState, item: int) -> int:
    """Le fil d'un moment, d'après l'un de ses numéros."""
    ev = s.events.get(item)
    if ev is not None and ev.thread:
        return ev.thread
    return s.threads.get(item, item)


def moment_thread(s: MemoryState, cx, item: int) -> int:
    return thread_of(s, int(item))


MEMORY.fact(c.MOMENT_THREAD)(moment_thread)


@MEMORY.reducer(c.RESOLVED)
def _moment_resolved(s: MemoryState, e, cx) -> MemoryState:
    """Comment un moment a tourné (ADR 0086) : il le garde ; et elle en apprend — de qui l'avait annoncé (un report,
    une annulation de plus, ou un moment tenu) et de ce qu'elle en attendait (sa calibration). Un moment dont on n'a
    jamais su l'issue n'apprend rien ; un moment déjà tranché ne se retranche pas."""
    d = e.data
    ev = s.events.get(d.event)
    if ev is None and d.thread:
        head = s.heads.get(d.thread)
        ev = s.events.get(head) if head is not None else None
    if ev is not None and ev.outcome:
        return s
    events = s.events.set(ev.id, replace(ev, outcome=d.outcome, resolved_at=e.at)) if ev is not None else s.events
    if d.outcome == c.UNKNOWN:
        return replace(s, events=events)
    track = s.track
    if d.teller:
        kept, missed = track.get(d.teller, (0, 0))
        track = track.set(d.teller, (kept + 1, missed) if d.outcome == c.HAPPENED else (kept, missed + 1))
    calibration = s.calibration
    if d.likelihood is not None and d.nature:
        n, squares = calibration.get(d.nature, (0, 0.0))
        # ce qui est arrivé, comme pour la surprise : déplacé, il aura lieu — à moitié
        happened = c.OUTCOME_VALUE[d.outcome]
        calibration = calibration.set(d.nature, (n + 1, round(squares + (d.likelihood - happened) ** 2, 6)))
    return replace(s, events=events, track=track, calibration=calibration)


@MEMORY.appraisal(c.RESOLVED, reads=[social_c.WEIGHT])
def _moment_resolved_felt(e, cx) -> list[Appraisal] | None:
    """Ce que l'issue d'un moment lui fait (ADR 0086) : surprise quand elle s'écarte de ce qu'elle attendait (pesée
    par ce que le moment compte) ; un espoir déçu attriste, une crainte levée soulage, une attente comblée réjouit
    un peu — davantage quand c'est un moment de sa propriétaire (``social.WEIGHT``). Ne pas savoir ne fait rien."""
    d = e.data
    if d.outcome == c.UNKNOWN:
        return None
    p = params(cx.params)
    out: list[Appraisal] = []
    # le moment de quelqu'un (pas du monde) : ce que vivent les autres suit la contagion du tempérament (ADR 0100)
    rel = bool(d.about)
    if d.surprise >= p.surprise_from:
        out.append(Appraisal(Emotion.SURPRISED, round(min(p.surprise_max, d.surprise), 3), reason=causes.TURNED_OUT,
                             relational=rel))
    counts = max((cx.facts.get(social_c.WEIGHT(person)) for person in d.about), default=1.0)
    weight = round(min(p.disappointment_max, abs(d.valence) * d.importance * counts), 3)
    if weight > 0 and d.valence > 0 and d.outcome in (c.CANCELLED, c.MOVED):
        out.append(Appraisal(Emotion.SAD, weight, reason=causes.LET_DOWN, relational=rel))
    elif weight > 0 and d.valence < 0 and d.outcome == c.CANCELLED:
        out.append(Appraisal(Emotion.RELIEVED, weight, reason=causes.FEAR_LIFTED, relational=rel))
    elif weight > 0 and d.valence > 0 and d.outcome == c.HAPPENED:
        out.append(Appraisal(Emotion.HAPPY, round(weight / 2, 3), reason=causes.AWAITED, relational=rel))
    return out or None


@MEMORY.reducer(c.SITUATION_ENDED)
def _situation_ended(s: MemoryState, e, cx) -> MemoryState:
    """Une situation qui durait est finie, de la bouche de la personne (« on a fini le déménagement », « on a dû
    l'endormir ») : elle reste notée, mais n'est plus « en ce moment ». La première fin dite compte."""
    ev = s.events.get(e.data.event)
    if ev is None or not ev.ongoing or ev.ended_at:
        return s
    return replace(s, events=s.events.set(ev.id, replace(ev, ended_at=e.at)))


@MEMORY.reducer(c.EXTRACTION_DEFERRED)
def _deferred(s: MemoryState, e, cx) -> MemoryState:
    return replace(s, deferred_seq=e.seq)


@MEMORY.reducer(c.CONSOLIDATED)
def _consolidated(s: MemoryState, e, cx) -> MemoryState:
    upto = max(s.checkpoint, e.data.upto)
    s = replace(s, checkpoint=upto, pending=tuple(q for q in s.pending if q > upto),
                unaddressed=tuple(q for q in s.unaddressed if q > upto), consolidated_seq=e.seq, consolidated_at=e.at)
    return replace(s, given_up=s.given_up + 1, given_up_seq=e.seq) if e.data.failed else s


@MEMORY.reducer(c.EVENT_NOTED)
def _noted(s: MemoryState, e, cx) -> MemoryState:
    """Un moment de la vie de quelqu'un : gardé tant qu'il est à venir ou passé
    depuis peu ; une situation en cours jusqu'à sa fin explicite ; une date qui
    revient chaque année, toujours. Le même
    moment renoté à la même date (la personne l'a dit elle-même après un tiers)
    reste repris s'il l'était ; une date qui change repart de zéro. Une
    situation finie, renotée, reste finie."""
    d = e.data
    p = params(cx.params)
    old = s.events.get(d.replaces) if d.replaces is not None else None
    followed = old.followed_at if old is not None and old.when == d.when else 0
    ended = old.ended_at if old is not None and old.ongoing and d.ongoing else 0
    events = s.events.delete(d.replaces) if d.replaces is not None else s.events
    # le fil : celui de ce qu'il remplace (reporté, redit) ou de la situation qu'il rouvre ; sinon le sien
    origin = d.replaces if d.replaces is not None else d.recurs
    thread = thread_of(s, origin) if origin is not None else e.seq
    events = events.set(e.seq, c.life_event_of(e.seq, d, followed_at=followed, ended_at=ended, thread=thread))
    if d.recurs is not None:
        events = events.delete(d.recurs)  # la situation finie laisse la place à celle qui recommence
    threads = s.threads.set(e.seq, thread) if thread != e.seq else s.threads
    s = replace(s, threads=_newest(threads, THREADS_KEPT), heads=_newest(s.heads.set(thread, e.seq), THREADS_KEPT))
    for i in [ev.id for ev in events.values() if not cached(ev, e.at, p)]:
        events = events.delete(i)
    return replace(s, items=s.items + 1, life_seen=True, events=life_cache(events))


def cached(ev: c.LifeEvent, at: int, p: MemoryParams) -> bool:
    """Ce que la tranche garde d'un moment à l'instant ``at`` : une date qui revient chaque année, toujours ; une
    situation en cours, ou finie depuis moins de ``event_recent_days`` ; un moment à venir, ou passé depuis moins que
    ça (une période, à sa fin — ADR 0084). Le reste vit dans l'archive : la relecture de sa vie ne l'y remet pas, ou
    chaque nouveau moment noté l'en chasserait, et chaque message le ferait revenir dans le journal."""
    if ev.yearly:
        return True
    keep_until = at - round(p.event_recent_days * DAY)
    if ev.ongoing:
        return not ev.ended_at or ev.ended_at >= keep_until
    return ev.ends >= keep_until


# L'archive SQL conserve tout ; cette tranche est seulement la mémoire de travail.
LIFE_CACHE_CAP = 2048
#: les fils retenus au plus (les plus récents) : un moment plus ancien est son propre fil, ou l'archive le dit
THREADS_KEPT = 4096


def _newest(table: FrozenDict[int, int], cap: int) -> FrozenDict[int, int]:
    if len(table) <= cap:
        return table
    return FrozenDict(sorted(table.items(), key=lambda kv: (kv[1], kv[0]))[-cap:])


def life_cache(events: FrozenDict[int, c.LifeEvent], keep: frozenset[int] = frozenset()) -> FrozenDict[int, c.LifeEvent]:
    if len(events) <= LIFE_CACHE_CAP:
        return events
    return FrozenDict(sorted(events.items(), key=lambda pair: (pair[0] in keep, pair[0]))[-LIFE_CACHE_CAP:])


@MEMORY.reducer(SUBJECT_FORGOTTEN)
def _forget_life(s: MemoryState, e, cx) -> MemoryState:
    """Oublier quelqu'un : ses moments, ses réflexions, ce qu'elle a appris de ses annonces — et ce qu'elle lui
    devait (une promesse dont le texte s'efface ne se tient plus d'elle-même), et ce qui l'a touché de grave."""
    person = e.data.subject
    gone = {i for i, pr in s.promises.items() if pr.to == person}
    return replace(s, events=FrozenDict((i, item) for i, item in s.events.items()
                                        if person not in (*item.about, *item.told_by)),
                   reflections=tuple(r for r in s.reflections if person not in r.about),
                   track=s.track.delete(person) if person in s.track else s.track,
                   promises=FrozenDict((i, pr) for i, pr in s.promises.items() if i not in gone),
                   tries=FrozenDict((i, t) for i, t in s.tries.items() if i not in gone),
                   kept=tuple(k for k in s.kept if k not in gone),
                   keeping=FrozenDict((k, v) for k, v in s.keeping.items() if v[0] not in gone),
                   hard=s.hard.delete(person) if person in s.hard else s.hard)


@MEMORY.reducer(c.LIFE_RECALLED)
def _life_recalled(s: MemoryState, e, cx) -> MemoryState:
    events = s.events
    for item in e.data.items:
        events = events.delete(item.id).set(item.id, item)
        if item.thread and item.thread != item.id:
            s = replace(s, threads=s.threads.set(item.id, item.thread), heads=s.heads.set(item.thread, item.id))
    return replace(s, events=life_cache(events, frozenset(item.id for item in e.data.items)), life_refreshed_at=e.at if e.data.daily else s.life_refreshed_at)


@MEMORY.reducer(c.REMEMBERED, c.BELIEVED)
def _retained(s: MemoryState, e, cx) -> MemoryState:
    """Un élément retenu de plus. Un souvenir ou une croyance marquant et douloureux pour la personne (un deuil vécu
    avec quelqu'un, un proche à l'hôpital) dit aussi que quelque chose de grave touche les personnes qu'il
    concerne."""
    d = e.data
    reflections = tuple(r for r in s.reflections if d.call_id != f"{REFLECTION_MARK}:{r.thought}")
    lies = tuple(seq for seq in s.lies if d.call_id != f"{LIE_MARK}:{seq}")
    s = replace(s, items=s.items + 1, reflections=reflections, lies=lies)
    if d.importance >= params(cx.params).landmark_importance:
        # ce que la personne en ressent d'abord (« son père est à l'hôpital » : elle est inquiète), sinon, pour un
        # souvenir, ce qu'elle-même a ressenti en le vivant (ADR 0083)
        mine = emotion_of(d.emotion) if e.type.name == c.REMEMBERED.name else None
        weight = facets_valence(d.felt) if d.felt else (valence(mine) if mine is not None else 0.0)
        if weight < 0:
            for person in d.about:
                s = _hard(s, person, e.at)
    return s


@MEMORY.reducer(c.REINFORCED, c.NIGHT_SORTED, c.PROMISE_RESOLVED, c.SITUATION_ENDED, c.ATTESTED, c.JOINED,
                c.RETRACTED)
def _index_changed(s: MemoryState, e, cx) -> MemoryState:
    """Un élément a changé de statut ou de texte : l'index des vecteurs se remet à jour (un élément démenti par
    l'opératrice en sort, ADR 0230)."""
    return replace(s, index_revision=e.seq)


@MEMORY.reducer(attention_c.DIGESTED)
def _digested(s: MemoryState, e, cx) -> MemoryState:
    """Ce qui est resté fort toute la journée, repensé la nuit, devient un souvenir."""
    new = tuple(Reflection(i.thought, i.text_ref, tuple(i.about), i.sensitivity, i.emotion)
                for i in e.data.items if i.reflective and i.text_ref)
    return replace(s, reflections=(*s.reflections, *new)[-20:]) if new else s


@MEMORY.reducer(c.NIGHT_SORTED)
def _sorted(s: MemoryState, e, cx) -> MemoryState:
    return replace(s, sorted_night=e.data.night)


@MEMORY.reducer(rss_c.READ, mcp_c.CONSULTED)
def _read(s: MemoryState, e, cx) -> MemoryState:
    """Elle a lu quelque chose : la nuit le relira (ADR 0085)."""
    return replace(s, readings_upto=max(s.readings_upto, e.seq))


@MEMORY.reducer(c.REREAD)
def _reread(s: MemoryState, e, cx) -> MemoryState:
    return replace(s, reread_night=e.data.night)


@MEMORY.reducer(c.PROMISE_NOTICED)
def _promised(s: MemoryState, e, cx) -> MemoryState:
    """Une promesse sans échéance (le journal d'avant l'horizon des promesses
    vagues) reçoit celle d'une promesse vague : rien n'est dû pour toujours."""
    due, implicit = e.data.due, e.data.implicit_due
    if due is None:
        due, implicit = e.at + round(params(cx.params).promise_horizon_days * DAY), True
    promise = c.PendingPromise(e.seq, e.data.to, due, e.at, implicit, all_day=e.data.all_day and not implicit,
                               work=e.data.work, text_ref=e.data.text.ref or "", sensitivity=e.data.sensitivity)
    return replace(s, items=s.items + 1, promises=s.promises.set(e.seq, promise))


@MEMORY.reducer(c.PROMISE_RESOLVED)
def _resolved(s: MemoryState, e, cx) -> MemoryState:
    promise = e.data.promise
    return replace(s, promises=s.promises.delete(promise), tries=s.tries.delete(promise),
                   kept=tuple(k for k in s.kept if k != promise))


@MEMORY.fact(c.CHECKPOINT)
def _checkpoint(s: MemoryState, cx) -> int:
    return s.checkpoint


def _speaks_for(cx, key: str, person: str) -> bool:
    """Une clé notée alors (une adresse, ``name:…``) désigne cette personne maintenant : une adresse reliée depuis à
    quelqu'un, un nom qu'un opérateur a relié à une personne parlent pour elle (ADR 0035, 0048)."""
    resolve, _ = identity_c.resolvers(cx.facts.get)
    return key == person or resolve(key) == person


@MEMORY.fact(c.PROMISES_TO, reads=[identity_c.PERSON])
def _promises_to(s: MemoryState, cx, person: str) -> tuple[c.PendingPromise, ...]:
    return tuple(p for p in s.promises.values() if _speaks_for(cx, p.to, person))


def day_of(t: int, tz: ZoneInfo) -> int:
    """Minuit (heure locale) du jour de cet instant."""
    return instant(datetime.combine(local(t, tz).date(), time(0, 0), tzinfo=tz))


def occurrence(ev: c.LifeEvent, now: int, tz: ZoneInfo, p: MemoryParams) -> c.LifeEvent:
    """Ce moment tel qu'il se présente à ``now`` : lui-même — sauf une date qui revient chaque année, passée depuis
    plus de ``event_recent_days`` : alors sa prochaine occurrence, le même jour à la même heure (un 29 février, le 28
    les autres années), jamais avant celle qui a été notée. L'avoir repris l'an dernier, ce n'est pas l'avoir repris
    cette année : ``followed_at`` d'avant le début de cette occurrence-là repart de zéro."""
    keep = round(p.event_recent_days * DAY)
    if not ev.yearly or now <= ev.when + keep:
        return ev
    first = local(ev.when, tz)
    for year in range(local(now, tz).year - 1, local(now, tz).year + 2):
        try:
            moment = first.replace(year=year)
        except ValueError:  # un 29 février, une année qui n'en a pas
            moment = first.replace(year=year, day=28)
        at = instant(moment)
        if at > ev.when and now <= at + keep:
            return replace(ev, when=at, followed_at=ev.followed_at if ev.followed_at >= day_of(at, tz) else 0)
    return ev


def events_at(s: MemoryState, now: int, tz: ZoneInfo, p: MemoryParams) -> list[c.LifeEvent]:
    """Les moments notés, tels qu'ils se présentent à ``now`` (une date qui revient chaque année : sa prochaine
    occurrence)."""
    return [occurrence(ev, now, tz, p) for ev in s.events.values()]


@MEMORY.fact(c.LIFE_EVENTS, reads=[identity_c.PERSON])
def _life_events(s: MemoryState, cx, person: str) -> tuple[c.LifeEvent, ...]:
    p = params(cx.params)
    events = (occurrence(ev, cx.now, cx.tz, p) for ev in s.events.values()
              if any(_speaks_for(cx, k, person) for k in ev.about))
    return tuple(sorted(events, key=lambda ev: (ev.when, ev.id)))


@MEMORY.fact(c.AHEAD)
def _ahead(s: MemoryState, cx) -> tuple[c.LifeEvent, ...]:
    """Ce qu'elle voit venir (ADR 0084) : les moments du monde et ceux qu'elle vivra à travers quelqu'un, pas finis,
    jusqu'à la fin de leur jour (ou de leur période)."""
    p = params(cx.params)
    ahead = [ev for ev in events_at(s, cx.now, cx.tz, p)
             if (ev.scope == c.WORLD or ev.shared) and not ev.ended_at and not ev.yearly and over(ev) >= cx.now
             and ev.outcome not in (c.CANCELLED, c.MOVED)]
    return tuple(sorted(ahead, key=lambda ev: (ev.when, ev.id)))


@MEMORY.fact(c.UPCOMING)
def _upcoming(s: MemoryState, cx) -> tuple[c.LifeEvent, ...]:
    """Ce qui approche (ADR 0086) : tout moment daté, pas encore tranché, qui commence d'ici ``upcoming_days`` ou se
    déroule — de quelqu'un, du monde, partagé."""
    p = params(cx.params)
    horizon = cx.now + round(p.upcoming_days * DAY)
    near = [ev for ev in s.events.values() if not ev.ongoing and not ev.ended_at and not ev.outcome
            and not ev.yearly and ev.when <= horizon and over(ev) >= cx.now]
    return tuple(sorted(near, key=lambda ev: (ev.when, ev.id)))


@MEMORY.fact(c.TO_CHECK)
def _to_check(s: MemoryState, cx) -> tuple[c.LifeEvent, ...]:
    """Ce qu'elle voudrait vérifier (ADR 0086) : un moment du monde passé depuis moins de ``check_days``, dont elle
    ne sait pas comment il a tourné, et qui lui tient à cœur — important, ou attendu avec un sentiment."""
    p = params(cx.params)
    since = cx.now - round(p.check_days * DAY)
    due = [ev for ev in s.events.values() if ev.scope == c.WORLD and not ev.outcome and not ev.yearly
           and since <= over(ev) < cx.now and (ev.importance >= p.check_importance or ev.empathy)]
    return tuple(sorted(due, key=lambda ev: (-ev.importance, -ev.when, ev.id)))


def over(ev: c.LifeEvent) -> int:
    """Quand un moment est passé : la fin de sa période ; la fin de son jour (minuit, pour un jour noté à 18 h) ; son
    heure, quand elle est dite."""
    if ev.vague:
        return ev.ends
    return ev.when + 6 * HOUR if ev.all_day else ev.when


def hard_since(s: MemoryState, keys: Collection[str], now: int, p: MemoryParams) -> int:
    """Quand quelque chose de grave a touché cette personne (l'une des clés qui la désignent), s'il y a moins de
    ``hard_days`` ; 0 sinon."""
    at = max((s.hard.get(k, 0) for k in keys), default=0)
    return at if at and 0 <= now - at <= round(p.hard_days * DAY) else 0


def heavy_day(s: MemoryState, cx, person: str, p: MemoryParams) -> int:
    """Le début de la journée, quand c'est aujourd'hui que revient une date lourde de cette personne (la date d'un
    deuil) qu'elle lui a confiée elle-même ; 0 sinon. Ce qu'un tiers en a dit ne fait pas d'elle quelqu'un de touché
    aux yeux de Mika."""
    today = day_of(cx.now, cx.tz)
    for ev in s.events.values():
        if not ev.yearly or not ev.told_by or not any(_speaks_for(cx, k, person) for k in ev.about) \
                or not all(_speaks_for(cx, t, person) for t in ev.told_by):
            continue
        this_year = occurrence(ev, cx.now, cx.tz, p)
        if c.heavy_date(this_year) and day_of(this_year.when, cx.tz) == today:
            return today
    return 0


@MEMORY.fact(c.HARD_TIMES, reads=[identity_c.PERSON])
def _hard_times(s: MemoryState, cx, person: str) -> int:
    p = params(cx.params)
    return max(hard_since(s, [k for k in s.hard if _speaks_for(cx, k, person)], cx.now, p),
               heavy_day(s, cx, person, p))
