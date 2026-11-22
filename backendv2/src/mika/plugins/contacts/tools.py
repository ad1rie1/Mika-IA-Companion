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
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.kernel.faculty import ToolResult
from mika.plugins.contacts import BUNDLE, CONTACTS
from mika.plugins.contacts.inspect import accounts_of
from mika.ports.contacts import MAIL, ORG, PHONE_SOURCE, TEAMS, TOLD, visible_sources
from mika.ports.preprocess import inert
from mika.vocab.access import PERSON
from mika.vocab.episodes import Kind
from mika.vocab.ownership import shared_with
from mika.vocab.phrasebook import family, phrase

#: au plus tant de fiches dites d'un appel (les plus récemment vues)
SHOWN = 3
#: au plus tant de faits par fiche
FACTS_SHOWN = 6
#: la source d'une vue → le mot de « sources » (voix.yaml)
SOURCE_KEYS = {TEAMS: "teams", MAIL: "mail", PHONE_SOURCE: "phone", TOLD: "told"}

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
    words = family("contacts.tools.lookup.sources")
    lines = [phrase("contacts.tools.lookup.data")]
    for c in found[:SHOWN]:
        sheet = port.sheet(c.id, visible=visible)
        if sheet is None:
            continue
        details = ""
        if sheet.title:
            details += phrase("contacts.tools.lookup.title", title=inert(sheet.title, 120))
        if sheet.department:
            details += phrase("contacts.tools.lookup.department", department=inert(sheet.department, 120))
        if sheet.org is not None:
            details += phrase("contacts.tools.lookup.org_of", org=inert(sheet.org.name, 120))
        seen = list(dict.fromkeys(words[SOURCE_KEYS[x.source]] for i in sheet.identifiers for x in i.sightings
                                  if x.source in SOURCE_KEYS))
        if seen:
            details += phrase("contacts.tools.lookup.seen", where=", ".join(seen))
        what = phrase("contacts.tools.lookup.org") if sheet.kind == ORG else phrase("contacts.tools.lookup.person")
        lines.append(phrase("contacts.tools.lookup.line", name=inert(sheet.name, 120), what=what, details=details))
        if sheet.kind == ORG:
            continue
        notes = port.notes(sheet.id, visible=visible)[:FACTS_SHOWN]
        lines += [phrase("contacts.tools.lookup.fact", text=inert(n.text, 200),
                         where=words.get(SOURCE_KEYS.get(n.source, ""), n.source),
                         confidence=round(n.confidence * 100)) for n in notes] \
            or [phrase("contacts.tools.lookup.no_fact")]
    # la personne en face n'est pas parmi les « autres » (sa propre fiche, écartée plus haut)
    hidden = len(got.items) - len(found) if got is not None else 0
    others = (got.total if got is not None else 0) - hidden - min(len(found), SHOWN)
    if others > 0 and len(found) > SHOWN:
        lines.append(phrase("contacts.tools.lookup.more", count=others))
    return "\n".join(lines)


__all__ = ["LookupArgs", "contacts_lookup", "facing", "visible_here"]
