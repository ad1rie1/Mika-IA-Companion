"""État immuable : dictionnaire gelé à partage structurel, racine d'état.

``FrozenDict`` enveloppe un ``immutables.Map`` (HAMT : mise à jour en
O(log n) avec partage structurel) et **itère toujours dans l'ordre trié des
clés** : l'ordre d'un HAMT dépend du hachage des chaînes, donc de
``PYTHONHASHSEED`` — le trier est la condition du déterminisme.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, get_args

import immutables
from pydantic import GetCoreSchemaHandler
from pydantic_core import core_schema

K = TypeVar("K")
V = TypeVar("V")


class FrozenDict(Generic[K, V]):
    #: ``_keys`` : l'ordre trié, calculé à la première itération puis gardé (la valeur est immuable)
    __slots__ = ("_m", "_keys")

    def __init__(self, data: Mapping[K, V] | Iterable[tuple[K, V]] | None = None) -> None:
        self._keys: list[K] | None = None
        if isinstance(data, FrozenDict):
            self._m = data._m
            self._keys = data._keys
        elif isinstance(data, immutables.Map):
            self._m = data
        else:
            self._m = immutables.Map(data or {})

    # lecture
    def __getitem__(self, key: K) -> V:
        return self._m[key]

    def get(self, key: K, default: Any = None) -> Any:
        return self._m.get(key, default)

    def __contains__(self, key: object) -> bool:
        return key in self._m

    def __len__(self) -> int:
        return len(self._m)

    def __bool__(self) -> bool:
        return len(self._m) > 0

    def keys(self) -> list[K]:
        if self._keys is None:
            self._keys = sorted(self._m.keys(), key=_sort_key)
        return list(self._keys)

    def __iter__(self) -> Iterator[K]:
        return iter(self._sorted())

    def items(self) -> list[tuple[K, V]]:
        m = self._m
        return [(k, m[k]) for k in self._sorted()]

    def values(self) -> list[V]:
        m = self._m
        return [m[k] for k in self._sorted()]

    def _sorted(self) -> list[K]:
        if self._keys is None:
            self._keys = sorted(self._m.keys(), key=_sort_key)
        return self._keys

    # écriture (nouvelle valeur)
    def set(self, key: K, value: V) -> FrozenDict[K, V]:
        return FrozenDict(self._m.set(key, value))

    def delete(self, key: K) -> FrozenDict[K, V]:
        if key not in self._m:
            return self
        return FrozenDict(self._m.delete(key))

    def update(self, other: Mapping[K, V]) -> FrozenDict[K, V]:
        if not other:
            return self
        return FrozenDict(self._m.update(dict(other)))

    def to_dict(self) -> dict[K, V]:
        return dict(self.items())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FrozenDict):
            return self._m == other._m
        if isinstance(other, Mapping):
            return dict(self._m.items()) == dict(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._m)

    def __repr__(self) -> str:
        return f"FrozenDict({self.to_dict()!r})"

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        args = get_args(source)
        key_t, val_t = (args if len(args) == 2 else (Any, Any))
        dict_schema = handler.generate_schema(dict[key_t, val_t])
        from_dict = core_schema.no_info_after_validator_function(cls, dict_schema)
        return core_schema.json_or_python_schema(
            json_schema=from_dict,
            python_schema=core_schema.union_schema([core_schema.is_instance_schema(cls), from_dict]),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda m: m.to_dict(), return_schema=dict_schema
            ),
        )


def _sort_key(k: Any) -> tuple[str, Any]:
    return (type(k).__name__, k)


EMPTY: FrozenDict[Any, Any] = FrozenDict()


@dataclass(frozen=True, slots=True)
class Root:
    """Une racine d'état : immuable, épinglée par les frames.

    ``changed[propriétaire]`` est le ``seq`` du dernier événement qui a modifié
    sa tranche (sert d'empreinte aux faits qui varient avec le temps) ;
    ``tainted[propriétaire]`` le ``seq`` d'un réducteur qui a levé en direct.
    """

    seq: int = 0
    at: int = 0
    slices: FrozenDict[str, Any] = field(default_factory=FrozenDict)
    changed: FrozenDict[str, int] = field(default_factory=FrozenDict)
    tainted: FrozenDict[str, int] = field(default_factory=FrozenDict)

    def slice(self, owner: str) -> Any:
        return self.slices[owner]
