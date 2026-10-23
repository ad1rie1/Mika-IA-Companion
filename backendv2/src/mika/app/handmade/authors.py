"""Réglages › Autrices, dessiné (ADR 0121, 0124) : la carte de chaque autrice, et en tête où chacune écrit.

Le tableau du haut dit, flux par flux (le chat, chaque boîte mail, Teams, le téléphone), qui y écrit, ce qu'elle
récrit et ce qui l'en empêcherait (aucun modèle au rôle « rendre naturel », Teams désactivé). Les autrices et le flux
de chacune se règlent dessous (``app/authors.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from markupsafe import Markup

from mika.app.authors import Authors, AuthorSpec
from mika.app.handmade import excerpt
from mika.inspector.ui import PREFIX, env
from mika.vocab import flows

#: la page
PAGE = f"{PREFIX}/reglages/autrices"
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
    if spec.example.strip():
        facts.append(("Exemple", f"{len(spec.example.strip())} caractères"))
    return {"title": spec.name.strip() or key, "tags": [("écrit", "ok")] if where else [("sans flux", "muted")],
            "lead": excerpt(spec.codes, 160) if spec.codes.strip() else "Pas de codes : le cadre de son flux seul.",
            "lead_label": "Ses codes", "lead_plain": True, "facts": facts}


def head(cfg: Authors, flow_rows: Sequence[tuple[str, str]], *, served: str, teams_on: bool) -> Markup:
    """Le haut de la page : où chacune écrit, flux par flux, et ce qui empêcherait qu'elle écrive."""
    rows = []
    for flow, label in flow_rows:
        author = cfg.author_for(flow)
        form = flows.form_of(flow)
        # sans modèle, le bandeau du haut le dit pour tous les flux
        note = "Teams est désactivé : rien n'y part" if author is not None and form == flows.TEAMS and not teams_on \
            else ""
        rows.append({"label": label, "what": WHAT.get(form, ""), "author": author,
                     "href": f"{PAGE}?enregistrement=authors&cle={author.key}" if author else "", "note": note})
    return Markup(env.get_template("handmade/reglages/autrices.html").render(
        rows=rows, served=served, roles=f"{PREFIX}/reglages/roles", writing=sum(1 for r in rows if r["author"])))
