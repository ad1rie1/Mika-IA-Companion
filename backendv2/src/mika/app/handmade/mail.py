"""Le courrier, dessiné (ADR 0121) : Réception et Envoyés en boîte aux lettres — une liste succincte, une ligne par
message (un point s'il n'est pas lu, qui l'écrit ou à qui, son objet et son début, sa date), et sous elle une
liseuse : le message choisi (``?lire=<clé>``), ses actions (répondre, transférer, ranger…), son texte, ses pièces.

Les données restent celles du plugin du courrier : sa vue de la boîte (son espace de travail, ses comptes et ses
dossiers, ses filtres, sa pagination) et l'onglet « Message » de la fiche d'un mail, que la liseuse ouvre dans la
page ; leurs formulaires sont ceux que la console prépare, avec leur jeton (pour la liseuse : au nom du message).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlsplit

from markupsafe import Markup

from mika.app.handmade import blocks as drawn_blocks
from mika.app.handmade import excerpt
from mika.inspector import render
from mika.inspector.ui import PREFIX, UI, Forms, env
from mika.kernel.inspect import Head

#: la fiche d'un mail : ce que la liseuse ouvre
FICHE = f"{PREFIX}/fiche/mail/"
#: l'onglet de la fiche que la liseuse montre (son propriétaire, son nom)
MESSAGE = ("email", "message")
#: le paramètre du message ouvert
READ = "lire"
#: ce que dit déjà la ligne (lu ; non lu : son point, son gras) : ces étiquettes se taisent
ORDINARY = frozenset({"lu", "non lu"})
#: qui : l'expéditeur d'un message reçu, le destinataire d'un message envoyé
WHO = ("Expéditeur", "À")


def _key(href: str) -> str:
    """La clé d'un mail, lue au lien de sa fiche."""
    path = urlsplit(href).path
    return unquote(path[len(FICHE):]) if path.startswith(FICHE) else ""


def _here(query: Mapping[str, str], **change: str) -> str:
    """Cette page (ses filtres, sa page, son compte) avec un autre message ouvert, ou aucun."""
    kept = {k: v for k, v in query.items() if k not in (READ, "flash")}
    kept.update({k: v for k, v in change.items() if v})
    return "?" + urlencode(kept) if kept else "?"


def lines(table: Mapping[str, Any], query: Mapping[str, str]) -> list[dict[str, Any]]:
    """Une ligne par message : son objet et son début, qui, sa date, son état ; le lien qui l'ouvre ici."""
    out = []
    opened = query.get(READ, "")
    for row in table["rows"]:
        heading = row.get("heading") or {}
        fields = {f["label"]: f["value"] for f in row.get("fields", [])}
        who = next((fields[w] for w in WHO if w in fields), None)
        when = next((v for v in fields.values() if v.get("t") == "when"), None)
        key = _key(row.get("href", ""))
        out.append({
            "subject": heading.get("text") or "(sans objet)", "snippet": excerpt(heading.get("secondary") or "", 160),
            "unread": bool(heading.get("emphasis")), "who": (who or {}).get("text", ""),
            "where": (who or {}).get("secondary", ""), "when": when,
            "tags": [b for b in row.get("badges", []) if (b.get("text") or "").casefold() not in ORDINARY],
            "href": _here(query, **{READ: key}) if key else row.get("href", ""),
            "on": bool(key) and key == opened,
        })
    return out


def reader(ui: UI, key: str, query: Mapping[str, str], forms: Forms) -> Markup:
    """Le message ouvert : l'en-tête de sa fiche, puis son onglet « Message », ses formulaires à son nom."""
    spec = ui.inspection.find(*MESSAGE)
    head = ui.inspection.head("mail", key, ui.when_long)
    if spec is None or not isinstance(head, Head):
        return Markup(env.get_template("handmade/mail/reader.html").render(
            missing=True, close=_here(query), blocks=[], forms={}))
    got = ui.inspection.run(spec, query, ui.when_long, subject=key)
    rendered = render.blocks(got, ui.env(), query, namespace=READ)  # ses listes à part de celles de la boîte
    return Markup(env.get_template("handmade/mail/reader.html").render(
        head={"title": head.title, "subtitle": head.subtitle, "badges": [render.cell(b, ui.env()) for b in head.badges],
              "facts": [{"label": k, "value": render.cell(v, ui.env())} for k, v in head.facts]},
        blocks=[drawn_blocks.shape(d) for d in rendered], forms=forms.of(rendered, key) if isinstance(forms, Forms) else {},
        fiche=FICHE + quote(key, safe=""), close=_here(query)))


def box(ui: UI, blocks: Sequence[Any], query: Mapping[str, str], forms: Mapping[str, Any]) -> Markup | None:
    """Courrier › Réception, Envoyés : l'espace de travail du plugin, sa liste en lignes, la liseuse dessous."""
    rendered = render.blocks(blocks, ui.env(), query)
    space = next((d for d in rendered if d["t"] == "workspace"), None)
    table = next((d for d in space["items"] if d["t"] == "table"), None) if space else None
    if space is None or table is None:  # pas de boîte, un compte inconnu : bloc par bloc
        return drawn_blocks.page(ui, blocks, query, forms=forms)
    key = query.get(READ, "")
    return Markup(env.get_template("handmade/mail/box.html").render(
        side=space["sidebar"], before=[d for d in space["items"] if d is not table], table=table,
        lines=lines(table, query), reader=reader(ui, key, query, forms) if key else "", forms=forms))
