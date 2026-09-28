"""Choisir les moyens d'une intention et lui donner une suite durable."""

from contextvars import ContextVar
from asgiref.sync import sync_to_async

from modules.types import ModuleTool, ToolParameter, ToolParameterType
from utils.tool_results import texte

travail_courant = ContextVar("conscience_travail", default=None)


def outils():
    async def decouvrir(args):
        from modules.manager import module_manager
        lignes = []
        for nom, capacites in module_manager.collect_capabilities().items():
            lignes.append(f"{nom}: " + "; ".join(c.description for c in capacites))
        return texte("\n".join(lignes)[:12000] or "Aucune capacité disponible.")

    async def preparer(args):
        from modules.manager import module_manager
        from conscience.models import Travail
        from projects.models import Project
        from projects.schedule import compute_next_run
        from django.utils import timezone
        from django.db import transaction

        raison = str(args.get("reason") or "").strip()[:2000]
        if not raison:
            return texte("Précise le besoin concret et ton prochain pas.", erreur=True)
        modules = args.get("modules") or []
        if not isinstance(modules, list) or any(not isinstance(m, str) for m in modules):
            return texte("modules doit être une liste de noms.", erreur=True)
        modules = list(dict.fromkeys(modules))[:5]
        disponibles = module_manager.collect_capabilities()
        inconnus = [m for m in modules if m not in disponibles]
        if inconnus:
            return texte(
                f"Capacités indisponibles : {', '.join(inconnus)}. Consulte discover_capabilities.", erreur=True,
            )
        identifiant = travail_courant.get()
        if identifiant is None:
            return texte(
                "Cet outil prépare le chantier autonome en cours ; aucun chantier actif dans ce tour.", erreur=True,
            )

        def enregistrer():
            with transaction.atomic():
                travail = Travail.objects.get(pk=identifiant)
                if travail.projet_id:
                    return texte(f"Ce chantier continue déjà dans le projet #{travail.projet_id}.")
                if travail.statut != Travail.Statut.EN_COURS:
                    return texte("Ce chantier est déjà clos.", erreur=True)
                travail.modules = modules
                travail.resultat = (travail.resultat + f"\nProchain pas : {raison}")[-6000:]
                if args.get("durable"):
                    # Un besoin personnel ne peut modifier aucun mandat existant.
                    projet = Project.objects.create(
                        title=travail.titre, description=raison,
                        origin=Project.Origin.SELF, emotion_policy=Project.EmotionPolicy.FULL,
                        allowed_modules=modules, schedule_rule="idle:15m",
                        next_run_at=compute_next_run("idle:15m", timezone.now()),
                    )
                    travail.projet = projet
                    travail.statut = Travail.Statut.TRANSFERE
                travail.save(update_fields=["modules", "resultat", "projet", "statut", "updated_at"])
                return texte(f"Poursuite dans le projet personnel #{travail.projet_id}." if travail.projet_id
                             else "Capacités choisies pour le prochain pas ; elles seront chargées à sa reprise.")
        return await sync_to_async(enregistrer)()

    return [
        ModuleTool("discover_capabilities", "Découvre les modules disponibles et leurs capacités.", [], decouvrir),
        ModuleTool("prepare_activity",
                   "Choisis les modules du prochain pas de ton chantier. Pour fabriquer un outil manquant, "
                   "choisis forge et décris le besoin, puis crée et teste ton module au pas suivant. "
                   "durable=true poursuit ce chantier dans un projet personnel ; cela ne termine pas le travail.",
                   [ToolParameter("modules", ToolParameterType.ARRAY, "Modules nécessaires (max. 5)."),
                    ToolParameter("reason", ToolParameterType.STRING, "Besoin concret, objectif et prochain pas."),
                    ToolParameter("durable", ToolParameterType.BOOLEAN,
                                  "En faire un projet personnel suivi.", required=False)],
                   preparer),
    ]
