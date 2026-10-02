"""La vie des autres, et sa parole (ADR 0046), par ses intentions.

- « je te demanderai jeudi soir comment ça s'est passé » : jeudi soir, elle le
  demande — elle ne s'excuse pas de ne pas l'avoir fait ; une promesse sans
  date ne déclenche rien (HUM-2) ;
- un moment de sa vie n'est « repris » que si l'une ou l'autre en reparle en
  mots : l'avoir eu sous les yeux sans en parler ne l'éteint pas ; le raconter
  elle-même, si (HUM-1) ;
- la veille, un mot pour l'encourager — pas si elles se sont déjà parlé ce
  soir-là ; après, « alors ? » — pas si elle a écrit depuis : la conversation
  était l'occasion (HUM-1) ;
- « Moustache est malade » le lundi, « salut » le samedi : Moustache lui
  revient ; jamais dans un salon (HUM-7) ;
- « j'ai eu le poste !! » : le lendemain, l'envie (faible) de lui en reparler ;
  un échange anodin, non (HUM-20) ;
- elle a répondu fâchée à une amie : « j'ai été dure avec elle » lui reste ;
  envers une inconnue qui l'insulte, non (HUM-14, son côté à elle).
"""

from __future__ import annotations

import asyncio

import pytest

from mika.contracts import attention as attention_c
from mika.contracts import memory as memory_c
from mika.contracts import others as others_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.memory.life import takes_up
from mika.faculties.needs import NeedsParams
from mika.kernel.clock import HOUR, MINUTE, US
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMResponse, ToolCall
from mika.sim.clock import run_virtual
from tests.fixtures.memory import section
from tests.fixtures.mika import at_paris, befriend, boot, build, connect, said

LIFE = "CE QUI SE PASSE DANS SA VIE"
PROMISED = "CE QUE TU LUI AS PROMIS"


class Script:
    """Un modèle scripté : il répond (``reply(message) -> texte | None``), consolide selon ``extract``, écrit
    d'elle-même ce qu'on lui dit d'écrire."""

    def __init__(self, reply=None, extract=None, initiative="Coucou ! [EMOTION:happy:0.5]"):
        self.reply = reply
        self.extract = extract
        self.initiative = initiative
        self.calls = []

    def __call__(self, req):
        self.calls.append(req)
        if req.role == "extract":
            args = (self.extract(req.messages[-1].content) if self.extract else None) or {}
            return LLMResponse("", tool_calls=(ToolCall("x", "record_memories", args),), stop="tool_use")
        if req.role in ("profile", "compact"):
            return LLMResponse("{}")
        if req.role == "murmur":
            return LLMResponse("tiens, et si je lui écrivais")
        if req.role in ("narrative", "journal", "dream"):
            return LLMResponse("Une journée.")
        if req.role == "initiative":
            return LLMResponse(self.initiative)
        message = req.messages[-1].content.rsplit("--- FIN ETAT INTERNE ---", 1)[-1].strip()
        text = self.reply(message) if self.reply else None
        return LLMResponse(text or "d'accord [EMOTION:happy:0.4]")

    def prompts(self, role, target):
        return [r.system_stable + "\n".join(m.content for m in r.messages) for r in self.calls
                if r.role == role and r.meta.get("target") == target]


def run(tmp_path, scenario, script, *, start):
    kernel, clock, _llm, _out = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        # pas d'autre envie de parler : on mesure ce qui la pousse vers la personne, rien d'autre
        await kernel.set_params("needs", NeedsParams(social_floor=1.0, expression_floor=1.0))
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def events(kernel, name):
    mind = kernel.mind
    return [mind.decode(e) for e in mind.store.read() if e.type == name]


def started(kernel, reason):
    return [e for e in events(kernel, rt.EPISODE_STARTED.name)
            if e.data.kind == "INITIATIVE" and reason in e.data.reason.split(",")]


async def chat(kernel, handle, texts, gap=60, **kw):
    for text in texts:
        p = await kernel.perceive(said(handle, text, **kw))
        if p.reply is not None:
            await p.reply
        await asyncio.sleep(gap)


async def until(kernel, t):
    now = kernel.mind.clock.now()
    if t > now:
        await asyncio.sleep((t - now) / US)


async def note(kernel, text, when, person="user_1", *, all_day=False, ongoing=False):
    commit = await kernel.mind.append([memory_c.EVENT_NOTED.draft(
        text=Content.of(text, level=2), when=when, about=(person,), all_day=all_day, sensitivity=2,
        told_by=(person,), heard_by=(person,), ongoing=ongoing)],
        emitter="memory", correlation=f"genese:{text}", origin=Origin.GENESIS)
    return commit.seqs[-1]


# ── Tenir parole (HUM-2) ──────────────────────────────────────────────────


@pytest.fixture
def kept_world(tmp_path):
    """Lundi, elle a promis à Adrien de lui demander jeudi à 20 h comment s'est passé son entretien, et de lui
    envoyer « un jour » la recette des crêpes (sans date). On laisse passer la semaine jusqu'à jeudi soir."""
    script = Script()
    box = {"script": script}

    async def scenario(kernel):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Adrien")
        await chat(kernel, "user_1", ["salut ! jeudi j'ai mon entretien", "bonne soirée !"])
        due = at_paris(2026, 10, 1, 20, 0)
        dated = (await kernel.mind.append([memory_c.PROMISE_NOTICED.draft(
            text=Content.of("lui demander comment s'est passé son entretien", level=2), to="user_1", due=due)],
            emitter="memory", correlation="promesse", origin=Origin.GENESIS)).seqs[-1]
        vague = (await kernel.mind.append([memory_c.PROMISE_NOTICED.draft(
            text=Content.of("lui envoyer la recette des crêpes", level=2), to="user_1", implicit_due=True)],
            emitter="memory", correlation="vague", origin=Origin.GENESIS)).seqs[-1]
        await until(kernel, at_paris(2026, 10, 1, 23, 30))
        box.update(dated=dated, vague=vague, due=due,
                   keep=started(kernel, memory_c.KEEP_PROMISE),
                   resolved=events(kernel, memory_c.PROMISE_RESOLVED.name),
                   missed=[e for e in events(kernel, attention_c.EXPECTATION_MISSED.name)
                           if e.data.kind == attention_c.PROMISE],
                   thoughts=[e for e in events(kernel, attention_c.THOUGHT_BORN.name)
                             if e.data.origin == attention_c.PROMISE])
        return box

    return run(tmp_path, scenario, script, start=at_paris(2026, 9, 28, 18, 0))


def test_the_promise_is_kept_on_time_by_her_word(kept_world):
    """Jeudi, un peu avant 20 h, elle le lui demande d'elle-même : la promesse est tenue — ni pensée « j'avais
    promis… », ni rien à se reprocher. Contre-exemple : une promesse sans date ne déclenche rien."""
    w = kept_world
    keep = w["keep"]
    assert len(keep) == 1 and keep[0].data.subject == f"promise:{w['dated']}", keep
    assert w["due"] - 30 * MINUTE <= keep[0].at <= w["due"] + 2 * HOUR, "au moment dit, pas à l'avance ni en retard"
    honored = [e for e in w["resolved"] if e.data.promise == w["dated"]]
    assert honored and honored[0].data.status == memory_c.HONORED and honored[0].data.by == memory_c.KEPT_BY
    assert w["missed"] == [] and w["thoughts"] == [], "tenue : ni « j'avais promis… », ni rien à se reprocher"
    # contre-exemple : sans date, rien ne la pousse — la promesse reste dans « ce que tu lui as promis »
    assert not [e for e in keep if e.data.subject == f"promise:{w['vague']}"]
    assert not [e for e in w["resolved"] if e.data.promise == w["vague"]]


def test_keeping_a_promise_shows_her_what_she_promised(kept_world):
    """Elle ne l'invente pas : la promesse est sous ses yeux, citée, avec « c'est le moment de le faire »."""
    prompts = kept_world["script"].prompts("initiative", "user_1")
    kept = [p for p in prompts if "c'est le moment de le faire" in p]
    assert kept, prompts
    promised = section(kept[0], PROMISED)
    assert "lui demander comment s'est passé son entretien" in promised and "c'est le moment" in promised
    assert "recette des crêpes" in promised and promised.count("c'est le moment") == 1  # la vague n'est pas due


# ── Un moment repris en mots (HUM-1) ──────────────────────────────────────


def test_taking_up_a_moment_is_a_matter_of_words_not_names():
    assert takes_up("son entretien chez Ubisoft", "Alors, cet entretien, ça s'est passé comment ?")
    assert takes_up("son entretien chez Ubisoft", "l'entretien s'est super bien passé !")
    assert not takes_up("son entretien chez Ubisoft", "coucou Alice ! ça va ?", names=("Alice",))
    assert not takes_up("l'anniversaire d'Alice", "Alice, tu viens ce soir ?", names=("Alice",))  # un prénom n'est
    # pas le moment


@pytest.mark.parametrize("told_herself", [False, True])
def test_a_moment_shown_but_not_spoken_of_is_still_to_be_asked_about(tmp_path, told_herself):
    """Jeudi 14 h, l'entretien d'Adrien. Il écrit jeudi à 15 h « coucou » ; elle lui répond sans en parler : le
    moment n'est pas « suivi » pour autant (audit HUM-1 : l'avoir sous les yeux l'éteignait) — samedi, à son
    « salut ! », il est encore là, et envers un ami c'est la première chose qu'on demande. Contre-exemple : s'il
    le lui raconte lui-même (« l'entretien s'est super bien passé »), samedi il n'y est plus. Et dans les deux
    cas, il lui a écrit après l'entretien : pas d'initiative « alors ? » — la conversation était l'occasion."""
    script = Script()

    async def scenario(kernel):
        await befriend(kernel, "tg_1", social_c.FRIEND)
        await chat(kernel, "tg_1", ["salut !", "bonne soirée !"], channel="telegram")
        moment = await note(kernel, "son entretien chez Ubisoft", at_paris(2026, 10, 1, 14, 0), "tg_1")
        await until(kernel, at_paris(2026, 10, 1, 15, 0))
        await chat(kernel, "tg_1", ["l'entretien s'est super bien passé !" if told_herself else "coucou",
                                    "bon, à plus !"], channel="telegram")
        await until(kernel, at_paris(2026, 10, 3, 11, 0))
        await chat(kernel, "tg_1", ["salut !"], channel="telegram")
        followed = [e for e in events(kernel, memory_c.MOMENT_FOLLOWED.name) if e.data.event == moment]
        return followed, started(kernel, others_c.FOLLOW_UP)

    followed, follow_ups = run(tmp_path, scenario, script, start=at_paris(2026, 9, 28, 18, 0))
    saturday = section(script.prompts("reply", "tg_1")[-1], LIFE)
    if told_herself:
        assert followed and followed[0].data.by == "tg_1"
        assert "Ubisoft" not in saturday, "il le lui a raconté : elle ne le redemande pas"
    else:
        assert not followed
        assert "Ubisoft" in saturday and "la première chose qu'une amie lui demanderait" in saturday
    # il a écrit après l'entretien : la conversation était l'occasion, pas une initiative de plus
    assert follow_ups == []


@pytest.mark.parametrize("talked_that_evening", [False, True])
def test_the_eve_of_a_big_moment_she_cheers_her_friend_once(tmp_path, talked_that_evening):
    """Lundi, Adrien lui dit que jeudi à 14 h il a son entretien. Mercredi soir, un petit mot pour l'encourager —
    une fois. Contre-exemple : s'ils se sont déjà parlé mercredi après-midi, la conversation en était
    l'occasion."""
    script = Script(initiative="Bonne chance pour demain, tu vas assurer ! [EMOTION:happy:0.6]")

    async def scenario(kernel):
        await befriend(kernel, "tg_1", social_c.FRIEND)
        await chat(kernel, "tg_1", ["salut !", "bonne soirée !"], channel="telegram")
        await note(kernel, "son entretien chez Ubisoft", at_paris(2026, 10, 1, 14, 0), "tg_1")
        await until(kernel, at_paris(2026, 9, 30, 13, 0))
        if talked_that_evening:
            await chat(kernel, "tg_1", ["je stresse pour demain", "bon, à plus !"], channel="telegram")
        await until(kernel, at_paris(2026, 10, 1, 13, 0))
        return started(kernel, others_c.CHEER)

    cheers = run(tmp_path, scenario, script, start=at_paris(2026, 9, 28, 18, 0))
    if talked_that_evening:
        assert cheers == []
    else:
        assert len(cheers) == 1, cheers
        assert cheers[0].data.subject.startswith("moment:")
        assert at_paris(2026, 9, 30, 18, 0) <= cheers[0].at <= at_paris(2026, 9, 30, 22, 0), "la veille au soir"
        prompt = script.prompts("initiative", "tg_1")[-1]
        assert "encourager" in prompt and "Ubisoft" in section(prompt, LIFE)


# ── Ce qui dure dans sa vie (HUM-7) ───────────────────────────────────────


@pytest.mark.parametrize("room", [None, "salon"])
def test_a_situation_in_her_life_comes_back_at_the_first_hello_but_never_in_a_room(tmp_path, room):
    """Lundi : « mon chat Moustache est malade depuis dimanche ». Samedi, au premier « salut ! » : Moustache et son
    état lui reviennent (« en ce moment »), et ce qu'Alice lui en avait dit. Contre-exemple : dans un salon, sa
    fiche est fermée — rien."""

    def extract(prompt):
        if "Moustache" not in prompt:
            return None
        return {"croyances": [{"texte": "Le chat d'Alice, Moustache, est malade depuis le 27 septembre",
                               "personnes": ["[P1]"], "sensibilite": "personnel", "importance": 3,
                               "messages": [int(line.split("]")[0][2:]) for line in prompt.splitlines()
                                            if "Moustache" in line and line.startswith("[#")]}],
                "evenements": [{"texte": "Moustache, son chat, est malade", "personnes": ["[P1]"],
                                "quand": "2026-09-27", "en_cours": True, "sensibilite": "personnel"}]}

    script = Script(extract=extract)

    async def scenario(kernel):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Alice")
        await chat(kernel, "user_1", ["et mon chat Moustache est malade depuis dimanche", "un", "deux", "trois",
                                      "quatre", "bonne soirée !"])
        await asyncio.sleep(10 * MINUTE / US)
        await until(kernel, at_paris(2026, 10, 3, 11, 0))
        kw = {"room": room, "public": True} if room else {}
        await chat(kernel, "user_1", ["salut !"], **kw)
        return None

    run(tmp_path, scenario, script, start=at_paris(2026, 9, 28, 18, 0))
    prompt = script.prompts("reply", "user_1")[-1]
    if room:
        assert "Moustache" not in prompt
    else:
        assert "Moustache" in section(prompt, LIFE) and "en ce moment" in section(prompt, LIFE)
        assert "Moustache" in section(prompt, "CE QUI TE REVIENT")


# ── Un bel échange, le lendemain (HUM-20) ─────────────────────────────────


@pytest.mark.parametrize("glad", [True, False])
def test_good_news_from_a_friend_can_be_spoken_of_again_the_next_day(tmp_path, glad):
    """Alice : « j'ai eu le poste !! » — elle s'en réjouit. Le lendemain, sans autre nouvelle d'Alice, l'envie de
    lui en reparler (« encore bravo ! ») peut venir. Contre-exemple : un échange anodin, rien."""
    tag = "[EMOTION:excited:0.9]" if glad else "[EMOTION:curious:0.4]"
    script = Script(reply=lambda m: f"Waouh, bravo !! {tag}" if "poste" in m or "salade" in m else None)

    async def scenario(kernel):
        await befriend(kernel, "tg_1", social_c.FRIEND)
        await chat(kernel, "tg_1", ["j'ai eu le poste !!" if glad else "j'ai mangé une salade", "bonne soirée !"],
                   channel="telegram")
        await asyncio.sleep(40 * HOUR / US)
        return [e for e in started(kernel, attention_c.THOUGHT) if e.data.target == "tg_1"]

    fired = run(tmp_path, scenario, script, start=at_paris(2026, 9, 28, 18, 0))
    if glad:
        assert fired, "le lendemain, l'envie de lui en reparler"
        assert 12 * HOUR <= fired[0].at - at_paris(2026, 9, 28, 18, 0) <= 40 * HOUR
        prompt = script.prompts("initiative", "tg_1")[0]
        assert "Tu repenses avec plaisir" in prompt
    else:
        assert fired == []


# ── Avoir été dure avec une amie (HUM-14, son côté) ───────────────────────


@pytest.mark.parametrize("friend", [True, False])
def test_after_snapping_at_a_friend_she_feels_she_was_harsh(tmp_path, friend):
    """Une amie la provoque, elle lui répond fâchée : « J'ai été dure avec Alice » lui reste en tête — de quoi
    revenir vers elle. Contre-exemple : une inconnue qui l'insulte n'appelle pas d'excuses."""
    script = Script(reply=lambda m: "Franchement, là tu exagères. [EMOTION:angry:0.8]" if "nulle" in m else None)

    async def scenario(kernel):
        if friend:
            await befriend(kernel, "tg_1", social_c.FRIEND)
        await chat(kernel, "tg_1", ["t'es vraiment nulle aujourd'hui"], channel="telegram", display_name="Alice")
        await asyncio.sleep(HOUR / US)
        born = [e for e in events(kernel, attention_c.THOUGHT_BORN.name) if e.data.origin == attention_c.REMORSE]
        return born, kernel.mind.store.content([e.data.text.ref for e in born])

    remorse, texts = run(tmp_path, scenario, script, start=at_paris(2026, 9, 28, 18, 0))
    if friend:
        assert len(remorse) == 1 and remorse[0].data.about == ("tg_1",)
        assert texts[remorse[0].data.text.ref] == "J'ai été dure avec Alice."
    else:
        assert remorse == []
