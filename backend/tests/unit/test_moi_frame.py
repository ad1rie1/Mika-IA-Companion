"""Le cadre de l'API par personne (F1-11, F2-16, K0-04, K0-15, K0-18) : un paquet sans import circulaire réglé à la main,
des petites aides dites une fois, la session lue une seule fois par requête."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from starlette.applications import Starlette
from starlette.routing import Match
from starlette.testclient import TestClient

import mika.app.me as me
from mika.app.domains.maps import api as maps_me
from mika.app.me import common as common_me
from mika.app.me import settings as settings_me
from mika.app.me.api import PREFIX, Denied, MeApiBase, either
from mika.app.me.assembly import MeApi
from mika.app.me.common import allows, held_by, millis, only_owner, opened, snippet
from mika.ports.mail import ACCOUNT_KEY
from mika.vocab.access import SHARE_PREPARE, SHARE_READ, SHARE_USE
from mika.vocab.ownership import OWNED

PACKAGE = Path(me.__file__).parent
#: les modules du paquet ``app/me``, le cadre de l'API par personne
FRAME = sorted(PACKAGE.glob("*.py"))
#: … et ceux des domaines, qui en ont quitté le paquet pour leur dossier (ADR 0310) : leur API par personne et ses
#: parts (le direct, les partages, les comptes…) ; leur console a ses propres gardes
DOMAINS = sorted(p for p in (PACKAGE.parent / "domains").rglob("*.py") if "console" not in p.parts)
MODULES = [*FRAME, *DOMAINS]
IMPORT = (ast.Import, ast.ImportFrom)


def where(path: Path) -> str:
    return path.relative_to(PACKAGE.parent).as_posix()


def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text())


def test_the_package_imports_everything_before_anything_else():
    body = tree(PACKAGE / "__init__.py").body[1:]  # sa docstring
    started = next(i for i, node in enumerate(body) if not isinstance(node, IMPORT))
    assert not [node.lineno for node in body[started:] if isinstance(node, IMPORT)]


def test_no_route_hides_another():
    """Les routes viennent des modules du cadre, puis de chaque domaine, dans l'ordre des fiches (ADR 0310). Cet ordre
    ne doit décider de rien : une adresse faite pour une route — ses paramètres remplis — n'est prise par aucune
    route essayée avant elle."""
    routes = MeApi(None, None).routes()  # type: ignore[arg-type]
    assert len({(r.path, tuple(sorted(r.methods or ()))) for r in routes}) == len(routes), "une route déclarée deux fois"
    hidden = []
    for i, r in enumerate(routes):
        path = re.sub(r"\{[^}:]+:path\}", "a/b", re.sub(r"\{[^}:]+:int\}", "7", r.path))
        path = re.sub(r"\{[^}]+\}", "x", path)
        for method in sorted((r.methods or set()) - {"HEAD"}):
            scope = {"type": "http", "method": method, "path": path, "root_path": ""}
            first = next(j for j, other in enumerate(routes) if other.matches(scope)[0] == Match.FULL)
            if first != i:
                hidden.append(f"{method} {r.path} est prise par {routes[first].path}")
    assert not hidden, hidden


def test_the_modules_read_are_the_frame_and_the_domains():
    """Les gardes qui suivent lisent le paquet et les modules des domaines : la recherche les trouve bien."""
    assert len(FRAME) >= 10 and {"api.py", "live.py", "wiring.py"} <= {p.name for p in DOMAINS}
    assert PACKAGE.parent / "domains" / "projects" / "api" / "manage.py" in DOMAINS


def test_the_modules_take_the_frame_from_its_own_module():
    stems = {path.stem for path in FRAME}  # les modules du paquet : ce qu'on y prend, sous son propre nom
    for path in MODULES:
        for node in ast.walk(tree(path)):
            if isinstance(node, ast.ImportFrom) and node.module == "mika.app.me":
                assert {alias.name for alias in node.names} <= stems, f"{where(path)}:{node.lineno}"


def test_each_little_helper_is_written_once():
    once = {"millis", "snippet", "allows", "held_by", "opened", "only_owner", "_ms", "_snippet"}
    for path in MODULES:
        if path != PACKAGE / "common.py":
            defined = {node.name for node in ast.walk(tree(path))
                       if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)}
            assert not defined & once, where(path)


def test_the_names_follow_the_glossary():
    """« shares » est la faculté des fichiers qu'elle envoie : le module des partages se nomme ``sharing``. Le niveau « à
    elle » se prend à sa source (``vocab.ownership.OWNED``), sans second nom ; aucun alias ne garde le nom de l'ancien
    paquet ``app/moi``."""
    assert "shares" not in {path.stem for path in MODULES}
    assert not hasattr(common_me, "OWN")
    kept = [f"{where(path)}:{node.lineno}" for path in MODULES for node in ast.walk(tree(path)) if isinstance(node, IMPORT)
            for alias in node.names if (alias.asname or "").endswith("_moi")]
    assert not kept


def test_an_instant_and_an_extract():
    assert (millis(0), millis(1_999)) == (0, 1)
    assert snippet(" un  deux\ntrois ", 20) == "un deux trois"
    assert snippet("x" * 10, 5) == "xxxx…" and len(snippet("x" * 10, 5)) == 5


def test_a_refusal_offers_its_choices_in_words():
    """Un refus qui énumère des sortes ou des canaux les tire de leur liste, dans son ordre (``either``) : « a, b ou
    c » — sans en nommer aucun lui-même."""
    assert either(["mail"]) == "mail" and either(iter(["a", "b"])) == "a ou b" and either([]) == ""
    assert either(("mail", "teams", "mcp", "agenda")) == "mail, teams, mcp ou agenda"


def test_what_a_level_opens():
    assert allows(OWNED, SHARE_USE) and allows(SHARE_USE, SHARE_PREPARE)
    assert not allows(SHARE_READ, SHARE_PREPARE) and not allows("", SHARE_READ)


PORT = NS(accounts=lambda: [NS(key=key) for key in ("a_toi", "a_elle", "a_lea", "partage", "ailleurs")])
PARAMS = NS(owners={"a_elle": "elle", "a_lea": "personne:lea", "partage": "personne:zoe", "ailleurs": "personne:zoe"},
            shares={"partage": {"personne:lea": SHARE_READ}})


def levels(person: str, owner: bool) -> dict[str, str]:
    call = NS(frame=object(), me=NS(person=person, owner=owner))
    return {key: level for key, (_, level) in held_by(call, PORT, lambda frame: PARAMS).items()}


def test_what_a_person_holds_of_a_port():
    assert levels("lea", False) == {"a_lea": OWNED, "partage": SHARE_READ}  # le sien, et ce qu'on lui partage
    assert levels("adrien", True) == {"a_toi": OWNED}  # une propriétaire : ce qui est « à toi »
    assert levels("inconnue", False) == {}


def test_no_port_holds_nothing_and_reads_no_params():
    def never(frame: object) -> object:
        raise AssertionError("les paramètres d'un port absent ne se lisent pas")

    assert held_by(NS(frame=object(), me=NS(person="lea", owner=False)), None, never) == {}


def test_a_refusal_says_missing_or_too_low():
    too_low = {SHARE_READ: "Partagé en lecture."}
    assert opened(("compte", OWNED), SHARE_USE, too_low, "Non.") == "compte"
    with pytest.raises(Denied) as absent:
        opened(None, SHARE_READ, too_low, "Non.")
    assert absent.value.status == 404
    with pytest.raises(Denied) as low:
        opened(("compte", SHARE_READ), SHARE_USE, too_low, "Non.")
    assert (low.value.status, low.value.message) == (403, "Partagé en lecture.")
    assert only_owner(("compte", OWNED), "Non.") == "compte"
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
    async def ping(call: me.Call) -> dict[str, str]:
        return {"handle": call.me.handle}

    api = MeApiBase(NS(mind=NS(frame=lambda: NS(get=lambda key: None))), sessions)  # type: ignore[arg-type]
    return TestClient(Starlette(routes=[api.route("/ping", ping)]), cookies=cookies)


def test_a_session_is_read_once_per_request():
    sessions = Sessions(NS(id=1, handle="user_1", operator=False))
    got = client(sessions, sessionid="sid").get(PREFIX + "/ping")
    assert (got.status_code, got.json(), sessions.reads) == (200, {"handle": "user_1"}, 1)
    assert client(sessions).get(PREFIX + "/ping").status_code == 401


def test_without_tiles_the_map_says_unplugged_as_the_map_screen_does():
    """Les tuiles du fond de carte (``MeApiBase.tiles``) ne sont pas le port ``maps`` : sans elles, le fond de carte
    dit « pas branchée » par la phrase de l'écran Carte (``maps.NOT_PLUGGED``), écrite une fois."""
    sessions = Sessions(NS(id=1, handle="user_1", operator=False))
    api = MeApiBase(NS(mind=NS(frame=lambda: NS(get=lambda key: None))), sessions, tiles=None)  # type: ignore[arg-type]
    app = Starlette(routes=[api.route(maps_me.BASE_MAP, maps_me.map_info)])
    got = TestClient(app, cookies={"sessionid": "sid"}).get(PREFIX + maps_me.BASE_MAP)
    assert got.json() == {"ready": False, "reason": maps_me.NOT_PLUGGED}


def test_a_new_box_key_folds_accents_and_ligatures():
    assert settings_me.fresh_key("Cœur.Été@exemple.fr", set(), ACCOUNT_KEY).startswith("coeur-ete-")
