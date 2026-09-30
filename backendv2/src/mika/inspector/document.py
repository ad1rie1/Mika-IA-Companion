"""Lecture d'un document HTML natif : typographie et liens, sans contenu actif.

On reconstruit des balises connues, sans reprendre aucun attribut source sauf
une URL http(s) vérifiée. Ni CSS, ni image distante, ni formulaire, ni script.
Les tableaux de mise en page des mails deviennent des lignes de document.
Les apps Forge n'ont pas accès à ce format : elles composent des blocs typés.
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from markupsafe import Markup

ALLOWED = frozenset(("p", "div", "span", "br", "hr", "strong", "b", "em", "i", "u", "s", "blockquote",
                     "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code", "a", "sup", "sub"))
HIDDEN = frozenset(("script", "style", "head", "iframe", "object", "svg", "math", "template", "noscript"))
LAYOUT = {"table": "document-table", "tr": "document-row", "td": "document-cell", "th": "document-cell"}
VOID = frozenset(("br", "hr"))
URL = re.compile(r"https?://[^\s<>]+")


def link_url(value: str) -> str:
    if not value or not value.isprintable() or any(c in value for c in "\\ \t\r\n"):
        return ""
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() in ("http", "https") and parts.hostname and not parts.username and not parts.password:
            return value
    except ValueError:
        pass
    return ""


class _Document(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[tuple[str, str]] = []
        self.hidden: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in HIDDEN:
            self.hidden.append(tag)
            return
        if self.hidden:
            return
        if tag == "img":
            alt = dict(attrs).get("alt") or ""
            if alt.strip():
                self.out.append('<span class="document-image">' + escape(alt) + '</span>')
            return
        if tag in LAYOUT:
            self.out.append(f'<div class="{LAYOUT[tag]}">')
            self.stack.append((tag, "div"))
        elif tag in ALLOWED:
            rendered = "h3" if tag.startswith("h") and tag != "hr" else tag
            extra = ""
            if tag == "a":
                href = link_url(dict(attrs).get("href") or "")
                if href:
                    extra = f' href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer nofollow"'
                else:
                    rendered = "span"
            self.out.append(f"<{rendered}{extra}>")
            if tag not in VOID:
                self.stack.append((tag, rendered))

    def handle_endtag(self, tag: str) -> None:
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if any(original == tag for original, _ in self.stack):
            while self.stack:
                original, rendered = self.stack.pop()
                self.out.append(f"</{rendered}>")
                if original == tag:
                    break

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.out.append(escape(data))

    def finish(self) -> Markup:
        self.out.extend(f"</{tag}>" for _, tag in reversed(self.stack))
        return Markup("".join(self.out))  # only the reconstructed allowlist above


def readable_html(source: str) -> Markup:
    parser = _Document()
    parser.feed(source[:200_000])
    parser.close()
    return parser.finish()


def readable_text(source: str) -> Markup:
    out: list[str] = []
    start = 0
    for match in URL.finditer(source):
        raw = match.group().rstrip(".,;:!?)")
        end = match.start() + len(raw)
        out.append(escape(source[start:match.start()]))
        href = link_url(raw)
        out.append(f'<a href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer nofollow">'
                   f'{escape(raw)}</a>' if href else escape(raw))
        start = end
    out.append(escape(source[start:]))
    return Markup("".join(out))
