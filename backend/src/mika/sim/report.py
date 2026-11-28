"""Le rapport d'une voie de simulation, en markdown."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from mika.sim.lane import Result


def markdown(results: Sequence[Result], *, day_lines: int = 60) -> str:
    ok = all(r.ok for r in results)
    out = [f"# Simulation — {'tout est vert' if ok else 'des assertions échouent'}", ""]
    out.append("| Scénario | Graine | Verdict | Durée |")
    out.append("|---|---|---|---|")
    for r in results:
        out.append(f"| {r.name} | {r.seed} | {'✔' if r.ok else '✘'} | {r.seconds:.1f} s |")
    for r in results:
        out += ["", f"## {r.name} (graine {r.seed})", ""]
        for c in r.checks:
            mark = "✔" if c.ok else "✘"
            detail = f" — {c.detail}" if c.detail else ""
            out.append(f"- {mark} **{c.name}** ({c.kind}) : {c.why}{detail}")
        keys = ("perceptions", "answered", "initiatives_said", "greetings", "crashes", "repeats", "latency_median_s")
        shown = {k: r.metrics[k] for k in keys if k in r.metrics}
        out += ["", "Mesures : `" + json.dumps(shown, ensure_ascii=False) + "`", ""]
        if r.day:
            out.append("<details><summary>Une journée de sa vie</summary>\n")
            out.append("```")
            out += r.day[:day_lines]
            if len(r.day) > day_lines:
                out.append(f"… ({len(r.day) - day_lines} lignes de plus)")
            out.append("```\n</details>")
    return "\n".join(out) + "\n"


def write(results: Sequence[Result], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "rapport.md"
    path.write_text(markdown(results), encoding="utf-8")
    metrics = [{"name": r.name, "seed": r.seed, "ok": r.ok, "seconds": r.seconds,
                "metrics": {k: v for k, v in r.metrics.items() if k != "abandoned"},
                "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in r.checks]} for r in results]
    (directory / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
