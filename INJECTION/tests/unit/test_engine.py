"""Le moteur Claude Code : isolation de la CLI, file reprenable, quota, passe d'annotation."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from twin.corpus import Corpus, SourceStats
from twin.engine import jobs
from twin.engine.claude import (
    CallResult,
    CallSpec,
    ClaudeError,
    QuotaReading,
    build_argv,
    call,
    first_json_object,
)
from twin.passes.annotate import AnnotatePass
from twin.people import resolve_people
from twin.planning import plan
from twin.records import NOTES, WHATSAPP, Author, Conversation, Document, Message
from twin.schemas import EMOTIONS
from twin.sessions import build_sessions
from twin.timing import Origin, Temps

TZ = ZoneInfo("Europe/Paris")
T0 = 1_600_000_000_000_000


# -- la CLI : isolée, sans jeton -------------------------------------------------------------------------

FAKE = r'''#!/usr/bin/env python3
import json, os, sys
prompt = sys.stdin.read()
args = sys.argv[1:]
print(json.dumps({{"type": "system", "subtype": "init", "mcp_servers": []}}))
print(json.dumps({{"type": "rate_limit_event", "rate_limit_info": {{"unifiedWindows": {{"five_hour":
      {{"utilization": 0.42, "resetsAt": 1900000000}}}}}}}}))
print(json.dumps({{"type": "assistant", "message": {{"model": "claude-sonnet-x", "content": [{{"type": "text", "text": "ok"}}]}}}}))
report = {{"args": args, "env_token": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"), "prompt": prompt,
          "system": open(args[args.index("--system-prompt-file") + 1]).read(), "cwd": os.getcwd(),
          "memory": os.environ.get("CLAUDE_CODE_DISABLE_AUTO_MEMORY")}}
print(json.dumps({{"type": "result", "subtype": "success", "result": "voilà", "structured_output": report,
                  "usage": {{"input_tokens": 10, "output_tokens": 5}}, "total_cost_usd": 0}}))
'''


def fake_cli(tmp_path: Path) -> str:
    f = tmp_path / "claude"
    f.write_text(FAKE.format(), encoding="utf-8")  # le chemin du venv contient une espace : pas de #! direct
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return str(f)


async def test_la_cli_ne_recoit_aucun_jeton_et_reste_isolee(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-NE-DOIT-PAS-PASSER")
    spec = CallSpec(prompt="les séances", system="la consigne", schema={"type": "object"})
    result = await call(spec, binary=fake_cli(tmp_path))
    seen = result.data
    assert seen is not None
    assert seen["env_token"] is None
    assert seen["prompt"] == "les séances" and seen["system"] == "la consigne"
    assert seen["memory"] == "1"
    args = seen["args"]
    for flag in ("--setting-sources", "--strict-mcp-config", "--no-session-persistence", "--json-schema"):
        assert flag in args
    assert args[args.index("--tools") + 1] == "" and args[args.index("--model") + 1] == "sonnet"
    assert args[args.index("--setting-sources") + 1] == ""  # aucune source de réglages : ni CLAUDE.md, ni hooks
    assert Path(seen["cwd"]).name.startswith("jumeau-appel-")  # un dossier vide, pas le dépôt
    assert result.quota == [QuotaReading("five_hour", 0.42, 1900000000)]
    assert result.model == "claude-sonnet-x"


async def test_une_cli_qui_meurt_sans_resultat_est_une_erreur(tmp_path: Path) -> None:
    f = tmp_path / "claude"
    f.write_text("#!/usr/bin/env python3\nimport sys; sys.stderr.write('Not logged in'); sys.exit(1)\n")
    f.chmod(0o755)
    with pytest.raises(ClaudeError, match="Not logged in"):
        await call(CallSpec("x", "y"), binary=str(f))


def test_mcp_ouvert_seulement_sur_demande(tmp_path: Path) -> None:
    plain = build_argv(CallSpec("x", "y"), tmp_path, "claude")
    assert "--mcp-config" not in plain and "--json-schema" not in plain
    with_mcp = build_argv(CallSpec("x", "y", mcp_config=tmp_path / "mcp.json", allowed_tools=("mcp__jumeau__*",)),
                          tmp_path, "claude")
    assert with_mcp[with_mcp.index("--allowedTools") + 1] == "mcp__jumeau__*"


def test_json_dans_le_texte() -> None:
    assert first_json_object('Voici :\n```json\n{"a": 1}\n```') == {"a": 1}
    assert first_json_object('bla {"b": [1, 2]} bla') == {"b": [1, 2]}
    assert first_json_object("rien") is None


def test_les_emotions_sont_celles_du_moteur() -> None:
    mika = pytest.importorskip("mika.vocab.affect")
    assert tuple(e.value for e in mika.Emotion) == EMOTIONS


# -- la passe d'annotation, avec un faux appelant -----------------------------------------------------------

def corpus_annote(tmp_path: Path, *, second_day: bool = False) -> Corpus:
    c = Corpus(tmp_path / "corpus.db")
    later = [Message(WHATSAPP, "Julie", "Julie", "Tu viens samedi ?", Temps.exact(T0 + 86_400_000_000), 2),
             Message(WHATSAPP, "Julie", "Léa", "Oui !! je ramène un gâteau", Temps.exact(T0 + 86_460_000_000), 3)]
    items: list[Any] = [
        Author(WHATSAPP, "Julie", name="Julie", me=False), Author(WHATSAPP, "Léa", name="Léa", me=True),
        Conversation(WHATSAPP, "Julie", members=("Julie", "Léa")),
        Message(WHATSAPP, "Julie", "Julie", "Je suis enceinte !!!", Temps.exact(T0), 0),
        Message(WHATSAPP, "Julie", "Léa", "QUOI ?? je suis trop heureuse pour toi ❤️", Temps.exact(T0 + 60_000_000), 1),
        Author(NOTES, "moi", me=True),
        Document(NOTES, "j#0", "journal", "12 mars", "Cette nuit j'ai rêvé que je volais au-dessus de Lyon.",
                 Temps.exact(T0, Origin.HEADER), 0),
        *(later if second_day else []),
    ]
    with c.transaction():
        sid = c.begin_source("x", "x", "test", 1, 0, "now")
        c.add_items(sid, items, SourceStats())
    resolve_people(c, tmp_path / "personnes.yaml", TZ)
    build_sessions(c)
    plan(c, tmp_path / "plan.yaml")
    if second_day:  # les deux journées au même palier : un seul lot de deux séances
        c.db.execute("UPDATE sessions SET tier = 'A' WHERE document IS NULL")
        c.db.commit()
    return c


def reply_for(spec: CallSpec, *, skip: str = "", bad_id: bool = False) -> CallResult:
    """Une réponse plausible : chaque séance demandée, avec les numéros vus dans le texte."""
    keys = [k.strip() for k in spec.prompt.rsplit("(Séances à rendre : ", 1)[1].rstrip(".)").split(",")]
    ids = [int(x) for x in __import__("re").findall(r"\[m(\d+)\][^\n]*ELLE", spec.prompt)]
    seances = []
    for k in keys:
        if k == skip:
            continue
        s: dict[str, Any] = {"seance": k, "resume": "Julie m'a annoncé sa grossesse le 13 septembre 2020.",
                             "humeur_debut": "neutral", "humeur_fin": "happy",
                             "emotions": [{"id": i, "emotion": "excited", "intensite": 0.8} for i in ids]
                             + ([{"id": 99999, "emotion": "sad", "intensite": 0.5}] if bad_id else []),
                             "restes": ["un berceau"], "signifiance": 0.9}
        if k.startswith("d"):
            s["reves"] = [{"texte": "Je volais au-dessus de Lyon, légère.", "emotion": "dreamy"}]
        else:
            s["souvenirs"] = [{"texte": "Julie m'a appris qu'elle était enceinte.", "personnes": ["p2", "p999"],
                               "messages": [*ids, 424242], "importance": 4, "sensibilite": "personnel"}]
        seances.append(s)
    return CallResult(text="", data={"seances": seances}, model="fake", usage={"input_tokens": 100,
                                                                               "output_tokens": 50})


async def test_annotation_de_bout_en_bout(tmp_path: Path) -> None:
    c = corpus_annote(tmp_path)
    p = AnnotatePass(TZ)
    assert jobs.enqueue(c, p) >= 1
    seen: list[CallSpec] = []

    async def caller(spec: CallSpec) -> CallResult:
        seen.append(spec)
        return reply_for(spec, bad_id=True)

    report = await jobs.run(c, p, caller=caller)
    assert report.done == jobs.counts(c, p).get("done") and report.failed == 0
    assert "ELLE" in seen[0].prompt and "Léa" in seen[0].system  # son nom vient de ses archives
    rows = {r["session"]: json.loads(r["data"]) for r in c.db.execute("SELECT * FROM annotations")}
    assert len(rows) == 2
    conv = next(d for d in rows.values() if d["seance"].startswith("s"))
    assert [e["id"] for e in conv["emotions"]] and all(e["id"] != 99999 for e in conv["emotions"])  # écarté
    assert 424242 not in conv["souvenirs"][0]["messages"]
    assert "p999" not in conv["souvenirs"][0]["personnes"]  # absente du glossaire : inventée
    doc = next(d for d in rows.values() if d["seance"].startswith("d"))
    assert doc["reves"][0]["texte"].startswith("Je volais")
    assert c.db.execute("SELECT COUNT(*) FROM sessions WHERE status = 'done'").fetchone()[0] == 2
    # relancer ne refait rien
    assert jobs.enqueue(c, p) == 0


async def test_une_seance_oubliee_repart_seule(tmp_path: Path) -> None:
    c = corpus_annote(tmp_path, second_day=True)
    p = AnnotatePass(TZ, tokens_per_batch=1_000_000)
    jobs.enqueue(c, p)
    calls: list[CallSpec] = []

    async def caller(spec: CallSpec) -> CallResult:
        calls.append(spec)
        keys = spec.prompt.rsplit("(Séances à rendre : ", 1)[1]
        # la première fois, le modèle « oublie » une séance d'un lot qui en compte plusieurs
        if len(calls) == 1 and "," in keys:
            first = keys.split(",")[0].strip()
            return reply_for(spec, skip=first)
        return reply_for(spec)

    await jobs.run(c, p, caller=caller)
    await jobs.run(c, p, caller=caller)
    assert "," in calls[0].prompt.rsplit("(Séances à rendre : ", 1)[1]  # un lot de plusieurs séances, sinon rien à oublier
    assert c.db.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 3


class FakeTime:
    def __init__(self) -> None:
        self.now = 1_000_000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.now += s


async def test_reponse_invalide_reessayee_de_plus_en_plus_tard_puis_coupee_puis_echec(tmp_path: Path) -> None:
    c = corpus_annote(tmp_path, second_day=True)
    p = AnnotatePass(TZ, tokens_per_batch=1_000_000)
    jobs.enqueue(c, p)
    t = FakeTime()

    async def caller(spec: CallSpec) -> CallResult:
        return CallResult(text="désolé", data=None)

    report = await jobs.run(c, p, caller=caller, max_attempts=3, workers=1, clock=t.clock, sleep=t.sleep)
    assert report.done == 0 and report.split >= 1 and report.failed >= 2
    assert set(jobs.counts(c, p)) == {"failed", "split"}  # le lot de deux séances coupé, chaque moitié échouée
    assert t.slept[:2] == [pytest.approx(30), pytest.approx(60)]  # le délai double
    assert jobs.retry_failed(c, p) == report.failed
    assert jobs.counts(c, p).get("todo") == report.failed


async def test_un_refus_pour_quota_n_est_pas_un_essai(tmp_path: Path) -> None:
    c = corpus_annote(tmp_path)
    p = AnnotatePass(TZ)
    jobs.enqueue(c, p)
    t = FakeTime()
    refused = [0]

    async def caller(spec: CallSpec) -> CallResult:
        if refused[0] < 3:
            refused[0] += 1
            raise ClaudeError("Claude AI usage limit reached", limited=True, resets_at=int(t.now) + 3600)
        return reply_for(spec)

    report = await jobs.run(c, p, caller=caller, max_attempts=2, workers=1, clock=t.clock, sleep=t.sleep)
    assert report.failed == 0 and report.done == jobs.counts(c, p)["done"]
    assert t.slept[0] == pytest.approx(3660)  # jusqu'à la réinitialisation, plus une minute
    assert c.db.execute("SELECT MAX(attempts) FROM jobs").fetchone()[0] == 1


def test_un_refus_pour_quota_se_reconnait() -> None:
    from twin.engine.claude import limit_state

    assert limit_state({"status": "rejected", "resetsAt": 1900000000}) == (True, 1900000000)
    assert limit_state(None, "Claude AI usage limit reached|1900000000") == (True, 1900000000)
    assert limit_state({"status": "allowed"}, "Not logged in") == (False, 0)


async def test_pause_au_plafond_du_quota(tmp_path: Path) -> None:
    c = corpus_annote(tmp_path)
    p = AnnotatePass(TZ, tokens_per_batch=50)  # un lot par séance
    jobs.enqueue(c, p)
    slept: list[float] = []
    now = [1_000_000.0]

    async def caller(spec: CallSpec) -> CallResult:
        r = reply_for(spec)
        r.quota = [QuotaReading("five_hour", 0.95, int(now[0]) + 600)]
        return r

    async def sleep(s: float) -> None:
        slept.append(s)
        now[0] += s

    report = await jobs.run(c, p, workers=1, caller=caller, clock=lambda: now[0], sleep=sleep)
    assert report.done == 2
    assert slept and slept[0] == pytest.approx(660)  # jusqu'à la réinitialisation, plus une minute
    _ = os
