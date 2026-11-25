"""Ce que plusieurs rubriques de réglages partagent — celles du cadre et celles des domaines (ADR 0310)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from mika.contracts import identity as identity_c
from mika.contracts import self_ as self_c
from mika.runtime.params import Parameters
from mika.vocab.access import PERSON, SELF

if TYPE_CHECKING:
    from collections.abc import Callable

    from mika.app.server import Live
    from mika.kernel.frame import Frame


def parameters(live: Live) -> Parameters:
    return Parameters(live.kernel, temperament=lambda: live.persona().temperament, overrides=live.settings.overrides,
                      save_overrides=live.settings.save_overrides, inputs=live.inputs, apply=live.reconfigure)


def tolerant(cls: type[BaseModel], /, **data: Any) -> Any:
    """Une valeur enregistrée avant qu'une règle existe (un hôte « https://github.com/ ») s'affiche
    quand même, telle quelle : la page reste ouverte pour la corriger ; l'enregistrer la revalide."""
    try:
        return cls(**data)
    except ValidationError:
        return cls.model_construct(**data)


def owners(live: Live) -> list[tuple[str, str]]:
    """À qui une boîte ou un compte Teams peut être (ADR 0185, 0186) : toi (ses propriétaires), elle par son nom, ou
    une personne qui a un
    compte actif — jamais un opérateur, que « toi » désigne déjà (comme dans les tableaux de droits)."""
    frame = live.kernel.mind.frame()
    her = self_c.name_of(frame.get(self_c.PERSONA)) or "Elle"
    people: dict[str, str] = {}
    for a in live.accounts.all():
        if not a.active or getattr(a, "operator", False):
            continue
        person = str(frame.get(identity_c.PERSON(a.handle)) or a.handle)
        people.setdefault(PERSON + person, a.display_name or person)
    return [("", "Toi (ses propriétaires)"), (SELF, her),
            *sorted(people.items(), key=lambda kv: kv[1].casefold())]


def owner_words(live: Live, owner: str, name_of: Callable[[Frame, str], str]) -> str:
    """À qui est une boîte ou un compte Teams, sur sa carte : le nom que lui donne la liste des choix (le nom
    affiché de son compte), sinon celui que disent ses onglets (``owner_name`` du plugin : son prénom — un
    opérateur, un compte fermé ne sont pas dans la liste) ; sa clé seulement si rien ne la nomme, jamais
    « personne:<clé> » (audit du 2026-11-05, C4-03)."""
    return dict(owners(live)).get(owner) or name_of(live.kernel.mind.frame(), owner)
