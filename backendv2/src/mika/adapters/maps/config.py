"""D'où vient la carte de sa position (ADR 0193) : rien (le plan dessiné), un fichier PMTiles du dossier de données, ou
un serveur de carte que le serveur relaie. Le navigateur ne parle qu'à Mika : aucune adresse du dehors ne lui est
donnée, qui dirait où tu es."""

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
