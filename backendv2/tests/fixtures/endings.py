"""Les fins d'une initiative qui n'a rien dit, et ce qu'elles valent comme essai (ADR 0044) : une table partagée
par les facultés qui comptent des tentatives (rappeler, raconter, demander un coup de main, annoncer un mail)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from mika.contracts import runtime as rt
from mika.kernel.clock import HOUR, US
from tests.fixtures.mika import at_paris

#: ((issue, murmure sans suite à cette adresse : None, depuis le départ, ou bien avant), essai ?, pourquoi)
ENDINGS = [
    (("superseded", None), False, "la personne a écrit pendant qu'elle composait : c'est la réponse qui parle"),
    (("preempted", None), False, "interrompue pour quelque chose de plus pressé"),
    (("interrupted", None), False, "un arrêt"),
    (("cancelled", None), False, "annulée"),
    (("abstained", "after"), False, "elle s'est ravisée (« pas maintenant ») : pas un renoncement"),
    (("abstained", None), True, "elle a choisi de se taire"),
    (("abstained", "before"), True, "un murmure sans suite d'avant ne dit rien de celle-ci"),
    (("failed", None), True, "une panne"),
    (("timeout", None), True, "un délai dépassé"),
]


def initiative_ends(reducers: tuple[Any, Any], state: Any, params: Any, reason: str, subject: str | None,
                    ending: tuple[str, str | None], *, times: int = 2,
                    start: int = at_paris(2026, 9, 28, 15, 0)) -> Any:
    """Une initiative vers ``user_1`` (raconter, rappeler…) part puis finit sans avoir rien dit, ``times`` fois de
    suite : la tranche après coup, par les vrais réducteurs de départ et de fin."""
    started, ended = reducers
    outcome, renounced = ending
    for i in range(times):
        at = start + i * HOUR
        mark = {None: 0, "after": at + 30 * US, "before": at - HOUR}[renounced]
        cx = SimpleNamespace(params=params, facts=SimpleNamespace(get=lambda key, mark=mark: mark))
        state = started(state, SimpleNamespace(correlation=f"c{i}", at=at, data=rt.EpisodeStarted(
            kind="INITIATIVE", target="user_1", reason=reason, subject=subject)), cx)
        state = ended(state, SimpleNamespace(correlation=f"c{i}", at=at + 40 * US, data=rt.EpisodeEnded(
            kind="INITIATIVE", outcome=outcome, target="user_1")), cx)
    return state
