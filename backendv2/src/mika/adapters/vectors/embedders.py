"""Deux plongements.

- ``HashEmbedder`` : l'astuce du hachage sur des mots et des trigrammes de
  caractères, repliés (casse, accents). Déterministe à l'octet, instantané,
  indépendant de ``PYTHONHASHSEED`` : celui du simulateur et des tests. Il ne
  comprend pas le sens, seulement le recouvrement de vocabulaire.
- ``SentenceEmbedder`` : un modèle sentence-transformers (multilingue par
  défaut), chargé à la première demande dans un fil dédié ; les calculs du
  modèle relâchent le verrou global, la boucle continue de répondre. Une
  requête et un document se plongent chacun comme le modèle l'attend (ses
  « prompts », ``query:``/``passage:`` pour E5 — ADR 0109), sur le processeur
  ou la carte graphique (``device``).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import hashlib
import math
from collections.abc import Sequence
from typing import Any

from mika.vocab.phrasebook import phrase
from mika.vocab.words import STOPWORDS as _STOPWORDS
from mika.vocab.words import WORD as _WORD
from mika.vocab.words import fold as _fold

#: Les mots qui ne disent rien du sujet : sans eux, « tu te souviens de ce que
#: je t'ai dit pour samedi » ressemble surtout à toute phrase contenant « dit ».
STOPWORDS = _STOPWORDS


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

    async def embed_query(self, texts: Sequence[str]) -> list[list[float]]:
        return self.encode(texts)


#: le modèle par défaut (ADR 0109 : un autre se choisit par la machine, ``MIKA_EMBEDDINGS_MODEL``)
DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

#: les préfixes d'une famille de modèles qui ne les déclare pas elle-même : sans eux, E5 perd l'essentiel de ce qui
#: le rend meilleur pour retrouver (une requête n'est pas un passage)
KNOWN_PROMPTS = {"multilingual-e5": {"query": "query: ", "document": "passage: "}}

#: les familles qui suivent une consigne de recherche : la nôtre (``vectors.query_instruction``) remplace la leur,
#: une recherche web en anglais (tools/banc_plongements : 35 souvenirs sur 40 en tête au lieu de 31)
INSTRUCTED = ("Qwen3-Embedding",)


def prompts_for(model: str) -> dict[str, str] | None:
    if any(family in model for family in INSTRUCTED):
        return {"query": f"Instruct: {phrase('vectors.query_instruction')}\nQuery:", "document": ""}
    return next((dict(v) for k, v in KNOWN_PROMPTS.items() if k in model), None)


class SentenceEmbedder:
    def __init__(self, model: str = DEFAULT_MODEL, *, device: str = "cpu") -> None:
        self.model_name = model
        #: ``cpu``, ``cuda`` (la carte graphique), ou ``auto`` (la carte si elle répond, sinon le processeur)
        self.device = device
        # le nom range les vecteurs dans l'index : un autre modèle a les siens, et la mémoire se replonge d'elle-même
        self.name = f"st:{model}"
        self.dims = 0
        self._model: Any = None
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="plongement")

    def _load(self) -> Any:
        if self._model is None:
            # lourd (torch) : chargé à la première demande, jamais par le simulateur
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            device = self.device
            if device == "auto":
                import torch  # noqa: PLC0415

                device = "cuda" if torch.cuda.is_available() else "cpu"
            prompts = prompts_for(self.model_name)
            kwargs: dict[str, Any] = {"prompts": prompts} if prompts else {}
            if device == "cuda":  # en demi-précision : deux fois moins de mémoire sur la carte, même rang au banc
                kwargs["model_kwargs"] = {"torch_dtype": "float16"}
            self._model = SentenceTransformer(self.model_name, device=device, **kwargs)
            self.dims = int(self._model.get_sentence_embedding_dimension())
        return self._model

    def encode(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        model = self._load()
        known = getattr(model, "prompts", None) or {}
        wanted = ("query",) if query else ("document", "passage")
        prompt = next((name for name in wanted if name in known), None)
        vecs = model.encode(list(texts), normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False,
                            batch_size=32, **({"prompt_name": prompt} if prompt else {}))
        return [list(map(float, v)) for v in vecs]

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Des documents (ce que sa mémoire range)."""
        if not texts:
            return []
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, self.encode, list(texts))

    async def embed_query(self, texts: Sequence[str]) -> list[list[float]]:
        """Des requêtes (ce qu'on cherche) : la consigne du modèle pour une recherche, quand il en a une."""
        if not texts:
            return []
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, functools.partial(self.encode, list(texts), query=True))

    async def warm(self) -> None:
        """Charge le modèle maintenant, dans son fil : au démarrage, pendant que le noyau relit sa vie. Sinon le
        premier tour le chargeait, et le rappel (2,5 s au plus) passait sans mémoire (sonde réelle du 2026-10-09).
        Une demande arrivée entre-temps attend la fin du chargement dans le même fil, sans le refaire."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._pool, self._load)

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
