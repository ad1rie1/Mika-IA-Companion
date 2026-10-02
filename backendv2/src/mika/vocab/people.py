"""Qui est une personne : identifiants réservés, adresses éphémères, noms.

Une adresse (``handle``) est ce par quoi quelqu'un lui écrit : ``user_7``
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
#: Tous les tirets d'Unicode (et le signe moins) : une suite d'entre eux imite les
#: titres des sections du prompt (« --- QUI TU AS EN FACE --- »).
_DASHES = "\\-\u2010\u2011\u2012\u2013\u2014\u2015\u2043\u2212\u2e3a\u2e3b\ufe58\ufe63\uff0d"
_DASH_RUN = re.compile(rf"[{_DASHES}](?:\s*[{_DASHES}])+")
#: Les mots qui encadrent son état interne, quelle que soit la casse ou l'accent
#: (« --- FIN ETAT INTERNE --- » tapé dans un nom ou un titre).
_INNER_STATE = re.compile(r"[EÉÈÊeéèê]\s*[Tt]\s*[AaÀàÂâ]\s*[Tt]\s+[IiÎî]\s*[Nn]\s*[Tt]\s*[EÉÈeéè]\s*[Rr]\s*[Nn]\s*[EÉÈeéè]")


def neutralize(text: str) -> str:
    """Ce qui vient d'ailleurs ne peut pas imiter la charpente du prompt : une
    suite de tirets (de n'importe quel alphabet) devient un seul tiret, et les
    mots « état interne » (toute casse, tout accent) disparaissent."""
    if not text:
        return ""
    return _INNER_STATE.sub(" ", _DASH_RUN.sub("-", text))


def is_internal(handle: str | None) -> bool:
    return (handle or "") in INTERNAL_IDS


def is_ephemeral(handle: str | None) -> bool:
    return (handle or "").startswith(EPHEMERAL_PREFIX)


def is_identifiable(handle: str | None) -> bool:
    """Vaut-il la peine d'attacher une mémoire durable à cette adresse ?"""
    return not is_internal(handle) and not is_ephemeral(handle)


def account_handle(account_id: int) -> str:
    return f"{ACCOUNT_PREFIX}{account_id}"


def client_claim_allowed(handle: str | None) -> bool:
    """Une adresse qu'un navigateur peut annoncer lui-même (``identify``)."""
    if not handle or not _CLIENT_ID.match(handle):
        return False
    if handle in INTERNAL_IDS:
        return False
    return not handle.startswith(RESERVED_PREFIXES)


def clean_display_name(raw: str | None, *, max_chars: int = DISPLAY_NAME_MAX) -> str:
    """Un nom d'affichage tel qu'il peut entrer dans un prompt : blancs repliés,
    caractères invisibles et guillemets retirés, longueur bornée après
    nettoyage. Un nom est une donnée citée, jamais une consigne : il ne peut
    imiter ni un titre de section (une suite de tirets) ni la fin de son état
    interne (``neutralize``)."""
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
    cleaned = neutralize("".join(kept))
    return " ".join(cleaned.split())[:max_chars].strip(" -")


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


def clean_tokens(text: str) -> str:
    """Le texte sans les jetons de personnes (« Chloé [P1] » → « Chloé ») : l'extraction s'en sert pour dire qui
    c'est ; ils ne doivent finir ni dans un souvenir, ni dans un rêve."""
    return re.sub(r"[ \t]*\[P\d{1,3}\]", "", text).strip()
