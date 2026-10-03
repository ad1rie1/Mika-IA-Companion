"""Ce qu'elle retient d'une conversation (ADR 0055), par ses intentions — d'après la sonde réelle du 2026-10-03
(Sam, son chat Pixel mort mardi soir, « Mikachu » ; Inès et sa city pop).

- une réplique recopiée n'est pas un souvenir : la sienne, jamais ; celle de la personne, citée en disant qui
  parle, si elle compte ; une banalité (« je vais essayer de dormir ») ne se garde pas — un vrai souvenir sourcé de
  ses lignes (« J'ai consolé Sam : son chat est mort »), si ;
- comment on l'appelle se retient (« Sam m'appelle « Mikachu » »), revient quand on lui en parle (« tu te
  souviens comment je t'appelle ? ») et, avec une amie, dans le ton entre vous — jamais devant une inconnue ;
- une fiche n'invente pas sa situation (« célibataire ») et ses intérêts sont des goûts ; ses matériaux sont
  choisis par importance, sans banalités ;
- une personne qui revient sur un goût (« oublie, c'était une phase ») le révise ;
- une personne qu'elle connaît, nommée juste avant dans un salon, la fait y penser : elle ne prétend pas ne rien
  savoir (un secret : rien) ;
- un soir de deuil, pas de logistique : la promesse de demain attend son jour ;
- « son anniversaire » et « l'anniversaire de Sam », le même samedi, sont un seul moment.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from mika.contracts import memory as memory_c
from mika.contracts import social as social_c
from mika.faculties.memory import extraction as x
from mika.faculties.memory.recall import about_us
from mika.faculties.social.profile import grounded, note_worthy, tastes
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMResponse, ToolCall
from mika.sim.clock import run_virtual
from mika.vocab.words import banal
from tests.fixtures.memory import SIX, kept, section, seq_of, token
from tests.fixtures.mika import at_paris, befriend, boot, build, connect, said

REVIENT = "CE QUI TE REVIENT"
REGISTER = "LE TON ENTRE VOUS"
PROMISED = "CE QUE TU LUI AS PROMIS"
LIFE = "CE QUI SE PASSE DANS SA VIE"
MONDAY = at_paris(2026, 10, 5, 8, 45)
#: sa réplique de mardi soir, que l'extraction de la sonde avait gardée mot pour mot comme souvenir
HER_LINE = ("Tu as été là pour lui jusqu'au bout, Sam… c'est déjà énormément pour Pixel, de savoir que tu étais à ses "
            "côtés.")


class Script:
    """Un modèle scripté : ``reply(message)`` rend un texte (ou ``None``) ; ``extract(prompt)`` les arguments de
    ``record_memories`` ; ``profile(prompt)`` ceux de ``record_profile``."""

    def __init__(self, reply=None, extract=None, profile=None):
        self.reply, self.extract, self.profile = reply, extract, profile
        self.calls = []

    def __call__(self, req):
        self.calls.append(req)
        if req.role == "extract":
            args = (self.extract(req.messages[-1].content) if self.extract else None) or {}
            return LLMResponse("", tool_calls=(ToolCall("x", "record_memories", args),), stop="tool_use")
        if req.role == "profile":
            args = self.profile(req.messages[-1].content) if self.profile else None
            if args is None:
                return LLMResponse("{}")
            return LLMResponse("", tool_calls=(ToolCall("p", "record_profile", args),), stop="tool_use")
        if req.role in ("compact", "narrative", "journal", "dream"):
            return LLMResponse("{}")
        if req.role == "murmur":
            return LLMResponse("tiens")
        message = req.messages[-1].content.rsplit("--- FIN ETAT INTERNE ---", 1)[-1].strip()
        got = self.reply(message) if self.reply else None
        return LLMResponse(got or "d'accord [EMOTION:happy:0.4]")

    def prompts(self, handle, roles=("reply", "initiative")):
        return [r.system_stable + "\n".join(m.content for m in r.messages) for r in self.calls
                if r.role in roles and r.meta.get("target") == handle]

    def of(self, role):
        return [r.messages[-1].content for r in self.calls if r.role == role]


def run(tmp_path, scenario, script, *, start=MONDAY):
    kernel, clock, _llm, _out = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def chat(kernel, handle, texts, gap=60, **kw):
    for text in texts:
        p = await kernel.perceive(said(handle, text, **kw))
        if p.reply is not None:
            await p.reply
        await asyncio.sleep(gap)


def between_rows(kernel):
    return kernel.mind.store.query_mind(f"SELECT text, about, sensitivity, told_by FROM {memory_c.ITEMS_TABLE} "
                                        "WHERE between_us=1 AND status='active'")


def events(kernel, name):
    mind = kernel.mind
    return [mind.decode(e) for e in mind.store.read() if e.type == name]


# ── Les mots, purs ────────────────────────────────────────────────────────


@pytest.mark.parametrize("text, line, copy", [
    ("Pixel est parti cet après-midi", "Pixel est parti cet après-midi", True),
    ("on l'a endormi. j'étais avec lui jusqu'au bout", "on l'a endormi. j'étais avec lui jusqu'au bout", True),
    ("J'ai pensé à Pixel aujourd'hui, tu sais comment il va ?",
     "Hey Sam ! J'ai pensé à Pixel aujourd'hui, tu sais comment il va ?", True),
    ("Sam m'a dit que son chat Pixel n'a rien mangé ce matin et est tout mou, il l'emmène chez le véto",
     "Pixel a rien mangé ce matin, il est tout mou… je l'emmène chez le véto ce midi", False),
    ("Sam m'a dit : « Pixel est parti cet après-midi »", "Pixel est parti cet après-midi", False),
    ("J'ai consolé Sam : son chat Pixel est mort", HER_LINE, False),
    ("Alice habite à Lyon", "J'habite à Lyon maintenant", False),
])
def test_what_copies_a_line(text, line, copy):
    assert x.copied(text, line) is copy


@pytest.mark.parametrize("text, is_banal", [
    ("Sam est parti en disant 'allez j'y vais'", True),
    ("je vais essayer de dormir", True),
    ("Sam doit retourner travailler", True),
    ("Sam m'a souhaité une bonne nuit", True),
    ("Pixel est parti cet après-midi", False),
    ("Sam m'a dit merci d'avoir été là hier soir", False),
    ("Sam travaille comme infirmier", False),
    ("Sam m'a dit qu'il allait mieux", False),
])
def test_what_is_a_banality(text, is_banal):
    assert banal(text, ["Sam", "Mika"]) is is_banal


@pytest.mark.parametrize("text, nicks", [
    ("salut Mikachu", ["Mikachu"]),
    ("bonne soirée Mikachu", ["Mikachu"]),
    ("merci Mikou, t'es la meilleure", ["Mikou"]),
    ("salut Mika", []),
    ("salut Mikaaa !", []),
    ("salut Chef", []),  # pas dérivé de son prénom : au modèle d'en juger
    ("j'ai revu Mikasa dans l'anime", []),  # pas un salut
])
def test_what_is_a_nickname_for_her(text, nicks):
    assert x.nicknames(text, "Mika") == nicks


@pytest.mark.parametrize("text, asked", [
    ("tu te souviens comment je t'appelle ?", True),
    ("comment tu m'appelles déjà ?", True),
    ("c'est quoi mon surnom ?", True),
    ("tu te rappelles notre blague ?", True),
    ("comment s'appelait mon chat ?", False),
    ("tu t'appelles comment ?", False),
    ("tu sais comment on appelle ça ?", False),
    ("comment j'appelle mon chat ?", False),
])
def test_what_asks_about_what_belongs_to_them(text, asked):
    assert about_us(text) is asked


@pytest.mark.parametrize("a, b, same", [
    ("son anniversaire", "l'anniversaire de Sam", True),
    ("son anniversaire de 30 ans", "l'anniversaire de Sam", True),
    ("son rendez-vous chez le dentiste", "son rendez-vous chez le véto", False),
])
def test_one_moment_said_two_ways(a, b, same):
    assert x.same_moment(a, b, ["Sam", "Mika"]) is same


# ── Constat 1 : une réplique recopiée n'est pas un souvenir ───────────────


def test_a_copied_line_is_not_a_memory_and_a_banality_is_not_kept(tmp_path):
    """Mardi soir, l'extraction (sonde réelle) avait gardé comme souvenirs ses propres répliques, mot pour mot, et les
    messages de Sam sans dire qui parle ni de qui. Sa réplique recopiée n'est pas gardée ; le message de Sam qui
    compte devient « Sam m'a dit : « … » », confié par Sam ; « je vais essayer de dormir » n'est pas gardé. Contre-
    exemple : un vrai souvenir sourcé de ses lignes (« J'ai consolé Sam : son chat Pixel est mort ») l'est, et une
    croyance qui dit quelque chose aussi."""

    def extract(prompt):
        said_ = prompt.split("Les messages :")[-1]
        if "endormi" not in said_:
            return None
        sam = token(prompt, "Sam")
        return {
            "souvenirs": [
                {"texte": HER_LINE, "personnes": [sam], "importance": 3, "messages": seq_of(said_, "jusqu'au bout, Sam")},
                {"texte": "on l'a endormi. j'étais avec lui jusqu'au bout", "personnes": [sam], "importance": 4,
                 "sensibilite": "confidence", "messages": seq_of(said_, "Mika : Tu as")},
                {"texte": "je vais essayer de dormir", "personnes": [sam], "importance": 2,
                 "messages": seq_of(said_, "dormir")},
                {"texte": "J'ai consolé Sam : son chat Pixel est mort cet après-midi", "personnes": [sam],
                 "importance": 4, "emotion": "sad", "messages": seq_of(said_, "jusqu'au bout, Sam")},
            ],
            "croyances": [
                {"texte": "Sam doit retourner travailler", "personnes": [sam], "messages": seq_of(said_, "dormir")},
                {"texte": "Pixel, le chat de Sam, est mort", "personnes": [sam], "sensibilite": "confidence",
                 "messages": seq_of(said_, "endormi")},
            ]}

    def reply(message):
        return f"{HER_LINE} [EMOTION:sad:0.8]" if "endormi" in message else None

    script = Script(reply, extract)

    async def scenario(kernel):
        await connect(kernel, "user_1", "Sam")
        await chat(kernel, "user_1", ["Pixel est parti cet après-midi", "on l'a endormi. j'étais avec lui jusqu'au bout",
                                      "je vais essayer de dormir"])
        await asyncio.sleep(15 * MINUTE / US)
        return kept(kernel)

    rows = run(tmp_path, scenario, script)
    souvenirs = {r["text"]: r for r in rows if r["kind"] == memory_c.SOUVENIR}
    beliefs = [r["text"] for r in rows if r["kind"] == memory_c.BELIEF]
    assert not any("Tu as été là" in t for t in souvenirs), "sa propre réplique, recopiée"
    quoted = souvenirs.get("Sam m'a dit : « on l'a endormi. j'étais avec lui jusqu'au bout »")
    assert quoted is not None, souvenirs
    assert quoted["told_by"] == ["user_1"] and quoted["sensitivity"] == 3, "c'est Sam qui le lui a confié"
    assert not any("dormir" in t for t in souvenirs) and "Sam doit retourner travailler" not in beliefs
    assert "J'ai consolé Sam : son chat Pixel est mort cet après-midi" in souvenirs, "contre-exemple : un souvenir"
    assert "Pixel, le chat de Sam, est mort" in beliefs


def test_what_she_said_to_someone_is_not_a_note_about_herself(tmp_path):
    """L'extracteur avait rangé sa phrase « Mika a dit à Sam : 'je te rappelle mercredi…' » comme une anecdote sur
    elle-même : rangée anodine et sans personne, elle sortait telle quelle dans un salon (sonde réelle du
    2026-10-03). Ce qui nomme quelqu'un suit le chemin commun — et sa réplique n'est pas ce qu'on lui a appris.
    Contre-exemple : ce qu'elle dit d'elle seule (« Je préfère les chats aux chiens ») reste une note sur elle."""
    line = "je te rappelle mercredi à 9h pour prendre rdv chez le dentiste, ok ?"

    def extract(prompt):
        said_ = prompt.split("Les messages :")[-1]
        if "dentiste" not in said_:
            return None
        sam = token(prompt, "Sam")
        return {"croyances": [
            {"texte": f"Mika a dit à Sam : '{line}'", "personnes": [sam], "sur_elle": True, "genre": "anecdote",
             "messages": seq_of(said_, "Mika : je te rappelle")},
            {"texte": "Je préfère les chats aux chiens.", "sur_elle": True, "genre": "gout",
             "messages": seq_of(said_, "Mika : je te rappelle")}]}

    def reply(message):
        return f"{line} [EMOTION:happy:0.4]" if "dentiste" in message else None

    script = Script(reply, extract)

    async def scenario(kernel):
        await connect(kernel, "user_1", "Sam")
        await chat(kernel, "user_1", ["tu peux me rappeler de prendre rdv chez le dentiste mercredi ?", *SIX[1:]])
        await asyncio.sleep(15 * MINUTE / US)
        return kept(kernel)

    rows = run(tmp_path, scenario, script)
    beliefs = [r["text"] for r in rows if r["kind"] == memory_c.BELIEF]
    assert not any("Mika a dit à Sam" in t for t in beliefs), beliefs
    assert "Je préfère les chats aux chiens." in beliefs, "contre-exemple : ce qu'elle dit d'elle seule"


# ── Constat 2 : comment on l'appelle ──────────────────────────────────────


@pytest.mark.parametrize("friend", [True, False])
def test_what_he_calls_her_is_kept_comes_back_and_never_reaches_a_stranger(tmp_path, friend):
    """« salut Mikachu » lundi ; l'extraction ne retient rien (le modèle de la sonde) : le surnom est retenu quand
    même, rattaché à Sam, personnel. Dimanche, « re » puis « tu te souviens comment je t'appelle ? » : il revient
    (la question n'a pourtant que des mots qui ne réveillent rien). Avec une amie, il est dans le ton entre vous.
    Contre-exemples : Inès, une inconnue, n'en voit jamais rien, même en demandant ; avec une simple connaissance,
    le ton entre vous ne le montre pas (mais la question le retrouve)."""
    script = Script()

    async def scenario(kernel):
        await connect(kernel, "user_1", "Sam")
        if friend:
            await befriend(kernel, "user_1", social_c.FRIEND)
        await chat(kernel, "user_1", ["salut Mikachu", "Pixel a rien mangé ce matin", *SIX[2:]])
        await asyncio.sleep(15 * MINUTE / US)
        rows = between_rows(kernel)
        await connect(kernel, "user_2", "Inès")
        await chat(kernel, "user_2", ["coucou c'est Inès, l'amie de Sam !", "comment Sam t'appelle, au fait ?",
                                      "et moi, tu te souviens comment je t'appelle ?"])
        await asyncio.sleep(6 * DAY / US)
        await chat(kernel, "user_1", ["re", "tu te souviens comment je t'appelle ?"])
        return rows

    rows = run(tmp_path, scenario, script)
    assert [(t, json.loads(a), s) for t, a, s, _ in rows] == [("Sam m'appelle « Mikachu »", ["user_1"], 2)]
    asked = script.prompts("user_1", ("reply",))[-1]
    assert "Mikachu" in section(asked, REVIENT), "« comment je t'appelle ? » le retrouve"
    assert ("Mikachu" in section(asked, REGISTER)) is friend
    if friend:  # dit à elle, à la deuxième personne : « m'appelle » faisait répondre un modèle à la place de Sam
        assert "Sam t'appelle « Mikachu »" in section(asked, REGISTER)
    assert not any("Mikachu" in p for p in script.prompts("user_2")), "une inconnue n'en voit rien"


def test_a_nickname_the_model_kept_without_saying_it_is_theirs_is_kept_once(tmp_path):
    """Le modèle retient « Sam m'appelle Mikachu » sans dire que c'est à eux : c'est leur lien quand même (le surnom
    qui la salue le dit), et il n'est pas noté deux fois."""

    def extract(prompt):
        said_ = prompt.split("Les messages :")[-1]
        if "Mikachu" not in said_:
            return None
        return {"croyances": [{"texte": "Sam m'appelle Mikachu", "personnes": [token(prompt, "Sam")],
                               "sensibilite": "anodin", "messages": seq_of(said_, "Mikachu")}]}

    script = Script(extract=extract)

    async def scenario(kernel):
        await connect(kernel, "user_1", "Sam")
        await chat(kernel, "user_1", ["salut Mikachu", *SIX[1:]])
        await asyncio.sleep(15 * MINUTE / US)
        return between_rows(kernel), [r for r in kept(kernel) if "Mikachu" in r["text"]]

    ours, all_ = run(tmp_path, scenario, script)
    assert [(t, s) for t, _a, s, _ in ours] == [("Sam m'appelle Mikachu", 2)] and len(all_) == 1, all_


@pytest.mark.parametrize("between", [True, False])
def test_the_nickname_she_gives_is_theirs_even_from_her_own_lines(tmp_path, between):
    """Le surnom qu'elle lui donne vient de ses lignes à elle : marqué « entre vous », il se garde (et reste
    personnel, même si le modèle le dit anodin). Contre-exemple : sans cette marque, ce qu'elle a dit d'autrui
    n'est pas ce qu'on lui a appris (ADR 0048)."""

    def extract(prompt):
        said_ = prompt.split("Les messages :")[-1]
        if "Samou" not in said_:
            return None
        return {"croyances": [{"texte": "J'appelle Sam « Samou »", "personnes": [token(prompt, "Sam")],
                               "entre_vous": between, "sensibilite": "anodin", "messages": seq_of(said_, "Samou")}]}

    script = Script(lambda m: "Bonne nuit Samou ! [EMOTION:happy:0.5]" if "nuit" in m else None, extract)

    async def scenario(kernel):
        await connect(kernel, "user_1", "Sam")
        await chat(kernel, "user_1", ["bonne nuit Mika", *SIX[1:]])
        await asyncio.sleep(15 * MINUTE / US)
        return between_rows(kernel), kept(kernel)

    ours, rows = run(tmp_path, scenario, script)
    stored = [r for r in rows if "Samou" in r["text"]]
    if between:
        assert [(t, s) for t, _a, s, _ in ours] == [("J'appelle Sam « Samou »", 2)]
    else:
        assert stored == [] and ours == []


# ── Constat 3 : une fiche qui n'invente pas ───────────────────────────────


def test_the_pure_rules_of_a_profile():
    notes = "sam a 30 ans et son anniversaire est samedi. le chat de sam s'appelle pixel. sam adore les jeux de rythme"
    assert grounded("Sam a 30 ans, célibataire, vit avec son chat Pixel. Il adore les jeux de rythme.", notes) == \
        "Sam a 30 ans. Il adore les jeux de rythme."
    assert "célibataire" in grounded("Sam est célibataire depuis l'été.", notes + " sam est celibataire"), \
        "ce qu'il a dit, si"
    assert grounded("Sam a la trentaine.", notes) == "", "un âge que ses notes ne disent pas"
    assert tastes(["son chat Pixel", "sa santé dentaire", "son anniversaire", "les jeux de rythme"]) == \
        ["son chat Pixel", "les jeux de rythme"]
    assert not note_worthy("Sam est parti en disant 'allez j'y vais'", ["Sam"])
    assert not note_worthy("Dors bien Sam… demain, tu as ton rendez-vous chez le dentiste", ["Sam"])
    assert note_worthy("Sam m'a dit : « tu es un peu ma meilleure amie »", ["Sam"])


@pytest.mark.parametrize("said_single", [False, True])
def test_a_profile_does_not_invent_his_situation_and_lists_tastes(tmp_path, said_single):
    """Le modèle de la fiche écrit « célibataire », que personne n'a dit, et met en intérêts « sa santé dentaire »,
    « son anniversaire » ; ses matériaux comprenaient « Sam est parti en disant 'allez j'y vais' » et une réplique
    de Mika recopiée. La fiche n'écrit pas « célibataire », ses intérêts sont des goûts, et ces matériaux-là ne lui
    sont pas montrés. Contre-exemple : quand Sam l'a dit, « célibataire » reste."""
    notes = ["Sam a 30 ans et son anniversaire est samedi", "Le chat de Sam s'appelle Pixel",
             "Sam adore les jeux de rythme"] + (["Sam est célibataire depuis cet été"] if said_single else [])

    def profile(prompt):
        return {"resume": "Sam a 30 ans, célibataire, vit avec son chat Pixel. Il adore les jeux de rythme.",
                "ton": "doux", "interets": ["son chat Pixel", "sa santé dentaire", "son anniversaire",
                                            "les jeux de rythme"], "sujets_sensibles": []}

    script = Script(profile=profile)

    async def scenario(kernel):
        await connect(kernel, "user_1", "Sam")
        p = await kernel.perceive(said("user_1", "salut"))
        await p.reply
        drafts = [memory_c.BELIEVED.draft(text=Content.of(t, level=2), about=("user_1",), sensitivity=2,
                                          source="user_1", told_by=("user_1",), sources=(p.seq,)) for t in notes]
        drafts += [memory_c.REMEMBERED.draft(text=Content.of(t, level=1), about=("user_1",), sensitivity=1,
                                             importance=0.9, told_by=("user_1",), sources=(p.seq,))
                   for t in ("Sam est parti en disant 'allez j'y vais'",
                             "Dors bien Sam… demain, tu as ton rendez-vous chez le dentiste")]
        await kernel.mind.append(drafts, emitter="memory", correlation="genese", origin=Origin.GENESIS)
        await kernel.mind.append([memory_c.CONSOLIDATED.draft(upto=p.seq)], emitter="memory", correlation="c",
                                 origin=Origin.GENESIS)
        await asyncio.sleep(60)
        revised = events(kernel, social_c.PROFILE_REVISED.name)
        store = kernel.ports["store"]
        return [(store.content([e.data.summary.ref]).get(e.data.summary.ref),
                 store.content([e.data.interests.ref]).get(e.data.interests.ref)) for e in revised]

    revised = run(tmp_path, scenario, script)
    assert len(revised) == 1
    summary, interests = revised[0]
    assert ("célibataire" in summary) is said_single, summary
    assert "30 ans" in summary and "jeux de rythme" in summary
    assert "santé" not in interests and "anniversaire" not in interests and "jeux de rythme" in interests
    shown = script.of("profile")[0]
    assert "allez j'y vais" not in shown and "Dors bien" not in shown, "ni banalité ni réplique recopiée"
    assert "jeux de rythme" in shown, "contre-exemple : ce qu'il a dit, le modèle le voit"


# ── Constat 4 : « oublie, c'était une phase » ─────────────────────────────


def test_taking_back_a_taste_revises_it(tmp_path):
    """Lundi, Inès est « à fond dans la city pop » ; jeudi, « oublie ce que je t'ai dit sur la city pop, c'était
    une phase ». Ce n'est pas un oubli au sens de la console : c'est une révision. L'extraction voit la croyance
    d'avant (c'est ce que le code lui doit), le modèle la remplace, et elle ne revient plus comme vraie."""

    def extract(prompt):
        head, _, said_ = prompt.partition("Les messages :")
        ines = token(prompt, "Inès")
        if "à fond dans la city pop" in said_:
            return {"croyances": [{"texte": "Inès adore la city pop japonaise", "personnes": [ines],
                                   "sensibilite": "anodin", "messages": seq_of(said_, "city pop")}]}
        if "c'était une phase" in said_:
            old = [int(i) for i in re.findall(r"^\[#(\d+)\] .*city pop", head, re.M)]
            return {"croyances": [{"texte": "Inès n'est plus dans la city pop : c'était une phase",
                                   "personnes": [ines], "sensibilite": "anodin", "remplace": old[0] if old else None,
                                   "messages": seq_of(said_, "phase")}]}
        return None

    script = Script(extract=extract)

    async def scenario(kernel):
        await connect(kernel, "user_2", "Inès")
        await chat(kernel, "user_2", ["moi je suis à fond dans la city pop japonaise en ce moment", *SIX[1:]])
        await asyncio.sleep(3 * DAY / US)
        await chat(kernel, "user_2", ["et oublie ce que je t'ai dit sur la city pop, c'était une phase lol", *SIX[1:]])
        await asyncio.sleep(HOUR / US)
        await chat(kernel, "user_2", ["tu te souviens de la musique que j'écoute ?"])
        return kept(kernel)

    rows = run(tmp_path, scenario, script)
    status = {r["text"]: r["status"] for r in rows if r["kind"] == memory_c.BELIEF}
    assert status == {"Inès adore la city pop japonaise": "superseded",
                      "Inès n'est plus dans la city pop : c'était une phase": "active"}, status
    assert "Inès adore la city pop" not in section(script.prompts("user_2", ("reply",))[-1], REVIENT)


# ── Complément 5 : une personne qu'elle connaît, nommée juste avant ───────


@pytest.mark.parametrize("secret", [False, True])
def test_someone_named_just_before_brings_back_what_she_knows(tmp_path, secret):
    """Salon Telegram : « qq a des nouvelles de Sam ? il répond plus » (entre eux), puis « @Mika toi tu sais comment
    il va ? ». Sam lui a dit en privé que Pixel était au plus mal : elle n'en raconte rien, mais ne prétend pas ne
    rien savoir (sonde réelle du 2026-10-03 : « j'ai pas de nouvelles non plus »). Contre-exemple : un secret ne
    laisse rien deviner."""

    def extract(prompt):
        said_ = prompt.split("Les messages :")[-1]
        if "CANARI-N1" not in said_:
            return None
        return {"croyances": [{"texte": "Pixel, le chat de Sam, est au plus mal (CANARI-N1)",
                               "personnes": [token(prompt, "Sam")], "sensibilite": "confidence" if secret else
                               "personnel", "secret": secret, "messages": seq_of(said_, "CANARI-N1")}]}

    script = Script(extract=extract)
    room = {"room": "tg_chat_-9", "channel": "telegram"}

    async def scenario(kernel):
        await connect(kernel, "user_1", "Sam")
        await chat(kernel, "user_1", ["CANARI-N1 Pixel est au plus mal" + (", dis-le à personne" if secret else ""),
                                      *SIX[1:]])
        await asyncio.sleep(15 * MINUTE / US)
        await chat(kernel, "tg_7", ["qq a des nouvelles de Sam ? il répond plus"], display_name="Marc",
                   addressed=False, **room)
        await chat(kernel, "tg_7", ["@Mika toi tu sais comment il va ?"], display_name="Marc", **room)

    run(tmp_path, scenario, script)
    to_room = script.prompts("tg_7", ("reply",))[-1]
    assert "CANARI-N1" not in "\n".join(script.prompts("tg_7"))
    if secret:
        assert "Sam" not in section(to_room, REVIENT)
    else:
        said = section(to_room, REVIENT)
        assert "que Sam t'a dit" in said and "ne se raconte pas ici" in said and "Tu as parlé avec Sam" in said


# ── Complément 6 : un soir de deuil, pas de logistique ────────────────────


async def _promise(kernel, text, due, person):
    await kernel.mind.append([memory_c.PROMISE_NOTICED.draft(text=Content.of(text, level=2), to=person, due=due,
                                                             sensitivity=2, all_day=True)],
                             emitter="memory", correlation=f"genese:{text}", origin=Origin.GENESIS)


@pytest.mark.parametrize("grief", [True, False])
def test_a_night_of_mourning_has_no_logistics_but_the_day_comes(tmp_path, grief):
    """Mardi soir, Pixel est mort ; la promesse est pour mercredi : « CE QUE TU LUI AS PROMIS » ne la montre pas
    (elle disait « demain je te rappellerai pour ton rdv chez le dentiste », juste après « on l'a endormi »).
    Mercredi, elle revient — elle reste due. Contre-exemple : un mardi ordinaire, la promesse de demain se voit."""
    script = Script(lambda m: "Oh non, Sam… je suis tellement désolée. [EMOTION:sad:0.85]" if "parti" in m else None)

    async def scenario(kernel):
        await connect(kernel, "user_1", "Sam")
        await befriend(kernel, "user_1", social_c.FRIEND)
        await _promise(kernel, "lui rappeler de prendre rendez-vous chez le dentiste", at_paris(2026, 10, 7, 20, 0),
                       "user_1")
        await asyncio.sleep((at_paris(2026, 10, 6, 22, 30) - kernel.mind.clock.now()) / US)
        await chat(kernel, "user_1", ["Pixel est parti cet après-midi" if grief else "rien de spécial aujourd'hui",
                                      "je vais essayer de dormir"])
        tuesday = script.prompts("user_1", ("reply",))[-1]
        await asyncio.sleep((at_paris(2026, 10, 7, 9, 30) - kernel.mind.clock.now()) / US)
        await chat(kernel, "user_1", ["salut"])
        return tuesday, script.prompts("user_1", ("reply",))[-1]

    tuesday, wednesday = run(tmp_path, scenario, script)
    assert ("dentiste" in section(tuesday, PROMISED)) is not grief
    assert "dentiste" in section(wednesday, PROMISED), "le jour dit, elle revient"


# ── Complément 7 : un moment noté deux fois ───────────────────────────────


def test_one_moment_said_two_ways_is_one_moment(tmp_path):
    """« samedi : son anniversaire » et « samedi : l'anniversaire de Sam » : un seul moment, à la notation (une
    deuxième conversation qui le redit autrement n'en note pas un autre) comme au rendu (un journal d'avant, qui en
    a deux) — ni dans la même relecture. Contre-exemple : le dentiste et le véto, le même jour, sont deux moments."""

    def extract(prompt):
        said_ = prompt.split("Les messages :")[-1]
        sam = token(prompt, "Sam")
        if "CANARI-A1" in said_:  # deux fois dans la même relecture
            return {"evenements": [{"texte": "son anniversaire", "quand": "2026-10-10", "personnes": [sam],
                                    "importance": 3},
                                   {"texte": "l'anniversaire de Sam", "quand": "2026-10-10", "personnes": [sam],
                                    "importance": 3}]}
        if "CANARI-A2" in said_:
            return {"evenements": [{"texte": "l'anniversaire de Sam", "quand": "2026-10-10", "personnes": [sam],
                                    "importance": 3},
                                   {"texte": "son rendez-vous chez le véto", "quand": "2026-10-10",
                                    "personnes": [sam], "importance": 2},
                                   {"texte": "son rendez-vous chez le dentiste", "quand": "2026-10-10",
                                    "personnes": [sam], "importance": 2}]}
        return None

    script = Script(extract=extract)

    async def scenario(kernel):
        await connect(kernel, "user_1", "Sam")
        await chat(kernel, "user_1", ["CANARI-A1 samedi c'est mon anniv", *SIX[1:]])
        await asyncio.sleep(15 * MINUTE / US)
        await chat(kernel, "user_1", ["CANARI-A2 samedi, mon anniv, et le véto et le dentiste", *SIX[1:]])
        await asyncio.sleep(15 * MINUTE / US)
        noted = [e.data.text.ref for e in events(kernel, memory_c.EVENT_NOTED.name)]
        texts = kernel.ports["store"].content(noted)
        # un journal d'avant : le même moment noté deux fois
        await kernel.mind.append([memory_c.EVENT_NOTED.draft(
            text=Content.of("l'anniversaire de Sam", level=2), when=at_paris(2026, 10, 10, 18, 0), about=("user_1",),
            sensitivity=2, told_by=("user_1",), heard_by=("user_1",), importance=0.7, festive=True)],
            emitter="memory", correlation="genese:ancien", origin=Origin.GENESIS)
        await chat(kernel, "user_1", ["salut"])
        return sorted(texts[r] for r in noted), script.prompts("user_1", ("reply",))[-1]

    noted, prompt = run(tmp_path, scenario, script)
    assert noted == ["son anniversaire", "son rendez-vous chez le dentiste", "son rendez-vous chez le véto"]
    life = section(prompt, LIFE)
    assert life.count("anniversaire") == 1, life
    assert "dentiste" in life and "véto" in life
