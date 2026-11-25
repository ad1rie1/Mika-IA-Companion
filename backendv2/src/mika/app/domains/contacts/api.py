"""Contacts, pour qui est connecté (ADR 0298) : ceux que Mika connaît pour elle — vus dans ses comptes Teams, ses
boîtes, sur son téléphone, ou dont elle lui a parlé — et leurs organisations ; la fiche d'un contact ; l'oublier.

- **Les siens** : un contact est à qui l'a fait connaître (``ports.contacts.visible_sources``) — vu dans un compte à
  elle ou qu'on lui partage, sur son téléphone, raconté par elle, ou par un compte qui n'est à personne (un compte à
  Mika). Un compte Teams ou une boîte est à qui ses paramètres journalisés le disent (``owners``, ``shares`` : la règle
  de Mail et de Teams, ``held_by``) ; le téléphone et ce qu'on raconte, à leur personne (``person_accounts``). Une
  fiche ne dit que ce qui en est visible (noms, poste, identifiants : le magasin le fait, ``visible=``), jamais de qui
  d'autre c'est le contact. Sa propre fiche (reliée à elle) n'est pas parmi ses contacts.
- **Ce qui l'identifie** : la sorte, la valeur, d'où elle le tient ; une clé du téléphone ou un nom raconté ne montrent
  jamais leur valeur (``OPAQUE_KINDS``) — ni comme identifiant, ni comme nom.
- **Où vous vous croisez** : ses conversations Teams dans tes comptes (``teams.written_in``), ses derniers mails dans
  tes boîtes, ses conversations de ton téléphone — seulement où tu lis : un compte à Mika se dit, sans y mener.
- **Ce que Mika en sait** : ce que l'annuaire tient (poste, service, organisation), puis ce qu'elle a tiré de ses
  derniers messages (lot 6, ``ContactsPort.notes``) — seulement les faits d'une vue que tu vois, chacun d'où il vient ;
  un fait d'un compte à toi s'oublie un à un (``POST /contacts/fact/forget``, l'action ``contacts.oublier_fait``,
  auditée ``moi.contacts.oublier_fait``), un fait d'un compte qu'on te partage ou à Mika non (403).
- **Oublier** (``moi.oublier.contact``) : permis quand tout ce que tu en vois vient de comptes à toi (jugé sur ce que
  tu vois, jamais sur le reste : la fiche ne laisse pas deviner qu'il est aussi le contact d'une autre). Si rien n'en
  vient d'ailleurs, c'est l'oubli de la console (``operations.forget_subject`` : la fiche et ses alias — ce que Teams,
  le courrier, le téléphone et sa mémoire en gardaient) ; sinon, seulement ce que l'annuaire tient de tes comptes
  (``ContactsPort.drop_places``) : ce qu'il est pour une autre ne change pas. La réponse est la même dans les deux cas.
  Une part qui vient d'un compte qu'on te partage ou d'un compte à Mika : 403, une opératrice l'oublie depuis la
  console.
- **Il lui parle aussi** (``linked``) : sa fiche est reliée à une personne qui a un compte ; ``talks`` dit si cette
  personne lui a écrit (« parle aussi à Mika ») ou n'a qu'un compte.
- **Sa photo** (ADR 0300) : celle de son profil Teams, gardée sous un compte Teams où tu lis (``photo`` : son adresse,
  ``GET …/teams/photo`` ; ``None`` sinon — un contact sans identifiant Teams garde ses initiales).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from starlette.routing import Route

from mika.app.domains.teams.api import photo_url
from mika.app.handmade.directory import Accounts, merged, take
from mika.app.me.api import Call, Denied, MeApiBase, done, form, missing
from mika.app.me.common import allows, held_by, millis
from mika.contracts import identity as identity_c
from mika.contracts import transcript as transcript_c
from mika.plugins import email as email_p
from mika.plugins import teams as teams_p
from mika.plugins.contacts.inspect import APP_WORDS, KIND, KIND_TITLES, contact_key
from mika.plugins.phone import app_name
from mika.ports.contacts import (
    COMPANY,
    EMAIL,
    MAIL,
    OPAQUE_KINDS,
    ORG,
    PERSON_KIND,
    PHONE,
    PHONE_APP,
    PHONE_SOURCE,
    TEAMS,
    TEAMS_ID,
    TENANT,
    TOLD,
    TOLD_NAME,
    ContactLine,
    ContactSheet,
    app_family,
    normalized,
    number_in_name,
    person_accounts,
)
from mika.ports.mail import MailQuery
from mika.ports.teams import conversation_key
from mika.runtime import operations
from mika.vocab.access import SELF, SHARE_USE

#: une page de contacts : au plus tant
PAGE_MAX = 100
#: ce qu'une ligne nomme de ses identifiants, au plus
IDS_SHOWN = 4
#: les contacts reliés à quelqu'un qui lui parle, lus d'un coup (ils sont peu : qui lui parle)
LINKED_MAX = 1000
#: les membres d'une organisation montrés sur sa fiche, au plus
MEMBERS_MAX = 50
#: où vous vous croisez : au plus tant de conversations Teams, d'adresses lues dans chaque boîte
TEAMS_PLACES, MAIL_ADDRESSES = 8, 4
#: les sortes d'une source, dans une ligne (l'icône que le client choisit, le mot qu'il dit)
SOURCE_LABELS = {TEAMS: "Teams", PHONE_SOURCE: "Téléphone", TOLD: "Raconté"}
#: ce que dit un oubli refusé : seulement ce que la fiche montre déjà (un compte qu'on te partage, un compte à Mika),
#: jamais qu'il serait aussi le contact de quelqu'un d'autre
NOT_ALL_YOURS = ("Une part de ce qu'elle en sait vient d'un compte qu'on te partage ou d'un de ses comptes à elle : "
                 "une opératrice peut l'oublier depuis la console.")
NOT_PLUGGED = "L'annuaire n'est pas branché."
NOT_YOUR_FACT = ("Ce fait vient d'un compte qui n'est pas à toi : elle l'a lu ailleurs que dans tes comptes. Une "
                 "opératrice peut l'oublier depuis la console.")
#: d'où vient un fait qu'elle a tiré de ses messages, en mots (« ses messages dans Teams »)
NOTE_FROM = {TEAMS: "ses messages dans Teams", PHONE_SOURCE: "ses messages sur ton téléphone"}


# ── à qui ──


@dataclass(frozen=True, slots=True)
class Reach:
    """Ce que qui est connecté voit de l'annuaire : les comptes de ses sources (``Accounts``), ceux dont elle voit les
    contacts, ceux qui sont à elle, ceux où elle lit (ses comptes Teams et ses boîtes, à elle ou partagés), et ses
    propres fiches (reliées à sa personne)."""

    accounts: Accounts
    visible: frozenset[tuple[str, str]]
    mine: frozenset[tuple[str, str]]
    readable: dict[str, dict[str, tuple[Any, str]]]
    selves: frozenset[int]
    #: combien de ses propres fiches sont dans chaque organisation (une organisation ne la compte pas parmi les siens)
    self_orgs: Counter[int] = field(default_factory=Counter)


def _port(call: Call) -> Any:
    port = call.port("contacts")
    if port is None:
        raise Denied(503, NOT_PLUGGED)
    return port


def reach(call: Call, port: Any) -> Reach:
    """À qui est chaque compte de ses sources : les comptes Teams et les boîtes selon leurs paramètres journalisés (ce
    que Mail et Teams lisent), le téléphone et ce qu'on raconte selon leur personne — et ce qu'en voit qui demande."""
    owner: dict[tuple[str, str], str] = {}
    label: dict[tuple[str, str], str] = {}
    shares: dict[tuple[str, str], dict[str, str]] = {}
    readable: dict[str, dict[str, tuple[Any, str]]] = {}
    for source, name, params_of in ((TEAMS, "teams", teams_p.params_of), (MAIL, "mail", email_p.params_of)):
        found = call.port(name)
        if found is None:
            continue
        params = params_of(call.frame)
        for a in found.accounts():
            owner[(source, a.key)] = params.owners.get(a.key, "")
            label[(source, a.key)] = a.name
            shares[(source, a.key)] = dict(params.shares.get(a.key, {}))
        readable[source] = held_by(call, found, params_of)
    owner.update(person_accounts(port.sources()))
    acc = Accounts(owner, label, shares, tuple(call.frame.get(identity_c.OWNERS) or ()))
    person = call.me.person
    visible = acc.visible(person)
    selves = frozenset(port.links().get(person, ()))
    orgs: Counter[int] = Counter()
    for cid in selves:
        sheet = port.sheet(cid, visible=visible) if visible else None
        if sheet is not None and sheet.org is not None:
            orgs[sheet.org.id] += 1
    return Reach(acc, visible, acc.held(person), readable, selves, orgs)


# ── ce qui se montre ──


def safe_name(name: str, identifiers: Sequence[tuple[str, str]]) -> str:
    """Son nom, jamais la valeur d'un identifiant qui ne se montre pas (une fiche sans nom vu le prend de son premier
    identifiant : une clé du téléphone, un nom raconté se disent alors en mots)."""
    hidden = {v for k, v in identifiers if k in OPAQUE_KINDS}
    if name and name not in hidden:
        return name
    shown = next((v for k, v in identifiers if k not in OPAQUE_KINDS), "")
    if shown:
        return shown
    app = next((v for k, v in identifiers if k == PHONE_APP), "")
    if app:
        return f"Contact {APP_WORDS.get(app_family(app), 'du téléphone')}"
    return "Quelqu'un dont tu lui as parlé" if any(k == TOLD_NAME for k, _ in identifiers) else "Sans nom"


def sources(places: Sequence[tuple[str, str, int]], apps: Sequence[tuple[str, int]],
            labels: dict[tuple[str, str], str]) -> list[dict[str, Any]]:
    """D'où elle le connaît, en étiquettes : Teams (tous tes comptes ensemble), chaque boîte sous son nom, le
    téléphone par appli (« WhatsApp », « SMS »), ce que tu lui as raconté — chacune avec combien de fois (0 : un
    profil seul, l'adresse d'une boîte)."""
    out: list[dict[str, Any]] = []
    teams = [n for s, _a, n in places if s == TEAMS]
    if teams:
        out.append({"source": TEAMS, "label": SOURCE_LABELS[TEAMS], "count": sum(teams)})
    boxes = sorted(((a, n) for s, a, n in places if s == MAIL), key=lambda an: (-an[1], an[0]))
    out += [{"source": MAIL, "account": a, "label": labels.get((MAIL, a), a), "count": n} for a, n in boxes]
    phone = [n for s, _a, n in places if s == PHONE_SOURCE]
    if phone:
        if apps:
            out += [{"source": family, "label": APP_WORDS.get(family, family), "count": n} for family, n in apps]
        else:
            out.append({"source": PHONE_SOURCE, "label": SOURCE_LABELS[PHONE_SOURCE], "count": sum(phone)})
    told = [n for s, _a, n in places if s == TOLD]
    if told:
        out.append({"source": TOLD, "label": SOURCE_LABELS[TOLD], "count": sum(told)})
    return out


def shown_value(kind: str, value: str, name: str) -> str:
    """La valeur d'un identifiant telle qu'elle se lit : une entreprise ou une organisation Teams est rangée repliée
    (``lumen conseil``) — celle qui porte le nom de la fiche se dit sous ce nom."""
    return name if kind in (COMPANY, TENANT) and name and normalized(kind, name) == value else value


def talks(call: Call, linked: str) -> bool:
    """La personne de l'identité à qui une fiche est reliée lui a-t-elle déjà écrit (« parle aussi à Mika ») ? Sinon,
    elle n'a qu'un compte."""
    if not linked:
        return False
    handles = tuple(call.frame.get(identity_c.HANDLES(linked)) or ()) or (linked,)
    return any(call.frame.get(transcript_c.LAST_FROM(h)) for h in handles)


def photos_for(call: Call, r: Reach, identifiers: Sequence[tuple[str, str]]) -> dict[str, str]:
    """Les photos de profil (ADR 0300) de ces identifiants Teams (``(sorte, valeur)`` : les autres sortes sont
    ignorées), gardées sous un compte Teams où tu lis : identifiant → son adresse. Une requête pour toute une page."""
    teams = call.port("teams")
    mine = sorted(r.readable.get(TEAMS, {}))
    ids = sorted({v for k, v in identifiers if k == TEAMS_ID})
    if teams is None or not mine or not ids:
        return {}
    return {person: photo_url(account, person, etag)
            for person, (account, etag) in teams.photos_of(ids, accounts=mine).items()}


def photo_of(identifiers: Sequence[tuple[str, str]], photos: Mapping[str, str]) -> str | None:
    """L'adresse de la photo d'un contact : celle de son premier identifiant Teams qui en a une (``None`` : aucune)."""
    return next((photos[v] for k, v in identifiers if k == TEAMS_ID and v in photos), None)


def line_json(c: ContactLine, r: Reach, person: str, call: Call | None = None,
              photos: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Un contact dans la liste : ce qu'en voit qui demande — jamais ses autres propriétaires. Son entreprise, quand
    c'est son nom même, n'est pas redite ; sa photo (ADR 0300), d'après ``photos`` (``photos_for``)."""
    shown = [{"kind": k, "value": shown_value(k, v, c.name)} for k, v in c.identifiers
             if k not in OPAQUE_KINDS and not (k == COMPANY and shown_value(k, v, c.name) == c.name)]
    return {"id": c.id, "kind": c.kind, "name": safe_name(c.name, c.identifiers), "title": c.title,
            "department": c.department,
            "organisation": {"id": c.org, "name": c.org_name} if c.org and c.org_name else None,
            "linked": bool(c.person) and c.person != person,
            "talks": bool(c.person) and c.person != person and call is not None and talks(call, c.person),
            "members": max(0, c.members - r.self_orgs.get(c.id, 0)) if c.kind == ORG else 0,
            "last": millis(c.last), "sources": sources(c.places, c.apps, r.accounts.label),
            "identifiers": shown[:IDS_SHOWN], "photo": photo_of(c.identifiers, photos or {})}


def _where(r: Reach, person: str, kind: str, source: str, account: str, count: int) -> str:
    """D'où elle tient un identifiant, en mots : Teams (son profil, pour l'e-mail ou le numéro qu'il dit), une boîte
    par son nom, ton téléphone, ce que tu lui as raconté."""
    if source == TEAMS:
        return "son profil Teams" if kind in (EMAIL, PHONE) and not count else "Teams"
    if source == MAIL:
        return r.accounts.label.get((MAIL, account), account)
    if source == PHONE_SOURCE:
        return "ton téléphone"
    if source == TOLD:
        return "ce qu'elle a appris d'elle-même" if account == SELF else "raconté par toi"
    return source


def identifiers_json(sheet: ContactSheet, r: Reach, person: str) -> list[dict[str, Any]]:
    """Ce qui l'identifie : chaque identifiant, sa sorte, sa valeur, d'où elle le tient. Un nom raconté n'est pas un
    moyen de le joindre (il n'y paraît pas) ; un contact du téléphone se dit par son appli et le nom que lui donne ton
    carnet, jamais par sa clé."""
    out = []
    for i in sheet.identifiers:
        if i.kind == TOLD_NAME:
            continue
        where = list(dict.fromkeys(_where(r, person, i.kind, x.source, x.account, x.count) for x in i.sightings))
        if i.kind == PHONE_APP:
            word = APP_WORDS.get(app_family(i.value), "")
            named = next((x.name for x in i.sightings if x.name and x.name != i.value), "")
            out.append({"kind": PHONE_APP, "label": f"Contact {word}" if word else KIND_TITLES[PHONE_APP],
                        "value": "", "name": named, "where": where, "generic": False})
            continue
        out.append({"kind": i.kind, "label": KIND_TITLES.get(i.kind, i.kind),
                    "value": shown_value(i.kind, i.value, sheet.name), "name": "",
                    "where": where, "generic": i.generic})
    return out


def note_from(r: Reach, source: str, account: str) -> str:
    """D'où vient un fait qu'elle a tiré de ses messages : « ses messages dans Teams », « ses mails à Pro » (la boîte
    sous son nom), « ses messages sur ton téléphone »."""
    if source == MAIL:
        return f"ses mails à {r.accounts.label.get((MAIL, account), account)}"
    return NOTE_FROM.get(source, source)


def notes_json(port: Any, sheet: ContactSheet, r: Reach) -> list[dict[str, Any]]:
    """Ce qu'elle a tiré de ses derniers messages (lot 6) : les faits d'une vue que tu vois, chacun d'où il vient,
    où il était, sa confiance (0 à 1), et s'il est à toi de l'oublier (un compte à toi : ``Reach.mine``)."""
    if sheet.kind == ORG:
        return []
    return [{"kind": "note", "id": n.id, "sort": n.kind, "label": "", "value": n.text,
             "confidence": round(n.confidence, 2), "from": note_from(r, n.source, n.account), "place": n.place,
             "at": millis(n.said_at or n.at), "forget": (n.source, n.account) in r.mine}
            for n in port.notes(sheet.id, visible=r.visible)]


def facts_json(call: Call, port: Any, sheet: ContactSheet, r: Reach) -> list[dict[str, Any]]:
    """Ce que Mika en sait : ce que l'annuaire tient — son poste et son service (ses profils Teams), son organisation
    (son adresse, ou ce que dit son profil) —, puis ce qu'elle a tiré de ses derniers messages (``notes_json``)."""
    out: list[dict[str, Any]] = []
    if sheet.title:
        out.append({"kind": "title", "label": "Poste", "value": sheet.title, "from": "son profil Teams"})
    if sheet.department:
        out.append({"kind": "department", "label": "Service", "value": sheet.department, "from": "son profil Teams"})
    if sheet.org is not None:
        org = port.sheet(sheet.org.id, visible=r.visible)
        domains = {i.value for i in org.identifiers if i.kind == "domain"} if org is not None else set()
        mails = {i.value.rpartition("@")[2] for i in sheet.identifiers if i.kind == EMAIL}
        by_address = any(m == d or m.endswith("." + d) for m in mails for d in domains)
        out.append({"kind": "organisation", "label": "Organisation", "value": sheet.org.name, "id": sheet.org.id,
                    "from": "son adresse e-mail" if by_address else "son profil Teams"})
    return out + notes_json(port, sheet, r)


def _teams_places(call: Call, sheet: ContactSheet, r: Reach) -> list[dict[str, Any]]:
    """Ses conversations Teams, dans les comptes où tu lis (à toi, ou qu'on te partage)."""
    teams = call.port("teams")
    mine = sorted(r.readable.get(TEAMS, {}))
    authors = [i.value for i in sheet.identifiers if i.kind == TEAMS_ID]
    if teams is None or not mine or not authors:
        return []
    return [{"source": TEAMS, "conversation": conversation_key(c.account, c.id), "account": c.account,
             "title": c.title, "kind": c.kind, "count": n, "last": millis(at)}
            for c, n, at in teams.written_in(authors, TEAMS_PLACES, accounts=mine)]


def _mail_places(call: Call, sheet: ContactSheet, r: Reach) -> list[dict[str, Any]]:
    """Ses mails, boîte par boîte, dans celles où tu lis : combien elle en a vu, le dernier reçu de lui (une personne
    par ses adresses ; une organisation aussi par ses adresses génériques)."""
    port = call.port("mail")
    mine = r.readable.get(MAIL, {})
    if port is None or not mine:
        return []
    seen: dict[str, list[int]] = {}
    addresses: dict[str, list[str]] = {}
    for i in sheet.identifiers:
        if i.kind != EMAIL or (i.generic and sheet.kind != ORG):
            continue
        for x in i.sightings:
            if x.source == MAIL and x.account in mine:
                got = seen.setdefault(x.account, [0, 0])
                got[0], got[1] = got[0] + x.count, max(got[1], x.last)
                addresses.setdefault(x.account, []).append(i.value)
    out = []
    for box, (count, last) in seen.items():
        latest = None
        for address in list(dict.fromkeys(addresses[box]))[:MAIL_ADDRESSES]:
            got = port.messages_page(MailQuery(accounts=(box,), sender=address), 1, 1).items
            if got and (latest is None or got[0].date > latest.date):
                latest = got[0]
        out.append({"source": MAIL, "box": box, "box_name": r.accounts.label.get((MAIL, box), box), "count": count,
                    "last": millis(max(last, latest.date if latest is not None else 0)),
                    "ref": latest.ref if latest is not None else "",
                    "subject": (latest.subject or "") if latest is not None else ""})
    return out


def _phone_places(sheet: ContactSheet, person: str) -> list[dict[str, Any]]:
    """Ses conversations de ton téléphone (ce que l'application en a lu) : un tête-à-tête sous son nom, un groupe sous
    le sien ; la clé que l'écran Téléphone ouvre (``<appli>|<fil>``)."""
    out = []
    for i in sheet.identifiers:
        if i.kind != PHONE_APP:
            continue
        app = i.value.partition(":")[0]
        for x in i.sightings:
            if x.source != PHONE_SOURCE or x.account != person:
                continue
            for t in x.threads:
                out.append({"source": PHONE_SOURCE, "conversation": f"{app}|{t.key}", "app": app,
                            "app_name": app_name(app), "title": t.title if t.group else "", "group": t.group,
                            "count": t.count, "last": millis(t.last)})
    return out


def places_json(call: Call, sheet: ContactSheet, r: Reach) -> list[dict[str, Any]]:
    """Où vous vous croisez, le plus récent d'abord."""
    found = [*_teams_places(call, sheet, r), *_mail_places(call, sheet, r), *_phone_places(sheet, call.me.person)]
    return sorted(found, key=lambda p: -p["last"])


def members_json(port: Any, sheet: ContactSheet, r: Reach, call: Call | None = None) \
        -> tuple[list[dict[str, Any]], int]:
    """Ses personnes parmi tes contacts (une organisation), les dernières vues d'abord, chacune avec sa photo (ADR
    0300, comme une ligne) ; combien en tout."""
    if sheet.kind != ORG:
        return [], 0
    got = port.page(visible=r.visible, kind=PERSON_KIND, org=sheet.id, size=MEMBERS_MAX)
    shown = [c for c in got.items if c.id not in r.selves]
    photos = photos_for(call, r, [i for c in shown for i in c.identifiers]) if call is not None else {}
    items = [{"id": c.id, "name": safe_name(c.name, c.identifiers), "title": c.title, "department": c.department,
              "last": millis(c.last), "linked": bool(c.person),
              "talks": bool(c.person) and call is not None and talks(call, c.person),
              "photo": photo_of(c.identifiers, photos)}
             for c in shown]
    return items, max(0, got.total - r.self_orgs.get(sheet.id, 0))


def _places(sheet: ContactSheet | None) -> set[tuple[str, str]]:
    return {(x.source, x.account) for i in sheet.identifiers for x in i.sightings} if sheet is not None else set()


def forgettable(sheet: ContactSheet, r: Reach) -> bool:
    """Tout ce que tu en vois vient-il de comptes à toi (à ton nom, « à toi », ton téléphone, ce que tu lui as
    raconté) ? Jugé sur ce que tu vois seulement (``sheet`` : lu pour toi) : rien ne dit ici s'il est vu ailleurs."""
    places = _places(sheet)
    return bool(places) and places <= r.mine


def whole_is_yours(port: Any, cid: int, r: Reach) -> bool:
    """Tout ce qu'elle en a vu, la fiche entière, vient-il de comptes à toi ? Alors l'oublier l'oublie pour tout le
    monde ; sinon, seule ta part s'efface (``forget``). Jamais dit à qui demande."""
    places = _places(port.sheet(cid))
    return bool(places) and places <= r.mine


def _writer(call: Call, sheet: ContactSheet, r: Reach) -> dict[str, str] | None:
    """À qui écrire, si tu as une boîte qui envoie : sa première adresse (pas une adresse générique)."""
    address = next((i.value for i in sheet.identifiers if i.kind == EMAIL and not i.generic), "")
    sends = any(allows(level, SHARE_USE) and getattr(a, "can_send", False)
                for a, level in r.readable.get(MAIL, {}).values())
    return {"address": address, "name": sheet.name} if address and sends else None


# ── lire ──


def _query(call: Call) -> str:
    """Ce qu'on cherche : un nom, un e-mail, un numéro (« 06 71 20 33 58 » se cherche comme il se range, en E.164)."""
    q = " ".join(call.arg("q", limit=200).split())
    number = number_in_name(q)
    return number.lstrip("+") if number else q


def _kind(call: Call) -> str | None:
    kind = call.arg("kind", limit=20)
    if kind not in ("", PERSON_KIND, ORG):
        raise Denied(400, "« kind » : person ou org.", {"kind": "person ou org"})
    return kind or None


async def listing(call: Call) -> dict[str, Any]:
    """Ses contacts, le dernier vu d'abord : personnes et organisations, qui lui parlent aussi comprises (lues d'un
    coup : elles sont peu), les autres par pages ; ce qu'on cherche, la sorte ; combien de chaque sorte (sans la
    recherche, comme les choix de l'écran)."""
    port = _port(call)
    r = reach(call, port)
    q, kind = _query(call), _kind(call)
    number, size = call.number("page", 1), call.number("size", 50, high=PAGE_MAX)
    person = call.me.person
    if not r.visible:
        return {"total": 0, "page": 1, "size": size, "counts": {"all": 0, "person": 0, "org": 0}, "items": []}

    def linked(k: str | None, text: str) -> list[ContactLine]:
        if k == ORG:
            return []  # une organisation n'est jamais reliée
        got = take(lambda n, s: port.page(visible=r.visible, q=text, kind=k, page=n, size=s, linked=True), 0,
                   LINKED_MAX)
        return [c for c in got if c.id not in r.selves]

    def far(k: str | None, text: str) -> Any:
        return lambda n, s: port.page(visible=r.visible, q=text, kind=k, page=n, size=s, linked=False)

    talking = linked(kind, q)
    total_far = far(kind, q)(1, 1).total
    total = len(talking) + total_far
    pages = max(1, -(-total // size))
    number = min(number, pages)
    window = merged(talking, far(kind, q), total_far, (number - 1) * size, size) if total else []
    people = len(talking) if not q and kind == PERSON_KIND else len(linked(PERSON_KIND, ""))
    persons = far(PERSON_KIND, "")(1, 1).total + people
    orgs = far(ORG, "")(1, 1).total
    photos = photos_for(call, r, [i for c in window for i in c.identifiers])
    return {"total": total, "page": number, "size": size,
            "counts": {"all": persons + orgs, "person": persons, "org": orgs},
            "items": [line_json(c, r, person, call, photos) for c in window]}


def _id(call: Call) -> int:
    raw = call.arg("id", limit=20).strip()
    return int(raw) if raw.isdigit() else 0


def _sheet(call: Call, port: Any, r: Reach) -> ContactSheet:
    """Un de ses contacts, réduit à ce qu'elle en voit — sinon introuvable (le même 404 qu'un contact inconnu)."""
    cid = _id(call)
    sheet = port.sheet(cid, visible=r.visible) if cid and r.visible and cid not in r.selves else None
    if sheet is None:
        raise missing()
    return sheet


def _privacy(sheet: ContactSheet, r: Reach) -> str:
    """D'où vient ce qu'elle en sait : de tes comptes seuls (``mine`` : elle n'en parle qu'à toi), ou aussi de comptes
    qu'on te partage ou qui sont à Mika (``shared``)."""
    places = {(x.source, x.account) for i in sheet.identifiers for x in i.sightings}
    return "mine" if places <= r.mine else "shared"


async def fiche(call: Call) -> dict[str, Any]:
    """La fiche d'un de ses contacts : ce qui l'identifie, ce que Mika en sait, où vous vous croisez, ses personnes
    (une organisation), ce qu'on peut faire (écrire, sa conversation Teams, celle du téléphone, l'oublier)."""
    port = _port(call)
    r = reach(call, port)
    sheet = _sheet(call, port, r)
    person = call.me.person
    idents = [(i.kind, i.value) for i in sheet.identifiers]
    places = places_json(call, sheet, r)
    members, members_total = members_json(port, sheet, r, call)
    seen = [(x.source, x.account, x.count) for i in sheet.identifiers if not i.generic for x in i.sightings]
    apps: dict[str, int] = {}
    for i in sheet.identifiers:
        family = app_family(i.value) if i.kind == PHONE_APP else ""
        if family:
            apps[family] = apps.get(family, 0) + sum(x.count for x in i.sightings)
    by_place: dict[tuple[str, str], int] = {}
    for source, account, n in seen:
        by_place[(source, account)] = by_place.get((source, account), 0) + n
    firsts = [x.first for i in sheet.identifiers for x in i.sightings if x.first]
    lasts = [x.last for i in sheet.identifiers for x in i.sightings if x.last]
    dm = next((p for p in places if p["source"] == TEAMS and p["kind"] == "dm"), None) or \
        next((p for p in places if p["source"] == TEAMS), None)
    phone = next((p for p in places if p["source"] == PHONE_SOURCE), None)
    allowed = forgettable(sheet, r)
    photo = photo_of(idents, photos_for(call, r, idents))
    return {"id": sheet.id, "kind": sheet.kind, "name": safe_name(sheet.name, idents), "title": sheet.title,
            "department": sheet.department,
            "organisation": {"id": sheet.org.id, "name": sheet.org.name} if sheet.org is not None else None,
            "linked": bool(sheet.person) and sheet.person != person,
            "talks": bool(sheet.person) and sheet.person != person and talks(call, sheet.person),
            "sources": sources([(s, a, n) for (s, a), n in sorted(by_place.items())], sorted(apps.items()),
                               r.accounts.label),
            "first": millis(min(firsts, default=0)), "last": millis(max(lasts, default=0)),
            "identifiers": identifiers_json(sheet, r, person), "facts": facts_json(call, port, sheet, r),
            "places": places, "members": members, "members_total": members_total,
            "write": _writer(call, sheet, r), "teams": dm["conversation"] if dm else "",
            "message": phone["conversation"] if phone else "", "privacy": _privacy(sheet, r),
            "forget": {"allowed": allowed, "reason": "" if allowed else NOT_ALL_YOURS}, "photo": photo}


# ── oublier ──


async def forget(call: Call) -> dict[str, Any]:
    """Oublier un de ses contacts, quand tout ce qu'elle en voit vient de comptes à elle : s'il ne vient de rien
    d'autre, ce que Teams, le courrier, le téléphone et sa mémoire en gardaient s'efface, comme depuis la console (la
    fiche et ses alias) ; s'il est aussi vu ailleurs, seulement ce que l'annuaire tient de ses comptes — la réponse est
    la même (rien ne dit à qui demande qu'il était aussi le contact d'une autre). Audité."""
    port = _port(call)
    r = reach(call, port)
    sheet = _sheet(call, port, r)
    if not forgettable(sheet, r):
        raise Denied(403, NOT_ALL_YOURS)
    name = safe_name(sheet.name, [(i.kind, i.value) for i in sheet.identifiers])
    key = contact_key(sheet.id)
    if whole_is_yours(port, sheet.id, r):
        await operations.forget_subject(call.kernel, KIND, key, by=call.me.handle, action="moi.oublier.contact")
    else:  # aussi vu ailleurs : sa part seulement
        port.drop_places(sheet.id, r.mine)
        await operations.audit(call.kernel, "moi.oublier.contact", by=call.me.handle, subject_kind=KIND, subject=key)
    return {"ok": True, "message": f"« {name} » est oublié·e : ce n'est plus un de tes contacts."}


async def forget_fact(call: Call) -> dict[str, Any]:
    """Oublier un fait qu'elle a tiré de ses messages (lot 6), seulement s'il vient d'un compte à toi : il part, et ne
    se réapprend pas — l'action de la console (``contacts.oublier_fait``), auditée depuis ton espace. Un fait que tu ne
    vois pas n'existe pas (404) ; vu par un compte qu'on te partage, ou à Mika : 403."""
    port = _port(call)
    r = reach(call, port)
    nid = _id(call)
    note = port.note(nid) if nid else None
    if note is None or (note.source, note.account) not in r.visible or note.contact in r.selves \
            or port.sheet(note.contact, visible=r.visible) is None:
        raise missing()
    if (note.source, note.account) not in r.mine:
        raise Denied(403, NOT_YOUR_FACT)
    return done(await call.act("contacts.oublier_fait", form(fixed={"fait": str(note.id)}),
                               subject=contact_key(note.contact)), id=note.id)


def routes(api: MeApiBase) -> list[Route]:
    return [api.route("/contacts", listing), api.route("/contacts/fiche", fiche),
            api.route("/contacts/forget", forget, write=True),
            api.route("/contacts/fact/forget", forget_fact, write=True)]


__all__ = ["Reach", "facts_json", "fiche", "forget", "forget_fact", "forgettable", "identifiers_json", "line_json",
           "listing", "note_from", "notes_json", "photo_of", "photos_for", "reach", "routes", "safe_name", "sources",
           "talks", "whole_is_yours"]
