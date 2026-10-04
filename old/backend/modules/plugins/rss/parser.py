"""Lecture d'un flux — une seule forme normalisée, deux implémentations.

**Pourquoi ce fichier existe.** Le module lisait ``feedparser`` directement et
en faisait sa condition d'existence (``is_available()`` renvoyait ``False``
sans lui). Or ``feedparser`` n'est pas dans ``requirements.txt`` : sur cette
installation il n'était pas installé, donc le module n'était jamais actif,
donc son espace n'affichait rien et aucun article n'était jamais relevé. Une
dépendance non déclarée transformait le module entier en page vide, sans
qu'aucun message ne le dise.

Deux corrections, pas une :

1. ``feedparser`` est déclaré dans ``requirements.txt`` — c'est le bon
   analyseur, il connaît les dialectes tordus (RSS 0.9x, iTunes, Dublin Core,
   dates en huit formats).
2. Un analyseur de secours en bibliothèque standard le remplace quand il
   manque. RSS 2.0, RSS 1.0/RDF et Atom sont trois gabarits XML stables ; en
   extraire titre/lien/résumé/date tient en une centaine de lignes. Le module
   **fonctionne donc toujours**, et la présence de ``feedparser`` ne fait que
   rendre la lecture plus tolérante.

Les deux chemins produisent le même ``ParsedFeed``. Rien en aval ne sait
lequel a servi — ``which_parser()`` le dit à la page d'état, pour que « les
dates sont approximatives » soit une information disponible plutôt qu'une
surprise.
"""
from __future__ import annotations

import hashlib
import html as html_module
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone as dt_timezone

logger = logging.getLogger(__name__)

# Espaces de noms rencontrés dans la nature. Atom et RDF nomment leurs
# éléments, RSS 2.0 ne nomme rien — d'où les deux chemins ci-dessous.
_NS_ATOM = "http://www.w3.org/2005/Atom"
_NS_RSS1 = "http://purl.org/rss/1.0/"
_NS_DC = "http://purl.org/dc/elements/1.1/"
_NS_CONTENT = "http://purl.org/rss/1.0/modules/content/"


@dataclass(frozen=True)
class ParsedEntry:
    """Un article, tel que le module le manipule ensuite."""
    uid: str                       # identifiant du flux (guid/id/link/titre)
    title: str
    link: str = ""
    summary: str = ""
    author: str = ""
    published_raw: str = ""        # tel qu'écrit dans le flux, pour affichage
    published_at: datetime | None = None


@dataclass
class ParsedFeed:
    title: str = ""
    entries: list[ParsedEntry] = field(default_factory=list)
    # Renseigné quand le flux est illisible *et* vide. Un flux légèrement
    # malformé mais dont on a extrait des articles n'est pas une erreur :
    # c'est le cas courant, et refuser ses articles ne rendrait service à
    # personne.
    error: str = ""


def which_parser() -> str:
    """« feedparser » ou « stdlib » — ce qui servira au prochain relevé."""
    try:
        import feedparser  # noqa: F401
        return "feedparser"
    except ImportError:
        return "stdlib"


def parse(raw: bytes) -> ParsedFeed:
    """Analyse les octets d'un flux. Ne lève jamais."""
    try:
        import feedparser
    except ImportError:
        return _parse_stdlib(raw)
    try:
        return _parse_feedparser(feedparser, raw)
    except Exception as exc:
        logger.debug("feedparser a échoué, repli sur la bibliothèque standard", exc_info=True)
        parsed = _parse_stdlib(raw)
        if not parsed.entries and not parsed.error:
            parsed.error = f"{type(exc).__name__}: {exc}"
        return parsed


# ── feedparser ──────────────────────────────────────────────────────────

def _parse_feedparser(feedparser, raw: bytes) -> ParsedFeed:
    doc = feedparser.parse(raw)
    entries: list[ParsedEntry] = []
    for item in doc.entries:
        title = clean_text(item.get("title", ""))
        link = (item.get("link") or "").strip()
        uid = (item.get("id") or item.get("guid") or link or title).strip()
        if not uid:
            continue
        entries.append(ParsedEntry(
            uid=uid,
            title=title or "(sans titre)",
            link=link,
            summary=clean_text(item.get("summary") or item.get("description") or ""),
            author=clean_text(item.get("author", ""))[:200],
            published_raw=(item.get("published") or item.get("updated") or "")[:100],
            published_at=_from_struct_time(
                item.get("published_parsed") or item.get("updated_parsed")
            ) or parse_date(item.get("published") or item.get("updated") or ""),
        ))

    error = ""
    if not entries and getattr(doc, "bozo", 0):
        error = str(getattr(doc, "bozo_exception", "flux illisible"))[:400]

    return ParsedFeed(
        title=clean_text(getattr(doc, "feed", {}).get("title", "")),
        entries=entries,
        error=error,
    )


def _from_struct_time(value) -> datetime | None:
    """``time.struct_time`` (UTC chez feedparser) → datetime aware."""
    if not value:
        return None
    try:
        return datetime(*value[:6], tzinfo=dt_timezone.utc)
    except (TypeError, ValueError):
        return None


# ── Bibliothèque standard ───────────────────────────────────────────────

def _parse_stdlib(raw: bytes) -> ParsedFeed:
    from xml.etree import ElementTree

    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        return ParsedFeed(error=f"XML invalide : {exc}"[:400])

    # RSS 2.0 : <rss><channel><item>. RDF/RSS 1.0 : <rdf:RDF><item> (les items
    # sont frères du channel, pas ses enfants). Atom : <feed><entry>.
    channel = root.find("channel")
    if channel is not None:
        return ParsedFeed(
            title=clean_text(_text(channel, "title")),
            entries=[_entry_rss(node) for node in channel.findall("item")],
        )

    rdf_items = root.findall(f"{{{_NS_RSS1}}}item")
    if rdf_items:
        rdf_channel = root.find(f"{{{_NS_RSS1}}}channel")
        return ParsedFeed(
            title=clean_text(_text(rdf_channel, f"{{{_NS_RSS1}}}title")),
            entries=[_entry_rss(node, ns=_NS_RSS1) for node in rdf_items],
        )

    atom_entries = root.findall(f"{{{_NS_ATOM}}}entry")
    if atom_entries or root.tag == f"{{{_NS_ATOM}}}feed":
        return ParsedFeed(
            title=clean_text(_text(root, f"{{{_NS_ATOM}}}title")),
            entries=[_entry_atom(node) for node in atom_entries],
        )

    return ParsedFeed(error="Format non reconnu (ni RSS, ni RDF, ni Atom).")


def _entry_rss(node, *, ns: str = "") -> ParsedEntry:
    prefix = f"{{{ns}}}" if ns else ""
    title = clean_text(_text(node, f"{prefix}title"))
    link = _text(node, f"{prefix}link").strip()
    guid = _text(node, f"{prefix}guid").strip()
    raw_date = (
        _text(node, f"{prefix}pubDate")
        or _text(node, f"{{{_NS_DC}}}date")
        or _text(node, f"{prefix}date")
    ).strip()
    summary = (
        _text(node, f"{prefix}description")
        or _text(node, f"{{{_NS_CONTENT}}}encoded")
    )
    author = (
        _text(node, f"{prefix}author")
        or _text(node, f"{{{_NS_DC}}}creator")
    )
    return ParsedEntry(
        uid=guid or link or title,
        title=title or "(sans titre)",
        link=link,
        summary=clean_text(summary),
        author=clean_text(author)[:200],
        published_raw=raw_date[:100],
        published_at=parse_date(raw_date),
    )


def _entry_atom(node) -> ParsedEntry:
    title = clean_text(_text(node, f"{{{_NS_ATOM}}}title"))
    link = ""
    for candidate in node.findall(f"{{{_NS_ATOM}}}link"):
        rel = candidate.get("rel", "alternate")
        if rel == "alternate" or not link:
            link = (candidate.get("href") or "").strip()
        if rel == "alternate":
            break
    uid = _text(node, f"{{{_NS_ATOM}}}id").strip()
    raw_date = (
        _text(node, f"{{{_NS_ATOM}}}published")
        or _text(node, f"{{{_NS_ATOM}}}updated")
    ).strip()
    summary = (
        _text(node, f"{{{_NS_ATOM}}}summary")
        or _text(node, f"{{{_NS_ATOM}}}content")
    )
    author_node = node.find(f"{{{_NS_ATOM}}}author")
    author = _text(author_node, f"{{{_NS_ATOM}}}name") if author_node is not None else ""
    return ParsedEntry(
        uid=uid or link or title,
        title=title or "(sans titre)",
        link=link,
        summary=clean_text(summary),
        author=clean_text(author)[:200],
        published_raw=raw_date[:100],
        published_at=parse_date(raw_date),
    )


def _text(node, tag: str) -> str:
    if node is None:
        return ""
    found = node.find(tag)
    if found is None:
        return ""
    # ``itertext`` plutôt que ``.text`` : un <description> peut contenir du
    # XHTML échappé *ou* des enfants, et ``.text`` s'arrête au premier balisage.
    return "".join(found.itertext())


# ── Dates ───────────────────────────────────────────────────────────────

def parse_date(raw: str) -> datetime | None:
    """RFC 822 (RSS) ou ISO 8601 (Atom) → datetime aware. Jamais d'exception.

    Le fuseau est conservé quand le flux en donne un ; sinon on suppose UTC.
    Supposer *local* serait pire : un flux étranger sans fuseau se retrouverait
    daté à quelques heures dans le futur, et l'ordre d'affichage passerait
    devant des articles réellement plus récents.
    """
    raw = (raw or "").strip()
    if not raw:
        return None

    from email.utils import parsedate_to_datetime

    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed


# ── Texte ───────────────────────────────────────────────────────────────

_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\r\f\v]+")
_NEWLINES = re.compile(r"\n{3,}")


def clean_text(raw: str) -> str:
    """Retire le balisage et les entités d'un fragment de flux.

    Un résumé RSS est du HTML arbitraire fourni par un tiers. Il ne sert
    qu'affiché en texte (cellules typées, invite système, outil MCP), donc il
    est réduit à du texte **ici**, une fois, plutôt que dans chaque
    consommateur.
    """
    if not raw:
        return ""
    text = _TAG.sub(" ", str(raw))
    text = html_module.unescape(text)
    text = _SPACES.sub(" ", text)
    text = _NEWLINES.sub("\n\n", text)
    return text.strip()


def entry_hash(uid: str, feed_url: str) -> str:
    """Empreinte de déduplication, stable d'un relevé à l'autre."""
    return hashlib.md5(f"{feed_url}:{uid}".encode()).hexdigest()
