"""Le port d'entrée, implémenté sur le noyau : ce que voient les adaptateurs."""

from __future__ import annotations

from typing import Any

from mika.contracts import attention as attention_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import presence as presence_c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.contracts import sensors as sensors_c
from mika.contracts import social as social_c
from mika.contracts.entry import Admission, HistoryRow
from mika.contracts.runtime import PerceptionReceived
from mika.faculties import transcript
from mika.faculties.attention import prompt as attention_prompt
from mika.faculties.identity import describe
from mika.faculties.projects import work as projects_work
from mika.faculties.self import night
from mika.kernel.clock import local
from mika.kernel.events import Content, Origin
from mika.kernel.frame import Audience, Frame
from mika.kernel.operate import Preview
from mika.runtime import decisions, health
from mika.runtime.bootstrap import Kernel, ReadOnlyStore
from mika.vocab.affect import emotion_of
from mika.vocab.episodes import project_of


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

    def health(self) -> dict[str, Any]:
        return health.report(self.kernel).public()

    def _inner_life(self, frame: Any, handle: str, disclosure: Any) -> dict[str, Any]:
        """Ses pensées (celles que cette personne peut entendre) et son récit."""
        out: dict[str, Any] = {}
        audience = Audience(persons=(handle,), channel="web", public=False, level=int(disclosure.level),
                            witness_level=int(disclosure.witness_level), private_ok=disclosure.own_file)
        person = frame.get(identity_c.PERSON(handle))
        thoughts = [t for t in frame.get(attention_c.THOUGHTS) if attention_prompt.admissible(t, person, audience)][:3]
        texts = self._store.content([t.text_ref for t in thoughts if t.text_ref])
        out["ruminations"] = [{"summary": texts.get(t.text_ref, ""), "intensity": round(t.intensity, 2),
                               "emotion": t.emotion} for t in thoughts if texts.get(t.text_ref)]
        yesterday, dream = frame.get(self_c.YESTERDAY), frame.get(self_c.DREAM_RESIDUE)
        if yesterday is not None and night.hearable(yesterday.about, 2, person, audience):
            text = self._store.content([yesterday.text_ref]).get(yesterday.text_ref)
            if text:
                out["today_journal"] = {"date": yesterday.day, "narrative": text, "dominant_emotion": yesterday.dominant,
                                        "persons_interacted": []}
        if dream is not None and night.hearable(dream.about, dream.sensitivity, person, audience):
            text = self._store.content([dream.text_ref]).get(dream.text_ref)
            if text:
                out["last_dream"] = {"content": text, "dream_type": dream.kind, "vividness": dream.vividness,
                                     "emotion": dream.emotion or "dreamy", "night_of": dream.night,
                                     "recalled": dream.recalled}
        ref = frame.state("self").narrative_ref
        narrative = self._store.content([ref]).get(ref) if ref else None
        if narrative:
            out["self_narrative"] = {"content": narrative, "key_themes": [], "key_people": [], "dominant_mood": "",
                                     "created_at": ""}
        return out

    async def sense(self, device: str, text: str, *, pertinence: float = 0.5, emotion: str = "",
                    sensitivity: int = 1) -> int | None:
        emotion = emotion if emotion_of(emotion) is not None else ""
        level = max(0, min(3, int(sensitivity)))
        draft = sensors_c.SENSED.draft(
            source=f"appareil:{device}", kind="signal", summary=Content.of(text[:400], level=level),
            pertinence=max(0.0, min(1.0, float(pertinence))), emotion=emotion, intensity=0.2 if emotion else 0.0,
            sensitivity=level, device=device)
        commit = await self.kernel.mind.append([draft], emitter="sensors", correlation=f"appareil:{device}",
                                               origin=Origin.EXTERNAL)
        return commit.seqs[-1] if commit.seqs else None

    async def resolve_effect(self, proposal: int, approved: bool, *, by: str, note: str = "",
                             seen: str = "") -> str:
        """Approuver ou refuser un effet en attente (``runtime/decisions.py``) : ``approved``,
        ``rejected``, ``unknown`` (inconnu ou déjà décidé), ``changed`` (ce qui partirait a
        changé depuis qu'on l'a lu) ou ``blocked`` (ça ne peut pas partir tel quel)."""
        got = await decisions.decide(self.kernel.mind, self.kernel.ports, proposal, approved, by=by, note=note,
                                     seen=seen)
        return got.status

    async def effect_preview(self, proposal: int) -> Preview | None:
        """Exactement ce que ferait un effet en attente s'il partait maintenant."""
        pending = self.kernel.mind.frame().state("runtime").effects.get(proposal)
        if pending is None:
            return None
        return await decisions.preview(self.kernel.mind, self.kernel.ports, pending.capability, pending.args_json)

    def _work(self, frame: Any) -> dict[str, Any]:
        """Ses projets et ce qui attend un accord — pour une propriétaire."""
        live = frame.get(projects_c.LIVE)
        pending = frame.get(rt.PENDING_EFFECTS)
        refs = [p.title_ref for p in live] + [e.summary_ref for e in pending]
        texts = self._store.content([r for r in refs if r])
        state = frame.state("projects")
        tz = frame.env.tz_of(frame.root)
        projects = []
        for v in live:
            p = state.projects.get(v.id)
            nxt = projects_work.next_run_at(p, state, frame) if p is not None else None
            projects.append({
                "id": v.id, "title": texts.get(v.title_ref, ""),
                "status": "active" if v.status == projects_c.ACTIVE else "paused", "priority": v.priority,
                "origin": "user" if v.authority == projects_c.USER else "self",
                "emotion_policy": "full" if v.mode == projects_c.PERSONA else "off",
                "schedule_rule": v.schedule or "manual",
                "next_run_at": local(nxt, tz).isoformat() if nxt else None,
                # ses objectifs ponctuels : faits sur tous (les constants n'ont pas de fin)
                "tasks_total": v.open_once + v.done_once + v.blocked_once, "tasks_done": v.done_once,
                "tasks_blocked": v.blocked_once})
        actions = []
        for e in pending:
            pid = project_of(e.context)
            p = state.projects.get(pid) if pid is not None else None
            title = self._store.content([p.title_ref]).get(p.title_ref, "") if p is not None else ""
            actions.append({"id": e.proposal, "project_id": pid or 0, "project_title": title or e.owner,
                            "proposal": texts.get(e.summary_ref, ""), "payload_kind": e.capability,
                            "created_at": local(e.at, tz).isoformat()})
        return {"projects": projects, "pending_project_actions": actions}

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
        out.update(self._inner_life(frame, handle, disclosure))
        if frame.get(identity_c.IS_OWNER(frame.get(identity_c.PERSON(handle)))):
            out.update(self._work(frame))
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
