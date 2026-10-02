"""Ce qu'un opérateur peut faire des liens depuis la console : déclarer la
proximité d'une personne (genèse, correction), ou la rendre à ce que leur
histoire a installé.

L'action rend un brouillon de ``social.closeness_set`` qui nomme l'opérateur ;
le moteur le journalise comme venant de l'extérieur, avec son audit, sous
garde (la proximité qu'il a vue n'a pas changé entre-temps). Déclarer une
proximité qui ouvre davantage que ce qu'elles ont vécu — ce que d'autres lui
ont confié pourra être dit à cette personne — s'annonce, et demande d'être
confirmé.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, field_validator

from mika.contracts import identity as identity_c
from mika.contracts import social as c
from mika.faculties.social.faculty import SOCIAL, SocialState
from mika.faculties.social.inspect import AUTO, CLOSENESS_FR, settable
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.kernel.operate import ActionContext, Done, Refused

CHOICES = ((AUTO, "automatique (née de leur histoire)"), *((k, CLOSENESS_FR[k]) for k in c.CLOSENESS_LEVELS))
_RANK = {level: i for i, level in enumerate(c.CLOSENESS_LEVELS)}
#: Ce que chaque proximité ouvre de ce que d'autres lui ont confié.
OPENS = {c.FRIEND: "ce que d'autres lui ont dit de personnel pourra lui être raconté",
         c.CLOSE: "même les confidences d'autres personnes pourront lui être dites"}


class ClosenessArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closeness: Annotated[str, Knob(
        label="Proximité", choices=CHOICES, advanced=False,
        help="Déclarée, elle l'emporte sur ce que leur histoire a installé ; « automatique » la lui rend.")] = AUTO
    confirmed: Annotated[bool, Knob(
        label="Je confirme", advanced=False,
        help="Exigé quand la proximité déclarée ouvre davantage que ce qu'elles ont vécu : ce que d'autres lui "
             "ont confié pourra être dit à cette personne.")] = False

    @field_validator("closeness")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in {k for k, _label in CHOICES}:
            raise ValueError("proximité inconnue")
        return value


def _available(s: SocialState, frame: Frame, key: str) -> bool:
    return settable(frame, key)


def _seen(person: str, level: str) -> Guard:
    """L'opération ne vaut que si sa proximité est toujours celle que l'opérateur a vue."""
    return Guard("proximité inchangée", predicate=lambda view, p=person, lv=level: view.get(c.CLOSENESS(p)) == lv)


@SOCIAL.action("proximite", title="Fixer la proximité", args=ClosenessArgs, emits=[c.CLOSENESS_SET],
               subject="person", available=_available, order=10,
               confirm="Changer sa proximité ? Ce qu'elle peut lui confier d'autres personnes en dépend.",
               description="Pas encore de lien, connaissance, amitié ou proche : ce qu'elle peut lui confier en "
                           "dépend.")
def _set_closeness(s: SocialState, frame: Frame, args: ClosenessArgs, ctx: ActionContext) -> Done:
    person = ctx.subject
    level = "" if args.closeness == AUTO else args.closeness
    current = s.declared.get(person, "")
    if current == level:
        said = "Sa proximité est déjà automatique." if not level else \
            f"Sa proximité est déjà déclarée : {CLOSENESS_FR[level]}."
        raise Refused(said, {"closeness": said})
    now = frame.get(c.CLOSENESS(person))
    if level and _RANK[level] > _RANK[now] and level in OPENS and not args.confirmed:
        name = frame.get(identity_c.IDENTITY(person)).name or person
        outcome = f"« {name} » passera de « {CLOSENESS_FR[now]} » à « {CLOSENESS_FR[level]} » : {OPENS[level]}."
        raise Refused(f"À confirmer : {outcome}", {"confirmed": f"{outcome} Coche « Je confirme »."})
    draft = c.CLOSENESS_SET.draft(person=person, closeness=level, by=ctx.by)
    message = ("Proximité rendue à leur histoire." if not level
               else f"Proximité déclarée : {CLOSENESS_FR[level]}.")
    return Done(drafts=(draft,), message=message, guard=_seen(person, now))
