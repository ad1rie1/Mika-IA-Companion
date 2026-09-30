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
from pathlib import Path
from urllib.parse import quote

from starlette.testclient import TestClient

from mika.adapters.llm.config import LiveGateway
from mika.adapters.llm.gateway import Gateway
from mika.adapters.system import RealClock
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app.console import NAVIGATION
from mika.app.server import build
from mika.ports.llm import LLMRequest, LLMResponse
from mika.sim.llm.scripted import ScriptedLLM
from mika.vocab.episodes import VOICE_ROLES

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
    ("bea", ["coucou Mika, c'est Béa", "je suis un peu fatiguée aujourd'hui", "à demain !"]),
)


def _respond(req: LLMRequest) -> LLMResponse:
    if req.role != "reply":
        return LLMResponse("[SILENCE]")
    text, emotion, intensity = next(REPLIES)
    return LLMResponse(f"{text} [EMOTION:{emotion}:{intensity}]")


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
    roles = {str(r): "apercu" for r in VOICE_ROLES}
    gateway = LiveGateway(Gateway({"apercu": ScriptedLLM(clock, _respond)}, roles, clock=clock,
                                  voice_roles=frozenset(roles), slots={"apercu": 1}))
    done: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        app, live = build(Path(tmp) / "data", web=WebConfig(), gateway=gateway, embedder=HashEmbedder())
        with TestClient(app, base_url=HOST, headers={"Origin": ORIGIN}) as client:
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
            for kind in ("person", "handle"):  # la première personne connectée, et sa poignée
                urls += [f"/inspecteur/fiche/{kind}/user_1?onglet={quote(v.name)}"
                         for v in live.kernel.registry.inspectors if v.subject == kind]
            ended = client.portal.call(lambda: live.kernel.mind.store.latest(["episode.ended"], 1))
            if ended:
                corr = quote(ended[0].correlation, safe="")
                urls += [f"/inspecteur/episode/{corr}?onglet={t}" for t in
                         ("deroule", "dit", "prompt", "outils", "appels", "decision")]
            urls += ["/inspecteur/reglages/fournisseurs?enregistrement=backends&cle=",
                     "/inspecteur/reglages/comportement-affect?groupe=repos-et-ancre",
                     "/inspecteur/reglages/comptes?nouveau=1", "/inspecteur/recherche?q=a"]
            for url in dict.fromkeys(u for u in urls if u):
                r = client.get(url, follow_redirects=True)
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
    return done
