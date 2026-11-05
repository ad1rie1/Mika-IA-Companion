"""Lire une tuile vectorielle (le format Mapbox Vector Tile, version 2) : les points des calques demandés et leurs
propriétés, rien d'autre. Un protobuf lu à la main — des entiers variables, des champs à longueur —, sans dépendance :
l'index des lieux (``places.build``) en décode des centaines de milliers, et saute tout le reste (les bâtiments, les
routes) par sa longueur.

Un point hors de ``[0, extent)`` est le débord d'une tuile voisine (chaque tuile répète un peu de ses voisines) : il
est ignoré, et chaque point compte une fois, dans la tuile où il se trouve."""

from __future__ import annotations

import struct
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass

#: les sortes de géométrie et de commande du format
POINT = 1
MOVE_TO = 1
EXTENT = 4096

Props = dict[str, object]
#: ``accept(calque, propriétés)`` : garder ce point (sa géométrie n'est lue qu'alors)
Accept = Callable[[str, Mapping[str, object]], bool]


@dataclass(frozen=True, slots=True)
class Point:
    """Un point d'un calque : en coordonnées de la tuile (``0 <= x, y < extent``, l'origine en haut à gauche)."""

    layer: str
    x: int
    y: int
    extent: int
    props: Props


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    b = buf[i]
    if b < 0x80:
        return b, i + 1
    value, shift = b & 0x7F, 7
    i += 1
    while True:
        b = buf[i]
        i += 1
        value |= (b & 0x7F) << shift
        if b < 0x80:
            return value, i
        shift += 7
        if shift > 63:
            raise ValueError("un entier démesuré")


def _skip(buf: bytes, i: int, wire: int) -> int:
    if wire == 0:
        return _varint(buf, i)[1]
    if wire == 1:
        return i + 8
    if wire == 2:
        length, i = _varint(buf, i)
        return i + length
    if wire == 5:
        return i + 4
    raise ValueError("un champ d'une sorte inconnue")


def _packed(buf: bytes, i: int, end: int) -> list[int]:
    out: list[int] = []
    append = out.append
    while i < end:
        b = buf[i]
        if b < 0x80:
            append(b)
            i += 1
        else:
            value, i = _varint(buf, i)
            append(value)
    if i != end:
        raise ValueError("une liste tronquée")
    return out


def _value(buf: bytes, i: int, end: int) -> object:
    """Une valeur de propriété (``Tile.Value``) : texte, nombre ou booléen."""
    out: object = None
    while i < end:
        key, i = _varint(buf, i)
        field, wire = key >> 3, key & 7
        if field == 1 and wire == 2:
            length, i = _varint(buf, i)
            out = buf[i:i + length].decode("utf-8", "replace")
            i += length
        elif field == 2 and wire == 5:
            out = struct.unpack_from("<f", buf, i)[0]
            i += 4
        elif field == 3 and wire == 1:
            out = struct.unpack_from("<d", buf, i)[0]
            i += 8
        elif field in (4, 5, 6, 7) and wire == 0:
            raw, i = _varint(buf, i)
            out = (raw - (1 << 64) if raw >= 1 << 63 else raw) if field == 4 else \
                raw if field == 5 else (raw >> 1) ^ -(raw & 1) if field == 6 else bool(raw)
        else:
            i = _skip(buf, i, wire)
    return out


def _layer(buf: bytes, i: int, end: int, wanted: Collection[str], keys_wanted: Collection[str] | None,
           accept: Accept | None, out: list[Point]) -> None:
    name: str | None = None
    features: list[tuple[int, int]] = []
    keys: list[str] = []
    values: list[tuple[int, int]] = []
    extent = EXTENT
    while i < end:
        key, i = _varint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == 2:
            length, i = _varint(buf, i)
            stop = i + length
            if stop > end:
                raise ValueError("un calque tronqué")
            if field == 1:
                name = buf[i:stop].decode("utf-8", "replace")
                if name not in wanted:
                    return  # un autre calque : sauté d'un coup, par sa longueur
            elif field == 2:
                features.append((i, stop))
            elif field == 3:
                keys.append(buf[i:stop].decode("utf-8", "replace"))
            elif field == 4:
                values.append((i, stop))
            i = stop
        elif wire == 0:
            got, i = _varint(buf, i)
            if field == 5:
                extent = got
        else:
            i = _skip(buf, i, wire)
    if name is None or name not in wanted or not features or extent <= 0:
        return
    #: les clés lues (leurs indices) ; les valeurs, décodées à la demande, une fois chacune
    kept = {k: key for k, key in enumerate(keys) if keys_wanted is None or key in keys_wanted}
    decoded: dict[int, object] = {}
    for start, stop in features:
        tags: tuple[int, int] | None = None
        geometry: tuple[int, int] | None = None
        kind = 0
        j = start
        while j < stop:
            key, j = _varint(buf, j)
            field, wire = key >> 3, key & 7
            if wire == 2:
                length, j = _varint(buf, j)
                if j + length > stop:
                    raise ValueError("un objet tronqué")
                if field == 2:
                    tags = (j, j + length)
                elif field == 4:
                    geometry = (j, j + length)
                j += length
            elif wire == 0:
                got, j = _varint(buf, j)
                if field == 3:
                    kind = got
            else:
                j = _skip(buf, j, wire)
        if kind != POINT or geometry is None:
            continue
        props: Props = {}
        if tags is not None:
            pairs = _packed(buf, *tags)
            for t in range(0, len(pairs) - 1, 2):
                k, v = pairs[t], pairs[t + 1]
                if k in kept and v < len(values):
                    if v not in decoded:
                        decoded[v] = _value(buf, *values[v])
                    props[kept[k]] = decoded[v]
        if accept is not None and not accept(name, props):
            continue
        commands = _packed(buf, *geometry)
        x = y = c = 0
        while c < len(commands):
            command = commands[c]
            c += 1
            if command & 7 != MOVE_TO:
                break  # un point n'a que des « aller à »
            for _ in range(command >> 3):
                if c + 1 >= len(commands):
                    raise ValueError("une géométrie tronquée")
                dx, dy = commands[c], commands[c + 1]
                c += 2
                x += (dx >> 1) ^ -(dx & 1)
                y += (dy >> 1) ^ -(dy & 1)
                if 0 <= x < extent and 0 <= y < extent:
                    out.append(Point(name, x, y, extent, props))


def read_points(tile: bytes, layers: Collection[str], *, keys: Collection[str] | None = None,
                accept: Accept | None = None) -> list[Point]:
    """Les points des calques ``layers`` de cette tuile (déjà ouverte : sans gzip), avec leurs propriétés — seulement
    les clés ``keys`` si on les donne. ``accept`` écarte un point avant de lire sa géométrie. Abîmée : ``ValueError``."""
    out: list[Point] = []
    try:
        i, n = 0, len(tile)
        while i < n:
            key, i = _varint(tile, i)
            field, wire = key >> 3, key & 7
            if field == 3 and wire == 2:
                length, i = _varint(tile, i)
                end = i + length
                if end > n:
                    raise ValueError("une tuile tronquée")
                _layer(tile, i, end, layers, keys, accept, out)
                i = end
            else:
                i = _skip(tile, i, wire)
        if i != n:
            raise ValueError("une tuile tronquée")
    except (IndexError, struct.error) as exc:
        raise ValueError("une tuile tronquée ou abîmée") from exc
    return out
