"""Les flux et Teams sur le schéma déclaré (ADR 0101), par leurs intentions.

- **une valeur venue d'ailleurs qui dépasse sa borne** ne fait pas échouer l'écriture : une clé (une adresse de flux,
  un identifiant de conversation, un auteur) est ramenée à sa borne par son empreinte — deux valeurs distinctes
  restent deux lignes, et une lecture par la valeur entière retrouve la sienne ; un nom de flux (un texte qu'on montre)
  est coupé ; une référence cherchée trop longue ne désigne rien ;
- **la recherche ignore la casse et les accents, pareil sur les deux moteurs** : les deux côtés sont repliés
  (``fold_text``) et comparés par ``instr`` — ``%`` et ``_`` n'y sont que des caractères ;
- **aucun SQL propre à SQLite** dans ces deux adaptateurs (relu par l'AST des chaînes, jamais par le texte du
  source : les commentaires nomment ce qu'il ne faut pas faire) ;
- **le schéma tient sous MariaDB** : toute clé ou colonne indexée est un ``VARCHAR`` borné, un index composite ne
  dépasse pas 768 caractères, les noms 64.
"""

from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Integer, String, insert, select
from sqlalchemy.dialects.mysql.mariadb import MariaDBDialect
from sqlalchemy.schema import CreateIndex, CreateTable

from mika.adapters.feeds import HttpFeeds
from mika.adapters.feeds.models import FEED_NAME_MAX, URL_MAX, EntryRow, FeedRow, entry_values
from mika.adapters.feeds.models import fit as feeds_fit
from mika.adapters.teams import TeamsConfig, TeamsStore
from mika.adapters.teams.models import AUTHOR_MAX, CONVERSATION_MAX, MessageRow
from mika.adapters.teams.models import fit as teams_fit
from mika.ports.sql import FEEDS, TEAMS, Key
from mika.ports.teams import Draft, InboxBatch, InboxConversation, InboxMessage, message_ref

SRC = Path(__file__).resolve().parents[2] / "src" / "mika" / "adapters"
FILES = (SRC / "feeds" / "__init__.py", SRC / "feeds" / "models.py", SRC / "teams" / "store.py",
         SRC / "teams" / "models.py")
NOW = 1_790_000_000_000_000


def go(coro):
    return asyncio.run(coro)


# ── Une valeur trop longue ────────────────────────────────────────────────


def test_fit_keeps_a_value_that_fits_and_digests_one_that_does_not():
    assert feeds_fit("court", 24) == "court"
    a, b = "x" * 600 + "a", "x" * 600 + "b"
    assert len(feeds_fit(a, URL_MAX)) == URL_MAX and feeds_fit(a, URL_MAX) == feeds_fit(a, URL_MAX)
    assert feeds_fit(a, URL_MAX) != feeds_fit(b, URL_MAX)  # le même début, deux clés
    assert feeds_fit(feeds_fit(a, URL_MAX), URL_MAX) == feeds_fit(a, URL_MAX)
    assert teams_fit(a, 32) == feeds_fit(a, 32) and len(teams_fit(a, 32)) == 32


def overlong_feeds(urls: list[str], titles: dict[str, str]):
    def handler(req: httpx.Request) -> httpx.Response:
        last = str(req.url)[-1]
        title = titles[last]
        item = f"<item><title>Article {last}</title><guid>{last}</guid></item>"
        return httpx.Response(200, content=f"<rss><channel><title>{title}</title>{item}</channel></rss>")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_an_overlong_feed_url_is_kept_by_its_digest_and_finds_its_row_again(tmp_path):
    base = "http://127.0.0.1:9/flux.xml?token=" + "s" * 3000
    urls = [base + "a", base + "b"]  # le même début, bien au-delà de la borne
    titles = {"a": "Flux A", "b": "Le flux B " * 60}  # un titre de 600 caractères
    feeds = HttpFeeds(lambda: urls, tmp_path / "f.db", client=overlong_feeds(urls, titles))
    try:
        first = go(feeds.poll(30))
        assert sorted(e.title for e in first) == ["Article a", "Article b"]
        assert go(feeds.poll(30)) == []  # chaque adresse retrouve sa ligne : rien n'est neuf, rien n'est perdu
        health = feeds.health()
        assert [h["kept"] for h in health] == [1, 1] and all(h["ok_at"] and not h["error"] for h in health)
        assert health[0]["title"] == "Flux A"
        assert len(health[1]["title"]) == FEED_NAME_MAX and health[1]["title"].startswith("Le flux B")  # coupé
        assert all("sss" not in h["url"] for h in health)  # l'adresse montrée vient des réglages, sans son jeton
        with feeds._session() as s:
            stored = sorted(s.scalars(select(FeedRow.url)).all())
            keys = sorted(set(s.scalars(select(EntryRow.feed_url)).all()))
        assert stored == keys == sorted(feeds_fit(u, URL_MAX) for u in urls)
        assert feeds.feed_counts() == {"Flux A": 1, health[1]["title"]: 1}
    finally:
        feeds.close()


def test_an_overlong_article_id_designates_nothing_and_raises_nothing(tmp_path):
    feeds = HttpFeeds(lambda: [], tmp_path / "f.db")
    try:
        with feeds._session.begin() as s:
            s.execute(insert(EntryRow), [entry_values(id="a1", feed_url="https://ex.test/rss", feed="Ex", title="T",
                                                      link="", summary="", published=1, handed=True, n=1,
                                                      seen_at=0)])
        assert go(feeds.entry("x" * 5000)) is None and go(feeds.article("x" * 5000)) == ""
        assert feeds.entry_count(exclude=("x" * 5000,)) == 1 and feeds.entry_count(exclude=("a1",)) == 0
    finally:
        feeds.close()


def batch(*messages: InboxMessage, conversations: tuple[InboxConversation, ...] = ()) -> InboxBatch:
    return InboxBatch("8:orgid:moi", "Moi", conversations, messages)


def test_an_overlong_teams_id_is_kept_by_its_digest_and_found_by_the_whole_id(tmp_path):
    long_a = "19:" + "c" * 400 + "a@thread.v2"
    long_b = "19:" + "c" * 400 + "b@thread.v2"
    author = "8:orgid:" + "X" * 300
    store = TeamsStore(lambda: TeamsConfig(), tmp_path / "teams.db", now=lambda: NOW)
    try:
        stored = store.store_batch(batch(
            InboxMessage("1", long_a, "Bob", author, NOW // 1000, "salut A"),
            InboxMessage("2", long_b, "Chloé", "8:c", NOW // 1000, "salut B"),
            conversations=(InboxConversation(long_a, "Projet A", "group"),
                           InboxConversation(long_b, "Projet B", "group"))), NOW)
        assert stored.new == 2
        a, b = store.conversation(long_a), store.conversation(long_b)
        assert a is not None and b is not None and a.id != b.id and len(a.id) == CONVERSATION_MAX
        assert (a.title, a.messages, store.title(long_b)) == ("Projet A", 1, "Projet B")
        assert [m.text for m in store.thread(long_a, 10)] == ["salut A"]
        assert store.message(message_ref(long_a, "1")).conversation == a.id
        # le même lot rejoué : chaque message retrouve sa ligne
        again = store.store_batch(batch(InboxMessage("1", long_a, "Bob", author, NOW // 1000, "salut A")), NOW)
        assert (again.new, again.known) == (0, 1)
        draft = store.save_draft(Draft(id="", conversation=long_a, body="Bonjour"))
        assert store.draft(draft.id).conversation == a.id
        # une référence cherchée trop longue ne désigne rien
        assert store.message("t" * 500) is None and store.draft("d" * 500) is None
        assert store.drafts(5, state="e" * 100) == []
        with store._session() as s:
            [key] = s.scalars(select(MessageRow.author_key).where(MessageRow.author_id == author)).all()
        assert key == teams_fit(author.lower(), AUTHOR_MAX)
        # oublier quelqu'un par son identifiant entier
        assert go(store.forget("teams:" + author)) >= 1 and store.message(message_ref(long_a, "1")) is None
    finally:
        store.close()


# ── La recherche : casse et accents ignorés, pareil sur les deux moteurs ──


def test_feed_search_ignores_case_and_accents_and_takes_wildcards_literally(tmp_path):
    feeds = HttpFeeds(lambda: [], tmp_path / "f.db")
    titles = ["Été caniculaire", "ÉTÉ indien", "Un ete pourri", "Hiver", "Hausse de 100% du blé", "Le module a_b"]
    try:
        with feeds._session.begin() as s:
            s.execute(insert(EntryRow), [
                entry_values(id=f"e{i}", feed_url="https://ex.test/rss", feed="Création Ŀibre" if i % 2 else "Autre",
                             title=t, link="", summary="", published=i, handed=True, n=i, seen_at=0)
                for i, t in enumerate(titles)])
        found = {q: {e.title for e in feeds.entries_page(text=q).items} for q in ("ÉTÉ", "ete", "Été", "eTe")}
        assert all(v == set(titles[:3]) for v in found.values()), found
        assert feeds.entries_page(feed="CREATION").total == feeds.entries_page(feed="création").total == 3
        assert feeds.entry_count("CRÉATION") == 3
        assert [e.title for e in feeds.entries_page(text="%").items] == ["Hausse de 100% du blé"]
        assert [e.title for e in feeds.entries_page(text="_").items] == ["Le module a_b"]
        assert feeds.entries_page(text="BLE").total == 1  # « blé »
    finally:
        feeds.close()


def test_teams_conversation_search_ignores_case_and_accents_and_takes_wildcards_literally(tmp_path):
    store = TeamsStore(lambda: TeamsConfig(), tmp_path / "teams.db", now=lambda: NOW)
    titled = {"19:un@thread.v2": "Équipe Projet", "19:deux@thread.v2": "EQUIPE de nuit",
              "19:trois@thread.v2": "l'equipe support", "19:quatre@thread.v2": "Autre",
              "19:cinq@thread.v2": "Prêt à 100%", "19:six@thread.v2": "module a_b"}
    try:
        store.store_batch(batch(
            *[InboxMessage(str(i), conv, "Bob", "8:b", NOW // 1000 - i, "message") for i, conv in enumerate(titled)],
            conversations=tuple(InboxConversation(conv, title, "group") for conv, title in titled.items())), NOW)
        for q in ("équipe", "EQUIPE", "Équipe", "eQuIpE"):
            assert {c.title for c in store.conversations(10, text=q)} == set(list(titled.values())[:3]), q
        assert [c.title for c in store.conversations(10, text="%")] == ["Prêt à 100%"]
        assert [c.title for c in store.conversations(10, text="_")] == ["module a_b"]
        assert [c.id for c in store.conversations(10, text="QUATRE@THREAD")] == ["19:quatre@thread.v2"]
        assert len(store.conversations(10)) == 6
    finally:
        store.close()


# ── Aucun SQL propre à SQLite ─────────────────────────────────────────────

#: ce qu'aucune chaîne de ces adaptateurs ne contient (ce que les aides de ``ports/sql`` écrivent pour chaque moteur)
FORBIDDEN = re.compile(
    r"\bINSERT\s+OR\b|\bON\s+CONFLICT\b|\bjson_each\b|\bjson_extract\b|\|\||\browid\b|\bPRAGMA\b|\bsqlite_master\b"
    r"|\bWITHOUT\s+ROWID\b|\bESCAPE\b|\bLIKE\b|\b(?:MAX|MIN)\s*\([^()]*,|\bexcluded\.", re.I)
#: les portes du SQL écrit en clair, ou d'une fonction Python appelée depuis le SQL
RAW = {"text", "exec_driver_sql", "executescript", "executemany", "create_function", "literal_column"}
CALLS_WITH_SQL = {"execute", "exec_driver_sql", "executemany", "executescript", "text"}


def _docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def violations(source: str) -> list[str]:
    tree = ast.parse(source)
    docs = _docstrings(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs \
                and FORBIDDEN.search(node.value):
            found.append(f"chaîne : {node.value!r}")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
            if any(n and n.split(".")[0] == "sqlite3" for n in names):
                found.append("import sqlite3")
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            if name in RAW:
                found.append(f"appel : {name}")
            if name in CALLS_WITH_SQL and node.args and isinstance(node.args[0], (ast.Constant, ast.JoinedStr)):
                found.append(f"SQL écrit en clair : {name}")
            if name in ("max", "min") and isinstance(f, ast.Attribute) and len(node.args) > 1:
                found.append(f"{name} scalaire")
    return found


def test_the_checker_sees_what_it_is_meant_to_see():
    """Le contrôle lui-même : il voit le SQL de SQLite écrit en clair, jamais une docstring qui en parle."""
    bad = ('import sqlite3\n'
           'db.execute("INSERT OR IGNORE INTO t VALUES(?)", (1,))\n'
           'q = "SELECT value FROM json_each(?) WHERE a || b"\n'
           'x = select(func.max(T.a, T.b))\n'
           'db.create_function("fold", 1, f)\n'
           'y = text("DELETE FROM t WHERE rowid IN (SELECT 1)")\n')
    assert len(violations(bad)) >= 6
    assert violations('"""On n\'écrit jamais INSERT OR REPLACE ni rowid."""\nx = select(func.max(T.a))\n') == []


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_sqlite_only_sql_in_feeds_and_teams(path):
    assert violations(path.read_text(encoding="utf-8")) == []


# ── Le schéma tient sous MariaDB ──────────────────────────────────────────


def _length(column) -> int:
    return column.type.length if isinstance(column.type, String) else 0


def test_keys_and_indexes_are_bounded_varchars_under_mariadb_limits():
    dialect = MariaDBDialect()
    assert set(FEEDS.tables) == {"entries", "feeds"}
    assert set(TEAMS.tables) == {"meta", "conversations", "messages", "drafts"}
    for metadata in (FEEDS, TEAMS):
        for table in metadata.sorted_tables:
            CreateTable(table).compile(dialect=dialect)
            groups = [("pk", list(table.primary_key.columns))]
            groups += [(ix.name, list(ix.columns)) for ix in table.indexes]
            groups += [(c.name, list(c.columns)) for c in table.constraints if c.columns and c is not
                       table.primary_key]
            for name, columns in groups:
                for column in columns:  # une clé : un VARCHAR borné, ou un entier
                    assert isinstance(column.type, Key | Integer) or column.type.python_type in (int, bool), \
                        (table.name, column.name)
                assert sum(_length(c) for c in columns) <= 768, (table.name, name)
            for ix in table.indexes:
                assert ix.name and len(ix.name) <= 64, ix
                CreateIndex(ix).compile(dialect=dialect)
            for constraint in table.constraints:
                assert constraint.name and len(str(constraint.name)) <= 64, (table.name, constraint)
