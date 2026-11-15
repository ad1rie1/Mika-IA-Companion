"""Ce que veut dire une panne du monde extérieur, pour un opérateur.

Les adaptateurs et les ports lèvent leurs propres erreurs (le serveur de courrier,
Claude Code, le magasin, les modèles) ; le noyau ne connaît que celles de Python et
la sienne. Leur sens est indexé par nom de classe, parce que les erreurs se gardent
aussi en texte (« NomDeClasse: message », un ``repr``) : un texte gardé n'est reconnu
que si son nom y figure, ou finit par « Error » ou « Exception ». Un adaptateur
nouveau vient inscrire ici le sens de ses pannes.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from mika.kernel import inspect as kernel_inspect

#: le sens des erreurs des adaptateurs et des ports, par nom de classe
OUTSIDE: Mapping[str, str] = MappingProxyType({
    "UnconfiguredRole": "aucun modèle configuré",  # adapters/llm/gateway.py
    "MissingPersona": "persona manquante",  # ports/llm.py
    "StoreSealed": "magasin fermé",  # adapters/store_sql/store.py
    "ListingFailed": "liste indisponible",  # adapters/listing.py
    "ClaudeCodeError": "erreur de Claude Code",  # adapters/llm/claude_code.py
    "ImapError": "erreur du serveur de courrier",  # adapters/mail/imap.py
})


def describe_error(error: BaseException | str) -> str:
    """Une erreur en français, pour un opérateur, celles du monde extérieur comprises :
    ``kernel.inspect.describe_error`` avec ``OUTSIDE``."""
    return kernel_inspect.describe_error(error, meanings=OUTSIDE)
