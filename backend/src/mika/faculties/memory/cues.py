"""Les indices dans les mots : ce que le code lit lui-même dans un texte, à côté de ce que juge la relecture.

Il y lit qu'on a demandé le silence (``says_secret``) et ce que la demande couvre (``silence_scope``,
``scoped_secrets``), ce qui laisse entendre qu'une chose est à garder (``hints_private``), une chose à faire
(``task_words``), un moment qui fait mal, se fête ou revient chaque année (``moment_importance``, ``festive``,
``yearly``), un texte qui laisse deviner un secret (``echoes``), une réplique recopiée ou reprise à son compte
(``copy_of``, ``voice_of``, ``quoted``), un surnom qu'on lui donne (``nicknames``), deux façons de dire le même
moment (``same_moment``) et ce qu'elle a vécu à travers quelqu'un, dit en bref (``gist_of``).

Le modèle tranche ce que des règles tranchaient (ADR 0153) : l'importance d'un moment, « à fêter » et « chaque
année » sont ceux qu'il dit, et une émotion est celle qu'il a jugée, jamais devinée dans le texte (``charged``). Ce
qui reste ici reste statique pour une raison :

- ce qui protège : ``SECRET_MARKERS`` (dit par la personne, c'est un secret quoi qu'en dise le modèle) et un deuil
  jamais fêté (``_DEATH`` : un fait, lu dans ce que la relecture a écrit, jamais dans le message de la personne) ;
- deux tris : une chose à faire n'est pas un moment de sa vie (``task_words``) ; un moment est celui de quelqu'un,
  ce qu'elle dit vivre seule n'en est pas un (ADR 0084 ; la règle est dans ``kept.py``) ;
- des filets sur ce que la relecture a écrit : une réplique recopiée mot pour mot, un nom ou un chiffre dans un bref,
  le même moment dit deux fois, un texte qui trahit un secret.

Le contrat avec le modèle vit dans ``extraction.py`` ; le filet d'une version sans nom (ADR 0091), dans
``retelling.py``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from difflib import SequenceMatcher

from mika.faculties.memory.conversation import Line
from mika.faculties.memory.extraction import IMPORTANCE, Extraction, XEvenement, sensitivity
from mika.faculties.memory.salience import SIGN
from mika.faculties.memory.speakers import People
from mika.vocab.affect import facets, facets_valence
from mika.vocab.circadian import DAYS_FR, MONTHS_FR
from mika.vocab.people import fold
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import WORD, stems, words
from mika.vocab.words import fold as wfold

#: un moment vécu à travers quelqu'un, dit en bref (« un concert de jazz ») : au plus tant de caractères
GIST_MAX = 80


def gist_of(text: str | None, people: People) -> str | None:
    """Ce qu'elle a vécu à travers quelqu'un, dit sans personne (ADR 0087) : la relecture l'écrit, le code garde un
    filet — trop long, un nom qu'elle connaît, un chiffre (une date, une adresse), et il n'y en a pas."""
    said = " ".join((text or "").split()).strip(" .")
    if len(said) < 3 or len(said) > GIST_MAX or re.search(r"\d", said) or people.names_someone(said):
        return None
    return said


#: ce qui, dit par la personne, en fait un secret quoi qu'en dise le modèle (replié, sans accents)
SECRET_MARKERS = ("dis le a personne", "dis a personne", "le dis a personne", "le repete a personne", "repete pas",
                  "repete a personne", "entre nous", "garde le pour toi", "garde ca pour toi", "c est un secret",
                  "c est secret", "motus", "ne lui dis pas", "lui dis pas", "ne lui dis surtout pas",
                  "lui dis surtout pas", "dis lui pas", "le lui dis pas", "ne lui en parle pas", "lui en parle pas",
                  "lui repete pas", "le dis a personne", "n en parle a personne", "en parle a personne")


def _flat(text: str) -> str:
    return " " + " ".join(re.sub(r"[^a-z0-9 ]", " ", fold(text)).split()) + " "


def says_secret(texts: Sequence[str]) -> bool:
    """La personne a-t-elle demandé de ne pas le répéter ?"""
    return any(marker in _flat(text) for text in texts for marker in SECRET_MARKERS)


#: ce qui laisse entendre, sans le demander, que c'est à garder (replié, sans accents) : « je l'ai encore dit à
#: personne », « tu es la seule à savoir » — le jugement du modèle y tient
PRIVATE_CUES = ("dit a personne", "personne ne le sait", "personne le sait", "personne n est au courant",
                "seule a savoir", "seul a savoir", "seule au courant", "seul au courant", "pas encore officiel",
                "pas officiel", "pas encore annonce", "pas encore dit")
#: ce qui accompagne une demande de silence sans rien raconter (replié) : « stp », « hein », « surtout »
_INSISTENCE = frozenset("stp svp please steuplait surtout hein promis promets jure vraiment okay ok compris "
                        "merci".split())


def hints_private(text: str) -> bool:
    flat = _flat(text)
    return any(cue in flat for cue in (*SECRET_MARKERS, *PRIVATE_CUES))


def _only_asks(text: str) -> bool:
    """Le message ne fait que demander le silence (« garde ça pour toi », « surtout dis-le à personne ») : il ne
    raconte rien lui-même."""
    flat = _flat(text)
    for marker in sorted(SECRET_MARKERS, key=len, reverse=True):
        flat = flat.replace(f" {marker} ", " ")
    return not [w for w in words(flat) if w not in _INSISTENCE]


def silence_scope(lines: Sequence[Line]) -> frozenset[int] | None:
    """Les messages qu'une demande de silence couvre (ADR 0092) — ``None`` : personne n'en a demandé dans cette
    conversation, le modèle seul en juge. Une demande dans un message qui raconte quelque chose couvre ce message ;
    une demande seule (« garde ça pour toi ») couvre ce que la même personne vient de dire, jusqu'à sa demande
    précédente. Pas au-delà : « je suis enceinte, dis-le à personne » ne fait pas un secret du licenciement raconté
    juste avant."""
    covered: set[int] = set()
    asked = False
    for i, ln in enumerate(lines):
        if ln.person is None or not says_secret([ln.text]):
            continue
        asked = True
        covered.add(ln.seq)
        if not _only_asks(ln.text):
            continue
        for prev in reversed(lines[:i]):
            if prev.person != ln.person:
                continue
            if says_secret([prev.text]):
                break
            covered.add(prev.seq)
    return frozenset(covered) if asked else None


def scoped_secrets(ex: Extraction, lines: Sequence[Line]) -> list[str]:
    """La relecture, corrigée par la portée des demandes de silence (ADR 0092) : un élément qui s'appuie sur un
    message couvert est un secret, que le modèle l'ait noté ou non ; un « secret » que le modèle pose hors de toute
    demande, dans une conversation où l'on en a fait une, ne l'est pas — sauf si ses messages laissent eux-mêmes
    entendre qu'il est à garder — mais reste une confidence (dans le doute, discrète, pas muette). Modifie ``ex`` ;
    rend les textes déclassés (pour le journal technique, jamais affichés)."""
    scope = silence_scope(lines)
    if scope is None:
        return []
    by_seq = {ln.seq: ln for ln in lines}
    lowered: list[str] = []
    for item in (*ex.souvenirs, *ex.croyances, *ex.evenements, *ex.previsions):
        theirs = {s for s in item.messages if s in by_seq and by_seq[s].person}
        if not theirs:
            continue  # rien de cité : la règle d'avant (une confidence d'une conversation où l'on a demandé le silence)
        if theirs & scope:
            item.secret = True
        elif item.secret and not any(hints_private(by_seq[s].text) for s in theirs):
            item.secret = False
            if sensitivity(item.sensibilite, has_person=True) < Sensitivity.CONFIDENCE:
                item.sensibilite = "confidence"
            lowered.append(item.texte)
    return lowered


#: ce qui commence comme une chose à faire (replié, sans accents) : « prendre rendez-vous chez le dentiste »,
#: « lui rappeler de… », « appeler sa mère » — pas ce qui lui arrive (« prendre l'avion pour Tokyo » en est un)
_TASK = re.compile(r"^\s*(?:lui\s+|me\s+|se\s+)?(?:rappeler|prendre\s+(?:un\s+)?(?:rdv|rendez)|appeler|reserver|"
                   r"acheter|payer|envoyer|commander|repondre|remplir|renvoyer|penser a|ne pas oublier)\b")


def task_words(text: str) -> bool:
    """Une chose à faire, pas un moment de la vie de quelqu'un (« prendre rendez-vous chez le dentiste »)."""
    return bool(_TASK.search(fold(text)))


#: ce qui dit qu'un moment parle d'une mort (replié, sans accents) — un fait, pas une émotion : dans le texte que la
#: relecture a écrit, jamais dans le message de la personne. Le filet qui garde de souhaiter « l'anniversaire de la
#: mort de son père »
_DEATH = re.compile(r"\b(?:mort|morte|deces|decede\w*|deuil|disparition|obseques|enterrement(?! de vie)|"
                    r"commemoration|hommage)\b")


def _felt_valence(ev: XEvenement) -> float:
    """Ce que la personne en ressent, tel que la relecture l'a jugé (ses facettes) : sa tonalité, 0 sans ressenti."""
    return facets_valence(facets(ev.ressenti))


def _painful(ev: XEvenement) -> bool:
    """Un moment qui fait mal : la personne le vit douloureusement (son ressenti, jugé par la relecture, ADR 0093),
    ou il parle d'une mort (un fait)."""
    return _felt_valence(ev) < -SIGN or bool(_DEATH.search(fold(ev.texte)))


def charged(importance: float, felt: Sequence[tuple[str, float]], empathy: Sequence[tuple[str, float]], *,
            from_: float, floor: float) -> float:
    """Ce qu'un élément pèse quand une émotion forte l'accompagne (ADR 0107) : au moins ``floor`` dès qu'une facette
    de ce que la personne ressent, ou de ce qu'elle-même en ressent, atteint ``from_`` — un moment chargé se garde
    mieux. L'émotion est celle que la relecture a jugée, jamais devinée dans le texte."""
    strongest = max((x for _e, x in (*felt, *empathy)), default=0.0)
    return max(importance, floor) if strongest >= from_ else importance


def moment_importance(ev: XEvenement) -> float:
    """Ce qu'un moment pèse : ce qu'en dit le modèle (ADR 0153 : aucun mot ne le relève) ; « marquant » pour une date
    qui revient chaque année et qui fait mal — la date d'un deuil, d'une séparation."""
    rated = IMPORTANCE.get(ev.importance, 0.45)
    return max(rated, IMPORTANCE[4]) if yearly(ev) and _painful(ev) else rated


def festive(ev: XEvenement) -> bool:
    """Un moment qui se fête, quand le modèle le dit (« a_feter ») — jamais ce qui fait mal (« l'anniversaire de la
    mort de son père », une date que la personne vit douloureusement)."""
    return ev.a_feter and not _painful(ev)


def yearly(ev: XEvenement) -> bool:
    """Une date qui revient chaque année (un anniversaire, la date d'un deuil), quand le modèle le dit
    (« chaque_annee ») — jamais une situation qui dure."""
    return not ev.en_cours and ev.chaque_annee


#: ce qui date un élément sans dire de quoi il parle : deux souvenirs du même mois ne se ressemblent pas pour autant
#: (sonde réelle du 2026-10-11 : « … le dimanche 11 octobre 2026, sa mère hospitalisée » devenait secret parce qu'un
#: secret de la semaine disait aussi « octobre 2026 »)
_DATING = frozenset(stems(" ".join((*DAYS_FR, *MONTHS_FR, "semaine", "dernier", "derniere", "prochain", "prochaine",
                                    "matin", "matinee", "soir", "soiree", "journee", "lundi", "aujourd'hui", "hier",
                                    "demain", "weekend", "week-end"))))


def _subject(text: str, names: set[str]) -> set[str]:
    return {s for s in stems(text) - names if s not in _DATING and not s.isdigit()}


def echoes(text: str, secrets: Sequence[str], names: set[str]) -> bool:
    """Ce texte laisse-t-il deviner un de ces secrets ? (au moins deux mots du
    sujet en commun — un seul si le secret n'en a qu'un —, prénoms, dates et
    nombres exclus)."""
    mine = _subject(text, names)
    for secret in secrets:
        theirs = _subject(secret, names)
        if theirs and len(mine & theirs) >= min(2, len(theirs)):
            return True
    return False


#: un texte qui reprend au moins cette part de ses mots, dans l'ordre, à une réplique la recopie
COPY_SHARE = 0.8


def copied(text: str, line: str) -> bool:
    """Ce texte recopie-t-il cette réplique ? Presque tous ses mots y sont, dans le même ordre (casse, accents et
    ponctuation à part) : « Pixel est parti cet après-midi », c'est le message de Sam ; « Sam m'a dit que Pixel est
    parti cet après-midi » le rapporte, il ne le recopie pas. Un texte de moins de quatre mots ne recopie qu'une
    suite exacte."""
    mine, theirs = WORD.findall(wfold(text)), WORD.findall(wfold(line))
    if not mine or not theirs:
        return False
    if len(mine) < 4:
        return any(theirs[i:i + len(mine)] == mine for i in range(len(theirs) - len(mine) + 1))
    blocks = SequenceMatcher(None, mine, theirs, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks) >= COPY_SHARE * len(mine)


#: un souvenir à la première personne qui reprend au moins cette part des mots d'une autre parle à sa place
VOICE_SHARE = 0.6
#: ce par quoi commence un texte à la première personne (replié)
_FIRST_PERSON = frozenset({"je", "j", "moi", "mon", "ma", "mes"})


def voice_of(text: str, lines: Sequence[Line]) -> Line | None:
    """La réplique d'une autre personne qu'un souvenir à la première personne reprend à son compte : « J'ai eu une
    petite fille, Jeanne : je suis épuisée mais tellement heureuse », tiré de Carol (« je viens d'avoir une petite
    fille, Jeanne, je suis épuisée… »), fait parler Mika à sa place (sonde réelle du 2026-10-09) — reformulé, il
    échappe à ``copied``. Un souvenir à elle (« J'ai consolé Carol, épuisée mais heureuse ») en reprend trop peu."""
    mine = WORD.findall(wfold(text))
    if not mine or mine[0] not in _FIRST_PERSON:
        return None
    best: tuple[float, Line] | None = None
    for ln in lines:
        if not ln.person:
            continue
        theirs = WORD.findall(wfold(ln.text))
        share = sum(b.size for b in SequenceMatcher(None, mine, theirs, autojunk=False).get_matching_blocks())
        share /= len(mine)
        if share >= VOICE_SHARE and (best is None or share > best[0]):
            best = (share, ln)
    return best[1] if best else None


def copy_of(text: str, lines: Sequence[Line]) -> Line | None:
    """La réplique que ce texte recopie (celle qui en reprend le plus), ou ``None``. À égalité, celle d'une personne
    plutôt que la sienne : Mika reprend souvent les mots qu'on vient de lui dire."""
    best: tuple[float, int, Line] | None = None
    mine = WORD.findall(wfold(text))
    for ln in lines:
        if not copied(text, ln.text):
            continue
        theirs = WORD.findall(wfold(ln.text))
        share = sum(b.size for b in SequenceMatcher(None, mine, theirs, autojunk=False).get_matching_blocks())
        key = (share / max(1, len(mine)), 1 if ln.person else 0, ln)
        if best is None or key[:2] > best[:2]:
            best = key
    return best[2] if best else None


def quoted(name: str, text: str) -> str:
    """Ce que quelqu'un lui a dit, mot pour mot, en disant qui parle."""
    words_ = " ".join(text.split()).strip().strip("«»\"' ")
    return phrase("memory.extraction.quoted", name=name or phrase("memory.extraction.someone"), words=words_)


#: un mot qui salue, remercie ou prend congé, suivi d'un nom : celui par lequel on s'adresse à elle (« salut
#: Mikachu », « bonne soirée Mikachu », « merci Mikachu ! »)
_VOCATIVE = re.compile(r"(?<![\w'])(?:salut|coucou|hey|hello|bonjour|bonsoir|yo|re|merci|bisous|bises|bye|ciao|"
                       r"[àa] plus|[àa] demain|bonne (?:nuit|soir[ée]e|journ[ée]e|aprem))[\s,]+([^\W\d_][\w-]{2,30})"
                       r"(?![\w'])", re.IGNORECASE)


def _squeezed(text: str) -> str:
    """Replié, lettres répétées réduites (« Mikaaa » est « Mika » qu'on étire, pas un surnom)."""
    return re.sub(r"(.)\1+", r"\1", wfold(text))


def nicknames(text: str, her: str) -> list[str]:
    """Les surnoms qu'un message lui donne : un mot qui la salue (« salut Mikachu ») et qui dérive de son prénom
    sans l'être — il le contient, ou en garde le début (« Mikachu », « Mikou » ; pas « Mika », ni « Mikaaa »). Ce
    qui ne dérive pas de son prénom (« salut Chef ») reste au modèle : un nom qui suit un bonjour peut aussi être
    celui de quelqu'un d'autre."""
    own = _squeezed(her)
    out: list[str] = []
    if len(own) < 3:
        return out
    for m in _VOCATIVE.finditer(text):
        word = m.group(1)
        folded = _squeezed(word)
        if (own in folded or folded[:3] == own[:3]) and folded != own and word not in out:
            out.append(word)
    return out


def same_moment(a: str, b: str, names: Sequence[str] = ()) -> bool:
    """Deux façons de dire le même moment de la vie de quelqu'un : une fois les prénoms ôtés, les mots de l'un sont
    tous dans l'autre (« son anniversaire », « l'anniversaire de Sam », « son anniversaire de 30 ans »). À l'appelant
    de vérifier que c'est le même jour, pour la même personne : « son rendez-vous chez le dentiste » n'est pas « son
    rendez-vous chez le véto »."""
    named = {w for n in names for w in WORD.findall(wfold(n))}
    mine, theirs = set(words(a)) - named, set(words(b)) - named
    return bool(mine) and bool(theirs) and (mine <= theirs or theirs <= mine)
