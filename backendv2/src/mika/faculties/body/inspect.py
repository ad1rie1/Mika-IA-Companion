"""Ce que le corps montre à un opérateur : le sommeil, le rythme, l'énergie.

Lecture seule : les mêmes fonctions que les faits et le processus de sommeil,
au même instant ; les dernières transitions viennent du journal.
"""

from __future__ import annotations

from mika.contracts import body as c
from mika.faculties.body import BODY, FOG, BodyState, energy, gate, night, params, rhythm
from mika.faculties.body import sleep as sl
from mika.kernel.frame import Frame
from mika.kernel.inspect import Block, Fields, InspectContext, Note, Table
from mika.vocab import circadian
from mika.vocab.affect import FR

TRANSITIONS_SHOWN = 12

SLEEP_FR = {
    c.SleepPhase.AWAKE: "éveillée",
    c.SleepPhase.LIGHT_SLEEP: "sommeil léger",
    c.SleepPhase.DEEP_SLEEP: "sommeil profond",
    c.SleepPhase.REM: "sommeil paradoxal (elle rêve)",
}
VETO_FR = {
    c.ASLEEP: "retenues : elle dort",
    c.WOKEN_AT_NIGHT: "retenues : tirée du sommeil en pleine nuit, elle va se rendormir",
    c.WAKING: "retenues : elle émerge à peine (inertie du réveil)",
}


def _hm(minutes: int) -> str:
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}"


def _gate_fr(s: BodyState, frame: Frame) -> str:
    m = gate(s, frame)
    if m.veto is not None:
        return VETO_FR.get(m.veto, m.veto)
    if m.shift:
        return f"plus rares (décalage {m.shift:+.1f})"
    return "libres"


def _transitions(ctx: InspectContext) -> tuple[tuple[str, str, str], ...]:
    out = []
    for e in ctx.events([c.FELL_ASLEEP, c.WOKE], TRANSITIONS_SHOWN):
        what = "s'endort" if e.type.name == c.FELL_ASLEEP.name else "se réveille"
        out.append((ctx.when(int(e.data.at)), what, f"{float(e.data.pressure):.0%}"))
    return tuple(out)


@BODY.inspect("rythme", title="Rythme")
def _rhythm_view(s: BodyState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = params(frame.env.params_of("body", frame.root))
    tz = frame.env.tz_of(frame.root)
    now = frame.now
    profile = rhythm(p)
    level = energy(s, now, p, tz)
    sleep = s.sleep
    upper, lower = sl.thresholds(now, p.sleep, tz, p.shift_minutes)
    nxt = sl.next_transition(sleep, now, p.sleep, tz, p.shift_minutes, night(p))
    what = "se réveiller" if sleep.asleep else "s'endormir"
    start, end = night(p)
    fog = next((text for limit, text in FOG if level < limit), "")
    return [
        Fields((
            ("sommeil", SLEEP_FR[sl.phase(sleep, now, p.sleep)]),
            ("depuis", ctx.when(sleep.since) if sleep.since else "aucune transition observée"),
            ("réveillée par un message", "oui" if sleep.woken_by_message and not sleep.asleep else "non"),
            ("phase du jour", circadian.PHASE_FR[circadian.phase_of(frame.local(), profile)]),
            ("énergie", f"{level:.0%} ({circadian.energy_word(level)})"),
            ("pression de sommeil", f"{sl.pressure(sleep, now, p.sleep, tz):.0%}"),
            ("seuils à cette heure", f"s'endormir au-dessus de {upper:.0%}, se réveiller sous {lower:.0%}"),
            ("dernière interaction", ctx.when(sleep.active_at) if sleep.active_at else "—"),
            ("prochaine transition", f"{what} — {ctx.when(nxt)}" if nxt is not None else f"{what} : pas dans les 48 h"),
            ("sa nuit", f"de {_hm(start)} à {_hm(end)}"),
            ("chronotype", f"décalage de {p.shift_minutes:+d} min"),
            ("initiatives et travail ordinaires", _gate_fr(s, frame)),
            ("barre de réveil", f"{c.WAKE_BAR:.0f} (log-odds) : une raison qui la passe à elle seule "
                                "(un rappel urgent) passe outre"),
        ), title="Son corps"),
        Note(circadian.describe(frame.local(), profile, level) + (f" {fog}" if fog else "")),
        Table(("phase", "début", "teinte"),
              tuple((circadian.PHASE_FR[ph], _hm(m), FR[profile.tints[ph]]) for ph, m in profile.starts),
              title="Son rythme"),
        Table(("quand", "transition", "pression"), _transitions(ctx), title="Dernières transitions",
              empty="aucune transition encore"),
    ]

