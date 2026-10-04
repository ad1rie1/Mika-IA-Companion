"""Promesses, rappels et moments de leur vie (ADR 0052), par leurs intentions — d'après la seconde semaine de la
sonde réelle (2026-10-03) : Sam demande lundi qu'on lui rappelle mercredi de prendre rendez-vous chez le dentiste,
son chat Pixel meurt mardi, il a 30 ans samedi.

- une promesse datée ne se tient pas la veille : « demain je te le rappelle comme promis », mardi soir, ne la
  règle pas — mercredi, elle le lui rappelle, même s'il ne passe que le soir ; s'il y renonce, elle est
  abandonnée ;
- un rappel demandé et accepté existe une fois et une seule : une promesse si l'outil n'a pas été appelé, le rappel
  programmé sinon (et une promesse notée avant lui laisse la place) ;
- « rappelle-moi de prendre rendez-vous chez le dentiste » n'est pas « son rendez-vous chez le dentiste » ;
- le lendemain d'un deuil, elle prend de ses nouvelles ; elle ne lui demande pas comment s'est passé le dentiste ;
- un anniversaire se souhaite le jour même, d'elle-même, une fois — ni « bonne chance » la veille, ni « comment
  ça s'est passé » le lendemain ; un entretien, lui, garde l'encouragement de la veille et le suivi ;
- ce qu'il raconte le jour même d'un moment « jour entier » (« le véto dit insuffisance rénale ») le reprend ;
- ce dont elle pourrait lui parler part de ce qui pèse le plus dans sa vie, pas du prochain rendez-vous banal.
"""

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

import pytest

from mika.contracts import goals as goals_c
from mika.contracts import memory as memory_c
from mika.contracts import needs as needs_c
from mika.contracts import others as others_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.memory import extraction as x
from mika.faculties.memory.life import same_task, wishes
from mika.faculties.needs import NeedsParams, _lead
from mika.faculties.others.faculty import _follow_up
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMResponse, ToolCall
from mika.sim.clock import run_virtual
from tests.fixtures.memory import section, seq_of, token
from tests.fixtures.mika import PARIS, at_paris, befriend, boot, build, connect, disconnect, said

LIFE = "CE QUI SE PASSE DANS SA VIE"
PROMISED = "CE QUE TU LUI AS PROMIS"
MONDAY = at_paris(2026, 10, 5, 8, 45)
ASK = "au fait tu peux me rappeler de prendre rdv chez le dentiste mercredi ? j'oublie tout le temps"


class Script:
    """Un modèle scripté : ``reply(message, req)`` rend un texte, ou un ``LLMResponse`` (un appel d'outil), ou
    ``None`` ; ``extract(prompt)`` rend les arguments de ``record_memories`` ; ses initiatives disent
    ``initiative``."""

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
        got = self.reply(message, req) if self.reply else None
        if isinstance(got, LLMResponse):
            return got
        return LLMResponse(got or "d'accord [EMOTION:happy:0.4]")

    def prompts(self, role, target):
        return [(r, r.system_stable + "\n".join(m.content for m in r.messages)) for r in self.calls
                if r.role == role and r.meta.get("target") == target]


def run(tmp_path, scenario, script, *, start=MONDAY):
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


def started(kernel, reason, target=None):
    return [e for e in events(kernel, rt.EPISODE_STARTED.name)
            if e.data.kind == "INITIATIVE" and reason in e.data.reason.split(",")
            and (target is None or e.data.target == target)]


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


async def note(kernel, text, when, person, *, all_day=False, importance=0.45, festive=False):
    commit = await kernel.mind.append([memory_c.EVENT_NOTED.draft(
        text=Content.of(text, level=2), when=when, about=(person,), all_day=all_day, sensitivity=2,
        told_by=(person,), heard_by=(person,), importance=importance, festive=festive)],
        emitter="memory", correlation=f"genese:{text}", origin=Origin.GENESIS)
    return commit.seqs[-1]


def _promise_id(prompt: str) -> int | None:
    m = re.search(r"\[#(\d+)\] \(à Sam", prompt)
    return int(m.group(1)) if m else None


def _messages(prompt: str) -> str:
    return prompt.split("Les messages :", 1)[-1]


# ── Les mots, purs ────────────────────────────────────────────────────────


def test_what_is_a_task_what_is_festive_and_what_counts():
    def ev(text, importance=2, a_feter=False):
        return x.XEvenement(texte=text, quand="2026-10-07", importance=importance, a_feter=a_feter)

    assert x.task_words("prendre rendez-vous chez le dentiste") and not x.task_words("son rendez-vous chez le dentiste")
    assert x.task_words("prendre rdv chez le dentiste") and not x.task_words("prendre l'avion pour Tokyo")
    assert same_task("lui rappeler de prendre rendez-vous chez le dentiste mercredi", "prendre rdv chez le dentiste")
    assert not same_task("lui rappeler d'appeler sa mère mercredi", "prendre rdv chez le dentiste mercredi"), \
        "le même jour et le même verbe ne font pas la même chose à faire"
    assert x.festive(ev("son anniversaire de 30 ans")) and x.festive(ev("leur pendaison", a_feter=True))
    assert not x.festive(ev("l'anniversaire de la mort de son père")), "un deuil ne se fête pas"
    assert not x.festive(ev("son entretien chez Ubisoft"))
    assert x.moment_importance(ev("son entretien chez Ubisoft")) >= memory_c.IMPORTANT_MOMENT, \
        "un entretien compte, même si le modèle ne le dit pas"
    assert x.moment_importance(ev("son rendez-vous chez le coiffeur")) < memory_c.IMPORTANT_MOMENT
    assert wishes("Joyeux anniv Sam !! 🎂") and wishes("bon anniversaire") and wishes("Félicitations à vous deux")
    assert not wishes("c'est quand ton anniversaire ?")


# ── Une promesse datée ne se tient pas la veille (constat 1) ──────────────


@pytest.mark.parametrize("cancelled,evening", [(False, 19), (False, 21), (True, 19)])
def test_the_wednesday_reminder_survives_tuesdays_keeping_and_is_said_on_wednesday(tmp_path, cancelled, evening):
    """Lundi, elle promet de lui rappeler mercredi de prendre rendez-vous. Mardi soir, « demain, je te le
    rappelle comme promis » : l'extraction la dit « tenue » — elle ne l'est pas, elle n'est due que mercredi. Sam
    (sur le web, absent toute la journée) ne passe que mercredi soir : elle le lui rappelle quand même, à 19 h comme
    à 21 h. Contre-exemple : mardi, il y renonce (« laisse tomber, j'ai déjà pris rdv ») — abandonnée, rien
    mercredi."""
    box = {}

    def extract(prompt):
        said = _messages(prompt)
        if "dentiste" in said and "rappeler" in said and "Promesses en cours" not in prompt:
            return {"promesses": [{"texte": "lui rappeler de prendre rendez-vous chez le dentiste",
                                   "envers": token(prompt, "Sam"), "echeance": "2026-10-07",
                                   "messages": seq_of(prompt, "rappel")}]}
        pid = _promise_id(prompt)
        if pid is not None and ("dormir" in said or "laisse tomber" in said):
            box["shown"] = prompt
            return {"promesses_tenues": [{"id": pid, "statut": "abandonnée" if cancelled else "tenue"}]}
        return None

    def reply(message, req):
        if "rappeler" in message:
            return "Avec plaisir ! Je te rappelle mercredi pour le dentiste. [EMOTION:happy:0.5]"
        if "dormir" in message:
            return "Dors bien Sam… demain, je te rappelle le dentiste comme promis. [EMOTION:sad:0.6]"
        return None

    script = Script(reply, extract, initiative="Hey Sam ! N'oublie pas de prendre ton rdv chez le dentiste. "
                                               "[EMOTION:happy:0.5]")

    async def scenario(kernel):
        await connect(kernel, "user_1", "Sam")
        await chat(kernel, "user_1", [ASK, "allez j'y vais"])
        await disconnect(kernel, "user_1")
        await until(kernel, at_paris(2026, 10, 6, 22, 30))
        await connect(kernel, "user_1", "Sam")
        await chat(kernel, "user_1", ["au fait laisse tomber pour le rappel, j'ai déjà pris rdv", "bonne nuit"]
                   if cancelled else ["on l'a endormi. j'étais avec lui jusqu'au bout", "je vais essayer de dormir"])
        await disconnect(kernel, "user_1")
        await until(kernel, at_paris(2026, 10, 7, evening, 0))
        await connect(kernel, "user_1", "Sam")
        await asyncio.sleep(HOUR / US)
        promised = events(kernel, memory_c.PROMISE_NOTICED.name)
        return (promised, events(kernel, memory_c.PROMISE_RESOLVED.name),
                started(kernel, memory_c.KEEP_PROMISE, "user_1"))

    promised, resolved, keep = run(tmp_path, scenario, script)
    assert len(promised) == 1 and promised[0].data.all_day
    pid = promised[0].seq
    assert "pour mercredi 7 octobre" in box["shown"], "l'extraction voit pour quand elle est due"
    wednesday = at_paris(2026, 10, 7, 0, 0)
    if cancelled:
        assert [(r.data.status, r.at < wednesday) for r in resolved] == [(memory_c.DROPPED, True)]
        assert keep == [], "abandonnée la veille : rien mercredi"
        return
    assert not [r for r in resolved if r.at < wednesday], "mardi soir, en parler n'était pas la tenir"
    assert len(keep) == 1 and keep[0].data.subject == f"promise:{pid}", keep
    assert keep[0].at >= at_paris(2026, 10, 7, evening, 0), "le jour dit, quand il est là"
    honored = [r for r in resolved if r.data.promise == pid]
    assert len(honored) == 1 and honored[0].data.status == memory_c.HONORED and honored[0].data.by == \
        memory_c.KEPT_BY
    asked = [p for r, p in script.prompts("initiative", "user_1") if "c'est le moment de le faire" in p]
    assert asked and "dentiste" in section(asked[-1], PROMISED)


# ── Un rappel demandé existe une fois et une seule (constats 2 et 3) ──────


@pytest.mark.parametrize("tool", ["none", "same_turn", "later"])
def test_a_reminder_asked_for_exists_once_and_only_once(tmp_path, tool):
    """« Tu peux me rappeler de prendre rdv chez le dentiste mercredi ? » — « ok ! ». Sans l'outil, une promesse
    (la consigne d'extraction l'excluait : « il est noté ailleurs ») ; avec l'outil ``goal_remind``, le rappel
    programmé et pas de promesse en plus ; programmé plus tard (« à 9 h stp »), il prend la place de la promesse.
    Et dans tous les cas, « son rendez-vous chez le dentiste » n'est pas un moment de sa vie : il n'en a pas."""

    def extract(prompt):
        said = _messages(prompt)
        if "dentiste" not in said or "Promesses en cours" in prompt:
            return None
        seqs = seq_of(prompt, "rappel")
        return {"promesses": [{"texte": "lui rappeler de prendre rendez-vous chez le dentiste",
                               "envers": token(prompt, "Sam"), "echeance": "2026-10-07", "messages": seqs}],
                "evenements": [{"texte": "son rendez-vous chez le dentiste", "personnes": [token(prompt, "Sam")],
                                "quand": "2026-10-07", "importance": 2, "messages": seqs}]}

    def remind(req, what):
        return LLMResponse("", tool_calls=(ToolCall(f"{req.call_id}:1", "goal_remind",
                                                    {"when": "2026-10-07T09:00", "what": what}),), stop="tool_use")

    def reply(message, req):
        if any(m.role == "tool" for m in req.messages):
            return "C'est noté ! [EMOTION:happy:0.5]"
        if "rappeler" in message:
            return remind(req, "prendre rdv chez le dentiste") if tool == "same_turn" else \
                "Avec plaisir, je te le rappelle mercredi ! [EMOTION:happy:0.5]"
        if "9 h" in message and tool == "later":
            return remind(req, "prendre rendez-vous chez le dentiste")
        return None

    script = Script(reply, extract)

    async def scenario(kernel):
        await connect(kernel, "user_1", "Sam")
        await chat(kernel, "user_1", [ASK, "merci, allez j'y vais"])
        await asyncio.sleep(10 * MINUTE / US)
        if tool == "later":
            await chat(kernel, "user_1", ["au fait pour le dentiste, à 9 h stp"])
            await asyncio.sleep(10 * MINUTE / US)
        memory = kernel.mind.root.slices["memory"]
        live = [g for g in kernel.mind.frame().get(goals_c.LIVE) if g.kind == goals_c.REMINDER]
        return (list(memory.promises.values()), live, events(kernel, memory_c.EVENT_NOTED.name),
                events(kernel, memory_c.PROMISE_RESOLVED.name))

    promises, reminders, noted, resolved = run(tmp_path, scenario, script)
    if tool == "none":
        assert len(promises) == 1 and reminders == [], "pas d'outil : la promesse, et elle seule"
    elif tool == "same_turn":
        assert promises == [] and len(reminders) == 1, "l'outil appelé : le rappel, pas une promesse de plus"
    else:
        assert promises == [] and len(reminders) == 1, "programmé ensuite, le rappel prend la place de la promesse"
        assert [(r.data.status, r.data.by) for r in resolved] == [(memory_c.DROPPED, memory_c.REMINDER_BY)]
    assert noted == [], "prendre rendez-vous est une chose à faire, pas un rendez-vous dont on prend des nouvelles"


def test_an_appointment_he_has_is_a_moment_of_his_life(tmp_path):
    """Contre-exemple : « mercredi j'ai rendez-vous chez le dentiste, je stresse » — là, c'est un moment de sa vie."""

    def extract(prompt):
        if "dentiste" not in _messages(prompt):
            return None
        return {"evenements": [{"texte": "son rendez-vous chez le dentiste", "personnes": [token(prompt, "Sam")],
                                "quand": "2026-10-07", "importance": 2,
                                "messages": seq_of(prompt, "dentiste")}]}

    async def scenario(kernel):
        await connect(kernel, "user_1", "Sam")
        await chat(kernel, "user_1", ["mercredi j'ai rendez-vous chez le dentiste, je stresse", "allez j'y vais"])
        await asyncio.sleep(10 * MINUTE / US)
        return events(kernel, memory_c.EVENT_NOTED.name)

    noted = run(tmp_path, scenario, Script(extract=extract))
    assert len(noted) == 1 and not noted[0].data.festive and noted[0].data.importance < memory_c.IMPORTANT_MOMENT


# ── Un suivi sans gravité (constat 4) ─────────────────────────────────────


@pytest.mark.parametrize("grief", [True, False])
def test_the_day_after_a_loss_she_checks_in_and_does_not_ask_about_the_dentist(tmp_path, grief):
    """Sam a un rendez-vous chez le dentiste mercredi à 14 h (un moment ordinaire) et un entretien le matin (un
    moment qui compte). Mardi soir, son chat est mort : elle lui répond profondément triste. Mercredi, elle prend
    de ses nouvelles ; ni initiative ni ligne pour lui demander comment s'est passé le dentiste ; l'entretien passe
    après des nouvelles de lui. Contre-exemple : un mardi ordinaire, l'entretien est la première chose qu'une amie
    demanderait, le dentiste reste à demander si ça vient."""

    def reply(message, req):
        if "parti" in message:
            return "Oh non, Sam… je suis tellement désolée pour Pixel. [EMOTION:sad:0.85]"
        return None

    script = Script(reply)

    async def scenario(kernel):
        await befriend(kernel, "ext_1", social_c.FRIEND)
        await chat(kernel, "ext_1", ["salut !", "bonne journée"], channel="external", display_name="Sam")
        moment = await note(kernel, "son rendez-vous chez le dentiste", at_paris(2026, 10, 7, 14, 0), "ext_1")
        await note(kernel, "son entretien chez Ubisoft", at_paris(2026, 10, 7, 10, 0), "ext_1", importance=0.7)
        await until(kernel, at_paris(2026, 10, 6, 22, 30))
        await chat(kernel, "ext_1", ["Pixel est parti cet après-midi" if grief else "rien de spécial aujourd'hui",
                                    "je vais dormir"], channel="external", display_name="Sam")
        await until(kernel, at_paris(2026, 10, 7, 16, 30))
        frame = kernel.mind.frame()
        proposed = [cand for cand in _follow_up(kernel.mind.root.slices["others"], frame)
                    if cand.args.get("subject") == f"moment:{moment}"]
        hard = frame.get(memory_c.HARD_TIMES("ext_1"))
        checked = started(kernel, others_c.CHECK_IN, "ext_1")
        await chat(kernel, "ext_1", ["coucou"], channel="external", display_name="Sam")
        return proposed, hard, checked

    proposed, hard, checked = run(tmp_path, scenario, script)
    life = section(script.prompts("reply", "ext_1")[-1][1], LIFE)
    if grief:
        assert hard > 0, "un deuil la touche : sa peine pour lui le dit, même sans le mot « mort »"
        assert proposed == [], "pas de « comment s'est passé ton dentiste ? » le lendemain d'un deuil"
        assert "dentiste" not in life and "quelque chose de dur" in life
        assert "Ubisoft" in life and "après avoir pris de ses nouvelles" in life and "première chose" not in life
        assert checked and checked[0].at < at_paris(2026, 10, 7, 16, 30), "elle prend de ses nouvelles"
    else:
        assert hard == 0
        assert len(proposed) == 1 and proposed[0].evidence <= 6.0, "un moment ordinaire : si elle y pense"
        lines = {ln.split(" : ", 1)[1].split(" — ")[0]: ln for ln in life.splitlines() if " : " in ln}
        assert "si ça vient" in lines["son rendez-vous chez le dentiste"]
        assert "première chose qu'une amie lui demanderait" in lines["son entretien chez Ubisoft"]
        assert "quelque chose de dur" not in life


def test_a_grave_message_touches_her_without_her_being_sad(tmp_path):
    """« mon père est décédé ce matin » : elle le lit grave, quel que soit le ton de sa réponse. Contre-exemple : une
    réponse à peine triste à un message ordinaire ne fait pas un deuil."""

    async def scenario(kernel):
        await befriend(kernel, "ext_1", social_c.FRIEND)
        await befriend(kernel, "ext_2", social_c.FRIEND)
        await chat(kernel, "ext_1", ["mon père est décédé ce matin"], channel="external")
        await chat(kernel, "ext_2", ["j'ai raté mon bus"], channel="external")
        frame = kernel.mind.frame()
        return frame.get(memory_c.HARD_TIMES("ext_1")), frame.get(memory_c.HARD_TIMES("ext_2"))

    grave, ordinary = run(tmp_path, scenario, Script(lambda m, r: "Oh… [EMOTION:sad:0.5]"))
    assert grave > 0 and ordinary == 0


# ── Un anniversaire se souhaite le jour même (constat 5) ──────────────────


@pytest.mark.parametrize("morning", ["", "salut Mika", "c'est mon anniversaire aujourd'hui !"])
def test_a_birthday_is_wished_on_the_day_once_neither_the_eve_nor_the_day_after(tmp_path, morning):
    """Samedi, les 30 ans de Sam : elle le lui souhaite d'elle-même, une fois — pas de « bonne chance » vendredi
    soir, pas de « comment s'est passé ton anniversaire ? » dimanche. S'il passe dès 8 h 30 et qu'elle le lui
    souhaite en répondant (« souhaite-le-lui si ce n'est pas fait »), c'est fait : pas d'initiative de plus. S'il
    le dit lui-même et qu'elle répond à côté, ce n'est pas le lui avoir souhaité : elle le fait ensuite."""
    in_reply = morning == "salut Mika"

    def reply(message, req):
        if "salut" in message:
            return "Joyeux anniversaire Sam !! 🎂 [EMOTION:happy:0.7]"
        return None

    script = Script(reply, initiative="Joyeux anniversaire Sam !! 30 ans ! 🎂 [EMOTION:happy:0.7]")

    async def scenario(kernel):
        await befriend(kernel, "ext_1", social_c.FRIEND)
        await chat(kernel, "ext_1", ["coucou !", "bonne journée"], channel="external", display_name="Sam")
        moment = await note(kernel, "son anniversaire de 30 ans", at_paris(2026, 10, 10, 18, 0), "ext_1",
                            all_day=True, festive=True)
        if morning:
            await until(kernel, at_paris(2026, 10, 10, 8, 30))
            await chat(kernel, "ext_1", [morning], channel="external", display_name="Sam")
        await until(kernel, at_paris(2026, 10, 11, 23, 0))
        return moment, (started(kernel, others_c.CHEER), started(kernel, others_c.CELEBRATE),
                        started(kernel, others_c.FOLLOW_UP))

    moment, (cheers, celebrations, follow_ups) = run(tmp_path, scenario, script)
    assert cheers == [], "pas de « bonne chance » la veille d'un anniversaire"
    assert [f for f in follow_ups if f.data.subject == f"moment:{moment}"] == [], \
        "souhaité le jour même : pas de « comment ça s'est passé » le lendemain"
    if in_reply:
        assert celebrations == [], "elle le lui a souhaité en répondant : rien de plus"
        prompt = script.prompts("reply", "ext_1")[-1][1]
        assert "souhaite-le-lui si ce n'est pas fait" in section(prompt, LIFE)
    else:
        assert len(celebrations) == 1 and celebrations[0].data.subject == f"moment:{moment}", celebrations
        assert at_paris(2026, 10, 10, 9, 0) <= celebrations[0].at <= at_paris(2026, 10, 10, 22, 0), "le jour même"
        prompt = script.prompts("initiative", "ext_1")[-1][1]
        assert "souhaite-le-lui" in prompt and "son anniversaire" in section(prompt, LIFE)


def test_an_interview_keeps_its_eve_cheer_and_its_follow_up(tmp_path):
    """Contre-exemple : un entretien n'est pas une fête — la veille au soir, un mot pour l'encourager ; après, « alors,
    cet entretien ? » (ce qui compte : d'elle-même) ; jamais de vœux."""
    script = Script(initiative="Bonne chance pour demain ! [EMOTION:happy:0.5]")
    box = {}

    async def scenario(kernel):
        await befriend(kernel, "ext_1", social_c.FRIEND)
        await chat(kernel, "ext_1", ["salut !", "bonne soirée !"], channel="external", display_name="Sam")
        box["moment"] = await note(kernel, "son entretien chez Ubisoft", at_paris(2026, 10, 8, 14, 0), "ext_1",
                                   importance=0.7)
        await until(kernel, at_paris(2026, 10, 8, 23, 0))
        box["starts"] = (started(kernel, others_c.CHEER), started(kernel, others_c.FOLLOW_UP),
                         started(kernel, others_c.CELEBRATE))

    run(tmp_path, scenario, script)
    cheers, follow_ups, celebrations = box["starts"]
    assert len(cheers) == 1 and at_paris(2026, 10, 7, 18, 0) <= cheers[0].at <= at_paris(2026, 10, 7, 22, 0)
    assert len(follow_ups) == 1 and follow_ups[0].at >= at_paris(2026, 10, 8, 16, 0)
    assert celebrations == []


# ── Ce qu'il raconte le jour même (complément a) ──────────────────────────


@pytest.mark.parametrize("told", [True, False])
def test_what_he_tells_the_same_day_takes_up_an_all_day_moment(tmp_path, told):
    """Lundi matin : « je l'emmène chez le véto ce midi » (un moment « jour entier » : son instant est la fin
    d'après-midi). À 13 h 41 : « le véto dit insuffisance rénale » — c'est en reparler. Mardi, elle ne lui demande
    pas comment s'est passé le véto. Contre-exemple : un « coucou » à 13 h 41 ne raconte rien — mardi, c'est à
    demander."""
    script = Script()

    async def scenario(kernel):
        await befriend(kernel, "ext_1", social_c.FRIEND)
        await chat(kernel, "ext_1", ["Pixel est tout mou, je l'emmène chez le véto ce midi"], channel="external",
                   display_name="Sam")
        await note(kernel, "son rendez-vous chez le véto pour Pixel", at_paris(2026, 10, 5, 18, 0), "ext_1",
                   all_day=True, importance=0.7)
        await until(kernel, at_paris(2026, 10, 5, 13, 41))
        await chat(kernel, "ext_1", ["le véto dit insuffisance rénale" if told else "coucou"], channel="external",
                   display_name="Sam")
        await until(kernel, at_paris(2026, 10, 6, 22, 30))
        await chat(kernel, "ext_1", ["salut"], channel="external", display_name="Sam")
        return events(kernel, memory_c.MOMENT_FOLLOWED.name)

    followed = run(tmp_path, scenario, script)
    life = section(script.prompts("reply", "ext_1")[-1][1], LIFE)
    if told:
        assert len(followed) == 1 and followed[0].data.by == "ext_1"
        assert "véto" not in life, "il le lui a raconté le jour même : rien à redemander"
    else:
        assert followed == [] and "véto" in life and "c'est passé" in life


# ── De quoi lui parler : ce qui pèse le plus (complément b) ───────────────


@pytest.mark.parametrize("weighty", [True, False])
def test_what_she_could_talk_about_starts_from_what_weighs_most(tmp_path, weighty):
    """Sam lui a dit, sans que le modèle nomme la source, que son chat a une insuffisance rénale ; il a un
    rendez-vous chez le dentiste demain. Ce dont elle pourrait lui parler : son chat, pas « un mot pour
    l'encourager » pour le dentiste. Contre-exemple : ce qu'il a dit est anodin — le rendez-vous de demain passe
    devant."""

    def extract(prompt):
        said = _messages(prompt)
        if "véto" not in said:
            return None
        text = "Pixel, le chat de Sam, souffre d'insuffisance rénale" if weighty else "Sam est allé chez le véto"
        return {"croyances": [{"texte": text, "personnes": [token(prompt, "Sam")], "importance": 3 if weighty else 1,
                               "messages": seq_of(prompt, "véto")}]}

    script = Script(extract=extract)

    async def scenario(kernel):
        await befriend(kernel, "ext_1", social_c.FRIEND)
        await chat(kernel, "ext_1", ["le véto dit insuffisance rénale" if weighty else "je sors de chez le véto",
                                    "à plus"], channel="external", display_name="Sam")
        await asyncio.sleep(10 * MINUTE / US)
        await note(kernel, "son rendez-vous chez le dentiste", kernel.mind.clock.now() + 20 * HOUR, "ext_1")
        matter = kernel.mind.frame().get(needs_c.MATTER("ext_1"))
        return matter, kernel.mind.store.content([matter.ref]) if matter else {}

    matter, texts = run(tmp_path, scenario, script)
    assert matter is not None
    if weighty:
        assert matter.kind == needs_c.TOLD_MATTER and "insuffisance rénale" in texts[matter.ref]
    else:
        assert matter.kind == needs_c.MOMENT_MATTER and "dentiste" in texts[matter.ref]


def test_a_situation_that_lasts_is_spoken_of_in_the_present():
    """« son chat malade » depuis trois jours n'est ni « à venir » ni « passé » : elle prend de ses nouvelles (« Ce
    qui lui est arrivé, il y a 3 jours… comment ça s'est passé ? » sonnait faux). Contre-exemple : un moment
    ponctuel passé garde sa question."""
    now = at_paris(2026, 10, 8, 18, 0)
    frame = SimpleNamespace(now=now, root=None, env=SimpleNamespace(tz_of=lambda root: PARIS))
    lasting = needs_c.Matter(needs_c.MOMENT_MATTER, "r", now - 3 * DAY, ("ext_1",), ongoing=True)
    done = needs_c.Matter(needs_c.MOMENT_MATTER, "r", now - 3 * DAY, ("ext_1",))
    assert _lead(lasting, frame, "« Sam »").startswith("Ce que « Sam » vit en ce moment, depuis 3 jours")
    assert "comment ça s'est passé" in _lead(done, frame, "« Sam »")


def test_an_upcoming_moment_she_already_mentioned_is_not_brought_up_again(tmp_path):
    """« Demain, c'est ton anniversaire » ne se redit pas à chaque réponse de la même conversation (sonde réelle du
    2026-10-03 : trois fois de suite, à « ouais », « bof », « je sais pas »). Contre-exemple : avant qu'elle en ait
    parlé, le moment est là sans remarque."""
    def reply(message, req):
        if message == "ouais":
            return "Demain c'est ton anniversaire, tu fais quelque chose ? [EMOTION:happy:0.4]"
        return "hmm, je vois [EMOTION:neutral:0.3]"

    script = Script(reply=reply)

    async def scenario(kernel):
        await connect(kernel, "user_1", "Sam")
        await befriend(kernel, "user_1", social_c.FRIEND)
        await note(kernel, "son anniversaire", kernel.mind.clock.now() + 26 * HOUR, "user_1", all_day=True,
                   festive=True)
        await chat(kernel, "user_1", ["ouais", "bof", "je sais pas"])

    run(tmp_path, scenario, script)
    life = [section(t, "CE QUI SE PASSE DANS SA VIE") for _r, t in script.prompts("reply", "user_1")]
    assert "anniversaire" in life[0] and "déjà parlé" not in life[0]
    assert "tu lui en as déjà parlé tout à l'heure" in life[1] and "tu lui en as déjà parlé" in life[2]
