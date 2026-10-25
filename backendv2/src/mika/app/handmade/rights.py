"""Réglages › Droits, dessiné (ADR 0121, 0133) : qui peut quoi, par personne et par ressource.

- *Par personne* : une grille — en colonnes, les audiences types (toi quand elle te répond ou quand elle prend la
  parole, chaque personne qui a un compte, un autre compte, une inconnue, un salon, elle quand elle travaille seule) ;
  en lignes, chaque ressource et chacune de ses actions ; dans chaque case, ce qu'elle en fait et la ligne qui en
  décide (``inspector.pages.rights.grants``). Des outils d'une même ressource qui reçoivent partout la même réponse
  tiennent sur une ligne ; ``?qui=`` souligne une colonne ;
- *Par ressource* : chaque tableau tel qu'il est écrit, replié, ce qu'aucune ligne n'ouvre et où il se règle
  (``rights.tables``) ;
- les règles d'outils par situation (ADR 0122), qui ne font que restreindre, et ce que le code fixe.

Tout se lit des déclarations des propriétaires, du moteur qu'ils appliquent : jamais une recopie.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from markupsafe import Markup

from mika.app.handmade.access import people_with_accounts
from mika.contracts import projects as projects_c
from mika.faculties.projects.access import STEER_WORDS
from mika.inspector import render
from mika.inspector.pages import rights
from mika.inspector.pages import tools as catalog
from mika.inspector.ui import UI, env
from mika.kernel.frame import Audience
from mika.kernel.inspect import Pager
from mika.kernel.rights import Grant
from mika.runtime.tools import ASK, HAND
from mika.vocab.access import ALONE, CARD, MOMENTS, NO, OWNER_OK, POLICY_WORDS
from mika.vocab.episodes import Kind
from mika.vocab.privacy import ChannelTrust

#: ce qu'une règle d'outil fait, en mots (ADR 0122)
RULE_WORDS = {HAND: "en main", ASK: "à chercher"}
#: le ton d'une réponse dans la grille : elle le fait (on), en partie (part), en demandant (ask), jamais (off) ; une
#: autre (ce qu'elle en garde) reste neutre. « oui » et « — » : le voir d'un projet, ce que garde un outil fermé.
TONES = {POLICY_WORDS[ALONE]: "on", POLICY_WORDS[CARD]: "ask", POLICY_WORDS[OWNER_OK]: "ask", POLICY_WORDS[NO]: "off",
         STEER_WORDS[projects_c.STEER_EDIT]: "on", STEER_WORDS[projects_c.STEER_READ]: "part",
         STEER_WORDS[projects_c.STEER_ASK]: "ask", STEER_WORDS[projects_c.STEER_NO]: "off", "oui": "on", "—": "off"}
#: la légende de la grille, dans l'ordre des tons
LEGEND = (("on", "elle le fait"), ("part", "en partie"), ("ask", "en demandant"), ("off", "jamais"))
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
    """Ce que le code déclare, lu des outils mêmes, jamais une recopie : ceux dont le minimum vital est à toi et elle
    seule (``owner_only`` — une ligne de leur famille peut l'ouvrir, ADR 0134), par famille ; ceux qu'une condition
    garde (``when``), regroupés par sa phrase."""
    reserved: dict[str, list[str]] = {}
    guarded: dict[str, list[str]] = {}
    for spec in sorted(ui.kernel.registry.tools.values(), key=lambda t: t.name):
        if spec.owner_only:
            reserved.setdefault(ui.names.bundle(spec.bundle), []).append(spec.name)
        elif spec.when is not None:
            guarded.setdefault(catalog.condition(spec), []).append(spec.name)
    return {"reserved": sorted(reserved.items()), "guarded": sorted(guarded.items(), key=lambda x: -len(x[1])),
            "count": sum(len(n) for n in reserved.values()), "guarded_count": sum(len(n) for n in guarded.values())}


@dataclass(frozen=True, slots=True)
class Face:
    """Une audience type : qui est en face, et à quel moment ; ``short`` et ``hint`` : son en-tête de colonne."""

    key: str
    label: str
    audience: Audience
    kind: str
    short: str
    hint: str


def _facing(key: str, person: str = "", *, owner: bool = False, channel: str = "web") -> Audience:
    return Audience(persons=(f"droits:{key}",), channel=channel, public=False, trust=ChannelTrust.AUTHENTICATED.value,
                    owner=owner, person=person)


#: elle travaille seule : personne n'écoute (l'audience d'un pas, d'une exécution, d'une tâche)
WORKING = Audience(persons=(), channel="internal", public=False, trust=ChannelTrust.INTERNAL.value, owner=True)


def faces(ui: UI) -> list[Face]:
    """Les audiences types : toi (quand elle te répond, quand elle prend la parole), chaque personne qui a un compte
    (son lien tel qu'il est), un autre compte, une inconnue, un salon, et quand elle travaille seule."""
    replying, speaking = dict(MOMENTS)["conversation"], dict(MOMENTS)["initiative"]
    out = [Face("toi", "Toi, par le chat web, quand elle te répond", _facing("toi", owner=True), Kind.REPLY, "Toi",
                "chat web · " + replying),
           Face("toi-mobile", "Toi, par l'app Android, quand elle te répond",
                _facing("toi", owner=True, channel="mobile"), Kind.REPLY, "Toi", "app Android · " + replying),
           Face("toi-parle", "Toi, quand elle te parle d'elle-même", _facing("toi", owner=True), Kind.INITIATIVE,
                "Toi", speaking)]
    out += [Face(f"p:{x['key']}", x["name"], _facing(x["key"], x["key"]), Kind.REPLY, x["name"], replying)
            for x in people_with_accounts(ui)]
    out.append(Face("comptes", "Un autre compte, quand elle lui répond", _facing("compte"), Kind.REPLY,
                    "Un autre compte", replying))
    out.append(Face("inconnue", "Une inconnue, par Internet (un moyen de communication que rien ne prouve)",
                    Audience(persons=("droits:inconnue",), channel="external", public=False,
                             trust=ChannelTrust.ACCOUNT.value), Kind.REPLY, "Une inconnue", "Internet · non reconnue"))
    out.append(Face("salon", "Un salon, devant plusieurs personnes",
                    Audience(persons=("droits:salon",), channel="web", room="salon", public=True,
                             trust=ChannelTrust.PUBLIC.value), Kind.REPLY, "Un salon", "plusieurs personnes"))
    out.append(Face("travail", "Elle, quand elle travaille seule", WORKING, Kind.WORK, "Elle seule",
                    "quand elle travaille"))
    return out


def _href(ref: Any) -> str:
    return render.href(ref) if ref is not None else ""


def _one_page(rows: int) -> Any:
    """La pagination d'un tableau qui tient en une page, dite comme partout."""
    return render._pager(Pager(size=max(1, rows), total=max(1, rows)), {})


def _named(titles: Sequence[str]) -> tuple[str, list[str]]:
    """Un libellé et les noms qu'il regroupe : « « web » · read » et « « web » · search » font « « web » » et
    ``[read, search]`` ; un titre seul reste entier."""
    heads = {t.rpartition(" · ")[0] for t in titles}
    if len(heads) == 1 and "" not in heads:
        return heads.pop(), [t.rpartition(" · ")[2] for t in titles]
    return ("", list(titles)) if len(titles) > 1 else (titles[0], [])


def _cell(face: Face, g: Grant | None, action: str) -> dict[str, str]:
    """Une case : ce qu'elle fait de cette action devant cette audience, son ton, et la phrase entière au survol."""
    if g is None:
        return {"word": "—", "tone": "none", "title": f"{face.label} — rien ici"}
    word = dict(g.what).get(action, "—")
    return {"word": word, "tone": TONES.get(word, "plain"), "title": f"{face.label} — {action} : {word} ({g.why})"}


def grid(ui: UI, all_faces: Sequence[Face]) -> list[dict[str, Any]]:
    """La grille, par type de règles : chaque ressource, ses actions, une case par audience, et la ligne qui en décide.
    Les ressources dans l'ordre où elles apparaissent ; des outils voisins d'une même ressource qui ont partout la même
    réponse et la même ligne n'en font qu'une."""
    answered = [rights.grants(ui, f.audience, f.kind) for f in all_faces]
    per_face = [{spec.key: found for spec, found in got} for got in answered]
    out = []
    for spec, _found in answered[0] if answered else ():
        keys: dict[tuple[str, str], Any] = {}
        for got in per_face:
            for g in got.get(spec.key, ()):
                keys.setdefault((g.resource, g.title), g.href)
        rows: list[dict[str, Any]] = []
        for (resource, title), href in keys.items():
            cells = [next((g for g in got.get(spec.key, ()) if (g.resource, g.title) == (resource, title)), None)
                     for got in per_face]
            actions = list(dict.fromkeys(k for g in cells if g is not None for k, _ in g.what))
            same = (resource, _href(href), tuple(actions),
                    tuple(None if g is None else (g.what, g.why) for g in cells))
            if rows and rows[-1]["same"] == same:
                rows[-1]["titles"].append(title)
                continue
            rows.append({"same": same, "titles": [title], "href": _href(href), "actions": actions, "cells": cells})
        shown = []
        for r in rows:
            label, names = _named(r["titles"])
            shown.append({
                "label": label, "names": names, "href": r["href"],
                "closed": all(g is None or g.closed for g in r["cells"]),
                "actions": [{"name": a, "cells": [_cell(f, g, a) for f, g in zip(all_faces, r["cells"], strict=True)]}
                            for a in r["actions"]],
                "why": [g.why if g is not None else "" for g in r["cells"]]})
        if shown:
            out.append({"title": spec.title, "description": spec.description, "rows": shown})
    return out


def page(ui: UI, items: Sequence[Any], query: Mapping[str, str]) -> Markup:
    """La page : par personne (la grille, ``?qui=`` souligne une colonne), par ressource (repliée), les règles
    d'outils, ce que le code fixe."""
    all_faces = faces(ui)
    chosen = next((f for f in all_faces if f.key == query.get("qui", "")), None)
    tables = [{"title": spec.title, "description": spec.description,
               "tables": [{"title": t.title, "columns": t.columns,
                           "rows": [(str(i), *r) for i, r in enumerate(t.rows, start=1)], "default": t.default,
                           "floors": t.floors, "note": t.note, "href": _href(t.href),
                           "pager": _one_page(len(t.rows) + 1)} for t in found]}
              for spec, found in rights.tables(ui) if found]
    ruled: list[dict[str, Any]] = []
    kinds = grid(ui, all_faces)
    return Markup(env.get_template("handmade/droits/page.html").render(
        faces=[{"key": f.key, "label": f.label, "short": f.short, "hint": f.hint, "on": f is chosen}
               for f in all_faces],
        grid=kinds, pager=_one_page(sum(len(k["rows"]) for k in kinds)), legend=LEGEND, tables=tables, ruled=ruled,
        fixed=FIXED, tools=fixed_tools(ui), catalogue=f"{catalog.BASE}/tous"))
