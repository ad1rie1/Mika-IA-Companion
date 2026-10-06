"""Étape 0 du jumeau numérique : rejouer une archive dans le vrai noyau, sur horloge virtuelle.

Rien n'est modifié dans ``backendv2`` : on compose le noyau comme le simulateur (``sim/world.py::Driver``), sur un
``SqliteStore`` sur disque, avec un fournisseur LLM scripté (le « rejoueur ») qui ne fait aucun appel réel.

Le pilote (``Pilote``) éprouve le mécanisme retenu pour l'avance rapide :

- un message entrant auquel elle a répondu est **retenu** par un ``reply_wait`` du pilote (la dépendance
  ``KernelDeps.reply_wait`` de la composition, qui délègue sinon à ``body``) jusqu'à l'heure de sa vraie réponse ;
  à cette heure, le pilote le **libère** : le noyau lance lui-même l'épisode REPLY sur le dernier message du tour
  (une rafale reçoit une seule réponse, qui règle tout le tour), et le rejoueur rend ses mots + la balise ;
- un message auquel elle n'a pas répondu part en réponse automatique : le rejoueur rend ``[SILENCE]`` ;
- une conversation qu'elle ouvre : ``lanes.submit(EpisodeRequest(kind=INITIATIVE, …, reason="archive"))`` ;
- les rôles de fond (``extract``, ``journal``, ``dream``, ``narrative``, ``profile``, ``compact``) sont servis par
  la doublure ``PersonaSimLLM`` (sans latence), comme le futur rejoueur les servira depuis les annotations.

Scénarios (``python mesure_noyau.py <scénario> …``) : ``debit``, ``episodes``, ``nuit``, ``spontane``, ``passe``.
Chaque scénario écrit ``out/<nom>/resultats.json`` (et ``jours.csv`` pour ``debit``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import resource
import shutil
import sqlite3
import sys
import time
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from mika.app import composition as compo
from mika.contracts import affect as affect_c
from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.contracts.runtime import PerceptionReceived
from mika.kernel.clock import US
from mika.kernel.events import Content
from mika.ports.llm import LLMRequest, LLMResponse, Usage
from mika.runtime import params as params_mod
from mika.runtime.pipeline import EpisodeRequest
from mika.runtime.state import RUNTIME
from mika.sim.clock import SimClock, run_virtual
from mika.sim.lane import PARIS, at_paris
from mika.sim.llm.persona import PersonaSimLLM
from mika.sim.world import Composition, Driver
from mika.vocab import privacy
from mika.vocab.episodes import Kind
from mika.vocab.people import EXTERNAL_PREFIX

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
MINUTE = 60 * US
HOUR = 60 * MINUTE
DAY = 24 * HOUR

#: le préréglage « avance rapide » éprouvé ici : couper sa vie spontanée (l'archive dit déjà ce qu'elle a fait)
FAST_FORWARD: dict[str, dict[str, Any]] = {
    "agency": {"daily_cap": 0},
    "goals": {"musings_per_day": 0, "live_self_max": 0},
    "expression": {"murmur_chance": 0.0, "murmur_charged_chance": 0.0},
}

EMOTIONS = ("happy", "amused", "curious", "grateful", "excited", "playful", "sad", "anxious", "hopeful", "relieved",
            "thinking")

# ── L'archive synthétique ──────────────────────────────────────────────────

PEOPLE = (  # (slug, nom, poids dans la conversation)
    ("lea", "Léa", 0.32), ("karim", "Karim", 0.2), ("maman", "Maman", 0.16), ("julie", "Julie", 0.13),
    ("tom", "Tom", 0.11), ("sami", "Sami", 0.08),
)
ROOM = "salon-amis"
ROOM_MEMBERS = ("lea", "julie", "tom")
#: poids des heures de début de séance (heure locale)
HOUR_WEIGHTS = (0.25, 0.12, 0.06, 0.03, 0.02, 0.02, 0.05, 0.4, 0.7, 0.6, 0.7, 0.8, 1.2, 1.1, 0.8, 0.8, 0.9, 1.0,
                1.3, 1.4, 1.5, 1.5, 1.2, 0.7)
THEIR = ("t'as vu ce qui s'est passé hier", "je suis crevé(e) ce soir", "on se fait un ciné ce week-end ?",
         "j'ai enfin fini ce dossier", "ma sœur m'a encore appelé pour rien", "tu penses quoi de la nouvelle série",
         "il pleut encore, j'en peux plus", "j'ai un entretien jeudi", "le chat a vomi sur le canapé",
         "on mange où demain midi ?", "j'ai réussi mon partiel", "trop bien la soirée d'hier",
         "tu me prêtes ton livre ?", "je repense à ce que tu m'as dit", "mon chef est insupportable",
         "j'ai acheté un vélo", "t'es dispo samedi ?", "c'est l'anniv de Paul bientôt")
HERS = ("ah carrément", "haha non mais sérieux", "trop bien pour toi", "oh mince, courage", "ouais grave",
        "je t'avoue que je sais pas", "attends je regarde", "j'suis trop contente", "pff pareil ici",
        "dis-moi tout", "on verra bien", "c'est clair", "je t'appelle ce soir", "t'inquiète pas pour ça")
TOPICS = ("le boulot", "les vacances", "le ciné", "la fac", "la famille", "le sport", "la musique", "les courses",
          "le bus", "la coloc", "le resto", "les exams", "la plage", "le concert")


@dataclass(frozen=True, slots=True)
class In:
    at: int
    mid: int
    handle: str
    name: str
    text: str
    room: str | None = None
    addressed: bool = True


@dataclass(frozen=True, slots=True)
class Her:
    at: int
    mid: int
    handle: str
    text: str
    emotion: str
    intensity: float
    #: « reply » (répond à des messages retenus), « open » (elle ouvre la conversation), « room » (au salon)
    mode: str
    answers: tuple[int, ...] = ()
    room: str | None = None
    #: combien de messages de l'archive cette parole fusionne
    merged: int = 1


@dataclass(frozen=True, slots=True)
class Mark:
    at: int
    day: int


Item = In | Her | Mark


def handle_of(slug: str) -> str:
    return f"{EXTERNAL_PREFIX}{slug}"


class Archive:
    """Une archive synthétique, graine fixe : ``per_day`` messages par jour en moyenne (les siens compris),
    six personnes en messagerie (``ext_<slug>``) et un salon."""

    def __init__(self, start: int, days: int, per_day: float, seed: int = 7, room_share: float = 0.06,
                 deferred_share: float = 0.2, open_share: float = 0.3) -> None:
        assert datetime.fromtimestamp(start / US, PARIS).strftime("%H:%M") == "00:00", "l'archive part de minuit"
        self.rng = random.Random(seed)
        self.start, self.days, self.per_day = start, days, per_day
        self.room_share, self.deferred_share, self.open_share = room_share, deferred_share, open_share
        self.items: list[Item] = []
        self.mid = 0
        self.her_n = 0
        self.archive_messages = 0
        self._build()

    def _text(self, pool: tuple[str, ...]) -> str:
        r = self.rng
        return f"{r.choice(pool)}, {r.choice(TOPICS)} {r.randint(1, 999)}"

    def _her_text(self) -> str:
        self.her_n += 1
        return f"{self.rng.choice(HERS)} — {self.rng.choice(TOPICS)} n°{self.her_n}"

    def _next(self) -> int:
        self.mid += 1
        return self.mid

    def _session_start(self, day0: int) -> int:
        h = self.rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
        return day0 + h * HOUR + self.rng.randint(0, 3599) * US

    def _build(self) -> None:
        r = self.rng
        per_session = 9.0  # mesuré sur le générateur (≈ 3 échanges × (2 + 1,2) + l'ouverture)
        busy: dict[str, int] = {}
        for d in range(self.days):
            day0 = self.start + d * DAY
            self.items.append(Mark(day0, d))
            n_sessions = max(0, round(r.gauss(self.per_day * (1 - self.room_share) / per_session, 0.6)))
            for _ in range(n_sessions):
                slug, name, _w = r.choices(PEOPLE, weights=[p[2] for p in PEOPLE])[0]
                t = max(self._session_start(day0), busy.get(slug, 0) + 20 * MINUTE)
                busy[slug] = self._session(slug, name, t)
            if r.random() < self.per_day * self.room_share / 6:  # une séance de salon de ~6 messages
                self._room(self._session_start(day0))
        self.items.sort(key=lambda it: (it.at, 0 if isinstance(it, Mark) else 1))

    def _session(self, slug: str, name: str, t: int) -> int:
        r, h = self.rng, handle_of(slug)
        if r.random() < self.open_share:  # elle ouvre
            n = 1 + (r.random() < 0.3)
            self.items.append(Her(t, self._next(), h, self._her_text(), r.choice(EMOTIONS), round(r.uniform(0.3, 0.8), 2),
                                  "open", merged=n))
            self.archive_messages += n
            t += r.randint(60, 1800) * US
        exchanges = 1 + min(6, int(r.expovariate(1 / 2.0)))
        for _ in range(exchanges):
            burst = r.choice((1, 1, 2, 2, 3))
            mids = []
            for _ in range(burst):
                mids.append(self._next())
                self.items.append(In(t, mids[-1], h, name, self._text(THEIR)))
                self.archive_messages += 1
                t += r.randint(5, 80) * US
            if r.random() < 0.12:  # elle ne répond pas : le tour est laissé sans réponse
                t += r.randint(5, 60) * MINUTE
                continue
            deferred = r.random() < self.deferred_share
            delay = r.randint(10 * 60, 4 * 3600) if deferred else r.randint(8, 110)
            t += delay * US
            n = 1 + (r.random() < 0.25)
            self.items.append(Her(t, self._next(), h, self._her_text(), r.choice(EMOTIONS),
                                  round(r.uniform(0.3, 0.85), 2), "reply", tuple(mids), merged=n))
            self.archive_messages += n
            t += r.randint(20, 300) * US
        return t

    def _room(self, t: int) -> None:
        r = self.rng
        for i in range(r.randint(4, 8)):
            slug = r.choice(ROOM_MEMBERS)
            name = next(p[1] for p in PEOPLE if p[0] == slug)
            addressed = i > 0 and r.random() < 0.25
            text = ("Mika, t'en penses quoi ? " if addressed else "") + self._text(THEIR)
            mid = self._next()
            self.items.append(In(t, mid, handle_of(slug), name, text, room=ROOM, addressed=addressed))
            self.archive_messages += 1
            t += r.randint(10, 240) * US
            if addressed and r.random() < 0.8:
                t += r.randint(10, 90) * US
                self.items.append(Her(t, self._next(), handle_of(slug), self._her_text(), r.choice(EMOTIONS), 0.5,
                                      "reply", (mid,), room=ROOM))
                self.archive_messages += 1
                t += r.randint(10, 120) * US


# ── Le rejoueur (fournisseur LLM scripté) ───────────────────────────────────


@dataclass(slots=True)
class Plan:
    text: str
    at: int
    emotion: str = "happy"
    intensity: float = 0.6


class Rejoueur:
    """Le fournisseur des épisodes : ``reply``/``initiative`` → le plan du pilote pour la cible (ses mots + la
    balise), sinon ``[SILENCE]`` (ou la doublure en mode « naturel ») ; les autres rôles → la doublure
    ``PersonaSimLLM`` sans latence (``murmur``/``step`` : ``[SILENCE]`` hors mode naturel)."""

    name = "rejoueur"

    def __init__(self, clock: SimClock, *, natural: bool = False, seed: int = 0, keep: int = 0) -> None:
        self.clock = clock
        self.bg = PersonaSimLLM(clock, seed=seed, latency=0.0, abstain_rate=0.0)
        self.bg.calls = deque(maxlen=0)  # type: ignore[assignment] — la doublure garderait tous les prompts
        self.natural = natural
        self.script: dict[str, Plan] = {}
        self.roles: Counter[str] = Counter()
        self.spent: Counter[str] = Counter()
        self.silences: Counter[str] = Counter()
        #: les dernières requêtes (pour regarder ce que voit le modèle)
        self.calls: deque[LLMRequest] = deque(maxlen=keep)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.roles[req.role] += 1
        self.calls.append(req)
        t0 = time.perf_counter()
        try:
            if req.role in ("reply", "initiative"):
                plan = self.script.get(str(req.meta.get("target")))
                if plan is not None and self.clock.now() >= plan.at - US:
                    return _out(req, f"{plan.text} [EMOTION:{plan.emotion}:{plan.intensity}]")
                if self.natural and req.role == "initiative":  # sa vie spontanée, jouée par la doublure
                    return await self.bg.complete(req)
                self.silences[req.role] += 1
                return _out(req, "[SILENCE]")
            if req.role in ("murmur", "step", "project", "job", "triage", "caption") and not self.natural:
                self.silences[req.role] += 1
                return _out(req, "[SILENCE]")
            return await self.bg.complete(req)
        finally:
            self.spent[req.role] += time.perf_counter() - t0


def _out(req: LLMRequest, text: str) -> LLMResponse:
    return LLMResponse(text, usage=Usage(input_tokens=1, output_tokens=len(text) // 4), model="rejoueur-1")


# ── Le pilote ───────────────────────────────────────────────────────────────


def mem_mb() -> dict[str, float]:
    out = {"maxrss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith(("VmHWM", "VmRSS")):
                k, v = line.split(":")
                out[k.lower() + "_mb"] = int(v.split()[0]) / 1024
    except OSError:
        pass
    return out


def db_sizes(root: Path) -> dict[str, int]:
    out = {}
    for name in ("mind.db", "views.db"):
        total = 0
        for suffix in ("", "-wal", "-shm"):
            p = root / f"{name}{suffix}"
            if p.exists():
                total += p.stat().st_size
        out[name] = total
    return out


def local(at: int) -> str:
    return datetime.fromtimestamp(at / US, PARIS).strftime("%Y-%m-%d %H:%M:%S")


class Pilote:
    def __init__(self, root: Path, clock: SimClock, rej: Rejoueur, *, overrides: dict[str, dict[str, Any]] | None,
                 seed: str = "jumeau", boots: int = 0, chronotype: float | None = None,
                 log: Callable[[str], None] = print) -> None:
        self.root = root
        self.clock = clock
        self.rej = rej
        self.log = log
        #: (adresse, salon) → l'instant de sa réponse : ses messages sont retenus jusque-là
        self.release_at: dict[tuple[str, str | None], int] = {}
        self.answered_by: dict[int, Her] = {}
        self.stats: Counter[str] = Counter()
        self.lags: list[float] = []
        self.ecarts: list[str] = []
        self.overrides = overrides
        persona = compo.load(compo.PERSONA)
        if chronotype is not None:
            persona = persona.model_copy(update={"temperament": persona.temperament.model_copy(
                update={"chronotype": chronotype})})
        self.persona = persona
        base_deps = compo.deps

        def deps(**kw: Any) -> Any:
            return base_deps(**kw, reply_wait=self.reply_wait)

        async def configure(kernel: Any, doc: Any) -> Any:
            return await compo.configure(kernel, doc, overrides=self.overrides)

        composition = Composition(deps=deps, configure=configure, persona=persona,
                                  voice_roles=compo.for_simulation(persona).voice_roles)
        self.driver = Driver(root, composition, rej, clock, seed=seed, slots=4)
        self.driver.boots = boots
        assert self.driver.transport is not None
        self.driver.transport.heard = deque(maxlen=2000)  # type: ignore[assignment]

    @property
    def kernel(self) -> Any:
        assert self.driver.kernel is not None
        return self.driver.kernel

    # la dépendance ``reply_wait`` : le pilote d'abord, ``body`` ensuite (la nuit)
    def reply_wait(self, frame: Any, seq: int) -> int | None:
        p = frame.root.slices[RUNTIME.name].pending.get(seq)
        if p is not None:
            due = self.release_at.get((p.handle, p.room))
            if due is not None:
                return 0 if frame.now < due else due
        return frame.get(body_c.REPLY_WAIT(seq))

    def on_events(self, events: Any, root: Any) -> None:
        for e in events:
            name = e.type.name
            if name == rt.UTTERANCE.name:
                d = e.data
                self.stats[f"énoncé:{d.kind}"] += 1
                plan = self.rej.script.get(d.target or "")
                if plan is not None and d.kind in ("REPLY", "INITIATIVE"):
                    del self.rej.script[d.target]
                    self.release_at.pop((d.target, d.room), None)
                    self.lags.append((e.at - plan.at) / US)
            elif name == rt.EPISODE_ENDED.name:
                self.stats[f"fin:{e.data.kind}:{e.data.outcome}"] += 1
            elif name == rt.EPISODE_STARTED.name:
                self.stats[f"début:{e.data.kind}:{'archive' if e.data.reason == 'archive' else 'autre'}"] += 1

    async def boot(self) -> Any:
        k = await self.driver.boot()
        k.mind.subscribe(self.on_events)
        return k

    async def until(self, t: int) -> None:
        now = self.clock.now()
        if t > now:
            await asyncio.sleep((t - now) / US)

    def learn(self, items: list[Item]) -> None:
        for it in items:
            if isinstance(it, Her):
                for m in it.answers:
                    self.answered_by[m] = it

    async def incoming(self, it: In) -> Any:
        her = self.answered_by.get(it.mid)
        if her is not None and it.addressed:
            self.release_at[(it.handle, it.room)] = her.at
        external = it.handle.startswith(EXTERNAL_PREFIX)
        data = PerceptionReceived(
            handle=it.handle, channel=privacy.channel_of(it.handle), text=Content.of(it.text),
            authenticated=not external, display_name=it.name, room=it.room, public=it.room is not None,
            addressed=it.addressed, reply_ref=it.room or (it.handle[len(EXTERNAL_PREFIX):] if external else None),
        )
        got = await self.kernel.perceive(data, dedupe_key=f"archive:{it.mid}")
        self.stats["perçus"] += 1
        if got.overloaded:
            self.stats["refusés:file pleine"] += 1
        if got.held:
            self.stats["retenus"] += 1
        if got.commit is not None and got.commit.deduped:
            self.stats["dédoublonnés"] += 1
        return got

    async def her(self, it: Her) -> Any:
        self.rej.script[it.handle] = Plan(it.text, it.at, it.emotion, it.intensity)
        k = self.kernel
        if it.mode == "reply" and it.answers:
            before = self.stats["énoncé:REPLY"]
            k._release_held(k.mind.root)  # ce que le lot noyau devrait exposer (``release_held``)
            await asyncio.sleep(0)
            for _ in range(5):
                if self.stats["énoncé:REPLY"] > before or it.handle not in self.rej.script:
                    break
                await asyncio.sleep(0.2)
            if it.handle in self.rej.script:
                # rien n'était retenu (réglé entre-temps) : une réponse sans message auquel répondre
                self.stats["réponse:repli manuel"] += 1
                fut = k.lanes.submit(EpisodeRequest(kind=Kind.REPLY, target=it.handle, reason="archive", priority=0,
                                                    channel="external", room=it.room))
                return await self._settled(fut, it)
            self.stats["réponse:libérée"] += 1
            return None
        kind = Kind.INITIATIVE if it.room is None else Kind.REPLY
        fut = k.lanes.submit(EpisodeRequest(kind=kind, target=it.handle, reason="archive",
                                            priority=1 if kind == Kind.INITIATIVE else 0, channel="external",
                                            room=it.room))
        return await self._settled(fut, it)

    async def _settled(self, fut: Any, it: Her) -> Any:
        if fut is None:
            self.stats["épisode:refusé"] += 1
            self.rej.script.pop(it.handle, None)
            return None
        try:
            rep = await fut
        except Exception as exc:  # noqa: BLE001 — une mesure
            self.ecarts.append(f"{local(it.at)} {it.handle} : {type(exc).__name__} {exc}")
            self.rej.script.pop(it.handle, None)
            return None
        if rep.outcome.value != "done":
            self.ecarts.append(f"{local(it.at)} {it.handle} {it.mode} : {rep.outcome.value} {rep.detail[:80]}")
            self.rej.script.pop(it.handle, None)
        return rep

    async def play(self, items: list[Item], on_mark: Callable[[Mark], None] | None = None) -> None:
        self.learn(items)
        for it in items:
            await self.until(it.at)
            if isinstance(it, Mark):
                if on_mark:
                    on_mark(it)
            elif isinstance(it, In):
                await self.incoming(it)
            else:
                await self.her(it)
        await self.kernel.lanes.join()

    # ── lectures ──
    def person(self, handle: str) -> dict[str, Any]:
        frame = self.kernel.mind.frame()
        person = frame.get(identity_c.PERSON(handle))
        out: dict[str, Any] = {"personne": person, "proximité": frame.get(social_c.CLOSENESS(person))}
        ct = frame.get(social_c.CONTACT(person))
        out.update(jours=ct.days, reçus=ct.inbound, rythme_j=round(ct.rhythm_days, 2), ses_ouvertures=ct.her_starts,
                   leurs_ouvertures=ct.their_starts)
        st = frame.get(affect_c.STANCE(person))
        out.update(posture=str(st.felt), posture_int=round(st.felt_intensity, 2),
                   déclaré=(str(st.declared.emotion) if st.declared else None), lien=round(st.bond, 3),
                   estime=round(st.regard, 3))
        return out

    def health(self) -> dict[str, Any]:
        k = self.kernel
        loop = asyncio.get_running_loop()
        errors = getattr(loop, "errors", [])
        return {"tranches_corrompues": dict(k.mind.root.tainted.items()), "boucles_mortes": k.dead_loops(),
                "erreurs_boucle": [f"{type(e).__name__}: {e}"[:200] for e in errors[:5]],
                "n_erreurs_boucle": len(errors),
                "processus_en_erreur": {n: str(v)[:160] for n, v in list(k.scheduler.last_error.items())[:10]},
                "passages_processus": dict(sorted(k.scheduler.runs.items(), key=lambda x: -x[1])[:12])}


def journal_counts(root: Path) -> tuple[int, Counter[str]]:
    con = sqlite3.connect(root / "mind.db")
    try:
        rows = con.execute("SELECT type, count(*) FROM events GROUP BY type").fetchall()
    finally:
        con.close()
    c = Counter({t: n for t, n in rows})
    return sum(c.values()), c


def table_sizes(root: Path, db: str) -> dict[str, int]:
    """Octets par table (``dbstat`` si disponible)."""
    con = sqlite3.connect(root / db)
    try:
        rows = con.execute("SELECT name, sum(pgsize) FROM dbstat GROUP BY name ORDER BY 2 DESC").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        con.close()
    return {n: s for n, s in rows[:12]}


def fresh(name: str) -> Path:
    d = OUT / name
    if d.exists():
        shutil.rmtree(d)
    (d / "vie").mkdir(parents=True)
    return d


def dump(out: Path, data: dict[str, Any]) -> None:
    import mika  # noqa: PLC0415 — d'où vient le noyau mesuré (un instantané gelé, de préférence)
    data["_meta"] = {"mika": mika.__file__, "python": sys.version.split()[0],
                     "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS"), "écrit": datetime.now().isoformat()}
    (out / "resultats.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))


# ── 1. Débit et taille ──────────────────────────────────────────────────────


def scenario_debit(args: argparse.Namespace) -> dict[str, Any]:
    out = fresh(args.nom or f"debit-{args.par_jour:g}")
    start = at_paris(*map(int, args.debut.split("-")), 0, 0)
    arch = Archive(start, args.jours, args.par_jour, seed=args.graine)
    items = arch.items
    n_in = sum(isinstance(i, In) for i in items)
    n_her = sum(isinstance(i, Her) for i in items)
    clock = SimClock(start - HOUR)
    rej = Rejoueur(clock)
    pilot = Pilote(out / "vie", clock, rej, overrides=None if args.naturel else FAST_FORWARD)
    rows: list[dict[str, Any]] = []
    t_wall = time.perf_counter()
    res: dict[str, Any] = {}

    def on_mark(m: Mark) -> None:
        k = pilot.kernel
        sizes = db_sizes(out / "vie")
        row = {"jour": m.day, "mur_s": round(time.perf_counter() - t_wall, 2), "seq": k.mind.store.head(),
               "mind_mo": round(sizes["mind.db"] / 1e6, 2), "views_mo": round(sizes["views.db"] / 1e6, 2),
               **{k2: round(v, 1) for k2, v in mem_mb().items()}, "perçus": pilot.stats["perçus"],
               "énoncés_reply": pilot.stats["énoncé:REPLY"]}
        rows.append(row)
        if m.day % 5 == 0:
            pilot.log(f"jour {m.day:3d} {local(m.at)[:10]} : {row}")

    async def main() -> None:
        await pilot.boot()
        t0 = time.perf_counter()
        await pilot.play(items, on_mark)
        await pilot.until(clock.now() + 2 * HOUR)
        await pilot.kernel.lanes.join()
        res["mur_rejeu_s"] = time.perf_counter() - t0
        res["personnes"] = {p[0]: pilot.person(handle_of(p[0])) for p in PEOPLE}
        if args.lever and not args.naturel:
            k = pilot.kernel
            def vals() -> dict[str, Any]:
                stored = k.mind.root.slices["kernel"].params
                return {o: {key: json.loads(stored[o].data).get(key) for key in keys} for o, keys in FAST_FORWARD.items()
                        if o in stored}

            before = vals()
            changed = await compo.configure(k, pilot.persona, overrides=None)
            after = vals()
            res["levée"] = {"journalisé": changed, "avant": before, "après": after}
        res["santé"] = pilot.health()
        await pilot.driver.stop()

    run_virtual(clock, main)
    total, counts = journal_counts(out / "vie")
    sizes = db_sizes(out / "vie")
    msgs = arch.archive_messages
    res.update({
        "archive": {"jours": args.jours, "par_jour_visé": args.par_jour, "messages_archive": msgs,
                    "entrants": n_in, "ses_paroles": n_her, "par_jour_réel": round(msgs / args.jours, 1),
                    "ouvertures": sum(isinstance(i, Her) and i.mode == "open" for i in items),
                    "salon": sum(isinstance(i, In) and i.room is not None for i in items)},
        "préréglage": None if args.naturel else FAST_FORWARD,
        "mur_total_s": round(time.perf_counter() - t_wall, 1),
        "s_par_message": round(res["mur_rejeu_s"] / msgs, 4),
        "messages_par_s": round(msgs / res["mur_rejeu_s"], 1),
        "événements": total, "événements_par_message": round(total / msgs, 2),
        "événements_par_type": dict(counts.most_common(25)),
        "tailles_octets": sizes,
        "mind_mo_par_10k_messages": round(sizes["mind.db"] / 1e6 / msgs * 10_000, 2),
        "views_mo_par_10k_messages": round(sizes["views.db"] / 1e6 / msgs * 10_000, 2),
        "tables_mind": table_sizes(out / "vie", "mind.db"), "tables_views": table_sizes(out / "vie", "views.db"),
        "mémoire": mem_mb(),
        "appels_par_rôle": dict(rej.roles.most_common()), "silences_rendus": dict(rej.silences),
        "temps_rejoueur_s": {k: round(v, 2) for k, v in rej.spent.items()},
        "pilote": dict(pilot.stats.most_common()), "écarts": pilot.ecarts[:30], "n_écarts": len(pilot.ecarts),
        "délai_réponse_s": _quantiles(pilot.lags),
    })
    with (out / "jours.csv").open("w") as f:
        if rows:
            f.write(",".join(rows[0]) + "\n")
            for r in rows:
                f.write(",".join(str(v) for v in r.values()) + "\n")
    dump(out, res)
    return res


def _quantiles(xs: list[float]) -> dict[str, float]:
    if not xs:
        return {}
    s = sorted(xs)
    q = lambda p: round(s[min(len(s) - 1, int(p * len(s)))], 3)  # noqa: E731
    return {"n": len(s), "min": round(s[0], 3), "p50": q(0.5), "p90": q(0.9), "max": round(s[-1], 3)}


# ── 2. Épisodes soumis à la main ────────────────────────────────────────────


def _say(handle: str, name: str, text: str, room: str | None = None, addressed: bool = True) -> PerceptionReceived:
    return PerceptionReceived(handle=handle, channel=privacy.channel_of(handle), text=Content.of(text),
                              authenticated=False, display_name=name, room=room, public=room is not None,
                              addressed=addressed, reply_ref=room or handle[len(EXTERNAL_PREFIX):])


def _utterances(pilot: Pilote, after: int = 0) -> list[dict[str, Any]]:
    out = []
    for e in pilot.driver.read_events():
        if e.seq <= after:
            continue
        if e.type.name == rt.UTTERANCE.name:
            d = e.data
            out.append({"seq": e.seq, "à": local(e.at), "sorte": d.kind, "cible": d.target, "salon": d.room,
                        "répond_à": d.reply_to, "règle": list(d.answers), "texte": d.text.text,
                        "annotations": dict(d.annotations)})
        elif e.type.name == rt.EPISODE_ENDED.name:
            out.append({"seq": e.seq, "à": local(e.at), "fin": f"{e.data.kind}:{e.data.outcome}",
                        "cible": e.data.target, "répond_à": e.data.reply_to, "détail": e.data.detail[:100],
                        "sans_réponse": list(e.data.unanswered or ())})
        elif e.type.name.startswith(("body.", "affect.declared", "transcript.")):
            out.append({"seq": e.seq, "à": local(e.at), "événement": e.type.name})
    return out


def _last_user(req: LLMRequest) -> str:
    last = req.messages[-1].content if req.messages else ""
    return last[-700:]


def scenario_episodes(args: argparse.Namespace) -> dict[str, Any]:
    out = fresh(args.nom or "episodes")
    start = at_paris(2026, 3, 2, 9, 0)
    clock = SimClock(start)
    rej = Rejoueur(clock, keep=50)
    pilot = Pilote(out / "vie", clock, rej, overrides=FAST_FORWARD)
    res: dict[str, Any] = {}
    lea, karim, tom, julie = handle_of("lea"), handle_of("karim"), handle_of("tom"), handle_of("julie")

    async def scene(title: str, coro: Any) -> None:
        mark = pilot.kernel.mind.store.head()
        n_calls = len(rej.calls)
        detail = await coro
        prompts = [{"rôle": r.role, "cible": r.meta.get("target"), "fin_du_dernier_tour": _last_user(r)}
                   for r in list(rej.calls)[n_calls:] if r.role in ("reply", "initiative")]
        res[title] = {"journal": _utterances(pilot, mark), "ce_que_voit_le_modèle": prompts[-2:], **(detail or {})}

    async def a_initiative() -> dict[str, Any]:
        # une initiative soumise à la main, sans aucun message entrant récent (Léa n'a jamais écrit)
        await pilot.until(start + 2 * HOUR)
        rej.script[lea] = Plan("coucou Léa, tu fais quoi ce week-end ?", clock.now(), "playful", 0.6)
        fut = pilot.kernel.lanes.submit(EpisodeRequest(kind=Kind.INITIATIVE, target=lea, reason="archive",
                                                       priority=1, channel="external"))
        rep = await fut
        return {"issue": rep.outcome.value, "après": pilot.person(lea)}

    async def b_differee_silence() -> dict[str, Any]:
        # message à t, le rejoueur rend [SILENCE] (ABSTAINED), puis à t+3 h un épisode REPLY sans reply_to
        await pilot.until(start + 4 * HOUR)
        got = await pilot.kernel.perceive(_say(karim, "Karim", "tu as vu mon message pour samedi ?"))
        r1 = await got.reply
        await pilot.until(clock.now() + 3 * HOUR)
        rej.script[karim] = Plan("désolée je viens de voir ! samedi c'est bon pour moi", clock.now(), "happy", 0.5)
        r2 = await pilot.kernel.lanes.submit(EpisodeRequest(kind=Kind.REPLY, target=karim, reason="archive",
                                                            priority=0, channel="external"))
        return {"immédiate": r1.outcome.value, "différée_REPLY_sans_reply_to": r2.outcome.value,
                "après": pilot.person(karim)}

    async def c_differee_initiative() -> dict[str, Any]:
        await pilot.until(start + 9 * HOUR)
        got = await pilot.kernel.perceive(_say(karim, "Karim", "et sinon, ça va toi ?"))
        r1 = await got.reply
        await pilot.until(clock.now() + 3 * HOUR)
        rej.script[karim] = Plan("ça va et toi ? pardon j'étais au boulot", clock.now(), "relieved", 0.4)
        r2 = await pilot.kernel.lanes.submit(EpisodeRequest(kind=Kind.INITIATIVE, target=karim, reason="archive",
                                                            priority=1, channel="external"))
        return {"immédiate": r1.outcome.value, "différée_INITIATIVE": r2.outcome.value, "après": pilot.person(karim)}

    async def d_differee_retenue() -> dict[str, Any]:
        # le mécanisme retenu : retenir (reply_wait) puis libérer à l'heure de sa réponse, rafale comprise
        t = start + 13 * HOUR + 30 * MINUTE
        await pilot.until(t)
        her_at = t + 3 * HOUR
        pilot.release_at[(karim, None)] = her_at
        seqs = []
        for i, text in enumerate(("t'es dispo jeudi soir ?", "y a le concert de Pomme", "dis-moi vite stp")):
            got = await pilot.kernel.perceive(_say(karim, "Karim", text))
            seqs.append({"seq": got.seq, "retenu": got.held, "futur": got.reply is not None})
            await asyncio.sleep(40)
        await pilot.until(her_at)
        rej.script[karim] = Plan("ouiii carrément, je prends les places !", her_at, "excited", 0.8)
        pilot.kernel._release_held(pilot.kernel.mind.root)
        await asyncio.sleep(5)
        await pilot.kernel.lanes.join()
        return {"messages": seqs, "après": pilot.person(karim)}

    async def e_salon() -> dict[str, Any]:
        # au salon : des messages non adressés, un adressé (réponse automatique), puis une parole spontanée
        t = start + 20 * HOUR
        await pilot.until(t)
        await pilot.kernel.perceive(_say(tom, "Tom", "qui vient au bowling samedi ?", ROOM, addressed=False))
        await asyncio.sleep(30)
        await pilot.kernel.perceive(_say(julie, "Julie", "moi ! et toi Tom t'as réservé ?", ROOM, addressed=False))
        await asyncio.sleep(30)
        rej.script[julie] = Plan("moi je viens aussi, gardez-moi une place", clock.now() + 20 * US, "happy", 0.6)
        pilot.release_at[(julie, ROOM)] = clock.now() + 20 * US
        got = await pilot.kernel.perceive(_say(julie, "Julie", "Mika tu viens ?", ROOM, addressed=True))
        await asyncio.sleep(20)
        pilot.kernel._release_held(pilot.kernel.mind.root)
        await asyncio.sleep(2)
        await pilot.kernel.lanes.join()
        await asyncio.sleep(120)
        # parole spontanée au salon (personne ne lui parle) : REPLY sans reply_to, cible le dernier à avoir parlé
        rej.script[tom] = Plan("au fait Tom, t'as pensé aux chaussures ?", clock.now(), "playful", 0.5)
        r2 = await pilot.kernel.lanes.submit(EpisodeRequest(kind=Kind.REPLY, target=tom, reason="archive",
                                                            priority=0, channel="external", room=ROOM))
        await asyncio.sleep(60)
        rej.script[tom] = Plan("bon je vous laisse, à samedi tout le monde", clock.now(), "happy", 0.5)
        r3 = await pilot.kernel.lanes.submit(EpisodeRequest(kind=Kind.INITIATIVE, target=tom, reason="archive",
                                                            priority=1, channel="external", room=ROOM))
        return {"adressé_retenu": got.held, "spontanée_REPLY_au_salon": r2.outcome.value,
                "spontanée_INITIATIVE_au_salon": r3.outcome.value, "après_julie": pilot.person(julie),
                "après_tom": pilot.person(tom)}

    async def main() -> None:
        await pilot.boot()
        await scene("a_initiative_sans_message", a_initiative())
        await scene("b_differee_silence_puis_REPLY", b_differee_silence())
        await scene("c_differee_silence_puis_INITIATIVE", c_differee_initiative())
        await scene("d_differee_retenue_puis_liberee", d_differee_retenue())
        await scene("e_salon", e_salon())
        res["santé"] = pilot.health()
        res["livré_au_transport"] = [{"à": local(h.at), "cible": h.target, "salon": h.room, "sorte": h.kind,
                                      "émotion": h.emotion, "texte": h.text} for h in pilot.driver.transport.heard]
        await pilot.driver.stop()

    run_virtual(clock, main)
    res["pilote"] = dict(pilot.stats)
    dump(out, res)
    return res


# ── 3. La nuit ──────────────────────────────────────────────────────────────


def scenario_nuit(args: argparse.Namespace) -> dict[str, Any]:
    out = fresh(args.nom or ("nuit-sans-reveil" if args.sans_reveil else "nuit"))
    res: dict[str, Any] = {}
    # a) une amie (installée par trois semaines d'échanges) et une inconnue écrivent à 2 h
    start = at_paris(2026, 3, 1, 0, 0)
    arch = Archive(start, 20, 30, seed=3, room_share=0.0, deferred_share=0.0)
    clock = SimClock(start - HOUR)
    rej = Rejoueur(clock, keep=20)
    pilot = Pilote(out / "vie", clock, rej, overrides=FAST_FORWARD)
    lea, inconnue = handle_of("lea"), handle_of("inconnue")
    night = at_paris(2026, 3, 22, 2, 0)

    async def main() -> None:
        await pilot.boot()
        await pilot.play(arch.items)
        res["avant"] = {"léa": pilot.person(lea)}
        await pilot.until(night)
        frame = pilot.kernel.mind.frame()
        res["à_2h"] = {"sommeil": str(frame.get(body_c.SLEEP)), "phase": str(frame.get(body_c.PHASE))}
        mark = pilot.kernel.mind.store.head()
        g1 = await pilot.kernel.perceive(_say(lea, "Léa", "tu dors ? j'arrive pas à dormir"))
        await asyncio.sleep(1)
        r1 = await g1.reply if g1.reply is not None else None
        await asyncio.sleep(10 * 60)
        g2 = await pilot.kernel.perceive(_say(inconnue, "Inconnue", "bonsoir, on se connaît ? j'ai eu ton numéro"))
        r2 = await g2.reply if g2.reply is not None else None
        res["message_amie"] = {"retenu": g1.held, "issue": r1.outcome.value if r1 else None}
        res["message_inconnue"] = {"retenu": g2.held, "issue": r2.outcome.value if r2 else None}
        # un épisode soumis à la main la nuit (une réponse à l'inconnue qu'elle aurait écrite à 2 h 30)
        await pilot.until(night + 30 * MINUTE)
        rej.script[inconnue] = Plan("euh non je crois pas, c'est qui ?", clock.now(), "confused", 0.5)
        r3 = await pilot.kernel.lanes.submit(EpisodeRequest(kind=Kind.REPLY, target=inconnue, reason="archive",
                                                            priority=0, channel="external"))
        res["épisode_manuel_la_nuit"] = {"issue": r3.outcome.value, "texte": r3.text}
        frame = pilot.kernel.mind.frame()
        res["après_épisode_manuel"] = {"sommeil": str(frame.get(body_c.SLEEP))}
        await pilot.until(night + 8 * HOUR)
        await pilot.kernel.lanes.join()
        res["journal_de_la_nuit"] = _utterances(pilot, mark)
        res["santé"] = pilot.health()
        await pilot.driver.stop()

    run_virtual(clock, main)

    # b) le chronotype : trois nuits sans personne, trois tempéraments
    res["chronotype"] = {}
    for chrono in (0.0, 0.5, 1.0):
        d = out / f"chrono-{chrono}"
        (d / "vie").mkdir(parents=True)
        clock = SimClock(at_paris(2026, 3, 2, 12, 0))
        p = Pilote(d / "vie", clock, Rejoueur(clock), overrides=FAST_FORWARD, chronotype=chrono)
        sleeps: list[str] = []

        async def nights(p: Pilote = p, clock: SimClock = clock, sleeps: list[str] = sleeps) -> None:
            await p.boot()
            await p.until(clock.now() + 4 * DAY)
            for e in p.driver.read_events():
                if e.type.name in (body_c.FELL_ASLEEP.name, body_c.WOKE.name):
                    sleeps.append(f"{e.type.name.split('.')[1]} {local(e.at)}")
            await p.driver.stop()

        run_virtual(clock, nights)
        res["chronotype"][str(chrono)] = sleeps
    dump(out, res)
    return res


# ── 4. Vie spontanée ─────────────────────────────────────────────────────────


def scenario_spontane(args: argparse.Namespace) -> dict[str, Any]:
    out = fresh(args.nom or "spontane")
    res: dict[str, Any] = {}
    start = at_paris(2026, 4, 6, 0, 0)
    for label, overrides in (("naturel", None), ("avance_rapide", FAST_FORWARD)):
        d = out / label
        (d / "vie").mkdir(parents=True)
        arch = Archive(start, args.jours, args.par_jour, seed=11)
        clock = SimClock(start - HOUR)
        rej = Rejoueur(clock, natural=True)
        p = Pilote(d / "vie", clock, rej, overrides=overrides)
        got: dict[str, Any] = {}

        async def main(p: Pilote = p, arch: Archive = arch, got: dict[str, Any] = got, clock: SimClock = clock) -> None:
            await p.boot()
            if overrides:
                planned = params_mod.plan(list(p.kernel.registry.faculties.values()), p.persona.temperament,
                                          overrides)
                got["refusées"] = {o: dict(pl.refused) for o, pl in planned.items() if pl.refused}
                got["en_vigueur"] = {o: {k: params_mod.forms.flatten(planned[o].value).get(k) for k in v}
                                     for o, v in overrides.items()}
            await p.play(arch.items)
            await p.until(clock.now() + 3 * HOUR)
            await p.kernel.lanes.join()
            got["santé"] = p.health()
            await p.driver.stop()

        run_virtual(clock, main)
        _total, counts = journal_counts(d / "vie")
        spont = {k: v for k, v in p.stats.items() if k.startswith(("début:", "fin:", "énoncé:"))}
        res[label] = {"appels_par_rôle": dict(rej.roles.most_common()), "épisodes": dict(sorted(spont.items())),
                      "buts_ouverts": counts.get("goals.opened", 0), "murmures": counts.get("expression.murmured", 0),
                      "sélections_arbitre": counts.get("kernel.selected", 0), **got}
    res["jours"] = args.jours
    dump(out, res)
    return res


# ── 5. Une horloge qui part du passé, et la reprise ─────────────────────────


def scenario_passe(args: argparse.Namespace) -> dict[str, Any]:
    out = fresh(args.nom or "passe")
    res: dict[str, Any] = {}
    start = at_paris(2008, 3, 27, 0, 0)  # le passage à l'heure d'été 2008 (30 mars) tombe dedans
    arch = Archive(start, args.jours, args.par_jour, seed=5)
    half = start + (args.jours // 2) * DAY + 3 * HOUR
    first = [i for i in arch.items if i.at < half]
    second = [i for i in arch.items if i.at >= half]
    clock = SimClock(start - HOUR)
    rej = Rejoueur(clock)
    pilot = Pilote(out / "vie", clock, rej, overrides=FAST_FORWARD, boots=0)

    saved: dict[str, Any] = {}

    async def part1() -> None:
        await pilot.boot()
        await pilot.play(first)
        res["partie_1"] = {"santé": pilot.health(), "tête": pilot.kernel.mind.store.head(),
                           "léa": pilot.person(handle_of("lea")), "pilote": dict(pilot.stats)}
        # un « plantage » en plein vol : un message retenu dont la réponse ne viendra qu'après la reprise
        her_at = clock.now() + 20 * MINUTE
        pilot.release_at[(handle_of("karim"), None)] = her_at
        got = await pilot.kernel.perceive(_say(handle_of("karim"), "Karim", "tu me rappelles quand t'es dispo ?"),
                                          dedupe_key="archive:karim-crash")
        saved.update(release_at=dict(pilot.release_at), her_at=her_at, seq=got.seq, held=got.held)
        await pilot.driver.crash()

    run_virtual(clock, part1)
    con = sqlite3.connect(out / "vie" / "mind.db")
    head_at, head_seq = con.execute("SELECT max(at), max(seq) FROM events").fetchone()
    con.close()
    res["tête_après_plantage"] = {"seq": head_seq, "at": local(head_at), "question_retenue": saved["seq"],
                                  "retenue": saved["held"], "sa_réponse_prévue": local(saved["her_at"])}
    # reprise : une nouvelle horloge part de la tête du journal (et non de l'heure du mur) ; le pilote restaure son
    # état (ce qui est retenu jusqu'à quand) AVANT le démarrage, pour que la reprise du noyau (``recover``) le voie
    clock2 = SimClock(head_at + US)
    rej2 = Rejoueur(clock2)
    pilot2 = Pilote(out / "vie", clock2, rej2, overrides=FAST_FORWARD, boots=1)
    pilot2.release_at.update(saved["release_at"])

    async def part2() -> None:
        k = await pilot2.boot()
        res["reprise"] = {"tête": k.mind.store.head(), "phase": k.phase, "retenus_par_le_noyau": sorted(k._held)}
        mark = head_seq
        # le pilote rejoue les deux dernières heures (idempotence : tout doit être dédoublonné)
        pilot2.learn(arch.items)
        replay = [i for i in first if i.at >= head_at - 2 * HOUR and isinstance(i, In)]
        for it in replay:
            await pilot2.incoming(it)
        res["rejeu_après_reprise"] = {"messages_renvoyés": len(replay), "pilote": dict(pilot2.stats)}
        # sa réponse à la question retenue, à l'heure prévue
        await pilot2.until(saved["her_at"])
        rej2.script[handle_of("karim")] = Plan("je te rappelle ce soir promis", saved["her_at"], "happy", 0.5)
        k._release_held(k.mind.root)
        await asyncio.sleep(2)
        await k.lanes.join()
        res["réponse_après_reprise"] = [x for x in _utterances(pilot2, mark)
                                        if x.get("cible") == handle_of("karim")][:6]
        await pilot2.play(second)
        await pilot2.until(clock2.now() + 2 * HOUR)
        res["partie_2"] = {"santé": pilot2.health(), "tête": pilot2.kernel.mind.store.head(),
                           "léa": pilot2.person(handle_of("lea")), "pilote": dict(pilot2.stats),
                           "écarts": pilot2.ecarts[:10]}
        await pilot2.driver.stop()

    run_virtual(clock2, part2)
    total, counts = journal_counts(out / "vie")
    con = sqlite3.connect(out / "vie" / "mind.db")
    try:
        outbox = con.execute("SELECT status, count(*) FROM outbox GROUP BY status").fetchall()
        boots = con.execute("SELECT seq, at FROM events WHERE type='kernel.boot'").fetchall()
        first_at, last_at = con.execute("SELECT min(at), max(at) FROM events").fetchone()
        backwards = con.execute("SELECT count(*) FROM events a JOIN events b ON b.seq = a.seq + 1 "
                                "WHERE b.at < a.at").fetchone()[0]
    finally:
        con.close()
    res.update({"événements": total, "par_type": dict(counts.most_common(12)), "file_de_sortie": dict(outbox),
                "démarrages": [(s, local(a)) for s, a in boots], "premier": local(first_at),
                "dernier": local(last_at), "instants_à_rebours": backwards,
                "journaux_intimes": counts.get("self.journaled", 0), "rêves": counts.get("self.dreamt", 0)})
    dump(out, res)
    return res


SCENARIOS = {"debit": scenario_debit, "episodes": scenario_episodes, "nuit": scenario_nuit,
             "spontane": scenario_spontane, "passe": scenario_passe}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scenario", choices=sorted(SCENARIOS))
    ap.add_argument("--jours", type=int, default=60)
    ap.add_argument("--par-jour", type=float, default=40)
    ap.add_argument("--debut", default="2026-01-05", help="AAAA-MM-JJ (débit)")
    ap.add_argument("--graine", type=int, default=7)
    ap.add_argument("--naturel", action="store_true", help="débit sans le préréglage avance rapide")
    ap.add_argument("--nom", default="")
    ap.add_argument("--sans-reveil", action="store_true", help="préréglage + body.woken_by=() (personne ne la réveille)")
    ap.add_argument("--lever", action="store_true", help="débit : lever le préréglage à l'arrivée et le vérifier")
    ap.add_argument("--profil", action="store_true", help="profiler (cProfile) : out/<nom>/profil.txt")
    args = ap.parse_args(argv)
    if args.sans_reveil:
        FAST_FORWARD["body"] = {"woken_by": []}
    t0 = time.perf_counter()
    if args.profil:
        import cProfile  # noqa: PLC0415
        import io  # noqa: PLC0415
        import pstats  # noqa: PLC0415
        prof = cProfile.Profile()
        res = prof.runcall(SCENARIOS[args.scenario], args)
        buf = io.StringIO()
        st = pstats.Stats(prof, stream=buf)
        st.sort_stats("cumulative").print_stats(60)
        st.sort_stats("tottime").print_stats(40)
        name = args.nom or f"{args.scenario}"
        (OUT / name / "profil.txt").write_text(buf.getvalue())
    else:
        res = SCENARIOS[args.scenario](args)
    brief = {k: v for k, v in res.items() if not isinstance(v, (dict, list)) or k in (
        "appels_par_rôle", "pilote", "délai_réponse_s", "tailles_octets", "mémoire")}
    print(json.dumps(brief, ensure_ascii=False, indent=1, default=str)[:6000])
    print(f"({time.perf_counter() - t0:.1f} s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONHASHSEED", "0")
    raise SystemExit(main())
