"""Le faux hôte de dépôts du banc du travail (ADR 0279) : des dépôts git nus sur ce disque, des pull requests, des
issues et des vérifications en mémoire — le port ``RepoHost`` entier, sans réseau.

Le scénario de la chaîne en a besoin pour que le flux par pull request (ADR 0274), les issues et la CI (ADR 0275)
tournent comme en vrai : l'atelier pousse et récupère par son vrai git, mais vers un dépôt nu d'ici
(``BenchWorkshop``), et tout ce que le moteur lit de l'hôte vient de ``FakeHost``.

- ``FakeHost`` : ce que le moteur lui demande (lire, ouvrir une pull request, la relire, les issues, les
  vérifications), et **les gestes des gens de l'autre côté** — le propriétaire qui fusionne ou renvoie une pull
  request, un inconnu qui ouvre une issue, un commit accepté sur la branche principale. Chaque geste est noté
  (``hote.jsonl``) : le juge lit ce qui s'est passé là-bas.
- ``BenchWorkshop`` : le vrai atelier (bubblewrap), dont le git distant est rejoué hors de la cage vers le dépôt nu
  de l'adresse visée. Une commande réseau, elle, est refusée : rien ne sort de la machine.

Une fusion est une vraie fusion (``git merge-tree``, deux parents) : une branche partie d'une base ancienne ne défait
pas ce qui a été accepté depuis ; un conflit laisse la pull request ouverte, et l'hôte la dit alors impossible à
fusionner à qui la relit (``Pull.mergeable``, ADR 0280).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from mika.adapters.workshop import BwrapWorkshop
from mika.ports.workshop import (
    BASE_BRANCH,
    CHECKS_FAILED,
    CHECKS_NONE,
    CHECKS_PASSED,
    CHECKS_PENDING,
    ISSUE_CLOSED,
    ISSUE_OPEN,
    PULL_CLOSED,
    PULL_MERGED,
    PULL_OPEN,
    REVIEW_CHANGES,
    CheckLog,
    Checks,
    Commit,
    Hosted,
    Issue,
    Issues,
    Pull,
    Remark,
    RunResult,
    Ticket,
)

#: le nom de l'hôte : un domaine réservé (RFC 2606), qui ne répondrait à personne si une adresse sortait quand même
HOST = "depots.banc.example"
US = 1_000_000
MINUTE = 60 * US
#: l'environnement de son git : aucune configuration de la machine, une identité à lui
_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "HOME": "/tmp",
        "LC_ALL": "C", "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
_IDENT = ("-c", "user.name=Hôte du banc", "-c", "user.email=hote@banc.example", "-c", "commit.gpgsign=false",
          "-c", f"init.defaultBranch={BASE_BRANCH}")


def url_of(name: str) -> str:
    """L'adresse d'un dépôt de l'hôte (« mirette/mirette » → ``https://depots.banc.example/mirette/mirette.git``)."""
    return f"https://{HOST}/{name}.git"


def _git(where: Path, *args: str, date: int = 0, check: bool = True) -> str:
    env = dict(_ENV)
    if date:  # une histoire datée à l'heure virtuelle : deux mesures font les mêmes commits
        stamp = f"{date // US} +0000"
        env.update(GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
    done = subprocess.run(["git", "-C", str(where), *_IDENT, *args], capture_output=True, text=True, env=env,
                          check=False)
    if check and done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} : {done.stderr.strip()[-300:]}")
    return done.stdout.strip() if done.returncode == 0 else ""


@dataclass(slots=True)
class Depot:
    """Un dépôt chez l'hôte : son dépôt nu, ses pull requests, ses issues, ses vérifications."""

    name: str
    path: Path
    #: a-t-il une CI ? Sinon ses commits n'ont aucune vérification (``CHECKS_NONE``)
    ci: bool = False
    pulls: list[Pull] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    remarks: list[Remark] = field(default_factory=list)
    #: quand chaque commit est arrivé (µs virtuelles), et ceux dont la CI échoue
    arrived: dict[str, int] = field(default_factory=dict)
    failing: dict[str, str] = field(default_factory=dict)

    def ref(self, name: str) -> str:
        return _git(self.path, "rev-parse", "--verify", "-q", f"{name}^{{commit}}", check=False)


class FakeHost:
    """Le port ``RepoHost``, servi d'ici. ``clock`` : l'horloge virtuelle du scénario ; ``ci_minutes`` : le temps que
    mettent les vérifications d'un commit à passer."""

    def __init__(self, root: Path, clock: Any, *, ci_minutes: int = 6,
                 log: Callable[[str], None] | None = None) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.ci_us = ci_minutes * MINUTE
        self.depots: dict[str, Depot] = {}
        self.say = log or (lambda text: None)
        self.file = (self.root / "hote.jsonl").open("a")
        #: ce que le moteur lui a demandé, compté par méthode (les lectures comprises)
        self.asked: dict[str, int] = {}

    # ── le monter ──
    def create(self, name: str, source: Path, *, ci: bool = False, message: str = "Premier dépôt",
               at: int = 0) -> str:
        """Un dépôt dont la branche principale porte les fichiers de ``source`` ; rend son adresse."""
        path = self.root / f"{name.replace('/', '--')}.git"
        _git(self.root, "init", "-q", "--bare", str(path))
        work = self.root / f".pose-{path.stem}"
        _git(self.root, "clone", "-q", str(path), str(work))
        for f in sorted(p for p in Path(source).rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            target = work / f.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f.read_bytes())
        _git(work, "add", "-A")
        _git(work, "commit", "-q", "-m", message, date=at or self.clock.now())
        _git(work, "push", "-q", "origin", f"HEAD:refs/heads/{BASE_BRANCH}")
        subprocess.run(["rm", "-rf", str(work)], check=False)
        depot = self.depots[name] = Depot(name, path, ci=ci)
        depot.arrived[depot.ref(BASE_BRANCH)] = at or self.clock.now()
        self._note("depot", name, commit=depot.ref(BASE_BRANCH)[:12])
        return url_of(name)

    def depot(self, url: str) -> Depot | None:
        got = re.fullmatch(rf"https://{re.escape(HOST)}/(.+?)(?:\.git)?/?", (url or "").strip())
        return self.depots.get(got.group(1)) if got else None

    def _note(self, what: str, name: str, **more: Any) -> None:
        self.file.write(json.dumps({"t": self.clock.now(), "quoi": what, "depot": name, **more},
                                   ensure_ascii=False) + "\n")
        self.file.flush()

    def _count(self, method: str) -> None:
        self.asked[method] = self.asked.get(method, 0) + 1

    def close(self) -> None:
        self.file.close()

    # ── ce que l'atelier y pousse et y récupère (``BenchWorkshop``) ──
    def received(self, depot: Depot, branch: str) -> None:
        sha = depot.ref(branch)
        if sha and sha not in depot.arrived:
            depot.arrived[sha] = self.clock.now()
        self._note("pousse", depot.name, branche=branch, commit=sha[:12])
        # une pull request ouverte suit sa branche
        depot.pulls = [replace(p, sha=sha, at=self.clock.now()) if p.state == PULL_OPEN and p.head == branch else p
                       for p in depot.pulls]

    # ── le port : lire ──
    def handles(self, url: str) -> bool:
        return self.depot(url) is not None

    def writes(self, url: str) -> bool:
        return self.handles(url)

    def _page(self, depot: Depot, what: str, number: int) -> str:
        return f"https://{HOST}/{depot.name}/{what}/{number}"

    async def read(self, url: str, branch: str, *, fresh: bool = False, since: int = 0) -> Hosted:
        self._count("read")
        depot = self.depot(url)
        if depot is None:
            return Hosted(name="", url=url, branch=branch, error="dépôt inconnu de l'hôte du banc")
        head = depot.ref(branch)
        commits = []
        for line in _git(depot.path, "log", "-15", "--format=%H%x09%ct%x09%an%x09%s", head, check=False).splitlines() \
                if head else []:
            sha, when, author, title = line.split("\t", 3)
            commits.append(Commit(sha, int(when) * US, title, author))
        issues = [Ticket(i.number, i.title, i.url, i.author, i.at) for i in depot.issues if i.state == ISSUE_OPEN]
        pulls = [Ticket(p.number, f"{p.head} → {p.base}", p.url, at=p.at, head=p.head, base=p.base)
                 for p in depot.pulls if p.state == PULL_OPEN]
        return Hosted(name=depot.name, url=f"https://{HOST}/{depot.name}", branch=branch, host="Hôte du banc",
                      head=head, commits=tuple(commits), issues=tuple(issues), pulls=tuple(pulls),
                      open_issues=len(issues), open_pulls=len(pulls), read_at=self.clock.now())

    async def compare(self, url: str, base: str, head: str) -> tuple[int, int] | None:
        self._count("compare")
        depot = self.depot(url)
        if depot is None or not depot.ref(base) or not depot.ref(head):
            return None
        behind, ahead = _git(depot.path, "rev-list", "--left-right", "--count", f"{base}...{head}").split()
        return int(behind), int(ahead)

    # ── le port : les pull requests ──
    async def open_pull(self, url: str, *, head: str, base: str, title: str, body: str) -> Pull:
        self._count("open_pull")
        depot = self.depot(url)
        if depot is None:
            return Pull(head=head, error="dépôt inconnu de l'hôte du banc")
        for p in depot.pulls:
            if p.state == PULL_OPEN and p.head == head:
                return replace(p, read_at=self.clock.now())
        sha = depot.ref(head)
        if not sha:
            return Pull(head=head, error=f"la branche « {head} » n'est pas chez l'hôte")
        number = len(depot.pulls) + len(depot.issues) + 1
        made = Pull(number=number, url=self._page(depot, "pull", number), state=PULL_OPEN, head=head, base=base,
                    sha=sha, at=self.clock.now(), read_at=self.clock.now())
        depot.pulls.append(made)
        self._note("pull_request", depot.name, numero=number, branche=head, base=base, titre=title, texte=body,
                   commit=sha[:12])
        self.say(f"hôte : pull request n° {number} ouverte sur {depot.name} ({head} → {base}) « {title} »")
        return made

    async def pull(self, url: str, head: str) -> Pull:
        self._count("pull")
        depot = self.depot(url)
        if depot is None:
            return Pull(head=head, error="dépôt inconnu de l'hôte du banc")
        mine = [p for p in depot.pulls if p.head == head]
        if not mine:
            return Pull(head=head, read_at=self.clock.now())
        got = next((p for p in mine if p.state == PULL_OPEN), mine[-1])
        # ce qu'il dit de sa fusion (ADR 0280) : une pull request ouverte dont la branche est en conflit avec la
        # base ne peut pas être fusionnée — le moteur le lit ici, sans attendre que le propriétaire s'y casse le nez
        able = self.mergeable(url, got) if got.state == PULL_OPEN else None
        return replace(got, mergeable=able, read_at=self.clock.now())

    # ── le port : les issues ──
    async def issues(self, url: str) -> Issues:
        self._count("issues")
        depot = self.depot(url)
        if depot is None:
            return Issues(error="dépôt inconnu de l'hôte du banc")
        now = self.clock.now()
        return Issues(items=tuple(replace(i, read_at=now) for i in depot.issues), remarks=tuple(depot.remarks),
                      read_at=now)

    async def open_issue(self, url: str, *, title: str, body: str, mark: str) -> Issue:
        self._count("open_issue")
        depot = self.depot(url)
        if depot is None:
            return Issue(error="dépôt inconnu de l'hôte du banc")
        for i in depot.issues:
            if mark and i.mark == mark:
                return i
        return self._issue(depot, title, body, author="mika-banc", mark=mark)

    def _issue(self, depot: Depot, title: str, body: str, *, author: str, mark: str = "") -> Issue:
        number = len(depot.pulls) + len(depot.issues) + 1
        made = Issue(number=number, url=self._page(depot, "issues", number), state=ISSUE_OPEN, title=title, body=body,
                     author=author, mark=mark, at=self.clock.now(), read_at=self.clock.now())
        depot.issues.append(made)
        self._note("issue", depot.name, numero=number, titre=title, texte=body, auteur=author, repere=mark)
        self.say(f"hôte : issue n° {number} ouverte sur {depot.name} par {author} « {title} »")
        return made

    async def set_issue(self, url: str, number: int, *, closed: bool, dropped: bool = False) -> Issue:
        self._count("set_issue")
        depot = self.depot(url)
        at = next((k for k, i in enumerate(depot.issues) if i.number == number), None) if depot else None
        if depot is None or at is None:
            return Issue(number=number, error="issue inconnue de l'hôte du banc")
        now = self.clock.now()
        depot.issues[at] = replace(depot.issues[at], state=ISSUE_CLOSED if closed else ISSUE_OPEN,
                                   dropped=closed and dropped, state_at=now if closed else 0, at=now)
        self._note("issue_etat", depot.name, numero=number, fermee=closed, ecartee=dropped)
        return depot.issues[at]

    async def remark(self, url: str, number: int, *, body: str, mark: str) -> Remark:
        self._count("remark")
        depot = self.depot(url)
        if depot is None:
            return Remark(issue=number, error="dépôt inconnu de l'hôte du banc")
        for r in depot.remarks:
            if mark and r.mark == mark:
                return r
        made = Remark(id=len(depot.remarks) + 1, issue=number, author="mika-banc", body=body, mark=mark,
                      at=self.clock.now())
        depot.remarks.append(made)
        self._note("commentaire", depot.name, issue=number, texte=body, auteur=made.author, repere=mark)
        return made

    # ── le port : la CI ──
    async def checks(self, url: str, sha: str) -> Checks:
        self._count("checks")
        depot = self.depot(url)
        now = self.clock.now()
        if depot is None:
            return Checks(sha=sha, error="dépôt inconnu de l'hôte du banc")
        if not depot.ci:
            return Checks(sha=sha, state=CHECKS_NONE, read_at=now)
        full = next((k for k in depot.arrived if k.startswith(sha) or sha.startswith(k)), "")
        if not full or now < depot.arrived[full] + self.ci_us:
            return Checks(sha=sha, state=CHECKS_PENDING, read_at=now)
        done = depot.arrived[full] + self.ci_us
        if full in depot.failing:
            return Checks(sha=sha, state=CHECKS_FAILED, failed=("tests",), at=done, read_at=now)
        return Checks(sha=sha, state=CHECKS_PASSED, at=done, read_at=now)

    async def check_log(self, url: str, sha: str) -> CheckLog:
        self._count("check_log")
        depot = self.depot(url)
        full = next((k for k in (depot.failing if depot else {}) if k.startswith(sha) or sha.startswith(k)), "")
        if depot is None or not full:
            return CheckLog(sha=sha, error="aucune vérification en échec pour ce commit")
        return CheckLog(sha=sha, name="tests", tail=depot.failing[full])

    # ── les gestes des gens, de l'autre côté ──
    def open_pulls(self, url: str) -> list[Pull]:
        depot = self.depot(url)
        return [p for p in depot.pulls if p.state == PULL_OPEN] if depot else []

    def ready(self, url: str, pull: Pull) -> bool:
        """Ses vérifications ont-elles fini sans échec (un dépôt sans CI : tout de suite) ?"""
        depot = self.depot(url)
        if depot is None or not depot.ci:
            return depot is not None
        arrived = depot.arrived.get(pull.sha)
        return arrived is not None and self.clock.now() >= arrived + self.ci_us and pull.sha not in depot.failing

    def direct_commit(self, url: str, path: str, old: str, new: str, message: str,
                      by: str = "proprietaire") -> str:
        """Quelqu'un pousse lui-même une retouche sur la branche principale d'un dépôt, hors de toute pull
        request ; rend pourquoi il n'a pas pu (vide : c'est fait)."""
        depot = self.depot(url)
        if depot is None:
            return "dépôt inconnu de l'hôte du banc"
        work = self.root / f".retouche-{depot.path.stem}"
        subprocess.run(["rm", "-rf", str(work)], check=False)
        _git(self.root, "clone", "-q", "--branch", BASE_BRANCH, str(depot.path), str(work))
        target = work / path
        text = target.read_text(encoding="utf-8") if target.is_file() else ""
        why = "" if old in text else f"« {path} » ne porte plus cette ligne"
        if not why:
            target.write_text(text.replace(old, new, 1), encoding="utf-8")
            now = self.clock.now()
            _git(work, "add", "-A")
            _git(work, "commit", "-q", "-m", message, date=now)
            _git(work, "push", "-q", "origin", f"HEAD:refs/heads/{BASE_BRANCH}")
            made = depot.ref(BASE_BRANCH)
            depot.arrived[made] = now
            self._note("retouche", depot.name, par=by, fichier=path, commit=made[:12], message=message)
            self.say(f"hôte : {by} pousse une retouche sur la branche principale de {depot.name} ({made[:12]}) "
                     f"« {message} »")
        subprocess.run(["rm", "-rf", str(work)], check=False)
        return why

    def mergeable(self, url: str, pull: Pull) -> bool:
        """Cette pull request peut-elle être fusionnée — sa branche entre-t-elle dans la base sans conflit ?"""
        depot = self.depot(url)
        base, head = (depot.ref(pull.base), depot.ref(pull.head)) if depot else ("", "")
        if not base or not head:
            return False
        tree = _git(depot.path, "merge-tree", "--write-tree", base, head, check=False).splitlines()
        return bool(tree) and bool(re.fullmatch(r"[0-9a-f]{40,64}", tree[0]))

    def merge(self, url: str, number: int, by: str = "proprietaire") -> str:
        """Le propriétaire fusionne une pull request ; rend pourquoi il n'a pas pu (vide : c'est fait)."""
        depot = self.depot(url)
        at = next((k for k, p in enumerate(depot.pulls) if p.number == number and p.state == PULL_OPEN), None) \
            if depot else None
        if depot is None or at is None:
            return "pull request introuvable ou déjà close"
        pull = depot.pulls[at]
        base, head = depot.ref(pull.base), depot.ref(pull.head)
        tree = _git(depot.path, "merge-tree", "--write-tree", base, head, check=False).splitlines()
        if not tree or not re.fullmatch(r"[0-9a-f]{40,64}", tree[0]):
            return "conflit avec la branche principale"
        now = self.clock.now()
        made = _git(depot.path, "commit-tree", tree[0], "-p", base, "-p", head, "-m",
                    f"Fusion de la pull request n° {number} ({pull.head})", date=now)
        _git(depot.path, "update-ref", f"refs/heads/{pull.base}", made, base)
        depot.arrived[made] = now
        depot.pulls[at] = replace(pull, state=PULL_MERGED, at=now)
        self._note("fusion", depot.name, numero=number, par=by, commit=made[:12])
        self.say(f"hôte : pull request n° {number} de {depot.name} fusionnée par {by} ({made[:12]})")
        return ""

    def send_back(self, url: str, number: int, said: str, by: str = "proprietaire", *, close: bool = False) -> str:
        """Le propriétaire demande des changements (ou ferme sans fusionner), avec son mot."""
        depot = self.depot(url)
        at = next((k for k, p in enumerate(depot.pulls) if p.number == number and p.state == PULL_OPEN), None) \
            if depot else None
        if depot is None or at is None:
            return "pull request introuvable ou déjà close"
        now = self.clock.now()
        depot.pulls[at] = replace(depot.pulls[at], state=PULL_CLOSED if close else PULL_OPEN,
                                  review="" if close else REVIEW_CHANGES, review_at=now, said=said, said_by=by,
                                  said_role=True, at=now)
        self._note("fermeture" if close else "changements_demandes", depot.name, numero=number, par=by, mot=said)
        self.say(f"hôte : pull request n° {number} de {depot.name} {'fermée' if close else 'renvoyée'} par {by} : "
                 f"{said[:80]}")
        return ""

    def stranger_issue(self, url: str, title: str, body: str, author: str) -> int:
        """Un inconnu ouvre une issue : elle n'a pas de repère, le moteur la lira comme la donnée d'un inconnu."""
        depot = self.depot(url)
        return self._issue(depot, title, body, author=author).number if depot else 0

    def fail_next(self, url: str, sha: str, tail: str) -> None:
        """La CI de ce commit échouera, avec cette fin de journal."""
        depot = self.depot(url)
        if depot is not None:
            depot.failing[sha] = tail

    def state(self) -> dict[str, Any]:
        """Tout ce que l'hôte possède à la fin, pour le juge."""
        out: dict[str, Any] = {}
        for name, d in self.depots.items():
            log = _git(d.path, "log", "-40", "--format=%h %s", BASE_BRANCH, check=False).splitlines()
            files = _git(d.path, "ls-tree", "-r", "--name-only", BASE_BRANCH, check=False).splitlines()
            texts = {f: _git(d.path, "show", f"{BASE_BRANCH}:{f}", check=False)[:6000] for f in files[:40]}
            out[name] = {
                "ci": d.ci, "principale": log, "fichiers": files, "textes": texts,
                "pull_requests": [{"numero": p.number, "etat": p.state, "branche": p.head, "relecture": p.review,
                                   "mot": p.said, "commit": p.sha[:12]} for p in d.pulls],
                "issues": [{"numero": i.number, "etat": i.state, "ecartee": i.dropped, "titre": i.title,
                            "auteur": i.author, "repere": i.mark} for i in d.issues],
                "commentaires": [{"issue": r.issue, "auteur": r.author, "texte": r.body[:400]} for r in d.remarks]}
        return {"depots": out, "demandes_du_moteur": dict(sorted(self.asked.items()))}


class BenchWorkshop(BwrapWorkshop):
    """Le vrai atelier, dont le dépôt distant est chez le faux hôte : un envoi et une récupération sont rejoués hors
    de la cage vers le dépôt nu de l'adresse visée (le git de la cage ne voit ni ce dossier ni le réseau). Tout autre
    appel au réseau est refusé."""

    def __init__(self, root: Path, host: FakeHost, **kw: Any) -> None:
        super().__init__(root, credentials=lambda: {"token": "jeton-du-banc", "hosts": [HOST]}, **kw)
        self.host = host

    async def run(self, project: int, argv: Sequence[str], *, network: Any = False, **kw: Any) -> RunResult:
        if network:
            return RunResult(tuple(argv), None, refused="le banc n'a pas de réseau : rien ne sort de la machine")
        return await super().run(project, argv, **kw)

    async def _git(self, project: int, *args: str, network: bool = False, timeout_s: float = 30,
                   extra_env: Mapping[str, str] | None = None, secrets: Sequence[str] = (),
                   clip: bool = True) -> RunResult:
        if not network:
            return await super()._git(project, *args, timeout_s=timeout_s, extra_env=extra_env, secrets=secrets,
                                      clip=clip)
        verb = next((a for a in args if a in ("push", "fetch")), "")
        rest = [a for a in args[args.index(verb) + 1:] if not a.startswith("-")] if verb else []
        depot = self.host.depot(rest[0]) if rest else None
        if depot is None or len(rest) < 2:
            return RunResult(("git", verb or "?"), None, refused="le banc ne connaît pas ce dépôt distant")
        where = self.folder(project)
        cmd = ["git", "-C", str(where), *_IDENT, verb, "--no-tags", str(depot.path), rest[1]] if verb == "fetch" else \
            ["git", "-C", str(where), *_IDENT, "push", str(depot.path), rest[1]]
        done = subprocess.run(cmd, capture_output=True, text=True, env=_ENV, check=False)
        if verb == "push" and done.returncode == 0:
            self.host.received(depot, rest[1].split(":refs/heads/", 1)[-1])
        return RunResult(("git", verb), done.returncode, stdout=done.stdout, stderr=done.stderr)
