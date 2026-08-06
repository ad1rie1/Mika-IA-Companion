"""ForgeAPI — l'objet capacitaire injecté dans chaque module forgé.

C'est l'UNIQUE surface de contact entre le code sandboxé et l'hôte.
Tout l'état privé est préfixé ``_`` : le validateur AST interdit l'accès
aux attributs préfixés, donc le code forgé ne voit que les méthodes
publiques ci-dessous.

Les handlers tournent dans un thread worker (contexte sync) : l'ORM est
appelé directement ; les effets asynchrones (notify_ai, emit) sont
projetés sur la boucle via ``run_coroutine_threadsafe`` en fire-and-forget.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime

logger = logging.getLogger("module.forge")

MAX_HTTP_CALLS_PER_RUN = 10
MAX_LOG_CALLS_PER_RUN = 200
MAX_KEY_LEN = 128
MAX_COLLECTION_LEN = 64
LOG_KEEP_PER_MODULE = 300


class ForgeAPIError(Exception):
    """Erreur d'usage de l'API (quota, domaine non autorisé, ...)."""


def _limit(key: str, default):
    from configs.service import config_service
    try:
        value = config_service.get(key, default=default)
    except Exception:
        return default
    return default if value is None else value


def prune_logs(module_name: str) -> None:
    from modules.plugins.forge.models import ForgeLog
    ids = list(
        ForgeLog.objects.filter(module_name=module_name)
        .order_by("-created_at")
        .values_list("id", flat=True)[LOG_KEEP_PER_MODULE:]
    )
    if ids:
        ForgeLog.objects.filter(id__in=ids).delete()


# Prune amorti : un DELETE toutes les N insertions par module, au lieu d'un
# tirage sur l'horloge (qui ne se déclenchait que ~5% du temps et pouvait ne
# jamais tomber pour un module loggant toujours aux mêmes secondes).
_LOG_PRUNE_EVERY = 50
_log_insert_counts: dict[str, int] = {}


def write_log(module_name: str, level: str, source: str, message: str) -> None:
    """Insertion synchrone d'une ligne de journal (thread worker ou
    ``sync_to_async`` depuis la boucle)."""
    from modules.plugins.forge.models import ForgeLog
    ForgeLog.objects.create(
        module_name=module_name,
        level=level,
        source=source,
        message=str(message)[:4000],
    )
    count = _log_insert_counts.get(module_name, 0) + 1
    if count >= _LOG_PRUNE_EVERY:
        _log_insert_counts[module_name] = 0
        try:
            prune_logs(module_name)
        except Exception:
            pass
    else:
        _log_insert_counts[module_name] = count


class ForgeStorage:
    """Espace clé/valeur par collections, confiné au module et quota-isé.

    Toutes les valeurs sont du JSON (dict/list/str/nombre/bool/None).
    """

    def __init__(self, module_name: str):
        self._module = module_name
        self._rows_cached: int | None = None   # nb de lignes du module, en RAM

    def _check_names(self, collection: str, key: str = "k") -> None:
        if not collection or len(collection) > MAX_COLLECTION_LEN:
            raise ForgeAPIError(f"nom de collection invalide: {collection!r}")
        if not key or len(key) > MAX_KEY_LEN:
            raise ForgeAPIError(f"clé invalide: {key!r}")

    def _assert_quota(self, collection: str, key: str) -> None:
        """Refuse une clé NOUVELLE au-delà du plafond de lignes du module.

        Le compte est tenu en RAM : loin du plafond — le cas normal, un
        module qui indexe un flux écrit des centaines de clés par tick —
        une écriture ne coûte plus que le SELECT + INSERT d'
        ``update_or_create``. Le vrai COUNT n'est repayé qu'au premier
        appel et à l'approche du plafond, ce qui rattrape au passage un
        compteur périmé (``reset_storage`` et ``erase`` effacent les
        lignes sans passer par ici). Le ``exists()`` ne se paie qu'à
        saturation, pour laisser une clé DÉJÀ stockée modifiable.
        """
        from modules.plugins.forge.models import ForgeRecord
        max_records = int(_limit("forge.max_records_per_module", 5000))
        if self._rows_cached is None:
            self._rows_cached = ForgeRecord.objects.filter(
                module_name=self._module,
            ).count()
        if self._rows_cached < max_records:
            return
        self._rows_cached = ForgeRecord.objects.filter(
            module_name=self._module,
        ).count()
        if self._rows_cached < max_records:
            return
        exists = ForgeRecord.objects.filter(
            module_name=self._module, collection=collection, key=key,
        ).exists()
        if not exists:
            raise ForgeAPIError(
                f"quota de stockage atteint ({max_records} lignes) — "
                "supprime des entrées avant d'en créer"
            )

    def set(self, collection: str, key: str, value) -> None:
        """Écrit une valeur JSON-sérialisable. Quotas: nb de lignes + taille."""
        from modules.plugins.forge.models import ForgeRecord
        self._check_names(collection, key)
        try:
            encoded = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as exc:
            raise ForgeAPIError(f"valeur non JSON-sérialisable: {exc}")
        max_kb = int(_limit("forge.max_value_kb", 32))
        if len(encoded.encode("utf-8", errors="replace")) > max_kb * 1024:
            raise ForgeAPIError(f"valeur trop grosse (max {max_kb} Ko)")
        self._assert_quota(collection, key)
        _, created = ForgeRecord.objects.update_or_create(
            module_name=self._module, collection=collection, key=key,
            defaults={"value": json.loads(encoded)},
        )
        if created and self._rows_cached is not None:
            self._rows_cached += 1

    def get(self, collection: str, key: str, default=None):
        from modules.plugins.forge.models import ForgeRecord
        self._check_names(collection, key)
        row = ForgeRecord.objects.filter(
            module_name=self._module, collection=collection, key=key,
        ).first()
        return row.value if row is not None else default

    def delete(self, collection: str, key: str) -> bool:
        from modules.plugins.forge.models import ForgeRecord
        self._check_names(collection, key)
        deleted, _ = ForgeRecord.objects.filter(
            module_name=self._module, collection=collection, key=key,
        ).delete()
        if deleted and self._rows_cached is not None:
            self._rows_cached = max(0, self._rows_cached - deleted)
        return bool(deleted)

    def find(self, collection: str, limit: int = 50, offset: int = 0,
             newest_first: bool = True) -> list:
        """Liste [{key, value, updated_at}] d'une collection, paginée."""
        from modules.plugins.forge.models import ForgeRecord
        self._check_names(collection)
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))
        order = "-updated_at" if newest_first else "updated_at"
        rows = ForgeRecord.objects.filter(
            module_name=self._module, collection=collection,
        ).order_by(order)[offset:offset + limit]
        return [
            {"key": r.key, "value": r.value,
             "updated_at": r.updated_at.isoformat(timespec="seconds")}
            for r in rows
        ]

    def keys(self, collection: str, limit: int = 200) -> list:
        from modules.plugins.forge.models import ForgeRecord
        self._check_names(collection)
        limit = max(1, min(int(limit), 2000))
        return list(
            ForgeRecord.objects.filter(
                module_name=self._module, collection=collection,
            ).order_by("key").values_list("key", flat=True)[:limit]
        )

    def count(self, collection: str | None = None) -> int:
        from modules.plugins.forge.models import ForgeRecord
        qs = ForgeRecord.objects.filter(module_name=self._module)
        if collection:
            self._check_names(collection)
            return qs.filter(collection=collection).count()
        self._rows_cached = qs.count()   # mesure exacte du module: on la garde
        return self._rows_cached

    def clear(self, collection: str) -> int:
        from modules.plugins.forge.models import ForgeRecord
        self._check_names(collection)
        deleted, _ = ForgeRecord.objects.filter(
            module_name=self._module, collection=collection,
        ).delete()
        if deleted and self._rows_cached is not None:
            self._rows_cached = max(0, self._rows_cached - deleted)
        return int(deleted)


class ForgeConfig:
    """Accès lecture aux valeurs de config déclarées dans le manifest.

    Les valeurs sont éditées par l'utilisateur dans le dashboard
    (section « Forge · <titre> ») et résolues par le ConfigService
    (déchiffrement des secrets inclus).
    """

    def __init__(self, module_name: str, fields: list[dict]):
        self._module = module_name
        self._fields = {f["key"]: f for f in fields}

    def get(self, key: str, default=None):
        field = self._fields.get(key)
        if field is None:
            raise ForgeAPIError(
                f"clé de config inconnue: {key!r} — déclare-la dans le "
                "manifest (section 'config')"
            )
        from configs.service import config_service
        fallback = field.get("default") if field.get("default") is not None else default
        try:
            value = config_service.get(f"forge.{self._module}.{key}",
                                       default=fallback)
        except Exception:
            return fallback
        return fallback if value is None else value

    def rows(self, key: str) -> list:
        """Lignes d'un champ ``record_list`` : [{row_id, payload, enabled}]."""
        field = self._fields.get(key)
        if field is None or field.get("type") != "record_list":
            raise ForgeAPIError(f"{key!r} n'est pas un record_list déclaré")
        from configs.service import config_service
        try:
            return config_service.list_rows(
                f"forge.{self._module}.{key}", decrypt_secrets=True,
            )
        except Exception as exc:
            raise ForgeAPIError(f"lecture des lignes impossible: {exc}")


class ForgeAPI:
    """Objet ``api`` passé à chaque handler d'un module forgé."""

    def __init__(self, module_name: str, manifest, host):
        self._module = module_name
        self._manifest = manifest
        self._host = host                     # ForgeModule (hôte)
        self._loop = None                     # boucle asyncio, injectée à load
        self._last_notify_mono: float = 0.0
        self._emit_window: deque = deque()
        self._http_calls_this_run = 0
        self._log_calls_this_run = 0
        self._logs_dropped_this_run = 0
        self.storage = ForgeStorage(module_name)
        self.config = ForgeConfig(module_name, manifest.config)
        self.state: dict = {}                 # RAM, vidé au reload

    # ── Identité / temps ─────────────────────────────────────────

    @property
    def module_name(self) -> str:
        return self._module

    def now(self) -> datetime:
        return datetime.now()

    # ── Journal ──────────────────────────────────────────────────

    def log(self, message, source: str = "print") -> None:
        self._write_log_budgeted("info", source, message)

    def warn(self, message) -> None:
        self._write_log_budgeted("warning", "print", message)

    def error(self, message) -> None:
        self._write_log_budgeted("error", "print", message)

    def _write_log_budgeted(self, level: str, source: str, message) -> None:
        """Journalise sous plafond par invocation de handler.

        C'était le seul canal d'effet de bord du bac à sable sans borne, et
        chaque ligne est un INSERT synchrone sur la base partagée : un
        ``for x in items: print(x)`` sur 500 éléments prend 500 fois le
        verrou d'écriture WAL en concurrence avec les six boucles de fond,
        à chaque tick, sans que le disjoncteur ne voie rien — la boucle
        réussit, elle est seulement bavarde. Le surplus est compté et dit
        par ``_end_run``, jamais silencieux.
        """
        if self._log_calls_this_run >= MAX_LOG_CALLS_PER_RUN:
            self._logs_dropped_this_run += 1
            return
        self._log_calls_this_run += 1
        write_log(self._module, level, source, message)

    # ── Signaux vers Mika / le bus ───────────────────────────────

    def notify_ai(self, summary: str, details: str = "",
                  urgency: str = "normal") -> bool:
        """Réveille Mika (perception INTERNAL_TRIGGER via le pipeline).

        Rate-limité par ``forge.notify_cooldown_s`` (défaut 300s) pour
        éviter qu'un module bavard spamme la conversation.
        Retourne False si le cooldown a bloqué l'envoi.
        """
        cooldown = float(_limit("forge.notify_cooldown_s", 300))
        now = time.monotonic()
        if now - self._last_notify_mono < cooldown:
            self._write_log_budgeted("warning", "system",
                                     f"notify_ai ignoré (cooldown {cooldown:.0f}s)")
            return False
        self._last_notify_mono = now
        if urgency not in ("low", "normal", "high", "critical"):
            urgency = "normal"
        summary = str(summary)[:300]
        details = str(details)[:2000]
        self._fire(self._host.notify_from_forged(
            self._module, summary, details, urgency,
        ))
        return True

    def emit(self, event_type: str, data: dict | None = None) -> bool:
        """Émet un événement ``forge.<module>.<event_type>`` sur le bus
        (la Conscience l'observe ; les autres modules forgés abonnés le
        reçoivent). Rate-limité par ``forge.emit_rate_per_min``.
        """
        if not isinstance(event_type, str) or not event_type.strip():
            raise ForgeAPIError("event_type requis")
        rate = int(_limit("forge.emit_rate_per_min", 12))
        now = time.monotonic()
        while self._emit_window and now - self._emit_window[0] > 60.0:
            self._emit_window.popleft()
        if len(self._emit_window) >= rate:
            self._write_log_budgeted("warning", "system",
                                     f"emit ignoré (limite {rate}/min)")
            return False
        self._emit_window.append(now)
        try:
            payload = json.loads(json.dumps(data or {}, default=str))
        except (TypeError, ValueError) as exc:
            raise ForgeAPIError(f"data non sérialisable: {exc}")
        full_type = f"forge.{self._module}.{event_type.strip()[:64]}"
        self._fire(self._host.emit_from_forged(self._module, full_type, payload))
        return True

    def _fire(self, coro) -> None:
        import asyncio
        loop = self._loop
        if loop is None or loop.is_closed():
            coro.close()
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:
            coro.close()

    # ── HTTP sortant (allowlist) ─────────────────────────────────

    def http_get(self, url: str, timeout: float = 10.0) -> dict:
        """GET vers un hôte déclaré dans ``allowed_domains`` du manifest.

        - http/https seulement, redirections désactivées
        - IP privées/loopback bloquées (pas d'accès au backend local)
        - réponse tronquée à ``forge.http_max_kb`` (défaut 512 Ko)

        Retourne {status, text, truncated, url}.
        """
        self._http_calls_this_run += 1
        if self._http_calls_this_run > MAX_HTTP_CALLS_PER_RUN:
            raise ForgeAPIError(
                f"trop d'appels http dans ce handler (max {MAX_HTTP_CALLS_PER_RUN})"
            )
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ForgeAPIError(f"schéma non autorisé: {parsed.scheme!r}")
        host = (parsed.hostname or "").lower()
        if not host:
            raise ForgeAPIError("URL sans hôte")
        if host not in self._manifest.allowed_domains:
            raise ForgeAPIError(
                f"domaine non autorisé: {host!r} — ajoute-le à "
                "'allowed_domains' dans le manifest"
            )
        _assert_public_host(host)

        timeout = max(1.0, min(float(timeout),
                               float(_limit("forge.http_timeout_s", 10))))
        max_bytes = int(_limit("forge.http_max_kb", 512)) * 1024
        request = urllib.request.Request(
            url, headers={"User-Agent": "MikaForge/1.0"}, method="GET",
        )
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=timeout) as resp:
                body = resp.read(max_bytes + 1)
                status = resp.status
        except urllib.error.HTTPError as exc:
            body = exc.read(max_bytes + 1) if exc.fp else b""
            status = exc.code
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ForgeAPIError(f"requête échouée: {exc}")
        truncated = len(body) > max_bytes
        text = body[:max_bytes].decode("utf-8", errors="replace")
        return {"status": int(status), "text": text,
                "truncated": truncated, "url": url}

    # ── Interne (hôte uniquement) ────────────────────────────────

    def _begin_run(self, loop) -> None:
        """Appelé par le runtime avant chaque invocation de handler."""
        self._loop = loop
        self._http_calls_this_run = 0
        self._log_calls_this_run = 0
        self._logs_dropped_this_run = 0

    def _end_run(self) -> None:
        """Appelé par le runtime après chaque invocation : dit la troncature.

        Une seule ligne, écrite hors budget — sinon la troncature serait
        elle-même tronquée. Jamais fatale : elle s'exécute dans un
        ``finally`` qui ne doit masquer ni le résultat ni l'erreur du
        handler.
        """
        dropped = self._logs_dropped_this_run
        if not dropped:
            return
        self._logs_dropped_this_run = 0
        try:
            write_log(
                self._module, "warning", "system",
                f"journal tronqué : {dropped} appel(s) ignoré(s) au-delà de "
                f"{MAX_LOG_CALLS_PER_RUN} lignes pour cette exécution",
            )
        except Exception:
            logger.debug("ligne de troncature non écrite pour %s", self._module)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _assert_public_host(host: str) -> None:
    """Refuse les hôtes qui résolvent vers du privé/loopback/réservé.

    Empêche un module forgé d'atteindre le backend local (endpoints
    debug Django) ou le LAN. Vérification au moment de l'appel — le
    TOCTOU DNS résiduel est accepté pour ce modèle de menace.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ForgeAPIError(f"résolution DNS impossible pour {host!r}: {exc}")
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ForgeAPIError(
                f"adresse non publique bloquée pour {host!r} ({ip_str})"
            )
