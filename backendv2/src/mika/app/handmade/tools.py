"""Outils › Qui reçoit quoi, dessiné (ADR 0121) : ce qu'elle a sous la main selon à qui elle parle.

Une grille : ses lots d'outils en lignes (leur nom de famille, combien d'outils), les situations en colonnes,
rangées par ce qui se passe (elle répond à quelqu'un, elle prend la parole, personne n'écoute) ; chaque case dit
si le lot est en main, à la demande ou pas offert, et s'il ne l'est qu'en partie. Une case ouvre le catalogue sur
ce lot dans cette situation. Lu à la porte d'offre du pipeline, comme l'onglet de la console.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.inspector import render
from mika.inspector.pages import tools as catalog
from mika.inspector.ui import PREFIX, UI, env
from mika.kernel.inspect import Pager
from mika.vocab.episodes import Kind

#: les situations rangées par ce qui se passe, dans l'ordre de la grille
MOMENTS = ((Kind.REPLY, "Elle répond"), (Kind.INITIATIVE, "Elle prend la parole"))
#: les autres situations (un pas, un projet, une tâche) : personne n'écoute
UNHEARD = "Personne n'écoute"
#: le préfixe des lots des serveurs MCP branchés
MCP = "mcp."
#: ce que dit chaque état d'une case
STATES = {"hand": "en main", "ask": "à la demande", "none": "pas offert"}


def _label(ui: UI, bundle: str) -> str:
    """Le nom d'un lot : celui de sa famille ; un lot de serveur MCP (``mcp.<serveur>``, un par serveur branché)
    se nomme par son serveur."""
    label = ui.names.faculty(bundle)
    return f"Service MCP « {bundle.removeprefix(MCP)} »" if label == bundle and bundle.startswith(MCP) else label


def who_gets_what(ui: UI, blocks: Sequence[Any], query: Mapping[str, str]) -> Markup:
    """Outils › Qui reçoit quoi : une grille lots × situations."""
    registry, policies = ui.kernel.registry, ui.kernel.runner.policies
    situations = catalog.situations(ui)
    offers = {s.key: catalog.offered_in(ui, s) for s in situations}
    hands = {s.key: catalog.in_hand(ui, policies[s.kind]) for s in situations}
    order = {kind: i for i, (kind, _) in enumerate(MOMENTS)}
    situations.sort(key=lambda s: order.get(s.kind, len(MOMENTS)))
    groups: list[dict[str, Any]] = []
    starts = set()  # la première colonne de chaque groupe : un filet la sépare de la précédente
    for i, s in enumerate(situations):
        label = dict(MOMENTS).get(s.kind, UNHEARD)
        if not groups or groups[-1]["label"] != label:
            groups.append({"label": label, "count": 0})
            starts.add(i)
        groups[-1]["count"] += 1
    by_bundle: dict[str, list[Any]] = {}
    for spec in registry.tools.values():
        by_bundle.setdefault(spec.bundle, []).append(spec)
    rows = []
    for bundle, specs in by_bundle.items():
        cells = []
        for s in situations:
            got = [x for x in specs if x.name in offers[s.key]]
            core = hands[s.key]
            state = "none" if not got else \
                "hand" if core is None or bundle in core or any(x.in_hand for x in got) else "ask"
            cells.append({
                "state": state, "said": STATES[state], "count": len(got), "total": len(specs),
                "partial": bool(got) and len(got) < len(specs), "situation": s.label,
                "names": ", ".join(sorted(x.name for x in got)) or "aucun de ses outils",
                "href": f"{PREFIX}/outils/tous?" + urlencode({"lot": bundle, "pour": s.key}),
            })
        rows.append({"label": _label(ui, bundle), "bundle": bundle, "total": len(specs),
                     "phrase": registry.bundles.get(bundle, ""), "cells": cells,
                     "href": f"{PREFIX}/outils/tous?" + urlencode({"lot": bundle})})
    rows.sort(key=lambda r: r["label"].casefold())
    everything = [s.label for s in situations if hands[s.key] is None]
    pager = render._pager(Pager(size=max(1, len(rows)), total=len(rows)), query)
    return Markup(env.get_template("handmade/outils/qui.html").render(
        groups=groups, situations=situations, starts=starts, rows=rows, everything=everything, pager=pager))
