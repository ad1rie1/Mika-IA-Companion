"""Lire le ton d'un message dans sa forme : des mots, la ponctuation, les
majuscules, les émojis. Pur, sans modèle (il passe sur chaque message).

C'est un indice, pas un verdict : la plupart des messages n'en disent rien
(valence 0), et c'est à l'aune de ce qu'une personne écrit d'habitude que ce
qu'on y lit prend un sens (voir ``others``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mika.vocab.words import fold

#: (mots repliés, valence, agitation) : des mots qui pèsent…
_HEAVY = ("triste", "marre", "fatigue", "fatiguee", "epuise", "epuisee", "deprime", "deprimee", "pleure",
          "pleurer", "seul", "seule", "angoisse", "angoissee", "peur", "mal", "nul", "nulle", "horrible",
          "galere", "ras le bol", "craque", "vide", "decu", "decue", "perdu", "perdue")
#: … des mots fâchés, des insultes…
_ANGRY = ("enerve", "enervee", "furieux", "furieuse", "colere", "saoule", "gonfle", "chiant", "putain", "merde",
          "insupportable", "degoute", "degoutee", "ta gueule", "idiot", "idiote", "stupide", "debile", "connard",
          "connasse", "abruti", "abrutie", "cretin", "cretine", "deteste")
#: … des mots qui ont de l'entrain
_BRIGHT = ("trop bien", "genial", "geniale", "content", "contente", "hate", "youpi", "super", "trop cool", "heureux",
           "heureuse", "incroyable", "adore", "mdr", "haha", "lol", "merci", "cool", "top", "parfait")
#: ce qui, juste avant, retourne le sens (« pas mal », « pas contente »)
_NEGATIONS = frozenset({"pas", "plus", "jamais", "guere", "aucunement"})

_WARM_EMOJI = frozenset("😀😃😄😁😆😊🙂😍🥰😘❤💕💖✨🎉👍😂🤣")
_SAD_EMOJI = frozenset("😢😭😞😔😟🙁☹💔😩😫")
_ANGRY_EMOJI = frozenset("😠😡🤬👿")

_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class Tone:
    valence: float  # [-1, 1]
    arousal: float  # [0, 1]
    cues: tuple[str, ...]


def _hits(low: str, words: tuple[str, ...]) -> tuple[int, int]:
    """(occurrences affirmées, occurrences niées) des mots dans le texte replié."""
    plain = negated = 0
    for w in words:
        for m in re.finditer(rf"\b{re.escape(w)}\b", low):
            before = _WORD.findall(low[: m.start()])[-2:]
            if _NEGATIONS & set(before):
                negated += 1
            else:
                plain += 1
    return plain, negated


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def measure(text: str) -> Tone:
    """Le ton d'un message : valence, agitation, et les indices qui les disent."""
    cues: list[str] = []
    stripped = text.strip()
    if not stripped:
        return Tone(0.0, 0.3, ())
    valence, arousal = 0.0, 0.3
    letters = [ch for ch in stripped if ch.isalpha()]
    if len(letters) >= 8 and sum(ch.isupper() for ch in letters) / len(letters) > 0.7:
        cues.append("écrit en majuscules : il ou elle s'emballe, ou crie")
        arousal += 0.4
    if "!!" in stripped:
        cues.append("beaucoup de points d'exclamation : de l'enthousiasme, ou de l'agacement")
        arousal += 0.25
    elif "!" in stripped:
        arousal += 0.1
    if stripped.count("...") + stripped.count("…") >= 2:
        cues.append("des points de suspension : une hésitation, ou quelque chose de lourd")
        valence -= 0.1
        arousal -= 0.05
    words = stripped.split()
    if len(words) <= 2 and not stripped.endswith("?"):
        cues.append("un message très court")
        arousal -= 0.05
    low = fold(stripped)
    heavy, heavy_negated = _hits(low, _HEAVY)
    angry, angry_negated = _hits(low, _ANGRY)
    bright, bright_negated = _hits(low, _BRIGHT)
    if heavy:
        cues.append("des mots lourds")
        valence -= 0.5 * min(2, heavy)
    if angry:
        cues.append("des mots fâchés")
        valence -= 0.45 * min(2, angry)
        arousal += 0.35
    if bright_negated:
        cues.append("de l'entrain qui manque (« pas… »)")
        valence -= 0.3
    if bright and not (heavy or angry):
        cues.append("de l'entrain")
        valence += 0.45 * min(2, bright)
        arousal += 0.1
    if heavy_negated or angry_negated:
        valence += 0.15  # « pas mal », « pas fâchée » : plutôt bien
    chars = set(stripped)
    if chars & _SAD_EMOJI:
        cues.append("un émoji triste")
        valence -= 0.4
    elif chars & _ANGRY_EMOJI:
        cues.append("un émoji fâché")
        valence -= 0.45
        arousal += 0.3
    elif chars & _WARM_EMOJI:
        cues.append("un émoji joyeux")
        valence += 0.35
    return Tone(round(_clamp(valence, -1.0, 1.0), 3), round(_clamp(arousal, 0.0, 1.0), 3), tuple(cues))


def read_tone(text: str) -> list[str]:
    """Les indices lus dans la forme d'un message. Vide le plus souvent."""
    return list(measure(text).cues)
