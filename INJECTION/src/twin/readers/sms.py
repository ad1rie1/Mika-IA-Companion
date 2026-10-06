"""SMS et MMS : la sauvegarde XML de « SMS Backup & Restore » (Android).

::

    <sms address="+33612345678" date="1552395933000" type="2" body="Salut" contact_name="Julie" />
    <mms date="1552395933000" msg_box="1" address="+336…~+336…" contact_name="Julie, Paul">
      <parts><part ct="text/plain" text="coucou"/><part ct="image/jpeg" name="IMG.jpg"/></parts>
      <addrs><addr address="+336…" type="137"/><addr address="+336…" type="151"/></addrs>
    </mms>

``type`` 1 = reçu, 2 = envoyé (``msg_box`` pour un MMS) : ce qui est envoyé vient d'elle.
Lu en flux (``iterparse``) : une sauvegarde de dix ans pèse des centaines de Mo.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

from twin.readers import ReadContext, head
from twin.readers.whatsapp import normalize_phone
from twin.records import ME, SMS, Attachment, Author, Conversation, Item, Message
from twin.timing import US, Origin, Temps

RECEIVED, SENT = "1", "2"
MMS_FROM = "137"


class SmsReader:
    name = "sms"
    label = "SMS / MMS (SMS Backup & Restore, XML)"
    version = 1

    def detect(self, path: Path) -> int:
        if path.suffix.lower() != ".xml":
            return 0
        h = head(path, 4096)
        return 95 if ("<smses" in h or "<allsms" in h) and ("<sms " in h or "<mms " in h or "count=" in h) else 0

    def read(self, path: Path, ctx: ReadContext) -> Iterator[Item]:
        seen_people: set[str] = set()
        seen_convs: set[str] = set()
        ranks: dict[str, int] = {}
        yield Author(SMS, ME, name="", me=True, me_reason="messages envoyés depuis son téléphone")
        for _event, el in ET.iterparse(path, events=("end",)):
            if el.tag not in ("sms", "mms"):
                continue
            try:
                items = list(self._one(el, ctx, seen_people, seen_convs, ranks))
            except (ValueError, KeyError) as exc:
                ctx.warn(f"{path.name} : {el.tag} illisible ({exc})")
                items = []
            el.clear()
            yield from items

    def _one(self, el: ET.Element, ctx: ReadContext, people: set[str], convs: set[str],
             ranks: dict[str, int]) -> Iterator[Item]:
        stamp = int(el.get("date") or 0)
        if not stamp:
            raise ValueError("sans date")
        when = Temps.exact(stamp * (US // 1000), Origin.SOURCE)
        names = [n.strip() for n in (el.get("contact_name") or "").split(",")]
        if el.tag == "sms":
            others = [normalize_phone(el.get("address", ""), ctx.country_code)]
            sent = el.get("type") == SENT
            sender = ME if sent else others[0]
            text = el.get("body") or ""
            atts: tuple[Attachment, ...] = ()
        else:
            addrs = [(normalize_phone(a.get("address", ""), ctx.country_code), a.get("type", ""))
                     for a in el.iter("addr")]
            others = sorted({a for a, _ in addrs if a and a != "insert-address-token"})
            sent = el.get("msg_box") == SENT
            sender = ME if sent else next((a for a, t in addrs if t == MMS_FROM), others[0] if others else "")
            if sent:
                others = [a for a in others if a != sender]
            parts = list(el.iter("part"))
            text = "\n".join(p.get("text") or "" for p in parts if (p.get("ct") or "").startswith("text/plain"))
            atts = tuple(Attachment(p.get("name") or p.get("cl") or p.get("ct", ""), p.get("ct", ""))
                         for p in parts if not (p.get("ct") or "").startswith(("text/", "application/smil")))
        others = [o for o in others if o]
        if not others:
            raise ValueError("sans correspondant")
        conv = "+".join(sorted(others))
        for i, addr in enumerate(others):
            if addr not in people:
                people.add(addr)
                name = names[i] if len(names) == len(others) and names[i] not in ("", "(Unknown)", "null") else ""
                yield Author(SMS, addr, name=name, address=addr, me=False, me_reason="correspondante d'un SMS")
        if conv not in convs:
            convs.add(conv)
            title = ", ".join(n for n in names if n and n not in ("(Unknown)", "null")) or conv
            yield Conversation(SMS, conv, title=title, group=len(others) > 1, members=(ME, *others))
        rank = ranks.get(conv, 0)
        ranks[conv] = rank + 1
        yield Message(SMS, conv, sender, text, when, rank, attachments=atts)


READER = SmsReader()
