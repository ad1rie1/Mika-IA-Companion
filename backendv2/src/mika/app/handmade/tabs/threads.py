"""Relations & échanges › Conversations : ses onglets dans leur forme (ADR 0177). Ses messages et ses réponses jugées
sont dessinés à part (``conversations.py``) ; ici, ce qui attend.

- **Questions sans réponse** : une file, comme le fil des messages la dirait — chaque question dans sa bulle, de qui,
  quand, et depuis combien de temps elle attend (en avant, une attente longue dite) ; sur sa ligne, le message source
  et la conversation avec cette personne. L'aide de la faculté au pied ; la pagination et la bascule « Tableau »
  sont les siennes.

Les données restent celles de la faculté du fil (``transcript``) ; l'instant de chaque question se lit à la liste
telle qu'elle l'a déclarée (le temps d'attente, pas une date relative).
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from mika.app.handmade import span
from mika.app.handmade.tabs import Got, Line, Tab, paged
from mika.app.handmade.tabs.people import person_of
from mika.inspector.pages.subjects import fiche_url
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.inspect import Row, When
from mika.vocab.people import is_identifiable

STYLES = ("handmade/fil.css",)



def _instants(got: Got, title: str, label: str) -> list[int]:
    """L'instant de chaque ligne de la page montrée (0 : ce n'en est pas un), lu à la liste telle que la faculté l'a
    déclarée — elle pagine elle-même : sa page est celle que la console rend."""
    table = got.raw_table(title)
    if table is None:
        return []
    labels = [c.label if hasattr(c, "label") else str(c) for c in table.columns]
    if label not in labels:
        return []
    i = labels.index(label)
    out = []
    for r in table.rows:
        cells = r.cells if isinstance(r, Row) else tuple(r)
        c = cells[i] if i < len(cells) else None
        out.append(c.at if isinstance(c, When) and c.at else 0)
    return out


def _wait(us: int) -> str:
    """Depuis combien de temps elle attend : « < 1 min », « 40 min », « 2 h 05 », « 3 j 2 h »."""
    return "< 1 min" if us < MINUTE else span(us)


def _question(line: Line, at: int, now: int) -> dict[str, Any]:
    who = line.get("de")
    person = person_of(who)
    wait = now - at if at else 0
    return {
        "who": who, "text": line.text("texte"), "when": line.get("reçue"), "number": line.get("n°"),
        "href": line.href, "wait": _wait(wait) if at else "", "tone": "danger" if wait >= DAY else
        "warn" if wait >= HOUR else "",
        "exchanges": fiche_url("person", person, "echanges") if is_identifiable(person) else "",
        "forgotten": line.tone == "muted" or line.text("texte") in ("", "—"),
    }


def questions(got: Got) -> Markup | None:
    """Conversations › Questions sans réponse : chaque question dans sa bulle, depuis combien de temps elle attend."""
    table = got.table("Questions sans réponse")
    if table is None:
        notes = got.notes()
        return got.draw("handmade/conversations/questions.html", t=None, items=[], notes=notes) if notes else None
    lines = got.lines("Questions sans réponse")
    instants = _instants(got, "Questions sans réponse", "reçue")
    now = got.env.now
    items = [_question(x, instants[i] if i < len(instants) else 0, now) for i, x in enumerate(lines)]
    oldest = min((a for a in instants if a), default=0)
    where = " sur cette page" if paged(table) else ""
    lede = f"la plus ancienne{where} attend depuis {_wait(now - oldest)} · la plus récente d'abord" if oldest else ""
    return got.draw("handmade/conversations/questions.html", t=table, items=items, notes=[], lede=lede)


TABS: dict[str, Any] = {
    "fil/questions": Tab(questions, *STYLES),
}
