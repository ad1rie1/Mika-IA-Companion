"""Réglages › Plugins : la vue d'ensemble, le courrier, les serveurs MCP, les réveils, les flux, la transcription, Teams,
les appareils. Leurs pages vivent là où l'on s'en sert (``SettingsPage.home``) ; elles s'enregistrent sous Réglages."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlencode, urlsplit

from pydantic import BaseModel, ConfigDict, field_validator

from mika.adapters.mail import MailConfig
from mika.adapters.mail.config import MailAccount
from mika.adapters.mcp.config import McpConfig
from mika.adapters.teams import TeamsConfig
from mika.app.console import FACULTY_LABELS, NAVIGATION
from mika.app.handmade import ago
from mika.app.handmade.tabs import settings as drawn_settings
from mika.app.settings_sections.common import tolerant
from mika.app.wakeups import NO_PROJECT, TOOLS, WakeupConfig
from mika.contracts import identity as identity_c
from mika.contracts import projects as projects_c
from mika.contracts import self_ as self_c
from mika.contracts import wakeup as wakeup_c
from mika.inspector.catalog import Command, SettingsPage, SettingsSection
from mika.inspector.pages.params import faculty_url
from mika.inspector.pages.settings_form import RECORD_KEY
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import PREFIX
from mika.kernel.forms import Knob
from mika.kernel.inspect import Ref
from mika.plugins.email.console.common import VOICE_LABEL
from mika.vocab.access import PERSON, SELF

if TYPE_CHECKING:
    from mika.app.server import Live

log = logging.getLogger("mika.reglages")

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


def sections(live: Live) -> tuple[SettingsSection, ...]:
    settings = live.settings

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
                "fiche": fiche_url("compte", key), "box": f"{PREFIX}/courrier/reception?" + urlencode({"compte": key})}

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
        return tolerant(SttSettings, base_url=got["base_url"], model=got["model"], api_key=got["api_key"])

    async def save_stt(cfg: SttSettings) -> list[str]:
        await settings.save_stt(cfg.base_url, cfg.api_key, cfg.model or "whisper-1")
        return []

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

    return (
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


def overview(live: Live, declared: tuple[SettingsSection, ...]) -> SettingsSection:
    """La section « Configuration des plugins » : sa page d'en-tête dessinée lit les pages de toutes les autres."""

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

    # dessinée (handmade/reglages/plugins.html) : une ligne par plugin composé, sans pagination
    return SettingsSection("plugins", "Plugins", "plugins", None, order=0,
                           head=lambda query: drawn_settings.plugins(plugin_rows()),
                           pages=(SettingsPage("plugins", "Vue d'ensemble des plugins", form=False,
                                               description="Chaque plugin : où se règle sa connexion, ses paramètres "
                                                           "avancés, et où s'en servir."),))
