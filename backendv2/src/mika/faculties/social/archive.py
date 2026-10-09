"""Graphe durable des relations explicites ; cache de travail rechargé à la rencontre."""
from __future__ import annotations

import json
from dataclasses import asdict

from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import social as c
from mika.faculties.social.faculty import SOCIAL
from mika.kernel.faculty import Tier
from mika.vocab.people import is_identifiable


class Relations:
    def create(self, sql, sfx):
        t = c.RELATIONS_TABLE + sfx
        sql.execute(f"CREATE TABLE IF NOT EXISTS {t}(subject TEXT NOT NULL, key TEXT NOT NULL, other TEXT NOT NULL, "
                    "item INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(subject,key))")
        sql.execute(f"CREATE INDEX IF NOT EXISTS {t}_other ON {t}(other,item)")
        sql.execute(f"CREATE INDEX IF NOT EXISTS {t}_item ON {t}(item)")

    def drop(self, sql, sfx):
        sql.execute(f"DROP TABLE IF EXISTS {c.RELATIONS_TABLE}{sfx}")

    def apply(self, sql, events, sfx):
        t = c.RELATIONS_TABLE + sfx
        for e in events:
            d = e.data
            if e.type.name == memory_c.JOINED.name:
                # une croyance jointe la nuit : ses liens passent à la gardée (ADR 0080)
                for keep, drop in d.pairs:
                    sql.execute(f"UPDATE {t} SET item=?, payload=json_set(payload,'$.item',?) WHERE item=?",
                                (keep, keep, drop))
                continue
            if d.replaces is not None:
                sql.execute(f"DELETE FROM {t} WHERE item=?", (d.replaces,))
            if e.type.name == memory_c.ATTESTED.name and d.secret:
                # la discrétion demandée : ce qu'en a dit qui la demande — tout, quand c'est la personne concernée
                for (key, item, raw) in sql.query(f"SELECT key, item, payload FROM {t} WHERE item=?", (d.item,)):
                    told = set(json.loads(raw).get("told_by") or [])
                    if d.everyone or told & set(d.told_by):
                        sql.execute(f"UPDATE {t} SET payload=json_set(payload,'$.secret',json('true')) "
                                    "WHERE key=? AND item=?", (key, item))
            if e.type.name == memory_c.REINFORCED.name:
                # la croyance d'où vient le lien devient un secret : le lien aussi (il ouvre les confidences, ADR 0058)
                if d.secret:
                    sql.execute(f"UPDATE {t} SET payload=json_set(payload,'$.secret',json('true')) WHERE item=?",
                                (d.item,))
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
                key = f"{other}|{relation.kind}|{','.join(sorted(d.told_by))}"
                sql.execute(f"INSERT OR REPLACE INTO {t} VALUES(?,?,?,?,?)",
                            (subject, key, other, item, json.dumps(asdict(edge))))

    def forget(self, sql, subject, sfx):
        t = c.RELATIONS_TABLE + sfx
        sql.execute(f"DELETE FROM {t} WHERE subject=? OR other=? OR "
                    "EXISTS(SELECT 1 FROM json_each(payload,'$.about') WHERE value=?) OR "
                    "EXISTS(SELECT 1 FROM json_each(payload,'$.told_by') WHERE value=?)",
                    (subject, subject, subject, subject))


# Un renforcement remplace une croyance ou la rend secrète : l'archive le suit, sinon le lien retiré revient à la
# rencontre suivante (audit du 2026-10-08)
# v3 : un lien suit chaque témoignage, et passe à la gardée d'une jointure (ADR 0080)
SOCIAL.projector(c.RELATIONS_TABLE, version=3, tier=Tier.T0,
                 types=[memory_c.BELIEVED, memory_c.REINFORCED, memory_c.ATTESTED, memory_c.JOINED])(Relations)


@SOCIAL.interpret(rt.PERCEPTION_RECEIVED)
def recall_relations(s, frame, ev, ports):
    store = ports.get("store") if ports else None
    if store is None:
        return []
    person = frame.get(identity_c.PERSON(ev.data.handle)) or ev.data.handle
    keys = tuple(sorted({person, ev.data.handle, *frame.get(identity_c.HANDLES(person))}))
    marks = ','.join('?' for _ in keys)
    rows = store.query_mind(f"SELECT subject,key,payload FROM {c.RELATIONS_TABLE} "
                            f"WHERE other IN ({marks}) OR subject IN ({marks}) ORDER BY item DESC LIMIT 512",
                            (*keys, *keys))
    edges = []
    for subject, key, raw in rows:
        data = json.loads(raw)
        for field in ("about", "told_by", "sources"):
            data[field] = tuple(data[field])
        edge = c.KnownRelation(**data)
        if (s.relations.get(subject) or {}).get(key) != edge:
            edges.append((subject, key, edge))
    return [c.RELATIONS_RECALLED.draft(edges=tuple(edges))] if edges else []
