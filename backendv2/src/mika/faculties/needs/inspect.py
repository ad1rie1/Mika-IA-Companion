"""Ce que les besoins montrent à un opérateur : leur tension, leur courbe,
l'envie dominante dans la barre de vitaux.

Lecture seule : la lecture est celle du fait (même instant) ; les courbes
viennent des séries mesurées toutes les dix minutes (``needs.social``,
``needs.expression``, ``needs.curiosite``).
"""

from __future__ import annotations

from mika.contracts import needs as c
from mika.faculties.needs import NEEDS, NeedsParams, NeedsState, _tau, busy, describe, params
from mika.kernel.clock import DAY, HOUR
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Block,
    Chart,
    Column,
    Fields,
    InspectContext,
    Meter,
    Note,
    Param,
    Ref,
    Series,
    Table,
    Text,
    Vital,
    When,
)

#: son nom en français, et ce qui le comble
NAMES = {c.SOCIAL: "compagnie", c.EXPRESSION: "s'exprimer", c.CURIOSITY: "apprendre"}
RELIEF = {
    c.SOCIAL: "un message qu'on lui adresse, parler à quelqu'un",
    c.EXPRESSION: "répondre, et plus encore prendre la parole d'elle-même ; travailler, un peu",
    c.CURIOSITY: "un message, une croyance nouvelle, un pas d'exploration",
}
#: la clé de la série de chaque besoin
SERIES = {c.SOCIAL: "social", c.EXPRESSION: "expression", c.CURIOSITY: "curiosite"}
#: au-delà, un besoin se dit dans le prompt (voir ``describe``)
PRESSING = 0.75

PERIODS = (("24h", "24 h"), ("7j", "7 jours"))
_SPANS = {"24h": DAY, "7j": 7 * DAY}
PERIOD = Param("periode", "Période", kind="select", choices=PERIODS, default="24h")


def _p(frame: Frame) -> NeedsParams:
    return params(frame.env.params_of("needs", frame.root))


def _values(r: c.NeedsReading) -> dict[str, float]:
    return {c.SOCIAL: r.social, c.EXPRESSION: r.expression, c.CURIOSITY: r.curiosity}


def _tone(value: float) -> str:
    return "warn" if value >= PRESSING else ""


# ── La barre de vitaux, les séries ────────────────────────────────────────


@NEEDS.vital("envie", label="Envie", order=40)
def _vital(s: NeedsState, frame: Frame) -> Vital:
    r = frame.get(c.NEEDS)
    kind = r.dominant
    value = _values(r)[kind]
    return Vital(NAMES[kind], tone=_tone(value), ratio=value,
                 hint=" ".join(describe(r)) or f"rien de pressant (tension {round(value * 100)} %)",
                 href=Ref.view("needs", "needs", "Besoins"))


@NEEDS.series("social", label="Compagnie", unit="%", lo=0.0, hi=1.0)
def _social(s: NeedsState, frame: Frame) -> float:
    return frame.get(c.NEEDS).social


@NEEDS.series("expression", label="S'exprimer", unit="%", lo=0.0, hi=1.0)
def _expression(s: NeedsState, frame: Frame) -> float:
    return frame.get(c.NEEDS).expression


@NEEDS.series("curiosite", label="Apprendre", unit="%", lo=0.0, hi=1.0)
def _curiosity(s: NeedsState, frame: Frame) -> float:
    return frame.get(c.NEEDS).curiosity


# ── La vue ────────────────────────────────────────────────────────────────


@NEEDS.inspect("needs", title="Besoins", section="vie", order=30, params=[PERIOD],
               description="Ses besoins de compagnie, de s'exprimer et d'apprendre : leur tension et leur courbe.")
def _inspect(s: NeedsState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _p(frame)
    r = frame.get(c.NEEDS)
    values = _values(r)
    span = _SPANS.get(str(ctx.value(PERIOD.name) or ""), DAY)
    since = frame.now - span
    rows = tuple((
        NAMES[k],
        Meter(values[k], f"{round(values[k] * 100)} %", tone=_tone(values[k])),
        f"{_tau(k, p):.1f} h",
        RELIEF[k],
        When(s.levels[k].at) if k in s.levels and s.levels[k].at else Text("—", kind="muted"),
    ) for k in c.KINDS)
    return [
        Table((Column("besoin"), Column("tension", hint="monte vers 100 % avec le temps, retombe quand il est comblé"),
               Column("horizon", "num", hint="le temps caractéristique de sa remontée"), Column("ce qui le comble"),
               Column("dernier relevé", "fit")), rows, title="Ses besoins"),
        Note(" ".join(describe(r)) or "Rien de pressant : aucun besoin ne se dit dans le prompt.",
             title="ce qu'elle en dit"),
        Chart(tuple(Series(NAMES[k], tuple(ctx.series(f"needs.{SERIES[k]}", since, frame.now)), slot=i + 1)
                    for i, k in enumerate(c.KINDS)),
              kind="line", title="Ses besoins dans le temps", unit="%", y=(0.0, 1.0), since=since, until=frame.now,
              empty="pas encore de mesure (une toutes les dix minutes) : la courbe se remplira"),
        Fields((
            ("rien ne s'est passé depuis", ctx.when(s.idle_since) if s.idle_since else "—"),
            ("dernier vide ressenti", ctx.when(s.felt_at) if s.felt_at else "—"),
            ("le vide se ressent après", f"{p.idle_before_empty_us / HOUR:.1f} h sans rien"),
            ("le vide se creuse", f"de {p.empty_intensity:g} à {p.empty_max:g}, +{p.empty_growth_per_h:g} par heure"),
            ("en ce moment", "elle travaille (pas de vide)" if busy(s, frame.now) else "—"),
            ("solitude plutôt qu'ennui", f"quand la compagnie dépasse {p.lonely_from:.0%}"),
            ("pousse à parler (compagnie)", f"au-delà de {p.social_floor:.0%}"),
            ("pousse à parler (s'exprimer)", f"au-delà de {p.expression_floor:.0%}"),
        ), title="En détail", columns=2),
    ]
