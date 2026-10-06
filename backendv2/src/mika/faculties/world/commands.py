"""Ce que le noyau fait d'une commande d'un client du monde (ADR 0050) — sans rien écrire lui-même.

``handle`` lit le monde, valide, et rend un verdict : les brouillons à journaliser (au nom de ``world``, sous la
garde qu'il donne) ou un refus avec son code et sa phrase. Le port d'entrée (``app/mindport.py``) l'appelle et
écrit ; l'adaptateur ne fait que l'authentification, les rôles, le bail, les débits et le dédoublonnage — toute
règle du monde est ici.

Ce qu'un hôte constate n'est jamais cru sur parole : une action qu'il dit terminée est conclue par le noyau, sur
l'état d'alors (comme à son échéance) ; une action qu'il dit ratée ne change que ce qui est vrai — où est
l'acteur, si c'est un endroit qui existe.

Une édition d'une opératrice (le créateur) passe en entier ou pas du tout, sur la révision qu'elle a lue (ADR 0050
§10). Ce premier éditeur ne touche ni aux pièces, ni à l'existence des lieux, ni aux personnages : les lieux sont
l'énumération du schéma de ``go_to``, tirée du monde par défaut (un schéma par épisode attend l'éditeur complet,
P5) ; les personnages arrivent avec P4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import social as social_c
from mika.contracts import world as w
from mika.faculties.world import WorldState, felt, plan, setback
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
    if isinstance(command, w.Address) and command.gesture is not None and command.request is None:
        return _gesture(frame, s, command, command.gesture, actor=actor, handle=handle)
    if isinstance(command, w.Edit):
        if not operator:
            return _refused(w.Refusal.NOT_CREATOR, "Seul un compte opérateur édite le monde.")
        return _edit(s, command, by=(handle or actor)[:96])
    # le reste n'est pas encore là : une demande (elle attend sa réponse, par un outil à venir), un acte, la prose
    # du créateur
    return _refused(w.Refusal.UNSUPPORTED, "Ce noyau ne sait pas encore faire ça (ADR 0050 : les personnes dans le "
                                           "monde et la prose du créateur arrivent ensuite).")


#: Ce qu'un lieu qui existe laisse éditer (ADR 0050 §10) : sa position et son orientation — son nom, sa sorte, sa
#: pièce sont ce que ``go_to`` lui dit encore.
PLACE_EDITABLE = ("pos", "facing")
#: Ce que ce premier éditeur ne change pas (les objets et les archétypes, si).
_FIXED_FR = {"room": "la pièce", "place": "le lieu", "actor": "le personnage"}


def _beyond(defn: w.WorldDef, changes: tuple[w.DefPut | w.DefRemove, ...]) -> list[str]:
    """Ce qu'un lot demande au-delà de ce premier éditeur, en mots (vide : rien) — tout, d'un coup. Un élément remis
    tel quel ne change rien et passe."""
    out: list[str] = []
    for ch in changes:
        if isinstance(ch, w.DefRemove):
            if ch.of.value in _FIXED_FR:
                out.append(f"retirer {_FIXED_FR[ch.of.value]} « {ch.id} »")
            continue
        item = ch.item
        if item.kind not in _FIXED_FR:
            continue
        current = {"room": defn.room, "place": defn.place, "actor": defn.actor}[item.kind](item.id)
        if current is None:
            out.append(f"ajouter {_FIXED_FR[item.kind]} « {item.id} »")
        elif isinstance(current, w.PlaceDef):
            if current.model_copy(update={f: getattr(item, f) for f in PLACE_EDITABLE}) != item:
                out.append(f"changer le lieu « {item.id} » autrement qu'en position ou en orientation")
        elif current != item:
            out.append(f"changer {_FIXED_FR[item.kind]} « {item.id} »")
    return out


def _edit(s: WorldState, e: w.Edit, *, by: str) -> Verdict:
    """Un lot d'édition : sur la révision en vigueur, dans ce que sait ce premier éditeur, cohérent — ou rien."""
    if e.base != s.definition.rev:
        return _refused(w.Refusal.STALE, f"Ce lot est écrit sur la révision {e.base} ; le monde en est à la "
                                         f"{s.definition.rev} : relis-le, puis recommence.")
    if beyond := _beyond(s.definition, e.changes):
        return _refused(w.Refusal.UNSUPPORTED, "Ce premier éditeur change les objets, les archétypes, et la position "
                                               "ou l'orientation d'un lieu (ADR 0050) ; pas encore : "
                                               + " ; ".join(beyond) + ". Rien n'a changé.")
    try:
        w.apply_changes(s.definition, e.changes)
    except ValueError as exc:
        return _refused(w.Refusal.INCOHERENT, f"Le monde serait incohérent : {_why(exc)}. Rien n'a changé.")
    return Verdict(drafts=(w.AUTHORED.draft(base_rev=e.base, changes=e.changes, by=by),), guard=UNCHANGED)


def _why(exc: ValueError) -> str:
    """La phrase d'un refus d'``apply_changes`` : la sienne, ou celles du validateur du monde, sans l'enrobage de
    pydantic."""
    if isinstance(exc, ValidationError):
        return " ; ".join(str(err.get("ctx", {}).get("error", err["msg"])) for err in exc.errors())
    return str(exc)


def _gesture(frame: Frame, s: WorldState, a: w.Address, gesture: w.Gesture, *, actor: str,
             handle: str | None) -> Verdict:
    """Un geste vers quelqu'un de la même pièce : il se fait sans accord (le contrat ``Gesture``) — et, quand il
    est pour elle et qu'elle est éveillée, elle le ressent selon qui le fait (``felt`` : la proximité gradue, rien
    n'est interdit). Le corps réagit tout de suite sur les écrans ; le ressenti passe par son attention."""
    me, to = s.actors.get(actor), s.actors.get(a.to)
    if me is None:
        return _refused(w.Refusal.UNKNOWN, "Tu n'es pas dans le monde : entre d'abord dans sa chambre.")
    if to is None:
        return _refused(w.Refusal.UNKNOWN, "Il n'y a personne de ce nom dans le monde.")
    if to.room != me.room:
        return _refused(w.Refusal.UNREACHABLE, "Vous n'êtes pas dans la même pièce.")
    if a.object is not None and a.object not in s.objects:
        return _refused(w.Refusal.UNKNOWN, "Cet objet n'est pas dans le monde.")
    gestured = w.GESTURED.draft(actor=actor, gesture=gesture, to_actor=a.to, object=a.object, by=handle)
    noticed = None
    if a.to == w.MIKA and frame.get(body_c.SLEEP) is body_c.SleepPhase.AWAKE:
        person = frame.get(identity_c.PERSON(handle)) if handle else None
        name = frame.get(identity_c.IDENTITY(handle)).name if handle else ""
        closeness = frame.get(social_c.CLOSENESS(person)) if person else None
        noticed = felt(actor, gesture, closeness, name or "Quelqu'un", person)
    # ce qu'elle en sent avant le geste lui-même : l'accusé porte le ``seq`` du dernier brouillon, celui de la trame
    # qui montre le geste
    return Verdict(drafts=(gestured,) if noticed is None else (noticed, gestured), guard=UNCHANGED)


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
    noticed = setback(s, intent, outcome, reason)
    # ce qu'elle en remarque avant la fin elle-même : l'accusé de l'hôte porte le ``seq`` du dernier brouillon,
    # celui de la trame qui applique sa commande
    return Verdict(drafts=(draft,) if noticed is None else (noticed, draft), guard=UNCHANGED)
