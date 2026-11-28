"""Les mots d'une ligne de ce qu'elle se rappelle, tels que le rappel, ses sections et ses outils les écrivent.

Une ligne, c'est un souvenir, une croyance ou un moment, dit avec ce qui l'accompagne :

- ce qui en fait douter : une personne seulement présumée (``doubted``, ADR 0075), une autre version qui la contredit
  sans la remplacer (``contested_line``, ADR 0081) ;
- ce qu'on en ressent : la personne concernée, elle-même (``feelings``), ce que c'est pour qui le vit (``tone``), ce
  qui pèse ou se sent sans rien en savoir (``heavy``, ``sensed``, ``mood_of``, ADR 0083) ;
- qui elle concerne (``concerned_name``), sa nature et selon qui (``knowledge_label``) ;
- quand : un jour dit comme on le dit (``when_words``), ce qu'elle attend d'une prévision (``expected_line``,
  ADR 0084).

Seules des lignes qui peuvent se dire ici en reçoivent : le verdict est rendu avant (``hearing.py``), et les doutes
n'y nomment qu'un témoin que l'audience peut entendre. Les phrases sont dans la voix (``memory.recall``,
``memory.when``, ``memory.tag``…). L'enrichisseur (``recall.py``), ses sections (``recall_sections.py``) et ses outils
(``tools.py``) les lisent d'ici ; ce module n'inscrit aucune contribution.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select

from mika.contracts import memory as c
from mika.faculties.memory import tables as tb
from mika.faculties.memory import timespan
from mika.faculties.memory.conversation import facet_words
from mika.faculties.memory.hearing import canon, hearing, items_by_id, names_of, presumed_of, verdict_of
from mika.faculties.memory.likelihood import likely_words
from mika.faculties.memory.salience import Item, facets_sign, valence_sign
from mika.kernel.frame import Audience, Frame
from mika.vocab import affect as A
from mika.vocab.circadian import DAYS_FR, day_month_fr
from mika.vocab.people import named_label
from mika.vocab.phrasebook import family, phrase
from mika.vocab.privacy import Sensitivity, Verdict

# ── Ce qui en fait douter ─────────────────────────────────────────────────


def doubted(frame: Frame, item: Item, memo: dict[str, str], interlocutor: str | None = None,
            verdict: Verdict | None = None) -> str:
    """Le doute d'une ligne qui parle d'une personne seulement présumée (ADR 0075) : « Alice », dont Bob lui a
    parlé, n'est peut-être pas l'Alice qu'elle connaît — qu'elle ne mélange pas les deux, ou qu'elle demande. Rien
    devant qui l'a raconté : il sait de qui il parlait (et la ligne lui apprendrait qu'elle connaît une Alice). Une
    croyance dite par plusieurs nomme le témoin auquel elle l'attribue ici (``verdict``), jamais les autres."""
    tellers_of = {k for t in item.testimonies for k in t.told_by} if item.testimonies else set(item.told_by)
    if interlocutor is not None and interlocutor in canon(frame, tuple(tellers_of), memo):
        return ""
    presumed = sorted(named_label(k).title() for k in (*item.about, *([item.holder] if item.holder else []))
                      if k.startswith("name:") and canon(frame, (k,), memo)[0] == k and presumed_of(frame, k, memo))
    if not presumed:
        return ""
    told = verdict.tellers if verdict is not None and item.testimonies else canon(frame, item.told_by, memo)
    tellers = sorted(names_of(frame, set(told)).values())
    who = phrase("memory.names.and", others=", ".join(tellers[:-1]), last=tellers[-1]) if len(tellers) > 1 else (
        tellers[0] if tellers else phrase("memory.names.someone"))
    return phrase("memory.tag.presumed", name=presumed[0], who=who)


def contested_line(frame: Frame, item: Item, person: str | None, aud: Audience, memo: dict[str, str],
                   store: Any, names: Mapping[str, str]) -> str:
    """Le doute d'une croyance qu'une autre contredit sans la remplacer (ADR 0081) : « mais Carol t'a dit autre
    chose » — seulement quand l'autre version peut se dire ici aussi (sinon le doute la laisserait deviner)."""
    if item.kind != c.BELIEF or store is None:
        return ""
    ct = tb.contests()
    others = [int(o) for (o,) in store.query_mind(select(ct.c.other).where(ct.c.item == item.id)
                                                  .order_by(ct.c.other))]
    for other in items_by_id(store, others).values():
        if other.status != c.ACTIVE_STATUS:
            continue
        verdict = verdict_of(frame, other, person, aud, memo, store)
        if not verdict.ok:
            continue
        # qui a dit l'autre version : le témoin auquel elle l'attribue ici, jamais un témoignage que cette audience
        # ne peut pas entendre (le premier pouvait être un secret, ADR 0080) ; quand c'est l'interlocuteur qui l'a
        # dite, c'est lui — sinon « quelqu'un »
        tellers = verdict.tellers
        if not tellers and person is not None and other.testimonies and any(
                t.speaks and person in canon(frame, t.told_by, memo)
                for t in hearing(frame, other, person, aud, memo, store)[1]):
            tellers = (person,)
        who = ", ".join(names.get(k) or names_of(frame, {k}).get(k) or phrase("memory.names.someone")
                        for k in tellers) or phrase("memory.names.someone")
        return phrase("memory.recall.contested", who=who, other=other.text)
    return ""


# ── Ce qu'on en ressent ───────────────────────────────────────────────────


def tone(item: Item) -> int:
    """Ce qu'un élément est pour qui le vit : une peine (−1), une joie (+1), on ne sait pas (0) — ce que la personne
    concernée en ressent d'abord, sinon ce qu'elle-même en ressent ; toutes facettes pesées (ADR 0083)."""
    return facets_sign(item.felt) or facets_sign(item.empathy) or valence_sign(item.emotion)


def feelings(felt: Sequence[tuple[str, float]], empathy: Sequence[tuple[str, float]], who: str) -> str:
    """Ce que la personne concernée en ressent (« Inès le vit avec colère et un peu de dégoût ») et ce qu'elle-même
    en ressent (« toi, tu en es triste, avec un peu d'inquiétude ») : l'empathie, en mots (ADR 0083), jugée par la
    relecture. ``who`` : le nom de la personne concernée — vide, ce qu'elle ressent ne se dit pas (on ne sait pas
    de qui)."""
    parts = [phrase("memory.recall.felt.theirs", who=who, what=facet_words(felt))] if felt and who else []
    if empathy:
        mine = phrase("memory.recall.felt.yours", feeling=A.FR[A.Emotion(empathy[0][0])])
        if empathy[1:]:
            mine += phrase("memory.recall.felt.yours_more", what=facet_words(empathy[1:], lead=False))
        parts.append(mine)
    return phrase("memory.recall.felt.both", what=" ; ".join(parts)) if parts else ""


def heavy(item: Item) -> bool:
    """Ce qui pèse : une peine, une peur, ou une confidence."""
    return tone(item) < 0 or item.sensitivity >= Sensitivity.CONFIDENCE


def sensed(item: Item) -> bool:
    """Ce qu'une proche peut sentir chez la personne sans rien en savoir : ce qui pèse, ou une joie qu'elle garde
    encore pour elle (ADR 0083)."""
    return heavy(item) or tone(item) > 0


def mood_of(items: Sequence[Item]) -> int:
    """Ce que des éléments tus sont, ensemble, pour la personne : une peine l'emporte, puis une joie (ADR 0083)."""
    tones = [tone(i) for i in items]
    return -1 if -1 in tones else 1 if 1 in tones else 0


# ── Qui elle concerne, ce qu'elle est ─────────────────────────────────────


def concerned_name(frame: Frame, about: Sequence[str], names: Mapping[str, str], memo: dict[str, str]) -> str:
    """Le nom de la seule personne qu'un élément concerne ; vide s'il en concerne plusieurs, ou personne."""
    keys = canon(frame, tuple(about), memo)
    return (names.get(keys[0]) or names_of(frame, {keys[0]}).get(keys[0], "")) if len(keys) == 1 else ""


def knowledge_label(item: Item, names: Mapping[str, str]) -> str:
    labels = family("memory.recall.nature")
    nature = labels.get(item.knowledge_kind, labels["claim"])
    holder = names.get(item.holder or "") or named_label(item.holder or "") or item.holder
    return phrase("memory.recall.viewpoint", nature=nature, holder=holder) if holder else nature


# ── Quand ─────────────────────────────────────────────────────────────────


def when_words(t: int, frame: Frame, *, all_day: bool = True) -> str:
    """Un jour dit comme on le dit : aujourd'hui, demain, jeudi, hier soir, le 12 octobre."""
    today, then = frame.local().date(), frame.local(t)
    days = (then.date() - today).days
    at = "" if all_day else phrase("memory.when.at", hour=then.hour, minute=f"{then.minute:02d}") if then.minute \
        else phrase("memory.when.at_hour", hour=then.hour)
    if days == 0:
        return phrase("memory.when.today") + at
    if days == 1:
        return phrase("memory.when.tomorrow") + at
    if days == -1:
        return phrase("memory.when.yesterday") + at
    if 1 < days < 7:
        return phrase("memory.when.soon", weekday=DAYS_FR[then.weekday()], at=at, days=days)
    if -7 < days < -1:
        return phrase("memory.when.last", weekday=DAYS_FR[then.weekday()])
    return phrase("memory.when.date", date=day_month_fr(then.date()), at=at)


def expected_line(item: Item, frame: Frame) -> str:
    """Après une prévision (ADR 0084) : quand c'est attendu et à quel point c'est sûr, en mots."""
    if item.knowledge_kind != "prediction":
        return ""
    likely = likely_words(item.likelihood)
    if not item.due:
        return phrase("memory.recall.expected_likely", likely=likely) if likely else ""
    tz = frame.env.tz_of(frame.root)
    when = timespan.period_words(item.due, item.until or item.due, item.precision, frame.now, tz) if item.precision \
        else when_words(item.due, frame)
    return phrase("memory.recall.expected", when=when, likely=likely or phrase("memory.likely.unsure"))
