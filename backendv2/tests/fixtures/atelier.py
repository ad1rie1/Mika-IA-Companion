"""Un atelier en mémoire : le port ``Workshop`` sans bubblewrap ni git ; et un hôte de dépôt distant (``Host``).

Des fichiers par projet, un historique à la git (un commit d'amorce, puis un par
enregistrement qui a changé quelque chose, titré comme l'adaptateur le forme),
des envois et des récupérations qui ne sortent de nulle part : on y lit ce qui
a été demandé (``pushed``, ``pulled``).

Les vues des ateliers lus (ADR 0260) y sont des copies de ce qui était
enregistré au dernier commit (``committed``), gardées par (lecteur, lu) : on y
lit ce qui est posé (``views``), ce qui a été retiré (``dropped``) et les vues
qu'un programme a reçues (``ran``).

Un commit y a son identifiant complet (``full_sha``), et chaque commit garde
ce qui était enregistré à ce moment-là (``snapshots``) : le diff d'un commit à
un autre (``patch``), la copie d'un commit qu'une relecture lit (``checkout``,
``copies``, ``copy_ran``, ``discarded``) et ce que le dépôt distant possède
(``sent`` : le dernier envoi, la dernière récupération) s'y lisent (ADR 0277)."""

from __future__ import annotations

import hashlib
import re

from mika.ports.workshop import (
    NO_COMMIT,
    TOO_BIG,
    Commit,
    Hosted,
    OutsideWorkshop,
    RunResult,
    View,
    view_place,
)

#: l'instant d'un commit en mémoire (il n'a pas d'horloge : il compte)
STAMP = 1_790_000_000_000_000


def full_sha(project: int, n: int, kind: str = "c") -> str:
    """L'identifiant complet d'un commit en mémoire : quarante chiffres hexadécimaux, comme ceux de git. Le port ne
    rend que lui (``commit``, ``head``, ``commits``) ; l'abrégé (``short``) n'est qu'un affichage (``log``) — les
    deux ne sont jamais la même chaîne, pour qu'un code qui comparerait l'un à l'autre échoue ici comme sur le vrai
    atelier (ADR 0277)."""
    return hashlib.sha1(f"{kind}:{project}:{n}".encode()).hexdigest()


def short(sha: str) -> str:
    """L'abrégé d'un identifiant, tel que ``git log --format=%h`` le montre."""
    return sha[:7]


class Atelier:
    def __init__(self, *, token: str = "") -> None:
        self.files: dict[int, dict[str, str]] = {}
        self.dirty: dict[int, list[str]] = {}
        self.commits_: dict[int, list[tuple[str, str]]] = {}
        self.token = token
        self.pushed: list[tuple[int, str, str]] = []
        self.pushed_shas: list[str] = []
        self.pulled: list[tuple[int, str, str]] = []
        #: ce que chaque atelier a d'enregistré (le dernier commit), fichier par fichier
        self.committed: dict[int, dict[str, str]] = {}
        #: les vues posées, par (lecteur, lu) : la vue et les fichiers du commit vu
        self.views: dict[tuple[int, int], tuple[View, dict[str, str]]] = {}
        #: les ménages demandés : (lecteur, ce qu'il garde)
        self.dropped: list[tuple[int, tuple[int, ...]]] = []
        #: les programmes lancés : (projet, commande, les vues montées)
        self.ran: list[tuple[int, tuple[str, ...], tuple[int, ...]]] = []
        #: la place d'une vue (octets) ; ``None`` : sans limite
        self.view_bytes: int | None = None
        #: ce qui était enregistré à chaque commit, par projet puis par identifiant complet
        self.snapshots: dict[int, dict[str, dict[str, str]]] = {}
        #: ce que le dépôt distant possède, par (projet, adresse, branche)
        self.sent_: dict[tuple[int, str, str], str] = {}
        #: la copie de commit posée pour une relecture, par projet : le commit et ses fichiers ; les commandes
        #: lancées dans une copie (projet, commit, commande) ; les copies effacées
        self.copies: dict[int, tuple[str, dict[str, str]]] = {}
        self.copy_ran: list[tuple[int, str, tuple[str, ...]]] = []
        self.discarded: list[int] = []

    def exists(self, project: int) -> bool:
        return project in self.files

    def _check(self, path: str) -> None:
        if ".." in path.split("/") or path.startswith("/"):
            raise OutsideWorkshop(f"hors de l'atelier : {path}")

    async def tree(self, project: int, path: str = ".") -> list[str]:
        prefix = "" if path in (".", "") else path.strip("/") + "/"
        return [f"{p} ({len(t.encode())} o)" for p, t in sorted(self.files.get(project, {}).items())
                if not prefix or p.startswith(prefix) or p == path.strip("/")]

    async def read(self, project: int, path: str) -> str:
        self._check(path)
        if path not in self.files.get(project, {}):
            raise FileNotFoundError(f"{path} n'existe pas dans l'atelier")
        return self.files[project][path]

    async def write(self, project: int, path: str, content: str) -> str:
        self._check(path)
        self.files.setdefault(project, {})[path] = content
        self.dirty.setdefault(project, []).append(path)
        self.commits_.setdefault(project, [(full_sha(project, 0, "a"), "atelier ouvert")])
        return path

    async def edit(self, project: int, path: str, old: str, new: str) -> str:
        return await self.write(project, path, self.files[project][path].replace(old, new))

    async def write_bytes(self, project: int, path: str, data: bytes) -> str:
        return await self.write(project, path, data.decode("latin-1"))

    async def read_bytes(self, project: int, path: str, limit: int) -> bytes:
        self._check(path)
        if path not in self.files.get(project, {}):
            raise FileNotFoundError(path)
        return self.files[project][path].encode("latin-1")[:limit]

    async def run(self, project: int, argv, *, timeout_s=None, network: bool = False, views=()) -> RunResult:
        self.ran.append((project, tuple(argv), () if network else tuple(views)))
        return RunResult(tuple(argv), 0, stdout="tests : ok\n")

    async def commit(self, project: int, message: str, paths=()) -> str:
        dirty = self.dirty.get(project, [])
        taken = [d for d in dirty if not paths or d in paths]
        if not taken:
            return ""
        sha = full_sha(project, len(self.commits_[project]))
        self.commits_[project].append((sha, re.sub(r"\s+", " ", message).strip()[:72]))
        self.dirty[project] = [d for d in dirty if d not in taken]
        self.committed.setdefault(project, {}).update({d: self.files[project][d] for d in taken})
        self.snapshots.setdefault(project, {})[sha] = dict(self.committed[project])
        return sha

    async def pending(self, project: int) -> list[str]:
        return list(dict.fromkeys(self.dirty.get(project, [])))

    async def diff(self, project: int) -> str:
        return "".join(f"diff --git a/{p} b/{p}\n+++ b/{p}\n+{self.files[project][p][:40]}\n"
                       for p in self.dirty.get(project, []))

    async def log(self, project: int, n: int = 10, *, offset: int = 0) -> str:
        rows = list(reversed(self.commits_.get(project, [])))[offset:offset + n]
        return "\n".join(f"{short(sha)} {title}" for sha, title in rows)

    async def commits(self, project: int, n: int = 25, *, offset: int = 0) -> list[Commit]:
        rows = list(reversed(list(enumerate(self.commits_.get(project, [])))))[offset:offset + n]
        return [Commit(sha, STAMP + i * 60_000_000, title, "Mika", 1, 3, 0) for i, (sha, title) in rows]

    async def count(self, project: int) -> int:
        return len(self.commits_.get(project, []))

    def _known(self, project: int, sha: str) -> str:
        """L'identifiant complet du commit que ``sha`` désigne (complet, ou abrégé comme git l'accepte), ou ``""``."""
        return next((k for k, _ in self.commits_.get(project, []) if sha and k.startswith(sha)), "")

    async def show(self, project: int, sha: str) -> str:
        sha = self._known(project, sha)
        title = dict(self.commits_.get(project, [])).get(sha)
        return f"{sha}\nMika\n\n    {title}\n\ndiff --git a/x b/x\n@@ -1 +1 @@\n-avant\n+après\n" if title else ""

    async def head(self, project: int) -> str:
        commits = self.commits_.get(project, [])
        return commits[-1][0] if commits else ""

    async def branch(self, project: int) -> str:
        return "main" if project in self.commits_ else ""

    async def base(self, project: int) -> str:
        """Cet atelier n'a qu'une branche : sa base est sa tête."""
        return await self.head(project)

    async def compare(self, project: int, sha: str) -> tuple[int, int] | None:
        """Une histoire en ligne droite : un commit connu est derrière la tête d'autant de commits."""
        shas = [s for s, _ in self.commits_.get(project, [])]
        sha = self._known(project, sha)
        return (len(shas) - 1 - shas.index(sha), 0) if sha in shas else None

    async def push(self, project: int, url: str, branch: str, sha: str = "") -> RunResult:
        if not self.token:
            return RunResult(("git", "push"), None, refused="pas d'envoi : aucun jeton : règle-le dans "
                                                            "Connexions › Dépôts Git")
        self.pushed.append((project, url, branch))
        self.pushed_shas.append(sha)
        self.sent_[(project, url, branch)] = self._known(project, sha) or await self.head(project)
        return RunResult(("git", "push", url, branch), 0, stderr=f"To {url}\n * [new branch] HEAD -> {branch}\n")

    async def pull(self, project: int, url: str, branch: str) -> RunResult:
        self.pulled.append((project, url, branch))
        self.files.setdefault(project, {})["README.md"] = "# Récupéré\n"
        history = self.commits_.setdefault(project, [(full_sha(project, 0, "a"), "atelier ouvert")])
        history.append((full_sha(project, len(history), "r"), "depuis le distant"))
        self.committed.setdefault(project, {})["README.md"] = "# Récupéré\n"
        self.snapshots.setdefault(project, {})[history[-1][0]] = dict(self.committed[project])
        self.sent_[(project, url, branch)] = history[-1][0]
        return RunResult(("git", "pull", url, branch), 0, stdout="Fast-forward\n")

    # ── ce qu'une relecture lit (ADR 0276, 0277) ──
    async def sent(self, project: int, url: str, branch: str) -> str:
        return self.sent_.get((project, url, branch), "")

    async def patch(self, project: int, since: str, head: str, limit: int = 60_000) -> str | None:
        """Ce qui change de ``since`` à ``head`` : une entrée par fichier dont le contenu enregistré diffère."""
        end = self._known(project, head)
        start = self._known(project, since) if since else ""
        if not end or (since and not start):
            return None
        snaps = self.snapshots.get(project, {})
        before, after = snaps.get(start, {}), snaps.get(end, {})
        text = "".join(f"diff --git a/{p} b/{p}\n+++ b/{p}\n+{after[p][:200]}\n"
                       for p in sorted(after) if before.get(p) != after[p])
        return text[:limit]

    async def checkout(self, project: int, sha: str) -> str:
        full = self._known(project, sha)
        if not full:
            return NO_COMMIT
        self.copies[project] = (full, dict(self.snapshots.get(project, {}).get(full, {})))
        return ""

    def _copied(self, project: int, sha: str) -> dict[str, str]:
        full, files = self.copies.get(project, ("", {}))
        if not full or full != sha:
            raise FileNotFoundError(f"aucune copie du commit {sha[:12] or '?'} n'est posée")
        return files

    async def copy_tree(self, project: int, sha: str, path: str = ".") -> list[str]:
        files = self._copied(project, sha)
        self._check(path)
        prefix = "" if path in (".", "") else path.strip("/") + "/"
        return [f"{p} ({len(t.encode())} o)" for p, t in sorted(files.items())
                if not prefix or p.startswith(prefix) or p == path.strip("/")]

    async def copy_read(self, project: int, sha: str, path: str) -> str:
        files = self._copied(project, sha)
        self._check(path)
        if path not in files:
            raise FileNotFoundError(f"{path} n'existe pas dans le commit relu")
        return files[path]

    async def copy_run(self, project: int, sha: str, argv, *, timeout_s=None, views=()) -> RunResult:
        self._copied(project, sha)
        self.copy_ran.append((project, sha, tuple(argv)))
        return RunResult(tuple(argv), 0, stdout="tests : ok\n")

    async def discard(self, project: int) -> None:
        if self.copies.pop(project, None) is not None:
            self.discarded.append(project)

    # ── les vues des ateliers lus (ADR 0260) ──
    async def view(self, reader: int, target: int, *, fresh: bool = False) -> View:
        key = (reader, target)
        if key in self.views and not fresh:
            return self.views[key][0]
        commits = self.commits_.get(target, [])
        files = dict(self.committed.get(target, {}))
        if not commits or reader == target:
            view = View(target, why=NO_COMMIT)
        elif self.view_bytes is not None and sum(len(t.encode()) for t in files.values()) > self.view_bytes:
            view = View(target, why=TOO_BIG)
        else:
            view = View(target, commits[-1][0], STAMP + (len(commits) - 1) * 60_000_000)
        self.views[key] = (view, files if view.sha else {})
        return view

    def _viewed(self, reader: int, target: int) -> dict[str, str]:
        view, files = self.views.get((reader, target), (View(target), {}))
        if not view.sha:
            raise FileNotFoundError(f"aucune vue de l'atelier du projet n° {target} n'est posée")
        return files

    async def view_tree(self, reader: int, target: int, path: str = ".") -> list[str]:
        files = self._viewed(reader, target)
        self._check(path)
        prefix = "" if path in (".", "") else path.strip("/") + "/"
        return [f"{view_place(target, p)} ({len(t.encode())} o)" for p, t in sorted(files.items())
                if not prefix or p.startswith(prefix) or p == path.strip("/")]

    async def view_read(self, reader: int, target: int, path: str) -> str:
        files = self._viewed(reader, target)
        self._check(path)
        if path not in files:
            raise FileNotFoundError(f"{view_place(target, path)} n'existe pas dans la vue du projet n° {target}")
        return files[path]

    async def drop_views(self, reader: int, keep=()) -> None:
        kept = tuple(int(t) for t in keep)
        self.dropped.append((reader, kept))
        for key in [k for k in self.views if k[0] == reader and k[1] not in kept]:
            del self.views[key]


class Host:
    """Un hôte de dépôt distant en mémoire (le port ``RepoHost``) : ce qu'il rend, et ce qu'on lui a demandé."""

    def __init__(self, hosted: Hosted, gap: tuple[int, int] | None = None) -> None:
        self.hosted, self.gap, self.asked = hosted, gap, []

    def handles(self, url: str) -> bool:
        return url.startswith("https://github.com/")

    async def read(self, url: str, branch: str, *, fresh: bool = False, since: int = 0) -> Hosted:
        self.asked.append((url, branch, fresh, since))
        return self.hosted

    async def compare(self, url: str, base: str, head: str) -> tuple[int, int] | None:
        return self.gap
