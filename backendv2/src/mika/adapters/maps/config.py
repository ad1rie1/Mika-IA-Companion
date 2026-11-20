"""D'où vient la carte de sa position (ADR 0193) : rien (le plan dessiné), un fichier PMTiles du dossier de données, ou
un serveur de carte que le serveur relaie. Le navigateur ne parle qu'à Mika : aucune adresse du dehors ne lui est
donnée, qui dirait où tu es.

Et d'où viennent les lieux, les adresses et les itinéraires de l'écran Carte (ADR 0194) : l'index local des lieux
(``PlacesConfig.index``, rien ne sort), la Géoplateforme de l'IGN pour les adresses, un serveur Valhalla pour les
itinéraires (``RoutingConfig``) — par défaut, ni adresses ni itinéraires : rien ne sort sans le choix d'un opérateur."""

from __future__ import annotations

import os
from pathlib import PurePosixPath
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from mika.kernel.forms import Knob

#: le dossier des cartes, dans le dossier de données : jamais sauvegardé (il se retélécharge)
MAPS_DIR = "cartes"
NONE, FILE, SERVER = "aucune", "fichier", "serveur"
SOURCES = ((NONE, "Aucune : le plan dessiné"), (FILE, "Un fichier PMTiles sur ce serveur"),
           (SERVER, "Un serveur de carte, relayé par ce serveur"))
VECTOR, IMAGE = "vecteur", "image"
KINDS = ((VECTOR, "Vectorielles, au schéma Protomaps"), (IMAGE, "Des images (PNG, JPEG, WebP)"))
#: les marques d'une adresse de tuiles (« …/{z}/{x}/{y}.mvt ») ; sans elles, l'adresse est celle d'une archive PMTiles
MARKS = ("{z}", "{x}", "{y}")


def _under_maps(value: str) -> str:
    """Un chemin du dossier de données, sous ``cartes/`` : ni absolu, ni remontant, ni ailleurs."""
    value = value.strip()
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or ".." in path.parts or path.parts[0] != MAPS_DIR \
            or len(path.parts) < 2:
        raise ValueError(f"un chemin sous {MAPS_DIR}/ du dossier de données ({MAPS_DIR}/france.pmtiles)")
    return str(path)


class MapConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Annotated[Literal["aucune", "fichier", "serveur"], Knob(
        label="Source", choices=SOURCES, advanced=False, order=10,
        help="D'où viennent ses tuiles. Aucune : le plan dessiné, rien ne se charge. Un fichier : une archive PMTiles "
             "posée dans le dossier de données. Un serveur : ce serveur le joint et relaie ses tuiles — le navigateur "
             "ne parle qu'à ce serveur.")] = NONE
    file: Annotated[str, Knob(
        label="Fichier", advanced=False, order=20, only=(("source", (FILE,)),),
        help="L'archive PMTiles, sous cartes/ du dossier de données (une extraction de la carte Protomaps : "
             "deploy/README.md, « La carte de sa position »).")] = f"{MAPS_DIR}/france.pmtiles"
    url: Annotated[str, Knob(
        label="Adresse du serveur", advanced=False, order=30, only=(("source", (SERVER,)),),
        help="Une archive PMTiles (https://…/france.pmtiles, lue par plages), ou des tuiles "
             "(https://…/{z}/{x}/{y}.mvt). Seul ce serveur la joint.")] = ""
    kind: Annotated[Literal["vecteur", "image"], Knob(
        label="Ses tuiles", choices=KINDS, order=40, only=(("source", (SERVER,)),),
        help="Pour une adresse {z}/{x}/{y} : des tuiles vectorielles au schéma Protomaps (le style de la carte les "
             "dessine), ou des images. Une archive PMTiles le dit elle-même.")] = VECTOR
    maxzoom: Annotated[int, Knob(
        label="Zoom le plus fin", lo=0, hi=22, order=50, only=(("source", (SERVER,)),),
        help="Pour une adresse {z}/{x}/{y} : le zoom le plus fin qu'elle sert (au-delà, la carte agrandit le "
             "dernier). Une archive PMTiles le dit elle-même.")] = 15
    assets: Annotated[str, Knob(
        label="Polices et icônes", order=60,
        help="Le dossier des polices et des icônes de la carte vectorielle (protomaps/basemaps-assets : fonts/ et "
             "sprites/), sous cartes/. Absent : une carte sans noms ni icônes.")] = f"{MAPS_DIR}/assets"
    attribution: Annotated[str, Knob(
        label="Mention", order=70,
        help="Ce que la carte affiche toujours dans son coin (OpenStreetMap l'exige).")] = "© OpenStreetMap"

    @field_validator("file", "assets")
    @classmethod
    def _paths(cls, value: str) -> str:
        return _under_maps(value)

    @field_validator("url")
    @classmethod
    def _url(cls, url: str) -> str:
        url = url.strip()
        if not url:
            return url
        parts = urlsplit(url.replace("{", "").replace("}", ""))
        if parts.scheme not in ("http", "https") or not parts.hostname or " " in url:
            raise ValueError("une adresse http(s) complète (https://cartes.exemple.org/france.pmtiles)")
        marks = [m in url for m in MARKS]
        if any(marks) and not all(marks):
            raise ValueError("une adresse de tuiles porte {z}, {x} et {y}")
        return url

    @field_validator("attribution")
    @classmethod
    def _said(cls, text: str) -> str:
        text = " ".join(text.split())[:200]
        return text or "© OpenStreetMap"

    @model_validator(mode="after")
    def _complete(self) -> MapConfig:
        if self.source == SERVER and not self.url:
            raise ValueError("un serveur de carte : son adresse")
        return self

    @property
    def zxy(self) -> bool:
        """Une adresse de tuiles (``{z}/{x}/{y}``), pas une archive PMTiles."""
        return all(m in self.url for m in MARKS)


def _http_url(url: str, example: str) -> str:
    """Une adresse http(s) complète, sans espace, sans ``/`` final (on y ajoute le chemin de l'API)."""
    url = url.strip()
    if not url:
        return url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or " " in url or parts.query or parts.fragment:
        raise ValueError(f"une adresse http(s) complète ({example})")
    return url.rstrip("/")


# ── les lieux et les adresses (ADR 0194) ──
NO_ADDRESSES, GEOPLATEFORME = "aucune", "geoplateforme"
ADDRESS_SOURCES = ((NO_ADDRESSES, "Aucune : rien ne sort"),
                   (GEOPLATEFORME, "La Géoplateforme de l'IGN (la Base Adresse Nationale), relayée par ce serveur"))
#: le service de géocodage de la Géoplateforme (iso-fonctionnel avec l'ancienne API Adresse)
GEOPLATEFORME_URL = "https://data.geopf.fr/geocodage"


class PlacesConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    index: Annotated[str, Knob(
        label="Index des lieux", advanced=False, order=10,
        help="Le fichier SQLite des lieux (points d'intérêt, villes et lieux-dits), sous cartes/ du dossier de "
             "données, que « mika carte lieux » tire de l'extrait OpenStreetMap (avec cuisine, horaires, terrasse…) "
             "ou des tuiles de la carte (deploy/README.md, « La carte de sa position »). On y cherche sans que rien "
             "ne sorte.")] = f"{MAPS_DIR}/lieux.db"
    addresses: Annotated[Literal["aucune", "geoplateforme"], Knob(
        label="Adresses", choices=ADDRESS_SOURCES, advanced=False, order=20,
        help="Où chercher une adresse (un numéro et une rue). La Géoplateforme : ce serveur ne lui envoie que le "
             "texte cherché — jamais la position de la personne, ni rien d'elle.")] = NO_ADDRESSES
    addresses_url: Annotated[str, Knob(
        label="Adresse du géocodage", order=30, only=(("addresses", (GEOPLATEFORME,)),),
        help="Le service de géocodage de la Géoplateforme (son API /search). Seul ce serveur le joint.")] = \
        GEOPLATEFORME_URL

    @field_validator("index")
    @classmethod
    def _path(cls, value: str) -> str:
        return _under_maps(value)

    @field_validator("addresses_url")
    @classmethod
    def _url(cls, url: str) -> str:
        return _http_url(url, GEOPLATEFORME_URL) or GEOPLATEFORME_URL


# ── les itinéraires (ADR 0194) ──
NO_ROUTING, FOSSGIS, VALHALLA = "aucun", "fossgis", "valhalla"
ROUTING_SOURCES = ((NO_ROUTING, "Aucun : pas d'itinéraires"),
                   (FOSSGIS, "Le Valhalla public de FOSSGIS (une demande par seconde, sans garantie)"),
                   (VALHALLA, "Un Valhalla à toi"))
#: le serveur Valhalla public de FOSSGIS (celui d'openstreetmap.org) : ses conditions — au plus une demande par
#: seconde, aucune garantie qu'il réponde — valent pour tout ce serveur ; son adresse n'est écrite qu'ici
FOSSGIS_URL = "https://valhalla1.openstreetmap.de"
FOSSGIS_PER_SECOND = 1.0


class RoutingConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Annotated[Literal["aucun", "fossgis", "valhalla"], Knob(
        label="Itinéraires", choices=ROUTING_SOURCES, advanced=False, order=10,
        help="Qui calcule les itinéraires. Le Valhalla public de FOSSGIS : ses conditions demandent au plus une "
             "demande par seconde (pour tout ce serveur, toutes personnes confondues) et ne garantissent rien ; "
             "chaque trajet est gardé un jour, un trajet redemandé ne repart pas. Un Valhalla à toi : sur le "
             "portable, par exemple (deploy/README.md). Seuls les points du trajet partent.")] = NO_ROUTING
    url: Annotated[str, Knob(
        label="Adresse du serveur", advanced=False, order=20, only=(("source", (VALHALLA,)),),
        help="Ton serveur Valhalla (http://127.0.0.1:8002). Seul ce serveur le joint.")] = ""
    per_second: Annotated[float, Knob(
        label="Demandes par seconde", lo=0.1, hi=100, step=0.1, order=30, only=(("source", (VALHALLA,)),),
        help="Au plus tant de demandes par seconde à ton serveur, pour tout ce serveur.")] = 10.0

    @field_validator("url")
    @classmethod
    def _url(cls, url: str) -> str:
        return _http_url(url, "http://127.0.0.1:8002")

    @field_validator("per_second")
    @classmethod
    def _rate(cls, value: float) -> float:
        if not 0.1 <= value <= 100:
            raise ValueError("entre 0,1 et 100 demandes par seconde")
        return value

    @model_validator(mode="after")
    def _complete(self) -> RoutingConfig:
        if self.source == VALHALLA and not self.url:
            raise ValueError("un Valhalla à toi : son adresse")
        return self

    @property
    def base(self) -> str:
        """L'adresse du serveur réglé ; vide : aucun."""
        return FOSSGIS_URL if self.source == FOSSGIS else self.url if self.source == VALHALLA else ""

    @property
    def rate(self) -> float:
        return FOSSGIS_PER_SECOND if self.source == FOSSGIS else self.per_second


# ── les données touristiques (ADR 0245) ──
#: la base des lieux touristiques et des événements, tenue à jour depuis DATAtourisme : jamais sauvegardée, elle se
#: refait
TOURISM_FILE = f"{MAPS_DIR}/tourisme.db"
#: les départements qu'on synchronise un à un : la métropole (la Corse en 2A et 2B), puis l'outre-mer
DEPARTMENTS: tuple[str, ...] = (
    *(f"{n:02d}" for n in range(1, 20)), "2A", "2B", *(f"{n:02d}" for n in range(21, 96)),
    "971", "972", "973", "974", "975", "976", "977", "978", "984", "986", "987", "988",
)
_DEPARTMENT_SET = frozenset(DEPARTMENTS)
#: tous les départements, d'un mot
ALL_FRANCE = "France"


def department_code(value: str) -> str:
    """Un département tel qu'on le tape (« 59 », « 2a », « 6 ») : son code (« 59 », « 2A », « 06 ») ; inconnu :
    ``ValueError``."""
    text = value.strip().upper()
    if text in ("FRANCE", "TOUT", "TOUS"):
        return ALL_FRANCE
    if text.isdigit() and len(text) == 1:
        text = "0" + text
    if text not in _DEPARTMENT_SET:
        raise ValueError(f"« {value.strip()[:10]} » n'est pas un département (59, 62, 2A, 974…)")
    return text


#: les bornes des réglages des données touristiques, et ce qu'elles demandent
_TOURISM_BOUNDS = {
    "horizon_days": (7, 365, "de 7 à 365 jours"), "night_hour": (0, 23, "une heure de 0 à 23"),
    "per_hour": (1, 1000, "de 1 à 1 000 demandes par heure (la limite de l'API)"),
    "per_second": (0.1, 10, "de 0,1 à 10 demandes par seconde"), "reserve_pct": (0, 90, "de 0 à 90 %"),
    "cell_km": (2, 50, "de 2 à 50 km"), "places_days": (1, 60, "de 1 à 60 jours"),
    "events_days": (1, 30, "de 1 à 30 jours"),
}


class TourismConfig(BaseModel):
    """Les données touristiques de DATAtourisme, en cache par cases autour des personnes : la clé de son API (scellée
    dans les réglages, jamais réaffichée ni écrite au journal ; vide, ``MIKA_DATATOURISME_API_KEY``), les bornes des
    demandes (par heure, par seconde, la réserve gardée au direct), la taille d'une case, combien de temps on garde
    une case (lieux, événements), jusqu'où voir les événements ; et, en option, des départements tenus à jour en
    entier (``zones`` ; vide : aucun), à une heure de la nuit. Relus à chaque usage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_key: Annotated[str, Field(repr=False), Knob(
        label="Clé d'API", secret=True, advanced=False, order=10,
        help="Ta clé personnelle de l'API DATAtourisme (www.datatourisme.fr, « Utiliser les données »). Chiffrée, "
             "jamais réaffichée, jamais écrite au journal ; elle ne part que vers api.datatourisme.fr, dans un en-tête. "
             "Vide : inchangée ; effacée, la variable d'environnement MIKA_DATATOURISME_API_KEY la remplace si elle est "
             "posée, sinon plus rien ne part (la base reste).")] = ""
    per_hour: Annotated[int, Knob(
        label="Demandes par heure", lo=1, hi=1000, advanced=False, order=20,
        help="Au plus tant de demandes à DATAtourisme sur toute heure glissante, pour tout ce serveur (et la "
             "commande mika carte tourisme, qui les compte au même endroit). Son API en permet 1 000.")] = 900
    per_second: Annotated[float, Knob(
        label="Demandes par seconde", lo=0.1, hi=10, step=0.1, order=30,
        help="Au plus tant de demandes par seconde, une à la fois. Son API en permet une dizaine.")] = 8.0
    reserve_pct: Annotated[int, Knob(
        label="Réserve pour le direct (%)", lo=0, hi=90, order=40,
        help="La part des demandes de l'heure gardée à ce qu'une personne ouvre (une case jamais vue, une fiche) : le "
             "réchauffage du soir et la synchronisation des départements ne prennent que le reste.")] = 20
    cell_km: Annotated[int, Knob(
        label="Taille d'une case (km)", lo=2, hi=50, order=50,
        help="On interroge DATAtourisme case par case (jamais sur la position exacte de la personne) : une case "
             "d'à peu près tant de kilomètres de côté, avec ses lieux et ses événements à venir.")] = 10
    places_days: Annotated[int, Knob(
        label="Durée du cache des lieux (jours)", lo=1, hi=60, order=60,
        help="Les lieux d'une case se relisent quand ils ont plus de tant de jours (le réchauffage du soir, ou "
             "quand une personne l'ouvre).")] = 7
    events_days: Annotated[int, Knob(
        label="Durée du cache des événements (jours)", lo=1, hi=30, order=70,
        help="Les événements changent plus vite (des dates s'ajoutent, d'autres s'annulent) : ceux d'une case se "
             "relisent après tant de jours — un : chaque soir, autour des personnes.")] = 1
    horizon_days: Annotated[int, Knob(
        label="Événements à venir (jours)", lo=7, hi=365, order=80,
        help="Jusqu'où voir les événements : ceux qui commencent dans plus de tant de jours ne se lisent pas encore.")] \
        = 90
    zones: Annotated[tuple[str, ...], Knob(
        label="Départements tenus en entier", order=90,
        help="En option : des départements copiés en entier (59, 62, 2A, 974… ; « France » : tous), une fois par "
             "semaine, et ce qui y change chaque nuit — en plus des cases. Vide : aucun (le cache par cases suffit). "
             "Toute la France, c'est des heures de demandes : la première se fait sur le PC (mika carte tourisme, "
             "deploy/README.md).")] = ()
    night_hour: Annotated[int, Knob(
        label="Heure de la synchronisation des départements", lo=0, hi=23, order=100,
        help="Chaque nuit à cette heure (de Paris), pour les départements tenus en entier.")] = 4

    @field_validator("zones", mode="before")
    @classmethod
    def _zones(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            value = value.replace(",", "\n").split()
        if not isinstance(value, list | tuple):
            raise ValueError("une liste de départements")
        codes = [department_code(str(v)) for v in value if str(v).strip()]
        if ALL_FRANCE in codes:
            return (ALL_FRANCE,)
        return tuple(dict.fromkeys(sorted(codes, key=DEPARTMENTS.index)))

    @field_validator("api_key")
    @classmethod
    def _key(cls, value: str) -> str:
        # jamais d'erreur sur la clé : une erreur de pydantic recopie la valeur refusée
        return "".join(str(value).split())[:200]

    @field_validator("horizon_days", "night_hour", "per_hour", "per_second", "reserve_pct", "cell_km", "places_days",
                     "events_days")
    @classmethod
    def _bounds(cls, value: float, info: ValidationInfo) -> float:
        # champ par champ : une erreur sur tout le modèle recopierait toutes ses valeurs, la clé comprise
        lo, hi, said = _TOURISM_BOUNDS[info.field_name or ""]
        if not lo <= value <= hi:
            raise ValueError(said)
        return value

    @property
    def everywhere(self) -> bool:
        """Les départements tenus en entier : toute la France."""
        return self.zones == (ALL_FRANCE,)


# ── le réchauffage des caches (ADR 0245) ──
class WarmConfig(BaseModel):
    """Le réchauffage du soir, partagé par les caches de la carte (DATAtourisme, puis les avis de Google) : à quelle
    heure (de Paris), autour des dernières positions connues des personnes ou non, et des points fixes (« Lille »,
    « 45.90, 6.13 »)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hour: Annotated[int, Knob(
        label="Heure du réchauffage", lo=0, hi=23, advanced=False, order=10,
        help="Chaque soir à cette heure (de Paris), les caches se rafraîchissent autour des points ci-dessous, les "
             "cases les plus vieilles d'abord, sur ce qui reste des quotas (la réserve gardée au direct).")] = 22
    people: Annotated[bool, Knob(
        label="Autour des personnes", advanced=False, order=20,
        help="Autour de la dernière position que le téléphone de chacun a donnée (s'il l'a permis) : seule la case "
             "part vers le service, jamais la position.")] = True
    points: Annotated[tuple[str, ...], Knob(
        label="Points fixes", advanced=False, order=30,
        help="Des endroits à tenir au chaud en plus, un par ligne : une ville de l'index des lieux (Lille, Annecy) "
             "ou des coordonnées (45.90, 6.13).")] = ()

    @field_validator("points", mode="before")
    @classmethod
    def _points(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            value = value.split("\n")
        if not isinstance(value, list | tuple):
            raise ValueError("une liste d'endroits")
        out = [" ".join(str(v).split())[:120] for v in value if str(v).strip()]
        if len(out) > 50:
            raise ValueError("50 points au plus")
        return tuple(dict.fromkeys(out))

    @field_validator("hour")
    @classmethod
    def _hour(cls, value: int) -> int:
        if not 0 <= value <= 23:
            raise ValueError("une heure de 0 à 23")
        return value


#: la clé de DATAtourisme quand le réglage est vide (un service qui la reçoit de son environnement)
TOURISM_KEY_ENV = "MIKA_DATATOURISME_API_KEY"
#: d'où vient la clé en service
KEY_SET, KEY_ENV = "reglage", "environnement"


def _key_of(value: str, env: str) -> tuple[str, str]:
    """La clé en service : celle du réglage d'abord (``KEY_SET``), sinon la variable d'environnement ``env``
    (``KEY_ENV``) ; ``("", "")`` : aucune."""
    if value:
        return value, KEY_SET
    posed = "".join(os.environ.get(env, "").split())[:200]
    return (posed, KEY_ENV) if posed else ("", "")


def tourism_key(cfg: TourismConfig) -> tuple[str, str]:
    """La clé de DATAtourisme en service et d'où elle vient : celle du réglage d'abord (``KEY_SET``), sinon la variable
    d'environnement ``MIKA_DATATOURISME_API_KEY`` (``KEY_ENV``) ; ``("", "")`` : aucune."""
    return _key_of(cfg.api_key, TOURISM_KEY_ENV)


# ── les avis (Google Places, l'API officielle Places (New), ADR 0256) ──
#: le cache des avis : jamais sauvegardé, il se relit
REVIEWS_FILE = f"{MAPS_DIR}/avis.db"
#: la clé de Google quand le réglage est vide (l'environnement du serveur, ou le ``.env`` que lit la commande)
REVIEWS_KEY_ENV = "MIKA_GOOGLE_PLACES_API_KEY"
#: les quotas gratuits de chaque mois, par SKU (la grille de Google, vérifiée le 2026-11-20) : les défauts des plafonds,
#: pour que rien ne soit facturé sans qu'on y touche
FREE_SEARCHES, FREE_DETAILS, FREE_PHOTOS = 1000, 1000, 1000
#: les bornes des réglages des avis, et ce qu'elles demandent
_REVIEWS_BOUNDS = {
    "per_second": (0.1, 10, "de 0,1 à 10 appels par seconde"),
    "per_day": (1, 100_000, "de 1 à 100 000 appels sur 24 heures"),
    "searches_per_month": (0, 1_000_000, "de 0 à 1 000 000 recherches par mois"),
    "details_per_month": (0, 1_000_000, "de 0 à 1 000 000 fiches par mois"),
    "photos_per_month": (0, 1_000_000, "de 0 à 1 000 000 photos par mois"),
    "reserve_pct": (0, 90, "de 0 à 90 %"),
    "cache_days": (1, 90, "de 1 à 90 jours"),
    "cell_km": (1, 20, "de 1 à 20 km"),
    "split_depth": (0, 2, "0, 1 ou 2"),
}


class ReviewsConfig(BaseModel):
    """Les avis de Google Places (l'API officielle Places (New)), en cache par cases autour des personnes : la clé de
    son API (scellée dans les réglages, jamais réaffichée ni écrite au journal ; vide, ``MIKA_GOOGLE_PLACES_API_KEY``),
    les bornes des appels (par seconde, sur 24 heures glissantes, et par mois pour chaque niveau facturé : les
    recherches à proximité, les fiches avec avis, les photos — par défaut, le quota gratuit de chacun), la réserve gardée
    au direct, combien de temps on garde ce qu'on a lu, la taille d'une case et son découpage, le préchargement autour de
    la position, la part au réchauffage du soir. Relus à chaque usage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_key: Annotated[str, Field(repr=False), Knob(
        label="Clé d'API", secret=True, advanced=False, order=10,
        help="Ta clé de l'API Places (New) de Google (console.cloud.google.com, « API et services › Identifiants », sur "
             "un projet où la facturation est ouverte). Restreins-la à « Places API (New) » (restrictions d'API) et, si "
             "tu peux, à l'adresse IP de ce serveur. Chiffrée, jamais réaffichée, jamais écrite au journal ; elle ne "
             "part que vers places.googleapis.com, dans un en-tête. Vide : inchangée ; effacée, la variable "
             "d'environnement MIKA_GOOGLE_PLACES_API_KEY la remplace si elle est posée, sinon plus rien ne part (le "
             "cache reste).")] = ""
    searches_per_month: Annotated[int, Knob(
        label="Recherches à proximité par mois", lo=0, hi=1_000_000, advanced=False, order=20,
        help="Le SKU « Nearby Search Enterprise » : chaque recherche (vingt lieux au plus, une case en coûte une à cinq "
             "par sorte) compte un appel, 1 000 offerts chaque mois puis 35 $ les 1 000. Au plus tant par mois (le "
             "mois de Google, qui commence à minuit, heure du Pacifique) : au-delà, plus rien ne part jusqu'au mois "
             "suivant. Par défaut, le quota offert : rien n'est facturé. 0 : aucune recherche.")] = FREE_SEARCHES
    details_per_month: Annotated[int, Knob(
        label="Fiches avec avis par mois", lo=0, hi=1_000_000, advanced=False, order=30,
        help="Le SKU « Place Details Enterprise + Atmosphere » : la fiche d'un lieu avec ses avis, son résumé, ses "
             "photos (un appel quand on l'ouvre, puis une fois par durée du cache), 1 000 offertes chaque mois puis "
             "25 $ les 1 000. Au plus tant par mois ; par défaut, le quota offert.")] = FREE_DETAILS
    photos_per_month: Annotated[int, Knob(
        label="Photos par mois", lo=0, hi=1_000_000, advanced=False, order=40,
        help="Le SKU « Place Details Photos » : chaque photo montrée la première fois (ensuite, ce serveur la garde), "
             "1 000 offertes chaque mois puis 7 $ les 1 000. Au plus tant par mois ; par défaut, le quota "
             "offert.")] = FREE_PHOTOS
    per_day: Annotated[int, Knob(
        label="Appels sur 24 heures", lo=1, hi=100_000, order=50,
        help="Au plus tant d'appels à Google, tous niveaux confondus, sur toutes 24 heures glissantes, pour tout ce "
             "serveur : un garde-fou si quelque chose s'emballe.")] = 500
    per_second: Annotated[float, Knob(
        label="Appels par seconde", lo=0.1, hi=10, step=0.1, order=60,
        help="Au plus tant d'appels par seconde, espacés.")] = 5.0
    reserve_pct: Annotated[int, Knob(
        label="Réserve pour le direct (%)", lo=0, hi=90, order=70,
        help="La part des appels du jour et de chaque plafond du mois gardée à ce qu'une personne ouvre (la fiche d'un "
             "lieu, une photo, « Actualiser ») : le réchauffage du soir et le préchargement ne prennent que le "
             "reste.")] = 20
    cache_days: Annotated[int, Knob(
        label="Durée du cache (jours)", lo=1, hi=90, advanced=False, order=80,
        help="Ce qu'on a lu (les lieux d'une case, la fiche et les avis d'un lieu) se relit quand il a plus de tant de "
             "jours ; d'ici là, rien ne repart. Au-delà de quatre fois cette durée sans être relu, il s'efface.")] = 7
    cell_km: Annotated[int, Knob(
        label="Taille d'une case (km)", lo=1, hi=20, order=90,
        help="On interroge Google case par case (jamais à la position de la personne) : une case d'à peu près tant de "
             "kilomètres de côté, demandée par sorte (restaurants, à voir, hébergements) dans le cercle qui la couvre "
             "— les vingt lieux les plus connus.")] = 3
    split_depth: Annotated[int, Knob(
        label="Découpage d'une case dense", lo=0, hi=2, order=100,
        help="Google rend vingt lieux au plus par recherche. Quand le cercle d'une case en rend vingt, elle est dense : "
             "on redemande ses quatre quarts (1 : jusqu'à cinq recherches par sorte), puis leurs quarts (2 : jusqu'à "
             "vingt et une). 0 : un cercle par case et par sorte. Plus fin, la liste est plus complète, et coûte "
             "plus.")] = 1
    preload: Annotated[bool, Knob(
        label="Précharger autour de la position", order=110,
        help="Quand le téléphone d'une personne donne sa position (ou qu'elle ouvre « Autour de moi »), la case où "
             "elle se trouve et les huit d'à côté se lisent en fond si elles sont vieilles : seuls leurs cercles "
             "partent, jamais la position.")] = True
    warm: Annotated[bool, Knob(
        label="Réchauffer chaque soir", order=120,
        help="Les avis prennent part au réchauffage du soir (Réchauffage des caches) : les restaurants d'abord, puis "
             "ce qui est à voir, puis les hébergements, les cases les plus vieilles d'abord, puis la fiche des lieux "
             "ouverts depuis un mois, les plus regardés d'abord — sur ce qui reste du jour et du mois.")] = True

    @field_validator("api_key")
    @classmethod
    def _key(cls, value: str) -> str:
        # jamais d'erreur sur la clé : une erreur de pydantic recopie la valeur refusée
        return "".join(str(value).split())[:200]

    @field_validator(*_REVIEWS_BOUNDS)
    @classmethod
    def _bounds(cls, value: float, info: ValidationInfo) -> float:
        # champ par champ : une erreur sur tout le modèle recopierait toutes ses valeurs, la clé comprise
        lo, hi, said = _REVIEWS_BOUNDS[info.field_name or ""]
        if not lo <= value <= hi:
            raise ValueError(said)
        return value


def reviews_key(cfg: ReviewsConfig) -> tuple[str, str]:
    """La clé de Google en service et d'où elle vient : celle du réglage d'abord (``KEY_SET``), sinon la variable
    d'environnement ``MIKA_GOOGLE_PLACES_API_KEY`` (``KEY_ENV``) ; ``("", "")`` : aucune."""
    return _key_of(cfg.api_key, REVIEWS_KEY_ENV)
