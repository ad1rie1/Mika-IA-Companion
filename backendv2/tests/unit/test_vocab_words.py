"""Le français des phrases qui nomment quelqu'un : « des nouvelles d'Adrien », jamais « de Adrien » (sonde réelle
du 2026-10-02 : « J'aimerais bien avoir des nouvelles de Adrien »)."""

from __future__ import annotations

import pytest

from mika.kernel.clock import DAY, HOUR, MINUTE
from mika.sim.lane import PARIS, at_paris
from mika.vocab.days import ago_words, part_of_day, since_fr, when_fr, window_of
from mika.vocab.phrasebook import family
from mika.vocab.words import elided, fold, stems
from tests.architecture.test_phrasebook import uses


@pytest.mark.parametrize("word, before, expected", [
    ("Adrien", "de", "d'Adrien"),
    ("Émilie", "que", "qu'Émilie"),
    ("Hugo", "de", "d'Hugo"),
    ("Yves", "que", "qu'Yves"),
    ("Yanis", "que", "que Yanis"),  # un y qui sonne comme une consonne
    # contre-exemples : une consonne, un nom entre guillemets, « quelqu'un »
    ("Chloé", "de", "de Chloé"),
    ("Léo", "que", "que Léo"),
    ("« Adrien »", "de", "de « Adrien »"),
    ("quelqu'un", "de", "de quelqu'un"),
])
def test_de_and_que_elide_before_a_vowel(word, before, expected):
    assert elided(word, before) == expected


def test_a_ligature_folds_like_its_letters():
    """« sœur » et « soeur » se recoupent : NFKD ne décompose pas les ligatures (lot H-A)."""
    assert fold("Sœur Lætitia") == "soeur laetitia"
    assert stems("ma sœur vient samedi") & stems("la soeur d'Alice")


@pytest.mark.parametrize("text, expected", [
    ("tu te souviens de ce que je t'ai dit lundi matin ?", (5, 5, 12)),  # le lundi 5 octobre, le matin
    ("hier soir on a parlé de quoi ?", (10, 17, 24)),
    ("avant-hier", (9, 0, 24)),
    ("ce matin", (11, 5, 12)),
    ("ce que tu fais", None),  # contre-exemples : rien de temporel
    ("on se voit demain ?", None),
])
def test_a_moment_said_in_words_is_found_in_time(text, expected):
    """« lundi matin », dit un dimanche à 15 h : le dernier lundi passé, de 5 h à midi."""
    now = at_paris(2026, 10, 11, 15, 0)  # le dimanche 11 octobre
    got = window_of(text, now, PARIS)
    if expected is None:
        assert got is None
        return
    day, lo, hi = expected
    assert got == (at_paris(2026, 10, day, 0, 0) + lo * 3_600_000_000,
                   min(at_paris(2026, 10, day, 0, 0) + hi * 3_600_000_000, now))


@pytest.mark.parametrize(("us", "expected"), [
    (0, "1 min"), (-HOUR, "1 min"), (MINUTE // 2, "1 min"), (12 * MINUTE, "12 min"), (119 * MINUTE, "119 min"),
    (2 * HOUR, "2 h"), (3 * HOUR + 59 * MINUTE, "3 h"), (47 * HOUR, "47 h"), (2 * DAY, "2 jours"), (9 * DAY, "9 jours"),
])
def test_how_long_ago_is_said_in_few_words(us, expected):
    assert ago_words(us) == expected


NOW = at_paris(2026, 11, 15, 15, 0)  # le dimanche 15 novembre


@pytest.mark.parametrize(("then", "when", "since"), [
    (NOW - 4 * DAY, "il y a 4 jours", "4 jours"),
    (0, "il y a longtemps", "longtemps"),  # un instant inconnu
    (at_paris(2026, 11, 14, 3, 0), "dans la nuit d'hier", "la nuit d'hier"),
    (at_paris(2026, 11, 14, 21, 0), "hier soir", "hier soir"),
    (at_paris(2026, 11, 13, 10, 0), "avant-hier", "avant-hier"),
    (at_paris(2026, 11, 15, 9, 0), "ce matin", "ce matin"),
    (NOW - 20 * MINUTE, "tout à l'heure", "tout à l'heure"),
])
def test_since_is_said_after_depuis_without_cutting_a_phrase(then, when, since):
    """« depuis 4 jours », « depuis la nuit d'hier » : ce qui suit « depuis » a ses cas à lui, lus sur l'instant.
    Plus de « il y a » retiré du début d'une phrase de sa voix (« depuis dans la nuit d'hier » : audit du 2026-11-05,
    K7-11) ; ``when_fr`` dit toujours la même chose."""
    assert when_fr(then, NOW, PARIS) == when
    assert since_fr(then, NOW, PARIS) == since


def test_since_says_what_the_old_cut_said():
    """Oracle : l'ancienne découpe de la pensée de solitude (attention, ``_alone``), sur un instant par heure pendant
    dix jours, et l'instant inconnu. ``since_fr`` dit la même chose partout."""
    def cut(when: str) -> str:
        return when[len("il y a "):] if when.startswith("il y a ") else when.removeprefix("dans ")

    for then in [0, *(NOW - h * HOUR for h in range(10 * 24 + 1))]:
        assert since_fr(then, NOW, PARIS) == cut(when_fr(then, NOW, PARIS)), then


def test_how_long_ago_is_counted_in_one_place():
    """Une seule façon de compter : les seuils ne divergent plus d'un greffon à l'autre."""
    assert {u.where.split(":")[0] for u in uses() if u.key == "timespan.ago.minutes"} == {"vocab/days.py"}


@pytest.mark.parametrize(("hour", "key"), [
    (5, "morning"), (11, "morning"), (12, "noon"), (13, "noon"), (14, "afternoon"), (17, "afternoon"),
    (18, "evening"), (23, "evening"), (0, "night"), (4, "night"),
])
def test_the_part_of_day_is_its_key_in_her_voice(hour, key):
    """Le moment de la journée se lit directement dans ses deux façons de dire quand : plus de table qui le
    retraduise d'un mot français en clé (audit du 2026-11-05, K1-08)."""
    assert part_of_day(hour) == key
    for words_of in ("expression.when.today", "expression.when.yesterday", "identity.calendar.today",
                     "identity.calendar.yesterday"):
        assert key in family(words_of), words_of
