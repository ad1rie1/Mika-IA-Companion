"""Le ``.env`` du dossier courant (ADR 0250, ``app/envfile.py``), lu au démarrage de la commande ``mika`` : des
affectations ``NOM=valeur`` (``export`` permis, guillemets retirés), les commentaires ignorés ; jamais une variable
déjà posée écrasée (en service, celles de ``/etc/mika/mika.env``) ; ``MIKA_ENV_FILE`` vide : rien n'est lu — ce que
posent les tests, qui ne lisent jamais le ``.env`` de qui les lance."""

from __future__ import annotations

import os
import subprocess
import sys

from mika.app import envfile
from mika.app.cli import main

TEXT = """# ma clé, à ne pas commiter
MIKA_GOOGLE_PLACES_API_KEY=cle-du-fichier
export MIKA_ESSAI_EXPORT=exportee
MIKA_ESSAI_GUILLEMETS="avec des espaces"
MIKA_ESSAI_SIMPLES='un # pas un commentaire'
MIKA_ESSAI_COMMENTE=valeur # un commentaire
   # indenté, un commentaire aussi
pas une affectation
3MAUVAIS=non
MIKA_ESSAI_VIDE=
"""


def test_the_file_reads_assignments_and_ignores_comments():
    assert envfile.parse(TEXT) == {
        "MIKA_GOOGLE_PLACES_API_KEY": "cle-du-fichier", "MIKA_ESSAI_EXPORT": "exportee",
        "MIKA_ESSAI_GUILLEMETS": "avec des espaces", "MIKA_ESSAI_SIMPLES": "un # pas un commentaire",
        "MIKA_ESSAI_COMMENTE": "valeur", "MIKA_ESSAI_VIDE": ""}


def test_it_never_overwrites_a_variable_already_set(tmp_path):
    (tmp_path / ".env").write_text(TEXT, encoding="utf-8")
    env = {"MIKA_GOOGLE_PLACES_API_KEY": "celle-du-service", "MIKA_ESSAI_VIDE": "deja"}
    posed = envfile.load(env, cwd=tmp_path)
    assert env["MIKA_GOOGLE_PLACES_API_KEY"] == "celle-du-service" and env["MIKA_ESSAI_VIDE"] == "deja"
    assert env["MIKA_ESSAI_EXPORT"] == "exportee" and "MIKA_GOOGLE_PLACES_API_KEY" not in posed
    assert sorted(posed) == ["MIKA_ESSAI_COMMENTE", "MIKA_ESSAI_EXPORT", "MIKA_ESSAI_GUILLEMETS", "MIKA_ESSAI_SIMPLES"]


def test_another_file_can_be_named_and_an_empty_name_reads_nothing(tmp_path):
    other = tmp_path / "ailleurs.env"
    other.write_text("MIKA_ESSAI_AILLEURS=oui\n", encoding="utf-8")
    (tmp_path / ".env").write_text("MIKA_ESSAI_ICI=oui\n", encoding="utf-8")
    env = {"MIKA_ENV_FILE": str(other)}
    assert envfile.load(env, cwd=tmp_path) == ["MIKA_ESSAI_AILLEURS"]
    assert envfile.load({"MIKA_ENV_FILE": ""}, cwd=tmp_path) == []
    assert envfile.load({}, cwd=tmp_path / "absent") == []


def test_the_tests_never_read_the_env_file_of_whoever_runs_them(tmp_path, monkeypatch):
    assert os.environ.get("MIKA_ENV_FILE") == ""
    (tmp_path / ".env").write_text("MIKA_ESSAI_FUITE=oui\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["--data", str(tmp_path / "data"), "token", "list"]) in (0, 1, 2)
    assert "MIKA_ESSAI_FUITE" not in os.environ
    # un sous-processus hérite de la garde
    run = subprocess.run([sys.executable, "-c", "import os; from mika.app import envfile; envfile.load(); "
                                                "print(os.environ.get('MIKA_ESSAI_FUITE', 'absente'))"],
                         cwd=tmp_path, capture_output=True, text=True, check=True)
    assert run.stdout.strip() == "absente"


def test_the_cli_reads_it_when_asked(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("MIKA_ESSAI_LU=oui\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MIKA_ENV_FILE")
    monkeypatch.delenv("MIKA_ESSAI_LU", raising=False)
    try:
        main(["--data", str(tmp_path / "data"), "token", "list"])
        assert os.environ["MIKA_ESSAI_LU"] == "oui"
    finally:
        os.environ.pop("MIKA_ESSAI_LU", None)
