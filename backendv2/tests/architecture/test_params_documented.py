"""Une politique : chaque paramètre interne d'une faculté se lit et se règle
dans la console.

La console dessine les paramètres depuis leur modèle (``kernel/forms.py``) :
sans ``Knob``, un champ s'affiche sous son nom Python humanisé, sans un mot
de ce qu'il pilote, et un nombre sans bornes y est en lecture seule. Chaque
champ dit donc ce qu'il fait (un libellé, une aide), chaque nombre est borné,
son défaut tient dans ses bornes — et, quand la faculté dérive ses paramètres
du tempérament, tout curseur poussé à un bout donne encore des valeurs que la
console accepterait d'écrire.

Toutes les facultés de la composition y passent d'elles-mêmes.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import BaseModel

from mika.app.composition import faculties
from mika.kernel import forms
from mika.kernel.builtin import KERNEL
from mika.vocab.temperament import Temperament

Derive = Callable[[Temperament], BaseModel]

#: (propriétaire, modèle de paramètres, dérivation depuis le tempérament — ou ``None``) : toute la
#: composition, et le noyau ; une faculté ajoutée y entre d'elle-même
MODELS: list[tuple[str, type[BaseModel], Derive | None]] = [
    (f.name, f.params, f.derive) for f in [KERNEL, *faculties()] if f.params is not None]

#: Les nombres laissés sans bornes (lecture seule dans la console) : « propriétaire.chemin » → pourquoi.
#: Cette liste ne peut que rétrécir.
UNBOUNDED: dict[str, str] = {}

NUMERIC = frozenset({"int", "float", "slider", "duration"})
#: les curseurs du tempérament (l'humeur de fond est un choix, pas un curseur)
SLIDERS = tuple(name for name, info in Temperament.model_fields.items() if info.annotation is float)
IDS = [owner for owner, _, _ in MODELS]


def _fields(model: type[BaseModel]) -> list[forms.FormField]:
    return [f for f in forms.describe(model) if f.kind != "group"]


def _name(path: str) -> str:
    return path.rsplit(".", 1)[-1]


@pytest.mark.parametrize(("owner", "model", "derive"), MODELS, ids=IDS)
def test_every_parameter_says_what_it_does(owner: str, model: type[BaseModel], derive: Derive | None) -> None:
    unnamed = [f.path for f in _fields(model) if f.label == forms._humanize(_name(f.path))]
    silent = [f.path for f in _fields(model) if not f.help.replace(forms.UNBOUNDED_NOTE, "").strip()]
    assert unnamed == [], f"{owner} : sans libellé (nom Python affiché tel quel) : {unnamed}"
    assert silent == [], f"{owner} : sans aide : {silent}"


@pytest.mark.parametrize(("owner", "model", "derive"), MODELS, ids=IDS)
def test_every_number_is_bounded_around_its_default(owner: str, model: type[BaseModel],
                                                     derive: Derive | None) -> None:
    unbounded, outside = [], []
    for f in _fields(model):
        if f.kind not in NUMERIC:
            continue
        if f.lo is None or f.hi is None:
            if f"{owner}.{f.path}" not in UNBOUNDED:
                unbounded.append(f.path)
            continue
        if not f.lo <= f.default <= f.hi:
            outside.append(f"{f.path} = {f.default} hors de [{f.lo} ; {f.hi}]")
    assert unbounded == [], f"{owner} : nombres sans bornes (lecture seule dans la console) : {unbounded}"
    assert outside == [], f"{owner} : défaut hors de ses bornes : {outside}"


def test_the_unbounded_allowlist_only_names_unbounded_numbers() -> None:
    """Un champ borné depuis (ou disparu) sort de la liste : elle ne fait que rétrécir."""
    unbounded = {f"{owner}.{f.path}" for owner, model, _ in MODELS for f in _fields(model)
                 if f.kind in NUMERIC and (f.lo is None or f.hi is None)}
    stale = sorted(set(UNBOUNDED) - unbounded)
    assert stale == [], f"à retirer de UNBOUNDED : {stale}"


DERIVED = [(owner, model, derive) for owner, model, derive in MODELS if derive is not None]


@pytest.mark.parametrize(("owner", "model", "derive"), DERIVED, ids=[d[0] for d in DERIVED])
def test_every_temperament_extreme_derives_writable_values(owner: str, model: type[BaseModel],
                                                           derive: Derive) -> None:
    """Chaque curseur à 0 puis à 1 (les autres au milieu) : la console accepterait
    d'écrire ce que le tempérament produit."""
    fields = _fields(model)
    problems = {}
    for slider in SLIDERS:
        for end in (0.0, 1.0):
            errors = forms.within(fields, forms.flatten(derive(Temperament(**{slider: end}))))
            if errors:
                problems[f"{slider}={end:g}"] = errors
    assert problems == {}, f"{owner} : le tempérament sort des bornes : {problems}"
