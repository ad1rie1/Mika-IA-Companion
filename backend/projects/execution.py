"""Le point de passage unique de toute exécution dans un atelier.

**Une seule fonction lance des processus dans ce dépôt.** C'est délibéré et
c'est le cœur du dispositif : la frontière retenue est « sous-processus borné,
mêmes droits », qui protège de l'accident et de la maladresse, pas d'un
adversaire. Elle laisse donc des résidus assumés — un script écrit par le
modèle tourne avec les droits du serveur, peut lire ``$HOME`` et, sans espace
de noms, atteindre le réseau. La seule barrière réelle serait un namespace
(``bubblewrap``, ``systemd-run``). En faisant passer *toute* exécution par
``run_bounded``, cette barrière reste ajoutable à un seul endroit.

Les bornes, et pourquoi chacune :

``exec`` et jamais ``shell``
    La commande vient du modèle. Une chaîne passée à un shell offrirait
    l'injection gratuitement (``pytest; curl … | sh``). Une liste d'arguments
    n'a pas de métacaractères.

Exécutables déclarés
    L'argument zéro est le seul endroit où poser une porte qu'un humain peut
    relire. ``projects.exec.allowed_commands``.

Répertoire verrouillé
    ``cwd`` = racine de l'atelier, pour que les chemins relatifs que le modèle
    écrit restent dans son bac.

Environnement reconstruit, jamais hérité
    Le processus du serveur porte ``CONFIG_ENCRYPTION_KEY`` et
    ``DJANGO_SECRET_KEY`` dans son ``os.environ``. Le comportement par défaut
    de ``create_subprocess_exec`` est d'hériter : ce serait remettre les
    secrets de l'installation à un script écrit par un modèle. ``HOME`` pointe
    dans l'atelier, si bien qu'un outil qui écrit un cache l'écrit là.

Entrée fermée
    Sans ``stdin=DEVNULL``, un ``input()`` oublié bloque jusqu'au délai entier.

Délai dur sur le *groupe*
    ``start_new_session=True`` puis ``killpg`` : tuer le seul enfant laisse
    ses petits-enfants tourner, et c'est ainsi qu'un worker survit à son test.

Sortie plafonnée
    Une boucle bavarde ne doit remplir ni la base ni l'invite du tour suivant.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path

from configs.runtime import cfg_bool, cfg_int, cfg_list

logger = logging.getLogger(__name__)

# Les constantes qui suivent restent le REPLI des clés ``projects.exec.*``.
ALLOWED_COMMANDS = [
    "python", "python3", "pytest", "node", "npm", "npx", "git",
    "ls", "cat", "head", "tail", "wc", "grep", "find", "mkdir", "cp", "mv",
]
EXEC_TIMEOUT_SECONDS = 120
EXEC_MAX_OUTPUT_CHARS = 20_000
EXEC_BLOCK_NETWORK = True

# Sous-dossier servant de ``HOME`` aux processus de l'atelier.
HOME_DIRNAME = ".atelier-home"


@dataclass
class ExecResult:
    """Ce qu'une commande a produit, sous une forme racontable au modèle."""

    argv: list[str]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    truncated: bool = False
    refused: str = ""  # non vide = la commande n'a jamais été lancée
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refused and not self.timed_out and self.returncode == 0

    def resume(self) -> str:
        """Une ligne, pour le journal du projet."""
        if self.refused:
            return f"refusé : {self.refused}"
        if self.timed_out:
            return f"{' '.join(self.argv)} — délai dépassé ({self.duration_ms} ms)"
        return (
            f"{' '.join(self.argv)} — code {self.returncode} "
            f"({self.duration_ms} ms)"
        )


def _commandes_autorisees() -> tuple[str, ...]:
    valeurs = cfg_list("projects.exec.allowed_commands", ALLOWED_COMMANDS)
    return tuple(str(v).strip() for v in valeurs if str(v or "").strip())


_prefixe_reseau: list[str] | None = None


def _prefixe_sans_reseau() -> list[str]:
    """``unshare -rn`` quand la machine le permet, sinon rien.

    Opportuniste et **annoncé comme tel** : sur un noyau sans espaces de noms
    utilisateur non privilégiés, la coupure réseau n'a pas lieu. Prétendre le
    contraire serait pire que de ne rien faire — la note remonte donc dans
    ``ExecResult.notes`` et de là au modèle et au journal.
    """
    global _prefixe_reseau
    if _prefixe_reseau is not None:
        return _prefixe_reseau

    chemin = shutil.which("unshare")
    if not chemin:
        _prefixe_reseau = []
        return _prefixe_reseau
    try:
        import subprocess  # noqa: PLC0415 — sonde unique, au premier appel

        sonde = subprocess.run(  # noqa: S603 — argv figé, aucun shell
            [chemin, "-r", "-n", "--", "true"],
            capture_output=True, timeout=5,
        )
        _prefixe_reseau = [chemin, "-r", "-n", "--"] if sonde.returncode == 0 else []
    except Exception as exc:  # noqa: BLE001 — une sonde qui échoue = pas de coupure
        logger.info("Ateliers : unshare indisponible (%s)", exc)
        _prefixe_reseau = []
    return _prefixe_reseau


def _environnement(racine: Path) -> dict[str, str]:
    """Un environnement construit, pas hérité. Voir l'en-tête du module."""
    maison = racine / HOME_DIRNAME
    try:
        maison.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Ateliers : %s incréable (%s)", maison, exc)
        maison = racine
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(maison),
        "TMPDIR": str(maison),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        # Un test qui lit cette variable sait qu'il n'est pas sur une vraie
        # machine de développement.
        "MIKA_ATELIER": "1",
    }


def _tronquer(flux: bytes, maxi: int) -> tuple[str, bool]:
    texte = flux.decode("utf-8", errors="replace")
    if len(texte) <= maxi:
        return texte, False
    garde = maxi // 2
    return (
        texte[:garde] + f"\n\n[… {len(texte) - maxi} caractères coupés …]\n\n"
        + texte[-garde:],
        True,
    )


async def run_bounded(
    *,
    racine: Path,
    argv: list[str],
    timeout_s: int | None = None,
    verifier_allowlist: bool = True,
) -> ExecResult:
    """Lance ``argv`` dans ``racine``. Ne lève jamais : tout est dans le résultat.

    Ne pas lever est un choix : l'appelant est un handler d'outil, et une
    commande qui échoue est une information à rendre au modèle — pas une
    panne du tour. Un refus (``refused``) et un échec (``returncode``) se
    lisent différemment et disent des choses différentes.
    """
    if not argv:
        return ExecResult(argv=[], returncode=None, refused="commande vide")

    argv = [str(a) for a in argv]
    programme = Path(argv[0]).name
    if verifier_allowlist and programme not in _commandes_autorisees():
        autorisees = ", ".join(_commandes_autorisees())
        return ExecResult(
            argv=argv, returncode=None,
            refused=(
                f"'{programme}' n'est pas dans les exécutables autorisés. "
                f"Autorisés : {autorisees}. La liste se règle dans "
                f"Configuration > Projets."
            ),
        )

    chemin = shutil.which(argv[0])
    if not chemin:
        return ExecResult(
            argv=argv, returncode=None,
            refused=f"'{argv[0]}' est introuvable sur cette machine",
        )

    notes: list[str] = []
    reel = [chemin, *argv[1:]]
    if cfg_bool("projects.exec.block_network", EXEC_BLOCK_NETWORK):
        prefixe = _prefixe_sans_reseau()
        if prefixe:
            reel = [*prefixe, *reel]
        else:
            notes.append(
                "réseau NON coupé : unshare indisponible sur cette machine"
            )

    delai = timeout_s or cfg_int(
        "projects.exec.timeout_seconds", EXEC_TIMEOUT_SECONDS, mini=1,
    )
    maxi = cfg_int(
        "projects.exec.max_output_chars", EXEC_MAX_OUTPUT_CHARS, mini=200,
    )

    debut = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            *reel,
            cwd=str(racine),
            env=_environnement(racine),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Le processus devient chef de son groupe : le délai peut alors
            # tuer TOUTE sa descendance, pas seulement lui.
            start_new_session=True,
        )
    except OSError as exc:
        return ExecResult(
            argv=argv, returncode=None, refused=f"lancement impossible : {exc}",
            notes=notes,
        )

    expire = False
    try:
        sortie, erreur = await asyncio.wait_for(proc.communicate(), timeout=delai)
    except asyncio.TimeoutError:
        expire = True
        sortie, erreur = b"", b""
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError) as exc:
            logger.warning("Ateliers : groupe %s non tuable (%s)", proc.pid, exc)
            proc.kill()
        try:
            sortie, erreur = await asyncio.wait_for(proc.communicate(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            pass

    duree = int((time.perf_counter() - debut) * 1000)
    texte_sortie, coupe_a = _tronquer(sortie or b"", maxi)
    texte_erreur, coupe_b = _tronquer(erreur or b"", maxi)
    return ExecResult(
        argv=argv,
        returncode=proc.returncode,
        stdout=texte_sortie,
        stderr=texte_erreur,
        duration_ms=duree,
        timed_out=expire,
        truncated=coupe_a or coupe_b,
        notes=notes,
    )
