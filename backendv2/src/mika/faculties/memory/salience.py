"""Ce qui revient, et ce qui peut se dire — fonctions pures.

**Durer.** Un souvenir s'estompe à la lecture, jamais par balayage : son
poids vaut ``importance × ½^(âge / demi-vie)``, l'âge comptant depuis la
dernière fois qu'il a été touché (renforcé, ou rappelé : se souvenir fait
durer). La demi-vie croît avec l'importance, et avec les rappels (l'effet
d'espacement). Sous un seuil, il **dort** : il ne revient plus de lui-même,
mais une recherche délibérée le retrouve. Une croyance, elle, perd sa
confiance beaucoup plus lentement.

**Se dire.** Ce qui ne concerne personne (sa vie, le monde) se dit partout.
Ce qui ne concerne que l'interlocuteur se dit s'il est anodin, ou si sa
fiche est ouverte (jamais en public). Ce qui concerne d'autres se dit
jusqu'au niveau de l'audience (le niveau « témoin » quand l'interlocuteur y
figure aussi), avec une étiquette au-delà de l'anodin pour qu'elle arbitre.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from mika.contracts import memory as c
from mika.faculties.memory.faculty import MemoryParams
from mika.kernel.clock import DAY
from mika.kernel.frame import Audience
from mika.vocab.affect import emotion_of, valence
from mika.vocab.privacy import Sensitivity


@dataclass(frozen=True, slots=True)
class Item:
    id: int
    kind: str
    text: str
    about: tuple[str, ...]
    sensitivity: int
    importance: float
    confidence: float | None
    origin: str | None
    source: str | None
    emotion: str | None
    born_at: int
    touched_at: int
    recalled_at: int
    recalls: int
    status: str
    recipient: str | None = None
    due: int | None = None

    @classmethod
    def of(cls, row: dict[str, Any]) -> Item:
        return cls(
            id=int(row["id"]), kind=row["kind"], text=row["text"], about=tuple(json.loads(row["about"] or "[]")),
            sensitivity=int(row["sensitivity"]), importance=float(row["importance"]),
            confidence=None if row["confidence"] is None else float(row["confidence"]), origin=row["origin"],
            source=row["source"], emotion=row["emotion"], born_at=int(row["born_at"]),
            touched_at=int(row["touched_at"]), recalled_at=int(row["recalled_at"] or 0), recalls=int(row["recalls"]),
            status=row["status"], recipient=row.get("recipient"), due=row.get("due"),
        )


def salience(item: Item, now: int, p: MemoryParams) -> float:
    """Ce qu'il en reste à l'instant ``now`` (souvenir) ; pour une croyance,
    sa confiance effective."""
    age = max(0.0, (now - item.touched_at) / DAY)
    if item.kind == c.BELIEF:
        return (item.confidence or 0.5) * 0.5 ** (age / p.belief_half_life_days)
    half_life = (p.base_half_life_days + p.importance_half_life_days * item.importance) * (1 + 0.25 * min(item.recalls, 4))
    return item.importance * 0.5 ** (age / half_life)


def dormant(item: Item, now: int, p: MemoryParams) -> bool:
    if item.kind == c.BELIEF:
        return salience(item, now, p) < p.min_belief_confidence
    return salience(item, now, p) < p.dormant


@dataclass(frozen=True, slots=True)
class Verdict:
    ok: bool
    others: tuple[str, ...] = ()  # les autres personnes concernées
    witness: bool = False  # l'interlocuteur y figure aussi
    level: int = 0  # ce qu'il faut pour l'entendre (sur autrui)


def admissible(about: tuple[str, ...], sensitivity: int, interlocutor: str | None, audience: Audience) -> Verdict:
    others = tuple(sorted(a for a in about if a != interlocutor))
    concerned = interlocutor is not None and interlocutor in about
    if not about:
        return Verdict(True)
    if not others:  # seulement l'interlocuteur
        ok = sensitivity <= Sensitivity.ANODYNE or audience.private_ok
        return Verdict(ok)
    limit = audience.witness_level if concerned else audience.level
    return Verdict(sensitivity <= limit, others, concerned, sensitivity)


def tag(verdict: Verdict, names: dict[str, str]) -> str:
    """L'étiquette qui lui dit d'arbitrer (rien sous le personnel)."""
    if not verdict.others or verdict.level < Sensitivity.PERSONAL:
        return ""
    who = ", ".join(names.get(o, o) for o in verdict.others)
    if verdict.level >= Sensitivity.CONFIDENCE:
        return f" (une confidence de {who} — tu ne la dis que parce que tu es en confiance)"
    return f" (confié en privé par {who} — pas à répéter à n'importe qui)"


def valence_sign(emotion: str | None) -> int:
    e = emotion_of(emotion)
    if e is None:
        return 0
    v = valence(e)
    return 1 if v > 0.15 else -1 if v < -0.15 else 0


def rank(item: Item, similarity: float, now: int, p: MemoryParams, *, interlocutor: str | None,
         mood_valence: float) -> float:
    """Pertinence × ce qu'il en reste × ce qui le rapproche de maintenant."""
    if item.kind == c.BELIEF:
        weight = 0.5 + 0.5 * item.importance * min(1.0, salience(item, now, p) / 0.7)
    else:
        weight = 0.5 + min(1.0, salience(item, now, p))
    if interlocutor is not None and interlocutor in item.about:
        weight *= p.person_boost
    sign = valence_sign(item.emotion)
    if sign and mood_valence:
        aligned = (sign > 0) == (mood_valence > 0)
        if aligned:
            # la congruence d'humeur, bornée ; deux fois moindre quand l'humeur est sombre
            weight *= 1.0 + (0.1 if mood_valence > 0 else 0.05) * min(1.0, abs(mood_valence) * 2)
    if item.recalled_at and now - item.recalled_at < p.repetition_us:
        weight *= p.repetition_penalty
    return similarity * weight


def age_words(then: int, now: int) -> str:
    days = (now - then) / DAY
    if days < 1 / 24:
        return "à l'instant"
    if days < 1:
        return f"il y a {max(1, round(days * 24))} h"
    if days < 2:
        return "hier"
    if days < 14:
        return f"il y a {math.floor(days)} jours"
    if days < 60:
        return f"il y a {round(days / 7)} semaines"
    return f"il y a {round(days / 30)} mois"
