"""Raconter sans nommer (ADR 0091) — pur.

Ce qu'elle ne peut pas dire nommément devant quelqu'un, elle peut parfois le raconter sans dire de qui il s'agit,
comme une humaine (« une amie cherche du travail ») : à qui n'a **aucun lien connu** avec la personne, gradué par ce
qu'elle sait de qui l'écoute (``vocab.privacy.veiled`` : l'anodin à tous, le personnel à qui elle connaît, une
confidence à une amie ou une proche dont elle est sûre). N'étend que ce qui est fermé : ce qui peut se dire nommé se
dit nommé. Tout le reste ferme : un secret ou une discrétion demandée — même sans nom —, un mensonge, ce qui
n'appartient qu'à deux personnes, un texte dérivé, un avis ou une hypothèse (pas un simple fait), une mention qu'on
présume, ce qui concerne qui l'écoute (ou qu'il a dit, ou entendu), plusieurs personnes, sa propriétaire, un
événement marquant, ce qui dépasse le niveau de qui l'écoute, et un lien qu'on n'a pas prouvé absent.

La version sans nom, la relecture l'écrit ; un filet la vérifie avant qu'elle soit gardée (``veiled_refusal``) :
un mois, un jour, un nom propre ou un nom de l'original écartent une version sans nom, comme une version trop courte
ou trop longue, ou un nom qu'elle connaît (ADR 0091 et 0092).
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mika.vocab.circadian import DAYS_FR, MONTHS_FR
from mika.vocab.words import OPENERS
from mika.vocab.words import fold as wfold

if TYPE_CHECKING:
    # le filet ne lit People qu'en annotation (``people.names_someone``) : à l'exécution, ce module ne dépend de rien
    # de la faculté
    from mika.faculties.memory.speakers import People

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


#: ce qu'elle sait de quelqu'un, raconté sans nom (ADR 0091) : au plus tant de caractères
VEILED_MAX = 240


#: un moment qui situerait le récit sans nom : une année, un mois (« le 10 octobre », « en janvier »), un jour de la
#: semaine — une durée (« six semaines »), non
_WHEN = re.compile(r"\b(?:19|20)\d{2}\b|\b(?:" + "|".join(wfold(m) for m in (*MONTHS_FR, *DAYS_FR)) + r")\b")
#: un mot (lettres, apostrophes et traits d'union compris : « l'Italie », « Saint-Malo »)
_TOKEN = re.compile(r"[^\W\d_][\w'’-]*")
#: ce qui précède un début de phrase : la majuscule y est la règle, pas un nom
_OPENS = re.compile(r"(?:^|[.!?…:;«\"“(]\s*)$")


def capitalized(text: str) -> tuple[set[str], set[str]]:
    """Les mots à majuscule d'un texte (repliés) : ceux qui ne sont pas en tête de phrase (un prénom, un lieu, une
    marque, un sigle), et ceux qui le sont."""
    inside: set[str] = set()
    opening: set[str] = set()
    for m in _TOKEN.finditer(text or ""):
        word = m.group(0)
        if any(ch.isupper() for ch in word):
            (opening if _OPENS.search(text[:m.start()]) else inside).add(wfold(word))
    return inside, opening


def veiled_refusal(text: str | None, people: People, original: str = "") -> str:
    """Pourquoi le filet écarte cette version sans nom (un code, pour le journal technique) — vide : il la garde.
    Le filet : trop courte ou trop longue, une date (un mois, un jour), un nom qu'elle connaît, un nom propre ou un
    de ceux de l'original.
    ``original`` : ce qu'elle raconte, nommé — ce qui y porte une majuscule (un nom, un employeur, une ville) ne
    revient pas dans la version sans nom, même en minuscules (ADR 0092)."""
    said = " ".join((text or "").split()).strip()
    if len(said) < 8:
        return "vide"
    if len(said) > VEILED_MAX:
        return "trop-longue"
    if _WHEN.search(wfold(said)):
        return "datee"
    if people.names_someone(said):
        return "nomme-quelqu-un"
    inside, opening = capitalized(said)
    if inside:
        return "nom-propre"
    named, starts = capitalized(original)
    found = {wfold(w) for w in _TOKEN.findall(said)}
    if found & named or (opening & starts) - OPENERS:
        return "reprend-un-nom"
    return ""
