"""Le mode sec du banc du travail (``--sec``) : sa voix, l'Adrien simulé et le juge remplacés par des doublures.

Il vérifie la mécanique de bout en bout — le noyau, la Forge réelle et son réseau figé, la collecte, le juge, le
rapport — sans aucun modèle ni réseau, en quelques minutes par scénario. Ses notes ne mesurent rien.

- ``DryVoice`` : la doublure du simulateur (``PersonaSimLLM``) qui, en plus, ouvre un projet quand Adrien lui fait
  sa demande, et à chaque exécution y bâtit une app de la Forge sur la première source du scénario (l'écrire,
  l'essayer, rendre sa vue, conclure sur l'essai) ;
- ``adrien`` : ses deux premières réponses probables, puis plus rien (vide) ;
- ``judge`` : une note tirée des compteurs, marquée factice.
"""

from __future__ import annotations

import re
from typing import Any

from mika.kernel.prompt import CONTEXT_FOOTER
from mika.ports.llm import LLMRequest, LLMResponse
from mika.sim.llm.persona import PersonaSimLLM
from scenarios import Scenario

MANIFEST = """\
title: {title}
description: Le relevé de la source du banc (mode sec).
schedule: interval:1h
timeout: 20
views:
  - key: resume
    label: Résumé
"""

CODE = '''\
URL = {url!r}


def tick(api):
    try:
        texte = api.http_get(URL)
    except RuntimeError as e:
        api.log("source indisponible : " + str(e))
        return {{"erreur": str(e)}}
    api.kv_set("dernier", texte[:4000])
    return {{"octets": len(texte)}}


def view_resume(api, params):
    texte = api.kv_get("dernier", "")
    return {{"version": 2, "blocks": [
        {{"type": "stats", "items": [{{"label": "Octets lus", "value": len(texte)}}]}},
        {{"type": "prose", "text": texte[:600] or "rien encore"}},
    ]}}
'''


def _asked(req: LLMRequest) -> str:
    """Le dernier message de la personne (sans le contexte qui le précède)."""
    users = [m.content for m in req.messages if m.role == "user"]
    text = users[-1] if users else ""
    return text.split(CONTEXT_FOOTER, 1)[1].strip() if CONTEXT_FOOTER in text else text


class DryVoice(PersonaSimLLM):
    name = "voix-seche"

    def __init__(self, clock: Any, sc: Scenario) -> None:
        super().__init__(clock, seed=sc.id, latency=0.0, abstain_rate=0.0)
        self.sc = sc
        self.app = "banc_" + re.sub(r"[^a-z0-9]", "_", sc.id)[:24]

    async def complete(self, req: LLMRequest) -> LLMResponse:
        if req.role == "reply" and self.sc.demand[:30] in _asked(req):
            return self._ask(req)
        if req.role in ("project", "job"):
            return self._build_app(req)
        return await super().complete(req)

    def _ask(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        offered = {t.name for t in req.tools}
        if any(m.role == "tool" for m in req.messages) or "start_project" not in offered:
            return self._out(req, "D'accord, je m'en occupe et je te dis quand c'est prêt. [EMOTION:curious:0.5]")
        return self._call(req, ("start_project", {
            "title": f"Banc : {self.sc.id}", "description": f"Ce qu'Adrien m'a demandé : {self.sc.demand}",
            "objectives": ["Une app qui relève la source", "Une vue qui montre ce qu'elle a relevé"],
            "tools": ["forge", "forge_apps"]}))

    def _build_app(self, req: LLMRequest) -> LLMResponse:
        """Une exécution : écrire l'app (une version identique est refusée : elle passe à l'essai), l'essayer, rendre
        sa vue, conclure sur l'essai."""
        self.calls.append(req)
        tools = [m for m in req.messages if m.role == "tool"]
        if any(m.name == "report_run" for m in tools):
            return self._out(req, "Voilà pour cette exécution.")
        if not {"forge_write", "forge_test"} <= {t.name for t in req.tools}:
            return self._call(req, ("report_run", {"verdict": "blocked",
                                                  "summary": "Je n'ai pas la Forge sur ce projet."}))
        if not tools:
            return self._call(req, ("forge_write", {"app": self.app, "manifest": MANIFEST.format(title=self.sc.id),
                                                    "code": CODE.format(url=self.sc.sources[0].sample)}))
        if len(tools) == 1:
            return self._call(req, ("forge_test", {"app": self.app, "method": "tick"}))
        if len(tools) == 2:
            return self._call(req, ("forge_test", {"app": self.app, "method": "view_resume"}))
        ok = "enveloppe valide" in tools[-1].content
        return self._call(req, ("report_run", {
            "verdict": "done" if ok else "continue", "notable": 0.7,
            "summary": "L'app relève la source chaque heure et sa vue la montre." if ok
            else "La vue ne passe pas encore."}))


def adrien(sc: Scenario, said: int) -> str:
    return sc.answers[said].split("« ", 1)[-1].rstrip(" »") if said < min(2, len(sc.answers)) else ""


def judge(counters: dict[str, Any]) -> dict[str, Any]:
    views = counters.get("vues", 0)
    valid = counters.get("vues_valides", 0)
    return {"plan": {"intention": 6 if counters.get("objectifs") else 0, "questions": 3, "criteres": 2,
                     "preuves": ["(factice)"], "pourquoi": "note factice du mode sec"},
            "travail": {"reponse": 8, "fonctionne": round(15 * valid / views) if views else 0, "profondeur": 3,
                        "preuves": ["(factice)"], "pourquoi": "note factice du mode sec"},
            "suivi": {"recits": 5 if counters.get("messages_mika", 0) > 1 else 2, "sollicitations": 4,
                      "preuves": ["(factice)"], "pourquoi": "note factice du mode sec"},
            "deceptions": [], "commentaire": "Mode sec : la mécanique a tourné, aucune qualité n'est mesurée."}
