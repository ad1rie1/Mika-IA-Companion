"""À valider › Historique des autorisations : ses onglets, chacun dans sa forme (ADR 0177).

- Historique des autorisations : une entrée par demande tranchée, la plus récente d'abord, comme les demandes en
  attente (``handmade/approbations/attente.html``) — ce qu'elle voulait faire (le résumé de sa proposition, relu au
  journal), la capacité (sa clé au survol), ce qu'elle concerne, puis son parcours : ta décision (par qui, ta note) et
  son exécution (réussie ou non, ce qu'elle a donné). La page de la console (``pages/approvals.py``) reste la
  source : elle pagine par demande (sa décision, ses exécutions relues avec elle : une demande ne se coupe jamais
  entre deux pages), la filtre par sorte (des puces) et par issue (un bouton à choix au bout de la barre d'onglets).
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from mika.app.handmade.tabs import Got, Line, Tab, blank, raw_lines
from mika.contracts import runtime as rt
from mika.inspector.pages.approvals import ALL, HISTORY_PARAMS, HISTORY_SORTS, HISTORY_TABLE, ISSUE, KIND
from mika.kernel.inspect import Ref, read_params

STYLES = ("handmade/approbations.css",)
#: le premier mot du détail d'une ligne, et ce qu'il dit
VERDICTS = {"approuvé": ("approuvé", "ok"), "refusé": ("refusé", ""), "réussi": ("exécuté", "ok"),
            "échec": ("en échec", "danger")}


def _step(line: Line) -> dict[str, Any]:
    said = line.text("détail")
    word = said.split(" ", 1)[0]
    tag, tone = VERDICTS.get(word, (line.text("quoi"), "info"))
    rest = said[len(word):].strip().removeprefix("—").strip() if word in VERDICTS else said
    return {"decision": line.text("quoi") == "décidé", "tag": tag, "tone": tone, "text": rest,
            "when": line.get("quand"), "href": line.href}


def _proposed(got: Got, seqs: list[int]) -> dict[int, str]:
    """Ce qu'elle voulait faire : le résumé de chaque proposition, relu au journal."""
    out: dict[int, str] = {}
    for stored in got.ui.kernel.mind.store.get_events(seqs) if seqs else ():
        e = got.ui.decode(stored)
        if e.type.name == rt.EFFECT_PROPOSED.name:
            out[e.seq] = e.data.summary.text or ""
    return out


def historique(got: Got) -> Markup | None:
    """Historique des autorisations : une entrée par demande tranchée, sa décision et son exécution."""
    table = got.table(HISTORY_TABLE)
    if table is None:
        return None
    groups: dict[str, dict[str, Any]] = {}
    for line, raw in zip(got.lines(HISTORY_TABLE), raw_lines(got, table), strict=False):
        ref = raw.get("proposition")
        key = ref.key if isinstance(ref, Ref) else line.text("proposition")
        group = groups.setdefault(key, {"proposal": key, "link": line.get("proposition"),
                                        "capability": line.get("capacité"),
                                        "about": None if blank(line.get("concerne")) else line.get("concerne"),
                                        "steps": []})
        group["steps"].insert(0, _step(line))  # dans l'ordre où ils sont arrivés : la décision, puis l'exécution
    told = _proposed(got, [int(k) for k in groups if k.isdigit()])
    entries = []
    for g in groups.values():
        steps = g["steps"]
        tones = [s["tone"] for s in steps]
        mark = "danger" if "danger" in tones else "ok" if any(not s["decision"] and s["tone"] == "ok" for s in steps) \
            else "refused" if any(s["decision"] and s["tag"] == "refusé" for s in steps) else "info"
        entries.append({**g, "summary": told.get(int(g["proposal"]) if g["proposal"].isdigit() else 0, ""),
                        "mark": mark})
    values, _ = read_params(HISTORY_PARAMS, got.query)
    return got.draw("handmade/approbations/historique.html", t=table, entries=entries, chips=got.nav(HISTORY_SORTS),
                    notes=got.notes(), filtered=bool(values[KIND]) or values[ISSUE] != ALL)


TABS: dict[str, Any] = {
    "approbations/historique": Tab(historique, *STYLES),
}
