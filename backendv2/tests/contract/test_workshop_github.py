"""L'hôte GitHub d'un dépôt distant, lu par son API (ADR 0183), contre un GitHub simulé (``httpx.MockTransport``) :

- la tête de la branche, ses derniers commits, les issues (sans les pull requests, que GitHub y mêle) et les pull
  requests ouvertes ; les liens composés à partir du dépôt, jamais repris de la réponse ;
- le jeton ne part qu'à ``api.github.com``, et seulement si ``github.com`` est parmi ses hôtes autorisés ;
- une branche absente ou un dépôt vide ne sont pas des erreurs ; un refus se dit en clair ;
- une lecture se garde, ``fresh`` et ``since`` la refont ; deux commits comparés le restent.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from mika.adapters.workshop.github import GitHubRepos, repo_of

URL = "https://github.com/moi/outils.git"
HEAD = "9" * 40
OLD = "8" * 40


def go(coro):
    return asyncio.run(coro)


def github(routes: dict[str, tuple[int, object]], seen: list[httpx.Request]) -> httpx.AsyncClient:
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = routes.get(request.url.path, (404, {"message": "Not Found"}))
        headers = {"x-ratelimit-remaining": "0"} if status == 403 else {}
        return httpx.Response(status, content=json.dumps(body).encode(), headers=headers)

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


def repo(**over: tuple[int, object]) -> dict[str, tuple[int, object]]:
    commit = {"sha": HEAD, "author": {"login": "adrien"},
              "commit": {"message": "Un titre\n\nle corps", "author": {"name": "A", "date": "2026-11-02T20:00:00Z"}}}
    routes = {
        "/repos/moi/outils": (200, {"description": "Des outils", "private": True, "open_issues_count": 3}),
        "/repos/moi/outils/commits": (200, [commit, {**commit, "sha": OLD}]),
        "/repos/moi/outils/issues": (200, [
            {"number": 7, "title": "Un bogue", "html_url": "https://ailleurs.example/piege", "user": {"login": "bea"},
             "updated_at": "2026-11-01T10:00:00Z", "labels": [{"name": "bug"}], "comments": 2},
            {"number": 8, "title": "Une PR mêlée aux issues", "pull_request": {}, "user": {"login": "bea"}}]),
        "/repos/moi/outils/pulls": (200, [
            {"number": 8, "title": "Une PR", "user": {"login": "bea"}, "updated_at": "2026-11-02T09:00:00Z",
             "head": {"ref": "fonction"}, "base": {"ref": "main"}, "draft": True}]),
    }
    routes.update(over)
    return routes


def test_the_branch_its_commits_issues_and_pull_requests_are_read():
    seen: list[httpx.Request] = []
    host = GitHubRepos(lambda: {"token": "ghp_SECRET", "hosts": ["github.com"]}, client=github(repo(), seen))
    got = go(host.read(URL, "main"))
    assert not got.error and got.name == "moi/outils" and got.private and got.about == "Des outils"
    assert got.head == HEAD and [k.title for k in got.commits] == ["Un titre", "Un titre"]
    assert got.commits[0].author == "adrien" and got.commits[0].at > 0
    assert [t.number for t in got.issues] == [7] and got.issues[0].labels == ("bug",)
    assert got.issues[0].url == "https://github.com/moi/outils/issues/7"  # composé, jamais repris de la réponse
    assert [(t.number, t.head, t.base, t.draft) for t in got.pulls] == [(8, "fonction", "main", True)]
    assert got.open_issues == 2 and got.open_pulls == 1  # GitHub compte issues et PR ensemble : 3 − 1
    assert all(r.url.host == "api.github.com" for r in seen)
    assert {r.headers.get("authorization") for r in seen} == {"Bearer ghp_SECRET"}
    assert dict(next(r for r in seen if r.url.path.endswith("/commits")).url.params)["sha"] == "main"


def test_the_token_goes_to_github_only_when_github_is_allowed():
    seen: list[httpx.Request] = []
    host = GitHubRepos(lambda: {"token": "ghp_SECRET", "hosts": ["git.exemple.org"]}, client=github(repo(), seen))
    assert not go(host.read(URL, "main")).error  # un dépôt public se lit sans lui
    assert all("authorization" not in r.headers for r in seen)
    assert repo_of("https://gitlab.com/moi/outils.git") is None and not host.handles("https://gitlab.com/moi/x")
    assert repo_of("https://github.com/moi/../x") is None and repo_of("https://github.com/moi/outils") == ("moi",
                                                                                                         "outils")
    assert "pas sur GitHub" in go(host.read("https://gitlab.com/moi/x.git", "main")).error


def test_a_missing_branch_is_not_an_error_but_a_refusal_is_said_plainly():
    seen: list[httpx.Request] = []
    empty = GitHubRepos(client=github(repo(**{"/repos/moi/outils/commits": (409, {"message": "empty"})}), seen))
    got = go(empty.read(URL, "main"))
    assert not got.error and got.head == "" and not got.commits  # le premier envoi créera la branche
    gone = GitHubRepos(client=github({}, seen))
    assert "introuvable" in go(gone.read(URL, "main")).error
    limited = GitHubRepos(client=github(repo(**{"/repos/moi/outils": (403, {})}), seen))
    assert "limite les lectures" in go(limited.read(URL, "main")).error
    moved = GitHubRepos(client=github(repo(**{"/repos/moi/outils": (301, {})}), seen))
    assert "renvoie ailleurs" in go(moved.read(URL, "main")).error  # une redirection ne se suit pas


def test_a_reading_is_kept_until_asked_again_or_outdated_by_an_exchange():
    seen: list[httpx.Request] = []
    clock = [100.0]
    host = GitHubRepos(client=github(repo(), seen), clock=lambda: clock[0], now=lambda: 5_000)
    first = go(host.read(URL, "main"))
    assert go(host.read(URL, "main")) is first and len(seen) == 4  # gardée
    assert go(host.read(URL, "main", fresh=True)) is first  # « relire » tout de suite : pas plus d'une fois par 10 s
    clock[0] += 11
    assert go(host.read(URL, "main", fresh=True)) is not first and len(seen) == 8
    clock[0] += 11
    kept = go(host.read(URL, "main", since=1_000))
    assert len(seen) == 8 and kept.read_at == 5_000  # un envoi d'avant la lecture : rien à refaire
    go(host.read(URL, "main", since=9_000))
    assert len(seen) == 12  # un envoi depuis : relue


def test_two_commits_are_compared_once():
    seen: list[httpx.Request] = []
    routes = {f"/repos/moi/outils/compare/{OLD}...{HEAD}": (200, {"ahead_by": 3, "behind_by": 1})}
    host = GitHubRepos(client=github(routes, seen))
    assert go(host.compare(URL, OLD, HEAD)) == (1, 3)  # (de l'atelier en plus, du distant en plus)
    assert go(host.compare(URL, OLD, HEAD)) == (1, 3) and len(seen) == 1
    assert go(host.compare(URL, HEAD, OLD)) is None  # GitHub ne connaît pas ce commit de l'atelier
    assert go(host.compare(URL, "HEAD~1", OLD)) is None and len(seen) == 2  # jamais une expression
