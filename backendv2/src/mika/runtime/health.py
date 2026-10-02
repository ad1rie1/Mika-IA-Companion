"""La santé du noyau : peut-elle répondre, et répond-elle moins bien ?

Un rapport de contrôles nommés, chacun ``ok``, ``degraded`` (elle répond,
moins bien) ou ``ko`` (quelque chose est cassé et rien ne le réparera seul).
``/health`` n'en publie que les noms et les états ; le détail est pour
l'inspecteur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from mika.kernel.clock import DAY, MINUTE
from mika.kernel.inspect import describe_error
from mika.kernel.registry import zone_known
from mika.runtime.boundary import Failed, call

if TYPE_CHECKING:
    from mika.runtime.bootstrap import Kernel

OK, DEGRADED, KO = "ok", "degraded", "ko"

#: au-delà, une projection différée est « en retard » (le rappel lit du vieux)
PROJECTION_LAG_MAX = 500
#: un effet en attente depuis plus longtemps : la livraison est bloquée
OUTBOX_AGE_MAX_US = 5 * MINUTE
#: échecs d'affilée d'un processus avant de le dire
PROCESS_FAILURES_MAX = 3


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
    state = DEGRADED if behind > limit else OK
    return Check("journal", state, f"{mind.head} événements, dernier instantané {behind} derrière",
                 (f"instantané au seq {snap.seq}" if snap else "aucun instantané",))


def _slices(kernel: Kernel) -> Check:
    tainted = dict(kernel.mind.root.tainted.items())
    if tainted:
        return Check("slices", KO, f"{len(tainted)} tranche(s) corrompue(s)",
                     tuple(f"{o} : un réducteur a levé au seq {seq}" for o, seq in sorted(tainted.items())))
    return Check("slices", OK, "toutes les tranches saines")


def _loops(kernel: Kernel) -> Check:
    dead = kernel.dead_loops()
    if dead:
        return Check("loops", KO, "boucle(s) arrêtée(s) : " + ", ".join(dead))
    return Check("loops", OK, "ordonnanceur, file de sortie et projections tournent")


def _projections(kernel: Kernel) -> Check:
    lag = kernel.projections.lag()
    late = {name: n for name, n in lag.items() if n > PROJECTION_LAG_MAX}
    quarantined = kernel.projections.quarantined
    detail = tuple(f"{name} : {n} événement(s) de retard" for name, n in sorted(lag.items()))
    detail += tuple(f"{name} : seq {seq} en quarantaine ({error[:120]})" for name, seq, error in quarantined[-10:])
    if late or quarantined:
        return Check("projections", DEGRADED, f"{len(late)} en retard, {len(quarantined)} en quarantaine", detail)
    return Check("projections", OK, "à jour", detail)


def _processes(kernel: Kernel) -> Check:
    sched = kernel.scheduler
    failing = {n: k for n, k in sched.consecutive.items() if k >= PROCESS_FAILURES_MAX}
    detail = tuple(f"{n} : {k} échec(s) d'affilée — {sched.last_error.get(n, (0, ''))[1]}"
                   for n, k in sorted(failing.items()))
    # un processus qui a tourné en rafale (retenu par l'ordonnanceur) : un défaut à comprendre, jamais un régime
    detail += tuple(f"{n} : {k} rafale(s) retenue(s)" for n, k in sorted(sched.storms.items()) if k)
    if failing or sched.storms:
        what = [f"{len(failing)} processus en échec"] if failing else []
        what += [f"{len(sched.storms)} processus en rafale"] if sched.storms else []
        return Check("processes", DEGRADED, " ; ".join(what), detail)
    return Check("processes", OK, f"{len(sched.specs)} processus", detail)


def _outbox(kernel: Kernel) -> Check:
    """En attente depuis trop longtemps, ou abandonné dans les dernières 24 h
    (un message qui n'est jamais parti ne doit pas disparaître en silence)."""
    store = kernel.mind.store
    now = kernel.mind.clock.now()
    # abandonné après ses réessais, ou capacité interrompue par une panne et pas relancée (à décider)
    rows = store.query_mind("SELECT seq, effect, last_error FROM outbox WHERE status IN ('failed', 'interrupted') "
                            "ORDER BY seq DESC LIMIT 50")
    at = {e.seq: e.at for e in store.get_events([r[0] for r in rows])}
    failed = [(seq, effect, error) for seq, effect, error in rows if now - at.get(seq, 0) < DAY]
    pending = store.pending_outbox()
    oldest = store.get_events([pending[0].seq]) if pending else []
    age = now - oldest[0].at if oldest else 0
    detail = tuple(f"{r.effect} (seq {r.seq}) : {r.attempts} tentative(s) {describe_error(r.last_error or '')}"
                   for r in pending[:10])
    detail += tuple(f"abandonné : {effect} (seq {seq}) — {describe_error(error or '')}"
                    for seq, effect, error in failed[:10])
    parts = []
    if pending:
        parts.append(f"{len(pending)} effet(s) en attente, le plus vieux depuis {age // 1_000_000} s")
    if failed:
        parts.append(f"{len(failed)} abandonné(s) en 24 h")
    state = DEGRADED if failed or age > OUTBOX_AGE_MAX_US else OK
    return Check("outbox", state, " ; ".join(parts) or "rien en attente", detail)


def _llm(kernel: Kernel) -> Check:
    gateway = kernel.deps.gateway
    configured = getattr(gateway, "configured", gateway is not None)
    if not configured:
        return Check("llm", DEGRADED, "aucun modèle configuré : elle ne peut pas parler")
    return Check("llm", OK, "modèles branchés")


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
        elif name == "kernel" and got is not None and not zone_known(str(getattr(got, "tz", "UTC"))):
            problems.append(f"fuseau horaire inconnu « {str(got.tz)[:60]} » : elle vit en UTC — corrige-le dans "
                            "Configuration › Personnage › Identité")
    if problems:
        return Check("config", DEGRADED, problems[0][:200], tuple(problems))
    return Check("config", OK, "paramètres et fuseau lisibles")


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
              _outbox(kernel), _llm(kernel), _lanes(kernel), _config(kernel))
    return Health(kernel.phase, checks)
