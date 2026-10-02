"""La console au service de l'opérateur (ADR 0042) : ce qu'il vit, page par page.

- « Pourquoi a-t-elle dit ça ? » : une page par parole, liée depuis le fil ;
- des noms plutôt que des clés, un filtre « vers » qui comprend un nom, un oubli
  qui se confirme en retapant le nom affiché ;
- une connexion qui ne se laisse pas deviner, une touche Entrée qui ne décide
  jamais d'un bouton secondaire ;
- des réglages qui refusent ce qui mettrait tout en panne (un fuseau inventé),
  qui renomment sans rien perdre, qui ne joignent un fournisseur que sur demande ;
- des listes qui ne perdent rien entre deux pages, ne mentent pas sur leur total,
  et des badges qu'on peut éteindre.
"""

from __future__ import annotations

import html
import logging
import re

from mika.contracts import runtime as rt
from mika.inspector.ui import env as templates
from mika.kernel.builtin import KernelParams
from mika.kernel.registry import _zone
from mika.runtime import health, operations
from tests.fixtures.console_html import ConsoleHTML
from tests.protocol.test_web import WS, bootstrap, recv_until, world  # noqa: F401 — fixture partagée

BASE = "/inspecteur"
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
    thread = client.get(f"{BASE}/fil/messages").text
    links = re.findall(r'data-href="(/inspecteur/parole/(\d+))"', thread)
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
    # le même lien depuis l'épisode, et depuis l'événement de la parole
    utterance = client.portal.call(lambda: live.kernel.mind.store.get_events([int(seq)]))[0]
    said = client.get(f"{BASE}/episode/{utterance.correlation}?onglet=dit").text
    assert f"/inspecteur/parole/{seq}" in said
    assert f"/inspecteur/parole/{seq}" in client.get(f"{BASE}/evenement/{seq}").text
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
    # son « pourquoi »
    fiche = client.get(f"{BASE}/fiche/person/user_1").text
    link = re.search(r'href="(/inspecteur/decisions/envers\?personne=[^"]+)"', fiche)
    assert link and "Envers adrien" in html_of(client.get(html.unescape(link.group(1))))
    assert re.search(r'data-href="/inspecteur/parole/\d+"',
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
    assert sum("connexion refusée" in m for m in caplog.messages) == 5  # chaque échec est journalisé
    blocked = post(client, f"{BASE}/connexion", {"username": "adrien", "password": "un-mot-de-passe-long"},
                   follow_redirects=False)
    assert blocked.status_code == 429 and "Trop de tentatives" in html_of(blocked)
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
    page = templates.get_template("approvals.html").render(
        items=[{"proposal": 3, "capability": "Envoyer un mail", "capability_key": "email.send", "summary": "Un mail",
                "context": "", "args": "{}", "when": "maintenant", "preview": "", "seen": "", "blocked": ""}],
        csrf="x", PREFIX=BASE, pending_pager=None)
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
    for url in (f"{BASE}/", f"{BASE}/decisions/episodes", f"{BASE}/systeme/sante", f"{BASE}/fil/messages"):
        assert client.get(url).status_code == 200, url
    assert "configuration lisible" in html_of(client.get(f"{BASE}/systeme/sante"))
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
    post(client, url, backend("b", kind="ollama", model="gemma", fallback="a"))
    post(client, f"{BASE}/reglages/roles", {"_section": "modeles", "_champs": ["routes"], "routes.reply": "a",
                                            "routes.murmur": "a"})
    renamed = post(client, url, backend("local", "a", kind="ollama", model="gemma"))
    page = html_of(renamed)
    assert renamed.status_code == 200 and "« a » s'appelle désormais « local »" in page
    assert "répondre (voix)" in page and "Repli" in page  # ce qui a suivi est nommé
    cfg = client.portal.call(live.settings.llm)
    assert set(cfg.backends) == {"local", "b"} and cfg.routes == {"reply": "local", "murmur": "local"}
    assert cfg.backends["b"].fallback == "local"
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
    assert set(client.portal.call(live.settings.email).accounts) == {"perso"}


def test_settings_refuse_what_cannot_work(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    for page in ("transcription", "depots", "identite", "telegram"):
        client.get(f"{BASE}/reglages/{page}")
    stt = post(client, f"{BASE}/reglages/transcription", {"_section": "transcription", "_champs": ["base_url"],
                                                        "base_url": "pas une url"})
    assert stt.status_code == 400 and "adresse http(s)" in html_of(stt)
    git = post(client, f"{BASE}/reglages/depots", {"_section": "depots", "_champs": ["hosts"],
                                                  "hosts": "https://github.com/\nexemple .org"})
    assert git.status_code == 400 and "n'est pas un hôte" in html_of(git)
    ok = post(client, f"{BASE}/reglages/depots", {"_section": "depots", "_champs": ["hosts"],
                                                 "hosts": "GitHub.com\ngit.exemple.org:8443"})
    assert ok.status_code == 200 and set(client.portal.call(live.settings.git)["hosts"]) == {"github.com",
                                                                                          "git.exemple.org:8443"}
    unnamed = post(client, f"{BASE}/reglages/identite", {"_section": "personnage", "_champs": ["name"], "name": " "})
    assert unnamed.status_code == 400 and "nom ne peut pas être vide" in html_of(unnamed)
    open_, shut = "N'importe qui trouvant le robot", "ne répond à personne"
    page = html_of(client.get(f"{BASE}/reglages/telegram"))
    assert open_ not in page and shut not in page  # pas de robot : rien à dire
    # sans liste ni propriétaires, le robot est fermé (ADR 0038) : on le dit, sans crier « ouvert »
    client.portal.call(lambda: live.settings.save_telegram(token="123:abc", allowed_chats=[], owners=[]))
    page = html_of(client.get(f"{BASE}/reglages/telegram"))
    assert shut in page and open_ not in page
    client.portal.call(lambda: live.settings.save_telegram(token="123:abc", open_to_all=True))
    assert open_ in html_of(client.get(f"{BASE}/reglages/telegram"))
    client.portal.call(lambda: live.settings.save_telegram(token="123:abc", allowed_chats=[42], owners=[],
                                                           open_to_all=False))
    page = html_of(client.get(f"{BASE}/reglages/telegram"))
    assert open_ not in page and shut not in page


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
    assert f"/inspecteur/episode/{op.correlation}" not in timeline and "une action d'opérateur" in timeline
    gone = client.get(f"{BASE}/episode/{op.correlation}", follow_redirects=False)
    assert gone.status_code == 303 and "/systeme/chronologie?correlation=" in gone.headers["location"]
    assert "Un épisode" not in html_of(client.get(f"{BASE}/episode/{op.correlation}"))


def test_a_failed_delivery_can_be_retried_or_marked_seen(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    converse(client)
    store = live.kernel.mind.store
    key = client.portal.call(lambda: store.query_mind("SELECT key FROM outbox ORDER BY seq DESC LIMIT 1"))[0][0]
    client.portal.call(store.mark_outbox, key, "failed", "TimeoutError()")
    sorties = html_of(client.get(f"{BASE}/systeme/sorties"))
    assert "Marquer comme vu" in sorties and "délai dépassé" in sorties and "TimeoutError" not in sorties
    assert '<span class="count">1</span>' in client.get(f"{BASE}/systeme/sorties").text
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


def test_giant_cursors_never_break_a_page(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    huge = "99999999999999999999999"
    for url in (f"{BASE}/?avant={huge}", f"{BASE}/systeme/chronologie?avant={huge}", f"{BASE}/evenement/{huge}",
                f"{BASE}/decisions/selections?avant={huge}", f"{BASE}/systeme/operations?avant={huge}",
                f"{BASE}/reglages/journal?avant={huge}", f"{BASE}/systeme/appels?page={huge}",
                f"{BASE}/fil/messages?avant={huge}", f"{BASE}/approbations/historique?avant=-4"):
        assert client.get(url).status_code < 500, url
