"""Le courrier réel : IMAP pour lire et ranger, SMTP pour envoyer (bibliothèque
standard, dans un fil), un cache SQLite à part pour ce qui est arrivé.

- **Plusieurs comptes**, chacun avec ses dossiers relevés ; une panne sur un
  compte n'empêche pas de relever les autres (elle est notée : la console la
  montre).
- **Chaque mail est rendu jusqu'à son accusé** (``fetch_new`` puis ``ack``),
  puis plus jamais, même s'il change de dossier : un relevé interrompu avant
  d'avoir remarqué ses mails les retrouve au suivant ; au premier relevé d'un
  dossier, on ne remonte que quelques jours.
- **Un client complet** : lu/non lu, suivi, déplacer, archiver, corbeille —
  sur le serveur, et le cache suit.
- **Ce qui part** est mis en forme par ``compose`` (l'expéditeur selon la voix
  du compte, sa signature, la citation) ; un brouillon ne part que tel qu'il
  a été lu (le condensé de l'aperçu).
- La configuration est relue à chaque appel (changer de compte ne demande pas
  de redémarrer).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import smtplib
import ssl
import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from mika.adapters.mail import compose
from mika.adapters.mail.cache import MailCache
from mika.adapters.mail.config import MailAccount, MailConfig
from mika.adapters.mail.imap import ImapError, Session, role_of, since
from mika.adapters.mail.parse import attachment_files, parse
from mika.ports.mail import (
    AccountInfo,
    AccountStatus,
    Attachment,
    Draft,
    File,
    Folder,
    Mail,
    Preview,
    Sent,
    forwarded_text,
    split_ref,
)

log = logging.getLogger("mika.mail")

#: les derniers mails d'un dossier relevé dont on relit les drapeaux (lus ailleurs ?)
FLAGS_WINDOW = 200


def _local_tz() -> tzinfo:
    return datetime.now().astimezone().tzinfo or UTC


class ImapSmtpMail:
    def __init__(self, config: Callable[[], MailConfig], cache: Path, *,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC), tz: tzinfo | None = None,
                 timeout: float = 30.0) -> None:
        self._config = config
        self._now = now
        self._tz = tz or _local_tz()
        self._timeout = timeout
        self._cache = MailCache(cache)
        self._locks: dict[str, asyncio.Lock] = {}
        self._seen_elsewhere: list[str] = []

    # ── comptes ──
    def _accounts(self) -> dict[str, MailAccount]:
        return dict(self._config().accounts)

    def configured(self) -> bool:
        return self._config().ready

    def accounts(self) -> list[AccountInfo]:
        return [a.info(k) for k, a in sorted(self._accounts().items())]

    def account(self, key: str) -> AccountInfo | None:
        found = self._accounts().get(key)
        return found.info(key) if found is not None else None

    def _account(self, key: str) -> MailAccount:
        found = self._accounts().get(key)
        if found is None:
            raise ValueError(f"compte inconnu : {key}")
        return found

    def _lock(self, key: str) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    def _at(self) -> int:
        return int(self._now().timestamp() * 1_000_000)

    async def _in_thread(self, key: str, fn: Callable[..., Any], *args: Any) -> Any:
        async with self._lock(key):
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, fn, *args)

    def _session(self, account: MailAccount) -> Session:
        return Session(account, timeout=self._timeout)

    # ── relever ──
    async def fetch_new(self, limit: int) -> list[Mail]:
        ready = [(k, a) for k, a in sorted(self._accounts().items()) if a.ready]
        out: list[Mail] = []
        for i, (key, account) in enumerate(ready):
            share = max(1, -(-(limit - len(out)) // (len(ready) - i)))
            if len(out) >= limit:
                break
            try:
                await self._in_thread(key, self._poll_sync, key, account, share)
            except (OSError, ImapError, ValueError, EOFError) as exc:
                self._cache.note(key, at=self._at(), error=_why(exc), polled=True)
                log.warning("courrier : relevé de %s impossible (%s)", key, type(exc).__name__)
            # ce qui attend son accusé : ce relevé-ci (même si un dossier suivant a échoué), ou un passage
            # interrompu avant d'avoir remarqué ce qu'on lui avait rendu
            out.extend(self._cache.offered(key, share))
        return out[:limit]

    def ack(self, refs: Sequence[str]) -> None:
        self._cache.ack(refs)

    def seen_elsewhere(self) -> list[str]:
        out, self._seen_elsewhere = self._seen_elsewhere, []
        return out

    def _poll_sync(self, key: str, account: MailAccount, limit: int) -> list[Mail]:
        out: list[Mail] = []
        with self._session(account) as s:
            if not self._cache.folders(key):
                self._list_sync(s, key)
            for folder in account.folders:
                if len(out) >= limit:
                    break
                out += self._sync_sync(s, key, account, folder, limit - len(out), hand=True)
        self._cache.note(key, at=self._at(), polled=True)
        return out

    def _list_sync(self, s: Session, key: str) -> None:
        found = s.folders()
        for name, flags in found:
            self._cache.save_folder(key, name, role=role_of(name, flags))
        self._cache.keep_folders(key, [n for n, _ in found])

    def _read(self, raw: bytes, uid: int, key: str, folder: str, flags: frozenset[str]) -> Mail:
        """Un mail brut lu ; un mail que la lecture ne comprend pas devient une ligne qui le dit
        (on ne le relira pas à chaque relevé : il est rangé, et le curseur passe)."""
        try:
            mail = parse(raw, str(uid), account=key, folder=folder, complete=True)
        except Exception as exc:  # un mail hostile ou cassé n'arrête jamais un relevé
            log.warning("courrier : un mail illisible dans %s/%s (%s)", key, folder, type(exc).__name__)
            mail = Mail(f"<illisible-{hashlib.sha256(raw).hexdigest()[:20]}@mika>", "(expéditeur illisible)", "",
                        "(un mail illisible)", 0, "Ce mail n'a pas pu être lu.", account=key, folder=folder)
        return replace(mail, seen="\\seen" in flags, flagged="\\flagged" in flags, answered="\\answered" in flags)

    def _sync_sync(self, s: Session, key: str, account: MailAccount, folder: str, limit: int, *,
                   hand: bool) -> list[Mail]:
        """Relit un dossier : ce qui est nouveau (au plus ``limit``), puis les drapeaux
        des derniers mails connus. Rend les mails nouveaux jamais rendus (``hand``).

        Le curseur avance **mail après mail** : un relevé interrompu reprend après le dernier mail
        rangé, et un mail illisible ne revient pas à chaque relevé. Relu depuis la console
        (``hand`` faux), un dossier qu'elle relève garde le curseur de la relève : ce que la
        console vient de ranger, elle le remarquera quand même au prochain relevé."""
        _count, validity, uidnext = s.select(folder)
        cursor = self._cache.cursor(key, folder)
        if cursor is not None and cursor[0] and validity and cursor[0] != validity:
            self._cache.reset_folder(key, folder)  # les UID ont changé de sens : tout se relit
            cursor = None
        owns_cursor = hand or folder not in account.folders  # la console relit un dossier relevé : pas son curseur
        start = cursor[1] if cursor is not None and cursor[1] > 0 else 0
        if start:
            uids = [u for u in s.search(f"UID {start}:*") if u >= start]
        else:
            uids = s.search(f"SINCE {since(self._now() - timedelta(days=max(0, account.since_days)))}")
        taken = uids[:max(0, limit)]
        out: list[Mail] = []
        for uid, flags, raw in sorted(s.fetch(taken)):
            stored = self._cache.store(self._read(raw, uid, key, folder, flags), uid)
            local = split_ref(stored.ref)[1]
            if hand and not self._cache.handed(key, local):
                self._cache.offer(key, stored.ref)  # rendu pour de bon à l'accusé (``ack``), pas avant
                out.append(stored)
            if owns_cursor:
                self._cache.save_folder(key, folder, uidvalidity=validity or None, uidnext=uid + 1)
        if not hand:
            for uid, flags, raw in s.fetch(self._cache.missing_html(key, folder, limit)):
                self._cache.store(self._read(raw, uid, key, folder, flags), uid)
        nxt = (max(taken) + 1) if len(taken) < len(uids) else max(uidnext, (max(taken) + 1) if taken else start)
        self._refresh_flags(s, key, folder, hand=hand)
        if owns_cursor:
            self._cache.save_folder(key, folder, uidvalidity=validity or None, uidnext=nxt or None,
                                    last_sync=self._at())
        else:
            self._cache.save_folder(key, folder, last_sync=self._at())
        self._cache.recount(key, folder)
        return out

    def _refresh_flags(self, s: Session, key: str, folder: str, *, hand: bool) -> None:
        known = self._cache.uids(key, folder, FLAGS_WINDOW)
        if not known:
            return
        flags = s.flags([u for u, _, _ in known])
        gone = [u for u, _, _ in known if u not in flags]
        if gone:
            self._cache.forget_uids(key, folder, gone)  # rangés ou supprimés ailleurs
        for uid, ref, was_seen in known:
            now = flags.get(uid)
            if now is None:
                continue
            seen = "\\seen" in now
            self._cache.set_flags(key, folder, uid, seen=seen, flagged="\\flagged" in now,
                                  answered="\\answered" in now)
            # su même quand c'est la console qui relit : la relève suivante ne le reverrait plus changer
            if seen and not was_seen and ref:
                self._seen_elsewhere.append(ref)

    # ── lire le cache ──
    async def get(self, ref: str) -> Mail | None:
        return self._cache.one(ref)

    async def recent(self, limit: int) -> list[Mail]:
        return self._cache.recent(limit)

    def cached(self, limit: int, *, account: str = "", folder: str = "") -> list[Mail]:
        return self._cache.recent(limit, account=account, folder=folder)

    def cached_one(self, ref: str) -> Mail | None:
        return self._cache.one(ref)

    def find_ref(self, key: str) -> str | None:
        return self._cache.find_ref(key)

    def messages_page(self, query, page=1, size=25):
        return self._cache.browse("messages", query, page, size)

    def outgoing_page(self, query, page=1, size=25):
        return self._cache.browse("outgoing", query, page, size)

    def contacts_page(self, account="", text="", page=1, size=25):
        return self._cache.browse("contacts", account, text, tuple(a.address for a in self.accounts()), page, size)

    def thread_page(self, ref, page=1, size=25):
        return self._cache.browse("thread", ref, page, size)

    def search_page(self, text, limit=25, offset=0):
        return self._cache.browse("hits", text, limit, offset)

    def search_count(self, text):
        return self._cache.browse("search_count", text)

    def drafts_page(self, text="", page=1, size=25):
        return self._cache.browse("drafts", text, page, size)

    async def _source(self, ref: str) -> bytes:
        local = self._cache.sent_source(ref)
        if local is not None:
            return local
        sent = self._cache.sent_one(ref)
        if sent is not None:
            msg = EmailMessage()
            msg['From'] = compose.sender(self._account(sent.account).info(sent.account))
            msg['To'], msg['Subject'], msg['Message-ID'] = sent.to, sent.subject, split_ref(sent.message_id)[1]
            msg.set_content(sent.body)
            return msg.as_bytes()
        key, acc, mail, uid = self._where(ref)
        def read():
            with self._session(acc) as session:
                _, validity, _ = session.select(mail.folder)
                previous, _ = self._cache.cursor(key, mail.folder) or (0, 0)
                if validity and previous and validity != previous:
                    raise ValueError("Le dossier a changé sur le serveur. Actualise-le avant de relire ce message.")
                actual = self._uid_sync(session, mail, uid)
                rows = session.fetch([actual])
                if not rows:
                    raise FileNotFoundError("Ce message n'est plus disponible sur le serveur.")
                number, flags, raw = rows[0]
                full = parse(raw, str(number), account=key, folder=mail.folder, complete=True)
                if full.message_id != mail.message_id:
                    raise ValueError("Ce message a changé sur le serveur. Actualise le dossier.")
                self._cache.store(replace(full, seen="\\seen" in flags, flagged="\\flagged" in flags,
                                           answered="\\answered" in flags), number)
                return raw
        return await self._in_thread(key, read)

    async def document(self, ref: str) -> Mail | None:
        cached = self._cache.one(ref)
        if cached is not None and cached.complete:
            return cached
        raw = await self._source(ref)
        if cached is not None:
            return self._cache.one(ref)
        sent = self._cache.sent_one(ref)
        return parse(raw, account=sent.account if sent else "", complete=True)

    async def file(self, ref: str, part: str) -> File:
        if part == "texte":
            full = await self.document(ref)
            if full is None:
                raise FileNotFoundError("Ce message n'est plus disponible.")
            return File("message.txt", "text/plain", full.body.encode())
        raw = await self._source(ref)
        if part == "source":
            return File("message.eml", "message/rfc822", raw)
        if not part.isdecimal() or len(part) > 5:
            raise FileNotFoundError("Pièce jointe inconnue.")
        files = attachment_files(raw)
        if int(part) >= len(files):
            raise FileNotFoundError("Cette pièce jointe n'est plus disponible.")
        return files[int(part)]

    async def forward(self, ref, to, subject, body, *, cc="", by="", attachments=True):
        original = await self.document(ref)
        if original is None:
            raise ValueError("Ce message n'est plus disponible.")
        files = attachment_files(await self._source(ref)) if attachments and original.attachments else ()
        key = self._sender_key(original.account, "")
        draft = Draft("", key, to, subject, forwarded_text(original, body), cc=cc, author=by)
        shown, _ = self._preview(draft)
        if shown.blocked:
            raise ValueError(shown.blocked)
        return await self._deliver(key, shown, None, "", by=by, draft_id="", files=files)

    def search(self, text: str, limit: int, *, account: str = "") -> list[Mail]:
        return self._cache.search(text, limit, account=account) if text.strip() else []

    # ── dossiers ──
    def folders(self, account: str) -> list[Folder]:
        found = self._accounts().get(account)
        return self._cache.folders(account, found.folders if found is not None else ())

    async def refresh_folders(self, account: str) -> list[Folder]:
        acc = self._account(account)

        def run() -> None:
            with self._session(acc) as s:
                self._list_sync(s, account)

        await self._in_thread(account, run)
        return self.folders(account)

    async def sync_folder(self, account: str, folder: str, limit: int) -> int:
        acc = self._account(account)

        def run() -> int:
            before = self._cache.folder_count(account, folder)
            with self._session(acc) as s:
                self._sync_sync(s, account, acc, folder, limit, hand=False)
            return max(0, self._cache.folder_count(account, folder) - before)

        return int(await self._in_thread(account, run))

    async def older(self, account: str, folder: str, limit: int = 50) -> int:
        acc = self._account(account)
        def run():
            with self._session(acc) as session:
                _, validity, _ = session.select(folder)
                previous, _ = self._cache.cursor(account, folder) or (0, 0)
                if previous and validity and previous != validity:
                    raise ValueError("Le dossier a changé sur le serveur : actualise-le avant de charger son historique.")
                first = self._cache.oldest_uid(account, folder)
                if first == 1:
                    return 0
                uids = sorted(u for u in session.search(f"UID 1:{first - 1}" if first else "ALL") if not first or u < first)
                rows = session.fetch(uids[-max(1, min(100, limit)):])
                for uid, flags, raw in rows:
                    stored = self._cache.store(self._read(raw, uid, account, folder, flags), uid)
                    self._cache.hand(account, split_ref(stored.ref)[1])
                self._cache.save_folder(account, folder, uidvalidity=validity or None)
                self._cache.recount(account, folder)
                return len(rows)
        return int(await self._in_thread(account, run))

    # ── ranger ──
    def _where(self, ref: str) -> tuple[str, MailAccount, Mail, int]:
        found = self._cache.located(ref)
        if found is None:
            raise ValueError("ce mail n'est plus dans le cache")
        mail, uid = found
        return mail.account, self._account(mail.account), mail, uid

    def _uid_sync(self, s: Session, mail: Mail, uid: int) -> int:
        """L'UID d'un mail dont le cache ne connaît pas l'UID (repris d'un ancien cache)."""
        if uid > 0:
            return uid
        wanted = mail.message_id.replace("\\", "").replace('"', "")
        found = s.search(f'HEADER Message-ID "{wanted}"')
        if not found:
            raise ValueError("ce mail n'est plus sur le serveur")
        self._cache.relocate(mail.account, mail.folder, uid, mail.folder, found[-1])
        return found[-1]

    async def set_flags(self, ref: str, *, seen: bool | None = None, flagged: bool | None = None) -> None:
        key, acc, mail, uid = self._where(ref)

        def run() -> None:
            with self._session(acc) as s:
                s.select(mail.folder, write=True)
                real = self._uid_sync(s, mail, uid)
                if seen is not None:
                    s.store(real, "\\Seen", seen)
                if flagged is not None:
                    s.store(real, "\\Flagged", flagged)
                self._cache.set_flags(key, mail.folder, real, seen=seen, flagged=flagged)
                self._cache.recount(key, mail.folder)

        await self._in_thread(key, run)

    async def mark_seen(self, refs: Sequence[str]) -> int:
        """Marque comme lus, par lot : une session par compte, un ``STORE`` par dossier pour tous
        ses mails ; rend combien n'ont pas pu l'être (inconnus du cache, ou refusés)."""
        wanted = list(dict.fromkeys(refs))
        found = self._cache.located_all(wanted)
        failed = len(wanted) - len(found)
        by_account: dict[str, dict[str, list[tuple[Mail, int]]]] = {}
        for mail, uid in found:
            if not mail.seen:
                by_account.setdefault(mail.account, {}).setdefault(mail.folder, []).append((mail, uid))
        for key, folders in by_account.items():
            acc = self._accounts().get(key)
            if acc is None or not acc.ready:
                failed += sum(len(v) for v in folders.values())
                continue

            def run(acc: MailAccount = acc, key: str = key, folders: dict = folders) -> int:
                missed = 0
                with self._session(acc) as s:
                    for folder, items in folders.items():
                        s.select(folder, write=True)
                        real = []
                        for mail, uid in items:
                            try:
                                real.append(self._uid_sync(s, mail, uid))
                            except ValueError:
                                missed += 1
                        for i in range(0, len(real), 200):
                            batch = real[i:i + 200]
                            s.store_many(batch, "\\Seen", True)
                            for u in batch:
                                self._cache.set_flags(key, folder, u, seen=True)
                        self._cache.recount(key, folder)
                return missed

            try:
                failed += int(await self._in_thread(key, run))
            except (OSError, ImapError, ValueError, EOFError) as exc:
                failed += sum(len(v) for v in folders.values())
                self._cache.note(key, at=self._at(), error=_why(exc))
        return failed

    async def move(self, ref: str, folder: str) -> str:
        key, acc, mail, uid = self._where(ref)
        if folder == mail.folder:
            return folder

        def run() -> str:
            with self._session(acc) as s:
                known = {f.name for f in self._cache.folders(key)}
                if folder not in known:
                    self._list_sync(s, key)
                    if folder not in {f.name for f in self._cache.folders(key)}:
                        raise ValueError(f"dossier inconnu : {folder}")
                s.select(mail.folder, write=True)
                real = self._uid_sync(s, mail, uid)
                new_uid = s.move(real, folder)
                self._cache.relocate(key, mail.folder, real, folder, new_uid)
                self._cache.recount(key, mail.folder)
                self._cache.recount(key, folder)
            return folder

        return str(await self._in_thread(key, run))

    async def _to_role(self, ref: str, role: str, missing: str) -> str:
        key, _acc, mail, _uid = self._where(ref)
        dest = self._cache.role_folder(key, role)
        if dest is None:
            await self.refresh_folders(key)
            dest = self._cache.role_folder(key, role)
        if dest is None:
            raise ValueError(missing)
        if mail.folder == dest:
            raise ValueError("il y est déjà")
        return await self.move(ref, dest)

    async def archive(self, ref: str) -> str:
        return await self._to_role(ref, "archive", "ce compte n'a pas de dossier d'archives")

    async def trash(self, ref: str) -> str:
        return await self._to_role(ref, "trash", "ce compte n'a pas de corbeille")

    async def delete(self, ref: str) -> None:
        key, acc, mail, uid = self._where(ref)
        if self._cache.role_folder(key, "trash") != mail.folder:
            raise ValueError("on ne supprime définitivement que depuis la corbeille")

        def run() -> None:
            with self._session(acc) as s:
                s.select(mail.folder, write=True)
                real = self._uid_sync(s, mail, uid)
                s.store(real, "\\Deleted", True)
                s.expunge(real)
                self._cache.forget_uids(key, mail.folder, [real])
                self._cache.recount(key, mail.folder)

        await self._in_thread(key, run)

    # ── envoyer ──
    def _sender_key(self, account: str, reply_to: str) -> str:
        accounts = self._accounts()
        if account:
            if account not in accounts:
                raise ValueError(f"compte inconnu : {account}")
            return account
        if reply_to:
            parent = self._cache.one(reply_to)
            if parent is not None and parent.account in accounts:
                return parent.account
        chosen = next((k for k, a in sorted(accounts.items()) if a.can_send), None)
        if chosen is None:
            raise RuntimeError("aucun serveur d'envoi configuré")
        return chosen

    def _preview(self, draft: Draft) -> tuple[Preview, Mail | None]:
        found = self._accounts().get(draft.account)
        parent = self._cache.one(draft.reply_to) if draft.reply_to else None
        info = found.info(draft.account) if found is not None else None
        return compose.preview(draft, info, parent, tz=self._tz), parent

    def preview(self, draft_id: str) -> Preview | None:
        found = self._cache.draft(draft_id)
        return self._preview(found)[0] if found is not None else None

    async def send(self, to: str, subject: str, body: str, in_reply_to: str = "", by: str = "", *,
                   account: str = "", cc: str = "", quote: bool = False) -> str:
        key = self._sender_key(account, in_reply_to)
        if quote and in_reply_to:
            await self.document(in_reply_to)
        draft = Draft(id="", account=key, to=to, subject=subject, body=body, cc=cc, reply_to=in_reply_to,
                      quote=quote, author=by)
        shown, parent = self._preview(draft)
        if shown.blocked:
            raise RuntimeError(shown.blocked)
        return await self._deliver(key, shown, parent, in_reply_to, by=by, draft_id="")

    async def send_draft(self, draft_id: str, *, by: str = "", digest: str = "") -> str:
        draft = self._cache.draft(draft_id)
        if draft is None:
            raise ValueError("ce brouillon n'existe plus")
        if draft.state != "brouillon":
            raise ValueError("ce brouillon est déjà parti" if draft.state == "envoye" else "ce brouillon a été abandonné")
        shown, parent = self._preview(draft)
        if shown.blocked:
            raise ValueError(shown.blocked)
        if digest and digest != shown.digest:
            raise ValueError("ce brouillon a changé depuis qu'il a été lu : relis-le avant de l'envoyer")
        message_id = await self._deliver(draft.account, shown, parent, draft.reply_to, by=by or draft.author,
                                         draft_id=draft_id)
        self._cache.mark_draft(draft_id, state="envoye", sent_id=message_id)
        return message_id

    async def _deliver(self, key: str, shown: Preview, parent: Mail | None, reply_to: str, *, by: str,
                       draft_id: str, files: tuple[File, ...] = ()) -> str:
        acc = self._account(key)
        info = acc.info(key)
        message_id = compose.new_message_id(info)
        msg = compose.message(shown, parent, message_id, when=self._now(), in_reply_to=split_ref(reply_to)[1])
        for file in files:
            if file.mime == "message/rfc822":
                msg.add_attachment(BytesParser(policy=policy.default).parsebytes(file.data), filename=file.name)
                continue
            maintype, _, subtype = file.mime.partition('/')
            msg.add_attachment(file.data, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=file.name)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._smtp_sync, acc, msg)
        # le mail est parti : plus rien ne doit le dire échoué (on le renverrait, et il arriverait deux fois)
        try:
            self._cache.remember_sent(Sent(message_id, shown.to[:300], shown.subject[:300], shown.text, self._at(),
                                           reply_to, by[:100], key, draft_id, shown.cc[:300],
                                           tuple(Attachment(f.name, f.mime, len(f.data)) for f in files)),
                                      msg.as_bytes())
        except Exception as exc:
            log.warning("courrier : envoi parti mais non retenu (%s)", type(exc).__name__)
        try:  # ranger une copie, marquer « répondu » : jamais au prix de l'envoi
            await self._in_thread(key, self._after_send_sync, key, acc, msg, parent)
        except Exception as exc:
            with contextlib.suppress(Exception):  # un cache qui ne note pas ne change rien à ce qui est parti
                self._cache.note(key, at=self._at(), error=f"envoi parti, mais copie non rangée : {_why(exc)}")
        return message_id

    def _after_send_sync(self, key: str, acc: MailAccount, msg: EmailMessage, parent: Mail | None) -> None:
        if not acc.ready or not (acc.save_sent or parent is not None):
            return
        with self._session(acc) as s:
            if acc.save_sent:
                if self._cache.role_folder(key, "sent") is None:
                    self._list_sync(s, key)
                folder = self._cache.role_folder(key, "sent")
                if folder is not None:
                    s.append(folder, msg.as_bytes(), seen=True)
            if parent is not None and parent.account == key:
                located = self._cache.located(parent.ref)
                if located is not None and located[1] > 0:
                    s.select(parent.folder, write=True)
                    s.store(located[1], "\\Answered", True)
                    self._cache.set_flags(key, parent.folder, located[1], answered=True)

    @staticmethod
    def _smtp_sync(acc: MailAccount, msg: EmailMessage) -> None:
        if not acc.smtp_host:
            raise RuntimeError("aucun serveur d'envoi configuré")
        if acc.smtp_security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(acc.smtp_host, acc.smtp_port, timeout=30,
                                                    context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(acc.smtp_host, acc.smtp_port, timeout=30)
        try:
            if acc.smtp_security == "starttls":
                server.starttls(context=ssl.create_default_context())
            user = acc.smtp_user or acc.user
            password = acc.smtp_password or acc.password
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass

    def sent_mails(self, limit: int, *, account: str = "") -> list[Sent]:
        return self._cache.sent(limit, account=account)

    def sent_mail(self, message_id: str) -> Sent | None:
        return self._cache.sent_one(message_id)

    # ── brouillons ──
    def save_draft(self, draft: Draft) -> Draft:
        now = self._at()
        if not draft.id:
            draft = replace(draft, id=f"b{uuid.uuid4().hex[:12]}", created=now)
        return self._cache.save_draft(replace(draft, updated=now))

    def draft(self, draft_id: str) -> Draft | None:
        return self._cache.draft(draft_id)

    def drafts(self, limit: int, *, state: str = "") -> list[Draft]:
        return self._cache.drafts(limit, state=state)

    def recent_edits(self, account: str, limit: int) -> list[Draft]:
        return self._cache.recent_edits(account, limit)

    def discard_draft(self, draft_id: str) -> None:
        found = self._cache.draft(draft_id)
        if found is not None and found.state == "brouillon":
            self._cache.mark_draft(draft_id, state="abandonne")

    # ── état ──
    async def test(self, account: str) -> tuple[bool, str]:
        acc = self._account(account)

        def run() -> tuple[bool, str]:
            parts, ok = [], True
            if acc.imap_host and acc.user:
                try:
                    with self._session(acc) as s:
                        found = s.folders()
                        for name, flags in found:
                            self._cache.save_folder(account, name, role=role_of(name, flags))
                        self._cache.keep_folders(account, [n for n, _ in found])
                    parts.append(f"lecture : ok ({len(found)} dossier(s))")
                except (OSError, ImapError, ValueError, EOFError) as exc:
                    ok = False
                    parts.append(f"lecture : échec — {_why(exc)}")
            else:
                ok = False
                parts.append("lecture : serveur IMAP ou utilisateur manquant")
            if acc.smtp_host:
                try:
                    self._smtp_check(acc)
                    parts.append("envoi : ok")
                except (OSError, smtplib.SMTPException) as exc:
                    ok = False
                    parts.append(f"envoi : échec — {_why(exc)}")
            else:
                parts.append("envoi : pas de serveur SMTP (elle ne pourra pas envoyer)")
            self._cache.note(account, at=self._at(), error="" if ok else "; ".join(parts))
            return ok, "; ".join(parts).capitalize() + "."

        result: tuple[bool, str] = await self._in_thread(account, run)
        return result

    @staticmethod
    def _smtp_check(acc: MailAccount) -> None:
        if acc.smtp_security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(acc.smtp_host, acc.smtp_port, timeout=15,
                                                    context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(acc.smtp_host, acc.smtp_port, timeout=15)
        try:
            if acc.smtp_security == "starttls":
                server.starttls(context=ssl.create_default_context())
            user = acc.smtp_user or acc.user
            password = acc.smtp_password or acc.password
            if user and password:
                server.login(user, password)
        finally:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass

    def status(self, account: str) -> AccountStatus:
        return self._cache.status(account)

    def close(self) -> None:
        self._cache.close()


def _why(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text[:200]
