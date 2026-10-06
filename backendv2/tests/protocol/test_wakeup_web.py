"""Les réveils par API (ADR 0068) par le vrai serveur : la route, ses clés, sa configuration et sa console.

Un réveil inconnu et une mauvaise clé se répondent pareil (401) ; désactivé : 403 ; texte : 400 ; trop d'appels,
par heure ou en attente : 429 ; son projet n'est pas actif : 409 ; reçu : 202, avec le réglage figé dans le journal.
Une clé neuve rend l'ancienne inutile ; retirée, plus rien ne passe ; la clé en clair n'est gardée nulle part (ni
dans les réglages, ni dans l'audit des actions). La page d'un réveil propose ses projets et ses destinataires, et
refuse un projet inconnu.
"""

from __future__ import annotations

from mika.app.wakeups import WakeEndpoint, WakeupConfig
from mika.contracts import runtime as rt
from mika.contracts import wakeup as c
from mika.runtime.effects import with_content
from mika.runtime.operations import perform
from tests.protocol.test_console_settings import BASE, html_of, post
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture

ROUTE = "/api/wake/serre"


def configure(client, live, **fields):
    endpoint = WakeEndpoint(label="l'alerte de la serre", instructions="Résume-la.", **fields)
    client.portal.call(live.settings.save_wakeup, WakeupConfig(endpoints={"serre": endpoint}))


def key_for(client, live, name="serre"):
    return client.portal.call(live.wakeups.new_key, name, "test")


def send(client, key, text="Il fait 41 °C dans la serre.", route=ROUTE, **headers):
    return client.post(route, json={"text": text}, headers={"Authorization": f"Bearer {key}", **headers})


def called(client, live):
    async def go():
        mind = live.kernel.mind
        return [with_content(mind, mind.decode(e)) for e in mind.store.read() if e.type == c.CALLED.name]

    return client.portal.call(go)


def test_a_call_is_admitted_only_with_its_key_and_lands_with_the_endpoint_settings(world):  # noqa: F811
    client, live, _ = world
    configure(client, live, tools=("memory",), notify=c.NOBODY)
    assert send(client, "mwk_inconnue").status_code == 401  # pas encore de clé : rien ne passe
    key = key_for(client, live)
    ok = send(client, key)
    assert ok.status_code == 202 and ok.headers["cache-control"] == "no-store"
    unknown, wrong = send(client, key, route="/api/wake/cave"), send(client, key[:-2] + "xy")
    assert unknown.status_code == wrong.status_code == 401 and unknown.json() == wrong.json()  # rien ne trahit un nom
    assert send(client, key, text="  ").status_code == 400
    assert send(client, key, text="x" * 4001).status_code == 400
    [ev] = called(client, live)
    assert ok.json() == {"ok": True, "call": ev.seq}
    d = ev.data
    assert d.endpoint == "serre" and d.text.text == "Il fait 41 °C dans la serre." and d.instructions.text == "Résume-la."
    assert d.bundles == ("memory",) and d.notify == c.NOBODY and d.project == 0 and not d.rouse
    assert d.expires_at > ev.at
    assert client.post(ROUTE, json={"text": "x"}, headers={"Authorization": f"Bearer {key}",
                                                          "Origin": "https://ailleurs.example"}).status_code == 403


def test_disabled_busy_and_inactive_project_are_refused_before_anything_is_written(world):  # noqa: F811
    client, live, _ = world
    configure(client, live, enabled=False)
    key = key_for(client, live)
    assert send(client, key).status_code == 403
    configure(client, live, max_pending=1)
    assert send(client, key).status_code == 202  # l'arbitrage est éteint ici : il reste en attente
    busy = send(client, key)
    assert busy.status_code == 429 and busy.headers["retry-after"]
    configure(client, live, per_hour=1, max_pending=50)
    assert send(client, key).status_code == 429  # déjà un appel dans l'heure
    configure(client, live, project="999")  # un projet qui n'existe pas (écrit sans passer par la console)
    assert send(client, key).status_code == 409
    assert len(called(client, live)) == 1


def test_the_same_idempotency_key_makes_one_call_even_at_the_cap(world):  # noqa: F811
    client, live, _ = world
    configure(client, live, max_pending=1)
    key = key_for(client, live)
    first = send(client, key, **{"Idempotency-Key": "abc"})
    # le client n'a pas su que c'était reçu : le rejeu rend le même appel, même plafond atteint (par cet appel-là)
    again = send(client, key, **{"Idempotency-Key": "abc"})
    assert first.status_code == again.status_code == 202 and first.json()["call"] == again.json()["call"]
    assert send(client, key, **{"Idempotency-Key": "abd"}).status_code == 429  # un autre appel, lui, attend son tour
    assert len(called(client, live)) == 1


def test_a_new_key_voids_the_old_one_a_revoked_key_lets_nothing_through(world):  # noqa: F811
    client, live, _ = world
    configure(client, live, max_pending=50)
    old = key_for(client, live)
    new = key_for(client, live)
    assert send(client, old).status_code == 401 and send(client, new).status_code == 202
    assert client.portal.call(live.wakeups.revoke_key, "serre", "test") is True
    assert send(client, new).status_code == 401
    # retiré de la configuration, il emporte sa clé : recréé sous ce nom, il n'en a pas
    key = key_for(client, live)
    client.portal.call(live.settings.save_wakeup, WakeupConfig())
    assert client.portal.call(live.settings.wakeup_keys) == {}
    configure(client, live)
    assert send(client, key).status_code == 401


def test_the_key_is_shown_once_and_kept_nowhere(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    configure(client, live)
    done = client.portal.call(lambda: perform(live.kernel, "wakeup.nouvelle_cle", {}, by="adrien", subject="serre"))
    assert done.ok
    key = next(w for w in done.message.split() if w.startswith("mwk_"))
    assert send(client, key).status_code == 202
    rows = client.portal.call(lambda: live.settings.store.run_mind(
        lambda sql: sql.execute("SELECT value FROM settings").fetchall()))
    assert all(key not in r[0] for r in rows)  # seule son empreinte est gardée

    async def audits():
        mind = live.kernel.mind
        return [str(mind.decode(e).data) for e in mind.store.read() if e.type == rt.OPERATED.name]

    trail = client.portal.call(audits)
    assert trail and all(key not in t for t in trail)
    page = html_of(client.get("/inspecteur/fiche/reveil/serre"))
    assert key not in page and key[:8] in page  # un indice pour la reconnaître, jamais la clé


def test_the_settings_page_offers_projects_and_recipients_and_refuses_an_unknown_project(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    url = f"{BASE}/reveils"
    page = html_of(client.get(f"{url}?enregistrement=endpoints&cle=&nouveau=1"))
    assert "aucun — un travail à part" in page and "ses propriétaires" in page and "adrien (compte)" in page
    record = {"_section": "reveils", "_enregistrement": "endpoints", "_ancienne": "", "_cle": "serre",
              "_champs": ["label", "instructions", "project", "notify", "tools"], "label": "l'alerte de la serre",
              "instructions": "Résume-la.", "project": "999", "notify": "proprietaire", "tools": "memory"}
    refused = post(client, url, record)
    assert refused.status_code == 400 and "projet inconnu" in html_of(refused)
    bad_tool = post(client, url, {**record, "project": "aucun", "tools": "memory\nworkshop"})
    assert bad_tool.status_code == 400 and "workshop" in html_of(bad_tool)
    saved = post(client, url, {**record, "project": "aucun"})
    assert saved.status_code == 200
    got = client.portal.call(live.settings.wakeup).endpoints["serre"]
    assert got.project == "aucun" and got.tools == ("memory",) and got.notify == c.OWNERS
    assert post(client, url, {**record, "project": "aucun", "_cle": "Serre Nord"}).status_code == 400  # le nom = l'URL
    fiche = html_of(client.get("/inspecteur/fiche/reveil/serre"))
    assert "POST /api/wake/serre" in fiche and "sans clé" in fiche
    listing = html_of(client.get("/inspecteur/reveils"))
    assert "serre" in listing and "Déclarer un réveil" in listing


def test_a_hostile_body_is_refused_cleanly(world):  # noqa: F811
    client, live, _ = world
    configure(client, live)
    key = key_for(client, live)
    auth = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    # du JSON illisible, ou valide mais imbriqué très profond (pas un objet) : refusé proprement, jamais une panne
    assert client.post(ROUTE, content=b"[" * 50_000, headers=auth).status_code == 400
    assert client.post(ROUTE, content=b"[" * 30_000 + b"]" * 30_000, headers=auth).status_code == 400

    def chunks():  # sans Content-Length : lu par morceaux, borné quand même
        for _ in range(100):
            yield b"x" * 4096

    assert client.post(ROUTE, content=chunks(), headers=auth).status_code == 413
    assert called(client, live) == []
