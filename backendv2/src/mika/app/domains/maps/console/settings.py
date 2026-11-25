"""Ses rubriques de réglages (ADR 0193, 0194, 0245, 0256, 0310), dans Réglages › Carte et téléphone : la carte de sa
position, les lieux et les adresses, les itinéraires, les données touristiques (DATAtourisme), les avis (Google) et le
réchauffage des caches. Les notifications du téléphone, dans le même onglet, restent au cadre
(``app/settings_sections/map_phone.py``)."""

from __future__ import annotations

from typing import Any

from mika.adapters.maps import (
    MapConfig,
    PlacesConfig,
    ReviewsConfig,
    RoutingConfig,
    TourismConfig,
    WarmConfig,
)
from mika.app.domains.maps.settings import MapsSettings
from mika.inspector.catalog import Command, SettingsPage, SettingsSection


def sections(live: Any) -> tuple[SettingsSection, ...]:
    """Ses rubriques, pour ce serveur (``live`` : ses réglages ; le port ``maps`` du noyau ; les tuiles du fond de
    carte, ``live.parts["tiles"]``)."""
    settings = live.settings.of(MapsSettings)

    # ── la carte de sa position (ADR 0193) ──
    async def save_map(cfg: MapConfig) -> list[str]:
        await settings.save_map_config(cfg)
        return []

    def map_facts() -> list[tuple[str, str]]:
        tiles = live.parts.get("tiles")
        return tiles.describe() if tiles is not None else [("Source", "la carte n'est pas branchée")]

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

    # ── les données touristiques et les événements (DATAtourisme, ADR 0245) ──
    async def save_tourism(cfg: TourismConfig) -> list[str]:
        await settings.save_tourism_config(cfg)
        return []

    def tourism_facts() -> list[tuple[str, str]]:
        desk = maps_desk()
        return desk.describe_tourism() if desk is not None else [("Données touristiques",
                                                                   "pas branchées sur ce serveur")]

    async def sync_tourism() -> tuple[str, str]:
        desk = maps_desk()
        return await desk.sync_now() if desk is not None else ("danger", "La carte n'est pas branchée ici.")

    # ── les avis (Google Places, ADR 0256) ──
    async def save_reviews(cfg: ReviewsConfig) -> list[str]:
        await settings.save_reviews_config(cfg)
        return []

    def reviews_facts() -> list[tuple[str, str]]:
        desk = maps_desk()
        return desk.describe_reviews() if desk is not None else [("Avis", "pas branchés sur ce serveur")]

    # ── le réchauffage du soir des caches de la carte (ADR 0245) ──
    async def save_warm(cfg: WarmConfig) -> list[str]:
        await settings.save_warm_config(cfg)
        return []

    def warm_facts() -> list[tuple[str, str]]:
        desk = maps_desk()
        return desk.describe_warm() if desk is not None else [("Réchauffage", "pas branché sur ce serveur")]

    async def warm_now() -> tuple[str, str]:
        desk = maps_desk()
        return desk.warmer.wake() if desk is not None else ("danger", "La carte n'est pas branchée ici.")

    return (
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
                            "dans un index que « mika carte lieux » tire de l'extrait OpenStreetMap de Geofabrik (un "
                            "fichier SQLite sous cartes/, fait sur le PC puis copié : deploy/README.md, « Les lieux, "
                            "les adresses et les itinéraires de l'écran Carte ») : par le nom, autour d'un point, dans "
                            "une zone, le long d'un trajet, avec la cuisine, les horaires et les filtres d'une liste, "
                            "et la fiche d'un lieu, sans que rien ne sorte. Il se refait sur un extrait plus récent, "
                            "jamais avec la carte ; à défaut d'extrait, des tuiles de la carte, sans ces détails. Une "
                            "adresse (un numéro et une rue) "
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
        SettingsSection("tourisme", "Données touristiques (DATAtourisme)", "carte-telephone", TourismConfig,
                        settings.tourism_config, save_tourism, order=28, facts=tourism_facts,
                        commands=(Command("synchroniser", "Synchroniser maintenant", sync_tourism),),
                        description="Les lieux touristiques et les événements des offices de tourisme, par "
                                    "DATAtourisme : un cache sur ce serveur, par cases, autour des personnes, où "
                                    "l'écran Carte et ses outils cherchent sans que rien ne sorte.",
                        pages=(SettingsPage("tourisme", "Données touristiques (DATAtourisme)", commands=True,
                                            description=(
                            "Les fiches des offices de tourisme — musées, sites, restaurants, hébergements, et les "
                            "événements à venir : concerts, spectacles, expositions, marchés… — viennent de "
                            "DATAtourisme (Licence Ouverte 2.0 : chaque fiche cite son auteur et sa date, chaque "
                            "photo son crédit et sa licence). Ce serveur les copie dans une base à lui "
                            "(cartes/tourisme.db, jamais sauvegardée : elle se refait) avec ta clé de leur API, qui "
                            "ne part que vers eux : case par case — une case d'une dizaine de kilomètres, jamais la "
                            "position de la personne —, chaque soir autour des personnes (Réchauffage des caches), "
                            "et tout de suite quand quelqu'un ouvre une case jamais vue, si le quota le permet. "
                            "Chercher un lieu ou un événement ne fait ensuite rien sortir. Les demandes sont "
                            "comptées (par heure, par seconde) ; une réserve reste à ce qu'une personne ouvre. En "
                            "option, des départements entiers, chaque nuit et chaque semaine. Une fiche se rapproche "
                            "du lieu d'OpenStreetMap qui est le sien (sa fiche l'enrichit), et un événement du lieu "
                            "nommé où il se tient. Sans clé, rien ne part et l'écran Carte le dit.")),)),
        SettingsSection("avis", "Avis (Google)", "carte-telephone", ReviewsConfig, settings.reviews_config,
                        save_reviews, order=29, facts=reviews_facts,
                        description="Les notes, les avis et les photos de Google Maps, par l'API officielle Places "
                                    "(New) : un cache sur ce serveur, par cases, autour des personnes, où l'écran "
                                    "Carte et ses outils lisent sans que rien ne sorte ; chaque appel est compté, et "
                                    "par défaut rien ne dépasse le quota offert chaque mois.",
                        pages=(SettingsPage("avis", "Avis (Google)", description=(
                            "La note, le nombre d'avis, le prix, les horaires, les avis en français, le résumé et les "
                            "photos des restaurants, de ce qui est à voir et des hébergements viennent de l'API "
                            "officielle Places (New) de Google, avec ta clé, qui ne part que vers elle — rien d'autre "
                            "n'est lu de Google. Ce serveur les garde dans un cache à lui (cartes/avis.db, jamais "
                            "sauvegardé : il se relit) case par case — une case de quelques kilomètres, demandée par "
                            "le cercle qui la couvre, jamais à la position de la personne : par sorte, les vingt "
                            "lieux les plus connus, et ceux de ses quarts quand elle est dense. La fiche d'un lieu lit "
                            "en direct ce qui lui manque (le lieu cherché tout près de lui, puis sa fiche avec ses "
                            "avis), sur la réserve gardée au direct ; une liste ne lit que le cache. Google facture "
                            "chaque appel selon les champs demandés : une recherche pour une liste (Nearby Search "
                            "Enterprise), la fiche avec ses avis (Place Details Enterprise + Atmosphere), une photo "
                            "(Place Details Photos) — 1 000 de chaque offertes chaque mois ; les plafonds sont réglés "
                            "là-dessus, et le cache est gardé sept jours. Ces comptes sont ceux de ce dossier de "
                            "données (cartes/quotas.db, qui part avec la sauvegarde) : Google compte, lui, par compte "
                            "de facturation — la même clé sur un autre serveur, ou dans le .env d'un poste, puise dans "
                            "le même quota offert sans que ce serveur le voie ; prends une clé à part pour un autre "
                            "serveur ou un poste de développement (un autre projet Google), ou baisse ses plafonds. "
                            "Ses conditions ne permettent de garder que "
                            "l'identifiant d'un lieu : tu as choisi de garder ce cache et de le lui faire lire, sous "
                            "ta responsabilité (ADR 0256) ; la mention « Google Maps », le lien vers la page du "
                            "lieu et le nom et le lien de l'auteur de chaque avis et de chaque photo restent toujours "
                            "avec. Dans Google Cloud, restreins ta clé à « Places API (New) ». Sans clé, rien ne part "
                            "et l'écran Carte le dit.")),)),
        SettingsSection("rechauffage", "Réchauffage des caches", "carte-telephone", WarmConfig, settings.warm_config,
                        save_warm, order=30, facts=warm_facts,
                        commands=(Command("rechauffer", "Réchauffer maintenant", warm_now),),
                        description="Chaque soir, les caches de la carte (les données touristiques, puis les avis) "
                                    "se rafraîchissent autour des personnes, sur ce qui reste de leurs quotas.",
                        pages=(SettingsPage("rechauffage", "Réchauffage des caches", commands=True, description=(
                            "Chaque soir à l'heure dite, ce serveur rafraîchit ou crée les caches de la carte autour "
                            "de la dernière position connue de chaque personne qui l'a permise (seule la case part "
                            "vers le service, jamais la position) et des points fixes réglés ici : les cases les "
                            "plus vieilles d'abord, chaque source dans son ordre (DATAtourisme : les événements à "
                            "venir, puis les lieux ; Google : les restaurants, puis ce qui est à voir, puis les "
                            "hébergements, puis la fiche des lieux ouverts depuis un mois, les plus regardés "
                            "d'abord), sur ce qui reste de son quota — sa réserve est gardée à ce qu'une personne "
                            "ouvre. Un passage dure au plus huit heures ; ce qui reste attend le "
                            "soir suivant.")),)),
    )
