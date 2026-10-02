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
secret. Ce qui ressemble de très près à ce qu'elle sait déjà le **renforce**
(au plus sensible des deux) au lieu de faire un doublon ; une croyance n'est
corroborée que par quelqu'un qui ne l'avait pas encore dite. Tout part en un
seul ajout gardé par le point de contrôle, qui n'avance que sur un succès —
ou, après plusieurs échecs sur la même fenêtre, en le disant (``failed``).

**Indexer.** L'index des vecteurs est un cache : ce processus y ajoute ce
qui manque (éléments retenus, extraits d'échanges) et retire ce qui a
disparu (l'oubli efface des lignes).

**Laisser filer.** Une promesse que rien n'a réglée bien après son échéance
s'abandonne : rien ne reste dû pour toujours.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.memory import extraction as x
from mika.faculties.memory.faculty import MEMORY, MemoryParams, MemoryState, params
from mika.faculties.memory.projections import ITEM_COLUMNS, informants_of
from mika.kernel.clock import DAY, MINUTE
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.ports.llm import LLMRequest, Message
from mika.ports.vectors import VectorItem
from mika.vocab.affect import emotion_of
from mika.vocab.people import clean_display_name, fold, is_identifiable
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import WORD, stems

BATCH = 64
#: les croyances déjà connues montrées au modèle, au plus
KNOWN_SHOWN = 8
#: après un échec de l'indexation (un plongement absent), pas de nouvel essai avant
INDEX_RETRY_US = 5 * MINUTE


def _rows(store: Any, sql: str, params_: tuple[Any, ...], columns: tuple[str, ...]) -> list[dict[str, Any]]:
    return [dict(zip(columns, r, strict=True)) for r in store.query_mind(sql, params_)]


def _keys(raw: Any) -> list[str]:
    try:
        got = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(k) for k in got] if isinstance(got, list) else []


@MEMORY.process("memory.consolidate", wake_on=[rt.PERCEPTION_RECEIVED, rt.UTTERANCE, c.CONSOLIDATED],
                lane="background", catch_up=CatchUp.ONCE, max_quantum_s=600)
class Consolidate:
    def __init__(self) -> None:
        self.retry_at = 0
        self.attempts: dict[int, int] = {}
        #: rien de consolidable à ce ``seq`` (des questions attendent) : on attend un événement
        self.stuck_at: int | None = None
        #: ce qu'une conversation a déjà donné pendant une relecture qu'une autre a fait échouer :
        #: on ne repaie pas l'appel (clé : la conversation et ses messages)
        self.extracted: dict[tuple[str, tuple[int, ...]], tuple[x.Extraction, str, str]] = {}

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        if not state.pending or self.stuck_at == frame.seq:
            return None
        if state.pending[0] in set(frame.get(rt.AWAITING)):
            return None  # la plus ancienne question attend sa réponse : réveil par l'énoncé
        p = params(frame.env.params_of("memory", frame.root))
        if self.retry_at > frame.now:
            return self.retry_at
        if len(state.pending) >= p.min_messages:
            return frame.now
        return state.last_message_at + p.quiet_us

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: MemoryState = ctx.state
        store = ctx.ports.get("store")
        if store is None or ctx.llm is None or not state.pending:
            return
        p = params(frame.env.params_of("memory", frame.root))
        rows = store.query_mind(
            f"SELECT id, at, role, person, text, reply_to, room FROM {transcript_c.THREAD_TABLE} WHERE id>? "
            "ORDER BY id LIMIT ?", (state.checkpoint, p.max_window))
        rows = window(rows, set(frame.get(rt.AWAITING)))
        if not rows:
            self.stuck_at = frame.seq
            return
        self.stuck_at = None
        upto = rows[-1][0]
        directory = self._directory(frame, store)
        conversations = self._conversations(frame, rows, state, directory)
        vectors = ctx.ports.get("vectors")
        # si un appel lève, on ne réessaie pas avant le délai (aucune rafale)
        self.retry_at = frame.now + p.retry_us
        done: list[tuple[x.Conversation, x.People, list[tuple[int, str]], list[tuple[int, str, str]],
                         x.Extraction, str]] = []
        failures, model, last_call = 0, "", f"{ctx.run_id}#0"
        for n, conv in enumerate(conversations):
            people = x.People.of(conv.speakers, directory)
            known = await self._known_beliefs(store, vectors, conv, people, directory)
            promises = self._promises(store, state, conv)
            cached = self.extracted.get((conv.key, conv.seqs))
            if cached is None:
                labels = {s.person: s.label for s in conv.speakers}
                prompt = x.render(conv, now=frame.local(), beliefs=known,
                                  promises=[(i, labels.get(to, to), t) for i, to, t in promises])
                request = LLMRequest(role="extract", call_id=f"{ctx.run_id}#{n}", system_stable=x.SYSTEM,
                                     messages=(Message("user", prompt),), tools=(x.tool(),), max_tokens=2500,
                                     lane="background", priority=2,
                                     meta={"window": (rows[0][0], upto), "conversation": conv.key})
                response = await ctx.llm.call(request)
                extraction = x.parse(response)
                if extraction is None:
                    failures += 1
                    continue
                cached = self.extracted[(conv.key, conv.seqs)] = (extraction, response.model, request.call_id)
            extraction, model, last_call = cached
            done.append((conv, people, known, promises, extraction, last_call))
        if failures:
            # les essais se comptent par point de départ : la fin de la fenêtre bouge avec les messages
            start = state.checkpoint
            self.attempts[start] = self.attempts.get(start, 0) + 1
            if self.attempts[start] < p.max_attempts:
                return
        else:
            self.retry_at = 0
        drafts: list[Draft[Any]] = []
        for conv, people, known, promises, extraction, call_id in done:
            drafts += await self._drafts(extraction, frame, state, store, conv, people, known, promises, vectors,
                                         p, call_id)
        drafts.append(c.CONSOLIDATED.draft(upto=upto, produced=len(drafts), failed=bool(failures),
                                           call_id=last_call, model=model))
        self.attempts.pop(state.checkpoint, None)
        self.extracted.clear()
        await ctx.emit(*drafts, guard=Guard("point de contrôle", reads=(c.CHECKPOINT,)))

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

    def _conversations(self, frame: Frame, rows: list[tuple[Any, ...]], state: MemoryState,
                       directory: dict[str, tuple[str, ...]]) -> list[x.Conversation]:
        """Un fil privé par personne (toutes ses adresses), un salon d'un
        seul tenant. Dans un salon, ce qui ne lui était pas adressé ne compte
        que s'il nomme quelqu'un qu'elle connaît."""
        aside = set(state.unaddressed)
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
                    lines.append(x.Line(int(seq), int(at), "Mika", text))
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
        out = []
        for i, t, about, told_by, sens, secret in sorted(found, key=lambda r: order[int(r[0])]):
            concerns, tellers = set(_keys(about)), set(_keys(told_by))
            anodyne = int(sens) <= Sensitivity.ANODYNE and not secret
            if not (anodyne or (tellers <= persons and not conv.room)):
                continue
            if concerns and not concerns & (persons | named):
                continue
            out.append((int(i), t))
        return out[:KNOWN_SHOWN]

    def _promises(self, store: Any, state: MemoryState, conv: x.Conversation) -> list[tuple[int, str, str]]:
        """Les promesses en cours envers les personnes de cette conversation
        (des clés de personne : toutes leurs adresses comptent)."""
        persons = set(conv.persons)
        pending = [pr for pr in state.promises.values() if pr.to in persons]
        if not pending:
            return []
        ids = [pr.id for pr in pending]
        marks = ",".join("?" * len(ids))
        texts = dict(store.query_mind(f"SELECT id, text FROM {c.ITEMS_TABLE} WHERE id IN ({marks})", tuple(ids)))
        return [(pr.id, pr.to, texts.get(pr.id, "")) for pr in pending if texts.get(pr.id)]

    # ── ce qu'on en garde ──
    async def _drafts(self, ex: x.Extraction, frame: Frame, state: MemoryState, store: Any, conv: x.Conversation,
                      people: x.People, known: list[tuple[int, str]], promises: list[tuple[int, str, str]],
                      vectors: Any, p: MemoryParams, call_id: str) -> list[Draft[Any]]:
        drafts: list[Draft[Any]] = []
        known_ids = {i for i, _ in known}
        heard = conv.persons
        lines = {ln.seq: ln for ln in conv.lines}
        speaking = tuple(sorted({ln.person for ln in conv.lines if ln.person}))

        def provenance(cited: Sequence[int]) -> tuple[tuple[int, ...], tuple[str, ...], list[str]]:
            """Les messages d'où vient un élément, qui les a écrits (qui l'a
            confié) et leurs textes. Sans citation : toute la conversation, et
            tous ceux qui y ont parlé l'ont confié (dans le doute, on ferme)."""
            seqs = sorted({s for s in cited if s in lines})
            if not seqs:
                return conv.seqs, speaking, []
            persons = sorted({lines[s].person for s in seqs if lines[s].person})
            return tuple(seqs), tuple(str(k) for k in persons), [lines[s].text for s in seqs if lines[s].person]

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
        names = {st for sp in conv.speakers for st in stems(sp.name)} | {"mika"}
        secrets = self._secrets(store, conv)
        for item in (*ex.souvenirs, *ex.croyances, *ex.evenements):
            cited = provenance(item.messages)[2]
            sens = x.sensitivity(item.sensibilite, has_person=True)
            if asked_silence(item.secret, cited, sens):
                secrets.append(item.texte)

        def secret_of(flag: bool, cited: list[str], sens: int, text: str = "") -> bool:
            return asked_silence(flag, cited, sens) or (bool(text) and x.echoes(text, secrets, names))

        seen: set[tuple[str, str]] = set()  # le même élément deux fois dans un lot n'en fait qu'un

        def fresh(kind: str, text: str) -> bool:
            key = (kind, " ".join(fold(text).split()))
            if key in seen:
                return False
            seen.add(key)
            return True

        for s in ex.souvenirs:
            if not fresh(c.SOUVENIR, s.texte):
                continue
            if s.sur_elle:
                drafts += await self._about_self(s, store, vectors, p, provenance, call_id)
                continue
            about = concerned(s.personnes)
            sources, told_by, cited = provenance(s.messages)
            sens = x.sensitivity(s.sensibilite, has_person=bool(about or told_by))
            secret = secret_of(s.secret, cited, sens, s.texte)
            twin = await self._twin(store, vectors, s.texte, c.SOUVENIR, about, p)
            if twin is not None:
                drafts.append(c.REINFORCED.draft(item=twin, sources=sources, sensitivity=sens, about=about,
                                                 told_by=told_by, heard_by=heard, secret=secret))
                continue
            e = emotion_of(s.emotion)
            drafts.append(c.REMEMBERED.draft(
                text=Content.of(s.texte, level=sens), about=about, sensitivity=sens,
                importance=x.IMPORTANCE.get(s.importance, 0.45), emotion=e.value if e else None,
                sources=sources, call_id=call_id, told_by=told_by, heard_by=heard, secret=secret))
        for b in ex.croyances:
            if not fresh(c.BELIEF, b.texte):
                continue
            if b.sur_elle:
                drafts += await self._about_self(b, store, vectors, p, provenance, call_id)
                continue
            about = concerned(b.personnes)
            sources, told_by, cited = provenance(b.messages)
            source = people.one(b.source) if b.source else None
            sens = x.sensitivity(b.sensibilite, has_person=bool(about or told_by))
            secret = secret_of(b.secret, cited, sens, b.texte)
            replaces = b.remplace if b.remplace in known_ids else None
            twin = await self._twin(store, vectors, b.texte, c.BELIEF, about, p)
            if twin is not None and twin != replaces:
                new = set(informants_of(source, told_by))
                drafts.append(c.REINFORCED.draft(
                    item=twin, corroborated=bool(new - set(self._informants(store, twin))), source=source,
                    sources=sources, sensitivity=sens, about=about, told_by=told_by, heard_by=heard, secret=secret,
                    replaces=replaces))
                continue
            drafts.append(c.BELIEVED.draft(
                text=Content.of(b.texte, level=sens), about=about, sensitivity=sens,
                importance=x.IMPORTANCE.get(b.importance, 0.45), confidence=round(b.confiance, 3),
                origin=x.ORIGIN.get(fold(b.origine), "told"), source=source, replaces=replaces, sources=sources,
                call_id=call_id, told_by=told_by, heard_by=heard, secret=secret))
        for item in ex.confidentiel:
            if item in known_ids:
                drafts.append(c.REINFORCED.draft(item=item, sensitivity=int(Sensitivity.CONFIDENCE), secret=True))
        drafts += await self._promised(ex, frame, store, conv, people, promises, vectors, p, provenance, fresh,
                                       call_id, lambda text: x.echoes(text, secrets, names))
        drafts += await self._events(ex, frame, state, store, people, vectors, p, provenance, concerned, secret_of,
                                     heard, fresh, call_id)
        return drafts

    @staticmethod
    def _secrets(store: Any, conv: x.Conversation) -> list[str]:
        """Les secrets qu'elle garde déjà sur les personnes de cette conversation."""
        out: list[str] = []
        for person in conv.persons:
            like = f'%"{person}"%'
            out += [str(t) for (t,) in store.query_mind(
                f"SELECT text FROM {c.ITEMS_TABLE} WHERE secret=1 AND status='active' AND (about LIKE ? OR "
                "told_by LIKE ?) ORDER BY id DESC LIMIT 50", (like, like))]
        return out

    async def _about_self(self, b: x.XSouvenir | x.XCroyance, store: Any, vectors: Any, p: MemoryParams,
                          provenance: Any, call_id: str) -> list[Draft[Any]]:
        """Ce qu'elle a raconté d'elle-même : une note anodine, de peu
        d'importance, qui s'efface en quelques jours."""
        sources, _told, _cited = provenance(b.messages)
        twin = await self._twin(store, vectors, b.texte, c.BELIEF, (), p)
        if twin is not None:
            return [c.REINFORCED.draft(item=twin, sources=sources)]
        return [c.BELIEVED.draft(
            text=Content.of(b.texte, level=int(Sensitivity.ANODYNE)), about=(), sensitivity=int(Sensitivity.ANODYNE),
            importance=x.IMPORTANCE[1], confidence=round(getattr(b, "confiance", 0.7), 3), origin=c.OBSERVED,
            sources=sources,
            call_id=call_id, about_self=True)]

    async def _promised(self, ex: x.Extraction, frame: Frame, store: Any, conv: x.Conversation, people: x.People,
                        promises: list[tuple[int, str, str]], vectors: Any, p: MemoryParams, provenance: Any,
                        fresh: Any, call_id: str, secretive: Any) -> list[Draft[Any]]:
        """Ce qu'elle a promis : à une personne (toutes ses adresses), une seule
        fois (une promesse redite n'en fait pas deux), avec une échéance même
        quand rien n'a été dit — l'horizon d'une promesse vague. Une promesse
        qui laisse deviner un secret est aussi sensible qu'une confidence."""
        drafts: list[Draft[Any]] = []
        tz = frame.env.tz_of(frame.root)
        for pr in ex.promesses:
            if not fresh(c.PROMISE, pr.texte):
                continue
            to = people.one(pr.envers) or (conv.persons[0] if len(conv.persons) == 1 else None)
            if to is None:
                continue
            if await self._already_promised(store, vectors, frame, to, pr.texte, p):
                continue
            due = x.due(pr.echeance, tz)
            implicit = due is None
            if due is None:
                due = frame.now + round(p.promise_horizon_days * DAY)
            sources, _told, _cited = provenance(pr.messages)
            sens = int(Sensitivity.CONFIDENCE if secretive(pr.texte) else Sensitivity.PERSONAL)
            drafts.append(c.PROMISE_NOTICED.draft(
                text=Content.of(pr.texte, level=sens), to=to, due=due, sensitivity=sens, sources=sources,
                call_id=call_id, implicit_due=implicit))
        pending_ids = {i for i, _, _ in promises}
        for done in ex.promesses_tenues:
            if done.id in pending_ids:
                status = c.HONORED if fold(done.statut).startswith("tenu") else c.DROPPED
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

    async def _events(self, ex: x.Extraction, frame: Frame, state: MemoryState, store: Any, people: x.People,
                      vectors: Any, p: MemoryParams, provenance: Any, concerned: Any, secret_of: Any,
                      heard: tuple[str, ...], fresh: Any, call_id: str) -> list[Draft[Any]]:
        """Ce qui va arriver dans la vie de quelqu'un : daté, à venir. Le même
        moment redit ne se note pas deux fois ; une date qui change remplace."""
        drafts: list[Draft[Any]] = []
        tz = frame.env.tz_of(frame.root)
        for ev in ex.evenements:
            got = x.when(ev.quand, tz)
            if got is None or not fresh(c.EVENT, ev.texte):
                continue
            at, all_day = got
            if at < frame.now - DAY:
                continue  # du passé : ce n'est plus à suivre
            about = concerned(ev.personnes)
            sources, told_by, cited = provenance(ev.messages)
            sens = max(x.sensitivity(ev.sensibilite, has_person=True), int(Sensitivity.ANODYNE))
            twin = await self._same_event(store, state, vectors, ev.texte, about, p)
            if twin is not None and abs(twin.when - at) < DAY // 2:
                continue
            drafts.append(c.EVENT_NOTED.draft(
                text=Content.of(ev.texte, level=sens), when=at, about=about, all_day=all_day, sensitivity=sens,
                sources=sources, told_by=told_by, heard_by=heard, secret=secret_of(ev.secret, cited, sens, ev.texte),
                replaces=twin.id if twin is not None else None, call_id=call_id))
        return drafts

    async def _same_event(self, store: Any, state: MemoryState, vectors: Any, text: str, about: tuple[str, ...],
                          p: MemoryParams) -> c.LifeEvent | None:
        mine = [ev for ev in state.events.values() if set(ev.about) & set(about)]
        if not mine:
            return None
        if vectors is not None:
            hits = await vectors.search(text, 1, kinds={c.EVENT}, keys=[ev.id for ev in mine])
            if hits and hits[0][1] >= p.dedup_similarity:
                return state.events.get(hits[0][0])
        texts = store.content([ev.text_ref for ev in mine if ev.text_ref])
        wanted = stems(text)
        for ev in mine:
            if len(wanted & stems(texts.get(ev.text_ref) or "")) >= max(2, (len(wanted) + 1) // 2):
                return ev
        return None

    async def _twin(self, store: Any, vectors: Any, text: str, kind: str, about: tuple[str, ...],
                    p: MemoryParams) -> int | None:
        """Ce qui est déjà su, presque mot pour mot, **et toujours actif** (une
        croyance remplacée ne se renforce pas) — et qui concerne au moins une
        même personne (« Alice habite à Lyon » n'est pas « Bob habite à Lyon »)."""
        if vectors is None:
            return None
        hits = [(k, sim) for k, sim in await vectors.search(text, 5, kinds={kind}) if sim >= p.dedup_similarity]
        if not hits:
            return None
        marks = ",".join("?" * len(hits))
        rows = {int(i): (st, _keys(a)) for i, st, a in store.query_mind(
            f"SELECT id, status, about FROM {c.ITEMS_TABLE} WHERE id IN ({marks})", tuple(k for k, _ in hits))}
        for k, _sim in hits:
            status, theirs = rows.get(k, ("", []))
            if status != "active":
                continue
            if about and theirs and not set(about) & set(theirs):
                continue
            return k
        return None

    @staticmethod
    def _informants(store: Any, item: int) -> list[str]:
        """Qui le lui a déjà appris (lu par l'identifiant du jumeau, pas dans ce qu'on a montré au modèle)."""
        rows = store.query_mind(f"SELECT informants, source FROM {c.ITEMS_TABLE} WHERE id=?", (item,))
        if not rows:
            return []
        return _keys(rows[0][0]) or ([rows[0][1]] if rows[0][1] else [])


@MEMORY.process("memory.promises", wake_on=[c.PROMISE_NOTICED, c.PROMISE_RESOLVED], lane="background",
                catch_up=CatchUp.ONCE, max_quantum_s=3600)
class LetGo:
    """Une promesse ni tenue ni abandonnée s'abandonne quelques jours après son
    échéance : elle y a repensé (l'attention le lui a rappelé), puis elle laisse filer."""

    def _due(self, state: MemoryState, p: MemoryParams) -> list[tuple[int, int]]:
        grace = round(p.promise_drop_days * DAY)
        return sorted((pr.due + grace, pr.id) for pr in state.promises.values() if pr.due is not None)

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        due = self._due(state, params(frame.env.params_of("memory", frame.root)))
        return max(frame.now, due[0][0]) if due else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        p = params(frame.env.params_of("memory", frame.root))
        drafts = [c.PROMISE_RESOLVED.draft(promise=pid, status=c.DROPPED, by=c.EXPIRED_BY,
                                           dedupe_key=f"promesse-abandonnée:{pid}")
                  for at, pid in self._due(ctx.state, p) if at <= frame.now]
        if drafts:
            await ctx.emit(*drafts)


@MEMORY.process("memory.index", wake_on=[c.REMEMBERED, c.BELIEVED, c.PROMISE_NOTICED, c.EVENT_NOTED, rt.UTTERANCE],
                lane="background", catch_up=CatchUp.ONCE, max_quantum_s=600)
class Index:
    def __init__(self) -> None:
        self.done: tuple[int, int] | None = None
        self.retry_at = 0

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        if (state.items, state.chunks) == self.done:
            return None
        return max(frame.now, self.retry_at)

    async def run(self, ctx: Any) -> None:
        state: MemoryState = ctx.state
        key = (state.items, state.chunks)
        vectors, store = ctx.ports.get("vectors"), ctx.ports.get("store")
        if vectors is None or store is None:
            self.done = key
            return
        # si le plongement lève (modèle absent), pas de nouvel essai avant un moment : aucune rafale
        self.retry_at = ctx.frame.now + INDEX_RETRY_US
        indexed = vectors.indexed()
        items = _rows(store, f"SELECT {','.join(ITEM_COLUMNS)} FROM {c.ITEMS_TABLE}", (), ITEM_COLUMNS)
        chunks = _rows(store, f"SELECT id, person, user_text, reply_text FROM {c.CHUNKS_TABLE}", (),
                       ("id", "person", "user_text", "reply_text"))
        # l'oubli efface des lignes : leurs vecteurs partent aussi (l'index n'est qu'un cache)
        gone = indexed - {int(r["id"]) for r in items} - {int(r["id"]) for r in chunks}
        remove = getattr(vectors, "remove", None)
        if gone and remove is not None:
            await remove(sorted(gone))
        todo = [VectorItem(int(r["id"]), r["kind"], r["text"], tuple(sorted({*_keys(r["about"]),
                                                                               *_keys(r["told_by"])})))
                for r in items if int(r["id"]) not in indexed]
        todo += [VectorItem(int(r["id"]), c.CHUNK, f"{r['user_text']}\n{r['reply_text']}", (r["person"],))
                 for r in chunks if int(r["id"]) not in indexed]
        for i in range(0, len(todo), BATCH):
            await vectors.upsert(todo[i:i + BATCH])
        self.done = key
        self.retry_at = 0


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
