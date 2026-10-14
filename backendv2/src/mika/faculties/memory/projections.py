"""Les projections T0 de la mémoire (dans la transaction d'ajout) :

- ``memory_items`` : souvenirs, croyances, promesses, moments de la vie des
  autres, avec ce qui les fait durer (importance, renforcements, rappels),
  leur statut, et ce qui décide devant qui ils peuvent ressortir (qui l'a
  confié, qui l'a entendu, secret ou non) ;
- ``memory_chunks`` : les échanges bruts avec chacun (sa question, sa
  réponse), retrouvables sans que la consolidation ait décidé de les garder.

**Montré, ou dit.** Un élément montré dans un prompt n'est pas un élément
dont elle s'est servie : être montré date seulement l'anti-répétition
(``shown_at``) ; seul ce qu'elle a vraiment repris dans ce qu'elle a dit
(au moins deux radicaux en commun) compte comme un rappel, qui le fait durer.

L'oubli d'une personne efface ses lignes : ce qui la concerne, et ce qu'elle a confié.
Une projection reconstruite (sa version change) ne les fait pas revenir : un
élément dont le texte a été oublié ne se recopie pas.

**Tenir des années** (ADR 0059) : ``memory_items`` est indexée par sorte,
statut et naissance ; ``memory_about`` dit qui concerne chaque élément, une
personne par ligne (« ce qu'elle sait d'Alice » ne parcourt plus toute la
mémoire) ; ``memory_chunks`` est indexée par personne et par salon, dans le
temps (« ce que je t'ai dit lundi » se lit sur l'intervalle, jamais par la
liste de tous ses échanges) ; ``memory_forgets`` compte les oublis, pour que
l'index des vecteurs se rapproche de ce qui reste sans tout relire.

**Deux moteurs** (ADR 0101) : les tables se déclarent dans ``tables.py``, les écritures passent par SQLAlchemy
(``upsert`` pour ce qui remplaçait, ``insert_ignore`` pour ce qui ignorait un doublon, ``greatest`` / ``least`` pour le
``MAX(a, b)`` scalaire). « Cette liste JSON contient-elle ce sujet ? » est ``json_has`` : une égalité exacte, sensible
à la casse — le ``LIKE '%"sujet"%'`` d'avant ignorait la casse ASCII sous SQLite et prenait ``_`` et ``%`` d'une
adresse pour des jokers (``user_7`` attrapait ``userX7``). Ce que MariaDB refuse (une sous-requête sur la table qu'on
met à jour, ``INSERT … SELECT`` sur elle-même) se lit d'abord, puis s'écrit.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import delete, func, or_, select, update

from mika.contracts import mcp as mcp_c
from mika.contracts import memory as c
from mika.contracts import rss as rss_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.memory.extraction import IMPORTANCE
from mika.faculties.memory.faculty import MEMORY
from mika.faculties.memory.knowledge import Testimony, pooled
from mika.faculties.memory.tables import (
    CHANGES_TABLE,
    CONTESTS_TABLE,
    DEFERRED_TABLE,
    EMOTION,
    READING_COLUMNS,
    READINGS_TABLE,
    REFS_TABLE,
    TESTIMONIES_TABLE,
    TESTIMONY_COLUMNS,
    about,
    batches,
    changes,
    contests,
    deferred,
    feelings,
    forgets,
    handle_key,
    items,
    readings,
    refs,
    testimonies,
    told,
    told_lines,
)
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.codec import digest
from mika.kernel.faculty import Tier
from mika.ports.paging import fold_text
from mika.ports.sql import create_view, drop_view, fit, greatest, insert_ignore, json_has, least, upsert
from mika.ports.store import Sql
from mika.vocab.affect import FACET_DEFAULT, dominant, strip_prosody
from mika.vocab.words import WORD, fold, same_words, stems

ITEM_COLUMNS = ("id", "kind", "text", "about", "sensitivity", "importance", "confidence", "origin", "source",
                "emotion", "born_at", "touched_at", "recalled_at", "recalls", "status", "replaces", "recipient",
                "due", "sources", "told_by", "heard_by", "secret", "informants", "about_self", "shown_at", "between_us",
                "knowledge_kind", "holder", "constraints", "internal_only", "superseded_by", "as_of", "valid_until",
                "felt", "empathy", "until", "precision", "likelihood", "gist", "veiled", "felt_from")
CHUNK_TEXT_MAX = 600
#: un élément → ses émotions, de qui (``theirs`` : la personne concernée ; ``hers`` : elle) et à quelle intensité
#: (ADR 0083)
FEELINGS_TABLE = c.FEELINGS_TABLE
#: les événements qui créent un élément (et portent son texte)
_CREATES = frozenset({c.REMEMBERED.name, c.BELIEVED.name, c.PROMISE_NOTICED.name, c.EVENT_NOTED.name})
#: deux radicaux en commun entre ce qu'elle a dit et un élément montré : elle s'en est servie
USED_STEMS = 2


def _keys(values: Iterable[str]) -> str:
    return json.dumps(sorted({v for v in values if v}), ensure_ascii=False)


def _loads(raw: str | None) -> list[str]:
    try:
        got = json.loads(raw or "[]")
    except ValueError:
        return []
    return [str(x) for x in got] if isinstance(got, list) else []


def informants_of(source: str | None, told_by: Sequence[str]) -> tuple[str, ...]:
    """Qui le lui a appris : la source nommée, sinon ceux qui le lui ont confié.
    Une croyance redite par un informateur déjà compté n'en devient pas plus sûre."""
    return (source,) if source else tuple(sorted(set(told_by)))


def _testify(sql: Sql, sfx: str, item: int, seq: int, *, told_by: Sequence[str], informants: Sequence[str],
             origin: str | None, confidence: float | None, heard_by: Sequence[str], sensitivity: int, secret: bool,
             between_us: bool, sources: Sequence[int], at: int, speaks: bool = True, first_hand: bool = False) -> None:
    values = (item, seq, _keys(told_by), _keys(informants), origin or c.TOLD,
              0.5 if confidence is None else float(confidence), _keys(heard_by), int(sensitivity), int(secret),
              int(between_us), json.dumps(sorted(set(sources))), at, int(speaks), int(first_hand))
    upsert(sql, testimonies(sfx), dict(zip(TESTIMONY_COLUMNS, values, strict=True)), keys=["item", "seq"])


def _supersede(sql: Sql, sfx: str, old: int, new: int, at: int) -> None:
    """``new`` remplace ``old`` : ce qu'elle croyait ne l'est plus, et sait par quoi (ADR 0081) ; le doute qui
    portait sur l'ancienne n'a plus d'objet."""
    t, ct = items(sfx), contests(sfx)
    sql.execute(update(t).where(t.c.id == old).values(status="superseded", superseded_by=new, superseded_at=at))
    sql.execute(delete(ct).where(or_(ct.c.item == old, ct.c.other == old)))


def _contest(sql: Sql, sfx: str, item: int, other: int, at: int) -> None:
    upsert(sql, contests(sfx), [{"item": item, "other": other, "at": at}, {"item": other, "other": item, "at": at}],
           keys=["item", "other"])


def testimony_of(row: Sequence[Any]) -> Testimony:
    """Une ligne de ``memory_testimonies`` (``TESTIMONY_COLUMNS``)."""
    r = dict(zip(TESTIMONY_COLUMNS, row, strict=True))
    return Testimony(int(r["seq"]), tuple(_loads(r["told_by"])), tuple(_loads(r["heard_by"])), int(r["sensitivity"]),
                     bool(r["secret"]), float(r["confidence"]), tuple(_loads(r["informants"])), str(r["origin"]),
                     int(r["at"]), bool(r["between_us"]), bool(r["speaks"]), bool(r["first_hand"]))


def testimony_columns(sfx: str = "") -> list[Any]:
    """Les colonnes de ``memory_testimonies`` dans l'ordre de ``TESTIMONY_COLUMNS`` (ce que lit ``testimony_of``)."""
    tt = testimonies(sfx)
    return [tt.c[n] for n in TESTIMONY_COLUMNS]


def _testimonies(sql: Sql, sfx: str, item: int) -> list[Testimony]:
    tt = testimonies(sfx)
    rows = sql.query(select(*testimony_columns(sfx)).where(tt.c.item == item).order_by(tt.c.seq))
    return [testimony_of(r) for r in rows]


def _settle(sql: Sql, sfx: str, item: int) -> None:
    """L'enveloppe d'une croyance suit ses témoignages : qui le lui a appris (tous), et la confiance mise en commun de
    tous ses témoins (le rappel, lui, ne met en commun que ce que l'audience peut entendre)."""
    got = _testimonies(sql, sfx, item)
    if not got:
        return
    t, tt = items(sfx), testimonies(sfx)
    row = sql.query(select(t.c.about).where(t.c.id == item))
    concerned = set(_loads(row[0][0])) if row else set()
    if any(x.secret and set(x.told_by) & concerned for x in got) and not all(x.secret for x in got):
        # la discrétion demandée par la personne concernée ferme tout — ce qui était déjà dit, et ce qu'un autre en
        # dira ensuite (ADR 0080) : Bob qui le redit après « garde-le pour toi » d'Alice ne l'ouvre pas
        sql.execute(update(tt).where(tt.c.item == item).values(secret=1))
        sql.execute(update(t).where(t.c.id == item).values(secret=1))
        got = _testimonies(sql, sfx, item)
    informants = sorted({k for x in got for k in (x.informants or x.told_by)})
    sql.execute(update(t).where(t.c.id == item)
                .values(informants=json.dumps(informants, ensure_ascii=False), confidence=pooled(got)))


def forgotten(text: Any) -> bool:
    """Un texte oublié (relu après l'oubli de qui il concerne) : sa référence reste, plus son texte."""
    return text is not None and text.ref is not None and text.text is None


def _about_rows(sql: Sql, sfx: str, item: int, keys: Iterable[str]) -> None:
    insert_ignore(sql, about(sfx), [{"item": item, "person": k} for k in sorted({handle_key(k) for k in keys if k})])


def used(item_text: str, said: str) -> bool:
    """Elle s'en est servie : ce qu'elle a dit reprend l'élément (radicaux communs)."""
    return len(stems(item_text) & stems(said)) >= USED_STEMS


def fingerprint(text: str) -> str:
    return digest(WORD.findall(fold(text)))


#: les vues de la porte (``contracts.memory``) que ``memory_items`` porte ; ``RETOLD_VIEW`` est à ``memory_told``
VIEWS = (c.KNOWLEDGE_VIEW, c.KNOWLEDGE_ABOUT_VIEW, c.FORMER_VIEW, c.LEDGER_VIEW, c.FEELINGS_VIEW,
         c.SELF_CHANGES_VIEW, c.LIVED_VIEW)


def create_views(sql: Sql, sfx: str) -> None:
    """La porte de la mémoire (``contracts.memory``) : ce que les autres facultés lisent de ce qu'elle sait. Chaque
    vue est une requête compilée pour le moteur (``create_view``), créée après les tables qu'elle lit — MariaDB
    refuse une vue sur une table qui n'existe pas encore ; la vue de ce qu'elle a répété (``RETOLD_VIEW``) naît
    donc avec ``memory_told``, son propre projecteur."""
    t, ab, ft = items(sfx), about(sfx), feelings(sfx)
    known = [t.c[n] for n in c.KNOWN_COLUMNS]
    held = t.c.status.not_in(c.FORMER_STATUSES)
    create_view(sql, f"{c.KNOWLEDGE_VIEW}{sfx}", select(*known).where(held))
    a, i = ab.alias("a"), t.alias("i")
    create_view(sql, f"{c.KNOWLEDGE_ABOUT_VIEW}{sfx}",
                select(a.c.item.label("item"), a.c.person.label("person"))
                .select_from(a.join(i, i.c.id == a.c.item)).where(i.c.status.not_in(c.FORMER_STATUSES)))
    create_view(sql, f"{c.FORMER_VIEW}{sfx}", select(*known).where(t.c.status.in_(c.FORMER_STATUSES)))
    create_view(sql, f"{c.LEDGER_VIEW}{sfx}", select(*(t.c[n] for n in c.LEDGER_COLUMNS)))
    f = ft.alias("f")
    create_view(sql, f"{c.FEELINGS_VIEW}{sfx}",
                select(f.c.item.label("item"), f.c.whose.label("whose"), f.c.emotion.label("emotion"),
                       f.c.intensity.label("intensity"))
                .select_from(f.join(i, i.c.id == f.c.item)).where(i.c.status.not_in(c.FORMER_STATUSES)))
    o, n = t.alias("o"), t.alias("n")
    create_view(sql, f"{c.SELF_CHANGES_VIEW}{sfx}",
                select(o.c.id.label("was"), o.c.text.label("was_text"), n.c.id.label("item"), n.c.text.label("text"),
                       n.c.knowledge_kind.label("knowledge_kind"),
                       greatest(o.c.sensitivity, n.c.sensitivity).label("sensitivity"),
                       greatest(o.c.secret, n.c.secret).label("secret"), o.c.superseded_at.label("changed_at"))
                .select_from(o.join(n, n.c.id == o.c.superseded_by))
                .where(o.c.status == "superseded", o.c.about_self > 0, n.c.about_self > 0, n.c.status == "active",
                       o.c.internal_only == 0, n.c.internal_only == 0))
    create_view(sql, f"{c.LIVED_VIEW}{sfx}",
                select(*known, t.c.gist).where(t.c.kind == c.SOUVENIR, t.c.gist != "", held))


def _facets_json(felt: Any) -> str:
    return json.dumps([[e, x] for e, x in felt])


def _feel(sql: Sql, sfx: str, item: int, felt: Any, empathy: Any, emotion: str | None) -> None:
    """Relie un élément à ses émotions (ADR 0083) : ce que la personne en ressent (``theirs``), ce qu'elle-même en
    ressent (``hers`` — sa seule émotion pour un souvenir d'avant les facettes)."""
    ft = feelings(sfx)
    sql.execute(delete(ft).where(ft.c.item == item))
    hers = [tuple(f) for f in empathy] or ([(emotion, FACET_DEFAULT)] if emotion else [])
    rows = [{"item": item, "whose": whose, "emotion": fit(str(e), EMOTION), "intensity": float(x)}
            for whose, facets in ((c.THEIRS, felt), (c.HERS, hers)) for e, x in facets]
    upsert(sql, ft, rows, keys=["item", "whose", "emotion"])


#: ce qu'un élément inséré porte quand l'événement ne le dit pas
_ITEM_DEFAULTS: dict[str, Any] = {
    "confidence": None, "origin": None, "source": None, "emotion": None, "recalled_at": 0, "recalls": 0,
    "replaces": None, "recipient": None, "due": None, "told_by": "[]", "heard_by": "[]", "secret": 0,
    "informants": "[]", "about_self": 0, "shown_at": 0, "between_us": 0, "knowledge_kind": "claim", "holder": None,
    "constraints": "[]", "internal_only": 0, "superseded_by": None, "superseded_at": None, "as_of": None,
    "valid_until": None, "felt": "[]", "empathy": "[]", "until": None, "precision": "", "likelihood": None, "gist": "",
    "veiled": "", "felt_from": None}
#: ce qu'on relit d'un élément pour le renforcer, le fondre ou le joindre
_ROW_COLUMNS = ("about", "told_by", "heard_by", "informants", "sensitivity", "secret", "importance", "sources", "text",
                "constraints", "internal_only", "felt", "empathy", "emotion", "between_us")


class Items:
    def create(self, sql: Sql, sfx: str) -> None:
        sql.create(items(sfx), about(sfx), refs(sfx), changes(sfx), forgets(sfx), testimonies(sfx), contests(sfx),
                   feelings(sfx))
        ft = forgets(sfx)
        if not sql.query(select(ft.c.id).limit(1)):
            sql.execute(ft.insert().values(id=1, n=0))
        create_views(sql, sfx)

    def drop(self, sql: Sql, sfx: str) -> None:
        for view in VIEWS:
            drop_view(sql, f"{view}{sfx}")
        sql.drop(items(sfx), about(sfx), forgets(sfx), refs(sfx), changes(sfx), testimonies(sfx), contests(sfx),
                 feelings(sfx))

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        t = items(sfx)
        columns = (*ITEM_COLUMNS, "superseded_at", "fingerprint", "folded")

        def insert(row: dict[str, Any]) -> None:
            # « insérer ou remplacer » : toute la ligne, ``superseded_at`` compris (remis à rien, comme le faisait
            # ``INSERT OR REPLACE``)
            full = {**_ITEM_DEFAULTS, **row}
            full["fingerprint"] = fingerprint(full["text"])
            full["folded"] = fold_text(full["text"])
            upsert(sql, t, {k: full[k] for k in columns}, keys=["id"])
            _about_rows(sql, sfx, int(full["id"]), _loads(full["about"]))
            _feel(sql, sfx, int(full["id"]), json.loads(full["felt"]), json.loads(full["empathy"]), full["emotion"])

        for e in events:
            d = e.data
            name = e.type.name
            changed = set()
            if name in _CREATES:
                changed.add(e.seq)
            for attr in ("item", "replaces", "promise", "event"):
                if (item_id := getattr(d, attr, None)) is not None:
                    changed.add(item_id)
            if name == c.NIGHT_SORTED.name:
                changed.update(i for pair in d.merges for i in pair)
            if name == c.JOINED.name:
                changed.update(i for pair in d.pairs for i in pair)
            if name == c.CONFRONTED.name:
                changed.update(i for pair in (*d.supersedes, *d.contests) for i in pair)
            upsert(sql, changes(sfx), [{"item": i, "seq": e.seq} for i in sorted(changed)], keys=["item"])
            if name in _CREATES and forgotten(d.text):
                continue  # relu après un oubli (une reconstruction) : ce qui a été oublié ne revient pas
            if name in _CREATES and d.text is not None and d.text.ref:
                # la référence de son texte : l'oubli d'une personne rattachée depuis (un renfort) l'atteint aussi
                upsert(sql, refs(sfx), {"item": e.seq, "ref": d.text.ref}, keys=["item"])
            if name == c.REMEMBERED.name:
                insert({"id": e.seq, "kind": c.SOUVENIR, "text": d.text.text or "", "about": _keys(d.about),
                        "sensitivity": d.sensitivity, "importance": d.importance,
                        "born_at": e.at, "touched_at": e.at, "status": "active", "sources": json.dumps(list(d.sources)),
                        "told_by": _keys(d.told_by), "heard_by": _keys(d.heard_by), "secret": int(d.secret),
                        "constraints": json.dumps([rule.model_dump() for rule in d.constraints]),
                        "internal_only": int(d.internal_only), "origin": c.LIED if d.lie else None,
                        "emotion": d.emotion or dominant(d.empathy), "felt": _facets_json(d.felt),
                        "empathy": _facets_json(d.empathy), "gist": (d.gist.text or "") if d.gist else "",
                        "veiled": (d.veiled.text or "") if d.veiled else ""})
            elif name == c.BELIEVED.name:
                insert({"id": e.seq, "kind": c.BELIEF, "text": d.text.text or "", "about": _keys(d.about),
                        "sensitivity": d.sensitivity, "importance": d.importance, "confidence": d.confidence,
                        "origin": d.origin, "source": d.source, "born_at": e.at, "touched_at": e.at,
                        "status": "active", "replaces": d.replaces, "sources": json.dumps(list(d.sources)),
                        "told_by": _keys(d.told_by), "heard_by": _keys(d.heard_by), "secret": int(d.secret),
                        "informants": _keys(informants_of(d.source, d.told_by)),
                        # 1 : ce qu'elle raconte d'elle, qui s'efface ; 2 : ce qui la définit (un goût, un avis), qui tient
                        "about_self": 2 if d.durable else int(d.about_self), "between_us": int(d.between_us),
                        "knowledge_kind": d.knowledge_kind, "holder": d.holder,
                        "as_of": d.as_of if d.as_of is not None else e.at, "valid_until": d.valid_until,
                        "emotion": dominant(d.empathy), "felt": _facets_json(d.felt),
                        "empathy": _facets_json(d.empathy), "due": d.expected, "until": d.expected_until,
                        "precision": d.expected_precision, "likelihood": d.likelihood,
                        "veiled": (d.veiled.text or "") if d.veiled else "",
                        # ce que la personne en ressent vient de ce premier témoignage (ADR 0083)
                        "felt_from": e.seq if d.felt else None})
                # le premier témoignage : comment elle l'a appris la première fois (ADR 0080)
                _testify(sql, sfx, e.seq, e.seq, told_by=d.told_by, informants=informants_of(d.source, d.told_by),
                         origin=d.origin, confidence=d.confidence, heard_by=d.heard_by, sensitivity=d.sensitivity,
                         secret=d.secret, between_us=d.between_us, sources=d.sources, at=e.at,
                         first_hand=d.first_hand)
                if d.replaces is not None:
                    _supersede(sql, sfx, d.replaces, e.seq, e.at)
                if d.contests is not None:
                    _contest(sql, sfx, e.seq, d.contests, e.at)
            elif name == c.PROMISE_NOTICED.name:
                insert({"id": e.seq, "kind": c.PROMISE, "text": d.text.text or "", "about": _keys([d.to]),
                        "sensitivity": d.sensitivity, "importance": 0.6, "born_at": e.at, "touched_at": e.at,
                        "status": "pending", "recipient": d.to, "due": d.due, "sources": json.dumps(list(d.sources))})
            elif name == c.EVENT_NOTED.name:
                insert({"id": e.seq, "kind": c.EVENT, "text": d.text.text or "", "about": _keys(d.about),
                        "sensitivity": d.sensitivity, "importance": d.importance, "born_at": e.at, "touched_at": e.at,
                        "status": "active", "due": d.when, "replaces": d.replaces,
                        "sources": json.dumps(list(d.sources)), "told_by": _keys(d.told_by),
                        "heard_by": _keys(d.heard_by), "secret": int(d.secret), "emotion": dominant(d.empathy),
                        "felt": _facets_json(d.felt), "empathy": _facets_json(d.empathy), "until": d.until,
                        "precision": d.precision, "likelihood": d.likelihood})
                if d.replaces is not None:
                    sql.execute(update(t).where(t.c.id == d.replaces, t.c.kind == c.EVENT).values(status="superseded"))
            elif name == c.PROMISE_RESOLVED.name:
                sql.execute(update(t).where(t.c.id == d.promise).values(status=d.status, touched_at=e.at))
            elif name == c.SITUATION_ENDED.name:
                sql.execute(update(t).where(t.c.id == d.event).values(status="ended", touched_at=e.at))
            elif name == c.REINFORCED.name:
                self._reinforce(sql, sfx, d, e.at)
                self._reinforce_testimonies(sql, sfx, d, e.seq, e.at)
            elif name == c.ATTESTED.name:
                self._attest(sql, sfx, d, e.seq, e.at)
            elif name == c.JOINED.name:
                for keep, drop in d.pairs:
                    self._join(sql, sfx, keep, drop, e.at, mute=d.mute)
            elif name == c.CONFRONTED.name:
                # la nuit a confronté deux témoins sur la même personne (ADR 0085)
                for new, old in d.supersedes:
                    _supersede(sql, sfx, old, new, e.at)
                for a, b in d.contests:
                    _contest(sql, sfx, a, b, e.at)
            elif name == c.RESOLVED.name and d.nature == c.PREDICTION:
                # une prévision constatée (ADR 0099) : de l'histoire — elle ne se montre plus à constater
                sql.execute(update(t).where(t.c.id == d.event, t.c.kind == c.BELIEF)
                            .values(status="resolved", touched_at=e.at))
            elif name == c.DELICATE.name:
                # un sujet délicat de la personne : une confidence, pour tous ses témoignages (ADR 0099)
                tt = testimonies(sfx)
                for item in d.items:
                    sql.execute(update(t).where(t.c.id == item)
                                .values(sensitivity=greatest(t.c.sensitivity, int(d.level))))
                    sql.execute(update(tt).where(tt.c.item == item)
                                .values(sensitivity=greatest(tt.c.sensitivity, int(d.level))))
            elif name == SUBJECT_FORGOTTEN.name:
                self._forget_testimonies(sql, sfx, d.subject)
            elif name == c.NIGHT_SORTED.name:
                for keep, drop in d.merges:
                    self._merge(sql, sfx, keep, drop, e.at)
            elif name == rt.UTTERANCE.name:
                self._uttered(sql, sfx, d, e.at)

    @staticmethod
    def _row(sql: Sql, sfx: str, item: int) -> dict[str, Any] | None:
        t = items(sfx)
        got = sql.query(select(*(t.c[k] for k in _ROW_COLUMNS)).where(t.c.id == item))
        if not got:
            return None
        return dict(zip(_ROW_COLUMNS, got[0], strict=True))

    def _reinforce(self, sql: Sql, sfx: str, d: Any, at: int) -> None:
        """Ce qui revient dure plus longtemps ; il garde la plus haute
        sensibilité, et les personnes, confidents et témoins s'unissent."""
        row = self._row(sql, sfx, d.item)
        if row is None:
            return
        t = items(sfx)
        sens = max(int(row["sensitivity"]), int(d.sensitivity)) if d.sensitivity is not None else int(row["sensitivity"])
        informants = _loads(row["informants"])
        if d.source or d.told_by:
            informants = [*informants, *informants_of(d.source, d.told_by)]
        sql.execute(update(t).where(t.c.id == d.item).values(
            # Un ancien renfort peut avoir été fondé sur une simple similarité. En rejouant le journal,
            # il ne doit pas élargir les permissions du texte conservé.
            sensitivity=sens, about=_keys([*_loads(row["about"]), *d.about]), told_by=row["told_by"],
            heard_by=row["heard_by"], secret=int(bool(row["secret"]) or d.secret), informants=_keys(informants),
            sources=json.dumps(sorted({*map(int, _loads(row["sources"])), *d.sources}))))
        if not d.restricts:
            # ce qui revient dure plus longtemps — une discrétion demandée ferme sans rien redire : ni plus
            # d'importance, ni un oubli remis à zéro
            sql.execute(update(t).where(t.c.id == d.item)
                        .values(touched_at=at, importance=least(1.0, t.c.importance + 0.05)))
        _about_rows(sql, sfx, d.item, d.about)
        if d.corroborated:
            sql.execute(update(t).where(t.c.id == d.item)
                        .values(confidence=least(0.95, func.coalesce(t.c.confidence, 0.5) + 0.1)))
        if d.between_us:
            sql.execute(update(t).where(t.c.id == d.item).values(between_us=1))
        if d.replaces is not None and d.replaces != d.item:
            _supersede(sql, sfx, d.replaces, d.item, at)

    @staticmethod
    def _reinforce_testimonies(sql: Sql, sfx: str, d: Any, seq: int, at: int) -> None:
        """Un ancien renforcement d'une croyance (d'avant les témoignages) : sa discrétion et sa sensibilité valent pour
        tous ses témoignages ; corroboré, il compte un témoin de plus pour la confiance — un témoignage **muet**, qui
        n'ouvre aucune diffusion (il pouvait reposer sur une simple ressemblance)."""
        first = _testimonies(sql, sfx, d.item)
        if not first:
            return  # un souvenir, ou une croyance oubliée
        if d.secret or d.sensitivity is not None:
            tt = testimonies(sfx)
            sql.execute(update(tt).where(tt.c.item == d.item)
                        .values(secret=greatest(tt.c.secret, int(d.secret)),
                                sensitivity=greatest(tt.c.sensitivity, int(d.sensitivity or 0))))
        if d.corroborated:
            base = first[0]
            _testify(sql, sfx, d.item, seq, told_by=base.told_by, informants=informants_of(d.source, d.told_by),
                     origin=c.TOLD, confidence=0.8, heard_by=base.heard_by, sensitivity=base.sensitivity,
                     secret=base.secret, between_us=base.between_us, sources=d.sources, at=at, speaks=False)
        _settle(sql, sfx, d.item)

    def _attest(self, sql: Sql, sfx: str, d: Any, seq: int, at: int) -> None:
        """Un témoignage de plus — ou une discrétion demandée : sur le témoignage de qui la demande, ou sur tous
        quand c'est la personne concernée (ADR 0080)."""
        row = self._row(sql, sfx, d.item)
        if row is None:
            return  # oubliée entre-temps
        t, tt = items(sfx), testimonies(sfx)
        mine = _keys(d.told_by)
        if d.restricts:
            for got in _testimonies(sql, sfx, d.item):
                if d.everyone or set(got.told_by) & set(d.told_by) or (not got.told_by and not d.told_by):
                    sql.execute(update(tt).where(tt.c.item == d.item, tt.c.seq == got.seq)
                                .values(secret=1, sensitivity=greatest(tt.c.sensitivity, int(d.sensitivity))))
            sql.execute(update(t).where(t.c.id == d.item)
                        .values(secret=1, sensitivity=greatest(t.c.sensitivity, int(d.sensitivity))))
        else:
            informants = _keys(informants_of(d.source, d.told_by))
            # le plus ancien d'abord : deux témoignages identiques ne se départagent pas au hasard du moteur
            same = sql.query(select(tt.c.seq, tt.c.sources)
                             .where(tt.c.item == d.item, tt.c.told_by == mine, tt.c.informants == informants,
                                    tt.c.heard_by == _keys(d.heard_by), tt.c.secret == int(d.secret),
                                    tt.c.between_us == int(d.between_us), tt.c.speaks == 1)
                             .order_by(tt.c.seq))
            testimony = seq
            if same:
                # la même personne, de la même façon, de la même source : elle le redit — la date et les messages,
                # rien de plus sûr
                kept_seq, kept_sources = same[0]
                testimony = int(kept_seq)
                sql.execute(update(tt).where(tt.c.item == d.item, tt.c.seq == kept_seq).values(
                    at=at, sources=json.dumps(sorted({*map(int, _loads(kept_sources)), *d.sources})),
                    confidence=greatest(tt.c.confidence, d.confidence),
                    sensitivity=greatest(tt.c.sensitivity, int(d.sensitivity))))
            else:
                _testify(sql, sfx, d.item, seq, told_by=d.told_by, informants=informants_of(d.source, d.told_by),
                         origin=d.origin, confidence=d.confidence, heard_by=d.heard_by, sensitivity=d.sensitivity,
                         secret=d.secret, between_us=d.between_us, sources=d.sources, at=at,
                         first_hand=d.first_hand)
            if d.secret:
                # ce qu'une personne demande de garder pour soi vaut pour tout ce qu'elle en a dit
                sql.execute(update(tt).where(tt.c.item == d.item, tt.c.told_by == mine).values(secret=1))
            if d.about_self and d.durable:
                # une anecdote redite comme ce qui la définit le devient (ADR 0087)
                sql.execute(update(t).where(t.c.id == d.item, t.c.about_self == 1).values(
                    about_self=2, importance=greatest(t.c.importance, IMPORTANCE[3]),
                    knowledge_kind=func.coalesce(d.knowledge_kind, t.c.knowledge_kind)))
            sql.execute(update(t).where(t.c.id == d.item).values(
                touched_at=at, importance=least(1.0, t.c.importance + 0.05),
                sensitivity=greatest(t.c.sensitivity, int(d.sensitivity)), secret=greatest(t.c.secret, int(d.secret)),
                about=_keys([*_loads(row["about"]), *d.about]),
                sources=json.dumps(sorted({*map(int, _loads(row["sources"])), *d.sources})),
                between_us=greatest(t.c.between_us, int(d.between_us))))
            _about_rows(sql, sfx, d.item, d.about)
            if d.felt and (not json.loads(row["felt"] or "[]") or set(d.told_by) & set(_loads(row["about"]))):
                # ce que la personne en ressent : son mot à elle l'emporte sur celui d'un autre (ADR 0083) — et l'on
                # sait de quel témoignage il vient : il ne se dit que là où ce témoignage peut s'entendre
                sql.execute(update(t).where(t.c.id == d.item).values(felt=_facets_json(d.felt), felt_from=testimony))
                _feel(sql, sfx, d.item, [list(f) for f in d.felt], json.loads(row["empathy"] or "[]"), row["emotion"])
        if d.replaces is not None and d.replaces != d.item:
            # ce qu'elle croyait, redit, revient (ADR 0081) : la croyance qui l'avait remplacée le cède
            sql.execute(update(t).where(t.c.id == d.item, t.c.status == "superseded")
                        .values(status="active", superseded_by=None, superseded_at=None))
            _supersede(sql, sfx, d.replaces, d.item, at)
        if d.contests is not None and d.contests != d.item:
            _contest(sql, sfx, d.item, d.contests, at)
        _settle(sql, sfx, d.item)

    def _join(self, sql: Sql, sfx: str, keep: int, drop: int, at: int, *, mute: bool = False) -> None:
        """La nuit, la même croyance dite par un autre (un doublon d'avant les témoignages) devient un témoignage de
        la gardée : ses témoignages passent, l'enveloppe garde le plus strict de chacune. ``mute`` : d'autres mots,
        jugés la même chose — ses témoignages passent muets (la confiance, jamais la diffusion, ADR 0085)."""
        a, b = self._row(sql, sfx, keep), self._row(sql, sfx, drop)
        if a is None or b is None:
            return
        t, tt = items(sfx), testimonies(sfx)
        sql.execute(update(tt).where(tt.c.item == drop).values(item=keep, **({"speaks": 0} if mute else {})))
        sql.execute(update(t).where(t.c.id == keep).values(
            importance=max(float(a["importance"]), float(b["importance"])),
            sensitivity=max(int(a["sensitivity"]), int(b["sensitivity"])),
            secret=int(bool(a["secret"]) or bool(b["secret"])), about=_keys([*_loads(a["about"]), *_loads(b["about"])]),
            sources=json.dumps(sorted({*map(int, _loads(a["sources"])), *map(int, _loads(b["sources"]))})),
            touched_at=greatest(t.c.touched_at, at),
            # ce qui n'appartenait qu'à elles dans la jointe le reste dans la gardée (lu avant : MariaDB refuse une
            # sous-requête sur la table qu'on met à jour)
            between_us=greatest(t.c.between_us, int(b["between_us"]))))
        _about_rows(sql, sfx, keep, _loads(b["about"]))
        sql.execute(update(t).where(t.c.id == drop).values(status="joined"))
        _settle(sql, sfx, keep)

    @staticmethod
    def _forget_testimonies(sql: Sql, sfx: str, subject: str) -> None:
        """Un témoin oublié emporte son témoignage — y compris quand la projection se reconstruit (le journal rejoue
        ses témoignages, puis son oubli)."""
        tt = testimonies(sfx)
        named = or_(json_has(tt.c.told_by, subject), json_has(tt.c.informants, subject))
        touched = sorted({int(i) for (i,) in sql.query(select(tt.c.item).distinct().where(named))})
        sql.execute(delete(tt).where(named))
        for item in touched:
            _settle(sql, sfx, item)

    def _merge(self, sql: Sql, sfx: str, keep: int, drop: int, at: int) -> None:
        """La nuit, un souvenir se fond dans un autre : le gardé prend le plus
        haut de chaque et l'union des personnes — une confidence fondue dans un
        souvenir anodin reste une confidence."""
        a, b = self._row(sql, sfx, keep), self._row(sql, sfx, drop)
        if a is None or b is None or any(a[k] != b[k] for k in ("about", "told_by", "heard_by", "secret", "constraints",
                                                                 "internal_only")):
            return  # même lors du rejeu d'un ancien journal, aucune permission ne s'élargit
        if not same_words(a["text"], b["text"]):
            return  # une négation ou un détail différent ne disparaît pas dans un quasi-doublon
        t = items(sfx)
        # les messages de l'un et de l'autre : une discrétion demandée sur ceux du fondu atteint le gardé
        sql.execute(update(t).where(t.c.id == keep).values(
            importance=max(float(a["importance"]), float(b["importance"])),
            sensitivity=max(int(a["sensitivity"]), int(b["sensitivity"])),
            about=_keys([*_loads(a["about"]), *_loads(b["about"])]),
            told_by=_keys([*_loads(a["told_by"]), *_loads(b["told_by"])]),
            heard_by=_keys([*_loads(a["heard_by"]), *_loads(b["heard_by"])]),
            secret=int(bool(a["secret"]) or bool(b["secret"])), touched_at=at,
            sources=json.dumps(sorted({*map(int, _loads(a["sources"])), *map(int, _loads(b["sources"]))}))))
        _about_rows(sql, sfx, keep, _loads(b["about"]))
        sql.execute(update(t).where(t.c.id == drop).values(status="merged"))

    @staticmethod
    def _uttered(sql: Sql, sfx: str, d: Any, at: int) -> None:
        ids = sorted({int(p.split(":", 1)[1]) for p in d.provenance if p.startswith("memory:") and p[7:].isdigit()})
        if not ids:
            return
        t = items(sfx)
        sql.execute(update(t).where(t.c.id.in_(ids)).values(shown_at=at))
        said = strip_prosody(d.text.text or "")
        if not said:
            return
        rows = sql.query(select(t.c.id, t.c.text).where(t.c.id.in_(ids)))
        hits = sorted(int(i) for i, text in rows if used(text or "", said))
        if hits:
            sql.execute(update(t).where(t.c.id.in_(hits))
                        .values(recalls=t.c.recalls + 1, recalled_at=at, touched_at=at))

    def forget(self, sql: Sql, subject: str, sfx: str) -> list[str]:
        t, ab, rf = items(sfx), about(sfx), refs(sfx)
        doomed = [int(i) for (i,) in sql.query(
            select(t.c.id).where(or_(t.c.id.in_(select(ab.c.item).where(ab.c.person == handle_key(subject))),
                                     json_has(t.c.told_by, subject), t.c.recipient == subject,
                                     t.c.holder == subject)).order_by(t.c.id))]
        refs_out: list[str] = []
        for chunk in batches(doomed):
            refs_out += [str(r) for (r,) in sql.query(select(rf.c.ref).where(rf.c.item.in_(chunk))
                                                      .order_by(rf.c.item))]
            sql.execute(delete(t).where(t.c.id.in_(chunk)))
            sql.execute(delete(ab).where(ab.c.item.in_(chunk)))
            sql.execute(delete(rf).where(rf.c.item.in_(chunk)))
            for table in (changes(sfx), testimonies(sfx), feelings(sfx)):
                sql.execute(delete(table).where(table.c.item.in_(chunk)))
            ct = contests(sfx)
            sql.execute(delete(ct).where(or_(ct.c.item.in_(chunk), ct.c.other.in_(chunk))))
        self._forget_testimonies(sql, sfx, subject)
        # l'index des vecteurs saura qu'il a quelque chose à oublier (``memory.index``)
        ft = forgets(sfx)
        sql.execute(update(ft).values(n=ft.c.n + 1))
        # qui l'a seulement entendu (un salon) ou appris en passant : son nom s'efface des listes
        for column in ("heard_by", "informants"):
            for item, raw in sql.query(select(t.c.id, t.c[column]).where(json_has(t.c[column], subject))
                                       .order_by(t.c.id)):
                sql.execute(update(t).where(t.c.id == item)
                            .values({column: _keys(k for k in _loads(raw) if k != subject)}))
        sql.execute(update(t).where(t.c.source == subject).values(source=None))
        # un élément qu'on lui a rattaché par un renfort ne nomme pas toujours ce sujet dans son texte : le magasin
        # efface ces textes-là aussi (sinon une reconstruction le ferait revenir — audit du lot L2 du 2026-10-03)
        return refs_out


def _joined(texts: Iterable[str | None]) -> str:
    """Les messages d'un tour, à la suite (« salut / t'as vu le match ? / allo ? »), bornés à
    ``CHUNK_TEXT_MAX`` : au-delà, chacun garde sa part plutôt que le premier mange tout."""
    parts = [" ".join(t.split()) for t in texts if t and t.strip()]
    if not parts:
        return ""
    joined = " / ".join(parts)
    if len(joined) <= CHUNK_TEXT_MAX:
        return joined
    share = max(40, CHUNK_TEXT_MAX // len(parts) - 3)
    return " / ".join(p if len(p) <= share else p[: share - 1] + "…" for p in parts)[:CHUNK_TEXT_MAX]


class Chunks:
    """T0 : un échange par réponse visible — ce qu'on lui a dit (tout le tour) et ce qu'elle a répondu."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.create(c.chunks_table(sfx))

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.drop(c.chunks_table(sfx))

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        t, thread = c.chunks_table(sfx), transcript_c.thread_table()
        for e in events:
            d = e.data
            if not d.visible or not d.target or d.reply_to is None or forgotten(d.text):
                continue
            # une réponse règle tout le tour (``answers`` : « salut », « t'as vu le match ? », « allo ? ») ; la
            # question n'est souvent pas le dernier message — l'échange les garde tous, dans l'ordre (un journal
            # d'avant le tour : ``reply_to`` seul)
            asked = tuple(sorted({*d.answers, d.reply_to}))
            rows = sql.query(select(thread.c.text).where(thread.c.id.in_(asked)).order_by(thread.c.id))
            user_text = _joined(t for (t,) in rows)
            reply = strip_prosody(d.text.text or "")[:CHUNK_TEXT_MAX]
            upsert(sql, t, {"id": e.seq, "person": handle_key(d.target), "question": asked[0], "user_text": user_text,
                            "reply_text": reply, "at": e.at, "room": handle_key(d.room) if d.room else d.room},
                   keys=["id"])

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        t = c.chunks_table(sfx)
        sql.execute(delete(t).where(t.c.person == handle_key(subject)))


class Told:
    """À qui elle a répété quoi : ce que montrait le prompt d'un énoncé adressé
    à quelqu'un (sa provenance). Ce qu'elle a raconté à Bob, Bob le sait — et,
    dans le doute, ce qu'on lui a montré pour parler à Bob compte comme dit :
    c'est la règle de qui ferme (un lien, une preuve d'identité). Pour un récit
    sans nom, chaque énoncé qui le montrait est gardé (``TOLD_LINES_TABLE``) :
    ce qu'elle a vraiment dit s'y juge à la lecture, sur sa réponse (ADR 0092).
    Ce qu'elle a lu pour quelqu'un en conversation, elle le lui a dit sur le
    moment : la croyance qu'elle en garde la nuit compte comme dite à qui
    l'a entendue (ADR 0110).
    La vue de la porte (``RETOLD_VIEW``) naît et meurt avec ces tables."""

    def create(self, sql: Sql, sfx: str) -> None:
        tt = told(sfx)
        sql.create(tt, told_lines(sfx))
        create_view(sql, f"{c.RETOLD_VIEW}{sfx}", select(tt.c.item, tt.c.handle, tt.c.at, tt.c.veiled))

    def drop(self, sql: Sql, sfx: str) -> None:
        drop_view(sql, f"{c.RETOLD_VIEW}{sfx}")
        sql.drop(told(sfx), told_lines(sfx))

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        tt, tl = told(sfx), told_lines(sfx)
        rows: list[tuple[int, str, int, int]] = []
        lines: list[tuple[int, str, int, int]] = []
        for e in events:
            d = e.data
            if e.type.name == c.JOINED.name:
                # ce qu'elle avait raconté de la jointe, elle l'a raconté de la gardée (lu, puis écrit : MariaDB
                # n'insère pas dans une table ce qu'il y lit)
                for keep, drop in d.pairs:
                    got = sql.query(select(tt.c.handle, tt.c.at, tt.c.veiled).where(tt.c.item == drop))
                    insert_ignore(sql, tt, [{"item": keep, "handle": h, "at": at, "veiled": v} for h, at, v in got])
                    got = sql.query(select(tl.c.handle, tl.c.utterance, tl.c.at).where(tl.c.item == drop))
                    insert_ignore(sql, tl, [{"item": keep, "handle": h, "utterance": u, "at": at} for h, u, at in got])
                continue
            if e.type.name in (c.BELIEVED.name, c.ATTESTED.name):
                if d.origin == c.READ:
                    item = e.seq if e.type.name == c.BELIEVED.name else int(d.item)
                    rows += [(item, handle_key(h), e.at, 0) for h in d.heard_by if h]
                continue
            if not d.visible or not d.target:
                continue
            target = handle_key(d.target)
            rows += [(int(p.split(":", 1)[1]), target, e.at, 0) for p in d.provenance
                     if p.startswith("memory:") and p[7:].isdigit()]
            # raconté sans nommer personne (ADR 0091) : compté à part — une fois nommé, il reste nommé
            veiled = [(int(p.split(":", 1)[1]), target, e.at, 1) for p in d.provenance
                      if p.startswith(c.VEILED_PROVENANCE) and p[len(c.VEILED_PROVENANCE):].isdigit()]
            rows += veiled
            lines += [(item, handle, e.seq, at) for item, handle, at, _ in veiled]
        if lines:
            insert_ignore(sql, tl, [{"item": i, "handle": h, "utterance": u, "at": at} for i, h, u, at in lines])
        if rows:
            # la dernière fois qu'elle l'a dit ; nommé une fois, nommé pour de bon (le plus petit ``veiled``, celui
            # de la table compris)
            merged: dict[tuple[int, str], tuple[int, int]] = {}
            for item, handle, at, v in rows:
                was = merged.get((item, handle))
                merged[(item, handle)] = (at, v if was is None else min(was[1], v))
            for chunk in batches(sorted({item for item, _h in merged})):
                for item, handle, v in sql.query(select(tt.c.item, tt.c.handle, tt.c.veiled)
                                                 .where(tt.c.item.in_(chunk))):
                    if (key := (int(item), str(handle))) in merged:
                        merged[key] = (merged[key][0], min(merged[key][1], int(v)))
            upsert(sql, tt, [{"item": i, "handle": h, "at": at, "veiled": v} for (i, h), (at, v) in merged.items()],
                   keys=["item", "handle"], update=["at", "veiled"])

    def forget(self, sql: Sql, subject: str, sfx: str) -> None:
        tt, tl = told(sfx), told_lines(sfx)
        sql.execute(delete(tt).where(tt.c.handle == handle_key(subject)))
        sql.execute(delete(tl).where(tl.c.handle == handle_key(subject)))


# v3 : ce qui n'appartient qu'à elle et à la personne (``between_us`` : un surnom, une blague à elles, ADR 0055)
# v4 : index (sorte, statut, naissance), ``memory_about``, ``memory_forgets`` ; l'oublié ne revient pas (ADR 0059)
# v5 : ``memory_refs`` (élément → référence de son texte) : l'oubli d'une personne rattachée par un renfort l'efface
# v9 : les vues de la porte (``contracts.memory`` : ``KNOWLEDGE_VIEW``…), seules lues hors de la mémoire
# v10 : les témoignages d'une croyance (``memory_testimonies``, ADR 0080) ; l'oubli d'un témoin les suit au rejeu
# v11 : « remplacée par » (``superseded_by``), depuis et jusqu'à quand c'est vrai, les contestations
# (``memory_contests``), la première main d'un témoignage, ce qu'elle croyait qui revient (ADR 0081)
# v12 : ce que chacun en ressent (``felt``, ``empathy``) et ses liens aux émotions (``memory_feelings``, ADR 0083)
# v13 : la période d'un moment, ce qu'attend une prévision et sa vraisemblance (ADR 0084)
# v14 : la nuit confronte deux témoins (``memory.confronted``) ; la discrétion de la personne concernée reste fermée
# pour ce qu'un autre en dira ensuite (ADR 0085)
# v15 : une note sur elle redite comme ce qui la définit le devient (``Attested.durable``) ; un moment vécu à travers
# quelqu'un garde son « en bref » sans personne (``gist``) ; vues ``memory_self_changes``, ``memory_lived`` (ADR 0087)
# v16 : la même chose, racontée sans qu'on puisse reconnaître la personne (``veiled``, ADR 0091)
# v17 : ce qui touche un sujet délicat d'une personne est une confidence, à la porte (``memory.delicate``, ADR 0099)
# v18 : une prévision constatée (``memory.resolved``, sorte « prévision ») n'est plus à constater (ADR 0099)
# v19 : de quel témoignage vient ce que la personne en ressent (``felt_from``) ; une discrétion demandée ne renforce
# pas (``Reinforced.restricts``) ; un souvenir fondu la nuit garde aussi les messages de l'autre (``sources``)
# v20 : les tables déclarées pour les deux moteurs (ADR 0101) ; ``folded`` (le texte replié que cherche la console)
MEMORY.projector(c.ITEMS_TABLE, version=20, tier=Tier.T0,
                 types=[*c.ALL, rt.UTTERANCE, SUBJECT_FORGOTTEN])(Items)
# v3 : l'échange garde tout le tour (``Utterance.answers``), pas seulement le dernier message d'une rafale
# v4 : index (personne, instant) et (salon, instant) ; l'oublié ne revient pas (ADR 0059)
# v5 : la table déclarée pour les deux moteurs (ADR 0101)
MEMORY.projector(c.CHUNKS_TABLE, version=5, tier=Tier.T0, types=[rt.UTTERANCE])(Chunks)
# v2 : une croyance jointe la nuit (ADR 0080) : ce qu'elle en avait raconté passe à la gardée
# v3 : ce qu'elle a raconté sans nommer personne (``veiled``, ADR 0091)
# v4 : chaque énoncé qui lui montrait un récit sans nom (``memory_told_lines``) : raconté se juge sur sa réponse
# v5 : les tables déclarées pour les deux moteurs (ADR 0101) ; la vue ``memory_retold`` naît avec elles
# v6 : ce qu'elle a lu pour quelqu'un en conversation compte comme dit à qui l'a entendu (ADR 0110)
MEMORY.projector(c.TOLD_TABLE, version=6, tier=Tier.T0,
                 types=[rt.UTTERANCE, c.JOINED, c.BELIEVED, c.ATTESTED])(Told)


#: ce qu'une extraction remise à plus tard réécrit (``since`` : la première fois, gardée)
_DEFERRED_UPDATE = ("messages", "about", "attempts", "retry_at", "status", "reason", "detail_ref", "aside")


class ExtractionQueue:
    def create(self, sql: Sql, sfx: str) -> None:
        sql.create(deferred(sfx))

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.drop(deferred(sfx))

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        t = deferred(sfx)
        for e in events:
            d = e.data
            if d.status == "resolved" or forgotten(d.detail):
                sql.execute(delete(t).where(t.c.key == d.key))
                continue
            upsert(sql, t, {"key": d.key, "messages": json.dumps(d.messages), "about": _keys(d.about),
                            "attempts": d.attempts, "retry_at": d.retry_at, "status": d.status,
                            "reason": d.failure_code, "detail_ref": d.detail.ref or "", "since": e.at,
                            "aside": json.dumps(sorted(d.aside))}, keys=["key"], update=_DEFERRED_UPDATE)

    def forget(self, sql: Sql, subject: str, sfx: str) -> list[str]:
        t = deferred(sfx)
        rows = sql.query(select(t.c.key, t.c.detail_ref).where(json_has(t.c.about, subject)).order_by(t.c.key))
        for chunk in batches([key for key, _ in rows]):
            sql.execute(delete(t).where(t.c.key.in_(chunk)))
        return [ref for _, ref in rows]


# v2 : ``aside`` (ce qui, dans un salon, ne lui était pas adressé), relu tel quel à la reprise
# v3 : la table déclarée pour les deux moteurs (ADR 0101)
MEMORY.projector(DEFERRED_TABLE, version=3, tier=Tier.T0, types=[c.EXTRACTION_DEFERRED])(ExtractionQueue)


class Readings:
    """Ses lectures (``rss.read``, ``mcp.consulted``), en attendant la relecture de la nuit (``memory.reread``) :
    relues, elles s'effacent — ce qu'elle en a gardé est dans ce qu'elle sait."""

    def create(self, sql: Sql, sfx: str) -> None:
        sql.create(readings(sfx))

    def drop(self, sql: Sql, sfx: str) -> None:
        sql.drop(readings(sfx))

    def apply(self, sql: Sql, events: Sequence[Any], sfx: str) -> None:
        t = readings(sfx)
        for e in events:
            d = e.data
            if e.type.name == c.REREAD.name:
                sql.execute(delete(t).where(t.c.seq <= d.upto))
                continue
            if forgotten(d.title):
                continue
            upsert(sql, t, dict(zip(READING_COLUMNS, (
                e.seq, d.source[:200], d.ref[:500], d.title.ref or "",
                (d.excerpt.ref or "") if d.excerpt is not None else "", d.depth, e.at, d.asked_by[:200]), strict=True)),
                   keys=["seq"])


# v2 : la table déclarée pour les deux moteurs (ADR 0101)
# v3 : lu en conversation, pour quelqu'un (``asked_by``, ADR 0110)
MEMORY.projector(READINGS_TABLE, version=3, tier=Tier.T0,
                 types=[rss_c.READ, mcp_c.CONSULTED, c.REREAD])(Readings)

__all__ = [
    "CHANGES_TABLE", "CONTESTS_TABLE", "DEFERRED_TABLE", "FEELINGS_TABLE", "ITEM_COLUMNS", "READINGS_TABLE",
    "READING_COLUMNS", "REFS_TABLE", "TESTIMONIES_TABLE", "TESTIMONY_COLUMNS", "Chunks", "ExtractionQueue", "Items",
    "Readings", "Told", "create_views", "fingerprint", "forgotten", "informants_of", "testimony_columns",
    "testimony_of", "used",
]
