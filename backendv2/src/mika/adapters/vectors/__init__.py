"""Vecteurs : plongements (hachage déterministe, sentence-transformers), un
index SQLite + numpy, et sa carte en trois dimensions (``layout``)."""

from mika.adapters.vectors.embedders import HashEmbedder, SentenceEmbedder
from mika.adapters.vectors.index import SqliteVectorIndex

__all__ = ["HashEmbedder", "SentenceEmbedder", "SqliteVectorIndex"]
