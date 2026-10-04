"""Un fournisseur d'images factice, pour les essais et le simulateur : une petite
image PNG unie dont la couleur dépend du prompt (même prompt, même image), aux
proportions demandées. Il retient les demandes reçues ; il peut refuser (un mot
du prompt), tomber en panne ou prendre son temps."""

from __future__ import annotations

import asyncio
import hashlib
import struct
import zlib
from collections.abc import Iterable

from mika.adapters.imaging.errors import ImagingError
from mika.adapters.imaging.sizes import pixels
from mika.ports.imaging import OK, REFUSED, ImageCaps, ImageRequest, ImageResult, Picture

#: l'image rendue est réduite de ce facteur (une image de 1024 px pèserait pour rien dans un essai)
SHRINK = 16


def solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """Un PNG uni (RVB, 8 bits), sans bibliothèque."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    row = b"\x00" + bytes(rgb) * width
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


class FakeImageBackend:
    def __init__(self, name: str = "fake", *, caps: ImageCaps | None = None, model: str = "fake-image",
                 refuse: Iterable[str] = (), fail: str = "", latency: float = 0.0) -> None:
        self.name = name
        self.model = model
        self.caps = caps or ImageCaps(edit=True, max_refs=4, transparent=True, negative=True, seed=True,
                                      local=True)
        self.refuse = tuple(w.lower() for w in refuse)
        #: non vide : chaque appel lève ``ImagingError`` avec ce message
        self.fail = fail
        self.latency = latency
        self.requests: list[ImageRequest] = []

    async def generate(self, req: ImageRequest) -> ImageResult:
        self.requests.append(req)
        if self.latency:
            await asyncio.sleep(self.latency)
        if self.fail:
            raise ImagingError(self.fail)
        w, h = pixels(req.aspect, req.quality)
        size = f"{w}x{h}"
        if any(word in req.prompt.lower() for word in self.refuse):
            return ImageResult(REFUSED, backend=self.name, model=self.model, size=size,
                               reason="refusé par la modération (factice)")
        digest = hashlib.sha256(f"{req.prompt}|{req.seed}".encode()).digest()
        width, height = max(1, w // SHRINK), max(1, h // SHRINK)
        data = solid_png(width, height, (digest[0], digest[1], digest[2]))
        return ImageResult(OK, (Picture("image/png", data, width, height),), backend=self.name, model=self.model,
                           size=size, quality=req.quality)
