"""Les réglages d'exploitation (fournisseurs, clés, rôles), rangés dans
``mind.db`` ; les secrets chiffrés (Fernet).

La clé de chiffrement vient de ``MIKA_SECRET_KEY`` ou, à défaut, d'un
fichier ``secret.key`` créé au premier démarrage à côté des bases (droits
0600). Elle ne va jamais dans le dépôt.

Un jeton porteur qu'on ne fait que vérifier (appareils, console MCP, prêts,
Teams, réveils) n'est pas gardé, même scellé : seule son empreinte SHA-256
l'est, et c'est l'empreinte du jeton présenté qu'on lui compare.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, TypeVar

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Mapped, mapped_column

from mika.adapters.imaging.config import ImageBackendSpec, ImagingConfig
from mika.adapters.llm.config import ROLES, BackendSpec, LLMConfig
from mika.adapters.web.gate import new_key, token_digest
from mika.app import authors as authors_m
from mika.app.domains import DOMAINS, part
from mika.inspector import mcp as console_mcp
from mika.ports.agenda import split_calendar_key
from mika.ports.imaging import ROLES as IMAGE_ROLES
from mika.ports.sql import Key, LongText, MindBase, upsert
from mika.runtime.boundary import call
from mika.runtime.tool_offer import RULES as TOOL_RULES
from mika.vocab.access import AgendaRule, Table, ToolRule
from mika.vocab.canals import Canals, CanalTable
from mika.vocab.rights import Rights

log = logging.getLogger("mika.settings")
#: les rôles inconnus déjà signalés au journal
_IGNORED_ROLES: set[str] = set()

LLM_KEY = "llm"
#: les fournisseurs d'images et leurs rôles (clés scellées)
IMAGING_KEY = "imaging"
STT_KEY = "stt"
#: les notifications du téléphone (ADR 0077) : la clé du compte de service Firebase, scellée
PUSH_KEY = "push"
#: … ou, à défaut d'une clé collée dans la console, ce fichier du dossier de données (à côté de ``secret.key``)
PUSH_KEY_FILE = "firebase-service-account.json"
#: le jeton des appareils (``POST /api/perceptions``) : son empreinte seule
SENSORS_KEY = "sensors"
#: le point MCP de la console (le Claude Code d'une opératrice) : l'empreinte de son jeton, et ce qu'il sert (ADR 0122)
CONSOLE_MCP_KEY = "console_mcp"
#: les deux ont été gardés scellés (réversibles) avant : convertis en empreinte à l'ouverture
HASHED_TOKEN_KEYS = (SENSORS_KEY, CONSOLE_MCP_KEY)
#: les points MCP qui prêtent ses outils à un agent (ADR 0122) : par nom, l'empreinte de leur jeton, leurs outils
LENT_KEY = "mcp_lent"
#: le nom d'un point de prêt : son adresse (``/mcp/pret/<nom>``)
LENT_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
#: ce qui commence le jeton d'un point de prêt (ce qu'on en montre ensuite : son début)
LENT_PREFIX = "mlp_"
PERSONA_KEY = "persona"
OVERRIDES_KEY = "overrides"
#: le tableau de droits de chaque agenda qu'on a réglé (ADR 0309), par sa clé ; les autres ont celui que leur
#: propriétaire et leurs partages donnent (``plugins/agenda/rights.py``)
AGENDA_RIGHTS_KEY = "agenda_droits"
#: ses droits (ADR 0134) : les tableaux de ses canaux, de ses familles d'outils, et l'offre réglée de ses outils
CANALS_KEY = "canaux"
FAMILIES_KEY = "outils_familles"
IN_HAND_KEY = "outils_en_main"
#: ses autrices et le flux de chacune (ADR 0124)
AUTHORS_KEY = "authors"
#: les réglages d'un canal retiré (Telegram, ADR 0060) : effacés à l'ouverture — un jeton scellé que plus
#: rien ne lit ne reste pas dans ``mind.db`` ni dans ses sauvegardes
RETIRED_KEYS = ("telegram", "envoi", "tool_rules")


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
            fresh = Fernet.generate_key()
            try:  # né en 0600, d'un seul coup : jamais un instant lisible par d'autres
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass  # un autre processus l'a créée entre-temps : on lit la sienne
            else:
                with os.fdopen(fd, "wb") as f:
                    f.write(fresh)
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


class SettingsPart:
    """Les réglages d'un domaine (ADR 0310) : une classe de son dossier (``app/domains/<nom>/settings.py``), posée sur
    la porte des réglages. Elle lit et écrit ses clés par cette porte seulement (``_get``, ``_put`` qui dit chaque
    écriture, ``box`` pour sceller, ``writing`` pour relire puis récrire sans se croiser) : jamais le magasin lui-même,
    ce que
    ``tests/architecture/test_changes_signalled.py`` garde. On la prend par ``Settings.of(SaClasse)``."""

    def __init__(self, door: Settings) -> None:
        self.door = door
        self.box = door.box
        #: le verrou des réglages qu'on relit pour n'en changer qu'une entrée (``Settings.writing``) : le même pour tous
        self.writing = door.writing

    def _get(self, key: str) -> Any:
        return self.door._get(key)

    async def _put(self, key: str, value: Any) -> None:
        await self.door._put(key, value)

    async def open(self) -> None:
        """Appelé à l'ouverture des réglages, une fois leur table là : un domaine qui tient ses réglages en mémoire
        (lus depuis d'autres fils, ou à chaque épisode) les lit ici. Sa classe doit alors être prise avant
        l'ouverture — dans le câblage de son domaine (``wire``)."""


P = TypeVar("P", bound=SettingsPart)


class Settings:
    def __init__(self, store: Any, box: SecretBox) -> None:
        self.store = store
        self.box = box
        #: ses droits (ADR 0134), lus à chaque épisode : tenus en mémoire, relus à l'ouverture
        self._rights = Rights(canals=Canals())
        #: ses autrices enregistrées, lues à chaque épisode (et à chaque brouillon) : tenues en mémoire ; ``None`` :
        #: rien d'enregistré (celles par défaut)
        self._authors: authors_m.Authors | None = None
        #: le fil de référence de sa persona (posé par le serveur) : l'exemple de « Message » quand le sien est vide
        self.reference_thread: Callable[[], str] = lambda: ""
        #: prévenu après chaque enregistrement (``_put``), par sa clé : les écrans de tous les jours relisent ce qu'il
        #: change (ADR 0308 : ces réglages sont hors du journal ; posé par le serveur)
        self.on_saved: Callable[[str], None] = lambda key: None
        #: ses boîtes, ses comptes Teams et ses serveurs MCP s'enregistrent en entier : qui les relit pour en changer
        #: une entrée le fait sous ce verrou, jusqu'à l'écriture (et ce qui s'en rejournalise). Deux enregistrements
        #: qui se croisent (deux personnes, une personne et la console) ne s'effacent donc pas. Il ne se reprend pas :
        #: ce qui le tient n'appelle rien qui le prenne à son tour (``settle`` des serveurs MCP le prend lui-même).
        self.writing = asyncio.Lock()
        #: les réglages de chaque domaine, par leur classe (``of``)
        self._parts: dict[type, SettingsPart] = {}
        #: ouverts : leur table existe, ce qu'ils tiennent en mémoire est lu
        self._opened = False

    async def open(self) -> None:
        def create(sql: Any) -> None:
            sql.create(SettingRow)
            sql.execute(delete(SettingRow).where(SettingRow.key.in_(RETIRED_KEYS)))

        await self.store.run_mind(create)
        for key in HASHED_TOKEN_KEYS:
            await self._hash_sealed_token(key)
        self._rights = self._read_rights()
        self._authors = self._read_authors()
        for own in list(self._parts.values()):  # ce que les réglages d'un domaine tiennent en mémoire
            await own.open()
        self._opened = True

    def _get(self, key: str) -> Any:
        try:
            rows = self.store.query_mind(select(SettingRow.value).where(SettingRow.key == key))
        except NO_TABLE:  # la table n'existe pas encore (avant ``open``)
            return None
        return json.loads(rows[0][0]) if rows else None

    async def _put(self, key: str, value: Any) -> None:
        """La seule écriture des réglages : enregistrée, puis dite (``on_saved``)."""
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
        await self.store.run_mind(lambda sql: upsert(sql, SettingRow, {"key": key, "value": raw}, keys=["key"]))
        self._saved(key)

    def _saved(self, key: str) -> None:
        """Ce réglage vient d'être enregistré : qui écoute le sait ; un écouteur en panne ne défait pas l'écriture."""
        call(self.on_saved, key, label="un réglage enregistré")

    def named(self, name: str) -> Any:
        """Les réglages d'un domaine, par son nom (ADR 0310) : pour une page du cadre qui croise plusieurs domaines et
        n'en importe aucun (les partages, les droits, l'annuaire). Sa fiche nomme le module de ses réglages
        (``Domain.settings``), lu ici à la demande. Un domaine prend les siens par leur classe (``of``)."""
        domain = next((d for d in DOMAINS if d.name == name and d.settings is not None), None)
        if domain is None:
            raise KeyError(f"le domaine « {name} » n'a pas de réglages dans sa fiche")
        return self.of(part(domain.settings, "SETTINGS"))

    def of(self, kind: type[P]) -> P:
        """Les réglages d'un domaine (ADR 0310) : sa classe (une ``SettingsPart`` de son dossier), construite une
        fois sur cette porte — ce qu'elle tient en mémoire et ses verrous valent donc pour tout le serveur."""
        if kind not in self._parts:
            if self._opened and kind.open is not SettingsPart.open:
                raise RuntimeError(f"{kind.__name__} tient un état en mémoire, lu à l'ouverture des réglages : son "
                                   "domaine le prend dans son câblage (``wire``), avant l'ouverture")
            self._parts[kind] = kind(self)
        return self._parts[kind]  # type: ignore[return-value]

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
        # l'effort d'un rôle (ADR 0285) : celui d'un rôle qui n'existe plus est oublié de même
        efforts = {r: e for r, e in dict(data.get("efforts") or {}).items() if r in ROLES}
        return LLMConfig.model_validate({"backends": backends, "routes": routes, "efforts": efforts,
            **({"context_tokens": data["context_tokens"]} if "context_tokens" in data else {})})

    async def save_llm(self, cfg: LLMConfig) -> LLMConfig:
        """Enregistre la configuration des modèles et rend celle qui vaut désormais : revalidée (une copie
        modifiée, ``model_copy``, ne passe pas par les validateurs) — le premier fournisseur déclaré y sert
        « répondre » d'office."""
        cfg = LLMConfig.model_validate({"backends": dict(cfg.backends), "routes": dict(cfg.routes),
                                        "efforts": dict(cfg.efforts)})
        problems = cfg.problems()
        if problems:
            raise ValueError("; ".join(problems))
        backends = {}
        for name, spec in cfg.backends.items():
            data = spec.model_dump()
            data["api_key_sealed"] = self.box.seal(data.pop("api_key"))
            backends[name] = data
        await self._put(LLM_KEY, {"backends": backends, "routes": dict(cfg.routes), "efforts": dict(cfg.efforts)})
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

    # ── Transcription ──
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

    # ── Ses droits (ADR 0134) : les canaux, ses familles d'outils, l'offre réglée ──
    def _read_rights(self) -> Rights:
        """Ce qui est rangé ; un tableau illisible est écarté (son minimum vital vaut), jamais bloquant."""
        try:
            canals = Canals.model_validate(self._get(CANALS_KEY) or {"tables": {}})
        except ValueError:
            log.warning("droits : les tableaux des canaux sont illisibles, les minimums vitaux valent")
            canals = Canals()
        families: dict[str, Table[ToolRule]] = {}
        for bundle, raw in dict(self._get(FAMILIES_KEY) or {}).items():
            try:
                families[str(bundle)] = Table[ToolRule].model_validate(raw)
            except ValueError:
                log.warning("droits : le tableau de la famille « %s » est illisible, son minimum vital vaut",
                            str(bundle)[:40])
        raw_hand = dict(self._get(IN_HAND_KEY) or {})
        in_hand = {str(k): str(v) for k, v in raw_hand.items() if v in TOOL_RULES}
        agendas: dict[str, Table[AgendaRule]] = {}
        for calendar, raw in dict(self._get(AGENDA_RIGHTS_KEY) or {}).items():
            try:
                agendas[str(calendar)] = Table[AgendaRule].model_validate(raw)
            except ValueError:
                log.warning("droits : le tableau d'un agenda est illisible, celui de son propriétaire vaut")
        return Rights(canals=canals, families=families, in_hand=in_hand, agendas=agendas)

    def access_tables(self) -> Rights:
        """Ses droits tels que le registre les lit à chaque épisode (``Registry.access_tables``)."""
        return self._rights

    def canals(self) -> Canals:
        return self._rights.canals or Canals()

    async def save_canal(self, key: str, table: CanalTable | None) -> Canals:
        """Le tableau d'un canal, enregistré ; ``None`` : retiré, son minimum vital vaut de nouveau."""
        tables = dict(self._rights.canals.tables)
        if table is None:
            tables.pop(key, None)
        else:
            tables[key] = CanalTable.model_validate(table.model_dump())
        canals = Canals(tables=tables)
        await self._put(CANALS_KEY, canals.model_dump(mode="json"))
        self._rights = replace(self._rights, canals=canals)
        return canals

    def families(self) -> dict[str, Table[ToolRule]]:
        return dict(self._rights.families)

    async def save_family(self, bundle: str, table: Table[ToolRule] | None) -> None:
        """Le tableau d'une famille de ses outils, enregistré ; ``None`` : retiré, son minimum vital vaut."""
        families = dict(self._rights.families)
        if table is None:
            families.pop(bundle, None)
        else:
            families[bundle] = Table[ToolRule].model_validate(table.model_dump())
        await self._put(FAMILIES_KEY, {k: v.model_dump(mode="json") for k, v in families.items()})
        self._rights = replace(self._rights, families=families)

    def in_hand(self) -> dict[str, str]:
        return dict(self._rights.in_hand)

    async def save_in_hand(self, tool: str, rule: str | None) -> None:
        """L'offre réglée d'un outil : en main, à chercher ; ``None`` : ce que prévoit le code."""
        if rule is not None and rule not in TOOL_RULES:
            raise ValueError(f"offre inconnue : {rule}")
        kept = dict(self._rights.in_hand)
        if rule is None:
            kept.pop(tool, None)
        else:
            kept[tool] = rule
        await self._put(IN_HAND_KEY, kept)
        self._rights = replace(self._rights, in_hand=kept)


    # ── Les droits de ses agendas (ADR 0309) : avec ceux des canaux et des familles, lus à chaque épisode ──
    def agenda_tables(self) -> dict[str, Table[AgendaRule]]:
        """Les tableaux de droits réglés des agendas (ADR 0309), par agenda ; les autres ont celui que leur propriétaire
        et leurs partages donnent (``plugins/agenda/rights.py::table_of``, qui lit les deux)."""
        return dict(self._rights.agendas)

    async def save_agenda_table(self, calendar: str, table: Table[AgendaRule] | None) -> None:
        """Le tableau de droits d'un agenda, enregistré — par son propriétaire (l'API par personne) ou par un opérateur
        (Réglages › Droits) ; ``None`` : retiré, celui que son propriétaire et ses partages donnent vaut de nouveau. Lu
        à chaque épisode (``access_tables``)."""
        if not split_calendar_key(calendar)[0]:
            raise ValueError(f"pas un agenda : « {calendar[:60]} »")
        tables = dict(self._rights.agendas)
        if table is None:
            tables.pop(calendar, None)
        else:
            tables[calendar] = Table[AgendaRule].model_validate(table.model_dump())
        await self._put(AGENDA_RIGHTS_KEY, {k: v.model_dump(mode="json") for k, v in sorted(tables.items())})
        self._rights = replace(self._rights, agendas=tables)

    # ── Les jetons gardés en empreinte (appareils, console MCP) ──
    def _token_digest(self, key: str) -> str:
        """L'empreinte du jeton de ``key`` (vide : aucun). Un jeton encore scellé par les réglages d'avant vaut par
        son empreinte, calculée ici ; ``open`` le convertit pour de bon."""
        data = dict(self._get(key) or {})
        digest = str(data.get("digest") or "")
        if digest:
            return digest
        token = self.box.open(str(data.get("token_sealed") or ""))
        return token_digest(token) if token else ""

    async def _hash_sealed_token(self, key: str) -> None:
        """Un jeton que les réglages d'avant gardaient scellé devient une empreinte : déchiffré, haché, le scellé
        retiré. Un scellé qui ne s'ouvre plus (``secret.key`` changée) part sans empreinte : il ne valait déjà plus —
        et la console fermée ainsi ne reste pas ouverte au réseau."""
        data = dict(self._get(key) or {})
        if "token_sealed" not in data:
            return
        token = self.box.open(str(data.pop("token_sealed") or ""))
        if token:
            data["digest"] = token_digest(token)
        else:
            data.pop("network", None)
        await self._put(key, data)

    # ── Appareils (``POST /api/perceptions``) ──
    def sensors_digest(self) -> str:
        """L'empreinte du jeton des appareils (vide : aucun) ; la porte compare les empreintes."""
        return self._token_digest(SENSORS_KEY)

    async def new_sensors_token(self) -> str:
        """Un jeton neuf (l'ancien ne vaut plus) ; montré une fois, seule son empreinte est gardée."""
        token = new_key()
        await self._put(SENSORS_KEY, {"digest": token_digest(token)})
        return token

    def console_mcp_digest(self) -> str:
        """L'empreinte du jeton de ``/mcp/console`` (vide : aucun, le point répond 404)."""
        return self._token_digest(CONSOLE_MCP_KEY)

    async def new_console_mcp_token(self) -> str:
        """Un jeton neuf pour ``/mcp/console`` (l'ancien ne vaut plus) ; montré une fois, seule son empreinte est
        gardée."""
        token = new_key()
        data = {k: v for k, v in dict(self._get(CONSOLE_MCP_KEY) or {}).items() if k != "token_sealed"}
        await self._put(CONSOLE_MCP_KEY, {**data, "digest": token_digest(token)})
        return token

    async def revoke_console_mcp_token(self) -> bool:
        """Le point de la console fermé (404) ; faux s'il n'avait pas de jeton. Ce qu'il sert reste choisi ; son
        ouverture au réseau, non : un jeton neuf la rouvre en local seulement."""
        data = dict(self._get(CONSOLE_MCP_KEY) or {})
        data.pop("network", None)
        had = bool(data.pop("digest", "")) | bool(data.pop("token_sealed", ""))
        if not had:
            return False
        await self._put(CONSOLE_MCP_KEY, data)
        return True

    def console_mcp_network(self) -> bool:
        """Vrai : ``/mcp/console`` répond aussi au réseau, mandataire compris, jeton toujours exigé (ADR 0126)."""
        return bool(dict(self._get(CONSOLE_MCP_KEY) or {}).get("network"))

    async def save_console_mcp_network(self, network: bool) -> None:
        data = dict(self._get(CONSOLE_MCP_KEY) or {})
        if network and not self.console_mcp_digest():
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
        token = new_key(LENT_PREFIX)
        entries[name] = {**entries[name], "digest": token_digest(token),
                         "hint": token[:len(LENT_PREFIX) + 4], "token_by": by[:80], "token_at": int(at)}
        await self._put(LENT_KEY, entries)
        return token

    async def remove_lent(self, name: str) -> bool:
        entries = self.lent()
        if entries.pop(name, None) is None:
            return False
        await self._put(LENT_KEY, entries)
        return True

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
            return authors_m.defaults(self.named("mail").email().accounts, reference)
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
        """Les surcharges, par faculté (une couche vide n'est pas gardée)."""
        await self._put(OVERRIDES_KEY, {k: v for k, v in overrides.items() if v})
