"""Le rendu des mails conserve le contenu utile, jamais du code actif."""

from html.parser import HTMLParser

import pytest

from mika.inspector.document import readable_html, readable_text
from mika.kernel.envelope import decode, encode
from mika.kernel.inspect import Note, Prose


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


@pytest.mark.parametrize("source", [
    '<script>alert(1)</script><style>body{display:none}</style><p onclick="run()">Bonjour</p>',
    '<img src=x onerror=run()><svg><a xlink:href="javascript:run()">x</a></svg><p>Bonjour</p>',
    '<iframe srcdoc="<script>run()</script>"></iframe><object data="https://x.test"></object><p>Bonjour</p>',
    '<form action="https://x.test"><input name=password><button>Bonjour</button></form>',
    '<a href="java&#x09;script:alert(1)" style="color:red" id="q-global">Bonjour</a>',
    '<math><mtext><table><mglyph><style><!--</style><img title="--><img src=x onerror=run()>"></math>Bonjour',
    '<a href="https://user:pass@example.test">Bonjour</a><a href="//example.test">x</a>',
])
def test_html_cannot_load_content_execute_code_or_inject_ui(source):
    result = str(readable_html(source))
    parsed = Tags(result)
    assert not {t for t, _ in parsed.tags} & {"script", "style", "img", "svg", "math", "iframe", "object", "input", "form", "button"}
    for _, attrs in parsed.tags:
        assert set(attrs) <= {"class", "href", "target", "rel"}
        assert not attrs.get("href", "").lower().startswith(("javascript:", "data:", "//"))
    assert "alert(1)" not in result


def test_html_preserves_links_lists_quotes_and_never_produces_a_second_h1():
    result = str(readable_html('<h1>Titre</h1><p>Bonjour <strong>Alice</strong></p><ul><li>Un</li></ul>'
                               '<blockquote>Avant</blockquote><a href="https://example.test?q=a&amp;b=c">Lien</a>'
                               '<table><tr><td>Valeur</td></tr></table>'))
    assert '<h3>Titre</h3>' in result and '<strong>Alice</strong>' in result
    assert '<li>Un</li>' in result and '<blockquote>Avant</blockquote>' in result
    assert 'href="https://example.test?q=a&amp;b=c"' in result and 'rel="noopener noreferrer nofollow"' in result
    assert '<table' not in result and 'document-cell' in result


@pytest.mark.parametrize("source", [
    "<li><div><li>A</li></div></li>" * 2 + "<h3>Faux bloc de la console</h3><a href='https://evil.example/login'>"
    "Se reconnecter</a>",  # un <li> referme ce qui l'entoure en remontant à travers un <div>
    "<p><div>x</div></p></div></div><h1>Faux</h1>",  # un bloc referme un paragraphe ouvert
    "<h1><h2>x</h2></h1></div><b>Faux</b>",  # un titre en referme un autre
    "<a href='https://a.example'><a href='https://b.example'>x</a></a></div>Faux",  # un lien en referme un autre
    "<table><tr><td><li>x</td></tr></table></div>Faux",
    "<ul><b><li>x</li></b></ul>",
])
def test_a_mail_cannot_step_out_of_its_frame_in_the_console(source):
    """Relu par un vrai parseur HTML5 (celui d'un navigateur), le mail reste dans son cadre : rien de ce qu'il
    contient ne s'affiche comme un morceau de la console."""
    html5lib = pytest.importorskip("html5lib")
    page = (f'<html><body><main><div id="cadre">{readable_html(source)}</div><p id="apres">fin</p></main>'
            "</body></html>")
    main = html5lib.parse(page, namespaceHTMLElements=False).find("body").find("main")
    assert [(k.tag, k.get("id")) for k in main] == [("div", "cadre"), ("p", "apres")]


def test_plain_text_links_are_clickable_but_text_stays_escaped():
    result = str(readable_text('Bonjour <script>x</script>\nhttps://example.test/a?q="b".'))
    assert '&lt;script&gt;x&lt;/script&gt;' in result
    assert 'href="https://example.test/a?q=&quot;b&quot;"' in result and result.endswith('</a>.')


def test_apps_keep_the_typed_language_without_raw_html():
    [block] = decode({"version": 2, "blocks": [{"type": "prose", "text": "x", "html": "<p>x</p>"}]})
    assert isinstance(block, Note) and block.tone == "danger"
    with pytest.raises(ValueError, match="HTML natif"):
        encode([Prose("x", html="<p>x</p>")])


def test_mail_cache_migrates_without_losing_messages_and_keeps_html(tmp_path):
    import sqlite3
    from dataclasses import replace

    from mika.adapters.mail.cache import MailCache
    from mika.ports.mail import Mail

    path = tmp_path / "mail.db"
    cache = MailCache(path)
    original = Mail("<one@x>", "Alice", "alice@x", "Sujet", 1, "Bonjour", account="pro", folder="INBOX", has_html=True)
    cache.store(original, 3)
    cache.close()
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE messages DROP COLUMN html")  # état du schéma précédent
    cache = MailCache(path)
    # la référence attribuée par le cache est la forme historique (les journaux restent valables)
    assert cache.one(original.ref) == replace(original, key=original.ref)
    assert cache.missing_html("pro", "INBOX", 25) == [3]
    rich = replace(original, html="<p>Bonjour <b>Alice</b></p>")
    cache.store(rich, 3)
    assert cache.one(original.ref) == replace(rich, key=original.ref) and cache.missing_html("pro", "INBOX", 25) == []
    cache.close()
