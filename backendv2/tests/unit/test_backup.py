"""Preuve M8 — sauvegarde → restauration → même état.

Une journée vécue pour de vrai (conversation, consolidation, index) ; on
archive, on restaure ailleurs, et l'on retrouve : le même état rejoué, les
mêmes souvenirs, le même index de vecteurs une fois reconstruit (``views.db``
n'est pas sauvegardée), ses secrets lisibles, ses ateliers et ses apps. Une
archive altérée est refusée sans rien toucher ; un dossier occupé n'est
remplacé qu'à la demande, et mis de côté.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from mika.adapters.llm.config import BackendSpec, LLMConfig
from mika.adapters.maps.quota import QUOTAS_FILE, QuotaStore
from mika.adapters.store_sql import SqlStore
from mika.adapters.workshop import VIEWS_DIRNAME
from mika.app import backup, datadir
from mika.app.cli import main
from mika.app.cli.journal import replay_verify
from mika.app.settings import SecretBox, Settings
from mika.contracts import memory as memory_c
from mika.sim.clock import SimClock, run_virtual
from mika.sim.llm.persona import PersonaSimLLM
from tests.fixtures.mika import AFTERNOON, boot, build, connect, said

#: la sauvegarde des fichiers SQLite du dossier ; celle d'un serveur MariaDB : ``test_backup_server.py``
pytestmark = pytest.mark.sqlite_only

WEEK = [
    "Mardi j'ai un entretien d'embauche chez Ubisoft, je stresse un peu",
    "Samedi c'est le mariage de ma sœur Julie à Lyon",
    "Mon chat Moustache est malade depuis dimanche",
    "Je me suis mise à la course à pied, cinq kilomètres ce matin",
    "J'ai fini de lire Dune hier soir, c'était génial",
    "Au fait je déménage le mois prochain à Nantes",
]
CANARY_KEY = "sk-ant-api-canari-7f3a"


def live(data: Path, *, start: int = AFTERNOON, talk: bool = True) -> dict:
    """Fait vivre Mika sur ``data`` ; rend ce qu'on comparera."""
    clock = SimClock(start)
    llm = PersonaSimLLM(clock, seed=1, latency=2.0, abstain_rate=0.0)
    kernel, clock, _, _ = build(data, lambda req: None, clock=clock, llm=llm)

    async def main() -> dict:
        await boot(kernel)
        if talk:
            await connect(kernel, "user_2", "Alice")
            for text in WEEK:
                await (await kernel.perceive(said("user_2", text))).reply
                await asyncio.sleep(60)
        await asyncio.sleep(15 * 60)  # consolidation, puis index des vecteurs
        await kernel.lanes.join()
        out = {
            "items": sorted(kernel.mind.store.query_mind(
                f"SELECT id, kind, text, about, status FROM {memory_c.ITEMS_TABLE}")),
            "vectors": kernel.ports["vectors"].digest(),
            "indexed": len(kernel.ports["vectors"].indexed()),
        }
        await kernel.stop()
        return out

    return run_virtual(clock, main)


def settle(data: Path) -> None:
    """Ce qui vit hors du journal : un secret chiffré, un atelier, une app."""

    async def run() -> None:
        store = SqlStore(data / "mind.db", data / "views.db", threaded=False)
        await store.open()
        settings = Settings(store, SecretBox.for_data(data))
        await settings.open()
        await settings.save_llm(LLMConfig(backends={"claude": BackendSpec(kind="claude", model="claude-sonnet-5",
                                                                          api_key=CANARY_KEY)}))
        await store.close()

    asyncio.run(run())
    (data / "ateliers" / "3-bonjour").mkdir(parents=True)
    (data / "ateliers" / "3-bonjour" / "bonjour.py").write_text("print('bonjour')\n", encoding="utf-8")
    (data / "forge" / "cafe").mkdir(parents=True)
    (data / "forge" / "cafe" / "manifest.yaml").write_text("title: Veille café\n", encoding="utf-8")


def secret_of(data: Path) -> str:
    async def run() -> str:
        store = SqlStore(data / "mind.db", data / "views.db", threaded=False)
        await store.open()
        settings = Settings(store, SecretBox.for_data(data))
        key = settings.llm().backends["claude"].api_key
        await store.close()
        return key

    return asyncio.run(run())


def test_backup_restore_rebuild_gives_back_the_same_life(tmp_path, monkeypatch):
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest, restored = tmp_path / "data", tmp_path / "archives", tmp_path / "restauree"
    before = live(data)
    assert before["items"] and before["indexed"] > 0  # une vraie journée : souvenirs et vecteurs
    settle(data)
    original = backup.state_of(data / "mind.db")

    made = backup.backup(data, dest)
    assert (made.head, made.state) == original  # l'état rejoué depuis la copie est celui du dossier
    assert made.archive.name.startswith("mika-") and made.files >= 4
    with tarfile.open(made.archive) as tar:
        names = tar.getnames()
    assert "data/mind.db" in names and "data/secret.key" in names and "data/MANIFEST.json" in names
    assert "data/ateliers/3-bonjour/bonjour.py" in names and "data/forge/cafe/manifest.yaml" in names
    assert not any(n.startswith("data/views.db") for n in names)  # jetable : reconstruite
    assert backup.verify(made.archive).state == made.state

    back = backup.restore(made.archive, restored)
    assert (back.head, back.state) == original
    assert not (restored / "views.db").exists()
    assert asyncio.run(replay_verify(restored))["identiques"]  # rejeu depuis la genèse = instantané + queue
    assert secret_of(restored) == CANARY_KEY  # ses clés restent lisibles
    assert (restored / "ateliers" / "3-bonjour" / "bonjour.py").read_text() == "print('bonjour')\n"

    # elle redémarre sur la copie : les vues se reconstruisent à l'identique
    after = live(restored, start=AFTERNOON + 3600 * 10**6, talk=False)
    assert after["items"] == before["items"]
    assert after["vectors"] == before["vectors"] and after["indexed"] == before["indexed"]


def test_an_altered_archive_is_refused_and_nothing_is_touched(tmp_path, monkeypatch):
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    made = backup.backup(data, dest)
    unpacked = tmp_path / "déballée"
    with tarfile.open(made.archive) as tar:
        tar.extractall(unpacked, filter="data")
    target = unpacked / "data" / "mind.db"
    raw = bytearray(target.read_bytes())
    raw[len(raw) // 2] ^= 0xFF  # un octet de travers suffit
    target.write_bytes(bytes(raw))
    forged = dest / "mika-falsifiee.tar.gz"
    with tarfile.open(forged, "w:gz") as tar:
        tar.add(unpacked / "data", arcname="data")
    victim = tmp_path / "cible"
    with pytest.raises(backup.BackupError, match="altéré"):
        backup.restore(forged, victim)
    assert not victim.exists()
    with pytest.raises(backup.BackupError, match="altéré"):
        backup.verify(forged)


def test_an_archive_that_does_not_replay_to_its_manifest_is_refused(tmp_path, monkeypatch):
    """Des sommes justes ne suffisent pas : la copie doit rejouer à l'état annoncé."""
    import json

    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    made = backup.backup(data, dest)
    unpacked = tmp_path / "déballée"
    with tarfile.open(made.archive) as tar:
        tar.extractall(unpacked, filter="data")
    manifest = unpacked / "data" / "MANIFEST.json"
    content = json.loads(manifest.read_text(encoding="utf-8"))
    content["state"] = "0" * 32  # un autre état annoncé, fichiers intacts
    manifest.write_text(json.dumps(content), encoding="utf-8")
    forged = dest / "mika-autre-etat.tar.gz"
    with tarfile.open(forged, "w:gz") as tar:
        tar.add(unpacked / "data", arcname="data")
    victim = tmp_path / "cible"
    with pytest.raises(backup.BackupError, match="ne rejoue pas"):
        backup.restore(forged, victim)
    assert not victim.exists()
    with pytest.raises(backup.BackupError, match="ne rejoue pas"):
        backup.verify(forged)


def test_an_occupied_folder_is_replaced_only_on_demand_and_kept_aside(tmp_path, monkeypatch):
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    made = backup.backup(data, dest)
    occupied = tmp_path / "occupee"
    occupied.mkdir()
    (occupied / "mind.db").write_bytes(b"une autre vie")
    with pytest.raises(backup.BackupError, match="n'est pas vide"):
        backup.restore(made.archive, occupied)
    assert (occupied / "mind.db").read_bytes() == b"une autre vie"
    done = backup.restore(made.archive, occupied, force=True)
    aside = [p for p in occupied.iterdir() if p.name.startswith(backup.ASIDE)]
    assert len(aside) == 1 and (aside[0] / "mind.db").read_bytes() == b"une autre vie"
    assert done.state == made.state
    with pytest.raises(backup.BackupError, match="destination"):
        backup.backup(data, data / "archives")


@pytest.mark.skipif(os.geteuid() == 0, reason="root écrit partout : le dossier parent fermé ne se ferme pas à lui")
def test_a_restore_writes_nothing_beside_the_folder(tmp_path, monkeypatch):
    """En service, le dossier de données (``/var/lib/mika``) est à l'utilisateur ``mika``, pas son parent
    (``/var/lib``) : la restauration prépare, met de côté et pose tout dans le dossier même. Le modèle de
    plongements (``cache/``, jamais archivé) reste en place ; l'ancien contenu mis de côté n'entre dans aucune
    archive suivante."""
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    made = backup.backup(data, dest)
    parent = tmp_path / "var-lib"
    service = parent / "mika"
    service.mkdir(parents=True)
    (service / "mind.db").write_bytes(b"la vie d'avant")
    (service / "cache").mkdir()
    (service / "cache" / "modele.bin").write_bytes(b"1,2 Go")
    parent.chmod(0o555)
    try:
        done = backup.restore(made.archive, service, force=True)
    finally:
        parent.chmod(0o755)
    assert done.state == made.state
    assert sorted(p.name for p in parent.iterdir()) == ["mika"]  # rien à côté du dossier
    aside = [p for p in service.iterdir() if p.name.startswith(backup.ASIDE)]
    assert len(aside) == 1 and (aside[0] / "mind.db").read_bytes() == b"la vie d'avant"
    assert (service / "cache" / "modele.bin").read_bytes() == b"1,2 Go"
    assert not (aside[0] / "cache").exists()
    again = backup.backup(service, tmp_path / "suivantes")
    with tarfile.open(again.archive) as tar:
        assert not any(backup.ASIDE in name or "/cache/" in name for name in tar.getnames())


def test_old_archives_are_pruned(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    for day in range(1, 5):
        backup.backup(data, dest, keep=2, now=datetime(2026, 9, day, 3, 0, tzinfo=UTC))
    assert sorted(p.name for p in dest.glob("mika-*.tar.gz")) == ["mika-20260903-030000.tar.gz",
                                                                  "mika-20260904-030000.tar.gz"]


def test_each_backup_and_verification_is_noted_for_the_console(tmp_path, monkeypatch):
    """La console (Système › Stockage et sauvegardes) lit la dernière sauvegarde et la dernière vérification ; la note
    vit dans le dossier de données mais n'entre pas dans les archives."""
    from datetime import UTC, datetime

    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    monkeypatch.setattr(backup, "UNIT_DIRS", (tmp_path / "systemd",))  # un poste de travail : aucune unité
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    fresh = backup.overview(data)
    # jamais sauvegardée ; le dossier de données en chemin absolu, pour les commandes de la page (C8-04)
    assert {k: v for k, v in fresh.items() if k != "place"} == {"archives": [], "donnees": str(data.resolve()),
                                                                 "unite": ""}
    assert callable(fresh["place"])  # la place se mesure à la demande : jamais pour l'accueil
    made = backup.backup(data, dest, keep=3, now=datetime(2026, 9, 30, 3, 0, tzinfo=UTC))
    seen = backup.overview(data)
    last = seen["sauvegarde"]
    assert last["archive"] == str(made.archive) and last["tete"] == made.head and last["garde"] == 3
    assert last["at"] == int(datetime(2026, 9, 30, 3, 0, tzinfo=UTC).timestamp() * 1_000_000)
    assert [a["nom"] for a in seen["archives"]] == [made.archive.name]
    with tarfile.open(made.archive) as tar:
        assert not any(backup.RECORD in m for m in tar.getnames())
    backup.verify(made.archive, record=data)
    assert backup.recorded(data)["verification"]["ok"] is True
    forged = dest / "mika-19990101-000000.tar.gz"
    forged.write_bytes(b"pas une archive")
    with pytest.raises(backup.BackupError):
        backup.verify(forged, record=data)
    failed = backup.recorded(data)["verification"]
    assert failed["ok"] is False and failed["erreur"] and backup.recorded(data)["sauvegarde"] == last


def test_the_backup_unit_counts_only_when_installed_for_this_data_folder(tmp_path, monkeypatch):
    """La page Stockage et sauvegardes dit « sudo systemctl start mika-backup.service » là où l'unité de sauvegarde
    est installée pour ce dossier de données (son ``--data``), la commande complète ailleurs (audit du 2026-11-05,
    C8-04) : l'unité livrée (``deploy/mika-backup.service``) se reconnaît ; une unité qui sauvegarde un autre dossier,
    non."""
    units = tmp_path / "systemd"
    units.mkdir()
    monkeypatch.setattr(backup, "UNIT_DIRS", (tmp_path / "absent", units))
    data = tmp_path / "var-lib-mika"
    assert backup.backup_unit(data) == ""  # pas installée
    shipped = (Path(__file__).parents[2] / "deploy" / backup.BACKUP_UNIT).read_text(encoding="utf-8")
    assert "--data /var/lib/mika backup" in shipped
    (units / backup.BACKUP_UNIT).write_text(shipped.replace("/var/lib/mika ", f"{data} "), encoding="utf-8")
    assert backup.backup_unit(data) == backup.BACKUP_UNIT == "mika-backup.service"
    assert backup.backup_unit(tmp_path / "data") == ""  # installée, mais pour un autre dossier
    assert backup.overview(data)["unite"] == backup.BACKUP_UNIT


def test_the_console_sees_each_base_and_folder_and_what_the_backup_does_with_it(tmp_path, monkeypatch):
    """Système › Stockage et sauvegardes (C9-10, audit du 2026-11-05) : une ligne par base et par dossier du dossier de
    données — sa place (une base avec son journal d'écriture), ce qu'il garde, ce que la sauvegarde en fait (d'après
    ``SKIPPED`` et ``SKIPPED_DIRS``) ; sous MariaDB, ses bases sont sur le serveur, sans taille de fichier."""
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    monkeypatch.delenv("MIKA_DATABASE_URL", raising=False)
    data = tmp_path / "data"
    live(data, talk=False)
    (data / "pieces" / "bea").mkdir(parents=True)
    (data / "pieces" / "bea" / "devis.pdf").write_bytes(b"x" * 3000)
    (data / "cartes").mkdir()
    (data / "cartes" / "lieux.db").write_bytes(b"y" * 500)
    (data / ".avant-restauration-20260930").mkdir()
    rows = {r["nom"]: r for r in backup.overview(data)["place"]()}
    assert rows["mind.db"]["sauvegarde"] == "oui" and rows["mind.db"]["octets"] > 0
    assert "journal" in rows["mind.db"]["garde"]
    assert rows["views.db"]["sauvegarde"] == "jetable"
    assert rows["pieces"]["dossier"] and rows["pieces"]["octets"] == 3000 and rows["pieces"]["sauvegarde"] == "oui"
    assert rows["cartes"]["sauvegarde"] == "réextrait" and rows["cartes"]["octets"] == 500
    assert rows[".avant-restauration-20260930"]["sauvegarde"] == "mis de côté"
    assert datadir.LOCK_NAME not in rows and not any(n.endswith(("-wal", "-shm")) for n in rows)
    monkeypatch.setenv("MIKA_DATABASE_URL", "mariadb+pymysql://mika@localhost/")
    served = [r for r in backup.place(data) if r["serveur"]]
    assert [r["nom"] for r in served] == ["mind", "mail", "feeds", "teams", "views"]
    assert all(r["octets"] is None for r in served) and served[-1]["sauvegarde"] == "jetable"


def test_what_each_place_keeps_is_said_without_an_adr_number():
    """La colonne « ce qu'il garde » de Système › Stockage et sauvegardes est lue par une opératrice : la règle en
    clair, sans numéro d'ADR (ADR 0225) ; les renvois sont dans le commentaire de ``PLACES`` (K10-13, audit du
    2026-11-05)."""
    cited = {name: said for name, said in backup.PLACES.items() if re.search(r"ADR\s*\d", said)}
    assert cited == {}
    assert "2 Gio par personne" in backup.PLACES["pieces"]


def test_a_restore_under_a_running_mika_is_refused_and_touches_nothing(tmp_path, monkeypatch):
    """Un serveur tient le dossier : restaurer par-dessus (même avec --force) le couperait en deux —
    il écrirait encore, par ses descripteurs ouverts, dans le dossier mis de côté. Refusé, rien ne bouge."""
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    made = backup.backup(data, dest)
    running = tmp_path / "en-marche"
    running.mkdir()
    (running / "mind.db").write_bytes(b"la vie en cours")
    holder = subprocess.Popen([sys.executable, "-c", "import sys, time\nfrom pathlib import Path\n"
                               "from mika.app import datadir\ndatadir.hold(Path(sys.argv[1]))\n"
                               "print('tenu', flush=True)\ntime.sleep(60)\n", str(running)],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "tenu"
        with pytest.raises(datadir.DataDirBusy):
            backup.restore(made.archive, running, force=True)
        assert main(["--data", str(running), "restore", str(made.archive), "--force"]) == 3  # dit, refusé
    finally:
        holder.kill()
        holder.wait()
    assert (running / "mind.db").read_bytes() == b"la vie en cours"
    assert not [p for p in running.iterdir() if p.name.startswith((backup.ASIDE, backup.STAGING))]
    # serveur arrêté : la restauration passe, et le verrou reste en place
    done = backup.restore(made.archive, running, force=True)
    assert done.state == made.state and (running / datadir.LOCK_NAME).exists()
    datadir.hold(running)  # rendu à la fin : ce processus le reprend
    datadir.release(running)


def test_workshop_symlinks_survive_a_backup_and_their_history_stays_clean(tmp_path, monkeypatch):
    """Un atelier est un dépôt git : un lien symbolique perdu à la sauvegarde, c'est sa suppression
    enregistrée au prochain commit (``git add -A``). Les liens reviennent tels quels, cible comprise."""
    if shutil.which("git") is None:
        pytest.skip("git absent")
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest, restored = tmp_path / "data", tmp_path / "archives", tmp_path / "restauree"
    live(data, talk=False)
    shop = data / "ateliers" / "4-liens"
    (shop / "docs").mkdir(parents=True)
    (shop / "cible.txt").write_text("bonjour\n", encoding="utf-8")
    (shop / "lien.txt").symlink_to("cible.txt")
    (shop / "docs" / "vers-cible.txt").symlink_to("../cible.txt")
    (shop / "systeme").symlink_to("/usr/bin")  # hors du dossier : gardé comme lien, jamais suivi (une cage)
    git = ["git", "-c", "user.name=Mika", "-c", "user.email=mika@localhost", "-C", str(shop)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "liens"], check=True)

    made = backup.backup(data, dest)
    with tarfile.open(made.archive) as tar:
        assert "data/ateliers/4-liens/cible.txt" in tar.getnames()
    backup.restore(made.archive, restored)
    back = restored / "ateliers" / "4-liens"
    assert os.readlink(back / "lien.txt") == "cible.txt" and (back / "lien.txt").read_text() == "bonjour\n"
    assert os.readlink(back / "docs" / "vers-cible.txt") == "../cible.txt"
    assert os.readlink(back / "systeme") == "/usr/bin"
    status = subprocess.run(["git", "-C", str(back), "status", "--porcelain"], check=True, capture_output=True,
                            text=True).stdout
    assert status == ""  # rien à commettre : aucune suppression de lien


def test_the_views_of_other_workshops_are_never_archived(tmp_path):
    """Une vue (``ateliers/.vues``, ADR 0260) est la copie du dernier commit d'un autre atelier, que l'archive porte
    déjà avec son dépôt, et elle se repose seule à l'exécution suivante (ADR 0262) : ni ses fichiers ni ses liens
    n'entrent dans une archive. Le reste des ateliers y entre comme avant — leur dépôt, leur dossier ``liens/`` à
    eux."""
    data = tmp_path / "data"
    read, reader = data / "ateliers" / "projet-1", data / "ateliers" / "projet-2"
    view = data / "ateliers" / VIEWS_DIRNAME / "projet-2" / "projet-1" / ("a" * 40)
    for folder in (read / ".git", reader / "liens", view / "src"):
        folder.mkdir(parents=True)
    for path, text in ((read / "README.md", "le produit\n"), (read / ".git" / "HEAD", "ref: refs/heads/main\n"),
                       (reader / "notes.md", "mes notes\n"), (reader / "liens" / "utiles.md", "des liens à lui\n"),
                       (view / "README.md", "le produit\n"), (view / "src" / "module.py", "x = 1\n")):
        path.write_text(text, encoding="utf-8")
    (view / "lien").symlink_to("README.md")
    files, links = backup._walk(data)
    assert {str(f) for f in files} == {
        "ateliers/projet-1/README.md", "ateliers/projet-1/.git/HEAD", "ateliers/projet-2/notes.md",
        "ateliers/projet-2/liens/utiles.md"}
    assert links == [] and backup._members(data) == files
    assert VIEWS_DIRNAME == ".vues" and ("ateliers", VIEWS_DIRNAME) in backup.SKIPPED_UNDER


def test_an_archive_whose_link_would_escape_the_folder_is_refused(tmp_path, monkeypatch):
    """Un lien ne se recrée jamais hors du dossier, ni à travers un autre lien qui en sort ; et hors des cages
    (``ateliers/``, ``mcp/``), sa cible ne sort pas du dossier non plus — ni absolue ni remontante : le serveur
    ouvrirait lui-même ``partages/<id>.bin → /etc/…``."""
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    made = backup.backup(data, dest)
    outside = tmp_path / "dehors"
    outside.mkdir()
    for links in ({"../evade": "x"}, {"a": str(outside), "a/b/c": "x"},
                  {"partages/fuite.bin": "/etc/passwd"},  # une cible absolue
                  {"pieces/fuite.bin": "../../dehors/x"},  # une cible qui remonte hors du dossier
                  {"forge/app/app.py": "../../../dehors/x"}):  # la Forge n'est pas une cage pour le serveur, qui la lit
        unpacked = tmp_path / "déballée"
        shutil.rmtree(unpacked, ignore_errors=True)
        with tarfile.open(made.archive) as tar:
            tar.extractall(unpacked, filter="data")
        manifest = unpacked / "data" / "MANIFEST.json"
        content = json.loads(manifest.read_text(encoding="utf-8"))
        content["links"] = links
        manifest.write_text(json.dumps(content), encoding="utf-8")
        forged = dest / "mika-liens.tar.gz"
        with tarfile.open(forged, "w:gz") as tar:
            tar.add(unpacked / "data", arcname="data")
        victim = tmp_path / "cible"
        with pytest.raises(backup.BackupError, match="lien"):
            backup.restore(forged, victim)
        assert not victim.exists() and not any(outside.iterdir())



def test_the_files_she_sent_are_archived_and_restored_private(tmp_path, monkeypatch):
    """ADR 0062 : les octets des fichiers qu'elle a envoyés ne sont pas au journal — ``partages/`` part avec la
    sauvegarde et revient à la restauration, à elle seule (0700, 0600), lisible par le même port."""
    import stat

    from mika.adapters.shares import DiskShares

    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest, restored = tmp_path / "data", tmp_path / "archives", tmp_path / "restauree"
    live(data, talk=False)
    file = "c0ffee" + "0" * 26
    asyncio.run(DiskShares(data / "partages").put(file, b"- pain\n- lait\n", subjects=("user_2",)))
    made = backup.backup(data, dest)
    with tarfile.open(made.archive) as tar:
        names = tar.getnames()
    assert f"data/partages/{file}.bin" in names and f"data/partages/{file}.json" in names
    backup.restore(made.archive, restored)
    assert stat.S_IMODE((restored / "partages").stat().st_mode) == 0o700
    assert stat.S_IMODE((restored / "partages" / f"{file}.bin").stat().st_mode) == 0o600
    again = DiskShares(restored / "partages")
    assert asyncio.run(again.read(file)) == b"- pain\n- lait\n"
    assert asyncio.run(again.forget("user_2")) == 1  # ses sujets reviennent avec lui


def test_the_map_counters_are_archived_and_never_put_back_over_newer_ones(tmp_path, monkeypatch):
    """R3-08 : les compteurs du mois de Google (``cartes/quotas.db``, ce qui empêche la facture) ne sont que dans le
    dossier de données, et ``cartes/`` ne se sauvegarde pas (la carte et l'index se refont) — restauré sur une machine
    neuve, le mois repartait de zéro quand Google, lui, avait compté. Les compteurs partent avec l'archive (le reste de
    ``cartes/``, non) ; restaurés là où il n'y en a pas, ils reviennent ; sur place, ceux du dossier, plus récents,
    restent."""
    monkeypatch.delenv("MIKA_SECRET_KEY", raising=False)
    data, dest = tmp_path / "data", tmp_path / "archives"
    live(data, talk=False)
    QuotaStore(data / QUOTAS_FILE).add_month("google-fiches", "2026-11", 640)
    (data / "cartes" / "lieux.db").write_bytes(b"un index qui se refait")
    made = backup.backup(data, dest)
    with tarfile.open(made.archive) as tar:
        names = tar.getnames()
    assert f"data/{QUOTAS_FILE}" in names and not any(n.endswith("cartes/lieux.db") for n in names)
    fresh = tmp_path / "neuve"
    backup.restore(made.archive, fresh)
    assert QuotaStore(fresh / QUOTAS_FILE).month_used("google-fiches", "2026-11") == 640
    assert not (fresh / "cartes" / "lieux.db").exists()
    QuotaStore(data / QUOTAS_FILE).add_month("google-fiches", "2026-11", 60)  # le serveur a compté depuis
    backup.restore(made.archive, data, force=True)
    assert QuotaStore(data / QUOTAS_FILE).month_used("google-fiches", "2026-11") == 700
    assert (data / "cartes" / "lieux.db").read_bytes() == b"un index qui se refait"
