"""Lancer l'avance rapide : préparer le script, geler le moteur, vivre, écrire le rapport.

``jumeau avancer`` (dans ``cli.py``) prépare puis relance ce module **dans un processus à part** :

- sous ``borne.sh`` : un plafond de mémoire, une seule avance à la fois ;
- avec ``PYTHONPATH`` sur une copie **gelée** de ``backendv2/src``. D'autres sessions modifient
  le moteur pendant qu'on avance, et une erreur de syntaxe à mi-chemin ruinerait des heures
  de rejeu ;
- avec BLAS sur un seul fil : 28 % plus rapide (étape 0).

    python -m twin.replay.run --racine INJECTION [--jusqu-a 2015-06-01]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from twin.corpus import Corpus
from twin.passes.synth import validate_persona
from twin.paths import default_root

BORNE = Path.home() / "recup-audit-v2-2026-10-01" / "outils" / "borne.sh"


def frozen_engine(root: Path) -> Path:
    """Une copie de ``backendv2/src`` (et de sa persona) sous ``travail/moteur-gele/<empreinte>`` : la même
    tant que le moteur ne change pas, une nouvelle s'il a changé."""
    src = root.parent / "backendv2" / "src"
    h = hashlib.sha256()
    for f in sorted(src.rglob("*.py")):
        h.update(str(f.relative_to(src)).encode())
        h.update(f.read_bytes())
    target = root / "travail" / "moteur-gele" / h.hexdigest()[:12]
    if not (target / "src" / "mika").is_dir():
        tmp = target.with_suffix(".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(src, tmp / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        persona = root.parent / "backendv2" / "persona"
        if persona.is_dir():
            shutil.copytree(persona, tmp / "persona")
        tmp.rename(target)
    return target


def launch(root: Path, tz: str, until: str | None, mem: str = "3G", hours: int = 72) -> int:
    """Relance l'avance dans un processus borné, sur le moteur gelé. Rend son code de sortie."""
    frozen = frozen_engine(root)
    env = {**os.environ, "PYTHONPATH": f"{frozen / 'src'}{os.pathsep}{root / 'src'}",
           "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
           "BORNE_MEM": mem, "BORNE_TEMPS": str(hours * 3600)}
    cmd = [sys.executable, "-m", "twin.replay.run", "--racine", str(root), "--fuseau", tz]
    if until:
        cmd += ["--jusqu-a", until]
    if BORNE.is_file():
        cmd = [str(BORNE), *cmd]
    print(f"Moteur gelé : {frozen}")
    os.execvpe(cmd[0], cmd, env)  # le processus devient l'avance : Ctrl+C l'arrête proprement, on reprendra


def persona_docs(root: Path, corpus: Corpus) -> dict[str, dict]:  # type: ignore[type-arg]
    """Ses personas, par clé (``chapitre-N``, ``actuelle``) : **les fichiers relus** de ``sortie/persona/`` d'abord
    (ce que ``/jumeau-persona`` a corrigé à la main), la table ``syntheses`` ensuite. Un fichier refusé par le
    moteur arrête tout, en le disant : on ne fait pas vivre une persona qu'on n'a pas pu lire."""
    docs: dict[str, dict] = {}  # type: ignore[type-arg]
    if corpus.db.execute("SELECT 1 FROM sqlite_master WHERE name = 'syntheses'").fetchone():
        docs.update({r["key"]: json.loads(r["data"]) for r in corpus.db.execute(
            "SELECT key, data FROM syntheses WHERE kind = 'persona' ORDER BY version")})
    folder = root / "sortie" / "persona"
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else ():
        m = re.search(r"-(chapitre-\d+)$", path.stem)
        key = m.group(1) if m else "actuelle"
        try:
            docs[key] = validate_persona(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        except (ValueError, yaml.YAMLError) as exc:
            raise SystemExit(f"{path} : persona illisible ou refusée par le moteur — {exc}") from exc
    return docs


def personas(root: Path, corpus: Corpus) -> tuple[dict, dict]:  # type: ignore[type-arg]
    docs = persona_docs(root, corpus)
    final = docs.get("actuelle")
    if final is None:
        raise SystemExit("Pas de persona : lancer d'abord `jumeau synthetiser` (étapes mois, chapitres, persona).")
    return docs.get("chapitre-1", final), final


def write_report(root: Path, stats: dict[str, int], gaps: list[str], started: float) -> Path:
    folder = root / "sortie" / "rapport"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d-%H%M")
    path = folder / f"avance-{stamp}.md"
    minutes = (datetime.now().astimezone().timestamp() - started) / 60
    lines = [f"# Avance rapide du {stamp}", "", f"Durée : {minutes:.0f} min de calcul.", "", "## Comptes", ""]
    lines += [f"- {k} : {v}" for k, v in sorted(stats.items())]
    lines += ["", f"## Écarts ({len(gaps)})", ""] + [f"- {g}" for g in gaps[:500]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / f"avance-{stamp}.json").write_text(json.dumps({"stats": stats, "gaps": gaps}, ensure_ascii=False,
                                                            indent=1), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    from twin.replay import driver  # noqa: PLC0415 — n'importe le moteur que dans le processus de l'avance

    ap = argparse.ArgumentParser(prog="python -m twin.replay.run")
    ap.add_argument("--racine", type=Path, default=default_root())
    ap.add_argument("--fuseau", default="Europe/Paris")
    ap.add_argument("--jusqu-a", dest="until", help="s'arrêter à cette date (AAAA-MM-JJ) ; on reprendra")
    args = ap.parse_args(argv)
    tz = ZoneInfo(args.fuseau)
    corpus = Corpus(args.racine / "travail" / "corpus.db")
    start, final = personas(args.racine, corpus)
    until = int(datetime.fromisoformat(args.until).replace(tzinfo=tz).timestamp() * 1_000_000) if args.until else None
    began = datetime.now().astimezone().timestamp()
    report = driver.run(corpus, args.racine / "sortie" / "vie", tz, start_persona=start, final_persona=final,
                        until=until)
    path = write_report(args.racine, dict(report.stats), report.gaps, began)
    print(f"Rapport : {path}")
    if "arrivée" in report.stats:
        print("Arrivée : sa vie est vécue. Vérifier puis servir :\n"
              f"  backendv2/.venv/bin/python -m mika --data {args.racine / 'sortie' / 'vie'} replay --verify\n"
              f"  backendv2/.venv/bin/python -m mika --data {args.racine / 'sortie' / 'vie'} serve --port 8001")
    corpus.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
