"""Un document HTML natif tel qu'il a été écrit (ADR 0169) : ses styles, sa mise en page, dans un cadre isolé.

La page de la console ne reçoit jamais ce HTML : elle pose un ``<iframe sandbox>`` vers ``/inspecteur/document/…``,
servi avec sa propre politique (``FRAME_CSP``). Le cadre n'exécute rien (ni script, ni formulaire), ne charge rien
du dehors (ni image distante, ni police, ni feuille de style), n'ouvre ses liens que dans un nouvel onglet et ne
peut ni toucher la console ni la remplacer. Ce que la politique interdit déjà, on le retire aussi de la source
(défense en profondeur) : scripts, cadres, objets, ``<meta>`` et ``<base>``, gestionnaires ``on…``, adresses
autres qu'un lien web ou ``mailto:`` vérifié et qu'une image ``data:`` ; les liens prennent ``target="_blank"``.

Les images que le document désigne par ``cid:`` (les images intégrées d'un mail, ADR 0172) arrivent avec lui :
chacune prend sa place en ``data:``, seulement d'un type d'image qu'un ``<img>`` lit sans risque. Le cadre ne charge
donc toujours rien.

Ses images distantes, l'opérateur peut les permettre, pour ce mail ou pour son expéditeur (ADR 0175) : le document
garde alors ses images ``http``/``https`` (rien d'autre : ni ``srcset``, ni fond ``background``) et se sert sous
``FRAME_CSP_REMOTE``, qui n'ouvre que les images, sans référent. Le reste ne change pas.

Le document attend dans ``Documents`` le temps que la page le charge : gardé par son empreinte, sans rien
d'autre qu'une mémoire bornée (un redémarrage l'oublie, la page rechargée le redonne).
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections import OrderedDict
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from urllib.parse import unquote

from mika.inspector.document import link_url

#: la politique du cadre : ses styles en ligne, ses images ``data:``, rien d'autre ; pas de script (bac à sable)
FRAME_CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; form-action 'none'; "
             "base-uri 'none'; frame-ancestors 'self'; "
             "sandbox allow-popups allow-popups-to-escape-sandbox allow-same-origin")
#: … quand ses images distantes sont permises (ADR 0175) : les images du web, rien d'autre de plus
FRAME_CSP_REMOTE = FRAME_CSP.replace("img-src data:;", "img-src data: https: http:;")
#: le même bac à sable, posé sur l'``<iframe>`` (``allow-same-origin`` : la console mesure sa hauteur ; sans
#: ``allow-scripts``, le cadre ne peut s'en servir)
SANDBOX = "allow-popups allow-popups-to-escape-sandbox allow-same-origin"
#: ce que le cadre ne reprend pas, contenu compris
DROPPED = frozenset(("script", "iframe", "frame", "frameset", "object", "embed", "applet", "noscript", "template",
                     "svg", "math", "title"))
#: ce que le cadre ne reprend pas, mais dont il garde le contenu
SKIPPED = frozenset(("base", "meta", "link", "portal", "fencedframe"))
#: des attributs porteurs d'adresse ou de comportement, jamais repris
UNSAFE = frozenset(("action", "formaction", "srcset", "background", "poster", "data", "codebase", "xlink:href",
                    "ping", "srcdoc", "manifest", "http-equiv", "target", "rel", "itemtype", "lowsrc", "dynsrc",
                    "longdesc", "archive", "classid", "profile", "attributionsrc"))
NAME = re.compile(r"[a-z][a-z0-9-]*")
ATTRIBUTE = re.compile(r"[a-z_][-a-z0-9_.:]*")
IMAGE = re.compile(r"data:image/(png|gif|jpe?g|webp|bmp);base64,[a-z0-9+/=\s]+", re.I)
#: une image distante, quand on les permet : une adresse web, sans espace ni guillemet
REMOTE = re.compile(r"https?://[^\s\"'<>\\]{1,2000}", re.I)
#: les types d'une image intégrée que le cadre montre (les mêmes qu'une image ``data:`` admise)
IMAGE_TYPES = frozenset(("image/png", "image/gif", "image/jpeg", "image/jpg", "image/webp", "image/bmp"))
SIZE = re.compile(r"\d{1,4}%?")
VOID = frozenset(("area", "br", "col", "embed", "hr", "img", "input", "source", "track", "wbr"))
#: le fond du cadre : la page blanche d'une messagerie, que les styles du message recouvrent
BASE_STYLE = ("<style>:root{color-scheme:light}html{background:#fff;color:#1f2328;"
              "font:15px/1.5 system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}"
              "body{margin:0;overflow-wrap:break-word}img{max-width:100%}</style>")
#: au-delà, la source est coupée (la fiche passe déjà en texte au-delà de 200 000 caractères)
SOURCE_MAX = 400_000


#: une image intégrée : (Content-ID, type, octets)
Image = tuple[str, str, bytes]


def content_key(value: str) -> str:
    """Un Content-ID comparable, qu'il vienne d'un en-tête (``<…>``) ou d'une adresse ``cid:`` (encodée)."""
    return unquote(value).strip().strip("<>").strip().lower()


class _Framed(HTMLParser):
    def __init__(self, images: dict[str, str], remote: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.dropped: list[str] = []
        self.raw = False  # dans un <style> : son texte reste tel quel
        #: les images intégrées, par Content-ID comparable : leur adresse ``data:``
        self.images = images
        #: ses images distantes se chargent (ADR 0175)
        self.remote = remote

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._start(tag, attrs)  # « <div/> » s'ouvre, comme le relit un navigateur

    def _start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.dropped:
            if tag == self.dropped[-1] and tag not in VOID:
                self.dropped.append(tag)
            return
        if tag in DROPPED:
            if tag not in VOID:
                self.dropped.append(tag)
            return
        if tag in SKIPPED or not NAME.fullmatch(tag):
            return
        kept = [(name, value) for name, value in (_attribute(tag, n, v) for n, v in attrs) if name]
        if tag == "img":
            source = (dict(attrs).get("src") or "").strip()
            if source[:4].lower() == "cid:" and content_key(source[4:]) in self.images:
                kept.append(("src", self.images[content_key(source[4:])]))
            elif self.remote and REMOTE.fullmatch(source):
                kept.append(("src", source))
        if tag == "img" and not any(name == "src" for name, _ in kept):
            self._blocked(dict(attrs), dict(kept))
            return
        if tag in ("a", "area") and any(name == "href" for name, _ in kept):
            kept += [("target", "_blank"), ("rel", "noopener noreferrer nofollow")]
        self.out.append(f"<{tag}" + "".join(f" {n}" if v is None else f' {n}="{escape(v, quote=True)}"'
                                            for n, v in kept) + ">")
        self.raw = tag == "style"

    def _blocked(self, source: dict[str, str | None], kept: dict[str, str | None]) -> None:
        """Une image distante : son texte de remplacement, à sa place et à sa taille (sans icône d'image cassée)."""
        alt = (source.get("alt") or "").strip()
        if not alt:  # un pixel espion, une image d'espacement
            return
        size = "".join(f"{side}:{value}{'' if value.endswith('%') else 'px'};" for side in ("width", "height")
                       if SIZE.fullmatch(value := (source.get(side) or "").strip()))
        style = "display:inline-block;overflow:hidden;" + size + (kept.get("style") or "")
        css = f' class="{escape(kept["class"], quote=True)}"' if kept.get("class") else ""
        self.out.append(f'<span{css} style="{escape(style, quote=True)}">{escape(alt, quote=False)}</span>')

    def handle_endtag(self, tag: str) -> None:
        if self.dropped:
            if tag == self.dropped[-1]:
                self.dropped.pop()
            return
        if tag in DROPPED or tag in SKIPPED or not NAME.fullmatch(tag):
            return
        self.out.append(f"</{tag}>")
        self.raw = False

    def handle_data(self, data: str) -> None:
        if self.dropped:
            return
        # le texte d'un <style> s'arrête au premier « </style » : la source ne peut pas en sortir
        self.out.append(data if self.raw else escape(data, quote=False))


def _attribute(tag: str, name: str, value: str | None) -> tuple[str, str | None]:
    """Un attribut repris tel quel, ou ``("", None)`` s'il est écarté."""
    if not ATTRIBUTE.fullmatch(name) or name.startswith("on") or name in UNSAFE:
        return "", None
    if name == "href":
        url = link_url((value or "").strip())
        return ("href", url) if url else ("", None)
    if name == "src":
        source = (value or "").strip()
        return ("src", source) if tag == "img" and IMAGE.fullmatch(source) else ("", None)
    return name, value


def framed_html(source: str, images: tuple[Image, ...] = (), *, remote: bool = False) -> str:
    """Le document complet servi dans le cadre : son fond, puis la source purgée de ce qui agirait, ses images
    intégrées à leur place, ses images distantes si on les a permises."""
    found = {content_key(cid): f"data:{mime.lower()};base64,{base64.b64encode(data).decode('ascii')}"
             for cid, mime, data in images if cid and mime.lower() in IMAGE_TYPES}
    parser = _Framed(found, remote)
    parser.feed(source[:SOURCE_MAX])
    parser.close()
    return '<!doctype html><meta charset="utf-8">' + BASE_STYLE + "".join(parser.out)


@dataclass(frozen=True, slots=True)
class Document:
    html: str
    images: tuple[Image, ...] = ()
    remote: bool = False

    @property
    def weight(self) -> int:
        return len(self.html) + sum(len(data) for _, _, data in self.images)


class Documents:
    """Les documents d'une page, en attendant que son cadre les charge : par empreinte, les plus récents ; au plus
    ``size`` documents et ``budget`` octets (le dernier venu reste toujours)."""

    def __init__(self, size: int = 64, budget: int = 64 * 1024 * 1024) -> None:
        self.size = size
        self.budget = budget
        self.kept: OrderedDict[str, Document] = OrderedDict()

    def keep(self, html: str, images: tuple[Image, ...] = (), *, remote: bool = False) -> str:
        hasher = hashlib.sha256(html.encode("utf-8", "replace"))
        for cid, mime, data in images:
            hasher.update(b"\0" + cid.encode("utf-8", "replace") + b"\0" + mime.encode("utf-8", "replace") + b"\0"
                          + hashlib.sha256(data).digest())
        if remote:  # le même mail, images permises ou non : deux documents
            hasher.update(b"\0remote")
        digest = hasher.hexdigest()[:40]
        self.kept[digest] = Document(html, tuple(images), remote)
        self.kept.move_to_end(digest)
        while len(self.kept) > 1 and (len(self.kept) > self.size or
                                      sum(d.weight for d in self.kept.values()) > self.budget):
            self.kept.popitem(last=False)
        return digest

    def get(self, digest: str) -> Document | None:
        return self.kept.get(digest)
