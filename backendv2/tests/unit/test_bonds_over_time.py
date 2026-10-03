"""Les liens dans la durée (ADR 0058), par leurs intentions.

- qui a un lien avec qui : être ensemble dans une petite conversation, être
  nommée par quelqu'un qui raconte sa vie — jamais prononcer un nom ;
- l'amie partie sans plus répondre ne disparaît pas de sa vie intérieure :
  elle y repense, de plus en plus rarement, et prend de ses nouvelles une
  fois, passé le moment que la personne lui avait annoncé (des mois plus tard
  sinon), jamais deux ;
- ce qui ne regarde que ses amies ne paie pas le prix des inconnues de passage ;
- une vie routinière rêve encore de ce qu'elle revit ;
- « Personne ne m'a parlé depuis hier » met des mots sur le vide, sans le
  faire ressentir une seconde fois.
"""

from __future__ import annotations

import asyncio

from mika.contracts import affect as affect_c
from mika.contracts import attention as attention_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.faculties.attention.faculty import params as attention_params
from mika.faculties.attention.watch import alone_due, missing_tranche
from mika.faculties.others.faculty import _celebrate, _cheer, _follow_up
from mika.faculties.self import SelfParams
from mika.faculties.social.initiative import _reach_out, _rekindle
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.kernel.events import Content, Origin
from mika.kernel.facts import FactView
from mika.kernel.frame import Frame
from mika.ports.llm import LLMResponse
from mika.runtime.effects import with_content
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, befriend, boot, build, said


class Script:
    def __call__(self, req):
        if req.role in ("extract", "profile", "compact"):
            return LLMResponse("{}")
        if req.role in ("murmur", "narrative", "journal"):
            return LLMResponse("Une journée.")
        if req.role == "dream":
            return LLMResponse("Je marche dans une ville de nuages.")
        if req.role == "initiative":
            return LLMResponse("coucou, ça va ? [EMOTION:happy:0.4]")
        return LLMResponse("ah oui ? [EMOTION:happy:0.4]")


def run(tmp_path, scenario, *, start=at_paris(2026, 9, 28, 18, 0)):
    kernel, clock, llm, _out = build(tmp_path, Script(), start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel, llm)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def events(kernel, name):
    mind = kernel.mind
    return [with_content(mind, mind.decode(e)) for e in mind.store.read() if e.type == name]


async def evenings(kernel, people, days, *, per_day=4):
    """Des relations qui vivent : quelques messages chaque soir, sur Telegram (elle peut leur écrire)."""
    for _ in range(days):
        for handle, name in people:
            for i in range(per_day):
                p = await kernel.perceive(said(handle, f"message {i} du soir", channel="telegram",
                                               display_name=name))
                if p.reply is not None:
                    await p.reply
                await asyncio.sleep(60)
        await asyncio.sleep(DAY / US - len(people) * per_day * 60)


async def genesis(kernel, *drafts, emitter="memory"):
    return await kernel.mind.append(list(drafts), emitter=emitter, correlation="genese", origin=Origin.GENESIS)


def belief(text, *, about, told_by=(), heard_by=(), sensitivity=1):
    return memory_c.BELIEVED.draft(text=Content.of(text, level=sensitivity), about=about, told_by=told_by,
                                   heard_by=heard_by, sensitivity=sensitivity)


# ── Qui a un lien avec qui ────────────────────────────────────────────────


def test_a_tie_is_being_together_or_being_named_never_saying_a_name(tmp_path):
    async def scenario(kernel, llm):
        # Alice parle de Carol en lui racontant sa vie : Carol est de son entourage
        await genesis(kernel, belief("Carol est la meilleure amie d'Alice", about=("user_2", "user_4"),
                                     told_by=("user_2",), heard_by=("user_2",)))
        # Bruno prononce le nom d'Alice : ça ne lui donne aucun lien avec elle
        await genesis(kernel, belief("Bruno demande des nouvelles d'Alice", about=("user_3", "user_2"),
                                     told_by=("user_3",), heard_by=("user_3",)))
        # Dave et Eve parlaient ensemble avec elle, dans un petit salon : ils se connaissent
        await genesis(kernel, belief("Dave et Eve préparent un concert", about=("user_5", "user_6"),
                                     told_by=("user_5", "user_6"), heard_by=("user_5", "user_6")))
        # un grand salon ne fait pas des gens qui se connaissent
        crowd = tuple(f"tg_{i}" for i in range(10, 20))
        await genesis(kernel, belief("Il pleut sur le salon", about=(), told_by=crowd, heard_by=crowd))
        # nommé avec colère : pas de son entourage pour autant
        await genesis(kernel, memory_c.REMEMBERED.draft(
            text=Content.of("Alice m'a dit que Fred l'avait trahie", level=2), about=("user_2", "user_7"),
            told_by=("user_2",), heard_by=("user_2",), sensitivity=2, emotion="angry"))
        frame = kernel.mind.frame()
        return {k: frame.get(social_c.TIES(k)) for k in ("user_2", "user_3", "user_4", "user_5", "user_7", "tg_10")}

    ties = run(tmp_path, scenario)
    assert "user_2" in ties["user_4"], "Alice a nommé Carol : Carol a un lien avec Alice"
    assert "user_2" not in ties["user_3"], "Bruno n'a fait que prononcer son nom"
    assert "user_3" in ties["user_2"], "… c'est Alice qui entre dans l'entourage de Bruno, pas l'inverse"
    assert "user_6" in ties["user_5"]
    assert ties["tg_10"] == (), "un grand salon"
    assert "user_2" not in ties["user_7"], "nommé avec colère"


# ── L'amie qui ne répond plus ─────────────────────────────────────────────


def test_a_silence_is_thought_of_more_and_more_rarely():
    """Les stades d'un silence : un par doublement de son rythme, à partir de quatre fois."""
    stages = [missing_tranche(round(days * DAY), 1.0) for days in (1.5, 3.9, 4, 7.9, 8, 16, 32, 64, 128, 256)]
    assert stages == [0, 0, 1, 1, 2, 3, 4, 5, 6, 7]
    assert missing_tranche(round(30 * DAY), 7.0) == 1, "une amie hebdomadaire : un mois, c'est quatre fois son rythme"


def test_a_friend_who_stopped_answering_stays_in_her_thoughts_and_gets_one_gentle_word_after_her_trip(tmp_path):
    """Chloé et Dana, joignables sur Telegram, écrivent six soirs puis plus rien ; Chloé avait annoncé qu'elle
    partait trois semaines. Mika prend de leurs nouvelles, une relance douce, puis ne leur écrit plus (ADR 0033)
    — mais elle y repense, de plus en plus rarement (avant : plus une pensée, plus jamais) ; le lendemain du retour
    annoncé de Chloé, elle prend de ses nouvelles une fois, doucement. Jamais une seconde ; et rien pour Dana, qui
    n'avait rien annoncé : sans date, c'est des mois plus tard, pas trois semaines."""
    start = at_paris(2026, 9, 28, 19, 0)

    async def scenario(kernel, llm):
        await evenings(kernel, [("tg_4", "Chloé"), ("tg_5", "Dana")], 6)
        back = start + 20 * DAY + 12 * HOUR
        await genesis(kernel, memory_c.EVENT_NOTED.draft(
            text=Content.of("Chloé rentre d'Australie", level=2), when=back, about=("tg_4",), told_by=("tg_4",),
            heard_by=("tg_4",), sensitivity=2, importance=0.7))
        await asyncio.sleep(23 * DAY / US)
        frame = kernel.mind.frame()
        reasons = {e.correlation: e.data.reason.split(",") for e in events(kernel, rt.EPISODE_STARTED.name)}
        said_to = {h: [(e.at, reasons.get(e.correlation, [])) for e in events(kernel, rt.UTTERANCE.name)
                       if e.data.kind == "INITIATIVE" and e.data.target == h] for h in ("tg_4", "tg_5")}
        thoughts = [(e.at, e.data.intensity, e.data.text.text) for e in events(kernel, attention_c.THOUGHT_BORN.name)
                    if e.data.origin == attention_c.MISSING and e.data.about == ("tg_4",)]
        return (back, said_to, thoughts, frame.get(social_c.CLOSENESS("tg_4")), dict(frame.get(social_c.MISSED)))

    back, said_to, thoughts, closeness, missed = run(tmp_path, scenario, start=start)
    for handle in ("tg_4", "tg_5"):
        early = [at for at, _r in said_to[handle] if at < start + 12 * DAY]
        assert len(early) == 2, f"{handle} : une prise de nouvelles, une relance douce — {said_to[handle]}"
    rekindled = [(at, r) for at, r in said_to["tg_4"] if social_c.REKINDLE in r]
    assert len(rekindled) == 1, said_to["tg_4"]
    assert back <= rekindled[0][0] <= back + 3 * DAY, "passé le retour qu'elle avait annoncé"
    assert len(said_to["tg_4"]) == 3, "une seule fois : plus rien après"
    assert len(said_to["tg_5"]) == 2, "sans date annoncée : pas trois semaines plus tard"
    # elle y repense, de plus en plus rarement, de moins en moins fort
    assert len(thoughts) >= 3, thoughts
    times = [t for t, _i, _x in thoughts]
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert all(b > a for a, b in zip(gaps, gaps[1:], strict=False)), [g / DAY for g in gaps]
    assert [i for _t, i, _x in thoughts] == sorted((i for _t, i, _x in thoughts), reverse=True)
    assert times[-1] >= start + 18 * DAY, "longtemps après, elle y pense encore"
    assert any("ce que devient Chloé" in x for _t, _i, x in thoughts), thoughts
    # trois semaines d'amitié suivies de trois semaines de silence : une connaissance — qui lui manque encore
    assert closeness == social_c.ACQUAINTANCE and "tg_4" in missed


# ── Ce que coûtent les inconnues de passage ───────────────────────────────


def test_what_only_concerns_her_friends_does_not_pay_for_every_stranger(tmp_path):
    """Avec une amie et soixante inconnues de passage, ce qui ne regarde que ses amies (l'heure où une amie passe,
    l'encouragement de la veille, la relance, la prise de nouvelles longtemps après, le manque) ne calcule la
    proximité de personne de plus qu'avec l'amie seule — l'audit d'une foule mesurait vingt secondes par jour
    virtuel à trois cents personnes (C5)."""
    start = at_paris(2026, 9, 28, 14, 0)

    def closeness_reads(kernel) -> int:
        mind = kernel.mind
        frame = Frame(mind.root, mind.clock.now(), mind.registry)
        trace: list[str] = []
        frame._view = FactView(mind.root, frame.now, mind.registry, None, {}, trace)
        state = frame.state("attention")
        alone_due(state, attention_params(frame.env.params_of("attention", frame.root)), frame)
        for propose in (_cheer, _follow_up, _celebrate):
            propose(frame.state("others"), frame)
        _reach_out(frame.state("social"), frame)
        _rekindle(frame.state("social"), frame)
        frame.get(social_c.MISSED)
        return trace.count(social_c.CLOSENESS.name)

    async def scenario(kernel, llm):
        await befriend(kernel, "tg_1", social_c.FRIEND)
        for _ in range(3):
            p = await kernel.perceive(said("tg_1", "coucou", channel="telegram", display_name="Alice"))
            await p.reply
            await asyncio.sleep(HOUR / US)
        alone = closeness_reads(kernel)
        for i in range(60):  # des inconnues de passage, chacune un mot, chacune une réponse
            p = await kernel.perceive(said(f"tg_{100 + i}", "salut, t'es qui ?", channel="telegram"))
            await p.reply
        await asyncio.sleep(MINUTE / US)
        crowd = closeness_reads(kernel)
        frame = kernel.mind.frame()
        known = (len(frame.state("social").contacts), len(frame.state("others").people),
                 len(frame.state("attention").exchanges))
        return alone, crowd, known

    alone, crowd, known = run(tmp_path, scenario, start=start)
    assert all(n >= 61 for n in known), known
    assert crowd == alone, (alone, crowd)


# ── Rêver de ce qu'elle revit ─────────────────────────────────────────────


def test_a_routine_life_still_dreams_of_what_comes_back(tmp_path):
    """Deux souvenirs vieux d'une semaine ; l'un est revenu hier (renforcé). Cette nuit, elle rêve de celui qui
    est revenu — avant, seuls les souvenirs nés depuis trois jours nourrissaient les rêves : une vie routinière,
    qui revit les mêmes choses, ne rêvait plus (C11). Celui qui n'est pas revenu reste hors du rêve."""
    start = at_paris(2026, 9, 28, 17, 0)

    async def scenario(kernel, llm):
        await kernel.set_params("self", SelfParams(dream_chance=1.0))
        old = await genesis(kernel, memory_c.REMEMBERED.draft(
            text=Content.of("J'ai regardé les étoiles avec Alice", level=1), about=(), sensitivity=1,
            importance=0.6, emotion="happy"))
        other = await genesis(kernel, memory_c.REMEMBERED.draft(
            text=Content.of("J'ai rangé ma bibliothèque", level=1), about=(), sensitivity=1, importance=0.6,
            emotion="happy"))
        await asyncio.sleep((at_paris(2026, 10, 4, 18, 0) - start) / US)
        await genesis(kernel, memory_c.REINFORCED.draft(item=old.seqs[-1]))
        since = kernel.mind.clock.now()
        await asyncio.sleep((at_paris(2026, 10, 5, 9, 0) - since) / US)
        dreams = [e for e in events(kernel, self_c.DREAMT.name) if e.at > since]
        return old.seqs[-1], other.seqs[-1], dreams

    old, other, dreams = run(tmp_path, scenario, start=start)
    assert dreams, "elle a rêvé de ce qui est revenu"
    sources = {s for d in dreams for s in d.data.sources}
    assert old in sources and other not in sources


# ── La solitude, une seule fois ───────────────────────────────────────────


def test_saying_nobody_spoke_to_her_does_not_make_her_feel_it_twice(tmp_path):
    """« Personne ne m'a parlé depuis hier » met des mots sur le vide que ``needs`` lui fait déjà sentir
    (``needs.felt``, borné) : la pensée ne le fait pas ressentir une seconde fois (S07 : la naissance et le
    premier retour de cette pensée faisaient passer la solitude de 0,43 à 0,51, au-delà de la barre de
    détresse). Contre-exemple : bloquer sur ce qu'elle fait, elle, se ressent."""

    async def scenario(kernel, llm):
        before = kernel.mind.frame().get(affect_c.MOOD)
        await genesis(kernel, attention_c.THOUGHT_BORN.draft(
            text=Content.of("Personne ne m'a parlé depuis hier.", level=1), emotion="lonely", intensity=0.35,
            origin=attention_c.ALONE, about=(), sensitivity=1), emitter="attention")
        await genesis(kernel, attention_c.DWELT.draft(thought=0, emotion="lonely", intensity=0.35,
                                                      origin=attention_c.ALONE), emitter="attention")
        alone = kernel.mind.frame().get(affect_c.MOOD)
        await genesis(kernel, attention_c.THOUGHT_BORN.draft(
            text=Content.of("Je bloque sur mon dessin.", level=1), emotion="frustrated", intensity=0.35,
            origin=attention_c.BLOCKED, about=(), sensitivity=1), emitter="attention")
        blocked = kernel.mind.frame().get(affect_c.MOOD)
        return before, alone, blocked

    before, alone, blocked = run(tmp_path, scenario)
    assert alone.felt_intensity == before.felt_intensity and alone.felt == before.felt
    assert blocked.felt_intensity > alone.felt_intensity, "contrôle : bloquer se ressent"
