"""Ce qu'on lui montre de son téléphone (ADR 0120) : la relecture des messages reçus ailleurs.

Un message reçu sur le téléphone de quelqu'un (la forme ``Relayed``, qu'apporte un plugin que la mémoire ne connaît
pas) attend que sa conversation se pose. Elle la relit alors comme une de ses conversations — la même consigne, le
même outil, ce que le code en garde jugé pareil (``kept.kept_from``) —, sous un en-tête qui dit ce que c'est :
une conversation entre d'autres, lue sur le téléphone de la personne qui l'a reçue, à laquelle elle n'a pas pris
part. Ce que la conversation de relecture en fait de différent tient à ``Conversation.relayed`` :

- la personne qui l'a reçue la lui montre : elle est parmi ceux qui l'ont confié (on lui redit ce qu'on lui a écrit) ;
- ni note sur elle, ni promesse, ni ce qui n'appartiendrait qu'à elle et quelqu'un ;
- de ce qu'elle sait déjà, seul l'anodin est montré (comme pour un salon : ``room`` est posé).

Au plus quelques conversations par passage. Une panne du fournisseur est retentée plus tard, au même délai et autant
de fois que pour ses conversations (les réglages « Délai avant de réessayer » et « Essais avant de réduire les lots »,
``retry_us`` et ``max_attempts``) ; si elle dure, si la réponse est illisible, ou si une partie de ce qu'elle en tire
est invalide (ce qui est valide est gardé), la conversation va dans la file durable des reprises, comme une des siennes
(``consolidation.deferral`` : ``memory.extraction_deferred``, ``source`` « relayed », ADR 0224) : visible et
reprenable dans Mémoire › Consolidation, reprise ici — une par passage, de plus en plus espacée —, et ses messages ne
l'attendent plus (``memory.relayed_read``). Une conversation reçue ailleurs garde la taille de son lot
(``LINES_MAX``) : ses reprises ne la réduisent pas.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import partial
from typing import Any

from sqlalchemy import func, select

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import self_ as self_c
from mika.faculties.memory import extraction as x
from mika.faculties.memory import tables as tb
from mika.faculties.memory.consolidation import deferral, people_directory
from mika.faculties.memory.conversation import Conversation, Line, Speaker
from mika.faculties.memory.faculty import MEMORY, MemoryParams, MemoryState, params
from mika.faculties.memory.kept import kept_from
from mika.faculties.memory.shown import extract_request, shown_of
from mika.faculties.memory.speakers import People
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.prompt import PromptBudgetError
from mika.ports.llm_budget import fit_by_halving
from mika.ports.preprocess import inert
from mika.vocab.people import clean_display_name
from mika.vocab.phrasebook import family, phrase

log = logging.getLogger(__name__)

#: une conversation relue d'un coup, au plus (la suite attend le passage d'après)
LINES_MAX = 60
NAME_MAX = 60


def _ref(data: dict[str, Any], name: str) -> str:
    found = data.get(name)
    return str(found.get("ref") or "") if isinstance(found, dict) else ""


def gather(store: Any, seqs: tuple[int, ...]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Les messages en attente, par conversation (la personne qui les a reçus, la conversation), dans l'ordre où ils
    ont été écrits ; chacun avec ses textes (``None`` une fois oubliés)."""
    events = store.get_events(list(seqs))
    rows = []
    for ev in events:
        try:
            data = json.loads(ev.data)
        except ValueError:
            continue
        if not isinstance(data, dict) or not data.get("recipient") or not data.get("thread"):
            continue
        rows.append((ev, data))
    refs = [r for _, d in rows for r in (_ref(d, "text"), _ref(d, "sender_name"), _ref(d, "title")) if r]
    texts = store.content(refs) if refs else {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for ev, d in rows:
        groups.setdefault((str(d["recipient"]), str(d["thread"])), []).append({
            "seq": ev.seq, "at": int(d.get("sent_at") or 0) or ev.at, "source": str(d.get("source") or ""),
            "sender": str(d.get("sender") or ""), "own": bool(d.get("own")), "group": bool(d.get("group")),
            "text": texts.get(_ref(d, "text")), "name": texts.get(_ref(d, "sender_name")),
            "title": texts.get(_ref(d, "title"))})
    for found in groups.values():
        found.sort(key=lambda m: (m["at"], m["seq"]))
    return groups


def conversation(frame: Frame, recipient: str, thread: str, messages: list[dict[str, Any]]) -> Conversation | None:
    """La conversation telle que la relecture la lit : la personne qui l'a reçue et ceux qui lui ont écrit, chacun
    avec son jeton, sous un en-tête qui dit d'où elle vient. ``None`` : plus rien à lire (tout oublié)."""
    owner = clean_display_name(frame.get(identity_c.IDENTITY(recipient)).name) or phrase("memory.relayed.someone")
    tokens: dict[str, Speaker] = {}
    lines: list[Line] = []
    for m in messages[:LINES_MAX]:
        if not m["text"]:
            continue  # oublié depuis
        person = recipient if m["own"] or not m["sender"] else m["sender"]
        if person not in tokens:
            name = owner if person == recipient else (
                clean_display_name(inert(m["name"] or "", NAME_MAX)) or phrase("memory.relayed.someone"))
            tokens[person] = Speaker(f"P{len(tokens) + 1}", person, name)
        lines.append(Line(int(m["seq"]), int(m["at"]), tokens[person].label, inert(m["text"], 3000), person))
    if not lines or not any(ln.person != recipient for ln in lines):
        return None  # rien qu'on lui ait écrit : seulement ses propres messages, ou tout est oublié
    apps = family("memory.relayed.apps")
    source = next((m["source"] for m in messages if m["source"]), "")
    title = next((m["title"] for m in messages if m["title"]), None)
    who = ", ".join(s.label for s in tokens.values())
    heading = phrase("memory.extraction.render.relayed", owner=owner, app=apps.get(source, apps["other"]), who=who)
    if title and any(m["group"] for m in messages):
        heading += " " + phrase("memory.extraction.render.relayed_group", title=inert(title, 80))
    return Conversation(f"relayed:{recipient}:{thread}", tuple(tokens.values()), tuple(lines),
                        room=f"relayed:{thread}", relayed=recipient, heading=heading)


@dataclass(frozen=True, slots=True)
class RelayedReading:
    """Une relecture : ce que le code en garde, l'appel, le modèle. ``failure`` : pourquoi elle va dans la file des
    reprises (le ``failure_code`` de ``ExtractionDeferred`` ; vide, elle est menée à bout) ; ``issues`` et ``output``,
    ce qui n'allait pas et la réponse brute, son détail (le format de la consolidation, que la console lit)."""

    kept: tuple[Draft[Any], ...] = ()
    call_id: str = ""
    model: str = ""
    failure: str = ""
    issues: tuple[str, ...] = ()
    output: str = ""


def _queued(conv: Conversation, seqs: tuple[int, ...], attempt: int, got: RelayedReading, frame: Frame,
            p: MemoryParams) -> Draft[c.ExtractionDeferred]:
    """La conversation dans la file des reprises, comme une des siennes (``consolidation.deferral``, ADR 0224) : ses
    messages sont le lot entier, ce qui en est oublié compris ; ses personnes (la personne qui l'a reçue, les clés
    ``phone:`` des expéditeurs) font que l'oubli l'atteint."""
    return deferral(frame, p, key=seqs[0], source=c.FROM_RELAYED, messages=seqs,
                    about=tuple(sorted({*conv.persons, *([conv.relayed] if conv.relayed else [])})), attempt=attempt,
                    failure=got.failure, issues=got.issues, output=got.output)


@MEMORY.process("memory.relayed", wake_on=[c.RELAYED_READ, c.EXTRACTION_DEFERRED], wake_on_shapes=[c.Relayed],
                catch_up=CatchUp.ONCE, max_quantum_s=600)
class Relay:
    """Relire les conversations reçues ailleurs, une fois posées ; reprendre celles de la file des reprises."""

    def __init__(self) -> None:
        self.retry_at = 0
        #: les pannes de suite du fournisseur, par conversation (son premier message)
        self.failures: dict[int, int] = {}
        #: la file de reprises telle que relue au dernier passage (``MemoryState.deferred_seq``) et la prochaine de
        #: ses reprises due (``None`` : rien en attente)
        self.queue_seq = 0
        self.next_job_at: int | None = None

    def _settled(self, state: MemoryState, frame: Frame) -> int | None:
        """Quand les messages en attente se relisent : leur conversation posée, et pas avant le nouvel essai après
        une panne (``None`` : rien n'attend)."""
        if not state.relayed:
            return None
        p = params(frame.env.params_of("memory", frame.root))
        due = min(state.relayed_at + p.relayed_quiet_us, state.relayed_since + p.relayed_wait_us)
        return max(due, self.retry_at)

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        due: list[int] = []
        settled = self._settled(state, frame)
        if settled is not None:
            due.append(max(frame.now, settled))
        if state.deferred_seq > self.queue_seq:
            due.append(frame.now)  # la file a changé (une reprise demandée, une conversation mise en file) : la relire
        elif self.next_job_at is not None:
            due.append(max(frame.now, self.next_job_at))
        return min(due) if due else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: MemoryState = ctx.state
        store, vectors = ctx.ports.get("store"), ctx.ports.get("vectors")
        if store is None or ctx.llm is None:
            return
        self.queue_seq = state.deferred_seq
        p = params(frame.env.params_of("memory", frame.root))
        settled = self._settled(state, frame)
        fresh = settled is not None and settled <= frame.now
        # Une reprise par passage, comme la consolidation : seulement les siennes (ses messages sont au journal, pas
        # dans le fil).
        queue = tb.deferred()
        jobs = store.query_mind(select(queue.c.key, queue.c.messages, queue.c.attempts, queue.c.about)
                                .where(queue.c.source == c.FROM_RELAYED, queue.c.status == c.RETRY_QUEUED,
                                       queue.c.retry_at <= frame.now)
                                .order_by(queue.c.retry_at, queue.c.key).limit(1))
        if not fresh and not jobs:
            self._next_job(store)
            return
        her = self_c.name_of(frame.get(self_c.PERSONA))
        groups = gather(store, state.relayed) if fresh else {}
        drafts: list[Draft[Any]] = []
        if fresh:
            # ce qui n'est plus lisible (un événement d'une autre forme, illisible) ne l'attend plus
            known_seqs = {m["seq"] for found in groups.values() for m in found}
            lost = tuple(q for q in state.relayed if q not in known_seqs)
            if lost:
                drafts.append(c.RELAYED_READ.draft(seqs=lost, dedupe_key=f"relu-perdu:{lost[0]}:{lost[-1]}"))
        directory = people_directory(frame, store) if groups or jobs else {}
        system = x.system(her, frame.get(self_c.PORTRAYED("compact"))) if groups or jobs else ""
        n = 0
        for n, ((recipient, thread), messages) in enumerate(sorted(groups.items(), key=lambda kv: kv[1][0]["at"])):
            if n >= p.relayed_per_run:
                break
            batch = messages[:LINES_MAX]
            seqs = tuple(int(m["seq"]) for m in batch)
            conv = conversation(frame, recipient, thread, batch)
            if conv is None:
                drafts.append(c.RELAYED_READ.draft(seqs=seqs, dedupe_key=f"relu:{seqs[0]}:{seqs[-1]}"))
                continue
            got = await self._read(ctx, frame, state, store, vectors, directory, conv, her, system, p, n)
            if got.failure == c.PROVIDER_ERROR:
                # retentée au délai et autant de fois que ses conversations (``retry_us``, ``max_attempts``) ; le
                # compte est celui du processus
                tries = self.failures.get(seqs[0], 0) + 1
                self.failures[seqs[0]] = tries
                if tries < p.max_attempts:
                    self.retry_at = frame.now + p.retry_us * 2 ** (tries - 1)
                    continue
                log.warning("relecture d'une conversation reçue ailleurs : %d pannes, mise en file de reprise", tries)
            self.failures.pop(seqs[0], None)
            drafts += got.kept
            if got.failure:
                # la file porte désormais ses messages : ils ne l'attendent plus
                drafts.append(_queued(conv, seqs, 1, got, frame, p))
            failed = bool(got.failure) and not got.kept  # rien n'en est gardé : tout attend la reprise
            drafts.append(c.RELAYED_READ.draft(seqs=seqs, produced=len(got.kept), failed=failed, call_id=got.call_id,
                                               model=got.model, dedupe_key=f"relu:{seqs[0]}:{seqs[-1]}"))
        for key, messages, attempts, about in jobs:
            drafts.append(c.EXTRACTION_DEFERRED.draft(key=key, source=c.FROM_RELAYED, status=c.RETRY_RESOLVED,
                                                      attempts=attempts, about=tuple(json.loads(about)),
                                                      detail=Content.of("reprise", level=3)))
            # une entrée tient une conversation (un lot) ; relue, elle est faite, ou elle revient avec un essai de plus
            for (recipient, thread), found in sorted(gather(store, tuple(json.loads(messages))).items(),
                                                     key=lambda kv: kv[1][0]["at"]):
                seqs = tuple(int(m["seq"]) for m in found[:LINES_MAX])
                conv = conversation(frame, recipient, thread, found[:LINES_MAX])
                if conv is None:
                    continue  # tout oublié depuis, ou plus rien qu'on lui ait écrit : il n'y a plus rien à relire
                n += 1
                got = await self._read(ctx, frame, state, store, vectors, directory, conv, her, system, p, n)
                drafts += got.kept
                if got.failure:
                    drafts.append(_queued(conv, seqs, attempts + 1, got, frame, p))
        if drafts:
            await ctx.emit(*drafts)
        self._next_job(store)

    def _next_job(self, store: Any) -> None:
        queue = tb.deferred()
        due = store.query_mind(select(func.min(queue.c.retry_at)).where(queue.c.source == c.FROM_RELAYED,
                                                                       queue.c.status == c.RETRY_QUEUED))
        self.next_job_at = int(due[0][0]) if due and due[0][0] is not None else None

    @staticmethod
    async def _read(ctx: Any, frame: Frame, state: MemoryState, store: Any, vectors: Any,
                    directory: dict[str, tuple[str, ...]], conv: Conversation, her: str, system: str, p: Any,
                    n: int) -> RelayedReading:
        """Une conversation relue : ce que le code en garde, l'appel, le modèle, et ce qui l'envoie dans la file des
        reprises — une panne, une réponse illisible, trop longue pour le contexte, une sortie en partie invalide
        (ce qui en est valide est gardé)."""
        people = People.of(conv.speakers, directory, her, scope=conv.key)
        shown = await shown_of(frame, store, state, vectors, conv, people, directory, p, promises=False)
        # ce qu'elle sait déjà est facultatif, les messages ne le sont pas
        request, times = fit_by_halving(ctx.llm, partial(extract_request, conv, frame, state, shown, system=system,
                                                         her=her, call_id=f"{ctx.run_id}#{n}", priority=3))
        try:
            response = await ctx.llm.call(request)
        except PromptBudgetError:
            log.warning("relecture d'une conversation reçue ailleurs : trop longue pour le contexte")
            return RelayedReading(failure=c.BUDGET_EXCEEDED, issues=("PromptBudgetError",))
        except Exception as exc:  # noqa: BLE001 — une panne : retentée, puis mise en file de reprise
            log.warning("relecture d'une conversation reçue ailleurs : %s", type(exc).__name__)
            return RelayedReading(failure=c.PROVIDER_ERROR, issues=(type(exc).__name__,))
        raw = json.dumps([dict(call.args) for call in response.tool_calls], ensure_ascii=False) \
            if response.tool_calls else response.text
        extraction = x.parse(response)
        if extraction is None:
            log.warning("relecture d'une conversation reçue ailleurs : réponse illisible")
            return RelayedReading(call_id=request.call_id, model=response.model, failure=c.INVALID_OUTPUT,
                           issues=(c.INVALID_OUTPUT,), output=raw)
        kept = await kept_from(extraction, frame, state, store, conv, people, shown.shrunk(times), vectors, p,
                               request.call_id)
        if extraction.issues:
            # leur nombre seulement : leurs textes sont dans le détail de l'entrée, qui s'oublie
            log.warning("relecture d'une conversation reçue ailleurs : %d éléments invalides écartés",
                        len(extraction.issues))
            return RelayedReading(tuple(kept), request.call_id, response.model, c.INVALID_ITEMS, tuple(extraction.issues),
                           raw)
        return RelayedReading(tuple(kept), request.call_id, response.model)


__all__ = ["RelayedReading", "Relay", "conversation", "gather"]
