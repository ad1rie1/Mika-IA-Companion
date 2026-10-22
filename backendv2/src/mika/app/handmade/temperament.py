"""Réglages › Tempérament, dessiné (ADR 0100, 0121) : la forme de son caractère, et partir d'un profil.

Un profil n'est qu'un préréglage du tempérament (``vocab.temperament.apply_profile`` : ses curseurs de caractère, son
humeur de fond, sa réaction, sa défense et ses précisions ; son chronotype et celles de l'opératrice gardés), recalculé à chaque lecture
(``profile_of``). La page le choisit donc ici : ``?profil=<clé>`` pré-remplit le formulaire sans rien enregistrer
(``SettingsSection.prefill``) ; on ajuste, on regarde l'effet, on enregistre une fois.

La forme : tous ses curseurs (les 27 du caractère et son chronotype), rangés par famille dans l'ordre du formulaire,
chaque famille un secteur nommé (chacun de ses 18 profils s'y reconnaît, sa silhouette à côté de son nom). La forme en
place est grise en pointillé quand un profil est proposé, la proposée pleine, dans la couleur d'accent ; chaque sommet
dit sa valeur dans une bulle, ses traits les plus marqués se disent à côté en mots, et ses trois choix (humeur de fond,
quand on la blesse, quand on la touche) en clair.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

from mika.inspector.ui import env
from mika.kernel import forms
from mika.vocab.affect import FR
from mika.vocab.temperament import (
    DEFENSES,
    NOTE_KEYS,
    PERSONALITY,
    PROFILES,
    REACTIONS,
    Temperament,
    apply_profile,
    profile_of,
)

#: le paramètre qui propose un profil
CHOSEN = "profil"
#: la page du tempérament
PAGE = "/inspecteur/reglages/temperament"
#: les axes de la forme, dans le sens des aiguilles d'une montre depuis le haut : tous ses curseurs, dans l'ordre du
#: formulaire (famille par famille)
_SLIDERS = tuple(f for f in forms.describe(Temperament) if f.kind == "slider")
AXES = tuple(f.path for f in _SLIDERS)
#: chaque famille et ses axes, dans l'ordre
FAMILIES = tuple((group, tuple(i for i, f in enumerate(_SLIDERS) if f.group == group))
                 for group in dict.fromkeys(f.group for f in _SLIDERS))
#: les noms courts des axes et des familles sur la figure (la bulle et le formulaire gardent les longs)
SHORT = {"mask": "Masque", "attachment": "Attachement", "stability": "Liens stables", "trust": "Confiance",
         "devotion": "Sa propriétaire", "fragility": "Estime fragile", "admiration": "Admiration",
         "Ce qu'elle fait de ses émotions": "Ce qu'elle en fait", "Son corps et son élan": "Son corps, son élan"}
#: le rayon de la grande forme, celui d'une vignette ; où commencent les noms des axes, où passent ceux des familles
RADIUS, SMALL = 150.0, 20.0
NAMES, FAMILY = RADIUS + 9, 281.0
#: au-delà, la souris ne vise aucun sommet (en unités du dessin, le script de la page)
NEAR = 22
#: les anneaux de la grille ; 0,5, « comme la plupart des gens », est marqué
RINGS = (0.25, 0.5, 0.75, 1.0)
#: un trait est marqué à 0,3 ou moins, à 0,7 ou plus (« TON TEMPÉRAMENT », ADR 0100)
MARKED = 0.2
_ENDS = re.compile(r"\(0 : (.+?) · 1 : (.+?)\)\s*$")


def _sliders() -> dict[str, tuple[str, str, str]]:
    """Chaque curseur : son nom, et les mots de ses deux bouts (lus dans son aide)."""
    out = {}
    for f in forms.describe(Temperament):
        if f.kind == "slider":
            ends = _ENDS.search(f.help or "")
            out[f.path] = (f.label, ends.group(1) if ends else "", ends.group(2) if ends else "")
    return out


def _angle(i: float) -> float:
    return -math.pi / 2 + 2 * math.pi * i / len(AXES)


def _at(angle: float, r: float) -> tuple[float, float]:
    return round(r * math.cos(angle), 1), round(r * math.sin(angle), 1)


def _point(i: int, value: float, radius: float) -> tuple[float, float]:
    return _at(_angle(i), max(0.0, min(1.0, value)) * radius)


def _polygon(values: Sequence[float], radius: float) -> str:
    return " ".join(f"{x},{y}" for x, y in (_point(i, v, radius) for i, v in enumerate(values)))


def _values(t: Temperament) -> list[float]:
    return [float(getattr(t, a)) for a in AXES]


def _number(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",") if v not in (0, 1) else str(int(v))


def _tip(x: float, y: float, lines: Sequence[str]) -> dict[str, Any]:
    """La bulle d'un sommet : au-dessus (au-dessous près du haut), du côté où elle tient, sa largeur estimée."""
    width = max(len(s) for s in lines) * 6.4 + 18
    below = y < -RADIUS * 0.55
    anchor = "end" if x > 40 else "start" if x < -40 else "middle"
    tx = x + (8 if anchor == "start" else -8 if anchor == "end" else 0)
    left = tx - 9 if anchor == "start" else tx - width + 9 if anchor == "end" else tx - width / 2
    top = y + 12 if below else y - 46
    return {"x": round(left, 1), "y": round(top, 1), "w": round(width, 1), "h": 36, "tx": round(tx, 1),
            "t1": round(top + 15, 1), "t2": round(top + 29, 1), "anchor": anchor, "lines": list(lines)}


def view(shown: Temperament, before: Temperament | None = None) -> dict[str, Any]:
    """Ce que la figure montre : la forme (``shown``), celle d'avant (``before``, en pointillé), chaque sommet et sa
    bulle, et ses traits les plus marqués. Le script de la page en reçoit une par profil."""
    sliders = _sliders()
    points = []
    for i, a in enumerate(AXES):
        v = float(getattr(shown, a))
        x, y = _point(i, v, RADIUS)
        name, lo, hi = sliders[a]
        word = lo if v <= 0.5 - MARKED else hi if v >= 0.5 + MARKED else "comme la plupart des gens"
        second = word if before is None else f"{word} · aujourd'hui {_number(float(getattr(before, a)))}"
        points.append({"x": x, "y": y, "title": f"{name} : {_number(v)} — {second}",
                       "tip": _tip(x, y, (f"{name} : {_number(v)}", second))})
    return {"shape": _polygon(_values(shown), RADIUS), "before": _polygon(_values(before), RADIUS) if before else "",
            "points": points, "marked": ", ".join(marked(shown)), "choices": choices(shown, before)}


#: ses trois choix qui ne sont pas des curseurs (leur nom est celui du formulaire)
CHOICES = ("background", "reaction", "defense")


def choices(shown: Temperament, before: Temperament | None = None) -> list[str]:
    """Ses trois choix, en clair, dans l'ordre de ``CHOICES`` ; ce qu'ils étaient, quand un profil les change."""
    reactions, defenses = dict(REACTIONS), dict(DEFENSES)
    said = []
    for of in (lambda t: FR[t.background], lambda t: reactions.get(t.reaction, t.reaction),
               lambda t: defenses.get(t.defense, t.defense)):
        now = of(shown)
        was = of(before) if before is not None else now
        said.append(now + (f" (aujourd'hui {was})" if was != now else ""))
    return said


def _arc(start: float, end: float, r: float) -> str:
    """Un arc de cercle de ``start`` à ``end`` (des angles), dans le sens où il va."""
    (x1, y1), (x2, y2) = _at(start, r), _at(end, r)
    sweep = 1 if end > start else 0
    return f"M{x1},{y1} A{r},{r} 0 {int(abs(end - start) > math.pi)} {sweep} {x2},{y2}"


def _families() -> list[dict[str, Any]]:
    """Chaque famille : son secteur (un coin de la figure, un sur deux teinté), et son nom sur un arc qui embrasse ses
    axes — lu de gauche à droite, à l'endroit en haut comme en bas."""
    out = []
    for n, (group, axes) in enumerate(FAMILIES):
        start, end = _angle(axes[0] - 0.5), _angle(axes[-1] + 0.5)
        (x1, y1), (x2, y2) = _at(start, RADIUS), _at(end, RADIUS)
        bottom = math.sin((start + end) / 2) > 0.05
        pad = 0.02
        name = _arc(end - pad, start + pad, FAMILY + 8) if bottom else _arc(start + pad, end - pad, FAMILY)
        out.append({"sector": f"M0,0 L{x1},{y1} A{RADIUS},{RADIUS} 0 {int(end - start > math.pi)} 1 {x2},{y2} Z",
                    "tinted": n % 2 == 1, "bracket": _arc(_angle(axes[0] - 0.3), _angle(axes[-1] + 0.3), FAMILY - 8),
                    "name": SHORT.get(group, group),
                    "title": group, "path": name, "id": f"temper-famille-{n}"})
    return out


def _named(key: str) -> str:
    return next(f.label for f in forms.describe(Temperament) if f.path == key)


def figure(current: Temperament, proposed: Temperament | None = None) -> dict[str, Any]:
    """La figure : sa grille, ses familles, ses axes nommés (en rayons), et ce qu'elle montre (la forme en place, ou la
    proposée devant elle)."""
    sliders = _sliders()
    labels = []
    for i, a in enumerate(AXES):
        angle = _angle(i)
        x, y = _at(angle, NAMES)
        left = math.cos(angle) < -1e-9
        turn = math.degrees(angle) + (180 if left else 0)
        labels.append({"x": x, "y": y, "turn": round(turn, 1), "anchor": "end" if left else "start",
                       "text": SHORT.get(a, sliders[a][0])})
    return {
        "rings": [{"points": _polygon([r] * len(AXES), RADIUS), "middle": r == 0.5} for r in RINGS],
        "spokes": [_point(i, 1.0, RADIUS) for i in range(len(AXES))], "families": _families(),
        "labels": labels, "count": len(AXES), "choices_named": [_named(k) for k in CHOICES],
        **view(proposed or current, current if proposed is not None else None),
    }


def marked(t: Temperament, limit: int = 6) -> list[str]:
    """Ses traits les plus marqués, des 27 curseurs, en mots : « à fleur de peau (réactivité 0,8) »."""
    sliders = _sliders()
    far = sorted(((abs(float(getattr(t, s)) - 0.5), s) for s in PERSONALITY), reverse=True)
    out = []
    for gap, s in far[:limit]:
        if gap < MARKED - 1e-9:
            break
        name, lo, hi = sliders[s]
        v = float(getattr(t, s))
        out.append(f"{(lo if v < 0.5 else hi) or name} ({name.lower()} {_number(v)})")
    return out


def _sets(key: str) -> str:
    """Ce qu'un profil pose, en écarts au milieu (sur 1–9) et en choix."""
    p = PROFILES[key]
    labels = {s: name for s, (name, _lo, _hi) in _sliders().items()}
    moved = [f"{labels.get(s, s)} {p.values[s]}" for s in PERSONALITY if s in p.values]
    if p.reaction:
        moved.append(f"blessée : {dict(REACTIONS)[p.reaction]}")
    if p.defense:
        moved.append(f"touchée : {dict(DEFENSES)[p.defense]}")
    return " · ".join(moved) or "5 partout"


def head(current: Temperament, query: Mapping[str, str]) -> Markup:
    """Le haut de la page : la forme de son caractère, partir d'un profil, et ses 18 profils (repliés)."""
    chosen = str(query.get(CHOSEN, ""))
    chosen = chosen if chosen in PROFILES else ""
    proposed = apply_profile(current, chosen) if chosen else None
    if proposed == current:
        proposed = None  # c'est déjà le sien
    now = profile_of(current)
    traits = dict(NOTE_KEYS)
    profiles = [{"key": k, "label": p.label, "summary": p.summary, "sets": _sets(k), "on": k == now,
                 "notes": [f"{traits[s]} : « {n} »" for s, n in p.notes.items()],
                 "proposed": k == chosen, "href": f"{PAGE}?" + urlencode({CHOSEN: k}),
                 "shape": _polygon(_values(apply_profile(current, k)), SMALL)} for k, p in PROFILES.items()]
    # ce que le script de la page montre quand on change de profil, sans rien remplir : une vue par profil (devant la
    # forme en place), et la forme en place seule
    alone = view(current)
    views = {}
    for k in PROFILES:
        under = apply_profile(current, k)
        views[k] = alone if under == current else view(under, current)
    data = {"current": alone, "profiles": views, "labels": {k: p.label for k, p in PROFILES.items()},
            "now": now, "shown": chosen if proposed is not None else now, "near": NEAR}
    return Markup(env.get_template("handmade/reglages/temperament.html").render(
        figure=figure(current, proposed), now=PROFILES[now].label if now else "",
        chosen=PROFILES[chosen].label if chosen else "", proposing=proposed is not None, profiles=profiles,
        reset=PAGE, small_rings=_polygon([1.0] * len(AXES), SMALL), page=PAGE, param=CHOSEN, selected=chosen or now,
        choices=[(k, f"{p.label} — {p.summary}") for k, p in PROFILES.items()], data=data))


def prefill(current: Temperament, query: Mapping[str, str]) -> Temperament | None:
    """Le tempérament que le formulaire montre : celui du profil proposé (``?profil=``), rien n'est enregistré."""
    chosen = str(query.get(CHOSEN, ""))
    return apply_profile(current, chosen) if chosen in PROFILES else None
