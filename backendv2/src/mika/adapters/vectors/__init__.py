"""Vecteurs : plongements (hachage déterministe, sentence-transformers) et un
index SQLite + numpy."""

from mika.adapters.vectors.embedders import HashEmbedder, SentenceEmbedder
from mika.adapters.vectors.index import SqliteVectorIndex

__all__ = ["HashEmbedder", "SentenceEmbedder", "SqliteVectorIndex"]
