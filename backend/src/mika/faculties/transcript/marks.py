"""Les repères de temps du fil, tels qu'on les perçoit (ADR 0041) : après un silence (« [25 minutes plus tard] »,
« [le lendemain, mardi 14h13] »), à l'ouverture de l'historique, quand elle lit un message en retard, et pour un message
resté sans réponse. Ils sont calculés en jours vécus et ne dépendent que des instants : le même repère d'un prompt à
l'autre. Ce module n'importe aucun autre module de la faculté."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from mika.contracts import transcript as c
from mika.kernel.clock import MINUTE, local, local_date_of_night
from mika.vocab.circadian import DAYS_FR, MONTHS_FR
from mika.vocab.phrasebook import phrase, phrases

#: Un message qui arrive après un tel silence porte un repère de temps.
MARK_AFTER = 20 * MINUTE

#: Avant cette heure, une heure de la nuit appartient encore à la veille : « le
#: lendemain » se compte en jours vécus, pas en passages de minuit.
DAY_STARTS_AT = 5


def _number(n: int) -> str:
    """Un nombre en lettres (de zéro à treize)."""
    return phrases("transcript.time.numbers")[n]


def _clock(dt: datetime) -> str:
    return phrase("transcript.time.clock", hour=dt.hour, minute=f"{dt.minute:02d}")


def _about(dt: datetime) -> str:
    """L'heure à la demi-heure près : « vers 17h », « vers 17h30 », « vers minuit »."""
    h, m = divmod(((dt.hour * 60 + dt.minute + 15) // 30 * 30) % (24 * 60), 60)
    if h == 0:
        return phrase("transcript.time.about_midnight_half") if m else phrase("transcript.time.about_midnight")
    if h == 12:
        return phrase("transcript.time.about_noon_half") if m else phrase("transcript.time.about_noon")
    return phrase("transcript.time.about_half", hour=h) if m else phrase("transcript.time.about_hour", hour=h)


def _lapse(minutes: int) -> str:
    """Un silence de moins de deux heures, dit comme on le dit (à cinq minutes près)."""
    m = max(5, round(minutes / 5) * 5)
    if m == 30:
        return phrase("transcript.time.half_hour_later")
    if m == 45:
        return phrase("transcript.time.three_quarters_later")
    if m < 55:
        return phrase("transcript.time.minutes_later", minutes=m)
    if m < 75:
        return phrase("transcript.time.hour_later")
    return phrase("transcript.time.hour_half_later") if m < 105 else phrase("transcript.time.two_hours_later")


def _day(dt: datetime) -> str:
    """Le jour et l'heure ; une heure de la nuit dit de quelle nuit il s'agit."""
    if dt.hour < DAY_STARTS_AT:
        return phrase("transcript.time.night_of", eve=DAYS_FR[(dt.weekday() - 1) % 7], weekday=DAYS_FR[dt.weekday()],
                      clock=_clock(dt))
    return phrase("transcript.time.day", weekday=DAYS_FR[dt.weekday()], clock=_clock(dt))


def _date(dt: datetime, year: bool) -> str:
    if year:
        return phrase("transcript.time.date_year", weekday=DAYS_FR[dt.weekday()], day=dt.day,
                      month=MONTHS_FR[dt.month - 1], year=dt.year, clock=_clock(dt))
    return phrase("transcript.time.date", weekday=DAYS_FR[dt.weekday()], day=dt.day, month=MONTHS_FR[dt.month - 1],
                  clock=_clock(dt))


def gap_mark(prev: int, at: int, tz: ZoneInfo, after_us: int = MARK_AFTER) -> str:
    """Le repère d'un message par rapport au précédent, tel qu'on le perçoit :
    rien quand il suit de près ; « 25 minutes plus tard », « une heure plus
    tard », puis « plus tard, vers 17h » le même jour ; « le lendemain, mardi
    14h13 », « cinq jours plus tard, samedi 18h08 », « trois semaines plus
    tard, lundi 19 octobre, 9h02 » au-delà. Compté en jours vécus du calendrier
    local, et fonction des deux instants seulement : le même repère d'un prompt
    à l'autre (le préfixe en cache ne bouge pas)."""
    if at - prev < after_us:
        return ""
    then, now = local(prev, tz), local(at, tz)
    days = (local_date_of_night(at, tz, DAY_STARTS_AT) - local_date_of_night(prev, tz, DAY_STARTS_AT)).days
    if days <= 0:
        minutes = (at - prev) // MINUTE
        if minutes < 110:
            return _lapse(minutes)
        if now.hour < DAY_STARTS_AT:
            return phrase("transcript.time.later_night", about=_about(now))
        return phrase("transcript.time.later", about=_about(now))
    if days == 1:
        return phrase("transcript.time.next_day", day=_day(now))
    if days == 2:
        return phrase("transcript.time.day_after", day=_day(now))
    if days < 7:
        return phrase("transcript.time.days_later_day", days=_number(days), day=_day(now))
    if days == 7:
        lap = phrase("transcript.time.week_later")
    elif days < 14:
        lap = phrase("transcript.time.days_later", days=_number(days))
    elif days < 30:
        lap = phrase("transcript.time.weeks_later", weeks=_number(days // 7))
    elif days < 365:
        months = max(1, round(days / 30.44))
        lap = phrase("transcript.time.month_later") if months == 1 else \
            phrase("transcript.time.months_later", months=_number(months))
    else:
        years = days // 365
        lap = phrase("transcript.time.year_later") if years == 1 else phrase("transcript.time.years_later", years=years)
    return phrase("transcript.time.lapse_date", lapse=lap, date=_date(now, now.year != then.year))


#: au-delà, un message auquel elle répond est un message qu'elle lit en retard (elle dormait, elle était prise)
READ_LATE_US = 20 * MINUTE


def read_late(at: int, now: int, tz: ZoneInfo) -> str:
    """Quand elle lit seulement maintenant un message écrit bien avant (la nuit, pendant qu'elle dormait) : « tu
    ne le lis que maintenant, jeudi vers 7h ». Sans ça, le repère du message (« vers 3h ») lui fait répondre comme
    si elle était éveillée à 3 h (sonde réelle du 2026-10-02 : « non je dors pas », à 7 h 14)."""
    if now - at < READ_LATE_US:
        return ""
    same = local_date_of_night(at, tz, DAY_STARTS_AT) == local_date_of_night(now, tz, DAY_STARTS_AT)
    when = _about(local(now, tz)) if same else _day(local(now, tz))
    return phrase("transcript.time.read_late", when=when)


def opening_mark(at: int, now: int, tz: ZoneInfo) -> str:
    """Le repère absolu d'un message qui ouvre l'historique : « lundi 28
    septembre, 18h02 » (avec l'année quand ce n'est pas celle-ci)."""
    dt = local(at, tz)
    return _date(dt, dt.year != local(now, tz).year)


#: ce que dit le repère d'un message resté sans réponse (la colonne ``unanswered``) : un fait, à la deuxième
#: personne, jamais la cause technique — à « t'es là ? », elle sait qu'elle n'a pas répondu et pourquoi, et ne
#: s'excuse pas d'une panne quand elle s'est tue exprès ; ce qu'elle en dit, elle le décide. Les mots sont sous
#: ``transcript.thread.unanswered`` (persona/voix.yaml) ; un délai dépassé se dit comme une panne.
LEFT_UNANSWERED = {
    c.UNANSWERED_ABSTAINED: "abstained",
    c.UNANSWERED_FAILED: "failed",
    c.UNANSWERED_TIMEOUT: "failed",
    c.UNANSWERED_LATE: "late",
}


def left_unanswered(cause: str | None) -> str:
    """Le repère d'un message resté sans réponse pour ``cause`` (``""`` : répondu, en attente ou pas pour elle)."""
    words = LEFT_UNANSWERED.get(cause or "")
    return phrase(f"transcript.thread.unanswered.{words}") if words else ""
