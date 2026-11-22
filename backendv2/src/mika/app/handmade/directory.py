"""L'annuaire, tel que la console le montre (ADR 0298) : tous ceux qu'elle connaît — qui lui parle (la faculté
``identity``) et qui elle connaît de loin, personnes et organisations (le port ``contacts``) —, dits d'une seule façon.

- **Une entrée** (``person_entry``, ``contact_entry``, une forme commune pour ``handmade/personnes/_annuaire.html``) :
  son avatar (de la couleur de ce qu'elle ressent pour qui lui parle ; neutre et cerné d'un pointillé pour qui elle
  connaît de loin ; carré pour une organisation), son nom, ses étiquettes, ce qu'elle en sait en une ligne (son poste
  et son service ; la mémoire viendra), ce qui l'identifie (la sorte, la valeur), d'où elle la connaît (une étiquette
  par source, avec son compte), et de qui c'est le contact. Une fiche de l'annuaire reliée à une personne qui lui
  parle ne paraît qu'une fois, comme cette personne, ses identifiants ajoutés aux siens.
- **À qui est un contact** : au propriétaire des comptes où elle le voit (``Accounts``, lu dans les ports ``teams`` et
  ``mail`` et, pour les partages, dans les réglages ; le téléphone de quelqu'un et ce que quelqu'un lui a raconté sont
  à cette personne, ``ports.contacts.person_accounts``) — un compte « à toi » est à ses propriétaires, un compte à
  elle ou à personne, à tout le monde (``ports.contacts.visible_sources``). D'où elle le connaît se dit par source
  (« Teams · 48 »), par appli pour le téléphone (« WhatsApp · 2 », « SMS · 1 ») et en fois pour ce qu'on lui a
  raconté (« Racontée · 3 fois »).
- **La liste** (``listing``) : qui lui parle et l'annuaire, réunis et triés du plus récemment vu, paginés ensemble
  sans tout relire (l'annuaire se lit par tranches, ``merged``) ; « Qui » (tout, lui parlent, connues de loin,
  organisations), une recherche (nom, e-mail, téléphone, identifiant) et « Contacts de… » la filtrent.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from mika.app.handmade import Look, person_card, presences
from mika.contracts import identity as identity_c
from mika.contracts import transcript as transcript_c
from mika.faculties.identity.inspect import handles_of, principal
from mika.faculties.identity.inspect import people as everyone_of
from mika.inspector.pages.subjects import subject_url
from mika.plugins.contacts.inspect import APP_WORDS, KIND_WORDS, SOURCE_WORDS, contact_key
from mika.plugins.contacts.inspect import KIND as CONTACT
from mika.ports.contacts import (
    COMPANY,
    MAIL,
    OPAQUE_KINDS,
    ORG,
    PERSON_KIND,
    PHONE_APP,
    PHONE_SOURCE,
    TEAMS,
    TEAMS_ID,
    TENANT,
    TOLD,
    ContactLine,
    app_family,
    normalized,
    person_accounts,
    visible_sources,
)
from mika.ports.paging import page_slice
from mika.vocab import privacy
from mika.vocab.access import PERSON, SELF
from mika.vocab.ownership import holds
from mika.vocab.people import fold
from mika.vocab.words import elided

STYLES = ("handmade/personnes.css", "handmade/personnes_annuaire.css")
#: le filtre « Qui » (un bouton à choix au bout de la barre d'onglets)
WHO = "qui"
ALL, TALK, FAR, ORGS = "tout", "lui_parlent", "loin", "organisations"
WHO_CHOICES = ((ALL, "Tout"), (TALK, "Lui parlent"), (FAR, "Connues de loin"), (ORGS, "Organisations"))
#: « Contacts de … » (la clé d'une personne) ; « à tout le monde » (les comptes qui ne sont à personne)
OF, EVERYONE = "de", "tous"
#: la recherche, et l'affichage en tableau
SEARCH, SHOW, TABLE = "q", "affichage", "tableau"
#: tant d'entrées par page
PAGE = 24
#: ce qu'une entrée nomme de ses identifiants, au plus
IDS_SHOWN = 5
#: par où une personne lui écrit, en mots (ses moyens de communication)
CHANNEL_WORDS = {privacy.WEB: "Chat", privacy.MOBILE: "Application", privacy.EXTERNAL: "Extérieur"}


@dataclass(frozen=True, slots=True)
class Accounts:
    """Les comptes de ses sources : leur propriétaire (vide : ses propriétaires ; ``elle`` ; ``personne:<clé>``), leur
    nom, leurs partages (personne → niveau), et ses propriétaires (leurs clés)."""

    owner: Mapping[tuple[str, str], str] = field(default_factory=dict)
    label: Mapping[tuple[str, str], str] = field(default_factory=dict)
    shares: Mapping[tuple[str, str], Mapping[str, str]] = field(default_factory=dict)
    owners: tuple[str, ...] = ()

    def holders(self, place: tuple[str, str]) -> tuple[str, ...]:
        """À qui est ce compte (des clés de personne) : ses propriétaires, une personne, ou personne (elle, ou un
        compte qu'on ne connaît plus : à tout le monde)."""
        owner = self.owner.get(place)
        if owner is None or owner == SELF:
            return ()
        if not owner:
            return self.owners
        return (owner[len(PERSON):],) if owner.startswith(PERSON) else ()

    def whose(self, places: Collection[tuple[str, str]]) -> tuple[str, ...]:
        """De qui c'est le contact (vide : de tout le monde)."""
        return tuple(dict.fromkeys(p for place in sorted(places) for p in self.holders(place)))

    def held(self, person: str) -> frozenset[tuple[str, str]]:
        """Les comptes à cette personne (à son nom, ou « à toi » si elle est une des propriétaires) : ses contacts."""
        owner = person in set(self.owners)
        return frozenset(p for p, o in self.owner.items() if o != SELF and holds(o, PERSON + person, owner=owner))

    def unowned(self) -> frozenset[tuple[str, str]]:
        """Les comptes qui ne sont à personne (les siens) : leurs contacts sont à tout le monde."""
        return frozenset(p for p, o in self.owner.items() if o == SELF)

    def visible(self, person: str) -> frozenset[tuple[str, str]]:
        """Les comptes dont cette personne voit les contacts : les siens, ceux qu'on lui partage, ceux de personne."""
        return visible_sources(person, owners=self.owners, accounts=self.owner, shares=self.shares)

    def holding(self) -> list[str]:
        """Les personnes qui ont au moins un compte : chacune a ses contacts."""
        return list(dict.fromkeys(p for place in sorted(self.owner) for p in self.holders(place)))

    def reaches(self, person: str) -> bool:
        """Cette personne a un compte, ou on lui en partage un : elle a des contacts à elle."""
        return bool(self.held(person)) or any(PERSON + person in given for given in self.shares.values())


def accounts(look: Look) -> Accounts:
    """Les comptes Teams et les boîtes, tels que les ports les disent ; leurs partages, dans les réglages ; les comptes
    qui sont des personnes (le téléphone de quelqu'un, ce que quelqu'un lui a raconté), tels que l'annuaire les garde."""
    ui = look.ui
    owner: dict[tuple[str, str], str] = {}
    label: dict[tuple[str, str], str] = {}
    for source, name in ((TEAMS, "teams"), (MAIL, "mail")):
        port = ui.kernel.ports.get(name)
        for a in (port.accounts() if port is not None else ()):
            owner[(source, a.key)] = a.owner or ""
            label[(source, a.key)] = a.name
    contacts = ui.kernel.ports.get("contacts")
    for place, whose in person_accounts(contacts.sources() if contacts is not None else ()).items():
        owner[place] = whose
        label[place] = "elle-même" if whose == SELF else look.name(place[1])
    shares: dict[tuple[str, str], Mapping[str, str]] = {}
    settings = ui.deps.settings
    if settings is not None:
        for source, specs in ((MAIL, settings.email().accounts), (TEAMS, settings.teams().accounts)):
            for key, spec in specs.items():
                shares[(source, key)] = dict(spec.shares)
    return Accounts(owner, label, shares, tuple(look.frame.get(identity_c.OWNERS) or ()))


def port_of(look: Look) -> Any:
    return look.ui.kernel.ports.get("contacts")


def contact_url(contact: int, tab: str = "") -> str:
    return subject_url(CONTACT, contact_key(contact), tab)


def short(kind: str, value: str) -> str:
    """Un identifiant tel qu'on le lit en ligne : un identifiant Teams raccourci (« 8:orgid:7c2e41d0-…-91ab »)."""
    if kind == TEAMS_ID and value.startswith("8:orgid:") and len(value) > 28:
        return f"{value[:16]}…{value[-4:]}"
    return value


def place_name(acc: Accounts, place: tuple[str, str]) -> str:
    """Un compte en mots : « Teams · Équipe », « Courrier · Atelier », « le téléphone d'adrien », « racontée par
    adrien »."""
    who = acc.label.get(place, place[1])
    if place[0] == PHONE_SOURCE:
        return f"le téléphone {elided(who, 'de')}"
    if place[0] == TOLD:
        return "ce qu'elle tient d'elle-même" if who == "elle-même" else f"racontée par {who}"
    return f"{SOURCE_WORDS.get(place[0], place[0])} · {who}"


def _of(look: Look, persons: Sequence[str]) -> list[dict[str, str]]:
    return [{"name": look.name(p), "href": subject_url("person", p, "contacts")} for p in persons]


def _sources(places: Sequence[tuple[str, str, int]],
             apps: Sequence[tuple[str, int]] = ()) -> list[dict[str, str]]:
    """D'où elle le connaît : une étiquette par source, combien de fois (rien pour un profil seul) — le téléphone par
    appli (« WhatsApp · 2 », ``apps``), ce qu'on lui a raconté en fois (« Racontée · 3 fois »)."""
    counts: dict[str, int] = {}
    for source, _account, n in places:
        counts[source] = counts.get(source, 0) + n
    out = []
    for s, n in counts.items():
        if s == PHONE_SOURCE and apps:
            out += [{"name": APP_WORDS.get(family, family), "n": str(k) if k else ""} for family, k in apps]
        elif s == TOLD:
            out.append({"name": SOURCE_WORDS[TOLD], "n": f"{n} fois" if n else ""})
        else:
            out.append({"name": SOURCE_WORDS.get(s, s), "n": str(n) if n else ""})
    return out


def entry_ids(c: ContactLine) -> list[dict[str, str]]:
    """Ce qui l'identifie, en ligne : ses moyens de communication (sorte, valeur) — sans un nom raconté ni la clé d'un
    expéditeur du téléphone, qui ne se lisent pas ; une fiche que seul un téléphone connaît dit son appli."""
    ids = []
    for k, v in c.identifiers:
        named = k in (COMPANY, TENANT) and normalized(k, c.name) == v  # sa valeur repliée : son nom la dit
        if k == COMPANY and named or k in OPAQUE_KINDS:
            continue  # l'entreprise est son nom même ; un nom raconté, une clé du téléphone ne se montrent pas
        ids.append({"k": KIND_WORDS.get(k, k), "v": c.name if named else short(k, v)})
    if not ids:  # que le téléphone connaît : son appli, et le nom qu'il lui donne
        ids += [{"k": APP_WORDS.get(app_family(v), KIND_WORDS[PHONE_APP]), "v": c.name or "contact du téléphone"}
                for k, v in c.identifiers if k == PHONE_APP][:1]
    return ids


def contact_entry(look: Look, acc: Accounts, c: ContactLine) -> dict[str, Any]:
    """Une fiche de l'annuaire (connue de loin, ou une organisation), en entrée."""
    org = c.kind == ORG
    tags = [{"text": "organisation", "cls": "org"}] if org else [{"text": "connue de loin", "cls": "far"}]
    if c.org and c.org_name:
        tags.append({"text": c.org_name, "cls": "org", "href": contact_url(c.org)})
    idea = " · ".join(x for x in (c.title, c.department) if x)
    places = [(s, a) for s, a, _n in c.places]
    ids = entry_ids(c)
    told = bool(places) and all(s == TOLD for s, _a in places)
    return {
        "kind": "org" if org else "far", "name": c.name or contact_key(c.id), "initial": (c.name[:1] or "?").upper(),
        "href": contact_url(c.id), "tags": tags,
        "extra": f"{c.members} personne{'s' if c.members > 1 else ''}" if org and c.members else "",
        "when": f"{'racontée' if told else 'vue'} {look.ago(c.last)}" if c.last else "", "last": c.last, "idea": idea,
        "ids": ids[:IDS_SHOWN], "more": max(0, len(ids) - IDS_SHOWN), "sources": _sources(c.places, c.apps),
        "of": _of(look, acc.whose(places)), "everyone": not acc.whose(places), "links": [],
    }


@dataclass(slots=True)
class Talker:
    """Une personne qui lui parle, pour la liste : sa clé, ses moyens de communication, quand elle lui a écrit, et
    les fiches de l'annuaire qui lui sont reliées."""

    person: str
    handles: tuple[str, ...]
    last: int
    linked: tuple[int, ...] = ()


def talkers(look: Look, q: str, links: Mapping[str, tuple[int, ...]], matched: Collection[str] = ()) -> list[Talker]:
    """Qui lui parle, le plus récemment d'abord : ceux que ``q`` trouve (leur nom, leur clé, leurs moyens de
    communication, ou un identifiant d'une fiche qui leur est reliée : ``matched``)."""
    frame = look.frame
    wanted = fold(q)
    out = []
    for person, handles in everyone_of(frame.state("identity"), frame).items():
        if wanted and wanted not in fold(look.name(person)) and wanted not in fold(person) \
                and not any(wanted in fold(h) for h in handles) and person not in matched:
            continue
        last = max((frame.get(transcript_c.LAST_FROM(h)) for h in handles), default=0)
        out.append(Talker(person, tuple(handles), last, links.get(person, ())))
    out.sort(key=lambda t: (-t.last, look.name(t.person).casefold()))
    return out


def person_entry(look: Look, acc: Accounts, t: Talker, online: Mapping[str, dict[str, Any]],
                 lines: Mapping[int, ContactLine], contacts: int | None = None) -> dict[str, Any]:
    """Une personne qui lui parle, en entrée : comme la vue d'ensemble la dit, puis ses moyens de communication et
    les identifiants des fiches de l'annuaire qui lui sont reliées."""
    face = person_card(look, t.person, online.get(t.person))
    s = look.frame.state("identity")
    ids: list[dict[str, str]] = []
    sources: list[dict[str, str]] = []
    main = principal(s, t.person)
    keys = sorted((k for k in handles_of(s, t.person) if k in s.handles),
                  key=lambda k: (k != main, -s.handles[k].first_seen, k))  # le principal d'abord
    for key in keys:
        h = s.handles[key]
        word = "identifiant" if h.authenticated else identity_c.kind_words(h)
        item = {"k": word, "v": h.name or key}
        if item not in ids:
            ids.append(item)
        channel = {"name": CHANNEL_WORDS.get(h.channel, (h.channel or "?").capitalize()), "n": ""}
        if channel not in sources:
            sources.append(channel)
    for cid in t.linked:
        c = lines.get(cid)
        if c is None:
            continue
        ids += [{"k": KIND_WORDS.get(k, k), "v": short(k, v)} for k, v in c.identifiers
                if k not in OPAQUE_KINDS and {"k": KIND_WORDS.get(k, k), "v": short(k, v)} not in ids]
        for place in sorted({(src, a) for src, a, _n in c.places}):
            word = {"name": SOURCE_WORDS[place[0]] if place[0] in (PHONE_SOURCE, TOLD)
                    else acc.label.get(place, place[1]), "n": ""}
            if word not in sources:
                sources.append(word)
    tags = []
    if face["owner"]:
        tags.append({"text": "propriétaire", "cls": "owner"})
    if face["closeness"]:
        tags.append({"text": face["closeness"], "cls": "close" if face["close"] else ""})
    links = []
    if contacts:
        links.append({"text": f"Ses {contacts} contacts →" if contacts > 1 else "Son contact →",
                      "href": subject_url("person", t.person, "contacts")})
    links.append({"text": "Leurs échanges →", "href": subject_url("person", t.person, "echanges")})
    return {
        "kind": "talks", "name": face["name"], "initial": face["initial"], "href": face["href"],
        "emotion": face["felt"]["emotion"] if face.get("felt") else "neutral", "online": face["online"],
        "composing": face["composing"], "tags": tags, "extra": "",
        "when": f"lui a écrit {look.ago(t.last)}" if t.last else "ne lui a jamais écrit", "last": t.last,
        "idea": "", "ids": ids[:IDS_SHOWN + 1], "more": max(0, len(ids) - IDS_SHOWN - 1), "sources": sources,
        "of": [], "everyone": False, "links": links,
    }


def take(fetch: Callable[[int, int], Any], offset: int, limit: int) -> list[ContactLine]:
    """Une tranche quelconque de l'annuaire (``page_slice``, par lectures de cent)."""
    out: list[ContactLine] = []
    while len(out) < limit:
        got = page_slice(fetch, offset + len(out), min(100, limit - len(out)))
        if not got:
            break
        out += got
    return out


def merged(talking: Sequence[Talker], fetch: Callable[[int, int], Any], total: int, offset: int,
           size: int) -> list[Talker | ContactLine]:
    """La tranche ``[offset, offset + size)`` de qui lui parle et de l'annuaire, réunis du plus récemment vu (à
    égalité, qui lui parle d'abord) — l'annuaire lu par tranches seulement : de la place que la page prend dans
    l'ensemble, combien de personnes qui lui parlent la précèdent (``j``) se déduit des fiches qui l'entourent."""
    room = min(len(talking), offset)
    base = offset - room
    near = take(fetch, base, room + size) if total else []

    def first(t: Talker, c: ContactLine) -> bool:
        return t.last >= c.last

    j = 0
    for k in range(room, 0, -1):  # le plus grand k tel que la k-ième personne passe avant la fiche qui la suivrait
        index = offset - k - base
        if index >= len(near) or first(talking[k - 1], near[index]):
            j = k
            break
    people, cards = list(talking[j:]), near[offset - j - base:]
    out: list[Talker | ContactLine] = []
    while len(out) < size and (people or cards):
        if people and (not cards or first(people[0], cards[0])):
            out.append(people.pop(0))
        else:
            out.append(cards.pop(0))
    return out


def query_href(query: Mapping[str, str], **change: str) -> str:
    """L'annuaire avec d'autres paramètres (la page repart à la première)."""
    kept = {k: v for k, v in query.items() if k in (WHO, OF, SEARCH, SHOW) and v}
    for k, v in change.items():
        if v:
            kept[k] = v
        else:
            kept.pop(k, None)
    return "?" + urlencode(kept) if kept else "?"


def listing(look: Look, query: Mapping[str, str]) -> dict[str, Any]:
    """La page de l'annuaire que l'adresse demande : ses entrées, ses comptes, ses puces, sa pagination."""
    who = query.get(WHO, ALL) if query.get(WHO, ALL) in dict(WHO_CHOICES) else ALL
    q = " ".join(str(query.get(SEARCH, "")).split())[:200]
    of = str(query.get(OF, ""))[:200]
    raw = str(query.get("page", "1"))
    number = max(1, int(raw)) if raw.isdigit() and len(raw) < 9 else 1
    port, acc = port_of(look), accounts(look)
    links = port.links() if port is not None else {}
    matched = {c.person for c in port.page(q=q, linked=True, size=100).items} if port is not None and q else set()
    holding = acc.holding()
    if of and of != EVERYONE and of not in holding:
        of = ""
    visible = acc.unowned() if of == EVERYONE else acc.held(of) if of else None
    talking = talkers(look, q, links, matched) if who in (ALL, TALK) and not of else []
    kind = ORG if who == ORGS else PERSON_KIND if who == FAR else None

    def fetch_kind(k: str | None, chosen: Collection[tuple[str, str]] | None) -> Callable[[int, int], Any]:
        return lambda n, size: port.page(visible=chosen, q=q, kind=k, page=n, size=size, linked=False)

    def count(k: str | None, chosen: Collection[tuple[str, str]] | None) -> int:
        return fetch_kind(k, chosen)(1, 1).total if port is not None else 0

    fetch = fetch_kind(kind, visible)
    total_cards = count(kind, visible) if who != TALK else 0
    total = len(talking) + total_cards
    pages = max(1, -(-total // PAGE))
    number = min(number, pages)
    window = merged(talking, fetch, total_cards, (number - 1) * PAGE, PAGE) if total else []
    online = presences(look)
    lines = {c.id: c for c in _lines(port, [cid for item in window if isinstance(item, Talker) for cid in item.linked])}
    entries = []
    for item in window:
        if isinstance(item, Talker):
            mine = count(None, acc.visible(item.person)) if acc.reaches(item.person) else None
            entries.append(person_entry(look, acc, item, online, lines, mine))
        else:
            entries.append(contact_entry(look, acc, item))
    talk = len(talking)
    counts = {"talk": talk, "far": count(PERSON_KIND, visible) if who in (ALL, FAR) else 0,
              "orgs": count(ORG, visible) if who in (ALL, ORGS) else 0}
    chips = []
    if port is not None and who != TALK:
        everyone = total if not of else (len(talkers(look, q, links, matched)) if who == ALL else 0) + count(kind, None)
        chips.append({"label": "Tout le monde", "count": everyone, "on": not of,
                      "href": query_href(query, **{OF: ""})})
        for person in sorted(holding, key=lambda p: look.name(p).casefold()):
            chips.append({"label": f"Contacts {elided(look.name(person), 'de')}", "count": count(kind, acc.held(person)),
                          "on": of == person, "href": query_href(query, **{OF: person})})
        if acc.unowned():
            chips.append({"label": "À tout le monde", "count": count(kind, acc.unowned()), "on": of == EVERYONE,
                          "href": query_href(query, **{OF: EVERYONE})})
    return {"entries": entries, "total": total, "page": number, "pages": pages, "size": PAGE,
            "first": (number - 1) * PAGE + 1 if total else 0, "last": min(total, number * PAGE),
            "prev": query_href(query, page=str(number - 1)) if number > 1 else "",
            "next": query_href(query, page=str(number + 1)) if number < pages else "",
            "q": q, "who": who, "of": of, "counts": counts, "chips": chips if len(chips) > 1 else [],
            "table": query.get(SHOW) == TABLE,
            "modes": [{"label": "Fiches", "href": query_href(query, **{SHOW: ""}), "on": query.get(SHOW) != TABLE},
                      {"label": "Tableau", "href": query_href(query, **{SHOW: TABLE}), "on": query.get(SHOW) == TABLE}],
            "hidden": [(k, v) for k, v in ((WHO, who if who != ALL else ""), (OF, of), (SHOW, query.get(SHOW, "")))
                       if v]}


def _lines(port: Any, ids: Sequence[int]) -> list[ContactLine]:
    """Les fiches de l'annuaire reliées aux personnes de la page, lues comme une page (leurs identifiants, leurs
    comptes)."""
    if port is None or not ids:
        return []
    wanted = set(ids)
    return [c for c in take(lambda n, size: port.page(linked=True, page=n, size=size), 0, 1000) if c.id in wanted]


__all__ = ["ALL", "EVERYONE", "FAR", "OF", "ORGS", "PAGE", "SEARCH", "SHOW", "STYLES", "TABLE", "TALK", "WHO",
           "WHO_CHOICES", "Accounts", "Talker", "accounts", "contact_entry", "contact_url", "entry_ids", "listing",
           "merged", "person_entry", "place_name", "port_of", "short", "take", "talkers"]
