"""La liste de composition : quelles facultés forment Mika.

Ajouter une faculté = ajouter son paquet et l'inscrire ici. Tout le reste
(registre, rejeu, prompt, arbitrage, inspecteur) la découvre seul.
"""

from __future__ import annotations

from typing import Any

from mika.kernel.faculty import Faculty


def faculties() -> list[Faculty[Any, Any]]:
    """Les facultés de Mika (remplies à partir de M1)."""
    return []
