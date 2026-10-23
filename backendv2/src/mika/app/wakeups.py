"""Les réveils par API (ADR 0068), côté application : ce que l'opérateur déclare, leurs clés, la porte.

- *Ce que l'opérateur déclare* (Réglages › Plugins › Réveils par API) : un modèle de réglages, un enregistrement
  par réveil ; le nom est la fin de son URL (``POST /api/wake/<nom>``), il ne change plus une fois créé.
- *Les clés* : générées ici (``mwk_…``), montrées une seule fois ; seule leur empreinte est gardée (``Settings``).
- *Le guichet* (le port ``wakeup``) : ce que la console lit et fait (une clé neuve, la retirer).
- *La porte* (``call``) : ce que le transport web appelle. Elle vérifie la clé, ou la signature du corps par cette
  clé (en temps constant ; un réveil inconnu et une mauvaise clé se répondent pareil), l'état du réveil, le texte et
  ses plafonds — **avant** de journaliser quoi que ce soit — puis journalise l'appel, avec le réglage du réveil figé
  à cet instant.
- *Le texte* (``call_text``) : ``{"text": "…"}`` comme avant, un ``context`` à côté, ou le JSON d'un service tel quel
  (GitHub, Home Assistant…), mis en lignes ``chemin: valeur`` — ses champs gardés seulement, s'il en a (ADR 0117).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import itertools
import json
import re
import secrets
import time
from collections import deque
from collections.abc import Iterable, Iterator, Sequence
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mika.contracts import projects as projects_c
from mika.contracts import wakeup as wakeup_c
from mika.kernel.clock import DAY, HOUR
from mika.kernel.forms import Knob
from mika.ports.wakeup import (
    ACCEPTED,
    BUSY,
    DISABLED,
    IGNORED,
    INVALID,
    KEY_PREFIX,
    REFUSED,
    UNKNOWN,
    Endpoint,
    KeyState,
    WakeRequest,
    WakeResult,
)

#: le nom d'un réveil : la fin de son URL
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
NAME_RULE = "minuscules, chiffres et tirets (40 au plus), en commençant par une lettre ou un chiffre"
#: le projet d'un réveil qui n'en a pas
NO_PROJECT = "aucun"
#: les lots qu'un réveil peut avoir (plus ceux des serveurs extérieurs, ``mcp.<serveur>``)
TOOLS = ("memory", "email", "rss", "camera", "forge", "forge_apps", "goals")
#: …ceux qu'un réveil sur un projet ne peut pas avoir : planter un rappel, ouvrir une exploration se font dans un
#: épisode de réveil, pas dans une exécution de projet (ADR 0117)
NOT_ON_A_PROJECT = ("goals",)
#: le texte d'un appel, au plus (ce qu'une citation garde)
MAX_CHARS = 4000
#: les champs gardés d'un corps de service, au plus (et la longueur d'un chemin)
FIELDS_MAX, FIELD_CHARS = 30, 200
#: un corps de service se lit jusqu'à cette profondeur (ce qu'il y a dessous est laissé)
DEPTH = 16
#: les évènements qui ne demandent rien (GitHub vérifie un webhook neuf par un « ping ») : admis, rien de journalisé
PINGS = frozenset({"ping"})
#: la ligne de tête de ce qu'apporte le corps d'un service : l'évènement qu'il annonce
EVENT_LINE = "event: {event}"
#: comment un appel est admis : la clé présentée, ou le corps signé par elle
KEY, SIGNATURE = "cle", "signature"
#: une clé d'idempotence, au plus
IDEMPOTENCY_MAX = 100
#: l'empreinte qu'on compare quand il n'y a rien à comparer (un réveil inconnu) : le même temps de calcul
_NOTHING = hashlib.sha256(b"").hexdigest()


class WakeEndpoint(BaseModel):
    """Un réveil : ce qu'il lui fait faire, quand, à qui il rend compte, ses bornes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: Annotated[str, Knob(
        label="À quoi il sert", group="Ce qu'il lui fait faire", advanced=False, order=1,
        help="Une ligne : ce que ce réveil lui apporte (« l'alerte de la sonde du jardin »). Elle la lit à chaque "
             "appel.")] = Field("", max_length=300)
    enabled: Annotated[bool, Knob(label="Actif", group="Ce qu'il lui fait faire", advanced=False, order=2,
                                  help="Décoché : ses appels sont refusés (403).")] = True
    instructions: Annotated[str, Knob(
        label="Consignes", widget="textarea", group="Ce qu'il lui fait faire", advanced=False, order=3,
        help="Ce qu'elle doit faire de chaque appel. Elles priment sur le texte que l'appel apporte, qui n'est jamais "
             "une consigne (il est cité). Vide : elle fait ce que l'appel demande, si c'est raisonnable.")] = \
        Field("", max_length=4000)
    project: Annotated[str, Knob(
        label="Projet", group="Ce qu'il lui fait faire", advanced=False, order=4,
        help="Aucun : un travail à part, avec les seuls outils du réveil. Un projet : une exécution de ce projet "
             "(son atelier, ses consignes, ses outils de base), qui compte dans ses plafonds ; un projet en pause "
             "ou archivé refuse les appels (409).")] = NO_PROJECT
    plain: Annotated[bool, Knob(
        label="Impersonnel", group="Ce qu'il lui fait faire", advanced=False, order=5,
        help="Sans persona, sans humeur, sans avis : un traitement factuel, comme l'exécution impersonnelle d'un "
             "projet. Décoché : elle s'en occupe dans son mode à elle.")] = False
    tools: Annotated[tuple[str, ...], Knob(
        label="Outils", group="Ce qu'il lui fait faire", advanced=False, order=6,
        help="Un lot par ligne : memory (sa mémoire), email, rss, camera, forge, forge_apps, goals (planter un "
             "rappel, ouvrir une exploration à reprendre plus tard ; sans projet seulement), mcp.<serveur>. Vide : "
             "aucun outil, seulement de quoi conclure. Le texte d'un appel vient d'ailleurs et le réveil a les droits "
             "de sa propriétaire : ne donne que ce qu'il faut.")] = ()
    fields: Annotated[tuple[str, ...], Knob(
        label="Champs gardés", group="Ce qu'il lui fait faire", advanced=False, order=7,
        help="Pour un service qui envoie son propre JSON (GitHub, Home Assistant…) au lieu de {\"text\": \"…\"} : un "
             "chemin par ligne (issue.title, repository.full_name, commits.*.message — * pour chaque élément). Vide : "
             "tout le corps, en lignes « chemin: valeur », coupé à la longueur du texte.")] = ()
    rouse: Annotated[bool, Knob(
        label="Ignorer son rythme", group="Quand et pour qui", advanced=False, order=10,
        help="Coché : un appel la réveille vraiment, comme le message d'une proche (elle se rendort ensuite au "
             "calme), et part aussitôt. Décoché : la nuit, il attend son réveil.")] = False
    notify: Annotated[str, Knob(
        label="Rendre compte à", group="Quand et pour qui", advanced=False, order=11,
        help="À qui elle dit ce que l'appel a donné, par une initiative (là où la personne est, sinon où on peut lui "
             "écrire absente). Personne : le compte rendu reste dans la console. C'est aussi pour cette personne "
             "qu'elle plante un rappel (lot goals).")] = wakeup_c.OWNERS
    signed: Annotated[bool, Knob(
        label="Signé (GitHub, Gitea, Forgejo)", group="Quand et pour qui", advanced=False, order=12,
        help="Coché : l'appelant peut aussi signer le corps avec la clé (HMAC-SHA256, en-tête X-Hub-Signature-256) au "
             "lieu de la présenter — c'est ce que font GitHub, Gitea et Forgejo avec le « secret » d'un webhook. La "
             "clé est alors gardée chiffrée, pour vérifier la signature : génère-la après avoir coché.")] = False
    per_hour: Annotated[int, Knob(label="Appels par heure", group="Bornes", lo=1, hi=600, order=20,
                                  help="Au-delà, les appels sont refusés (429) jusqu'à ce que l'heure glisse.")] = 30
    max_pending: Annotated[int, Knob(label="Appels en attente", group="Bornes", lo=1, hi=50, order=21,
                                     help="Les appels pas encore traités ; au-delà, refusés (429).")] = 5
    lifetime_us: Annotated[int, Knob(
        label="Durée de vie d'un appel", group="Bornes", lo=HOUR, hi=7 * DAY, order=22,
        help="Un appel resté en attente au-delà (elle dort, son projet est occupé) n'est plus traité.")] = DAY
    max_chars: Annotated[int, Knob(label="Longueur du texte (caractères)", group="Bornes", lo=100, hi=MAX_CHARS,
                                   order=23, help="Au-delà, l'appel est refusé (400).")] = MAX_CHARS

    @field_validator("label", "instructions")
    @classmethod
    def _strip(cls, text: str) -> str:
        return text.strip()

    @field_validator("tools")
    @classmethod
    def _tools(cls, tools: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(t.strip() for t in tools if t.strip()))

    @field_validator("fields")
    @classmethod
    def _fields(cls, fields: tuple[str, ...]) -> tuple[str, ...]:
        kept = tuple(dict.fromkeys(f.strip().strip(".") for f in fields if f.strip().strip(".")))
        if len(kept) > FIELDS_MAX:
            raise ValueError(f"{FIELDS_MAX} champs gardés au plus")
        bad = next((f for f in kept if len(f) > FIELD_CHARS or any(ch.isspace() for ch in f) or ".." in f), None)
        if bad is not None:
            raise ValueError(f"champ gardé illisible : « {bad[:60]} » (des noms séparés par des points, sans espace)")
        return kept

    @field_validator("project")
    @classmethod
    def _project(cls, project: str) -> str:
        project = project.strip() or NO_PROJECT
        if project != NO_PROJECT and not project.isdigit():
            raise ValueError("un numéro de projet, ou « aucun »")
        return project

    @model_validator(mode="after")
    def _said(self) -> WakeEndpoint:
        if not self.label:
            raise ValueError("dis à quoi sert ce réveil (une ligne) : elle le lit à chaque appel")
        return self

    @model_validator(mode="after")
    def _on_a_project(self) -> WakeEndpoint:
        bad = [t for t in self.tools if t in NOT_ON_A_PROJECT]
        if bad and self.project != NO_PROJECT:
            raise ValueError(f"{', '.join(bad)} : seulement pour un réveil sans projet")
        return self

    @property
    def project_id(self) -> int:
        return int(self.project) if self.project.isdigit() else 0


class WakeupConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoints: Annotated[dict[str, WakeEndpoint], Knob(
        label="Réveils", advanced=False, order=10,
        help=f"Chaque réveil a sa page. Son nom ({NAME_RULE}) est la fin de son URL : POST /api/wake/<nom>. Sa clé "
             "se génère sur sa fiche (Connexions extérieures › Réveils par API).")] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _names(self) -> WakeupConfig:
        bad = [k for k in self.endpoints if not NAME.fullmatch(k)]
        if bad:
            raise ValueError(f"nom de réveil invalide : « {bad[0][:40]} » ({NAME_RULE})")
        return self


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def signature_of(key: str, body: bytes) -> str:
    """La signature d'un corps par une clé : HMAC-SHA256, en hexadécimal (celle de GitHub, Gitea, Forgejo)."""
    return hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


# ── Le texte d'un appel ───────────────────────────────────────────────────


def _path(prefix: str, key: Any) -> str:
    return f"{prefix}.{key}" if prefix else str(key)


def flatten(value: Any, prefix: str = "", depth: int = 0) -> Iterator[str]:
    """Un JSON en lignes ``chemin: valeur``, dans l'ordre où il est écrit ; les valeurs vides sont sautées, et ce qui
    est plus profond que ``DEPTH`` est laissé."""
    if depth > DEPTH:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            yield from flatten(v, _path(prefix, k), depth + 1)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from flatten(v, _path(prefix, i), depth + 1)
    elif value is not None and value != "":
        shown = value if isinstance(value, str) else json.dumps(value)
        yield f"{prefix}: {shown}" if prefix else shown


def pick(value: Any, parts: Sequence[str], prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Ce qu'un chemin désigne dans un JSON (``issue.title`` ; ``commits.*.message`` : chaque élément ;
    ``commits.0.message`` : le premier) : des paires (son chemin, sa valeur). Un chemin absent ne donne rien."""
    if not parts:
        yield prefix, value
        return
    head, rest = parts[0], parts[1:]
    if head == "*":
        items: Iterable[tuple[Any, Any]] = value.items() if isinstance(value, dict) else \
            enumerate(value) if isinstance(value, list) else ()
        for k, v in items:
            yield from pick(v, rest, _path(prefix, k))
    elif isinstance(value, dict) and head in value:
        yield from pick(value[head], rest, _path(prefix, head))
    elif isinstance(value, list) and head.isdigit() and int(head) < len(value):
        yield from pick(value[int(head)], rest, _path(prefix, head))


def clip(lines: Iterable[str], limit: int) -> str:
    """Des lignes, jusqu'à ``limit`` caractères ; au-delà, coupées (« … ») — un service ne choisit pas la taille de
    son corps, et on ne lit que ce qu'il faut."""
    out: list[str] = []
    size = 0
    for line in lines:
        size += len(line) + (1 if out else 0)
        out.append(line)
        if size > limit:
            return "\n".join(out)[: max(0, limit - 1)].rstrip() + "…"
    return "\n".join(out)


def call_text(data: Any, ep: WakeEndpoint, event: str = "") -> str:
    """Ce que l'appel apporte, en texte — vide s'il n'apporte rien qui se lise, ou si son ``text`` dépasse la longueur
    admise (l'appelant l'a écrit : à lui de le raccourcir).

    - ``{"text": "…"}`` : le texte ; un ``context`` à côté (un objet, une liste, une phrase) suit, en lignes
      ``chemin: valeur``, coupé à ce qui reste de place ;
    - tout autre objet (le JSON d'un service) : ses champs gardés (tout le corps s'il n'y en a pas), en lignes,
      l'évènement que le service annonce en tête, coupé à la longueur admise."""
    limit = ep.max_chars
    if isinstance(data, dict) and isinstance(data.get("text"), str):
        text = data["text"].strip()
        if not text or len(text) > limit:
            return ""
        room = limit - len(text) - 2
        context = clip(flatten(data.get("context")), room) if room > 0 else ""
        return f"{text}\n\n{context}" if context else text
    if not isinstance(data, dict | list):
        return ""
    lines: Iterator[str] = (line for f in ep.fields for path, v in pick(data, f.split(".")) for line in flatten(v, path)) \
        if ep.fields else flatten(data)
    first = next(lines, None)
    if first is None:
        return ""
    head = [EVENT_LINE.format(event=event)] if event else []
    return clip(itertools.chain(head, [first], lines), limit)


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


class WakeupDesk:
    """Le guichet (le port ``wakeup``) et la porte des réveils. ``port`` (le ``KernelPort``) est relié après la
    construction du noyau, qui reçoit ce guichet parmi ses ports."""

    def __init__(self, settings: Any, clock: Any) -> None:
        self.settings = settings
        self.clock = clock
        self.port: Any = None
        #: ce qu'on ouvre quand il n'y a pas de clé chiffrée (un réveil inconnu, ou qui ne signe pas) : le même chemin
        self._nothing = settings.box.seal(_NOTHING)
        #: les appels acceptés de l'heure, par réveil (en mémoire : un redémarrage les oublie)
        self._hour: dict[str, deque[float]] = {}
        #: les plafonds se vérifient et l'appel se journalise d'un tenant : deux appels simultanés ne passent pas
        #: tous les deux sous un plafond qui n'en admet qu'un
        self._lock = asyncio.Lock()

    # ── le guichet ──
    def _endpoint(self, name: str, ep: WakeEndpoint, keys: dict[str, dict[str, Any]]) -> Endpoint:
        k = keys.get(name)
        key = KeyState(str(k.get("hint") or ""), int(k.get("created_at") or 0), str(k.get("by") or ""),
                       signs=bool(k.get("sealed"))) if k and k.get("digest") else None
        return Endpoint(name=name, label=ep.label, enabled=ep.enabled, project=ep.project_id, plain=ep.plain,
                        bundles=ep.tools, instructions=ep.instructions, rouse=ep.rouse, notify=ep.notify,
                        per_hour=ep.per_hour, max_pending=ep.max_pending, lifetime_us=ep.lifetime_us,
                        max_chars=ep.max_chars, key=key, signed=ep.signed, fields=ep.fields)

    def endpoints(self) -> list[Endpoint]:
        keys = self.settings.wakeup_keys()
        return [self._endpoint(n, ep, keys) for n, ep in sorted(self.settings.wakeup().endpoints.items())]

    def endpoint(self, name: str) -> Endpoint | None:
        ep = self.settings.wakeup().endpoints.get(name)
        return self._endpoint(name, ep, self.settings.wakeup_keys()) if ep is not None else None

    async def new_key(self, name: str, by: str) -> str:
        ep = self.settings.wakeup().endpoints.get(name)
        if ep is None:
            raise ValueError("Réveil inconnu : déclare-le d'abord dans Réglages › Plugins › Réveils par API.")
        key = new_key()
        # un réveil signé garde aussi sa clé chiffrée : il faut la relire pour vérifier une signature
        sealed = self.settings.box.seal(key) if ep.signed else ""
        await self.settings.save_wakeup_key(name, digest(key), key[:len(KEY_PREFIX) + 4], self.clock(), by,
                                            sealed=sealed)
        return key

    async def revoke_key(self, name: str, by: str) -> bool:
        return await self.settings.revoke_wakeup_key(name)

    # ── la porte ──
    def _recent(self, name: str, now: float) -> deque[float]:
        window = self._hour.setdefault(name, deque())
        while window and now - window[0] >= 3600:
            window.popleft()
        return window

    async def call(self, req: WakeRequest) -> WakeResult:
        async with self._lock:
            return await self._call(req)

    def _admits(self, req: WakeRequest, ep: WakeEndpoint | None, stored: dict[str, Any]) -> str:
        """Comment l'appel est admis : par la clé présentée (``KEY``), par la signature du corps par cette clé (un
        réveil signé, ``SIGNATURE``), sinon pas (``""``). Les deux se vérifient toujours, du même coût : rien ne dit
        si le nom existe, ni s'il signe."""
        wanted = str(stored.get("digest") or "") if ep is not None else ""
        given = digest(req.key) if req.key.startswith(KEY_PREFIX) and len(req.key) <= 200 else _NOTHING
        by_key = hmac.compare_digest(given, wanted or _NOTHING) and bool(wanted)
        sealed = str(stored.get("sealed") or "") if ep is not None and ep.signed else ""
        # une copie qui ne s'ouvre plus (``secret.key`` changée) rend « » : jamais une signature par une clé vide
        secret = self.settings.box.open(sealed or self._nothing)
        expected = signature_of(secret or _NOTHING, req.body)
        signature = req.signature.strip().lower().removeprefix("sha256=")
        by_signature = hmac.compare_digest(expected.encode(), signature.encode()) and bool(sealed) \
            and secret.startswith(KEY_PREFIX) and bool(signature)
        if ep is None:
            return ""
        return KEY if by_key else SIGNATURE if by_signature else ""

    async def _call(self, req: WakeRequest) -> WakeResult:
        name = req.name
        cfg = self.settings.wakeup()
        ep = cfg.endpoints.get(name)
        keys = self.settings.wakeup_keys()  # lues dans tous les cas : le même chemin, que le nom existe ou non
        how = self._admits(req, ep, keys.get(name, {}))
        if not how or ep is None:
            return WakeResult(UNKNOWN, "Réveil inconnu ou clé refusée.")
        if not ep.enabled:
            return WakeResult(DISABLED, "Ce réveil est désactivé.")
        if req.event.strip().lower() in PINGS:
            return WakeResult(IGNORED, "Rien à faire : c'est un « ping ».")
        text = call_text(req.data, ep, req.event.strip())
        if not text:
            return WakeResult(INVALID, f"Un texte (le champ « text »), ou un objet JSON qui apporte quelque chose ; "
                                       f"un « text » de {ep.max_chars} caractères au plus.")
        if self.port is None:
            return WakeResult(REFUSED, "Elle n'est pas prête à recevoir des réveils.")
        # signé, seul le corps est garanti (ni l'en-tête de la livraison, ni l'heure) : son empreinte est la clé
        # d'idempotence — une livraison rejouée, même sous un autre identifiant, rend le même appel
        idempotency = f"corps:{hashlib.sha256(req.body).hexdigest()[:40]}" if how == SIGNATURE else \
            req.idempotency[:IDEMPOTENCY_MAX]
        seen = self.port.wake_seen(name, idempotency)
        if seen is not None:  # un rejeu (le client n'a pas su que c'était reçu) : le même appel, hors plafonds
            return WakeResult(ACCEPTED, "Déjà reçu.", call=seen)
        now = time.monotonic()
        self._hour = {n: w for n, w in self._hour.items() if n in cfg.endpoints}  # les réveils retirés s'oublient
        window = self._recent(name, now)
        if len(window) >= ep.per_hour:
            return WakeResult(BUSY, f"Trop d'appels : {ep.per_hour} par heure au plus.",
                              retry_after=max(1, int(3600 - (now - window[0]))))
        frame = self.port.kernel.mind.frame()
        if frame.get(wakeup_c.PENDING(name)) >= ep.max_pending:
            return WakeResult(BUSY, f"Trop d'appels en attente : {ep.max_pending} au plus.", retry_after=60)
        if ep.project_id and frame.get(projects_c.STATUS(ep.project_id)) != projects_c.ACTIVE:
            return WakeResult(REFUSED, "Le projet de ce réveil n'est pas actif.")
        seq = await self.port.wake(name, label=ep.label, text=text, instructions=ep.instructions, plain=ep.plain,
                                   project=ep.project_id, bundles=ep.tools, rouse=ep.rouse, notify=ep.notify,
                                   lifetime_us=ep.lifetime_us, idempotency=idempotency)
        if seq is None:
            return WakeResult(REFUSED, "L'appel n'a pas pu être journalisé.")
        window.append(now)
        return WakeResult(ACCEPTED, "Reçu.", call=seq)
