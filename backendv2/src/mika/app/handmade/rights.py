"""Réglages › Droits, dessiné (ADR 0121, 0133) : qui peut quoi, par personne et par ressource.

- *Par personne* : une audience type à la fois — toi quand elle te répond ou quand elle te parle d'elle-même, une
  personne qui a un compte (par son nom), les autres comptes, quand elle travaille seule — et ce que chaque type de
  règles lui accorde, avec la ligne qui en décide (``inspector.pages.rights.grants``) ;
- *Par ressource* : chaque tableau, ce qu'aucune ligne n'ouvre et où il se règle (``rights.tables``) ;
- les règles d'outils par situation (ADR 0122), qui ne font que restreindre, et ce que le code fixe.

Tout se lit des déclarations des propriétaires, du moteur qu'ils appliquent : jamais une recopie.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from markupsafe import Markup

from mika.app.handmade.access import people_with_accounts
from mika.inspector import render
from mika.inspector.pages import rights
from mika.inspector.pages import tools as catalog
from mika.inspector.ui import UI, env
from mika.kernel.frame import Audience
from mika.kernel.inspect import Pager
from mika.runtime.tools import ASK, HAND, OFF
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust

#: ce qu'une règle d'outil fait, en mots (ADR 0122)
RULE_WORDS = {OFF: "retiré", HAND: "en main", ASK: "à chercher"}
#: ce que le code fixe et qui n'est pas un outil (les outils, eux, se lisent : ``fixed_tools``)
FIXED = (
    "Ce que le téléphone envoie : toujours ton geste.",
    "À qui elle rend compte (un courrier qui arrive, un réveil, un projet) : toi, selon la confidentialité.",
    "Un réveil par API agit avec tes droits, dans les seuls outils qu'il déclare ; prêter à un agent, avec les tiens "
    "et tes règles d'outils.",
    "Une carte d'accord : la personne à qui elle est adressée la tranche dans son chat ; un opérateur, toutes, dans "
    "la console (« À valider »).",
)


def fixed_tools(ui: UI) -> dict[str, Any]:
    """Ce que le code fixe, lu des outils mêmes, jamais une recopie : ceux qu'il réserve à sa propriétaire
    (``owner_only`` — toi en privé, ou elle qui travaille pour toi, ``vocab.access.owner_here``), par famille ; ceux
    qu'une condition garde (``when``), avec sa phrase."""
    reserved: dict[str, list[str]] = {}
    guarded: list[tuple[str, str]] = []
    for spec in sorted(ui.kernel.registry.tools.values(), key=lambda t: t.name):
        if spec.owner_only:
            reserved.setdefault(ui.names.bundle(spec.bundle), []).append(spec.name)
        elif spec.when is not None:
            guarded.append((spec.name, catalog.condition(spec)))
    return {"reserved": sorted(reserved.items()), "guarded": guarded}


@dataclass(frozen=True, slots=True)
class Face:
    """Une audience type : qui est en face, et à quel moment."""

    key: str
    label: str
    audience: Audience
    kind: str


def _facing(key: str, person: str = "", *, owner: bool = False) -> Audience:
    return Audience(persons=(f"droits:{key}",), channel="web", public=False, trust=ChannelTrust.AUTHENTICATED.value,
                    owner=owner, person=person)


#: elle travaille seule : personne n'écoute (l'audience d'un pas, d'une exécution, d'une tâche)
WORKING = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)


def faces(ui: UI) -> list[Face]:
    """Les audiences types : toi (quand elle te répond, quand elle te parle d'elle-même), chaque personne qui a un
    compte (son lien tel qu'il est), un autre compte, une inconnue, un salon, et quand elle travaille seule."""
    out = [Face("toi", "Toi, quand elle te répond", _facing("toi", owner=True), Kind.REPLY),
           Face("toi-parle", "Toi, quand elle te parle d'elle-même", _facing("toi", owner=True), Kind.INITIATIVE)]
    out += [Face(f"p:{x['key']}", x["name"], _facing(x["key"], x["key"]), Kind.REPLY) for x in people_with_accounts(ui)]
    out.append(Face("comptes", "Un autre compte, quand elle lui répond", _facing("compte"), Kind.REPLY))
    out.append(Face("inconnue", "Une inconnue (un moyen de communication sans compte)",
                    Audience(persons=("droits:inconnue",), channel="external", public=False,
                             trust=ChannelTrust.ACCOUNT.value), Kind.REPLY))
    out.append(Face("salon", "Un salon, devant plusieurs personnes",
                    Audience(persons=("droits:salon",), channel="web", room="salon", public=True,
                             trust=ChannelTrust.PUBLIC.value), Kind.REPLY))
    out.append(Face("travail", "Elle, quand elle travaille seule", WORKING, Kind.WORK))
    return out


def _href(ref: Any) -> str:
    return render.href(ref) if ref is not None else ""


def _one_page(rows: int) -> Any:
    """La pagination d'un tableau qui tient en une page, dite comme partout."""
    return render._pager(Pager(size=max(1, rows), total=max(1, rows)), {})


def page(ui: UI, items: Sequence[Any], query: Mapping[str, str]) -> Markup:
    """La page : par personne (l'audience choisie, ``?qui=``), par ressource, les règles d'outils, ce que le code
    fixe."""
    all_faces = faces(ui)
    chosen = next((f for f in all_faces if f.key == query.get("qui", "")), all_faces[0])
    groups = []
    for spec, found in rights.grants(ui, chosen.audience, chosen.kind):
        opened = [g for g in found if not g.closed]
        groups.append({"title": spec.title, "description": spec.description,
                       "grants": [{"title": g.title, "what": g.what, "why": g.why, "href": _href(g.href)}
                                  for g in opened],
                       "closed": len(found) - len(opened), "pager": _one_page(len(opened))})
    tables = [{"title": spec.title, "description": spec.description,
               "tables": [{"title": t.title, "columns": t.columns,
                           "rows": [(str(i), *r) for i, r in enumerate(t.rows, start=1)], "default": t.default,
                           "floors": t.floors, "note": t.note, "href": _href(t.href),
                           "pager": _one_page(len(t.rows) + 1)} for t in found]}
              for spec, found in rights.tables(ui) if found]
    ruled = []
    for s in catalog.situations(ui):
        got = catalog.rules(ui, s)
        if got:
            ruled.append({"label": s.label, "rules": sorted((tool, RULE_WORDS.get(rule, rule))
                                                            for tool, rule in got.items())})
    return Markup(env.get_template("handmade/droits/page.html").render(
        faces=[{"key": f.key, "label": f.label, "on": f is chosen} for f in all_faces], chosen=chosen.label,
        groups=groups, tables=tables, ruled=ruled, fixed=FIXED, tools=fixed_tools(ui),
        catalogue=f"{catalog.BASE}/tous"))
