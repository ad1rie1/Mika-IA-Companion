"""Être convaincue : ce que dit quelqu'un recoupe-t-il ce que seule la
personne qu'il prétend être pourrait savoir ?

Ne comptent que des souvenirs et croyances :

- sur la personne revendiquée, au moins **personnels** (l'anodin, tout le
  monde peut le savoir) ;
- appris **d'elle, en privé** : chaque message source vient d'une de ses
  adresses, hors d'un salon (un fait cité en groupe ne prouve rien) ;
- que Mika **n'a répété à personne d'autre** (sinon d'autres le savent) ;
- pas déjà utilisés comme preuve pour cette revendication.

Le recoupement est lexical, et prudent — un faux négatif coûte un lien
d'opérateur, un faux positif coûterait une confidence :

- les mots de tout le monde ne prouvent rien : « journée de travail,
  épuisée, j'ai pleuré, mal dormi, stress, ma mère, l'argent » se disent de
  n'importe qui. Ce lexique courant est retiré, ainsi que les noms ;
- un radical pèse d'autant plus qu'il est rare dans sa mémoire (``1/df`` : un
  mot qu'on retrouve dans dix souvenirs ne désigne personne) ;
- le message doit reprendre une part du souvenir (au moins trois dixièmes de
  ce qu'il dit), pas un mot au détour d'une liste ; un message fourre-tout ne
  prouve rien ;
- un **détail rare** partagé (un nom propre, un nombre, une date) vaut plus
  qu'un mot commun — et il en faut un, sur l'une des deux preuves (``reading``).

Fonctions pures ; les lectures du magasin sont faites par l'appelant.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from mika.faculties.identity.detection import NOT_NAMES
from mika.vocab.words import CHATTER, STOPWORDS, WORD, fold, stems

#: Sans détail rare : trois radicaux recoupés au moins…
MIN_OVERLAP = 3
#: … avec un détail rare (un nom propre, un nombre, une date) partagé : deux.
MIN_OVERLAP_RARE = 2
#: La part du souvenir que le message reprend, au moins.
MIN_RATE = 0.3
#: Le poids des radicaux recoupés (chacun vaut ``1 / nombre de souvenirs où il figure``).
MIN_WEIGHT = 2.0
MIN_WEIGHT_RARE = 1.5
#: Un message qui aligne plus de radicaux que ça ne prouve rien (une liste jetée au hasard).
MAX_MESSAGE_STEMS = 30
#: Les souvenirs relus au plus pour mesurer la rareté d'un mot.
CORPUS_MAX = 2000

#: Ce que tout le monde dit de sa journée, de son humeur, des siens : ça ne
#: désigne personne (replié, sans accents ; réduit en radicaux plus bas).
COMMON_WORDS = frozenset("""
travail travaille travailler travaux boulot boulots taf taff job bureau collegue collegues chef patron patronne
reunion reunions client clients projet projets journee journees soiree soirees matin matinee midi soir soirs nuit
nuits semaine semaines weekend week heure heures minute minutes moment moments temps annee annees aujourd
fatigue fatiguee fatigues fatiguees epuise epuisee epuises epuisant epuisante creve crevee crevant stress stresse
stressee stressant stressante angoisse angoissee anxieux anxieuse inquiet inquiete inquiete inquietude triste
tristesse heureux heureuse content contente enerve enervee enervant colere peur pleure pleurer pleure pleuree
pleurs larmes pleurait rire rigole rigoler dormi dormir dors dort dormais sommeil reveil reveille reveillee lever
leve couche coucher manger mange mangé repas diner dejeuner petit cafe maison appart appartement famille mere pere
maman papa parents parent frere soeur freres soeurs enfant enfants fils fille filles mari femme copain copine
copains copines ami amie amis amies pote potes argent sous payer paye salaire achat achats courses malade maladie
mal tete ventre docteur medecin depuis encore souvent parfois beaucoup grosse gros grand grande petite nouveau
nouvelle nouveaux nouvelles compte telephone portable message messages ecrit ecrire ecris raconte raconter
raconte souvenir souvenirs aime aimer adore adorer deteste envie besoin penser pense pensee bien mieux pire super
genial geniale cool tellement bref enfin voila ouais merci bonjour bonsoir bisous chat chats chien chiens confie
confier confiee secret secrets personne gens monde vie chose choses passe passee apres avant pendant toute tous
encore quand meme vraiment plutot assez deux trois quatre cinq six sept huit neuf premier premiere derniere dire
parle parler parlais demande demander mois mieux galere marre vide nul nulle horrible difficile dur dure
""".split())
COMMON = frozenset(w[:6] for w in COMMON_WORDS if len(w) >= 4)

_MONTHS = frozenset("janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre".split())
_WEEKDAYS = frozenset("lundi mardi mercredi jeudi vendredi samedi dimanche".split())
_TOKEN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]*|\d+")
_DATE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?\b")


@dataclass(frozen=True, slots=True)
class Candidate:
    id: int
    text: str


@dataclass(frozen=True, slots=True)
class Hit:
    """Un souvenir recoupé : par quoi, et s'il l'est par un détail rare."""

    id: int
    overlap: frozenset[str]
    rare: tuple[str, ...]
    weight: float
    rate: float


def _banned(names: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for name in names:
        out |= stems(name, min_len=2)
    return out


def _name_words(names: Iterable[str]) -> set[str]:
    return {w for name in names for w in WORD.findall(fold(name or ""))}


def content_stems(text: str, *, names: Iterable[str] = ()) -> set[str]:
    """Les radicaux qui disent quelque chose de précis : sans le lexique courant ni les noms."""
    return stems(text) - COMMON - _banned(names)


def rare_details(text: str, *, names: Iterable[str] = ()) -> set[str]:
    """Les détails rares d'un souvenir, repliés : ses noms propres (une majuscule
    qui n'est pas un mot courant), ses nombres (deux chiffres au moins), ses
    dates (un mois, « 12/03 »). Un jour de la semaine n'en est pas un."""
    excluded = _name_words(names)
    out: set[str] = set()
    for m in _DATE.finditer(text):
        out.add(m.group(0))
    for token in _TOKEN.findall(text):
        if token.isdigit():
            if len(token) >= 2:
                out.add(token)
            continue
        raw = token.replace("’", "'").split("'")[-1]  # « l'Islande » : le nom est après l'élision
        word = fold(raw)
        if word in _MONTHS:
            out.add(word)
            continue
        if not raw[:1].isupper() or len(word) < 3 or word in excluded or word in _WEEKDAYS:
            continue
        if word in STOPWORDS or word in CHATTER or word in NOT_NAMES or word in COMMON_WORDS:
            continue
        out.add(word)
    return out


def _words(text: str) -> set[str]:
    folded = fold(text.replace("’", "'"))
    return set(WORD.findall(folded)) | {m.group(0) for m in _DATE.finditer(text)}


def rarity(corpus: Iterable[str]) -> Counter[str]:
    """Dans combien de souvenirs figure chaque radical (sa fréquence documentaire)."""
    df: Counter[str] = Counter()
    for text in corpus:
        df.update(stems(text))
    return df


def overlap(message: str, text: str, *, exclude: Iterable[str] = ()) -> set[str]:
    """Les radicaux communs, noms exclus — sans rien d'autre (mesure brute)."""
    return (stems(message) & stems(text)) - _banned(exclude)


def judge(message: str, cand: Candidate, *, names: Iterable[str] = (),
          df: Counter[str] | None = None) -> Hit | None:
    """Ce message recoupe-t-il ce souvenir ? Le verdict, ou rien."""
    names = tuple(names)
    said = content_stems(message, names=names)
    if not said or len(said) > MAX_MESSAGE_STEMS:
        return None
    known = content_stems(cand.text, names=names)
    if not known:
        return None
    common = said & known
    rare = tuple(sorted(rare_details(cand.text, names=names) & _words(message)))
    if len(common) < (MIN_OVERLAP_RARE if rare else MIN_OVERLAP):
        return None
    rate = len(common) / len(known)
    if rate < MIN_RATE:
        return None
    weight = sum(1.0 / max(1, (df or {}).get(s, 1)) for s in common)
    if weight < (MIN_WEIGHT_RARE if rare else MIN_WEIGHT):
        return None
    return Hit(cand.id, frozenset(common), rare, round(weight, 3), round(rate, 3))


def corroborating(message: str, candidates: Sequence[Candidate], *, names: Iterable[str] = (),
                  corpus: Iterable[str] | None = None) -> Hit | None:
    """Le souvenir le mieux recoupé, s'il l'est assez (un détail rare d'abord)."""
    names = tuple(names)
    df = rarity(corpus) if corpus is not None else rarity(c.text for c in candidates)
    best: Hit | None = None
    for cand in candidates:
        hit = judge(message, cand, names=names, df=df)
        if hit is None:
            continue
        if best is None or (bool(hit.rare), hit.weight, -hit.id) > (bool(best.rare), best.weight, -best.id):
            best = hit
    return best
