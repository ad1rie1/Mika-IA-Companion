"""Le monde extérieur simulé : une boîte aux lettres, des flux.

Ils appartiennent au monde, pas au noyau : ils survivent à ses redémarrages,
et le monde y dépose ce qui arrive (un mail, un article) à l'instant voulu.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from email.message import EmailMessage

from mika.adapters.mail import compose
from mika.ports.feeds import Entry
from mika.ports.mail import (
    AccountInfo,
    AccountStatus,
    Attachment,
    Contact,
    Draft,
    File,
    Folder,
    Mail,
    MailHit,
    MailQuery,
    Preview,
    Sent,
    addresses,
    forwarded_text,
    reference_key,
    split_ref,
)
from mika.ports.paging import Page, fold_text

#: la boîte simulée par défaut : un compte sans clé (les références restent les Message-ID)
DEFAULT_ACCOUNT = AccountInfo(key="", label="Sa boîte", address="mika@exemple.fr", ready=True, can_send=True)
FOLDERS = (("INBOX", "inbox"), ("Brouillons", "drafts"), ("Envoyés", "sent"), ("Archives", "archive"),
           ("Indésirables", "junk"), ("Corbeille", "trash"))


@dataclass(slots=True)
class FakeMail:
    """Une boîte aux lettres simulée, qui suit le port du courrier : des comptes,
    des dossiers, des drapeaux, des brouillons ; ce qui part est mis en forme
    comme par l'adaptateur réel (``compose``)."""

    inbox: list[Mail] = field(default_factory=list)
    handed: set[str] = field(default_factory=set)
    sent: list[tuple[str, str, str, str]] = field(default_factory=list)
    #: ce qui est parti, avec qui l'a écrit (la console, « Envoyés »)
    outgoing: list[Sent] = field(default_factory=list)
    #: l'horloge du monde (l'instant d'un envoi)
    now: Callable[[], int] = lambda: 0
    enabled: bool = True
    polls: int = 0
    #: les comptes (par défaut : un seul, sans clé)
    boxes: list[AccountInfo] = field(default_factory=lambda: [DEFAULT_ACCOUNT])
    kept_drafts: dict[str, Draft] = field(default_factory=dict)
    read_elsewhere: list[str] = field(default_factory=list)
    #: les actions faites sur le serveur (``("seen", réf)``, ``("move", réf, dossier)``…)
    actions: list[tuple[str, ...]] = field(default_factory=list)
    files: dict[tuple[str, str], File] = field(default_factory=dict)
    outgoing_files: dict[str, tuple[File, ...]] = field(default_factory=dict)

    # ── comptes ──
    def configured(self) -> bool:
        return self.enabled and any(a.ready for a in self.boxes)

    def accounts(self) -> list[AccountInfo]:
        return [replace(a, ready=a.ready and self.enabled, can_send=a.can_send and self.enabled) for a in self.boxes]

    def account(self, key: str) -> AccountInfo | None:
        return next((a for a in self.accounts() if a.key == key), None)

    # ── le monde dépose ──
    def deliver(self, mail: Mail) -> None:
        self.inbox.append(replace(mail, folder=mail.folder or "INBOX"))

    def read_on_another_device(self, ref: str) -> None:
        self._update(ref, seen=True)
        self.read_elsewhere.append(ref)

    def _find(self, ref: str) -> int | None:
        account, mid = split_ref(ref)
        for i, m in enumerate(self.inbox):
            if m.message_id == mid and (not account or m.account == account):
                return i
        return None

    def _update(self, ref: str, **changes: object) -> Mail:
        i = self._find(ref)
        if i is None:
            raise ValueError("ce mail n'est plus dans le cache")
        self.inbox[i] = replace(self.inbox[i], **changes)  # type: ignore[arg-type]
        return self.inbox[i]

    # ── relever ──
    async def fetch_new(self, limit: int) -> list[Mail]:
        self.polls += 1
        if not self.configured():
            return []
        polled = {a.key: set(a.folders) for a in self.accounts() if a.ready}
        fresh = [m for m in self.inbox if m.account in polled and m.folder in polled[m.account]
                 and m.ref not in self.handed][:limit]
        self.handed |= {m.ref for m in fresh}
        return fresh

    def seen_elsewhere(self) -> list[str]:
        out, self.read_elsewhere = self.read_elsewhere, []
        return out

    async def get(self, ref: str) -> Mail | None:
        return self.cached_one(ref)

    async def recent(self, limit: int) -> list[Mail]:
        return self.cached(limit)

    def cached_one(self, ref: str) -> Mail | None:
        i = self._find(ref)
        return self.inbox[i] if i is not None else None

    def cached(self, limit: int, *, account: str = "", folder: str = "") -> list[Mail]:
        kept = [m for m in self.inbox if (not account or m.account == account) and (not folder or m.folder == folder)]
        return sorted(kept, key=lambda m: -m.date)[:limit]

    def search(self, text: str, limit: int, *, account: str = "") -> list[Mail]:
        low = text.lower().strip()
        return [m for m in self.cached(10_000, account=account)
                if low and low in f"{m.subject} {m.sender} {m.body}".lower()][:limit]

    def messages_page(self, query: MailQuery, page=1, size=25):
        kept = [m for m in self.inbox if (not query.account or m.account == query.account)
                and (not query.folder or m.folder == query.folder)
                and (query.seen is None or m.seen == query.seen)
                and (query.flagged is None or m.flagged == query.flagged)
                and (query.refs is None or m.ref in query.refs) and m.ref not in query.exclude
                and fold_text(query.text) in fold_text(f"{m.subject} {m.sender} {m.body}")
                and fold_text(query.sender) in fold_text(f"{m.sender} {m.address}")]
        return Page.of(sorted(kept, key=lambda m: (-m.date, m.ref)), page, size)

    def find_ref(self, key):
        return next((m.ref for m in (*self.inbox, *self.outgoing)
                     if key in (reference_key(m.ref), reference_key(m.message_id))), None)

    def _letters(self):
        letters = {}
        sent_folders = {(a.key, f.name) for a in self.accounts() for f in self.folders(a.key) if f.role == "sent"}
        for m in sorted(self.inbox, key=lambda m: (m.folder == "INBOX", m.date)):
            sent = (m.account, m.folder) in sent_folders or letters.get((m.account, m.message_id), (None, False, False))[2]
            letters[m.account, m.message_id] = (m, False, sent)
        for m in self.outgoing:
            letters[m.account, split_ref(m.message_id)[1]] = (m, True, True)
        return letters

    def outgoing_page(self, query: MailQuery, page=1, size=25):
        rows = [(m, local) for m, local, sent in self._letters().values() if sent
                and (not query.account or m.account == query.account)
                and fold_text(query.text) in fold_text(f"{m.subject} {m.to} {m.body}")]
        return Page.of(sorted(rows, key=lambda item: (-item[0].date, item[0].ref)), page, size)

    @staticmethod
    def _hit(m, sent):
        return MailHit(m.ref, split_ref(m.message_id)[1], m.account, m.subject, m.date,
                       f"à {m.to}" if sent else m.sender, sent)

    def search_page(self, text, limit=25, offset=0):
        rows = [self._hit(m, sent) for m, _, sent in self._letters().values()
                if fold_text(text) in fold_text(f"{m.subject} {m.to} {getattr(m, 'sender', '')} {m.body}")]
        return sorted(rows, key=lambda m: (-m.date, m.ref))[offset:offset + limit]

    def search_count(self, text):
        return sum(fold_text(text) in fold_text(f"{m.subject} {m.to} {getattr(m, 'sender', '')} {m.body}")
                   for m, _, _ in self._letters().values())

    def thread_page(self, ref, page=1, size=25):
        selected = self.cached_one(ref) or self.sent_mail(ref)
        if selected is None:
            return Page((), 0)
        letters = {mid: (m, sent) for (account, mid), (m, _, sent) in self._letters().items() if account == selected.account}
        connected = {split_ref(selected.message_id)[1]}
        while True:
            related = {key for mid, (m, _) in letters.items()
                       for key in (mid, split_ref(m.in_reply_to)[1])
                       if key and (mid in connected or split_ref(m.in_reply_to)[1] in connected)}
            if related <= connected:
                break
            connected |= related
        rows = [self._hit(m, sent) for mid, (m, sent) in letters.items() if mid in connected]
        return Page.of(sorted(rows, key=lambda m: (m.date, m.ref)), page, size)

    def contacts_page(self, account="", text="", page=1, size=25):
        own = {a.address.lower() for a in self.accounts()}
        book = {}
        for m, _, sent in self._letters().values():
            if account and m.account != account:
                continue
            for name, address in addresses(','.join(x for x in (m.to, m.cc) if x)) if sent else addresses(m.sender):
                if address in own:
                    continue
                old = book.get(address, Contact(address, name, 0, 0, 0))
                book[address] = Contact(address, old.name or name, old.received + int(not sent),
                                        old.sent + int(sent), max(old.last, m.date))
        rows = [c for c in book.values() if fold_text(text) in fold_text(c.name + ' ' + c.address)]
        return Page.of(sorted(rows, key=lambda c: (-c.last, c.address)), page, size)

    def drafts_page(self, text="", page=1, size=25):
        rows = [d for d in self.kept_drafts.values() if fold_text(text) in fold_text(d.subject + ' ' + d.to)]
        return Page.of(sorted(rows, key=lambda d: (-d.updated, d.id)), page, size)

    async def document(self, ref):
        return self.cached_one(ref) or self.sent_mail(ref)

    async def file(self, ref, part):
        found = self.files.get((ref, part))
        if found is not None:
            return found
        m = self.cached_one(ref) or self.sent_mail(ref)
        if m is None:
            raise FileNotFoundError("Ce message n'est plus disponible.")
        if part == "texte":
            return File("message.txt", "text/plain", m.body.encode())
        if part == "source":
            raw = EmailMessage()
            raw['Subject'], raw['To'], raw['Message-ID'] = m.subject, m.to, m.message_id
            raw['From'] = getattr(m, 'sender', '')
            raw.set_content(m.body)
            for file in self.outgoing_files.get(m.message_id, ()):
                maintype, _, subtype = file.mime.partition('/')
                raw.add_attachment(file.data, maintype=maintype, subtype=subtype, filename=file.name)
            return File("message.eml", "message/rfc822", raw.as_bytes())
        if part.isdecimal() and int(part) < len(self.outgoing_files.get(m.message_id, ())):
            return self.outgoing_files[m.message_id][int(part)]
        raise FileNotFoundError("Cette pièce jointe n'est plus disponible.")

    async def forward(self, ref, to, subject, body, *, cc="", by="", attachments=True):
        m = self.cached_one(ref) or self.sent_mail(ref)
        if m is None:
            raise ValueError("Ce message n'est plus disponible.")
        files = tuple([await self.file(ref, str(i)) for i, _ in enumerate(getattr(m, 'attachments', ()))]) if attachments else ()
        mid = await self.send(to, subject, forwarded_text(m, body), by=by, account=m.account, cc=cc)
        self.outgoing_files[mid] = files
        self.outgoing[-1] = replace(self.outgoing[-1], attachments=tuple(Attachment(f.name, f.mime, len(f.data)) for f in files))
        return mid

    # ── dossiers ──
    def folders(self, account: str) -> list[Folder]:
        info = self.account(account)
        polled = set(info.folders) if info is not None else set()
        return [Folder(account, name, role, name in polled,
                       sum(1 for m in self.inbox if m.account == account and m.folder == name),
                       sum(1 for m in self.inbox if m.account == account and m.folder == name and not m.seen))
                for name, role in FOLDERS]

    async def refresh_folders(self, account: str) -> list[Folder]:
        return self.folders(account)

    async def sync_folder(self, account: str, folder: str, limit: int) -> int:
        return 0

    async def older(self, account: str, folder: str, limit: int = 50) -> int:
        return 0

    async def set_flags(self, ref: str, *, seen: bool | None = None, flagged: bool | None = None) -> None:
        changes = {k: v for k, v in (("seen", seen), ("flagged", flagged)) if v is not None}
        self._update(ref, **changes)
        self.actions += [(k if v else f"un{k}", ref) for k, v in changes.items()]

    async def mark_seen(self, refs) -> int:
        """Par lot (une seule action) ; rend combien sont inconnus."""
        known = [r for r in dict.fromkeys(refs) if self._find(r) is not None]
        for ref in known:
            self._update(ref, seen=True)
        self.actions.append(("seen_many", tuple(known)))
        return len(set(refs)) - len(known)

    async def move(self, ref: str, folder: str) -> str:
        if folder not in dict(FOLDERS):
            raise ValueError(f"dossier inconnu : {folder}")
        self._update(ref, folder=folder)
        self.actions.append(("move", ref, folder))
        return folder

    async def archive(self, ref: str) -> str:
        return await self.move(ref, "Archives")

    async def trash(self, ref: str) -> str:
        return await self.move(ref, "Corbeille")

    async def delete(self, ref: str) -> None:
        i = self._find(ref)
        if i is None or self.inbox[i].folder != "Corbeille":
            raise ValueError("on ne supprime définitivement que depuis la corbeille")
        del self.inbox[i]
        self.actions.append(("delete", ref))

    # ── envoyer ──
    def _sender(self, account: str, reply_to: str) -> AccountInfo:
        if account:
            found = self.account(account)
        else:
            parent = self.cached_one(reply_to) if reply_to else None
            found = self.account(parent.account) if parent is not None else None
            found = found or next((a for a in self.accounts() if a.can_send), None)
        if found is None:
            raise RuntimeError("aucun serveur d'envoi configuré")
        return found

    def _preview(self, draft: Draft) -> tuple[Preview, Mail | None]:
        parent = self.cached_one(draft.reply_to) if draft.reply_to else None
        return compose.preview(draft, self.account(draft.account), parent), parent

    async def send(self, to: str, subject: str, body: str, in_reply_to: str = "", by: str = "", *,
                   account: str = "", cc: str = "", quote: bool = False) -> str:
        info = self._sender(account, in_reply_to)
        shown, _ = self._preview(Draft("", info.key, to, subject, body, cc, in_reply_to, quote, by))
        if shown.blocked:
            raise RuntimeError(shown.blocked)
        self.sent.append((to, subject, body, in_reply_to))
        return self._gone(info.key, shown, in_reply_to, by, "")

    def _gone(self, account: str, shown: Preview, in_reply_to: str, by: str, draft: str) -> str:
        message_id = f"<envoi-{len(self.outgoing) + 1}@sim>"
        self.outgoing.append(Sent(message_id, shown.to, shown.subject, shown.text, self.now(), in_reply_to, by,
                                  account, draft, shown.cc))
        return message_id

    def sent_mails(self, limit: int, *, account: str = "") -> list[Sent]:
        return [m for m in reversed(self.outgoing) if not account or m.account == account][:limit]

    def sent_mail(self, message_id: str) -> Sent | None:
        account, mid = split_ref(message_id)
        return next((m for m in self.outgoing if m.message_id in (message_id, mid)
                     and (not account or m.account == account)), None)

    # ── brouillons ──
    def save_draft(self, draft: Draft) -> Draft:
        if not draft.id:
            draft = replace(draft, id=f"b{len(self.kept_drafts) + 1}", created=self.now())
        draft = replace(draft, updated=self.now())
        self.kept_drafts[draft.id] = draft
        return draft

    def draft(self, draft_id: str) -> Draft | None:
        return self.kept_drafts.get(draft_id)

    def drafts(self, limit: int, *, state: str = "") -> list[Draft]:
        kept = [d for d in self.kept_drafts.values() if not state or d.state == state]
        return sorted(kept, key=lambda d: (-d.updated, d.id))[:limit]

    def discard_draft(self, draft_id: str) -> None:
        found = self.kept_drafts.get(draft_id)
        if found is not None and found.state == "brouillon":
            self.kept_drafts[draft_id] = replace(found, state="abandonne")

    def preview(self, draft_id: str) -> Preview | None:
        found = self.kept_drafts.get(draft_id)
        return self._preview(found)[0] if found is not None else None

    async def send_draft(self, draft_id: str, *, by: str = "", digest: str = "") -> str:
        found = self.kept_drafts.get(draft_id)
        if found is None:
            raise ValueError("ce brouillon n'existe plus")
        if found.state != "brouillon":
            raise ValueError("ce brouillon est déjà parti" if found.state == "envoye" else "ce brouillon a été abandonné")
        shown, _ = self._preview(found)
        if shown.blocked:
            raise ValueError(shown.blocked)
        if digest and digest != shown.digest:
            raise ValueError("ce brouillon a changé depuis qu'il a été lu : relis-le avant de l'envoyer")
        self.sent.append((found.to, found.subject, found.body, found.reply_to))
        message_id = self._gone(found.account, shown, found.reply_to, by or found.author, draft_id)
        self.kept_drafts[draft_id] = replace(found, state="envoye", sent_id=message_id)
        return message_id

    # ── état ──
    async def test(self, account: str) -> tuple[bool, str]:
        return (True, "Lecture : ok ; envoi : ok.") if self.enabled else (False, "Lecture : échec.")

    def status(self, account: str) -> AccountStatus:
        return AccountStatus(account, last_poll=self.now() if self.polls else 0)


@dataclass(slots=True)
class FakeFeeds:
    entries: list[Entry] = field(default_factory=list)
    articles: dict[str, str] = field(default_factory=dict)
    handed: set[str] = field(default_factory=set)
    read: list[str] = field(default_factory=list)
    polls: int = 0

    def configured(self) -> bool:
        return True

    def publish(self, entry: Entry, article: str = "") -> None:
        self.entries.append(entry)
        if article:
            self.articles[entry.id] = article

    async def poll(self, limit: int) -> list[Entry]:
        self.polls += 1
        fresh = [e for e in self.entries if e.id not in self.handed][:limit]
        self.handed |= {e.id for e in fresh}
        return fresh

    async def entry(self, entry_id: str) -> Entry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    async def recent(self, limit: int) -> list[Entry]:
        return self.cached(limit)

    def cached(self, limit: int) -> list[Entry]:
        return sorted(self.entries, key=lambda e: -e.published)[:limit]

    def cached_count(self) -> int:
        return len(self.entries)

    def entries_page(self, feed="", text="", page=1, size=25):
        rows = [e for e in self.entries if fold_text(feed) in fold_text(e.feed)
                and fold_text(text) in fold_text(e.title + ' ' + e.summary)]
        return Page.of(sorted(rows, key=lambda e: -e.published), page, size)

    def entry_count(self, feed="", exclude=()):
        return sum(fold_text(feed) in fold_text(e.feed) and e.id not in exclude for e in self.entries)

    def feed_counts(self):
        counts = {}
        for e in self.entries:
            counts[e.feed] = counts.get(e.feed, 0) + 1
        return counts

    def followed(self) -> list[tuple[str, str]]:
        return [(feed, "") for feed in sorted({e.feed for e in self.entries})]

    async def article(self, entry_id: str) -> str:
        self.read.append(entry_id)
        return self.articles.get(entry_id, "")
