"""Shared parsing utilities for JSON extraction from LLM responses."""

from __future__ import annotations

import json
import re

# Bloc JSON entoure de fences markdown. Le contenu est non gourmand, mais le
# ``\s*``` `` qui suit force le moteur a etendre jusqu'a la vraie fin du bloc.
_FENCED_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

# Un modele qui prefixe sa reponse peut semer des accolades dans sa prose. On
# borne le nombre de candidats testes par le scan equilibre : c'est un repli,
# pas un analyseur syntaxique.
_MAX_SCAN_CANDIDATES = 32


def strip_markdown_json(raw: str) -> str:
    """Extract JSON from a response that may be wrapped in markdown code fences.

    Quatre strategies, dans cet ordre, la premiere qui produit un objet JSON
    valide gagne ; ``raw`` est renvoye inchange si aucune n'aboutit :

    1. le bloc entre fences markdown, s'il y en a un ;
    2. la chaine entiere, si elle est deja du JSON ;
    3. l'ancrage sur la **derniere** accolade ouvrante — un modele qui preface
       sa reponse ("Voici l'analyse au format {cle: valeur} : ...") met son
       JSON en queue, et le repli historique ``re.search(r"\\{.*\\}")``, gourmand
       du *premier* ``{`` au *dernier* ``}``, capturait alors une chaine non
       parsable : l'appel LLM etait facture puis jete ;
    4. a defaut, un scan a accolades equilibrees, qui rend le cas imbrique
       deterministe au lieu de le confier au backtracking d'une regex.
    """
    if not raw:
        return raw
    text = raw.strip()

    # 1. Bloc entre fences.
    match = _FENCED_RE.search(text)
    if match and _is_json_object(match.group(1)):
        return match.group(1)

    # 2. La reponse est deja du JSON nu.
    if _is_json_object(text):
        return text

    # 3. Ancrage sur la derniere accolade ouvrante (JSON en queue de reponse).
    last_open = text.rfind("{")
    if last_open > 0:
        candidate = text[last_open:].strip()
        if _is_json_object(candidate):
            return candidate

    # 4. Scan a accolades equilibrees, depuis chaque ouvrante.
    candidate = _first_balanced_object(text)
    if candidate is not None:
        return candidate

    return raw


def _is_json_object(candidate: str) -> bool:
    """Le candidat est-il un objet JSON ? Une liste ou un scalaire ne l'est
    pas : tous les appelants lisent le resultat avec ``.get()``, et leur
    rendre un ``int`` remplacerait un echec de parse par un ``AttributeError``
    qui, lui, ne serait pas rattrape."""
    try:
        return isinstance(json.loads(candidate), dict)
    except (ValueError, TypeError):
        return False


def _balanced_object(text: str, start: int) -> str | None:
    """Sous-chaine ``{...}`` equilibree demarrant a ``start``, ou ``None`` si
    aucune fermeture ne vient. Les accolades a l'interieur d'une chaine JSON
    ne comptent pas."""
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _first_balanced_object(text: str) -> str | None:
    """Premier objet equilibre *et* parsable, en partant de chaque accolade
    ouvrante dans l'ordre. Une accolade de prose ("format {cle: valeur}")
    produit un bloc equilibre mais invalide : on passe simplement a la
    suivante au lieu d'abandonner."""
    start = text.find("{")
    tried = 0
    while start != -1 and tried < _MAX_SCAN_CANDIDATES:
        candidate = _balanced_object(text, start)
        if candidate is not None and _is_json_object(candidate):
            return candidate
        tried += 1
        start = text.find("{", start + 1)
    return None
