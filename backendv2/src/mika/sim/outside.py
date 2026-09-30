"""Le monde extérieur simulé : une boîte aux lettres, des flux.

Ils appartiennent au monde, pas au noyau : ils survivent à ses redémarrages,
et le monde y dépose ce qui arrive (un mail, un article) à l'instant voulu.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

from mika.adapters.mail import compose
from mika.ports.feeds import Entry
from mika.ports.mail import AccountInfo, AccountStatus, Draft, Folder, Mail, Preview, Sent, split_ref

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

    async def set_flags(self, ref: str, *, seen: bool | None = None, flagged: bool | None = None) -> None:
        changes = {k: v for k, v in (("seen", seen), ("flagged", flagged)) if v is not None}
        self._update(ref, **changes)
        self.actions += [(k if v else f"un{k}", ref) for k, v in changes.items()]

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
        mid = split_ref(message_id)[1]
        return next((m for m in self.outgoing if m.message_id in (message_id, mid)), None)

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

    def followed(self) -> list[tuple[str, str]]:
        return [(feed, "") for feed in sorted({e.feed for e in self.entries})]

    async def article(self, entry_id: str) -> str:
        self.read.append(entry_id)
        return self.articles.get(entry_id, "")
