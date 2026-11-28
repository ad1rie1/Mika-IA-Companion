"""Arbre de hasard : des flux nommés et stables.

Chaque consommateur tire d'un flux dérivé de (graine, chemin). Ajouter un flux
n'en perturbe aucun autre — deux variantes d'un scénario partagent leurs
tirages communs (nombres aléatoires communs).
"""

from __future__ import annotations

import hashlib
import random


class RngTree:
    def __init__(self, seed: int | str, path: tuple[str, ...] = ()) -> None:
        self.seed = seed
        self.path = path

    def child(self, *names: str) -> RngTree:
        return RngTree(self.seed, (*self.path, *names))

    def rng(self) -> random.Random:
        d = hashlib.blake2b(f"{self.seed}:{'/'.join(self.path)}".encode(), digest_size=8).digest()
        return random.Random(int.from_bytes(d, "big"))

    def __repr__(self) -> str:
        return f"RngTree({self.seed!r}, {'/'.join(self.path)})"
