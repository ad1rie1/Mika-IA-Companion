"""Fournisseur Claude Code : la vraie CLI ``claude -p``, avec son propre login.

Mika ne lit, ne stocke ni ne transmet aucun jeton : la CLI s'authentifie comme
elle le fait pour son utilisateur (mode ``abonnement``), ou reçoit une clé API
Console (mode ``cle_api``). ``CLAUDE_CODE_OAUTH_TOKEN`` ne passe jamais :
l'environnement du sous-processus est reconstruit sur liste blanche.

Une requête du runtime devient une session de la CLI, tenue le temps de la
boucle d'outils de l'épisode (même ``call_id`` d'un tour à l'autre) :

- premier tour : la CLI est lancée, isolée (aucun réglage, aucune mémoire,
  aucun connecteur claude.ai, aucun outil natif — l'atelier et la Forge
  exécutent sous bubblewrap, pas la CLI), avec le prompt système du runtime
  et deux serveurs MCP servis par le relais (``mika`` en main, ``mika_plus`` à
  la demande, que la CLI charge par sa recherche d'outils). Le prompt système
  (``system.txt``) ne reçoit que la zone stable : la zone volatile — où
  voyage ce qui vient d'ailleurs (mails, titres de flux, pages web) — part
  dans le tour utilisateur, encadrée comme le pipeline l'encadre
  (``CONTEXT_HEADER``/``CONTEXT_FOOTER``), jamais avec l'autorité du système ;
- quand la CLI appelle un outil, le relais le met en attente : la réponse est
  ``stop="tool_use"`` et c'est **le runtime** qui l'exécute ;
- les appels écrits dans un même message du modèle forment **un** lot, comme sur
  l'API : les outils du relais sont « lecture seule » pour la CLI (sans quoi elle
  les lance un par un), elle lance chacun dès que son bloc est écrit, et le lot
  se ferme quand le message est fini (``message_stop``, diffusé grâce à
  ``--include-partial-messages``) et que chaque appel annoncé est arrivé ; il est
  rendu dans l'ordre où le modèle les a écrits (ils arrivent au relais dans
  l'ordre de leurs requêtes HTTP) ;
- tour suivant (les résultats dans la requête) : ils sont rendus à la CLI, qui
  continue — rien d'autre ne part, et la passerelle ne mesure pas contre le budget le
  fil que la session tient déjà (``carries``, ADR 0142) ; son message ``result`` fait
  la réponse finale. Si le runtime clôt
  la boucle (les résultats suivis d'un dernier mot à elle : « réponds
  maintenant, sans outil »), ce mot accompagne les résultats rendus — la session
  vivante finit sa réponse, rien n'est refait ;
- annulation (préemption, supplantation, délai) : le groupe de processus est
  arrêté (SIGINT puis SIGKILL) et la session fermée ; une boucle finie sur un
  appel d'outil (un rôle qui le lit comme sortie structurée, un plafond de
  tours) est relâchée par ``release(call_id)`` ; à défaut, la session est
  fauchée après ``idle_s`` — plus long que l'outil le plus lent (un programme de
  l'atelier : 600 s) pour ne jamais faucher une session vivante, plus court que
  le délai d'outil de la CLI (``MCP_TOOL_TIMEOUT``) pour qu'elle ne continue
  jamais seule sur un outil abandonné ;
- **une boucle d'outils ne se reprend pas** : une requête qui porte déjà des
  échanges d'outils sans session vivante (un redémarrage, une bascule de
  fournisseur) est refusée — aplatie en un message, la CLI referait les outils ;
- la lecture de la CLI ne peut pas mourir en silence : une ligne illisible, trop
  longue ou d'une forme inattendue est sautée, et la fin du processus est
  toujours signalée ; l'attente d'un tour est bornée (``turn_timeout_s``) ;
- la sortie est bornée (``CLAUDE_CODE_MAX_OUTPUT_TOKENS`` d'après ``max_tokens`` ; avec des outils, assez pour
  écrire leurs arguments entiers, la CLI ne sachant pas rejouer un appel coupé), et ce plafond est dit à la
  passerelle (``output_tokens``), qui ne rejoue jamais une coupure au même plafond ; une sortie qui passe son plafond
  est ``stop="max_tokens"`` — ``truncated_tool_call`` seulement si un appel d'outil avait été annoncé (sinon la
  parole se coupe à sa dernière phrase, comme ailleurs, au lieu de rejouer toute la session) ;
- l'usage d'un tour somme ses messages ; la plus grande entrée d'un seul (``LLMResponse.prompt_tokens``) sert à la
  passerelle pour juger l'estimation du budget — la CLI renvoie tout le contexte à chaque message, et une recherche
  d'outil en fait un de plus ;
- aucune connexion annexe (``CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC``) et pas de socket de messagerie entre
  sessions (``CLAUDE_CODE_HARBOR_KITE=0``) ; ``mika claude-code check`` vérifie qu'aucune ne s'ouvre ;
- les dossiers d'appel (prompt système, configuration MCP et son jeton de
  session) vivent sous ``XDG_RUNTIME_DIR`` (mémoire, propre à l'utilisateur,
  jamais sauvegardé), en ``0700`` ; ceux d'un processus mort sont purgés.

La CLI rend aussi l'usage de l'abonnement (``rate_limit_event``) : au-delà de
``quota_ceiling``, les appels de fond sont refusés (``QuotaHeld``) — la
passerelle journalise alors le refus, et la conversation, elle,
passe toujours. Une lecture dont la fenêtre est déjà réinitialisée
(``resetsAt`` passé) ne compte plus. Le dernier relevé est gardé dans le
dossier des appels (``quota.json``) : un redémarrage ne l'oublie pas. Un
refus est un ``Held`` (``holds()`` le dit d'avance) : l'arbitre ne lance pas
un épisode de fond qui serait refusé, et un épisode refusé quand même se règle
en ``preempted``, jamais en panne (ADR 0127).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mika.adapters.llm.openai_compat import volatile_system
from mika.adapters.mcp.protocol import Outcome, Tool
from mika.adapters.mcp.relay import Pending, Relay, RelaySession
from mika.kernel.prompt import CONTEXT_FOOTER, CONTEXT_HEADER
from mika.ports.llm import Held, LLMRequest, LLMResponse, Message, ToolCall, Usage
from mika.vocab.phrasebook import phrase

log = logging.getLogger("mika.llm.claude_code")

AUTHS = ("abonnement", "cle_api")
#: les efforts de réflexion que la CLI accepte (``--effort``) ; vide : le sien par défaut
EFFORTS = ("", "low", "medium", "high", "xhigh", "max")
#: les seules variables du parent qui passent (HOME : la CLI y trouve son login)
INHERITED = ("HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR", "XDG_RUNTIME_DIR")
#: jamais transmises, même si le processus de Mika les a
FORBIDDEN = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")
SERVERS = {"mika": "mika", "plus": "mika_plus"}
#: le temps de regrouper des appels d'outils partis ensemble, quand la CLI ne diffuse pas son message
#: (sans ``message_stop``, rien ne dit que le modèle a fini d'écrire ses appels)
BATCH_WINDOW_S = 0.15
#: le message du modèle fini, ce qu'on attend encore un appel annoncé qui n'est pas arrivé au relais
LATE_CALL_S = 2.0
READ_LIMIT = 16 * 1024 * 1024
STDERR_KEPT = 4000
#: le dernier relevé du quota de l'abonnement, dans le dossier des appels : un redémarrage ne l'oublie pas, sans
#: quoi le premier appel de fond passait toujours, même l'abonnement entamé au-delà du plafond (ADR 0127)
QUOTA_FILE = "quota.json"
#: le plafond de sortie donné à la CLI ne descend pas sous ceci (un modèle qui réfléchit
#: dépenserait un petit budget avant le premier mot)
MIN_OUTPUT_TOKENS = 1024
def sockets_dir() -> Path:
    """Où la CLI ouvre sa socket de messagerie entre sessions (``cc-socks/<pid>.sock``)."""
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / "cc-socks"


def _parent_of(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return 0


def opens_socket(pid: int, folder: Path | None = None) -> bool:
    """Ce processus (ou un de ses enfants) a-t-il une socket de messagerie ouverte ? (la vérification de
    ``CLAUDE_CODE_HARBOR_KITE``, une variable non documentée)."""
    try:
        names = [p.stem for p in (folder or sockets_dir()).glob("*.sock")]
    except OSError:
        return False
    return any(n.isdigit() and (int(n) == pid or _parent_of(int(n)) == pid) for n in names)


#: la sortie d'une requête qui porte des outils : ce qu'un appel d'outil coupé à ``max_tokens`` aurait obtenu en étant
#: rejoué (``runtime.tools.TOOL_CALL_CAP_CEILING``) — la CLI, elle, ne sait pas reprendre une boucle d'outils dans
#: une nouvelle session : elle l'a d'emblée (sonde du 12 octobre : écrire une app en répondant coupait l'appel, et la
#: réponse échouait entière, ADR 0104). Le texte, lui, reste court : sa consigne le borne.
TOOLS_OUTPUT_TOKENS = 16_384
#: un dossier d'appel sans processus connu, plus vieux que ça, est une épave (secondes)
STALE_CALL_S = 3600.0
#: le préfixe des dossiers d'appel
CALL_PREFIX = "appel-"


def runtime_dir(scope: str | os.PathLike[str] = "") -> Path:
    """Où rangent les dossiers d'appel : sous ``XDG_RUNTIME_DIR`` (en mémoire, propre à
    l'utilisateur, hors de tout dossier sauvegardé), à défaut le dossier temporaire
    suffixé de l'uid ; un sous-dossier par ``scope`` (le dossier de données), pour que
    deux Mika ne purgent pas les appels l'une de l'autre."""
    base = os.environ.get("XDG_RUNTIME_DIR") or ""
    root = Path(base) / "mika" if base and Path(base).is_dir() else \
        Path(tempfile.gettempdir()) / f"mika-{os.getuid()}"
    tag = hashlib.sha256(str(Path(scope).resolve()).encode()).hexdigest()[:12] if str(scope) else "defaut"
    return root / "claude-code" / tag


def foreign_owner(path: Path) -> Path | None:
    """Le premier dossier du chemin (lui ou un parent existant) qui n'est ni à nous ni à root :
    un ``/tmp/mika-<uid>`` créé d'avance par un autre compte recevrait sinon nos prompts privés
    et nos jetons de session (il peut renommer ce qu'on crée chez lui). ``None`` : sûr."""
    uid = os.getuid()
    for p in (path, *path.parents):
        try:
            owner = os.lstat(p).st_uid
        except OSError:
            continue  # pas encore créé : on le créera, à nous
        if owner not in (uid, 0):
            return p
    return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def purge_stale(work_dir: Path, *, now: float | None = None) -> int:
    """Efface les dossiers d'appel laissés par un processus mort (``appel-<pid>-…``) ou,
    sans pid lisible, plus vieux que ``STALE_CALL_S`` ; rend le nombre effacé."""
    if not work_dir.is_dir():
        return 0
    now = time.time() if now is None else now
    gone = 0
    for d in work_dir.glob(f"{CALL_PREFIX}*"):
        pid_text = d.name[len(CALL_PREFIX):].split("-", 1)[0]
        try:
            dead = int(pid_text) != os.getpid() and not _pid_alive(int(pid_text))
        except ValueError:
            try:
                dead = now - d.stat().st_mtime > STALE_CALL_S
            except OSError:
                continue
        if dead:
            shutil.rmtree(d, ignore_errors=True)
            gone += 1
    return gone


#: l'erreur de l'API quand la réponse dépasse ``CLAUDE_CODE_MAX_OUTPUT_TOKENS`` (« Claude's response exceeded the
#: 2500 output token maximum ») : une sortie tronquée, pas une panne
OUTPUT_CAPPED = re.compile(r"exceeded the \d+ output token maximum", re.IGNORECASE)


class ClaudeCodeError(RuntimeError):
    """La CLI a échoué (non connectée, absente, erreur en cours de tour)."""


class QuotaHeld(ClaudeCodeError, Held):
    """Appel de fond refusé : l'abonnement est trop entamé (un ``Held`` : rien n'a été tenté, ADR 0127)."""


@dataclass(frozen=True, slots=True)
class QuotaReading:
    window: str
    utilization: float
    resets_at: int = 0


@dataclass(slots=True)
class _Run:
    session: RelaySession | None
    proc: asyncio.subprocess.Process | None = None
    workdir: Path | None = None
    events: asyncio.Queue[tuple[str, Any]] = field(default_factory=asyncio.Queue)
    handed: set[str] = field(default_factory=set)
    model: str = ""
    stderr: str = ""
    reaper: asyncio.TimerHandle | None = None
    tasks: list[asyncio.Task[Any]] = field(default_factory=list)
    #: les serveurs MCP donnés à la CLI (``mcp.json``) : chacun doit être connecté
    servers: tuple[str, ...] = ()
    #: la CLI diffuse son message (``stream_event``) : on sait quand le modèle a fini d'écrire
    streaming: bool = False
    #: le modèle est en train d'écrire un message (entre ``message_start`` et ``message_stop``)
    writing: bool = False
    #: les appels d'outils du relais que ce message annonce, dans l'ordre écrit : (id, outil, arguments)
    announced: list[tuple[str, str, Any]] = field(default_factory=list)
    #: ceux qui n'attendent plus rien de nous : déjà rendus au runtime, ou répondus par la CLI elle-même
    settled: set[str] = field(default_factory=set)
    #: l'usage de chaque message du modèle (son identifiant → le plus haut relevé vu) et le message en cours d'écriture :
    #: un tour qui finit sur des appels d'outils rend l'usage de ses messages — la boucle s'arrête souvent sur un
    #: appel d'outil, avant le ``result`` de la CLI, et l'appel comptait zéro jeton (ADR 0127)
    usage: dict[str, Usage] = field(default_factory=dict)
    current: str = ""
    #: les messages dont l'usage est déjà rendu
    reported: set[str] = field(default_factory=set)

    def on_call(self, p: Pending) -> None:
        self.events.put_nowait(("call", p))


class ClaudeCodeBackend:
    #: une boucle d'outils commencée ailleurs ne se reprend pas ici (voir l'en-tête) :
    #: la passerelle ne bascule jamais vers ce fournisseur en cours de boucle
    resumes_tool_loops = False

    def __init__(
        self,
        model: str = "",
        *,
        relay: Relay,
        relay_base: Any,
        name: str = "claude_code",
        auth: str = "abonnement",
        api_key: str = "",
        claude_bin: str = "",
        config_dir: str = "",
        work_dir: str | Path | None = None,
        idle_s: float = 660.0,
        quota_ceiling: float = 0.8,
        tool_timeout_s: float = 900.0,
        turn_timeout_s: float = 900.0,
        effort: str = "",
    ) -> None:
        if auth not in AUTHS:
            raise ValueError(f"mode d'authentification inconnu : {auth!r} (attendu : {' ou '.join(AUTHS)})")
        if effort not in EFFORTS:
            raise ValueError(f"effort de réflexion inconnu : {effort!r} (attendu : {', '.join(e for e in EFFORTS if e)})")
        #: l'effort de réflexion passé à la CLI (``--effort``) ; vide : son défaut
        self.effort = effort
        self.name = name
        self.model = model
        self.auth = auth
        self._api_key = api_key
        self.claude_bin = claude_bin
        self.config_dir = config_dir
        self.relay = relay
        #: l'URL de base du serveur qui monte le relais (connue quand il écoute)
        self._relay_base = relay_base
        self.work_dir = Path(work_dir) if work_dir else runtime_dir()
        # fauchée avant que la CLI ne renonce d'elle-même à un outil (elle continuerait seule)
        self.idle_s = min(idle_s, max(1.0, tool_timeout_s - 60.0))
        self.quota_ceiling = quota_ceiling
        self.tool_timeout_s = tool_timeout_s
        #: l'attente d'un tour de la CLI (entre deux appels d'outils, ou jusqu'à sa réponse)
        self.turn_timeout_s = turn_timeout_s
        self.quota: dict[str, QuotaReading] = self._load_quota()
        self._runs: dict[str, _Run] = {}
        self._purged = False

    # ── Ce que la CLI reçoit ─────────────────────────────────────────────

    def opened_socket(self, call_id: str) -> bool:
        """La CLI de cet appel, encore en vie, a-t-elle ouvert une socket de messagerie entre sessions ?"""
        run = self._runs.get(call_id)
        proc = run.proc if run is not None else None
        return proc is not None and opens_socket(proc.pid)

    def binary(self) -> str:
        found = self.claude_bin or shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
        return found

    def argv(self, req: LLMRequest, workdir: Path, *, mcp: bool, deferred: bool) -> list[str]:
        args = [self.binary(), "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                "--verbose", "--system-prompt-file", str(workdir / "system.txt"),
                "--setting-sources", "", "--strict-mcp-config",
                "--tools", "ToolSearch" if deferred else "",
                "--permission-mode", "dontAsk", "--no-session-persistence",
                # ``message_stop`` : la fin du message du modèle, qui ferme un lot d'appels d'outils
                "--include-partial-messages"]
        if mcp:
            args += ["--mcp-config", str(workdir / "mcp.json"),
                     "--allowedTools", ",".join(f"mcp__{s}__*" for s in SERVERS.values())]
        if self.model:
            args += ["--model", self.model]
        if self.effort:
            args += ["--effort", self.effort]
        return args

    def output_tokens(self, req: LLMRequest) -> int:
        """Le plafond de sortie donné à la CLI pour ``req`` (``CLAUDE_CODE_MAX_OUTPUT_TOKENS``) : celui demandé,
        jamais sous ``MIN_OUTPUT_TOKENS`` ; avec des outils, ``TOOLS_OUTPUT_TOKENS`` au moins. La passerelle le lit
        pour réserver la sortie et ne pas rejouer une coupure au même plafond."""
        return max(MIN_OUTPUT_TOKENS, int(req.max_tokens), TOOLS_OUTPUT_TOKENS if req.tools else 0)

    def env(self, req: LLMRequest) -> dict[str, str]:
        out = {k: os.environ[k] for k in INHERITED if os.environ.get(k)}
        out.update({
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
            # aucune connexion annexe (mises à jour, télémétrie…) : démarrage 0,42 → 0,12 s, fin ~0,95 → 0,20 s
            # (audit du 2026-10-08)
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            # pas de socket de messagerie entre sessions (``/run/user/<uid>/cc-socks/<pid>.sock``) : par elle, tout
            # processus du même compte pouvait glisser un message dans sa session, hors du runtime. Variable interne,
            # non documentée : ``mika claude-code check`` dit si la CLI en ouvre encore une
            "CLAUDE_CODE_HARBOR_KITE": "0",
            "MCP_TOOL_TIMEOUT": str(int(self.tool_timeout_s * 1000)),
            # la sortie suit le budget de la requête (la CLI l'ignorait : un murmure pouvait faire une page) ; avec des
            # outils, de quoi écrire leurs arguments entiers (le code d'une app)
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(self.output_tokens(req)),
        })
        if self.config_dir:
            out["CLAUDE_CONFIG_DIR"] = self.config_dir
        if self.auth == "cle_api" and self._api_key:
            out["ANTHROPIC_API_KEY"] = self._api_key
        for key in FORBIDDEN:
            out.pop(key, None)
        return out

    @staticmethod
    def user_message(req: LLMRequest) -> dict[str, Any]:
        """Le fil en un message : l'historique, puis le dernier tour tel quel
        (il porte déjà l'état interne). Un bloc volatile que la requête porte
        encore dans son système (``system_volatile``, pas déjà encadré dans ce
        dernier tour) y descend, encadré comme le pipeline l'encadre : ce qui
        vient d'ailleurs ne parle jamais avec l'autorité du système."""
        turns = [m for m in req.messages if m.role in ("user", "assistant") and m.content.strip()]
        last = turns[-1] if turns and turns[-1].role == "user" else None
        history = turns[:-1] if last is not None else turns
        lines = [phrase("llm.thread.mine", text=m.content.strip()) if m.role == "assistant" else m.content.strip()
                 for m in history]
        text = last.content if last is not None else ""
        volatile = volatile_system(req)
        if volatile:
            text = f"{CONTEXT_HEADER}\n{volatile}\n{CONTEXT_FOOTER}" + (f"\n\n{text}" if text.strip() else "")
        if lines:
            text = phrase("llm.thread.header") + "\n" + "\n".join(lines) + "\n" + phrase("llm.thread.footer") \
                + "\n\n" + text
        content: list[dict[str, Any]] = [
            {"type": "image", "source": {"type": "base64", "media_type": i.mime, "data": i.data}}
            for i in (last.images if last is not None else ())]
        content.append({"type": "text", "text": text or phrase("llm.thread.silence")})
        return {"type": "user", "message": {"role": "user", "content": content}}

    def mcp_config(self, session: RelaySession, base: str) -> dict[str, Any]:
        servers: dict[str, Any] = {}
        for part, server in SERVERS.items():
            if not session.parts[part].tools():
                continue
            conf: dict[str, Any] = {"type": "http", "url": Relay.url(base, session, part),
                                    "headers": {"Authorization": f"Bearer {session.token}"}}
            if part == "mika":
                conf["alwaysLoad"] = True
            servers[server] = conf
        return {"mcpServers": servers}

    # ── Appel ────────────────────────────────────────────────────────────

    async def complete(self, req: LLMRequest) -> LLMResponse:
        run = self._runs.get(req.call_id)
        try:
            if run is not None and self._answers(run, req):
                self._feed(run, req)
            else:
                if run is not None:
                    await self._stop(req.call_id)
                run = await self._start(req)
            return await self._next(req.call_id, run)
        except BaseException:
            await self._stop(req.call_id)
            raise

    def carries(self, req: LLMRequest) -> bool:
        """``req`` poursuit-elle une boucle dont la session est vivante (elle attend ces résultats) ? Alors seuls ses
        nouveaux résultats partent : le reste du fil est déjà dans la session, que la CLI tient dans sa propre
        fenêtre — la passerelle ne le mesure pas contre le budget (ADR 0142)."""
        run = self._runs.get(req.call_id)
        return run is not None and self._answers(run, req)

    def _answers(self, run: _Run, req: LLMRequest) -> bool:
        results = _results_of(req.messages)
        return bool(run.handed) and bool(results) and {m.tool_call_id for m in results} >= run.handed

    def _feed(self, run: _Run, req: LLMRequest) -> None:
        if run.reaper is not None:
            run.reaper.cancel()
            run.reaper = None
        assert run.session is not None
        mine = [m for m in _results_of(req.messages) if m.tool_call_id in run.handed]
        closing = _closing_word(req.messages)
        for i, m in enumerate(mine):
            # le dernier mot du runtime (clore la boucle) arrive avec le dernier résultat : la CLI ne
            # reçoit plus rien d'autre de nous, c'est la seule voie pour qu'elle le lise
            content = f"{m.content}\n\n{closing}" if closing and i == len(mine) - 1 else m.content
            run.session.resolve(m.tool_call_id or "", Outcome(content, bool(m.is_error)))
        run.handed.clear()

    async def _start(self, req: LLMRequest) -> _Run:
        if any(m.role == "tool" or m.tool_calls for m in req.messages):
            # aplatie en un message, la boucle perdrait ses échanges d'outils : la CLI les referait
            raise ClaudeCodeError("une boucle d'outils commencée ailleurs (ou avant un redémarrage) ne se reprend "
                                  "pas dans une nouvelle session de la CLI")
        self._hold_for_quota(req)
        binary = self.binary()
        if not Path(binary).is_file() and shutil.which(binary) is None:
            raise ClaudeCodeError(f"CLI Claude Code introuvable : {binary}")
        core = [_tool(t) for t in req.tools if not t.deferred]
        extra = [_tool(t) for t in req.tools if t.deferred]
        base = self._relay_base() if callable(self._relay_base) else self._relay_base
        if (core or extra) and not base:
            raise ClaudeCodeError("le relais MCP n'est pas joignable (serveur pas encore à l'écoute)")
        self._prepare_work_dir()
        run = _Run(session=None)
        # enregistrée tout de suite : une erreur plus loin (disque plein…) l'arrête entière, session comprise
        self._runs[req.call_id] = run
        if core or extra:
            run.session = self.relay.open(core, extra, run.on_call)
        run.workdir = Path(tempfile.mkdtemp(prefix=f"{CALL_PREFIX}{os.getpid()}-", dir=self.work_dir))
        # la zone stable seule : le volatile (la bande citée comprise) voyage dans le tour utilisateur (``user_message``)
        _write_private(run.workdir / "system.txt", req.system_stable)
        if run.session is not None:
            config = self.mcp_config(run.session, str(base))
            run.servers = tuple(config["mcpServers"])
            _write_private(run.workdir / "mcp.json", json.dumps(config))
        (run.workdir / "cwd").mkdir()
        run.proc = await asyncio.create_subprocess_exec(
            *self.argv(req, run.workdir, mcp=run.session is not None, deferred=bool(extra)),
            cwd=run.workdir / "cwd", env=self.env(req), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
            limit=READ_LIMIT)
        assert run.proc.stdin is not None
        run.proc.stdin.write((json.dumps(self.user_message(req), ensure_ascii=False) + "\n").encode())
        await run.proc.stdin.drain()
        run.proc.stdin.close()
        run.tasks = [asyncio.create_task(self._read(run)), asyncio.create_task(self._drain_stderr(run))]
        return run

    def _prepare_work_dir(self) -> None:
        """Le dossier des appels, privé (``0700``) ; à sa première utilisation, les épaves
        laissées par un processus mort (prompts privés, jetons de session) sont effacées.
        Un dossier tenu par un autre compte est refusé : on n'y écrit rien."""
        squatted = foreign_owner(self.work_dir)
        if squatted is not None:
            raise ClaudeCodeError(f"le dossier des appels passe par {squatted}, qui appartient à un autre compte : "
                                  "rien n'y est écrit (définis XDG_RUNTIME_DIR)")
        self.work_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            self.work_dir.chmod(0o700)
        if not self._purged:
            self._purged = True
            gone = purge_stale(self.work_dir)
            if gone:
                log.info("Claude Code : %d dossier(s) d'appel abandonné(s) effacé(s)", gone)

    async def _next(self, call_id: str, run: _Run) -> LLMResponse:
        texts: list[str] = []
        while True:
            try:
                kind, value = await asyncio.wait_for(run.events.get(), self.turn_timeout_s)
            except TimeoutError:
                self._schedule_stop(call_id)
                raise ClaudeCodeError(f"la CLI n'a rien dit en {self.turn_timeout_s:.0f} s") from None
            if kind == "text":
                texts.append(value)
            elif kind == "wake":
                continue
            elif kind == "call":
                batch = [value]
                ended = await self._gather(run, batch, texts)
                if ended is not None:  # la CLI s'est arrêtée pendant qu'on complétait le lot : c'est l'issue
                    return self._ended(call_id, run, *ended, texts)
                placed = _place(run.announced, run.settled, batch)
                batch.sort(key=lambda p: placed.get(p.id, len(run.announced)))  # stable : un appel sans bloc en dernier
                run.settled.update(run.announced[i][0] for i in placed.values())
                run.handed.update(p.id for p in batch)
                self._arm_reaper(call_id, run)
                usage, prompt = _unreported(run)
                return LLMResponse("".join(texts), tuple(ToolCall(p.id, p.name, p.args) for p in batch),
                                   stop="tool_use", usage=usage, model=run.model or self.model, prompt_tokens=prompt)
            else:
                return self._ended(call_id, run, kind, value, texts)

    async def _gather(self, run: _Run, batch: list[Pending], texts: list[str]) -> tuple[str, Any] | None:
        """Complète le lot que ``batch`` commence : tous les appels d'outils d'un même message du modèle.
        Rend l'issue de la CLI si elle s'arrête entre-temps.

        La CLI lance un appel dès que son bloc est écrit, pendant que le modèle écrit encore les suivants :
        le lot est complet quand le message est fini et que ses appels se répondent un à un — chaque appel
        annoncé est arrivé au relais (ou a reçu sa réponse de la CLI elle-même), chaque appel arrivé a son
        bloc (sinon la lecture de stdout est en retard sur le relais : deux canaux). Ce qui manque encore est
        attendu ``LATE_CALL_S`` ; au-delà, un appel en retard ira au tour suivant. Une CLI qui ne diffuse pas
        son message : la fenêtre d'avant."""
        loop = asyncio.get_running_loop()
        start = loop.time()
        late_since: float | None = None
        while True:
            now = loop.time()
            if not run.streaming:
                wait = start + BATCH_WINDOW_S - now
            elif run.writing:
                wait = start + self.turn_timeout_s - now
            elif not _matched(run.announced, run.settled, batch):
                late_since = now if late_since is None else late_since
                wait = late_since + LATE_CALL_S - now
            else:
                return None
            if wait <= 0:
                return None
            try:
                kind, value = await asyncio.wait_for(run.events.get(), wait)
            except TimeoutError:
                continue
            if kind == "call":
                batch.append(value)
            elif kind == "text":
                texts.append(value)
            elif kind != "wake":
                return kind, value

    def _ended(self, call_id: str, run: _Run, kind: str, value: Any, texts: Sequence[str] = ()) -> LLMResponse:
        self._schedule_stop(call_id)
        if kind == "exit":
            raise ClaudeCodeError(f"la CLI s'est arrêtée sans réponse (code {value}) : {run.stderr[-300:]}".strip())
        if kind == "mcp":
            raise ClaudeCodeError(f"la CLI n'a pas pu joindre ses outils ({value}) : elle aurait répondu "
                                  "sans ses mains")
        d: Mapping[str, Any] = value
        if d.get("is_error") or d.get("subtype") != "success":
            detail = d.get("result") or ", ".join(map(str, d.get("errors") or ())) or d.get("subtype")
            if OUTPUT_CAPPED.search(str(detail)):
                # la sortie a passé son plafond : une réponse tronquée, comme chez les autres fournisseurs — l'appelant
                # sait la traiter (la relecture diffère et redécoupe sa fenêtre) ; une panne se réessaierait à
                # l'identique (sonde réelle du 2026-10-10). Un appel d'outil coupé seulement si le message en
                # annonçait un : sinon c'est une parole trop longue, coupée à sa dernière phrase par la passerelle,
                # pas une session entière à rejouer
                return LLMResponse(answer(texts, ""), stop="max_tokens", model=run.model or self.model,
                                   truncated_tool_call=bool(run.announced))
            raise ClaudeCodeError(f"la CLI a échoué : {detail}")
        stop = {"max_tokens": "max_tokens", "refusal": "refusal"}.get(str(d.get("stop_reason") or ""), "end")
        models = list((d.get("modelUsage") or {}).keys())
        model = run.model or (models[0] if models else self.model)
        # l'usage du ``result`` couvre toute la session : ce que les tours d'outils ont déjà rendu n'y est pas recompté
        usage, prompt = _unreported(run) if run.usage else (_usage(d.get("usage")), 0)
        return LLMResponse(answer(texts, str(d.get("result") or "")), stop=stop, usage=usage, model=model,
                           prompt_tokens=prompt)

    # ── Lecture de la CLI ────────────────────────────────────────────────

    async def _read(self, run: _Run) -> None:
        """Lit la CLI jusqu'au bout. Ne meurt jamais en silence : une ligne qu'on ne
        comprend pas est sautée, et la fin est **toujours** signalée (``exit``) quand
        aucun résultat n'est venu — sinon l'appel attendait sans fin."""
        assert run.proc is not None and run.proc.stdout is not None
        result_seen = False
        code: int | None = None
        try:
            while True:
                try:
                    line = await run.proc.stdout.readline()
                except ValueError:  # ligne au-delà de READ_LIMIT : le tampon est vidé, la suite se relit
                    log.warning("Claude Code : une ligne trop longue a été sautée")
                    continue
                if not line:
                    break
                try:
                    if self._line(run, line):
                        result_seen = True
                except Exception as exc:  # une forme inattendue ne tue pas la lecture
                    log.warning("Claude Code : ligne illisible sautée (%r)", exc)
            code = await run.proc.wait()
        finally:
            if not result_seen:
                run.events.put_nowait(("exit", code))

    def _line(self, run: _Run, line: bytes) -> bool:
        """Une ligne de la CLI ; ``True`` si c'est son résultat."""
        try:
            d = json.loads(line)
        except ValueError:
            return False
        if not isinstance(d, dict):
            return False
        kind = d.get("type")
        if kind == "system" and d.get("subtype") == "init":
            broken = _unreachable(d, run.servers)
            if broken:
                # la vraie CLI continue sans un serveur MCP qui a échoué : le modèle
                # n'aurait alors aucun outil et raconterait ses appels au lieu de les faire
                run.events.put_nowait(("mcp", broken))
        elif kind == "stream_event":
            event = d.get("event")
            phase = event.get("type") if isinstance(event, Mapping) else None
            if not d.get("parent_tool_use_id") and isinstance(event, Mapping):
                if phase == "message_start" and isinstance(event.get("message"), Mapping):
                    run.current = str(event["message"].get("id") or "")
                    _note_usage(run, run.current, event["message"].get("usage"))
                elif phase == "message_delta":
                    _note_usage(run, run.current, event.get("usage"))
            if phase in ("message_start", "message_stop") and not d.get("parent_tool_use_id"):
                run.streaming = True
                run.writing = phase == "message_start"
                if run.writing:  # un nouveau message : le lot précédent est clos, la CLI attendait ses résultats
                    run.announced.clear()
                    run.settled.clear()
                run.events.put_nowait(("wake", None))
        elif kind == "assistant":
            message = d.get("message")
            message = message if isinstance(message, Mapping) else {}
            run.model = str(message.get("model") or run.model)
            if not d.get("parent_tool_use_id"):
                _note_usage(run, str(message.get("id") or ""), message.get("usage"))
            for block in message.get("content") or ():
                if not isinstance(block, Mapping):
                    continue
                if block.get("type") == "text" and block.get("text"):
                    run.events.put_nowait(("text", str(block["text"])))
                elif block.get("type") == "tool_use" and (tool := _relayed(str(block.get("name") or ""))):
                    run.announced.append((str(block.get("id") or ""), tool, block.get("input")))
                    run.events.put_nowait(("wake", None))
        elif kind == "user":
            # une réponse d'outil écrite par la CLI : pour un appel qu'elle a refusé elle-même, elle arrive sans
            # que le relais ait rien vu — on n'attend plus cet appel
            message = d.get("message")
            for block in (message.get("content") if isinstance(message, Mapping) else None) or ():
                if isinstance(block, Mapping) and block.get("type") == "tool_result" and block.get("tool_use_id"):
                    run.settled.add(str(block["tool_use_id"]))
                    run.events.put_nowait(("wake", None))
        elif kind == "rate_limit_event":
            info = d.get("rate_limit_info")
            self._note_quota(info if isinstance(info, Mapping) else {})
        elif kind == "result":
            run.events.put_nowait(("result", d))
            return True
        return False

    async def _drain_stderr(self, run: _Run) -> None:
        assert run.proc is not None and run.proc.stderr is not None
        while chunk := await run.proc.stderr.read(4096):
            run.stderr = (run.stderr + chunk.decode(errors="replace"))[-STDERR_KEPT:]

    # ── Quota de l'abonnement ────────────────────────────────────────────

    def _note_quota(self, info: Mapping[str, Any]) -> None:
        """Les fenêtres d'usage de l'abonnement : un objet par fenêtre, ou une liste
        (une forme qui changerait ne doit jamais casser la lecture)."""
        windows = info.get("unifiedWindows")
        if isinstance(windows, Mapping):
            items = [(str(k), w) for k, w in windows.items()]
        elif isinstance(windows, list):
            items = [(str(w.get("window") or w.get("name") or i) if isinstance(w, Mapping) else str(i), w)
                     for i, w in enumerate(windows)]
        else:
            return
        noted = False
        for window, w in items:
            if not isinstance(w, Mapping) or not isinstance(w.get("utilization"), (int, float)):
                continue
            resets = w.get("resetsAt")
            self.quota[window] = QuotaReading(window, float(w["utilization"]),
                                              int(resets) if isinstance(resets, (int, float)) else 0)
            noted = True
        if noted:
            self._save_quota()

    def _quota_path(self) -> Path:
        return self.work_dir / QUOTA_FILE

    def _load_quota(self) -> dict[str, QuotaReading]:
        """Le relevé gardé au dernier démarrage (vide : aucun, illisible, ou un dossier tenu par un autre compte —
        un relevé posé là par un autre ne règle pas nos appels). Une fenêtre déjà réinitialisée tombe à la lecture
        (``_live_quota``)."""
        if self.auth != "abonnement" or foreign_owner(self.work_dir) is not None:
            return {}
        try:
            rows = json.loads(self._quota_path().read_text())
        except (OSError, ValueError):
            return {}
        out: dict[str, QuotaReading] = {}
        for r in rows if isinstance(rows, list) else ():
            if isinstance(r, Mapping) and isinstance(r.get("window"), str) \
                    and isinstance(r.get("utilization"), (int, float)) and isinstance(r.get("resets_at"), int):
                out[r["window"]] = QuotaReading(r["window"], float(r["utilization"]), r["resets_at"])
        return out

    def _save_quota(self) -> None:
        """Le relevé, gardé pour le prochain démarrage (privé, écrit d'un bloc) ; un échec d'écriture ne coûte que
        ce souvenir-là."""
        rows = [{"window": q.window, "utilization": q.utilization, "resets_at": q.resets_at}
                for q in self.quota.values()]
        try:
            self._prepare_work_dir()
            tmp = self._quota_path().with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(rows, f)
            os.replace(tmp, self._quota_path())
        except (OSError, ClaudeCodeError) as exc:
            log.warning("Claude Code : relevé du quota non gardé (%s)", type(exc).__name__)

    def _live_quota(self, now: float | None = None) -> list[QuotaReading]:
        """Les lectures encore valables : une fenêtre réinitialisée (``resetsAt`` passé) ne compte plus."""
        now = time.time() if now is None else now
        for key in [k for k, q in self.quota.items() if q.resets_at and q.resets_at <= now]:
            del self.quota[key]
        return list(self.quota.values())

    def holds(self, priority: int) -> str:
        """Un appel à cette priorité serait-il refusé d'avance (``QuotaHeld``) ? La raison en mots, « » : il
        passerait. La conversation (priorité 0) passe toujours."""
        if self.auth != "abonnement" or self.quota_ceiling <= 0 or priority == 0:
            return ""
        worst = max(self._live_quota(), key=lambda q: q.utilization, default=None)
        if worst is None or worst.utilization < self.quota_ceiling:
            return ""
        return f"abonnement entamé à {worst.utilization:.0%} ({worst.window})"

    def _hold_for_quota(self, req: LLMRequest) -> None:
        reason = self.holds(req.priority)
        if reason:
            raise QuotaHeld(f"{reason} : appel de fond refusé pour préserver la réserve")

    def status(self) -> dict[str, Any]:
        return {"sessions": len(self._runs),
                "quota": {q.window: round(q.utilization, 3) for q in sorted(self._live_quota(), key=lambda q: q.window)}}

    def release(self, call_id: str) -> None:
        """La boucle ``call_id`` est finie (la passerelle relaie la fin dite par le runtime) :
        la session, si elle attend encore un résultat d'outil, est arrêtée tout de suite."""
        if call_id in self._runs:
            self._schedule_stop(call_id)

    # ── Arrêt ────────────────────────────────────────────────────────────

    def _arm_reaper(self, call_id: str, run: _Run) -> None:
        if run.reaper is not None:
            run.reaper.cancel()
        run.reaper = asyncio.get_running_loop().call_later(self.idle_s, self._schedule_stop, call_id)

    def _schedule_stop(self, call_id: str) -> None:
        task = asyncio.get_running_loop().create_task(self._stop(call_id))
        task.add_done_callback(lambda t: t.cancelled() or t.exception())

    async def _stop(self, call_id: str) -> None:
        run = self._runs.pop(call_id, None)
        if run is None:
            return
        if run.reaper is not None:
            run.reaper.cancel()
        if run.session is not None:
            self.relay.close(run.session)
        proc = run.proc
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGINT)
            try:
                await asyncio.wait_for(asyncio.shield(proc.wait()), 3.0)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()
        for task in run.tasks:
            task.cancel()
        if run.workdir is not None:
            shutil.rmtree(run.workdir, ignore_errors=True)

    async def aclose(self) -> None:
        for call_id in list(self._runs):
            await self._stop(call_id)


def _tool(t: Any) -> Tool:
    # « lecture seule » pour la CLI, quel que soit l'outil : sans la marque, elle lance les outils MCP un par un (le
    # suivant après la réponse du précédent), et N appels écrits ensemble coûtaient N tours de la boucle du runtime.
    # La marque ne règle que l'envoi : c'est le runtime qui exécute le lot, un appel après l'autre, dans l'ordre écrit.
    return Tool(t.name, t.description, t.schema, read_only=True)


#: ce qui clôt une phrase : un texte qui s'arrête là, avant une recherche d'outil, est un préambule fini
_SENTENCE_END = ".!?…»\")"
#: un préambule fini qu'on écarte (« je vérifie. », « Je regarde. ») est court ; au-delà, c'est le début de la réponse
#: (ADR 0157)
#: (banc du profil, 2026-10-28 : un caractère écrit en deux messages perdait ses quatre premières phrases, et avec elles
#: le trait le plus marqué de la tsundere — pour toute sa vie)
PREAMBLE_MAX = 60


def answer(texts: Sequence[str], result: str) -> str:
    """La réponse d'un tour. ``result`` ne porte que le dernier message de la CLI : quand le modèle s'est
    interrompu au milieu d'une phrase pour chercher un outil (``ToolSearch``, que la CLI exécute elle-même) et
    l'a reprise dans un second message, le début de la réponse se perdait (sonde réelle du 2026-10-09 :
    « pas, et je ne connais pas ton équipe… »). Ce qui précède est rendu quand il s'arrête en pleine phrase, ou
    quand c'est un vrai début fini (un second message, en paragraphe à part) ; un préambule court et fini
    (« je vérifie. », ``PREAMBLE_MAX``) reste écarté, comme sur l'API."""
    whole, tail = "".join(texts).rstrip(), result.strip()
    if not tail or not whole.endswith(tail) or len(whole) == len(tail):
        return result
    before = whole[: len(whole) - len(tail)]
    if not before.strip():
        return result
    if before.rstrip()[-1] in _SENTENCE_END:
        if len(before.strip()) <= PREAMBLE_MAX:
            return result
        return before.rstrip() + "\n\n" + tail
    glue = "" if before[-1].isspace() else " "
    return before + glue + tail


def _relayed(name: str) -> str:
    """Le nom qu'un outil du relais porte au relais (``mcp__mika__x`` → ``x``) ; vide pour un autre outil
    (``ToolSearch``, que la CLI exécute elle-même)."""
    for server in SERVERS.values():
        prefix = f"mcp__{server}__"
        if name.startswith(prefix):
            return name[len(prefix):]
    return ""


def _place(announced: Sequence[tuple[str, str, Any]], settled: set[str], batch: Sequence[Pending]) -> dict[str, int]:
    """Chaque appel arrivé au relais → l'index du bloc ``tool_use`` qui l'a demandé : même outil et mêmes
    arguments, à défaut le même outil, le premier libre dans l'ordre écrit. Un appel sans bloc n'est pas placé."""
    free = [i for i, (tid, _, _) in enumerate(announced) if tid not in settled]
    placed: dict[str, int] = {}
    for p in batch:
        same = [i for i in free if announced[i][1] == p.name]
        pick = next((i for i in same if announced[i][2] == p.args), same[0] if same else None)
        if pick is not None:
            placed[p.id] = pick
            free.remove(pick)
    return placed


def _matched(announced: Sequence[tuple[str, str, Any]], settled: set[str], batch: Sequence[Pending]) -> bool:
    """Les appels arrivés et ceux que le message annonce se répondent un à un (les annoncés déjà réglés à part)."""
    placed = _place(announced, settled, batch)
    return len(placed) == len(batch) and all(tid in settled or i in placed.values()
                                             for i, (tid, _, _) in enumerate(announced))


def _trailing_results(messages: Sequence[Message]) -> list[Message]:
    out: list[Message] = []
    for m in reversed(messages):
        if m.role != "tool":
            break
        out.append(m)
    return out[::-1]


def _closing_word(messages: Sequence[Message]) -> str:
    """Le dernier mot du runtime après les résultats d'outils (« réponds maintenant ») : vide sinon."""
    if len(messages) >= 2 and messages[-1].role == "user" and messages[-2].role == "tool":
        return str(messages[-1].content or "")
    return ""


def _results_of(messages: Sequence[Message]) -> list[Message]:
    """Les résultats d'outils qui terminent la requête — suivis, au plus, d'un dernier mot du runtime."""
    return _trailing_results(messages[:-1] if _closing_word(messages) else messages)


#: ce qu'un serveur MCP peut encore devenir (la CLI peut annoncer l'état avant la fin de la poignée de main)
REACHABLE = frozenset({"connected", "pending"})


def _unreachable(init: Mapping[str, Any], servers: Sequence[str]) -> str:
    """Les serveurs donnés à la CLI qu'elle n'a pas pu joindre, en mots (vide : tous
    joints). Sans liste d'états dans ``init`` (une CLI qui ne la donne pas), rien à dire."""
    listed = init.get("mcp_servers")
    if not servers or not isinstance(listed, list):
        return ""
    states = {str(s.get("name")): str(s.get("status") or "") for s in listed if isinstance(s, Mapping)}
    broken = [f"{name} : {states.get(name) or 'absent'}" for name in servers if states.get(name) not in REACHABLE]
    return ", ".join(broken)


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def _note_usage(run: _Run, message_id: str, u: Any) -> None:
    """Un relevé d'usage d'un message du modèle (son début, sa fin, chaque bloc) : on garde le plus haut de chaque
    compte — les relevés d'un même message ne se somment pas."""
    if not message_id or not isinstance(u, Mapping):
        return
    got, seen = _usage(u), run.usage.get(message_id, Usage())
    run.usage[message_id] = Usage(max(got.input_tokens, seen.input_tokens), max(got.output_tokens, seen.output_tokens),
                                  max(got.cache_read, seen.cache_read), max(got.cache_write, seen.cache_write))


def _unreported(run: _Run) -> tuple[Usage, int]:
    """L'usage des messages pas encore rendus, sommé (puis rendu), et la plus grande entrée d'un seul d'entre eux,
    cache compris (``LLMResponse.prompt_tokens``) : la CLI renvoie tout le contexte à chaque message, et c'est à un
    seul que l'estimation du budget se compare."""
    fresh = [u for m, u in run.usage.items() if m not in run.reported]
    run.reported.update(run.usage)
    return (Usage(sum(u.input_tokens for u in fresh), sum(u.output_tokens for u in fresh),
                  sum(u.cache_read for u in fresh), sum(u.cache_write for u in fresh)),
            max((u.input_tokens + u.cache_read + u.cache_write for u in fresh), default=0))


def _usage(u: Any) -> Usage:
    u = u if isinstance(u, Mapping) else {}

    def n(key: str) -> int:
        value = u.get(key, 0)
        return value if isinstance(value, int) else 0

    return Usage(input_tokens=n("input_tokens"), output_tokens=n("output_tokens"),
                 cache_read=n("cache_read_input_tokens"), cache_write=n("cache_creation_input_tokens"))
