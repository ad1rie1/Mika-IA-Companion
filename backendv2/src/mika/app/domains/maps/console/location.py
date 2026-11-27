"""Les morceaux des pages de la localisation (ADR 0119, 0123) : une position que son téléphone a dite (``fix_of``) et ce
que les téléphones lui ont dit, d'une personne ou de tous, par pages (``said_of``). Deux pages les dessinent, sur les
morceaux de gabarit que l'inspecteur garde (``handmade/sens/macros.html``) : Ses sens › Localisation
(``app/domains/senses/console/tabs.py``, qui les lit ici) et l'onglet Sa position de la fiche d'une personne
(``person.py``). Ils se lisent dans la tranche du plugin ``location`` et au journal, ses textes au magasin.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from mika.app.handmade import Look, moment_fr, person_link
from mika.contracts import location as location_c
from mika.kernel.inspect import FORGOTTEN
from mika.plugins.location.inspect import SHOWN as SAID


def _accuracy(m: int) -> str:
    return f"à {m} m près" if m else "précision inconnue"


def _link(page: str, **params: Any) -> str:
    """Une page, et ces paramètres en plus de ceux qu'elle a."""
    return page + ("&" if "?" in page else "?") + urlencode(params) if params else page


def fix_of(look: Look, f: Any, texts: Mapping[str, str]) -> dict[str, Any]:
    return {"place": texts.get(f.label_ref, FORGOTTEN) if f.label_ref else "", "coords": texts.get(f.coords_ref,
            FORGOTTEN), "accuracy": _accuracy(f.accuracy_m), "when": moment_fr(look, f.fixed_at),
            "ago": look.ago(f.fixed_at), "handle": f.handle}


def said_of(look: Look, query: Mapping[str, str], person: str, page: str) -> dict[str, Any]:
    """Ce que les téléphones lui ont dit (d'une personne, ou de tous), du plus récent, par pages."""
    before = int(query.get("avant", 0) or 0) if str(query.get("avant", "")).isdigit() else 0
    got = look.ui.inspection.context().events([location_c.LOCATED, location_c.CLEARED], SAID,
                                              before=before or None, where=("person", person) if person else None)
    entries = []
    for e in got:
        d = e.data
        cleared = e.type.name == location_c.CLEARED.name
        entries.append({"when": moment_fr(look, e.at), "who": person_link(look, d.person), "cleared": cleared,
                        "place": "" if cleared or d.label is None else (d.label.text or FORGOTTEN),
                        "coords": "" if cleared else (d.coords.text or FORGOTTEN),
                        "accuracy": "" if cleared else _accuracy(int(d.accuracy_m))})
    keep = {k: v for k, v in query.items() if k not in ("avant", "flash", "onglet")}
    older = _link(page, **keep, avant=got[-1].seq) if len(got) == SAID else ""
    newer = _link(page, **keep) if before else ""
    return {"entries": entries, "older": older, "newer": newer}
