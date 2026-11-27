"""Ce qui peut se dire ici, élément par élément : la règle de sûreté de sa mémoire devant qui l'écoute (secrets,
confidences, ADR 0078, 0080, 0092).

Un souvenir, une croyance et ses témoignages peuvent-ils se dire devant cette audience, attribués à quel témoin
(``verdict_of``, ``hearing``) ? Avec quelle confiance (``heard_confidence``), et ce que la personne concernée en
ressent peut-il s'entendre ici (``felt_here``) ? Ce que le verdict lit pour en juger :

- les clés telles qu'elles valent maintenant (``canon`` : une adresse reliée depuis à quelqu'un parle pour lui) et la
  personne qu'une mention désigne présumément (``presumed_of``, ``presumer``, ADR 0075 : de quoi y penser, jamais de
  quoi la traiter comme elle) — lues par le contrat de l'identité (``contracts.identity.resolvers``), comme partout
  dans sa mémoire, ces deux-là n'y ajoutant qu'un mémo ;
- un élément relu par son numéro, ses témoignages compris (``items_by_id``) ;
- et, pour le dire, le nom d'une clé (``names_of``).

Le verdict d'une règle de divulgation est commun à toutes les facultés (``vocab.privacy.admissible``) ; ce module dit
ce que la mémoire en lit pour l'un de ses éléments. Ce qui fait d'un sujet délicat une confidence (ADR 0099) est dans
``delicate.py``. Le rappel (``recall.py``), les mots d'une ligne, ses outils (``tools.py``), la relecture de la nuit
(``reread.py``) et la console (``inspect.py``) lisent d'ici ; ce module n'inscrit aucune contribution.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

from sqlalchemy import select

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.faculties.memory import tables as tb
from mika.faculties.memory.delicate import sensitivity_of
from mika.faculties.memory.salience import Item
from mika.faculties.memory.tables import (
    ITEM_COLUMNS,
    Testimony,
    batches,
    item_columns,
    testimony_columns,
    testimony_of,
)
from mika.faculties.memory.testimonies import pooled
from mika.kernel.frame import Audience, Frame
from mika.vocab.people import named_label, phone_label, read_source
from mika.vocab.privacy import Sensitivity, Verdict, admissible

# ── Les clés telles qu'elles valent maintenant ────────────────────────────


def canon(frame: Frame, keys: Sequence[str], memo: dict[str, str]) -> tuple[str, ...]:
    """Les clés telles qu'elles valent maintenant : une adresse reliée depuis
    à quelqu'un parle pour lui (ce qu'elle a confié sous son autre compte est à elle) ; un nom qu'un opérateur a
    relié à une personne (« l'Alice dont Bob parlait », c'était elle) la désigne — sinon il reste ce qu'il est. Lue
    par le contrat de l'identité (``resolvers``), une fois par clé (``memo``)."""
    out = set()
    for k in keys:
        if k not in memo:
            resolve, _ = identity_c.resolvers(frame.get)
            memo[k] = resolve(k)
        out.add(memo[k])
    return tuple(sorted(out))


def presumed_of(frame: Frame, key: str, memo: dict[str, str]) -> str:
    """La personne qu'une mention non reliée désigne présumément (ADR 0075), ``""`` sinon : de quoi y penser
    quand on la nomme, jamais de quoi la traiter comme elle (le verdict ne suit pas une présomption). Lue par le
    contrat de l'identité (``resolvers``), une fois par clé (``memo``)."""
    slot = "?" + key  # rangée à côté de ``canon`` sans s'y mêler
    if slot not in memo:
        _, presumed = identity_c.resolvers(frame.get)
        memo[slot] = presumed(key)
    return memo[slot]


def presumer(frame: Frame, memo: dict[str, str]) -> Callable[[str], str]:
    """La présomption d'une mention, telle que le verdict la lit (un lien exigé avec la personne présumée)."""
    return lambda key: presumed_of(frame, key, memo)


# ── Le nom d'une clé ──────────────────────────────────────────────────────


def names_of(frame: Frame, keys: set[str]) -> dict[str, str]:
    out = {}
    for k in keys:
        if k.startswith("name:"):
            out[k] = named_label(k).title()
        elif read_source(k):
            out[k] = read_source(k)  # ce qu'elle a lu : le flux, pas une personne (ADR 0085)
        elif phone_label(k):
            out[k] = phone_label(k)  # un contact du téléphone de quelqu'un (ADR 0120)
        else:
            out[k] = frame.get(identity_c.IDENTITY(k)).name or k
    return out


# ── Un élément relu par son numéro ────────────────────────────────────────


def items_by_id(store: Any, ids: list[int]) -> dict[int, Item]:
    if not ids:
        return {}
    t, tt = tb.items(), tb.testimonies()
    found: dict[int, Item] = {}
    for chunk in batches(sorted(set(ids))):
        rows = store.query_mind(select(*item_columns()).where(t.c.id.in_(chunk)))
        found.update({int(r[0]): Item.of(dict(zip(ITEM_COLUMNS, r, strict=True))) for r in rows})
    beliefs = sorted(i for i, it in found.items() if it.kind == c.BELIEF)
    if beliefs:
        said: dict[int, list[Testimony]] = {}
        for chunk in batches(beliefs):
            for r in store.query_mind(select(*testimony_columns()).where(tt.c.item.in_(chunk))
                                      .order_by(tt.c.item, tt.c.seq)):
                said.setdefault(int(r[0]), []).append(testimony_of(r))
        found.update({i: replace(found[i], testimonies=tuple(ts)) for i, ts in said.items()})
    return found


# ── Son verdict devant qui l'écoute ───────────────────────────────────────


def verdict_of(frame: Frame, item: Item, person: str | None, aud: Audience, memo: dict[str, str],
               store: Any = None) -> Verdict:
    """Ce qui décide si un élément peut se dire ici : ses personnes, qui l'a
    confié et entendu (telles qu'elles valent maintenant), sa sensibilité
    (sujets délicats des profils compris, gardés à part dans ``store``)."""
    if item.internal_only:
        return Verdict(False, secret=True)
    inherited_rules = []
    # les sujets délicats des profils comptent aussi pour ce qu'elle a repensé (``item.about`` porte ses sources)
    own = sensitivity_of(frame, item, person, store) if item.constraints else item.sensitivity
    for rule in item.constraints:
        inherited = admissible(canon(frame, rule.about, memo), max(rule.sensitivity, own), person, aud,
                               told_by=canon(frame, rule.told_by, memo),
                               heard_by=canon(frame, rule.heard_by, memo), secret=rule.secret,
                               presumed=presumer(frame, memo))
        if not inherited.ok:
            return inherited
        inherited_rules.append(inherited)
    if inherited_rules:
        return Verdict(True, others=tuple(sorted({p for v in inherited_rules for p in v.others})),
                       tellers=tuple(sorted({p for v in inherited_rules for p in v.tellers})),
                       level=max(v.level for v in inherited_rules), secret=any(v.secret for v in inherited_rules),
                       witness=all(v.witness for v in inherited_rules))
    subjects = tuple(sorted({*item.about, *([item.holder] if item.holder else [])}))
    if item.testimonies:
        return hearing(frame, item, person, aud, memo, store)[0]
    return admissible(canon(frame, subjects, memo), sensitivity_of(frame, item, person, store), person, aud,
                      told_by=canon(frame, item.told_by, memo), heard_by=canon(frame, item.heard_by, memo),
                      secret=item.secret, presumed=presumer(frame, memo))


def hearing(frame: Frame, item: Item, person: str | None, aud: Audience, memo: dict[str, str],
            store: Any = None) -> tuple[Verdict, tuple[Testimony, ...]]:
    """Ce qu'une croyance permet ici, d'après ses témoignages (ADR 0080) : le verdict du témoignage qui la laisse
    dire — celui de l'interlocuteur d'abord (c'est sa fiche), puis le plus ouvert, puis de première main, puis le
    plus récent : elle l'attribue à ce témoin, sans laisser deviner les autres —, et tous ceux que cette audience
    peut entendre (pour la confiance). Aucun ne la laisse dire : le verdict du témoignage de la personne
    concernée, sinon du premier (ce qu'elle sait savoir, sans un mot)."""
    subjects = canon(frame, tuple(sorted({*item.about, *([item.holder] if item.holder else [])})), memo)
    # ce qui touche un sujet délicat du portrait d'une personne concernée est une confidence, quel qu'en soit le témoin
    delicate = sensitivity_of(frame, item, person, store) > item.sensitivity
    presumed = presumer(frame, memo)
    heard: list[tuple[Testimony, Verdict]] = []
    refused: list[tuple[Testimony, Verdict]] = []
    for t in item.testimonies:
        level = int(Sensitivity.CONFIDENCE) if delicate else t.sensitivity
        v = admissible(subjects, level, person, aud,
                       told_by=canon(frame, t.told_by, memo), heard_by=canon(frame, t.heard_by, memo),
                       secret=t.secret, presumed=presumed)
        (heard if v.ok else refused).append((t, v))
    speaking = [(t, v) for t, v in heard if t.speaks]
    if speaking:
        mine = [(t, v) for t, v in speaking if person is not None and person in canon(frame, t.told_by, memo)]
        first_hand = set(subjects)
        chosen = mine[0] if mine else min(speaking, key=lambda tv: (
            tv[1].level, tv[1].secret, not (set(tv[0].told_by) <= first_hand), -tv[0].at, tv[0].seq))
        return chosen[1], tuple(t for t, _v in heard)
    if not refused:
        return Verdict(False), ()
    own = [(t, v) for t, v in refused if t.speaks and set(t.told_by) <= set(subjects)]
    return (own or refused)[0][1], ()


def felt_here(frame: Frame, item: Item, person: str | None, aud: Audience, memo: dict[str, str],
              store: Any = None) -> tuple[tuple[str, float], ...]:
    """Ce que la personne concernée en ressent, tel que cette audience peut l'entendre (ADR 0083) : pour une croyance,
    seulement quand le témoignage qui l'a dit est de ceux qu'elle entend ici — la honte qu'Alice a confiée ne passe
    pas par la rumeur de Bob (ADR 0080). Un souvenir, qui n'a pas de témoignages, suit son propre verdict."""
    if not item.felt or not item.testimonies:
        return item.felt
    heard = hearing(frame, item, person, aud, memo, store)[1]
    return item.felt if item.felt_from in {t.seq for t in heard if t.speaks} else ()


def heard_confidence(frame: Frame, item: Item, person: str | None, aud: Audience, memo: dict[str, str],
                     store: Any = None) -> float | None:
    """Sa confiance devant cette audience : mise en commun sur les seuls témoignages qu'elle peut entendre — sinon
    le secret d'Alice la rendrait plus sûre devant Carol, qui n'en sait rien (ADR 0080)."""
    if not item.testimonies:
        return item.confidence
    verdict, heard = hearing(frame, item, person, aud, memo, store)
    if not verdict.ok:
        return item.confidence
    return pooled(heard) or item.confidence
