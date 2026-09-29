"""La liste de composition : quelles facultés forment Mika, et comment le
noyau les fait parler.

Ajouter une faculté = ajouter son paquet et l'inscrire ici. Tout le reste
(registre, rejeu, prompt, arbitrage, inspecteur) la découvre seul.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.app.paths import PERSONA
from mika.contracts import identity as identity_c
from mika.contracts import self_ as self_c
from mika.faculties.affect import AFFECT
from mika.faculties.agency import AGENCY
from mika.faculties.agency import brief as initiative_brief
from mika.faculties.attention import ATTENTION
from mika.faculties.body import BODY
from mika.faculties.expression import EXPRESSION
from mika.faculties.expression import parse as parse_reply
from mika.faculties.identity import IDENTITY, audience_for
from mika.faculties.memory import MEMORY
from mika.faculties.needs import NEEDS
from mika.faculties.presence import PRESENCE
from mika.faculties.self import SELF, load, persona_for
from mika.faculties.social import SOCIAL
from mika.faculties.transcript import TRANSCRIPT
from mika.kernel.builtin import KernelParams
from mika.kernel.episode import EpisodePolicy
from mika.kernel.events import Origin
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Audience, Frame
from mika.kernel.guards import Guard
from mika.kernel.registry import ArbitrationPolicy
from mika.runtime.bootstrap import Kernel, KernelDeps
from mika.sim.world import Composition
from mika.vocab.episodes import VOICE_ROLES, Kind, Role


def faculties() -> list[Faculty[Any, Any]]:
    """Les facultés de Mika (M4)."""
    return [PRESENCE, IDENTITY, TRANSCRIPT, MEMORY, BODY, AFFECT, NEEDS, ATTENTION, SELF, EXPRESSION, SOCIAL,
            AGENCY]


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
                                  tool_bundles=frozenset({"memory", "identity"})),
        Kind.INITIATIVE: EpisodePolicy(kind=Kind.INITIATIVE, role=Role.INITIATIVE, priority=1, lane="conversation",
                                       brief=initiative_brief, max_tokens=600, deadline_s=180.0,
                                       tool_bundles=frozenset({"memory", "identity"})),
        # une pensée à voix haute : sa voix brève, pas dans le fil, à l'écran seulement
        Kind.MURMUR: EpisodePolicy(kind=Kind.MURMUR, role=Role.MURMUR, priority=1, lane="conversation",
                                   persona_depth="compact", visible=False, max_tokens=80, deadline_s=60.0),
    }


def arbitration() -> ArbitrationPolicy:
    """Seuils en log-odds, taux maximaux par seconde. Une raison forte (saluer
    quelqu'un qui arrive) se déclenche en secondes ; le fond (une présence
    sans raison) presque jamais ; une humeur qui déborde, en minutes."""
    return ArbitrationPolicy(
        thresholds={Kind.INITIATIVE: 9.0},
        max_rates={Kind.INITIATIVE: 0.1},
        aging_per_hour={Kind.INITIATIVE: 0.0},
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


async def configure(kernel: Kernel, doc: self_c.PersonaDoc, overrides: Mapping[str, Mapping[str, Any]] | None = None) -> bool:
    """Journalise la persona si elle a changé, puis les paramètres qui en
    dérivent (fuseau, et ceux de chaque faculté depuis le tempérament).
    Rend ``True`` si quelque chose a été ajouté."""
    changed = False
    state = kernel.mind.root.slices["self"]
    if state.revisions == 0 or state.persona != doc:
        await kernel.mind.append([self_c.PERSONA_REVISED.draft(persona=doc)], emitter="self",
                                 correlation="persona", origin=Origin.GENESIS)
        changed = True
    changed |= await kernel.set_params("kernel", KernelParams(tz=doc.timezone))
    for f in kernel.registry.faculties.values():
        if f.derive is None:
            continue
        params = f.derive(doc.temperament, (overrides or {}).get(f.name))
        changed |= await kernel.set_params(f.name, params)
    return changed


def for_simulation(persona: self_c.PersonaDoc | None = None) -> Composition:
    """La même racine, pour le simulateur (qui ne connaît aucune faculté)."""

    return Composition(deps=deps, configure=configure, persona=persona or load(PERSONA),
                       voice_roles=frozenset(str(r) for r in VOICE_ROLES))
