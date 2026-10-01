"""Un atelier en mémoire : le port ``Workshop`` sans bubblewrap ni git.

Des fichiers par projet, un historique à la git (un commit d'amorce, puis un par
enregistrement qui a changé quelque chose, titré comme l'adaptateur le forme),
des envois et des récupérations qui ne sortent de nulle part : on y lit ce qui
a été demandé (``pushed``, ``pulled``)."""

from __future__ import annotations

import re

from mika.ports.workshop import Commit, OutsideWorkshop, RunResult

#: l'instant d'un commit en mémoire (il n'a pas d'horloge : il compte)
STAMP = 1_790_000_000_000_000


class Atelier:
    def __init__(self, *, token: str = "") -> None:
        self.files: dict[int, dict[str, str]] = {}
        self.dirty: dict[int, list[str]] = {}
        self.commits_: dict[int, list[tuple[str, str]]] = {}
        self.token = token
        self.pushed: list[tuple[int, str, str]] = []
        self.pushed_shas: list[str] = []
        self.pulled: list[tuple[int, str, str]] = []

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
        self.commits_.setdefault(project, [("a000000", "atelier ouvert")])
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

    async def run(self, project: int, argv, *, timeout_s=None, network: bool = False) -> RunResult:
        return RunResult(tuple(argv), 0, stdout="tests : ok\n")

    async def commit(self, project: int, message: str, paths=()) -> str:
        dirty = self.dirty.get(project, [])
        taken = [d for d in dirty if not paths or d in paths]
        if not taken:
            return ""
        sha = f"c{len(self.commits_[project]):06d}"
        self.commits_[project].append((sha, re.sub(r"\s+", " ", message).strip()[:72]))
        self.dirty[project] = [d for d in dirty if d not in taken]
        return sha

    async def pending(self, project: int) -> list[str]:
        return list(dict.fromkeys(self.dirty.get(project, [])))

    async def diff(self, project: int) -> str:
        return "".join(f"diff --git a/{p} b/{p}\n+++ b/{p}\n+{self.files[project][p][:40]}\n"
                       for p in self.dirty.get(project, []))

    async def log(self, project: int, n: int = 10, *, offset: int = 0) -> str:
        rows = list(reversed(self.commits_.get(project, [])))[offset:offset + n]
        return "\n".join(f"{sha} {title}" for sha, title in rows)

    async def commits(self, project: int, n: int = 25, *, offset: int = 0) -> list[Commit]:
        rows = list(reversed(list(enumerate(self.commits_.get(project, [])))))[offset:offset + n]
        return [Commit(sha, STAMP + i * 60_000_000, title, "Mika", 1, 3, 0) for i, (sha, title) in rows]

    async def count(self, project: int) -> int:
        return len(self.commits_.get(project, []))

    async def show(self, project: int, sha: str) -> str:
        title = dict(self.commits_.get(project, [])).get(sha)
        return f"{sha}\nMika\n\n    {title}\n\ndiff --git a/x b/x\n@@ -1 +1 @@\n-avant\n+après\n" if title else ""

    async def head(self, project: int) -> str:
        commits = self.commits_.get(project, [])
        return commits[-1][0] if commits else ""

    async def push(self, project: int, url: str, branch: str, sha: str = "") -> RunResult:
        if not self.token:
            return RunResult(("git", "push"), None, refused="pas d'envoi : aucun jeton : règle-le dans "
                                                            "Configuration › Canaux › Dépôts git")
        self.pushed.append((project, url, branch))
        self.pushed_shas.append(sha)
        return RunResult(("git", "push", url, branch), 0, stderr=f"To {url}\n * [new branch] HEAD -> {branch}\n")

    async def pull(self, project: int, url: str, branch: str) -> RunResult:
        self.pulled.append((project, url, branch))
        self.files.setdefault(project, {})["README.md"] = "# Récupéré\n"
        self.commits_.setdefault(project, [("a000000", "atelier ouvert")]).append(("r000001", "depuis le distant"))
        return RunResult(("git", "pull", url, branch), 0, stdout="Fast-forward\n")
