"""L'onglet « Agendas » de la fiche d'une personne (ADR 0309, lot 5 ; la maquette :
``output/maquette-agenda-console/personne-lea-agendas.html``), à côté de Comptes : à gauche ses agendas (ceux que le
serveur lui donne et ceux qu'elle a branchés, leur sorte, leur synchro), ce qu'on lui partage et ce qu'elle partage —
« Retirer » sur chaque partage (le geste de Réglages › Droits › Partages, ADR 0210 ; le donner reste au propriétaire) ;
à droite ses prochains événements de la semaine : ses agendas, ce qu'on lui partage, et ce que l'agenda de Mika retient
pour elle. Les données sont celles du plugin ``agenda`` (``app/domains/agenda/console/reads.py``) ; un événement privé d'une autre personne
reste « Occupé · privé ».

Sa part de la fiche (``PERSON_PART``, ADR 0310) : cet onglet, qui pose aussi les formulaires de la console, et son
compte.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.app.domains.agenda.console.reads import items, read
from mika.app.domains.domain import PersonPart
from mika.app.handmade import Look
from mika.app.handmade.person.common import Who
from mika.inspector.pages.subjects import subject_url
from mika.inspector.ui import PREFIX, UI, env
from mika.plugins.agenda.inspect.views import (
    HER,
    KIND,
    KIND_SHORT,
    YOURS,
    bounds,
    count_events,
    person_calendars,
    synced,
    week_of,
)
from mika.vocab.access import PERSON, SHARES

#: « Retirer » un partage (``app/handmade/rights.py``)
UNSHARE = f"{PREFIX}/reglages/droits/partages"
DAYS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


def agendas(ui: UI, key: str, blocks: Sequence[Any], query: Mapping[str, str],
            forms: Mapping[str, Any] | None = None) -> Markup | None:
    """L'onglet dessiné : ses agendas, ce qu'on lui partage, ce qu'elle partage ; ses prochains événements."""
    if ui.kernel.ports.get("agenda") is None:
        return None
    r = read(ui)
    person = ui.names.person_of(key) or key
    who = r.who_of_person(person)
    levels = {k: v.lower() for k, v in SHARES}
    counts = count_events(r.ports, [c.key for c in r.calendars])
    back = subject_url("person", person, "agendas")

    def said(c: Any) -> tuple[str, str]:
        s = synced(r.ports, r.frame, c, lambda t: r.look.ago(t) if t else "jamais")
        return s.label, s.tone

    mine = [{"name": c.name, "color": r.colors.get(c.key), "href": subject_url(KIND, c.key),
             "tags": [(KIND_SHORT.get(c.kind, c.kind), ""), said(c)],
             "time": f"{counts.get(c.key, 0)} événement{'s' if counts.get(c.key, 0) > 1 else ''}",
             "facts": [("compte", "sur ce serveur" if c.system else (c.state.address if c.state and c.state.address
                                                                     else c.cal.account))]
             + ([("partagé avec", ", ".join(f"{r.look.name(w[len(PERSON):])} ({levels.get(lv, lv)})"
                                             for w, lv in sorted(c.shares.items())))] if c.shares else [])}
            for c in r.calendars if c.who == who]
    received, given = [], []
    for c in r.calendars:
        for w, lv in sorted(c.shares.items()):
            target = w[len(PERSON):]
            row = {"name": c.name, "color": r.colors.get(c.key), "href": subject_url(KIND, c.key),
                   "level": levels.get(lv, lv), "key": c.key, "person": target,
                   "ask": f"Retirer à {r.look.name(target)} son accès à l'agenda « {c.name} » ? Il disparaît de son "
                          "espace ; seul son propriétaire peut le lui redonner."}
            if r.who_of_person(target) == who and c.who != who:
                received.append({**row, "owner": r.whose(c.who)})
            elif c.who == who:
                given.append({**row, "to": r.look.name(target), "to_href": subject_url("person", target, "agendas")})
    today = r.frame.local(r.now).date()
    end_day = week_of(today) + timedelta(days=6)
    start, end = bounds(r.frame, today, end_day)
    shared_keys = {x["key"] for x in received}
    found = [x for x in items(r, set(), set(), start, end)
             if x.end > r.now and (x.who == who or x.calendar in shared_keys
                                   or (x.hers and x.date is not None
                                       and who in {r.who_of_person(p) for p in x.date.persons}))]
    upcoming = []
    for x in found:
        local = r.frame.local(x.start)
        where = (f"{r.her_title} · pour elle" if x.hers else
                 f"{x.calendar_name} de {r.whose(x.who)} · partagé" if x.calendar in shared_keys else x.calendar_name)
        upcoming.append({"x": x, "when": f"{DAYS[x.first.weekday()]} {x.first.day} · "
                                         f"{'journée' if x.all_day else local.strftime('%H:%M')}", "where": where,
                         "href": f"{PREFIX}/agendas/tous?" + urlencode({"du": x.first.isoformat(), "ev": x.key,
                                                                        "qui": HER if x.hers else x.who})})
    return Markup(env.get_template("handmade/person/tabs/agendas.html").render(
        mine=mine, received=received, given=given, upcoming=upcoming, name=r.look.name(person),
        grid=f"{PREFIX}/agendas/tous?" + urlencode({"qui": who if who != YOURS else YOURS}),
        accounts=f"{PREFIX}/agendas/comptes?" + urlencode({"qui": who}), unshare=UNSHARE,
        csrf=getattr(forms, "csrf", ""), back=back))


def count(look: Look, who: Who) -> int:
    """Le compte de son onglet (``PersonOverview.counts``)."""
    # ses agendas et ceux qu'on lui partage (ADR 0309, lot 5)
    return sum(map(len, person_calendars(look.ui.kernel.ports, look.frame, who.person)))


#: sa part de la fiche d'une personne (ADR 0310)
PERSON_PART = PersonPart(
    # ses agendas, ce qu'on lui partage, ce qu'elle partage, ses prochains événements (ADR 0309, lot 5)
    tabs={"agendas": agendas}, counts={"agendas": count}, styles=("handmade/agendas.css",))


__all__ = ["PERSON_PART", "agendas", "count"]
