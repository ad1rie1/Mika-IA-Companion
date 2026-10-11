"""Les processus de la mémoire.

**Consolider.** Une fenêtre se relit quand elle est mûre (assez de messages
de personnes) ou calme (plus rien depuis quelques minutes) — jamais en
coupant une question de sa réponse : une question récente sans réponse est
gardée pour la fois suivante. La fenêtre se découpe en **conversations** —
un fil privé par personne, un salon d'un seul tenant — et le modèle (rôle
``extract``) relit chacune à part : ce qu'Alice dit en privé ne se mêle jamais
à ce que Bob dit ailleurs. De chaque élément on sait qui il concerne, **qui
l'a confié** (les auteurs des messages d'où il vient) et **qui l'a entendu**
(les personnes de la conversation) ; ce qu'on a demandé de taire est un
secret. Les mêmes mots, avec les mêmes personnes et permissions, **renforcent**
le souvenir existant. Deux informateurs gardent deux témoignages distincts. Une réplique
recopiée n'est pas un souvenir (la sienne jamais ; celle de la personne, citée
en disant qui parle), une banalité ne se garde pas, et comment la personne
l'appelle se retient même quand le modèle l'oublie (ADR 0055). La relecture
voit les situations en cours de ses personnes, avec leur numéro : une situation
que la personne dit finie (« on a fini le déménagement ») prend fin. Tout part en un
seul ajout gardé par le point de contrôle. Les échecs sont inscrits dans une file durable,
sans retenir les conversations suivantes ; les reprises s'espacent et réduisent leurs lots.

**Indexer.** L'index des vecteurs est un cache : ce processus y ajoute ce
qui manque (éléments retenus, extraits d'échanges) et retire ce qui a
disparu (l'oubli efface des lignes).

**Laisser filer.** Une promesse que rien n'a réglée bien après son échéance
s'abandonne : rien ne reste dû pour toujours.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, time
from typing import Any

from mika.contracts import expression as expression_c
from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import transcript as transcript_c
from mika.faculties.memory import extraction as x
from mika.faculties.memory import likelihood as lk
from mika.faculties.memory.archive import for_people
from mika.faculties.memory.faculty import MEMORY, MemoryParams, MemoryState, day_of, occurrence, over, params
from mika.faculties.memory.knowledge import CONTEST, SUPERSEDE, Testimony, judge
from mika.faculties.memory.life import kept_too_early, same_task
from mika.faculties.memory.projections import (
    DEFERRED_TABLE,
    ITEM_COLUMNS,
    TESTIMONIES_TABLE,
    TESTIMONY_COLUMNS,
    fingerprint,
    testimony_of,
)
from mika.kernel.clock import DAY, MINUTE, instant
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.prompt import PromptBudgetError
from mika.ports.llm import LLMRequest, Message
from mika.ports.llm_budget import fits_context
from mika.ports.vectors import VectorItem
from mika.vocab import timespan
from mika.vocab.affect import Emotion, dominant, facets, facets_valence
from mika.vocab.people import clean_display_name, fold, is_identifiable
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import WORD, banal, same_words, stems

log = logging.getLogger(__name__)

BATCH = 64
#: les croyances déjà connues montrées au modèle, au plus
KNOWN_SHOWN = 8
#: après un échec de l'indexation (un plongement absent), pas de nouvel essai avant
INDEX_RETRY_US = 5 * MINUTE


def _rows(store: Any, sql: str, params_: tuple[Any, ...], columns: tuple[str, ...]) -> list[dict[str, Any]]:
    return [dict(zip(columns, r, strict=True)) for r in store.query_mind(sql, params_)]


def kept_secrets(store: Any, persons: Sequence[str]) -> list[str]:
    """Les secrets qu'elle garde déjà sur ces personnes : ce qui les concerne, ou ce qu'elles lui ont confié."""
    out: list[str] = []
    for person in persons:
        like = f'%"{person}"%'
        out += [str(t) for (t,) in store.query_mind(
            f"SELECT text FROM {c.ITEMS_TABLE} WHERE secret=1 AND status='active' AND (id IN (SELECT item FROM "
            f"{c.ABOUT_TABLE} WHERE person=?) OR told_by LIKE ?) ORDER BY id DESC LIMIT 50", (person, like))]
    return out


def resolution(ev: c.LifeEvent, outcome: str, by: str, sources: Sequence[int], call_id: str) -> Draft[Any]:
    """Comment ce moment a tourné, avec ce qu'elle en attendait et de qui elle en apprend (ADR 0086) — une seule
    façon, pour la consolidation et la relecture de la nuit."""
    return c.RESOLVED.draft(
        event=ev.id, thread=ev.key, outcome=outcome, by=by, likelihood=ev.likelihood, importance=ev.importance,
        surprise=lk.surprise(outcome, ev.likelihood, ev.importance) if outcome != c.UNKNOWN else 0.0,
        nature=lk.nature_of(ev), teller=ev.told_by[0] if ev.told_by else "", shared=ev.shared,
        valence=round(facets_valence(ev.empathy or ev.felt), 3), about=ev.about, sources=tuple(sources),
        call_id=call_id, dedupe_key=f"issue:{ev.key}:{ev.when}")


def _keys(raw: Any) -> list[str]:
    try:
        got = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(k) for k in got] if isinstance(got, list) else []


@MEMORY.process("memory.consolidate", wake_on=[rt.PERCEPTION_RECEIVED, rt.UTTERANCE, c.CONSOLIDATED,
                                               c.EXTRACTION_DEFERRED],
                lane="background", catch_up=CatchUp.ONCE, max_quantum_s=600)
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
        rows = store.query_mind(
            f"SELECT id, at, role, person, text, reply_to, room FROM {transcript_c.THREAD_TABLE} WHERE id>? "
            "ORDER BY id LIMIT ?", (state.checkpoint, p.max_window)) if state.pending else []
        rows = window(rows, set(frame.get(rt.AWAITING)))
        self.stuck_at = None if rows else frame.seq
        directory = self._directory(frame, store)
        her = self_c.name_of(frame.get(self_c.PERSONA))
        tasks = [(conv, 0) for conv in self._conversations(frame, rows, state, directory)]
        drafts: list[Draft[Any]] = []
        # Une reprise par passage : un document illisible ne monopolise pas la mémoire ; la suivante, si elle est
        # due, au passage d'après, aussitôt.
        jobs = store.query_mind(f"SELECT key,messages,attempts,about,aside FROM {DEFERRED_TABLE} "
                                "WHERE status='queued' AND retry_at<=? ORDER BY retry_at,key LIMIT 1", (frame.now,))
        for key, messages, attempts, about, aside in jobs:
            ids = json.loads(messages)
            retry_rows = store.query_mind(
                f"SELECT id, at, role, person, text, reply_to, room FROM {transcript_c.THREAD_TABLE} "
                f"WHERE id IN ({','.join('?' for _ in ids)}) ORDER BY id", tuple(ids)) if ids else []
            drafts.append(c.EXTRACTION_DEFERRED.draft(key=key, status="resolved", attempts=attempts,
                          about=tuple(json.loads(about)), detail=Content.of("reprise", level=3)))
            tasks.extend((conv, attempts) for conv in self._conversations(frame, retry_rows, state, directory,
                                                                           aside=json.loads(aside)))
        tasks = [(self._lies(store, conv), attempts) for conv, attempts in tasks]
        vectors = ctx.ports.get("vectors")
        rooms = self._rooms(frame, store) if tasks else {}
        failed = False
        model, last_call = "", f"{ctx.run_id}#0"
        for n, (conv, attempts) in enumerate(tasks):
            people = x.People.of(conv.speakers, directory, her, scope=conv.key, near=self._near(conv, rooms))
            known = await self._known_beliefs(store, vectors, conv, people, directory)
            promises = self._promises(frame, store, state, conv)
            labels = {speaker.person: speaker.label for speaker in conv.speakers}
            situations = self._situations(frame, store, state, conv, p, labels)
            moments, upcoming = self._moments(frame, store, state, conv, labels)
            ended, gone = self._ended_situations(frame, store, state, conv, p, labels)
            passed, past, foreseen = self._behind(frame, store, state, conv, p, labels)
            prompt = x.render(conv, now=frame.local(), beliefs=known,
                              promises=[(i, _whom(frame, state, i, labels.get(to, to)), t)
                                        for i, to, t in promises], situations=situations, moments=moments,
                              ended=ended, passed=passed)
            request = LLMRequest(role="extract", call_id=f"{ctx.run_id}#{n}", system_stable=x.system(her),
                                 messages=(Message("user", prompt),), tools=(x.tool(her),), max_tokens=x.MAX_OUTPUT_TOKENS,
                                 lane="background", priority=2, meta={"conversation": conv.key})
            # Les souvenirs de contexte sont facultatifs, les messages sources ne le sont pas.
            # Une ancienne liste de situations ne doit pas rendre une paire courte illisible.
            while not fits_context(ctx.llm, request) and (known or promises or situations or moments or ended
                                                           or passed):
                known, promises, situations = known[:len(known) // 2], promises[:len(promises) // 2], situations[:len(situations) // 2]
                moments, ended, passed = moments[:len(moments) // 2], ended[:len(ended) // 2], passed[:len(passed) // 2]
                prompt = x.render(conv, now=frame.local(), beliefs=known,
                                  promises=[(i, _whom(frame, state, i, labels.get(to, to)), t)
                                            for i, to, t in promises], situations=situations, moments=moments,
                                  ended=ended, passed=passed)
                request = replace(request, messages=(Message("user", prompt),))
            retry_size = max(2, p.max_window // (2 ** min(8, attempts // max(1, p.max_attempts))))
            if (not fits_context(ctx.llm, request) or len(conv.lines) > retry_size) and len(conv.lines) > 1:
                cuts = [i for i in range(1, len(conv.lines)) if conv.lines[i].person is not None
                        and conv.lines[i - 1].person is None]
                if cuts:
                    middle = min(cuts, key=lambda i: abs(i - len(conv.lines) // 2))
                    tasks.extend([(replace(conv, lines=conv.lines[:middle]), attempts),
                                  (replace(conv, lines=conv.lines[middle:]), attempts)])
                    continue
            extraction, raw, reason = None, "", "invalid_output"
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
                attempt = attempts + 1
                delay = min(DAY, p.retry_us * 2 ** min(attempt - 1, 16))
                partial = extraction is not None
                # Une sortie partielle, ou une paire qui ne tiendra jamais dans le contexte, attend un opérateur ;
                # le reste revient de lui-même, de plus en plus espacé.
                review = partial or reason == "PromptBudgetError"
                drafts.append(c.EXTRACTION_DEFERRED.draft(
                    key=conv.seqs[0], messages=conv.seqs, aside=tuple(ln.seq for ln in conv.lines if ln.aside),
                    about=tuple(labels), attempts=attempt,
                    retry_at=0 if review else frame.now + delay, status="review" if review else "queued",
                    failure_code="invalid_items" if partial else ("invalid_output" if reason == "invalid_output" else
                        "budget_exceeded" if reason == "PromptBudgetError" else "provider_error"),
                    detail=Content.of(json.dumps({"issues": extraction.issues if partial else [reason],
                                                  "output": raw}, ensure_ascii=False), level=3)))
            if extraction is not None:
                shown = {i for i, _w, _t in (*moments, *ended, *passed)}
                # un moment passé se désigne aussi : reporté après coup (« finalement c'est lundi »), ou constaté
                designable = {i: ev for i, ev in {**upcoming, **gone, **past}.items() if i in shown}
                drafts += await self._drafts(extraction, frame, state, store, conv, people, known, promises, vectors,
                                             p, last_call, moments=designable,
                                             passed={i: ev for i, ev in past.items() if i in shown},
                                             foreseen={i: f for i, f in foreseen.items() if i in shown})
                drafts += self._ended(extraction, situations, last_call)
        if rows:
            drafts.append(c.CONSOLIDATED.draft(upto=rows[-1][0], produced=sum(
                d.type.name != c.EXTRACTION_DEFERRED.name for d in drafts), failed=failed,
                call_id=last_call, model=model))
        if drafts:
            await ctx.emit(*drafts, guard=Guard("point de contrôle", reads=(c.CHECKPOINT,)))
        self.extracted.clear()
        self.outages = 0
        self.retry_at = 0  # un passage mené à bout : le suivant dès qu'il y a de quoi
        due = store.query_mind(f"SELECT MIN(retry_at) FROM {DEFERRED_TABLE} WHERE status='queued'")
        self.next_job_at = int(due[0][0]) if due and due[0][0] is not None else None

    # ── qui est qui ──
    @staticmethod
    def _directory(frame: Frame, store: Any) -> dict[str, tuple[str, ...]]:
        """Toutes les personnes qu'elle connaît (celles à qui elle a parlé),
        par nom et par prénom repliés : un nom porté par une seule personne
        désigne cette personne, même quand elle n'est pas de la conversation."""
        found: dict[str, set[str]] = {}
        for (handle,) in store.query_mind(f"SELECT DISTINCT person FROM {transcript_c.THREAD_TABLE}"):
            if not handle or not is_identifiable(handle):
                continue
            name = clean_display_name(frame.get(identity_c.IDENTITY(handle)).name)
            folded = " ".join(fold(name).split())
            if not folded:
                continue
            key = frame.get(identity_c.PERSON(handle)) or handle
            for k in {folded, folded.split()[0]}:
                found.setdefault(k, set()).add(key)
        return {k: tuple(sorted(v)) for k, v in found.items()}

    def _rooms(self, frame: Frame, store: Any) -> dict[str, set[str]]:
        """Les salons où elle a vu chaque personne : les adresses lues jusqu'ici, plus la suite du fil, rangées sous
        la personne qu'elles désignent maintenant (une adresse reliée depuis parle pour elle)."""
        for seq, handle, room in store.query_mind(
                f"SELECT id, person, room FROM {transcript_c.THREAD_TABLE} WHERE id>? AND room IS NOT NULL "
                "ORDER BY id", (self.rooms_read,)):
            self.rooms_read = max(self.rooms_read, int(seq))
            if handle and is_identifiable(handle):
                self.seen_rooms.setdefault(str(handle), set()).add(str(room))
        out: dict[str, set[str]] = {}
        for handle, seen in self.seen_rooms.items():
            out.setdefault(frame.get(identity_c.PERSON(handle)) or handle, set()).update(seen)
        return out

    @staticmethod
    def _lies(store: Any, conv: x.Conversation) -> x.Conversation:
        """Ses répliques qu'elle a marquées mensonge (``LIE_ANNOTATION``) : la relecture le sait, et n'en tire rien
        comme vrai — ni une croyance, ni une note sur elle (« je ne sais rien de ses projets », redit, ne doit pas
        devenir ce qu'elle croit). Et celles qui racontaient sans nom ce qu'elle sait de quelqu'un (``veiled:…`` dans
        leur provenance, ADR 0091) : la relecture n'en voit pas le texte — rien à en retenir sur qui l'écoutait."""
        mine = [ln.seq for ln in conv.lines if ln.person is None]
        if not mine:
            return conv
        said = {e.seq: json.loads(e.data) for e in store.get_events(mine) if e.type == rt.UTTERANCE.name}
        lied = {seq for seq, d in said.items()
                if any(k == expression_c.LIE_ANNOTATION for k, _v in d.get("annotations") or ())}
        # ce qu'elle a raconté sans nommer personne (ADR 0091) : la relecture n'en voit pas le texte
        veiled = {seq for seq, d in said.items()
                  if any(str(x).startswith(c.VEILED_PROVENANCE) for x in d.get("provenance") or ())}
        if not lied and not veiled:
            return conv
        return replace(conv, lines=tuple(replace(ln, lie=ln.seq in lied, veiled=ln.seq in veiled)
                                         if ln.seq in lied or ln.seq in veiled else ln for ln in conv.lines))

    @staticmethod
    def _near(conv: x.Conversation, rooms: Mapping[str, set[str]]) -> tuple[str, ...]:
        """Celles qu'elle a vues dans un salon avec quelqu'un de cette conversation : quand on y dit « Inès », c'est
        l'Inès qu'ils connaissent tous deux, pas une autre qu'elle connaîtrait seule de son côté."""
        shared = set().union(*(rooms.get(sp.person, set()) for sp in conv.speakers))
        return tuple(sorted(person for person, seen in rooms.items() if seen & shared))

    def _conversations(self, frame: Frame, rows: list[tuple[Any, ...]], state: MemoryState,
                       directory: dict[str, tuple[str, ...]], aside: Sequence[int] = ()) -> list[x.Conversation]:
        """Un fil privé par personne (toutes ses adresses), un salon d'un
        seul tenant. Dans un salon, ce qui ne lui était pas adressé ne compte
        que s'il nomme quelqu'un qu'elle connaît. ``aside`` : ce qu'une reprise
        sait ne pas lui avoir été adressé (la tranche l'a oublié depuis)."""
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
                person_of[handle] = frame.get(identity_c.PERSON(handle)) or handle
                name_of[handle] = clean_display_name(frame.get(identity_c.IDENTITY(handle)).name) or handle
            key = f"room:{room}" if room else f"private:{person_of[handle]}"
            groups.setdefault(key, []).append(row)
        out: list[x.Conversation] = []
        for key, grows in sorted(groups.items(), key=lambda kv: kv[1][0][0]):
            room = grows[0][6]
            tokens: dict[str, x.Speaker] = {}
            lines: list[x.Line] = []
            for seq, at, role, handle, text, _reply, _room in (r[:7] for r in grows):
                person = person_of[handle]
                if person not in tokens:
                    tokens[person] = x.Speaker(f"P{len(tokens) + 1}", person, name_of[handle])
                if role == "assistant":
                    lines.append(x.Line(int(seq), int(at), her, text))
                    continue
                side = bool(room) and int(seq) in aside
                if side and not set(WORD.findall(fold(text))) & known_names:
                    continue  # on parle entre soi, de rien ni de personne qu'elle connaisse
                lines.append(x.Line(int(seq), int(at), tokens[person].label, text, person, side))
            if not any(ln.person for ln in lines):
                continue  # personne ne lui a rien dit : rien à apprendre
            out.append(x.Conversation(key, tuple(tokens.values()), tuple(lines), room or None))
        return out

    # ── ce qu'on montre au modèle ──
    async def _known_beliefs(self, store: Any, vectors: Any, conv: x.Conversation, people: x.People,
                             directory: dict[str, tuple[str, ...]]) -> list[tuple[int, str]]:
        """Ce qu'elle sait déjà et qui touche cette conversation : ses
        personnes, ou quelqu'un qu'on y nomme — jamais ce que d'autres ont
        confié au-delà de l'anodin (le modèle pourrait le recopier ici). Pour
        un salon, seulement l'anodin : ce qu'Alice a confié en privé, recopié
        dans ce que le salon a « entendu », ferait de chacun un témoin."""
        text = " ".join(ln.text for ln in conv.lines)[-2000:]
        if vectors is None or not text.strip():
            return []
        hits = await vectors.search(text, KNOWN_SHOWN * 2, kinds={c.BELIEF})
        if not hits:
            return []
        ids = [k for k, _ in hits]
        marks = ",".join("?" * len(ids))
        found = store.query_mind(f"SELECT id, text, about, told_by, sensitivity, secret FROM {c.ITEMS_TABLE} "
                                 f"WHERE id IN ({marks}) AND status='active'", tuple(ids))
        persons = set(conv.persons)
        named = {k for w in set(WORD.findall(fold(text))) for k in directory.get(w, ())
                 if len(directory.get(w, ())) == 1}
        order = {k: n for n, k in enumerate(ids)}
        # qui l'a dit, témoignage par témoignage (ADR 0080) : ce que les personnes d'ici en ont dit elles-mêmes se
        # montre, même quand un autre l'avait confié avant
        tellers_of: dict[int, list[set[str]]] = {}
        for item, told, speaks in store.query_mind(f"SELECT item, told_by, speaks FROM {TESTIMONIES_TABLE} "
                                                   f"WHERE item IN ({marks})", tuple(ids)):
            if speaks:
                tellers_of.setdefault(int(item), []).append(set(_keys(told)))
        out = []
        for i, t, about, told_by, sens, secret in sorted(found, key=lambda r: order[int(r[0])]):
            concerns = set(_keys(about))
            anodyne = int(sens) <= Sensitivity.ANODYNE and not secret
            told_here = any(bool(tellers) and tellers <= persons
                            for tellers in tellers_of.get(int(i), [set(_keys(told_by))]))
            if not (anodyne or (told_here and not conv.room)):
                continue
            # une mention faite dans cette conversation-ci (« ma collègue Alice ») la touche aussi : sans elle, un
            # « garde-le pour toi » dit après coup ne pouvait plus viser sa croyance (ADR 0075)
            mentioned = {k for k in concerns if x.scope_of(k) == people.scope}
            if concerns and not concerns & (persons | named | mentioned):
                continue
            out.append((int(i), t))
        return out[:KNOWN_SHOWN]

    def _promises(self, frame: Frame, store: Any, state: MemoryState,
                  conv: x.Conversation) -> list[tuple[int, str, str]]:
        """Les promesses en cours envers les personnes de cette conversation
        (des clés de personne : toutes leurs adresses comptent — une adresse
        reliée depuis à quelqu'un parle pour lui)."""
        persons = set(conv.persons)
        pending = [(pr, frame.get(identity_c.PERSON(pr.to)) or pr.to) for pr in state.promises.values()]
        pending = [(pr, to) for pr, to in pending if to in persons]
        if not pending:
            return []
        ids = [pr.id for pr, _ in pending]
        marks = ",".join("?" * len(ids))
        texts = dict(store.query_mind(f"SELECT id, text FROM {c.ITEMS_TABLE} WHERE id IN ({marks})", tuple(ids)))
        return [(pr.id, to, texts.get(pr.id, "")) for pr, to in pending if texts.get(pr.id)]

    @staticmethod
    def _situations(frame: Frame, store: Any, state: MemoryState, conv: x.Conversation, p: MemoryParams,
                    labels: dict[str, str]) -> list[tuple[int, str, str]]:
        """Les situations en cours des personnes de cette conversation (numéro, qui, texte) : la relecture peut dire
        lesquelles la personne dit finies. Comme les croyances connues, jamais ce qu'un autre a confié au-delà de
        l'anodin, et dans un salon l'anodin seulement (le modèle pourrait le recopier ici)."""
        persons = set(conv.persons)
        live: list[tuple[c.LifeEvent, str]] = []
        archive = {ev.id: ev for ev in for_people(store, tuple(persons))}
        for ev in sorted({**state.events, **archive}.values(), key=lambda ev: ev.id):
            if not ev.ongoing or ev.ended_at or not ev.text_ref or ev.when > frame.now:
                continue
            whom = next((k for k in (frame.get(identity_c.PERSON(a)) or a for a in ev.about) if k in persons), None)
            if whom is None:
                continue
            tellers = {frame.get(identity_c.PERSON(t)) or t for t in ev.told_by}
            anodyne = ev.sensitivity <= Sensitivity.ANODYNE and not ev.secret
            if not (anodyne or (tellers <= persons and not conv.room)):
                continue
            live.append((ev, whom))
        if not live:
            return []
        texts = store.content([ev.text_ref for ev, _ in live])
        return [(ev.id, labels.get(whom, whom), phrase("memory.extraction.render.situation",
                 since=frame.local(ev.when).date().isoformat(), text=texts[ev.text_ref]))
                for ev, whom in live if texts.get(ev.text_ref)]

    @staticmethod
    def _moments(frame: Frame, store: Any, state: MemoryState, conv: x.Conversation,
                 labels: dict[str, str]) -> tuple[list[tuple[int, str, str]], dict[int, c.LifeEvent]]:
        """Les moments à venir des personnes de cette conversation (numéro, qui, « le jour : texte ») : la relecture
        peut dire lequel un nouveau remplace — reporté, avancé, précisé (ADR 0076). Sans eux, « finalement mon
        entretien est reporté à lundi » notait un second entretien à côté du premier, et l'ancien, resté non secret,
        trahissait ce que le nouveau gardait (sonde réelle du 2026-10-09). Les mêmes règles que les situations :
        jamais ce qu'un autre a confié au-delà de l'anodin, et dans un salon l'anodin seulement."""
        persons = set(conv.persons)
        archive = {ev.id: ev for ev in for_people(store, tuple(persons))}
        live: dict[int, tuple[c.LifeEvent, str]] = {}
        for ev in sorted({**state.events, **archive}.values(), key=lambda ev: ev.id):
            if ev.ongoing or ev.yearly or not ev.text_ref or over(ev) < frame.now or ev.outcome:
                continue  # passé : il est parmi les moments à constater (ADR 0086)
            whom = next((k for k in (frame.get(identity_c.PERSON(a)) or a for a in ev.about) if k in persons), None)
            if whom is None:
                continue
            tellers = {frame.get(identity_c.PERSON(t)) or t for t in ev.told_by}
            anodyne = ev.sensitivity <= Sensitivity.ANODYNE and not ev.secret
            if anodyne or (tellers <= persons and not conv.room):
                live[ev.id] = (ev, whom)
        if not live:
            return [], {}
        texts = store.content([ev.text_ref for ev, _ in live.values()])
        shown = [(i, labels.get(whom, whom), phrase("memory.extraction.render.moment",
                                                   when=frame.local(ev.when).date().isoformat(),
                                                   text=texts[ev.text_ref]))
                 for i, (ev, whom) in live.items() if texts.get(ev.text_ref)]
        return shown, {i: ev for i, (ev, _w) in live.items()}

    @staticmethod
    def _ended_situations(frame: Frame, store: Any, state: MemoryState, conv: x.Conversation, p: MemoryParams,
                          labels: dict[str, str]) -> tuple[list[tuple[int, str, str]], dict[int, c.LifeEvent]]:
        """Les situations des personnes de cette conversation finies depuis moins de ``recurrence_days`` (numéro, qui,
        « du … au … : texte ») : la relecture peut dire laquelle revient (« il est de nouveau malade »), et la
        reprise garde son fil (ADR 0079). Sans elles, la relecture ne voyait plus une situation finie : à la rechute
        du chat de Carol, elle n'a noté qu'un souvenir, et Mika ne suivait plus rien (sonde réelle du 2026-10-09).
        Les mêmes règles que les situations en cours : jamais ce qu'un autre a confié au-delà de l'anodin, et dans
        un salon l'anodin seulement."""
        persons = set(conv.persons)
        archive = {ev.id: ev for ev in for_people(store, tuple(persons))}
        latest: dict[int, c.LifeEvent] = {}
        for ev in sorted({**state.events, **archive}.values(), key=lambda ev: ev.id):
            latest[ev.thread or ev.id] = ev  # d'un fil, la dernière fois seulement
        live: dict[int, tuple[c.LifeEvent, str]] = {}
        for ev in latest.values():
            if not (ev.ongoing and ev.ended_at and ev.text_ref) or frame.now - ev.ended_at > p.recurrence_days * DAY:
                continue
            whom = next((k for k in (frame.get(identity_c.PERSON(a)) or a for a in ev.about) if k in persons), None)
            if whom is None:
                continue
            tellers = {frame.get(identity_c.PERSON(t)) or t for t in ev.told_by}
            anodyne = ev.sensitivity <= Sensitivity.ANODYNE and not ev.secret
            if anodyne or (tellers <= persons and not conv.room):
                live[ev.id] = (ev, whom)
        if not live:
            return [], {}
        texts = store.content([ev.text_ref for ev, _ in live.values()])
        shown = [(i, labels.get(whom, whom), phrase("memory.extraction.render.ended_situation",
                                                   since=frame.local(ev.when).date().isoformat(),
                                                   ended=frame.local(ev.ended_at).date().isoformat(),
                                                   text=texts[ev.text_ref]))
                 for i, (ev, whom) in live.items() if texts.get(ev.text_ref)]
        return shown, {i: ev for i, (ev, _w) in live.items()}

    # ── ce qu'on en garde ──
    async def _drafts(self, ex: x.Extraction, frame: Frame, state: MemoryState, store: Any, conv: x.Conversation,
                      people: x.People, known: list[tuple[int, str]], promises: list[tuple[int, str, str]],
                      vectors: Any, p: MemoryParams, call_id: str,
                      moments: dict[int, c.LifeEvent] | None = None,
                      passed: dict[int, c.LifeEvent] | None = None,
                      foreseen: dict[int, Forecast] | None = None) -> list[Draft[Any]]:
        drafts: list[Draft[Any]] = []
        known_ids = {i for i, _ in known}
        known_texts = dict(known)
        tz = frame.env.tz_of(frame.root)
        heard = conv.persons
        lines = {ln.seq: ln for ln in conv.lines}
        speaking = tuple(sorted({ln.person for ln in conv.lines if ln.person}))
        # une demande de silence couvre ce qu'elle vise, pas toute la conversation (ADR 0092)
        lowered = x.scoped_secrets(ex, conv.lines)
        if lowered:
            log.info("relecture : %d « secret(s) » hors de la demande de silence, gardé(s) en confidence", len(lowered))

        def provenance(cited: Sequence[int]) -> tuple[tuple[int, ...], tuple[str, ...], list[str]]:
            """Les messages d'où vient un élément, qui les a écrits (qui l'a
            confié) et leurs textes. Sans citation : toute la conversation, et
            tous ceux qui y ont parlé l'ont confié (dans le doute, on ferme)."""
            seqs = sorted({s for s in cited if s in lines})
            if not seqs:
                return conv.seqs, speaking if len(speaking) == 1 else (), []
            persons = sorted({lines[s].person for s in seqs if lines[s].person})
            return tuple(seqs), tuple(str(k) for k in persons), [lines[s].text for s in seqs if lines[s].person]

        def hers(cited: Sequence[int]) -> bool:
            """L'élément ne s'appuie que sur ce qu'elle a dit elle-même : ce n'est pas quelque chose qu'on lui a
            appris (sonde réelle du 2026-10-02 : elle avait inventé « il n'a rien voulu me dire » devant Chloé, et
            l'extraction en avait fait une croyance sur Adrien)."""
            seqs = [s for s in cited if s in lines]
            return bool(seqs) and not any(lines[s].person for s in seqs)

        def from_her(cited: Sequence[int]) -> bool:
            """Ce qu'elle dit d'elle vient de sa bouche : une de ses répliques est citée (la question qu'on lui a posée
            peut l'être aussi), ou rien ne l'est (le doute d'avant). Ce que seule une autre personne a dit d'elle
            (« ton code, c'est ORCHIDEE, garde-le pour toi ») lui a été appris : il suit le chemin commun, avec son
            confident et son secret (audit du 2026-10-08)."""
            seqs = [s for s in cited if s in lines]
            return not seqs or any(not lines[s].person for s in seqs)

        def lied(cited: Sequence[int]) -> bool:
            """Ce qu'elle dit d'elle s'appuie sur une de ses répliques marquées mensonge (ADR 0076), ou qui racontait
            sans nom ce qu'elle sait de quelqu'un (ADR 0091) — ou ne cite rien, dans une conversation où elle a menti :
            ce n'est pas ce qu'elle est (dans le doute, on ferme ; ADR 0087)."""
            seqs = [s for s in cited if s in lines]
            if not seqs:
                return any(ln.lie for ln in conv.lines)
            return any((lines[s].lie or lines[s].veiled) and not lines[s].person for s in seqs)

        def her_words(cited: Sequence[int]) -> list[str]:
            """Ses répliques citées : « garde ça pour toi », dit par elle, fait un secret même quand le modèle ne le
            note pas (``provenance`` ne rend que les mots des autres)."""
            return [lines[s].text for s in cited if s in lines and not lines[s].person]

        def concerned(names: list[str]) -> tuple[str, ...]:
            """Dans le doute, on ferme : un élément dont le modèle ne nomme
            personne concerne ceux qui parlent dans cette conversation (le seul
            interlocuteur d'un fil privé) — sinon il serait rangé comme ne
            concernant personne, donc dicible à tous."""
            return people.resolve(names) or speaking

        def asked_silence(flag: bool, cited: list[str], sens: int) -> bool:
            if flag or x.says_secret(cited):
                return True
            # rien de cité : une confidence d'une conversation où l'on a demandé le silence
            return not cited and sens >= Sensitivity.CONFIDENCE and x.says_secret(
                [ln.text for ln in conv.lines if ln.person])

        # ce qui laisse deviner un secret est secret aussi : les secrets de ce lot, et ceux qu'elle garde déjà
        her = self_c.name_of(frame.get(self_c.PERSONA))
        names = {st for sp in conv.speakers for st in stems(sp.name)} | stems(her)
        secrets = self._secrets(store, conv)
        for item in (*ex.souvenirs, *ex.croyances, *ex.evenements):
            cited = provenance(item.messages)[2]
            sens = x.sensitivity(item.sensibilite, has_person=True)
            if asked_silence(item.secret, cited, sens):
                secrets.append(item.texte)

        def secret_of(flag: bool, cited: list[str], sens: int, text: str = "") -> bool:
            return asked_silence(flag, cited, sens) or (bool(text) and x.echoes(text, secrets, names))

        seen: set[tuple[str, str]] = set()  # le même élément deux fois dans un lot n'en fait qu'un
        said_names = [*(sp.name for sp in conv.speakers), her]
        name_of = {sp.person: sp.name for sp in conv.speakers}
        mine = [ln for ln in conv.lines if ln.person is None]
        nicks = self._heard_nicknames(conv, her)  # « salut Mikachu » : comment la personne l'appelle
        ours: list[str] = []  # ce qui n'appartient qu'à elles deux, retenu dans ce lot

        def fresh(kind: str, text: str) -> bool:
            key = (kind, " ".join(fold(text).split()))
            if key in seen:
                return False
            seen.add(key)
            return True

        for s in ex.souvenirs:
            if not fresh(c.SOUVENIR, s.texte):
                continue
            if s.sur_elle and not people.resolve(s.personnes) and from_her(s.messages) \
                    and not people.names_someone(s.texte):
                if not lied(s.messages):
                    drafts += self._about_self(s, store, provenance, call_id, known_ids, secret_of,
                                               her_words(s.messages))
                continue
            text, cited_seqs = s.texte, list(s.messages)
            if banal(text, said_names):
                continue  # « Sam est parti en disant 'allez j'y vais' » : une banalité ne se retient pas
            line = x.copy_of(text, conv.lines) or x.voice_of(text, conv.lines)
            if line is not None:
                # une réplique recopiée n'est pas un souvenir (sonde réelle du 2026-10-03 : « Dors bien Sam… », « on
                # l'a endormi ») : la sienne, jamais ; celle de la personne, citée en disant qui parle, si elle compte
                if line.person is None or s.importance < 2:
                    continue
                text, cited_seqs = x.quoted(name_of.get(line.person, ""), text), [line.seq]
            about = concerned(s.personnes)
            sources, told_by, cited = provenance(cited_seqs)
            sens = x.sensitivity(s.sensibilite, has_person=bool(about or told_by))
            secret = secret_of(s.secret, cited, sens, text)
            twin = await self._twin(store, vectors, text, c.SOUVENIR, about, p, told_by=told_by, heard_by=heard)
            if twin is not None:
                drafts.append(c.REINFORCED.draft(item=twin, sources=sources, sensitivity=sens, about=about,
                                                 told_by=told_by, heard_by=heard, secret=secret))
                continue
            # sans nom : seulement ce qui concerne quelqu'un d'autre, ni secret, ni recopié de sa bouche (ADR 0091)
            veiled = self._veiled(s.sans_nom, people, s.texte) if about and not secret and text == s.texte else None
            drafts.append(c.REMEMBERED.draft(
                text=Content.of(text, level=sens), about=about, sensitivity=sens,
                importance=x.IMPORTANCE.get(s.importance, 0.45), emotion=dominant(facets(s.mon_ressenti)),
                felt=facets(s.ressenti), empathy=facets(s.mon_ressenti), sources=sources, call_id=call_id, told_by=told_by, heard_by=heard,
                secret=secret, veiled=Content.of(veiled, level=sens) if veiled else None))
        for b in ex.croyances:
            if not fresh(c.BELIEF, b.texte):
                continue
            if b.sur_elle and not people.resolve(b.personnes) and from_her(b.messages) \
                    and not people.names_someone(b.texte):
                # ce qu'elle dit d'elle seule ; « Mika a dit à Sam : … », lui, nomme quelqu'un : ce n'est pas une
                # note anodine sur elle (elle sortait telle quelle dans un salon — sonde du 2026-10-03), il suit le
                # chemin commun (sa réplique n'est pas ce qu'on lui a appris)
                if not lied(b.messages):
                    drafts += self._about_self(b, store, provenance, call_id, known_ids, secret_of,
                                               her_words(b.messages))
                continue
            between = b.entre_vous or any(fold(n) in fold(b.texte) for n in nicks)
            if (not between and hers(b.messages)) or banal(b.texte, said_names):
                continue  # ce qu'elle a dit des autres n'est pas ce qu'on lui a appris d'eux ; une banalité, rien
            if x.copy_of(b.texte, mine) is not None:
                continue  # sa réplique recopiée, quoi qu'en disent les numéros cités (ADR 0048, 0055)
            about = concerned(b.personnes)
            sources, told_by, cited = provenance(b.messages)
            # leur lien, de première main : ce qu'un tiers en raconte n'est pas ce qui n'appartient qu'à elles deux
            between = between and set(told_by) <= set(about)
            # qui l'a dit : celle qu'on nomme, sinon la seule personne dont viennent les messages cités (un modèle
            # oublie souvent de la nommer — sonde réelle du 2026-10-03 : « Pixel souffre d'insuffisance rénale »,
            # dit par Sam, sans source, n'était plus « ce qu'il lui a raconté de sa vie »)
            source = people.one(b.source) if b.source else (told_by[0] if len(told_by) == 1 else None)
            sens = x.sensitivity(b.sensibilite, has_person=bool(about or told_by))
            if between and not conv.room:
                sens = max(sens, int(Sensitivity.PERSONAL))  # dit en privé : jamais devant une inconnue
            importance = x.IMPORTANCE.get(b.importance, 0.45)
            if between:
                importance = max(importance, x.IMPORTANCE[3])  # entre amis, c'est ce qui fait un lien
            secret = secret_of(b.secret, cited, sens, b.texte)
            replaces = b.remplace if b.remplace in known_ids else None
            if between:
                ours.append(fold(b.texte))
            nature = x.kind_of_genre(b.genre)
            if x.ORIGIN.get(fold(b.origine)) == "inferred":
                nature = "hypothesis"
            # un avis, une hypothèse sont à qui les porte ; un fait rapporté n'est à personne (ses témoins le disent)
            holder = people.one(b.point_de_vue) if b.point_de_vue else (source if nature != "claim" else None)
            relations = []
            for relation in b.relations:
                subject, other = people.one(relation.subject), people.one(relation.other)
                if subject and other and subject != other and cited:
                    relations.append(c.Relation(subject=subject, other=other, kind=relation.kind,
                                                status=relation.status))
                    about = tuple(sorted({*about, subject, other}))
            origin = x.ORIGIN.get(fold(b.origine), "told")
            # de première main : la personne nommée qui parle d'elle-même, ou un témoin qui l'a vu (ADR 0081)
            named = set(people.resolve(b.personnes))
            first_hand = bool(b.de_premiere_main) or (bool(told_by) and bool(named) and set(told_by) <= named)
            said = Testimony(0, tuple(told_by), tuple(heard), sens, secret, 0.0, origin=origin,
                             first_hand=first_hand)
            # la vérité se juge sans l'audience : la croyance désignée est remplacée par une source au moins aussi
            # sûre, ou le même témoin qui se corrige ; sinon contestée — elle doute (ADR 0081)
            target = self._target_of(store, replaces, nature, holder)
            verdict = judge(self._testimonies(store, target), said) if target is not None else None
            replaces = target if verdict == SUPERSEDE else None
            contests = target if verdict == CONTEST else None
            twin = await self._twin(store, vectors, b.texte, c.BELIEF, about, p,
                                    told_by=told_by, heard_by=heard, knowledge_kind=nature, holder=holder)
            if target is not None and not same_words(known_texts.get(target, ""), b.texte):
                twin = None  # une correction explicite prime sur la proximité vectorielle
            former = None
            if twin is None and target is None:
                # ce qu'elle a cru, puis cessé de croire, et qu'on lui redit : elle y revient (ou elle doute)
                former = self._former_twin(store, b.texte, about, nature, holder)
            if former is not None:
                head = self._head_of(store, former)
                again = judge(self._testimonies(store, head), said) if head is not None else None
                drafts.append(c.ATTESTED.draft(
                    item=former, told_by=told_by, heard_by=heard, source=source, origin=origin,
                    confidence=x.born_confidence(b.confiance, origin, nature), sensitivity=sens, secret=secret,
                    between_us=between, sources=sources, about=about, relations=tuple(relations),
                    replaces=head if again == SUPERSEDE else None, contests=head if again == CONTEST else None,
                    first_hand=first_hand, call_id=call_id, felt=facets(b.ressenti)))
                continue
            if twin is not None:
                # la même proposition : un témoignage de plus, avec ses propres droits (ADR 0080) — redire une
                # croyance en la désignant elle-même comme « remplacée » n'est pas la réviser : c'est la confirmer
                # (sonde réelle du 2026-10-02 : « Je croyais que X — apparemment ce n'est plus vrai : X »)
                drafts.append(c.ATTESTED.draft(
                    item=twin, told_by=told_by, heard_by=heard, source=source, origin=origin,
                    confidence=x.born_confidence(b.confiance, origin, nature), sensitivity=sens, secret=secret,
                    between_us=between, sources=sources, about=about, relations=tuple(relations),
                    replaces=replaces if replaces != twin else None, contests=contests if contests != twin else None,
                    first_hand=first_hand, call_id=call_id, felt=facets(b.ressenti)))
                continue
            since, until = x.when(b.depuis, tz) if b.depuis else None, x.when(b.jusqua, tz) if b.jusqua else None
            # sans nom : un fait sur quelqu'un d'autre, ni secret, ni ce qui n'appartient qu'à eux deux (ADR 0091)
            veiled = self._veiled(b.sans_nom, people, b.texte) \
                if about and not secret and not between and nature == "claim" else None
            drafts.append(c.BELIEVED.draft(
                text=Content.of(b.texte, level=sens), about=about, sensitivity=sens,
                importance=importance, confidence=x.born_confidence(b.confiance, origin, nature),
                origin=origin, source=source, replaces=replaces, contests=contests, sources=sources,
                call_id=call_id, told_by=told_by, heard_by=heard, secret=secret, between_us=between,
                knowledge_kind=nature, holder=holder, relations=tuple(relations), first_hand=first_hand,
                as_of=min(since[0], frame.now) if since else None, valid_until=until[0] if until else None,
                felt=facets(b.ressenti), empathy=facets(b.mon_ressenti),
                veiled=Content.of(veiled, level=sens) if veiled else None))
        drafts += self._predictions(ex, frame, conv, people, p, call_id, fresh, provenance, concerned, secret_of,
                                    from_her, lied, heard, tz)
        drafts += self._called(nicks, ours, store, conv, call_id)
        closed = [item for item in dict.fromkeys(ex.confidentiel) if item in known_ids]
        for item in closed:
            # la discrétion demandée : sur ce que celui qui la demande en a dit — sur tout, quand c'est la
            # personne concernée elle-même (ADR 0080)
            concerned_by = set(self._about_of(store, item))
            drafts.append(c.ATTESTED.draft(item=item, told_by=tuple(conv.persons), heard_by=tuple(conv.persons),
                                           restricts=True, everyone=bool(concerned_by & set(conv.persons)),
                                           sensitivity=int(Sensitivity.CONFIDENCE), secret=True,
                                           call_id=call_id))
        drafts += self._closed_souvenirs(frame, store, conv, closed)
        drafts += await self._promised(ex, frame, state, store, conv, people, promises, vectors, p, provenance,
                                       fresh, call_id, lambda text: x.echoes(text, secrets, names))
        drafts += await self._events(ex, frame, state, store, conv, people, vectors, p, provenance, concerned,
                                     secret_of, heard, fresh, call_id, moments or {})
        drafts += self._constats(ex, frame, store, conv, people, passed or {}, p, provenance, call_id,
                                 upcoming={i: ev for i, ev in (moments or {}).items() if not ev.ongoing})
        drafts += self._foreseen(ex, frame, foreseen or {}, provenance, call_id)
        return drafts

    @staticmethod
    def _moved(old: c.LifeEvent, at: int, frame: Frame, by: Sequence[str], sources: Sequence[int],
               call_id: str) -> list[Draft[Any]]:
        """Un moment déplacé à un autre jour — pas précisé dans sa période (« en novembre » → « le 12 ») : comment il
        a tourné à sa date (``moved``), ce qui apprend un report de plus de qui l'avait annoncé (ADR 0086). À écrire
        avant le moment à sa nouvelle date, qui reprend son fil."""
        tz = frame.env.tz_of(frame.root)
        if old.outcome or old.ongoing or day_of(old.when, tz) <= day_of(at, tz) <= day_of(old.ends, tz):
            return []
        return [resolution(old, c.MOVED, by[0] if len(by) == 1 else "", sources, call_id)]

    @staticmethod
    def _passed(frame: Frame, store: Any, state: MemoryState, conv: x.Conversation, p: MemoryParams,
                labels: dict[str, str]) -> tuple[list[tuple[int, str, str]], dict[int, c.LifeEvent]]:
        """Les moments des personnes de cette conversation passés depuis moins de ``resolve_days``, dont elle ne sait
        pas comment ils ont tourné (numéro, qui, « le jour : texte ») : si la personne le dit, la relecture le constate
        (ADR 0086). Les mêmes règles que les moments à venir : jamais ce qu'un autre a confié au-delà de l'anodin, et
        dans un salon l'anodin seulement."""
        persons = set(conv.persons)
        archive = {ev.id: ev for ev in for_people(store, tuple(persons))}
        since = frame.now - round(p.resolve_days * DAY)
        live: dict[int, tuple[c.LifeEvent, str]] = {}
        for ev in sorted({**state.events, **archive}.values(), key=lambda ev: ev.id):
            if ev.ongoing or ev.yearly or ev.outcome or not ev.text_ref or not since <= over(ev) < frame.now:
                continue
            whom = next((k for k in (frame.get(identity_c.PERSON(a)) or a for a in ev.about) if k in persons), None)
            if whom is None:
                continue
            tellers = {frame.get(identity_c.PERSON(t)) or t for t in ev.told_by}
            anodyne = ev.sensitivity <= Sensitivity.ANODYNE and not ev.secret
            if anodyne or (tellers <= persons and not conv.room):
                live[ev.id] = (ev, whom)
        if not live:
            return [], {}
        texts = store.content([ev.text_ref for ev, _ in live.values()])
        shown = [(i, labels.get(whom, whom), phrase("memory.extraction.render.moment",
                                                   when=frame.local(ev.when).date().isoformat(),
                                                   text=texts[ev.text_ref]))
                 for i, (ev, whom) in live.items() if texts.get(ev.text_ref)]
        return shown, {i: ev for i, (ev, _w) in live.items()}

    def _behind(self, frame: Frame, store: Any, state: MemoryState, conv: x.Conversation, p: MemoryParams,
                labels: dict[str, str]) -> tuple[list[tuple[int, str, str]], dict[int, c.LifeEvent],
                                                  dict[int, Forecast]]:
        """Ce qui est passé sans qu'elle sache comment ça a tourné, montré à la relecture : les moments, puis les
        prévisions (ADR 0086, 0099)."""
        passed, past = self._passed(frame, store, state, conv, p, labels)
        forecasts, foreseen = self._forecasts(frame, store, conv, p, labels)
        return [*passed, *forecasts], past, foreseen

    @staticmethod
    def _forecasts(frame: Frame, store: Any, conv: x.Conversation, p: MemoryParams,
                   labels: dict[str, str]) -> tuple[list[tuple[int, str, str]], dict[int, Forecast]]:
        """Les prévisions des personnes de cette conversation (« Léa pense qu'elle sera prise ») dont l'échéance est
        passée depuis moins de ``resolve_days`` et qu'on n'a pas encore constatées : montrées avec les moments passés,
        pour que la relecture dise si elles se sont réalisées (ADR 0099). Les mêmes règles de discrétion que les
        moments : dans un salon, l'anodin seulement ; jamais ce qu'un autre a confié au-delà."""
        persons = set(conv.persons)
        since = frame.now - round(p.resolve_days * DAY)
        rows = store.query_mind(
            f"SELECT id, text, about, holder, told_by, likelihood, importance, due, until, sensitivity, secret, felt, "
            f"empathy FROM {c.ITEMS_TABLE} WHERE kind=? AND knowledge_kind='prediction' AND status='active' "
            "AND due IS NOT NULL AND COALESCE(until, due) < ? AND COALESCE(until, due) >= ? ORDER BY id",
            (c.BELIEF, frame.now, since))
        shown: list[tuple[int, str, str]] = []
        found: dict[int, Forecast] = {}
        for (item, text, about, holder, told_by, likely, importance, due, until, sens, secret, felt,
             empathy) in rows:
            concerned = {frame.get(identity_c.PERSON(k)) or k for k in (*_keys(about), *([holder] if holder else []))}
            whom = next((k for k in sorted(concerned) if k in persons), None)
            if whom is None or not text:
                continue
            tellers = {frame.get(identity_c.PERSON(t)) or t for t in _keys(told_by)}
            if not (int(sens) <= Sensitivity.ANODYNE and not secret) and (conv.room or not tellers <= persons):
                continue
            found[int(item)] = Forecast(int(item), tuple(_keys(about)), holder or "", likely, float(importance or 0.5),
                                        tuple(concerned), _facets_of(empathy) or _facets_of(felt))
            shown.append((int(item), labels.get(whom, whom), phrase(
                "memory.extraction.render.forecast", when=frame.local(int(until or due)).date().isoformat(),
                text=str(text))))
        return shown, found

    @staticmethod
    def _foreseen(ex: x.Extraction, frame: Frame, foreseen: dict[int, Forecast], provenance: Any,
                  call_id: str) -> list[Draft[Any]]:
        """Une prévision passée, constatée par une personne qu'elle concerne (« j'ai été prise ! ») : réalisée (« a eu
        lieu ») ou non (« annulé ») — ce qu'elle apprend de qui l'avait prévu, et de ses propres pronostics (sa
        calibration, la sorte « prévision »). Ce qu'un autre en dit ne constate rien (ADR 0099)."""
        drafts: list[Draft[Any]] = []
        for k in ex.constats:
            f = foreseen.get(k.numero)
            outcome = x.outcome_of(k.issue)
            if f is None or outcome not in (c.HAPPENED, c.CANCELLED) or not k.messages:
                continue
            sources, told_by, _cited = provenance(k.messages)
            by = next((t for t in told_by if (frame.get(identity_c.PERSON(t)) or t) in f.concerned), None)
            if by is None:
                continue
            drafts.append(c.RESOLVED.draft(
                event=f.item, outcome=outcome, by=by, likelihood=f.likelihood, importance=f.importance,
                surprise=lk.surprise(outcome, f.likelihood, f.importance), nature=c.PREDICTION, teller=f.holder,
                valence=round(facets_valence(f.felt), 3), about=f.about, sources=tuple(sources), call_id=call_id,
                dedupe_key=f"issue:prévision:{f.item}"))
            foreseen = {i: g for i, g in foreseen.items() if i != f.item}
        return drafts

    @staticmethod
    def _constats(ex: x.Extraction, frame: Frame, store: Any, conv: x.Conversation, people: x.People,
                  passed: dict[int, c.LifeEvent], p: MemoryParams, provenance: Any, call_id: str,
                  upcoming: dict[int, c.LifeEvent] | None = None) -> list[Draft[Any]]:
        """Comment un moment passé a tourné, de la bouche de la personne concernée — ses messages à elle seulement :
        ce qu'un autre en dit n'est qu'une rumeur (ADR 0086). Un moment à venir peut être annulé d'avance (« finalement
        mon IRM de demain est annulée ») ; il n'a pas encore eu lieu. Un moment qu'elle vivait à travers elle (« je te
        montrerai tout »), qui a eu lieu, devient un souvenir à elle, plus marquant avec sa propriétaire — avec, quand
        rien n'en est secret ni confié, ce que c'était en bref et sans personne (« un concert de jazz », ADR 0087)."""
        drafts: list[Draft[Any]] = []
        done: set[int] = set()
        for k in ex.constats:
            outcome = x.outcome_of(k.issue)
            ev = passed.get(k.numero)
            if ev is None and outcome == c.CANCELLED:
                ev = (upcoming or {}).get(k.numero)
            if ev is None or outcome is None or ev.id in done:
                continue
            sources, told_by, _cited = provenance(k.messages)
            concerned = {frame.get(identity_c.PERSON(a)) or a for a in ev.about}
            by = next((t for t in told_by if (frame.get(identity_c.PERSON(t)) or t) in concerned), None)
            if by is None or not k.messages:
                continue
            done.add(ev.id)
            drafts.append(resolution(ev, outcome, by, sources, call_id))
            if outcome == c.HAPPENED and ev.shared:
                text = store.content([ev.text_ref]).get(ev.text_ref)
                if not text:
                    continue
                name = next((sp.name for sp in conv.speakers if sp.person == by), "") or \
                    frame.get(identity_c.IDENTITY(by)).name or phrase("memory.names.someone")
                owner = bool(frame.get(identity_c.IS_OWNER(frame.get(identity_c.PERSON(by)) or by)))
                lived = phrase("memory.lived.souvenir", name=name, text=text)
                gist = x.gist_of(k.en_bref, people) if not ev.secret and ev.sensitivity < Sensitivity.CONFIDENCE \
                    else None
                drafts.append(c.REMEMBERED.draft(
                    text=Content.of(lived, level=ev.sensitivity), about=ev.about, sensitivity=ev.sensitivity,
                    importance=p.lived_owner_importance if owner else p.lived_importance,
                    emotion=dominant(ev.empathy) or Emotion.HAPPY.value, sources=sources, call_id=call_id,
                    told_by=(by,), heard_by=conv.persons, secret=ev.secret, felt=ev.felt, empathy=ev.empathy,
                    gist=Content.of(gist, level=ev.sensitivity) if gist else None,
                    dedupe_key=f"vécu:{ev.key}:{ev.when}"))
        return drafts

    @staticmethod
    def _ended(ex: x.Extraction, situations: list[tuple[int, str, str]], call_id: str) -> list[Draft[Any]]:
        """Les situations que la personne dit finies, parmi celles montrées à la relecture : un numéro qu'elle n'a
        pas vu ne finit rien."""
        shown = {i for i, _, _ in situations}
        return [c.SITUATION_ENDED.draft(event=i, call_id=call_id, dedupe_key=f"situation-finie:{i}")
                for i in dict.fromkeys(ex.situations_finies) if i in shown]

    @staticmethod
    def _heard_nicknames(conv: x.Conversation, her: str) -> dict[str, list[int]]:
        """En privé, les surnoms que la personne lui donne en la saluant (« salut Mikachu ») et où elle l'a fait."""
        if conv.room or len(conv.persons) != 1:
            return {}
        heard: dict[str, list[int]] = {}
        for ln in conv.lines:
            if ln.person == conv.persons[0]:
                for nick in x.nicknames(ln.text, her):
                    heard.setdefault(nick, []).append(ln.seq)
        return heard

    @staticmethod
    def _called(heard: dict[str, list[int]], ours: list[str], store: Any, conv: x.Conversation,
                call_id: str) -> list[Draft[Any]]:
        """Comment la personne l'appelle, quand le modèle ne l'a pas retenu : en privé, un mot qui la salue et
        dérive de son prénom (« salut Mikachu ») — la sonde réelle du 2026-10-03 l'a vue l'oublier, puis répondre
        « je t'appelle Sam, tout simplement » à « tu te souviens comment je t'appelle ? ». Redit, il renforce ce
        qu'elle en sait déjà ; ce que le modèle en a retenu lui-même (``ours``) n'est pas noté deux fois."""
        if not heard:
            return []
        person = conv.persons[0]
        noted = ours
        known = store.query_mind(f"SELECT id, text FROM {c.ITEMS_TABLE} WHERE kind=? AND status='active' "
                                 f"AND between_us=1 AND id IN (SELECT item FROM {c.ABOUT_TABLE} WHERE person=?) "
                                 "ORDER BY id", (c.BELIEF, person))
        name = next((sp.name for sp in conv.speakers if sp.person == person), "")
        drafts: list[Draft[Any]] = []
        for nick, seqs in heard.items():
            folded = fold(nick)
            if any(folded in t for t in noted):
                continue
            hit = next((int(i) for i, t in known if folded in fold(str(t))), None)
            if hit is not None:
                # redit par la même personne : la date et les messages, rien de plus sûr
                drafts.append(c.ATTESTED.draft(item=hit, told_by=(person,), heard_by=conv.persons, source=person,
                                               origin=c.OBSERVED, confidence=0.9, between_us=True,
                                               sensitivity=int(Sensitivity.PERSONAL), sources=tuple(seqs),
                                               about=(person,), call_id=call_id))
                continue
            sens = int(Sensitivity.PERSONAL)
            drafts.append(c.BELIEVED.draft(
                text=Content.of(phrase("memory.extraction.nickname", name=name or phrase("memory.extraction.someone"),
                                       nick=nick), level=sens), about=(person,),
                sensitivity=sens, importance=x.IMPORTANCE[3], confidence=0.9, origin=c.OBSERVED, source=person,
                sources=tuple(seqs), call_id=call_id, told_by=(person,), heard_by=conv.persons, between_us=True))
        return drafts

    @staticmethod
    def _veiled(proposed: str | None, people: x.People, original: str) -> str | None:
        """La version sans nom que la relecture propose, si le filet la garde (``original`` : ce qu'elle raconte,
        nommé) ; sinon, pourquoi (un code, jamais le texte : il pouvait nommer quelqu'un)."""
        if not proposed:
            return None
        why = x.veiled_refusal(proposed, people, original)
        if why:
            log.info("relecture : une version sans nom écartée (%s)", why)
            return None
        return " ".join(proposed.split())

    @staticmethod
    def _secrets(store: Any, conv: x.Conversation) -> list[str]:
        """Les secrets qu'elle garde déjà sur les personnes de cette conversation."""
        return kept_secrets(store, conv.persons)

    def _about_self(self, b: x.XSouvenir | x.XCroyance, store: Any, provenance: Any, call_id: str,
                    known_ids: set[int], secret_of: Any = None, her_lines: Sequence[str] = ()) -> list[Draft[Any]]:
        """Ce qu'elle a raconté d'elle-même : une note anodine, de peu
        d'importance, qui s'efface en quelques jours — sauf ce qui la définit
        (un goût, un avis, un fait de sa vie), qui tient longtemps ; quand elle
        change d'avis, la nouvelle croyance remplace l'ancienne. Ce qu'elle a
        demandé de garder pour soi, ou une confidence sur elle, le reste : ça ne
        se dit qu'en grande confiance (audit du 2026-10-08).

        Les mêmes mots sont la même note, quelle qu'en soit la sorte : une anecdote redite comme un goût le devient,
        et ce qu'elle pensait avant d'en changer, redit, revient — sa parole sur elle-même tranche (ADR 0087)."""
        sources, _told, cited = provenance(b.messages)
        sens = x.sensitivity(b.sensibilite, has_person=False)
        asked = bool(b.secret) or x.says_secret(her_lines)  # elle a demandé le silence
        secret = bool(secret_of(asked, cited, sens, b.texte)) if secret_of is not None else asked
        # sa vie de tous les jours est à elle, elle la raconte à qui elle veut ; une confidence ou un secret, non
        sens = max(sens, int(Sensitivity.CONFIDENCE)) if secret else (
            sens if sens >= Sensitivity.CONFIDENCE else int(Sensitivity.ANODYNE))
        durable = x.durable_self(b)
        nature = x.kind_of_genre(b.genre)
        confidence = x.born_confidence(getattr(b, "confiance", 0.7), c.OBSERVED, nature)
        replaces = getattr(b, "remplace", None)
        replaces = replaces if durable and replaces in known_ids else None
        if replaces is not None and not self._target_of(store, replaces, nature, None, about_self=True):
            replaces = None  # changer d'avis ne vaut que sur ce qu'elle a dit d'elle-même
        twin = self._self_twin(store, b.texte, status="active")
        former = None if twin is not None else self._self_twin(store, b.texte, status="superseded")
        head = self._head_of(store, former) if former is not None else None  # ce qu'elle en pense maintenant
        if (twin is not None and twin != replaces) or head is not None:
            # ce qu'elle redit d'elle-même : son propre témoignage, redit
            return [c.ATTESTED.draft(item=twin if head is None else former, sources=sources, sensitivity=sens,
                                     secret=secret, origin=c.OBSERVED, confidence=confidence, about_self=True,
                                     durable=durable, knowledge_kind=nature if durable else None, replaces=head,
                                     call_id=call_id)]
        return [c.BELIEVED.draft(
            text=Content.of(b.texte, level=sens), about=(), sensitivity=sens,
            importance=x.IMPORTANCE[3 if durable else 1], confidence=confidence,
            origin=c.OBSERVED, sources=sources, replaces=replaces, call_id=call_id, about_self=True, durable=durable,
            knowledge_kind=nature, secret=secret)]

    @staticmethod
    def _self_twin(store: Any, text: str, *, status: str) -> int | None:
        """Ce qu'elle a déjà dit d'elle-même aux mêmes mots, quelle qu'en soit la sorte : vivante (elle le redit — la
        plus ancienne), ou remplacée (elle y revient — la dernière qu'elle a quittée)."""
        order = "id" if status == "active" else "id DESC"
        rows = store.query_mind(
            f"SELECT id, text FROM {c.ITEMS_TABLE} WHERE fingerprint=? AND kind=? AND status=? AND about_self > 0 "
            f"ORDER BY {order}", (fingerprint(text), c.BELIEF, status))
        return next((int(k) for k, previous in rows if same_words(previous, text)), None)

    async def _promised(self, ex: x.Extraction, frame: Frame, state: MemoryState, store: Any, conv: x.Conversation,
                        people: x.People, promises: list[tuple[int, str, str]], vectors: Any, p: MemoryParams,
                        provenance: Any, fresh: Any, call_id: str, secretive: Any) -> list[Draft[Any]]:
        """Ce qu'elle a promis : à une personne (toutes ses adresses), une seule
        fois (une promesse redite n'en fait pas deux), avec une échéance même
        quand rien n'a été dit — l'horizon d'une promesse vague. Une promesse
        qui laisse deviner un secret est aussi sensible qu'une confidence.

        Un rappel qu'on lui a demandé et qu'elle a accepté en mots est une
        promesse — sauf s'il est déjà programmé (l'outil ``goal_remind``, un but
        ``goals``) : il existe une fois et une seule. Une promesse datée ne se
        règle « tenue » qu'à partir de son jour (la veille, en parler n'est pas
        la tenir) ; abandonnée (la personne y renonce), à tout moment."""
        drafts: list[Draft[Any]] = []
        tz = frame.env.tz_of(frame.root)
        reminders = reminders_of(frame, store)
        for pr in ex.promesses:
            if not fresh(c.PROMISE, pr.texte):
                continue
            to = people.one(pr.envers) or (conv.persons[0] if len(conv.persons) == 1 else None)
            if to is None:
                continue
            if await self._already_promised(store, vectors, frame, to, pr.texte, p):
                continue
            got = x.when(pr.echeance, tz)
            due, all_day = got if got is not None else (None, False)
            if any(r.owner == to and same_task(pr.texte, r.title) and same_day(frame, due, r.due)
                   for r in reminders):
                continue  # le rappel est programmé (goal_remind) : il le portera, pas une promesse de plus
            if due is not None and all_day:
                # un jour sans heure : dû jusqu'au soir (quelqu'un qu'elle ne voit qu'à 19 h l'entend quand même)
                due = _at(frame, due, p.promise_day_end_min)
            implicit = due is None
            if due is None:
                due = frame.now + round(p.promise_horizon_days * DAY)
            sources, _told, _cited = provenance(pr.messages)
            sens = int(Sensitivity.CONFIDENCE if secretive(pr.texte) else Sensitivity.PERSONAL)
            drafts.append(c.PROMISE_NOTICED.draft(
                text=Content.of(pr.texte, level=sens), to=to, due=due, sensitivity=sens, sources=sources,
                call_id=call_id, implicit_due=implicit, all_day=all_day))
        pending_ids = {i for i, _, _ in promises}
        said_at = max((ln.at for ln in conv.lines if ln.person is None), default=frame.now)
        for done in ex.promesses_tenues:
            if done.id not in pending_ids:
                continue
            status = c.HONORED if fold(done.statut).startswith("tenu") else c.DROPPED
            pending = state.promises.get(done.id)
            if status == c.HONORED and pending is not None and kept_too_early(pending, said_at, frame):
                continue  # la veille, « demain je te le rappelle » ne la tient pas : elle part le jour dit
            drafts.append(c.PROMISE_RESOLVED.draft(promise=done.id, status=status))
        return drafts

    async def _already_promised(self, store: Any, vectors: Any, frame: Frame, to: str, text: str,
                                p: MemoryParams) -> bool:
        pending = [pr.id for pr in frame.get(c.PROMISES_TO(to))]
        if not pending:
            return False
        if vectors is not None:
            hits = await vectors.search(text, 1, kinds={c.PROMISE}, keys=pending)
            if hits and hits[0][1] >= p.dedup_similarity:
                return True
        marks = ",".join("?" * len(pending))
        mine = stems(text)
        return any(len(mine & stems(t)) >= max(2, (len(mine) + 1) // 2) for (t,) in store.query_mind(
            f"SELECT text FROM {c.ITEMS_TABLE} WHERE id IN ({marks})", tuple(pending)))

    async def _events(self, ex: x.Extraction, frame: Frame, state: MemoryState, store: Any, conv: x.Conversation,
                      people: x.People, vectors: Any, p: MemoryParams, provenance: Any, concerned: Any,
                      secret_of: Any, heard: tuple[str, ...], fresh: Any, call_id: str,
                      moments: dict[int, c.LifeEvent] | None = None) -> list[Draft[Any]]:
        """Ce qui va arriver dans la vie de quelqu'un : daté, à venir ; ou une
        situation qui dure (depuis quand). Le même moment redit ne se note pas
        deux fois ; une date qui change remplace. Avec ce qu'il pèse (ce qui
        compte : un entretien, un examen), s'il se fête (un anniversaire) et
        s'il revient chaque année — alors même passé, il se note (« c'était mon
        anniv hier »). Une chose à faire n'en est pas un : « rappelle-moi de
        prendre rendez-vous chez le dentiste » est une promesse, pas « son
        rendez-vous chez le dentiste » dont on prendrait des nouvelles."""
        drafts: list[Draft[Any]] = []
        tz = frame.env.tz_of(frame.root)
        tasks = self._tasks(ex, frame, conv, people, store)
        # « son anniversaire » et « l'anniversaire de Sam », le même samedi : un seul moment (sonde du 2026-10-03)
        names = [*(sp.name for sp in conv.speakers), self_c.name_of(frame.get(self_c.PERSONA))]
        noted: list[tuple[str, int, tuple[str, ...]]] = []
        for ev in ex.evenements:
            # une date floue garde sa précision : « en novembre » n'est pas le 1er novembre (ADR 0084)
            span = timespan.parse(ev.quand, tz)
            if (span is None and not ev.en_cours) or not fresh(c.EVENT, ev.texte):
                continue
            at, all_day = (span.point, span.all_day) if span is not None else (frame.now, True)
            until, precision = (span.end, span.precision) if span is not None and span.vague else (None, "")
            yearly = x.yearly(ev) and not precision
            if ev.en_cours:
                # Conserver sa véritable ancienneté, même lorsqu'elle n'est plus relancée spontanément.
                at = min(at, frame.now)
            elif (until or at) < frame.now - DAY and not yearly:
                continue  # du passé : ce n'est plus à suivre (ce qui revient chaque année, si : il reviendra)
            if ev.sur_elle and not people.resolve(ev.personnes):
                # elle n'a pas de corps : « je vais au cinéma samedi », dit par elle, n'est pas un moment de sa vie —
                # ce qu'elle vit, elle le vit à travers les autres (un moment partagé, ADR 0084)
                continue
            if not ev.en_cours and (x.task_words(ev.texte) or any(
                    (not seqs or not ev.messages or set(seqs) & set(ev.messages)) and same_task(ev.texte, text)
                    and same_day(frame, at, due) for text, seqs, due in tasks)):
                continue  # une chose à faire (une promesse, un rappel), pas un moment de sa vie
            sources, told_by, cited = provenance(ev.messages)
            world = bool(ev.monde)
            if world and not told_by:
                continue  # un moment du monde est toujours dit par quelqu'un (on peut l'oublier avec lui)
            # le monde n'est la vie de personne : un nom qu'on y lit ne devient pas une mention
            about = () if world else concerned(ev.personnes)
            sens = max(x.sensitivity(ev.sensibilite, has_person=not world), int(Sensitivity.ANODYNE))
            nature = (lk.OFFICIAL if ev.date_officielle else
                      lk.FIRST_HAND if told_by and about and set(told_by) <= set(about) else lk.REPORTED)
            # ce qu'elle a vu de qui l'annonce : reporté, annulé trop souvent, moins sûr (ADR 0086)
            track = state.track.get(told_by[0]) if len(told_by) == 1 else None
            extra = dict(until=until, precision=precision, scope=c.WORLD if world else c.PERSON_SCOPE,
                         shared=bool(ev.partage or ev.sur_elle) and not world, official=bool(ev.date_officielle),
                         likelihood=lk.likelihood(nature, ev.probabilite, p, track))
            if any(set(a) & set(about) and same_day(frame, t, at) and x.same_moment(ev.texte, n, names)
                   for n, t, a in noted):
                continue  # dit deux fois dans la même conversation
            moved = (moments or {}).get(ev.remplace) if ev.remplace is not None and not ev.en_cours else None
            if moved is not None:
                # la relecture désigne le moment qu'il déplace (ADR 0076) : le même, à sa nouvelle date — il en garde
                # le secret, la sensibilité et le poids, et l'ancien ne reste pas à côté
                noted.append((ev.texte, at, about))
                sens = max(sens, moved.sensitivity)
                drafts += self._moved(moved, at, frame, told_by, sources, call_id)
                drafts.append(c.EVENT_NOTED.draft(
                    text=Content.of(ev.texte, level=sens), when=at, about=tuple(dict.fromkeys((*about, *moved.about))),
                    all_day=all_day, sensitivity=sens, sources=sources, told_by=told_by, heard_by=heard,
                    secret=moved.secret or secret_of(ev.secret, cited, sens, ev.texte), replaces=moved.id,
                    call_id=call_id, ongoing=False, importance=max(moved.importance, x.moment_importance(ev)),
                    festive=moved.festive or x.festive(ev), yearly=yearly,
                    felt=facets(ev.ressenti) or moved.felt,
                    empathy=facets(ev.mon_ressenti) or moved.empathy, **{**extra, "shared": extra["shared"] or moved.shared}))
                continue
            back = (moments or {}).get(ev.remplace) if ev.remplace is not None and ev.en_cours else None
            if back is not None and not (back.ongoing and back.ended_at):
                back = None  # une situation encore en cours, ou un moment à venir : rien ne revient
            twin = None if back is not None else await self._same_event(store, state, vectors, ev.texte, about, p,
                                                                         frame=frame, at=at, names=names)
            # désignée par la relecture (« il est de nouveau malade », parmi les situations finies depuis peu), ou
            # reconnue à ses mots
            again = back if back is not None else self._ended_twin(store, state, ev.texte, about, p, frame, names) \
                if ev.en_cours and twin is None else None
            if again is not None:
                # « il est de nouveau malade » : la même situation, une autre fois — le même fil (ADR 0079)
                noted.append((ev.texte, at, about))
                sens = max(sens, again.sensitivity)
                drafts.append(c.EVENT_NOTED.draft(
                    text=Content.of(ev.texte, level=sens), when=at, about=tuple(dict.fromkeys((*about, *again.about))),
                    all_day=all_day, sensitivity=sens, sources=sources, told_by=told_by, heard_by=heard,
                    secret=again.secret or secret_of(ev.secret, cited, sens, ev.texte), recurs=again.id,
                    call_id=call_id, ongoing=True, importance=max(again.importance, x.moment_importance(ev)),
                    felt=facets(ev.ressenti) or again.felt,
                    empathy=facets(ev.mon_ressenti) or again.empathy, **extra))
                continue
            if twin is not None and not ev.en_cours and abs(twin.when - at) >= DAY // 2 and not x.same_moment(
                    ev.texte, store.content([twin.text_ref]).get(twin.text_ref) or "", names):
                # à une autre date, une ressemblance ne suffit pas à dire « reporté » : il faut les mêmes mots (« son
                # examen de maths » n'est pas « son examen de physique », audit du 2026-10-08) — sinon le nouveau
                # moment effacerait l'autre ; deux moments notés valent mieux qu'un moment perdu
                twin = None
            if twin is not None and (ev.en_cours or abs(twin.when - at) < DAY // 2):
                if not (told_by and set(told_by) <= set(about) and not set(twin.told_by) <= set(twin.about)):
                    continue  # déjà noté (une situation redite dure toujours : rien à changer)
                # un tiers l'avait annoncé, la personne le lui dit elle-même : le même moment, de première main
                # (ses vœux, son encouragement, « alors ? » ne se font jamais sur la foi d'un tiers)
                noted.append((ev.texte, twin.when, about))
                drafts.append(c.EVENT_NOTED.draft(
                    text=Content.of(ev.texte, level=max(sens, twin.sensitivity)), when=twin.when,
                    about=tuple(dict.fromkeys((*about, *twin.about))),
                    all_day=twin.all_day, sensitivity=max(sens, twin.sensitivity), sources=sources, told_by=told_by,
                    heard_by=heard, secret=twin.secret or secret_of(ev.secret, cited, sens, ev.texte),
                    replaces=twin.id, call_id=call_id, ongoing=twin.ongoing,
                    importance=max(twin.importance, x.moment_importance(ev)),
                    festive=twin.festive or (not twin.ongoing and x.festive(ev)),
                    yearly=twin.yearly or (not twin.ongoing and yearly),
                    felt=facets(ev.ressenti) or twin.felt,
                    empathy=facets(ev.mon_ressenti) or twin.empathy,
                    **{**extra, "until": twin.until or None, "precision": twin.precision,
                       "shared": extra["shared"] or twin.shared}))
                continue
            noted.append((ev.texte, at, about))
            if twin is not None:
                drafts += self._moved(twin, at, frame, told_by, sources, call_id)
            drafts.append(c.EVENT_NOTED.draft(
                text=Content.of(ev.texte, level=sens), when=at, about=about, all_day=all_day, sensitivity=sens,
                sources=sources, told_by=told_by, heard_by=heard, secret=secret_of(ev.secret, cited, sens, ev.texte),
                replaces=twin.id if twin is not None else None, call_id=call_id, ongoing=ev.en_cours,
                importance=x.moment_importance(ev), festive=not ev.en_cours and x.festive(ev), yearly=yearly,
                felt=facets(ev.ressenti), empathy=facets(ev.mon_ressenti), **extra))
        return drafts

    @staticmethod
    def _tasks(ex: x.Extraction, frame: Frame, conv: x.Conversation, people: x.People,
               store: Any) -> list[tuple[str, tuple[int, ...], int | None]]:
        """Les choses à faire de cette conversation (texte, messages cités, échéance) : ses promesses, et les
        rappels programmés pendant qu'elle avait lieu pour une de ses personnes."""
        tz = frame.env.tz_of(frame.root)
        out: list[tuple[str, tuple[int, ...], int | None]] = []
        for pr in ex.promesses:
            got = x.when(pr.echeance, tz)
            out.append((pr.texte, tuple(pr.messages), got[0] if got else None))
        persons = set(conv.persons)
        start = min((ln.at for ln in conv.lines), default=frame.now)
        end = max((ln.at for ln in conv.lines), default=frame.now) + 10 * MINUTE
        out += [(r.title, (), r.due) for r in reminders_of(frame, store)
                if r.owner in persons and start <= r.opened_at <= end]
        return out

    @staticmethod
    def _ended_twin(store: Any, state: MemoryState, text: str, about: tuple[str, ...], p: MemoryParams,
                    frame: Frame, names: Sequence[str]) -> c.LifeEvent | None:
        """Une situation finie depuis peu (``recurrence_days``) que ce texte redit : elle recommence. Les mêmes mots
        une fois les prénoms ôtés, ou assez de radicaux en commun."""
        since = frame.now - round(p.recurrence_days * DAY)
        archive = {ev.id: ev for ev in for_people(store, about)}
        ended = [ev for ev in {**state.events, **archive}.values()
                 if ev.ongoing and ev.ended_at and ev.ended_at >= since and set(ev.about) & set(about)]
        if not ended:
            return None
        said = store.content([ev.text_ref for ev in ended if ev.text_ref])
        wanted = stems(text)
        for ev in sorted(ended, key=lambda ev: -ev.ended_at):
            before = said.get(ev.text_ref) or ""
            if x.same_moment(text, before, names) or \
                    len(wanted & stems(before)) >= max(2, (len(wanted) + 1) // 2):
                return ev
        return None

    async def _same_event(self, store: Any, state: MemoryState, vectors: Any, text: str, about: tuple[str, ...],
                          p: MemoryParams, *, frame: Frame | None = None, at: int | None = None,
                          names: Sequence[str] = ()) -> c.LifeEvent | None:
        """Le moment déjà noté que ce texte redit : presque les mêmes mots (vecteurs, radicaux) — ou, le même jour
        pour la même personne, les mêmes mots une fois les prénoms ôtés (« son anniversaire » est « l'anniversaire
        de Sam »). Une date qui revient chaque année se compare à son occurrence de ce jour-là."""
        archive = {ev.id: ev for ev in for_people(store, about)}
        # une situation finie n'est plus à redire : « il est de nouveau malade » en ouvre une autre (une récidive),
        # qui sinon passait pour déjà notée (audit du 2026-10-08)
        mine = [ev for ev in {**state.events, **archive}.values() if set(ev.about) & set(about) and not ev.ended_at]
        if not mine:
            return None
        if frame is not None and at is not None:
            mine = [occurrence(ev, at, frame.env.tz_of(frame.root), p) for ev in mine]
        if frame is not None and at is not None:
            day = [ev for ev in mine if not ev.ongoing and same_day(frame, ev.when, at) and ev.text_ref]
            said = store.content([ev.text_ref for ev in day]) if day else {}
            for ev in day:
                if x.same_moment(text, said.get(ev.text_ref) or "", names):
                    return ev
        if vectors is not None:
            hits = await vectors.search(text, 1, kinds={c.EVENT}, keys=[ev.id for ev in mine])
            if hits and hits[0][1] >= p.dedup_similarity:
                return next((ev for ev in mine if ev.id == hits[0][0]), None)
        texts = store.content([ev.text_ref for ev in mine if ev.text_ref])
        wanted = stems(text)
        for ev in mine:
            if len(wanted & stems(texts.get(ev.text_ref) or "")) >= max(2, (len(wanted) + 1) // 2):
                return ev
        return None

    async def _twin(self, store: Any, vectors: Any, text: str, kind: str, about: tuple[str, ...],
                    p: MemoryParams, *, told_by: tuple[str, ...] = (), heard_by: tuple[str, ...] = (),
                    knowledge_kind: str = "claim", holder: str | None = None, about_self: bool = False) -> int | None:
        """Doublon exact indexé, sans dépendre des cinq voisins vectoriels les plus proches. Un souvenir : le même,
        confié et entendu par les mêmes. Une croyance : **la même proposition**, quel qu'en soit le témoin — ce
        qu'un autre lui en dira sera un témoignage de plus (ADR 0080) ; un avis ou une hypothèse restent à qui les
        porte ; la plus ancienne."""
        if kind == c.BELIEF:
            rows = store.query_mind(
                f"SELECT id, text, knowledge_kind, holder FROM {c.ITEMS_TABLE} WHERE fingerprint=? AND kind=? "
                "AND status='active' AND about=? AND (about_self > 0) = ? ORDER BY id",
                (fingerprint(text), kind, json.dumps(sorted(set(about)), ensure_ascii=False), about_self))
            for k, previous, nature, owner in rows:
                if same_words(previous, text) and nature == knowledge_kind \
                        and (knowledge_kind == "claim" or (owner or None) == (holder or None)):
                    return int(k)
            return None
        encoded = tuple(json.dumps(sorted(set(keys)), ensure_ascii=False) for keys in (about, told_by, heard_by))
        rows = store.query_mind(
            f"SELECT id, text FROM {c.ITEMS_TABLE} WHERE fingerprint=? AND kind=? "
            "AND status='active' AND about=? AND told_by=? AND heard_by=? ORDER BY id", (fingerprint(text), kind, *encoded))
        for k, previous in rows:
            if same_words(previous, text):
                return int(k)
        return None

    @staticmethod
    def _target_of(store: Any, item: int | None, nature: str, holder: str | None, *,
                   about_self: bool = False) -> int | None:
        """La croyance qu'une correction désigne, si elle peut l'être (ADR 0081) : vivante, de même sorte (sur elle,
        ou pas). L'audience n'y est pour rien — qui l'a entendue ne décide pas de ce qui est vrai. Un avis ou un goût
        d'un autre porteur ne se corrige pas : deux avis, deux porteurs, aucun n'a tort."""
        if item is None:
            return None
        rows = store.query_mind(f"SELECT knowledge_kind, holder, about_self FROM {c.ITEMS_TABLE} "
                                "WHERE id=? AND kind=? AND status='active'", (item, c.BELIEF))
        if not rows:
            return None
        kind, owner, self_item = rows[0]
        if bool(self_item) != about_self:
            return None
        personal = {"opinion", "preference"}
        if not about_self and (kind in personal or nature in personal) and (owner or None) != (holder or None):
            return None
        return item

    @staticmethod
    def _testimonies(store: Any, item: int | None) -> list[Testimony]:
        if item is None:
            return []
        return [testimony_of(r) for r in store.query_mind(
            f"SELECT {','.join(TESTIMONY_COLUMNS)} FROM {TESTIMONIES_TABLE} WHERE item=? ORDER BY seq", (item,))]

    @staticmethod
    def _former_twin(store: Any, text: str, about: tuple[str, ...], nature: str, holder: str | None) -> int | None:
        """Une croyance qu'elle a cessé de croire (remplacée), aux mêmes mots : redite, elle revient."""
        rows = store.query_mind(
            f"SELECT id, text, knowledge_kind, holder FROM {c.ITEMS_TABLE} WHERE fingerprint=? AND kind=? "
            "AND status='superseded' AND about=? AND about_self=0 ORDER BY id DESC",
            (fingerprint(text), c.BELIEF, json.dumps(sorted(set(about)), ensure_ascii=False)))
        for k, previous, kind, owner in rows:
            if same_words(previous, text) and kind == nature and (nature == "claim" or (owner or None) == (holder or None)):
                return int(k)
        return None

    @staticmethod
    def _head_of(store: Any, item: int) -> int | None:
        """Ce qui l'a remplacée, de remplacement en remplacement, jusqu'à ce qu'elle croit maintenant."""
        seen: set[int] = set()
        current: int | None = item
        while current is not None and current not in seen and len(seen) < 16:
            seen.add(current)
            rows = store.query_mind(f"SELECT status, superseded_by FROM {c.ITEMS_TABLE} WHERE id=?", (current,))
            if not rows:
                return None
            status, after = rows[0]
            if status == "active":
                return current if current != item else None
            current = after
        return None

    @staticmethod
    def _predictions(ex: x.Extraction, frame: Frame, conv: x.Conversation, people: x.People, p: MemoryParams,
                     call_id: str, fresh: Any, provenance: Any, concerned: Any, secret_of: Any, from_her: Any,
                     lied: Any, heard: tuple[str, ...], tz: Any) -> list[Draft[Any]]:
        """Ce que quelqu'un s'attend à voir arriver (« Léa pense qu'elle sera prise », « les taux vont remonter ») :
        une croyance de la sorte « prévision », à qui la porte, avec quand c'est attendu et à quel point (ADR 0084) —
        au plus comme une déduction, quoi qu'en dise qui prévoit. Ses propres pronostics sont à elle (ses avis sont
        libres, sur tout) ; une prévision ne revient plus d'elle-même une fois sa période passée."""
        drafts: list[Draft[Any]] = []
        for pv in ex.previsions:
            if not fresh(c.BELIEF, pv.texte):
                continue
            span = timespan.parse(pv.quand, tz)
            if span is not None and span.end < frame.now:
                continue  # déjà passé : ce n'est plus une prévision
            sources, told_by, cited = provenance(pv.messages)
            mine = pv.sur_elle and from_her(pv.messages)
            if mine and lied(pv.messages):
                continue  # un pronostic qu'elle a dit en mentant n'est pas ce qu'elle attend
            about = () if mine else concerned(pv.personnes)
            holder = None if mine else (people.one(pv.point_de_vue) if pv.point_de_vue else
                                        (told_by[0] if len(told_by) == 1 else None))
            sens = max(x.sensitivity(pv.sensibilite, has_person=bool(about or told_by)), int(Sensitivity.ANODYNE))
            secret = secret_of(pv.secret, cited, sens, pv.texte)
            expected = dict(expected=span.point, expected_until=span.end if span.vague else None,
                            expected_precision=span.precision) if span is not None else {}
            drafts.append(c.BELIEVED.draft(
                text=Content.of(pv.texte, level=sens), about=about, sensitivity=sens, importance=x.IMPORTANCE[2],
                confidence=x.born_confidence(0.7, c.TOLD if told_by else c.OBSERVED, "prediction"),
                origin=c.OBSERVED if mine else c.TOLD, source=None if mine else holder, sources=sources,
                call_id=call_id, told_by=() if mine else told_by, heard_by=heard, secret=secret, about_self=mine,
                knowledge_kind="prediction", holder=holder, felt=facets(pv.ressenti), empathy=facets(pv.mon_ressenti),
                likelihood=lk.likelihood(lk.PREDICTION, pv.probabilite, p),
                valid_until=span.end if span is not None else None, **expected))
        return drafts

    @staticmethod
    def _about_of(store: Any, item: int) -> list[str]:
        """Qui une croyance concerne (lu par son identifiant)."""
        rows = store.query_mind(f"SELECT about FROM {c.ITEMS_TABLE} WHERE id=?", (item,))
        return _keys(rows[0][0]) if rows else []

    @staticmethod
    def _closed_souvenirs(frame: Frame, store: Any, conv: x.Conversation, items: Sequence[int]) -> list[Draft[Any]]:
        """Ce que la discrétion demandée ferme aussi : les souvenirs nés des mêmes mots de qui la demande. La relecture
        ne voit que les croyances déjà connues ; le souvenir de la même confidence (« Alice m'a dit qu'elle quittait sa
        boîte »), noté avant le « garde-le pour toi », restait dicible à toute amie, et nourrissait le portrait (sonde
        réelle du 2026-10-09). Une autre croyance née du même message ne se ferme pas : la relecture la voit, et la
        désigne si elle laisse deviner le secret."""
        if not items:
            return []
        marks = ",".join("?" * len(items))
        cited = {int(m) for (raw,) in store.query_mind(f"SELECT sources FROM {c.ITEMS_TABLE} WHERE id IN ({marks})",
                                                       tuple(items)) for m in _keys(raw)}
        if not cited:
            return []
        askers = set(conv.persons)
        marks = ",".join("?" * len(cited))
        theirs = sorted(int(i) for i, who in store.query_mind(
            f"SELECT id, person FROM {transcript_c.THREAD_TABLE} WHERE role='user' AND id IN ({marks})",
            tuple(sorted(cited))) if who and (frame.get(identity_c.PERSON(who)) or who) in askers)
        if not theirs:
            return []
        marks = ",".join("?" * len(theirs))
        found = store.query_mind(
            f"SELECT DISTINCT i.id FROM {c.ITEMS_TABLE} i, json_each(i.sources) j WHERE i.kind=? AND "
            f"i.status='active' AND i.secret=0 AND j.value IN ({marks}) ORDER BY i.id", (c.SOUVENIR, *theirs))
        return [c.REINFORCED.draft(item=int(i), secret=True, sensitivity=int(Sensitivity.CONFIDENCE)) for (i,) in found]


@dataclass(frozen=True, slots=True)
class Forecast:
    """Une prévision passée qu'on n'a pas encore constatée (ADR 0099) : l'élément, qui elle concerne, qui la portait
    (vide : la sienne), ce qu'elle en attendait, ce qu'elle compte, qui peut la constater, comment on l'attendait."""

    item: int
    about: tuple[str, ...]
    holder: str
    likelihood: float | None
    importance: float
    concerned: tuple[str, ...]
    felt: tuple[tuple[str, float], ...]


def _facets_of(raw: Any) -> tuple[tuple[str, float], ...]:
    """Des facettes gardées en JSON (« [["sad", 0.6]] ») ; illisibles : aucune."""
    try:
        return facets(json.loads(raw or "[]"))
    except (TypeError, ValueError):
        return ()


@dataclass(frozen=True, slots=True)
class Reminder:
    """Un rappel programmé (un but ``goals`` vivant, de la sorte ``reminder``) : à qui, quoi, pour quand."""

    id: int
    owner: str
    title: str
    due: int | None
    opened_at: int


def reminders_of(frame: Frame, store: Any) -> list[Reminder]:
    """Les rappels programmés en cours (``goals.LIVE``), avec leur texte."""
    live = [g for g in frame.get(goals_c.LIVE) if g.kind == goals_c.REMINDER and g.owner and g.title_ref]
    if not live or store is None:
        return []
    texts = store.content([g.title_ref for g in live])
    return [Reminder(g.id, g.owner, texts.get(g.title_ref) or "", g.due, g.opened_at) for g in live
            if texts.get(g.title_ref)]


def _whom(frame: Frame, state: MemoryState, promise: int, label: str) -> str:
    """À qui, et pour quand (une promesse datée) : le modèle voit qu'elle n'est due que ce jour-là."""
    pr = state.promises.get(promise)
    if pr is None or pr.due is None or pr.implicit_due:
        return label
    due = frame.local(pr.due)
    if pr.all_day:
        return phrase("memory.extraction.due_day", label=label, day=x.day_words(due.date()))
    return phrase("memory.extraction.due_time", label=label, day=x.day_words(due.date()), time=f"{due:%H:%M}")


def same_day(frame: Frame, a: int | None, b: int | None) -> bool:
    """Le même jour (heure locale) — ou l'un des deux sans date : rien ne les distingue."""
    return a is None or b is None or frame.local(a).date() == frame.local(b).date()


def _at(frame: Frame, t: int, minutes: int) -> int:
    """Ce jour-là (heure locale), à cette heure (minutes depuis minuit)."""
    return instant(datetime.combine(frame.local(t).date(), time(minutes // 60 % 24, minutes % 60),
                                    tzinfo=frame.env.tz_of(frame.root)))


@MEMORY.process("memory.promises", wake_on=[c.PROMISE_NOTICED, c.PROMISE_RESOLVED, rt.UTTERANCE,
                                             goals_c.GOAL_OPENED],
                lane="background", catch_up=CatchUp.ONCE, max_quantum_s=3600)
class LetGo:
    """Une promesse qu'elle vient de tenir en le disant (l'initiative qui la tenait a parlé) est réglée : tenue.
    Une promesse ni tenue ni abandonnée s'abandonne quelques jours après son
    échéance : elle y a repensé (l'attention le lui a rappelé), puis elle laisse filer. Un rappel programmé
    ensuite pour la même chose (« à 9 h, stp » : l'outil ``goal_remind``) la porte désormais : la promesse lui
    laisse la place (un rappel demandé existe une fois et une seule)."""

    def __init__(self) -> None:
        #: les rappels programmés déjà confrontés aux promesses
        self.seen: set[int] = set()

    def _due(self, state: MemoryState, p: MemoryParams) -> list[tuple[int, int]]:
        grace = round(p.promise_drop_days * DAY)
        return sorted((pr.due + grace, pr.id) for pr in state.promises.values() if pr.due is not None)

    def _fresh_reminders(self, state: MemoryState, frame: Frame) -> bool:
        owners = {frame.get(identity_c.PERSON(pr.to)) or pr.to for pr in state.promises.values()}
        return any(g.kind == goals_c.REMINDER and g.owner in owners and g.id not in self.seen
                   for g in frame.get(goals_c.LIVE))

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        if any(k in state.promises for k in state.kept) or self._fresh_reminders(state, frame):
            return frame.now
        due = self._due(state, params(frame.env.params_of("memory", frame.root)))
        return max(frame.now, due[0][0]) if due else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: MemoryState = ctx.state
        p = params(frame.env.params_of("memory", frame.root))
        kept = [k for k in state.kept if k in state.promises]
        drafts = [c.PROMISE_RESOLVED.draft(promise=pid, status=c.HONORED, by=c.KEPT_BY,
                                           dedupe_key=f"promesse-tenue:{pid}") for pid in kept]
        drafts += [c.PROMISE_RESOLVED.draft(promise=pid, status=c.DROPPED, by=c.EXPIRED_BY,
                                            dedupe_key=f"promesse-abandonnée:{pid}")
                   for at, pid in self._due(state, p) if at <= frame.now and pid not in kept]
        done = {d.data.promise for d in drafts}
        drafts += [c.PROMISE_RESOLVED.draft(promise=pid, status=c.DROPPED, by=c.REMINDER_BY,
                                            dedupe_key=f"promesse-rappel:{pid}")
                   for pid in self._carried(ctx.ports.get("store"), state, frame) if pid not in done]
        if drafts:
            await ctx.emit(*drafts)

    def _carried(self, store: Any, state: MemoryState, frame: Frame) -> list[int]:
        """Les promesses qu'un rappel programmé après elles porte désormais : la même chose, pour la même
        personne, le même jour."""
        self.seen = {g.id for g in frame.get(goals_c.LIVE) if g.kind == goals_c.REMINDER}
        reminders = reminders_of(frame, store)
        pending = [pr for pr in state.promises.values() if pr.id not in state.kept]
        if not reminders or not pending or store is None:
            return []
        marks = ",".join("?" * len(pending))
        texts = dict(store.query_mind(f"SELECT id, text FROM {c.ITEMS_TABLE} WHERE id IN ({marks})",
                                      tuple(pr.id for pr in pending)))
        return sorted(pr.id for pr in pending if any(
            r.owner == (frame.get(identity_c.PERSON(pr.to)) or pr.to) and r.opened_at >= pr.at and same_task(texts.get(pr.id) or "", r.title)
            and same_day(frame, None if pr.implicit_due else pr.due, r.due) for r in reminders))


#: au plus tant de clés par requête ``IN (…)`` (SQLite en refuse au-delà de 32 766)
IN_MAX = 500
_CHUNK_COLUMNS = ("id", "person", "user_text", "reply_text", "room")


def _item_vector(r: dict[str, Any]) -> VectorItem:
    # qui l'a dit, tous témoins compris (ADR 0080) : ce qu'une personne lui a appris se retrouve avec elle
    people = {*_keys(r["about"]), *_keys(r["told_by"]), *_keys(r.get("informants"))}
    if r.get("holder"):
        people.add(r["holder"])
    return VectorItem(int(r["id"]), r["kind"], r["text"], tuple(sorted(people)))


def _chunk_vector(r: dict[str, Any]) -> VectorItem:
    """Un échange : en privé (``chunk``), retrouvé avec la personne ; dans un salon (``room_chunk``), dans ce salon
    seulement."""
    kind = c.CHUNK if r["room"] is None else c.ROOM_CHUNK
    return VectorItem(int(r["id"]), kind, f"{r['user_text']}\n{r['reply_text']}", (r["person"],))


def _by_ids(store: Any, table: str, columns: tuple[str, ...], ids: Sequence[int]) -> list[dict[str, Any]]:
    """Ces lignes, par paquets (jamais une liste ``IN`` sans borne)."""
    out: list[dict[str, Any]] = []
    for i in range(0, len(ids), IN_MAX):
        part = tuple(ids[i:i + IN_MAX])
        out += _rows(store, f"SELECT {','.join(columns)} FROM {table} WHERE id IN ({','.join('?' * len(part))}) "
                            "ORDER BY id", part, columns)
    return out


def forgets_of(store: Any) -> int:
    """Combien de fois la mémoire a oublié quelqu'un (``memory_forgets``)."""
    rows = store.query_mind(f"SELECT n FROM {c.FORGETS_TABLE}")
    return int(rows[0][0]) if rows else 0


@MEMORY.process("memory.index", wake_on=[*c.ALL, rt.UTTERANCE],
                lane="background", catch_up=CatchUp.ONCE, max_quantum_s=600)
class Index:
    """L'index des vecteurs (un cache) suit la mémoire : à chaque passage, ce qui est né depuis le précédent
    (``id > ?``, textes compris) ; au premier passage, et après un oubli (``memory_forgets`` a bougé), un
    rapprochement par les seuls identifiants — ce qui a disparu part, ce qui manque s'ajoute. Relire toute la
    mémoire, textes compris, à chaque énoncé coûtait 80 ms à cinquante mille éléments, sur la boucle (ADR 0059)."""

    def __init__(self) -> None:
        self.done: tuple[int, int, int] | None = None
        self.retry_at = 0
        #: les plus grands identifiants déjà confiés à l'index (éléments, échanges)
        self.upto = (0, 0)
        #: le compte d'oublis vu au dernier rapprochement
        self.forgets = 0
        self.revision = 0

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        if (state.items, state.chunks, state.index_revision) == self.done:
            return None
        return max(frame.now, self.retry_at)

    async def run(self, ctx: Any) -> None:
        state: MemoryState = ctx.state
        key = (state.items, state.chunks, state.index_revision)
        vectors, store = ctx.ports.get("vectors"), ctx.ports.get("store")
        if vectors is None or store is None:
            self.done = key
            return
        # si le plongement lève (modèle absent), pas de nouvel essai avant un moment : aucune rafale
        self.retry_at = ctx.frame.now + INDEX_RETRY_US
        forgets = forgets_of(store)
        first = self.done is None
        if first or forgets != self.forgets:
            todo, upto = await self._reconcile(vectors, store)
        else:
            todo, upto = self._fresh(store)
        if first:
            self.revision = int(store.query_mind("SELECT COALESCE(MAX(seq),0) FROM memory_changes")[0][0])
        changed = store.query_mind("SELECT item, seq FROM memory_changes WHERE seq>? ORDER BY seq", (self.revision,))
        if changed:
            rows = _by_ids(store, c.ITEMS_TABLE, ITEM_COLUMNS, [int(i) for i, _ in changed])
            active = [r for r in rows if r["status"] in ("active", "pending")]
            valid = {int(r["id"]) for r in active}
            await vectors.remove([int(i) for i, _ in changed if int(i) not in valid])
            todo = list({v.key: v for v in [*todo, *map(_item_vector, active)]}.values())
        for i in range(0, len(todo), BATCH):
            await vectors.upsert(todo[i:i + BATCH])
        self.upto, self.forgets, self.done = upto, forgets, key
        self.revision = max((int(seq) for _, seq in changed), default=self.revision)
        self.retry_at = 0

    def _fresh(self, store: Any) -> tuple[list[VectorItem], tuple[int, int]]:
        """Ce qui est né depuis le dernier passage."""
        items = _rows(store, f"SELECT {','.join(ITEM_COLUMNS)} FROM {c.ITEMS_TABLE} WHERE id > ? ORDER BY id",
                      (self.upto[0],), ITEM_COLUMNS)
        chunks = _rows(store, f"SELECT {','.join(_CHUNK_COLUMNS)} FROM {c.CHUNKS_TABLE} WHERE id > ? ORDER BY id",
                       (self.upto[1],), _CHUNK_COLUMNS)
        upto = (max([self.upto[0], *(int(r["id"]) for r in items)]),
                max([self.upto[1], *(int(r["id"]) for r in chunks)]))
        return [*map(_item_vector, (r for r in items if r["status"] in ("active", "pending"))),
                *map(_chunk_vector, chunks)], upto

    @staticmethod
    async def _reconcile(vectors: Any, store: Any) -> tuple[list[VectorItem], tuple[int, int]]:
        """Toute la mémoire, par ses identifiants : l'oubli efface des lignes, leurs vecteurs partent aussi (l'index
        n'est qu'un cache) ; ce qui manque (un index neuf, jeté) s'ajoute."""
        indexed = vectors.indexed()
        items = {int(r[0]) for r in store.query_mind(
            f"SELECT id FROM {c.ITEMS_TABLE} WHERE status IN ('active','pending')")}
        chunks = {int(r[0]) for r in store.query_mind(f"SELECT id FROM {c.CHUNKS_TABLE}")}
        gone = indexed - items - chunks
        remove = getattr(vectors, "remove", None)
        if gone and remove is not None:
            await remove(sorted(gone))
        todo = [*map(_item_vector, _by_ids(store, c.ITEMS_TABLE, ITEM_COLUMNS, sorted(items - indexed))),
                *map(_chunk_vector, _by_ids(store, c.CHUNKS_TABLE, _CHUNK_COLUMNS, sorted(chunks - indexed)))]
        return todo, (max(items, default=0), max(chunks, default=0))


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
