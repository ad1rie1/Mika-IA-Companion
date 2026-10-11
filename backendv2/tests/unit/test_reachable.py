"""Joignable maintenant (lot C du chantier « émotions, conscience, mémoire ») : on n'écrit pas à quelqu'un qui dort.

Avant, seul le flux RSS regardait les heures où une personne écrit : une inquiétude, le manque, une pensée qui
insiste ou un moment à encourager pouvaient partir à trois heures du matin, et l'application de son téléphone la
réveillait. Une règle dans ``agency`` pour toutes les initiatives : quelqu'un d'absent, pendant sa nuit, attend. Sa
nuit est supposée tant qu'on ne sait rien ; ses heures apprises l'ouvrent (une noctambule) mais ne ferment jamais la
journée (une amie qui écrit vers 23 h reste joignable l'après-midi). Ce qui est dû ou prévient passe outre ; quelqu'un
de présent est joignable.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

from mika.contracts import agency as agency_c
from mika.contracts import attention as attention_c
from mika.contracts import email as email_c
from mika.contracts import goals as goals_c
from mika.contracts import others as others_c
from mika.contracts import social as social_c
from mika.faculties.agency import _reachable
from mika.faculties.others.faculty import OthersParams, hours_reading
from mika.kernel.arbitration import Anyone, RowView

PARIS = ZoneInfo("Europe/Paris")
#: ses heures : de 9 h à 22 h
DAYTIME = others_c.HoursReading(days=10, active=tuple(9 <= h <= 22 for h in range(24)), learned=True, usual=19)


def frame(hour: int, *, present: tuple[str, ...] = (), hours: others_c.HoursReading = DAYTIME):
    facts = {"presence.present": present, "identity.person": "alice", "others.hours": hours}
    return NS(get=lambda key: facts[key.name], local=lambda t=None: datetime(2026, 10, 12, hour, 5, tzinfo=PARIS))


def row(reason: str, target: str = "ext_1") -> RowView:
    return RowView("INITIATIVE", target, 10.0, (reason,))


def test_she_does_not_write_to_someone_asleep():
    for reason in (others_c.CHECK_IN, social_c.RECONTACT, attention_c.THOUGHT, others_c.CHEER, others_c.CELEBRATE):
        assert _reachable(None, frame(3), row(reason)).veto == agency_c.NOT_REACHABLE, reason
        assert _reachable(None, frame(10), row(reason)).veto is None, reason  # le matin venu, oui


def test_someone_present_is_reachable_whatever_the_hour():
    assert _reachable(None, frame(3, present=("ext_1",)), row(others_c.CHECK_IN)).veto is None


def test_what_is_owed_or_warns_goes_through():
    assert _reachable(None, frame(3), row(goals_c.REMIND)).veto is None  # le rappel qu'on lui a demandé
    assert _reachable(None, frame(3), row(email_c.MENTION)).veto is None  # prévenir
    assert _reachable(None, frame(3), row(attention_c.THOUGHT, target=Anyone.ANY)).veto is None  # personne en vue


def test_her_hours_open_her_night_but_never_close_her_day():
    """Une amie qui écrit chaque soir vers 23 h reste joignable l'après-midi (le test d'avant : elle ne lui écrivait
    plus jamais) ; une noctambule qui écrit vers 1 h est joignable à 1 h ; personne à 4 h."""
    evening = hours_reading(tuple((d, 23) for d in range(6)), OthersParams())
    night_owl = hours_reading(tuple((d, 1) for d in range(6)), OthersParams())
    assert evening.learned and night_owl.learned
    assert _reachable(None, frame(15, hours=evening), row(social_c.RECONTACT)).veto is None
    assert _reachable(None, frame(23, hours=evening), row(social_c.RECONTACT)).veto is None
    assert _reachable(None, frame(1, hours=night_owl), row(social_c.RECONTACT)).veto is None
    assert _reachable(None, frame(4, hours=evening), row(social_c.RECONTACT)).veto == agency_c.NOT_REACHABLE
