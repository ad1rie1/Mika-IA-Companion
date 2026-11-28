"""Tailles et formats : traduire une proportion et une qualité en pixels, et lire
ce qu'un fournisseur a rendu (le type d'une image, ses dimensions) sans
bibliothèque d'images — quelques octets d'en-tête suffisent."""

from __future__ import annotations

import math
import struct

from mika.ports.imaging import ASPECTS

#: la surface visée par qualité (côté d'un carré équivalent, en pixels)
SIDE_BY_QUALITY = {"draft": 768, "normal": 1024, "high": 1280}


def pixels(aspect: str, quality: str, *, multiple: int = 64) -> tuple[int, int]:
    """(largeur, hauteur) pour une proportion et une qualité, en multiples de ``multiple`` : la surface d'un carré
    de ``SIDE_BY_QUALITY[qualité]`` répartie selon la proportion (1024 × 1024 → 832 × 1280 en portrait 2:3)."""
    ratio = ASPECTS.get(aspect, 1.0)
    side = SIDE_BY_QUALITY.get(quality, SIDE_BY_QUALITY["normal"])
    area = side * side

    def snap(v: float) -> int:
        return max(multiple, int(round(v / multiple)) * multiple)

    return snap(math.sqrt(area * ratio)), snap(math.sqrt(area / ratio))


def sniff(data: bytes) -> str:
    """Le type d'une image d'après ses premiers octets (« » : inconnu)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def dimensions(data: bytes) -> tuple[int, int]:
    """(largeur, hauteur) lues dans l'en-tête ; (0, 0) quand on ne sait pas les lire."""
    try:
        kind = sniff(data)
        if kind == "image/png" and len(data) >= 24:
            w, h = struct.unpack(">II", data[16:24])
            return int(w), int(h)
        if kind == "image/jpeg":
            return _jpeg(data)
        if kind == "image/webp":
            return _webp(data)
    except struct.error:
        pass
    return 0, 0


def _jpeg(data: bytes) -> tuple[int, int]:
    i, n = 2, len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # sans longueur
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):  # un début de trame : les dimensions
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return int(w), int(h)
        i += 2 + length
    return 0, 0


def _webp(data: bytes) -> tuple[int, int]:
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        w = int.from_bytes(data[24:27], "little") + 1
        h = int.from_bytes(data[27:30], "little") + 1
        return w, h
    if chunk == b"VP8 " and len(data) >= 30:
        w, h = struct.unpack("<HH", data[26:30])
        return int(w & 0x3FFF), int(h & 0x3FFF)
    if chunk == b"VP8L" and len(data) >= 25:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return 0, 0
