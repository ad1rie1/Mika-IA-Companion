"""La boucle d'outils — une seule, pour tous les fournisseurs.

Trois issues d'un appel d'outil, aucune ne remonte en exception : outil
inconnu, arguments illisibles, gestionnaire qui lève → un résultat d'erreur
rendu au modèle. Un appel d'outil coupé par la limite de jetons est rejoué une
fois avec une limite doublée. Un outil émet ses événements tout de suite ; le
suivant voit l'état à jour (il lit ses propres écritures).

Chaque appel d'outil laisse un ``ToolRecord`` (arguments et résultat bornés,
durée lue sur l'horloge injectée) : de quoi répondre à « pourquoi a-t-elle dit
ça ? » sans rejouer l'épisode.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from mika.kernel.events import Draft, Origin
from mika.kernel.faculty import ToolResult, ToolSpec
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.ports.llm import LLMGateway, LLMRequest, LLMResponse, Message, ToolCall, ToolDecl
from mika.runtime.boundary import Failed, acall

if TYPE_CHECKING:
    from mika.runtime.mind import Commit, Mind

TOOL_CALL_CAP_CEILING = 16_384
TRUNCATED_MARKER = "[réponse tronquée avant l'appel d'outil]"
MAX_TURNS_MARKER = "[trop d'appels d'outils : j'arrête là]"
#: Clé que posent les fournisseurs quand les arguments d'un appel ne sont pas
#: du JSON : l'appel est refusé au modèle, jamais exécuté avec des défauts.
RAW_ARGS_KEY = "_raw"
#: au-delà, les arguments et le résultat d'un appel sont coupés dans sa trace
RECORD_MAX_CHARS = 4096
RECORD_TRUNCATED = "…[coupé]"


@dataclass(slots=True)
class ToolContext:
    """Ce qu'un gestionnaire d'outil reçoit."""

    mind: Mind
    spec: ToolSpec
    call_id: str
    episode_id: str
    frame: Frame
    guard: Guard | None = None
    ports: Mapping[str, Any] = field(default_factory=dict)
    #: les appels d'outils déjà faits dans cet épisode (nom, réussi) : ce
    #: qu'elle a réellement fait, pour qui doit en juger (« fini » exige une preuve)
    calls: tuple[tuple[str, bool], ...] = ()
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


@dataclass(frozen=True, slots=True)
class ToolRecord:
    """Un appel d'outil tel qu'il s'est passé : ce que le modèle a demandé, ce
    qui lui a été rendu. ``executed`` est faux pour un appel refusé avant le
    gestionnaire (outil inconnu, plafond, arguments illisibles)."""

    call_id: str
    name: str
    args_json: str
    ok: bool
    result: str
    duration_us: int = 0
    executed: bool = True


@dataclass(slots=True)
class LoopResult:
    text: str
    #: (nom, réussi) des appels exécutés — ce que garde ``Utterance.tools``
    calls: list[tuple[str, bool]] = field(default_factory=list)
    stop: str = "end"
    responses: int = 0
    last: LLMResponse | None = None
    #: chaque appel d'outil, exécuté ou refusé, dans l'ordre
    records: list[ToolRecord] = field(default_factory=list)
    #: chaque réponse du modèle, avec l'identifiant de l'appel qui l'a produite
    exchanges: list[tuple[str, LLMResponse]] = field(default_factory=list)

    @property
    def call_ids(self) -> list[str]:
        """Les identifiants des appels de modèle, sans doublon, dans l'ordre (une
        boucle réutilise le même d'un tour à l'autre)."""
        return list(dict.fromkeys(cid for cid, _ in self.exchanges))


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
    clock: Callable[[], int] | None = None,
    result: LoopResult | None = None,
) -> LoopResult:
    """``clock`` date les appels d'outils (sans horloge : durées nulles) ;
    ``result``, s'il est donné, est rempli au fil de l'eau — ce qui a été fait
    reste lisible quand l'épisode est coupé en route (délai, supplantation)."""
    result = result if result is not None else LoopResult(text="")
    result.stop = "running"  # chaque sortie le fixe ; resté tel quel, la boucle a été coupée en route
    now = clock or _no_clock
    req = request
    counts: dict[str, int] = {}
    replayed = False
    for _turn in range(max_turns):
        resp = await gateway.call(req)
        result.responses += 1
        result.last = resp
        result.exchanges.append((req.call_id, resp))
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
                outputs.append(_refused(call, f"outil inconnu : {call.name}", result))
                continue
            limit = spec.max_calls_per_episode
            if limit is not None and counts.get(call.name, 0) >= limit:
                outputs.append(_refused(call, f"{call.name} : plafond d'appels atteint pour cet épisode", result))
                continue
            if RAW_ARGS_KEY in call.args:
                outputs.append(_refused(call, "arguments illisibles : ce n'était pas du JSON valide", result))
                continue
            try:
                args = spec.args.model_validate(dict(call.args))
            except ValidationError as exc:
                outputs.append(_refused(call, f"arguments illisibles : {exc.errors(include_url=False)}", result))
                continue
            counts[call.name] = counts.get(call.name, 0) + 1
            ctx = make_context(spec, call.id)
            if isinstance(ctx, ToolContext):
                ctx.calls = tuple(result.calls)
            t0 = now()
            out = await acall(spec.handler, args, ctx, label=f"outil {call.name}")
            elapsed = max(0, now() - t0)
            if isinstance(out, Failed):
                message = f"l'outil a échoué : {out.error!r}"
                result.calls.append((call.name, False))
                result.records.append(ToolRecord(call.id, call.name, _args_json(call.args), False,
                                                 _bounded(message), elapsed))
                outputs.append(Message("tool", message, tool_call_id=call.id, name=call.name, is_error=True))
                continue
            tr = out if isinstance(out, ToolResult) else ToolResult(content=_as_text(out))
            result.calls.append((call.name, tr.ok))
            result.records.append(ToolRecord(call.id, call.name, _args_json(call.args), tr.ok,
                                             _bounded(tr.content), elapsed))
            outputs.append(Message("tool", tr.content, tool_call_id=call.id, name=call.name, is_error=not tr.ok))
        req = req.extend(Message("assistant", resp.text, tool_calls=resp.tool_calls), *outputs)
    result.text = MAX_TURNS_MARKER
    result.stop = "max_turns"
    return result


def _refused(call: ToolCall, message: str, result: LoopResult) -> Message:
    """Un appel refusé avant son gestionnaire : l'erreur rendue au modèle, et sa trace."""
    result.records.append(ToolRecord(call.id, call.name, _args_json(call.args), False, _bounded(message),
                                     executed=False))
    return Message("tool", message, tool_call_id=call.id, name=call.name, is_error=True)


def _no_clock() -> int:
    return 0


def _bounded(text: str, limit: int = RECORD_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - len(RECORD_TRUNCATED)] + RECORD_TRUNCATED


def _args_json(args: Mapping[str, Any]) -> str:
    """Les arguments tels que le modèle les a écrits (clés triées), bornés."""
    try:
        raw = json.dumps(dict(args), ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        raw = repr(dict(args))
    return _bounded(raw)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)
