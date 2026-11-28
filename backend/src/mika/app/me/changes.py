"""Le direct (ADR 0308) : ce qui change ce que montrent les écrans de tous les jours leur est poussé, sur le ``/ws``
que chacun a déjà ouvert — une trame ``changed`` qui dit quoi a changé, jamais le contenu ; l'écran relit la route
qu'il montre (``docs/protocole-moi.md``, § 2 bis).

- **D'où ça vient.** Du journal (``listen``, abonné à ``Mind.subscribe`` : chaque lot commité, traduit type par type
  en sujets) ; des bases tenues à côté — le courrier relevé, le cache de Teams, l'annuaire (``touch``, leur
  ``on_change`` : appelé une fois l'écriture validée, depuis n'importe quel fil) ; de l'étape d'un épisode, qui ne vit
  qu'en mémoire (``step``, ``EpisodeRunner.on_step``) ; des comptes (``everyone`` : un nom, un téléphone).
- **Regroupé.** La première touche arme un délai (``WINDOW_S``) ; tout ce qui arrive pendant ce délai part ensemble.
  Un sujet qui revient sans cesse (une boîte qu'on range, une étape après l'autre) part au plus ``BURST`` fois d'affilée,
  puis une fois par ``GAP_S`` : ce qui attend n'est jamais perdu, il part dès que son sujet le peut.
- **Seulement ce que chacune peut voir.** À l'envoi, pour chaque personne connectée — et chaque canal de ses clients,
  car ce qu'elle voit d'un projet en dépend —, le service relit ce qu'elle a par les règles mêmes des routes
  (ce que dit la part du direct d'un domaine qui a sa fiche : ``LivePart.levels``, ``seen``, ``judge``, ADR 0310)
  et ne garde que ses ressources : une boîte, une conversation, un projet d'une autre n'y paraissent jamais. Ce qu'on ne sait
  pas nommer part sans clé, seulement à qui a quelque chose dans ce domaine. Ce qui change qui voit quoi — les
  propriétaires et les partages d'une boîte, d'un compte Teams, les accès d'un projet, une adresse reliée à une
  personne, un réglage enregistré — part sans clé à toutes : le filtre lit l'état d'après, et celle qui vient de perdre
  l'accès doit le savoir aussi. Une règle qui lève ne prive pas les autres : ce qu'elle gardait ne part pas.
- **Hors de la boucle.** Ces règles lisent l'annuaire et le cache de Teams, que leurs écritures tiennent sous leur
  verrou le temps d'un lot : elles tournent dans un fil, sur l'état lu une fois et sur les comptes que les réglages
  disent (lus une fois par envoi, sur la boucle). Une seule relecture à la fois ; ce qui arrive pendant ce temps part
  avec la suivante.
- **Envoyé en parallèle.** Chaque personne reçoit sa trame sans attendre les autres, en ``SEND_TIMEOUT_S`` au plus ; ce
  qui lui est dit pendant qu'une trame lui part s'y ajoute et part juste après, en une — rien ne s'empile.
- **Rien n'est rattrapé.** Personne de connecté : rien ne se calcule. Le client relit tout à sa reconnexion.
- **Par domaine** (ADR 0310). La forme d'une touche est dans ``touches.py`` ; ce qu'un domaine change et ce que
  chacune en voit, dans la part du direct de sa fiche (``PARTS``). Ce service les réunit sans en nommer aucun.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mika.adapters.web.accounts import Account
from mika.adapters.web.hub import Hub
from mika.app.domains import DOMAINS, gathered, part
from mika.app.me.api import Call, me_of
from mika.app.me.common import allows
from mika.app.me.touches import EVERYONE, OWN, PERSON, READ, Touch
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.kernel.builtin import KERNEL, PARAMS_CHANGED
from mika.ports.changes import (
    KEYS,
    PROJECTS,
    SETTINGS,
    TOPICS,
    Change,
)
from mika.runtime.boundary import Failed, acall, call
from mika.runtime.state import RUNTIME
from mika.vocab.episodes import Kind, task_of
from mika.vocab.ownership import OWNED

log = logging.getLogger("mika.live")

#: ce qui arrive pendant ce délai après la première touche part en une trame (s)
WINDOW_S = 0.15
#: un même sujet part au plus ``BURST`` fois d'affilée, puis une fois par ``GAP_S`` (s) tant qu'il revient : une boîte
#: qu'on range des heures durant ne fait pas relire chaque écran toutes les 150 ms
GAP_S = 1.0
BURST = 3
#: une trame à une personne part en ce délai au plus (s) : une connexion lente ne retient ni les autres ni la suite
SEND_TIMEOUT_S = 5.0

#: ce que chaque domaine apporte au direct (ADR 0310) : la part de sa fiche, dans l'ordre des fiches, et qui l'apporte
BROUGHT = tuple((f"le domaine « {d.name} »", part(d.live, "LIVE")) for d in DOMAINS if d.live is not None)
PARTS = tuple(brought for _, brought in BROUGHT)
# chaque table réunit ce que disent les parts (``gathered``) : un nom que deux parts disent est refusé à l'import,
# au lieu que la dernière l'emporte sans bruit
#: sujet d'une base tenue à côté → la traduction de son domaine ; règle d'une touche → ce que la personne en voit
CHANGES = gathered("un sujet de LivePart.changes", ((who, p.changes) for who, p in BROUGHT))
SEEN = gathered("une règle de LivePart.seen", ((who, p.seen) for who, p in BROUGHT))
#: règle → les niveaux de la personne sur ses propriétaires ; règle → le propriétaire d'une clé
LEVELS = gathered("une règle de LivePart.levels", ((who, p.levels) for who, p in BROUGHT))
OWNER_OF = gathered("une règle de LivePart.owner_of", ((who, p.owner_of) for who, p in BROUGHT))
#: règle → son propre jugement
JUDGE = gathered("une règle de LivePart.judge", ((who, p.judge) for who, p in BROUGHT))
#: port du noyau → ses comptes, à lire une fois par envoi sur la boucle
LISTED = gathered("un port de LivePart.listed", ((who, p.listed) for who, p in BROUGHT))
#: propriétaire d'une tâche → où elle en est (la traduction de son domaine)
TASKS = gathered("un propriétaire de LivePart.tasks", ((who, p.tasks) for who, p in BROUGHT))

#: ce que change le réglage d'un propriétaire (``kernel.params_changed``) : qui voit quoi, ce qui se règle — à toutes
PARAMS: Mapping[str, tuple[str, ...]] = gathered("un propriétaire de LivePart.params",
                                                 ((who, p.params) for who, p in BROUGHT))

#: ce qu'un réglage enregistré hors du journal change (``Settings._put``, par sa clé), à toutes, sans clé ; tout autre
#: réglage, Paramètres seulement
SAVED: Mapping[str, tuple[str, ...]] = gathered("une clé de LivePart.saved",
                                                ((who, p.saved) for who, p in BROUGHT))


# ── du journal ────────────────────────────────────────────────────────────


def _work(kind: str, target: str | None, frame: Any, kernel: Any, *, boundary: bool) -> list[Touch]:
    """Où elle en est d'une réponse (ADR 0306) : la tâche d'un domaine qui a sa fiche (un mail, un message de
    Teams) ; et, au départ et à la fin d'un épisode (``boundary`` ; faux à une étape), ce qu'en dit un domaine qui
    a sa fiche (une exécution d'un projet)."""
    found = task_of(target) if kind == Kind.TASK else None
    if found is not None and found[0] in TASKS:  # la tâche d'un domaine qui a sa fiche
        return list(TASKS[found[0]](found[1], frame, kernel))
    if boundary:  # le départ, la fin d'un épisode : ce qu'un domaine qui a sa fiche en dit (``LivePart.episodes``)
        return [t for brought in PARTS if brought.episodes is not None
                for t in brought.episodes(kind, target, frame, kernel)]
    return []


def _effect(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    """Un brouillon proposé, décidé, parti : celui d'un domaine qui a sa fiche (une boîte, un compte Teams, le
    téléphone, un agenda), reconnu par sa proposition ; un accord d'un projet, par le contexte de l'événement."""
    d = e.data
    proposal = e.seq if e.type is rt.EFFECT_PROPOSED else d.proposal
    for brought in PARTS:  # l'effet d'un domaine qui a sa fiche : le premier qui le reconnaît dit ses touches
        mine = brought.effects(proposal, frame, kernel, e) if brought.effects is not None else None
        if mine is not None:
            return list(mine)
    return []


def _runtime(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    if e.type in (rt.EFFECT_PROPOSED, rt.EFFECT_RESOLVED, rt.EFFECT_EXECUTED):
        return _effect(e, frame, kernel)
    if e.type in (rt.EPISODE_STARTED, rt.EPISODE_ENDED):
        return _work(e.data.kind, e.data.target, frame, kernel, boundary=True)
    return []


def _kernel(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    if e.type is not PARAMS_CHANGED:
        return []
    return [Touch(topic, EVERYONE) for topic in PARAMS.get(e.data.owner, ())]


def _identity(e: Any, frame: Any, kernel: Any) -> list[Touch]:
    """Une adresse reliée à une personne (ou déliée) : à qui elle est (``me.person``) change ce qui est à elle dans
    chaque domaine — les boîtes et les comptes « personne:… », son téléphone, sa position, ses voyages, ses contacts,
    ses projets. Rare : tous les domaines, à toutes, sans clé."""
    return [Touch(topic, EVERYONE) for topic in TOPICS] if e.type is identity_c.LINKED else []


#: chaque propriétaire d'événements dont le journal change ce que montrent les écrans, et sa traduction : ceux du
#: cadre, puis ceux des parts — un propriétaire que deux disent est refusé
BY_OWNER = gathered("un propriétaire de LivePart.events", [
    ("le cadre", {rt.OWNER: _runtime, KERNEL.name: _kernel, identity_c.OWNER: _identity}),
    *((who, p.events) for who, p in BROUGHT)])


def touches_of(events: Iterable[Any], frame: Any, kernel: Any) -> list[Touch]:
    """Ce qu'un lot commité change, traduit événement par événement (``frame`` : l'état juste après) ; un événement
    qui ne se traduit pas (une panne de sa traduction) ne prive pas les autres."""
    out: list[Touch] = []
    for e in events:
        translate = BY_OWNER.get(e.type.owner)
        if translate is None:
            continue
        got = call(translate, e, frame, kernel, label=f"le direct ({e.type.name})")
        if not isinstance(got, Failed):
            out += got
    return out


# ── des bases tenues à côté ───────────────────────────────────────────────


def touches_from(change: Change) -> list[Touch]:
    """Ce qu'une écriture d'une base tenue à côté change : ses boîtes, ses comptes et ses conversations, ses sources —
    la traduction du domaine qui la tient."""
    translate = CHANGES.get(change.topic)
    return list(translate(change)) if translate is not None else []




# ── ce que chacune voit ───────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Listed:
    """Les comptes d'un port (des boîtes, des comptes Teams) tels que ses réglages les disent, lus une fois sur la
    boucle : ce que les règles des routes en lisent (``held_by``, ``contacts.reach``), sans base ni verrou."""

    found: tuple[Any, ...]

    def accounts(self) -> list[Any]:
        return list(self.found)


class Seen(Call):
    """Ce qu'une route de son espace lirait, sans requête, sur un état lu une fois (``frame``) et sur les comptes que
    les réglages disent (``ports`` : ``Listed``, lus sur la boucle) — ce que le direct relit dans un fil : rien n'y
    touche la base de son journal, que seule la boucle lit."""

    __slots__ = ("_frame", "_ports")

    def __init__(self, me: Any, kernel: Any, api: Any, frame: Any, ports: Mapping[str, Any]) -> None:
        super().__init__(None, me, kernel, {}, api)  # type: ignore[arg-type]
        self._frame = frame
        self._ports = dict(ports)

    @property
    def frame(self) -> Any:
        return self._frame

    def port(self, name: str) -> Any:
        return self._ports[name] if name in self._ports else super().port(name)


@dataclass(slots=True)
class Reader:
    """Ce qu'une personne voit, par ce canal, lu par les règles des routes — chaque domaine une fois, à la demande. Une
    règle qui lève ne voit rien (rien de ce qu'elle gardait ne part) et ne prive pas les autres."""

    call: Call
    channel: str
    _seen: dict[str, Any] = field(default_factory=dict)

    def once(self, name: str, read: Any, empty: Any) -> Any:
        """Ce que lit la règle d'un domaine (``LivePart.judge``), une fois par personne et par envoi ; illisible :
        ``empty``."""
        return self._once(name, read, empty)

    def _once(self, name: str, read: Any, empty: Any) -> Any:
        if name not in self._seen:
            got = call(read, label=f"le direct ({name})")
            self._seen[name] = empty if isinstance(got, Failed) else got
        return self._seen[name]

    def levels(self, rule: str) -> dict[str, str]:
        """Ce qu'elle tient par la règle d'un domaine (ses boîtes, ses comptes Teams) : la clé et son niveau (les
        siens, ceux qu'on lui partage), comme le dit sa part du direct (``LivePart.levels``) ; une règle que
        personne ne dit : rien."""
        if rule not in LEVELS:
            return {}
        return self._once(rule, lambda: dict(LEVELS[rule](self.call)), {})

    def judge(self, t: Touch) -> tuple[bool, tuple[str, ...]]:
        """Cette touche la concerne-t-elle, et ce qu'elle peut en voir nommé."""
        me = self.call.me
        if t.rule == EVERYONE:
            return True, ()
        if t.rule in JUDGE:  # la règle d'un domaine qui juge elle-même
            return JUDGE[t.rule](self, t)
        if t.rule == PERSON:
            mine = me.handle in t.owners or me.person in t.owners
            return mine, t.keys if mine else ()
        if t.rule in SEEN:  # la règle d'un domaine : ce que sa part du direct dit qu'elle voit
            seen = self._once(t.rule, lambda: frozenset(SEEN[t.rule](self.call)), frozenset())
        else:
            seen = frozenset(a for a, level in self.levels(t.rule).items()
                             if t.need == READ or (level == OWNED if t.need == OWN else allows(level, t.need)))
        if t.keys:
            kept = tuple(k for k in t.keys if _owner_of(t, k) in seen)
            return bool(kept), kept
        return (bool(seen & set(t.owners)) if t.owners else bool(seen)), ()

    def changes(self, touches: Sequence[Touch]) -> list[dict[str, Any]]:
        """La trame de cette personne : un sujet par élément, dans l'ordre du contrat ; un sujet sans clé dit tout son
        domaine et l'emporte sur ce qu'on y nommait."""
        found: dict[str, set[Any] | None] = {}
        for t in sorted(touches, key=lambda t: t.weak):  # une touche faible après les autres : elle ne les efface pas
            got = call(self.judge, t, label="le direct (une règle)")
            if isinstance(got, Failed):
                continue
            mine, keys = got
            if mine and not (t.weak and t.topic in found):
                _add_keys(found, t.topic, keys)
        return _ordered(found)


def _add_keys(found: dict[str, set[Any] | None], topic: str, keys: Iterable[Any]) -> None:
    """Ce sujet, avec ces clés (aucune : tout le domaine, qui l'emporte)."""
    keys = tuple(keys)
    if not keys or topic not in KEYS:
        found[topic] = None
    elif (known := found.get(topic, set())) is not None:
        found[topic] = known | set(keys)


def _ordered(found: Mapping[str, set[Any] | None]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for topic in TOPICS:
        if topic not in found:
            continue
        keys = found[topic]
        item: dict[str, Any] = {"topic": topic}
        if keys:
            item[KEYS[topic]] = sorted(int(k) for k in keys) if topic == PROJECTS else sorted(keys)
        out.append(item)
    return out


def merged(*frames: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Plusieurs trames d'une même personne en une : les clés d'un sujet s'ajoutent, un sujet sans clé l'emporte."""
    found: dict[str, set[Any] | None] = {}
    for frame in frames:
        for item in frame:
            topic = str(item["topic"])
            name = KEYS.get(topic)
            _add_keys(found, topic, item.get(name) or () if name else ())
    return _ordered(found)


def _owner_of(t: Touch, key: str) -> str:
    """Le compte d'une clé : sa clé même, sauf quand la règle d'un domaine qui a sa fiche le dit elle-même
    (``LivePart.owner_of`` : la boîte d'un mail, le compte d'une conversation Teams)."""
    if t.rule in OWNER_OF:
        return str(OWNER_OF[t.rule](t.topic, key))
    return key


# ── le service ────────────────────────────────────────────────────────────

#: à qui va une trame : une personne (son adresse) et le canal de ses clients
Recipient = tuple[str, str]


class LiveChanges:
    """Ce qui change, regroupé puis poussé à chaque personne connectée, filtré par ses droits (ADR 0308). ``api`` :
    l'API par personne (ce que ses routes lisent) ; ``window_s`` : le regroupement ; ``gap_s`` et ``burst`` : le rythme
    d'un même sujet (``gap_s`` nul : aucun) ; ``send_timeout_s`` : l'attente d'un envoi.

    Ce qui arrive (``_add``, de n'importe quel fil) attend le délai du regroupement, puis passe par le rythme de son
    sujet (``_admit``, sur la boucle : ce qui doit attendre son tour est gardé, ``_held``) ; ce qui peut partir est
    relu par une seule tâche à la fois (``_drain`` : les règles dans un fil), puis confié à chaque personne
    (``_deliver`` : une trame en vol par personne et par canal, ce qui suit s'y ajoute)."""

    def __init__(self, kernel: Any, hub: Hub, api: Any = None, *, window_s: float = WINDOW_S, gap_s: float = GAP_S,
                 burst: int = BURST, send_timeout_s: float = SEND_TIMEOUT_S) -> None:
        self.kernel = kernel
        self.hub = hub
        self.api = api
        self.window_s = window_s
        self.gap_s = gap_s
        self.burst = max(1, burst)
        self.send_timeout_s = send_timeout_s
        self._lock = threading.Lock()
        self._pending: list[Touch] = []
        self._armed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        # le reste ne se touche que sur la boucle
        self._held: list[Touch] = []
        self._held_timer: asyncio.TimerHandle | None = None
        #: par sujet : ce qu'il lui reste d'envois d'affilée, et quand on l'a compté (horloge de la boucle)
        self._budget: dict[str, tuple[float, float]] = {}
        self._ready: list[Touch] = []
        self._sender: asyncio.Task[None] | None = None
        #: par personne et canal dont une trame est en vol : ce qui partira juste après, en une
        self._waiting: dict[Recipient, list[dict[str, Any]]] = {}
        self._tasks: set[asyncio.Task[Any]] = set()

    def start(self) -> None:
        """Sur la boucle du serveur : avant, rien ne part (la relecture de sa vie ne prévient personne)."""
        self._loop = asyncio.get_running_loop()

    async def stop(self) -> None:
        self._loop = None
        with self._lock:
            self._pending, self._armed = [], False
        if self._held_timer is not None:
            self._held_timer.cancel()
            self._held_timer = None
        self._held, self._ready = [], []
        for task in [*self._tasks, *([self._sender] if self._sender is not None else [])]:
            task.cancel()
        self._waiting.clear()

    # ── ce qui le prévient ──
    def listen(self, events: Sequence[Any], root: Any) -> None:
        """Un lot commité (``Mind.subscribe``, sur la boucle) : traduit, s'il y a quelqu'un à prévenir."""
        if self._loop is None or not self.hub.signed_in():
            return
        found = call(touches_of, events, self.kernel.mind.frame(), self.kernel, label="le direct (journal)")
        if not isinstance(found, Failed):
            self._add(found)

    def touch(self, change: Change) -> None:
        """Une écriture validée d'une base tenue à côté (``on_change``), depuis n'importe quel fil."""
        self._add(touches_from(change))

    def step(self, episode: str) -> None:
        """L'étape d'un épisode a changé (``EpisodeRunner.on_step``) : sa tâche sur un mail ou un message de Teams."""
        if self._loop is None or not self.hub.signed_in():
            return
        frame = self.kernel.mind.frame()
        opened = frame.state(RUNTIME.name).open.get(episode)
        if opened is not None:
            self._add(_work(opened.kind, opened.target, frame, self.kernel, boundary=False))

    def add(self, touches: Sequence[Touch]) -> None:
        """Ce qu'un domaine signale de lui-même, hors du journal et de ses bases (la présence d'une extension, une
        connexion qui aboutit) : ses touches, depuis n'importe quel fil."""
        self._add(touches)

    def everyone(self, *topics: str) -> None:
        """Ce qui change pour qui que ce soit sans rien nommer (un compte, ses téléphones) : à toutes, sans clé."""
        self._add([Touch(topic, EVERYONE) for topic in topics])

    def saved(self, key: str) -> None:
        """Un réglage enregistré hors du journal (``Settings.on_saved``, par sa clé) : ce qu'il change, à toutes."""
        self.everyone(*SAVED.get(key, (SETTINGS,)))

    # ── le regroupement ──
    def _add(self, touches: Sequence[Touch]) -> None:
        loop = self._loop
        if not touches or loop is None:
            return
        with self._lock:
            self._pending.extend(touches)
            if self._armed:
                return
            self._armed = True
        try:
            loop.call_soon_threadsafe(self._arm)
        except RuntimeError:  # la boucle s'est arrêtée : plus personne à prévenir
            with self._lock:
                self._pending, self._armed = [], False

    def _arm(self) -> None:
        if self._loop is not None:
            self._loop.call_later(self.window_s, self._fire)

    def _fire(self) -> None:
        with self._lock:
            touches, self._pending, self._armed = self._pending, [], False
        if touches:
            self._admit(touches)

    # ── le rythme d'un sujet ──
    def _spend(self, topic: str, now: float) -> bool:
        """Ce sujet peut-il partir maintenant ? Il a ``burst`` envois d'affilée, qui reviennent un par ``gap_s``."""
        if self.gap_s <= 0:
            return True
        left, at = self._budget.get(topic, (float(self.burst), now))
        left = min(float(self.burst), left + (now - at) / self.gap_s)
        ok = left >= 1 - 1e-9
        self._budget[topic] = (left - 1 if ok else left, now)
        return ok

    def _admit(self, touches: Sequence[Touch]) -> None:
        """(Sur la boucle.) Ce qui attendait son tour et ce qui arrive : ce dont le sujet peut partir part (toutes
        ses touches ensemble) ; le reste attend le premier tour qui revient."""
        loop = self._loop
        if loop is None:
            return
        pool = list(dict.fromkeys([*self._held, *touches]))
        self._held = []
        if self._held_timer is not None:
            self._held_timer.cancel()
            self._held_timer = None
        now = loop.time()
        go: list[Touch] = []
        spent: set[str] = set()
        refused: set[str] = set()
        for t in pool:
            if t.topic not in spent and t.topic not in refused:
                (spent if self._spend(t.topic, now) else refused).add(t.topic)
            (go if t.topic in spent else self._held).append(t)
        if self._held:
            due = min(at + max(0.0, 1 - left) * self.gap_s
                      for left, at in (self._budget[topic] for topic in refused))
            self._held_timer = loop.call_at(due, self._unhold)
        if go:
            self._ready.extend(go)
            if self._sender is None or self._sender.done():
                self._sender = loop.create_task(self._drain())

    def _unhold(self) -> None:
        self._held_timer = None
        self._admit([])

    # ── l'envoi ──
    async def _drain(self) -> None:
        """Une relecture à la fois : ce qui est prêt pendant qu'elle tourne part avec la suivante."""
        while self._ready:
            batch, self._ready = self._ready, []
            await acall(self._dispatch, batch, label="le direct (envoi)")

    async def send(self, touches: Sequence[Touch]) -> int:
        """Ces touches, à chaque personne connectée (par canal), ce qu'elle en voit ; rend combien de trames sont
        parties (ce qui s'ajoute à une trame déjà en vol part avec elle, sans être compté ici)."""
        tasks = await self._dispatch(touches)
        return sum(await asyncio.gather(*tasks)) if tasks else 0

    async def _dispatch(self, touches: Sequence[Touch]) -> list[asyncio.Task[int]]:
        said = await self._judged(touches)
        return [task for task in (self._deliver(key, changes) for key, changes in said.items()) if task is not None]

    def _listed(self) -> dict[str, Listed]:
        """(Sur la boucle.) Les boîtes et les comptes Teams que disent les réglages, lus une fois pour cet envoi : leur
        lecture passe par la base du journal, que seule la boucle lit. Illisibles : aucun (rien ne part qui les nomme)."""
        out: dict[str, Listed] = {}
        for name, read in LISTED.items():
            port = self.kernel.ports.get(name)
            if port is not None:
                got = call(functools.partial(read, port), label=f"le direct (les comptes de {name})")
                out[name] = Listed(() if isinstance(got, Failed) else tuple(got))
        return out

    async def _judged(self, touches: Sequence[Touch]) -> dict[Recipient, list[dict[str, Any]]]:
        """Ce que chaque personne connectée en voit, par canal : les règles des routes, dans un fil."""
        groups: dict[Recipient, Any] = {}
        for conn in self.hub.signed_in():
            groups.setdefault((conn.handle, conn.channel), conn)
        if not groups:
            return {}
        frame = self.kernel.mind.frame()
        ports = self._listed()
        readers = {key: Reader(Seen(me_of(frame, Account(int(conn.account), "", conn.display_name, conn.operator,
                                                         True)), self.kernel, self.api, frame, ports), key[1])
                   for key, conn in groups.items()}

        def judge() -> dict[Recipient, list[dict[str, Any]]]:
            out: dict[Recipient, list[dict[str, Any]]] = {}
            for key, reader in readers.items():
                got = call(reader.changes, touches, label=f"le direct ({key[0]})")
                if not isinstance(got, Failed) and got:
                    out[key] = got
            return out

        return await asyncio.to_thread(judge)

    def _deliver(self, key: Recipient, said: list[dict[str, Any]]) -> asyncio.Task[int] | None:
        """Sa trame part, sans attendre les autres ; si une trame lui part déjà, celle-ci s'y ajoute et part juste
        après (rien rend ``None``)."""
        if key in self._waiting:
            self._waiting[key] = merged(self._waiting[key], said)
            return None
        self._waiting[key] = []
        task = asyncio.get_running_loop().create_task(self._push(key, said))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _push(self, key: Recipient, said: list[dict[str, Any]]) -> int:
        sent = 0
        try:
            while said:
                got = await acall(self._one, key, said, label=f"le direct ({key[0]})")
                sent += got if isinstance(got, int) else 0
                said, self._waiting[key] = self._waiting.get(key, []), []
        finally:
            self._waiting.pop(key, None)
        return sent

    async def _one(self, key: Recipient, said: list[dict[str, Any]]) -> int:
        try:
            return await asyncio.wait_for(self.hub.push_changed(key[0], key[1], said), self.send_timeout_s)
        except TimeoutError:  # une connexion qui ne prend plus rien : elle relira tout à sa reconnexion
            log.info("le direct : une trame pour %s n'est pas partie en %g s", key[0], self.send_timeout_s)
            return 0
