#!/usr/bin/env python3
"""Les icônes de l'app (ADR 0235), tirées du jeu de la maquette (`frontend/Android/maquette/index.html`, le même trait
que le frontendv2 : 1,7 sur une grille de 24) : un vecteur Android par symbole, `res/drawable/ic_m_<nom>.xml`.

Une seule source : on retouche une icône dans la maquette, puis on relance

    python3 frontend/Android/tools/icones.py           # écrit les vecteurs
    python3 frontend/Android/tools/icones.py --check   # échoue si un vecteur a vieilli

Les cercles et les rectangles deviennent des chemins ; un cercle rempli (`fill="currentColor"`) reste plein. La teinte
vient de Compose (`Icon(tint = …)`) : la couleur écrite ici ne se voit jamais.
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ICI = Path(__file__).resolve().parent
SOURCE = ICI.parent / "maquette" / "index.html"
SORTIE = ICI.parent / "app" / "src" / "main" / "res" / "drawable"
PREFIXE = "ic_m_"


class Sprite(HTMLParser):
    """Les symboles du sprite : leur nom, et leurs formes (balise, attributs)."""

    def __init__(self) -> None:
        super().__init__()
        self.symboles: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self._courant: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "symbol" and a.get("id", "").startswith("i-"):
            self._courant = a["id"][2:]
            self.symboles[self._courant] = []
        elif self._courant and tag in ("path", "circle", "rect"):
            self.symboles[self._courant].append((tag, a))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "symbol":
            self._courant = None


def nombre(x: float) -> str:
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def chemin(tag: str, a: dict[str, str]) -> str:
    if tag == "path":
        return a["d"]
    if tag == "circle":
        cx, cy, r = (float(a[k]) for k in ("cx", "cy", "r"))
        return (f"M{nombre(cx - r)},{nombre(cy)}a{nombre(r)},{nombre(r)} 0 1,0 {nombre(2 * r)},0"
                f"a{nombre(r)},{nombre(r)} 0 1,0 {nombre(-2 * r)},0Z")
    x, y, w, h = (float(a[k]) for k in ("x", "y", "width", "height"))
    rx = min(float(a.get("rx") or 0), w / 2, h / 2)
    if not rx:
        return f"M{nombre(x)},{nombre(y)}h{nombre(w)}v{nombre(h)}h{nombre(-w)}Z"
    n = nombre
    return (f"M{n(x + rx)},{n(y)}h{n(w - 2 * rx)}a{n(rx)},{n(rx)} 0 0,1 {n(rx)},{n(rx)}v{n(h - 2 * rx)}"
            f"a{n(rx)},{n(rx)} 0 0,1 {n(-rx)},{n(rx)}h{n(-(w - 2 * rx))}a{n(rx)},{n(rx)} 0 0,1 {n(-rx)},{n(-rx)}"
            f"v{n(-(h - 2 * rx))}a{n(rx)},{n(rx)} 0 0,1 {n(rx)},{n(-rx)}Z")


def vecteur(nom: str, formes: list[tuple[str, dict[str, str]]]) -> str:
    lignes = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f"<!-- Généré par frontend/Android/tools/icones.py depuis la maquette (« i-{nom} ») : ne pas retoucher à la main. -->",
        '<vector xmlns:android="http://schemas.android.com/apk/res/android"',
        '    android:width="24dp"',
        '    android:height="24dp"',
        '    android:viewportWidth="24"',
        '    android:viewportHeight="24">',
    ]
    for tag, a in formes:
        d = re.sub(r"\s+", " ", chemin(tag, a)).strip()
        if a.get("fill") == "currentColor":
            lignes.append(f'    <path android:fillColor="#FF000000" android:pathData="{d}" />')
        else:
            lignes.append(f'    <path android:strokeColor="#FF000000" android:strokeWidth="1.7" '
                          f'android:strokeLineCap="round" android:strokeLineJoin="round" android:pathData="{d}" />')
    lignes.append("</vector>")
    return "\n".join(lignes) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    sprite = Sprite()
    sprite.feed(SOURCE.read_text(encoding="utf-8"))
    attendus = {f"{PREFIXE}{nom.replace('-', '_')}.xml": vecteur(nom, formes) for nom, formes in sprite.symboles.items()}
    presents = {p.name for p in SORTIE.glob(f"{PREFIXE}*.xml")}
    vieux = sorted(n for n, texte in attendus.items()
                   if not (SORTIE / n).exists() or (SORTIE / n).read_text(encoding="utf-8") != texte)
    orphelins = sorted(presents - set(attendus))
    if check:
        if vieux or orphelins:
            print(f"Icônes à régénérer : {', '.join(vieux + orphelins)}", file=sys.stderr)
            return 1
        print(f"{len(attendus)} icônes à jour.")
        return 0
    for nom in vieux:
        (SORTIE / nom).write_text(attendus[nom], encoding="utf-8")
    for nom in orphelins:
        (SORTIE / nom).unlink()
    print(f"{len(attendus)} icônes ({len(vieux)} écrites, {len(orphelins)} retirées).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
