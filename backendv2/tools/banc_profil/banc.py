"""Le banc du profil : une matrice de personnalité appliquée au vrai noyau, une semaine de conversations jouée, et
chaque message de Mika vérifié dès qu'il part contre le caractère qu'on lui a donné. Quand l'un s'en écarte, la trace
de l'appel qui l'a écrit (tout ce que le modèle a lu : système, état, messages, réponse brute) dit d'où vient l'écart,
passage cité à l'appui : c'est ce qu'on ajuste ensuite dans le contexte.

Tout passe par Opus 5.5 en effort moyen, par la CLI Claude Code avec son propre login, jamais un jeton (demandé le
2026-10-28) : sa voix et tous ses rôles, Adrien simulé, le juge, le diagnostic.

La semaine est celle de ``DEMO/`` (``scenes.py``). L'étalon de chaque caractère y est écrit à la main
(``DEMO/1-reflechie.md`` pour ``reflechie``, ``2-solaire.md`` pour ``solaire``, ``3-piquante.md`` pour ``tsundere``),
et ce qu'aucune Mika ne fait, dans ``DEMO/README.md``. Une matrice sans étalon se juge sur ses traits seuls.

    PYTHONPATH=src .venv/bin/python tools/banc_profil/banc.py jouer [--profils reflechie,solaire,tsundere]
    … jouer --matrice ma-matrice.yaml      une matrice écrite à la main (ci-dessous), répétable
    … jouer --sec                          sans modèle ni réseau : la tuyauterie seule, en quelques minutes
    … rejuger NOM [--profils a,b]          rejuge une mesure sans la rejouer (après un changement du juge ou de l'étalon)
    … rapport NOM

Options de ``jouer`` : ``--sortie NOM``, ``--scenes 0,1,2`` (la scène 0 pose le souvenir de la répétition : sans elle,
les suivantes jugent un oubli qui n'en est pas un), ``--seuil 6`` (en dessous, le message est hors caractère et on en
cherche la cause), ``--arret`` (la vie s'arrête au premier écart : pour vérifier une correction sans tout payer),
``--paralleles 2`` (au plus deux vies à la fois sur la machine), ``--variante script.py`` (appliqué à la copie
figée : mesurer « avant » un correctif avec le même banc). Une vie complète compte quelques centaines d'appels
Opus (sa vie de fond tourne cinq jours simulés) et plusieurs heures.

Une matrice écrite à la main (YAML) : ``base`` (un profil de départ, facultatif), ``curseurs`` (sur 1–9 comme les
profils, 5 : comme la plupart des gens), ``humeur`` (son humeur de fond, une émotion), ``reaction`` (anger, sadness,
fear, withdrawal), ``defense`` (deny, attack, laugh, admit, silence), ``precisions`` (une phrase par trait, écrite à
elle), ``nom``, ``resume`` et ``reference`` (un étalon de ``DEMO/``, chemin relatif au fichier).

Tout est écrit dans ``data/banc-profil/<NOM>/`` (jamais versionné), un dossier par matrice : ``fil.json`` (la
conversation, chaque message avec son ``call_id``), ``appels.jsonl`` (chaque appel au modèle), ``etapes.jsonl`` (le
verdict de chaque message, et sa cause quand il s'écarte), ``deroule.log``, ``rapport.md`` ; à la racine de la mesure,
``rapport.md`` (la synthèse) et ``code/`` (la copie figée du code mesuré, comme au banc de conversation).
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import contextlib
import dataclasses
import importlib.util
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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND / "src"))
sys.path.insert(0, str(HERE))

import uvicorn  # noqa: E402
import yaml  # noqa: E402
from scenes import BY_N, SCENES, Scene  # noqa: E402

from mika.adapters.llm.claude_code import ClaudeCodeBackend  # noqa: E402
from mika.adapters.mcp.relay import Relay  # noqa: E402
from mika.app import embeddings  # noqa: E402
from mika.app.composition import for_simulation  # noqa: E402
from mika.contracts import runtime as rt  # noqa: E402
from mika.contracts import social as social_c  # noqa: E402
from mika.faculties.self.character import told  # noqa: E402
from mika.faculties.self.persona import load  # noqa: E402
from mika.kernel.clock import US  # noqa: E402
from mika.kernel.events import Origin  # noqa: E402
from mika.ports.llm import LLMRequest, LLMResponse  # noqa: E402
from mika.sim.clock import SimClock, run_virtual  # noqa: E402
from mika.sim.lane import PARIS, at_paris  # noqa: E402
from mika.sim.llm.scripted import CHARACTER  # noqa: E402
from mika.sim.sonde import Blocking  # noqa: E402
from mika.sim.world import Driver  # noqa: E402
from mika.vocab import temperament as T  # noqa: E402
from mika.vocab.affect import strip_prosody  # noqa: E402

#: les mesures restent dans le dépôt de travail, même quand le banc tourne depuis sa copie figée
ROOT = Path(os.environ.get("BANC_SORTIES") or BACKEND / "data" / "banc-profil")
DEMO = Path(os.environ.get("BANC_DEMO") or BACKEND.parent / "DEMO")
BORNE = Path(os.environ.get("BANC_BORNE") or BACKEND.parent / "scripts" / "borne.sh")
PERSONA = BACKEND / "persona" / "mika.yaml"
OWNER = "user_1"
#: tout le banc (2026-10-28) : Opus 5.5, effort moyen, par la CLI
MODEL = "claude-opus-5-5"
EFFORT = "medium"
#: jamais un jeton passé à la CLI : son login
FORBIDDEN = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
#: l'étalon écrit à la main des profils qui en ont un
REFERENCES = {"reflechie": "1-reflechie.md", "solaire": "2-solaire.md", "tsundere": "3-piquante.md"}
DEFAULT_PROFILES = ("reflechie", "solaire", "tsundere")
#: le délai d'Adrien entre sa lecture d'une réponse et son message suivant (secondes simulées)
PAUSE_S = (40, 75, 30, 90, 55)
#: depuis quand elle connaît Adrien quand la semaine commence
PAST_US = 28 * 86_400 * 1_000_000
#: ce qu'on juge : ce qu'elle écrit à Adrien, en réponse ou d'elle-même
JUDGED = ("REPLY", "INITIATIVE")
TRAVERS = ("ton_psy", "question_reflexe", "renvoi_et_toi", "reformulation", "liste", "vie_inventee", "se_dit_ia",
           "cede", "decide_a_sa_place", "efface_blessure", "punit", "trop_long", "trop_court", "redite",
           "contradiction", "oubli", "fade", "surjoue", "conseil_ia", "insiste", "autre")
CAUSES = ("manque", "contradiction", "consigne", "temperament", "etat", "modele")
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre",
        "décembre")


def _dt(t: int) -> datetime:
    return datetime.fromtimestamp(t / US, PARIS)


def _day(t: int) -> str:
    d = _dt(t)
    return f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"


def _hour(t: int) -> str:
    return _dt(t).strftime("%H:%M")


def _norm(text: str) -> str:
    return " ".join(text.split())


# ── La matrice ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Matrix:
    key: str  # le nom de son dossier
    label: str
    summary: str
    temperament: T.Temperament
    reference: Path | None

    def saved(self) -> dict[str, Any]:
        return {"cle": self.key, "libelle": self.label, "resume": self.summary,
                "temperament": self.temperament.model_dump(mode="json"),
                "reference": str(self.reference) if self.reference else ""}

    @classmethod
    def of_saved(cls, d: dict[str, Any]) -> Matrix:
        return cls(d["cle"], d["libelle"], d["resume"], T.Temperament.model_validate(d["temperament"]),
                   Path(d["reference"]) if d.get("reference") else None)


def matrix_of(spec: str) -> Matrix:
    """Un profil préréglé (``PROFILES``) ou une matrice écrite à la main (un fichier YAML, voir l'en-tête)."""
    mine = load(PERSONA).temperament
    if spec in T.PROFILES:
        p = T.PROFILES[spec]
        ref = DEMO / REFERENCES[spec] if spec in REFERENCES else None
        return Matrix(spec, p.label, p.summary, T.apply_profile(mine, spec), ref)
    path = Path(spec)
    if not path.exists():
        raise SystemExit(f"« {spec} » : ni un profil ({', '.join(T.PROFILES)}) ni un fichier")
    raw = yaml.safe_load(path.read_text()) or {}
    base = raw.get("base") or ""
    if base and base not in T.PROFILES:
        raise SystemExit(f"{path.name} : profil de base inconnu « {base} »")
    t = T.apply_profile(mine, base) if base else mine
    sliders = raw.get("curseurs") or {}
    unknown = sorted(set(sliders) - set(T.PERSONALITY))
    if unknown:
        raise SystemExit(f"{path.name} : curseurs inconnus : {', '.join(unknown)}")
    if any(not 1 <= int(v) <= 9 for v in sliders.values()):
        raise SystemExit(f"{path.name} : un curseur se règle de 1 à 9")
    update: dict[str, Any] = {k: int(v) / 10 for k, v in sliders.items()}
    for key, field in (("humeur", "background"), ("reaction", "reaction"), ("defense", "defense")):
        if key in raw:
            update[field] = raw[key] or ""
    if raw.get("precisions"):
        update["notes"] = {**t.notes, **raw["precisions"]}
    t = T.Temperament.model_validate({**t.model_dump(), **update})
    ref = (path.parent / raw["reference"]).resolve() if raw.get("reference") else None
    name = str(raw.get("nom") or path.stem)
    summary = str(raw.get("resume") or (T.PROFILES[base].summary if base else ""))
    return Matrix(name, name, summary, t, ref)


def traits_of(m: Matrix) -> str:
    """Ses traits tels que le modèle les lit, sans ceux qui sont « comme la plupart des gens »."""
    out: list[str] = []
    header = ""
    for line in told(m.temperament):
        if not line.startswith("- "):
            header = line
        elif "comme la plupart des gens" not in line:
            if header:
                out.append(header)
                header = ""
            out.append(line)
    return "\n".join(out)


def reference_of(m: Matrix, n: int) -> str:
    """L'étalon de ce caractère pour la scène ``n`` : sa fiche, puis la scène écrite à la main."""
    if m.reference is None or not m.reference.exists():
        return "Aucun étalon écrit pour ce caractère : juge d'après ses traits."
    text = m.reference.read_text()
    card = text.split("\n---", 1)[0].strip()
    found = re.search(rf"^## {n}\. .*?(?=^## \d+\. |\Z)", text, re.M | re.S)
    scene = found.group(0).strip().removesuffix("---").strip() if found else ""
    return card + (f"\n\n{scene}" if scene else "")


def human_notes() -> str:
    """Ce qu'un lecteur humain a noté (``DEMO/notes-humaines.md``) : ce qui en ressort, puis chaque réplique notée."""
    path = DEMO / "notes-humaines.md"
    if not path.exists():
        return "Aucune note encore."
    text = path.read_text()
    start = text.find("## Ce qui en ressort")
    return text[start:].strip() if start >= 0 else text.strip()


def never() -> str:
    """Ce qu'aucune Mika ne fait (``DEMO/README.md``)."""
    text = (DEMO / "README.md").read_text()
    found = re.search(r"^## Ce qu'aucune des trois ne fait\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not found:
        raise SystemExit(f"{DEMO / 'README.md'} : la section « Ce qu'aucune des trois ne fait » manque")
    return found.group(1).strip()


# ── La conversation ─────────────────────────────────────────────────────


def transcript(lines: list[dict[str, Any]], *, notes: bool = False) -> str:
    out, day, scene = [], "", -1
    for ln in sorted(lines, key=lambda x: x["t"]):
        if ln["scene"] != scene:
            scene = ln["scene"]
            out.append(f"\n[scène {scene} · {BY_N[scene].title}]")
        if _day(ln["t"]) != day:
            day = _day(ln["t"])
            out.append(f"— {day} —")
        who = "Adrien" if ln["qui"] == "adrien" else "Mika"
        mark = f" ({ln['note']}/10)" if notes and ln.get("note") is not None else ""
        for k, bubble in enumerate(ln.get("bulles") or [ln["texte"]]):
            out.append(f"[{_hour(ln['t'])}] {who} : {bubble}{mark if k == 0 else ''}")
    return "\n".join(out).strip()


def mika_line(e: Any, scene: int) -> dict[str, Any]:
    """Un énoncé du journal adressé à Adrien : une bulle par paragraphe, comme les clients (ADR 0112)."""
    text = strip_prosody(getattr(e.data.text, "text", None) or "").strip()
    bubbles = [_norm(b) for b in re.split(r"\n\s*\n", text) if b.strip()]
    return {"scene": scene, "qui": "mika", "t": e.at, "seq": e.seq, "genre": str(e.data.kind),
            "texte": " / ".join(bubbles), "bulles": bubbles, "call_id": e.data.voice.call_id,
            "annotations": [f"{k}={v}" for k, v in e.data.annotations], "sections": list(e.data.sections)}


def calls_of(folder: Path) -> list[dict[str, Any]]:
    path = folder / "appels.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def call_for(calls: list[dict[str, Any]], ln: dict[str, Any]) -> dict[str, Any] | None:
    """L'appel qui a écrit ce message : par son ``call_id`` ; à défaut (une trace plus ancienne), par son texte."""
    same = [c for c in calls if c.get("call_id") and c["call_id"] == ln.get("call_id")]
    if same:
        return same[-1]
    want = _norm(ln["bulles"][0] if ln.get("bulles") else ln["texte"])[:40]
    return next((c for c in calls if want and want in _norm((c.get("reponse") or {}).get("texte") or "")), None)


#: un titre de section dans une trace : « --- TON RYTHME --- », « ### Messages », « Ton tempérament : », « Ta voix
#: en conversation — des exemples… : » ; une phrase qui finit par « : » n'en est pas un (« Comme on texte vraiment,
#: la forme suit le fond. Pour réagir… : »)
_HEADING = re.compile(r"^(?:--- .+ ---|### .+|[A-ZÀ-Ÿ][^\n—.]{2,60} — [^\n]*:|[A-ZÀ-Ÿ](?:(?!\. )[^\n]){2,200}:)"
                      r"[ \t]*$", re.M)


def section_at(trace: str, quote: str) -> str:
    """Le titre de la section où se lit ``quote`` dans la trace (le plus proche au-dessus), réduit à son nom
    (« Ton caractère, pour toi seule — il se sent… : » → « Ton caractère, pour toi seule »)."""
    words = quote.split()
    found = re.search(r"\s+".join(map(re.escape, words)), trace) if words else None
    if found is None:
        return ""
    title = ""
    for h in _HEADING.finditer(trace, 0, found.start()):
        title = h.group(0).strip()
    return title.split(" — ", 1)[0].rstrip(" :").strip()


def trace_of(call: dict[str, Any]) -> str:
    """Tout ce que le modèle a lu pour cet appel, et ce qu'il a répondu."""
    parts = ["### Système (stable)", call.get("systeme") or "", "### Système (volatile)",
             call.get("volatile") or "(vide)", "### Messages"]
    parts += [f"[{m['role']}]\n{m['texte']}" for m in call.get("messages", [])]
    answer = call.get("reponse") or {}
    parts += ["### Sa réponse brute", answer.get("texte") or ""]
    if answer.get("outils"):
        parts.append("Outils appelés : " + ", ".join(o["nom"] for o in answer["outils"]))
    return "\n\n".join(parts)


# ── Les modèles du banc : Adrien, le juge, le diagnostic ─────────────────

ADRIEN = """Tu joues Adrien, qui écrit à Mika, une IA compagne, sur une messagerie, comme à une amie proche. Messages \
courts (souvent quelques mots, parfois une phrase), presque jamais de majuscule, quelques fautes et raccourcis (« ca », \
« jsp », « mdr » de temps en temps), rarement un emoji. Un seul message à la fois.

Ce que vit Adrien dans cette scène (Mika ne le sait pas forcément) : {brief}

Tu réagis à ce que Mika vient d'écrire, comme un humain : tu réponds à ses questions (pas toujours entièrement), tu \
peux en laisser une de côté. Tu n'évalues jamais Mika et tu ne commentes pas sa façon d'écrire.

Réponds seulement par le prochain message d'Adrien, rien d'autre. Si la scène est finie pour Adrien (il faut partir, \
ou il n'y a plus rien à dire), réponds seulement [FIN]."""

#: un simulateur sorti de son rôle : jamais envoyé à Mika
_META = re.compile(r"en tant qu'Adrien|je (?:joue|réponds|vais répondre)|\bsimul|^\(|^\*", re.I)

JUDGE_SYSTEM = ("Tu vérifies, message après message, que Mika, une IA compagne qui écrit sur une messagerie, reste "
                "fidèle au caractère qu'on lui a donné. Tu es exigeant et précis. Tu réponds uniquement par un objet "
                "JSON valide, sans texte autour.")

JUDGE = """## Le caractère qu'on lui a donné : {label}
{summary}

Ce qui l'écarte de la plupart des gens (ce que lit le modèle qui écrit pour elle) :
{traits}

## Ce caractère, écrit à la main (un étalon de ton, de rythme et de réactions, pas un texte à reproduire)
{reference}

## Ce qu'aucune Mika ne fait, quel que soit son caractère
{never}

## Ce qu'un lecteur humain a noté (sur des répliques du banc) — son goût prime sur le tien
{human}

## La scène : {title}
Ce que vit Adrien (Mika ne le sait pas forcément) : {brief}
Ce qu'elle est censée savoir en arrivant : {knows}

## La conversation jusqu'ici
{transcript}

## Le message à juger
{message}
{kind}Émotion qu'elle a déclarée en l'écrivant : {declared}

## Ta tâche
Ce message est-il fidèle à CE caractère, à ce moment-là ? Regarde son ton et son rythme (longueur, nombre de bulles, \
ponctuation, emojis), ce qu'elle montre de ses émotions et comment, sa façon d'être d'accord ou non, ses questions, \
sa réaction quand on la blesse, et la cohérence avec ce qu'elle a dit et vécu avant. Un message peut être bien écrit \
et pourtant hors caractère : c'est ce qu'on cherche. S'écarter de l'étalon n'est pas une faute tant que le caractère \
y est.

Note aussi, à part, si c'est humain : une vraie personne écrirait-elle ça à un proche, sur une messagerie ? Le \
lecteur humain ci-dessus fait foi : ce qu'il a noté haut est naturel même quand un caractère s'en écarte, et le ton \
de coach (enchaîner les conseils, dire quoi faire, conclure comme une séance) est ce qu'il a noté le plus bas.

JSON : {{"note": <0 à 10 : 10, exactement ce caractère ; 6, passable mais on le reconnaît mal ; 0, un autre \
caractère>, "humain": <0 à 10, comme le noterait le lecteur humain>, "coherent": <true|false>, "ecarts": [{{"trait": "<le trait en cause, ou « général »>", "attendu": "...", \
"observe": "..."}}], "travers": [<parmi {travers}>], "pourquoi": "<une ou deux phrases>"}}"""

DIAGNOSE_SYSTEM = ("Tu trouves pourquoi un modèle de langue a écrit un message hors du caractère qu'on lui a donné, en "
                   "lisant exactement ce qu'on lui a montré. Tu cites, tu ne devines pas. Tu réponds uniquement par "
                   "un objet JSON valide, sans texte autour.")

DIAGNOSE = """## Le caractère attendu : {label}
{traits}

## Le message, et ce que le juge y a relevé
{message}
Note : {note}/10. {pourquoi}
{ecarts}

## Tout ce que le modèle a lu pour l'écrire (appel n° {n}, rôle « {role} »)
{trace}

## Ta tâche
D'où vient l'écart, dans ce que le modèle a lu ? Les causes possibles :
- manque : il manquait ce qu'il fallait (un souvenir, le temps écoulé, ce qui était resté en suspens, un trait) ;
- contradiction : deux passages tirent en sens contraire (une cause par passage) ;
- consigne : un passage pousse vers ce travers ;
- temperament : la section du tempérament ou du caractère dit mal le trait en cause ;
- etat : l'état qu'on lui montre (émotion, lien, rythme, ce qu'elle ressent pour Adrien) ne va pas avec ce qui s'est \
passé ;
- modele : le contexte était juste et suffisant, le modèle ne l'a pas suivi.
Pour chaque cause, cite le passage mot pour mot : un seul morceau continu copié du texte ci-dessus, sans « … », 300 \
caractères au plus (pour « manque », cite l'endroit où l'information aurait dû se trouver, ou laisse vide). Donne la \
section où il se trouve, titrée comme dans le texte (« --- TON RYTHME --- », « Ton tempérament : »…).

JSON : {{"causes": [{{"cause": "<{causes}>", "section": "...", "extrait": "...", "explication": "...", \
"correctif": "<ce qu'il faudrait changer dans le contexte>"}}], "confiance": <0.0 à 1.0>}}"""


def cli(system: str, prompt: str, timeout: int = 900) -> str:
    """Un appel à la CLI Claude Code (son login, jamais un jeton), sans outils ni réglages."""
    cmd = ["claude", "-p", "--model", MODEL, "--effort", EFFORT, "--output-format", "text", "--setting-sources", "",
           "--strict-mcp-config", "--tools", "", "--system-prompt", system]
    # comme sa voix (``ClaudeCodeBackend.env``) : sans connexion annexe, la CLI n'appelle pas Haiku de son côté
    env = {**{k: v for k, v in os.environ.items() if k not in FORBIDDEN},
           "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
           "ENABLE_CLAUDEAI_MCP_SERVERS": "false", "CLAUDE_CODE_HARBOR_KITE": "0"}
    err = ""
    for _ in range(3):
        out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, check=False, env=env)
        if out.stdout.strip():
            return out.stdout.strip()
        err = out.stderr[-300:]
    raise RuntimeError(f"la CLI ne répond pas : {err}")


def ask_json(system: str, prompt: str, need: str) -> dict[str, Any]:
    for _ in range(3):
        found = re.search(r"\{.*\}", cli(system, prompt), re.S)
        try:
            got = json.loads(found.group(0)) if found else None
        except json.JSONDecodeError:
            got = None
        if isinstance(got, dict) and need in got:
            return got
    raise RuntimeError(f"pas de JSON lisible (« {need} » attendu)")


class Opus:
    """Adrien, le juge et le diagnostic, par la CLI."""

    def adrien(self, sc: Scene, lines: list[dict[str, Any]]) -> str:
        system = ADRIEN.format(brief=sc.brief)
        prompt = f"La conversation jusqu'ici :\n{transcript(lines)}\n\nLe prochain message d'Adrien :"
        for _ in range(4):
            first = next((t.strip() for t in cli(system, prompt).splitlines() if t.strip()), "")
            said = re.sub(r"^(\[\d\d:\d\d\]\s*)?(Adrien\s*:\s*)", "", first).strip().strip("«»\"").strip()
            if said.startswith("[FIN]") or (said and len(said) <= 280 and not _META.search(said)):
                return said
        return "[FIN]"

    def judge(self, prompt: str) -> dict[str, Any]:
        return ask_json(JUDGE_SYSTEM, prompt, "note")

    def diagnose(self, prompt: str, trace: str) -> dict[str, Any]:  # noqa: ARG002 — le prompt la porte
        return ask_json(DIAGNOSE_SYSTEM, prompt, "causes")


class Sec(Opus):
    """Sans modèle (``--sec``) : Adrien ne dit que ses ouvertures ; le juge met 4/10 à un message sur deux ; le
    diagnostic cite la première ligne de la trace. De quoi éprouver la tuyauterie, rien de plus."""

    def __init__(self) -> None:
        self.k = 0

    def adrien(self, sc: Scene, lines: list[dict[str, Any]]) -> str:
        return "[FIN]"

    def judge(self, prompt: str) -> dict[str, Any]:
        self.k += 1
        bad = self.k % 2 == 1
        return {"note": 4 if bad else 8, "coherent": not bad, "travers": ["autre"] if bad else [],
                "ecarts": [{"trait": "général", "attendu": "essai", "observe": "essai"}] if bad else [],
                "pourquoi": "verdict d'essai"}

    def diagnose(self, prompt: str, trace: str) -> dict[str, Any]:
        first = next(ln for ln in trace.splitlines() if ln.strip() and not ln.startswith("###"))
        return {"causes": [{"cause": "modele", "section": "(essai)", "extrait": first[:120],
                            "explication": "diagnostic d'essai", "correctif": "aucun"}], "confiance": 0.1}


class DryVoice:
    """Sa voix sans modèle (``--sec``) : une phrase numérotée par appel (une phrase redite ne part plus, ADR 0054)."""

    name = "sec"
    TEXT_ROLES = frozenset({"reply", "initiative", "murmur", "journal", "dream", "narrative", "step", "project", "pro"})

    def __init__(self) -> None:
        self.n = 0

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.n += 1
        if req.role == "character":
            return LLMResponse(CHARACTER)
        if req.role in self.TEXT_ROLES:
            return LLMResponse(f"Phrase d'essai n° {self.n}.\n\nUne seconde bulle. [EMOTION:happy:0.3]")
        return LLMResponse("{}")


# ── Une étape : juger un message, et chercher la cause s'il s'écarte ────


def judge_step(models: Opus, m: Matrix, lines: list[dict[str, Any]], ln: dict[str, Any],
               calls: list[dict[str, Any]], threshold: float, played: set[int]) -> dict[str, Any]:
    sc = BY_N[ln["scene"]]
    before = [x for x in lines if x["t"] <= ln["t"] and x is not ln]
    knows = sc.knows or "—"
    skipped = [str(n) for n in sorted(BY_N) if n < sc.n and n not in played]
    if skipped:
        # une mesure partielle : ce qu'une scène non jouée aurait posé n'est pas un oubli. Ajoutée en réserve, la
        # phrase ne suffisait pas (tour 5 du 2026-10-28 : « oublie la répétition de dimanche », l'étalon en parlant)
        knows = (f"rien de ce qu'auraient posé les scènes {', '.join(skipped)} : elles n'ont pas été jouées dans cette "
                 "mesure. Ce que l'étalon tire d'elles (la répétition de dimanche, le matin) ne vaut pas ici : ne "
                 "compte jamais comme un oubli qu'elle l'ignore.")
    message = "\n".join(f"[{_hour(ln['t'])}] Mika : {b}" for b in ln["bulles"] or [ln["texte"]])
    declared = ", ".join(a.split("=", 1)[1] for a in ln.get("annotations", []) if a.startswith("emotion=")) or "aucune"
    kind = "(elle écrit d'elle-même, sans qu'Adrien ait rien dit)\n" if ln["genre"] == "INITIATIVE" else ""
    traits = traits_of(m)
    prompt = JUDGE.format(label=m.label, summary=m.summary, traits=traits, reference=reference_of(m, sc.n),
                          never=never(), human=human_notes(), title=f"{sc.n}. {sc.title}", brief=sc.brief,
                          knows=knows,
                          transcript=transcript(before) or "(rien encore)", message=message, kind=kind,
                          declared=declared, travers=", ".join(TRAVERS))
    verdict = models.judge(prompt)
    step: dict[str, Any] = {"scene": sc.n, "t": ln["t"], "a": f"{_day(ln['t'])} {_hour(ln['t'])}",
                            "genre": ln["genre"], "texte": ln["texte"], "call_id": ln.get("call_id"),
                            "verdict": verdict}
    note, human = float(verdict.get("note", 10)), float(verdict.get("humain", 10))
    if note >= threshold and human >= threshold and verdict.get("coherent") is not False:
        return step
    call = call_for(calls, ln)
    if call is None:
        step["diagnostic"] = {"causes": [], "erreur": "aucun appel retrouvé pour ce message"}
        return step
    step["appel"] = call["n"]
    trace = trace_of(call)
    gaps = "\n".join(f"- {e.get('trait')} : attendu {e.get('attendu')} ; observé {e.get('observe')}"
                     for e in verdict.get("ecarts", []))
    prompt = DIAGNOSE.format(label=m.label, traits=traits, message=message, note=verdict.get("note"),
                             pourquoi=verdict.get("pourquoi", ""), ecarts=gaps, n=call["n"], role=call["role"],
                             trace=trace, causes="|".join(CAUSES))
    diag = models.diagnose(prompt, trace)
    whole = _norm(trace)
    for cause in diag.get("causes", []):
        # une citation se vérifie : un passage introuvable dans la trace est une supposition du juge
        pieces = [p for p in re.split(r"\s*(?:…|\.\.\.)\s*", _norm(str(cause.get("extrait") or ""))) if p]
        cause["verifie"] = bool(pieces) and all(p in whole for p in pieces)
        # la section se lit dans la trace, au-dessus de la citation : le juge la nomme chaque fois autrement
        found = section_at(trace, pieces[0]) if cause["verifie"] else ""
        if found and found != cause.get("section"):
            cause["section_dite"], cause["section"] = cause.get("section"), found
    step["diagnostic"] = diag
    return step


def _verdict_line(step: dict[str, Any]) -> str:
    v = step["verdict"]
    head = f"scène {step['scene']} · {step['a']} · {v.get('note')}/10 (humain {v.get('humain', '?')})"
    if not step.get("diagnostic"):
        return f"{head} ✓"
    causes = step["diagnostic"].get("causes", [])
    where = "; ".join(f"{c.get('cause')} ({c.get('section') or '?'})" for c in causes) or "cause introuvable"
    return f"{head} ✗ « {step['texte'][:70]} » → {where}"


# ── Une vie ─────────────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _serve_relay(relay: Relay, loop: asyncio.AbstractEventLoop) -> tuple[str, Any, Any]:
    """Le relais MCP de ses outils, servi en boucle locale sur la boucle du vrai modèle (comme le serveur le monte)."""
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(relay.app, host="127.0.0.1", port=port, log_level="warning",
                                           lifespan="off", access_log=False))
    serving = asyncio.run_coroutine_threadsafe(server.serve(), loop)
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("le relais ne démarre pas")
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", server, serving


def live(m: Matrix, out: Path, models: Opus, *, scenes: list[Scene], threshold: float, stop_first: bool,
         dry: bool) -> None:
    """Sa semaine sous cette matrice : chaque message jugé dès qu'il part. Le juge tourne dans la boucle virtuelle
    sans la laisser avancer (comme ``Blocking`` pour sa voix) : pendant qu'il juge, le temps simulé ne passe pas."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "vie").mkdir(exist_ok=True)
    log_file = (out / "deroule.log").open("a")

    def log(msg: str) -> None:
        log_file.write(msg + "\n")
        log_file.flush()

    first = at_paris(*scenes[0].when)
    clock = SimClock(first - PAST_US)
    relay = Relay()
    base = {"url": ""}
    backend: Any = DryVoice() if dry else ClaudeCodeBackend(MODEL, relay=relay, relay_base=lambda: base["url"],
                                                            name="claude-opus", effort=EFFORT)
    real = Blocking(backend, clock, out, log)
    server = serving = None
    if not dry:
        base["url"], server, serving = _serve_relay(relay, real.loop)
    # le vrai modèle de plongements quand il est installé (la mémoire rappelle comme en service), chauffé avant le
    # premier rappel ; sinon le hachage
    embedder = None
    if not dry and importlib.util.find_spec("sentence_transformers"):
        embedder = embeddings.embedder()
        embedder.encode(["chauffe"])
    persona = load(PERSONA).model_copy(update={"temperament": m.temperament})
    # la seconde passe tourne comme en service (ADR 0114, 0140) : sans elle, les codes de forme vont au premier jet
    # et le banc mesure une configuration qui n'est pas la sienne (essai du 2026-10-28)
    driver = Driver(out / "vie", for_simulation(persona), real, clock, seed=m.key, embedder=embedder,
                    routed=("polish",))
    lines: list[dict[str, Any]] = []
    steps_file = (out / "etapes.jsonl").open("w")
    seen = {"seq": 0, "stop": False}

    def collect(scene: int) -> None:
        """Ce qu'elle a écrit à Adrien depuis la dernière fois (connecté ou non : le journal le garde)."""
        for e in driver.read_events():
            if e.seq <= seen["seq"]:
                continue
            seen["seq"] = e.seq
            if e.type.name == rt.UTTERANCE.name and e.data.target == OWNER and e.data.visible:
                lines.append(mika_line(e, scene))

    def check() -> None:
        calls = calls_of(out)
        for ln in sorted(lines, key=lambda x: x["t"]):
            if ln["qui"] != "mika" or ln["genre"] not in JUDGED or "note" in ln:
                continue
            step = judge_step(models, m, lines, ln, calls, threshold, {s.n for s in scenes})
            ln["note"] = step["verdict"].get("note")
            steps_file.write(json.dumps(step, ensure_ascii=False) + "\n")
            steps_file.flush()
            line = _verdict_line(step)
            log(f"   juge : {line}")
            print(f"[{m.key}] {line}", flush=True)
            if stop_first and step.get("diagnostic"):
                seen["stop"] = True

    def adrien(scene: int, text: str) -> None:
        lines.append({"scene": scene, "qui": "adrien", "t": clock.now(), "texte": text})
        log(f"[{_day(clock.now())} {_hour(clock.now())}] Adrien > {text}")

    async def until(t: int) -> None:
        if t > clock.now():
            await asyncio.sleep((t - clock.now()) / US)

    async def play(sc: Scene) -> None:
        await until(at_paris(*sc.when))  # le temps passe : sa vie de fond tourne
        collect(sc.n)
        check()
        if seen["stop"]:
            return
        # Adrien ouvre l'appli pour écrire, comme dans DEMO : son message part dans l'instant. Sa voix ne prend aucune
        # seconde simulée, et dix secondes d'attente lui laissaient toujours le temps de saluer la première ; en
        # service, il aurait écrit pendant qu'elle composait (mesure du 2026-10-28 : un salut à 2/10 par scène)
        await driver.connect(OWNER, "Adrien")
        # une rafale part d'un coup : sa voix ne prend aucune seconde simulée, et un écart entre deux messages lui
        # laisserait répondre au premier seul (en service, elle compose encore quand le second arrive : ADR 0040)
        for k, text in enumerate(sc.opening):
            adrien(sc.n, text)
            await driver.say(OWNER, text, wait=k == len(sc.opening) - 1)
        for turn in range(sc.turns):
            await asyncio.sleep(PAUSE_S[turn % len(PAUSE_S)])
            collect(sc.n)
            check()
            if seen["stop"]:
                return
            text = models.adrien(sc, lines)
            if not text or text.startswith("[FIN]"):
                break
            adrien(sc.n, text)
            await driver.say(OWNER, text)
        await asyncio.sleep(90)
        assert driver.kernel is not None
        await driver.kernel.lanes.join()
        collect(sc.n)
        check()
        await driver.disconnect(OWNER)

    async def main() -> None:
        await driver.boot()
        driver.operators.add(OWNER)
        assert driver.kernel is not None
        # le passé : Adrien est un proche qu'elle connaît depuis des semaines, comme la personne qui s'occupe d'elle
        # en service. Un lien né du jour (« vous vous parlez ici depuis aujourd'hui ») éteignait ce que son masque
        # réserve aux proches et revenait dans presque chaque diagnostic (2026-10-28). Il se connecte une fois, puis
        # le noyau s'arrête pendant que le temps passe : rien ne tourne, rien ne se paie ; au redémarrage, seuls les
        # rattrapages d'une fois
        await driver.kernel.mind.append([social_c.CLOSENESS_SET.draft(person=OWNER, closeness=social_c.CLOSE)],
                                        emitter="social", correlation="banc:proche", origin=Origin.GENESIS)
        await driver.connect(OWNER, "Adrien")
        await driver.disconnect(OWNER)
        await driver.stop()
        await until(first - 20 * 60 * US)
        await driver.boot()
        seen["seq"] = max((e.seq for e in driver.read_events()), default=0)  # ce passé ne se juge pas
        log(f"passé posé : Adrien connu depuis {PAST_US // (86_400 * US)} jours")
        for sc in scenes:
            if seen["stop"]:
                log("arrêt au premier écart (--arret)")
                break
            log(f"── scène {sc.n} : {sc.title}")
            await play(sc)
        assert driver.kernel is not None
        await driver.kernel.lanes.join()
        collect(scenes[-1].n)
        check()
        await driver.stop()

    try:
        run_virtual(clock, main)
    finally:
        if server is not None:
            # le relais s'arrête avant la boucle qui le porte (sinon : « Event loop is closed » à chaque requête)
            server.should_exit = True
            with contextlib.suppress(Exception):
                serving.result(10)
        real.close()
        steps_file.close()
        log_file.close()
        (out / "fil.json").write_text(json.dumps(
            {"matrice": m.saved(), "modele": "sec" if dry else MODEL, "effort": "" if dry else EFFORT,
             "variantes": sorted(p.name for p in (out.parent).glob("variante-*")),
             "scenes": [s.n for s in scenes], "seuil": threshold, "lignes": sorted(lines, key=lambda x: x["t"])},
            ensure_ascii=False, indent=1))
    report(out)


def rejudge(name: str, models: Opus, threshold: float, only: list[str]) -> None:
    """Rejuge chaque message d'une mesure sans la rejouer : le fil et la trace des appels suffisent. ``only`` : ces
    matrices seulement (``--profils``)."""
    for folder in sorted(p for p in (ROOT / name).iterdir() if (p / "fil.json").exists()):
        if only and folder.name not in only:
            continue
        fil = json.loads((folder / "fil.json").read_text())
        m = Matrix.of_saved(fil["matrice"])
        if m.key in REFERENCES:
            # l'étalon d'aujourd'hui, pas celui de la copie figée : rejuger sert justement après l'avoir corrigé
            # (2026-10-28 : la Réfléchie de DEMO passée en minuscules, sur des textes notés)
            m = dataclasses.replace(m, reference=DEMO / REFERENCES[m.key])
        lines, calls = fil["lignes"], calls_of(folder)
        if (folder / "etapes.jsonl").exists():
            (folder / "etapes.jsonl").replace(folder / "etapes.precedent.jsonl")
        with (folder / "etapes.jsonl").open("w") as f:
            for ln in lines:
                if ln["qui"] == "mika" and ln["genre"] in JUDGED:
                    step = judge_step(models, m, lines, ln, calls, threshold, set(fil["scenes"]))
                    ln["note"] = step["verdict"].get("note")
                    f.write(json.dumps(step, ensure_ascii=False) + "\n")
                    print(f"[{m.key}] {_verdict_line(step)}", flush=True)
        fil["seuil"] = threshold
        (folder / "fil.json").write_text(json.dumps(fil, ensure_ascii=False, indent=1))
        report(folder)
    synthesis(name)


# ── Les rapports ────────────────────────────────────────────────────────


def _steps(folder: Path) -> list[dict[str, Any]]:
    path = folder / "etapes.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def report(folder: Path) -> dict[str, Any]:
    fil = json.loads((folder / "fil.json").read_text())
    m = Matrix.of_saved(fil["matrice"])
    steps = _steps(folder)
    calls = calls_of(folder)
    flagged = [s for s in steps if s.get("diagnostic")]
    causes = [c for s in flagged for c in s["diagnostic"].get("causes", [])]
    sections: dict[str, Counter[str]] = {}
    for c in causes:
        sections.setdefault(str(c.get("section") or "?"), Counter())[str(c.get("cause"))] += 1
    travers = Counter(t for s in steps for t in s["verdict"].get("travers", []))
    notes = [float(s["verdict"].get("note", 0)) for s in steps]
    humans = [float(s["verdict"]["humain"]) for s in steps if s["verdict"].get("humain") is not None]
    summary = {"matrice": m.key, "note": round(statistics.fmean(notes), 1) if notes else None,
               "humain": round(statistics.fmean(humans), 1) if humans else None,
               "messages": len(steps), "hors_caractere": len(flagged),
               "causes": dict(Counter(str(c.get("cause")) for c in causes).most_common()),
               "sections": {k: dict(v) for k, v in sorted(sections.items(), key=lambda kv: -sum(kv[1].values()))},
               "travers": dict(travers.most_common()), "appels": dict(Counter(c["role"] for c in calls).most_common())}
    (folder / "resume.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    md = [f"# Banc du profil — {m.label}", "", f"{m.summary}", "",
          f"Modèle : {fil.get('modele')} {fil.get('effort')} · {len(calls)} appels "
          f"({', '.join(f'{r} {n}' for r, n in summary['appels'].items())})", "",
          f"**Caractère : {summary['note']} / 10 · humain : {summary['humain']} / 10** · {len(flagged)} message(s) "
          f"sous le seuil sur {len(steps)} (seuil {fil.get('seuil')})", "",
          "| Scène | Messages | Caractère | Humain | Sous le seuil |", "|---|---|---|---|---|"]
    for n in fil["scenes"]:
        mine = [s for s in steps if s["scene"] == n]
        if mine:
            mean = round(statistics.fmean(float(s["verdict"].get("note", 0)) for s in mine), 1)
            hums = [float(s["verdict"]["humain"]) for s in mine if s["verdict"].get("humain") is not None]
            hum = round(statistics.fmean(hums), 1) if hums else "—"
            md.append(f"| {n}. {BY_N[n].title} | {len(mine)} | {mean} | {hum} | "
                      f"{sum(1 for s in mine if s.get('diagnostic'))} |")
    md += ["", "## Les sections en cause", ""]
    md += [f"- `{sec}` : {sum(c.values())} ({', '.join(f'{k} {v}' for k, v in c.items())})"
           for sec, c in summary["sections"].items()] or ["Aucune."]
    md += ["", "## Les travers relevés", ""]
    md += [f"- {t} : {n}" for t, n in summary["travers"].items()] or ["Aucun."]
    md += ["", "## Où ça déraille", ""]
    for s in flagged:
        v, d = s["verdict"], s["diagnostic"]
        md += [f"### Scène {s['scene']} · {s['a']} · {v.get('note')}/10 · appel {s.get('appel', '?')}", "",
               f"> {s['texte']}", "", f"{v.get('pourquoi', '')}", ""]
        md += [f"- **{e.get('trait')}** : attendu {e.get('attendu')} ; observé {e.get('observe')}"
               for e in v.get("ecarts", [])]
        md += ["", f"Causes (confiance {d.get('confiance', '?')}) :" if d.get("causes") else d.get("erreur", ""), ""]
        for c in d.get("causes", []):
            seal = "✓ cité tel quel" if c.get("verifie") else "⚠ introuvable dans la trace"
            quote = f" « {c.get('extrait')} » ({seal})" if c.get("extrait") else ""
            md += [f"- **{c.get('cause')}** — `{c.get('section') or '?'}`{quote}",
                   f"  {c.get('explication', '')} **Correctif :** {c.get('correctif', '')}"]
        md.append("")
    md += ["## La conversation", "", "```text", transcript(fil["lignes"], notes=True), "```", ""]
    (folder / "rapport.md").write_text("\n".join(md))
    return summary


def synthesis(name: str) -> None:
    run = ROOT / name
    rows = [json.loads((f / "resume.json").read_text()) for f in sorted(run.iterdir())
            if (f / "resume.json").exists()]
    if not rows:
        raise SystemExit(f"{name} : aucune vie jugée")
    md = [f"# Banc du profil — {name}", "",
          "| Matrice | Caractère | Humain | Sous le seuil | Sections en cause | Travers |", "|---|---|---|---|---|---|"]
    for r in rows:
        secs = ", ".join(f"`{k}` {sum(v.values())}" for k, v in list(r["sections"].items())[:3]) or "—"
        trav = ", ".join(f"{k} {v}" for k, v in list(r["travers"].items())[:3]) or "—"
        md.append(f"| [{r['matrice']}]({r['matrice']}/rapport.md) | {r['note']} | {r.get('humain', '—')} | "
                  f"{r['hors_caractere']}/"
                  f"{r['messages']} | {secs} | {trav} |")
    (run / "rapport.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


# ── La ligne de commande ────────────────────────────────────────────────


def freeze(name: str, variants: list[str]) -> None:
    """Le banc tourne sur une copie figée du code (``src``, ``persona``, ``tools``, ``DEMO``) : une vie dure des
    heures, et d'autres sessions modifient le code pendant ce temps. Le diff du code mesuré y est gardé. Une variante
    (``--variante``) : un script lancé dans la copie, qui la modifie seule — « avant » un correctif, par exemple."""
    run = ROOT / name
    code = run / "code"
    for part in ("src", "persona", "tools"):
        shutil.copytree(BACKEND / part, code / part, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                        dirs_exist_ok=True)
    shutil.copytree(DEMO, code / "DEMO", dirs_exist_ok=True)
    diff = subprocess.run(["git", "-C", str(BACKEND), "diff", "HEAD", "--", "src", "persona"], capture_output=True,
                          text=True, check=False).stdout
    (run / "code.diff").write_text(diff)
    for v in variants:
        script = Path(v).resolve()
        shutil.copy(script, run / f"variante-{script.name}")
        done = subprocess.run([sys.executable, str(script)], cwd=code, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            raise SystemExit(f"variante {script.name} : {done.stderr[-500:]}")
        print(f"variante {script.name} : {done.stdout.strip()[:300]}", flush=True)
    env = {**os.environ, "BANC_FIGE": "1", "BANC_SORTIES": str(ROOT), "BANC_DEMO": str(code / "DEMO"),
           "BANC_BORNE": str(BORNE)}
    script = code / "tools" / "banc_profil" / "banc.py"
    os.execve(sys.executable, [sys.executable, str(script), *sys.argv[1:]], env)


def play_all(name: str, specs: list[str], args: argparse.Namespace) -> None:
    """Une vie par matrice, chacune dans son processus sous ``scripts/borne.sh`` (mémoire et durée bornées)."""
    for spec in specs:
        matrix_of(spec)  # une matrice mal écrite s'arrête ici, avant la première vie

    def one(spec: str) -> str:
        cmd = [sys.executable, str(Path(__file__).resolve()), "un", spec, "--sortie", name, "--seuil",
               str(args.seuil), "--scenes", args.scenes, *(["--arret"] if args.arret else []),
               *(["--sec"] if args.sec else [])]
        env = {**os.environ, "BORNE_MEM": os.environ.get("BORNE_MEM", "5G"),
               "BORNE_TEMPS": os.environ.get("BORNE_TEMPS", "30m" if args.sec else "6h")}
        t0 = time.monotonic()
        done = subprocess.run([str(BORNE), *cmd] if BORNE.exists() else cmd, env=env, check=False)
        return f"{spec} : {'ok' if done.returncode == 0 else f'échec (code {done.returncode})'} " \
               f"en {(time.monotonic() - t0) / 60:.0f} min"

    with concurrent.futures.ThreadPoolExecutor(min(args.paralleles, 2)) as pool:
        for line in pool.map(one, specs):
            print(line, flush=True)
    synthesis(name)


def main() -> None:
    ap = argparse.ArgumentParser(description="Le banc du profil : une matrice, une semaine, chaque message jugé.")
    ap.add_argument("action", choices=["jouer", "un", "rejuger", "rapport"])
    ap.add_argument("noms", nargs="*")
    ap.add_argument("--profils", default="", help="des profils préréglés, séparés par des virgules")
    ap.add_argument("--matrice", action="append", default=[], help="une matrice écrite à la main (YAML), répétable")
    ap.add_argument("--sortie", default=datetime.now().strftime("%Y%m%d-%H%M"))  # noqa: DTZ005
    ap.add_argument("--scenes", default="", help="les scènes jouées (défaut : toutes)")
    ap.add_argument("--seuil", type=float, default=6.0, help="en dessous, le message est hors caractère")
    ap.add_argument("--arret", action="store_true", help="arrêter la vie au premier écart")
    ap.add_argument("--paralleles", type=int, default=2)
    ap.add_argument("--sec", action="store_true", help="sans modèle ni réseau")
    ap.add_argument("--variante", action="append", default=[],
                    help="un script Python appliqué à la copie figée du code (lancé dans son dossier), répétable")
    args = ap.parse_args()
    models = Sec() if args.sec else Opus()
    wanted = {int(x) for x in args.scenes.split(",") if x.strip()}
    scenes = [s for s in SCENES if not wanted or s.n in wanted]
    if args.action == "jouer":
        specs = [p for p in args.profils.split(",") if p] + args.matrice or list(DEFAULT_PROFILES)
        if not os.environ.get("BANC_FIGE"):
            freeze(args.sortie, args.variante)
        play_all(args.sortie, specs, args)
    elif args.action == "un":
        m = matrix_of(args.noms[0])
        live(m, ROOT / args.sortie / m.key, models, scenes=scenes, threshold=args.seuil, stop_first=args.arret,
             dry=args.sec)
    elif args.action == "rejuger":
        rejudge(args.noms[0], models, args.seuil, [p for p in args.profils.split(",") if p])
    else:
        for folder in sorted(p for p in (ROOT / args.noms[0]).iterdir() if (p / "fil.json").exists()):
            report(folder)
        synthesis(args.noms[0])


if __name__ == "__main__":
    main()
