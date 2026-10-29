"""Ses outils prêtés à un agent (ADR 0122) : des points MCP qu'une opératrice déclare dans la console (Outils › Ce
qu'elle expose), servis sous ``/mcp/pret/<nom>``.

Un point prête une liste d'outils, choisis parmi ceux que la porte d'offre lui donne en conversation
(``runtime.tools.lendable``) — jamais au-delà de ce que le code permet. L'agent agit avec les droits de l'opératrice
qui a déclaré le point, comme si elle le lui demandait en tête-à-tête : son audience est celle de son adresse
(``audience_of``), la porte d'offre est relue à chaque appel, et un outil qu'elle ne lui offrirait plus n'est plus
servi. Chaque appel est une petite séance à lui (``pret:<nom>:…``), sans modèle : les arguments sont vérifiés comme
dans la boucle d'outils (``checked_args``), ses écritures portent cette corrélation. En lecture seule, rien ne
s'écrit dans sa vie (``ReadingContext``) : un outil qui voudrait écrire est refusé.

La porte : la boucle locale seulement, un jeton par point (seule son empreinte est gardée), au plus ``PER_MINUTE``
appels par minute. Un point sans jeton n'existe pas (404).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mika.adapters.mcp.protocol import Outcome, Tool, asgi, bearer, loopback
from mika.kernel.clock import US
from mika.kernel.faculty import ToolResult, ToolSpec
from mika.kernel.frame import CLOSED, Audience, EpisodeRef, Frame
from mika.runtime.bootstrap import Kernel
from mika.runtime.boundary import Failed, acall, call
from mika.runtime.tools import (
    ReadingContext,
    ReadOnly,
    ToolContext,
    checked_args,
    declare,
    gate_of,
    lendable,
    offer,
)
from mika.vocab.episodes import Kind

PREFIX = "/mcp/pret"
#: au-delà, un point refuse les appels de la minute (429) : un agent qui boucle ne la noie pas
PER_MINUTE = 60
#: les derniers appels d'un point, gardés pour la console (en mémoire : un redémarrage les oublie)
RECENT = 30
#: l'empreinte qu'on compare quand il n'y a rien à comparer (un point inconnu) : le même temps de calcul
_NOTHING = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True, slots=True)
class LentCall:
    """Un appel reçu par un point : quand, quel outil, s'il a réussi."""

    at: int
    tool: str
    ok: bool


@dataclass(frozen=True, slots=True)
class _Asking:
    """Ce que l'audience d'un épisode lit de sa demande : l'opératrice qui a déclaré le point, en tête-à-tête."""

    target: str
    kind: str = Kind.REPLY
    room: str | None = None
    channel: str | None = None


class LentHost:
    """Les outils d'un point, pour un agent MCP."""

    def __init__(self, lending: Lending, name: str, entry: Mapping[str, Any]) -> None:
        self.lending, self.point, self.entry = lending, name, entry
        self.name = f"mika-{name}"

    def tools(self) -> Sequence[Tool]:
        read_only = not self.entry.get("writes")
        specs = self.lending.offered(self.entry)
        return tuple(Tool(d.name, d.description, d.schema, read_only=read_only) for d in declare(list(specs.values())))

    async def call(self, name: str, arguments: Mapping[str, Any]) -> Outcome:
        return await self.lending.call(self.point, self.entry, name, arguments)


class Lending:
    """Les points de prêt : leur porte (``app``), et ce que la console en lit (``offered``, ``recent``)."""

    def __init__(self, kernel: Kernel, entries: Callable[[], Mapping[str, Mapping[str, Any]]]) -> None:
        self.kernel = kernel
        self.entries = entries
        self._minute: dict[str, deque[int]] = {}
        self._recent: dict[str, deque[LentCall]] = {}

    def audience(self, handle: str) -> Audience:
        """L'audience de l'opératrice qui a déclaré le point, en tête-à-tête ; une panne : fermée."""
        runner = self.kernel.runner
        if not handle or runner.audience_of is None:
            return CLOSED
        got = call(runner.audience_of, self.kernel.mind.frame(), _Asking(handle), label="audience d'un point de prêt")
        return CLOSED if isinstance(got, Failed) or got is None else got

    def candidates(self, handle: str) -> dict[str, ToolSpec]:
        """Ce qu'un point déclaré par cette opératrice peut prêter : ce que la porte lui offre en conversation, en
        tête-à-tête — ses règles d'outils comprises (ce qu'elle a retiré dans cette situation ne se prête pas, ADR
        0133) —, moins ce qui clôt une boucle."""
        runner = self.kernel.runner
        policy = runner.policies.get(Kind.REPLY)
        if policy is None:
            return {}
        audience = self.audience(handle)
        registry, frame = self.kernel.mind.registry, self.kernel.mind.frame()
        rights, close = gate_of(registry, frame)
        return lendable(offer(registry.tools, policy, Kind.REPLY, audience, frame=frame, rights=rights, close=close,
                              ports=runner.ports))

    def offered(self, entry: Mapping[str, Any]) -> dict[str, ToolSpec]:
        """Les outils que ce point sert maintenant : ceux qu'il prête, parmi ce qu'il peut prêter."""
        chosen = set(entry.get("tools") or ())
        return {n: s for n, s in self.candidates(str(entry.get("by") or "")).items() if n in chosen}

    def recent(self, name: str) -> list[LentCall]:
        """Les derniers appels d'un point, du plus récent au plus ancien."""
        return list(reversed(self._recent.get(name, ())))

    async def call(self, point: str, entry: Mapping[str, Any], name: str, arguments: Mapping[str, Any]) -> Outcome:
        spec = self.offered(entry).get(name)
        if spec is None:
            return Outcome(f"outil inconnu ou plus prêté ici : {name}", is_error=True)
        args, refused = checked_args(spec, arguments)
        if refused:
            self._note(point, name, False)
            return Outcome(refused, is_error=True)
        mind = self.kernel.mind
        handle = str(entry.get("by") or "")
        eid = f"pret:{point}:{secrets.token_hex(6)}"
        frame = Frame(mind.root, mind.clock.now(), mind.registry, self.audience(handle),
                      EpisodeRef(eid, Kind.REPLY, handle))
        kind = ToolContext if entry.get("writes") else ReadingContext
        ctx = kind(mind, spec, eid, eid, frame, guard=None, ports=self.kernel.runner.ports, dedupe_scope=eid,
                   call_key=f"{name}:1")
        out = await acall(spec.handler, args, ctx, label=f"outil prêté {name} ({point})")
        if isinstance(out, Failed):
            self._note(point, name, False)
            if isinstance(out.error, ReadOnly):
                return Outcome(str(out.error), is_error=True)
            return Outcome(f"l'outil a échoué : {out.error!r}", is_error=True)
        result = out if isinstance(out, ToolResult) else ToolResult(content=str(out))
        self._note(point, name, result.ok)
        return Outcome(result.content, is_error=not result.ok)

    def _note(self, point: str, tool: str, ok: bool) -> None:
        self._recent.setdefault(point, deque(maxlen=RECENT)).append(LentCall(self.kernel.mind.clock.now(), tool, ok))

    def _admitted(self, point: str) -> bool:
        """Sous le plafond de la minute (et l'appel compté)."""
        now = self.kernel.mind.clock.now()
        window = self._minute.setdefault(point, deque())
        while window and now - window[0] > 60 * US:
            window.popleft()
        if len(window) >= PER_MINUTE:
            return False
        window.append(now)
        return True

    def _host(self, scope: Mapping[str, Any]) -> Any:
        if not loopback(scope):
            return 403
        path, root = str(scope.get("path", "")), str(scope.get("root_path", ""))
        route = path[len(root):] if root and path.startswith(root) else path
        bits = [b for b in route.removeprefix(PREFIX).split("/") if b]
        if len(bits) != 1:
            return 404
        entry = self.entries().get(bits[0])
        expected = str((entry or {}).get("digest") or "")
        given = hashlib.sha256(bearer(scope).encode()).hexdigest()
        if not hmac.compare_digest(given, expected or _NOTHING) or not expected:
            return 404 if not expected else 401
        if not self._admitted(bits[0]):
            return 429
        return LentHost(self, bits[0], entry or {})

    def app(self) -> Callable[..., Any]:
        return asgi(self._host)
