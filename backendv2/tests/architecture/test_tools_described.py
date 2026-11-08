"""Chaque outil dit à quoi il sert et à qui il est offert (ADR 0064) : « Ses outils » le lit dans le registre.

Un lot sans phrase se lirait dans son catalogue comme une liste de noms ; une condition d'offre (``when=``) sans
docstring se lirait sur sa fiche « sa condition n'est pas remplie », sans dire laquelle.

Chaque outil du code dit aussi ce qu'il fait **à la personne** qui lit ses droits (``label``, ADR 0208) : sa
description est une consigne écrite pour le modèle, où « tu » la désigne, elle ; lue dans Outils sous « Ce que Mika
peut faire pour toi », « Promettre un rappel à la personne à qui tu parles » se lisait comme une chose à faire soi-même
(audit du 2026-11-05, F4-01)."""

from __future__ import annotations

import inspect
import re

from mika.app.composition import arbitration, faculties
from mika.kernel.registry import Registry
from mika.runtime.state import RUNTIME

#: une ligne de la matrice d'Outils : au-delà, le client coupait une description
LABEL_MAX = 56
#: « tu », c'est elle dans une description : un libellé n'a pas de sujet (« Te promettre un rappel »)
YOU = re.compile(r"\btu\b", re.IGNORECASE)
#: un nom d'outil ou d'argument (``report_step``, ``needs_you``) : la personne ne le lit pas
CODE = re.compile(r"\w+_\w+|[`{}\[\]<>]")
#: son nom vient de sa persona (ADR 0070), jamais d'un texte
HER_NAME = re.compile(r"\bMika\b")


def _registry() -> Registry:
    return Registry([RUNTIME, *faculties()], arbitration=arbitration())


def test_every_bundle_of_the_code_says_what_it_allows():
    registry = _registry()
    missing = sorted({s.bundle for s in registry.tools.values() if not registry.bundles.get(s.bundle, "").strip()})
    assert missing == [], f"lots sans description : {missing}"


def test_every_offer_condition_says_itself():
    registry = _registry()
    silent = sorted(s.name for s in registry.tools.values() for gate in (s.when, s.fits)
                    if gate is not None and not (inspect.getdoc(gate) or "").strip())
    assert silent == [], f"conditions d'offre sans docstring : {silent}"


def test_every_tool_says_what_it_does():
    registry = _registry()
    assert sorted(s.name for s in registry.tools.values() if len(s.description.strip()) < 8) == []


def test_every_tool_of_the_code_tells_the_person_what_it_does():
    """Un libellé déclaré avec l'outil (``@f.tool(..., label=phrase(...))``), écrit dans ``persona/voix.yaml`` à côté
    de sa description. Seuls les outils venus d'ailleurs (un service, une app) n'en ont pas : ce registre n'a que ceux
    du code."""
    registry = _registry()
    assert sorted(s.name for s in registry.tools.values() if not s.label.strip()) == []


def test_a_label_speaks_to_the_person_in_a_few_words():
    """Quelques mots à l'infinitif, adressés à qui lit (« Te promettre un rappel », « Chercher dans sa mémoire ») :
    ni « tu » (elle, dans une description), ni nom d'outil, ni son nom, ni la description recopiée."""
    registry = _registry()
    wrong: dict[str, str] = {}
    for s in registry.tools.values():
        label = s.label
        if not label.strip():
            continue  # le test d'avant le dit
        if len(label) > LABEL_MAX:
            wrong[s.name] = f"{len(label)} caractères (au plus {LABEL_MAX})"
        elif label != label.strip() or "\n" in label or label.endswith((".", ":", ";", ",")):
            wrong[s.name] = "une ligne, sans ponctuation finale"
        elif not label[0].isupper():
            wrong[s.name] = "une majuscule en tête"
        elif YOU.search(label):
            wrong[s.name] = "« tu » : c'est elle, dans une consigne au modèle"
        elif CODE.search(label):
            wrong[s.name] = "un nom du code"
        elif HER_NAME.search(label):
            wrong[s.name] = "son nom vient de sa persona"
        elif " ".join(label.split()) == " ".join(s.description.split()):
            wrong[s.name] = "la description recopiée"
    assert wrong == {}, wrong


def test_a_label_is_not_shared():
    """Deux outils d'une même famille, deux libellés : la personne les distingue sur la même page."""
    registry = _registry()
    seen: dict[tuple[str, str], str] = {}
    twins = []
    for s in sorted(registry.tools.values(), key=lambda t: t.name):
        key = (s.bundle, s.label)
        if s.label and key in seen:
            twins.append((seen[key], s.name))
        seen.setdefault(key, s.name)
    assert twins == []
