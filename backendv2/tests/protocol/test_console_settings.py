"""Les réglages déclarés : chaque section se découpe en sous-pages rangées dans un
sous-menu (jamais toute une section d'un coup), se rend depuis son modèle,
s'enregistre par un formulaire protégé, refuse champ par champ, ne réaffiche
jamais un secret, ne montre un champ que s'il sert, propose un sélecteur quand
les choix sont limités, et laisse une trace dans le journal des modifications.

Canari : des secrets connus sont posés, puis cherchés dans chaque page de la
console et dans le journal — ils n'y sont jamais.
"""

from __future__ import annotations

import html
import re

from mika.app.console import NAVIGATION
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

CANARY_KEY = "sk-ant-api-CANARI-7f3e"
CANARY_MAIL = "mot-de-passe-CANARI"
CANARY_STT = "sk-CANARI-whisper"
BASE = "/inspecteur/reglages"


def html_of(r) -> str:
    return html.unescape(r.text)


def post(client, path: str, data: dict) -> object:
    return client.post(path, data={"csrf": client.cookies.get("csrftoken"), **data})


def backend(name: str, **fields: str) -> dict:
    return {"_section": "modeles", "_enregistrement": "backends", "_ancienne": "", "_cle": name,
            "_champs": list(fields), **fields}


def links(page: str, prefix: str) -> set[str]:
    return set(re.findall(rf'href="({re.escape(prefix)}/[\w-]+)"', page))


def test_models_are_records_with_sealed_keys_roles_and_a_loader_that_degrades(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    url = f"{BASE}/fournisseurs"
    page = html_of(client.get(url))
    # une sous-page par sujet : les fournisseurs ici, les rôles et le contexte chacun sur la leur
    assert "Fournisseurs" in page and "répondre (voix)" not in page and "Contexte (jetons)" not in page
    assert {f"{BASE}/roles", f"{BASE}/contexte", f"{BASE}/identite", f"{BASE}/comptes"} <= links(page, BASE)
    r = post(client, url, backend("claude", kind="claude", model="claude-sonnet-5", api_key=CANARY_KEY))
    assert r.status_code == 200 and "« claude » enregistré" in html_of(r)
    assert CANARY_KEY not in r.text and "défini" in html_of(r)
    # une borne dépassée : refus au champ, rien n'est gardé
    bad = post(client, url, {**backend("claude", slots="99"), "_ancienne": "claude"})
    assert bad.status_code == 400 and "doit être entre 0 et 32" in html_of(bad)
    # modifier sans retaper la clé la garde ; un nom déjà pris est refusé
    kept = post(client, url, {**backend("claude", model="claude-opus-5", temperature="0,4"), "_ancienne": "claude"})
    assert kept.status_code == 200
    cfg = client.portal.call(live.settings.llm)
    assert cfg.backends["claude"].api_key == CANARY_KEY and cfg.backends["claude"].model == "claude-opus-5"
    assert cfg.backends["claude"].temperature == 0.4
    post(client, url, backend("local", kind="ollama", model="gemma", host="http://127.0.0.1:9"))
    taken = post(client, url, {**backend("claude", kind="ollama", model="x"), "_ancienne": "local"})
    assert taken.status_code == 400 and "Ce nom existe déjà" in html_of(taken)
    # la page d'un fournisseur : le repli est un sélecteur parmi les autres, la clé ne se montre que si elle sert,
    # et la liste des modèles se charge d'elle-même (injoignable : un message, pas une erreur)
    edit = html_of(client.get(f"{url}?enregistrement=backends&cle=local"))
    assert re.search(r'<select name="fallback"[^>]*>.*?<option value="claude"', edit, re.S)
    assert 'value="local"' not in re.search(r'<select name="fallback".*?</select>', edit, re.S).group(0)
    assert 'data-only="kind=claude|openai|ollama_cloud||kind=claude_code;auth=cle_api"' in edit
    assert "Liste indisponible" in edit and "Options avancées" in edit
    # les rôles : une correspondance rôle → fournisseur ; un choix hors liste est refusé ; ce qui sert vraiment
    roles = f"{BASE}/roles"
    routed = post(client, roles, {"_section": "modeles", "_champs": ["routes"], "routes.reply": "claude",
                                  "routes.extract": "local"})
    assert routed.status_code == 200 and "Qui sert quoi : enregistré" in html_of(routed)
    assert "Ce qui sert vraiment chaque rôle" in html_of(routed) and "par repli" in html_of(routed)
    unknown = post(client, roles, {"_section": "modeles", "_champs": ["routes"], "routes.reply": "fantome"})
    assert unknown.status_code == 400 and "choix inconnu" in html_of(unknown)
    ctx = post(client, f"{BASE}/contexte", {"_section": "modeles", "_champs": ["context_tokens"],
                                            "context_tokens": "32 000"})
    assert ctx.status_code == 200 and "Contexte : enregistré" in html_of(ctx)
    cfg = client.portal.call(live.settings.llm)
    assert cfg.routes == {"reply": "claude", "extract": "local"} and cfg.context_tokens == 32_000
    # retirer un fournisseur emporte les rôles qui le visaient
    gone = post(client, url, {"_section": "modeles", "_supprimer": "backends", "_cle": "local"})
    assert "« local » retiré" in html_of(gone)
    assert client.portal.call(live.settings.llm).routes == {"reply": "claude"}
    # les anciennes adresses mènent aux nouvelles pages
    moved = client.get(f"{BASE}/modeles?enregistrement=backends&cle=claude", follow_redirects=False)
    assert moved.status_code == 301 and moved.headers["location"].startswith(f"{BASE}/fournisseurs?")


def test_persona_pages_yaml_import_and_back_to_the_file(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    identite = html_of(client.get(f"{BASE}/identite"))
    assert "Nom" in identite and "Traits" not in identite  # un sujet par page
    assert re.search(r'<select name="timezone"[^>]*>.*?<option value="Europe/Paris" selected', identite, re.S)
    assert "Ce que pilote chaque curseur" in html_of(client.get(f"{BASE}/temperament"))
    kernel = live.kernel

    def revisions() -> int:
        return len(client.portal.call(lambda: kernel.mind.store.latest([self_c.PERSONA_REVISED.name], 50)))

    before = revisions()
    saved = post(client, f"{BASE}/identite", {"_section": "personnage", "_champs": ["name"], "name": "Mikaela"})
    assert saved.status_code == 200 and "Identité : enregistré" in html_of(saved)
    traits = post(client, f"{BASE}/caractere", {"_section": "personnage", "_champs": ["traits"],
                                               "traits": "Curieuse de tout, pas juste de tech\nDrôle"})
    assert traits.status_code == 200 and "Caractère : enregistré" in html_of(traits)
    doc = client.portal.call(lambda: kernel.mind.frame().get(self_c.PERSONA))
    assert doc.name == "Mikaela" and doc.traits == ("Curieuse de tout, pas juste de tech", "Drôle")
    assert revisions() == before + 2
    document = f"{BASE}/document"
    assert "Révisions de sa persona" in html_of(client.get(document))
    unknown = post(client, document, {"_section": "personnage", "_yaml": "1", "_texte": "name: Mika\ncouleur: bleue\n"})
    assert unknown.status_code == 400 and "champ inconnu" in html_of(unknown) and revisions() == before + 2
    broken = post(client, document, {"_section": "personnage", "_yaml": "1", "_texte": "name: [Mika\n"})
    assert broken.status_code == 400 and "YAML illisible" in html_of(broken)
    back = post(client, document, {"_section": "personnage", "_commande": "fichier"})
    assert "Retour au fichier" in html_of(back)
    assert client.portal.call(lambda: kernel.mind.frame().get(self_c.PERSONA)).name == "Mika"


def test_temperament_sliders_rederive_the_parameters(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    url = f"{BASE}/temperament"
    client.get(url)
    kernel = live.kernel

    def needs():
        return client.portal.call(lambda: kernel.mind.frame().env.params_of("needs", kernel.mind.root))

    before = needs().tau_social_h
    fields = ["reactivity", "resilience", "contagion", "optimism", "sociability", "curiosity", "perseverance",
              "chronotype", "background"]
    r = post(client, url, {"_section": "temperament", "_champs": fields, **{k: "0.5" for k in fields},
                           "sociability": "0,9", "background": "curious"})
    assert r.status_code == 200 and "Tempérament : enregistré" in html_of(r)
    assert needs().tau_social_h < before  # plus sociable : le besoin de compagnie revient plus vite
    doc = client.portal.call(lambda: kernel.mind.frame().get(self_c.PERSONA))
    assert doc.temperament.sociability == 0.9 and doc.temperament.background.value == "curious"
    out = post(client, url, {"_section": "temperament", "_champs": fields, **{k: "0.5" for k in fields},
                             "background": "curious", "reactivity": "1,5"})
    assert out.status_code == 400 and "doit être entre 0 et 1" in html_of(out)


def test_telegram_owners_are_an_input_that_survives_reconfiguration(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    url = f"{BASE}/telegram"
    client.get(url)
    bad = post(client, url, {"_section": "telegram", "_champs": ["owners"], "owners": "12\nabc"})
    assert bad.status_code == 400 and "doit être un nombre entier" in html_of(bad)
    ok = post(client, url, {"_section": "telegram", "_champs": ["allowed_chats", "owners"],
                            "allowed_chats": "", "owners": "12\n34"})
    assert ok.status_code == 200 and "Telegram : enregistré" in html_of(ok)
    assert client.portal.call(live.settings.telegram)["owners"] == [12, 34]
    kernel = live.kernel

    def owners():
        return client.portal.call(lambda: kernel.mind.frame().env.params_of("identity", kernel.mind.root)).owners

    assert owners() == ("tg_12", "tg_34")
    client.portal.call(live.reconfigure)  # un changement de persona ne les efface pas
    assert owners() == ("tg_12", "tg_34")
    params = html_of(client.get(f"{BASE}/comportement-identity"))
    assert "réglage" in params


def test_senses_mail_feeds_transcription_and_a_device_token_shown_once(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    url = f"{BASE}/boites"
    client.get(url)
    account = {"_section": "courrier", "_enregistrement": "accounts", "_ancienne": "", "_cle": "perso",
               "_champs": ["address", "imap_host", "user", "password", "imap_port", "voice", "tone"],
               "address": "mika@exemple.fr", "imap_host": "imap.exemple.fr", "user": "mika",
               "password": CANARY_MAIL, "imap_port": "993", "voice": "proprietaire", "tone": "sobre",
               "_retour": "/inspecteur/courrier/comptes"}
    mail = post(client, url, account)
    assert mail.status_code == 200 and CANARY_MAIL not in mail.text
    assert "/inspecteur/reglages/boites" in str(mail.url)  # ancien onglet redirigé vers la configuration
    saved = client.portal.call(live.settings.email).accounts["perso"]
    assert saved.password == CANARY_MAIL and saved.voice == "proprietaire" and saved.tone == "sobre"
    # modifier sans retaper le mot de passe le garde ; un retour hors de la console est ignoré
    again = post(client, url, {**account, "_ancienne": "perso", "password": "", "tone": "chaleureux",
                               "_retour": "https://ailleurs.example/"})
    assert again.status_code == 200 and "ailleurs.example" not in str(again.url)
    saved = client.portal.call(live.settings.email).accounts["perso"]
    assert saved.password == CANARY_MAIL and saved.tone == "chaleureux"
    assert CANARY_MAIL not in html_of(client.get("/inspecteur/courrier/comptes"))
    assert CANARY_MAIL not in html_of(client.get("/inspecteur/fiche/compte/perso"))
    bad = post(client, url, {**account, "_cle": "Mon Compte"})
    assert bad.status_code == 400 and "nom de compte invalide" in html_of(bad)
    feeds = f"{BASE}/flux"
    refused = post(client, feeds, {"_section": "flux", "_champs": ["urls"], "urls": "https://a.fr/rss\nftp://b"})
    assert refused.status_code == 400 and "non http(s)" in html_of(refused)
    post(client, feeds, {"_section": "flux", "_champs": ["urls"], "urls": "https://a.fr/rss\nhttps://b.fr/atom"})
    assert client.portal.call(live.settings.feeds) == ["https://a.fr/rss", "https://b.fr/atom"]
    post(client, f"{BASE}/transcription", {"_section": "transcription", "_champs": ["api_key"],
                                           "api_key": CANARY_STT})
    assert client.portal.call(live.settings.stt)["api_key"] == CANARY_STT
    devices = f"{BASE}/appareils"
    shown = post(client, devices, {"_section": "appareils", "_commande": "jeton"})
    token = client.portal.call(live.settings.sensors_token)
    assert token and token in shown.text  # montré une fois…
    assert token not in client.get(devices).text  # … et plus jamais
    # un envoi sur la page d'une autre section est refusé
    wrong = post(client, feeds, {"_section": "transcription", "_champs": ["model"], "model": "x"})
    assert wrong.status_code == 400 and "Section inconnue" in html_of(wrong)


def test_internal_parameters_one_page_per_faculty_overrides_bounded_and_journaled(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    overview = html_of(client.get(f"{BASE}/comportement"))
    assert "Les facultés" in overview and "Ce que pilote chaque curseur" in overview
    assert f"{BASE}/comportement-body" in overview and "Corps et sommeil" in overview
    body_url = f"{BASE}/comportement-body"
    body = html_of(client.get(body_url))
    # un groupe à la fois (le corps en a cinq) : chaque paramètre dit sa provenance, ses bornes, son sens
    assert "shift_minutes" in body and "tempérament" in body and "Groupes" in body and "Sommeil" in body
    assert "sleep.tau_wake_h" not in body  # un autre groupe : une autre page
    assert "sleep.tau_wake_h" in html_of(client.get(f"{body_url}?groupe=sommeil"))
    # l'ancienne adresse redirige vers la page de la faculté
    moved = client.get(f"{BASE}/parametres?faculte=body", follow_redirects=False)
    assert moved.status_code == 301 and moved.headers["location"] == body_url
    nothing = post(client, body_url, {"_faculte": "body"})
    assert nothing.status_code == 200 and "Rien n'a changé" in html_of(nothing)
    refused = post(client, f"{BASE}/comportement", {"_faculte": "inconnue"})
    assert refused.status_code == 400 and "Faculté inconnue" in html_of(refused)
    over = post(client, body_url, {"_faculte": "body", "_champs": ["shift_minutes"], "shift_minutes": "45"})
    assert over.status_code == 200 and "surcharges enregistrées" in html_of(over)
    assert "revenir au tempérament" in html_of(over)
    kernel = live.kernel
    assert client.portal.call(lambda: kernel.mind.frame().env.params_of("body", kernel.mind.root)).shift_minutes == 45
    out = post(client, body_url, {"_faculte": "body", "_champs": ["shift_minutes"], "shift_minutes": "9999"})
    assert out.status_code == 400 and "doit être entre" in html_of(out)
    reset = post(client, body_url, {"_faculte": "body", "_reinitialiser_chemin": "shift_minutes"})
    assert reset.status_code == 200 and "surcharges enregistrées" in html_of(reset)
    assert client.portal.call(lambda: kernel.mind.frame().env.params_of("body", kernel.mind.root)).shift_minutes == 0


def test_every_settings_change_lands_in_the_configuration_journal_without_content(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    client.get(f"{BASE}/fournisseurs")
    post(client, f"{BASE}/fournisseurs", backend("claude", kind="claude", model="m", api_key=CANARY_KEY))
    post(client, f"{BASE}/transcription", {"_section": "transcription", "_champs": ["api_key"],
                                           "api_key": CANARY_STT})
    journal = html_of(client.get(f"{BASE}/journal"))
    assert "reglages.modeles" in journal and "reglages.transcription" in journal and "user_1" in journal
    ops = client.portal.call(lambda: live.kernel.mind.store.latest([rt.OPERATED.name], 50))
    raw = " ".join(o.data for o in ops)
    assert CANARY_KEY not in raw and CANARY_STT not in raw
    # canari : aucun secret dans aucune page de la console (chaque destination, chaque sous-page)
    urls: set[str] = set()
    for group in NAVIGATION:
        for d in group.items:
            base = "/inspecteur/" if d.key == "accueil" else f"/inspecteur/{d.key}"
            urls.add(base)
            first = client.get(base, follow_redirects=True)
            urls |= links(html_of(first), f"/inspecteur/{d.key}")
    urls |= {f"{BASE}/fournisseurs?enregistrement=backends&cle=claude", f"{BASE}/comportement-identity",
             "/inspecteur/systeme/operations"}
    assert f"{BASE}/transcription" in urls and "/inspecteur/systeme/sorties" in urls
    for u in sorted(urls):
        r = client.get(u, follow_redirects=True)
        assert r.status_code == 200, u
        for canary in (CANARY_KEY, CANARY_STT):
            assert canary not in r.text, (u, canary)
    stored = client.portal.call(live.kernel.mind.store.query_mind, "SELECT value FROM settings")
    assert all(CANARY_KEY not in row[0] and CANARY_STT not in row[0] for row in stored)  # scellés au repos


def test_a_new_provider_picks_its_model_from_the_list_before_anything_is_saved(world, monkeypatch):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    seen: list[str] = []

    async def fake_models(spec):  # le fournisseur répond avec la clé tapée : rien ne sort de la machine
        seen.append(spec.api_key)
        return ["claude-haiku-4-5", "claude-opus-5"]

    monkeypatch.setattr("mika.app.reglages.list_models", fake_models)
    url = f"{BASE}/fournisseurs"
    page = html_of(client.get(f"{url}?enregistrement=backends&cle=&nouveau=1"))
    assert "Charger la liste" in page
    # le modèle est obligatoire et vide : sans formnovalidate, le navigateur refuse l'envoi et rien ne se charge
    assert re.search(r'<input name="model"[^>]*required', page)
    assert re.search(r'<button[^>]*name="_charger" value="model"[^>]*formnovalidate', page)
    loaded = post(client, url, {**backend("neuf", kind="claude", model="", api_key=CANARY_KEY), "_charger": "model"})
    text = html_of(loaded)
    assert loaded.status_code == 200 and "Rien n'est encore enregistré" in text and seen == [CANARY_KEY]
    assert re.search(r'<select name="model"[^>]*>.*?<option value="claude-opus-5"', text, re.S)
    assert CANARY_KEY not in loaded.text  # la clé tapée ne redescend pas : elle est gardée sous un jeton
    assert client.portal.call(live.settings.llm).backends == {}  # rien d'enregistré
    token = re.search(r'name="_reserve" value="([^"]+)"', text).group(1)
    saved = post(client, url, {**backend("neuf", kind="claude", model="claude-opus-5", api_key=""),
                               "_reserve": token})
    assert saved.status_code == 200 and "« neuf » enregistré" in html_of(saved)
    spec = client.portal.call(live.settings.llm).backends["neuf"]
    assert spec.model == "claude-opus-5" and spec.api_key == CANARY_KEY
    # un jeton inconnu ne rend aucun secret ; une liste indisponible le dit, sans rien enregistrer
    none = post(client, url, {**backend("autre", kind="claude", model="m", api_key=""), "_reserve": "faux"})
    assert none.status_code == 200 and client.portal.call(live.settings.llm).backends["autre"].api_key == ""

    async def broken(spec):
        raise __import__("mika.adapters.llm.models", fromlist=["ListingFailed"]).ListingFailed("hôte injoignable")

    monkeypatch.setattr("mika.app.reglages.list_models", broken)
    failed = post(client, url, {**backend("local", kind="ollama", model=""), "_charger": "model"})
    assert failed.status_code == 200 and "Liste indisponible" in html_of(failed)
    assert "local" not in client.portal.call(live.settings.llm).backends
