"""La santé du noyau : peut-elle répondre, et répond-elle moins bien ?

Un rapport de contrôles nommés, chacun ``ok``, ``degraded`` (elle répond,
moins bien) ou ``ko`` (quelque chose est cassé et rien ne le réparera seul).
``/health`` n'en publie que les noms et les états ; le détail est pour
l'inspecteur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import case, func, select

from mika.kernel.clock import DAY, MINUTE, US
from mika.kernel.forms import show_duration
from mika.kernel.inspect import plural
from mika.kernel.registry import zone_known
from mika.ports.errors import describe_error
from mika.ports.journal import JournalEvent, JournalOutbox
from mika.runtime.boundary import Failed, call
from mika.runtime.effects import OUTBOX_LABELS, OUTBOX_LABELS_MANY, OUTBOX_PROBLEMS
from mika.vocab.episodes import Role

if TYPE_CHECKING:
    from mika.runtime.bootstrap import Kernel

OK, DEGRADED, KO = "ok", "degraded", "ko"

#: le rôle sans lequel elle ne parle pas
REPLY_ROLE = str(Role.REPLY)
#: des réponses en échec plus vieilles que ça ne disent plus rien de l'état du fournisseur
FAILING_WINDOW_US = DAY

#: au-delà, une projection différée est « en retard » (le rappel lit du vieux)
PROJECTION_LAG_MAX = 500
#: un effet en attente depuis plus longtemps : la livraison est bloquée
OUTBOX_AGE_MAX_US = 5 * MINUTE
#: échecs d'affilée d'un processus avant de le dire
PROCESS_FAILURES_MAX = 3
#: une lecture du magasin plus longue que ça est dite ; plus longue que ``SLOW_READ_STALL_MS``, la santé se dégrade
#: (elle a retenu la boucle d'événements — audit du 2026-10-26)
SLOW_READ_MS = 50.0
SLOW_READ_STALL_MS = 200.0


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    state: str
    summary: str
    detail: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Health:
    phase: str
    checks: tuple[Check, ...]

    @property
    def ready(self) -> bool:
        return self.phase == "ready"

    @property
    def status(self) -> str:
        if not self.ready:
            return self.phase
        states = {c.state for c in self.checks}
        return KO if KO in states else DEGRADED if DEGRADED in states else OK

    def public(self) -> dict[str, Any]:
        """Ce que tout le monde peut lire : des noms et des états, aucun contenu."""
        return {"status": self.status, "ready": self.ready, "checks": {c.name: c.state for c in self.checks}}


def _journal(kernel: Kernel) -> Check:
    mind = kernel.mind
    snap = mind.store.latest_snapshot()
    behind = mind.head - (snap.seq if snap else 0)
    limit = 4 * max(1, kernel.deps.snapshot_every)
    detail: tuple[str, ...] = (f"dernier instantané : n° {snap.seq}" if snap else "aucun instantané",)
    if mind.gaps:
        # des événements ont disparu du journal : l'état relu n'est plus celui vécu (audit du 2026-10-26)
        holes = ", ".join(f"{a}–{b - 1}" if b - 1 > a else str(a) for a, b in mind.gaps[:10])
        return Check("journal", KO, f"{plural(len(mind.gaps), 'trou', 'trous')} de séquence dans le journal relu",
                     (*detail, f"numéros manquants : {holes}{'…' if len(mind.gaps) > 10 else ''} — "
                               "`mika replay --verify` les liste tous"))
    state = DEGRADED if behind > limit else OK
    # des lectures qui ont retenu la boucle d'événements (le magasin les mesure, s'il sait le faire)
    recent = getattr(mind.store, "recent_slow_reads", None)
    slow = recent() if callable(recent) else []
    if slow:
        worst_ms, sql = slow[0]
        detail += (f"{plural(len(slow), 'lecture', 'lectures')} de plus de {SLOW_READ_MS:.0f} ms ces 10 min, "
                   f"la plus longue {worst_ms:.0f} ms : {sql[:100]}",)
        if worst_ms >= SLOW_READ_STALL_MS:
            state = DEGRADED
    said = f"{plural(mind.head, 'événement', 'événements')} ; {_snapshot_age(snap is not None, behind)}"
    return Check("journal", state, said, detail)


def _snapshot_age(taken: bool, behind: int) -> str:
    """De combien d'événements date le dernier instantané (ce que rejoue un démarrage), en mots."""
    if not taken:
        return "aucun instantané"
    if behind <= 0:
        return "le dernier instantané est à jour"
    return f"le dernier instantané date de {plural(behind, 'événement', 'événements')}"


def _slices(kernel: Kernel) -> Check:
    tainted = dict(kernel.mind.root.tainted.items())
    if tainted:
        return Check("slices", KO, plural(len(tainted), "tranche corrompue", "tranches corrompues"),
                     tuple(f"{o} : un réducteur a levé à l'événement n° {seq}"
                           for o, seq in sorted(tainted.items())))
    return Check("slices", OK, "toutes les tranches saines")


def _loops(kernel: Kernel) -> Check:
    """Les boucles du noyau (ordonnanceur, file de sortie, projections) : une boucle morte en marche ne se relance
    pas d'elle-même, et aucune page ne la montre mieux que ce constat — il dit le geste (redémarrer le serveur)."""
    dead = kernel.dead_loops()
    if dead:
        what, them = plural(len(dead), "boucle arrêtée", "boucles arrêtées"), "les" if len(dead) > 1 else "la"
        return Check("loops", KO, f"{what} ({', '.join(dead)}) : rien ne {them} relance — redémarre le serveur")
    return Check("loops", OK, "ordonnanceur, file de sortie et projections tournent")


def _projections(kernel: Kernel) -> Check:
    lag = kernel.projections.lag()
    late = {name: n for name, n in lag.items() if n > PROJECTION_LAG_MAX}
    quarantined = kernel.projections.quarantined
    detail = tuple(f"{name} : {plural(n, 'événement', 'événements')} de retard" for name, n in sorted(lag.items()))
    detail += tuple(f"{name} : événement n° {seq} en quarantaine ({error[:120]})"
                    for name, seq, error in quarantined[-10:])
    if late or quarantined:
        return Check("projections", DEGRADED, f"{len(late)} en retard, {len(quarantined)} en quarantaine", detail)
    return Check("projections", OK, "à jour", detail)


def _processes(kernel: Kernel) -> Check:
    sched = kernel.scheduler
    failing = {n: k for n, k in sched.consecutive.items() if k >= PROCESS_FAILURES_MAX}
    detail = tuple(f"{n} : {plural(k, 'échec', 'échecs')} d'affilée — {sched.last_error.get(n, (0, ''))[1]}"
                   for n, k in sorted(failing.items()))
    # un processus qui a tourné en rafale (retenu par l'ordonnanceur) : un défaut à comprendre, jamais un régime
    detail += tuple(f"{n} : {plural(k, 'rafale retenue', 'rafales retenues')}"
                    for n, k in sorted(sched.storms.items()) if k)
    if failing or sched.storms:
        what = [f"{len(failing)} processus en échec"] if failing else []
        what += [f"{len(sched.storms)} processus en rafale"] if sched.storms else []
        return Check("processes", DEGRADED, " ; ".join(what), detail)
    return Check("processes", OK, f"{len(sched.specs)} processus", detail)


def _outbox(kernel: Kernel) -> Check:
    """Ce qui attend depuis trop longtemps, et ce qui est à traiter — les états de ``OUTBOX_PROBLEMS``, comptés
    comme la File de sortie les compte, tous et sans limite de temps (un message qui n'est jamais parti ne doit pas
    disparaître en silence). La fenêtre de 24 h ne décide que du ton : un départ à traiter de moins de 24 h dégrade
    le contrôle ; plus vieux, il reste ``ok`` (la sonde publique ne reste pas dégradée pour un vieux départ que
    personne n'a marqué), mais son constat les dit, et le badge de la File de sortie les compte. Le détail garde la
    clé de chaque effet : le runtime ne sait pas les nommer, la File de sortie les dit en mots."""
    store = kernel.mind.store
    now = kernel.mind.clock.now()
    o, e = JournalOutbox, JournalEvent
    # un compte exact par état, et combien sont nés dans les dernières 24 h (l'événement qui les a fait partir)
    recent = func.sum(case((e.at >= int(now) - DAY, 1), else_=0))
    counts: dict[str, tuple[int, int]] = {
        str(status): (int(n), int(fresh or 0)) for status, n, fresh in store.query_mind(
            select(o.status, func.count(), recent).select_from(o).outerjoin(e, e.seq == o.seq)
            .where(o.status.in_(OUTBOX_PROBLEMS)).group_by(o.status))}
    total = sum(n for n, _fresh in counts.values())
    young = sum(fresh for _n, fresh in counts.values())
    # les plus récents, départagés par la clé : un événement fait partir plusieurs effets (les mêmes sur les deux
    # moteurs)
    stuck = store.query_mind(select(o.seq, o.effect, o.status, o.last_error).where(o.status.in_(OUTBOX_PROBLEMS))
                             .order_by(o.seq.desc(), o.key).limit(10)) if total else []
    pending = store.pending_outbox()
    oldest = store.get_events([pending[0].seq]) if pending else []
    age = now - oldest[0].at if oldest else 0
    detail = tuple(f"{r.effect} (événement n° {r.seq}) : {OUTBOX_LABELS['pending']}, "
                   f"{plural(r.attempts, 'tentative', 'tentatives')}{_error(r.last_error)}" for r in pending[:10])
    detail += tuple(f"{effect} (événement n° {seq}) : {OUTBOX_LABELS.get(status, status)}{_error(error)}"
                    for seq, effect, status, error in stuck)
    parts = []
    if pending:
        parts.append(f"{plural(len(pending), 'effet', 'effets')} en attente, le plus vieux depuis {_span(age)}")
    if total:
        old = total - young
        since = "" if not old else " depuis plus de 24 h" if not young else f", dont {old} depuis plus de 24 h"
        parts.append(f"{plural(total, 'départ à traiter', 'départs à traiter')}{since} : " + ", ".join(
            plural(counts[s][0], OUTBOX_LABELS[s], OUTBOX_LABELS_MANY[s]) for s in sorted(counts)))
    state = DEGRADED if young or age > OUTBOX_AGE_MAX_US else OK
    return Check("outbox", state, " ; ".join(parts) or "rien en attente", detail)


def _error(error: str | None) -> str:
    """La dernière erreur d'un effet, en clair, après un tiret ; rien s'il n'en a pas."""
    said = describe_error(error or "")
    return f" — {said}" if said else ""


def _llm(kernel: Kernel) -> Check:
    """Peut-elle répondre ? Un modèle doit servir « répondre » (un fournisseur déclaré sans ce rôle ne suffit
    pas), et ce fournisseur doit répondre : des réponses qui échouent toutes depuis un moment, c'est une
    panne, même si la configuration est juste (un Ollama arrêté, une clé révoquée)."""
    gateway = kernel.deps.gateway
    configured = getattr(gateway, "configured", gateway is not None)
    if not configured:
        return Check("llm", DEGRADED, "aucun modèle ne sert « répondre » : elle ne peut pas parler — déclare un "
                                      "fournisseur (Réglages › Modèles de texte › Fournisseurs)")
    failing = getattr(gateway, "failing", None)
    if callable(failing):
        now = kernel.mind.clock.now()
        got = call(failing, REPLY_ROLE, now, FAILING_WINDOW_US, label="santé des modèles")
        if not isinstance(got, Failed) and got:
            backend, since, cause = got
            return Check("llm", DEGRADED, f"le fournisseur « {backend} » ne répond pas ({cause}) depuis "
                                          f"{_span(now - since)} : ses réponses échouent",
                         (f"dernières réponses en échec depuis {_span(now - since)}",))
    holding = getattr(gateway, "holding", None)
    got = call(holding, label="retenue des modèles") if callable(holding) else []
    if not isinstance(got, Failed) and got:
        # elle répond, mais sa vie de fond est suspendue : travailler, rêver, relire la nuit (ADR 0127)
        return Check("llm", DEGRADED, "appels de fond retenus : " + " ; ".join(f"« {n} », {why}" for n, why in got)
                     + " — elle répond, mais ne travaille plus, ne rêve plus et ne relit plus ses lectures "
                       "jusqu'à ce que le quota redescende",
                     tuple(f"{n} : {why}, seule la conversation passe" for n, why in got))
    return Check("llm", OK, "modèles branchés")


def _span(us: int) -> str:
    """Une durée lisible, à la minute près au-delà d'une minute (« 12 min », « 2 h 5 min », « 40 s »)."""
    step = MINUTE if us >= MINUTE else US
    return show_duration(max(US, us - us % step))


def _config(kernel: Kernel) -> Check:
    """La configuration journalisée se relit : chaque faculté retrouve ses paramètres, et le fuseau
    qu'elle vit existe (sinon elle vit en UTC — ses nuits et ses salutations au mauvais moment)."""
    registry = kernel.registry
    root = kernel.mind.root
    problems: list[str] = []
    for name in sorted(registry.faculties):
        got = call(registry.params_of, name, root, label=f"paramètres de {name}")
        if isinstance(got, Failed):
            problems.append(f"les paramètres de « {name} » ne se relisent pas : {describe_error(got.error)}")
        elif (bad := registry.params_problem(name, root)) is not None:
            problems.append(f"les paramètres de « {name} » ne se relisent pas : {describe_error(bad)} — elle vit "
                            "sur leurs valeurs par défaut jusqu'à ce qu'on les règle de nouveau")
        elif name == "kernel" and got is not None and not zone_known(str(getattr(got, "tz", "UTC"))):
            problems.append(f"fuseau horaire inconnu « {str(got.tz)[:60]} » : elle vit en UTC — corrige-le dans "
                            "Réglages › Personnage › Identité")
    if problems:
        return Check("config", DEGRADED, problems[0][:200], tuple(problems))
    return Check("config", OK, "paramètres et fuseau lisibles")


def _ports(kernel: Kernel) -> Check:
    """Ses branchements (ADR 0064) : un port qui sait dire ce qui est en panne chez lui (``failing()`` → des noms)
    — un serveur d'outils extérieurs coupé par son disjoncteur, par exemple. Le noyau n'en nomme aucun. Ce crochet
    et les trois autres que le runtime cherche sur chaque port sont décrits dans ports/__init__.py."""
    problems: list[str] = []
    for name, port in sorted(kernel.deps.ports.items()):
        failing = getattr(port, "failing", None)
        if not callable(failing):
            continue
        got = call(failing, label=f"santé du port {name}")
        if isinstance(got, Failed):
            problems.append(f"{name} : ne dit pas son état ({describe_error(got.error)})")
        elif isinstance(got, (list, tuple)) and got:
            problems.append(f"{name} : en panne — {', '.join(str(x)[:40] for x in got[:5])}")
    if problems:
        return Check("ports", DEGRADED, problems[0][:200], tuple(problems))
    return Check("ports", OK, "branchements en état")


def _lanes(kernel: Kernel) -> Check:
    lanes = kernel.lanes
    counts = {lane: lanes.pending(lane) for lane in lanes.capacities}
    busy = {lane: n for lane, n in counts.items() if n > lanes.max_pending // 2}
    detail = tuple(f"{lane} : {n} en attente" for lane, n in sorted(counts.items()))
    if busy:
        return Check("lanes", DEGRADED, "voies encombrées : " + ", ".join(busy), detail)
    return Check("lanes", OK, "voies fluides", detail)


def report(kernel: Kernel) -> Health:
    if kernel.phase != "ready":
        return Health(kernel.phase, ())
    checks = (_journal(kernel), _slices(kernel), _loops(kernel), _projections(kernel), _processes(kernel),
              _outbox(kernel), _llm(kernel), _lanes(kernel), _config(kernel), _ports(kernel))
    return Health(kernel.phase, checks)
