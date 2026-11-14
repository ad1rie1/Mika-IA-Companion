"""La balise déclarée, et le texte prêt à livrer.

Ce que le modèle écrit passe ici avant d'être livré. ``parse_tag`` lit ce qu'elle a déclaré ressentir (la balise
``[EMOTION:…]`` et ses variantes réelles) et rend le texte prêt à livrer : la prosodie dans la grammaire du frontend,
les didascalies, les gestes et les jetons parasites retirés, le préfixe d'un locuteur, les guillemets englobants et le
raisonnement ôtés, la ponctuation recollée. ``strip_prosody`` rend le texte sans voix, pour le fil relu par le modèle,
la mémoire et les messages écrits.

Les émotions, ce qu'elle déclare (``Declared``) et l'intensité d'une balise (``tag_intensity``) sont dans
``vocab.affect`` : ce module les lit, et ``vocab.affect`` n'importe rien d'ici.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mika.vocab.affect import Declared, emotion_key, emotion_named, facets, tag_intensity

_VALUE = r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<pct>%)?"
_MD = r"[*_`~]*"
#: ``[EMOTION:nom:intensité]`` et ses variantes réelles : crochets doublés,
#: parenthèses, accolades, ``=`` ou ``,`` comme séparateurs, ``60%``, échelles
#: 0–10 et 0–100, point final parasite, balise non fermée en fin de ligne,
#: débris de markdown autour (``**[EMOTION:…]**``).
TAG = re.compile(
    r"(?P<pre>" + _MD + r")(?:\[\[|\(\(|\{\{|[\[({])\s*[ÉE]MOTIONS?\s*[:=]\s*"
    r"(?P<name>[^\W\d_][\w'’ \-]*?)\s*(?:[:,=/|;]\s*" + _VALUE + r")?[\s.]*"
    r"(?:\]\]|\)\)|\}\}|[\])}]|(?=\n|$))(?P<post>" + _MD + r")",
    re.IGNORECASE)
#: La forme abrégée : ``[playful:0.8]``, ``[SAD]``, ``[triste]``. Jamais un
#: lien markdown (``[curious](https://…)``).
SHORT_TAG = re.compile(
    r"(?P<pre>" + _MD + r")\[\s*(?P<name>[^\W\d_][\w'’\- ]{0,30}?)\s*(?::\s*" + _VALUE + r")?\s*\](?!\()"
    r"(?P<post>" + _MD + r")")
#: La forme en toutes lettres, en toute fin de texte : ``Émotion : happy (0.6)``.
TEXT_TAG = re.compile(
    r"(?P<pre>" + _MD + r")\b[ÉE]motion\s*:\s*(?P<name>[^\W\d_][\w'’\-]*(?: [^\W\d_][\w'’\-]*)?)\s*"
    r"(?:\(\s*" + _VALUE + r"\s*\))?(?P<post>" + _MD + r")[\s.]*$",
    re.IGNORECASE)
#: La balise à facettes (ADR 0093) : ``[EMOTION: sad 0.6, anxious 0.3]`` — tout ce que la balise contient, rangé par
#: ``facets`` ; la forme d'une seule facette (``[EMOTION:sad:0.6]``) y passe aussi.
FACETS_TAG = re.compile(
    r"(?P<pre>" + _MD + r")(?:\[\[|\(\(|\{\{|[\[({])\s*[ÉE]MOTIONS?\s*[:=]\s*(?P<body>[^\]\)}\n]{1,160}?)\s*"
    r"(?:\]\]|\)\)|\}\}|[\])}]|(?=\n|$))(?P<post>" + _MD + r")",
    re.IGNORECASE)
#: Ce qui reste d'une balise mal formée (``[EMOTION ?]``) : jamais livré.
TAG_DEBRIS = re.compile(r"\[\s*[ÉE]MOTIONS?\b[^\]\n]*\]", re.IGNORECASE)
#: Les jetons prosodiques, dans la grammaire exacte du frontend : pour la voix
#: seulement (le frontend les cale sur l'audio). Partout ailleurs — fil relu
#: par le modèle, mémoire, messages écrits — ce sont des didascalies parasites.
PROSODY = re.compile(r"\[(?:SIGH|LAUGH|BREATH|PAUSE:\d+)\]")
#: Le silence : un autre étage le reconnaît ; on ne l'abîme jamais.
SILENCE_TOKEN = "[SILENCE]"
_SILENCE = re.compile(_MD.replace("P<", "") + r"\[\s*silence\s*\]" + _MD, re.IGNORECASE)
_BRACKET = re.compile(r"\[\s*([^\[\]\n]{1,40}?)\s*\](?!\()")
_SHOUTED = re.compile(r"[^\W\d_a-zß-ÿ][^\Wa-zß-ÿ]*(?:[ _:.,'’!\-]+[^\Wa-zß-ÿ]+)*[.!]?")
_PAUSE = re.compile(r"pause\s*(?:[:= ]\s*(\d+(?:[.,]\d+)?)\s*(ms|s|sec|secs|secondes?|seconds?)?)?", re.IGNORECASE)
_THINKING = re.compile(r"<\s*(thinking|think|reasoning)\b[^>]*>.*?<\s*/\s*\1\s*>", re.IGNORECASE | re.DOTALL)
_THINKING_END = re.compile(r"^.*?<\s*/\s*(?:thinking|think|reasoning)\s*>", re.IGNORECASE | re.DOTALL)
#: un libellé d'orateur recopié en tête de réponse (« Assistant : », « **Léa** : ») — son nom vient de sa persona
_SPEAKER = r"^\s*(?:\*\*|__)?(?:{names})(?:\*\*|__)?\s*[:：]\s*"
_ASSISTANT = "Assistant"


def _speaker(name: str) -> re.Pattern[str]:
    """Le libellé à retirer : « Assistant », et son nom à elle quand on le connaît (en entier, ou son prénom)."""
    names = [_ASSISTANT, *dict.fromkeys(n for n in (" ".join(name.split()), *name.split()[:1]) if n)]
    return re.compile(_SPEAKER.format(names="|".join(re.escape(n) for n in names)), re.IGNORECASE)


_STARRED = re.compile(r"(?<![*\w])(\*{1,2}|_)(?!\s)([^*_\n]{1,60}?)(?<!\s)\1(?![*\w])")
_PARENS = re.compile(r"\(\s*([^()\n]{1,40}?)\s*\)")
_QUOTES = (("«", "»"), ("“", "”"), ('"', '"'))

#: Les didascalies qui ont une voix : un rire, un soupir, une respiration.
_VOICED = {
    "[LAUGH]": ("rit", "rire", "rires", "ris", "rigole", "rigolant", "pouffe", "glousse", "ricane", "petit_rire",
                "eclate_de_rire", "eclat_de_rire", "laugh", "laughs", "laughing", "laughter", "giggle", "giggles",
                "giggling", "chuckle", "chuckles", "chuckling"),
    "[SIGH]": ("soupir", "soupirs", "soupire", "soupirant", "petit_soupir", "long_soupir", "grand_soupir", "sigh",
               "sighs", "sighing"),
    "[BREATH]": ("breath", "breaths", "breathe", "breathes", "breathing", "inhale", "inhales", "exhale", "exhales",
                 "inspire", "respire", "souffle", "respiration", "inspiration", "grande_inspiration",
                 "prend_une_inspiration", "prend_une_grande_inspiration"),
}
_VOICE_OF = {word: token for token, words in _VOICED.items() for word in words}
#: Les autres gestes de théâtre : retirés (le visage et le corps les jouent déjà).
_GESTURES = (
    "sourit", "sourire", "souriante", "souriant", "smile", "smiles", "smiling", "grin", "grins", "grinning",
    "rougit", "rougissant", "rougissante", "blush", "blushes", "blushing", "hausse_les_epaules", "shrug", "shrugs",
    "clin_d_oeil", "fait_un_clin_d_oeil", "wink", "winks", "hoche_la_tete", "nod", "nods", "secoue_la_tete",
    "tousse", "toussote", "baille", "s_etire", "se_gratte_la_tete", "penche_la_tete", "hesite", "reflechit",
    "fronce_les_sourcils", "grimace", "tire_la_langue", "croise_les_bras", "leve_les_yeux_au_ciel", "murmure",
    "chuchote", "whispers", "tape_du_pied", "applaudit", "se_mord_la_levre", "regarde_ailleurs", "cligne_des_yeux",
    "fait_la_moue", "boude", "pense", "thinks", "sighs_softly", "hugs", "calin", "fait_un_calin",
)
_GESTURE = frozenset(_GESTURES)
#: Ce qui peut suivre un geste sans changer sa nature (« rit doucement »).
_MANNER = frozenset(("doucement", "nerveusement", "timidement", "tristement", "malicieusement", "legerement",
                     "un_peu", "fort", "aux_eclats", "en_coin", "gene", "genee", "betement", "tendrement", "softly",
                     "nervously", "gently", "quietly", "a_bit", "encore", "franchement", "jaune"))


@dataclass(frozen=True, slots=True)
class Tag:
    """Le résultat de l'analyse : le texte prêt à livrer, ce qui a été déclaré
    (``None`` : rien d'utilisable), et le nom inconnu éventuel."""

    text: str
    declared: Declared | None
    unknown: str | None = None


def _drop_thinking(text: str) -> str:
    text = _THINKING.sub("", text)
    return _THINKING_END.sub("", text)


def _found(m: re.Match[str]) -> tuple[int, int, str, str | None, bool]:
    return m.start(), m.end(), m.group("name").strip(), m.group("value"), bool(m.group("pct"))


def _is_cue(text: str, m: re.Match[str]) -> bool:
    """Une forme abrégée est une balise si elle a une intensité, si elle est
    en tout début ou en toute fin de texte, ou si elle est écrite en
    minuscules ou en capitales — « J'ai lancé [Curious] le jeu » est un titre."""
    name = m.group("name").strip()
    if emotion_named(name) is None or _voice_token(name) is not None or _is_silence_word(name):
        return False
    if m.group("value") or name.islower() or name.isupper():
        return True
    before, after = text[:m.start()].strip(), text[m.end():]
    return not before or not re.sub(r"[\s.!?…]|\[[^\]\n]*\]", "", after)


def _is_silence_word(inner: str) -> bool:
    return emotion_key(inner) == "silence"


def _voice_token(inner: str) -> str | None:
    """Un jeton de voix dans la grammaire exacte du frontend, ou ``None``."""
    m = _PAUSE.fullmatch(inner.strip())
    if m is not None:
        if m.group(1) is None:
            return "[PAUSE:500]"
        value = float(m.group(1).replace(",", "."))
        unit = (m.group(2) or "").lower()
        ms = value * 1000.0 if unit.startswith("s") or (not unit and value < 10) else value
        return f"[PAUSE:{max(100, min(5000, round(ms)))}]"
    head = emotion_key(inner.split(":", 1)[0])
    return _VOICE_OF.get(head)


def _stage(inner: str, *, narrow: bool) -> str | None:
    """Une didascalie (« rit doucement », « sourit ») : son jeton de voix, ou
    ``""`` (retirée) ; ``None`` si ce n'en est pas une. ``narrow`` : entre
    parenthèses, on n'ôte que les gestes sûrs, suivis au plus d'une manière."""
    words = emotion_key(inner).split("_")
    if not words or not words[0]:
        return None
    for n in range(min(len(words), 6), 0, -1):
        head = "_".join(words[:n])
        rest = words[n:]
        if head not in _VOICE_OF and head not in _GESTURE:
            continue
        tail = "_".join(rest)
        manner = not rest or tail in _MANNER or (len(rest) == 1 and rest[0].endswith("ment"))
        if narrow and not manner:
            return None
        if not narrow and not manner and len(rest) > 3:
            return None
        return _VOICE_OF.get(head, "")
    return None


def _voice(text: str) -> str:
    """Les jetons entre crochets : la prosodie normalisée, le silence intact,
    les gestes et tout autre jeton en capitales retirés."""

    def sub(m: re.Match[str]) -> str:
        inner = m.group(1)
        if _is_silence_word(inner):
            return SILENCE_TOKEN
        token = _voice_token(inner)
        if token is not None:
            return token
        staged = _stage(inner, narrow=False)
        if staged is not None:
            return staged
        if _SHOUTED.fullmatch(inner.strip()) and sum(ch.isalpha() for ch in inner) >= 2:
            return ""
        return m.group(0)

    text = _SILENCE.sub(SILENCE_TOKEN, text)
    return _BRACKET.sub(sub, TAG_DEBRIS.sub("", text))


def _gestures(text: str) -> str:
    """Les didascalies hors crochets : ``*rit*`` (une voix), ``(sourit)``
    (retirée) ; l'emphase (``*vraiment*``) et les vraies parenthèses restent."""

    def starred(m: re.Match[str]) -> str:
        staged = _stage(m.group(2), narrow=False)
        return m.group(0) if staged is None else staged

    def parens(m: re.Match[str]) -> str:
        staged = _stage(m.group(1), narrow=True)
        return m.group(0) if staged is None else staged

    return _PARENS.sub(parens, _STARRED.sub(starred, text))


def _unquote(text: str) -> str:
    for opening, closing in _QUOTES:
        if len(text) >= 2 and text.startswith(opening) and text.endswith(closing):
            inner = text[len(opening):-len(closing)]
            if opening not in inner and closing not in inner:
                return inner.strip()
    return text


def _tidy(text: str) -> str:
    text = re.sub(r"(?<=\S)[ \t]{2,}", " ", text)
    text = re.sub(r"(?<=\w)[ \t]+(?=[,.](?:\s|$))", "", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n[ \t]+(?=\S)", lambda m: "\n" + m.group(0)[1:] if m.group(0)[1:].startswith("    ") else "\n",
                  text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _cut(text: str, spans: list[tuple[int, int]]) -> str:
    out, cursor = [], 0
    for start, end in sorted(spans):
        if start < cursor:
            continue
        out.append(text[cursor:start])
        out.append(" ")
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


#: une seule émotion dans une balise, avec ou sans intensité, quel qu'en soit le séparateur (« happy », « sad:0.6 »,
#: « surprised, 0.6 », « excited 8 ») : la forme d'avant les facettes, lue comme avant
_ONE = re.compile(r"^\s*(?P<name>[^\W\d_][\w'’ \-]*?)\s*(?:[:,=/|;\s]\s*" + _VALUE + r")?\s*\.?\s*$")


def _declared_in(body: str) -> Declared | None:
    """Ce que dit le contenu d'une balise d'émotion : une émotion (la forme d'avant, son intensité par défaut
    ``DEFAULT_TAG_INTENSITY``), ses facettes, ou le calme (``neutral``, qui n'est pas une facette mais reste une
    déclaration)."""
    one = _ONE.match(body)
    if one is not None and emotion_named(one["name"]) is not None:
        return Declared(emotion_named(one["name"]), tag_intensity(one["value"], bool(one["pct"])))  # type: ignore[arg-type]
    return Declared.of(facets(body))


def parse_tag(text: str, speaker: str = "") -> Tag:
    """Ce qu'elle a déclaré, et le texte prêt à livrer : prosodie dans la
    grammaire du frontend, didascalies et jetons parasites retirés, préfixe
    « Assistant : » ou « <son nom> : » (``speaker``, celui de sa persona),
    guillemets englobants et raisonnement ôtés, ponctuation recollée.

    Pas de balise → ``declared=None`` (aucune impulsion) ; plusieurs balises →
    la **dernière** (c'est ce qu'elle ressent en finissant d'écrire) ; une balise
    à facettes (« sad 0.6, anxious 0.3 ») les garde toutes, rangées (ADR 0093) ;
    un nom hors des 29 (et d'aucune table de synonymes) → ``declared=None`` et
    ``unknown`` renseigné. ``neutral`` reste une déclaration : c'est l'affect
    qui décide qu'elle ne fait rien bouger."""
    raw = _drop_thinking(text or "")
    felt = [(m.start(), m.end(), got) for m in FACETS_TAG.finditer(raw) if (got := _declared_in(m.group("body")))]
    found = [f for f in (_found(m) for m in TAG.finditer(raw))
             if not any(s < f[1] and f[0] < e for s, e, _ in felt)]
    taken = [(s, e) for s, e, *_ in found] + [(s, e) for s, e, _ in felt]
    for m in SHORT_TAG.finditer(raw):
        if _is_cue(raw, m) and not any(s < m.end() and m.start() < e for s, e in taken):
            found.append(_found(m))
    tail = TEXT_TAG.search(raw)
    if tail is not None and emotion_named(tail.group("name")) is not None and \
            not any(s < tail.end() and tail.start() < e for s, e in taken):
        found.append(_found(tail))
    found.sort()
    clean = _cut(raw, sorted([(s, e) for s, e, *_ in found] + [(s, e) for s, e, _ in felt]))
    clean = _gestures(_voice(clean))
    clean = _unquote(_tidy(_speaker(speaker).sub("", _tidy(clean))))
    declared: Declared | None = None
    unknown: str | None = None
    last_felt = max(felt, default=None, key=lambda f: f[0])
    for start, _e, name, value, pct in reversed(found):
        if last_felt is not None and last_felt[0] > start:
            break  # la balise à facettes est la dernière
        emotion = emotion_named(name)
        if emotion is not None:
            declared = Declared(emotion, tag_intensity(value, pct))
            break
    if declared is None and last_felt is not None:
        declared = last_felt[2]
    if declared is None and found:
        unknown = found[-1][2].lower()
    elif declared is None:
        vague = [m.group("body") for m in FACETS_TAG.finditer(raw) if _declared_in(m.group("body")) is None]
        words = re.findall(r"[^\W\d_][\w'’\-]*", vague[-1]) if vague else []
        unknown = words[0].lower() if words else None
    return Tag(clean, declared, unknown)


def strip_prosody(text: str) -> str:
    """Le texte sans voix : pour le fil relu par le modèle, la mémoire, un
    message écrit. Les variantes sont reconnues (un texte ancien n'a pas été
    normalisé) ; le silence reste."""
    if not text:
        return text
    return _tidy(PROSODY.sub("", _voice(text)))
