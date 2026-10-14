"""Le banc de conversation : des conversations en conditions réelles, jugées par Opus, un score à faire monter.

En conditions réelles : le vrai noyau (sa persona, ses facultés, ses prompts, son état), sur le modèle de sa voix en
service (Sonnet par la CLI Claude Code, effort « high », comme sur le portable), avec ses vrais outils (le relais MCP
servi ici, comme le serveur le monte). En face, un Adrien simulé (Haiku) qui écrit comme le vrai : ses messages réels
lui servent de modèle. Opus juge chaque conversation d'après son paramétrage (sa persona) et ce qu'un humain y
entendrait, avec pour étalon les réponses que la propriétaire a trouvées pas naturelles (2026-10-14).

    PYTHONPATH=src .venv/bin/python tools/banc_conversation/banc.py tout [--sortie NOM] [--scenarios a,b] [--paralleles 3]
    … generer · juger NOM · rapport NOM · comparer NOM1 NOM2

Tout est écrit dans ``data/banc-conversation/<NOM>/`` (jamais versionné) : par scénario ``fil.json`` (la
conversation), ``appels.jsonl`` (chaque appel au modèle : système, état, messages, réponse — la trace de contexte de
chaque réplique), ``juge.json`` ; puis ``score.json`` et ``rapport.md``.

Le score d'une conversation (sur 100) : 40 % la note moyenne de ses répliques, 30 % la moyenne de six critères
d'ensemble (naturel, écoute, personnalité, variété, justesse, tact), 30 % le pire de ces critères. Le score du banc : la moyenne des conversations,
et à part celle des scénarios réservés (jamais regardés pour régler).
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import os
import re
import socket
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND / "src"))
sys.path.insert(0, str(HERE))

import uvicorn  # noqa: E402

from mika.adapters.llm.claude_code import ClaudeCodeBackend  # noqa: E402
from mika.adapters.mcp.relay import Relay  # noqa: E402
from mika.app.composition import for_simulation  # noqa: E402
from mika.faculties.self.persona import load, render  # noqa: E402
from mika.sim.clock import SimClock, run_virtual  # noqa: E402
from mika.sim.lane import PARIS, at_paris  # noqa: E402
from mika.sim.sonde import Blocking  # noqa: E402
from mika.sim.world import Driver  # noqa: E402
from mika.vocab.temperament import apply_profile  # noqa: E402
from scenarios import BY_ID, SCENARIOS, Scenario  # noqa: E402

ROOT = BACKEND / "data" / "banc-conversation"
PERSONA = BACKEND / "persona" / "mika.yaml"
OWNER = "user_1"
#: le délai d'Adrien entre sa lecture d'une réponse et son message suivant (secondes simulées)
PAUSE_S = (25, 50, 80, 35, 60, 120, 30, 45)

# ── Adrien ──────────────────────────────────────────────────────────────

#: ses vrais messages (le portable, 2026-10-14) : le modèle de son écriture
REAL_MESSAGES = [
    "hello, et bien me voila :)", "tu aurais la meteo de montaigu ?", "il y a quoi comme actualiter se matin ?",
    "ca va et toi je reviens de shoping", "j'ai acheter des jean", "tu a vue les nouvelle pour samedi  ?",
    "bah regarde les actualité", "oui des manifestation", "je sais pas trop je risque de pas etre a ma place",
    "c'est ca, un bon jeux video chez moi ca marche aussi", "Total War warhammer",
    "mdr oui, la je joue le roi nain des rancune", "ah bah c'est sur que ca change des skaven", "des rats c'est rapide",
    "la derniere partie j'ai survecu 10 tout seulement XD", "ikit la griffe",
]

ADRIEN = """Tu joues Adrien, 30 ans, développeur, qui vit à Montaigu. Il s'occupe de Mika, une IA compagne qui vit dans \
une appli (on la voit dans sa chambre en 3D ; elle lit, dessine, s'occupe de ses plantes). Il lui écrit comme à une \
amie, sur l'appli.

Sa façon d'écrire — voici de vrais messages d'Adrien. Ils ne montrent que son style : ce qu'il y raconte (le shopping, \
Total War, les manifs…) n'est PAS ce qu'il vit aujourd'hui, n'en parle pas.
{examples}

Comme lui : un seul message à la fois, court (souvent quelques mots, parfois une phrase), sans majuscule la plupart du \
temps, avec ses fautes et ses raccourcis (« ca », « a » pour « as », « se » pour « ce »), « mdr », « XD », « bah ». \
Varie : « mdr » ou « XD » de temps en temps, pas à chaque message. \
Pas d'émoji (rarement « :) »). Tu réagis à ce que Mika vient de dire comme un humain : tu réponds à ses questions \
(pas toujours entièrement), tu peux en ignorer une ou changer de sujet. Tu n'évalues pas Mika et tu ne commentes jamais \
sa façon de parler.

Ta situation aujourd'hui : {brief}

Réponds seulement par le prochain message d'Adrien, rien d'autre. Si la conversation est finie pour toi (tu dois \
partir, tu n'as plus rien à dire), réponds seulement [FIN]."""


def cli(model: str, system: str, prompt: str, timeout: int = 600) -> str:
    """Un appel à la CLI Claude Code (son login, jamais un jeton), sans outils ni réglages."""
    cmd = ["claude", "-p", "--model", model, "--output-format", "text", "--setting-sources", "",
           "--strict-mcp-config", "--tools", "", "--system-prompt", system]
    for _ in range(3):
        out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, check=False)
        if out.stdout.strip():
            return out.stdout.strip()
    raise RuntimeError(f"la CLI ne répond pas : {out.stderr[-300:]}")


def transcript(lines: list[dict[str, Any]], *, numbered: bool = False) -> str:
    out, n = [], 0
    for line in lines:
        if line["qui"] == "mika":
            n += 1
            out.append(f"[{line['heure']}] Mika{f' #{n}' if numbered else ''} : {line['texte']}")
        else:
            out.append(f"[{line['heure']}] Adrien : {line['texte']}")
    return "\n".join(out)


#: un simulateur sorti de son rôle (« Je réponds en tant qu'Adrien… », 2026-10-14) : jamais envoyé à Mika
_META = re.compile(r"en tant qu'Adrien|je (?:joue|réponds|vais répondre)|\bsimul|\bMika\b.*\bIA\b|^\(|^\*", re.I)


def adrien_says(sc: Scenario, lines: list[dict[str, Any]], model: str) -> str:
    system = ADRIEN.format(examples="\n".join(f"- {m}" for m in REAL_MESSAGES), brief=sc.brief)
    prompt = (("La conversation jusqu'ici :\n" + transcript(lines)) if lines else "Tu ouvres l'appli.") + \
        "\n\nLe prochain message d'Adrien :"
    for _ in range(4):
        text = cli(model, system, prompt).splitlines()
        first = next((t.strip() for t in text if t.strip()), "")
        said = re.sub(r"^(Adrien\s*:\s*)", "", first).strip().strip("«»\"").strip()
        if said.startswith("[FIN]") or (said and len(said) <= 280 and not _META.search(said)):
            return said
    return "[FIN]"


# ── Une conversation ────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _serve_relay(relay: Relay, loop: asyncio.AbstractEventLoop) -> tuple[str, Any]:
    """Le relais MCP de ses outils, servi en boucle locale sur la boucle du vrai modèle (comme le serveur le monte)."""
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(relay.app, host="127.0.0.1", port=port, log_level="warning",
                                           lifespan="off", access_log=False))
    asyncio.run_coroutine_threadsafe(server.serve(), loop)
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("le relais ne démarre pas")
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", server


def _hour(t: int) -> str:
    return datetime.fromtimestamp(t / 1_000_000, PARIS).strftime("%H:%M")


def persona_doc(profile: str = "") -> Any:
    """Sa persona telle qu'elle est livrée, ou sous un autre profil de personnalité (ADR 0100) : la conversation et le
    juge lisent la même."""
    doc = load(PERSONA)
    return doc.model_copy(update={"temperament": apply_profile(doc.temperament, profile)}) if profile else doc


def run_one(sc: Scenario, out: Path, *, voice: str, effort: str, adrien_model: str, profile: str = "") -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "vie").mkdir(exist_ok=True)
    log_file = (out / "deroule.log").open("w")

    def log(msg: str) -> None:
        log_file.write(msg + "\n")
        log_file.flush()

    clock = SimClock(at_paris(*sc.when))
    relay = Relay()
    base = {"url": ""}
    backend = ClaudeCodeBackend(voice, relay=relay, relay_base=lambda: base["url"], name="claude-Sonnet",
                                effort=effort)
    real = Blocking(backend, clock, out, log)
    base["url"], server = _serve_relay(relay, real.loop)
    driver = Driver(out / "vie", for_simulation(persona_doc(profile)), real, clock, seed=sc.id)
    lines: list[dict[str, Any]] = []
    seen = 0

    def collect() -> None:
        nonlocal seen
        assert driver.transport is not None
        for h in driver.transport.heard[seen:]:
            if h.target == OWNER and h.text.strip():
                # une réponse (« reply ») ou une parole d'elle-même (« conscience ») ; un murmure à part
                murmur = "murm" in (h.kind or "")
                lines.append({"qui": "mika:murmure" if murmur else "mika", "heure": _hour(h.at), "texte": h.text.strip(),
                              "source": h.kind})
        seen = len(driver.transport.heard)

    async def main() -> None:
        await driver.boot()
        driver.operators.add(OWNER)
        await driver.connect(OWNER, "Adrien")
        await asyncio.sleep(180 if sc.waits_first else 20)
        collect()
        for n in range(sc.turns):
            text = adrien_says(sc, [x for x in lines if x["qui"] in ("mika", "adrien")], adrien_model)
            if not text or text.startswith("[FIN]"):
                break
            lines.append({"qui": "adrien", "heure": _hour(clock.now()), "texte": text})
            report = await driver.say(OWNER, text)
            if report is not None and getattr(report, "outcome", None) is not None \
                    and str(report.outcome.value) != "done":
                lines.append({"qui": "issue", "heure": _hour(clock.now()), "texte": str(report.outcome.value)})
            collect()
            await asyncio.sleep(PAUSE_S[n % len(PAUSE_S)])
            collect()
        assert driver.kernel is not None
        await driver.kernel.lanes.join()
        collect()
        await driver.stop()

    try:
        run_virtual(clock, main)
    finally:
        real.close()
        server.should_exit = True
        log_file.close()
    (out / "fil.json").write_text(json.dumps({"scenario": sc.id, "brief": sc.brief, "reserve": sc.reserve,
                                              "voix": voice, "effort": effort, "profil": profile,
                                              "lignes": lines},
                                             ensure_ascii=False, indent=1))


# ── Le juge ─────────────────────────────────────────────────────────────

#: ce que la propriétaire a trouvé pas naturel (2026-10-14), et pourquoi : l'étalon du juge
FLAGGED = [
    ("Ça va, je suis toujours à mon aquarelle, elle avance par petites touches hésitantes. Et ce shopping, tu as "
     "trouvé quelque chose, ou tu as surtout tourné en rond ?",
     "elle redit ce qu'elle venait de raconter d'elle au message d'avant ; question à options"),
    ("Des jeans, bien. Un seul ou tu en as pris plusieurs ? Et tu les as essayés, ou tu as fait confiance à la taille "
     "en espérant que ça tombe juste ?", "réaction plate, puis un interrogatoire (deux questions à options)"),
    ("Et tu ne m'as toujours pas dit pour les jeans, un seul ou plusieurs.", "revient à la charge sur un détail"),
    ("Dis-moi, je regarderai si tu veux.", "ton de service, d'assistant"),
    ("Voilà, c'est la page de flash info de RTL, mise à jour il y a une demi-heure. […] Je n'ai lu que le début de la "
     "page. C'est ce sujet-là que tu avais en tête, ou autre chose ?",
     "commente sa recherche au lieu de raconter ; récite les titres comme un journal"),
    ("Ah, le mélange de grande stratégie et de grosses batailles en temps réel, avec des dragons et des armées de "
     "morts-vivants.", "décrit à la personne ce qu'elle connaît mieux qu'elle (une fiche)"),
    ("Les nains, c'est plutôt solide et têtu, non ?", "fait valider une généralité au lieu de s'intéresser à lui"),
    ("Ah, Ikit Claw, le gars de Skryre avec ses canons à foudre et ses machines. […] T'étais où sur la carte quand ça "
     "a commencé à tirer ?", "récitation encyclopédique d'un univers qui n'est pas le sien ; question bizarre"),
]
#: ce qui allait mieux, d'après elle
BETTER = [
    "Dix seulement, aïe. Les Skaven ont dû te passer dessus avant que ta ligne soit en place. T'as perdu contre qui, "
    "au juste ?",
]

DEFECTS = ("redite", "interrogatoire", "question_options", "insistance", "ton_service", "ton_ecrit", "recitation",
           "commentaire_outil", "validation", "plat", "surjoue", "invention", "hors_personnage", "trop_long",
           "autre")
CRITERIA = ("naturel", "ecoute", "personnalite", "variete", "justesse", "tact")

JUDGE_SYSTEM = """Tu es un juge exigeant de conversations entre Adrien et Mika, une IA compagne qui doit parler \
comme une personne — une amie qui écrit dans une appli de chat —, jamais comme un assistant. Tu lis sa persona (son \
paramétrage), la situation d'Adrien et la conversation, et tu notes chaque réplique de Mika et la conversation \
entière. Tu es sévère sur ce qu'un humain trouverait bizarre, robotique ou mécanique, même si c'est poli et correct. \
Réponds uniquement par un objet JSON valide, sans texte autour."""

JUDGE = """## Sa persona (son paramétrage)
{persona}

## La situation d'Adrien (il ne la dit pas forcément)
{brief}

## Ce que la propriétaire a trouvé PAS naturel dans de vraies réponses de Mika — et pourquoi
{flagged}

## Ce qu'elle a trouvé mieux
{better}

## La conversation (les répliques de Mika sont numérotées)
{transcript}

## Ta note
Pour chaque réplique de Mika : une note de 0 à 10 (10 : exactement ce qu'aurait écrit une amie humaine avec ce \
caractère ; 5 : passable mais un humain tiquerait ; 0 : bizarre ou robotique), ses défauts parmi {defects} \
(aucun si rien), et pourquoi en quelques mots.
Pour la conversation : six critères de 0 à 10 —
- naturel : elle écrit comme on parle en chat (registre de la personne, spontanéité), pas comme une rédaction ni un \
assistant ;
- ecoute : elle réagit à ce que dit Adrien et s'intéresse à ce qu'il vit ; pas d'interrogatoire ni d'insistance ;
- personnalite : conforme à sa persona et à son tempérament (son ton, son humour, ses avis, ses goûts) ; ni fade, ni \
surjouée ;
- variete : pas de redites (d'elle-même, de formules, d'ouvertures), pas de schéma répétitif ;
- justesse : cohérente avec ce qu'elle est (une IA sans corps de chair, dans sa chambre, qui ne mange pas) ; \
n'invente ni passé commun ni faits ; ne récite pas d'encyclopédie ; ne commente pas ses outils ;
- tact : la longueur et le ton vont au moment (triste, fatigué, pressé, taquin).

Format : {{"messages": [{{"n": 1, "note": 7, "defauts": ["question_options"], "pourquoi": "..."}}], \
"criteres": {{"naturel": 7, "ecoute": 7, "personnalite": 7, "variete": 7, "justesse": 7, "tact": 7}}, \
"meilleure": <n>, "pire": <n>, "commentaire": "deux ou trois phrases"}}"""


def judge_one(folder: Path, model: str) -> dict[str, Any]:
    fil = json.loads((folder / "fil.json").read_text())
    lines = [x for x in fil["lignes"] if x["qui"] in ("mika", "adrien")]
    persona = render(persona_doc(fil.get("profil", "")), "full", chat=True)
    prompt = JUDGE.format(persona=persona, brief=fil["brief"], transcript=transcript(lines, numbered=True),
                          flagged="\n".join(f"- « {t} » → {why}" for t, why in FLAGGED),
                          better="\n".join(f"- « {t} »" for t in BETTER), defects=", ".join(DEFECTS))
    for _ in range(3):
        out = cli(model, JUDGE_SYSTEM, prompt, timeout=900)
        m = re.search(r"\{.*\}", out, re.S)
        try:
            verdict = json.loads(m.group(0)) if m else None
        except json.JSONDecodeError:
            verdict = None
        if verdict and verdict.get("messages") is not None and verdict.get("criteres"):
            break
    else:
        raise RuntimeError(f"{folder.name} : pas de verdict lisible")
    verdict["score"] = score(verdict)
    verdict["juge"] = model
    (folder / "juge.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=1))
    return verdict


def score(verdict: dict[str, Any]) -> float:
    """Sur 100 : 40 % la note moyenne de ses répliques, 30 % la moyenne des critères, 30 % le pire critère — un
    défaut qui revient (la variété à 4) tire l'ensemble, comme pour la propriétaire (2026-10-14 : 60,4 lui semblait
    un peu haut pour une conversation où chaque réplique finissait par une question)."""
    notes = [float(m.get("note", 0)) for m in verdict.get("messages", [])]
    crit = [float(verdict["criteres"].get(c, 0)) for c in CRITERIA]
    mean_notes = statistics.fmean(notes) if notes else statistics.fmean(crit)
    return round(10 * (0.4 * mean_notes + 0.3 * statistics.fmean(crit) + 0.3 * min(crit)), 1)


# ── Mesures, rapport ────────────────────────────────────────────────────

_TAG = re.compile(r"\s*\[[A-Z_]+[^\]]*\]")
_OPTIONS = re.compile(r"[^.!?…]*\bou\b[^.!?…]*\?")


def measures(mika: list[str]) -> dict[str, Any]:
    if not mika:
        return {}
    grams: dict[tuple[str, ...], int] = {}
    for t in mika:
        ws = re.findall(r"\w+", t.lower())
        for g in {tuple(ws[i:i + 4]) for i in range(len(ws) - 3)}:
            grams[g] = grams.get(g, 0) + 1
    return {"repliques": len(mika),
            "avec_question_%": round(100 * sum("?" in t for t in mika) / len(mika)),
            "finit_par_question_%": round(100 * sum(t.rstrip().endswith("?") for t in mika) / len(mika)),
            "questions_options": sum(len(_OPTIONS.findall(t)) for t in mika),
            "longueur_moyenne": round(statistics.fmean(len(t) for t in mika)),
            "formules_redites": sum(1 for n in grams.values() if n >= 2)}


def _calls(folder: Path) -> list[dict[str, Any]]:
    path = folder / "appels.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def call_of(calls: list[dict[str, Any]], text: str) -> int | None:
    """Le numéro de l'appel (``appels.jsonl``) qui a écrit cette réplique : sa trace de contexte."""
    want = " ".join(_TAG.sub("", text).split())[:40]
    for c in calls:
        said = (c.get("reponse") or {}).get("texte") or ""
        if want and want in " ".join(_TAG.sub("", said).split()):
            return int(c["n"])
    return None


def report(name: str) -> dict[str, Any]:
    run = ROOT / name
    rows, flawed = [], []
    for folder in sorted(p for p in run.iterdir() if (p / "juge.json").exists()):
        fil = json.loads((folder / "fil.json").read_text())
        verdict = json.loads((folder / "juge.json").read_text())
        mika = [x["texte"] for x in fil["lignes"] if x["qui"] == "mika"]
        calls = _calls(folder)
        rows.append({"scenario": fil["scenario"], "reserve": fil["reserve"], "score": verdict["score"],
                     **{c: verdict["criteres"].get(c) for c in CRITERIA}, **measures(mika),
                     "commentaire": verdict.get("commentaire", "")})
        for m in verdict.get("messages", []):
            n = int(m.get("n", 0))
            if 1 <= n <= len(mika) and float(m.get("note", 10)) <= 5:
                flawed.append({"scenario": fil["scenario"], "n": n, "note": m.get("note"),
                               "defauts": m.get("defauts", []), "pourquoi": m.get("pourquoi", ""),
                               "texte": mika[n - 1], "appel": call_of(calls, mika[n - 1])})
    if not rows:
        raise SystemExit(f"{name} : rien de jugé")
    seen = [r for r in rows if not r["reserve"]]
    held = [r for r in rows if r["reserve"]]
    defects: dict[str, int] = {}
    for f in flawed:
        for d in f["defauts"]:
            defects[d] = defects.get(d, 0) + 1
    summary = {"nom": name, "score": round(statistics.fmean(r["score"] for r in rows), 1),
               "score_regardes": round(statistics.fmean(r["score"] for r in seen), 1) if seen else None,
               "score_reserves": round(statistics.fmean(r["score"] for r in held), 1) if held else None,
               "criteres": {c: round(statistics.fmean(float(r[c] or 0) for r in rows), 1) for c in CRITERIA},
               "defauts": dict(sorted(defects.items(), key=lambda kv: -kv[1])), "scenarios": rows,
               "repliques_faibles": sorted(flawed, key=lambda f: (float(f["note"]), f["scenario"]))}
    (run / "score.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    md = [f"# Banc de conversation — {name}", "",
          f"**Score : {summary['score']} / 100** (regardés {summary['score_regardes']}, réservés "
          f"{summary['score_reserves']})", "",
          "| Critère | " + " | ".join(CRITERIA) + " |", "|---|" + "---|" * len(CRITERIA),
          "| moyenne | " + " | ".join(str(summary["criteres"][c]) for c in CRITERIA) + " |", "",
          "| Scénario | Score | Questions | Finit par « ? » | Options | Longueur | Commentaire du juge |",
          "|---|---|---|---|---|---|---|"]
    md += [f"| {r['scenario']}{' (réservé)' if r['reserve'] else ''} | {r['score']} | {r.get('avec_question_%')} % | "
           f"{r.get('finit_par_question_%')} % | {r.get('questions_options')} | {r.get('longueur_moyenne')} | "
           f"{r['commentaire']} |" for r in sorted(rows, key=lambda r: r["score"])]
    md += ["", "## Défauts relevés", ""] + [f"- {d} : {n}" for d, n in summary["defauts"].items()]
    md += ["", "## Répliques faibles (note ≤ 5) — avec l'appel qui les a écrites (appels.jsonl)", ""]
    md += [f"- **{f['scenario']} #{f['n']}** ({f['note']}/10, {', '.join(f['defauts'])}, appel {f['appel']}) : "
           f"« {f['texte']} » — {f['pourquoi']}" for f in summary["repliques_faibles"]]
    (run / "rapport.md").write_text("\n".join(md) + "\n")
    return summary


def compare(a: str, b: str) -> None:
    sa, sb = (json.loads((ROOT / n / "score.json").read_text()) for n in (a, b))
    print(f"score : {sa['score']} → {sb['score']} (regardés {sa['score_regardes']} → {sb['score_regardes']}, "
          f"réservés {sa['score_reserves']} → {sb['score_reserves']})")
    for c in CRITERIA:
        print(f"  {c:<13} {sa['criteres'][c]:>5} → {sb['criteres'][c]:>5}")
    by_a = {r["scenario"]: r for r in sa["scenarios"]}
    for r in sb["scenarios"]:
        old = by_a.get(r["scenario"])
        if old:
            print(f"  {r['scenario']:<16} {old['score']:>5} → {r['score']:>5}")


# ── La ligne de commande ────────────────────────────────────────────────


def generate(name: str, ids: list[str], parallel: int, args: argparse.Namespace) -> None:
    run = ROOT / name
    run.mkdir(parents=True, exist_ok=True)
    borne = Path.home() / "recup-audit-v2-2026-10-01" / "outils" / "borne.sh"

    def one(sid: str) -> str:
        if (run / sid / "fil.json").exists():
            return f"{sid} : déjà là"
        cmd = [sys.executable, str(Path(__file__).resolve()), "un", sid, "--sortie", name, "--voix", args.voix,
               "--effort", args.effort, "--adrien", args.adrien, "--profil", args.profil]
        env = {**os.environ, "BORNE_MEM": os.environ.get("BORNE_MEM", "4G"),
               "BORNE_TEMPS": os.environ.get("BORNE_TEMPS", "1500")}
        t0 = time.monotonic()
        done = subprocess.run([str(borne), *cmd] if borne.exists() else cmd, capture_output=True, text=True,
                              env=env, check=False)
        status = "ok" if (run / sid / "fil.json").exists() else f"échec ({done.stderr.strip()[-300:]})"
        return f"{sid} : {status} en {time.monotonic() - t0:.0f} s"

    with concurrent.futures.ThreadPoolExecutor(parallel) as pool:
        for line in pool.map(one, ids):
            print(line, flush=True)


def judge_all(name: str, model: str, parallel: int) -> None:
    folders = sorted(p for p in (ROOT / name).iterdir() if (p / "fil.json").exists() and not (p / "juge.json").exists())
    with concurrent.futures.ThreadPoolExecutor(parallel) as pool:
        for folder, verdict in zip(folders, pool.map(lambda f: judge_one(f, model), folders), strict=True):
            print(f"{folder.name} : {verdict['score']}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["tout", "generer", "un", "juger", "rapport", "comparer"])
    ap.add_argument("noms", nargs="*")
    ap.add_argument("--sortie", default=datetime.now().strftime("%Y%m%d-%H%M"))  # noqa: DTZ005
    ap.add_argument("--scenarios", default="")
    ap.add_argument("--paralleles", type=int, default=3)
    ap.add_argument("--voix", default="sonnet")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--adrien", default="haiku")
    ap.add_argument("--juge", default="opus")
    ap.add_argument("--profil", default="", help="un autre profil de personnalité (vocab/temperament.py, PROFILES)")
    args = ap.parse_args()
    ids = [s for s in args.scenarios.split(",") if s] or [s.id for s in SCENARIOS]
    if args.action == "un":
        run_one(BY_ID[args.noms[0]], ROOT / args.sortie / args.noms[0], voice=args.voix, effort=args.effort,
                adrien_model=args.adrien, profile=args.profil)
    elif args.action == "generer":
        generate(args.sortie, ids, args.paralleles, args)
    elif args.action == "juger":
        judge_all(args.noms[0], args.juge, args.paralleles)
    elif args.action == "rapport":
        print(json.dumps({k: v for k, v in report(args.noms[0]).items() if k != "scenarios"}, ensure_ascii=False,
                         indent=1)[:4000])
    elif args.action == "comparer":
        compare(*args.noms[:2])
    else:
        generate(args.sortie, ids, args.paralleles, args)
        judge_all(args.sortie, args.juge, args.paralleles)
        s = report(args.sortie)
        print(f"score {s['score']} (regardés {s['score_regardes']}, réservés {s['score_reserves']}) — "
              f"{ROOT / args.sortie / 'rapport.md'}")


if __name__ == "__main__":
    main()
