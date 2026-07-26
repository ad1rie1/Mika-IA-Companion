"""Tests du bac à sable de la Forge — validation AST, environnement
d'exécution confiné, deadline. Aucun accès DB ici."""
from __future__ import annotations

import pytest

from modules.plugins.forge import sandbox


# ---------------------------------------------------------------------------
# Validation AST — rejets
# ---------------------------------------------------------------------------


class TestValidatorRejects:
    def _assert_rejected(self, code: str, fragment: str = ""):
        errors = sandbox.validate_source(code)
        assert errors, f"aurait dû être rejeté: {code!r}"
        if fragment:
            joined = "\n".join(errors)
            assert fragment in joined, f"{fragment!r} absent de {joined!r}"

    def test_import(self):
        self._assert_rejected("import os", "import interdit")
        self._assert_rejected("from pathlib import Path", "import interdit")

    def test_dunder_attribute(self):
        self._assert_rejected("x = ().__class__", "interdit")

    def test_private_attribute(self):
        self._assert_rejected("def on_tick(api):\n    api._host", "_")

    def test_forbidden_builtins(self):
        for name in ("eval", "exec", "open", "getattr", "setattr",
                     "type", "globals", "vars", "compile", "input"):
            self._assert_rejected(f"x = {name}", "nom interdit")

    def test_dunder_name(self):
        self._assert_rejected("x = __import__", "interdit")
        self._assert_rejected("print(__name__)", "interdit")

    def test_str_format_blocked(self):
        self._assert_rejected("x = '{0}'.format(1)", ".format")
        self._assert_rejected("x = template.format_map(d)", ".format")

    def test_async_blocked(self):
        self._assert_rejected("async def on_tick(api):\n    pass", "async")

    def test_dunder_def_outside_class(self):
        self._assert_rejected("def __init__(x):\n    pass", "dunder")

    def test_syntax_error_reported(self):
        errors = sandbox.validate_source("def broken(:\n")
        assert len(errors) == 1
        assert "syntaxe" in errors[0]

    def test_oversized_source(self):
        big = "x = 1\n" * 40_000
        errors = sandbox.validate_source(big)
        assert errors and "longue" in errors[0]


# ---------------------------------------------------------------------------
# Validation AST — code légitime accepté
# ---------------------------------------------------------------------------


class TestValidatorAccepts:
    def test_typical_module(self):
        code = """
SEUIL = 10

def on_tick(api):
    valeurs = [x * 2 for x in range(5)]
    api.storage.set('data', 'valeurs', valeurs)
    api.log(f"ok {len(valeurs)}")

def on_event(api, event):
    if event['type'].startswith('rss.'):
        api.state['dernier'] = event['data']

def get_context(api):
    n = api.storage.count('data')
    return f"{n} entrées"

def view_stats(api, params):
    page = int(params.get('page') or 0)
    return {'columns': [{'key': 'k', 'label': 'K'}], 'rows': [], 'page': page}
"""
        assert sandbox.validate_source(code) == []

    def test_classes_with_allowed_dunders(self):
        code = """
class Compteur:
    def __init__(self, base):
        self.n = base
    def __repr__(self):
        return f"Compteur({self.n})"
    def inc(self):
        self.n += 1
"""
        assert sandbox.validate_source(code) == []

    def test_control_flow_and_stdlib_names(self):
        code = """
def on_tick(api):
    try:
        d = json.loads('{"a": 1}')
        m = math.sqrt(16)
        quand = datetime.datetime.now()
        h = hashlib.sha256(b'x').hexdigest()
        c = collections.Counter('aabb')
        parts = re.findall(r'\\w+', 'a b')
    except (ValueError, KeyError) as exc:
        api.error(f"oops {exc}")
"""
        assert sandbox.validate_source(code) == []

    def test_list_handlers(self):
        code = """
def on_tick(api):
    pass
def view_inbox(api, params):
    pass
def helper():
    pass
"""
        assert sandbox.list_handlers(code) == ["on_tick", "view_inbox"]


# ---------------------------------------------------------------------------
# Environnement d'exécution
# ---------------------------------------------------------------------------


class _FakeAPI:
    def __init__(self):
        self.logged = []

    def log(self, message, source="print"):
        self.logged.append(str(message))


def _run(code: str):
    api = _FakeAPI()
    printed = []
    env = sandbox.build_globals(api, lambda *a: printed.append(" ".join(map(str, a))))
    compiled = compile(code, "<forge:test>", "exec")
    exec(compiled, env)
    return env, api, printed


class TestExecutionEnv:
    def test_no_dangerous_builtins(self):
        env, _, _ = _run("x = 1")
        builtins = env["__builtins__"]
        for name in ("open", "eval", "exec", "__import__", "getattr", "type"):
            assert name not in builtins

    def test_import_fails_at_runtime_too(self):
        # Même si la validation était contournée, l'exec n'a pas __import__.
        with pytest.raises(ImportError):
            _run("exec_bypass = 0\nimport os")  # noqa — SyntaxError impossible ici
        # NB: 'import' passe compile() mais échoue sans __import__ au runtime.

    def test_classes_work(self):
        env, _, _ = _run("""
class Point:
    def __init__(self, x):
        self.x = x
p = Point(3)
resultat = p.x * 2
""")
        assert env["resultat"] == 6

    def test_print_captured(self):
        _, _, printed = _run("print('hello', 42)")
        assert printed == ["hello 42"]

    def test_safe_modules_available(self):
        env, _, _ = _run("""
a = math.floor(3.7)
b = json.dumps({'x': 1})
c = str(datetime.date(2026, 1, 1))
d = string.digits
""")
        assert env["a"] == 3
        assert env["d"] == "0123456789"

    def test_frozen_module_readonly(self):
        env, _, _ = _run("x = 1")
        frozen_math = env["math"]
        with pytest.raises(AttributeError):
            frozen_math.pi = 3
        with pytest.raises(AttributeError):
            frozen_math._private

    def test_fstrings_ok_but_no_attr_escape(self):
        # L'échappement classique par f-string est bloqué à la VALIDATION.
        assert sandbox.validate_source('x = f"{().__class__}"')


# ---------------------------------------------------------------------------
# Deadline
# ---------------------------------------------------------------------------


class TestDeadline:
    def test_interrupts_infinite_loop(self):
        def spin():
            while True:
                pass

        with pytest.raises(sandbox.ForgeTimeout):
            sandbox.run_with_deadline(spin, (), 0.2)

    def test_passes_result_through(self):
        assert sandbox.run_with_deadline(lambda a, b: a + b, (2, 3), 5.0) == 5

    def test_exceptions_propagate(self):
        def boom():
            raise ValueError("kaputt")

        with pytest.raises(ValueError, match="kaputt"):
            sandbox.run_with_deadline(boom, (), 5.0)

    def test_trace_restored(self):
        import sys
        before = sys.gettrace()
        sandbox.run_with_deadline(lambda: None, (), 1.0)
        assert sys.gettrace() is before
