"""Le courrier, dessiné (ADR 0121) : chaque onglet dans le même espace (ses comptes et ses dossiers à côté, ses
actions et ses filtres au-dessus).

- **Réception, Envoyés** : une boîte aux lettres — une liste succincte, une ligne par message (une case pour la
  cocher, un point s'il n'est pas lu, qui l'écrit ou à qui, son objet et son début, sa date), la barre qui range ce
  qu'on a coché, et une liseuse, à côté de la liste sur un écran large, dessous sinon (ADR 0175) : le message choisi
  (``?lire=<clé>``), le précédent et le suivant, ce qu'elle en sait, ses actions (répondre, lui demander une
  réponse, ranger…), son texte, ses pièces.
- **Brouillons** : ce qui attend ton accord en enveloppes (à qui, depuis quelle boîte, en réponse à quoi, d'où il
  vient, ce qu'il faut vérifier), ce qui est décidé en lignes.
- **Contacts** : une ligne par adresse (combien de mails dans chaque sens, le dernier échange), ses échanges en un
  clic, « Écrire » à côté.

Les données restent celles du plugin du courrier : ses vues (leur espace de travail, leurs listes lues par le nom
de leurs colonnes, leur pagination) et l'onglet « Message » de la fiche d'un mail, que la liseuse ouvre dans la
page ; leurs formulaires sont ceux que la console prépare, avec leur jeton (pour la liseuse : au nom du message).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlsplit

from markupsafe import Markup

from mika.app.handmade import blocks as drawn_blocks
from mika.app.handmade import excerpt
from mika.app.handmade.fiche_parts import side_view
from mika.inspector import render
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import PREFIX, UI, Forms, env
from mika.kernel.inspect import Head
from mika.plugins.email import READ_AFTER_S, params_of
from mika.plugins.email.console.actions import GESTURES

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
#: l'action qui range ce qu'on a coché dans la liste
TIDY = "email.ranger"
#: ce que « Ce qu'elle en sait » dit en tête de la liseuse, d'après son onglet (ses libellés) ; les autres restent sur
#: la fiche. Un oui-non ne se dit que oui, en étiquette.
HER_TAGS = {"important": "important", "réponse attendue": "réponse attendue"}
HER_FACTS = {"ce que ça pourrait lui faire": "ce que ça lui fait", "brouillon de réponse": "sa réponse",
             "où il en est": "où elle en est"}


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
            "tags": [b for b in row.get("badges", []) if (b.get("text") or "").casefold() not in ORDINARY | {"—"}],
            "href": _here(query, **{READ: key}) if key else row.get("href", ""),
            "on": bool(key) and key == opened, "key": key,
        })
    return out


def _her(ui: UI, key: str) -> dict[str, Any] | None:
    """Ce qu'elle sait du message ouvert, en tête de la liseuse : ce qu'elle en a retenu, ce que son tri en dit (s'il
    est important, s'il attend une réponse, ce qu'il lui fait), sa réponse et où elle en est, une demande en cours ;
    lus à son onglet « Ce qu'elle en sait » (``None`` : elle n'en sait rien de plus que la boîte)."""
    said, facts, notes = "", [], []
    for d in side_view(ui, "email", "remarque", key, "liseuse"):
        if d["t"] == "prose" and d.get("title") == "Ce qu'elle en a retenu":
            said = excerpt(d.get("text") or "", 420)
        elif d["t"] == "fields":
            for pair in d.get("pairs", []):
                label, value = pair["label"], pair["value"]
                text = str(value.get("text") or "")
                if label in HER_TAGS and text == "oui":
                    facts.append((HER_TAGS[label], None))
                elif label in HER_FACTS and text not in ("", "—"):
                    facts.append((HER_FACTS[label], value))
        elif d["t"] == "note" and d.get("tone") in ("info", "warn"):
            notes.append(d["text"])
    if not (said or facts or notes):
        return None
    return {"said": said, "facts": facts, "notes": notes, "more": fiche_url("mail", key, "remarque")}


def _read_after(ui: UI) -> int | None:
    """Le réglage « ouvrir un mail le marque lu » (ADR 0175), en secondes ; ``None`` : jamais."""
    return READ_AFTER_S.get(params_of(ui.kernel.mind.frame()).read_on_open)


def _neighbours(ordered: Sequence[Mapping[str, Any]], key: str) -> tuple[str, str]:
    """Le message d'avant et celui d'après dans la page de la liste (leur lien), s'il y en a."""
    keys = [m for m in ordered if m.get("key")]
    at = next((i for i, m in enumerate(keys) if m["key"] == key), None)
    if at is None:
        return "", ""
    return (keys[at - 1]["href"] if at > 0 else ""), (keys[at + 1]["href"] if at + 1 < len(keys) else "")


def reader(ui: UI, key: str, query: Mapping[str, str], forms: Forms,
           ordered: Sequence[Mapping[str, Any]] = ()) -> Markup:
    """Le message ouvert : l'en-tête de sa fiche, le précédent et le suivant de la liste (``ordered``), ce qu'elle en
    sait, puis son onglet « Message », ses formulaires à son nom."""
    spec = ui.inspection.find(*MESSAGE)
    head = ui.inspection.head("mail", key, ui.when_long)
    if spec is None or not isinstance(head, Head):
        return Markup(env.get_template("handmade/mail/reader.html").render(
            missing=True, close=_here(query), blocks=[], forms={}, read_after=None))
    got = ui.inspection.run(spec, query, ui.when_long, subject=key)
    rendered = render.blocks(got, ui.env(), query, namespace=READ)  # ses listes à part de celles de la boîte
    prev, next_ = _neighbours(ordered, key)
    return Markup(env.get_template("handmade/mail/reader.html").render(
        head={"title": head.title, "subtitle": head.subtitle, "badges": [render.cell(b, ui.env()) for b in head.badges],
              "facts": [{"label": k, "value": render.cell(v, ui.env())} for k, v in head.facts]},
        blocks=[drawn_blocks.shape(d) for d in rendered], forms=forms.of(rendered, key) if isinstance(forms, Forms) else {},
        fiche=FICHE + quote(key, safe=""), close=_here(query), prev=prev, next=next_, her=_her(ui, key),
        read_after=_read_after(ui)))


def _space(ui: UI, blocks: Sequence[Any], query: Mapping[str, str]) -> tuple[dict[str, Any] | None, list[Any]]:
    """L'espace de travail d'un onglet du plugin, rendu comme la console le numérote, et ses listes."""
    rendered = render.blocks(blocks, ui.env(), query)
    space = next((d for d in rendered if d["t"] == "workspace"), None)
    return space, [d for d in space["items"] if d["t"] == "table"] if space else []


def _cells(table: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Les cellules d'une ligne par le nom de leur colonne (qu'elle soit en cartes ou en tableau)."""
    return {c["label"]: v for c, v in zip(table["columns"], row["cells"], strict=False)}


def _said(cell: Mapping[str, Any] | None) -> str:
    """Le texte d'une cellule ; « — » (rien) se tait."""
    text = str((cell or {}).get("text") or "")
    return "" if text == "—" else text


def box(ui: UI, blocks: Sequence[Any], query: Mapping[str, str], forms: Mapping[str, Any]) -> Markup | None:
    """Courrier › Réception, Envoyés : l'espace de travail du plugin, la barre qui range ce qu'on a coché, sa liste en
    lignes, ce qui suit la liste (remonter plus loin), la liseuse."""
    space, tables = _space(ui, blocks, query)
    if space is None or not tables:  # pas de boîte, un compte inconnu : bloc par bloc
        return drawn_blocks.page(ui, blocks, query, forms=forms)
    table, key = tables[0], query.get(READ, "")
    items = space["items"]
    tidy = next((d for d in items if d["t"] == "action" and d["key"] == TIDY), None)
    at = items.index(table)
    shown = lines(table, query)
    return Markup(env.get_template("handmade/mail/box.html").render(
        side=space["sidebar"], before=[d for d in items[:at] if d is not tidy], after=items[at + 1:], table=table,
        lines=shown, reader=reader(ui, key, query, forms, shown) if key else "", forms=forms,
        bulk=forms.get(tidy["slot"]) if tidy is not None else None, gestures=GESTURES))


def _draft(table: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    """Un brouillon de la liste : son objet, à qui, depuis quelle boîte, en réponse à quoi, d'où il vient, son état."""
    cells = _cells(table, row)
    answer = cells.get("En réponse à")
    box_, _, voice = _said(cells.get("Boîte")).partition(" · ")
    state, check = cells.get("État") or {}, cells.get("À vérifier") or {}
    return {"subject": _said(cells.get("Objet")) or "(sans objet)", "href": row.get("href", ""),
            "to": _said(cells.get("À")), "box": box_, "voice": voice,
            "answer": answer if answer is not None and _said(answer) else None,
            "origin": _said(cells.get("Origine")), "when": cells.get("Proposé"),
            "state": state if _said(state) else None, "check": check if _said(check) else None,
            "waiting": row.get("tone") == "warn"}


def drafts(ui: UI, blocks: Sequence[Any], query: Mapping[str, str], forms: Mapping[str, Any]) -> Markup | None:
    """Courrier › Brouillons : ce qui attend ton accord en enveloppes, ce qui est décidé en lignes."""
    space, tables = _space(ui, blocks, query)
    if space is None or not tables:  # pas de courrier branché : bloc par bloc
        return drawn_blocks.page(ui, blocks, query, forms=forms)
    lists = [{**t, "drafts": [_draft(t, r) for r in t["rows"]]} for t in tables]
    return Markup(env.get_template("handmade/mail/drafts.html").render(
        side=space["sidebar"], before=[d for d in space["items"] if d["t"] != "table"], waiting=lists[0],
        done=lists[1] if len(lists) > 1 else None, forms=forms))


def _contact(table: Mapping[str, Any], row: Mapping[str, Any], forms: Mapping[str, Any]) -> dict[str, Any]:
    """Un contact : son nom (sinon son adresse), son adresse, ses échanges dans chaque sens, le dernier ; « Écrire »."""
    cells = _cells(table, row)
    address, name = _said(cells.get("adresse")), _said(cells.get("nom"))
    write = next((forms.get(d["slot"]) for d in row.get("detail", []) if d["t"] == "action"), None)
    return {"name": name or address, "address": address if name else "", "initial": (name or address or "?")[:1].upper(),
            "received": _said(cells.get("reçus")) or "0", "sent": _said(cells.get("envoyés")) or "0",
            "last": cells.get("dernier échange") if _said(cells.get("dernier échange")) else None,
            "href": row.get("href", ""), "write": {**write, "title": "Écrire"} if write else None}


def contacts(ui: UI, blocks: Sequence[Any], query: Mapping[str, str], forms: Mapping[str, Any]) -> Markup | None:
    """Courrier › Contacts : une ligne par adresse, ses échanges en un clic, « Écrire » à côté."""
    space, tables = _space(ui, blocks, query)
    if space is None or not tables:
        return drawn_blocks.page(ui, blocks, query, forms=forms)
    table = tables[0]
    return Markup(env.get_template("handmade/mail/contacts.html").render(
        side=space["sidebar"], before=[d for d in space["items"] if d is not table], table=table,
        people=[_contact(table, r, forms) for r in table["rows"]], forms=forms,
        note=str(table.get("caption") or "").split(". ")[0].rstrip(".")))
