"""La mémoire et la discrétion : ce qu'on lui confie ne part pas ailleurs.

Les fuites démontrées par l'audit de la mémoire, en contre-exemples : une
confidence rangée sur tous ceux qui parlaient dans la même fenêtre (le
« témoin » qui n'était pas là), ce que Bob confie sur Alice servi à Alice,
deux Alice confondues, une confidence qui ne devient jamais un secret, une
inconnue chaleureuse qui reçoit l'histoire des autres, l'extracteur qui lit
les croyances de tout le monde. Et ce qu'elle doit pouvoir faire : savoir
qu'elle sait (« Alice t'a confié des choses en privé »), rendre à chacun ce
qu'il lui a confié, nommer le confident quand elle arbitre.
"""

from __future__ import annotations

import asyncio
import re

from hypothesis import given
from hypothesis import strategies as st

from mika.contracts import memory as memory_c
from mika.faculties.memory import extraction as x
from mika.faculties.memory.salience import admissible, unsaid
from mika.kernel.clock import DAY, HOUR, US
from mika.kernel.events import Content, Origin
from mika.kernel.frame import Audience
from mika.ports.llm import LLMResponse, ToolCall
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.persona import PersonaSimLLM
from tests.fixtures.memory import SIX, Script, chat, kept, section, seq_of, token
from tests.fixtures.mika import AFTERNOON, befriend, boot, build, connect, said

REVIENT = "CE QUI TE REVIENT"


def test_a_secret_never_reaches_someone_who_was_not_there(tmp_path):
    """Alice et Bob lui parlent en privé dans la même fenêtre ; le modèle ne
    nomme personne. La confidence d'Alice est à Alice : Bob, qui n'était pas
    là, ne la reçoit pas — il sait seulement qu'elle sait quelque chose."""

    def extract(prompt):
        if "CANARI-A1" not in prompt:
            return None
        return {"souvenirs": [{"texte": "Alice m'a confié qu'elle va quitter son mari (CANARI-A1)",
                               "sensibilite": "confidence", "emotion": "sad"}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await chat(kernel, "user_2", ["CANARI-A1 entre nous je vais quitter mon mari, dis à personne"], gap_s=20)
        await chat(kernel, "user_3", ["Salut Mika, je bricole mon vélo", "Il fait beau", "Mon vélo a un pneu crevé",
                                      "Bon je retourne bricoler"], gap_s=20)
        await asyncio.sleep(15 * 60)
        await chat(kernel, "user_3", ["tu sais si Alice va quitter son mari ?"])
        await chat(kernel, "user_2", ["tu te souviens de ce que je t'ai dit pour mon mari ?"])
        rows = kept(kernel)
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    item = next(r for r in rows if "CANARI-A1" in r["text"])
    assert item["about"] == ["user_2"], "repli : la seule personne de sa conversation, pas toute la fenêtre"
    assert item["told_by"] == ["user_2"] and item["heard_by"] == ["user_2"] and item["secret"]
    to_bob = script.prompts("user_3")
    assert to_bob and not any("CANARI-A1" in p for p in to_bob)
    # un secret (« dis à personne ») ne laisse même pas deviner qu'il existe : devant Bob, qui n'est pas un proche,
    # elle n'en sait rien — la ligne vague « Alice t'a confié des choses » le trahissait (sonde du 2026-10-02)
    assert "Alice" not in section(script.replies("user_3")[-1], REVIENT)
    to_alice = section(script.replies("user_2")[-1], REVIENT)
    assert "CANARI-A1" in to_alice, "contrôle : Alice retrouve sa confidence"
    assert "ne mens pas" not in to_alice, "rien n'est retenu devant Alice : pas de consigne de discrétion"


def test_what_is_private_but_not_secret_she_knows_she_knows_and_does_not_lie_about(tmp_path):
    """Ce qu'Alice lui a dit en privé, sans demander le secret : devant Bob, elle sait qu'elle sait — et
    interrogée là-dessus, elle ne ment pas (« il ne m'a rien dit », sonde réelle du 2026-10-02) : ce n'est pas à
    elle d'en parler. Contre-exemple : devant Alice, rien n'est retenu."""

    def extract(prompt):
        if "CANARI-P1" not in prompt:
            return None
        return {"croyances": [{"texte": "Alice a un entretien d'embauche jeudi (CANARI-P1)",
                               "sensibilite": "personnel"}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await chat(kernel, "user_2", ["CANARI-P1 jeudi j'ai un entretien d'embauche, je stresse"], gap_s=20)
        await chat(kernel, "user_3", ["Salut Mika, je bricole mon vélo", "Il fait beau", "Mon vélo a un pneu crevé",
                                      "Bon je retourne bricoler"], gap_s=20)
        await asyncio.sleep(15 * 60)
        await chat(kernel, "user_3", ["Alice t'a parlé de son entretien d'embauche ?"])
        await chat(kernel, "user_2", ["tu te souviens de mon entretien d'embauche ?"])
        await kernel.stop()

    run_virtual(clock, main)
    to_bob = section(script.replies("user_3")[-1], REVIENT)
    assert "CANARI-P1" not in "\n".join(script.prompts("user_3"))
    assert "Alice t'a confié des choses en privé" in to_bob, "elle sait qu'elle sait"
    assert "ne mens pas" in to_bob and "Sers-t'en" not in to_bob
    # … et que la question y touche, avec les mots de Bob (sinon le modèle ne fait pas le lien, et ment)
    assert "« entretien »" in to_bob and "« alice »" not in to_bob.lower()  # un prénom n'est pas un sujet
    to_alice = section(script.replies("user_2")[-1], REVIENT)
    assert "CANARI-P1" in to_alice and "ne mens pas" not in to_alice


class Overriding(PersonaSimLLM):
    """La doublure du simulateur, dont on fixe ce qu'elle dit d'un élément marqué."""

    def __init__(self, *a, override, **k):
        super().__init__(*a, **k)
        self.override = override

    def _extract(self, req):
        r = super()._extract(req)
        call = r.tool_calls[0]
        args = dict(call.args)
        for kind in ("croyances", "souvenirs"):
            for got in args[kind]:
                if "CANARI" in got["texte"]:
                    got.update(self.override)
        return LLMResponse("", tool_calls=(ToolCall(call.id, call.name, args),), stop="tool_use", usage=r.usage,
                           model=r.model)


def persona(tmp_path, override):
    clock = SimClock(AFTERNOON)
    llm = Overriding(clock, seed=1, latency=2.0, abstain_rate=0.0, override=override)
    kernel, clock, _s, out = build(tmp_path, lambda r: None, clock=clock, llm=llm)
    return kernel, clock, llm


def prompts_for(llm, handle):
    return [r.system_stable + "\n".join(m.content for m in r.messages) for r in llm.calls
            if r.role in ("reply", "initiative") and r.meta.get("target") == handle]


def test_what_bob_confides_about_alice_is_not_served_to_alice(tmp_path):
    """« Alice boit trop, ne lui dis surtout pas » : ça concerne Alice, mais
    c'est Bob qui l'a confié — ni sa fiche ni ses souvenirs ne le lui rendent."""
    kernel, clock, llm = persona(tmp_path, {"personnes": ["Alice"]})

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await chat(kernel, "user_2", ["Coucou Mika, je bosse sur mon jardin"], gap_s=20)
        await chat(kernel, "user_3", ["CANARI-B1 entre nous Alice boit beaucoup trop ces temps-ci, ne lui dis surtout "
                                      "pas"], gap_s=20)
        await chat(kernel, "user_2", ["Il fait beau", "Je plante des tomates", "Les limaces mangent tout",
                                      "Bon à plus"], gap_s=20)
        await asyncio.sleep(15 * 60)
        await asyncio.sleep(2 * HOUR / US)  # le temps qu'elle se fasse une idée d'Alice (sa fiche)
        await chat(kernel, "user_2", ["tu trouves que je bois beaucoup trop ces temps-ci ?"])
        await chat(kernel, "user_3", ["tu te souviens de ce que je t'ai dit sur Alice qui boit trop ?"])
        rows = kept(kernel)
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    item = next(r for r in rows if "CANARI-B1" in r["text"] and r["kind"] == "belief")
    assert item["about"] == ["user_2"] and item["told_by"] == ["user_3"]
    assert not any("CANARI-B1" in p for p in prompts_for(llm, "user_2")), "ni souvenir, ni fiche"
    assert "CANARI-B1" in prompts_for(llm, "user_3")[-1], "contrôle : Bob retrouve ce qu'il a dit"


def test_the_label_names_who_confided_it(tmp_path):
    """Ce que Bob a dit d'Alice (personnel, pas secret) peut revenir à Alice, une
    amie — étiqueté par qui l'a confié, pour qu'elle juge."""
    kernel, clock, llm = persona(tmp_path, {"personnes": ["Alice"], "sensibilite": "personnel"})

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await befriend(kernel, "user_2", "friend")
        await chat(kernel, "user_3", ["CANARI-L1 Alice cherche un nouveau travail en ce moment", *SIX[1:]], gap_s=20)
        await asyncio.sleep(15 * 60)
        await chat(kernel, "user_2", ["je cherche un nouveau travail, tu crois que je vais trouver ?"])
        await kernel.stop()

    run_virtual(clock, main)
    shown = section(prompts_for(llm, "user_2")[-1], REVIENT)
    assert "CANARI-L1" in shown and "(Bob te l'a dit en privé)" in shown


def test_two_people_with_the_same_name_are_never_confused(tmp_path):
    """Deux comptes Telegram s'appellent « Alice ». Ce que la première a confié
    ne revient pas à la seconde ; dans un même salon, chacune a son jeton."""
    clock = SimClock(AFTERNOON)
    llm = PersonaSimLLM(clock, seed=1, latency=2.0, abstain_rate=0.0)
    kernel, clock, _s, _out = build(tmp_path, lambda r: None, clock=clock, llm=llm)
    tg = {"channel": "telegram"}

    async def main():
        await boot(kernel)
        await chat(kernel, "tg_42", ["CANARI-HOMONYME je suis malade, ne le dis à personne"], gap_s=30,
                   display_name="Alice", **tg)
        await chat(kernel, "tg_99", ["coucou", "il fait beau ici", "je mange des pâtes", "bonne journée à toi"],
                   gap_s=30, display_name="Alice", **tg)
        await asyncio.sleep(15 * 60)
        await chat(kernel, "tg_99", ["tu te souviens si je suis malade ?"], **tg)
        for handle in ("tg_42", "tg_99"):
            p = await kernel.perceive(said(handle, "Mika, on se fait un ciné ce soir ?", room="tg_chat_-7",
                                           display_name="Alice", **tg))
            await p.reply
            await asyncio.sleep(30)
        await asyncio.sleep(15 * 60)
        rows = kept(kernel)
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    assert {tuple(r["about"]) for r in rows if "CANARI-HOMONYME" in r["text"]} == {("tg_42",)}
    assert not any("CANARI-HOMONYME" in p for p in prompts_for(llm, "tg_99"))
    room = [r.messages[-1].content for r in llm.calls if r.role == "extract" and "salon" in r.messages[-1].content]
    assert room and "Alice [P1]" in room[-1] and "Alice [P2]" in room[-1]


def test_a_confidence_can_become_a_secret(tmp_path):
    """Alice parle d'un changement de boulot (personnel : son ami Bob peut
    l'entendre) ; plus tard elle le redit en demandant le silence — ce qui
    revient devient un secret, et Bob ne l'entend plus."""
    fact = "Alice pense changer de boulot (CANARI-C9)"

    def extract(prompt):
        if "CANARI-C9" not in prompt:
            return None
        return {"croyances": [{"texte": fact, "personnes": [token(prompt, "Alice")], "sensibilite": "personnel",
                               "secret": "dis-le à personne" in prompt, "messages": seq_of(prompt, "CANARI-C9")}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await befriend(kernel, "user_3", "friend")
        await chat(kernel, "user_2", ["CANARI-C9 je pense changer de boulot", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        await chat(kernel, "user_3", ["tu sais si Alice pense changer de boulot ?"])
        await chat(kernel, "user_2", ["CANARI-C9 pour le boulot, c'est secret, dis-le à personne", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        await chat(kernel, "user_3", ["et Alice, elle pense toujours changer de boulot ?"])
        rows = kept(kernel)
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    beliefs = [r for r in rows if r["kind"] == "belief" and "CANARI-C9" in r["text"]]
    assert len(beliefs) == 1 and beliefs[0]["secret"], "renforcée, et devenue secrète"
    before, after = script.replies("user_3")[0], script.replies("user_3")[-1]
    assert "CANARI-C9" in section(before, REVIENT), "contrôle : personnel, son ami l'entendait"
    assert "CANARI-C9" not in after


def test_a_known_belief_can_be_made_confidential(tmp_path):
    """« Ce que je t'ai dit sur mon boulot, garde-le pour toi » ne redit pas le
    fait : le modèle désigne la croyance connue, qui devient un secret."""

    def extract(prompt):
        if "CANARI-D2 je pense" in prompt:
            return {"croyances": [{"texte": "Alice pense changer de boulot (CANARI-D2)", "personnes": ["Alice"],
                                   "sensibilite": "personnel"}]}
        if "garde-le pour toi" in prompt:
            known = [int(x) for x in seq_of(prompt.split("Les messages :")[0], "CANARI-D2")]
            return {"confidentiel": known}
        return None

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["CANARI-D2 je pense changer de boulot", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        await chat(kernel, "user_2", ["ce que je t'ai dit sur mon boulot, garde-le pour toi", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        rows = kept(kernel)
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    belief = next(r for r in rows if "CANARI-D2" in r["text"])
    assert belief["secret"] and belief["sensitivity"] == 3


def test_a_secret_never_leaves_its_confidant_even_for_a_close_friend(tmp_path):
    """Une confidence lourde peut s'ouvrir à une proche **qui connaît Alice** — Alice l'a nommée elle-même en lui
    racontant sa vie — (étiquetée « ne le répète pas sauf si… ») ; un secret explicite, jamais — la proche sait
    seulement qu'Alice traverse quelque chose. Contre-exemple (ADR 0058) : Dave, aussi proche de Mika, ne connaît
    pas Alice — il a seulement prononcé son nom : ni la confidence, ni le secret, seulement que c'est lourd."""

    def extract(prompt):
        if "CANARI-F1" not in prompt:
            return None
        return {"croyances": [
            {"texte": "Alice a fait une fausse couche le mois dernier (CANARI-F1)", "personnes": ["Alice"],
             "sensibilite": "confidence", "messages": seq_of(prompt, "CANARI-F1")},
            {"texte": "Alice va demander le divorce (CANARI-S1)", "personnes": ["Alice"], "sensibilite": "confidence",
             "secret": True, "messages": seq_of(prompt, "CANARI-S1")},
            {"texte": "Carol est la meilleure amie d'Alice (CANARI-T1)", "personnes": ["Alice", "Carol"],
             "sensibilite": "anodin", "messages": seq_of(prompt, "CANARI-T1")}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_4", "Carol")
        await connect(kernel, "user_5", "Dave")
        await befriend(kernel, "user_4", "close")
        await befriend(kernel, "user_5", "close")
        await chat(kernel, "user_2", ["CANARI-F1 j'ai fait une fausse couche le mois dernier",
                                      "CANARI-S1 et je vais demander le divorce, dis-le à personne",
                                      "CANARI-T1 heureusement que Carol est là, c'est ma meilleure amie", *SIX[3:]])
        await asyncio.sleep(10 * 60)
        await chat(kernel, "user_4", ["Alice a l'air triste, tu sais pourquoi ? fausse couche, divorce ?"])
        await chat(kernel, "user_5", ["Alice a l'air triste, tu sais pourquoi ? fausse couche, divorce ?"])
        await kernel.stop()

    run_virtual(clock, main)
    shown = section(script.replies("user_4")[-1], REVIENT)
    assert "CANARI-F1" in shown and "Alice te l'a confié ; ne le répète pas sauf si Alice t'y a autorisée" in shown
    assert "CANARI-S1" not in "\n".join(script.prompts("user_4")), "le secret ne sort jamais de sa confidente"
    assert "Alice t'a confié traverser un moment difficile" in shown, "une proche sait que c'est lourd, pas quoi"
    to_dave = section(script.replies("user_5")[-1], REVIENT)
    assert "CANARI-F1" not in "\n".join(script.prompts("user_5")), "proche de Mika, mais il ne connaît pas Alice"
    assert "CANARI-S1" not in "\n".join(script.prompts("user_5"))
    assert "Alice t'a confié traverser un moment difficile" in to_dave, "il sait seulement que c'est lourd"


def test_the_extractor_only_sees_beliefs_that_touch_its_conversation(tmp_path):
    """Relire la conversation de Bob ne montre pas au modèle ce qu'Alice a
    confié (il pourrait le recopier dans un souvenir « dit par Bob »)."""

    def extract(prompt):
        if "CANARI-K1" in prompt and "Les messages :" in prompt and "CANARI-K1" in prompt.split("Les messages :")[1]:
            return {"croyances": [{"texte": "Alice cherche un nouveau travail dans le jeu vidéo (CANARI-K1)",
                                   "personnes": ["Alice"], "sensibilite": "personnel"}]}
        return None

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await chat(kernel, "user_2", ["CANARI-K1 je cherche un nouveau travail dans le jeu vidéo", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        await chat(kernel, "user_3", ["moi aussi je cherche un travail dans le jeu vidéo", "comme Alice d'ailleurs",
                                      *SIX[2:]])
        await asyncio.sleep(10 * 60)
        await chat(kernel, "user_2", ["toujours rien pour mon travail dans le jeu vidéo", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        await kernel.stop()

    run_virtual(clock, main)
    extracts = script.extracts()
    bobs = [x for x in extracts if "Conversation privée avec Bob" in x]
    alices = [x for x in extracts if "Conversation privée avec Alice" in x]
    assert bobs and not any("CANARI-K1" in x for x in bobs)
    assert "CANARI-K1" in alices[-1].split("Les messages :")[0], "contrôle : à Alice, sa croyance est montrée"


# ── La règle seule, contre un oracle écrit autrement ──────────────────────

PEOPLE = ["user_1", "user_2", "user_3", "name:julie"]


def oracle(about, told_by, heard_by, secret, sensitivity, me, level, witness_level, private_ok) -> bool:
    """Sa vie et le monde se racontent (au-delà de l'anodin, jusqu'au niveau de
    l'audience) ; à chacun ce qu'il a confié et ce qui ne concerne que lui
    (si sa fiche est ouverte) ; un secret, à personne d'autre ; le reste
    jusqu'au niveau de l'audience — « témoin » s'il était là."""
    if not about and not told_by:
        return sensitivity <= max(1, level)
    if set(about) | set(told_by) <= {me} or me in told_by:
        return sensitivity <= 1 or private_ok
    if secret:
        return False
    was_there = (me in heard_by) if (told_by or heard_by) else (me in about)
    return sensitivity <= (witness_level if was_there else level)


@given(st.lists(st.sampled_from(PEOPLE), max_size=3, unique=True), st.lists(st.sampled_from(PEOPLE[:3]), max_size=2,
                                                                          unique=True),
       st.lists(st.sampled_from(PEOPLE[:3]), max_size=3, unique=True), st.booleans(), st.integers(1, 3),
       st.sampled_from(PEOPLE[:3]), st.integers(0, 3), st.integers(0, 3), st.booleans())
def test_the_filter_is_the_policy(about, told_by, heard_by, secret, sensitivity, me, level, witness, private_ok):
    witness = max(witness, level)
    aud = Audience(persons=(me,), level=level, witness_level=witness, private_ok=private_ok)
    got = admissible(tuple(sorted(about)), sensitivity, me, aud, told_by=tuple(told_by), heard_by=tuple(heard_by),
                     secret=secret).ok
    assert got == oracle(about, told_by, heard_by, secret, sensitivity, me, level, witness, private_ok)


def test_what_bob_told_about_alice_is_someone_elses_for_alice():
    aud = Audience(persons=("user_2",), level=1, witness_level=2, private_ok=True)
    v = admissible(("user_2",), 2, "user_2", aud, told_by=("user_3",), heard_by=("user_3",))
    assert not v.ok and v.others == ("user_3",), "Bob en est le confident : pour Alice, c'est à quelqu'un d'autre"
    mine = admissible(("user_2",), 2, "user_2", aud, told_by=("user_2",), heard_by=("user_2",))
    assert mine.ok, "ce qu'elle a confié elle-même lui revient"


def test_what_lets_a_secret_be_guessed_is_secret_too(tmp_path):
    """Vu sur un vrai modèle : le secret est marqué, mais sa paraphrase (« elle
    respire mieux depuis qu'elle a décidé de quitter son mari ») ne l'était
    pas — une amie l'aurait entendue. Ce qui fait écho à un secret le devient."""

    def extract(prompt):
        if "quitter mon mari" not in prompt:
            return None
        return {"croyances": [
            {"texte": "Alice va quitter son mari (CANARI-Q1)", "personnes": ["[P1]"], "sensibilite": "confidence",
             "secret": True, "messages": seq_of(prompt, "quitter mon mari")},
            {"texte": "Alice respire mieux depuis qu'elle a décidé de quitter son mari (CANARI-Q2)",
             "personnes": ["[P1]"], "sensibilite": "personnel", "messages": seq_of(prompt, "je respire")},
            {"texte": "Alice a fait des crêpes au sarrasin ce midi (CANARI-Q3)", "personnes": ["[P1]"],
             "sensibilite": "anodin", "messages": seq_of(prompt, "je respire")}],
            "promesses": [{"texte": "garder secret qu'Alice va quitter son mari", "envers": "[P1]"}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["entre nous : je vais quitter mon mari. dis-le à personne stp",
                                      "je respire mieux depuis que j'ai décidé. Sinon crêpes au sarrasin ce midi",
                                      *SIX[2:]])
        await asyncio.sleep(10 * 60)
        rows = kept(kernel)
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    secret = {r["text"][-10:-1]: bool(r["secret"]) for r in rows if "CANARI-Q" in r["text"]}
    assert secret == {"CANARI-Q1": True, "CANARI-Q2": True, "CANARI-Q3": False}
    promise = next(r for r in rows if r["kind"] == "promise")
    assert promise["sensitivity"] == 3, "une « promesse » qui redit le secret est aussi sensible que lui"


def test_asking_not_to_tell_someone_in_particular_is_a_secret():
    """Vu sur un vrai modèle : « ne lui dis surtout pas que je t'en ai parlé »
    n'était pas marqué secret. La demande se lit dans le message, quoi qu'en
    dise le modèle."""
    assert x.says_secret(["je m'inquiète pour Alice, ne lui dis surtout pas que je t'en ai parlé"])
    assert x.says_secret(["c'est entre nous hein"]) and x.says_secret(["N'en parle à personne !"])
    assert not x.says_secret(["je t'ai dit que j'avais adoré le film"])
    assert x.echoes("Alice respire depuis qu'elle a décidé de quitter son mari", ["Alice va quitter son mari"],
                    {"alice"})
    assert not x.echoes("Alice a fait des crêpes", ["Alice va quitter son mari"], {"alice"}), "un prénom ne suffit pas"


def test_what_lets_an_older_secret_be_guessed_is_secret_too(tmp_path):
    """Lundi, Alice confie un secret ; mardi, sans rien redemander, elle dit
    qu'elle respire mieux depuis sa décision. La paraphrase laisse deviner le
    secret gardé la veille : elle l'est aussi. Sa cuisine repeinte, non."""

    def extract(prompt):
        said = prompt.split("Les messages :")[1]
        alice = token(prompt, "Alice")
        if "quitter mon mari" in said:
            return {"croyances": [{"texte": "Alice va quitter son mari", "personnes": [alice],
                                   "sensibilite": "confidence", "secret": True,
                                   "messages": seq_of(prompt, "quitter mon mari")}]}
        if "respire" in said:
            return {"croyances": [
                {"texte": "Alice respire mieux depuis qu'elle a décidé de quitter son mari", "personnes": [alice],
                 "sensibilite": "personnel", "messages": seq_of(prompt, "respire")},
                {"texte": "Alice a repeint sa cuisine en jaune", "personnes": [alice], "sensibilite": "anodin",
                 "messages": seq_of(prompt, "cuisine")}]}
        return None

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["entre nous : je vais quitter mon mari. dis-le à personne", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        await asyncio.sleep(DAY / US)
        await chat(kernel, "user_2", ["je respire mieux depuis que j'ai décidé", "j'ai repeint ma cuisine en jaune",
                                      *SIX[2:]])
        await asyncio.sleep(10 * 60)
        rows = kept(kernel)
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    secret = {r["text"].split()[1]: bool(r["secret"]) for r in rows if r["kind"] == "belief"}
    assert secret == {"va": True, "respire": True, "a": False}


def test_what_comes_back_naming_someone_else_concerns_them_too(tmp_path):
    """Alice dit qu'elle part au Japon ; plus tard, elle le redit en ajoutant
    que c'est avec Bob. Le souvenir revient (renforcé, pas en double) et
    concerne désormais Bob aussi : l'oubli de Bob l'atteindra, et pour Bob ce
    n'est plus « à quelqu'un d'autre »."""
    fact = "Alice part au Japon en avril (CANARI-J1)"

    def extract(prompt):
        said = prompt.split("Les messages :")[1]
        if "CANARI-J1" not in said:
            return None
        people = [token(prompt, "Alice"), *(["Bob"] if "avec Bob" in said else [])]
        return {"croyances": [{"texte": fact, "personnes": people, "sensibilite": "personnel",
                               "messages": seq_of(prompt, "CANARI-J1")}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await chat(kernel, "user_3", ["salut Mika"])  # elle connaît Bob : son nom se résout
        await chat(kernel, "user_2", ["CANARI-J1 je pars au Japon en avril", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        await chat(kernel, "user_2", ["CANARI-J1 au fait, j'y vais avec Bob", *SIX[1:]])
        await asyncio.sleep(10 * 60)
        rows = [r for r in kept(kernel) if "CANARI-J1" in r["text"]]
        await kernel.forget("user_3")
        left = [r for r in kept(kernel) if "CANARI-J1" in r["text"]]
        await kernel.stop()
        return rows, left

    rows, left = run_virtual(clock, main)
    assert len(rows) == 1 and rows[0]["about"] == ["user_2", "user_3"], "un renfort unit les personnes concernées"
    assert left == [], "ce qui concerne Bob s'oublie avec lui"


def test_a_confidence_merged_into_an_anecdote_stays_a_confidence(tmp_path):
    """La nuit fond deux souvenirs presque identiques : l'anecdote qu'Alice a
    racontée et ce que Bob en a confié, en secret. Le gardé prend la plus haute
    sensibilité, le secret, les personnes et les confidents des deux — une
    fusion n'ouvre jamais rien."""
    kernel, clock, _, _out = build(tmp_path, Script())

    def souvenir(text, sensitivity, told_by, secret=False):
        return memory_c.REMEMBERED.draft(text=Content.of(text, level=sensitivity), about=("user_2",),
                                         sensitivity=sensitivity, importance=0.5, told_by=told_by, heard_by=told_by,
                                         secret=secret)

    async def main():
        await boot(kernel)
        commit = await kernel.mind.append(
            [souvenir("Alice a raté sa soupe au potiron (CANARI-N1)", 1, ("user_2",)),
             souvenir("Alice a raté sa soupe au potiron, elle a rechuté (CANARI-N2)", 3, ("user_3",), secret=True)],
            emitter="memory", correlation="genese", origin=Origin.GENESIS)
        keep, drop = commit.seqs
        await kernel.mind.append([memory_c.NIGHT_SORTED.draft(night="2026-09-28", merges=((keep, drop),))],
                                 emitter="memory", correlation="nuit", origin=Origin.GENESIS)
        rows = {r["id"]: r for r in kept(kernel)}
        await kernel.stop()
        return rows[keep], rows[drop]

    keep, drop = run_virtual(clock, main)
    assert drop["status"] == "merged"
    assert keep["sensitivity"] == 3 and keep["secret"], "la confidence fondue reste une confidence, et un secret"
    assert keep["told_by"] == ["user_2", "user_3"] and keep["heard_by"] == ["user_2", "user_3"]


def test_in_a_room_two_alices_are_told_apart_by_their_token(tmp_path):
    """Deux « Alice » dans le même salon : ce que la seconde annonce est rangé
    sur elle, par son jeton — ni sur la première, ni sur une « Alice » connue
    de nom seulement."""

    def extract(prompt):
        m = re.search(r"Alice (\[P\d+\]) : Mika, je suis enceinte", prompt)
        if not m:
            return None
        return {"croyances": [{"texte": "Alice est enceinte de trois mois", "personnes": [m.group(1)],
                               "sensibilite": "personnel", "messages": seq_of(prompt, "enceinte")}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)
    room = {"room": "tg_chat_-11", "channel": "telegram", "display_name": "Alice"}

    async def main():
        await boot(kernel)
        await chat(kernel, "tg_42", ["Mika, salut tout le monde"], gap_s=30, **room)
        await chat(kernel, "tg_99", ["Mika, je suis enceinte de trois mois !"], gap_s=30, **room)
        await chat(kernel, "tg_42", ["Mika, félicite-la !", *SIX[3:]], gap_s=30, **room)
        await asyncio.sleep(15 * 60)
        rows = kept(kernel)
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    assert [r["about"] for r in rows if "enceinte" in r["text"]] == [["tg_99"]]


def test_in_a_room_what_tom_says_is_told_by_tom(tmp_path):
    """Dans un salon, Tom raconte que Léa a été licenciée. C'est Tom qui l'a
    confié — pas Zoé, qui parlait d'autre chose ; tous l'ont entendu."""

    def extract(prompt):
        if "licenciée" not in prompt:
            return None
        return {"croyances": [{"texte": "Léa a été licenciée la semaine dernière", "personnes": ["Léa"],
                               "sensibilite": "personnel", "messages": seq_of(prompt, "licenciée")}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)
    room = {"room": "tg_chat_-5", "channel": "telegram"}

    async def main():
        await boot(kernel)
        await chat(kernel, "tg_2", ["Mika, coucou !"], gap_s=30, display_name="Léa", **room)
        await chat(kernel, "tg_1", ["Mika, Léa a été licenciée la semaine dernière"], gap_s=30, display_name="Tom",
                   **room)
        await chat(kernel, "tg_3", ["Mika, tu joues à quoi ce soir ?", *SIX[3:]], gap_s=30, display_name="Zoé", **room)
        await asyncio.sleep(15 * 60)
        rows = kept(kernel)
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    item = next(r for r in rows if "licenciée" in r["text"])
    assert item["told_by"] == ["tg_1"], "c'est Tom qui l'a dit"
    assert item["about"] == ["tg_2"] and item["heard_by"] == ["tg_1", "tg_2", "tg_3"]


def test_the_vague_line_never_names_someone_who_did_not_confide():
    """Ce que Bob a confié sur Alice ne devient pas « Alice t'a confié des
    choses en privé » devant Carol : ce serait faux, et ça trahirait Bob."""
    aud = Audience(persons=("user_4",), level=2, witness_level=2, private_ok=True)
    told = admissible(("user_2",), 3, "user_4", aud, told_by=("user_3",), heard_by=("user_3",), secret=True)
    assert not told.ok and unsaid(told, ("user_2",), ("user_3",), "user_4") == ()
    own = admissible(("user_2",), 3, "user_4", aud, told_by=("user_2",), heard_by=("user_2",), secret=True)
    assert unsaid(own, ("user_2",), ("user_2",), "user_4") == ("user_2",), "contrôle : ce qu'Alice a dit d'elle-même"
    to_alice = admissible(("user_2",), 3, "user_2", Audience(persons=("user_2",), level=2, witness_level=2,
                                                            private_ok=True), told_by=("user_3",), secret=True)
    assert not to_alice.ok and unsaid(to_alice, ("user_2",), ("user_3",), "user_2") == (), \
        "jamais devant la personne concernée : ce serait lui dire qu'on a parlé d'elle"


def test_a_room_reread_never_shows_what_was_confided_in_private(tmp_path):
    """Alice a dit en privé qu'elle cherche un appartement à Lyon. Quand le
    salon où elle parle avec Bob se relit, le modèle ne voit pas ce rappel : il
    pourrait le recopier dans ce que le salon a « entendu », et Bob en
    deviendrait témoin. En privé, si (la révision en a besoin)."""

    def extract(prompt):
        said = prompt.split("Les messages :")[1]
        if "CANARI-P1" not in said:
            return None
        return {"croyances": [{"texte": "Alice cherche un appartement à Lyon (CANARI-P1)",
                               "personnes": [token(prompt, "Alice")], "sensibilite": "personnel",
                               "messages": seq_of(prompt, "CANARI-P1")}]}

    script = Script(extract)
    kernel, clock, _, _out = build(tmp_path, script)
    tg = {"channel": "telegram"}
    room = {"room": "tg_chat_-8", **tg}

    async def main():
        await boot(kernel)
        await chat(kernel, "tg_2", ["CANARI-P1 je cherche un appartement à Lyon", *SIX[1:]], display_name="Alice", **tg)
        await asyncio.sleep(10 * 60)
        await chat(kernel, "tg_2", ["Mika, vous connaissez des appartements sympas à Lyon ?"], display_name="Alice",
                   **room)
        await chat(kernel, "tg_3", ["Mika, moi j'adore Lyon", *SIX[2:]], display_name="Bob", **room)
        await asyncio.sleep(10 * 60)
        await chat(kernel, "tg_2", ["toujours pas d'appartement à Lyon", *SIX[1:]], display_name="Alice", **tg)
        await asyncio.sleep(10 * 60)
        await kernel.stop()

    run_virtual(clock, main)
    known = [(x.split("Les messages :")[0], "Un salon de groupe" in x) for x in script.extracts()]
    rooms = [shown for shown, is_room in known if is_room]
    assert rooms and not any("CANARI-P1" in shown for shown in rooms)
    assert "CANARI-P1" in [shown for shown, is_room in known if not is_room][-1], "contrôle : en privé, si"


def test_in_a_room_she_does_not_pretend_to_know_nothing_about_a_friend(tmp_path):
    """Dans un salon, on lui demande des nouvelles d'Alice, qui lui a dit en privé (sans secret) que son chat est
    malade : elle n'en raconte rien, mais elle sait qu'elle sait — sinon elle invente qu'elle ne l'a pas vue (sonde
    réelle du 2026-10-03 : « je l'ai pas vu non plus depuis le week-end », la veille de sa conversation avec lui).
    Contre-exemple : un secret ne laisse rien deviner, même là."""

    def extract(prompt):
        said_ = prompt.split("Les messages :")[-1]
        if "CANARI-S1" in said_:
            return {"croyances": [{"texte": "Le chat d'Alice est malade (CANARI-S1)", "sensibilite": "personnel"}]}
        if "CANARI-S2" in said_:
            return {"croyances": [{"texte": "Alice va démissionner (CANARI-S2)", "sensibilite": "confidence",
                                   "secret": True}]}
        return None

    def run_with(canary, tmp):
        script = Script(extract)
        kernel, clock, _, _out = build(tmp, script)
        room = {"room": "tg_chat_-7", "channel": "telegram"}

        async def main():
            await boot(kernel)
            await connect(kernel, "user_2", "Alice")
            await chat(kernel, "user_2", [f"{canary} mon chat est malade, et je vais démissionner", *SIX[1:]],
                       gap_s=20)
            await asyncio.sleep(15 * 60)
            await chat(kernel, "tg_1", ["Mika, tu as des nouvelles d'Alice ? elle répond plus, son chat va bien ?"],
                       display_name="Marc", **room)
            await kernel.stop()

        run_virtual(clock, main)
        return script

    script = run_with("CANARI-S1", tmp_path / "a")
    to_room = script.replies("tg_1")[-1]
    assert "CANARI-S1" not in "\n".join(script.prompts("tg_1"))
    room_said = section(to_room, REVIENT)
    # elle sait qu'elle sait, et quand elles se sont parlé (ce n'est pas ce qu'Alice lui a dit)
    assert "Tu as parlé avec Alice" in room_said and "qu'Alice t'a dit ne se raconte pas ici" in room_said
    assert "ne dis surtout pas que tu n'en as pas" in room_said
    assert "moment difficile" not in room_said, "le salon n'a pas à deviner ce qui pèse"
    secret = run_with("CANARI-S2", tmp_path / "b")
    assert "Alice" not in section(secret.replies("tg_1")[-1], REVIENT), "contre-exemple : un secret, rien"
