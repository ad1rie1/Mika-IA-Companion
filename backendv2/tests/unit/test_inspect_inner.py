"""Les vues d'inspection de la vie intérieure — mémoire, attention, soi.

- sur un noyau neuf, chacune se lit sans erreur et dit qu'il n'y a rien ;
- la mémoire se lit en quatre vues (souvenirs, croyances, promesses,
  consolidation), l'attention en trois (pensées, remarqué, attentes), le soi
  en deux (estime et récit, nuits) ; chaque liste a ses filtres typés et sa
  pagination avec le total ;
- après un peu de vie, elles montrent ce qu'elle a retenu, ce qui lui trotte
  dans la tête, ce qu'elle a remarqué (habituation comprise), son récit et
  ses nuits — et les filtres réduisent vraiment ce qui est montré ;
- l'onglet d'une personne ne montre que ce qui la concerne (toutes ses
  poignées, jamais celles d'un autre) ;
- l'estime est une série mesurée ;
- l'oubli s'y voit : le souvenir d'une personne oubliée n'y est plus, une
  pensée ou un journal dont le texte a été effacé se lit « (oublié) ».
"""

from __future__ import annotations

import asyncio
from typing import Any

from mika.contracts import attention as attention_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import rss as rss_c
from mika.contracts import self_ as self_c
from mika.faculties.attention import inspect as attention_inspect
from mika.faculties.memory import inspect as memory_inspect
from mika.kernel.clock import DAY, US
from mika.kernel.events import Content, Origin
from mika.kernel.inspect import (
    Badge,
    Block,
    Chart,
    Fields,
    InspectContext,
    Meter,
    Note,
    Prose,
    Ref,
    Row,
    Stats,
    Swatch,
    Table,
    Text,
    Timeline,
    When,
)
from mika.ports.llm import LLMResponse, ToolCall
from mika.runtime.inspection import Inspection, find, run_view, views
from mika.sim.clock import run_virtual
from tests.fixtures.mika import at_paris, boot, build, connect, said

INNER = {
    ("memory", "souvenirs"): ("Souvenirs", "memoire", 10), ("memory", "croyances"): ("Croyances", "memoire", 20),
    ("memory", "promesses"): ("Promesses", "memoire", 30),
    ("memory", "consolidation"): ("Consolidation", "memoire", 40),
    ("attention", "pensees"): ("Pensées", "pensees", 10), ("attention", "remarque"): ("Remarqué", "pensees", 20),
    ("attention", "attentes"): ("Attentes", "pensees", 30),
    ("self", "soi"): ("Estime et récit", "vie", 50), ("self", "nuits"): ("Nuits", "pensees", 40),
}
#: les onglets de la fiche d'une personne (lus avec une clé de personne)
TABS = {("memory", "memoire"): ("Mémoire", 50), ("attention", "pensees_personne"): ("Pensées", 80)}
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


def show(kernel, owner: str, name: str, *, subject: str = "", **params: str) -> list[Block]:
    spec = find(kernel, owner, name)
    assert spec is not None, f"vue {owner}/{name} non déclarée"
    return run_view(kernel, spec, params, subject=subject)


def _cell(value: Any) -> str:
    if isinstance(value, Ref | Text | Badge | Meter | Swatch):
        return value.text
    if isinstance(value, When):
        return str(value.at)
    return "" if value is None else str(value)


def _cells(r: Any) -> tuple[Any, ...]:
    return r.cells if isinstance(r, Row) else r


def _label(c: Any) -> str:
    return c if isinstance(c, str) else c.label


def text_of(blocks: list[Any]) -> str:
    out: list[str] = []
    for b in blocks:
        if isinstance(b, Table):
            out += [b.title, *map(_label, b.columns), *(_cell(c) for r in b.rows for c in _cells(r))]
            out += [] if b.rows else [b.empty]
            out += [text_of(list(r.detail)) for r in b.rows if isinstance(r, Row)]
        elif isinstance(b, Fields):
            out += [b.title, *(f"{k} : {_cell(v)}" for k, v in b.pairs)]
        elif isinstance(b, Prose):
            out += [b.title, b.text]
        elif isinstance(b, Note):
            out.append(b.text)
        elif isinstance(b, Stats):
            out += [f"{s.label} : {_cell(s.value)} {s.sub}" for s in b.items]
        elif isinstance(b, Timeline):
            out += [f"{e.title} : {e.text} ({e.meta})" for e in b.entries] + ([] if b.entries else [b.empty])
    return "\n".join(out)


def failures(blocks: list[Block]) -> list[str]:
    return [b.text for b in blocks if isinstance(b, Note) and b.tone in ("ko", "danger")]


def warnings(blocks: list[Block]) -> list[str]:
    return [b.text for b in blocks if isinstance(b, Note) and b.tone == "warn"]


def table(blocks: list[Block], title: str) -> Table:
    return next(b for b in blocks if isinstance(b, Table) and b.title.startswith(title))


def fields(blocks: list[Block], title: str) -> dict[str, str]:
    block = next(b for b in blocks if isinstance(b, Fields) and b.title == title)
    return {k: _cell(v) for k, v in block.pairs}


def column(t: Table, name: str) -> list[str]:
    i = [_label(c) for c in t.columns].index(name)
    return [_cell(_cells(r)[i]) for r in t.rows]


def raw_column(t: Table, name: str) -> list[Any]:
    i = [_label(c) for c in t.columns].index(name)
    return [_cells(r)[i] for r in t.rows]


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


async def remember(kernel, *items: tuple[str, tuple[str, ...]], kind: str = "souvenir") -> None:
    """La genèse de ce qu'elle a retenu (on ne l'écrit pas à la main dans la projection)."""
    drafts = []
    for text, about in items:
        if kind == "souvenir":
            drafts.append(memory_c.REMEMBERED.draft(text=Content.of(text, level=2), about=about, sensitivity=2,
                                                    importance=0.6, sources=(1,)))
        elif kind == "croyance":
            drafts.append(memory_c.BELIEVED.draft(text=Content.of(text, level=2), about=about, sensitivity=2))
        else:
            drafts.append(memory_c.PROMISE_NOTICED.draft(text=Content.of(text, level=2), to=about[0]))
    await kernel.mind.append(drafts, emitter="memory", correlation="genese", origin=Origin.GENESIS)


# ── Un noyau neuf ─────────────────────────────────────────────────────────


def test_on_a_fresh_kernel_every_view_reads_and_says_there_is_nothing(tmp_path):
    async def scenario(kernel):
        declared = {(v.owner, v.name): v for v in views(kernel)}
        shown = {key: show(kernel, *key) for key in INNER}
        tabs = {key: show(kernel, *key, subject="user_9") for key in TABS}
        bare = {key: show(kernel, *key) for key in TABS}
        bad = show(kernel, "memory", "souvenirs", status="licorne")
        return declared, shown, tabs, bare, bad

    declared, shown, tabs, bare, bad = live(tmp_path, scenario)
    for key, (title, section, order) in INNER.items():
        assert key in declared, key
        spec = declared[key]
        assert (spec.title, spec.section, spec.order) == (title, section, order), key
        assert shown[key] and failures(shown[key]) == [], (key, failures(shown[key]))
    for key, (title, order) in TABS.items():
        assert declared[key].title == title and declared[key].order == order
        assert tabs[key] and failures(tabs[key]) == [], (key, failures(tabs[key]))
        assert "Choisissez une personne" in text_of(bare[key])
    # des filtres typés, avec des libellés en français
    for name in ("souvenirs", "croyances", "promesses"):
        typed = declared[("memory", name)].typed
        assert [(p.name, p.kind) for p in typed] == [("q", "search"), ("status", "select"), ("person", "search")]
    statuses = dict(declared[("memory", "promesses")].typed[1].choices)
    assert statuses == {"pending": "en cours", "honored": "tenue", "dropped": "abandonnée"}
    assert declared[("memory", "souvenirs")].description

    assert table(shown[("memory", "souvenirs")], "Ses souvenirs").rows == ()
    assert table(shown[("memory", "souvenirs")], "Ses souvenirs").pager.total == 0
    assert fields(shown[("memory", "consolidation")], "La relecture")["dernière relecture"] == "jamais"
    assert "pas encore de relecture" in text_of(shown[("memory", "consolidation")])
    assert "rien ne lui trotte dans la tête" in text_of(shown[("attention", "pensees")])
    assert "rien de remarqué" in text_of(shown[("attention", "remarque")])
    assert "elle n'attend rien de personne" in text_of(shown[("attention", "attentes")])
    soi = text_of(shown[("self", "soi")])
    assert "0,50" in soi and "jamais bousculée" in soi and "réactivité" in soi and "humeur de fond" in soi
    assert "Elle ne s'est pas encore racontée" in soi
    curve = next(b for b in shown[("self", "soi")] if isinstance(b, Chart))
    assert curve.y == (0.0, 1.0) and curve.series[0].label == "Estime"
    nights = shown[("self", "nuits")]
    assert table(nights, "Toutes ses nuits").rows == () and "pas encore de nuit racontée" in text_of(nights)
    # un filtre invalide est dit, jamais deviné : il retombe sur « tous »
    assert failures(bad) == [] and warnings(bad) and "licorne" in warnings(bad)[0]
    assert "fondu dans un autre" in warnings(bad)[0]


class _NoTables:
    """Un magasin où la projection n'existe pas encore."""

    def query_mind(self, sql: str, params: Any = ()) -> list[tuple[Any, ...]]:
        return []

    def query_views(self, sql: str, params: Any = ()) -> list[tuple[Any, ...]]:
        return []

    def content(self, refs: Any) -> dict[str, str]:
        return {}


def test_memory_views_survive_a_missing_projection(tmp_path):
    async def scenario(kernel):
        frame = kernel.mind.frame()
        out = {}
        for name in ("souvenirs", "croyances", "promesses", "consolidation", "memoire"):
            spec = find(kernel, "memory", name)
            ctx = InspectContext(store=_NoTables(), ports={}, subject="user_2")
            out[name] = list(spec.fn(frame.state("memory"), frame, ctx))
        return out

    for name, blocks in live(tmp_path, scenario).items():
        assert failures(blocks) == [], name
        if name != "consolidation":
            assert "n'existe pas" in text_of(blocks), name


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
            "souvenirs": show(kernel, "memory", "souvenirs"),
            "croyances": show(kernel, "memory", "croyances"),
            "q": show(kernel, "memory", "souvenirs", q="parapluie"),
            "q_none": show(kernel, "memory", "souvenirs", q="licorne"),
            "active": show(kernel, "memory", "croyances", status="active"),
            "replaced": show(kernel, "memory", "croyances", status="remplacée"),
            "by_name": show(kernel, "memory", "croyances", person="alice"),
            "by_handle": show(kernel, "memory", "souvenirs", person="user_2"),
            "nobody": show(kernel, "memory", "souvenirs", person="Zoé"),
            "consolidation": show(kernel, "memory", "consolidation"),
            "thoughts": show(kernel, "attention", "pensees"),
            "noticed": show(kernel, "attention", "remarque"),
        }
        await kernel.forget("user_2")
        after = {"souvenirs": show(kernel, "memory", "souvenirs"), "thoughts": show(kernel, "attention", "pensees")}
        return before, after

    before, after = live(tmp_path, scenario, script=script)
    for blocks in (*before.values(), *after.values()):
        assert failures(blocks) == []

    # la mémoire : un souvenir, une croyance, chacun dans sa vue, en français, qui concernent Alice
    kept = table(before["souvenirs"], "Ses souvenirs")
    assert kept.title == "Ses souvenirs (1)" and kept.pager.total == 1
    assert column(kept, "concerne") == ["Alice"]
    assert raw_column(kept, "concerne")[0] == Ref.subject("person", "user_2", "Alice", "memoire")
    assert column(kept, "sensibilité") == ["anodin"] and isinstance(raw_column(kept, "sensibilité")[0], Badge)
    assert column(kept, "statut") == ["actif"]
    assert isinstance(raw_column(kept, "importance")[0], Meter)
    assert isinstance(raw_column(kept, "ce qu'il en reste")[0], Meter)
    assert isinstance(raw_column(kept, "émotion")[0], Swatch) and column(kept, "émotion") == ["amusée"]
    assert isinstance(raw_column(kept, "né")[0], When)
    assert "parapluie jaune" in column(kept, "souvenir")[0]
    # le détail : le texte en entier et les messages d'où il vient, en liens
    detail = kept.rows[0].detail
    assert any(isinstance(b, Prose) and "parapluie jaune" in b.text for b in detail)
    sources = [v for b in detail if isinstance(b, Fields) for k, v in b.pairs if k == "vient du message"]
    assert sources and all(isinstance(v, Ref) and v.kind == "event" for v in sources)

    belief = table(before["croyances"], "Ses croyances")
    assert column(belief, "croyance") == ["Alice travaille chez Ubisoft"]
    assert column(belief, "origine")[0].startswith("on le lui a dit") and column(belief, "statut") == ["active"]
    assert column(belief, "sensibilité") == ["personnel"] and isinstance(raw_column(belief, "confiance")[0], Meter)

    relecture = fields(before["consolidation"], "La relecture")
    assert relecture["dernière relecture"] != "jamais" and relecture["fenêtres abandonnées"] == "0"
    assert relecture["relu jusqu'au message"].startswith("n° ")
    runs = table(before["consolidation"], "Les dernières relectures")
    assert "faite" in column(runs, "issue")

    # les filtres réduisent vraiment
    searched = table(before["q"], "Ses souvenirs")
    assert len(searched.rows) == 1 and "parapluie" in column(searched, "souvenir")[0]
    none = table(before["q_none"], "Ses souvenirs")
    assert none.rows == () and none.empty == "aucun résultat pour ces filtres"
    assert len(table(before["active"], "Ses croyances").rows) == 1
    assert table(before["replaced"], "Ses croyances").rows == ()  # un libellé tapé à la main est compris
    assert column(table(before["by_name"], "Ses croyances"), "croyance") == ["Alice travaille chez Ubisoft"]
    assert len(table(before["by_handle"], "Ses souvenirs").rows) == 1
    assert table(before["nobody"], "Ses souvenirs").rows == ()
    assert "Personne dans sa mémoire ne répond à « Zoé »" in text_of(before["nobody"])

    # l'attention : la pensée née de l'échange, et ce qu'elle a remarqué (habituée au second titre)
    thoughts = table(before["thoughts"], "Ce qui lui trotte dans la tête")
    assert any("CANARI-PENSEE" in t for t in column(thoughts, "pensée"))
    assert "un échange" in column(thoughts, "née de") and "Alice" in column(thoughts, "concerne")
    assert "triste" in column(thoughts, "couleur") and all(isinstance(x, Swatch)
                                                           for x in raw_column(thoughts, "couleur"))
    assert all(isinstance(x, Meter) for x in raw_column(thoughts, "intensité"))
    assert any("volcans" in t for t in column(thoughts, "pensée")), "un signal assez pertinent devient une pensée"
    history = table(before["thoughts"], "Toutes ses pensées")
    assert len(history.rows) >= 2 and "vivante" in column(history, "maintenant")
    noticed = table(before["noticed"], "Remarqué ces dernières minutes")
    assert column(noticed, "source") == ["rss", "rss"]
    assert sorted(column(noticed, "poids (habituation)")) == ["0,85", "1,00"]
    assert sorted(column(noticed, "pertinence retenue")) == ["0,68", "0,80"]
    assert column(table(before["noticed"], "Tout ce qu'elle a remarqué"), "source") == ["rss", "rss"]

    # l'oubli : son souvenir n'est plus là ; la pensée reste, son texte non
    gone = text_of(after["souvenirs"])
    assert "parapluie" not in gone and "Ses souvenirs (0)" in gone
    left = table(after["thoughts"], "Ce qui lui trotte dans la tête")
    assert "(oublié)" in column(left, "pensée")
    assert not any("CANARI-PENSEE" in t for t in column(left, "pensée"))
    assert "CANARI-PENSEE" not in text_of(after["thoughts"])


def test_memory_lists_paginate_with_their_total(tmp_path):
    async def scenario(kernel):
        await remember(kernel, *((f"Souvenir numéro {i}", ()) for i in range(60)))
        return (show(kernel, "memory", "souvenirs"), show(kernel, "memory", "souvenirs", page="2"),
                show(kernel, "memory", "souvenirs", page="9"), show(kernel, "memory", "souvenirs", q="numéro 1"))

    first, second, clamped, searched = live(tmp_path, scenario)
    one, two = table(first, "Ses souvenirs"), table(second, "Ses souvenirs")
    assert one.title == "Ses souvenirs (60)" and one.pager.total == 60 and one.pager.pages == 2
    assert len(one.rows) == 50 and len(two.rows) == 10 and two.pager.number == 2
    assert column(one, "souvenir")[0] == "Souvenir numéro 59"  # les plus récents d'abord
    assert column(two, "souvenir")[-1] == "Souvenir numéro 0"
    assert set(column(one, "souvenir")).isdisjoint(column(two, "souvenir"))
    assert table(clamped, "Ses souvenirs").pager.number == 2  # une page trop loin : ramenée à la dernière
    # « numéro 1 », « numéro 10 » à « numéro 19 » : le total suit la recherche
    assert table(searched, "Ses souvenirs").pager.total == 11


# ── L'onglet d'une personne ───────────────────────────────────────────────


def test_person_tabs_show_only_what_concerns_that_person_on_all_her_handles(tmp_path):
    async def scenario(kernel):
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        # une poignée Telegram reliée à Alice par un opérateur
        await kernel.mind.append([identity_c.LINKED.draft(handle="tg_42", person="user_2")], emitter="identity",
                                 correlation="op", origin=Origin.EXTERNAL)
        await remember(kernel, ("Alice aime les crêpes CANARI-A", ("user_2",)),
                       ("Alice m'a écrit sur Telegram CANARI-TG", ("tg_42",)),
                       ("Bob collectionne les timbres CANARI-B", ("user_3",)),
                       ("Il pleut sur la ville", ()))
        await remember(kernel, ("Alice est infirmière", ("user_2",)), ("Bob est pompier", ("user_3",)),
                       kind="croyance")
        await remember(kernel, ("Envoyer la recette à Alice", ("user_2",)), ("Rappeler Bob", ("user_3",)),
                       kind="promesse")
        born = [attention_c.THOUGHT_BORN.draft(text=Content.of("Alice me manque CANARI-MANQUE", level=2),
                                               emotion="lonely", intensity=0.6, origin=attention_c.MISSING,
                                               about=("user_2",)),
                attention_c.THOUGHT_BORN.draft(text=Content.of("Bob m'a vexée CANARI-VEXEE", level=2),
                                               emotion="frustrated", intensity=0.6, origin=attention_c.EXCHANGE,
                                               about=("user_3",))]
        await kernel.mind.append(born, emitter="attention", correlation="genese", origin=Origin.GENESIS)
        ins = Inspection(kernel)
        memory, attention = ins.find("memory", "memoire"), ins.find("attention", "pensees_personne")
        return {who: (ins.run(memory, {}, subject=who), ins.run(attention, {}, subject=who))
                for who in ("user_2", "tg_42", "user_3")}

    shown = live(tmp_path, scenario)
    for mem, att in shown.values():
        assert failures(mem) == [] and failures(att) == []

    alice_mem, alice_att = shown["user_2"]
    text = text_of(alice_mem)
    assert "CANARI-A" in text and "CANARI-TG" in text, "toutes ses poignées"
    assert "Alice est infirmière" in text and "Envoyer la recette à Alice" in text
    assert "CANARI-B" not in text and "pompier" not in text and "Rappeler Bob" not in text, "jamais un autre"
    assert "Il pleut" not in text
    assert table(alice_mem, "Ses souvenirs").title == "Ses souvenirs (2)"
    assert table(alice_mem, "Ses croyances").title == "Ses croyances (1)"
    assert table(alice_mem, "Ses promesses").title == "Ses promesses (1)"
    # la poignée reliée lit la même personne
    assert text_of(shown["tg_42"][0]) == text

    thoughts = text_of(alice_att)
    assert "CANARI-MANQUE" in thoughts and "CANARI-VEXEE" not in thoughts
    waits = table(alice_att, "Ce qu'elle en attend")
    assert column(waits, "elle attend") == ["son retour"] and column(waits, "de") == ["Alice"]

    bob_mem, bob_att = shown["user_3"]
    assert "CANARI-B" in text_of(bob_mem) and "CANARI-A" not in text_of(bob_mem)
    assert "CANARI-TG" not in text_of(bob_mem)
    assert "CANARI-VEXEE" in text_of(bob_att) and "CANARI-MANQUE" not in text_of(bob_att)
    assert table(bob_att, "Ce qu'elle en attend").rows == ()


def test_person_tabs_are_placed_on_the_person_fiche(tmp_path):
    """Les onglets se rangent sur la fiche d'une personne (le type est déclaré
    par l'identité), dans leur ordre, sans que la console les nomme."""

    async def scenario(kernel):
        return [(t.owner, t.name, t.order, t.hidden) for t in Inspection(kernel).tabs("person")]

    tabs = live(tmp_path, scenario)
    mine = [t for t in tabs if (t[0], t[1]) in TABS]
    assert [(o, n, order) for o, n, order, _ in mine] == [("memory", "memoire", 50),
                                                          ("attention", "pensees_personne", 80)]
    assert not any(hidden for *_, hidden in mine)
    assert memory_inspect.PERSON_KIND == attention_inspect.PERSON_KIND == "person"


# ── L'estime, son récit, ses nuits ────────────────────────────────────────


def test_esteem_is_a_measured_series_and_its_curve_is_drawn(tmp_path):
    async def scenario(kernel):
        spec = kernel.registry.series["self.estime"]
        frame = kernel.mind.frame()
        rested = spec.fn(frame.state("self"), frame)
        await kernel.mind.append([attention_c.EXPECTATION_MISSED.draft(kind=attention_c.REPLY, person="user_2",
                                                                       since=frame.now - 1)],
                                 emitter="attention", correlation="genese", origin=Origin.GENESIS)
        frame = kernel.mind.frame()
        knocked = spec.fn(frame.state("self"), frame)
        now = kernel.mind.clock.now()
        points = [(now - 2 * DAY, 0.5), (now - DAY, 0.45), (now, knocked)]
        seen: list[tuple[str, int]] = []

        def sampler(key, since, until, n):
            seen.append((key, until - since))
            return points

        blocks = Inspection(kernel, sampler=sampler).run(find(kernel, "self", "soi"), {})
        return spec, rested, knocked, blocks, seen

    spec, rested, knocked, blocks, seen = live(tmp_path, scenario)
    assert (spec.label, spec.lo, spec.hi) == ("Estime", 0, 1)
    assert rested == 0.5 and 0.4 < knocked < 0.5
    assert seen and seen[0] == ("self.estime", 7 * DAY)
    curve = next(b for b in blocks if isinstance(b, Chart))
    assert curve.y == (0.0, 1.0) and len(curve.series[0].points) == 3
    stat = next(b for b in blocks if isinstance(b, Stats)).items[0]
    assert isinstance(stat.value, Meter) and stat.trend is not None and "remonte vers 0,50" in stat.sub


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
    assert fields(soi, "Son récit d'elle-même")["écrit"] != "jamais"
    persona = fields(soi, "La persona")
    assert persona["nom"] and persona["fuseau"] == "Europe/Paris"
    temperament = table(soi, "Le tempérament")
    assert all(isinstance(v, Meter | Swatch) for v in raw_column(temperament, "valeur"))
    assert "optimisme" in column(temperament, "curseur")

    full = next(b for b in nights if isinstance(b, Prose))
    assert full.title == "Journal du 2026-09-28, en entier" and full.text == JOURNAL
    timeline = next(b for b in nights if isinstance(b, Timeline))
    assert any(e.title == "Journal du 2026-09-28" and "CANARI-JOURNAL" in e.text for e in timeline.entries)
    assert sum(1 for e in timeline.entries if e.title.startswith("Rêve")) == min(dreamt, 14)
    history = table(nights, "Toutes ses nuits")
    kinds = column(history, "sorte")
    assert kinds.count("journal") == 1 and sum(1 for k in kinds if k.startswith("rêve")) == dreamt
    journal_row = kinds.index("journal")
    assert "CANARI-JOURNAL" in column(history, "texte")[journal_row]
    assert all(isinstance(v, Meter) for k, v in zip(kinds, raw_column(history, "vivacité"), strict=True)
               if k.startswith("rêve"))

    # la journée concernait user_1 : oubliée, son journal se lit « (oublié) »
    after = table(forgotten, "Toutes ses nuits")
    assert column(after, "texte")[column(after, "sorte").index("journal")] == "(oublié)"
    assert "CANARI-JOURNAL" not in text_of(forgotten)
