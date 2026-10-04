"""Telegram est retiré (ADR 0060) : on écrit à Mika par une application dédiée, jamais par un robot.

Ce qui reste, c'est la gestion des identités inconnues sur un canal non sécurisé — un compte sur un
réseau extérieur (``ext_…``), où elle échangera en naviguant d'elle-même : un compte stable qui ne prouve
pas qui le tient, une messagerie où l'on lit quand on y pense, et des salons publics.
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

from mika.adapters.store_sqlite import SqliteStore
from mika.app.settings import RETIRED_KEYS, SecretBox, Settings
from mika.vocab import privacy
from mika.vocab.people import EXTERNAL_PREFIX, RESERVED_PREFIXES
from mika.vocab.privacy import ChannelTrust

SRC = Path(__file__).resolve().parents[2] / "src" / "mika"


def test_the_retired_settings_row_and_its_sealed_token_are_erased_at_open(tmp_path):
    """Une installation qui avait un robot garde dans ``mind.db`` son jeton scellé : plus rien ne le lit, il
    ne reste ni dans la base ni dans ses sauvegardes. Le reste des réglages ne bouge pas."""

    async def run() -> tuple[list[str], str]:
        store = SqliteStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
        await store.open()
        box = SecretBox.for_data(tmp_path)
        settings = Settings(store, box)
        await settings.open()
        await settings._put("telegram", {"token_sealed": box.seal("123:secret"), "owners": [42]})
        await settings._put("feeds", {"urls": ["https://flux.example/rss"]})
        await Settings(store, box).open()  # le redémarrage suivant
        keys = [row[0] for row in store.query_mind("SELECT key FROM settings ORDER BY key")]
        feeds = json.dumps(Settings(store, box)._get("feeds"))
        await store.close()
        return keys, feeds

    keys, feeds = asyncio.run(run())
    assert "telegram" in RETIRED_KEYS and "telegram" not in keys
    assert "flux.example" in feeds


def _modules() -> list[tuple[Path, ast.Module]]:
    return [(p, ast.parse(p.read_text(encoding="utf-8"))) for p in sorted(SRC.rglob("*.py"))]


def test_no_module_imports_a_telegram_library_or_adapter():
    for path, tree in _modules():
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not [n for n in names if n.split(".")[0] == "telegram" or n.startswith("mika.adapters.telegram")], \
                path


def test_no_code_names_the_telegram_channel_except_the_retired_settings_key():
    """Sur l'arbre syntaxique, pas sur le texte : un commentaire qui rappelle ce qui a été retiré ne compte pas."""
    found = []
    for path, tree in _modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.strip().lower()
                if value == "telegram" or value.startswith("tg_"):
                    found.append(str(path.relative_to(SRC)))
    assert found == ["app/settings.py"]


def test_an_external_account_is_an_unproven_messaging_account():
    """Un compte extérieur prouve que le même compte est revenu, jamais qui le tient ; on y lit quand on y
    pense ; dans un salon, il ne prouve rien de plus que la salle. Le web reste un écran."""
    assert privacy.channel_of(f"{EXTERNAL_PREFIX}42") == privacy.EXTERNAL
    assert privacy.channel_of("user_7") == privacy.channel_of("web_abc") == privacy.WEB
    assert privacy.channel_trust(privacy.EXTERNAL) == ChannelTrust.ACCOUNT
    assert privacy.channel_trust(privacy.EXTERNAL, public=True) == ChannelTrust.PUBLIC
    assert privacy.CEILINGS[ChannelTrust.ACCOUNT] < privacy.VERIFIED  # aucune conversation n'y vaut une connexion
    assert privacy.is_messaging(privacy.EXTERNAL) and not privacy.is_messaging(privacy.WEB)
    assert privacy.channel_trust("telegram") == ChannelTrust.PUBLIC  # un transport que plus rien ne décrit
    assert EXTERNAL_PREFIX in RESERVED_PREFIXES  # un navigateur ne peut pas se faire passer pour un compte extérieur
