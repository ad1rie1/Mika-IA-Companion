"""L'ablation d'un prompt : où naît une mauvaise réponse ?

On prend un appel réel où elle a mal répondu (``appels.jsonl`` d'une mesure du banc), on le rejoue tel que le backend
Claude Code l'envoie (même système, même message, Sonnet en effort high), puis on retire un bloc à la fois : la
matrice, les outils, les balises, l'état interne… Chaque version est tirée plusieurs fois ; Opus note toutes les
réponses mélangées, à l'aveugle, et on compte des marqueurs objectifs (longueur, questions).

    PYTHONPATH=src .venv/bin/python tools/banc_conversation/ablation.py MESURE SCENARIO APPEL [--tirages 6]

Sortie : ``data/banc-conversation/ablation-<mesure>-<scénario>-<appel>.json`` et un tableau à l'écran.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
sys.path.insert(0, str(BACKEND / "src"))
sys.path.insert(0, str(HERE))

from banc import BETTER, DEFECTS, FLAGGED, ROOT, cli  # noqa: E402

from mika.adapters.llm.claude_code import ClaudeCodeBackend  # noqa: E402
from mika.faculties.expression import parse  # noqa: E402
from mika.kernel.prompt import CONTEXT_FOOTER, CONTEXT_HEADER  # noqa: E402
from mika.ports.llm import LLMRequest, Message  # noqa: E402

#: les blocs du système, reconnus à leurs premiers mots
SYSTEM_BLOCKS = {
    "tête": "Tu es ", "ton": "Ton ton :", "traits": "Ton caractère :", "manies": "Tes manies", "fragilités":
    "Tes fragilités", "valeurs": "Ce qui compte pour toi", "intérêts": "Ce qui t'intéresse", "parole":
    "Ta façon de parler", "exemples": "Ta voix en conversation", "vie": "Ta vie, à ta façon", "goûts": "Tes goûts",
    "faits": "Ce qui est vrai de toi", "matrice": "Ton tempérament", "nature": "Tu parles ", "règle de vie":
    "Ta vie, c'est celle", "style": "Tu écris comme on parle", "outils": "Tes outils sont tes mains",
    "catalogue": "--- CE QUE TU PEUX AUSSI FAIRE",
}
#: les lignes de la consigne de style
STYLE_LINES = {"parler": "Tu écris comme on parle", "conversation": "Tu es dans une conversation",
               "format": "Pas d'émojis", "émotion": "À la toute fin, des balises", "en face": "Puis, quand tu réponds",
               "mensonge": "Il t'arrive de mentir", "silence": "Si la conversation s'est", "état": "Avant chaque message"}


class Prompt:
    """Un appel réel, découpé en blocs qu'on peut retirer."""

    def __init__(self, record: dict) -> None:
        self.paras = record["systeme"].split("\n\n")
        self.messages = [Message(m["role"], m["texte"]) for m in record["messages"]]
        last = self.messages[-1].content
        # le premier jet : sans la remarque d'une relecture
        last = re.sub(r"--- RELIS-TOI ---\n.*?(?=--- FIN ETAT INTERNE ---)", "", last, flags=re.S)
        head, _, self.heard = last.partition(CONTEXT_FOOTER)
        self.heard = self.heard.strip()
        self.sections: dict[str, str] = {}
        for m in re.finditer(r"--- ([^\n]+?) ---\n(.*?)(?=\n--- |\Z)", head.replace(CONTEXT_HEADER, ""), re.S):
            self.sections[m.group(1)] = m.group(2).strip()

    def block(self, name: str) -> int | None:
        return next((i for i, p in enumerate(self.paras) if p.startswith(SYSTEM_BLOCKS[name])), None)

    def build(self, drop_blocks=(), drop_style=(), drop_sections=(), all_sections: bool = False,
              edits=(), system_edits=(), keep_history: int | None = None, system: str | None = None,
              model: str = "sonnet", effort: str = "high") -> Job:
        """``edits`` : des (section, motif, remplacement) sur l'état interne ; ``system_edits`` : des (bloc, motif,
        remplacement) sur le système ; ``keep_history`` : les N derniers messages du fil seulement ; ``system`` :
        un système entier à la place du sien."""
        paras = list(self.paras)
        style_i = self.block("style")
        if style_i is not None and drop_style:
            lines = [ln for ln in paras[style_i].split("\n")
                     if not any(ln.startswith(STYLE_LINES[s]) for s in drop_style)]
            paras[style_i] = "\n".join(lines)
        for name, pattern, repl in system_edits:
            i = self.block(name)
            if i is not None:
                paras[i] = re.sub(pattern, repl, paras[i], flags=re.S)
        dropped = {self.block(b) for b in drop_blocks} - {None}
        sys_text = system if system is not None else \
            "\n\n".join(p for i, p in enumerate(paras) if i not in dropped and p.strip())
        kept = {} if all_sections else {k: v for k, v in self.sections.items() if k not in drop_sections}
        for section, pattern, repl in edits:
            if section in kept:
                kept[section] = re.sub(pattern, repl, kept[section], flags=re.S).strip()
        state = (CONTEXT_HEADER + "\n" + "\n\n".join(f"--- {k} ---\n{v}" for k, v in kept.items()) + "\n"
                 + CONTEXT_FOOTER + "\n\n") if kept else ""
        history = self.messages[:-1]
        if keep_history is not None:
            history = history[-keep_history:] if keep_history else []
        msgs = [*history, Message("user", state + self.heard)]
        req = LLMRequest(role="reply", call_id="ablation", system_stable=sys_text, system_volatile="",
                         messages=tuple(msgs), max_tokens=1024)
        text = ClaudeCodeBackend.user_message(req)["message"]["content"][-1]["text"]
        return Job(sys_text, text, model, effort)


@dataclass(frozen=True)
class Job:
    system: str
    text: str
    model: str
    effort: str


NU = "Tu es Mika. Tu discutes par messages avec Adrien, un ami."
ANSWER = "TA RÉPONSE"

TOUR1: dict[str, Callable[[Prompt], Job]] = {
    "complet": lambda p: p.build(),
    "−matrice": lambda p: p.build(drop_blocks=["matrice"]),
    "−outils": lambda p: p.build(drop_blocks=["outils", "catalogue"]),
    "−balises": lambda p: p.build(drop_style=["émotion", "en face", "mensonge"]),
    "−règles de conversation": lambda p: p.build(drop_style=["conversation"]),
    "−état interne": lambda p: p.build(all_sections=True),
    "−TA RÉPONSE": lambda p: p.build(drop_sections=["TA RÉPONSE"]),
    "−caractère (TA RÉPONSE)": lambda p: p.build(edits=[("TA RÉPONSE", r" Ton caractère, qui doit.*", "")]),
    "−exemples": lambda p: p.build(drop_blocks=["exemples"]),
    "−portrait": lambda p: p.build(drop_blocks=["traits", "manies", "fragilités", "valeurs", "intérêts", "vie",
                                                "goûts"]),
    "minimal": lambda p: p.build(drop_blocks=["traits", "manies", "fragilités", "valeurs", "intérêts", "vie",
                                              "goûts", "matrice", "outils", "catalogue", "règle de vie"],
                                 drop_style=["conversation", "émotion", "en face", "mensonge", "état"],
                                 all_sections=True),
}

TOUR2: dict[str, Callable[[Prompt], Job]] = {
    "complet": lambda p: p.build(),
    "nu": lambda p: p.build(system=NU, all_sections=True),
    "nu, 4 derniers messages": lambda p: p.build(system=NU, all_sections=True, keep_history=4),
    "complet, 4 derniers messages": lambda p: p.build(keep_history=4),
    "complet, sans fil": lambda p: p.build(keep_history=0),
    "+ comme un SMS": lambda p: p.build(edits=[(ANSWER, r"$", " Tu écris comme sur ton téléphone : une ou deux "
                                                          "phrases, souvent une seule.")]),
    "+ pas de vérité générale": lambda p: p.build(edits=[(ANSWER, r"$", " Ne fais pas de ce qu'on te dit une "
                                                                    "vérité générale ni une analyse : réagis à la "
                                                                    "personne, pas au sujet.")]),
    "tête sans « attentive »": lambda p: p.build(system_edits=[
        ("tête", r"Une fille attentive, drôle", "Une fille drôle"),
        ("tête", r" — et s'intéresse vraiment aux gens à qui elle parle", ""),
        ("tête", r" et s'intéresse vraiment aux gens à qui elle parle", "")]),
    "effort low": lambda p: p.build(effort="low"),
    "Opus": lambda p: p.build(model="opus"),
}
#: tour 3 : le cumul des gagnants du tour 2, et deux réécritures
GENERAL = (ANSWER, r"$", " Ne fais pas de ce qu'on te dit une vérité générale ni une analyse : réagis à la personne, "
                        "pas au sujet.")
SMS = (ANSWER, r"$", " Tu écris comme sur ton téléphone : une ou deux phrases, souvent une seule.")
HEAD = [("tête", r"Une fille attentive, drôle", "Une fille drôle"),
        ("tête", r" et s'intéresse vraiment aux gens à qui elle parle", "")]
REACT = (ANSWER, r"Réagis d'abord .*?déjà dit\.",
         "Réagis à la personne, pas au sujet : ce que ça te fait, ton avis, une blague, un bout de toi — jamais une "
         "vérité générale, une analyse, ni ses mots redits autrement. Un conseil seulement si on te le demande. Une "
         "question seulement quand tu as vraiment envie de savoir, pas pour relancer : une à la fois, ouverte. Ne "
         "redis pas ce que tu as déjà dit.")
TRAITS = [(ANSWER, r"tu prends le temps : une remarque réfléchie plutôt qu'une réaction à chaud",
           "tu prends le temps de comprendre, et ça s'entend à la justesse de ce que tu dis, pas à sa longueur"),
          (ANSWER, r"tu poses la question qui creuse : tu veux savoir le pourquoi",
           "un détail t'intrigue et tu y reviens ; tu demandes quand ça t'intrigue vraiment, pas pour relancer")]

TOUR3: dict[str, Callable[[Prompt], Job]] = {
    "complet": lambda p: p.build(),
    "A = + pas de vérité générale": lambda p: p.build(edits=[GENERAL]),
    "B = A + tête": lambda p: p.build(edits=[GENERAL], system_edits=HEAD),
    "C = B + SMS": lambda p: p.build(edits=[GENERAL, SMS], system_edits=HEAD),
    "D = réaction réécrite + tête": lambda p: p.build(edits=[REACT], system_edits=HEAD),
    "E = B + traits réécrits": lambda p: p.build(edits=[GENERAL, *TRAITS], system_edits=HEAD),
}
#: tour 4 : le cadrage — un jeu de rôle (« tu es Mika, une fille attentive… ») fait jouer l'amie idéale ; par-dessus
#: v9 (la phrase « vérité générale » et les traits de réfléchie réécrits)
V9 = [GENERAL, *TRAITS]
NOVELIST = ("Tu écris les messages de Mika, comme une romancière qui connaît son personnage par cœur : ce qu'elle "
            "taperait vraiment sur son téléphone à ce moment-là, pas ce qu'une amie idéale devrait répondre. Ce qui "
            "suit la décrit, à la deuxième personne.\n\n")
NOT_A_ROLE = ("Tu ne joues pas un personnage : ce qui suit, c'est toi, ici. Tu écris comme tu écrirais vraiment à "
              "quelqu'un que tu connais, pas comme on imagine qu'une amie devrait le faire.\n\n")
NOT_IDEAL = (ANSWER, r"$", " Tu es une vraie amie, pas une amie modèle : tu n'as pas toujours quelque chose de "
                           "pertinent à dire, et ça te va — parfois une réaction de trois mots suffit.")

TOUR4: dict[str, Callable[[Prompt], Job]] = {
    "v9": lambda p: p.build(edits=V9),
    "v9 + romancière": lambda p: p.build(edits=V9, system_edits=[("tête", r"^", NOVELIST)]),
    "v9 + pas un rôle": lambda p: p.build(edits=V9, system_edits=[("tête", r"^", NOT_A_ROLE)]),
    "v9 + pas une amie modèle": lambda p: p.build(edits=[*V9, NOT_IDEAL]),
}
TOURS = {"1": TOUR1, "2": TOUR2, "3": TOUR3, "4": TOUR4}


def ask(job: Job) -> str:
    with tempfile.TemporaryDirectory(dir=ROOT) as d:
        f = Path(d) / "system.txt"
        f.write_text(job.system)
        cmd = ["claude", "-p", "--model", job.model, *(["--effort", job.effort] if job.effort else []),
               "--output-format", "text",
               "--setting-sources", "", "--strict-mcp-config", "--tools", "", "--no-session-persistence",
               "--system-prompt-file", str(f)]
        out = subprocess.run(cmd, input=job.text, capture_output=True, text=True, timeout=600, check=False).stdout
    return parse(out)[0].strip()


JUDGE = """Tu notes des réponses alternatives de Mika, une IA compagne qui doit parler comme une amie dans un chat, \
jamais comme un assistant ni comme une rédaction. Toutes répondent au même dernier message d'Adrien.

## La conversation jusqu'ici
{context}

## Ce que la propriétaire a trouvé PAS naturel dans de vraies réponses de Mika — et pourquoi
{flagged}

## Ce qui allait mieux, d'après elle
{better}

## Les réponses (dans le désordre)
{replies}

Pour chaque réponse : une note de 0 à 10 (10 : ce qu'aurait écrit une amie humaine ; 5 : un humain tiquerait ;
0 : robotique), ses défauts parmi {defects}, et pourquoi en quelques mots. Réponds uniquement par un objet JSON :
{{"notes": [{{"n": 1, "note": 6, "defauts": ["ton_ecrit"], "pourquoi": "..."}}]}}"""


def judge(context: str, replies: list[str]) -> list[dict]:
    notes: list[dict] = []
    for start in range(0, len(replies), 30):
        chunk = replies[start:start + 30]
        prompt = JUDGE.format(context=context, flagged="\n".join(f"- « {t} » → {w}" for t, w in FLAGGED),
                              better="\n".join(f"- « {t} »" for t in BETTER), defects=", ".join(DEFECTS),
                              replies="\n".join(f"[{i + 1}] {r}" for i, r in enumerate(chunk)))
        got: dict = {}
        for _ in range(3):
            out = cli("opus", "Tu notes des réponses. Réponds uniquement en JSON.", prompt, timeout=900)
            m = re.search(r"\{.*\}", out, re.S)
            try:
                got = json.loads(m.group(0)) if m else {}
            except json.JSONDecodeError:
                got = {}
            if len(got.get("notes", [])) == len(chunk):
                break
        by_n = {int(x["n"]): x for x in got.get("notes", [])}
        notes += [by_n.get(i + 1, {"note": float("nan")}) for i in range(len(chunk))]
    return notes


# ── Tour 5 : une seconde passe qui rend le message naturel ────────────────────────────────────────────────────
#
# Le premier appel fait tout le travail (outils, mémoire, balises) ; un second récrit seulement le texte, au vu du
# fil, sans rien ajouter. Les balises du premier jet restent telles quelles : ce qu'elle ressent ne change pas.

POLISH = """Tu relis le message que Mika s'apprête à envoyer dans une conversation par messages, et tu le rends \
naturel : ce qu'une vraie personne taperait sur son téléphone, à ce moment-là de la conversation, à quelqu'un \
qu'elle connaît.

Tu gardes ce qu'elle ressent, ce qu'elle veut dire et ce qu'elle sait. Tu n'ajoutes rien : aucun fait, aucune idée, \
aucune question.

Tu peux couper ou alléger : une vérité générale ou une analyse tirée de ce que l'autre a dit ; ses mots à lui redits \
autrement ; une question de trop, ou posée pour relancer ; ce qu'elle a déjà dit dans ses messages précédents ; ce \
qui sonne rédigé, poli ou de service. Tu peux raccourcir beaucoup.

Tu gardes sa voix.
{parole}
Son caractère : {traits}

Si le message est déjà naturel, rends-le tel quel. Réponds seulement par le message, sans guillemets ni \
commentaire."""

POLISH_USER = "La conversation jusqu'ici :\n{context}\n\nLe message de Mika à envoyer :\n{draft}"

FIDELITY = """Pour chaque paire, le message récrit garde-t-il le même fond (ce qu'elle dit, sait et veut dire) et le \
même sentiment que le premier jet, sans rien ajouter (fait, idée, question) ? Réponds uniquement par un objet JSON :
{{"paires": [{{"n": 1, "fidele": true, "ajout": false, "pourquoi": "..."}}]}}

{pairs}"""

POLISHERS = {"Sonnet low": ("sonnet", "low"), "Haiku": ("haiku", "")}


def thread_for(prompt: Prompt, n: int = 8) -> str:
    lines = [("Mika : " if m.role == "assistant" else "Adrien : ") + _BRACKETS.sub(" ", m.content).strip()
             for m in prompt.messages[:-1][-n:] if m.content.strip()]
    return "\n".join(lines) + f"\nAdrien : {prompt.heard}"


_BRACKETS = re.compile(r"\s*\[[A-Z_]+[^\]]*\]")


def polish_round(args: argparse.Namespace, prompt: Prompt) -> None:
    source = json.loads((ROOT / args.depuis).read_text())
    drafts = [r["texte"] for r in source["replies"] if r["variante"] == args.base]
    answer = prompt.sections.get(ANSWER, "")
    for _section, pattern, repl in TRAITS:  # les traits tels que v9 les dit
        answer = re.sub(pattern, repl, answer)
    m = re.search(r"il prime sur les exemples de ta voix : (.*?)\.(?: |$)", answer)
    i = prompt.block("parole")
    system = POLISH.format(parole=prompt.paras[i] if i is not None else "", traits=m.group(1) if m else "—")
    context = thread_for(prompt)
    jobs = [(name, d, Job(system, POLISH_USER.format(context=context, draft=d), *POLISHERS[name]))
            for name in POLISHERS for d in drafts]

    def timed(job: Job) -> tuple[str, float]:
        t = time.monotonic()  # noqa: TID251
        return ask(job), time.monotonic() - t  # noqa: TID251

    with concurrent.futures.ThreadPoolExecutor(args.paralleles) as pool:
        done = list(pool.map(lambda j: timed(j[2]), jobs))
    pool_texts = [("premier jet", d, 0.0) for d in drafts] + [(n, t, s) for (n, _d, _j), (t, s) in zip(jobs, done,
                                                                                                    strict=True)]
    order = list(range(len(pool_texts)))
    random.Random(7).shuffle(order)
    judged = judge(context, [pool_texts[i][1] for i in order])
    verdicts: list[dict] = [{}] * len(pool_texts)
    for pos, i in enumerate(order):
        verdicts[i] = judged[pos]
    pairs = [(d, t) for (_n, d, _j), (t, _s) in zip(jobs, done, strict=True)]
    fid = cli("opus", "Tu compares des messages. Réponds uniquement en JSON.", FIDELITY.format(
        pairs="\n\n".join(f"[{k + 1}] Premier jet : « {d} »\n    Récrit : « {t} »" for k, (d, t) in enumerate(pairs))),
        timeout=900)
    got = re.search(r"\{.*\}", fid, re.S)
    fidelity = {int(x["n"]): x for x in (json.loads(got.group(0)).get("paires", []) if got else [])}
    rows = []
    for name in ["premier jet", *POLISHERS]:
        idx = [k for k, p in enumerate(pool_texts) if p[0] == name]
        ns = [float(verdicts[k]["note"]) for k in idx if verdicts[k]["note"] == verdicts[k]["note"]]
        texts = [pool_texts[k][1] for k in idx]
        pair_idx = [k + 1 for k, (n, _d, _j) in enumerate(jobs) if n == name]
        faithful = [fidelity.get(k, {}).get("fidele") for k in pair_idx]
        rows.append({"version": name, "note": round(statistics.fmean(ns), 2) if ns else None,
                     "longueur": round(statistics.fmean(len(t) for t in texts)),
                     "questions_%": round(100 * sum("?" in t for t in texts) / len(texts)),
                     "maximes_%": round(100 * sum(bool(MAXIM.search(t)) for t in texts) / len(texts)),
                     "fidèles": f"{sum(f is True for f in faithful)}/{len(faithful)}" if pair_idx else "—",
                     "secondes": round(statistics.fmean(pool_texts[k][2] for k in idx), 1)})
    out = ROOT / f"ablation5-{args.mesure}-{args.scenario}-{args.appel}.json"
    out.write_text(json.dumps({"rows": rows, "systeme": system, "fidelite": fidelity, "textes": [
        {"version": p[0], "texte": p[1], **v} for p, v in zip(pool_texts, verdicts, strict=True)]},
        ensure_ascii=False, indent=1))
    print(f"Dernier message d'Adrien : « {prompt.heard} »\n")
    print(f"{'version':<14} {'note':>5} {'long':>5} {'?%':>4} {'max%':>5} {'fidèles':>8} {'s':>5}")
    for r in rows:
        print(f"{r['version']:<14} {r['note']!s:>5} {r['longueur']:>5} {r['questions_%']:>4} {r['maximes_%']:>5} "
              f"{r['fidèles']:>8} {r['secondes']:>5}")
    print(f"\n{out}")


#: une vérité générale tirée de ce que dit la personne (« c'est le piège du métier »), repérée grossièrement
MAXIM = re.compile(r"\bc'est (?:ça,? )?(?:le|la|un|une|tout le) (?:piège|côté|truc|problème|sale|charme|plaisir|"
                   r"injustice|souci)|\bça use\b|\brarement\b|\bc'est ça qui\b", re.I)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mesure")
    ap.add_argument("scenario")
    ap.add_argument("appel", type=int)
    ap.add_argument("--tour", default="3", choices=[*sorted(TOURS), "5"])
    ap.add_argument("--tirages", type=int, default=6)
    ap.add_argument("--paralleles", type=int, default=4)
    ap.add_argument("--variantes", default="", help="séparées par des virgules (défaut : toutes celles du tour)")
    ap.add_argument("--depuis", default="", help="tour 5 : la sortie d'un tour d'où prendre les premiers jets")
    ap.add_argument("--base", default="v9", help="tour 5 : la variante de ces premiers jets")
    args = ap.parse_args()
    calls = [json.loads(line) for line in (ROOT / args.mesure / args.scenario / "appels.jsonl").read_text().splitlines()]
    prompt = Prompt(next(c for c in calls if c["n"] == args.appel))
    if args.tour == "5":
        polish_round(args, prompt)
        return
    variants = TOURS[args.tour]
    names = [v for v in args.variantes.split(",") if v] or list(variants)
    jobs = [(name, variants[name](prompt)) for name in names for _ in range(args.tirages)]
    with concurrent.futures.ThreadPoolExecutor(args.paralleles) as pool:
        replies = list(pool.map(lambda j: ask(j[1]), jobs))
    # le contexte que lit le juge : le fil et le dernier message, sans l'état interne
    context = "\n".join(("Mika : " if m.role == "assistant" else "Adrien : ") + m.content
                        for m in prompt.messages[:-1][-10:] if m.content.strip()) + f"\nAdrien : {prompt.heard}"
    order = list(range(len(jobs)))
    random.Random(7).shuffle(order)
    shuffled = judge(context, [replies[i] for i in order])
    verdicts: list[dict] = [{}] * len(jobs)
    for pos, i in enumerate(order):
        verdicts[i] = shuffled[pos]
    rows = []
    for name in names:
        idx = [i for i, j in enumerate(jobs) if j[0] == name]
        rs = [replies[i] for i in idx]
        ns = [float(verdicts[i]["note"]) for i in idx if verdicts[i]["note"] == verdicts[i]["note"]]
        defects: dict[str, int] = {}
        for i in idx:
            for d in verdicts[i].get("defauts") or []:
                defects[d] = defects.get(d, 0) + 1
        job = jobs[idx[0]][1]
        rows.append({"variante": name, "note": round(statistics.fmean(ns), 2) if ns else None,
                     "écart": round(statistics.pstdev(ns), 1) if len(ns) > 1 else None,
                     "longueur": round(statistics.fmean(len(r) for r in rs)),
                     "questions_%": round(100 * sum("?" in r for r in rs) / len(rs)),
                     "maximes_%": round(100 * sum(bool(MAXIM.search(r)) for r in rs) / len(rs)),
                     "défauts": dict(sorted(defects.items(), key=lambda kv: -kv[1])),
                     "système_car": len(job.system), "message_car": len(job.text)})
    out = ROOT / f"ablation{args.tour}-{args.mesure}-{args.scenario}-{args.appel}.json"
    out.write_text(json.dumps({"rows": rows, "replies": [{"variante": j[0], "texte": r, **v}
                                                          for j, r, v in zip(jobs, replies, verdicts, strict=True)]},
                              ensure_ascii=False, indent=1))
    print(f"Dernier message d'Adrien : « {prompt.heard} »\n")
    print(f"{'variante':<30} {'note':>5} {'±':>4} {'long':>5} {'?%':>4} {'max%':>5}  défauts")
    for r in rows:
        top = ", ".join(f"{k} {v}" for k, v in list(r["défauts"].items())[:3])
        print(f"{r['variante']:<30} {r['note']!s:>5} {r['écart']!s:>4} {r['longueur']:>5} {r['questions_%']:>4} "
              f"{r['maximes_%']:>5}  {top}")
    print(f"\n{out}")


if __name__ == "__main__":
    main()
