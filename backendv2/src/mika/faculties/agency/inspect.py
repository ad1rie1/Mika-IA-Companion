"""Ce que l'initiative montre à un opérateur : son budget du jour, sa période
réfractaire, ce qu'elle a dit d'elle-même et si on lui a répondu.

Lecture seule : la lecture est celle du fait (même instant) ; ses prises de
parole sont relues dans le fil de conversation.
"""

from __future__ import annotations

from mika.contracts import agency as c
from mika.contracts import attention as attention_c
from mika.contracts import identity as identity_c
from mika.contracts import transcript as transcript_c
from mika.faculties.agency import AGENCY, AgencyParams, AgencyState, _params, restraint
from mika.kernel.clock import HOUR, MINUTE, local
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Block,
    Cell,
    Column,
    Disclosure,
    Entry,
    Fields,
    InspectContext,
    Meter,
    Ref,
    Stat,
    Stats,
    Table,
    Text,
    Timeline,
    When,
)
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable

#: ses dernières prises de parole d'elle-même, relues dans le fil
SPOKEN_SHOWN = 20
EXCERPT = 160


def _name(frame: Frame, handle: str) -> str:
    if not handle:
        return "quiconque était là"
    name = frame.get(identity_c.IDENTITY(handle)).name
    return f"« {name} » ({handle})" if name else handle


def _restraint_fr(frame: Frame) -> str:
    m = restraint(frame)
    if m.veto == c.DAILY_CAP:
        return "retenues : le plafond du jour est atteint"
    if m.veto is not None:
        return f"retenues : {m.veto}"
    return f"plus rares (décalage {m.shift:+.1f})" if m.shift else "libres"


def _spoken(ctx: InspectContext) -> list[tuple[int, str, str | None, int]]:
    """Ce qu'elle a dit d'elle-même (salutations et rappels compris), et quand
    la personne lui a écrit depuis (0 : pas encore) : (instant, poignée, texte, réponse)."""
    if ctx.store is None:
        return []
    t = transcript_c.THREAD_TABLE
    rows = ctx.store.query_mind(
        f"SELECT m.at, m.person, m.text, (SELECT MIN(u.at) FROM {t} u WHERE u.role='user' AND u.person=m.person "
        f"AND u.id>m.id) FROM {t} m WHERE m.role='assistant' AND m.kind=? ORDER BY m.id DESC LIMIT ?",
        (str(Kind.INITIATIVE), SPOKEN_SHOWN))
    return [(int(at), str(person or ""), text, int(answered or 0)) for at, person, text, answered in rows]


def _excerpt(text: str | None) -> str:
    if text is None:
        return "(oublié)"
    return text if len(text) <= EXCERPT else text[:EXCERPT - 1] + "…"


def _entry(frame: Frame, ctx: InspectContext, at: int, handle: str, text: str | None, answered: int) -> Entry:
    person = frame.get(identity_c.PERSON(handle)) if handle else ""
    name = _name(frame, person)
    href = Ref.subject("person", person, name) if is_identifiable(person) else None
    if not handle:
        tone, meta = "muted", "à personne en particulier"
    elif answered:
        tone, meta = "ok", f"répondue — {ctx.when(answered)}"
    else:
        tone, meta = "warn", "sans réponse pour l'instant"
    return Entry(at, f"à {name}", _excerpt(text), tone=tone, href=href, meta=meta)


def _stretch(s: AgencyState, p: AgencyParams, ignored: int) -> float:
    """La période réfractaire allongée par les initiatives ignorées d'affilée."""
    return min(p.max_refractory_us, (s.refractory_us or p.refractory_us) * p.ignored_backoff ** max(0, ignored))


@AGENCY.inspect("initiatives", title="Initiatives", section="decisions", order=50,
                description="Combien elle prend la parole d'elle-même, ce qui la retient, et si on lui répond.")
def _inspect(s: AgencyState, frame: Frame, ctx: InspectContext) -> list[Block]:
    p = _params(frame.env.params_of("agency", frame.root))
    r = frame.get(c.AGENCY)
    ignored = frame.get(attention_c.IGNORED)
    now = frame.now
    capped = r.initiatives_today >= p.daily_cap
    refractory: Cell
    if r.refractory_until > now:
        refractory, refractory_sub = When(r.refractory_until), "encore retenue jusque-là"
    elif r.refractory_until:
        refractory, refractory_sub = Text("terminée", kind="muted"), f"depuis {ctx.when(r.refractory_until)}"
    else:
        refractory, refractory_sub = Text("—", kind="muted"), "aucune initiative encore"
    stretch = _stretch(s, p, ignored)
    tz = frame.env.tz_of(frame.root)
    today = frame.local().date()
    counted = tuple((When(t), "oui" if local(t, tz).date() == today else "non") for t in reversed(s.initiatives))
    spoken = _spoken(ctx)
    return [
        Stats((
            Stat("aujourd'hui", Meter(r.initiatives_today / max(1, p.daily_cap), f"{r.initiatives_today} / {p.daily_cap}",
                                      tone="warn" if capped else ""),
                 sub="plafond atteint" if capped else "initiatives ordinaires comptées", tone="warn" if capped else ""),
            Stat("période réfractaire", refractory, sub=refractory_sub),
            Stat("ignorées d'affilée", ignored, tone="warn" if ignored else "",
                 sub=f"période allongée à {stretch / MINUTE:.0f} min" if ignored else "on lui répond"),
            Stat("initiatives ordinaires", _restraint_fr(frame), sub="saluer, dire un rappel promis : hors budget"),
        ), title="Son budget"),
        Timeline(tuple(_entry(frame, ctx, *row) for row in spoken), title="Ce qu'elle a dit d'elle-même",
                 empty="elle n'a encore rien dit d'elle-même"),
        Fields((
            ("dernière initiative comptée", ctx.when(r.last_initiative_at) if r.last_initiative_at else "—"),
            ("durée tirée à la dernière", f"{(s.refractory_us or p.refractory_us) / MINUTE:.0f} min"),
            ("allongement par ignorée", f"×{p.ignored_backoff:g}, au plus {p.max_refractory_us / HOUR:.0f} h"),
            ("dernier murmure", ctx.when(r.murmured_at) if r.murmured_at else "—"),
        ), title="En détail", columns=2),
        Disclosure("Initiatives comptées (dernières 24 h)", (
            Table((Column("quand", "fit"), "aujourd'hui"), counted, empty="aucune initiative comptée"),)),
    ]
