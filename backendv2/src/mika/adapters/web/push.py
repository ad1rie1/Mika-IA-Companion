"""Notifier le téléphone fermé (ADR 0077).

L'application ne garde plus de connexion ouverte quand elle est fermée : ce qu'elle disait à un téléphone en
arrière-plan (ADR 0062) part désormais par Firebase, scellé pour lui seul (``adapters/push``). La règle est celle
que l'application appliquait à ce qu'elle recevait :

- **une parole** de Mika à une personne, dans le fil (un identifiant de message), avec du texte — jamais une pensée
  à voix haute, jamais le sort d'une question (abstention, échec) ;
- **pas la réponse à une question posée d'un autre appareil** (un navigateur) : on la lit là où on l'a posée ;
  posée depuis un téléphone (une réponse depuis la notification), elle revient en notification ;
- **à chaque téléphone du compte qui ne la regarde pas** : un téléphone dont l'application est à l'écran, connexion
  vivante, reçoit par elle. Quittée depuis peu (connexion « absente ») ou muette depuis ``LIVE_S``, il est notifié
  quand même : l'application ne montre pas deux fois le même message.

Un envoi ne retient jamais la livraison : il part dans une tâche à part. Un jeton Firebase mort est oublié.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from mika.adapters.push import fcm, seal
from mika.adapters.web.accounts import Accounts, PushRegistration, account_of_handle
from mika.ports import delivery as delivery_p
from mika.ports.delivery import Delivery
from mika.ports.shares import valid_id
from mika.vocab import voice
from mika.vocab.affect import strip_prosody
from mika.vocab.people import is_internal

log = logging.getLogger("mika.push")

#: à l'arrêt, ce que les notifications en cours ont encore pour partir (secondes)
STOP_GRACE_S = 5.0
#: une connexion qui regarde mais n'a rien envoyé depuis (secondes ; les clients pinguent toutes les 20 s) n'est plus
#: crue vivante : le téléphone est notifié quand même
LIVE_S = 45.0


class Sender(Protocol):
    def configured(self) -> bool: ...
    async def send(self, device_token: str, data: dict[str, str]) -> fcm.SendResult: ...


def wanted(d: Delivery, *, asked_session: str | None, registered: Iterable[str]) -> bool:
    """Cette livraison mérite-t-elle une notification ? ``asked_session`` : la connexion d'où venait la question
    à laquelle elle répond (``None`` : elle écrit la première, ou on ne sait plus) ; ``registered`` : les clés de
    connexion des téléphones notifiables de la personne."""
    if d.kind != delivery_p.SPEECH or d.persona == voice.INNER:
        return False
    if not d.target or is_internal(d.target) or d.message_id <= 0:
        return False
    if not strip_prosody(d.text).strip():
        return False
    return asked_session is None or asked_session in set(registered)


def recipients(registrations: Iterable[PushRegistration], open_sessions: Iterable[str]) -> list[PushRegistration]:
    """Les téléphones à notifier : ceux dont aucune connexion n'est ouverte."""
    opened = set(open_sessions)
    return [r for r in registrations if r.session not in opened]


@dataclass(slots=True)
class PushStats:
    """Ce que la console montre de l'envoi (en mémoire, depuis le démarrage)."""

    sent: int = 0
    failed: int = 0
    gone: int = 0
    last_sent_at: float = 0.0
    last_error: str = ""


class MobilePush:
    def __init__(self, accounts: Accounts, sender: Sender, *, now_ms: Callable[[], int] | None = None) -> None:
        self.accounts = accounts
        self.sender = sender
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._tasks: set[asyncio.Task[None]] = set()
        self._stopped = False
        self.stats = PushStats()

    def configured(self) -> bool:
        return self.sender.configured()

    def schedule(self, d: Delivery, *, open_sessions: Iterable[str], asked_session: str | None) -> bool:
        """Décide tout de suite (``open_sessions`` : les téléphones qui la regardent en ce moment) et envoie dans une
        tâche à part. Rend vrai si au moins un téléphone sera notifié."""
        account = account_of_handle(d.target)
        if self._stopped or account is None or not self.sender.configured():
            return False
        try:
            registrations = self.accounts.push_registrations(account)
        except Exception as exc:  # une base illisible ne retient pas la livraison
            log.warning("notifications : téléphones illisibles (%r)", exc)
            return False
        if not wanted(d, asked_session=asked_session, registered=[r.session for r in registrations]):
            return False
        targets = recipients(registrations, open_sessions)
        if not targets:
            return False
        body = seal.payload(message_id=d.message_id, text=strip_prosody(d.text).strip(), ts_ms=self._now_ms(),
                            files=sum(1 for a in d.attachments if valid_id(a)))  # ses fichiers, pas ses bulles
        task = asyncio.get_running_loop().create_task(self._send_all(targets, body), name="push")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    def offer(self, account: int, body: dict[str, object]) -> int:
        """Un clair qui n'est pas une parole (une réponse proposée, ADR 0120) : à **chaque** téléphone du compte,
        que l'application soit ouverte ou non — c'est lui qui demande l'autorisation, une notification qu'aucune
        connexion ne montre. Envoyé dans une tâche à part ; rend combien de téléphones le recevront."""
        if self._stopped or not self.sender.configured():
            return 0
        try:
            targets = list(self.accounts.push_registrations(account))
        except Exception as exc:  # une base illisible ne fait pas tomber la capacité
            log.warning("notifications : téléphones illisibles (%r)", exc)
            return 0
        if not targets:
            return 0
        task = asyncio.get_running_loop().create_task(self._send_all(targets, body), name="push")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return len(targets)

    async def _send_all(self, targets: list[PushRegistration], body: dict[str, object]) -> None:
        for reg in targets:
            try:
                await self._send_one(reg, body)
            except Exception as exc:  # un téléphone en échec n'empêche jamais les suivants
                self.stats.failed += 1
                self.stats.last_error = f"{type(exc).__name__} : {exc}"[:300]
                log.warning("notifications : envoi au téléphone %s en échec (%r)", reg.token_id, exc)

    async def _send_one(self, reg: PushRegistration, body: dict[str, object]) -> None:
        try:
            data = seal.seal(seal.key_from(reg.key), body)
        except ValueError as exc:
            log.warning("notifications : clé du téléphone %s illisible (%s), oubliée", reg.token_id, exc)
            await self.accounts.clear_push(reg.token_id, reg.device_token)
            return
        result = await self.sender.send(reg.device_token, data)
        if result.outcome == fcm.SENT:
            self.stats.sent += 1
            self.stats.last_sent_at = time.time()
        elif result.outcome == fcm.GONE:
            self.stats.gone += 1
            log.info("notifications : le téléphone %s ne reçoit plus (%s), oublié", reg.token_id, result.detail)
            # ce jeton-là seulement : le téléphone a pu en donner un neuf entre-temps
            await self.accounts.clear_push(reg.token_id, reg.device_token)
        elif result.outcome == fcm.FAILED:
            self.stats.failed += 1
            self.stats.last_error = result.detail
            log.warning("notifications : envoi au téléphone %s en échec (%s)", reg.token_id, result.detail)

    async def drain(self) -> None:
        """Attend les envois en cours (les tests, l'arrêt)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def stop(self, grace_s: float = STOP_GRACE_S) -> None:
        """À l'arrêt : ce qui part encore a ``grace_s`` pour partir (une parole dite juste avant l'arrêt), puis
        est abandonné — le message reste dans le fil."""
        self._stopped = True  # ce qui se dit pendant l'arrêt reste dans le fil, sans notification
        pending = list(self._tasks)
        if pending:
            _done, late = await asyncio.wait(pending, timeout=grace_s)
            for task in late:
                task.cancel()
            await asyncio.gather(*late, return_exceptions=True)
