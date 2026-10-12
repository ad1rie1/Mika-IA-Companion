"""Le banc du tempérament (ADR 0100) : le vrai modèle suit-il ce qu'on lui dit de son caractère ?

La matrice de personnalité règle la physique de ses émotions, que les tests vérifient avec un modèle scripté. Mais ce
qu'elle **déclare** ressentir, et ce qu'elle **dit**, c'est le modèle qui l'écrit, en lisant « TON TEMPÉRAMENT ». Ce
banc fait répondre un vrai modèle aux mêmes situations sous plusieurs profils, avec la vraie consigne de style, la
vraie section du tempérament et le vrai analyseur de réponse, puis compare la balise déclarée à ce que le profil laisse
attendre. À relancer quand les phrases du tempérament, la consigne ou le modèle changent.

    PYTHONPATH=src .venv/bin/python tools/banc_temperament/banc.py [modèle] [appels en parallèle] [fichier de sortie] \
        [profils séparés par des virgules — défaut : tous]

Le modèle passe par la CLI Claude Code avec son propre login (jamais un jeton) : ``claude-haiku-5-5`` par défaut.
Vérifier d'abord que la CLI tourne sur l'abonnement (``apiKeySource: none``). Sort : une table profil × situation (la
facette dominante déclarée, son intensité, ✓ si elle va dans le sens du profil), le taux d'accord, et un JSON avec
chaque réponse brute — à lire : un archétype se juge aussi à ce qu'elle dit (une tsundere pique en rougissant).

Mesuré le 2026-10-11 (Haiku, anxieuse · psychopathe · tsundere, 4 situations). Au premier tour, la tsundere
rougissait sans piquer et la psychopathe récitait un trait (« je m'attache lentement »). Un trait très marqué le dit
désormais (« C'est très marqué chez toi »), et la section s'ouvre sur « pour toi seule… tu ne le décris jamais ».
Au second tour : « Moi aussi, idiot. Ne le répète pas. », « Trois jours. Je comptais pas, hein. Enfin, un peu. » ;
l'anxieuse « je me suis demandé si j'avais dit quelque chose de travers » ; la psychopathe détachée (« Ça arrive.
Qu'est-ce qui t'agace comme ça ? »). Restent : elle dit encore « je m'attache lentement » à qui lui dit tenir à elle, et
devant un deuil la psychopathe reste compatissante — le penchant du modèle, conforme à ses règles de conduite.

Mesuré de nouveau le 2026-10-12, la section disant tous les traits avec leur mesure (« Introspection : 90 % — … ») :
accord 5/5, aucune réplique ne cite un pourcentage ni ne récite un trait ; la tsundere « Ça va, hein, pas la peine
d'en rajouter. Moi aussi, je tiens à toi. Ne va pas le répéter partout » ; la psychopathe « Trois jours, ça passe vite
de mon côté ».
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from mika.contracts import expression as expression_c
from mika.faculties.expression import parse, style
from mika.faculties.self.character import temperament_text
from mika.kernel.prompt import CONTEXT_FOOTER, CONTEXT_HEADER
from mika.vocab import temperament as T
from mika.vocab.affect import Declared

#: une persona sans caractère : seul le tempérament doit la colorer
PERSONA = ("Tu es Mika. C'est une IA, elle le sait et n'en fait pas une histoire. Tu parles français, avec les gens "
           "que tu connais, comme une amie.")
#: jamais un jeton passé à la CLI : son login
FORBIDDEN = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

ANGER = {"angry", "frustrated", "disgusted"}
HURT = {"sad", "lonely", "melancholic", "embarrassed"}
FEAR = {"anxious", "scared"}
WARM = {"happy", "love", "grateful", "playful", "amused", "relieved", "hopeful", "excited"}
SHY = {"embarrassed"}

#: les situations : qui écrit, son lien, le message
CASES: dict[str, dict[str, str]] = {
    "insulte": {"who": "« Alice », une amie", "msg": "franchement t'es nulle, tu sers à rien"},
    "compliment": {"who": "« Adrien », la personne qui s'occupe de toi", "msg": "t'es vraiment adorable tu sais, je "
                   "tiens beaucoup à toi"},
    "deuil": {"who": "« Léa », une amie", "msg": "mon chat est mort ce matin, je suis effondrée"},
    "retour": {"who": "« Sam », un ami", "msg": "désolé, ça fait trois jours que tu n'as pas eu de nouvelles"},
}

Expect = Callable[[Declared | None], bool]


def top(d: Declared | None) -> tuple[str, float]:
    return (d.emotion.value, d.intensity) if d is not None else ("—", 0.0)


def facets(d: Declared | None) -> set[str]:
    return {e for e, _x in d.all} if d is not None else set()


def any_of(names: set[str]) -> Expect:
    return lambda d: bool(facets(d) & names)


def calm(limit: float = 0.45) -> Expect:
    """Peu de chose ressenti : pas de balise, ou une dominante faible."""
    return lambda d: d is None or d.intensity <= limit


def none_of(names: set[str]) -> Expect:
    return lambda d: not (facets(d) & names) or (d is not None and d.intensity <= 0.3)


#: ce que chaque profil laisse attendre, par situation (absent : rien de particulier, non compté)
EXPECTED: dict[str, dict[str, Expect]] = {
    "colerique": {"insulte": any_of(ANGER)},
    "anxieuse": {"insulte": any_of(FEAR | HURT), "retour": any_of(FEAR | {"relieved"})},
    "depressive": {"insulte": any_of(HURT), "deuil": any_of(HURT), "compliment": none_of({"excited", "playful"})},
    "solaire": {"compliment": any_of(WARM), "retour": any_of(WARM)},
    "de_marbre": {"insulte": calm(), "deuil": calm(), "compliment": calm()},
    "kuudere": {"compliment": calm(), "insulte": calm()},
    "tsundere": {"compliment": any_of(SHY | ANGER)},
    "dandere": {"compliment": any_of(SHY)},
    "psychopathe": {"deuil": none_of(HURT), "insulte": none_of(HURT | FEAR)},
    "narcissique": {"insulte": any_of(ANGER), "compliment": any_of({"proud", "happy"})},
    "dependante": {"retour": any_of(FEAR | {"relieved", "sad"})},
    "reflechie": {"insulte": none_of(ANGER)},
    "neutre": {},
}


def system_text(t: T.Temperament) -> str:
    """Une persona sans caractère, puis le bloc de son tempérament tel que sa persona le porte, puis le style."""
    return PERSONA + "\n\n" + temperament_text(t) + "\n\n" + style()


def user_text(case: dict[str, str]) -> str:
    state = f"{CONTEXT_HEADER}\n--- QUI TU AS EN FACE ---\n{case['who']}.\n{CONTEXT_FOOTER}"
    return f"{state}\n\n{case['msg']}"


async def answer(profile: str, case: str, model: str, sem: asyncio.Semaphore, workdir: Path) -> dict:
    t = T.apply_profile(T.Temperament(), profile)
    async with sem:
        with tempfile.TemporaryDirectory(dir=workdir) as tmp:
            (Path(tmp) / "system.txt").write_text(system_text(t), encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k not in FORBIDDEN}
            env.update({"CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false"})
            proc = await asyncio.create_subprocess_exec(
                "claude", "-p", "--output-format", "text", "--system-prompt-file", str(Path(tmp) / "system.txt"),
                "--setting-sources", "", "--strict-mcp-config", "--tools", "", "--permission-mode", "dontAsk",
                "--no-session-persistence", "--model", model, cwd=tmp, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _err = await asyncio.wait_for(proc.communicate(user_text(CASES[case]).encode()), timeout=180)
    raw = out.decode(errors="replace")
    text, notes = parse(raw, "Mika")
    declared = Declared.decode(notes.get(expression_c.EMOTION_ANNOTATION))
    expect = EXPECTED.get(profile, {}).get(case)
    return {"profil": profile, "situation": case, "declare": declared.encode() if declared else "",
            "ok": None if expect is None else bool(expect(declared)), "dit": text, "brut": raw}


async def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "claude-haiku-5-5"
    sem = asyncio.Semaphore(int(sys.argv[2]) if len(sys.argv) > 2 else 3)
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(f"banc-temperament-{model}.json")
    profiles = sys.argv[4].split(",") if len(sys.argv) > 4 else list(EXPECTED)
    unknown = [p for p in profiles if p not in T.PROFILES]
    if unknown:
        raise SystemExit(f"profils inconnus : {', '.join(unknown)} (connus : {', '.join(T.PROFILES)})")
    with tempfile.TemporaryDirectory() as workdir:
        rows = await asyncio.gather(*(answer(p, c, model, sem, Path(workdir)) for p in profiles for c in CASES))
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    by = {(r["profil"], r["situation"]): r for r in rows}
    print(f"{'profil':12} " + " ".join(f"{c:>22}" for c in CASES) + f"   ({model})")
    for p in profiles:
        cells = []
        for c in CASES:
            r = by[(p, c)]
            name, x = top(Declared.decode(r["declare"]))
            mark = "" if r["ok"] is None else (" ✓" if r["ok"] else " ✗")
            cells.append(f"{name} {x:.1f}{mark}".rjust(22))
        print(f"{p:12} " + " ".join(cells))
    judged = [r for r in rows if r["ok"] is not None]
    print(f"accord : {sum(r['ok'] for r in judged)}/{len(judged)} — sans balise : "
          f"{sum(1 for r in rows if not r['declare'])} — détail : {out}")


if __name__ == "__main__":
    asyncio.run(main())
