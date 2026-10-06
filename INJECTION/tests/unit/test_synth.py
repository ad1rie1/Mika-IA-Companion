"""Les synthèses, de bout en bout avec un faux Claude : mois → chapitres → persona → profils → journaux → rêves."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from twin.corpus import Corpus, SourceStats
from twin.engine import jobs
from twin.engine.claude import CallResult, CallSpec
from twin.passes.annotate import AnnotatePass
from twin.passes.synth import (
    ChapterPass,
    DreamPass,
    JournalPass,
    MonthPass,
    PersonaPass,
    ProfilePass,
    chronotype_from_activity,
    latest,
)
from twin.people import resolve_people
from twin.planning import plan
from twin.records import WHATSAPP, Author, Conversation, Message
from twin.sessions import build_sessions
from twin.timing import Temps, to_us

TZ = ZoneInfo("Europe/Paris")


def corpus(tmp_path: Path) -> Corpus:
    """Trente soirées de discussion avec Julie, de mars à mai 2019 ; elle écrit jusque vers 1 h du matin."""
    c = Corpus(tmp_path / "travail" / "corpus.db")
    items: list[Any] = [Author(WHATSAPP, "Julie Martin", name="Julie Martin", me=False),
                        Author(WHATSAPP, "Léa Martin", name="Léa Martin", me=True),
                        Conversation(WHATSAPP, "Julie Martin", members=("Julie Martin", "Léa Martin"))]
    rank = 0
    for day in range(30):
        base = datetime(2019, 3, 10, 22, 30, tzinfo=TZ) + timedelta(days=day * 2)
        for k, (who, text) in enumerate([("Julie Martin", "tu fais quoi ce soir ? je suis trop stressée pour mon oral"),
                                         ("Léa Martin", "je bosse sur mes partiels mdr, tkt tu vas gérer !!"),
                                         ("Léa Martin", "bonne nuit ma belle 💛")]):
            t = base + timedelta(minutes=70 * k + (60 if k == 2 else 0))
            items.append(Message(WHATSAPP, "Julie Martin", who, text, Temps.exact(to_us(t)), rank))
            rank += 1
    with c.transaction():
        sid = c.begin_source("x", "x", "test", 1, 0, "now")
        c.add_items(sid, items, SourceStats())
    resolve_people(c, tmp_path / "travail" / "personnes.yaml", TZ)
    build_sessions(c)
    plan(c, tmp_path / "travail" / "plan.yaml")
    return c


def fake(spec: CallSpec) -> CallResult:
    """Un faux Claude qui répond selon la consigne reçue."""
    s, p = spec.system, spec.prompt
    if "Tu es la mémoire de" in s:
        keys = [k.strip() for k in p.rsplit("(Séances à rendre : ", 1)[1].rstrip(".)").split(",")]
        out = []
        for k in keys:
            block = p.split(f"## Séance {k}", 1)[1].split("## Séance", 1)[0]
            ids = [int(x) for x in re.findall(r"\[m(\d+)\][^\n]*ELLE", block)]
            out.append({"seance": k, "resume": "Julie stressait pour son oral, je l'ai rassurée.",
                        "humeur_fin": "love", "emotions": [{"id": i, "emotion": "playful", "intensite": 0.6}
                                                           for i in ids],
                        "restes": ["un amphi vide"], "signifiance": 0.7,
                        "croyances": [{"texte": "Je révise toujours tard le soir", "sur_elle": True, "genre": "fait"},
                                      {"texte": "Julie passe un oral de master", "personnes": ["p2"]}],
                        "souvenirs": [{"texte": "J'ai rassuré Julie avant son oral.", "personnes": ["p2"],
                                       "importance": 3}]})
        return CallResult("", {"seances": out}, model="fake")
    if "un mois à la fois" in s:
        return CallResult("", {"resume": "Un mois de révisions et de soirées au téléphone avec Julie.",
                               "humeur": "determined", "personnes": ["p2"],
                               "recit": "Je suis quelqu'un qui tient debout les autres, même fatiguée."}, model="fake")
    if "grands chapitres" in s:
        return CallResult("", {"chapitres": [{"titre": "Les partiels", "debut": "2019-03", "fin": "2019-04",
                                              "description": "Je révisais beaucoup, Julie et moi on se soutenait."}]})
    if "Tu fais le portrait" in s:
        return CallResult("", {"description": "Étudiante en master, fidèle en amitié.", "tone": "Familière, rieuse.",
                               "traits": ["Fidèle"], "speech": ["Écrit « mdr » et « tkt »"],
                               "greetings": ["coucou ma belle"], "facts": ["Est en master"],
                               "temperament": {"reactivity": 0.6, "resilience": 0.5, "contagion": 0.7,
                                               "optimism": 0.6, "sociability": 0.7, "curiosity": 0.5,
                                               "perseverance": 0.8, "background": "happy"}})
    if "se faire une idée d'une personne" in s:
        qs = re.findall(r"## (\d{4}T\d)", p)
        return CallResult("", {"profils": [{"trimestre": q, "resume": "Julie prépare son master, on est très proches.",
                                            "ton": "complice"} for q in qs]})
    if "journal intime" in s:
        days = re.findall(r"## (\d{4}-\d{2}-\d{2})", p)
        return CallResult("", {"jours": [{"jour": d, "texte": "J'ai passé la soirée à rassurer Julie."} for d in days]})
    if "les rêves de" in s:
        soirs = re.findall(r"## soir du (\d{4}-\d{2}-\d{2})", p)
        return CallResult("", {"nuits": [{"soir": d, "reves": [
            {"ton": "etrange", "texte": "Je cours dans un amphi vide, Julie m'appelle du fond, la porte recule.",
             "emotion": "anxious", "personnes": ["p2"]},
            {"ton": "doux", "texte": "Julie et moi rions sur un toit, les copies s'envolent comme des oiseaux.",
             "emotion": "happy", "personnes": ["p2"]}]} for d in soirs]})
    raise AssertionError(f"consigne inattendue : {s[:80]}")


async def run_all(c: Corpus, *passes: Any) -> None:
    async def caller(spec: CallSpec) -> CallResult:
        return fake(spec)

    for p in passes:
        jobs.enqueue(c, p)
        report = await jobs.run(c, p, caller=caller)
        assert report.failed == 0, (p.name, report.errors)


async def test_toute_la_chaine(tmp_path: Path) -> None:
    c = corpus(tmp_path)
    await run_all(c, AnnotatePass(TZ), MonthPass(TZ), ChapterPass(), PersonaPass(tmp_path, TZ), ProfilePass(TZ),
                  JournalPass(TZ), DreamPass(TZ))
    assert set(latest(c, "mois")) == {"2019-03", "2019-04", "2019-05"}  # 30 soirées, un jour sur deux
    assert latest(c, "chapitres")["chapitres"]["chapitres"][0]["titre"] == "Les partiels"

    persona_file = tmp_path / "sortie" / "persona" / "lea.yaml"
    assert persona_file.is_file()
    doc = yaml.safe_load(persona_file.read_text(encoding="utf-8"))
    assert doc["name"] == "Léa"  # son prénom, tiré de ses archives
    assert doc["temperament"]["chronotype"] > 0.5  # elle écrit tard : oiseau de nuit
    assert (tmp_path / "sortie" / "persona" / "lea-chapitre-1.yaml").is_file()

    profiles = latest(c, "profil")
    assert any(k.startswith("p2:2019T") for k in profiles)
    assert latest(c, "journal") and all(v["texte"] for v in latest(c, "journal").values())
    dreams = latest(c, "reve")
    assert dreams and {d["ton"] for d in next(iter(dreams.values()))["reves"]} == {"etrange", "doux"}

    # rien n'est refait au second passage
    for p in (MonthPass(TZ), ChapterPass(), PersonaPass(tmp_path, TZ), ProfilePass(TZ), JournalPass(TZ),
              DreamPass(TZ)):
        assert jobs.enqueue(c, p) == 0, p.name


def test_chronotype_lu_dans_ses_heures(tmp_path: Path) -> None:
    c = corpus(tmp_path)
    chrono = chronotype_from_activity(c, TZ)
    assert chrono is not None and 0.5 < chrono <= 1.0
    assert json.dumps(chrono)
