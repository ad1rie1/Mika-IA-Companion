"""Les notifications du téléphone (ADR 0077) : le scellé et Firebase, sans réseau.

- le scellé ne s'ouvre qu'avec la clé du téléphone et pour cet usage (``AAD``), tient sous les 4 Kio de Firebase
  même pour un message long, et coupe le texte sur un caractère entier ;
- une clé de compte de service se lit ou se refuse en français ;
- le jeton d'accès vient d'une assertion RS256 vérifiable avec la clé publique du compte, et se garde jusqu'à sa
  fin ; un 401 en redemande un, une fois ; un jeton de téléphone mort (404, ``UNREGISTERED``) est ``GONE`` ;
- sans clé, rien ne part (et rien n'est appelé) ;
- la règle : une parole dans le fil, avec du texte, jamais une pensée ni le sort d'une question ; la réponse à
  une question posée d'un navigateur ne notifie pas, celle posée du téléphone si ; un téléphone connecté reçoit
  par sa connexion.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from mika.adapters.push import fcm, seal
from mika.adapters.web.accounts import PushRegistration, account_of_handle
from mika.adapters.web.push import recipients, wanted
from mika.ports.delivery import REPLY_ABSTAINED, Delivery
from mika.vocab import voice

KEY = bytes(range(32))


def _b64url_decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


@pytest.fixture(scope="module")
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def service_account(private_key) -> str:
    pem = private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
    return json.dumps({"type": "service_account", "project_id": "mika-test", "private_key_id": "k1",
                       "private_key": pem, "client_email": "mika@mika-test.iam.gserviceaccount.com",
                       "token_uri": "https://oauth2.googleapis.com/token"})


# ── le scellé ──

def test_seal_round_trip_and_bound_to_its_use() -> None:
    body = seal.payload(message_id=42, text="coucou toi", ts_ms=1_700_000_000_000, files=1)
    data = seal.seal(KEY, body)
    assert set(data) == {"v", "n", "c"} and data["v"] == "1"
    assert seal.unseal(KEY, data) == {"t": "speech", "id": 42, "text": "coucou toi", "ts": 1_700_000_000_000,
                                      "files": 1}
    with pytest.raises(Exception):  # noqa: B017 — une autre clé n'ouvre rien
        seal.unseal(bytes(32), data)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = AESGCM(KEY)
    with pytest.raises(Exception):  # noqa: B017 — un chiffré sans ces données associées ne s'ouvre pas
        raw.decrypt(base64.b64decode(data["n"]), base64.b64decode(data["c"]), b"autre")


def test_two_seals_of_the_same_message_differ() -> None:
    body = seal.payload(message_id=1, text="même", ts_ms=0)
    assert seal.seal(KEY, body)["n"] != seal.seal(KEY, body)["n"]


def test_a_long_message_fits_firebase() -> None:
    text = "é" * 5000 + "🙂" * 100
    body = seal.payload(message_id=10**9, text=text, ts_ms=10**13, files=5)
    assert len(body["text"].encode()) <= seal.TEXT_MAX_BYTES and body["text"].endswith(seal.ELLIPSIS)
    data = seal.seal(KEY, body)
    assert sum(len(k) + len(v) for k, v in data.items()) < 4000  # Firebase : 4 Kio de données au plus


def test_clip_cuts_on_a_whole_character() -> None:
    assert seal.clip("abc", 10) == "abc"
    cut = seal.clip("éééé", 6)  # 8 octets → 3 pour « … », il reste 3 : un « é » entier
    assert cut == "é…" and len(cut.encode()) <= 6
    assert seal.clip("abcdef", 2) == "" and seal.clip("abcdef", 0) == ""  # pas même la place de « … »


@pytest.mark.parametrize("text", ["\n" * 3000, '"' * 3000, "\x01" * 3000, "é\n" * 2000, "\\" * 3000])
def test_escapes_are_counted_before_firebase_refuses(text: str) -> None:
    """Un saut de ligne, un guillemet coûtent deux octets en JSON, un caractère de contrôle six : la taille se mesure
    sur le clair sérialisé."""
    body = seal.payload(message_id=10**9, text=text, ts_ms=10**13, files=5)
    assert len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()) <= seal.PLAIN_MAX_BYTES
    data = seal.seal(KEY, body)
    assert sum(len(k) + len(v) for k, v in data.items()) < 4000


@pytest.mark.parametrize("bad", ["", "pas du base64 !", base64.b64encode(b"court").decode()])
def test_a_bad_key_is_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        seal.key_from(bad)


def test_a_key_is_32_bytes_of_base64() -> None:
    assert seal.key_from(base64.b64encode(KEY).decode()) == KEY


# ── la clé du compte de service ──

@pytest.mark.parametrize(("text", "says"), [
    ("{", "JSON"),
    (json.dumps({"type": "authorized_user"}), "compte de service"),
    (json.dumps({"type": "service_account", "project_id": "p"}), "client_email"),
    (json.dumps({"type": "service_account", "project_id": "p", "client_email": "e", "private_key": "x"}),
     "ne se lit pas"),
])
def test_a_bad_service_account_is_refused_in_french(text: str, says: str) -> None:
    with pytest.raises(ValueError, match=says):
        fcm.parse_service_account(text)


def test_a_service_account_reads(service_account: str) -> None:
    account = fcm.parse_service_account(service_account)
    assert (account.project_id, account.key_id) == ("mika-test", "k1")


# ── Firebase ──

class Google:
    """Les deux points de Google : le jeton d'accès, puis l'envoi."""

    def __init__(self, sends: list[tuple[int, dict[str, Any]]] | None = None) -> None:
        self.sends = list(sends or [])
        self.assertions: list[str] = []
        self.messages: list[dict[str, Any]] = []
        self.auth: list[str] = []
        self.issued = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            assert form["grant_type"] == "urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer"
            self.assertions.append(form["assertion"])
            self.issued += 1
            return httpx.Response(200, json={"access_token": f"acces-{self.issued}", "expires_in": 3600})
        assert request.url.path == "/v1/projects/mika-test/messages:send"
        self.auth.append(request.headers["authorization"])
        self.messages.append(json.loads(request.content))
        status, body = self.sends.pop(0) if self.sends else (200, {"name": "ok"})
        return httpx.Response(status, json=body)


def sender(service_account: str, google: Google, clock: list[float]) -> fcm.FcmSender:
    return fcm.FcmSender(lambda: service_account, now=lambda: clock[0],
                         client=httpx.AsyncClient(transport=httpx.MockTransport(google)))


async def test_sends_a_high_priority_data_message_with_a_verifiable_assertion(service_account, private_key) -> None:
    google, clock = Google(), [1_000_000.0]
    result = await sender(service_account, google, clock).send("tel-1", {"v": "1", "n": "a", "c": "b"})
    assert result.outcome == fcm.SENT
    assert google.messages == [{"message": {"token": "tel-1", "data": {"v": "1", "n": "a", "c": "b"},
                                            "android": {"priority": "HIGH"}}}]
    head, claims, sig = google.assertions[0].split(".")
    private_key.public_key().verify(_b64url_decode(sig), f"{head}.{claims}".encode(), padding.PKCS1v15(),
                                    hashes.SHA256())
    assert json.loads(_b64url_decode(head)) == {"alg": "RS256", "typ": "JWT", "kid": "k1"}
    got = json.loads(_b64url_decode(claims))
    assert got["iss"] == "mika@mika-test.iam.gserviceaccount.com" and got["scope"] == fcm.SCOPE
    assert got["aud"] == "https://oauth2.googleapis.com/token" and got["exp"] - got["iat"] == 3600


async def test_the_access_token_is_kept_until_its_end(service_account) -> None:
    google, clock = Google(), [1_000_000.0]
    s = sender(service_account, google, clock)
    await s.send("t", {})
    clock[0] += 3000
    await s.send("t", {})
    assert google.issued == 1 and google.auth == ["Bearer acces-1"] * 2
    clock[0] += 600  # à moins d'une minute de sa fin : un neuf
    await s.send("t", {})
    assert google.issued == 2 and google.auth[-1] == "Bearer acces-2"


async def test_a_refused_access_is_asked_again_once(service_account) -> None:
    google = Google([(401, {"error": {"status": "UNAUTHENTICATED"}}), (200, {})])
    result = await sender(service_account, google, [0.0]).send("t", {})
    assert result.outcome == fcm.SENT and google.issued == 2
    google = Google([(403, {"error": {"status": "PERMISSION_DENIED"}})] * 2)
    result = await sender(service_account, google, [0.0]).send("t", {})
    assert result.outcome == fcm.FAILED and len(google.messages) == 2


@pytest.mark.parametrize(("status", "body"), [
    (404, {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}),
    (400, {"error": {"status": "INVALID_ARGUMENT", "details": [{"errorCode": "UNREGISTERED"}]}}),
])
async def test_a_dead_phone_token_is_gone(service_account, status: int, body: dict[str, Any]) -> None:
    result = await sender(service_account, Google([(status, body)]), [0.0]).send("t", {})
    assert result.outcome == fcm.GONE


async def test_a_key_from_another_project_forgets_no_phone(service_account) -> None:
    """``SENDER_ID_MISMATCH`` : la clé du serveur n'est pas celle du projet de l'application — une erreur de
    configuration ; oublier les téléphones les laisserait muets une fois la clé corrigée."""
    body = {"error": {"status": "PERMISSION_DENIED", "details": [{"errorCode": "SENDER_ID_MISMATCH"}]}}
    result = await sender(service_account, Google([(403, body)] * 2), [0.0]).send("t", {})
    assert result.outcome == fcm.FAILED and "projet" in result.detail


async def test_an_oauth_refusal_is_a_failure_not_a_crash(service_account) -> None:
    """Google répond ``{"error": "invalid_grant"}`` (une chaîne) : clé supprimée, horloge décalée."""

    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant", "error_description": "Invalid JWT Signature."})

    s = fcm.FcmSender(lambda: service_account, client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
    result = await s.send("t", {})
    assert result.outcome == fcm.FAILED and "invalid_grant" in result.detail


async def test_a_server_error_fails_without_retry(service_account) -> None:
    google = Google([(503, {"error": {"status": "UNAVAILABLE"}})])
    result = await sender(service_account, google, [0.0]).send("t", {})
    assert result.outcome == fcm.FAILED and "503" in result.detail and len(google.messages) == 1


async def test_without_a_key_nothing_is_called() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("aucun appel sans clé")

    s = fcm.FcmSender(lambda: "", client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
    assert not s.configured()
    assert (await s.send("t", {})).outcome == fcm.UNCONFIGURED
    broken = fcm.FcmSender(lambda: "{", client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
    assert not broken.configured() and (await broken.send("t", {})).outcome == fcm.UNCONFIGURED


# ── la règle ──

def said(**kw: Any) -> Delivery:
    base: dict[str, Any] = {"key": "k", "target": "user_3", "channel": "mobile", "room": None, "text": "coucou",
                            "message_id": 12}
    return Delivery(**(base | kw))


PHONE = "token:7"


@pytest.mark.parametrize(("d", "asked", "expected"), [
    (said(), None, True),  # elle écrit la première
    (said(text="[SIGH] coucou [PAUSE:300]"), None, True),
    (said(persona=voice.INNER), None, False),  # une pensée à voix haute
    (said(kind=REPLY_ABSTAINED), None, False),  # le sort d'une question
    (said(message_id=0), None, False),  # hors du fil
    (said(text="[SIGH]"), None, False),  # rien à lire
    (said(target="conscience_mika"), None, False),
    (said(target=None), None, False),
    (said(client_msg_id="m1"), "s3ss10n-web", False),  # posée d'un navigateur : lue là-bas
    (said(client_msg_id="m1"), "", False),  # posée d'une connexion sans session
    (said(client_msg_id="m1"), PHONE, True),  # posée du téléphone, qui a fermé depuis
])
def test_what_deserves_a_notification(d: Delivery, asked: str | None, expected: bool) -> None:
    assert wanted(d, asked_session=asked, registered=[PHONE]) is expected


def test_a_connected_phone_receives_by_its_connection() -> None:
    regs = [PushRegistration(7, "a", "k"), PushRegistration(8, "b", "k")]
    assert [r.token_id for r in recipients(regs, ["token:7", "web-session"])] == [8]
    assert recipients(regs, ["token:7", "token:8"]) == []


@pytest.mark.parametrize(("handle", "account"), [("user_3", 3), ("user_", None), ("user_x", None),
                                                 ("ext_12", None), (None, None), ("anon_ab", None)])
def test_only_an_account_address_has_phones(handle: str | None, account: int | None) -> None:
    assert account_of_handle(handle) == account
