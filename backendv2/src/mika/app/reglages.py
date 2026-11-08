"""Les réglages d'exploitation, déclarés : ce qu'un opérateur décide, et où.

Chaque section apporte un modèle (le formulaire en sort), sa valeur actuelle
et de quoi l'enregistrer ; la console les rend toutes de la même façon
(``inspector/pages/settings_form.py``). Un enregistrement qui échoue au
rechargement est défait : on ne laisse pas une configuration à moitié prise.

Les réglages d'un plugin vivent là où l'on s'en sert, derrière la roue de sa
destination (``SettingsPage.home``, ADR 0173, 0206) : Courrier, Teams, Réveils
par API › Paramètres, Ses outils › Paramètres des services, et dans Ses sens les
flux suivis, l'accès des appareils, la transcription ; ils s'enregistrent
toujours sous Réglages. « Configuration des plugins » en est la vue d'ensemble.
"""

from __future__ import annotations

import logging
import re
import zoneinfo
from functools import cache
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from mika.adapters.imaging.config import ImagingConfig
from mika.adapters.imaging.models import ListingFailed as ImageListingFailed
from mika.adapters.imaging.models import list_image_models
from mika.adapters.llm.config import KIND_LABELS, REPLY, ROLE_LABELS, BackendSpec, LLMConfig, tokens_fr
from mika.adapters.llm.models import ListingFailed, list_models, settle_limits
from mika.adapters.mail import MailConfig
from mika.adapters.mail.config import MailAccount
from mika.adapters.maps import MapConfig, PlacesConfig, RoutingConfig
from mika.adapters.mcp.config import McpConfig
from mika.adapters.push import parse_service_account
from mika.adapters.teams import TeamsConfig
from mika.app import authors as authors_m
from mika.app import persona as persona_file
from mika.app.console import FACULTY_LABELS, NAVIGATION
from mika.app.handmade import ago
from mika.app.handmade import authors as drawn_authors
from mika.app.handmade import temperament as temper
from mika.app.handmade.tabs import settings as drawn_settings
from mika.app.settings import PUSH_KEY_FILE, push_key_file
from mika.app.wakeups import NO_PROJECT, TOOLS, WakeupConfig
from mika.contracts import identity as identity_c
from mika.contracts import projects as projects_c
from mika.contracts import self_ as self_c
from mika.contracts import wakeup as wakeup_c
from mika.contracts.self_ import PersonaDoc
from mika.inspector.catalog import Command, SettingsPage, SettingsSection, SettingsTab
from mika.inspector.formview import decimal_fr
from mika.inspector.pages.reglages import effect, faculty_url
from mika.inspector.pages.settings_form import RECORD_KEY
from mika.inspector.ui import PREFIX
from mika.kernel import forms
from mika.kernel.clock import DAY
from mika.kernel.forms import Knob
from mika.kernel.inspect import Column, Disclosure, Note, Ref, Row, Table, Text, When
from mika.plugins.email.console.common import VOICE_LABEL
from mika.ports.imaging import DRAW
from mika.runtime.params import Parameters
from mika.vocab.access import PERSON, SELF
from mika.vocab.episodes import FALLBACKS, VOICE_ROLES, Role
from mika.vocab.temperament import (
    Temperament,
)

if TYPE_CHECKING:
    from mika.app.server import Live

log = logging.getLogger("mika.reglages")

#: les rubriques de l'annuaire des réglages, dans l'ordre ; chacune porte le nom de ce qu'elle contient (ADR 0197) :
#: « Canaux » ne nomme que les tableaux de droits par canal (ADR 0134), et Dépôts Git, joint par Connexions extérieures,
#: s'y range sous ce nom. Leurs clés ne sont pas des adresses : les anciennes (« canaux », « sens ») restent des
#: adresses d'enregistrement dans ``inspector/pages/routes.py`` (LEGACY_POSTS)
TABS = (SettingsTab("intelligence", "Intelligence"), SettingsTab("personnage", "Personnage"),
        SettingsTab("carte-telephone", "Carte et téléphone"), SettingsTab("plugins", "Plugins"),
        SettingsTab("connexions", "Connexions extérieures"))

#: la famille de chaque rôle (la page « Qui sert quoi »)
ROLE_FAMILIES = {**{str(r): "voix" for r in VOICE_ROLES}, "extract": "mémoire", "validate": "mémoire",
                 "compact": "mémoire", "profile": "compréhension", "interpret": "compréhension",
                 "triage": "sens", "caption": "sens", "plan": "travail", "job": "travail", "polish": "voix",
                 "character": "voix"}

#: Réglages › Configuration des plugins : une ligne par paquet de ``plugins/`` (``test_settings_pages`` les compare,
#: pour qu'aucun ne manque), dans l'ordre de la page — ce qui s'y règle, ses pages de réglages, où s'en servir (nom,
#: « destination/onglet »). Une ligne n'est montrée que si son plugin est composé ; ses paramètres avancés, que si sa
#: faculté en a.
PLUGINS: dict[str, tuple[str, tuple[str, ...], tuple[str, str] | None]] = {
    "email": ("Ses boîtes : serveurs, identifiants, sa façon d'y écrire ; son relevé, ses brouillons", ("boites",),
              ("Courrier", "courrier/reception")),
    "teams": ("Ses comptes : à qui, sa façon d'y écrire, sa signature ; la clé de chaque extension", ("teams",),
              ("Teams", "teams/conversations")),
    "phone": ("Les messages WhatsApp et SMS que ton téléphone lui relaie, et ce qu'elle en fait", (),
              ("Ses sens › Messages du téléphone", "sens/messages")),
    "rss": ("Les adresses des flux qu'elle suit", ("flux",), ("Ses sens › Flux RSS", "sens/flux")),
    "web": ("Sa recherche sur le web : ses bornes", (), ("La fiche du serveur « web »", "fiche/serveur/web")),
    "mcp": ("Les serveurs MCP : à quoi ils servent pour elle, où les joindre ; qui peut quoi, sur leur fiche",
            ("serveurs-mcp",), ("Outils › Venus d'ailleurs", "outils/serveurs")),
    "camera": ("La fréquence de ses regards et la durée de ses observations", (),
               ("Ses sens › Caméra", "sens/camera")),
    "imaging": ("Ses fournisseurs d'images et qui dessine quoi ; sa qualité par défaut, ses quotas",
                ("images-fournisseurs", "images-roles"), ("Ses sens › Dessins", "sens/dessins")),
    "sensors": ("Le jeton avec lequel les appareils lui envoient leurs signaux", ("appareils",),
                ("Ses sens › Appareils", "sens/appareils")),
    "location": ("D'où viennent les tuiles de la carte de sa position", ("carte",),
                 ("Ses sens › Localisation", "sens/positions")),
    "trips": ("Où chercher un lieu et une adresse, qui calcule les itinéraires (l'écran Carte de frontendv2)",
              ("lieux", "itineraires"), None),
    "wakeup": ("Ce que chaque réveil lui fait faire, quand, à qui elle en rend compte ; ses clés sur sa fiche",
               ("reveils",), ("Réveils par API", "reveils")),
    "forge": ("Le comportement du moteur qui exécute ses apps ; les réglages d'une app restent sur sa fiche", (),
              ("Apps forgées", "apps")),
}
#: ce qui se branche sans être un plugin (le noyau s'en sert) : (nom, ce qui s'y règle, sa page de réglages)
SERVICES = (("Transcription vocale", "Le service qui transcrit les messages vocaux qu'on lui envoie", "transcription"),
            ("Notifications du téléphone", "Firebase, pour écrire à qui a fermé l'application Android",
             "notifications"))


@cache
def timezones() -> tuple[tuple[str, str], ...]:
    """Les fuseaux IANA connus de la machine (Europe/Paris…), triés, et UTC."""
    names = sorted(n for n in zoneinfo.available_timezones() if "/" in n and not n.startswith(("Etc/", "SystemV")))
    return (("UTC", "UTC (temps universel)"), *((n, n.replace("_", " ")) for n in names))


#: un hôte seul (github.com, git.exemple.org:8443) : ni schéma, ni chemin, ni espace
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+(?::[0-9]{1,5})?")


class FeedsSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    urls: Annotated[tuple[str, ...], Knob(label="Flux suivis", help="Une adresse http(s) par ligne (RSS ou Atom).",
                                          advanced=False)] = ()

    @field_validator("urls")
    @classmethod
    def _http(cls, urls: tuple[str, ...]) -> tuple[str, ...]:
        bad = [u for u in urls if not u.startswith(("http://", "https://"))]
        if bad:
            raise ValueError(f"adresse non http(s) : {bad[0][:80]}")
        return tuple(sorted(set(urls)))


class SttSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: Annotated[str, Knob(label="Adresse du service", help="Un service compatible OpenAI (vide : OpenAI).",
                                  advanced=False, order=10)] = ""
    model: Annotated[str, Knob(label="Modèle", help="Le modèle de transcription chez ce service (whisper-1 chez "
                                              "OpenAI).", advanced=False, order=20)] = "whisper-1"
    api_key: Annotated[str, Knob(label="Clé d'API", help="Chiffrée, jamais réaffichée. Vide : inchangée.",
                                 secret=True, advanced=False, order=30)] = ""

    @field_validator("base_url")
    @classmethod
    def _url(cls, url: str) -> str:
        url = url.strip()
        if not url:
            return url
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or " " in url:
            raise ValueError("une adresse http(s) complète (https://api.exemple.org/v1), ou vide pour OpenAI")
        return url


class GitSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    token: Annotated[str, Knob(label="Jeton", help="Un jeton d'accès personnel (GitHub : « fine-grained », droits "
                                                   "« Contents : Read and write » sur les dépôts de ses projets). "
                               "Chiffré, jamais réaffiché, jamais dans le journal ni dans ce qu'elle lit. Vide : "
                               "inchangé.", secret=True, advanced=False, order=10)] = ""
    hosts: Annotated[tuple[str, ...], Knob(
        label="Hôtes autorisés", help="Un hôte par ligne (github.com). Le jeton n'est montré qu'à eux : un projet "
                                      "réglé sur un autre hôte ne l'envoie pas.", advanced=False, order=15)] = \
        ("github.com",)
    user: Annotated[str, Knob(label="Utilisateur", help="Le nom qui accompagne le jeton ; « x-access-token » convient "
                                                        "à GitHub.", order=20)] = "x-access-token"

    @field_validator("hosts")
    @classmethod
    def _hosts(cls, hosts: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(dict.fromkeys(h.strip().lower() for h in hosts if h.strip()))
        bad = [h for h in cleaned if not _HOST.fullmatch(h)]
        if bad:
            raise ValueError(f"« {bad[0][:80]} » n'est pas un hôte : écris-le seul, sans « https:// » ni chemin "
                             "(github.com)")
        return cleaned

    @field_validator("user")
    @classmethod
    def _user(cls, user: str) -> str:
        user = user.strip()
        if not user or any(c.isspace() or c in ":@/" for c in user):
            raise ValueError("un nom sans espace ni « : @ / » (« x-access-token » pour GitHub)")
        return user


class PushSettings(BaseModel):
    """Les notifications du téléphone (ADR 0077) : la clé avec laquelle le serveur parle à Firebase."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_account: Annotated[str, Knob(
        label="Clé du compte de service", help="Le fichier JSON téléchargé dans la console Firebase (Paramètres du "
        "projet › Comptes de service › Générer une nouvelle clé privée), collé tel quel. Chiffrée, jamais réaffichée. "
        "Vide : inchangée ; « effacer » coupe les notifications.", secret=True, advanced=False, order=10)] = ""

    @field_validator("service_account")
    @classmethod
    def _key(cls, text: str) -> str:
        text = text.strip()
        if text:
            parse_service_account(text)  # ValueError en français : la page le dit sous le champ
        return text


#: les profils que la console propose d'appliquer (ADR 0100) ; « ajusté » : aucun profil exact (on a réglé à la main)
def _dump(doc: PersonaDoc) -> str:
    return yaml.safe_dump(doc.model_dump(mode="json"), allow_unicode=True, sort_keys=False, width=100)


def parameters(live: Live) -> Parameters:
    return Parameters(live.kernel, temperament=lambda: live.persona().temperament, overrides=live.settings.overrides,
                      save_overrides=live.settings.save_overrides, inputs=live.inputs, apply=live.reconfigure)


def _count(n: int) -> str:
    """Un nombre, ses milliers séparés : « 24 000 »."""
    return f"{n:,}".replace(",", " ")


def _seconds(s: float) -> str:
    """Une durée de réponse : « 2,3 s », « 1,5 min »."""
    if not s:
        return "—"
    if s < 0.1:
        return "moins de 0,1 s"
    return f"{s:.1f} s".replace(".", ",") if s < 60 else f"{s / 60:.1f} min".replace(".", ",")


def _cost(usd: float) -> str:
    """Un coût : « 1,24 $ », « moins de 0,01 $ », rien quand c'est gratuit ou non compté."""
    if not usd:
        return "—"
    return f"{usd:.2f} $".replace(".", ",") if usd >= 0.01 else "moins de 0,01 $"


def sections(live: Live) -> tuple[SettingsSection, ...]:
    settings = live.settings
    params = parameters(live)

    # ── modèles ──
    async def save_llm(cfg: LLMConfig) -> list[str]:
        # un fournisseur retiré emporte les rôles qui le visaient (ils retombent sur leur repli)
        cfg = cfg.model_copy(update={"routes": {r: b for r, b in cfg.routes.items() if b in cfg.backends}})
        previous = settings.llm()
        await settings.save_llm(cfg)
        problems = await live.reload_llm()
        if problems:
            await settings.save_llm(previous)
            await live.reload_llm()
        return problems

    async def models(values: Any) -> list[tuple[str, str]]:
        try:
            spec = BackendSpec.model_validate(forms.nest(dict(values)))
        except ValidationError:
            raise ValueError("fournisseur incomplet (type, hôte ou clé)") from None
        try:
            # ce que la liste dit de chacun (l'API Claude : fenêtre et réponse) se lit avant de choisir
            return [(name, f"{name} — fenêtre {tokens_fr(got.window)}"
                           + (f", réponse {tokens_fr(got.output)}" if got.output else "") if got.window else name)
                    for name, got in await list_models(spec)]
        except ListingFailed as exc:
            raise ValueError(str(exc)) from None

    async def settle_llm(cfg: LLMConfig) -> tuple[LLMConfig, list[str]]:
        """Ce que chaque fournisseur dit de son modèle, lu avant d'enregistrer (ADR 0136)."""
        if live.read_limits is None:
            return cfg, []
        return await settle_limits(cfg, live.read_limits)

    def route(role: str, _chosen: Any) -> dict[str, Any]:
        """La ligne d'un rôle dans Qui sert quoi (la correspondance rôle → fournisseur, en table) : sa famille, puis
        ce qui le sert vraiment — le fournisseur déclaré, sinon celui de son rôle de repli, ou rien (chaque appel
        échoue) —, son type et son modèle, et comment il y est arrivé."""
        cfg = settings.llm()
        chain, seen, cur, served = [], set(), role, ""
        while cur and cur not in seen:
            seen.add(cur)
            name = cfg.routes.get(cur)
            if name and name in cfg.backends:
                served = name
                break
            chain.append(ROLE_LABELS.get(cur, cur))
            nxt = FALLBACKS.get(Role(cur)) if cur in {str(x) for x in Role} else None
            cur = str(nxt) if nxt else ""
        spec = cfg.backends.get(served)
        how = "déclaré" if cfg.routes.get(role) == served and served else \
            (f"par repli ({' → '.join(chain[1:] + [ROLE_LABELS.get(cur, cur)])})" if served else "")
        return {"title": "Ce qui sert vraiment chaque rôle", "key_head": "Rôle", "choice_head": "Son fournisseur",
                "tone": "" if served else "danger",
                "cells": [{"head": "Famille", "text": ROLE_FAMILIES.get(role, "—"), "tag": True, "before": True},
                          {"head": "Ce qui le sert vraiment", "text": served or "aucun", "mono": bool(served),
                           "tone": "" if served else "muted", "sub": f"{spec.kind} · {spec.model}" if spec else ""},
                          # une étiquette pour ce qui se lit d'un coup (déclaré, rien) ; la chaîne d'un repli, en texte
                          {"head": "Comment", "text": how or "chaque appel échoue", "tag": how in ("déclaré", ""),
                           "tone": "ok" if how == "déclaré" else "muted" if served else "danger"}]}

    # ── images ──
    async def save_images(cfg: ImagingConfig) -> list[str]:
        # un fournisseur retiré emporte les rôles qui le visaient (ils retombent sur « dessiner ») et les replis
        # qui menaient à lui
        cfg = cfg.model_copy(update={
            "routes": {r: b for r, b in cfg.routes.items() if b in cfg.backends},
            "backends": {n: s if not s.fallback or s.fallback in cfg.backends else s.model_copy(update={"fallback": ""})
                         for n, s in cfg.backends.items()}})
        previous = settings.imaging()
        await settings.save_imaging(cfg)  # une configuration qui a un problème est refusée (ValueError), en le disant
        problems = await live.reload_imaging()
        if problems:
            await settings.save_imaging(previous)
            await live.reload_imaging()
        return problems

    async def image_models(values: Any) -> list[tuple[str, str]]:
        data = forms.nest(dict(values))
        try:
            names = await list_image_models(str(data.get("kind") or ""), api_key=str(data.get("api_key") or ""),
                                            base_url=str(data.get("base_url") or ""))
        except ImageListingFailed as exc:
            raise ValueError(str(exc)) from None
        return [(name, name) for name in names]

    def image_route(role: str, _chosen: Any) -> dict[str, Any]:
        """La ligne d'un rôle d'images dans Qui dessine quoi (en table) : ce qui le sert, son type et son modèle, où
        il tourne, ce qu'il sait aussi faire, et comment il y est arrivé. Sans fournisseur déclaré, elle ne génère pas
        d'images ; le premier déclaré sert « dessiner », les autres rôles y retombent."""
        cfg = settings.imaging()
        name = live.imaging.resolution().get(role, "")
        spec = cfg.backends.get(name)
        caps = next((row for row in live.imaging.status() if row["name"] == name), {}) if name else {}
        how = "déclaré" if cfg.routes.get(role) == name else "par repli (dessiner)"
        return {"title": "Ce qui sert chaque rôle", "key_head": "Rôle", "choice_head": "Son fournisseur",
                "cells": [{"head": "Ce qui le sert", "text": name or "aucun", "mono": bool(name),
                           "tone": "" if name else "muted", "sub": f"{spec.kind} · {spec.model}" if spec else ""},
                          {"head": "Où", "text": ("local" if caps.get("local") else "hébergé") if name else "—",
                           "tone": "muted"},
                          {"head": "Sait aussi", "text": ", ".join(w for w, on in (("retouche", caps.get("edit")),
                                                                                    ("adulte", caps.get("adult")))
                                                                    if on) or "—", "tone": "muted"},
                          {"head": "Comment", "text": how if name else "désactivé",
                           "tag": how == "déclaré" or not name, "tone": "ok" if name and how == "déclaré" else "muted"}]}

    def image_facts() -> list[tuple[str, str]]:
        cfg = settings.imaging()
        serving = live.imaging.serving(DRAW)
        return [("Dessiner", f"servi par « {serving} »" if serving else "désactivé : aucun fournisseur"),
                ("Fournisseurs", str(len(cfg.backends)))]

    def llm_facts() -> list[tuple[str, str]]:
        cfg = settings.llm()
        serving = live.gateway.serving(REPLY) if live.gateway.configured else ""
        return [("Répondre", f"servi par « {serving} »" if serving else "aucun modèle : chaque tour échoue "
                 "proprement"), ("Fournisseurs", str(len(cfg.backends))), ("Rôles routés", str(len(cfg.routes)))]

    def describe_backend(key: str, spec: BackendSpec) -> dict[str, Any]:
        """La carte d'un fournisseur : son type, s'il la fait parler, sa connexion, son modèle, les rôles qui le
        désignent, ses bornes en mots, et ce qu'il a fait ces dernières 24 h (le registre des appels)."""
        cfg = settings.llm()
        serves = [ROLE_LABELS.get(r, r) for r, name in cfg.routes.items() if name == key]
        speaks = live.gateway.configured and live.gateway.serving(REPLY) == key
        tags = [(KIND_LABELS.get(spec.kind, spec.kind), "info")]
        if speaks:
            tags.append(("la fait parler", "ok"))
        if spec.kind == "claude_code":
            tags.append(("clé d'API définie", "ok") if spec.auth == "cle_api" and spec.api_key else
                        ("clé d'API manquante", "warn") if spec.auth == "cle_api" else ("son login (abonnement)", ""))
        elif spec.kind != "ollama":
            tags.append(("clé d'API définie", "ok") if spec.api_key else ("clé d'API manquante", "warn"))
        if not serves:
            said = "aucun rôle ne le désigne" + (" ; ceux qui n'ont pas de fournisseur y retombent" if speaks else "")
        else:
            said = ", ".join(serves[:6]) + (f" et {len(serves) - 6} autres" if len(serves) > 6 else "")
        if spec.detected_window:
            accepts = f"{tokens_fr(spec.detected_window)} jetons" + (
                f", réponse {tokens_fr(spec.detected_output)}" if spec.detected_output else "")
        else:
            accepts = "son fournisseur ne le dit pas" if spec.detected_for == spec.detection_key else \
                "lu au prochain enregistrement"
        facts = [("Sert", f"{len(serves)} rôle{'s' if len(serves) > 1 else ''} : {said}" if serves else said),
                 ("Contexte", f"{spec.context_tokens:,} jetons".replace(",", " ") if spec.context_tokens
                  else "celui du modèle"),
                 ("Réponse au plus", f"{spec.max_output_tokens:,} jetons".replace(",", " ") if spec.max_output_tokens
                  else "ce que prévoit son type"),
                 ("Le modèle accepte", accepts),
                 ("Appels en même temps", str(spec.slots) if spec.slots else "selon son type (1 en local, 4 hébergé)")]
        where = spec.base_url or spec.host
        if where:
            facts.append(("Adresse", where))
        calls = live.calls
        now = live.kernel.mind.clock.now()
        day = calls.profile(key, now - DAY) if calls else None
        week = calls.profile(key, now - 7 * DAY) if calls else None
        last = next((tr for tr in calls.recent(50) if tr.backend == key), None) if calls else None
        if day is None:
            activity, tone = "Aucun appel ces dernières 24 h.", ""
        else:
            used = day.total
            activity = (f"{used.calls} appel{'s' if used.calls > 1 else ''} ces dernières 24 h"
                        + (f", {used.failures} en échec" if used.failures else ", tous réussis")
                        + f" · {_seconds(used.latency_avg_s)} en moyenne")
            tone = "warn" if used.failures else "ok"
        if last is not None:
            activity += f" · dernier appel {ago(now, last.at)} ({'réussi' if last.outcome == 'ok' else 'en échec'})"
        return {"tags": tags, "lead": spec.model or "aucun modèle choisi", "lead_label": "Modèle", "facts": facts,
                "activity": activity, "activity_tone": tone, "detail": _detail(day, week, now)}

    def _detail(day: Any, week: Any, now: int) -> dict[str, Any] | None:
        """Le détail d'un fournisseur : sa consommation et ses temps de réponse, sur 24 h et sur 7 jours, puis rôle
        par rôle sur 7 jours."""
        if week is None:
            return None

        def period(prof: Any) -> list[str]:
            if prof is None:
                return ["0", "—", "—", "—", "—", "—", "—", "—", "—", "—"]
            u = prof.total
            share = f" ({u.failures * 100 // u.calls} %)" if u.failures else ""
            return [_count(u.calls), f"{_count(u.failures)}{share}", _seconds(u.latency_avg_s),
                    _seconds(prof.median_s), _seconds(prof.slow_s), _seconds(prof.wait_avg_s),
                    _count(u.input_tokens), _count(u.output_tokens),
                    f"{round(u.cache_ratio * 100)} %" if u.cache_read or u.cache_write else "—", _cost(u.cost_usd)]

        labels = ("Appels", "En échec", "Temps de réponse moyen", "Temps médian", "Les plus lents (95 %)",
                  "Attente d'un créneau", "Jetons lus", "Jetons écrits", "Lus depuis le cache", "Coût")
        day_cells, week_cells = period(day), period(week)
        failure = (f"Dernier échec {ago(now, week.last_failure_at)}, pour « "
                   f"{ROLE_LABELS.get(week.last_failure_role, week.last_failure_role)} ».") \
            if week.last_failure_at else "Aucun échec ces 7 derniers jours."
        return {"rows": [(label, day_cells[i], week_cells[i]) for i, label in enumerate(labels)],
                "roles": [{"role": ROLE_LABELS.get(u.key, u.key), "calls": _count(u.calls),
                           "failures": _count(u.failures), "avg": _seconds(u.latency_avg_s),
                           "tokens": f"{_count(u.input_tokens)} / {_count(u.output_tokens)}", "cost": _cost(u.cost_usd)}
                          for u in week.by_role],
                "failure": failure, "href": "/inspecteur/systeme/appels"}

    def who_replies() -> list[Any]:
        """Qui la fait parler : le premier fournisseur déclaré sert « répondre » d'office — la page le dit,
        pour qu'il n'y ait pas de seconde étape à deviner."""
        cfg = settings.llm()
        name = cfg.routes.get(REPLY, "")
        spec = cfg.backends.get(name)
        if spec is None:
            return [Note("Aucun fournisseur : elle ne peut pas parler. Ajoute-en un — le premier déclaré sert "
                         "« répondre » d'office, et tous les autres rôles y retombent.", "warn",
                         title="Elle ne peut pas encore répondre")]
        others = len(cfg.backends) - 1
        return [Note(f"« {name} » ({spec.kind} · {spec.model}) sert « répondre » : c'est lui qui la fait parler, "
                     "et les rôles sans fournisseur à eux y retombent. Le premier fournisseur déclaré le sert "
                     "d'office" + (" ; pour en changer, va dans Qui sert quoi." if others else "."), "info",
                     title="Qui la fait parler")]

    # ── personnalité ──
    async def save_persona(doc: PersonaDoc) -> list[str]:
        if not doc.name.strip():
            return ["Son nom ne peut pas être vide : c'est ainsi qu'elle se présente."]
        previous = settings.persona_yaml()
        await settings.save_persona(_dump(doc))
        problems = await live.reconfigure()
        if problems:
            await settings.save_persona(previous)
            await live.reconfigure()
        return problems

    async def save_temperament(t: Temperament) -> list[str]:
        return await save_persona(live.persona().model_copy(update={"temperament": t}))

    # ── ses autrices (ADR 0124) ──
    def author_flows() -> list[tuple[str, str]]:
        return authors_m.flow_list(settings.email())

    def polish_served() -> str:
        return live.gateway.serving(str(Role.POLISH)) if live.gateway.configured else ""

    async def save_authors(cfg: authors_m.Authors) -> list[str]:
        await settings.save_authors(cfg)
        return []

    def author_facts() -> list[tuple[str, Any]]:
        cfg, flow_rows, served = settings.authors(), author_flows(), polish_served()
        writing = sum(1 for flow, _label in flow_rows if cfg.author_for(flow) is not None)
        rest = " (les autres partent en premier jet)" if writing < len(flow_rows) else ""
        return [("Flux qui ont une autrice", f"{writing} sur {len(flow_rows)}{rest}"),
                ("Leur modèle", Ref("local", f"{PREFIX}/reglages/roles", f"« {served} », rôle « rendre naturel »")
                 if served else "aucun")]

    def character_state() -> dict[str, Any]:
        """Son caractère écrit (ADR 0139), et ce qui retient l'appel qui l'écrirait : aucun modèle, ou le quota."""
        if not live.gateway.configured or not live.gateway.serving(str(Role.CHARACTER)):
            held = "aucun modèle ne sert ce rôle (Intelligence › Qui sert quoi)"
        else:
            held = live.gateway.held(str(Role.CHARACTER), 2)
        return temper.character_state(live.kernel, held)

    def temperament_effect(ui: Any, t: Temperament) -> list[Any]:
        """« Voir l'effet » d'un tempérament : chaque faculté rederivée, surcharges et réglages gardés."""
        return effect(ui, params.preview_temperament(t))

    async def back_to_file(by: str) -> tuple[str, str]:
        if settings.persona_yaml() is None:
            return "info", "La persona vient déjà du fichier."
        try:
            persona_file.read(live.persona_file)
        except persona_file.PersonaInvalid as exc:  # revenir à un fichier illisible, c'est revenir à rien
            raise ValueError(f"Le fichier ne se lit pas : {exc.problem}. La persona de la console reste en "
                             "place.") from None
        previous = settings.persona_yaml()
        await settings.save_persona(None)
        problems = await live.reconfigure()
        if problems:
            await settings.save_persona(previous)
            await live.reconfigure()
            raise ValueError("; ".join(problems))
        return "ok", "Retour au fichier : la persona du fichier fait foi (une révision est journalisée)."

    def persona_facts() -> list[tuple[str, str]]:
        if settings.persona_yaml():
            return [("Source", "la console")]
        live.persona()  # relue : le problème du fichier, s'il en a un, est à jour
        if live.persona_problem:
            return [("Source", "sa dernière persona gardée au journal : le fichier ne se lit pas"),
                    ("Le fichier", live.persona_problem)]
        return [("Source", f"le fichier {live.persona_file.name}")]

    def revisions() -> list[Any]:
        """Les révisions de sa persona, de la plus récente, et ce que chacune a changé."""
        kernel = live.kernel
        stored = kernel.mind.store.latest([self_c.PERSONA_REVISED.name], 200)
        events = [kernel.mind.decode(e) for e in stored]
        labels = {f.path: f.label for f in forms.describe(self_c.PersonaDoc)}
        rows = []
        for i, e in enumerate(events):
            doc = e.data.persona.model_dump(mode="json")
            before = events[i + 1].data.persona.model_dump(mode="json") if i + 1 < len(events) else None
            if before is None:
                changed = ["première version"]
            else:
                changed = [labels.get(k, k) for k in doc if doc[k] != before.get(k)] or ["rien (rejournalisée)"]
            rows.append(Row((When(e.at), Text(", ".join(changed), clamp=200), Text(str(e.origin.value), "muted")),
                            href=None))
        return [Table((Column("quand", "fit"), "ce qui a changé", Column("origine", "fit")), tuple(rows),
                      title=f"Révisions de sa persona ({len(rows)})", empty="Aucune révision journalisée.",
                      caption="Chaque enregistrement du personnage (ou du tempérament) journalise une révision "
                              "complète : l'ancienne se rejoue telle quelle.")]

    def drives() -> list[Any]:
        labels = params.slider_labels()
        rows = tuple((Text(labels.get(slider, slider)), Text(
            " · ".join(f"{o} › {p} ({_num(lo)} → {_num(hi)})" for o, p, lo, hi in moved) or "rien (non branché)",
            "text" if moved else "muted", clamp=500)) for slider, moved in params.influences().items())
        # replié sous la table de mixage : l'aide du curseur touché le dit déjà à côté (ADR 0176)
        return [Disclosure("Ce que pilote chaque curseur", (Table((Column("curseur", "fit"),
                                                                  "ce qu'il pilote (à 0 → à 1)"), rows),))]

    # ── sens ──
    def mail_owners() -> list[tuple[str, str]]:
        """À qui une boîte peut être (ADR 0185) : toi (ses propriétaires), elle par son nom, ou une personne qui a un
        compte actif — jamais un opérateur, que « toi » désigne déjà (comme dans les tableaux de droits)."""
        frame = live.kernel.mind.frame()
        her = self_c.name_of(frame.get(self_c.PERSONA)) or "Elle"
        people: dict[str, str] = {}
        for a in live.accounts.all():
            if not a.active or getattr(a, "operator", False):
                continue
            person = str(frame.get(identity_c.PERSON(a.handle)) or a.handle)
            people.setdefault(PERSON + person, a.display_name or person)
        return [("", "Toi (ses propriétaires)"), (SELF, her),
                *sorted(people.items(), key=lambda kv: kv[1].casefold())]

    async def save_mail(cfg: MailConfig) -> list[str]:
        """Une boîte est à toi, à elle ou à une personne qui a un compte (ADR 0185) — sauf ce qui était déjà là (un
        compte fermé depuis reste affiché, pour qu'on le corrige)."""
        before, known = settings.email().accounts, {v for v, _ in mail_owners()}
        problems = [f"« {name} » : elle est à toi, à elle, ou à une personne qui a un compte."
                    for name, a in cfg.accounts.items()
                    if a.owner not in known and (name not in before or before[name].owner != a.owner)]
        if problems:
            return problems
        await settings.save_email(cfg)
        # ce que ses proposeurs lisent (les comptes où elle prépare des réponses) est un réglage journalisé
        problems = await live.reconfigure()
        if problems:  # le courrier est enregistré ; seuls ses paramètres attendent la prochaine reconfiguration
            log.warning("courrier enregistré, paramètres non rejournalisés : %s", "; ".join(problems))
        return []

    async def mail_folders(values: Any) -> list[tuple[str, str]]:
        """Les dossiers d'une boîte enregistrée, lus sur son serveur avec sa connexion, à cocher (la liste
        gardée pour la console se relit du même coup)."""
        port = live.kernel.ports.get("mail") if live.kernel is not None else None
        key = str(values.get(RECORD_KEY) or "")
        if port is None or not key or port.account(key) is None:
            raise ValueError("enregistre d'abord la boîte : ses dossiers se lisent sur son serveur, avec ce qui est "
                             "enregistré")
        try:
            found = await port.refresh_folders(key)
        except (OSError, RuntimeError, EOFError) as exc:
            raise ValueError(str(exc)[:200] or type(exc).__name__) from None
        return [(f.name, f.name if f.label == f.name else f"{f.label} ({f.name})") for f in found]

    def describe_mailbox(key: str, account: MailAccount) -> dict[str, Any]:
        """La carte d'une boîte (Courrier › Paramètres, ADR 0173) : où elle en est, son adresse, comment elle lit et
        envoie, sa voix, ce que dit son dernier relevé — et où la lire."""
        port = live.kernel.ports.get("mail") if live.kernel is not None else None
        status = port.status(key) if port is not None and port.account(key) is not None else None
        if not account.enabled:
            tags = [("inactive", "")]
        elif not account.ready:
            tags = [("incomplète", "warn")]
        elif status is not None and status.error:
            tags = [("en erreur", "danger")]
        else:
            tags = [("prête", "ok")]
        tags.append((f"elle y écrit {VOICE_LABEL.get(account.voice, account.voice)}", "info"))
        if account.owner:  # à qui elle est, quand ce n'est pas à toi (ADR 0185)
            tags.append((f"à {dict(mail_owners()).get(account.owner, account.owner)}", "owner"))
        if account.microsoft:
            tags.append(("compte Microsoft", ""))
        reads = f"{account.imap_host} · {account.user}" if account.imap_host else "pas de serveur IMAP"
        facts = [("Lire", reads), ("Envoyer", account.smtp_host or "rien : elle ne fait que lire"),
                 ("Dossiers relevés", ", ".join(account.folders))]
        now = live.kernel.mind.clock.now() if live.kernel is not None else 0
        if status is not None and status.error:
            activity, tone = f"Dernière erreur : {status.error}"[:300], "danger"
        elif status is not None and status.last_poll:
            activity, tone = f"Relevée {ago(now, status.last_poll)}", ""
        else:
            activity, tone = "Jamais relevée encore", ""
        return {"title": account.label or key, "tags": tags, "lead_label": "Adresse", "lead": account.address or "—",
                "lead_plain": True, "facts": facts, "activity": activity, "activity_tone": tone,
                "fiche": f"/inspecteur/fiche/compte/{key}", "box": f"/inspecteur/courrier/reception?compte={key}"}

    def mail_facts() -> list[tuple[str, Any]]:
        accounts = settings.email().accounts
        ready = sum(1 for a in accounts.values() if a.ready)
        return [("Comptes", f"{len(accounts)} ({ready} prêt(s) à relever)" if accounts else "aucun"),
                ("Lire et envoyer", Ref("local", f"{PREFIX}/courrier/reception", "Courrier › Réception"))]

    async def save_mcp(cfg: McpConfig) -> list[str]:
        await settings.save_mcp(cfg)
        if live.mcp is not None:  # les sessions dont la connexion a changé sont fermées, les serveurs actifs rejoints
            await live.mcp.reconfigure()
        return []

    def mcp_facts() -> list[tuple[str, Any]]:
        servers = settings.mcp().servers
        ready = sum(1 for x in servers.values() if x.enabled and x.ready)
        return [("Serveurs", f"{len(servers)} ({ready} actif(s) et prêt(s))" if servers else "aucun"),
                ("État, outils et qui peut quoi", Ref("local", f"{PREFIX}/outils/serveurs",
                                                      "Outils › Venus d'ailleurs"))]

    async def save_feeds(cfg: FeedsSettings) -> list[str]:
        await settings.save_feeds(list(cfg.urls))
        return []

    def stt() -> SttSettings:
        got = settings.stt()
        return _tolerant(SttSettings, base_url=got["base_url"], model=got["model"], api_key=got["api_key"])

    async def save_stt(cfg: SttSettings) -> list[str]:
        await settings.save_stt(cfg.base_url, cfg.api_key, cfg.model or "whisper-1")
        return []

    def git() -> GitSettings:
        got = settings.git()
        return _tolerant(GitSettings, token=got["token"], user=got["user"], hosts=tuple(got["hosts"]))

    async def save_git(cfg: GitSettings) -> list[str]:
        await settings.save_git(cfg.token, cfg.user, list(cfg.hosts))
        return []

    # ── la carte de sa position (ADR 0193) ──
    async def save_map(cfg: MapConfig) -> list[str]:
        await settings.save_map_config(cfg)
        return []

    def map_facts() -> list[tuple[str, str]]:
        return live.maps.describe() if live.maps is not None else [("Source", "la carte n'est pas branchée")]

    # ── les lieux, les adresses et les itinéraires de l'écran Carte (ADR 0194) : le port ``maps`` ──
    def maps_desk() -> Any:
        return live.kernel.ports.get("maps")

    async def save_places(cfg: PlacesConfig) -> list[str]:
        await settings.save_places_config(cfg)
        return []

    def places_facts() -> list[tuple[str, str]]:
        desk = maps_desk()
        return desk.describe_places() if desk is not None else [("Lieux", "pas branchés sur ce serveur")]

    async def save_routing(cfg: RoutingConfig) -> list[str]:
        await settings.save_routing_config(cfg)
        return []

    def routing_facts() -> list[tuple[str, str]]:
        desk = maps_desk()
        return desk.describe_routing() if desk is not None else [("Itinéraires", "pas branchés sur ce serveur")]

    # ── notifications du téléphone (ADR 0077) ──
    async def save_push(cfg: PushSettings) -> list[str]:
        await settings.save_push(cfg.service_account)
        return []

    def push_facts() -> list[tuple[str, str]]:
        pasted = settings.push()
        filed = push_key_file(live.data) if live.data is not None and not pasted else ""
        key = pasted or filed
        try:
            project = parse_service_account(key).project_id if key else ""
        except ValueError as exc:
            project = f"clé illisible : {exc}"
        where = ("collée ici" if pasted else f"fichier {PUSH_KEY_FILE} du dossier de données" if filed
                 else f"aucune (colle-la ici, ou pose {PUSH_KEY_FILE} dans le dossier de données)")
        facts = [("Clé", where), ("Projet Firebase", project or "rien ne part"),
                 ("Téléphones notifiables", str(live.accounts.push_count()))]
        stats = live.hub.push.stats if live.hub.push is not None else None
        if stats is not None and (stats.sent or stats.failed or stats.gone):
            facts.append(("Depuis le démarrage", f"{stats.sent} envoyée(s), {stats.failed} en échec, "
                                                 f"{stats.gone} téléphone(s) oublié(s)"))
        if stats is not None and stats.last_error:
            facts.append(("Dernier échec", stats.last_error))
        return facts

    async def new_token(by: str) -> tuple[str, str]:
        token = await settings.new_sensors_token()
        return "ok", f"Jeton neuf (l'ancien ne vaut plus ; montré une seule fois) : {token}"

    # ── Teams (ADR 0069, 0186) ──
    #: à qui un compte Teams peut être : les mêmes qu'une boîte (toi, elle, une personne qui a un compte)
    teams_owners = mail_owners

    async def save_teams(cfg: TeamsConfig) -> list[str]:
        """Un compte Teams est à toi, à elle ou à une personne qui a un compte (ADR 0186) — sauf ce qui était déjà là
        (un compte fermé depuis reste affiché, pour qu'on le corrige)."""
        before, known = settings.teams().accounts, {v for v, _ in teams_owners()}
        problems = [f"« {name} » : il est à toi, à elle, ou à une personne qui a un compte."
                    for name, a in cfg.accounts.items()
                    if a.owner not in known and (name not in before or before[name].owner != a.owner)]
        if problems:
            return problems
        await settings.save_teams(cfg)
        # un compte supprimé : ce que son extension avait apporté s'efface avec lui (ADR 0186)
        store = live.kernel.ports.get("teams") if live.kernel is not None else None
        for gone in sorted(set(before) - set(cfg.accounts)):
            if store is not None:
                store.drop_account(gone)
        # actif ou non, et à qui est chaque compte, sont lus par ses proposeurs et ses outils : un réglage journalisé
        problems = await live.reconfigure()
        if problems:
            log.warning("teams enregistré, paramètres non rejournalisés : %s", "; ".join(problems))
        return []

    def teams_facts() -> list[tuple[str, Any]]:
        """Ses comptes en chiffres, et une fois chacun, en liens, les pages où le reste se fait (C7-15). La page vit
        dans Teams (ADR 0206) : ses conversations et ses réponses sont les onglets d'à côté, pas un fait de plus."""
        accounts, keys = settings.teams().accounts, settings.teams_keys()
        store = live.kernel.ports.get("teams") if live.kernel is not None else None
        plugged = sum(1 for k in accounts if store is not None and store.configured(k))
        keyed = sum(1 for k in accounts if k in keys)
        return [("Comptes", f"{len(accounts)} ({keyed} avec une clé, {plugged} branché(s))"),
                ("La clé de chaque extension", Ref("local", f"{PREFIX}/teams/extension", "Teams › Extension")),
                ("Ce qu'elle prépare, comment ça part", Ref("local", f"{PREFIX}/reglages/canaux",
                                                            "Canaux, le tableau de Teams ou celui d'un compte"))]

    def describe_teams_account(key: str, account: Any) -> dict[str, Any]:
        """La carte d'un compte Teams (ADR 0186) : à qui il est, sa clé, ce que son extension a apporté — et où la
        brancher."""
        store = live.kernel.ports.get("teams") if live.kernel is not None else None
        info = store.account(key) if store is not None else None
        has_key = key in settings.teams_keys()
        plugged = info is not None and bool(info.last_batch)
        tags = [("branché", "ok")] if plugged else [("clé créée", "info")] if has_key else [("sans clé", "warn")]
        if not account.enabled:  # décoché : son extension est refusée
            tags.insert(0, ("inactif", ""))
        tags.append((f"à {dict(teams_owners()).get(account.owner, account.owner)}" if account.owner else "à toi",
                     "owner" if account.owner else ""))
        if account.sign:
            tags.append(("signé", ""))
        now = live.kernel.mind.clock.now() if live.kernel is not None else 0
        # le chemin de sa clé est dit une fois, en lien, dans les faits de la page : le bandeau ne le répète pas
        activity = f"Son extension a poussé {ago(now, info.last_batch)}" if plugged else \
            "Son extension n'a encore rien apporté." + ("" if has_key else " Sa clé n'est pas encore créée.")
        return {"title": account.label or key, "tags": tags, "lead_label": "Elle y écrit à la place de",
                "lead": account.display_name or (info.self_name if info is not None and info.self_name else "") or
                "la personne du compte (le nom que Teams donne)", "lead_plain": True,
                "facts": [("Ton", account.tone or "—"), ("Consignes", "oui" if account.instructions.strip() else "aucune")],
                "activity": activity, "activity_tone": "" if plugged else "warn"}

    # ── réveils par API (ADR 0068) ──
    def wake_tools() -> list[str]:
        """Les lots qu'un réveil peut avoir : ceux du code, et ceux des serveurs extérieurs branchés."""
        return [*TOOLS, *sorted(b for b in live.kernel.registry.bundles if b.startswith("mcp."))]

    def wake_projects() -> list[tuple[str, str]]:
        views = list(live.kernel.mind.frame().get(projects_c.LIVE))
        titles = live.kernel.mind.store.content([v.title_ref for v in views if v.title_ref])
        return [(NO_PROJECT, "aucun — un travail à part"), *(
            (str(v.id), f"n° {v.id} — {titles.get(v.title_ref) or '(sans titre)'}"
             + (" (en pause)" if v.status == projects_c.PAUSED else "")) for v in views)]

    def wake_notify() -> list[tuple[str, str]]:
        return [(wakeup_c.OWNERS, "ses propriétaires"),
                (wakeup_c.NOBODY, "personne (le compte rendu reste dans la console)"),
                *((a.handle, f"{a.display_name} (compte)") for a in live.accounts.all() if a.active)]

    async def save_wakeup(cfg: WakeupConfig) -> list[str]:
        """Un projet, une personne, des outils qui existent — sauf ce qui était déjà là (un projet archivé depuis
        reste affiché, pour qu'on le corrige)."""
        before = settings.wakeup().endpoints
        projects, notify, tools = {v for v, _ in wake_projects()}, {v for v, _ in wake_notify()}, set(wake_tools())
        problems = []
        for name, ep in cfg.endpoints.items():
            old = before.get(name)
            if ep.project not in projects and (old is None or old.project != ep.project):
                problems.append(f"« {name} » : projet inconnu ou archivé ({ep.project}).")
            if ep.notify not in notify and (old is None or old.notify != ep.notify):
                problems.append(f"« {name} » : il rend compte à ses propriétaires, à un compte actif, ou à personne.")
            bad = [t for t in ep.tools if t not in tools and (old is None or t not in old.tools)]
            if bad:
                problems.append(f"« {name} » : lot inconnu ou qu'un réveil ne peut pas avoir : {', '.join(bad)} "
                                f"(permis : {', '.join(sorted(tools))}).")
        if problems:
            return problems
        await settings.save_wakeup(cfg)
        return []

    def wakeup_facts() -> list[tuple[str, Any]]:
        endpoints, keys = settings.wakeup().endpoints, settings.wakeup_keys()
        keyed = sum(1 for n in endpoints if n in keys)
        return [("Réveils", f"{len(endpoints)} ({keyed} avec une clé)" if endpoints else "aucun"),
                ("Lots permis", ", ".join(wake_tools())),
                ("Clés, appels et ce qu'ils ont donné", Ref("local", f"{PREFIX}/reveils", "Réveils par API"))]

    def plugin_rows() -> list[dict[str, Any]]:
        """La vue d'ensemble des plugins : une ligne par plugin composé (``PLUGINS``, dans son ordre) — où se règle sa
        connexion (ses pages de réglages), ses paramètres avancés (sa faculté en a-t-elle ?), où s'en servir —, puis
        ce qui se branche sans être un plugin (``SERVICES``)."""
        composed = live.kernel.registry.faculties if live.kernel is not None else {}
        pages = {pg.key: (sec, pg) for sec in declared for pg in sec.pages}
        destinations = {d.key: d.label for group in NAVIGATION for d in group.items}

        def link(key: str) -> tuple[str, str]:
            sec, pg = pages[key]
            # une page qui vit dans sa destination se nomme par elle (« Teams › Paramètres », « Ses sens › Flux
            # suivis », ADR 0173, 0206)
            if pg.home:
                return f"{destinations.get(pg.home.split('/', 1)[0], sec.label)} › {pg.title}", f"{PREFIX}/{pg.home}"
            return pg.title, f"{PREFIX}/reglages/{pg.key}"

        rows = [{"name": FACULTY_LABELS.get(name, name), "what": what, "configure": [link(k) for k in keys],
                 "params": faculty_url(name) if composed[name].params is not None else "",
                 "usage": (usage[0], f"{PREFIX}/{usage[1]}") if usage else None}
                for name, (what, keys, usage) in PLUGINS.items() if name in composed]
        services = [{"name": name, "what": what, "configure": [link(key)], "params": "", "usage": None}
                    for name, what, key in SERVICES]
        return [{"title": "Plugins", "rows": rows}, {"title": "Hors plugins", "rows": services}]

    declared = (
        # dessinée (handmade/reglages/plugins.html) : une ligne par plugin composé, sans pagination
        SettingsSection("plugins", "Plugins", "plugins", None, order=0,
                        head=lambda query: drawn_settings.plugins(plugin_rows()),
                        pages=(SettingsPage("plugins", "Vue d'ensemble des plugins", form=False,
                                            description="Chaque plugin : où se règle sa connexion, ses paramètres "
                                                        "avancés, et où s'en servir."),)),
        SettingsSection("modeles", "Modèles", "intelligence", LLMConfig, settings.llm, save_llm,
                        description="Les fournisseurs de modèles, et lequel sert chaque rôle. Les clés sont "
                                    "chiffrées, jamais réaffichées.", loaders={"models": models}, facts=llm_facts,
                        describe={"backends": describe_backend, "routes": route}, adjust=settle_llm,
                        pages=(
                            SettingsPage("fournisseurs", "Fournisseurs", ("backends",), order=10, extra=who_replies,
                                         description=(
                                "Les services qui font tourner ses modèles. Chaque fournisseur a sa page : son "
                                "type, le modèle choisi dans la liste qu'il propose, sa clé ; le reste est rangé "
                                "dans « Options avancées ». Le premier déclaré sert « répondre » d'office.")),
                            SettingsPage("roles", "Qui sert quoi", ("routes",), order=20, facts=False, description=(
                                             "Chaque rôle (répondre, rêver, retenir, trier le courrier…) choisit "
                                             "son fournisseur. Laisse vide : le rôle retombe sur son repli. "
                                             "« Répondre » est toujours servi : sans choix, par le premier "
                                             "fournisseur déclaré.")),
                        )),
        SettingsSection("images", "Images", "intelligence", ImagingConfig, settings.imaging, save_images, order=120,
                        description="Les fournisseurs qui génèrent ses images, et lequel sert chaque rôle. Aucun "
                                    "fournisseur : elle n'en génère pas. Les clés sont chiffrées, jamais "
                                    "réaffichées.", loaders={"image_models": image_models}, facts=image_facts,
                        describe={"routes": image_route},
                        pages=(
                            SettingsPage("images-fournisseurs", "Fournisseurs d'images", ("backends",), order=10,
                                         description=(
                                             "OpenAI (son API Images), ou un serveur compatible : le tien, qui "
                                             "fait tourner un modèle sur ta machine, ou un proxy. Le premier "
                                             "déclaré sert « dessiner » d'office. Un repli prend le relais "
                                             "d'une panne, ou de ce que le premier ne sait pas faire ; jamais "
                                             "d'un refus de modération.")),
                            SettingsPage("images-roles", "Qui dessine quoi", ("routes",), order=20,
                                         facts=False, description=(
                                             "Dessiner (une demande), retoucher une image reçue, ses dessins à "
                                             "elle. Laisse vide : le rôle retombe sur « dessiner ».")),
                        )),
        SettingsSection("personnage", "Personnage", "personnage", PersonaDoc, live.persona, save_persona,
                        description="Qui elle est. Chaque enregistrement journalise une révision de sa persona.",
                        exclude=("temperament",), yaml=True, facts=persona_facts,
                        choices={"timezone": timezones},
                        commands=(Command("fichier", "Revenir au fichier", back_to_file, danger=True,
                                          confirm="La persona rédigée ici sera oubliée ; le fichier fera foi."),),
                        pages=(
                            SettingsPage("identite", "Identité",
                                         ("name", "nature", "description", "language", "timezone"), order=10,
                                         description="Son nom, ce qu'elle est (une IA qui le sait, ou une personne "
                                                     "incarnée), qui elle est en une phrase, sa langue et l'heure "
                                                     "qu'elle vit (ses nuits, ses salutations en dépendent)."),
                            # ADR 0138 : un seul texte la décrit ; ce qu'elle ressent se règle dans son tempérament
                            SettingsPage("portrait", "Portrait", ("portrait", "facts", "interests"), order=20,
                                         facts=False, description="Qui elle est, en prose — le seul texte qui la "
                                                                  "décrit, qu'elle lit partout —, ce qui est vrai "
                                                                  "d'elle, et ce qui la passionne. Ce qu'elle "
                                                                  "ressent, montre et fait de ses émotions se règle "
                                                                  "dans son tempérament, pas ici."),
                            SettingsPage("parole", "Sa parole", ("samples", "greetings", "reference_thread"),
                                         order=30, facts=False,
                                         description="Comment elle écrit : des échanges qui montrent sa voix en "
                                                     "chat, ses petits mots de bonjour, et un vrai fil de SMS pour "
                                                     "la forme — des exemples, jamais recopiés."),
                            SettingsPage("document", "Import / export", order=50, form=False, yaml=True,
                                         commands=True, extra=revisions, description=(
                                             "Le personnage entier en YAML (pour le garder ou le coller d'un "
                                             "coup), le retour au fichier, et l'historique de ses révisions.")),
                        )),
        SettingsSection("autrices", "Autrices", "personnage", authors_m.Authors, settings.authors, save_authors,
                        order=120,
                        # en tête, le seul bandeau : aucun modèle ne les fait écrire
                        head=lambda query: drawn_authors.head(served=polish_served()),
                        facts=author_facts,
                        # « Où elles écrivent » est le formulaire même : une ligne par flux, sa liste dans la colonne
                        # « Autrice » (une seule table, un seul Enregistrer)
                        describe={"authors": lambda key, entry: drawn_authors.describe(
                            key, entry, settings.authors(), dict(author_flows())),
                                  "flows": lambda key, value: drawn_authors.flow(key,
                                                                                 teams_on=settings.teams().enabled)},
                        keys={"flows": author_flows},
                        description="Qui récrit ce qui part, et où : une autrice par flux — le chat, chaque boîte "
                                    "mail, Teams, le téléphone —, chacune avec ses codes d'écriture. Le sens reste "
                                    "celui du premier jet, la forme change."),
        SettingsSection("temperament", "Tempérament", "personnage", Temperament,
                        lambda: live.persona().temperament, save_temperament, order=110,
                        head=lambda query: temper.head(live.persona().temperament, query, character_state()),
                        probe=character_state,
                        prefill=lambda query: temper.prefill(live.persona().temperament, query),
                        description="Sa matrice de personnalité : des curseurs rangés en familles, une humeur de "
                                    "fond, deux choix. L'entrée principale de son caractère ; chaque faculté en dérive "
                                    "ses paramètres (Paramètres avancés), et ce qui s'écarte du milieu se dit au "
                                    "modèle.",
                        blocks=drives, preview=temperament_effect, aside=True,
                        pages=(SettingsPage("temperament", "Tempérament", blocks=True, description=(
                            "Des curseurs (0,5 = comme la plupart des gens ; la console s'arrête à 0,1 et 0,9), "
                            "une humeur de fond, sa réaction quand on la blesse et sa défense quand on la touche. "
                            "Chaque faculté en dérive ses paramètres ; la table dessous dit ce que pilote chaque "
                            "curseur, mesuré en le poussant à ses deux bouts. Son caractère, le modèle l'écrit "
                            "d'après ces curseurs, à chaque enregistrement (en haut de la page). Un profil les pose "
                            "tous d'un coup : choisis-le en haut, le formulaire s'ouvre sur ses valeurs, rien n'est "
                            "enregistré avant « Enregistrer ».")),)),
        SettingsSection("notifications", "Notifications du téléphone", "carte-telephone", PushSettings,
                        lambda: _tolerant(PushSettings, service_account=settings.push()), save_push, order=20,
                        description="Ce qu'elle écrit à quelqu'un dont l'application est fermée part par Firebase, "
                                    "chiffré pour son seul téléphone.", facts=push_facts,
                        pages=(SettingsPage("notifications", "Notifications du téléphone", description=(
                            "L'application Android ne garde aucune connexion ouverte quand elle est fermée : ce "
                            "qu'elle écrit à la personne lui arrive en notification par Firebase Cloud Messaging, "
                            "chiffré avec une clé que seul son téléphone connaît (Google ne transporte qu'un "
                            "chiffré). Il faut un projet Firebase où l'application est déclarée, et la clé d'un "
                            "compte de service de ce projet : collée ici, ou posée dans le dossier de données sous "
                            "le nom firebase-service-account.json (droits 600) — collée ici, elle prime. Sans elle, "
                            "l'application ne reçoit que ce qu'elle trouve en s'ouvrant.")),)),
        SettingsSection("carte", "Carte de sa position", "carte-telephone", MapConfig, settings.map_config, save_map,
                        order=25, facts=map_facts,
                        description="D'où viennent les tuiles de la carte de Téléphone › Position : un "
                                    "fichier PMTiles du dossier de données, ou un serveur de carte que ce serveur "
                                    "relaie. Le navigateur ne parle qu'à ce serveur.",
                        pages=(SettingsPage("carte", "Carte de sa position", description=(
                            "La carte où chacun voit sa dernière position (frontendv2, Téléphone › Position). Ses "
                            "tuiles passent toujours par ce serveur : le navigateur ne joint aucune adresse du "
                            "dehors, qui dirait où la personne se trouve. Un fichier PMTiles posé sous cartes/ du "
                            "dossier de données (une extraction de la carte Protomaps, jamais sauvegardée : elle se "
                            "réextrait) ne parle à personne ; un serveur de carte est joint par ce serveur seul, sans "
                            "rien de la personne. Hors de la zone couverte, ou sans carte, la position garde son "
                            "plan dessiné.")),)),
        SettingsSection("lieux", "Lieux et adresses", "carte-telephone", PlacesConfig, settings.places_config, save_places,
                        order=26, facts=places_facts,
                        description="Où l'écran Carte et ses outils cherchent un lieu et une adresse : "
                                    "l'index des lieux du dossier de données (rien ne sort), et la Géoplateforme de "
                                    "l'IGN pour les adresses, que ce serveur joint seul.",
                        pages=(SettingsPage("lieux", "Lieux et adresses", description=(
                            "Les lieux — restaurants, campings, sommets, musées, villes et lieux-dits — se cherchent "
                            "dans un index tiré des tuiles de la carte par « mika carte lieux » (un fichier SQLite "
                            "sous cartes/, refait quand la carte l'est) : par le nom, autour d'un point, dans une "
                            "zone, le long d'un trajet, sans que rien ne sorte. Une adresse (un numéro et une rue) "
                            "vient de la Géoplateforme de l'IGN (la Base Adresse Nationale), relayée par ce serveur : "
                            "seul le texte cherché lui part, jamais la position de la personne. Sans index, ou sans "
                            "adresses, l'écran Carte le dit.")),)),
        SettingsSection("itineraires", "Itinéraires", "carte-telephone", RoutingConfig, settings.routing_config, save_routing,
                        order=27, facts=routing_facts,
                        description="Qui calcule les itinéraires de l'écran Carte et de ses voyages : un "
                                    "serveur Valhalla, le public de FOSSGIS ou le tien. Vers lui ne partent que les "
                                    "points du trajet.",
                        pages=(SettingsPage("itineraires", "Itinéraires", description=(
                            "En voiture, à vélo ou à pied, péages, autoroutes ou ferries évitables, les consignes en "
                            "français et le meilleur ordre des arrêts : un serveur Valhalla les calcule, joint par ce "
                            "serveur seul. Le Valhalla public de FOSSGIS (celui d'openstreetmap.org) demande au plus "
                            "une demande par seconde, pour tout ce serveur, et ne garantit pas de répondre : chaque "
                            "trajet est gardé un jour, un trajet redemandé ne repart pas. Un Valhalla à toi, sur le "
                            "portable, n'a pas ces limites (la recette : deploy/README.md, « La carte de sa "
                            "position »). Par défaut, aucun : rien ne sort.")),)),
        # joint par Connexions extérieures, où son lien est dans le menu (ADR 0197)
        SettingsSection("depots", "Dépôts Git", "connexions", GitSettings, git, save_git,
                        description="Le jeton avec lequel ses projets poussent vers leur dépôt distant.",
                        facts=lambda: [("Jeton", "défini" if settings.git()["token"] else "aucun"),
                                       ("L'adresse de chaque dépôt", Ref("local", f"{PREFIX}/projets",
                                                                         "sur la fiche de son projet"))],
                        pages=(SettingsPage("depots", "Dépôts Git", description=(
                            "Le jeton avec lequel l'atelier d'un projet pousse vers son dépôt distant (GitHub ou un "
                            "autre hôte https) et en récupère l'histoire ; l'adresse du dépôt se règle sur la fiche "
                            "du projet. Le jeton ne passe que par l'environnement de git, limité à l'hôte du "
                            "dépôt.")),)),
        SettingsSection("courrier", "Courrier", "plugins", MailConfig, settings.email, save_mail, lock=settings.writing,
                        description="Ses boîtes aux lettres (IMAP pour lire et ranger, SMTP pour envoyer) et, pour "
                                    "chacune, sa façon d'y écrire. Relues à chaque relève.", order=10,
                        facts=mail_facts, fixed_names=("accounts",), describe={"accounts": describe_mailbox},
                        loaders={"folders": mail_folders}, named_loaders=("folders",),
                        choices={"accounts.owner": mail_owners},
                        # ses paramètres vivent dans le Courrier, en haut à droite : ses boîtes et ses paramètres
                        # généraux (relevé, ce qu'elle en dit, ses brouillons), sur une seule page (ADR 0173)
                        pages=(SettingsPage("boites", "Paramètres", ("accounts",), description=(
                            "Ses boîtes aux lettres — lire (IMAP), envoyer (SMTP), sa voix dans chacune — et ce que "
                            "fait le courrier de toutes : son relevé, ce qu'elle en dit, les réponses qu'elle "
                            "prépare."), home="courrier/parametres", params="email",
                            template="handmade/mail/parametres.html", styles=("handmade/courrier_reglages.css",)),)),
        SettingsSection("mcp", "Outils extérieurs", "plugins", McpConfig, settings.mcp, save_mcp, order=15,
                        lock=settings.writing,
                        description="Les serveurs MCP dont elle peut utiliser les outils. Jetons et variables "
                                    "secrètes chiffrés, jamais réaffichés.", facts=mcp_facts,
                        fixed_names=("servers",),
                        # qui peut quoi : sur la fiche du serveur, en lignes d'accès (« Accès aux outils », ADR 0131)
                        # — ici, la connexion seulement
                        exclude=tuple(f"servers.{k}" for k in ("access", "default_read", "default_act",
                                                               "default_keep")),
                        # dans Ses outils, en haut à droite, à côté de Venus d'ailleurs (ADR 0206)
                        pages=(SettingsPage("serveurs-mcp", "Paramètres des services", ("servers",), description=(
                            "Chaque service branché (un serveur MCP) a sa page : à quoi il sert, pour elle — la ligne "
                            "de son catalogue —, puis "
                            "où le joindre (une adresse, ou une commande lancée ici, isolée) et ses bornes. Qui peut "
                            "quoi se règle sur sa fiche, dans « Accès aux outils »."), home="outils/parametres"),)),
        SettingsSection("reveils", "Réveils par API", "plugins", WakeupConfig, settings.wakeup, save_wakeup, order=45,
                        description="Les réveils que des systèmes extérieurs appellent (POST /api/wake/<nom>) : ce "
                                    "qu'ils lui font faire, quand, à qui elle en rend compte. Leurs clés se génèrent "
                                    "sur leur fiche, montrées une seule fois.",
                        facts=wakeup_facts, fixed_names=("endpoints",),
                        choices={"endpoints.project": wake_projects, "endpoints.notify": wake_notify},
                        # dans Réveils par API, en haut à droite (ADR 0206)
                        pages=(SettingsPage("reveils", "Paramètres", ("endpoints",), description=(
                            "Chaque réveil a sa page : à quoi il sert, ses consignes (elles priment sur le texte "
                            "qu'un appel apporte, qui n'est jamais une consigne), son projet, son mode, ses outils, "
                            "s'il passe outre son sommeil, à qui elle rend compte, ses bornes. Son nom est la fin de "
                            "son URL."), home="reveils/parametres"),)),
        # Flux, Transcription et Appareils : dans Ses sens, derrière sa roue (ADR 0206)
        SettingsSection("flux", "Flux", "plugins", FeedsSettings, lambda: FeedsSettings(urls=tuple(settings.feeds())),
                        save_feeds, description="Ce qu'elle lit du monde.", order=20,
                        facts=lambda: [("Suivis", str(len(settings.feeds()))),
                                       ("Ce qu'elle en remarque", Ref("local", f"{PREFIX}/sens/flux", "Flux RSS"))],
                        pages=(SettingsPage("flux", "Flux suivis", description=(
                            "Les flux RSS ou Atom qu'elle relève."), home="sens/parametres-flux"),)),
        SettingsSection("transcription", "Transcription", "plugins", SttSettings, stt, save_stt, order=30,
                        description="Pour entendre les messages vocaux (un service compatible Whisper).",
                        pages=(SettingsPage("transcription", "Transcription vocale", description=(
                            "Le service qui transcrit les messages vocaux qu'on lui envoie (compatible Whisper). "
                            "Sans lui, un vocal lui arrive comme « un message vocal » sans son contenu."),
                            home="sens/parametres-transcription"),)),
        SettingsSection("teams", "Teams", "plugins", TeamsConfig, settings.teams, save_teams, order=12,
                        lock=settings.writing,
                        description="Les conversations Teams que l'extension de navigateur de chaque compte lui "
                                    "apporte, et ce qu'elle fait des réponses qu'elle y prépare.",
                        facts=teams_facts, fixed_names=("accounts",), describe={"accounts": describe_teams_account},
                        choices={"accounts.owner": teams_owners},
                        # dans Teams, en haut à droite, comme le courrier (ADR 0173, 0206)
                        pages=(SettingsPage("teams", "Paramètres", home="teams/parametres", description=(
                            "Chaque compte Teams — le tien, le sien, celui d'une personne qui a un compte — a son "
                            "extension (frontend/Extension), qui lit ce que Teams web reçoit dans le navigateur où il "
                            "est ouvert et l'apporte ici, avec la clé de ce compte (montrée une seule fois). Elle y "
                            "écrit à la place de la personne du compte : un brouillon posé dans Teams, un envoi après "
                            "accord, ou un envoi sans demander — toujours de ce compte, sous son nom.")),)),
        SettingsSection("appareils", "Appareils", "plugins", None, order=40,
                        description="Les appareils envoient leurs signaux à POST /api/perceptions, avec ce jeton.",
                        facts=lambda: [("Jeton", "défini" if settings.sensors_digest() else "aucun")],
                        commands=(Command("jeton", "Nouveau jeton", new_token,
                                          confirm="L'ancien jeton ne vaudra plus rien."),),
                        pages=(SettingsPage("appareils", "Accès des appareils", commands=True, description=(
                            "Les appareils envoient leurs signaux à POST /api/perceptions avec ce jeton "
                            "(en-tête Authorization: Bearer). Un nouveau jeton se montre une seule fois ; l'ancien "
                            "ne vaut plus rien."), home="sens/parametres-appareils"),)),
    )
    return declared


def _tolerant(cls: type[BaseModel], /, **data: Any) -> Any:
    """Une valeur enregistrée avant qu'une règle existe (un hôte « https://github.com/ ») s'affiche
    quand même, telle quelle : la page reste ouverte pour la corriger ; l'enregistrer la revalide."""
    try:
        return cls(**data)
    except ValidationError:
        return cls.model_construct(**data)


def _num(value: Any) -> str:
    if isinstance(value, float):
        return decimal_fr(value, 3)  # « 0,00000001 », comme les bornes des Paramètres avancés
    return str(value)
