"""Les réglages d'exploitation (fournisseurs, clés, rôles), rangés dans
``mind.db`` ; les secrets chiffrés (Fernet).

La clé de chiffrement vient de ``MIKA_SECRET_KEY`` ou, à défaut, d'un
fichier ``secret.key`` créé au premier démarrage à côté des bases (droits
0600). Elle ne va jamais dans le dépôt.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from mika.adapters.llm.config import BackendSpec, LLMConfig
from mika.adapters.mail import MailConfig

LLM_KEY = "llm"
TELEGRAM_KEY = "telegram"
EMAIL_KEY = "email"
FEEDS_KEY = "feeds"
STT_KEY = "stt"
SENSORS_KEY = "sensors"


class SecretBox:
    def __init__(self, key: bytes) -> None:
        self._f = Fernet(key)

    @classmethod
    def for_data(cls, data: Path) -> SecretBox:
        env = os.environ.get("MIKA_SECRET_KEY", "").strip()
        if env:
            return cls(env.encode())
        path = data / "secret.key"
        if not path.exists():
            data.mkdir(parents=True, exist_ok=True)
            path.write_bytes(Fernet.generate_key())
            path.chmod(0o600)
        return cls(path.read_bytes().strip())

    def seal(self, text: str) -> str:
        return self._f.encrypt(text.encode()).decode() if text else ""

    def open(self, token: str) -> str:
        if not token:
            return ""
        try:
            return self._f.decrypt(token.encode()).decode()
        except InvalidToken:
            return ""


class Settings:
    def __init__(self, store: Any, box: SecretBox) -> None:
        self.store = store
        self.box = box

    async def open(self) -> None:
        await self.store.run_mind(lambda sql: sql.execute(
            "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)"))

    def _get(self, key: str) -> Any:
        try:
            rows = self.store.query_mind("SELECT value FROM settings WHERE key=?", (key,))
        except sqlite3.OperationalError:  # la table n'existe pas encore (avant ``open``)
            return None
        return json.loads(rows[0][0]) if rows else None

    async def _put(self, key: str, value: Any) -> None:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
        await self.store.run_mind(lambda sql: sql.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, raw)))

    def llm(self) -> LLMConfig:
        data = self._get(LLM_KEY) or {}
        backends = {}
        for name, spec in (data.get("backends") or {}).items():
            spec = dict(spec)
            spec["api_key"] = self.box.open(spec.pop("api_key_sealed", ""))
            backends[name] = BackendSpec.model_validate(spec)
        return LLMConfig(backends=backends, routes=data.get("routes") or {},
                         context_tokens=data.get("context_tokens") or 24_000)

    async def save_llm(self, cfg: LLMConfig) -> None:
        problems = cfg.problems()
        if problems:
            raise ValueError("; ".join(problems))
        backends = {}
        for name, spec in cfg.backends.items():
            data = spec.model_dump()
            data["api_key_sealed"] = self.box.seal(data.pop("api_key"))
            backends[name] = data
        await self._put(LLM_KEY, {"backends": backends, "routes": dict(cfg.routes),
                                  "context_tokens": cfg.context_tokens})

    # ── Telegram ──
    def telegram(self) -> dict[str, Any]:
        """``{"token": …, "allowed_chats": [...], "owners": [...]}`` (jeton déchiffré)."""
        data = dict(self._get(TELEGRAM_KEY) or {})
        return {"token": self.box.open(data.get("token_sealed", "")),
                "allowed_chats": [int(c) for c in data.get("allowed_chats") or []],
                "owners": [int(o) for o in data.get("owners") or []]}

    async def save_telegram(self, *, token: str | None = None, allowed_chats: list[int] | None = None,
                            owners: list[int] | None = None) -> None:
        data = dict(self._get(TELEGRAM_KEY) or {})
        if token is not None:
            data["token_sealed"] = self.box.seal(token.strip())
        if allowed_chats is not None:
            data["allowed_chats"] = sorted({int(c) for c in allowed_chats})
        if owners is not None:
            data["owners"] = sorted({int(o) for o in owners})
        await self._put(TELEGRAM_KEY, data)

    # ── Courrier, flux, transcription ──
    def email(self) -> MailConfig:
        data = dict(self._get(EMAIL_KEY) or {})
        data["password"] = self.box.open(data.pop("password_sealed", ""))
        try:
            return MailConfig.model_validate(data)
        except ValueError:
            return MailConfig()

    async def save_email(self, **fields: Any) -> MailConfig:
        current = self.email().model_dump()
        current.update({k: v for k, v in fields.items() if v is not None})
        cfg = MailConfig.model_validate(current)
        data = cfg.model_dump()
        data["password_sealed"] = self.box.seal(data.pop("password"))
        await self._put(EMAIL_KEY, data)
        return cfg

    def feeds(self) -> list[str]:
        return [str(u) for u in (self._get(FEEDS_KEY) or [])]

    async def save_feeds(self, urls: list[str]) -> list[str]:
        clean = sorted({u.strip() for u in urls if u.strip().startswith(("http://", "https://"))})
        await self._put(FEEDS_KEY, clean)
        return clean

    def stt(self) -> dict[str, str]:
        data = dict(self._get(STT_KEY) or {})
        return {"base_url": data.get("base_url", ""), "model": data.get("model", "whisper-1"),
                "api_key": self.box.open(data.get("api_key_sealed", ""))}

    async def save_stt(self, base_url: str, api_key: str, model: str = "whisper-1") -> None:
        await self._put(STT_KEY, {"base_url": base_url.strip(), "model": model,
                                  "api_key_sealed": self.box.seal(api_key.strip())})

    # ── Appareils (``POST /api/perceptions``) ──
    def sensors_token(self) -> str:
        return self.box.open(dict(self._get(SENSORS_KEY) or {}).get("token_sealed", ""))

    async def new_sensors_token(self) -> str:
        """Un jeton neuf (l'ancien ne vaut plus) ; montré une fois."""
        token = secrets.token_urlsafe(32)
        await self._put(SENSORS_KEY, {"token_sealed": self.box.seal(token)})
        return token
