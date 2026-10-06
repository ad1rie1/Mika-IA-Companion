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
from mika.vocab.phrasebook import family

from twin.corpus import Corpus
from twin.passes.synth import real_dreams
from twin.replay.assemble import ArchiveItems, assemble_extraction
from twin.timing import from_us, to_us

SILENCE = "[SILENCE]"
SEQ_SCHEMA = """
CREATE TABLE IF NOT EXISTS replay_seq (seq INTEGER PRIMARY KEY, archive TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS replay_archive (archive INTEGER PRIMARY KEY, seq INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS replay_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
EXTRACT_TOOL, PROFILE_TOOL = "record_memories", "record_profile"
#: les tons de rêve du moteur (leurs mots sont dans sa voix, ``self.night.dream.tone.<code>``) → ceux des rêves
#: synthétisés. Le rejoueur reconnaît le ton à ses mots dans la consigne : changer une tournure dans ``voix.yaml``
#: ne le perd pas.
TONES = {"nightmare": "cauchemar", "pleasant": "doux", "melancholic": "melancolique", "associative": "etrange",
         "mundane": "banal"}
MAX_COMPACT_SENTENCES = 10


def dream_tone(system: str) -> str:
    """Le ton demandé par la consigne du rêve, d'après les mots que la voix du moteur donne à chaque ton (le plus
    long qui y figure : « un cauchemar, inquiétant » plutôt qu'un mot qu'il contiendrait)."""
    words = family("self.night.dream.tone")
    found = sorted(((len(w), code) for code, w in words.items() if w and w in system), reverse=True)
    return TONES.get(found[0][1], "") if found else ""


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
        #: ``seq`` du journal → messages d'archive qu'il porte (tenu par le pilote, dans ``corpus.db`` : un million
        #: de lignes ne tiennent pas en mémoire à côté du noyau)
        self.db.executescript(SEQ_SCHEMA)
        self.holes: Counter[str] = Counter()
        self.served: Counter[str] = Counter()
        self._compacted_until: dict[int, int] = {}
        self._told_dreams: dict[str, list[dict[str, Any]]] | None = None
        persons = self.db.execute("SELECT id, handle, name FROM persons").fetchall()
        self.person_of_handle = {r["handle"]: r["id"] for r in persons}
        self._handle_of = {r["id"]: r["handle"] for r in persons}
        self.display_name = {f"p{r['id']}": r["name"] for r in persons}

    # -- ce que le pilote annonce ------------------------------------------------------------------------

    def handle_of(self, person: int) -> str | None:
        return self._handle_of.get(person)

    def expect(self, handle: str, text: str) -> None:
        self.expected[handle].append(text)

    def note_seq(self, seq: int, archive: tuple[int, ...] | list[int]) -> None:
        self.db.execute("INSERT OR REPLACE INTO replay_seq (seq, archive) VALUES (?, ?)",
                        (seq, ",".join(str(a) for a in archive)))
        self.db.executemany("INSERT OR REPLACE INTO replay_archive (archive, seq) VALUES (?, ?)",
                            [(int(a), seq) for a in archive])

    def seq_of(self, archive_id: int) -> int | None:
        """Le ``seq`` du journal qui porte ce message d'archive (``None`` : pas encore vécu)."""
        row = self.db.execute("SELECT seq FROM replay_archive WHERE archive = ?", (int(archive_id),)).fetchone()
        return int(row["seq"]) if row else None

    def archive_of(self, seqs: list[int]) -> dict[int, tuple[int, ...]]:
        out: dict[int, tuple[int, ...]] = {}
        for i in range(0, len(seqs), 500):
            chunk = seqs[i: i + 500]
            for r in self.db.execute(f"SELECT seq, archive FROM replay_seq WHERE seq IN ({','.join('?' * len(chunk))})",  # noqa: S608
                                     chunk):
                out[r["seq"]] = tuple(int(a) for a in r["archive"].split(",") if a)
        return out

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
        mapping = self.archive_of(seqs)
        archive = {a for ids in mapping.values() for a in ids}
        items = ArchiveItems()
        for sid in sorted({self._session_of_message(a) for a in archive} - {None}):
            annotation, messages = self._annotation(sid)  # type: ignore[arg-type]
            if annotation:
                items.add_session(annotation, messages)
        args = assemble_extraction(text, mapping, items, self.display_name)
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
        # les messages que le script rejoue, dans l'ordre du temps (ni système, ni supprimé, ni vide)
        msgs = tuple(r["id"] for r in self.db.execute(
            "SELECT id FROM messages WHERE session = ? AND author IS NOT NULL AND kind NOT IN ('systeme', 'supprime') "
            "AND TRIM(text) != '' ORDER BY t_point IS NULL, t_point, rank", (session,)))
        return (json.loads(row["data"]) if row else None), msgs

    def _profile(self, req: LLMRequest) -> LLMResponse:
        person = self.person_of_handle.get(req.call_id.rsplit("#", 1)[-1])
        quarter = _quarter(from_us(self.now(), self.tz).date())
        data = None
        if person is not None:
            rows = self.db.execute("SELECT key, data FROM syntheses WHERE kind = 'profil' AND key LIKE ? "
                                   "ORDER BY key DESC", (f"p{person}:%",)).fetchall()
            # un trimestre fini : celui en cours est tiré de semaines qu'elle n'a pas encore vécues
            data = next((json.loads(r["data"]) for r in rows if r["key"].split(":")[1] < quarter), None)
        if data is None:
            self.holes["profile:sans profil"] += 1
            return LLMResponse(SILENCE, model=self.model)
        args = {k: data.get(k) for k in ("resume", "ton", "interets", "sujets_sensibles")}
        return LLMResponse("", tool_calls=(ToolCall(f"{req.call_id}:p", PROFILE_TOOL, args),), stop="tool_use",
                           model=self.model)

    # -- ses nuits ---------------------------------------------------------------------------------------------

    def _journal(self, req: LLMRequest) -> LLMResponse:
        if req.call_id.count("#") >= 2:
            # une « nuit coupée » fait réécrire le journal du jour : on garde le premier (l'archive n'en dit pas plus)
            self.served["journal:révision tue"] += 1
            return LLMResponse(SILENCE, model=self.model)
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
        self.holes["journal:rien de lu ce jour-là"] += 1
        return LLMResponse(SILENCE, model=self.model)  # rien n'invente une journée

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
            "AND s.t_point < ? AND a.version = (SELECT MAX(version) FROM annotations WHERE session = s.id) "
            "ORDER BY s.t_point", (start, end)).fetchall()
        return [json.loads(r["data"]).get("resume", "") for r in rows if r["data"]]

    def _dream(self, req: LLMRequest) -> LLMResponse:
        night, _, cycle = _key_after_hash(req.call_id).partition(":")
        wanted = dream_tone(req.system_stable)
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
        # un mois fini : le récit du mois en cours dirait déjà ce qui arrivera dans trois semaines
        row = self.db.execute("SELECT data FROM syntheses WHERE kind = 'mois' AND key < ? ORDER BY key DESC, "
                              "version DESC LIMIT 1", (month,)).fetchone()
        if not row:
            self.holes["narrative:sans mois"] += 1
            return LLMResponse("", model=self.model)
        return LLMResponse(json.loads(row["data"])["recit"], model=self.model)

    def _compact(self, req: LLMRequest) -> LLMResponse:
        """Le résumé d'un long fil : le résumé précédent (dans la requête) et ce qui s'est passé depuis, d'après les
        résumés de séances (la dernière version de chaque annotation), jamais ce qui n'est pas encore arrivé."""
        person = self.person_of_handle.get(req.call_id.rsplit("#", 1)[-1])
        if person is None:
            self.holes["compact:inconnue"] += 1
            return LLMResponse("", model=self.model)
        key = f"compact:{person}"
        row = self.db.execute("SELECT value FROM replay_state WHERE key = ?", (key,)).fetchone()
        since = int(json.loads(row["value"])) if row else 0
        now = self.now()
        rows = self.db.execute(
            "SELECT s.t_point, a.data FROM sessions s, json_each(s.persons) j JOIN annotations a ON a.session = s.id "
            "WHERE j.value = ? AND s.t_point > ? AND s.t_point <= ? AND a.version = (SELECT MAX(version) FROM "
            "annotations WHERE session = s.id) ORDER BY s.t_point", (person, since, now)).fetchall()
        self.db.execute("INSERT OR REPLACE INTO replay_state (key, value) VALUES (?, ?)", (key, json.dumps(now)))
        text = req.messages[-1].content if req.messages else ""
        previous = text.split("Résumé précédent :", 1)[1].split("\n\n", 1)[0].strip() \
            if "Résumé précédent :" in text else ""
        news = " ".join(x for x in (json.loads(r["data"]).get("resume", "") for r in rows) if x)
        recent = [x for x in re.split(r"(?<=[.!?])\s+", news) if x]
        before = [x for x in re.split(r"(?<=[.!?])\s+", previous) if x]
        room = max(3, MAX_COMPACT_SENTENCES - len(before))  # le plus récent d'abord, sans jamais tout perdre
        return LLMResponse(" ".join([*before, *recent[-room:]]).strip(), model=self.model)

    def _has(self, table: str) -> bool:
        return self.db.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone() is not None


def _key_after_hash(call_id: str) -> str:
    """« run#2019-03-12 » → « 2019-03-12 » ; « run#2019-03-12#1 » (une révision) → « 2019-03-12 »."""
    parts = call_id.split("#")
    return parts[1] if len(parts) > 1 else ""


def _quarter(d: date) -> str:
    return f"{d.year}T{(d.month - 1) // 3 + 1}"


def _local_us(d: date, tz: ZoneInfo) -> int:
    return to_us(datetime.combine(d, time(0), tzinfo=tz))
