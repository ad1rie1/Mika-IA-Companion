"""Situations et dates durables ; la tranche n'en est qu'un cache d'attention."""
from __future__ import annotations

import json
from dataclasses import asdict, replace

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.faculties.memory.faculty import MEMORY, cached, params
from mika.kernel.clock import DAY
from mika.kernel.faculty import CatchUp, Tier
from mika.vocab.affect import facets


def decode(raw: str) -> c.LifeEvent:
    data = json.loads(raw)
    return c.LifeEvent(**{**data, "about": tuple(data["about"]), "told_by": tuple(data["told_by"]),
                          "felt": facets(data.get("felt")), "empathy": facets(data.get("empathy"))})


class LifeArchive:
    def create(self, sql, sfx):
        t = c.LIFE_TABLE + sfx
        sql.execute(f"CREATE TABLE IF NOT EXISTS {t}(id INTEGER PRIMARY KEY, payload TEXT NOT NULL, "
                    "when_at INTEGER NOT NULL, yearly INTEGER NOT NULL, ongoing INTEGER NOT NULL, "
                    "ended_at INTEGER NOT NULL, ordinal INTEGER NOT NULL, thread INTEGER NOT NULL DEFAULT 0)")
        sql.execute(f"CREATE INDEX IF NOT EXISTS {t}_thread ON {t}(thread)")
        sql.execute(f"CREATE INDEX IF NOT EXISTS {t}_due ON {t}(yearly,when_at)")
        sql.execute(f"CREATE INDEX IF NOT EXISTS {t}_year ON {t}(yearly,ordinal)")

    def drop(self, sql, sfx):
        sql.execute(f"DROP TABLE IF EXISTS {c.LIFE_TABLE}{sfx}")

    def apply(self, sql, events, sfx):
        t = c.LIFE_TABLE + sfx
        for e in events:
            d = e.data
            if e.type.name == c.EVENT_NOTED.name:
                previous = sql.query(f"SELECT payload FROM {t} WHERE id=?", (d.replaces,)) if d.replaces else []
                old = decode(previous[0][0]) if previous else None
                origin = d.replaces if d.replaces is not None else d.recurs
                was = sql.query(f"SELECT payload FROM {t} WHERE id=?", (origin,)) if origin is not None else []
                thread = (decode(was[0][0]).key if was else origin) if origin is not None else e.seq
                for gone in (d.replaces, d.recurs):
                    if gone is not None:
                        sql.execute(f"DELETE FROM {t} WHERE id=?", (gone,))
                if not d.text.text:
                    continue
                item = c.life_event_of(e.seq, d, followed_at=old.followed_at if old and old.when == d.when else 0,
                                       ended_at=old.ended_at if old and old.ongoing and d.ongoing else 0,
                                       thread=thread)
            else:
                previous = sql.query(f"SELECT payload FROM {t} WHERE id=?", (d.event,))
                if not previous and e.type.name in (c.MOMENT_FOLLOWED.name, c.RESOLVED.name) and d.thread:
                    # repris sous un numéro remplacé depuis : le moment tel qu'il est noté maintenant, s'il est à la
                    # même date (ADR 0079). Une issue (``resolved``) ne dit pas d'occurrence : le numéro remplacé
                    # l'a été le même jour (précisé, redit de première main) — un moment déplacé à un autre jour a
                    # déjà reçu la sienne (``moved``, même clé de dédoublonnage), comme dans la tranche
                    occurrence = d.occurrence if e.type.name == c.MOMENT_FOLLOWED.name else 0
                    previous = [r for r in sql.query(f"SELECT payload FROM {t} WHERE thread=?", (d.thread,))
                                if not occurrence or decode(r[0]).when == occurrence or decode(r[0]).yearly]
                if not previous:
                    continue
                item = decode(previous[0][0])
                if e.type.name == c.RESOLVED.name:
                    if item.outcome:
                        continue  # tranché une fois pour toutes (ADR 0086)
                    item = replace(item, outcome=d.outcome, resolved_at=e.at)
                elif e.type.name == c.MOMENT_FOLLOWED.name:
                    item = replace(item, followed_at=e.at)
                else:
                    item = replace(item, ended_at=item.ended_at or e.at)
            sql.execute(f"INSERT OR REPLACE INTO {t} VALUES(?,?,?,?,?,?,"
                        "CAST(strftime('%j',?/1000000,'unixepoch') AS INTEGER),?)",
                        (item.id, json.dumps(asdict(item)), item.ends, int(item.yearly), int(item.ongoing),
                         item.ended_at, item.when, item.key))

    def forget(self, sql, subject, sfx):
        t = c.LIFE_TABLE + sfx
        sql.execute(f"DELETE FROM {t} WHERE EXISTS(SELECT 1 FROM json_each(payload,'$.about') WHERE value=?) "
                    "OR EXISTS(SELECT 1 FROM json_each(payload,'$.told_by') WHERE value=?)", (subject, subject))


# v2 : le fil de chaque moment (``thread``) : reporté, redit, revenu, le même ; un suivi sous un ancien numéro
# retrouve le moment tel qu'il est noté maintenant (ADR 0079). v3 : ce que chacun en ressent (ADR 0083). v4 : une
# période (``when_at`` : sa fin, pour que le calendrier la recharge tant qu'elle dure), le monde, le partage, la
# vraisemblance (ADR 0084). v5 : comment il a tourné (``outcome``, ADR 0086)
MEMORY.projector(c.LIFE_TABLE, version=5, tier=Tier.T0,
                 types=[c.EVENT_NOTED, c.MOMENT_FOLLOWED, c.SITUATION_ENDED, c.RESOLVED])(LifeArchive)


def for_people(store, people, limit=256):
    if not people:
        return []
    marks = ','.join('?' for _ in people)
    return [decode(raw) for (raw,) in store.query_mind(
        f"SELECT payload FROM {c.LIFE_TABLE} WHERE id IN (SELECT item FROM {c.ABOUT_TABLE} WHERE person IN ({marks})) "
        "ORDER BY when_at DESC,id DESC LIMIT ?", (*people, limit))]


@MEMORY.interpret(rt.PERCEPTION_RECEIVED)
def recall_life(s, frame, ev, ports):
    store = ports.get("store") if ports else None
    if store is None:
        return []
    person = frame.get(identity_c.PERSON(ev.data.handle)) or ev.data.handle
    keys = tuple(sorted({person, ev.data.handle, *frame.get(identity_c.HANDLES(person))}))
    # seulement ce que la tranche garderait : un moment passé depuis longtemps, rechargé, en sortirait au prochain
    # moment noté — et reviendrait dans le journal au message suivant
    p = params(frame.env.params_of("memory", frame.root))
    items = tuple(item for item in for_people(store, keys)
                  if cached(item, ev.at, p) and s.events.get(item.id) != item)
    return [c.LIFE_RECALLED.draft(items=items)] if items else []


@MEMORY.process("memory.calendar", wake_on=[c.EVENT_NOTED], lane="background", catch_up=CatchUp.ONCE,
                max_quantum_s=3600)
class Calendar:
    def next_due(self, state, frame, last_run):
        return max(frame.now, state.life_refreshed_at + DAY) if state.life_seen else None

    async def run(self, ctx):
        store, frame, state = ctx.ports.get("store"), ctx.frame, ctx.state
        if store is None:
            return
        # Les prochaines dates, même si personne n'en a reparlé depuis des années.
        ordinary = store.query_mind(f"SELECT payload FROM {c.LIFE_TABLE} WHERE yearly=0 AND when_at>=? "
                                    "ORDER BY when_at,id LIMIT 256", (frame.now - 7 * DAY,))
        ordinal = int(frame.local().strftime("%j"))
        # Deux parcours d'index plutôt qu'un tri de toutes les dates annuelles.
        yearly = store.query_mind(f"SELECT payload FROM {c.LIFE_TABLE} WHERE yearly=1 AND ordinal>=? "
                                  "ORDER BY ordinal,id LIMIT 256", (ordinal - 2,))
        yearly += store.query_mind(f"SELECT payload FROM {c.LIFE_TABLE} WHERE yearly=1 AND ordinal<? "
                                   "ORDER BY ordinal,id LIMIT ?", (ordinal - 2, 256 - len(yearly)))
        # Seulement ce que le cache n'a pas déjà tel quel : le journal ne recopie pas chaque jour les mêmes dates.
        items = tuple(item for item in (decode(raw) for (raw,) in ordinary + yearly) if state.events.get(item.id) != item)
        await ctx.emit(c.LIFE_RECALLED.draft(items=items, daily=True))
