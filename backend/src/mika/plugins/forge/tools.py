"""Les outils ``forge_*`` : écrire une app, la relire, y chercher, la retoucher, l'essayer, et sa base.

- **Écrire** (``forge_write``) : une app est relue à l'écriture ; une version refusée ne change rien. Une app qui a
  des secrets sans avoir jamais été validée voit sa nouvelle version mise de côté et proposée (``guarded``,
  ``install_draft``, ADR 0105). Elle vit dans le projet qu'elle désigne, sinon celui où elle vit déjà, sinon celui
  de l'exécution en cours (``home_of``, ADR 0104, 0161).
- **Relire** (``forge_list``, ``forge_read`` par morceaux numérotés, avec ses réglages en vigueur : ``settings_lines``),
  **chercher** dans ses apps (``forge_search``, dans un processus à part), **retoucher** sans tout réécrire
  (``forge_edit``), **apprendre** à les écrire (``forge_help``, ``guide.py``).
- **Essayer** tout de suite (``forge_test``) : tout ce qu'elle écrit, avec les délais et les arguments déclarés ; un
  essai est un vrai passage (ADR 0105), et un essai réussi d'une version qu'aucun essai n'a encore prouvée prouve un
  travail (``proves``, ADR 0161). **Régler** et **lire** (``forge_command``, ``forge_logs``).
- **Sa base** (``forge_db_schema``, ``forge_db_query``, ``forge_db_execute``, ADR 0101).

Le lot ``forge``, offert selon ses droits (``_may_build``). Ces outils s'inscrivent sur ``FORGE`` à l'import du
module, que le paquet fait en fin de fichier, après la file de signaux : ils restent inscrits après
``forge_signals_done``. Ils lisent du paquet l'état, les tours et les aides partagées, et d'``install.py`` la
proposition d'installer (``install_draft``) ; le paquet ne lit rien d'ici.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from mika.contracts import identity as identity_c
from mika.contracts import projects as projects_c
from mika.kernel.faculty import ToolResult
from mika.kernel.frame import Frame
from mika.kernel.inspect import size_fr
from mika.plugins.forge import (
    BUNDLE,
    FORGE,
    PROVED,
    SWITCHED,
    WRITTEN,
    App,
    ForgeParams,
    bad_args,
    caretaker,
    concerns,
    forge_port,
    guide,
    has_secrets,
    outcomes,
    params,
    rules_of,
    sifting_app,
    stopped,
    timeout_of,
    trusted,
    written_draft,
)
from mika.plugins.forge.install import install_draft
from mika.plugins.forge.views import (
    VIEW_MAX_BYTES,
    VIEW_TIMEOUT_S,
    decode_view,
    failure_note,
    is_invalid,
    summary,
    view_params,
)
from mika.ports.forge import AppInfo, ForgeRefused, SignalRules
from mika.ports.forge_args import check_args
from mika.vocab.episodes import PROJECT_KINDS, WORKING, Kind, project_of
from mika.vocab.phrasebook import phrase
from mika.vocab.rights import here_allowed

# ── Outils ────────────────────────────────────────────────────────────────


def _may_build(ctx: Any) -> bool:
    """Écrire et régler ses apps : ce que ses droits en laissent (``vocab.rights.here_allowed``, ADR 0133, 0134 : le minimum vital de sa famille la réserve à sa propriétaire, une ligne peut l'ouvrir) — toi en privé, jamais dans un salon ; elle qui travaille, un projet ou un réveil seulement s'il a pris la
    Forge ; la lecture de la file d'une app."""
    return here_allowed(ctx.frame, BUNDLE, acts=True, tasks=lambda target: bool(sifting_app(target)))


def _refused(ctx: Any) -> ToolResult:
    if forge_port(ctx) is None:
        return ToolResult(ok=False, content=phrase("forge.tools.absent"))
    return ToolResult(ok=False, content=phrase("forge.tools.not_here", who=caretaker(ctx.frame)))


class NoArgs(BaseModel):
    pass


class AppArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31)


class WriteArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31, description=phrase("forge.tools.app_name"))
    manifest: str = Field(min_length=1, max_length=16_000, description=phrase("forge.tools.manifest"))
    code: str = Field(min_length=1, max_length=200_000, description=phrase("forge.tools.code"))
    project: int = Field(default=0, ge=0, description=phrase("forge.tools.write.project"))


#: ce qu'elle peut essayer elle-même : un battement, sa ligne de contexte, un événement d'exemple, une vue, un de ses
#: outils, une action — tout ce qu'elle écrit (ADR 0104). Un essai est un vrai passage (ADR 0105) : ce qu'il range
#: reste dans sa base, ce qu'il signale part dans sa file ; seul un événement d'exemple est inventé. Jamais compté
#: contre l'app.
TESTABLE = r"^(tick|context|on_event|view|view_[a-z0-9_]+|tool_[a-z0-9_]+|action_[a-z0-9_]+|service_[a-z0-9_]+)$"


class TestArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31)
    method: str = Field(default="tick", pattern=TESTABLE, description=phrase("forge.tools.method"))
    args: dict[str, Any] = Field(default_factory=dict, description=phrase("forge.tools.test_args"))


class HelpArgs(BaseModel):
    sujet: Literal["manifeste", "outils", "reseau", "vues", "actions", "reglages", "blocs", "base", "veille",
                   "exemple"] = "manifeste"


#: les deux fichiers d'une app, par leur nom court (ses outils de fichiers, ADR 0105)
FILES = {"manifest": "manifest.yaml", "code": "main.py"}
FileName = Literal["manifest", "code"]
#: ce qu'une lecture montre au plus quand elle ne dit pas combien (lignes)
READ_LINES = 2000
#: ce qu'une recherche rend au plus (lignes trouvées), et le temps qu'elle a
SEARCH_MAX, SEARCH_S = 100, 3.0


class ReadArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31)
    file: FileName | None = Field(default=None, description=phrase("forge.tools.read.file"))
    offset: int = Field(default=1, ge=1, description=phrase("forge.tools.read.offset"))
    limit: int = Field(default=0, ge=0, le=5000, description=phrase("forge.tools.read.limit"))


class Edit(BaseModel):
    old_string: str = Field(min_length=1, max_length=100_000, description=phrase("forge.tools.edit.old"))
    new_string: str = Field(max_length=100_000, description=phrase("forge.tools.edit.new"))
    replace_all: bool = Field(default=False, description=phrase("forge.tools.edit.all"))


class EditArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31)
    file: FileName = Field(default="code", description=phrase("forge.tools.edit.file"))
    edits: list[Edit] = Field(min_length=1, max_length=20, description=phrase("forge.tools.edit.edits"))
    project: int = Field(default=0, ge=0, description=phrase("forge.tools.write.project"))


class SearchArgs(BaseModel):
    pattern: str = Field(min_length=1, max_length=300, description=phrase("forge.tools.search.pattern"))
    app: str = Field(default="", max_length=31, description=phrase("forge.tools.search.app"))
    file: FileName | None = Field(default=None, description=phrase("forge.tools.search.file"))
    regex: bool = Field(default=False, description=phrase("forge.tools.search.regex"))
    ignore_case: bool = Field(default=False, description=phrase("forge.tools.search.ignore_case"))
    context: int = Field(default=0, ge=0, le=5, description=phrase("forge.tools.search.context"))


class DbArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31)
    sql: str = Field(min_length=1, max_length=20_000, description=phrase("forge.tools.db.sql"))
    params: dict[str, Any] = Field(default_factory=dict, description=phrase("forge.tools.db.params"))


class CommandArgs(BaseModel):
    app: str = Field(min_length=2, max_length=31)
    command: Literal["enable", "disable", "rollback", "erase", "reset_storage"]


BUILD = [Kind.REPLY, *WORKING]


def guarded(app: App | None, ports: Mapping[str, Any], info: AppInfo | None) -> str:
    """Pourquoi une nouvelle version de cette app ne s'installe pas sans accord (vide : elle peut) : elle a des
    secrets qu'aucun opérateur ne lui a jamais confiés en connaissance de cause — la première validation. Une app
    validée une fois change sans repasser par lui (ADR 0105)."""
    if trusted(app):
        return ""
    if has_secrets(ports, info):
        return phrase("forge.tools.guarded.secrets")
    return ""


@FORGE.tool("forge_list", description=phrase("forge.tools.list.description"),
            label=phrase("forge.tools.list.label"), args=NoArgs, bundle=BUNDLE,
            episodes=BUILD, owner_only=True)
async def forge_list(args: NoArgs, ctx: Any) -> Any:
    port = forge_port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    state = ctx.frame.state("forge").apps
    lines = []
    for info in port.apps():
        a = state.get(info.name)
        status = phrase("forge.tools.list.broken", error=a.broken) if a and a.broken else \
            phrase("forge.tools.list.active") if a is None or a.enabled else \
            phrase("forge.tools.list.held") if a.held else phrase("forge.tools.list.stopped")
        lines.append(phrase("forge.tools.list.line", app=info.name, version=info.version, title=info.title,
                            status=status,
                            error=phrase("forge.tools.list.manifest_error", error=info.error) if info.error else ""))
    return _nothing("\n".join(lines) or phrase("forge.tools.list.none"))


def numbered(text: str, offset: int = 1, limit: int = 0) -> tuple[str, int]:
    """Les lignes d'un fichier, numérotées comme ``cat -n`` (le numéro, une tabulation, la ligne), à partir de
    ``offset`` ; rend (texte, nombre total de lignes)."""
    lines = text.splitlines()
    shown = lines[offset - 1: offset - 1 + (limit or READ_LINES)]
    return "\n".join(f"{offset + i:>6}\t{line}" for i, line in enumerate(shown)), len(lines)


@FORGE.tool("forge_read", description=phrase("forge.tools.read.description"),
            label=phrase("forge.tools.read.label"), args=ReadArgs,
            bundle=BUNDLE, episodes=BUILD, owner_only=True)
async def forge_read(args: ReadArgs, ctx: Any) -> Any:
    port = forge_port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    try:
        got = port.source(args.app)
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=str(exc))
    if got is None:
        return ToolResult(ok=False, content=phrase("forge.tools.no_app"))
    texts = dict(zip(("manifest", "code"), got, strict=True))
    if args.file is not None:  # un fichier, un morceau : de quoi retoucher sans tout relire
        body, total = numbered(texts[args.file], args.offset, args.limit)
        last = min(total, args.offset - 1 + (args.limit or READ_LINES))
        head = phrase("forge.tools.read.range", file=FILES[args.file], first=min(args.offset, total), last=last,
                      total=total)
        return _nothing(head + "\n" + (body or phrase("forge.tools.read.empty")))
    logs = "\n".join(port.logs(args.app, 15))
    settings = settings_lines(ctx, args.app, port.info(args.app))
    return _nothing("\n".join((phrase("forge.tools.read.manifest"), numbered(texts["manifest"])[0],
                                *settings, phrase("forge.tools.read.code"), numbered(texts["code"])[0],
                                phrase("forge.tools.read.logs"), logs or phrase("forge.tools.read.empty"))))


def settings_lines(ctx: Any, name: str, info: AppInfo | None) -> list[str]:
    """Ses réglages en vigueur : la valeur qu'un opérateur a donnée l'emporte sur le défaut du manifeste — changer un
    défaut ne change alors rien, et elle doit le savoir ; un secret se dit défini ou non, jamais sa valeur ; une app
    à secrets que personne n'a validée les lit vides (ADR 0161)."""
    fields = info.config_fields if info is not None else ()
    if not fields:
        return []
    store = ctx.ports.get("forge_settings")
    current = dict(store.values(name)) if store is not None else {}
    app = ctx.frame.state("forge").apps.get(name)
    out = [phrase("forge.tools.read.settings")]
    for f in fields:
        given = current.get(f.path)
        if f.secret:
            state = phrase("forge.tools.read.secret_set") if given else phrase("forge.tools.read.secret_unset")
            if given and not trusted(app):
                state += phrase("forge.tools.read.untrusted")
        elif given not in (None, ""):
            state = phrase("forge.tools.read.overridden", value=str(given)[:80])
        else:
            state = phrase("forge.tools.read.default", value=str(f.default)[:80])
        out.append(f"- {f.path} : {state}")
    return out


def _nothing(text: str) -> ToolResult:
    """Une réponse qui ne prouve aucun travail : relire, se renseigner, écrire sans avoir essayé, commander (ADR
    0104 — sans quoi relire sa Forge « prouvait » qu'une séance de réparation avait abouti)."""
    return ToolResult(content=text, proof=False)


def _written_of(info: AppInfo | None, app: str, version: int, project: int = 0) -> Any:
    return written_draft(info, project=project) if info is not None else \
        WRITTEN.draft(app=app, version=version, title=app, project=project)


def home_of(ctx: Any, asked: int, current: int = 0) -> tuple[int, str]:
    """Le projet où vivra l'app qu'elle écrit (ADR 0104) : celui qu'elle désigne parmi ses projets vivants — (0,
    « pourquoi pas ») pour un numéro inconnu —, sinon celui où elle vit déjà s'il vit encore (retouchée depuis un
    autre projet, elle ne déménage pas avec sa réparation et ses trouvailles : ADR 0161), sinon celui de l'exécution
    en cours ; (0, "") : aucun (celui d'avant reste)."""
    alive = {p.id for p in ctx.frame.get(projects_c.LIVE)}
    if asked:
        return (asked, "") if asked in alive else (0, phrase("forge.tools.write.no_project", id=asked))
    if current and current in alive:
        return current, ""
    ep = ctx.frame.episode
    if ep is not None and ep.kind in PROJECT_KINDS and (pid := project_of(ep.target)):
        return pid, ""
    return 0, ""


def keeper_handle(frame: Frame) -> str:
    """Où montrer la carte d'accord d'une version mise de côté : la propriétaire qui lui parle, sinon la première
    qui s'occupe d'elle (une carte dans son chat, ADR 0064, 0104)."""
    ep = frame.episode
    if ep is not None and ep.kind == Kind.REPLY and ep.target and frame.audience is not None and frame.audience.owner:
        return ep.target
    owners = frame.get(identity_c.OWNERS)
    return owners[0] if owners else ""


async def _save(ctx: Any, port: Any, name: str, manifest: str, code: str, asked_project: int) -> ToolResult:
    """Installer une version (relue ; une version refusée ne change rien) — ou la mettre de côté quand elle attend
    la première validation d'un opérateur. Le chemin commun de ``forge_write`` et ``forge_edit``."""
    app = ctx.frame.state("forge").apps.get(name)
    project, wrong = home_of(ctx, asked_project, app.project if app is not None else 0)
    if wrong:
        return ToolResult(ok=False, content=wrong)
    why = guarded(app, ctx.ports, port.info(name)) if app is not None else ""
    try:
        if why:
            print_ = await port.stage(name, manifest, code)
        else:
            version, _ = await port.write(name, manifest, code)
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=phrase("forge.tools.write.refused", error=exc))
    if why:
        if app is not None and print_ == app.fingerprint:
            return ToolResult(ok=False, content=phrase("forge.tools.write.same"))
        await ctx.propose(install_draft(name, print_, app, why, decider=keeper_handle(ctx.frame)))
        return _nothing(phrase("forge.tools.write.staged", why=why))
    await ctx.emit(_written_of(port.info(name), name, version, project))
    return _nothing(phrase("forge.tools.write.done", version=version))  # la preuve viendra de son essai


@FORGE.tool("forge_write", acts=True, description=phrase("forge.tools.write.description"),
            label=phrase("forge.tools.write.label"), args=WriteArgs,
            bundle=BUNDLE, episodes=BUILD, max_calls_per_episode=3, owner_only=True)
async def forge_write(args: WriteArgs, ctx: Any) -> Any:
    port = forge_port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    return await _save(ctx, port, args.app, args.manifest, args.code, args.project)


def apply_edits(text: str, edits: Sequence[Edit]) -> tuple[str, str]:
    """Remplacer des fragments exacts, l'un après l'autre (comme l'outil Edit de Claude Code) : rend (le nouveau
    texte, un problème en français — vide : tout s'applique). Un fragment introuvable, ou trouvé plusieurs fois sans
    ``replace_all``, arrête tout : le texte rendu est alors celui d'avant, intact."""
    original = text
    for n, e in enumerate(edits, start=1):
        if e.old_string == e.new_string:
            return original, phrase("forge.tools.edit.identical", n=n)
        count = text.count(e.old_string)
        if count == 0:
            start = e.old_string.strip().splitlines()[0][:80] if e.old_string.strip() else repr(e.old_string[:40])
            return original, phrase("forge.tools.edit.missing", n=n, start=start)
        if count > 1 and not e.replace_all:
            at, lines = 0, []
            for _ in range(count):
                at = text.index(e.old_string, at)
                lines.append(text.count("\n", 0, at) + 1)
                at += len(e.old_string)
            return original, phrase("forge.tools.edit.many", n=n, count=count, lines=", ".join(map(str, lines[:12])))
        text = text.replace(e.old_string, e.new_string, -1 if e.replace_all else 1)
    return text, ""


def _around(text: str, spans: Sequence[tuple[int, int]], margin: int = 2, most: int = 60) -> str:
    """Les lignes retouchées et un peu autour, numérotées : de quoi vérifier sans tout relire."""
    lines = text.splitlines()
    keep: list[int] = []
    for first, last in spans:
        keep += range(max(1, first - margin), min(len(lines), last + margin) + 1)
    shown = sorted(set(keep))[:most]
    out, prev = [], 0
    for n in shown:
        if prev and n != prev + 1:
            out.append("   …")
        out.append(f"{n:>6}\t{lines[n - 1]}")
        prev = n
    return "\n".join(out)


@FORGE.tool("forge_edit", acts=True, description=phrase("forge.tools.edit.description"),
            label=phrase("forge.tools.edit.label"), args=EditArgs,
            bundle=BUNDLE, episodes=BUILD, max_calls_per_episode=12, owner_only=True)
async def forge_edit(args: EditArgs, ctx: Any) -> Any:
    port = forge_port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    try:
        got = port.source(args.app)
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=str(exc))
    if got is None:
        return ToolResult(ok=False, content=phrase("forge.tools.edit.no_app"))
    manifest, code = got
    text, problem = apply_edits(manifest if args.file == "manifest" else code, args.edits)
    if problem:
        return ToolResult(ok=False, content=phrase("forge.tools.edit.refused", why=problem))
    new_manifest, new_code = (text, code) if args.file == "manifest" else (manifest, text)
    saved = await _save(ctx, port, args.app, new_manifest, new_code, args.project)
    if not saved.ok:
        return saved
    shown = _around(text, _spans_in(text, args.edits))
    return _nothing(saved.content + (f"\n{phrase('forge.tools.edit.around', file=FILES[args.file])}\n{shown}"
                                     if shown else ""))


def _spans_in(text: str, edits: Sequence[Edit]) -> list[tuple[int, int]]:
    """Où se trouve, dans le texte retouché, ce que chaque retouche a mis (ses lignes)."""
    spans = []
    for e in edits:
        at = 0
        while e.new_string and (found := text.find(e.new_string, at)) >= 0:
            first = text.count("\n", 0, found) + 1
            spans.append((first, first + e.new_string.count("\n")))
            at = found + max(1, len(e.new_string))
            if not e.replace_all:
                break
    return spans


#: ce que fait le processus de recherche : rien que la bibliothèque standard, pour démarrer vite ; il reçoit le motif
#: et les lignes de chaque fichier, et rend les numéros des lignes trouvées
_MATCH = ("import json, re, sys\n"
          "q = json.load(sys.stdin)\n"
          "rx = re.compile(q['pattern'], q['flags'])\n"
          "json.dump([[i for i, line in enumerate(lines) if rx.search(line[:2000])] for lines in q['files']],"
          " sys.stdout)\n")


def _searched(sources: Mapping[str, tuple[str, str]], args: SearchArgs) -> list[tuple[str, str, list[str]]]:
    """Les fichiers où chercher, dans l'ordre : (app, nom court, lignes)."""
    return [(app, short, text.splitlines()) for app, (manifest, code) in sorted(sources.items())
            for short, text in (("manifest", manifest), ("code", code)) if args.file is None or args.file == short]


def _matches(files: Sequence[list[str]], args: SearchArgs) -> list[list[int]] | None:
    """Les lignes de chaque fichier où se trouve ``pattern`` (``None`` : trop lent). Le moteur ``re`` garde le GIL
    tant qu'il cherche : une expression qui s'emballe dans un fil figerait tout le serveur. La recherche se fait
    donc dans un processus à part, tué au bout de ``SEARCH_S``."""
    query = {"pattern": args.pattern if args.regex else re.escape(args.pattern),
             "flags": int(re.IGNORECASE) if args.ignore_case else 0, "files": list(files)}
    try:
        done = subprocess.run([sys.executable, "-I", "-S", "-c", _MATCH], input=json.dumps(query),
                              capture_output=True, text=True, timeout=SEARCH_S, check=False)
    except subprocess.TimeoutExpired:
        return None
    return json.loads(done.stdout) if done.returncode == 0 else None


def search(sources: Mapping[str, tuple[str, str]], args: SearchArgs,
           hits: Sequence[Sequence[int]]) -> tuple[list[str], int]:
    """Les lignes de ses apps où se trouve ``pattern`` (``hits``, rendu par ``_matches`` pour chaque fichier de
    ``_searched``) : « app/fichier:ligne: texte » (et ``context`` lignes autour) ; rend (lignes, nombre de
    correspondances)."""
    out: list[str] = []
    found = 0
    for (app, short, lines), found_in in zip(_searched(sources, args), hits, strict=True):
        found += len(found_in)
        shown: set[int] = set()
        for i in found_in:
            for j in range(max(0, i - args.context), min(len(lines), i + args.context + 1)):
                if j in shown or len(out) >= SEARCH_MAX:
                    continue
                shown.add(j)
                mark = ":" if j == i else "-"
                out.append(f"{app}/{FILES[short]}{mark}{j + 1}{mark} {lines[j][:300]}")
    return out, found


@FORGE.tool("forge_search", description=phrase("forge.tools.search.description"),
            label=phrase("forge.tools.search.label"), args=SearchArgs,
            bundle=BUNDLE, episodes=BUILD, max_calls_per_episode=8, owner_only=True)
async def forge_search(args: SearchArgs, ctx: Any) -> Any:
    port = forge_port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    names = [args.app] if args.app else [i.name for i in port.apps()]
    sources: dict[str, tuple[str, str]] = {}
    for name in names:
        try:
            got = port.source(name)
        except ForgeRefused:
            got = None
        if got is not None:
            sources[name] = got
    if args.app and not sources:
        return ToolResult(ok=False, content=phrase("forge.tools.no_app"))
    if args.regex:
        try:
            re.compile(args.pattern)
        except re.error as exc:
            return ToolResult(ok=False, content=phrase("forge.tools.search.bad_pattern", error=exc))
    # une expression qui s'emballe ne bloque pas sa vie : elle a quelques secondes, dans un processus à part
    hits = await asyncio.get_running_loop().run_in_executor(
        None, _matches, [lines for _, _, lines in _searched(sources, args)], args)
    if hits is None:
        return ToolResult(ok=False, content=phrase("forge.tools.search.slow"))
    lines, found = search(sources, args, hits)
    if not found:
        return _nothing(phrase("forge.tools.search.none"))
    more = phrase("forge.tools.search.more", count=found) if found > len(lines) else ""
    return _nothing(phrase("forge.tools.search.result", count=found) + "\n" + "\n".join(lines)
                    + (f"\n{more}" if more else ""))


@FORGE.tool("forge_help", description=phrase("forge.tools.help.description"),
            label=phrase("forge.tools.help.label"), args=HelpArgs, bundle=BUNDLE,
            episodes=BUILD)
async def forge_help(args: HelpArgs, ctx: Any) -> Any:
    return _nothing(guide.topic(args.sujet))


def signal_fate(app: App | None, signals: Sequence[tuple[str, float, str]], frame: Frame, p: ForgeParams, *,
                invented: bool = False) -> str:
    """Ce que deviennent les signaux d'un essai : un vrai passage les met dans la file de l'app, où elle les lira par
    lots, sous son quota (ADR 0105) — qu'elle l'apprenne en écrivant, pas en attendant ; ``invented`` : un événement
    d'exemple, dont les signaux ne partent pas."""
    if not signals:
        return ""
    if invented:
        return phrase("forge.tools.test.signals_invented", count=len(signals))
    r = rules_of(app) if app is not None else SignalRules()
    waiting = len(app.queue) if app is not None else 0
    note = phrase("forge.tools.test.signals_queued", count=len(signals), waiting=waiting, size=r.queue,
                  per_call=r.per_call, quota=min(r.quota, p.signal_calls_max))
    if waiting + len(signals) > r.queue:
        note += " " + phrase("forge.tools.test.signals_overflow", count=waiting + len(signals) - r.queue)
    return note


def _tested(r: Any, verdict: str = "", *, invalid: bool = False, fate: str = "", made: bool = False,
            stored: bool = False) -> ToolResult:
    """Ce qu'a donné un essai ; ``invalid`` : une vue rendue mais invalide (l'essai n'est pas réussi) ; ``fate`` : ce
    que deviendraient ses signaux ; ``made`` : un essai réussi prouverait un travail (``proves``) ; ``stored`` : un
    outil ou une action, dont ce qu'il range reste dans sa base. Ce qui n'a pas répondu au réseau se montre (ADR
    0161) : « réussi » ne veut dire que « rien n'a levé », et c'est à elle d'en juger — une app réparée qui tient
    pendant que son site est tombé a réussi, sans qu'aucune requête ait abouti."""
    logs = "\n".join(r.logs[-10:])
    head = phrase("forge.tools.test.outcome",
                  state=phrase("forge.tools.test.ok") if r.ok else phrase("forge.tools.test.failed"),
                  ms=r.duration_ms, killed=phrase("forge.tools.test.killed") if r.killed else "")
    body = json.dumps(r.value, ensure_ascii=False, default=str)[:3000] if r.ok else r.error
    failed = tuple(getattr(r, "failed", ()) or ())
    requests = int(getattr(r, "requests", 0) or 0)
    extra = ("\n" + phrase("forge.tools.test.signals", signals=list(r.signals)) if r.signals else "") + \
        (f"\n{fate}" if fate else "") + \
        ("\n" + phrase("forge.tools.test.http_failed", count=len(failed), total=max(requests, len(failed)),
                       lines="\n".join(failed[:5])) if failed else "") + \
        ("\n" + phrase("forge.tools.test.stored") if stored and r.ok else "") + \
        ("\n" + phrase("forge.tools.test.logs") + f"\n{logs}" if logs else "")
    ok = r.ok and not invalid
    return ToolResult(ok=ok, content=phrase("forge.tools.test.result", head=head) + f"\n{body}{extra}"
                                     + (f"\n{verdict}" if verdict else ""), proof=ok and made)


#: ce qui prouve, à l'essai : ce que l'app fait pour de vrai — un battement, un service, un outil, une vue, une
#: action ; ni sa ligne de contexte ni un événement inventé (ADR 0161)
PROVING = ("tick", "service_", "tool_", "view", "action_")


def proves(app: App | None, ctx: Any, method: str) -> bool:
    """Un essai réussi de cette app prouverait-il un travail ? Écrite ou relancée après une panne dans cet épisode
    (ADR 0104) ; ou, pendant une exécution de son projet, une version qu'aucun essai n'a encore prouvée — écrite par
    une exécution qui n'a pas abouti, elle se prouve à la suivante sans être réécrite (ADR 0161)."""
    if app is None or not method.startswith(PROVING):
        return False
    if ctx.episode_id in (app.written_in, app.revived_in):
        return True
    ep = ctx.frame.episode
    here = project_of(ep.target) if ep is not None and ep.kind in PROJECT_KINDS else None
    return bool(here) and app.project == here and app.version > app.proven


async def _settled(ctx: Any, name: str, app: App | None, out: ToolResult) -> ToolResult:
    """Un essai qui prouve le note : crédité par le compte rendu de son exécution, sa version est prouvée, et
    l'essayer de nouveau ne prouvera plus rien (ADR 0161)."""
    if out.proof and app is not None and app.version > app.proven:
        await ctx.emit(PROVED.draft(app=name, version=app.version))
    return out


@FORGE.tool("forge_test", acts=True, description=phrase("forge.tools.test.description"),
            label=phrase("forge.tools.test.label"), args=TestArgs, bundle=BUNDLE,
            episodes=BUILD, max_calls_per_episode=12, owner_only=True)
async def forge_test(args: TestArgs, ctx: Any) -> Any:
    port = forge_port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    app = ctx.frame.state("forge").apps.get(args.app)
    if why := stopped(app):
        return ToolResult(ok=False, content=phrase("forge.tools.test.stopped", why=why))
    made = proves(app, ctx, args.method)
    if args.method.startswith("view"):
        return await _settled(ctx, args.app, app, await _test_view(port, args.app, args.method, args.args,
                                                                   trusted(app), made=made))
    frame: Frame = ctx.frame
    info = port.info(args.app)
    verdict, payload = "", {}
    if args.method.startswith("tool_"):
        tool = next((t for t in info.tools if t.name == args.method[5:]), None) if info is not None else None
        if tool is None:
            return ToolResult(ok=False, content=phrase("forge.tools.call.no_tool"))
        payload, errors = check_args(tool.args, args.args)  # ce que le modèle lui passerait, vérifié pareil
        if errors:
            return ToolResult(ok=False, content=bad_args(tool, errors))
    elif args.method.startswith("action_"):
        action = next((a for v in (info.views if info is not None else ()) for a in v.actions
                       if a.function == args.method), None)
        if action is None:
            return ToolResult(ok=False, content=phrase("forge.tools.test.no_action", action=args.method))
        # vérifiées comme la console les vérifie : chaque champ déclaré présent et typé (ADR 0161)
        payload, errors = check_args(action.specs, dict(args.args), defaults=False, strict=False)
        if errors:
            return ToolResult(ok=False, content=phrase("forge.tools.test.bad_data", errors="; ".join(
                f"{k} : {v}" for k, v in errors.items())))
    elif args.method == "on_event":
        payload = {"type": "rss.noticed", "at": frame.now // 1_000_000, "source": "rss", "kind": "", "summary": "",
                   **args.args}
    p = params(frame.env.params_of("forge", frame.root))
    r = await port.call(args.app, args.method, payload, timeout_s=timeout_of(info, args.method, p),
                        secrets=trusted(app))
    # un essai est un vrai passage : ce qu'il range reste dans la base, ce qu'il signale ou émet part comme au passage
    # planifié — sinon ce qu'il a rangé n'est plus « nouveau » au passage suivant, et ne serait jamais signalé (sonde
    # du 2026-10-13) ; seul un événement d'exemple est inventé. Jamais compté contre l'app.
    invented = args.method == "on_event"
    if app is not None and not invented:
        drafts = outcomes(args.app, app, [r], frame.now, p, breaker=False, concern=concerns(frame, app))
        if drafts:
            await ctx.emit(*drafts)
    if r.ok and args.method.startswith("action_"):
        verdict = action_verdict(r.value)
    return await _settled(ctx, args.app, app, _tested(
        r, verdict, invalid=verdict == phrase("forge.tools.action.invalid"),
        fate=signal_fate(app, r.signals, frame, p, invented=invented), made=made,
        stored=args.method.startswith(("tool_", "action_"))))


def action_verdict(value: Any) -> str:
    """Une action rend ``{ok: bool, message: texte}``."""
    if isinstance(value, dict) and isinstance(value.get("ok"), bool) and isinstance(value.get("message", ""), str):
        return phrase("forge.tools.action.valid")
    return phrase("forge.tools.action.invalid")


async def _test_view(port: Any, app: str, method: str, raw: dict[str, Any], secrets: bool = False, *,
                     made: bool = False) -> ToolResult:
    info = port.info(app)
    spec = next((v for v in info.views if v.function == method), None) if info is not None else None
    if info is None or spec is None:
        return ToolResult(ok=False, content=phrase("forge.tools.test.no_view", view=method))
    params, notes = view_params(spec, {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in raw.items()})
    r = await port.call(app, method, params, timeout_s=VIEW_TIMEOUT_S, max_result=VIEW_MAX_BYTES, secrets=secrets)
    said = "".join(f"\n{n}" for n in notes)
    if not r.ok:
        return _tested(r, failure_note(spec.label, r).text + said, made=made)
    blocks = decode_view(r.value, app, info, spec)
    invalid = is_invalid(blocks)
    verdict = phrase("forge.tools.test.invalid", why=blocks[0].text) if invalid else summary(blocks)
    return _tested(r, verdict + said, invalid=invalid, made=made)


@FORGE.tool("forge_logs", description=phrase("forge.tools.logs.description"),
            label=phrase("forge.tools.logs.label"), args=AppArgs, bundle=BUNDLE,
            episodes=BUILD, owner_only=True)
async def forge_logs(args: AppArgs, ctx: Any) -> Any:
    port = forge_port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    return _nothing("\n".join(port.logs(args.app, 30)) or phrase("forge.tools.logs.empty"))


@FORGE.tool("forge_command", acts=True, description=phrase("forge.tools.command.description"),
            label=phrase("forge.tools.command.label"), args=CommandArgs, bundle=BUNDLE, episodes=BUILD,
            owner_only=True)
async def forge_command(args: CommandArgs, ctx: Any) -> Any:
    port = forge_port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    app = ctx.frame.state("forge").apps.get(args.app)
    try:
        if args.command in ("enable", "disable"):
            if app is None:
                return ToolResult(ok=False, content=phrase("forge.tools.no_app"))
            if args.command == "enable" and app.held:
                return ToolResult(ok=False, content=phrase("forge.tools.command.held_enable"))
            await ctx.emit(SWITCHED.draft(app=args.app, state=f"{args.command}d"))
            return _nothing(phrase("forge.tools.command.done"))
        if args.command == "rollback":
            if why := guarded(app, ctx.ports, port.info(args.app)):
                return ToolResult(ok=False, content=phrase("forge.tools.command.no_rollback", why=why))
            version = await port.rollback(args.app)
            await ctx.emit(_written_of(port.info(args.app), args.app, version))
            return _nothing(phrase("forge.tools.command.rolled_back", version=version))
        if args.command == "erase":
            if app is not None and app.held:
                # effacer emporterait `held` avec la tranche : réécrite, l'app repartirait d'elle-même
                return ToolResult(ok=False, content=phrase("forge.tools.command.held_erase"))
            await port.erase(args.app)
            await ctx.emit(SWITCHED.draft(app=args.app, state="erased"))
            return _nothing(phrase("forge.tools.command.erased"))
        n = await port.reset_storage(args.app)
        return _nothing(phrase("forge.tools.command.reset", count=n))
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=str(exc))


# ── Sa base (ADR 0101) ────────────────────────────────────────────────────

#: ce qu'une lecture montre au plus (le reste est coupé, et elle le voit)
DB_SHOWN = 6_000


def schema_text(got: Mapping[str, Any]) -> str:
    """Le schéma d'une base d'app, en lignes."""
    lines = [phrase("forge.tools.db_schema.head", engine=got.get("engine", "?"), size=_size(got.get("size")),
                    max=_size(got.get("max")))]
    for t in got.get("tables", []):
        columns = ", ".join(phrase("forge.tools.db_schema.column", name=c["name"], type=c["type"],
                                   key=phrase("forge.tools.db_schema.key") if c.get("key") else "")
                            for c in t.get("columns", []))
        line = phrase("forge.tools.db_schema.table", table=t["name"], rows=t.get("rows", 0), columns=columns)
        lines.append(line + (phrase("forge.tools.db_schema.kv") if t["name"] == "_kv" else ""))
    if got.get("views"):
        lines.append(phrase("forge.tools.db_schema.views", views=", ".join(got["views"])))
    return "\n".join(lines)


def _size(n: Any) -> str:
    return size_fr(int(n or 0))


def rows_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return phrase("forge.tools.db_query.none")
    shown, size = [], 0
    for row in rows:
        line = json.dumps(row, ensure_ascii=False, default=str)
        size += len(line) + 1
        if size > DB_SHOWN:
            shown.append(phrase("forge.tools.db_query.cut"))
            break
        shown.append(line)
    return phrase("forge.tools.db_query.result", count=len(rows), rows="\n".join(shown))


@FORGE.tool("forge_db_schema", description=phrase("forge.tools.db_schema.description"),
            label=phrase("forge.tools.db_schema.label"), args=AppArgs, bundle=BUNDLE,
            episodes=BUILD, owner_only=True)
async def forge_db_schema(args: AppArgs, ctx: Any) -> Any:
    port = forge_port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    try:
        return _nothing(schema_text(await port.db_schema(args.app)))
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=phrase("forge.tools.db.refused", error=exc))


@FORGE.tool("forge_db_query", description=phrase("forge.tools.db_query.description"),
            label=phrase("forge.tools.db_query.label"), args=DbArgs, bundle=BUNDLE,
            episodes=BUILD, max_calls_per_episode=8, owner_only=True)
async def forge_db_query(args: DbArgs, ctx: Any) -> Any:
    port = forge_port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    try:
        return _nothing(rows_text(await port.db_query(args.app, args.sql, args.params)))
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=phrase("forge.tools.db.refused", error=exc))


@FORGE.tool("forge_db_execute", acts=True, description=phrase("forge.tools.db_execute.description"),
            label=phrase("forge.tools.db_execute.label"), args=DbArgs,
            bundle=BUNDLE, episodes=BUILD, max_calls_per_episode=6, owner_only=True)
async def forge_db_execute(args: DbArgs, ctx: Any) -> Any:
    port = forge_port(ctx)
    if port is None or not _may_build(ctx):
        return _refused(ctx)
    try:
        got = await port.db_execute(args.app, args.sql, args.params)
    except ForgeRefused as exc:
        return ToolResult(ok=False, content=phrase("forge.tools.db.refused", error=exc))
    inserted = phrase("forge.tools.db_execute.inserted", id=got["id"]) if got.get("id") is not None else ""
    return phrase("forge.tools.db_execute.done", rows=got.get("rows", 0), id=inserted)
