"""Les courbes de la console, en SVG inline — le **seul** endroit qui fabrique
du balisage à la main. Tout texte y est échappé ; les couleurs viennent de la
feuille de style (classes ``s1``…``s4``), jamais d'un attribut ``style``.

Une échelle par graphe ; une info-bulle sans JavaScript (``<title>`` sur une
zone par instant) ; une coupure de la ligne quand les mesures manquent.

Une courbe a une hauteur fixe et suit la largeur de la page : son tracé s'étire
en largeur seulement (``preserveAspectRatio="none"``, des traits d'épaisseur
constante), et ses graduations, sa légende et ses points vivent hors de
l'étirement (en pixels, ou placés en pourcentage). Leur taille ne dépend jamais
de la largeur de l'écran — une courbe pleine page n'est plus une affiche.
"""

from __future__ import annotations

from collections.abc import Callable
from statistics import median

from markupsafe import Markup, escape

from mika.kernel.inspect import Chart, money_fr, num_fr, pct_fr

#: le tracé : une largeur en unités (étirée), une hauteur en pixels, une marge en haut et en bas (un point au bord
#: reste entier)
W, H, PAD = 1000, 180, 10
#: les graduations : la colonne des valeurs, la ligne des instants (en pixels)
AXIS_W, AXIS_H = 56, 22
SPARK_W, SPARK_H = 120, 30
MAX_STAMPS = 240


def _fmt(value: float, unit: str) -> str:
    """Une graduation à la française (« 0,5 », « 42 % », « 1,25 $ »)."""
    if unit == "%":
        return pct_fr(value)
    if unit == "$":
        return money_fr(value)
    if abs(value - round(value)) < 1e-9 or abs(value) >= 100:
        return num_fr(value, 0)
    text = f"{value:.2f}".rstrip("0").rstrip(".") if abs(value) < 10 else f"{value:.1f}"
    return text.replace("-", "−").replace(".", ",")


def _bounds(chart: Chart) -> tuple[int, int, float, float]:
    points = [(at, v) for s in chart.series for at, v in s.points]
    xs = sorted({at for at, _ in points})
    x0 = chart.since if chart.since is not None else xs[0]
    x1 = chart.until if chart.until is not None else xs[-1]
    if chart.kind == "bars":  # une demi-case de chaque côté : aucune barre ne touche un bord
        gaps = [b - a for a, b in zip(xs, xs[1:], strict=False)]
        half = (median(gaps) if gaps else 86_400_000_000) / 2
        x0, x1 = int(min(x0, xs[0] - half)), int(max(x1, xs[-1] + half))
    if x1 <= x0:
        x1 = x0 + 1
    if chart.y is not None:
        y0, y1 = chart.y
    else:
        ys = [v for _, v in points]
        y0, y1 = min(ys), max(ys)
        if chart.kind == "bars":
            y0 = min(0.0, y0)
        if y1 - y0 < 1e-9:
            y0, y1 = y0 - 1, y1 + 1
        pad = (y1 - y0) * 0.08
        y0, y1 = (y0 if chart.kind == "bars" and y0 == 0 else y0 - pad), y1 + pad
        if all(float(v).is_integer() for v in ys) and y1 - y0 <= 8:  # des comptes : graduations entières
            y0, y1 = float(int(y0)), float(int(y1) + (0 if y1.is_integer() else 1))
    return x0, x1, y0, y1


def _segments(points: list[tuple[int, float]]) -> list[list[tuple[int, float]]]:
    """Une ligne par suite de mesures ; un trou (> 3 fois l'écart habituel) la coupe."""
    if len(points) < 2:
        return [points] if points else []
    gaps = [b[0] - a[0] for a, b in zip(points, points[1:], strict=False)]
    limit = 3 * median(gaps)
    out, cur = [], [points[0]]
    for prev, pt in zip(points, points[1:], strict=False):
        if pt[0] - prev[0] > limit:
            out.append(cur)
            cur = []
        cur.append(pt)
    out.append(cur)
    return out


def _spark(chart: Chart, series: list, x0: int, x1: int, y0: float, y1: float) -> Markup:
    """Une petite tendance (une carte de chiffres) : sans graduation, étirée dans sa case."""

    def x(at: int) -> float:
        return 1 + (at - x0) / (x1 - x0) * (SPARK_W - 2)

    def y(v: float) -> float:
        v = min(max(v, y0), y1)
        return 2 + (1 - (v - y0) / (y1 - y0)) * (SPARK_H - 4)

    parts = [f'<svg class="chart chart-spark" viewBox="0 0 {SPARK_W} {SPARK_H}" role="img" '
             f'aria-label="{escape(chart.title or "courbe")}" preserveAspectRatio="none">']
    for i, s in enumerate(series):
        slot = s.slot or i + 1
        pts = sorted(s.points)
        for seg in _segments(pts):
            d = " ".join(f"{'M' if j == 0 else 'L'}{x(at):.1f},{y(v):.1f}" for j, (at, v) in enumerate(seg))
            parts.append(f'<path class="line s{slot}" d="{d}"/>')
        last_at, last_v = pts[-1]
        parts.append(f'<circle class="dot s{slot}" cx="{x(last_at):.1f}" cy="{y(last_v):.1f}" r="2.5"/>')
    parts.append("</svg>")
    return Markup("".join(parts))


def chart_svg(chart: Chart, when: Callable[[int], str], stamp: Callable[[int, int], str] | None = None) -> Markup:
    """``when`` : l'instant complet (info-bulles) ; ``stamp(instant, étendue)`` : une
    graduation courte (l'heure sur un jour, la date sur des semaines)."""
    series = [s for s in chart.series[:4] if s.points]
    if not series:
        return Markup("")
    x0, x1, y0, y1 = _bounds(chart)
    if chart.kind == "spark":
        return _spark(chart, series, x0, x1, y0, y1)

    def part(at: int) -> float:
        return (at - x0) / (x1 - x0)

    def x(at: int) -> float:
        return part(at) * W

    def y(v: float) -> float:
        v = min(max(v, y0), y1)
        return PAD + (1 - (v - y0) / (y1 - y0)) * (H - 2 * PAD)

    title = escape(chart.title or "courbe")
    short = stamp or (lambda at, span: when(at))
    ticks = 5
    if all(float(v).is_integer() for s in series for _, v in s.points) and 0 < y1 - y0 <= 8:
        ticks = int(y1 - y0) + 1
    plot = [f'<svg class="chart-plot chart-{escape(chart.kind)}" viewBox="0 0 {W} {H}" preserveAspectRatio="none" '
            f'width="100%" height="{H}" role="img" aria-label="{title}">']
    yaxis = [f'<svg class="chart-yaxis" width="{AXIS_W}" height="{H}" aria-hidden="true">']
    for i in range(ticks):
        v = y0 + (y1 - y0) * i / max(1, ticks - 1)
        yy = y(v)
        plot.append(f'<line class="grid" x1="0" x2="{W}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
        yaxis.append(f'<text class="tick" x="{AXIS_W - 10}" y="{yy + 4:.1f}" text-anchor="end">'
                     f'{escape(_fmt(v, chart.unit))}</text>')
    yaxis.append("</svg>")
    if chart.zero is not None and y0 < chart.zero < y1:
        plot.append(f'<line class="zero" x1="0" x2="{W}" y1="{y(chart.zero):.1f}" y2="{y(chart.zero):.1f}"/>')
    for i, s in enumerate(series):
        slot = s.slot or i + 1
        pts = sorted(s.points)
        if chart.kind == "bars":
            bw = max(2.0, min(40.0, W / max(1, len(pts)) * 0.7))
            base = y(max(y0, 0.0) if y0 <= 0 <= y1 else y0)
            for at, v in pts:
                top_y = y(v)
                plot.append(f'<rect class="bar s{slot}" x="{x(at) - bw / 2:.1f}" y="{min(top_y, base):.1f}" '
                            f'width="{bw:.1f}" height="{abs(base - top_y):.1f}"/>')
            continue
        for seg in _segments(pts):
            d = " ".join(f"{'M' if j == 0 else 'L'}{x(at):.1f},{y(v):.1f}" for j, (at, v) in enumerate(seg))
            plot.append(f'<path class="line s{slot}" d="{d}"/>')
        last_at, last_v = pts[-1]
        # un point : un trait nul aux bouts ronds, d'épaisseur constante — il reste rond quand le tracé s'étire
        plot.append(f'<path class="dot s{slot}" d="M{x(last_at):.1f},{y(last_v):.1f}h0.01"/>')
    stamps = sorted({at for s in series for at, _ in s.points})
    if len(stamps) <= MAX_STAMPS:
        by = [dict(s.points) for s in series]
        for j, at in enumerate(stamps):
            a = (x(stamps[j - 1]) + x(at)) / 2 if j else 0.0
            b = (x(at) + x(stamps[j + 1])) / 2 if j + 1 < len(stamps) else float(W)
            values = " · ".join(f"{s.label} {_fmt(d[at], chart.unit)}" for s, d in zip(series, by, strict=True)
                                if at in d)
            plot.append(f'<rect class="hit" x="{a:.1f}" y="0" width="{max(0.5, b - a):.1f}" height="{H}">'
                        f'<title>{escape(when(at))} — {escape(values)}</title></rect>')
    plot.append("</svg>")
    marks = stamps if (chart.kind == "bars" and len(stamps) <= 8 or
                       len(stamps) == 1 and chart.since is None and chart.until is None) else \
        [int(x0 + (x1 - x0) * i / 3) for i in range(4)]
    xaxis = [f'<svg class="chart-xaxis" width="100%" height="{AXIS_H}" aria-hidden="true">']
    for i, at in enumerate(marks):
        pct = part(at) * 100
        anchor = "middle" if chart.kind == "bars" or 0 < i < len(marks) - 1 else "start" if i == 0 else "end"
        xaxis.append(f'<text class="tick" x="{pct:.2f}%" y="15" text-anchor="{anchor}">'
                     f'{escape(short(at, x1 - x0))}</text>')
    xaxis.append("</svg>")
    legend = ""
    if len(series) > 1:
        legend = '<ul class="chart-legend">' + "".join(
            f'<li><span class="chart-key s{s.slot or i + 1}"></span>{escape(s.label)}</li>'
            for i, s in enumerate(series)) + "</ul>"
    return Markup(f'<div class="chart-frame">{legend}<div class="chart-body">{"".join(yaxis)}{"".join(plot)}'
                  f'<span></span>{"".join(xaxis)}</div></div>')
