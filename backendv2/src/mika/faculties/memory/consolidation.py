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
corroborée que par quelqu'un qui ne l'avait pas encore dite. Une réplique
recopiée n'est pas un souvenir (la sienne jamais ; celle de la personne, citée
en disant qui parle), une banalité ne se garde pas, et comment la personne
l'appelle se retient même quand le modèle l'oublie (ADR 0055). La relecture
voit les situations en cours de ses personnes, avec leur numéro : une situation
que la personne dit finie (« on a fini le déménagement ») prend fin. Tout part en un
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
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any

from mika.contracts import goals as goals_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import transcript as transcript_c
from mika.faculties.memory import extraction as x
from mika.faculties.memory.faculty import MEMORY, MemoryParams, MemoryState, occurrence, params
from mika.faculties.memory.life import kept_too_early, same_task
from mika.faculties.memory.projections import ITEM_COLUMNS, informants_of
from mika.kernel.clock import DAY, MINUTE, instant
from mika.kernel.events import Content, Draft
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.ports.llm import LLMRequest, Message
from mika.ports.vectors import VectorItem
from mika.vocab.affect import emotion_of
from mika.vocab.people import clean_display_name, fold, is_identifiable
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import WORD, banal, stems

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
        her = self_c.name_of(frame.get(self_c.PERSONA))
        conversations = self._conversations(frame, rows, state, directory)
        vectors = ctx.ports.get("vectors")
        # si un appel lève, on ne réessaie pas avant le délai (aucune rafale)
        self.retry_at = frame.now + p.retry_us
        done: list[tuple[x.Conversation, x.People, list[tuple[int, str]], list[tuple[int, str, str]],
                         list[tuple[int, str, str]], x.Extraction, str]] = []
        failures, model, last_call = 0, "", f"{ctx.run_id}#0"
        for n, conv in enumerate(conversations):
            people = x.People.of(conv.speakers, directory, her)
            known = await self._known_beliefs(store, vectors, conv, people, directory)
            promises = self._promises(frame, store, state, conv)
            labels = {s.person: s.label for s in conv.speakers}
            situations = self._situations(frame, store, state, conv, p, labels)
            cached = self.extracted.get((conv.key, conv.seqs))
            if cached is None:
                prompt = x.render(conv, now=frame.local(), beliefs=known,
                                  promises=[(i, _whom(frame, state, i, labels.get(to, to)), t)
                                            for i, to, t in promises], situations=situations)
                request = LLMRequest(role="extract", call_id=f"{ctx.run_id}#{n}", system_stable=x.system(her),
                                     messages=(Message("user", prompt),), tools=(x.tool(her),), max_tokens=2500,
                                     lane="background", priority=2,
                                     meta={"window": (rows[0][0], upto), "conversation": conv.key})
                response = await ctx.llm.call(request)
                extraction = x.parse(response)
                if extraction is None:
                    failures += 1
                    continue
                cached = self.extracted[(conv.key, conv.seqs)] = (extraction, response.model, request.call_id)
            extraction, model, last_call = cached
            done.append((conv, people, known, promises, situations, extraction, last_call))
        if failures:
            # les essais se comptent par point de départ : la fin de la fenêtre bouge avec les messages
            start = state.checkpoint
            self.attempts[start] = self.attempts.get(start, 0) + 1
            if self.attempts[start] < p.max_attempts:
                return
        else:
            self.retry_at = 0
        drafts: list[Draft[Any]] = []
        for conv, people, known, promises, situations, extraction, call_id in done:
            drafts += await self._drafts(extraction, frame, state, store, conv, people, known, promises, vectors,
                                         p, call_id)
            drafts += self._ended(extraction, situations, call_id)
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
        for ev in sorted(state.events.values(), key=lambda ev: ev.id):
            if not ev.ongoing or ev.ended_at or not ev.text_ref \
                    or not ev.when <= frame.now <= ev.when + round(p.situation_days * DAY):
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
        return [(ev.id, labels.get(whom, whom), texts[ev.text_ref]) for ev, whom in live if texts.get(ev.text_ref)]

    # ── ce qu'on en garde ──
    async def _drafts(self, ex: x.Extraction, frame: Frame, state: MemoryState, store: Any, conv: x.Conversation,
                      people: x.People, known: list[tuple[int, str]], promises: list[tuple[int, str, str]],
                      vectors: Any, p: MemoryParams, call_id: str) -> list[Draft[Any]]:
        drafts: list[Draft[Any]] = []
        known_ids = {i for i, _ in known}
        known_texts = dict(known)
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

        def hers(cited: Sequence[int]) -> bool:
            """L'élément ne s'appuie que sur ce qu'elle a dit elle-même : ce n'est pas quelque chose qu'on lui a
            appris (sonde réelle du 2026-10-02 : elle avait inventé « il n'a rien voulu me dire » devant Chloé, et
            l'extraction en avait fait une croyance sur Adrien)."""
            seqs = [s for s in cited if s in lines]
            return bool(seqs) and not any(lines[s].person for s in seqs)

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
            if s.sur_elle and not people.resolve(s.personnes):
                drafts += await self._about_self(s, store, vectors, p, provenance, call_id, known_ids)
                continue
            text, cited_seqs = s.texte, list(s.messages)
            if banal(text, said_names):
                continue  # « Sam est parti en disant 'allez j'y vais' » : une banalité ne se retient pas
            line = x.copy_of(text, conv.lines)
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
            twin = await self._twin(store, vectors, text, c.SOUVENIR, about, p)
            if twin is not None:
                drafts.append(c.REINFORCED.draft(item=twin, sources=sources, sensitivity=sens, about=about,
                                                 told_by=told_by, heard_by=heard, secret=secret))
                continue
            e = emotion_of(s.emotion)
            drafts.append(c.REMEMBERED.draft(
                text=Content.of(text, level=sens), about=about, sensitivity=sens,
                importance=x.IMPORTANCE.get(s.importance, 0.45), emotion=e.value if e else None,
                sources=sources, call_id=call_id, told_by=told_by, heard_by=heard, secret=secret))
        for b in ex.croyances:
            if not fresh(c.BELIEF, b.texte):
                continue
            if b.sur_elle and not people.resolve(b.personnes):
                # ce qu'elle dit d'elle seule ; « Mika a dit à Sam : … », lui, nomme quelqu'un : ce n'est pas une
                # note anodine sur elle (elle sortait telle quelle dans un salon — sonde du 2026-10-03), il suit le
                # chemin commun (sa réplique n'est pas ce qu'on lui a appris)
                drafts += await self._about_self(b, store, vectors, p, provenance, call_id, known_ids)
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
            twin = await self._twin(store, vectors, b.texte, c.BELIEF, about, p)
            if replaces is not None and same_words(known_texts.get(replaces, ""), b.texte):
                twin = replaces  # la croyance « remplacée » dit la même chose : c'est elle
            if twin is not None:
                # redire une croyance en la désignant elle-même comme « remplacée » n'est pas la réviser : c'est la
                # confirmer (sonde réelle du 2026-10-02 : « Je croyais que X — apparemment ce n'est plus vrai : X »)
                new = set(informants_of(source, told_by))
                drafts.append(c.REINFORCED.draft(
                    item=twin, corroborated=bool(new - set(self._informants(store, twin))), source=source,
                    sources=sources, sensitivity=sens, about=about, told_by=told_by, heard_by=heard, secret=secret,
                    replaces=replaces if replaces != twin else None, between_us=between))
                continue
            drafts.append(c.BELIEVED.draft(
                text=Content.of(b.texte, level=sens), about=about, sensitivity=sens,
                importance=importance, confidence=round(b.confiance, 3),
                origin=x.ORIGIN.get(fold(b.origine), "told"), source=source, replaces=replaces, sources=sources,
                call_id=call_id, told_by=told_by, heard_by=heard, secret=secret, between_us=between))
        drafts += self._called(nicks, ours, store, conv, call_id)
        for item in ex.confidentiel:
            if item in known_ids:
                drafts.append(c.REINFORCED.draft(item=item, sensitivity=int(Sensitivity.CONFIDENCE), secret=True))
        drafts += await self._promised(ex, frame, state, store, conv, people, promises, vectors, p, provenance,
                                       fresh, call_id, lambda text: x.echoes(text, secrets, names))
        drafts += await self._events(ex, frame, state, store, conv, people, vectors, p, provenance, concerned,
                                     secret_of, heard, fresh, call_id)
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
                drafts.append(c.REINFORCED.draft(item=hit, sources=tuple(seqs)))
                continue
            sens = int(Sensitivity.PERSONAL)
            drafts.append(c.BELIEVED.draft(
                text=Content.of(phrase("memory.extraction.nickname", name=name or phrase("memory.extraction.someone"),
                                       nick=nick), level=sens), about=(person,),
                sensitivity=sens, importance=x.IMPORTANCE[3], confidence=0.9, origin=c.OBSERVED, source=person,
                sources=tuple(seqs), call_id=call_id, told_by=(person,), heard_by=conv.persons, between_us=True))
        return drafts

    @staticmethod
    def _secrets(store: Any, conv: x.Conversation) -> list[str]:
        """Les secrets qu'elle garde déjà sur les personnes de cette conversation."""
        return kept_secrets(store, conv.persons)

    async def _about_self(self, b: x.XSouvenir | x.XCroyance, store: Any, vectors: Any, p: MemoryParams,
                          provenance: Any, call_id: str, known_ids: set[int]) -> list[Draft[Any]]:
        """Ce qu'elle a raconté d'elle-même : une note anodine, de peu
        d'importance, qui s'efface en quelques jours — sauf ce qui la définit
        (un goût, un avis, un fait de sa vie), qui tient longtemps ; quand elle
        change d'avis, la nouvelle croyance remplace l'ancienne."""
        sources, _told, _cited = provenance(b.messages)
        durable = x.durable_self(b)
        replaces = getattr(b, "remplace", None)
        replaces = replaces if durable and replaces in known_ids else None
        twin = await self._twin(store, vectors, b.texte, c.BELIEF, (), p)
        if twin is not None and twin != replaces:
            return [c.REINFORCED.draft(item=twin, sources=sources)]
        return [c.BELIEVED.draft(
            text=Content.of(b.texte, level=int(Sensitivity.ANODYNE)), about=(), sensitivity=int(Sensitivity.ANODYNE),
            importance=x.IMPORTANCE[3 if durable else 1], confidence=round(getattr(b, "confiance", 0.7), 3),
            origin=c.OBSERVED, sources=sources, replaces=replaces, call_id=call_id, about_self=True, durable=durable)]

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
                      secret_of: Any, heard: tuple[str, ...], fresh: Any, call_id: str) -> list[Draft[Any]]:
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
            got = x.when(ev.quand, tz) or ((frame.now, True) if ev.en_cours else None)
            if got is None or not fresh(c.EVENT, ev.texte):
                continue
            at, all_day = got
            yearly = x.yearly(ev)
            if ev.en_cours:
                # une situation : depuis quand (jamais dans le futur, jamais plus vieille que ce qu'on suit)
                at = max(frame.now - round(p.situation_days * DAY) + DAY, min(at, frame.now))
            elif at < frame.now - DAY and not yearly:
                continue  # du passé : ce n'est plus à suivre (ce qui revient chaque année, si : il reviendra)
            if not ev.en_cours and (x.task_words(ev.texte) or any(
                    (not seqs or not ev.messages or set(seqs) & set(ev.messages)) and same_task(ev.texte, text)
                    and same_day(frame, at, due) for text, seqs, due in tasks)):
                continue  # une chose à faire (une promesse, un rappel), pas un moment de sa vie
            about = concerned(ev.personnes)
            sources, told_by, cited = provenance(ev.messages)
            sens = max(x.sensitivity(ev.sensibilite, has_person=True), int(Sensitivity.ANODYNE))
            if any(set(a) & set(about) and same_day(frame, t, at) and x.same_moment(ev.texte, n, names)
                   for n, t, a in noted):
                continue  # dit deux fois dans la même conversation
            twin = await self._same_event(store, state, vectors, ev.texte, about, p, frame=frame, at=at,
                                          names=names)
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
                    yearly=twin.yearly or (not twin.ongoing and yearly)))
                continue
            noted.append((ev.texte, at, about))
            drafts.append(c.EVENT_NOTED.draft(
                text=Content.of(ev.texte, level=sens), when=at, about=about, all_day=all_day, sensitivity=sens,
                sources=sources, told_by=told_by, heard_by=heard, secret=secret_of(ev.secret, cited, sens, ev.texte),
                replaces=twin.id if twin is not None else None, call_id=call_id, ongoing=ev.en_cours,
                importance=x.moment_importance(ev), festive=not ev.en_cours and x.festive(ev), yearly=yearly))
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

    async def _same_event(self, store: Any, state: MemoryState, vectors: Any, text: str, about: tuple[str, ...],
                          p: MemoryParams, *, frame: Frame | None = None, at: int | None = None,
                          names: Sequence[str] = ()) -> c.LifeEvent | None:
        """Le moment déjà noté que ce texte redit : presque les mêmes mots (vecteurs, radicaux) — ou, le même jour
        pour la même personne, les mêmes mots une fois les prénoms ôtés (« son anniversaire » est « l'anniversaire
        de Sam »). Une date qui revient chaque année se compare à son occurrence de ce jour-là."""
        mine = [ev for ev in state.events.values() if set(ev.about) & set(about)]
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


def same_words(a: str, b: str) -> bool:
    """Deux textes qui disent la même chose mot pour mot (casse, accents et ponctuation à part ; pas un mot de
    moins — « n'habite pas » n'est pas « habite »)."""
    return bool(a) and WORD.findall(fold(a)) == WORD.findall(fold(b))


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
    return VectorItem(int(r["id"]), r["kind"], r["text"], tuple(sorted({*_keys(r["about"]), *_keys(r["told_by"])})))


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


@MEMORY.process("memory.index", wake_on=[c.REMEMBERED, c.BELIEVED, c.PROMISE_NOTICED, c.EVENT_NOTED, rt.UTTERANCE],
                lane="background", catch_up=CatchUp.ONCE, max_quantum_s=600)
class Index:
    """L'index des vecteurs (un cache) suit la mémoire : à chaque passage, ce qui est né depuis le précédent
    (``id > ?``, textes compris) ; au premier passage, et après un oubli (``memory_forgets`` a bougé), un
    rapprochement par les seuls identifiants — ce qui a disparu part, ce qui manque s'ajoute. Relire toute la
    mémoire, textes compris, à chaque énoncé coûtait 80 ms à cinquante mille éléments, sur la boucle (ADR 0059)."""

    def __init__(self) -> None:
        self.done: tuple[int, int] | None = None
        self.retry_at = 0
        #: les plus grands identifiants déjà confiés à l'index (éléments, échanges)
        self.upto = (0, 0)
        #: le compte d'oublis vu au dernier rapprochement
        self.forgets = 0

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
        forgets = forgets_of(store)
        if self.done is None or forgets != self.forgets:
            todo, upto = await self._reconcile(vectors, store)
        else:
            todo, upto = self._fresh(store)
        for i in range(0, len(todo), BATCH):
            await vectors.upsert(todo[i:i + BATCH])
        self.upto, self.forgets, self.done = upto, forgets, key
        self.retry_at = 0

    def _fresh(self, store: Any) -> tuple[list[VectorItem], tuple[int, int]]:
        """Ce qui est né depuis le dernier passage."""
        items = _rows(store, f"SELECT {','.join(ITEM_COLUMNS)} FROM {c.ITEMS_TABLE} WHERE id > ? ORDER BY id",
                      (self.upto[0],), ITEM_COLUMNS)
        chunks = _rows(store, f"SELECT {','.join(_CHUNK_COLUMNS)} FROM {c.CHUNKS_TABLE} WHERE id > ? ORDER BY id",
                       (self.upto[1],), _CHUNK_COLUMNS)
        upto = (max([self.upto[0], *(int(r["id"]) for r in items)]),
                max([self.upto[1], *(int(r["id"]) for r in chunks)]))
        return [*map(_item_vector, items), *map(_chunk_vector, chunks)], upto

    @staticmethod
    async def _reconcile(vectors: Any, store: Any) -> tuple[list[VectorItem], tuple[int, int]]:
        """Toute la mémoire, par ses identifiants : l'oubli efface des lignes, leurs vecteurs partent aussi (l'index
        n'est qu'un cache) ; ce qui manque (un index neuf, jeté) s'ajoute."""
        indexed = vectors.indexed()
        items = {int(r[0]) for r in store.query_mind(f"SELECT id FROM {c.ITEMS_TABLE}")}
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
