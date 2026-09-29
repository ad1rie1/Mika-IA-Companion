"""Le monde extérieur simulé : une boîte aux lettres, des flux.

Ils appartiennent au monde, pas au noyau : ils survivent à ses redémarrages,
et le monde y dépose ce qui arrive (un mail, un article) à l'instant voulu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mika.ports.feeds import Entry
from mika.ports.mail import Mail


@dataclass(slots=True)
class FakeMail:
    inbox: list[Mail] = field(default_factory=list)
    handed: set[str] = field(default_factory=set)
    sent: list[tuple[str, str, str, str]] = field(default_factory=list)
    enabled: bool = True
    polls: int = 0

    def configured(self) -> bool:
        return self.enabled

    def deliver(self, mail: Mail) -> None:
        self.inbox.append(mail)

    async def fetch_new(self, limit: int) -> list[Mail]:
        self.polls += 1
        fresh = [m for m in self.inbox if m.message_id not in self.handed][:limit]
        self.handed |= {m.message_id for m in fresh}
        return fresh

    async def get(self, message_id: str) -> Mail | None:
        return self.cached_one(message_id)

    async def recent(self, limit: int) -> list[Mail]:
        return self.cached(limit)

    def cached_one(self, message_id: str) -> Mail | None:
        return next((m for m in self.inbox if m.message_id == message_id), None)

    def cached(self, limit: int) -> list[Mail]:
        return sorted(self.inbox, key=lambda m: -m.date)[:limit]

    async def send(self, to: str, subject: str, body: str, in_reply_to: str = "") -> str:
        self.sent.append((to, subject, body, in_reply_to))
        return f"<envoi-{len(self.sent)}@sim>"


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
