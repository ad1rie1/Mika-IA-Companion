"""Les noms de l'annuaire, et les postes : des règles pures — ni base, ni entrée-sortie — que seul son magasin
(``store.py``) applique.

- **Un nom vu, rangé** (``clean_name`` : blancs repliés, sans guillemets autour, borné à ``NAME_MAX`` ; vide pour une
  adresse donnée comme nom), de même un poste ou un service (``clean_role``) ; un nom qui a une lettre (``lettered``).
- **Ses mots** : ceux qu'on compare (``name_words`` : repliés, sans ponctuation), ceux que le juge rapproche
  (``name_tokens``, ADR 0304).
- **Le nom d'un contact** d'après ce qu'on lui voit (``name_of``), son poste et son service (``role_of``).
- **Ce que le nom seul rapproche** (``rule_pairs``) : le même nom complet, une initiale et le même nom, et, plus
  faible, un prénom seul et le prénom d'un nom complet — des suggestions, jamais une réunion.
- **Un nom dans un texte** (``name_index``, ``names_in``) : ce qu'un fait ou une raison nomme.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from mika.ports.contacts import COMPANY, DOMAIN, OPAQUE_KINDS, ORG
from mika.ports.paging import fold_text

#: un nom vu, au plus (caractères)
NAME_MAX = 200
#: un même nom chez plus de tant de contacts ne se propose plus (un nom de service, pas une personne)
SAME_NAME_MAX = 20
#: un prénom seul se propose s'il a au moins tant de lettres (« Jo » ne rapproche personne)
FIRST_NAME_MIN = 3
#: ce qui sépare les mots d'un nom comparé (``Rousseau, Gilles`` : deux mots)
_NAME_MARKS = str.maketrans({c: " " for c in ".,;:()[]{}\"'«»“”‘’/\\|_"})


def clean_name(name: str) -> str:
    """Un nom vu, rangé : blancs repliés, sans guillemets autour, borné ; vide pour une adresse donnée comme nom."""
    found = " ".join((name or "").replace("\x00", " ").split()).strip("\"'“”«»‘’ ")
    return "" if "@" in found else found[:NAME_MAX]


def clean_role(text: str) -> str:
    """Un poste, un service : blancs repliés, borné."""
    return " ".join((text or "").replace("\x00", " ").split())[:NAME_MAX]


def name_words(name: str) -> list[str]:
    """Les mots d'un nom, comparés (repliés, sans ponctuation) : « ROUSSEAU, Gilles » → ``rousseau``, ``gilles``."""
    return fold_text(name).translate(_NAME_MARKS).split()


def rule_pairs(rows: Sequence[Any], informal: set[int]) -> dict[tuple[int, int], str]:
    """Les paires que le nom seul rapproche (``Suggestion.reason``) : le même nom complet, une initiale et le même nom,
    et, plus faible, un prénom seul (d'une fiche qu'on nomme ainsi) et le prénom d'un nom complet."""
    full: dict[str, list[int]] = {}
    spelled: dict[tuple[str, str], list[int]] = {}
    initials: dict[tuple[str, str], list[int]] = {}
    #: un prénom seul (des fiches qu'on nomme ainsi) ; le prénom des noms complets
    alone: dict[str, list[int]] = {}
    firsts: dict[str, list[int]] = {}
    for r in rows:
        words = name_words(r.name)
        if not lettered(r.name) or "@" in r.name:
            continue
        if len(words) == 1:
            if int(r.id) in informal and len(words[0]) >= FIRST_NAME_MIN:
                alone.setdefault(words[0], []).append(int(r.id))
            continue
        if len(words) < 2:
            continue
        if len(words[0]) >= FIRST_NAME_MIN:
            firsts.setdefault(words[0], []).append(int(r.id))
        short = [w for w in words if len(w) == 1]
        if short:  # « G. Rousseau » : une initiale et un nom
            if len(words) == 2 and len(short) == 1:
                initials.setdefault((short[0], next(w for w in words if len(w) > 1)), []).append(int(r.id))
            continue
        full.setdefault(" ".join(sorted(words)), []).append(int(r.id))
        for i, w in enumerate(words):
            for j, v in enumerate(words):
                if i != j:
                    spelled.setdefault((w[0], v), []).append(int(r.id))
    pairs: dict[tuple[int, int], str] = {}
    for ids in full.values():
        if 1 < len(ids) <= SAME_NAME_MAX:
            for x, a in enumerate(ids):
                for b in ids[x + 1:]:
                    pairs.setdefault((min(a, b), max(a, b)), "same_name")
    for key, ids in initials.items():
        whole = sorted(set(spelled.get(key, ())))
        if len(whole) > SAME_NAME_MAX:
            continue
        for a in ids:
            for b in whole:
                if a != b:
                    pairs.setdefault((min(a, b), max(a, b)), "initial")
    for word, ids in alone.items():  # plus faible : le même prénom, d'un côté sans nom de famille
        others = sorted({*ids, *firsts.get(word, ())})
        if len(others) > SAME_NAME_MAX:
            continue
        for a in ids:
            for b in others:
                if a != b:
                    pairs.setdefault((min(a, b), max(a, b)), "first_name")
    return pairs


#: les mots d'un nom comparés par le juge : ses lettres et ses chiffres, repliés — un trait d'union, une parenthèse,
#: un crochet séparent (« MASSOL-EXT » : ``massol``, ``ext``)
_TOKENS = re.compile(r"[a-z0-9]+")


def name_tokens(name: str) -> list[str]:
    """Les mots d'un nom tels que le juge les rapproche (ADR 0304) : repliés, séparés par tout ce qui n'est ni lettre
    ni chiffre, ceux qui ont une lettre — sans rien retirer d'autre : c'est leur rareté dans l'annuaire qui dit s'ils
    comptent (« ext », que portent tous les prestataires, ne rapproche personne)."""
    return [w for w in _TOKENS.findall(fold_text(name or "")) if any(c.isalpha() for c in w)]


def name_of(kind: str, idents: Sequence[tuple[str, str, bool]], names: Sequence[tuple[str, bool, str]]) -> str:
    """Le nom d'un contact (``names`` : sorte de l'identifiant, générique, nom — le plus récent d'abord) : une
    organisation, son nom d'entreprise le plus récent, sinon son domaine ; une personne, le plus récent qu'on lui voit
    (ceux d'une adresse générique ne comptent pas), sinon son premier identifiant."""
    if kind == ORG:
        found = next((n for k, _, n in names if n and k == COMPANY), "")
        return found or next((v for k, v, _ in idents if k == DOMAIN), idents[0][1] if idents else "")
    found = next((n for _, generic, n in names if n and not generic and lettered(n)), "") or \
        next((n for _, generic, n in names if n and not generic), "")
    # sans nom vu : un identifiant qui se lit (une clé du téléphone, un nom raconté, non), sinon le premier
    return found or next((v for k, v, g in idents if not g and k not in OPAQUE_KINDS),
                         next((v for k, v, g in idents if not g), idents[0][1] if idents else ""))


def lettered(name: str) -> bool:
    """Un nom qui a au moins une lettre (pas un numéro donné comme nom)."""
    return any(c.isalpha() for c in name)


#: les mots d'un texte, avec leur casse (un nom d'un seul mot ne se reconnaît qu'écrit avec sa majuscule)
_TEXT_WORDS = re.compile(r"[^\W\d_]+")


def name_index(names: Iterable[str]) -> dict[str, list[tuple[str, ...]]]:
    """Des noms à reconnaître dans un texte, par leur premier mot replié : un nom de plusieurs mots, ou d'un seul mot
    d'au moins ``FIRST_NAME_MIN`` lettres (ni un numéro, ni une adresse)."""
    out: dict[str, list[tuple[str, ...]]] = {}
    for name in names:
        if not name or "@" in name or not lettered(name):
            continue
        words = tuple(_TEXT_WORDS.findall(fold_text(name)))
        if not words or (len(words) == 1 and len(words[0]) < FIRST_NAME_MIN):
            continue
        out.setdefault(words[0], [])
        if words not in out[words[0]]:
            out[words[0]].append(words)
    return out


def names_in(text: str, wanted: Mapping[str, Sequence[tuple[str, ...]]]) -> bool:
    """Ce texte nomme-t-il l'un de ces noms (``name_index``) : ses mots à la suite ; un nom d'un seul mot, écrit avec
    sa majuscule (« il gère le support » ne nomme pas « Support »)."""
    raw = _TEXT_WORDS.findall(text or "")
    words = [fold_text(w) for w in raw]
    for i, w in enumerate(words):
        for name in wanted.get(w, ()):
            if len(name) == 1:
                if raw[i][:1].isupper():
                    return True
            elif tuple(words[i:i + len(name)]) == name:
                return True
    return False


def role_of(roles: Sequence[tuple[str, str]]) -> tuple[str, str]:
    """Le poste et le service d'un contact : chacun le plus récent qu'on lui voit (``roles`` : le plus récent
    d'abord)."""
    return (next((t for t, _ in roles if t), ""), next((d for _, d in roles if d), ""))
