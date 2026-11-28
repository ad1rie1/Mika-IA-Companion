"""Les assertions d'un scénario : chacune dit pourquoi elle existe.

Formes : ``invariant`` (doit tenir partout), ``band`` (une mesure dans une
plage), ``control`` (la version permise de l'interdit arrive bien — sinon le
détecteur est mort). Une assertion échouée nomme ce qui manque.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    why: str
    ok: bool
    detail: str = ""
    kind: str = "invariant"


def invariant(name: str, ok: bool, why: str, detail: str = "") -> Check:
    return Check(name, why, bool(ok), detail, "invariant")


def control(name: str, ok: bool, why: str, detail: str = "") -> Check:
    return Check(name, why, bool(ok), detail, "contrôle")


def band(name: str, value: float | None, why: str, *, lo: float | None = None, hi: float | None = None) -> Check:
    if value is None:
        return Check(name, why, False, "aucune mesure", "bande")
    ok = (lo is None or value >= lo) and (hi is None or value <= hi)
    span = f"[{'-∞' if lo is None else lo}, {'+∞' if hi is None else hi}]"
    return Check(name, why, ok, f"{value:.3f} dans {span}" if ok else f"{value:.3f} hors de {span}", "bande")
