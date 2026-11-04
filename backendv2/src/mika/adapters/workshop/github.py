"""L'hôte GitHub d'un dépôt distant, lu par son API (ADR 0183) : la tête d'une branche, ses derniers commits, les
issues et pull requests ouvertes — pour la console, en lecture seule.

- **Le jeton** est celui des dépôts git (Réglages › Connexions › Dépôts git). Il n'est montré à ``api.github.com``
  que si ``github.com`` est parmi ses hôtes autorisés ; sans lui, un dépôt public se lit quand même (GitHub borne
  alors les lectures anonymes à soixante par heure).
- **Rien ne s'y égare** : ni redirection suivie, ni réponse de plus de ``MAX_BYTES``, un délai court (la page
  l'attend). Les liens montrés sont composés ici, à partir du dépôt et d'un numéro, jamais repris de la réponse.
- **Une lecture se garde** ``TTL_S`` (une erreur, ``ERROR_TTL_S``) ; ``fresh`` la refait, pas plus d'une fois par
  ``FRESH_S`` ; ``since`` aussi, quand elle date d'avant (un envoi depuis).
- Rien n'en va au journal ni au modèle : ce que GitHub dit ne se lit que dans la console.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from mika.adapters.workshop import DEFAULT_HOSTS
from mika.ports.workshop import Commit, Hosted, Ticket

API = "https://api.github.com"
HOST = "github.com"
#: un dépôt GitHub : ``https://github.com/compte/depot`` (``.git`` et la barre finale facultatifs)
_REPO = re.compile(r"^https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$")
_SHA = re.compile(r"^[0-9a-f]{4,40}$")
#: combien de commits, d'issues, de pull requests on lit
SHOWN = 20
TIMEOUT_S = 6.0
TTL_S = 120.0
ERROR_TTL_S = 30.0
FRESH_S = 10.0
MAX_BYTES = 2_000_000
#: au-delà, les plus anciennes lectures quittent le cache
CACHE_MAX = 64


def repo_of(url: str) -> tuple[str, str] | None:
    """(compte, dépôt) d'une adresse GitHub, ou ``None``."""
    m = _REPO.match((url or "").strip())
    if m is None or m.group(2) in (".", ".."):
        return None
    return m.group(1), m.group(2)


def _at(stamp: Any) -> int:
    """Un instant de GitHub (« 2026-11-02T21:06:47Z ») en µs ; 0 s'il est illisible."""
    try:
        return int(datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp() * 1_000_000)
    except (TypeError, ValueError):
        return 0


def _line(value: Any, limit: int = 300) -> str:
    """Un texte de GitHub en une ligne bornée."""
    return " ".join(str(value or "").split())[:limit]


class Refused(Exception):
    """GitHub a répondu, mais pas ce qu'on attendait : ``said`` le dit en clair."""

    def __init__(self, status: int, said: str) -> None:
        super().__init__(said)
        self.status, self.said = status, said


def _refusal(status: int, headers: httpx.Headers) -> str:
    if status == 401:
        return "GitHub refuse le jeton : vérifie-le dans Réglages › Connexions › Dépôts git"
    if status in (403, 429) and headers.get("x-ratelimit-remaining") == "0":
        return ("GitHub limite les lectures pour l'instant (sans jeton : soixante par heure) : réessaie plus tard, ou "
                "règle un jeton")
    if status == 403:
        return "GitHub refuse la lecture : le jeton n'a pas ce droit sur ce dépôt"
    if status == 404:
        return "dépôt introuvable sur GitHub (ou privé, et le jeton n'y a pas accès)"
    if 300 <= status < 400:
        return "GitHub renvoie ailleurs (dépôt renommé ou déplacé ?) : corrige l'adresse du dépôt distant"
    return f"GitHub a répondu {status}"


class GitHubRepos:
    """Le port ``RepoHost`` sur l'API de GitHub."""

    def __init__(self, credentials: Callable[[], Mapping[str, Any]] | None = None, *,
                 client: httpx.AsyncClient | None = None, clock: Callable[[], float] = time.monotonic,
                 now: Callable[[], int] | None = None) -> None:
        self.credentials = credentials
        self._client = client
        self._clock = clock
        self._now = now or (lambda: time.time_ns() // 1000)
        self._read: dict[tuple[str, str], tuple[float, Hosted]] = {}
        self._compared: dict[tuple[str, str, str], tuple[int, int] | None] = {}

    def handles(self, url: str) -> bool:
        return repo_of(url) is not None

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "mika-console"}
        creds = dict(self.credentials() if self.credentials is not None else {})
        token = str(creds.get("token") or "").strip()
        hosts = creds.get("hosts") or DEFAULT_HOSTS
        allowed = {str(h).strip().lower() for h in (hosts.split(",") if isinstance(hosts, str) else hosts)}
        if token and HOST in allowed:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _get(self, client: httpx.AsyncClient, path: str, params: Mapping[str, Any] | None = None) -> Any:
        async with client.stream("GET", f"{API}{path}", params=dict(params or {}), headers=self._headers()) as resp:
            if resp.status_code != 200:
                raise Refused(resp.status_code, _refusal(resp.status_code, resp.headers))
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise Refused(200, "GitHub a répondu trop long : lecture abandonnée")
        return json.loads(bytes(body))

    def _open(self) -> httpx.AsyncClient:
        return self._client or httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False)

    async def _close(self, client: httpx.AsyncClient) -> None:
        if client is not self._client:
            await client.aclose()

    async def read(self, url: str, branch: str, *, fresh: bool = False, since: int = 0) -> Hosted:
        repo = repo_of(url)
        if repo is None:
            return Hosted(name="", url="", branch=branch, error="ce dépôt n'est pas sur GitHub : ni issues ni pull "
                                                                "requests à lire ici")
        key = (f"{repo[0]}/{repo[1]}".lower(), branch)
        kept = self._read.get(key)
        if kept is not None:
            age = self._clock() - kept[0]
            stale = since > kept[1].read_at and age >= FRESH_S
            if not stale and age < (FRESH_S if fresh else ERROR_TTL_S if kept[1].error else TTL_S):
                return kept[1]
        got = await self._fetch(*repo, branch)
        self._read[key] = (self._clock(), got)
        while len(self._read) > CACHE_MAX:
            self._read.pop(min(self._read, key=lambda k: self._read[k][0]))
        return got

    async def _fetch(self, owner: str, name: str, branch: str) -> Hosted:
        base, page = f"/repos/{owner}/{name}", f"https://{HOST}/{owner}/{name}"
        shell = Hosted(name=f"{owner}/{name}", url=page, branch=branch, read_at=self._now())
        client = self._open()
        try:
            got = await asyncio.wait_for(asyncio.gather(
                self._get(client, base),
                self._get(client, f"{base}/commits", {"sha": branch, "per_page": SHOWN}),
                self._get(client, f"{base}/issues", {"state": "open", "sort": "updated", "per_page": SHOWN + 10}),
                self._get(client, f"{base}/pulls", {"state": "open", "sort": "updated", "direction": "desc",
                                                    "per_page": SHOWN}),
                return_exceptions=True), TIMEOUT_S + 2)
        except TimeoutError:
            return replace(shell, error="GitHub ne répond pas à temps")
        finally:
            await self._close(client)
        meta, commits, issues, pulls = got
        # la branche peut ne pas exister encore (404), ou le dépôt être vide (409) : pas une erreur
        if isinstance(commits, Refused) and commits.status in (404, 409) and not isinstance(meta, BaseException):
            commits = []
        for part in (meta, commits, issues, pulls):
            if isinstance(part, Refused):
                return replace(shell, error=part.said)
            if isinstance(part, httpx.HTTPError):
                return replace(shell, error=f"GitHub ne répond pas ({type(part).__name__})")
            if isinstance(part, BaseException):
                return replace(shell, error="GitHub a répondu quelque chose d'illisible")
        try:
            return self._shaped(shell, meta, commits, issues, pulls)
        except (AttributeError, KeyError, TypeError, ValueError):
            return replace(shell, error="GitHub a répondu quelque chose d'illisible")

    def _shaped(self, shell: Hosted, meta: Any, commits: Any, issues: Any, pulls: Any) -> Hosted:
        page = shell.url
        listed = []
        for item in commits[:SHOWN]:
            sha = str(item.get("sha") or "")
            if not _SHA.match(sha):
                continue
            said = item.get("commit") or {}
            who = (item.get("author") or {}).get("login") or (said.get("author") or {}).get("name") or ""
            listed.append(Commit(sha, _at((said.get("author") or {}).get("date")),
                                 _line(str(said.get("message") or "").split("\n", 1)[0], 200), _line(who, 80)))
        tickets = [i for i in issues if "pull_request" not in i][:SHOWN]
        opened = [Ticket(int(i["number"]), _line(i.get("title")), f"{page}/issues/{int(i['number'])}",
                         _line((i.get("user") or {}).get("login"), 80), _at(i.get("updated_at")),
                         tuple(_line(x.get("name"), 40) for x in (i.get("labels") or [])[:6] if isinstance(x, dict)),
                         int(i.get("comments") or 0)) for i in tickets]
        asked = [Ticket(int(r["number"]), _line(r.get("title")), f"{page}/pull/{int(r['number'])}",
                        _line((r.get("user") or {}).get("login"), 80), _at(r.get("updated_at")),
                        tuple(_line(x.get("name"), 40) for x in (r.get("labels") or [])[:6] if isinstance(x, dict)),
                        0, _line((r.get("head") or {}).get("ref"), 100), _line((r.get("base") or {}).get("ref"), 100),
                        bool(r.get("draft"))) for r in pulls[:SHOWN]]
        more_pulls = len(pulls) >= SHOWN
        # GitHub compte ensemble issues et pull requests ouvertes : les siennes s'en déduisent quand on les a toutes
        total = int(meta.get("open_issues_count") or 0)
        open_issues = len(opened) if more_pulls else max(len(opened), total - len(asked))
        return replace(shell, about=_line(meta.get("description")), private=bool(meta.get("private")),
                       head=listed[0].sha if listed else "", commits=tuple(listed), issues=tuple(opened),
                       pulls=tuple(asked), open_issues=open_issues, open_pulls=len(asked),
                       more_issues=open_issues > len(opened), more_pulls=more_pulls)

    async def compare(self, url: str, base: str, head: str) -> tuple[int, int] | None:
        repo = repo_of(url)
        if repo is None or not _SHA.match(base or "") or not _SHA.match(head or ""):
            return None
        key = (f"{repo[0]}/{repo[1]}".lower(), base, head)
        if key in self._compared:  # deux commits ne changent pas : leur écart non plus
            return self._compared[key]
        client = self._open()
        try:
            data = await asyncio.wait_for(
                self._get(client, f"/repos/{repo[0]}/{repo[1]}/compare/{quote(base)}...{quote(head)}"), TIMEOUT_S)
            gap = (int(data["behind_by"]), int(data["ahead_by"]))
        except Refused as exc:
            if exc.status != 404:
                return None
            gap = None  # GitHub ne connaît pas ce commit de l'atelier : jamais poussé
        except (TimeoutError, httpx.HTTPError, KeyError, TypeError, ValueError):
            return None
        finally:
            await self._close(client)
        if len(self._compared) >= CACHE_MAX * 4:
            self._compared.clear()
        self._compared[key] = gap
        return gap


__all__ = ["GitHubRepos", "repo_of"]
