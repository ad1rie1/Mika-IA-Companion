"""Le port d'entrée, implémenté sur le noyau : ce que voient les adaptateurs."""

from __future__ import annotations

from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import presence as presence_c
from mika.contracts import social as social_c
from mika.contracts.entry import Admission, HistoryRow
from mika.contracts.runtime import PerceptionReceived
from mika.faculties import transcript
from mika.faculties.identity import describe
from mika.kernel.events import Origin
from mika.kernel.frame import Frame
from mika.runtime.bootstrap import Kernel, ReadOnlyStore


def _row(r: dict) -> HistoryRow:
    return HistoryRow(
        id=r["id"], at=r["at"], role=r["role"], text=r["text"], source=r["source"] or "",
        emotion=r["emotion"], emotion_intensity=r["emotion_intensity"], attachments=r["attachments"] or "[]",
    )


class KernelPort:
    def __init__(self, kernel: Kernel) -> None:
        self.kernel = kernel
        self._store = ReadOnlyStore(kernel.deps.store)

    async def perceive(self, p: PerceptionReceived, *, dedupe_key: str | None = None) -> Admission:
        got = await self.kernel.perceive(p, dedupe_key=dedupe_key)
        if got.overloaded:
            return Admission("overloaded")
        return Admission("accepted", got.seq, duplicate=bool(got.commit and got.commit.deduped), reply=got.reply)

    async def connected(self, c: presence_c.Connected) -> None:
        await self.kernel.mind.append([presence_c.CONNECTED.draft(c)], emitter="presence",
                                      correlation=f"ws:{c.connection}", origin=Origin.EXTERNAL)

    async def disconnected(self, handle: str, connection: str) -> None:
        await self.kernel.mind.append([presence_c.DISCONNECTED.draft(handle=handle, connection=connection)],
                                      emitter="presence", correlation=f"ws:{connection}", origin=Origin.EXTERNAL)

    def frame(self) -> Frame:
        return self.kernel.mind.frame()

    def recent(self, handle: str, limit: int) -> list[HistoryRow]:
        return [_row(r) for r in transcript.recent(self._store, handle, limit)]

    def after(self, handle: str, after_id: int, limit: int) -> tuple[list[HistoryRow], bool]:
        rows, truncated = transcript.after(self._store, handle, after_id, limit)
        return [_row(r) for r in rows], truncated

    def ready(self) -> bool:
        return self.kernel.started

    def person_panel(self, handle: str) -> dict[str, Any] | None:
        frame = self.kernel.mind.frame()
        view = frame.get(identity_c.IDENTITY(handle))
        if not view.known:
            return None
        claims = [{"id": 0, "name": view.claim, "kind": "self_declared", "evidence": "", "created_at": ""}] \
            if view.claim else []
        out: dict[str, Any] = {"identity": {
            "known_as": view.name, "certainty": round(view.claim_certainty if view.claim else view.certainty, 2),
            "level": " ".join(describe(view, public=False)), "trust": view.trust.value, "pending_claims": claims,
        }}
        disclosure = frame.get(identity_c.DISCLOSURE((handle, view.channel or "web", False)))
        if not disclosure.own_file:
            return out  # sa fiche est fermée : rien de ce qu'elle sait de la personne
        person = frame.get(identity_c.PERSON(handle))
        profile = frame.state("social").profiles.get(person)
        contact = frame.get(social_c.CONTACT(person))
        summary = self._store.content([profile.summary_ref]).get(profile.summary_ref, "") if profile else ""
        out["person_profile"] = {
            "name": view.name, "summary": summary or "", "closeness": frame.get(social_c.CLOSENESS(person)),
            "preferred_tone": profile.tone if profile else "", "topics_of_interest": list(profile.interests if profile else ()),
            "sensitive_topics": list(profile.sensitive if profile else ()), "interaction_count": contact.inbound,
        }
        promises = frame.get(memory_c.PROMISES_TO(person))
        if promises:
            ids = [pr.id for pr in promises]
            marks = ",".join("?" * len(ids))
            rows = self._store.query_mind(f"SELECT text FROM {memory_c.ITEMS_TABLE} WHERE id IN ({marks}) ORDER BY id",
                                          tuple(ids))
            out["pending_commitments"] = [r[0] for r in rows]
        return out
