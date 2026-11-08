"""Qui est une personne : identifiants réservés, adresses éphémères, noms.

Une adresse (``handle``) est ce par quoi quelqu'un lui écrit : ``user_7``
(compte web authentifié), ``web_…`` (navigateur identifié sans compte),
``anon_…`` (une connexion, jetable), ``ext_…`` (un compte sur un réseau
extérieur, non sécurisé). Une personne peut en avoir plusieurs ; la faculté
``identity`` les relie.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from mika.kernel.prompt import LINE_DASHES, neutral
from mika.kernel.text import fold as text_fold
from mika.kernel.text import unaccented

#: Pas des personnes : la tuyauterie de Mika elle-même.
INTERNAL_IDS = frozenset({"conscience_mika", "__global__", "anonymous", ""})
EPHEMERAL_PREFIX = "anon_"
ACCOUNT_PREFIX = "user_"
EXTERNAL_PREFIX = "ext_"
#: Préfixes qu'un client ne peut pas revendiquer dans une trame ``identify`` :
#: ils sont émis par le serveur (compte, connexion, compte extérieur, modules, soi).
RESERVED_PREFIXES = (EXTERNAL_PREFIX, "module_", "conscience", ACCOUNT_PREFIX, EPHEMERAL_PREFIX)
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

DISPLAY_NAME_MAX = 40
_QUOTES = frozenset('«»"“”')


def neutralize(text: str) -> str:
    """Ce qui vient d'ailleurs ne peut pas imiter la charpente du prompt : la
    neutralisation du noyau (``kernel.prompt.neutral``), au seuil d'une ligne —
    ce qui ne se voit pas est retiré, deux tirets à la suite (de n'importe quelle
    graphie) deviennent un seul tiret, et les mots « état interne » (toute
    graphie) disparaissent : un nom ne les porte jamais."""
    if not text:
        return ""
    return neutral(text, run=LINE_DASHES, dash="-", state=" ")


def is_internal(handle: str | None) -> bool:
    return (handle or "") in INTERNAL_IDS


def is_ephemeral(handle: str | None) -> bool:
    return (handle or "").startswith(EPHEMERAL_PREFIX)


def is_identifiable(handle: str | None) -> bool:
    """Vaut-il la peine d'attacher une mémoire durable à cette adresse ?"""
    return not is_internal(handle) and not is_ephemeral(handle)


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
        elif c in _QUOTES or unicodedata.category(c) == "Cn":
            # un caractère que la table d'Unicode ne connaît pas : un nom s'en passe, comme avant l'ADR 0198, et sa
            # clé ``name:`` ne bouge pas (un texte le garde : c'est souvent un émoji) ; l'invisible, ``neutralize``
            # le retire
            continue
        else:
            kept.append(c)
    cleaned = neutralize("".join(kept))
    return " ".join(cleaned.split())[:max_chars].strip(" -")


def fold(text: str) -> str:
    """Le repli qui forme les clés ``name:…`` : casse et accents repliés, les ligatures gardées. Ces clés sont écrites
    au journal et l'oubli les recalcule : il ne suit pas ``kernel.text.fold`` (ADR 0212)."""
    return unaccented(text.lower()).strip()


def same_name(a: str | None, b: str | None) -> bool:
    """Deux noms désignent-ils la même personne ? Un prénom vaut le nom complet."""
    fa, fb = text_fold(a or "").strip(), text_fold(b or "").strip()
    if not fa or not fb:
        return False
    if fa == fb:
        return True
    return (len(fa.split()) == 1 or len(fb.split()) == 1) and fa.split()[0] == fb.split()[0]


def mentions(text: str | None, names: Iterable[str]) -> bool:
    """Le texte nomme-t-il une de ces personnes (son nom, ou son prénom, en mot entier ; casse et accents repliés) ?"""
    said = " " + " ".join(re.findall(r"\w+", text_fold(text or ""))) + " "
    for name in names:
        parts = re.findall(r"\w+", text_fold(name))
        if parts and len(parts[0]) >= 3 and (f" {parts[0]} " in said or f" {' '.join(parts)} " in said):
            return True
    return False


def named_label(key: str) -> str:
    """Le nom lisible d'une mention, ancienne ou contextualisée ; sa portée n'est pas un nom."""
    return key.removeprefix("name:").split(":", 1)[-1]


#: un contact connu par le téléphone de quelqu'un (ADR 0120) : « phone:<empreinte>:<nom> ». Ce n'est pas une
#: personne à qui elle parle ; pour les liens, c'est une personne que personne ne connaît (rien ne s'ouvre sur elle)
PHONE_PREFIX = "phone:"
#: les clés qui portent un nom en clair : leur oubli les remplace par un jeton opaque dans les enveloppes du journal
NAME_BEARING = ("name:", PHONE_PREFIX)


def phone_label(key: str) -> str:
    """Le nom d'un contact du téléphone (« phone:3fa9c2d81b0e:Léa » → « Léa ») ; ``""`` pour une autre clé."""
    if not key.startswith(PHONE_PREFIX):
        return ""
    parts = key.split(":", 2)
    return parts[2] if len(parts) == 3 else ""


#: les sources d'une lecture (ADR 0085) : un flux, un serveur d'outils, une page — des témoins, jamais des personnes
READ_PREFIXES = ("rss:", "mcp:", "web:")


def read_source(key: str) -> str:
    """« rss:Le Monde » → « Le Monde » ; ``""`` pour ce qui n'est pas une source de lecture."""
    return key.split(":", 1)[1] if key.startswith(READ_PREFIXES) else ""


def clean_tokens(text: str) -> str:
    """Le texte sans les jetons de personnes (« Chloé [P1] » → « Chloé ») : l'extraction s'en sert pour dire qui
    c'est ; ils ne doivent finir ni dans un souvenir, ni dans un rêve."""
    return re.sub(r"[ \t]*\[P\d{1,3}\]", "", text).strip()


def key_concerns(key: object, person: str) -> bool:
    """La clé d'une carte d'état parle-t-elle de cette personne : elle-même, ou une clé composée qui la porte
    (« elle|classe », « elle:moment », « sorte:elle ») ? Ce que retirent l'oubli d'une personne et l'expiration
    d'une inconnue (audit du 2026-10-26)."""
    if not isinstance(key, str) or not person:
        return False
    return key == person or key.startswith(f"{person}|") or key.startswith(f"{person}:") or key.endswith(f":{person}")
