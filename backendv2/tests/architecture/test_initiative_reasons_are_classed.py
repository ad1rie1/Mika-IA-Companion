"""Une politique : chaque raison d'initiative est classée, une fois, dans ``contracts/agency.py``.

Les retenues d'``agency`` (le plafond du jour, la période réfractaire, ne pas harceler, la rancune, l'heure où la
personne répond) lisent la sorte d'une raison dans une seule déclaration : ce qui est dû (``OWED``), ce qui prévient
(``INFORMS``, et ``WAITS_FOR_AN_ANSWER`` parmi elles), ce qui salue (``GREETS``), ce qui ne regarde que la personne
(``FOR_THEM``), une seule fois longtemps après (``ONCE_MORE``). Une raison qu'aucun ne nomme est une initiative
ordinaire, sans erreur : un rappel dû qu'on oublierait d'y ranger partirait trop tard, ou pas du tout devant une
rancune. Cette garde lit les raisons que déclarent les proposants d'initiative du registre composé
(``@f.propose(kinds=[Kind.INITIATIVE], reasons=…)``, rangés dans ``Registry.proposers``), jamais le texte du code :

- chacune est dans un de ces ensembles, ou dans ``ORDINARY``, qui nomme les raisons ordinaires **exprès** ;
- ``ORDINARY`` ne nomme rien que personne ne déclare, ni rien qu'un autre ensemble classe déjà.

Les raisons des autres sortes d'épisode (un travail, une tâche, un réveil) ne passent pas par ces retenues : elles ne
sont pas regardées. Le contrôle est une fonction des proposants (``unclassed``) : le dernier test l'essaie sur une
composition jouet, pour qu'il échoue vraiment quand une raison n'est rangée nulle part.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from mika.app.composition import arbitration, faculties
from mika.contracts import agency
from mika.kernel.faculty import Faculty, ProposerSpec
from mika.kernel.registry import Registry
from mika.runtime.state import RUNTIME
from mika.vocab.episodes import Kind

#: les ensembles d'``agency`` qui classent une raison d'initiative (``NOT_SPEAKING_UP`` n'est que leur union)
CLASSES: dict[str, frozenset[str]] = {
    "OWED": agency.OWED, "INFORMS": agency.INFORMS, "WAITS_FOR_AN_ANSWER": agency.WAITS_FOR_AN_ANSWER,
    "GREETS": agency.GREETS, "FOR_THEM": agency.FOR_THEM, "ONCE_MORE": agency.ONCE_MORE,
}


def declared(proposers: Iterable[ProposerSpec]) -> dict[str, set[str]]:
    """Chaque raison que déclare un proposant d'initiative, et qui la déclare."""
    out: dict[str, set[str]] = {}
    for p in proposers:
        if Kind.INITIATIVE in p.kinds:
            for reason in p.reasons:
                out.setdefault(reason, set()).add(p.owner)
    return out


def unclassed(proposers: Iterable[ProposerSpec], classes: Mapping[str, frozenset[str]],
              ordinary: frozenset[str]) -> list[str]:
    """Ce que le classement des raisons d'initiative ne dit pas, en phrases : une raison déclarée rangée nulle part,
    une raison d'``ORDINARY`` que personne ne déclare, ou qu'un autre ensemble classe déjà."""
    found = declared(proposers)
    classed = frozenset().union(*classes.values())
    out = [f"la raison d'initiative « {reason} » ({', '.join(sorted(owners))}) n'est classée nulle part : la ranger "
           f"dans son ensemble de contracts/agency.py ({', '.join(classes)}), ou dans ORDINARY si elle est ordinaire "
           "exprès (ARCHITECTURE.md, « Écrire une faculté », « Ce qu'elle range ailleurs que chez elle »)"
           for reason, owners in sorted(found.items()) if reason not in classed | ordinary]
    out += [f"ORDINARY nomme « {reason} », qu'aucun proposant d'initiative ne déclare : l'en retirer"
            for reason in sorted(ordinary - set(found))]
    out += [f"ORDINARY nomme « {reason} », que {name} classe déjà : elle est ordinaire ou elle ne l'est pas"
            for reason in sorted(ordinary) for name, members in classes.items() if reason in members]
    return out


def test_every_initiative_reason_is_classed():
    proposers = Registry([RUNTIME, *faculties()], arbitration=arbitration()).proposers
    found = declared(proposers)
    assert len(found) >= 20 and agency.OWED <= set(found)  # la lecture trouve bien les raisons, les dues comprises
    faults = unclassed(proposers, CLASSES, agency.ORDINARY)
    assert not faults, "\n".join(faults)


@dataclass(frozen=True, slots=True)
class _S:
    n: int = 0


def test_the_check_sees_a_reason_classed_nowhere_and_an_ordinary_one_that_no_longer_serves():
    toy = Faculty("jouet", state=_S, init=lambda p: _S())
    toy.propose(kinds=[Kind.INITIATIVE], reasons={"due": (0.0, 1.0), "envie": (0.0, 1.0), "neuve": (0.0, 1.0)})(
        lambda s, f: [])
    toy.propose(kinds=[Kind.TASK], reasons={"tache": (0.0, 1.0)})(lambda s, f: [])  # pas une initiative
    proposers = Registry([toy]).proposers
    classes = {"OWED": frozenset({"due"})}
    assert declared(proposers) == {"due": {"jouet"}, "envie": {"jouet"}, "neuve": {"jouet"}}
    assert unclassed(proposers, classes, frozenset({"envie", "neuve"})) == []
    assert unclassed(proposers, classes, frozenset({"envie"})) == [
        "la raison d'initiative « neuve » (jouet) n'est classée nulle part : la ranger dans son ensemble de "
        "contracts/agency.py (OWED), ou dans ORDINARY si elle est ordinaire exprès (ARCHITECTURE.md, « Écrire une "
        "faculté », « Ce qu'elle range ailleurs que chez elle »)"]
    assert unclassed(proposers, classes, frozenset({"envie", "neuve", "partie", "due"})) == [
        "ORDINARY nomme « partie », qu'aucun proposant d'initiative ne déclare : l'en retirer",
        "ORDINARY nomme « due », que OWED classe déjà : elle est ordinaire ou elle ne l'est pas"]
