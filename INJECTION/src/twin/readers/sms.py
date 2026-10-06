"""SMS et MMS : la sauvegarde XML de « SMS Backup & Restore » (Android).

::

    <sms address="+33612345678" date="1552395933000" type="2" body="Salut" contact_name="Julie" />
    <mms date="1552395933000" msg_box="1" address="+336…~+336…" contact_name="Julie, Paul">
      <parts><part ct="text/plain" text="coucou"/><part ct="image/jpeg" name="IMG.jpg"/></parts>
      <addrs><addr address="+336…" type="137"/><addr address="+336…" type="151"/></addrs>
    </mms>

``type`` (``msg_box`` pour un MMS) : 1 reçu ; 2 envoyé, 4 boîte d'envoi, 5 échec, 6 en file — ce qui part de son
téléphone vient d'elle ; 3 brouillon — jamais envoyé, ignoré.

Les MMS listent **son propre numéro** parmi les adresses (``type=151`` : destinataire). Un premier passage repère
le numéro présent dans presque tous les MMS : c'est le sien, il n'est ni une correspondante ni un membre de groupe.
Les noms (``contact_name``, « Lou, Paul ») suivent l'ordre des numéros d'``address`` (« +336…~+337… »).

La sauvegarde code parfois un émoji en demi-caractères (``&#55357;&#56832;``), ce qu'un parseur XML refuse : ils
sont recomposés au vol. Lu en flux (``iterparse``) : une sauvegarde de dix ans pèse des centaines de Mo. Le rang suit
le temps (la sauvegarde range tous les SMS puis tous les MMS).
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from twin.readers import ReadContext, head
from twin.readers.whatsapp import normalize_phone
from twin.records import ME, SMS, Attachment, Author, Conversation, Item, Message
from twin.timing import US, Origin, Temps

RECEIVED, DRAFT = "1", "3"
FROM_HER = ("2", "4", "5", "6")
MMS_FROM = "137"
#: un numéro présent dans au moins cette part des MMS : le sien
OWN_SHARE = 0.6
_SURROGATES = re.compile(rb"&#(5[5-6]\d{3});&#(5[6-7]\d{3});")


def _join_surrogates(m: re.Match[bytes]) -> bytes:
    hi, lo = int(m.group(1)), int(m.group(2))
    if 0xD800 <= hi <= 0xDBFF and 0xDC00 <= lo <= 0xDFFF:
        return f"&#{0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00)};".encode()
    return m.group(0)


class _Repaired(io.RawIOBase):
    """Le fichier, lu par morceaux, avec les émojis en demi-caractères recomposés (un morceau garde sa fin pour
    ne pas couper une entité en deux)."""

    def __init__(self, path: Path, chunk: int = 1 << 20) -> None:
        self.f = path.open("rb")
        self.chunk = chunk
        self.buf = b""
        self.carry = b""

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:  # type: ignore[no-untyped-def]
        while len(self.buf) < len(b):
            data = self.f.read(self.chunk)
            if not data:
                self.buf += _SURROGATES.sub(_join_surrogates, self.carry)
                self.carry = b""
                break
            data = self.carry + data
            cut = data.rfind(b"&")
            keep = data[cut:] if cut != -1 and len(data) - cut < 32 else b""
            self.carry = keep
            self.buf += _SURROGATES.sub(_join_surrogates, data[: len(data) - len(keep)])
        n = min(len(b), len(self.buf))
        b[:n] = self.buf[:n]
        self.buf = self.buf[n:]
        return n

    def close(self) -> None:
        self.f.close()
        super().close()


def _parse(path: Path) -> Iterator[tuple[str, ET.Element]]:
    with io.BufferedReader(_Repaired(path)) as f:
        yield from ET.iterparse(f, events=("end",))


class SmsReader:
    name = "sms"
    label = "SMS / MMS (SMS Backup & Restore, XML)"
    version = 2

    def detect(self, path: Path) -> int:
        if path.suffix.lower() != ".xml":
            return 0
        h = head(path, 4096)
        return 95 if ("<smses" in h or "<allsms" in h) and ("<sms " in h or "<mms " in h or "count=" in h) else 0

    def read(self, path: Path, ctx: ReadContext) -> Iterator[Item]:
        own = self._own_number(path, ctx)
        seen_people: set[str] = set()
        seen_convs: set[str] = set()
        yield Author(SMS, ME, name="", address=own or "", me=True, me_reason="messages envoyés depuis son téléphone")
        for _event, el in _parse(path):
            if el.tag not in ("sms", "mms"):
                continue
            try:
                items = list(self._one(el, ctx, own, seen_people, seen_convs))
            except (ValueError, KeyError) as exc:
                ctx.warn(f"{path.name} : {el.tag} illisible ({exc})")
                items = []
            el.clear()
            yield from items

    def _own_number(self, path: Path, ctx: ReadContext) -> str | None:
        """Le numéro présent dans presque tous les MMS : le sien (premier passage, les adresses seulement)."""
        counts: Counter[str] = Counter()
        total = 0
        for _event, el in _parse(path):
            if el.tag == "mms":
                total += 1
                counts.update({normalize_phone(a.get("address", ""), ctx.country_code) for a in el.iter("addr")})
                el.clear()
            elif el.tag == "sms":
                el.clear()
        if total < 3 or not counts:
            return None
        number, n = counts.most_common(1)[0]
        return number if n >= OWN_SHARE * total else None

    def _one(self, el: ET.Element, ctx: ReadContext, own: str | None, people: set[str],
             convs: set[str]) -> Iterator[Item]:
        stamp = int(el.get("date") or 0)
        if not stamp:
            raise ValueError("sans date")
        box = el.get("type") if el.tag == "sms" else el.get("msg_box")
        if box == DRAFT:
            return  # un brouillon n'a jamais été envoyé
        when = Temps.exact(stamp * (US // 1000), Origin.SOURCE)
        sent = box in FROM_HER
        raw_addresses = [normalize_phone(a, ctx.country_code) for a in (el.get("address") or "").split("~") if a]
        names = [n.strip() for n in (el.get("contact_name") or "").split(",")]
        named = {a: n for a, n in zip(raw_addresses, names, strict=False)
                 if len(names) == len(raw_addresses) and n not in ("", "(Unknown)", "null")}
        if el.tag == "sms":
            others = raw_addresses[:1]
            sender = ME if sent else (others[0] if others else "")
            text = el.get("body") or ""
            atts: tuple[Attachment, ...] = ()
        else:
            addrs = [(normalize_phone(a.get("address", ""), ctx.country_code), a.get("type", ""))
                     for a in el.iter("addr")]
            others = sorted({a for a, _ in addrs if a and a != "insert-address-token" and a != own})
            sender = ME if sent else next((a for a, t in addrs if t == MMS_FROM and a != own), others[0] if others else "")
            parts = list(el.iter("part"))
            text = "\n".join(p.get("text") or "" for p in parts if (p.get("ct") or "").startswith("text/plain"))
            atts = tuple(Attachment(p.get("name") or p.get("cl") or p.get("ct", ""), p.get("ct", ""))
                         for p in parts if not (p.get("ct") or "").startswith(("text/", "application/smil")))
        others = [o for o in others if o and o != own]
        if not others:
            raise ValueError("sans correspondant")
        conv = "+".join(sorted(others))
        for addr in others:
            if addr not in people:
                people.add(addr)
                yield Author(SMS, addr, name=named.get(addr, ""), address=addr, me=False,
                             me_reason="correspondante d'un SMS")
        if conv not in convs:
            convs.add(conv)
            title = ", ".join(named[a] for a in others if a in named) or conv
            yield Conversation(SMS, conv, title=title, group=len(others) > 1, members=(ME, *others))
        # le rang suit le temps : la sauvegarde range tous les SMS, puis tous les MMS
        yield Message(SMS, conv, sender, text, when, stamp, attachments=atts)


READER = SmsReader()
