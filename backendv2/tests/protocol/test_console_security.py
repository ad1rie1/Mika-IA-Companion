"""La console est une surface d'attaque : elle affiche des textes venus de
partout (messages, mails, flux, apps forgées, persona). Aucun ne devient du
balisage, aucune page n'exécute de script en ligne, chaque réponse porte sa
politique de sécurité."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from mika.app.console import NAVIGATION
from mika.inspector.pages import TABS
from mika.runtime import inspection
from tests.protocol.test_web import WS, bootstrap, recv_until, world  # noqa: F401 — fixture partagée

INSPECTOR = Path(__file__).resolve().parents[2] / "src" / "mika" / "inspector"
TAG = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*)>")
PAYLOAD = '<script>alert("xss")</script><img src=x onerror=alert(1)>'


def pages(client, live) -> list[str]:
    urls = []
    views = client.portal.call(inspection.views, live.kernel)
    for group in NAVIGATION:
        for d in group.items:
            base = "/inspecteur/" if d.key == "accueil" else f"/inspecteur/{d.key}"
            urls.append(base)
            if d.layout == "tabs":
                # les onglets à part (href) : leur propre page ; les réglages déclarés : leur onglet
                urls += [TABS.items[k].href if k in TABS.items and TABS.items[k].href else f"{base}/{k.split('.', 1)[1]}"
                         for k in d.builtin]
                urls += [f"{base}/{v.name}" for v in views if v.section == d.key]
    return urls


def test_hostile_text_is_escaped_and_no_page_runs_inline_code(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "message": PAYLOAD, "client_msg_id": "x1"})
        recv_until(ws, "speech")
    ended = client.portal.call(lambda: live.kernel.mind.store.latest(["episode.ended"], 1))[0]
    urls = pages(client, live) + [f"/inspecteur/episode/{ended.correlation}?onglet={t}"
                                  for t in ("deroule", "dit", "prompt", "outils", "appels", "decision")]
    seen_payload = False
    for url in urls:
        r = client.get(url)
        assert r.status_code == 200, url
        csp = r.headers.get("content-security-policy", "")
        assert "script-src 'self'" in csp and "default-src 'none'" in csp and "frame-ancestors 'none'" in csp, url
        assert r.headers.get("x-content-type-options") == "nosniff"
        body = r.text
        assert "<script>alert" not in body and "<img src=x" not in body, url
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", body), f"script en ligne : {url}"
        for tag in TAG.finditer(body):  # les attributs des vraies balises, pas le texte échappé
            attrs = tag.group(2)
            assert not re.search(r"\son[a-z]+\s*=", attrs), f"gestionnaire en ligne : {url} {tag.group(0)[:80]}"
            assert not re.search(r"\sstyle\s*=", attrs), f"style en ligne : {url} {tag.group(0)[:80]}"
        seen_payload |= "&lt;script&gt;alert(" in body
    assert seen_payload  # le texte hostile est bien montré… en texte


def test_only_audited_renderers_make_markup():
    offenders = []
    for path in INSPECTOR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "Markup":
                if path.name not in {"svg.py", "document.py"}:
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
    templates = [p for p in (INSPECTOR / "templates").rglob("*.html") if "|safe" in p.read_text(encoding="utf-8")]
    assert templates == []
