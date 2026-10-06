"""MSN / Windows Live Messenger : l'historique XML natif et les journaux de Messenger Plus!.

**XML natif** (``History/<contact><numéro>.xml``)::

    <Message Date="12/03/2009" Time="14:05:33" DateTime="2009-03-12T13:05:33.383Z" SessionID="1">
      <From><User FriendlyName="Julie ~ ☆"/></From><To><User FriendlyName="Moi"/></To>
      <Text Style="...">salut</Text>
    </Message>

``DateTime`` (UTC) quand il existe ; sinon ``Date`` + ``Time`` en heure locale. Les
pseudos changeaient sans cesse : un même côté de la conversation porte plusieurs noms.
Dans un fil à deux, ``From`` et ``To`` sont toujours de côtés opposés : on colore le
graphe des noms en deux côtés, chacun devient un auteur dont les autres pseudos sont des
alias. Lequel est elle ? Le côté dont les pseudos se retrouvent dans *tous* ses fichiers
— décidé à l'étape « personnes », pas ici.

**Messenger Plus!** (texte ou HTML) : un en-tête de session qui donne la date et les
participants avec leur adresse, puis ``[14:05:33] Julie : salut``. Elle n'est pas dans
la liste des participants : l'auteur qui n'y est pas, c'est elle.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from pathlib import Path

from twin.dates import find_date
from twin.readers import ReadContext, head, read_text
from twin.records import MSN, Attachment, Author, Conversation, Item, Message
from twin.timing import Origin, Temps, from_us

#: l'époque de MSN : une date absente tombe forcément là-dedans
ERA = (date(1999, 7, 22), date(2014, 10, 31))

_PLUS_CODES = re.compile(r"·(?:\$(?:#[0-9A-Fa-f]{6}|\d{1,2})(?:,(?:#[0-9A-Fa-f]{6}|\d{1,2}))?|[#&'@0])")
_BB_CODES = re.compile(r"\[/?(?:[biuscpa]|c=[^\]]*|a=[^\]]*)\]", re.I)
_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_nick(nick: str) -> str:
    """Un pseudo MSN sans ses codes de couleur (« ·$4Julie [b]☆[/b] » → « Julie ☆ »)."""
    s = _BB_CODES.sub("", _PLUS_CODES.sub("", html.unescape(nick or "")))
    return re.sub(r"\s+", " ", s).strip()


class MsnReader:
    name = "msn"
    label = "MSN Messenger (historique XML, Messenger Plus!)"
    version = 1

    def detect(self, path: Path) -> int:
        suffix = path.suffix.lower()
        h = head(path, 4096)
        if suffix == ".xml" and "<Log" in h and ("<Message" in h or "MessageLog.xsl" in h or "FirstSessionID" in h):
            return 95
        low = h.lower()
        if suffix in (".txt", ".html", ".htm") and (
                "session start" in low or "début de session" in low or "debut de session" in low
                or "messenger plus" in low):
            return 85
        return 0

    def read(self, path: Path, ctx: ReadContext) -> Iterator[Item]:
        if path.suffix.lower() == ".xml":
            yield from self._read_xml(path, ctx)
        else:
            yield from self._read_plus(path, ctx)

    # -- XML natif ----------------------------------------------------------------------

    def _read_xml(self, path: Path, ctx: ReadContext) -> Iterator[Item]:
        root = _parse_xml(read_text(path), path, ctx)
        if root is None:
            return
        entries = [el for el in root if el.tag in ("Message", "Invitation", "InvitationResponse", "Join", "Leave")]
        month_first = _month_first([el.get("Date", "") for el in entries])
        rows: list[tuple[Temps, str, tuple[str, ...], str, str, tuple[Attachment, ...]]] = []
        for el in entries:
            when = _when(el, month_first, ctx)
            sender = clean_nick(_first_user(el.find("From")) or _first_user(el))
            to_el = el.find("To")
            to = tuple(clean_nick(u.get("FriendlyName", "")) for u in to_el.iter("User")) if to_el is not None else ()
            text = "".join(el.findtext("Text") or "")
            kind = "message" if el.tag == "Message" else "systeme"
            atts: tuple[Attachment, ...] = ()
            if el.tag.startswith("Invitation") and el.findtext("File"):
                atts = (Attachment(el.findtext("File") or "fichier"),)
                kind = "message"
            rows.append((when, sender, to, text, kind, atts))

        conv_key = path.stem
        pairs = [(s, t) for _, s, t, _, k, _ in rows if k == "message" and s]
        group = any(len(t) > 1 for _, t in pairs)
        sides = None if group else _two_sides(pairs)
        all_names = {s for _, s, _, _, _, _ in rows if s} | {n for _, _, t, _, _, _ in rows for n in t}
        if sides is None:  # groupe, ou côtés indécidables : un auteur par pseudo
            keys = {n: n for n in all_names}
            for n in sorted(all_names):
                yield Author(MSN, n, name=n)
        else:
            keys = {}
            for side in sides:
                counts = Counter(s for _, s, _, _, _, _ in rows if s in side)
                main = counts.most_common(1)[0][0] if counts else sorted(side)[0]
                for n in side:
                    keys[n] = f"{conv_key}#{main}"
                yield Author(MSN, f"{conv_key}#{main}", name=main, aliases=tuple(sorted(side)))
        yield Conversation(MSN, conv_key, title=conv_key, group=group, members=tuple(sorted(set(keys.values()))))
        for rank, (when, sender, _to, text, kind, atts) in enumerate(rows):
            yield Message(MSN, conv_key, keys.get(sender, ""), text, when, rank, kind=kind, attachments=atts)

    # -- Messenger Plus! ----------------------------------------------------------------

    def _read_plus(self, path: Path, ctx: ReadContext) -> Iterator[Item]:
        text = read_text(path)
        if path.suffix.lower() in (".html", ".htm"):
            text = _html_to_text(text)
        conv_key = path.stem
        participants: dict[str, str] = {}  # nom → adresse
        rows: list[tuple[Temps, str, str]] = []
        day: date | None = None
        last_t: time | None = None
        in_header = False
        for line in text.splitlines():
            s = line.strip().strip("|").strip()
            low = s.lower()
            if low.startswith(("session start", "début de session", "debut de session")):
                found = find_date(s.split(":", 1)[-1], ctx.tz, Origin.HEADER)
                if found and found.point is not None:
                    day = from_us(found.point, ctx.tz).date()
                    last_t = None
                in_header = True
                continue
            if low.startswith(("participants", "session close", "fin de session")):
                continue
            if in_header:
                m = re.match(r"^(.+?)\s*\(([^()\s]+@[^()\s]+)\)$", s)
                if m:
                    participants[clean_nick(m.group(1))] = m.group(2).lower()
                    continue
                if s.startswith("."):
                    in_header = False
                    continue
            m = re.match(r"^[\[(](\d{1,2}):(\d{2})(?::(\d{2}))?[\])]\s*(.+?)\s*:\s(.*)$", s)
            if not m:
                if rows and s and not s.startswith("."):
                    t, a, body = rows[-1]
                    rows[-1] = (t, a, body + "\n" + s)
                continue
            in_header = False
            hh, mm, ss, who, body = m.groups()
            clock = time(int(hh), int(mm), int(ss or 0))
            if day is None:
                rows.append((_era(ctx), clean_nick(who), body))
                continue
            if last_t is not None and clock < last_t:
                day = day + timedelta(days=1)  # passé minuit dans la même session
            last_t = clock
            rows.append((Temps.exact(datetime.combine(day, clock, tzinfo=ctx.tz), Origin.SOURCE), clean_nick(who), body))

        names = sorted({a for _, a, _ in rows})
        listed = set(participants)
        group = len(listed) > 1
        yield Conversation(MSN, conv_key, title=", ".join(sorted(listed)) or conv_key, group=group,
                           members=tuple(names))
        for n in names:
            if n in listed:
                yield Author(MSN, n, name=n, address=participants[n], me=False,
                             me_reason="listée parmi les participants de la session")
            elif listed:
                yield Author(MSN, n, name=n, me=True, me_reason="absente de la liste des participants : la titulaire")
            else:
                yield Author(MSN, n, name=n)
        for rank, (when, who, body) in enumerate(rows):
            yield Message(MSN, conv_key, who, body, when, rank)


def _parse_xml(text: str, path: Path, ctx: ReadContext) -> ET.Element | None:
    text = re.sub(r"<\?xml-stylesheet[^>]*\?>", "", text)
    for attempt in (text, _BAD_XML.sub("", text)):
        try:
            return ET.fromstring(attempt.encode("utf-8"))
        except ET.ParseError:
            continue
    # dernier recours : reprendre message par message
    blocks = re.findall(r"<(Message|Invitation|InvitationResponse|Join|Leave)\b.*?</\1>", _BAD_XML.sub("", text), re.S)
    if not blocks:
        ctx.warn(f"{path.name} : XML illisible")
        return None
    root = ET.Element("Log")
    bad = 0
    for m in re.finditer(r"<(Message|Invitation|InvitationResponse|Join|Leave)\b.*?</\1>", _BAD_XML.sub("", text), re.S):
        try:
            root.append(ET.fromstring(m.group(0)))
        except ET.ParseError:
            bad += 1
    ctx.warn(f"{path.name} : XML abîmé, {len(root)} entrées récupérées, {bad} perdues")
    return root


def _first_user(el: ET.Element | None) -> str:
    if el is None:
        return ""
    u = el.find(".//User")
    return u.get("FriendlyName", "") if u is not None else ""


def _month_first(dates: list[str]) -> bool:
    pairs = [d.split("/")[:2] for d in dates if d.count("/") == 2]
    try:
        if any(int(a) > 12 for a, _ in pairs):
            return False
        return any(int(b) > 12 for _, b in pairs)
    except ValueError:
        return False


def _when(el: ET.Element, month_first: bool, ctx: ReadContext) -> Temps:
    stamp = el.get("DateTime")
    if stamp:
        try:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                return Temps.exact(dt, Origin.SOURCE)
        except ValueError:
            pass
    d, t = el.get("Date", ""), el.get("Time", "")
    try:
        a, b, y = (int(x) for x in d.split("/"))
        day, month = (b, a) if month_first else (a, b)
        hh, mm, *rest = (int(x) for x in t.split(":"))
        return Temps.exact(datetime(y, month, day, hh, mm, rest[0] if rest else 0, tzinfo=ctx.tz), Origin.SOURCE)
    except (ValueError, TypeError):
        return _era(ctx)


def _era(ctx: ReadContext) -> Temps:
    """Pas de date du tout : quelque part dans l'époque de MSN."""
    return Temps.span(Temps.day(ERA[0], ctx.tz, Origin.ERA).start, Temps.day(ERA[1], ctx.tz, Origin.ERA).end,
                      Origin.ERA)


def _two_sides(pairs: list[tuple[str, tuple[str, ...]]]) -> list[set[str]] | None:
    """Colore les pseudos en deux côtés (From et To toujours opposés) ; ``None`` pour un groupe."""
    graph: dict[str, set[str]] = defaultdict(set)
    for sender, to in pairs:
        if len(to) != 1:
            return None
        graph[sender].add(to[0])
        graph[to[0]].add(sender)
    color: dict[str, int] = {}
    for start in graph:
        if start in color:
            continue
        color[start] = 0
        stack = [start]
        while stack:
            n = stack.pop()
            for m in graph[n]:
                if m not in color:
                    color[m] = 1 - color[n]
                    stack.append(m)
                elif color[m] == color[n]:
                    return None  # un pseudo des deux côtés : ce n'est pas un fil à deux
    if not color or _components(graph) != 1:
        return None  # deux composantes : impossible de savoir quel côté de l'une va avec l'autre
    sides = [{n for n, c in color.items() if c == k} for k in (0, 1)]
    return sides if all(sides) else None


def _components(graph: dict[str, set[str]]) -> int:
    seen: set[str] = set()
    count = 0
    for start in graph:
        if start in seen:
            continue
        count += 1
        stack = [start]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(graph[n] - seen)
    return count


def _html_to_text(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", text)
    return html.unescape(re.sub(r"<[^>]+>", "", text))


READER = MsnReader()
