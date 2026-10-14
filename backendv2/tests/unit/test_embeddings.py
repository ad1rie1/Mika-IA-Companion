"""Le modèle de plongements (ADR 0109), par ses intentions.

- une requête et un document se plongent chacun comme le modèle l'attend : sa consigne de recherche pour ce qu'on
  cherche, sa consigne de document pour ce qu'elle range — ``query:``/``passage:`` pour E5, qui ne les déclare pas ;
- l'index plonge une recherche comme une requête ;
- le modèle et l'appareil se choisissent par la machine (comme ses bases), le processeur par défaut.
"""

from __future__ import annotations

import asyncio

from mika.adapters.vectors import HashEmbedder, SqliteVectorIndex
from mika.adapters.vectors.embedders import DEFAULT_MODEL, SentenceEmbedder, load_options, prompts_for
from mika.app import embeddings
from mika.ports.vectors import VectorItem
from mika.vocab.phrasebook import phrase
from tests.unit.test_audit_regressions import DB


class FakeModel:
    """Ce que voit le modèle : le nom de la consigne demandée pour chaque appel."""

    def __init__(self, prompts: dict[str, str]) -> None:
        self.prompts = prompts
        self.asked: list[str | None] = []

    def encode(self, texts, **kw):
        self.asked.append(kw.get("prompt_name"))
        return [[1.0, 0.0] for _ in texts]


def _with(prompts: dict[str, str]) -> tuple[SentenceEmbedder, FakeModel]:
    emb = SentenceEmbedder("un-modele")
    emb._model = fake = FakeModel(prompts)
    return emb, fake


def test_a_query_and_a_document_each_get_the_prompt_the_model_expects():
    emb, fake = _with({"query": "Instruct: retrouve\nQuery:", "document": ""})
    emb.encode(["comment va mon matou ?"], query=True)
    emb.encode(["Adrien a un chat qui s'appelle Pixel."])
    assert fake.asked == ["query", "document"]
    # la famille E5 nomme son document « passage »
    emb, fake = _with({"query": "query: ", "passage": "passage: "})
    emb.encode(["x"], query=True)
    emb.encode(["y"])
    assert fake.asked == ["query", "passage"]
    # contre-exemple : un modèle sans consigne (l'actuel) plonge les deux pareil, sans rien ajouter
    emb, fake = _with({})
    emb.encode(["x"], query=True)
    emb.encode(["y"])
    assert fake.asked == [None, None]


def test_e5_gets_its_prefixes_even_though_it_does_not_declare_them():
    assert prompts_for("intfloat/multilingual-e5-small") == {"query": "query: ", "document": "passage: "}
    assert prompts_for("intfloat/multilingual-e5-base") is not None
    assert prompts_for(DEFAULT_MODEL) is None


def test_qwen3_reads_our_memory_instruction_before_a_query_only():
    """Sa consigne par défaut parle de recherche web, en anglais : la nôtre (``vectors.query_instruction``) retrouve
    le bon souvenir en tête 35 fois sur 40 au banc, au lieu de 31. Rien devant ce que sa mémoire range."""
    prompts = prompts_for("Qwen/Qwen3-Embedding-0.6B")
    assert prompts == {"query": f"Instruct: {phrase('vectors.query_instruction')}\nQuery:", "document": ""}


def test_a_search_is_embedded_as_a_query():
    class Recording(HashEmbedder):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[str] = []

        async def embed(self, texts):
            self.calls.append("document")
            return self.encode(texts)

        async def embed_query(self, texts):
            self.calls.append("query")
            return self.encode(texts)

    async def run() -> list[str]:
        emb = Recording()
        index = SqliteVectorIndex(DB(), emb)
        await index.open()
        await index.upsert([VectorItem(1, "souvenir", "Adrien a un chat qui s'appelle Pixel.", ("user_1",))])
        assert (await index.search("mon chat Pixel", 3))[0][0] == 1
        return emb.calls

    assert asyncio.run(run()) == ["document", "query"]


def test_the_machine_chooses_the_model_and_the_device(monkeypatch):
    monkeypatch.delenv(embeddings.MODEL_ENV, raising=False)
    monkeypatch.delenv(embeddings.DEVICE_ENV, raising=False)
    assert embeddings.configured() == (DEFAULT_MODEL, "cpu"), "par défaut : le modèle d'avant, sur le processeur"
    monkeypatch.setenv(embeddings.MODEL_ENV, " Qwen/Qwen3-Embedding-0.6B ")
    monkeypatch.setenv(embeddings.DEVICE_ENV, "CUDA")
    emb = embeddings.embedder()
    assert (emb.model_name, emb.device, emb.name) == ("Qwen/Qwen3-Embedding-0.6B", "cuda", "st:Qwen/Qwen3-Embedding-0.6B")
    monkeypatch.setenv(embeddings.DEVICE_ENV, "tpu")
    assert embeddings.configured()[1] == "cpu", "un appareil inconnu : le processeur"


def test_each_model_loads_in_the_precision_it_supports():
    """Sur la carte : fp16 pour Qwen3 (même rang au banc, deux fois moins de mémoire), jamais pour EmbeddingGemma 2
    (vecteurs faux en fp16, sans erreur) — bf16 si la carte le calcule nativement, sinon fp32. Sa seule partie texte
    est chargée. Sur le processeur, rien d'imposé."""
    gemma = "google/embeddinggemma-2"
    text_only = {"vision_config": None, "audio_config": None}
    assert load_options("Qwen/Qwen3-Embedding-0.6B", "cuda", False) == {"model_kwargs": {"torch_dtype": "float16"}}
    assert load_options(gemma, "cuda", False) == {"config_kwargs": text_only}, "fp32 sur une GTX 1650 (pas de bf16)"
    assert load_options(gemma, "cuda", True) == {"config_kwargs": text_only,
                                                 "model_kwargs": {"torch_dtype": "bfloat16"}}
    assert load_options(gemma, "cpu", False) == {"config_kwargs": text_only}
    assert load_options(DEFAULT_MODEL, "cpu", False) == {}
    assert prompts_for(gemma) is None, "ses consignes à lui (« task: search result ») : les nôtres le desservent"
