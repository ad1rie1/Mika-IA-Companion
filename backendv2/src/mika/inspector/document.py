"""Lecture d'un document HTML natif : typographie et liens, sans contenu actif.

On reconstruit des balises connues, sans reprendre aucun attribut source sauf
une URL http(s) ou mailto vérifiée et la fusion de colonnes d'une cellule (un
``colspan``, devenu une classe). Ni CSS, ni image distante, ni formulaire, ni script.
Les tableaux des mails deviennent des grilles de ``<div>`` dont chaque colonne
prend la largeur de son contenu, comme dans une messagerie : la coche d'une
liste reste étroite, le texte à côté prend la place.
Les apps Forge n'ont pas accès à ce format : elles composent des blocs typés.

**Le contenu ne sort jamais de son cadre.** Ce qu'on émet est bien imbriqué,
mais un navigateur ferme lui-même certaines balises à l'ouverture d'autres
(un ``<li>`` en ferme un autre en remontant à travers un ``<div>``, un bloc
ferme un ``<p>`` ouvert, un titre en ferme un autre, un lien un autre lien) :
son arbre diverge alors du nôtre, et nos fermetures suivantes refermaient le
cadre de la console — la suite du mail s'affichait comme de l'interface. On
n'émet donc que ce qu'un navigateur relit **à l'identique** : un ``<li>``
seulement directement dans une liste (sinon un ``<div>``), aucun bloc dans un
paragraphe (il y devient un ``<span>``), pas de titre dans un titre ni de
lien dans un lien.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
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
#: ce qu'un navigateur traite comme un bloc (qui ferme un paragraphe ouvert)
BLOCKS = frozenset(("p", "div", "ul", "ol", "li", "blockquote", "pre", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
                    "table", "tr", "td", "th"))
HEADINGS = frozenset(("h1", "h2", "h3", "h4", "h5", "h6"))
#: au-delà, un tableau n'est plus une grille : ses cellules passent à la ligne (leurs classes : console.css)
COLUMNS = 12


def link_url(value: str) -> str:
    if not value or not value.isprintable() or any(c in value for c in "\\ \t\r\n"):
        return ""
    try:
        parts = urlsplit(value)
        scheme = parts.scheme.lower()
        if scheme in ("http", "https") and parts.hostname and not parts.username and not parts.password:
            return value
        if scheme == "mailto" and parts.path:
            return value
    except ValueError:
        pass
    return ""


def _span(value: str | None) -> int:
    try:
        return max(1, min(COLUMNS, int(value or 1)))
    except ValueError:
        return 1


@dataclass
class _Grid:
    """Un tableau ouvert : sa balise dans la sortie (sa classe se pose à sa fermeture), sa ligne la plus large."""
    at: int
    columns: int = 0
    row: int = 0


class _Document(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[tuple[str, str]] = []
        self.hidden: list[str] = []
        self.grids: list[_Grid] = []  # un par tableau rendu en <div> encore ouvert, dans l'ordre de la pile

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
        if tag not in LAYOUT and tag not in ALLOWED:
            return
        if tag in ("tr", "td", "th"):
            self._implied(tag)
        rendered = self._rendered(tag)
        if tag in LAYOUT and rendered == "div":
            self.out.append(f'<div class="{self._layout(tag, attrs)}">')
            self.stack.append((tag, "div"))
            return
        extra = ""
        if tag == "a" and rendered == "a":
            href = link_url(dict(attrs).get("href") or "")
            if href:
                web = not href.lower().startswith("mailto:")  # un mailto ouvre la messagerie, pas un onglet vide
                extra = (f' href="{escape(href, quote=True)}"' + (' target="_blank"' if web else "") +
                         ' rel="noopener noreferrer nofollow"')
            else:
                rendered = "span"
        self.out.append(f"<{rendered}{extra}>")
        if rendered not in VOID:
            self.stack.append((tag, rendered))

    def _implied(self, tag: str) -> None:
        """``</td>`` et ``</tr>`` sont facultatifs : une cellule ferme la cellule ouverte de sa ligne, une ligne
        la ligne ouverte de son tableau, avec ce qui y reste ouvert (sinon la suivante s'imbriquerait dedans)."""
        table = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == "table"), None)
        if table is None or self.stack[table][1] != "div":
            return
        keep = table + 1
        if tag != "tr" and self.stack[keep:keep + 1] == [("tr", "div")]:
            keep += 1
        if len(self.stack) > keep and self.stack[keep] in (("tr", "div"), ("td", "div"), ("th", "div")):
            while len(self.stack) > keep:
                self._close(*self.stack.pop())

    def _layout(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        """La classe d'une balise de tableau. Ses colonnes se comptent sur les lignes et cellules posées
        directement dans le tableau : celles que la grille place (``.document-grid > .document-row > …``)."""
        if tag == "table":
            self.grids.append(_Grid(len(self.out)))
            return LAYOUT[tag]
        if tag == "tr":
            if self.stack[-1:] == [("table", "div")]:
                self.grids[-1].row = 0
            return LAYOUT[tag]
        span = _span(dict(attrs).get("colspan"))
        if self.stack[-2:] == [("table", "div"), ("tr", "div")]:
            grid = self.grids[-1]
            grid.row += span
            grid.columns = max(grid.columns, grid.row)
        return LAYOUT[tag] + (" document-head" if tag == "th" else "") + (f" document-span-{span}" if span > 1 else "")

    def _close(self, original: str, rendered: str) -> None:
        self.out.append(f"</{rendered}>")
        if (original, rendered) == ("table", "div"):
            grid = self.grids.pop()
            if 2 <= grid.columns <= COLUMNS:
                self.out[grid.at] = f'<div class="document-table document-grid document-cols-{grid.columns}">'

    def _rendered(self, tag: str) -> str:
        """La balise émise pour ``tag`` à cet endroit : une que le navigateur relira sans rien fermer
        de lui-même (sinon son arbre diverge du nôtre, et le contenu sort de son cadre)."""
        open_tags = [rendered for _, rendered in self.stack]
        if "p" in open_tags and tag in BLOCKS:  # un bloc ferme un paragraphe ouvert : il reste en ligne
            return "br" if tag == "hr" else "span"
        if tag in LAYOUT:
            return "div"
        if tag == "li":  # un élément de liste ailleurs que dans une liste en fermerait un autre
            return "li" if open_tags and open_tags[-1] in ("ul", "ol") else "div"
        if tag in HEADINGS:
            return "span" if "h3" in open_tags else "h3"
        if tag == "a" and "a" in open_tags:
            return "span"
        return tag

    def handle_endtag(self, tag: str) -> None:
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if any(original == tag for original, _ in self.stack):
            while self.stack:
                original, rendered = self.stack.pop()
                self._close(original, rendered)
                if original == tag:
                    break

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.out.append(escape(data))

    def finish(self) -> Markup:
        for original, rendered in reversed(self.stack):
            self._close(original, rendered)
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
