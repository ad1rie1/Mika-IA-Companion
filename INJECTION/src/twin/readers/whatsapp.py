"""WhatsApp : l'export « Exporter la discussion » (``.txt``), Android et iPhone, français et anglais.

Formats rencontrés::

    12/03/2019 14:05 - Julie: Salut              (Android, ancien)
    12/03/2019 à 14:05 - Julie: Salut            (Android, récent)
    [12/03/2019 14:05:33] Julie: Salut           (iPhone, souvent précédé d'un U+200E)
    3/12/19, 2:05 PM - Julie: Salut              (anglais : mois d'abord, heure à l'américaine)

Les lignes sans date prolongent le message précédent. L'ordre jour/mois se déduit du
fichier entier (un 13 en première position ⇒ jour d'abord). Les heures sont locales :
le fuseau de la personne. Le nom du fichier nomme l'autre personne d'une discussion à
deux (« Discussion WhatsApp avec Julie ») : l'autre auteur, c'est elle.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from twin.readers import ReadContext, head, read_text
from twin.records import WHATSAPP, Attachment, Author, Conversation, Item, Message
from twin.timing import Origin, Temps

_INVISIBLE = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮﻿"), None)
_DATE = r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})"
_TIME = r"(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\s?([AaPp])\.?\s?[Mm]\.?)?"
ANDROID = re.compile(rf"^{_DATE},?(?:\s+à)?\s+{_TIME}\s+[-–]\s+(.*)$")
IOS = re.compile(rf"^\[{_DATE},?(?:\s+à)?\s+{_TIME}\]\s+(.*)$")

_FILE_NAMES = [
    re.compile(r"^Discussion WhatsApp avec (.+?)(?: \(\d+\))?$", re.I),
    re.compile(r"^WhatsApp Chat with (.+?)(?: \(\d+\))?$", re.I),
    re.compile(r"^WhatsApp Chat - (.+?)$", re.I),
    re.compile(r"^Conversa do WhatsApp com (.+?)$", re.I),
]
_GROUP_HINTS = ("a créé le groupe", "a créé ce groupe", "created group", "created this group", " a ajouté ",
                " added ", "a changé l'icône de ce groupe", "changed this group's icon", "a quitté", " left")
_DELETED = ("ce message a été supprimé", "vous avez supprimé ce message", "this message was deleted",
            "you deleted this message")
_MEDIA = re.compile(
    r"^(?:<(?:médias omis|media omitted)>|(?:image|vidéo|audio|gif|sticker|document)s? omise?s?"
    r"|(?:image|video|audio|gif|sticker|document) omitted"
    r"|<(?:attached|pièce jointe)\s*:\s*(?P<a>[^>]+)>"
    r"|(?P<b>\S+\.\w{2,4}) \((?:fichier joint|file attached)\))$",
    re.I,
)


def _chat_name(path: Path) -> str:
    for candidate in (path.stem, path.parent.name):
        for pat in _FILE_NAMES:
            m = pat.match(candidate)
            if m:
                return m.group(1).strip()
    return ""


def _parse_line(line: str) -> tuple[tuple[str, ...], str] | None:
    m = IOS.match(line) or ANDROID.match(line)
    if not m:
        return None
    return m.groups()[:7], m.group(8)


class WhatsAppReader:
    name = "whatsapp"
    label = "WhatsApp (export .txt)"
    version = 1

    def detect(self, path: Path) -> int:
        if path.suffix.lower() != ".txt":
            return 0
        lines = [ln.translate(_INVISIBLE) for ln in head(path).splitlines()[:30]]
        hits = sum(1 for ln in lines if _parse_line(ln))
        if hits >= 3 or (hits >= 1 and _chat_name(path)):
            return 90
        return 0

    def read(self, path: Path, ctx: ReadContext) -> Iterator[Item]:
        raw_lines = read_text(path).translate(_INVISIBLE).replace(" ", " ").replace(" ", " ").splitlines()
        parsed: list[tuple[tuple[str, ...], list[str]]] = []
        for line in raw_lines:
            got = _parse_line(line)
            if got:
                stamp, rest = got
                parsed.append((stamp, [rest]))
            elif parsed:
                parsed[-1][1].append(line)  # suite d'un message sur plusieurs lignes
        if not parsed:
            return

        month_first = self._month_first(parsed, path, ctx)
        chat = _chat_name(path) or path.stem
        rows: list[tuple[Temps, str, str]] = []  # (temps, auteur, texte)
        for stamp, body in parsed:
            when = self._when(stamp, month_first, ctx)
            if when is None:
                ctx.warn(f"{path.name} : date illisible {stamp}")
                continue
            text = "\n".join(body)
            author, sep, msg = text.partition(": ")
            if not sep or "\n" in author or len(author) > 60:
                rows.append((when, "", text))  # message système (chiffrement, groupe…)
            else:
                rows.append((when, author.strip(), msg))

        authors = sorted({a for _, a, _ in rows if a})
        system_text = " ".join(t.lower() for _, a, t in rows if not a)
        group = len(authors) > 2 or any(h in system_text for h in _GROUP_HINTS)
        conv_key = chat
        yield Conversation(WHATSAPP, conv_key, title=chat, group=group, members=tuple(authors))

        others = [a for a in authors if a == chat]
        for a in authors:
            me: bool | None = None
            reason = ""
            if not group and others and len(authors) == 2:
                me = a != chat
                reason = (f"discussion à deux exportée « avec {chat} »"
                          if me else "porte le nom de la discussion exportée")
            phone = _phone(a, ctx.country_code)
            yield Author(WHATSAPP, a, name="" if phone else a, address=phone, me=me, me_reason=reason)

        for rank, (when, author, text) in enumerate(rows):
            kind, atts, body = self._classify(author, text)
            yield Message(WHATSAPP, conv_key, author, body, when, rank, kind=kind, attachments=atts)

    def _month_first(self, parsed: list[tuple[tuple[str, ...], list[str]]], path: Path, ctx: ReadContext) -> bool:
        firsts = [int(s[0]) for s, _ in parsed]
        seconds = [int(s[1]) for s, _ in parsed]
        if any(v > 12 for v in firsts):
            return False
        if any(v > 12 for v in seconds):
            return True
        ctx.warn(f"{path.name} : ordre jour/mois ambigu, lu jour d'abord")
        return False

    def _when(self, s: tuple[str, ...], month_first: bool, ctx: ReadContext) -> Temps | None:
        a, b, y, hh, mm, ss, ampm = s
        day, month = (int(b), int(a)) if month_first else (int(a), int(b))
        year = int(y) + (2000 if len(y) == 2 else 0)
        hour = int(hh)
        if ampm:
            hour = hour % 12 + (12 if ampm.lower() == "p" else 0)
        try:
            dt = datetime(year, month, day, hour, int(mm), int(ss or 0), tzinfo=ctx.tz)
        except ValueError:
            return None
        return Temps.exact(dt, Origin.SOURCE)

    def _classify(self, author: str, text: str) -> tuple[str, tuple[Attachment, ...], str]:
        if not author:
            return "systeme", (), text
        stripped = text.strip()
        if stripped.lower() in _DELETED:
            return "supprime", (), ""
        m = _MEDIA.match(stripped)
        if m:
            name = (m.group("a") or m.group("b") or "média").strip()
            return "message", (Attachment(name),), ""
        return "message", (), text


_PHONE = re.compile(r"^\+?[\d\s().\-]{8,}$")


def _phone(text: str, country_code: str) -> str:
    """Un auteur nommé par son numéro (contact non enregistré) : le numéro normalisé."""
    if not _PHONE.match(text.strip()):
        return ""
    return normalize_phone(text, country_code)


def normalize_phone(text: str, country_code: str = "+33") -> str:
    digits = re.sub(r"[^\d+]", "", text)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits.startswith("0") and len(digits) == 10:  # numéro national français
        digits = country_code + digits[1:]
    return digits


READER = WhatsAppReader()
