"""Un Teams par personne (ADR 0186) par le vrai serveur : la porte, la console, les réglages, la fiche d'une personne.

- **la porte** reconnaît le compte à sa clé : deux clés, deux comptes — chacun range ce qu'il pousse sous lui, ne relève
  que sa file, n'accuse que ses brouillons ; la clé unique d'avant est celle du compte ``principal`` ;
- **la console** se lit par propriétaire (« Les comptes de », ``?qui=`` : toi, elle par son nom, chaque personne qui a
  un compte Teams), puis par compte ; l'extension se branche compte par compte, sa clé s'y crée ;
- **les réglages** listent les comptes : un compte est à toi, à elle ou à une personne qui a un compte — rien
  d'autre ; à qui est chaque compte est journalisé (ses outils le lisent) ;
- **la fiche d'une personne** a l'onglet « Teams » quand un compte est à elle (ses propriétaires : un compte sans
  propriétaire nommé), et seulement alors.
"""

from __future__ import annotations

import html
import re
import time

from mika.adapters.teams import TeamsConfig
from mika.app.settings import TEAMS_KEYS_KEY
from mika.app.teams import digest
from mika.contracts import runtime as rt
from mika.plugins.teams import params_of
from mika.ports.teams import Draft
from mika.runtime.operations import perform
from tests.protocol.test_drawn_pages import drawn
from tests.protocol.test_moi_mail import journal
from tests.protocol.test_teams_web import DM, batch, headers, new_key
from tests.protocol.test_web import bootstrap, world  # noqa: F401 — fixture partagée

BEA_DM = "19:bea_bob@unq.gbl.spaces"
SAVE = "/inspecteur/reglages/teams"


def post(client, path: str, data: dict):
    return client.post(path, data={"csrf": client.cookies.get("csrftoken"), **data})


def two_accounts(client, live) -> str:
    """Toi (``principal``) et Béa, qui a un compte (``bea_t``) ; rend la clé de personne de Béa."""
    bea = client.portal.call(lambda: live.accounts.create("bea", "un-mot-de-passe-long", operator=False,
                                                          full_name="Béa Martin"))
    owner = f"personne:{bea.handle}"
    client.portal.call(live.settings.save_teams, TeamsConfig(accounts={
        "principal": {"display_name": "Adrien"}, "bea_t": {"label": "Teams de Béa", "owner": owner,
                                                          "display_name": "Béa"}}))
    client.portal.call(live.reconfigure)
    return bea.handle


def test_two_keys_two_accounts_each_sees_only_its_own(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    two_accounts(client, live)
    mine, hers = new_key(client, live), new_key(client, live, "bea_t")
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(mine)).status_code == 202
    assert client.post("/api/teams/inbox", json=batch(conv=BEA_DM, text="Tu viens ?"),
                       headers=headers(hers)).status_code == 202
    store = live.kernel.ports["teams"]
    assert [m.text for m in client.portal.call(store.thread, "principal", DM, 10)] == ["On se voit à 14 h ?"]
    assert [m.text for m in client.portal.call(store.thread, "bea_t", BEA_DM, 10)] == ["Tu viens ?"]
    assert client.portal.call(store.thread, "principal", BEA_DM, 10) == []
    # une réponse dans le compte de Béa : sa file à elle, jamais la tienne ; ton extension ne peut pas l'accuser
    now = time.time_ns() // 1000
    d = client.portal.call(store.save_draft, Draft(id="", conversation=BEA_DM, body="J'arrive.", account="bea_t"))
    shown = client.portal.call(store.preview, d.id)
    assert client.portal.call(lambda: store.enqueue(d.id, mode="draft", digest=shown.digest,
                                                    expires_at=now + 3_600_000_000, now=now)) == ""
    assert client.get("/api/teams/outbox", headers=headers(mine)).json()["items"] == []
    [item] = client.get("/api/teams/outbox", headers=headers(hers)).json()["items"]
    assert item["id"] == d.id and item["conversation"] == BEA_DM
    assert client.post(f"/api/teams/outbox/{d.id}", json={"result": "placed"}, headers=headers(mine)).status_code == 404
    assert client.post(f"/api/teams/outbox/{d.id}", json={"result": "placed"}, headers=headers(hers)).status_code == 200
    # un compte décoché (« Actif ») : son extension est refusée, l'autre passe ; elle n'y propose plus rien
    cfg = client.portal.call(live.settings.teams)
    off = cfg.model_copy(update={"accounts": {**cfg.accounts,
                                              "bea_t": cfg.accounts["bea_t"].model_copy(update={"enabled": False})}})
    client.portal.call(live.settings.save_teams, off)
    client.portal.call(live.reconfigure)
    assert client.post("/api/teams/inbox", json=batch(conv=BEA_DM, text="Encore ?"),
                       headers=headers(hers)).status_code >= 400
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(mine)).status_code == 202
    assert params_of(live.kernel.mind.frame()).accounts_off == ("bea_t",)
    # retirer la clé de Béa ne ferme que sa porte
    client.portal.call(live.teams.revoke_key, "bea_t")
    assert client.get("/api/teams/outbox", headers=headers(hers)).status_code == 401
    assert client.get("/api/teams/outbox", headers=headers(mine)).status_code == 200
    # un compte retiré des réglages emporte sa clé
    again = new_key(client, live, "bea_t")
    client.portal.call(live.settings.save_teams, TeamsConfig(accounts={"principal": {}}))
    assert "bea_t" not in client.portal.call(live.settings.teams_keys)
    assert client.get("/api/teams/outbox", headers=headers(again)).status_code == 401


def test_the_single_key_of_before_is_the_principal_accounts(world):  # noqa: F811
    client, live, _ = world
    old = "mtk_la-cle-d-avant"
    client.portal.call(live.settings._put, TEAMS_KEYS_KEY,
                       {"digest": digest(old), "hint": old[:8], "created_at": 1, "by": "avant"})
    assert set(client.portal.call(live.settings.teams_keys)) == {"principal"}
    assert client.post("/api/teams/inbox", json=batch(), headers=headers(old)).status_code == 202
    store = live.kernel.ports["teams"]
    assert client.portal.call(store.configured, "principal")


def test_the_console_reads_by_owner_then_by_account(world):  # noqa: F811
    from mika.contracts import self_ as self_c

    client, live, _ = world
    bootstrap(client)
    handle = two_accounts(client, live)
    her = self_c.name_of(live.kernel.mind.frame().get(self_c.PERSONA))
    mine, hers = new_key(client, live), new_key(client, live, "bea_t")
    client.post("/api/teams/inbox", json=batch(), headers=headers(mine))
    client.post("/api/teams/inbox", json=batch(conv=BEA_DM, text="Tu viens ?"), headers=headers(hers))
    every = drawn(client, "/inspecteur/teams/conversations")
    chooser = every.split("Les comptes de", 1)[1].split("</nav>", 1)[0]
    assert "Tout le monde" in chooser and "Toi" in chooser and her in chooser and "Béa Martin" in chooser
    assert "On se voit à 14 h ?" in every and "Tu viens ?" in every and "Teams de Béa" in every  # deux comptes
    bea = drawn(client, f"/inspecteur/teams/conversations?qui=personne:{handle}")
    assert "Tu viens ?" in bea and "On se voit à 14 h ?" not in bea
    yours = drawn(client, "/inspecteur/teams/conversations?qui=toi")
    assert "On se voit à 14 h ?" in yours and "Tu viens ?" not in yours
    assert "Aucun compte Teams n'est à" in drawn(client, "/inspecteur/teams/conversations?qui=elle")
    one = drawn(client, "/inspecteur/teams/conversations?compte=bea_t")
    assert "Tu viens ?" in one and "On se voit à 14 h ?" not in one
    # l'extension : un compte par ligne, puis chacun la sienne, avec sa clé
    listing = drawn(client, "/inspecteur/teams/extension")
    assert "Comptes Teams" in listing and "?compte=bea_t" in listing
    page = drawn(client, f"/inspecteur/teams/extension?qui=personne:{handle}")
    assert "Ce compte Teams" in page and "Teams de Béa" in page
    assert "/inspecteur/action/teams.cle" in page and "/inspecteur/action/teams.retirer_cle" in page
    done = client.portal.call(lambda: perform(live.kernel, "teams.cle", {"_fixes": ["compte"], "compte": ["bea_t"]},
                                              by="user_1", nonce="cle-bea"))
    key = re.search(r"mtk_[\w-]+", done.message).group()
    assert done.ok and client.get("/api/teams/outbox", headers=headers(key)).status_code == 200
    assert client.get("/api/teams/outbox", headers=headers(hers)).status_code == 401  # l'ancienne ne vaut plus
    refused = client.portal.call(lambda: perform(live.kernel, "teams.cle",
                                                 {"_fixes": ["compte"], "compte": ["inconnu"]}, by="user_1",
                                                 nonce="cle-x"))
    assert not refused.ok and "inconnu" in refused.message
    # le refus dit où déclarer un compte : Teams › Paramètres, derrière la roue de Teams (ADR 0206) — pas l'ancienne
    # adresse sous Réglages, que le menu n'a plus (la même phrase répond à ``mika teams key``)
    assert "Teams › Paramètres" in refused.message and "Réglages" not in refused.message
    # une conversation de Béa a sa fiche, sous son compte
    fiche = drawn(client, f"/inspecteur/fiche/conversation_teams/bea_t~{BEA_DM}")
    assert "Tu viens ?" in fiche and "On se voit à 14 h ?" not in fiche


def test_an_account_belongs_to_you_to_her_or_to_a_person(world):  # noqa: F811
    from mika.contracts import self_ as self_c

    client, live, _ = world
    bootstrap(client)
    her = self_c.name_of(live.kernel.mind.frame().get(self_c.PERSONA))
    page = drawn(client, SAVE)
    assert "principal" in page  # ce qui était là : le compte d'avant, à toi
    form = drawn(client, f"{SAVE}?enregistrement=accounts&cle=&nouveau=1")
    assert "À qui" in form and f">{her}</option>" in form and ">Toi (ses propriétaires)</option>" in form
    account = {"_section": "teams", "_enregistrement": "accounts", "_ancienne": "", "_cle": "sien",
               "_champs": ["label", "owner", "display_name"], "label": "Le sien", "owner": "elle",
               "display_name": her}
    assert post(client, SAVE, account).status_code == 200
    refused = post(client, SAVE, {**account, "_cle": "autre", "owner": "personne:inconnue"})
    assert refused.status_code == 400 and "à une personne qui a un compte" in html.unescape(refused.text)
    saved = client.portal.call(live.settings.teams).accounts
    assert saved["sien"].owner == "elle" and saved["principal"].owner == "" and "autre" not in saved
    # le journal le sait : ses outils ne lui montreront que les comptes de qui est en face
    assert params_of(live.kernel.mind.frame()).owners == {"principal": "", "sien": "elle"}


def test_a_persons_fiche_has_its_teams_tab_only_when_an_account_is_hers(world):  # noqa: F811
    client, live, _ = world
    bootstrap(client)
    handle = two_accounts(client, live)
    cam = client.portal.call(lambda: live.accounts.create("cam", "un-mot-de-passe-long", operator=False,
                                                          full_name="Cam"))

    def text(url: str) -> str:
        return " ".join(re.sub(r"<[^>]+>", " ", drawn(client, url)).split())

    bea = text(f"/inspecteur/fiche/person/{handle}?onglet=teams")
    assert "Teams de Béa" in bea and "principal" not in bea and "Ses conversations" in bea
    you = drawn(client, "/inspecteur/fiche/person/user_1?onglet=teams")
    assert "principal" in you and "Teams de Béa" not in you
    assert "onglet=teams" not in drawn(client, f"/inspecteur/fiche/person/{cam.handle}")


def test_the_console_takes_a_key_back_and_its_audit_says_who(world):  # noqa: F811
    """K0-26 : ``revoke_key`` ne reçoit plus qui retire la clé ; le geste de la console reste au journal à son nom."""
    client, live, _ = world
    bootstrap(client)
    two_accounts(client, live)
    key = new_key(client, live, "bea_t")

    def take_back(nonce: str):
        return client.portal.call(lambda: perform(live.kernel, "teams.retirer_cle",
                                                  {"_fixes": ["compte"], "compte": ["bea_t"]}, by="user_1",
                                                  nonce=nonce))

    assert take_back("retrait").ok
    assert client.get("/api/teams/outbox", headers=headers(key)).status_code == 401
    assert not take_back("encore").ok  # il n'y a plus de clé
    done = [(e.data.action, e.data.by, e.data.outcome) for e in journal(live, rt.OPERATED)
            if e.data.action == "teams.retirer_cle"]
    assert ("teams.retirer_cle", "user_1", "done") in done
