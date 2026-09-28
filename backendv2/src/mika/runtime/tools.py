"""La boucle d'outils — une seule, pour tous les fournisseurs.

Trois issues d'un appel d'outil, aucune ne remonte en exception : outil
inconnu, arguments illisibles, gestionnaire qui lève → un résultat d'erreur
rendu au modèle. Un appel d'outil coupé par la limite de jetons est rejoué une
fois avec une limite doublée. Un outil émet ses événements tout de suite ; le
suivant voit l'état à jour (il lit ses propres écritures).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from mika.kernel.events import Draft, Origin
from mika.kernel.faculty import ToolSpec
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.ports.llm import LLMGateway, LLMRequest, LLMResponse, Message, ToolDecl
from mika.runtime.boundary import Failed, acall

if TYPE_CHECKING:
    from mika.runtime.mind import Commit, Mind

TOOL_CALL_CAP_CEILING = 16_384
TRUNCATED_MARKER = "[réponse tronquée avant l'appel d'outil]"
MAX_TURNS_MARKER = "[trop d'appels d'outils : j'arrête là]"
#: Clé que posent les fournisseurs quand les arguments d'un appel ne sont pas
#: du JSON : l'appel est refusé au modèle, jamais exécuté avec des défauts.
RAW_ARGS_KEY = "_raw"


class ToolResult(BaseModel):
    ok: bool = True
    content: str = ""


@dataclass(slots=True)
class ToolContext:
    """Ce qu'un gestionnaire d'outil reçoit."""

    mind: Mind
    spec: ToolSpec
    call_id: str
    episode_id: str
    frame: Frame
    guard: Guard | None = None
    _emitted: int = 0

    @property
    def state(self) -> Any:
        return self.frame.state(self.spec.owner)

    async def emit(self, *drafts: Draft[Any]) -> Commit:
        keyed = []
        for d in drafts:
            key = d.dedupe_key or f"{self.call_id}:{self._emitted}"
            self._emitted += 1
            keyed.append(replace(d, dedupe_key=key))
        commit = await self.mind.append(
            keyed, emitter=self.spec.owner, correlation=self.episode_id, origin=Origin.TOOL,
            causation=None, basis=self.frame.root, guard=self.guard, holder=self.episode_id,
        )
        self.frame = Frame(commit.root, self.mind.clock.now(), self.mind.registry,
                           self.frame.audience, self.frame.episode)
        return commit


@dataclass(slots=True)
class LoopResult:
    text: str
    calls: list[tuple[str, bool]] = field(default_factory=list)
    stop: str = "end"
    responses: int = 0
    last: LLMResponse | None = None


def declare(specs: Sequence[ToolSpec]) -> tuple[ToolDecl, ...]:
    """Déclarations triées par nom : un préfixe stable pour le cache."""
    return tuple(
        ToolDecl(s.name, s.description, s.args.model_json_schema())
        for s in sorted(specs, key=lambda s: s.name)
    )


async def run_tool_loop(
    gateway: LLMGateway,
    request: LLMRequest,
    tools: Mapping[str, ToolSpec],
    make_context: Callable[[ToolSpec, str], ToolContext],
    *,
    max_turns: int,
) -> LoopResult:
    result = LoopResult(text="")
    req = request
    counts: dict[str, int] = {}
    replayed = False
    for _turn in range(max_turns):
        resp = await gateway.call(req)
        result.responses += 1
        result.last = resp
        if resp.truncated_tool_call:
            if not replayed and req.max_tokens < TOOL_CALL_CAP_CEILING:
                replayed = True
                req = replace(req, max_tokens=min(TOOL_CALL_CAP_CEILING, req.max_tokens * 2))
                continue
            result.text = (resp.text + "\n" + TRUNCATED_MARKER).strip()
            result.stop = "truncated"
            return result
        if not resp.tool_calls:
            result.text = resp.text
            result.stop = resp.stop
            return result
        outputs: list[Message] = []
        for call in resp.tool_calls:
            spec = tools.get(call.name)
            if spec is None:
                outputs.append(Message("tool", f"outil inconnu : {call.name}", tool_call_id=call.id,
                                       name=call.name, is_error=True))
                continue
            limit = spec.max_calls_per_episode
            if limit is not None and counts.get(call.name, 0) >= limit:
                outputs.append(Message("tool", f"{call.name} : plafond d'appels atteint pour cet épisode",
                                       tool_call_id=call.id, name=call.name, is_error=True))
                continue
            if RAW_ARGS_KEY in call.args:
                outputs.append(Message("tool", "arguments illisibles : ce n'était pas du JSON valide",
                                       tool_call_id=call.id, name=call.name, is_error=True))
                continue
            try:
                args = spec.args.model_validate(dict(call.args))
            except ValidationError as exc:
                outputs.append(Message("tool", f"arguments illisibles : {exc.errors(include_url=False)}",
                                       tool_call_id=call.id, name=call.name, is_error=True))
                continue
            counts[call.name] = counts.get(call.name, 0) + 1
            ctx = make_context(spec, call.id)
            out = await acall(spec.handler, args, ctx, label=f"outil {call.name}")
            if isinstance(out, Failed):
                result.calls.append((call.name, False))
                outputs.append(Message("tool", f"l'outil a échoué : {out.error!r}", tool_call_id=call.id,
                                       name=call.name, is_error=True))
                continue
            tr = out if isinstance(out, ToolResult) else ToolResult(content=_as_text(out))
            result.calls.append((call.name, tr.ok))
            outputs.append(Message("tool", tr.content, tool_call_id=call.id, name=call.name, is_error=not tr.ok))
        req = req.extend(Message("assistant", resp.text, tool_calls=resp.tool_calls), *outputs)
    result.text = MAX_TURNS_MARKER
    result.stop = "max_turns"
    return result


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)
