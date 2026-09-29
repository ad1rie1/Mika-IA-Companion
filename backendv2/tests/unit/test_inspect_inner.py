"""Les vues d'inspection de la vie intérieure — mémoire, attention, soi.

- sur un noyau neuf, chacune se lit sans erreur et dit qu'il n'y a rien ;
- après un peu de vie, elles montrent ce qu'elle a retenu, ce qui lui trotte
  dans la tête, ce qu'elle a remarqué (habituation comprise), son récit et
  ses nuits — et les filtres réduisent vraiment ce qui est montré ;
- l'oubli s'y voit : le souvenir d'une personne oubliée n'y est plus, une
  pensée ou un journal dont le texte a été effacé se lit « (oublié) ».
"""

from __future__ import annotations

import asyncio
from typing import Any

from mika.contracts import memory as memory_c
from mika.contracts import rss as rss_c
from mika.contracts import self_ as self_c
from mika.kernel.clock import US
from mika.kernel.events import Content, Origin
from mika.kernel.inspect import Block, Fields, InspectContext, Note, Prose, Ref, Table
from mika.ports.llm import LLMResponse, ToolCall
from mika.runtime.inspection import find, run_view, views
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, boot, build, connect, said

INNER = {("memory", "souvenirs"): "Mémoire", ("attention", "pensees"): "Pensées", ("self", "soi"): "Soi",
         ("self", "nuits"): "Nuits"}
SIX = ["un", "deux", "trois", "quatre", "cinq", "six"]
JOURNAL = "J'ai parlé avec Alice de son chagrin, CANARI-JOURNAL."
NARRATIVE = "Je suis quelqu'un qui aime les petites choses du quotidien."


class Script:
    """Converse, consolide selon un script, écrit récit, journal et rêves."""

    def __init__(self, windows: list[dict[str, Any]] | None = None, tag: str = "[EMOTION:happy:0.4]") -> None:
        self.windows = list(windows or [])
        self.tag = tag

    def __call__(self, req):
        if req.role == "extract":
            args = self.windows.pop(0) if self.windows else {}
            return LLMResponse("", tool_calls=(ToolCall("x", "record_memories", args),), stop="tool_use")
        if req.role in ("profile", "compact"):
            return LLMResponse("{}")
        if req.role == "narrative":
            return LLMResponse(NARRATIVE)
        if req.role == "journal":
            return LLMResponse(JOURNAL)
        if req.role == "dream":
            return LLMResponse("Je vole au-dessus d'un marché de nuages.")
        if req.role == "murmur":
            return LLMResponse("hmm")
        return LLMResponse(f"d'accord {self.tag}")


# ── Lire une vue ──────────────────────────────────────────────────────────


def show(kernel, owner: str, name: str, **params: str) -> list[Block]:
    spec = find(kernel, owner, name)
    assert spec is not None, f"vue {owner}/{name} non déclarée"
    return run_view(kernel, spec, params)


def _cell(value: Any) -> str:
    return value.text if isinstance(value, Ref) else "" if value is None else str(value)


def text_of(blocks: list[Block]) -> str:
    out: list[str] = []
    for b in blocks:
        if isinstance(b, Table):
            out += [b.title, *b.columns, *(_cell(c) for r in b.rows for c in r)] + ([] if b.rows else [b.empty])
        elif isinstance(b, Fields):
            out += [b.title, *(f"{k} : {_cell(v)}" for k, v in b.pairs)]
        elif isinstance(b, Prose):
            out += [b.title, b.text]
        elif isinstance(b, Note):
            out.append(b.text)
    return "\n".join(out)


def failures(blocks: list[Block]) -> list[str]:
    return [b.text for b in blocks if isinstance(b, Note) and b.tone == "ko"]


def table(blocks: list[Block], title: str) -> Table:
    return next(b for b in blocks if isinstance(b, Table) and b.title.startswith(title))


def fields(blocks: list[Block], title: str) -> dict[str, str]:
    block = next(b for b in blocks if isinstance(b, Fields) and b.title == title)
    return {k: _cell(v) for k, v in block.pairs}


def column(t: Table, name: str) -> list[str]:
    i = t.columns.index(name)
    return [_cell(r[i]) for r in t.rows]


def live(tmp_path, scenario, *, script: Script | None = None, start: int = at_paris(2026, 9, 28, 14, 0)):
    kernel, clock, _, _ = build(tmp_path, script or Script(), start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def chat(kernel, handle: str, lines: list[str], gap_s: float = 60) -> None:
    for text in lines:
        p = await kernel.perceive(said(handle, text))
        await p.reply
        await asyncio.sleep(gap_s)


async def until(kernel, t: int) -> None:
    now = kernel.mind.clock.now()
    if t > now:
        await asyncio.sleep((t - now) / US)


# ── Un noyau neuf ─────────────────────────────────────────────────────────


def test_on_a_fresh_kernel_every_view_reads_and_says_there_is_nothing(tmp_path):
    async def scenario(kernel):
        declared = {(v.owner, v.name): v for v in views(kernel)}
        return declared, {key: show(kernel, *key) for key in INNER}, show(kernel, "memory", "souvenirs",
                                                                        kind="licorne")

    declared, shown, bad = live(tmp_path, scenario)
    for key, title in INNER.items():
        assert key in declared and declared[key].title == title
        assert shown[key] and failures(shown[key]) == [], (key, failures(shown[key]))
    assert [name for name, _ in declared[("memory", "souvenirs")].params] == ["q", "kind", "status"]
    memory = shown[("memory", "souvenirs")]
    assert table(memory, "Ce qu'elle a retenu").rows == ()
    assert fields(memory, "La relecture")["dernière relecture"] == "jamais"
    assert "rien ne lui trotte dans la tête" in text_of(shown[("attention", "pensees")])
    soi = text_of(shown[("self", "soi")])
    assert "0,50" in soi and "jamais bousculée" in soi and "réactivité" in soi and "humeur de fond" in soi
    assert "Elle ne s'est pas encore racontée" in soi
    nights = shown[("self", "nuits")]
    assert table(nights, "Son journal").rows == () and table(nights, "Ses rêves").rows == ()
    # un filtre invalide est dit, jamais deviné
    assert failures(bad) and "licorne" in failures(bad)[0] and "croyance" in failures(bad)[0]
    assert not any(isinstance(b, Table) for b in bad)


class _NoTables:
    """Un magasin où la projection n'existe pas encore."""

    def query_mind(self, sql: str, params: Any = ()) -> list[tuple[Any, ...]]:
        return []

    def query_views(self, sql: str, params: Any = ()) -> list[tuple[Any, ...]]:
        return []

    def content(self, refs: Any) -> dict[str, str]:
        return {}


def test_memory_view_survives_a_missing_projection(tmp_path):
    async def scenario(kernel):
        spec = find(kernel, "memory", "souvenirs")
        frame = kernel.mind.frame()
        return list(spec.fn(frame.state("memory"), frame, InspectContext(store=_NoTables(), ports={})))

    blocks = live(tmp_path, scenario)
    assert failures(blocks) == [] and "n'existe pas" in text_of(blocks)


# ── Après un peu de vie ───────────────────────────────────────────────────

WINDOW = {
    "souvenirs": [{"texte": "Alice m'a raconté qu'elle a oublié son parapluie jaune au café", "personnes": ["Alice"],
                   "importance": 3, "sensibilite": "anodin", "emotion": "amused"}],
    "croyances": [{"texte": "Alice travaille chez Ubisoft", "personnes": ["Alice"], "source": "Alice",
                   "origine": "dit", "confiance": 0.7, "sensibilite": "personnel"}],
}


def headline(entry: str, text: str):
    return rss_c.NOTICED.draft(source="rss", kind="entry", summary=Content.of(text), pertinence=0.8, entry=entry,
                               feed="f1", bundle="rss")


def test_after_a_conversation_she_shows_what_she_kept_and_forgetting_shows(tmp_path):
    script = Script([WINDOW], tag="[EMOTION:sad:0.85]")

    async def scenario(kernel):
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["CANARI-PENSEE ma mère est à l'hôpital", *SIX[1:]])
        await asyncio.sleep(10 * 60)  # la fenêtre est mûre et calme : relue
        await kernel.mind.append([headline("e1", "Un titre sur les volcans d'Islande"),
                                  headline("e2", "Un autre titre sur les volcans")],
                                 emitter="rss", correlation="flux", origin=Origin.EXTERNAL)
        await asyncio.sleep(5)
        before = {
            "all": show(kernel, "memory", "souvenirs"),
            "q": show(kernel, "memory", "souvenirs", q="parapluie"),
            "belief": show(kernel, "memory", "souvenirs", kind="croyance"),
            "belief_en": show(kernel, "memory", "souvenirs", kind="belief", status="active"),
            "nothing": show(kernel, "memory", "souvenirs", q="licorne"),
            "thoughts": show(kernel, "attention", "pensees"),
        }
        await kernel.forget("user_2")
        after = {"all": show(kernel, "memory", "souvenirs"), "thoughts": show(kernel, "attention", "pensees")}
        return before, after

    before, after = live(tmp_path, scenario, script=script)
    for blocks in (*before.values(), *after.values()):
        assert failures(blocks) == []

    # la mémoire : un souvenir et une croyance, en français, qui concernent Alice
    kept = table(before["all"], "Ce qu'elle a retenu")
    assert sorted(column(kept, "sorte")) == ["croyance", "souvenir"]
    assert set(column(kept, "concerne")) == {"Alice"}
    assert {"anodin", "personnel"} == set(column(kept, "sensibilité"))
    assert "on le lui a dit" in column(kept, "origine") and "actif" in column(kept, "statut")
    assert any("parapluie jaune" in t for t in column(kept, "texte"))
    relecture = fields(before["all"], "La relecture")
    assert relecture["dernière relecture"] != "jamais" and relecture["fenêtres abandonnées"] == "0"
    assert relecture["relu jusqu'au message"].startswith("#")

    # les filtres réduisent vraiment
    searched = table(before["q"], "Ce qu'elle a retenu")
    assert len(searched.rows) == 1 and "parapluie" in column(searched, "texte")[0]
    assert column(table(before["belief"], "Ce qu'elle a retenu"), "sorte") == ["croyance"]
    assert column(table(before["belief_en"], "Ce qu'elle a retenu"), "sorte") == ["croyance"]
    assert table(before["nothing"], "Ce qu'elle a retenu").rows == ()

    # l'attention : la pensée née de l'échange, et ce qu'elle a remarqué (habituée au second titre)
    thoughts = table(before["thoughts"], "Ce qui lui trotte dans la tête")
    assert any("CANARI-PENSEE" in t for t in column(thoughts, "pensée"))
    assert "un échange" in column(thoughts, "née de") and "Alice" in column(thoughts, "concerne")
    assert "triste" in column(thoughts, "couleur")
    assert any("volcans" in t for t in column(thoughts, "pensée")), "un signal assez pertinent devient une pensée"
    noticed = table(before["thoughts"], "Ce qu'elle a remarqué")
    assert column(noticed, "source") == ["rss", "rss"]
    assert sorted(column(noticed, "poids (habituation)")) == ["0,85", "1,00"]
    assert sorted(column(noticed, "pertinence retenue")) == ["0,68", "0,80"]

    # l'oubli : son souvenir n'est plus là ; la pensée reste, son texte non
    gone = text_of(after["all"])
    assert "parapluie" not in gone and "Ubisoft" not in gone
    left = table(after["thoughts"], "Ce qui lui trotte dans la tête")
    assert "(oublié)" in column(left, "pensée")
    assert not any("CANARI-PENSEE" in t for t in column(left, "pensée"))


def test_her_story_and_her_nights_show_and_a_forgotten_journal_reads_forgotten(tmp_path):
    async def scenario(kernel):
        await kernel.mind.append([memory_c.REMEMBERED.draft(text=Content.of(t, level=1), sensitivity=1)
                                  for t in ("J'ai parlé de cuisine", "J'ai appris les oiseaux", "J'ai ri d'une blague",
                                            "J'ai regardé la pluie", "J'ai lu un poème")],
                                 emitter="memory", correlation="genese", origin=Origin.GENESIS)
        await until(kernel, at_paris(2026, 9, 28, 18, 0))
        p = await kernel.perceive(said("user_1", "coucou, bonne soirée"))
        await p.reply
        await until(kernel, at_paris(2026, 9, 29, 10, 0))
        soi = show(kernel, "self", "soi")
        nights = show(kernel, "self", "nuits")
        dreams = [e for e in kernel.mind.store.read() if e.type == self_c.DREAMT.name]
        await kernel.forget("user_1")
        return soi, nights, len(dreams), show(kernel, "self", "nuits")

    soi, nights, dreamt, forgotten = live(tmp_path, scenario, start=at_paris(2026, 9, 28, 17, 0))
    for blocks in (soi, nights, forgotten):
        assert failures(blocks) == []
    story = next(b for b in soi if isinstance(b, Prose))
    assert story.text == NARRATIVE
    assert fields(soi, "Son récit d'elle-même")["écrit le"] != "jamais"

    journal = table(nights, "Son journal")
    assert column(journal, "journée") == ["2026-09-28"] and "CANARI-JOURNAL" in column(journal, "journal")[0]
    full = next(b for b in nights if isinstance(b, Prose))
    assert full.title == "Journal du 2026-09-28, en entier" and full.text == JOURNAL
    assert len(table(nights, "Ses rêves").rows) == min(dreamt, 14)

    # la journée concernait user_1 : oublié, son journal se lit « (oublié) »
    after = table(forgotten, "Son journal")
    assert column(after, "journal") == ["(oublié)"]
    assert "CANARI-JOURNAL" not in text_of(forgotten)
