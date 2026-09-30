"""« Veille Hacker News », l'app forgée de la v1, portée vers la Forge v2
(``examples/forge/veille_hn``) : son manifeste et son code passent la relecture
de la Forge ; en mode demo (sans réseau), un passage garde des histoires, les
consigne, les élague ; ses trois vues se décodent sans une violation ; ses
actions répondent {ok, message} ; un titre de flux qu'elle remarque fait
remonter les histoires qui en parlent — jamais une conversation."""

from __future__ import annotations

import asyncio
import copy
import json
import shutil
from pathlib import Path

import pytest

from mika.adapters.forge import ForgeHost, read_manifest
from mika.adapters.forge.manifest import coherence, signatures
from mika.kernel.inspect import ActionSlot, Chart, Disclosure, Fields, Grid, Row, Section, Stats, Table
from mika.plugins.forge.views import decode_view, is_invalid

APP = Path(__file__).resolve().parents[2] / "examples" / "forge" / "veille_hn"
MANIFEST, CODE = (APP / "manifest.yaml").read_text(encoding="utf-8"), (APP / "main.py").read_text(encoding="utf-8")


class Api:
    """L'api d'une app, en mémoire (le bac à sable n'est pas nécessaire pour la logique)."""

    def __init__(self, config):
        self.store, self.cfg, self.signals, self.emitted, self.logs = {}, dict(config), [], [], []

    def kv_get(self, key, default=None):
        return copy.deepcopy(self.store.get(key, default))

    def kv_set(self, key, value):
        self.store[key] = json.loads(json.dumps(value))
        return True

    def kv_delete(self, key):
        self.store.pop(key, None)
        return True

    def kv_keys(self, prefix=""):
        return sorted(k for k in self.store if k.startswith(prefix))

    def config(self, key, default=None):
        return self.cfg.get(key, default)

    def log(self, *parts):
        self.logs.append(" ".join(str(p) for p in parts))

    def emit(self, type, data=None):
        self.emitted.append((type, data))

    def signal(self, summary, pertinence=0.3, emotion=""):
        self.signals.append(summary)

    def http_get(self, url):
        raise RuntimeError("pas de réseau en mode demo")


def walk(blocks):
    for b in blocks:
        yield b
        if isinstance(b, Section | Disclosure | Grid):
            yield from walk(b.items)
        elif isinstance(b, Table):
            yield from walk([x for r in b.rows if isinstance(r, Row) for x in r.detail])


def test_the_ported_app_passes_the_forge_review():
    manifest, problems = read_manifest(MANIFEST)
    code_problems, functions = signatures(CODE)
    assert problems == [] and code_problems == [] and coherence(manifest, functions) == []
    assert {"tick", "context", "on_event", "view_veille", "view_passages", "view_bac", "action_veille_recolter",
            "action_veille_purger"} <= set(functions)


def test_a_demo_watch_keeps_shows_and_prunes_stories(tmp_path):
    host = ForgeHost(tmp_path / "forge", bwrap="")
    asyncio.run(host.write("veille_hn", MANIFEST, CODE))
    info = host.info("veille_hn")
    specs = {s.key: s for s in info.views}
    api = Api({f.path: f.default for f in info.config_fields} | {"seuil_pepite": 0, "prevenir": True,
                                                                  "max_gardees": 10})
    app: dict = {}
    exec(compile(CODE, "main.py", "exec"), app)  # noqa: S102 — le code de l'app, en mémoire
    for _ in range(4):
        app["tick"](api)
    stories = [k for k in api.store if k.startswith("h:")]
    assert 0 < len(stories) <= 10  # gardées, puis élaguées au plafond
    assert api.signals and api.emitted[0][0] == "pepite"  # seuil 0 : chaque passage a sa pépite
    assert app["context"](api).startswith("veille HN : ")
    decoded = {}
    for key, spec in specs.items():
        value = json.loads(json.dumps(app[f"view_{key}"](api, {"page": 1})))
        decoded[key] = decode_view(value, "veille_hn", info, spec)
        assert not is_invalid(decoded[key]), (key, decoded[key])
    veille = decoded["veille"]
    table = next(b for b in walk(veille) if isinstance(b, Table))
    assert len(table.rows) == len(stories) and all(isinstance(r.detail[0], Fields) for r in table.rows)
    assert {s.action for s in walk(veille) if isinstance(s, ActionSlot)} == {"forge.agir"}
    assert any(isinstance(b, Stats) for b in veille)
    assert any(isinstance(b, Chart) for b in walk(decoded["passages"]))
    secret = next(b for b in walk(decoded["bac"]) if isinstance(b, Fields) and b.title == "Réglages lus par l'app")
    assert ("jeton (secret)", "non renseigné") in [(k, str(v)) for k, v in secret.pairs]
    # un titre de flux remarqué fait remonter les histoires qui en parlent
    title = api.store[stories[0]]["titre"]
    before = api.store[stories[0]]["score"]
    app["on_event"](api, {"type": "rss.noticed", "summary": title, "source": "rss", "kind": "entry", "at": 0})
    assert api.store[stories[0]]["score"] == before + 5 and api.emitted[-1][0] == "echo"
    # les actions de l'opérateur
    assert app["action_veille_recolter"](api, {})["ok"] is True
    purged = app["action_veille_purger"](api, {"collection": "histoires"})
    assert purged["ok"] and not [k for k in api.store if k.startswith("h:")]
    assert app["action_veille_purger"](api, {"collection": "tout"})["ok"] is False


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bubblewrap absent")
def test_it_really_runs_in_the_sandbox(tmp_path):
    """Dans le vrai bac à sable (un processus à part) : un passage, puis sa vue."""
    host = ForgeHost(tmp_path / "forge")

    async def main():
        await host.write("veille_hn", MANIFEST, CODE)
        ticked = await host.call("veille_hn", "tick", timeout_s=10)
        shown = await host.call("veille_hn", "view_veille", {"page": 1}, timeout_s=10)
        return ticked, shown

    ticked, shown = asyncio.run(main())
    assert ticked.ok, ticked.error
    assert shown.ok and shown.value["version"] == 2 and shown.value["blocks"], shown.error
