"""Même périmètre d'outils en conversation, en tâche de fond et à l'approbation."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path

from asgiref.sync import sync_to_async

from old.backend.modules.types import ModuleTool, ToolParameter, ToolParameterType
from old.backend.utils.tool_results import en_echec, instrumenter, texte

# Liste explicite : un nom ressemblant à « read » ne constitue pas un contrat.
LECTURES = frozenset({
    "list_recent_emails", "read_email", "search_emails", "list_contacts",
    "list_email_accounts", "forge_list_modules", "forge_read_module",
    "forge_read_logs", "memory_search", "memory_recent_souvenirs",
    "memory_read_journal", "memory_list_commitments",
    "list_rss_entries", "read_rss_entry", "search_rss", "list_rss_feeds",
    "refresh_rss_feeds", "files_list", "files_read",
})

MODULES_DE_CONTROLE = frozenset({
    "projects", "projects_tools", "project_tools", "conscience",
    "conscience_tools", "identity", "identity_tools",
})


def empreinte_cadre(project):
    return hashlib.sha256(json.dumps({
        champ: getattr(project, champ) for champ in (
            "instructions", "out_of_scope", "allowed_modules", "resource_paths",
            "contacts", "requires_approval", "tone_directive", "emotion_policy",
        )
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def executer(project_id, module, nom, params, *, approuve=False, cadre=""):
    from old.backend.modules.manager import module_manager
    from old.backend.projects.models import Project, ProjectPendingAction

    project = await sync_to_async(Project.objects.get)(pk=project_id)
    if project.status != Project.Status.ACTIVE:
        return texte("Projet inactif ; action non exécutée.", erreur=True)
    if module not in (project.allowed_modules or []) or module in MODULES_DE_CONTROLE:
        return texte("Module hors du cadre d'exécution de ce projet.", erreur=True)
    if cadre and cadre != empreinte_cadre(project):
        return texte("Le cadre a changé ; une nouvelle proposition est nécessaire.", erreur=True)
    tool = next((t for t in module_manager.get_tools_for_modules([module]) if t.name == nom), None)
    if tool is None:
        return texte("Outil indisponible ; aucune action exécutée.", erreur=True)
    if nom == "send_email":
        from old.backend.projects.views import _verifier_le_destinataire
        try:
            _verifier_le_destinataire(project, params.get("to", ""))
        except RuntimeError as exc:
            return texte(str(exc), erreur=True)
    elif module == "email" and nom not in LECTURES and project.contacts:
        return texte("Cet outil ne permet pas de vérifier le destinataire ; utilise send_email.", erreur=True)

    if project.requires_approval and nom not in LECTURES and not approuve:
        payload = {"kind": "tool", "module": module, "tool": nom,
                   "args": params, "contract": empreinte_cadre(project)}
        def proposer():
            # Dédupliquer les propositions identiques encore en attente.
            for row in ProjectPendingAction.objects.filter(project=project, status="pending"):
                if row.payload == payload:
                    return row
            return ProjectPendingAction.objects.create(
                project=project, payload=payload, proposal=f"Exécuter {nom} : {params}"[:2000],
            )
        row = await sync_to_async(proposer)()
        return {
            **texte(f"Proposition #{row.pk} en attente d'approbation ; rien n'est exécuté."),
            "status": "pending_approval", "pending_action_id": row.pk,
        }
    handler = (tool.handler.__wrapped__ if getattr(tool.handler, "_mika_instrumente", False) is True
               else tool.handler)
    return await handler(params)


async def construire(project_id, *, locaux=()):
    from old.backend.modules.manager import module_manager
    from old.backend.projects.models import Project
    project = await sync_to_async(Project.objects.get)(pk=project_id)
    outils = list(locaux)
    noms = {t.name for t in outils}
    for module in project.allowed_modules or []:
        if module in MODULES_DE_CONTROLE:
            continue  # pas de délégation permettant de sortir de ce contrat
        for outil in module_manager.get_tools_for_modules([module]):
            if outil.name in noms:
                continue
            async def execute(params, module=module, nom=outil.name):
                return await executer(project_id, module, nom, params)
            outils.append(replace(outil, handler=execute))
            noms.add(outil.name)

    if project.resource_paths:
        async def lire_reference(params):
            def lire():
                # Relecture du cadre à l'exécution : une référence retirée
                # pendant le tour cesse immédiatement d'être accessible.
                actuel = Project.objects.get(pk=project_id)
                chemin = Path(str(params.get("chemin") or "")).resolve()
                racines = [Path(p).resolve() for p in actuel.resource_paths or []]
                if not any(chemin == r or (r.is_dir() and chemin.is_relative_to(r)) for r in racines):
                    return texte("Référence hors du cadre du projet.", erreur=True)
                try:
                    with chemin.open("rb") as f:
                        contenu = f.read(400_001)
                    if len(contenu) > 400_000:
                        return texte("Référence trop volumineuse (400 ko maximum).", erreur=True)
                    return texte(contenu.decode("utf-8"))
                except (OSError, UnicodeError) as exc:
                    return texte(f"Lecture impossible : {exc}", erreur=True)
            return await sync_to_async(lire)()
        outils.append(ModuleTool(
            name="project_read_reference", description="Lit une référence explicitement autorisée, en UTF-8.",
            parameters=[ToolParameter(name="chemin", type=ToolParameterType.STRING,
                                      description="Chemin absolu de la référence.")], handler=lire_reference,
        ))
    return [replace(t, handler=instrumenter(t.name, t.handler)) for t in outils]


async def completer_conversation(project_id, identite, outils):
    """Un mot-clé reconnaît un sujet ; il ne délègue pas l'accès à un atelier.

    La fiche d'identité déjà résolue porte la certitude et le canal. Sans
    propriétaire identifié en privé, la trousse de conversation reste telle
    quelle. Inutile de payer les tâches, les logs et l'atelier via build().
    """
    from old.backend.identity.trust import ChannelTrust
    from old.backend.projects.models import Project
    from old.backend.projects.toolkit import construire_trousse
    from old.backend.projects.workspace import atelier_de

    if (not identite.entity_id or not identite.may_disclose
            or identite.trust not in (ChannelTrust.AUTHENTICATED, ChannelTrust.ACCOUNT)):
        return outils
    project = await sync_to_async(lambda: Project.objects.filter(
        pk=project_id, owner_id=identite.entity_id, status=Project.Status.ACTIVE,
    ).only("id", "title", "test_command").first())()
    if project is None:
        return outils
    atelier = await sync_to_async(atelier_de)(project.pk, project.title)
    ajouts = await construire(project.pk, locaux=construire_trousse(
        atelier, commande_de_test=project.test_command,
    ))
    # Les outils du projet prennent leur version cadrée ; les outils de vie
    # (mémoire, identité, agenda, tâches) continuent d'accompagner la discussion.
    fusion = {outil.name: outil for outil in outils}
    fusion.update({outil.name: outil for outil in ajouts})
    return list(fusion.values())


async def executer_proposition(action):
    payload = action.payload
    resultat = await executer(action.project_id, payload.get("module"), payload.get("tool"),
                              payload.get("args") or {}, approuve=True,
                              cadre=payload.get("contract", ""))
    if en_echec(resultat):
        raise RuntimeError(str(resultat))
    return True, str(resultat)
