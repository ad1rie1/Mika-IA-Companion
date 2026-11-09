"""Réglages › Carte et téléphone : les notifications, la carte de sa position, les lieux, les itinéraires."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, ConfigDict, field_validator

from mika.adapters.maps import MapConfig, PlacesConfig, RoutingConfig
from mika.adapters.push import parse_service_account
from mika.app.settings import PUSH_KEY_FILE, push_key_file
from mika.app.settings_sections.common import tolerant
from mika.inspector.catalog import SettingsPage, SettingsSection
from mika.kernel.forms import Knob

if TYPE_CHECKING:
    from mika.app.server import Live


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


def sections(live: Live) -> tuple[SettingsSection, ...]:
    settings = live.settings

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

    return (
        SettingsSection("notifications", "Notifications du téléphone", "carte-telephone", PushSettings,
                        lambda: tolerant(PushSettings, service_account=settings.push()), save_push, order=20,
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
    )
