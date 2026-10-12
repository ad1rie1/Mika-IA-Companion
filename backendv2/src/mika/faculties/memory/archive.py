"""Situations et dates durables ; la tranche n'en est qu'un cache d'attention.

``memory_life`` garde chaque moment en JSON (``payload``) avec ce qui le cherche : sa date (``when_at``), s'il revient
chaque année (``yearly``) et son jour de l'année (``ordinal``, calculé ici en UTC — le ``strftime('%j', …,
'unixepoch')`` d'avant n'existe pas sous MariaDB)."""
from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.faculties.memory.faculty import MEMORY, cached, params
from mika.faculties.memory.tables import about, handle_key, life
from mika.kernel.clock import DAY
from mika.kernel.faculty import CatchUp, Tier
from mika.ports.sql import json_has, upsert
from mika.vocab.affect import facets

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
LIFE_COLUMNS = ("id", "payload", "when_at", "yearly", "ongoing", "ended_at", "ordinal", "thread")


def decode(raw: str) -> c.LifeEvent:
    data = json.loads(raw)
    return c.LifeEvent(**{**data, "about": tuple(data["about"]), "told_by": tuple(data["told_by"]),
                          "felt": facets(data.get("felt")), "empathy": facets(data.get("empathy"))})


def ordinal_of(when: int) -> int:
    """Le jour de l'année (1 à 366, en UTC) d'un instant en microsecondes ; 0 pour un instant hors du calendrier."""
    try:
        return (_EPOCH + timedelta(microseconds=int(when))).timetuple().tm_yday
    except (OverflowError, ValueError, TypeError):
        return 0


class LifeArchive:
    def create(self, sql, sfx):
        sql.create(life(sfx))

    def drop(self, sql, sfx):
        sql.drop(life(sfx))

    def apply(self, sql, events, sfx):
        t = life(sfx)

        def payload(item_id):
            return sql.query(select(t.c.payload).where(t.c.id == item_id))

        for e in events:
            d = e.data
            if e.type.name == c.EVENT_NOTED.name:
                previous = payload(d.replaces) if d.replaces else []
                old = decode(previous[0][0]) if previous else None
                origin = d.replaces if d.replaces is not None else d.recurs
                was = payload(origin) if origin is not None else []
                thread = (decode(was[0][0]).key if was else origin) if origin is not None else e.seq
                for gone in (d.replaces, d.recurs):
                    if gone is not None:
                        sql.execute(delete(t).where(t.c.id == gone))
                if not d.text.text:
                    continue
                item = c.life_event_of(e.seq, d, followed_at=old.followed_at if old and old.when == d.when else 0,
                                       ended_at=old.ended_at if old and old.ongoing and d.ongoing else 0,
                                       thread=thread)
            else:
                previous = payload(d.event)
                if not previous and e.type.name in (c.MOMENT_FOLLOWED.name, c.RESOLVED.name) and d.thread:
                    # repris sous un numéro remplacé depuis : le moment tel qu'il est noté maintenant, s'il est à la
                    # même date (ADR 0079). Une issue (``resolved``) ne dit pas d'occurrence : le numéro remplacé
                    # l'a été le même jour (précisé, redit de première main) — un moment déplacé à un autre jour a
                    # déjà reçu la sienne (``moved``, même clé de dédoublonnage), comme dans la tranche
                    occurrence = d.occurrence if e.type.name == c.MOMENT_FOLLOWED.name else 0
                    previous = [r for r in sql.query(select(t.c.payload).where(t.c.thread == d.thread).order_by(t.c.id))
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
            upsert(sql, t, dict(zip(LIFE_COLUMNS, (
                item.id, json.dumps(asdict(item)), item.ends, int(item.yearly), int(item.ongoing), item.ended_at,
                ordinal_of(item.when), item.key), strict=True)), keys=["id"])

    def forget(self, sql, subject, sfx):
        t = life(sfx)
        sql.execute(delete(t).where(or_(json_has(t.c.payload, subject, "$.about"),
                                        json_has(t.c.payload, subject, "$.told_by"))))


# v2 : le fil de chaque moment (``thread``) : reporté, redit, revenu, le même ; un suivi sous un ancien numéro
# retrouve le moment tel qu'il est noté maintenant (ADR 0079). v3 : ce que chacun en ressent (ADR 0083). v4 : une
# période (``when_at`` : sa fin, pour que le calendrier la recharge tant qu'elle dure), le monde, le partage, la
# vraisemblance (ADR 0084). v5 : comment il a tourné (``outcome``, ADR 0086). v6 : la table déclarée pour les deux
# moteurs (ADR 0101) ; le jour de l'année calculé ici, en UTC
MEMORY.projector(c.LIFE_TABLE, version=6, tier=Tier.T0,
                 types=[c.EVENT_NOTED, c.MOMENT_FOLLOWED, c.SITUATION_ENDED, c.RESOLVED])(LifeArchive)


def for_people(store, people, limit=256):
    if not people:
        return []
    t, ab = life(), about()
    keys = sorted({handle_key(p) for p in people})
    return [decode(raw) for (raw,) in store.query_mind(
        select(t.c.payload).where(t.c.id.in_(select(ab.c.item).where(ab.c.person.in_(keys))))
        .order_by(t.c.when_at.desc(), t.c.id.desc()).limit(limit))]


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
        t = life()
        # Les prochaines dates, même si personne n'en a reparlé depuis des années.
        ordinary = store.query_mind(select(t.c.payload).where(t.c.yearly == 0, t.c.when_at >= frame.now - 7 * DAY)
                                    .order_by(t.c.when_at, t.c.id).limit(256))
        ordinal = int(frame.local().strftime("%j"))
        # Deux parcours d'index plutôt qu'un tri de toutes les dates annuelles.
        yearly = store.query_mind(select(t.c.payload).where(t.c.yearly == 1, t.c.ordinal >= ordinal - 2)
                                  .order_by(t.c.ordinal, t.c.id).limit(256))
        yearly += store.query_mind(select(t.c.payload).where(t.c.yearly == 1, t.c.ordinal < ordinal - 2)
                                   .order_by(t.c.ordinal, t.c.id).limit(256 - len(yearly)))
        # Seulement ce que le cache n'a pas déjà tel quel : le journal ne recopie pas chaque jour les mêmes dates.
        items = tuple(item for item in (decode(raw) for (raw,) in ordinary + yearly) if state.events.get(item.id) != item)
        await ctx.emit(c.LIFE_RECALLED.draft(items=items, daily=True))
