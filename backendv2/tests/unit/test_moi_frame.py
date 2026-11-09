"""Le cadre de l'API par personne (F1-11, F2-16, K0-04, K0-15, K0-18) : un paquet sans import circulaire réglé à la main,
des petites aides dites une fois, la session lue une seule fois par requête."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

import mika.app.moi as moi
from mika.app.moi import settings as settings_moi
from mika.app.moi.api import PREFIX, Denied, MeApiBase
from mika.app.moi.common import OWN, allows, held_by, millis, only_owner, opened, snippet
from mika.vocab.access import SHARE_PREPARE, SHARE_READ, SHARE_USE

PACKAGE = Path(moi.__file__).parent
MODULES = sorted(PACKAGE.glob("*.py"))
IMPORT = (ast.Import, ast.ImportFrom)


def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text())


def test_the_package_imports_everything_before_anything_else():
    body = tree(PACKAGE / "__init__.py").body[1:]  # sa docstring
    started = next(i for i, node in enumerate(body) if not isinstance(node, IMPORT))
    assert not [node.lineno for node in body[started:] if isinstance(node, IMPORT)]


def test_the_modules_take_the_frame_from_its_own_module():
    stems = {path.stem for path in MODULES}
    for path in MODULES:
        for node in ast.walk(tree(path)):
            if isinstance(node, ast.ImportFrom) and node.module == "mika.app.moi":
                assert {alias.name for alias in node.names} <= stems, f"{path.name}:{node.lineno}"


def test_each_little_helper_is_written_once():
    once = {"millis", "snippet", "allows", "held_by", "opened", "only_owner", "_ms", "_snippet"}
    for path in MODULES:
        if path.name != "common.py":
            defined = {node.name for node in ast.walk(tree(path)) if isinstance(node, ast.FunctionDef)}
            assert not defined & once, path.name


def test_an_instant_and_an_extract():
    assert (millis(0), millis(1_999)) == (0, 1)
    assert snippet(" un  deux\ntrois ", 20) == "un deux trois"
    assert snippet("x" * 10, 5) == "xxxx…" and len(snippet("x" * 10, 5)) == 5


def test_what_a_level_opens():
    assert allows(OWN, SHARE_USE) and allows(SHARE_USE, SHARE_PREPARE)
    assert not allows(SHARE_READ, SHARE_PREPARE) and not allows("", SHARE_READ)


PORT = NS(accounts=lambda: [NS(key=key) for key in ("a_toi", "a_elle", "a_lea", "partage", "ailleurs")])
PARAMS = NS(owners={"a_elle": "elle", "a_lea": "personne:lea", "partage": "personne:zoe", "ailleurs": "personne:zoe"},
            shares={"partage": {"personne:lea": SHARE_READ}})


def levels(person: str, owner: bool) -> dict[str, str]:
    call = NS(frame=object(), me=NS(person=person, owner=owner))
    return {key: level for key, (_, level) in held_by(call, PORT, lambda frame: PARAMS).items()}


def test_what_a_person_holds_of_a_port():
    assert levels("lea", False) == {"a_lea": OWN, "partage": SHARE_READ}  # le sien, et ce qu'on lui partage
    assert levels("adrien", True) == {"a_toi": OWN}  # une propriétaire : ce qui est « à toi »
    assert levels("inconnue", False) == {}


def test_no_port_holds_nothing_and_reads_no_params():
    def never(frame: object) -> object:
        raise AssertionError("les paramètres d'un port absent ne se lisent pas")

    assert held_by(NS(frame=object(), me=NS(person="lea", owner=False)), None, never) == {}


def test_a_refusal_says_missing_or_too_low():
    too_low = {SHARE_READ: "Partagé en lecture."}
    assert opened(("compte", OWN), SHARE_USE, too_low, "Non.") == "compte"
    with pytest.raises(Denied) as absent:
        opened(None, SHARE_READ, too_low, "Non.")
    assert absent.value.status == 404
    with pytest.raises(Denied) as low:
        opened(("compte", SHARE_READ), SHARE_USE, too_low, "Non.")
    assert (low.value.status, low.value.message) == (403, "Partagé en lecture.")
    assert only_owner(("compte", OWN), "Non.") == "compte"
    with pytest.raises(Denied) as shared:
        only_owner(("compte", SHARE_USE), "Seul son propriétaire.")
    assert (shared.value.status, shared.value.message) == (403, "Seul son propriétaire.")


class Sessions:
    """Des comptes qui comptent leurs lectures."""

    def __init__(self, account: object) -> None:
        self.account, self.reads = account, 0

    def session(self, key: str | None) -> object | None:
        self.reads += 1
        return self.account if key == "sid" else None

    def token(self, value: str) -> None:
        return None

    def still_valid(self, key: str | None, *, operator: bool) -> bool:
        raise AssertionError("relit la session qu'on vient de lire")


def client(sessions: Sessions, **cookies: str) -> TestClient:
    async def ping(call: moi.Call) -> dict[str, str]:
        return {"handle": call.me.handle}

    api = MeApiBase(NS(mind=NS(frame=lambda: NS(get=lambda key: None))), sessions)  # type: ignore[arg-type]
    return TestClient(Starlette(routes=[api.route("/ping", ping)]), cookies=cookies)


def test_a_session_is_read_once_per_request():
    sessions = Sessions(NS(id=1, handle="user_1", operator=False))
    got = client(sessions, sessionid="sid").get(PREFIX + "/ping")
    assert (got.status_code, got.json(), sessions.reads) == (200, {"handle": "user_1"}, 1)
    assert client(sessions).get(PREFIX + "/ping").status_code == 401


def test_a_new_box_key_folds_accents_and_ligatures():
    assert settings_moi._slug("Cœur.Été@exemple.fr", set()).startswith("coeur-ete-")
