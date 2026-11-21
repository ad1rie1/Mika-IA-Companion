"""La documentation d'un projet dans l'API par personne et par MCP (ADR 0289), à travers le vrai serveur.

Ce que ces tests gardent : enregistrer et relire une page ; ses versions et le retour à l'une d'elles ; l'écriture
concurrente qui ne s'écrase pas ; créer, renommer, déplacer, supprimer ; la recherche ; une image téléversée, servie,
retirée, et ses bornes ; un chemin qui sort de l'espace ; **les droits de chaque route** — un projet inconnu, le voir
sans le lire, lire sa documentation sans l'écrire, l'écrire — ; ce qu'un lien donne, dit sur la fiche ; et **par
MCP** : pas de jeton, un jeton d'outil qui n'ouvre rien d'autre, une personne qui ne voit que les projets auxquels
elle a droit, qui lit et écrit selon ses droits, et l'historique qui dit « par MCP ».

Et ce que la relecture adverse a fixé (ADR 0292) : une image retirée puis remise à l'identique se remet, et la réponse
dit vrai ; le refus d'une page périmée ne nomme pas qui l'a écrite — ni son jeton — à qui n'a pas le droit de le
savoir ; la porte du point MCP compte chaque appel, borne un lot et les écritures d'un projet ; un jeton d'outil se
voit servir, ne s'élague pas comme une connexion, et se rend lui-même.
"""

from __future__ import annotations

import base64
import json

import pytest
from starlette.websockets import WebSocketDisconnect

from mika.adapters.mcp.protocol import BATCH_MAX
from mika.adapters.web.accounts import LOGIN_TOKENS_KEPT
from mika.adapters.web.gate import SlidingWindow
from mika.adapters.web.hub import WS_UNAUTHORIZED
from mika.app.me import project_docs as pages
from mika.app.me.docs_mcp import PER_MINUTE, PREFIX, READS_ONLY, TOO_MANY, TOO_MANY_WRITES, UNKNOWN, DocsPoint
from mika.contracts import identity as identity_c
from mika.contracts import projects as c
from mika.faculties.projects import docs
from mika.faculties.projects import inspect_docs as words
from mika.faculties.projects.faculty import ACCESS_SET, LINKS_SET, REFRAMED
from mika.vocab.access import PERSON
from tests.fixtures.mika import befriend
from tests.protocol.test_moi_mail import API, append, login, post
from tests.protocol.test_moi_projects import _lea
from tests.protocol.test_tabs_projects import _create, _life
from tests.protocol.test_web import csrf, world  # noqa: F401 — fixture partagée

P = API + "/projets"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _project(client, live, title: str = "Outils réseau") -> int:
    return _create(client, _life(client, live), title, "Écrire sa documentation")


def _share(client, live, pid: int, person: str, **columns) -> None:
    """Une ligne d'accès qui désigne cette personne, partout et toujours."""
    rows = (*c.UNSET, c.ProjectAccess(who=(PERSON + person,), see=True, **columns))
    append(client, live, [ACCESS_SET.draft(project=pid, rows=rows, default=c.UNSET_DEFAULT, by="user_1")], "projects")


def _get(client, pid: int, route: str = "", status: int = 200, /, **params):
    r = client.get(f"{P}/{pid}/documentation{route}", params=params)
    assert r.status_code == status, r.text
    return r.json()


def _save(client, pid: int, path: str, text: str, base: int | None, word: str = "Un mot", status: int = 200):
    body = {"path": path, "text": text, "word": word} | ({} if base is None else {"base": base})
    r = post(client, f"/projets/{pid}/documentation/page/enregistrer", body)
    assert r.status_code == status, r.text
    return r.json()


def _do(client, pid: int, route: str, status: int = 200, **body):
    r = post(client, f"/projets/{pid}/documentation/{route}", body)
    assert r.status_code == status, r.text
    return r.json()


def _upload(client, pid: int, name: str, data: bytes, status: int = 200):
    r = client.post(f"{P}/{pid}/documentation/image/televerser", files={"file": (name, data, "image/png")},
                    data={"name": ""}, headers=csrf(client))
    assert r.status_code == status, r.text
    return r.json()


# ── une page : l'écrire, la relire, ses versions ──


def test_a_page_is_saved_read_back_versioned_and_never_overwritten(world):  # noqa: F811
    client, live, _ = world
    pid = _project(client, live)
    empty = _get(client, pid)
    assert empty["pages"] == [] and empty["images"] == [] and empty["rights"] == {"read": True, "write": True}
    assert empty["limits"]["page_chars"] == docs.PAGE_CHARS and empty["limits"]["versions"] == 50
    made = _save(client, pid, "accueil.md", "# Outils réseau\n\nUn scan par sous-réseau.", 0, "Création")
    assert made["ok"] and made["version"] == 1 and "créée" in made["message"]
    page = _get(client, pid, "/page", path="accueil.md")
    assert page["text"] == "# Outils réseau\n\nUn scan par sous-réseau." and page["title"] == "Outils réseau"
    assert (page["version"], page["author_kind"], page["author"], page["via"]) == (1, "you", "toi", "web")
    assert page["via_label"] == "dans le navigateur" and page["at"] > 10**12 and page["can"] == {"write": True}
    assert _save(client, pid, "accueil.md", "# Outils réseau\n\nDeux commandes.", 1, "Les commandes")["version"] == 2
    # partie de la version 1, qui n'est plus la dernière : rien n'est écrasé, et la réponse le dit
    stale = _save(client, pid, "accueil.md", "j'écrase", 1, status=409)
    assert "version 2" in stale["error"] and "Relis-la" in stale["error"]
    assert _save(client, pid, "accueil.md", "j'écrase", None, status=400)["fields"] == {"base": "valeur requise"}
    assert "existe déjà" in _save(client, pid, "accueil.md", "j'écrase", 0, status=409)["error"]
    assert _get(client, pid, "/page", path="accueil.md")["text"].endswith("Deux commandes.")
    history = _get(client, pid, "/historique", path="accueil.md")
    assert [(v["n"], v["word"], v["current"]) for v in history["versions"]] == [
        (2, "Les commandes", True), (1, "Création", False)]
    assert _get(client, pid, "/version", path="accueil.md", n=1)["text"].endswith("Un scan par sous-réseau.")
    _get(client, pid, "/version", 404, path="accueil.md", n=7)
    # revenir à la version 1 : une version de plus, qui le dit
    back = _do(client, pid, "page/revenir", path="accueil.md", version=1, base=2)
    assert back["version"] == 3 and "retour à la version 1" in back["message"]
    history = _get(client, pid, "/historique", path="accueil.md")["versions"]
    assert (history[0]["n"], history[0]["restored"], history[0]["word"]) == (3, 1, "Retour à la version 1")
    assert _get(client, pid, "/page", path="accueil.md")["text"].endswith("Un scan par sous-réseau.")
    _do(client, pid, "page/revenir", status=409, path="accueil.md", version=1, base=2)  # elle a bougé depuis
    # sans jeton CSRF, rien ne s'écrit
    r = client.post(f"{P}/{pid}/documentation/page/enregistrer", json={"path": "x.md", "text": "x", "base": 0})
    assert r.status_code == 403


def test_pages_are_created_renamed_moved_removed_and_searched(world):  # noqa: F811
    client, live, _ = world
    pid = _project(client, live)
    _save(client, pid, "accueil.md", "# Accueil\n\nVoir [le guide](guide/installation.md).", 0)
    _save(client, pid, "guide/installation.md", "# Installer\n\nLancer `pip install .` puis le scan.", 0)
    _save(client, pid, "guide/avance/rdp.md", "# Le module RDP\n", 0)
    tree = _get(client, pid)
    assert [x["path"] for x in tree["pages"]] == ["accueil.md", "guide/avance/rdp.md", "guide/installation.md"]
    assert tree["folders"] == ["guide", "guide/avance"]
    assert tree["pages"][2] | {"at": 0, "created_at": 0} == {
        "path": "guide/installation.md", "name": "installation.md", "folder": "guide", "title": "Installer",
        "version": 1, "at": 0, "created_at": 0, "chars": 49, "images": [], "author_kind": "you", "author": "toi",
        "via": "web", "via_label": "dans le navigateur", "tool": ""}
    found = _get(client, pid, "/chercher", q="PIP Install")
    assert [x["path"] for x in found["items"]] == ["guide/installation.md"] and "pip install" in found["items"][0]["excerpt"]
    assert _get(client, pid, "/chercher", q="kubernetes")["items"] == []
    # renommer, déplacer : ses versions la suivent
    _save(client, pid, "guide/installation.md", "# Installer\n\nPlus court.", 1)
    assert _do(client, pid, "page/deplacer", path="guide/installation.md", to="guide/demarrer.md")["path"] == \
        "guide/demarrer.md"
    assert _do(client, pid, "page/deplacer", path="guide/demarrer.md", to="demarrer.md")["ok"]
    _get(client, pid, "/page", 404, path="guide/installation.md")
    assert [v["n"] for v in _get(client, pid, "/historique", path="demarrer.md")["versions"]] == [2, 1]
    _do(client, pid, "page/deplacer", status=409, path="demarrer.md", to="accueil.md")  # un chemin pris
    _do(client, pid, "page/deplacer", status=409, path="inconnue.md", to="x.md")
    # supprimer : la page et ses versions
    assert _do(client, pid, "page/supprimer", path="demarrer.md")["ok"]
    _get(client, pid, "/page", 404, path="demarrer.md")
    _get(client, pid, "/historique", 404, path="demarrer.md")
    assert [x["path"] for x in _get(client, pid)["pages"]] == ["accueil.md", "guide/avance/rdp.md"]
    # la console montre ses pages et leur dernière modification, sans rien y éditer
    tab = client.get(f"/admin/fiche/project/{pid}", params={"onglet": "documentation"})
    assert tab.status_code == 200 and "Ses pages" in tab.text and "guide/avance/rdp.md" in tab.text
    assert "dans son espace" in tab.text and "doc_ecrire" not in tab.text and "doc_supprimer" not in tab.text


def test_a_path_never_leaves_the_space_and_a_page_has_its_bound(world):  # noqa: F811
    client, live, _ = world
    pid = _project(client, live)
    for bad in ("../secret.md", "/etc/passwd.md", "guide/../../x.md", "Accueil.md", "notes.txt", "a//b.md"):
        assert _save(client, pid, bad, "x", 0, status=400)["fields"] == {
            "path": "un chemin de page, relatif, en « .md »"}, bad
        _get(client, pid, "/page", 400, path=bad)
    _save(client, pid, "a.md", "x", 0)
    assert _do(client, pid, "page/deplacer", status=400, path="a.md", to="../a.md")["fields"]["to"]
    assert _do(client, pid, "page/supprimer", status=400, path="../a.md")["fields"]["path"]
    # un corps JSON est borné à 64 Kio : une longue page s'enregistre en multipart, jusqu'à sa borne
    long = "é" * 70_000
    r = client.post(f"{P}/{pid}/documentation/page/enregistrer", headers=csrf(client),
                    files={"path": (None, "longue.md"), "text": (None, long), "word": (None, "Longue"),
                           "base": (None, "0")})
    assert r.status_code == 200, r.text
    assert _get(client, pid, "/page", path="longue.md")["chars"] == 70_000
    r = client.post(f"{P}/{pid}/documentation/page/enregistrer", headers=csrf(client),
                    files={"path": (None, "trop.md"), "text": (None, "x" * (docs.PAGE_CHARS + 1)),
                           "word": (None, "x"), "base": (None, "0")})
    assert r.status_code == 400 and "caractères au plus" in r.json()["error"]
    assert _get(client, pid)["images"] == []


# ── ses images ──


def test_an_image_is_uploaded_served_listed_and_removed_within_its_bounds(world):  # noqa: F811
    client, live, _ = world
    pid = _project(client, live)
    got = _upload(client, pid, "Schéma Réseau.PNG", PNG)
    assert got["name"] == "schema-reseau.png" and got["path"] == "images/schema-reseau.png"
    assert _upload(client, pid, "schema-reseau.png", PNG)["name"] == "schema-reseau-2.png"  # un nom pris
    _save(client, pid, "accueil.md", "# Accueil\n\n![le réseau](images/schema-reseau.png)", 0)
    listed = _get(client, pid, "/images")
    assert [(i["name"], i["size"], i["mime"], i["used_by"]) for i in listed["items"]] == [
        ("schema-reseau-2.png", len(PNG), "image/png", []), ("schema-reseau.png", len(PNG), "image/png", ["accueil.md"])] \
        or {i["name"] for i in listed["items"]} == {"schema-reseau.png", "schema-reseau-2.png"}
    assert next(i for i in listed["items"] if i["name"] == "schema-reseau.png")["used_by"] == ["accueil.md"]
    assert listed["space_used"] == 2 * len(PNG) and _get(client, pid, "/page", path="accueil.md")["images"] == [
        "schema-reseau.png"]
    served = client.get(f"{P}/{pid}/documentation/image", params={"name": "schema-reseau.png"})
    assert served.status_code == 200 and served.content == PNG and served.headers["content-type"] == "image/png"
    assert served.headers["x-content-type-options"] == "nosniff" and "sandbox" in served.headers[
        "content-security-policy"]
    for name in ("../../secret.key", "inconnue.png", "/etc/passwd"):
        assert client.get(f"{P}/{pid}/documentation/image", params={"name": name}).status_code == 404
    # ses bornes : ce qui n'est pas une image qu'on garde, une image trop grosse
    assert "pas une image" in _upload(client, pid, "piege.png", b"<svg onload=alert(1)>", status=409)["error"]
    assert "5 Mio" in _upload(client, pid, "grosse.png", PNG + b"0" * docs.IMAGE_BYTES, status=409)["error"]
    assert _do(client, pid, "image/retirer", name="schema-reseau.png")["ok"]
    assert client.get(f"{P}/{pid}/documentation/image", params={"name": "schema-reseau.png"}).status_code == 404
    _do(client, pid, "image/retirer", status=409, name="schema-reseau.png")
    assert [i["name"] for i in _get(client, pid, "/images")["items"]] == ["schema-reseau-2.png"]


# ── les droits de chaque route ──

READS = ("", "/page?path=accueil.md", "/historique?path=accueil.md", "/version?path=accueil.md&n=1",
         "/chercher?q=scan", "/images", "/image?name=schema.png")
WRITES = (("page/enregistrer", {"path": "accueil.md", "text": "j'écrase", "base": 1}),
          ("page/revenir", {"path": "accueil.md", "version": 1, "base": 1}),
          ("page/deplacer", {"path": "accueil.md", "to": "x.md"}), ("page/supprimer", {"path": "accueil.md"}),
          ("image/retirer", {"name": "schema.png"}))


def _statuses(client, pid: int) -> tuple[set[int], set[int]]:
    reads = {client.get(f"{P}/{pid}/documentation{path}").status_code for path in READS}
    writes = {post(client, f"/projets/{pid}/documentation/{route}", body).status_code for route, body in WRITES}
    writes.add(client.post(f"{P}/{pid}/documentation/image/televerser", files={"file": ("x.png", PNG, "image/png")},
                           data={"name": ""}, headers=csrf(client)).status_code)
    return reads, writes


def test_each_route_follows_what_the_access_lines_give(world):  # noqa: F811
    client, live, _ = world
    pid = _project(client, live)
    _save(client, pid, "accueil.md", "# Accueil\n\nUn scan.", 0)
    assert _upload(client, pid, "schema.png", PNG)["name"] == "schema.png"
    lea = _lea(client, live)
    login(client, "lea")
    # un projet qu'on ne lui ouvre pas, ou inconnu : la même réponse partout
    assert _statuses(client, pid) == ({404}, {404}) and _statuses(client, 999) == ({404}, {404})
    # le voir sans son détail
    login(client, "adrien")
    _share(client, live, pid, lea, docs=True)
    login(client, "lea")
    assert _statuses(client, pid) == ({403}, {403})
    assert client.get(f"{P}/{pid}/documentation").json()["error"] == "Ce projet ne t'est ouvert qu'à voir : son " \
                                                                      "détail reste à son propriétaire."
    # son détail, ses fichiers même, sans sa documentation : la colonne est fermée tant qu'on ne la coche pas
    login(client, "adrien")
    _share(client, live, pid, lea, steer=c.STEER_EDIT, files=True)
    login(client, "lea")
    assert _statuses(client, pid) == ({403}, {403})
    assert client.get(f"{P}/{pid}/documentation").json()["error"] == pages.NO_DOCS
    assert client.get(f"{P}/{pid}").json()["rights"]["detail"] is True
    # la lire sans l'écrire : en lecture seule, puis sur accord
    for steer in (c.STEER_READ, c.STEER_ASK):
        login(client, "adrien")
        _share(client, live, pid, lea, steer=steer, docs=True)
        login(client, "lea")
        assert _statuses(client, pid) == ({200}, {403}), steer
        got = _get(client, pid)
        assert got["rights"] == {"read": True, "write": False} and got["pages"][0]["author_kind"] == "person"
        assert _get(client, pid, "/page", path="accueil.md")["can"] == {"write": False}
        assert post(client, f"/projets/{pid}/documentation/page/enregistrer",
                    {"path": "accueil.md", "text": "x", "base": 1}).json()["error"] == pages.READ_ONLY
    assert client.get(f"{P}/{pid}/documentation/image", params={"name": "schema.png"}).content == PNG
    # l'écrire : qui le pilote en modification
    login(client, "adrien")
    _share(client, live, pid, lea, steer=c.STEER_EDIT, docs=True)
    login(client, "lea")
    assert _get(client, pid)["rights"] == {"read": True, "write": True}
    assert _save(client, pid, "accueil.md", "# Accueil\n\nRevu par Léa.", 1, "Relecture")["version"] == 2
    assert _upload(client, pid, "capture.png", PNG)["name"] == "capture.png"
    mine = _get(client, pid, "/historique", path="accueil.md")["versions"]
    assert [(v["n"], v["author_kind"], v["author"]) for v in mine] == [(2, "you", "toi"), (1, "person", "adrien")]
    # le propriétaire la lit toujours, et y voit qui a écrit
    login(client, "adrien")
    theirs = _get(client, pid, "/historique", path="accueil.md")["versions"]
    assert [(v["author_kind"], v["author"], v["via"]) for v in theirs] == [
        ("person", "Léa Martin", "web"), ("you", "toi", "web")]
    # un droit repris coupe la lecture à la requête suivante
    _share(client, live, pid, lea, steer=c.STEER_EDIT)
    login(client, "lea")
    assert _statuses(client, pid) == ({403}, {403})


def test_the_owner_reads_its_documentation_whatever_its_lines_say_and_a_link_says_what_it_gives(world):  # noqa: F811
    client, live, _ = world
    pid = _project(client, live)
    rid = _create(client, live.kernel, "Faire connaître Outils réseau", "Écrire la page d'accueil")
    _save(client, pid, "accueil.md", "# Accueil", 0)
    # un tableau réglé avant la colonne (sans « documentation ») ne la ferme pas à son propriétaire
    rows = tuple(line.model_copy(update={"docs": False}) for line in c.UNSET)
    append(client, live, [ACCESS_SET.draft(project=pid, rows=rows, default=c.UNSET_DEFAULT, by="user_1")], "projects")
    assert _get(client, pid)["rights"] == {"read": True, "write": True}
    append(client, live, [LINKS_SET.draft(project=rid, reads=(pid,), by="user_1")], "projects")
    gives = client.get(f"{P}/{rid}").json()["links"]["reads"][0]["gives"]
    assert gives["see"] and gives["docs"] is False  # la ligne « elle seule » ne la donne plus à ses projets
    append(client, live, [ACCESS_SET.draft(project=pid, rows=c.UNSET, default=c.UNSET_DEFAULT, by="user_1")],
           "projects")
    assert client.get(f"{P}/{rid}").json()["links"]["reads"][0]["gives"]["docs"] is True


# ── par MCP ──


def _token(client, live, username: str, kind: str, label: str = "Claude Code") -> str:
    account = client.portal.call(live.accounts.by_name, username)[0]
    return client.portal.call(lambda: live.accounts.create_token(account.id, label, client=kind))[1]


def _rpc(client, token: str | None, method: str, **params):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(PREFIX + "/", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                       headers=headers)


def _tool(client, token: str, name: str, **arguments):
    """Un appel d'outil : ce qu'il rend (lu comme du JSON quand c'en est), et s'il a échoué."""
    r = _rpc(client, token, "tools/call", name=name, arguments=arguments)
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    text = result["content"][0]["text"]
    try:
        return json.loads(text), result["isError"]
    except ValueError:
        return text, result["isError"]


def test_the_mcp_point_needs_an_account_token_and_a_tool_token_opens_nothing_else(world):  # noqa: F811
    client, live, _ = world
    _project(client, live)
    assert _rpc(client, None, "tools/list").status_code == 401  # la session du navigateur n'y compte pas
    assert _rpc(client, "mw_un-jeton-qui-ne-vaut-rien", "tools/list").status_code == 401
    tool, screen = _token(client, live, "adrien", "tool"), _token(client, live, "adrien", "screen")
    names = [t["name"] for t in _rpc(client, tool, "tools/list").json()["result"]["tools"]]
    assert names == ["doc_lister", "doc_lire", "doc_chercher", "doc_ecrire", "doc_image"]
    # un écran ne fait que lire, ici comme ailleurs
    assert [t["name"] for t in _rpc(client, screen, "tools/list").json()["result"]["tools"]] == names[:3]
    # le jeton d'un outil n'ouvre que ce point : ni l'API, ni le chat
    client.cookies.clear()
    origin = client.headers.pop("origin")  # sans Origin : un client natif
    try:
        assert client.get(API, headers={"Authorization": f"Bearer {tool}"}).status_code == 401
        assert client.get(API, headers={"Authorization": f"Bearer {screen}"}).status_code == 200
        asked = client.post("/auth/token", json={"username": "adrien", "password": "un-mot-de-passe-long",
                                                 "client": "tool"})
        assert asked.status_code == 200 and asked.json()["token"].startswith("mw_")  # il se demande aussi par connexion
        with client.websocket_connect("/ws", headers={"Authorization": f"Bearer {tool}"}) as ws, \
                pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == WS_UNAUTHORIZED
    finally:
        client.headers["origin"] = origin


def test_by_mcp_a_person_sees_only_her_projects_reads_and_writes_as_her_rights_allow(world):  # noqa: F811
    client, live, _ = world
    pid = _project(client, live)
    hidden = _create(client, live.kernel, "Un projet caché", "Rester caché")
    _save(client, pid, "accueil.md", "# Accueil\n\nUn scan par sous-réseau.", 0)
    _save(client, hidden, "secret.md", "# Secret", 0)
    lea = _lea(client, live)
    token = _token(client, live, "lea", "tool", "Claude Code de Léa")
    # rien ne lui est ouvert : aucun projet, et un projet qui existe répond comme un projet inconnu
    assert _tool(client, token, "doc_lister") == ({"projects": []}, False)
    for project in (pid, hidden, 999):
        assert _tool(client, token, "doc_lire", projet=project, chemin="accueil.md") == (UNKNOWN, True)
    # le détail sans la documentation : toujours rien
    _share(client, live, pid, lea, steer=c.STEER_EDIT, files=True)
    assert _tool(client, token, "doc_lister") == ({"projects": []}, False)
    assert _tool(client, token, "doc_lister", projet=pid) == (UNKNOWN, True)
    # la lire, sans l'écrire
    _share(client, live, pid, lea, steer=c.STEER_READ, docs=True)
    assert _tool(client, token, "doc_lister")[0] == {"projects": [
        {"id": pid, "title": "Outils réseau", "pages": 1, "write": False}]}
    listed, failed = _tool(client, token, "doc_lister", projet=pid)
    assert not failed and [x["path"] for x in listed["pages"]] == ["accueil.md"] and listed["rights"]["write"] is False
    page, failed = _tool(client, token, "doc_lire", projet=pid, chemin="accueil.md")
    assert not failed and page["text"].endswith("Un scan par sous-réseau.") and page["version"] == 1
    found, _failed = _tool(client, token, "doc_chercher", projet=pid, mots="sous-réseau")
    assert [x["path"] for x in found["items"]] == ["accueil.md"]
    assert _tool(client, token, "doc_ecrire", projet=pid, chemin="accueil.md", texte="x", mot="x", base=1) == (
        pages.READ_ONLY, True)
    assert _tool(client, token, "doc_image", projet=pid, nom="x.png", base64=base64.b64encode(PNG).decode()) == (
        pages.READ_ONLY, True)
    assert _tool(client, token, "doc_lire", projet=hidden, chemin="secret.md") == (UNKNOWN, True)
    assert _tool(client, token, "doc_lire", projet=pid, chemin="../../secret.md")[1] is True
    # l'écrire : en modification
    _share(client, live, pid, lea, steer=c.STEER_EDIT, docs=True)
    said, failed = _tool(client, token, "doc_ecrire", projet=pid, chemin="accueil.md",
                         texte="# Accueil\n\nRevu par un outil.", mot="Relecture", base=1)
    assert not failed and "Version 2" in said
    stale, failed = _tool(client, token, "doc_ecrire", projet=pid, chemin="accueil.md", texte="j'écrase", mot="x",
                          base=1)
    assert failed and "version 2" in stale and "par MCP" in stale
    made, failed = _tool(client, token, "doc_ecrire", projet=pid, chemin="guide/mcp.md", texte="# Par MCP", base=0)
    assert not failed and "créée" in made
    assert _tool(client, token, "doc_ecrire", projet=pid, chemin="../x.md", texte="x", base=0)[1] is True
    image, failed = _tool(client, token, "doc_image", projet=pid, nom="capture.png",
                          base64=base64.b64encode(PNG).decode())
    assert not failed and "images/capture.png" in image
    assert _tool(client, token, "doc_image", projet=pid, nom="x.png", base64="pas du base64 !")[1] is True
    # un jeton d'écran de la même personne lit, et n'écrit pas
    screen = _token(client, live, "lea", "screen")
    assert _tool(client, screen, "doc_lire", projet=pid, chemin="accueil.md")[0]["version"] == 2
    assert _tool(client, screen, "doc_ecrire", projet=pid, chemin="accueil.md", texte="x", base=2) == (READS_ONLY, True)
    # l'historique dit « par MCP », avec le nom du jeton, et la page lue dans le navigateur aussi
    history = _get(client, pid, "/historique", path="accueil.md")["versions"]
    assert [(v["n"], v["author_kind"], v["author"], v["via"], v["via_label"], v["tool"]) for v in history] == [
        (2, "person", "Léa Martin", "mcp", "un outil, par MCP", "Claude Code de Léa"),
        (1, "you", "toi", "web", "dans le navigateur", "")]
    page = _get(client, pid, "/page", path="accueil.md")
    assert (page["via"], page["tool"], page["text"]) == ("mcp", "Claude Code de Léa", "# Accueil\n\nRevu par un outil.")
    assert [i["via"] for i in _get(client, pid, "/images")["items"]] == ["mcp"]
    # un droit repris coupe l'outil à l'appel suivant
    _share(client, live, pid, lea, steer=c.STEER_EDIT)
    assert _tool(client, token, "doc_lire", projet=pid, chemin="accueil.md") == (UNKNOWN, True)


# ── Ce que la relecture adverse a fixé (ADR 0292) ──


def test_an_image_removed_then_put_back_as_it_was_is_there_again(world):  # noqa: F811
    """Aucune clé permanente pour l'ajout d'une image : retirée puis remise à l'identique sous le même nom, elle est
    de nouveau là — servie, comptée —, et la réponse dit ce qui s'est vraiment passé."""
    client, live, _ = world
    pid = _project(client, live)

    def served() -> int:
        return client.get(f"{P}/{pid}/documentation/image", params={"name": "schema.png"}).status_code

    for _round in range(3):
        got = _upload(client, pid, "schema.png", PNG)
        assert (got["name"], got["path"], got["message"]) == ("schema.png", "images/schema.png",
                                                              words.IMAGE_ADDED.format(name="schema.png"))
        assert served() == 200 and [i["name"] for i in _get(client, pid, "/images")["items"]] == ["schema.png"]
        assert _get(client, pid, "/images")["space_used"] == len(PNG)
        assert _do(client, pid, "image/retirer", name="schema.png")["ok"] and served() == 404
        client.portal.call(live.kernel.lanes.join)  # l'effet du retrait a effacé ses octets
    # par MCP aussi, et son nom vient de ce qui a été écrit
    token = _token(client, live, "adrien", "tool")
    for _round in range(2):
        said, failed = _tool(client, token, "doc_image", projet=pid, nom="schema.png",
                             base64=base64.b64encode(PNG).decode())
        assert (said, failed) == (words.IMAGE_ADDED.format(name="schema.png"), False) and served() == 200
        assert _do(client, pid, "image/retirer", name="schema.png")["ok"]
        client.portal.call(live.kernel.lanes.join)
    # un envoi redit (la même clé d'envoi) rend la même réponse, avec le même nom, sans rien refaire
    sent = [client.post(f"{P}/{pid}/documentation/image/televerser", files={"file": ("plan.png", PNG, "image/png")},
                        data={"name": ""}, headers={**csrf(client), "Idempotency-Key": "envoi-1"}).json()
            for _ in range(2)]
    assert [(x["name"], x["path"]) for x in sent] == [("plan.png", "images/plan.png")] * 2
    assert sent[1].get("deduped") is True
    assert [i["name"] for i in _get(client, pid, "/images")["items"]] == ["plan.png"]


def test_the_refusal_of_a_stale_page_names_its_writer_only_to_who_may_know(world):  # noqa: F811
    """Le refus d'une écriture partie d'une version périmée dit qui a écrit la dernière — par la règle des noms : une
    personne qu'on ne doit pas nommer reste « une autre personne », et le nom de son jeton ne sort pas."""
    client, live, _ = world
    pid = _project(client, live)
    _save(client, pid, "accueil.md", "# Accueil", 0)
    # le projet est celui de Léa, une connaissance : elle lit ce qui est à elle, pas ce qui concerne autrui
    lea = _lea(client, live, friend=False)
    before = live.kernel.mind.frame().state("projects").projects[pid]
    append(client, live, [REFRAMED.draft(project=pid, set_owner=True, owner=lea, about=(lea,), by="user_1",
                                         read_about=before.read_about)], "projects")
    nina = client.portal.call(lambda: live.accounts.create("nina", "un-mot-de-passe-long", operator=False,
                                                           full_name="Nina Roche"))
    nina_person = str(live.kernel.mind.frame().get(identity_c.PERSON(nina.handle)) or nina.handle)
    client.portal.call(lambda: befriend(live.kernel, nina_person, "friend"))
    rows = (*c.UNSET, c.ProjectAccess(who=(PERSON + lea, PERSON + nina_person), see=True, steer=c.STEER_EDIT,
                                      docs=True))
    append(client, live, [ACCESS_SET.draft(project=pid, rows=rows, default=c.UNSET_DEFAULT, by="user_1")], "projects")
    # Nina écrit la version 2 par MCP, avec un jeton qui porte un nom à elle
    token = _token(client, live, "nina", "tool", "Portable de Nina, rue des Lilas")
    said, failed = _tool(client, token, "doc_ecrire", projet=pid, chemin="accueil.md", texte="# Accueil\n\nNina.",
                         mot="x", base=1)
    assert not failed and "Version 2" in said
    # Léa, qui n'a aucun lien avec Nina, part de la version 1 : refusée, sans le nom de Nina ni celui de son jeton
    login(client, "lea")
    assert _get(client, pid)["rights"] == {"read": True, "write": True}
    stale = _save(client, pid, "accueil.md", "j'écrase", 1, status=409)["error"]
    assert "version 2" in stale and "une autre personne" in stale
    assert "Nina" not in stale and "Lilas" not in stale and "Portable" not in stale
    history = _get(client, pid, "/historique", path="accueil.md")["versions"]
    assert (history[0]["author_kind"], history[0]["via"], history[0]["tool"]) == ("person", "mcp", "")
    assert "Nina" not in str(history) and "Lilas" not in str(_get(client, pid)) + str(
        _get(client, pid, "/page", path="accueil.md"))
    # par MCP aussi
    mine = _token(client, live, "lea", "tool", "Outil de Léa")
    stale, failed = _tool(client, mine, "doc_ecrire", projet=pid, chemin="accueil.md", texte="j'écrase", mot="x", base=1)
    assert failed and "version 2" in stale and "Nina" not in stale and "Lilas" not in stale
    # Nina, elle, lit son propre jeton ; qui s'occupe d'elle peut la nommer, et le lit aussi
    for who in ("nina", "adrien"):
        login(client, who)
        seen = _get(client, pid, "/historique", path="accueil.md")["versions"][0]
        assert seen["tool"] == "Portable de Nina, rue des Lilas", who
    stale = _save(client, pid, "accueil.md", "j'écrase", 1, status=409)["error"]
    assert "Nina Roche" in stale and "Portable de Nina" in stale
    # l'action elle-même, hors de la console, ne nomme personne
    assert words.SOMEONE == "entre-temps"


def _batch(client, token: str, calls: list[tuple[str, dict]]):
    body = [{"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
            for n, (name, arguments) in enumerate(calls)]
    return client.post(PREFIX + "/", json=body, headers={"Authorization": f"Bearer {token}"})


def test_the_mcp_gate_counts_every_call_bounds_a_batch_and_the_writes_of_a_project(world):  # noqa: F811
    client, live, _ = world
    pid = _project(client, live)
    token = _token(client, live, "adrien", "tool")
    # un lot au-delà de sa borne est refusé en entier : rien n'en est exécuté
    over = _batch(client, token, [("doc_ecrire", {"projet": pid, "chemin": f"page-{n}.md", "texte": "# x", "base": 0})
                                  for n in range(BATCH_MAX + 1)])
    assert over.status_code == 200 and over.json()["error"]["message"].startswith("lot trop grand")
    assert _get(client, pid)["pages"] == []
    # chaque appel d'un lot paie son passage : PER_MINUTE appels, pas PER_MINUTE requêtes
    spent = 1  # la requête refusée a payé le sien
    while spent + BATCH_MAX <= PER_MINUTE - BATCH_MAX:
        got = _batch(client, token, [("doc_lister", {})] * BATCH_MAX)
        assert got.status_code == 200 and not any(x["result"]["isError"] for x in got.json())
        spent += BATCH_MAX
    left = PER_MINUTE - spent
    assert 0 < left < BATCH_MAX * 2
    last = _batch(client, token, [("doc_lister", {})] * (left + 1)).json() if left < BATCH_MAX else None
    if last is None:
        assert _batch(client, token, [("doc_lister", {})] * BATCH_MAX).status_code == 200
        left -= BATCH_MAX
        last = _batch(client, token, [("doc_lister", {})] * (left + 1)).json()
    # le lot qui passe la fenêtre : ses premiers appels répondent, celui de trop se refuse sans rien faire
    assert [x["result"]["isError"] for x in last] == [False] * left + [True]
    assert last[-1]["result"]["content"][0]["text"] == TOO_MANY
    assert _rpc(client, token, "tools/list").status_code == 429  # et la requête suivante attend la minute
    # les écritures d'un projet, sur vingt-quatre heures : au-delà, rien ne s'écrit — la lecture reste

    async def writes() -> tuple[list[tuple[bool, str]], bool]:
        point = DocsPoint(live.kernel, live.accounts)
        point._writes = SlidingWindow(2, 24 * 3600.0)
        scope = {"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]}
        out = []
        for n in range(3):
            host = await point._host(scope)
            got = await host.call("doc_ecrire", {"projet": pid, "chemin": f"note-{n}.md", "texte": "# x", "base": 0})
            out.append((got.is_error, got.text))
        host = await point._host(scope)
        return out, (await host.call("doc_lister", {"projet": pid})).is_error

    written, read_failed = client.portal.call(writes)
    assert [failed for failed, _ in written] == [False, False, True] and written[2][1] == TOO_MANY_WRITES
    assert not read_failed and [x["path"] for x in _get(client, pid)["pages"]] == ["note-0.md", "note-1.md"]


def test_a_tool_token_is_seen_serving_is_not_pruned_like_a_login_and_gives_itself_back(world):  # noqa: F811
    client, live, _ = world
    _project(client, live)
    account = client.portal.call(live.accounts.by_name, "adrien")[0]
    client.cookies.clear()
    origin = client.headers.pop("origin")  # sans Origin : un client natif
    try:
        def login_token(kind: str) -> str:
            got = client.post("/auth/token", json={"username": "adrien", "password": "un-mot-de-passe-long",
                                                   "client": kind})
            assert got.status_code == 200, got.text
            return got.json()["token"]

        def alive() -> dict[str, list]:
            found = client.portal.call(live.accounts.tokens, account.id)
            return {kind: [t for t in found if t.client == kind and not t.revoked] for kind in ("tool", "screen")}

        tool = login_token("tool")
        assert alive()["tool"][0].last_used is None
        assert _rpc(client, tool, "tools/list").status_code == 200
        assert alive()["tool"][0].last_used is not None  # son usage se note au point MCP
        # une application qui se reconnecte bien des fois n'emporte pas le jeton de l'outil
        for _ in range(LOGIN_TOKENS_KEPT + 3):
            login_token("screen")
        assert len(alive()["screen"]) == LOGIN_TOKENS_KEPT and len(alive()["tool"]) == 1
        assert _rpc(client, tool, "tools/list").status_code == 200
        # il se rend lui-même : il ne vaut plus rien, nulle part
        gone = client.delete("/auth/token", headers={"Authorization": f"Bearer {tool}"})
        assert gone.status_code == 200 and gone.json() == {"ok": True}
        assert _rpc(client, tool, "tools/list").status_code == 401 and alive()["tool"] == []
    finally:
        client.headers["origin"] = origin
