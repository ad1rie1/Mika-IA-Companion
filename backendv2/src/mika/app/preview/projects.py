"""Une chaîne de travail d'exemple pour relire la console des projets (ADR 0281), dans le magasin temporaire de
l'aperçu : un produit, et un projet qui le lit et lui adresse une demande ; des tickets à chaque étape où la main est
au propriétaire, un point d'arrêt dit prêt, une liste de suivi à sa charge, une mission déclenchée par un commit, un
plan qui attend sa réponse. Les gestes d'un opérateur passent par les actions de la console ; ce que seule une
exécution écrit (une demande d'un autre projet, sa question, son plan, un jalon dit prêt) par les brouillons de la
faculté, comme elle les écrirait."""

from __future__ import annotations

from typing import Any

from mika.contracts import projects as c
from mika.faculties.projects import milestones, tracker
from mika.faculties.projects.actions import link_knob
from mika.faculties.projects.faculty import PLAN_PROPOSED, project_at, subjects_of, written
from mika.kernel.events import Content, Origin
from mika.runtime.operations import perform

BY = "user_1"
#: les entreprises de la liste d'exemple (leur clé, leur nom) : à la charge du propriétaire
COMPANIES = (("acme", "Acme Réseaux"), ("boreal", "Boréal Hébergement"), ("cobalt", "Cobalt Systèmes"),
             ("delta", "Delta Infogérance"), ("ecume", "Écume Télécom"))


async def _do(kernel: Any, action: str, subject: str, nonce: str, fixed: dict[str, str] | None = None,
              **values: str) -> bool:
    posted: dict[str, Any] = {"_champs": list(values), **{k: [v] for k, v in values.items()}}
    if fixed:
        posted |= {"_fixes": list(fixed), **{k: [v] for k, v in fixed.items()}}
    got = await perform(kernel, f"projects.{action}", posted, by=BY, subject=subject, nonce=f"apercu-chaine-{nonce}")
    return bool(got.ok)


async def _write(kernel: Any, drafts: list[Any], slug: str) -> None:
    await kernel.mind.append(drafts, emitter="projects", origin=Origin.GENESIS, correlation=f"apercu-chaine-{slug}")


def _project(kernel: Any, key: str) -> Any:
    return project_at(kernel.mind.frame().state("projects"), key)


async def chain(kernel: Any, product: str, reader: str) -> None:
    """Fait de ``reader`` un projet qui lit ``product``, et pose sur les deux de quoi remplir chaque onglet."""
    if not product or not reader or _project(kernel, product) is None or _project(kernel, reader) is None:
        return
    pid = int(product)
    # ── le projet lecteur : son lien, sa mission déclenchée par le produit, sa liste, son plan ──
    await _do(kernel, "liens", reader, "lien", **{link_knob(pid): "on"})
    await _do(kernel, "objectif_ajouter", reader, "mission", text="Garder le site cohérent avec le produit",
              kind=c.CONSTANT, cadence_hours="48", on=f"project:{pid}:commit")
    await _do(kernel, "liste_regler", reader, "liste", name="entreprises", title="Entreprises à contacter",
              open="à contacter\ncontactée", closed="a répondu\nsans suite", actor=c.ACTOR_OWNER)
    for key, name in COMPANIES:
        await _do(kernel, "element_ajouter", reader, f"e-{key}", list_name="entreprises", title=name, key=key)
    r = _project(kernel, reader)
    await _write(kernel, [PLAN_PROPOSED.draft(
        project=r.id, plan=Content.of("1. Relire la page d'accueil face au produit.\n2. Écrire trois articles.\n"
                                      "3. Tenir la liste des entreprises, que tu contactes toi-même.", level=1),
        questions=Content.of("Faut-il publier les articles un par semaine ? Je recommande : oui, le mardi.", level=1),
        owner=r.owner, about=r.about)], "plan")
    # ── le produit : un ticket à chaque étape où la main est à toi, et un point d'arrêt dit prêt ──
    await _do(kernel, "ticket_ouvrir", product, "t-pied", title="Le pied de page est vide", kind=c.BUG,
              priority=c.HIGH)
    p, r = _project(kernel, product), _project(kernel, reader)
    await _write(kernel, [tracker.adding(
        p, c.TICKETS, "demande-export", "Exporter la liste des hôtes en CSV",
        text="Le site doit montrer un exemple d'export. Fait quand : la commande « export » écrit un CSV.",
        kind=c.TASK, proposed=True, author=c.item_author(r.id), level=written(r), inherited=subjects_of(r))], "demande")
    await _write(kernel, [tracker.adding(
        p, c.TICKETS, "question-port", "Quel port par défaut pour RDP ?", kind=c.QUESTION, text="3389, ou un port "
        "choisi à l'installation ?")], "t-question")
    await _write(kernel, [tracker.adding(p, c.TICKETS, "plan-journal", "Journaliser les connexions refusées",
                                         kind=c.TASK)], "t-plan")
    p = _project(kernel, product)
    asked, planned = (tracker.held(p.board, c.TICKETS, key) for key in ("question-port", "plan-journal"))
    notes = []
    if asked is not None:
        notes.append(tracker.ITEM_NOTED.draft(
            project=p.id, list_name=c.TICKETS, key=asked.key, kind=c.NOTE_QUESTION, owner=p.owner, about=p.about,
            text=Content.of("Je garde 3389 par défaut, ou je le demande à l'installation ?", level=1)))
    if planned is not None:
        notes.append(tracker.ITEM_NOTED.draft(
            project=p.id, list_name=c.TICKETS, key=planned.key, kind=c.NOTE_PLAN, owner=p.owner, about=p.about,
            text=Content.of("Plan : un journal tournant de 7 jours, une ligne par refus. Fait quand : un refus "
                            "simulé s'y lit.", level=1)))
    if notes:
        await _write(kernel, notes, "notes")
    once = next((o for o in p.objectives if o.kind == c.ONCE and o.status == c.OPEN), None)
    if once is None:
        return
    await _do(kernel, "jalon_ajouter", product, "j-1", {"objective": str(once.id)},
              text="Le module se connecte à un hôte de test", check=c.CHECK_PROSE)
    await _do(kernel, "jalon_ajouter", product, "j-2", {"objective": str(once.id)},
              text="Tu as relu l'écran de connexion", check=c.CHECK_OWNER)
    p = _project(kernel, product)
    o = next((x for x in p.objectives if x.id == once.id), None)
    stop = next((m for m in (o.milestones if o is not None else ()) if m.check == c.CHECK_OWNER), None)
    if stop is not None:
        await _write(kernel, [milestones.changing(
            p, once.id, stop, level=written(p), inherited=(), ready=True,
            how="L'écran est dans « ui/connexion.py » : un champ hôte, un champ port, le bouton.")], "pret")
