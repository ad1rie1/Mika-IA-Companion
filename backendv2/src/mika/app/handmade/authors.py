"""Réglages › Personnage › Autrices, dessiné (ADR 0121, 0124) : la carte de chaque autrice, et où chacune écrit.

« Où elles écrivent » est le formulaire même (``flow``, une ligne de la correspondance « flux → autrice ») : flux par
flux (le chat, chaque boîte mail, Teams, le téléphone), sa liste dans la colonne « Autrice », ce qu'elle y récrit et ce
qui l'en empêcherait (Teams désactivé). En tête, un seul bandeau quand aucun modèle ne sert le rôle « rendre naturel »
(``head``). Les autrices et leurs flux se règlent dans ``app/authors.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from markupsafe import Markup

from mika.app.authors import Authors, AuthorSpec
from mika.app.handmade import excerpt
from mika.inspector.ui import PREFIX, env
from mika.vocab import flows

#: la page
PAGE = f"{PREFIX}/reglages/autrices"
#: les premiers mots de son exemple, sur sa carte
EXAMPLE_CHARS = 90
#: ce que récrit l'autrice de chaque forme de flux, et quand
WHAT = {
    flows.CHAT: "ses réponses et ses initiatives, avant qu'elles partent (pas le mode pro)",
    flows.MAIL: "les brouillons de cette boîte, avant qu'on te les propose",
    flows.TEAMS: "les réponses qu'elle prépare à ta place, avant qu'elles partent ou soient posées dans Teams",
    flows.PHONE: "les réponses WhatsApp et SMS qu'elle prépare à ta place, avant que ton téléphone te les propose",
}


def describe(key: str, entry: Any, cfg: Authors, labels: Mapping[str, str]) -> dict[str, Any]:
    """La carte d'une autrice dans la liste : où elle écrit, ses codes en bref, son exemple."""
    spec = entry if isinstance(entry, AuthorSpec) else AuthorSpec.model_validate(entry or {})
    where = [labels.get(flow, flow) for flow, k in cfg.flows.items() if k == key]
    facts = [("Écrit dans", ", ".join(where) if where else "aucun flux : elle attend qu'on lui en donne un")]
    if spec.example.strip():  # ses premiers mots : sa longueur n'apprend rien d'elle
        facts.append(("Exemple", excerpt(spec.example, EXAMPLE_CHARS)))
    return {"title": spec.name.strip() or key, "tags": [("écrit", "ok")] if where else [("sans flux", "muted")],
            "lead": excerpt(spec.codes, 160) if spec.codes.strip() else "Pas de codes : le cadre de son flux seul.",
            "lead_label": "Ses codes", "lead_plain": True, "facts": facts}


def head(*, served: str) -> Markup:
    """Le haut de la page : le seul bandeau, quand aucun modèle ne sert le rôle « rendre naturel » (aucune n'écrit) ;
    rien sinon."""
    if served:
        return Markup("")
    return Markup(env.get_template("handmade/reglages/autrices.html").render(roles=f"{PREFIX}/reglages/roles"))


def flow(key: str, *, teams_on: bool) -> dict[str, Any]:
    """La ligne d'un flux dans « Où elles écrivent » (la correspondance flux → autrice, en table) : ce que son autrice y
    récrit, et ce qui l'en empêcherait. Sans modèle, le bandeau du haut le dit pour tous les flux."""
    form = flows.form_of(key)
    note = "Teams est désactivé : rien n'y part" if form == flows.TEAMS and not teams_on else ""
    return {"title": "Où elles écrivent", "key_head": "Flux", "choice_head": "Autrice",
            "cells": [{"head": "Ce qu'elle récrit", "text": WHAT.get(form, ""), "note": note}]}
