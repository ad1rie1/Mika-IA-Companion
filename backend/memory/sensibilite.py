"""La sensibilité d'une ligne de mémoire, et ce qu'elle devient au rappel.

Trois niveaux, notés par l'extracteur au même titre que l'importance
(``anodin`` / ``personnel`` / ``confidence``) et stockés sur
``Souvenir.sensibilite`` / ``Connaissance.sensibilite``. Ce module est la
partie **pure** de la frontière intime côté mémoire :

* ``sensibilite_extraite`` — lire et borner ce que l'extraction a rendu ;
* ``qualifier`` — pour une ligne chargée avec ses entités, dire si elle
  concerne un tiers, lequel, à quelle sensibilité *effective* (la fiche de
  la personne peut la **remonter** via ``sensitive_topics``, jamais la
  descendre) et si l'interlocuteur était témoin ;
* ``tag`` — la parenthèse ajoutée en fin de ligne dans le prompt pour que
  Mika arbitre ce qui est sous le niveau mais pas anodin.

Aucune lecture ORM ni de registre ici : les entités arrivent en tuples
``(pk, nom, type, sujets_sensibles)`` construits dans le thread ORM.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from identity.divulgation import RANG, SENSIBILITES, Divulgation, Niveau, niveau_de

#: Ce que vaut une ligne dont l'extraction n'a rien dit et qui concerne une
#: personne : jamais anodin — on ne sait pas.
DEFAUT_AVEC_PERSONNE = Niveau.PERSONNEL.value
#: Une ligne qui ne concerne personne (vécue seule, une nouvelle RSS) n'a
#: rien à protéger.
DEFAUT_SANS_PERSONNE = Niveau.ANODIN.value


def sensibilite_extraite(extraction: dict, *, a_une_personne: bool) -> str:
    """La sensibilité jugée par l'extraction, ramenée aux trois valeurs.

    Même contrat que ``_extracted_importance`` : absente, illisible ou hors
    échelle → le défaut, qui dépend de la présence d'une personne.
    """
    brut = extraction.get("sensibilite")
    if isinstance(brut, str) and brut.strip().lower() in SENSIBILITES:
        return brut.strip().lower()
    return DEFAUT_AVEC_PERSONNE if a_une_personne else DEFAUT_SANS_PERSONNE


def plus_sensible(a: str | None, b: str | None) -> str:
    """La plus haute des deux — une sensibilité ne descend jamais."""
    na, nb = niveau_de(a), niveau_de(b)
    return (na if RANG[na] >= RANG[nb] else nb).value


# ── Surcharge par les sujets sensibles de la fiche ───────────────────────

_MOT = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]{4,}")
#: Longueur du radical comparé. Volontairement fruste, comme
#: ``corroboration_score`` : « rechute » doit toucher « rechuté », « santé »
#: « santé mentale ».
_RADICAL = 5


def _plier(mot: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", mot.lower())
        if not unicodedata.combining(c)
    )


def _radicaux(texte: str) -> set[str]:
    return {_plier(m)[:_RADICAL] for m in _MOT.findall(texte or "")}


def sujet_sensible_touche(contenu: str, sujets: Iterable[str]) -> bool:
    """Le contenu parle-t-il d'un des sujets sensibles de la fiche ?

    Recoupement lexical par radical, plié (accents, casse). Un sujet vide ou
    sans mot de quatre lettres ne touche rien.
    """
    radicaux = _radicaux(contenu)
    if not radicaux:
        return False
    for sujet in sujets or ():
        if not isinstance(sujet, str):
            continue
        if _radicaux(sujet) & radicaux:
            return True
    return False


# ── Qualification d'une ligne chargée ────────────────────────────────────

@dataclass(frozen=True)
class Qualification:
    """Ce qu'une ligne vaut face à l'interlocuteur du tour."""

    #: Les autres personnes concernées (noms), dans l'ordre des entités.
    autres: tuple[str, ...]
    #: Sensibilité effective — stockée, remontée par les sujets sensibles.
    sensibilite: str
    #: L'interlocuteur figure aussi parmi les personnes de la ligne.
    temoin: bool


def qualifier(
    contenu: str,
    sensibilite: str | None,
    entites: Iterable[tuple],
    *,
    soi_nom: str = "",
    soi_pk: int | None = None,
) -> Qualification | None:
    """``None`` quand la ligne ne concerne aucun tiers — rien à filtrer ni à
    taguer. Sinon les autres, la sensibilité effective et le témoignage.

    ``entites`` : ``(pk, nom, type, sujets_sensibles)`` ; l'interlocuteur est
    reconnu par son pk (outils) ou par son nom sans la casse (rappel), les
    deux formes que la couche identité rend selon le chemin.
    """
    soi = _plier(soi_nom.strip()) if soi_nom else ""
    autres: list[str] = []
    temoin = False
    effective = niveau_de(sensibilite)
    for pk, nom, genre, sujets in entites:
        if genre != "person":
            continue
        est_soi = (soi_pk is not None and pk == soi_pk) or (
            bool(soi) and _plier(str(nom or "").strip()) == soi
        )
        if est_soi:
            temoin = True
            continue
        autres.append(str(nom or ""))
        if sujets and sujet_sensible_touche(contenu, sujets):
            effective = Niveau.CONFIDENCE
    if not autres:
        return None
    return Qualification(tuple(autres), effective.value, temoin)


def admissible(q: Qualification | None, divulgation: Divulgation) -> bool:
    """La ligne peut-elle entrer dans ce tour ?"""
    if q is None:
        return True
    return divulgation.admet(q.sensibilite, temoin=q.temoin)


def tag(q: Qualification | None) -> str:
    """La parenthèse d'arbitrage, ou ``""`` pour l'anodin et pour ce qui ne
    concerne aucun tiers."""
    if q is None:
        return ""
    qui = _nommer(q.autres)
    niveau = niveau_de(q.sensibilite)
    if niveau is Niveau.CONFIDENCE:
        return f" (une confidence de {qui} — seulement parce que tu es en confiance)"
    if niveau is Niveau.PERSONNEL:
        return f" (confié en privé par {qui} — pas à répéter à n'importe qui)"
    return ""


def _nommer(noms: tuple[str, ...]) -> str:
    noms = tuple(n for n in noms if n) or ("quelqu'un",)
    if len(noms) == 1:
        return noms[0]
    return ", ".join(noms[:-1]) + " et " + noms[-1]
