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
from collections.abc import Sequence
from functools import cache
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from mika.adapters.imaging.config import ImagingConfig
from mika.adapters.imaging.models import ListingFailed as ImageListingFailed
from mika.adapters.imaging.models import list_image_models
from mika.adapters.llm.config import REPLY, ROLE_LABELS, BackendSpec, LLMConfig
from mika.adapters.llm.models import ListingFailed, list_models
from mika.adapters.mail import MailConfig
from mika.adapters.mcp.config import McpConfig
from mika.adapters.teams import TeamsConfig
from mika.app import persona as persona_file
from mika.app.wakeups import NO_PROJECT, TOOLS, WakeupConfig
from mika.contracts import projects as projects_c
from mika.contracts import self_ as self_c
from mika.contracts import wakeup as wakeup_c
from mika.contracts.self_ import PersonaDoc
from mika.inspector.catalog import Command, SettingsPage, SettingsSection, SettingsTab
from mika.inspector.pages.reglages import effect
from mika.kernel import forms
from mika.kernel.forms import Knob
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Column,
    Nav,
    NavItem,
    Note,
    Ref,
    Row,
    Table,
    Text,
    When,
    int_query,
)
from mika.ports.imaging import DRAW
from mika.ports.imaging import ROLE_LABELS as IMAGE_ROLE_LABELS
from mika.ports.imaging import ROLES as IMAGE_ROLES
from mika.runtime.params import Parameters
from mika.vocab.episodes import FALLBACKS, VOICE_ROLES, Role
from mika.vocab.temperament import Temperament

if TYPE_CHECKING:
    from mika.app.server import Live

log = logging.getLogger("mika.reglages")

#: les rubriques du sous-menu de la configuration, dans l'ordre
TABS = (SettingsTab("intelligence", "Intelligence"), SettingsTab("personnage", "Personnage"),
        SettingsTab("canaux", "Canaux"), SettingsTab("sens", "Plugins"))

#: la famille de chaque rôle (la page « Qui sert quoi »)
ROLE_FAMILIES = {**{str(r): "voix" for r in VOICE_ROLES}, "extract": "mémoire", "validate": "mémoire",
                 "compact": "mémoire", "profile": "compréhension", "interpret": "compréhension",
                 "triage": "sens", "caption": "sens", "plan": "travail", "job": "travail"}

#: une valeur d'une révision de sa persona se montre jusqu'à tant de caractères, repliée au-delà de ``REVISION_CLAMP``
REVISION_VALUE_MAX = 2_000
REVISION_CLAMP = 300


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


def _dump(doc: PersonaDoc) -> str:
    return yaml.safe_dump(doc.model_dump(mode="json"), allow_unicode=True, sort_keys=False, width=100)


def parameters(live: Live) -> Parameters:
    return Parameters(live.kernel, temperament=lambda: live.persona().temperament, overrides=live.settings.overrides,
                      save_overrides=live.settings.save_overrides, inputs=live.inputs, apply=live.reconfigure)


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

    async def back_to_revision(by: str, revision: str) -> tuple[str, str]:
        """Revenir à une révision journalisée : le document entier, enregistré comme une saisie (validation,
        reconfiguration, retour arrière si elle échoue). Une nouvelle révision est journalisée ; l'historique
        ne se réécrit pas."""
        seq = int_query(revision)
        found = live.kernel.mind.store.get_events([seq]) if seq else []
        if not found or found[0].type != self_c.PERSONA_REVISED.name:
            raise ValueError("Révision introuvable : recharge la page.")
        doc = live.kernel.mind.decode(found[0]).data.persona
        if doc == live.persona():
            return "info", "C'est déjà sa persona : rien n'a changé."
        from_file = settings.persona_yaml() is None
        problems = await save_persona(doc, by)
        if problems:
            raise ValueError("; ".join(problems))
        return "ok", ("Sa persona revient à cette version (une nouvelle révision est journalisée, l'historique ne "
                      "change pas)." + (" Elle vient désormais de la console : « Revenir au fichier » rend la main "
                                        "au fichier." if from_file else ""))

    def persona_facts() -> list[tuple[str, str]]:
        if settings.persona_yaml():
            return [("Source", "la console")]
        live.persona()  # relue : le problème du fichier, s'il en a un, est à jour
        if live.persona_problem:
            return [("Source", "sa dernière persona gardée au journal : le fichier ne se lit pas"),
                    ("Le fichier", live.persona_problem)]
        return [("Source", f"le fichier {live.persona_file.name}")]

    def revisions() -> list[Any]:
        """Les révisions de sa persona, de la plus récente : ce que chacune a changé (champ par champ, avant et
        après, dans son détail) et de quoi y revenir."""
        kernel = live.kernel
        stored = kernel.mind.store.latest([self_c.PERSONA_REVISED.name], 200)
        events = [kernel.mind.decode(e) for e in stored]
        described = forms.describe(self_c.PersonaDoc)
        labels = {f.path: f.label for f in described}
        current = live.persona()
        rows = []
        for i, e in enumerate(events):
            doc = e.data.persona.model_dump(mode="json")
            previous = events[i + 1].data.persona if i + 1 < len(events) else None
            before = previous.model_dump(mode="json") if previous is not None else None
            if before is None:
                changed = ["première version"]
            else:
                changed = [labels.get(k, k) for k in doc if doc[k] != before.get(k)] or ["rien (rejournalisée)"]
            back = Note("C'est sa persona actuelle.", "muted") if e.data.persona == current else \
                ActionSlot("personnage.revenir", initial=(("revision", str(e.seq)),), title="Revenir à cette version",
                           presentation="button")
            rows.append(Row((When(e.at), Text(", ".join(changed), clamp=200), Text(str(e.origin.value), "muted")),
                            href=None, detail=(_revision_diff(described, e.data.persona, previous), back)))
        from_file = settings.persona_yaml() is None
        return [Table((Column("quand", "fit"), "ce qui a changé", Column("origine", "fit")), tuple(rows),
                      title=f"Révisions de sa persona ({len(rows)})", empty="Aucune révision journalisée.",
                      caption="Chaque enregistrement du personnage (ou du tempérament) journalise une révision "
                              "complète : son détail montre chaque champ changé, avant et après, et « Revenir à "
                              "cette version » la reprend entière — une nouvelle révision, l'historique ne change "
                              "pas." + (" Sa persona vient aujourd'hui du fichier : revenir à une version la fait "
                                        "venir de la console." if from_file else ""))]

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
                ("État et outils", "Ses outils › Serveurs extérieurs")]

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
                ("Conversations et réponses", "Ses canaux › Teams")]

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
                ("Clés, appels et ce qu'ils ont donné", "Ses canaux › Réveils par API")]

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
                Table(("Plugin", "Ce qui se règle", "Configuration", "Comportement", "Utiliser / consulter"),
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
                            SettingsPage("contexte", "Contexte", ("context_tokens",), order=30, facts=False,
                                         description="La place que le prompt peut occuper : plus grande, elle se "
                                                     "souvient de plus de fil et de souvenirs, pour plus cher."),
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
                                          confirm="La persona rédigée ici sera oubliée ; le fichier fera foi."),
                                  Command("revenir", "Revenir à cette version", back_to_revision, argument="revision",
                                          confirm="Sa persona reprendra cette version entière ; si elle vient du "
                                                  "fichier, elle viendra désormais de la console. Une nouvelle "
                                                  "révision est journalisée, l'historique ne change pas.")),
                        pages=(
                            SettingsPage("identite", "Identité",
                                         ("name", "nature", "description", "language", "timezone"), order=10,
                                         description="Son nom, ce qu'elle est (une IA qui le sait, ou une personne "
                                                     "incarnée), qui elle est, sa langue et l'heure qu'elle vit "
                                                     "(ses nuits, ses salutations en dépendent)."),
                            SettingsPage("parole", "Ton et parole", ("tone", "speech", "greetings"), order=20,
                                         facts=False, description="Comment elle parle : son ton général, ses "
                                                                  "tournures, le ton de ses bonjours (des "
                                                                  "exemples, jamais recopiés)."),
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
                                             "coup), le retour au fichier, et l'historique de ses révisions : ce "
                                             "que chacune a changé, et y revenir.")),
                        )),
        SettingsSection("temperament", "Tempérament", "personnage", Temperament,
                        lambda: live.persona().temperament, save_temperament, order=110,
                        description="Huit curseurs et une humeur de fond : l'entrée principale de son caractère. "
                                    "Chaque faculté en dérive ses paramètres (Comportement).",
                        blocks=drives, preview=temperament_effect,
                        pages=(SettingsPage("temperament", "Tempérament", blocks=True, description=(
                            "Huit curseurs (0,5 = comme la plupart des gens) et une humeur de fond. Chaque "
                            "faculté en dérive ses paramètres ; la table dessous dit ce que pilote chaque "
                            "curseur, mesuré en le poussant à ses deux bouts.")),)),
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
                            "fiche du serveur (Ses outils › Serveurs extérieurs).")),)),
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
                            "son URL. Sa clé, ses appels et ce qu'ils ont donné : Ses canaux › Réveils par "
                            "API.")),)),
        SettingsSection("flux", "Flux", "sens", FeedsSettings, lambda: FeedsSettings(urls=tuple(settings.feeds())),
                        save_feeds, description="Ce qu'elle lit du monde.", order=20,
                        pages=(SettingsPage("flux", "Flux RSS", description=(
                            "Les flux RSS ou Atom qu'elle relève. Ce qu'elle en remarque se lit dans Flux et "
                            "capteurs › Flux.")),)),
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
                            "se lisent dans Ses canaux › Teams.")),)),
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


def _revision_diff(described: Sequence[forms.FormField], doc: PersonaDoc, before: PersonaDoc | None) -> Table:
    """Ce qu'une révision de sa persona a changé, champ par champ (``described`` : les champs de ``PersonaDoc``) :
    la valeur d'avant, celle d'après (la plus ancienne gardée : ce qu'elle disait, sans « avant »)."""
    after = forms.flatten(doc)
    prior = forms.flatten(before) if before is not None else {}
    rows = []
    for f in described:
        if f.kind == "group" or f.path not in after:
            continue
        value = after[f.path]
        if (before is None and value in ("", ())) or (before is not None and value == prior.get(f.path)):
            continue
        label = f"{f.group} · {f.label}" if "." in f.path else f.label
        rows.append((Text(label), _revision_value(f, prior.get(f.path)) if before is not None
                     else Text("—", "muted"), _revision_value(f, value)))
    return Table((Column("champ", "fit"), "avant", "après"), tuple(rows),
                 title="Ce que cette révision a changé" if before is not None else "Ce que disait cette version",
                 empty="Rien : la même persona, rejournalisée.")


def _revision_value(f: forms.FormField, value: Any) -> Text:
    """Une valeur d'une révision, lisible dans une cellule : une liste en phrases séparées par « · », un choix par
    son libellé, un nombre à la française ; coupée au-delà de ``REVISION_VALUE_MAX``."""
    if value is None or value == "" or value == ():
        return Text("(vide)", "muted")
    if isinstance(value, tuple | list):
        text = " · ".join(str(v) for v in value)
    elif isinstance(value, float):
        text = _num(value)
    else:
        raw = forms.as_text(f, value)
        text = next((label for v, label in f.choices if v == raw), raw)
    if len(text) > REVISION_VALUE_MAX:
        text = text[:REVISION_VALUE_MAX] + "…"
    return Text(text, clamp=REVISION_CLAMP)
