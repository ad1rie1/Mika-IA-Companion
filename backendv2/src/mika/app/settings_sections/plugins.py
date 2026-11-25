"""Réglages › Plugins : la vue d'ensemble, la transcription, les appareils — et, par leur fiche, les rubriques des
domaines (``ConsolePart.sections``, ADR 0310 : le courrier, Teams, les agendas…). Leurs pages vivent là où l'on s'en
sert (``SettingsPage.home``) ; elles s'enregistrent sous Réglages."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Annotated, Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator

from mika.app.console import FACULTY_LABELS, NAVIGATION
from mika.app.domains import DOMAINS
from mika.app.handmade.tabs import settings as drawn_settings
from mika.app.settings_sections.common import tolerant
from mika.inspector.catalog import Command, SettingsPage, SettingsSection
from mika.inspector.pages.params import faculty_url
from mika.inspector.ui import PREFIX
from mika.kernel.forms import Knob

if TYPE_CHECKING:

    from mika.app.server import Live

log = logging.getLogger("mika.reglages")

#: Réglages › Configuration des plugins : une ligne par paquet de ``plugins/`` (``test_settings_pages`` les compare,
#: pour qu'aucun ne manque), dans l'ordre de la page — ce qui s'y règle, ses pages de réglages, où s'en servir (nom,
#: « destination/onglet »). Une ligne n'est montrée que si son plugin est composé ; ses paramètres avancés, que si sa
#: faculté en a.
_FRAME: dict[str, tuple[str, tuple[str, ...], tuple[str, str] | None]] = {
    "imaging": ("Ses fournisseurs d'images et qui dessine quoi ; sa qualité par défaut, ses quotas",
                ("images-fournisseurs", "images-roles"), ("Ses sens › Dessins", "sens/dessins")),
    "contacts": ("Ce qu'elle se forme de ses contacts à partir de ce qu'elle lit : la période relue, ses bornes, les "
                 "plafonds par jour", (), ("Personnes › Annuaire", "personnes/personnes")),
}
#: l'ordre de la page : une décision de la console, comme son menu — il se dit ici, pour tous les plugins
ORDER = ("email", "teams", "phone", "rss", "web", "mcp", "camera", "imaging", "sensors", "location", "trips", "wakeup",
         "forge", "contacts", "agenda")
#: la ligne de chaque plugin : celles du cadre, puis celles que chaque domaine dit dans sa fiche (``Domain.plugins``,
#: ADR 0310)
_CARDS = {**_FRAME, **{name: card for domain in DOMAINS for name, card in domain.plugins.items()}}
if set(ORDER) != set(_CARDS) or len(_FRAME) + sum(len(d.plugins) for d in DOMAINS) != len(_CARDS):
    raise ValueError("Configuration des plugins : chaque plugin a une ligne, dite une fois, et sa place dans ORDER — "
                     f"{sorted(set(ORDER) ^ set(_CARDS))}")
PLUGINS: dict[str, tuple[str, tuple[str, ...], tuple[str, str] | None]] = {name: _CARDS[name] for name in ORDER}
#: ce qui se branche sans être un plugin (le noyau s'en sert) : (nom, ce qui s'y règle, sa page de réglages)
SERVICES = (("Transcription vocale", "Le service qui transcrit les messages vocaux qu'on lui envoie", "transcription"),
            ("Notifications du téléphone", "Firebase, pour écrire à qui a fermé l'application Android",
             "notifications"))


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

    def stt() -> SttSettings:
        got = settings.stt()
        return tolerant(SttSettings, base_url=got["base_url"], model=got["model"], api_key=got["api_key"])

    async def save_stt(cfg: SttSettings) -> list[str]:
        await settings.save_stt(cfg.base_url, cfg.api_key, cfg.model or "whisper-1")
        return []

    async def new_token() -> tuple[str, str]:
        token = await settings.new_sensors_token()
        return "ok", f"Jeton neuf (l'ancien ne vaut plus ; montré une seule fois) : {token}"

    return (
        # Transcription et Appareils : dans Ses sens, derrière sa roue (ADR 0206), avec ses flux suivis (leur rubrique :
        # app/domains/senses/console/settings.py)
        SettingsSection("transcription", "Transcription", "plugins", SttSettings, stt, save_stt, order=30,
                        description="Pour entendre les messages vocaux (un service compatible Whisper).",
                        pages=(SettingsPage("transcription", "Transcription vocale", description=(
                            "Le service qui transcrit les messages vocaux qu'on lui envoie (compatible Whisper). "
                            "Sans lui, un vocal lui arrive comme « un message vocal » sans son contenu."),
                            home="sens/parametres-transcription"),)),
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
