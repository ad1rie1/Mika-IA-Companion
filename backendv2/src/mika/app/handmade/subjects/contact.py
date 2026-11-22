"""La fiche d'un contact, dessinée (ADR 0298) : une personne qu'elle connaît de loin, ou une organisation.

- **L'en-tête** : son avatar (neutre et cerné d'un pointillé ; carré pour une organisation), son nom, « connue de
  loin » ou « organisation » et son organisation, quand elle l'a vue pour la première fois et où, combien de fois, et
  qu'elle ne lui a jamais écrit ; ses moyens de communication, de qui c'est le contact, son organisation. La console
  y ajoute ses gestes : « Réunir avec… » (une autre fiche, ou la personne qui lui parle), « Délier », et « Oublier »
  sous « ⋯ » — l'oubli de la console, qui atteint ce que Teams et le courrier gardaient d'elle.
- **La vue d'ensemble** d'une personne : un seul bandeau (un rapprochement à valider), la bande de chiffres, ce
  qu'elle en sait (ses profils : poste, service, entreprise, ses noms — sa mémoire ne s'en forme pas encore d'idée),
  où elle la voit (chaque compte, combien, quand, et où le lire), de qui c'est le contact (et à qui ce qu'elle a lu
  se dit), ce qui l'identifie, ses derniers courriers lus (Teams ne se lit pas par auteur : ses messages sont dans
  ses conversations). D'une organisation : ses personnes, ce qui l'identifie (domaine, entreprise, organisation
  Teams, ses adresses sans personne derrière), de qui c'est le contact.
- **Ce qu'elle en sait** (lot 6) : sous ses profils, les faits qu'elle a tirés de ses derniers messages — chacun d'où
  il vient (« lu dans Teams · … · il y a … »), sa confiance en jauge — et, dans l'onglet du même nom, « Oublier » fait
  par fait (``contacts.oublier_fait``, audité).
- **Ce qui l'identifie** : une tuile par identifiant — sa sorte, sa valeur, où elle l'a vu, depuis quand, réuni
  d'office quand c'est le compte de sa personne, et « Détacher » ; ses noms ; son organisation. Un expéditeur du
  téléphone s'y dit par le nom sous lequel le téléphone le connaît, un nom raconté par ce nom. **Personnes** (une
  organisation) : ses membres. **Où elle la voit** : la vue du plugin, bloc par bloc.
- **Où elle la voit**, sur la vue d'ensemble : chaque compte Teams et chaque boîte ; chaque conversation du téléphone
  où elle l'a lue (un tête-à-tête, un groupe et son nom), qui mène au téléphone de la personne ; chaque personne qui
  lui en a parlé, combien de fois, qui mène à leurs échanges.

Les données sont celles du port ``contacts`` ; à qui est un contact, des comptes de ses vues (``directory``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.app.handmade import Look, excerpt
from mika.app.handmade import blocks as drawn_blocks
from mika.app.handmade.directory import STYLES as DIRECTORY_STYLES
from mika.app.handmade.directory import Accounts, accounts, contact_url, place_name, port_of, short
from mika.app.handmade.subjects.parts import safely
from mika.inspector import render
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import PREFIX, UI, Forms, Overview, env
from mika.kernel.clock import DAY
from mika.kernel.inspect import ActionSlot, plural
from mika.plugins.contacts.inspect import (
    KIND,
    KIND_TITLES,
    KIND_WORDS,
    SOURCE_WORDS,
    app_word,
    contact_id,
    contact_key,
    seen_count,
    span_of,
)
from mika.plugins.email.inspect.common import mail_key
from mika.ports.contacts import (
    COMPANY,
    DOMAIN,
    EMAIL,
    MAIL,
    OPAQUE_KINDS,
    ORG,
    ORG_KINDS,
    PHONE,
    PHONE_APP,
    PHONE_SOURCE,
    TEAMS,
    TENANT,
    TOLD,
    TOLD_NAME,
    ContactLine,
    ContactSheet,
    app_family,
)
from mika.ports.mail import MailQuery
from mika.vocab.access import SELF
from mika.vocab.words import elided

TABS = ("membres", "identifiants", "savoir")
#: ses derniers courriers lus, au plus ; ses personnes, sur la vue d'ensemble d'une organisation
LAST_READ, MEMBERS_SHOWN = 3, 8
DETACH = "contacts.detacher"
#: oublier un fait qu'elle a tiré de ses messages (lot 6)
FORGET_FACT = "contacts.oublier_fait"
#: la file « À valider » ouverte sur un rapprochement
MATCHES = f"{PREFIX}/approbations/rapprochements"


def sheet_of(ui: UI, key: str) -> ContactSheet | None:
    port = ui.kernel.ports.get("contacts")
    cid = contact_id(key)
    return safely(lambda: port.sheet(cid), "fiche d'un contact") if port is not None and cid else None


def _places(sheet: ContactSheet) -> dict[tuple[str, str], dict[str, Any]]:
    """Où elle le voit, par compte : combien (une adresse générique comptée par son domaine), la première et la
    dernière fois, le nom qu'il y porte, ses identifiants."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for i in sheet.identifiers:
        for x in i.sightings:
            got = out.setdefault((x.source, x.account), {"count": 0, "first": 0, "last": 0, "name": "", "own": False,
                                                          "ids": []})
            got["count"] += 0 if i.generic else x.count
            got["first"] = min(filter(None, (got["first"], x.first)), default=0)
            if x.last >= got["last"]:
                got["last"], got["name"] = x.last, x.name or got["name"]
            got["own"] = got["own"] or x.own
            got["ids"].append(i)
    return out


def told_count(sheet: ContactSheet) -> int:
    """Combien de fois on lui en a parlé (les éléments de sa mémoire, par personne qui les lui a confiés)."""
    return sum(x.count for i in sheet.identifiers if i.kind == TOLD_NAME for x in i.sightings)


def read_count(sheet: ContactSheet) -> int:
    """Combien de messages d'elle ou de lui elle a lus (ce qu'on lui a raconté n'en est pas)."""
    return seen_count(sheet) - told_count(sheet)


def whose_words(look: Look, acc: Accounts, sheet: ContactSheet) -> list[dict[str, Any]]:
    """De qui c'est le contact : chaque personne, et par quels comptes ; vide, de tout le monde."""
    by: dict[str, list[str]] = {}
    for place in sorted(_places(sheet)):
        for person in acc.holders(place):
            via = f"ce {elided(acc.label.get(place, place[1]), 'que')} lui a raconté" if place[0] == TOLD \
                else place_name(acc, place)
            if via not in by.get(person, []):
                by.setdefault(person, []).append(via)
    return [{"name": look.name(p), "href": subject_url("person", p, "contacts"), "via": ", ".join(ws)}
            for p, ws in by.items()]


def _names(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " et " + items[-1] if items else ""


def head_of(look: Look, acc: Accounts, sheet: ContactSheet) -> dict[str, Any]:
    """L'en-tête de sa fiche : son nom, ses étiquettes, ses faits sur une ligne, ses liens."""
    org = sheet.kind == ORG
    tags = [{"text": "organisation", "cls": "org"}] if org else \
        [{"text": "lui parle aussi", "cls": "close"}] if sheet.person else [{"text": "connue de loin", "cls": "far"}]
    if sheet.org is not None:
        tags.append({"text": sheet.org.name, "cls": "org", "href": contact_url(sheet.org.id)})
    first, last = span_of(sheet)
    places = _places(sheet)
    where = sorted(places, key=lambda p: places[p]["first"] or 1 << 62)
    facts = []
    if org:
        facts += [f"{KIND_WORDS[TENANT]} « {shown_value(i)} »" if i.kind == TENANT else i.value
                  for i in sheet.identifiers if i.kind in (DOMAIN, TENANT)][:3]
        facts.append(plural(len(sheet.members), "personne", "personnes"))
    if first and where and where[0][0] == TOLD:
        facts.append(f"racontée pour la première fois le {look.date(first)}")
    elif first and where and where[0][0] == PHONE_SOURCE:
        facts.append(f"vue pour la première fois le {look.date(first)} sur {place_name(acc, where[0])}")
    elif first:
        facts.append(f"vue pour la première fois le {look.date(first)}"
                     + (f" dans {SOURCE_WORDS.get(where[0][0], where[0][0])}" if where else ""))
    seen, told = read_count(sheet), told_count(sheet)
    if seen and not org:
        facts.append(plural(seen, "message lu", "messages lus"))
    if told:
        facts.append(f"racontée {plural(told, 'fois', 'fois')}")
    if last:
        facts.append(f"la dernière {look.ago(last)}")
    if not org and not sheet.person:
        facts.append("ne lui a jamais écrit")
    ids = [i for i in sheet.identifiers if not i.generic and i.kind != TOLD_NAME]  # un nom raconté ne la joint pas
    kinds = list(dict.fromkeys(app_word(i.value) if i.kind == PHONE_APP else KIND_WORDS.get(i.kind, i.kind)
                               for i in ids))
    links = [{"text": plural(len(ids), "moyen de communication", "moyens de communication")
              + (f" · {', '.join(kinds)}" if kinds else "") if ids or org else "connue seulement de nom",
              "href": contact_url(sheet.id, "identifiants")}]
    whose = whose_words(look, acc, sheet)
    if whose:
        links.append({"text": "contact " + elided(_names([w["name"] for w in whose]), "de"),
                      "href": whose[0]["href"] if len(whose) == 1 else ""})
    else:
        links.append({"text": "contact de tout le monde", "href": ""})
    if sheet.person:
        links.append({"text": f"reliée à {look.name(sheet.person)}", "href": subject_url("person", sheet.person)})
    if sheet.org is not None:
        links.append({"text": sheet.org.name, "href": contact_url(sheet.org.id)})
    return {"name": sheet.name or contact_key(sheet.id), "initial": (sheet.name[:1] or "?").upper(),
            "kind": "org" if org else "far", "tags": tags, "facts": facts, "links": links}


def _suggestion(ui: UI, sheet: ContactSheet) -> dict[str, Any] | None:
    """Un rapprochement qui la concerne et attend (le premier) : le bandeau unique de sa fiche."""
    port = ui.kernel.ports.get("contacts")
    found = next((x for x in safely(lambda: port.suggestions(200), "rapprochements", []) or ()
                  if sheet.id in (x.a.id, x.b.id)), None) if port is not None else None
    if found is None:
        return None
    other = found.b if found.a.id == sheet.id else found.a
    them = sheet_of(ui, contact_key(other.id))
    said = next((i.value for i in them.identifiers if i.kind == EMAIL), "") if them is not None else ""
    return {"name": other.name, "said": said, "href": contact_url(other.id),
            "open": f"{MATCHES}?" + urlencode({"element": f"{MATCH}:{min(found.a.id, found.b.id)}-"
                                                         f"{max(found.a.id, found.b.id)}"})}


#: la sorte d'un rapprochement dans la file « À valider » (``waiting.py``)
MATCH = "rapprochement"


def _place_rows(ui: UI, look: Look, acc: Accounts, sheet: ContactSheet) -> list[dict[str, Any]]:
    """Où elle le voit : une ligne par compte, ce qu'elle y a lu, et où le relire (ses conversations Teams, les
    courriers de ses adresses)."""
    rows = _phone_rows(look, acc, sheet)
    mail = ui.kernel.ports.get("mail")
    for (source, account), got in sorted(_places(sheet).items(), key=lambda kv: -kv[1]["last"]):
        label = place_name(acc, (source, account))
        n = got["count"]
        if source == PHONE_SOURCE:
            continue  # conversation par conversation (``_phone_rows``)
        if source == TOLD:
            label = SOURCE_WORDS[TOLD]
            text = f"{place_name(acc, (source, account))} · {plural(n, 'fois', 'fois')}"
            href = subject_url("person", account, "echanges") if account != SELF else ""
            meta = f"sous le nom « {got['name']} »" if got["name"] else ""
        elif source == TEAMS:
            text = plural(n, "message", "messages") if n else "son profil"
            href = f"{PREFIX}/teams/conversations?" + urlencode({"compte": account})
            meta = f"sous le nom « {got['name']} »" if got["name"] else ""
        elif source == MAIL:
            text = plural(n, "courrier", "courriers") if n else "son adresse"
            address = next((i.value for i in got["ids"] if i.kind == EMAIL), "")
            href = f"{PREFIX}/courrier/reception?" + urlencode({"compte": account, "dossier": "*", "de": address}) \
                if address else ""
            latest = _mails(mail, account, [address], 1) if address else []
            meta = f"le dernier : « {excerpt(latest[0].subject, 80)} »" if latest else ""
        else:
            text, href, meta = plural(n, "fois", "fois"), "", ""
        if got["own"]:
            meta = "c'est la personne de ce compte" + (f" · {meta}" if meta else "")
        rows.append({"source": label, "text": text, "href": href, "meta": meta,
                     "when": look.ago(got["last"]) if got["last"] else "", "last": got["last"]})
    rows.sort(key=lambda r: -r.pop("last"))
    return rows


def _phone_rows(look: Look, acc: Accounts, sheet: ContactSheet) -> list[dict[str, Any]]:
    """Où elle le voit sur les téléphones : une ligne par conversation (un tête-à-tête, un groupe et son nom), qui
    mène au téléphone de la personne ; un expéditeur vu sans conversation gardée, une ligne pour sa vue."""
    rows = []
    for i in sheet.identifiers:
        if i.kind != PHONE_APP:
            continue
        for x in i.sightings:
            if x.source != PHONE_SOURCE:
                continue
            href = subject_url("person", x.account, "telephone")
            where = place_name(acc, (x.source, x.account))
            meta = f"sous le nom « {x.name} »" if x.name else ""
            for th in x.threads or ():
                what = f"groupe « {th.title} »" if th.group and th.title else "un groupe" if th.group \
                    else "en tête-à-tête"
                rows.append({"source": app_word(i.value), "text": f"{plural(th.count, 'message', 'messages')} · "
                                                                  f"{what}", "href": href,
                             "meta": f"{where}" + (f" · {meta}" if meta else ""),
                             "when": look.ago(th.last) if th.last else "", "last": th.last})
            if not x.threads:
                rows.append({"source": app_word(i.value), "text": plural(x.count, "message", "messages"),
                             "href": href, "meta": f"{where}" + (f" · {meta}" if meta else ""),
                             "when": look.ago(x.last) if x.last else "", "last": x.last})
    return rows


def _mails(port: Any, account: str, addresses: Sequence[str], limit: int) -> list[Any]:
    """Ses derniers courriers dans cette boîte (tous dossiers), du plus récent."""
    if port is None:
        return []
    out: list[Any] = []
    for address in addresses:
        got = safely(lambda a=address: port.messages_page(MailQuery(accounts=(account,) if account else None,
                                                                     sender=a), 1, limit), "courriers d'un contact")
        out += list(getattr(got, "items", ()) or ())
    return sorted(out, key=lambda m: -m.date)[:limit]


def _last_read(ui: UI, look: Look, acc: Accounts, sheet: ContactSheet) -> list[dict[str, Any]]:
    """Ses derniers courriers lus (Teams ne se lit pas par auteur : ses messages restent dans ses conversations)."""
    mail = ui.kernel.ports.get("mail")
    addresses = [i.value for i in sheet.identifiers if i.kind == EMAIL and not i.generic]
    boxes = sorted({x.account for i in sheet.identifiers if i.kind == EMAIL for x in i.sightings if x.source == MAIL})
    got = sorted((m for box in boxes for m in _mails(mail, box, addresses, LAST_READ)), key=lambda m: -m.date)
    return [{"text": excerpt(m.subject or "(sans objet)", 160), "body": excerpt(m.body, 220),
             "meta": f"Courrier · {acc.label.get((MAIL, m.account), m.account)}"
                     + (f" · {look.ago(m.date)}" if m.date else ""),
             "href": subject_url("mail", mail_key(m.ref))} for m in got[:LAST_READ]]


def shown_value(i: Any) -> str:
    """La valeur d'un identifiant telle qu'on la lit : une entreprise, une organisation Teams sous le nom qu'on lui a
    vu (sa valeur est repliée pour se comparer), un expéditeur du téléphone sous le nom que le téléphone lui donne, un
    nom raconté tel qu'on le lui a dit, un identifiant Teams raccourci."""
    if i.kind in (COMPANY, TENANT, *OPAQUE_KINDS):
        found = next((x.name for x in i.sightings if x.name), "")
        return found or ("hors du carnet" if i.kind == PHONE_APP else i.value)
    return short(i.kind, i.value)


def _identifiers_line(sheet: ContactSheet, generic: bool = False) -> list[dict[str, str]]:
    # ni un nom raconté, ni un expéditeur que le téléphone ne nomme pas (son numéro, s'il le donne, est déjà là)
    return [{"k": app_word(i.value) if i.kind == PHONE_APP else KIND_WORDS.get(i.kind, i.kind), "v": shown_value(i)}
            for i in sheet.identifiers if i.generic == generic and i.kind != TOLD_NAME
            and not (i.kind == PHONE_APP and not any(x.name for x in i.sightings))]


def line_of(sheet: ContactSheet) -> ContactLine:
    """Une fiche lue en entier, dite comme une ligne de l'annuaire (une entrée : ``directory.contact_entry``)."""
    places = _places(sheet)
    first, last = span_of(sheet)
    apps: dict[str, int] = {}
    for i in sheet.identifiers:
        if i.kind == PHONE_APP and app_family(i.value):
            apps[app_family(i.value)] = apps.get(app_family(i.value), 0) + sum(x.count for x in i.sightings)
    return ContactLine(sheet.id, sheet.kind, sheet.name, sheet.org.id if sheet.org is not None else 0,
                       sheet.org.name if sheet.org is not None else "", sheet.person, seen_count(sheet), last,
                       tuple(sorted({s for s, _a in places})),
                       tuple((i.kind, i.value) for i in sheet.identifiers), sheet.title, sheet.department,
                       tuple((s, a, got["count"]) for (s, a), got in sorted(places.items())), len(sheet.members),
                       tuple(sorted(apps.items())))


class ContactFiche(Overview):
    """La fiche d'un contact : son en-tête, sa vue d'ensemble, « Ce qui l'identifie » et « Personnes » dessinés ; « Où
    elle la voit » bloc par bloc."""

    slug = "ensemble"
    title = "Vue d'ensemble"
    styles = ("handmade/person.css", *DIRECTORY_STYLES)
    tabs = TABS

    def head(self, ui: UI, key: str) -> Markup | None:
        sheet = sheet_of(ui, key)
        if sheet is None:
            return None
        look = Look.of(ui, DAY)
        return Markup(env.get_template("handmade/personnes/contact_tete.html").render(h=head_of(look, accounts(look), sheet)))

    def counts(self, ui: UI, key: str) -> Mapping[str, int]:
        sheet = sheet_of(ui, key)
        if sheet is None:
            return {}
        port = ui.kernel.ports.get("contacts")
        notes = safely(lambda: port.notes(sheet.id), "ce qu'elle sait d'un contact", []) if port is not None else []
        return {"identifiants": len(sheet.identifiers), "membres": len(sheet.members),
                "vues": len(_places(sheet)), "savoir": len(notes or ())}

    def hidden(self, ui: UI, key: str) -> Sequence[str]:
        """Une personne n'a pas de membres : l'onglet n'est qu'aux organisations ; une organisation n'a pas de
        portrait (elle n'écrit pas : ses personnes, si)."""
        sheet = sheet_of(ui, key)
        if sheet is None:
            return ()
        return ("savoir",) if sheet.kind == ORG else ("membres",)

    def render(self, ui: UI, key: str) -> Markup | None:
        sheet = sheet_of(ui, key)
        if sheet is None:
            return None
        look = Look.of(ui, DAY)
        acc = accounts(look)
        places = _places(sheet)
        by_source: dict[str, int] = {}
        for (source, _account), got in places.items():
            by_source[source] = by_source.get(source, 0) + got["count"]
        org = sheet.kind == ORG
        figures = []
        if org:
            figures.append({"n": len(sheet.members), "text": "personnes" if len(sheet.members) > 1 else "personne",
                            "href": contact_url(sheet.id, "membres")})
        if read_count(sheet) or not told_count(sheet):
            figures.append({"n": read_count(sheet), "text": "messages lus", "href": contact_url(sheet.id, "vues")})
        words = {TEAMS: ("message Teams", "messages Teams"), MAIL: ("courrier", "courriers"),
                 PHONE_SOURCE: ("message du téléphone", "messages du téléphone"), TOLD: ("fois racontée", "fois racontée")}
        # d'une seule source, le premier chiffre le dit déjà (sauf ce qu'on lui a raconté, qui n'en est pas un)
        if sum(1 for n in by_source.values() if n) > 1 or (by_source.get(TOLD) and not read_count(sheet)):
            figures += [{"n": n, "text": (words.get(s, (SOURCE_WORDS.get(s, s),) * 2)[0 if n < 2 else 1]),
                         "href": contact_url(sheet.id, "vues")} for s, n in sorted(by_source.items()) if n]
        figures.append({"n": len(places), "text": "comptes" if len(places) > 1 else "compte",
                        "href": contact_url(sheet.id, "vues")})
        known = [(label, value) for label, value in (
            ("poste", sheet.title), ("service", sheet.department),
            ("entreprise", next((x.name for i in sheet.identifiers if i.kind == COMPANY for x in i.sightings
                                 if x.name), "")),
            ("organisation", sheet.org.name if sheet.org is not None else ""),
            ("ses noms", "" if org else ", ".join(sheet.names[:4]))) if value]
        whose = whose_words(look, acc, sheet)
        name = sheet.name or contact_key(sheet.id)
        context = {
            "name": name, "of": elided(name, "de"), "org": org, "figures": figures, "known": known,
            "alert": None if org else _suggestion(ui, sheet), "places": _place_rows(ui, look, acc, sheet),
            "whose": whose, "whose_names": _names([w["name"] for w in whose]), "person": sheet.person,
            "person_name": look.name(sheet.person) if sheet.person else "",
            "person_href": subject_url("person", sheet.person) if sheet.person else "",
            "ids": _identifiers_line(sheet), "generic": _identifiers_line(sheet, True),
            "ids_href": contact_url(sheet.id, "identifiants"), "places_href": contact_url(sheet.id, "vues"),
            "read": [] if org else _last_read(ui, look, acc, sheet),
            "notes": [] if org else notes_of(ui, look, acc, sheet), "notes_href": contact_url(sheet.id, "savoir"),
            "members": [{"name": m.name, "href": contact_url(m.id), "initial": (m.name[:1] or "?").upper()}
                        for m in sheet.members[:MEMBERS_SHOWN]],
            "members_total": len(sheet.members), "members_href": contact_url(sheet.id, "membres"),
        }
        return Markup(env.get_template("handmade/personnes/contact.html").render(c=context))

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Sequence[Any], query: Mapping[str, str],
                   forms: Mapping[str, Any] | None = None) -> Any:
        sheet = sheet_of(ui, key)
        if sheet is None:
            return None
        look = Look.of(ui, DAY)
        if tab == "identifiants":
            return identifiers_tab(ui, look, key, sheet, query, forms)
        if tab == "savoir":
            return knows_tab(ui, look, key, sheet, query, forms)
        if tab == "membres":
            members = [{"name": m.name, "href": contact_url(m.id), "initial": (m.name[:1] or "?").upper()}
                       for m in sheet.members]
            return Markup(env.get_template("handmade/personnes/membres.html").render(
                name=sheet.name, members=members))
        return drawn_blocks.page(ui, blocks, query, forms=forms) if tab in TABS else None


def notes_of(ui: UI, look: Look, acc: Accounts, sheet: ContactSheet) -> list[dict[str, Any]]:
    """Ce qu'elle a tiré de ses derniers messages (lot 6) : chaque fait, d'où il vient (« lu dans Teams · Équipe ·
    dans le groupe « Projet » · il y a 2 j »), sa confiance (en jauge), le lien qui mène à son « Oublier »."""
    port = ui.kernel.ports.get("contacts")
    notes = safely(lambda: port.notes(sheet.id), "ce qu'elle sait d'un contact", []) if port is not None else []
    out = []
    for n in notes or ():
        where = [f"lu dans {place_name(acc, (n.source, n.account))}", *([n.place] if n.place else [])]
        if n.said_at or n.at:
            where.append(look.ago(n.said_at or n.at))
        pct = round(n.confidence * 100)
        out.append({"id": n.id, "text": n.text, "meta": " · ".join(where), "confidence": f"{pct} %",
                    "confidence_w": pct, "kind": NOTE_WORDS.get(n.kind, ""),
                    "forget": contact_url(sheet.id, "savoir") + f"#fait-{n.id}"})
    return out


#: la sorte d'un fait, en mots
NOTE_WORDS = {"role": "son rôle", "topic": "un sujet", "relation": "avec qui", "expectation": "ce qu'elle attend",
              "manner": "sa façon d'être", "bond": "avec la personne du compte", "other": ""}


def fact_forms(ui: UI, key: str, ids: Sequence[int], query: Mapping[str, str], forms: Any) -> dict[int, Any]:
    """Le formulaire « Oublier » de chaque fait, préparé par la console pour la fiche ``key`` ; sans formulaires (un
    rendu hors d'une page), aucun."""
    if not isinstance(forms, Forms) or not ids:
        return {}
    slots = render.blocks([ActionSlot(FORGET_FACT, (("fait", str(i)),), title="Oublier") for i in ids],
                          ui.env(), dict(query))
    prepared = forms.of(slots, key)
    return {int(x["initial"]["fait"]): prepared[x["slot"]] for x in slots if x["slot"] in prepared}


def knows_tab(ui: UI, look: Look, key: str, sheet: ContactSheet, query: Mapping[str, str], forms: Any) -> Markup:
    """« Ce qu'elle en sait » : chaque fait tiré de ses derniers messages, et « Oublier » ; ses portraits."""
    acc = accounts(look)
    notes = notes_of(ui, look, acc, sheet)
    ready = fact_forms(ui, key, [n["id"] for n in notes], query, forms)
    for n in notes:
        n["form"] = ready.get(n["id"])
    port = ui.kernel.ports.get("contacts")
    done = safely(lambda: port.portraits(contacts={sheet.id}), "portraits d'un contact", []) if port is not None \
        else []
    last = done[0] if done else None
    status = (f"Dernier portrait {look.ago(last.at)}, sur {plural(last.read, 'message', 'messages')}"
              + ("" if last.ok else " : sa réponse ne se lisait pas, rien n'a été gardé") + ".") if last else \
        "Pas encore de portrait : elle ne relit que qui échange vraiment avec un compte (des messages dans les deux sens)."
    return Markup(env.get_template("handmade/personnes/savoir.html").render(
        name=sheet.name, of=elided(sheet.name or contact_key(sheet.id), "de"), notes=notes, status=status,
        portraits=len(done or ())))


def detach_forms(ui: UI, key: str, ids: Sequence[int], query: Mapping[str, str], forms: Any) -> dict[int, Any]:
    """Le formulaire « Détacher » de chaque identifiant, préparé par la console pour la fiche ``key`` (celle du
    contact, même sur la fiche d'une personne qui lui parle) ; sans formulaires (un rendu hors d'une page), aucun."""
    if not isinstance(forms, Forms) or not ids:
        return {}
    slots = render.blocks([ActionSlot(DETACH, (("identifiant", str(i)),), title="Détacher") for i in ids],
                          ui.env(), dict(query))
    prepared = forms.of(slots, key)
    return {int(x["initial"]["identifiant"]): prepared[x["slot"]] for x in slots if x["slot"] in prepared}


def tiles_of(look: Look, acc: Accounts, sheet: ContactSheet, *, holder: str = "") -> list[dict[str, Any]]:
    """Une tuile par identifiant d'une fiche : sa sorte, sa valeur, où elle l'a vu, depuis quand, pourquoi il est là.
    ``holder`` : la personne qui lui parle dont c'est la fiche (un identifiant vu comme la personne de son compte est
    « son compte »)."""
    out = []
    for i in sheet.identifiers:
        own = [x for x in i.sightings if x.own]
        where = [f"{place_name(acc, (x.source, x.account))}" + (f" · {plural(x.count, 'fois', 'fois')}" if x.count
                                                                 else " · son profil" if x.source == TEAMS else "")
                 for x in i.sightings]
        first = min((x.first for x in i.sightings if x.first), default=0)
        names = list(dict.fromkeys(x.name for x in i.sightings if x.name))
        mine = bool(own) and (not holder or any(holder in acc.holders((x.source, x.account)) for x in own))
        if i.generic:
            why, merged = "Une adresse sans personne derrière : rangée à son organisation.", False
        elif mine:
            why, merged = f"Réuni d'office : c'est la personne de {place_name(acc, (own[0].source, own[0].account))}.", True
        elif i.kind == EMAIL and any(x.source == TEAMS for x in i.sightings) and len(sheet.identifiers) > 1:
            why, merged = "Réuni d'office : la même adresse sur son profil Teams.", True
        elif i.kind in (COMPANY, TENANT):
            why, merged = "Le nom que ses profils Teams donnent à son entreprise.", False
        elif i.kind == DOMAIN:
            why, merged = "Le domaine de ses adresses.", False
        elif i.kind == PHONE_APP:
            holders = [acc.label.get((x.source, x.account), x.account) for x in i.sightings]
            number = next((n.value for n in sheet.identifiers if n.kind == PHONE
                           and any(x.source == PHONE_SOURCE for x in n.sightings)), "")
            if not names and number:  # hors du carnet : le téléphone ne le nomme que par son numéro
                why, merged = f"Réuni d'office : le téléphone ne le nomme que par son numéro, {number}.", True
            else:
                why = (f"Le nom sous lequel le téléphone {elided(_names(holders), 'de')} le connaît : un contact "
                       "renommé reste le même.") if holders else ""
                merged = False
        elif i.kind == TOLD_NAME:
            why, merged = "On lui en a parlé sous ce nom : ce que sa mémoire en garde s'y rattache.", False
        else:
            why, merged = "", False
        kind = f"Contact {app_word(i.value)}" if i.kind == PHONE_APP else KIND_TITLES.get(i.kind, i.kind)
        out.append({"id": i.id, "kind": kind,
                    "value": shown_value(i) if i.kind in (COMPANY, TENANT, *OPAQUE_KINDS) else i.value,
                    "state": ("son compte", "owner") if mine else ("elle le lit", "far"),
                    "facts": [*(("nom", n) for n in names[:1] if i.kind not in OPAQUE_KINDS), *(("vu dans", w) for w in [" ; ".join(where)] if w),
                              *(("depuis", f"le {look.date(first)}") for _ in [0] if first)],
                    "why": why, "merged": merged, "detachable": i.kind not in ORG_KINDS})
    return out


def identifiers_tab(ui: UI, look: Look, key: str, sheet: ContactSheet, query: Mapping[str, str],
                    forms: Any) -> Markup:
    """« Ce qui l'identifie » d'une fiche de l'annuaire : ses tuiles, ses noms, son organisation."""
    acc = accounts(look)
    tiles = tiles_of(look, acc, sheet)
    if len(sheet.identifiers) > 1:
        ready = detach_forms(ui, key, [t["id"] for t in tiles if t["detachable"]], query, forms)
        for t in tiles:
            t["form"] = ready.get(t["id"])
    port = port_of(look)
    pending = sum(1 for x in (safely(lambda: port.suggestions(200), "rapprochements", []) or ())
                  if sheet.id in (x.a.id, x.b.id)) if port is not None else 0
    counts = [(len(sheet.identifiers), "moyen de communication" if len(sheet.identifiers) < 2
               else "moyens de communication"),
              (sum(1 for t in tiles if t["merged"]), "réunis d'office" if sum(1 for t in tiles if t["merged"]) > 1
               else "réuni d'office"),
              (len(sheet.names), "noms" if len(sheet.names) > 1 else "nom")]
    if pending:
        counts.append((pending, "rapprochements à valider" if pending > 1 else "rapprochement à valider"))
    names = []
    for n in sheet.names:
        where = sorted({SOURCE_WORDS.get(x.source, x.source) for i in sheet.identifiers for x in i.sightings
                        if x.name == n})
        names.append({"name": n, "where": " et ".join(where), "shown": n == sheet.name})
    org = None
    if sheet.org is not None:
        theirs = sheet_of(ui, contact_key(sheet.org.id))
        by = [f"le domaine {i.value}" if i.kind == DOMAIN else f"son {KIND_WORDS.get(i.kind, i.kind)}"
              for i in (theirs.identifiers if theirs is not None else ()) if i.kind in ORG_KINDS]
        org = {"name": sheet.org.name, "href": contact_url(sheet.org.id),
               "why": "par " + (" et ".join(by) if len(by) < 3 else ", ".join(by[:-1]) + " et " + by[-1]) if by else ""}
    return Markup(env.get_template("handmade/personnes/identifie.html").render(
        counts=counts, tiles=tiles, names=names, org=org, contact=sheet.kind != ORG, matches=MATCHES))


__all__ = ["ContactFiche", "KIND", "MATCH", "detach_forms", "fact_forms", "head_of", "knows_tab", "line_of",
           "notes_of", "sheet_of", "shown_value", "tiles_of", "whose_words"]
