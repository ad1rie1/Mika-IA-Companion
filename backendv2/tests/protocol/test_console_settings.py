"""Les réglages déclarés : chaque section se rend depuis son modèle, s'enregistre
par un formulaire protégé, refuse champ par champ, ne réaffiche jamais un
secret, et laisse une trace dans le journal de configuration.

Canari : des secrets connus sont posés, puis cherchés dans chaque page de la
console et dans le journal — ils n'y sont jamais.
"""

from __future__ import annotations

import html

from mika.app.console import NAVIGATION
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

CANARY_KEY = "sk-ant-api-CANARI-7f3e"
CANARY_MAIL = "mot-de-passe-CANARI"
CANARY_STT = "sk-CANARI-whisper"


def html_of(r) -> str:
    return html.unescape(r.text)


def post(client, path: str, data: dict) -> object:
    return client.post(path, data={"csrf": client.cookies.get("csrftoken"), **data})


def backend(name: str, **fields: str) -> dict:
    return {"_section": "modeles", "_enregistrement": "backends", "_ancienne": "", "_cle": name,
            "_champs": list(fields), **fields}


def test_models_are_records_with_sealed_keys_roles_and_a_loader_that_degrades(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    client.get("/inspecteur/reglages/modeles")
    url = "/inspecteur/reglages/modeles"
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
    # les rôles : une correspondance rôle → fournisseur ; un choix hors liste est refusé
    routed = post(client, url, {"_section": "modeles", "_champs": ["routes", "context_tokens"],
                                "routes.reply": "claude", "routes.extract": "local", "context_tokens": "32 000"})
    assert routed.status_code == 200 and "Modèles : enregistré" in html_of(routed)
    unknown = post(client, url, {"_section": "modeles", "_champs": ["routes"], "routes.reply": "fantome"})
    assert unknown.status_code == 400 and "choix inconnu" in html_of(unknown)
    cfg = client.portal.call(live.settings.llm)
    assert cfg.routes == {"reply": "claude", "extract": "local"} and cfg.context_tokens == 32_000
    # la liste des modèles d'un fournisseur injoignable : un message, pas une erreur
    loading = client.get(f"{url}?section=modeles&enregistrement=backends&cle=local&charger=model")
    assert loading.status_code == 200 and "Liste indisponible" in html_of(loading)
    # retirer un fournisseur emporte les rôles qui le visaient
    gone = post(client, url, {"_section": "modeles", "_supprimer": "backends", "_cle": "local"})
    assert "« local » retiré" in html_of(gone)
    assert client.portal.call(live.settings.llm).routes == {"reply": "claude"}


def test_persona_form_yaml_import_and_back_to_the_file(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    url = "/inspecteur/reglages/personnalite"
    page = html_of(client.get(url))
    assert "Personnage" in page and "Tempérament" in page and "Ce que pilote chaque curseur" in page
    kernel = live.kernel

    def revisions() -> int:
        return len(client.portal.call(lambda: kernel.mind.store.latest([self_c.PERSONA_REVISED.name], 50)))

    before = revisions()
    saved = post(client, url, {"_section": "personnage", "_champs": ["name", "traits"], "name": "Mikaela",
                               "traits": "Curieuse de tout, pas juste de tech\nDrôle"})
    assert saved.status_code == 200 and "Personnage : enregistré" in html_of(saved)
    doc = client.portal.call(lambda: kernel.mind.frame().get(self_c.PERSONA))
    assert doc.name == "Mikaela" and doc.traits == ("Curieuse de tout, pas juste de tech", "Drôle")
    assert revisions() == before + 1
    unknown = post(client, url, {"_section": "personnage", "_yaml": "1", "_texte": "name: Mika\ncouleur: bleue\n"})
    assert unknown.status_code == 400 and "champ inconnu" in html_of(unknown) and revisions() == before + 1
    broken = post(client, url, {"_section": "personnage", "_yaml": "1", "_texte": "name: [Mika\n"})
    assert broken.status_code == 400 and "YAML illisible" in html_of(broken)
    back = post(client, url, {"_section": "personnage", "_commande": "fichier"})
    assert "Retour au fichier" in html_of(back)
    assert client.portal.call(lambda: kernel.mind.frame().get(self_c.PERSONA)).name == "Mika"


def test_temperament_sliders_rederive_the_parameters(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    url = "/inspecteur/reglages/personnalite"
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
    url = "/inspecteur/reglages/canaux"
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
    params = html_of(client.get("/inspecteur/reglages/parametres?faculte=identity"))
    assert "réglage" in params


def test_senses_mail_feeds_transcription_and_a_device_token_shown_once(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    url = "/inspecteur/reglages/sens"
    client.get(url)
    account = {"_section": "courrier", "_enregistrement": "accounts", "_ancienne": "", "_cle": "perso",
               "_champs": ["address", "imap_host", "user", "password", "imap_port", "voice", "tone"],
               "address": "mika@exemple.fr", "imap_host": "imap.exemple.fr", "user": "mika",
               "password": CANARY_MAIL, "imap_port": "993", "voice": "proprietaire", "tone": "sobre",
               "_retour": "/inspecteur/courrier/comptes"}
    mail = post(client, url, account)
    assert mail.status_code == 200 and CANARY_MAIL not in mail.text
    assert "/inspecteur/courrier/comptes" in str(mail.url)  # l'enregistrement ramène au courrier
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
    feeds = post(client, url, {"_section": "flux", "_champs": ["urls"], "urls": "https://a.fr/rss\nftp://b"})
    assert feeds.status_code == 400 and "non http(s)" in html_of(feeds)
    post(client, url, {"_section": "flux", "_champs": ["urls"], "urls": "https://a.fr/rss\nhttps://b.fr/atom"})
    assert client.portal.call(live.settings.feeds) == ["https://a.fr/rss", "https://b.fr/atom"]
    post(client, url, {"_section": "transcription", "_champs": ["api_key"], "api_key": CANARY_STT})
    assert client.portal.call(live.settings.stt)["api_key"] == CANARY_STT
    shown = post(client, url, {"_section": "appareils", "_commande": "jeton"})
    token = client.portal.call(live.settings.sensors_token)
    assert token and token in shown.text  # montré une fois…
    assert token not in client.get(url).text  # … et plus jamais


def test_internal_parameters_are_readable_and_overrides_are_bounded_and_journaled(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    url = "/inspecteur/reglages/parametres"
    overview = html_of(client.get(url))
    assert "Les facultés" in overview and "Ce que pilote chaque curseur" in overview
    body = html_of(client.get(f"{url}?faculte=body"))
    assert "shift_minutes" in body and "tempérament" in body and "Modifier (avancé)" in body
    assert client.get(f"{url}?faculte=inconnue").status_code == 200  # retombe sur la vue d'ensemble
    nothing = post(client, url, {"_faculte": "body"})
    assert nothing.status_code == 200 and "Rien n'a changé" in html_of(nothing)
    refused = post(client, url, {"_faculte": "inconnue"})
    assert refused.status_code == 400 and "Faculté inconnue" in html_of(refused)


def test_every_settings_change_lands_in_the_configuration_journal_without_content(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    client.get("/inspecteur/reglages/modeles")
    post(client, "/inspecteur/reglages/modeles", backend("claude", kind="claude", model="m", api_key=CANARY_KEY))
    post(client, "/inspecteur/reglages/sens", {"_section": "transcription", "_champs": ["api_key"],
                                               "api_key": CANARY_STT})
    journal = html_of(client.get("/inspecteur/reglages/journal"))
    assert "reglages.modeles" in journal and "reglages.transcription" in journal and "user_1" in journal
    ops = client.portal.call(lambda: live.kernel.mind.store.latest([rt.OPERATED.name], 50))
    raw = " ".join(o.data for o in ops)
    assert CANARY_KEY not in raw and CANARY_STT not in raw
    # canari : aucun secret dans aucune page de la console
    urls = []
    for group in NAVIGATION:
        for d in group.items:
            base = "/inspecteur/" if d.key == "accueil" else f"/inspecteur/{d.key}"
            urls += [base] + [f"{base}/{k.split('.', 1)[1]}" for k in d.builtin]
    urls += ["/inspecteur/reglages/modeles?section=modeles&enregistrement=backends&cle=claude",
             "/inspecteur/reglages/parametres?faculte=identity", "/inspecteur/systeme/operations"]
    for u in urls:
        text = client.get(u, follow_redirects=True).text
        for canary in (CANARY_KEY, CANARY_STT):
            assert canary not in text, (u, canary)
    stored = client.portal.call(live.kernel.mind.store.query_mind, "SELECT value FROM settings")
    assert all(CANARY_KEY not in row[0] and CANARY_STT not in row[0] for row in stored)  # scellés au repos
