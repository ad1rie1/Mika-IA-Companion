"""Relations & échanges › Personnes › Annuaire, dans sa forme (ADR 0177, 0310) : l'onglet de l'annuaire dans la
barre de Personnes, sous la clé qu'il y a toujours (``personnes/personnes``). La page d'entrée de Personnes et ses
autres onglets, Liens et Présents, restent au cadre (``app/handmade/tabs/people.py``).

- **Annuaire** (ADR 0298) : tous ceux qu'elle connaît — qui lui parle, et qui elle connaît de loin, personnes et
  organisations (le port ``contacts``) —, en deux colonnes sur un grand écran, du plus récemment vu
  (``directory.listing``) : « Qui » au bout de la barre (tout, lui parlent, connues de loin, organisations), une
  recherche (nom, e-mail, téléphone, identifiant), « Contacts de… » en puces, en fiches ou en tableau. Ses filtres
  sont les siens (``Tab.params``) : la vue de la faculté ne connaît que qui lui parle. Sous la liste, l'état des
  portraits (lot 6 : ce qu'elle se forme de chacun à partir de ce qu'elle lit), face à leurs plafonds.

L'Annuaire lit la faculté ``identity`` et le port ``contacts`` (``directory``).
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from mika.app.domains.contacts.console.directory import (
    ALL,
    FAR,
    OF,
    ORGS,
    SEARCH,
    SHOW,
    TALK,
    WHO,
    WHO_CHOICES,
    listing,
)
from mika.app.domains.contacts.console.directory import STYLES as DIRECTORY_STYLES
from mika.app.handmade import Look
from mika.app.handmade.subjects.parts import safely
from mika.app.handmade.tabs import Got, Tab
from mika.inspector import render
from mika.inspector.ui import PREFIX
from mika.kernel.clock import DAY
from mika.kernel.inspect import Pager, Param, Ref, Row, Table, plural
from mika.plugins.contacts import params as contacts_params
from mika.plugins.contacts.portrait import CURSOR_ELIGIBLE, CURSOR_RUN


def annuaire(got: Got) -> Markup | None:
    """Personnes › Annuaire (ADR 0298) : tous ceux qu'elle connaît — qui lui parle et qui elle connaît de loin,
    personnes et organisations —, du plus récemment vu ; « Qui », une recherche, « Contacts de… », en fiches ou en
    tableau (``directory.listing``)."""
    look = Look.of(got.ui, DAY)
    d = listing(look, got.query)
    paging = Pager("page", d["page"], d["size"], d["total"])
    said = {TALK: ("lui parle", "lui parlent"), FAR: ("connue de loin", "connues de loin"),
            ORGS: ("organisation", "organisations")}
    shown = (TALK, FAR, ORGS) if d["who"] == ALL else (d["who"],)
    parts = [plural(d["counts"][k], *said[key]) for key, k in zip((TALK, FAR, ORGS), ("talk", "far", "orgs"),
                                                                  strict=True) if key in shown]
    lede = " · ".join([*parts, "vues le plus récemment d'abord"])
    table = None
    if d["table"]:
        rows = tuple(Row((Ref("local", e["href"], e["name"]), ENTRY_KINDS[e["kind"]],
                          " · ".join(f"{i['k']} {i['v']}" for i in e["ids"]) or "—",
                          ", ".join(f"{x['name']} · {x['n']}" if x["n"] else x["name"] for x in e["sources"]) or "—",
                          "—" if e["kind"] == "talks" else "tout le monde" if e["everyone"]
                          else ", ".join(x["name"] for x in e["of"]), e["when"] or "—"))
                     for e in d["entries"])
        table = render.blocks([Table(("nom", "sorte", "ce qui l'identifie", "vue dans", "contact de", "quand"), rows,
                                     title="Personnes et organisations", pager=paging,
                                     empty="personne ne correspond")], got.env, dict(got.query))[0]
        table.update(count=d["total"], modes=d["modes"])  # sa bascule « Fiches / Tableau », dans son en-tête
    return got.draw("handmade/personnes/annuaire.html", d=d, lede=lede, table=table,
                    pager={"pager": render.pager_ctx(paging, dict(got.query))}, portraits=portraits_line(look))


def portraits_line(look: Look) -> dict[str, str] | None:
    """L'état des portraits (ADR 0298, lot 6), en une ligne sous l'annuaire : combien de contacts et d'appels en
    vingt-quatre heures face à leurs plafonds, combien de personnes échangent vraiment avec un compte, le dernier
    passage — et où régler tout ça. Rien sans annuaire."""
    port = look.ui.kernel.ports.get("contacts")
    if port is None:
        return None
    frame = look.frame
    p = contacts_params(frame.env.params_of("contacts", frame.root))
    day = safely(lambda: port.portraits(since=frame.now - DAY), "portraits du jour", []) or []
    run = safely(lambda: port.cursor(CURSOR_RUN), "dernier portrait", 0) or 0
    eligible = safely(lambda: port.cursor(CURSOR_ELIGIBLE), "contacts qui échangent", 0) or 0
    if not p.portraits:
        text = "Portraits coupés : elle ne se forme plus d'idée de ses contacts à partir de ce qu'elle lit."
    else:
        text = (f"Portraits : {plural(len({x.contact for x in day}), 'contact', 'contacts')} sur "
                f"{p.contacts_per_day} et {plural(len(day), 'appel', 'appels')} sur {p.calls_per_day} en "
                f"vingt-quatre heures · {plural(eligible, 'personne échange', 'personnes échangent')} vraiment avec "
                f"un compte · " + (f"dernier passage {look.ago(run)}" if run else "pas encore passé")
                + (" · tout l'historique" if p.history else ""))
    return {"text": text, "href": f"{PREFIX}/reglages/comportement-contacts"}


#: la sorte d'une entrée de l'annuaire, en mots (son tableau)
ENTRY_KINDS = {"talks": "lui parle", "far": "connue de loin", "org": "organisation"}


TABS: dict[str, Any] = {
    # ses filtres à lui (``Tab.params``) : il réunit qui lui parle et l'annuaire, la vue de la faculté ne les connaît pas
    "personnes/personnes": Tab(annuaire, *DIRECTORY_STYLES, params=(
        Param(WHO, "Qui", "select", WHO_CHOICES, default=ALL), Param(SEARCH, "Chercher", "hidden"),
        Param(OF, "Contacts de", "hidden"), Param(SHOW, "Affichage", "hidden")),
        description="Tous ceux qu'elle connaît : qui lui parle, et qui elle connaît de loin — par ce qu'elle lit "
                    "(Teams, courrier, téléphone) ou ce qu'on lui raconte —, et les organisations."),
}
