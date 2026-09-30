"""La liste de composition : quelles facultés forment Mika, et comment le
noyau les fait parler.

Ajouter une faculté = ajouter son paquet et l'inscrire ici. Tout le reste
(registre, rejeu, prompt, arbitrage, inspecteur) la découvre seul.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from mika.app.paths import PERSONA
from mika.contracts import identity as identity_c
from mika.contracts import self_ as self_c
from mika.faculties.affect import AFFECT
from mika.faculties.agency import AGENCY, task_brief
from mika.faculties.agency import brief as initiative_brief
from mika.faculties.attention import ATTENTION
from mika.faculties.body import BODY
from mika.faculties.expression import EXPRESSION
from mika.faculties.expression import parse as parse_reply
from mika.faculties.goals import GOALS, step_brief
from mika.faculties.identity import IDENTITY, audience_for
from mika.faculties.memory import MEMORY
from mika.faculties.needs import NEEDS
from mika.faculties.others import OTHERS
from mika.faculties.presence import PRESENCE
from mika.faculties.self import SELF, load, persona_for
from mika.faculties.social import SOCIAL
from mika.faculties.transcript import TRANSCRIPT
from mika.kernel.episode import EpisodePolicy
from mika.kernel.events import Origin
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Audience, Frame
from mika.kernel.guards import Guard
from mika.kernel.registry import ArbitrationPolicy
from mika.plugins.camera import CAMERA
from mika.plugins.email import EMAIL
from mika.plugins.forge import FORGE
from mika.plugins.rss import RSS
from mika.plugins.sensors import SENSORS
from mika.runtime import params
from mika.runtime.bootstrap import Kernel, KernelDeps
from mika.sim.world import Composition
from mika.vocab.episodes import VOICE_ROLES, Kind, Role

log = logging.getLogger("mika.composition")


def faculties() -> list[Faculty[Any, Any]]:
    """Les facultés de Mika, puis ses plugins (M7)."""
    return [PRESENCE, IDENTITY, TRANSCRIPT, MEMORY, BODY, AFFECT, NEEDS, OTHERS, ATTENTION, SELF, EXPRESSION,
            SOCIAL, AGENCY, GOALS, EMAIL, RSS, CAMERA, FORGE, SENSORS]


def _reply_guard(frame: Frame, target: str | None, audience: Audience | None) -> Guard | None:
    """Une réponse composée avec ce qu'on pouvait dire à cette audience est
    supplantée si la divulgation change en plein tour (un démenti d'identité)."""
    if not target or audience is None:
        return None
    return Guard("divulgation", reads=(identity_c.DISCLOSURE((target, audience.channel, audience.public)),))


def policies() -> dict[str, EpisodePolicy]:
    return {
        Kind.REPLY: EpisodePolicy(kind=Kind.REPLY, role=Role.REPLY, priority=0, lane="conversation",
                                  guard=_reply_guard, max_tokens=1024, deadline_s=180.0,
                                  tool_bundles=frozenset({"memory", "identity", "goals", "email", "rss", "camera",
                                                          "forge", "forge_apps", "self", "attention", "social"}),
                                  core_bundles=frozenset({"memory", "identity", "goals"})),
        Kind.INITIATIVE: EpisodePolicy(kind=Kind.INITIATIVE, role=Role.INITIATIVE, priority=1, lane="conversation",
                                       brief=initiative_brief, max_tokens=600, deadline_s=180.0,
                                       tool_bundles=frozenset({"memory", "identity", "rss", "forge_apps", "self",
                                                               "attention", "social"}),
                                       core_bundles=frozenset({"memory", "identity"})),
        # un pas de travail : sa voix (compacte), pour elle seule — ni fil, ni livraison ; le verdict fait l'affect
        Kind.STEP: EpisodePolicy(kind=Kind.STEP, role=Role.STEP, priority=2, lane="background",
                                 persona_depth="compact", visible=False, delivered=False, brief=step_brief,
                                 max_tool_turns=12, max_tokens=2048, deadline_s=300.0,
                                 tool_bundles=frozenset({"goals", "memory", "workshop", "email", "rss",
                                                         "camera", "forge", "forge_apps"})),
        # une tâche qu'une faculté lui confie (préparer un brouillon de réponse) : sa voix, pour elle seule
        Kind.TASK: EpisodePolicy(kind=Kind.TASK, role=Role.STEP, priority=2, lane="background",
                                 persona_depth="compact", visible=False, delivered=False, brief=task_brief,
                                 max_tool_turns=6, max_tokens=2048, deadline_s=240.0,
                                 tool_bundles=frozenset({"email", "memory", "identity"})),
        # une pensée à voix haute : sa voix brève, pas dans le fil, à l'écran seulement
        Kind.MURMUR: EpisodePolicy(kind=Kind.MURMUR, role=Role.MURMUR, priority=1, lane="conversation",
                                   persona_depth="compact", visible=False, max_tokens=80, deadline_s=60.0),
    }


def arbitration() -> ArbitrationPolicy:
    """Seuils en log-odds, taux maximaux par seconde. Une raison forte (saluer
    quelqu'un qui arrive) se déclenche en secondes ; le fond (une présence
    sans raison) presque jamais ; une humeur qui déborde, en minutes. Un pas de
    travail, en quelques minutes quand l'envie est là ; rarement quand elle
    s'use."""
    return ArbitrationPolicy(
        thresholds={Kind.INITIATIVE: 9.0, Kind.STEP: 8.0, Kind.TASK: 8.0},
        max_rates={Kind.INITIATIVE: 0.1, Kind.STEP: 1 / 120, Kind.TASK: 1 / 300},
        aging_per_hour={Kind.INITIATIVE: 0.0, Kind.STEP: 0.0, Kind.TASK: 0.0},
    )


def deps(**kw: Any) -> KernelDeps:
    """Les dépendances du noyau pour cette composition ; horloge, magasin,
    identifiants et passerelle sont fournis par l'appelant (serveur ou
    simulateur)."""
    base: dict[str, Any] = {
        "faculties": faculties(),
        "policies": policies(),
        "arbitration": arbitration(),
        "persona": persona_for,
        "audience_of": audience_for,
        "parsers": [parse_reply],
        "reply_kind": Kind.REPLY,
    }
    base.update(kw)
    return KernelDeps(**base)


async def configure(kernel: Kernel, doc: self_c.PersonaDoc, overrides: Mapping[str, Mapping[str, Any]] | None = None,
                    inputs: Mapping[str, Mapping[str, Any]] | None = None) -> bool:
    """Journalise la persona si elle a changé, puis les paramètres (fuseau, et
    ceux de chaque faculté : défaut ← tempérament ← réglages ← surcharges,
    ``runtime/params.py``). Une surcharge refusée est ignorée et signalée, jamais
    fatale. Rend ``True`` si quelque chose a été ajouté."""
    changed = False
    state = kernel.mind.root.slices["self"]
    if state.revisions == 0 or state.persona != doc:
        await kernel.mind.append([self_c.PERSONA_REVISED.draft(persona=doc)], emitter="self",
                                 correlation="persona", origin=Origin.GENESIS)
        changed = True
    # le fuseau de sa persona est un réglage du noyau (jamais une surcharge qu'un plan effacerait)
    given = {k: dict(v) for k, v in (inputs or {}).items()}
    given["kernel"] = {**given.get("kernel", {}), "tz": doc.timezone}
    inputs = given
    faculties = list(kernel.registry.faculties.values())
    planned = params.plan(faculties, doc.temperament, overrides, inputs)
    for owner, p in planned.items():
        if p.refused:
            log.warning("surcharges de %s ignorées : %s", owner, dict(p.refused))
    for owner, value in params.to_journal(kernel, planned, overrides, inputs):
        changed |= await kernel.set_params(owner, value)
    return changed


def for_simulation(persona: self_c.PersonaDoc | None = None) -> Composition:
    """La même racine, pour le simulateur (qui ne connaît aucune faculté)."""

    return Composition(deps=deps, configure=configure, persona=persona or load(PERSONA),
                       voice_roles=frozenset(str(r) for r in VOICE_ROLES))
