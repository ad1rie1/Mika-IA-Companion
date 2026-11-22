"""La file « À valider » (ADR 0177) : une seule page pour tout ce qui attend une décision. La composition lui donne ses
onglets (``TABS`` : les courriers à envoyer, les réponses Teams, les identités à confirmer, les rapprochements —
« Tout » et l'historique sont ceux de la console), ce qui n'est pas une demande d'envoi (``Waiting.items``) — les
identités à confirmer, lues dans la vue de la faculté d'identité, avec leurs faits, leur source et leurs actions déjà
orientées (``tabs/identities.py``) ; les rapprochements — deux fiches de l'annuaire au même nom, sans identifiant
commun (ADR 0298, lues dans le port ``contacts``, avec l'avis du juge quand il en a un : ADR 0304 — ce dont il est sûr
s'est fait d'office), et une personne dont on lui a parlé que porte quelqu'un qui lui
parle (la vue « Noms à relier » de l'identité, ``NAMES_VIEW``) —, leurs deux fiches côte à côte (``QueueItem.body``)
et leurs deux gestes — et ce que concerne une demande (``Waiting.about``, lu dans son contexte par
``approval_sources.about`` : une personne, un projet, un service, une app, un canal). « Noms à relier » n'est plus un
onglet (ADR 0298, lot 5) : une personne dont on lui parle a sa fiche d'emblée, et se rapproche des autres comme
n'importe quelle fiche ; face à quelqu'un qui lui parle, c'est l'identité qui les relie (sa mémoire le saura). Les vues
de la faculté d'identité n'ont plus de destination : la file est le seul endroit où l'on en décide (ADR 0180).
L'inspecteur dessine la file sans nommer ni plugin ni faculté.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from markupsafe import Markup

from mika.app.handmade import Look, approval_sources
from mika.app.handmade.directory import STYLES as DIRECTORY_STYLES
from mika.app.handmade.directory import Talker, accounts, contact_entry, person_entry
from mika.app.handmade.subjects.contact import MATCH, line_of, sheet_of, whose_words
from mika.app.handmade.subjects.parts import safely
from mika.app.handmade.tabs import Got, Line, blank, instant, raw_lines, text
from mika.app.handmade.tabs.identities import claim_entry, handle_of, name_entry
from mika.contracts import email as email_c
from mika.contracts import teams as teams_c
from mika.contracts import transcript as transcript_c
from mika.faculties.identity.inspect import handles_of
from mika.inspector.ui import UI, QueueItem, QueueTab, env
from mika.kernel.clock import DAY
from mika.plugins.contacts.inspect import RULE_WORDS, contact_key, verdict_words
from mika.ports.contacts import TOLD_NAME
from mika.vocab.people import fold, named_label

#: les sortes d'éléments que la composition met dans la file
CLAIM, NAME = "identite", "nom"
#: les rapprochements de l'annuaire lus d'un coup, au plus (``ContactsPort.suggestions``)
MATCHES_MAX = 200
#: pourquoi deux fiches se ressemblent, en mots (la même source que la vue des rapprochements)
REASONS = RULE_WORDS
#: ce que dit la file de chaque rapprochement (ADR 0304)
MATCH_RULE = ("Ce qu'un identifiant prouve (la même adresse, le même compte) se réunit d'office, et ce dont le juge "
              "est sûr aussi — il ne réunit jamais deux fiches que tu as séparées ; ce qui reste ici, il n'en est pas "
              "sûr.")
#: les vues de la faculté d'où ils viennent : (propriétaire, vue) ; celle des rapprochements de l'annuaire, que la file
#: lit par le port mais que la console en MCP sert en texte (ADR 0304)
CLAIMS_VIEW, NAMES_VIEW, MATCHES_VIEW = ("identity", "revendications"), ("identity", "noms"), ("contacts", "rapprochements")

TABS: tuple[QueueTab, ...] = (
    QueueTab("courriers", "Courriers à envoyer", capabilities=(email_c.SEND,), order=10,
             description="Les mails qu'elle voudrait envoyer : ce qui partira, tel quel, après ton accord.",
             empty="Aucun mail n'attend ton accord."),
    QueueTab("teams", "Réponses Teams", capabilities=(teams_c.SEND,), order=20,
             description="Ses réponses dans Teams, à ta place : ce qui sera posé, après ton accord.",
             empty="Aucune réponse Teams n'attend ton accord."),
    QueueTab("identites", "Identités à confirmer", kinds=(CLAIM,), order=30,
             description="Qui dit être quelqu'un d'autre, sans preuve encore : t'en porter garant, la démentir ou "
                         "relier ce moyen de communication.",
             empty="Personne ne dit être quelqu'un d'autre sans preuve en ce moment."),
    QueueTab("rapprochements", "Rapprochements", kinds=(MATCH, NAME), order=35,
             description="Deux fiches qui pourraient être la même personne — deux fiches de l'annuaire, ou une personne "
                         "dont on lui a parlé et quelqu'un qui lui parle : la même personne ? " + MATCH_RULE,
             empty="Aucune fiche n'en rappelle une autre par son nom."),
)


async def _view(ui: UI, owner: str, name: str) -> Got | None:
    spec = ui.inspection.find(owner, name)
    if spec is None:
        return None
    return Got(ui, list(await ui.inspection.arun(spec, {}, ui.when_long)), {}, {})


def _claim_item(got: Got, line: Line, raw: dict[str, Any], rule: str) -> QueueItem:
    c = claim_entry(got, line)
    handle = handle_of(c["handle"])
    target = c["target"] if c["known"] else None
    facts: list[tuple[str, Any]] = [("vise", c["target"]), ("canal", c["channel"])]
    if (meter := line.get("vers la barre")) is not None:
        facts.append(("vers la barre", meter))
    facts += [("preuves comptées", {"t": "text", "text": c["evidence"] or "—"}), ("depuis", c["since"]),
              ("s'éteint", c["ends"])]
    sources = [("Le moyen de communication", line.href)] if line.href else []
    if target is not None and target.get("href"):
        sources.append((f"La fiche de {text(target)}", target["href"]))
    return QueueItem(CLAIM, handle, "Identité à confirmer", f"{text(c['handle'])} se présente comme {c['name']}",
                     context=text(target) if target is not None else "plusieurs personnes portent ce nom",
                     at=instant(raw.get("depuis")), facts=tuple(facts), sources=tuple(sources),
                     links=tuple((a["label"], a["href"]) for a in c["actions"]), note=rule)


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


class Waiting:
    """Ce que la composition met dans la file « À valider » (``InspectorDeps.queue``)."""

    tabs: Sequence[QueueTab] = TABS
    #: les feuilles de ce qu'elle dessine dans la liseuse (deux fiches côte à côte)
    styles: Sequence[str] = DIRECTORY_STYLES
    #: les vues qui montrent les mêmes demandes que la file, dans leur destination : l'accueil ne les compte pas une
    #: seconde fois (``UI.attention_items(distinct=True)``)
    covers: Sequence[str] = ("courrier/brouillons", "teams/reponses", "projets/tous")
    #: les vues de ce qui attend ta décision hors des demandes d'envoi : la console en MCP les sert sous leur part, « la
    #: file « À valider » » (``inspector.mcp.QUEUE``), que la page Outils › Prêter à un agent montre (ADR 0304)
    views: Sequence[tuple[str, str]] = (CLAIMS_VIEW, NAMES_VIEW, MATCHES_VIEW)

    def count(self, ui: UI, kinds: Sequence[str] | None) -> int:
        """Combien d'éléments de ces sortes attendent (toutes : ``kinds`` vide) — les compteurs de leurs vues."""
        total = 0
        for kind, (owner, name) in ((CLAIM, CLAIMS_VIEW), (NAME, NAMES_VIEW)):
            if kinds is not None and kind not in kinds:
                continue
            spec = ui.inspection.find(owner, name)
            got = ui.inspection.badge(spec) if spec is not None else None
            total += int(got[0]) if got else 0
        if kinds is None or MATCH in kinds:
            total += len(_suggestions(ui))
        return total

    def about(self, ui: UI, context: str) -> tuple[str, str | None]:
        """Ce que concerne une demande, dit simplement (« Adrien », « projet n° 61 », « Teams »), et la fiche où ça
        mène (``None`` : aucune) — la file, sa demande ouverte et l'historique le disent tous ainsi."""
        return approval_sources.about(ui, context)

    async def items(self, ui: UI) -> list[QueueItem]:
        """Les identités à confirmer, telles que leur vue les dit ; les rapprochements — les noms qui attendent
        quelqu'un (la vue de l'identité) et ceux de l'annuaire."""
        out: list[QueueItem] = []
        got = await _view(ui, *CLAIMS_VIEW)
        table = got.table("Revendications en attente") if got is not None else None
        if got is not None and table is not None:
            rule = next((n["text"] for n in got.notes()), "")
            out += [_claim_item(got, x, r, rule) for x, r in zip(got.lines("Revendications en attente"),
                                                                 raw_lines(got, table), strict=False)]
        look = Look.of(ui, DAY)
        acc = accounts(look)
        got = await _view(ui, *NAMES_VIEW)
        table = got.table("Noms qui attendent") if got is not None else None
        if got is not None and table is not None:
            rule = next((n["text"] for n in got.notes()), "")
            out += [_name_item(ui, look, acc, x, r, rule) for x, r in zip(got.lines("Noms qui attendent"),
                                                                          raw_lines(got, table), strict=False)]
        out += [item for x in _suggestions(ui) if (item := _match_item(ui, look, acc, x)) is not None]
        return out


QUEUE = Waiting()
