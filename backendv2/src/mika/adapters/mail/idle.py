"""Le courrier en direct (ADR 0308) : ce qui arrive dans une boîte est rangé tout de suite dans le courrier relevé, de
jour comme de nuit — ce qu'elle en remarque garde son rythme à elle.

- **Une connexion IMAP IDLE par boîte qui le permet** (RFC 2177), sur sa réception (sans elle, son premier dossier
  relevé), à part du verrou de la boîte : à chaque réveil — un mail arrivé ou parti, des drapeaux —, la boîte est
  rangée (``ImapSmtpMail.range_box``, sur une session à elle, sous le verrou). Ses autres dossiers relevés suivent à ce
  moment-là, et au moins toutes les ``FOLDERS_EVERY_S`` ; les dossiers seulement synchronisés pour la console
  (« tous les dossiers », « tout garder en local ») restent à sa relève. L'attente se relance toutes les
  ``IDLE_FOR_S`` (``DONE`` puis ``IDLE``) : une connexion muette plus longtemps, un routeur ou un pare-feu l'oublie,
  et le courrier n'arriverait qu'à la reconnexion. La connexion se refait toutes les ``SESSION_FOR_S`` (avant les 29
  minutes de la RFC), avec un jeton frais pour une boîte Microsoft (ADR 0166) ; chaque connexion commence par ranger
  ce qui est arrivé pendant que personne n'écoutait. Un rangement en plusieurs passages (une nuit de courrier) les fait
  tous sur une même connexion, à part de celle qui attend.
- **Sans IDLE** (le serveur ne le sait pas, ou ce Python : avant 3.14), la boîte est rangée toutes les
  ``POLL_EVERY_S``.
- **Une panne** (serveur muet, accès refusé, boîte Microsoft à reconnecter) se note sur la boîte comme une relève
  manquée — la console et les écrans la montrent — et ne se journalise qu'à son changement ; on retente après un délai
  qui double (``RETRY_FIRST_S`` → ``RETRY_MAX_S``). Une boîte observée a une seule règle : sa panne est celle du
  direct (``ImapSmtpMail.observed``) ; sa relève et son historique n'en disent ni n'en effacent. Une connexion établie que le serveur coupe (une attente trop longue
  pour lui, un routeur) n'est pas une panne : elle se refait, de moins en moins vite si elle retombe sitôt faite.
- **Ce qu'elle remarque ne change pas** : ranger met chaque mail neuf en attente de son tri (``offer``), et ce qui est
  lu ailleurs reste à lui dire (``seen_elsewhere``) ; sa relève (``email.poll``, éveillée) le lui rend une fois. Rien
  ici ne la réveille, n'écrit à son journal ni ne la fait relever.
- **Les boîtes suivent leurs réglages** : une boîte ajoutée, retirée, coupée ou réglée autrement (son serveur, son
  accès, ses dossiers) voit son observateur naître, s'arrêter ou se refaire — à chaque enregistrement (``nudge``), au
  plus tard à la vérification suivante (``CHECK_EVERY_S``) ; un enregistrement retente aussi tout de suite une boîte en
  panne (une connexion Microsoft qui vient d'être faite).
- Ce qui bloque (se connecter, attendre) passe dans des fils à part, qui ne retiennent pas l'arrêt du serveur :
  arrêter coupe leurs connexions.
- Seul le serveur le démarre (``app/server.py``, depuis ``serve``) : ni une commande, ni la sonde, ni un test qui ne le
  demande.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from mika.adapters.mail.client import ImapSmtpMail
from mika.adapters.mail.config import MailAccount
from mika.adapters.mail.imap import ImapError, Session
from mika.adapters.mail.oauth import OAuthError

log = logging.getLogger("mika.mail")

#: une connexion d'attente se refait au bout de ce temps (s) : avant les 29 minutes de la RFC 2177, et avec un jeton
#: frais pour une boîte Microsoft
SESSION_FOR_S = 25 * 60.0
#: une attente se relance au bout de ce temps (s), sur la même connexion (``DONE`` puis ``IDLE``) : un routeur ou un
#: pare-feu oublie souvent une connexion muette au bout de dix à quinze minutes
IDLE_FOR_S = 8 * 60.0
#: une boîte qui relève plusieurs dossiers les range au moins à ce rythme (s) : on n'attend que sur l'un d'eux
FOLDERS_EVERY_S = 5 * 60.0
#: une boîte dont le serveur ne sait pas attendre est rangée à ce rythme (s)
POLL_EVERY_S = 60.0
#: après une panne, on retente au bout de ce délai (s), qui double jusqu'au suivant
RETRY_FIRST_S = 5.0
RETRY_MAX_S = 5 * 60.0
#: les réglages des boîtes se relisent au plus tard à ce rythme (s), même sans enregistrement qui le dise
CHECK_EVERY_S = 60.0
#: à l'arrêt, on attend au plus autant (s) que chaque observateur ait fini
STOP_WAIT_S = 5.0
#: un rangement se fait par passages (``LIVE_BATCH`` mails par dossier) : au plus autant d'affilée, le reste au réveil
#: suivant
PASSES_MAX = 200

#: ce que fait l'observateur d'une boîte (``MailWatch.modes``)
CONNECTING, WAITING, EVERY_MINUTE, FAILING, PAUSED = "connexion", "attente", "chaque minute", "panne", "pause"

#: ce qui dit qu'une boîte ne se joint pas (comme pour sa relève)
FAILURES = (OSError, ImapError, OAuthError, ValueError, EOFError)

T = TypeVar("T")


def retry_after(previous: float) -> float:
    """Le délai avant de retenter, après ``previous`` (0 : une première panne) : il double, de quelques secondes à
    quelques minutes."""
    return RETRY_FIRST_S if previous <= 0 else min(RETRY_MAX_S, previous * 2)


def watched_folder(account: MailAccount) -> str:
    """Le dossier où l'on attend : la réception si elle est relevée, sinon le premier dossier relevé."""
    return "INBOX" if "INBOX" in account.folders else account.folders[0]


def _how(account: MailAccount) -> tuple[Any, ...]:
    """Ce qui, changé, refait l'observateur d'une boîte : où et comment on y entre, ce qu'on y relève."""
    return (account.imap_host, account.imap_port, account.imap_ssl, account.user, account.password, account.auth,
            account.oauth_client_id, account.oauth_tenant, account.folders)


async def _aside(fn: Callable[[], T], discard: Callable[[T], Any] | None = None) -> T:
    """``fn`` dans un fil à part (un démon : il ne retient pas l'arrêt du serveur). Si l'attente est annulée
    entre-temps, ce qu'il rend passe à ``discard`` (une connexion ouverte pour rien se referme)."""
    loop = asyncio.get_running_loop()
    done: asyncio.Future[T] = loop.create_future()

    def settle(result: Any, error: BaseException | None) -> None:
        if done.cancelled():
            if error is None and discard is not None:
                threading.Thread(target=discard, args=(result,), daemon=True).start()
        elif error is not None:
            done.set_exception(error)
        else:
            done.set_result(result)

    def run() -> None:
        result: Any = None
        error: BaseException | None = None
        try:
            result = fn()
        except BaseException as exc:  # tout repasse à la boucle, qui le lève là où on l'attend
            error = exc
        try:
            loop.call_soon_threadsafe(settle, result, error)
        except RuntimeError:  # la boucle est fermée : plus personne n'attend
            if error is None and discard is not None:
                discard(result)

    threading.Thread(target=run, name="mika-courrier-direct", daemon=True).start()
    return await done


class _Lost(Exception):
    """Une connexion établie que le serveur a coupée pendant l'attente : elle se refait, ce n'est pas une panne."""


@dataclass
class _Box:
    """L'observateur d'une boîte : sa tâche, sa connexion d'attente, où il en est."""

    key: str
    account: MailAccount
    task: asyncio.Task[None] | None = None
    session: Session | None = None
    mode: str = CONNECTING
    #: le délai après une panne (0 : aucune depuis le dernier rangement réussi)
    delay: float = 0.0
    #: le délai après une connexion coupée
    pause: float = 0.0

    def drop(self) -> None:
        """Ferme sa connexion d'attente sans l'attendre : une attente en cours finit aussitôt."""
        session, self.session = self.session, None
        if session is not None:
            session.interrupt()
            threading.Thread(target=session.close, daemon=True).start()

    def end(self) -> None:
        if self.task is not None:
            self.task.cancel()
        self.drop()


class MailWatch:
    """Le courrier en direct : un observateur par boîte prête (``ImapSmtpMail.watched``), réglé sur ses réglages.

    ``sleep`` et ``clock`` (secondes, monotone) sont ceux du vrai temps ; un test donne les siens, et ses durées."""

    def __init__(self, mail: ImapSmtpMail, *, sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
                 clock: Callable[[], float] = time.monotonic, session_for: float = SESSION_FOR_S,
                 idle_for: float = IDLE_FOR_S, folders_every: float = FOLDERS_EVERY_S,
                 poll_every: float = POLL_EVERY_S, check_every: float = CHECK_EVERY_S) -> None:
        self._mail = mail
        self._sleep = sleep
        self._clock = clock
        self._session_for = session_for
        self._idle_for = idle_for
        self._folders_every = folders_every
        self._poll_every = poll_every
        self._check_every = check_every
        self._boxes: dict[str, _Box] = {}
        self._supervisor: asyncio.Task[None] | None = None
        self._nudged = asyncio.Event()
        self._retry = False
        #: par boîte, la panne déjà dite : la même, répétée, ne se redit pas
        self._said: dict[str, str] = {}

    # ── le cycle de vie ──
    def start(self) -> None:
        """Démarre (dans la boucle du serveur) : les boîtes prêtes ont leur observateur tout de suite."""
        if self._supervisor is None:
            self._supervisor = asyncio.get_running_loop().create_task(self._supervise(), name="courrier-direct")

    def nudge(self) -> None:
        """Les réglages des boîtes viennent d'être enregistrés : on s'y règle tout de suite, et une boîte en panne se
        retente (appelé dans la boucle du serveur)."""
        self._retry = True
        self._nudged.set()

    async def stop(self) -> None:
        """Arrête chaque observateur et ferme ses connexions ; rend la main au plus tard après ``STOP_WAIT_S``."""
        tasks = [t for t in (self._supervisor, *(b.task for b in self._boxes.values())) if t is not None]
        self._supervisor = None
        for box in self._boxes.values():
            box.end()
        self._boxes.clear()
        self._mail.observed = frozenset()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=STOP_WAIT_S)

    def modes(self) -> dict[str, str]:
        """Ce que fait l'observateur de chaque boîte : il se connecte, il attend, il relève chaque minute, il est en
        panne ou en pause (une connexion coupée qui se refait)."""
        return {key: box.mode for key, box in sorted(self._boxes.items())}

    def reconcile(self, *, retry: bool = False) -> None:
        """Un observateur par boîte prête, tel qu'elle est réglée à l'instant : celui d'une boîte retirée, coupée ou
        réglée autrement s'arrête (et se refait pour la nouvelle), celui d'une boîte nouvelle naît, celui qu'un défaut a
        arrêté repart ; ``retry`` refait aussi celui d'une boîte en panne."""
        wanted = self._mail.watched()
        for key, box in list(self._boxes.items()):
            account = wanted.get(key)
            stopped = box.task is not None and box.task.done()
            if account is None or _how(account) != _how(box.account) or stopped or (retry and box.mode == FAILING):
                del self._boxes[key]
                box.end()
                if account is None:
                    self._said.pop(key, None)
        loop = asyncio.get_running_loop()
        for key, account in wanted.items():
            if key not in self._boxes:
                box = self._boxes[key] = _Box(key, account)
                box.task = loop.create_task(self._watch(box), name=f"courrier-direct:{key}")
        self._mail.observed = frozenset(self._boxes)

    async def _supervise(self) -> None:
        while True:
            retry, self._retry = self._retry, False
            self._nudged.clear()
            try:
                self.reconcile(retry=retry)
            except Exception:  # des réglages illisibles un instant : on se règle à la vérification suivante
                log.exception("courrier en direct : les réglages des boîtes n'ont pas pu être relus")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._nudged.wait(), self._check_every)

    # ── une boîte ──
    async def _watch(self, box: _Box) -> None:
        try:
            await self._watch_loop(box)
        except Exception:  # un défaut ici n'emporte pas les autres boîtes : celle-ci se refait à la vérification suivante
            log.exception("courrier en direct : l'observateur de %s s'est arrêté", box.key)

    async def _watch_loop(self, box: _Box) -> None:
        try:
            while True:
                started = self._clock()
                try:
                    if await self._listen(box):  # son serveur ne sait pas attendre
                        await self._every_minute(box)
                    wait = 0.0
                except _Lost as lost:
                    # une connexion qui a tenu se refait vite ; une qui retombe sitôt faite, de moins en moins vite
                    box.pause = RETRY_FIRST_S if self._clock() - started >= RETRY_MAX_S else retry_after(box.pause)
                    box.mode, wait = PAUSED, box.pause
                    log.debug("courrier en direct : connexion de %s coupée (%s)", box.key, type(lost.__cause__).__name__)
                except FAILURES as exc:
                    self._failed(box, exc)
                    wait = box.delay
                finally:
                    box.drop()
                if wait:
                    await self._sleep(wait)
        finally:
            box.drop()

    async def _listen(self, box: _Box) -> bool:
        """Une connexion d'attente : se connecter, ouvrir le dossier, ranger ce qui est arrivé ; puis attendre, et
        ranger à chaque réveil, jusqu'à ``session_for``. Rend vrai si son serveur ne sait pas attendre."""
        box.mode = CONNECTING
        account = box.account
        token = await self._mail.watch_token(box.key, account)

        def connect() -> Session:
            session = self._mail.watch_session(account, token)
            try:
                if not session.can_wait:  # certains ne le disent qu'à qui est entré
                    session.recheck()
                if session.can_wait:
                    session.select(watched_folder(account))
            except BaseException:
                session.close()
                raise
            return session

        session = box.session = await _aside(connect, discard=Session.close)
        if not session.can_wait:
            box.drop()
            return True
        await self._range(box)  # ce qui est arrivé pendant que personne n'écoutait
        box.mode = WAITING
        until = self._clock() + self._session_for
        several = len(account.folders) > 1
        due = self._clock() + self._folders_every
        while (left := until - self._clock()) > 0:
            span = min(left, self._idle_for, max(0.0, due - self._clock())) if several else min(left, self._idle_for)
            try:
                woke = await _aside(functools.partial(session.wait, span))
            except FAILURES as exc:
                raise _Lost from exc
            if woke or (several and self._clock() >= due):
                await self._range(box)
                due = self._clock() + self._folders_every
        return False

    async def _every_minute(self, box: _Box) -> None:
        """Son serveur ne sait pas attendre : la boîte est rangée à chaque ``poll_every`` ; une panne espace les
        essais (jamais moins que ce rythme)."""
        box.mode = EVERY_MINUTE
        while True:
            try:
                await self._range(box)
                box.mode, wait = EVERY_MINUTE, self._poll_every
            except FAILURES as exc:
                self._failed(box, exc)
                wait = max(box.delay, self._poll_every)
            await self._sleep(wait)

    async def _range(self, box: _Box) -> None:
        """Range la boîte, par passages (le verrou de la boîte rendu entre deux), jusqu'à ce que tout ce qui est arrivé
        soit là ; un rangement réussi clôt une panne. Le premier passage ouvre sa connexion ; s'il en faut d'autres,
        ils partagent une seule connexion, refermée à la fin — pas une par passage."""
        session: Session | None = None
        try:
            for n in range(PASSES_MAX):
                if n == 1:
                    token = await self._mail.watch_token(box.key, box.account)
                    session = await _aside(functools.partial(self._mail.watch_session, box.account, token),
                                           discard=Session.close)
                if await self._mail.range_box(box.key, session=session):
                    break
        finally:
            if session is not None:
                threading.Thread(target=session.close, daemon=True).start()
        box.delay = 0.0
        if self._said.pop(box.key, None) is not None:
            log.info("courrier en direct : %s de nouveau joignable", box.key)

    def _failed(self, box: _Box, exc: BaseException) -> None:
        box.delay = retry_after(box.delay)
        box.mode = FAILING
        why = self._mail.watch_failed(box.key, exc)
        if self._said.get(box.key) != why:  # une panne répétée ne se redit pas ; une autre, si
            self._said[box.key] = why
            log.warning("courrier en direct : %s injoignable (%s) ; nouvel essai dans %d s", box.key,
                        type(exc).__name__, box.delay)
