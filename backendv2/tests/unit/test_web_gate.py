"""La machinerie des portes à clé (ADR 0213) : empreintes, fenêtres glissantes, nettoyage, une table de statuts,
et la session du transport web, lue une seule fois."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace as NS

import pytest
from starlette.requests import Request

from mika.adapters.web import app as web_app
from mika.adapters.web import protocol, session
from mika.adapters.web.app import GATE_STATUS, LoginThrottle, gate_reply
from mika.adapters.web.gate import (
    KEY_MAX,
    NOTHING,
    SlidingWindow,
    clean_fields,
    clean_text,
    matches,
    new_key,
    one_line,
    plausible_ms,
    presented,
    token_digest,
)
from mika.ports import gate, phone, teams, wakeup


class Tick:
    """Une horloge qu'on avance à la main."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_an_empty_wanted_digest_never_opens():
    """Rien d'attendu ne s'ouvre, pas même une clé vide, dont l'empreinte est justement ``NOTHING``."""
    assert not matches(NOTHING, "") and not matches(token_digest("x"), "")
    assert matches(token_digest("x"), token_digest("x")) and not matches(token_digest("y"), token_digest("x"))


def test_a_presented_key_has_the_shape_of_the_keys_of_its_door():
    assert presented("mtk_abc", "mtk_") == hashlib.sha256(b"mtk_abc").hexdigest()
    assert presented("mw_abc", "mtk_") == NOTHING  # une clé d'ailleurs
    assert presented("mtk_" + "a" * KEY_MAX, "mtk_") == NOTHING  # trop longue pour en être une


def test_a_new_key_carries_its_prefix_and_is_never_the_same():
    assert new_key("mwk_").startswith("mwk_") and len(new_key("mwk_")) > 40 and new_key() != new_key()


def test_allow_judges_and_counts_in_one_gesture():
    tick = Tick()
    w = SlidingWindow(2, 60.0, monotonic=tick)
    assert w.allow() and w.allow() and not w.allow()
    assert w.wait_s() == 60
    tick.now += 59.5
    assert not w.allow() and w.wait_s() == 1  # jamais 0 : un Retry-After dit d'attendre
    tick.now += 0.5
    assert w.allow()


def test_allow_takes_the_time_it_is_given():
    """Le hub et le monde passent leur horloge à chaque appel."""
    w = SlidingWindow(1, 10.0)
    assert w.allow(100.0) and not w.allow(109.0) and w.allow(110.0)


def test_each_key_has_its_window():
    w = SlidingWindow(1, 60.0, monotonic=Tick())
    assert w.allow(key="a") and w.allow(key="b") and not w.allow(key="a")


def test_the_ceiling_can_be_that_of_the_call():
    """Le plafond d'un réveil se règle réveil par réveil."""
    w = SlidingWindow(1, 3600.0, monotonic=Tick())
    w.fail("serre")
    w.fail("serre")
    assert w.blocked("serre") and w.blocked("serre", n=2) and not w.blocked("serre", n=3)
    assert w.allow(key="serre", n=3) and not w.allow(key="serre", n=3)


def test_failures_count_apart_and_a_success_gives_its_try_back():
    tick = Tick()
    w = LoginThrottle(2, 60.0, monotonic=tick)
    w.fail("ip")
    assert not w.blocked("ip")
    w.fail("ip")
    assert w.blocked("ip")
    w.forgive("ip")
    assert not w.blocked("ip")
    w.forgive("ip")
    assert len(w) == 0  # une clé vide est oubliée
    w.forgive("ip")  # rien à rendre : sans effet


def test_emptied_keys_are_forgotten_and_memory_is_bounded(monkeypatch):
    tick = Tick()
    monkeypatch.setattr(SlidingWindow, "MAX_KEYS", 3)
    w = SlidingWindow(5, 60.0, monotonic=tick)
    for key in "abcd":
        w.fail(key)
    assert len(w) == 3 and not w.blocked("a") and len(w) == 3  # la plus ancienne est partie
    tick.now += 60
    assert not w.blocked("b") and len(w) == 2


def test_keep_forgets_the_keys_that_are_gone():
    w = SlidingWindow(1, 60.0, monotonic=Tick())
    w.fail("serre")
    w.fail("retire")
    w.keep({"serre": object()})
    assert not w.blocked("retire") and w.blocked("serre")


def test_the_two_old_names_are_the_same_window():
    assert protocol.RateLimiter is SlidingWindow and LoginThrottle is SlidingWindow


def test_what_arrives_from_outside_is_cleaned():
    half = "a\ud83d"  # la moitié d'un emoji, coupé par la borne d'un client
    assert clean_text("a\x00b") == "ab" and clean_text(half) == "a?"
    assert one_line("  Léa\n\t Dupont\x07 ", 120) == "Léa Dupont" and one_line("abcdef", 3) == "abc"
    assert clean_fields({"text": half, "time": 3}) == {"text": "a?", "time": 3}
    assert clean_fields(["pas un objet"]) == ["pas un objet"]


def test_a_plausible_date():
    now = 1_800_000_000_000
    assert plausible_ms(now, now) and plausible_ms(now + 86_400_000, now) and plausible_ms(1_420_070_400_000, now)
    assert not plausible_ms(1_420_070_399_999, now) and not plausible_ms(now + 86_400_001, now)


def test_every_outcome_has_its_status_and_the_ports_share_them():
    outcomes = {v for k, v in vars(gate).items() if k.isupper()}
    assert set(GATE_STATUS) == outcomes
    assert phone.GateResult is teams.GateResult is wakeup.GateResult is gate.GateResult
    assert teams.KeyState is wakeup.KeyState is gate.KeyState
    assert teams.ACCEPTED == phone.ACCEPTED == gate.ACCEPTED
    assert phone.IGNORED == "ignored"  # le sort d'une réponse proposée : pas une issue de porte, il reste au port


@pytest.mark.parametrize(("got", "accepted", "status", "body"), [
    (gate.GateResult(gate.ACCEPTED, "Reçu.", data={"call": 7}), 202, 202, {"ok": True, "call": 7}),
    (gate.GateResult(gate.IGNORED, data={"call": None}), 202, 200, {"ok": True, "call": None}),
    (gate.GateResult(gate.ACCEPTED, data={"status": "parti"}), 200, 200, {"ok": True, "status": "parti"}),
    (gate.GateResult(gate.UNKNOWN, "Clé refusée."), 200, 401, {"error": "Clé refusée."}),
    (gate.GateResult(gate.REFUSED), 202, 409, {"error": "Refusé."}),
    (gate.GateResult("inconnue"), 200, 400, {"error": "Refusé."}),
])
def test_a_gate_says_its_decision_in_http(got, accepted, status, body):
    reply = gate_reply(got, {"Cache-Control": "no-store"}, accepted=accepted)
    assert reply.status_code == status and reply.headers["cache-control"] == "no-store"
    assert reply.body == gate_reply(got, {}, accepted=accepted).body
    assert json.loads(reply.body) == body


def test_a_busy_gate_says_when_to_come_back_and_leaves_the_headers_it_got():
    headers = {"Cache-Control": "no-store"}
    reply = gate_reply(gate.GateResult(gate.BUSY, "Trop de requêtes.", retry_after=12), headers)
    assert reply.status_code == 429 and reply.headers["retry-after"] == "12" and "Retry-After" not in headers


def _request(*, cookies: str = "", **headers: str) -> Request:
    raw = [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]
    if cookies:
        raw.append((b"cookie", cookies.encode()))
    return Request({"type": "http", "headers": raw})


ACCOUNTS = NS(token=lambda raw: ("du jeton", 1) if raw == "mw_bon" else None,
              session=lambda key: "de la session" if key == "cle" else None)


def test_a_native_client_is_read_by_its_token_a_browser_by_its_session():
    bearer = "Bearer mw_bon"
    assert session.account_of(_request(authorization=bearer), ACCOUNTS) == "du jeton"
    assert session.account_of(_request(authorization="Bearer mw_faux"), ACCOUNTS) is None
    assert session.account_of(_request(cookies="sessionid=cle"), ACCOUNTS) == "de la session"
    # un mauvais jeton ne se rattrape pas par une session, et une ``Origin`` ne fait pas valoir un jeton
    assert session.account_of(_request(authorization="Bearer mw_faux", cookies="sessionid=cle"), ACCOUNTS) is None
    assert session.account_of(_request(authorization=bearer, origin="http://x", cookies="sessionid=cle"),
                              ACCOUNTS) == "de la session"
    assert session.account_of(_request(authorization=bearer, origin="http://x"), ACCOUNTS) is None


def test_the_csrf_header_must_be_the_cookie_and_there_must_be_one():
    assert session.csrf_header_ok(_request(x_csrftoken="abc", cookies="csrftoken=abc"))
    assert not session.csrf_header_ok(_request(x_csrftoken="abd", cookies="csrftoken=abc"))
    assert not session.csrf_header_ok(_request(cookies="csrftoken=abc"))
    assert not session.csrf_header_ok(_request(x_csrftoken="abc"))
    assert not session.csrf_header_ok(_request())


def test_the_web_app_still_lends_the_names_others_read():
    """L'API par personne, le monde et la console lisent encore ces noms depuis ``adapters/web/app.py``."""
    assert web_app.SESSION_COOKIE is session.SESSION_COOKIE and web_app.CSRF_COOKIE is session.CSRF_COOKIE
    assert web_app.bearer is session.bearer and web_app.native_token is session.native_token
