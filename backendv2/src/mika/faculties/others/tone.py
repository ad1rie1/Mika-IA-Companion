"""Lire le ton d'un message dans sa forme : des mots, la ponctuation, les
majuscules, les émojis. Pur, sans modèle (il passe sur chaque message).

C'est un indice, pas un verdict : la plupart des messages n'en disent rien
(valence 0), et c'est à l'aune de ce qu'une personne écrit d'habitude que ce
qu'on y lit prend un sens (voir ``others``) — sauf un **événement grave** (un
deuil, une maladie, une rupture, une perte de travail, des mots de détresse) :
celui-là compte venant de n'importe qui.

Quelques pièges, nommés :

- « putain », « merde », « trop », « tellement » sont des **intensifs** :
  « putain c'est trop bien !! » est joyeux ;
- la fatigue au moment de dormir n'est pas lourde (« je suis fatiguée, bonne
  nuit ») ;
- l'émotion heureuse n'est pas lourde (« ce film m'a fait pleurer tellement il
  était beau », « mort de rire »).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mika.vocab.words import fold

#: (mots repliés, valence, agitation) : des mots qui pèsent…
_HEAVY = ("triste", "marre", "deprime", "deprimee", "pleure", "pleurer", "pleurs", "seul", "seule", "angoisse",
          "angoissee", "peur", "mal", "nul", "nulle", "horrible", "galere", "ras le bol", "craque", "vide", "decu",
          "decue", "perdu", "perdue", "plus la force", "en peux plus", "inquiete", "inquiet")
#: … la fatigue (légère, et rien au moment d'aller dormir)…
_TIRED = ("fatigue", "fatiguee", "creve", "crevee", "epuise", "epuisee", "naze", "claque", "claquee")
#: … des mots fâchés, des insultes…
_ANGRY = ("enerve", "enervee", "furieux", "furieuse", "colere", "saoule", "gonfle", "chiant", "insupportable",
          "degoute", "degoutee", "ta gueule", "idiot", "idiote", "stupide", "debile", "connard", "connasse", "abruti",
          "abrutie", "cretin", "cretine", "deteste")
#: … des mots qui ont de l'entrain
_BRIGHT = ("trop bien", "genial", "geniale", "content", "contente", "hate", "youpi", "super", "trop cool", "heureux",
           "heureuse", "incroyable", "adore", "mdr", "haha", "lol", "merci", "cool", "top", "parfait", "beau", "belle",
           "magnifique", "emouvant", "touchant", "adorable", "va mieux", "vais mieux", "ca va bien", "soulage",
           "soulagee", "de joie", "de rire")
#: des intensifs : ils renforcent ce qui est dit, sans dire un sens à eux seuls (sauf un juron isolé)
_INTENSIFIERS = ("putain", "merde", "trop", "tellement", "grave", "carrement", "vraiment", "hyper")
_SWEARS = ("putain", "merde")
#: ce qui, juste avant, retourne le sens (« pas mal », « pas contente »)
_NEGATIONS = frozenset({"pas", "plus", "jamais", "guere", "aucunement"})
#: aller dormir : la fatigue y est normale
_BEDTIME = re.compile(r"\b(bonne nuit|bonne soiree|dodo|au lit|vais dormir|vais me coucher|vais me pieuter)\b")
#: l'émotion heureuse, qui n'a rien de lourd
_HAPPY_TEARS = re.compile(r"\b(morte?s? de rire|mourir de rire|meurs de rire|pleure[rs]? de (rire|joie)|"
                          r"larmes de joie|mdr|ptdr)\b")

#: Les proches dont la mort est un deuil (replié, sans accents) — pas une batterie, ni un projet
#: (« c'est mort pour ce soir », « mon téléphone est mort »).
_KIN = (r"(?:pere|mere|papa|maman|parents?|frere|soeur|grand[- ]?(?:pere|mere|parents?)|papi|papy|mamie|mamy|"
        r"oncle|tante|cousine?|fils|fille|enfant|bebe|mari|femme|epou(?:x|se)|copain|copine|compagne?|ami|amie|"
        r"meilleure? ami|neveu|niece|chat|chatte|chien|chienne|beau[- ]pere|belle[- ]mere)")
#: (motif sur le texte replié, valence, étiquette) : les événements graves, qui comptent venant de n'importe qui.
#: Pas les hyperboles de tous les jours : « mourir de chaud », « hâte d'en finir avec ce dossier », « ma mère
#: va me tuer », « le suicide de Werther », « un petit accident de café », « rupture de stock ».
_GRAVE = (
    (re.compile(r"\b(?:veux|voudrais|vais|envie de|prefererais)\s+(?:mourir|crever|disparaitre)\b(?!\s+d[e'])|"
                r"\b(?:veux|voudrais|vais|envie d'|besoin d')\s*en\s+finir\b(?!\s+avec)|"
                r"\b(?:me|je)\s+suicider\b|\bsuicidaire|\btentative de suicide\b|\bidees noires\b|"
                r"\bplus\s+envie\s+de\s+vivre\b|\b(?:veux|vais|envie de)\s+me\s+tuer\b"),
     -1.0, "des mots de détresse"),
    (re.compile(r"\b(?:decedee?s?|deces|enterrement|obseques|funerailles)\b|"
                rf"\b(?:mon|ma|mes|son|sa|ses|notre|nos)\s+{_KIN}\b[^.!?]{{0,30}}?"
                r"\b(?:est|sont|etait|vient|viennent)\s+(?:de\s+)?(?:mourir|morte?s?)\b|"
                r"\bmort\s+de\s+(?:mon|ma|mes|son|sa|ses|notre|nos)\b|"
                rf"\bperdu\s+(?:mon|ma|mes)\s+{_KIN}\b"),
     -0.9, "un deuil"),
    (re.compile(r"\b(?:cancer|tumeur|chimio|chimiotherapie|leucemie|hospitalisee?s?|avc|infarctus|fausse couche)\b|"
                r"\b(?:a l'hopital|aux urgences)\b|(?<!petit )\baccident\b(?!\s+de\s+(?:cafe|the|parcours))|"
                r"\bcrise cardiaque\b"),
     -0.85, "une maladie, un accident"),
    (re.compile(r"\b(?:fait|fais|faire|suis|ete|etre)\s+(?:virer?|viree)\b|\blicencie(?:e|s|es)?\b|"
                r"\blicenciement\b|\b(?:au|mise? au)\s+chomage\b|"
                r"\bperdu\s+(?:mon|ma)\s+(?:travail|boulot|job|emploi|taf)\b"),
     -0.75, "une perte de travail"),
    (re.compile(r"\brupture\b(?!\s+de\s+(?:stock|contrat|charge))|\bm'a\s+quittee?\b|\bnous\s+sommes\s+separes?\b|"
                r"\bon\s+s'est\s+separee?s?\b|\bdivorce\b|\blarguee?\b|\bon\s+se\s+separe\b"),
     -0.75, "une rupture"),
)

_WARM_EMOJI = frozenset("😀😃😄😁😆😊🙂😍🥰😘❤💕💖✨🎉👍😂🤣")
_SAD_EMOJI = frozenset("😢😭😞😔😟🙁☹💔😩😫")
_ANGRY_EMOJI = frozenset("😠😡🤬👿")

_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class Tone:
    valence: float  # [-1, 1]
    arousal: float  # [0, 1]
    cues: tuple[str, ...]
    #: un événement grave : il compte venant de n'importe qui, quel que soit son ton habituel
    grave: bool = False


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


def grave(low: str) -> tuple[float, str] | None:
    """Le plus grave des événements nommés dans le texte replié (valence, étiquette)."""
    found = [(v, label) for pattern, v, label in _GRAVE if pattern.search(low)]
    return min(found) if found else None


def measure(text: str) -> Tone:
    """Le ton d'un message : valence, agitation, et les indices qui les disent."""
    cues: list[str] = []
    stripped = text.strip()
    if not stripped:
        return Tone(0.0, 0.3, ())
    valence, arousal = 0.0, 0.3
    letters = [ch for ch in stripped if ch.isalpha()]
    if len(letters) >= 8 and sum(ch.isupper() for ch in letters) / len(letters) > 0.7:
        cues.append("écrit en majuscules : la personne s'emballe, ou crie")
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
    low = fold(stripped).replace("’", "'")
    happy_tears = bool(_HAPPY_TEARS.search(low))
    if happy_tears:
        low = _HAPPY_TEARS.sub(" rire ", low)  # « mort de rire » n'est ni un deuil ni des larmes
    serious = grave(low)
    heavy, heavy_negated = _hits(low, _HEAVY)
    tired, _ = _hits(low, _TIRED)
    angry, angry_negated = _hits(low, _ANGRY)
    bright, bright_negated = _hits(low, _BRIGHT)
    bright += int(happy_tears)
    swears, _ = _hits(low, _SWEARS)
    intense, _ = _hits(low, _INTENSIFIERS)
    if serious is not None:
        value, label = serious
        cues.append(f"un événement grave ({label})" if label != "des mots de détresse" else label)
        valence = min(valence, value)
        arousal += 0.2
    if heavy:
        # l'émotion heureuse qui accompagne (« pleurer tellement c'était beau ») allège le lourd
        cues.append("des mots lourds" if not bright else "des mots lourds, mais de l'émotion heureuse avec")
        valence -= (0.5 if not bright else 0.3) * min(2, heavy)
    if tired and not _BEDTIME.search(low) and serious is None:
        cues.append("de la fatigue")
        valence -= 0.25
    if angry:
        cues.append("des mots fâchés")
        valence -= 0.45 * min(2, angry)
        arousal += 0.35
    if bright_negated:
        cues.append("de l'entrain qui manque (« pas… »)")
        valence -= 0.3
    if bright and not angry and serious is None:
        cues.append("de l'entrain")
        valence += (0.45 if not heavy else 0.3) * min(2, bright)
        arousal += 0.1
    if heavy_negated or angry_negated:
        valence += 0.15  # « pas mal », « pas fâchée » : plutôt bien
    if swears and abs(valence) < 0.05 and serious is None:
        cues.append("un juron")  # seul, il dit un agacement ; avec autre chose, il l'intensifie
        valence -= 0.2
        arousal += 0.2
    elif intense and abs(valence) >= 0.05 and serious is None:
        valence *= 1.25  # « putain c'est trop bien », « tellement nul »
        arousal += 0.1
    chars = set(stripped)
    if chars & _SAD_EMOJI and not happy_tears:
        cues.append("un émoji triste")
        valence -= 0.4
    elif chars & _ANGRY_EMOJI:
        cues.append("un émoji fâché")
        valence -= 0.45
        arousal += 0.3
    elif chars & _WARM_EMOJI:
        cues.append("un émoji joyeux")
        valence += 0.35
    if serious is not None:
        valence = min(valence, serious[0] + 0.1)  # rien n'en fait un message léger
    return Tone(round(_clamp(valence, -1.0, 1.0), 3), round(_clamp(arousal, 0.0, 1.0), 3), tuple(cues),
                grave=serious is not None)


def read_tone(text: str) -> list[str]:
    """Les indices lus dans la forme d'un message. Vide le plus souvent."""
    return list(measure(text).cues)
