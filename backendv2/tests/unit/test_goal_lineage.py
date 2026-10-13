"""Un but garde la filiation de la pensée d'où il est né (lot I du chantier « émotions, conscience, mémoire »,
ADR 0097).

Une pensée sait d'où elle vient (ce qu'on lui a confié, et comment : en secret, à qui) et ne se redit que devant qui
ses sources le permettent (ADR 0078). Devenue un but (« Repenser à ce que « Alice » m'a confié »), elle perdait cette
filiation : le but ne gardait que ses personnes et un niveau, et son titre, son résultat se montraient (« CE QUE TU AS
EN TRAIN ») là où la pensée elle-même se serait tue — un secret confié par Alice racontable à Bob parce qu'elle y
avait repensé.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

from mika.contracts import goals as goals_c
from mika.faculties.goals.faculty import Goal, audible
from mika.kernel.frame import Audience
from mika.vocab.lineage import Lineage, requirement
from mika.vocab.privacy import Sensitivity

FRIEND_LEVEL = int(Sensitivity.CONFIDENCE)


def frame(person: str) -> NS:
    """Une conversation privée et sûre avec une amie proche (elle entendrait une confidence sur autrui)."""
    aud = Audience(persons=(person,), public=False, level=FRIEND_LEVEL, witness_level=FRIEND_LEVEL, private_ok=True,
                   untied_level=FRIEND_LEVEL)
    return NS(audience=aud, get=lambda key: "")


def goal(lineage: Lineage | None) -> Goal:
    return Goal(id=1, kind=goals_c.EXPLORATION, authority=goals_c.SELF, title_ref="1.title", opened_at=0,
                owner="alice", about=("alice",), sensitivity=int(Sensitivity.PERSONAL), source="thought:9",
                origin=goals_c.FROM_EXCHANGE, lineage=lineage)


def test_a_reflection_on_a_secret_is_not_told_to_another_friend():
    secret = Lineage(sources=(9,), requirements=(requirement(9, ("alice",), int(Sensitivity.CONFIDENCE),
                                                             told_by=("alice",), heard_by=("alice",), secret=True),))
    assert not audible(goal(secret), "bob", frame("bob"))
    assert audible(goal(secret), "alice", frame("alice"))  # à celle qui le lui a confié


def test_without_a_lineage_the_rule_of_its_people_holds():
    assert audible(goal(None), "bob", frame("bob"))
    assert not audible(goal(None), "bob", NS(audience=None, get=lambda key: ""))


def test_the_goal_born_of_a_thought_keeps_its_lineage():
    """La pensée (une croyance révisée, que Bob lui avait confiée en secret sur Sam) devient un but : sa filiation
    le suit."""
    import asyncio
    from datetime import datetime

    from mika.contracts import attention as attention_c
    from mika.contracts import body as body_c
    from mika.faculties.goals.faculty import GoalsParams, GoalsState
    from mika.faculties.goals.tend import Seed
    from mika.kernel.clock import DAY

    secret = Lineage(sources=(9,), requirements=(requirement(9, ("sam",), int(Sensitivity.CONFIDENCE),
                                                             told_by=("bob",), secret=True),))
    thought = attention_c.ThoughtReading(id=12, text_ref="12.text", emotion="confused", intensity=0.8,
                                         origin=attention_c.REVISION, about=("sam",), sensitivity=3, born_at=0,
                                         lineage=secret)
    facts = {"body.sleep": body_c.SleepPhase.AWAKE, "attention.thoughts": (thought,),
             "identity.identity": NS(name="Sam"), "identity.owners": (),
             "forge.apps": (), "projects.live": ()}
    now = DAY
    frame = NS(now=now, get=lambda key: facts[key.name], env=NS(params_of=lambda *_: GoalsParams()), root=None,
               local=lambda t=None: datetime(2026, 10, 12, 15, 0))
    emitted = []

    async def emit(*drafts, **_kw):
        emitted.extend(drafts)

    ctx = NS(frame=frame, state=GoalsState(), ports={"store": NS(content=lambda refs: {r: "Sam…" for r in refs})},
             emit=emit)
    asyncio.run(Seed().run(ctx))
    assert emitted and emitted[0].data.lineage == secret


def test_the_goal_remembers_its_lineage():
    from mika.faculties.goals.faculty import GoalsState, _opened
    from mika.kernel.events import Content

    lineage = Lineage(sources=(9,), requirements=(requirement(9, ("sam",), 3, told_by=("bob",), secret=True),))
    d = goals_c.GoalOpened(kind=goals_c.EXPLORATION, authority=goals_c.SELF,
                           title=Content(ref="5.title", text="Repenser à ce que je croyais", level=3),
                           about=("sam",), source="thought:12", sensitivity=3, origin=goals_c.FROM_REVISION,
                           lineage=lineage)
    s = _opened(GoalsState(), NS(seq=5, at=0, data=d), NS(params=None))
    assert s.goals[5].lineage == lineage
