"""Réglages › Droits (ADR 0133) : qui peut quoi, lu des types de règles que chaque propriétaire déclare
(``Faculty.rights``) — jamais une recopie.

- ``tables`` : chaque tableau de règles, par ressource (un service, un projet, ce qu'elle envoie), en mots ;
- ``grants`` : ce qu'une audience aurait à un moment, et la ligne qui en décide.

La page dessinée (``app/handmade/rights.py``) les montre par personne et par ressource ; l'onglet lui-même rend les
tableaux en blocs, son repli.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request

from mika.inspector.pages.tabs import TABS
from mika.kernel.inspect import Block, Note, Table
from mika.kernel.rights import Grant, RightsSpec, RuleTable
from mika.runtime.boundary import Failed, call


def _ran(ui: Any, spec: RightsSpec, fn: Any, *args: Any) -> list[Any]:
    """Ce qu'un type de règles rend (une panne tait ce type, jamais la page : elle est au journal)."""
    frame = ui.kernel.mind.frame()
    ctx = ui.inspection.context(when=ui.when)
    got = call(fn, frame.state(spec.owner), frame, ctx, *args, label=f"droits {spec.key}")
    return [] if isinstance(got, Failed) or got is None else list(got)


def tables(ui: Any) -> list[tuple[RightsSpec, list[RuleTable]]]:
    """Chaque type de règles et ses tableaux, dans l'ordre où ils se déclarent."""
    return [(spec, _ran(ui, spec, spec.tables)) for spec in ui.kernel.registry.rights]


def grants(ui: Any, audience: Any, kind: str) -> list[tuple[RightsSpec, list[Grant]]]:
    """Ce que chaque type de règles accorde à cette audience, à ce moment ; un type qui ne dépend pas de qui est en
    face (le destinataire d'un envoi) ne dit rien ici."""
    return [(spec, _ran(ui, spec, spec.grants, audience, kind)) for spec in ui.kernel.registry.rights
            if spec.grants is not None]


@TABS.tab("reglages.droits", title="Droits", group="Droits", order=2500,
          description="Qui peut quoi : les services, les projets et leurs apps, ce qu'elle envoie à ta place — par "
                      "personne et par ressource, avec la ligne qui en décide.")
async def rights_page(ui: Any, request: Request) -> Any:
    blocks: list[Block] = []
    for _spec, found in tables(ui):
        for t in found:
            rows = tuple((str(i), *r) for i, r in enumerate(t.rows, start=1)) + (("", *t.default),)
            blocks.append(Table(("#", *t.columns), rows, title=t.title,
                                caption=" · ".join(("ce qu'aucune ligne n'ouvre : " + " ; ".join(t.floors),)
                                                   if t.floors else ()) + (f" {t.note}" if t.note else "")))
    return {"blocks": blocks or [Note("Aucune règle déclarée.", tone="muted")]}
