"""Une échelle de similarité commune à tous les modèles (ADR 0111), par ses intentions.

- deux textes sans rapport valent environ 0, l'identique 1, quel que soit le modèle : pour un modèle dont tout se
  ressemble déjà (deux phrases quelconques à 0,8), les seuils de sa mémoire gardent leur sens ;
- centrer ne change ni l'ordre ni le départage par clé, en mémoire comme sur disque ;
- le fond se plonge une fois, comme des documents.
"""

from __future__ import annotations

import asyncio
import math

from mika.adapters.vectors import HashEmbedder, SqliteVectorIndex
from mika.adapters.vectors.background import BACKGROUND
from mika.ports.vectors import VectorItem
from tests.unit.test_audit_regressions import DB

TEXTS = {
    1: "Alice part au Japon en mai pour son travail.",
    2: "Le chat de Bob est malade depuis lundi.",
    3: "Sam a perdu son père l'an dernier.",
    4: "Karim ouvre son restaurant de couscous à Nantes.",
    5: "Le volcan islandais est entré en éruption cette nuit.",
}


class Crowded(HashEmbedder):
    """Un modèle où tout se ressemble : chaque vecteur penche vers une même direction (comme EmbeddingGemma 2, où
    deux phrases quelconques valent 0,8)."""

    def encode(self, texts):
        out = []
        for v in super().encode(texts):
            w = [0.45 * x for x in v]
            w[0] += 0.9
            n = math.sqrt(sum(x * x for x in w))
            out.append([x / n for x in w])
        return out


async def _index(emb, **kw) -> SqliteVectorIndex:
    index = SqliteVectorIndex(DB(), emb, **kw)
    await index.open()
    await index.upsert([VectorItem(k, "souvenir", t) for k, t in TEXTS.items()])
    return index


def test_unrelated_is_near_zero_and_identical_is_one_for_any_model():
    async def run(emb):
        index = await _index(emb)
        same = dict(await index.search(TEXTS[2], 5, document=True))
        other = dict(await index.search("La marée sera très haute ce week-end.", 5))
        return same, other

    for emb in (HashEmbedder(), Crowded()):
        same, other = asyncio.run(run(emb))
        assert same[2] > 0.99, emb.name
        assert max(v for k, v in same.items() if k != 2) < 0.3, "un texte sans rapport ne ressemble pas au doublon"
        assert max(other.values()) < 0.3, "une recherche sans rapport ne remonte rien au-dessus d'un seuil"
    raw = Crowded().encode([TEXTS[1], TEXTS[3]])
    assert sum(a * b for a, b in zip(*raw, strict=True)) > 0.7, "le modèle tassé l'est vraiment, sans centrage"


def test_centering_keeps_the_order_in_memory_and_on_disk():
    async def run(**kw):
        index = await _index(Crowded(), **kw)
        return await index.search("le chat de Bob va mieux ?", 5)

    ram, disk = asyncio.run(run()), asyncio.run(run(max_resident_vectors=1))
    assert [k for k, _ in ram] == [k for k, _ in disk]
    assert [round(s, 4) for _, s in ram] == [round(s, 4) for _, s in disk]
    assert ram[0][0] == 2
    assert [s for _, s in ram] == sorted((s for _, s in ram), reverse=True)


def test_the_background_is_embedded_once_as_documents():
    class Counting(HashEmbedder):
        def __init__(self) -> None:
            super().__init__()
            self.background = 0

        async def embed(self, texts):
            self.background += list(texts) == list(BACKGROUND)
            return self.encode(texts)

    async def run() -> int:
        emb = Counting()
        index = await _index(emb)
        for q in ("Alice", "Bob", "Sam"):
            await index.search(q, 2)
        await index.search(TEXTS[3], 2, document=True)
        return emb.background

    assert asyncio.run(run()) == 1
