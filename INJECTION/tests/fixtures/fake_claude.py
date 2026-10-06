#!/usr/bin/env python3
"""Un faux ``claude -p`` pour les tests de bout en bout : il lit la consigne et rend une sortie structurée plausible.

Il parle comme la vraie CLI 2.1.282 en ``stream-json`` (``system/init``, ``assistant``, ``rate_limit_event``,
``result`` avec ``structured_output``). Aucune donnée réelle, aucun appel réseau.
"""

import json
import re
import sys

args = sys.argv[1:]
system = open(args[args.index("--system-prompt-file") + 1], encoding="utf-8").read()
prompt = sys.stdin.read()


def out(obj):
    print(json.dumps(obj, ensure_ascii=False))


def answer():
    if "Tu es la mémoire de" in system:
        keys = [k.strip() for k in prompt.rsplit("(Séances à rendre : ", 1)[1].rstrip(".)\n").split(",")]
        seances = []
        for k in keys:
            block = re.split(r"## (?:Séance|Texte) ", prompt.split(k, 1)[1], maxsplit=1)[0] if k in prompt else ""
            hers = [int(x) for x in re.findall(r"\[m(\d+)\][^\n]*ELLE", block)]
            seances.append({"seance": k, "resume": "J'ai discuté avec une amie le 12 mars 2019.",
                            "humeur_fin": "happy", "signifiance": 0.7, "restes": ["une terrasse au soleil"],
                            "emotions": [{"id": i, "emotion": "happy", "intensite": 0.6} for i in hers],
                            "croyances": [{"texte": "J'adore les terrasses au soleil", "sur_elle": True,
                                           "genre": "gout", "importance": 3}],
                            "souvenirs": [{"texte": "J'ai pris un café en terrasse avec mon amie.",
                                           "messages": hers[:1], "importance": 2}]})
        return {"seances": seances}
    if "un mois à la fois" in system:
        return {"resume": "Un mois doux, entre cours et cafés.", "humeur": "happy",
                "recit": "Je suis quelqu'un qui aime les petits moments partagés."}
    if "grands chapitres" in system:
        months = sorted(set(re.findall(r"^- (\d{4}-\d{2})", prompt, re.M)))
        return {"chapitres": [{"titre": "Les années fac", "debut": months[0], "fin": months[-1],
                               "description": "J'étais étudiante, entourée de mes amis."}]}
    if "Tu fais le portrait" in system:
        return {"description": "Étudiante, chaleureuse.", "tone": "Familière et rieuse.", "traits": ["Chaleureuse"],
                "speech": ["Écrit avec beaucoup de points d'exclamation"], "greetings": ["coucou !"],
                "temperament": {"reactivity": 0.5, "resilience": 0.5, "contagion": 0.5, "optimism": 0.6,
                                "sociability": 0.7, "curiosity": 0.5, "perseverance": 0.5, "background": "happy"}}
    if "se faire une idée d'une personne" in system:
        return {"profils": [{"trimestre": q, "resume": "Une amie proche, on se voit souvent.", "ton": "complice"}
                            for q in re.findall(r"## (\d{4}T\d)", prompt)]}
    if "journal intime" in system:
        return {"jours": [{"jour": d, "texte": "Belle journée, un café en terrasse avec mon amie."}
                          for d in re.findall(r"## (\d{4}-\d{2}-\d{2})", prompt)]}
    if "les rêves de" in system:
        return {"nuits": [{"soir": d, "reves": [{"ton": "doux", "texte": "Je flotte au-dessus d'une terrasse dorée."},
                                                {"ton": "etrange", "texte": "La terrasse s'étire jusqu'à la mer."}]}
                          for d in re.findall(r"## soir du (\d{4}-\d{2}-\d{2})", prompt)]}
    if "dater les archives" in system:
        return {"dates": []}
    return {}


data = answer()
out({"type": "system", "subtype": "init", "mcp_servers": [], "apiKeySource": "none"})
out({"type": "assistant", "message": {"model": "faux-sonnet", "content": [{"type": "text", "text": "ok"}]}})
out({"type": "rate_limit_event", "rate_limit_info": {"unifiedWindows": {"five_hour": {"utilization": 0.1,
                                                                                     "resetsAt": 1900000000}}}})
out({"type": "result", "subtype": "success", "result": json.dumps(data, ensure_ascii=False),
     "structured_output": data, "usage": {"input_tokens": len(prompt) // 4, "output_tokens": 100},
     "total_cost_usd": 0})
