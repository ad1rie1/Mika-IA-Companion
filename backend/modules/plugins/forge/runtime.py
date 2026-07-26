"""Chargement + invocation synchrone d'un module forgé.

Tout ici est SYNCHRONE et pensé pour tourner dans le thread pool de
l'hôte (ForgeModule) — qui, lui, gère l'async, les timeouts globaux et
le disjoncteur.
"""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any, Callable

from modules.plugins.forge import sandbox
from modules.plugins.forge.api import ForgeAPI, write_log
from modules.plugins.forge.store import ForgeManifest

LOAD_TIMEOUT_S = 10.0

VALID_STATUSES = ("actif", "désactivé", "cassé")


class LoadedForgeModule:
    """Un module forgé chargé en mémoire : namespace exécuté + handlers."""

    def __init__(self, manifest: ForgeManifest, code: str, api: ForgeAPI):
        self.manifest = manifest
        self.code = code
        self.api = api
        self.handlers: dict[str, Callable] = {}
        self.loaded_at = datetime.now()
        self.consecutive_failures = 0
        self.last_error: str | None = None
        self.next_run_at: datetime | None = None
        self.context_cache: str = ""

    @property
    def name(self) -> str:
        return self.manifest.name

    def handler_names(self) -> list[str]:
        return sorted(self.handlers)


def format_module_error(exc: BaseException, module_name: str) -> str:
    """Erreur compacte et actionnable pour Mika : type, message, et les
    lignes de traceback qui appartiennent au code du module lui-même."""
    filename = f"<forge:{module_name}>"
    lines = [f"{type(exc).__name__}: {exc}"]
    tb = traceback.extract_tb(exc.__traceback__)
    own = [f for f in tb if f.filename == filename]
    for frame in own[-3:]:
        where = frame.name if frame.name != "<module>" else "niveau module"
        lines.append(f"  ligne {frame.lineno} ({where}): {frame.line or ''}".rstrip())
    return "\n".join(lines)[:1500]


def load_module(manifest: ForgeManifest, code: str, api: ForgeAPI) -> LoadedForgeModule:
    """Valide puis exécute le code du module ; collecte les handlers.

    Lève ``sandbox.SandboxViolation`` (validation) ou l'exception du code
    lui-même (exec top-level). À appeler DANS un thread worker.
    """
    violations = sandbox.validate_source(code)
    if violations:
        raise sandbox.SandboxViolation(
            "code refusé par le bac à sable:\n- " + "\n- ".join(violations)
        )

    lm = LoadedForgeModule(manifest, code, api)

    def _print(*args, **kwargs):
        message = " ".join(str(a) for a in args)
        if message.strip():
            write_log(manifest.name, "info", "print", message)

    env = sandbox.build_globals(api, _print)
    compiled = compile(code, f"<forge:{manifest.name}>", "exec")
    sandbox.run_with_deadline(_exec_in, (compiled, env), LOAD_TIMEOUT_S)

    for key, value in env.items():
        if callable(value) and key.startswith(sandbox.HANDLER_PREFIXES):
            lm.handlers[key] = value
    return lm


def _exec_in(compiled, env: dict) -> None:
    exec(compiled, env)  # noqa: S102 — c'est le cœur assumé de la forge


def call_handler(lm: LoadedForgeModule, handler_name: str,
                 extra_args: tuple, timeout_s: float) -> Any:
    """Invoque ``handler(api, *extra_args)`` sous deadline.

    Synchrone (thread worker). Les exceptions remontent telles quelles ;
    l'hôte les formate et les journalise.
    """
    fn = lm.handlers[handler_name]
    return sandbox.run_with_deadline(fn, (lm.api, *extra_args), timeout_s)
