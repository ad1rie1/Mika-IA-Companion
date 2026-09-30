"""Un seul Mika par dossier de données.

Plusieurs ``mika serve`` ont écrit ensemble dans ``data/v2`` : le second échouait en
boucle sur ``events.seq`` et plus rien ne s'écrivait — ni un pas de travail, ni une
opération de la console. Un second processus est désormais refusé, en le disant ;
dans un même processus, le verrou est réentrant.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from mika.app import datadir
from mika.app.cli import main

HOLDER = """
import sys, time
from pathlib import Path
from mika.app import datadir
datadir.hold(Path(sys.argv[1]))
print("tenu", flush=True)
time.sleep(60)
"""


def _other_process_holds(data: Path) -> subprocess.Popen[str]:
    proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(data)], stdout=subprocess.PIPE, text=True)
    assert proc.stdout is not None and proc.stdout.readline().strip() == "tenu"
    return proc


def test_a_second_process_is_refused_and_told_who_holds_the_folder(tmp_path):
    proc = _other_process_holds(tmp_path)
    try:
        with pytest.raises(datadir.DataDirBusy, match=f"pid {proc.pid}"):
            datadir.hold(tmp_path)
        assert main(["--data", str(tmp_path), "forget", "quelqu_un"]) == 3  # une commande qui écrit : refusée
    finally:
        proc.kill()
        proc.wait()
    for _ in range(50):  # mort, le processus rend le dossier
        try:
            datadir.hold(tmp_path)
            break
        except datadir.DataDirBusy:
            time.sleep(0.05)
    datadir.release(tmp_path)


def test_the_same_process_may_open_it_again_and_the_last_holder_frees_it(tmp_path):
    datadir.hold(tmp_path)
    datadir.hold(tmp_path)  # replay --verify ouvre deux fois ; les tests bâtissent plusieurs serveurs
    datadir.release(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):  # encore tenu par ce processus
        subprocess.run([sys.executable, "-c", "import sys; from pathlib import Path; from mika.app import datadir; "
                        "datadir.hold(Path(sys.argv[1]))", str(tmp_path)], check=True, capture_output=True)
    datadir.release(tmp_path)
    subprocess.run([sys.executable, "-c", "import sys; from pathlib import Path; from mika.app import datadir; "
                    "datadir.hold(Path(sys.argv[1]))", str(tmp_path)], check=True, capture_output=True)
