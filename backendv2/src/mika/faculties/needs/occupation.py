"""Ce qu'elle fait de ses mains : une séance de travail qui l'absorbe (``busy``), une occupation dans sa chambre
qui la nourrit (``occupied``) — elle s'y met, en change ou s'arrête selon ce que dit le monde, et sa fin comble ce
qu'elle nourrit au prorata du temps passé —, et depuis quand rien ne l'occupe (``idle_from``)."""

from __future__ import annotations

from dataclasses import replace

from mika.contracts import body as body_c
from mika.contracts import needs as c
from mika.contracts import world as w
from mika.faculties.needs.faculty import (
    NEEDS,
    OCCUPATION_STALE,
    WORK_STALE,
    NeedsState,
    Occupation,
    _relieve,
    _shared,
    _touch,
)
from mika.faculties.needs.params import NeedsParams, params


def busy(s: NeedsState, now: int) -> bool:
    """Elle travaille en ce moment (une séance en cours, pas plus vieille qu'une heure)."""
    return any(now - t < WORK_STALE for t in s.working.values())


def occupation_end(o: Occupation) -> int:
    """Quand une occupation s'arrête au plus tard : sa fin prévue, sinon ``OCCUPATION_STALE`` après son début."""
    return o.until if o.until is not None else o.since + OCCUPATION_STALE


def occupied(s: NeedsState, now: int) -> bool:
    """Elle est à une occupation qui la nourrit (dessiner, feuilleter un livre), pas encore finie."""
    return s.occupied is not None and now < occupation_end(s.occupied)


def _void_after(o: Occupation, idle_since: int, end: int, p: NeedsParams) -> int:
    """Depuis quand le vide court, une fois l'occupation finie à ``end`` : le vide qu'elle avait avant de s'y mettre
    s'efface au prorata de ce que l'occupation a comblé (pleinement au bout de ``occupied_full_us``) — deux minutes à
    regarder dehors ne valent pas deux heures de répit, une heure à dessiner, si (ADR 0098) ; ce qui s'est passé
    entre-temps (un message) compte en entier."""
    if o.void_from and idle_since <= max(o.since, o.noted):
        share = min(1.0, (end - o.since) / max(1, p.occupied_full_us))
        return max(o.void_from, end - round((o.since - o.void_from) * (1.0 - share)))
    return max(idle_since, end)


def idle_from(s: NeedsState, p: NeedsParams) -> int:
    """Depuis quand rien ne l'occupe : la dernière chose qui s'est passée, ou ce que lui laisse son occupation (à sa
    fin prévue, tant qu'elle dure — ``Empty`` attend qu'elle soit finie)."""
    if s.occupied is None:
        return s.idle_since
    return _void_after(s.occupied, s.idle_since, occupation_end(s.occupied), p)


def _stop(s: NeedsState, t: int, p: NeedsParams) -> NeedsState:
    """Son occupation s'arrête — à ``t``, ou à sa fin prévue si elle est déjà passée : elle comble ce qu'elle
    nourrit, au prorata du temps passé (pleinement au bout de ``occupied_full_us``) ; rien ne l'occupe plus depuis
    sa fin."""
    o = s.occupied
    if o is None:
        return s
    end = max(o.since, min(t, occupation_end(o)))
    share = min(1.0, (end - o.since) / max(1, p.occupied_full_us))
    s = _touch(s, t, p)
    for kind, factor in ((c.EXPRESSION, p.occupied_expression), (c.CURIOSITY, p.occupied_curiosity)):
        if kind in o.nourishes:
            s = _relieve(s, kind, _shared(factor, share), t, p)
    return replace(s, occupied=None, nourished=replace(o, until=end), idle_since=_void_after(o, s.idle_since, end, p))


def _occupy(s: NeedsState, a: w.Activity | None, t: int, p: NeedsParams) -> NeedsState:
    """Ce qu'elle fait de ses mains change : ce qu'elle faisait s'arrête, et une occupation qui nourrit un besoin
    commence — seule la déclaration du monde (``nourishes``) en fait foi, jamais le nom d'une activité."""
    o = s.occupied
    if a is not None and o is not None and (a.name, a.since) == (o.name, o.since):
        return s  # la même, redite
    s = _stop(s, t, p)
    if a is None or not a.nourishes:
        return s
    o = Occupation(a.name, a.since, a.until, tuple(str(k) for k in a.nourishes), void_from=s.idle_since or t,
                   noted=t)
    return replace(_touch(s, t, p), occupied=o, idle_since=t)


@NEEDS.reducer(w.ENDED, w.CHANGED)
def _occupation(s: NeedsState, e, cx) -> NeedsState:
    """Ce que le monde dit de son occupation (une action qui aboutit, un constat, la lassitude qui l'arrête) :
    elle s'y met, en change ou s'arrête."""
    p = params(cx.params)
    for change in e.data.changes:
        if isinstance(change, w.ActorBusy) and change.actor == w.MIKA:
            s = _occupy(s, change.activity, e.at, p)
    return s


@NEEDS.reducer(w.INTENDED)
def _torn_away(s: NeedsState, e, cx) -> NeedsState:
    """Une action qu'elle commence l'arrache à ce qu'elle faisait (la règle du monde) : son occupation s'arrête là."""
    if e.data.intent.actor != w.MIKA or s.occupied is None:
        return s
    return _stop(s, e.at, params(cx.params))


@NEEDS.reducer(body_c.FELL_ASLEEP)
def _fell_asleep(s: NeedsState, e, cx) -> NeedsState:
    """Elle s'endort : elle va se coucher, et ce qu'elle faisait s'arrête."""
    if s.occupied is None:
        return s
    return _stop(s, e.at, params(cx.params))
