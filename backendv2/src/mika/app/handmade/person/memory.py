"""L'onglet Mémoire de la fiche d'une personne, dessiné (ADR 0121) : ce qu'elle garde d'elle, en quatre cartes — les
moments de sa vie, ses promesses, ses croyances, ses souvenirs —, chaque élément avec son texte, ce qu'il est, d'où
il vient et son détail.

Les données restent celles de la faculté de la mémoire (son onglet ``memoire`` : ses listes paginées, sa recherche)
— cette page n'en change que la forme ; une forme qu'elle ne reconnaît pas rend la main aux blocs de la faculté.
L'origine d'une croyance est une étiquette dans la vue, pour sa clé (``told``…), que lit l'onglet Mémoire de la
console : ici, elle reste un fait en mots, comme ses voisins (``PLAIN``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade.lists import counts, listing
from mika.inspector import render
from mika.inspector.ui import UI, env
from mika.kernel.inspect import Table

#: chaque liste de la mémoire, reconnue à son titre : (un mot de son titre, sa place, son titre ici, sa sorte)
KINDS = (("vie des autres", 0, "Les moments de sa vie", "moments"), ("promesse", 1, "Ses promesses", "promesses"),
         ("croyance", 2, "Ce qu'elle croit", "croyances"), ("souvenir", 3, "Ses souvenirs", "souvenirs"))
#: des faits qu'une étiquette porte dans la vue pour sa clé seule (l'origine d'une croyance) : ils se disent ici en mots
PLAIN = frozenset({"origine"})


def memory(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str],
           forms: Mapping[str, Any] | None = None) -> Markup | None:
    tables = [b for b in blocks if isinstance(b, Table)]
    if not tables:
        return None
    shown, counter = ui.env(), [0]
    name = ui.names.name_of(key)
    sections = []
    for table in tables:
        known = next((k for k in KINDS if k[0] in table.title.lower()), None)
        if known is None:
            return None  # une liste qu'elle ne connaît pas : les blocs de la faculté
        _word, order, title, kind = known
        section = listing(table, shown, query, name, counter=counter)
        for row in section["rows"]:
            row["fields"] = [_plain(f, shown) for f in row.get("fields", [])]
        sections.append({**section, "order": order, "title": title, "kind": kind})
    sections.sort(key=lambda s: s["order"])
    return Markup(env.get_template("handmade/person/tabs/memoire.html").render(
        counts=counts(blocks), sections=sections, searched=bool(query.get("q"))))


def _plain(fact: dict[str, Any], shown: render.Env) -> dict[str, Any]:
    """Un fait de ``PLAIN`` rendu en étiquette : la même cellule que son texte seul aurait donnée."""
    value = fact["value"]
    if fact["label"] not in PLAIN or value.get("t") != "badge":
        return fact
    return {**fact, "value": render.cell(value["text"], shown)}
