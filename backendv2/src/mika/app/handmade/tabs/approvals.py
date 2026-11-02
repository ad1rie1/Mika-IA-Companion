"""À valider › Historique des autorisations : ses onglets, chacun dans sa forme (ADR 0177).

- Historique des autorisations : une entrée par demande, la plus récente d'abord, comme les demandes en attente
  (``handmade/approbations/attente.html``) — ce qu'elle voulait faire (le résumé de sa proposition, relu au journal),
  la capacité, puis son parcours : ta décision (par qui, ta note) et son exécution (réussie ou non, ce qu'elle a
  donné). Les décisions et exécutions d'une même demande, sur une page, se réunissent ; la pagination reste celle de
  la page de la console (``pages/approvals.py``), qui reste la source.
"""

from __future__ import annotations

from typing import Any

from markupsafe import Markup

from mika.app.handmade.tabs import Got, Line, Tab, raw_lines
from mika.contracts import runtime as rt
from mika.kernel.inspect import Ref

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


def _proposed(got: Got, seqs: list[int]) -> dict[int, dict[str, str]]:
    """Ce qu'elle voulait faire : le résumé de chaque proposition et à propos de qui, relus au journal."""
    out: dict[int, dict[str, str]] = {}
    for stored in got.ui.kernel.mind.store.get_events(seqs) if seqs else ():
        e = got.ui.decode(stored)
        if e.type.name == rt.EFFECT_PROPOSED.name:
            out[e.seq] = {"summary": e.data.summary.text or "", "about": got.ui.names.who(e.data.context)
                          if e.data.context else ""}
    return out


def historique(got: Got) -> Markup | None:
    """Historique des autorisations : une entrée par demande, sa décision et son exécution."""
    table = got.table("Décisions et exécutions")
    if table is None:
        return None
    groups: dict[str, dict[str, Any]] = {}
    for line, raw in zip(got.lines("Décisions et exécutions"), raw_lines(got, table), strict=False):
        ref = raw.get("proposition")
        key = ref.key if isinstance(ref, Ref) else line.text("proposition")
        group = groups.setdefault(key, {"proposal": key, "link": line.get("proposition"),
                                        "capability": line.get("capacité"),
                                        "key": line.text("capacité (clé)"), "steps": []})
        group["steps"].insert(0, _step(line))  # dans l'ordre où ils sont arrivés : la décision, puis l'exécution
    told = _proposed(got, [int(k) for k in groups if k.isdigit()])
    entries = []
    for g in groups.values():
        steps = g["steps"]
        tones = [s["tone"] for s in steps]
        mark = "danger" if "danger" in tones else "ok" if any(not s["decision"] and s["tone"] == "ok" for s in steps) \
            else "refused" if any(s["decision"] and s["tag"] == "refusé" for s in steps) else "info"
        entries.append({**g, **told.get(int(g["proposal"]) if g["proposal"].isdigit() else 0, {}), "mark": mark})
    return got.draw("handmade/approbations/historique.html", t=table, entries=entries)


TABS: dict[str, Any] = {
    "approbations/historique": Tab(historique, *STYLES),
}
