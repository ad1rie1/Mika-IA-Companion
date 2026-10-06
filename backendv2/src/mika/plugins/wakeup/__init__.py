"""Le plugin ``wakeup`` : les réveils par API (ADR 0068).

Un opérateur déclare des réveils (Configuration › Plugins › Réveils par API) ; un système extérieur appelle l'un
d'eux (``POST /api/wake/<nom>``, avec sa clé) et lui apporte un texte. Rien ici ne parle au réseau : la porte HTTP
vérifie la clé et les plafonds, puis journalise ``wakeup.called`` — le réglage du réveil figé à cet instant.

Ce que le plugin en fait :

- *Le travail* : sans projet, un épisode à lui — ``WAKE`` dans son mode à elle, ``WAKE_JOB`` en impersonnel —,
  cible ``task:wakeup:<seq>``, avec les outils du réveil ; sur un projet, une exécution de ce projet (``WORK`` ou
  ``JOB``) que le plugin propose lui-même (``prompt``). Le texte de l'appel est cité, jamais obéi ; les consignes
  de l'opérateur priment. Il se conclut par ``report_wake`` (ou ``report_run`` sur un projet).
- *Le sommeil* : un réveil qui passe outre son rythme passe la barre de réveil (et le corps la tire du sommeil,
  ``body``) ; sinon, il attend qu'elle soit réveillée.
- *Le compte rendu* : à qui le réveil le dit (sa propriétaire, un compte, personne), par une initiative due.
- *L'expiration* : un appel resté en attente au-delà de sa durée de vie n'est plus traité ; une panne est réessayée
  quelques fois, puis l'appel est dit échoué.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mika.contracts import agency as agency_c
from mika.contracts import projects as projects_c
from mika.contracts import runtime as rt
from mika.contracts import wakeup as c
from mika.kernel.clock import DAY, HOUR, MINUTE, US
from mika.kernel.events import Content, Payload
from mika.kernel.faculty import Faculty, ToolResult
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, Superseded
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import PROJECT_KINDS, WAKE_KINDS, Kind
from mika.vocab.privacy import Sensitivity

#: l'état d'un appel
WAITING, RUNNING, DONE, IMPOSSIBLE, UNFINISHED, FAILED, EXPIRED, CANCELLED = (
    "attend", "en_cours", "fait", "impossible", "pas_fini", "echoue", "expire", "annule")
#: ce qui a été traité (bien ou mal)
FINISHED = frozenset({DONE, IMPOSSIBLE, UNFINISHED, FAILED})
#: ce qui se dit à qui le réveil rend compte : ce qui a été traité, et ce qui a expiré sans l'être (une annulation
#: vient de l'opérateur, qui le sait)
TELLABLE = FINISHED | {EXPIRED}
#: ce qui ne sera plus traité
CLOSED = FINISHED | {EXPIRED, CANCELLED}
#: ce qu'un compte rendu peut dire de l'appel (``report_wake``)
OUTCOMES = (DONE, IMPOSSIBLE, UNFINISHED)
#: les fins d'un épisode qui ne disent rien de l'appel : il n'a pas eu lieu, il repart en attente (un instant après)
REQUEUE = frozenset({"superseded", "preempted", "cancelled"})
#: …celles d'une panne (ou d'un arrêt) : un essai de plus, de plus en plus espacé
BROKEN = frozenset({"failed", "timeout", "interrupted"})
#: la fin d'un épisode à court de tours d'outils (``runtime/pipeline``) : elle a travaillé sans conclure — pas une panne,
#: rien à rejouer
OUT_OF_TURNS = "au bout des outils"
#: l'attente avant de repartir : après une fin sans suite, puis après la n-ième panne (doublée à chaque fois)
REQUEUE_SPACING = 30 * US
RETRY_SPACING = 2 * MINUTE
#: au-delà de tant de départs (supplantés compris), l'appel est dit échoué : jamais une boucle sans fin
MAX_STARTS = 12
#: ce qu'on garde d'appels (les plus anciens appels clos s'effacent d'abord)
CALLS_KEPT = 200
#: un compte rendu dit au plus tant de fois sans succès, espacées
TELL_SPACING = 30 * MINUTE
#: le sujet de l'initiative qui dit des comptes rendus : ``wakeup:dire:<seq>,<seq>``
TELL_PREFIX = f"{c.PREFIX}dire:"
REPORT = "report_wake"
#: ce qu'un compte rendu garde au plus (ce que la section qui le dit montre en entier)
SUMMARY_MAX = 1200


class WakeupParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_tries: Annotated[int, Knob(
        label="Essais avant l'échec", group="Traiter", lo=1, hi=10,
        help="Une panne (le modèle qui ne répond pas, un arrêt du serveur) fait réessayer l'appel ; au-delà, il est "
             "dit échoué — et dit à qui le réveil rend compte.")] = 3
    tell_tries: Annotated[int, Knob(
        label="Essais pour le dire", group="Rendre compte", lo=1, hi=10,
        help="Combien de fois elle essaie de dire un compte rendu (un silence, une panne comptent), espacés d'une "
             "demi-heure.")] = 3
    too_late_us: Annotated[int, Knob(
        label="Plus la peine de le dire après", group="Rendre compte", lo=HOUR, hi=7 * DAY,
        help="Un compte rendu resté sans occasion d'être dit (personne de joignable) n'est plus annoncé passé ce "
             "délai ; il reste dans la console.")] = 12 * HOUR


def params(p: WakeupParams | None) -> WakeupParams:
    return p if p is not None else WakeupParams()


def params_of(frame: Frame) -> WakeupParams:
    return params(frame.env.params_of(c.OWNER, frame.root))


class Reported(Payload):
    """Ce qu'un réveil a donné, dit par elle-même (``report_wake``)."""

    call: int
    outcome: str
    summary: Content
    about: tuple[str, ...] = ()


class Expired(Payload):
    call: int
    #: pourquoi (vide : sa durée de vie est passée)
    reason: str = ""


class Cancelled(Payload):
    call: int
    by: str = ""


@dataclass(frozen=True, slots=True)
class Call:
    """Un appel, de sa réception à ce qu'elle en a dit."""

    seq: int
    endpoint: str
    at: int
    label: str = ""
    text_ref: str = ""
    instructions_ref: str = ""
    plain: bool = False
    project: int = 0
    bundles: tuple[str, ...] = ()
    rouse: bool = False
    notify: str = c.NOBODY
    expires_at: int = 0
    about: tuple[str, ...] = ()
    status: str = WAITING
    #: l'épisode qui le traite (ou l'a traité en dernier)
    episode: str = ""
    started_at: int = 0
    starts: int = 0
    tries: int = 0
    #: pas avant (après une panne, ou une fin sans suite)
    retry_at: int = 0
    done_at: int = 0
    report_ref: str = ""
    #: ce qu'il faudrait de qui a confié le projet (``report_run``)
    need_ref: str = ""
    told: bool = False
    told_at: int = 0
    tell_tries: int = 0
    tell_after: int = 0
    by: str = ""
    #: pourquoi il a expiré (vide : sa durée de vie)
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Telling:
    """Une initiative qui dit des comptes rendus : lesquels, et depuis quand."""

    calls: tuple[int, ...]
    started: int
    target: str = ""


@dataclass(frozen=True, slots=True)
class WakeupState:
    calls: FrozenDict[int, Call] = field(default_factory=FrozenDict)
    telling: FrozenDict[str, Telling] = field(default_factory=FrozenDict)


WAKEUP = Faculty("wakeup", state=WakeupState, init=lambda p: WakeupState(), params=WakeupParams)
WAKEUP.declare(*c.ALL)
REPORTED = WAKEUP.event("reported", Reported, content=("summary",), subjects=("about",))
EXPIRED_EVENT = WAKEUP.event("expired", Expired)
CANCELLED_EVENT = WAKEUP.event("cancelled", Cancelled)


def tell_subject(calls: tuple[int, ...]) -> str:
    return TELL_PREFIX + ",".join(str(n) for n in calls)


def told_calls(subject: str | None) -> tuple[int, ...]:
    """Les appels qu'une initiative de compte rendu dit (son sujet), sinon ``()``."""
    if not subject or not subject.startswith(TELL_PREFIX):
        return ()
    return tuple(int(x) for x in subject[len(TELL_PREFIX):].split(",") if x.isdigit())


def _keep(calls: FrozenDict[int, Call]) -> FrozenDict[int, Call]:
    """Au-delà de ``CALLS_KEPT``, les plus anciens appels clos s'effacent (jamais un appel à traiter)."""
    while len(calls) > CALLS_KEPT:
        closed = [n for n, call in calls.items() if call.status in CLOSED]
        if not closed:
            break
        calls = calls.delete(min(closed))
    return calls


def _set(s: WakeupState, call: Call) -> WakeupState:
    return replace(s, calls=s.calls.set(call.seq, call))


@WAKEUP.reducer(c.CALLED)
def _called(s: WakeupState, e: Any, cx: Any) -> WakeupState:
    d = e.data
    instructions = (d.instructions.ref or "") if d.instructions is not None else ""
    call = Call(seq=e.seq, endpoint=d.endpoint, at=e.at, label=d.label, text_ref=d.text.ref or "",
                instructions_ref=instructions, plain=d.plain,
                project=d.project, bundles=tuple(d.bundles), rouse=d.rouse, notify=d.notify,
                expires_at=d.expires_at, about=tuple(d.about))
    return replace(s, calls=_keep(s.calls.set(e.seq, call)))


def _of_episode(s: WakeupState, correlation: str) -> Call | None:
    return next((x for x in s.calls.values() if x.status == RUNNING and x.episode == correlation), None)


@WAKEUP.reducer(rt.EPISODE_STARTED)
def _started(s: WakeupState, e: Any, cx: Any) -> WakeupState:
    d = e.data
    told = told_calls(d.subject)
    if d.kind == Kind.INITIATIVE and told:
        return replace(s, telling=s.telling.set(e.correlation, Telling(told, e.at, d.target or "")))
    n = c.call_of(d.subject)
    call = s.calls.get(n) if n is not None else None
    if call is None or call.status != WAITING or d.kind not in WAKE_KINDS | PROJECT_KINDS:
        return s
    return _set(s, replace(call, status=RUNNING, episode=e.correlation, started_at=e.at, starts=call.starts + 1))


def _finished(call: Call, status: str, at: int, *, report_ref: str = "", need_ref: str = "") -> Call:
    return replace(call, status=status, done_at=at, report_ref=report_ref or call.report_ref,
                   need_ref=need_ref or call.need_ref)


@WAKEUP.reducer(REPORTED)
def _reported(s: WakeupState, e: Any, cx: Any) -> WakeupState:
    d = e.data
    call = s.calls.get(d.call)
    if call is None or call.status != RUNNING:
        return s
    status = d.outcome if d.outcome in OUTCOMES else UNFINISHED
    return _set(s, _finished(call, status, e.at, report_ref=d.summary.ref or ""))


#: le verdict d'une exécution de projet, dit comme l'issue d'un réveil
VERDICTS = {projects_c.DONE: DONE, projects_c.BLOCKED: IMPOSSIBLE}


@WAKEUP.reducer(projects_c.RUN_REPORTED)
def _run_reported(s: WakeupState, e: Any, cx: Any) -> WakeupState:
    """Une exécution de projet qu'un réveil a lancée s'est conclue : son verdict est l'issue de l'appel."""
    call = _of_episode(s, e.correlation)
    if call is None:
        return s
    d = e.data
    need = d.need.ref if d.need is not None and d.need.ref else ""
    return _set(s, _finished(call, VERDICTS.get(d.verdict, UNFINISHED), e.at, report_ref=d.summary.ref or "",
                             need_ref=need))


@WAKEUP.reducer(rt.EPISODE_ENDED, reads=[agency_c.RENOUNCED])
def _ended(s: WakeupState, e: Any, cx: Any) -> WakeupState:
    telling = s.telling.get(e.correlation)
    if telling is not None:
        s = replace(s, telling=s.telling.delete(e.correlation))
        renounced = cx.facts.get(agency_c.RENOUNCED(telling.target)) if telling.target else 0
        if not agency_c.tried(e.data.outcome, telling.started, renounced):
            return s
        for n in telling.calls:  # un essai de plus pour chacun de ceux qui restent à dire
            call = s.calls.get(n)
            if call is not None and not call.told:
                s = _set(s, replace(call, tell_tries=call.tell_tries + 1, tell_after=e.at + TELL_SPACING))
        return s
    call = _of_episode(s, e.correlation)
    if call is None:
        return s
    outcome = e.data.outcome
    p = params(cx.params)
    if outcome in BROKEN and OUT_OF_TURNS in (e.data.detail or ""):
        return _set(s, _finished(call, UNFINISHED, e.at))  # à court de tours : elle a travaillé, sans conclure
    if outcome in REQUEUE or outcome in BROKEN:
        broke = outcome in BROKEN
        tries = call.tries + (1 if broke else 0)
        if tries >= p.max_tries or call.starts >= MAX_STARTS:
            return _set(s, replace(_finished(call, FAILED, e.at), tries=tries))
        wait = RETRY_SPACING * 2 ** (tries - 1) if broke else REQUEUE_SPACING
        return _set(s, replace(call, status=WAITING, tries=tries, retry_at=e.at + wait))
    # le modèle a travaillé sans conclure (ou s'est tu) : c'est dit tel quel
    return _set(s, _finished(call, UNFINISHED, e.at))


@WAKEUP.reducer(EXPIRED_EVENT)
def _expired(s: WakeupState, e: Any, cx: Any) -> WakeupState:
    call = s.calls.get(e.data.call)
    if call is None or call.status != WAITING:
        return s
    return _set(s, replace(call, status=EXPIRED, done_at=e.at, reason=e.data.reason))


@WAKEUP.reducer(CANCELLED_EVENT)
def _cancelled(s: WakeupState, e: Any, cx: Any) -> WakeupState:
    call = s.calls.get(e.data.call)
    if call is None or call.status not in (WAITING, RUNNING):
        return s
    return _set(s, replace(call, status=CANCELLED, done_at=e.at, by=e.data.by))


@WAKEUP.reducer(rt.UTTERANCE)
def _uttered(s: WakeupState, e: Any, cx: Any) -> WakeupState:
    """Ce que son prompt lui montrait d'un compte rendu (``wakeup:<seq>``) quand elle a parlé : c'est dit."""
    d = e.data
    if not d.visible:
        return s
    for p in d.provenance:
        n = c.call_of(p)
        call = s.calls.get(n) if n is not None else None
        if call is not None and call.status in TELLABLE and not call.told:
            s = _set(s, replace(call, told=True, told_at=e.at))
    return s


# ── Faits ─────────────────────────────────────────────────────────────────


def untold(call: Call) -> bool:
    return call.status in TELLABLE and call.notify != c.NOBODY and not call.told


@WAKEUP.fact(c.STATUS)
def _status(s: WakeupState, cx: Any, call: int) -> str:
    got = s.calls.get(call)
    return got.status if got is not None else ""


@WAKEUP.fact(c.UNTOLD)
def _untold(s: WakeupState, cx: Any, call: int) -> bool:
    got = s.calls.get(call)
    return got is not None and untold(got)


@WAKEUP.fact(c.PENDING)
def _pending(s: WakeupState, cx: Any, endpoint: str) -> int:
    return sum(1 for x in s.calls.values() if x.endpoint == endpoint and x.status in (WAITING, RUNNING))


def live(n: int) -> Guard:
    """Un épisode qui traite cet appel ne vaut que tant qu'il n'est ni expiré ni annulé : son propre compte rendu ne
    le fait pas tomber."""
    return Guard("réveil", predicate=lambda view, n=n: view.get(c.STATUS(n)) not in ("", EXPIRED, CANCELLED))


def current(ctx: Any) -> Call | None:
    """L'appel que traite l'épisode de cet outil (en cours), sinon ``None``."""
    ep = ctx.frame.episode
    n = c.call_of(ep.attrs.get("subject")) if ep is not None else None
    s: WakeupState = ctx.frame.state(c.OWNER)
    call = s.calls.get(n) if n is not None else None
    return call if call is not None and call.status == RUNNING else None


# ── L'expiration ──────────────────────────────────────────────────────────


def _still_waiting(n: int) -> Guard:
    return Guard("appel en attente", predicate=lambda view, n=n: view.get(c.STATUS(n)) == WAITING)


#: son projet n'existe plus pour lui (archivé) : il ne sera jamais traité
PROJECT_GONE = "son projet a été archivé"


def _orphan(call: Call, frame: Any) -> bool:
    """Un appel sur un projet archivé (ou inconnu) : il ne partira jamais — il n'attend pas sa fin de vie, ni ne
    retient ceux de son réveil qui le suivent."""
    return bool(call.project) and frame.get(projects_c.STATUS(call.project)) in ("", projects_c.ARCHIVED)


@WAKEUP.process("wakeup.expire", wake_on=[c.CALLED, EXPIRED_EVENT, CANCELLED_EVENT, rt.EPISODE_STARTED,
                                         rt.EPISODE_ENDED, "projects.archived"],
                lane="background", max_quantum_s=60, priority=60, reads=[projects_c.STATUS])
class Expire:
    """Un appel resté en attente au-delà de sa durée de vie n'est plus traité (un appel en cours, si) ; un appel
    dont le projet a été archivé non plus, tout de suite."""

    def next_due(self, s: WakeupState, frame: Any, last_run: int | None) -> int | None:
        waiting = [x for x in s.calls.values() if x.status == WAITING]
        if any(_orphan(x, frame) for x in waiting):
            return frame.now
        due = [x.expires_at for x in waiting if x.expires_at]
        return max(frame.now, min(due)) if due else None

    async def run(self, ctx: Any) -> None:
        now = ctx.frame.now
        for x in [x for x in ctx.state.calls.values() if x.status == WAITING]:
            if _orphan(x, ctx.frame):
                reason = PROJECT_GONE
            elif x.expires_at and x.expires_at <= now:
                reason = ""
            else:
                continue
            try:
                await ctx.emit(EXPIRED_EVENT.draft(call=x.seq, reason=reason, dedupe_key=f"reveil-expire:{x.seq}"),
                               guard=_still_waiting(x.seq))
            except Superseded:  # parti entre-temps : il sera traité
                continue


# ── L'outil qui conclut ───────────────────────────────────────────────────


class ReportArgs(BaseModel):
    outcome: Literal["fait", "impossible", "pas_fini"] = Field(
        description="fait : c'est fait ; impossible : tu ne peux pas le faire (consignes, limites, outils) ; "
                    "pas_fini : tu n'as pas pu aller au bout")
    summary: str = Field(min_length=1, max_length=SUMMARY_MAX,
                         description="ce que tu as fait ou trouvé, pour qui lira ce compte rendu")


WAKEUP.bundle("wakeup", "conclure un réveil par API : le compte rendu de ce que l'appel t'a fait faire")


@WAKEUP.tool(REPORT, description="Conclure ce réveil par API : ce que tu en as fait (« fait », « impossible » ou "
             "« pas_fini ») et un compte rendu pour qui le lira. C'est la fin du réveil.",
             args=ReportArgs, bundle="wakeup", episodes=sorted(WAKE_KINDS), max_calls_per_episode=2, ends_loop=True)
async def report_wake(args: ReportArgs, ctx: Any) -> Any:
    call = current(ctx)
    if call is None:
        return ToolResult(ok=False, content="Ce réveil n'est plus en cours (expiré ou annulé).")
    if any(name == REPORT and ok for name, ok in ctx.calls):
        return ToolResult(ok=False, content="Tu as déjà conclu ce réveil : arrête-toi là.")
    summary = args.summary.strip()
    await ctx.emit(REPORTED.draft(call=call.seq, outcome=args.outcome,
                                  summary=Content.of(summary, level=int(Sensitivity.PERSONAL)), about=call.about))
    if call.notify == c.NOBODY:
        return "C'est noté : ton compte rendu reste dans la console."
    return "C'est noté : tu le diras à qui ce réveil rend compte."


# ses contributions : son prompt et ses candidats, sa console
from mika.plugins.wakeup import console as console  # noqa: E402
from mika.plugins.wakeup import prompt as prompt  # noqa: E402
