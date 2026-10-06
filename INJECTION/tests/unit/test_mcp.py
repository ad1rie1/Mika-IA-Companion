"""Le serveur MCP « jumeau » : protocole, outils de lecture, écriture seulement sur demande."""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from twin.corpus import Corpus, SourceStats
from twin.mcp.server import build_server
from twin.people import resolve_people
from twin.records import NOTES, WHATSAPP, Author, Conversation, Document, Message
from twin.sessions import build_sessions
from twin.timing import Origin, Temps, to_us

TZ = ZoneInfo("Europe/Paris")


def corpus(tmp_path: Path) -> Corpus:
    c = Corpus(tmp_path / "travail" / "corpus.db")
    t = to_us(datetime(2015, 6, 20, 15, 0, tzinfo=TZ))
    items: list[Any] = [
        Author(WHATSAPP, "Julie Martin", name="Julie Martin", me=False), Author(WHATSAPP, "Léa", name="Léa", me=True),
        Conversation(WHATSAPP, "Julie Martin", members=("Julie Martin", "Léa")),
        Message(WHATSAPP, "Julie Martin", "Julie Martin", "Le mariage était magnifique, merci d'être venue",
                Temps.exact(t), 0),
        Message(WHATSAPP, "Julie Martin", "Léa", "C'était génial, j'ai pleuré à la cérémonie", Temps.exact(t + 60_000_000), 1),
        Author(NOTES, "moi", me=True),
        Document(NOTES, "n#0", "note", "Souvenir", "Je repense au mariage de Julie, quelle journée.",
                 Temps.year(2015, TZ, Origin.PATH), 0),
    ]
    with c.transaction():
        sid = c.begin_source("x", "x", "test", 1, 0, "now")
        c.add_items(sid, items, SourceStats())
    c.rebuild_search()
    resolve_people(c, tmp_path / "travail" / "personnes.yaml", TZ)
    build_sessions(c)
    return c


def rpc(server: Any, method: str, params: dict[str, Any] | None = None, mid: int = 1) -> dict[str, Any]:
    line = json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
    return json.loads(server.handle_line(line))


def tool(server: Any, name: str, **args: Any) -> tuple[str, bool]:
    r = rpc(server, "tools/call", {"name": name, "arguments": args})["result"]
    return r["content"][0]["text"], r["isError"]


def test_protocole(tmp_path: Path) -> None:
    s = build_server(corpus(tmp_path), TZ)
    init = rpc(s, "initialize", {"protocolVersion": "2025-06-18"})["result"]
    assert init["protocolVersion"] == "2025-06-18" and init["serverInfo"]["name"] == "jumeau"
    assert s.handle_line(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})) is None
    names = {t["name"] for t in rpc(s, "tools/list")["result"]["tools"]}
    assert "corpus_chercher" in names and "date_fixer" not in names  # lecture seule par défaut
    prompts = {p["name"] for p in rpc(s, "prompts/list")["result"]["prompts"]}
    assert "annoter" in prompts
    assert "error" in rpc(s, "nimporte/quoi")


def test_recherche_sans_accents_et_lecture(tmp_path: Path) -> None:
    s = build_server(corpus(tmp_path), TZ)
    text, err = tool(s, "corpus_chercher", requete="ceremonie")
    assert not err
    hits = json.loads(text)
    assert hits[0]["qui"] == "elle" and "juin 2015" in hits[0]["quand"]
    session, err = tool(s, "seance_lire", ref=hits[0]["ref"])
    assert not err and "ELLE" in session and "Julie Martin (p" in session
    _, err = tool(s, "seance_lire", ref="xyz")
    assert err
    text, err = tool(s, "corpus_chercher", requete='"mariage AND')  # une requête que FTS5 refuserait telle quelle
    assert not err and (text == "aucun résultat" or isinstance(json.loads(text), list))  # nettoyée
    def locked(_args: object) -> str:
        raise sqlite3.OperationalError("database is locked")

    s.tools["corpus_stats"] = dataclasses.replace(s.tools["corpus_stats"], run=locked)
    text, err = tool(s, "corpus_stats")
    assert err and "database is locked" in text  # dite à Claude Code ; le serveur reste debout


def test_ecriture_seulement_sur_demande_et_jamais_plus_large(tmp_path: Path) -> None:
    c = corpus(tmp_path)
    ro = build_server(c, TZ)
    _, err = tool(ro, "personnes_lister")
    assert not err
    rpc_tools = {t["name"] for t in rpc(ro, "tools/list")["result"]["tools"]}
    assert "date_fixer" not in rpc_tools
    rw = build_server(c, TZ, write=True)
    did = c.db.execute("SELECT id FROM documents").fetchone()["id"]
    msg, err = tool(rw, "date_fixer", ref=f"d{did}", date="juin 2015", ancres=["m1"])
    assert not err and "recoupement" in msg
    row = c.db.execute("SELECT t_precision, t_origin FROM documents WHERE id = ?", (did,)).fetchone()
    assert (row["t_precision"], row["t_origin"]) == ("mois", "recoupement")
    # une date hors de l'estimation actuelle est un conflit, pas un écrasement
    msg, err = tool(rw, "date_fixer", ref=f"d{did}", date="2009")
    assert err and "conflit" in msg
    assert c.db.execute("SELECT t_precision FROM documents WHERE id = ?", (did,)).fetchone()[0] == "mois"


def test_serveur_stdio(tmp_path: Path) -> None:
    corpus(tmp_path).close()
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "corpus_stats", "arguments": {}}}]
    proc = subprocess.run([sys.executable, "-m", "twin.mcp", "--racine", str(tmp_path)],
                          input="\n".join(json.dumps(m) for m in msgs) + "\n", capture_output=True, text=True,
                          timeout=30, check=True)
    lines = [json.loads(ln) for ln in proc.stdout.splitlines()]
    assert [m["id"] for m in lines] == [1, 2]  # rien sur la sortie que du JSON-RPC
    assert json.loads(lines[1]["result"]["content"][0]["text"])["messages"] == 2
