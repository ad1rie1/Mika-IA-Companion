"""La console de l'annuaire (ADR 0298) : la fiche d'un contact — une personne connue de loin, ou une organisation —, ses
onglets, l'onglet « Contacts » de la fiche d'une personne, et les gestes d'une opératrice.

- **La fiche** (``contact``, sa clé ``contact:<n°>``, le sujet même de son oubli) : son nom, connue de loin ou
  organisation, son organisation, à qui elle est reliée ; ses onglets — ses personnes (une organisation), ce qui
  l'identifie (chaque identifiant, sa sorte, où elle l'a vu, et « Détacher »), où elle la voit (chaque compte, combien,
  quand). La page dessinée (``app/handmade/subjects/contact.py``) lit le port elle-même ; ces vues restent la source
  pour la console en MCP et pour le repli bloc par bloc.
- **Oublier** est l'oubli de la console (la fiche est « oubliable ») : sa clé et ses alias — ses identifiants Teams et
  ses adresses, ``teams:<id>`` et ``mail:<adresse>``, ses clés d'expéditeur du téléphone (``phone:<empreinte>:<nom>``,
  retrouvées dans le journal) et les noms sous lesquels on lui en a parlé (``name:…``) — atteignent aussi ce que Teams,
  le courrier, le téléphone et sa mémoire gardaient d'elle (ADR 0298 : oublier la personne atteint ce qu'elle a lu
  d'elle). Jamais ce qui est à une personne qui lui parle — un de ses moyens de communication, qu'elle soit reliée à la
  fiche ou non, un nom que l'identité relie à elle : celle-là s'oublie sur sa propre fiche.
- **Les gestes** (des actions d'opératrice, auditées comme toutes) : réunir deux fiches, ou relier une fiche à une
  personne qui lui parle (« Réunir avec… ») ; l'en délier ; détacher un identifiant réuni par erreur ; et, depuis la
  file « À valider » (Rapprochements), dire de deux fiches au même nom qu'elles sont la même personne, ou deux. Une
  fiche qui n'est qu'un nom raconté se relie à une personne par l'identité (« C'est la personne dont on lui a
  parlé », ``identity.name_bound``) : sa mémoire le sait aussi, et la collecte relie la fiche — « Réunir avec… » une
  personne y mène, le formulaire déjà rempli.
- **À qui est un contact** se lit sur le propriétaire des comptes de ses vues, que les ports ``teams`` et ``mail``
  disent (``visible_sources``). Les partages sont rangés dans les réglages des comptes : la page dessinée les lit,
  pas ces vues — l'onglet « Contacts » d'une personne, ici, ne compte que ses comptes et ceux qui ne sont à personne.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Column,
    Found,
    Head,
    InspectContext,
    Note,
    Pager,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    When,
    agree,
    paginate,
    plural,
)
from mika.kernel.operate import Done, Refused
from mika.plugins.contacts import CONTACTS, ContactsState
from mika.ports.contacts import (
    COMPANY,
    CONTACT_PREFIX,
    DOMAIN,
    EMAIL,
    MAIL,
    MAIL_PREFIX,
    NAME_PREFIX,
    ORG,
    PHONE,
    PHONE_APP,
    PHONE_PREFIX,
    PHONE_SOURCE,
    SMS,
    TEAMS,
    TEAMS_ID,
    TEAMS_PREFIX,
    TENANT,
    TOLD,
    TOLD_NAME,
    WHATSAPP,
    ContactSheet,
    app_family,
    person_accounts,
    subject_aliases,
    visible_sources,
)
from mika.ports.paging import page_slice
from mika.vocab.access import SELF

KIND = "contact"
#: la sorte d'un identifiant, en tête de sa tuile (« Identifiant Teams ») et en ligne (« e-mail »)
KIND_TITLES = {TEAMS_ID: "Identifiant Teams", EMAIL: "E-mail", PHONE: "Téléphone", DOMAIN: "Domaine",
               COMPANY: "Entreprise", TENANT: "Organisation Teams", PHONE_APP: "Contact du téléphone",
               TOLD_NAME: "Nom raconté"}
KIND_WORDS = {TEAMS_ID: "Teams", EMAIL: "e-mail", PHONE: "téléphone", DOMAIN: "domaine", COMPANY: "entreprise",
              TENANT: "organisation Teams", PHONE_APP: "contact du téléphone", TOLD_NAME: "nom raconté"}
#: une source, en mots
SOURCE_WORDS = {TEAMS: "Teams", MAIL: "Courrier", PHONE_SOURCE: "Téléphone", TOLD: "Racontée"}
#: une famille d'applis du téléphone, en mots (« WhatsApp · 3 »)
APP_WORDS = {WHATSAPP: "WhatsApp", SMS: "SMS"}


def app_word(value: str) -> str:
    """L'appli d'un expéditeur du téléphone, en mots (« WhatsApp », « SMS ») ; « Téléphone » pour une autre."""
    return APP_WORDS.get(app_family(value), SOURCE_WORDS[PHONE_SOURCE])
#: ses vues et ses membres : tant par page
PAGE = 50
NO_PORT = "L'annuaire n'est pas branché (le port « contacts »)."
#: le paramètre de la fiche d'une personne qui y pose le formulaire « C'est la personne dont on lui a parlé » de
#: l'identité, pré-rempli de ce nom (``?nom=name:…`` : celui de la file « À valider »)
NAMING_PARAM = "nom"


def contact_key(contact: int) -> str:
    """La clé de la fiche d'un contact : le sujet de son oubli (``contact:<n°>``)."""
    return f"{CONTACT_PREFIX}{int(contact)}"


def contact_id(key: str) -> int:
    """Le numéro d'un contact d'après la clé de sa fiche (0 : ce n'en est pas une)."""
    rest = (key or "").strip().removeprefix(CONTACT_PREFIX)
    return int(rest) if rest.isdigit() and len(rest) < 18 else 0


def contact_ref(contact: int, text: str, tab: str = "") -> Ref:
    return Ref.subject(KIND, contact_key(contact), text, tab)


def name_of(frame: Frame, person: str) -> str:
    """Le nom d'une personne de l'identité (sa clé à défaut)."""
    return frame.get(identity_c.IDENTITY(person)).name or person


def aliases_of(sheet: ContactSheet, theirs: Sequence[str] = (), store: Any = None,
               frame: Frame | None = None) -> tuple[str, ...]:
    """Ce que son oubli atteint en plus de sa fiche : ses identifiants Teams et ses adresses (``teams:<id>``,
    ``mail:<adresse>``), les noms sous lesquels on lui en a parlé (``name:…``), ses clés d'expéditeur du téléphone
    (``phone:<empreinte>:<nom>``, telles que le journal les nomme : ``store.subjects``) — jamais ce qui est à une
    personne qui lui parle : ses moyens de communication (``theirs`` pour celle à qui la fiche est reliée ; pour
    toute autre, l'identité les connaît : ``frame``), un nom que l'identité relie à elle. Celle-là s'oublie sur sa
    fiche à elle : oublier une fiche de l'annuaire ne l'ampute pas."""
    out = subject_aliases(((i.kind, i.value) for i in sheet.identifiers),
                          store.subjects if store is not None else None)
    mine = set(theirs)
    return tuple(a for a in dict.fromkeys(out) if a not in mine and not (frame is not None and talks_by(frame, a)))


def talks_by(frame: Frame, alias: str) -> bool:
    """Ce sujet est-il à une personne qui lui parle : un de ses moyens de communication (l'identité le connaît), un
    nom que l'identité relie à une personne (« C'est la personne dont on lui a parlé ») ?"""
    if alias.startswith(NAME_PREFIX):
        person = frame.get(identity_c.PERSON(alias)) or alias
        return bool(person) and person != alias and not person.startswith((NAME_PREFIX, PHONE_PREFIX))
    if alias.startswith((TEAMS_PREFIX, MAIL_PREFIX)):
        view = frame.get(identity_c.IDENTITY(alias))
        return bool(getattr(view, "known", False))
    return False


def _port(ctx: Any) -> Any:
    port = ctx.ports.get("contacts") if ctx.ports is not None else None
    if port is None:
        raise Refused(NO_PORT)
    return port


def _sheet(ctx: InspectContext) -> tuple[Any, ContactSheet | None]:
    port = ctx.ports.get("contacts")
    cid = contact_id(ctx.subject)
    return port, (port.sheet(cid) if port is not None and cid else None)


def seen_count(sheet: ContactSheet) -> int:
    """Combien de fois elle l'a vu (une adresse générique est comptée par le domaine de son organisation)."""
    return sum(x.count for i in sheet.identifiers if not i.generic for x in i.sightings)


def span_of(sheet: ContactSheet) -> tuple[int, int]:
    """La première et la dernière fois qu'elle l'a vu (0 : jamais daté)."""
    firsts = [x.first for i in sheet.identifiers for x in i.sightings if x.first]
    lasts = [x.last for i in sheet.identifiers for x in i.sightings if x.last]
    return min(firsts, default=0), max(lasts, default=0)


def accounts_of(ctx: Any) -> dict[tuple[str, str], str]:
    """Le propriétaire de chaque compte de ses sources (vide : ses propriétaires ; ``elle`` ; ``personne:<clé>``) : les
    comptes Teams et les boîtes, et ceux qui sont des personnes (le téléphone de quelqu'un, ce que quelqu'un lui a
    raconté : ``person_accounts``)."""
    out: dict[tuple[str, str], str] = {}
    for source, port in ((TEAMS, ctx.ports.get("teams")), (MAIL, ctx.ports.get("mail"))):
        for a in (port.accounts() if port is not None else ()):
            out[(source, a.key)] = a.owner or ""
    contacts = ctx.ports.get("contacts")
    out.update(person_accounts(contacts.sources() if contacts is not None else ()))
    return out


def account_name(ctx: Any, source: str, account: str, frame: Frame | None = None) -> str:
    """Un compte, nommé comme ses réglages le nomment (« Teams · Équipe », « Courrier · Atelier ») ; le téléphone de
    quelqu'un (« Téléphone · adrien »), ce que quelqu'un lui a raconté (« Racontée · adrien », « Racontée · elle-même »)."""
    word = SOURCE_WORDS.get(source, source)
    if source in (PHONE_SOURCE, TOLD):
        who = "elle-même" if account == SELF else name_of(frame, account) if frame is not None else account
        return f"{word} · {who}"
    port = ctx.ports.get("teams" if source == TEAMS else "mail" if source == MAIL else "")
    found = port.account(account) if port is not None else None
    return f"{word} · {found.name}" if found is not None else f"{word} · {account}"


# ── La fiche ──────────────────────────────────────────────────────────────


@CONTACTS.subject(KIND, label="Contact", plural="Contacts", forgettable=True, icon="☏")
def _head(s: ContactsState, frame: Frame, ctx: InspectContext, key: str) -> Head | None:
    port = ctx.ports.get("contacts")
    cid = contact_id(key)
    sheet = port.sheet(cid) if port is not None and cid else None
    if sheet is None:
        return None
    if sheet.kind == ORG:
        badges = [Badge("organisation", "info")]
        subtitle = f"Une organisation : {plural(len(sheet.members), 'personne', 'personnes')} qu'elle connaît de loin."
    elif sheet.person:
        badges = [Badge("lui parle aussi", "ok")]
        subtitle = f"Reliée à {name_of(frame, sheet.person)}, qui lui parle : ses identifiants restent ceux de l'annuaire."
    else:
        badges = [Badge("connue de loin", "muted")]
        subtitle = "Connue de loin : elle la lit, sans lui avoir jamais parlé."
    if sheet.org is not None:
        badges.append(Badge(sheet.org.name, "info"))
    first, last = span_of(sheet)
    facts: list[tuple[str, Any]] = [("identifiants", len(sheet.identifiers)), ("vue", seen_count(sheet)),
                                    ("pour la première fois", When(first) if first else "—"),
                                    ("la dernière fois", When(last) if last else "—")]
    if sheet.org is not None:
        facts.append(("organisation", contact_ref(sheet.org.id, sheet.org.name)))
    if sheet.person:
        facts.append(("reliée à", Ref.subject("person", sheet.person, name_of(frame, sheet.person))))
    theirs = tuple(frame.get(identity_c.HANDLES(sheet.person)) or ()) if sheet.person else ()
    return Head(key=contact_key(sheet.id), title=sheet.name or contact_key(sheet.id), subtitle=subtitle,
                badges=tuple(badges), facts=tuple(facts),
                aliases=(contact_key(sheet.id), *aliases_of(sheet, theirs, ctx.store, frame)))


@CONTACTS.search(KIND)
def _search(s: ContactsState, frame: Frame, ctx: InspectContext, text: str, limit: int) -> list[Found]:
    port = ctx.ports.get("contacts")
    if port is None:
        return []
    offset = max(0, ctx.int_param("_offset", 0))
    got = page_slice(lambda number, size: port.page(q=text, page=number, size=size), offset, max(1, limit))
    out = []
    for c in got:
        said = "organisation" if c.kind == ORG else c.org_name or next(
            (f"{KIND_WORDS.get(k, k)} {v}" for k, v in c.identifiers if k not in (PHONE_APP, TOLD_NAME)), "") or next(
            (app_word(v) if k == PHONE_APP else KIND_WORDS[k] for k, v in c.identifiers), "")
        out.append(Found(contact_key(c.id), c.name or contact_key(c.id), said))
    return out


@CONTACTS.inspect("membres", title="Personnes", subject=KIND, order=5,
                  description="Les personnes de cette organisation qu'elle connaît de loin.")
def _members(s: ContactsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port, sheet = _sheet(ctx)
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    if sheet is None:
        return [Note("Ce contact n'existe plus.", tone="muted")]
    if sheet.kind != ORG:
        return [Note("Une personne n'a pas de membres : c'est une organisation qui en a.", tone="muted")]
    page, pager = paginate(list(sheet.members), ctx.pager(size=PAGE))
    return [Table((Column("personne", role="title"),), tuple(Row((contact_ref(m.id, m.name),),
                                                                 href=contact_ref(m.id, "")) for m in page),
                  title="Ses personnes", pager=pager, empty="aucune personne connue de cette organisation")]


@CONTACTS.inspect("identifiants", title="Ce qui l'identifie", subject=KIND, order=10,
                  description="Chacun de ses identifiants : sa sorte, où elle l'a vu, depuis quand ; un identifiant "
                              "réuni par erreur se détache.")
def _identifiers(s: ContactsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port, sheet = _sheet(ctx)
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    if sheet is None:
        return [Note("Ce contact n'existe plus.", tone="muted")]
    rows = []
    for i in sheet.identifiers:
        where = " ; ".join(f"{account_name(ctx, x.source, x.account, frame)}"
                           + (f" · {x.count} fois" if x.count else "") for x in i.sightings)
        first = min((x.first for x in i.sightings if x.first), default=0)
        detail = () if i.kind in (DOMAIN, COMPANY, TENANT) else (
            ActionSlot("contacts.detacher", (("identifiant", str(i.id)),), title="Détacher"),)
        shown = (i.sightings[0].name if i.sightings and i.sightings[0].name else i.value) \
            if i.kind in (PHONE_APP, TOLD_NAME) else i.value
        rows.append(Row((KIND_TITLES.get(i.kind, i.kind), Text(shown, "mono"),
                         "adresse sans personne derrière" if i.generic else where or "—",
                         When(first) if first else "—"), detail=detail))
    names = tuple((n,) for n in sheet.names)
    return [Stats((Stat(agree(len(sheet.identifiers), "identifiant", "identifiants"), len(sheet.identifiers)),
                   Stat(agree(len(sheet.names), "nom vu", "noms vus"), len(sheet.names)))),
            Table(("sorte", "valeur", "vu dans", "depuis"), tuple(rows), title="Ses identifiants",
                  empty="aucun identifiant"),
            Table(("nom",), names, title="Ses noms", empty="aucun nom vu"),
            Note("Un identifiant réuni par erreur se détache (« Détacher ») ; une autre fiche s'y réunit par « Réunir "
                 "avec… ». Un même nom seul ne réunit jamais : il se propose dans À valider › Rapprochements.",
                 tone="muted")]


@CONTACTS.inspect("vues", title="Où elle la voit", subject=KIND, order=20,
                  description="Chaque compte où elle l'a vu : combien de fois, la première et la dernière fois, sous "
                              "quel nom.")
def _places(s: ContactsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port, sheet = _sheet(ctx)
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    if sheet is None:
        return [Note("Ce contact n'existe plus.", tone="muted")]
    rows = [Row((account_name(ctx, x.source, x.account, frame),
                 Text(app_word(i.value) if i.kind == PHONE_APP else KIND_WORDS[TOLD_NAME] if i.kind == TOLD_NAME
                      else f"{KIND_WORDS.get(i.kind, i.kind)} {i.value}", "mono"),
                 x.count, When(x.first) if x.first else "—", When(x.last) if x.last else "—", x.name or "—"))
            for i in sheet.identifiers for x in i.sightings]
    rows.sort(key=lambda r: -(r.cells[4].at if isinstance(r.cells[4], When) else 0))
    page, pager = paginate(rows, ctx.pager(size=PAGE))
    return [Table(("compte", "identifiant", "fois", "la première", "la dernière", "sous le nom"), tuple(page),
                  title="Où elle la voit", pager=pager, empty="nulle part encore")]


@CONTACTS.inspect("savoir", title="Ce qu'elle en sait", subject=KIND, order=15,
                  description="Ce qu'elle a compris de cette personne en lisant ses derniers messages (le rôle « "
                              "portrait ») : chaque fait, d'où il vient, sa confiance ; un fait s'oublie un à un.")
def _knows(s: ContactsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port, sheet = _sheet(ctx)
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    if sheet is None:
        return [Note("Ce contact n'existe plus.", tone="muted")]
    notes = port.notes(sheet.id)
    rows = tuple(Row((n.text, account_name(ctx, n.source, n.account, frame), n.place or "—",
                      f"{round(n.confidence * 100)} %", When(n.at) if n.at else "—"),
                     detail=(ActionSlot("contacts.oublier_fait", (("fait", str(n.id)),), title="Oublier"),))
                 for n in notes)
    done = port.portraits(contacts={sheet.id})
    return [Stats((Stat(agree(len(notes), "fait", "faits"), len(notes)),
                   Stat(agree(len(done), "portrait", "portraits"), len(done)))),
            Table(("fait", "lu dans", "où", "confiance", "appris"), rows, title="Ce qu'elle en sait",
                  empty="rien encore : elle ne relit que qui échange vraiment avec un compte"),
            Note("Chaque fait vient de ses derniers messages dans un compte : il ne se dit qu'à qui voit ce compte. "
                 "Un fait oublié ne se réapprend pas, même reformulé.", tone="muted")]


# ── Sur la fiche d'une personne : ses contacts ────────────────────────────


@CONTACTS.inspect("contacts", title="Contacts", subject="person", order=22,
                  description="Ceux que ses comptes lui ont fait connaître (son Teams, ses boîtes), et ceux qu'elle lit "
                              "sans le compte de personne : ce qu'elle en a lu se dit à cette personne.")
def _person_contacts(s: ContactsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("contacts")
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    visible = visible_sources(ctx.subject, owners=tuple(frame.get(identity_c.OWNERS) or ()),
                              accounts=accounts_of(ctx))
    pager = ctx.pager(size=PAGE)
    got = port.page(visible=visible, linked=False, page=pager.number, size=min(pager.size, 100))
    rows = tuple(Row((contact_ref(c.id, c.name), "organisation" if c.kind == ORG else "connue de loin",
                      contact_ref(c.org, c.org_name) if c.org else "—",
                      ", ".join(SOURCE_WORDS.get(x, x) for x in c.sources) or "—", When(c.last) if c.last else "—"),
                     href=contact_ref(c.id, "")) for c in got.items)
    return [Table(("contact", "sorte", "organisation", "vu dans", "la dernière fois"), rows,
                  title="Ses contacts", pager=Pager(param=pager.param, number=got.number, size=got.size,
                                                    total=got.total),
                  empty="ses comptes ne lui ont fait connaître personne"),
            Note("Les partages de ses comptes sont lus par la fiche dessinée (ils sont rangés dans les réglages des "
                 "comptes).", tone="muted")]


# ── Les gestes ────────────────────────────────────────────────────────────


class NoArgs(BaseModel):
    pass


class MergeArgs(BaseModel):
    fiche: Annotated[str, Knob(label="Une autre fiche", widget="subject", subject=KIND, advanced=False, order=10,
                               help="Elle rejoint celle-ci : ses identifiants, ses vues, ses membres.")] = ""
    personne: Annotated[str, Knob(label="Ou la personne qui lui parle", widget="subject", subject="person",
                                  advanced=False, order=20,
                                  help="Reliée, elle paraît dans l'annuaire comme cette personne ; ses identifiants "
                                       "restent ceux de l'annuaire.")] = ""


class DetachArgs(BaseModel):
    identifiant: Annotated[int, Knob(label="Identifiant", widget="hidden")] = Field(ge=1)


class FactArgs(BaseModel):
    fait: Annotated[int, Knob(label="Fait", widget="hidden")] = Field(ge=1)


class PairArgs(BaseModel):
    a: Annotated[int, Knob(label="Une fiche", widget="hidden")] = Field(ge=1)
    b: Annotated[int, Knob(label="L'autre fiche", widget="hidden")] = Field(ge=1)


def _this(ctx: Any) -> tuple[Any, ContactSheet]:
    port = _port(ctx)
    sheet = port.sheet(contact_id(ctx.subject))
    if sheet is None:
        raise Refused("Ce contact n'existe plus.")
    return port, sheet


def _linked(s: ContactsState, frame: Frame, key: str, ports: Any = None) -> bool:
    port = ports.get("contacts") if ports is not None else None
    sheet = port.sheet(contact_id(key)) if port is not None and contact_id(key) else None
    return sheet is not None and bool(sheet.person)


@CONTACTS.action("reunir", title="Réunir avec…", args=MergeArgs, emits=[], subject=KIND, order=10,
                 description="La même personne sous deux fiches : choisis l'autre fiche, qui rejoint celle-ci, ou la "
                             "personne qui lui parle à qui la relier. Un même nom seul ne réunit jamais d'office.")
async def _merge(s: ContactsState, frame: Frame, args: MergeArgs, ctx: Any) -> Done:
    port, sheet = _this(ctx)
    other, person = contact_id(args.fiche), args.personne.strip()
    if bool(other) == bool(person):
        raise Refused("Choisis l'une des deux : une autre fiche, ou la personne qui lui parle.",
                      {"fiche": "Une autre fiche, ou bien une personne (pas les deux)."})
    if person:
        if sheet.kind == ORG:
            raise Refused("Une organisation ne se relie pas à une personne.")
        told = [i.value for i in sheet.identifiers if i.kind == TOLD_NAME]
        if told and all(i.kind == TOLD_NAME for i in sheet.identifiers):
            # un nom raconté : c'est l'identité qui le relie (sa mémoire le saura), la collecte relie la fiche
            return Done(message=f"« {sheet.name} » est une personne dont on lui a parlé : confirme sur la fiche de "
                                f"{name_of(frame, person)} que c'est elle — ce qu'on lui en a dit s'y rattachera.",
                        go=Ref("subject", f"person/{person}", name_of(frame, person),
                               (("onglet", "synthese"), (NAMING_PARAM, told[0]))))
        if not port.link(sheet.id, person):
            raise Refused(f"« {sheet.name} » est déjà reliée à {name_of(frame, person)}.")
        return Done(message=f"« {sheet.name} » est reliée à {name_of(frame, person)} : dans l'annuaire, elle paraît "
                            "comme cette personne ; ses identifiants restent ceux de l'annuaire.")
    gone = port.sheet(other)
    if gone is None:
        raise Refused("Cette autre fiche n'existe plus.", {"fiche": "Choisis une fiche qui existe."})
    try:
        done = port.merge(sheet.id, other)
    except ValueError as exc:
        raise Refused(str(exc)[:1].upper() + str(exc)[1:] + ".") from None
    if not done:
        raise Refused("Rien à réunir : c'est la même fiche.")
    return Done(message=f"« {gone.name} » est réunie à « {sheet.name} ».")


@CONTACTS.action("delier", title="Délier de la personne", args=NoArgs, emits=[], subject=KIND, order=20,
                 available=_linked, confirm="Elle redeviendra une personne connue de loin dans l'annuaire.",
                 description="Cette fiche n'est pas la personne qui lui parle : elle redevient connue de loin.")
async def _unlink(s: ContactsState, frame: Frame, args: NoArgs, ctx: Any) -> Done:
    port, sheet = _this(ctx)
    if not sheet.person or not port.link(sheet.id, None):
        raise Refused("Elle n'est reliée à personne.")
    return Done(message=f"« {sheet.name} » n'est plus reliée à {name_of(frame, sheet.person)}.")


@CONTACTS.action("detacher", title="Détacher", args=DetachArgs, emits=[], subject=KIND, order=30, inline=True,
                 confirm="Cet identifiant fera une fiche à lui, avec ce qu'elle en a vu ; les deux ne se proposeront "
                         "plus l'une pour l'autre.",
                 description="Un identifiant réuni par erreur : il fait une fiche à lui.")
async def _detach(s: ContactsState, frame: Frame, args: DetachArgs, ctx: Any) -> Done:
    port, sheet = _this(ctx)
    found = next((i for i in sheet.identifiers if i.id == args.identifiant), None)
    if found is None:
        raise Refused("Cet identifiant n'est pas sur cette fiche.")
    try:
        new = port.detach(found.id)
    except ValueError as exc:
        raise Refused(str(exc)[:1].upper() + str(exc)[1:] + ".") from None
    if not new:
        raise Refused("Cet identifiant n'existe plus.")
    return Done(message=f"« {found.value} » est détaché de « {sheet.name} » : il a sa fiche.",
                go=contact_ref(new, found.value))


def _pair(ctx: Any, args: PairArgs) -> tuple[Any, ContactSheet, ContactSheet]:
    port = _port(ctx)
    a, b = port.sheet(args.a), port.sheet(args.b)
    if a is None or b is None or a.id == b.id:
        raise Refused("L'une de ces fiches n'existe plus : le rapprochement est parti.")
    return port, a, b


@CONTACTS.action("rapprocher", title="La même personne : réunir", args=PairArgs, emits=[], order=40, inline=True,
                 confirm="Les deux fiches n'en feront plus qu'une.",
                 description="Deux fiches au même nom sont la même personne : elles se réunissent, la plus vue garde "
                             "l'autre.")
async def _same(s: ContactsState, frame: Frame, args: PairArgs, ctx: Any) -> Done:
    port, a, b = _pair(ctx, args)
    keep, other = sorted((a, b), key=lambda x: (-seen_count(x), x.id))
    try:
        port.merge(keep.id, other.id)
    except ValueError as exc:
        raise Refused(str(exc)[:1].upper() + str(exc)[1:] + ".") from None
    return Done(message=f"« {other.name} » est réunie à « {keep.name} ».")


@CONTACTS.action("ecarter", title="Deux personnes différentes", args=PairArgs, emits=[], order=50, inline=True,
                 description="Deux fiches au même nom sont deux personnes : elles ne se proposeront plus.")
async def _apart(s: ContactsState, frame: Frame, args: PairArgs, ctx: Any) -> Done:
    port, a, b = _pair(ctx, args)
    port.dismiss(a.id, b.id)
    return Done(message=f"« {a.name} » et « {b.name} » sont deux personnes : elles ne se proposeront plus.")


@CONTACTS.action("oublier_fait", title="Oublier ce fait", args=FactArgs, emits=[], subject=KIND, order=35,
                 inline=True, confirm="Elle l'oublie ; elle ne le réapprendra pas, même dit autrement.",
                 description="Un fait qu'elle a tiré de ses messages, faux ou à ne pas garder : il part, et ne se "
                             "réapprend pas.")
async def _forget_fact(s: ContactsState, frame: Frame, args: FactArgs, ctx: Any) -> Done:
    port, sheet = _this(ctx)
    found = port.note(args.fait)
    if found is None or found.contact != sheet.id:
        raise Refused("Ce fait n'est plus sur cette fiche.")
    port.forget_note(found.id)
    return Done(message=f"Oublié : « {found.text} ».")


__all__ = ["APP_WORDS", "KIND", "KIND_TITLES", "KIND_WORDS", "SOURCE_WORDS", "account_name", "accounts_of",
           "aliases_of", "app_word", "contact_id", "contact_key", "contact_ref", "name_of", "seen_count", "span_of"]
