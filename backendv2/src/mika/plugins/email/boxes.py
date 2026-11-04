"""Le courrier tel que ses outils le voient ici (ADR 0185) : le port, réduit aux boîtes dont elle peut se servir
devant qui est en face (``boxes_here``). Une boîte sert à son propriétaire : ce qui est dans une autre n'existe pas
pour l'outil — ni ses mails, ni ses dossiers, ni ses brouillons, ni ses envois.

Seuls ses outils passent par là ; ce qui part après un accord (la capacité) lit le port lui-même : l'accord a déjà
décidé.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import Any

from mika.ports.mail import AccountInfo, Contact, Draft, Folder, Mail, MailQuery, Preview, Sent, split_ref
from mika.ports.paging import Page


class Boxes:
    """Le port du courrier, réduit à des boîtes (``keys``)."""

    def __init__(self, port: Any, keys: Iterable[str]) -> None:
        self.port = port
        self.keys = tuple(keys)

    def _mine(self, account: str) -> bool:
        return account in self.keys

    def _ref(self, ref: str) -> bool:
        return self._mine(split_ref(ref)[0])

    # ── ses boîtes ──

    def accounts(self) -> list[AccountInfo]:
        return [a for a in self.port.accounts() if self._mine(a.key)]

    def account(self, key: str) -> AccountInfo | None:
        return self.port.account(key) if self._mine(key) else None

    def folders(self, account: str) -> list[Folder]:
        return self.port.folders(account) if self._mine(account) else []

    def status(self, account: str) -> Any:
        return self.port.status(account)

    # ── lire ──

    def messages_page(self, query: MailQuery, page: int = 1, size: int = 25) -> Page[Mail]:
        if query.account and not self._mine(query.account):
            return Page.of([], page, size)
        return self.port.messages_page(replace(query, accounts=self.keys), page, size)

    def contacts_page(self, account: str = "", text: str = "", page: int = 1, size: int = 25) -> Page[Contact]:
        if account:
            return self.port.contacts_page(account, text, page, size) if self._mine(account) else Page.of([], page, size)
        if len(self.keys) == len(self.port.accounts()):
            return self.port.contacts_page("", text, page, size)
        found: dict[str, Contact] = {}
        for key in self.keys:  # quelques boîtes au plus : chacune, puis réunies
            for c in self.port.contacts_page(key, text, 1, size).items:
                found.setdefault(c.address, c)
        return Page.of(list(found.values()), page, size)

    async def get(self, ref: str) -> Mail | None:
        m = await self.port.get(ref)
        return m if m is not None and self._mine(m.account) else None

    def cached_one(self, ref: str) -> Mail | None:
        m = self.port.cached_one(ref)
        return m if m is not None and self._mine(m.account) else None

    def sent_mails(self, limit: int, *, account: str = "") -> list[Sent]:
        if account and not self._mine(account):
            return []
        return [s for s in self.port.sent_mails(limit, account=account) if self._mine(s.account)]

    def sent_mail(self, message_id: str) -> Sent | None:
        s = self.port.sent_mail(message_id)
        return s if s is not None and self._mine(s.account) else None

    # ── ranger ──

    async def set_flags(self, ref: str, *, seen: bool | None = None, flagged: bool | None = None) -> None:
        if self._ref(ref):
            await self.port.set_flags(ref, seen=seen, flagged=flagged)

    async def mark_seen(self, refs: Sequence[str]) -> int:
        return await self.port.mark_seen([r for r in refs if self._ref(r)])

    async def move(self, ref: str, folder: str) -> str:
        return await self.port.move(ref, folder) if self._ref(ref) else ""

    async def archive(self, ref: str) -> str:
        return await self.port.archive(ref) if self._ref(ref) else ""

    async def trash(self, ref: str) -> str:
        return await self.port.trash(ref) if self._ref(ref) else ""

    # ── écrire ──

    def save_draft(self, draft: Draft) -> Draft:
        if not self._mine(draft.account):
            raise ValueError("cette boîte n'est pas à qui est en face")
        return self.port.save_draft(draft)

    def draft(self, draft_id: str) -> Draft | None:
        d = self.port.draft(draft_id)
        return d if d is not None and self._mine(d.account) else None

    def preview(self, draft_id: str) -> Preview | None:
        return self.port.preview(draft_id) if self.draft(draft_id) is not None else None

    def discard_draft(self, draft_id: str) -> None:
        if self.draft(draft_id) is not None:
            self.port.discard_draft(draft_id)

    def recent_edits(self, account: str, limit: int) -> list[Draft]:
        return self.port.recent_edits(account, limit) if self._mine(account) else []
