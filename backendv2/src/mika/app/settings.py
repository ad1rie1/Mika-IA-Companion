"""Les réglages d'exploitation (fournisseurs, clés, rôles), rangés dans
``mind.db`` ; les secrets chiffrés (Fernet).

La clé de chiffrement vient de ``MIKA_SECRET_KEY`` ou, à défaut, d'un
fichier ``secret.key`` créé au premier démarrage à côté des bases (droits
0600). Elle ne va jamais dans le dépôt.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from mika.adapters.llm.config import ROLES, BackendSpec, LLMConfig
from mika.adapters.mail import MailAccount, MailConfig, from_stored

log = logging.getLogger("mika.settings")
#: les rôles inconnus déjà signalés au journal
_IGNORED_ROLES: set[str] = set()

LLM_KEY = "llm"
EMAIL_KEY = "email"
FEEDS_KEY = "feeds"
STT_KEY = "stt"
#: le jeton des dépôts git distants des projets (GitHub ou un autre hôte https), scellé
GIT_KEY = "git"
SENSORS_KEY = "sensors"
#: le jeton du point MCP de la console (le Claude Code d'une opératrice), scellé
CONSOLE_MCP_KEY = "console_mcp"
PERSONA_KEY = "persona"
OVERRIDES_KEY = "overrides"
FORGE_CONFIG_KEY = "forge_config"
#: les réglages d'un canal retiré (Telegram, ADR 0060) : effacés à l'ouverture — un jeton scellé que plus
#: rien ne lit ne reste pas dans ``mind.db`` ni dans ses sauvegardes
RETIRED_KEYS = ("telegram",)


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
        #: lus depuis les fils de la Forge : tenus en mémoire (une connexion SQLite
        #: appartient à son fil)
        self._forge: dict[str, dict[str, Any]] = {}

    async def open(self) -> None:
        await self.store.run_mind(lambda sql: sql.execute(
            "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)"))
        await self.store.run_mind(lambda sql: sql.executemany(
            "DELETE FROM settings WHERE key=?", [(k,) for k in RETIRED_KEYS]))
        data = self._get(FORGE_CONFIG_KEY) or {}
        self._forge = {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}

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
        routes = dict(data.get("routes") or {})
        # un rôle qui n'existe pas (« reponse », gardé avant qu'on les vérifie) ne servait rien : il ne bloque
        # pas pour autant toute la passerelle au démarrage
        for role in [r for r in routes if r not in ROLES]:
            if role not in _IGNORED_ROLES:  # dit une fois (la console relit la configuration à chaque page)
                _IGNORED_ROLES.add(role)
                log.warning("modèles : le rôle « %s » n'existe pas, sa route est ignorée", role[:40])
            routes.pop(role)
        return LLMConfig(backends=backends, routes=routes, context_tokens=data.get("context_tokens") or 24_000)

    async def save_llm(self, cfg: LLMConfig) -> LLMConfig:
        """Enregistre la configuration des modèles et rend celle qui vaut désormais : revalidée (une copie
        modifiée, ``model_copy``, ne passe pas par les validateurs) — le premier fournisseur déclaré y sert
        « répondre » d'office."""
        cfg = LLMConfig.model_validate({"backends": dict(cfg.backends), "routes": dict(cfg.routes),
                                        "context_tokens": cfg.context_tokens})
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
        return cfg

    # ── Courrier, flux, transcription ──
    #: les secrets d'un compte de courrier (scellés à part, jamais en clair dans ``mind.db``)
    MAIL_SECRETS = ("password", "smtp_password")

    def email(self) -> MailConfig:
        """Les comptes de courrier (mots de passe déchiffrés) ; une ancienne
        configuration à un seul compte devient le compte « principal »."""
        raw = dict(self._get(EMAIL_KEY) or {})
        if "accounts" not in raw:  # l'ancienne forme : un compte, ses secrets au premier niveau
            raw = {**raw, **{k: self.box.open(raw.pop(f"{k}_sealed", "")) for k in self.MAIL_SECRETS}}
            data = from_stored(raw)
        else:
            accounts = {}
            for name, spec in dict(raw.get("accounts") or {}).items():
                spec = dict(spec)
                for k in self.MAIL_SECRETS:
                    spec[k] = self.box.open(spec.pop(f"{k}_sealed", ""))
                accounts[name] = spec
            data = {"accounts": accounts}
        try:
            return MailConfig.model_validate(data)
        except ValueError:
            return MailConfig()

    async def save_email(self, cfg: MailConfig) -> MailConfig:
        accounts = {}
        for name, account in cfg.accounts.items():
            spec = account.model_dump(mode="json")
            for k in self.MAIL_SECRETS:
                spec[f"{k}_sealed"] = self.box.seal(spec.pop(k))
            accounts[name] = spec
        await self._put(EMAIL_KEY, {"accounts": accounts})
        return cfg

    async def save_mail_account(self, name: str, **fields: Any) -> MailConfig:
        """Crée ou modifie un compte (la ligne de commande) : les champs ``None`` ne changent pas."""
        cfg = self.email()
        current = cfg.accounts[name].model_dump() if name in cfg.accounts else {}
        current.update({k: v for k, v in fields.items() if v is not None})
        account = MailAccount.model_validate(current)
        return await self.save_email(MailConfig(accounts={**cfg.accounts, name: account}))

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

    # ── Dépôts git (ses projets poussent vers un dépôt distant) ──
    def git(self) -> dict[str, str]:
        """``{"token": …, "user": …}`` (jeton déchiffré) : ce que l'atelier passe à git, et à lui seul."""
        data = dict(self._get(GIT_KEY) or {})
        return {"token": self.box.open(data.get("token_sealed", "")), "user": data.get("user", "") or "x-access-token",
                "hosts": list(data.get("hosts") or ["github.com"])}

    async def save_git(self, token: str, user: str = "", hosts: list[str] | None = None) -> None:
        clean = sorted({h.strip().lower() for h in (hosts or []) if h.strip()}) or ["github.com"]
        await self._put(GIT_KEY, {"token_sealed": self.box.seal(token.strip()), "user": user.strip(), "hosts": clean})

    # ── Appareils (``POST /api/perceptions``) ──
    def sensors_token(self) -> str:
        return self.box.open(dict(self._get(SENSORS_KEY) or {}).get("token_sealed", ""))

    async def new_sensors_token(self) -> str:
        """Un jeton neuf (l'ancien ne vaut plus) ; montré une fois."""
        token = secrets.token_urlsafe(32)
        await self._put(SENSORS_KEY, {"token_sealed": self.box.seal(token)})
        return token

    def console_mcp_token(self) -> str:
        return self.box.open(dict(self._get(CONSOLE_MCP_KEY) or {}).get("token_sealed", ""))

    async def new_console_mcp_token(self) -> str:
        """Un jeton neuf pour ``/mcp/console`` (l'ancien ne vaut plus) ; montré une fois."""
        token = secrets.token_urlsafe(32)
        await self._put(CONSOLE_MCP_KEY, {"token_sealed": self.box.seal(token)})
        return token

    # ── Persona, surcharges avancées (l'inspecteur ; le fichier YAML reste le défaut) ──
    def persona_yaml(self) -> str | None:
        """La persona rédigée dans l'inspecteur, ou ``None`` (le fichier fait foi)."""
        value = self._get(PERSONA_KEY)
        return str(value) if value else None

    async def save_persona(self, text: str | None) -> None:
        await self._put(PERSONA_KEY, text or "")

    def overrides(self) -> dict[str, dict[str, Any]]:
        """Surcharges des paramètres dérivés, par faculté (diagnostic)."""
        data = self._get(OVERRIDES_KEY) or {}
        return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict) and v}

    async def save_overrides(self, overrides: dict[str, dict[str, Any]]) -> None:
        await self._put(OVERRIDES_KEY, {k: v for k, v in overrides.items() if v})

    # ── Réglages des apps forgées (valeurs simples, surchargent le manifeste) ──
    def forge_config(self, app: str | None = None) -> dict[str, Any]:
        """Sans base : appelable depuis n'importe quel fil (celui d'une app)."""
        if app is None:
            return {k: dict(v) for k, v in self._forge.items()}
        return dict(self._forge.get(app, {}))

    async def save_forge_config(self, app: str, values: dict[str, Any]) -> None:
        clean = {str(k)[:40]: v for k, v in values.items() if isinstance(v, str | int | float | bool)}
        data = self.forge_config()
        if clean:
            data[app] = clean
        else:
            data.pop(app, None)
        await self._put(FORGE_CONFIG_KEY, data)
        self._forge = data
