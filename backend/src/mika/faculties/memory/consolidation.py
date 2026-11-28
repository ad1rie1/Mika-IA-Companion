"""La consolidation : ce qu'elle retient d'une conversation (``memory.consolidate``).

**Consolider.** Une fenêtre se relit quand elle est mûre (assez de messages
de personnes) ou calme (plus rien depuis quelques minutes) — jamais en
coupant une question de sa réponse : une question récente sans réponse est
gardée pour la fois suivante. La fenêtre se découpe en **conversations** —
un fil privé par personne, un salon d'un seul tenant — et le modèle (rôle
``extract``) relit chacune à part : ce qu'Alice dit en privé ne se mêle jamais
à ce que Bob dit ailleurs. Tout part en un seul ajout gardé par le point de contrôle. Les échecs sont inscrits dans
une file durable, sans retenir les conversations suivantes ; les reprises s'espacent et réduisent leurs lots.

Ce module porte le processus, sa fenêtre, et la mise en file des reprises (``deferral``) : la relecture des
conversations d'un téléphone (``relayed.py``) y met les siennes par la même fonction (ADR 0224). Le reste vit à côté, en
fonctions de module que lisent aussi la relecture de la nuit (``reread.py``) et celle d'un téléphone (ADR 0153) :

- ``shown.py`` : ce qu'on montre au modèle d'une conversation ;
- ``kept.py`` : ce que le code garde d'une relecture — les règles de ce qu'elle retient ;
- ``testimonies.py`` : retrouver une croyance et ses témoins.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from functools import partial
from typing import Any

from sqlalchemy import func, select

from mika.contracts import expression as expression_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import transcript as transcript_c
from mika.faculties.memory import extraction as x
from mika.faculties.memory import tables as tb
from mika.faculties.memory.conversation import Conversation, Line, Piece, Speaker
from mika.faculties.memory.faculty import MEMORY, MemoryState
from mika.faculties.memory.kept import kept_from
from mika.faculties.memory.params import MemoryParams, params
from mika.faculties.memory.shown import extract_request, shown_of
from mika.faculties.memory.speakers import People
from mika.faculties.memory.tables import batches
from mika.kernel.clock import DAY, MINUTE
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.prompt import PromptBudgetError
from mika.ports.llm_budget import fit_by_halving, fits_context
from mika.ports.shares import valid_id
from mika.vocab.affect import Declared
from mika.vocab.people import clean_display_name, fold, is_identifiable
from mika.vocab.words import WORD

log = logging.getLogger(__name__)


@MEMORY.process("memory.consolidate", wake_on=[rt.PERCEPTION_RECEIVED, rt.UTTERANCE, c.CONSOLIDATED,
                                               c.EXTRACTION_DEFERRED],
                catch_up=CatchUp.ONCE, max_quantum_s=600)
class Consolidate:
    def __init__(self) -> None:
        #: pas de nouveau passage avant : une panne passagère, ou une erreur hors des appels (aucune rafale)
        self.retry_at = 0
        #: rien de consolidable à ce ``seq`` (des questions attendent) : on attend un événement
        self.stuck_at: int | None = None
        #: la file de reprises telle que relue au dernier passage (``MemoryState.deferred_seq``) et sa prochaine
        #: reprise due (``None`` : rien en attente)
        self.queue_seq = 0
        self.next_job_at: int | None = None
        #: passages de suite interrompus par une panne passagère du fournisseur
        self.outages = 0
        #: ce qu'une conversation a déjà donné pendant un passage qu'une panne a interrompu : on ne repaie pas
        #: l'appel (clé : la conversation et ses messages)
        self.extracted: dict[tuple[str, tuple[int, ...]], tuple[x.Extraction, str, str, str]] = {}
        #: les salons où chaque adresse a été vue, et jusqu'où le fil en a été lu : chaque passage ne relit que la
        #: suite (ADR 0075 ; tout relire parcourait chaque message de salon depuis la genèse)
        self.seen_rooms: dict[str, set[str]] = {}
        self.rooms_read = 0

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        if self.retry_at > frame.now:
            return self.retry_at
        p = params(frame.env.params_of("memory", frame.root))
        due: list[int] = []
        # la plus ancienne question attend sa réponse : réveil par l'énoncé
        if state.pending and self.stuck_at != frame.seq and state.pending[0] not in set(frame.get(rt.AWAITING)):
            due.append(frame.now if len(state.pending) >= p.min_messages else state.last_message_at + p.quiet_us)
        if state.deferred_seq > self.queue_seq:
            due.append(frame.now)  # la file a changé (une reprise demandée, un passage différé) : la relire
        elif self.next_job_at is not None:
            due.append(max(frame.now, self.next_job_at))
        return min(due) if due else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: MemoryState = ctx.state
        store = ctx.ports.get("store")
        if store is None or ctx.llm is None:
            return
        p = params(frame.env.params_of("memory", frame.root))
        self.retry_at = frame.now + p.retry_us
        self.queue_seq = state.deferred_seq
        thread = transcript_c.thread_table()
        said = (thread.c.id, thread.c.at, thread.c.role, thread.c.person, thread.c.text, thread.c.reply_to,
                thread.c.room, thread.c.attachments)
        rows = store.query_mind(select(*said).where(thread.c.id > state.checkpoint).order_by(thread.c.id)
                                .limit(p.max_window)) if state.pending else []
        rows = window(rows, set(frame.get(rt.AWAITING)))
        self.stuck_at = None if rows else frame.seq
        directory = people_directory(frame, store)
        her = self_c.name_of(frame.get(self_c.PERSONA))
        tasks = [(conv, 0) for conv in _conversations(frame, rows, state, directory)]
        drafts: list[Draft[Any]] = []
        # Une reprise par passage : un document illisible ne monopolise pas la mémoire ; la suivante, si elle est
        # due, au passage d'après, aussitôt. Seulement les siennes : une conversation reçue ailleurs se reprend par
        # ``memory.relayed`` (ADR 0224), ses messages ne sont pas dans le fil.
        queue = tb.deferred()
        jobs = store.query_mind(select(queue.c.key, queue.c.messages, queue.c.attempts, queue.c.about, queue.c.aside)
                                .where(queue.c.source == c.FROM_THREAD, queue.c.status == c.RETRY_QUEUED,
                                       queue.c.retry_at <= frame.now)
                                .order_by(queue.c.retry_at, queue.c.key).limit(1))
        for key, messages, attempts, about, aside in jobs:
            ids = json.loads(messages)
            retry_rows = [r for chunk in batches(sorted(set(ids))) for r in store.query_mind(
                select(*said).where(thread.c.id.in_(chunk)).order_by(thread.c.id))]
            drafts.append(c.EXTRACTION_DEFERRED.draft(key=key, status=c.RETRY_RESOLVED, attempts=attempts,
                          about=tuple(json.loads(about)), detail=Content.of("reprise", level=3)))
            tasks.extend((conv, attempts) for conv in _conversations(frame, retry_rows, state, directory,
                                                                     aside=json.loads(aside)))
        tasks = [(_her_lines(store, conv), attempts) for conv, attempts in tasks]
        vectors = ctx.ports.get("vectors")
        rooms = self._rooms(frame, store) if tasks else {}
        failed = False
        model, last_call = "", f"{ctx.run_id}#0"
        system = x.system(her, frame.get(self_c.PORTRAYED("compact"))) if tasks else ""
        for n, (conv, attempts) in enumerate(tasks):
            people = People.of(conv.speakers, directory, her, scope=conv.key, near=_near(conv, rooms))
            labels = {speaker.person: speaker.label for speaker in conv.speakers}
            shown = await shown_of(frame, store, state, vectors, conv, people, directory, p)
            # Les souvenirs de contexte sont facultatifs, les messages sources ne le sont pas.
            # Une ancienne liste de situations ne doit pas rendre une paire courte illisible.
            request, times = fit_by_halving(ctx.llm, partial(extract_request, conv, frame, state, shown, system=system,
                                                             her=her, call_id=f"{ctx.run_id}#{n}", priority=2))
            shown = shown.shrunk(times)
            retry_size = max(2, p.max_window // (2 ** min(8, attempts // max(1, p.max_attempts))))
            if (not fits_context(ctx.llm, request) or len(conv.lines) > retry_size) and len(conv.lines) > 1:
                cuts = [i for i in range(1, len(conv.lines)) if conv.lines[i].person is not None
                        and conv.lines[i - 1].person is None]
                if cuts:
                    middle = min(cuts, key=lambda i: abs(i - len(conv.lines) // 2))
                    tasks.extend([(replace(conv, lines=conv.lines[:middle]), attempts),
                                  (replace(conv, lines=conv.lines[middle:]), attempts)])
                    continue
            extraction, raw, reason = None, "", c.INVALID_OUTPUT
            cached = self.extracted.get((conv.key, conv.seqs))
            if cached is not None:
                extraction, raw, model, last_call = cached
            else:
                try:
                    response = await ctx.llm.call(request)
                    model, last_call = response.model, request.call_id
                    raw = json.dumps([dict(call.args) for call in response.tool_calls], ensure_ascii=False) \
                        if response.tool_calls else response.text
                    extraction = x.parse(response)
                except PromptBudgetError:
                    reason = "PromptBudgetError"  # une paire trop longue : la relire ne la raccourcira pas
                except Exception as exc:  # noqa: BLE001 — une panne passagère : la fenêtre attend, bornée
                    reason = type(exc).__name__
                    if self.outages + 1 < p.max_attempts:
                        # Rien n'avance, rien n'est mis en file : quand le fournisseur revient, la fenêtre se relit
                        # d'un seul tenant ; ce qui a déjà réussi dans ce passage est gardé pour ne pas repayer.
                        self.outages += 1
                        self.retry_at = frame.now + p.retry_us * 2 ** (self.outages - 1)
                        log.warning("consolidation : %s, nouvel essai dans %s min", reason,
                                    (self.retry_at - frame.now) // MINUTE)
                        return
                    log.warning("consolidation %s : %s, passage mis en file de reprise", conv.seqs[0], reason)
                if extraction is not None:
                    self.extracted[(conv.key, conv.seqs)] = (extraction, raw, model, last_call)
            if extraction is None or extraction.issues:
                failed = True
                halfway = extraction is not None
                drafts.append(deferral(
                    frame, p, key=conv.seqs[0], source=c.FROM_THREAD, messages=conv.seqs,
                    aside=tuple(ln.seq for ln in conv.lines if ln.aside), about=tuple(labels), attempt=attempts + 1,
                    failure=c.INVALID_ITEMS if halfway else (c.INVALID_OUTPUT if reason == c.INVALID_OUTPUT else
                        c.BUDGET_EXCEEDED if reason == "PromptBudgetError" else c.PROVIDER_ERROR),
                    issues=extraction.issues if extraction is not None else [reason], output=raw))
            if extraction is not None:
                drafts += await kept_from(extraction, frame, state, store, conv, people, shown, vectors, p, last_call)
        if rows:
            drafts.append(c.CONSOLIDATED.draft(upto=rows[-1][0], produced=sum(
                d.type.name != c.EXTRACTION_DEFERRED.name for d in drafts), failed=failed,
                call_id=last_call, model=model))
        if drafts:
            await ctx.emit(*drafts, guard=Guard("point de contrôle", reads=(c.CHECKPOINT,)))
        self.extracted.clear()
        self.outages = 0
        self.retry_at = 0  # un passage mené à bout : le suivant dès qu'il y a de quoi
        queue = tb.deferred()
        due = store.query_mind(select(func.min(queue.c.retry_at)).where(queue.c.source == c.FROM_THREAD,
                                                                       queue.c.status == c.RETRY_QUEUED))
        self.next_job_at = int(due[0][0]) if due and due[0][0] is not None else None

    def _rooms(self, frame: Frame, store: Any) -> dict[str, set[str]]:
        """Les salons où elle a vu chaque personne : les adresses lues jusqu'ici, plus la suite du fil, rangées sous
        la personne qu'elles désignent maintenant (une adresse reliée depuis parle pour elle)."""
        resolve, _ = identity_c.resolvers(frame.get)
        thread = transcript_c.thread_table()
        for seq, handle, room in store.query_mind(
                select(thread.c.id, thread.c.person, thread.c.room)
                .where(thread.c.id > self.rooms_read, thread.c.room.is_not(None)).order_by(thread.c.id)):
            self.rooms_read = max(self.rooms_read, int(seq))
            if handle and is_identifiable(handle):
                self.seen_rooms.setdefault(str(handle), set()).add(str(room))
        out: dict[str, set[str]] = {}
        for handle, seen in self.seen_rooms.items():
            out.setdefault(resolve(handle), set()).update(seen)
        return out


# ── la file des reprises ──
def deferral(frame: Frame, p: MemoryParams, *, key: int, source: str, messages: tuple[int, ...],
             about: tuple[str, ...], attempt: int, failure: str, issues: Sequence[str], output: str,
             aside: tuple[int, ...] = ()) -> Draft[c.ExtractionDeferred]:
    """Une relecture dans la file des reprises (ADR 0224), d'où que viennent ses messages : de son fil (``source``
    « thread », la consolidation) ou reçus ailleurs (« relayed », ``relayed.py``). Une sortie partielle, ou trop longue
    pour le contexte, attend un opérateur ; le reste revient de lui-même, de plus en plus espacé (``retry_us`` doublé
    à chaque essai, au plus un jour).

    ``attempt`` : l'essai qui vient d'échouer ; ``failure`` : son code (``failure_code``) ; ``issues`` et ``output`` :
    ce qui n'allait pas et la réponse brute, le détail que la console relit. ``about`` : ses personnes, pour que l'oubli
    de l'une l'atteigne ; ``aside`` : parmi ses messages, ce qui ne lui était pas adressé (la reprise le relit pareil)."""
    review = failure in (c.INVALID_ITEMS, c.BUDGET_EXCEEDED)
    delay = min(DAY, p.retry_us * 2 ** min(attempt - 1, 16))
    return c.EXTRACTION_DEFERRED.draft(
        key=key, source=source, messages=messages, aside=aside, about=about, attempts=attempt,
        retry_at=0 if review else frame.now + delay, status=c.RETRY_REVIEW if review else c.RETRY_QUEUED,
        failure_code=failure,
        detail=Content.of(json.dumps({"issues": list(issues), "output": output}, ensure_ascii=False), level=3))


# ── qui est qui ──
def people_directory(frame: Frame, store: Any) -> dict[str, tuple[str, ...]]:
    """Toutes les personnes qu'elle connaît (celles à qui elle a parlé),
    par nom et par prénom repliés : un nom porté par une seule personne
    désigne cette personne, même quand elle n'est pas de la conversation."""
    resolve, _ = identity_c.resolvers(frame.get)
    found: dict[str, set[str]] = {}
    thread = transcript_c.thread_table()
    for (handle,) in store.query_mind(select(thread.c.person).distinct().order_by(thread.c.person)):
        if not handle or not is_identifiable(handle):
            continue
        name = clean_display_name(frame.get(identity_c.IDENTITY(handle)).name)
        folded = " ".join(fold(name).split())
        if not folded:
            continue
        key = resolve(handle)
        for k in {folded, folded.split()[0]}:
            found.setdefault(k, set()).add(key)
    return {k: tuple(sorted(v)) for k, v in found.items()}


def _her_lines(store: Any, conv: Conversation) -> Conversation:
    """Ce que ses répliques disent d'elles-mêmes, lu dans leurs annotations :

    - celles qu'elle a marquées mensonge (``LIE_ANNOTATION``) : la relecture le sait, et n'en tire rien comme
      vrai — ni une croyance, ni une note sur elle (« je ne sais rien de ses projets », redit, ne doit pas devenir
      ce qu'elle croit) ;
    - celles qui racontaient sans nom ce qu'elle sait de quelqu'un (``veiled:…`` dans leur provenance, ADR 0091) :
      la relecture n'en voit pas le texte — rien à en retenir sur qui l'écoutait ;
    - ce qu'elle a déclaré ressentir en écrivant chacune (sa balise, ``EMOTION_ANNOTATION``) : la relecture en
      part pour juger ce qu'elle-même ressent de ce qui s'est dit, au lieu de le juger à neuf (ADR 0107)."""
    mine = [ln.seq for ln in conv.lines if ln.person is None]
    if not mine:
        return conv
    said = {e.seq: json.loads(e.data) for e in store.get_events(mine) if e.type == rt.UTTERANCE.name}

    def note(d: Mapping[str, Any], key: str) -> str | None:
        return next((str(v) for k, v in d.get("annotations") or () if k == key), None)

    lied = {seq for seq, d in said.items() if note(d, expression_c.LIE_ANNOTATION) is not None}
    # ce qu'elle a raconté sans nommer personne (ADR 0091) : la relecture n'en voit pas le texte
    veiled = {seq for seq, d in said.items()
              if any(str(x).startswith(c.VEILED_PROVENANCE) for x in d.get("provenance") or ())}
    felt = {seq: declared.all for seq, d in said.items()
            if (declared := Declared.decode(note(d, expression_c.EMOTION_ANNOTATION))) is not None}
    # ce qu'elle a lu à un service pour l'écrire (ADR 0128) : ce qu'il vaut s'étend à la demande qu'elle suivait
    unkept: set[int] = set()
    floors: dict[int, int] = {}
    for seq, d in said.items():
        floor = int(d.get("floor") or 0)
        if not d.get("unkept") and not floor:
            continue
        for s in (seq, *(d.get("answers") or ()), d.get("reply_to")):
            if not s:
                continue
            if d.get("unkept"):
                unkept.add(int(s))
            floors[int(s)] = max(floors.get(int(s), 0), floor)
    if not lied and not veiled and not felt and not unkept and not floors:
        return conv
    return replace(conv, lines=tuple(
        replace(ln, lie=ln.seq in lied, veiled=ln.seq in veiled, felt=felt.get(ln.seq, ()),
                unkept=ln.seq in unkept, floor=floors.get(ln.seq, 0))
        if ln.person is None and ln.seq in said
        else replace(ln, unkept=ln.seq in unkept, floor=floors.get(ln.seq, 0))
        if ln.seq in unkept or ln.seq in floors else ln for ln in conv.lines))


def _near(conv: Conversation, rooms: Mapping[str, set[str]]) -> tuple[str, ...]:
    """Celles qu'elle a vues dans un salon avec quelqu'un de cette conversation : quand on y dit « Inès », c'est
    l'Inès qu'ils connaissent tous deux, pas une autre qu'elle connaîtrait seule de son côté."""
    shared = set().union(*(rooms.get(sp.person, set()) for sp in conv.speakers))
    return tuple(sorted(person for person, seen in rooms.items() if seen & shared))


def _conversations(frame: Frame, rows: list[tuple[Any, ...]], state: MemoryState,
                   directory: dict[str, tuple[str, ...]], aside: Sequence[int] = ()) -> list[Conversation]:
    """Un fil privé par personne (toutes ses adresses), un salon d'un
    seul tenant. Dans un salon, ce qui ne lui était pas adressé ne compte
    que s'il nomme quelqu'un qu'elle connaît. ``aside`` : ce qu'une reprise
    sait ne pas lui avoir été adressé (la tranche l'a oublié depuis)."""
    resolve, _ = identity_c.resolvers(frame.get)
    aside = {*state.unaddressed, *aside}
    her = self_c.name_of(frame.get(self_c.PERSONA))
    known_names = {k for k in directory if " " not in k and len(k) >= 3}
    person_of: dict[str, str] = {}
    name_of: dict[str, str] = {}
    groups: dict[str, list[tuple[Any, ...]]] = {}
    for row in rows:
        _seq, _at, _role, handle, _text, _reply, room = row[:7]
        if not handle:
            continue
        if handle not in person_of:
            person_of[handle] = resolve(handle)
            name_of[handle] = clean_display_name(frame.get(identity_c.IDENTITY(handle)).name) or handle
        key = f"room:{room}" if room else f"private:{person_of[handle]}"
        groups.setdefault(key, []).append(row)
    out: list[Conversation] = []
    for key, grows in sorted(groups.items(), key=lambda kv: kv[1][0][0]):
        room = grows[0][6]
        tokens: dict[str, Speaker] = {}
        lines: list[Line] = []
        for r in grows:
            seq, at, role, handle, text, _reply, _room = r[:7]
            person = person_of[handle]
            if person not in tokens:
                tokens[person] = Speaker(f"P{len(tokens) + 1}", person, name_of[handle])
            if role == "assistant":
                lines.append(Line(int(seq), int(at), her, text))
                continue
            side = bool(room) and int(seq) in aside
            if side and not set(WORD.findall(fold(text))) & known_names:
                continue  # on parle entre soi, de rien ni de personne qu'elle connaisse
            lines.append(Line(int(seq), int(at), tokens[person].label, text, person, side,
                              pieces=_pieces(int(seq), r[7] if len(r) > 7 else None)))
        if not any(ln.person for ln in lines):
            continue  # personne ne lui a rien dit : rien à apprendre
        out.append(Conversation(key, tuple(tokens.values()), tuple(lines), room or None))
    return out


def _pieces(seq: int, raw: Any) -> tuple[Piece, ...]:
    """Les pièces jointes gardées d'un message (la colonne ``attachments`` du fil, ``AttachmentMeta``) : leur place
    dans le message fait leur repère (« #12.1 »), comme pour la faculté qui les garde (ADR 0106)."""
    try:
        items = json.loads(raw) if isinstance(raw, str) and raw else []
    except ValueError:
        return ()
    if not isinstance(items, list):
        return ()
    return tuple(Piece(f"#{seq}.{i}", str(a.get("name") or ""), str(a.get("kind") or ""), str(a["file"]))
                 for i, a in enumerate(items, 1) if isinstance(a, dict) and isinstance(a.get("file"), str)
                 and valid_id(a["file"]))


def window(rows: list[tuple[Any, ...]], awaiting: set[int]) -> list[tuple[Any, ...]]:
    """La plus longue fenêtre qui ne coupe aucune paire : une question n'y
    entre qu'avec sa réponse, et jamais une question qui attend encore la
    sienne. ``rows`` : ``(id, at, role, person, text, reply_to, …)`` triés."""
    answers = {r[5]: r[0] for r in rows if r[2] == "assistant" and r[5] is not None}
    upto = rows[-1][0] if rows else 0
    changed = True
    while changed:
        changed = False
        for seq, _at, role, *_ in rows:
            if seq > upto or role != "user":
                continue
            answer = answers.get(seq)
            if seq in awaiting or (answer is not None and answer > upto):
                upto = seq - 1
                changed = True
                break
    return [r for r in rows if r[0] <= upto]
