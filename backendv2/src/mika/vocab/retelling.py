"""Raconter sans nommer (ADR 0091) — pur.

Ce qu'elle ne peut pas dire nommément devant quelqu'un, elle peut parfois le raconter sans dire de qui il s'agit,
comme une humaine (« une amie cherche du travail ») : à qui n'a **aucun lien connu** avec la personne, gradué par ce
qu'elle sait de qui l'écoute (``vocab.privacy.veiled`` : l'anodin à tous, le personnel à qui elle connaît, une
confidence à une amie ou une proche dont elle est sûre). N'étend que ce qui est fermé : ce qui peut se dire nommé se
dit nommé. Tout le reste ferme : un secret ou une discrétion demandée — même sans nom —, un mensonge, ce qui
n'appartient qu'à deux personnes, un texte dérivé, un avis ou une hypothèse (pas un simple fait), une mention qu'on
présume, ce qui concerne qui l'écoute (ou qu'il a dit, ou entendu), plusieurs personnes, sa propriétaire, un
événement marquant, ce qui dépasse le niveau de qui l'écoute, et un lien qu'on n'a pas prouvé absent.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

#: un événement marquant ne se raconte jamais sans nom : même anonyme, il se reconnaît
MARKING = 0.9
#: les mots qui tournent un récit sans nom (« quelqu'un que je connais vient de… »), repliés : ils ne disent rien de
#: ce qu'il raconte — sa réponse qui les reprend n'a pas pour autant raconté l'histoire (ADR 0092)
FRAMING = frozenset("""
quelqu un que je connais une personne connaissance proche amie ami entourage aime bien vient venir viens
""".split())


@dataclass(frozen=True, slots=True)
class Retelling:
    """Le verdict : ``ok``, ou pourquoi pas (un code, gardé dans la trace)."""

    ok: bool
    why: str = ""


def retellable(*, admitted: bool, veiled: str, persons: tuple[str, ...], sensitivity: int, level: int,
               listener: str | None, told_by: Collection[str] = (), heard_by: Collection[str] = (),
               secret: bool = False, lie: bool = False, between_us: bool = False, derived: bool = False,
               claim: bool = True, owners: Collection[str] = (), importance: float = 0.0,
               linked: bool | None = None) -> Retelling:
    """Peut-elle le raconter sans nommer personne à ``listener`` ? ``persons`` : qui c'est concerne (résolu) ;
    ``linked`` : un lien connu entre qui l'écoute et la personne — ``None`` (on n'a pas pu le savoir) ferme."""
    if admitted:
        return Retelling(False, "deja-dicible")  # ce qui se dit nommé se dit nommé
    if not veiled:
        return Retelling(False, "pas-de-version-sans-nom")
    if secret:
        return Retelling(False, "secret")
    if lie:
        return Retelling(False, "mensonge")
    if between_us:
        return Retelling(False, "entre-eux")
    if derived:
        return Retelling(False, "derive")
    if not claim:
        return Retelling(False, "pas-un-fait")
    if any(p.startswith("name:") for p in persons):
        return Retelling(False, "mention")
    if len(persons) != 1:
        return Retelling(False, "plusieurs-personnes" if persons else "personne")
    if not listener or listener in persons or listener in told_by or listener in heard_by:
        return Retelling(False, "concerne-qui-ecoute")
    if persons[0] in owners:
        return Retelling(False, "proprietaire")
    if importance >= MARKING:
        return Retelling(False, "marquant")
    if sensitivity > level:
        return Retelling(False, "trop-sensible")
    if linked is None or linked:
        return Retelling(False, "lien")
    return Retelling(True)
