"""Le modèle de plongements de sa mémoire : choisi par la machine, comme ses bases (ADR 0109).

``MIKA_EMBEDDINGS_MODEL`` : un modèle sentence-transformers (défaut : celui de ``SentenceEmbedder``).
``MIKA_EMBEDDINGS_DEVICE`` : ``cpu`` (défaut), ``cuda`` (la carte graphique) ou ``auto``.

Le serveur et la ligne de commande passent par ici : un ``rebuild`` plonge avec le modèle du service, jamais avec
un autre. Changer de modèle ne demande rien d'autre qu'un redémarrage : l'index range ses vecteurs par modèle, et
la mémoire replonge ce qui manque au premier passage.
"""

from __future__ import annotations

import os

from mika.adapters.vectors.embedders import DEFAULT_MODEL, SentenceEmbedder

MODEL_ENV = "MIKA_EMBEDDINGS_MODEL"
DEVICE_ENV = "MIKA_EMBEDDINGS_DEVICE"
DEVICES = ("cpu", "cuda", "auto")


def configured() -> tuple[str, str]:
    """Le modèle et l'appareil que l'environnement demande (un appareil inconnu : le processeur)."""
    model = os.environ.get(MODEL_ENV, "").strip() or DEFAULT_MODEL
    device = os.environ.get(DEVICE_ENV, "").strip().lower() or "cpu"
    return model, device if device in DEVICES else "cpu"


def embedder() -> SentenceEmbedder:
    model, device = configured()
    return SentenceEmbedder(model, device=device)
