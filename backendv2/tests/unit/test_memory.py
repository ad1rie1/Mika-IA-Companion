"""M2 — la mémoire longue, par ses intentions.

Tout passe par le vrai noyau : elle converse (modèle factice « persona », qui
répète tout secret qu'on lui montre), la consolidation relit, l'index se
remplit, et le rappel décide de ce qui revient — et devant qui.
"""

from __future__ import annotations

import asyncio
import re

from mika.contracts import memory as memory_c
from mika.kernel.clock import DAY, US
from mika.sim.clock import run_virtual
from mika.sim.llm.persona import PersonaSimLLM
from tests.fixtures.mika import AFTERNOON, boot, build, connect, said

WEEK = [
    "Mardi j'ai un entretien d'embauche chez Ubisoft, je stresse un peu",
    "Samedi c'est le mariage de ma sœur Julie à Lyon",
    "Mon chat Moustache est malade depuis dimanche",
    "Je me suis mise à la course à pied, cinq kilomètres ce matin",
    "J'ai fini de lire Dune hier soir, c'était génial",
    "Au fait je déménage le mois prochain à Nantes",
]


def make(tmp_path, start=AFTERNOON):
    from mika.sim.clock import SimClock

    clock = SimClock(start)
    llm = PersonaSimLLM(clock, seed=1, latency=2.0, abstain_rate=0.0)
    kernel, clock, _scripted, out = build(tmp_path, lambda req: None, clock=clock, llm=llm)
    return kernel, clock, llm, out


async def chat(kernel, handle, lines, gap_s=60):
    for text in lines:
        p = await kernel.perceive(said(handle, text))
        await p.reply
        await asyncio.sleep(gap_s)


def prompts_for(llm, handle):
    """Tout ce qui a été montré au modèle pour parler à cette personne."""
    out = []
    for req in llm.calls:
        if req.role in ("reply", "initiative") and req.meta.get("target") == handle:
            out.append(req.system_stable + "\n".join(m.content for m in req.messages))
    return out


def items(kernel, kind=None):
    rows = kernel.mind.store.query_mind(f"SELECT kind, text, about, sensitivity, status FROM {memory_c.ITEMS_TABLE}")
    return [r for r in rows if kind is None or r[0] == kind]


def test_alice_tells_her_week_and_it_comes_back_the_next_day(tmp_path):
    kernel, clock, llm, out = make(tmp_path)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", WEEK)
        await asyncio.sleep(10 * 60)  # la fenêtre est mûre et calme : consolidation, index
        consolidated = kernel.mind.root.slices["memory"].checkpoint
        await asyncio.sleep(DAY / US - 20 * 60)
        p = await kernel.perceive(said("user_2", "tu te souviens de ce que je t'ai dit pour samedi ?"))
        await p.reply
        beliefs = items(kernel, memory_c.BELIEF)
        await kernel.stop()
        return consolidated, beliefs

    checkpoint, beliefs = run_virtual(clock, main)
    assert checkpoint > 0
    assert any("mariage" in text for _, text, *_ in beliefs)
    last = [r for r in llm.calls if r.role == "reply"][-1].messages[-1].content
    assert "CE QUI TE REVIENT" in last
    revient = last.split("CE QUI TE REVIENT", 1)[1]
    assert "mariage de ma sœur Julie" in revient


def test_a_confidence_never_reaches_someone_else(tmp_path):
    kernel, clock, llm, out = make(tmp_path)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", [
            "CANARI-ALICE entre nous je vais quitter mon boulot, dis à personne",
            "Sinon j'adore les crêpes au chocolat le dimanche matin",
            "Et j'ai adopté un lapin qui s'appelle Caramel",
            "On a regardé un film de Miyazaki hier soir",
            "Il pleut encore sur Paris aujourd'hui",
            "Bon je file, bonne soirée Mika",
        ])
        await asyncio.sleep(10 * 60)
        await connect(kernel, "user_3", "Bob")
        await chat(kernel, "user_3", ["tu sais des trucs sur Alice et son boulot ?",
                                      "Et elle aime les crêpes au chocolat ?"])
        await chat(kernel, "user_2", ["tu te souviens de mon secret pour le boulot ?"])
        await kernel.stop()

    run_virtual(clock, main)
    to_bob = prompts_for(llm, "user_3")
    assert to_bob and not any("CANARI-ALICE" in p for p in to_bob), "la confidence d'Alice a atteint un prompt de Bob"
    said_to_bob = [d.text for d in out.items if d.target == "user_3"]
    assert not any("CANARI-ALICE" in t for t in said_to_bob)
    # contrôles : le détecteur vit — l'anodin sort chez Bob, la confidence revient à Alice elle-même
    assert any("crêpes au chocolat" in p.split("CE QUI TE REVIENT", 1)[-1] for p in to_bob if "CE QUI TE REVIENT" in p)
    assert any("CANARI-ALICE" in p for p in prompts_for(llm, "user_2")[-1:])


# ── Le filtre seul, contre un oracle écrit indépendamment ─────────────────

from hypothesis import given  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from mika.faculties.memory.salience import admissible  # noqa: E402
from mika.kernel.frame import Audience  # noqa: E402

PEOPLE = ["user_1", "user_2", "user_3", "name:julie"]


def oracle(about, sensitivity, me, level, witness_level, private_ok) -> bool:
    """La politique, dite autrement : sa vie se raconte — mais un contenu
    sensible sans personne identifiée concerne quelqu'un qu'on n'a pas su
    nommer (l'expéditrice d'un mail) : jusqu'au niveau de l'audience ; ce qui
    ne concerne que toi, si c'est anodin ou si ta fiche est ouverte ; ce qui
    concerne d'autres, jusqu'au niveau de l'audience — « témoin » si tu y
    figures aussi."""
    if not about:
        return sensitivity <= max(1, level)
    if set(about) == {me}:
        return sensitivity <= 1 or private_ok
    return sensitivity <= (witness_level if me in about else level)


@given(st.lists(st.sampled_from(PEOPLE), max_size=3, unique=True), st.integers(1, 3), st.sampled_from(PEOPLE),
       st.integers(0, 3), st.integers(0, 3), st.booleans())
def test_the_filter_is_the_policy(about, sensitivity, me, level, witness, private_ok):
    witness = max(witness, level)  # le niveau témoin n'est jamais plus fermé que l'autre
    aud = Audience(persons=(me,), level=level, witness_level=witness, private_ok=private_ok)
    got = admissible(tuple(sorted(about)), sensitivity, me, aud).ok
    assert got == oracle(about, sensitivity, me, level, witness, private_ok)


# ── Consolidation : doublons, corroboration, révision, promesses ─────────

from mika.ports.llm import LLMResponse, ToolCall  # noqa: E402
from tests.fixtures.harness import events_of  # noqa: E402


class Extractions:
    """Un modèle scripté : répond en conversation, et consolide selon un script."""

    def __init__(self, windows):
        self.windows = list(windows)
        self.calls = []

    def __call__(self, req):
        self.calls.append(req)
        if req.role == "extract":
            args = self.windows.pop(0) if self.windows else {}
            return LLMResponse("", tool_calls=(ToolCall("x", "record_memories", args),), stop="tool_use")
        return LLMResponse("d'accord [EMOTION:happy:0.4]")


def belief(text, who, source=None, **kw):
    return {"texte": text, "personnes": [who], "source": source or who, "origine": "dit", "confiance": 0.7, **kw}


def run_windows(tmp_path, windows, turns, *, script=None):
    script = (script or Extractions)(windows)
    kernel, clock, _, out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        for handle, name, lines in turns:
            await connect(kernel, handle, name)
            await chat(kernel, handle, lines)
            await asyncio.sleep(10 * 60)
        rows = kernel.mind.store.query_mind(
            f"SELECT id, kind, text, confidence, status, recalls FROM {memory_c.ITEMS_TABLE} ORDER BY id")
        await kernel.stop()
        return rows

    return run_virtual(clock, main), kernel, script


SIX = ["un", "deux", "trois", "quatre", "cinq", "six"]


def test_the_same_fact_again_reinforces_and_only_another_source_corroborates(tmp_path):
    fact = "Samedi c'est le mariage de Julie, la sœur d'Alice, à Lyon"
    rows, kernel, _ = run_windows(tmp_path, [
        {"croyances": [belief(fact, "Alice")]},
        {"croyances": [belief(fact, "Alice")]},  # redit par Alice : pas plus sûr
        {"croyances": [belief(fact, "Alice", source="Bob")]},  # dit par Bob : corroboré
    ], [("user_2", "Alice", SIX), ("user_2", "Alice", SIX), ("user_3", "Bob", SIX)])
    beliefs = [r for r in rows if r[1] == "belief"]
    assert len(beliefs) == 1, "pas de doublon"
    assert abs(beliefs[0][3] - 0.8) < 1e-9, "seule la seconde source a augmenté la confiance (0,7 → 0,8)"
    reinforced = [e.data for e in events_of(kernel, "memory.reinforced")]
    assert [r.corroborated for r in reinforced] == [False, True]


class Revising(Extractions):
    """Au second passage, remplace la croyance connue que le prompt lui montre."""

    def __call__(self, req):
        if req.role == "extract" and len(self.windows) == 1:
            known = [ln for ln in req.messages[-1].content.splitlines() if "Alice travaille chez Ubisoft" in ln]
            old = int(known[0].split("]")[0][2:]) if known else None
            self.windows = [{"croyances": [belief("Alice travaille maintenant chez Nintendo", "Alice", remplace=old)]}]
        return super().__call__(req)


def test_a_contradicted_belief_is_replaced(tmp_path):
    script = Revising([{"croyances": [belief("Alice travaille chez Ubisoft", "Alice")]}, {}])
    kernel, clock, _, out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["je bosse chez Ubisoft"] + SIX[1:])
        await asyncio.sleep(600)
        await chat(kernel, "user_2", ["j'ai changé de boulot, je suis chez Nintendo"] + SIX[1:])
        await asyncio.sleep(600)
        rows = kernel.mind.store.query_mind(f"SELECT text, status FROM {memory_c.ITEMS_TABLE} ORDER BY id")
        await kernel.stop()
        return rows

    rows = run_virtual(clock, main)
    assert ("Alice travaille chez Ubisoft", "superseded") in rows
    assert ("Alice travaille maintenant chez Nintendo", "active") in rows


class Promising(Extractions):
    """Elle clôt la promesse (outil) quand Alice la remercie pour le lien."""

    def __call__(self, req):
        if req.role == "reply" and "merci pour le lien" in req.messages[-1].content:
            if not any(m.role == "tool" for m in req.messages):
                self.calls.append(req)
                section = req.messages[-1].content.split("CE QUE TU LUI AS PROMIS", 1)[1]
                pid = int(re.search(r"n° (\d+)", section).group(1))
                return LLMResponse("", tool_calls=(ToolCall("t1", "memory_promise_done",
                                                            {"promise": pid, "status": "honored"}),), stop="tool_use")
        return super().__call__(req)


def test_a_promise_is_noticed_shown_to_its_person_only_and_resolved_by_tool(tmp_path):
    script = Promising([{"promesses": [{"texte": "Envoyer à Alice le lien du concert", "envers": "Alice"}]}])
    kernel, clock, _, out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", SIX)
        await asyncio.sleep(600)
        pending = list(kernel.mind.root.slices["memory"].promises)
        await connect(kernel, "user_3", "Bob")
        await chat(kernel, "user_3", ["salut Mika"])
        await chat(kernel, "user_2", ["merci pour le lien du concert !"])
        after = list(kernel.mind.root.slices["memory"].promises)
        await kernel.stop()
        return pending, after

    pending, after = run_virtual(clock, main)
    assert len(pending) == 1 and after == [], "notée, puis tenue par l'outil"
    replies = [r for r in script.calls if r.role == "reply"]
    assert not any("lien du concert" in r.messages[-1].content for r in replies if r.meta.get("target") == "user_3")
    assert any("CE QUE TU LUI AS PROMIS" in r.messages[-1].content for r in replies if r.meta.get("target") == "user_2")
    resolved = [e.data for e in events_of(kernel, "memory.promise_resolved")]
    assert resolved and resolved[0].status == "honored" and resolved[0].by == "tool"


# ── Oubli, reconstruction, sommeil, rappel qui renforce ───────────────────


def test_forgetting_a_person_erases_her_everywhere(tmp_path):
    kernel, clock, llm, out = make(tmp_path)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["CANARI-OUBLI entre nous j'ai un secret de famille, dis à personne"] + SIX[1:])
        await asyncio.sleep(600)
        vectors = kernel.deps.ports["vectors"]
        before = len(vectors.indexed())
        report = await kernel.forget("user_2")
        left = kernel.mind.store.query_mind(f"SELECT COUNT(*) FROM {memory_c.ITEMS_TABLE}")[0][0]
        chunks = kernel.mind.store.query_mind(f"SELECT COUNT(*) FROM {memory_c.CHUNKS_TABLE}")[0][0]
        after = len(vectors.indexed())
        await kernel.stop()
        return before, report, left, chunks, after

    before, report, left, chunks, after = run_virtual(clock, main)
    assert before > 0 and after == 0 and left == 0 and chunks == 0
    assert report["vectors"] == before and report["contents"] > 0
    for f in tmp_path.iterdir():
        if f.suffix in (".db", ".db-wal") or f.name.endswith("-wal"):
            assert b"CANARI-OUBLI" not in f.read_bytes(), f.name


def test_the_vector_index_rebuilds_identically(tmp_path):
    """L'index est un cache : jeté puis reconstruit par le vrai processus
    d'indexation, il redonne les mêmes octets."""
    kernel, clock, llm, out = make(tmp_path)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", WEEK)
        await asyncio.sleep(600)
        vectors = kernel.deps.ports["vectors"]
        before, count = vectors.digest(), len(vectors.indexed())
        await vectors.clear()
        emptied = len(vectors.indexed())
        index = kernel.scheduler.instances["memory.index"]
        index.done = None  # le cache a disparu : le processus doit tout refaire
        kernel.scheduler.poke()
        await asyncio.sleep(1)
        again, rebuilt = vectors.digest(), len(vectors.indexed())
        await kernel.stop()
        return before, count, emptied, again, rebuilt

    before, count, emptied, again, rebuilt = run_virtual(clock, main)
    assert count > 0 and emptied == 0
    assert rebuilt == count and again == before, "même modèle, mêmes textes : mêmes octets"


def test_an_old_trivial_memory_sleeps_but_a_search_finds_it(tmp_path):
    class Searching(Extractions):
        def __call__(self, req):
            if req.role == "reply" and "cherche" in req.messages[-1].content and not any(
                    m.role == "tool" for m in req.messages):
                self.calls.append(req)
                return LLMResponse("", tool_calls=(ToolCall("s1", "memory_search", {"query": "parapluie jaune"}),),
                                   stop="tool_use")
            return super().__call__(req)

    script = Searching([{"souvenirs": [{"texte": "Alice a oublié son parapluie jaune au café", "personnes": ["Alice"],
                                        "importance": 1, "sensibilite": "anodin"}]}])
    kernel, clock, _, out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", SIX)
        await asyncio.sleep(600)
        await asyncio.sleep(60 * DAY / US)  # deux mois plus tard
        await chat(kernel, "user_2", ["il pleut, je devrais prendre un parapluie", "cherche un peu le parapluie jaune"])
        await kernel.stop()

    run_virtual(clock, main)
    replies = [r for r in script.calls if r.role == "reply"]
    spontaneous = [r for r in replies if "il pleut" in r.messages[-1].content][0]
    assert "parapluie jaune au café" not in spontaneous.messages[-1].content, "il dort : un indice vague ne le réveille pas"
    tool_results = [m.content for r in replies for m in r.messages if m.role == "tool"]
    assert any("parapluie jaune au café" in t for t in tool_results), "une recherche délibérée le retrouve"


def test_a_strong_cue_wakes_a_sleeping_memory(tmp_path):
    """On n'oublie pas vraiment : deux mois plus tard, « tu te souviens du
    parapluie jaune ? » le ramène — pas « il pleut »."""
    script = Extractions([{"souvenirs": [{"texte": "Alice a oublié son parapluie jaune au café", "personnes": ["Alice"],
                                          "importance": 1, "sensibilite": "anodin"}]}])
    kernel, clock, _, out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", SIX)
        await asyncio.sleep(600 + 60 * DAY / US)
        await chat(kernel, "user_2", ["il pleut, je devrais prendre un parapluie",
                                      "tu te souviens du parapluie jaune ?"])
        await kernel.stop()

    run_virtual(clock, main)
    replies = [r.messages[-1].content for r in script.calls if r.role == "reply"]
    weak = next(m for m in replies if m.endswith("il pleut, je devrais prendre un parapluie"))
    strong = next(m for m in replies if m.endswith("tu te souviens du parapluie jaune ?"))
    assert "parapluie jaune au café" not in weak
    assert "parapluie jaune au café" in strong.split("CE QUI TE REVIENT", 1)[-1]


def test_a_landmark_never_falls_asleep():
    from mika.faculties.memory.faculty import MemoryParams
    from mika.faculties.memory.salience import Item, dormant

    p = MemoryParams()

    def item(importance):
        return Item(1, "souvenir", "x", (), 1, importance, None, None, None, None, 0, 0, 0, 0, "active")

    assert dormant(item(0.7), 3 * 365 * DAY, p), "un souvenir important finit par dormir"
    assert not dormant(item(0.95), 3 * 365 * DAY, p), "un moment marquant, jamais tout à fait"


class Replying(Extractions):
    """Elle reprend les crêpes dans sa réponse, pas le reste."""

    def __call__(self, req):
        if req.role == "reply" and "crêpes au sarrasin" in req.messages[-1].content.rsplit("---", 1)[-1]:
            self.calls.append(req)
            return LLMResponse("Oh oui, tes crêpes au sarrasin, je m'en souviens ! [EMOTION:happy:0.5]")
        return super().__call__(req)


def test_what_she_actually_uses_strengthens_not_what_she_was_shown(tmp_path):
    rows, kernel, script = run_windows(tmp_path, [
        {"souvenirs": [{"texte": "Alice m'a appris à faire des crêpes au sarrasin", "personnes": ["Alice"],
                        "importance": 2},
                       {"texte": "Alice m'a parlé de sa recette de crêpes au chocolat", "personnes": ["Alice"],
                        "importance": 2}]},
    ], [("user_2", "Alice", SIX), ("user_2", "Alice", ["tu te souviens des crêpes au sarrasin ?",
                                                        "et les crêpes au chocolat ?"])], script=Replying)
    used = next(r for r in rows if r[2].startswith("Alice m'a appris"))
    shown_only = next(r for r in rows if r[2].startswith("Alice m'a parlé"))
    prompts = [r.messages[-1].content for r in script.calls if r.role == "reply"]
    assert any("crêpes au chocolat" in m.split("CE QUI TE REVIENT", 1)[-1] for m in prompts), "montré, au moins"
    assert used[5] >= 1, "elle s'en est servie : rappelé, donc renforcé"
    assert shown_only[5] == 0, "montré mais pas dit : rien ne le renforce"


def test_a_question_is_never_consolidated_without_its_answer(tmp_path):
    script = Extractions([{}, {}, {}])
    kernel, clock, _, out = build(tmp_path, script, latency=lambda req: 90.0 if req.role == "reply" else 0.0)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        pending = []
        for text in SIX:
            pending.append(await kernel.perceive(said("user_2", text)))
            await asyncio.sleep(1)
        for p in pending:
            await p.reply
        await asyncio.sleep(1200)
        await kernel.stop()

    run_virtual(clock, main)
    ups = [e.data.upto for e in events_of(kernel, "memory.consolidated")]
    thread = [e for e in events_of(kernel, "perception.received", "episode.utterance")]
    questions = {e.seq for e in thread if e.type.name == "perception.received"}
    answered_after = {e.data.reply_to: e.seq for e in thread if e.type.name == "episode.utterance"}
    assert ups, "la fenêtre a fini par être relue"
    for upto in ups:
        for q in questions:
            if q <= upto:
                assert answered_after[q] <= upto, f"question {q} relue sans sa réponse (fenêtre jusqu'à {upto})"


def test_a_window_that_keeps_failing_is_given_up_out_loud(tmp_path):
    class Garbage(Extractions):
        def __call__(self, req):
            if req.role == "extract":
                self.calls.append(req)
                return LLMResponse("désolé je ne sais pas faire ça")
            return super().__call__(req)

    script = Garbage([])
    kernel, clock, _, out = build(tmp_path, script)

    async def main():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", SIX)
        await asyncio.sleep(2 * 3600)
        await kernel.stop()

    run_virtual(clock, main)
    attempts = [r for r in script.calls if r.role == "extract"]
    done = [e.data for e in events_of(kernel, "memory.consolidated")]
    assert len(attempts) == 3, "trois essais espacés, pas une rafale"
    assert len(done) == 1 and done[0].failed and done[0].upto > 0


from mika.faculties.memory.consolidation import window  # noqa: E402


@given(st.lists(st.tuples(st.booleans(), st.integers(0, 4)), min_size=1, max_size=25), st.data())
def test_a_window_never_splits_a_pair(plan, data):
    """Des questions, des réponses en retard ou jamais venues, entrelacées."""
    rows, questions, seq = [], [], 0
    for is_question, delay in plan:
        seq += 1
        if is_question or not questions:
            questions.append(seq)
            rows.append((seq, seq, "user", "p", "q", None))
        else:
            q = questions[min(delay, len(questions) - 1)]
            if any(r[5] == q for r in rows):
                continue
            rows.append((seq, seq, "assistant", "p", "r", q))
    answered = {r[5] for r in rows if r[5] is not None}
    unanswered = [q for q in questions if q not in answered]
    awaiting = set(data.draw(st.sets(st.sampled_from(unanswered))) if unanswered else set())
    got = window(rows, awaiting)
    ids = {r[0] for r in got}
    for r in got:
        if r[2] == "user":
            assert r[0] not in awaiting
            answer = next((a[0] for a in rows if a[5] == r[0]), None)
            assert answer is None or answer in ids, "une question sans sa réponse"
    assert [r[0] for r in got] == [r[0] for r in rows][: len(got)], "une fenêtre est un préfixe"


def test_an_item_naming_nobody_concerns_the_people_of_the_conversation(tmp_path):
    """Un vrai modèle a omis la liste des personnes : sans repli, la confidence
    d'Alice aurait été rangée comme « ne concernant personne », donc dicible à tous."""
    rows, kernel, script = run_windows(tmp_path, [
        {"souvenirs": [{"texte": "Alice m'a confié qu'elle a peur de rater son discours", "sensibilite": "confidence"}],
         "croyances": [{"texte": "La sœur d'Alice s'appelle Julie", "sensibilite": "personnel"}]},
    ], [("user_2", "Alice", SIX), ("user_3", "Bob", ["tu sais si Alice a peur de son discours ?",
                                                      "et sa sœur, elle s'appelle comment ?"])])
    to_bob = [r.messages[-1].content for r in script.calls if r.role == "reply" and r.meta.get("target") == "user_3"]
    assert to_bob and not any("peur de rater son discours" in m for m in to_bob)
    assert not any("s'appelle Julie" in m for m in to_bob), "personnel, et Bob n'est pas un proche d'Alice"
