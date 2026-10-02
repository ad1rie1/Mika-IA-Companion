"""Ce que le noyau fait d'une commande d'un client du monde (ADR 0050) — sans rien écrire lui-même.

``handle`` lit le monde, valide, et rend un verdict : les brouillons à journaliser (au nom de ``world``, sous la
garde qu'il donne) ou un refus avec son code et sa phrase. Le port d'entrée (``app/mindport.py``) l'appelle et
écrit ; l'adaptateur ne fait que l'authentification, les rôles, le bail, les débits et le dédoublonnage — toute
règle du monde est ici.

Ce qu'un hôte constate n'est jamais cru sur parole : une action qu'il dit terminée est conclue par le noyau, sur
l'état d'alors (comme à son échéance) ; une action qu'il dit ratée ne change que ce qui est vrai — où est
l'acteur, si c'est un endroit qui existe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mika.contracts import world as w
from mika.faculties.world import WorldState, plan
from mika.kernel.events import Draft
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard


@dataclass(frozen=True, slots=True)
class Verdict:
    """Accepté (avec, peut-être, des brouillons à écrire sous ``guard``) ou refusé (``code`` et ``message``)."""

    drafts: tuple[Draft[Any], ...] = ()
    code: w.Refusal | None = None
    message: str = ""
    guard: Guard | None = None

    @property
    def ok(self) -> bool:
        return self.code is None


def _refused(code: w.Refusal, message: str) -> Verdict:
    return Verdict(code=code, message=message)


#: Une écriture qui suppose que le monde n'a pas bougé depuis la validation (sinon : ``stale``, rien d'écrit).
UNCHANGED = Guard("monde inchangé", reads=(w.STATE,))


def handle(frame: Frame, command: Any, *, actor: str, handle: str | None, operator: bool) -> Verdict:
    """Le verdict du noyau sur une commande (``w.Command``) d'un client, pour l'acteur qu'il incarne."""
    s: WorldState = frame.state("world")
    if isinstance(command, w.Report):
        if not operator:
            return _refused(w.Refusal.NOT_HOST, "Seul un moteur hôte, sur un compte opérateur, constate le monde.")
        body = command.report
        if isinstance(body, w.Finished):
            return _finished(s, body)
        if isinstance(body, w.Progress | w.Loaded):
            return Verdict()  # rien à écrire : le progrès ne décide rien, ce qui manque se lit dans la console
    return _refused(w.Refusal.UNSUPPORTED, "Ce noyau ne sait pas encore faire ça (ADR 0050 : les personnes dans le "
                                           "monde et l'édition arrivent ensuite).")


def _finished(s: WorldState, f: w.Finished) -> Verdict:
    intent = s.intents.get(f.intent)
    if intent is None:
        return _refused(w.Refusal.UNKNOWN, "Cette action n'est plus en cours (déjà terminée, ou remplacée).")
    if f.outcome is w.Outcome.DONE:
        outcome, reason, changes = plan.conclude(s.definition, s.actors, s.objects, intent)
    else:
        outcome, reason = f.outcome, f.reason
        changes = []
        if f.at is not None:
            if f.at.actor != intent.actor:
                return _refused(w.Refusal.IMPLAUSIBLE, "La position donnée n'est pas celle de l'acteur de l'action.")
            place = s.definition.place(f.at.place) if f.at.place else None
            if s.definition.room(f.at.room) is None or (f.at.place is not None and (place is None
                                                                                   or place.room != f.at.room)):
                return _refused(w.Refusal.IMPLAUSIBLE, "Cet endroit n'existe pas dans le monde.")
            if place is not None and f.at.posture not in w.POSTURES[place.place_kind]:
                return _refused(w.Refusal.IMPLAUSIBLE, "On ne se tient pas comme ça à cet endroit.")
            changes = [f.at]
    draft = w.ENDED.draft(intent=intent.id, actor=intent.actor, outcome=outcome, reason=reason,
                          changes=tuple(changes), dedupe_key=f"fin:{intent.id}")
    return Verdict(drafts=(draft,), guard=UNCHANGED)
