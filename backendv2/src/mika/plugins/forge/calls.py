"""Un appel d'outil d'app qui attendait un accord (ADR 0133) : ce qui est montré, ce qui part, ce qui revient, ce qui
expire — comme l'appel d'un service extérieur (``plugins/mcp/calls.py``).

- *Demander* (``ask``) : quand la ligne d'accès de son projet le veut — ``carte`` : une carte à la personne en face ;
  ``toi`` : ta carte quand c'est toi en face ; sans personne pour l'accepter, la console —, l'appel est proposé
  (``forge.call``) et rien ne part.
- *L'aperçu* montre exactement ce qui partirait — l'app, sa version, l'outil, les arguments — et l'empreinte de tout
  cela : c'est elle qu'on accepte. Une app changée, arrêtée ou cassée depuis la demande, une demande expirée, bloque.
- *La capacité* appelle et garde ce qu'il a rendu le temps qu'il soit journalisé (``ForgePort.keep``) ; *le retour*
  (``came_back``) l'écrit comme un contenu (``forge.answered``, l'oubli l'atteint) et vit ce que l'app a signalé ou
  émis ; la section et l'initiative due le disent à qui l'avait demandé.
- *L'expiration* : sans accord à temps (10 min dans le chat, un jour pour l'opérateur), refusée au nom du délai.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from mika.contracts import forge as c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.codec import canonical_json
from mika.kernel.events import Content
from mika.kernel.faculty import ToolResult, Zone
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, floor
from mika.kernel.operate import Preview
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.plugins.forge import (
    FORGE,
    App,
    AppCall,
    ForgeState,
    concerns,
    outcomes,
    params,
    timeout_of,
    trusted,
)
from mika.ports.preprocess import cite, inert
from mika.vocab.access import CARD, can_approve
from mika.vocab.episodes import CONVERSATIONAL, Kind, is_work_target
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

WAITING, APPROVED, REFUSED, EXPIRED, ANSWERED, FAILED = "attend", "acceptée", "refusée", "expirée", "rendue", "ratée"
FINAL = frozenset({REFUSED, EXPIRED, ANSWERED, FAILED})
#: une carte dans la conversation vaut tant ; un accord de l'opérateur, tant ; passé ce délai, l'issue ne se dit plus
CARD_TTL, OPERATOR_TTL, TOO_LATE = 10 * MINUTE, DAY, 6 * HOUR
#: ce qu'on garde des demandes, d'une réponse (le contenu journalisé), ce que la section en montre
CALLS_KEPT, ANSWER_KEPT, SHOWN_CHARS, SHOWN_MAX = 100, 8000, 2000, 4
#: qui signe un refus faute d'accord à temps
EXPIRER = "délai"
PROVENANCE = "forge-call:"
EVIDENCE = 12.0


def call_digest(args: Mapping[str, Any]) -> str:
    """L'empreinte de ce qui partirait : l'app, sa version, ce qu'elle appelle, ses arguments, qui décide."""
    pinned = {k: args.get(k) for k in ("app", "function", "args", "fingerprint", rt.DECIDER)}
    return hashlib.sha256(canonical_json(pinned).encode()).hexdigest()[:32]


async def ask(ctx: Any, app: App, name: str, tool: str, function: str, values: Mapping[str, Any],
              level: str) -> ToolResult:
    """Proposer l'appel (rien ne part) et le dire : la carte à la personne en face (``carte``), ou à sa propriétaire
    quand c'est elle en face (``toi``) ; sinon, l'opérateur décide."""
    ep, audience = ctx.frame.episode, ctx.frame.audience
    # au travail, la cible est un but ou un projet, pas une personne : l'opérateur décide
    target = (ep.target if ep is not None else None) or ""
    target = "" if is_work_target(target) else target
    in_chat = bool(target) and can_approve(audience) and (level == CARD or bool(audience.owner))
    payload: dict[str, Any] = {
        "app": name, "tool": tool, "function": function, "args": dict(values), "fingerprint": app.fingerprint,
        "request": f"{ctx.episode_id}:{ctx.call_key or ctx.call_id}", "target": target,
        "approval": "conversation" if in_chat else "operateur",
        rt.EXPIRES: ctx.frame.now + (CARD_TTL if in_chat else OPERATOR_TTL)}
    if in_chat:
        payload[rt.DECIDER] = target
    payload["_apercu"] = call_digest(payload)
    shown = inert(json.dumps(values, ensure_ascii=False, sort_keys=True), 300)
    await ctx.propose(rt.EFFECT_PROPOSED.draft(
        capability=c.CALL, owner=FORGE.name, args_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        summary=Content.of(phrase("forge.calls.summary", tool=inert(tool, 80), app=inert(app.title, 60),
                                  args=shown)[:400], level=int(Sensitivity.PERSONAL)),
        approval=True, context=f"forge:{name}", about=(target,) if target else ()))
    who = phrase("forge.calls.in_chat") if in_chat else phrase("forge.calls.operator")
    return ToolResult(content=phrase("forge.calls.asked", who=who))


def preview(args: Mapping[str, Any], ports: Mapping[str, Any]) -> Preview:
    """Exactement ce qui partirait, et ce qui l'empêcherait de partir tel quel."""
    name = str(args.get("app") or "")
    port, frame_of = ports.get("forge"), ports.get("frame")
    frame = frame_of() if frame_of is not None else None
    app = frame.state("forge").apps.get(name) if frame is not None else None
    shown = json.dumps(args.get("args") or {}, ensure_ascii=False, indent=1, sort_keys=True)
    text = phrase("forge.calls.preview", app=app.title if app is not None else name,
                  version=app.version if app is not None else "?", tool=str(args.get("tool") or ""), args=shown)
    info = port.info(name) if port is not None else None
    blocked = ""
    if app is None or info is None:
        blocked = phrase("forge.calls.gone")
    elif app.held or not app.enabled or app.broken:
        blocked = phrase("forge.calls.stopped")
    elif info.fingerprint != args.get("fingerprint"):
        blocked = phrase("forge.calls.changed")
    expires = int(args.get(rt.EXPIRES) or 0)
    if not blocked and expires and frame is not None and frame.now > expires:
        blocked = phrase("forge.calls.expired_block")
    return Preview(text, call_digest(args), blocked)


@FORGE.capability("call", description="Appeler un outil d'une app (après accord).", preview=preview)
async def call(args: Mapping[str, Any], context: str, ports: Mapping[str, Any]) -> tuple[bool, str]:
    port, frame_of = ports.get("forge"), ports.get("frame")
    name = str(args.get("app") or "")
    frame = frame_of() if frame_of is not None else None
    app = frame.state("forge").apps.get(name) if frame is not None else None
    info = port.info(name) if port is not None else None
    if frame is None or app is None or info is None or info.fingerprint != args.get("fingerprint") \
            or app.held or not app.enabled or app.broken:
        return False, "refusé : l'app a changé ou s'est arrêtée depuis l'accord"
    function = str(args.get("function") or "")
    r = await port.call(name, function, dict(args.get("args") or {}),
                        timeout_s=timeout_of(info, function, params(frame.env.params_of("forge", frame.root))),
                        secrets=trusted(app))
    port.keep(str(args.get("request") or ""), r)
    return r.ok, "rendu" if r.ok else "échec"


def came_back(ev: Any, s: ForgeState, frame: Frame, port: Any) -> list[Any] | None:
    """L'appel est fait (ou a échoué) : ce qu'il a rendu devient un contenu journalisé, pour qu'elle le dise ; ce que
    l'app a signalé ou émis en le faisant vit comme le reste de sa vie."""
    req = s.calls.get(ev.data.proposal)
    if req is None:
        return None
    try:
        request = str(json.loads(req.args_json).get("request") or "")
    except ValueError:
        request = ""
    r = port.take(request) if request else None
    app = s.apps.get(req.app)
    drafts: list[Any] = []
    if r is not None and app is not None:
        drafts += outcomes(req.app, app, [r], frame.now, params(frame.env.params_of("forge", frame.root)),
                           breaker=False, concern=concerns(frame, app))
    if r is None:
        text = phrase("forge.calls.lost") if ev.data.ok else ev.data.result
    else:
        text = json.dumps(r.value, ensure_ascii=False, default=str) if r.ok else r.error
    ok = ev.data.ok and (r is None or r.ok)
    return [*drafts, c.ANSWERED.draft(proposal=req.proposal, ok=ok,
                                      text=Content.of((text or "")[:ANSWER_KEPT], level=int(Sensitivity.PERSONAL)),
                                      about=(req.target,) if req.target else (),
                                      dedupe_key=f"forge-rendu:{req.proposal}")]


# ── Ce qu'elle en sait ────────────────────────────────────────────────────


def _kept(calls: FrozenDict[int, AppCall]) -> FrozenDict[int, AppCall]:
    while len(calls) > CALLS_KEPT:
        calls = calls.delete(min(calls))
    return calls


@FORGE.reducer(rt.EFFECT_PROPOSED)
def _call_proposed(s: ForgeState, e: Any, cx: Any) -> ForgeState:
    d = e.data
    if d.owner != FORGE.name or d.capability != c.CALL:
        return s
    try:
        args = json.loads(d.args_json or "{}")
    except ValueError:
        args = {}
    req = AppCall(proposal=e.seq, app=str(args.get("app") or ""), tool=str(args.get("tool") or ""),
                  target=str(args.get("target") or ""), approval=str(args.get("approval") or ""), at=e.at,
                  expires=int(args.get(rt.EXPIRES) or 0), args_json=d.args_json,
                  status=WAITING if d.approval else APPROVED)
    return replace(s, calls=_kept(s.calls.set(e.seq, req)))


@FORGE.reducer(rt.EFFECT_RESOLVED)
def _call_resolved(s: ForgeState, e: Any, cx: Any) -> ForgeState:
    d = e.data
    req = s.calls.get(d.proposal)
    if req is None:
        return s
    status = APPROVED if d.approved else (EXPIRED if d.by == EXPIRER else REFUSED)
    return replace(s, calls=s.calls.set(d.proposal, replace(req, status=status, by=d.by,
                                                            done_at=0 if d.approved else e.at)))


@FORGE.reducer(rt.EFFECT_EXECUTED)
def _call_executed(s: ForgeState, e: Any, cx: Any) -> ForgeState:
    req = s.calls.get(e.data.proposal)
    if req is None or e.data.ok:
        return s  # réussi : ``forge.answered`` suit, avec ce qu'il a rendu
    return replace(s, calls=s.calls.set(e.data.proposal, replace(req, status=FAILED, done_at=e.at)))


@FORGE.reducer(c.ANSWERED)
def _call_answered(s: ForgeState, e: Any, cx: Any) -> ForgeState:
    d = e.data
    req = s.calls.get(d.proposal)
    if req is None:
        return s
    return replace(s, calls=s.calls.set(d.proposal, replace(req, status=ANSWERED if d.ok else FAILED, done_at=e.at,
                                                            text_ref=d.text.ref or "")))


@FORGE.reducer(rt.UTTERANCE)
def _call_told(s: ForgeState, e: Any, cx: Any) -> ForgeState:
    """Ce que son prompt lui montrait d'une issue (``forge-call:<proposition>``) quand elle a parlé : c'est dit."""
    if not e.data.visible:
        return s
    calls = s.calls
    for p in e.data.provenance:
        n = p[len(PROVENANCE):] if p.startswith(PROVENANCE) else ""
        req = calls.get(int(n)) if n.isdigit() else None
        if req is not None and req.status in FINAL and not req.told:
            calls = calls.set(req.proposal, replace(req, told=True))
    return s if calls is s.calls else replace(s, calls=calls)


@FORGE.fact(c.UNTOLD)
def _untold(s: ForgeState, cx: Any, proposal: int) -> bool:
    req = s.calls.get(proposal)
    return req is not None and req.status in FINAL and not req.told


# ── Le dire ───────────────────────────────────────────────────────────────


def _relevant(s: ForgeState, frame: Frame) -> list[AppCall]:
    """Les appels demandés pour la personne en face : en attente, ou finis et pas encore dits."""
    ep = frame.episode
    if ep is None or not ep.target:
        return []
    person = frame.get(identity_c.PERSON(ep.target)) or ep.target
    handles = set(frame.get(identity_c.HANDLES(person)) or (ep.target,))
    out = [r for r in s.calls.values() if r.target in handles
           and (r.status == WAITING or (r.status in FINAL and not r.told and frame.now - r.done_at <= TOO_LATE))]
    return sorted(out, key=lambda r: r.proposal)[-SHOWN_MAX:]


@FORGE.enricher("calls", episodes=CONVERSATIONAL, deadline_ms=300)
async def _texts(s: ForgeState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    refs = [r.text_ref for r in _relevant(s, frame) if r.text_ref]
    return store.content(refs) if store is not None and refs else None


def line(r: AppCall, texts: Mapping[str, str]) -> str:
    what = phrase("forge.calls.what", tool=inert(r.tool, 80))
    if r.status == WAITING:
        who = phrase("forge.calls.by_chat") if r.approval == "conversation" else phrase("forge.calls.by_operator")
        return "- " + phrase("forge.calls.waiting", what=what, who=who)
    said = texts.get(r.text_ref, "")
    if r.status == ANSWERED:
        return ("- " + phrase("forge.calls.answered", what=what) + "\n"
                + (cite(said, SHOWN_CHARS) or phrase("forge.calls.nothing")) + "\n" + phrase("forge.calls.say_it"))
    if r.status == FAILED:
        why = phrase("forge.calls.why", said=inert(said, 300)) if said else ""
        return "- " + phrase("forge.calls.failed", what=what, why=why)
    if r.status == EXPIRED:
        return "- " + phrase("forge.calls.expired", what=what)
    return "- " + phrase("forge.calls.refused", what=what)


@FORGE.section("app_calls", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=20,
               title=phrase("forge.calls.title"), untrusted=True, reads=[identity_c.PERSON, identity_c.HANDLES])
def _section(s: ForgeState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    reqs = _relevant(s, frame)
    if not reqs:
        return None
    texts = enrich.get("calls") or {}
    told = tuple(f"{PROVENANCE}{r.proposal}" for r in reqs if r.status in FINAL)
    return SectionBody(phrase("forge.calls.head") + "\n" + "\n".join(line(r, texts) for r in reqs),
                       level=int(Sensitivity.PERSONAL), witness=True, provenance=told)


def _still_untold(proposal: int) -> Guard:
    """L'épisode ne vaut que tant que ce n'est pas dit (sa réponse l'a emporté : plus rien à faire)."""
    return Guard("issue d'un appel d'app", predicate=lambda view, n=proposal: view.get(c.UNTOLD(n)) is True)


def _address(frame: Frame, r: AppCall) -> str:
    """Où le dire : là où la personne est maintenant (connectée, sinon joignable), sinon d'où venait la demande."""
    person = frame.get(identity_c.PERSON(r.target)) or r.target
    handles = frame.get(identity_c.HANDLES(person)) or (r.target,)
    present = [h for h in frame.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    reachable = frame.get(identity_c.REACHABLE(person))
    return reachable[0] if reachable else r.target


def _brief(status: str, app: str) -> str:
    """La consigne de l'initiative qui dit une issue."""
    if status == ANSWERED:
        return phrase("forge.calls.brief.answered", app=app)
    if status == FAILED:
        return phrase("forge.calls.brief.failed", app=app)
    if status == EXPIRED:
        return phrase("forge.calls.brief.expired", app=app)
    return phrase("forge.calls.brief.refused", app=app)


@FORGE.propose(kinds=[Kind.INITIATIVE], reasons={c.ANSWERED_REASON: (0.0, 17.0)},
               reads=[c.UNTOLD, identity_c.PERSON, identity_c.HANDLES, identity_c.REACHABLE, presence_c.PRESENT])
def _owed(s: ForgeState, frame: Frame) -> list[Candidate]:
    """L'issue d'un appel sur accord, à dire à qui l'avait demandé (une initiative due, comme un service)."""
    out = []
    for r in sorted(s.calls.values(), key=lambda r: (r.done_at, r.proposal)):
        if r.status not in FINAL or r.told or not r.target or frame.now - r.done_at > TOO_LATE:
            continue
        address = _address(frame, r)
        app = s.apps.get(r.app)
        brief = _brief(r.status, f"« {inert(app.title if app is not None else r.app, 60)} »")
        out.append(Candidate(Kind.INITIATIVE, address, c.ANSWERED_REASON, EVIDENCE,
                             resources=frozenset({floor(address)}), guards=(_still_untold(r.proposal),),
                             args=FrozenDict({"brief:forge": brief, "subject": f"forge-call:{r.proposal}"})))
    return out


@FORGE.process("forge.calls_expire", wake_on=[rt.EFFECT_PROPOSED, rt.EFFECT_RESOLVED], lane="background",
               max_quantum_s=60, priority=60)
class Expire:
    """Une demande sans accord à temps est refusée au nom du délai (elle le saura comme un refus)."""

    def next_due(self, s: ForgeState, frame: Frame, last_run: int | None) -> int | None:
        waiting = [r.expires for r in s.calls.values() if r.status == WAITING and r.expires]
        return max(frame.now, min(waiting)) if waiting else None

    async def run(self, ctx: Any) -> None:
        now = ctx.frame.now
        for r in [r for r in ctx.state.calls.values() if r.status == WAITING and r.expires and r.expires <= now]:
            draft = rt.EFFECT_RESOLVED.draft(
                proposal=r.proposal, approved=False, by=EXPIRER, note=Content.of("pas d'accord dans le délai"),
                capability=c.CALL, owner=FORGE.name, args_json=r.args_json, context=f"forge:{r.app}",
                about=(r.target,) if r.target else (), dedupe_key=f"décision:{r.proposal}")
            pending = Guard("encore en attente", reads=(rt.PENDING_EFFECTS,),
                            predicate=lambda view, n=r.proposal: any(p.proposal == n
                                                                     for p in view.get(rt.PENDING_EFFECTS)))
            try:
                await ctx.emit(draft, guard=pending, emitter=rt.OWNER)
            except Exception:  # noqa: BLE001 — décidée entre-temps : rien à faire
                continue
