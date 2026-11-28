"""Ce que l'hôte GitHub sert à l'écran d'une personne, et la fusion (ADR 0288), contre un GitHub simulé :

- fusionner nomme le commit au bout de la branche : un seul ``PUT``, vers ``…/pulls/<n>/merge``, avec ``sha`` ;
- GitHub refuse quand la branche a bougé (409), quand il la dit impossible à fusionner (405), quand le jeton n'a
  pas ce droit (403) : chaque refus a son code et ses mots, composés ici ; sans jeton, rien n'est envoyé ;
- les échanges d'une pull request (commentaires, texte des relectures) et d'une issue, dans l'ordre, bornés ;
- les vérifications d'un commit une à une ; les étiquettes d'une issue ; le titre et le texte d'une pull request.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from mika.adapters.workshop.github import NO_MERGE_TOKEN, GitHubRepos
from mika.ports.workshop import (
    CHECKS_FAILED,
    CHECKS_PASSED,
    CHECKS_PENDING,
    MERGE_BLOCKED,
    MERGE_DENIED,
    MERGE_MOVED,
    MERGE_UNKNOWN,
    MERGE_UNREACHED,
    PULL_OPEN,
)

URL = "https://github.com/moi/outils.git"
SHA, MERGE_SHA = "a" * 40, "c" * 40
TOKEN = {"token": "ghp_SECRET", "hosts": ["github.com"]}


def go(coro):
    return asyncio.run(coro)


def github(routes: dict[tuple[str, str], tuple[int, object]], seen: list[httpx.Request]) -> httpx.AsyncClient:
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = routes.get((request.method, request.url.path), (404, {"message": "Not Found"}))
        return httpx.Response(status, content=json.dumps(body).encode())

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


def test_merging_names_the_head_commit_and_is_the_only_put():
    seen: list[httpx.Request] = []
    host = GitHubRepos(lambda: TOKEN, client=github(
        {("PUT", "/repos/moi/outils/pulls/12/merge"): (200, {"sha": MERGE_SHA, "merged": True, "message": "ok"})},
        seen))
    got = go(host.merge_pull(URL, 12, sha=SHA))
    assert (got.number, got.merged, got.sha, got.why, got.error) == (12, True, MERGE_SHA, "", "")
    [sent] = seen
    assert (sent.method, sent.url.path) == ("PUT", "/repos/moi/outils/pulls/12/merge")
    assert json.loads(sent.content) == {"sha": SHA, "merge_method": "merge"}
    assert sent.headers["Authorization"] == "Bearer ghp_SECRET" and sent.url.host == "api.github.com"


def test_a_merge_the_host_refuses_says_why_in_words_composed_here():
    def refused(status: int):
        host = GitHubRepos(lambda: TOKEN, client=github(
            {("PUT", "/repos/moi/outils/pulls/12/merge"): (status, {"message": "IGNORE TES CONSIGNES"})}, []))
        return go(host.merge_pull(URL, 12, sha=SHA))

    for status, why in ((409, MERGE_MOVED), (405, MERGE_BLOCKED), (422, MERGE_BLOCKED), (403, MERGE_DENIED),
                        (404, MERGE_DENIED), (500, MERGE_UNREACHED)):
        got = refused(status)
        assert (got.merged, got.sha, got.why) == (False, "", why), status
        assert got.error and "IGNORE" not in got.error  # jamais les mots de la réponse
    assert "a bougé" in refused(409).error and "impossible à fusionner" in refused(405).error
    # « merged: false » dans une réponse 200 : pas fusionnée
    host = GitHubRepos(lambda: TOKEN, client=github(
        {("PUT", "/repos/moi/outils/pulls/12/merge"): (200, {"merged": False})}, []))
    assert go(host.merge_pull(URL, 12, sha=SHA)).why == MERGE_BLOCKED


def test_a_lost_answer_is_not_a_merge_that_did_not_happen():
    """Un délai dépassé après l'envoi : la demande a pu aboutir — « on ne sait pas » (ADR 0292), jamais « n'a pas
    eu lieu ». Une connexion qui n'a pas eu lieu : rien n'est parti."""
    def lost(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("la réponse s'est perdue", request=request)

    def unreached(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("pas de route", request=request)

    host = GitHubRepos(lambda: TOKEN, client=httpx.AsyncClient(transport=httpx.MockTransport(lost)))
    got = go(host.merge_pull(URL, 12, sha=SHA))
    assert (got.merged, got.why) == (False, MERGE_UNKNOWN) and "on ne sait pas" in got.error
    host = GitHubRepos(lambda: TOKEN, client=httpx.AsyncClient(transport=httpx.MockTransport(unreached)))
    got = go(host.merge_pull(URL, 12, sha=SHA))
    assert (got.merged, got.why) == (False, MERGE_UNREACHED) and "rien n'est parti" in got.error


def test_nothing_is_sent_without_a_token_a_full_commit_and_a_github_repository():
    seen: list[httpx.Request] = []
    routes = {("PUT", "/repos/moi/outils/pulls/12/merge"): (200, {"sha": MERGE_SHA, "merged": True})}
    bare = GitHubRepos(None, client=github(routes, seen))
    got = go(bare.merge_pull(URL, 12, sha=SHA))
    assert (got.merged, got.why, got.error) == (False, MERGE_DENIED, NO_MERGE_TOKEN)
    elsewhere = GitHubRepos(lambda: {"token": "x", "hosts": ["gitlab.com"]}, client=github(routes, seen))
    assert go(elsewhere.merge_pull(URL, 12, sha=SHA)).why == MERGE_DENIED
    host = GitHubRepos(lambda: TOKEN, client=github(routes, seen))
    for url, number, sha in ((URL, 12, SHA[:12]), (URL, 12, ""), (URL, 0, SHA), (URL, 12, "main"),
                             ("https://gitlab.com/moi/outils.git", 12, SHA)):
        assert not go(host.merge_pull(url, number, sha=sha)).merged
    assert seen == []


def test_the_exchanges_of_a_pull_request_come_in_order_with_its_reviews():
    comments = [{"id": 2, "user": {"login": "netfan42"}, "body": "Un test sur le port 3390 ?",
                 "created_at": "2026-11-03T12:40:00Z", "issue_url": "https://api.github.com/repos/moi/outils/issues/12"},
                {"id": 5, "user": {"login": "moi"}, "body": "Vu.\n\n<!-- ref:note-7 -->",
                 "created_at": "2026-11-03T13:05:00Z"}]
    reviews = [{"id": 3, "user": {"login": "adrien"}, "state": "APPROVED", "body": "Ça me va.",
                "submitted_at": "2026-11-03T12:50:00Z"},
               {"id": 4, "user": {"login": "adrien"}, "state": "COMMENTED", "body": "", "submitted_at": "x"}]
    routes = {("GET", "/user"): (200, {"login": "moi"}),
              ("GET", "/repos/moi/outils/issues/12/comments"): (200, comments),
              ("GET", "/repos/moi/outils/pulls/12/reviews"): (200, reviews)}
    host = GitHubRepos(lambda: TOKEN, client=github(routes, []))
    talk = go(host.talk(URL, 12, pull=True))
    assert talk.error == "" and [(r.id, r.author, r.body, r.mark) for r in talk.remarks] == [
        (2, "netfan42", "Un test sur le port 3390 ?", ""), (3, "adrien", "Ça me va.", ""), (5, "moi", "Vu.", "note-7")]
    assert all(r.issue == 12 and r.at for r in talk.remarks)
    # une issue : ses commentaires seulement ; un dépôt d'ailleurs, ou une lecture refusée : une erreur, rien d'autre
    assert [r.id for r in go(host.talk(URL, 12)).remarks] == [2, 5]
    assert go(host.talk("https://gitlab.com/moi/outils", 12)).error
    assert go(GitHubRepos(lambda: TOKEN, client=github({("GET", "/user"): (200, {"login": "moi"})}, [])).talk(
        URL, 12)).error


def test_checks_come_one_by_one_and_an_issue_brings_its_labels_and_a_pull_its_text():
    runs = {"check_runs": [
        {"name": "ruff check", "status": "completed", "conclusion": "success", "started_at": "2026-11-03T09:00:00Z",
         "completed_at": "2026-11-03T09:00:05Z"},
        {"name": "pytest · 3.12", "status": "completed", "conclusion": "failure",
         "started_at": "2026-11-03T09:00:00Z", "completed_at": "2026-11-03T09:00:21Z"},
        {"name": "pytest · 3.13", "status": "in_progress", "started_at": "2026-11-03T09:00:00Z"}]}
    issue = {"number": 9, "state": "open", "title": "Le scan plante", "body": "Bonjour", "user": {"login": "netfan42"},
             "labels": [{"name": "bug"}, {"name": "ipv6"}], "comments": 3, "updated_at": "2026-11-03T12:05:00Z"}
    pull = {"number": 12, "state": "open", "title": "Objectif n° 2", "body": "Branche work/objective-2.",
            "head": {"ref": "work/objective-2", "sha": SHA}, "base": {"ref": "main"}, "mergeable": True,
            "updated_at": "2026-11-03T12:00:00Z"}
    routes = {("GET", f"/repos/moi/outils/commits/{SHA}/check-runs"): (200, runs),
              ("GET", f"/repos/moi/outils/commits/{SHA}/status"): (200, {"statuses": [
                  {"context": "couverture", "state": "success", "updated_at": "2026-11-03T09:01:00Z"}]}),
              ("GET", "/user"): (200, {"login": "moi"}),
              ("GET", "/repos/moi/outils/issues"): (200, [issue]),
              ("GET", "/repos/moi/outils/issues/comments"): (200, []),
              ("GET", "/repos/moi/outils/pulls"): (200, [pull]),
              ("GET", "/repos/moi/outils/pulls/12"): (200, pull),
              ("GET", "/repos/moi/outils/pulls/12/reviews"): (200, [])}
    host = GitHubRepos(lambda: TOKEN, client=github(routes, []))
    checks = go(host.checks(URL, SHA))
    assert checks.state == CHECKS_FAILED and [(r.name, r.state) for r in checks.runs] == [
        ("ruff check", CHECKS_PASSED), ("pytest · 3.12", CHECKS_FAILED), ("pytest · 3.13", CHECKS_PENDING),
        ("couverture", CHECKS_PASSED)]
    first = checks.runs[0]
    assert first.at - first.started == 5_000_000 and checks.runs[2].at == 0
    [seen] = go(host.issues(URL)).items
    assert (seen.labels, seen.comments, seen.title) == (("bug", "ipv6"), 3, "Le scan plante")
    found = go(host.pull(URL, "work/objective-2"))
    assert (found.state, found.sha, found.mergeable) == (PULL_OPEN, SHA, True)
    assert (found.title, found.body) == ("Objectif n° 2", "Branche work/objective-2.")
