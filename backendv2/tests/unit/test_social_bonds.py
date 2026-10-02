"""Les liens, par les cas de l'audit (ADR 0035).

- la réciprocité : quand c'est presque toujours elle qui écrit la première, elle
  le remarque (une pensée, un pincement), et ses relances s'espacent ; pas avec
  une amie qui écrit autant qu'elle ;
- les mots du profil de quelqu'un (ton, intérêts, sujets délicats)
  s'oublient avec la personne ;
- « QUI TU AS EN FACE » dit qui c'est sans réciter le mécanisme, sans « elle ou
  lui », sans se contredire ; et quand ils se sont parlé pour la dernière fois,
  en mots de calendrier.
"""

from __future__ import annotations

import asyncio

from mika.contracts import attention as attention_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.social.reciprocity import _one_sided
from mika.kernel.arbitration import RowView
from mika.kernel.clock import DAY, HOUR, US
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.ports.llm import LLMResponse, ToolCall
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, befriend, boot, build, connect, said


class Script:
    def __init__(self):
        self.profiles: list[str] = []

    def __call__(self, req):
        if req.role == "profile":
            self.profiles.append(req.messages[-1].content)
            return LLMResponse("", tool_calls=(ToolCall("p", "record_profile", {
                "resume": "C'est quelqu'un qui aime la montagne.", "ton": "doux", "interets": ["montagne"],
                "sujets_sensibles": ["sa santé"]}),), stop="tool_use")
        if req.role in ("extract", "compact", "narrative"):
            return LLMResponse("{}")
        return LLMResponse("d'accord [EMOTION:happy:0.4]")


def run(tmp_path, scenario, *, start=at_paris(2026, 9, 28, 12, 0)):
    script = Script()
    kernel, clock, llm, out = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel, script)
        finally:
            await kernel.stop()

    return run_virtual(clock, main), llm, script


def events(kernel, name):
    mind = kernel.mind
    return [mind.decode(e) for e in mind.store.read() if e.type == name]


async def her_initiative(kernel, handle: str, n: int) -> None:
    """Elle écrit d'elle-même (une envie de discuter), journalisée comme le ferait le pipeline."""
    corr = f"ep:{handle}:{n}"
    await kernel.mind.append([rt.EPISODE_STARTED.draft(kind="INITIATIVE", target=handle, reason=social_c.CHAT)],
                             emitter="runtime", correlation=corr, origin=Origin.GENESIS)
    await kernel.mind.append([rt.UTTERANCE.draft(
        kind="INITIATIVE", text=Content.of("coucou, ça va ?"), target=handle, channel="telegram",
        voice=VoiceProvenance(call_id=corr, persona_hash="", role="initiative", model="m"))],
        emitter="runtime", correlation=corr, origin=Origin.GENESIS)


async def they_say(kernel, handle: str, text: str) -> None:
    p = await kernel.perceive(said(handle, text, channel="telegram"))
    if p.reply is not None:
        await p.reply


# ── MEM-22 : la réciprocité ───────────────────────────────────────────────


def test_she_notices_when_she_always_writes_first_and_her_reaching_out_slows_down(tmp_path):
    async def scenario(kernel, script):
        await befriend(kernel, "tg_1", social_c.FRIEND)
        await befriend(kernel, "tg_2", social_c.FRIEND)
        for day in range(6):
            await her_initiative(kernel, "tg_1", day)  # c'est toujours elle…
            await asyncio.sleep(HOUR / US)
            await they_say(kernel, "tg_1", "ah coucou, oui ça va")  # … la personne répond, sans jamais ouvrir
            if day % 2:
                await her_initiative(kernel, "tg_2", day)
                await asyncio.sleep(HOUR / US)
                await they_say(kernel, "tg_2", "coucou toi")
            else:
                await they_say(kernel, "tg_2", "salut Mika, devine quoi")  # l'autre amie ouvre aussi
            await asyncio.sleep(DAY / US - 2 * HOUR / US)
        await asyncio.sleep(60)
        frame = kernel.mind.frame()
        state = frame.state("social")
        modulation = {reason: _one_sided(state, frame, RowView("INITIATIVE", "tg_1", 5.0, (reason,)))
                      for reason in (social_c.CHAT, social_c.RECONTACT, attention_c.THOUGHT, "remind")}
        other = _one_sided(state, frame, RowView("INITIATIVE", "tg_2", 5.0, (social_c.CHAT,)))
        thoughts = events(kernel, attention_c.THOUGHT_BORN.name)
        texts = kernel.mind.store.content([t.data.text.ref for t in thoughts])
        return (frame.get(social_c.CONTACT("tg_1")), frame.get(social_c.CONTACT("tg_2")), modulation, other,
                events(kernel, social_c.ONE_SIDED.name), list(texts.values()))

    (one, both, modulation, other, noticed, thoughts), _llm, _s = run(tmp_path, scenario)
    assert one.one_sided and one.her_starts >= 5 and one.their_starts == 0
    assert not both.one_sided and both.their_starts >= 3  # contrôle : une amie qui écrit autant qu'elle
    assert modulation[social_c.CHAT].shift < 0 and modulation[social_c.RECONTACT].shift < 0
    assert modulation[attention_c.THOUGHT].shift < 0
    assert modulation["remind"].shift == 0 and modulation["remind"].veto is None  # un rappel promis se dit
    assert other.shift == 0
    assert [e.data.about for e in noticed] == [("tg_1",)]  # une fois, pour elle seule
    assert any("toujours moi qui écris la première" in t for t in thoughts)


# ── MEM-6 (b) : les mots d'un profil s'oublient avec la personne ──────────


def test_the_words_of_her_profile_of_someone_are_forgotten_with_them(tmp_path):
    """Le ton, les intérêts et les sujets délicats d'une fiche sont gardés à part :
    « Oublier » la personne les efface (avant : en clair au journal, et dans le prompt)."""
    async def scenario(kernel, script):
        await connect(kernel, "user_1", "Alice")
        drafts = []
        for text in ("j'adore la montagne", "je fais de l'escalade le samedi", "je pars dans les Alpes en juin"):
            p = await kernel.perceive(said("user_1", text))
            await p.reply
            drafts.append(memory_c.BELIEVED.draft(text=Content.of(f"Alice m'a dit : {text}", level=2),
                                                  about=("user_1",), sensitivity=2, source="user_1",
                                                  sources=(p.seq,)))
        await kernel.mind.append(drafts, emitter="memory", correlation="genese", origin=Origin.GENESIS)
        await kernel.mind.append([memory_c.CONSOLIDATED.draft(upto=p.seq)], emitter="memory", correlation="c",
                                 origin=Origin.GENESIS)
        await asyncio.sleep(60)
        frame = kernel.mind.frame()
        profile = frame.state("social").profiles.get("user_1")
        refs = [profile.tone_ref, profile.interests_ref, profile.sensitive_ref] if profile else []
        store = kernel.ports["store"]
        before = store.content(refs)
        sensitive_ref = frame.get(social_c.SENSITIVE_REF("user_1"))
        await kernel.forget("user_1")
        after = kernel.ports["store"].content(refs)
        plain = [e for e in events(kernel, social_c.PROFILE_REVISED.name)
                 if e.data.legacy_tone or e.data.legacy_interests or e.data.legacy_sensitive]
        return script.profiles, profile, before, after, sensitive_ref, plain

    (prompts, profile, before, after, sensitive_ref, plain), _llm, _s = run(tmp_path, scenario)
    assert prompts and profile is not None and all(r for r in (profile.tone_ref, profile.interests_ref))
    assert sensitive_ref == profile.sensitive_ref
    assert sorted(before.values()) == ["doux", "montagne", "sa santé"]
    assert after == {}  # oubliée, Alice n'a plus ni ton, ni intérêts, ni sujets délicats nulle part
    assert plain == []  # rien en clair dans l'enveloppe du journal


# ── PRM-1, 17, 18, 19 : « QUI TU AS EN FACE » ─────────────────────────────


def test_who_says_when_they_last_talked_in_calendar_words_without_mechanism(tmp_path):
    async def scenario(kernel, script):
        await connect(kernel, "user_1", "Alice")
        await befriend(kernel, "user_1", social_c.CLOSE)
        p = await kernel.perceive(said("user_1", "bonne soirée !"))  # lundi 18 h
        await p.reply
        await asyncio.sleep((at_paris(2026, 9, 29, 14, 13) - at_paris(2026, 9, 28, 18, 0)) / US)
        p = await kernel.perceive(said("user_1", "re ! tu fais quoi cet aprèm ?"))  # mardi 14 h 13
        await p.reply
        return None

    _, llm, _s = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 18, 0))
    last = [r for r in llm.calls if r.role == "reply" and r.meta.get("target") == "user_1"][-1]
    text = "\n".join(m.content for m in last.messages)
    who = text.split("--- QUI TU AS EN FACE ---", 1)[1].split("\n--- ", 1)[0]
    assert "C'est « Alice »." in who
    assert "connectée" not in who and "compte" not in who  # pas le mécanisme
    assert "Avant cette conversation, « Alice » t'avait écrit pour la dernière fois hier soir (lundi vers 18 h)." in who
    assert "presque pas de passé commun" not in who  # une proche : on ne se contredit pas
    assert "Vous vous parlez ici depuis hier." in who
    about = text.split("--- CE QUE TU SAIS DE CETTE PERSONNE ---", 1)[1].split("\n--- ", 1)[0]
    assert "« Alice » compte parmi tes proches." in about
    assert "elle ou lui" not in about and "elle ou il" not in who


def test_a_stranger_is_someone_she_does_not_know_yet(tmp_path):
    async def scenario(kernel, script):
        await connect(kernel, "user_3", "Chloé")
        for text in ("salut", "je découvre l'appli", "tu fais quoi ?"):
            p = await kernel.perceive(said("user_3", text))
            await p.reply
        frame = kernel.mind.frame()
        return frame.get(social_c.CLOSENESS("user_3")), frame.get(identity_c.IDENTITY("user_3"))

    (level, view), llm, _s = run(tmp_path, scenario)
    assert level == social_c.STRANGER and view.name == "Chloé"
    last = [r for r in llm.calls if r.role == "reply" and r.meta.get("target") == "user_3"][-1]
    text = "\n".join(m.content for m in last.messages)
    assert "c'est inconnue" not in text
