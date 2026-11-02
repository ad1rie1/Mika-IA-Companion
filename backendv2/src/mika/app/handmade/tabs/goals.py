"""Activité › Buts : ses onglets, chacun dans sa forme (ADR 0177), dans le vocabulaire de la fiche d'un but
(``app/handmade/goal.py``).

- Buts vivants : ce qu'elle a entrepris en une bande de chiffres (combien, en pause, ses séances de l'heure sur son
  plafond, quand elle pourra entreprendre d'elle-même) ; puis, côte à côte, ses explorations — chacune avec ses
  séances sur son plafond et son envie qui s'use — et ses rappels, chacun à sa date, le plus proche d'abord.
- Clos : ce qu'il en est sur la page (tant d'aboutis, de bloqués…), puis une entrée par but clos — son issue en
  marque, ce qu'il a donné ou pourquoi il s'est arrêté, cité ; en deux colonnes sur un grand écran.

Les listes, leurs filtres (sorte, autorité) et leur pagination restent ceux de la faculté (``faculties/goals``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from markupsafe import Markup

from mika.app.handmade import MONTHS, Look
from mika.app.handmade.tabs import Got, Line, Tab, blank, gauge, instant, pairs, raw_lines, rest, text
from mika.inspector.ui import PREFIX
from mika.kernel.clock import DAY

STYLES = ("handmade/buts.css",)
#: une sorte de but, telle que la faculté l'écrit : un rappel (à sa date) ; le reste s'explore
REMINDER = "rappel"
#: le statut ordinaire d'un but vivant : il se tait
ORDINARY = frozenset({"en cours"})
#: l'issue d'un but clos, telle que la faculté l'écrit, et sa marque
ISSUES = {"abouti": "done", "abandonné": "dropped", "annulé": "dropped", "bloqué": "stuck", "en échec": "stuck"}


def _ratio(said: str) -> dict[str, Any] | None:
    """« 2 / 8 » : fait sur plafond, et sa part (0–100) ; rien si ce n'en est pas un."""
    try:
        done, cap = (int(part.strip()) for part in said.split("/", 1))
    except ValueError:
        return None
    return {"done": done, "cap": cap, "w": round(100 * min(1.0, done / cap), 1) if cap else 0.0}


# ── Buts vivants ──────────────────────────────────────────────────────────


def _live(look: Look, line: Line, raw: Mapping[str, Any]) -> dict[str, Any]:
    status = line.get("statut")
    due = instant(raw.get("échéance"))
    nxt = line.get("prochaine séance")
    local = look.frame.local(due) if due else None
    return {"title": line["titre"], "href": line.href, "n": line.text("but"), "kind": line.text("sorte"),
            "authority": line.text("autorité"), "status": status,
            "quiet": blank(status) or text(status) in ORDINARY, "paused": line.tone == "warn",
            "owner": None if blank(line.get("pour qui")) else line.get("pour qui"),
            "steps": _ratio(line.text("séances")), "wish": gauge(line.get("envie")),
            "next": None if blank(nxt) else nxt, "due": line.get("échéance") if due else None, "at": due,
            "day": look.day(due) if due else "", "late": 0 < due < look.now,
            "cal": {"d": local.day, "m": MONTHS[local.month - 1], "hm": local.strftime("%H:%M")} if local else None,
            "detail": rest(line, ("but", "autorité", "envie", "séances", "prochaine séance"))}


def vivants(got: Got) -> Markup | None:
    """Buts › vivants : ce qu'elle a entrepris en chiffres ; ses explorations et ses rappels, côte à côte."""
    t, facts = got.table("Buts vivants"), got.fields("Ce qu'elle a entrepris")
    if t is None or facts is None:
        return None
    f = pairs(facts)
    look = Look.of(got.ui, DAY)
    items = [_live(look, x, r) for x, r in zip(got.lines("Buts vivants"), raw_lines(got, t), strict=False)]
    # un rappel se range à sa date, le plus proche d'abord ; sans date, après les autres
    reminders = sorted((x for x in items if x["kind"] == REMINDER), key=lambda x: x["at"] or 1 << 62)
    explorations = [x for x in items if x["kind"] != REMINDER]
    hour = _ratio(text(f.get("séances dans l'heure")))
    paused = text(f.get("en pause")) or "0"
    band = {"t": "stats", "title": "", "items": [
        {"label": "Vivants", "value": f.get("vivants") or {"t": "text", "text": "0"}, "sub": "explorations et rappels"},
        {"label": "En pause", "value": f.get("en pause") or {"t": "text", "text": "0"},
         "sub": "figés jusqu'à leur reprise", "tone": "warn" if paused not in ("0", "") else ""},
        {"label": "Séances dans l'heure", "value": f.get("séances dans l'heure") or {"t": "text", "text": "—"},
         "sub": "sur son plafond par heure",
         "tone": "warn" if hour and hour["cap"] and hour["done"] >= hour["cap"] else ""},
        {"label": "Entreprendre d'elle-même", "value": f.get("entreprendre d'elle-même") or {"t": "text", "text": "—"},
         "sub": "un nouveau but à elle"},
        {"label": "Dernier blocage", "value": f.get("dernier blocage sur ce qu'elle avait entrepris")
         or {"t": "text", "text": "—"}, "sub": "sur ce qu'elle avait entrepris",
         "href": f"{PREFIX}/buts/clos"}]}
    filtered = bool(got.query.get("sorte") or got.query.get("autorite"))
    return got.draw("handmade/buts/vivants.html", t=t, band=band, explorations=explorations, reminders=reminders,
                    filtered=filtered, notes=got.notes())


# ── Clos ──────────────────────────────────────────────────────────────────


def _closed(line: Line) -> dict[str, Any]:
    issue = line.get("issue")
    said = text(issue)
    result = line.get("raison ou résultat")
    return {"title": line["titre"], "href": line.href, "n": line.text("but"), "issue": issue,
            "mark": ISSUES.get(said, "dropped"), "kind": line.text("sorte"), "authority": line.text("autorité"),
            "when": line.get("clos"), "result": None if blank(result) else result,
            "owner": None if blank(line.get("pour qui")) else line.get("pour qui"),
            "detail": rest(line, ("but", "sorte", "autorité"))}


def clos(got: Got) -> Markup | None:
    """Buts › Clos : une entrée par but clos, son issue en marque, ce qu'il a donné."""
    t = got.table("Buts clos")
    if t is None:
        return None
    items = [_closed(x) for x in got.lines("Buts clos")]
    tally: dict[str, dict[str, Any]] = {}
    for x in items:
        said = text(x["issue"])
        if said:
            tally.setdefault(said, {"text": said, "tone": (x["issue"] or {}).get("tone", ""), "n": 0})["n"] += 1
    return got.draw("handmade/buts/clos.html", t=t, items=items, tally=list(tally.values()), notes=got.notes())


TABS: dict[str, Any] = {
    "buts/vivants": Tab(vivants, *STYLES),
    "buts/clos": Tab(clos, *STYLES),
}
