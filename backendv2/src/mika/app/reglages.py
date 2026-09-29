"""Les réglages d'exploitation, déclarés : ce qu'un opérateur décide, et où.

Chaque section apporte un modèle (le formulaire en sort), sa valeur actuelle
et de quoi l'enregistrer ; la console les rend toutes de la même façon
(``inspector/pages/settings_form.py``). Un enregistrement qui échoue au
rechargement est défait : on ne laisse pas une configuration à moitié prise.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from mika.adapters.llm.config import BackendSpec, LLMConfig
from mika.adapters.llm.models import ListingFailed, list_models
from mika.adapters.mail import MailConfig
from mika.contracts.self_ import PersonaDoc
from mika.inspector.catalog import Command, SettingsSection, SettingsTab
from mika.kernel import forms
from mika.kernel.forms import Knob
from mika.kernel.inspect import Column, Table, Text
from mika.runtime.params import Parameters
from mika.vocab.temperament import Temperament

if TYPE_CHECKING:
    from mika.app.server import Live

log = logging.getLogger("mika.reglages")

TABS = (SettingsTab("modeles", "Modèles"), SettingsTab("personnalite", "Personnalité"),
        SettingsTab("canaux", "Canaux"), SettingsTab("sens", "Sens"))


class TelegramSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    token: Annotated[str, Knob(label="Jeton du robot", help="Donné par @BotFather. Vide : pas de robot.",
                               secret=True, advanced=False, order=10)] = ""
    allowed_chats: Annotated[tuple[int, ...], Knob(
        label="Conversations autorisées", help="Un identifiant de conversation par ligne ; vide : tout le monde "
                                               "peut lui écrire.", advanced=False, order=20)] = ()
    owners: Annotated[tuple[int, ...], Knob(
        label="Propriétaires", help="Les comptes Telegram (un identifiant par ligne) qu'elle traite comme toi : "
                                    "ils voient ses coulisses.", advanced=False, order=30)] = ()


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
    model: Annotated[str, Knob(label="Modèle", advanced=False, order=20)] = "whisper-1"
    api_key: Annotated[str, Knob(label="Clé d'API", secret=True, advanced=False, order=30)] = ""


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

    def llm_facts() -> list[tuple[str, str]]:
        cfg = settings.llm()
        return [("Passerelle", "configurée" if live.gateway.configured else "aucun modèle : chaque tour échoue "
                 "proprement"), ("Fournisseurs", str(len(cfg.backends))), ("Rôles routés", str(len(cfg.routes)))]

    # ── personnalité ──
    async def save_persona(doc: PersonaDoc, by: str) -> list[str]:
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
                                owners=tuple(tg["owners"]))

    async def save_telegram(cfg: TelegramSettings, by: str) -> list[str]:
        await settings.save_telegram(token=cfg.token, allowed_chats=list(cfg.allowed_chats), owners=list(cfg.owners))
        try:
            await live.stop_telegram()
            await live.start_telegram()
        except Exception as exc:  # noqa: BLE001 — enregistré quand même : l'état du robot le dira
            log.warning("Telegram : redémarrage impossible (%s)", type(exc).__name__)
        return []

    def telegram_facts() -> list[tuple[str, str]]:
        tg = settings.telegram()
        state = "en marche" if live.telegram is not None else ("arrêté" if tg["token"] else "non configuré")
        return [("Robot", state), ("Accès", "liste blanche" if tg["allowed_chats"] else "ouvert à tous")]

    # ── sens ──
    async def save_mail(cfg: MailConfig, by: str) -> list[str]:
        await settings.save_email(**cfg.model_dump())
        return []

    async def save_feeds(cfg: FeedsSettings, by: str) -> list[str]:
        await settings.save_feeds(list(cfg.urls))
        return []

    def stt() -> SttSettings:
        got = settings.stt()
        return SttSettings(base_url=got["base_url"], model=got["model"], api_key=got["api_key"])

    async def save_stt(cfg: SttSettings, by: str) -> list[str]:
        await settings.save_stt(cfg.base_url, cfg.api_key, cfg.model or "whisper-1")
        return []

    async def new_token(by: str) -> tuple[str, str]:
        token = await settings.new_sensors_token()
        return "ok", f"Jeton neuf (l'ancien ne vaut plus ; montré une seule fois) : {token}"

    return (
        SettingsSection("modeles", "Modèles", "modeles", LLMConfig, settings.llm, save_llm,
                        description="Les fournisseurs de modèles, et lequel sert chaque rôle. Les clés sont "
                                    "chiffrées, jamais réaffichées.", loaders={"models": models}, facts=llm_facts),
        SettingsSection("personnage", "Personnage", "personnalite", PersonaDoc, live.persona, save_persona,
                        description="Qui elle est. Chaque enregistrement journalise une révision de sa persona.",
                        exclude=("temperament",), yaml=True, facts=persona_facts,
                        commands=(Command("fichier", "Revenir au fichier", back_to_file, danger=True,
                                          confirm="La persona rédigée ici sera oubliée ; le fichier fera foi."),)),
        SettingsSection("temperament", "Tempérament", "personnalite", Temperament,
                        lambda: live.persona().temperament, save_temperament, order=110,
                        description="Huit curseurs et une humeur de fond : l'entrée principale de son caractère. "
                                    "Chaque faculté en dérive ses paramètres (Paramètres internes).",
                        blocks=drives),
        SettingsSection("telegram", "Telegram", "canaux", TelegramSettings, telegram, save_telegram,
                        description="Le robot qui la relie à Telegram. L'enregistrer le redémarre.",
                        facts=telegram_facts),
        SettingsSection("courrier", "Courrier", "sens", MailConfig, settings.email, save_mail,
                        description="Sa boîte aux lettres (IMAP pour lire, SMTP pour envoyer), relue à chaque "
                                    "relève.", order=10,
                        facts=lambda: [("Boîte", "prête" if settings.email().ready else "incomplète")]),
        SettingsSection("flux", "Flux", "sens", FeedsSettings, lambda: FeedsSettings(urls=tuple(settings.feeds())),
                        save_feeds, description="Ce qu'elle lit du monde.", order=20),
        SettingsSection("transcription", "Transcription", "sens", SttSettings, stt, save_stt, order=30,
                        description="Pour entendre les messages vocaux (un service compatible Whisper)."),
        SettingsSection("appareils", "Appareils", "sens", None, order=40,
                        description="Les appareils envoient leurs signaux à POST /api/perceptions, avec ce jeton.",
                        facts=lambda: [("Jeton", "défini" if settings.sensors_token() else "aucun")],
                        commands=(Command("jeton", "Nouveau jeton", new_token,
                                          confirm="L'ancien jeton ne vaudra plus rien."),)),
    )


def _num(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.3g}".replace(".", ",")
    return str(value)
