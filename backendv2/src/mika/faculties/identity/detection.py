"""Lire qui quelqu'un dit être, sans modèle : « moi c'est Thomas », « je ne
suis pas Julie ».

Tourne sur chaque message reçu : gratuit, pur, et **prudent**. Un faux
positif lui fait appeler un inconnu par le nom d'un ami ; dans le doute, rien.
« Je suis » est le piège : « je suis fatiguée », « je suis allée au ciné »,
« je suis développeur » ne sont pas des noms — après « je suis », seul un mot
écrit avec une majuscule, qui ne ressemble ni à un état ni à un participe,
compte comme un nom.

« Moi c'est » aussi : « moi c'est pizza ce soir, et toi ? » n'est pas une
présentation. Elle ne compte qu'en tête de phrase (ou après une salutation),
le nom fermant la proposition (« moi c'est Zoé », « moi c'est Zoé, et toi ? »).
Un nom commun, une ville, une nationalité ne sont jamais des prénoms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mika.vocab.people import fold

_CORE = r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,30}"
#: Un ou deux mots ; jamais suivi d'un chiffre (« Agent007 » n'est pas « Agent »).
_NAME = rf"{_CORE}(?:\s+{_CORE})?(?![A-Za-zÀ-ÖØ-öø-ÿ0-9])"
MAX_NAME = 40
#: Où une présentation peut commencer : en tête, après une ponctuation, une salutation ou « et ».
_OPENING = r"(?:^\s*|[.!?,;:…(]\s*|\b(?:salut|bonjour|bonsoir|coucou|hey|hello|yo|re|ok|bon|alors|et)\b[\s,!]*)"
#: Où elle finit : le nom ferme la proposition (ou « et toi ? », « enchantée »).
_CLOSING = r"(?=\s*(?:[.!?,;:…)]|$)|\s+(?:et\s+(?:toi|vous)|enchant[ée]e?s?)\b)"


@dataclass(frozen=True, slots=True)
class Detection:
    claim: str | None = None  # le nom que la personne se donne
    denial: str | None = None  # le nom que la personne refuse
    strong: bool = True  # tournure sans ambiguïté (« je m'appelle »)

    @property
    def empty(self) -> bool:
        return self.claim is None and self.denial is None


#: Tournures sans ambiguïté : la casse n'y compte pas (« moi c'est alice »).
_STRONG = (
    re.compile(rf"\bje\s+m['’]appelle\s+({_NAME})", re.I),
    re.compile(rf"\bje\s+me\s+nomme\s+({_NAME})", re.I),
    re.compile(rf"\bmon\s+(?:pr[ée]nom|nom)\s*,?\s+(?:c['’]est|est)\s+({_NAME})", re.I),
    re.compile(rf"{_OPENING}moi\s*,?\s*c['’]est\s+({_NAME}){_CLOSING}", re.I),
    re.compile(rf"(?:\bc['’]est\s+)?\b({_NAME})\s+(?:[àa]\s+l['’]appareil|au\s+clavier)", re.I),
    re.compile(rf"^\s*(?:salut|bonjour|bonsoir|coucou|hey|hello|yo)[\s,!]+c['’]est\s+({_NAME})", re.I),
    re.compile(rf"\bmy\s+name\s+is\s+({_NAME})", re.I),
)
#: « je suis X », « ici X », « i'm X » : seulement avec une majuscule.
_WEAK = (
    re.compile(rf"\b[Jj]e\s+suis\s+({_NAME})"),
    re.compile(rf"(?:^|[.!?]\s*)[Ii]ci\s+({_NAME})"),
    re.compile(rf"\b[Ii]\s*['’]?m\s+({_NAME})"),
)
_DENIALS = (
    re.compile(rf"\bje\s+(?:ne\s+)?suis\s+pas\s+({_NAME})", re.I),
    re.compile(rf"\bc['’]est\s+pas\s+(?:moi\s*,?\s*)?({_NAME})", re.I),
    re.compile(rf"\bce\s+n['’]est\s+pas\s+({_NAME})", re.I),
    re.compile(rf"\bje\s+m['’]appelle\s+pas\s+({_NAME})", re.I),
    re.compile(rf"\bi\s*['’]?m\s+not\s+({_NAME})", re.I),
)

#: Ce qui suit « je suis » sans être un nom (replié, sans accents).
NOT_NAMES = frozenset("""
fatigue fatiguee creve crevee content contente triste desole desolee sur sure certain certaine pret prete occupe
occupee malade vieux vieille jeune perdu perdue la ici parti partie rentre rentree libre dispo cool nul nulle bete
curieux curieuse heureux heureuse enerve enervee stresse stressee deborde debordee seul seule vivant vivante mort
morte en au aux un une le les des du de pas plus tres trop assez toujours jamais vraiment juste encore deja bien mal
mieux sorry tired happy sad here back good fine ok okay not a the so just really still your ton ta mon ma son sa leur
notre votre cette ce ces mais et ou donc or ni car puis ensuite avec sans pour chez dans sous vers depuis apres avant
pendant aussi comme quand si que qui quoi dont ainsi enfin bref alors meme and but then with from for when while
developpeur developpeuse etudiant etudiante prof professeur ingenieur ingenieure medecin infirmier infirmiere artiste
musicien musicienne dev admin humain humaine personne quelqu moi toi lui elle nous vous eux elles on je tu il
grave rien tout sympa drole marrant normal possible vrai faux bon bonne mauvais mauvaise bizarre genial super top
gentil gentille desolé francais francaise chez sure pareil pareille sincere serieux serieuse
c l j m n s t qu est etait sera
""".split()) | frozenset("""
pizza pizzas pates pate burger burgers sushi sushis frites salade soupe raclette fondue tacos kebab sandwich
crepes crepe gateau chocolat cafe the biere vin apero resto restaurant cantine dessert repas diner dejeuner
gouter petit ce cette demain soir matin midi aujourd hier ce ca cela week weekend vacances boulot travail taf
taff cours ecole fac lycee college sport foot football tennis basket velo course gym muscu piscine danse yoga
cine cinema film films serie series netflix jeu jeux gaming console musique concert lecture livre livres dodo
sieste douche menage courses lessive vaisselle cuisine maison appart bureau voiture train bus metro avion
moi toi lui eux nous vous chacun personne tout rien quelqu quelquun chef patron collegue copain copine pote
amie ami frere soeur maman papa mere pere mari femme fils fille bebe chat chien
paris lyon marseille toulouse nice nantes bordeaux lille strasbourg montpellier rennes grenoble brest rouen
toulon dijon reims angers limoges metz caen orleans bruxelles geneve lausanne montreal quebec londres berlin
madrid rome barcelone lisbonne amsterdam tokyo
francais francaise parisien parisienne lyonnais lyonnaise marseillais marseillaise toulousain toulousaine
nantais nantaise bordelais bordelaise lillois lilloise breton bretonne normand normande alsacien alsacienne
corse basque belge suisse canadien canadienne quebecois quebecoise americain americaine anglais anglaise
allemand allemande espagnol espagnole italien italienne portugais portugaise chinois chinoise japonais
japonaise algerien algerienne marocain marocaine tunisien tunisienne africain africaine europeen europeenne
enchante enchantee enchantes enchantees ravi ravie
""".split())
#: Participes : « Allée », « Tombé » (un prénom finit rarement ainsi).
_PARTICIPLE = re.compile(r"[éèê]e?s?$", re.I)


def _is_name_word(word: str) -> bool:
    if len(word) < 2 or any(ch.isdigit() for ch in word):
        return False
    folded = fold(word).replace("’", "'")
    if folded in NOT_NAMES:
        return False
    stem, _, rest = folded.partition("'")
    return not (rest and (stem in NOT_NAMES or rest in NOT_NAMES))


def plausible(raw: str) -> str | None:
    """Un fragment capturé → un nom, ou ``None``. La capture sur deux mots est
    gourmande (« Thomas en fait ») : un second mot refusé retombe sur le
    premier seul, un nom manqué dans un démenti coûtant cher."""
    name = " ".join(raw.split()).strip(" ,.;:!?-'’")
    if not name or len(name) > MAX_NAME:
        return None
    parts = name.split()
    while parts:
        if all(_is_name_word(w) for w in parts):
            return " ".join(w if w[:1].isupper() else w.capitalize() for w in parts)
        parts = parts[:-1]
    return None


def _weak_ok(raw: str) -> bool:
    first = raw.split()[0] if raw.split() else ""
    if not first[:1].isupper() or (first.isupper() and len(first) > 3):
        return False  # une minuscule ne se présente pas ; « je suis FATIGUÉE » crie
    return not _PARTICIPLE.search(first)


def _first(patterns: tuple[re.Pattern[str], ...], text: str, *, weak: bool = False) -> str | None:
    for pattern in patterns:
        for m in pattern.finditer(text):
            raw = m.group(1)
            if weak and not _weak_ok(raw):
                continue
            name = plausible(raw)
            if name:
                return name
    return None


def detect(text: str) -> Detection:
    """Ce qu'un message dit de qui l'écrit. Le plus souvent : rien."""
    if not text or len(text) > 2000:
        return Detection()
    denial = _first(_DENIALS, text)
    # un démenti contient souvent « je suis pas X » : on ne le relit pas en revendication
    rest = text
    for pattern in _DENIALS:
        rest = pattern.sub(" ", rest)
    claim = _first(_STRONG, rest)
    strong = claim is not None
    if claim is None:
        claim = _first(_WEAK, rest, weak=True)
    return Detection(claim=claim, denial=denial, strong=strong)
