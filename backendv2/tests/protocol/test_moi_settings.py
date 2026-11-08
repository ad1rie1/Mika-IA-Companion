"""L'API par personne, Paramètres (ADR 0187) : son nom, son mot de passe ; les boîtes et les comptes Teams qu'elle
branche, à elle et à personne d'autre (ADR 0185, 0186), leurs secrets jamais rendus ; la clé de son extension Teams,
montrée une seule fois ; comment part ce que Mika prépare depuis chacun, qu'elle règle elle-même (ADR 0207)."""

from __future__ import annotations

from mika.adapters.mail.config import MailAccount, MailConfig
from mika.app.moi import settings as settings_moi
from mika.plugins import email as email_p
from mika.vocab.canals import CanalRule, CanalTable, mail_rule, teams_rule
from tests.protocol.test_moi_mail import API, login, post, second_person
from tests.protocol.test_web import bootstrap, csrf, world  # noqa: F401 — fixture partagée

BOX = {"label": "Rando Cassel", "address": "rando.cassel@example.test", "imap_host": "imap.example.test",
       "user": "rando.cassel@example.test", "password": "secret-imap", "smtp_host": "smtp.example.test",
       "smtp_user": "rando.cassel@example.test", "smtp_password": "secret-smtp"}


def boxes(client, live) -> dict:
    """Les boîtes enregistrées, lues comme le serveur les lit (dans sa boucle : le fil du test voit une base d'avant)."""
    return client.portal.call(live.settings.email).accounts


def teams_accounts(client, live) -> dict:
    return client.portal.call(live.settings.teams).accounts


def test_she_changes_her_name_and_her_password(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    assert post(client, "/account/name", {"name": "  Adrien   Moreau "}).status_code == 200
    assert client.get(API).json()["name"] == "Adrien Moreau"
    wrong = post(client, "/account/password", {"current": "pas le bon", "password": "un-autre-mot-de-passe-long"})
    assert wrong.status_code == 400 and "current" in wrong.json()["fields"]
    weak = post(client, "/account/password", {"current": "un-mot-de-passe-long", "password": "court"})
    assert weak.status_code == 400
    ok = post(client, "/account/password", {"current": "un-mot-de-passe-long", "password": "un-autre-mot-de-passe-long"})
    assert ok.status_code == 200 and ok.json()["relogin"]
    assert client.get(API).status_code == 401  # ses sessions se ferment : on se reconnecte
    r = client.post("/auth/login", json={"username": "adrien", "password": "un-autre-mot-de-passe-long"},
                    headers=csrf(client))
    assert r.status_code == 200


def test_a_box_she_plugs_is_hers_alone_and_keeps_its_secrets(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    login(client, "lea")
    made = post(client, "/mail/box/save", {"values": BOX})
    assert made.status_code == 200, made.text
    key = made.json()["box"]
    assert key.startswith("rando-cassel-")  # un suffixe tiré au hasard : une clé ne resert jamais
    stored = boxes(client, live)[key]
    assert stored.owner == "personne:" + lea and stored.password == "secret-imap"
    assert [b["key"] for b in client.get(API + "/mail/boxes").json()["boxes"]] == [key]
    shown = client.get(API + f"/mail/box?box={key}").json()
    assert shown["values"]["address"] == BOX["address"] and "password" not in shown["values"]
    assert shown["secrets"] == {"password": True, "smtp_password": True} and "secret-imap" not in str(shown)

    # la régler : un secret laissé vide reste ; « à qui » ne se règle pas ici
    assert post(client, "/mail/box/save", {"box": key, "values": {"label": "Rando", "password": ""}}).status_code == 200
    again = boxes(client, live)[key]
    assert again.label == "Rando" and again.password == "secret-imap" and again.owner == "personne:" + lea
    assert post(client, "/mail/box/save", {"box": key, "values": {"owner": ""}}).status_code == 400
    bad = post(client, "/mail/box/save", {"values": {"label": "x", "imap_port": "beaucoup"}})
    assert bad.status_code == 400 and bad.json()["fields"]

    login(client, "adrien")  # une boîte à Léa n'existe pas pour toi
    assert key not in [b["key"] for b in client.get(API + "/mail/boxes").json()["boxes"]]
    assert client.get(API + f"/mail/box?box={key}").status_code == 404
    assert post(client, "/mail/box/remove", {"box": key}).status_code == 404
    login(client, "lea")
    assert post(client, "/mail/box/remove", {"box": key}).status_code == 200
    assert key not in boxes(client, live)


def test_her_teams_account_and_its_extension_key(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    login(client, "lea")
    made = post(client, "/teams/account/save", {"values": {"label": "Teams de Léa", "display_name": "Léa"}})
    assert made.status_code == 200, made.text
    account = made.json()["account"]
    assert teams_accounts(client, live)[account].owner == "personne:" + lea
    assert [a["key"] for a in client.get(API + "/teams/accounts").json()["accounts"]] == [account]
    fresh = post(client, "/teams/account/key", {"account": account})
    assert fresh.status_code == 200 and fresh.json()["key"].startswith("mtk_")
    assert client.get(API + f"/teams/account?account={account}").json()["extension_key"]["hint"].startswith("mtk_")
    assert fresh.json()["key"] not in client.get(API + f"/teams/account?account={account}").text  # plus montrée
    assert post(client, "/teams/account/key", {"account": "principal"}).status_code == 404  # pas le sien
    assert post(client, "/teams/account/revoke", {"account": account}).status_code == 200
    assert post(client, "/teams/account/revoke", {"account": account}).status_code == 409


def test_a_box_is_checked_against_the_console_bounds(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    bad = post(client, "/mail/box/save", {"values": {**BOX, "imap_port": 0}})
    assert bad.status_code == 400 and "imap_port" in bad.json()["fields"]
    assert post(client, "/mail/box/save", {"values": {**BOX, "since_days": 365}}).status_code == 400
    assert boxes(client, live) == {}


def test_she_removes_her_teams_account_and_its_key_goes_with_it(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    second_person(client, live)
    login(client, "lea")
    account = post(client, "/teams/account/save", {"values": {"label": "Teams de Léa"}}).json()["account"]
    assert post(client, "/teams/account/key", {"account": account}).status_code == 200
    login(client, "adrien")
    assert post(client, "/teams/account/remove", {"account": account}).status_code == 404  # pas le tien
    login(client, "lea")
    assert post(client, "/teams/account/remove", {"account": account}).status_code == 200
    assert account not in teams_accounts(client, live)
    assert account not in client.portal.call(live.settings.teams_keys)


def test_a_changed_connection_asks_for_the_password_again(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    key = post(client, "/mail/box/save", {"values": BOX}).json()["box"]
    moved = post(client, "/mail/box/save", {"box": key, "values": {"imap_host": "imap.ailleurs.example.test"}})
    assert moved.status_code == 400 and "password" in moved.json()["fields"]  # jamais vers un autre serveur
    assert boxes(client, live)[key].imap_host == "imap.example.test"
    ok = post(client, "/mail/box/save", {"box": key, "values": {"imap_host": "imap.ailleurs.example.test",
                                                                 "password": "nouveau-secret"}})
    assert ok.status_code == 200 and boxes(client, live)[key].password == "nouveau-secret"
    assert boxes(client, live)[key].smtp_password == "secret-smtp"  # l'envoi n'a pas changé : son secret reste


def test_a_person_only_plugs_servers_on_the_internet(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    second_person(client, live)
    login(client, "lea")
    for host in ("127.0.0.1", "localhost", "192.168.1.10", "nas.local"):
        r = post(client, "/mail/box/save", {"values": {**BOX, "imap_host": host}})
        assert r.status_code == 400 and "imap_host" in r.json()["fields"], host
    r = post(client, "/mcp/plug", {"name": "nas", "purpose": "Mes fichiers du réseau.", "url": "https://10.0.0.5/mcp"})
    assert r.status_code == 400 and "url" in r.json()["fields"]
    login(client, "adrien")  # un opérateur règle ce qu'il veut, comme dans la console
    assert post(client, "/mail/box/save", {"values": {**BOX, "imap_host": "192.168.1.10"}}).status_code == 200


def test_logging_in_again_and_again_is_never_blocked(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    for _ in range(12):  # un essai réussi est rendu : seuls les faux comptent
        login(client, "adrien")


def test_password_tries_are_bounded(world):  # noqa: F811
    client, _, _ = world
    bootstrap(client)
    for _ in range(5):
        assert post(client, "/account/password", {"current": "faux", "password": "un-autre-mot-de-passe-long"}
                    ).status_code == 400
    r = post(client, "/account/password", {"current": "un-mot-de-passe-long", "password": "un-autre-mot-de-passe-long"})
    assert r.status_code == 429  # même juste : la fenêtre est pleine


def test_a_box_an_operator_set_on_the_machine_still_takes_her_changes(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    lea = second_person(client, live)
    davmail = MailAccount.model_validate({**BOX, "label": "Pro de Léa", "imap_host": "127.0.0.1",
                                          "smtp_host": "127.0.0.1", "owner": "personne:" + lea})
    client.portal.call(live.settings.save_email, MailConfig(accounts={**boxes(client, live), "davmail": davmail}))
    client.portal.call(live.reconfigure)
    login(client, "lea")
    r = post(client, "/mail/box/save", {"box": "davmail", "values": {"signature": "Léa", "enabled": False}})
    assert r.status_code == 200, r.text  # seuls comptent les serveurs qu'elle donne
    assert boxes(client, live)["davmail"].signature == "Léa"
    moved = post(client, "/mail/box/save", {"box": "davmail", "values": {"smtp_host": "10.0.0.9",
                                                                         "smtp_password": "x"}})
    assert moved.status_code == 400 and set(moved.json()["fields"]) == {"smtp_host"}
    # viser un autre service du même hôte (son port, sa sécurité), c'est en donner un : refusé aussi
    port = post(client, "/mail/box/save", {"box": "davmail", "values": {"imap_port": 3306, "imap_ssl": False,
                                                                        "password": "x"}})
    assert port.status_code == 400 and set(port.json()["fields"]) == {"imap_host"}
    assert boxes(client, live)["davmail"].imap_port == davmail.imap_port


def test_the_sending_server_never_gets_the_reading_password(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    key = post(client, "/mail/box/save", {"values": {**BOX, "smtp_password": ""}}).json()["box"]
    # l'envoi sans mot de passe à lui se sert de celui de la lecture : il ne part pas vers un autre serveur
    moved = post(client, "/mail/box/save", {"box": key, "values": {"smtp_host": "smtp.ailleurs.example.test"}})
    assert moved.status_code == 400 and "smtp_password" in moved.json()["fields"]
    assert boxes(client, live)[key].smtp_host == "smtp.example.test"
    given = post(client, "/mail/box/save", {"box": key, "values": {"smtp_host": "smtp.ailleurs.example.test",
                                                                    "password": "redonne-pour-lire"}})
    assert given.status_code == 200, given.text  # redonné dans le même envoi : il sait où il va
    ok = post(client, "/mail/box/save", {"box": key, "values": {"smtp_port": 465, "smtp_password": "pour-envoyer"}})
    assert ok.status_code == 200 and boxes(client, live)[key].smtp_password == "pour-envoyer"
    # retirer l'envoi (une boîte qui ne fait que lire) : rien ne part plus, rien à redonner
    off = post(client, "/mail/box/save", {"box": key, "values": {"smtp_host": ""}})
    assert off.status_code == 200, off.text
    assert boxes(client, live)[key].smtp_password == "pour-envoyer" and not boxes(client, live)[key].can_send
    back = post(client, "/mail/box/save", {"box": key, "values": {"smtp_host": "smtp.encore.example.test"}})
    assert back.status_code == 400 and "smtp_password" in back.json()["fields"]  # un serveur revient : redonné


def test_a_microsoft_box_only_reaches_microsoft(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    ms = {"label": "Hotmail", "address": "adrien@hotmail.example", "auth": "microsoft", "user": "adrien@hotmail.example",
          "imap_host": "outlook.office365.com", "smtp_host": "smtp-mail.outlook.com",
          "oauth_client_id": "12345678-1234-1234-1234-123456789abc"}
    made = post(client, "/mail/box/save", {"values": ms})
    assert made.status_code == 200, made.text
    key = made.json()["box"]
    moved = post(client, "/mail/box/save", {"box": key, "values": {"smtp_host": "smtp.ailleurs.example.test"}})
    assert moved.status_code == 400 and set(moved.json()["fields"]) == {"smtp_host"}  # son jeton : chez Microsoft
    assert post(client, "/mail/box/save", {"values": {**ms, "imap_host": "imap.ailleurs.example.test"}}
                ).status_code == 400
    plain = post(client, "/mail/box/save", {"values": BOX}).json()["box"]
    switched = post(client, "/mail/box/save", {"box": plain, "values": {"auth": "microsoft"}})
    assert switched.status_code == 400 and set(switched.json()["fields"]) == {"imap_host", "smtp_host"}
    assert post(client, "/mail/box/save", {"box": key, "values": {"signature": "A."}}).status_code == 200


def test_a_creation_said_twice_makes_one_box(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    first = post(client, "/mail/box/save", {"values": BOX, "nonce": "ajout-1"}).json()
    again = post(client, "/mail/box/save", {"values": BOX, "nonce": "ajout-1"}).json()
    assert again["box"] == first["box"] and again["deduped"] and "deduped" not in first
    assert list(boxes(client, live)) == [first["box"]]
    assert post(client, "/mail/box/save", {"values": BOX, "nonce": "ajout-2"}).json()["box"] != first["box"]
    account = post(client, "/teams/account/save", {"values": {"label": "Teams"}, "nonce": "t-1"}).json()["account"]
    assert post(client, "/teams/account/save", {"values": {"label": "Teams"}, "nonce": "t-1"}).json()["account"] == account


def test_a_person_plugs_a_bounded_number_of_boxes(world, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings_moi, "OWN_MAX", 1)
    client, live, _ = world
    bootstrap(client)
    second_person(client, live)
    login(client, "lea")
    assert post(client, "/mail/box/save", {"values": BOX}).status_code == 200
    assert post(client, "/mail/box/save", {"values": BOX}).status_code == 409
    assert post(client, "/teams/account/save", {"values": {"label": "Teams"}}).status_code == 200
    assert post(client, "/teams/account/save", {"values": {"label": "Teams"}}).status_code == 409
    login(client, "adrien")  # un opérateur, comme dans la console
    for _ in range(2):
        assert post(client, "/mail/box/save", {"values": BOX}).status_code == 200


def canals(client, live):
    return client.portal.call(live.settings.canals)


def test_she_sets_how_what_mika_prepares_leaves_her_box(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    second_person(client, live)
    login(client, "lea")
    key = post(client, "/mail/box/save", {"values": BOX}).json()["box"]
    canal = f"courrier:{key}"
    rules = client.get(API + f"/mail/box?box={key}").json()["rules"]
    # jamais réglée : la règle de départ du courrier, telle que le courrier la lit (rien ne part sans ton accord)
    assert (rules["canal"], rules["set"], rules["common"]) == (canal, False, False)
    assert [(a["who"], a["prepare"], a["reply"]) for a in rules["lines"]] == [("Tout le monde", False, "accord")]
    assert (rules["default"]["prepare"], rules["default"]["reply"]) == (False, "non")
    body = {"canal": canal, "version": rules["version"], "lines": [{"prepare": True, "reply": "seule"}],
            "default": {"prepare": False, "reply": "accord"}}
    for wrong, code in (({"lines": [{"prepare": True, "reply": "brouillon"}]}, 400),  # le courrier n'en a pas
                        ({"lines": [{"prepare": "oui", "reply": "seule"}]}, 400),
                        ({"lines": [{"prepare": True, "reply": "seule", "who": ["tous"]}]}, 400),  # qui : la console
                        ({"lines": []}, 409),  # une ligne de moins : ce n'est plus la règle lue
                        ({"version": "0" * 16}, 409),
                        ({"canal": "courrier"}, 400), ({"canal": "courrier:pas-la-sienne"}, 404)):
        assert post(client, "/rules", {**body, **wrong}).status_code == code, wrong
    assert canal not in canals(client, live).tables  # rien d'écrit
    saved = post(client, "/rules", body)
    assert saved.status_code == 200, saved.text
    table = canals(client, live).tables[canal]
    assert table.lines[0].who == ("tous",) and (table.lines[0].prepare, table.lines[0].reply) == (True, "seule")
    assert table.lines[0].canal == (canal,) and table.default.reply == "accord"
    # le courrier la lit : la règle du canal de la boîte, journalisée avec ses paramètres
    assert mail_rule(canals(client, live), key, "quelqu.un@example.test").reply == "seule"
    assert canal in email_p.params_of(live.kernel.mind.frame()).canaux.tables
    again = client.get(API + f"/mail/box?box={key}").json()["rules"]
    assert again["set"] and again["version"] != rules["version"] and again["lines"][0]["prepare"]
    assert post(client, "/rules", body).status_code == 409  # l'empreinte d'avant ne vaut plus

    login(client, "adrien")  # la boîte de Léa : ni la sienne, ni à toi
    assert post(client, "/rules", {**body, "version": again["version"]}).status_code == 404


def test_a_shared_box_keeps_its_rule_to_its_owner_and_teams_has_drafts(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    second_person(client, live)
    adrien = client.get(API).json()["person"]
    login(client, "lea")
    key = post(client, "/mail/box/save", {"values": BOX}).json()["box"]
    assert post(client, "/shares/set", {"kind": "mail", "key": key, "person": adrien, "level": "servir"}
                ).status_code == 200
    account = post(client, "/teams/account/save", {"values": {"label": "Teams de Léa"}}).json()["account"]
    rules = client.get(API + f"/teams/account?account={account}").json()["rules"]
    assert rules["canal"] == f"teams:{account}" and not rules["set"]
    # une ligne réglée dans la console (qui, par où) : la propriétaire n'en règle que préparer et comment ça part
    client.portal.call(live.settings.save_canal, f"teams:{account}", CanalTable(
        lines=(CanalRule(who=("adresse:Marc",), reply="accord"), CanalRule(who=("tous",), reply="accord"))))
    rules = client.get(API + f"/teams/account?account={account}").json()["rules"]
    assert [a["who"] for a in rules["lines"]] == ["Marc", "Tout le monde"] and rules["set"]
    teams = post(client, "/rules", {"canal": f"teams:{account}", "version": rules["version"],
                                    "lines": [{"prepare": True, "reply": "brouillon"}, {"prepare": False, "reply": "non"}],
                                    "default": {"prepare": False, "reply": "non"}})
    assert teams.status_code == 200, teams.text  # Teams a ses brouillons, posés dans Teams
    assert teams_rule(canals(client, live), account, "Marc Dupont").reply == "brouillon"
    assert teams_rule(canals(client, live), account, "Quelqu'un d'autre").reply == "non"
    assert canals(client, live).tables[f"teams:{account}"].lines[0].who == ("adresse:Marc",)
    # une boîte sans règle à elle suit celle de tout le courrier, si la console l'a réglée : c'est celle-là qu'elle lit
    client.portal.call(live.settings.save_canal, "courrier", CanalTable(
        lines=(CanalRule(who=("tous",), prepare=True, reply="seule"),)))
    common = client.get(API + f"/mail/box?box={key}").json()["rules"]
    assert (common["set"], common["common"]) == (False, True)
    assert [(a["prepare"], a["reply"]) for a in common["lines"]] == [(True, "seule")]

    login(client, "adrien")  # elle la lui partage pour s'en servir : la règle reste à elle
    shared = client.get(API + "/mail/boxes").json()["boxes"]
    assert [b["level"] for b in shared if b["key"] == key] == ["servir"]
    assert post(client, "/rules", {"canal": f"courrier:{key}", "version": "x", "lines": [], "default": {}}
                ).status_code == 403
