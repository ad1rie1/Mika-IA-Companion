"""L'hôte de la Forge contre son contrat : ce qu'une app forgée peut et ne
peut pas faire.

- elle ne lit ni les bases ni l'environnement du serveur, n'a pas de réseau ;
- une boucle infinie, une bombe d'expression régulière et une bombe mémoire
  sont arrêtées (tuées à leur délai, ou à leur limite) — et l'app repart à
  l'appel suivant ;
- son stockage lui est propre et borné ; ``http_get`` ne sort que vers ses
  domaines déclarés, jamais vers une adresse privée ;
- une écriture refusée ne change rien ; une version se remplace, se
  restaure ; sans bubblewrap, rien ne tourne.
"""

from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from mika.adapters.forge import ForgeHost, lint
from mika.ports.forge import ForgeRefused

needs_bwrap = pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")
MANIFEST = "title: Essai\nschedule: manual\nallowed_domains: [api.exemple.fr]\nconfig: {seuil: 3}\n"
WITH_CONTEXT = MANIFEST + "context: true\n"


def go(coro):
    return asyncio.run(coro)


def host(tmp_path, **kw):
    return ForgeHost(tmp_path / "forge", **kw)


def write(h, code, manifest=MANIFEST, app="essai"):
    return go(h.write(app, manifest, code))


@needs_bwrap
def test_an_app_sees_neither_the_databases_nor_the_environment_nor_the_network(tmp_path, monkeypatch):
    monkeypatch.setenv("MIKA_SECRET_KEY", "CANARI-cle")
    secret = tmp_path / "mind.db"
    secret.write_text("CANARI-base")
    h = host(tmp_path)
    write(h, f'''
import os
def view(api):
    out = {{"env": sorted(os.environ.items())}}
    try:
        out["db"] = open({str(secret)!r}).read()
    except OSError as exc:
        out["db"] = type(exc).__name__
    try:
        out["home"] = os.listdir({os.path.expanduser("~")!r})
    except OSError as exc:
        out["home"] = type(exc).__name__
    try:
        import urllib.request
        urllib.request.urlopen("http://1.1.1.1", timeout=2)
        out["net"] = "ouvert"
    except Exception as exc:
        out["net"] = type(exc).__name__
    return out
''')
    r = go(h.call("essai", "view"))
    assert r.ok, r.error
    assert "CANARI" not in str(r.value["env"]) and r.value["db"] in ("FileNotFoundError", "PermissionError")
    assert r.value["home"] in ("FileNotFoundError", "PermissionError") and r.value["net"] != "ouvert"
    h.shutdown()


@needs_bwrap
@pytest.mark.parametrize("bomb", [
    "while True:\n        pass",
    "import re\n    re.match(r'(a+)+$', 'a' * 40 + 'b')",  # un appel C : v1 ne pouvait pas l'interrompre
])
def test_a_runaway_call_is_killed_at_its_deadline_and_the_app_restarts(tmp_path, bomb):
    h = host(tmp_path)
    write(h, f"def tick(api):\n    {bomb}\n\ndef view(api):\n    return 'vivante'\n")
    async def both():  # dans la même boucle, comme en service (le processus ne meurt pas par hasard entre deux)
        return await h.call("essai", "tick", timeout_s=1.0), await h.call("essai", "view", timeout_s=3.0)

    r, again = go(both())
    assert not r.ok and r.killed and 900 <= r.duration_ms < 5000
    assert again.ok and again.value == "vivante"  # un processus neuf
    h.shutdown()


@needs_bwrap
def test_a_memory_bomb_hits_its_limit_not_the_server(tmp_path):
    h = host(tmp_path)
    write(h, "def tick(api):\n    x = []\n    while True:\n        x.append(' ' * 10_000_000)\n\n"
             "def view(api):\n    return 'vivante'\n")
    r = go(h.call("essai", "tick", timeout_s=10.0))
    assert not r.ok and ("MemoryError" in r.error or r.killed)
    assert go(h.call("essai", "view")).ok
    h.shutdown()


@needs_bwrap
def test_storage_config_logs_signals_and_http_go_through_the_host(tmp_path):
    fetched = []

    def http(url):
        fetched.append(url)
        return '{"prix": 12}'

    h = host(tmp_path, http_get=http, public=lambda host_: host_ == "api.exemple.fr")
    write(h, '''
def tick(api):
    n = api.kv_get("n", 0) + 1
    api.kv_set("n", n)
    print("tour", n)
    api.signal("le café a baissé", pertinence=0.6, emotion="happy")
    api.emit("prix", {"n": n})
    return {"n": n, "seuil": api.config("seuil"), "prix": api.http_get("https://api.exemple.fr/prix")}

def context(api):
    return "le café coûte " + str(api.kv_get("n"))
''', manifest=WITH_CONTEXT)
    first = go(h.call("essai", "tick"))
    second = go(h.call("essai", "tick"))
    assert first.ok and second.ok and second.value["n"] == 2 and second.value["seuil"] == 3
    assert second.signals == (("le café a baissé", 0.6, "happy"),) and second.emits == (("prix", '{"n": 2}'),)
    assert "tour 2" in second.logs and h.logs("essai")[-1] == "tour 2"
    assert fetched == ["https://api.exemple.fr/prix"] * 2
    write(h, 'def tick(api):\n    return api.http_get("http://169.254.169.254/latest")\n')
    blocked = go(h.call("essai", "tick"))
    assert not blocked.ok and "allowed_domains" in blocked.error
    # un domaine déclaré qui pointe vers une adresse privée : refusé quand même
    write(h, 'def tick(api):\n    return api.http_get("https://interne.exemple.fr/admin")\n',
          manifest="title: Essai\nallowed_domains: [interne.exemple.fr]\n")
    private = go(h.call("essai", "tick"))
    assert not private.ok and "privée" in private.error and "https://interne.exemple.fr/admin" not in fetched
    h.shutdown()


def test_a_refused_write_changes_nothing_and_versions_can_be_restored(tmp_path):
    h = host(tmp_path, bwrap="")
    assert write(h, "def view(api):\n    return 1\n")[0] == 1
    with pytest.raises(ForgeRefused, match="syntaxe"):
        write(h, "def view(api) return 2\n")
    with pytest.raises(ForgeRefused, match="import subprocess"):
        write(h, "import subprocess\ndef view(api):\n    return 2\n")
    with pytest.raises(ForgeRefused, match="context"):
        write(h, "def view(api):\n    return 2\n", manifest="title: x\ncontext: true\n")
    assert h.source("essai")[1] == "def view(api):\n    return 1\n" and h.info("essai").version == 1
    assert write(h, "def view(api):\n    return 2\n")[0] == 2
    assert go(h.rollback("essai")) == 3 and "return 1" in h.source("essai")[1]
    go(h.erase("essai"))
    assert h.info("essai") is None and any((tmp_path / "forge" / "_corbeille").iterdir())


def test_without_bubblewrap_no_app_runs(tmp_path):
    h = host(tmp_path, bwrap="")
    write(h, "def view(api):\n    return 1\n")
    r = go(h.call("essai", "view"))
    assert not r.ok and "bubblewrap" in r.error


def test_the_lint_explains_in_french():
    problems, functions = lint("import socket\ndef nothing():\n    pass\n")
    assert any("import socket" in p for p in problems) and any("aucune fonction attendue" in p for p in problems)
    assert functions == {"nothing"}
