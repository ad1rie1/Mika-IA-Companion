"""Module-supplied dashboard payloads must not carry raw markup.

The generic renderer injects `html` keys via innerHTML, so a module piping
an email body / RSS item / scraped page through `{html: ...}` would be
stored XSS on the admin interface — which is also where the config editor
and its secrets live.
"""
from __future__ import annotations

from utils.sanitize import sanitize_payload


class TestSanitizePayload:

    def test_strips_html_key(self):
        out = sanitize_payload({"label": "Objet", "html": "<img onerror=x>"})
        assert out == {"label": "Objet"}

    def test_strips_js_and_template(self):
        out = sanitize_payload({"js": "a.js", "template": "t.html", "k": 1})
        assert out == {"k": 1}

    def test_is_case_insensitive(self):
        assert sanitize_payload({"HTML": "<b>x</b>", "ok": 1}) == {"ok": 1}

    def test_strips_nested_inside_rows(self):
        payload = {
            "columns": [{"key": "sujet", "label": "Sujet"}],
            "rows": [
                {"sujet": "coucou", "html": "<script>alert(1)</script>"},
                {"sujet": "hello"},
            ],
        }
        out = sanitize_payload(payload)
        assert out["rows"][0] == {"sujet": "coucou"}
        assert out["rows"][1] == {"sujet": "hello"}

    def test_strips_inside_tabs(self):
        payload = {"tabs": [{"key": "a", "label": "A", "html": "<i>x</i>"}]}
        out = sanitize_payload(payload)
        assert "html" not in out["tabs"][0]

    def test_deeply_nested_is_capped_not_crashed(self):
        node: dict = {"html": "<b>x</b>"}
        for _ in range(30):
            node = {"child": node}
        out = sanitize_payload(node)  # must not recurse forever
        assert out is not None

    def test_scalars_pass_through(self):
        assert sanitize_payload("plain") == "plain"
        assert sanitize_payload(42) == 42
        assert sanitize_payload(None) is None

    def test_tuples_become_sanitized_lists(self):
        out = sanitize_payload({"rows": ({"html": "<b>"}, {"k": 2})})
        assert out["rows"] == [{}, {"k": 2}]


class TestViewOptIn:

    def test_forge_reexports_the_shared_implementation(self):
        # Two divergent copies is how one of them ends up missing a key.
        from modules.plugins.forge import views as forge_views
        assert forge_views.sanitize_view_payload is sanitize_payload
