"""Le pilote de l'avance rapide : faire vivre le script de sa vie au vrai noyau, sur horloge virtuelle.

Le noyau est composé comme par le simulateur (``mika.sim.world.Driver``), sur un dossier de
données sur disque (``sortie/vie/``), avec le rejoueur pour seul « modèle ». Le mécanisme
de réponse a été validé à l'étape 0 (``docs/mesures-etape-0.md``) :

- un message auquel elle a répondu est **retenu** par le ``reply_wait`` du pilote, puis
  **libéré** à l'heure de sa vraie réponse (``Kernel.release_held``). Le noyau lance alors
  lui-même une REPLY, avec ``reply_to``, qui règle tout le tour ;
- un message laissé sans réponse part tout de suite, et le rejoueur se tait ;
- une conversation qu'elle ouvre est une INITIATIVE soumise à la main
  (``reason="archive"``) ; au salon, sa parole spontanée est une REPLY sans ``reply_to`` ;
- le préréglage « avance rapide » (``mika.app.genesis``) coupe sa vie spontanée, et la nuit
  de l'archive est respectée (personne ne la réveille). Il est levé à l'arrivée, avec sa
  persona actuelle ;
- le savoir d'archive (palier C, ses notes, son journal) entre à sa date par la couture
  ``genesis`` ;
- **une retenue par message** : chaque message auquel elle a répondu est retenu par son numéro (``seq``), et le
  pilote le marque « à libérer » juste avant d'appeler ``release_held`` — jamais un autre tour échu en même temps,
  jamais une autre conversation avec la même personne (relecture du 2026-10-06) ;
- **reprise** : l'état du pilote (curseur, retenues) et la table ``replay_seq`` sont écrits dans ``corpus.db``
  **après chaque pas**, et restaurés **avant** ``boot``. Les perceptions portent ``dedupe_key="archive:<id>"`` ;
  une parole déjà dite mais pas encore notée au moment d'un plantage est retrouvée dans le journal (et pas redite) ;
  l'horloge repart de la tête du journal. Sans ``mind.db`` (la vie supprimée à la main), l'état est oublié.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections import Counter, defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from mika.app import composition as compo
from mika.app import genesis
from mika.app.datadir import hold, release
from mika.contracts import body as body_c
from mika.contracts import runtime as rt
from mika.contracts.runtime import PerceptionReceived
from mika.contracts.self_ import PersonaDoc
from mika.kernel.clock import US
from mika.kernel.events import Content
from mika.runtime.pipeline import EpisodeRequest
from mika.runtime.state import RUNTIME
from mika.sim.clock import SimClock, run_virtual
from mika.sim.world import Composition, Driver
from mika.vocab import privacy
from mika.vocab.episodes import Kind
from mika.vocab.people import EXTERNAL_PREFIX

from twin.corpus import Corpus
from twin.replay.assemble import event_date
from twin.replay.provider import ReplayLLM
from twin.replay.script import steps
from twin.timing import DAY, from_us

STATE_SCHEMA = "CREATE TABLE IF NOT EXISTS replay_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
IMPORTANCE = {1: 0.2, 2: 0.45, 3: 0.7, 4: 0.95}  # l'échelle de la mémoire du moteur
SENSITIVITY = {"anodin": 1, "personnel": 2, "confidence": 3}
#: un tour qu'on vient de libérer a ce temps (virtuel) pour partir avant le repli manuel
RELEASE_GRACE_S = 5.0


@dataclass
class Report:
    started: float = field(default_factory=time.time)
    stats: Counter[str] = field(default_factory=Counter)
    gaps: list[str] = field(default_factory=list)
    lags: list[float] = field(default_factory=list)

    def gap(self, text: str) -> None:
        if len(self.gaps) < 2000:
            self.gaps.append(text)


class FastForward:
    def __init__(self, corpus: Corpus, life: Path, tz: ZoneInfo, *, start_persona: dict[str, Any],
                 final_persona: dict[str, Any], seed: str = "jumeau", until: int | None = None,
                 log: Callable[[str], None] = print) -> None:
        self.corpus = corpus
        self.db = corpus.db
        self.life = life
        self.tz = tz
        self.log = log
        self.until = until
        self.report = Report()
        self.db.executescript(STATE_SCHEMA)
        resuming = (life / "mind.db").is_file()
        if not resuming:  # une vie neuve (ou supprimée à la main) : rien de l'ancien état ne vaut plus
            self.db.execute("DELETE FROM replay_state")
            self.db.execute("DELETE FROM replay_seq") if self._has("replay_seq") else None
            self.db.commit()
        state = self._load_state()
        self.cursor: tuple[int, int] = tuple(state.get("cursor", (-(2**62), 0)))  # type: ignore[assignment]
        #: perception retenue (``seq``) → l'heure de sa réponse ; ``releasing`` : celles qu'on libère maintenant
        self.holds: dict[int, int] = {int(k): int(v) for k, v in state.get("holds", {}).items()}
        self.releasing: set[int] = set()
        #: le message en train d'arriver (adresse, salon, heure de sa réponse) — voir ``reply_wait``
        self.perceiving: tuple[str, str | None, int] | None = None
        self.persona = PersonaDoc.model_validate(state.get("persona") or start_persona)
        self.final_persona = PersonaDoc.model_validate(final_persona)
        boots = int(state.get("boots", 0))
        self.last_at = self._last_step_at()
        if until is not None and until >= self.last_at:
            self.until = None  # au-delà de la dernière date : c'est l'avance entière, jusqu'à l'arrivée
        #: ses paroles dites (au journal) mais pas encore notées au moment d'un plantage : (seq, cible)
        self.unmapped: deque[tuple[int, str]] = deque(self._unmapped_utterances()) if resuming else deque()
        start = self._resume_clock() if resuming else self._first_step_at() - DAY
        self.clock = SimClock(start)
        self.llm = ReplayLLM(corpus, tz, self.clock.now)
        #: par adresse : les messages d'archive des paroles annoncées, dans l'ordre (pour relier énoncé ↔ archive)
        self.awaiting: dict[str, deque[list[int]]] = defaultdict(deque)
        self.overrides = genesis.fast_forward_overrides()
        base_deps = compo.deps

        def deps(**kw: Any) -> Any:
            return base_deps(**kw, reply_wait=self.reply_wait)

        async def configure(kernel: Any, doc: Any) -> Any:
            return await compo.configure(kernel, doc, overrides=self.overrides)

        composition = Composition(deps=deps, configure=configure, persona=self.persona,
                                  voice_roles=compo.for_simulation(self.persona).voice_roles)
        self.driver = Driver(life, composition, self.llm, self.clock, seed=seed, slots=4)
        self.driver.boots = boots + 1 if resuming else 0
        assert self.driver.transport is not None
        self.driver.transport.heard = deque(maxlen=1000)  # type: ignore[assignment]

    # -- l'état du pilote ------------------------------------------------------------------------------------

    def _load_state(self) -> dict[str, Any]:
        return {r["key"]: json.loads(r["value"]) for r in self.db.execute("SELECT key, value FROM replay_state")}

    def _has(self, table: str) -> bool:
        return self.db.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone() is not None

    def save_state(self) -> None:
        """Après chaque pas : le curseur, les retenues et les relevés ``replay_seq`` partent ensemble."""
        state = {"cursor": list(self.cursor), "boots": self.driver.boots, "persona": self.persona.model_dump(mode="json"),
                 "holds": {str(k): v for k, v in self.holds.items()}}
        self.db.executemany("INSERT OR REPLACE INTO replay_state (key, value) VALUES (?, ?)",
                            [(k, json.dumps(v, ensure_ascii=False)) for k, v in state.items()])
        self.db.commit()

    def _first_step_at(self) -> int:
        row = self.db.execute("SELECT MIN(at) FROM replay_steps").fetchone()
        if row is None or row[0] is None:
            raise RuntimeError("le script est vide : lancer d'abord la préparation (jumeau avancer --preparer)")
        return int(row[0])

    def _last_step_at(self) -> int:
        row = self.db.execute("SELECT MAX(at) FROM replay_steps").fetchone()
        return int(row[0]) if row and row[0] is not None else 0

    def _unmapped_utterances(self) -> list[tuple[int, str]]:
        """Ses paroles au journal après la dernière notée : dites juste avant un plantage, pas encore relevées."""
        last = self.db.execute("SELECT MAX(seq) FROM replay_seq").fetchone()[0] if self._has("replay_seq") else None
        with sqlite3.connect(self.life / "mind.db") as db:
            rows = db.execute("SELECT seq, data FROM events WHERE type = ? AND seq > ? ORDER BY seq",
                              (rt.UTTERANCE.name, int(last or 0))).fetchall()
        return [(int(seq), str(json.loads(data).get("target") or "")) for seq, data in rows]

    def _resume_clock(self) -> int:
        """Reprendre : l'horloge repart de la tête du journal (jamais en arrière). Seule lecture directe du journal,
        avant que le noyau ne l'ouvre."""
        with sqlite3.connect(self.life / "mind.db") as db:
            head = db.execute("SELECT MAX(at) FROM events").fetchone()[0]
        return int(head or self._first_step_at()) + 1

    # -- le noyau ---------------------------------------------------------------------------------------------

    @property
    def kernel(self) -> Any:
        assert self.driver.kernel is not None
        return self.driver.kernel

    def reply_wait(self, frame: Any, seq: int) -> int | None:
        """Le pilote d'abord : un message auquel elle a répondu reste retenu (0) jusqu'à ce que le pilote le marque
        « à libérer » — alors il rend l'heure de sa réponse. Sinon ``body`` (la nuit)."""
        if seq not in self.holds and self.perceiving is not None:
            p = frame.root.slices[RUNTIME.name].pending.get(seq)
            handle, room, answered = self.perceiving
            if p is not None and p.handle == handle and p.room == room:
                self.holds[seq] = answered  # le message qui arrive : retenu sous son seq
        due = self.holds.get(seq)
        if due is not None:
            return due if seq in self.releasing else 0
        return frame.get(body_c.REPLY_WAIT(seq))

    def on_events(self, events: Any, root: Any) -> None:
        for e in events:
            name = e.type.name
            if name == rt.UTTERANCE.name:
                d = e.data
                self.report.stats[f"énoncé:{d.kind}"] += 1
                queue = self.awaiting.get(d.target or "")
                if queue:
                    self.llm.note_seq(e.seq, queue.popleft())
                for seq in getattr(d, "answers", ()) or ():
                    self.holds.pop(int(seq), None)
                    self.releasing.discard(int(seq))
            elif name == rt.EPISODE_ENDED.name:
                self.report.stats[f"fin:{e.data.kind}:{e.data.outcome}"] += 1

    # -- les pas -----------------------------------------------------------------------------------------------

    async def run(self) -> Report:
        self.life.mkdir(parents=True, exist_ok=True)
        hold(self.life)  # un seul processus sur ce dossier (``mika serve`` attendra la fin)
        try:
            return await self._run()
        finally:
            release(self.life)

    async def _run(self) -> Report:
        k = await self.driver.boot()
        k.mind.subscribe(self.on_events)
        await genesis.begin_fast_forward(k, self.persona, overrides=None)
        day = None
        try:
            for sid, at, kind, data in steps(self.corpus, self.cursor):
                if self.until is not None and at > self.until:
                    break
                await self._until(at)
                await self._step(kind, data, sid)
                self.cursor = (at, sid)
                self.save_state()  # après chaque pas : un plantage ne rejoue rien de ce qui est fait
                today = from_us(at, self.tz).date()
                if today != day:
                    day = today
                    self.report.stats["jours"] += 1
                    if self.report.stats["jours"] % 30 == 0:
                        self.log(f"{today} · {self.report.stats['perçus']} messages reçus, "
                                 f"{self.report.stats['énoncé:REPLY'] + self.report.stats['énoncé:INITIATIVE']} "
                                 "paroles")
            await self.kernel.lanes.join()
            if self.until is None:
                # l'arrivée : le préréglage levé (aucune surcharge d'opératrice dans une vie neuve), sa persona
                # d'aujourd'hui, ses valeurs naturelles
                await genesis.end_fast_forward(self.kernel, self.final_persona, overrides=None)
                self.report.stats["arrivée"] = 1
        finally:
            self.save_state()
            await self.driver.stop()
        self.report.stats.update({f"rejoueur:{role}": n for role, n in self.llm.served.items()})
        self.report.stats.update({f"trou:{role}": n for role, n in self.llm.holes.items()})
        return self.report

    async def _until(self, t: int) -> None:
        now = self.clock.now()
        if t > now:
            await asyncio.sleep((t - now) / US)

    async def _step(self, kind: str, data: dict[str, Any], sid: int) -> None:
        if kind == "in":
            await self._incoming(data)
        elif kind == "her":
            await self._her(data)
        elif kind == "persona":
            self.persona = PersonaDoc.model_validate(data["doc"])
            await compo.configure(self.kernel, self.persona, overrides=self.overrides)
            self.report.stats["chapitres"] += 1
            self.log(f"chapitre {data['chapitre']} : {data['titre']}")
        elif kind == "knowledge":
            await self._knowledge(data, sid)

    async def _incoming(self, d: dict[str, Any]) -> None:
        handle = d["handle"]
        answered = int(d["release_at"]) if d.get("release_at") and d.get("addressed") else None
        # le noyau demande ``reply_wait`` pendant ``perceive``, avant qu'on connaisse le seq : on lui dit quel message
        # est en train d'arriver, et ``reply_wait`` le retient sous son seq dès qu'il le voit
        self.perceiving = (handle, d.get("room"), answered) if answered is not None else None
        external = handle.startswith(EXTERNAL_PREFIX)
        data = PerceptionReceived(
            handle=handle, channel=privacy.channel_of(handle), text=Content.of(d["text"][:20000]),
            authenticated=not external, display_name=d["name"], room=d.get("room"), public=d.get("room") is not None,
            addressed=bool(d.get("addressed", True)),
            reply_ref=d.get("room") or (handle[len(EXTERNAL_PREFIX):] if external else None))
        try:
            for attempt in range(60):
                got = await self.kernel.perceive(data, dedupe_key=f"archive:{d['archive'][0]}")
                if not got.overloaded:
                    break
                await asyncio.sleep(5 + attempt)  # la file est pleine : on patiente (en temps virtuel)
            else:
                self.report.gap(f"{from_us(self.clock.now(), self.tz)} message perdu (file pleine) : {handle}")
                return
        finally:
            self.perceiving = None
        self.report.stats["perçus"] += 1
        if got.seq is not None:
            self.llm.note_seq(got.seq, d["archive"])
            if answered is not None and got.commit is not None and not got.commit.deduped:
                self.holds.setdefault(got.seq, answered)
        if got.held:
            self.report.stats["retenus"] += 1

    async def _her(self, d: dict[str, Any]) -> None:
        target = d["target"]
        if not target:
            self.report.gap(f"{from_us(self.clock.now(), self.tz)} parole sans destinataire")
            return
        if self._already_said(target, d["archive"]):
            return
        self.llm.expect(target, d["text"])
        self.awaiting[target].append(list(d["archive"]))
        k = self.kernel
        if d["kind"] == "reply":
            seqs = {s for a in d.get("reply_to", []) if (s := self.llm.seq_of(a)) is not None and s in self.holds}
            if seqs:
                before = self.report.stats["énoncé:REPLY"]
                self.releasing |= seqs  # seulement ce tour-ci : un autre tour échu reste retenu
                k.release_held()
                for _ in range(int(RELEASE_GRACE_S / 0.5)):
                    await asyncio.sleep(0.5)
                    if self.report.stats["énoncé:REPLY"] > before:
                        self.report.stats["réponse:libérée"] += 1
                        return
            # rien n'était retenu (réglé entre-temps) : une réponse sans reply_to
            self.report.stats["réponse:repli"] += 1
            req = EpisodeRequest(kind=Kind.REPLY, target=target, reason="archive", priority=0, channel="external",
                                 room=d.get("room"))
        elif d["kind"] in ("room", "continue"):
            # au salon, ou en pleine conversation (la personne a écrit il y a peu) : une parole qui ne répond à rien
            # d'adressé — une REPLY sans reply_to, jamais une ouverture (étape 0)
            req = EpisodeRequest(kind=Kind.REPLY, target=target, reason="archive", priority=0, channel="external",
                                 room=d.get("room"))
        else:
            req = EpisodeRequest(kind=Kind.INITIATIVE, target=target, reason="archive", priority=1,
                                 channel="external")
        fut = k.lanes.submit(req)
        if fut is None:
            self._drop(target, "épisode refusé (file pleine)")
            return
        rep = await fut
        if rep.outcome.value != "done":
            self._drop(target, f"{d['kind']} : {rep.outcome.value} {getattr(rep, 'detail', '')[:80]}")

    def _already_said(self, target: str, archive: list[int]) -> bool:
        """Après un plantage : sa parole est-elle déjà au journal (notée, ou dite juste avant de tomber) ?"""
        if self.llm.seq_of(archive[0]) is not None:
            return True
        while self.unmapped and self.unmapped[0][1] != target:
            self.unmapped.popleft()  # une parole hors script (un silence, une réponse de secours) : rien à relier
        if self.unmapped:
            seq, _ = self.unmapped.popleft()
            self.llm.note_seq(seq, archive)
            self.report.stats["reprise:parole retrouvée"] += 1
            return True
        return False

    def _drop(self, target: str, why: str) -> None:
        """Une parole qui n'a pas pu partir : on la retire du plan, et on le dit dans le rapport."""
        if self.llm.expected.get(target):
            self.llm.expected[target].pop()
        if self.awaiting.get(target):
            self.awaiting[target].pop()
        self.report.stats["paroles perdues"] += 1
        self.report.gap(f"{from_us(self.clock.now(), self.tz)} {target} : {why}")

    async def _knowledge(self, d: dict[str, Any], sid: int) -> None:
        """Ce que ses archives non rejouées disent, par la couture ``genesis``, à sa date."""
        k = self.kernel

        def told_of(item: dict[str, Any]) -> tuple[str, ...]:
            # qui le lui a confié : les auteurs de ses messages d'ancrage (ses propres textes : personne)
            return () if d.get("own") else tuple(item.get("told_by") or ())

        for i, item in enumerate(d.get("souvenirs", [])):
            told = told_of(item)
            await self._safe(genesis.remember(
                k, item["texte"], self._about(item), sensitivity=SENSITIVITY.get(item.get("sensibilite", ""), None),
                importance=IMPORTANCE.get(int(item.get("importance", 2)), 0.45), emotion=item.get("emotion"),
                told_by=told, secret=bool(item.get("secret")), dedupe_key=f"archive:s{sid}:souvenir:{i}"), "souvenir")
        for i, item in enumerate(d.get("croyances", [])):
            mine = bool(item.get("sur_elle"))
            about = () if mine else self._about(item)
            told = told_of(item)
            if item.get("entre_vous"):
                told = tuple(t for t in told if t in about)  # « entre vous » se tient de première main
            await self._safe(genesis.believe(
                k, item["texte"], about,
                sensitivity=SENSITIVITY.get(item.get("sensibilite", ""), None),
                importance=IMPORTANCE.get(int(item.get("importance", 2)), 0.45),
                confidence=float(item.get("confiance", 0.7)),
                origin={"dit": "told", "observe": "observed", "deduit": "inferred"}.get(item.get("origine", "dit"),
                                                                                       "told"),
                told_by=() if mine else told, secret=bool(item.get("secret")), about_self=mine,
                durable=mine and item.get("genre") in ("gout", "avis", "fait"),
                between_us=bool(item.get("entre_vous")), dedupe_key=f"archive:s{sid}:croyance:{i}"), "croyance")
        for i, item in enumerate(d.get("evenements", [])):
            told = told_of(item)
            when = _event_us(str(item.get("quand", "")), self.tz)
            about = self._about(item)
            if when is None or not about:
                continue
            await self._safe(genesis.note_event(
                k, item["texte"], about, when, all_day="T" not in str(item.get("quand", "")),
                sensitivity=SENSITIVITY.get(item.get("sensibilite", ""), None),
                importance=IMPORTANCE.get(int(item.get("importance", 3)), 0.7), festive=bool(item.get("a_feter")),
                ongoing=bool(item.get("en_cours")), told_by=told, secret=bool(item.get("secret")),
                dedupe_key=f"archive:s{sid}:evenement:{i}"), "événement")

    def _about(self, item: dict[str, Any]) -> tuple[str, ...]:
        out = []
        for ref in item.get("personnes", []):
            ref = str(ref)
            if ref.startswith("p") and ref[1:].isdigit():
                handle = self.llm.handle_of(int(ref[1:]))
                if handle:
                    out.append(handle)
            elif ref.strip():
                out.append(genesis.named(ref))
        return tuple(dict.fromkeys(out))

    async def _safe(self, coro: Any, what: str) -> None:
        try:
            await coro
            self.report.stats[f"savoir:{what}"] += 1
        except ValueError as exc:  # dont genesis.NotAPerson : une clé de personne refusée
            self.report.stats[f"savoir refusé:{what}"] += 1
            self.report.gap(f"{from_us(self.clock.now(), self.tz)} {what} refusé : {exc}")


def _event_us(raw: str, tz: ZoneInfo) -> int | None:
    got = event_date(raw)
    if got is None:
        return None
    text, _precise = got
    try:
        dt = datetime.fromisoformat(text) if "T" in text else datetime.fromisoformat(text + "T12:00")
    except ValueError:
        return None
    return int(dt.replace(tzinfo=tz).timestamp() * US)


def run(corpus: Corpus, life: Path, tz: ZoneInfo, *, start_persona: dict[str, Any], final_persona: dict[str, Any],
        until: int | None = None, log: Callable[[str], None] = print) -> Report:
    """Une avance rapide entière (ou jusqu'à ``until``), sur sa propre boucle à temps virtuel."""
    ff = FastForward(corpus, life, tz, start_persona=start_persona, final_persona=final_persona, until=until, log=log)

    async def main() -> Report:
        return await ff.run()

    return run_virtual(ff.clock, main)
