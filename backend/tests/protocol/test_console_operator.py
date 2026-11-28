"""La console au service de l'opérateur (ADR 0042) : ce qu'il vit, page par page.

- « Pourquoi a-t-elle dit ça ? » : une page par parole, liée depuis le fil ;
- des noms plutôt que des clés, un filtre « vers » qui comprend un nom, un oubli
  qui se confirme en retapant le nom affiché ;
- une connexion qui ne se laisse pas deviner, une touche Entrée qui ne décide
  jamais d'un bouton secondaire ;
- des réglages qui refusent ce qui mettrait tout en panne (un fuseau inventé),
  qui renomment sans rien perdre, qui ne joignent un fournisseur (ou le serveur
  d'une boîte, pour ses dossiers à cocher) que sur demande ;
- des listes qui ne perdent rien entre deux pages, ne mentent pas sur leur total,
  et des badges qu'on peut éteindre.
"""

from __future__ import annotations

import html
import logging
import re

from sqlalchemy import func, insert, select

from mika.app.domains.mail.settings import MailSettings
from mika.app.domains.projects.settings import ProjectsSettings
from mika.contracts import runtime as rt
from mika.inspector.pages.system import OUTBOX_PAGE
from mika.inspector.ui import env as templates
from mika.kernel.builtin import KernelParams
from mika.kernel.events import Content, Origin, VoiceProvenance
from mika.kernel.registry import _zone
from mika.ports.journal import JournalOutbox
from mika.ports.mail import Folder
from mika.runtime import health, operations
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_web import WS, bootstrap, recv_until, world  # noqa: F401 — fixture partagée

BASE = "/admin"
HOSTILE = '<script>alert("x")</script>'


def html_of(r) -> str:
    return html.unescape(r.text)


def post(client, path: str, data: dict, **kw):
    return client.post(path, data={"csrf": client.cookies.get("csrftoken"), **data}, **kw)


def converse(client, text: str = "raconte-moi ta journée") -> None:
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "message": text, "client_msg_id": "o1"})
        recv_until(ws, "speech")


# ── Pourquoi a-t-elle dit ça ? ────────────────────────────────────────────


def test_why_did_she_say_that_is_one_click_from_the_thread(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    converse(client, f"salut {HOSTILE}")
    thread = client.get(f"{BASE}/fiche/person/user_1?onglet=echanges").text
    # un lien « pourquoi ? » sous chacune de ses bulles (la conversation est dessinée, ADR 0121)
    links = re.findall(r'href="(/admin/parole/(\d+))"', thread)
    assert links, "chaque parole d'elle mène à son « pourquoi »"
    url, seq = links[0]
    r = client.get(url)
    page = html_of(r)
    assert r.status_code == 200
    ConsoleHTML(r.text).check()
    assert "Pourquoi a-t-elle dit ça ?" in page and "Ce qu'elle a dit" in page
    assert "Elle répondait au message de" in page  # la cause, en mots
    assert "Ce qu'elle avait sous les yeux" in page and "Qui elle a en face" in page  # sections en français
    assert "Ce dont elle s'est souvenue" in page and "Ce qu'elle a fait" in page
    assert "<script>alert" not in r.text and "&lt;script&gt;alert" in r.text  # le texte hostile reste du texte
    # la clé d'une section ne se lit qu'au détail : jamais en libellé de ligne
    assert not re.search(r"<td>who</td>", r.text)
    # dessinée (ADR 0121) : son humeur, sa réponse pas à pas depuis le texte brut du modèle, le texte de chaque section
    # et le contexte complet, ses outils en main
    assert "handmade/parole.css" in r.text and 'class="now-page parole"' in r.text
    assert "Son humeur à ce moment-là" in page and "Sa réponse, pas à pas" in page and "Le modèle principal" in page
    assert "Le contexte complet, tel qu'envoyé au modèle" in page and "QUI TU AS EN FACE" in page
    # ses nombres accordés, jamais « (s) » (« 61 outils en main, 0 appelé. »)
    assert re.search(r"\d+ outils? en main, \d+ appelés?\.", page) and "(s)" not in page
    # le grand encart ne redit pas la ligne de faits de l'en-tête (à qui, quand, l'issue, la voix, le fil) : sa phrase
    # sous « Ce qu'elle a dit », et seulement l'autrice en puce s'il y en a une
    hero = html.unescape(r.text.split('class="now-hero parole-hero', 1)[1].split("</section>", 1)[0])
    assert "Ce qu'elle a dit</p>" in hero and "Ce qu'elle a dit · à" not in hero
    assert "dans le fil" not in hero and "a parlé" not in hero
    assert all("autrice" in chip for chip in re.findall(r'<ul class="now-chips">(.*?)</ul>', hero, re.S))
    assert "dans le fil" in page  # l'en-tête, lui, le dit toujours
    # son humeur est le texte de son prompt, au « tu » parce qu'il s'adresse à elle : le libellé le dit, le texte est cité
    inner = r.text.split('class="parole-inner"', 1)[1].split("</dl>", 1)[0]
    assert "<dt>dans son prompt : son humeur</dt>" in inner and '<blockquote class="now-voice">' in inner
    # au repli (une liste demandée en tableau), les blocs de la console disent la même chose
    fallback = client.get(f"{url}?vue_x=table")
    assert fallback.status_code == 200 and "now-page parole" not in fallback.text
    ConsoleHTML(fallback.text).check()
    assert "Son humeur à ce moment-là" in html_of(fallback) and "Sa réponse, pas à pas" in html_of(fallback)
    assert "dans son prompt : son humeur" in html_of(fallback)
    # le même lien depuis l'épisode, et depuis l'événement de la parole
    utterance = client.portal.call(lambda: live.kernel.mind.store.get_events([int(seq)]))[0]
    said = client.get(f"{BASE}/episode/{utterance.correlation}?onglet=dit").text
    assert f"/admin/parole/{seq}" in said
    # l'onglet Prompt de l'épisode reprend les mêmes libellés accordés (why.prompt_view, parole/macros.html)
    prompt_tab = html.unescape(client.get(f"{BASE}/episode/{utterance.correlation}?onglet=prompt").text)
    assert re.search(r"caractères?, \d+ tours? de conversation\.", prompt_tab) and "tour(s)" not in prompt_tab
    assert f"/admin/parole/{seq}" in client.get(f"{BASE}/evenement/{seq}").text
    # contre-exemples : un message de la personne n'est pas une de ses paroles
    asked = client.portal.call(lambda: live.kernel.mind.store.latest([rt.PERCEPTION_RECEIVED.name], 1))[0]
    assert client.get(f"{BASE}/parole/{asked.seq}").status_code == 404
    assert client.get(f"{BASE}/parole/99999999999999999999999").status_code == 404


def test_episodes_name_people_and_the_filter_understands_a_name(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    converse(client)
    episodes = html_of(client.get(f"{BASE}/decisions/episodes"))
    assert ">adrien<" in episodes  # le nom, pas « user_1 »
    by_name = html_of(client.get(f"{BASE}/decisions/episodes?cible=Adrien"))
    assert "Aucun épisode ne correspond" not in by_name and ">adrien<" in by_name
    nobody = html_of(client.get(f"{BASE}/decisions/episodes?cible=Personne-de-ce-nom"))
    assert "Aucun épisode ne correspond" in nobody
    towards = client.get(f"{BASE}/decisions/envers?personne=adrien")
    assert towards.status_code == 200 and "Envers adrien" in html_of(towards)
    ConsoleHTML(towards.text).check()
    # depuis sa fiche : « que ferait-elle envers elle ? » (par sa clé), et chaque parole de ses échanges mène à
    # son « pourquoi » (un lien sous sa bulle : l'onglet est dessiné, ADR 0121)
    fiche = client.get(f"{BASE}/fiche/person/user_1").text
    link = re.search(r'href="(/admin/decisions/envers\?personne=[^"]+)"', fiche)
    assert link and "Envers adrien" in html_of(client.get(html.unescape(link.group(1))))
    assert re.search(r'href="/admin/parole/\d+"',
                     client.get(f"{BASE}/fiche/person/user_1?onglet=echanges").text)


def test_forgetting_someone_is_confirmed_by_retyping_the_name_shown(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    converse(client)
    fiche = html_of(client.get(f"{BASE}/fiche/person/user_1"))
    assert "Retape « adrien » pour confirmer" in fiche
    wrong = post(client, f"{BASE}/oublier/person/user_1", {"_confirmer": "quelqu'un"})
    assert wrong.status_code == 400 and "Retape « adrien »" in html_of(wrong)
    done = post(client, f"{BASE}/oublier/person/user_1", {"_confirmer": "  Adrien "}, follow_redirects=False)
    assert done.status_code == 303
    # l'accueil, où l'oubli ramène, le confirme (son gabarit ne montrait pas les messages)
    home = client.get(done.headers["location"])
    assert home.status_code == 200 and "est oublié·e" in html_of(home)
    # le compte accordé, jamais « contenu(s) effacé(s) » (audit du 2026-11-05, C8-14)
    assert re.search(r"est oublié·e \(\d+ contenus? effacés?\)", html_of(home)) and "contenu(s)" not in html_of(home)


# ── accès ─────────────────────────────────────────────────────────────────


def test_console_login_cannot_be_guessed_and_says_so(world, caplog):  # noqa: F811
    client, live, _ = world
    bootstrap(client, password="un-mot-de-passe-long")
    client.cookies.delete("sessionid")
    client.get(f"{BASE}/connexion")
    with caplog.at_level(logging.WARNING, logger="mika.console"):
        for _ in range(5):
            r = post(client, f"{BASE}/connexion", {"username": "adrien", "password": "faux"})
            assert r.status_code == 200 and "Identifiants invalides" in html_of(r)
            assert 'name="username" value="adrien"' in r.text and 'value="faux"' not in r.text
    assert sum("connexion refusée" in m for m in caplog.messages) == 5  # chaque échec est journalisé
    blocked = post(client, f"{BASE}/connexion", {"username": "adrien", "password": "un-mot-de-passe-long"},
                   follow_redirects=False)
    assert blocked.status_code == 429 and "Trop de tentatives" in html_of(blocked)
    assert 'name="username" value="adrien"' in blocked.text
    # contre-exemple : un autre identifiant depuis la même adresse n'est pas (encore) bloqué
    other = post(client, f"{BASE}/connexion", {"username": "quelquun", "password": "x"})
    assert other.status_code == 200


def _first_submit(form_html: str) -> str:
    """Le bouton par défaut d'un formulaire : son premier bouton d'envoi (``type`` absent ou « submit »)."""
    for m in re.finditer(r"<button\b([^>]*)>", form_html):
        attrs = m.group(1)
        if re.search(r'type="(button|reset)"', attrs):
            continue
        return attrs
    return ""


def test_enter_never_fires_a_secondary_or_destructive_button(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    # approuver : Entrée dans la note ne décide rien, « Approuver » se confirme
    opened = {"proposal": 3, "capability": "Envoyer un mail", "capability_key": "email.send", "summary": "Un mail",
              "context": "", "args": "{}", "when": "maintenant", "ago": "à l'instant", "event": "", "preview": "",
              "seen": "", "blocked": "", "position": 1, "total": 1, "previous": "", "next": "", "follow": "",
              "kind": "", "effect": True, "tab": ""}
    page = templates.get_template("handmade/approbations/attente.html").render(
        items=[{"proposal": 3, "capability": "Envoyer un mail", "context": "", "summary": "Un mail", "ago": "",
                "exact": "", "href": "?demande=3", "on": True}], opened=opened, total=1, shown=1, kinds=[],
        kind="", all_href="?", explicit=False, csrf="x", PREFIX=BASE, pending_pager=None)
    default = _first_submit(page)
    assert "disabled" in default and 'value="approve"' not in default
    assert re.search(r'value="approve" data-confirm="Approuver', page)
    # paramètres : Entrée enregistre, jamais « revenir au tempérament »
    body = f"{BASE}/reglages/comportement-body"
    post(client, body, {"_faculte": "body", "_champs": ["shift_minutes"], "shift_minutes": "45"})
    params = client.get(body).text
    form = re.search(r'<form method="post"[^>]*class="form params-form">(.*?)</form>', params, re.S).group(1)
    assert "_reinitialiser_chemin" not in _first_submit(form) and "revenir au tempérament" in params
    assert re.search(r'form="params-reset-body" name="_reinitialiser_chemin"', params)
    # un fournisseur : Entrée enregistre, jamais « charger la liste » (qui interroge le fournisseur)
    record = client.get(f"{BASE}/reglages/fournisseurs?enregistrement=backends&cle=&nouveau=1").text
    form = re.search(r'id="enregistrement">(.*?)</form>', record, re.S).group(1)
    assert "_charger" not in _first_submit(form) and "_charger" in form


# ── réglages ──────────────────────────────────────────────────────────────


def test_an_invented_time_zone_is_refused_and_could_not_break_the_console(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    doc = html_of(client.get(f"{BASE}/reglages/document"))
    text = re.search(r'<textarea id="yaml-personnage"[^>]*>(.*?)</textarea>', doc, re.S).group(1)
    bad = text.replace("timezone: Europe/Paris", "timezone: Pas/UnFuseau")
    assert bad != text
    refused = post(client, f"{BASE}/reglages/document", {"_section": "personnage", "_yaml": "1", "_texte": bad})
    said = html_of(refused)  # refusé par le document lui-même (ADR 0036) ou par les choix connus de la section
    assert refused.status_code == 400 and ("fuseau horaire inconnu" in said or "choix inconnu" in said)
    assert client.portal.call(live.persona).timezone == "Europe/Paris"
    form = post(client, f"{BASE}/reglages/identite", {"_section": "personnage", "_champs": ["timezone"],
                                                     "timezone": "Pas/UnFuseau"})
    said = html_of(form)
    assert form.status_code == 400 and ("fuseau horaire inconnu" in said or "choix inconnu" in said)
    # même s'il arrivait au journal (un ancien import), rien ne tombe : elle vit en UTC et la santé le dit
    assert _zone("Pas/UnFuseau").key == "UTC"
    kernel = live.kernel
    client.portal.call(kernel.set_params, "kernel", KernelParams(tz="Pas/UnFuseau"))
    report = client.portal.call(health.report, kernel)
    config = next(c for c in report.checks if c.name == "config")
    assert config.state == health.DEGRADED and "Pas/UnFuseau" in config.summary
    for url in (f"{BASE}/", f"{BASE}/decisions/episodes", f"{BASE}/systeme/sante", f"{BASE}/fil"):
        assert client.get(url).status_code == 200, url
    assert "Configuration lisible" in html_of(client.get(f"{BASE}/systeme/sante"))
    converse(client)  # la conversation aussi


def test_renaming_a_provider_keeps_its_roles_and_says_so(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    url = f"{BASE}/reglages/fournisseurs"
    client.get(url)

    def backend(name: str, old: str = "", **fields: str) -> dict:
        return {"_section": "modeles", "_enregistrement": "backends", "_ancienne": old, "_cle": name,
                "_champs": list(fields), **fields}

    post(client, url, backend("a", kind="ollama", model="gemma"))
    post(client, url, backend("b", kind="ollama", model="gemma"))
    post(client, f"{BASE}/reglages/roles", {"_section": "modeles", "_champs": ["routes"], "routes.reply": "a",
                                            "routes.murmur": "a"})
    renamed = post(client, url, backend("local", "a", kind="ollama", model="gemma"))
    page = html_of(renamed)
    assert renamed.status_code == 200 and "« a » s'appelle désormais « local »" in page
    assert "répondre (voix)" in page  # ce qui a suivi est nommé
    cfg = client.portal.call(live.settings.llm)
    assert set(cfg.backends) == {"local", "b"} and cfg.routes == {"reply": "local", "murmur": "local"}
    assert "fallback" not in cfg.backends["b"].model_dump()
    # un nom hors règle est refusé, rien ne change
    bad = post(client, url, backend("<b>x</b> / ? &", kind="ollama", model="gemma"))
    assert bad.status_code == 400 and "Nom refusé" in html_of(bad)
    assert set(client.portal.call(live.settings.llm).backends) == {"local", "b"}
    # retirer annonce ce qui le désignait
    listing = html_of(client.get(url))
    assert re.search(r"Retirer « local » \? Ce qui le désigne ne le pourra plus : [^\"]*répondre", listing)


def test_a_mailbox_keeps_its_name(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    url = f"{BASE}/reglages/boites"
    client.get(url)
    account = {"_section": "courrier", "_enregistrement": "accounts", "_ancienne": "", "_cle": "perso",
               "_champs": ["imap_host", "address"], "imap_host": "imap.exemple.org", "address": "moi@exemple.org"}
    assert post(client, url, account).status_code == 200
    moved = post(client, url, {**account, "_ancienne": "perso", "_cle": "pro"})
    assert moved.status_code == 400 and "ne change pas" in html_of(moved)
    assert set(client.portal.call(live.settings.of(MailSettings).email).accounts) == {"perso"}


def test_a_mailbox_loads_its_folders_to_tick_and_keeps_the_ticked_ones(world):  # noqa: F811
    """ADR 0171 : « Charger la liste » lit les dossiers de la boîte enregistrée, en cases à cocher ; ceux qu'on coche
    sont relevés, et « Synchroniser tous les dossiers » se coche à côté."""
    client, live, _ = world
    bootstrap(client)
    url = f"{BASE}/reglages/boites"
    client.get(url)
    account = {"_section": "courrier", "_enregistrement": "accounts", "_ancienne": "", "_cle": "perso",
               "_champs": ["imap_host", "user", "address", "folders", "sync_all"], "imap_host": "imap.exemple.org",
               "user": "moi", "address": "moi@exemple.org", "folders": "INBOX"}
    early = post(client, url, {**account, "_charger": "folders"})  # pas encore enregistrée : rien à lire
    assert early.status_code == 200 and "enregistre d'abord la boîte" in html_of(early)
    assert post(client, url, account).status_code == 200
    asked: list[str] = []

    held: list[bool] = []

    class Port:  # le serveur de la boîte, sans réseau
        def account(self, key):
            return object() if key == "perso" else None

        async def refresh_folders(self, key):
            asked.append(key)
            # charger n'enregistre rien : le verrou des réglages reste libre pendant que le serveur répond (sinon un
            # serveur lent tiendrait tous les réglages des autres)
            held.append(live.settings.writing.locked())
            return [Folder("perso", "INBOX", "inbox", True), Folder("perso", "Archives", "archive"),
                    Folder("perso", "Projets")]

    live.kernel.ports["mail"] = Port()
    page = html_of(client.get(f"{url}?enregistrement=accounts&cle=perso"))
    assert re.search(r'<button[^>]*name="_charger" value="folders"', page) and asked == []  # sur demande seulement
    loaded = html_of(post(client, url, {**account, "_ancienne": "perso", "_charger": "folders"}))
    assert asked == ["perso"] and "Rien n'est encore enregistré" in loaded and held == [False]
    # seul ce chargement-là se passe du verrou : une suppression qui porterait aussi « _charger » réécrit les
    # réglages, sous le verrou
    saving = live.settings.of(MailSettings).save_email
    under: list[bool] = []

    async def watched(cfg):
        under.append(live.settings.writing.locked())
        return await saving(cfg)

    live.settings.of(MailSettings).save_email = watched
    try:
        post(client, url, {"_section": "courrier", "_supprimer": "accounts", "_cle": "perso", "_charger": "folders"})
    finally:
        live.settings.of(MailSettings).save_email = saving
    assert under == [True] and "perso" not in client.portal.call(live.settings.of(MailSettings).email).accounts
    ticks = re.findall(r'<label class="check"><input type="checkbox" name="folders" value="([^"]+)"( checked)?[^>]*> '
                       r'([^<]+)</label>', loaded)
    assert ticks == [("INBOX", " checked", "Réception (INBOX)"), ("Archives", "", "Archives"),
                     ("Projets", "", "Projets")]
    saved = post(client, url, {**account, "_ancienne": "perso", "folders": ["INBOX", "Projets"], "sync_all": "on"})
    assert saved.status_code == 200
    got = client.portal.call(live.settings.of(MailSettings).email).accounts["perso"]
    assert got.folders == ("INBOX", "Projets") and got.sync_all


def test_settings_refuse_what_cannot_work(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    for page in ("transcription", "depots", "identite"):
        client.get(f"{BASE}/reglages/{page}")
    stt = post(client, f"{BASE}/reglages/transcription", {"_section": "transcription", "_champs": ["base_url"],
                                                        "base_url": "pas une url"})
    assert stt.status_code == 400 and "adresse http(s)" in html_of(stt)
    git = post(client, f"{BASE}/reglages/depots", {"_section": "depots", "_champs": ["hosts"],
                                                  "hosts": "https://github.com/\nexemple .org"})
    assert git.status_code == 400 and "n'est pas un hôte" in html_of(git)
    ok = post(client, f"{BASE}/reglages/depots", {"_section": "depots", "_champs": ["hosts"],
                                                 "hosts": "GitHub.com\ngit.exemple.org:8443"})
    assert ok.status_code == 200 and set(client.portal.call(live.settings.of(ProjectsSettings).git)["hosts"]) == {"github.com",
                                                                                          "git.exemple.org:8443"}
    unnamed = post(client, f"{BASE}/reglages/identite", {"_section": "personnage", "_champs": ["name"], "name": " "})
    assert unnamed.status_code == 400 and "nom ne peut pas être vide" in html_of(unnamed)


# ── vérité des listes et des badges ───────────────────────────────────────


def test_the_change_journal_loses_nothing_between_pages(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    kernel = live.kernel

    async def noise() -> None:
        # chaque tour : une modification depuis la console, beaucoup d'autres actions d'opérateur, et une
        # rejournalisation des paramètres — deux flux qui avancent à des rythmes très différents
        for i in range(40):
            await operations.audit(kernel, f"console.reglages.essai{i}", by="user_1", subject=str(i))
            for j in range(15):
                await operations.audit(kernel, f"autre.chose{i}_{j}", by="user_1")
            await kernel.set_params("kernel", KernelParams(tz="UTC" if i % 2 else "Europe/Paris"))

    client.portal.call(noise)
    seen: list[str] = []
    url = f"{BASE}/reglages/journal"
    for _ in range(20):
        page = client.get(url).text
        seen += sorted(set(re.findall(r"(essai\d+)", page)))  # chacun une fois par page (libellé et survol)
        nxt = re.search(r'<a href="([^"]+)" rel="next">', page)
        if not nxt:
            break
        url = f"{BASE}/reglages/journal" + html.unescape(nxt.group(1))
    assert sorted(seen) == sorted(f"essai{i}" for i in range(40))  # chacune une fois, aucune perdue


def test_operator_actions_are_not_presented_as_episodes(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    client.portal.call(lambda: operations.audit(live.kernel, "console.reglages.essai", by="user_1"))
    op = client.portal.call(lambda: live.kernel.mind.store.latest([rt.OPERATED.name], 1))[0]
    timeline = html_of(client.get(f"{BASE}/systeme/chronologie"))
    # un geste audité, fait depuis la console ou depuis l'espace d'une personne (C8-R1) : sa clé de corrélation
    # « opérateur:… » ne change pas
    assert op.correlation.startswith("opérateur:")
    assert f"/admin/episode/{op.correlation}" not in timeline and "un geste audité" in timeline
    assert "Geste audité : " in timeline and "action d'opérateur" not in timeline.lower()
    gone = client.get(f"{BASE}/episode/{op.correlation}", follow_redirects=False)
    assert gone.status_code == 303 and "/systeme/chronologie?correlation=" in gone.headers["location"]
    assert "Un épisode" not in html_of(client.get(f"{BASE}/episode/{op.correlation}"))


def test_a_failed_delivery_can_be_retried_or_marked_seen(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    converse(client)
    store = live.kernel.mind.store
    key = client.portal.call(lambda: store.query_mind("SELECT `key` FROM outbox ORDER BY seq DESC LIMIT 1"))[0][0]
    client.portal.call(store.mark_outbox, key, "failed", "TimeoutError()")
    sorties = html_of(client.get(f"{BASE}/systeme/sorties"))
    assert "Marquer comme vu" in sorties and "délai dépassé" in sorties and "TimeoutError" not in sorties
    assert re.search(r'<span class="count"[^>]*>1</span>', client.get(f"{BASE}/systeme/sorties").text)
    seen = post(client, f"{BASE}/systeme/sorties", {"cle": key, "faire": "vu"})
    assert seen.status_code == 200 and "Marqué comme vu" in html_of(seen)
    assert client.portal.call(lambda: store.outbox_status(key)) == "seen"
    page = client.get(f"{BASE}/systeme/sorties").text
    assert "Marquer comme vu" not in page  # le badge et la carte s'éteignent
    again = post(client, f"{BASE}/systeme/sorties", {"cle": key, "faire": "relancer"})
    assert "Rien à faire" in html_of(again)  # contre-exemple : on ne relance pas ce qui n'est pas en échec
    client.portal.call(store.mark_outbox, key, "failed", "boom")
    retried = post(client, f"{BASE}/systeme/sorties", {"cle": key, "faire": "relancer"})
    assert "Relancé" in html_of(retried)
    assert client.portal.call(lambda: store.outbox_status(key)) in ("pending", "done", "failed")
    audit = client.portal.call(lambda: store.latest([rt.OPERATED.name], 5))
    assert any("console.sorties" in a.data for a in audit)


def test_stale_and_interrupted_effects_are_named_filtered_and_to_handle(world):  # noqa: F811
    """Une réponse devenue « stale » (transport coupé plus de dix minutes) n'est jamais dite, ni par une
    réponse ni par « désolée » ; une commande réseau « interrupted » non plus. La console les montrait en anglais,
    refusait leur filtre (« État inconnu ») et n'allumait rien dans « À traiter »."""
    client, live, _ = world
    bootstrap(client)
    converse(client)
    with client.websocket_connect(WS) as ws:  # un second échange (un autre identifiant : pas dédoublonné)
        ws.receive_json(), ws.receive_json()
        ws.send_json({"type": "chat", "message": "et demain, tu fais quoi ?", "client_msg_id": "o2"})
        recv_until(ws, "speech")
    store = live.kernel.mind.store
    keys = [k for (k,) in client.portal.call(lambda: store.query_mind("SELECT `key` FROM outbox ORDER BY seq"))]
    assert len(keys) >= 2
    client.portal.call(store.mark_outbox, keys[-1], "stale", "trop tard : elle ne le dit plus")
    client.portal.call(store.mark_outbox, keys[-2], "interrupted", "délai dépassé : coupée au bout de 900 s")
    page = html_of(client.get(f"{BASE}/systeme/sorties"))
    assert "Périmé (pas dit)" in page and "Interrompu (à vérifier)" in page
    assert "Stale" not in page and "Interrupted" not in page
    assert re.search(r'<span class="count"[^>]*>2</span>', client.get(f"{BASE}/systeme/sorties").text)  # « à traiter »
    assert "Marquer comme vu" in page and ">Relancer</button>" not in page  # on ne relance pas une parole périmée
    filtered = html_of(client.get(f"{BASE}/systeme/sorties?etat=stale"))
    assert "État inconnu" not in filtered and "périmé (pas dit)" in filtered
    assert "État inconnu" in html_of(client.get(f"{BASE}/systeme/sorties?etat=inexistant"))  # contre-exemple
    refused = post(client, f"{BASE}/systeme/sorties", {"cle": keys[-1], "faire": "relancer"})
    assert "Pas relancé" in html_of(refused)
    assert client.portal.call(lambda: store.outbox_status(keys[-1])) == "stale"
    seen = post(client, f"{BASE}/systeme/sorties", {"cle": keys[-1], "faire": "vu"})
    assert "Marqué comme vu" in html_of(seen)
    assert client.portal.call(lambda: store.outbox_status(keys[-1])) == "seen"


def test_giant_cursors_never_break_a_page(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    huge = "99999999999999999999999"
    for url in (f"{BASE}/?avant={huge}", f"{BASE}/systeme/chronologie?avant={huge}", f"{BASE}/evenement/{huge}",
                f"{BASE}/decisions/selections?avant={huge}", f"{BASE}/systeme/operations?avant={huge}",
                f"{BASE}/reglages/journal?avant={huge}", f"{BASE}/systeme/appels?page={huge}",
                f"{BASE}/fiche/person/user_1?onglet=echanges&avant={huge}", f"{BASE}/fil/conversations?page={huge}",
                f"{BASE}/approbations/historique?avant=-4"):
        assert client.get(url).status_code < 500, url


def test_outbox_action_cards_follow_filter_and_paginate_without_deciding(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    with client.websocket_connect(WS) as ws:
        ws.receive_json(), ws.receive_json()
        for i in range(10):
            ws.send_json({'type': 'chat', 'message': f'message de test {i}', 'client_msg_id': f'outbox-page-{i}'})
            recv_until(ws, 'speech')
    store = live.kernel.mind.store
    keys = [k for (k,) in client.portal.call(lambda: store.query_mind('SELECT `key` FROM outbox ORDER BY seq DESC LIMIT 10'))]
    assert len(keys) == 10
    for key in keys[:9]:
        client.portal.call(store.mark_outbox, key, 'failed', 'échec fictif')
    client.portal.call(store.mark_outbox, keys[9], 'interrupted', 'arrêt fictif')
    first = html_of(client.get(f'{BASE}/systeme/sorties?etat=failed'))
    second = html_of(client.get(f'{BASE}/systeme/sorties?etat=failed&page_problemes=2'))
    for body in (first, second):
        ConsoleHTML(body).check()
        assert body.index('outbox-review') < body.index('id="out-recent"')  # à traiter, puis les derniers départs
    def shown(body):
        return set(re.findall(r'name="cle" value="([^\"]+)"', body))
    assert len(shown(first)) == 8 and len(shown(second)) == 1
    assert shown(first) | shown(second) == set(keys[:9])
    assert not shown(first) & shown(second)
    interrupted = html_of(client.get(f'{BASE}/systeme/sorties?etat=interrupted'))
    assert shown(interrupted) == {keys[9]} and '>Relancer</button>' not in interrupted
    assert 'peut-être déjà eu lieu' in interrupted
    done = html_of(client.get(f'{BASE}/systeme/sorties?etat=done'))
    assert not shown(done)
    assert all(client.portal.call(store.outbox_status, key) == 'failed' for key in keys[:9])


def test_the_drawn_outbox_and_its_table_show_the_same_page_of_departures(world):  # noqa: F811
    """La page dessinée de la File de sortie lit la page de départs de sa vue, sans la relire à côté (ADR 0177) : la
    même taille de page que sa vue en tableau (et que la console en MCP), le même total. Avant, la vue en montrait
    50 et la page dessinée 20, chacune de ses propres requêtes."""
    client, live, _ = world
    bootstrap(client)
    converse(client)
    store, seq = live.kernel.mind.store, live.kernel.mind.head
    client.portal.call(store.run_mind, lambda sql: sql.execute(insert(JournalOutbox), [
        {"key": f"essai:{i}", "seq": seq, "effect": "expression:episode.utterance", "status": "done", "attempts": 1,
         "last_error": None} for i in range(OUTBOX_PAGE + 5)]))
    total = client.portal.call(lambda: store.query_mind(select(func.count()).select_from(JournalOutbox)))[0][0]
    assert total > OUTBOX_PAGE
    drawn = html_of(client.get(f"{BASE}/systeme/sorties"))
    table = html_of(client.get(f"{BASE}/systeme/sorties?vue_pg1=table"))
    assert 'data-tab="systeme/sorties"' in drawn and 'data-tab="systeme/sorties"' not in table  # le repli
    ConsoleHTML(drawn).check()
    ConsoleHTML(table).check()
    assert drawn.count('class="sys-out-ev"') == OUTBOX_PAGE
    assert f"1–{OUTBOX_PAGE} sur {total}" in drawn and f"1–{OUTBOX_PAGE} sur {total}" in table
    second = html_of(client.get(f"{BASE}/systeme/sorties?page=2"))
    assert second.count('class="sys-out-ev"') == min(OUTBOX_PAGE, total - OUTBOX_PAGE)


def _card(page: str, key: str) -> str:
    """La carte « À traiter » d'une ligne de la file (par sa clé), dans une page."""
    cards = [c for c in re.findall(r'<li class="st-[a-z]*">(.*?)</li>', page, re.S) if f'value="{key}"' in c]
    assert len(cards) == 1, key
    return cards[0]


def test_a_departure_to_handle_says_what_did_not_leave_and_to_whom(world):  # noqa: F811
    """Avant de relancer un départ ou de le marquer comme vu, l'opératrice devait ouvrir son événement pour savoir à
    qui la parole n'était pas partie : la carte disait « Ses messages » et « L'action a échoué » pour une parole
    (audit du 2026-11-05, C8-06). Chaque carte dit maintenant ce qui n'est pas parti (une parole : à qui et le début de
    son texte, sur une ligne ; une action : l'action et son résumé, celui de sa proposition pour une action autorisée)
    et que faire selon sa sorte — dessinée comme au repli."""
    client, live, _ = world
    bootstrap(client)
    converse(client)
    long = "Je voulais te dire que " + "la pluie tombe encore sur les toits de la ville, " * 6 + "et je pense à toi."
    voice = VoiceProvenance(call_id="coince#0", persona_hash="fictive", role="reply", model="fake")

    async def seed():
        said = await live.kernel.mind.append([rt.UTTERANCE.draft(
            kind="REPLY", target="user_1", voice=voice, text=Content.of(long))],
            emitter="runtime", origin=Origin.GENESIS, correlation="parole-coincee")
        asked = await live.kernel.mind.append([rt.EFFECT_PROPOSED.draft(
            capability="email.send", owner="email", args_json="{}", summary=Content.of("Écrire à Léa pour samedi."))],
            emitter="runtime", origin=Origin.PROCESS, correlation="action-coincee")
        refused = await live.kernel.mind.append([rt.EFFECT_RESOLVED.draft(
            proposal=asked.seqs[0], approved=False, capability="email.send", owner="email")],
            emitter="runtime", origin=Origin.PROCESS, correlation="action-coincee")
        return said.seqs[0], asked.seqs[0], refused.seqs[0]

    said, asked, refused = client.portal.call(seed)
    store = live.kernel.mind.store
    client.portal.call(store.run_mind, lambda sql: sql.execute(insert(JournalOutbox), [
        {"key": "essai:parole", "seq": said, "effect": "expression:episode.utterance", "status": "failed",
         "attempts": 8, "last_error": "TimeoutError()"},
        {"key": "essai:perimee", "seq": said, "effect": "expression:episode.utterance", "status": "stale",
         "attempts": 1, "last_error": "trop tard : elle ne le dit plus"},
        {"key": "essai:action", "seq": asked, "effect": "runtime:effect.proposed", "status": "failed",
         "attempts": 8, "last_error": "boom"},
        {"key": "essai:autorisee", "seq": refused, "effect": "runtime:effect.resolved", "status": "failed",
         "attempts": 8, "last_error": "boom"}]))
    drawn = html_of(client.get(f"{BASE}/systeme/sorties"))
    folded = html_of(client.get(f"{BASE}/systeme/sorties?vue_pg1=table"))
    assert 'data-tab="systeme/sorties"' in drawn and 'data-tab="systeme/sorties"' not in folded
    for page in (drawn, folded):
        ConsoleHTML(page).check()
        speech = _card(page, "essai:parole")
        assert "Ses messages" in speech and "à adrien" in speech  # à qui, par son nom
        assert "« Je voulais te dire que la pluie tombe encore" in speech and "…" in speech and long not in speech
        assert "Ce message n'est pas parti. Tu peux le relancer ou le marquer comme vu." in speech
        assert "action a échoué" not in speech and "délai dépassé" in speech
        stale = _card(page, "essai:perimee")
        assert "Ce message est périmé : elle ne le dira plus." in stale and ">Relancer</button>" not in stale
        action = _card(page, "essai:action")
        assert "Une action, tout de suite : Envoyer un mail" in action and "Écrire à Léa pour samedi." in action
        assert "L'action a échoué. Tu peux la relancer ou la marquer comme vue." in action and "à adrien" not in action
        # une action autorisée (ici refusée, pour qu'elle ne parte pas) : le résumé de sa proposition
        resolved = _card(page, "essai:autorisee")
        assert "Une action que tu as autorisée : Envoyer un mail" in resolved
        assert "Écrire à Léa pour samedi." in resolved
    # la vue le dit aussi en tableau (la console en MCP) : à qui, quoi
    table = folded[folded.index("À traiter, ligne par ligne"):]
    assert "<th" in table and "à qui" in table and "« Je voulais te dire que" in table
    # la parole y est déjà coupée sur une ligne (guillemets en plus) : sa cellule ne se replie pas en « lire la suite »,
    # qui n'aurait révélé que la fin « … »
    rows = table[:table.index("</table>")]
    assert "… »" in rows and '<details class="more">' not in rows and "lire la suite" not in rows
