"""Ce que disent ses balises d'émotion dans des mesures du banc, et combien de réponses « marquent » (ADR 0283).

Les seuils d'« un échange qui marque » (``AttentionParams.marking_intensity``, ``marking_min_intensity``) se lisent sur
l'échelle que sa voix emploie vraiment : cette lecture la mesure, sur les traces d'une ou plusieurs mesures déjà
faites (``appels.jsonl`` — aucun appel au modèle). À refaire quand le modèle de sa voix change.

    PYTHONPATH=src .venv/bin/python tools/banc_conversation/balises.py MESURE [MESURE…] [--seuil 0.6] [--minimum 0.4]

Sans ``--seuil`` ni ``--minimum`` : les réglages par défaut du code. Les deux situations fortes (des mots durs, une
nouvelle qui bouleverse) s'ajoutent à une mesure par ``--variante tools/banc_conversation/variantes/moments_forts.py``.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND / "src"))

from mika.faculties.attention.faculty import AttentionParams, _marking  # noqa: E402
from mika.vocab.affect import Declared  # noqa: E402
from mika.vocab.tag import parse_tag  # noqa: E402

ROOT = BACKEND / "data" / "banc-conversation"


def declared_in(folder: Path) -> list[Declared]:
    """Ce qu'elle a déclaré en finissant chacune de ses réponses d'une conversation (le premier jet : la seconde passe
    garde ses balises)."""
    out = []
    for line in (folder / "appels.jsonl").read_text().splitlines():
        call = json.loads(line)
        if call.get("role") != "reply":
            continue
        answer = call.get("reponse") or {}
        tag = parse_tag(answer.get("texte") or answer.get("text") or "")
        if tag.declared is not None:
            out.append(tag.declared)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mesures", nargs="+")
    ap.add_argument("--seuil", type=float, default=None, help="marking_intensity (défaut : celui du code)")
    ap.add_argument("--minimum", type=float, default=None, help="marking_min_intensity (défaut : celui du code)")
    args = ap.parse_args()
    asked = {k: v for k, v in (("marking_intensity", args.seuil), ("marking_min_intensity", args.minimum))
             if v is not None}
    p = AttentionParams().model_copy(update=asked)
    by: dict[str, list[Declared]] = defaultdict(list)
    for name in args.mesures:
        for folder in sorted(f for f in (ROOT / name).iterdir() if (f / "appels.jsonl").exists()):
            by[folder.name] += declared_in(folder)
    every = [d for rows in by.values() for d in rows]
    if not every:
        raise SystemExit("aucune balise lue dans ces mesures")
    values = Counter(round(d.intensity, 2) for d in every)
    marks = [d for d in every if _marking(d, p)]
    print(f"{len(every)} réponses balisées, {len(by)} scénarios — intensité principale : "
          + "  ".join(f"{k:.1f} × {n}" for k, n in sorted(values.items())))
    print(f"seuils : intensité {p.marking_intensity}, minimum {p.marking_min_intensity}, valence {p.marking_valence} — "
          f"{len(marks)} réponses marquent ({len(marks) * 100 / len(every):.1f} %)")
    for scenario, rows in sorted(by.items()):
        hit = Counter(f"{d.emotion.value} {d.intensity:.1f}" for d in rows if _marking(d, p))
        main_values = [d.intensity for d in rows]
        print(f"  {scenario:16s} {sum(hit.values()):2d} sur {len(rows):2d}   moyenne {statistics.mean(main_values):.2f}, "
              f"plus haut {max(main_values):.1f}   {', '.join(f'{k} × {n}' for k, n in hit.most_common()) or '—'}")


if __name__ == "__main__":
    main()
