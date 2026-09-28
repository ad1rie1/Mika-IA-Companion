"""Deux plongements.

- ``HashEmbedder`` : l'astuce du hachage sur des mots et des trigrammes de
  caractères, repliés (casse, accents). Déterministe à l'octet, instantané,
  indépendant de ``PYTHONHASHSEED`` : celui du simulateur et des tests. Il ne
  comprend pas le sens, seulement le recouvrement de vocabulaire.
- ``SentenceEmbedder`` : un modèle sentence-transformers (multilingue par
  défaut), chargé à la première demande dans un fil dédié ; les calculs du
  modèle relâchent le verrou global, la boucle continue de répondre.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence
from typing import Any

_WORD = re.compile(r"[a-z0-9]+")
#: Les mots qui ne disent rien du sujet (repliés, sans accents) : sans eux,
#: « tu te souviens de ce que je t'ai dit pour samedi » ressemble surtout à
#: toute phrase contenant « dit » ou « pour ».
STOPWORDS = frozenset("""
les des une uns aux que qui quoi dont pour par sur sous dans avec sans chez entre vers mais donc car pas plus moins
tres trop bien tout tous toute toutes cette ces son sa ses mon ma mes ton ta tes leur leurs notre nos votre vos
est sont suis etais etait ete etre avoir avais avait ont fait faire dit dire dis vais vas va aller peu peut peux
elle elles lui ils nous vous moi toi ceux celle cela ceci comme quand alors aussi encore deja meme autre autres
quelque chose rien oui non bon bah ben hein ouais cest jai tai quil quelle souviens rappelles rappelle sais
""".split())


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


class HashEmbedder:
    def __init__(self, dims: int = 256) -> None:
        self.dims = dims
        self.name = f"hash-{dims}"

    def _features(self, text: str) -> list[str]:
        words = [w for w in _WORD.findall(_fold(text)) if len(w) > 2 and w not in STOPWORDS]
        feats = [f"w:{w[:6]}" for w in words]  # un radical grossier : « mariage » ≈ « mariages »
        for w in words:
            if len(w) >= 5:
                padded = f"^{w}$"
                feats += [f"t:{padded[i:i + 3]}" for i in range(len(padded) - 2)]
        return feats

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dims
            for feat in self._features(text):
                h = hashlib.blake2b(feat.encode(), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "big") % self.dims
                sign = 1.0 if h[4] & 1 else -1.0
                vec[idx] += sign * (2.0 if feat.startswith("w:") else 0.3)
            n = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / n for v in vec])
        return out

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return self.encode(texts)


class SentenceEmbedder:
    def __init__(self, model: str = "paraphrase-multilingual-MiniLM-L12-v2", *, device: str = "cpu") -> None:
        self.model_name = model
        self.device = device
        self.name = f"st:{model}"
        self.dims = 0
        self._model: Any = None
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="plongement")

    def _load(self) -> Any:
        if self._model is None:
            # lourd (torch) : chargé à la première demande, jamais par le simulateur
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            self._model = SentenceTransformer(self.model_name, device=self.device)
            self.dims = int(self._model.get_sentence_embedding_dimension())
        return self._model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        vecs = self._load().encode(list(texts), normalize_embeddings=True, convert_to_numpy=True,
                                   show_progress_bar=False, batch_size=32)
        return [list(map(float, v)) for v in vecs]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, self.encode, list(texts))

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
