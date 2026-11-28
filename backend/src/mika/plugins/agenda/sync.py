"""La synchronisation des agendas branchés (ADR 0309), ``agenda.sync`` : chaque compte d'un fournisseur se relit à la
cadence de sa sorte, dans la fenêtre (90 jours derrière, un an devant), depuis le curseur de chaque agenda suivi.

- **Les comptes** sont ceux des réglages (``agenda_providers.connections``) : chacun est rangé dans la base tel qu'ils
  le disent (``keep_account`` : sa sorte, à qui il est, son adresse, s'il est actif) ; un compte retiré des réglages
  emporte sa copie (``drop_account``). Le système n'a rien à relire : ses événements font foi dans la base.
- **Un passage** : ses agendas, tels que le fournisseur les liste (``keep_calendars`` : ceux qui n'y sont plus partent
  avec leurs événements), puis chaque agenda suivi (``ports.agenda.follows``) depuis son curseur, page après page
  (``SyncBatch.more``) ; un agenda qu'on ne suit plus perd sa copie. La synchronisation faite, ou manquée — l'erreur
  en mots, ses échecs comptés — se range sur le compte (``synced``) : la santé et la fiche du compte la lisent.
- **Quand** : un compte dû (``due_at`` : sa cadence après sa dernière synchronisation ; après une panne, le recul,
  doublé à chaque échec, borné) ; au plus ``per_run`` comptes par passage, les plus en retard d'abord. Le passage
  suivant est l'échéance la plus proche. Une sorte sans fournisseur (pas encore branché) attend. « Synchroniser
  maintenant » (``agenda.sync_asked``, lot 4) réveille le processus et rend dû, tout de suite, le compte demandé (ou
  tous) s'il n'a pas été relu depuis la demande.
- **L'erreur en mots** : celle d'un fournisseur (``AgendaError`` : « identifiant ou mot de passe refusé par … »,
  « le serveur CalDAV est injoignable (…) », « l'abonnement pèse plus de 10 Mo… ») telle qu'il la dit ; une autre,
  par ``describe_error``.
- **Après une écriture** chez un fournisseur (réussie, ou refusée : un conflit, un événement disparu), la copie de
  l'agenda se relit tout de suite (``reread``) : ce que l'écriture a rendu se range d'abord, avec ce que Mika y a mis,
  puis l'agenda se relit depuis son curseur. Le système n'a rien à relire.
- **Son historique** (lot 5, ``note_sync`` : l'onglet Synchronisation de la fiche d'un agenda) : une relecture qui a
  changé quelque chose (entière quand l'agenda n'avait pas de curseur), la copie relue après une écriture, un agenda
  qu'on ne suit plus, une panne — la première, ou une autre erreur que la précédente — et sa reprise ; ce qui n'a rien
  changé n'y est pas, ni un titre ni une adresse. Il garde ``history_us`` (30 jours).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from mika.kernel.clock import HOUR
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.plugins.agenda import AGENDA, SYNC_ASKED, AgendaParams, AgendaState, cadence, params_of
from mika.ports.agenda import (
    SYNC_DROPPED,
    SYNC_FAILED,
    SYNC_FULL,
    SYNC_READ,
    SYNC_RECOVERED,
    SYNC_WRITTEN,
    SYSTEM,
    AccountState,
    AgendaError,
    AgendaPort,
    AgendaProviders,
    Calendar,
    CalendarProvider,
    Connection,
    Event,
    SyncNote,
    Window,
    follows,
    sync_window,
    system_person,
)
from mika.ports.errors import describe_error

#: au plus tant de pages d'un même agenda par passage (le reste au suivant, depuis son curseur)
PAGES_MAX = 20
#: sans compte branché à relire : repasser à ce rythme (un compte ajouté se voit au plus tard alors)
IDLE_EVERY = HOUR


def due_at(state: AccountState | None, kind: str, p: AgendaParams, asked: int = 0) -> int:
    """Quand ce compte est dû : jamais essayé, ou demandé (``asked``) depuis son dernier essai, tout de suite (0) ;
    après une panne, son dernier essai plus le recul (``retry_us`` doublé à chaque échec de suite, au plus
    ``retry_max_us``) ; sinon sa dernière synchronisation plus la cadence de sa sorte."""
    if state is None or not state.tried_at or asked > state.tried_at:
        return 0
    if state.failures:
        return state.tried_at + min(p.retry_max_us, p.retry_us * 2 ** min(state.failures - 1, 30))
    return max(state.synced_at, state.tried_at) + cadence(p, kind)


def failure_words(exc: BaseException) -> str:
    """Une panne de synchronisation en mots : celle d'un fournisseur telle qu'il la dit, une autre traduite."""
    return str(exc) if isinstance(exc, AgendaError) and str(exc) else describe_error(exc)


async def sync_calendar(store: AgendaPort, provider: CalendarProvider, account: Connection, calendar: Calendar,
                        window: Window) -> int:
    """Un agenda relu depuis son curseur, page après page (au plus ``PAGES_MAX``) ; rend combien d'événements la base
    a rangés ou retirés."""
    cursor, changed = calendar.cursor, 0
    for _ in range(PAGES_MAX):
        batch = await provider.sync(account, calendar, cursor, window)
        changed += store.apply(calendar.key, batch, window=window)
        cursor = batch.cursor
        if not batch.more:
            break
    return changed


def _noted(store: AgendaPort, p: AgendaParams, account: str, calendar: str, what: str, now: int, changed: int = 0,
           detail: str = "") -> None:
    """Une ligne de l'historique de la synchro ; une panne de l'historique ne défait jamais la synchro."""
    try:
        store.note_sync(SyncNote(account, calendar, now, what, changed, detail), keep_us=p.history_us)
    except Exception:  # noqa: BLE001 — l'historique est un surcroît : la synchronisation, elle, est faite
        return


async def sync_account(store: AgendaPort, provider: CalendarProvider, account: Connection, p: AgendaParams,
                       now: int) -> AccountState:
    """Un compte relu : ses agendas, puis chaque agenda suivi depuis son curseur ; ce qui en sort se range sur lui."""
    window = sync_window(now, p.past_us, p.ahead_us)
    before = store.account(account.key)
    try:
        for calendar in store.keep_calendars(account.key, await provider.calendars(account)):
            if not follows(account, calendar):
                if calendar.synced_at:  # on ne le suit plus : sa copie part
                    gone = store.clear_calendar(calendar.key)
                    _noted(store, p, account.key, calendar.key, SYNC_DROPPED, now, gone)
                continue
            changed = await sync_calendar(store, provider, account, calendar, window)
            if changed:
                _noted(store, p, account.key, calendar.key, SYNC_READ if calendar.cursor else SYNC_FULL, now, changed)
    except Exception as exc:  # noqa: BLE001 — un fournisseur en panne, quelle qu'elle soit, se dit sur son compte
        words = failure_words(exc)
        if before is None or not before.failures or before.error != words:  # une panne, ou une autre : une ligne
            _noted(store, p, account.key, "", SYNC_FAILED, now, detail=words)
        return store.synced(account.key, error=words, at=now)
    if before is not None and before.failures:
        _noted(store, p, account.key, "", SYNC_RECOVERED, now, detail=before.error)
    return store.synced(account.key, at=now)


async def reread(store: AgendaPort, provider: CalendarProvider, account: Connection, calendar: str,
                 p: AgendaParams, now: int, kept: Sequence[Event] = ()) -> Calendar | None:
    """La copie d'un agenda relue après une écriture chez son fournisseur (réussie, ou refusée : un conflit, un
    événement disparu) : ``kept`` — ce que l'écriture a rendu, avec ce que Mika y a mis (``added``) — rangé d'abord,
    puis l'agenda relu depuis son curseur (``sync_calendar``). Rend l'agenda tel qu'il est après ; une panne de la
    relecture se lève (``AgendaError``), la copie d'avant reste. Le système n'a rien à relire."""
    if provider.kind == SYSTEM:
        return store.calendar(calendar)
    if kept:
        store.save([e for e in kept if e.calendar == calendar])
    found = store.calendar(calendar)
    if found is None:
        return None
    changed = await sync_calendar(store, provider, account, found, sync_window(now, p.past_us, p.ahead_us))
    _noted(store, p, account.key, calendar, SYNC_WRITTEN, now, changed + len(kept))
    return store.calendar(calendar)


async def sync_due(store: AgendaPort, providers: AgendaProviders, p: AgendaParams, now: int,
                   asked: Mapping[str, int] | None = None) -> int:
    """Un passage : les comptes des réglages rangés, ceux qui en sont partis effacés, les comptes dus relus — ceux
    qu'on a demandés (``asked`` : par compte, vide pour tous, l'instant de la demande) d'abord. Rend l'échéance
    suivante."""
    wanted = dict(asked or {})

    def when(c: Connection) -> int:
        return due_at(states[c.key], c.kind, p, max(wanted.get(c.key, 0), wanted.get("", 0)))

    accounts = [c for c in providers.connections() if not system_person(c.key)]
    keys = {c.key for c in accounts}
    for state in store.accounts():
        if not system_person(state.key) and state.key not in keys:
            store.drop_account(state.key)
    off = set(p.accounts_off)
    states = {c.key: store.keep_account(c.key, c.kind, owner=c.owner, address=c.address,
                                        enabled=c.enabled and c.key not in off) for c in accounts}
    live = [c for c in accounts if c.enabled and c.key not in off and providers.of(c.kind) is not None]
    ran = 0
    for c in sorted(live, key=lambda c: (when(c), c.key)):
        provider = providers.of(c.kind)
        if provider is None or when(c) > now or ran >= p.per_run:
            continue
        states[c.key] = await sync_account(store, provider, c, p, now)
        ran += 1
    following = [when(c) for c in live]
    return max(now, min(following)) if following else now + IDLE_EVERY


@AGENDA.process("agenda.sync", wake_on=[SYNC_ASKED], catch_up=CatchUp.ONCE, max_quantum_s=900, priority=80,
                deadline_s=600)
class Sync:
    def __init__(self) -> None:
        #: l'échéance la plus proche, d'après le dernier passage (``None`` : pas encore passé)
        self.due: int | None = None

    def next_due(self, s: AgendaState | None, frame: Frame, last_run: int | None) -> int | None:
        if s is not None and any(at > (last_run or 0) for at in s.sync_asked.values()):
            return frame.now  # « Synchroniser maintenant » : tout de suite, même endormie
        return frame.now if self.due is None else max(frame.now, self.due)

    async def run(self, ctx: Any) -> None:
        store, providers = ctx.ports.get("agenda"), ctx.ports.get("agenda_providers")
        if store is None or providers is None:
            self.due = ctx.now + IDLE_EVERY
            return
        self.due = await sync_due(store, providers, params_of(ctx.frame), ctx.now,
                                  getattr(getattr(ctx, "state", None), "sync_asked", None))


__all__ = ["IDLE_EVERY", "PAGES_MAX", "Sync", "due_at", "failure_words", "reread", "sync_account", "sync_calendar",
           "sync_due"]
