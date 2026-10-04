"""Tenir des années (ADR 0059), par ses intentions.

- « les adresses d'Alice » se lisent sans passer par toutes les inconnues de passage ;
- « ce que je t'ai dit hier soir » se retrouve même après des années d'échanges : le moment se lit sur
  l'intervalle, jamais par la liste de tous ses échanges — et la question, faite des mots d'une politesse, n'est
  pas prise pour une politesse ; ce qui s'est dit dans un salon ne revient pas en privé ;
- un énoncé de plus ne fait pas relire toute sa mémoire à l'index ; l'index ne recopie pas sa matrice à chaque
  ajout, et répond exactement comme une recherche exhaustive ;
- la file de sortie oublie ce qui est parti depuis longtemps, jamais ce qui n'est pas parti ;
- « qui concerne quoi » se lit par personne et suit la mémoire (renforcée, fondue la nuit, oubliée) ;
- « VOS ÉCHANGES PASSÉS » ne rappelle ni un « coucou Mika ! », ni deux fois le même échange ;
- une installation d'avant migre seule au démarrage, et ce qui avait été oublié ne revient pas quand la mémoire se
  reconstruit.
"""

from __future__ import annotations

import asyncio
import json
import random
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from mika.adapters.store_sqlite import SqliteStore
from mika.adapters.store_sqlite.store import OUTBOX_DONE_KEPT_US
from mika.adapters.vectors import HashEmbedder, SqliteVectorIndex
from mika.app import composition
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.faculties.identity.faculty import _owners, handles_of, owner_person, view_of
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.kernel.events import Content, Origin
from mika.kernel.state import FrozenDict
from mika.ports.store import AppendBatch, OutboxRow, SnapshotRow, StoredEvent
from mika.ports.vectors import VectorItem
from mika.sim.clock import run_virtual
from tests.fixtures.memory import Script, chat, section
from tests.fixtures.mika import DOC, at_paris, boot, build, connect

EXCHANGES = "VOS ÉCHANGES PASSÉS"


def run(tmp_path, scenario, *, script=None, start=at_paris(2026, 10, 5, 18, 0)):
    script = script or Script(reply="ah oui ? [EMOTION:happy:0.4]")
    kernel, clock, _llm, _out = build(tmp_path, script, start=start)

    async def main():
        await boot(kernel)
        try:
            return await scenario(kernel, clock, script)
        finally:
            await kernel.stop()

    return run_virtual(clock, main)


async def genesis(kernel, *drafts, emitter="memory"):
    await kernel.mind.append(list(drafts), emitter=emitter, correlation="genese", origin=Origin.GENESIS)


# ── Les adresses d'une personne ───────────────────────────────────────────


class Counting(FrozenDict):
    """Un dictionnaire gelé qui compte combien de fois on le parcourt."""

    walks = [0]

    def items(self):
        Counting.walks[0] += 1
        return super().items()

    def keys(self):
        Counting.walks[0] += 1
        return super().keys()

    def values(self):
        Counting.walks[0] += 1
        return super().values()

    def __iter__(self):
        Counting.walks[0] += 1
        return super().__iter__()


def brute(s, person):
    """Les adresses d'une personne, comme on les calculait : en parcourant toutes les adresses."""
    return tuple(sorted(k for k, h in s.handles.items() if (h.person or k) == person))


def test_her_addresses_are_read_without_going_through_every_stranger(tmp_path):
    """Alice écrit par son compte et par un compte extérieur (relié par un opérateur) ; deux cents inconnues sont passées.
    « Les adresses d'Alice », sa propriété, sa fiche se lisent sans parcourir les deux cents — l'audit d'une foule
    comptait 621 467 parcours de toutes les adresses en une journée à trois cents personnes (C5). Délier
    son compte extérieur la rend à elle-même ; et le journal, rejoué depuis la genèse, redonne le même index. « Qui sont ses
    propriétaires ? » non plus ne parcourt pas les inconnues."""

    async def scenario(kernel, clock, script):
        await connect(kernel, "user_1", "Camille", operator=True)
        await connect(kernel, "user_2", "Alice")
        await genesis(kernel, identity_c.LINKED.draft(handle="ext_5", person="user_2"), emitter="identity")
        for i in range(200):
            await connect(kernel, f"web_{i}", authenticated=False)
        frame = kernel.mind.frame()
        s = frame.state("identity")
        spy = replace(s, handles=Counting(s.handles))
        Counting.walks[0] = 0
        got = {p: handles_of(spy, p) for p in ("user_2", "ext_5", "web_7", "personne")}
        owner = owner_person(spy, "user_2", set())
        view = view_of(spy, "ext_5", frame.now)
        owners = _owners(spy, SimpleNamespace(params=None))
        walks = Counting.walks[0]
        linked = {p: brute(s, p) for p in got}
        await genesis(kernel, identity_c.LINKED.draft(handle="ext_5", person=None), emitter="identity")
        s2 = kernel.mind.frame().state("identity")
        unlinked = {p: (handles_of(s2, p), brute(s2, p)) for p in ("user_2", "ext_5")}
        everyone = {p for k, h in s2.handles.items() for p in (h.person or k,)}
        consistent = all(handles_of(s2, p) == brute(s2, p) for p in everyone) and set(s2.by_person.keys()) == everyone
        replayed = kernel.mind._rebuild_from_genesis(kernel.mind.root, {"identity"}, kernel.mind.head)
        return got, linked, walks, (owner, owners), view, unlinked, consistent, replayed.slices["identity"] == s2

    got, linked, walks, (owner, owners), view, unlinked, consistent, same = run(tmp_path, scenario)
    assert got == linked and got["user_2"] == ("ext_5", "user_2") and got["personne"] == ()
    assert walks == 0, f"{walks} parcours de toutes les adresses"
    assert owner is False and owners == ("user_1",) and view.person == "user_2" and view.first_seen > 0
    assert unlinked == {"user_2": (("user_2",), ("user_2",)), "ext_5": (("ext_5",), ("ext_5",))}
    assert consistent, "l'index et le parcours disent la même chose pour chacune"
    assert same, "rejoué depuis la genèse, le même index"


# ── Ce que je t'ai dit hier soir, après des années ────────────────────────

#: plus que ce qu'une requête SQLite accepte de paramètres (32 766) : des années d'échanges avec la propriétaire
YEARS_OF_EXCHANGES = 33_000


def test_last_night_is_found_after_years_of_exchanges(tmp_path):
    """Adrien a parlé à Mika des dizaines de milliers de fois ; hier soir, il lui a dit qu'il avait fini son
    puzzle. « tu te souviens de ce que je t'ai dit hier soir ? » le lui rend. Avant : la question, faite des mots
    d'une politesse (« hier », « soir »), ne cherchait rien ; et le moment se cherchait parmi la liste de tous ses
    échanges, que SQLite refuse au-delà de 32 766 — tout le rappel du tour disparaissait (C6)."""

    async def scenario(kernel, clock, script):
        await composition.configure(kernel, DOC, {"transcript": {"window": 2}})  # hier soir n'est plus dans le fil
        await connect(kernel, "user_2", "Adrien")
        await chat(kernel, "user_2", ["CANARI-C6 j'ai enfin fini le puzzle du phare, mille pièces"], gap_s=60)
        await asyncio.sleep(10 * 60)
        old = at_paris(2023, 1, 1, 12, 0)
        rows = [(-1 - i, "user_2", None, f"message ancien {i}", "réponse ancienne", old + i * MINUTE, None)
                for i in range(YEARS_OF_EXCHANGES)]
        await kernel.mind.store.run_mind(lambda sql: sql.executemany(
            f"INSERT INTO {memory_c.CHUNKS_TABLE}(id, person, question, user_text, reply_text, at, room) "
            "VALUES(?,?,?,?,?,?,?)", rows))
        await asyncio.sleep((at_paris(2026, 10, 6, 15, 0) - clock.now()) / US)
        await chat(kernel, "user_2", ["CANARI-AUTRE la pluie tombe", "le chat dort"], gap_s=60)
        await asyncio.sleep(HOUR / US)
        await chat(kernel, "user_2", ["tu te souviens de ce que je t'ai dit hier soir ?"])
        return section(script.replies("user_2")[-1], EXCHANGES)

    shown = run(tmp_path, scenario)
    assert "CANARI-C6" in shown, shown
    assert "CANARI-AUTRE" not in shown and "message ancien" not in shown, "seulement hier soir"


def test_what_was_said_in_a_room_does_not_come_back_in_private(tmp_path):
    """Tom raconte dans un groupe que le chat de Léa a vomi, puis lui écrit en privé. En privé, cet échange de salon
    ne revient pas — même quand l'index des vecteurs le range comme un échange privé (un index écrit avant ce lot,
    où les échanges de salon n'avaient pas leur sorte) : la recherche filtrée par personne repasse par la condition
    du privé. Dans le salon, il revient."""
    room = {"room": "ext_chat_-9", "channel": "external"}

    async def scenario(kernel, clock, script):
        await composition.configure(kernel, DOC, {"transcript": {"window": 2}})
        await chat(kernel, "ext_1", ["CANARI-SALON Mika, le chat de Léa a vomi sur le tapis ce matin"],
                   display_name="Tom", **room)
        await chat(kernel, "ext_1", ["Mika tu joues à quoi ?", "Mika il pleut chez toi ?"], display_name="Tom",
                   **room)
        await asyncio.sleep(15 * 60)
        vectors = kernel.deps.ports["vectors"]
        rows = kernel.mind.store.query_mind(f"SELECT id, user_text, reply_text, person FROM {memory_c.CHUNKS_TABLE} "
                                            "WHERE user_text LIKE '%CANARI-SALON%'")
        kinds = {vectors._kind_names[int(vectors._kinds[vectors._pos[int(r[0])]])] for r in rows}
        await vectors.upsert([VectorItem(int(i), memory_c.CHUNK, f"{u}\n{r}", (who,)) for i, u, r, who in rows])
        await chat(kernel, "ext_1", ["tu sais si le chat de Léa a encore vomi sur le tapis ?"], channel="external",
                   display_name="Tom")
        private = section(script.replies("ext_1")[-1], EXCHANGES)
        await chat(kernel, "ext_1", ["Mika, tu sais si le chat de Léa a encore vomi sur le tapis ?"],
                   display_name="Tom", **room)
        return kinds, private, section(script.replies("ext_1")[-1], EXCHANGES)

    kinds, private, in_room = run(tmp_path, scenario)
    assert kinds == {memory_c.ROOM_CHUNK}, "un échange de salon a sa sorte"
    assert "CANARI-SALON" not in private, private
    assert "CANARI-SALON" in in_room, in_room


# ── L'index des vecteurs ──────────────────────────────────────────────────


def test_one_more_utterance_does_not_reread_her_whole_memory(tmp_path):
    """Mille deux cents choses retenues ; Alice dit un mot de plus. L'index ajoute l'échange, sans relire les mille
    deux cents (avant : toute la mémoire, textes compris, à chaque énoncé, sur la boucle — C7). Contrôle : ce qui
    est oublié par la mémoire seule quitte l'index au passage suivant (le cache suit l'oubli)."""

    async def scenario(kernel, clock, script):
        await genesis(kernel, *(memory_c.BELIEVED.draft(text=Content.of(f"Sam aime le numéro {i} de la série"),
                                                        about=("name:sam",), told_by=("user_3",))
                                for i in range(1200)))
        await connect(kernel, "user_2", "Alice")
        await chat(kernel, "user_2", ["coucou"])
        await asyncio.sleep(MINUTE / US)
        vectors = kernel.deps.ports["vectors"]
        before = len(vectors.indexed())
        store = kernel.mind.store
        read = store.query_mind
        biggest = [0]

        def spy(sql, params=()):
            rows = read(sql, params)
            if memory_c.ITEMS_TABLE in sql or memory_c.CHUNKS_TABLE in sql:
                biggest[0] = max(biggest[0], len(rows))
            return rows

        store.query_mind = spy
        await chat(kernel, "user_2", ["j'ai acheté un vélo rouge"])
        await asyncio.sleep(MINUTE / US)
        store.query_mind = read
        newest = max(int(r[0]) for r in store.query_mind(f"SELECT id FROM {memory_c.CHUNKS_TABLE}"))
        added = newest in vectors.indexed()
        await kernel.mind.forget("user_3")  # la mémoire seule : l'index n'est pas prévenu
        await chat(kernel, "user_2", ["et toi ça va ?"])
        await asyncio.sleep(MINUTE / US)
        return before, biggest[0], added, len(vectors.indexed())

    before, biggest, added, after = run(tmp_path, scenario)
    assert before >= 1200 and added
    assert biggest < 100, f"une requête de l'index a relu {biggest} lignes"
    assert after < 100, "ce que Sam a confié, oublié avec lui, a quitté l'index"


def _random_items(rng, n):
    words = "chat soeur lyon guitare pluie film plage crepes velo train gare jardin poterie".split()
    items = []
    for key in rng.sample(range(10 * n), n):  # dans le désordre : l'ordre d'arrivée ne doit rien changer
        text = " ".join(rng.choice(words) for _ in range(rng.randint(1, 4)))
        items.append(VectorItem(key, rng.choice(("chunk", "belief", "souvenir")), text,
                                tuple(rng.sample(("user_1", "user_2", "ext_3", "name:sam"), rng.randint(1, 2)))))
    return items


def _exhaustive(embedder, items, query, k, kinds=None, keys=None, persons=None):
    """La recherche de référence : tous les vecteurs, filtrés un à un, triés par similarité puis par clé."""
    vecs = np.asarray(embedder.encode([i.text for i in items]), dtype=np.float32).astype(np.float16).astype(np.float32)
    q = np.asarray(embedder.encode([query])[0], dtype=np.float32)
    out = []
    for item, v in zip(items, vecs, strict=True):
        if kinds is not None and item.kind not in kinds:
            continue
        if keys is not None and item.key not in keys:
            continue
        if persons is not None and not set(item.persons) & set(persons):
            continue
        out.append((item.key, float(v @ q)))
    out.sort(key=lambda r: (-r[1], r[0]))
    return out[:k]


def test_the_vector_index_answers_like_an_exhaustive_search_and_grows_without_copying(tmp_path):
    """Des vecteurs arrivés dans le désordre, des textes en double (des ex æquo) : chaque recherche filtrée (par
    sorte, par clés, par personnes) rend exactement ce que rendrait le parcours de tous, ex æquo départagés par
    la clé — avant comme après un redémarrage, et après l'oubli d'une personne. Ajoutés un à un, ils ne font pas
    recopier la matrice à chaque ajout (avant : à chaque ajout, C7)."""
    rng = random.Random(7)
    items = _random_items(rng, 400)
    embedder = HashEmbedder()

    async def main():
        store = SqliteStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
        await store.open()
        index = SqliteVectorIndex(store, embedder)
        await index.open()
        matrices = set()
        for item in items:
            await index.upsert([item])
            matrices.add(index._mat.shape[0])  # une capacité nouvelle : une recopie
        queries = [("chat guitare", {}), ("pluie", {"kinds": {"belief"}}), ("film plage", {"persons": {"ext_3"}}),
                   ("crepes", {"keys": {i.key for i in items[::3]}, "kinds": {"chunk", "souvenir"}}),
                   ("velo train", {"persons": {"user_1", "name:sam"}, "kinds": {"souvenir"}})]
        got = [await index.search(q, 25, **kw) for q, kw in queries]
        again = SqliteVectorIndex(store, embedder)
        await again.open()
        reopened = [await again.search(q, 25, **kw) for q, kw in queries]
        await again.forget("ext_3")
        left = [i for i in items if "ext_3" not in i.persons]
        forgotten = [await again.search(q, 25, **kw) for q, kw in queries]
        await store.close()
        return matrices, got, reopened, left, forgotten

    matrices, got, reopened, left, forgotten = asyncio.run(main())
    assert len(matrices) <= 12, f"{len(matrices)} recopies de la matrice pour 400 ajouts"

    def same(a, b):
        return [k for k, _ in a] == [k for k, _ in b] and np.allclose([s for _, s in a], [s for _, s in b], atol=1e-5)

    queries = [("chat guitare", {}), ("pluie", {"kinds": {"belief"}}), ("film plage", {"persons": {"ext_3"}}),
               ("crepes", {"keys": {i.key for i in items[::3]}, "kinds": {"chunk", "souvenir"}}),
               ("velo train", {"persons": {"user_1", "name:sam"}, "kinds": {"souvenir"}})]
    expected = [_exhaustive(embedder, items, q, 25, **kw) for q, kw in queries]
    assert all(same(a, b) for a, b in zip(got, expected, strict=True))
    assert all(same(a, b) for a, b in zip(reopened, expected, strict=True))
    expected_left = [_exhaustive(embedder, left, q, 25, **kw) for q, kw in queries]
    assert all(same(a, b) for a, b in zip(forgotten, expected_left, strict=True)) and forgotten[2] == []
    ties = [s for _, s in expected[0]]
    assert len(set(ties)) < len(ties), "le jeu d'essai a des ex æquo"


# ── La file de sortie ─────────────────────────────────────────────────────


def test_the_outbox_forgets_what_left_long_ago_never_what_did_not(tmp_path):
    """Un an de réponses parties : la file de sortie ne garde les lignes parties que trente jours (le journal garde
    l'événement) ; ce qui attend, a échoué ou a été interrompu reste, quel que soit son âge (C8)."""
    day = DAY

    def event(seq, at):
        return StoredEvent(seq, f"e{seq}", "test.event", 1, at, None, "c", 0, "kernel", "{}")

    async def main():
        store = SqliteStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
        await store.open()
        rows = []
        for n in range(1, 61):  # un événement tous les deux jours, chacun avec une sortie
            status = "done" if n % 10 else ("failed" if n % 20 else "pending")
            rows.append((n, n * 2 * day, status))
            await store.append(AppendBatch([event(n, n * 2 * day)], outbox=[OutboxRow(f"k{n}", n, "x:y", status)]))
        await store.append(AppendBatch([event(61, 122 * day)],
                                       snapshot=SnapshotRow(61, 122 * day, json.dumps({"seq": 61, "at": 122 * day}))))
        kept = {r[0]: r[1] for r in store.query_mind("SELECT key, status FROM outbox")}
        await store.close()
        return rows, kept

    rows, kept = asyncio.run(main())
    for n, at, status in rows:
        old = at < 122 * day - OUTBOX_DONE_KEPT_US
        assert (f"k{n}" in kept) is (status != "done" or not old), (n, status, old)
    assert sum(1 for n, at, st in rows if st == "done" and at < 122 * day - OUTBOX_DONE_KEPT_US) > 30


# ── Qui concerne quoi ─────────────────────────────────────────────────────


def mirror(kernel) -> tuple[bool, int]:
    """``memory_about`` dit exactement ce que dit ``about``, élément par élément (et rien pour un élément disparu)."""
    store = kernel.mind.store
    about = {int(i): set(json.loads(a)) for i, a in store.query_mind(f"SELECT id, about FROM {memory_c.ITEMS_TABLE}")}
    joined: dict[int, set[str]] = {}
    for item, person in store.query_mind(f"SELECT item, person FROM {memory_c.ABOUT_TABLE}"):
        joined.setdefault(int(item), set()).add(person)
    return {i: a for i, a in about.items() if a} == joined, len(joined)


def test_who_an_item_concerns_follows_her_memory(tmp_path):
    """Une croyance sur Sam, redite avec Alice ; deux souvenirs fondus la nuit ; puis Sam est oublié. À chaque pas,
    « qui concerne quoi » (lu par personne, sans parcourir la mémoire) dit ce que dit la mémoire (C9)."""

    async def scenario(kernel, clock, script):
        steps = []
        await genesis(kernel, memory_c.BELIEVED.draft(text=Content.of("Sam fait de la poterie"), about=("name:sam",),
                                                      told_by=("user_3",)),
                      memory_c.REMEMBERED.draft(text=Content.of("Une soirée crêpes avec Bob"), about=("user_3",)),
                      memory_c.REMEMBERED.draft(text=Content.of("Une soirée crêpes avec Alice"), about=("user_2",)))
        steps.append(mirror(kernel))
        ids = [int(r[0]) for r in kernel.mind.store.query_mind(f"SELECT id FROM {memory_c.ITEMS_TABLE} ORDER BY id")]
        await genesis(kernel, memory_c.REINFORCED.draft(item=ids[0], about=("user_2",)))
        steps.append(mirror(kernel))
        await genesis(kernel, memory_c.NIGHT_SORTED.draft(night="2026-10-05", merges=((ids[1], ids[2]),)))
        steps.append(mirror(kernel))
        merged = {r[0] for r in kernel.mind.store.query_mind(
            f"SELECT person FROM {memory_c.ABOUT_TABLE} WHERE item=?", (ids[1],))}
        await kernel.forget("name:sam")
        steps.append(mirror(kernel))
        return steps, merged

    steps, merged = run(tmp_path, scenario)
    assert all(ok for ok, _ in steps), steps
    assert [n for _, n in steps] == [3, 3, 3, 2]
    assert merged == {"user_2", "user_3"}, "le souvenir gardé concerne les deux"


# ── Les échanges passés ───────────────────────────────────────────────────


@pytest.mark.slow
def test_past_exchanges_are_neither_greetings_nor_twice_the_same(tmp_path):
    """Des semaines de « coucou Mika ! », une histoire de crêperie, et deux fois la même phrase sur le match de
    rugby. Un mois plus tard, à « coucou Mika, ça faisait longtemps… », « VOS ÉCHANGES PASSÉS » ne rappelle aucun
    « coucou Mika ! » (au jour 85 de la vie de l'audit : trois, dont deux identiques — C10) ; sur le rugby, l'échange
    revient une fois, pas deux. Contrôle : la crêperie revient quand on en parle."""

    async def scenario(kernel, clock, script):
        await composition.configure(kernel, DOC, {"transcript": {"window": 2}})
        await connect(kernel, "user_2", "Alice")
        days = [["coucou Mika !"], ["coucou Mika !", "le match de rugby de samedi était incroyable"],
                ["coucou Mika !", "ma grand-mère Odette tenait une crêperie bleue à Quimper"],
                ["salut Mika", "le match de rugby de samedi était incroyable"], ["coucou !"]]
        for lines in days:
            await chat(kernel, "user_2", lines, gap_s=120)
            await asyncio.sleep(DAY / US - 240)
        await asyncio.sleep(30 * DAY / US)
        shown = []
        for text in ("coucou Mika, ça faisait longtemps…", "tu as aimé le match de rugby ?",
                     "tu te souviens de la crêperie de ma grand-mère ?"):
            await chat(kernel, "user_2", [text], gap_s=2 * HOUR / US)
            shown.append(section(script.replies("user_2")[-1], EXCHANGES))
        return shown

    greeting, rugby, creperie = run(tmp_path, scenario)
    assert "coucou Mika !" not in greeting and "« salut Mika »" not in greeting, greeting
    assert rugby.count("le match de rugby de samedi était incroyable") == 1, rugby
    assert "crêperie bleue à Quimper" in creperie, creperie


# ── Une installation d'avant ──────────────────────────────────────────────


def _as_before(path) -> int:
    """Ramène un dossier à ce qu'écrivait le code d'avant : projections de la mémoire en version 3, sans
    ``memory_about`` ni ``memory_forgets`` ni les nouveaux index ; tranche ``identity`` en version 3, sans index."""
    db = sqlite3.connect(path / "mind.db")
    for table in (memory_c.ABOUT_TABLE, memory_c.FORGETS_TABLE):
        db.execute(f"DROP TABLE IF EXISTS {table}")
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name IN (?, ?) "
                              "AND name NOT LIKE 'sqlite_%'", (memory_c.ITEMS_TABLE, memory_c.CHUNKS_TABLE)).fetchall():
        db.execute(f"DROP INDEX {name}")
    db.execute(f"CREATE INDEX {memory_c.CHUNKS_TABLE}_person ON {memory_c.CHUNKS_TABLE}(person, id)")
    db.execute("UPDATE meta SET value='3' WHERE key IN (?, ?)",
               (f"t0:{memory_c.ITEMS_TABLE}", f"t0:{memory_c.CHUNKS_TABLE}"))
    snapshots = db.execute("SELECT seq, data FROM snapshots").fetchall()
    for seq, data in snapshots:
        snap = json.loads(data)
        ident = snap["slices"]["identity"]
        ident["v"] = 3
        ident["data"].pop("by_person", None)
        db.execute("UPDATE snapshots SET data=? WHERE seq=?", (json.dumps(snap), seq))
    db.commit()
    db.close()
    return len(snapshots)


def extract(prompt):
    body = prompt.split("Les messages :")[-1]
    if "CANARI-ALICE" in body:
        return {"croyances": [{"texte": "Alice a un chat qui s'appelle Moustache (CANARI-ALICE)",
                               "personnes": ["Alice"], "sensibilite": "personnel"}]}
    if "CANARI-BOB" in body:
        return {"croyances": [{"texte": "Bob joue de la guitare (CANARI-BOB)", "personnes": ["Bob"],
                               "sensibilite": "anodin"}]}
    return None


def test_an_install_from_before_migrates_by_itself_and_what_was_forgotten_stays_forgotten(tmp_path):
    """Une vie écrite par le code d'avant : Alice et Bob ont parlé, un compte extérieur est relié à Alice, puis Alice a été
    oubliée. Au démarrage, la mémoire se reconstruit (nouvelle version), l'index des adresses aussi (depuis la
    genèse) ; « qui concerne quoi » se remplit ; et rien d'Alice ne revient — avant, une reconstruction recopiait
    les éléments oubliés, texte vide, toujours rangés à son nom."""
    script = Script(extract, reply="d'accord [EMOTION:happy:0.4]")
    kernel, clock, _llm, _out = build(tmp_path, script)
    six = ["un", "deux", "trois", "quatre", "cinq"]

    async def first():
        await boot(kernel)
        await connect(kernel, "user_2", "Alice")
        await connect(kernel, "user_3", "Bob")
        await genesis(kernel, identity_c.LINKED.draft(handle="ext_9", person="user_3"), emitter="identity")
        await chat(kernel, "user_2", ["CANARI-ALICE mon chat Moustache est adorable", *six])
        await chat(kernel, "user_3", ["CANARI-BOB je joue de la guitare le soir", *six])
        await asyncio.sleep(20 * 60)
        await kernel.forget("user_2")
        kernel.mind._snapshot_every = 1  # un instantané d'avant : sa tranche ``identity`` sans index
        await connect(kernel, "web_1", authenticated=False)
        await kernel.stop()

    run_virtual(clock, first)
    assert _as_before(tmp_path) > 0, "un instantané d'avant à relire"
    kernel2, clock2, _, _ = build(tmp_path, script, start=clock.now() + HOUR)

    async def second():
        await boot(kernel2)
        await asyncio.sleep(MINUTE / US)
        store = kernel2.mind.store
        rows = store.query_mind(f"SELECT text, about, told_by FROM {memory_c.ITEMS_TABLE}")
        chunks = store.query_mind(f"SELECT person FROM {memory_c.CHUNKS_TABLE}")
        indexes = {r[0] for r in store.query_mind("SELECT name FROM sqlite_master WHERE type='index'")}
        ok, joined = mirror(kernel2)
        handles = handles_of(kernel2.mind.frame().state("identity"), "user_3")
        vectors = kernel2.deps.ports["vectors"]
        hits = await vectors.search("guitare", 5, persons={"user_3"})
        await kernel2.stop()
        return rows, chunks, indexes, ok, joined, handles, hits, kernel2.mind.anomalies

    rows, chunks, indexes, ok, joined, handles, hits, anomalies = run_virtual(clock2, second)
    assert rows and all(text for text, _a, _t in rows), "aucun élément vide"
    assert not any("user_2" in a or "user_2" in t for _x, a, t in rows), "rien d'Alice ne revient"
    assert "CANARI-BOB" in " ".join(text for text, _a, _t in rows)
    assert chunks and all(p != "user_2" for (p,) in chunks)
    assert {f"{memory_c.ITEMS_TABLE}_kind", f"{memory_c.CHUNKS_TABLE}_person_at"} <= indexes
    assert ok and joined > 0
    assert handles == ("ext_9", "user_3"), "l'index des adresses s'est reconstruit"
    assert hits, "l'index des vecteurs a rattrapé"
    assert not [a for a in anomalies if "identity" in a], anomalies
