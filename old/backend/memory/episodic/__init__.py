"""Étage épisodique — les échanges bruts, trouvables le jour même.

Trois étages de mémoire :

- **Étage 0 — SQL** (`memory.models.Message`) : la vérité, pour toujours.
- **Étage 1 — ici** : les échanges découpés en chunks et indexés dans ChromaDB
  au fil de l'eau (embeddings seuls, aucun LLM). Rien n'est perdu pendant la
  journée, tout est trouvable sémantiquement avant toute extraction. Purgé
  après ``memory.episodic_retention_days`` — sa valeur durable a été promue à
  l'étage 2 entre-temps, et le SQL reste derrière.
- **Étage 2 — curé** (souvenirs/connaissances) : la nuit décide du durable.

La compaction du fil (lot B) ne touche que la fenêtre du modèle, jamais ces
étages : la fenêtre est un cache, pas une archive.
"""

from old.backend.memory.episodic.indexer import EpisodicIndexer  # noqa: F401
