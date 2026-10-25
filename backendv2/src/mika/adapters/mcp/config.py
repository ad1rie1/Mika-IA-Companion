"""La configuration des serveurs MCP branchés (ADR 0064) : un enregistrement par serveur, dans les réglages (ses
secrets scellés), jamais dans le journal ; le hub la relit à chaque usage.

Ce que l'opérateur dit d'abord, c'est **à quoi sert le serveur, pour elle** : la ligne de son catalogue. Puis
comment le joindre (une adresse, ou une commande sur cette machine), qui peut quoi — ses lignes d'accès, lues de haut
en bas, et la ligne par défaut (ADR 0131) —, et ses bornes.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Mapping
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mika.kernel.codec import canonical_json
from mika.kernel.forms import Knob
from mika.ports.mcp import KEEPS, MOMENTS, POLICIES, WHO_ACCOUNTS, WHO_OWNER, WHO_PERSON

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


_Policy = Literal["seule", "carte", "toi", "non"]
_Keep = Literal["public", "perso", "prive", "rien"]
_Moment = Literal["conversation", "initiative", "travail"]
#: qui une ligne désigne : toi, les comptes, ou une personne nommée par sa clé
WHO = re.compile(rf"(?:{WHO_OWNER}|{WHO_ACCOUNTS}|{WHO_PERSON}\S{{1,200}})")


class AccessRule(BaseModel):
    """Une ligne d'accès aux outils d'un serveur (ADR 0131), telle qu'elle est rangée : qui, quand, ce qu'elle fait
    d'un outil qui lit et d'un outil qui agit, ce qu'elle en garde, et ses outils (vide : tous)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    who: str = Field(pattern=f"^{WHO.pattern}$")
    #: ses moments ; vide (ou tous) : toujours
    when: tuple[_Moment, ...] = ()
    read: _Policy = "non"
    act: _Policy = "non"
    keep: _Keep = "rien"
    tools: tuple[str, ...] = ()

    @field_validator("when", mode="before")
    @classmethod
    def _moments(cls, value: Any) -> Any:
        """Un seul moment écrit seul, « toujours », ou tous les moments : la même chose qu'une liste, ou que rien."""
        if isinstance(value, str):
            value = () if value == "toujours" else (value,)
        got = tuple(dict.fromkeys(value or ()))
        return () if {k for k, _ in MOMENTS} <= set(got) else got


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
    secret_headers: Annotated[str, Knob(
        label="En-têtes", group="Connexion", secret=True, order=15, only=_REMOTE,
        help="« Nom: valeur », un par ligne ou séparés par « ; » (comme Claude Code). Chiffrés, jamais réaffichés ; "
             "vide : inchangés.")] = ""
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
    in_hand: Annotated[bool, Knob(label="En main", group="Ses outils", order=36,
                                  help="Décoché (conseillé) : ses outils sont à la demande, elle les cherche par ce "
                                       "qu'ils font quand elle en a besoin.")] = False
    access: Annotated[tuple[AccessRule, ...], Knob(
        label="Accès à ses outils", group="Accès", order=37,
        help="Les lignes se lisent de haut en bas : pour un outil, la première qui le concerne (qui, quand, ses "
             "outils) décide ; aucune, c'est la ligne par défaut. Jamais dans un salon ni avec une inconnue.")] = ()
    default_read: Annotated[_Policy, Knob(label="Par défaut, un outil qui lit", group="Accès", choices=POLICIES,
                                          order=38)] = "non"
    default_act: Annotated[_Policy, Knob(label="Par défaut, un outil qui agit", group="Accès", choices=POLICIES,
                                         order=39)] = "non"
    default_keep: Annotated[_Keep, Knob(label="Par défaut, ce qu'elle en garde", group="Accès", choices=KEEPS,
                                        order=40)] = "rien"
    timeout_s: Annotated[float, Knob(label="Délai d'un appel", group="Bornes", lo=1, hi=300, unit="s",
                                     order=40)] = 30.0
    max_calls: Annotated[int, Knob(label="Appels par épisode (par outil)", group="Bornes", lo=1, hi=20,
                                   order=41)] = 3
    max_result_chars: Annotated[int, Knob(label="Réponse lue (caractères)", group="Bornes", lo=200, hi=20_000,
                                          order=42)] = 4000
    breaker: Annotated[int, Knob(label="Pannes d'affilée avant de le couper", group="Bornes", lo=1, hi=20,
                                 order=43)] = 3

    @model_validator(mode="before")
    @classmethod
    def _before_0131(cls, data: Any) -> Any:
        """Une fiche d'avant l'ADR 0131 reste lisible : ses réglages (avec qui, quand, ce qu'elle fait seule, ce
        qu'elle en garde) deviennent les lignes qui font la même chose ; la prochaine sauvegarde l'écrit sous la forme
        neuve. Les exceptions de ses outils, rangées à part, sont traduites par les réglages (``Settings.mcp``)."""
        if not isinstance(data, dict) or not set(LEGACY_KEYS) & set(data):
            return data
        return access_from_0128(data)

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
            out += [f"en-tête « {part.split(':')[0].strip()[:30]} » : Nom: valeur" for part in _header_lines(
                self.secret_headers) if not HEADER.fullmatch(part.partition(":")[0].strip()) or ":" not in part]
        return out

    @property
    def ready(self) -> bool:
        return not self.problems()

    def headers(self) -> dict[str, str]:
        """Les en-têtes de chaque requête : les siens (``secret_headers``), puis le jeton de son authentification."""
        out = {}
        for part in _header_lines(self.secret_headers):
            name, sep, value = part.partition(":")
            if sep and HEADER.fullmatch(name.strip()):
                out[name.strip()] = value.strip()
        if self.auth == "bearer" and self.token:
            out["Authorization"] = f"Bearer {self.token}"
        elif self.auth == "entete" and self.token:
            out[self.header] = self.token
        return out

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
        data = self.model_dump(include={"transport", "url", "auth", "token", "header", "secret_headers", "ca_file",
                                        "command", "args", "env", "secret_env", "network", "shared"})
        return hashlib.sha256(canonical_json(data).encode()).hexdigest()


# ── les réglages d'avant l'ADR 0131 ───────────────────────────────────────

#: ce qu'un service disait de lui avant l'ADR 0131 (et avant l'ADR 0128 : ``audience``, ``learns``)
LEGACY_KEYS = ("with_owner", "with_accounts", "with_people", "in_conversation", "in_initiative", "in_work", "autonomy",
               "keep", "audience", "learns")
#: un accord d'avant l'ADR 0131 : (ce qu'elle fait d'un outil qui lit, d'un outil qui agit)
_AUTONOMIES = {"seule": ("seule", "seule"), "lit": ("seule", "carte"), "carte": ("carte", "carte"),
               "toi": ("toi", "toi")}
#: l'accord d'un outil d'avant l'ADR 0128 : ce qu'il devient
LEGACY_APPROVALS = {"aucun": "seule", "conversation": "service", "operateur": "toi"}
#: ses lignes, du plus précis au plus large : une personne nommée passe avant les comptes (elle en a un)
_SPECIFIC = {WHO_ACCOUNTS: 1, WHO_OWNER: 2}


def _whens(episodes: list[str], owner: bool) -> list[str] | None:
    """Les moments d'une ligne : rien (toujours) quand elle vaut à tout moment où cette personne peut la voir (une
    personne ne la voit jamais travailler), sinon les siens ; ``None`` : aucun, pas de ligne."""
    every = {"conversation", "initiative", "travail"} if owner else {"conversation", "initiative"}
    got = [e for e in episodes if owner or e != "travail"]
    if not got:
        return None
    return [] if every <= set(got) else got


def access_from_0128(data: Mapping[str, Any], tools: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Les réglages d'un service d'avant l'ADR 0131 — avec qui, quand, ce qu'elle fait seule, ce qu'elle en garde, et
    les exceptions de ses outils (``tools`` : leurs décisions telles que rangées) — en lignes d'accès qui font la même
    chose : celles des outils qui s'écartent du service d'abord (une personne nommée avant les comptes, les comptes
    avant toi), puis celles du service. La ligne par défaut est fermée : avant, personne d'autre n'en avait."""
    data = dict(data)
    if data.pop("audience", None) == "comptes":
        data.setdefault("with_accounts", True)
    if data.pop("learns", False):
        data.setdefault("keep", "public")
    owner = bool(data.pop("with_owner", True))
    accounts = bool(data.pop("with_accounts", False))
    named = list(dict.fromkeys(str(p).strip() for p in data.pop("with_people", ()) or () if str(p).strip()))
    episodes = [e for e, on in (("conversation", data.pop("in_conversation", True)),
                                ("initiative", data.pop("in_initiative", False)),
                                ("travail", data.pop("in_work", False))) if on]
    autonomy = str(data.pop("autonomy", "carte"))
    keep = str(data.pop("keep", "prive"))
    read, act = _AUTONOMIES.get(autonomy, ("carte", "carte"))
    whos = ([WHO_OWNER] if owner else []) + [WHO_PERSON + p for p in named] + ([WHO_ACCOUNTS] if accounts else [])
    service = [{"who": w, "when": when, "read": read, "act": act, "keep": keep, "tools": []}
               for w in whos if (when := _whens(episodes, w == WHO_OWNER)) is not None]
    rows: list[dict[str, Any]] = []
    for remote, raw in sorted((tools or {}).items()):
        rows += [{**r, "tools": [remote]} for r in _tool_rows(raw, owner, accounts, named, episodes, autonomy, keep)]
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in sorted(rows, key=lambda r: _SPECIFIC.get(r["who"], 0)):
        key = (r["who"], tuple(r["when"]), r["read"], r["act"], r["keep"])
        if key in merged:
            merged[key]["tools"] += r["tools"]
        else:
            merged[key] = r
    data["access"] = [*merged.values(), *service]
    data.update(default_read="non", default_act="non", default_keep="rien")
    return data


def _tool_rows(raw: Mapping[str, Any], owner: bool, accounts: bool, named: list[str], episodes: list[str],
               autonomy: str, keep: str) -> list[dict[str, Any]]:
    """Les lignes d'un outil qui s'écarte de son service (son accord, ce qu'elle en garde, ses exceptions par
    situation et par personne) ; aucune s'il fait comme lui. Un outil coupé n'en a pas : rien ne lui sert."""
    raw = dict(raw)
    if not raw.get("enabled"):
        return []
    nature = "lecture" if raw.get("nature", "lecture") == "lecture" else "action"
    own = str(raw.get("autonomy") or LEGACY_APPROVALS.get(str(raw.get("approval") or ""), "service"))
    service = _AUTONOMIES.get(autonomy, ("carte", "carte"))[0 if nature == "lecture" else 1]
    base = service if own == "service" else own
    kept = keep if raw.get("keep", "service") == "service" else str(raw["keep"])
    situations = dict(raw.get("situations") or {})
    people = dict(raw.get("people") or {})
    talks = [e for e in episodes if e != "travail"]
    compte = situations.get("compte") or base
    out: list[dict[str, Any]] = []

    def add(who: str, whens: list[str] | None, level: str, below: tuple[str, str] = (service, keep)) -> None:
        """Une ligne, sauf si celle qui la suivrait pour cette personne fait déjà la même chose (``below``)."""
        if whens is not None and (level, kept) != below:
            out.append({"who": who, "when": whens, "read": level, "act": level, "keep": kept})

    # une personne nommée de l'outil a sa ligne au-dessus de celle des comptes de l'outil, qui la suivrait sinon :
    # « comme le service » pour elle ne l'est plus quand l'outil règle les comptes autrement (2026-10-25)
    after_person = (compte, kept) if accounts else (service, keep)
    for person, level in people.items():
        if accounts or person in named:
            add(WHO_PERSON + person, _whens(talks, False), level, after_person)
    if accounts:
        add(WHO_ACCOUNTS, _whens(talks, False), compte)
    for person in named:
        if person not in people:
            add(WHO_PERSON + person, _whens(talks, False), compte)
    if owner:
        mine = situations.get("proprietaire") or base
        work = situations.get("travail") or base
        if "travail" in episodes and mine == work:
            add(WHO_OWNER, _whens(episodes, True), mine)
        else:
            add(WHO_OWNER, talks or None, mine)
            if "travail" in episodes:
                add(WHO_OWNER, ["travail"], work)
    return out


def _header_lines(raw: str) -> list[str]:
    """Les en-têtes écrits « Nom: valeur », un par ligne ou séparés par « ; »."""
    return [p.strip() for p in re.split(r"[;\n]", raw or "") if p.strip()]


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
        label="Serveurs", advanced=False, order=10, key_pattern=SERVER_NAME, key_rule=SERVER_NAME_RULE,
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
    #: (son accord, ce qu'elle en gardait et ses exceptions d'avant l'ADR 0131, encore rangés, sont devenus des lignes
    #: d'accès de son serveur : ignorés ici)
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
