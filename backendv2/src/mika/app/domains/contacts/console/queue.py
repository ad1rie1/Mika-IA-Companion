"""Sa part de la file « À valider » (ADR 0177, 0298, 0304, 0310) : les rapprochements — deux fiches de l'annuaire au
même nom, sans identifiant commun (lues dans le port ``contacts``, avec l'avis du juge quand il en a un : ce dont il
est sûr s'est fait d'office), et une personne dont on lui a parlé que porte quelqu'un qui lui parle (la vue « Noms à
relier » de l'identité) —, leurs deux fiches côte à côte et leurs deux gestes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from markupsafe import Markup

from mika.app.domains.contacts.console.directory import STYLES as DIRECTORY_STYLES
from mika.app.domains.contacts.console.directory import Talker, accounts, contact_entry, person_entry
from mika.app.domains.contacts.console.subject import MATCH, line_of, sheet_of, whose_words
from mika.app.domains.domain import QueuePart
from mika.app.handmade import Look
from mika.app.handmade.subjects.parts import safely
from mika.app.handmade.tabs import Line, blank, instant, raw_lines, text, view_of
from mika.app.handmade.tabs.identities import name_entry
from mika.contracts import transcript as transcript_c
from mika.faculties.identity.inspect import handles_of
from mika.inspector.ui import UI, QueueItem, QueueTab, env
from mika.kernel.clock import DAY
from mika.plugins.contacts.inspect import RULE_WORDS, contact_key, verdict_words
from mika.ports.contacts import TOLD_NAME
from mika.vocab.people import fold, named_label

#: la sorte d'un nom à relier (une personne dont on lui a parlé) ; celle d'un rapprochement de l'annuaire : ``MATCH``
NAME = "nom"
#: les rapprochements de l'annuaire lus d'un coup, au plus (``ContactsPort.suggestions``)
MATCHES_MAX = 200
#: pourquoi deux fiches se ressemblent, en mots (la même source que la vue des rapprochements)
REASONS = RULE_WORDS
#: ce que dit la file de chaque rapprochement (ADR 0304)
MATCH_RULE = ("Ce qu'un identifiant prouve (la même adresse, le même compte) se réunit d'office, et ce dont le juge "
              "est sûr aussi — il ne réunit jamais deux fiches que tu as séparées ; ce qui reste ici, il n'en est pas "
              "sûr.")
#: les vues d'où ils viennent : (propriétaire, vue) — les noms à relier de l'identité ; celle des rapprochements de
#: l'annuaire, que la file lit par le port mais que la console en MCP sert en texte (ADR 0304)
NAMES_VIEW, MATCHES_VIEW = ("identity", "noms"), ("contacts", "rapprochements")


def _told_side(ui: UI, look: Look, acc: Any, key: str, said: str) -> dict[str, Any]:
    """La personne dont on lui a parlé, comme l'annuaire la dit : sa fiche (``TOLD_NAME``), sinon son nom seul."""
    port = ui.kernel.ports.get("contacts")
    cid = safely(lambda: port.contact_of(TOLD_NAME, key), "un nom raconté") if port is not None and key else None
    sheet = sheet_of(ui, contact_key(cid)) if cid else None
    if sheet is not None:
        return contact_entry(look, acc, line_of(sheet))
    return {"kind": "far", "name": said, "initial": (said[:1] or "?").upper(), "href": "",
            "tags": [{"text": "connue de nom", "cls": "far"}], "idea": "", "ids": [], "more": 0,
            "sources": [{"name": "Racontée", "n": ""}], "of": [], "everyone": False, "links": []}


def _talker_side(look: Look, acc: Any, person: str) -> dict[str, Any]:
    """Quelqu'un qui lui parle, comme l'annuaire le dit."""
    s = look.frame.state("identity")
    handles = tuple(handles_of(s, person))
    last = max((look.frame.get(transcript_c.LAST_FROM(h)) for h in handles), default=0)
    return person_entry(look, acc, Talker(person, handles, last), {}, {})


def _name_item(ui: UI, look: Look, acc: Any, line: Line, raw: dict[str, Any], rule: str) -> QueueItem:
    """Une personne dont on lui a parlé, que porte quelqu'un qui lui parle : les deux fiches côte à côte, et les
    gestes de l'identité — la relier (sa fiche, le formulaire pré-rempli : sa mémoire le saura) ou l'écarter."""
    w = name_entry(line)
    person = w["person"]
    facts = [(k, v) for k, v in (("qui lui en a parlé", w["told"]), ("ce qui attend", {"t": "text", "text": w["what"]}),
                                 ("personne qui le porte", person), ("par où", {"t": "text", "text": w["where"]}),
                                 ("vue pour la première fois", w["first"])) if not blank(v)]
    dismiss = w["dismiss"]
    given = (dismiss or {}).get("initial") or {}
    key, who = str(given.get("name") or ""), str(given.get("person") or "")
    said = w["name"].strip("« »") or named_label(key).title()
    body = None
    if key and who:
        sides = [_told_side(ui, look, acc, key, said), _talker_side(look, acc, who)]
        same = named_label(key).split() == fold(sides[1]["name"]).split()
        why = ("Le même nom." if same else "Le même prénom, d'un côté sans nom de famille.") + \
            " On lui en a parlé ; l'autre lui parle. Reliée, ce qu'on lui en a dit se rattache à elle — chacun garde " \
            "qui le lui a confié."
        body = Markup(env.get_template("handmade/approbations/rapprochement.html").render(sides=sides, why=why))
    return QueueItem(NAME, f"{w['name']}|{text(person)}", "Rapprochement",
                     f"« {said} », dont on lui a parlé, et {text(person)} : la même personne ?",
                     context=f"porté par {text(person)}", at=instant(raw.get("vue pour la première fois")),
                     facts=tuple(facts), body=body,
                     sources=((f"La fiche de {text(person)}", person["href"]),) if (person or {}).get("href") else (),
                     links=(("La même personne : relier…", w["href"]),) if w["href"] else (),
                     actions=((dismiss["key"], given, "Deux personnes différentes"),) if dismiss else (),
                     note=rule, warn=w["homonyms"])


def _suggestions(ui: UI) -> list[Any]:
    port = ui.kernel.ports.get("contacts")
    return list(safely(lambda: port.suggestions(MATCHES_MAX), "rapprochements", []) or ()) if port is not None else []


def _match_item(ui: UI, look: Look, acc: Any, x: Any) -> QueueItem | None:
    """Un rapprochement : ses deux fiches côte à côte, pourquoi, et ses deux gestes."""
    a, b = sheet_of(ui, contact_key(x.a.id)), sheet_of(ui, contact_key(x.b.id))
    if a is None or b is None:
        return None
    sides = [contact_entry(look, acc, line_of(sheet)) for sheet in (a, b)]
    common = not {(i.kind, i.value) for i in a.identifiers} & {(i.kind, i.value) for i in b.identifiers}
    why = REASONS.get(x.reason, x.reason).capitalize() + (". Aucun identifiant en commun." if common else ".")
    if x.verdict:  # ce qu'en dit le juge (ADR 0304) : jamais sûr ici, sinon ce serait fait
        why += f" Le juge : {verdict_words(x.verdict, False)}" + (f" — {x.why}" if x.why else "") + \
            ("" if x.why.endswith((".", "!", "?")) else ".")
    holders = list(dict.fromkeys(w["name"] for sheet in (a, b) for w in whose_words(look, acc, sheet)))
    if len(holders) > 1:
        why += (f" Réunies, elle serait le contact de {', '.join(holders[:-1])} et de {holders[-1]} ; ce que chacun "
                "lui a appris d'elle reste à lui.")
    body = Markup(env.get_template("handmade/approbations/rapprochement.html").render(sides=sides, why=why))
    pair = {"a": a.id, "b": b.id}
    return QueueItem(MATCH, f"{min(a.id, b.id)}-{max(a.id, b.id)}", "Rapprochement",
                     f"« {a.name} » et « {b.name} » : la même personne ?", context=REASONS.get(x.reason, x.reason),
                     at=max(a.created, b.created), body=body,
                     actions=(("contacts.rapprocher", pair, "La même personne : réunir"),
                              ("contacts.ecarter", pair, "Deux personnes différentes")), note=MATCH_RULE)


def count(ui: UI, kinds: Sequence[str] | None) -> int:
    """Combien de rapprochements attendent, de ces sortes (toutes : ``kinds`` vide)."""
    total = 0
    if kinds is None or NAME in kinds:
        spec = ui.inspection.find(*NAMES_VIEW)
        got = ui.inspection.badge(spec) if spec is not None else None
        total += int(got[0]) if got else 0
    if kinds is None or MATCH in kinds:
        total += len(_suggestions(ui))
    return total


async def items(ui: UI) -> list[QueueItem]:
    """Les noms qui attendent quelqu'un (la vue de l'identité), puis les rapprochements de l'annuaire."""
    out: list[QueueItem] = []
    look = Look.of(ui, DAY)
    acc = accounts(look)
    got = await view_of(ui, *NAMES_VIEW)
    table = got.table("Noms qui attendent") if got is not None else None
    if got is not None and table is not None:
        rule = next((n["text"] for n in got.notes()), "")
        out += [_name_item(ui, look, acc, x, r, rule) for x, r in zip(got.lines("Noms qui attendent"),
                                                                      raw_lines(got, table), strict=False)]
    out += [item for x in _suggestions(ui) if (item := _match_item(ui, look, acc, x)) is not None]
    return out


QUEUE = QueuePart(
    tabs=(QueueTab("rapprochements", "Rapprochements", kinds=(MATCH, NAME), order=35,
         description="Deux fiches qui pourraient être la même personne — deux fiches de l'annuaire, ou une personne "
                     "dont on lui a parlé et quelqu'un qui lui parle : la même personne ? " + MATCH_RULE,
         empty="Aucune fiche n'en rappelle une autre par son nom.",
         hint="Deux fiches au même nom, des noms racontés"),),
    items=items, count=count, views=(NAMES_VIEW, MATCHES_VIEW),
    # les deux fiches côte à côte d'un rapprochement : les feuilles de l'annuaire
    styles=DIRECTORY_STYLES,
)
