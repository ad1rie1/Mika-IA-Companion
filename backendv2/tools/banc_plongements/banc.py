"""Le banc des plongements : quel modèle retrouve le mieux ses souvenirs en français, et à quel prix.

Pour chaque modèle, sur ``corpus.py`` : les éléments plongés comme documents, chaque message comme requête (avec le
préfixe ou la consigne que le modèle attend : ``query:``/``passage:`` pour E5, ses « prompts » pour Qwen3 et
EmbeddingGemma), puis le rang du premier élément attendu. Mesure aussi la mémoire prise par le modèle chargé et le
temps d'une requête, sur le processeur (ce que tient le portable) ou sur ``--device cuda``.

    .venv/bin/python tools/banc_plongements/banc.py [--device cpu|cuda] [--out fichier.json] [modèle …]

Sans modèle nommé : ceux de ``MODELS``. Un modèle introuvable ou réservé (licence à accepter) est sauté, en le disant.
Passer par ``borne.sh`` : un gros modèle prend plusieurs gigaoctets.
"""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import resource
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from corpus import ITEMS, QUERIES  # noqa: E402

#: (nom affiché, modèle Hugging Face, préfixes imposés quand le modèle ne les déclare pas)
MODELS = [
    ("actuel MiniLM-L12", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", None),
    ("e5-small", "intfloat/multilingual-e5-small", {"query": "query: ", "document": "passage: "}),
    ("e5-base", "intfloat/multilingual-e5-base", {"query": "query: ", "document": "passage: "}),
    ("granite-278m", "ibm-granite/granite-embedding-278m-multilingual", None),
    ("embeddinggemma-300m", "google/embeddinggemma-300m", None),
    ("bge-m3", "BAAI/bge-m3", None),
    ("qwen3-0.6b", "Qwen/Qwen3-Embedding-0.6B", None),
    # Qwen3 suit une consigne de recherche : la sienne par défaut parle de recherche web ; une consigne de souvenirs
    ("qwen3 consigne fr", "Qwen/Qwen3-Embedding-0.6B",
     {"query": "Instruct: Retrouve, parmi ce qu'elle sait des gens, ce qui aide à répondre à ce message\nQuery:",
      "document": ""}),
    # plus gros : pour une carte graphique (fp16 : ~2 octets par paramètre)
    ("qwen3-4b consigne fr", "Qwen/Qwen3-Embedding-4B",
     {"query": "Instruct: Retrouve, parmi ce qu'elle sait des gens, ce qui aide à répondre à ce message\nQuery:", "document": ""}),
    ("e5-large-instruct", "intfloat/multilingual-e5-large-instruct",
     {"query": "Instruct: Retrouve, parmi ce qu'elle sait des gens, ce qui aide à répondre à ce message\nQuery: ", "document": ""}),
    ("qwen3 consigne en", "Qwen/Qwen3-Embedding-0.6B",
     {"query": "Instruct: Given a chat message from a friend, retrieve the memories that help answer it\nQuery:",
      "document": ""}),
]


FP16 = False
BITS4 = False


def rss_mb() -> float:
    with open("/proc/self/status") as fh:
        for line in fh:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return 0.0


def bench(label: str, name: str, prompts: dict | None, device: str) -> dict:
    import torch  # noqa: PLC0415
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    gc.collect()
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    before = rss_mb()
    t0 = time.monotonic()
    kwargs = {"device": device}
    if prompts:
        kwargs["prompts"] = prompts
    model_kwargs = {}
    if FP16:
        model_kwargs["torch_dtype"] = "float16"
    if device == "cuda" and importlib.util.find_spec("accelerate"):  # droit sur la carte, sans passer par la RAM
        model_kwargs["device_map"] = "cuda"
    if BITS4:  # quantifié en 4 bits (NF4, calcul en fp16) : un 4B tient alors dans ~2,5 Go de carte
        from transformers import BitsAndBytesConfig  # noqa: PLC0415

        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16)
    if model_kwargs:
        kwargs["model_kwargs"] = model_kwargs
    model = SentenceTransformer(name, **kwargs)
    load_s = time.monotonic() - t0
    loaded = rss_mb() - before
    keys = list(ITEMS)
    docs = model.encode_document([ITEMS[k] for k in keys], normalize_embeddings=True, convert_to_numpy=True,
                                 batch_size=16)
    times, ranks, rows = [], [], []
    for text, wanted in QUERIES:
        t1 = time.monotonic()
        q = model.encode_query([text], normalize_embeddings=True, convert_to_numpy=True)[0]
        times.append(time.monotonic() - t1)
        order = [keys[i] for i in (docs @ q).argsort()[::-1]]
        rank = order.index(wanted[0]) + 1
        ranks.append(rank)
        rows.append({"message": text, "attendu": wanted[0], "rang": rank, "premier": order[0],
                     "premier_texte": ITEMS[order[0]]})
    out = {
        "modèle": label, "nom": name, "dimensions": int(model.get_sentence_embedding_dimension()),
        "top1": sum(r == 1 for r in ranks), "top3": sum(r <= 3 for r in ranks), "cas": len(ranks),
        "mrr": round(statistics.fmean(1 / r for r in ranks), 3),
        "mémoire_mo": round(loaded), "chargement_s": round(load_s, 1),
        "requête_ms": round(1000 * statistics.median(times[1:] or times), 1),
        "carte_mo": round(torch.cuda.max_memory_allocated() / 2**20) if device == "cuda" else 0,
        "échecs": [r for r in rows if r["rang"] > 1],
    }
    del model, docs
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--out", default="")
    ap.add_argument("--fp16", action="store_true", help="en demi-précision (comme sur la carte graphique)")
    ap.add_argument("--4bits", dest="bits4", action="store_true", help="quantifié en 4 bits (bitsandbytes, sur carte)")
    args = ap.parse_args()
    global FP16, BITS4
    FP16, BITS4 = args.fp16, args.bits4
    chosen = [m for m in MODELS if not args.models or m[0] in args.models or m[1] in args.models]
    results = []
    for label, name, prompts in chosen:
        try:
            r = bench(label, name, prompts, args.device)
        except Exception as exc:  # noqa: BLE001 — un modèle réservé ou introuvable est sauté, en le disant
            print(f"{label:22s} sauté : {type(exc).__name__}: {str(exc)[:140]}", flush=True)
            continue
        results.append(r)
        print(f"{label:22s} top1 {r['top1']:2d}/{r['cas']}  top3 {r['top3']:2d}/{r['cas']}  MRR {r['mrr']:.3f}  "
              f"{r['dimensions']:4d} dim  carte {r['carte_mo']:5d} Mo  requête {r['requête_ms']:6.1f} ms", flush=True)
    print(f"(pic de mémoire du processus : {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} Mo)")
    if args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
