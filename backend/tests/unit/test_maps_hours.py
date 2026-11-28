"""Les horaires d'OpenStreetMap (ADR 0244) : ouvert, fermé ou inconnu à un instant donné, à l'heure de Paris, en une
phrase ; la semaine en français ; ce qui sort du sous-ensemble compris ne se devine pas (``unknown``, le texte tel
quel) et rien ne lève jamais."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from mika.adapters.maps import hours as h

PARIS = h.PARIS
#: un mardi de novembre (le 11, l'Armistice, est le mercredi d'avant)
TUESDAY = date(2026, 11, 17)


def at(day: date, hm: str) -> datetime:
    hour, minute = (int(x) for x in hm.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=PARIS)


RESTAURANT = "Tu-Sa 12:00-14:00,19:00-22:30; Su 12:00-14:30; Mo off"


@pytest.mark.parametrize(("when", "state", "text"), [
    (at(TUESDAY, "13:00"), "open", "Ouvert · ferme à 14:00"),
    (at(TUESDAY, "15:00"), "closed", "Ouvre à 19:00"),
    (at(TUESDAY, "22:29"), "open", "Ouvert · ferme à 22:30"),
    (at(TUESDAY, "22:30"), "closed", "Fermé · ouvre demain 12:00"),
    (at(date(2026, 11, 16), "12:30"), "closed", "Fermé · ouvre demain 12:00"),  # le lundi
    (at(date(2026, 11, 22), "15:00"), "closed", "Fermé · ouvre mardi 12:00"),
])
def test_a_restaurant_says_whether_it_is_open_and_until_when(when, state, text):
    assert h.state_at(RESTAURANT, when) == (state, text)


def test_its_week_reads_in_french_with_closed_days_last():
    assert h.week_fr(RESTAURANT, at(TUESDAY, "13:00")) == \
        "mar.–sam. 12:00–14:00, 19:00–22:30 · dim. 12:00–14:30 · lun. fermé"
    assert h.week_fr("Mo-Su 07:00-21:00", at(TUESDAY, "9:00")) == "tous les jours 07:00–21:00"
    assert h.week_fr("24/7", at(TUESDAY, "9:00")) == "tous les jours 24 h/24"
    assert h.week_fr("Mo,We-Fr 09:00-18:00; Tu 14:00-18:00", at(TUESDAY, "9:00")) == \
        "lun., mer.–ven. 09:00–18:00 · mar. 14:00–18:00 · sam.–dim. fermé"
    assert h.week_fr("Sa 11:45-24:00", at(TUESDAY, "9:00")) == "sam. 11:45–24:00 · lun.–ven., dim. fermé"


def test_after_midnight_belongs_to_the_evening_before():
    bar = "Fr-Sa 18:00-02:00"
    saturday_night = at(date(2026, 11, 21), "01:00")
    assert h.state_at(bar, saturday_night) == ("open", "Ouvert · ferme à 02:00")
    assert h.state_at(bar, at(date(2026, 11, 21), "02:00"))[0] == "closed"
    assert h.state_at("Mo-Su 18:00-26:00", at(TUESDAY, "01:30")) == ("open", "Ouvert · ferme à 02:00")
    assert h.state_at("Mo-Su 11:00-24:00", at(TUESDAY, "23:00")) == ("open", "Ouvert · ferme à minuit")
    assert h.week_fr(bar, saturday_night) == "ven.–sam. 18:00–02:00 · lun.–jeu., dim. fermé"


def test_always_open_and_never_open():
    assert h.state_at("24/7", at(TUESDAY, "03:00")) == ("open", "Ouvert 24 h/24")
    assert h.state_at("Mo-Su 00:00-24:00", at(TUESDAY, "03:00")) == ("open", "Ouvert 24 h/24")
    assert h.state_at("off", at(TUESDAY, "12:00")) == ("closed", "Fermé")
    assert h.week_fr("off", at(TUESDAY, "12:00")) == "fermé cette semaine"


def test_french_public_holidays_close_what_says_ph_off():
    office = "Mo-Fr 09:00-18:00; PH off"
    armistice = date(2026, 11, 11)
    assert h.holiday_fr(armistice) and h.holiday_fr(date(2026, 4, 6)) and h.holiday_fr(date(2026, 5, 14))
    assert not h.holiday_fr(TUESDAY) and not h.holiday_fr(date(2026, 4, 3))  # ni le Vendredi saint
    assert h.state_at(office, at(armistice, "10:00")) == ("closed", "Fermé · ouvre demain 09:00")
    assert h.state_at("Mo-Fr 09:00-18:00", at(armistice, "10:00"))[0] == "open"  # sans PH : un jour comme un autre
    assert h.state_at("Mo-Fr 09:00-18:00, PH off", at(armistice, "10:00"))[0] == "closed"
    assert h.week_fr(office, at(TUESDAY, "10:00")) == "lun.–ven. 09:00–18:00 · sam.–dim. fermé · jours fériés fermé"
    market = "Mo-Sa 08:30-20:00; PH Mo-Sa 08:30-18:00; PH Su off"  # un férié selon le jour où il tombe
    assert h.state_at(market, at(armistice, "19:00"))[0] == "closed"
    assert h.state_at(market, at(armistice, "17:00"))[0] == "open"
    assert h.week_fr(market, at(TUESDAY, "10:00")).endswith(
        "jours fériés lun.–sam. 08:30–18:00 · jours fériés dim. fermé")


def test_months_and_dates_select_their_season():
    seasonal = "Jun-Sep Mo-Su 10:00-19:00; Oct-May Sa,Su 10:00-17:00"
    assert h.state_at(seasonal, at(TUESDAY, "12:00")) == ("closed", "Fermé · ouvre samedi 10:00")
    assert h.state_at(seasonal, at(date(2026, 7, 14), "12:00"))[0] == "open"
    assert h.week_fr(seasonal, at(TUESDAY, "12:00")) == "sam.–dim. 10:00–17:00 · lun.–ven. fermé"
    assert h.state_at("Apr-Oct: 07:30-21:00; Nov-Mar: 07:30-17:30", at(TUESDAY, "18:00"))[0] == "closed"
    assert h.state_at("Apr 01-Oct 31 10:00-18:00", at(TUESDAY, "12:00")) == ("closed", "Fermé")
    shop = "Mo-Sa 09:00-19:00; Dec 24,31 09:00-17:00; Jan 01,Dec 25 off"
    assert h.state_at(shop, at(date(2026, 12, 31), "18:00"))[0] == "closed"
    assert h.state_at(shop, at(date(2026, 12, 30), "18:00"))[0] == "open"
    assert h.state_at("Dec 24-Jan 02 off; Mo-Su 10:00-18:00", at(date(2027, 1, 1), "12:00"))[0] == "open"
    assert h.state_at("Mo-Su 10:00-18:00; Dec 24-Jan 02 off", at(date(2027, 1, 1), "12:00"))[0] == "closed"
    dated = "Mo-Fr 09:00-12:00; 2026 Nov 17 off"
    assert h.state_at(dated, at(TUESDAY, "10:00"))[0] == "closed"
    assert h.state_at(dated, at(TUESDAY + timedelta(days=7), "10:00"))[0] == "open"  # seulement cette année-là


#: le LaM dans l'index du Nord (R1-03 : 49 lieux sur 10 250 ont une liste de dates séparées par des virgules)
LAM = "10:00-18:00; Mo off; Jan 01,May 01,Dec 25 off"


@pytest.mark.parametrize("day", [date(2027, 1, 1), date(2027, 5, 1), date(2026, 12, 25)])
def test_a_list_of_dates_keeps_its_off(day):
    """« Jan 01,May 01,Dec 25 off » ferme les trois jours : la virgule d'une liste de dates n'ajoute pas une règle (le
    1er janvier et le 1er mai étaient ouverts 24 h sur 24)."""
    assert h.state_at(LAM, at(day, "11:00"))[0] == "closed"
    assert h.state_at(LAM, at(date(2027, 1, 2), "11:00"))[0] == "open"  # un samedi : ouvert


def test_a_list_of_dates_keeps_its_hours():
    rule = h.parse("Mo-Sa 09:00-19:00; Dec 24,Dec 31 08:00-12:00")
    assert rule.spans(date(2026, 12, 24)) == ((480, 720),) and rule.spans(date(2026, 12, 31)) == ((480, 720),)
    assert rule.spans(date(2026, 12, 23)) == ((540, 1140),)
    assert h.state_at("Mo-Sa 09:00-19:00; Jan 01,Dec 25 off, Su 10:00-12:00", at(date(2026, 11, 22), "11:00"))[0] \
        == "open"  # une règle ajoutée après « off » : toujours lue


def test_spaces_and_an_added_rule_after_a_comma_are_read():
    assert h.state_at("Mo - Fr 08:00 - 12:00, Sa 09:00-12:00", at(date(2026, 11, 21), "10:00"))[0] == "open"
    assert h.state_at("Mo, We 10:00-12:00", at(TUESDAY, "11:00"))[0] == "closed"
    assert h.state_at("Mo-Fr", at(TUESDAY, "03:00"))[0] == "open"  # des jours seuls : le jour entier


@pytest.mark.parametrize("raw", [
    '"Sur rendez-vous"', "Tu-Sa 11:30-14:00 \"Restaurant\"", "sunrise-sunset", "Mo-Fr 10:00+",
    "Mo-Fr 09:00-12:00 || PH off", "SH off; Mo-Fr 09:00-18:00", "Su[1] 10:00-12:00", "week 01-10 Mo 09:00-10:00",
    "easter off", "Mo-Fr 25:00-26:00", "Mo-Fr 10:60-12:00", "Lu-Ve 09:00-18:00", "09h00-18h00", "", "   ", ";",
    "Jun-15 10:00-12:00", "x" * 300, "Mo-Fr 09:00-12:00; nonsense",
])
def test_what_it_does_not_understand_is_unknown_and_kept_as_written(raw):
    """Y compris un texte plus long que la clé d'OpenStreetMap ne le permet (255 caractères)."""
    assert h.parse(raw) is None
    assert h.state_at(raw, at(TUESDAY, "12:00")) == ("unknown", "")
    assert h.week_fr(raw, at(TUESDAY, "12:00")) == " ".join(raw.split())[:h.RAW_MAX]


def test_an_instant_without_a_zone_is_utc_and_paris_decides():
    # 21:00 UTC un mardi d'hiver, 22:00 à Paris
    assert h.state_at("Mo-Su 18:00-21:30", datetime(2026, 11, 17, 21, 0)) == ("closed", "Fermé · ouvre demain 18:00")
    assert h.state_at("Mo-Su 18:00-21:30", datetime(2026, 11, 17, 20, 0, tzinfo=UTC))[0] == "open"


# ── propriétés ──

ANY_TEXT = st.text(alphabet=st.sampled_from(list("MoTuWeThFrSaSuPHJanDecoff0123456789:-,;+ /\"[]")), max_size=60)


@settings(max_examples=400, deadline=None)
@given(raw=ANY_TEXT | st.text(max_size=80), minutes=st.integers(0, 14 * 1440))
def test_nothing_ever_raises(raw, minutes):
    when = at(TUESDAY, "00:00") + timedelta(minutes=minutes)
    state, text = h.state_at(raw, when)
    assert state in ("open", "closed", "unknown") and (text == "") == (state == "unknown")
    assert isinstance(h.week_fr(raw, when), str)


def _hm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


#: une semaine simple : pour chaque jour, jusqu'à trois plages dans la journée qui ne se touchent pas (en quarts
#: d'heure) ; écrite, plus longue que la clé ne le permet, elle est écartée (``assume``)
WEEK = st.lists(
    st.lists(st.integers(0, 95), max_size=6, unique=True).map(sorted).map(
        lambda qs: [(qs[i] * 15, qs[i + 1] * 15) for i in range(0, len(qs) - 1, 2) if qs[i + 1] > qs[i]]),
    min_size=7, max_size=7)


def _written(week: list[list[tuple[int, int]]]) -> str:
    rules = []
    for d, spans in enumerate(week):
        day = h.WEEKDAYS[d]
        rules.append(f"{day} " + (",".join(f"{_hm(a)}-{_hm(b)}" for a, b in spans) if spans else "off"))
    return "; ".join(rules)


@settings(max_examples=300, deadline=None)
@given(week=WEEK, minutes=st.integers(0, 7 * 1440 - 1))
def test_a_written_week_is_open_exactly_in_its_spans(week, minutes):
    """Une semaine tirée au hasard, écrite en ``opening_hours`` : ouvert exactement dans ses plages, et ce qu'on dit
    de la fermeture ou de la réouverture tombe sur une borne de plage."""
    raw = _written(week)
    assume(len(raw) <= h.RAW_MAX)  # la clé d'OpenStreetMap n'en porte pas plus
    monday = date(2026, 11, 16)
    when = at(monday, "00:00") + timedelta(minutes=minutes)
    day, now = when.weekday(), when.hour * 60 + when.minute
    inside = any(a <= now < b for a, b in week[day])
    state, text = h.state_at(raw, when)
    assert state == ("open" if inside else "closed"), (raw, when)
    edges = {_hm(m % 1440) for spans in week for a, b in spans for m in (a, b)} | {"minuit"}
    if state == "open":
        assert any(e in text for e in edges)
    elif any(week):
        assert text == "Fermé" or any(e in text for e in edges)


@settings(max_examples=200, deadline=None)
@given(week=WEEK)
def test_a_written_week_reads_back_day_by_day(week):
    """Chaque jour ouvert de la semaine se retrouve dans le texte, avec ses plages ; un jour fermé est dit fermé."""
    raw = _written(week)
    assume(len(raw) <= h.RAW_MAX)
    text = h.week_fr(raw, at(TUESDAY, "12:00"))
    if not any(week):
        assert text == "fermé cette semaine"
        return
    for spans in week:
        for a, b in spans:
            assert f"{_hm(a)}–{'24:00' if b == 1440 else _hm(b)}" in text
    if not all(week):
        assert "fermé" in text
