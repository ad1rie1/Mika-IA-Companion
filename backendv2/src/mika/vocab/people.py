"""Qui est une personne : identifiants réservés, poignées éphémères, noms.

Une poignée (``handle``) est l'adresse de transport de quelqu'un : ``user_7``
(compte web authentifié), ``web_…`` (navigateur identifié sans compte),
``anon_…`` (une connexion, jetable), ``tg_…`` (Telegram). Une personne peut
en avoir plusieurs ; la faculté ``identity`` les relie.
"""

from __future__ import annotations

import re
import unicodedata

#: Pas des personnes : la tuyauterie de Mika elle-même.
INTERNAL_IDS = frozenset({"conscience_mika", "__global__", "anonymous", ""})
EPHEMERAL_PREFIX = "anon_"
ACCOUNT_PREFIX = "user_"
#: Préfixes qu'un client ne peut pas revendiquer dans une trame ``identify`` :
#: ils sont émis par le serveur (compte, connexion, Telegram, modules, soi).
RESERVED_PREFIXES = ("tg_", "module_", "conscience", ACCOUNT_PREFIX, EPHEMERAL_PREFIX)
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

DISPLAY_NAME_MAX = 40
_INVISIBLE = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
_QUOTES = frozenset('«»"“”')


def is_internal(handle: str | None) -> bool:
    return (handle or "") in INTERNAL_IDS


def is_ephemeral(handle: str | None) -> bool:
    return (handle or "").startswith(EPHEMERAL_PREFIX)


def is_identifiable(handle: str | None) -> bool:
    """Vaut-il la peine d'attacher une mémoire durable à cette poignée ?"""
    return not is_internal(handle) and not is_ephemeral(handle)


def account_handle(account_id: int) -> str:
    return f"{ACCOUNT_PREFIX}{account_id}"


def client_claim_allowed(handle: str | None) -> bool:
    """Une poignée qu'un navigateur peut annoncer lui-même (``identify``)."""
    if not handle or not _CLIENT_ID.match(handle):
        return False
    if handle in INTERNAL_IDS:
        return False
    return not handle.startswith(RESERVED_PREFIXES)


def clean_display_name(raw: str | None, *, max_chars: int = DISPLAY_NAME_MAX) -> str:
    """Un nom d'affichage tel qu'il peut entrer dans un prompt : blancs repliés,
    caractères invisibles et guillemets retirés, longueur bornée après
    nettoyage. Un nom est une donnée citée, jamais une consigne."""
    if not isinstance(raw, str) or not raw:
        return ""
    kept: list[str] = []
    for c in raw:
        if c.isspace():
            kept.append(" ")
        elif c in _QUOTES or unicodedata.category(c) in _INVISIBLE:
            continue
        else:
            kept.append(c)
    return " ".join("".join(kept).split())[:max_chars].strip()


def fold(text: str) -> str:
    """Casse et accents repliés (comparaison de noms)."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)).strip()


def same_name(a: str | None, b: str | None) -> bool:
    """Deux noms désignent-ils la même personne ? Un prénom vaut le nom complet."""
    fa, fb = fold(a or ""), fold(b or "")
    if not fa or not fb:
        return False
    if fa == fb:
        return True
    return fa.split()[0] == fb.split()[0]
