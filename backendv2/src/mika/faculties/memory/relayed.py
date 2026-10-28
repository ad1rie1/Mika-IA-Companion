"""Ce qu'on lui montre de son téléphone (ADR 0120) : la relecture des messages reçus ailleurs.

Un message reçu sur le téléphone de quelqu'un (la forme ``Relayed``, qu'apporte un plugin que la mémoire ne connaît
pas) attend que sa conversation se pose. Elle la relit alors comme une de ses conversations — la même consigne, le
même outil, ce que le code en garde jugé pareil (``consolidation.kept_from``) —, sous un en-tête qui dit ce que c'est :
une conversation entre d'autres, lue sur le téléphone de la personne qui l'a reçue, à laquelle elle n'a pas pris
part. Ce que la conversation de relecture en fait de différent tient à ``Conversation.relayed`` :

- la personne qui l'a reçue la lui montre : elle est parmi ceux qui l'ont confié (on lui redit ce qu'on lui a écrit) ;
- ni note sur elle, ni promesse, ni ce qui n'appartiendrait qu'à elle et quelqu'un ;
- de ce qu'elle sait déjà, seul l'anodin est montré (comme pour un salon : ``room`` est posé).

Au plus quelques conversations par passage ; un échec est repris plus tard, trois fois au plus, puis laissé.
"""

from __future__ import annotations

import json
import logging
from functools import partial
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import self_ as self_c
from mika.faculties.memory import extraction as x
from mika.faculties.memory.consolidation import extract_request, kept_from, people_directory, shown_of
from mika.faculties.memory.faculty import MEMORY, MemoryState, params
from mika.kernel.clock import MINUTE
from mika.kernel.events import Draft
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.ports.llm_budget import fit_by_halving
from mika.ports.preprocess import inert
from mika.vocab.people import clean_display_name
from mika.vocab.phrasebook import family, phrase

log = logging.getLogger(__name__)

#: une conversation relue d'un coup, au plus (la suite attend le passage d'après)
LINES_MAX = 60
#: une relecture qui échoue autant de fois est laissée
ATTEMPTS_MAX = 3
#: après un échec, pas de nouvel essai avant
RETRY_US = 10 * MINUTE
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


def conversation(frame: Frame, recipient: str, thread: str, messages: list[dict[str, Any]]) -> x.Conversation | None:
    """La conversation telle que la relecture la lit : la personne qui l'a reçue et ceux qui lui ont écrit, chacun
    avec son jeton, sous un en-tête qui dit d'où elle vient. ``None`` : plus rien à lire (tout oublié)."""
    owner = clean_display_name(frame.get(identity_c.IDENTITY(recipient)).name) or phrase("memory.relayed.someone")
    tokens: dict[str, x.Speaker] = {}
    lines: list[x.Line] = []
    for m in messages[:LINES_MAX]:
        if not m["text"]:
            continue  # oublié depuis
        person = recipient if m["own"] or not m["sender"] else m["sender"]
        if person not in tokens:
            name = owner if person == recipient else (
                clean_display_name(inert(m["name"] or "", NAME_MAX)) or phrase("memory.relayed.someone"))
            tokens[person] = x.Speaker(f"P{len(tokens) + 1}", person, name)
        lines.append(x.Line(int(m["seq"]), int(m["at"]), tokens[person].label, inert(m["text"], 3000), person))
    if not lines or not any(ln.person != recipient for ln in lines):
        return None  # rien qu'on lui ait écrit : seulement ses propres messages, ou tout est oublié
    apps = family("memory.relayed.apps")
    source = next((m["source"] for m in messages if m["source"]), "")
    title = next((m["title"] for m in messages if m["title"]), None)
    who = ", ".join(s.label for s in tokens.values())
    heading = phrase("memory.extraction.render.relayed", owner=owner, app=apps.get(source, apps["other"]), who=who)
    if title and any(m["group"] for m in messages):
        heading += " " + phrase("memory.extraction.render.relayed_group", title=inert(title, 80))
    return x.Conversation(f"relayed:{recipient}:{thread}", tuple(tokens.values()), tuple(lines),
                          room=f"relayed:{thread}", relayed=recipient, heading=heading)


@MEMORY.process("memory.relayed", wake_on=[c.RELAYED_READ], wake_on_shapes=[c.Relayed], lane="background",
                catch_up=CatchUp.ONCE, max_quantum_s=600)
class Relay:
    """Relire les conversations reçues ailleurs, une fois posées."""

    def __init__(self) -> None:
        self.retry_at = 0
        #: les relectures qui ont échoué, par conversation (son premier message)
        self.failures: dict[int, int] = {}

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        if not state.relayed:
            return None
        p = params(frame.env.params_of("memory", frame.root))
        due = min(state.relayed_at + p.relayed_quiet_us, state.relayed_since + p.relayed_wait_us)
        return max(frame.now, due, self.retry_at)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: MemoryState = ctx.state
        store, vectors = ctx.ports.get("store"), ctx.ports.get("vectors")
        if store is None or ctx.llm is None or not state.relayed or self.retry_at > frame.now:
            return
        p = params(frame.env.params_of("memory", frame.root))
        her = self_c.name_of(frame.get(self_c.PERSONA))
        groups = gather(store, state.relayed)
        known_seqs = {m["seq"] for found in groups.values() for m in found}
        # ce qui n'est plus lisible (un événement d'une autre forme, illisible) ne l'attend plus
        drafts: list[Draft[Any]] = []
        lost = tuple(q for q in state.relayed if q not in known_seqs)
        if lost:
            drafts.append(c.RELAYED_READ.draft(seqs=lost, dedupe_key=f"relu-perdu:{lost[0]}:{lost[-1]}"))
        directory = people_directory(frame, store) if groups else {}
        system = x.system(her, frame.get(self_c.PORTRAYED("compact"))) if groups else ""
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
            if got is None:
                tries = self.failures.get(seqs[0], 0) + 1
                self.failures[seqs[0]] = tries
                if tries < ATTEMPTS_MAX:
                    self.retry_at = frame.now + RETRY_US * 2 ** (tries - 1)
                    continue
                self.failures.pop(seqs[0], None)
                log.warning("relecture d'une conversation reçue ailleurs : laissée après %d échecs", tries)
                drafts.append(c.RELAYED_READ.draft(seqs=seqs, failed=True, dedupe_key=f"relu:{seqs[0]}:{seqs[-1]}"))
                continue
            kept, call_id, model = got
            self.failures.pop(seqs[0], None)
            drafts += kept
            drafts.append(c.RELAYED_READ.draft(seqs=seqs, produced=len(kept), call_id=call_id, model=model,
                                               dedupe_key=f"relu:{seqs[0]}:{seqs[-1]}"))
        if drafts:
            await ctx.emit(*drafts)

    @staticmethod
    async def _read(ctx: Any, frame: Frame, state: MemoryState, store: Any, vectors: Any,
                    directory: dict[str, tuple[str, ...]], conv: x.Conversation, her: str, system: str, p: Any,
                    n: int) -> tuple[list[Draft[Any]], str, str] | None:
        """Une conversation relue : ce que le code en garde, l'appel, le modèle ; ``None`` si l'appel a échoué."""
        people = x.People.of(conv.speakers, directory, her, scope=conv.key)
        shown = await shown_of(frame, store, state, vectors, conv, people, directory, p, promises=False)
        # ce qu'elle sait déjà est facultatif, les messages ne le sont pas
        request, times = fit_by_halving(ctx.llm, partial(extract_request, conv, frame, state, shown, system=system,
                                                         her=her, call_id=f"{ctx.run_id}#{n}", priority=3))
        try:
            response = await ctx.llm.call(request)
        except Exception as exc:  # noqa: BLE001 — une panne : la conversation attend le passage suivant
            log.warning("relecture d'une conversation reçue ailleurs : %s", type(exc).__name__)
            return None
        extraction = x.parse(response)
        if extraction is None:
            log.warning("relecture d'une conversation reçue ailleurs : réponse illisible")
            return None
        kept = await kept_from(extraction, frame, state, store, conv, people, shown.shrunk(times), vectors, p,
                               request.call_id)
        return kept, request.call_id, response.model


__all__ = ["Relay", "conversation", "gather"]
