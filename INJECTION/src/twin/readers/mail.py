"""Les mails : mbox (Thunderbird, export Gmail/Takeout), ``.eml`` et Maildir.

Un mail devient un message d'une conversation (le fil : la racine de ``References``,
sinon ``In-Reply-To``, sinon le sujet nettoyé de ses « Re: » et « TR: »). Le corps est
le texte brut (le HTML est dépouillé), **sans les citations** (« > … », « Le … a écrit : »,
« -----Original Message----- », l'en-tête « De : … Envoyé : … » d'Outlook) ni la
signature (« -- »). Un envoi de masse (``List-Unsubscribe``, ``Precedence: bulk``,
« noreply ») est marqué ``masse`` : le palier « bruit » le mettra de côté.

Ce qui est rangé dans un dossier « Envoyés » vient d'elle.
"""

from __future__ import annotations

import email
import email.policy
import html
import mailbox
import re
from collections.abc import Iterator
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from pathlib import Path

from twin.readers import ReadContext, head
from twin.records import MAIL, Attachment, Author, Conversation, Item, Message
from twin.timing import Origin, Temps

_SENT_FOLDERS = ("sent", "envoy", "éléments envoyés", "elements envoyes", "messages envoyés", "boîte d'envoi")
_REPLY_PREFIX = re.compile(r"^\s*((re|tr|fw|fwd|aw|wg)\s*(\[\d+\])?\s*:\s*)+", re.I)
_QUOTE_HEADERS = [
    re.compile(r"^\s*(le|on)\s.{5,120}(a écrit|wrote)\s*:\s*$", re.I | re.M),
    re.compile(r"^\s*-{2,}\s*(original message|message d'origine|forwarded message|message transféré)\s*-{2,}", re.I | re.M),
    re.compile(r"^\s*(de|from)\s*:\s.+\n\s*(envoyé|sent|date)\s*:\s.+", re.I | re.M),
]
_BULK_SENDERS = re.compile(r"(no-?reply|ne-?pas-?repondre|newsletter|notification|mailer-daemon|info@|news@)", re.I)
_HEADERS = ("from:", "to:", "subject:", "date:", "message-id:", "received:", "return-path:", "mime-version:")


def strip_quotes(body: str) -> str:
    """Le texte écrit dans ce mail-ci, sans ce qu'il cite ni la signature."""
    cut = len(body)
    for pat in _QUOTE_HEADERS:
        m = pat.search(body)
        if m:
            cut = min(cut, m.start())
    body = body[:cut]
    sig = re.search(r"^-- ?$", body, re.M)
    if sig:
        body = body[: sig.start()]
    lines = [ln for ln in body.splitlines() if not ln.lstrip().startswith(">")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(text: str) -> str:
    text = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d|blockquote)>", "\n", text)
    text = re.sub(r"(?is)<blockquote\b.*?</blockquote>", "\n", text)  # la citation d'un client web
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def body_of(msg: EmailMessage) -> tuple[str, tuple[Attachment, ...]]:
    plain = None
    rich = None
    atts: list[Attachment] = []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        ctype = part.get_content_type()
        if disposition == "attachment" or (part.get_filename() and not ctype.startswith("text/")):
            payload = part.get_payload(decode=True) or b""
            atts.append(Attachment(part.get_filename() or ctype, ctype, len(payload)))
            continue
        try:
            content = part.get_content()
        except (LookupError, ValueError, AssertionError):
            raw = part.get_payload(decode=True) or b""
            content = raw.decode("latin-1", errors="replace")
        if not isinstance(content, str):
            continue
        if ctype == "text/plain" and plain is None:
            plain = content
        elif ctype == "text/html" and rich is None:
            rich = content
    text = plain if plain is not None else html_to_text(rich or "")
    return strip_quotes(text.replace("\r\n", "\n")), tuple(atts)


def thread_key(msg: EmailMessage, subject: str, people: list[str]) -> str:
    refs = (msg.get("References") or "").split()
    if refs:
        return refs[0].strip()
    irt = (msg.get("In-Reply-To") or "").strip()
    if irt:
        return irt.split()[0]
    clean = _REPLY_PREFIX.sub("", subject).strip().lower()
    return f"sujet:{clean}|{'+'.join(sorted(people))}" if clean else (msg.get("Message-ID") or "").strip()


def is_bulk(msg: EmailMessage, sender: str) -> bool:
    prec = (msg.get("Precedence") or "").lower()
    return bool(msg.get("List-Unsubscribe") or msg.get("List-Id") or prec in ("bulk", "list", "junk")
                or _BULK_SENDERS.search(sender))


class MailReader:
    name = "mail"
    label = "Mails (mbox, .eml, Maildir)"
    version = 1

    def detect(self, path: Path) -> int:
        suffix = path.suffix.lower()
        if suffix in (".mbox", ".mbx"):
            return 90
        h = head(path, 2048)
        if h.startswith("From ") and "\nFrom:" in h:
            return 85  # mbox sans extension (Thunderbird)
        low = h.lower()
        if suffix == ".eml" or (suffix == "" and sum(low.count(k) for k in _HEADERS) >= 3):
            return 80 if any(k in low for k in ("from:", "message-id:")) else 0
        return 0

    def read(self, path: Path, ctx: ReadContext) -> Iterator[Item]:
        sent_box = any(f in p.lower() for p in path.parts for f in _SENT_FOLDERS)
        if path.suffix.lower() == ".eml" or not head(path, 5).startswith("From "):
            with path.open("rb") as f:
                msgs: Iterator[EmailMessage] = iter([email.message_from_binary_file(f, policy=email.policy.default)])  # type: ignore[list-item]
                yield from self._messages(msgs, path, ctx, sent_box)
        else:
            box = mailbox.mbox(path, factory=lambda f: email.message_from_binary_file(f, policy=email.policy.default),
                               create=False)
            try:
                yield from self._messages(iter(box), path, ctx, sent_box)
            finally:
                box.close()

    def _messages(self, msgs: Iterator[EmailMessage], path: Path, ctx: ReadContext, sent_box: bool) -> Iterator[Item]:
        known: set[str] = set()
        convs: set[str] = set()
        for rank, msg in enumerate(msgs):
            try:
                items = list(self._one(msg, rank, path, ctx, sent_box, known, convs))
            except (ValueError, TypeError, LookupError) as exc:
                ctx.warn(f"{path.name} : mail n°{rank} illisible ({exc})")
                continue
            yield from items

    def _one(self, msg: EmailMessage, rank: int, path: Path, ctx: ReadContext, sent_box: bool, known: set[str],
             convs: set[str]) -> Iterator[Item]:
        name, sender = parseaddr(str(msg.get("From") or ""))
        sender = sender.lower()
        if not sender:
            raise ValueError("sans expéditeur")
        recipients = [(n, a.lower()) for n, a in getaddresses([str(msg.get(h) or "") for h in ("To", "Cc")]) if a]
        for n, a in [(name, sender), *recipients]:
            if a not in known:
                known.add(a)
                me = True if (sent_box and a == sender) else None
                yield Author(MAIL, a, name=n or "", address=a, me=me,
                             me_reason="expéditrice d'un mail rangé dans « Envoyés »" if me else "")
        subject = str(msg.get("Subject") or "")
        people = sorted({sender, *(a for _, a in recipients)})
        conv = thread_key(msg, subject, people)
        if conv not in convs:
            convs.add(conv)
            yield Conversation(MAIL, conv, title=_REPLY_PREFIX.sub("", subject).strip(), group=len(people) > 2,
                               members=tuple(people))
        when = self._date(msg, path, ctx)
        text, atts = body_of(msg)
        kind = "masse" if is_bulk(msg, sender) else "message"
        yield Message(MAIL, conv, sender, text, when, rank, native_key=(msg.get("Message-ID") or "").strip(),
                      reply_to=(msg.get("In-Reply-To") or "").strip(), kind=kind, subject=subject,
                      attachments=atts)

    def _date(self, msg: EmailMessage, path: Path, ctx: ReadContext) -> Temps:
        raw = msg.get("Date")
        if raw:
            try:
                dt = parsedate_to_datetime(str(raw))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ctx.tz)
                return Temps.exact(dt, Origin.SOURCE)
            except (TypeError, ValueError, IndexError):
                ctx.warn(f"{path.name} : date de mail illisible « {raw} »")
        return Temps.unknown()


READER = MailReader()
