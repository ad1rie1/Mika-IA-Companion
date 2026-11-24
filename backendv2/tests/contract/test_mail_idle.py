"""Le courrier en direct (ADR 0308), contre le faux serveur IMAP qui sait attendre (``IDLE``) :

- un mail arrivé pendant qu'on attend est rangé tout de suite, sans rien marquer lu ; il attend son tri, et sa relève
  le lui rend une fois, une seule ;
- un drapeau posé ailleurs se range aussi ; ce qu'il dit (lu ailleurs) lui est dit une fois, même après un
  redémarrage ;
- un serveur qui ne sait pas attendre est rangé chaque minute (le temps des attentes est factice : rien n'attend
  vraiment) ;
- une connexion coupée se refait, et ce qui est arrivé entre-temps est rangé — ce n'est pas une panne ;
- une panne se dit sur la boîte et une seule fois au journal, les essais s'espacent, et une boîte réparée repart ;
- un dossier relevé où l'on n'attend pas suit quand même ; la connexion se refait avant la limite de la RFC ;
- une boîte réglée autrement se refait, une boîte retirée s'arrête.
"""

from __future__ import annotations

import asyncio
import imaplib
import logging
import socket
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from mika.adapters.mail import ImapSmtpMail, MailAccount, MailConfig, MailWatch, idle
from tests.fixtures.mail_servers import Imap, raw_mail, serve

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)
WAITS = "IMAP4rev1 MOVE UIDPLUS IDLE"
FIRST = "pro:<mail-3@exemple.fr>"


@pytest.fixture
def imap():
    Imap.reset({3: raw_mail(3, "Coucou", "Tu viens samedi ?")}, caps=WAITS)
    server = serve(Imap)
    yield server.server_address[1]
    Imap.cut()
    server.shutdown()
    server.server_close()


def account(port: int, **more) -> MailAccount:
    return MailAccount(**{"address": "mika@exemple.fr", "imap_host": "127.0.0.1", "imap_port": port,
                          "imap_ssl": False, "user": "mika", "password": "secret", "since_days": 7, **more})


class Boxes:
    """Des réglages qu'on change en cours de route (relus à chaque appel, comme ceux du serveur)."""

    def __init__(self, **accounts: MailAccount) -> None:
        self.accounts = dict(accounts)

    def __call__(self) -> MailConfig:
        return MailConfig(accounts=dict(self.accounts))


class Ticks:
    """Le temps des attentes de l'observateur, factice : chaque ``sleep`` est noté, et ne rend la main que quand le
    test le dit (``go``)."""

    def __init__(self) -> None:
        self.asked: list[float] = []
        self._permits: asyncio.Queue[None] = asyncio.Queue()

    async def sleep(self, seconds: float) -> None:
        self.asked.append(seconds)
        await self._permits.get()

    def go(self) -> None:
        self._permits.put_nowait(None)


async def until(cond: Callable[[], object], timeout: float = 5.0) -> None:
    """Attend (vraiment, mais peu) que ``cond`` tienne ; échoue au-delà de ``timeout``."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        if loop.time() > end:
            raise AssertionError("trop long")
        await asyncio.sleep(0.01)


def mailbox(tmp_path, boxes: Boxes) -> ImapSmtpMail:
    return ImapSmtpMail(boxes, tmp_path / "mail.db", now=lambda: NOW, tz=UTC)


def idles() -> int:
    return sum(1 for c in Imap.commands if c.upper() == "IDLE")


def test_a_mail_that_arrives_while_it_waits_is_ranged_at_once_and_handed_once(tmp_path, imap):
    async def run() -> None:
        mail = mailbox(tmp_path, Boxes(pro=account(imap)))
        said: list = []
        mail.on_change(said.append)
        watch = MailWatch(mail, sleep=Ticks().sleep)
        watch.start()
        try:
            await until(lambda: Imap.waiting() == 1)  # entré, ce qui était là rangé, il attend
            assert mail.cached_one(FIRST) is not None and watch.modes() == {"pro": idle.WAITING}
            said.clear()
            Imap.deliver(raw_mail(9, "Vite", "Tu es là ?"))
            await until(lambda: mail.cached_one("pro:<mail-9@exemple.fr>") is not None)
            await until(lambda: Imap.waiting() == 1)
            assert any(c.topic == "mail" and c.accounts == ("pro",) for c in said)  # les écrans le voient
            assert mail.waiting() == {FIRST, "pro:<mail-9@exemple.fr>"}  # son tri l'attend
            status = mail.status("pro")
            assert status.last_poll > 0 and status.error == ""  # un rangement compte comme une relève
        finally:
            await watch.stop()
        assert all(not flags for flags, _ in Imap.boxes["INBOX"].mails.values())  # rien n'est marqué lu
        assert not any(c.upper().startswith(("UID STORE", "SELECT")) for c in Imap.commands)  # EXAMINE seulement
        # sa relève, à son rythme : chacun une fois, puis plus jamais
        got = await mail.fetch_new(10)
        assert sorted(m.ref for m in got) == [FIRST, "pro:<mail-9@exemple.fr>"]
        mail.ack([m.ref for m in got])
        assert await mail.fetch_new(10) == [] and mail.waiting() == frozenset()
        mail.close()

    asyncio.run(run())


def test_her_poll_takes_what_was_ranged_at_her_pace_and_loses_nothing(tmp_path, imap):
    """Une nuit de courrier, rangée par passages (le verrou de la boîte rendu entre deux), puis rendue à sa relève à
    son budget : rien de perdu, rien deux fois."""
    for uid in range(10, 40):
        Imap.boxes["INBOX"].add(raw_mail(uid, f"Mail {uid}", "Bonjour"), uid=uid)

    async def run() -> None:
        mail = mailbox(tmp_path, Boxes(pro=account(imap)))
        passes = [await mail.range_box("pro") for _ in range(3)]  # il en restait : un autre passage, puis plus rien
        assert passes == [False, True, True] and len(mail.waiting()) == 31
        seen: list[str] = []
        while got := await mail.fetch_new(10):
            seen += [m.ref for m in got]
            mail.ack([m.ref for m in got])
        assert len(seen) == len(set(seen)) == 31 and mail.waiting() == frozenset()
        mail.close()

    asyncio.run(run())


def test_a_mail_read_elsewhere_is_told_to_her_once_even_after_a_restart(tmp_path, imap):
    async def run() -> None:
        mail = mailbox(tmp_path, Boxes(pro=account(imap)))
        mail.ack([m.ref for m in await mail.fetch_new(10)])  # déjà remarqué
        watch = MailWatch(mail, sleep=Ticks().sleep)
        watch.start()
        try:
            await until(lambda: Imap.waiting() == 1)
            Imap.touch(3, "\\Seen")  # lu sur son téléphone, pendant qu'elle dort
            await until(lambda: mail.cached_one(FIRST).seen)
        finally:
            await watch.stop()
        mail.close()
        again = mailbox(tmp_path, Boxes(pro=account(imap)))  # le serveur redémarre avant sa relève
        assert again.seen_elsewhere() == [FIRST]
        assert again.seen_elsewhere() == []  # dit une fois
        again.close()

    asyncio.run(run())


def test_a_box_whose_server_cannot_wait_is_ranged_every_minute(tmp_path, imap):
    Imap.caps = "IMAP4rev1 MOVE UIDPLUS"

    async def run() -> None:
        mail = mailbox(tmp_path, Boxes(pro=account(imap)))
        ticks = Ticks()
        watch = MailWatch(mail, sleep=ticks.sleep)
        watch.start()
        try:
            await until(lambda: ticks.asked == [idle.POLL_EVERY_S])
            assert mail.cached_one(FIRST) is not None and watch.modes() == {"pro": idle.EVERY_MINUTE}
            Imap.deliver(raw_mail(9, "Vite", "Tu es là ?"))
            await asyncio.sleep(0.2)
            assert mail.cached_one("pro:<mail-9@exemple.fr>") is None  # la minute n'est pas passée
            ticks.go()
            await until(lambda: len(ticks.asked) == 2)
            assert mail.cached_one("pro:<mail-9@exemple.fr>") is not None and ticks.asked == [60.0, 60.0]
        finally:
            await watch.stop()
        assert "IDLE" not in {c.upper() for c in Imap.commands}
        mail.close()

    asyncio.run(run())


def test_a_cut_connection_is_made_again_and_what_arrived_meanwhile_is_ranged(tmp_path, imap):
    async def run() -> None:
        mail = mailbox(tmp_path, Boxes(pro=account(imap)))
        ticks = Ticks()
        watch = MailWatch(mail, sleep=ticks.sleep)
        watch.start()
        try:
            await until(lambda: Imap.waiting() == 1)
            Imap.cut()  # le serveur ferme la connexion qui attend…
            Imap.deliver(raw_mail(9, "Pendant", "Personne n'écoutait"))  # … et un mail arrive entre-temps
            await until(lambda: ticks.asked == [idle.RETRY_FIRST_S])
            assert watch.modes() == {"pro": idle.PAUSED}
            assert mail.status("pro").error == ""  # une connexion coupée n'est pas une panne
            ticks.go()
            await until(lambda: mail.cached_one("pro:<mail-9@exemple.fr>") is not None)  # rangé à la reconnexion
            await until(lambda: Imap.waiting() == 1)
            assert watch.modes() == {"pro": idle.WAITING}
        finally:
            await watch.stop()
        mail.close()

    asyncio.run(run())


def test_a_failure_is_said_on_the_box_once_and_tried_again_ever_later(tmp_path, imap, caplog):
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    nobody = closed.getsockname()[1]
    closed.close()  # un port où personne ne répond
    boxes = Boxes(pro=account(nobody))

    async def run() -> None:
        mail = mailbox(tmp_path, boxes)
        ticks = Ticks()
        watch = MailWatch(mail, sleep=ticks.sleep)
        watch.start()
        try:
            await until(lambda: ticks.asked == [5.0])
            assert mail.status("pro").error and watch.modes() == {"pro": idle.FAILING}
            for _ in range(2):
                ticks.go()
                await until(lambda n=len(ticks.asked): len(ticks.asked) == n + 1)
            assert ticks.asked == [5.0, 10.0, 20.0]  # de plus en plus espacés
            warned = [r for r in caplog.records if r.levelno == logging.WARNING and "direct" in r.getMessage()]
            assert len(warned) == 1  # trois essais, une ligne
            boxes.accounts["pro"] = account(imap)  # réparée…
            watch.nudge()  # … et enregistrée
            await until(lambda: Imap.waiting() == 1)
            assert mail.status("pro").error == "" and mail.cached_one(FIRST) is not None
            assert any("de nouveau" in r.getMessage() for r in caplog.records)
        finally:
            await watch.stop()
        mail.close()

    with caplog.at_level(logging.INFO, logger="mika.mail"):
        asyncio.run(run())


def test_a_watched_box_ranges_its_other_folders_too(tmp_path, imap):
    Imap.boxes["Pro"] = Imap.boxes.pop("Archives")

    async def run() -> None:
        mail = mailbox(tmp_path, Boxes(pro=account(imap, folders=("INBOX", "Pro"))))
        watch = MailWatch(mail, sleep=Ticks().sleep, folders_every=0.2)
        watch.start()
        try:
            await until(lambda: Imap.waiting() == 1)
            # rangé là par une règle du serveur : on n'attend que sur la réception, rien ne le dit…
            Imap.deliver(raw_mail(9, "Ailleurs", "Rangé par une règle du serveur"), folder="Pro")
            # … et le dossier suit quand même, à son rythme (ici, vite)
            await until(lambda: mail.cached_one("pro:<mail-9@exemple.fr>") is not None)
            assert mail.cached_one("pro:<mail-9@exemple.fr>").folder == "Pro"
            assert watch.modes() == {"pro": idle.WAITING}
        finally:
            await watch.stop()
        mail.close()

    asyncio.run(run())


def test_the_waiting_connection_is_made_again_before_the_rfc_limit(tmp_path, imap):
    async def run() -> None:
        mail = mailbox(tmp_path, Boxes(pro=account(imap)))
        watch = MailWatch(mail, sleep=Ticks().sleep, session_for=0.5)
        watch.start()
        try:
            await until(lambda: Imap.waiting() == 1)
            # une connexion pour attendre, une pour ranger ce qui était là ; rien n'arrive : seule la limite de la
            # session en fait entrer d'autres
            assert len(Imap.logins) == 2
            await until(lambda: len(Imap.logins) >= 4 and Imap.waiting() == 1)
            assert idles() >= 2 and watch.modes() == {"pro": idle.WAITING}
        finally:
            await watch.stop()
        mail.close()

    asyncio.run(run())


def test_a_box_set_otherwise_is_made_again_and_a_removed_one_stops(tmp_path, imap):
    boxes = Boxes(pro=account(imap))

    async def run() -> None:
        mail = mailbox(tmp_path, boxes)
        watch = MailWatch(mail, sleep=Ticks().sleep)
        watch.start()
        try:
            await until(lambda: Imap.waiting() == 1)
            logins = len(Imap.logins)
            boxes.accounts["pro"] = account(imap, folders=("INBOX", "Archives"))  # ses dossiers changent
            watch.nudge()
            await until(lambda: len(Imap.logins) > logins and Imap.waiting() == 1)
            boxes.accounts["pro"] = account(imap, folders=("INBOX", "Archives"), enabled=False)  # coupée
            watch.nudge()
            await until(lambda: Imap.waiting() == 0 and watch.modes() == {})
            boxes.accounts.clear()  # retirée
            watch.nudge()
            Imap.deliver(raw_mail(9, "Trop tard", "Plus personne"))
            await asyncio.sleep(0.3)
            assert mail.cached_one("pro:<mail-9@exemple.fr>") is None and watch.modes() == {}
        finally:
            await watch.stop()
        mail.close()

    asyncio.run(run())


def test_stopping_closes_every_connection_at_once(tmp_path, imap):
    async def run() -> None:
        mail = mailbox(tmp_path, Boxes(pro=account(imap), perso=account(imap, user="perso")))
        watch = MailWatch(mail, sleep=Ticks().sleep)
        watch.start()
        await until(lambda: Imap.waiting() == 2)
        loop = asyncio.get_running_loop()
        began = loop.time()
        await watch.stop()
        assert loop.time() - began < 1.0  # l'attente (25 min) ne retient pas l'arrêt
        await until(lambda: Imap.waiting() == 0)
        mail.close()

    asyncio.run(run())


def test_the_wait_is_renewed_on_the_same_connection_before_a_router_forgets_it(tmp_path, imap):
    """Une connexion muette, un routeur l'oublie au bout de dix à quinze minutes : l'attente se relance (``DONE`` puis
    ``IDLE``) bien avant, sans se reconnecter."""
    async def run() -> None:
        mail = mailbox(tmp_path, Boxes(pro=account(imap)))
        watch = MailWatch(mail, sleep=Ticks().sleep, idle_for=0.2)
        watch.start()
        try:
            await until(lambda: idles() >= 3 and Imap.waiting() == 1)
            assert len(Imap.logins) == 2 and watch.modes() == {"pro": idle.WAITING}  # la même connexion
            Imap.deliver(raw_mail(9, "Vite", "Tu es là ?"))  # et elle entend toujours
            await until(lambda: mail.cached_one("pro:<mail-9@exemple.fr>") is not None)
        finally:
            await watch.stop()
        mail.close()

    asyncio.run(run())
    assert 0 < idle.IDLE_FOR_S <= 10 * 60


def test_without_idle_in_this_python_a_box_is_ranged_every_minute(tmp_path, imap, monkeypatch):
    """``imaplib`` ne sait ``IDLE`` que depuis Python 3.14 : avant (le dépôt admet 3.12), même un serveur qui le sait
    voit sa boîte rangée chaque minute, sans trace à chaque essai."""
    monkeypatch.delattr(imaplib.IMAP4, "idle", raising=False)

    async def run() -> None:
        mail = mailbox(tmp_path, Boxes(pro=account(imap)))
        ticks = Ticks()
        watch = MailWatch(mail, sleep=ticks.sleep)
        watch.start()
        try:
            await until(lambda: ticks.asked == [idle.POLL_EVERY_S])
            assert mail.cached_one(FIRST) is not None and watch.modes() == {"pro": idle.EVERY_MINUTE}
            assert mail.status("pro").error == ""
        finally:
            await watch.stop()
        assert "IDLE" not in {c.upper() for c in Imap.commands}
        mail.close()

    asyncio.run(run())


def test_a_ranging_in_several_passes_shares_one_connection(tmp_path, imap):
    """Une nuit de courrier se range par passages (le verrou de la boîte rendu entre deux) : le premier ouvre sa
    connexion, les suivants en partagent une — pas une connexion par passage."""
    for uid in range(10, 70):
        Imap.boxes["INBOX"].add(raw_mail(uid, f"Mail {uid}", "Bonjour"), uid=uid)

    async def run() -> None:
        mail = mailbox(tmp_path, Boxes(pro=account(imap)))
        watch = MailWatch(mail, sleep=Ticks().sleep)
        watch.start()
        try:
            await until(lambda: Imap.waiting() == 1)
            assert len(mail.waiting()) == 61  # trois passages de 25
            assert len(Imap.logins) == 3  # celle qui attend, celle du premier passage, celle des suivants
        finally:
            await watch.stop()
        mail.close()

    asyncio.run(run())


def test_a_history_pass_says_its_folder_once(tmp_path, imap):
    """Une boîte « tout garder en local » remonte son historique par passages : chacun dit son dossier une fois, pas
    une fois par mail (les écrans se relisaient toutes les 150 ms, des heures durant)."""
    for uid in range(10, 40):
        Imap.boxes["INBOX"].add(raw_mail(uid, f"Mail {uid}", "Bonjour"), uid=uid)

    async def run() -> None:
        mail = mailbox(tmp_path, Boxes(pro=account(imap)))
        said: list = []
        mail.on_change(said.append)
        assert await mail.older("pro", "INBOX", 100) == 31
        assert [c for c in said if c.topic == "mail"] == [said[0]] and said[0].accounts == ("pro",)
        mail.close()

    asyncio.run(run())


def test_a_watched_box_has_one_rule_for_its_failure(tmp_path, imap):
    """Observée en direct, sa panne est celle du direct : sa relève, qui y range encore, n'en dit ni n'en efface — le
    marqueur ne bascule plus de l'un à l'autre."""
    async def run() -> None:
        mail = mailbox(tmp_path, Boxes(pro=account(imap)))
        mail.observed = frozenset({"pro"})
        mail._cache.note("pro", at=1, error="le direct ne joint pas le serveur", polled=True)
        await mail.fetch_new(10)  # sa relève réussit…
        assert mail.status("pro").error == "le direct ne joint pas le serveur"  # … la panne du direct reste
        mail.observed = frozenset()
        await mail.fetch_new(10)
        assert mail.status("pro").error == ""  # sans direct, sa relève dit l'état de la boîte
        mail.close()

    asyncio.run(run())


def test_retrying_doubles_up_to_a_few_minutes():
    delays = [idle.retry_after(0)]
    for _ in range(8):
        delays.append(idle.retry_after(delays[-1]))
    assert delays[:4] == [5.0, 10.0, 20.0, 40.0] and delays[-1] == idle.RETRY_MAX_S == 300.0
    assert idle.SESSION_FOR_S < 29 * 60  # RFC 2177
