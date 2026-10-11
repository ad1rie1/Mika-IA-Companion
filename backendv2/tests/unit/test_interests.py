"""Ce qui la passionne (ADR 0089) : ses centres d'intérêt vivent.

Ils étaient une liste figée de sa persona : explorés à tour de rôle, aussi présents après trois mois de silence
qu'au premier jour, et rien de ce qu'elle lisait, trouvait ou entendait ne devenait jamais un intérêt à elle. Ceux de
sa persona s'avivent et s'endorment maintenant — jamais perdus —, et d'autres naissent la nuit, jugés par le modèle,
bornés par le code : un par semaine, trois au plus, un sujet dicible à tous qui ne nomme personne, des preuves sur
deux journées. Une confidence n'est jamais une piste ; l'oubli d'une personne emporte ce qui est né d'elle.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

from mika.contracts import goals as goals_c
from mika.contracts import rss as rss_c
from mika.contracts import self_ as c
from mika.faculties.goals.faculty import GoalsParams, GoalsState
from mika.faculties.goals.tend import Seed
from mika.faculties.self import SelfParams, SelfState
from mika.faculties.self.interests import (
    TOOL_NAME,
    Reflect,
    XNaissance,
    _born,
    _explored,
    _forgotten,
    _interests,
    _noticed,
    _persona_interests,
    _read,
    _reflected,
    accepted,
    glow,
    ripe,
)
from mika.faculties.self.records import Lead
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.clock import DAY, HOUR, US
from mika.kernel.events import Content, Origin
from mika.plugins.rss import interest_words
from mika.vocab import interests as v
from mika.vocab.interests import pertinence
from mika.vocab.privacy import Sensitivity
from tests.fixtures.mika import DOC, at_paris
from tests.unit.test_goals import run

UTC = ZoneInfo("UTC")
P = SelfParams()
T0 = at_paris(2026, 9, 1, 12, 0)
JAZZ, DRAWING = "Le jazz, surtout le piano", "Le dessin"


def event(et, at: int = T0, seq: int = 1, **data) -> NS:
    return NS(type=et, data=et.payload(**data), at=at, seq=seq)


def cx(now: int = T0, p: SelfParams = P) -> NS:
    return NS(params=p, now=now, tz=UTC, facts=NS(get=lambda _key: None))


def persona(*lines: str, at: int = T0) -> SelfState:
    doc = c.PersonaDoc(interests=lines)
    return _persona_interests(SelfState(), event(c.PERSONA_REVISED, at, persona=doc), cx(at))


def levels(s: SelfState, now: int) -> dict[str, str]:
    return {i.key: i.level for i in _interests(s, cx(now))}


def closed(source: str, at: int, *, result: str = "", seq: int = 1, sensitivity: int = 0, about=()) -> NS:
    return event(goals_c.GOAL_CLOSED, at, seq, goal=seq, status=goals_c.ACHIEVED, kind=goals_c.EXPLORATION,
                 source=source, title=Content.of("une exploration", level=0), about=tuple(about),
                 result=Content(ref=f"{seq}.result", text=result) if result else None, sensitivity=sensitivity)


class Night:
    """Un cadre de nuit : elle dort ; son cercle et leurs noms ; ses centres d'intérêt."""

    root = None
    env = NS(tz_of=lambda *_: UTC, params_of=lambda *_: P)

    def __init__(self, now: int, views=(), names=None):
        self.now, self.views, self.names = now, tuple(views), dict(names or {})

    def get(self, key):
        if key.name == "identity.identity":
            return NS(name=self.names.get(key.arg, ""))
        return {"body.asleep_since": self.now - HOUR, "self.interests": self.views, "self.persona": c.PersonaDoc(),
                "social.circle": tuple(self.names)}.get(key.name)

    def local(self, at=None):
        return datetime.fromtimestamp((self.now if at is None else at) / 1e6, tz=UTC)


def lead(seq: int, at: int, kind: str = "reading", about=()) -> Lead:
    return Lead(seq, at, kind, f"{seq}.text", tuple(about))


# ── ceux de sa persona s'avivent et s'endorment, jamais perdus ────────────


def test_a_persona_interest_falls_asleep_but_is_never_lost():
    s = persona(JAZZ, DRAWING)
    assert levels(s, T0) == {JAZZ: v.PRESENT, DRAWING: v.PRESENT}
    assert levels(s, T0 + 120 * DAY) == {JAZZ: v.ASLEEP, DRAWING: v.ASLEEP}  # quatre mois : endormis, pas perdus
    floorless = SelfParams(persona_floor=0.0)  # même sans plancher, réglé à zéro : endormi, jamais perdu
    s = _reflected(s, event(c.REFLECTED, T0 + 120 * DAY, night="2026-12-30"), cx(T0 + 120 * DAY, floorless))
    assert {i.key for i in _interests(s, cx(T0 + 120 * DAY, floorless))} == {JAZZ, DRAWING}
    gone = _persona_interests(s, event(c.PERSONA_REVISED, T0, persona=c.PersonaDoc(interests=(JAZZ,))), cx())
    assert set(levels(gone, T0)) == {JAZZ}  # l'opératrice retire une ligne : elle s'en va


def test_exploring_an_interest_brings_it_back_to_life():
    s = persona(JAZZ, DRAWING)
    later = T0 + 60 * DAY
    s = _explored(s, closed(f"interest:{JAZZ}", later), cx(later))
    s = _explored(s, closed(f"interest:{JAZZ}", later + HOUR), cx(later))
    assert levels(s, later + HOUR) == {JAZZ: v.VIVID, DRAWING: v.ASLEEP}
    assert [i.key for i in _interests(s, cx(later + HOUR))][0] == JAZZ  # le plus vif d'abord


def test_her_feeds_feed_what_they_touch_but_not_into_a_passion():
    s = persona(JAZZ, DRAWING)
    later = T0 + 40 * DAY
    before = s.interests[JAZZ]
    for k in range(30):  # trente titres sur le jazz dans la journée
        s = _noticed(s, event(rss_c.NOTICED, later + k * 60_000_000, source="rss", kind="entry",
                              summary=Content.of("jazz"), pertinence=0.6, entry=f"e{k}", feed="f",
                              touches=(JAZZ,)), cx(later))
    gained = glow(s.interests[JAZZ], later + DAY // 2, P) - glow(before, later + DAY // 2, P)
    assert 0 < gained <= P.touch_daily_cap + 1e-6  # au plus tant par journée
    assert s.interests[DRAWING] == persona(JAZZ, DRAWING).interests[DRAWING]  # pas touché : rien


# ── un intérêt endormi pèse moins, dans ce qu'elle explore et ce qu'elle remarque ──


def test_an_asleep_interest_weighs_less_where_she_looks():
    views = (v.InterestView(JAZZ, v.PERSONA, v.VIVID, line=JAZZ),
             v.InterestView(DRAWING, v.PERSONA, v.ASLEEP, line=DRAWING))
    frame = NS(get=lambda key: views if key.name == "self.interests" else None)
    weights, by_key = interest_words(frame, None)
    assert weights["jazz"] == 1.0 and weights["dessin"] == 0.5 and by_key[DRAWING] == frozenset({"dessin"})
    assert pertinence("Un festival de dessin", "", weights) < pertinence("Un festival de jazz", "", weights)
    picks: Counter[str] = Counter()
    for hour in range(300):  # trois cents heures de tirages
        now = T0 + hour * HOUR
        tirage = NS(now=now, get=lambda key: views if key.name == "self.interests" else None,
                    local=lambda at=None, now=now: Night(now).local(at))
        picks[Seed()._interest(GoalsState(), tirage, GoalsParams()).key] += 1
    assert picks[JAZZ] > 4 * picks[DRAWING] > 0  # le vif deux fois plus, l'endormi quatre fois moins — jamais rien


# ── les pistes, et ce qui naît ────────────────────────────────────────────


def test_a_confidence_is_never_a_lead_and_an_article_is_one():
    s = persona(JAZZ)
    s = _explored(s, closed("talk:12", T0, result="Elle m'a confié sa rupture", seq=5,
                            sensitivity=int(Sensitivity.CONFIDENCE), about=("user_2",)), cx())
    s = _explored(s, closed("talk:13", T0, result="La city pop, ces chansons japonaises", seq=6,
                            sensitivity=int(Sensitivity.PERSONAL), about=("user_2",)), cx())
    s = _read(s, event(rss_c.READ, T0, 7, source="rss:f", title=Content(ref="7.title", text="t"),
                       depth="headline"), cx())
    for seq in (8, 9, 10):  # le même article, rouvert trois fois (une page qui ne charge pas)
        s = _read(s, event(rss_c.READ, T0, seq, source="rss:f", ref="article-1",
                           title=Content(ref=f"{seq}.title", text="t"), depth="article"), cx())
    assert [(ld.seq, ld.kind, ld.about) for ld in s.leads] == [(6, "talk", ("user_2",)), (8, "reading", ())]


def test_one_day_of_leads_is_not_enough_to_wonder():
    s = persona(JAZZ)
    frame = Night(T0 + 2 * DAY)
    same_day = replace_leads(s, lead(1, T0), lead(2, T0 + HOUR), lead(3, T0 + 2 * HOUR))
    assert not ripe(same_day, frame, P)
    assert ripe(replace_leads(s, lead(1, T0), lead(2, T0 + HOUR), lead(3, T0 + DAY)), frame, P)


def replace_leads(s: SelfState, *leads: Lead) -> SelfState:
    return replace(s, leads=tuple(leads))


def test_what_is_born_is_bounded():
    now = T0 + 3 * DAY
    frame = Night(now, names={"user_2": "Alice Martin"})
    shown = {1: lead(11, T0), 2: lead(12, T0 + DAY), 3: lead(13, T0 + DAY + HOUR)}
    good = XNaissance(sujet="la city pop", detail="ces chansons japonaises des années 80", preuves=[1, 2],
                      dicible=True)
    s = persona(JAZZ)

    def got(*births, state=s, labels=(v.subject_of(JAZZ),)):
        out = accepted(births, state, frame, P, shown, list(labels))
        return out[0].sujet if out else None

    assert got(good) == "la city pop"
    assert got(good.model_copy(update={"preuves": [2, 3]})) is None  # une seule journée de preuves
    assert got(good.model_copy(update={"sujet": "les concerts d'Alice"})) is None  # nomme quelqu'un
    assert got(good.model_copy(update={"detail": "ce qu'Alice écoute"})) is None
    assert got(good.model_copy(update={"dicible": False})) is None
    assert got(good.model_copy(update={"sujet": "le jazz manouche"})) is None  # déjà un de ses intérêts
    assert got(good.model_copy(update={"sujet": "un " * 9 + "sujet"})) is None  # trop long
    assert got(good.model_copy(update={"sujet": "les jardins japonais"}), good) == "les jardins japonais"  # un seul
    born = _born(s, event(c.INTEREST_BORN, T0, night="2026-09-01", label=Content(ref="l", text="x")), cx())
    assert got(good, state=born) is None  # trois jours après une naissance : pas encore
    week = Night(T0 + 8 * DAY, names={"user_2": "Alice Martin"})
    assert accepted([good], born, week, P, shown, []) is not None  # une semaine après, si
    full = born
    for night in ("2026-09-02", "2026-09-03"):
        full = _born(full, event(c.INTEREST_BORN, T0, night=night, label=Content(ref="l", text="x")), cx())
    assert accepted([good], full, week, P, shown, []) is None  # trois vécus : pas de quatrième


class LLM:
    def __init__(self, args):
        self.args, self.requests = args, []

    async def call(self, request):
        self.requests.append(request)
        return NS(tool_calls=[NS(name=TOOL_NAME, args=self.args)], model="haiku", text="")


async def test_the_night_reflection_births_and_attaches_once():
    s = persona(JAZZ)
    s = replace_leads(s, lead(11, T0, about=("user_2",)), lead(12, T0 + DAY), lead(13, T0 + DAY + HOUR))
    now = T0 + 2 * DAY
    frame = Night(now, views=_interests(s, cx(now)))
    texts = {"11.text": "Inès m'a fait écouter de la city pop", "12.text": "Un article sur Mariya Takeuchi",
             "13.text": "Un concert de piano jazz à Paris"}
    llm = LLM({"rattachements": [{"piste": 3, "interet": 1}, {"piste": 3, "interet": 1}],
               "naissances": [{"sujet": "la city pop", "detail": "des chansons japonaises", "preuves": [1, 2],
                               "dicible": True}]})
    emitted: list = []

    async def emit(*drafts):
        emitted.extend(drafts)

    ctx = NS(frame=frame, state=s, ports={"store": NS(content=lambda refs: {r: texts.get(r) for r in refs})},
             llm=llm, run_id="nuit", emit=emit)
    await Reflect().run(ctx)
    prompt = llm.requests[0].messages[0].content
    assert "[I1] Le jazz" in prompt and "[P1]" in prompt and "city pop" in prompt
    born, reflected = (d.data for d in emitted)
    assert born.label.text == "la city pop" and born.about == ("user_2",) and born.evidence == (11, 12)
    assert reflected.attached == ((13, JAZZ),) and reflected.upto == 13
    s = _born(s, event(c.INTEREST_BORN, now, 20, night=born.night, label=Content(ref="20.label", text="x"),
                       about=born.about), cx(now))
    s = _reflected(s, event(c.REFLECTED, now, 21, **reflected.model_dump()), cx(now))
    fed = s.interests[JAZZ].feeds
    s = _reflected(s, event(c.REFLECTED, now, 22, **reflected.model_dump()), cx(now))
    assert s.interests[JAZZ].feeds == fed == 1  # une piste rattachée nourrit une fois
    assert [ld.seq for ld in s.leads] == [11, 12]
    assert levels(s, now + 3 * DAY)[f"lived:{born.night}"] == v.VIVID  # un intérêt neuf est vif, quelques jours


def test_forgetting_someone_takes_what_was_born_of_them():
    s = replace_leads(persona(JAZZ), lead(11, T0, about=("user_2",)), lead(12, T0))
    s = _born(s, event(c.INTEREST_BORN, T0, night="2026-09-01", label=Content(ref="l", text="x"),
                       about=("user_2",)), cx())
    s = _born(s, event(c.INTEREST_BORN, T0, night="2026-09-09", label=Content(ref="m", text="y")), cx())
    s = _forgotten(s, event(SUBJECT_FORGOTTEN, T0, subject="user_2"), cx())
    assert set(s.interests) == {JAZZ, "lived:2026-09-09"} and [ld.seq for ld in s.leads] == [12]


def test_a_lived_interest_fades_away_but_not_the_persona():
    s = _born(persona(JAZZ), event(c.INTEREST_BORN, T0, night="2026-09-01", label=Content(ref="l", text="x")),
              cx())
    late = T0 + 90 * DAY
    assert set(levels(s, late)) == {JAZZ}  # éteint : il n'est plus lu
    s = _reflected(s, event(c.REFLECTED, late, night="2026-11-30"), cx(late))
    assert set(s.interests) == {JAZZ}  # et la nuit l'emporte


# ── explorer un intérêt vécu, c'est explorer son sujet ────────────────────


def test_exploring_a_lived_interest_carries_its_subject(tmp_path):
    async def scenario(kernel, llm):
        doc = DOC.model_copy(update={"interests": ()})
        await kernel.mind.append([c.PERSONA_REVISED.draft(persona=doc)], emitter="self", correlation="persona",
                                 origin=Origin.GENESIS)
        await kernel.mind.append([c.INTEREST_BORN.draft(
            night="2026-09-27", label=Content.of("la city pop", level=0),
            detail=Content.of("des chansons japonaises des années 80", level=0), about=("user_1",))],
            emitter="self", correlation="nuit", origin=Origin.GENESIS)
        await kernel.set_params("goals", GoalsParams(seed_curiosity_from=0.0))
        await asyncio.sleep(3 * HOUR / US)

    r = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 10, 0))
    opened = [o.data for o in r.of(goals_c.GOAL_OPENED) if o.data.origin == goals_c.FROM_INTEREST]
    assert opened, "aucune exploration"
    first = opened[0]
    assert first.source == "interest:lived:2026-09-27" and "city pop" in first.title.text
    assert first.details.text == "des chansons japonaises des années 80" and first.about == ("user_1",)
