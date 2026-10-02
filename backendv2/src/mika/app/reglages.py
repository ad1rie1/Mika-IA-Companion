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

from mika.adapters.llm.config import ROLE_LABELS, BackendSpec, LLMConfig
from mika.adapters.llm.models import ListingFailed, list_models
from mika.adapters.mail import MailConfig
from mika.contracts import self_ as self_c
from mika.contracts.self_ import PersonaDoc
from mika.inspector.catalog import Command, SettingsPage, SettingsSection, SettingsTab
from mika.kernel import forms
from mika.kernel.forms import Knob
from mika.kernel.inspect import Badge, Column, Nav, NavItem, Note, Ref, Row, Table, Text, When
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


@cache
def timezones() -> tuple[tuple[str, str], ...]:
    """Les fuseaux IANA connus de la machine (Europe/Paris…), triés, et UTC."""
    names = sorted(n for n in zoneinfo.available_timezones() if "/" in n and not n.startswith(("Etc/", "SystemV")))
    return (("UTC", "UTC (temps universel)"), *((n, n.replace("_", " ")) for n in names))


#: un hôte seul (github.com, git.exemple.org:8443) : ni schéma, ni chemin, ni espace
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+(?::[0-9]{1,5})?")


class TelegramSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    token: Annotated[str, Knob(label="Jeton du robot", help="Donné par @BotFather. Vide : pas de robot.",
                               secret=True, advanced=False, order=10)] = ""
    allowed_chats: Annotated[tuple[int, ...], Knob(
        label="Conversations autorisées", help="Un identifiant de conversation par ligne. Vide : seules les "
                                               "propriétaires lui écrivent (en privé).", advanced=False,
        order=20)] = ()
    owners: Annotated[tuple[int, ...], Knob(
        label="Propriétaires", help="Les comptes Telegram (un identifiant par ligne) qu'elle traite comme toi : "
                                    "ils voient ses coulisses, et leur conversation privée est toujours admise.",
        advanced=False, order=30)] = ()
    open_to_all: Annotated[bool, Knob(
        label="Ouvert à tous", help="N'importe qui peut lui écrire, même hors de la liste : à cocher seulement "
                                    "si c'est voulu (chaque message coûte un tour de modèle).", order=40)] = False


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

    def llm_facts() -> list[tuple[str, str]]:
        cfg = settings.llm()
        return [("Passerelle", "configurée" if live.gateway.configured else "aucun modèle : chaque tour échoue "
                 "proprement"), ("Fournisseurs", str(len(cfg.backends))), ("Rôles routés", str(len(cfg.routes)))]

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

    async def back_to_file(by: str) -> tuple[str, str]:
        if settings.persona_yaml() is None:
            return "info", "La persona vient déjà du fichier."
        previous = settings.persona_yaml()
        await settings.save_persona(None)
        problems = await live.reconfigure()
        if problems:
            await settings.save_persona(previous)
            await live.reconfigure()
            raise ValueError("; ".join(problems))
        return "ok", "Retour au fichier : la persona du fichier fait foi (une révision est journalisée)."

    def persona_facts() -> list[tuple[str, str]]:
        return [("Source", "la console" if settings.persona_yaml() else f"le fichier {live.persona_file.name}")]

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

    # ── canaux ──
    def telegram() -> TelegramSettings:
        tg = settings.telegram()
        return TelegramSettings(token=tg["token"], allowed_chats=tuple(tg["allowed_chats"]),
                                owners=tuple(tg["owners"]), open_to_all=tg["open"])

    async def save_telegram(cfg: TelegramSettings, by: str) -> list[str]:
        await settings.save_telegram(token=cfg.token, allowed_chats=list(cfg.allowed_chats), owners=list(cfg.owners),
                                     open_to_all=cfg.open_to_all)
        try:
            await live.stop_telegram()
            await live.start_telegram()
        except Exception as exc:  # noqa: BLE001 — enregistré quand même : l'état du robot le dira
            log.warning("Telegram : redémarrage impossible (%s)", type(exc).__name__)
        return []

    def telegram_facts() -> list[tuple[str, str]]:
        tg = settings.telegram()
        state = live.telegram_state() if tg["token"] else "non configuré"
        access = "ouvert à tous" if tg["open"] else "liste blanche" if tg["allowed_chats"] else \
            "propriétaires seulement" if tg["owners"] else "fermé (personne)"
        return [("Robot", state), ("Accès", access)]

    def telegram_warning() -> list[Any]:
        """Ce que l'accès au robot implique, en tête de page. Fermé par défaut (ADR 0038) : on avertit
        quand il est ouvert à tous, et quand il n'est ouvert à personne (il ne démarre pas)."""
        tg = settings.telegram()
        if not tg["token"]:
            return []
        if tg["open"]:
            return [Note("N'importe qui trouvant le robot peut lui écrire, même hors de la liste (et chaque "
                         "message lui coûte un tour). Décoche « Ouvert à tous » pour réserver l'accès.", "warn",
                         title="Ouvert à tous")]
        if not tg["allowed_chats"] and not tg["owners"]:
            return [Note("Ni conversation autorisée ni propriétaire : le robot ne répond à personne et ne démarre "
                         "pas. Liste les identifiants de conversation, ou ses propriétaires.", "warn",
                         title="Fermé à tous")]
        return []

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

    def plugin_settings() -> list[Any]:
        rows = (
            ("Courrier", "Boîtes, serveurs, identifiants et façon d'écrire", "boites", "email", "courrier/reception"),
            ("Flux RSS", "Adresses des flux suivis", "flux", "rss", "sens/flux"),
            ("Caméra", "Fréquence des regards et durée des observations", "comportement-camera", "", "sens/camera"),
            ("Appareils", "Jeton d'accès des capteurs", "appareils", "", "sens/appareils"),
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
                            SettingsPage("fournisseurs", "Fournisseurs", ("backends",), order=10, description=(
                                "Les services qui font tourner ses modèles. Chaque fournisseur a sa page : son "
                                "type, le modèle choisi dans la liste qu'il propose, sa clé ; le reste est rangé "
                                "dans « Options avancées ».")),
                            SettingsPage("roles", "Qui sert quoi", ("routes",), order=20, extra=routing,
                                         facts=False, description=(
                                             "Chaque rôle (répondre, rêver, retenir, trier le courrier…) choisit "
                                             "son fournisseur. Laisse vide : le rôle retombe sur son repli.")),
                            SettingsPage("contexte", "Contexte", ("context_tokens",), order=30, facts=False,
                                         description="La place que le prompt peut occuper : plus grande, elle se "
                                                     "souvient de plus de fil et de souvenirs, pour plus cher."),
                        )),
        SettingsSection("personnage", "Personnage", "personnage", PersonaDoc, live.persona, save_persona,
                        description="Qui elle est. Chaque enregistrement journalise une révision de sa persona.",
                        exclude=("temperament",), yaml=True, facts=persona_facts,
                        choices={"timezone": timezones},
                        commands=(Command("fichier", "Revenir au fichier", back_to_file, danger=True,
                                          confirm="La persona rédigée ici sera oubliée ; le fichier fera foi."),),
                        pages=(
                            SettingsPage("identite", "Identité", ("name", "description", "language", "timezone"),
                                         order=10, description="Son nom, qui elle est, sa langue et l'heure qu'elle "
                                                               "vit (ses nuits, ses salutations en dépendent)."),
                            SettingsPage("parole", "Ton et parole", ("tone", "speech", "greetings"), order=20,
                                         facts=False, description="Comment elle parle : son ton général, ses "
                                                                  "tournures, le ton de ses bonjours (des "
                                                                  "exemples, jamais recopiés)."),
                            SettingsPage("caractere", "Caractère",
                                         ("traits", "quirks", "vulnerabilities", "values", "interests"), order=30,
                                         facts=False, description="Ce qui la définit, la touche et la passionne : "
                                                                  "une phrase par ligne."),
                            SettingsPage("vie", "Sa vie", ("life", "tastes", "facts"), order=40, facts=False,
                                         description="Sa vie d'IA VTuber, rédigée : ce qu'elle fait à sa façon, "
                                                     "ses goûts et avis tranchés, ce qui est vrai d'elle. Ce "
                                                     "qu'elle raconte de son quotidien en découle, et elle ne se "
                                                     "contredit pas d'un jour à l'autre."),
                            SettingsPage("document", "Import / export", order=50, form=False, yaml=True,
                                         commands=True, extra=revisions, description=(
                                             "Le personnage entier en YAML (pour le garder ou le coller d'un "
                                             "coup), le retour au fichier, et l'historique de ses révisions.")),
                        )),
        SettingsSection("temperament", "Tempérament", "personnage", Temperament,
                        lambda: live.persona().temperament, save_temperament, order=110,
                        description="Huit curseurs et une humeur de fond : l'entrée principale de son caractère. "
                                    "Chaque faculté en dérive ses paramètres (Comportement).",
                        blocks=drives,
                        pages=(SettingsPage("temperament", "Tempérament", blocks=True, description=(
                            "Huit curseurs (0,5 = comme la plupart des gens) et une humeur de fond. Chaque "
                            "faculté en dérive ses paramètres ; la table dessous dit ce que pilote chaque "
                            "curseur, mesuré en le poussant à ses deux bouts.")),)),
        SettingsSection("telegram", "Telegram", "canaux", TelegramSettings, telegram, save_telegram,
                        description="Le robot qui la relie à Telegram. L'enregistrer le redémarre.",
                        facts=telegram_facts, blocks=telegram_warning,
                        pages=(SettingsPage("telegram", "Telegram", blocks=True, description=(
                            "Le robot qui la relie à Telegram : son jeton, qui peut lui écrire, et qui elle traite "
                            "comme toi. L'enregistrer redémarre le robot. Les identifiants se lisent dans "
                            "Identités › Adresses (tg_<nombre>).")),)),
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
