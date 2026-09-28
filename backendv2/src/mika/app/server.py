"""Le serveur : le noyau réel (horloge, identifiants, magasin, modèles),
l'adaptateur web par-dessus, un seul processus.

``python -m mika serve --port 8001`` puis, dans ``frontend/`` : ``npm run dev``.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starlette.applications import Starlette

from mika.adapters.llm.config import LiveGateway, build_gateway
from mika.adapters.store_sqlite import SqliteStore
from mika.adapters.system import RandomIdGen, RealClock
from mika.adapters.vectors import SentenceEmbedder, SqliteVectorIndex
from mika.adapters.web import protocol
from mika.adapters.web.accounts import Accounts
from mika.adapters.web.app import WebConfig, create_app
from mika.adapters.web.hub import Hub
from mika.app import composition
from mika.app.mindport import KernelPort
from mika.app.paths import PERSONA
from mika.app.settings import SecretBox, Settings
from mika.faculties.self import load
from mika.inspector.app import InspectorDeps, routes
from mika.kernel.prompt import Budget
from mika.runtime.bootstrap import Kernel

log = logging.getLogger("mika.server")


@dataclass(slots=True)
class Live:
    kernel: Kernel
    hub: Hub
    port: KernelPort
    accounts: Accounts
    settings: Settings
    gateway: LiveGateway
    #: une passerelle fournie de l'extérieur (tests, simulateur) n'est pas rechargée
    fixed: bool = False

    async def reload_llm(self) -> list[str]:
        if self.fixed:
            return []
        cfg = self.settings.llm()
        problems = cfg.problems()
        if cfg.backends and not problems:
            self.gateway.set(build_gateway(cfg, self.kernel.deps.clock, on_trace=self.gateway.traces.append))
            self.kernel.runner.budget = Budget(max_tokens=cfg.context_tokens)
        else:
            self.gateway.set(None)
        return problems


def build(data: Path, *, persona: Path = PERSONA, web: WebConfig | None = None,
          gateway: LiveGateway | None = None, embedder: Any = None, **deps: Any) -> tuple[Starlette, Live]:
    """L'application et ce qu'elle fait vivre. Tout est construit ici ; le
    cycle de vie ouvre, démarre et arrête."""
    data.mkdir(parents=True, exist_ok=True)
    store = SqliteStore(data / "mind.db", data / "views.db", threaded=True)
    clock = RealClock()
    fixed = gateway is not None
    gateway = gateway or LiveGateway()
    hub = Hub(port=None)  # type: ignore[arg-type] — relié au port juste après
    vectors = SqliteVectorIndex(store, embedder or SentenceEmbedder())
    kernel = Kernel(composition.deps(store=store, clock=clock, ids=RandomIdGen(), gateway=gateway,
                                     ports={"delivery": hub, "vectors": vectors}, **deps))
    port = KernelPort(kernel)
    hub.port = port
    live = Live(kernel, hub, port, Accounts(store), Settings(store, SecretBox.for_data(data)), gateway, fixed)

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        await kernel.start()
        await composition.configure(kernel, load(persona))
        await live.settings.open()
        await live.accounts.open()
        problems = await live.reload_llm()
        if not gateway.configured and not problems:
            log.warning("aucun modèle configuré : voir `python -m mika llm --help`")
        for problem in problems:
            log.warning("configuration des modèles : %s", problem)
        hub.start()
        try:
            yield
        finally:
            await hub.stop()
            await kernel.stop()

    inspector = routes(InspectorDeps(kernel, live.accounts, live.settings, live.reload_llm, gateway.traces),
                       cookie_secure=(web.cookie_secure if web else False))
    return create_app(port, live.accounts, hub, web, lifespan=lifespan, extra_routes=inspector), live


def serve(*, host: str = "127.0.0.1", port: int = 8001, data: Path = Path("data/v2")) -> None:
    import uvicorn  # noqa: PLC0415 — seul le serveur réel en a besoin

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")
    app, _ = build(data)
    uvicorn.run(app, host=host, port=port, ws_max_size=protocol.MAX_FRAME_BYTES, log_level="info")
