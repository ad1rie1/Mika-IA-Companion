"""Le plan : quelles séances seront rejouées, lesquelles lues par Claude Code, et à quel prix.

Cinq paliers :

- **A** : rejouée et lue à fond (émotions de chacun de ses messages, souvenirs, croyances,
  promesses, événements). Ses notes et son journal sont toujours en A.
- **B** : rejouée, lecture légère (émotions de ses messages, résumé).
- **R** : rejouée sans lecture. Ses mots sont vécus, sans balise d'émotion. Aucun coût.
- **C** : non rejouée, résumée en « savoir d'archive » (souvenirs et faits datés).
- **D** : ignorée (envois de masse, robots, fils vides).

Le plan remplit le budget dans l'ordre de la signifiance : d'abord ses textes, puis les
séances rejouables les plus fortes (A puis B) tant que la lecture le permet, le reste
des rejouables en R, puis le savoir d'archive (C) sur sa part réservée. ``travail/plan.yaml``
porte les curseurs ; relancer ``jumeau planifier`` refait le plan tant que la lecture n'a
pas commencé.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from twin.corpus import Corpus

#: une estimation honnête du nombre de jetons d'un texte français (même règle que le moteur)
CHARS_PER_TOKEN = 3.6
#: ce qu'un lot coûte en plus de son texte (consignes, contexte des personnes)
BATCH_OVERHEAD_TOKENS = 3000

DEFAULTS: dict[str, dict[str, float | int]] = {
    "rejeu": {"messages_max": 1_000_000, "secondes_par_message": 0.05},
    "lecture": {"jetons_max": 50_000_000, "jetons_par_lot": 40_000, "appels_par_heure": 20},
    "paliers": {"signifiance_A": 0.55, "signifiance_min_rejeu": 0.15, "part_C": 0.25},
}

HEADER = """# Le plan du jumeau — régler puis relancer `jumeau planifier`.
# rejeu.messages_max        : plafond de messages vécus par le noyau (voir docs/mesures-etape-0.md)
# rejeu.secondes_par_message: vitesse mesurée de l'avance rapide (pour l'estimation)
# lecture.jetons_max        : ce que Claude Code lira au plus, en jetons d'entrée (tous paliers)
# lecture.jetons_par_lot    : la taille d'un appel ; lecture.appels_par_heure : la cadence observée
# paliers.signifiance_A     : au-dessus, une séance rejouée est lue à fond (sinon légèrement : B)
# paliers.signifiance_min_rejeu : en dessous, une séance n'est jamais rejouée (savoir d'archive au mieux)
# paliers.part_C            : la part du budget de lecture réservée au savoir d'archive (palier C)
"""


@dataclass
class TierStats:
    sessions: int = 0
    messages: int = 0  # messages de conversation (un document n'est pas rejoué comme une conversation)
    tokens: int = 0
    documents: int = 0


@dataclass
class Plan:
    knobs: dict[str, dict[str, float | int]]
    tiers: dict[str, TierStats] = field(default_factory=dict)

    @property
    def read_tokens(self) -> int:
        return sum(self.tiers.get(t, TierStats()).tokens for t in ("A", "B", "C"))

    @property
    def batches(self) -> int:
        per = int(self.knobs["lecture"]["jetons_par_lot"])
        return sum(-(-self.tiers.get(t, TierStats()).tokens // per) for t in ("A", "B", "C"))

    @property
    def read_hours(self) -> float:
        return self.batches / max(1.0, float(self.knobs["lecture"]["appels_par_heure"]))

    @property
    def replayed_messages(self) -> int:
        return sum(self.tiers.get(t, TierStats()).messages for t in ("A", "B", "R"))

    @property
    def replay_hours(self) -> float:
        return self.replayed_messages * float(self.knobs["rejeu"]["secondes_par_message"]) / 3600


def load_knobs(path: Path) -> dict[str, dict[str, float | int]]:
    knobs = {k: dict(v) for k, v in DEFAULTS.items()}
    if path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for section, values in (data or {}).items():
            if section in knobs and isinstance(values, dict):
                for k, v in values.items():
                    if k in knobs[section] and isinstance(v, int | float):
                        knobs[section][k] = v
    return knobs


def tokens_of(chars: int) -> int:
    return int(chars / CHARS_PER_TOKEN) + 1


def plan(corpus: Corpus, plan_path: Path) -> Plan:
    db = corpus.db
    if db.execute("SELECT COUNT(*) FROM sessions WHERE status != 'todo'").fetchone()[0]:
        raise RuntimeError("la lecture a commencé : le plan est figé (seules les séances non lues bougeraient)")
    knobs = load_knobs(plan_path)
    sig_a = float(knobs["paliers"]["signifiance_A"])
    sig_min = float(knobs["paliers"]["signifiance_min_rejeu"])
    max_replay = int(knobs["rejeu"]["messages_max"])
    budget = int(knobs["lecture"]["jetons_max"])
    budget_c = int(budget * float(knobs["paliers"]["part_C"]))
    budget_ab = budget - budget_c
    overhead_per_token = BATCH_OVERHEAD_TOKENS / int(knobs["lecture"]["jetons_par_lot"])

    tiers: dict[int, str] = {}
    rows = db.execute("SELECT id, document, n_messages, chars, significance FROM sessions "
                      "ORDER BY significance DESC, id").fetchall()
    spent_ab = 0
    replayed = 0
    # 1. ses textes à elle : toujours lus à fond
    for r in rows:
        if r["document"] is not None:
            tiers[r["id"]] = "A"
            spent_ab += int(tokens_of(r["chars"]) * (1 + overhead_per_token))
    # 2. les séances rejouables, des plus fortes aux plus faibles
    for r in rows:
        if r["document"] is not None:
            continue
        if r["significance"] <= 0:
            tiers[r["id"]] = "D"
            continue
        if r["significance"] < sig_min or replayed + r["n_messages"] > max_replay:
            continue  # au mieux du savoir d'archive (étape 3)
        cost = int(tokens_of(r["chars"]) * (1 + overhead_per_token))
        replayed += r["n_messages"]
        if spent_ab + cost <= budget_ab:
            tiers[r["id"]] = "A" if r["significance"] >= sig_a else "B"
            spent_ab += cost
        else:
            tiers[r["id"]] = "R"
    # 3. le savoir d'archive, sur sa part
    spent_c = 0
    for r in rows:
        if r["id"] in tiers:
            continue
        cost = int(tokens_of(r["chars"]) * (1 + overhead_per_token))
        if spent_c + cost <= budget_c:
            tiers[r["id"]] = "C"
            spent_c += cost
        else:
            tiers[r["id"]] = "D"

    db.executemany("UPDATE sessions SET tier = ? WHERE id = ?", [(t, sid) for sid, t in tiers.items()])
    db.commit()
    result = Plan(knobs)
    for r in db.execute("SELECT tier, COUNT(*) n, SUM(CASE WHEN document IS NULL THEN n_messages ELSE 0 END) m, "
                        "SUM(chars) c, SUM(document IS NOT NULL) d FROM sessions GROUP BY tier"):
        result.tiers[r["tier"]] = TierStats(r["n"], r["m"] or 0, tokens_of(r["c"] or 0) if r["tier"] in "ABC" else 0,
                                            r["d"] or 0)
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(HEADER + yaml.safe_dump(knobs, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return result
