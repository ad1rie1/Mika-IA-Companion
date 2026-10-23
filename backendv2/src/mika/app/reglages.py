"""Les réglages d'exploitation, déclarés : ce qu'un opérateur décide, et où.

Chaque section apporte un modèle (le formulaire en sort), sa valeur actuelle
et de quoi l'enregistrer ; la console les rend toutes de la même façon
(``inspector/pages/settings_form.py``). Un enregistrement qui échoue au
rechargement est défait : on ne laisse pas une configuration à moitié prise.
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
from mika.adapters.llm.config import KIND_LABELS, REPLY, ROLE_LABELS, BackendSpec, LLMConfig
from mika.adapters.llm.models import ListingFailed, list_models
from mika.adapters.mail import MailConfig
from mika.adapters.mcp.config import McpConfig
from mika.adapters.push import parse_service_account
from mika.adapters.teams import TeamsConfig
from mika.app import authors as authors_m
from mika.app import persona as persona_file
from mika.app.handmade import ago
from mika.app.handmade import authors as drawn_authors
from mika.app.handmade import temperament as temper
from mika.app.settings import PUSH_KEY_FILE, push_key_file
from mika.app.wakeups import NO_PROJECT, TOOLS, WakeupConfig
from mika.contracts import projects as projects_c
from mika.contracts import self_ as self_c
from mika.contracts import wakeup as wakeup_c
from mika.contracts.self_ import PersonaDoc
from mika.inspector.catalog import Command, SettingsPage, SettingsSection, SettingsTab
from mika.inspector.pages.reglages import effect
from mika.kernel import forms
from mika.kernel.clock import DAY
from mika.kernel.forms import Knob
from mika.kernel.inspect import Badge, Column, Nav, NavItem, Note, Ref, Row, Table, Text, When
from mika.ports.imaging import DRAW
from mika.ports.imaging import ROLE_LABELS as IMAGE_ROLE_LABELS
from mika.ports.imaging import ROLES as IMAGE_ROLES
from mika.runtime.params import Parameters
from mika.vocab.episodes import FALLBACKS, VOICE_ROLES, Role
from mika.vocab.temperament import (
    Temperament,
)

if TYPE_CHECKING:
    from mika.app.server import Live

log = logging.getLogger("mika.reglages")

#: les rubriques du sous-menu de la configuration, dans l'ordre
TABS = (SettingsTab("intelligence", "Intelligence"), SettingsTab("personnage", "Personnage"),
        SettingsTab("canaux", "Canaux"), SettingsTab("sens", "Plugins"))

#: la famille de chaque rôle (la page « Qui sert quoi »)
ROLE_FAMILIES = {**{str(r): "voix" for r in VOICE_ROLES}, "extract": "mémoire", "validate": "mémoire",
                 "compact": "mémoire", "profile": "compréhension", "interpret": "compréhension",
                 "triage": "sens", "caption": "sens", "plan": "travail", "job": "travail", "polish": "voix"}


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
    async def save_llm(cfg: LLMConfig, by: str) -> list[str]:
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
            return [(name, name) for name in await list_models(spec)]
        except ListingFailed as exc:
            raise ValueError(str(exc)) from None

    def routing() -> list[Any]:
        """Qui sert vraiment chaque rôle : le fournisseur déclaré, sinon le repli de rôle."""
        cfg = settings.llm()
        rows = []
        for role in Role:
            r = str(role)
            chain, seen, cur, served = [], set(), r, ""
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
            how = "déclaré" if cfg.routes.get(r) == served and served else \
                (f"par repli ({' → '.join(chain[1:] + [ROLE_LABELS.get(cur, cur)])})" if served else "")
            rows.append(Row((Text(ROLE_LABELS.get(r, r)), Badge(ROLE_FAMILIES.get(r, "—"), "muted"),
                             Text(served or "aucun", "mono" if served else "muted"),
                             Text(f"{spec.kind} · {spec.model}" if spec else "—", "muted"),
                             Badge(how, "ok" if how == "déclaré" else "info") if served
                             else Badge("chaque appel échoue", "danger")),
                            tone="" if served else "danger"))
        return [Table((Column("rôle"), Column("famille", "fit"), "fournisseur qui sert", "type · modèle",
                       "comment"), tuple(rows), title="Ce qui sert vraiment chaque rôle",
                      caption="Un rôle sans fournisseur retombe sur son rôle de repli (murmurer → répondre, "
                              "vérifier → retenir → répondre…). Les rôles « voix » reçoivent sa persona.")]

    # ── images ──
    async def save_images(cfg: ImagingConfig, by: str) -> list[str]:
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

    def image_routing() -> list[Any]:
        """Qui sert chaque rôle d'images, et ce que ce fournisseur sait faire."""
        cfg = settings.imaging()
        served = live.imaging.resolution()
        status = {row["name"]: row for row in live.imaging.status()}
        rows = []
        for role in IMAGE_ROLES:
            name = served.get(role, "")
            spec = cfg.backends.get(name)
            caps = status.get(name, {})
            how = "déclaré" if cfg.routes.get(role) == name else "par repli (dessiner)"
            rows.append(Row((Text(IMAGE_ROLE_LABELS[role]), Text(name or "aucun", "mono" if name else "muted"),
                             Text(f"{spec.kind} · {spec.model}" if spec else "—", "muted"),
                             Text(("local" if caps.get("local") else "hébergé") if name else "—", "muted"),
                             Text(", ".join(w for w, on in (("retouche", caps.get("edit")),
                                                            ("adulte", caps.get("adult"))) if on) or "—", "muted"),
                             Badge(how, "ok" if how == "déclaré" else "info") if name
                             else Badge("désactivé", "muted"))))
        return [Table((Column("rôle"), "fournisseur qui sert", "type · modèle", Column("où", "fit"), "sait aussi",
                       "comment"), tuple(rows), title="Ce qui sert chaque rôle",
                      caption="Sans fournisseur déclaré, elle ne génère pas d'images. Le premier déclaré sert "
                              "« dessiner » ; les autres rôles y retombent.")]

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
        facts = [("Sert", f"{len(serves)} rôle{'s' if len(serves) > 1 else ''} : {said}" if serves else said),
                 ("Contexte", f"{spec.context_tokens:,} jetons".replace(",", " ") if spec.context_tokens
                  else "celui du modèle"),
                 ("Réponse au plus", f"{spec.max_output_tokens:,} jetons".replace(",", " ") if spec.max_output_tokens
                  else "ce que prévoit son type"),
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
    async def save_persona(doc: PersonaDoc, by: str) -> list[str]:
        if not doc.name.strip():
            return ["Son nom ne peut pas être vide : c'est ainsi qu'elle se présente."]
        previous = settings.persona_yaml()
        await settings.save_persona(_dump(doc))
        problems = await live.reconfigure()
        if problems:
            await settings.save_persona(previous)
            await live.reconfigure()
        return problems

    async def save_temperament(t: Temperament, by: str) -> list[str]:
        return await save_persona(live.persona().model_copy(update={"temperament": t}), by)

    # ── ses autrices (ADR 0124) ──
    def author_flows() -> list[tuple[str, str]]:
        return authors_m.flow_list(settings.email())

    def polish_served() -> str:
        return live.gateway.serving(str(Role.POLISH)) if live.gateway.configured else ""

    async def save_authors(cfg: authors_m.Authors, by: str) -> list[str]:
        await settings.save_authors(cfg)
        return []

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
        return [Table((Column("curseur", "fit"), "ce qu'il pilote (à 0 → à 1)"), rows,
                      title="Ce que pilote chaque curseur")]

    # ── sens ──
    async def save_mail(cfg: MailConfig, by: str) -> list[str]:
        await settings.save_email(cfg)
        # ce que ses proposeurs lisent (les comptes où elle prépare des réponses) est un réglage journalisé
        problems = await live.reconfigure()
        if problems:  # le courrier est enregistré ; seuls ses paramètres attendent la prochaine reconfiguration
            log.warning("courrier enregistré, paramètres non rejournalisés : %s", "; ".join(problems))
        return []

    def mail_facts() -> list[tuple[str, str]]:
        accounts = settings.email().accounts
        ready = sum(1 for a in accounts.values() if a.ready)
        return [("Comptes", f"{len(accounts)} ({ready} prêt(s) à relever)" if accounts else "aucun"),
                ("Lire et envoyer", "Courrier › Réception")]

    async def save_mcp(cfg: McpConfig, by: str) -> list[str]:
        await settings.save_mcp(cfg)
        if live.mcp is not None:  # les sessions dont la connexion a changé sont fermées, les serveurs actifs rejoints
            await live.mcp.reconfigure()
        return []

    def mcp_facts() -> list[tuple[str, str]]:
        servers = settings.mcp().servers
        ready = sum(1 for x in servers.values() if x.enabled and x.ready)
        return [("Serveurs", f"{len(servers)} ({ready} actif(s) et prêt(s))" if servers else "aucun"),
                ("État et outils", "Outils › Venus d'ailleurs")]

    async def save_feeds(cfg: FeedsSettings, by: str) -> list[str]:
        await settings.save_feeds(list(cfg.urls))
        return []

    def stt() -> SttSettings:
        got = settings.stt()
        return _tolerant(SttSettings, base_url=got["base_url"], model=got["model"], api_key=got["api_key"])

    async def save_stt(cfg: SttSettings, by: str) -> list[str]:
        await settings.save_stt(cfg.base_url, cfg.api_key, cfg.model or "whisper-1")
        return []

    def git() -> GitSettings:
        got = settings.git()
        return _tolerant(GitSettings, token=got["token"], user=got["user"], hosts=tuple(got["hosts"]))

    async def save_git(cfg: GitSettings, by: str) -> list[str]:
        await settings.save_git(cfg.token, cfg.user, list(cfg.hosts))
        return []

    # ── notifications du téléphone (ADR 0077) ──
    async def save_push(cfg: PushSettings, by: str) -> list[str]:
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

    # ── Teams (ADR 0069) ──
    async def save_teams(cfg: TeamsConfig, by: str) -> list[str]:
        await settings.save_teams(cfg)
        # le mode, l'initiative et les exclusions sont lus par ses proposeurs : un réglage journalisé
        problems = await live.reconfigure()
        if problems:
            log.warning("teams enregistré, paramètres non rejournalisés : %s", "; ".join(problems))
        return []

    def teams_facts() -> list[tuple[str, str]]:
        key = live.teams.key_state() if live.teams is not None else None
        store = live.kernel.ports.get("teams") if live.kernel is not None else None
        seen = "jamais" if store is None or not store.configured() else "oui"
        return [("Clé de l'extension", f"définie ({key.hint}…)" if key is not None else "aucune"),
                ("Reçu de l'extension", seen),
                ("Conversations et réponses", "Relations & échanges › Teams")]

    async def new_teams_key(by: str) -> tuple[str, str]:
        if live.teams is None:
            return "warn", "Teams n'est pas branché."
        key = await live.teams.new_key(by)
        return "ok", (f"Clé neuve (l'ancienne ne vaut plus ; montrée une seule fois) — colle-la dans l'extension : "
                      f"{key}")

    async def revoke_teams_key(by: str) -> tuple[str, str]:
        if live.teams is None or not await live.teams.revoke_key(by):
            return "warn", "Il n'y avait pas de clé."
        return "ok", "Clé retirée : l'extension est refusée jusqu'à une clé neuve."

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

    async def save_wakeup(cfg: WakeupConfig, by: str) -> list[str]:
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

    def wakeup_facts() -> list[tuple[str, str]]:
        endpoints, keys = settings.wakeup().endpoints, settings.wakeup_keys()
        keyed = sum(1 for n in endpoints if n in keys)
        return [("Réveils", f"{len(endpoints)} ({keyed} avec une clé)" if endpoints else "aucun"),
                ("Lots permis", ", ".join(wake_tools())),
                ("Clés, appels et ce qu'ils ont donné", "Connexions extérieures › Réveils par API")]

    def plugin_settings() -> list[Any]:
        rows = (
            ("Courrier", "Boîtes, serveurs, identifiants et façon d'écrire", "boites", "email", "courrier/reception"),
            ("Flux RSS", "Adresses des flux suivis", "flux", "rss", "sens/flux"),
            ("Outils extérieurs", "Serveurs MCP : à quoi ils servent pour elle, où les joindre, pour qui",
             "serveurs-mcp", "", "outils/serveurs"),
            ("Caméra", "Fréquence des regards et durée des observations", "comportement-camera", "", "sens/camera"),
            ("Dessins", "Ses fournisseurs d'images ; sa qualité par défaut, ses quotas", "images-fournisseurs",
             "imaging", "sens/dessins"),
            ("Appareils", "Jeton d'accès des capteurs", "appareils", "", "sens/appareils"),
            ("Teams", "La clé de l'extension, ce qu'elle fait de ses réponses (brouillon, accord, autonome), sa "
             "signature", "teams", "teams", "teams/conversations"),
            ("Réveils par API", "Ce que chaque réveil lui fait faire, quand, à qui elle en rend compte ; ses clés sur "
             "sa fiche", "reveils", "wakeup", "reveils"),
            ("Forge", "Comportement du moteur qui exécute les apps", "comportement-forge", "", "apps"),
        )
        return [Note("Les connexions et le comportement des plugins se règlent ici. Les réglages propres à une "
                     "app forgée restent dans sa fiche, dans la Forge."),
                Table(("Plugin", "Ce qui se règle", "Configuration", "Paramètres avancés", "Utiliser / consulter"),
                      tuple((label, help_, Ref("local", f"/inspecteur/reglages/{settings_page}", "Configurer"),
                             Ref("local", f"/inspecteur/reglages/comportement-{owner}", "Paramètres") if owner else "—",
                             Ref("local", f"/inspecteur/{usage}", "Ouvrir"))
                            for label, help_, settings_page, owner, usage in rows), title="Plugins"),
                Nav((NavItem("Configurer la transcription vocale", Ref("local", "/inspecteur/reglages/transcription",
                                                                         "Transcription vocale")),))]

    return (
        SettingsSection("plugins", "Plugins", "sens", None, order=0, blocks=plugin_settings,
                        pages=(SettingsPage("plugins", "Vue d'ensemble des plugins", form=False, blocks=True,
                                            description="Choisis le plugin à configurer ou ouvre sa vue d'utilisation."),)),
        SettingsSection("modeles", "Modèles", "intelligence", LLMConfig, settings.llm, save_llm,
                        description="Les fournisseurs de modèles, et lequel sert chaque rôle. Les clés sont "
                                    "chiffrées, jamais réaffichées.", loaders={"models": models}, facts=llm_facts,
                        describe={"backends": describe_backend},
                        pages=(
                            SettingsPage("fournisseurs", "Fournisseurs", ("backends",), order=10, extra=who_replies,
                                         description=(
                                "Les services qui font tourner ses modèles. Chaque fournisseur a sa page : son "
                                "type, le modèle choisi dans la liste qu'il propose, sa clé ; le reste est rangé "
                                "dans « Options avancées ». Le premier déclaré sert « répondre » d'office.")),
                            SettingsPage("roles", "Qui sert quoi", ("routes",), order=20, extra=routing,
                                         facts=False, description=(
                                             "Chaque rôle (répondre, rêver, retenir, trier le courrier…) choisit "
                                             "son fournisseur. Laisse vide : le rôle retombe sur son repli. "
                                             "« Répondre » est toujours servi : sans choix, par le premier "
                                             "fournisseur déclaré.")),
                        )),
        SettingsSection("images", "Images", "intelligence", ImagingConfig, settings.imaging, save_images, order=120,
                        description="Les fournisseurs qui génèrent ses images, et lequel sert chaque rôle. Aucun "
                                    "fournisseur : elle n'en génère pas. Les clés sont chiffrées, jamais "
                                    "réaffichées.", loaders={"image_models": image_models}, facts=image_facts,
                        pages=(
                            SettingsPage("images-fournisseurs", "Fournisseurs d'images", ("backends",), order=10,
                                         description=(
                                             "OpenAI (son API Images), ou un serveur compatible : le tien, qui "
                                             "fait tourner un modèle sur ta machine, ou un proxy. Le premier "
                                             "déclaré sert « dessiner » d'office. Un repli prend le relais "
                                             "d'une panne, ou de ce que le premier ne sait pas faire ; jamais "
                                             "d'un refus de modération.")),
                            SettingsPage("images-roles", "Qui dessine quoi", ("routes",), order=20,
                                         extra=image_routing, facts=False, description=(
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
                                                     "incarnée), qui elle est, sa langue et l'heure qu'elle vit "
                                                     "(ses nuits, ses salutations en dépendent)."),
                            SettingsPage("parole", "Ton et parole", ("tone", "speech", "greetings", "samples"), order=20,
                                         facts=False, description="Comment elle parle : son ton général, ses "
                                                                  "tournures, le ton de ses bonjours et des "
                                                                  "échanges qui montrent sa voix (des exemples, "
                                                                  "jamais recopiés)."),
                            SettingsPage("caractere", "Caractère",
                                         ("traits", "quirks", "vulnerabilities", "values", "interests"), order=30,
                                         facts=False, description="Ce qui la définit, la touche et la passionne : "
                                                                  "une phrase par ligne."),
                            SettingsPage("vie", "Sa vie", ("life", "tastes", "facts"), order=40, facts=False,
                                         description="Sa vie, rédigée, à sa façon : ce qu'elle fait de ses "
                                                     "journées, ses goûts et avis tranchés, ce qui est vrai d'elle. "
                                                     "Ce qu'elle raconte de son quotidien en découle, et elle ne se "
                                                     "contredit pas d'un jour à l'autre."),
                            SettingsPage("document", "Import / export", order=50, form=False, yaml=True,
                                         commands=True, extra=revisions, description=(
                                             "Le personnage entier en YAML (pour le garder ou le coller d'un "
                                             "coup), le retour au fichier, et l'historique de ses révisions.")),
                        )),
        SettingsSection("autrices", "Autrices", "personnage", authors_m.Authors, settings.authors, save_authors,
                        order=120,
                        head=lambda query: drawn_authors.head(settings.authors(), author_flows(),
                                                              served=polish_served(),
                                                              teams_on=settings.teams().enabled),
                        describe={"authors": lambda key, entry: drawn_authors.describe(
                            key, entry, settings.authors(), dict(author_flows()))},
                        keys={"flows": author_flows},
                        description="Qui récrit ce qui part, et où (ADR 0124) : une autrice par flux — le chat, chaque "
                                    "boîte mail, Teams, le téléphone —, chacune avec ses codes d'écriture. Le sens "
                                    "reste celui du premier jet, la forme change. Toutes écrivent par le modèle du "
                                    "rôle « rendre naturel »."),
        SettingsSection("temperament", "Tempérament", "personnage", Temperament,
                        lambda: live.persona().temperament, save_temperament, order=110,
                        head=lambda query: temper.head(live.persona().temperament, query),
                        prefill=lambda query: temper.prefill(live.persona().temperament, query),
                        description="Sa matrice de personnalité : des curseurs rangés en familles, une humeur de "
                                    "fond, deux choix. L'entrée principale de son caractère ; chaque faculté en dérive "
                                    "ses paramètres (Paramètres avancés), et ce qui s'écarte du milieu se dit au modèle "
                                    "(ADR 0100).",
                        blocks=drives, preview=temperament_effect,
                        pages=(SettingsPage("temperament", "Tempérament", blocks=True, description=(
                            "Des curseurs (0,5 = comme la plupart des gens ; la console s'arrête à 0,1 et 0,9), "
                            "une humeur de fond, sa réaction quand on la blesse et sa défense quand on la touche. "
                            "Chaque faculté en dérive ses paramètres ; la table dessous dit ce que pilote chaque "
                            "curseur, mesuré en le poussant à ses deux bouts. Un trait à 0,3 ou moins, à 0,7 ou "
                            "plus, se dit aussi au modèle (« TON TEMPÉRAMENT »). Un profil les pose tous d'un "
                            "coup : choisis-le en haut, le formulaire s'ouvre sur ses valeurs, rien n'est enregistré "
                            "avant « Enregistrer ».")),)),
        SettingsSection("notifications", "Notifications du téléphone", "canaux", PushSettings,
                        lambda: _tolerant(PushSettings, service_account=settings.push()), save_push, order=20,
                        description="Ce qu'elle écrit à quelqu'un dont l'application est fermée part par Firebase, "
                                    "chiffré pour son seul téléphone (ADR 0077).", facts=push_facts,
                        pages=(SettingsPage("notifications", "Notifications du téléphone", description=(
                            "L'application Android ne garde aucune connexion ouverte quand elle est fermée : ce "
                            "qu'elle écrit à la personne lui arrive en notification par Firebase Cloud Messaging, "
                            "chiffré avec une clé que seul son téléphone connaît (Google ne transporte qu'un "
                            "chiffré). Il faut un projet Firebase où l'application est déclarée, et la clé d'un "
                            "compte de service de ce projet : collée ici, ou posée dans le dossier de données sous "
                            "le nom firebase-service-account.json (droits 600) — collée ici, elle prime. Sans elle, "
                            "l'application ne reçoit que ce qu'elle trouve en s'ouvrant.")),)),
        SettingsSection("depots", "Dépôts git", "canaux", GitSettings, git, save_git,
                        description="Le jeton avec lequel ses projets poussent vers leur dépôt distant.",
                        facts=lambda: [("Jeton", "défini" if settings.git()["token"] else "aucun")],
                        pages=(SettingsPage("depots", "Dépôts git", description=(
                            "Le jeton avec lequel l'atelier d'un projet pousse vers son dépôt distant (GitHub ou un "
                            "autre hôte https) et en récupère l'histoire. L'adresse de chaque dépôt se règle sur la "
                            "fiche du projet (Projets › un projet › Dépôt git). Le jeton ne passe que par "
                            "l'environnement de git, limité à l'hôte du dépôt.")),)),
        SettingsSection("courrier", "Courrier", "sens", MailConfig, settings.email, save_mail,
                        description="Ses boîtes aux lettres (IMAP pour lire et ranger, SMTP pour envoyer) et, pour "
                                    "chacune, sa façon d'y écrire. Relues à chaque relève.", order=10,
                        facts=mail_facts, fixed_names=("accounts",),
                        pages=(SettingsPage("boites", "Boîtes aux lettres", ("accounts",), description=(
                            "Chaque boîte a sa page : lire (IMAP), envoyer (SMTP), sa voix dans cette boîte et ce "
                            "qu'elle y prépare d'elle-même. Ce qui s'y passe se lit dans Courrier.")),)),
        SettingsSection("mcp", "Outils extérieurs", "sens", McpConfig, settings.mcp, save_mcp, order=15,
                        description="Les serveurs MCP dont elle peut utiliser les outils (ADR 0064). Jetons et "
                                    "variables secrètes chiffrés, jamais réaffichés.", facts=mcp_facts,
                        fixed_names=("servers",),
                        pages=(SettingsPage("serveurs-mcp", "Outils extérieurs (MCP)", ("servers",), description=(
                            "Chaque serveur a sa page : d'abord à quoi il sert, pour elle — la ligne de son "
                            "catalogue —, puis où le joindre (une adresse, ou une commande lancée ici, isolée), pour "
                            "qui et quand. Ses outils ne lui sont servis qu'une fois approuvés, un par un, sur la "
                            "fiche du serveur (Outils › Venus d'ailleurs).")),)),
        SettingsSection("reveils", "Réveils par API", "sens", WakeupConfig, settings.wakeup, save_wakeup, order=45,
                        description="Les réveils que des systèmes extérieurs appellent (POST /api/wake/<nom>, ADR "
                                    "0068) : ce qu'ils lui font faire, quand, à qui elle en rend compte. Leurs clés "
                                    "se génèrent sur leur fiche, montrées une seule fois.",
                        facts=wakeup_facts, fixed_names=("endpoints",),
                        choices={"endpoints.project": wake_projects, "endpoints.notify": wake_notify},
                        pages=(SettingsPage("reveils", "Réveils par API", ("endpoints",), description=(
                            "Chaque réveil a sa page : à quoi il sert, ses consignes (elles priment sur le texte "
                            "qu'un appel apporte, qui n'est jamais une consigne), son projet, son mode, ses outils, "
                            "s'il passe outre son sommeil, à qui elle rend compte, ses bornes. Son nom est la fin de "
                            "son URL. Sa clé, ses appels et ce qu'ils ont donné : Connexions "
                            "extérieures › Réveils par API.")),)),
        SettingsSection("flux", "Flux", "sens", FeedsSettings, lambda: FeedsSettings(urls=tuple(settings.feeds())),
                        save_feeds, description="Ce qu'elle lit du monde.", order=20,
                        pages=(SettingsPage("flux", "Flux RSS", description=(
                            "Les flux RSS ou Atom qu'elle relève. Ce qu'elle en remarque se lit dans Connexions "
                            "extérieures › Flux RSS.")),)),
        SettingsSection("transcription", "Transcription", "sens", SttSettings, stt, save_stt, order=30,
                        description="Pour entendre les messages vocaux (un service compatible Whisper).",
                        pages=(SettingsPage("transcription", "Transcription vocale", description=(
                            "Le service qui transcrit les messages vocaux qu'on lui envoie (compatible Whisper). "
                            "Sans lui, un vocal lui arrive comme « un message vocal » sans son contenu.")),)),
        SettingsSection("teams", "Teams", "sens", TeamsConfig, settings.teams, save_teams, order=12,
                        description="Les conversations Teams que l'extension de navigateur lui apporte (ADR 0069), "
                                    "et ce qu'elle fait des réponses qu'elle prépare à ta place.",
                        facts=teams_facts,
                        commands=(Command("cle", "Nouvelle clé", new_teams_key,
                                          confirm="L'ancienne clé ne vaudra plus rien : l'extension devra recevoir "
                                                  "la nouvelle."),
                                  Command("retirer", "Retirer la clé", revoke_teams_key, danger=True,
                                          confirm="L'extension sera refusée jusqu'à une clé neuve.")),
                        pages=(SettingsPage("teams", "Teams", commands=True, description=(
                            "L'extension (frontend/Extension) lit ce que Teams web reçoit dans ton navigateur et "
                            "l'apporte ici, avec cette clé (montrée une seule fois). Ce qu'elle fait de ses "
                            "réponses : un brouillon posé dans Teams (tu l'envoies), un envoi après ton accord, ou "
                            "un envoi sans te demander — toujours sous ton nom. Les conversations et les réponses "
                            "se lisent dans Relations & échanges › Teams.")),)),
        SettingsSection("appareils", "Appareils", "sens", None, order=40,
                        description="Les appareils envoient leurs signaux à POST /api/perceptions, avec ce jeton.",
                        facts=lambda: [("Jeton", "défini" if settings.sensors_token() else "aucun")],
                        commands=(Command("jeton", "Nouveau jeton", new_token,
                                          confirm="L'ancien jeton ne vaudra plus rien."),),
                        pages=(SettingsPage("appareils", "Appareils connectés", commands=True, description=(
                            "Les appareils envoient leurs signaux à POST /api/perceptions avec ce jeton "
                            "(en-tête Authorization: Bearer). Un nouveau jeton se montre une seule fois ; l'ancien "
                            "ne vaut plus rien.")),)),
    )


def _tolerant(cls: type[BaseModel], /, **data: Any) -> Any:
    """Une valeur enregistrée avant qu'une règle existe (un hôte « https://github.com/ ») s'affiche
    quand même, telle quelle : la page reste ouverte pour la corriger ; l'enregistrer la revalide."""
    try:
        return cls(**data)
    except ValidationError:
        return cls.model_construct(**data)


def _num(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3g}".replace(".", ",")
    return str(value)
