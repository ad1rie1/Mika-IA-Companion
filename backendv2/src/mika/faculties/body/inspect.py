"""Ce que le corps montre à un opérateur : le sommeil, le rythme, l'énergie.

Lecture seule : les mêmes fonctions que les faits et le processus de sommeil,
au même instant ; ses dernières nuits viennent de sa tranche, les dernières
transitions du journal ; les courbes
de l'énergie et de la pression de sommeil sont mesurées toutes les dix
minutes (``body.energie``, ``body.pression``).
"""

from __future__ import annotations

from mika.contracts import body as c
from mika.contracts import identity as identity_c
from mika.faculties.body import (
    BODY,
    NIGHT_TOLD_US,
    BodyParams,
    BodyState,
    Night,
    energy,
    fog,
    gate,
    last_night,
    night,
    params,
    rhythm,
)
from mika.faculties.body import sleep as sl
from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Block,
    Chart,
    Entry,
    Fields,
    InspectContext,
    Meter,
    Note,
    Pager,
    Ref,
    Series,
    Stat,
    Stats,
    Table,
    Text,
    Timeline,
    Vital,
    When,
    num_fr,
)
from mika.vocab import circadian
from mika.vocab.affect import emotion_cell

#: ses transitions (s'endormir, se réveiller), par page : tout le journal, du plus récent au plus ancien
TRANSITIONS_PAGE = 25

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


def _percent(value: float) -> str:
    return f"{round(value * 100)} %"


def _p(frame: Frame) -> BodyParams:
    return params(frame.env.params_of("body", frame.root))


def _gate_fr(s: BodyState, frame: Frame) -> str:
    m = gate(s, frame)
    if m.veto is not None:
        return VETO_FR.get(m.veto, m.veto)
    if m.shift:
        return f"plus rares (décalage {num_fr(m.shift, 1, signed=True)})"
    return "libres"


def _pressure(s: BodyState, frame: Frame) -> float:
    return max(0.0, min(1.0, sl.pressure(s.sleep, frame.now, _p(frame).sleep, frame.env.tz_of(frame.root))))


# ── La barre de vitaux, les séries ────────────────────────────────────────


@BODY.vital("energie", label="Énergie", order=20)
def _energy_vital(s: BodyState, frame: Frame) -> Vital:
    p = _p(frame)
    level = frame.get(c.ENERGY)
    tired = level < p.tired_below
    return Vital(_percent(level), tone="warn" if tired else "", ratio=level,
                 hint=f"énergie {circadian.energy_word(level)}" + (" : elle est fatiguée" if tired else ""),
                 href=Ref.view("body", "rythme", "Rythme"))


@BODY.vital("sommeil", label="Sommeil", order=30)
def _sleep_vital(s: BodyState, frame: Frame) -> Vital:
    phase = frame.get(c.SLEEP)
    since = s.sleep.since
    hint = f"depuis {frame.local(since):%H:%M}" if since else ""
    return Vital(SLEEP_FR[phase], tone="" if phase is c.SleepPhase.AWAKE else "info", hint=hint,
                 href=Ref.view("body", "rythme", "Rythme"))


@BODY.series("energie", label="Énergie", unit="%", lo=0.0, hi=1.0)
def _energy_series(s: BodyState, frame: Frame) -> float:
    return frame.get(c.ENERGY)


@BODY.series("pression", label="Pression de sommeil", unit="%", lo=0.0, hi=1.0)
def _pressure_series(s: BodyState, frame: Frame) -> float:
    return _pressure(s, frame)


# ── Rythme ────────────────────────────────────────────────────────────────


ROUSED_FR = {c.CLOSE_ONE: "quelqu'un de proche", c.URGENT: "quelque chose d'urgent",
             c.CALL: "un réveil par API qui passe outre son rythme"}


def _who(frame: Frame, person: str, handle: str) -> str:
    if person:
        name = frame.get(identity_c.IDENTITY(person)).name
        if name:
            return f"« {name} »"
    return "quelqu'un"


def _transitions(ctx: InspectContext, frame: Frame) -> tuple[tuple[Entry, ...], Pager]:
    """Une page de ses transitions (``?avant=`` : la suite, plus ancienne) —
    les réveils par un message compris, et les messages qui ont attendu son
    réveil."""
    found = ctx.events([c.FELL_ASLEEP, c.WOKE, c.ROUSED, c.WAITED], TRANSITIONS_PAGE + 1,
                       before=ctx.int_param("avant", 0) or None)
    page = found[:TRANSITIONS_PAGE]
    out = []
    for e in page:
        href = Ref("event", str(e.seq), "l'événement")
        if e.type.name == c.ROUSED.name and e.data.reason == c.CALL:
            out.append(Entry(e.at, "tirée du sommeil par un réveil par API", ROUSED_FR[c.CALL], tone="warn",
                             href=href))
            continue
        if e.type.name == c.ROUSED.name:
            out.append(Entry(e.at, "tirée du sommeil par un message",
                             f"de {_who(frame, e.data.person, e.data.handle)} — "
                             f"{ROUSED_FR.get(e.data.reason, e.data.reason)}", tone="warn", href=href))
            continue
        if e.type.name == c.WAITED.name:
            out.append(Entry(e.at, "un message attend son réveil",
                             f"de {_who(frame, e.data.person, e.data.handle)} : elle dort, elle y répondra au réveil",
                             tone="muted", href=href))
            continue
        asleep = e.type.name == c.FELL_ASLEEP.name
        out.append(Entry(int(e.data.at), "s'endort" if asleep else "se réveille",
                         f"pression de sommeil {_percent(float(e.data.pressure))}", tone="info" if asleep else "ok",
                         href=href))
    older = (("avant", str(page[-1].seq)),) if len(found) > TRANSITIONS_PAGE else ()
    return tuple(out), Pager(param="avant", size=TRANSITIONS_PAGE, older=older)


def _duration(us: int) -> str:
    minutes = max(0, round(us / MINUTE))
    return f"{minutes // 60} h {minutes % 60:02d}"


def _rousings(frame: Frame, n: Night) -> str:
    if not n.rousings:
        return "—"
    return " ; ".join(f"{frame.local(r.at):%H:%M} — "
                      + (ROUSED_FR[c.CALL] if r.reason == c.CALL else
                         f"{_who(frame, r.person, r.handle)} ({ROUSED_FR.get(r.reason, r.reason)})")
                      for r in n.rousings)


def _nights(s: BodyState, frame: Frame) -> Table:
    """Ses dernières nuits, de la plus récente à la plus ancienne : ce qu'elle a dormi (sans les moments où un
    message l'a tenue éveillée), qui l'a tirée du sommeil, si elle a veillé tard — et, pour celle qui vient de
    finir, ce qu'elle en sait (« courte »)."""
    told = last_night(s, frame.now, _p(frame), frame.env.tz_of(frame.root))
    rows = []
    for n in reversed(s.nights):
        slept = max(0, n.end - n.start - n.awake_us)
        rows.append((
            When(n.start, relative=False),
            When(n.end, relative=False) if n.end else Text("elle dort encore", kind="muted"),
            _duration(slept) if n.end else "—",
            _rousings(frame, n),
            "oui" if n.late else "non",
            ("courte" if told.short else "ordinaire") if told is not None and n is s.nights[-1] else "",
        ))
    return Table(("endormie", "réveillée", "dormi", "tirée du sommeil", "veillé tard", "ce qu'elle en sait ce matin"),
                 tuple(rows), title="Ses dernières nuits",
                 empty="aucune nuit encore : la première s'inscrira à son prochain endormissement",
                 caption=f"Une semaine au plus. Jusqu'à {NIGHT_TOLD_US // HOUR} h après son réveil, elle sait "
                         "comment s'est passée la dernière (« bien dormi ? »).")


@BODY.inspect("rythme", title="Rythme", section="vie", order=40,
              description="Son sommeil, son énergie, sa pression de sommeil et son rythme circadien.")
def _rhythm_view(s: BodyState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _p(frame)
    tz = frame.env.tz_of(frame.root)
    now = frame.now
    profile = rhythm(p)
    level = energy(s, now, p, tz)
    sleep = s.sleep
    pressure = _pressure(s, frame)
    upper, lower = sl.thresholds(now, p.sleep, tz, p.shift_minutes)
    nxt = sl.next_transition(sleep, now, p.sleep, tz, p.shift_minutes, night(p))
    what = "se réveiller" if sleep.asleep else "s'endormir"
    start, end = night(p)
    foggy = fog(level) or ""
    tired = level < p.tired_below
    phase = circadian.phase_of(frame.local(), profile)
    since = now - DAY
    transitions, pager = _transitions(ctx, frame)
    return [
        Stats((
            Stat("sommeil", SLEEP_FR[sl.phase(sleep, now, p.sleep)],
                 sub=f"phase du jour : {circadian.PHASE_FR[phase]}"),
            Stat("énergie", Meter(level, _percent(level), tone="warn" if tired else ""),
                 sub=circadian.energy_word(level) + (" — fatiguée" if tired else ""), tone="warn" if tired else ""),
            Stat("pression de sommeil", Meter(pressure, _percent(pressure)),
                 sub=f"s'endormir au-dessus de {_percent(upper)}, se réveiller sous {_percent(lower)}"),
            Stat("prochaine transition", When(nxt) if nxt is not None else Text("pas dans les 48 h", kind="muted"),
                 sub=what),
        ), title="Son corps"),
        Note(circadian.describe(frame.local(), profile, level) + (f" {foggy}" if foggy else "")),
        Chart((Series("Énergie", tuple(ctx.series("body.energie", since, now)), slot=1),
               Series("Pression de sommeil", tuple(ctx.series("body.pression", since, now)), slot=2)),
              kind="line", title="Énergie et pression de sommeil (24 h)", unit="%", y=(0.0, 1.0), since=since,
              until=now, empty="pas encore de mesure (une toutes les dix minutes) : la courbe se remplira"),
        Fields((
            ("sommeil", SLEEP_FR[sl.phase(sleep, now, p.sleep)]),
            ("depuis", ctx.when(sleep.since) if sleep.since else "aucune transition observée"),
            ("réveillée par un message", "oui" if sleep.woken_by_message and not sleep.asleep else "non"),
            ("messages qui attendent son réveil", str(len(s.waiting)) if s.waiting else "aucun"),
            ("phase du jour", circadian.PHASE_FR[phase]),
            ("prochaine transition", f"{what} — {ctx.when(nxt)}" if nxt is not None else f"{what} : pas dans les 48 h"),
            ("dernière interaction", ctx.when(sleep.active_at) if sleep.active_at else "—"),
            ("sa nuit", f"de {_hm(start)} à {_hm(end)}"),
            ("chronotype", f"décalage de {p.shift_minutes:+d} min"),
            ("initiatives et travail ordinaires", _gate_fr(s, frame)),
            ("barre de réveil", f"{c.WAKE_BAR:.0f} (log-odds) : une raison qui la passe à elle seule "
                                "(un rappel urgent) passe outre"),
        ), title="En détail", columns=2),
        Table(("phase", "début", "teinte"),
              tuple((circadian.PHASE_FR[ph], _hm(m), emotion_cell(profile.tints[ph])) for ph, m in profile.starts),
              title="Son rythme"),
        _nights(s, frame),
        Timeline(transitions, title="Dernières transitions", empty="aucune transition encore", pager=pager),
    ]
