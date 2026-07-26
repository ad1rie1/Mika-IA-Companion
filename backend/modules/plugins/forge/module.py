"""ForgeModule — l'hôte des modules forgés par l'IA.

Un seul plugin visible du ModuleManager (« forge ») qui charge, planifie,
surveille et expose N mini-modules écrits par Mika dans l'espace confiné
``data/forge_modules/``. L'hôte apporte ce que le cœur n'offre pas :

- **hot reload** (écrire → valider → recharger sans redémarrage)
- **disjoncteur** : N échecs consécutifs → module auto-désactivé + Mika
  prévenue (elle peut lire les logs, corriger le code, recharger)
- **timeouts** : chaque handler tourne dans un thread avec deadline —
  un module forgé lent ne bloque jamais le scheduler partagé
- **espace de config par module** injecté dans l'éditeur du dashboard
- **pages dashboard par module** (Option A générique, payload assaini)
- **signaux** : schedule (interval/cron/idle), abonnements aux événements
  du bus, ``api.emit`` inter-modules, ``api.notify_ai`` rate-limité
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from asgiref.sync import sync_to_async

from modules.base import BaseModule
from modules.types import (
    ModuleCapability,
    ModuleEvent,
    ModuleNotification,
    ModuleRoute,
    ModuleStatus,
    ModuleTool,
    ModuleView,
)
from modules.plugins.forge import runtime, sandbox, store
from modules.plugins.forge.api import ForgeAPI, write_log

HANDLER_TIMEOUT_DEFAULT = 10
CONTEXT_TIMEOUT_S = 5.0


def _cfg(key: str, default):
    """Lecture config synchrone — à appeler depuis un thread worker.
    Depuis la boucle async, passer par ``_cfg_async``."""
    from configs.service import config_service
    try:
        value = config_service.get(key, default=default)
    except Exception:
        return default
    return default if value is None else value


async def _cfg_async(key: str, default):
    return await sync_to_async(_cfg, thread_sensitive=False)(key, default)


class _ScheduleShim:
    """Duck-type minimal pour ``projects.schedule.is_due``."""

    def __init__(self, schedule_rule: str, next_run_at):
        self.schedule_rule = schedule_rule
        self.next_run_at = next_run_at


class ForgeModule(BaseModule):
    """Hôte du système de modules auto-gérés par l'IA."""

    CRON_INTERVAL = 5  # granularité fine: les schedules forgés vont jusqu'à 5s

    def __init__(self):
        super().__init__("forge")
        self._loaded: dict[str, runtime.LoadedForgeModule] = {}
        self._load_errors: dict[str, str] = {}
        self._executor: ThreadPoolExecutor | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tick_task: asyncio.Task | None = None
        self._event_tasks: set[asyncio.Task] = set()
        self._breaker_notified: set[str] = set()
        self._ops_lock: asyncio.Lock = asyncio.Lock()

    # ══ Lifecycle ═════════════════════════════════════════════════

    def is_available(self) -> bool:
        return True

    async def instantiate(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="forge",
        )
        await sync_to_async(self._ensure_dir, thread_sensitive=False)()
        names = await sync_to_async(store.list_module_names,
                                    thread_sensitive=False)()
        for name in names:
            await self._load_one(name, reason="boot")
        self.logger.info(
            "Forge démarrée: %d module(s) chargé(s), %d en erreur, dir=%s",
            len(self._loaded), len(self._load_errors), store.forge_dir(),
        )

    @staticmethod
    def _ensure_dir() -> None:
        root = store.forge_dir()
        root.mkdir(parents=True, exist_ok=True)
        (root / "_trash").mkdir(exist_ok=True)

    async def shutdown(self) -> None:
        if self._tick_task and not self._tick_task.done():
            self._tick_task.cancel()
        for task in list(self._event_tasks):
            task.cancel()
        for name in list(self._loaded):
            self._unregister_config(name)
        self._loaded.clear()
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    # ══ Chargement / déchargement ═════════════════════════════════

    async def _load_one(self, name: str, *, reason: str) -> tuple[bool, str]:
        """Charge (ou recharge) un module depuis le disque.

        Retourne (ok, message). Un échec de chargement laisse le module
        en ``_load_errors`` — visible, jamais fatal pour l'hôte.
        """
        self._loaded.pop(name, None)
        self._load_errors.pop(name, None)
        try:
            data = await sync_to_async(store.read_module,
                                       thread_sensitive=False)(name)
        except store.StoreError as exc:
            self._load_errors[name] = str(exc)
            return False, str(exc)

        if not data["state"].get("enabled", True):
            reason_txt = data["state"].get("disabled_reason") or "désactivé"
            return False, f"module désactivé ({reason_txt})"

        manifest, errors = store.validate_manifest(data["manifest_raw"], name)
        if errors:
            message = "manifest invalide:\n- " + "\n- ".join(errors)
            self._load_errors[name] = message
            await self._log(name, "error", "system", message)
            return False, message

        api = ForgeAPI(name, manifest, self)

        def _do_load():
            from django.db import close_old_connections
            close_old_connections()
            return runtime.load_module(manifest, data["code"], api)

        try:
            lm = await asyncio.wait_for(
                self._loop.run_in_executor(self._executor, _do_load),
                timeout=runtime.LOAD_TIMEOUT_S + 5,
            )
        except sandbox.SandboxViolation as exc:
            self._load_errors[name] = str(exc)
            await self._log(name, "error", "system", str(exc))
            return False, str(exc)
        except asyncio.TimeoutError:
            message = "chargement bloqué (timeout)"
            self._load_errors[name] = message
            await self._log(name, "error", "system", message)
            return False, message
        except Exception as exc:  # erreur du code top-level du module
            message = "erreur au chargement:\n" + runtime.format_module_error(exc, name)
            self._load_errors[name] = message
            await self._log(name, "error", "system", message)
            return False, message

        from projects.schedule import compute_next_run
        lm.next_run_at = compute_next_run(manifest.schedule)
        self._loaded[name] = lm
        self._register_config(lm)
        await self._log(name, "info", "system",
                        f"chargé ({reason}) — handlers: "
                        + (", ".join(lm.handler_names()) or "aucun"))

        if "on_start" in lm.handlers:
            await self._run_handler(lm, "on_start", (), source="start")
        await self._refresh_context(lm)
        return True, "ok"

    def _unload(self, name: str) -> None:
        self._loaded.pop(name, None)
        self._load_errors.pop(name, None)
        self._unregister_config(name)

    # ══ Config dynamique (sections dashboard par module forgé) ════

    def _register_config(self, lm: runtime.LoadedForgeModule) -> None:
        if not lm.manifest.config:
            return
        try:
            from configs.registry import registry
            from configs.service import config_service
            registry.register_replace(self._build_config_entries(lm))
            config_service.invalidate_cache()
        except Exception:
            self.logger.exception("registration config forge.%s", lm.name)

    def _unregister_config(self, name: str) -> None:
        try:
            from configs.registry import registry
            registry.unregister(
                key_prefix=f"forge.{name}.", section_key=f"forge_{name}",
            )
        except Exception:
            self.logger.exception("unregistration config forge.%s", name)

    @staticmethod
    def _build_config_entries(lm: runtime.LoadedForgeModule) -> list:
        from configs.types import ConfigItem, ConfigRecord, ConfigSection, record_item
        entries: list = [ConfigSection(
            key=f"forge_{lm.name}",
            label=f"Forge · {lm.manifest.title}",
            icon="⚒",
            order=91,
            description=lm.manifest.description or "Module forgé par Mika.",
        )]
        for f in lm.manifest.config:
            kwargs = dict(
                key=f"forge.{lm.name}.{f['key']}",
                type=f["type"],
                section=f"forge_{lm.name}",
                label=f["label"],
                description=f.get("description", ""),
                default=f.get("default"),
                sensitive=bool(f.get("sensitive")),
                hot_reload=True,
            )
            if f.get("choices"):
                kwargs["choices"] = tuple(f["choices"])
            if f.get("min") is not None:
                kwargs["min"] = f["min"]
            if f.get("max") is not None:
                kwargs["max"] = f["max"]
            if f["type"] == "record_list" and f.get("fields"):
                kwargs["record"] = ConfigRecord(
                    name=f["key"],
                    label=f["label"],
                    fields=tuple(
                        record_item(
                            key=sub["key"], type=sub["type"], label=sub["label"],
                            description=sub.get("description", ""),
                            default=sub.get("default"),
                            sensitive=bool(sub.get("sensitive")),
                            choices=tuple(sub.get("choices") or ()),
                        )
                        for sub in f["fields"]
                    ),
                )
            entries.append(ConfigItem(**kwargs))
        return entries

    # ══ Exécution de handlers (timeout + disjoncteur) ═════════════

    async def _run_handler(
        self,
        lm: runtime.LoadedForgeModule,
        handler: str,
        extra_args: tuple,
        *,
        source: str,
        timeout_s: float | None = None,
        count_failure: bool | None = None,
    ) -> tuple[bool, object, str | None]:
        """Exécute ``handler`` dans le pool avec deadline.

        Retourne (ok, result, erreur). ``count_failure`` (défaut: True pour
        tick/event/start) alimente le disjoncteur.
        """
        if handler not in lm.handlers:
            return False, None, f"handler absent: {handler}"
        if count_failure is None:
            count_failure = source in ("tick", "event", "start")
        timeout = float(timeout_s or await _cfg_async(
            "forge.handler_timeout_s", HANDLER_TIMEOUT_DEFAULT))
        lm.api._begin_run(self._loop)

        def _runner():
            from django.db import close_old_connections
            close_old_connections()
            try:
                return runtime.call_handler(lm, handler, extra_args, timeout)
            finally:
                close_old_connections()

        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._loop.run_in_executor(self._executor, _runner),
                timeout=timeout + 5,
            )
        except asyncio.TimeoutError:
            error = (f"{handler}: thread bloqué au-delà de {timeout:.0f}s "
                     "(appel C non interruptible ?)")
            await self._record_failure(lm, source, error, count_failure)
            return False, None, error
        except sandbox.ForgeTimeout as exc:
            error = f"{handler}: {exc}"
            await self._record_failure(lm, source, error, count_failure)
            return False, None, error
        except Exception as exc:
            error = f"{handler}:\n" + runtime.format_module_error(exc, lm.name)
            await self._record_failure(lm, source, error, count_failure)
            return False, None, error

        if count_failure:
            lm.consecutive_failures = 0
            lm.last_error = None
        elapsed = time.monotonic() - started
        if elapsed > timeout * 0.8:
            await self._log(lm.name, "warning", source,
                            f"{handler} lent: {elapsed:.1f}s")
        return True, result, None

    async def _record_failure(self, lm: runtime.LoadedForgeModule,
                              source: str, error: str,
                              count_failure: bool) -> None:
        lm.last_error = error
        await self._log(lm.name, "error", source, error)
        if not count_failure:
            return
        lm.consecutive_failures += 1
        threshold = int(await _cfg_async("forge.max_consecutive_failures", 5))
        if lm.consecutive_failures < threshold:
            return

        # Disjoncteur : on décharge, on persiste la raison, on prévient Mika.
        reason = (f"auto-désactivé après {lm.consecutive_failures} échecs "
                  f"consécutifs — dernière erreur: {error[:300]}")
        await sync_to_async(store.write_state, thread_sensitive=False)(
            lm.name, enabled=False, disabled_reason=reason,
        )
        self._unload(lm.name)
        await self._log(lm.name, "error", "system", f"DISJONCTEUR: {reason}")
        if lm.name not in self._breaker_notified and self._notify_ai:
            self._breaker_notified.add(lm.name)
            try:
                await self._notify_ai(ModuleNotification(
                    source_module="forge",
                    summary=f"Ton module forgé '{lm.name}' vient d'être "
                            "désactivé automatiquement (échecs répétés).",
                    details=f"Dernière erreur:\n{error[:800]}\n\n"
                            "Tu peux inspecter avec forge_read_module / "
                            "forge_read_logs, corriger via forge_write_module, "
                            "puis le réactiver avec forge_command(enable).",
                    urgency="normal",
                ))
            except Exception:
                self.logger.exception("notification disjoncteur échouée")

    async def _refresh_context(self, lm: runtime.LoadedForgeModule) -> None:
        if not lm.manifest.context or "get_context" not in lm.handlers:
            return
        ok, result, _ = await self._run_handler(
            lm, "get_context", (), source="context",
            timeout_s=CONTEXT_TIMEOUT_S, count_failure=False,
        )
        if ok and isinstance(result, str):
            lm.context_cache = result.strip()[:500]

    # ══ Cron : schedules des modules forgés ═══════════════════════

    async def worker_cron(self) -> None:
        """Ne bloque JAMAIS le scheduler partagé : le batch de ticks part
        dans une tâche de fond, une seule à la fois."""
        if self._tick_task and not self._tick_task.done():
            return
        due = self._due_modules()
        if not due:
            return
        self._tick_task = asyncio.create_task(self._run_ticks(due))

    def _due_modules(self) -> list[runtime.LoadedForgeModule]:
        from django.utils import timezone
        from projects.schedule import is_due, parse_rule
        now = timezone.now()
        due = []
        for lm in self._loaded.values():
            rule = lm.manifest.schedule
            if not rule or parse_rule(rule).kind == "none":
                continue
            shim = _ScheduleShim(rule, lm.next_run_at)
            kind = parse_rule(rule).kind
            if kind == "idle":
                # is_due(idle) lit l'idle de la conscience ; next_run_at
                # sert de garde-fou anti-rafale (min 1 tick / fenêtre).
                if lm.next_run_at and lm.next_run_at > now:
                    continue
                if is_due(shim):
                    due.append(lm)
            else:
                if is_due(shim):
                    due.append(lm)
        return due

    async def _run_ticks(self, due: list[runtime.LoadedForgeModule]) -> None:
        from projects.schedule import compute_next_run
        for lm in due:
            # Recalcule AVANT l'exécution pour éviter la re-sélection
            # si le tick dure plus longtemps que l'intervalle.
            lm.next_run_at = compute_next_run(lm.manifest.schedule)
        results = await asyncio.gather(
            *(self._run_handler(lm, "on_tick", (), source="tick")
              for lm in due if "on_tick" in lm.handlers),
            return_exceptions=True,
        )
        for lm in due:
            if lm.name in self._loaded:  # pas décharge par le disjoncteur
                await self._refresh_context(lm)
        for r in results:
            if isinstance(r, Exception):
                self.logger.exception("tick forge inattendu", exc_info=r)

    # ══ Événements ════════════════════════════════════════════════

    async def on_event(self, event: ModuleEvent) -> None:
        """Fan-out du bus vers les modules forgés abonnés — en tâche de
        fond pour ne pas ralentir l'émetteur."""
        targets = self._subscribers_for(event.event_type, exclude=None)
        if not targets:
            return
        payload = self._event_payload(event.event_type, event.source_module,
                                      event.data)
        task = asyncio.create_task(self._dispatch_event(targets, payload))
        self._event_tasks.add(task)
        task.add_done_callback(self._event_tasks.discard)

    def _subscribers_for(self, event_type: str,
                         exclude: str | None) -> list[runtime.LoadedForgeModule]:
        out = []
        for lm in self._loaded.values():
            if exclude and lm.name == exclude:
                continue
            if "on_event" not in lm.handlers:
                continue
            for pattern in lm.manifest.events:
                if fnmatch.fnmatchcase(event_type, pattern):
                    out.append(lm)
                    break
        return out

    @staticmethod
    def _event_payload(event_type: str, source: str, data) -> dict:
        try:
            clean = json.loads(json.dumps(data or {}, default=str))
        except (TypeError, ValueError):
            clean = {"repr": str(data)[:500]}
        return {"type": event_type, "source": source, "data": clean}

    async def _dispatch_event(self, targets, payload: dict) -> None:
        for lm in targets:
            if lm.name not in self._loaded:
                continue
            await self._run_handler(lm, "on_event", (payload,), source="event")
            if lm.name in self._loaded:
                await self._refresh_context(lm)

    # ══ Ponts appelés par ForgeAPI (depuis les threads workers) ═══

    async def notify_from_forged(self, name: str, summary: str,
                                 details: str, urgency: str) -> None:
        if self._notify_ai is None:
            return
        try:
            await self._notify_ai(ModuleNotification(
                source_module=f"forge/{name}",
                summary=summary,
                details=details,
                urgency=urgency,
            ))
        except Exception:
            self.logger.exception("notify_from_forged(%s) échoué", name)

    async def emit_from_forged(self, name: str, event_type: str,
                               data: dict) -> None:
        """Événement émis par un module forgé : bus global (Conscience +
        autres plugins) + fan-out direct aux frères forgés abonnés (le
        manager ne re-livre pas à ``forge`` lui-même)."""
        from modules.manager import module_manager
        try:
            await module_manager.emit_event(ModuleEvent(
                event_type=event_type, source_module="forge", data=data,
            ))
        except Exception:
            self.logger.exception("emit_from_forged(%s) bus échoué", name)
        targets = self._subscribers_for(event_type, exclude=name)
        if targets:
            payload = self._event_payload(event_type, f"forge/{name}", data)
            await self._dispatch_event(targets, payload)

    # ══ Commandes de gestion (outils MCP + routes + dashboard) ════

    async def command(self, name: str, command: str) -> dict:
        """enable | disable | reload | rollback | erase | reset_storage.

        Retourne {ok, message}. Sérialisé par un lock pour éviter les
        courses entre outils MCP, routes HTTP et dashboard.
        """
        async with self._ops_lock:
            return await self._command_locked(name, command)

    async def _command_locked(self, name: str, command: str) -> dict:
        valid = ("enable", "disable", "reload", "rollback", "erase",
                 "reset_storage")
        if command not in valid:
            return {"ok": False,
                    "message": f"commande inconnue: {command} — choix: "
                               + ", ".join(valid)}
        exists = await sync_to_async(store.module_exists,
                                     thread_sensitive=False)(name)
        if not exists:
            return {"ok": False, "message": f"module inconnu: {name}"}

        if command == "disable":
            await sync_to_async(store.write_state, thread_sensitive=False)(
                name, enabled=False, disabled_reason="désactivé manuellement",
            )
            self._unload(name)
            await self._log(name, "info", "system", "désactivé")
            return {"ok": True, "message": f"{name} désactivé (code et données conservés)"}

        if command == "enable":
            await sync_to_async(store.write_state, thread_sensitive=False)(
                name, enabled=True,
            )
            self._breaker_notified.discard(name)
            ok, message = await self._load_one(name, reason="enable")
            return {"ok": ok,
                    "message": f"{name} réactivé" if ok else message}

        if command == "reload":
            ok, message = await self._load_one(name, reason="reload")
            return {"ok": ok,
                    "message": f"{name} rechargé" if ok else message}

        if command == "rollback":
            try:
                ts = await sync_to_async(store.rollback,
                                         thread_sensitive=False)(name)
            except store.StoreError as exc:
                return {"ok": False, "message": str(exc)}
            await self._log(name, "info", "system", f"rollback vers {ts}")
            ok, message = await self._load_one(name, reason="rollback")
            suffix = "" if ok else f" (mais rechargement en échec: {message})"
            return {"ok": ok, "message": f"{name} restauré ({ts}){suffix}"}

        if command == "reset_storage":
            deleted = await sync_to_async(self._wipe_records,
                                          thread_sensitive=False)(name)
            await self._log(name, "info", "system",
                            f"stockage vidé ({deleted} lignes)")
            return {"ok": True,
                    "message": f"stockage de {name} vidé ({deleted} lignes)"}

        # erase
        self._unload(name)
        try:
            dest = await sync_to_async(store.erase,
                                       thread_sensitive=False)(name)
        except store.StoreError as exc:
            return {"ok": False, "message": str(exc)}
        deleted = await sync_to_async(self._wipe_records,
                                      thread_sensitive=False)(name)
        await self._log(name, "warning", "system",
                        f"effacé → {dest} ({deleted} lignes de stockage supprimées)")
        return {"ok": True,
                "message": f"{name} effacé (archivé dans _trash, "
                           f"{deleted} lignes de stockage supprimées)"}

    @staticmethod
    def _wipe_records(name: str) -> int:
        from modules.plugins.forge.models import ForgeRecord
        deleted, _ = ForgeRecord.objects.filter(module_name=name).delete()
        return int(deleted)

    async def write_module(self, name: str, *, code: str | None,
                           manifest_patch: dict, reason: str = "") -> dict:
        """Crée ou met à jour un module (fusion manifest + validation +
        archivage + hot reload). Toute erreur laisse la version en place."""
        async with self._ops_lock:
            return await self._write_module_locked(
                name, code=code, manifest_patch=manifest_patch, reason=reason,
            )

    async def _write_module_locked(self, name: str, *, code: str | None,
                                   manifest_patch: dict, reason: str) -> dict:
        exists = await sync_to_async(store.module_exists,
                                     thread_sensitive=False)(name)
        if not exists:
            existing_manifest: dict = {}
            existing_code = ""
            max_modules = int(await _cfg_async("forge.max_modules", 12))
            current = await sync_to_async(store.list_module_names,
                                          thread_sensitive=False)()
            if len(current) >= max_modules:
                return {"ok": False, "errors": [
                    f"limite de {max_modules} modules atteinte — efface ou "
                    "fusionne un module existant d'abord"]}
            if not code:
                return {"ok": False,
                        "errors": ["'code' est requis pour créer un module"]}
        else:
            data = await sync_to_async(store.read_module,
                                       thread_sensitive=False)(name)
            existing_manifest = data["manifest_raw"] or {}
            existing_code = data["code"]

        merged = dict(existing_manifest)
        for key, value in manifest_patch.items():
            if value is not None:
                merged[key] = value
        merged["version"] = int(existing_manifest.get("version") or 0) + 1
        new_code = code if code is not None else existing_code

        max_kb = int(await _cfg_async("forge.max_source_kb", 64))
        if len((new_code or "").encode()) > max_kb * 1024:
            return {"ok": False,
                    "errors": [f"code trop long (max {max_kb} Ko)"]}

        manifest, errors = store.validate_manifest(merged, name)
        if errors:
            return {"ok": False, "errors": errors}
        violations = sandbox.validate_source(new_code or "")
        if violations:
            return {"ok": False, "errors": violations}

        await sync_to_async(store.write_module, thread_sensitive=False)(
            name, merged, new_code,
        )
        await self._log(name, "info", "system",
                        f"v{merged['version']} écrite"
                        + (f" — {reason}" if reason else ""))

        state = await sync_to_async(store.read_state,
                                    thread_sensitive=False)(name)
        if state.get("enabled", True):
            ok, message = await self._load_one(name, reason="write")
            if not ok:
                return {"ok": False, "errors": [
                    f"écrit (v{merged['version']}) mais le chargement a "
                    f"échoué: {message}",
                    "utilise forge_command(rollback) pour revenir à la "
                    "version précédente",
                ]}
            lm = self._loaded.get(name)
            return {"ok": True, "version": merged["version"],
                    "handlers": lm.handler_names() if lm else []}
        return {"ok": True, "version": merged["version"],
                "handlers": [], "note": "module désactivé — non chargé"}

    async def test_module(self, name: str, handler: str,
                          payload: dict | None) -> dict:
        """Exécute un handler MAINTENANT (sans compter d'échec) et
        rapporte résultat + logs produits pendant l'appel."""
        lm = self._loaded.get(name)
        if lm is None:
            hint = self._load_errors.get(name, "module non chargé")
            return {"ok": False, "error": hint}
        if handler not in lm.handlers:
            return {"ok": False,
                    "error": f"handler absent: {handler} — disponibles: "
                             + (", ".join(lm.handler_names()) or "aucun")}
        args: tuple = ()
        if handler == "on_event":
            args = (self._event_payload("forge.test", "test",
                                        payload or {}),)
        elif handler.startswith("view_") and handler.endswith("_detail"):
            args = (str((payload or {}).get("item_id", "")),)
        elif handler.startswith("view_") or handler.startswith("action_"):
            args = (payload or {},)

        from django.utils import timezone
        since = timezone.now()
        ok, result, error = await self._run_handler(
            lm, handler, args, source="test", count_failure=False,
        )
        logs = await sync_to_async(self._logs_since,
                                   thread_sensitive=False)(name, since)
        out: dict = {"ok": ok, "logs": logs}
        if ok:
            try:
                out["result"] = json.loads(json.dumps(result, default=str))
            except (TypeError, ValueError):
                out["result"] = str(result)[:2000]
        else:
            out["error"] = error
        return out

    @staticmethod
    def _logs_since(name: str, since: datetime) -> list[str]:
        from modules.plugins.forge.models import ForgeLog
        rows = ForgeLog.objects.filter(
            module_name=name, created_at__gte=since,
        ).order_by("created_at")[:30]
        return [f"[{r.level}/{r.source}] {r.message}" for r in rows]

    @staticmethod
    def _logs_since_all(name: str | None, limit: int) -> list[str]:
        from modules.plugins.forge.models import ForgeLog
        qs = ForgeLog.objects.all()
        if name:
            qs = qs.filter(module_name=name)
        rows = list(qs.order_by("-created_at")[:limit])[::-1]
        return [
            f"{r.created_at.strftime('%d/%m %H:%M:%S')} "
            f"[{r.module_name}/{r.level}/{r.source}] {r.message[:300]}"
            for r in rows
        ]

    # ══ Introspection (partagée outils / routes / vues) ═══════════

    def module_infos(self) -> list[dict]:
        """Snapshot synchrone de l'état de tous les modules forgés.

        ORM-free (RAM + disque) sauf pour rien — appelable partout.
        """
        infos = []
        for name in store.list_module_names():
            state = store.read_state(name)
            lm = self._loaded.get(name)
            if lm is not None:
                status = "actif"
                detail = None
            elif not state.get("enabled", True):
                status = "désactivé"
                detail = state.get("disabled_reason")
            elif name in self._load_errors:
                status = "cassé"
                detail = self._load_errors[name]
            else:
                status = "non chargé"
                detail = None
            info = {
                "name": name,
                "status": status,
                "status_detail": detail,
                "enabled": bool(state.get("enabled", True)),
            }
            if lm is not None:
                info.update({
                    "title": lm.manifest.title,
                    "schedule": lm.manifest.schedule,
                    "events": lm.manifest.events,
                    "views": [v.key for v in lm.manifest.views],
                    "handlers": lm.handler_names(),
                    "failures": lm.consecutive_failures,
                    "last_error": lm.last_error,
                    "next_run_at": (lm.next_run_at.isoformat(timespec="seconds")
                                    if lm.next_run_at else None),
                    "version": lm.manifest.version,
                    "context": lm.context_cache or None,
                })
            else:
                try:
                    raw = store.read_module(name)["manifest_raw"] or {}
                    info["title"] = str(raw.get("title") or name)
                    info["version"] = raw.get("version")
                except store.StoreError:
                    info["title"] = name
            infos.append(info)
        return infos

    # ══ Intégrations BaseModule ═══════════════════════════════════

    def get_capabilities(self) -> list[ModuleCapability]:
        return [
            ModuleCapability(
                description=(
                    "Forger ses propres mini-modules: créer, lire, modifier, "
                    "tester, recharger, désactiver ou effacer des modules "
                    "personnels sandboxés (stockage, config, pages dashboard, "
                    "schedule, réactions aux événements)"
                ),
                tool_names=[
                    "forge_list_modules", "forge_read_module",
                    "forge_write_module", "forge_command",
                    "forge_test_module", "forge_read_logs",
                ],
            ),
        ]

    def return_tools(self) -> list[ModuleTool]:
        from modules.plugins.forge.tools import build_tools
        return build_tools(self)

    def get_views(self) -> list[ModuleView]:
        from modules.plugins.forge.views import build_views
        return build_views(self)

    def get_routes(self) -> list[ModuleRoute]:
        from modules.plugins.forge.views import build_routes
        return build_routes(self)

    def get_models(self) -> list:
        from modules.plugins.forge.models import ForgeLog, ForgeRecord
        return [ForgeRecord, ForgeLog]

    def config_schema(self) -> list:
        from modules.plugins.forge.config_schema import CONFIG_SCHEMA
        return CONFIG_SCHEMA

    def get_context(self, person_id: str = "") -> str:
        parts: list[str] = []
        broken = [n for n in self._load_errors]
        for lm in self._loaded.values():
            if lm.context_cache:
                parts.append(f"({lm.name}) {lm.context_cache}")
        if broken:
            parts.append(
                "modules forgés en panne: " + ", ".join(sorted(broken))
                + " — tu peux les inspecter avec forge_read_module"
            )
        if not parts and not self._loaded:
            return ""
        summary = f"{len(self._loaded)} module(s) forgé(s) actif(s)"
        return summary + (" | " + " | ".join(parts) if parts else "")

    def get_status(self) -> ModuleStatus:
        status = super().get_status()
        status.details = {
            "dir": str(store.forge_dir()),
            "loaded": sorted(self._loaded),
            "broken": {k: v[:120] for k, v in self._load_errors.items()},
        }
        return status

    # ══ Utilitaires ═══════════════════════════════════════════════

    async def _log(self, name: str, level: str, source: str,
                   message: str) -> None:
        try:
            await sync_to_async(write_log, thread_sensitive=False)(
                name, level, source, message,
            )
        except Exception:
            self.logger.exception("écriture ForgeLog échouée pour %s", name)
