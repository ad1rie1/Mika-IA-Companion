"""Deux onglets de la fiche d'une personne qui lui parle, dessinés (ADR 0298) :

- **Ce qui l'identifie** (l'onglet ``adresses`` de la faculté ``identity``) : une tuile par moyen de communication
  qui lui parle (son identifiant de compte, un compte extérieur…), puis les identifiants des fiches de l'annuaire qui
  lui sont reliées — son identifiant Teams, ses e-mails, ses numéros —, chacun avec sa sorte, où elle l'a vu, et
  « son compte » quand un de ses comptes le désigne (réuni d'office) ; « Détacher » sur ceux de l'annuaire (le geste
  de la fiche du contact). Ses identifiants de l'annuaire restent les siens : jamais des moyens de communication.
- **Contacts** (l'onglet ``contacts`` du plugin) : ceux que ses comptes lui ont fait connaître, ceux qu'on lui
  partage et ceux que personne n'a (``Accounts.visible``, les partages compris), des puces par compte, une entrée
  chacun comme l'annuaire les dit. C'est la liste que montrera l'onglet Contacts de frontendv2.

Sa part de la fiche (``PERSON_PART``, ADR 0310) : ces deux onglets et leur compte — pour Ce qui l'identifie, les
identifiants des fiches reliées, que la fiche ajoute à ses moyens de communication —, et Contacts tu pour qui n'en a
pas (``hidden``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.app.domains.contacts.console.directory import (
    accounts,
    contact_entry,
    contact_url,
    place_name,
    port_of,
)
from mika.app.domains.contacts.console.subject import detach_forms, sheet_of, tiles_of
from mika.app.domains.domain import PersonPart
from mika.app.handmade import Look
from mika.app.handmade.person.common import Who
from mika.app.handmade.subjects.parts import safely
from mika.faculties.identity.inspect import TRUST_SHORT, handle_label, handles_of
from mika.inspector import render
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import UI, env
from mika.kernel.clock import DAY
from mika.kernel.inspect import Pager, plural
from mika.plugins.contacts.inspect import contact_key
from mika.ports.contacts import ORG, PHONE_SOURCE, TOLD, ContactSheet
from mika.vocab import privacy
from mika.vocab.words import elided

#: par où elle lui écrit, en mots
CHANNELS = {privacy.WEB: "le chat web", privacy.MOBILE: "l'application Android", privacy.EXTERNAL: "un canal extérieur"}
#: ses contacts : tant par page ; le compte choisi en puce
PAGE, ACCOUNT = 24, "compte"
#: ses propres comptes qui sont elle-même, sur sa fiche (son téléphone, ce qu'elle lui a raconté)
OWN_WORDS = {PHONE_SOURCE: "Téléphone", TOLD: "Racontés"}


def linked_sheets(look: Look, person: str) -> list[ContactSheet]:
    """Les fiches de l'annuaire reliées à cette personne."""
    port = port_of(look)
    ids = (safely(port.links, "fiches reliées", {}) or {}).get(person, ()) if port is not None else ()
    return [x for x in (sheet_of(look.ui, contact_key(cid)) for cid in ids) if x is not None]


def _own_tiles(look: Look, person: str) -> list[dict[str, Any]]:
    """Ses moyens de communication : ceux par où elle lui parle."""
    s = look.frame.state("identity")
    out = []
    for key in handles_of(s, person):
        h = s.handles.get(key)
        if h is None:
            continue
        kind = "Identifiant de compte" if h.authenticated else "Compte extérieur" \
            if h.channel == privacy.EXTERNAL else (h.channel or "Moyen de communication").capitalize()
        why = ("Son compte opérateur sur ce serveur." if h.operator else "Son compte sur ce serveur.") \
            if h.authenticated else ""
        out.append({"id": 0, "kind": kind, "value": h.name or handle_label(s, key), "href": subject_url("handle", key),
                    "state": ("lui parle", "ok"),
                    "facts": [("par", CHANNELS.get(h.channel, h.channel or "?")), ("canal", TRUST_SHORT[h.trust]),
                              *((("depuis", f"le {look.date(h.first_seen)}"),) if h.first_seen else ())],
                    "why": why, "merged": False, "detachable": False})
    return out


def identifies(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str],
               forms: Mapping[str, Any] | None = None) -> Markup | None:
    """La fiche d'une personne › Ce qui l'identifie : ses moyens de communication, puis ses identifiants de
    l'annuaire."""
    look = Look.of(ui, DAY)
    acc = accounts(look)
    own = _own_tiles(look, key)
    tiles = list(own)
    for sheet in linked_sheets(look, key):
        mine = tiles_of(look, acc, sheet, holder=key)
        if len(sheet.identifiers) > 1:
            ready = detach_forms(ui, contact_key(sheet.id), [t["id"] for t in mine if t["detachable"]], query, forms)
            for t in mine:
                t["form"] = ready.get(t["id"])
        for t in mine:
            t["href"] = contact_url(sheet.id, "identifiants")
        tiles += mine
    merged = sum(1 for t in tiles if t["merged"])
    counts = [(len(tiles), "moyen de communication" if len(tiles) < 2 else "moyens de communication"),
              (len(own), "qui lui parle" if len(own) < 2 else "qui lui parlent")]
    if merged:
        counts.append((merged, "réuni d'office" if merged < 2 else "réunis d'office"))
    name = look.name(key)
    note = (f"Un compte de {name} (Teams, boîte) désigne d'office son identifiant ou son adresse : ce qu'il en voit "
            f"est à {name}, et ceux qu'il lui fait connaître sont ses contacts. Pour relier un autre moyen de "
            "communication, ouvre sa fiche, puis « Relier ».")
    return Markup(env.get_template("handmade/personnes/identifie.html").render(
        counts=counts, tiles=tiles, names=[], org=None, contact=False, note=note,
        contacts=subject_url("person", key, "contacts")))


def _visible(look: Look, person: str) -> tuple[Any, frozenset[tuple[str, str]]]:
    acc = accounts(look)
    return acc, acc.visible(person)


def contacts_count(look: Look, person: str) -> int:
    """Combien de contacts cette personne voit (connus de loin et organisations)."""
    port = port_of(look)
    if port is None:
        return 0
    _acc, visible = _visible(look, person)
    got = safely(lambda: port.page(visible=visible, linked=False, size=1), "contacts d'une personne")
    return int(got.total) if got is not None else 0


def contacts(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str],
             forms: Mapping[str, Any] | None = None) -> Markup | None:
    """La fiche d'une personne › Contacts : ceux qu'elle voit, par compte, une entrée chacun."""
    look = Look.of(ui, DAY)
    port = port_of(look)
    if port is None:
        return None
    acc, visible = _visible(look, key)
    chosen = str(query.get(ACCOUNT, ""))
    places = sorted(visible)
    pick = next((p for p in places if f"{p[0]}:{p[1]}" == chosen), None)
    seen = frozenset({pick}) if pick is not None else visible
    raw = str(query.get("page", "1"))
    number = max(1, int(raw)) if raw.isdigit() and len(raw) < 9 else 1
    got = port.page(visible=seen, linked=False, page=number, size=PAGE)
    entries = [contact_entry(look, acc, c) for c in got.items]
    people = port.page(visible=visible, linked=False, kind="person", size=1).total
    orgs = port.page(visible=visible, linked=False, kind=ORG, size=1).total
    held = acc.held(key)
    shared = [p for p in places if p not in held and acc.holders(p)]
    base = {k: v for k, v in query.items() if k == "onglet"}
    chips = [{"label": "Tous", "count": people + orgs, "on": pick is None,
              "href": "?" + urlencode({**base})}]
    for p in places:
        n = port.page(visible=frozenset({p}), linked=False, size=1).total
        if n:
            # son téléphone, ce qu'elle lui a raconté : sur sa fiche, sans son nom (« Téléphone », « Racontés »)
            label = OWN_WORDS[p[0]] if p in held and p[0] in OWN_WORDS else place_name(acc, p)
            chips.append({"label": label + ("" if p in held else " · partagé" if p in shared else
                                            " · à tout le monde"),
                          "count": n, "on": p == pick, "href": "?" + urlencode({**base, ACCOUNT: f"{p[0]}:{p[1]}"})})
    pager = render.pager_ctx(Pager("page", got.number, got.size, got.total), dict(query))
    name = look.name(key)
    counts = [(people + orgs, "contacts" if people + orgs > 1 else "contact"),
              (people, "personnes" if people > 1 else "personne"),
              (orgs, "organisations" if orgs > 1 else "organisation")]
    return Markup(env.get_template("handmade/personnes/contacts.html").render(
        name=name, of=elided(name, "de"), counts=counts, chips=chips if len(chips) > 2 else [], entries=entries,
        total=got.total, pager={"pager": pager}, lede=plural(got.total, "contact", "contacts")))


def _identifiers(look: Look, who: Who) -> int:
    """Sa part du compte de Ce qui l'identifie : les identifiants des fiches de l'annuaire qui lui sont reliées (la
    fiche y ajoute ses moyens de communication)."""
    return sum(len(x.identifiers) for x in linked_sheets(look, who.person))


def _contacts(look: Look, who: Who) -> int:
    """Le compte de l'onglet Contacts."""
    return contacts_count(look, who.person)


def hidden(ui: UI, key: str) -> Sequence[str]:
    """Contacts (ADR 0298) seulement pour qui en a : ses comptes, ceux qu'on lui partage, ceux de personne."""
    return () if contacts_count(Look.of(ui, DAY), key) else ("contacts",)


#: sa part de la fiche d'une personne (ADR 0310)
PERSON_PART = PersonPart(
    # ce qui l'identifie : ses moyens de communication, et les identifiants des fiches de l'annuaire qui lui sont
    # reliées (« Détacher » sur ceux-là) ; ses contacts (ADR 0298)
    tabs={"adresses": identifies, "contacts": contacts},
    counts={"adresses": _identifiers, "contacts": _contacts}, hidden=hidden,
    # la feuille de l'annuaire (« Ce qui l'identifie », « Contacts ») ; ``personnes.css``, la fiche la charge déjà
    styles=("handmade/personnes_annuaire.css",))


__all__ = ["PERSON_PART", "contacts", "contacts_count", "hidden", "identifies", "linked_sheets"]
