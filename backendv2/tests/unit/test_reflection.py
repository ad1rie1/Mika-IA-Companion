"""Une réflexion sur quelqu'un (ADR 0053), par ses intentions.

Sonde réelle du 2026-10-03 : Sam, endeuillé, répond « ouais », « bof », « je sais pas », « laisse tomber »,
« désolé je suis pas d'humeur ». Une pensée naît de « laisse tomber », devient « Repenser à ce que Sam m'a
confié » : quatorze appels où elle écrit « c'est venu comme ça, sans contexte », fouille sa mémoire au hasard, et
conclut que Sam lui reprochait son perfectionnisme sur un « nouveau format de stream » — inventé.

- la pensée née d'un échange porte ce qu'il voulait dire (il répondait à peine), pas une réplique isolée ;
  contre-exemple : un échange nourri garde son moment le plus marquant ;
- la réflexion a l'échange sous les yeux, et ce qui se passe dans la vie de la personne (rien d'un tiers) ;
- elle tient en une séance, même si le modèle dit « je reprendrai » ; contre-exemple : une exploration qui va
  lire ses flux continue ;
- ce qu'elle écrit en y repensant ne devient ni un souvenir ni une croyance sur l'autre.
"""

from __future__ import annotations

import asyncio

from mika.contracts import attention as attention_c
from mika.contracts import goals as goals_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMResponse
from mika.sim.clock import run_virtual
from mika.sim.llm.persona import _section
from tests.fixtures.mika import at_paris, befriend, boot, build, connect, said
from tests.unit.test_projects import llm_call

FRIDAY_18H = at_paris(2026, 10, 9, 18, 30)
SAM_EVENING = [("ouais", "hopeful", 0.6), ("bof", "hopeful", 0.6), ("je sais pas", "hopeful", 0.6),
               ("laisse tomber", "sad", 0.7), ("désolé je suis pas d'humeur. à demain", "sad", 0.6)]
REFLECTION = ("CANARI-REFLEXION Sam n'avait pas le cœur à parler ce soir, Pixel lui manque et son anniversaire "
              "arrive : je lui laisse de l'air, et je prendrai de ses nouvelles demain, doucement.")


class Mika:
    """Un modèle scripté : le ton de ses réponses se règle ; une séance de travail écrit sa réflexion puis
    conclut par ``verdict``."""

    def __init__(self, verdict: str = "done") -> None:
        self.tag = ("happy", 0.5)
        self.verdict = verdict

    def __call__(self, req):
        if req.role in ("extract", "profile", "compact"):
            return LLMResponse("{}")
        if req.role == "step":
            if [m for m in req.messages if m.role == "tool"]:
                return LLMResponse("Voilà.")
            if self.verdict == "silent":
                return LLMResponse("je ne sais pas trop")
            return llm_call(req, ("goal_reflect", {"text": REFLECTION}),
                            ("report_step", {"verdict": self.verdict, "summary": "J'y ai repensé.", "notable": 0.6}))
        if req.role in ("murmur", "narrative", "journal", "dream"):
            return LLMResponse("hmm")
        emotion, intensity = self.tag
        return LLMResponse(f"je vois [EMOTION:{emotion}:{intensity}]")


def live(tmp_path, scenario, mika: Mika | None = None, start: int = FRIDAY_18H):
    mika = mika or Mika()
    kernel, clock, llm, _ = build(tmp_path, mika, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel, mika)
        finally:
            await kernel.stop()

    return run_virtual(clock, main), llm


def of(kernel, event_type):
    mind = kernel.mind
    return [mind.decode(e) for e in mind.store.read() if e.type == event_type.name]


async def sam_evening(kernel, mika: Mika, lines=SAM_EVENING) -> None:
    await befriend(kernel, "user_1", "close")
    await connect(kernel, "user_1", "Sam")
    for text, emotion, intensity in lines:
        mika.tag = (emotion, intensity)
        await (await kernel.perceive(said("user_1", text))).reply
        await asyncio.sleep(2 * MINUTE / US)


def thought_texts(kernel) -> list[str]:
    born = of(kernel, attention_c.THOUGHT_BORN)
    texts = kernel.mind.store.content([b.data.text.ref for b in born])
    return [texts[b.data.text.ref] for b in born if b.data.origin == attention_c.EXCHANGE]


def test_a_thought_born_of_laisse_tomber_carries_what_the_exchange_meant(tmp_path):
    async def scenario(kernel, mika):
        await sam_evening(kernel, mika)
        await asyncio.sleep(15 * MINUTE / US)  # l'échange se pose
        return thought_texts(kernel)

    texts, _ = live(tmp_path, scenario)
    assert len(texts) == 1
    assert texts[0].startswith("Sam répondait à peine : ")  # ce que l'échange voulait dire…
    assert all(f"« {t} »" in texts[0] for t, _e, _i in SAM_EVENING)  # …avec ses mots, pas une réplique isolée
    assert texts[0] != "Sam m'a dit : « laisse tomber »"


def test_a_thought_born_in_a_room_never_quotes_their_private_words(tmp_path):
    """Une pensée née dans un salon est anodine : elle porte l'échange du salon, jamais ce que la même personne lui a
    écrit en privé juste avant."""
    async def scenario(kernel, mika):
        await befriend(kernel, "ext_1", "close")
        tg = {"channel": "external", "display_name": "Sam"}
        await (await kernel.perceive(said("ext_1", "CANARI-PRIVE mon chat est malade, je te le dis à toi", **tg))).reply
        await asyncio.sleep(5 * MINUTE / US)
        for text, emotion, intensity in SAM_EVENING[:4]:
            mika.tag = (emotion, intensity)
            p = await kernel.perceive(said("ext_1", text, room="ext_chat_-7", **tg))
            if p.reply is not None:
                await p.reply
            await asyncio.sleep(2 * MINUTE / US)
        await asyncio.sleep(15 * MINUTE / US)
        return thought_texts(kernel)

    texts, _ = live(tmp_path, scenario)
    assert texts and "laisse tomber" in texts[0]
    assert all("CANARI-PRIVE" not in t for t in texts)


def test_a_full_exchange_keeps_its_most_marking_moment(tmp_path):
    """Contre-exemple : un échange nourri n'est pas « répondre à peine » — la pensée cite ce qui a le plus marqué,
    et ce qui a été dit autour."""
    lines = [("salut Mika", "happy", 0.5),
             ("Pixel a rien mangé ce matin, il est tout mou… je l'emmène chez le véto ce midi", "anxious", 0.7),
             ("samedi c'est mon anniv, 30 ans, ça me déprime un peu", "hopeful", 0.5),
             ("allez j'y vais", "happy", 0.5)]

    async def scenario(kernel, mika):
        await sam_evening(kernel, mika, lines)
        await asyncio.sleep(15 * MINUTE / US)
        return thought_texts(kernel)

    texts, _ = live(tmp_path, scenario)
    assert len(texts) == 1 and texts[0].startswith("Sam m'a dit : « Pixel a rien mangé ce matin")
    assert "répondait à peine" not in texts[0] and "« samedi c'est mon anniv" in texts[0]


def test_her_reflection_sees_the_exchange_and_what_the_person_is_living_in_one_session(tmp_path):
    """Elle repense à Sam l'échange sous les yeux, avec ce qu'elle sait de ce qu'il vit (son chat, son
    anniversaire) — en une séance : elle écrit ce qu'elle en pense, c'est tout. Rien de ce qu'elle sait de la vie
    d'une autre personne n'y entre."""
    async def scenario(kernel, mika):
        now = kernel.mind.clock.now()
        await kernel.mind.append([
            memory_c.EVENT_NOTED.draft(text=Content.of("son chat Pixel est mort mardi", level=2), when=now - 3 * DAY,
                                       about=("user_1",), sensitivity=2, told_by=("user_1",), ongoing=False),
            memory_c.EVENT_NOTED.draft(text=Content.of("son anniversaire de 30 ans", level=1), when=now + DAY,
                                       about=("user_1",), sensitivity=1, told_by=("user_1",)),
            memory_c.BELIEVED.draft(text=Content.of("Pixel, le chat de Sam, avait 16 ans", level=1),
                                    about=("user_1",), sensitivity=1, told_by=("user_1",)),
            memory_c.EVENT_NOTED.draft(text=Content.of("CANARI-TIERS l'entretien de Bea", level=2), when=now,
                                       about=("user_2",), sensitivity=2, told_by=("user_2",))],
            emitter="memory", correlation="genese", origin=Origin.GENESIS)
        await sam_evening(kernel, mika)
        await asyncio.sleep(3 * HOUR / US)
        return of(kernel, goals_c.GOAL_OPENED), of(kernel, goals_c.GOAL_CLOSED), of(kernel, rt.EPISODE_STARTED)

    (opened, closed, started), llm = live(tmp_path, scenario)
    [goal] = [o for o in opened if o.data.origin == goals_c.FROM_EXCHANGE]
    assert goal.data.max_steps == 1 and "projects" not in goal.data.bundles
    sessions = [s for s in started if s.data.kind == "STEP" and s.data.target == f"goal:{goal.seq}"]
    assert len(sessions) == 1, "une réflexion tient en une séance"
    assert [(c.data.status, c.data.goal) for c in closed] == [(goals_c.ACHIEVED, goal.seq)]
    step = next(c for c in llm.calls if c.role == "step")
    exchange = _section(step, "L'ÉCHANGE D'OÙ ÇA VIENT")
    assert "Sam : laisse tomber" in exchange and "Sam : bof" in exchange and "toi : je vois" in exchange
    life = _section(step, "CE QUI SE PASSE DANS SA VIE")
    assert "son chat Pixel est mort mardi" in life and "son anniversaire de 30 ans" in life
    assert "avait 16 ans" in life and "CANARI-TIERS" not in life
    work = _section(step, "CE À QUOI TU TRAVAILLES")
    assert "N'invente rien" in work and "en une séance" in work


def test_one_session_even_when_she_says_she_will_come_back(tmp_path):
    """Elle écrit sa réflexion puis dit « je reprendrai » (sonde réelle : « continue » trois fois, puis l'enquête) :
    il n'y aura pas d'autre séance, ce qu'elle a écrit la clôt."""
    async def scenario(kernel, mika):
        await sam_evening(kernel, mika)
        await asyncio.sleep(3 * HOUR / US)
        return of(kernel, goals_c.GOAL_CLOSED), of(kernel, goals_c.STEP_REPORTED)

    (closed, reports), _ = live(tmp_path, scenario, Mika(verdict="continue"))
    assert [r.data.verdict for r in reports] == [goals_c.DONE] and reports[0].data.proven
    assert [c.data.status for c in closed] == [goals_c.ACHIEVED]


def test_a_reflection_never_ends_in_je_bloque(tmp_path):
    """Repenser à ce qu'un ami a confié ne se rate pas : même quand le modèle dit qu'il « bloque », elle en reste
    là — ni « Je bloque sur : Repenser à ce que Sam m'a confié », ni frustration (sonde réelle du 2026-10-02)."""
    async def scenario(kernel, mika):
        await sam_evening(kernel, mika)
        await asyncio.sleep(3 * HOUR / US)
        return of(kernel, goals_c.GOAL_CLOSED), kernel.mind.frame().get(attention_c.THOUGHTS)

    (closed, thoughts), _ = live(tmp_path, scenario, Mika(verdict="blocked"))
    assert [(c.data.status, c.data.reason) for c in closed] == [(goals_c.ABANDONED, goals_c.LET_GO)]
    assert not [t for t in thoughts if t.origin == attention_c.BLOCKED]


def test_an_exploration_that_reads_its_feeds_goes_on_after_continue(tmp_path):
    """Contre-exemple : une exploration née de ce qu'elle a remarqué dans ses flux a plusieurs séances — « je
    reprendrai » la laisse ouverte."""
    async def scenario(kernel, mika):
        await kernel.mind.append([goals_c.GOAL_OPENED.draft(
            kind=goals_c.EXPLORATION, authority=goals_c.SELF,
            title=Content.of("En savoir plus sur ce que j'ai remarqué dans mes flux", level=0),
            details=Content.of("Un article sur les marées", level=0), bundles=("goals", "memory", "rss"),
            max_steps=3, source="thought:42", sensitivity=0, desire=1.0, origin=goals_c.FROM_SIGNAL)],
            emitter="goals", correlation="genese", origin=Origin.GENESIS)
        await asyncio.sleep(20 * MINUTE / US)
        return of(kernel, goals_c.GOAL_CLOSED), of(kernel, goals_c.STEP_REPORTED)

    (closed, reports), _ = live(tmp_path, scenario, Mika(verdict="continue"))
    assert reports and reports[0].data.verdict == goals_c.CONTINUE and not closed


def test_what_she_writes_while_thinking_it_over_feeds_no_memory_about_him(tmp_path):
    """Ce qu'elle écrit en y repensant est à elle : ni souvenir, ni croyance, ni moment de sa vie à lui."""
    async def scenario(kernel, mika):
        await sam_evening(kernel, mika)
        await asyncio.sleep(DAY / US)
        rows = kernel.mind.store.query_mind(f"SELECT kind, text FROM {memory_c.ITEMS_TABLE}")
        return rows, of(kernel, goals_c.GOAL_CLOSED)

    (rows, closed), _ = live(tmp_path, scenario)
    assert closed and closed[0].data.status == goals_c.ACHIEVED  # elle a bien écrit sa réflexion
    assert not [r for r in rows if "CANARI-REFLEXION" in r[1]]
