"""Choix dynamiques — un champ dont les options viennent d'une source vivante.

Certains champs ne peuvent pas déclarer leurs options au registre : elles
dépendent d'un autre champ du même formulaire **et** d'un appel réseau. Le cas
qui motive ce module est celui que le schéma décrit lui-même
(``ai/config_schema.py``) : « choisir le fournisseur → charger la liste via le
SDK / l'API → sélectionner → nommer ». L'utilisateur ne doit jamais taper un
identifiant de modèle à la main — une faute de frappe ne se voit qu'au premier
appel IA, bien plus tard et bien plus loin.

**Le chargement est explicite, jamais implicite.** Résoudre les options à
chaque affichage du formulaire ferait un appel réseau vers le fournisseur pour
ouvrir une page — lent, dépendant de la disponibilité d'un service tiers, et
inutile neuf fois sur dix. C'est donc un bouton, et le tout se fait par un
aller-retour serveur ordinaire : pas de JavaScript, et le formulaire reste
utilisable si le script ne charge pas.

**Le champ reste saisissable si le chargement échoue.** Un fournisseur
injoignable ne doit pas rendre la configuration impossible à réparer — c'est
précisément le moment où on vient la corriger.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

# (options, message d'erreur) — l'un des deux est toujours vide.
Loader = Callable[[dict], "tuple[list[tuple[str, str]], str]"]


@dataclass(frozen=True)
class DynamicField:
    """Un champ dont les options se chargent à la demande.

    ``depends_on`` nomme le champ qui pilote le chargement : le gabarit s'en
    sert pour expliquer pourquoi le bouton est là, et la vue pour refuser un
    chargement quand ce champ est vide.
    """
    parent_key: str          # clé de la record_list (ex. "ai.models")
    field_key: str           # champ à remplir (ex. "model_id")
    depends_on: str          # champ pilote (ex. "provider")
    button_label: str
    empty_message: str
    loader: Loader


_REGISTRY: dict[str, DynamicField] = {}


def register(field: DynamicField) -> None:
    _REGISTRY[field.parent_key] = field


def for_list(parent_key: str) -> DynamicField | None:
    return _REGISTRY.get(parent_key)


def load(parent_key: str, payload: dict) -> tuple[list[tuple[str, str]], str]:
    """Charge les options pour une saisie en cours.

    Renvoie ``(options, erreur)``. Une erreur est un message destiné à
    l'écran, jamais une exception : le formulaire doit se réafficher avec ce
    que l'utilisateur a déjà tapé.
    """
    field = _REGISTRY.get(parent_key)
    if field is None:
        return [], ""
    pilote = str(payload.get(field.depends_on) or "").strip()
    if not pilote:
        return [], field.empty_message
    try:
        return field.loader(payload)
    except Exception as exc:
        logger.warning("chargement des options %s en échec : %s", parent_key, exc)
        return [], f"Chargement impossible : {exc}"


# ── Modèles d'un fournisseur IA ─────────────────────────────────────────

def _load_provider_models(payload: dict) -> tuple[list[tuple[str, str]], str]:
    """Interroge le fournisseur sélectionné avec les identifiants enregistrés.

    Simple aiguillage : chaque fournisseur implémente ``list_models()``
    lui-même, et son ``__init__`` lit ses identifiants depuis le service de
    configuration. Aucun code spécifique à un SDK ne vit ici — cela appartient
    à ``ai/providers/<nom>_provider.py``.
    """
    from asgiref.sync import async_to_sync

    from ai.router import _PROVIDER_CLASSES

    nom = str(payload.get("provider") or "").strip().lower()
    if nom not in _PROVIDER_CLASSES:
        return [], (
            f"Fournisseur inconnu « {nom} ». Disponibles : "
            + ", ".join(sorted(_PROVIDER_CLASSES))
        )

    try:
        instance = _PROVIDER_CLASSES[nom]()
        modeles = async_to_sync(instance.list_models)()
    except ImportError as exc:
        return [], f"SDK manquant pour {nom} : {exc}"

    options = [
        (str(m.get("id", "")), str(m.get("label") or m.get("id", "")))
        for m in (modeles or [])
        if m.get("id")
    ]
    if not options:
        return [], (
            f"{nom} n'a renvoyé aucun modèle. Vérifie la clé d'API dans "
            "« IA · Providers » (ou, pour Ollama, que le serveur répond)."
        )
    options.sort(key=lambda o: o[1].lower())
    return options, ""


register(DynamicField(
    parent_key="ai.models",
    field_key="model_id",
    depends_on="provider",
    button_label="Charger les modèles du fournisseur",
    empty_message="Choisis d'abord un fournisseur, puis charge la liste.",
    loader=_load_provider_models,
))
