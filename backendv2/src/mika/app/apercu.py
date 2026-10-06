"""``mika console apercu --out DOSSIER`` : la console, page par page, sans serveur.

Une Mika neuve (dossier temporaire, modèle factice local : rien ne sort de la
machine) converse avec deux personnes ; puis chaque destination, chaque
onglet, chaque réglage et quelques fiches sont exportés en HTML statique, en
clair et en sombre, avec la feuille de style — de quoi relire la console
dans un navigateur, ou en faire des captures (``google-chrome --headless``).
Le script de la console est retiré des copies : le thème exporté est celui
qu'on a choisi.
"""

from __future__ import annotations

import itertools
import logging
import re
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from starlette.testclient import TestClient

from mika.adapters.llm.config import BackendSpec, LiveGateway, LLMConfig
from mika.adapters.llm.gateway import Gateway, LLMTrace
from mika.adapters.system import RealClock
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app.console import NAVIGATION
from mika.app.server import build
from mika.ports.llm import LLMRequest, LLMResponse, Usage
from mika.runtime.operations import perform
from mika.sim.llm.persona import PersonaSimLLM
from mika.vocab.episodes import FALLBACKS, VOICE_ROLES

#: le fournisseur de l'aperçu (la doublure du simulateur, locale : rien ne sort de la machine)
NAME = "apercu"
#: la relecture de ses conversations, attendue au plus tant de fois 0,1 s
CONSOLIDATION_WAIT_STEPS = 100
ORIGIN = "http://localhost:3000"
HOST = "http://localhost:8001"
PASSWORD = "une-phrase-de-passe-longue"
STATIC = Path(__file__).resolve().parent.parent / "inspector" / "static"
REPLIES = itertools.cycle([
    ("Oh, ça me fait plaisir de te lire ! Raconte-moi tout.", "happy", 0.6),
    ("Hmm, attends… c'est une vraie question, ça.", "thinking", 0.5),
    ("Ha ! Je ne m'y attendais pas du tout.", "surprised", 0.55),
    ("Je comprends. Ça doit être lourd, en ce moment.", "sad", 0.4),
])
CONVERSATIONS = (
    ("adrien", ["salut ! moi c'est Adrien", "je bosse sur un jeu en ce moment", "tu aimes le café ?"]),
    ("bea", ["coucou, c'est Béa", "je suis un peu fatiguée aujourd'hui", "à demain !"]),
)


async def _project(kernel) -> str:
    """Un projet fictif, créé comme un opérateur le ferait : des objectifs ponctuels et un constant."""
    got = await perform(kernel, "projects.creer", {
        "_champs": ["title", "description", "objectives", "constants", "mode", "schedule", "days", "start", "end",
                    "cadence_hours", "runs_per_day", "priority", "branch", "tool_memory"],
        "title": ["Outils réseau"], "description": ["Un petit outillage d'administration, propre et testé."],
        "objectives": ["Créer un module RDP\nÉcrire sa documentation"], "constants": ["Améliorer la sécurité"],
        "mode": ["persona"], "schedule": ["manual"], "days": ["weekdays"], "start": ["9:00"], "end": ["18:00"],
        "cadence_hours": ["24"], "runs_per_day": ["0"], "priority": ["normal"], "branch": ["main"],
        "tool_memory": ["on"]}, by="user_1", nonce="apercu-projet")
    return got.go.key.split("/", 1)[1] if got.ok and got.go is not None else ""


class _Model(PersonaSimLLM):
    """La doublure du simulateur, qui tient tous les rôles (retenir, son journal, comprendre les gens…) : une
    vie complète, que la mémoire, la consolidation et les coûts montrent. Ses réponses, elles, varient d'un
    message à l'autre sans jamais se taire (l'aperçu veut une parole à chaque message)."""

    async def complete(self, req: LLMRequest) -> LLMResponse:
        if req.role != "reply":
            return await super().complete(req)
        self.calls.append(req)
        text, emotion, intensity = next(REPLIES)
        return LLMResponse(f"{text} [EMOTION:{emotion}:{intensity}]", model=self.model,
                           usage=Usage(input_tokens=sum(len(m.content) for m in req.messages) // 4, output_tokens=20))


def _page(text: str, theme: str, depth: int) -> str:
    prefix = "../" * depth
    text = text.replace("/inspecteur/static/", f"{prefix}static/")
    text = re.sub(r"<script[^>]*console\.js[^>]*></script>", "", text)
    return text.replace('<html lang="fr">', f'<html lang="fr" data-theme="{theme}">', 1)


def _name(url: str) -> str:
    slug = url.removeprefix("/inspecteur").strip("/") or "accueil"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", slug)[:120] + ".html"


def export(out: Path) -> list[str]:
    """Rend les pages dans ``out`` ; rend la liste des adresses exportées."""
    logging.getLogger("mika").setLevel(logging.ERROR)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(STATIC, out / "static", dirs_exist_ok=True)
    clock = RealClock()
    sink: list[Callable[[LLMTrace], None]] = []
    # un seul fournisseur, déclaré comme un opérateur le ferait : il sert « répondre », les autres rôles y
    # retombent (replis de rôle) ; chaque appel laisse sa trace (Coûts, Pourquoi a-t-elle dit ça ?)
    gateway = LiveGateway(Gateway({NAME: _Model(clock, latency=0.0, abstain_rate=0.0)}, {"reply": NAME},
                                  clock=clock, voice_roles=frozenset(str(r) for r in VOICE_ROLES),
                                  fallbacks={str(k): str(v) for k, v in FALLBACKS.items()}, slots={NAME: 1},
                                  on_trace=lambda tr: [f(tr) for f in sink]))
    done: list[str] = []
    failed: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        # l'horloge est réelle : la nuit, ses réponses attendraient son réveil (ADR 0036) — un aperçu
        # répond à toute heure
        app, live = build(Path(tmp) / "data", web=WebConfig(), gateway=gateway, embedder=HashEmbedder(),
                          reply_wait=None)
        sink.append(live.trace)
        with TestClient(app, base_url=HOST, headers={"Origin": ORIGIN}) as client:
            client.portal.call(lambda: live.settings.save_llm(LLMConfig(backends={NAME: BackendSpec(
                kind="ollama", model="doublure-du-simulateur")})))
            def token() -> dict[str, str]:
                client.get("/auth/whoami")
                return {"X-CSRFToken": client.cookies.get("csrftoken", "")}

            operator = {"username": "adrien", "password": PASSWORD}
            client.post("/auth/bootstrap", json=operator, headers=token())
            for who, messages in CONVERSATIONS:
                if who != "adrien":  # une autre personne : son propre compte, sa propre session
                    client.portal.call(lambda w=who: live.accounts.create(w, PASSWORD, operator=False,
                                                                          full_name=w.capitalize()))
                    client.post("/auth/login", json={"username": who, "password": PASSWORD}, headers=token())
                with client.websocket_connect(HOST.replace("http", "ws") + "/ws") as ws:
                    ws.receive_json(), ws.receive_json()
                    for i, message in enumerate(messages):
                        ws.send_json({"type": "chat", "message": message, "client_msg_id": f"{who}-{i}"})
                        for _ in range(30):
                            if ws.receive_json().get("type") == "speech":
                                break
            # six messages reçus : elle relit la conversation (souvenirs, croyances) — attendre qu'elle l'ait fait,
            # pour que Mémoire et Consolidation montrent une vie, pas des pages vides
            for _ in range(CONSOLIDATION_WAIT_STEPS):
                if client.portal.call(lambda: live.kernel.mind.store.latest(["memory.consolidated"], 1)):
                    break
                time.sleep(0.1)
            client.post("/auth/login", json=operator, headers=token())
            urls: list[str] = []
            for group in NAVIGATION:
                for d in group.items:
                    base = "/inspecteur/" if d.key == "accueil" else f"/inspecteur/{d.key}"
                    urls.append(base)
                    if d.layout == "tabs":
                        urls += [f"{base}/{k.split('.', 1)[1]}" for k in d.builtin]
                        urls += [f"{base}/{v.name}" for v in live.kernel.registry.inspectors if v.section == d.key]
                    elif d.layout == "menu":  # un sous-menu : chacune de ses pages
                        page = client.get(base, follow_redirects=True).text
                        urls += re.findall(rf'class="submenu-item[^"]*" href="({re.escape(base)}/[\w-]+)"', page)
            for kind in ("person", "handle"):  # la première personne connectée, et son adresse
                urls += [f"/inspecteur/fiche/{kind}/user_1?onglet={quote(v.name)}"
                         for v in live.kernel.registry.inspectors if v.subject == kind]
            project = client.portal.call(lambda: _project(live.kernel))  # un projet, et chaque onglet de sa fiche
            if project:
                urls += [f"/inspecteur/fiche/project/{project}?onglet={quote(v.name)}"
                         for v in live.kernel.registry.inspectors if v.subject == "project"]
            ended = client.portal.call(lambda: live.kernel.mind.store.latest(["episode.ended"], 1))
            if ended:
                corr = quote(ended[0].correlation, safe="")
                urls += [f"/inspecteur/episode/{corr}?onglet={t}" for t in
                         ("deroule", "dit", "prompt", "outils", "appels", "decision")]
            said = client.portal.call(lambda: live.kernel.mind.store.latest(["episode.utterance"], 1))
            if said:  # « Pourquoi a-t-elle dit ça ? » sur sa dernière parole
                urls.append(f"/inspecteur/parole/{said[0].seq}")
            urls.append("/inspecteur/decisions/envers?personne=adrien")
            urls += ["/inspecteur/reglages/fournisseurs?enregistrement=backends&cle=",
                     "/inspecteur/reglages/comportement-affect?groupe=repos-et-ancre",
                     "/inspecteur/reglages/comptes?nouveau=1", "/inspecteur/recherche?q=a",
                     "/inspecteur/action/projects.creer?retour=/inspecteur/projets"]
            for url in dict.fromkeys(u for u in urls if u):
                r = client.get(url, follow_redirects=True)
                if r.status_code != 200:  # une page en erreur ne s'exporte pas comme si de rien n'était
                    failed.append(f"{url} ({r.status_code})")
                    continue
                name = _name(url)
                for theme in ("clair", "sombre"):
                    target = out / theme / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(_page(r.text, "light" if theme == "clair" else "dark", 1), encoding="utf-8")
                done.append(url)
    index = "\n".join(f'<li><a href="clair/{_name(u)}">{u}</a> · <a href="sombre/{_name(u)}">sombre</a></li>'
                      for u in done)
    (out / "index.html").write_text(f"<!doctype html><meta charset=utf-8><title>Aperçu de la console</title>"
                                    f"<h1>Aperçu de la console</h1><ul>{index}</ul>", encoding="utf-8")
    if failed:
        raise ExportFailed(failed)
    return done


class ExportFailed(RuntimeError):
    """Des pages de la console ont répondu autre chose que 200 : les autres sont exportées, celles-ci nommées."""

    def __init__(self, pages: list[str]) -> None:
        self.pages = pages
        super().__init__(f"{len(pages)} page(s) en erreur : " + ", ".join(pages[:10]))
