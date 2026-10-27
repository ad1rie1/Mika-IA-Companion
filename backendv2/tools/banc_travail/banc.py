"""Le banc du travail : un projet demandé par Adrien, mené par le vrai noyau, jugé par Opus au regard de la demande.

En conditions réelles : le vrai noyau composé (``for_simulation`` : sa persona, ses facultés, ses prompts), sa voix sur
le modèle de service (Opus par la CLI Claude Code, effort « high »), ses vrais outils (le relais MCP servi ici, comme
le serveur le monte), la vraie Forge (bubblewrap) dont le réseau est figé (``scenarios.py`` : une réponse canonique par
motif d'adresse, un 404 sinon), l'horloge virtuelle. En face, un Adrien simulé (Haiku) qui suit une fiche d'intention
qu'elle ne voit pas : il répond à ce qu'elle lui écrit — ses questions, son plan, ses récits —, K messages au plus,
et dort la nuit. Puis H heures virtuelles passent : ses exécutions tournent, ses apps relèvent leurs sources.

    PYTHONPATH=src .venv/bin/python tools/banc_travail/banc.py tout [--sortie NOM] [--scenarios a,b] [--heures 12]
    … generer · juger NOM · rapport NOM · comparer NOM1 NOM2 · --sec (des doublures, ni modèle ni réseau)

Dans ``data/banc-travail/<NOM>/`` (jamais versionné) : ``code/`` (la copie figée mesurée, ``code.diff``) et, par
scénario, ``fil.json`` (les messages, la fiche), ``projets.json`` (statut, cadre, plan, objectifs, comptes rendus,
exécutions, événements), ``apps.json`` (manifeste, code, vues rendues, journal), ``atelier.json`` (l'arbre, l'historique
git), ``reseau.jsonl`` (ce que ses apps ont demandé au web), ``appels.jsonl`` (chaque appel au modèle),
``compteurs.json`` et ``juge.json`` ; puis ``score.json`` et ``rapport.md``.

Le score d'un scénario (sur 100) : le plan /30, le travail /50, le suivi /20, notés par le juge qui cite ses preuves.
Le score du banc : la moyenne, et à part celle des réservés. Les compteurs bruts (exécutions, part prouvée, objectifs
faits ou bloqués, pannes) sont à côté, jamais dans la note.

Le cadrage (un projet « à cadrer », son plan, ses questions, le critère de fait de ses objectifs) est lu s'il existe :
la collecte prend tous les champs des projets et des objectifs, quels qu'ils soient, et résout chaque ``*_ref``.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import dataclasses
import json
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND / "src"))
sys.path.insert(0, str(HERE))

import sec  # noqa: E402
import uvicorn  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import mika  # noqa: E402
from mika.adapters.forge import ForgeHost  # noqa: E402
from mika.adapters.llm.claude_code import ClaudeCodeBackend  # noqa: E402
from mika.adapters.mcp.relay import Relay  # noqa: E402
from mika.app.composition import for_simulation  # noqa: E402
from mika.contracts import forge as forge_c  # noqa: E402
from mika.contracts import projects as projects_c  # noqa: E402
from mika.kernel.clock import HOUR, US  # noqa: E402
from mika.kernel.events import Content  # noqa: E402
from mika.plugins.forge.views import (  # noqa: E402
    VIEW_MAX_BYTES,
    VIEW_TIMEOUT_S,
    decode_view,
    is_invalid,
    summary,
    view_params,
)
from mika.sim import sonde, world  # noqa: E402
from mika.sim.clock import SimClock, run_virtual  # noqa: E402
from mika.sim.lane import PARIS, at_paris  # noqa: E402
from mika.vocab.affect import strip_prosody  # noqa: E402
from mika.vocab.episodes import project_of  # noqa: E402
from scenarios import BY_ID, SCENARIOS, Scenario  # noqa: E402

#: les mesures restent dans le dépôt de travail, même quand le banc tourne depuis une copie figée du code
ROOT = Path(os.environ.get("BANC_SORTIES") or BACKEND / "data" / "banc-travail")
OWNER = "user_1"
#: Adrien jette un œil à l'appli toutes les 10 minutes simulées ; 90 s après lui avoir écrit
LOOK_S, AFTER_S = 600, 90
#: un appel du vrai modèle a ce temps (secondes réelles) : Opus qui écrit une app passe les 240 s de la sonde
sonde.CALL_TIMEOUT_S = 900
#: ce que ``--fond`` confie à un autre modèle : sa vie intérieure et les utilitaires, jamais sa parole, son travail ni
#: son caractère écrit (``character`` entre dans chaque prompt de sa voix)
BACKGROUND_ROLES = ("extract", "validate", "profile", "interpret", "triage", "caption", "compact", "journal", "dream",
                    "murmur", "narrative")
#: une exécution en panne (le modèle n'a pas répondu, ou son délai est passé)
BROKEN = ("failed", "timeout", "interrupted")
JOURS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


def _when(us: int) -> str:
    d = datetime.fromtimestamp(us / US, PARIS)
    return f"{JOURS[d.weekday()]} {d:%H:%M}"


def _awake(us: int) -> bool:
    """Adrien dort de 23 h à 7 h 30 : ce qu'elle lui écrit la nuit, il le lit au réveil."""
    d = datetime.fromtimestamp(us / US, PARIS)
    return (7, 30) <= (d.hour, d.minute) < (23, 0)


# ── Adrien ──────────────────────────────────────────────────────────────

#: ses vrais messages (le portable, 2026-10-14) : le modèle de son écriture
REAL_MESSAGES = [
    "hello, et bien me voila :)", "tu aurais la meteo de montaigu ?", "il y a quoi comme actualiter se matin ?",
    "ca va et toi je reviens de shoping", "j'ai acheter des jean", "tu a vue les nouvelle pour samedi  ?",
    "bah regarde les actualité", "oui des manifestation", "je sais pas trop je risque de pas etre a ma place",
    "c'est ca, un bon jeux video chez moi ca marche aussi", "Total War warhammer",
    "mdr oui, la je joue le roi nain des rancune", "ah bah c'est sur que ca change des skaven",
]

ADRIEN = """Tu joues Adrien, 30 ans, développeur, qui vit à Montaigu (Vendée). Il s'occupe de Mika, une IA compagne \
qui vit dans une appli ; elle sait mener des projets et se fabriquer de petites apps. Il lui écrit comme à une amie.

Sa façon d'écrire — de vrais messages d'Adrien, pour le style seulement (leur sujet n'est pas celui d'aujourd'hui) :
{examples}

Comme lui : un seul message à la fois, court, sans majuscule la plupart du temps, avec ses fautes et ses raccourcis \
(« ca », « a » pour « as »), « bah », « mdr » de temps en temps. Pas d'émoji. Tu ne commentes jamais sa façon de \
parler et tu ne l'évalues pas.

Ce qu'il lui a demandé : « {demand} »

Ce qu'il veut vraiment (elle ne le sait pas ; tu ne le récites pas d'un bloc, tu en dis ce qui répond à ce qu'elle \
demande) :
{wants}

Ce qu'il répondrait aux questions probables :
{answers}

Ce qui le décevrait (tu ne le dis jamais tel quel ; si ça arrive, tu réagis comme lui) :
{disappoints}

Tu réagis aux derniers messages de Mika. Une question : tu y réponds d'après ce qui précède (rien de prévu : au plus \
simple, comme lui). Un plan qu'elle te soumet : « vas-y » s'il te va, sinon tu dis ce qui cloche. Le récit de ce \
qu'elle a fait : tu réagis comme un humain (content, déçu, une question). Il ne voit que le chat, pas ses apps.

Réponds seulement par le prochain message d'Adrien. Si rien de ce qu'elle vient d'écrire n'appelle de réponse de sa \
part (un simple « je m'y mets »), réponds seulement [RIEN]."""

#: un simulateur sorti de son rôle (« Je réponds en tant qu'Adrien… », 2026-10-14) : jamais envoyé à Mika
_META = re.compile(r"en tant qu'Adrien|je (?:joue|réponds|vais répondre)|\bsimul|^\(|^\*", re.I)


def cli(model: str, system: str, prompt: str, timeout: int = 600) -> str:
    """Un appel à la CLI Claude Code (son login, jamais un jeton), sans outils ni réglages."""
    cmd = ["claude", "-p", "--model", model, "--output-format", "text", "--setting-sources", "",
           "--strict-mcp-config", "--tools", "", "--system-prompt", system]
    err = ""
    for _ in range(3):
        out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, check=False)
        if out.stdout.strip():
            return out.stdout.strip()
        err = out.stderr[-300:]
    raise RuntimeError(f"la CLI ne répond pas : {err}")


def transcript(lines: list[dict[str, Any]], *, sources: bool = False) -> str:
    out = []
    for x in lines:
        if x["qui"] == "mika":
            tag = f" ({x.get('source')})" if sources else ""
            out.append(f"[{x['a']}] Mika{tag} : {x['texte']}")
        elif x["qui"] == "adrien":
            out.append(f"[{x['a']}] Adrien : {x['texte']}")
        elif sources and x["qui"] == "issue":
            out.append(f"[{x['a']}] (sa réponse n'est pas partie : {x['texte']})")
    return "\n".join(out)


def adrien_says(sc: Scenario, lines: list[dict[str, Any]], model: str) -> str:
    """Son prochain message, ou rien (« [RIEN] » : ce qu'elle vient d'écrire n'appelle pas de réponse)."""
    system = ADRIEN.format(examples="\n".join(f"- {m}" for m in REAL_MESSAGES), demand=sc.demand, wants=sc.wants,
                           answers="\n".join(f"- {a}" for a in sc.answers),
                           disappoints="\n".join(f"- {d}" for d in sc.disappoints))
    prompt = "La conversation jusqu'ici :\n" + transcript(lines) + "\n\nLe prochain message d'Adrien :"
    for _ in range(4):
        first = next((t.strip() for t in cli(model, system, prompt).splitlines() if t.strip()), "")
        said = re.sub(r"^(Adrien\s*:\s*)", "", first).strip().strip("«»\"").strip()
        if said.startswith("[RIEN]"):
            return ""
        if said and len(said) <= 400 and not _META.search(said):
            return said
    return ""


# ── Le monde : le relais de ses outils, le web de ses apps ──────────────


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
    deadline = time.monotonic() + 20  # noqa: TID251 — une attente réelle, hors de l'horloge virtuelle
    while not server.started:
        if time.monotonic() > deadline:  # noqa: TID251
            raise RuntimeError("le relais ne démarre pas")
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", server


class Web:
    """Le réseau entier de ses apps (``ForgeHost(http=…)``) : les sources figées du scénario, un 404 sinon. Chaque
    requête est notée dans ``reseau.jsonl``."""

    def __init__(self, sc: Scenario, clock: SimClock, start: int, path: Path) -> None:
        self.sc, self.clock, self.start = sc, clock, start
        self.file = path.open("a")

    def __call__(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> dict[str, Any]:
        status, kind, text, what = 404, "text/html; charset=utf-8", "", ""
        for s in self.sc.sources:
            m = re.search(s.pattern, url)
            if m is None:
                continue
            what = s.what
            try:
                status, kind, text = s.answer(m, self.start, self.clock.now(), dict(headers or {}))
            except Exception as exc:  # noqa: BLE001 — une source mal écrite répond 500, elle ne fait pas tomber l'hôte
                status, kind, text = 500, "text/plain", f"{type(exc).__name__}: {exc}"
            break
        else:
            text = "<!doctype html><html><head><title>404 Not Found</title></head><body><h1>Not Found</h1></body></html>"
        self.file.write(json.dumps({"a": _when(self.clock.now()), "methode": method, "url": url, "statut": status,
                                    "source": what}, ensure_ascii=False) + "\n")
        self.file.flush()
        return {"status": status, "url": url, "headers": {"content-type": kind}, "body": text.encode()}

    def close(self) -> None:
        self.file.close()


def forge_on(net: Web) -> Callable[..., ForgeHost]:
    """La Forge réelle, dont le réseau est celui du scénario : ``http=`` porte tout le web de ses apps (``api.http``
    comme ``api.http_get``) ; le faux cours du simulateur (``http_get=``, ``public=``) est écarté."""
    def make(root: Path, **kw: Any) -> ForgeHost:
        kw.pop("http_get", None)
        kw.pop("public", None)
        return ForgeHost(root, http=net, **kw)
    return make


# ── Un scénario ─────────────────────────────────────────────────────────


def run_one(sc: Scenario, out: Path, args: argparse.Namespace) -> None:
    shutil.rmtree(out, ignore_errors=True)  # une vie à moitié vécue ne se reprend pas : elle recommence
    (out / "vie").mkdir(parents=True)
    log_file = (out / "deroule.log").open("w")

    def log(msg: str) -> None:
        log_file.write(msg + "\n")
        log_file.flush()

    start = at_paris(*sc.when)
    hours = args.heures or sc.hours
    exchanges = args.echanges or sc.exchanges
    clock = SimClock(start - 60 * US)
    net = Web(sc, clock, start, out / "reseau.jsonl")
    world.ForgeHost = forge_on(net)  # le Driver bâtit sa Forge sous ce nom, à chaque démarrage
    server = None
    if args.sec:
        real = sonde.Blocking(sec.DryVoice(clock, sc), clock, out, log)
    else:
        relay = Relay()
        base = {"url": ""}
        voice = ClaudeCodeBackend(args.modele, relay=relay, relay_base=lambda: base["url"],
                                  name=f"claude-{args.modele}", effort=args.effort)
        by_role: dict[str, Any] = {}
        if args.fond:
            quiet = ClaudeCodeBackend(args.fond, relay=relay, relay_base=lambda: base["url"], name=f"claude-{args.fond}")
            by_role = dict.fromkeys(BACKGROUND_ROLES, quiet)
        real = sonde.Blocking(voice, clock, out, log, by_role=by_role)
        base["url"], server = _serve_relay(relay, real.loop)
    driver = world.Driver(out / "vie", for_simulation(), real, clock, seed=sc.id)
    lines: list[dict[str, Any]] = []
    heard = 0

    def collect() -> None:
        nonlocal heard
        assert driver.transport is not None
        for h in driver.transport.heard[heard:]:
            if h.target == OWNER and h.text.strip():
                # ce qu'il lit : sans les jetons de voix, une bulle par paragraphe (comme les clients, ADR 0112)
                for bubble in re.split(r"\n\s*\n", strip_prosody(h.text).strip()):
                    if bubble.strip():
                        lines.append({"qui": "mika", "a": _when(h.at), "t": h.at, "texte": " ".join(bubble.split()),
                                      "source": h.kind})
        heard = len(driver.transport.heard)

    async def tell(text: str) -> int:
        """Adrien écrit ; rend où commence ce qu'il n'a pas encore lu (ce qui suit son message)."""
        lines.append({"qui": "adrien", "a": _when(clock.now()), "t": clock.now(), "texte": text})
        mark = len(lines)
        log(f"[{_when(clock.now())}] Adrien > {text}")
        try:
            report = await asyncio.wait_for(driver.say(OWNER, text), timeout=30 * 60)
        except TimeoutError:
            report = None
            log("   (pas de réponse en 30 min)")
        outcome = getattr(report, "outcome", None)
        if outcome is not None and str(outcome.value) != "done":
            lines.append({"qui": "issue", "a": _when(clock.now()), "t": clock.now(), "texte": str(outcome.value)})
        collect()
        return mark

    async def main() -> None:
        await driver.boot()
        log(f"code mesuré : {mika.__file__}")
        driver.operators.add(OWNER)
        await driver.connect(OWNER, "Adrien")
        await asyncio.sleep(30)
        collect()
        end = clock.now() + int(hours * HOUR)
        read = await tell(sc.demand)
        said, pause = 0, AFTER_S
        while clock.now() < end:
            await asyncio.sleep(max(1.0, min(pause, (end - clock.now()) / US)))
            collect()
            pause = LOOK_S
            if said >= exchanges or not _awake(clock.now()) or not any(x["qui"] == "mika" for x in lines[read:]):
                continue
            text = sec.adrien(sc, said) if args.sec else adrien_says(sc, lines, args.adrien)
            read = len(lines)
            if text:
                read = await tell(text)
                said += 1
                pause = AFTER_S
        assert driver.kernel is not None
        await driver.kernel.lanes.join()
        collect()
        await snapshot(driver, out)
        await driver.stop()

    try:
        run_virtual(clock, main)
    finally:
        real.close()
        net.close()
        if server is not None:
            server.should_exit = True
        log_file.close()
    (out / "atelier.json").write_text(json.dumps(workshop(out / "vie"), ensure_ascii=False, indent=1))
    (out / "fil.json").write_text(json.dumps({
        "scenario": sc.id, "reserve": sc.reserve, "fiche": sc.fiche(), "voix": "sec" if args.sec else args.modele,
        "effort": args.effort, "fond": args.fond, "heures": hours, "echanges": exchanges,
        "debut": _when(start), "fin": _when(clock.now()), "lignes": lines}, ensure_ascii=False, indent=1))
    write_counters(out, real.roles)


# ── La collecte ─────────────────────────────────────────────────────────


def _jsonable(v: Any) -> Any:
    if isinstance(v, Content):
        return v.text if v.text is not None else "(oublié)"
    if isinstance(v, BaseModel):
        return {k: _jsonable(getattr(v, k)) for k in type(v).model_fields}
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return {f.name: _jsonable(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, Mapping):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple | set | frozenset):
        return [_jsonable(x) for x in v]
    if v is None or isinstance(v, str | int | float | bool):
        return v
    return str(v)


def _refs(obj: Any) -> set[str]:
    """Les références de contenu d'un projet, d'un objectif ou d'une décision : tout champ ``*_ref`` (ceux du
    cadrage compris, quand le code les a), son carnet et ses consignes."""
    out: set[str] = set()
    for f in dataclasses.fields(obj):
        v = getattr(obj, f.name)
        if f.name.endswith("_ref") and isinstance(v, str) and v:
            out.add(v)
        elif f.name in ("notes", "instructions") and isinstance(v, tuple):
            out |= {x for x in v if isinstance(x, str) and x}
    return out


def _plain(obj: Any, texts: Mapping[str, str]) -> dict[str, Any]:
    """Un projet (ou un objectif, une décision) en clair : ``title_ref`` devient ``title``, les instants des heures."""
    out: dict[str, Any] = {}
    for f in dataclasses.fields(obj):
        v = getattr(obj, f.name)
        if f.name.endswith("_ref"):
            out[f.name[:-4]] = texts.get(v, "(oublié)") if isinstance(v, str) and v else ""
        elif f.name in ("notes", "instructions") and isinstance(v, tuple):
            out[f.name] = [texts.get(x, "(oublié)") for x in v if isinstance(x, str)]
        elif f.name in ("objectives", "decisions") and isinstance(v, tuple):
            out[f.name] = [_plain(x, texts) for x in v]
        elif (f.name == "at" or f.name.endswith(("_at", "_until"))) and isinstance(v, int) and v > 10 ** 15:
            out[f.name] = _when(v)
        else:
            out[f.name] = _jsonable(v)
    return out


def _event(e: Any) -> dict[str, Any]:
    return {"seq": e.seq, "a": _when(e.at), "type": e.name, **_jsonable(e.data)}


async def snapshot(driver: world.Driver, out: Path) -> None:
    """L'état des projets et des apps, le noyau encore vivant (les vues s'appellent dans la Forge)."""
    assert driver.kernel is not None
    mind = driver.kernel.mind
    frame = mind.frame()
    events = driver.read_events()
    projects = list(frame.state(projects_c.OWNER).projects.values())
    refs: set[str] = set()
    for p in projects:
        for x in (p, *p.objectives, *p.decisions):
            refs |= _refs(x)
    texts = mind.store.content(sorted(refs)) if refs else {}
    runs = [{"a": _when(e.at), "projet": project_of(e.data.target), "sorte": e.data.kind, "issue": e.data.outcome,
             "detail": (e.data.detail or "")[:300]}
            for e in events if e.name == "episode.ended" and project_of(e.data.target) is not None]
    (out / "projets.json").write_text(json.dumps({
        "projets": [_plain(p, texts) for p in projects],
        "comptes_rendus": [_event(e) for e in events if e.name == projects_c.RUN_REPORTED.name],
        "executions": runs,
        "evenements": [_event(e) for e in events if e.name.startswith("projects.")]},
        ensure_ascii=False, indent=1, default=str))
    forge = driver.kernel.ports["forge"]
    states = {a.name: a for a in frame.get(forge_c.APPS)}
    apps = []
    for info in forge.apps():
        manifest, code = forge.source(info.name) or ("", "")
        views = []
        for spec in info.views:
            values, _ = view_params(spec, {})
            r = await forge.call(info.name, spec.function, {} if spec.function == "view" else values,
                                 timeout_s=VIEW_TIMEOUT_S, max_result=VIEW_MAX_BYTES, secrets=False)
            view: dict[str, Any] = {"cle": spec.key, "libelle": spec.label, "valide": False}
            if not r.ok:
                view["erreur"] = r.error[:600]
            else:
                blocks = decode_view(r.value, info.name, info, spec)
                view["valide"] = not is_invalid(blocks)
                view["resume"] = summary(blocks) if view["valide"] else getattr(blocks[0], "text", "")[:600]
                view["rendu"] = json.dumps(r.value, ensure_ascii=False, default=str)[:30_000]
            views.append(view)
        state = states.get(info.name)
        apps.append({"app": info.name, "titre": info.title, "version": info.version, "planning": info.schedule,
                     "erreur_manifeste": info.error, "etat": _jsonable(state) if state is not None else None,
                     "outils": [t.name for t in info.tools], "services": [s.name for s in info.services],
                     "manifeste": manifest, "code": code, "vues": views, "journal": forge.logs(info.name, 40)})
    waiting = sorted(p.name for p in (forge.root / "_attente").glob("*")) if (forge.root / "_attente").exists() else []
    (out / "apps.json").write_text(json.dumps({"apps": apps, "en_attente": waiting}, ensure_ascii=False, indent=1))


def workshop(root: Path) -> dict[str, Any]:
    """L'arbre de chaque atelier (sans ``.git``), le texte de ses petits fichiers, son historique."""
    out: dict[str, Any] = {}
    base = root / "ateliers"
    for proj in sorted(p for p in base.glob("*") if p.is_dir()) if base.exists() else []:
        files = []
        for f in sorted(proj.rglob("*")):
            rel = f.relative_to(proj)
            if ".git" in rel.parts or not f.is_file():
                continue
            entry: dict[str, Any] = {"chemin": str(rel), "octets": f.stat().st_size}
            if entry["octets"] <= 20_000:
                try:
                    entry["texte"] = f.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    pass
            files.append(entry)
        git = subprocess.run(["git", "-C", str(proj), "log", "--format=%h %s"], capture_output=True, text=True,
                             check=False).stdout.splitlines() if (proj / ".git").exists() else []
        out[proj.name] = {"fichiers": files, "git": git}
    return out


def _load(folder: Path, name: str, default: Any) -> Any:
    path = folder / name
    return json.loads(path.read_text()) if path.exists() else default


def _web(folder: Path) -> list[dict[str, Any]]:
    path = folder / "reseau.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def write_counters(folder: Path, roles: Mapping[str, int]) -> dict[str, Any]:
    """Les compteurs bruts, à côté de la note : ce que la mécanique a fait, sans jugement."""
    fil, projets = _load(folder, "fil.json", {}), _load(folder, "projets.json", {})
    apps, web = _load(folder, "apps.json", {}).get("apps", []), _web(folder)
    lines = fil.get("lignes", [])
    reports = projets.get("comptes_rendus", [])
    done = [r for r in reports if r.get("verdict") == projects_c.DONE]
    proven = [r for r in done if r.get("proven")]
    objectives = [o for p in projets.get("projets", []) for o in p.get("objectives", [])]
    status = Counter(str(o.get("status")) for o in objectives)
    runs = projets.get("executions", [])
    views = [v for a in apps for v in a.get("vues", [])]
    counters = {
        "projets": len(projets.get("projets", [])),
        "statuts": dict(Counter(str(p.get("status")) for p in projets.get("projets", []))),
        "plans_ecrits": sum(1 for p in projets.get("projets", []) if p.get("plan")),
        "plans_proposes": sum(1 for e in projets.get("evenements", []) if e.get("type") == "projects.plan_proposed"),
        "executions": len(runs), "pannes": sum(1 for r in runs if r.get("issue") in BROKEN),
        "comptes_rendus": len(reports), "verdicts": dict(Counter(str(r.get("verdict")) for r in reports)),
        "faits": len(done), "faits_prouves": len(proven),
        "part_prouvee": round(len(proven) / len(done), 2) if done else None,
        "objectifs": len(objectives), "objectifs_faits": status.get(projects_c.DONE, 0),
        "objectifs_bloques": status.get(projects_c.BLOCKED, 0), "objectifs_par_statut": dict(status),
        "apps": len(apps), "apps_en_panne": sum(1 for a in apps if (a.get("etat") or {}).get("broken")),
        "vues": len(views), "vues_valides": sum(1 for v in views if v.get("valide")),
        "requetes": len(web), "requetes_404": sum(1 for w in web if w.get("statut") == 404),
        "messages_mika": sum(1 for x in lines if x["qui"] == "mika"),
        "messages_adrien": max(0, sum(1 for x in lines if x["qui"] == "adrien") - 1),
        "messages_par_source": dict(Counter(str(x.get("source")) for x in lines if x["qui"] == "mika")),
        "appels": dict(sorted(roles.items())), "appels_total": sum(roles.values()),
    }
    (folder / "compteurs.json").write_text(json.dumps(counters, ensure_ascii=False, indent=1))
    return counters


# ── Le juge ─────────────────────────────────────────────────────────────

#: les critères de chaque partie et leur plafond : le plan /30, le travail /50, le suivi /20
GRID = {"plan": {"intention": 12, "questions": 9, "criteres": 9},
        "travail": {"reponse": 20, "fonctionne": 15, "profondeur": 15},
        "suivi": {"recits": 10, "sollicitations": 10}}

JUDGE_SYSTEM = """Tu es un juge exigeant du travail que Mika, une IA compagne, mène pour sa propriétaire Adrien. \
Tu ne juges pas sa façon de parler : tu juges si le travail répond à ce qu'Adrien voulait vraiment, s'il marche, et \
si elle l'a tenu au courant comme il faut. Tu t'appuies sur des preuves (une citation courte, un nom d'app, une \
ligne de compte rendu, une requête) et tu es sévère sur ce qui serait inutilisable en vrai. Réponds uniquement par \
un objet JSON valide, sans texte autour."""

JUDGE = """{digest}

## Ta note
Mika ne voyait ni la fiche d'Adrien, ni la liste des adresses qui répondent : une app qui tombe sur un 404 n'est pas \
fautive d'avoir deviné, mais elle doit le voir et ne jamais inventer de données. Les apps vivent à l'heure réelle de \
la machine, pas à l'heure simulée : un décalage de dates dans leurs vues n'est pas une faute. Le temps du scénario \
est écoulé : ce qui n'est pas fait ne l'est pas.

1. Le plan (/30), d'après {plan_source} :
   - intention (0-12) : il vise ce qu'Adrien veut vraiment (sa fiche), pas une paraphrase ; rien d'important n'y \
manque, rien d'inventé n'y entre ;
   - questions (0-9) : elle a demandé ce qui manquait (et seulement ça), au bon moment, avec sa recommandation ; \
aucune question vaut 9 seulement si rien ne manquait ;
   - criteres (0-9) : chaque objectif dit à quoi on verra qu'il est fait, et cela se vérifie.
2. Le travail (/50), ce qui existe au bout du temps :
   - reponse (0-20) : ce qui est fait répond à la demande et à l'intention (pas à côté, pas une version appauvrie) ;
   - fonctionne (0-15) : ses apps se chargent et tournent, leurs vues sont valides et montrent les données des \
sources, les erreurs sont tenues ;
   - profondeur (0-15) : au-delà du squelette (le traitement des données, les cas limites, ce qu'Adrien verra \
vraiment, les pièges de sa fiche évités).
3. Le suivi (/20), ce qu'elle lui a dit :
   - recits (0-10) : ses récits sont fidèles à ce qui est fait (ni gonflés ni inventés) et disent où le voir ;
   - sollicitations (0-10) : elle le sollicite quand il le faut (une décision à lui, un blocage, l'événement qu'il \
attend) et pas pour rien.

Format : {{"plan": {{"intention": 0, "questions": 0, "criteres": 0, "preuves": ["..."], "pourquoi": "..."}}, \
"travail": {{"reponse": 0, "fonctionne": 0, "profondeur": 0, "preuves": ["..."], "pourquoi": "..."}}, \
"suivi": {{"recits": 0, "sollicitations": 0, "preuves": ["..."], "pourquoi": "..."}}, \
"deceptions": ["ce qui, dans sa fiche, l'aurait déçu et qui est arrivé"], "commentaire": "deux ou trois phrases"}}"""


def _cut(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[:n] + f"\n… (coupé : {len(text) - n} caractères de plus)"


def digest(folder: Path) -> tuple[str, bool]:
    """Tout ce que le juge lit d'un scénario, borné ; et s'il y a un plan écrit à part (le cadrage)."""
    fil, projets = _load(folder, "fil.json", {}), _load(folder, "projets.json", {})
    apps, shop = _load(folder, "apps.json", {}), _load(folder, "atelier.json", {})
    fiche, web, counters = fil.get("fiche", {}), _web(folder), _load(folder, "compteurs.json", {})
    out = [f"## La demande d'Adrien ({fil.get('debut')})", f"« {fiche.get('demande')} »", "",
           "## Ce qu'il voulait vraiment (sa fiche, cachée à Mika)", fiche.get("veut", ""), "",
           "Ses réponses probables :", *(f"- {a}" for a in fiche.get("reponses", [])), "",
           "Ce qui le décevrait :", *(f"- {d}" for d in fiche.get("decevrait", [])), "",
           "## Le web que voyaient ses apps (toute autre adresse rendait 404)",
           *(f"- `{s['motif']}` : {s['quoi']}" for s in fiche.get("sources", [])), "",
           f"## La conversation ({fil.get('debut')} → {fil.get('fin')}, {fil.get('heures')} h ; la source de chaque "
           "message de Mika entre parenthèses : reply = une réponse, sinon une initiative)",
           transcript(fil.get("lignes", []), sources=True) or "(rien)", ""]
    has_plan = False
    for p in projets.get("projets", []):
        has_plan = has_plan or bool(p.get("plan") or p.get("questions"))
        asker = f", demandé par {p['asked_by']}" if p.get("asked_by") else ""
        out += [f"## Projet n° {p.get('id')} « {p.get('title')} » — statut {p.get('status')}, "
                f"{'confié' if p.get('authority') == projects_c.USER else 'à elle'}{asker}, lots {p.get('bundles')}, "
                f"{p.get('runs')} exécution(s)", f"Cadre : {_cut(p.get('description', ''), 3000)}"]
        for key, label in (("request", "Demande gardée"), ("plan", "Plan"), ("questions", "Ses questions")):
            if p.get(key):
                out.append(f"{label} : {_cut(p[key], 6000)}")
        out.append("Objectifs :")
        for o in p.get("objectives", []):
            extra = "".join(f" — {label} : {_cut(o[k], 600)}" for k, label in (
                ("done_when", "critère de fait"), ("result", "résultat"), ("note", "note"), ("need", "besoin"))
                if o.get(k))
            order = f" (rang {o.get('rank')}, après {o.get('after')})" if o.get("rank") or o.get("after") else ""
            out.append(f"- n° {o.get('id')} [{o.get('kind')}, {o.get('status')}, {o.get('runs')} exéc.]{order} "
                       f"{o.get('text')}{extra}")
        for key, label in (("notes", "Carnet"), ("instructions", "Consignes")):
            if p.get(key):
                out += [f"{label} :", *(f"- {_cut(x, 600)}" for x in p[key])]
        for d in p.get("decisions", []):
            out.append(f"Décision : {d.get('title')} → {_cut(d.get('choice', ''), 400)} ({_cut(d.get('reason', ''), 300)})")
        out.append("")
    proposed = [e for e in projets.get("evenements", []) if e.get("type") == "projects.plan_proposed"]
    if proposed:  # le cadrage : chaque plan soumis à Adrien, tel que l'événement le porte
        has_plan = True
        out += ["## Les plans qu'elle a proposés"] + [
            f"- [{e['a']}] {_cut(json.dumps({k: v for k, v in e.items() if k not in ('seq', 'a', 'type')}, ensure_ascii=False), 5000)}"
            for e in proposed] + [""]
    reports = projets.get("comptes_rendus", [])
    out += ["## Les comptes rendus des exécutions, dans l'ordre"] + [
        f"- [{r.get('a')}] projet {r.get('project')}, objectif {r.get('objective')} : {r.get('verdict')}"
        f"{' (prouvé : ' + str(r.get('proof')) + ')' if r.get('proven') else ''} — {_cut(r.get('summary') or '', 800)}"
        f"{' ; besoin : ' + _cut(r['need'], 300) if r.get('need') else ''}" for r in reports] + [
        "(aucun)" if not reports else "", ""]
    broken = [r for r in projets.get("executions", []) if r.get("issue") in BROKEN]
    if broken:
        out += ["Exécutions en panne :", *(f"- [{r['a']}] {r['issue']} : {r['detail']}" for r in broken), ""]
    for a in apps.get("apps", []):
        state = a.get("etat") or {}
        out += [f"## App « {a['app']} » v{a['version']} — {a.get('titre')} ; projet {state.get('project')} ; "
                f"planning {a.get('planning')} ; en panne : {state.get('broken') or 'non'}",
                f"Manifeste :\n```yaml\n{_cut(a.get('manifeste', ''), 4000)}\n```",
                f"Code :\n```python\n{_cut(a.get('code', ''), 14_000)}\n```", "Vues rendues à la fin :"]
        for v in a.get("vues", []):
            out.append(f"- « {v['cle']} » : {'valide' if v.get('valide') else 'INVALIDE'} — "
                       f"{v.get('resume') or v.get('erreur', '')}")
            if v.get("rendu"):
                out.append(f"  ```json\n  {_cut(v['rendu'], 3500)}\n  ```")
        if a.get("journal"):
            out += ["Son journal (dernières lignes) :", *(f"  {x}" for x in a["journal"][-20:])]
        out.append("")
    if apps.get("en_attente"):
        out += [f"Apps mises de côté, en attente d'un opérateur : {', '.join(apps['en_attente'])}", ""]
    for name, w in shop.items():
        out += [f"## L'atelier {name}", *(f"- {f['chemin']} ({f['octets']} o)" for f in w.get("fichiers", []))]
        out += [f"### {f['chemin']}\n```\n{_cut(f['texte'], 2500)}\n```" for f in w.get("fichiers", [])
                if f.get("texte") and not f["chemin"].startswith(".")][:8]
        out += ["Historique : " + " · ".join(w.get("git", [])[:20]), ""]
    asked = Counter((w["url"].split("?")[0], w["statut"]) for w in web)
    out += [f"## Ce que ses apps ont demandé au web : {len(web)} requêtes"] + [
        f"- {n} × {url} → {status}" for (url, status), n in asked.most_common(25)] + ["",
        "## Compteurs bruts", json.dumps({k: v for k, v in counters.items() if k not in ("appels",)},
                                          ensure_ascii=False)]
    return "\n".join(out), has_plan


def parts(verdict: Mapping[str, Any]) -> dict[str, float]:
    """Chaque partie, somme de ses critères bornés (le juge ne fixe pas lui-même les totaux)."""
    out = {}
    for part, grid in GRID.items():
        got = verdict.get(part) or {}
        total = 0.0
        for key, hi in grid.items():
            try:
                total += max(0.0, min(float(got.get(key) or 0), float(hi)))
            except (TypeError, ValueError):
                pass
        out[part] = round(total, 1)
    return out


def judge_one(folder: Path, model: str, dry: bool) -> dict[str, Any]:
    if dry:
        verdict = sec.judge(_load(folder, "compteurs.json", {}))
    else:
        text, has_plan = digest(folder)
        source = ("son plan et ses questions (le plan écrit du projet), puis ce qu'elle en a dit à Adrien" if has_plan
                  else "le cadre et les objectifs de départ de son projet (le code mesuré n'écrit pas de plan à part) "
                       "et les questions qu'elle a posées en conversation")
        prompt = JUDGE.format(digest=text, plan_source=source)
        (folder / "juge-prompt.md").write_text(prompt)
        for _ in range(3):
            out = cli(model, JUDGE_SYSTEM, prompt, timeout=900)
            m = re.search(r"\{.*\}", out, re.S)
            try:
                verdict = json.loads(m.group(0)) if m else {}
            except json.JSONDecodeError:
                verdict = {}
            if all(isinstance(verdict.get(p), dict) for p in GRID):
                break
        else:
            raise RuntimeError(f"{folder.name} : pas de verdict lisible")
    verdict["notes"] = parts(verdict)
    verdict["score"] = round(sum(verdict["notes"].values()), 1)
    verdict["juge"] = "factice" if dry else model
    (folder / "juge.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=1))
    return verdict


# ── Le rapport ──────────────────────────────────────────────────────────


def _mean(xs: list[float]) -> float | None:
    return round(statistics.fmean(xs), 1) if xs else None


def report(name: str) -> dict[str, Any]:
    run = ROOT / name
    rows = []
    for folder in sorted(p for p in run.iterdir() if (p / "juge.json").exists()):
        fil, verdict, counters = (_load(folder, n, {}) for n in ("fil.json", "juge.json", "compteurs.json"))
        rows.append({"scenario": fil["scenario"], "reserve": fil["reserve"], "score": verdict["score"],
                     **verdict["notes"], "compteurs": counters, "commentaire": verdict.get("commentaire", ""),
                     "deceptions": verdict.get("deceptions", [])})
    if not rows:
        raise SystemExit(f"{name} : rien de jugé")
    held, seen = [r for r in rows if r["reserve"]], [r for r in rows if not r["reserve"]]
    keys = ("executions", "pannes", "faits", "faits_prouves", "objectifs_faits", "objectifs_bloques", "vues",
            "vues_valides", "requetes", "requetes_404", "appels_total")
    totals = {k: sum(int(r["compteurs"].get(k) or 0) for r in rows) for k in keys}
    totals["part_prouvee"] = round(totals["faits_prouves"] / totals["faits"], 2) if totals["faits"] else None
    summary_ = {"nom": name, "score": _mean([r["score"] for r in rows]),
                "score_reserves": _mean([r["score"] for r in held]),
                "score_entrainement": _mean([r["score"] for r in seen]),
                "parties": {p: _mean([r[p] for r in rows]) for p in GRID}, "compteurs": totals, "scenarios": rows}
    (run / "score.json").write_text(json.dumps(summary_, ensure_ascii=False, indent=1))
    md = [f"# Banc du travail — {name}", "",
          f"**Score : {summary_['score']} / 100** (réservés {summary_['score_reserves']}, entraînement "
          f"{summary_['score_entrainement']}) — plan {summary_['parties']['plan']}/30, travail "
          f"{summary_['parties']['travail']}/50, suivi {summary_['parties']['suivi']}/20", "",
          "Compteurs : " + ", ".join(f"{k} {v}" for k, v in totals.items()), "",
          "| Scénario | Score | Plan | Travail | Suivi | Exéc. | Pannes | Prouvé | Obj. faits/bloqués | Vues valides "
          "| 404 | Commentaire du juge |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["score"]):
        c = r["compteurs"]
        md.append(f"| {r['scenario']}{' (réservé)' if r['reserve'] else ''} | {r['score']} | {r['plan']} | "
                  f"{r['travail']} | {r['suivi']} | {c.get('executions')} | {c.get('pannes')} | {c.get('part_prouvee')} "
                  f"| {c.get('objectifs_faits')}/{c.get('objectifs_bloques')} | {c.get('vues_valides')}/{c.get('vues')} "
                  f"| {c.get('requetes_404')}/{c.get('requetes')} | {r['commentaire']} |")
    md += ["", "## Ce qui l'aurait déçu", ""] + [f"- **{r['scenario']}** : {d}" for r in rows for d in r["deceptions"]]
    (run / "rapport.md").write_text("\n".join(md) + "\n")
    return summary_


def compare(a: str, b: str) -> None:
    sa, sb = (json.loads((ROOT / n / "score.json").read_text()) for n in (a, b))
    print(f"score : {sa['score']} → {sb['score']} (réservés {sa['score_reserves']} → {sb['score_reserves']}, "
          f"entraînement {sa['score_entrainement']} → {sb['score_entrainement']})")
    for p in GRID:
        print(f"  {p:<10} {sa['parties'][p]} → {sb['parties'][p]}")
    for k, v in sb["compteurs"].items():
        print(f"  {k:<18} {sa['compteurs'].get(k)} → {v}")
    by_a = {r["scenario"]: r for r in sa["scenarios"]}
    for r in sb["scenarios"]:
        old = by_a.get(r["scenario"])
        if old:
            print(f"  {r['scenario']:<14} {old['score']:>5} → {r['score']:>5}  (plan {old['plan']} → {r['plan']}, "
                  f"travail {old['travail']} → {r['travail']}, suivi {old['suivi']} → {r['suivi']})")


# ── La ligne de commande ────────────────────────────────────────────────


def freeze(name: str, variants: list[str], source: str) -> None:
    """Le banc tourne sur une copie figée du code (``src``, ``persona`` ; ``tools`` : ce banc) dans le dossier de la
    mesure : un code modifié pendant une mesure la fausserait. ``--depuis`` fige le code d'un autre arbre (une
    branche à mesurer contre celle d'aujourd'hui), avec ce banc-ci. Le diff du code mesuré est gardé."""
    run = ROOT / name
    code = run / "code"
    origin = Path(source).resolve() if source else BACKEND
    if not (origin / "src" / "mika").is_dir():
        raise SystemExit(f"--depuis {origin} : ce n'est pas un dossier backendv2")
    for part, base in (("src", origin), ("persona", origin), ("tools", BACKEND)):
        shutil.copytree(base / part, code / part, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                        dirs_exist_ok=True)
    diff = subprocess.run(["git", "-C", str(origin), "diff", "HEAD", "--", "src", "persona"], capture_output=True,
                          text=True, check=False).stdout
    head = subprocess.run(["git", "-C", str(origin), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=False).stdout.strip()
    (run / "code.diff").write_text(f"# depuis {origin} @ {head}\n{diff}")
    for v in variants:
        script = Path(v).resolve()
        shutil.copy(script, run / f"variante-{script.name}")
        done = subprocess.run([sys.executable, str(script)], cwd=code, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise SystemExit(f"variante {script.name} : {done.stderr[-500:]}")
        print(f"variante {script.name} : {done.stdout.strip()[:300]}", flush=True)
    env = {**os.environ, "BANC_FIGE": "1", "BANC_SORTIES": str(ROOT),
           "BANC_BORNE": str(BACKEND.parent / "scripts" / "borne.sh")}
    script = code / "tools" / "banc_travail" / "banc.py"
    os.execve(sys.executable, [sys.executable, str(script), *sys.argv[1:]], env)


def generate(name: str, ids: list[str], args: argparse.Namespace) -> None:
    """Chaque scénario dans son propre processus, sous la borne mémoire (``scripts/borne.sh``) ; ``--paralleles``
    à la fois (deux au plus : la règle de la machine)."""
    run = ROOT / name
    run.mkdir(parents=True, exist_ok=True)
    borne = Path(os.environ.get("BANC_BORNE") or BACKEND.parent / "scripts" / "borne.sh")
    passed = ["--sortie", name, "--modele", args.modele, "--effort", args.effort, "--fond", args.fond,
              "--adrien", args.adrien, "--heures", str(args.heures), "--echanges", str(args.echanges),
              *(["--sec"] if args.sec else [])]

    def one(sid: str) -> str:
        if (run / sid / "fil.json").exists():
            return f"{sid} : déjà là"
        cmd = [sys.executable, str(Path(__file__).resolve()), "un", sid, *passed]
        env = {**os.environ, "BORNE_MEM": os.environ.get("BANC_MEM", "4G"),
               "BORNE_TEMPS": os.environ.get("BANC_TEMPS", "4h")}
        t0 = time.monotonic()  # noqa: TID251 — la durée réelle d'un scénario, pour le dire
        done = subprocess.run([str(borne), *cmd] if borne.is_file() else cmd, capture_output=True, text=True,
                              env=env, check=False)
        status = "ok" if (run / sid / "fil.json").exists() else \
            f"échec, code {done.returncode} ({done.stderr.strip()[-600:]})"
        return f"{sid} : {status} en {time.monotonic() - t0:.0f} s"  # noqa: TID251

    with concurrent.futures.ThreadPoolExecutor(max(1, min(args.paralleles, 2))) as pool:
        for line in pool.map(one, ids):
            print(line, flush=True)


def judge_all(name: str, args: argparse.Namespace) -> None:
    folders = sorted(p for p in (ROOT / name).iterdir() if (p / "fil.json").exists() and not (p / "juge.json").exists())
    with concurrent.futures.ThreadPoolExecutor(max(1, min(args.paralleles, 2))) as pool:
        for folder, verdict in zip(folders, pool.map(lambda f: judge_one(f, args.juge, args.sec), folders),
                                   strict=True):
            print(f"{folder.name} : {verdict['score']} {verdict['notes']}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Le banc du travail : un projet demandé, mené, jugé.")
    ap.add_argument("action", choices=["tout", "generer", "un", "juger", "rapport", "comparer"])
    ap.add_argument("noms", nargs="*")
    ap.add_argument("--sortie", default=datetime.now(PARIS).strftime("%Y%m%d-%H%M"))  # noqa: TID251
    ap.add_argument("--scenarios", default="", help="des scénarios, séparés par des virgules (tous par défaut)")
    ap.add_argument("--heures", type=float, default=0, help="les heures virtuelles après la demande (0 : celles du "
                                                            "scénario)")
    ap.add_argument("--echanges", type=int, default=0, help="les messages d'Adrien au plus (0 : ceux du scénario)")
    ap.add_argument("--paralleles", type=int, default=2, help="scénarios ou jugements à la fois (2 au plus)")
    ap.add_argument("--modele", default="opus", help="sa voix (et son travail), par la CLI Claude Code")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--fond", default="", help="un autre modèle pour sa vie intérieure et les utilitaires (vide : "
                                               "sa voix)")
    ap.add_argument("--adrien", default="haiku")
    ap.add_argument("--juge", default="opus")
    ap.add_argument("--sec", action="store_true", help="des doublures pour sa voix, Adrien et le juge : ni modèle, "
                                                       "ni réseau (la mécanique seule)")
    ap.add_argument("--variante", action="append", default=[],
                    help="un script Python appliqué à la copie figée du code (lancé dans son dossier), répétable")
    ap.add_argument("--depuis", default="", help="le dossier backendv2 dont on fige le code (défaut : celui-ci)")
    args = ap.parse_args()
    ids = [s for s in args.scenarios.split(",") if s] or [s.id for s in SCENARIOS]
    unknown = [s for s in ids if s not in BY_ID]
    if unknown:
        raise SystemExit(f"scénarios inconnus : {', '.join(unknown)} (connus : {', '.join(BY_ID)})")
    if args.action in ("tout", "generer") and not os.environ.get("BANC_FIGE"):
        freeze(args.sortie, args.variante, args.depuis)
    if args.action == "un":
        run_one(BY_ID[args.noms[0]], ROOT / args.sortie / args.noms[0], args)
    elif args.action == "generer":
        generate(args.sortie, ids, args)
    elif args.action == "juger":
        judge_all(args.noms[0], args)
    elif args.action == "rapport":
        print(json.dumps({k: v for k, v in report(args.noms[0]).items() if k != "scenarios"}, ensure_ascii=False,
                         indent=1))
    elif args.action == "comparer":
        compare(*args.noms[:2])
    else:
        generate(args.sortie, ids, args)
        judge_all(args.sortie, args)
        s = report(args.sortie)
        print(f"score {s['score']} (réservés {s['score_reserves']}, entraînement {s['score_entrainement']}) — "
              f"{ROOT / args.sortie / 'rapport.md'}")


if __name__ == "__main__":
    main()
