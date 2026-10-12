"""Les sujets délicats, à la porte (ADR 0099).

Ce qu'elle sait d'une personne et qui touche un de ses sujets délicats (son portrait : « sa rupture », « sa santé »)
est une confidence, quoi qu'en ait dit la consolidation. Le rappel le recalculait seul, à chaque tour ; ses pensées
(une croyance révisée), ses buts, son journal lisaient la porte de la mémoire et n'en savaient rien. Ce processus le
pose dans la mémoire même (``memory.delicate``) : les nouveaux éléments à leur arrivée, tous ceux d'une personne quand
son portrait change. Jamais abaissé : un sujet que le portrait ne dit plus ne rouvre rien.
"""

from __future__ import annotations

import functools
from typing import Any

from sqlalchemy import bindparam, select

from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import social as social_c
from mika.faculties.memory.faculty import MEMORY
from mika.faculties.memory.recall import delicate_topics, person_of, touches
from mika.faculties.memory.tables import about, handle_key, items
from mika.kernel.codec import h64
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.ports.sql import Prepared, alias_of
from mika.vocab.privacy import Sensitivity

#: les éléments examinés au plus par passage (les plus récents d'abord)
BATCH = 2000


@MEMORY.process("memory.delicate", wake_on=[c.REMEMBERED, c.BELIEVED, c.ATTESTED, c.EVENT_NOTED,
                                           social_c.PROFILE_REVISED],
                lane="background", catch_up=CatchUp.ONCE, max_quantum_s=3600)
class Delicate:
    def __init__(self) -> None:
        #: le dernier élément examiné ; le portrait d'après lequel chaque personne a été relue (ses sujets délicats)
        self.items_upto = 0
        self.portraits: dict[str, tuple[Any, ...]] = {}

    def next_due(self, state: Any, frame: Frame, last_run: int | None) -> int | None:
        return frame.now if frame.seq > self.items_upto else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        store = ctx.ports.get("store")
        upto, self.items_upto = self.items_upto, frame.seq
        if store is None:
            return
        found: dict[str, set[int]] = {}
        topics: dict[str, tuple[str, ...]] = {}

        def examine(rows: Any) -> None:
            for key, item, text in rows:
                person = person_of(frame, str(key))
                if not person:
                    continue
                if person not in topics:
                    topics[person] = delicate_topics(frame, person, store)
                if touches(str(text or ""), topics[person]):
                    found.setdefault(person, set()).add(int(item))

        recent, of_people = _queries()
        # ce qui vient d'arriver, de qui que ce soit (jamais toute la mémoire à chaque passage)
        examine(store.query_mind(recent, {"upto": upto}))
        # et tout ce qui concerne une personne dont le portrait a changé (ses adresses comprises)
        for person in frame.get(social_c.DELICATE_PEOPLE) or ():
            portrait = (tuple(frame.get(social_c.SENSITIVE(person))), frame.get(social_c.SENSITIVE_REF(person)))
            if self.portraits.get(person, ((), "")) == portrait:
                continue
            self.portraits[person] = portrait
            keys = sorted({handle_key(k) for k in (person, *(frame.get(identity_c.HANDLES(person)) or ()))})
            examine(store.query_mind(of_people, {"keys": keys}))
        drafts = [c.DELICATE.draft(person=person, items=tuple(sorted(ids)), level=int(Sensitivity.CONFIDENCE),
                                   dedupe_key=f"délicat:{person}:{h64(*sorted(ids))}")
                  for person, ids in sorted(found.items())]
        if drafts:
            await ctx.emit(*drafts)


@functools.cache
def _queries() -> tuple[Prepared, Prepared]:
    """Les deux lectures du processus, préparées une fois (il passe à chaque élément retenu) : ce qui est arrivé depuis
    ``upto``, et ce qui concerne ces adresses — les plus récents d'abord, départagés par la personne (un lot coupé
    l'est au même endroit sur les deux moteurs)."""
    a, i = alias_of(about(), "a"), alias_of(items(), "i")
    base = (select(a.c.person, i.c.id, i.c.text).select_from(a.join(i, i.c.id == a.c.item))
            .where(i.c.status.in_(("active", "pending")), i.c.sensitivity < int(Sensitivity.CONFIDENCE))
            .order_by(i.c.id.desc(), a.c.person).limit(BATCH))
    return (Prepared(base.where(i.c.id > bindparam("upto"))),
            Prepared(base.where(a.c.person.in_(bindparam("keys", expanding=True)))))
