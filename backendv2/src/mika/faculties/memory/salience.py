"""Ce qui revient, et ce qui peut se dire — fonctions pures.

**Durer.** Un souvenir s'estompe à la lecture, jamais par balayage : son
poids vaut ``importance × ½^(âge / demi-vie)``, l'âge comptant depuis la
dernière fois qu'il a été touché (renforcé, ou rappelé : s'en servir fait
durer). La demi-vie croît avec l'importance, et avec les rappels (l'effet
d'espacement). Sous un seuil, il **dort** : il ne revient plus de lui-même,
mais une recherche délibérée — ou un indice fort — le retrouve ; un moment
marquant ne s'endort jamais tout à fait. Une croyance perd sa confiance
beaucoup plus lentement — sauf ce qu'elle raconte d'elle-même, qui s'efface
en quelques jours (ses goûts, ses avis, sa vie, eux, tiennent). Un souvenir
vécu avec quelqu'un à qui elle tient s'endort moins vite.

**Se dire.** Chaque élément sait qui il concerne (``about``), qui le lui a
confié (``told_by``) et qui l'a entendu (``heard_by``). Pour l'interlocuteur :

- ce qui ne concerne personne (sa vie, le monde) se dit partout s'il est
  anodin, sinon jusqu'au niveau de l'audience ;
- ce qu'il lui a confié lui-même, ou ce qui ne concerne que lui, sort s'il
  est anodin ou si sa fiche est ouverte (jamais en public) ;
- un secret (« dis-le à personne ») ne sort **que** devant qui l'a confié ;
- le reste concerne d'autres — tout confident autre que lui est un « autre » :
  ce que Bob a confié sur Alice n'est pas « à Alice » — et se dit jusqu'au
  niveau de l'audience, le niveau « témoin » s'il était là quand ça s'est dit,
  le niveau « lié » s'il a un lien avec chacune des personnes concernées
  (``Audience.ties``, ADR 0058) ;
  au-delà de l'anodin, une étiquette nomme qui l'a confié pour qu'elle arbitre.

Ce qui ne peut pas se dire ici n'est pas pour autant inconnu : elle peut
savoir qu'elle sait (``unsaid_line``), sans un mot du contenu.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from mika.contracts import memory as c
from mika.faculties.memory.faculty import MemoryParams
from mika.faculties.memory.knowledge import Testimony
from mika.kernel.clock import DAY
from mika.vocab.affect import emotion_of, facets, facets_valence, valence
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity, Verdict
from mika.vocab.privacy import admissible as admissible  # le verdict vit dans ``vocab.privacy`` : réexporté
from mika.vocab.words import elided, fold, stems


def _keys(raw: Any) -> tuple[str, ...]:
    try:
        got = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return ()
    return tuple(str(x) for x in got) if isinstance(got, list) else ()


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
    told_by: tuple[str, ...] = ()
    heard_by: tuple[str, ...] = ()
    secret: bool = False
    informants: tuple[str, ...] = ()
    about_self: bool = False
    shown_at: int = 0
    #: ce qu'elle a dit d'elle qui la définit (un goût, un avis, un fait de sa vie) : ça tient
    durable_self: bool = False
    #: ce qui n'appartient qu'à elle et à la personne : un surnom, une blague à elles (ADR 0055)
    between_us: bool = False
    knowledge_kind: str = "claim"
    holder: str | None = None
    constraints: tuple[c.Disclosure, ...] = ()
    internal_only: bool = False
    #: une croyance : chaque façon dont elle l'a apprise (ADR 0080) — vide pour un souvenir
    testimonies: tuple[Testimony, ...] = ()
    #: ce qui l'a remplacée (0 : rien) ; depuis et jusqu'à quand c'est vrai (ADR 0081)
    superseded_by: int = 0
    as_of: int = 0
    valid_until: int | None = None
    #: ce que la personne concernée en ressent, ce qu'elle-même en ressent (``emotion`` : sa facette la plus forte) —
    #: des émotions et leur intensité, la plus forte d'abord (ADR 0083)
    felt: tuple[tuple[str, float], ...] = ()
    empathy: tuple[tuple[str, float], ...] = ()
    #: une période (un moment) ou ce qui est attendu (une prévision : ``due`` son début), et à quel point (ADR 0084)
    until: int | None = None
    precision: str = ""
    likelihood: float | None = None
    #: la même chose, racontée sans qu'on puisse reconnaître la personne (ADR 0091) ; vide : jamais sans nom
    veiled: str = ""

    @classmethod
    def of(cls, row: dict[str, Any]) -> Item:
        return cls(
            id=int(row["id"]), kind=row["kind"], text=row["text"], about=_keys(row["about"]),
            sensitivity=int(row["sensitivity"]), importance=float(row["importance"]),
            confidence=None if row["confidence"] is None else float(row["confidence"]), origin=row["origin"],
            source=row["source"], emotion=row["emotion"], born_at=int(row["born_at"]),
            touched_at=int(row["touched_at"]), recalled_at=int(row["recalled_at"] or 0), recalls=int(row["recalls"]),
            status=row["status"], recipient=row.get("recipient"), due=row.get("due"),
            told_by=_keys(row.get("told_by")), heard_by=_keys(row.get("heard_by")), secret=bool(row.get("secret")),
            informants=_keys(row.get("informants")), about_self=bool(row.get("about_self")),
            shown_at=int(row.get("shown_at") or 0), durable_self=int(row.get("about_self") or 0) >= 2,
            between_us=bool(row.get("between_us")),
            knowledge_kind=str(row.get("knowledge_kind") or "claim"), holder=row.get("holder"),
            constraints=tuple(c.Disclosure.model_validate(v) for v in json.loads(row.get("constraints") or "[]")),
            internal_only=bool(row.get("internal_only")), superseded_by=int(row.get("superseded_by") or 0),
            as_of=int(row.get("as_of") or row["born_at"]),
            valid_until=None if row.get("valid_until") is None else int(row["valid_until"]),
            felt=facets(json.loads(row.get("felt") or "[]")), empathy=facets(json.loads(row.get("empathy") or "[]")),
            until=row.get("until"), precision=str(row.get("precision") or ""), likelihood=row.get("likelihood"),
            veiled=str(row.get("veiled") or ""),
        )


def salience(item: Item, now: int, p: MemoryParams, bond: float = 0.0) -> float:
    """Ce qu'il en reste à l'instant ``now`` (souvenir) ; pour une croyance,
    sa confiance effective. ``bond`` : ce qui l'attache aux personnes du
    souvenir (0 à 1) — vécu avec quelqu'un à qui elle tient, il dure plus."""
    age = max(0.0, (now - item.touched_at) / DAY)
    if item.kind == c.BELIEF:
        if item.about_self:
            half = p.self_durable_half_life_days if item.durable_self else p.self_half_life_days
        else:
            half = p.belief_half_life_days
        return (0.5 if item.confidence is None else item.confidence) * 0.5 ** (age / half)
    half_life = (p.base_half_life_days + p.importance_half_life_days * item.importance) * (1 + 0.25 * min(item.recalls, 4))
    half_life *= 1.0 + p.bond_memory_gain * max(0.0, min(1.0, bond))
    value = item.importance * 0.5 ** (age / half_life)
    if item.importance >= p.landmark_importance:
        value = max(value, p.landmark_floor)  # un moment marquant ne s'endort jamais tout à fait
    return value


def dormant(item: Item, now: int, p: MemoryParams, bond: float = 0.0) -> bool:
    if item.kind == c.BELIEF:
        return salience(item, now, p) < p.min_belief_confidence
    return salience(item, now, p, bond) < p.dormant


def _names(keys: Sequence[str], names: dict[str, str]) -> tuple[str, bool]:
    """« Alice », « Alice et Bob », « Alice, Bob et Carol » ; et si c'est un pluriel."""
    shown = [names.get(k, k) for k in keys]
    if len(shown) <= 1:
        return (shown[0] if shown else phrase("memory.names.someone")), False
    return phrase("memory.names.and", others=", ".join(shown[:-1]), last=shown[-1]), True


def tag(verdict: Verdict, names: dict[str, str]) -> str:
    """L'étiquette qui lui dit d'arbitrer (rien sous le personnel, rien sur
    ce qu'on lui a dit soi-même) : elle nomme qui l'a confié."""
    if not verdict.ok or not verdict.others or verdict.level < Sensitivity.PERSONAL:
        return ""
    if verdict.tellers:
        who, many = _names(verdict.tellers, names)
        if verdict.level >= Sensitivity.CONFIDENCE:
            return phrase("memory.tag.confided_many", who=who) if many else phrase("memory.tag.confided_one", who=who)
        return phrase("memory.tag.private_many", who=who) if many else phrase("memory.tag.private_one", who=who)
    who, _many = _names(verdict.others, names)
    if verdict.level >= Sensitivity.CONFIDENCE:
        return phrase("memory.tag.touches_close", who=who)
    return phrase("memory.tag.touches", who=who)


def unsaid(verdict: Verdict, about: Sequence[str], told_by: Sequence[str], interlocutor: str | None) -> tuple[str, ...]:
    """Ce qui ne se dit pas ici, mais qu'elle peut savoir savoir : les
    personnes à nommer dans une ligne vague. Seulement ce qu'une personne a
    confié sur elle-même (sinon la ligne trahirait un confident), et jamais
    devant la personne concernée (ce serait lui dire qu'on a parlé d'elle)."""
    if verdict.ok or not verdict.others or interlocutor is None or interlocutor in about:
        return ()
    subjects = tuple(a for a in about if not a.startswith("name:"))
    if not subjects or (told_by and not set(told_by) <= set(about)):
        return ()
    return subjects


def touched(query: str, text: str) -> tuple[str, ...]:
    """Les mots de la question qui touchent ce qu'on lui a confié (des radicaux pleins en commun) — les mots de
    la personne qui demande, jamais ceux du souvenir : les lui rendre ne dit rien qu'elle n'ait dit."""
    common = stems(query) & stems(text)
    out: list[str] = []
    for raw in re.findall(r"\w+", query.lower()):
        if len(raw) >= 4 and fold(raw)[:6] in common and raw not in out:
            out.append(raw)
    return tuple(out[:3])


def unsaid_line(person: str, names: dict[str, str], *, heavy: bool, close: bool,
                asked: tuple[str, ...] = (), tone: int = -1) -> str:
    """Une ligne qui ne dit rien du contenu. Devant un ami, elle peut sentir
    ce que ça pèse pour la personne — une peine (``tone`` négatif), une joie
    qu'elle garde encore (positif), ou seulement que ça compte (0) : ce que la
    personne en ressent, jugé par la relecture (ADR 0083) ; une grossesse gardée
    pour soi n'est pas « un moment difficile ». Devant les autres, seulement que
    c'est privé. Quand la question en cours y touche, elle le sait, avec les mots
    de la question (sinon le modèle ne fait pas le lien, et ment : « non, il ne
    m'a rien dit »)."""
    who = names.get(person, person)
    if heavy and close:
        if tone > 0:
            return phrase("memory.unsaid.joyful", who=who)
        if tone < 0:
            return phrase("memory.unsaid.heavy", who=who)
        return phrase("memory.unsaid.weighty", who=who)
    known = {fold(n) for n in names.values() if n}
    asked = tuple(w for w in asked if fold(w) not in known)  # un prénom n'est pas un sujet
    if asked:
        words = ", ".join(f"« {w} »" for w in asked)
        return phrase("memory.unsaid.asked", who=who, words=words)
    return phrase("memory.unsaid.private", who=who)


def unsaid_public_line(person: str, names: dict[str, str], when: str = "") -> str:
    """Devant un salon : ce que la personne lui a dit en privé ne se raconte pas, mais elle ne fait pas comme si
    elle ne savait rien — sinon le modèle invente qu'il ne l'a pas vue (sonde réelle du 2026-10-03, dans un salon :
    « je l'ai pas vu non plus depuis le week-end », alors qu'elle lui avait parlé la veille). Ni le
    contenu, ni « moment difficile » : le salon n'a pas à deviner ce qui pèse."""
    who = names.get(person, person)
    if when:
        # quand elles se sont parlé n'est pas ce qu'elle lui a dit : sans ce repère, même avec la consigne, un modèle
        # répondait encore « j'ai pas eu de nouvelles non plus » (sonde du 2026-10-03)
        return phrase("memory.unsaid.public_when", when=when, who=who, that_who=elided(who, "que"))
    return phrase("memory.unsaid.public", who=who, that_who=elided(who, "que"))


def valence_sign(emotion: str | None) -> int:
    e = emotion_of(emotion)
    if e is None:
        return 0
    v = valence(e)
    return 1 if v > 0.15 else -1 if v < -0.15 else 0


def facets_sign(felt: tuple[tuple[str, float], ...]) -> int:
    """La tonalité d'un ressenti à plusieurs facettes (ADR 0083) : sa valence pondérée par les intensités."""
    v = facets_valence(felt)
    return 1 if v > 0.15 else -1 if v < -0.15 else 0


def rank(item: Item, similarity: float, now: int, p: MemoryParams, *, interlocutor: str | None,
         mood_valence: float, bond: float = 0.0) -> float:
    """Pertinence × ce qu'il en reste × ce qui le rapproche de maintenant."""
    if item.kind == c.BELIEF:
        weight = 0.5 + 0.5 * item.importance * min(1.0, salience(item, now, p) / 0.7)
    else:
        weight = 0.5 + min(1.0, salience(item, now, p, bond))
    if interlocutor is not None and interlocutor in item.about:
        weight *= p.person_boost
    sign = valence_sign(item.emotion)
    if sign and mood_valence:
        aligned = (sign > 0) == (mood_valence > 0)
        if aligned:
            # la congruence d'humeur, bornée ; deux fois moindre quand l'humeur est sombre
            weight *= 1.0 + (0.1 if mood_valence > 0 else 0.05) * min(1.0, abs(mood_valence) * 2)
    last = max(item.shown_at, item.recalled_at)
    if last and now - last < p.repetition_us:
        weight *= p.repetition_penalty
    return similarity * weight


def age_words(then: int, now: int) -> str:
    days = (now - then) / DAY
    if days < 1 / 24:
        return phrase("memory.age.now")
    if days < 1:
        return phrase("memory.age.hours", hours=max(1, round(days * 24)))
    if days < 2:
        return phrase("memory.age.yesterday")
    if days < 14:
        return phrase("memory.age.days", days=math.floor(days))
    if days < 60:
        return phrase("memory.age.weeks", weeks=round(days / 7))
    return phrase("memory.age.months", months=round(days / 30))
