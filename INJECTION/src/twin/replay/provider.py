"""Le rejoueur : un fournisseur LLM qui répond aux vraies requêtes du noyau avec ce que Claude Code a lu.

Pendant l'avance rapide, ses facultés travaillent comme d'habitude : consolider, écrire le
journal, rêver, se raconter, se faire une idée des gens, replier les longs fils. Seul le
modèle qu'elles appellent est remplacé par ce fournisseur :

| rôle | ce qu'il rend |
|---|---|
| ``reply``, ``initiative`` | ses vrais mots, balise d'émotion comprise, que le pilote a annoncés pour cette personne ; sinon ``[SILENCE]`` |
| ``extract`` | ``record_memories`` assemblé (``assemble.py``) pour la fenêtre demandée |
| ``profile`` | ``record_profile`` : le dernier profil de la personne à cette date |
| ``journal`` | son vrai journal du jour, sinon celui synthétisé, sinon ses résumés du jour |
| ``dream`` | son vrai rêve de la nuit, sinon le candidat du ton demandé |
| ``narrative`` | le récit de soi du mois |
| ``compact`` | les résumés des séances avec la personne depuis le dernier repli |
| autres | rien, compté comme « trou » dans le rapport |

Tout se lit dans ``corpus.db`` à la demande (des caches bornés) : des millions de messages
ne tiennent pas en mémoire.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict, deque
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

from mika.ports.llm import LLMRequest, LLMResponse, ToolCall

from twin.corpus import Corpus
from twin.passes.synth import real_dreams
from twin.replay.assemble import ArchiveItems, assemble_extraction
from twin.timing import from_us, to_us

SILENCE = "[SILENCE]"
EXTRACT_TOOL, PROFILE_TOOL = "record_memories", "record_profile"
#: les tons du moteur (``faculties/self/night.py::TONE_FR``) → ceux des rêves synthétisés
TONES = {"cauchemar": "cauchemar", "doux, lumineux": "doux", "mélancolique": "melancolique", "étrange": "etrange",
         "banal": "banal"}
MAX_COMPACT_SENTENCES = 10


class ReplayLLM:
    """``LLMBackend`` du moteur (``name`` + ``complete``)."""

    name = "rejeu"
    model = "archives"
    resumes_tool_loops = False
    defers_tools = False

    def __init__(self, corpus: Corpus, tz: ZoneInfo, now: Callable[[], int]) -> None:
        self.corpus = corpus
        self.db = corpus.db
        self.tz = tz
        self.now = now
        #: ce que le pilote a annoncé qu'elle dira, par adresse de la personne visée
        self.expected: dict[str, deque[str]] = defaultdict(deque)
        #: ``seq`` du journal → messages d'archive qu'il porte (tenu par le pilote)
        self.archive_of_seq: dict[int, tuple[int, ...]] = {}
        self.holes: Counter[str] = Counter()
        self.served: Counter[str] = Counter()
        self._compacted_until: dict[int, int] = {}
        self._told_dreams: dict[str, list[dict[str, Any]]] | None = None
        persons = self.db.execute("SELECT id, handle, name FROM persons").fetchall()
        self.person_of_handle = {r["handle"]: r["id"] for r in persons}
        self.display_name = {f"p{r['id']}": r["name"] for r in persons}

    # -- ce que le pilote annonce ------------------------------------------------------------------------

    def expect(self, handle: str, text: str) -> None:
        self.expected[handle].append(text)

    def note_seq(self, seq: int, archive: tuple[int, ...]) -> None:
        self.archive_of_seq[seq] = archive

    # -- le port LLM -------------------------------------------------------------------------------------

    async def complete(self, req: LLMRequest) -> LLMResponse:
        handler = {"reply": self._speak, "initiative": self._speak, "extract": self._extract,
                   "profile": self._profile, "journal": self._journal, "dream": self._dream,
                   "narrative": self._narrative, "compact": self._compact}.get(req.role)
        if handler is None:
            self.holes[req.role] += 1
            return LLMResponse(SILENCE, model=self.model)
        out = handler(req)
        self.served[req.role] += 1
        return out

    # -- sa parole -----------------------------------------------------------------------------------------

    def _speak(self, req: LLMRequest) -> LLMResponse:
        target = str((req.meta or {}).get("target") or "")
        queue = self.expected.get(target)
        if not queue:
            self.holes[f"{req.role}:imprévu"] += 1
            return LLMResponse(SILENCE, model=self.model)
        return LLMResponse(queue.popleft(), model=self.model)

    # -- sa mémoire ----------------------------------------------------------------------------------------

    def _extract(self, req: LLMRequest) -> LLMResponse:
        text = req.messages[-1].content if req.messages else ""
        seqs = [int(x) for x in re.findall(r"^\[#(\d+)\]", text, re.M)]
        archive = {a for s in seqs for a in self.archive_of_seq.get(s, ())}
        items = ArchiveItems()
        for sid in sorted({self._session_of_message(a) for a in archive} - {None}):
            annotation, messages = self._annotation(sid)  # type: ignore[arg-type]
            if annotation:
                items.add_session(annotation, messages)
        args = assemble_extraction(text, self.archive_of_seq, items, self.display_name)
        return LLMResponse("", tool_calls=(ToolCall(f"{req.call_id}:x", EXTRACT_TOOL, args),), stop="tool_use",
                           model=self.model)

    @lru_cache(maxsize=200_000)  # noqa: B019 — un fournisseur par avance rapide : le cache vit avec elle
    def _session_of_message(self, archive_id: int) -> int | None:
        row = self.db.execute("SELECT session FROM messages WHERE id = ?", (archive_id,)).fetchone()
        return row["session"] if row else None

    @lru_cache(maxsize=4096)  # noqa: B019
    def _annotation(self, session: int) -> tuple[dict[str, Any] | None, tuple[int, ...]]:
        row = self.db.execute("SELECT data FROM annotations WHERE session = ? ORDER BY version DESC LIMIT 1",
                              (session,)).fetchone()
        msgs = tuple(r["id"] for r in self.db.execute("SELECT id FROM messages WHERE session = ?", (session,)))
        return (json.loads(row["data"]) if row else None), msgs

    def _profile(self, req: LLMRequest) -> LLMResponse:
        person = self.person_of_handle.get(req.call_id.rsplit("#", 1)[-1])
        quarter = _quarter(from_us(self.now(), self.tz).date())
        data = None
        if person is not None:
            rows = self.db.execute("SELECT key, data FROM syntheses WHERE kind = 'profil' AND key LIKE ? "
                                   "ORDER BY key DESC", (f"p{person}:%",)).fetchall()
            data = next((json.loads(r["data"]) for r in rows if r["key"].split(":")[1] <= quarter), None)
        if data is None:
            self.holes["profile:sans profil"] += 1
            return LLMResponse(SILENCE, model=self.model)
        args = {k: data.get(k) for k in ("resume", "ton", "interets", "sujets_sensibles")}
        return LLMResponse("", tool_calls=(ToolCall(f"{req.call_id}:p", PROFILE_TOOL, args),), stop="tool_use",
                           model=self.model)

    # -- ses nuits ---------------------------------------------------------------------------------------------

    def _journal(self, req: LLMRequest) -> LLMResponse:
        day = _key_after_hash(req.call_id)
        real = self._real_journal(day)
        if real:
            return LLMResponse(real, model=self.model)
        row = self.db.execute("SELECT data FROM syntheses WHERE kind = 'journal' AND key = ? ORDER BY version DESC",
                              (day,)).fetchone()
        if row:
            return LLMResponse(json.loads(row["data"])["texte"], model=self.model)
        resumes = self._day_resumes(day)
        if resumes:
            return LLMResponse(" ".join(resumes[:3]), model=self.model)
        return LLMResponse("Journée calme, rien de particulier.", model=self.model)

    def _real_journal(self, day: str) -> str:
        try:
            d = date.fromisoformat(day)
        except ValueError:
            return ""
        start = _local_us(d, self.tz)
        end = _local_us(d + timedelta(days=1), self.tz)
        rows = self.db.execute("SELECT text FROM documents WHERE kind = 'journal' AND t_point >= ? AND t_point < ? "
                               "AND t_precision IN ('exacte', 'jour') ORDER BY rank", (start, end)).fetchall()
        return "\n\n".join(r["text"] for r in rows)[:2000]

    def _day_resumes(self, day: str) -> list[str]:
        try:
            d = date.fromisoformat(day)
        except ValueError:
            return []
        start = _local_us(d, self.tz) + 5 * 3_600_000_000  # une heure du matin appartient à la veille
        end = start + 24 * 3_600_000_000
        rows = self.db.execute(
            "SELECT a.data FROM sessions s JOIN annotations a ON a.session = s.id WHERE s.t_point >= ? "
            "AND s.t_point < ? ORDER BY s.t_point", (start, end)).fetchall()
        return [json.loads(r["data"]).get("resume", "") for r in rows if r["data"]]

    def _dream(self, req: LLMRequest) -> LLMResponse:
        night, _, cycle = _key_after_hash(req.call_id).partition(":")
        wanted = next((t for word, t in TONES.items() if word in req.system_stable.split("Ton du rêve :")[-1]), "")
        real = self._real_dreams(night)
        index = int(cycle) if cycle.isdigit() else 0
        if index < len(real):
            return LLMResponse(real[index], model=self.model)
        row = self.db.execute("SELECT data FROM syntheses WHERE kind = 'reve' AND key = ? ORDER BY version DESC",
                              (night,)).fetchone()
        if not row:
            return LLMResponse(SILENCE, model=self.model)  # une nuit sans rêve dont elle se souvienne
        candidates = json.loads(row["data"]).get("reves", [])
        same = [c for c in candidates if c.get("ton") == wanted]
        pick = (same or candidates)[min(index, len(same or candidates) - 1)] if candidates else None
        return LLMResponse(pick["texte"] if pick else SILENCE, model=self.model)

    def _real_dreams(self, night: str) -> list[str]:
        """Les rêves qu'elle a racontés de cette nuit-là (clé : la journée vécue avant, comme le noyau)."""
        if self._told_dreams is None:
            self._told_dreams = real_dreams(self.corpus, self.tz)
        return [d["texte"] for d in self._told_dreams.get(night, [])]

    # -- ce qu'elle se dit d'elle ---------------------------------------------------------------------------------

    def _narrative(self, req: LLMRequest) -> LLMResponse:
        month = from_us(self.now(), self.tz).strftime("%Y-%m")
        row = self.db.execute("SELECT data FROM syntheses WHERE kind = 'mois' AND key <= ? ORDER BY key DESC, "
                              "version DESC LIMIT 1", (month,)).fetchone()
        if not row:
            self.holes["narrative:sans mois"] += 1
            return LLMResponse("", model=self.model)
        return LLMResponse(json.loads(row["data"])["recit"], model=self.model)

    def _compact(self, req: LLMRequest) -> LLMResponse:
        person = self.person_of_handle.get(req.call_id.rsplit("#", 1)[-1])
        if person is None:
            self.holes["compact:inconnue"] += 1
            return LLMResponse("", model=self.model)
        since = self._compacted_until.get(person, 0)
        now = self.now()
        rows = self.db.execute(
            "SELECT s.t_point, a.data FROM sessions s, json_each(s.persons) j JOIN annotations a ON a.session = s.id "
            "WHERE j.value = ? AND s.t_point > ? AND s.t_point <= ? ORDER BY s.t_point", (person, since, now)).fetchall()
        self._compacted_until[person] = now
        sentences = [json.loads(r["data"]).get("resume", "") for r in rows]
        text = " ".join(s for s in sentences if s)
        parts = re.split(r"(?<=[.!?])\s+", text)
        return LLMResponse(" ".join(parts[:MAX_COMPACT_SENTENCES]), model=self.model)


def _key_after_hash(call_id: str) -> str:
    """« run#2019-03-12 » → « 2019-03-12 » ; « run#2019-03-12#1 » (une révision) → « 2019-03-12 »."""
    parts = call_id.split("#")
    return parts[1] if len(parts) > 1 else ""


def _quarter(d: date) -> str:
    return f"{d.year}T{(d.month - 1) // 3 + 1}"


def _local_us(d: date, tz: ZoneInfo) -> int:
    return to_us(datetime.combine(d, time(0), tzinfo=tz))
