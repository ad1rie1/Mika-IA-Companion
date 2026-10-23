"""Les réglages d'exploitation (fournisseurs, clés, rôles), rangés dans
``mind.db`` ; les secrets chiffrés (Fernet).

La clé de chiffrement vient de ``MIKA_SECRET_KEY`` ou, à défaut, d'un
fichier ``secret.key`` créé au premier démarrage à côté des bases (droits
0600). Elle ne va jamais dans le dépôt.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Mapped, mapped_column

from mika.adapters.imaging.config import ImageBackendSpec, ImagingConfig
from mika.adapters.llm.config import ROLES, BackendSpec, LLMConfig
from mika.adapters.mail import MailAccount, MailConfig, from_stored
from mika.adapters.mcp.config import McpConfig, McpServer, StoredReview
from mika.adapters.teams import TeamsConfig
from mika.app import authors as authors_m
from mika.app.wakeups import WakeEndpoint, WakeupConfig
from mika.inspector import mcp as console_mcp
from mika.ports.imaging import ROLES as IMAGE_ROLES
from mika.ports.sql import Key, LongText, MindBase, upsert
from mika.runtime.boundary import call
from mika.runtime.tools import RULES as TOOL_RULES
from mika.runtime.tools import SITUATIONS as TOOL_SITUATIONS

log = logging.getLogger("mika.settings")
#: les rôles inconnus déjà signalés au journal
_IGNORED_ROLES: set[str] = set()

LLM_KEY = "llm"
#: les fournisseurs d'images et leurs rôles (clés scellées)
IMAGING_KEY = "imaging"
EMAIL_KEY = "email"
FEEDS_KEY = "feeds"
STT_KEY = "stt"
#: le jeton des dépôts git distants des projets (GitHub ou un autre hôte https), scellé
GIT_KEY = "git"
#: les notifications du téléphone (ADR 0077) : la clé du compte de service Firebase, scellée
PUSH_KEY = "push"
#: … ou, à défaut d'une clé collée dans la console, ce fichier du dossier de données (à côté de ``secret.key``)
PUSH_KEY_FILE = "firebase-service-account.json"
SENSORS_KEY = "sensors"
#: le point MCP de la console (le Claude Code d'une opératrice) : son jeton, scellé, et ce qu'il sert (ADR 0122)
CONSOLE_MCP_KEY = "console_mcp"
#: les points MCP qui prêtent ses outils à un agent (ADR 0122) : par nom, l'empreinte de leur jeton, leurs outils
LENT_KEY = "mcp_lent"
#: le nom d'un point de prêt : son adresse (``/mcp/pret/<nom>``)
LENT_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
#: ce qui commence le jeton d'un point de prêt (ce qu'on en montre ensuite : son début)
LENT_PREFIX = "mlp_"
PERSONA_KEY = "persona"
OVERRIDES_KEY = "overrides"
FORGE_CONFIG_KEY = "forge_config"
#: les serveurs MCP branchés (ADR 0064 ; jeton et variables secrètes scellés) et les décisions sur leurs outils
MCP_KEY = "mcp"
MCP_TOOLS_KEY = "mcp_tools"
#: les réveils par API (ADR 0068) ; leurs clés à part, dont seule l'empreinte est gardée
WAKEUP_KEY = "wakeup"
WAKEUP_KEYS_KEY = "wakeup_keys"
#: Teams (ADR 0069) : ce qu'un opérateur règle ; la clé de l'extension à part, dont seule l'empreinte est gardée
TEAMS_KEY = "teams"
TEAMS_KEYS_KEY = "teams_key"
#: les règles d'outils d'un opérateur (ADR 0122) : par situation, « outil → off, hand ou ask »
TOOL_RULES_KEY = "tool_rules"
#: ses autrices et le flux de chacune (ADR 0124)
AUTHORS_KEY = "authors"
#: les réglages d'un canal retiré (Telegram, ADR 0060) : effacés à l'ouverture — un jeton scellé que plus
#: rien ne lit ne reste pas dans ``mind.db`` ni dans ses sauvegardes
RETIRED_KEYS = ("telegram",)


class SettingRow(MindBase):
    """Un réglage : sa clé, sa valeur en JSON (les secrets y sont scellés)."""

    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(Key(100), primary_key=True)
    value: Mapped[str] = mapped_column(LongText)


#: une lecture avant que la table existe (avant ``open``) : sous SQLite comme sous MariaDB
NO_TABLE = (OperationalError, ProgrammingError)


_SAID_OPEN: set[str] = set()  # les fichiers de clé déjà signalés lisibles par d'autres


def push_key_file(data: Path) -> str:
    """Le JSON de la clé du compte de service Firebase posée dans le dossier de données
    (``firebase-service-account.json``) ; vide sans fichier ou illisible. Un fichier lisible par d'autres
    que son propriétaire est signalé une fois (``chmod 600``) — il sert quand même."""
    path = data / PUSH_KEY_FILE
    try:
        text = path.read_text(encoding="utf-8")
        if path.stat().st_mode & 0o077 and str(path) not in _SAID_OPEN:
            _SAID_OPEN.add(str(path))
            log.warning("notifications : %s est lisible par d'autres que son propriétaire (chmod 600)", path)
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("notifications : %s illisible (%s)", path, exc)
        return ""
    return text.strip()


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
        #: lues à chaque épisode : tenues en mémoire, relues à l'ouverture
        self._tool_rules: dict[str, dict[str, str]] = {}
        #: ses autrices enregistrées, lues à chaque épisode (et à chaque brouillon) : tenues en mémoire ; ``None`` :
        #: rien d'enregistré (celles par défaut)
        self._authors: authors_m.Authors | None = None
        #: le fil de référence de sa persona (posé par le serveur) : l'exemple de « Message » quand le sien est vide
        self.reference_thread: Callable[[], str] = lambda: ""

    async def open(self) -> None:
        def create(sql: Any) -> None:
            sql.create(SettingRow)
            sql.execute(delete(SettingRow).where(SettingRow.key.in_(RETIRED_KEYS)))

        await self.store.run_mind(create)
        data = self._get(FORGE_CONFIG_KEY) or {}
        self._forge = {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)}
        rules = self._get(TOOL_RULES_KEY) or {}
        self._tool_rules = {str(s): {str(t): str(r) for t, r in v.items() if r in TOOL_RULES}
                            for s, v in rules.items() if s in TOOL_SITUATIONS and isinstance(v, dict)}
        self._authors = self._read_authors()

    def _get(self, key: str) -> Any:
        try:
            rows = self.store.query_mind(select(SettingRow.value).where(SettingRow.key == key))
        except NO_TABLE:  # la table n'existe pas encore (avant ``open``)
            return None
        return json.loads(rows[0][0]) if rows else None

    async def _put(self, key: str, value: Any) -> None:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
        await self.store.run_mind(lambda sql: upsert(sql, SettingRow, {"key": key, "value": raw}, keys=["key"]))

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
        return LLMConfig.model_validate({"backends": backends, "routes": routes,
            **({"context_tokens": data["context_tokens"]} if "context_tokens" in data else {})})

    async def save_llm(self, cfg: LLMConfig) -> LLMConfig:
        """Enregistre la configuration des modèles et rend celle qui vaut désormais : revalidée (une copie
        modifiée, ``model_copy``, ne passe pas par les validateurs) — le premier fournisseur déclaré y sert
        « répondre » d'office."""
        cfg = LLMConfig.model_validate({"backends": dict(cfg.backends), "routes": dict(cfg.routes)})
        problems = cfg.problems()
        if problems:
            raise ValueError("; ".join(problems))
        backends = {}
        for name, spec in cfg.backends.items():
            data = spec.model_dump()
            data["api_key_sealed"] = self.box.seal(data.pop("api_key"))
            backends[name] = data
        await self._put(LLM_KEY, {"backends": backends, "routes": dict(cfg.routes)})
        return cfg

    # ── Images ──
    def imaging(self) -> ImagingConfig:
        """Les fournisseurs d'images (clés déchiffrées) ; aucun : la génération d'images est désactivée. Un
        rôle qui n'existe plus est ignoré, jamais bloquant."""
        data = self._get(IMAGING_KEY) or {}
        backends = {}
        for name, spec in (data.get("backends") or {}).items():
            spec = dict(spec)
            spec["api_key"] = self.box.open(spec.pop("api_key_sealed", ""))
            backends[name] = ImageBackendSpec.model_validate(spec)
        routes = {r: b for r, b in dict(data.get("routes") or {}).items() if r in IMAGE_ROLES}
        return ImagingConfig(backends=backends, routes=routes)

    async def save_imaging(self, cfg: ImagingConfig) -> ImagingConfig:
        """Enregistre les fournisseurs d'images et rend la configuration qui vaut désormais (revalidée : le
        premier fournisseur déclaré sert « dessiner » d'office) ; refusée, en le disant, si elle a un problème."""
        cfg = ImagingConfig.model_validate({"backends": dict(cfg.backends), "routes": dict(cfg.routes)})
        problems = cfg.problems()
        if problems:
            raise ValueError("; ".join(problems))
        backends = {}
        for name, spec in cfg.backends.items():
            data = spec.model_dump()
            data["api_key_sealed"] = self.box.seal(data.pop("api_key"))
            backends[name] = data
        await self._put(IMAGING_KEY, {"backends": backends, "routes": dict(cfg.routes)})
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

    # ── Outils extérieurs (MCP, ADR 0064) ──
    #: les secrets d'un serveur MCP (scellés à part)
    MCP_SECRETS = ("token", "secret_env")

    def mcp(self) -> McpConfig:
        """Les serveurs MCP (secrets déchiffrés) ; un serveur illisible est écarté, jamais bloquant."""
        servers = {}
        for name, spec in dict(dict(self._get(MCP_KEY) or {}).get("servers") or {}).items():
            spec = dict(spec)
            for k in self.MCP_SECRETS:
                spec[k] = self.box.open(spec.pop(f"{k}_sealed", ""))
            try:
                servers[name] = McpServer.model_validate(spec)
            except ValueError:
                log.warning("mcp : le serveur « %s » est illisible, il est ignoré", str(name)[:40])
        try:
            return McpConfig(servers=servers)
        except ValueError:
            return McpConfig()

    async def save_mcp(self, cfg: McpConfig) -> McpConfig:
        cfg = McpConfig.model_validate({"servers": dict(cfg.servers)})
        servers = {}
        for name, server in cfg.servers.items():
            spec = server.model_dump(mode="json")
            for k in self.MCP_SECRETS:
                spec[f"{k}_sealed"] = self.box.seal(spec.pop(k))
            servers[name] = spec
        await self._put(MCP_KEY, {"servers": servers})
        return cfg

    def mcp_tools(self) -> dict[str, dict[str, StoredReview]]:
        """Les décisions de l'opérateur sur les outils des serveurs : serveur → outil → décision."""
        out: dict[str, dict[str, StoredReview]] = {}
        for server, tools in dict(self._get(MCP_TOOLS_KEY) or {}).items():
            kept = {}
            for remote, raw in dict(tools or {}).items():
                try:
                    kept[str(remote)] = StoredReview.model_validate(raw)
                except ValueError:
                    continue
            out[str(server)] = kept
        return out

    async def save_mcp_tools(self, reviews: dict[str, dict[str, StoredReview]]) -> None:
        await self._put(MCP_TOOLS_KEY, {s: {r: v.model_dump(mode="json", by_alias=True) for r, v in tools.items()}
                                        for s, tools in reviews.items()})

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

    # ── Notifications du téléphone (Firebase, ADR 0077) ──
    def push(self) -> str:
        """Le JSON de la clé du compte de service Firebase (déchiffré) ; vide : pas de notifications."""
        return self.box.open(dict(self._get(PUSH_KEY) or {}).get("service_account_sealed", ""))

    async def save_push(self, service_account: str) -> None:
        await self._put(PUSH_KEY, {"service_account_sealed": self.box.seal(service_account.strip())})

    # ── Dépôts git (ses projets poussent vers un dépôt distant) ──
    def git(self) -> dict[str, str]:
        """``{"token": …, "user": …}`` (jeton déchiffré) : ce que l'atelier passe à git, et à lui seul."""
        data = dict(self._get(GIT_KEY) or {})
        return {"token": self.box.open(data.get("token_sealed", "")), "user": data.get("user", "") or "x-access-token",
                "hosts": list(data.get("hosts") or ["github.com"])}

    async def save_git(self, token: str, user: str = "", hosts: list[str] | None = None) -> None:
        clean = sorted({h.strip().lower() for h in (hosts or []) if h.strip()}) or ["github.com"]
        await self._put(GIT_KEY, {"token_sealed": self.box.seal(token.strip()), "user": user.strip(), "hosts": clean})

    # ── Réveils par API (``POST /api/wake/<nom>``, ADR 0068) ──
    def wakeup(self) -> WakeupConfig:
        """Les réveils déclarés ; un réveil illisible est écarté, jamais bloquant."""
        endpoints = {}
        for name, spec in dict(dict(self._get(WAKEUP_KEY) or {}).get("endpoints") or {}).items():
            try:
                endpoints[str(name)] = WakeEndpoint.model_validate(spec)
            except ValueError:
                log.warning("réveils : « %s » est illisible, il est ignoré", str(name)[:40])
        try:
            return WakeupConfig(endpoints=endpoints)
        except ValueError:
            return WakeupConfig()

    async def save_wakeup(self, cfg: WakeupConfig) -> WakeupConfig:
        """Enregistre les réveils ; la clé d'un réveil retiré part avec lui (un réveil recréé sous ce nom n'en a
        pas), et la copie chiffrée de la clé d'un réveil qui ne signe plus aussi (ADR 0117)."""
        cfg = WakeupConfig.model_validate({"endpoints": dict(cfg.endpoints)})
        await self._put(WAKEUP_KEY, {"endpoints": {n: ep.model_dump(mode="json") for n, ep in cfg.endpoints.items()}})
        keys = self.wakeup_keys()
        kept = {n: k if cfg.endpoints[n].signed else {f: v for f, v in k.items() if f != "sealed"}
                for n, k in keys.items() if n in cfg.endpoints}
        if kept != keys:
            await self._put(WAKEUP_KEYS_KEY, kept)
        return cfg

    def wakeup_keys(self) -> dict[str, dict[str, Any]]:
        """Réveil → ``{digest, hint, created_at, by}`` : jamais la clé en clair — et, pour un réveil signé,
        ``sealed`` : la clé chiffrée, qu'il faut relire pour vérifier une signature."""
        return {str(n): dict(k) for n, k in dict(self._get(WAKEUP_KEYS_KEY) or {}).items() if isinstance(k, dict)}

    async def save_wakeup_key(self, name: str, digest: str, hint: str, created_at: int, by: str,
                              sealed: str = "") -> None:
        keys = self.wakeup_keys()
        keys[name] = {"digest": digest, "hint": hint, "created_at": int(created_at), "by": by[:80]}
        if sealed:
            keys[name]["sealed"] = sealed
        await self._put(WAKEUP_KEYS_KEY, keys)

    async def revoke_wakeup_key(self, name: str) -> bool:
        keys = self.wakeup_keys()
        if name not in keys:
            return False
        del keys[name]
        await self._put(WAKEUP_KEYS_KEY, keys)
        return True

    # ── Teams (``/api/teams/…``, ADR 0069) ──
    def teams(self) -> TeamsConfig:
        """Ce qu'un opérateur a réglé de Teams ; illisible, les valeurs par défaut (jamais bloquant)."""
        try:
            return TeamsConfig.model_validate(dict(self._get(TEAMS_KEY) or {}))
        except ValueError:
            log.warning("teams : réglages illisibles, valeurs par défaut")
            return TeamsConfig()

    async def save_teams(self, cfg: TeamsConfig) -> TeamsConfig:
        cfg = TeamsConfig.model_validate(cfg.model_dump())
        await self._put(TEAMS_KEY, cfg.model_dump(mode="json"))
        return cfg

    def teams_key(self) -> dict[str, Any]:
        """``{digest, hint, created_at, by}`` de la clé de l'extension : jamais la clé elle-même (vide : aucune)."""
        got = self._get(TEAMS_KEYS_KEY)
        return dict(got) if isinstance(got, dict) else {}

    async def save_teams_key(self, digest: str, hint: str, created_at: int, by: str) -> None:
        await self._put(TEAMS_KEYS_KEY, {"digest": digest, "hint": hint, "created_at": int(created_at), "by": by[:80]})

    async def revoke_teams_key(self) -> bool:
        if not self.teams_key():
            return False
        await self._put(TEAMS_KEYS_KEY, {})
        return True

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
        await self._put(CONSOLE_MCP_KEY, {**dict(self._get(CONSOLE_MCP_KEY) or {}), "token_sealed": self.box.seal(token)})
        return token

    async def revoke_console_mcp_token(self) -> bool:
        """Le point de la console fermé (404) ; faux s'il n'avait pas de jeton. Ce qu'il sert reste choisi ; son
        ouverture au réseau, non : un jeton neuf la rouvre en local seulement."""
        data = dict(self._get(CONSOLE_MCP_KEY) or {})
        data.pop("network", None)
        if not data.pop("token_sealed", ""):
            return False
        await self._put(CONSOLE_MCP_KEY, data)
        return True

    def console_mcp_network(self) -> bool:
        """Vrai : ``/mcp/console`` répond aussi au réseau, mandataire compris, jeton toujours exigé (ADR 0126)."""
        return bool(dict(self._get(CONSOLE_MCP_KEY) or {}).get("network"))

    async def save_console_mcp_network(self, network: bool) -> None:
        data = dict(self._get(CONSOLE_MCP_KEY) or {})
        if network and not data.get("token_sealed"):
            raise ValueError("la console n'a pas de jeton")
        if network:
            data["network"] = True
        else:
            data.pop("network", None)
        await self._put(CONSOLE_MCP_KEY, data)

    def console_mcp_served(self) -> tuple[str, ...] | None:
        """Ce que sert la console en MCP (``inspector.mcp`` : des pages de ``SERVABLE`` et des ``PARTS``) ;
        ``None`` : ce qu'elle sert d'office."""
        got = dict(self._get(CONSOLE_MCP_KEY) or {}).get("served")
        return tuple(str(k) for k in got) if isinstance(got, list) else None

    async def save_console_mcp_served(self, served: Sequence[str] | None) -> None:
        unknown = [k for k in served or () if k not in (*console_mcp.SERVABLE, *console_mcp.PARTS)]
        if unknown:
            raise ValueError(f"la console ne sert pas « {unknown[0]} »")
        data = dict(self._get(CONSOLE_MCP_KEY) or {})
        if served is None:
            data.pop("served", None)
        else:
            data["served"] = sorted(set(served))
        await self._put(CONSOLE_MCP_KEY, data)

    # ── Ses outils prêtés à un agent (``/mcp/pret/<nom>``, ADR 0122) ──
    def lent(self) -> dict[str, dict[str, Any]]:
        """Nom → ``{digest, hint, token_at, token_by, tools, writes, by, created_at}`` : jamais le jeton en clair.
        ``by`` : l'opératrice qui l'a déclaré — l'agent agit avec ses droits à elle, en tête-à-tête."""
        return {str(n): dict(e) for n, e in dict(self._get(LENT_KEY) or {}).items() if isinstance(e, dict)}

    async def save_lent(self, name: str, *, tools: Sequence[str], writes: bool, by: str, at: int) -> None:
        """Un point de prêt déclaré ou réglé (ses outils, s'il peut écrire) ; son jeton ne change pas."""
        if not LENT_NAME.fullmatch(name):
            raise ValueError("un nom de point : des minuscules, des chiffres et des tirets (40 au plus)")
        entries = self.lent()
        entry = entries.get(name) or {"digest": "", "hint": "", "by": by[:80], "created_at": int(at)}
        entries[name] = {**entry, "tools": sorted({str(t) for t in tools}), "writes": bool(writes)}
        await self._put(LENT_KEY, entries)

    async def new_lent_token(self, name: str, *, by: str, at: int) -> str:
        """Un jeton neuf pour ce point (l'ancien ne vaut plus) ; montré une fois, seule son empreinte est gardée."""
        entries = self.lent()
        if name not in entries:
            raise ValueError("point inconnu : déclare-le d'abord")
        token = LENT_PREFIX + secrets.token_urlsafe(32)
        entries[name] = {**entries[name], "digest": hashlib.sha256(token.encode()).hexdigest(),
                         "hint": token[:len(LENT_PREFIX) + 4], "token_by": by[:80], "token_at": int(at)}
        await self._put(LENT_KEY, entries)
        return token

    async def remove_lent(self, name: str) -> bool:
        entries = self.lent()
        if entries.pop(name, None) is None:
            return False
        await self._put(LENT_KEY, entries)
        return True

    # ── Ses outils, situation par situation (ADR 0122) ──
    def tool_rules(self) -> dict[str, dict[str, str]]:
        """Les règles d'outils d'un opérateur : par situation, « outil → off, hand ou ask »."""
        return {s: dict(r) for s, r in self._tool_rules.items()}

    def tool_rules_for(self, situation: str) -> dict[str, str]:
        """Les règles d'une situation (``runtime.tools.situation_of``) : ce que lit le pipeline à chaque épisode."""
        return self._tool_rules.get(situation, {})

    async def save_tool_rules(self, situation: str, rules: Mapping[str, str | None]) -> dict[str, str]:
        """Les règles d'une situation, mises à jour : une règle ``None`` rend l'outil à ce que dit le code."""
        if situation not in TOOL_SITUATIONS:
            raise ValueError(f"situation inconnue : {situation}")
        kept = dict(self._tool_rules.get(situation, {}))
        for tool, rule in rules.items():
            if rule is None:
                kept.pop(tool, None)
            elif rule in TOOL_RULES:
                kept[tool] = rule
            else:
                raise ValueError(f"règle inconnue : {rule}")
        everything = {**self._tool_rules, situation: kept}
        everything = {s: r for s, r in everything.items() if r}
        await self._put(TOOL_RULES_KEY, everything)
        self._tool_rules = everything
        return kept

    # ── Ses autrices et leurs flux (ADR 0124) ──
    def _read_authors(self) -> authors_m.Authors | None:
        stored = self._get(AUTHORS_KEY)
        if stored is None:
            return None
        try:
            return authors_m.Authors.model_validate(stored)
        except ValueError:
            log.warning("autrices illisibles : celles par défaut")
            return None

    def authors(self) -> authors_m.Authors:
        """Ses autrices et le flux de chacune. Rien d'enregistré : les autrices livrées, chacune d'office sur son flux
        (une par boîte mail) ; enregistrées, un champ vide d'une autrice livrée reprend son défaut."""
        got = call(self.reference_thread, label="le fil de référence de sa persona")
        reference = got if isinstance(got, str) else ""
        if self._authors is None:
            return authors_m.defaults(self.email().accounts, reference)
        return authors_m.filled(self._authors, reference)

    def author_for(self, flow: str) -> Any:
        """L'autrice d'un flux (``vocab.flows.Author``), ou ``None`` : ce que lit le pipeline."""
        return self.authors().author_for(flow)

    async def save_authors(self, value: authors_m.Authors) -> None:
        await self._put(AUTHORS_KEY, value.model_dump(mode="json"))
        self._authors = value

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
