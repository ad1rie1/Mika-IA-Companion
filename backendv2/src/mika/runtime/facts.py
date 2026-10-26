"""Les faits d'un texte, et ce qu'une récriture doit en garder.

Un fait : un nombre (une température, une heure, un montant, une date — blancs, y
compris insécables, et ponctuation finale ôtés) ou un lien. Une récriture (la
seconde passe, l'autrice d'un brouillon) les garde tous, sinon le premier jet
part : l'autrice ne voit pas les résultats des outils qui l'ont fondé.

Elle écrit comme on parle — « trois idées », « à seize heures », « le 28 octobre »,
« quatre-vingts pour cent » : du côté récrit seulement, les nombres en lettres,
les ordinaux, les mois, midi et minuit, « pour cent » et « degrés » sont ramenés
en chiffres avant la comparaison (``in_digits``). Un premier jet qui disait
« trois » n'impose rien : ses faits restent ses chiffres et ses liens.
"""

from __future__ import annotations

import re

#: un nombre : des chiffres, des blancs (« 1 234 », « 14 °C »), une unité ; un point, une virgule ou deux-points
#: seulement entre deux chiffres (« 1 234,50 », « 16:30 ») — « 1999, 2 fois » fait deux faits, pas un
_NUMBER = re.compile(r"\d(?:[\d\s%°]|[.,:](?=\d))*")
_URL = re.compile(r"https?://\S+")
_URL_TAIL = ".,;:!?)»\"'"
#: autour d'un nombre ramené en chiffres : un séparateur que ``_NUMBER`` ne traverse pas, pour que « 28 octobre 2026 »
#: donne trois faits et non un seul
_MARK = "·"
_WORD = re.compile(r"[^\W\d_]+")
_JOIN = re.compile(r"[\s\-]+")
_PERCENT = re.compile(r"\bpour[\s\-]?cents?\b|\bpourcents?\b", re.IGNORECASE)
_DEGREES = re.compile(r"\bdegr[ée]s?\b", re.IGNORECASE)
_UNIT_GLUE = re.compile(rf"{_MARK}(\d+){_MARK}[   ]*([%°])")

_UNITS = {
    "zéro": 0, "zero": 0, "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7,
    "huit": 8, "neuf": 9, "dix": 10, "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16,
    "vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60,
}
_ORDINALS = {
    "premier": 1, "première": 1, "premiere": 1, "unième": 1, "second": 2, "seconde": 2, "deuxième": 2,
    "troisième": 3, "quatrième": 4, "cinquième": 5, "sixième": 6, "septième": 7, "huitième": 8, "neuvième": 9,
    "dixième": 10, "onzième": 11, "douzième": 12, "treizième": 13, "quatorzième": 14, "quinzième": 15,
    "seizième": 16, "vingtième": 20, "trentième": 30, "quarantième": 40, "cinquantième": 50, "soixantième": 60,
    "centième": 100, "millième": 1000,
}
_SCALES = {"cent": 100, "cents": 100, "mille": 1000, "million": 1_000_000, "millions": 1_000_000,
           "milliard": 1_000_000_000, "milliards": 1_000_000_000}
_MONTHS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
           "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12}
_HOURS = {"midi": 12, "minuit": 0}


def facts_of(text: str, *, spelled: bool = False) -> frozenset[str]:
    """Les faits d'un texte, normalisés : ses nombres sans blancs ni ponctuation finale (« 14 °C » → « 14°C »,
    « 1 234,50 » → « 1234,50 »), ses liens sans la ponctuation qui les suit. ``spelled`` : ses nombres en lettres
    comptent aussi (le côté récrit)."""
    if spelled:
        text = in_digits(text)
    numbers = {n for raw in _NUMBER.findall(text) if (n := re.sub(r"\s", "", raw).rstrip(".,:"))}
    urls = {u.rstrip(_URL_TAIL) for u in _URL.findall(text)}
    return frozenset(numbers | urls)


def keeps_facts(draft: str, text: str) -> bool:
    """Une récriture garde les faits du premier jet : chacun de ses nombres et de ses liens s'y retrouve, en chiffres
    ou en lettres. Sinon (« 14 °C à Montaigu, averses à 16 h » devenu « il fera moche cet aprèm », une URL altérée),
    le premier jet part."""
    return facts_of(draft) <= facts_of(text, spelled=True)


def in_digits(text: str) -> str:
    """Le texte, ses nombres en lettres ramenés en chiffres entre deux marques (« à ·16· heures », « le ·28· ·10· »),
    « pour cent » en « % » et « degrés » en « ° » collés au nombre (« ·80%· »). Un mot qui n'est pas un nombre
    (« trois ou quatre » : « ou ») clôt le nombre ; « et » le continue (« vingt et un ») ; un ordinal le finit."""
    text = _PERCENT.sub("%", text)
    text = _DEGREES.sub("°", text)
    return _UNIT_GLUE.sub(rf"{_MARK}\1\2{_MARK}", _spelled(text))


def _is_number_word(word: str) -> bool:
    return word in _UNITS or word in _ORDINALS or word in _SCALES


def _spelled(text: str) -> str:
    tokens = [(m.start(), m.end(), m.group(0).lower()) for m in _WORD.finditer(text)]
    out: list[str] = []
    last = 0
    i = 0
    while i < len(tokens):
        start, end, word = tokens[i]
        if word in _MONTHS or word in _HOURS:
            out += [text[last:start], f"{_MARK}{_MONTHS.get(word, _HOURS.get(word))}{_MARK}"]
            last = end
            i += 1
            continue
        if not _is_number_word(word):
            i += 1
            continue
        words = [word]
        j = i + 1
        stop = end
        while j < len(tokens) and word not in _ORDINALS:
            s, e, w = tokens[j]
            if not _JOIN.fullmatch(text[stop:s]):
                break
            if w == "et":
                after = tokens[j + 1] if j + 1 < len(tokens) else None
                if after is None or not _is_number_word(after[2]) or not _JOIN.fullmatch(text[e:after[0]]):
                    break
                j += 1
                stop = e
                continue
            if not _is_number_word(w):
                break
            words.append(w)
            word, stop = w, e
            j += 1
        out += [text[last:start], f"{_MARK}{_value(words)}{_MARK}"]
        last = stop
        i = j
    out.append(text[last:])
    return "".join(out)


def _value(words: list[str]) -> int:
    """La valeur d'une suite de mots-nombres : « quatre-vingt-dix-neuf » → 99, « deux mille vingt-six » → 2026,
    « vingt-troisième » → 23."""
    total = 0
    current = 0
    for w in words:
        if w in _UNITS:
            n = _UNITS[w]
            # « quatre-vingts » multiplie : 4 puis 20 font 80 (et « neuf cent quatre-vingt-dix-neuf », 999)
            current = current - 4 + 80 if n == 20 and current % 100 == 4 else current + n
        elif w in _ORDINALS:
            current += _ORDINALS[w]
        elif _SCALES[w] == 100:
            current = (current or 1) * 100
        else:
            total += (current or 1) * _SCALES[w]
            current = 0
    return total + current
