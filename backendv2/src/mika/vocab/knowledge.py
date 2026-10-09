"""Une ligne de ce qu'elle sait, telle que les autres facultés la lisent (les vues de ``contracts.memory`` :
``KNOWLEDGE_VIEW``, ``FORMER_VIEW``), et ce qu'elle exige pour se redire (sa filiation).

Lire ce qu'elle sait ne donne pas le droit de le redire : chaque ligne porte sa ``lineage``, et le texte qu'on en
tire (un portrait, un rêve, une pensée) la garde ou la vérifie avec ``vocab.lineage.admits`` — jamais avec un filtre
refait à la main sur ``secret`` ou ``told_by``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mika.vocab.lineage import Lineage, Requirement, Restriction


def keys(raw: Any) -> tuple[str, ...]:
    """Une colonne JSON de clés (« [] » si vide ou illisible)."""
    try:
        got = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return ()
    return tuple(str(x) for x in got) if isinstance(got, list) else ()


def _ints(raw: Any) -> tuple[int, ...]:
    try:
        got = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return ()
    return tuple(int(x) for x in got if isinstance(x, int | str) and str(x).lstrip("-").isdigit()) \
        if isinstance(got, list) else ()


@dataclass(frozen=True, slots=True)
class Known:
    id: int
    kind: str
    text: str
    about: tuple[str, ...]
    sensitivity: int
    importance: float
    confidence: float | None
    origin: str | None
    source: str | None
    emotion: str | None
    born_at: int
    touched_at: int
    status: str
    recipient: str | None
    due: int | None
    sources: tuple[int, ...]
    told_by: tuple[str, ...]
    heard_by: tuple[str, ...]
    secret: bool
    #: 1 : une note sur elle ; 2 : ce qui la définit (un goût, un avis)
    about_self: int
    between_us: bool
    knowledge_kind: str
    holder: str | None
    lineage: Lineage


def lineage_of(item: int, about: tuple[str, ...], sensitivity: int, *, told_by: tuple[str, ...] = (),
               heard_by: tuple[str, ...] = (), secret: bool = False, holder: str | None = None,
               constraints: tuple[Restriction, ...] = (), internal_only: bool = False) -> Lineage:
    """Ce qu'exige un élément pour se redire — la règle du rappel (``memory.recall.verdict_of``) : ce qu'elle ne
    garde que pour elle, jamais ; ce qu'elle a repensé, ce que permettait chacune de ses sources ; le reste, ses
    personnes (le porteur d'un avis compris), qui le lui a confié et qui l'a entendu."""
    if internal_only:
        return Lineage(sources=(item,), internal_only=True)
    if constraints:
        reqs = tuple(Requirement(item=item, any_of=(Restriction(
            about=r.about, told_by=r.told_by, heard_by=r.heard_by, sensitivity=max(int(r.sensitivity), sensitivity),
            secret=r.secret),)) for r in constraints)
        return Lineage(sources=(item,), requirements=reqs)
    subjects = tuple(sorted({*about, *([holder] if holder else [])}))
    return Lineage(sources=(item,), requirements=(Requirement(item=item, any_of=(Restriction(
        about=subjects, told_by=told_by, heard_by=heard_by, sensitivity=sensitivity, secret=secret),)),))


def known_of(row: Mapping[str, Any]) -> Known:
    """Une ligne d'une vue de ce qu'elle sait (``KNOWN_COLUMNS``, en dictionnaire)."""
    item = int(row["id"])
    about, told_by, heard_by = keys(row.get("about")), keys(row.get("told_by")), keys(row.get("heard_by"))
    sensitivity, secret, holder = int(row.get("sensitivity") or 0), bool(row.get("secret")), row.get("holder")
    try:
        constraints = tuple(Restriction.model_validate(v) for v in json.loads(row.get("constraints") or "[]"))
    except ValueError:
        constraints = (Restriction(sensitivity=3, secret=True),)  # illisible : rien ne s'ouvre
    return Known(
        id=item, kind=str(row["kind"]), text=str(row.get("text") or ""), about=about, sensitivity=sensitivity,
        importance=float(row.get("importance") or 0.0),
        confidence=None if row.get("confidence") is None else float(row["confidence"]), origin=row.get("origin"),
        source=row.get("source"), emotion=row.get("emotion"), born_at=int(row.get("born_at") or 0),
        touched_at=int(row.get("touched_at") or 0), status=str(row.get("status") or ""),
        recipient=row.get("recipient"), due=None if row.get("due") is None else int(row["due"]),
        sources=_ints(row.get("sources")), told_by=told_by, heard_by=heard_by, secret=secret,
        about_self=int(row.get("about_self") or 0), between_us=bool(row.get("between_us")),
        knowledge_kind=str(row.get("knowledge_kind") or "claim"), holder=holder,
        lineage=lineage_of(item, about, sensitivity, told_by=told_by, heard_by=heard_by, secret=secret, holder=holder,
                           constraints=constraints, internal_only=bool(row.get("internal_only"))))


def knowns(rows: Iterable[Sequence[Any]], columns: Sequence[str]) -> list[Known]:
    """Les lignes d'une requête sur une vue de ce qu'elle sait (``SELECT_KNOWN``), dans l'ordre."""
    return [known_of(dict(zip(columns, r, strict=True))) for r in rows]
