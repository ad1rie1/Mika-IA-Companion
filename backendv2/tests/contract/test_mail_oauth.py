"""Une boîte Microsoft (Hotmail, Outlook.com) : OAuth2 et XOAUTH2 (ADR 0166), contre un faux Microsoft (le point
OAuth2, par ``httpx.MockTransport``) et les faux serveurs IMAP et SMTP.

- se connecter : un code à entrer chez Microsoft, attendu en tâche de fond ; la connexion gardée ; puis la boîte
  se relève et envoie par ``XOAUTH2``, jamais par mot de passe ;
- le jeton d'accès se renouvelle avant d'expirer, et le jeton de renouvellement que Microsoft remplace est gardé ;
- une connexion que Microsoft ne renouvelle plus n'est plus présentée, et la fiche dit de se reconnecter ; changer
  d'application aussi ; un nouveau code qui n'aboutit pas ne la rend pas valable ;
- un jeton refusé par le serveur échoue comme un serveur qui refuse (lecture et envoi), sans rester suspendu ;
- la connexion est scellée dans les réglages, et part avec sa boîte ;
- l'application et l'annuaire sont vérifiés avant d'entrer dans l'adresse de Microsoft.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl

import httpx
import pytest

from mika.adapters.mail import ImapSmtpMail, MailAccount, MailConfig
from mika.adapters.mail.oauth import DEVICE_GRANT, EXPIRED, REVOKED, Grant, MicrosoftSignIn, OAuthError
from mika.adapters.store_sql import SqlStore
from mika.app.settings import MAIL_GRANTS_KEY, SecretBox, Settings
from mika.ports.mail import SIGNED_IN, SIGNIN_NEEDED, SIGNIN_PENDING, SignIn
from tests.fixtures.mail_servers import Imap, Smtp, raw_mail, serve

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)
CLIENT = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


class Microsoft:
    """Le point OAuth2 de Microsoft : un code d'appareil, des jetons, et ce qu'on lui a demandé."""

    def __init__(self, *, pending: int = 1, access: str = "acces") -> None:
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.pending = pending
        self.access = access
        self.issued = 0
        self.revoked = False
        self.declined = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        data = dict(parse_qsl(request.content.decode()))
        parts = request.url.path.strip("/").split("/")
        self.calls.append((parts[0], parts[-1], data))
        if parts[-1] == "devicecode":
            return httpx.Response(200, json={"device_code": "appareil-1", "user_code": "ABCD-EFGH", "expires_in": 900,
                                             "interval": 5, "verification_uri": "https://microsoft.com/devicelogin"})
        if data.get("grant_type") == DEVICE_GRANT:
            if self.declined:
                return httpx.Response(400, json={"error": "authorization_declined"})
            if self.pending:
                self.pending -= 1
                return httpx.Response(400, json={"error": "authorization_pending"})
            return self._tokens()
        if self.revoked:
            return httpx.Response(400, json={"error": "invalid_grant",
                                             "error_description": "AADSTS70000: The refresh token has expired."})
        return self._tokens()

    def _tokens(self) -> httpx.Response:
        self.issued += 1
        return httpx.Response(200, json={"access_token": f"{self.access}-{self.issued}" if self.access != "refuse"
                                         else "refuse", "refresh_token": f"renouv-{self.issued}",
                                         "expires_in": 3600, "token_type": "Bearer"})


class Vault:
    """Où les connexions se gardent (en vrai : les réglages, scellées)."""

    def __init__(self, **grants: Grant) -> None:
        self.grants = dict(grants)

    def mail_grant(self, account: str) -> Grant | None:
        return self.grants.get(account)

    async def save_mail_grant(self, account: str, grant: Grant) -> None:
        self.grants[account] = grant


async def _no_wait(_seconds: float) -> None:
    await asyncio.sleep(0)


def signin(vault: Vault, microsoft: Microsoft, clock: list[datetime] | None = None) -> MicrosoftSignIn:
    clock = clock if clock is not None else [NOW]
    return MicrosoftSignIn(vault, now=lambda: clock[0], transport=httpx.MockTransport(microsoft), sleep=_no_wait)


@pytest.fixture
def servers():
    Imap.reset({3: raw_mail(3, "Coucou", "Tu viens samedi ?")})
    Smtp.received = []
    imap, smtp = serve(Imap), serve(Smtp)
    yield imap.server_address[1], smtp.server_address[1]
    imap.shutdown()
    smtp.shutdown()


def hotmail(imap_port: int = 1, smtp_port: int = 1, **more) -> MailAccount:
    base = dict(auth="microsoft", oauth_client_id=CLIENT, address="moi@hotmail.fr", imap_host="127.0.0.1",
                imap_port=imap_port, imap_ssl=False, user="moi@hotmail.fr", smtp_host="127.0.0.1",
                smtp_port=smtp_port, smtp_security="none", since_days=7)
    return MailAccount(**{**base, **more})


def box_for(tmp_path, account: MailAccount, microsoft: MicrosoftSignIn) -> ImapSmtpMail:
    return ImapSmtpMail(lambda: MailConfig(accounts={"hotmail": account}), tmp_path / "mail.db", now=lambda: NOW,
                        tz=UTC, microsoft=microsoft)


async def _settled(box: ImapSmtpMail, key: str) -> None:
    for _ in range(200):
        if box.signin(key).state != SIGNIN_PENDING:
            return
        await asyncio.sleep(0)
    raise AssertionError("la connexion attend encore")


def test_a_microsoft_box_signs_in_by_a_code_then_reads_and_sends_by_xoauth2(tmp_path, servers):
    vault, microsoft = Vault(), Microsoft(pending=2)
    box = box_for(tmp_path, hotmail(*servers), signin(vault, microsoft))
    assert box.signin("hotmail").state == SIGNIN_NEEDED and box.signin("hotmail").error == ""

    async def scenario():
        started = await box.start_signin("hotmail")
        assert started.state == SIGNIN_PENDING and started.code == "ABCD-EFGH"
        assert started.url == "https://microsoft.com/devicelogin" and started.until > 0
        await _settled(box, "hotmail")
        got = await box.fetch_new(10)
        await box.send("bob@exemple.fr", "Salut", "Ça marche.", account="hotmail")
        return got

    [mail] = asyncio.run(scenario())
    assert box.signin("hotmail").state == SIGNED_IN
    assert vault.grants["hotmail"] == Grant("renouv-1", CLIENT, "consumers")
    tenant, endpoint, asked = microsoft.calls[0]
    assert (tenant, endpoint, asked["client_id"]) == ("consumers", "devicecode", CLIENT)
    assert set(asked["scope"].split()) == {"offline_access", "https://outlook.office.com/IMAP.AccessAsUser.All",
                                           "https://outlook.office.com/SMTP.Send"}
    assert [c[2]["grant_type"] for c in microsoft.calls[1:]] == [DEVICE_GRANT] * 3  # deux « pas encore », puis oui
    assert mail.subject == "Coucou" and mail.account == "hotmail"
    # le relevé, puis la copie rangée dans « Envoyés » : toujours par XOAUTH2, jamais par mot de passe
    assert set(Imap.bearers) == {("moi@hotmail.fr", "acces-1")} and Imap.logins == []
    assert "auth=Bearer acces-1" in Smtp.received[-1][3] and "moi@hotmail.fr" in Smtp.received[-1][3]


def test_an_access_token_is_renewed_before_it_expires_and_the_replaced_refresh_token_is_kept():
    clock, vault, microsoft = [NOW], Vault(hotmail=Grant("renouv-0", CLIENT, "consumers")), Microsoft()
    oauth = signin(vault, microsoft, clock)

    async def scenario():
        first = await oauth.token("hotmail", hotmail())
        again = await oauth.token("hotmail", hotmail())  # encore valable : gardé en mémoire
        clock[0] = NOW + timedelta(seconds=3400)  # moins de cinq minutes avant sa fin : renouvelé
        later = await oauth.token("hotmail", hotmail())
        return first, again, later

    assert asyncio.run(scenario()) == ("acces-1", "acces-1", "acces-2")
    assert [c[2]["refresh_token"] for c in microsoft.calls] == ["renouv-0", "renouv-1"]
    assert vault.grants["hotmail"] == Grant("renouv-2", CLIENT, "consumers")


def test_a_connection_microsoft_no_longer_renews_is_not_presented_again(tmp_path, servers):
    vault, microsoft = Vault(hotmail=Grant("renouv-0", CLIENT, "consumers")), Microsoft()
    microsoft.revoked = True
    box = box_for(tmp_path, hotmail(*servers), signin(vault, microsoft))
    ok, said = asyncio.run(box.test("hotmail"))
    assert not ok and REVOKED in said and said.startswith("Connexion Microsoft : ")
    assert box.status("hotmail").error and box.signin("hotmail").state == SIGNIN_NEEDED
    assert box.signin("hotmail").error == REVOKED
    assert asyncio.run(box.fetch_new(10)) == [] and REVOKED in box.status("hotmail").error
    assert len(microsoft.calls) == 1  # une seule fois : on ne lui représente pas ce qu'il a refusé
    assert Imap.bearers == [] and Imap.logins == []
    with pytest.raises(OAuthError):
        asyncio.run(box.send("bob@exemple.fr", "Salut", "Ça marche.", account="hotmail"))
    assert Smtp.received == []


def test_another_application_asks_to_sign_in_again():
    vault, microsoft = Vault(hotmail=Grant("renouv-0", "ffffffff-4e5f-4a6b-8c7d-9e0f1a2b3c4d", "consumers")), Microsoft()
    oauth = signin(vault, microsoft)
    assert oauth.state("hotmail", hotmail()).state == SIGNIN_NEEDED
    with pytest.raises(OAuthError, match="pas encore connectée"):
        asyncio.run(oauth.token("hotmail", hotmail()))
    assert oauth.state("hotmail", hotmail(oauth_client_id="")).error.startswith("aucune application")
    assert microsoft.calls == []


def _wait_for(oauth: MicrosoftSignIn, microsoft: Microsoft, clock: list[datetime], *, late: bool = False) -> None:
    async def scenario():
        await oauth.start("hotmail", hotmail())
        if late:
            clock[0] = NOW + timedelta(seconds=901)  # le code vaut un quart d'heure
        for _ in range(50):
            await asyncio.sleep(0)

    asyncio.run(scenario())


def test_a_declined_or_expired_code_says_so_and_keeps_the_old_connection():
    clock, vault, microsoft = [NOW], Vault(), Microsoft()
    microsoft.declined = True
    oauth = signin(vault, microsoft, clock)
    _wait_for(oauth, microsoft, clock)
    assert oauth.state("hotmail", hotmail()).error == "la connexion a été refusée chez Microsoft"
    assert vault.grants == {}
    clock, slow = [NOW], Microsoft(pending=1000)
    oauth = signin(vault, slow, clock)
    _wait_for(oauth, slow, clock, late=True)
    assert oauth.state("hotmail", hotmail()) == SignIn(SIGNIN_NEEDED, error=EXPIRED)
    clock, vault = [NOW], Vault(hotmail=Grant("renouv-0", CLIENT, "consumers"))
    oauth = signin(vault, microsoft, clock)
    _wait_for(oauth, microsoft, clock)
    assert oauth.state("hotmail", hotmail()) == SignIn(SIGNED_IN)  # l'ancienne connexion vaut toujours
    assert vault.grants["hotmail"].refresh == "renouv-0"


def test_a_new_code_that_expires_leaves_a_revoked_connection_revoked():
    clock, vault, microsoft = [NOW], Vault(hotmail=Grant("renouv-0", CLIENT, "consumers")), Microsoft(pending=1000)
    microsoft.revoked = True
    oauth = signin(vault, microsoft, clock)
    with pytest.raises(OAuthError):
        asyncio.run(oauth.token("hotmail", hotmail()))
    _wait_for(oauth, microsoft, clock, late=True)
    assert oauth.state("hotmail", hotmail()) == SignIn(SIGNIN_NEEDED, error=EXPIRED)  # pas « connectée »
    with pytest.raises(OAuthError, match="ne renouvelle plus"):
        asyncio.run(oauth.token("hotmail", hotmail()))
    assert sum(c[2].get("grant_type") == "refresh_token" for c in microsoft.calls) == 1


def test_a_token_the_server_refuses_fails_like_a_refusing_server(tmp_path, servers):
    vault, microsoft = Vault(hotmail=Grant("renouv-0", CLIENT, "consumers")), Microsoft(access="refuse")
    box = box_for(tmp_path, hotmail(*servers), signin(vault, microsoft))
    ok, said = asyncio.run(box.test("hotmail"))
    assert not ok and "Lecture : échec" in said and "connexion refusée" in said
    assert "envoi : échec" in said and "535" in said
    assert Imap.bearers == [] and Smtp.received == []


def test_a_password_box_has_no_microsoft_connection(tmp_path, servers):
    box = box_for(tmp_path, hotmail(*servers, auth="password", password="secret"), signin(Vault(), Microsoft()))
    assert box.signin("hotmail") is None
    with pytest.raises(ValueError):
        asyncio.run(box.start_signin("hotmail"))
    assert asyncio.run(box.test("hotmail"))[0] and Imap.logins == [("moi@hotmail.fr", "secret")]


def test_the_connection_is_kept_sealed_and_leaves_with_its_box(tmp_path):
    async def scenario():
        store = SqlStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
        await store.open()
        try:
            settings = Settings(store, SecretBox.for_data(tmp_path))
            await settings.open()
            await settings.save_email(MailConfig(accounts={"hotmail": hotmail(), "autre": hotmail()}))
            await settings.save_mail_grant("hotmail", Grant("renouv-secret", CLIENT, "consumers"))
            await settings.save_mail_grant("autre", Grant("renouv-autre", CLIENT, "consumers"))
            rows = [r[0] for r in store.query_mind("SELECT value FROM settings")]
            kept = settings.mail_grant("hotmail")
            # « autre » reprend un mot de passe, « hotmail » reste : seule la connexion d'« hotmail » demeure
            await settings.save_email(MailConfig(accounts={"hotmail": hotmail(),
                                                           "autre": hotmail(auth="password")}))
            after = settings.mail_grant("hotmail"), settings.mail_grant("autre")
            await settings.save_email(MailConfig(accounts={}))  # la boîte retirée : sa connexion part avec elle
            return rows, kept, after, settings.mail_grant("hotmail"), settings._get(MAIL_GRANTS_KEY)
        finally:
            await store.close()

    rows, kept, after, gone, stored = asyncio.run(scenario())
    assert all("renouv-secret" not in r for r in rows)  # scellé, jamais en clair dans mind.db
    assert kept == Grant("renouv-secret", CLIENT, "consumers")
    assert after == (kept, None) and gone is None and stored == {}


def test_the_application_and_the_directory_are_checked():
    assert hotmail(oauth_client_id=CLIENT.upper()).oauth_client_id == CLIENT
    assert hotmail(oauth_tenant="  ").oauth_tenant == "consumers"
    assert hotmail(oauth_tenant="contoso.onmicrosoft.com").oauth_tenant == "contoso.onmicrosoft.com"
    for bad in ({"oauth_client_id": "pas-un-guid"}, {"oauth_tenant": "consumers/../x"},
                {"oauth_tenant": "a?b=c"}):
        with pytest.raises(ValueError):
            hotmail(**bad)
    details = dict(hotmail().details())
    assert "mot de passe" not in details and CLIENT in details["connexion"]
    assert dict(hotmail(auth="password").details())["mot de passe"] == "aucun"
