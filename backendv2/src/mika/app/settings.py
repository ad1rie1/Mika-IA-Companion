"""Les réglages d'exploitation (fournisseurs, clés, rôles), rangés dans
``mind.db`` ; les secrets chiffrés (Fernet).

La clé de chiffrement vient de ``MIKA_SECRET_KEY`` ou, à défaut, d'un
fichier ``secret.key`` créé au premier démarrage à côté des bases (droits
0600). Elle ne va jamais dans le dépôt.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from mika.adapters.llm.config import BackendSpec, LLMConfig

LLM_KEY = "llm"
TELEGRAM_KEY = "telegram"


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
        rows = self.store.query_mind("SELECT value FROM settings WHERE key=?", (key,))
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
