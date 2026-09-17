"""Les trois orchestrateurs du pipeline restent lisibles.

``gather_context``, ``process_message`` et ``broadcast_to_websocket``
faisaient ~300, ~450 et ~130 lignes : des corps trop longs pour être lus,
alors que chacun est une suite d'étapes dont l'ORDRE est porteur (la question
persistée après le contexte et avant l'appel IA, la ``speech`` avant
l'``inner_state``…). Ils sont maintenant des orchestrations qui appellent des
étapes nommées ; ce test borne leur longueur pour que la dette ne revienne
pas une fonction à la fois.

Mesuré sur l'AST — les lignes de code du corps, docstring exclue : une
docstring qui explique l'ordre des étapes est précisément ce qu'on veut
garder, pas ce qu'on veut décourager.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_PIPELINE = pathlib.Path(__file__).resolve().parent.parent / "pipeline"

# (fichier, fonction, lignes de code maximales)
_BORNES = (
    ("context.py", "gather_context", 80),
    ("processor.py", "process_message", 100),
    ("broadcast.py", "broadcast_to_websocket", 40),
)


def _lignes_de_code(path: pathlib.Path, nom: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == nom:
            corps = node.body
            if ast.get_docstring(node) is not None:
                corps = corps[1:]
            return node.end_lineno - corps[0].lineno + 1
    raise AssertionError(f"{nom} introuvable dans {path.name}")


@pytest.mark.parametrize("fichier, nom, borne", _BORNES)
def test_l_orchestrateur_reste_court(fichier, nom, borne):
    lignes = _lignes_de_code(_PIPELINE / fichier, nom)
    assert lignes <= borne, (
        f"{fichier}::{nom} fait {lignes} lignes de code (borne {borne}) — "
        "extraire une étape nommée plutôt que d'allonger l'orchestration"
    )


def test_les_etapes_sont_nommees_dans_l_ordre_du_data_flow():
    """L'orchestration de ``process_message`` appelle ses étapes dans l'ordre
    documenté (contexte → question → modèle → émotion → réponse → annonce →
    diffusion). Pinné sur les ``lineno`` des appels, jamais sur le texte."""
    tree = ast.parse((_PIPELINE / "processor.py").read_text(encoding="utf-8"))
    corps = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "process_message"
    )
    premiere_ligne: dict[str, int] = {}
    for node in ast.walk(corps):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            premiere_ligne.setdefault(node.func.id, node.lineno)
    attendu = [
        "_contexte_du_tour", "_ecrire_la_question", "_interroger_le_modele",
        "_ressentir", "_ecrire_la_reponse", "_annoncer_le_tour",
        "_vue_emotionnelle", "_diffuser",
    ]
    manquantes = [nom for nom in attendu if nom not in premiere_ligne]
    assert not manquantes, manquantes
    lignes = [premiere_ligne[nom] for nom in attendu]
    assert lignes == sorted(lignes), dict(zip(attendu, lignes))
