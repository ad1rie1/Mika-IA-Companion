"""Prendre la parole sans harceler (ADR 0033), par ses intentions.

- quelqu'un qui reste connecté sans répondre : au plus une relance, douce,
  puis le silence — et un ressenti (« … ne m'a pas répondu ») ; une amie qui
  répond reçoit toujours des initiatives ;
- une amie absente qui se tait : une prise de nouvelles, puis une seule
  relance douce après un long délai, puis plus rien ;
- le budget se compte à ce qu'elle a dit : un silence ne consomme rien ;
- l'envie de compagnie sans rien à dire ne suffit presque plus ; avec une
  matière concrète, si ;
- travailler l'occupe ; la solitude se creuse avec la durée.
"""

from __future__ import annotations

import asyncio

from mika.app import composition
from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import goals as goals_c
from mika.contracts import memory as memory_c
from mika.contracts import needs as needs_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.agency import _budget, restraint
from mika.kernel.arbitration import RowView
from mika.kernel.clock import DAY, HOUR, MINUTE, US, local
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.ports.llm import LLMResponse
from mika.runtime.effects import with_content
from mika.sim.clock import run_virtual
from tests.fixtures.mika import DOC, PARIS, at_paris, befriend, boot, build, connect, disconnect, said


class Script:
    """Elle répond par une question (comme dans la sonde), écrit d'elle-même
    quand on la pousse, murmure quand on le lui demande."""

    def __init__(self) -> None:
        self.reply = "ah oui ? et toi, ta soirée ? [EMOTION:curious:0.5]"
        self.initiative = "coucou, ça va ? [EMOTION:happy:0.5]"

    def __call__(self, req):
        if req.role in ("extract", "profile", "compact"):
            return LLMResponse("{}")
        if req.role == "murmur":
            return LLMResponse("tiens, et si je lui écrivais")
        if req.role in ("narrative", "journal", "dream"):
            return LLMResponse("Une journée.")
        if req.role == "initiative":
            return LLMResponse(self.initiative)
        return LLMResponse(self.reply)


def run(tmp_path, scenario, *, start=at_paris(2026, 9, 28, 17, 0), script=None):
    script = script or Script()
    kernel, clock, llm, out = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel, script, out, llm)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


def events(kernel, name):
    mind = kernel.mind
    return [with_content(mind, mind.decode(e)) for e in mind.store.read() if e.type == name]


def initiatives(kernel, target, *, owed=False):
    """Ses initiatives dites vers cette adresse (sans les salutations ni les rappels, sauf ``owed``)."""
    reasons = {e.correlation: e.data.reason for e in events(kernel, rt.EPISODE_STARTED.name)}
    return [e for e in events(kernel, rt.UTTERANCE.name) if e.data.kind == "INITIATIVE" and e.data.target == target
            and (owed or not {social_c.GREETING, "remind"} & set(reasons.get(e.correlation, "").split(",")))]


async def chat(kernel, handle, texts, *, channel="web", gap=90):
    for text in texts:
        p = await kernel.perceive(said(handle, text, channel=channel))
        await p.reply
        await asyncio.sleep(gap)


# ── La sonde : connecté, et plus un mot ───────────────────────────────────


def test_a_friend_who_stays_connected_and_silent_gets_one_gentle_word_then_silence_and_a_feeling(tmp_path):
    """La sonde avec un vrai modèle : Adrien reste connecté trois jours sans
    répondre à sa question ; elle lui écrivait cinq fois d'affilée. Une
    personne lui écrirait au plus une fois, doucement, puis se tairait — et le
    ressentirait."""
    async def scenario(kernel, script, out, llm):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(90)
        await chat(kernel, "user_1", ["salut mika ! ça va ?", "moi je suis crevé, grosse journée au taf",
                                      "tu fais quoi de beau toi aujourd'hui ?"])
        await asyncio.sleep(3 * DAY / US)
        briefs = [c.messages[-1].content for c in llm.calls if c.role == "initiative"]
        felt = [e for e in events(kernel, attention_c.THOUGHT_BORN.name) if e.data.origin == attention_c.UNANSWERED]
        return initiatives(kernel, "user_1"), briefs, felt

    sent, briefs, felt = run(tmp_path, scenario)
    assert len(sent) <= 1, [local(e.at, PARIS).strftime("%a %H:%M") for e in sent]
    if sent:  # le mot qu'elle lui écrit sait que sa question est restée sans réponse
        assert any("resté sans réponse" in b for b in briefs)
    texts = [e.data.text.text or "" for e in felt]
    assert texts and texts[0] == "Adrien n'a pas répondu à ma question.", texts  # elle le ressent…
    assert all("Adrien" in t for t in texts) and len(texts) <= 2  # … une fois par silence, pas en boucle


def test_a_question_left_behind_by_someone_who_left_is_not_an_affront(tmp_path):
    """Le contre-exemple du ressenti : Adrien ferme l'application après sa
    réponse (une question) — on se reparlera ; ce n'est pas l'ignorer, ni
    quand il revient le lendemain. Il dit « bon je file, à plus ! » sans fermer
    l'application : la conversation s'est close, pas davantage (audit HUM-4).
    Resté là sans répondre, si (la sonde)."""
    def scenario(leaves, back=False, last="bof, longue journée"):
        async def go(kernel, script, out, llm):
            await befriend(kernel, "user_1", social_c.FRIEND)
            await connect(kernel, "user_1", "Adrien")
            await chat(kernel, "user_1", ["salut mika ! ça va ?", last])
            if leaves:
                await disconnect(kernel, "user_1")
            if back:
                await asyncio.sleep(22 * HOUR / US)
                await connect(kernel, "user_1", "Adrien")
            await asyncio.sleep(8 * HOUR / US)
            return [e.data.text.text for e in events(kernel, attention_c.THOUGHT_BORN.name)
                    if e.data.origin == attention_c.UNANSWERED]
        return go

    start = at_paris(2026, 9, 28, 10, 0)
    assert run(tmp_path / "parti", scenario(True), start=start) == []
    back = run(tmp_path / "revenu", scenario(True, back=True), start=start)
    assert not any("à ma question" in t for t in back), back  # (s'il ignore ensuite son initiative, c'est autre chose)
    # « je file » : sa réponse ne laisse aucune question en suspens (une initiative ignorée ensuite, c'est autre chose)
    clos = run(tmp_path / "clos", scenario(False, last="bon je file, à plus !"), start=start)
    assert not any("à ma question" in t for t in clos), clos
    assert run(tmp_path / "reste", scenario(False), start=start) == ["Adrien n'a pas répondu à ma question."]


def test_after_a_goodbye_she_does_not_write_right_away_even_if_the_tab_stays_open(tmp_path):
    """« bon je file, bonne soirée » et l'onglet reste ouvert : pas de « t'es encore là ? » dix minutes après ;
    quelques heures plus tard, si. Ce qui est dû (un rappel promis) passe quand même (contre-exemples)."""
    async def scenario(kernel, script, out, llm):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Adrien")
        await chat(kernel, "user_1", ["salut mika ! ça va ?", "bon je file, bonne soirée"])
        await asyncio.sleep(20 * MINUTE / US)
        soon = kernel.mind.frame()
        await asyncio.sleep(5 * HOUR / US)
        later = kernel.mind.frame()
        def veto(f, *reasons):
            return _budget(f.state("agency"), f, RowView("INITIATIVE", "user_1", 5.0, reasons)).veto

        return [veto(f, social_c.CHAT) for f in (soon, later)], veto(soon, goals_c.REMIND)

    (chat_soon, chat_later), remind = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 14, 0))
    assert chat_soon == agency_c.FAREWELL and chat_later != agency_c.FAREWELL
    assert remind != agency_c.FAREWELL


def test_a_friend_who_answers_keeps_getting_initiatives(tmp_path):
    """Le contre-exemple : la même amie, qui répond à chaque fois, continue de
    recevoir des mots d'elle — la retenue vise le silence, pas l'amitié."""
    async def scenario(kernel, script, out, llm):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Adrien")
        script.reply = "haha d'accord [EMOTION:happy:0.5]"
        seen = 0
        for _ in range(3 * 24 * 6):
            await asyncio.sleep(10 * MINUTE / US)
            sent = initiatives(kernel, "user_1")
            if len(sent) > seen:
                seen = len(sent)
                await asyncio.sleep(5 * MINUTE / US)
                p = await kernel.perceive(said("user_1", "oui ça va, et toi ?"))
                await p.reply
        return initiatives(kernel, "user_1")

    sent = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 9, 0))
    assert len(sent) >= 4, [local(e.at, PARIS).strftime("%a %H:%M") for e in sent]


def test_the_rule_vetoes_every_ordinary_reason_and_allows_one_gentle_follow_up(tmp_path):
    """Le filet : quelle que soit la raison (une pensée, un manque…), après une
    initiative sans réponse, plus rien — présente ou non — sauf une relance
    douce après au moins un jour et deux fois le rythme ; après deux, plus rien.
    Saluer, dire un rappel promis : jamais concernés."""
    def voice():
        return VoiceProvenance(call_id="x", persona_hash="", role="initiative", model="m")

    async def initiative(kernel, n):
        await kernel.mind.append([rt.UTTERANCE.draft(
            kind="INITIATIVE", text=Content.of("tu vas mieux ?"), target="tg_1", channel="telegram", voice=voice())],
            emitter="runtime", correlation=f"genese{n}", origin=Origin.GENESIS)

    def veto(kernel, reasons=("thought",)):
        frame = kernel.mind.frame()
        return _budget(frame.state("agency"), frame, RowView("INITIATIVE", "tg_1", 5.0, reasons)).veto

    async def scenario(kernel, script, out, llm):
        await befriend(kernel, "tg_1", social_c.CLOSE)
        p = await kernel.perceive(said("tg_1", "coucou", channel="telegram"))
        await p.reply
        await asyncio.sleep(13 * HOUR / US)
        free = veto(kernel)
        await initiative(kernel, 1)
        absent = veto(kernel)
        await connect(kernel, "tg_1", "Alice")
        present = veto(kernel)
        greeting = veto(kernel, (social_c.GREETING,))
        first = kernel.mind.clock.now()
        await asyncio.sleep(DAY / US)
        early = veto(kernel)  # proche, rythme supposé de trois jours : deux fois ça, pas encore
        await asyncio.sleep(9 * DAY / US)  # elle relance d'elle-même, une fois, doucement
        sent = initiatives(kernel, "tg_1")
        briefs = [c.messages[-1].content for c in llm.calls if c.role == "initiative"]
        after_two = veto(kernel)
        p = await kernel.perceive(said("tg_1", "désolée, j'étais débordée !", channel="telegram"))
        await p.reply
        answered = kernel.mind.frame().get(attention_c.AWAITING("tg_1"))
        return free, absent, present, greeting, early, first, sent, briefs, after_two, answered

    free, absent, present, greeting, early, first, sent, briefs, after_two, answered = run(tmp_path, scenario)
    assert free is None
    assert absent == present == agency_c.UNANSWERED  # présente ou non
    assert greeting is None  # saluer qui arrive n'est pas prendre la parole
    assert early == agency_c.UNANSWERED
    follow_ups = [e for e in sent if e.at > first]
    assert len(follow_ups) == 1 and follow_ups[0].at - first >= 6 * DAY, [e.at - first for e in sent]
    assert any("relance douce" in b for b in briefs)
    assert after_two == agency_c.UNANSWERED  # après deux sans réponse : plus rien
    assert answered.initiatives == 0 and answered.ignored == 0  # elle a écrit : tout repart de zéro


def test_her_last_message_left_unanswered_holds_her_back_for_hours_a_question_longer(tmp_path):
    async def scenario(kernel, script, out, llm):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Adrien")
        await chat(kernel, "user_1", ["tu fais quoi ce soir ?"], gap=1)
        frame = kernel.mind.frame()
        asked = restraint(frame, "user_1", ("need_social",)).veto
        worried = restraint(frame, "user_1", ("check_in",)).veto
        await asyncio.sleep(6 * HOUR / US)
        later = restraint(kernel.mind.frame(), "user_1", ("need_social",)).veto
        await asyncio.sleep(7 * HOUR / US)
        free = restraint(kernel.mind.frame(), "user_1", ("need_social",)).veto
        return asked, worried, later, free

    asked, worried, later, free = run(tmp_path, scenario)
    assert asked == agency_c.AWAITING_REPLY and later == agency_c.AWAITING_REPLY  # sa question attend
    assert worried is None  # une prise de nouvelles après une inquiétude n'attend pas autant
    assert free is None


# ── Le budget se compte à ce qu'elle dit ──────────────────────────────────


def test_a_silence_consumes_nothing_but_leaves_a_short_hesitation(tmp_path):
    """Elle s'abstient (ou l'appel tombe en panne, ou la personne écrit entre-temps) :
    rien n'est compté contre son plafond du jour, aucune période réfractaire ;
    une abstention ou une panne laissent seulement une courte hésitation. Ce
    qu'elle dit, si : c'est compté."""
    def voice():
        return VoiceProvenance(call_id="x", persona_hash="", role="initiative", model="m")

    async def episode(kernel, n, outcome, *, said_=False):
        mind, eid = kernel.mind, f"ep{n}"
        await mind.append([rt.EPISODE_STARTED.draft(kind="INITIATIVE", target="user_1", reason="need_social")],
                          emitter="runtime", correlation=eid, origin=Origin.KERNEL)
        if said_:
            await mind.append([rt.UTTERANCE.draft(kind="INITIATIVE", text=Content.of("coucou"), target="user_1",
                                                  voice=voice())], emitter="runtime", correlation=eid,
                              origin=Origin.KERNEL)
        await mind.append([rt.EPISODE_ENDED.draft(kind="INITIATIVE", outcome=outcome, target="user_1")],
                          emitter="runtime", correlation=eid, origin=Origin.KERNEL)
        return kernel.mind.frame().get(agency_c.AGENCY)

    async def scenario(kernel, script, out, llm):
        silent = await episode(kernel, 1, "abstained")
        await asyncio.sleep(HOUR / US)
        superseded = await episode(kernel, 2, "superseded")
        failed = await episode(kernel, 3, "failed")
        await asyncio.sleep(HOUR / US)
        said_ = await episode(kernel, 4, "done", said_=True)
        return silent, superseded, failed, said_

    silent, superseded, failed, said_ = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 10, 0))
    assert silent.initiatives_today == 0 and silent.last_initiative_at == 0 and silent.hesitated_at  # rien de consommé
    assert superseded.initiatives_today == 0 and superseded.hesitated_at == silent.hesitated_at  # pas d'hésitation
    assert failed.initiatives_today == 0 and failed.hesitated_at > silent.hesitated_at
    assert said_.initiatives_today == 1 and said_.refractory_until > said_.last_initiative_at > 0


# ── De quoi parler ────────────────────────────────────────────────────────


def test_without_anything_to_say_the_urge_alone_barely_counts(tmp_path):
    """L'envie de compagnie ne dit pas de quoi parler : sans matière, sa preuve
    ne garde qu'une part ; ce que la personne lui a dit d'elle-même, une pensée,
    ce qu'elle a fini — et la preuve est entière."""
    from mika.faculties.needs import _matterless

    async def scenario(kernel, script, out, llm):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await connect(kernel, "user_1", "Adrien")
        await asyncio.sleep(4 * HOUR / US)
        row = RowView("INITIATIVE", "user_1", 9.0, ("need_expression", "need_social", "present"))
        frame = kernel.mind.frame()
        empty = _matterless(frame.state("needs"), frame, row)
        before = frame.get(needs_c.MATTER("user_1"))
        await kernel.mind.append([memory_c.BELIEVED.draft(
            text=Content.of("Adrien a un entretien jeudi", level=1), about=("user_1",), sensitivity=1,
            source="user_1")], emitter="memory", correlation="genese", origin=Origin.GENESIS)
        frame = kernel.mind.frame()
        told = _matterless(frame.state("needs"), frame, row)
        other = _matterless(frame.state("needs"), frame,
                            RowView("INITIATIVE", "user_1", 9.0, ("need_social", "recontact")))
        return empty, before, told, frame.get(needs_c.MATTER("user_1")), other

    empty, before, told, matter, other = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 9, 0))
    assert before is None and empty.shift < -3  # nettement plus faible
    assert matter is not None and matter.kind == needs_c.TOLD_MATTER and told.shift == 0
    assert other.shift == 0  # une autre raison est sa propre matière


def test_what_someone_else_said_about_a_person_is_not_her_matter_with_them(tmp_path):
    async def scenario(kernel, script, out, llm):
        await kernel.mind.append([memory_c.BELIEVED.draft(
            text=Content.of("Alice va quitter son mari", level=3), about=("user_1",), sensitivity=3,
            source="user_2")], emitter="memory", correlation="genese", origin=Origin.GENESIS)
        return kernel.mind.frame().get(needs_c.MATTER("user_1"))

    assert run(tmp_path, scenario) is None


def test_a_needs_driven_initiative_is_told_what_to_talk_about_never_to_speak_for_nothing(tmp_path):
    async def scenario(kernel, script, out, llm):
        await befriend(kernel, "user_1", social_c.FRIEND)
        await kernel.mind.append([memory_c.BELIEVED.draft(
            text=Content.of("Adrien prépare un entretien chez Ubisoft", level=1), about=("user_1",),
            sensitivity=1, source="user_1")], emitter="memory", correlation="genese", origin=Origin.GENESIS)
        await connect(kernel, "user_1", "Adrien")
        for _ in range(6 * 10):
            await asyncio.sleep(10 * MINUTE / US)
            if initiatives(kernel, "user_1"):
                break
        return [c.messages[-1].content for c in llm.calls if c.role == "initiative"]

    briefs = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 9, 0))
    assert briefs
    assert not any("simplement envie de dire quelque chose" in b for b in briefs)
    needs_driven = [b for b in briefs if "CE DONT TU POURRAIS PARLER" in b]
    assert needs_driven and "entretien chez Ubisoft" in needs_driven[0]


# ── Travailler l'occupe ; la solitude se creuse ───────────────────────────


def test_the_void_deepens_with_time_but_never_drowns_her(tmp_path):
    """Tant que rien ne l'occupe, le vide se creuse ; une rêverie qu'elle entreprend l'occupe (le vide repart de
    son plancher, c'est voulu) : on mesure la montée avant qu'elle ne s'occupe."""
    async def scenario(kernel, script, out, llm):
        p = await kernel.perceive(said("user_1", "bon, à plus"))
        await p.reply
        await asyncio.sleep(10 * HOUR / US)
        busy = [e.at for e in events(kernel, goals_c.GOAL_OPENED.name)]
        return [e.data.intensity for e in events(kernel, needs_c.FELT.name)
                if not busy or e.at < busy[0]], events(kernel, needs_c.FELT.name)

    felt, every = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 9, 0))
    assert felt and felt[-1] > felt[0] + 0.1  # elle s'aggrave avec la durée…
    felt = [e.data.intensity for e in every]
    assert max(felt) <= 0.35  # … sans la faire sombrer
    assert len(felt) <= 8 * 4 + 1  # toutes les quinze minutes, pas plus


def test_a_day_without_anyone_leaves_a_thought(tmp_path):
    async def scenario(kernel, script, out, llm):
        p = await kernel.perceive(said("user_1", "bon, à plus"))
        await p.reply
        await asyncio.sleep(30 * HOUR / US)
        alone = [e for e in events(kernel, attention_c.THOUGHT_BORN.name) if e.data.origin == attention_c.ALONE]
        p = await kernel.perceive(said("user_1", "coucou !"))
        await p.reply
        after = [t for t in kernel.mind.frame().get(attention_c.THOUGHTS) if t.origin == attention_c.ALONE]
        return alone, after

    # le retour arrive en journée (mardi 16 h) : la nuit, la réponse d'une inconnue attendrait son réveil (ADR 0036)
    alone, after = run(tmp_path, scenario, start=at_paris(2026, 9, 28, 10, 0))
    assert len(alone) == 1 and (alone[0].data.text.text or "").startswith("Personne ne m'a parlé depuis hier")
    assert not after  # quelqu'un écrit : elle n'est plus seule


# ── Le murmure ────────────────────────────────────────────────────────────


def run_with(tmp_path, scenario, overrides, *, start=at_paris(2026, 9, 28, 10, 0), script=None):
    script = script or Script()
    kernel, clock, llm, out = build(tmp_path, script, start=start)

    async def main():
        await kernel.start(configure=lambda k: composition.configure(k, DOC, overrides))
        try:
            return await scenario(kernel, script, out, llm)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def _worried_about_alice(kernel):
    """Alice (proche, présente) lui a confié quelque chose qui l'inquiète — une
    pensée qui insiste, dont le texte porte un canari."""
    await befriend(kernel, "user_1", social_c.CLOSE)
    await connect(kernel, "user_1", "Alice")
    await kernel.mind.append([attention_c.THOUGHT_BORN.draft(
        text=Content.of("Alice m'a dit : « CANARI-MURMURE mon père est à l'hôpital »", level=2),
        emotion="anxious", intensity=0.9, origin=attention_c.CONCERN, about=("user_1",), sensitivity=2)],
        emitter="attention", correlation="genese", origin=Origin.GENESIS)


def test_the_murmur_says_why_in_plain_words_never_the_motive_and_only_to_the_one_she_writes_to(tmp_path):
    async def scenario(kernel, script, out, llm):
        await _worried_about_alice(kernel)
        await connect(kernel, "user_2", "Bob")  # quelqu'un d'autre regarde aussi
        for _ in range(6 * 6):
            await asyncio.sleep(10 * MINUTE / US)
            if [c for c in llm.calls if c.role == "murmur"]:
                break
        await asyncio.sleep(MINUTE / US)
        prompts = ["\n".join(m.content for m in c.messages) + c.system_stable for c in llm.calls if c.role == "murmur"]
        inner = [d for d in out.items if d.persona == "inner" and d.kind == "speech"]
        return prompts, inner

    prompts, inner = run_with(tmp_path, scenario, {"expression": {"murmur_chance": 1.0, "murmur_charged_chance": 1.0,
                                                                   "murmur_adrift": 0.0}})
    assert prompts and inner
    assert not any("CANARI-MURMURE" in p or "n'avait pas l'air" in p for p in prompts)  # ni le motif, ni ses mots
    assert "quelque chose qui te trotte dans la tête" in prompts[0]  # la raison, en clair et générique
    assert "Il est " in prompts[0] and "tu te sens" in prompts[0] and "« Alice »" in prompts[0]
    assert "Tu t'apprêtes" not in prompts[0]  # plus la consigne nue qui faisait « pourquoi il m'demande d'écrire »
    assert all(d.target == "user_1" for d in inner)  # pas sur l'écran de Bob


def test_sometimes_she_thinks_of_writing_then_changes_her_mind(tmp_path):
    """Un murmure sans suite : elle y pense, se ravise — et l'initiative ne part
    pas (elle n'est même pas composée)."""
    async def scenario(kernel, script, out, llm):
        await _worried_about_alice(kernel)
        for _ in range(6 * 6):
            await asyncio.sleep(10 * MINUTE / US)
            if [c for c in llm.calls if c.role == "murmur"]:
                break
        await asyncio.sleep(2 * MINUTE / US)
        murmurs = [c.messages[-1].content for c in llm.calls if c.role == "murmur"]
        first = next(i for i, c in enumerate(llm.calls) if c.role == "murmur")
        composed = [c for c in llm.calls[first:] if c.role == "initiative"]
        return murmurs, composed, initiatives(kernel, "user_1"), kernel.mind.frame().get(agency_c.AGENCY)

    murmurs, composed, sent, reading = run_with(tmp_path, scenario, {"expression": {
        "murmur_chance": 1.0, "murmur_charged_chance": 1.0, "murmur_adrift": 1.0}})
    assert murmurs and "tu te ravises" in murmurs[0]
    assert not composed and not sent  # l'initiative qu'il précédait ne part pas
    assert reading.hesitated_at  # une courte hésitation
