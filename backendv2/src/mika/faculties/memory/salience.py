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
from mika.kernel.clock import DAY
from mika.kernel.frame import Audience
from mika.vocab.affect import emotion_of, valence
from mika.vocab.privacy import Sensitivity, tied_to
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
        return (item.confidence or 0.5) * 0.5 ** (age / half)
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


@dataclass(frozen=True, slots=True)
class Verdict:
    ok: bool
    others: tuple[str, ...] = ()  # les autres personnes concernées, ou qui l'ont confié
    witness: bool = False  # l'interlocuteur était là quand ça s'est dit
    level: int = 0  # ce qu'il faut pour l'entendre (sur autrui) : 0 quand c'est sa fiche ou sa vie à elle
    tellers: tuple[str, ...] = ()  # qui l'a confié, hors l'interlocuteur
    secret: bool = False
    #: admis parce que l'interlocuteur a un lien avec les personnes concernées (au niveau « lié », ADR 0058)
    tied: bool = False


def admissible(about: tuple[str, ...], sensitivity: int, interlocutor: str | None, audience: Audience, *,
               told_by: Sequence[str] = (), heard_by: Sequence[str] = (), secret: bool = False) -> Verdict:
    """Peut-on le dire devant cette audience ? (voir le docstring du module).

    Un élément d'avant que la mémoire ne sache qui le lui a confié (ni
    confident ni témoin) garde l'ancienne règle : l'interlocuteur qui y figure
    est traité en témoin."""
    known = bool(told_by or heard_by)
    tellers = tuple(sorted(set(told_by) - {interlocutor}))
    others = tuple(sorted({*about, *told_by} - {interlocutor}))
    if not about and not told_by:  # personne d'identifié : anodin, ou ce que l'audience peut entendre
        return Verdict(sensitivity <= max(Sensitivity.ANODYNE, audience.level))
    if not others:  # seulement l'interlocuteur
        return Verdict(sensitivity <= Sensitivity.ANODYNE or audience.private_ok)
    if interlocutor is not None and interlocutor in told_by:  # ses propres mots, même sur d'autres : sa fiche
        return Verdict(sensitivity <= Sensitivity.ANODYNE or audience.private_ok, others, secret=secret)
    witness = interlocutor is not None and (interlocutor in heard_by if known else interlocutor in about)
    if secret:  # « dis-le à personne » : jamais hors de qui l'a confié
        return Verdict(False, others, witness, int(sensitivity), tellers, True)
    limit = audience.witness_level if witness else audience.level
    tied = False
    if sensitivity > limit and interlocutor is not None and tied_to(others, audience.ties):
        # il a un lien avec chacune (ils se sont parlé ensemble, ou elle l'a nommé elle-même) : une proche peut
        # entendre sa confidence — jamais quelqu'un qui a seulement prononcé son nom (ADR 0058)
        limit, tied = max(limit, audience.tied_level), True
    return Verdict(sensitivity <= limit, others, witness, int(sensitivity), tellers, tied=tied)


def _names(keys: Sequence[str], names: dict[str, str]) -> tuple[str, bool]:
    """« Alice », « Alice et Bob », « Alice, Bob et Carol » ; et si c'est un pluriel."""
    shown = [names.get(k, k) for k in keys]
    if len(shown) <= 1:
        return (shown[0] if shown else "quelqu'un"), False
    return f"{', '.join(shown[:-1])} et {shown[-1]}", True


def tag(verdict: Verdict, names: dict[str, str]) -> str:
    """L'étiquette qui lui dit d'arbitrer (rien sous le personnel, rien sur
    ce qu'on lui a dit soi-même) : elle nomme qui l'a confié."""
    if not verdict.ok or not verdict.others or verdict.level < Sensitivity.PERSONAL:
        return ""
    if verdict.tellers:
        who, many = _names(verdict.tellers, names)
        if verdict.level >= Sensitivity.CONFIDENCE:
            return (f" ({who} te l'{'ont' if many else 'a'} confié ; ne le répète pas sauf si "
                    f"{who} t'y {'ont' if many else 'a'} autorisée)")
        return f" ({who} te l'{'ont' if many else 'a'} dit en privé)"
    who, _many = _names(verdict.others, names)
    if verdict.level >= Sensitivity.CONFIDENCE:
        return f" (ça touche {who} de près : ne le répète pas)"
    return f" (ça touche {who} : à toi de juger si ça se dit ici)"


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
                asked: tuple[str, ...] = ()) -> str:
    """Une ligne qui ne dit rien du contenu. Devant un ami, elle peut savoir
    que c'est lourd ; devant les autres, seulement que c'est privé. Quand la
    question en cours y touche, elle le sait, avec les mots de la question (sinon
    le modèle ne fait pas le lien, et ment : « non, il ne m'a rien dit »)."""
    who = names.get(person, person)
    if heavy and close:
        return f"- {who} t'a confié traverser un moment difficile : ce n'est pas à toi d'en dire plus."
    known = {fold(n) for n in names.values() if n}
    asked = tuple(w for w in asked if fold(w) not in known)  # un prénom n'est pas un sujet
    if asked:
        words = ", ".join(f"« {w} »" for w in asked)
        return (f"- {who} t'a confié des choses en privé, et ce dont on te parle là ({words}) en fait partie : "
                "ce n'est pas à toi d'en parler ici.")
    return f"- {who} t'a confié des choses en privé : ce n'est pas à toi d'en parler ici."


def unsaid_public_line(person: str, names: dict[str, str], when: str = "") -> str:
    """Devant un salon : ce que la personne lui a dit en privé ne se raconte pas, mais elle ne fait pas comme si
    elle ne savait rien — sinon le modèle invente qu'il ne l'a pas vue (sonde réelle du 2026-10-03, dans un groupe
    Telegram : « je l'ai pas vu non plus depuis le week-end », alors qu'elle lui avait parlé la veille). Ni le
    contenu, ni « moment difficile » : le salon n'a pas à deviner ce qui pèse."""
    who = names.get(person, person)
    if when:
        # quand elles se sont parlé n'est pas ce qu'elle lui a dit : sans ce repère, même avec la consigne, un modèle
        # répondait encore « j'ai pas eu de nouvelles non plus » (sonde du 2026-10-03)
        return (f"- Tu as parlé avec {who} {when}. Ce {elided(who, 'que')} t'a dit ne se raconte pas ici : si on te "
                "demande de ses nouvelles, ne dis surtout pas que tu n'en as pas — dis que vous vous êtes parlé et que "
                f"c'est à {who} de raconter.")
    return (f"- Ce {elided(who, 'que')} t'a dit en privé ne se raconte pas ici : si on te demande de ses nouvelles, "
            f"ne prétends pas ne rien savoir — c'est à {who} de raconter, renvoie vers lui ou elle.")


def valence_sign(emotion: str | None) -> int:
    e = emotion_of(emotion)
    if e is None:
        return 0
    v = valence(e)
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
