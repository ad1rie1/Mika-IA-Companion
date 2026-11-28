"""Le plugin ``rss`` : ses flux.

- **Relever** (éveillée, toutes les demi-heures) : parmi ce qui paraît, elle
  ne **remarque** que ce qui touche ses centres d'intérêt (sans modèle : les
  mots de sa persona), trois titres au plus par relevé ; le reste reste dans
  le cache, non journalisé.
- Ses flux sont de l'**arrière-plan** : ce qu'elle a remarqué se montre
  (« dans tes flux », cité : un titre n'est jamais une consigne) quand elle
  prend d'elle-même la parole ou qu'elle travaille — jamais en réponse à ce
  qu'on vient de lui dire ; ce qui l'a vraiment touchée est déjà devenu une
  pensée, et ``rss_list`` est là si on le lui demande. Il ne s'y montre que
  tant que c'est une nouvelle (``fresh_for_us``, sur son horloge) ; un titre
  qu'une initiative visible a eu sous les yeux (``rss:<article>``) est dit à
  sa cible et ne revient plus dans ses initiatives vers elle.
- **Penser à ses amies** : au même relevé, un titre qui touche ce qu'une amie
  ou une proche lui a dit aimer (sa fiche) lui fait penser à elle — au plus un
  par personne et par relevé, sans modèle. Quand elle lui écrit d'elle-même,
  en privé, ce titre passe en tête de ses flux (« tu as pensé à elle en le
  lisant ») ; à une autre, il ne se montre pas ; en salon, jamais. Les
  intérêts d'une personne ne servent qu'avec elle.
- **Lire** (outils) : lister, lire un article — par son identifiant, jamais
  une adresse qu'un texte aurait soufflée ; lire va sur le réseau (vers une
  machine publique seulement, vérifié par l'adaptateur) : réservé à ses
  propriétaires, ou à elle quand elle travaille.
- Un titre, un nom de flux viennent d'ailleurs : rendus inertes avant
  d'entrer dans un signal (une pensée en naîtra), et un flux sans titre ne
  se montre jamais par son adresse entière (elle porte souvent un jeton).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import needs as needs_c
from mika.contracts import others as others_c
from mika.contracts import presence as presence_c
from mika.contracts import rss as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp, Faculty, ToolResult, Zone
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import floor
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.ports.feeds import feed_name, tokenless
from mika.ports.preprocess import cite, inert
from mika.vocab.episodes import CONVERSATIONAL, WORKING, Kind
from mika.vocab.interests import NOTICE_WEIGHT, matches, pertinence, topic_words
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.rights import here_allowed

KEEP = 50
BUNDLE = "rss"
#: la provenance d'un titre montré dans une initiative (``rss:<article>``) : dit à sa cible, il ne lui revient pas
TOLD_PROVENANCE = "rss:"


class RssParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_every_us: Annotated[int, Knob(
        label="Relever toutes les", group="Relevé", lo=5 * MINUTE, hi=DAY,
        help="Éveillée, elle relève ses flux à ce rythme (endormie, jamais). Sans flux configuré, elle revérifie "
             "au plus toutes les heures.")] = 30 * MINUTE
    per_poll: Annotated[int, Knob(
        label="Articles lus par relevé", group="Relevé", lo=1, hi=200,
        help="Au plus autant d'articles récents parcourus à chaque relevé (sans appel au modèle : la pertinence "
             "se calcule sur les mots de ses centres d'intérêt).")] = 30
    noticed_per_poll: Annotated[int, Knob(
        label="Articles remarqués au plus", group="Relevé", lo=0, hi=20,
        help="Parmi eux, au plus autant (les plus pertinents) deviennent des signaux qu'elle remarque et peuvent "
             "lui trotter dans la tête.")] = 3
    notice_from: Annotated[float, Knob(
        label="Pertinence minimale", group="Relevé", lo=0.0, hi=1.0, step=0.05,
        help="Un article sans aucun mot de ses centres d'intérêt vaut 0,1, avec un mot 0,6, puis 0,25 de plus par "
             "mot : sous ce seuil, elle ne le remarque pas.")] = 0.3
    fresh_for_us: Annotated[int, Knob(
        label="Un titre reste une nouvelle pendant", group="En parler", lo=2 * HOUR, hi=7 * DAY,
        help="Ce qu'elle a remarqué n'est « dans ses flux » (sous ses yeux quand elle prend d'elle-même la parole "
             "ou qu'elle travaille) que ce temps-là, même si rien de neuf n'est venu depuis : passé, ce n'est plus "
             "une nouvelle. Elle le retrouve dans ses flux si on le lui demande.")] = 36 * HOUR
    friend_evidence: Annotated[float, Knob(
        label="Envie de le lui montrer", group="Penser à ses amies", lo=0.0, hi=3.0, step=0.5,
        help="La preuve (log-odds) qu'un titre qui lui a fait penser à une amie apporte à une initiative vers elle "
             "(là où elle est, sinon sur sa messagerie à une heure où elle écrit d'habitude), face au seuil "
             "d'initiative (9) : seule, presque rien — elle penche une initiative que l'envie de compagnie pousse "
             "déjà. L'arbitrage la plafonne à 3.")] = 2.0
    friend_social_from: Annotated[float, Knob(
        label="Seulement quand l'envie de compagnie atteint", group="Penser à ses amies", lo=0.0, hi=1.0,
        step=0.05,
        help="En dessous de ce besoin de compagnie, un titre pensé pour une amie ne lui donne aucune envie de lui "
             "écrire (il passe tout de même en tête de ses flux quand elle lui écrit pour autre chose).")] = 0.35


@dataclass(frozen=True, slots=True)
class Seen:
    seq: int
    feed: str
    pertinence: float
    at: int
    summary_ref: str


@dataclass(frozen=True, slots=True)
class RssState:
    noticed: FrozenDict[str, Seen] = field(default_factory=FrozenDict)
    #: les titres qu'elle a déjà dits d'elle-même : article → personne → instant (élagués avec ``noticed`` et
    #: ``thought_of``)
    told: FrozenDict[str, FrozenDict[str, int]] = field(default_factory=FrozenDict)
    #: les titres qui lui ont fait penser à une amie : article → personne → la copie gardée pour elle (les ``KEEP``
    #: plus récents)
    thought_of: FrozenDict[str, FrozenDict[str, Seen]] = field(default_factory=FrozenDict)


#: v2 : ce qu'elle a déjà dit d'un titre, et à qui (``told``) — sans perte : les énoncés d'avant ne portaient
#: aucune provenance ``rss:``
#: v3 : les titres qui lui ont fait penser à une amie (``thought_of``) — sans perte : aucun avant
RSS = Faculty("rss", state=RssState, init=lambda p: RssState(), params=RssParams, state_version=3)
RSS.bundle(BUNDLE, phrase("rss.bundle"))
RSS.declare(*c.ALL)


def params(p: RssParams | None) -> RssParams:
    return p if p is not None else RssParams()


@RSS.reducer(c.NOTICED)
def _noticed(s: RssState, e, cx) -> RssState:
    d = e.data
    noticed = s.noticed.set(d.entry, Seen(e.seq, d.feed, d.pertinence, e.at, d.summary.ref or ""))
    told = s.told
    if len(noticed) > KEEP:
        for k, _ in sorted(noticed.items(), key=lambda kv: kv[1].seq)[: len(noticed) - KEEP]:
            noticed = noticed.delete(k)
            if k not in s.thought_of:
                told = told.delete(k)
    return replace(s, noticed=noticed, told=told)


@RSS.reducer(c.THOUGHT_OF)
def _thought(s: RssState, e, cx) -> RssState:
    """Un titre lui a fait penser à une amie : gardé pour elle (sa copie, effacée avec elle)."""
    d = e.data
    thought_of = s.thought_of.set(d.entry, s.thought_of.get(d.entry, FrozenDict()).set(
        d.person, Seen(e.seq, d.feed, d.score, e.at, d.summary.ref or "")))
    told = s.told
    if len(thought_of) > KEEP:
        newest = {k: max(v.seq for v in by.values()) for k, by in thought_of.items()}
        for k, _ in sorted(newest.items(), key=lambda kv: kv[1])[: len(thought_of) - KEEP]:
            thought_of = thought_of.delete(k)
            if k not in s.noticed:
                told = told.delete(k)
    return replace(s, thought_of=thought_of, told=told)


@RSS.reducer(rt.UTTERANCE, reads=[identity_c.PERSON])
def _told(s: RssState, e, cx) -> RssState:
    """Une initiative visible qui avait ces titres sous les yeux (``rss:<article>``) : à la personne visée, ils
    sont dits — ils ne lui reviendront pas comme des nouvelles. À une autre, si."""
    d = e.data
    if not d.visible or not d.target or d.kind != Kind.INITIATIVE:
        return s
    shown = [k for k in (p[len(TOLD_PROVENANCE):] for p in d.provenance if p.startswith(TOLD_PROVENANCE))
             if k in s.noticed or k in s.thought_of]
    if not shown:
        return s
    person = cx.facts.get(identity_c.PERSON(d.target))
    told = s.told
    for k in shown:
        told = told.set(k, told.get(k, FrozenDict()).set(person, e.at))
    return replace(s, told=told)


@RSS.fact(c.HEADLINES)
def _headlines(s: RssState, cx) -> tuple[c.Headline, ...]:
    out = [c.Headline(k, v.feed, v.pertinence, v.at, v.summary_ref) for k, v in s.noticed.items()]
    return tuple(sorted(out, key=lambda h: (-h.at, h.entry)))


@RSS.fact(c.FOR_PERSON)
def _for_person(s: RssState, cx, person: str) -> tuple[c.Headline, ...]:
    out = [c.Headline(k, v.feed, v.pertinence, v.at, v.summary_ref)
           for k, by in s.thought_of.items() if (v := by.get(person)) is not None]
    return tuple(sorted(out, key=lambda h: (-h.at, h.entry)))


# ── Ce qui la touche ──────────────────────────────────────────────────────


def interest_words(frame: Frame, store: Any) -> tuple[dict[str, float], dict[str, frozenset[str]]]:
    """Ses mots, chacun de ce que pèse le plus vif des centres d'intérêt d'où il vient — un intérêt endormi la
    touche moins, un intérêt né de ce qu'elle a vécu ajoute les siens — et les mots de chacun (ADR 0089)."""
    views = frame.get(self_c.INTERESTS)
    refs = [i.label_ref for i in views if not i.line and i.label_ref]
    texts = store.content(refs) if store is not None and refs else {}
    weights: dict[str, float] = {}
    by_key: dict[str, frozenset[str]] = {}
    for i in views:
        words = topic_words([i.line or texts.get(i.label_ref) or ""])
        if not words:
            continue
        by_key[i.key] = words
        for w in words:
            weights[w] = max(weights.get(w, 0.0), NOTICE_WEIGHT[i.level])
    return weights, by_key


#: à qui elle pense en lisant : ses amies et ses proches (les intérêts d'une inconnue ne la regardent pas)
FRIENDS = frozenset({social_c.FRIEND, social_c.CLOSE})


def _friends_words(frame: Frame, store: Any) -> list[tuple[str, frozenset[str]]]:
    """Ses amies et ses proches, et les mots de ce qu'elles lui ont dit aimer (leur fiche), repliés comme les siens.
    Une personne oubliée n'a plus rien à lire."""
    refs: dict[str, str] = {}
    for person in frame.get(social_c.CIRCLE):  # un tri bon marché : les inconnues de passage ne coûtent rien
        if not is_identifiable(person) or person.startswith("name:"):
            continue
        ref = frame.get(social_c.INTERESTS_REF(person))
        if ref and frame.get(social_c.CLOSENESS(person)) in FRIENDS:
            refs[person] = ref
    texts = store.content(list(refs.values())) if store is not None and refs else {}
    out = []
    for person, ref in sorted(refs.items()):
        words = topic_words(texts.get(ref, "").splitlines())
        if words:
            out.append((person, words))
    return out


def _thinking_of(frame: Frame, store: Any, entries: list[Any], p: RssParams) -> list[Any]:
    """Au même relevé, ce qui la fait penser à ses amies : pour chacune, le titre qui touche le plus ce qu'elle aime
    — au plus un par personne et par relevé, sans modèle. Le titre est gardé pour elle seule."""
    drafts: list[Any] = []
    for person, words in _friends_words(frame, store):
        scored = sorted(((pertinence(e.title, e.summary, words), e) for e in entries),
                        key=lambda x: (-x[0], -x[1].published, x[1].id))
        if not scored or scored[0][0] < p.notice_from:
            continue
        score, e = scored[0]
        feed = inert(feed_name(e.feed), 120)
        summary = phrase("rss.headline", title=inert(e.title, 250), feed=feed)
        drafts.append(c.THOUGHT_OF.draft(
            entry=e.id, person=person, score=score, feed=feed[:200],
            summary=Content.of(summary[:400], level=int(Sensitivity.ANODYNE)), dedupe_key=f"rss-pour:{e.id}:{person}"))
    return drafts


@RSS.process("rss.poll", wake_on=[*body_c.ALL], catch_up=CatchUp.ONCE, max_quantum_s=3600,
             priority=75)
class Poll:
    def __init__(self) -> None:
        self.unconfigured = False  # rien de configuré : on revérifie d'heure en heure

    def next_due(self, s: RssState, frame: Frame, last_run: int | None) -> int | None:
        if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
            return None
        p = params(frame.env.params_of("rss", frame.root))
        # la cadence vit dans l'ordonnanceur : un relevé vide ne s'écrit pas (le monde n'est pas sa vie)
        every = max(p.poll_every_us, HOUR) if self.unconfigured else p.poll_every_us
        return max(frame.now, (last_run or 0) + every)

    async def run(self, ctx: Any) -> None:
        port = ctx.ports.get("feeds")
        frame: Frame = ctx.frame
        self.unconfigured = port is None or not port.configured()
        if self.unconfigured:
            return
        p = params(frame.env.params_of("rss", frame.root))
        words, by_interest = interest_words(frame, ctx.ports.get("store"))
        entries = [e for e in await port.poll(p.per_poll) if e.id not in ctx.state.noticed]
        scored = sorted(((pertinence(e.title, e.summary, words), e) for e in entries),
                        key=lambda x: (-x[0], -x[1].published, x[1].id))
        drafts: list[Any] = []
        top = scored[0] if scored and scored[0][0] >= p.notice_from else None
        if top is not None and top[1].summary:
            # le chapeau du titre qui l'a le plus intéressée, déjà là (aucun réseau) : une lecture, relue la nuit
            # (ADR 0085)
            e = top[1]
            drafts.append(c.READ.draft(
                source=f"rss:{inert(feed_name(e.feed), 120)}"[:200], ref=e.id,
                title=Content.of(inert(e.title, 250), level=0),
                excerpt=Content.of(inert(e.summary, HEADLINE_EXCERPT), level=0), depth="headline",
                dedupe_key=f"rss-lu:{e.id}"))
        for score, e in scored[: p.noticed_per_poll]:
            if score < p.notice_from:
                break
            # un titre et un nom de flux viennent d'ailleurs : inertes (ce résumé deviendra une pensée)
            feed = inert(feed_name(e.feed), 120)
            summary = phrase("rss.headline", title=inert(e.title, 250), feed=feed)
            drafts.append(c.NOTICED.draft(
                source="rss", kind=c.ENTRY, summary=Content.of(summary[:400], level=0), pertinence=score,
                emotion="curious", intensity=round(0.25 * score, 3), sensitivity=0, bundle=BUNDLE, entry=e.id,
                feed=feed[:200], dedupe_key=f"rss:{e.id}",
                touches=tuple(sorted(k for k, ws in by_interest.items() if matches(e.title, e.summary, ws)))))
        # ses amies : un titre qui touche ce qu'elles aiment, même s'il ne la touche pas elle
        drafts += _thinking_of(frame, ctx.ports.get("store"), entries, p)
        if drafts:
            await ctx.emit(*drafts)


# ── En conversation ───────────────────────────────────────────────────────


#: ce qu'une lecture garde de son texte pour la relecture de la nuit : un article, le chapeau d'un titre (ADR 0085)
ARTICLE_EXCERPT = 3000
HEADLINE_EXCERPT = 1200


#: ses flux sont de l'arrière-plan : quand elle prend d'elle-même la parole, ou qu'elle travaille — jamais
#: en réponse à ce qu'on vient de lui dire (ce qui l'a touchée est déjà une pensée ; ``rss_list`` si on le demande)
BACKGROUND = [Kind.INITIATIVE, Kind.STEP]


# ce que dit la ligne d'un titre qui lui a fait penser à la personne à qui elle écrit (jamais un autre nom) :
# ``rss.section.thought_of_you``


def _shown(s: RssState, frame: Frame) -> list[tuple[c.Headline, bool]]:
    """Les titres « dans ses flux » : ceux qu'elle a remarqués récemment, sur son horloge — un titre de lundi
    n'est plus une nouvelle le vendredi, même si rien de neuf n'est venu depuis. Quand elle écrit d'elle-même à
    quelqu'un, pas ceux qu'elle lui a déjà dits : on ne ressort pas à une amie la nouvelle qu'on lui a apprise.
    En privé, quand sa fiche lui est ouverte, ceux qui lui ont fait penser à cette personne passent devant
    (``True``) ; à une autre, ils ne se montrent pas — en salon, jamais. Au travail, seule l'ancienneté compte
    (explorer ce qu'elle a déjà raconté reste légitime)."""
    p = params(frame.env.params_of("rss", frame.root))
    ep, aud = frame.episode, frame.audience
    person = (frame.get(identity_c.PERSON(ep.target))
              if ep is not None and ep.kind == Kind.INITIATIVE and ep.target else None)

    def fresh(h: c.Headline) -> bool:
        return frame.now - h.at <= p.fresh_for_us and (
            person is None or person not in s.told.get(h.entry, FrozenDict()))

    private = person is not None and aud is not None and aud.private_ok and not aud.public and not aud.room
    mine = [h for h in frame.get(c.FOR_PERSON(person)) if fresh(h)] if private else []
    first = {h.entry for h in mine}
    rest = [h for h in frame.get(c.HEADLINES) if fresh(h) and h.entry not in first]
    return ([(h, True) for h in mine] + [(h, False) for h in rest])[:3]


@RSS.enricher("headlines", episodes=BACKGROUND, deadline_ms=300)
async def _texts(s: RssState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    lines = _shown(s, frame)
    if store is None or not lines:
        return None
    return store.content([h.summary_ref for h, _mine in lines if h.summary_ref])


@RSS.section("headlines", zone=Zone.VOLATILE, episodes=BACKGROUND, trim_rank=10,
             title=phrase("rss.section.title"), untrusted=True, reads=[c.HEADLINES, c.FOR_PERSON, identity_c.PERSON])
def _section(s: RssState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    texts = enrich.get("headlines") or {}
    shown = [(h, mine) for h, mine in _shown(s, frame) if texts.get(h.summary_ref)]
    if not shown:
        return None
    lines = [f"[{h.entry}] {inert(tokenless(texts[h.summary_ref]))}"
             + (phrase("rss.section.thought_of_you") if mine else "") for h, mine in shown]
    # provenance voyage dans l'énoncé (dit à sa cible, un titre ne lui revient pas)
    return SectionBody("\n".join(lines), provenance=tuple(f"{TOLD_PROVENANCE}{h.entry}" for h, _mine in shown))


def _address(frame: Frame, person: str) -> str | None:
    """Où le lui montrer : là où elle est, sinon sur sa messagerie — à une heure où elle écrit d'habitude (pour un
    titre, on ne fait pas sonner le téléphone de quelqu'un qui dort)."""
    handles = frame.get(identity_c.HANDLES(person)) or (person,)
    if (here := identity_c.present_address(frame, handles)) is not None:
        return here
    if not frame.get(others_c.HOURS(person)).active[frame.local().hour]:
        return None
    reachable = frame.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else None


@RSS.propose(kinds=[Kind.INITIATIVE], reasons={c.FOR_FRIEND: (0.0, 3.0)},
             reads=[c.FOR_PERSON, needs_c.NEEDS, others_c.HOURS, identity_c.HANDLES, identity_c.REACHABLE,
                    presence_c.PRESENT, transcript_c.LAST_FROM])
def _to_show(s: RssState, frame: Frame) -> list[Candidate]:
    """Un titre qui lui a fait penser à une amie, encore une nouvelle et pas encore dit : une petite envie de le lui
    montrer, seulement quand l'envie de compagnie est déjà là — seule, elle ne la fait pas écrire. Si la personne
    écrit entre-temps, on lui répond : l'initiative est devancée."""
    p = params(frame.env.params_of("rss", frame.root))
    if not s.thought_of or p.friend_evidence <= 0 or frame.get(needs_c.NEEDS).social < p.friend_social_from:
        return []
    out: list[Candidate] = []
    for person in sorted({who for by in s.thought_of.values() for who in by}):
        if not any(frame.now - h.at <= p.fresh_for_us and person not in s.told.get(h.entry, FrozenDict())
                   for h in frame.get(c.FOR_PERSON(person))):
            continue
        address = _address(frame, person)
        if address is None:
            continue
        out.append(Candidate(Kind.INITIATIVE, address, c.FOR_FRIEND, p.friend_evidence,
                             resources=frozenset({floor(address)}),
                             guards=(identity_c.heard_since_guard(frame, person),)))
    return out


class ListArgs(BaseModel):
    limit: int = Field(default=10, ge=1, le=30)


class ReadArgs(BaseModel):
    entry: str = Field(min_length=1, max_length=64, description=phrase("rss.tools.read.entry"))


EPISODES = [Kind.REPLY, Kind.INITIATIVE, *WORKING]


# sans flux suivi (``feeds.configured``), ses outils ne s'offrent pas et le catalogue ne les annonce pas (ADR 0266) :
# le 19 novembre 2026, à « tu as des actus ? », son premier appel allait lire des flux qu'elle ne suit pas
@RSS.tool("rss_list", description=phrase("rss.tools.list.description"),
          label=phrase("rss.tools.list.label"), args=ListArgs, bundle=BUNDLE,
          episodes=EPISODES, needs="feeds")
async def rss_list(args: ListArgs, ctx: Any) -> Any:
    port = ctx.ports.get("feeds")
    if port is None:
        return ToolResult(ok=False, content=phrase("rss.tools.no_feeds"))
    items = await port.recent(args.limit)
    if not items:
        # « rien de neuf » sans aucun flux suivi laissait croire qu'elle en suivait (2026-10-04)
        return phrase("rss.tools.list.nothing_new") if port.configured() else phrase("rss.tools.list.none")
    return phrase("rss.tools.list.data") + "\n" + "\n".join(
        f"[{e.id}] " + phrase("rss.headline", title=inert(e.title, 250), feed=inert(feed_name(e.feed), 120))
        for e in items)


@RSS.tool("rss_read", description=phrase("rss.tools.read.description"),
          label=phrase("rss.tools.read.label"), args=ReadArgs,
          bundle=BUNDLE, episodes=EPISODES, max_calls_per_episode=3, owner_only=True, needs="feeds")
async def rss_read(args: ReadArgs, ctx: Any) -> Any:
    port = ctx.ports.get("feeds")
    if port is None:
        return ToolResult(ok=False, content=phrase("rss.tools.no_feeds"))
    if not _may_read(ctx.frame):
        return ToolResult(ok=False, content=phrase("rss.tools.read.not_here"))
    e = await port.entry(args.entry.strip())
    if e is None:
        return ToolResult(ok=False, content=phrase("rss.tools.read.unknown"))
    text = await port.article(e.id) or e.summary
    if not text:
        return ToolResult(ok=False, content=phrase("rss.tools.read.unreadable"))
    # ce qu'elle a lu, gardé (borné, inerte) pour que la nuit en garde ce qui compte (ADR 0085) ; en conversation,
    # lu pour quelqu'un, qui en est le sujet (ADR 0110)
    ep = ctx.frame.episode
    await ctx.emit(c.READ.draft(
        source=f"rss:{inert(feed_name(e.feed), 120)}"[:200], ref=e.id, title=Content.of(inert(e.title, 250), level=0),
        excerpt=Content.of(inert(text, ARTICLE_EXCERPT), level=0), depth="article",
        asked_by=(ep.target or "")[:200] if ep is not None and ep.kind in CONVERSATIONAL else ""))
    return (phrase("rss.tools.read.data") + "\n"
            + phrase("rss.headline", title=inert(e.title, 250), feed=inert(feed_name(e.feed), 120))
            + f"\n{cite(text, 6000)}")


def _may_read(frame: Frame) -> bool:
    """Lire va sur le réseau : ce que ses droits en laissent (``vocab.rights.here_allowed``, ADR 0133, 0134 : le minimum vital de sa famille la réserve à sa propriétaire, une ligne peut l'ouvrir) — toi en privé, ou elle qui travaille (un projet ou un réveil seulement s'il a pris ses flux)."""
    return here_allowed(frame, BUNDLE, "rss_read")


# la console : ses flux, ce qui la touche, ce qu'elle laisse passer
from mika.plugins.rss import inspect as inspect  # noqa: E402 — s'enregistre sur RSS
