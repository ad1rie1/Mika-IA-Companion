"""Graphe durable des relations explicites ; cache de travail rechargé à la rencontre."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from sqlalchemy import delete, or_, select, update

from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import social as c
from mika.faculties.social.faculty import SOCIAL
from mika.kernel.faculty import Tier
from mika.ports.sql import HANDLE_MAX, fit, json_has, upsert
from mika.vocab.people import is_identifiable


class Relations:
    def create(self, sql, sfx):
        sql.create(c.relations_table(sfx))

    def drop(self, sql, sfx):
        sql.drop(c.relations_table(sfx))

    def apply(self, sql, events, sfx):
        t = c.relations_table(sfx)
        for e in events:
            d = e.data
            if e.type.name == memory_c.JOINED.name:
                # une croyance jointe la nuit : ses liens passent à la gardée (ADR 0080)
                for keep, drop in d.pairs:
                    for subject, key, data in _rows(sql, t, drop):
                        _rewrite(sql, t, subject, key, {**data, "item": keep}, item=keep)
                continue
            if d.replaces is not None:
                sql.execute(delete(t).where(t.c.item == d.replaces))
            if e.type.name == memory_c.ATTESTED.name and d.secret:
                # la discrétion demandée : ce qu'en a dit qui la demande — tout, quand c'est la personne concernée
                told = set(d.told_by)
                for subject, key, data in _rows(sql, t, d.item):
                    if d.everyone or set(data.get("told_by") or []) & told:
                        _rewrite(sql, t, subject, key, {**data, "secret": True})
            if e.type.name == memory_c.REINFORCED.name:
                # la croyance d'où vient le lien devient un secret : le lien aussi (il ouvre les confidences, ADR 0058)
                if d.secret:
                    for subject, key, data in _rows(sql, t, d.item):
                        _rewrite(sql, t, subject, key, {**data, "secret": True})
                continue
            attested = e.type.name == memory_c.ATTESTED.name
            if not attested and not d.text.text:
                continue
            for relation in d.relations:
                subject, other = relation.subject, relation.other
                if subject == other or not is_identifiable(subject) or not is_identifiable(other):
                    continue
                holder = getattr(d, "holder", None)
                status = "uncertain" if getattr(d, "knowledge_kind", "claim") == "hypothesis" else relation.status
                about = tuple(sorted({*d.about, *([holder] if holder else [])}))
                item = d.item if attested else e.seq
                edge = c.KnownRelation(other, relation.kind, status, item, e.at,
                                       tuple(d.told_by), tuple(d.sources), d.secret, about)
                key = c.relation_key(other, relation.kind, d.told_by)
                upsert(sql, t, {"subject": fit(subject, HANDLE_MAX), "key": fit(key, c.RELATION_KEY_MAX),
                                "other": fit(other, HANDLE_MAX), "item": item, "payload": json.dumps(asdict(edge))},
                       keys=["subject", "key"])

    def forget(self, sql, subject, sfx):
        t = c.relations_table(sfx)
        key = fit(subject, HANDLE_MAX)
        sql.execute(delete(t).where(or_(t.c.subject == key, t.c.other == key,
                                        json_has(t.c.payload, subject, "$.about"),
                                        json_has(t.c.payload, subject, "$.told_by"))))


def _rows(sql: Any, t: Any, item: int) -> list[tuple[str, str, dict[str, Any]]]:
    """Les liens d'un élément, leur charge utile décodée : lus d'abord, réécrits ensuite par leur clé (pas de
    sous-requête sur la table qu'on modifie ; la charge se recompose en Python — ``json_set`` ne s'écrit pas pareil
    sur les deux moteurs)."""
    return [(subject, key, json.loads(raw))
            for subject, key, raw in sql.query(select(t.c.subject, t.c.key, t.c.payload).where(t.c.item == item))]


def _rewrite(sql: Any, t: Any, subject: str, key: str, data: dict[str, Any], **more: Any) -> None:
    sql.execute(update(t).where(t.c.subject == subject, t.c.key == key).values(payload=json.dumps(data), **more))


# Un renforcement remplace une croyance ou la rend secrète : l'archive le suit, sinon le lien retiré revient à la
# rencontre suivante (audit du 2026-10-08)
# v3 : un lien suit chaque témoignage, et passe à la gardée d'une jointure (ADR 0080) ; déclarée pour les deux
# moteurs (ADR 0101) sous les mêmes colonnes : pas de reconstruction
SOCIAL.projector(c.RELATIONS_TABLE, version=3, tier=Tier.T0,
                 types=[memory_c.BELIEVED, memory_c.REINFORCED, memory_c.ATTESTED, memory_c.JOINED])(Relations)


@SOCIAL.interpret(rt.PERCEPTION_RECEIVED)
def recall_relations(s, frame, ev, ports):
    store = ports.get("store") if ports else None
    if store is None:
        return []
    person = frame.get(identity_c.PERSON(ev.data.handle)) or ev.data.handle
    keys = sorted({fit(k, HANDLE_MAX) for k in (person, ev.data.handle, *frame.get(identity_c.HANDLES(person)))})
    t = c.relations_table()
    # départagés par la clé : plusieurs liens d'un même élément, toujours les mêmes sous la borne
    rows = store.query_mind(select(t.c.subject, t.c.payload)
                            .where(or_(t.c.other.in_(keys), t.c.subject.in_(keys)))
                            .order_by(t.c.item.desc(), t.c.subject, t.c.key).limit(512))
    edges = []
    for subject, raw in rows:
        data = json.loads(raw)
        for field in ("about", "told_by", "sources"):
            data[field] = tuple(data[field])
        edge = c.KnownRelation(**data)
        key = c.relation_key(edge.other, edge.kind, edge.told_by)  # exacte, même au-delà de la borne de la colonne
        if (s.relations.get(subject) or {}).get(key) != edge:
            edges.append((subject, key, edge))
    return [c.RELATIONS_RECALLED.draft(edges=tuple(edges))] if edges else []
