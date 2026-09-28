"""La trousse d'un atelier : ce que Mika tient dans les mains sur un projet.

Ce sont des ``ModuleTool`` ordinaires — la même dataclass que tout le reste du
moteur. Conséquence voulue : la boucle d'outils, le sémaphore par provider et
la trace succès/échec valent ici sans une ligne de machinerie nouvelle, et un
outil qui échoue est **compté** au lieu de ressembler à un outil qui a marché.

Trois règles tiennent tout le fichier :

1. **Un handler ne lève pas.** Il rend au modèle ce qui s'est passé, y compris
   l'échec. Une exception qui remonte tuerait le tour ; une phrase qui dit
   « fragment introuvable, relis le fichier » le fait avancer.
2. **Tout chemin passe par ``Atelier.chemin``**, jamais par une concaténation
   locale : le confinement est un contrôle unique, appliqué partout.
3. **Toute exécution passe par ``run_bounded``**, pour que la frontière reste
   déplaçable à un seul endroit.
"""

from __future__ import annotations

import logging

from asgiref.sync import sync_to_async

from modules.types import ModuleTool, ToolParameter, ToolParameterType
from projects.execution import run_bounded
from projects.workspace import Atelier, HorsAtelier

logger = logging.getLogger(__name__)


from utils.tool_results import texte as _texte


def _echec(quoi: str, exc: Exception) -> dict:
    """Un échec est une information rendue au modèle, pas une panne du tour."""
    return _texte(f"{quoi} : {exc}", erreur=True)


def construire_trousse(atelier: Atelier, *, commande_de_test: str = "") -> list[ModuleTool]:
    """Les outils de CET atelier — les handlers ferment sur sa racine.

    Aucun identifiant de projet ne circule dans les arguments : le modèle ne
    peut donc pas désigner l'atelier d'un autre projet, même par erreur. La
    portée est portée par la fermeture, pas par un paramètre à valider.
    """

    async def lister(args: dict) -> dict:
        try:
            lignes = await sync_to_async(atelier.arborescence)(
                str(args.get("sous_dossier") or "."),
            )
        except HorsAtelier as exc:
            return _echec("chemin refusé", exc)
        except OSError as exc:
            return _echec("lecture impossible", exc)
        if not lignes:
            return _texte("L'atelier est vide.")
        return _texte("\n".join(lignes))

    async def lire(args: dict) -> dict:
        chemin = str(args.get("chemin") or "").strip()
        try:
            return _texte(await sync_to_async(atelier.lire)(chemin))
        except (HorsAtelier, FileNotFoundError, OSError) as exc:
            return _echec("lecture impossible", exc)

    async def ecrire(args: dict) -> dict:
        chemin = str(args.get("chemin") or "").strip()
        contenu = args.get("contenu")
        if contenu is None:
            return _texte("Il manque le contenu à écrire.", erreur=True)
        try:
            ecrit = await sync_to_async(atelier.ecrire)(chemin, str(contenu))
        except (HorsAtelier, OSError) as exc:
            return _echec("écriture impossible", exc)
        return _texte(f"Écrit : {ecrit} ({len(str(contenu))} caractères).")

    async def editer(args: dict) -> dict:
        chemin = str(args.get("chemin") or "").strip()
        ancien = args.get("ancien")
        nouveau = args.get("nouveau")
        if ancien is None or nouveau is None:
            return _texte("Il faut 'ancien' et 'nouveau'.", erreur=True)
        try:
            ecrit = await sync_to_async(atelier.remplacer)(
                chemin, str(ancien), str(nouveau),
            )
        except (HorsAtelier, FileNotFoundError, ValueError, OSError) as exc:
            return _echec("édition impossible", exc)
        return _texte(f"Modifié : {ecrit}.")

    async def supprimer(args: dict) -> dict:
        chemin = str(args.get("chemin") or "").strip()
        try:
            enleve = await sync_to_async(atelier.supprimer)(chemin)
        except (HorsAtelier, FileNotFoundError, IsADirectoryError, OSError) as exc:
            return _echec("suppression impossible", exc)
        return _texte(f"Supprimé : {enleve}.")

    def _rendre(resultat) -> dict:
        morceaux = [resultat.resume()]
        if resultat.notes:
            morceaux.append("(" + " ; ".join(resultat.notes) + ")")
        if resultat.stdout.strip():
            morceaux.append("--- sortie ---\n" + resultat.stdout.rstrip())
        if resultat.stderr.strip():
            morceaux.append("--- erreurs ---\n" + resultat.stderr.rstrip())
        if resultat.ok and not resultat.stdout.strip() and not resultat.stderr.strip():
            morceaux.append("(aucune sortie)")
        return _texte("\n".join(morceaux), erreur=not resultat.ok)

    async def executer(args: dict) -> dict:
        brut = args.get("commande")
        if isinstance(brut, str):
            argv = brut.split()
        else:
            argv = [str(a) for a in (brut or [])]
        if not argv:
            return _texte("Il manque la commande.", erreur=True)
        return _rendre(await run_bounded(racine=atelier.racine, argv=argv))

    async def tester(args: dict) -> dict:
        brut = str(args.get("commande") or commande_de_test or "").strip()
        if not brut:
            return _texte(
                "Aucune commande de test n'est déclarée pour ce projet. "
                "Passe-la en argument, ou renseigne-la dans la fiche du projet.", erreur=True
            )
        return _rendre(await run_bounded(racine=atelier.racine, argv=brut.split()))

    async def differences(args: dict) -> dict:
        texte = await atelier.git_diff()
        if not texte.strip():
            return _texte("Rien n'a changé depuis le dernier enregistrement.")
        return _texte(texte)

    async def historique(args: dict) -> dict:
        try:
            n = int(args.get("nombre") or 10)
        except (TypeError, ValueError):
            n = 10
        texte = await atelier.git_journal(n)
        return _texte(texte.strip() or "L'atelier n'a pas encore d'historique.")

    P = ToolParameter
    T = ToolParameterType
    return [
        ModuleTool(
            name="project_list_files",
            description=(
                "Liste les fichiers de l'atelier du projet. Commence toujours "
                "par là avant d'écrire quoi que ce soit."
            ),
            parameters=[
                P(name="sous_dossier", type=T.STRING, required=False, default=".",
                  description="Sous-dossier à explorer, relatif à la racine."),
            ],
            handler=lister,
        ),
        ModuleTool(
            name="project_read_file",
            description="Lit un fichier de l'atelier.",
            parameters=[
                P(name="chemin", type=T.STRING,
                  description="Chemin relatif à la racine de l'atelier."),
            ],
            handler=lire,
        ),
        ModuleTool(
            name="project_write_file",
            description=(
                "Crée ou remplace entièrement un fichier de l'atelier. "
                "Pour une retouche ciblée, project_edit_file coûte moins cher."
            ),
            parameters=[
                P(name="chemin", type=T.STRING,
                  description="Chemin relatif ; les dossiers manquants sont créés."),
                P(name="contenu", type=T.STRING, description="Contenu complet du fichier."),
            ],
            handler=ecrire,
        ),
        ModuleTool(
            name="project_edit_file",
            description=(
                "Remplace un fragment exact dans un fichier. Échoue si le "
                "fragment est absent ou présent plusieurs fois — donne alors "
                "un extrait plus large."
            ),
            parameters=[
                P(name="chemin", type=T.STRING, description="Chemin relatif."),
                P(name="ancien", type=T.STRING, description="Fragment exact à remplacer."),
                P(name="nouveau", type=T.STRING, description="Ce qui le remplace."),
            ],
            handler=editer,
        ),
        ModuleTool(
            name="project_delete_file",
            description="Supprime un fichier de l'atelier.",
            parameters=[
                P(name="chemin", type=T.STRING, description="Chemin relatif."),
            ],
            handler=supprimer,
        ),
        ModuleTool(
            name="project_run",
            description=(
                "Lance une commande dans l'atelier et rend sa sortie. Seuls "
                "certains exécutables sont autorisés ; le refus dit lesquels."
            ),
            parameters=[
                P(name="commande", type=T.STRING,
                  description="La commande, par exemple 'python csv2json.py entree.csv sortie.json'."),
            ],
            handler=executer,
        ),
        ModuleTool(
            name="project_test",
            description=(
                "Lance la suite de tests du projet. Sans argument, utilise la "
                "commande de test déclarée sur la fiche."
            ),
            parameters=[
                P(name="commande", type=T.STRING, required=False,
                  description="Commande de test à lancer, si elle diffère de celle déclarée."),
            ],
            handler=tester,
        ),
        ModuleTool(
            name="project_diff",
            description=(
                "Montre ce qui a changé dans l'atelier depuis le dernier "
                "enregistrement — de quoi relire ton propre travail."
            ),
            parameters=[],
            handler=differences,
        ),
        ModuleTool(
            name="project_history",
            description="Les derniers enregistrements de l'atelier.",
            parameters=[
                P(name="nombre", type=T.INTEGER, required=False, default=10,
                  description="Combien d'entrées afficher."),
            ],
            handler=historique,
        ),
    ]
