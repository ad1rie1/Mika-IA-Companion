"""Le banc de mémoire : une seule base ou deux, pour ses proches et le monde (ADR 0110).

Sur le corpus de ``generer.py`` : ce qu'elle sait de ses proches (souvenirs, croyances, rattachés à la personne et à
qui l'a dit) et des milliers de faits du monde (lus, rattachés à personne). Chaque message est rappelé par les vraies
fonctions du rappel (``memory.recall`` : recherche globale et recherche propre à qui parle, hybride vecteurs et mots,
seuil et marge, classement, souvenirs qui dorment, plafonds), puis on regarde si l'élément visé est remonté.

- A, une base : le monde concourt pour les mêmes places que ses proches (aujourd'hui).
- B, deux bases : ses proches dans un index, le monde dans un autre, avec son seuil et son quota.

Mesures : messages sur ses proches (trouvé, et combien de faits du monde se glissent parmi ce qui remonte), homonymes
d'une personnalité (« t'as des nouvelles d'Emmanuel ? »), questions sur le monde, temps d'une recherche, place des
vecteurs, à plusieurs tailles du monde.

    PYTHONPATH=~/.cache/mika-banc-libs .venv/bin/python tools/banc_memoire/banc.py [--modele …] [--appareil cuda]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mika.adapters.vectors import SqliteVectorIndex  # noqa: E402
from mika.adapters.vectors.embedders import SentenceEmbedder  # noqa: E402
from mika.contracts import memory as c  # noqa: E402
from mika.faculties.memory.faculty import MemoryParams  # noqa: E402
from mika.faculties.memory.recall import _merged, kept, scored, search  # noqa: E402
from mika.faculties.memory.salience import Item, dormant, rank  # noqa: E402
from mika.ports.vectors import VectorItem  # noqa: E402
from tests.fixtures.sqldb import SqlDB  # noqa: E402

ROOT = Path(__file__).resolve().parents[2] / "data" / "banc-memoire"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generer import PERSONNES  # noqa: E402

DAY = 86_400_000_000
NOW = 1_791_979_200_000_000  # le 14 octobre 2026 à midi (UTC), en µs
#: les proches qui portent le prénom d'une personnalité publique du corpus
HOMONYMES = {"Emmanuel", "Marine", "Jordan", "Gabriel", "Antoine", "Victor", "Léon", "Raphaël", "Lionel", "Christine",
             "Céline", "Charles", "Arthur", "Sophie", "Pierre", "Jean", "Simone", "Xavier", "Marion", "Thomas",
             "Léa", "Michel", "Nicolas", "François", "Max"}

#: des messages qui ne visent rien de ce qu'elle sait : ce qui remonte quand même est du bruit
BANALS = ["salut ça va ?", "bonne nuit", "j'ai faim", "il fait beau aujourd'hui", "tu fais quoi ?", "mdr",
          "je rentre du boulot", "je suis fatigué", "on parle de quoi ?", "raconte-moi un truc", "t'es là ?",
          "j'ai bien dormi", "quelle journée", "ok merci", "je m'ennuie un peu", "tu penses à quoi ?",
          "c'est le week-end enfin", "j'ai pris un café", "il pleut encore", "à plus tard",
          "tu as passé une bonne journée ?", "je vais me coucher tôt", "bon appétit", "j'écoute de la musique",
          "il est quelle heure chez toi ?", "j'ai rien fait de spécial", "coucou", "t'as le moral ?",
          "on se parle demain", "je suis dans le train"]


@dataclass
class Message:
    text: str
    speaker: str
    gold: int
    world: bool
    homonym: bool = False


class Cached:
    """Le modèle, avec un cache par texte : chaque configuration ne coûte que ses recherches."""

    def __init__(self, inner: SentenceEmbedder) -> None:
        self.inner, self.name = inner, inner.name
        self.docs: dict[str, list[float]] = {}
        self.queries: dict[str, list[float]] = {}

    @property
    def dims(self) -> int:
        return self.inner.dims

    async def embed(self, texts):
        todo = [t for t in dict.fromkeys(texts) if t not in self.docs]
        for i in range(0, len(todo), 256):
            for t, v in zip(todo[i:i + 256], await self.inner.embed(todo[i:i + 256]), strict=True):
                self.docs[t] = v
        return [self.docs[t] for t in texts]

    async def embed_query(self, texts):
        todo = [t for t in dict.fromkeys(texts) if t not in self.queries]
        if todo:
            for t, v in zip(todo, await self.inner.embed_query(todo), strict=True):
                self.queries[t] = v
        return [self.queries[t] for t in texts]


def item(i: int, kind: str, text: str, about: tuple[str, ...], told_by: tuple[str, ...], importance: float,
         confidence: float | None, origin: str | None, born_at: int) -> Item:
    return Item(id=i, kind=kind, text=text, about=about, sensitivity=1, importance=importance, confidence=confidence,
                origin=origin, source=None, emotion=None, born_at=born_at, touched_at=born_at, recalled_at=0,
                recalls=0, status="active", told_by=told_by)


def corpus() -> tuple[dict[int, Item], list[Message], set[int]]:
    rnd = random.Random(14)
    items: dict[int, Item] = {}
    messages: list[Message] = []
    world: set[int] = set()
    handles: dict[str, str] = {}
    for n, (prenom, _lien, parle) in enumerate(PERSONNES):
        handles[prenom] = f"user_{n + 1}" if parle else f"name:private:user_1:{prenom.lower()}"
    nxt = 1
    for n, (prenom, _lien, parle) in enumerate(PERSONNES):
        path = ROOT / "lots" / f"personne-{n:02d}.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        who = handles[prenom]
        teller = who if parle else handles["Adrien"]
        ids = []
        for el in data.get("elements", []):
            kind = c.SOUVENIR if el.get("type") == "souvenir" else c.BELIEF
            items[nxt] = item(nxt, kind, el["texte"], (who,), (teller,), float(el.get("importance", 0.5)),
                              0.8 if kind == c.BELIEF else None, None, NOW - rnd.randint(1, 365) * DAY)
            ids.append(nxt)
            nxt += 1
        for m in data.get("messages", []):
            if isinstance(m.get("cible"), int) and 0 <= m["cible"] < len(ids):
                messages.append(Message(m["texte"], teller if parle else handles["Adrien"], ids[m["cible"]], False,
                                        prenom in HOMONYMES))
    for path in sorted((ROOT / "lots").glob("*.json")):
        if path.name.startswith("personne-"):
            continue
        data = json.loads(path.read_text())
        ids = []
        for f in data.get("faits", []):
            source = f"rss:{f.get('source') or 'presse'}"
            items[nxt] = item(nxt, c.BELIEF, f["texte"], (), (source,), 0.3, 0.7, "read",
                              NOW - rnd.randint(1, 180) * DAY)
            world.add(nxt)
            ids.append(nxt)
            nxt += 1
        for q in data.get("questions", []):
            if isinstance(q.get("cible"), int) and 0 <= q["cible"] < len(ids):
                messages.append(Message(q["texte"], handles["Adrien"], ids[q["cible"]], True))
    return items, messages, world


def persons_of(it: Item) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*it.about, *it.told_by)))


async def index_of(emb: Cached, items: dict[int, Item]) -> SqliteVectorIndex:
    idx = SqliteVectorIndex(SqlDB(), emb, max_resident_vectors=10**6)
    await idx.open()
    batch = [VectorItem(i, it.kind, it.text, persons_of(it)) for i, it in items.items()]
    for k in range(0, len(batch), 512):
        await idx.upsert(batch[k:k + 512])
    return idx


async def recall(idx: SqliteVectorIndex, items: dict[int, Item], msg: Message, p: MemoryParams,
                 caps: tuple[int, int]) -> tuple[list[int], float]:
    """Ce que le rappel ferait remonter pour ce message : (identifiants retenus, temps des recherches)."""
    t0 = time.perf_counter()
    near, wider = await search(idx, msg.text, "", p.recall_k, kinds={c.SOUVENIR, c.BELIEF})
    own_near, own_wider = await search(idx, msg.text, "", p.recall_k, kinds={c.SOUVENIR, c.BELIEF},
                                       persons=(msg.speaker,))
    near, wider = _merged(near, own_near), _merged(wider, own_wider)
    took = time.perf_counter() - t0
    sims = scored(near, wider, {i: items[i].text for i in {*near, *wider}}, msg.text, "")
    candidates = kept(sims, p)
    ranked = []
    for i, sim in candidates.items():
        it = items[i]
        if dormant(it, NOW, p) and sim < p.strong_cue:
            continue
        ranked.append((rank(it, sim, NOW, p, interlocutor=msg.speaker, mood_valence=0.0), i))
    ranked.sort(key=lambda r: (-r[0], r[1]))
    souvenirs = [i for _s, i in ranked if items[i].kind == c.SOUVENIR][:caps[0]]
    beliefs = [i for _s, i in ranked if items[i].kind == c.BELIEF][:caps[1]]
    return souvenirs + beliefs, took


async def world_recall(idx: SqliteVectorIndex, items: dict[int, Item], msg: Message, p: MemoryParams,
                       quota: int) -> tuple[list[int], float]:
    t0 = time.perf_counter()
    near, wider = await search(idx, msg.text, "", p.recall_k)
    took = time.perf_counter() - t0
    sims = kept(scored(near, wider, {i: items[i].text for i in {*near, *wider}}, msg.text, ""), p)
    ranked = sorted(((rank(items[i], s, NOW, p, interlocutor=None, mood_valence=0.0), i) for i, s in sims.items()),
                    key=lambda r: (-r[0], r[1]))
    return [i for _s, i in ranked[:quota]], took


def summary(rows: list[dict]) -> dict:
    def rate(sel):
        return round(100 * sum(r["hit"] for r in sel) / len(sel), 1) if sel else None
    banal = [r for r in rows if r["banal"]]
    rows = [r for r in rows if not r["banal"]]
    personal = [r for r in rows if not r["world"]]
    homonym = [r for r in personal if r["homonym"]]
    world = [r for r in rows if r["world"]]
    return {"proches_%": rate(personal), "homonymes_%": rate(homonym), "monde_%": rate(world),
            "intrusions": round(statistics.fmean(r["intrusions"] for r in personal), 2) if personal else None,
            "bruit": round(statistics.fmean(r["got"] for r in banal), 2) if banal else None,
            "rappel_ms": round(1000 * statistics.median(r["took"] for r in rows), 1),
            "messages": f"{len(personal)}+{len(world)}"}


async def run(model: str, device: str, sizes: list[int], out: Path, grid: list[tuple[float, float]],
              quotas: list[int]) -> None:
    items, messages, world = corpus()
    personal = {i: it for i, it in items.items() if i not in world}
    gold_world = {m.gold for m in messages if m.world}
    print(f"corpus : {len(personal)} éléments sur {len(PERSONNES)} personnes, {len(world)} faits du monde, "
          f"{sum(not m.world for m in messages)} messages sur ses proches, {sum(m.world for m in messages)} sur le monde",
          flush=True)
    emb = Cached(SentenceEmbedder(model, device=device))
    t0 = time.perf_counter()
    await emb.embed([it.text for it in items.values()])
    print(f"plongés en {time.perf_counter() - t0:.0f} s ({model}, {device})", flush=True)
    rnd = random.Random(7)
    others = sorted(world - gold_world)
    results = []
    configs = []
    for floor, cue in grid:
        p = MemoryParams().model_copy(update={"recall_floor": floor, "strong_cue": cue})
        configs.append((f"A une base, seuil {floor}, indice {cue}", None, p, 0))
        for q in quotas:
            configs.append((f"B deux bases, seuil {floor}, indice {cue}, monde ×{q} dès {floor + 0.1:.2f}",
                            round(floor + 0.1, 2), p, q))
    for size in sizes:
        chosen = set(gold_world) | set(rnd.sample(others, max(0, min(len(others), size - len(gold_world)))))
        if size == 0:
            chosen = set()
        sub_world = {i: items[i] for i in chosen}
        one = await index_of(emb, {**personal, **sub_world})
        two_p = await index_of(emb, personal)
        two_w = await index_of(emb, sub_world) if sub_world else None
        msgs = [m for m in messages if not m.world or (size and m.gold in chosen)]
        msgs += [Message(text, "user_1", -1, False) for text in BANALS]
        for label, floor, p, quota in configs:
            rows = []
            for m in msgs:
                if quota == 0:  # une base
                    got, took = await recall(one, {**personal, **sub_world}, m, p, (p.max_souvenirs, p.max_beliefs))
                else:
                    got, took = await recall(two_p, personal, m, p, (p.max_souvenirs, p.max_beliefs))
                    if two_w is not None:
                        pw = p.model_copy(update={"recall_floor": floor})
                        wgot, wtook = await world_recall(two_w, sub_world, m, pw, quota)
                        got, took = got + wgot, took + wtook
                rows.append({"hit": m.gold in got, "world": m.world, "homonym": m.homonym, "took": took,
                             "banal": m.gold < 0, "got": len(got),
                             "intrusions": sum(1 for i in got if i in chosen) if not m.world and quota == 0 else
                             (sum(1 for i in got if i in chosen) if not m.world else 0)})
            s = {"monde": len(sub_world), "config": label, **summary(rows),
                 "vecteurs_mo": round((len(personal) + len(sub_world)) * emb.dims * 4 / 2**20, 1)}
            results.append(s)
            print(json.dumps(s, ensure_ascii=False), flush=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1))


async def calibrate(model: str, device: str) -> dict:
    """Où tombent les scores, sur l'échelle centrée de l'index (ADR 0111), pour ce modèle :

    - le rappel : le score hybride (similarité centrée + bonus des mots) de l'élément visé et de tous les autres, de
      quoi placer le seuil (``recall_floor``) et l'indice fort (``strong_cue``) ;
    - les doublons : un élément et sa reformulation (à fusionner), un élément et un fait voisin de la même personne
      (à garder), et le plus proche des autres éléments de la même personne — de quoi placer ``dedup_similarity`` et
      ``night_merge_similarity`` (comparaisons de documents entre eux).

    Le fond est celui de l'index (``background``), comparé à la médiane de la requête sur tout le corpus."""
    import numpy as np  # noqa: PLC0415

    from mika.adapters.vectors.background import BACKGROUND  # noqa: PLC0415
    from mika.faculties.memory.recall import LEXICAL_BONUS, topic  # noqa: PLC0415
    from mika.vocab.words import stems  # noqa: PLC0415

    items, messages, _world = corpus()
    emb = Cached(SentenceEmbedder(model, device=device))
    keys = list(items)
    docs = np.asarray(await emb.embed([items[k].text for k in keys]), dtype=np.float32)
    docs16 = docs.astype(np.float16).astype(np.float32)  # ce que l'index garde
    anchors = np.asarray(await emb.embed(list(BACKGROUND)), dtype=np.float32)

    def centre(sims: np.ndarray, q: np.ndarray) -> tuple[np.ndarray, float]:
        back = min(0.95, max(0.0, float(np.median(anchors @ q))))
        return (sims - back) / (1.0 - back), back

    qs = np.asarray(await emb.embed_query([m.text for m in messages]), dtype=np.float32)
    item_stems = [stems(items[k].text) for k in keys]
    gold, other, ranks, backs, medians, gold_vec = [], [], [], [], [], []
    for qi, m in enumerate(messages):
        wanted = topic(m.text)
        lex = np.array([LEXICAL_BONUS * (len(wanted & st) / len(wanted)) ** 0.5 if wanted else 0.0
                        for st in item_stems], dtype=np.float32)
        raw = docs16 @ qs[qi]
        centred, back = centre(raw, qs[qi])
        backs.append(back)
        medians.append(float(np.median(raw)))
        hybrid = centred + lex
        g = keys.index(m.gold)
        gold.append(float(hybrid[g]))
        gold_vec.append(float(centred[g]))
        ranks.append(int((hybrid > hybrid[g]).sum()) + 1)
        other.extend(np.delete(hybrid, g)[::7].tolist())
    pct = lambda xs, q: round(float(np.percentile(xs, q)), 3) if len(xs) else None  # noqa: E731
    out = {"modèle": model, "fond_phrases_médiane": pct(backs, 50), "fond_corpus_médiane": pct(medians, 50),
           "visé_médiane": pct(gold, 50), "visé_25%": pct(gold, 25), "visé_10%": pct(gold, 10),
           "visé_vecteurs_seuls_médiane": pct(gold_vec, 50),
           "autres_médiane": pct(other, 50), "autres_90%": pct(other, 90), "autres_99%": pct(other, 99),
           "autres_99,9%": pct(other, 99.9),
           "visé_premier_%": round(100 * sum(r == 1 for r in ranks) / len(ranks), 1),
           "visé_top10_%": round(100 * sum(r <= 10 for r in ranks) / len(ranks), 1),
           "messages": len(messages), "éléments": len(items)}
    # les doublons : des documents comparés entre eux
    pairs = [pr for f in sorted((ROOT / "lots").glob("paires-*.json")) for pr in json.loads(f.read_text())["paires"]
             if pr.get("meme") and pr.get("voisin")]
    proches = [el["texte"] for f in sorted((ROOT / "lots").glob("personne-*.json"))
               for el in json.loads(f.read_text()).get("elements", [])][::3]
    if pairs:
        base = []
        for f in sorted((ROOT / "lots").glob("paires-*.json")):
            n = int(f.stem.split("-")[1])
            chunk = proches[25 * n:25 * n + 25]
            base += [(chunk[pr["index"]], pr["meme"], pr["voisin"]) for pr in json.loads(f.read_text())["paires"]
                     if isinstance(pr.get("index"), int) and 0 <= pr["index"] < len(chunk)
                     and pr.get("meme") and pr.get("voisin")]
        a = np.asarray(await emb.embed([b[0] for b in base]), dtype=np.float32)
        same = np.asarray(await emb.embed([b[1] for b in base]), dtype=np.float32).astype(np.float16).astype(np.float32)
        near = np.asarray(await emb.embed([b[2] for b in base]), dtype=np.float32).astype(np.float16).astype(np.float32)
        s_same, s_near = [], []
        for i in range(len(base)):
            s_same.append(float(centre(np.asarray([same[i] @ a[i]]), a[i])[0][0]))
            s_near.append(float(centre(np.asarray([near[i] @ a[i]]), a[i])[0][0]))
        # le plus proche des autres éléments de la même personne (ce que la fusion de la nuit verrait)
        by_person: dict[tuple[str, ...], list[int]] = {}
        for n, k in enumerate(keys):
            if items[k].about:
                by_person.setdefault(items[k].about, []).append(n)
        s_sibling = []
        for rows in by_person.values():
            sub = docs16[rows]
            for j, r in enumerate(rows):
                sims, _b = centre(sub @ docs[r], docs[r])
                sims[j] = -1
                s_sibling.append(float(sims.max()))
        out |= {"paires": len(base), "même_médiane": pct(s_same, 50), "même_25%": pct(s_same, 25),
                "même_10%": pct(s_same, 10), "même_5%": pct(s_same, 5),
                "voisin_médiane": pct(s_near, 50), "voisin_90%": pct(s_near, 90), "voisin_99%": pct(s_near, 99),
                "plus_proche_même_personne_médiane": pct(s_sibling, 50),
                "plus_proche_même_personne_99%": pct(s_sibling, 99),
                **{f"dès {t}": f"même {100 * np.mean(np.asarray(s_same) >= t):.0f} %, voisin "
                               f"{100 * np.mean(np.asarray(s_near) >= t):.0f} %, autre de la personne "
                               f"{100 * np.mean(np.asarray(s_sibling) >= t):.1f} %"
                   for t in (0.8, 0.83, 0.85, 0.87, 0.89, 0.91)}}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modele", default="google/embeddinggemma-2")
    ap.add_argument("--appareil", default="cuda")
    ap.add_argument("--tailles", default="0,1000,3000,999999")
    ap.add_argument("--sortie", default=str(ROOT / "resultats.json"))
    ap.add_argument("--etalonner", nargs="*", help="les modèles à étalonner (sans : le banc)")
    ap.add_argument("--grille", default="0.45:0.75,0.40:0.70,0.35:0.65,0.30:0.60",
                    help="seuil:indice fort, séparés par des virgules")
    ap.add_argument("--quotas", default="3", help="les places du monde à part (B)")
    args = ap.parse_args()
    if args.etalonner is not None:
        for model in args.etalonner or [args.modele]:
            print(json.dumps(asyncio.run(calibrate(model, args.appareil)), ensure_ascii=False), flush=True)
        return
    grid = [(float(a), float(b)) for a, b in (g.split(":") for g in args.grille.split(","))]
    asyncio.run(run(args.modele, args.appareil, [int(x) for x in args.tailles.split(",")], Path(args.sortie), grid,
                    [int(q) for q in args.quotas.split(",") if q]))


if __name__ == "__main__":
    main()
