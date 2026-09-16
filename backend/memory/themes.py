"""Regroupement thématique des échanges — pur, sans I/O.

Le consolidateur extrait une fenêtre de messages en un appel LLM quand elle
tient dans une tranche, et la découpait sinon en tranches *linéaires* : le
backlog d'un provider mort tout l'après-midi partait en morceaux de 8 000
caractères pris dans l'ordre, une tranche mêlant la fin du projet, le début
de la dispute et la moitié des vacances. Le regroupement par thème vivait
ailleurs — dans la réorganisation nocturne, qui l'appliquait au-dessus du
checkpoint du consolidateur sans jamais faire avancer ce checkpoint, donc
en double de ce que le tick suivant réextrayait. La seule valeur propre de
cette étape était le découpage par thème, et rien ne justifiait de la
réserver à la nuit : elle est ici, appelée par le consolidateur.

Le clustering réutilise les embeddings **stockés** des chunks épisodiques
(ChromaDB, étage 1) — zéro ré-encodage, zéro dépendance nouvelle (numpy
arrive avec chromadb). Rien ne touche la base ni le vector store : la
fenêtre et ses chunks arrivent en arguments, le plan repart en valeur. C'est
ce qui rend le découpage testable sans Chroma, et ce qui laisse au
consolidateur la décision de ne demander les chunks qu'au-delà d'une tranche
— le tick ordinaire de 60 s ne coûte aucune lecture vectorielle.
"""

from __future__ import annotations

from dataclasses import dataclass

from configs.runtime import cfg_float, cfg_int

# Replis des trois réglages du regroupement. Le préfixe ``memory.reorg_`` est
# historique : ces clés sont nées dans la réorganisation nocturne, et les
# renommer aurait perdu la valeur réglée de chaque installation. Le schéma
# (memory/config_schema.py) les range sous « Extraction par thème ».
CLUSTER_SIMILARITY = 0.55
MAX_CLUSTERS = 20
# Un thème plus petit que ça n'est pas perdu : il rejoint la tranche
# résiduelle plutôt que de coûter un appel LLM pour un chunk minuscule.
MIN_CLUSTER_CHARS = 200


@dataclass(frozen=True)
class ThemeTuning:
    """Les trois réglages résolus, passés en valeur aux fonctions pures."""

    similarity: float = CLUSTER_SIMILARITY
    max_clusters: int = MAX_CLUSTERS
    min_cluster_chars: int = MIN_CLUSTER_CHARS


def theme_tuning() -> ThemeTuning:
    """Lit le registre — le seul endroit du module qui le fait.

    Lu à l'appel et non en défaut d'argument : un défaut est évalué à
    l'import, donc avant que la base soit joignable.
    """
    return ThemeTuning(
        similarity=cfg_float(
            "memory.reorg_cluster_similarity", CLUSTER_SIMILARITY, mini=0.3, maxi=0.9,
        ),
        max_clusters=cfg_int(
            "memory.reorg_max_clusters", MAX_CLUSTERS, mini=1, maxi=200,
        ),
        min_cluster_chars=cfg_int(
            "memory.reorg_min_cluster_chars", MIN_CLUSTER_CHARS, mini=0, maxi=5000,
        ),
    )


def cluster_greedy(
    chunks: list[dict], threshold: float, max_clusters: int = MAX_CLUSTERS,
) -> list[list[dict]]:
    """Clustering greedy cosinus sur embeddings stockés. Pur, déterministe
    (ordre chronologique par ``metadata.ts`` ; un chunk sans embedding est
    ignoré).

    Un chunk rejoint le cluster le plus proche si la similarité passe le
    seuil — ou dès que ``max_clusters`` est atteint, un thème de plus étant
    un appel LLM de plus. Les clusters sortent dans l'ordre de leur premier
    chunk, donc dans l'ordre où les sujets sont apparus.
    """
    import numpy as np

    ordered = sorted(
        (c for c in chunks if c.get("embedding") is not None),
        key=lambda c: (c.get("metadata") or {}).get("ts", 0.0),
    )
    clusters: list[dict] = []
    for c in ordered:
        v = np.asarray(c["embedding"], dtype=float)
        norm = float(np.linalg.norm(v)) or 1.0
        v = v / norm
        best, best_sim = None, -1.0
        for cl in clusters:
            sim = float(v @ cl["centroid"])
            if sim > best_sim:
                best, best_sim = cl, sim
        if best is not None and (best_sim >= threshold or len(clusters) >= max_clusters):
            best["items"].append(c)
            best["sum"] = best["sum"] + v
            s_norm = float(np.linalg.norm(best["sum"])) or 1.0
            best["centroid"] = best["sum"] / s_norm
        else:
            clusters.append({"centroid": v, "sum": v.copy(), "items": [c]})
    return [cl["items"] for cl in clusters]


def split_on_message_boundaries(
    messages: list[dict], max_chars: int,
) -> list[list[dict]]:
    """Découpe une suite de messages en tranches ≤ max_chars, aux frontières
    de messages. Un message seul plus gros que la tranche part seul (jamais
    coupé).
    """
    batches: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for m in messages:
        weight = len(m.get("content") or "")
        if current and size + weight > max_chars:
            batches.append(current)
            current, size = [], 0
        current.append(m)
        size += weight
    if current:
        batches.append(current)
    return batches


@dataclass(frozen=True)
class PlanExtraction:
    """Les tranches d'extraction d'une fenêtre, et d'où elles viennent.

    ``themes`` = nombre de thèmes qui sont partis seuls ; ``residuel`` =
    nombre de messages de la tranche résiduelle (sans chunk, ou d'un thème
    trop petit). Chaque message de la fenêtre est dans exactement une
    tranche — c'est l'invariant que ``plan_by_theme`` garantit.
    """

    tranches: list[list[dict]]
    themes: int = 0
    residuel: int = 0


def _taille(messages: list[dict]) -> int:
    return sum(len(m.get("content") or "") for m in messages)


def plan_by_theme(
    messages: list[dict], chunks: list[dict], *, max_chars: int,
    tuning: ThemeTuning,
) -> PlanExtraction:
    """Découpe une fenêtre en tranches d'extraction, par thème.

    ``messages`` : la fenêtre du consolidateur, dans son ordre (chronologique).
    ``chunks`` : les chunks épisodiques dont la plage ``[first_message_id,
    last_message_id]`` chevauche la fenêtre, avec leur embedding stocké.

    1. Chaque chunk se voit attribuer les messages DE LA FENÊTRE que sa
       plage couvre — un message appartient à au plus un chunk, un chunk
       qui déborde de la fenêtre n'y apporte que ce qui en fait partie.
    2. Les chunks sont regroupés par similarité (``cluster_greedy``).
    3. Un cluster devient un thème : ses messages, remis dans l'ordre de la
       fenêtre, découpés sur les frontières de messages si le thème dépasse
       ``max_chars``. Un thème sous ``min_cluster_chars`` rejoint le résiduel.
    4. Le résiduel — les messages qu'aucun chunk ne couvre (l'indexeur
       épisodique a son propre checkpoint et peut être en retard) et les
       thèmes trop petits — part en dernier, en ordre linéaire, découpé de
       même. Sans aucun chunk, le plan EST l'ancien découpage linéaire.
    """
    if not messages:
        return PlanExtraction(tranches=[])

    position = {int(m["id"]): i for i, m in enumerate(messages)}
    par_position = sorted(position.items(), key=lambda kv: kv[0])
    couverts: set[int] = set()
    porteurs: list[dict] = []
    for c in chunks:
        meta = c.get("metadata") or {}
        first, last = meta.get("first_message_id"), meta.get("last_message_id")
        if first is None or last is None or c.get("embedding") is None:
            continue
        first, last = int(first), int(last)
        miens = [
            messages[idx] for mid, idx in par_position
            if first <= mid <= last and mid not in couverts
        ]
        if not miens:
            continue
        couverts.update(int(m["id"]) for m in miens)
        porteur = dict(c)
        porteur["_messages"] = miens
        porteurs.append(porteur)

    tranches: list[list[dict]] = []
    residuel: list[dict] = []
    themes = 0
    for items in cluster_greedy(porteurs, tuning.similarity, tuning.max_clusters):
        du_theme = sorted(
            (m for c in items for m in c["_messages"]),
            key=lambda m: position[int(m["id"])],
        )
        if _taille(du_theme) < tuning.min_cluster_chars:
            residuel.extend(du_theme)
            continue
        themes += 1
        tranches.extend(split_on_message_boundaries(du_theme, max_chars))

    residuel.extend(m for m in messages if int(m["id"]) not in couverts)
    residuel.sort(key=lambda m: position[int(m["id"])])
    tranches.extend(split_on_message_boundaries(residuel, max_chars))
    return PlanExtraction(tranches=tranches, themes=themes, residuel=len(residuel))
