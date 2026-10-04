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
import ipaddress
import os
import shutil
import socket

import pytest

from mika.adapters import forge as forge_adapter
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


# ── Manifeste v2 : vues, actions, réglages typés ──────────────────────────

V2 = """\
title: Météo
config:
  - {key: ville, type: str, label: Ville, group: Lieu, default: Paris}
  - {key: cle_api, type: secret, label: Clé d'API}
  - {key: n, type: int, min: 1, max: 20, default: 5}
  - {key: villes, type: lines, default: [Paris, Lyon]}
  - {key: unite, type: select, choices: [celsius, {value: fahrenheit, label: Fahrenheit}], default: celsius}
views:
  - key: jour
    label: Aujourd'hui
    params: [{key: ville, label: Ville, kind: search}, {key: n, kind: int, default: 3}]
    actions:
      - {key: rafraichir, label: Rafraîchir, fields: [{key: ville, type: text, required: true, max_length: 40}]}
"""
V2_CODE = '''\
def view_jour(api, params):
    return {"version": 2, "blocks": [{"type": "note", "text": "il fait beau à " + (params.get("ville") or "?")}]}

def action_jour_rafraichir(api, data):
    return {"ok": True, "message": "rafraîchi : " + data["ville"]}

def view_cachee(api, params):
    return {"version": 2, "blocks": []}

def action_jour_secret(api, data):
    return {"ok": True, "message": "jamais"}

def tool_cache(api, args):
    return "jamais"
'''


def refused(h, manifest, code=V2_CODE, app="meteo") -> str:
    with pytest.raises(ForgeRefused) as info:
        write(h, code, manifest=manifest, app=app)
    return str(info.value)


def test_a_v2_manifest_declares_typed_settings_views_and_actions(tmp_path):
    h = host(tmp_path, bwrap="")
    write(h, V2_CODE, manifest=V2, app="meteo")
    info = h.info("meteo")
    assert info.error == ""
    fields = {f.path: f for f in info.config_fields}
    assert [f.kind for f in info.config_fields] == ["text", "secret", "int", "lines", "select"]
    assert fields["ville"].group == "Lieu" and fields["ville"].default == "Paris"
    assert fields["cle_api"].secret and fields["cle_api"].default is None
    assert (fields["n"].lo, fields["n"].hi, fields["n"].default) == (1.0, 20.0, 5)
    assert fields["villes"].default == ["Paris", "Lyon"]
    assert fields["unite"].choices == (("celsius", "celsius"), ("fahrenheit", "Fahrenheit"))
    assert dict(info.config) == {"ville": "Paris", "n": 5, "unite": "celsius"}  # la forme simple : ni secret, ni liste
    [view] = info.views
    assert (view.key, view.label, view.function) == ("jour", "Aujourd'hui", "view_jour")
    assert [(p.key, p.kind, p.default) for p in view.params] == [("ville", "search", ""), ("n", "int", "3")]
    [action] = view.actions
    assert action.function == "action_jour_rafraichir" and action.fields[0].required
    assert action.rules[0].max_length == 40
    # seules les fonctions déclarées (et les fixes présentes) s'appellent
    assert set(info.callable) == {"view_jour", "action_jour_rafraichir"}


@pytest.mark.parametrize(("manifest", "expected"), [
    (V2.replace("type: int, min: 1", "type: entier, min: 1"),
     "config[2] (« n ») : type inconnu « entier » (au choix : str, text, int, float, bool, secret, select, lines)"),
    (V2.replace("label: Clé d'API}", "label: Clé d'API, default: sk-123}"),
     "config[1] (« cle_api ») : un secret n'a jamais de valeur par défaut"),
    (V2.replace("default: 5}", "default: 50}"), "config[2] (« n ») : « default » est hors de [min, max]"),
    (V2.replace("choices: [celsius, {value: fahrenheit, label: Fahrenheit}], ", ""),
     "config[4] (« unite ») : « choices » est requis"),
    (V2.replace("{key: n, kind: int, default: 3}", "{key: page, kind: int}"),
     "views[0] (« jour »).params[1] (« page ») : « page » est réservé à la console"),
    (V2.replace("type: text, required: true", "type: couleur, required: true"),
     "views[0] (« jour »).actions[0] (« rafraichir »).fields[0] (« ville ») : type inconnu « couleur »"),
    (V2.replace("{key: ville, type: text, required: true", "{key: app, type: text, required: true"),
     "« app » est réservé au formulaire"),
    (V2.replace("label: Aujourd'hui", "label: Aujourd'hui\n    couleur: bleue"),
     "views[0] (« jour ») : option(s) inconnue(s) : couleur"),
])
def test_an_invalid_v2_manifest_is_refused_in_french_naming_the_field(tmp_path, manifest, expected):
    assert expected in refused(host(tmp_path, bwrap=""), manifest)


def test_each_declared_view_and_action_needs_its_function_with_its_signature(tmp_path):
    h = host(tmp_path, bwrap="")
    missing = refused(h, V2, V2_CODE.replace("def view_jour(api, params):", "def vue_du_jour(api, params):"))
    assert "la vue « jour » est déclarée sans fonction view_jour(api, params)" in missing
    arity = refused(h, V2, V2_CODE.replace("def action_jour_rafraichir(api, data):", "def action_jour_rafraichir(api):"))
    assert "action_jour_rafraichir doit accepter 2 arguments : action_jour_rafraichir(api, data)" in arity
    twins = V2.replace("    actions:\n", "    actions:\n      - {key: b_c}\n") \
        .replace("  - key: jour", "  - key: a\n    actions: [{key: b_c}]\n  - key: a_b\n    actions: [{key: c}]\n"
                 "  - key: jour")
    assert "donneraient la même fonction action_a_b_c" in refused(h, twins)
    assert h.info("meteo") is None  # rien n'a été écrit


def test_an_old_manifest_still_loads(tmp_path):
    h = host(tmp_path, bwrap="")
    write(h, "def view(api):\n    return [api.config('seuil')]\n\ndef tick(api):\n    return 1\n",
          manifest="title: Ancienne\nconfig: {seuil: 3, actif: false, ratio: 0.5, nom: Mika}\n", app="ancienne")
    info = h.info("ancienne")
    assert info.error == "" and dict(info.config) == {"seuil": 3, "actif": False, "ratio": 0.5, "nom": "Mika"}
    assert [(f.path, f.kind, f.default) for f in info.config_fields] == [
        ("seuil", "int", 3), ("actif", "bool", False), ("ratio", "float", 0.5), ("nom", "text", "Mika")]
    [view] = info.views  # une view(api) seule devient la vue « principale »
    assert (view.key, view.function, view.label) == ("principale", "view", "Ancienne")
    assert set(info.callable) == {"view", "tick"}


def test_secret_settings_never_appear_in_the_app_info(tmp_path):
    h = host(tmp_path, bwrap="", config=lambda app: {"cle_api": "sk-TRES-SECRET"})
    write(h, V2_CODE, manifest=V2, app="meteo")
    assert "sk-TRES-SECRET" not in repr(h.info("meteo")) and "sk-TRES-SECRET" not in repr(h.apps())


@needs_bwrap
def test_only_declared_functions_can_be_called(tmp_path):
    h = host(tmp_path)
    write(h, V2_CODE, manifest=V2, app="meteo")
    ok = go(h.call("meteo", "view_jour", {"ville": "Lyon", "page": 1}))
    assert ok.ok and ok.value["blocks"][0]["text"] == "il fait beau à Lyon"
    act = go(h.call("meteo", "action_jour_rafraichir", {"ville": "Lyon"}))
    assert act.ok and act.value == {"ok": True, "message": "rafraîchi : Lyon"}
    for undeclared in ("view_cachee", "action_jour_secret", "tool_cache", "tick", "__import__"):
        r = go(h.call("meteo", undeclared))
        assert not r.ok and "n'est pas une fonction déclarée" in r.error, undeclared
    h.shutdown()


FRAGILE = """\
title: Fragile
views:
  - {key: lente, label: Lente}
  - {key: grosse, label: Grosse}
  - {key: invalide, label: Invalide}
  - {key: vivante, label: Vivante}
"""
FRAGILE_CODE = '''\
def view_lente(api, params):
    while True:
        pass

def view_grosse(api, params):
    return {"version": 2, "blocks": [{"type": "prose", "text": "x" * 9000}] * 40}

def view_invalide(api, params):
    return {"version": 2, "blocks": [{"type": "table", "columns": ["a"], "rows": [["x", "y"]]}]}

def view_vivante(api, params):
    return {"version": 2, "blocks": [{"type": "note", "text": "vivante"}]}
'''


@pytest.mark.slow
@needs_bwrap
def test_a_slow_huge_or_invalid_view_becomes_a_note_and_the_app_lives_on(tmp_path):
    from mika.kernel.inspect import Note
    from mika.plugins.forge.views import render, view_params

    h = host(tmp_path)
    write(h, FRAGILE_CODE, manifest=FRAGILE, app="fragile")
    info = h.info("fragile")

    async def show(key):
        spec = next(v for v in info.views if v.key == key)
        return await render(h, "fragile", info, spec, view_params(spec, {})[0], cache_s=0)

    async def all_of_them():
        return {k: await show(k) for k in ("lente", "grosse", "invalide", "vivante")}

    got = go(all_of_them())
    [slow], [huge], [bad], [alive] = got["lente"], got["grosse"], got["invalide"], got["vivante"]
    assert isinstance(slow, Note) and "plus de 3 s" in slow.text and "Rien n'est compté" in slow.text
    assert isinstance(huge, Note) and "trop de données" in huge.text and "256 Ko" in huge.text
    assert bad.title == "Vue invalide" and "blocks[0].rows[0] : 2 cellules pour 1 colonnes" in bad.text
    assert alive == Note("vivante")  # l'app repart après avoir été tuée
    h.shutdown()


# ── http_get : une seule résolution, Internet seulement, une durée totale (PRJ-16) ──


@pytest.mark.parametrize("address, public", [
    ("93.184.216.34", True), ("2606:2800:220:1:248:1893:25c8:1946", True),
    ("127.0.0.1", False), ("10.1.2.3", False), ("192.168.1.1", False), ("169.254.169.254", False),
    ("100.64.0.1", False),  # l'espace partagé d'un opérateur (CGNAT) : pas Internet
    ("::1", False), ("fd00::1", False), ("fe80::1", False),
    ("::ffff:10.0.0.1", False),  # une adresse privée déguisée en IPv6
    ("64:ff9b::a00:1", False),  # …derrière le préfixe NAT64
    ("64:ff9b::5db8:d822", True),  # une adresse publique derrière NAT64, elle, l'est
    ("2002:a00:1::", False),  # 6to4 vers 10.0.0.1
    ("224.0.0.1", False), ("0.0.0.0", False),
])
def test_only_an_internet_address_is_public(address, public):
    assert forge_adapter.is_global(ipaddress.ip_address(address)) is public


class _Answer:
    status_code = 200

    def __init__(self, chunks):
        self.chunks = chunks

    def iter_bytes(self):
        yield from self.chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_http_get_resolves_once_and_connects_to_the_address_it_checked(monkeypatch):
    """Le DNS qui répond une adresse publique au contrôle puis la machine elle-même à la connexion (le
    « rebinding ») ne joint rien : on se connecte à l'adresse vérifiée, le nom ne sert qu'à l'en-tête et au
    certificat."""
    answers = iter([[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
                    [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]])
    resolved, seen = [], {}

    def getaddrinfo(host, port, *args, **kwargs):
        resolved.append(host)
        return next(answers)

    class Client:
        def __init__(self, **kw):
            seen["client"] = kw

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def stream(self, method, url, headers=None, extensions=None):
            seen.update(url=url, headers=headers, extensions=extensions)
            return _Answer([b"ok"])

    monkeypatch.setattr(forge_adapter.socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(forge_adapter.httpx, "Client", Client)
    assert forge_adapter.real_http_get("https://api.exemple.fr/prix?j=1") == "ok"
    assert resolved == ["api.exemple.fr"]  # une seule résolution
    assert seen["url"] == "https://93.184.216.34:443/prix?j=1"
    assert seen["headers"]["Host"] == "api.exemple.fr" and seen["extensions"] == {"sni_hostname": "api.exemple.fr"}
    assert seen["client"]["follow_redirects"] is False and seen["client"]["trust_env"] is False
    monkeypatch.setattr(forge_adapter.socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                                         (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))])
    with pytest.raises(ValueError, match="privée"):  # une seule adresse privée parmi les réponses suffit
        forge_adapter.real_http_get("https://melange.exemple.fr/")


def test_http_get_stops_at_the_call_deadline_not_per_read(monkeypatch):
    """Une réponse qui goutte (un octet de temps en temps, sans jamais dépasser le délai d'une lecture) s'arrête au
    délai de l'appel."""
    clock = iter(range(0, 10_000))
    monkeypatch.setattr(forge_adapter.time, "monotonic", lambda: float(next(clock)))
    monkeypatch.setattr(forge_adapter.socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])

    class Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def stream(self, method, url, headers=None, extensions=None):
            return _Answer([b"x"] * 1000)

    monkeypatch.setattr(forge_adapter.httpx, "Client", Client)
    with pytest.raises(RuntimeError, match="délai"):
        forge_adapter.real_http_get("https://lent.exemple.fr/", deadline=20.0)
