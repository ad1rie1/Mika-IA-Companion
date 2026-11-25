"""Leur part du port d'entrée (ADR 0310) : ce que le panneau d'une personne dit du travail en cours, pour une
propriétaire (``KernelPort.person_panel``) — ses projets, et ce qui attend un accord, une commande réseau montrée
entière et exacte (``_work``, ``_proposal_text``). ``app/mindport.py::KernelPort`` mêle sa méthode aux siennes et
l'appelle par ``PortPart.work``."""

from __future__ import annotations

import json
from typing import Any

from mika.app.console import FACULTY_LABELS, OWNER_LABELS
from mika.app.domains.domain import PortPart
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.faculties.projects import actions as project_actions
from mika.faculties.projects import work as projects_work
from mika.kernel.clock import local
from mika.ports.workshop import argv_lines
from mika.vocab.episodes import project_of


def _owner_words(owner: str) -> str:
    """Ce qu'on voit d'un effet en attente qui n'appartient à aucun projet : son propriétaire, en mots — le mot court
    que sa fiche lui donne (« Forge »), sinon le nom de sa faculté (« Courrier », « Teams »)."""
    return OWNER_LABELS.get(owner) or FACULTY_LABELS.get(owner) or owner


def _proposal_text(summary: str, capability: str, effect: Any) -> str:
    """Ce qu'on montre d'une demande qui attend un accord. Une commande réseau se montre **entière et exacte**, un
    argument par ligne (lue dans ce qui partira, pas dans un résumé qu'on aurait pu couper) ; ses raisons restent ses
    mots à elle."""
    if capability != f"{projects_c.OWNER}.networked" or effect is None:
        return summary
    try:
        argv = json.loads(effect.args_json).get("argv") or []
    except (ValueError, AttributeError):
        return summary
    exact = argv_lines([str(a) for a in argv])
    return summary if exact in summary else f"{summary}\n\nLa commande exacte, un argument par ligne :\n{exact}"


class ProjectsPort:
    """Le travail en cours, pour une propriétaire. Elle lit ``self.kernel`` et ``self._store``, que pose ``KernelPort``."""

    def _work(self, frame: Any) -> dict[str, Any]:
        """Ses projets et ce qui attend un accord — pour une propriétaire."""
        live = frame.get(projects_c.LIVE)
        pending = frame.get(rt.PENDING_EFFECTS)
        refs = [p.title_ref for p in live] + [e.summary_ref for e in pending]
        texts = self._store.content([r for r in refs if r])
        state = frame.state("projects")
        tz = frame.env.tz_of(frame.root)
        projects = []
        for v in live:
            p = state.projects.get(v.id)
            nxt = projects_work.next_run_at(p, state, frame) if p is not None else None
            projects.append({
                "id": v.id, "title": texts.get(v.title_ref, ""),
                "status": "active" if v.status == projects_c.ACTIVE else "paused", "priority": v.priority,
                "origin": "user" if v.authority == projects_c.USER else "self",
                "emotion_policy": "full" if v.mode == projects_c.PERSONA else "off",
                # ce que montre le panneau : rien pour son mode à elle, « impersonnel » pour un travail factuel
                "mode_label": "" if v.mode == projects_c.PERSONA else "impersonnel",
                "schedule_rule": v.schedule or "manual",
                "schedule_label": project_actions.schedule_words(v.schedule),
                "next_run_at": local(nxt, tz).isoformat() if nxt else None,
                # ses objectifs ponctuels : faits sur tous (les constants n'ont pas de fin)
                "tasks_total": v.open_once + v.done_once + v.blocked_once, "tasks_done": v.done_once,
                "tasks_blocked": v.blocked_once})
        actions = []
        effects = frame.state("runtime").effects
        capabilities = self.kernel.mind.registry.capabilities
        for e in pending:
            pid = project_of(e.context)
            p = state.projects.get(pid) if pid is not None else None
            title = self._store.content([p.title_ref]).get(p.title_ref, "") if p is not None else ""
            spec = capabilities.get(e.capability)
            actions.append({"id": e.proposal, "project_id": pid or 0, "project_title": title or e.owner,
                            "proposal": _proposal_text(texts.get(e.summary_ref, ""), e.capability,
                                                       effects.get(e.proposal)),
                            "payload_kind": e.capability, "created_at": local(e.at, tz).isoformat(),
                            # ce que le panneau en montre : à qui c'est (un projet, « Courrier », « Forge »), et ce
                            # que ça fera, en mots — jamais ``email`` ni ``email.send``
                            "owner_label": title or _owner_words(e.owner),
                            "kind_label": spec.description if spec is not None else ""})
        return {"projects": projects, "pending_project_actions": actions}


#: le panneau d'une personne y prend ses projets et ce qui attend un accord (``person_panel``)
PORT = PortPart(methods=ProjectsPort, work=ProjectsPort._work)
