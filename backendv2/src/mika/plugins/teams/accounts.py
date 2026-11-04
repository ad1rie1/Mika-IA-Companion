"""Teams tel que ses outils le voient ici (ADR 0186) : le port, réduit aux comptes dont elle peut se servir devant qui
est en face (``accounts_here``). Un compte sert à son propriétaire : ce qui est dans un autre n'existe pas pour
l'outil — ni ses conversations, ni ses messages, ni ses brouillons.

Seuls ses outils (et la console, quand on y choisit « Les comptes de ») passent par là ; ce qui part après un accord
(la capacité) lit le port lui-même : l'accord a déjà décidé.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from mika.ports.teams import AccountInfo, Conversation, Draft, Message, Preview, Voice


class Accounts:
    """Le port de Teams, réduit à des comptes (``keys``)."""

    def __init__(self, port: Any, keys: Iterable[str]) -> None:
        self.port = port
        self.keys = tuple(keys)

    def _mine(self, account: str) -> bool:
        return account in self.keys

    # ── ses comptes ──

    def accounts(self) -> list[AccountInfo]:
        return [a for a in self.port.accounts() if self._mine(a.key)]

    def account(self, key: str) -> AccountInfo | None:
        return self.port.account(key) if self._mine(key) else None

    def configured(self, account: str = "") -> bool:
        if account:
            return self._mine(account) and self.port.configured(account)
        return any(self.port.configured(k) for k in self.keys)

    def last_batch(self, account: str) -> int:
        return self.port.last_batch(account) if self._mine(account) else 0

    def owner(self, account: str) -> tuple[str, str]:
        return self.port.owner(account) if self._mine(account) else ("", "")

    def voice(self, account: str) -> Voice:
        return self.port.voice(account) if self._mine(account) else Voice()

    # ── lire ──

    def message(self, ref: str) -> Message | None:
        m = self.port.message(ref)
        return m if m is not None and self._mine(m.account) else None

    def thread(self, account: str, conversation: str, limit: int, *, before: int = 0) -> list[Message]:
        return self.port.thread(account, conversation, limit, before=before) if self._mine(account) else []

    def conversation(self, account: str, conversation: str) -> Conversation | None:
        return self.port.conversation(account, conversation) if self._mine(account) else None

    def conversations(self, limit: int, *, text: str = "", accounts: Sequence[str] | None = None) \
            -> list[Conversation]:
        keys = self.keys if accounts is None else tuple(a for a in accounts if self._mine(a))
        return self.port.conversations(limit, text=text, accounts=keys)

    def title(self, account: str, conversation: str) -> str:
        return self.port.title(account, conversation) if self._mine(account) else ""

    # ── écrire ──

    def save_draft(self, draft: Draft) -> Draft:
        if not self._mine(draft.account):
            raise ValueError("ce compte Teams n'est pas à qui est en face")
        return self.port.save_draft(draft)

    def draft(self, draft_id: str) -> Draft | None:
        d = self.port.draft(draft_id)
        return d if d is not None and self._mine(d.account) else None

    def drafts(self, limit: int, *, state: str = "", accounts: Sequence[str] | None = None) -> list[Draft]:
        keys = self.keys if accounts is None else tuple(a for a in accounts if self._mine(a))
        return self.port.drafts(limit, state=state, accounts=keys)

    def preview(self, draft_id: str, *, her: str = "") -> Preview | None:
        return self.port.preview(draft_id, her=her) if self.draft(draft_id) is not None else None

    def discard_draft(self, draft_id: str) -> None:
        if self.draft(draft_id) is not None:
            self.port.discard_draft(draft_id)


class Scope(Accounts):
    """La console réduite aux comptes de qui on a choisi (``?qui=``) : un affichage, pas un droit — le reste du port
    passe tel quel (ses outils, eux, ont ``Accounts``, sans rien qui passe à côté)."""

    def __getattr__(self, name: str) -> Any:
        return getattr(self.port, name)
