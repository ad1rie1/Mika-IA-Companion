"""L'hôte GitHub d'un dépôt distant, par son API : pour la console (ADR 0183), la tête d'une branche, ses derniers
commits, les issues et pull requests ouvertes ; pour un projet qui passe par des pull requests (ADR 0274), ouvrir
celle d'une branche de travail (``open_pull``) et la relire (``pull``) ; et, pour le reflet des tickets (ADR 0275),
lire les issues et leurs commentaires, en ouvrir une, la fermer ou la rouvrir, y publier un commentaire, dire les
vérifications d'un commit et rendre la fin du journal d'un échec. Pour l'écran d'une personne (ADR 0288), les
échanges d'une pull request ou d'une issue (``talk``) et les vérifications une à une. Rien d'autre ne s'y écrit —
sauf **la fusion d'une pull request** (``merge_pull``, ADR 0288), le geste d'une personne : le seul ``PUT`` d'ici.

- **Le jeton** est celui des dépôts git (Connexions › Dépôts Git). Il n'est montré à ``api.github.com``
  que si ``github.com`` est parmi ses hôtes autorisés ; sans lui, un dépôt public se lit quand même (GitHub borne
  alors les lectures anonymes à soixante par heure).
- **Rien ne s'y égare** : ni redirection suivie, ni réponse de plus de ``MAX_BYTES``, un délai court (la page
  l'attend). Les liens montrés sont composés ici, à partir du dépôt et d'un numéro, jamais repris de la réponse.
- **Une lecture se garde** ``TTL_S`` (une erreur, ``ERROR_TTL_S``) ; ``fresh`` la refait, pas plus d'une fois par
  ``FRESH_S`` ; ``since`` aussi, quand elle date d'avant (un envoi depuis).
- Ce que la console lit de GitHub ne va ni au journal ni au modèle. L'état d'une pull request suivie, lui, est
  rendu à qui le demande (``pull``) : son numéro, son état, ce que ses relecteurs demandent, et ce que l'hôte en dit —
  le texte d'un inconnu sur un dépôt public, borné, que l'appelant cite comme une donnée.
- **Seul qui a un rôle sur le dépôt y demande ou y lève des changements** (ADR 0278). Sur un dépôt public, tout
  compte peut déposer une relecture : ne comptent que celles de son propriétaire, d'un membre de l'organisation
  qui le possède ou d'un collaborateur (``author_association`` : ``_ROLES``), la dernière qui tranche de chacun.
  Une demande de changements tient tant que son auteur ne l'a pas levée — ou qu'elle n'a pas été écartée là-bas.
  Le commentaire cité suit le même filtre. Relectures et commentaires se lisent par leur fin (``_recent`` : les
  dernières pages) : GitHub les rend de la plus ancienne à la plus récente.
- **Ouvrir une pull request** demande un jeton autorisé pour ``github.com`` : sans lui, rien n'est envoyé. Il lui
  faut, sur le dépôt, le contenu et les pull requests en lecture et écriture (un jeton à portée fine : « Contents »
  et « Pull requests » en « Read and write » ; un jeton classique : ``repo``). Une pull request déjà ouverte pour la
  branche est rendue telle quelle : jamais deux.
- **Les issues** (ADR 0275). Écrire demande le même jeton, avec « Issues » en « Read and write ». Ce qui part d'ici
  porte un **repère** (un commentaire HTML, invisible à la lecture) : une issue ou un commentaire qui le porte déjà
  est retrouvé, jamais doublé. Un repère ne vaut que sur ce qu'a écrit le compte du jeton (``mine``, lu une fois par
  ``/user``) : un inconnu qui le recopie n'y gagne rien. Ce que les autres y écrivent — titre, texte, commentaire,
  nom de compte — est rendu borné, sur une ligne : des données, que l'appelant cite.
- **Les vérifications** d'un commit se lisent dans ses « check runs » et ses statuts (« Checks » et « Commit
  statuses » en lecture ; l'un des deux suffit). La fin du journal d'un échec se télécharge ailleurs que chez l'API :
  GitHub renvoie vers une adresse signée, lue **sans le jeton**, en ``https`` seulement, sa fin seulement.
- **Fusionner** (ADR 0288) demande le même jeton que pour ouvrir une pull request (le contenu et les pull requests
  en lecture et écriture), et nomme le commit au bout de la branche : GitHub refuse si elle a bougé depuis (409), ou
  s'il la dit impossible à fusionner (405 : un conflit, une règle de la branche, plus ouverte). Une fusion ordinaire
  (un commit de fusion) ; ce que GitHub répond se dit en mots composés ici.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from mika.adapters.workshop import DEFAULT_HOSTS
from mika.ports.workshop import (
    CHECK_RUNS_MAX,
    CHECKS_FAILED,
    CHECKS_NAMED,
    CHECKS_NONE,
    CHECKS_PASSED,
    CHECKS_PENDING,
    ISSUE_BODY_MAX,
    ISSUE_CLOSED,
    ISSUE_OPEN,
    ISSUE_TITLE_MAX,
    ISSUES_READ,
    LABELS_MAX,
    LOG_TAIL_MAX,
    MARK_MAX,
    MERGE_BLOCKED,
    MERGE_DENIED,
    MERGE_MOVED,
    MERGE_UNKNOWN,
    MERGE_UNREACHED,
    PULL_BODY_MAX,
    PULL_CLOSED,
    PULL_MERGED,
    PULL_OPEN,
    PULL_SAID_MAX,
    REMARK_MAX,
    REVIEW_CHANGES,
    TALK_MAX,
    CheckLog,
    CheckRun,
    Checks,
    Commit,
    Hosted,
    Issue,
    Issues,
    Merged,
    Pull,
    Remark,
    Talk,
    Ticket,
)

API = "https://api.github.com"
HOST = "github.com"
#: un dépôt GitHub : ``https://github.com/compte/depot`` (``.git`` et la barre finale facultatifs)
_REPO = re.compile(r"^https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$")
_SHA = re.compile(r"^[0-9a-f]{4,40}$")
#: une branche qu'on nomme à GitHub (celle d'une pull request, celle où elle veut entrer)
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
#: les relectures et les commentaires relus pour dire où en est une pull request : par page, et combien de pages,
#: en partant de la fin (les plus récents)
REVIEWS_READ, COMMENTS_READ = 50, 50
PAGES_READ = 3
#: qui a un rôle sur le dépôt, tel que GitHub le dit de l'auteur d'une relecture ou d'un commentaire
#: (``author_association``) : son propriétaire, un membre de l'organisation qui le possède, un collaborateur. Tout
#: autre compte (``CONTRIBUTOR``, ``NONE``…) n'en a pas : ce qu'il dépose ne demande ni ne lève rien (ADR 0278)
_ROLES = ("OWNER", "MEMBER", "COLLABORATOR")
#: les relectures qui tranchent : des changements demandés, une approbation, une relecture écartée
_DECISIVE = ("CHANGES_REQUESTED", "APPROVED", "DISMISSED")
#: le numéro de la dernière page d'une liste, lu dans l'en-tête ``Link`` (l'adresse, elle, est composée ici)
_LAST_PAGE = re.compile(r'[?&]page=(\d+)[^>]*>\s*;\s*rel="last"')
#: un titre et un texte de pull request, au plus (caractères)
TITLE_MAX, BODY_MAX = 200, 20_000
NO_TOKEN = ("aucun jeton autorisé pour github.com : une pull request ne s'ouvre pas sans lui (Connexions › Dépôts "
            "Git)")
#: le repère de ce qui part d'ici (ADR 0275) : un commentaire HTML à la fin du texte, invisible à la lecture
_MARK_NAME = re.compile(rf"[a-z0-9][a-z0-9-]{{0,{MARK_MAX - 1}}}")
_MARK = re.compile(rf"\s*<!--\s*ref:({_MARK_NAME.pattern})\s*-->")
NO_ISSUE_TOKEN = ("aucun jeton autorisé pour github.com : rien ne s'écrit dans ses issues sans lui (Connexions › "
                  "Dépôts Git)")
NOT_HERE = "ce dépôt n'est pas sur GitHub : pas d'issues à y lire ni à y écrire"
#: pourquoi une fusion n'a pas eu lieu (ADR 0288), en mots composés ici — jamais ceux de la réponse
NO_MERGE_TOKEN = ("aucun jeton autorisé pour github.com : une pull request ne se fusionne pas sans lui (Connexions "
                  "› Dépôts Git)")
MERGE_SAID = {
    MERGE_MOVED: "sa branche a bougé chez GitHub depuis le commit que tu as lu : relis-la, puis recommence",
    MERGE_BLOCKED: "GitHub la dit impossible à fusionner : un conflit avec la base, une règle de la branche, ou "
                   "elle n'est plus ouverte",
    MERGE_UNREACHED: "GitHub n'a pas été joint : rien n'est parti",
    MERGE_UNKNOWN: "GitHub n'a pas répondu à temps : on ne sait pas si elle a été fusionnée",
}
#: ce qu'une vérification achevée dit quand elle a échoué (les « check runs »), et un statut en échec
_RUN_FAILED = ("failure", "timed_out", "startup_failure", "action_required")
_STATUS_FAILED = ("failure", "error")
#: la fin d'un journal : ce qu'on en demande à l'hôte (octets), et ce qu'on accepte d'en lire s'il rend tout
LOG_BYTES, LOG_READ_MAX = 64_000, 8_000_000
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ?")
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


def _unmarked(text: Any) -> tuple[str, str]:
    """(le repère que porte ce texte, le texte sans lui)."""
    raw = str(text or "")
    found = _MARK.search(raw)
    return (found.group(1), _MARK.sub("", raw)) if found is not None else ("", raw)


def _with_mark(text: str, mark: str) -> str:
    return f"{_MARK.sub('', text).rstrip()}\n\n<!-- ref:{mark} -->"


def _tail(text: str, limit: int = LOG_TAIL_MAX) -> str:
    """La fin d'un journal, lisible : sans couleurs ni horodatage en tête de ligne, ses dernières lignes entières."""
    rows = [_STAMP.sub("", _ANSI.sub("", row)).rstrip() for row in str(text or "").replace("\r", "").split("\n")]
    kept = "\n".join(row for row in rows if row.strip())
    if len(kept) <= limit:
        return kept
    cut = kept[-limit:]
    return cut.partition("\n")[2] or cut


class Refused(Exception):
    """GitHub a répondu, mais pas ce qu'on attendait : ``said`` le dit en clair."""

    def __init__(self, status: int, said: str) -> None:
        super().__init__(said)
        self.status, self.said = status, said


def _refusal(status: int, headers: httpx.Headers) -> str:
    if status == 401:
        return "GitHub refuse le jeton : vérifie-le dans Connexions › Dépôts Git"
    if status in (403, 429) and headers.get("x-ratelimit-remaining") == "0":
        return ("GitHub limite les lectures pour l'instant (sans jeton : soixante par heure) : réessaie plus tard, ou "
                "règle un jeton")
    if status == 403:
        return "GitHub refuse : le jeton n'a pas ce droit sur ce dépôt"
    if status == 422:
        return ("GitHub refuse la pull request : la branche n'a rien de plus que sa base, ou l'une des deux n'existe "
                "pas chez lui")
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
        #: le compte du jeton (le condensé du jeton, son nom là-bas) : lu une fois, tant que le jeton ne change pas
        self._who: tuple[str, str] | None = None
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

    def writes(self, url: str) -> bool:
        return repo_of(url) is not None

    async def _get(self, client: httpx.AsyncClient, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return await self._ask(client, "GET", path, params)

    async def _ask(self, client: httpx.AsyncClient, method: str, path: str,
                   params: Mapping[str, Any] | None = None, sent: Mapping[str, Any] | None = None) -> Any:
        """Une demande à l'API de GitHub, et à elle seule (``API``) : c'est le seul hôte qui voit le jeton."""
        return (await self._exchange(client, method, path, params, sent))[0]

    async def _exchange(self, client: httpx.AsyncClient, method: str, path: str,
                        params: Mapping[str, Any] | None = None,
                        sent: Mapping[str, Any] | None = None) -> tuple[Any, httpx.Headers]:
        """La même demande, avec les en-têtes de la réponse (la pagination s'y lit)."""
        more = {} if sent is None else {"content": json.dumps(dict(sent)).encode(),
                                        "headers": {**self._headers(), "Content-Type": "application/json"}}
        async with client.stream(method, f"{API}{path}", params=dict(params or {}),
                                 **({"headers": self._headers()} | more)) as resp:
            if resp.status_code not in ((200,) if sent is None else (200, 201)):
                raise Refused(resp.status_code, _refusal(resp.status_code, resp.headers))
            body = bytearray()
            async for chunk in resp.aiter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise Refused(200, "GitHub a répondu trop long : lecture abandonnée")
            headers = resp.headers
        return json.loads(bytes(body)), headers

    async def _recent(self, client: httpx.AsyncClient, path: str, per_page: int) -> list[Any]:
        """La fin d'une liste que GitHub rend de la plus ancienne à la plus récente (les relectures d'une pull
        request, ses commentaires), dans cet ordre : sa dernière page et celles d'avant, ``PAGES_READ`` au plus. Le
        numéro de la dernière page vient de l'en-tête ``Link`` ; l'adresse demandée est composée ici, jamais
        reprise de la réponse. Lire la première page seulement rendait les plus anciens, pas les derniers."""
        first, headers = await self._exchange(client, "GET", path, {"per_page": per_page})
        if not isinstance(first, list):
            return []
        found = _LAST_PAGE.search(headers.get("link", ""))
        last = int(found.group(1)) if found is not None else 1
        if last <= 1:
            return first
        wanted = range(max(2, last - PAGES_READ + 1), last + 1)
        more = await asyncio.gather(*(self._get(client, path, {"per_page": per_page, "page": n}) for n in wanted))
        kept = first if last <= PAGES_READ else []  # la première page n'en est que si la fenêtre remonte jusqu'à elle
        return [*kept, *(x for page in more if isinstance(page, list) for x in page)]

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

    # ── la pull request d'une branche de travail (ADR 0274) ──
    def _pull(self, page: str, item: Mapping[str, Any]) -> Pull:
        number = int(item["number"])
        state = PULL_MERGED if item.get("merged_at") else PULL_OPEN if item.get("state") == "open" else PULL_CLOSED
        return Pull(number=number, url=f"{page}/pull/{number}", state=state,
                    head=_line((item.get("head") or {}).get("ref"), 100),
                    base=_line((item.get("base") or {}).get("ref"), 100),
                    sha=str((item.get("head") or {}).get("sha") or "")[:40], at=_at(item.get("updated_at")),
                    read_at=self._now(), title=_line(item.get("title"), ISSUE_TITLE_MAX),
                    body=str(item.get("body") or "").strip()[:PULL_BODY_MAX])

    @staticmethod
    def _role(item: Mapping[str, Any]) -> bool:
        """L'auteur de cette relecture, ou de ce commentaire, a-t-il un rôle sur le dépôt (ADR 0278) ?"""
        return str(item.get("author_association") or "").upper() in _ROLES

    async def _said(self, client: httpx.AsyncClient, base: str, found: Pull) -> Pull:
        """Ce que l'hôte dit d'une pull request (ADR 0278). Ouverte : des changements y sont demandés quand un
        relecteur **qui a un rôle sur le dépôt** en demande dans sa dernière relecture qui tranche — une approbation
        de lui, ou sa relecture écartée, les lève ; celle d'un autre non, et celle d'un compte sans rôle ne demande
        ni ne lève rien. Ce qu'il en dit : le texte de la plus récente de ces demandes, sinon le dernier commentaire
        de qui a un rôle ; fermée sans qu'aucun d'eux ait rien dit, son dernier commentaire tout court, donné pour
        celui d'un compte sans rôle. Toujours le texte d'un inconnu, borné."""
        review, said, by, when, role = "", "", "", 0, False
        if found.state == PULL_OPEN:
            reviews = await self._recent(client, f"{base}/pulls/{found.number}/reviews", REVIEWS_READ)
            standing: dict[str, Mapping[str, Any]] = {}
            for r in reviews:  # de la plus ancienne à la plus récente : la dernière de chaque relecteur reste
                who = _line((r.get("user") or {}).get("login"), 80) if isinstance(r, dict) else ""
                if who and r.get("state") in _DECISIVE and self._role(r):
                    standing[who] = r
            asked = [(who, r) for who, r in standing.items() if r.get("state") == "CHANGES_REQUESTED"]
            if asked:
                who, last = max(asked, key=lambda x: _at(x[1].get("submitted_at")))
                review, when = REVIEW_CHANGES, _at(last.get("submitted_at"))
                said, by, role = _line(last.get("body"), PULL_SAID_MAX), who, True
        if not said and (review or found.state == PULL_CLOSED):
            comments = [x for x in await self._recent(client, f"{base}/issues/{found.number}/comments",
                                                      COMMENTS_READ) if isinstance(x, dict)]
            # une demande de changements sans texte ne se dit pas par les mots d'un passant
            ranked = [x for x in comments if self._role(x)] or ([] if review else comments)
            if ranked:
                last = ranked[-1]
                said, by = _line(last.get("body"), PULL_SAID_MAX), _line((last.get("user") or {}).get("login"), 80)
                role = self._role(last)
        # sans mots, personne à nommer
        return replace(found, review=review, review_at=when, said=said, said_by=by if said else "",
                       said_role=bool(said) and role)

    async def _find(self, client: httpx.AsyncClient, owner: str, name: str, head: str) -> Pull:
        base, page = f"/repos/{owner}/{name}", f"https://{HOST}/{owner}/{name}"
        listed = await self._get(client, f"{base}/pulls", {"head": f"{owner}:{head}", "state": "all",
                                                           "sort": "created", "direction": "desc", "per_page": 10})
        mine = [x for x in listed if isinstance(x, dict) and (x.get("head") or {}).get("ref") == head]
        if not mine:
            return Pull(head=head, read_at=self._now())
        chosen = next((x for x in mine if x.get("state") == "open"), mine[0])
        found = self._pull(page, chosen)
        if found.state == PULL_OPEN:
            found = replace(found, mergeable=await self._mergeable(client, base, found.number))
        return await self._said(client, base, found)

    async def _mergeable(self, client: httpx.AsyncClient, base: str, number: int) -> bool | None:
        """Ce que GitHub dit de la fusion d'une pull request ouverte (ADR 0280) : possible, impossible — sa branche
        est en conflit avec celle où elle veut entrer —, ou rien encore (il le recalcule après chaque envoi, et la
        liste des pull requests ne le porte pas : il faut la lire elle-même). Une lecture refusée ne dit rien."""
        try:
            one = await self._get(client, f"{base}/pulls/{number}")
        except Refused:
            return None
        said = one.get("mergeable") if isinstance(one, dict) else None
        return said if isinstance(said, bool) else None

    async def pull(self, url: str, head: str) -> Pull:
        repo = repo_of(url)
        if repo is None or not _BRANCH.match(head or ""):
            return Pull(head=head, error="ce dépôt n'est pas sur GitHub, ou la branche ne se nomme pas ainsi")
        client = self._open()
        try:
            return await asyncio.wait_for(self._find(client, *repo, head), TIMEOUT_S * 2)
        except Refused as exc:
            return Pull(head=head, error=exc.said)
        except TimeoutError:
            return Pull(head=head, error="GitHub ne répond pas à temps")
        except httpx.HTTPError as exc:
            return Pull(head=head, error=f"GitHub ne répond pas ({type(exc).__name__})")
        except (AttributeError, KeyError, TypeError, ValueError):
            return Pull(head=head, error="GitHub a répondu quelque chose d'illisible")
        finally:
            await self._close(client)

    async def open_pull(self, url: str, *, head: str, base: str, title: str, body: str) -> Pull:
        repo = repo_of(url)
        if repo is None:
            return Pull(head=head, error="ce dépôt n'est pas sur GitHub : pas de pull request à y ouvrir")
        if not _BRANCH.match(head or "") or not _BRANCH.match(base or "") or head == base:
            return Pull(head=head, error="une pull request part d'une branche de travail vers une autre branche")
        if "Authorization" not in self._headers():  # sans jeton pour cet hôte, rien n'est envoyé
            return Pull(head=head, error=NO_TOKEN)
        found = await self.pull(url, head)
        if found.error or found.state == PULL_OPEN:  # déjà ouverte pour cette branche : jamais deux
            return found
        owner, name = repo
        client = self._open()
        try:
            made = await asyncio.wait_for(self._ask(
                client, "POST", f"/repos/{owner}/{name}/pulls",
                sent={"title": title.strip()[:TITLE_MAX], "head": head, "base": base, "body": body[:BODY_MAX]}),
                TIMEOUT_S * 2)
            return self._pull(f"https://{HOST}/{owner}/{name}", made)
        except Refused as exc:
            return Pull(head=head, error=exc.said)
        except TimeoutError:
            return Pull(head=head, error="GitHub ne répond pas à temps")
        except httpx.HTTPError as exc:
            return Pull(head=head, error=f"GitHub ne répond pas ({type(exc).__name__})")
        except (AttributeError, KeyError, TypeError, ValueError):
            return Pull(head=head, error="GitHub a répondu quelque chose d'illisible")
        finally:
            await self._close(client)

    # ── les issues, reflet des tickets (ADR 0275) ──
    async def _try(self, work: Callable[[httpx.AsyncClient], Awaitable[Any]], failed: Callable[[str], Any]) -> Any:
        """Une demande menée jusqu'au bout, ou ``failed(pourquoi)`` : un refus se dit, il ne lève pas."""
        client = self._open()
        try:
            return await asyncio.wait_for(work(client), TIMEOUT_S * 2)
        except Refused as exc:
            return failed(exc.said)
        except TimeoutError:
            return failed("GitHub ne répond pas à temps")
        except httpx.HTTPError as exc:
            return failed(f"GitHub ne répond pas ({type(exc).__name__})")
        except (AttributeError, KeyError, TypeError, ValueError):
            return failed("GitHub a répondu quelque chose d'illisible")
        finally:
            await self._close(client)

    async def _me(self, client: httpx.AsyncClient) -> str:
        """Le nom du compte du jeton chez GitHub (vide : pas de jeton pour cet hôte)."""
        token = self._headers().get("Authorization", "")
        if not token:
            return ""
        key = hashlib.sha256(token.encode()).hexdigest()
        if self._who is not None and self._who[0] == key:
            return self._who[1]
        # s'il ne se lit pas, la demande échoue : mieux vaut ne rien lire que prendre ses propres issues pour
        # celles d'un inconnu
        login = _line((await self._get(client, "/user")).get("login"), 80)
        self._who = (key, login)
        return login

    def _issue(self, page: str, item: Mapping[str, Any], me: str) -> Issue:
        number = int(item["number"])
        closed = item.get("state") == "closed"
        mark, body = _unmarked(item.get("body"))
        author = _line((item.get("user") or {}).get("login"), 80)
        # un repère ne vaut que sur ce qu'a écrit le compte du jeton : recopié par un autre, il n'est rien
        return Issue(number=number, url=f"{page}/issues/{number}", state=ISSUE_CLOSED if closed else ISSUE_OPEN,
                     dropped=closed and item.get("state_reason") == "not_planned",
                     title=_line(item.get("title"), ISSUE_TITLE_MAX), body=_line(body, ISSUE_BODY_MAX), author=author,
                     mark=mark if me and author == me else "", state_at=_at(item.get("closed_at")) if closed else 0,
                     at=_at(item.get("updated_at")), read_at=self._now(),
                     labels=tuple(_line(x.get("name"), 40) for x in (item.get("labels") or [])[:LABELS_MAX]
                                  if isinstance(x, dict)), comments=int(item.get("comments") or 0))

    @staticmethod
    def _remark(item: Mapping[str, Any], me: str, issue: int = 0) -> Remark:
        mark, body = _unmarked(item.get("body"))
        author = _line((item.get("user") or {}).get("login"), 80)
        tail = str(item.get("issue_url") or "").rsplit("/", 1)[-1]
        # son heure est celle de sa création : elle ne bouge plus — retouché, il ne repasse pas devant les autres
        return Remark(id=int(item["id"]), issue=issue or (int(tail) if tail.isdecimal() else 0), author=author,
                      body=_line(body, REMARK_MAX), mark=mark if me and author == me else "",
                      at=_at(item.get("created_at") or item.get("updated_at")))

    async def _issues(self, client: httpx.AsyncClient, owner: str, name: str) -> Issues:
        base, page = f"/repos/{owner}/{name}", f"https://{HOST}/{owner}/{name}"
        me = await self._me(client)
        listed, said = await asyncio.gather(
            self._get(client, f"{base}/issues", {"state": "all", "sort": "updated", "direction": "desc",
                                                 "per_page": ISSUES_READ}),
            # les derniers écrits, pas les derniers retouchés : retoucher d'anciens commentaires ne chasse pas les
            # nouveaux de la lecture (ADR 0278)
            self._get(client, f"{base}/issues/comments", {"sort": "created", "direction": "desc",
                                                          "per_page": ISSUES_READ}))
        items = tuple(self._issue(page, x, me) for x in listed if isinstance(x, dict) and "pull_request" not in x)
        remarks = tuple(self._remark(x, me) for x in said if isinstance(x, dict))
        return Issues(items=items, remarks=tuple(r for r in remarks if r.issue), read_at=self._now())

    async def issues(self, url: str) -> Issues:
        repo = repo_of(url)
        if repo is None:
            return Issues(error=NOT_HERE)
        return await self._try(lambda client: self._issues(client, *repo), lambda why: Issues(error=why))

    def _writable(self, url: str) -> tuple[str, str] | str:
        """Le dépôt où écrire, ou pourquoi rien ne s'y écrit : sans jeton pour cet hôte, rien n'est envoyé."""
        repo = repo_of(url)
        if repo is None:
            return NOT_HERE
        return repo if "Authorization" in self._headers() else NO_ISSUE_TOKEN

    async def open_issue(self, url: str, *, title: str, body: str, mark: str) -> Issue:
        repo = self._writable(url)
        if isinstance(repo, str):
            return Issue(error=repo)
        if not _MARK_NAME.fullmatch(mark or "") or not title.strip():
            return Issue(error="une issue s'ouvre avec un titre et un repère")
        owner, name = repo

        async def work(client: httpx.AsyncClient) -> Issue:
            seen = await self._issues(client, owner, name)
            found = next((x for x in seen.items if x.mark == mark), None)
            if found is not None:  # déjà ouverte pour ce repère : jamais deux
                return found
            made = await self._ask(client, "POST", f"/repos/{owner}/{name}/issues",
                                   sent={"title": title.strip()[:TITLE_MAX], "body": _with_mark(body[:BODY_MAX], mark)})
            return self._issue(f"https://{HOST}/{owner}/{name}", made, await self._me(client))

        return await self._try(work, lambda why: Issue(error=why))

    async def set_issue(self, url: str, number: int, *, closed: bool, dropped: bool = False) -> Issue:
        repo = self._writable(url)
        if isinstance(repo, str):
            return Issue(error=repo)
        if number <= 0:
            return Issue(error="cette issue n'a pas de numéro")
        owner, name = repo
        sent = {"state": "closed", "state_reason": "not_planned" if dropped else "completed"} if closed else \
            {"state": "open"}

        async def work(client: httpx.AsyncClient) -> Issue:
            made = await self._ask(client, "PATCH", f"/repos/{owner}/{name}/issues/{int(number)}", sent=sent)
            return self._issue(f"https://{HOST}/{owner}/{name}", made, await self._me(client))

        return await self._try(work, lambda why: Issue(number=number, error=why))

    async def remark(self, url: str, number: int, *, body: str, mark: str) -> Remark:
        repo = self._writable(url)
        if isinstance(repo, str):
            return Remark(error=repo)
        if number <= 0 or not _MARK_NAME.fullmatch(mark or "") or not body.strip():
            return Remark(error="un commentaire se publie sur une issue, avec un texte et un repère")
        owner, name = repo

        async def work(client: httpx.AsyncClient) -> Remark:
            me = await self._me(client)
            said = await self._get(client, f"/repos/{owner}/{name}/issues/{int(number)}/comments", {"per_page": 100})
            found = next((r for r in (self._remark(x, me, number) for x in said if isinstance(x, dict))
                          if r.mark == mark), None)
            if found is not None:  # déjà publié : jamais deux
                return found
            made = await self._ask(client, "POST", f"/repos/{owner}/{name}/issues/{int(number)}/comments",
                                   sent={"body": _with_mark(body[:BODY_MAX], mark)})
            return self._remark(made, me, number)

        return await self._try(work, lambda why: Remark(issue=number, error=why))

    # ── les vérifications d'un commit (ADR 0275) ──
    async def _runs(self, client: httpx.AsyncClient, base: str, sha: str) -> tuple[list[Any], list[Any]]:
        """Ses « check runs » et ses statuts ; l'un des deux peut se refuser (un droit qui manque) : l'autre suffit."""
        got = await asyncio.gather(self._get(client, f"{base}/commits/{sha}/check-runs", {"per_page": 100}),
                                   self._get(client, f"{base}/commits/{sha}/status"), return_exceptions=True)
        if all(isinstance(x, BaseException) for x in got):
            raise got[0]
        runs = got[0].get("check_runs") or [] if isinstance(got[0], dict) else []
        statuses = got[1].get("statuses") or [] if isinstance(got[1], dict) else []
        return [x for x in runs if isinstance(x, dict)], [x for x in statuses if isinstance(x, dict)]

    async def checks(self, url: str, sha: str) -> Checks:
        repo = repo_of(url)
        if repo is None or not _SHA.match(sha or ""):
            return Checks(sha=sha, error="ce dépôt n'est pas sur GitHub, ou ce commit ne se nomme pas ainsi")

        async def work(client: httpx.AsyncClient) -> Checks:
            runs, statuses = await self._runs(client, f"/repos/{repo[0]}/{repo[1]}", sha)
            failed = [_line(r.get("name"), 80) for r in runs
                      if r.get("status") == "completed" and r.get("conclusion") in _RUN_FAILED]
            failed += [_line(s.get("context"), 80) for s in statuses if s.get("state") in _STATUS_FAILED]
            pending = [r for r in runs if r.get("status") != "completed"] + \
                [s for s in statuses if s.get("state") == "pending"]
            state = CHECKS_NONE if not (runs or statuses) else CHECKS_FAILED if failed else \
                CHECKS_PENDING if pending else CHECKS_PASSED
            at = max([0, *(_at(r.get("completed_at")) for r in runs), *(_at(s.get("updated_at")) for s in statuses)])
            one = [CheckRun(_line(r.get("name"), 80),
                            CHECKS_PENDING if r.get("status") != "completed" else
                            CHECKS_FAILED if r.get("conclusion") in _RUN_FAILED else CHECKS_PASSED,
                            _at(r.get("started_at")), _at(r.get("completed_at"))) for r in runs]
            one += [CheckRun(_line(s.get("context"), 80),
                             CHECKS_FAILED if s.get("state") in _STATUS_FAILED else
                             CHECKS_PENDING if s.get("state") == "pending" else CHECKS_PASSED,
                             _at(s.get("created_at")), _at(s.get("updated_at"))) for s in statuses]
            return Checks(sha=sha, state=state, failed=tuple(dict.fromkeys(failed))[:CHECKS_NAMED], at=at,
                          read_at=self._now(), runs=tuple(one[:CHECK_RUNS_MAX]))

        return await self._try(work, lambda why: Checks(sha=sha, error=why))

    async def _log(self, client: httpx.AsyncClient, path: str) -> str:
        """La fin du journal d'un travail d'Actions. GitHub ne le sert pas lui-même : il renvoie vers une adresse
        signée, ailleurs. Elle est lue en ``https`` seulement, **sans le jeton** — c'est un autre hôte —, sans suivre
        d'autre renvoi, et sa fin seulement."""
        async with client.stream("GET", f"{API}{path}", headers=self._headers()) as resp:
            if resp.status_code not in (301, 302, 307):
                raise Refused(resp.status_code, _refusal(resp.status_code, resp.headers))
            where = httpx.URL(resp.headers.get("location", ""))
        if where.scheme != "https" or not where.host:
            raise Refused(302, "GitHub renvoie le journal vers une adresse qui ne se lit pas")
        plain = {"User-Agent": "mika-console", "Range": f"bytes=-{LOG_BYTES}"}  # ni jeton, ni rien qui le porte
        async with client.stream("GET", where, headers=plain) as resp:
            if resp.status_code not in (200, 206):
                raise Refused(resp.status_code, f"le journal ne se lit pas ({resp.status_code})")
            kept, read = bytearray(), 0
            async for chunk in resp.aiter_bytes():
                read += len(chunk)
                if read > LOG_READ_MAX:
                    raise Refused(200, "le journal est trop long : sa fin ne se lit pas")
                kept = (kept + chunk)[-LOG_BYTES:]
        return bytes(kept).decode("utf-8", "replace")

    async def check_log(self, url: str, sha: str) -> CheckLog:
        repo = repo_of(url)
        if repo is None or not _SHA.match(sha or ""):
            return CheckLog(sha=sha, error="ce dépôt n'est pas sur GitHub, ou ce commit ne se nomme pas ainsi")
        base = f"/repos/{repo[0]}/{repo[1]}"

        async def work(client: httpx.AsyncClient) -> CheckLog:
            runs, _ = await self._runs(client, base, sha)
            bad = next((r for r in runs if r.get("status") == "completed" and r.get("conclusion") in _RUN_FAILED),
                       None)
            if bad is None:
                return CheckLog(sha=sha, error="aucune vérification en échec dont le journal se lise ici")
            name = _line(bad.get("name"), 80)
            try:
                text = await self._log(client, f"{base}/actions/jobs/{int(bad['id'])}/logs")
            except (Refused, httpx.HTTPError, KeyError, TypeError, ValueError):
                text = ""
            if not text.strip():  # pas un travail d'Actions, ou son journal a expiré : ce que la vérification en dit
                out = bad.get("output") or {}
                text = "\n".join(str(out.get(k) or "") for k in ("title", "summary", "text") if out.get(k))
            tail = _tail(text)
            return CheckLog(sha=sha, name=name, tail=tail,
                            error="" if tail else "son journal ne se lit pas (expiré, ou elle n'en a pas)")

        return await self._try(work, lambda why: CheckLog(sha=sha, error=why))

    # ── pour l'écran d'une personne : les échanges, et la fusion (ADR 0288) ──
    async def talk(self, url: str, number: int, *, pull: bool = False) -> Talk:
        repo = repo_of(url)
        if repo is None or number <= 0:
            return Talk(error=NOT_HERE)
        base = f"/repos/{repo[0]}/{repo[1]}"

        async def work(client: httpx.AsyncClient) -> Talk:
            me = await self._me(client)
            said = [self._remark(x, me, number)
                    for x in await self._recent(client, f"{base}/issues/{int(number)}/comments", COMMENTS_READ)
                    if isinstance(x, dict)]
            if pull:  # le texte de ses relectures : une relecture sans mots n'est pas un échange
                reviews = await self._recent(client, f"{base}/pulls/{int(number)}/reviews", REVIEWS_READ)
                said += [self._remark({**r, "created_at": r.get("submitted_at")}, me, number)
                         for r in reviews if isinstance(r, dict) and str(r.get("body") or "").strip()]
            said.sort(key=lambda r: (r.at, r.id))
            return Talk(remarks=tuple(said[-TALK_MAX:]), read_at=self._now())

        return await self._try(work, lambda why: Talk(error=why))

    async def merge_pull(self, url: str, number: int, *, sha: str) -> Merged:
        """La fusion d'une pull request, pour le geste d'une personne (ADR 0288) : seulement si le commit au bout de
        sa branche est ``sha``. Une fusion ordinaire, dans la base que la pull request nomme. Rien d'autre d'elle ne
        change, et rien n'est forcé."""
        repo = repo_of(url)
        if repo is None or number <= 0 or not _SHA.fullmatch(sha or "") or len(sha) != 40:
            return Merged(number=number, why=MERGE_UNREACHED,
                          error="ce dépôt n'est pas sur GitHub, ou cette pull request ne se nomme pas ainsi")
        if "Authorization" not in self._headers():  # sans jeton pour cet hôte, rien n'est envoyé
            return Merged(number=number, why=MERGE_DENIED, error=NO_MERGE_TOKEN)
        owner, name = repo
        client = self._open()
        try:
            made = await asyncio.wait_for(self._ask(
                client, "PUT", f"/repos/{owner}/{name}/pulls/{int(number)}/merge",
                sent={"sha": sha, "merge_method": "merge"}), TIMEOUT_S * 2)
            done = isinstance(made, dict) and made.get("merged") is True
            return Merged(number=number, merged=done, sha=str(made.get("sha") or "")[:40] if done else "",
                          why="" if done else MERGE_BLOCKED, error="" if done else MERGE_SAID[MERGE_BLOCKED])
        except Refused as exc:
            why = MERGE_MOVED if exc.status == 409 else MERGE_BLOCKED if exc.status in (405, 422) else \
                MERGE_DENIED if exc.status in (401, 403, 404) else MERGE_UNREACHED
            return Merged(number=number, why=why, error=exc.said if why == MERGE_DENIED else MERGE_SAID[why])
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            # la connexion n'a pas eu lieu : la demande n'est pas partie
            return Merged(number=number, why=MERGE_UNREACHED, error=MERGE_SAID[MERGE_UNREACHED])
        except (TimeoutError, httpx.HTTPError, AttributeError, KeyError, TypeError, ValueError):
            # la demande est partie, sa réponse s'est perdue ou ne se lit pas : elle a pu avoir lieu (ADR 0292)
            return Merged(number=number, why=MERGE_UNKNOWN, error=MERGE_SAID[MERGE_UNKNOWN])
        finally:
            await self._close(client)

    async def edit_pull(self, url: str, number: int, *, title: str | None = None, body: str | None = None) -> Pull:
        """Le titre et le texte d'une pull request, pour le geste d'une personne (ADR 0290) : un ``PATCH`` qui ne
        porte que ces deux champs — ni son état, ni sa base. Sans jeton pour cet hôte, rien n'est envoyé."""
        repo = repo_of(url)
        sent = {k: v for k, v in (("title", (title or "").strip()[:TITLE_MAX] if title is not None else None),
                                  ("body", body[:BODY_MAX] if body is not None else None)) if v}
        if repo is None or number <= 0 or not sent:
            return Pull(number=number, error="ce dépôt n'est pas sur GitHub, ou rien n'est à changer")
        if "Authorization" not in self._headers():
            return Pull(number=number, error=NO_TOKEN)
        owner, name = repo
        client = self._open()
        try:
            made = await asyncio.wait_for(self._ask(
                client, "PATCH", f"/repos/{owner}/{name}/pulls/{int(number)}", sent=sent), TIMEOUT_S * 2)
            return self._pull(f"https://{HOST}/{owner}/{name}", made)
        except Refused as exc:
            return Pull(number=number, error=exc.said)
        except TimeoutError:
            return Pull(number=number, error="GitHub ne répond pas à temps")
        except httpx.HTTPError as exc:
            return Pull(number=number, error=f"GitHub ne répond pas ({type(exc).__name__})")
        except (AttributeError, KeyError, TypeError, ValueError):
            return Pull(number=number, error="GitHub a répondu quelque chose d'illisible")
        finally:
            await self._close(client)


__all__ = ["GitHubRepos", "repo_of"]
