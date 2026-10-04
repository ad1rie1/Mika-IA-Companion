"""La configuration des serveurs MCP branchés (ADR 0064) : un enregistrement par serveur, dans les réglages (ses
secrets scellés), jamais dans le journal ; le hub la relit à chaque usage.

Ce que l'opérateur dit d'abord, c'est **à quoi sert le serveur, pour elle** : la ligne de son catalogue. Puis
comment le joindre (une adresse, ou une commande sur cette machine), pour qui, quand, et ses bornes.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mika.kernel.codec import canonical_json
from mika.kernel.forms import Knob
from mika.ports.mcp import AUDIENCES

#: le nom d'un serveur : il entre dans le nom de ses outils (``mcp_<serveur>_<outil>``) et de son lot
SERVER_NAME = re.compile(r"[a-z][a-z0-9_]{0,23}")
SERVER_NAME_RULE = "des minuscules, chiffres et _ (24 au plus), en commençant par une lettre"
#: la famille de lots (``mcp.<serveur>``) et le préfixe des noms d'outils
FAMILY = "mcp"
#: un nom d'outil chez elle : ce qu'acceptent les fournisseurs
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
MAX_TOOL_NAME = 64
#: les suffixes d'un nom de machine du réseau local
LOCAL_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain")
#: une description de serveur ou d'outil au-delà : coupée (une donnée venue d'ailleurs)
MAX_DESCRIPTION = 1024
#: un schéma d'arguments au-delà : l'outil est refusé (le budget du prompt le paierait à chaque épisode)
MAX_SCHEMA = 16_384

TRANSPORTS = (("distant", "à une adresse (HTTP)"), ("local", "sur cette machine (une commande)"))
AUTHS = (("aucune", "aucune"), ("bearer", "jeton (Authorization: Bearer …)"), ("entete", "un en-tête nommé"))
NETWORKS = (("aucun", "aucun réseau"), ("isole", "réseau isolé (Internet, jamais cette machine ni le réseau local)"))

_LOCAL = ((("transport", ("local",)),))
_REMOTE = ((("transport", ("distant",)),))


class McpServer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    purpose: Annotated[str, Knob(
        label="À quoi il sert, pour elle", widget="textarea", group="Pour elle", advanced=False, order=5,
        help="Une phrase qu'elle lira dans son catalogue d'outils (« la météo et les prévisions d'une ville »). "
             "Obligatoire : sans elle, elle ne saurait pas quand s'en servir.")] = ""
    when_to_use: Annotated[str, Knob(
        label="Quand s'en servir", widget="textarea", group="Pour elle", advanced=False, order=6,
        help="Facultatif : quand y penser, ou ne pas y penser (« seulement quand on lui parle d'une sortie »).")] = ""
    enabled: Annotated[bool, Knob(label="Actif", group="Pour elle", advanced=False, order=7,
                                  help="Décoché : il n'est ni joint ni offert ; ses réglages et ses outils "
                                       "approuvés restent.")] = True
    transport: Annotated[Literal["distant", "local"], Knob(
        label="Où il tourne", group="Connexion", choices=TRANSPORTS, advanced=False, order=10,
        help="À une adresse (sur cette machine, ton réseau ou ailleurs), ou lancé ici par une commande, isolé.")] = \
        "distant"
    url: Annotated[str, Knob(
        label="Adresse", group="Connexion", advanced=False, order=11, only=_REMOTE,
        help="L'adresse MCP « streamable HTTP » (https://…/mcp). En http seulement vers cette machine ou ton "
             "réseau local : le jeton passerait en clair.")] = ""
    auth: Annotated[Literal["aucune", "bearer", "entete"], Knob(
        label="Authentification", group="Connexion", choices=AUTHS, order=12, only=_REMOTE)] = "aucune"
    token: Annotated[str, Knob(
        label="Jeton", group="Connexion", secret=True, order=13, only_any=((("auth", ("bearer", "entete")),),),
        help="Chiffré, jamais réaffiché ; vide : inchangé.")] = ""
    header: Annotated[str, Knob(
        label="Nom de l'en-tête", group="Connexion", order=14, only=(("auth", ("entete",)),),
        help="Celui qui porte le jeton (X-API-Key…).")] = "X-API-Key"
    ca_file: Annotated[str, Knob(
        label="Autorité de certification", group="Connexion", order=15, only=_REMOTE,
        help="Le chemin d'un certificat d'autorité (.pem) pour un serveur de ton réseau signé par ta propre "
             "autorité ; vide : les autorités du système.")] = ""
    command: Annotated[str, Knob(
        label="Commande", group="Sur cette machine", advanced=False, order=20, only=_LOCAL,
        help="Le programme à lancer (npx, uvx, python3, ou un chemin dans son dossier). Il tourne isolé : /usr "
             "en lecture, son dossier à lui, rien d'autre.")] = ""
    args: Annotated[tuple[str, ...], Knob(
        label="Arguments", group="Sur cette machine", order=21, only=_LOCAL,
        help="Un par ligne.")] = ()
    env: Annotated[tuple[str, ...], Knob(
        label="Variables", group="Sur cette machine", order=22, only=_LOCAL,
        help="Une par ligne : NOM=valeur. Rien n'est hérité de l'environnement du serveur.")] = ()
    secret_env: Annotated[str, Knob(
        label="Variables secrètes", group="Sur cette machine", secret=True, order=23, only=_LOCAL,
        help="NOM=valeur, séparées par « ; ». Chiffrées, jamais réaffichées ; vide : inchangées.")] = ""
    network: Annotated[Literal["aucun", "isole"], Knob(
        label="Réseau", group="Sur cette machine", choices=NETWORKS, order=24, only=_LOCAL,
        help="Isolé : il peut aller sur Internet, jamais sur cette machine ni sur ton réseau local.")] = "aucun"
    shared: Annotated[tuple[str, ...], Knob(
        label="Dossiers partagés", group="Sur cette machine", order=25, only=_LOCAL,
        help="Un chemin absolu par ligne, en lecture seule ; « chemin:rw » pour qu'il puisse y écrire.")] = ()
    audience: Annotated[Literal["proprietaire", "comptes"], Knob(
        label="Pour qui", group="Qui et quand", choices=AUDIENCES, advanced=False, order=30,
        help="Jamais dans un salon, quel que soit ce choix. Ce qu'elle met dans un appel part de la machine.")] = \
        "proprietaire"
    in_conversation: Annotated[bool, Knob(label="Quand elle répond", group="Qui et quand", advanced=False,
                                          order=31)] = True
    in_initiative: Annotated[bool, Knob(label="Quand elle prend la parole", group="Qui et quand", order=32)] = False
    in_work: Annotated[bool, Knob(label="Quand elle travaille", group="Qui et quand", order=33,
                                  help="Un pas sur un but ou une exécution de projet — seulement si le but ou le "
                                       "projet a pris ce lot.")] = False
    in_hand: Annotated[bool, Knob(label="En main", group="Qui et quand", order=34,
                                  help="Décoché (conseillé) : ses outils sont à la demande, elle les cherche par ce "
                                       "qu'ils font quand elle en a besoin.")] = False
    timeout_s: Annotated[float, Knob(label="Délai d'un appel", group="Bornes", lo=1, hi=300, unit="s",
                                     order=40)] = 30.0
    max_calls: Annotated[int, Knob(label="Appels par épisode (par outil)", group="Bornes", lo=1, hi=20,
                                   order=41)] = 3
    max_result_chars: Annotated[int, Knob(label="Réponse lue (caractères)", group="Bornes", lo=200, hi=20_000,
                                          order=42)] = 4000
    breaker: Annotated[int, Knob(label="Pannes d'affilée avant de le couper", group="Bornes", lo=1, hi=20,
                                 order=43)] = 3

    @property
    def local(self) -> bool:
        return self.transport == "local"

    def problems(self) -> list[str]:
        """Ce qui l'empêche de servir (vide : prêt)."""
        out = []
        if len(self.purpose.strip()) < 8:
            out.append("dis à quoi il sert, pour elle (une phrase)")
        if self.local:
            if not self.command.strip():
                out.append("une commande à lancer")
            out += [f"variable « {line[:30]} » : NOM=valeur" for line in self.env if not ENV_LINE.fullmatch(line)]
            out += [f"dossier partagé « {line[:60]} » : un chemin absolu" for line in self.shared
                    if not shared_path(line)[0].startswith("/")]
        else:
            out += url_problems(self.url)
            if self.auth != "aucune" and not self.token:
                out.append("un jeton")
            if self.auth == "entete" and not HEADER.fullmatch(self.header):
                out.append("un nom d'en-tête (lettres, chiffres, -)")
        return out

    @property
    def ready(self) -> bool:
        return not self.problems()

    def headers(self) -> dict[str, str]:
        if self.auth == "bearer" and self.token:
            return {"Authorization": f"Bearer {self.token}"}
        if self.auth == "entete" and self.token:
            return {self.header: self.token}
        return {}

    def secret_vars(self) -> dict[str, str]:
        out = {}
        for part in self.secret_env.split(";"):
            if "=" in part:
                k, _, v = part.strip().partition("=")
                if ENV_NAME.fullmatch(k.strip()):
                    out[k.strip()] = v
        return out

    def connection(self) -> str:
        """Ce qui décide d'une connexion (une session ouverte avec d'autres réglages est fermée)."""
        data = self.model_dump(include={"transport", "url", "auth", "token", "header", "ca_file", "command", "args",
                                        "env", "secret_env", "network", "shared"})
        return hashlib.sha256(canonical_json(data).encode()).hexdigest()


ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
ENV_LINE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}=.*")
HEADER = re.compile(r"[A-Za-z0-9-]{1,64}")


def shared_path(line: str) -> tuple[str, bool]:
    """(chemin, écriture permise) d'une ligne « chemin » ou « chemin:rw »."""
    line = line.strip()
    if line.endswith(":rw"):
        return line[:-3], True
    if line.endswith(":ro"):
        return line[:-3], False
    return line, False


def private_host(host: str) -> bool:
    """Une machine de ce côté-ci : cette machine, une adresse privée, un nom du réseau local."""
    host = host.strip("[]").lower()
    if host in ("localhost", "localhost.localdomain") or host.endswith(LOCAL_SUFFIXES) or (host and "." not in host
                                                                                          and ":" not in host):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return private_ip(ip)


def private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_loopback or ip.is_private or ip.is_link_local


def url_problems(url: str) -> list[str]:
    url = url.strip()
    if not url:
        return ["une adresse"]
    try:
        parts = urlsplit(url)
    except ValueError:
        return ["une adresse lisible"]
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ["une adresse http(s)://…"]
    if parts.username or parts.password:
        return ["pas d'identifiants dans l'adresse (le jeton a son champ)"]
    if parts.scheme == "http" and not private_host(parts.hostname):
        return ["http seulement vers cette machine ou ton réseau local (ailleurs : https)"]
    return []


class McpConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    servers: Annotated[dict[str, McpServer], Knob(
        label="Serveurs", advanced=False, order=10,
        help=f"Chaque serveur MCP dont elle peut utiliser les outils. La clé est un nom court ({SERVER_NAME_RULE}) : "
             "il entre dans le nom de ses outils.")] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _keys(self) -> McpConfig:
        bad = [k for k in self.servers if not SERVER_NAME.fullmatch(k)]
        if bad:
            raise ValueError(f"nom de serveur invalide : « {bad[0][:40]} » ({SERVER_NAME_RULE})")
        return self


# ── ce que le hub garde de chaque outil approuvé ──────────────────────────


class StoredReview(BaseModel):
    """Une décision de l'opérateur sur un outil, telle qu'elle est rangée (``mcp_tools``)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    fingerprint: str
    enabled: bool = False
    nature: Literal["lecture", "action"] = "lecture"
    approval: Literal["aucun", "conversation", "operateur"] = "conversation"
    description: str = ""
    server_description: str = ""
    title: str = ""
    schema_: dict[str, Any] = Field(default_factory=dict, alias="schema")
    by: str = ""
    at: int = 0


def valid_choice(value: str, choices: tuple[tuple[str, str], ...]) -> bool:
    return value in {k for k, _ in choices}


# ── noms et empreintes ────────────────────────────────────────────────────


def fingerprint(name: str, description: str, schema: Any, annotations: Any) -> str:
    """L'empreinte de ce qu'un outil dit être : un changement de l'un des quatre le suspend."""
    raw = canonical_json({"name": name, "description": description, "schema": schema or {},
                          "annotations": annotations or {}})
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def tool_name(server: str, remote: str, taken: set[str] | None = None) -> str:
    """Son nom chez elle : ``mcp_<serveur>_<outil>``, des caractères qu'acceptent les fournisseurs, 64 au plus ;
    une collision (deux noms que le nettoyage rend égaux, un nom trop long) prend une empreinte."""
    base = f"{FAMILY}_{server}_{_UNSAFE.sub('_', remote)}"
    taken = taken if taken is not None else set()
    if len(base) <= MAX_TOOL_NAME and base not in taken:
        return base
    digest = hashlib.sha256(f"{server}/{remote}".encode()).hexdigest()[:8]
    return f"{base[:MAX_TOOL_NAME - 9]}_{digest}"


def bundle_of(server: str) -> str:
    return f"{FAMILY}.{server}"
