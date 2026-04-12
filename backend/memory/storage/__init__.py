"""Memory storage layer — ChromaDB vector store and background consolidation.

Imports are lazy to avoid pulling in chromadb at module load time
(chromadb is not compatible with Python 3.14+).
"""


def __getattr__(name):
    if name == "VectorStore":
        from memory.storage.vector_store import VectorStore
        return VectorStore
    if name == "MemoryConsolidator":
        from memory.storage.consolidator import MemoryConsolidator
        return MemoryConsolidator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["VectorStore", "MemoryConsolidator"]
