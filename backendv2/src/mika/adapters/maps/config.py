"""D'où vient la carte de sa position (ADR 0193) : rien (le plan dessiné), un fichier PMTiles du dossier de données, ou
un serveur de carte que le serveur relaie. Le navigateur ne parle qu'à Mika : aucune adresse du dehors ne lui est
donnée, qui dirait où tu es.

Et d'où viennent les lieux, les adresses et les itinéraires de l'écran Carte (ADR 0194) : l'index local des lieux
(``PlacesConfig.index``, rien ne sort), la Géoplateforme de l'IGN pour les adresses, un serveur Valhalla pour les
itinéraires (``RoutingConfig``) — par défaut, ni adresses ni itinéraires : rien ne sort sans le choix d'un opérateur."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

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
             "données, que « mika carte lieux » tire des tuiles de la carte (deploy/README.md, « La carte de sa "
             "position »). On y cherche sans que rien ne sorte.")] = f"{MAPS_DIR}/lieux.db"
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
