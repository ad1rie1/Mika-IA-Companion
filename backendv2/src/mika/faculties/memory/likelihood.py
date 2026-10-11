"""La vraisemblance de ce qui vient (ADR 0084) : à quel point un moment, une prévision vont arriver.

Elle part de la nature de ce qui la dit — la personne sur sa propre vie (``likely_first_hand``), un autre ou le monde
(``likely_reported``), une date officielle (``likely_official``), une prévision, la sienne comprise
(``likely_prediction``, au plus comme une déduction) — et ce qu'en dit la personne (« c'est pas sûr », « peut-être »),
jugé par la relecture, ne peut que l'abaisser : on ne croit pas un moment plus sûr parce qu'on nous l'affirme. Elle se
dit en mots, jamais en nombre.

Elle apprend (ADR 0086) : de qui reporte ou annule souvent, ses prochaines annonces sont moins sûres (``learned``) ;
quand ses attentes d'une sorte tombent souvent à côté, elle en parle avec des mots plus prudents (``cautious``). Un
moment dont on n'a jamais su l'issue n'apprend rien. La surprise est l'écart entre ce qu'elle attendait et ce qui
est arrivé, pesé par ce que le moment compte (``surprise``).
"""

from __future__ import annotations

from typing import Any

from mika.contracts.memory import FIRST_HAND, OFFICIAL, OUTCOME_VALUE, PREDICTION, REPORTED
from mika.faculties.memory.faculty import MemoryParams
from mika.vocab.affect import tag_intensity
from mika.vocab.phrasebook import phrase
from mika.vocab.words import fold

#: ce qu'écrit la relecture dans « probabilite », rabattu sur une vraisemblance (clés : ``fold``)
_SAID = {
    0.98: ("certain", "certaine", "sur", "sure", "garanti", "assure", "officiel", "100%", "certainly"),
    0.9: ("prevu", "prevue", "confirme", "confirmee", "planifie", "planned", "confirmed"),
    0.7: ("probable", "probablement", "sans doute", "surement", "likely", "probably"),
    0.5: ("possible", "peut-etre", "peut etre", "pas sur", "pas sure", "incertain", "incertaine", "50/50",
          "maybe", "uncertain"),
    0.25: ("peu probable", "improbable", "douteux", "unlikely", "ca m'etonnerait"),
    0.1: ("tres improbable", "presque impossible", "very unlikely"),
}
_WORDS = {w: x for x, ws in _SAID.items() for w in ws}


def said(value: Any) -> float | None:
    """Ce qui a été dit de sa vraisemblance (un mot, ou un nombre de 0 à 1, ou un pourcentage) ; rien sinon."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return tag_intensity(str(value))
    text = fold(str(value)).strip().rstrip(".!")
    if not text:
        return None
    if text in _WORDS:
        return _WORDS[text]
    if any(ch.isdigit() for ch in text):
        return tag_intensity(text.rstrip("%"), percent=text.endswith("%"))
    return None


def prior_of(nature: str, p: MemoryParams) -> float:
    return {FIRST_HAND: p.likely_first_hand, OFFICIAL: p.likely_official,
            PREDICTION: p.likely_prediction}.get(nature, p.likely_reported)


def learned(prior: float, track: tuple[int, int] | None, p: MemoryParams) -> float:
    """Ce que vaut l'annonce de quelqu'un, d'après ce qu'elle a vu de lui (ADR 0086) : ``track`` (tenus, reportés ou
    annulés) ; à partir de ``track_min_cases`` cas, sa part de moments tenus, l'a priori comptant pour
    ``track_weight`` cas — jamais plus que l'a priori : tenir parole ne rend pas une annonce plus sûre que sa
    nature."""
    if not track:
        return prior
    kept, missed = track
    if kept + missed < p.track_min_cases:
        return prior
    return min(prior, (kept + prior * p.track_weight) / (kept + missed + p.track_weight))


def likelihood(nature: str, value: Any, p: MemoryParams, track: tuple[int, int] | None = None) -> float:
    """La vraisemblance d'un moment ou d'une prévision : l'a priori de sa nature (appris de qui l'annonce, ``track``),
    abaissé par ce qui en a été dit."""
    prior = learned(prior_of(nature, p), track, p)
    told = said(value)
    return round(min(prior, told) if told is not None else prior, 2)


def nature_of(ev: Any) -> str:
    """De quelle sorte était l'annonce d'un moment : une date officielle, la personne sur sa propre vie, sinon
    rapportée (un autre, le monde)."""
    if ev.official:
        return OFFICIAL
    if ev.told_by and ev.about and set(ev.told_by) <= set(ev.about):
        return FIRST_HAND
    return REPORTED




def surprise(outcome: str, likely: float | None, importance: float) -> float:
    """L'écart entre ce qu'elle attendait (``likely``) et ce qui est arrivé, pesé par ce que le moment compte : 0
    quand on ne sait pas comment il a tourné, ni ce qu'elle en attendait."""
    if outcome not in OUTCOME_VALUE or likely is None:
        return 0.0
    return round(abs(OUTCOME_VALUE[outcome] - likely) * max(0.0, min(1.0, importance)), 3)


def brier(calibration: tuple[int, float] | None) -> float | None:
    """L'écart quadratique moyen de ses attentes d'une sorte (``(n, somme des carrés)``) ; ``None`` sans cas."""
    if not calibration or calibration[0] <= 0:
        return None
    return calibration[1] / calibration[0]


def cautious(calibration: tuple[int, float] | None, p: MemoryParams) -> bool:
    """Ses attentes de cette sorte sont souvent tombées à côté : elle en parle plus prudemment."""
    b = brier(calibration)
    return b is not None and calibration is not None and calibration[0] >= p.calibration_min \
        and b >= p.calibration_cautious


#: de combien la prudence rabat les mots (un cran : « c'est sûr » devient « c'est prévu »)
CAUTION = 0.15


def likely_words(x: float | None, *, careful: bool = False) -> str:
    """Sa vraisemblance en mots (« c'est prévu », « ce n'est pas sûr »), jamais un nombre ; rien quand on ne sait pas.
    ``careful`` : ses attentes de cette sorte se sont souvent trompées, un cran plus prudent."""
    if x is None:
        return ""
    if careful:
        x -= CAUTION
    if x >= 0.95:
        return phrase("memory.likely.sure")
    if x >= 0.8:
        return phrase("memory.likely.planned")
    if x >= 0.6:
        return phrase("memory.likely.probable")
    if x >= 0.4:
        return phrase("memory.likely.unsure")
    if x >= 0.2:
        return phrase("memory.likely.unlikely")
    return phrase("memory.likely.doubtful")
