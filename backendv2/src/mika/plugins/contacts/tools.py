"""Ce qu'elle sait de ses contacts, quand elle parle à qui la source appartient (ADR 0298, lot 6) : ``contacts_lookup``.

- **Un outil, pas une section du prompt** : elle le demande quand la conversation en a besoin (« tu sais qui est
  Gilles ? »), plutôt que de porter l'annuaire à chaque réponse.
- **À qui** : seulement en tête-à-tête, avec une personne reconnue (``vocab.ownership.shared_with``) — jamais dans un
  salon, jamais à une inconnue, jamais quand elle travaille seule. Réservé à ses propriétaires (``owner_only``) : la
  famille « contacts » de Réglages › Droits peut l'ouvrir à d'autres.
- **Ce qu'il dit** : les fiches et les faits que la personne en face voit (``visible_sources`` sur les comptes de
  ses sources : les siens, son téléphone, ce qu'elle a raconté, et ce qui n'est à personne), jamais ce qui vient du
  compte d'un autre ; un compte qu'on lui partage n'y compte pas (le port des comptes ne dit pas les partages : le
  côté sûr). Tout ce qui vient d'ailleurs (un nom, un poste, un fait tiré d'un message) est rendu inerte et dit comme
  une donnée.
- **De quoi agir** (le 2026-11-22) : ses moyens de la joindre (e-mail, téléphone ; jamais un identifiant Teams ni une
  clé du téléphone), ses autres noms, combien de fois et quand elle l'a vue, les conversations où elle écrit (Teams :
  ``TeamsPort.written_in``, avec la référence du dernier message, que ``teams_read`` relit ; ses derniers mails, que
  ``email_read`` relit ; ses conversations du téléphone), chaque fait daté avec le message qui le fonde, la personne de
  l'identité à qui la fiche est reliée (seulement à ses propriétaires, qui la voient dans la console ; « te parle
  aussi » seulement si elle lui a écrit, sinon « a un compte »), et pour une
  organisation son domaine, ses adresses génériques et les personnes qu'elle y connaît.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Frame
from mika.plugins.contacts import BUNDLE, CONTACTS
from mika.plugins.contacts.inspect import accounts_of
from mika.plugins.contacts.portrait import mail_place, phone_place, teams_place
from mika.ports.contacts import (
    DOMAIN,
    EMAIL,
    MAIL,
    NOTES_MAX,
    ORG,
    PHONE,
    PHONE_APP,
    PHONE_SOURCE,
    SMS,
    TEAMS,
    TEAMS_ID,
    TOLD,
    WHATSAPP,
    ContactSheet,
    app_family,
    visible_sources,
)
from mika.ports.preprocess import inert
from mika.vocab.access import PERSON
from mika.vocab.episodes import Kind
from mika.vocab.ownership import shared_with
from mika.vocab.phrasebook import family, phrase

#: au plus tant de fiches dites d'un appel (les plus récemment vues)
SHOWN = 3
#: au plus tant de faits par vue d'une fiche : la fiche entière qu'un portrait rend (ADR 0303)
FACTS_SHOWN = NOTES_MAX
#: au plus tant de moyens de la joindre, d'autres noms, de conversations par source, de mails, de membres
WAYS_SHOWN, NAMES_SHOWN, PLACES_SHOWN, MAILS_SHOWN, MEMBERS_SHOWN = 5, 3, 3, 2, 8
#: la source d'une vue → le mot de « sources » (voix.yaml)
SOURCE_KEYS = {TEAMS: "teams", MAIL: "mail", PHONE_SOURCE: "phone", TOLD: "told"}
#: un identifiant qui est un moyen de la joindre → sa clé de « way » (voix.yaml) ; un identifiant Teams, une clé du
#: téléphone, un nom raconté ne se montrent pas (le domaine d'une organisation se dit sur sa ligne)
WAY_KEYS = {EMAIL: "email", PHONE: "phone"}
#: une famille d'applis du téléphone → sa clé de « apps » (voix.yaml)
APP_KEYS = {WHATSAPP: "whatsapp", SMS: "sms"}

CONTACTS.bundle(BUNDLE, phrase("contacts.bundle"))


class LookupArgs(BaseModel):
    name: str = Field(min_length=2, max_length=120, description=phrase("contacts.tools.lookup.name"))


def facing(ctx: Any) -> str:
    """La personne en face (sa clé), reconnue, en tête-à-tête ; vide sinon (un salon, une inconnue, elle seule)."""
    kind = ctx.frame.episode.kind if ctx.frame.episode is not None else ""
    return shared_with(ctx.frame.audience, kind).removeprefix(PERSON)


def visible_here(ctx: Any, person: str) -> frozenset[tuple[str, str]]:
    """Les vues (source, compte) que cette personne voit : ses comptes, son téléphone, ce qu'elle a raconté, et ce qui
    n'est à personne."""
    return visible_sources(person, owners=tuple(ctx.frame.get(identity_c.OWNERS) or ()), accounts=accounts_of(ctx))


@CONTACTS.tool("contacts_lookup", description=phrase("contacts.tools.lookup.description"),
               label=phrase("contacts.tools.lookup.label"), args=LookupArgs, bundle=BUNDLE, episodes=[Kind.REPLY],
               owner_only=True, max_calls_per_episode=4)
async def contacts_lookup(args: LookupArgs, ctx: Any) -> Any:
    port = ctx.ports.get("contacts")
    if port is None:
        return ToolResult(ok=False, content=phrase("contacts.tools.lookup.not_plugged"))
    person = facing(ctx)
    if not person:
        return ToolResult(ok=False, content=phrase("contacts.tools.lookup.not_here"))
    visible = visible_here(ctx, person)
    # ses propres fiches (reliées à elle) sont écartées : de quoi en dire ``SHOWN`` et savoir s'il en reste
    own = len(port.links().get(person, ()))
    got = port.page(visible=visible, q=args.name, size=SHOWN + 1 + own) if visible else None
    found = [c for c in (got.items if got is not None else ()) if c.person != person]
    if not found:
        return phrase("contacts.tools.lookup.nobody", name=inert(args.name, 120))
    owner = person in set(ctx.frame.get(identity_c.OWNERS) or ())
    lines = [phrase("contacts.tools.lookup.data")]
    for c in found[:SHOWN]:
        sheet = port.sheet(c.id, visible=visible)
        if sheet is not None:
            lines += sheet_lines(ctx, sheet, visible, owner=owner)
    # la personne en face n'est pas parmi les « autres » (sa propre fiche, écartée plus haut)
    hidden = len(got.items) - len(found) if got is not None else 0
    others = (got.total if got is not None else 0) - hidden - min(len(found), SHOWN)
    if others > 0 and len(found) > SHOWN:
        lines.append(phrase("contacts.tools.lookup.more", count=others))
    return "\n".join(lines)


def sheet_lines(ctx: Any, sheet: ContactSheet, visible: frozenset[tuple[str, str]], *, owner: bool) -> list[str]:
    """Une fiche, dans ce que la personne en face voit : sa ligne (nom, poste, organisation, autres noms, où et quand
    elle la voit), puis ce qui sert à agir — la joindre, relire où elle écrit — et ce qu'elle en a compris."""
    frame = ctx.frame
    words = family("contacts.tools.lookup.sources")
    sightings = [x for i in sheet.identifiers for x in i.sightings]
    details = ""
    if sheet.title:
        details += phrase("contacts.tools.lookup.title", title=inert(sheet.title, 120))
    if sheet.department:
        details += phrase("contacts.tools.lookup.department", department=inert(sheet.department, 120))
    if sheet.org is not None:
        details += phrase("contacts.tools.lookup.org_of", org=inert(sheet.org.name, 120))
    for domain in dict.fromkeys(i.value for i in sheet.identifiers if i.kind == DOMAIN and i.value != sheet.name):
        details += phrase("contacts.tools.lookup.domain", domain=inert(domain, 120))
    others = [inert(n, 80) for n in sheet.names if n.strip() and n != sheet.name][:NAMES_SHOWN]
    if others:
        details += phrase("contacts.tools.lookup.also_named", names=" ; ".join(others))
    seen = list(dict.fromkeys(words[SOURCE_KEYS[x.source]] for x in sightings if x.source in SOURCE_KEYS))
    if seen:
        details += phrase("contacts.tools.lookup.seen", where=", ".join(seen))
    last = max((x.last for x in sightings), default=0)
    if last > 0:
        details += phrase("contacts.tools.lookup.last", count=sum(x.count for x in sightings), when=day(frame, last))
    what = phrase("contacts.tools.lookup.org") if sheet.kind == ORG else phrase("contacts.tools.lookup.person")
    out = [phrase("contacts.tools.lookup.line", name=inert(sheet.name, 120), what=what, details=details)]
    ways = ways_of(sheet)
    if ways:
        out.append(phrase("contacts.tools.lookup.ways", ways=" ; ".join(ways)))
    if sheet.kind == ORG:
        if sheet.members:
            names = ", ".join(inert(m.name, 80) for m in sheet.members[:MEMBERS_SHOWN])
            more = len(sheet.members) - MEMBERS_SHOWN
            out.append(phrase("contacts.tools.lookup.members", names=names)
                       + (phrase("contacts.tools.lookup.members_more", count=more) if more > 0 else ""))
        return out
    if owner and sheet.person:  # « te parle aussi » seulement de qui lui a écrit ; sinon, un compte (ADR 0298)
        name = identity_c.person_name(frame, sheet.person)
        if name and identity_c.last_heard(frame, sheet.person) > 0:
            out.append(phrase("contacts.tools.lookup.talks_to_you", name=inert(name, 80)))
        elif name:
            out.append(phrase("contacts.tools.lookup.has_account", name=inert(name, 80)))
    out += teams_lines(ctx, sheet, visible) + mail_lines(ctx, sheet, visible) + phone_lines(frame, sheet)
    notes = per_place(ctx.ports.get("contacts").notes(sheet.id, visible=visible))
    out += [phrase("contacts.tools.lookup.fact", text=inert(n.text, 200),
                   where=words.get(SOURCE_KEYS.get(n.source, ""), n.source),
                   place=phrase("contacts.tools.lookup.fact_place", place=inert(n.place, 120)) if n.place else "",
                   when=day(frame, n.said_at or n.at), confidence=round(n.confidence * 100),
                   ref=reference(n.ref)) for n in notes] or [phrase("contacts.tools.lookup.no_fact")]
    return out


def per_place(notes: list[Any]) -> list[Any]:
    """Ses faits, ``FACTS_SHOWN`` au plus par vue (source, compte) — la fiche entière de chacune (ADR 0303) —, dans
    leur ordre (les plus sûrs d'abord)."""
    seen: dict[tuple[str, str], int] = {}
    out = []
    for n in notes:
        place = (n.source, n.account)
        if seen.get(place, 0) < FACTS_SHOWN:
            seen[place] = seen.get(place, 0) + 1
            out.append(n)
    return out


def ways_of(sheet: ContactSheet) -> list[str]:
    """Ses moyens de la joindre, dans ce qui est visible : ses e-mails (une adresse générique dite comme telle), ses
    numéros — jamais un identifiant Teams, une clé du téléphone, un nom raconté."""
    labels = family("contacts.tools.lookup.way")
    out: list[str] = []
    for i in sheet.identifiers:
        key = WAY_KEYS.get(i.kind)
        if key is None or not i.value:
            continue
        key = "generic" if key == "email" and i.generic else key
        out.append(phrase("contacts.tools.lookup.way_line", label=labels[key], value=inert(i.value, 200)))
    return list(dict.fromkeys(out))[:WAYS_SHOWN]


def teams_lines(ctx: Any, sheet: ContactSheet, visible: frozenset[tuple[str, str]]) -> list[str]:
    """Les conversations Teams où elle écrit, dans les comptes visibles, la plus récente d'abord, chacune avec la
    référence de son dernier message (``teams_read`` la relit)."""
    port = ctx.ports.get("teams")
    authors = [i.value for i in sheet.identifiers if i.kind == TEAMS_ID and i.value]
    accounts = sorted(a for s, a in visible if s == TEAMS)
    if port is None or not authors or not accounts:
        return []
    found = port.written_in(authors, PLACES_SHOWN, accounts=accounts)
    if not found:
        return []
    lasts = port.last_messages([(conv.account, conv.id) for conv, _n, _at in found])
    places = []
    for conv, count, at in found:
        last = lasts.get((conv.account, conv.id))
        places.append(phrase("contacts.tools.lookup.place", place=teams_place(conv.kind, conv.title),
                             count=messages(count), when=day(ctx.frame, at),
                             ref=reference(last.ref if last is not None else "")))
    return [phrase("contacts.tools.lookup.on_teams", places=" ; ".join(places))]


def mail_lines(ctx: Any, sheet: ContactSheet, visible: frozenset[tuple[str, str]]) -> list[str]:
    """Ses derniers mails, dans les boîtes visibles, chacun avec sa référence (``email_read`` le relit)."""
    port = ctx.ports.get("mail")
    boxes = sorted(a for s, a in visible if s == MAIL)
    addresses = [i.value for i in sheet.identifiers if i.kind == EMAIL and i.value and not i.generic]
    if port is None or not boxes or not addresses:
        return []
    got = sorted((m for a in addresses for m in port.letters_from(a, limit=MAILS_SHOWN, accounts=boxes)),
                 key=lambda m: -m.date)[:MAILS_SHOWN]
    if not got:
        return []
    mails = [phrase("contacts.tools.lookup.mail", place=mail_place(m.subject or ""), when=day(ctx.frame, m.date),
                    ref=reference(m.ref)) for m in got]
    return [phrase("contacts.tools.lookup.on_mail", mails=" ; ".join(mails))]


def phone_lines(frame: Frame, sheet: ContactSheet) -> list[str]:
    """Ses conversations sur le téléphone de la personne en face (ce que la fiche visible en garde) : l'appli, le nom
    qu'elle y porte, où, et quand elle y a écrit."""
    apps = family("contacts.tools.lookup.apps")
    places: list[tuple[int, str]] = []
    for i in sheet.identifiers:
        app = apps.get(APP_KEYS.get(app_family(i.value), ""), apps["other"]) if i.kind == PHONE_APP else apps["other"]
        for x in i.sightings:
            if x.source != PHONE_SOURCE:
                continue
            named = phrase("contacts.tools.lookup.phone_name", name=inert(x.name, 80)) if x.name else ""
            for t in x.threads or ():
                places.append((t.last, phrase("contacts.tools.lookup.phone_place", app=app, name=named,
                                              place=phone_place(t.group, t.title), when=day(frame, t.last))))
    if not places:
        return []
    shown = [p for _at, p in sorted(places, key=lambda kv: -kv[0])][:PLACES_SHOWN]
    return [phrase("contacts.tools.lookup.on_phone", places=" ; ".join(dict.fromkeys(shown)))]


def day(frame: Frame, at: int) -> str:
    """Le jour d'un instant, court (« aujourd'hui », « hier », « le 12/11 », « le 03/02/2025 ») : de quoi juger si un
    fait est encore vrai."""
    if at <= 0:
        return phrase("contacts.tools.lookup.day.unknown")
    then, today = frame.local(at), frame.local().date()
    days = (today - then.date()).days
    if days == 0:
        return phrase("contacts.tools.lookup.day.today")
    if days == 1:
        return phrase("contacts.tools.lookup.day.yesterday")
    dm = {"day": f"{then.day:02d}", "month": f"{then.month:02d}"}
    if then.year == today.year:
        return phrase("contacts.tools.lookup.day.date", **dm)
    return phrase("contacts.tools.lookup.day.date_year", **dm, year=then.year)


def messages(count: int) -> str:
    return phrase("contacts.tools.lookup.messages.one") if count == 1 \
        else phrase("contacts.tools.lookup.messages.many", count=count)


def reference(ref: str) -> str:
    """La référence d'un message, entre crochets (vide sans référence) : ``teams_read``, ``email_read`` la relisent."""
    return phrase("contacts.tools.lookup.ref", ref=inert(ref, 120)) if ref else ""

__all__ = ["LookupArgs", "contacts_lookup", "day", "facing", "per_place", "sheet_lines", "visible_here", "ways_of"]
