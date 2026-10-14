"""Le corpus du banc de mémoire : ses proches et le monde, en volume (ADR 0110).

Ce que sa mémoire range, écrit comme sa relecture l'écrit, et ce qu'on lui demande, comme on le tape :
- des personnes (Adrien, ses proches, des gens qui parlent à Mika), dont des homonymes de personnalités publiques
  (Emmanuel, Marine, Jordan…), chacune avec ses souvenirs et croyances et des messages qui visent un élément précis ;
- le monde : les nouvelles du jour (``brut/*.xml``) réécrites en croyances « lues », des personnalités publiques, des
  faits généraux — et des questions qui visent un fait.

Génération par la CLI Claude Code (son login, jamais un jeton), par lots, reprise là où elle s'est arrêtée : chaque
lot est gardé dans ``data/banc-memoire/lots/``. Le corpus n'est jamais versionné (des textes de presse).

    .venv/bin/python tools/banc_memoire/generer.py [--modele haiku] [--paralleles 4]
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "data" / "banc-memoire"
LOTS = ROOT / "lots"

#: (prénom, lien, parle à Mika elle-même) — des homonymes de personnalités publiques, exprès
PERSONNES = [
    ("Adrien", "la personne qui s'occupe de Mika, développeur, il vit à Montaigu", True),
    ("Thomas", "le frère d'Adrien, ingénieur, vient d'avoir une petite fille", False),
    ("Emmanuel", "un collègue d'Adrien, chef de projet un peu stressé", False),
    ("Marine", "une amie de lycée d'Adrien, infirmière à Nantes", True),
    ("Jordan", "le cousin d'Adrien, 19 ans, étudiant en STAPS", False),
    ("Gabriel", "le voisin d'Adrien, retraité, passionné de jardinage", False),
    ("Léa", "une amie d'Adrien qui parle aussi à Mika, graphiste", True),
    ("Sam", "un ami d'Adrien qui parle à Mika, musicien, a perdu son père", True),
    ("Alice", "une amie d'Adrien qui parle à Mika, infirmière de nuit", True),
    ("Antoine", "un ami d'enfance d'Adrien, joue au rugby amateur", False),
    ("Victor", "un collègue d'Adrien, grand, fan de basket", False),
    ("Léon", "le neveu d'Adrien, 12 ans, fait de la natation", False),
    ("Raphaël", "un ancien colocataire d'Adrien, vit à Lyon", False),
    ("Lionel", "l'oncle d'Adrien, ancien footballeur amateur", False),
    ("Christine", "la mère d'Adrien, vit à Nantes, institutrice à la retraite", False),
    ("Michel", "le père d'Adrien, bricoleur, problèmes de dos", False),
    ("Camille", "la sœur d'Adrien, étudiante en médecine", True),
    ("Chloé", "l'ex d'Adrien, restés en bons termes", False),
    ("Inès", "une collègue d'Adrien, développeuse front, adore les chats", True),
    ("Karim", "un ami d'Adrien, cuisinier, ouvre son restaurant", True),
    ("Yasmine", "la compagne de Karim, avocate", False),
    ("Hugo", "un ami d'Adrien, joueur de jeux vidéo, streamer amateur", True),
    ("Manon", "une amie de Léa, prof d'anglais", False),
    ("Pauline", "la cheffe d'Adrien, exigeante mais juste", False),
    ("Mehdi", "un ami d'Adrien, coureur de trail", True),
    ("Zoé", "la fille de Thomas, bébé", False),
    ("Nicolas", "un collègue d'Adrien, sysadmin, part bientôt", False),
    ("François", "le grand-père d'Adrien, 88 ans, en maison de retraite", False),
    ("Céline", "une amie de Camille, chanteuse dans une chorale", False),
    ("Charles", "un ami d'Adrien, passionné de formule 1", False),
    ("Arthur", "un ami d'Adrien, joue au tennis en club", False),
    ("Sophie", "une voisine d'Adrien, astronome amatrice", True),
    ("Pierre", "le beau-frère d'Adrien, pilote de ligne", False),
    ("Jean", "le parrain d'Adrien, comédien de théâtre amateur", False),
    ("Simone", "la grand-mère d'Adrien, décédée il y a deux ans", False),
    ("Xavier", "un ami d'Adrien, entrepreneur dans les télécoms", False),
    ("Marion", "une amie d'Adrien, actrice qui galère", True),
    ("Julien", "un collègue d'Adrien, cycliste du dimanche", False),
    ("Max", "le chien de Gabriel, un vieux labrador", False),
    ("Pixel", "le chat d'Adrien, malade en ce moment", False),
]

SUJETS = ["astronomie et espace", "biologie et médecine", "physique et climat", "histoire de France",
          "histoire du monde", "football et rugby", "tennis, cyclisme et formule 1", "jeux olympiques",
          "intelligence artificielle et informatique", "jeux vidéo", "cinéma et séries", "musique",
          "littérature", "géographie et pays", "économie et entreprises", "écologie et énergie",
          "cuisine et gastronomie", "art et architecture", "faits divers et société", "technologie grand public"]

SYSTEME = ("Tu génères des données de test en français pour une mémoire d'IA compagne. Réponds uniquement par un objet "
           "JSON valide, sans texte autour, sans bloc de code.")


def appel(prompt: str, modele: str) -> dict:
    cmd = ["claude", "-p", "--model", modele, "--output-format", "text", "--setting-sources", "",
           "--strict-mcp-config", "--tools", "", "--append-system-prompt", SYSTEME]
    for _ in range(3):
        out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600, check=False).stdout
        m = re.search(r"\{.*\}", out, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
    raise RuntimeError(f"pas de JSON : {out[:200]}")


def lot_personne(prenom: str, lien: str, parle: bool) -> str:
    qui = (f"{prenom} parle lui-même/elle-même à Mika : les messages viennent de {prenom}." if parle else
           f"{prenom} ne parle pas à Mika : les messages viennent d'Adrien, qui parle de {prenom}.")
    return f"""Personne : {prenom} — {lien}.
Écris ce que Mika, une IA compagne, a retenu de {prenom} au fil de conversations, comme sa relecture l'écrit : à la
troisième personne, une phrase chacun, concret, varié (travail, famille, santé, animaux, goûts, projets, soucis,
voyages, anecdotes, dates approximatives). 22 éléments : environ 12 « souvenir » (ce qui s'est passé ou a été dit) et
10 « croyance » (un fait durable). Mets le prénom {prenom} dans la plupart des phrases.
Puis 6 messages courts que l'on pourrait écrire à Mika, familiers (fautes, abréviations, argot), chacun visant UN
élément précis par son index, SANS reprendre ses mots-clés (paraphrase : « mon matou » pour « chat »). {qui}
Format : {{"elements": [{{"type": "souvenir"|"croyance", "texte": "...", "importance": 0.2-0.9}}],
"messages": [{{"texte": "...", "cible": <index dans elements>}}]}}"""


def lot_nouvelles(items: list[dict]) -> str:
    lignes = "\n".join(f"{i}. [{it['source']}] {it['titre']} — {it['resume'][:300]}" for i, it in enumerate(items))
    return f"""Voici des nouvelles lues par Mika ce matin.
{lignes}
Pour chacune, écris 1 à 3 croyances factuelles telles que Mika les retiendrait (« D'après Le Monde, … »), une
phrase chacune, et pour environ une nouvelle sur quatre une question familière qu'Adrien pourrait poser à Mika et
dont la réponse est une de ces croyances (sans reprendre ses mots-clés).
Format : {{"faits": [{{"texte": "...", "source": "..."}}], "questions": [{{"texte": "...", "cible": <index dans faits>}}]}}"""


def lot_figures(noms: list[str], resumes: dict) -> str:
    blocs = "\n".join(f"- {n} : {resumes.get(n, {}).get('extrait', '')[:400]}" for n in noms)
    return f"""Personnalités publiques :
{blocs}
Pour chacune, écris 15 faits variés (biographie, carrière, déclarations, polémiques, vie publique) tels que Mika les
aurait lus dans la presse, une phrase chacun, avec le nom en clair. Puis, pour chacune, une question familière
qu'Adrien pourrait poser à Mika et dont la réponse est un de ces faits (sans reprendre ses mots-clés).
Format : {{"faits": [{{"texte": "...", "figure": "..."}}], "questions": [{{"texte": "...", "cible": <index dans faits>}}]}}"""


def lot_sujet(sujet: str) -> str:
    return f"""Sujet : {sujet}.
Écris 100 faits variés et précis sur ce sujet, tels que Mika les aurait lus (presse, vulgarisation), une phrase
chacun, avec des noms propres, des dates, des chiffres. Puis 6 questions familières qu'Adrien pourrait poser à Mika,
chacune visant un fait précis par son index, sans reprendre ses mots-clés.
Format : {{"faits": [{{"texte": "..."}}], "questions": [{{"texte": "...", "cible": <index dans faits>}}]}}"""


def lot_paires(textes: list[str]) -> str:
    lignes = "\n".join(f"{i}. {t}" for i, t in enumerate(textes))
    return f"""Voici des éléments que la mémoire de Mika, une IA compagne, a retenus.
{lignes}
Pour chacun, écris :
- « meme » : le même fait tel qu'une autre relecture de la même conversation l'aurait noté (autres mots, autre
  tournure, parfois un détail en plus ou en moins), à fusionner avec l'original ;
- « voisin » : un fait différent sur la même personne, du même domaine et de la même forme (autre date, autre
  événement, autre détail qui change le sens), à ne surtout pas fusionner.
Format : {{"paires": [{{"index": <index>, "meme": "...", "voisin": "..."}}]}}"""


def nouvelles() -> list[dict]:
    out = []
    for f in sorted((ROOT / "brut").glob("*.xml")):
        raw = f.read_text(errors="ignore")
        for item in re.findall(r"<item\b.*?</item>", raw, re.S):
            def champ(tag: str) -> str:
                m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", item, re.S)
                return re.sub(r"<[^>]+>", " ", html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1)))).strip() \
                    if m else ""
            titre, resume = champ("title"), champ("description")
            if titre:
                out.append({"source": f.stem.split("-")[0], "titre": titre, "resume": resume})
    return out


def taches() -> dict[str, str]:
    t: dict[str, str] = {}
    for i, (prenom, lien, parle) in enumerate(PERSONNES):
        t[f"personne-{i:02d}"] = lot_personne(prenom, lien, parle)
    news = nouvelles()
    for i in range(0, len(news), 25):
        t[f"nouvelles-{i // 25:02d}"] = lot_nouvelles(news[i:i + 25])
    wiki = json.loads((ROOT / "brut" / "wikipedia.json").read_text())
    noms = list(wiki)
    for i in range(0, len(noms), 8):
        t[f"figures-{i // 8:02d}"] = lot_figures(noms[i:i + 8], wiki)
    for i, sujet in enumerate(SUJETS):
        t[f"sujet-{i:02d}"] = lot_sujet(sujet)
    # des paires pour les seuils de doublon et de fusion : un élément sur trois de ses proches, par 25
    proches = [el["texte"] for f in sorted(LOTS.glob("personne-*.json"))
               for el in json.loads(f.read_text()).get("elements", [])][::3]
    for i in range(0, len(proches), 25):
        t[f"paires-{i // 25:02d}"] = lot_paires(proches[i:i + 25])
    return t


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modele", default="haiku")
    ap.add_argument("--paralleles", type=int, default=4)
    ap.add_argument("--seulement", default="", help="les lots dont le nom commence ainsi")
    args = ap.parse_args()
    LOTS.mkdir(parents=True, exist_ok=True)
    todo = {k: v for k, v in taches().items()
            if k.startswith(args.seulement) and not (LOTS / f"{k}.json").exists()}
    print(f"{len(todo)} lots à générer", flush=True)

    def faire(item: tuple[str, str]) -> str:
        key, prompt = item
        try:
            data = appel(prompt, args.modele)
        except Exception as exc:  # noqa: BLE001 — un lot raté se relance au prochain passage
            return f"{key} : échec ({str(exc)[:80]})"
        (LOTS / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
        n = len(data.get("elements") or data.get("faits") or data.get("paires") or [])
        return f"{key} : {n} éléments, {len(data.get('messages') or data.get('questions') or [])} messages"

    with concurrent.futures.ThreadPoolExecutor(args.paralleles) as pool:
        for line in pool.map(faire, todo.items()):
            print(line, flush=True)


if __name__ == "__main__":
    sys.exit(main())
