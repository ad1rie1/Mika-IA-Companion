"""Parcours d'opérateur hors courrier, avec des états utiles et des filtres réels."""

from __future__ import annotations

import html
import json
import re
import shutil
import time
from pathlib import Path

from mika.contracts import attention, goals, memory
from mika.contracts import runtime as rt
from mika.inspector.pages import approvals as approvals_page
from mika.inspector.pages import decisions
from mika.inspector.ui import STATIC
from mika.kernel.events import Content, Origin
from mika.ports.workshop import Commit, Hosted
from mika.runtime.operations import perform
from tests.fixtures.atelier import Atelier
from tests.fixtures.console_html import ConsoleHTML
from tests.fixtures.mika import connect
from tests.protocol.test_inspector_pages import converse
from tests.protocol.test_web import bootstrap, world  # noqa: F401


def page(client, url, out: Path | None = None):
    response = client.get(url)
    assert response.status_code == 200, (url, response.status_code)
    assert "Cette vue a échoué" not in response.text and "Bloc inconnu" not in response.text, url
    ConsoleHTML(response.text).check()
    if out is not None:
        out.mkdir(exist_ok=True)
        name = re.sub(r"[^a-zA-Z0-9_-]+", "_", url.removeprefix("/inspecteur/")).strip("_") or "accueil"
        body = response.text.replace('/inspecteur/static/', 'static/')
        body = body.replace('method="post"', 'method="dialog"').replace(' data-vitals="/inspecteur/_vitals"', '')
        (out / (name + '.html')).write_text(body)
    return html.unescape(response.text)


def append(client, kernel, drafts, owner="runtime"):
    return client.portal.call(lambda: kernel.mind.append(drafts, emitter=owner, correlation="console-review",
                                                        origin=Origin.GENESIS))


def headers(body):
    return re.findall(r'<th\b[^>]*>([^<]*)</th>', body)


def test_connected_apps_are_paged_and_each_revocation_keeps_its_own_token(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    account = client.portal.call(live.accounts.all)[0]
    async def seed():
        return [await live.accounts.create_token(account.id, f"Écran {n:02}") for n in range(14)]
    tokens = client.portal.call(seed)
    base = f"/inspecteur/reglages/comptes?compte={account.id}"
    first = page(client, base)
    assert "14 au total" in first and first.count('name="action" value="revoke_token"') == 12
    next_url = html.unescape(re.search(r'<a href="([^"]+)" rel="next">', first).group(1))
    assert f"compte={account.id}" in next_url and "page_apps=2" in next_url
    last = page(client, "/inspecteur/reglages/comptes" + next_url)
    assert last.count('name="action" value="revoke_token"') == 2
    def ids(body):
        return set(re.findall(r'name="token" value="(\d+)"', body))
    assert not ids(first) & ids(last)
    assert ids(first) | ids(last) == {str(t.id) for t, _ in tokens}
    assert all(secret not in first + last for _, secret in tokens)
    assert all(not t.revoked for t in client.portal.call(live.accounts.tokens))


def test_reading_pages_show_content_keep_details_and_search_names(world, tmp_path):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    client.portal.call(connect, kernel, "alice", "Alice")
    client.portal.call(connect, kernel, "bob", "Bob")
    append(client, kernel, [rt.PERCEPTION_RECEIVED.draft(handle=who, channel="web", addressed=False,
        text=Content.of(f"{who} : un message en deux paragraphes.\n\nSuite du message {n}."))
        for n in range(61) for who in ("alice", "bob")])
    append(client, kernel, [memory.REMEMBERED.draft(text=Content.of(f"Souvenir {n} : Alice prépare son exposition."),
        about=("alice",), sensitivity=1, importance=0.6) for n in range(61)], "memory")
    append(client, kernel, [attention.THOUGHT_BORN.draft(text=Content.of("L'exposition d'Alice approche."),
        emotion="curious", intensity=0.5, origin="exchange", about=("alice",))], "attention")
    opened = append(client, kernel, [goals.GOAL_OPENED.draft(kind=goals.PROJECT, authority=goals.USER,
        title=Content.of("Préparer les visuels de l'exposition"), owner="alice", bundles=("goals",), max_steps=8,
        source="console-review")], "goals")
    out = tmp_path / "review"
    out.mkdir()
    shutil.copytree(STATIC, out / "static")
    # Conversations : une ligne par personne, le filtre par nom (ADR 0181) ; l'ancienne adresse y mène, filtre gardé
    found = page(client, "/inspecteur/fil/conversations?handle=Alice", out)
    assert found.count('<li class="fil-conv') == 1 and "Suite du message 60" in found
    moved = client.get("/inspecteur/fil/messages?handle=Alice", follow_redirects=False)
    assert moved.status_code == 301 and moved.headers["location"] == "/inspecteur/fil/conversations?handle=Alice"
    messages = page(client, "/inspecteur/fiche/person/alice?onglet=echanges", out)
    assert "alice : un message" in messages and "bob : un message" not in messages
    # la conversation est dessinée (ADR 0121) : le message entier, son numéro, et la même liste en tableau à un clic ;
    # les plus récents en premier (ADR 0181)
    assert 'class="now-card person-chat"' in messages and "Suite du message" in messages and "n° " in messages
    assert messages.index("Suite du message 60") < messages.index("Suite du message 59")
    as_table = html.unescape(re.search(r'<a class="person-as-table" href="([^"]+)"', messages).group(1))
    table = page(client, "/inspecteur/fiche/person/alice" + as_table, out)
    assert "épisode" not in headers(table) and "texte" in headers(table)
    assert "alice : un message" in table and "bob : un message" not in table
    assert "Informations complémentaires" in table
    next_url = html.unescape(re.search(r'<a href="([^"]+)" rel="next">', messages).group(1))
    tail = page(client, "/inspecteur/fiche/person/alice" + next_url, out)
    assert "Plus récents" in tail and "alice : un message" in tail
    memories = page(client, "/inspecteur/memoire/souvenirs?person=Alice&page=2", out)
    assert "Souvenir 0 : Alice" in memories and "importance" not in headers(memories)
    assert "Informations complémentaires" in memories and "importance" in memories
    none = page(client, "/inspecteur/memoire/souvenirs?q=aucun-resultat")
    assert "aucun résultat pour ces filtres" in none and "Souvenir 0" not in none
    for url in ("personnes/personnes", "identites/annuaire", "pensees/pensees", "buts/projets",
                "buts/vivants", "buts/clos", "vie/humeur", "vie/postures", "vie/needs", "vie/rythme", "vie/soi",
                "pensees/remarque", "pensees/attentes", "pensees/nuits", "memoire/croyances", "memoire/promesses",
                "memoire/consolidation", "personnes/liens", "personnes/presents", "approbations/identites",
                "identites/politique", "fil/questions", "decisions/maintenant", "decisions/en_cours",
                "decisions/initiatives", "decisions/selections", "decisions/episodes", "decisions/echeances",
                "sens/flux", "sens/camera", "sens/appareils", "apps", "systeme/sante", "systeme/processus",
                "systeme/anomalies", "systeme/sorties", "systeme/passerelle", "systeme/appels", "systeme/stockage",
                "systeme/chronologie", "systeme/operations", "systeme/etat", "systeme/contributions",
                "systeme/vues", "systeme/simulations"):
        page(client, "/inspecteur/" + url, out)
    for spec in live.kernel.registry.inspectors:
        if spec.subject == "person":
            page(client, "/inspecteur/fiche/person/alice?onglet=" + spec.name, out)
        elif spec.subject == "goal":
            page(client, f"/inspecteur/fiche/goal/{opened.seqs[0]}?onglet=" + spec.name, out)
    fiche = page(client, "/inspecteur/fiche/person/alice?onglet=memoire&page_souvenir=2&avant=20&q=exposition")
    tabs = re.search(r'<nav class="tabs".*?</nav>', fiche, re.S).group()
    assert "page_souvenir" not in tabs and "avant=" not in tabs and "q=exposition" in tabs


def test_sparse_episode_filters_can_continue_after_the_scan_budget(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    monkeypatch.setattr(decisions, "EPISODE_SCAN", 2)
    monkeypatch.setattr(decisions, "EPISODE_SCAN_BATCHES", 1)
    append(client, live.kernel, [rt.EPISODE_ENDED.draft(kind="REPLY", outcome=state, target="alice", detail=detail)
        for state, detail in (("failed", "Échec ancien à retrouver"), ("ok", "Réussi 1"), ("ok", "Réussi 2"))])
    body = page(client, "/inspecteur/decisions/episodes?sorte=REPLY&issue=failed")
    assert "La recherche continue" in body
    next_url = html.unescape(re.search(r'<a href="([^"]+)" rel="next">', body).group(1))
    tail = page(client, "/inspecteur/decisions/episodes" + next_url)
    assert "Échec ancien à retrouver" in tail and "Réussi 1" not in tail
    assert "Plus récents" in tail


def test_empty_outbox_filter_does_not_show_successful_deliveries(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    converse(client)
    all_ = page(client, "/inspecteur/systeme/sorties")
    assert "parti" in all_
    failed = page(client, "/inspecteur/systeme/sorties?etat=failed")
    # la liste des derniers départs, filtrée : vide, sans les messages partis (le résumé par sorte, lui, compte tout)
    assert "Rien dans cet état" in failed and 'class="sys-out-recent-list"' not in failed
    assert "État inconnu" in page(client, "/inspecteur/systeme/sorties?etat=inconnu")


def test_last_thought_and_night_history_pages_keep_the_return_path(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    for view in ("pensees", "remarque", "attentes", "nuits"):
        body = page(client, f"/inspecteur/pensees/{view}?avant=1&pile=0,90")
        assert "Plus récents" in body, view


def test_pending_approvals_read_like_a_mailbox(world, tmp_path):  # noqa: F811
    """À valider › Actions à autoriser : la file à gauche, une ligne par demande (50 par page), une seule demande
    ouverte à droite — sa place dans la file, ses voisines ; des puces par sorte (« Toutes » sans compte : l'onglet le
    dit ; la file ne se compte que filtrée) ; après une décision, la suivante s'ouvre (dans la même sorte), et tout
    l'historique de ce genre est à un lien."""
    client, live, _ = world
    bootstrap(client)
    kinds = ["review.fictive"] * 40 + ["review.other"] * 15
    append(client, live.kernel, [rt.EFFECT_PROPOSED.draft(capability=k, owner="review", args_json="{}",
        summary=Content.of(f"Proposition de revue {n:02}"), context="test") for n, k in enumerate(kinds)])
    pending = [p.proposal for p in live.kernel.mind.frame().get(rt.PENDING_EFFECTS)]

    def ids(s):
        return re.findall(r'<li><a href="\?(?:[^"]*&)?demande=(\d+)"', s)
    body = page(client, "/inspecteur/approbations/en_attente", tmp_path / "review")
    assert len(ids(body)) == 50 and body.count('class="approve-form"') == 1  # une ligne chacune, une seule ouverte
    assert f'name="proposal" value="{pending[0]}"' in body and "<b class=\"now-num\">1</b> sur <span class=\"now-num\">55" in body
    tail = page(client, "/inspecteur/approbations/en_attente?page=2", tmp_path / "review")
    assert len(ids(tail)) == 5 and "Précédente" in tail and "?page=2&demande=" in tail  # la page se garde
    assert set(map(int, ids(body) + ids(tail))) == set(pending)
    # des puces par sorte, qui filtrent la file ; la place dans la file suit le filtre ; « Toutes » ne répète pas le
    # compte de l'onglet, et la file ne se compte que quand une puce filtre
    chips = body.split('class="hm-chips apv-kinds"', 1)[1].split("</nav>", 1)[0]
    assert re.search(r'aria-current="page">Toutes</a>', chips) and "55" not in chips
    assert '<span class="hm-count">40' in chips and '<span class="hm-count">15' in chips
    assert "now-num" not in body.split('class="apv-queue-head"', 1)[1].split("</header>", 1)[0]
    other = page(client, "/inspecteur/approbations/en_attente?sorte=review.other")
    assert len(re.findall(r'<li><a href="\?sorte=review.other&demande=', other)) == 15
    assert "<b class=\"now-num\">1</b> sur <span class=\"now-num\">15" in other
    assert '<span class="person-count now-num">15</span>' in other.split('class="apv-queue-head"', 1)[1]
    # ouvrir la troisième : ses voisines ; la refuser ouvre la quatrième
    third = page(client, f"/inspecteur/approbations/en_attente?demande={pending[2]}")
    assert "<b class=\"now-num\">3</b> sur" in third and "← Précédente" in third and "Suivante →" in third
    assert f'name="suivante" value="{pending[3]}"' in third
    csrf = client.cookies.get("csrftoken")
    done = client.post("/inspecteur/approbations", data={"csrf": csrf, "proposal": str(pending[2]),
                                                         "decision": "reject", "suivante": str(pending[3])},
                       follow_redirects=False)
    assert done.status_code == 303 and f"demande={pending[3]}" in done.headers["location"]
    after = page(client, done.headers["location"])
    assert "Refusé." in after and f'name="proposal" value="{pending[3]}"' in after
    # son historique : la décision d'avant, du même genre
    history = after.split('class="apv-history"', 1)[1].split("</section>", 1)[0]
    assert "Proposée" in history and "refusée" in history and f"n° {pending[2]}" in history
    # tout l'historique, de ce genre de demande : le lien garde sa sorte
    assert 'href="/inspecteur/approbations/historique?sorte=review.fictive">Tout l\'historique' in history


def test_a_request_links_to_its_source(world):  # noqa: F811
    """La demande ouverte dit d'où elle vient, en liens : le brouillon et la boîte d'un mail, la fiche de la personne
    (« d'Adrien », élidé devant une voyelle) et leur conversation."""
    client, live, _ = world
    bootstrap(client)
    client.portal.call(connect, live.kernel, "user_1", "Adrien")
    append(client, live.kernel, [rt.EFFECT_PROPOSED.draft(capability="email.send", owner="email",
        args_json='{"draft": "d-1", "account": "perso"}', summary=Content.of("Répondre au libraire"),
        context="user_1")])
    body = page(client, "/inspecteur/approbations/en_attente")
    sources = body.split('class="apv-sources"', 1)[1].split("</p>", 1)[0]
    assert '/inspecteur/fiche/brouillon/d-1">Le brouillon' in sources
    assert '/inspecteur/courrier/reception?compte=perso">La boîte « perso »' in sources
    assert ">La fiche d'Adrien<" in sources and "/inspecteur/fiche/person/user_1?onglet=echanges" in sources


def _halt(client, kernel):
    """Plus de processus de fond : la page ne bouge que de ce que le test écrit (les effets approuvés partent encore)."""
    async def halt():
        kernel.scheduler.stop()
        await kernel.scheduler.cancel_all()
    client.portal.call(halt)


def _executed(client, kernel, n: int) -> None:
    """Attend que ``n`` exécutions soient au journal : la file de sortie exécute d'elle-même ce qui est approuvé."""
    for _ in range(200):
        if len(client.portal.call(lambda: kernel.mind.store.latest([rt.EFFECT_EXECUTED.name], 100))) >= n:
            return
        time.sleep(0.05)
    raise AssertionError(f"{n} exécution(s) attendue(s)")


def _reader(body: str) -> str:
    return body.split('class="now-card hm-approval apv-reader', 1)[1].split("</article>", 1)[0]


def test_a_channel_is_never_taken_for_a_person(world):  # noqa: F811
    """Une réponse Teams, un mail : leur contexte est un canal (« teams », « email »), jamais une personne — ni « La
    fiche de teams » dans leur source, ni un lien vers une fiche qui n'existe pas ; la file et l'historique le disent
    pareil, par la composition (audit du 2026-11-05, C1-01)."""
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    asked = append(client, kernel, [
        rt.EFFECT_PROPOSED.draft(capability="teams.send", owner="teams", context="teams",
                                 args_json='{"conversation": "19:projet", "draft": "r-1"}',
                                 summary=Content.of("Répondre sur Teams à Léa, à ta place")),
        rt.EFFECT_PROPOSED.draft(capability="email.send", owner="email", context="email",
                                 args_json='{"draft": "d-1", "account": "perso"}',
                                 summary=Content.of("Répondre au libraire"))]).seqs
    body = page(client, f"/inspecteur/approbations/en_attente?demande={asked[0]}")
    sources = body.split('class="apv-sources"', 1)[1].split("</p>", 1)[0]
    assert "La réponse préparée" in sources and "La conversation Teams" in sources
    assert "/fiche/person/" not in sources and "La fiche" not in sources
    rows = body.split('class="apv-list"', 1)[1].split("</ol>", 1)[0]
    assert '<span class="apv-row-ctx">Teams</span>' in rows and '<span class="apv-row-ctx">courrier</span>' in rows
    mail = page(client, f"/inspecteur/approbations/en_attente?demande={asked[1]}")
    assert "/fiche/person/" not in mail.split('class="apv-sources"', 1)[1].split("</p>", 1)[0]
    # tranchée, la réponse Teams se dit encore « Teams » dans l'historique, sans fiche de personne
    client.post("/inspecteur/approbations", data={"csrf": client.cookies.get("csrftoken"),
                                                  "proposal": str(asked[0]), "decision": "reject"})
    history = page(client, "/inspecteur/approbations/historique")
    entry = history.split("Répondre sur Teams à Léa", 1)[0].rsplit('<li class="hist-item', 1)[1]
    assert "· Teams" in entry and "/fiche/person/" not in entry


def test_a_chip_never_repeats_a_tab(world):  # noqa: F811
    """Sur « Tout ce qui attend », une sorte qu'un onglet de la file garde déjà (les courriers, Teams) n'a pas de puce :
    deux chemins ne mènent pas au même filtre ; celles qu'aucun onglet ne garde en ont une (C1-06)."""
    client, live, _ = world
    bootstrap(client)
    append(client, live.kernel, [rt.EFFECT_PROPOSED.draft(capability=k, owner="review", args_json="{}",
                                                          summary=Content.of(f"Demande {n}"), context="test")
                                 for n, k in enumerate(["email.send", "email.send", "teams.send", "review.reseau",
                                                        "review.reseau", "review.envoi"])])
    body = page(client, "/inspecteur/approbations/en_attente")
    chips = body.split('class="hm-chips apv-kinds"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r'href="\?sorte=([\w.]+)"', chips) == ["review.reseau", "review.envoi"]
    # une adresse filtrée sur une sorte d'onglet : la puce qui filtre reste, qu'on voie ce qui est filtré
    mails = page(client, "/inspecteur/approbations/en_attente?sorte=email.send")
    assert 'href="?sorte=email.send"' in mails.split('class="hm-chips apv-kinds"', 1)[1].split("</nav>", 1)[0]
    assert "apv-kinds" not in page(client, "/inspecteur/approbations/courriers")  # une seule sorte : pas de puces


def _project(client, kernel, title: str) -> int:
    """Un projet créé comme un opérateur le ferait (l'action de la console)."""
    got = client.portal.call(lambda: perform(kernel, "projects.creer", {
        "_champs": ["title", "description", "objectives", "constants", "mode", "schedule", "days", "start", "end",
                    "cadence_hours", "runs_per_day", "priority", "branch", "tool_memory"],
        "title": [title], "description": ["Un projet de test."], "objectives": ["Écrire l'outil"],
        "constants": [""], "mode": ["persona"], "schedule": ["manual"], "days": ["weekdays"], "start": ["9:00"],
        "end": ["18:00"], "cadence_hours": ["24"], "runs_per_day": ["0"], "priority": ["normal"], "branch": ["main"],
        "tool_memory": ["on"]}, by="user_1", nonce=f"test-{title}"))
    assert got.ok, got
    return int(got.go.key.split("/", 1)[1])


class _Hosts:
    """Des dépôts distants en mémoire (le port ``RepoHost``), un par adresse."""

    def __init__(self, hosted: dict[str, Hosted]) -> None:
        self.hosted = hosted

    def handles(self, url: str) -> bool:
        return url in self.hosted

    async def read(self, url: str, branch: str, *, fresh: bool = False, since: int = 0) -> Hosted:
        return self.hosted[url]

    async def compare(self, url: str, base: str, head: str) -> tuple[int, int] | None:
        return None


def test_a_push_is_approved_on_what_leaves_its_raw_arguments_folded(world):  # noqa: F811
    """Pousser vers un dépôt distant se décide sur un aperçu — le dépôt, la branche, le commit épinglé, les
    enregistrements que le distant n'a pas —, pas sur un JSON ; une récupération dit ce qui arrivera. Une demande sans
    aperçu montre ses arguments un par ligne ; le JSON et la clé restent repliés sous « Détails techniques » (C1-07)."""
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    pid = _project(client, kernel, "Outils réseau")
    atelier = Atelier(token="ghp_secret")

    async def work() -> list[Commit]:
        for path, message in (("README.md", "le README"), ("rdp.py", "le module RDP")):
            await atelier.write(pid, path, "x\n")
            await atelier.commit(pid, message)
        return await atelier.commits(pid, 10)  # le plus récent d'abord
    commits = client.portal.call(work)
    ours, theirs = "https://github.com/moi/outils.git", "https://github.com/moi/amont.git"
    kernel.ports["workshop"] = atelier
    kernel.ports["repo_host"] = _Hosts({
        ours: Hosted(name="moi/outils", url="https://github.com/moi/outils", branch="main", head=commits[1].sha,
                     commits=tuple(commits[1:])),  # le distant a tout, sauf le module RDP
        theirs: Hosted(name="moi/amont", url="https://github.com/moi/amont", branch="main", head="e0e0e0e",
                       commits=(Commit("e0e0e0e", 0, "une correction d'Adrien"), commits[0]))})
    asked = append(client, kernel, [
        rt.EFFECT_PROPOSED.draft(capability="projects.push", owner="projects", context=f"project:{pid}",
                                 args_json=json.dumps({"project": pid, "url": ours, "branch": "main",
                                                       "sha": commits[0].sha}),
                                 summary=Content.of("Pousser le module RDP")),
        rt.EFFECT_PROPOSED.draft(capability="projects.pull", owner="projects", context=f"project:{pid}",
                                 args_json=json.dumps({"project": pid, "url": theirs, "branch": "main"}),
                                 summary=Content.of("Récupérer la correction d'Adrien")),
        rt.EFFECT_PROPOSED.draft(capability="review.sans_apercu", owner="review", context="test",
                                 args_json=json.dumps({"cible": "atelier", "essais": 3, "options": ["a", "b"]}),
                                 summary=Content.of("Une demande sans aperçu"))]).seqs
    push = _reader(page(client, f"/inspecteur/approbations/en_attente?demande={asked[0]}"))
    shown = push.split('aria-label="Aperçu"', 1)[1].split("</section>", 1)[0]
    assert f"Pousser le commit {commits[0].sha} (« le module RDP ») vers {ours}, branche main." in shown
    assert f"- {commits[0].sha[:7]} le module RDP" in shown and "le README" not in shown  # ce que le distant n'a pas
    folded = push.split('<details class="hm-subfold">', 1)[1].split("</details>", 1)[0]
    assert "projects.push" in folded and f'"sha": "{commits[0].sha}"' in folded
    assert "Ton accord est attendu" in push
    pull = _reader(page(client, f"/inspecteur/approbations/en_attente?demande={asked[1]}"))
    shown = pull.split('aria-label="Aperçu"', 1)[1].split("</section>", 1)[0]
    assert f"Récupérer dans l'atelier {theirs}, branche main" in shown and "- e0e0e0e une correction d'Adrien" in shown
    assert "le module RDP" not in shown  # l'atelier l'a déjà
    plain = _reader(page(client, f"/inspecteur/approbations/en_attente?demande={asked[2]}"))
    executed, folded = plain.split('aria-label="Ce qui sera exécuté"', 1)[1].split('<details class="hm-subfold">', 1)
    assert "<dt>cible</dt><dd>atelier</dd>" in executed and "<dt>essais</dt><dd>3</dd>" in executed
    assert '<dt>options</dt><dd>["a", "b"]</dd>' in executed and "review.sans_apercu" not in executed
    assert '"essais": 3' in folded and "review.sans_apercu" in folded


def test_the_history_filters_by_sort_and_issue_and_never_splits_a_request(world, monkeypatch):  # noqa: F811
    """L'historique se filtre par sorte (des puces) et par issue (un bouton à choix au bout de la barre d'onglets, qui
    garde la sorte) ; la clé de la capacité au survol, plus en clair ; vide, un bandeau, sans carte qui redise l'intro ;
    une page compte des demandes, pas des événements : une décision et son exécution ne se séparent jamais (C1-08)."""
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    _halt(client, kernel)
    asked = append(client, kernel, [rt.EFFECT_PROPOSED.draft(capability=k, owner="review", args_json="{}",
                                                             summary=Content.of(text), context="test")
                                    for k, text in (("review.reseau", "Lancer la commande réseau"),
                                                    ("review.envoi", "Envoyer le rapport"),
                                                    ("review.envoi", "Envoyer la relance"))]).seqs
    append(client, kernel, [rt.EFFECT_RESOLVED.draft(proposal=p, approved=ok, by="user_1", capability=k,
                                                     owner="review", context="test")
                            for p, ok, k in zip(asked, (True, False, False),
                                                ("review.reseau", "review.envoi", "review.envoi"), strict=True)])
    _executed(client, kernel, 1)  # la commande approuvée revient de la file de sortie : en échec (capacité inconnue)
    url = "/inspecteur/approbations/historique"
    everything = page(client, url)
    listed = everything.split('data-tab="approbations/historique"', 1)[1]
    chips = listed.split('aria-label="Sorte de demande"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r'href="([^"]+)"', chips) == [url, f"{url}?sorte=review.envoi", f"{url}?sorte=review.reseau"]
    seg = everything.split('<nav class="seg" aria-label="Issue">', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r">([^<]+)</a>", seg) == ["Toutes", "Approuvées", "Refusées", "En échec"]
    assert "<code>" not in listed and 'title="review.envoi"' in listed  # la clé au survol
    sent = page(client, f"{url}?sorte=review.envoi")
    assert "Envoyer le rapport" in sent and "Envoyer la relance" in sent and "Lancer la commande réseau" not in sent
    seg = sent.split('<nav class="seg" aria-label="Issue">', 1)[1].split("</nav>", 1)[0]
    assert 'href="?sorte=review.envoi&issue=refuse"' in seg  # l'issue garde la sorte
    failed = page(client, f"{url}?issue=echec").split('class="hist-list"', 1)[1]
    assert "Lancer la commande réseau" in failed and "Envoyer" not in failed
    refused = page(client, f"{url}?issue=refuse").split('class="hist-list"', 1)[1]
    assert "Envoyer le rapport" in refused and "Lancer la commande réseau" not in refused
    none = page(client, f"{url}?sorte=review.reseau&issue=refuse").split('data-tab="approbations/historique"', 1)[1]
    assert 'class="hm-calm"' in none and "Aucune demande tranchée ne correspond" in none and "now-card" not in none
    # un filtre qui écarte beaucoup : la lecture s'arrête à son budget et dit que la recherche continue
    monkeypatch.setattr(approvals_page, "HISTORY_SCAN", 1)
    monkeypatch.setattr(approvals_page, "HISTORY_SCAN_BATCHES", 1)
    sparse = page(client, f"{url}?sorte=review.envoi&issue=approuve")
    assert "La recherche continue" in sparse and re.search(r'<a href="[^"]*avant=\d+[^"]*" rel="next">', sparse)
    monkeypatch.undo()
    # une page compte des demandes : la décision approuvée (la plus ancienne) et son exécution (le dernier événement
    # du journal) restent ensemble, sur la seconde page
    monkeypatch.setattr(approvals_page, "HISTORY_PAGE", 2)
    first = page(client, url)
    assert "Envoyer la relance" in first and "Envoyer le rapport" in first and "Lancer la commande réseau" not in first
    older = html.unescape(re.search(r'<a href="([^"]+)" rel="next">', first).group(1))
    second = page(client, url + older)
    entry = second.split("Lancer la commande réseau", 1)[1].split("</ol>", 1)[0]
    assert ">approuvé<" in entry and ">en échec<" in entry and "Envoyer" not in second.split('class="hist-list"')[1]


def test_large_episode_keeps_its_outcome_and_every_event_accessible(world, tmp_path):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    drafts = [rt.EPISODE_STARTED.draft(kind="REPLY", target="alice", reason="Un long échange")]
    drafts += [rt.PERCEPTION_RECEIVED.draft(handle="alice", channel="web", addressed=False,
               text=Content.of(f"Étape de l'épisode {i:03}")) for i in range(550)]
    drafts += [rt.EPISODE_ENDED.draft(kind="REPLY", outcome="done", detail="FIN ÉPISODE LONG")]
    append(client, live.kernel, drafts)
    url = '/inspecteur/episode/console-review'
    summary = page(client, url, tmp_path / 'review')
    assert 'FIN ÉPISODE LONG' in summary and 'Résultat de l’épisode' in summary
    first = page(client, url + '?onglet=deroule', tmp_path / 'review')
    assert '552 au total' in first and 'en cours ou interrompu' not in first
    assert 'FIN ÉPISODE LONG' not in first
    tail = page(client, url + '?page=23', tmp_path / 'review')
    assert 'FIN ÉPISODE LONG' in tail and 'Précédente' in tail
    assert 'runtime.episode.ended' in tail or rt.EPISODE_ENDED.name in tail


def test_activity_keeps_open_work_pending_question_and_recent_failure_separate(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel
    async def seed():
        kernel.scheduler.stop()
        await kernel.scheduler.cancel_all()
        question = await kernel.mind.append([rt.PERCEPTION_RECEIVED.draft(handle='user_1', channel='web',
            text=Content.of('Une question encore en attente'))], emitter='runtime', origin=Origin.EXTERNAL,
            correlation='activity-pending')
        await kernel.mind.append([rt.EPISODE_STARTED.draft(kind='REPLY', target='user_1', reply_to=question.seqs[0])],
            emitter='runtime', origin=Origin.GENESIS, correlation='activity-open')
        await kernel.mind.append([rt.EPISODE_STARTED.draft(kind='TASK'),
            rt.EPISODE_ENDED.draft(kind='TASK', outcome='failed', detail='Service momentanément indisponible')],
            emitter='runtime', origin=Origin.GENESIS, correlation='activity-failed')
    client.portal.call(seed)
    before = client.portal.call(lambda: kernel.mind.head)
    body = page(client, '/inspecteur/decisions/en_cours')
    # dessinée (ADR 0121) : ce qu'elle fait, ce qui attend, ce qu'elle vient de faire
    assert 'Relevé ' in body and 'Actualiser' in body and 'Sorties à vérifier' in body
    assert 'En ce moment' in body and 'Ce qui attend' in body and "Ce qu'elle vient de faire" in body
    assert 'Elle répond à' in body and 'Suivre cet épisode' in body
    assert '/inspecteur/episode/activity-open' in body and '/inspecteur/episode/activity-failed' in body
    assert 'Toutes les questions sans réponse' in body and 'Service momentanément indisponible' in body
    assert client.portal.call(lambda: kernel.mind.head) == before
    history = page(client, '/inspecteur/decisions/episodes?issue=failed')
    # dans sa forme (ADR 0177) : le fil des épisodes jour par jour ; en tableau, la liste de la console
    assert 'class="eps-feed"' in history and 'Service momentanément indisponible' in history
    table = page(client, '/inspecteur/decisions/episodes?issue=failed&vue_pg1=table')
    assert 'eps-feed' not in table and 'Service momentanément indisponible' in table
