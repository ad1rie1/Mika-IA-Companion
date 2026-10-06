"""Notes et journaux : ``.txt``, ``.md``, ``.docx``, Google Keep (Takeout JSON), Evernote (``.enex``).

Ce sont ses textes à elle. Un fichier qui enchaîne des entrées datées (« 12 mars 2009 »
seul sur sa ligne, « # 2009-03-12 », « Mardi 12 mars : ») est un **journal** : chaque
entrée devient un document à sa date. Sinon c'est une **note**, datée au mieux :

1. la date écrite dans la note (Keep, Evernote) ou en tête du texte ;
2. le nom du fichier, puis celui de ses dossiers (« 2009/12 mars.txt ») ;
3. à défaut, la date de modification du fichier — seulement comme borne : la note a
   été écrite *au plus tard* là ; le reste, l'étape « dater » s'en charge.

Les lecteurs de conversations (WhatsApp, Messenger Plus!) reconnaissent leurs ``.txt``
avec plus d'assurance : une note n'est que ce que personne d'autre ne réclame.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from twin.dates import date_from_header, date_from_path, find_date, is_date_line
from twin.readers import ReadContext, head, read_text
from twin.readers.mail import html_to_text
from twin.records import ME, NOTES, Author, Document, Item
from twin.timing import US, Origin, Temps, from_us

TEXT_SUFFIXES = (".txt", ".md", ".markdown", ".text", ".rtf")


class NotesReader:
    name = "notes"
    label = "Notes et journaux (txt, md, docx, Keep, Evernote)"
    version = 1

    def detect(self, path: Path) -> int:
        suffix = path.suffix.lower()
        if suffix in (".docx", ".enex"):
            return 70
        if suffix == ".json":
            h = head(path, 2048)
            return 70 if '"textContent"' in h or '"listContent"' in h else 0
        if suffix in TEXT_SUFFIXES and path.name.upper() not in ("LISEZMOI.MD", "README.MD"):
            return 10
        return 0

    def read(self, path: Path, ctx: ReadContext) -> Iterator[Item]:
        yield Author(NOTES, ME, me=True, me_reason="ses notes à elle")
        suffix = path.suffix.lower()
        rel = str(path.relative_to(ctx.root)) if path.is_relative_to(ctx.root) else str(path)
        if suffix == ".enex":
            yield from self._enex(path, rel, ctx)
            return
        if suffix == ".json":
            yield from self._keep(path, rel, ctx)
            return
        text = _docx_text(path) if suffix == ".docx" else read_text(path)
        if suffix == ".rtf":
            text = _rtf_text(text)
        yield from self._text(text, path, rel, ctx)

    # -- texte libre ----------------------------------------------------------------------

    def _text(self, text: str, path: Path, rel: str, ctx: ReadContext) -> Iterator[Item]:
        by_path = date_from_path(path, ctx.root, ctx.tz)
        year_hint = from_us(by_path.point, ctx.tz).year if by_path and by_path.point else None
        entries = split_journal(text)
        if len(entries) >= 2:
            last_month = None
            for rank, (head_line, body) in enumerate(entries):
                when = find_date(head_line, ctx.tz, Origin.HEADER, year_hint=year_hint) or Temps.unknown()
                if when.point is not None:
                    local = from_us(when.point, ctx.tz)
                    if year_hint is not None and last_month is not None and local.month < last_month \
                            and str(local.year) not in head_line:
                        # « 28 décembre » puis « 2 janvier » sans année : on a changé d'année
                        year_hint += 1
                        when = find_date(head_line, ctx.tz, Origin.HEADER, year_hint=year_hint) or when
                        local = from_us(when.point, ctx.tz) if when.point is not None else local
                    year_hint, last_month = local.year, local.month
                yield Document(NOTES, f"{rel}#{rank}", "journal", head_line.strip(), body.strip(), when, rank,
                               path=rel)
            return
        when = (date_from_header(text, ctx.tz, year_hint=year_hint) or by_path or _mtime_bound(path))
        title = _title(text) or path.stem
        yield Document(NOTES, rel, "note", title, text.strip(), when, 0, path=rel)

    # -- Google Keep -----------------------------------------------------------------------

    def _keep(self, path: Path, rel: str, ctx: ReadContext) -> Iterator[Item]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("isTrashed"):
            return
        text = data.get("textContent") or "\n".join(
            ("[x] " if i.get("isChecked") else "[ ] ") + i.get("text", "") for i in data.get("listContent") or [])
        usec = data.get("createdTimestampUsec") or data.get("userEditedTimestampUsec")
        when = Temps.exact(int(usec), Origin.SOURCE) if usec else (date_from_header(text, ctx.tz) or _mtime_bound(path))
        yield Document(NOTES, rel, "note", data.get("title") or _title(text) or path.stem, text.strip(), when, 0,
                       path=rel)

    # -- Evernote ---------------------------------------------------------------------------

    def _enex(self, path: Path, rel: str, ctx: ReadContext) -> Iterator[Item]:
        rank = 0
        for _event, el in ET.iterparse(path, events=("end",)):
            if el.tag != "note":
                continue
            title = el.findtext("title") or ""
            body = html_to_text(el.findtext("content") or "")
            created = el.findtext("created") or el.findtext("updated") or ""
            when = _enex_date(created) or date_from_header(body, ctx.tz) or Temps.unknown()
            yield Document(NOTES, f"{rel}#{rank}", "note", title, body.strip(), when, rank, path=rel)
            rank += 1
            el.clear()


def split_journal(text: str) -> list[tuple[str, str]]:
    """Les entrées d'un journal tenu dans un seul fichier : (ligne de date, texte)."""
    entries: list[tuple[str, list[str]]] = []
    preamble: list[str] = []
    for line in text.splitlines():
        if is_date_line(line):
            entries.append((line, []))
        elif entries:
            entries[-1][1].append(line)
        else:
            preamble.append(line)
    if len(entries) < 2 or sum(1 for ln in preamble if ln.strip()) > 20:
        return []  # pas un journal : une note qui cite une date
    return [(h, "\n".join(b)) for h, b in entries]


def _title(text: str) -> str:
    for line in text.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:80]
    return ""


def _mtime_bound(path: Path) -> Temps:
    """La date de modification : écrite au plus tard là (et pas plus tôt connue)."""
    try:
        mtime = int(path.stat().st_mtime * US)
    except OSError:
        return Temps.unknown()
    return Temps(None, mtime, None, Temps.unknown().precision, Origin.FILE)


def _enex_date(raw: str) -> Temps | None:
    m = re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$", raw.strip())
    if not m:
        return None
    y, mo, d, hh, mm, ss = (int(x) for x in m.groups())
    try:
        return Temps.exact(datetime(y, mo, d, hh, mm, ss, tzinfo=UTC), Origin.SOURCE)
    except ValueError:
        return None


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    paragraphs = []
    for p in root.iter(f"{_W}p"):
        paragraphs.append("".join(t.text or "" for t in p.iter(f"{_W}t")))
    return "\n".join(paragraphs)


def _rtf_text(rtf: str) -> str:
    text = re.sub(r"\\par[d]?", "\n", rtf)
    text = re.sub(r"\\'([0-9a-f]{2})", lambda m: bytes.fromhex(m.group(1)).decode("cp1252"), text)
    text = re.sub(r"\\[a-z]+-?\d* ?|[{}]", "", text)
    return text


READER = NotesReader()
