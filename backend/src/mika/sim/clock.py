"""Temps virtuel.

Le temps simulé n'avance que lorsque toutes les tâches attendent : asyncio
demande alors au sélecteur de bloquer jusqu'au prochain minuteur ; le sélecteur
virtuel *saute* l'horloge à cet instant et rend la main. Toute E/S réelle lève,
et une attente sans minuteur (tout le monde attend quelqu'un qui n'arrivera
jamais) lève ``SimulationStalled`` avec la pile de chaque tâche.
"""

from __future__ import annotations

import asyncio
import math
import selectors
import traceback
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from mika.kernel.clock import US, Instant

T = TypeVar("T")


class TimeWentBackwards(RuntimeError):
    pass


class SimulationStalled(RuntimeError):
    pass


class RealIOInSimulation(RuntimeError):
    pass


class SimClock:
    """Horloge simulée, en microsecondes."""

    def __init__(self, start_us: int) -> None:
        self._us = int(start_us)

    def now(self) -> Instant:
        return Instant(self._us)

    def advance_to(self, us: int) -> None:
        if us < self._us:
            raise TimeWentBackwards(f"{us} < {self._us}")
        self._us = int(us)

    async def sleep_until(self, t: int) -> None:
        delay = int(t) - self._us
        await asyncio.sleep(delay / US if delay > 0 else 0)


class VirtualSelector(selectors.DefaultSelector):
    def __init__(self, clock: SimClock) -> None:
        super().__init__()
        self.clock = clock
        self.loop: asyncio.AbstractEventLoop | None = None
        self._pipe_registered = False

    def register(self, fileobj: Any, events: int, data: Any = None) -> selectors.SelectorKey:
        if self._pipe_registered:
            raise RealIOInSimulation(f"E/S réelle en simulation : {fileobj!r}")
        self._pipe_registered = True  # le tube interne de la boucle, une seule fois
        return super().register(fileobj, events, data)

    def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
        ready = super().select(0)
        if ready or (timeout is not None and timeout <= 0):
            return ready
        if timeout is None:
            raise SimulationStalled(f"simulation bloquée à {self.clock.now()} :\n{_task_stacks(self.loop)}")
        self.clock.advance_to(self.clock.now() + max(1, math.ceil(timeout * US)))
        return []


def _task_stacks(loop: asyncio.AbstractEventLoop | None) -> str:
    if loop is None:
        return ""
    out = []
    for task in asyncio.all_tasks(loop):
        frames = task.get_stack(limit=6)
        where = "".join(traceback.format_list(traceback.extract_stack(frames[-1]))) if frames else "(sans pile)"
        out.append(f"- {task.get_name()} :\n{where}")
    return "\n".join(out)


class SimEventLoop(asyncio.SelectorEventLoop):
    def __init__(self, clock: SimClock) -> None:
        selector = VirtualSelector(clock)
        super().__init__(selector=selector)
        selector.loop = self
        self._sim_clock = clock
        # Temps de boucle *relatif* au départ : à ~1,8·10⁹ s depuis 1970, un
        # flottant ne distingue plus la résolution d'asyncio (1 ns) et un
        # minuteur échu n'était jamais jugé prêt — la boucle tournait à vide.
        self._base = clock.now()
        # … et la résolution est celle de l'horloge simulée (la microseconde) : au-delà de 2²⁴ s de temps de boucle
        # (194 jours virtuels), l'écart entre deux flottants dépasse 1 ns, « time() + 1e-9 == time() », et la
        # boucle retombait dans le même piège (audit « vie longue » du 2026-10-03)
        self._clock_resolution = 1 / US
        self.errors: list[BaseException] = []
        self.set_exception_handler(self._on_error)

    def time(self) -> float:
        return (self._sim_clock.now() - self._base) / US

    def run_in_executor(self, executor: Any, func: Callable[..., T], *args: Any) -> asyncio.Future[T]:
        fut: asyncio.Future[T] = self.create_future()
        try:
            fut.set_result(func(*args))
        except BaseException as exc:
            fut.set_exception(exc)
        return fut

    def _on_error(self, loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        if isinstance(exc, BaseException):
            self.errors.append(exc)
        else:
            self.errors.append(RuntimeError(context.get("message", "erreur de boucle")))


def run_virtual(clock: SimClock, main: Callable[[], Awaitable[T]]) -> T:
    """Exécute ``main()`` dans une boucle à temps virtuel."""
    loop = SimEventLoop(clock)
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(main())
    finally:
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        asyncio.set_event_loop(None)
        loop.close()
