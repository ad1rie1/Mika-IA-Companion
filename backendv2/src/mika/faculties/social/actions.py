"""Ce qu'un opérateur peut faire des liens depuis la console : déclarer la
proximité d'une personne (genèse, correction), ou la rendre à ce que leur
histoire a installé.

L'action rend un brouillon de ``social.closeness_set`` qui nomme l'opérateur ;
le moteur le journalise comme venant de l'extérieur, avec son audit.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, field_validator

from mika.contracts import social as c
from mika.faculties.social.faculty import SOCIAL, SocialState
from mika.faculties.social.inspect import AUTO, CLOSENESS_FR, settable
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.operate import ActionContext, Done, Refused

CHOICES = ((AUTO, "automatique (née de leur histoire)"), *((k, CLOSENESS_FR[k]) for k in c.CLOSENESS_LEVELS))


class ClosenessArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    closeness: Annotated[str, Knob(
        label="Proximité", choices=CHOICES, advanced=False,
        help="Déclarée, elle l'emporte sur ce que leur histoire a installé ; « automatique » la lui rend.")] = AUTO

    @field_validator("closeness")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in {k for k, _label in CHOICES}:
            raise ValueError("proximité inconnue")
        return value


def _available(s: SocialState, frame: Frame, key: str) -> bool:
    return settable(frame, key)


@SOCIAL.action("proximite", title="Fixer la proximité", args=ClosenessArgs, emits=[c.CLOSENESS_SET],
               subject="person", available=_available, order=10,
               description="Inconnue, connaissance, amie ou proche : ce qu'elle peut lui confier en dépend.")
def _set_closeness(s: SocialState, frame: Frame, args: ClosenessArgs, ctx: ActionContext) -> Done:
    person = ctx.subject
    level = "" if args.closeness == AUTO else args.closeness
    current = s.declared.get(person, "")
    if current == level:
        said = "Sa proximité est déjà automatique." if not level else \
            f"Sa proximité est déjà déclarée : {CLOSENESS_FR[level]}."
        raise Refused(said, {"closeness": said})
    draft = c.CLOSENESS_SET.draft(person=person, closeness=level, by=ctx.by)
    message = ("Proximité rendue à leur histoire." if not level
               else f"Proximité déclarée : {CLOSENESS_FR[level]}.")
    return Done(drafts=(draft,), message=message)
