"""L'atelier d'un projet : un dossier réel, et le seul contrôle qui le garde.

Un projet est un dossier avec des outils pour le manipuler, séparé du moteur.
C'est la symétrie exacte de la Forge, dont il est l'opposé assumé : la Forge
est **confinée parce qu'elle est couplée** (elle s'exécute dans le processus
de Mika pour l'étendre, donc tout lui est interdit) ; un atelier est
**capable parce qu'il est séparé** (il ne touche rien du moteur, donc il peut
écrire de vrais fichiers et lancer de vrais programmes).

Le confinement des chemins est **un seul contrôle appliqué partout** :
résoudre puis vérifier l'appartenance. C'est ce qui attrape à la fois
``../../etc/passwd`` et le lien symbolique qui pointe hors du dossier — une
comparaison de chaînes laisse passer le second, et c'est l'erreur classique.

Portée du contrôle, dite franchement : il borne **la trousse**, pas un
programme une fois lancé. ``project_write_file`` ne peut pas écrire dehors ;
un script que ``project_run`` démarre le peut, puisque la frontière retenue
est « mêmes droits ». Voir l'en-tête de :mod:`projects.execution`.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings

from old.backend.configs.runtime import cfg_int, cfg_str
from old.backend.projects.execution import HOME_DIRNAME, run_bounded

logger = logging.getLogger(__name__)

# Repli des clés ``projects.workspace.*``. La racine est déclarée RELATIVE :
# le réglage du tableau de bord et le repli du code doivent être la même
# valeur écrite deux fois (un test parcourt l'AST pour l'exiger), et un chemin
# absolu dépend de l'installation. Un chemin relatif se résout depuis la
# racine du dépôt ; un chemin absolu saisi dans le tableau de bord est pris
# tel quel, ce qui permet de sortir les ateliers du dépôt si on le souhaite.
WORKSPACE_ROOT = "data/projects"
MAX_FILE_BYTES = 400_000
MAX_TREE_ENTRIES = 400

# Jamais écrits par la trousse, quel que soit le chemin demandé : ce sont les
# organes de l'atelier, pas son contenu.
INTERDITS_EN_ECRITURE = (".git", HOME_DIRNAME)


class HorsAtelier(ValueError):
    """Le chemin demandé sort de la racine du projet."""


@dataclass(frozen=True)
class Atelier:
    """Un dossier de projet, et ce qu'on a le droit d'y faire."""

    project_id: int
    racine: Path

    # ── Confinement ───────────────────────────────────────────────

    def chemin(self, relatif: str, *, pour_ecriture: bool = False) -> Path:
        """Résout ``relatif`` dans l'atelier, ou lève ``HorsAtelier``.

        Résout d'abord, vérifie ensuite : comparer les chaînes laisserait
        passer ``..`` aussi bien que le lien symbolique sortant.
        """
        brut = str(relatif or "").strip()
        if not brut or brut in (".", "./"):
            cible = self.racine
        else:
            if Path(brut).is_absolute():
                raise HorsAtelier(
                    f"chemin absolu refusé : {brut} — écris un chemin "
                    "relatif à la racine de l'atelier"
                )
            cible = self.racine / brut

        base = self.racine.resolve()
        try:
            resolu = cible.resolve()
        except OSError as exc:
            raise HorsAtelier(f"chemin illisible : {brut} ({exc})") from exc
        if resolu != base and not resolu.is_relative_to(base):
            raise HorsAtelier(f"hors de l'atelier : {brut}")

        if pour_ecriture:
            parts = resolu.relative_to(base).parts if resolu != base else ()
            if parts and parts[0] in INTERDITS_EN_ECRITURE:
                raise HorsAtelier(
                    f"'{parts[0]}/' appartient à l'atelier lui-même et ne "
                    "s'écrit pas depuis la trousse"
                )
        return resolu

    def relatif(self, chemin: Path) -> str:
        try:
            return str(chemin.resolve().relative_to(self.racine.resolve()))
        except (ValueError, OSError):
            return str(chemin)

    # ── Lecture ───────────────────────────────────────────────────

    def arborescence(self, sous_dossier: str = ".") -> list[str]:
        """Les fichiers sous ``sous_dossier``, triés, plafonnés.

        ``.git`` et le HOME de l'atelier sont masqués : ce sont des organes,
        les lister remplirait la réponse de bruit que le modèle n'a aucune
        raison de lire.
        """
        depart = self.chemin(sous_dossier)
        if not depart.exists():
            return []
        if depart.is_file():
            return [self.relatif(depart)]

        maxi = cfg_int("projects.workspace.max_tree_entries", MAX_TREE_ENTRIES, mini=1)
        lignes: list[str] = []
        for p in sorted(depart.rglob("*")):
            rel = self.relatif(p)
            if any(part in INTERDITS_EN_ECRITURE for part in Path(rel).parts):
                continue
            if p.is_dir():
                continue
            try:
                taille = p.stat().st_size
            except OSError:
                taille = 0
            lignes.append(f"{rel} ({taille} o)")
            if len(lignes) >= maxi:
                lignes.append(f"[… liste coupée à {maxi} entrées …]")
                break
        return lignes

    def lire(self, relatif: str) -> str:
        cible = self.chemin(relatif)
        if not cible.is_file():
            raise FileNotFoundError(f"{relatif} n'existe pas dans l'atelier")
        maxi = cfg_int("projects.workspace.max_file_bytes", MAX_FILE_BYTES, mini=1)
        brut = cible.read_bytes()[: maxi + 1]
        coupe = len(brut) > maxi
        brut = brut[:maxi]
        try:
            texte = brut.decode("utf-8")
        except UnicodeDecodeError:
            texte = brut.decode("latin-1", errors="replace")
        return texte + ("\n\n[… fichier tronqué …]" if coupe else "")

    # ── Écriture ──────────────────────────────────────────────────

    def ecrire(self, relatif: str, contenu: str) -> str:
        cible = self.chemin(relatif, pour_ecriture=True)
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(str(contenu), encoding="utf-8")
        return self.relatif(cible)

    def remplacer(self, relatif: str, ancien: str, nouveau: str) -> str:
        """Remplacement exact et unique.

        Échoue si le fragment est absent ou ambigu, jamais de correspondance
        approximative : une édition « à peu près » sur du code produit un
        fichier plausible et faux, ce qui coûte plus cher que l'échec.
        """
        cible = self.chemin(relatif, pour_ecriture=True)
        if not cible.is_file():
            raise FileNotFoundError(f"{relatif} n'existe pas dans l'atelier")
        texte = cible.read_text(encoding="utf-8", errors="replace")
        occurrences = texte.count(ancien)
        if occurrences == 0:
            raise ValueError(
                f"fragment introuvable dans {relatif} — relis le fichier "
                "avant de l'éditer"
            )
        if occurrences > 1:
            raise ValueError(
                f"fragment présent {occurrences} fois dans {relatif} — "
                "donne un extrait plus large pour lever l'ambiguïté"
            )
        cible.write_text(texte.replace(ancien, nouveau, 1), encoding="utf-8")
        return self.relatif(cible)

    def supprimer(self, relatif: str) -> str:
        cible = self.chemin(relatif, pour_ecriture=True)
        if not cible.exists():
            raise FileNotFoundError(f"{relatif} n'existe pas dans l'atelier")
        if cible.is_dir():
            raise IsADirectoryError(
                f"{relatif} est un dossier — la trousse ne supprime que des fichiers"
            )
        cible.unlink()
        return self.relatif(cible)

    # ── Git ───────────────────────────────────────────────────────

    async def git(self, *args: str, timeout_s: int = 30):
        """Un git de l'atelier. Passe par la même borne que tout le reste."""
        return await run_bounded(
            racine=self.racine, argv=["git", *args], timeout_s=timeout_s,
            # Git est l'outil de l'atelier lui-même : il n'a pas à figurer
            # dans la liste blanche destinée aux commandes du modèle, et le
            # retirer de cette liste ne doit pas casser l'historique.
            verifier_allowlist=False,
        )

    async def git_initialiser(self) -> bool:
        if (self.racine / ".git").exists():
            return True
        r = await self.git("init", "-q")
        if not r.ok:
            logger.info("Atelier %s : git init a échoué (%s)", self.project_id, r.stderr[:200])
            return False
        (self.racine / ".gitignore").write_text(
            f"{HOME_DIRNAME}/\n__pycache__/\n*.pyc\n.venv/\nnode_modules/\n",
            encoding="utf-8",
        )
        await self.git("config", "user.email", "mika@local")
        await self.git("config", "user.name", "Mika")
        # L'initialisation scelle son propre état. Sans ce commit d'amorce, le
        # `.gitignore` reste non suivi, `git status` n'est pas vide, et le
        # PREMIER tick est enregistré comme du travail sous le résumé de ce
        # tour — un tick qui n'a rien fait signerait la mise en place.
        await self.git("add", "-A")
        await self.git("commit", "-q", "-m", "atelier initialisé")
        return True

    async def git_commit(self, message: str) -> str:
        """Enregistre l'état s'il a changé. Rend le sha court, ou "".

        Un tick qui n'a rien modifié ne produit pas de commit vide : un
        historique où chaque tick laisse une trace ne se relit plus.
        """
        if not (self.racine / ".git").exists() and not await self.git_initialiser():
            return ""
        etat = await self.git("status", "--porcelain")
        if not etat.ok or not etat.stdout.strip():
            return ""
        await self.git("add", "-A")
        titre = (message or "travail").strip().splitlines()[0][:72] or "travail"
        fait = await self.git("commit", "-q", "-m", titre)
        if not fait.ok:
            logger.info(
                "Atelier %s : commit refusé (%s)",
                self.project_id, (fait.stderr or fait.stdout)[:200],
            )
            return ""
        sha = await self.git("rev-parse", "--short", "HEAD")
        return sha.stdout.strip() if sha.ok else ""

    async def git_diff(self, *, depuis_dernier_commit: bool = True) -> str:
        if not (self.racine / ".git").exists():
            return ""
        args = ["diff", "--stat", "-p"] if depuis_dernier_commit else ["show", "--stat"]
        r = await self.git(*args)
        return r.stdout if r.ok else ""

    async def git_journal(self, n: int = 10) -> str:
        if not (self.racine / ".git").exists():
            return ""
        r = await self.git("log", f"-{max(1, n)}", "--format=%h %ad %s", "--date=short")
        return r.stdout if r.ok else ""


# ── Résolution ────────────────────────────────────────────────────


def _fragment(titre: str) -> str:
    nettoye = re.sub(r"[^a-z0-9]+", "-", (titre or "").lower()).strip("-")
    return (nettoye or "projet")[:40]


def racine_des_ateliers() -> Path:
    declare = str(cfg_str("projects.workspace.root", WORKSPACE_ROOT) or "").strip()
    chemin = Path(declare or WORKSPACE_ROOT).expanduser()
    if chemin.is_absolute():
        return chemin
    return Path(settings.PROJECT_ROOT) / chemin


def _nom_du_dossier(project_id: int, titre: str) -> str:
    return f"{project_id}-{_fragment(titre)}"


def _derniere_activite(dossier: Path) -> float:
    """Le moment le plus récent où l'atelier a bougé, pour départager.

    Le mtime du dossier ne bouge qu'à l'ajout d'une entrée directe ; l'index
    git, lui, est réécrit à chaque ``git add`` du lanceur.
    """
    instants = [dossier.stat().st_mtime]
    for organe in (dossier / ".git" / "index", dossier / ".git" / "HEAD"):
        try:
            instants.append(organe.stat().st_mtime)
        except OSError:
            pass
    return max(instants)


def _dossier_de(project_id: int, titre: str) -> Path:
    """Le dossier d'un projet : celui qui existe déjà sous son identifiant,
    sinon ``<id>-<slug du titre>``.

    Le nom portait le titre, et le titre se modifie. Renommer un projet
    détachait donc son travail : le lanceur ouvrait un dossier neuf et vide,
    l'ancien restait orphelin, et la suppression ne mettait en corbeille que
    le neuf. L'identifiant est la seule partie stable du nom ; le slug n'est
    qu'un confort de lecture, figé à la création. Résoudre par préfixe évite
    une migration — rien à recopier sur une installation existante.
    """
    racine = racine_des_ateliers()
    existants = (
        [p for p in racine.glob(f"{project_id}-*") if p.is_dir()]
        if racine.is_dir() else []
    )
    if not existants:
        return racine / _nom_du_dossier(project_id, titre)
    if len(existants) > 1:
        # Installation d'avant ce correctif, renommée entre deux ticks : deux
        # dossiers, deux fragments de travail. On reprend là où le lanceur a
        # travaillé en dernier, et on nomme les autres pour qu'on les fusionne.
        existants.sort(key=_derniere_activite, reverse=True)
        logger.warning(
            "Projet %s : plusieurs ateliers sous %s (%s) — reprise dans %s",
            project_id, racine, ", ".join(p.name for p in existants),
            existants[0].name,
        )
    return existants[0]


def atelier_de(project_id: int, titre: str) -> Atelier:
    """L'atelier d'un projet, créé à la volée.

    Création paresseuse : un projet qui n'écrit jamais rien n'a jamais de
    dossier, et rien n'est à migrer sur une installation existante.

    Prend l'identifiant et le titre plutôt qu'un objet du modèle : le lanceur
    travaille sur un contexte figé, pas sur une ligne de base, et lui faire
    recharger le projet pour obtenir son dossier serait une requête de plus
    par tick pour deux champs qu'il a déjà.
    """
    racine = _dossier_de(project_id, titre)
    racine.mkdir(parents=True, exist_ok=True)
    return Atelier(project_id=project_id, racine=racine)


def atelier_existant(project_id: int, titre: str) -> Atelier | None:
    """L'atelier s'il existe déjà, sans le créer (lecture d'écran)."""
    racine = _dossier_de(project_id, titre)
    return Atelier(project_id=project_id, racine=racine) if racine.is_dir() else None


def mettre_en_corbeille(project_id: int, titre: str) -> str:
    """Déplace l'atelier plutôt que de l'effacer — comme le fait la Forge.

    Supprimer un projet supprimait jusqu'ici des lignes en base. Il supprime
    désormais du travail, et le travail ne se jette pas sur un clic.
    """
    atelier = atelier_existant(project_id, titre)
    if atelier is None:
        return ""
    corbeille = racine_des_ateliers() / "_corbeille"
    corbeille.mkdir(parents=True, exist_ok=True)
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = corbeille / f"{atelier.racine.name}-{horodatage}"
    shutil.move(str(atelier.racine), str(destination))
    return str(destination)
