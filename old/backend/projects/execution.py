"""Exécution isolée d'un atelier Linux via bubblewrap.

L'atelier seul est inscriptible ; les exécutables système sont en lecture.
Aucun repli aux droits du serveur si l'isolation est indisponible.
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

from old.backend.configs.runtime import cfg_bool, cfg_int, cfg_list

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
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"


def _chemin_de_recherche(racine: Path) -> str:
    return f"{racine}/.venv/bin:{racine}/node_modules/.bin:{SYSTEM_PATH}"


def _executable_visible(programme: str, racine: Path) -> str | None:
    """Résoudre dans le PATH du bac, sans importer les dépendances du serveur."""
    if "/" in programme:
        candidat = Path(programme)
        candidat = candidat if candidat.is_absolute() else racine / candidat
        chemin = str(candidat)
    else:
        chemin = shutil.which(programme, path=_chemin_de_recherche(racine))
    if not chemin:
        return None
    cible = Path(chemin).resolve()
    visibles = [racine, *(Path(p).resolve() for p in ("/usr", "/bin", "/sbin", "/lib", "/lib64"))]
    if not any(cible.is_relative_to(p) for p in visibles):
        return None
    return chemin if cible.is_file() and os.access(cible, os.X_OK) else None


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


def _commande_isolee(racine: Path, commande: list[str], *, reseau: bool) -> list[str]:
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise OSError("bubblewrap (bwrap) requis : exécution isolée indisponible")
    args = [bwrap, "--die-with-parent", "--new-session", "--unshare-all",
            "--cap-drop", "ALL"]
    if reseau:
        args += ["--share-net"]
    for dossier in ("/usr", "/bin", "/sbin", "/lib", "/lib64"):
        chemin = Path(dossier)
        if chemin.is_symlink():
            args += ["--symlink", os.readlink(chemin), dossier]
        elif chemin.is_dir():
            args += ["--ro-bind", dossier, dossier]
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    # Fichiers de résolution système, jamais /etc entier (qui contient les
    # secrets de services). Certains exécutables consultent uid/gid et ld.so.
    for fichier in ("/etc/passwd", "/etc/group", "/etc/nsswitch.conf", "/etc/ld.so.cache"):
        if Path(fichier).is_file():
            args += ["--ro-bind", fichier, fichier]
    if reseau:
        for fichier in ("/etc/resolv.conf", "/etc/ssl/certs"):
            if Path(fichier).exists():
                args += ["--ro-bind", fichier, fichier]
    args += ["--bind", str(racine), str(racine), "--chdir", str(racine)]
    return [*args, "--", *commande]


def _environnement(racine: Path) -> dict[str, str]:
    """Un environnement construit, pas hérité. Voir l'en-tête du module."""
    maison = racine / HOME_DIRNAME
    try:
        maison.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Ateliers : %s incréable (%s)", maison, exc)
        maison = racine
    return {
        "PATH": _chemin_de_recherche(racine),
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

    racine = racine.resolve()
    chemin = _executable_visible(argv[0], racine)
    if not chemin:
        return ExecResult(
            argv=argv, returncode=None,
            refused=(f"'{argv[0]}' est absent de l'environnement isolé. "
                     "Installe-le dans l'atelier (.venv/bin ou node_modules/.bin), "
                     "ou utilise un exécutable système. Le venv et ~/.local du serveur ne sont pas montés."),
        )

    notes: list[str] = []
    try:
        reel = _commande_isolee(
            racine, [chemin, *argv[1:]],
            reseau=not cfg_bool("projects.exec.block_network", EXEC_BLOCK_NETWORK),
        )
    except OSError as exc:
        return ExecResult(argv=argv, returncode=None, refused=str(exc))

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

    async def lire_borne(flux):
        # Continuer à drainer, sans accumuler toute la sortie en mémoire.
        contenu = bytearray()
        coupe = False
        while morceau := await flux.read(8192):
            reste = max(0, maxi * 4 - len(contenu))
            contenu.extend(morceau[:reste])
            coupe |= len(morceau) > reste
        return bytes(contenu), coupe

    async def recolter():
        sortie, erreur = await asyncio.gather(lire_borne(proc.stdout), lire_borne(proc.stderr))
        await proc.wait()
        return sortie, erreur

    collecte = asyncio.create_task(recolter())
    expire = False
    try:
        (sortie, coupe_flux_a), (erreur, coupe_flux_b) = await asyncio.wait_for(
            asyncio.shield(collecte), timeout=delai,
        )
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            (sortie, coupe_flux_a), (erreur, coupe_flux_b) = await asyncio.wait_for(collecte, 5)
        except asyncio.TimeoutError:
            sortie, erreur, coupe_flux_a, coupe_flux_b = b"", b"", True, True
        if isinstance(exc, asyncio.CancelledError):
            raise
        expire = True

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
        truncated=coupe_a or coupe_b or coupe_flux_a or coupe_flux_b,
        notes=notes,
    )
