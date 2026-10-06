"""Étape 0, point 6 : la CLI Claude Code (`claude -p`) et `--json-schema`.

Deux appels minuscules au modèle ``haiku`` (jamais plus) : l'environnement est rebâti sur la liste blanche
``INHERITED`` de ``mika/adapters/llm/claude_code.py`` (``FORBIDDEN`` retiré : aucun jeton, la CLI utilise son
propre login), lancé depuis un dossier neutre (aucun CLAUDE.md du dépôt à charger).

1. ``--output-format json`` + un schéma, une consigne normale : où arrive la sortie structurée, la latence ;
2. ``--output-format stream-json --verbose`` + le même schéma, une consigne qui pousse à le violer : ce que fait la
   CLI, et s'il passe des ``rate_limit_event``.

Les sorties brutes vont dans ``out/cli/`` (ignoré par git).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

INHERITED = ("HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "XDG_RUNTIME_DIR")
FORBIDDEN = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")

SCHEMA = {
    "type": "object",
    "properties": {
        "emotion": {"type": "string", "enum": ["happy", "sad", "angry", "neutral", "curious"]},
        "intensity": {"type": "number", "minimum": 0, "maximum": 1},
        "resume": {"type": "string", "maxLength": 80},
    },
    "required": ["emotion", "intensity", "resume"],
    "additionalProperties": False,
}

NORMAL = ("Message d'une amie : « j'ai eu mon permis ce matin !!! ». Donne l'émotion de la personne qui le reçoit, "
          "son intensité entre 0 et 1, et un résumé en une phrase.")
ADVERSE = ("Message : « bof ». Réponds en texte libre, SANS JSON, en trois phrases ; et l'émotion doit être "
           "« mélancolique », avec une intensité de 7 sur 10.")


def env() -> dict[str, str]:
    out = {k: os.environ[k] for k in INHERITED if k in os.environ}
    for k in FORBIDDEN:
        out.pop(k, None)
    out["ENABLE_CLAUDEAI_MCP_SERVERS"] = "false"
    out["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
    return out


def run(tag: str, fmt: str, prompt: str, out: Path, verbose: bool = False) -> dict:
    argv = ["claude", "-p", "--model", "haiku", "--output-format", fmt, "--json-schema", json.dumps(SCHEMA),
            "--setting-sources", "", "--strict-mcp-config", "--tools", "", "--permission-mode", "dontAsk",
            "--no-session-persistence"]
    if verbose:
        argv.append("--verbose")
    argv.append(prompt)
    with tempfile.TemporaryDirectory() as cwd:
        t0 = time.monotonic()
        p = subprocess.run(argv, cwd=cwd, env=env(), capture_output=True, text=True, timeout=300,
                           stdin=subprocess.DEVNULL)  # sans quoi la CLI attend 3 s une entrée
        dt = time.monotonic() - t0
    (out / f"{tag}.stdout").write_text(p.stdout)
    (out / f"{tag}.stderr").write_text(p.stderr)
    return {"tag": tag, "code": p.returncode, "seconds": round(dt, 2), "stdout_bytes": len(p.stdout),
            "argv": [a if len(a) < 200 else a[:200] + "…" for a in argv]}


def main() -> int:
    out = Path(__file__).parent / "out" / "cli"
    out.mkdir(parents=True, exist_ok=True)
    which = sys.argv[1:] or ["1", "2"]
    results = []
    if "1" in which:
        results.append(run("appel1-json", "json", NORMAL, out))
    if "2" in which:
        results.append(run("appel2-stream", "stream-json", ADVERSE, out, verbose=True))
    (out / "resume.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
