"""Les courbes de la console, en SVG inline — le **seul** endroit qui fabrique
du balisage à la main. Tout texte y est échappé ; les couleurs viennent de la
feuille de style (classes ``s1``…``s4``), jamais d'un attribut ``style``.

Une échelle par graphe ; une info-bulle sans JavaScript (``<title>`` sur une
zone par instant) ; une coupure de la ligne quand les mesures manquent.
"""

from __future__ import annotations

from collections.abc import Callable
from statistics import median

from markupsafe import Markup, escape

from mika.kernel.inspect import Chart, money_fr, num_fr, pct_fr

W, H = 960, 240
LEFT, RIGHT, TOP, BOTTOM = 52, 16, 30, 28
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


def chart_svg(chart: Chart, when: Callable[[int], str], stamp: Callable[[int, int], str] | None = None) -> Markup:
    """``when`` : l'instant complet (info-bulles) ; ``stamp(instant, étendue)`` : une
    graduation courte (l'heure sur un jour, la date sur des semaines)."""
    series = [s for s in chart.series[:4] if s.points]
    if not series:
        return Markup("")
    x0, x1, y0, y1 = _bounds(chart)
    spark = chart.kind == "spark"
    w, h = (SPARK_W, SPARK_H) if spark else (W, H)
    left, right, top, bottom = (1, 1, 2, 2) if spark else (LEFT, RIGHT, TOP, BOTTOM)

    def x(at: int) -> float:
        return left + (at - x0) / (x1 - x0) * (w - left - right)

    def y(v: float) -> float:
        v = min(max(v, y0), y1)
        return top + (1 - (v - y0) / (y1 - y0)) * (h - top - bottom)

    title = escape(chart.title or "courbe")
    parts = [f'<svg class="chart chart-{escape(chart.kind)}" viewBox="0 0 {w} {h}" role="img" '
             f'aria-label="{title}"' + (' preserveAspectRatio="none"' if spark else "") + ">"]
    short = stamp or (lambda at, span: when(at))
    ticks = 5
    if not spark and all(float(v).is_integer() for s in series for _, v in s.points) and 0 < y1 - y0 <= 8:
        ticks = int(y1 - y0) + 1
    if not spark:
        for i in range(ticks):
            v = y0 + (y1 - y0) * i / max(1, ticks - 1)
            yy = y(v)
            parts.append(f'<line class="grid" x1="{left}" x2="{w - right}" y1="{yy:.1f}" y2="{yy:.1f}"/>')
            parts.append(f'<text class="tick" x="{left - 6}" y="{yy + 3:.1f}" text-anchor="end">'
                         f'{escape(_fmt(v, chart.unit))}</text>')
        stamps_all = sorted({at for s in series for at, _ in s.points})
        marks = stamps_all if (chart.kind == "bars" and len(stamps_all) <= 8 or
                               len(stamps_all) == 1 and chart.since is None and chart.until is None) else \
            [int(x0 + (x1 - x0) * i / 3) for i in range(4)]
        for i, at in enumerate(marks):
            anchor = "middle" if chart.kind == "bars" else "start" if i == 0 else "end" if i == len(marks) - 1 \
                else "middle"
            parts.append(f'<text class="tick" x="{x(at):.1f}" y="{h - 8}" text-anchor="{anchor}">'
                         f'{escape(short(at, x1 - x0))}</text>')
        if chart.zero is not None and y0 < chart.zero < y1:
            parts.append(f'<line class="zero" x1="{left}" x2="{w - right}" y1="{y(chart.zero):.1f}" '
                         f'y2="{y(chart.zero):.1f}"/>')
    for i, s in enumerate(series):
        slot = s.slot or i + 1
        pts = sorted(s.points)
        if chart.kind == "bars":
            n = max(1, len(pts))
            bw = max(2.0, min(24.0, (w - left - right) / n * 0.7))
            base = y(max(y0, 0.0) if y0 <= 0 <= y1 else y0)
            for at, v in pts:
                top_y = y(v)
                parts.append(f'<rect class="bar s{slot}" x="{x(at) - bw / 2:.1f}" y="{min(top_y, base):.1f}" '
                             f'width="{bw:.1f}" height="{abs(base - top_y):.1f}" rx="2"/>')
            continue
        for seg in _segments(pts):
            d = " ".join(f"{'M' if j == 0 else 'L'}{x(at):.1f},{y(v):.1f}" for j, (at, v) in enumerate(seg))
            parts.append(f'<path class="line s{slot}" d="{d}"/>')
        last_at, last_v = pts[-1]
        parts.append(f'<circle class="dot s{slot}" cx="{x(last_at):.1f}" cy="{y(last_v):.1f}" '
                     f'r="{2.5 if spark else 4}"/>')
    if not spark:
        if len(series) > 1:
            lx = left
            for i, s in enumerate(series):
                slot = s.slot or i + 1
                parts.append(f'<line class="line s{slot}" x1="{lx}" x2="{lx + 14}" y1="10" y2="10"/>')
                label = escape(s.label)
                parts.append(f'<text class="legend" x="{lx + 18}" y="14">{label}</text>')
                lx += 26 + 7 * len(s.label)
        stamps = sorted({at for s in series for at, _ in s.points})
        if len(stamps) <= MAX_STAMPS:
            by = [dict(s.points) for s in series]
            for j, at in enumerate(stamps):
                lo = x(stamps[j - 1]) if j else left
                hi = x(stamps[j + 1]) if j + 1 < len(stamps) else w - right
                a, b = (lo + x(at)) / 2 if j else left, (x(at) + hi) / 2 if j + 1 < len(stamps) else w - right
                values = " · ".join(f"{s.label} {_fmt(d[at], chart.unit)}" for s, d in zip(series, by, strict=True)
                                    if at in d)
                parts.append(f'<rect class="hit" x="{a:.1f}" y="{top}" width="{max(1.0, b - a):.1f}" '
                             f'height="{h - top - bottom}"><title>{escape(when(at))} — {escape(values)}</title></rect>')
    parts.append("</svg>")
    return Markup("".join(parts))
