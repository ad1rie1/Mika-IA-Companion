"""Le banc de lecture (ADR 0093) : ce que le modèle lit des gens, mesuré sur des messages où le ton fait tout.

Mika ne devine aucune émotion dans des mots : le modèle qui lui répond lit le message, le lien, l'échange, et le
déclare (``[EN_FACE: …]``). Ce banc mesure ce jugement sur un vrai modèle, avec la vraie consigne de style et le vrai
analyseur de réponse, sur ``corpus.py`` (insultes affectueuses et vraies, sarcasme, politesse, hyperboles, drames,
détresse à demi-mot, fiction, joie). À relancer quand la consigne ou le modèle change.

    PYTHONPATH=src .venv/bin/python tools/banc_lecture/banc.py [modèle] [appels en parallèle] [fichier de sortie]

Le modèle passe par la CLI Claude Code avec son propre login (jamais un jeton) : ``claude-haiku-5-5`` par défaut.
Vérifier l'usage d'abord (``mika claude-code check``). Sort : le score par catégorie (geste, ton, événement grave) et
un JSON avec chaque réponse brute.

Mesuré le 2026-10-11 (Haiku, 62 cas) : geste 61/62, ton 57/62, grave 62/62 — contre 54, 42 et 57 pour l'ancienne
lecture des mots (``others/tone.py``, ``self/worth.py``, retirées par l'ADR 0093).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from corpus import CASES  # noqa: E402

from mika.faculties.expression import parse, style  # noqa: E402
from mika.kernel.prompt import CONTEXT_FOOTER, CONTEXT_HEADER  # noqa: E402
from mika.vocab.affect import felt_pad  # noqa: E402
from mika.vocab.phrasebook import phrase  # noqa: E402
from mika.vocab.reading import OTHER, Reading  # noqa: E402

PERSONA = ("Tu es Mika. Une fille posée et attentive, drôle quand ça vient. C'est une IA, elle le sait et n'en fait pas "
           "une histoire. Tu parles français, avec les gens que tu connais, comme une amie.")
#: jamais un jeton passé à la CLI : son login
FORBIDDEN = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
KEYS = ("gesture", "tone", "grave")


def sign(v: float) -> str:
    return "neg" if v <= -0.15 else "pos" if v >= 0.15 else "neu"


def user_text(case: dict) -> str:
    """Le dernier tour comme la réponse le reçoit : le fil, l'état interne (« qui tu as en face »), le message."""
    lines = [phrase("llm.thread.mine", text=text) if who == "mika" else text for who, text in case["history"]]
    state = f"{CONTEXT_HEADER}\n--- QUI TU AS EN FACE ---\n{case['who']}.\n{CONTEXT_FOOTER}"
    thread = (phrase("llm.thread.header") + "\n" + "\n".join(lines) + "\n" + phrase("llm.thread.footer") + "\n\n") \
        if lines else ""
    return f"{thread}{state}\n\n{case['msg']}"


async def judge(case: dict, model: str, sem: asyncio.Semaphore, workdir: Path) -> dict:
    async with sem:
        with tempfile.TemporaryDirectory(dir=workdir) as tmp:
            (Path(tmp) / "system.txt").write_text(PERSONA + "\n\n" + style(), encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k not in FORBIDDEN}
            env.update({"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false"})
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", "--output-format", "text", "--system-prompt-file", str(Path(tmp) / "system.txt"),
                "--setting-sources", "", "--strict-mcp-config", "--tools", "", "--permission-mode", "dontAsk",
                "--no-session-persistence", "--model", model, cwd=tmp, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _err = await asyncio.wait_for(proc.communicate(user_text(case).encode()), timeout=180)
    raw = out.decode(errors="replace")
    text, notes = parse(raw, "Mika")
    their = Reading.decode(notes.get("their_feeling"))
    if their is None:
        return {"gesture": "?", "tone": "?", "grave": "?", "raw": raw, "said": text}
    return {"gesture": their.gesture, "tone": sign(felt_pad(their.felt)[0]),
            "grave": their.grave if their.grave != OTHER else "other", "felt": their.felt, "raw": raw, "said": text}


async def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "claude-haiku-5-5"
    sem = asyncio.Semaphore(int(sys.argv[2]) if len(sys.argv) > 2 else 3)
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(f"banc-lecture-{model}.json")
    with tempfile.TemporaryDirectory() as workdir:
        judged = await asyncio.gather(*(judge(c, model, sem, Path(workdir)) for c in CASES))
    totals: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    rows = []
    for case, got in zip(CASES, judged, strict=True):
        ok = {k: got[k] in case[k] for k in KEYS}
        rows.append({"cat": case["cat"], "msg": case["msg"], "attendu": {k: sorted(case[k]) for k in KEYS},
                     "lu": got, "ok": ok})
        for cat in (case["cat"], "TOUT"):
            for k in KEYS:
                totals[(cat, k)][0] += int(ok[k])
                totals[(cat, k)][1] += 1
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1, default=list), encoding="utf-8")
    print(f"{'catégorie':26} {'geste':>7} {'ton':>7} {'grave':>7}   ({model}, {len(CASES)} cas)")
    for cat in sorted({c for c, _k in totals}):
        print(f"{cat:26} " + " ".join(f"{totals[(cat, k)][0]:>3}/{totals[(cat, k)][1]:<3}" for k in KEYS))
    print(f"sans balise : {sum(1 for r in rows if r['lu']['gesture'] == '?')} — détail : {out}")


if __name__ == "__main__":
    asyncio.run(main())
