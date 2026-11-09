"""Relations & échanges › Conversations : ses onglets dans leur forme (ADR 0177) : avec qui elle parle, ce qui attend,
ses réponses jugées.

- **Par personne** (ADR 0181) : comme une messagerie — une ligne par personne, tous ses moyens de communication réunis,
  la conversation la plus récente d'abord : son avatar à la couleur de ce qu'elle ressent envers elle (et sa présence,
  comme sur Personnes), son nom, par où, l'heure ; le dernier message et s'il est d'elle ; les questions qui attendent
  sa réponse et combien de messages. Une ligne s'ouvre sur leur conversation ; le filtre par nom, la pagination et la
  bascule « Tableau » sont ceux de la faculté.
- **Questions sans réponse** : une file, comme le fil des messages la dirait — chaque question dans sa bulle, de qui,
  quand, et depuis combien de temps elle attend (en avant, une attente longue dite) ; sur sa ligne, le message source
  et la conversation avec cette personne. L'aide de la faculté au pied ; la pagination et la bascule « Tableau »
  sont les siennes.
- **Ses réponses jugées** (ADR 0121) : le message, sa réponse, l'avis de l'opératrice et ce qu'elle aurait dû dire ; son
  filtre et sa pagination sont ceux de la faculté, une liste qu'il ne reconnaît pas rend la main à ses blocs.

Les données restent celles de la faculté du fil (``transcript``) ; l'instant de chaque question se lit à la liste
telle qu'elle l'a déclarée (le temps d'attente, pas une date relative).
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from mika.app.handmade import Look, person_card, plain, presences, span
from mika.app.handmade.tabs import Got, Line, Tab, blank, paged, raw_rows, text
from mika.app.handmade.tabs.people import person_of
from mika.inspector import render
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.ui import env
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.inspect import Badge, Row, When
from mika.vocab.people import is_identifiable

STYLES = ("handmade/fil.css",)


# ── Par personne ──────────────────────────────────────────────────────────


def _person(line: Line, look: Look, online: dict[str, dict[str, Any]]) -> dict[str, Any]:
    who = line.get("avec")
    person = person_of(who)
    face = person_card(look, person, online.get(person)) if person else None
    name = text(who) or "quelqu'un"
    last = line.text("dernier message")
    return {
        "name": name, "initial": name[:1].upper(), "href": line.href or str((who or {}).get("href") or ""),
        "emotion": face["felt"]["emotion"] if face and face["felt"] else "neutral",
        "online": bool(face and face["online"]), "composing": bool(face and face["composing"]),
        "closeness": face["closeness"] if face else "", "by": "" if blank(line.get("par")) else line.text("par"),
        "when": line.get("le dernier"), "last": "" if last in ("", "—") else last,
        "mine": line.text("de") == "elle", "count": line.text("messages"),
        "questions": None if blank(line.get("questions")) else line.get("questions"),
    }


def conversations(got: Got) -> Markup | None:
    """Conversations › Par personne : une ligne par personne, son dernier message, ce qui attend sa réponse."""
    table = got.table("Ses conversations")
    if table is None:
        notes = got.notes()
        return got.draw("handmade/conversations/par_personne.html", t=None, items=[], notes=notes) if notes else None
    look = Look.of(got.ui, DAY)
    online = presences(look)
    items = [_person(x, look, online) for x in got.lines("Ses conversations")]
    waiting = sum(1 for x in items if x["questions"])
    where = " sur cette page" if paged(table) else ""
    said = str(got.query.get("q") or "").strip()
    lede = (f"{waiting} avec une question sans réponse{where} · " if waiting else "") \
        + (f"le dernier message où « {said} » a été dit" if said else "la plus récente d'abord") \
        + " ; une ligne s'ouvre sur leur conversation"
    return got.draw("handmade/conversations/par_personne.html", t=table, items=items, notes=[], lede=lede)


# ── Questions sans réponse ────────────────────────────────────────────────


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


# ── Ses réponses jugées ───────────────────────────────────────────────────

#: le titre de sa liste chez la faculté
JUDGED = "Ses réponses jugées"


def judged(got: Got) -> Markup | None:
    """Conversations › Ses réponses jugées : le message, sa réponse, ton avis, ce qu'elle aurait dû dire."""
    table = got.raw_table(JUDGED)
    if table is None:
        return None
    look = Look.of(got.ui, DAY)
    shown = render.Env(when=got.ui.when_long, now=look.now)
    verdicts = []
    for row, cell in raw_rows(table):
        verdict, when = cell.get("avis"), cell.get("quand")
        should = plain(cell.get("ce qu'elle aurait dû dire"))
        verdicts.append({
            "ok": isinstance(verdict, Badge) and verdict.tone == "ok",
            "verdict": plain(verdict),
            "who": render.cell(cell["avec"], shown) if cell.get("avec") is not None else None,
            "when": f"{look.date(when.at)}, {look.hm(when.at)}" if isinstance(when, When) and when.at else "",
            "asked": plain(cell.get("on lui avait écrit")), "said": plain(cell.get("sa réponse")),
            "should": "" if should == "—" else should, "why": render.href(row.href) if row.href else "",
        })
    pager = render.block(table, shown, got.query).get("pager")
    return Markup(env.get_template("handmade/conversations/judged.html").render(
        verdicts=verdicts, pager=pager, empty=table.empty))


TABS: dict[str, Any] = {
    "fil/jugees": Tab(judged),
    "fil/conversations": Tab(conversations, *STYLES),
    "fil/questions": Tab(questions, *STYLES),
}
