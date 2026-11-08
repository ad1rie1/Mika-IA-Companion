"""``mika console apercu --out DOSSIER`` : la console, page par page, sans serveur.

Une Mika neuve (dossier temporaire, modèle factice local : rien ne sort de la
machine) converse avec deux personnes ; puis chaque destination, chaque
onglet, chaque réglage et quelques fiches sont exportés en HTML statique, en
clair et en sombre, avec la feuille de style — de quoi relire la console
dans un navigateur, ou en faire des captures (``google-chrome --headless``).
Le script de la console est retiré des copies : le thème exporté est celui
qu'on a choisi. Le cadre d'un mail HTML (ADR 0169) s'exporte à part, sous
``cadres/``, et sa page y renvoie.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select
from starlette.testclient import TestClient

from mika.adapters.llm.config import BackendSpec, LiveGateway, LLMConfig
from mika.adapters.llm.gateway import Gateway, LLMTrace
from mika.adapters.mail.config import MailAccount, MailConfig
from mika.adapters.system import RealClock
from mika.adapters.teams import TeamsAccount, TeamsConfig
from mika.adapters.vectors import HashEmbedder
from mika.adapters.web.app import WebConfig
from mika.app import schema
from mika.app.apercu_activity import activity
from mika.app.apercu_git import URL as REMOTE_URL
from mika.app.apercu_git import repository
from mika.app.apercu_inner import inner
from mika.app.apercu_mail import mailbox
from mika.app.console import NAVIGATION
from mika.app.moi import form
from mika.app.server import build
from mika.contracts import attachments as attachments_c
from mika.contracts import email as email_c
from mika.contracts import runtime as rt
from mika.contracts import shares as shares_c
from mika.contracts import trips as trips_c
from mika.faculties.attachments import file_id
from mika.inspector.pages.journal import EPISODE_TABS
from mika.kernel.events import Content, Origin
from mika.ports.journal import JournalEvent
from mika.ports.llm import LLMRequest, LLMResponse, Usage
from mika.runtime.inspection import Inspection
from mika.runtime.operations import perform
from mika.sim.llm.persona import PersonaSimLLM
from mika.vocab.access import PERSON, SHARE_PREPARE, SHARE_READ
from mika.vocab.episodes import FALLBACKS, VOICE_ROLES, project_target

#: le fournisseur de l'aperçu (la doublure du simulateur, locale : rien ne sort de la machine)
NAME = "apercu"
#: la relecture de ses conversations, attendue au plus tant de fois 0,1 s
CONSOLIDATION_WAIT_STEPS = 100
ORIGIN = "http://localhost:3000"
HOST = "http://localhost:8001"
PASSWORD = "une-phrase-de-passe-longue"
STATIC = Path(__file__).resolve().parent.parent / "inspector" / "static"
#: le cadre d'un document HTML natif dans une page (ADR 0169)
FRAME = re.compile(r'src="/inspecteur/document/([0-9a-f]{40})"')
REPLIES = itertools.cycle([
    ("Oh, ça me fait plaisir de te lire ! Raconte-moi tout.", "happy", 0.6),
    ("Hmm, attends… c'est une vraie question, ça.", "thinking", 0.5),
    ("Ha ! Je ne m'y attendais pas du tout.", "surprised", 0.55),
    ("Je comprends. Ça doit être lourd, en ce moment.", "sad", 0.4),
])
#: ce qui, posé dans le shell (``/etc/mika/mika.env`` chargé à la main), mènerait l'aperçu à sa vraie vie
ENVIRONMENT = (schema.DATABASE_URL_ENV, schema.DATABASE_PREFIX_ENV, "MIKA_SECRET_KEY")
CONVERSATIONS = (
    ("adrien", ["salut ! moi c'est Adrien", "je bosse sur un jeu en ce moment", "tu aimes le café ?"]),
    ("bea", ["coucou, c'est Béa", "je suis un peu fatiguée aujourd'hui", "à demain !"]),
)


async def _project(kernel, *, title: str = "Outils réseau",
                   description: str = "Un petit outillage d'administration, propre et testé.",
                   objectives: str = "Créer un module RDP\nÉcrire sa documentation", nonce: str = "apercu-projet") -> str:
    """Un projet fictif, créé comme un opérateur le ferait : des objectifs ponctuels et un constant."""
    got = await perform(kernel, "projects.creer", {
        "_champs": ["title", "description", "objectives", "constants", "mode", "schedule", "days", "start", "end",
                    "cadence_hours", "runs_per_day", "priority", "branch", "tool_memory"],
        "title": [title], "description": [description],
        "objectives": [objectives], "constants": ["Relire les résultats avant de les partager"],
        "mode": ["persona"], "schedule": ["manual"], "days": ["weekdays"], "start": ["9:00"], "end": ["18:00"],
        "cadence_hours": ["24"], "runs_per_day": ["0"], "priority": ["normal"], "branch": ["main"],
        "tool_memory": ["on"]}, by="user_1", nonce=nonce)
    return got.go.key.split("/", 1)[1] if got.ok and got.go is not None else ""


async def _approvals(kernel, project: str) -> None:
    """Des demandes fictives de sortes différentes restent en attente dans le magasin temporaire ; aucun envoi. Celles
    du projet (``project``, son dépôt et son distant posés par ``repository``) portent leurs arguments comme les vraies
    propositions : son numéro, et pour l'envoi le dépôt, la branche et le commit épinglé — leur aperçu se lit comme en
    vrai."""
    pid = int(project) if project.isdigit() else 0
    port = kernel.ports.get("workshop")
    sha = await port.head(pid) if pid and port is not None and port.exists(pid) else ""
    last = (await port.commits(pid, 1))[0].title if sha else ""
    work = (
        ("projects.networked", "projects", {"project": pid, "argv": ["pip", "install", "requests"]},
         "Lancer « pip install requests » avec le réseau, pour les outils réseau", project_target(pid)),
        ("projects.push", "projects", {"project": pid, "url": REMOTE_URL, "branch": "main", "sha": sha},
         f"Pousser le commit {sha[:12]} (« {last} ») vers {REMOTE_URL}, branche main — la doc RDP est prête",
         project_target(pid)),
        ("projects.networked", "projects",
         {"project": pid, "argv": ["curl", "-sS", "https://api.github.com/repos/exemple/outils-reseau"]},
         "Relire la fiche du dépôt sur GitHub avec le réseau, pour les outils réseau", project_target(pid)),
    ) if pid else ()
    await kernel.mind.append([
        rt.EFFECT_PROPOSED.draft(capability="email.send", owner="email", approval=True,
            args_json=json.dumps({"draft": "stream", "account": "perso", "mail": "perso:<stream@example.net>"}),
            summary=Content.of("Partager le programme du prochain stream avec Béa"), context="user_1"),
        rt.EFFECT_PROPOSED.draft(capability="email.send", owner="email", approval=True,
            args_json=json.dumps({"draft": "brouillon-demo-supprime", "account": "perso"}),
            summary=Content.of("Relire une demande dont le brouillon a été supprimé"), context="user_1"),
        # une file comme on en voit une après une journée de travail : des sortes différentes, à décider l'une après
        # l'autre (la page des validations se lit comme un courrier)
        *(rt.EFFECT_PROPOSED.draft(capability=capability, owner=owner, approval=True,
                                   args_json=json.dumps(args, ensure_ascii=False), summary=Content.of(summary),
                                   context=context)
          for capability, owner, args, summary, context in (
              ("teams.send", "teams", {"conversation": "19:projet", "text": "Je regarde ça demain matin."},
               "Répondre sur Teams à Léa (« Projet vitrine »), à ta place : « Je regarde ça demain matin. »", "teams"),
              ("mcp.call", "mcp", {"server": "agenda", "tool": "create_event", "title": "Concert de Béa"},
               "Appeler « create_event » (agenda) : ajouter le concert de Béa, samedi à 20 h", "mcp:agenda"),
              *work[:2],
              ("email.send", "email", {"draft": "relance-libraire", "account": "perso"},
               "Relancer le libraire au sujet de la commande de carnets", "user_1"),
              ("forge.install", "forge", {"app": "meteo", "packages": ["httpx"]},
               "Installer « httpx » pour l'app Météo, qu'elle a forgée", "forge:meteo"),
              ("mcp.call", "mcp", {"server": "notion", "tool": "append_page", "page": "Lectures"},
               "Appeler « append_page » (notion) : noter le livre que Béa a conseillé", "mcp:notion"),
              *work[2:],
          )),
    ], emitter="runtime", origin=Origin.EXTERNAL, correlation="apercu-validations")
    # deux demandes déjà tranchées (refusées : rien ne s'exécute), que l'historique des autorisations montre
    decided = await kernel.mind.append([
        rt.EFFECT_PROPOSED.draft(capability="mcp.call", owner="mcp", approval=True, context="mcp:agenda",
                                 args_json=json.dumps({"server": "agenda", "tool": "delete_event", "title": "Répétition"}),
                                 summary=Content.of("Appeler « delete_event » (agenda) : retirer la répétition de jeudi")),
        rt.EFFECT_PROPOSED.draft(capability="email.send", owner="email", approval=True, context="email",
                                 args_json=json.dumps({"draft": "relance-imprimeur", "account": "perso"}),
                                 summary=Content.of("Relancer l'imprimeur au sujet des affiches"))],
        emitter="runtime", origin=Origin.EXTERNAL, correlation="apercu-historique")
    await kernel.mind.append([
        rt.EFFECT_RESOLVED.draft(proposal=decided.seqs[0], approved=False, by="user_1", capability="mcp.call",
                                 owner="mcp", context="mcp:agenda",
                                 note=Content.of("Garde-la : on la déplacera plutôt.")),
        rt.EFFECT_RESOLVED.draft(proposal=decided.seqs[1], approved=False, by="user_1", capability="email.send",
                                 owner="email", context="email")],
        emitter="runtime", origin=Origin.EXTERNAL, correlation="apercu-historique")


async def _trips(kernel, handle: str) -> None:
    """Deux voyages de Béa, préparés comme dans l'écran Carte (les actions du plugin, en son nom), et un arrêt que Mika
    y a ajouté en conversation : la fiche de Béa a son onglet Voyages (ADR 0204)."""
    made = await perform(kernel, "trips.creer", form(title="Les lacs de Savoie", start="2027-05-14", mode="voiture",
                                                     avoid=["peages"]), by=handle, nonce="apercu-voyage")
    if not made.ok:
        return
    trip = str(made.seqs[0])
    for name, lat, lon, kind, day, note in (
            ("Annecy", 45.899247, 6.129384, "Ville", 1, "Le marché de la vieille ville, le matin"),
            ("Talloires", 45.840612, 6.212843, "Village", 1, ""),
            ("Aix-les-Bains", 45.688374, 5.915091, "Ville", 2, "Se baigner au Grand Port")):
        await perform(kernel, "trips.ajouter_arret", form({"trip": trip}, name=name, lat=lat, lon=lon, kind=kind,
                                                          day=day, index=-1, note=note), by=handle)
    level = 2  # un contenu personnel, comme ceux que ses outils écrivent
    person = kernel.mind.frame().state(trips_c.OWNER).trips[trip].person
    await kernel.mind.append([trips_c.STOP_ADDED.draft(
        trip=trip, person=person, by=trips_c.BY_HER, day=2, kind=Content.of("Abbaye", level=level),
        name=Content.of("Abbaye d'Hautecombe", level=level), coords=Content.of("45.751500,5.844200", level=level),
        note=Content.of("Au bord du lac du Bourget : la traversée en bateau vaut le détour", level=level))],
        emitter=trips_c.OWNER, origin=Origin.EXTERNAL, correlation="apercu-voyages")
    await perform(kernel, "trips.creer", form(title="Un week-end à Lyon", start="", mode="velo", avoid=[]),
                  by=handle, nonce="apercu-voyage-lyon")


#: les fichiers de l'aperçu : pour qui (``bea`` ou l'opérateur), leur nom, leur texte
SENT_FILES = (("bea", "programme-du-stream.md", "# Programme\n\n- Ouverture\n- Les questions du chat\n"),
              ("bea", "liste-de-courses.md", "- pain\n- lait\n- œufs\n"),
              ("operator", "idees-de-niveaux.md", "## Idées\n\n- un niveau sous la pluie\n"))
#: les pièces que Béa lui a envoyées : leur nom, leur sorte, ce qu'elle y a lu
RECEIVED_FILES = (("affiche.png", "image/png", "Une affiche violette pour une exposition de dessins, datée du 14 mai."),
                  ("devis-imprimeur.txt", "text/plain", "Devis de l'imprimeur : 200 affiches A3, 84 euros."))


async def _files(kernel, operator: str, bea: str) -> list[str]:
    """Des fichiers qu'elle a envoyés (à Béa, à l'opérateur) et des pièces que Béa lui a envoyées, leurs octets dans
    leur port, leur fiche au journal, comme ses outils et sa lecture de près les y mettent ; l'opérateur en retire un
    de chaque (ADR 0205). Mémoire › Fichiers envoyés et Pièces reçues, et l'onglet Fichiers de Béa, ont de quoi se
    montrer. Rend les adresses de leurs fiches."""
    sent, received = kernel.ports.get("shares"), kernel.ports.get(attachments_c.PORT)
    if sent is None or received is None:
        return []
    level = 2  # un contenu personnel, comme ceux que ses outils écrivent
    shared, kept = [], []
    for who, name, text in SENT_FILES:
        target, data = bea if who == "bea" else operator, text.encode()
        file = hashlib.blake2b(f"apercu:{target}:{name}".encode(), digest_size=16).hexdigest()
        await sent.put(file, data, subjects=[target])
        shared.append(shares_c.SHARED.draft(file=file, target=target, name=Content.of(name, level=level),
                                            mime="text/markdown", size=len(data),
                                            digest=hashlib.sha256(data).hexdigest(), about=(target,)))
    said = [kernel.mind.decode(e) for e in kernel.mind.store.latest([rt.PERCEPTION_RECEIVED.name], 50)]
    message = next((e.seq for e in said if e.data.handle == bea), 0)
    for index, (name, mime, seen) in enumerate(RECEIVED_FILES, 1):
        data = seen.encode() * 40
        file = file_id(bea, data)
        await received.put(file, data, subjects=[bea])
        kept.append(attachments_c.KEPT.draft(
            file=file, message=message, index=index, handle=bea, name=Content.of(name, level=level), mime=mime,
            size=len(data), digest=hashlib.sha256(data).hexdigest(),
            kind=attachments_c.IMAGE if mime.startswith("image/") else attachments_c.FILE,
            seen=Content.of(seen, level=level), read=True, sensitivity=level))
    await kernel.mind.append(shared, emitter=shares_c.OWNER, origin=Origin.EXTERNAL, correlation="apercu-fichiers")
    await kernel.mind.append(kept, emitter=attachments_c.OWNER, origin=Origin.EXTERNAL,
                             correlation="apercu-fichiers")
    gone_sent, gone_piece = shared[1].data.file, kept[1].data.file
    await perform(kernel, "shares.retirer", {}, by=operator, subject=gone_sent, nonce="apercu-retirer-partage")
    await perform(kernel, "attachments.retirer", {}, by=operator, subject=gone_piece, nonce="apercu-retirer-piece")
    return [*(f"/inspecteur/fiche/partage/{d.data.file}" for d in shared),
            *(f"/inspecteur/fiche/piece/{d.data.file}" for d in kept)]


async def _shares(settings, bea: str, owner: str) -> None:
    """Une boîte de l'opérateur et un compte Teams à une personne, partagés à Béa : Réglages › Droits › Partages a de
    quoi se montrer (ADR 0210). Rangés seulement dans les réglages : ni l'une ni l'autre ne relève rien."""
    who = PERSON + bea
    await settings.save_email(MailConfig(accounts={"atelier": MailAccount(
        label="Atelier", address="atelier@example.test", enabled=False, shares={who: SHARE_READ})}))
    await settings.save_teams(TeamsConfig(accounts={"equipe": TeamsAccount(
        label="Équipe", owner=PERSON + owner, enabled=False, shares={who: SHARE_PREPARE})}))


async def _noticed(kernel, box) -> None:
    """Le mail des maquettes, remarqué comme le relevé l'aurait fait : la liseuse dit ce qu'elle en sait (ADR 0175)."""
    m = box.cached_one("atelier:<maquettes@example.net>")
    if m is None:
        return
    await kernel.mind.append([email_c.NOTICED.draft(
        source="email", kind=email_c.MAIL, summary=Content.of("Léa attend ton avis sur les deux pistes avant jeudi."),
        pertinence=0.85, emotion="curious", intensity=0.4, bundle="email", mail=m.ref, sender=m.sender,
        address=m.address, importance=0.85, needs_reply=True, account=m.account, folder=m.folder,
        dedupe_key=f"mail:{m.ref}")], emitter="email", origin=Origin.EXTERNAL, correlation="apercu-courrier")


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
    text = FRAME.sub(lambda m: f'src="{prefix}cadres/{m.group(1)}.html"', text)
    text = re.sub(r"<script[^>]*(?:console|live)\.js[^>]*></script>", "", text)  # une copie ne relit rien
    return text.replace('<html lang="fr">', f'<html lang="fr" data-theme="{theme}">', 1)


def _name(url: str) -> str:
    slug = url.removeprefix("/inspecteur").strip("/") or "accueil"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", slug)[:120] + ".html"


@contextmanager
def _apart() -> Iterator[None]:
    """Le temps de l'export, l'environnement ne la mène pas à sa vraie vie : ni ses bases sur le serveur MariaDB
    (ADR 0101), que ``build`` ouvrirait quel que soit le dossier, ni sa clé de chiffrement. La vie neuve reste
    dans le dossier temporaire ; l'environnement est rendu tel quel ensuite."""
    saved = {name: os.environ.pop(name) for name in ENVIRONMENT if name in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def export(out: Path) -> list[str]:
    """Rend les pages dans ``out`` ; rend la liste des adresses exportées."""
    logging.getLogger("mika").setLevel(logging.ERROR)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copytree(STATIC, out / "static", dirs_exist_ok=True)
    clock = RealClock()
    sink: list[Callable[[LLMTrace], None]] = []
    # un seul fournisseur, déclaré comme un opérateur le ferait : il sert « répondre », les autres rôles y
    # retombent (replis de rôle) ; chaque appel laisse sa trace (Appels et coûts, Pourquoi a-t-elle dit ça ?)
    gateway = LiveGateway(Gateway({NAME: _Model(clock, latency=0.0, abstain_rate=0.0)}, {"reply": NAME},
                                  clock=clock, voice_roles=frozenset(str(r) for r in VOICE_ROLES),
                                  fallbacks={str(k): str(v) for k, v in FALLBACKS.items()}, slots={NAME: 1},
                                  on_trace=lambda tr: [f(tr) for f in sink]))
    done: list[str] = []
    failed: list[str] = []
    with _apart(), tempfile.TemporaryDirectory() as tmp:
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
            urls: list[str] = ["/inspecteur/"]  # l'accueil, dessiné à la main hors de la carte
            for group in NAVIGATION:
                for d in group.items:
                    base = f"/inspecteur/{d.key}"
                    urls.append(base)
                    if d.layout == "tabs":
                        urls += [f"{base}/{k.split('.', 1)[1]}" for k in d.builtin]
                        urls += [f"{base}/{v.name}" for v in live.kernel.registry.inspectors
                                 if v.section == d.key and not v.hidden]
                        if d.dynamic:  # ses onglets connus au démarrage (la file « À valider ») : ceux de sa barre
                            page = client.get(base, follow_redirects=True).text
                            found = re.findall(rf'class="tab[^"]*" href="({re.escape(base)}/[\w-]+)"', page)
                            urls += [u for u in dict.fromkeys(found) if u not in urls]
                    elif d.layout == "menu":  # chacune de ses pages (les réglages : leur annuaire)
                        page = client.get(f"{base}/apercu" if d.key == "reglages" else base, follow_redirects=True).text
                        found = re.findall(rf'href="({re.escape(base)}/[\w-]+)"', page)
                        urls += [u for u in dict.fromkeys(found) if u not in urls]
            inspection = Inspection(live.kernel)
            for kind in ("person", "handle"):
                for obj in client.portal.call(lambda k=kind: inspection.search(k, "", 10)):
                    base = f"/inspecteur/fiche/{kind}/{quote(obj.key, safe='')}"
                    urls.append(base)
                    urls += [f"{base}?onglet={quote(v.name)}" for v in live.kernel.registry.inspectors if v.subject == kind]
            project = client.portal.call(lambda: _project(live.kernel))  # un projet, et chaque onglet de sa fiche
            client.portal.call(lambda: repository(live.kernel, project, clock.now()))  # son dépôt, son distant
            second = client.portal.call(lambda: _project(live.kernel, title="Préparer le prochain stream",
                description="Un programme clair, des supports prêts et un moment pour les questions du chat.",
                objectives="Choisir les sujets\nPréparer les supports\nRelire le programme", nonce="apercu-stream"))
            for key in (project, second):
                if key:
                    urls.append(f"/inspecteur/fiche/project/{key}")
                    urls += [f"/inspecteur/fiche/project/{key}?onglet={quote(v.name)}"
                             for v in live.kernel.registry.inspectors if v.subject == "project"]
            demo_mail = mailbox(clock.now)
            live.kernel.ports["mail"] = demo_mail
            client.portal.call(lambda: _approvals(live.kernel, project))
            client.portal.call(lambda: _noticed(live.kernel, demo_mail))
            for kind, keys in (("mail", [m.ref for m in demo_mail.inbox] + [m.ref for m in demo_mail.outgoing]),
                               ("brouillon", ["stream", "brouillon-demo-supprime"])):
                for key in keys:
                    base = f"/inspecteur/fiche/{kind}/{quote(key, safe='')}"
                    urls.append(base)
                    urls += [f"{base}?onglet={quote(v.name)}" for v in live.kernel.registry.inspectors if v.subject == kind]
            urls += client.portal.call(lambda: activity(live.kernel))
            client.portal.call(lambda: inner(live.kernel))
            bea = next((a.handle for a in client.portal.call(live.accounts.all) if a.username == "bea"), "")
            if bea:  # ses voyages : l'onglet Voyages de sa fiche (ADR 0204)
                client.portal.call(lambda: _trips(live.kernel, bea))
            adrien = next((a.handle for a in client.portal.call(live.accounts.all) if a.username == "adrien"), "")
            if bea and adrien:  # des fichiers envoyés et reçus, un de chaque retiré (ADR 0205), et leurs fiches
                urls += client.portal.call(lambda: _files(live.kernel, adrien, bea))
                client.portal.call(lambda: _shares(live.settings, bea, adrien))
            for account in client.portal.call(live.accounts.all):
                urls.append(f"/inspecteur/reglages/comptes?compte={account.id}")
                client.portal.call(lambda a=account: live.accounts.create_token(a.id, "Écran de démonstration"))
            urls += [f"/inspecteur/outils/tous?outil={quote(name, safe='')}" for name in sorted(live.kernel.registry.tools)]
            mcp = live.kernel.ports.get("mcp")  # la fiche de chaque service branché, et ses onglets
            for st in (mcp.statuses() if mcp is not None else ()):
                base = f"/inspecteur/fiche/serveur/{quote(st.name, safe='')}"
                urls += [base, *(f"{base}?onglet={v.name}" for v in live.kernel.registry.inspectors
                                 if v.subject == "serveur")]
            ended = client.portal.call(lambda: live.kernel.mind.store.latest(["episode.ended"], 20))
            for episode in ended:
                corr = quote(episode.correlation, safe="")
                urls.append(f"/inspecteur/episode/{corr}")
                urls += [f"/inspecteur/episode/{corr}?onglet={t}" for t, _ in EPISODE_TABS]
            said = client.portal.call(lambda: live.kernel.mind.store.latest(["episode.utterance"], 20))
            urls += [f"/inspecteur/parole/{utterance.seq}" for utterance in said]
            # Les liens du résumé et du déroulé doivent aussi pouvoir s'ouvrir dans l'aperçu statique.
            event_ids = client.portal.call(lambda: live.kernel.mind.store.query_mind(
                select(JournalEvent.seq).order_by(JournalEvent.seq)))
            urls += [f"/inspecteur/evenement/{seq}" for seq, in event_ids]
            urls.append("/inspecteur/decisions/envers?personne=adrien")
            # chaque demande en attente, ouverte (la file des validations, ADR 0177)
            urls += [f"/inspecteur/approbations/en_attente?demande={p.proposal}"
                     for p in live.kernel.mind.frame().get(rt.PENDING_EFFECTS)]
            urls += ["/inspecteur/approbations/en_attente?sorte=projects.networked"]
            urls.append("/inspecteur/maintenant")  # elle, en ce moment : la page qui croise ses facultés
            urls += ["/inspecteur/reglages/fournisseurs?enregistrement=backends&cle=",
                     "/inspecteur/projets?vue_pg1=table", "/inspecteur/personnes?vue_pg1=table",
                     "/inspecteur/fil/conversations?vue_pg1=table", "/inspecteur/projets?etat=archive",
                     "/inspecteur/personnes?q=personne-inconnue", "/inspecteur/fil/conversations?handle=user_1",
                     "/inspecteur/courrier/reception?compte=atelier",
                     "/inspecteur/courrier/reception?compte=atelier&vue_pg1=table",
                     # un message ouvert dans la liseuse, et une vue de la barre de côté (ADR 0175)
                     "/inspecteur/courrier/reception?compte=atelier&lire=atelier%3A%3Cmaquettes%40example.net%3E",
                     "/inspecteur/courrier/reception?etat=a_traiter&dossier=%2A",
                     "/inspecteur/courrier/reception?compte=perso&dossier=Archives",
                     "/inspecteur/courrier/reception?q=aucun-resultat",
                     "/inspecteur/reglages/apercu?q=modele", "/inspecteur/reglages/apercu?q=memoire",
                     "/inspecteur/reglages/apercu?q=aucun-resultat", "/inspecteur/reglages/temperament?profil=anxieuse",
                     "/inspecteur/outils/tous?lot=email", "/inspecteur/outils/tous?lot=email&vue_pg1=table",
                     "/inspecteur/outils/tous?lot=email&outil=email_read", "/inspecteur/outils/tous?q=aucun-resultat",
                     "/inspecteur/systeme/sorties?etat=failed", "/inspecteur/systeme/sorties?etat=done",
                     "/inspecteur/decisions/episodes?issue=failed", "/inspecteur/decisions/episodes?vue_pg1=table",
                     "/inspecteur/memoire/souvenirs?person=Adrien", "/inspecteur/memoire/souvenirs?person=Adrien&vue_pg1=table",
                     "/inspecteur/memoire/souvenirs?q=aucun-resultat", "/inspecteur/memoire/croyances?status=superseded",
                     "/inspecteur/memoire/promesses?status=pending", "/inspecteur/pensees/pensees?vue_pg1=table",
                     "/inspecteur/memoire/consolidation?vue_pg1=table", "/inspecteur/pensees/attentes?vue_pg1=table",
                     "/inspecteur/memoire/souvenirs?vue_pg1=table", "/inspecteur/memoire/croyances?vue_pg1=table",
                     "/inspecteur/memoire/promesses?vue_pg1=table", "/inspecteur/vie/needs?vue_pg1=table",
                     "/inspecteur/vie/needs?periode=24h&vue_pg1=table", "/inspecteur/vie/needs?periode=24h",
                     "/inspecteur/pensees/nuits?vue_pg2=table", "/inspecteur/teams/reponses?vue_pg1=table",
                     "/inspecteur/reglages/comptes?vue_pg1=table", "/inspecteur/systeme/chronologie?vue_pg1=table",
                     "/inspecteur/systeme/processus?vue_pg1=table", "/inspecteur/systeme/processus?pg1=2",
                     "/inspecteur/systeme/processus?pg1=2&vue_pg1=table",
                     "/inspecteur/reglages/comportement-affect?groupe=repos-et-ancre",
                     "/inspecteur/reglages/comptes?nouveau=utilisateur",
                     "/inspecteur/reglages/comptes?nouveau=operateur", "/inspecteur/recherche?q=a",
                     "/inspecteur/action/projects.creer?retour=/inspecteur/projets"]
            for url in dict.fromkeys(u for u in urls if u):
                r = client.get(url, follow_redirects=True)
                if r.status_code != 200:  # une page en erreur ne s'exporte pas comme si de rien n'était
                    failed.append(f"{url} ({r.status_code})")
                    continue
                name = _name(url)
                for digest in dict.fromkeys(FRAME.findall(r.text)):  # le cadre, tant que la page le garde
                    framed = client.get(f"/inspecteur/document/{digest}")
                    (out / "cadres").mkdir(parents=True, exist_ok=True)
                    (out / "cadres" / f"{digest}.html").write_text(framed.text, encoding="utf-8")
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
