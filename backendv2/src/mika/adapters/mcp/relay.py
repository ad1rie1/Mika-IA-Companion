"""Le relais : un serveur MCP par épisode, dont les outils ne s'exécutent pas ici.

Quand Claude Code appelle un outil, le relais met l'appel **en attente** et le
signale au backend ``claude_code``, qui le rend au runtime comme un appel
d'outil ordinaire. Le runtime l'exécute avec toutes ses gardes (validation,
plafonds par épisode, écritures corrélées à l'épisode, trace) ; au tour
suivant, le backend rend le résultat ici, et la réponse HTTP part vers la CLI.
La boucle d'outils reste donc unique, celle du runtime.

Chaque session a deux serveurs : ``mika`` (les outils en main, que la CLI
charge d'emblée) et ``plus`` (les outils à la demande, que la CLI charge par sa
recherche d'outils). Un jeton aléatoire par session ; seules les connexions
locales (127.0.0.1, ::1) sont servies ; une session fermée répond 404 et libère
ses appels encore en attente par une erreur.
"""

from __future__ import annotations

import asyncio
import hmac
import itertools
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mika.adapters.mcp.protocol import Outcome, Tool, asgi, bearer, loopback

PREFIX = "/mcp/relais"
PARTS = ("mika", "plus")
CLOSED = Outcome("l'épisode est fini : cet appel n'a pas été exécuté", is_error=True)


@dataclass(slots=True)
class Pending:
    """Un appel d'outil en attente d'être exécuté par le runtime."""

    id: str
    name: str
    args: dict[str, Any]
    future: asyncio.Future[Outcome] = field(repr=False)


class _Part:
    def __init__(self, session: RelaySession, name: str, tools: Sequence[Tool]) -> None:
        self.session = session
        self.name = name
        self._tools = tuple(tools)

    def tools(self) -> Sequence[Tool]:
        return self._tools

    async def call(self, name: str, arguments: Mapping[str, Any]) -> Outcome:
        return await self.session.park(name, arguments)


class RelaySession:
    def __init__(self, sid: str, token: str, core: Sequence[Tool], extra: Sequence[Tool],
                 on_call: Callable[[Pending], None]) -> None:
        self.id = sid
        self.token = token
        self.parts = {"mika": _Part(self, "mika", core), "plus": _Part(self, "plus", extra)}
        self._known = {t.name for t in (*core, *extra)}
        self._on_call = on_call
        self._pending: dict[str, Pending] = {}
        self._ids = itertools.count(1)
        self.closed = False

    async def park(self, name: str, arguments: Mapping[str, Any]) -> Outcome:
        if self.closed:
            return CLOSED
        if name not in self._known:
            return Outcome(f"outil inconnu : {name}", is_error=True)
        p = Pending(f"{self.id}-{next(self._ids)}", name, dict(arguments),
                    asyncio.get_running_loop().create_future())
        self._pending[p.id] = p
        self._on_call(p)
        try:
            return await p.future
        finally:
            self._pending.pop(p.id, None)

    def resolve(self, pending_id: str, outcome: Outcome) -> bool:
        p = self._pending.get(pending_id)
        if p is None or p.future.done():
            return False
        p.future.set_result(outcome)
        return True

    @property
    def waiting(self) -> tuple[str, ...]:
        return tuple(pid for pid, p in self._pending.items() if not p.future.done())

    def close(self) -> None:
        self.closed = True
        for p in list(self._pending.values()):
            if not p.future.done():
                p.future.set_result(CLOSED)


class Relay:
    """Les sessions ouvertes, et l'application ASGI qui les sert (montée sous ``PREFIX``)."""

    def __init__(self) -> None:
        self._sessions: dict[str, RelaySession] = {}
        self.app = asgi(self._host)

    def open(self, core: Sequence[Tool], extra: Sequence[Tool], on_call: Callable[[Pending], None]) -> RelaySession:
        sid = secrets.token_hex(8)
        session = RelaySession(sid, secrets.token_urlsafe(24), core, extra, on_call)
        self._sessions[sid] = session
        return session

    def close(self, session: RelaySession) -> None:
        session.close()
        self._sessions.pop(session.id, None)

    def __len__(self) -> int:
        return len(self._sessions)

    def __bool__(self) -> bool:
        # un relais sans session reste un relais : sans ceci, ``__len__`` le rendait faux et
        # « relay or Relay() » en créait un autre, jamais monté (la CLI recevait 404)
        return True

    @staticmethod
    def url(base: str, session: RelaySession, part: str) -> str:
        return f"{base.rstrip('/')}{PREFIX}/{session.id}/{part}"

    def _host(self, scope: Mapping[str, Any]) -> Any:
        if not loopback(scope):
            return 403
        path, root = str(scope.get("path", "")), str(scope.get("root_path", ""))
        route = path[len(root):] if root and path.startswith(root) else path
        if route.startswith(PREFIX):
            route = route[len(PREFIX):]
        bits = [b for b in route.split("/") if b]
        if len(bits) != 2 or bits[1] not in PARTS:
            return 404
        session = self._sessions.get(bits[0])
        if session is None or session.closed:
            return 404
        if not hmac.compare_digest(bearer(scope), session.token):
            return 401
        return session.parts[bits[1]]
