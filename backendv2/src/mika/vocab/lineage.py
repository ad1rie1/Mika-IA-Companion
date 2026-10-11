"""La filiation d'un texte : de quoi il vient, et devant qui ses sources permettent de le redire.

Un texte écrit à partir de ce qu'elle sait — un rêve, une pensée, son journal, le portrait de quelqu'un — n'est pas
plus libre que ses sources : le secret que Bob lui a confié sur Sam ne devient pas dicible devant Sam parce qu'il a
traversé un rêve. Chaque source apporte une **exigence** (``Requirement``) : au moins une des façons dont elle l'a
appris (``any_of``, une restriction par témoignage) doit admettre l'audience ; **toutes** les exigences doivent tenir.
Un texte qu'elle ne garde que pour elle (``internal_only``) ne se dit à personne.

Une filiation **absente** (``None``, un texte d'avant qu'on ne la garde) n'est jamais une filiation vide : le lecteur
garde alors son ancienne règle. Une filiation vide (aucune source tirée de la mémoire) ne restreint rien.

Fonctions pures (le verdict lui-même : ``vocab.privacy.admissible``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from mika.kernel.events import Payload
from mika.kernel.frame import Audience
from mika.vocab.privacy import Sensitivity, Verdict, admissible


class Restriction(Payload):
    """Comment une chose lui a été dite : qui elle concerne, qui la lui a confiée, qui l'a entendue, ce qu'elle pèse,
    et si on lui a demandé de la garder pour soi. Le JSON est celui de l'ancien ``memory.Disclosure``."""

    about: tuple[str, ...] = ()
    told_by: tuple[str, ...] = ()
    heard_by: tuple[str, ...] = ()
    sensitivity: int = 2
    secret: bool = False


class Requirement(Payload):
    """Ce qu'exige une source : qu'au moins une de ses restrictions admette l'audience. Sans restriction, rien ne
    peut l'admettre (une source dont on ne sait rien ne se redit pas)."""

    item: int | None = None
    any_of: tuple[Restriction, ...] = ()


class Lineage(Payload):
    sources: tuple[int, ...] = ()
    requirements: tuple[Requirement, ...] = ()
    #: elle ne le garde que pour elle : rien ne l'admet
    internal_only: bool = False


def merged(*lineages: Lineage | None) -> Lineage:
    """La filiation d'un texte fait de plusieurs : toutes leurs exigences (une source en double ne compte qu'une
    fois)."""
    sources: list[int] = []
    reqs: list[Requirement] = []
    internal = False
    for lin in lineages:
        if lin is None:
            continue
        sources += [s for s in lin.sources if s not in sources]
        reqs += [r for r in lin.requirements if r not in reqs]
        internal = internal or lin.internal_only
    return Lineage(sources=tuple(sources), requirements=tuple(reqs), internal_only=internal)


def subjects(lineage: Lineage | None) -> tuple[str, ...]:
    """Qui le texte concerne par ses sources (les personnes concernées et celles qui les ont confiées) : l'oubli de
    l'une d'elles l'atteint."""
    if lineage is None:
        return ()
    return tuple(sorted({k for req in lineage.requirements for r in req.any_of for k in (*r.about, *r.told_by) if k}))


def _canon(keys: Sequence[str], resolve: Callable[[str], str] | None) -> tuple[str, ...]:
    if resolve is None:
        return tuple(sorted(set(keys)))
    return tuple(sorted({resolve(k) or k for k in keys}))


def verdict_of(r: Restriction, interlocutor: str | None, audience: Audience, *,
               resolve: Callable[[str], str] | None = None, presumed: Callable[[str], str] | None = None) -> Verdict:
    return admissible(_canon(r.about, resolve), int(r.sensitivity), interlocutor, audience,
                      told_by=_canon(r.told_by, resolve), heard_by=_canon(r.heard_by, resolve), secret=r.secret,
                      presumed=presumed)


def _best(verdicts: Iterable[Verdict]) -> Verdict | None:
    """Parmi les façons de l'avoir appris qui l'admettent, la plus ouverte (le niveau le plus bas)."""
    ok = [v for v in verdicts if v.ok]
    return min(ok, key=lambda v: (v.level, v.secret, len(v.tellers))) if ok else None


def admits(lineage: Lineage, interlocutor: str | None, audience: Audience, *,
           resolve: Callable[[str], str] | None = None, presumed: Callable[[str], str] | None = None) -> Verdict:
    """Le texte peut-il se dire devant cette audience ? Toutes ses sources doivent le permettre, chacune par au
    moins une façon dont elle l'a appris. ``resolve`` : la clé telle qu'elle vaut maintenant (une adresse reliée
    depuis à une personne) ; ``presumed`` : la personne qu'une mention désigne présumément (ADR 0075)."""
    if lineage.internal_only:
        return Verdict(False, secret=True)
    kept: list[Verdict] = []
    for req in lineage.requirements:
        verdicts = [verdict_of(r, interlocutor, audience, resolve=resolve, presumed=presumed) for r in req.any_of]
        best = _best(verdicts)
        if best is None:
            return verdicts[0] if verdicts else Verdict(False)
        kept.append(best)
    if not kept:
        return Verdict(True)
    return Verdict(True, others=tuple(sorted({p for v in kept for p in v.others})),
                   witness=all(v.witness for v in kept), level=max(v.level for v in kept),
                   tellers=tuple(sorted({p for v in kept for p in v.tellers})), secret=any(v.secret for v in kept),
                   tied=any(v.tied for v in kept))


def without_whom(lineage: Lineage, ceiling: int) -> bool:
    """Peut-il se dire sans dire de qui (« un concert de jazz », ADR 0087) ? Rien d'interne, et chaque source apprise
    au moins une fois hors secret, au plus à ``ceiling`` — qui l'a confié, qui l'a entendu n'y comptent pas, puisque
    personne n'est nommé. Une source sans façon connue ferme."""
    if lineage.internal_only:
        return False
    return all(any(not r.secret and r.sensitivity <= ceiling for r in req.any_of) for req in lineage.requirements)


def requirement(item: int | None, about: Sequence[str], sensitivity: int, *, told_by: Sequence[str] = (),
                heard_by: Sequence[str] = (), secret: bool = False) -> Requirement:
    """L'exigence d'une source qu'elle a apprise d'une seule façon."""
    return Requirement(item=item, any_of=(Restriction(about=tuple(about), told_by=tuple(told_by),
                                                      heard_by=tuple(heard_by), sensitivity=int(sensitivity),
                                                      secret=secret),))


def of_message(item: int | None, person: str, *, public: bool = False, secret: bool = False) -> Requirement:
    """Ce qu'exige un message qu'on lui a dit : ce que la personne lui a dit en privé est personnel et à elle (un
    salon l'a entendu : anodin, devant ceux qui y étaient)."""
    level = Sensitivity.ANODYNE if public and not secret else Sensitivity.PERSONAL
    return requirement(item, (person,), int(level), told_by=(person,), heard_by=(person,), secret=secret)
