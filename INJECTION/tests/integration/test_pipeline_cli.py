"""Toute la chaîne par la ligne de commande, comme l'utilisatrice la lancera : de brut/ à une vie vécue.

Un faux ``claude`` est mis en tête du ``PATH`` : le vrai moteur de sous-processus est exercé, sans quota.
L'avance tourne dans ce processus (``twin.replay.run.main``) plutôt que relancée sous ``borne.sh``.
"""

from __future__ import annotations

import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mika")

from twin.cli import main  # noqa: E402
from twin.replay import run as run_mod  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"

CHAT = "\n".join(
    f"{day:02d}/03/2019 à {h}:{m:02d} - {who}: {text}"
    for day in (11, 12, 13)
    for h, m, who, text in [(9, 0, "Julie Martin", "on se fait un café ?"), (9, 1, "Léa", "carrément !!"),
                            (12, 30, "Julie Martin", "terrasse à 18h ?"), (15, 0, "Léa", "ok parfait")]
) + "\n"


def test_de_brut_a_une_vie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "INJECTION"
    (root / "brut" / "whatsapp").mkdir(parents=True)
    (root / "brut" / "whatsapp" / "Discussion WhatsApp avec Julie Martin.txt").write_text(CHAT, encoding="utf-8")
    (root / "brut" / "notes" / "2019").mkdir(parents=True)
    (root / "brut" / "notes" / "2019" / "12 mars.txt").write_text("Cette nuit j'ai rêvé que je volais.",
                                                                  encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    shutil.copy(FIXTURES / "fake_claude.py", fake)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{__import__('os').environ['PATH']}")

    r = ["--racine", str(root)]
    for cmd in (["ingerer", "--silence"], ["dater"], ["personnes"], ["planifier"], ["lire", "--ouvriers", "2"],
                ["synthetiser", "--ouvriers", "2"], ["avancer", "--preparer"]):
        assert main([*r, *cmd]) == 0, cmd
    assert (root / "sortie" / "persona" / "lea.yaml").is_file()

    assert run_mod.main(["--racine", str(root)]) == 0
    life = root / "sortie" / "vie"
    with sqlite3.connect(life / "mind.db") as db:
        kinds = dict(db.execute("SELECT type, COUNT(*) FROM events GROUP BY type").fetchall())
    assert kinds.get("perception.received") == 6
    assert kinds.get("episode.utterance") == 6
    assert kinds.get("memory.remembered", 0) + kinds.get("memory.believed", 0) > 0
    reports = list((root / "sortie" / "rapport").glob("avance-*.md"))
    assert reports and "arrivée" in reports[0].read_text(encoding="utf-8")

    # l'invariant du moteur : rejouer le journal produit redonne l'état vivant
    engine_python = Path(__file__).resolve().parents[3] / "backendv2" / ".venv" / "bin" / "python"
    python = str(engine_python) if engine_python.is_file() else sys.executable
    verify = subprocess.run([python, "-m", "mika", "--data", str(life), "replay", "--verify"],
                            capture_output=True, text=True, timeout=300)
    assert verify.returncode == 0, verify.stdout[-2000:] + verify.stderr[-2000:]
