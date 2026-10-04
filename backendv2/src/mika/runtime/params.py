"""Les paramètres des facultés, et d'où vient chacun.

Quatre étages, du plus faible au plus fort :

1. **défaut** — la valeur déclarée par le modèle de paramètres ;
2. **tempérament** — ce que ``derive`` en fait (le caractère) ;
3. **réglage** — ce que l'exploitation fournit comme une donnée (le fuseau
   de sa persona, les boîtes où elle prépare des réponses) : jamais une surcharge,
   donc jamais effacé par une reconfiguration ;
4. **surcharge** — le bloc « avancé » de la console, par chemin pointé.

Le plan est pur : il ne journalise rien. ``configure`` (la composition) le
journalise ; la console le lit pour montrer la provenance et l'influence de
chaque curseur, et le recalcule avant d'enregistrer une surcharge (une valeur
refusée ne s'enregistre jamais). Les bornes de la console (``Knob``) ne
s'appliquent qu'à l'écriture : un plan rejoué relit les surcharges passées
telles quelles.

Rien ici ne nomme une faculté.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from mika.kernel import forms
from mika.kernel.registry import drop_retired
from mika.vocab.temperament import Temperament

if TYPE_CHECKING:
    from mika.kernel.faculty import Faculty
    from mika.runtime.bootstrap import Kernel

log = logging.getLogger("mika.params")

DEFAULT, TEMPERAMENT, SETTING, OVERRIDE = "défaut", "tempérament", "réglage", "surcharge"
SOURCES = (DEFAULT, TEMPERAMENT, SETTING, OVERRIDE)

#: les curseurs du tempérament (l'humeur de fond est un choix, pas un curseur)
SLIDERS: tuple[str, ...] = tuple(name for name, info in Temperament.model_fields.items()
                                 if info.annotation is float)

Layer = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Planned:
    """Les paramètres d'une faculté tels qu'ils seraient journalisés."""

    owner: str
    model: type[BaseModel]
    value: BaseModel
    #: sans les surcharges (la valeur « naturelle » : tempérament et réglages)
    natural: BaseModel
    #: chemin → provenance (``SOURCES``)
    sources: Mapping[str, str]
    #: les surcharges refusées, par chemin (ignorées)
    refused: Mapping[str, str] = field(default_factory=dict)


def _default(fac: Faculty[Any, Any], temperament: Temperament) -> BaseModel:
    assert fac.params is not None
    try:
        return fac.params()
    except (TypeError, ValueError):
        # des paramètres sans valeur par défaut : le tempérament neutre en tient lieu
        assert fac.derive is not None
        return fac.derive(Temperament(), None)


def _related(a: str, b: str) -> bool:
    return not b or a == b or a.startswith(b + ".") or b.startswith(a + ".")


def _apply(model: type[BaseModel], base: BaseModel, layer: Layer) -> tuple[BaseModel, dict[str, str]]:
    """``layer`` fondu dans ``base`` ; un chemin refusé est écarté (les autres restent)."""
    if not layer:
        return base, {}
    value, errors = forms.validate(model, base, dict(layer))
    if value is not None:
        return value, {}
    kept = {p: v for p, v in layer.items() if not any(_related(p, e) for e in errors)}
    refused = {p: next((m for e, m in errors.items() if _related(p, e)), "refusé") for p in layer if p not in kept}
    if kept:
        value, _ = forms.validate(model, base, kept)
        if value is not None:
            return value, refused
    return base, {p: refused.get(p, "refusé") for p in layer}


def _touches(path: str, layer: Layer) -> bool:
    return any(p and _related(path, p) for p in layer)


def planned(fac: Faculty[Any, Any], temperament: Temperament, overrides: Layer | None = None,
            inputs: Layer | None = None) -> Planned | None:
    """Le plan d'une faculté (``None`` si elle n'a pas de paramètres)."""
    if fac.params is None:
        return None
    model = fac.params
    base = _default(fac, temperament)
    derived = fac.derive(temperament, None) if fac.derive is not None else base
    natural, refused_inputs = _apply(model, derived, inputs or {})
    if refused_inputs:
        log.warning("paramètres de %s : réglages refusés %s", fac.name, refused_inputs)
    value, refused = _apply(model, natural, overrides or {})
    flat_base, flat_derived = forms.flatten(base), forms.flatten(derived)
    driven = {path for moved in influence(fac, temperament).values() for path, _lo, _hi in moved}
    sources = {}
    for path in forms.flatten(value):
        if _touches(path, overrides or {}) and not any(_related(path, r) for r in refused):
            sources[path] = OVERRIDE
        elif _touches(path, inputs or {}):
            sources[path] = SETTING
        elif path in driven or flat_derived.get(path) != flat_base.get(path):
            sources[path] = TEMPERAMENT
        else:
            sources[path] = DEFAULT
    return Planned(fac.name, model, value, natural, sources, refused)


def plan(faculties: Sequence[Faculty[Any, Any]], temperament: Temperament,
         overrides: Mapping[str, Layer] | None = None, inputs: Mapping[str, Layer] | None = None
         ) -> dict[str, Planned]:
    out = {}
    for fac in faculties:
        p = planned(fac, temperament, (overrides or {}).get(fac.name), (inputs or {}).get(fac.name))
        if p is not None:
            out[fac.name] = p
    return out


def influence(fac: Faculty[Any, Any], temperament: Temperament) -> dict[str, tuple[tuple[str, Any, Any], ...]]:
    """Ce que chaque curseur pilote dans cette faculté : ``curseur → ((chemin, à 0, à 1), …)``,
    mesuré en poussant le curseur à ses deux bouts (les autres restant où ils sont)."""
    if fac.derive is None:
        return {}
    out: dict[str, tuple[tuple[str, Any, Any], ...]] = {}
    for slider in SLIDERS:
        lo = forms.flatten(fac.derive(temperament.model_copy(update={slider: 0.0}), None))
        hi = forms.flatten(fac.derive(temperament.model_copy(update={slider: 1.0}), None))
        moved = tuple((path, lo[path], hi[path]) for path in lo if lo[path] != hi.get(path))
        if moved:
            out[slider] = moved
    return out


def influences(faculties: Sequence[Faculty[Any, Any]], temperament: Temperament
               ) -> dict[str, list[tuple[str, str, Any, Any]]]:
    """Pour chaque curseur : ``(faculté, chemin, à 0, à 1)`` partout où il pilote quelque chose."""
    out: dict[str, list[tuple[str, str, Any, Any]]] = {s: [] for s in SLIDERS}
    for fac in faculties:
        for slider, moved in influence(fac, temperament).items():
            out[slider] += [(fac.name, path, lo, hi) for path, lo, hi in moved]
    return out


def to_journal(kernel: Kernel, planned_: Mapping[str, Planned], overrides: Mapping[str, Layer] | None = None,
               inputs: Mapping[str, Layer] | None = None) -> list[tuple[str, BaseModel]]:
    """Ce qu'il faut journaliser : les facultés qui dérivent du tempérament, celles
    qu'une surcharge ou un réglage touche, et celles qui ont déjà des paramètres
    journalisés (pour qu'enlever une surcharge ramène au défaut). Les autres gardent
    leur défaut sans un événement de plus."""
    stored = kernel.mind.root.slices["kernel"].params
    out = []
    for owner, p in sorted(planned_.items()):
        fac = kernel.registry.faculties.get(owner)
        if fac is None:
            continue
        if fac.derive is not None or (overrides or {}).get(owner) or (inputs or {}).get(owner) or owner in stored:
            out.append((owner, p.value))
    return out


# ── La console : lire, changer ────────────────────────────────────────────


@dataclass(slots=True)
class Parameters:
    """Ce que la console demande pour les paramètres internes. Les sources sont
    fournies par la composition (qui seule sait où vivent tempérament, réglages et
    surcharges)."""

    kernel: Kernel
    temperament: Callable[[], Temperament]
    overrides: Callable[[], Mapping[str, Layer]]
    save_overrides: Callable[[dict[str, dict[str, Any]]], Awaitable[None]]
    inputs: Callable[[], Mapping[str, Layer]]
    #: rejournalise (``configure``) ; rend les problèmes
    apply: Callable[[], Awaitable[list[str]]]

    def faculties(self) -> list[Faculty[Any, Any]]:
        return [f for _, f in sorted(self.kernel.registry.faculties.items()) if f.params is not None]

    def plan(self, owner: str) -> Planned | None:
        fac = self.kernel.registry.faculties.get(owner)
        if fac is None:
            return None
        return planned(fac, self.temperament(), self.overrides().get(owner), self.inputs().get(owner))

    def journaled(self, owner: str) -> BaseModel | None:
        """Les paramètres en vigueur (journalisés), ou ``None`` : le défaut."""
        fac = self.kernel.registry.faculties.get(owner)
        record = self.kernel.mind.root.slices["kernel"].params.get(owner)
        if fac is None or fac.params is None or record is None:
            return None
        try:
            return fac.params.model_validate(drop_retired(json.loads(record.data), fac.retired_params))
        except ValueError:
            return None

    def influence(self, owner: str) -> dict[str, tuple[tuple[str, Any, Any], ...]]:
        fac = self.kernel.registry.faculties.get(owner)
        return influence(fac, self.temperament()) if fac is not None else {}

    def influences(self) -> dict[str, list[tuple[str, str, Any, Any]]]:
        return influences(self.faculties(), self.temperament())

    @staticmethod
    def slider_labels() -> dict[str, str]:
        return {f.path: f.label for f in forms.describe(Temperament)}

    def fields(self, owner: str) -> tuple[forms.FormField, ...]:
        """Les champs du bloc avancé ; ce qu'un réglage fournit s'y lit sans s'y changer
        (il se change là où il vit : les propriétaires, dans « Canaux »)."""
        fac = self.kernel.registry.faculties.get(owner)
        if fac is None or fac.params is None:
            return ()
        given = self.inputs().get(owner) or {}
        return tuple(dataclasses.replace(f, readonly=True) if _touches(f.path, given) else f
                     for f in forms.describe(fac.params))

    async def change(self, owner: str, form: Mapping[str, Sequence[str]]) -> tuple[bool, dict[str, str]]:
        """Relit le formulaire avancé d'une faculté : une valeur égale à la valeur
        naturelle retire la surcharge, une autre la pose. Rend (changé ?, erreurs)."""
        p = self.plan(owner)
        if p is None:
            return False, {"": "Faculté inconnue."}
        fields = self.fields(owner)
        current = forms.flatten(p.value)
        values, errors = forms.parse(fields, {k: list(v) for k, v in form.items()}, current=current)
        errors = {**errors, **forms.within(fields, values)}
        if errors:
            return False, errors
        natural = forms.flatten(p.natural)
        layer = dict(self.overrides().get(owner) or {})
        for path, value in values.items():
            if _close(value, current.get(path)) and not _plain_eq(value, current.get(path)):
                continue  # la valeur montrée arrondie, renvoyée telle quelle : rien n'a changé
            layer = {k: v for k, v in layer.items() if not (k == path or k.startswith(path + "."))}
            if _plain_eq(value, natural.get(path)) or _close(value, natural.get(path)):
                continue
            layer[path] = _jsonable(value)
        fac = self.kernel.registry.faculties[owner]
        check = planned(fac, self.temperament(), layer, self.inputs().get(owner))
        if check is None or check.refused:
            return False, dict(check.refused) if check is not None else {"": "refusé"}
        return await self._store(owner, layer), {}

    async def reset(self, owner: str, path: str = "") -> bool:
        """Retire une surcharge (ou toutes celles de la faculté)."""
        layer = dict(self.overrides().get(owner) or {})
        kept = {k: v for k, v in layer.items() if path and not (k == path or k.startswith(path + "."))}
        if kept == layer:
            return False
        return await self._store(owner, kept)

    async def _store(self, owner: str, layer: dict[str, Any]) -> bool:
        before = {k: dict(v) for k, v in self.overrides().items()}
        after = {**before, owner: layer} if layer else {k: v for k, v in before.items() if k != owner}
        if after == before:
            return False
        await self.save_overrides(after)
        problems = await self.apply()
        if problems:
            await self.save_overrides(before)
            await self.apply()
            raise ValueError("; ".join(problems))
        return True


#: la console montre un réel à 6 chiffres significatifs : renvoyé tel quel, il vaut la valeur exacte
SHOWN_DIGITS = 6


def shown(value: float) -> str:
    """Un réel tel que la console l'affiche dans un champ (``1.42857``, ``5.21757e-06``)."""
    return f"{value:.{SHOWN_DIGITS}g}"


def _close(a: Any, b: Any) -> bool:
    """Deux réels égaux à l'affichage près (un champ montré arrondi, renvoyé sans y toucher)."""
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, float | int) or not isinstance(b, float):
        return False
    return shown(float(a)) == shown(b)


def _plain_eq(a: Any, b: Any) -> bool:
    return _jsonable(a) == _jsonable(b)


def _jsonable(value: Any) -> Any:
    """Une valeur telle qu'elle se range dans les réglages (JSON)."""
    return json.loads(json.dumps(forms.plain(value), default=_default_json))


def _default_json(value: Any) -> Any:
    if isinstance(value, set | frozenset):
        return sorted(value, key=str)
    if hasattr(value, "value"):
        return value.value
    return str(value)
