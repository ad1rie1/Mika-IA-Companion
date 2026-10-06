"""Les réveils par API (ADR 0068), côté application : ce que l'opérateur déclare, leurs clés, la porte.

- *Ce que l'opérateur déclare* (Configuration › Plugins › Réveils par API) : un modèle de réglages, un enregistrement
  par réveil ; le nom est la fin de son URL (``POST /api/wake/<nom>``), il ne change plus une fois créé.
- *Les clés* : générées ici (``mwk_…``), montrées une seule fois ; seule leur empreinte est gardée (``Settings``).
- *Le guichet* (le port ``wakeup``) : ce que la console lit et fait (une clé neuve, la retirer).
- *La porte* (``call``) : ce que le transport web appelle. Elle vérifie la clé (en temps constant ; un réveil inconnu
  et une mauvaise clé se répondent pareil), l'état du réveil, le texte et ses plafonds — **avant** de journaliser
  quoi que ce soit — puis journalise l'appel, avec le réglage du réveil figé à cet instant.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
import time
from collections import deque
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
    INVALID,
    KEY_PREFIX,
    REFUSED,
    UNKNOWN,
    Endpoint,
    KeyState,
    WakeResult,
)

#: le nom d'un réveil : la fin de son URL
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
NAME_RULE = "minuscules, chiffres et tirets (40 au plus), en commençant par une lettre ou un chiffre"
#: le projet d'un réveil qui n'en a pas
NO_PROJECT = "aucun"
#: les lots qu'un réveil peut avoir (plus ceux des serveurs extérieurs, ``mcp.<serveur>``)
TOOLS = ("memory", "email", "rss", "camera", "forge", "forge_apps")
#: le texte d'un appel, au plus (ce qu'une citation garde)
MAX_CHARS = 4000
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
        help="Un lot par ligne : memory (sa mémoire), email, rss, camera, forge, forge_apps, mcp.<serveur>. Vide : "
             "aucun outil, seulement de quoi conclure. Le texte d'un appel vient d'ailleurs et le réveil a les droits "
             "de sa propriétaire : ne donne que ce qu'il faut.")] = ()
    rouse: Annotated[bool, Knob(
        label="Ignorer son rythme", group="Quand et pour qui", advanced=False, order=10,
        help="Coché : un appel la réveille vraiment, comme le message d'une proche (elle se rendort ensuite au "
             "calme), et part aussitôt. Décoché : la nuit, il attend son réveil.")] = False
    notify: Annotated[str, Knob(
        label="Rendre compte à", group="Quand et pour qui", advanced=False, order=11,
        help="À qui elle dit ce que l'appel a donné, par une initiative (là où la personne est, sinon où on peut lui "
             "écrire absente). Personne : le compte rendu reste dans la console.")] = wakeup_c.OWNERS
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

    @property
    def project_id(self) -> int:
        return int(self.project) if self.project.isdigit() else 0


class WakeupConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoints: Annotated[dict[str, WakeEndpoint], Knob(
        label="Réveils", advanced=False, order=10,
        help=f"Chaque réveil a sa page. Son nom ({NAME_RULE}) est la fin de son URL : POST /api/wake/<nom>. Sa clé "
             "se génère sur sa fiche (Ses canaux › Réveils par API).")] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _names(self) -> WakeupConfig:
        bad = [k for k in self.endpoints if not NAME.fullmatch(k)]
        if bad:
            raise ValueError(f"nom de réveil invalide : « {bad[0][:40]} » ({NAME_RULE})")
        return self


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


class WakeupDesk:
    """Le guichet (le port ``wakeup``) et la porte des réveils. ``port`` (le ``KernelPort``) est relié après la
    construction du noyau, qui reçoit ce guichet parmi ses ports."""

    def __init__(self, settings: Any, clock: Any) -> None:
        self.settings = settings
        self.clock = clock
        self.port: Any = None
        #: les appels acceptés de l'heure, par réveil (en mémoire : un redémarrage les oublie)
        self._hour: dict[str, deque[float]] = {}
        #: les plafonds se vérifient et l'appel se journalise d'un tenant : deux appels simultanés ne passent pas
        #: tous les deux sous un plafond qui n'en admet qu'un
        self._lock = asyncio.Lock()

    # ── le guichet ──
    def _endpoint(self, name: str, ep: WakeEndpoint, keys: dict[str, dict[str, Any]]) -> Endpoint:
        k = keys.get(name)
        key = KeyState(str(k.get("hint") or ""), int(k.get("created_at") or 0), str(k.get("by") or "")) \
            if k and k.get("digest") else None
        return Endpoint(name=name, label=ep.label, enabled=ep.enabled, project=ep.project_id, plain=ep.plain,
                        bundles=ep.tools, instructions=ep.instructions, rouse=ep.rouse, notify=ep.notify,
                        per_hour=ep.per_hour, max_pending=ep.max_pending, lifetime_us=ep.lifetime_us,
                        max_chars=ep.max_chars, key=key)

    def endpoints(self) -> list[Endpoint]:
        keys = self.settings.wakeup_keys()
        return [self._endpoint(n, ep, keys) for n, ep in sorted(self.settings.wakeup().endpoints.items())]

    def endpoint(self, name: str) -> Endpoint | None:
        ep = self.settings.wakeup().endpoints.get(name)
        return self._endpoint(name, ep, self.settings.wakeup_keys()) if ep is not None else None

    async def new_key(self, name: str, by: str) -> str:
        if name not in self.settings.wakeup().endpoints:
            raise ValueError("Réveil inconnu : déclare-le d'abord dans Configuration.")
        key = new_key()
        await self.settings.save_wakeup_key(name, digest(key), key[:len(KEY_PREFIX) + 4], self.clock(), by)
        return key

    async def revoke_key(self, name: str, by: str) -> bool:
        return await self.settings.revoke_wakeup_key(name)

    # ── la porte ──
    def _recent(self, name: str, now: float) -> deque[float]:
        window = self._hour.setdefault(name, deque())
        while window and now - window[0] >= 3600:
            window.popleft()
        return window

    async def call(self, name: str, key: str, text: str, idempotency: str = "") -> WakeResult:
        async with self._lock:
            return await self._call(name, key, text, idempotency)

    async def _call(self, name: str, key: str, text: str, idempotency: str) -> WakeResult:
        cfg = self.settings.wakeup()
        ep = cfg.endpoints.get(name)
        keys = self.settings.wakeup_keys()  # lues dans tous les cas : le même chemin, que le nom existe ou non
        stored = str(keys.get(name, {}).get("digest") or "") if ep is not None else ""
        given = digest(key) if key.startswith(KEY_PREFIX) and len(key) <= 200 else _NOTHING
        # toujours une comparaison, du même coût : rien ne dit si le nom existe
        if not hmac.compare_digest(given, stored or _NOTHING) or not stored or ep is None:
            return WakeResult(UNKNOWN, "Réveil inconnu ou clé refusée.")
        if not ep.enabled:
            return WakeResult(DISABLED, "Ce réveil est désactivé.")
        text = text.strip()
        if not text or len(text) > ep.max_chars:
            return WakeResult(INVALID, f"Un texte, de {ep.max_chars} caractères au plus.")
        if self.port is None:
            return WakeResult(REFUSED, "Elle n'est pas prête à recevoir des réveils.")
        idempotency = idempotency[:IDEMPOTENCY_MAX]
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
