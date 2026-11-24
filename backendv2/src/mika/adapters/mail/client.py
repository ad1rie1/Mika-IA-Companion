"""Le courrier réel : IMAP pour lire et ranger, SMTP pour envoyer (bibliothèque
standard, dans un fil), un cache à part pour ce qui est arrivé (sa base, ADR 0101).

- **Plusieurs comptes**, chacun avec ses dossiers relevés ; une panne sur un
  compte n'empêche pas de relever les autres (elle est notée : la console la
  montre).
- **Chaque mail est rendu jusqu'à son accusé** (``fetch_new`` puis ``ack``),
  puis plus jamais, même s'il change de dossier : un relevé interrompu avant
  d'avoir remarqué ses mails les retrouve au suivant ; au premier relevé d'un
  dossier, on ne remonte que quelques jours.
- **Un client complet** : lu/non lu, suivi, déplacer, archiver, corbeille —
  sur le serveur, et le cache suit.
- **Ses pièces sont gardées avec lui** (ADR 0172) : le relevé lit chaque mail
  entier ; ses pièces jointes et ses images intégrées vont au cache. Télécharger
  ou transférer une pièce gardée ne demande pas le serveur ; un mail gardé avant
  se relit (``reread``) pour garder les siennes.
- **Ce qui part** est mis en forme par ``compose`` (l'expéditeur selon la voix
  du compte, sa signature, la citation) ; un brouillon ne part que tel qu'il
  a été lu (le condensé de l'aperçu).
- La configuration est relue à chaque appel (changer de compte ne demande pas
  de redémarrer).
- **Une boîte Microsoft** (Hotmail, Outlook.com) entre par XOAUTH2 : avant
  chaque session, le jeton d'accès de sa connexion (``oauth``, ADR 0166) ; une
  boîte pas (ou plus) connectée échoue comme un serveur qui refuse, en le disant.
- **Ce qui vient d'avant** (son historique, ``older`` et ``keep_history`` ; ce
  qu'une recherche ramène du serveur, ``search_server``) n'est jamais rendu par
  ``fetch_new`` : son tri ne lit que ce qui arrive (ADR 0249). Seul un mail d'un
  dossier relevé que la relève n'a pas encore atteint reste à lui rendre.
- **Ranger n'est pas remarquer** (ADR 0308) : ranger un dossier relevé garde
  chaque mail neuf et le met en attente de son tri (``offer``) ; ``fetch_new``
  rend ce qui attend, et seul l'accusé (``ack``) le retire. Le courrier en
  direct (``idle``) range donc à toute heure (``range_box``) sans rien lui
  rendre : sa relève suivante le lui donne une fois. Ce qui a été lu ailleurs
  attend de même, gardé dans le cache (``seen_elsewhere``).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import smtplib
import ssl
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Protocol

from mika.adapters.changes import Listener
from mika.adapters.database import Target
from mika.adapters.mail import compose
from mika.adapters.mail.cache import MailCache
from mika.adapters.mail.config import MailAccount, MailConfig
from mika.adapters.mail.imap import ImapError, Session, role_of, since
from mika.adapters.mail.models import sent_name
from mika.adapters.mail.oauth import MicrosoftSignIn, OAuthError, answer
from mika.adapters.mail.parse import Part, attachment_files, parse, parse_parts
from mika.contracts.email import HANDLE_PREFIX
from mika.ports.mail import (
    ASIDE,
    PIECES_MAX,
    PIECES_TOTAL_MAX,
    AccountInfo,
    AccountStatus,
    Attachment,
    Draft,
    File,
    Folder,
    Found,
    Mail,
    MailQuery,
    Moved,
    Preview,
    Sent,
    SignIn,
    forwarded_text,
    split_ref,
)
from mika.ports.paging import written_words

log = logging.getLogger("mika.mail")

#: l'attente d'une commande SMTP ; l'envoi du mail lui-même a un délai à sa mesure (``compose.transfer_timeout``)
SMTP_TIMEOUT = 30.0

#: les derniers mails d'un dossier relevé dont on relit les drapeaux (lus ailleurs ?)
FLAGS_WINDOW = 200
#: « tous les dossiers » : ce qu'un dossier seulement synchronisé (pas relevé) range au plus à chaque relève
SYNC_ALL_BATCH = 50
#: le courrier en direct (ADR 0308) : ce qu'un passage range au plus par dossier relevé, avant de rendre le verrou de
#: la boîte à ses outils (un autre passage suit aussitôt s'il en reste)
LIVE_BATCH = 25
#: une lecture de l'historique ou d'une recherche lit les mails par paquets : jamais plus en mémoire à la fois
HISTORY_CHUNK = 10
#: un passage de l'historique ne commence plus de paquet au-delà (s) : le verrou de la boîte se rend vite
HISTORY_SLICE_S = 20.0
#: une recherche sur le serveur : au plus autant de dossiers, et, par dossier, les en-têtes des plus récents qui
#: correspondent sans être ici
SEARCH_FOLDERS = 40
SEARCH_HEADS = 200
#: le nom d'un dossier qu'elle crée (son chemin, « / » compris)
FOLDER_NAME_MAX = 200
#: les expéditeurs dont les images distantes s'affichent d'emblée (ADR 0175) : au plus autant, les plus récents
IMAGES_FROM_MAX = 500


class ImagesFrom(Protocol):
    """Où se gardent les expéditeurs dont on affiche les images distantes (les réglages)."""

    def mail_images(self) -> tuple[str, ...]: ...

    async def save_mail_images(self, addresses: tuple[str, ...]) -> None: ...


def _local_tz() -> tzinfo:
    return datetime.now().astimezone().tzinfo or UTC


def _check_added_pieces(carried: Sequence[File], added: Sequence[File]) -> None:
    """Des fichiers ajoutés à un transfert : les bornes d'un mail comptent aussi les pièces qu'il reprend, que seul ce
    module connaît (ADR 0214)."""
    way_out = "retire des fichiers, ou transfère-le sans ses pièces."
    if len(carried) + len(added) > PIECES_MAX:
        raise ValueError(f"Avec les pièces du mail d'origine, il en porterait plus de {PIECES_MAX} : {way_out}")
    if sum(len(f.data) for f in (*carried, *added)) > PIECES_TOTAL_MAX:
        raise ValueError(f"Avec les pièces du mail d'origine, il pèserait plus de "
                         f"{PIECES_TOTAL_MAX // (1024 * 1024)} Mo : {way_out}")


class ImapSmtpMail:
    def __init__(self, config: Callable[[], MailConfig], cache: Path | Target, *,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC), tz: tzinfo | None = None,
                 timeout: float = 30.0, her: Callable[[], str] | None = None,
                 microsoft: MicrosoftSignIn | None = None, images: ImagesFrom | None = None) -> None:
        self._config = config
        #: les expéditeurs dont les images s'affichent (sans endroit où les garder, aucun)
        self._images = images
        #: son nom d'expéditrice quand un compte n'en dit pas : celui de sa persona, que l'application fournit
        self._her = her or (lambda: compose.DEFAULT_NAME)
        self._now = now
        self._tz = tz or _local_tz()
        self._timeout = timeout
        self._cache = MailCache(cache)
        self._locks: dict[str, asyncio.Lock] = {}
        #: les connexions Microsoft (sans endroit où garder leur jeton, aucune boîte Microsoft n'entre)
        self._microsoft = microsoft or MicrosoftSignIn()
        #: par compte, le jeton d'accès de la session qui va s'ouvrir (posé sous le verrou du compte)
        self._bearers: dict[str, str] = {}
        #: les boîtes que le courrier en direct observe (ADR 0308 ; ``MailWatch``) : leur panne est la sienne — une
        #: seule règle, pas un marqueur qui bascule entre lui et la relève ; la relève y range encore, sans dire de
        #: panne ni en effacer une
        self.observed: frozenset[str] = frozenset()

    def on_change(self, fn: Listener) -> None:
        """Prévenir ``fn`` de chaque écriture du courrier relevé, une fois validée (ADR 0308 : ``MailCache.on_change``)
        — relève, drapeaux, dossiers, envois, brouillons, oubli. Appelé dans le fil qui a écrit."""
        self._cache.on_change(fn)

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
            found = self._accounts().get(key)
            self._bearers[key] = await self._bearer(key, found) if found is not None else ""
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, fn, *args)

    async def _bearer(self, key: str, account: MailAccount) -> str:
        """Le jeton d'accès d'une boîte Microsoft (``OAuthError`` si elle n'est pas connectée) ; rien pour les autres."""
        return await self._microsoft.token(key, account) if account.microsoft else ""

    def _session(self, key: str, account: MailAccount) -> Session:
        return Session(account, timeout=self._timeout, token=self._bearers.get(key, ""))

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
            except (OSError, ImapError, OAuthError, ValueError, EOFError) as exc:
                if key not in self.observed:  # observée en direct : sa panne est celle du direct
                    self._cache.note(key, at=self._at(), error=_why(exc), polled=True)
                log.warning("courrier : relevé de %s impossible (%s)", key, type(exc).__name__)
            # ce qui attend son accusé : ce relevé-ci (même si un dossier suivant a échoué), ce que le direct a rangé
            # depuis (ADR 0308), ou un passage interrompu avant d'avoir remarqué ce qu'on lui avait rendu
            out.extend(self._cache.offered(key, share))
        return out[:limit]

    def ack(self, refs: Sequence[str]) -> None:
        self._cache.ack(refs)

    def waiting(self) -> frozenset[str]:
        return self._cache.offered_refs()

    def seen_elsewhere(self) -> list[str]:
        return self._cache.take_seen_elsewhere()

    def _poll_sync(self, key: str, account: MailAccount, limit: int) -> list[Mail]:
        out: list[Mail] = []
        with self._session(key, account) as s:
            # la liste se relit à chaque relève : un dossier créé ailleurs paraît, un dossier disparu s'en va (lue
            # une seule fois, elle restait figée dès qu'un dossier était connu — souvent la seule réception)
            self._list_sync(s, key)
            for folder in account.folders:
                if len(out) >= limit:
                    break
                out += self._sync_sync(s, key, account, folder, limit - len(out), hand=True)[0]
            if account.sync_all or account.keep_all:
                # les autres dossiers sont tenus à jour pour la console, sans rien lui rendre : elle ne remarque que
                # ceux qu'elle relève ; tout garder en local laisse à part les indésirables et la corbeille (ADR 0249)
                for f in self._cache.folders(key):
                    if f.name in account.folders or (not account.sync_all and f.role in ASIDE):
                        continue
                    try:
                        self._sync_sync(s, key, account, f.name, SYNC_ALL_BATCH, hand=False)
                    except ImapError as exc:  # un dossier que le serveur refuse n'arrête pas les suivants
                        log.warning("courrier : dossier %s/%s non synchronisé (%s)", key, f.name, type(exc).__name__)
        self._cache.note(key, at=self._at(), polled=True, clears=key not in self.observed)
        return out

    def _list_sync(self, s: Session, key: str) -> None:
        found = s.folders()
        for name, flags in found:
            self._cache.save_folder(key, name, role=role_of(name, flags))
        self._cache.keep_folders(key, [n for n, _ in found])

    def _read(self, raw: bytes, uid: int, key: str, folder: str,
              flags: frozenset[str]) -> tuple[Mail, tuple[Part, ...]]:
        """Un mail brut lu, et ses pièces (que le cache garde avec lui, ADR 0172) ; un mail que la lecture ne
        comprend pas devient une ligne qui le dit (on ne le relira pas à chaque relevé : il est rangé, et le curseur
        passe)."""
        try:
            mail, parts = parse_parts(raw, str(uid), account=key, folder=folder, complete=True)
        except Exception as exc:  # un mail hostile ou cassé n'arrête jamais un relevé
            log.warning("courrier : un mail illisible dans %s/%s (%s)", key, folder, type(exc).__name__)
            mail, parts = Mail(f"<illisible-{hashlib.sha256(raw).hexdigest()[:20]}@mika>", "(expéditeur illisible)",
                               "", "(un mail illisible)", 0, "Ce mail n'a pas pu être lu.", account=key,
                               folder=folder), ()
        return replace(mail, seen="\\seen" in flags, flagged="\\flagged" in flags,
                       answered="\\answered" in flags), parts

    def _sync_sync(self, s: Session, key: str, account: MailAccount, folder: str, limit: int, *,
                   hand: bool) -> tuple[list[Mail], bool]:
        """Relit un dossier : ce qui est nouveau (au plus ``limit``), puis les drapeaux
        des derniers mails connus. Rend les mails nouveaux jamais rendus (``hand``), et
        s'il en reste de nouveaux au-delà de ``limit``.

        Le curseur avance **mail après mail** : un relevé interrompu reprend après le dernier mail
        rangé, et un mail illisible ne revient pas à chaque relevé. Relu depuis la console
        (``hand`` faux), un dossier qu'elle relève garde le curseur de la relève : ce que la
        console vient de ranger, elle le remarquera quand même au prochain relevé. Ce que le
        dossier range se dit une fois, à la fin (ADR 0308), pas mail par mail."""
        with self._cache.held():
            return self._synced(s, key, account, folder, limit, hand=hand)

    def _synced(self, s: Session, key: str, account: MailAccount, folder: str, limit: int, *,
                hand: bool) -> tuple[list[Mail], bool]:
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
            mail, parts = self._read(raw, uid, key, folder, flags)
            stored = self._cache.store(mail, uid, parts)
            local = split_ref(stored.ref)[1]
            if hand and not self._cache.handed(key, local):
                self._cache.offer(key, stored.ref)  # rendu pour de bon à l'accusé (``ack``), pas avant
                out.append(stored)
            if owns_cursor:
                self._cache.save_folder(key, folder, uidvalidity=validity or None, uidnext=uid + 1)
        if not hand:
            for uid, flags, raw in s.fetch(self._cache.missing_html(key, folder, limit)):
                mail, parts = self._read(raw, uid, key, folder, flags)
                self._cache.store(mail, uid, parts)
        nxt = (max(taken) + 1) if len(taken) < len(uids) else max(uidnext, (max(taken) + 1) if taken else start)
        self._refresh_flags(s, key, folder, hand=hand)
        if owns_cursor:
            self._cache.save_folder(key, folder, uidvalidity=validity or None, uidnext=nxt or None,
                                    last_sync=self._at())
        else:
            self._cache.save_folder(key, folder, last_sync=self._at())
        self._cache.recount(key, folder)
        return out, len(taken) < len(uids)

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
            # su même quand c'est la console (ou le direct) qui relit : la relève suivante ne le reverrait plus
            # changer — gardé jusqu'à ce qu'elle le lise, même si elle dort, même après un redémarrage
            if seen and not was_seen and ref:
                self._cache.seen_elsewhere(key, ref)

    # ── le direct (ADR 0308) ──
    def watched(self) -> dict[str, MailAccount]:
        """Les boîtes que le courrier en direct observe : celles prêtes à relever, telles que réglées à l'instant."""
        return {k: a for k, a in sorted(self._accounts().items()) if a.ready}

    async def watch_token(self, key: str, account: MailAccount) -> str:
        """Le jeton d'une session du direct : celui d'une boîte Microsoft, renouvelé comme pour la relève (``OAuthError``
        si elle n'est pas connectée) ; rien pour les autres."""
        return await self._bearer(key, account)

    def watch_session(self, account: MailAccount, token: str) -> Session:
        """Une session à part, pour attendre (``Session.wait``) : hors du verrou de la boîte, que ses outils et sa
        relève gardent. Bloquante (dans un fil)."""
        return Session(account, timeout=self._timeout, token=token)

    async def range_box(self, key: str, *, session: Session | None = None) -> bool:
        """Range dans le courrier relevé ce qui est arrivé dans les dossiers relevés de cette boîte, et les drapeaux qui
        ont changé — au plus ``LIVE_BATCH`` mails par dossier, sous le verrou de la boîte —, sans rien lui rendre :
        chaque mail neuf attend son tri (``offer``), et sa relève le lui donnera une fois (``fetch_new``). Un passage
        réussi compte comme une relève (``AccountStatus.last_poll``). Rend vrai quand tout est rangé, faux s'il en
        reste (un autre passage suit, le verrou rendu entre deux) ; une boîte retirée ou coupée n'a rien à ranger. Une
        panne se lève (``OSError``, ``ImapError``, ``OAuthError``…) : qui observe la note (``watch_failed``).
        ``session`` : une connexion à qui observe (``watch_session``), gardée d'un passage à l'autre et refermée par
        lui ; sans elle, chaque passage ouvre la sienne."""
        account = self._accounts().get(key)
        if account is None or not account.ready:
            return True
        return bool(await self._in_thread(key, self._range_sync, key, account, session))

    def _range_sync(self, key: str, account: MailAccount, given: Session | None) -> bool:
        done = True
        with contextlib.nullcontext(given) if given is not None else self._session(key, account) as s:
            for folder in account.folders:
                _handed, more = self._sync_sync(s, key, account, folder, LIVE_BATCH, hand=True)
                done = done and not more
        self._cache.note(key, at=self._at(), polled=True)
        return done

    def watch_failed(self, key: str, exc: BaseException) -> str:
        """Une panne du direct sur cette boîte (serveur muet, accès refusé, boîte Microsoft à reconnecter), notée comme
        une relève manquée : la console et les écrans la montrent. Rend ce qui s'en dit ; une boîte retirée entre-temps
        n'a plus d'état à tenir."""
        why = _why(exc)
        if key in self._accounts():
            self._cache.note(key, at=self._at(), error=why, polled=True)
        return why

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

    def correspondents_since(self, cursor: tuple[int, int], limit: int):
        return self._cache.correspondents_since(cursor, limit, {a.key: a.address for a in self.accounts()})

    def exchanged(self, since: int, *, limit: int = 2000, accounts=None):
        return self._cache.exchanged(since, limit, {a.key: a.address for a in self.accounts()}, accounts)

    def letters_from(self, address: str, *, since: int = 0, limit: int = 30, accounts=None):
        return self._cache.letters_from(address, since, limit, accounts)

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
            msg['From'] = compose.sender(self._account(sent.account).info(sent.account), self._her())
            msg['To'], msg['Subject'], msg['Message-ID'] = sent.to, sent.subject, split_ref(sent.message_id)[1]
            msg.set_content(sent.body)
            return msg.as_bytes()
        key, acc, mail, uid = self._where(ref)
        def read():
            with self._session(key, acc) as session:
                _, validity, _ = session.select(mail.folder)
                previous, _ = self._cache.cursor(key, mail.folder) or (0, 0)
                if validity and previous and validity != previous:
                    raise ValueError("Le dossier a changé sur le serveur. Actualise-le avant de relire ce message.")
                actual = self._uid_sync(session, mail, uid)
                rows = session.fetch([actual])
                if not rows:
                    raise FileNotFoundError("Ce message n'est plus disponible sur le serveur.")
                number, flags, raw = rows[0]
                full, parts = parse_parts(raw, str(number), account=key, folder=mail.folder, complete=True)
                if full.message_id != mail.message_id:
                    raise ValueError("Ce message a changé sur le serveur. Actualise le dossier.")
                self._cache.store(replace(full, seen="\\seen" in flags, flagged="\\flagged" in flags,
                                           answered="\\answered" in flags), number, parts)
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
        found = parse(raw, account=sent.account if sent else "", complete=True)
        # sa source ne porte plus ses pièces (leurs octets sont à part, ADR 0214) : sa ligne les liste
        return replace(found, attachments=sent.attachments) if sent is not None and sent.attachments else found

    async def file(self, ref: str, part: str) -> File:
        if part == "texte":
            full = await self.document(ref)
            if full is None:
                raise FileNotFoundError("Ce message n'est plus disponible.")
            return File("message.txt", "text/plain", full.body.encode())
        if part.isdecimal() and len(part) <= 5:
            kept = self._cache.part(ref, int(part))  # gardée à son arrivée (ADR 0172) : le serveur n'est pas requis
            if kept is not None:
                return kept
        raw = await self._source(ref)
        if part == "source":
            return File("message.eml", "message/rfc822", self._with_pieces(ref, raw))
        if not part.isdecimal() or len(part) > 5:
            raise FileNotFoundError("Pièce jointe inconnue.")
        files = attachment_files(raw)
        if int(part) >= len(files):
            raise FileNotFoundError("Cette pièce jointe n'est plus disponible.")
        return files[int(part)]

    def _with_pieces(self, ref: str, raw: bytes) -> bytes:
        """Un envoi entier : ses pièces, gardées à part (ADR 0214), remises dans sa source ; tel quel s'il en manque une."""
        sent = self._cache.sent_one(ref)
        files = self._cache.files(ref, len(sent.attachments)) if sent is not None and sent.attachments else None
        if not files:
            return raw
        msg = BytesParser(policy=policy.default).parsebytes(raw)
        compose.attach(msg, files)
        return msg.as_bytes()

    async def reread(self, ref: str) -> Mail | None:
        """Relit un mail reçu sur le serveur et le garde entier, pièces comprises (un mail gardé avant qu'elles le
        soient, ADR 0172) ; un envoi se relit comme ``document``."""
        if self._cache.one(ref) is None:
            return await self.document(ref)
        await self._source(ref)
        return self._cache.one(ref)

    def inline_images(self, ref: str) -> tuple[tuple[str, str, bytes], ...]:
        return self._cache.inline(ref)

    async def forward(self, ref, to, subject, body, *, cc="", by="", attachments=True, bcc="", files=()):
        original = await self.document(ref)
        if original is None:
            raise ValueError("Ce message n'est plus disponible.")
        carried = self._cache.files(ref, len(original.attachments)) if attachments and original.attachments else ()
        if carried is None:  # une pièce n'est pas gardée ici : le message se relit sur le serveur
            carried = attachment_files(await self._source(ref))
            if len(carried) < len(original.attachments):  # un envoi dont les octets ont été cédés (ADR 0214)
                raise ValueError("Une de ses pièces n'est plus gardée ici : transfère-le sans ses pièces.")
        if files:  # sans ajout, un transfert reste ce qu'il était, même d'un mail au-delà de ces bornes
            _check_added_pieces(carried, files)
        key = self._sender_key(original.account, "")
        draft = Draft("", key, to, subject, forwarded_text(original, body), cc=cc, author=by)
        shown, _ = self._preview(draft)
        if shown.blocked:
            raise ValueError(shown.blocked)
        return await self._deliver(key, shown, None, "", by=by, draft_id="", files=(*carried, *files), bcc=bcc)

    def search(self, text: str, limit: int, *, account: str = "") -> list[Mail]:
        return self._cache.search(text, limit, account=account) if text.strip() else []

    # ── dossiers ──
    def folders(self, account: str) -> list[Folder]:
        found = self._accounts().get(account)
        return self._cache.folders(account, found.folders if found is not None else ())

    async def refresh_folders(self, account: str) -> list[Folder]:
        acc = self._account(account)

        def run() -> None:
            with self._session(account, acc) as s:
                self._list_sync(s, account)

        await self._in_thread(account, run)
        return self.folders(account)

    async def sync_folder(self, account: str, folder: str, limit: int) -> int:
        acc = self._account(account)

        def run() -> int:
            before = self._cache.folder_count(account, folder)
            with self._session(account, acc) as s:
                self._sync_sync(s, account, acc, folder, limit, hand=False)
            return max(0, self._cache.folder_count(account, folder) - before)

        return int(await self._in_thread(account, run))

    async def older(self, account: str, folder: str, limit: int = 50) -> int:
        acc = self._account(account)

        def run() -> int:
            with self._session(account, acc) as session:
                return self._history_sync(session, account, acc, folder, max(1, min(100, limit)))

        return int(await self._in_thread(account, run))

    def _hands(self, key: str, account: MailAccount, folder: str, uid: int) -> bool:
        """Un mail ramené d'avant (son historique, une recherche) est-il rendu pour de bon, jamais remarqué comme
        arrivé ? Seulement dans un dossier relevé, sous ce que la relève a déjà atteint : au-dessus, il vient
        d'arriver, son tri le lira. Ailleurs, rien n'est rendu : « rendu » vaut pour le mail dans toute la boîte, et sa
        copie dans un dossier relevé (Gmail : « Tous les messages » et la réception) doit encore être triée si elle
        vient d'arriver (ADR 0249)."""
        if folder not in account.folders:
            return False
        reached = (self._cache.cursor(key, folder) or (0, 0))[1]
        return 0 < uid < reached

    def _keep(self, s: Session, key: str, account: MailAccount, folder: str, uids: list[int]) -> int:
        """Lit et garde ces mails du dossier ouvert, par paquets ; rend combien sont gardés (un correspondant oublié
        ne l'est pas)."""
        kept = 0
        for at in range(0, len(uids), HISTORY_CHUNK):
            for uid, flags, raw in s.fetch(uids[at:at + HISTORY_CHUNK]):
                mail, parts = self._read(raw, uid, key, folder, flags)
                stored = self._cache.store(mail, uid, parts)
                kept += bool(stored.key)
                if self._hands(key, account, folder, uid):
                    self._cache.hand(key, split_ref(stored.ref)[1])
        return kept

    def _history_sync(self, s: Session, key: str, account: MailAccount, folder: str, limit: int,
                      until: float | None = None) -> int:
        """Remonte l'historique d'un dossier : jusqu'à ``limit`` mails du serveur qui ne sont pas ici, sous le
        plancher de la lecture précédente (la première : tout le dossier, pour les trous que la fenêtre du premier
        relevé laisse), les plus récents d'abord ; ``until`` (``time.monotonic``) : on ne commence plus de paquet
        au-delà. Le dossier est complet quand il n'y en a plus. Rend combien ont été lus. Ce qu'un passage range se
        dit une fois, à sa fin (ADR 0308) : une boîte « tout garder » ne fait pas relire les écrans à chaque mail."""
        with self._cache.held():
            return self._history_of(s, key, account, folder, limit, until)

    def _history_of(self, s: Session, key: str, account: MailAccount, folder: str, limit: int,
                    until: float | None) -> int:
        _, validity, _ = s.select(folder)
        previous, _ = self._cache.cursor(key, folder) or (0, 0)
        if previous and validity and previous != validity:
            raise ValueError("Le dossier a changé sur le serveur : actualise-le avant de charger son historique.")
        floor = self._cache.history_floor(key, folder)
        found = [] if floor == 1 else [u for u in s.search(f"UID 1:{floor - 1}" if floor else "ALL")
                                        if not floor or u < floor]
        here = self._cache.known_uids(key, folder, found)
        uids = sorted(u for u in found if u not in here)
        taken = uids[-max(0, limit):] if limit > 0 else []
        read = 0
        # les plus récents d'abord, et le plancher après chaque paquet : une lecture coupée reprend où elle en était
        for at in range(len(taken), 0, -HISTORY_CHUNK):
            if until is not None and read and time.monotonic() > until:
                break
            chunk = taken[max(0, at - HISTORY_CHUNK):at]
            self._keep(s, key, account, folder, chunk)
            read += len(chunk)
            self._cache.save_folder(key, folder, uidvalidity=validity or None, floor=min(chunk))
        self._cache.save_folder(key, folder, uidvalidity=validity or None, complete=read == len(uids))
        self._cache.recount(key, folder)
        return read

    async def keep_history(self, account: str, limit: int) -> int:
        acc = self._accounts().get(account)
        if acc is None or not acc.ready or not acc.keep_all or limit <= 0:
            return 0

        def wanted() -> list[str]:
            return [f.name for f in self._cache.folders(account, acc.folders) if f.role not in ASIDE and not f.complete]

        if not wanted():  # tout est là : pas de connexion (un dossier nouveau paraît à la relève suivante)
            return 0

        def run() -> int:
            # une tranche courte : le verrou de la boîte n'est tenu que le temps d'un passage, ses outils attendent peu
            until, read = time.monotonic() + HISTORY_SLICE_S, 0
            with self._session(account, acc) as s:
                self._list_sync(s, account)
                for name in wanted():
                    if read >= limit or (read and time.monotonic() > until):
                        break
                    try:
                        read += self._history_sync(s, account, acc, name, limit - read, until)
                    except (ImapError, ValueError) as exc:  # un dossier refusé, ou changé : les suivants passent
                        log.info("courrier : historique de %s/%s remis (%s)", account, name, type(exc).__name__)
            return read

        try:
            return int(await self._in_thread(account, run))
        except (OSError, ImapError, OAuthError, ValueError, EOFError) as exc:
            if account not in self.observed:  # observée en direct : sa panne est celle du direct
                self._cache.note(account, at=self._at(), error=_why(exc))
            log.warning("courrier : historique de %s impossible (%s)", account, type(exc).__name__)
            return 0

    async def search_server(self, query: MailQuery, want: int) -> Found:
        key = query.account
        acc = self._account(key)
        if not acc.ready:
            raise ValueError("cette boîte n'est pas prête à relever")
        words, senders = written_words(query.text), written_words(query.sender)
        if not words and not senders:
            return Found()

        def run() -> Found:
            # ce qu'elle ramène se dit une fois, à la fin (ADR 0308)
            with self._cache.held(), self._session(key, acc) as s:
                self._list_sync(s, key)
                roles = {f.name: f.role for f in self._cache.folders(key, acc.folders)}
                names = [query.folder] if query.folder else [n for n, role in roles.items() if role not in ASIDE]
                skipped = names[SEARCH_FOLDERS:]  # au-delà : dit, pas tu
                missing: list[tuple[int, int, str]] = []  # (arrivée, uid, dossier) de ce qui manque ici
                beyond = 0  # ce qui correspond au-delà des en-têtes lus : compté, sans être daté
                ids: set[str] = set()
                validities: dict[str, int] = {}
                for name in names[:SEARCH_FOLDERS]:
                    try:
                        _, validity, _ = s.select(name)
                        previous = (self._cache.cursor(key, name) or (0, 0))[0]
                        if previous and validity and previous != validity:
                            skipped.append(name)  # ses UID ne disent plus la même chose ici : la relève le relira
                            continue
                        found = s.matching(words, senders)
                        here = self._cache.known_uids(key, name, found)
                        fresh = [u for u in found if u not in here]
                        beyond += max(0, len(fresh) - SEARCH_HEADS)
                        heads = s.heads(fresh[-SEARCH_HEADS:]) if fresh else []
                    except ImapError as exc:  # un dossier refusé n'arrête pas les suivants
                        log.info("courrier : recherche dans %s/%s refusée (%s)", key, name, type(exc).__name__)
                        skipped.append(name)
                        continue
                    validities[name] = validity
                    sent = roles.get(name) == "sent" or sent_name(name)
                    known = self._cache.known_ids(key, [h.message_id for h in heads])
                    for h in heads:
                        if h.message_id and (h.message_id in known or h.message_id in ids):
                            continue  # le même mail, gardé ou trouvé dans un autre dossier
                        if self._cache.forgotten(h.sender, h.at, recipients=h.recipients if sent else ()):
                            continue  # un correspondant oublié : ni relu, ni compté
                        if h.message_id:
                            ids.add(h.message_id)
                        missing.append((h.at, h.uid, name))
                missing.sort(reverse=True)
                chosen = missing[:max(0, want)]
                kept = 0
                for name in dict.fromkeys(n for _, _, n in chosen):
                    s.select(name)
                    if validities.get(name):  # ce qui est gardé d'un dossier jamais relu dit à quels UID il croit
                        self._cache.save_folder(key, name, uidvalidity=validities[name])
                    kept += self._keep(s, key, acc, name, sorted((u for _, u, n in chosen if n == name), reverse=True))
                    self._cache.recount(key, name)
                return Found(kept=kept, left=len(missing) - len(chosen) + beyond, skipped=tuple(skipped))

        return await self._in_thread(key, run)  # type: ignore[no-any-return]

    async def create_folder(self, account: str, name: str) -> str:
        acc = self._account(account)
        wanted = name.strip()
        if not wanted or len(wanted) > FOLDER_NAME_MAX or not wanted.isprintable():
            raise ValueError("un nom de dossier : des mots, « / » pour un sous-dossier, 200 caractères au plus")

        def listed(full: str) -> str | None:
            # la liste rend la réception comme le serveur l'écrit (« Inbox/Factures » chez Outlook) : sans casse
            return next((f.name for f in self._cache.folders(account) if f.name.casefold() == full.casefold()), None)

        def run() -> str:
            with self._session(account, acc) as s:
                self._list_sync(s, account)
                if wanted in {f.name for f in self._cache.folders(account)}:
                    return wanted
                prefix, delim = s.root()
                rest = wanted[len(prefix):] if prefix and wanted.startswith(prefix) else wanted
                # « / » sépare un sous-dossier, comme le séparateur du serveur (un nom ne peut pas le porter)
                parts = [p.strip() for p in rest.replace(delim, "/").split("/")]
                if not all(parts):
                    raise ValueError("un nom de dossier : des mots, « / » pour un sous-dossier, rien de vide entre deux")
                path = delim.join(parts)
                full = path if path.upper() == "INBOX" else prefix + path
                there = listed(full)
                if there is not None:
                    return there
                s.create(full)
                self._list_sync(s, account)
                there = listed(full)
                if there is None:
                    raise ValueError(f"le serveur n'a pas créé « {full} »")
                return there

        return str(await self._in_thread(account, run))

    # ── ranger ──
    def _where(self, ref: str) -> tuple[str, MailAccount, Mail, int]:
        found = self._cache.located(ref)
        if found is None:
            raise ValueError("ce mail n'est plus dans le cache")
        mail, uid = found
        return mail.account, self._account(mail.account), mail, uid

    def _uid_sync(self, s: Session, mail: Mail, uid: int) -> int:
        """L'UID d'un mail que le cache tient à une place provisoire (déplacé sans que le serveur ait dit son nouvel
        UID) : demandé au serveur par son Message-ID."""
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
            with self._session(key, acc) as s:
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
                with self._session(key, acc) as s:
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
            except (OSError, ImapError, OAuthError, ValueError, EOFError) as exc:
                failed += sum(len(v) for v in folders.values())
                self._cache.note(key, at=self._at(), error=_why(exc))
        return failed

    async def move(self, ref: str, folder: str) -> str:
        key, acc, mail, uid = self._where(ref)
        if folder == mail.folder:
            return folder

        def run() -> str:
            with self._session(key, acc) as s:
                known = {f.name for f in self._cache.folders(key)}
                if folder not in known:
                    self._list_sync(s, key)
                    if folder not in {f.name for f in self._cache.folders(key)}:
                        raise ValueError(f"dossier inconnu : {folder}")
                s.select(mail.folder, write=True)
                self._move_sync(s, key, mail, uid, folder)
                self._cache.recount(key, mail.folder)
                self._cache.recount(key, folder)
            return folder

        return str(await self._in_thread(key, run))

    def _move_sync(self, s: Session, key: str, mail: Mail, uid: int, dest: str) -> None:
        """Un mail du dossier ouvert déplacé dans ``dest`` ; le cache le suit (à son UID d'arrivée, s'il est dit)."""
        real = self._uid_sync(s, mail, uid)
        new_uid = s.move(real, dest)
        self._cache.relocate(key, mail.folder, real, dest, new_uid)

    async def _to_role(self, ref: str, role: str) -> str:
        key, _acc, mail, _uid = self._where(ref)
        dest = await self._role_folder(key, role)
        if mail.folder == dest:
            raise ValueError("il y est déjà")
        return await self.move(ref, dest)

    async def archive(self, ref: str) -> str:
        return await self._to_role(ref, "archive")

    async def trash(self, ref: str) -> str:
        return await self._to_role(ref, "trash")

    async def move_many(self, refs: Sequence[str], *, folder: str = "", role: str = "") -> Moved:
        """Par lot (ADR 0302) : une session par compte, chaque dossier de départ ouvert une fois, un ``MOVE`` par mail
        (chacun garde son UID d'arrivée). Ce qui est fait le reste quand la connexion tombe en route : seul ce qui
        restait à faire dans cette boîte est refusé."""
        if bool(folder) == bool(role):
            raise ValueError("un dossier ou un rôle, l'un des deux")
        done: dict[str, str] = {}
        refused: dict[str, str] = {}
        by_account: dict[str, list[tuple[str, Mail, int]]] = {}
        for ref in dict.fromkeys(refs):
            found = self._cache.located(ref)
            if found is None:
                refused[ref] = "ce mail n'est plus dans le cache"
            else:
                by_account.setdefault(found[0].account, []).append((ref, *found))
        for key, items in by_account.items():
            acc = self._accounts().get(key)
            if acc is None:
                refused.update((ref, f"compte inconnu : {key}") for ref, _m, _u in items)
                continue
            try:
                dest = folder or await self._role_folder(key, role)
            except (OSError, ImapError, OAuthError, ValueError, EOFError) as exc:
                refused.update((ref, _why(exc)) for ref, _m, _u in items)
                continue
            todo: dict[str, list[tuple[str, Mail, int]]] = {}
            for ref, mail, uid in items:
                if mail.folder != dest:
                    todo.setdefault(mail.folder, []).append((ref, mail, uid))
                elif role:
                    refused[ref] = "il y est déjà"
                else:
                    done[ref] = dest
            if not todo:
                continue

            def run(acc: MailAccount = acc, key: str = key, dest: str = dest,
                    todo: dict[str, list[tuple[str, Mail, int]]] = todo) -> None:
                touched: set[str] = set()
                try:
                    with self._session(key, acc) as s:
                        if dest not in {f.name for f in self._cache.folders(key)}:
                            self._list_sync(s, key)
                            if dest not in {f.name for f in self._cache.folders(key)}:
                                raise ValueError(f"dossier inconnu : {dest}")
                        for source, group in todo.items():
                            try:
                                s.select(source, write=True)
                            except ImapError as exc:
                                refused.update((ref, _why(exc)) for ref, _m, _u in group)
                                continue
                            for ref, mail, uid in group:
                                try:
                                    self._move_sync(s, key, mail, uid, dest)
                                except (ImapError, ValueError) as exc:
                                    refused[ref] = _why(exc)
                                else:
                                    done[ref] = dest
                                    touched.add(source)
                finally:
                    for name in touched | ({dest} if touched else set()):
                        self._cache.recount(key, name)

            try:
                await self._in_thread(key, run)
            except (OSError, ImapError, OAuthError, ValueError, EOFError) as exc:
                left = [ref for group in todo.values() for ref, _m, _u in group if ref not in done and ref not in refused]
                refused.update((ref, _why(exc)) for ref in left)
                if not isinstance(exc, ValueError):  # un dossier inconnu n'est pas une panne de la boîte
                    self._cache.note(key, at=self._at(), error=_why(exc))
        return Moved(done=done, refused=refused)

    async def _role_folder(self, key: str, role: str) -> str:
        """Le dossier de ce rôle dans la boîte ; la liste des dossiers relue une fois s'il n'y est pas encore."""
        dest = self._cache.role_folder(key, role)
        if dest is None:
            await self.refresh_folders(key)
            dest = self._cache.role_folder(key, role)
        if dest is None:
            raise ValueError(_ROLE_MISSING.get(role, f"ce compte n'a pas de dossier « {role} »"))
        return dest

    async def delete(self, ref: str) -> None:
        key, acc, mail, uid = self._where(ref)
        if self._cache.role_folder(key, "trash") != mail.folder:
            raise ValueError("on ne supprime définitivement que depuis la corbeille")

        def run() -> None:
            with self._session(key, acc) as s:
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
            if parent is not None:  # gardé, mais sa boîte est retirée : jamais une autre à sa place
                raise ValueError("la boîte du mail auquel tu réponds n'est plus configurée")
            # une réponse part de la boîte de son mail, jamais d'une autre : le mail n'est plus (ou pas) dans le
            # cache, sa référence dit encore sa boîte (« compte:Message-ID »)
            owner = split_ref(reply_to)[0]
            if owner in accounts:
                return owner
            if owner:
                raise ValueError("la boîte du mail auquel tu réponds n'est plus configurée")
            # une ancienne référence, sans sa boîte, d'un mail qui n'est plus gardé : la seule boîte qui envoie, s'il
            # n'y en a qu'une ; sinon on ne devine pas
            senders = [k for k, a in accounts.items() if a.can_send]
            if len(senders) == 1:
                return senders[0]
            raise ValueError("le mail auquel tu réponds n'est plus gardé : on ne sait plus de quelle boîte il venait")
        chosen = next((k for k, a in sorted(accounts.items()) if a.can_send), None)
        if chosen is None:
            raise RuntimeError("aucun serveur d'envoi configuré")
        return chosen

    def _preview(self, draft: Draft) -> tuple[Preview, Mail | None]:
        found = self._accounts().get(draft.account)
        parent = self._cache.one(draft.reply_to) if draft.reply_to else None
        info = found.info(draft.account) if found is not None else None
        return compose.preview(draft, info, parent, tz=self._tz, her=self._her()), parent

    def preview(self, draft_id: str) -> Preview | None:
        found = self._cache.draft(draft_id)
        return self._preview(found)[0] if found is not None else None

    async def send(self, to: str, subject: str, body: str, in_reply_to: str = "", by: str = "", *,
                   account: str = "", cc: str = "", quote: bool = False, bcc: str = "",
                   files: tuple[File, ...] = ()) -> str:
        key = self._sender_key(account, in_reply_to)
        if quote and in_reply_to:
            await self.document(in_reply_to)
        draft = Draft(id="", account=key, to=to, subject=subject, body=body, cc=cc, reply_to=in_reply_to,
                      quote=quote, author=by)
        shown, parent = self._preview(draft)
        if shown.blocked:
            raise RuntimeError(shown.blocked)
        return await self._deliver(key, shown, parent, in_reply_to, by=by, draft_id="", files=files, bcc=bcc)

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
                       draft_id: str, files: tuple[File, ...] = (), bcc: str = "") -> str:
        acc = self._account(key)
        info = acc.info(key)
        message_id = compose.new_message_id(info)
        msg = compose.message(shown, parent, message_id, when=self._now(), in_reply_to=split_ref(reply_to)[1])
        # ce qu'on garde ici : le mail, sans ses pièces (leurs octets vont à part, en morceaux, ADR 0172) ni sa copie
        # cachée (rien ne la relierait à l'oubli de celui qui la reçoit, ADR 0214)
        source = msg.as_bytes()
        if files:  # l'encodage de pièces lourdes ne retient pas tout le serveur
            await asyncio.to_thread(compose.attach, msg, files)
        if bcc:
            msg["Bcc"] = bcc  # ``send_message`` la met dans l'enveloppe et la retire de ce qui part
        token = await self._bearer(key, acc)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._smtp_sync, acc, msg, token)
        # le mail est parti : plus rien ne doit le dire échoué (on le renverrait, et il arriverait deux fois)
        try:
            await asyncio.to_thread(
                self._cache.remember_sent,
                Sent(message_id, shown.to[:300], shown.subject[:300], shown.text, self._at(), reply_to, by[:100], key,
                     draft_id, shown.cc[:300], tuple(Attachment(f.name, f.mime, len(f.data)) for f in files)),
                source, files)
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
        with self._session(key, acc) as s:
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
    def _smtp_sync(acc: MailAccount, msg: EmailMessage, token: str = "") -> None:
        if not acc.smtp_host:
            raise RuntimeError("aucun serveur d'envoi configuré")
        if acc.smtp_security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(acc.smtp_host, acc.smtp_port, timeout=SMTP_TIMEOUT,
                                                    context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(acc.smtp_host, acc.smtp_port, timeout=SMTP_TIMEOUT)
        try:
            if acc.smtp_security == "starttls":
                server.starttls(context=ssl.create_default_context())
            _smtp_login(server, acc, token)
            server.sock.settimeout(compose.transfer_timeout(compose.wire_size(msg), SMTP_TIMEOUT))
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

    # ── l'oubli ──
    async def forget(self, subject: str) -> int:
        """Oublier un correspondant (``mail:<adresse>``) : ce que le cache garde de lui (``MailCache.forget``), et
        qu'on affichait ses images."""
        if not subject.startswith(HANDLE_PREFIX):
            return 0
        address = subject[len(HANDLE_PREFIX):]
        if self.images_shown(address):
            await self.show_images(address, False)
        return self._cache.forget(address, at=self._at())

    # ── images distantes (ADR 0175) ──
    def images_shown(self, address: str) -> bool:
        wanted = address.strip().lower()
        return bool(wanted) and self._images is not None and wanted in self._images.mail_images()

    async def show_images(self, address: str, shown: bool) -> None:
        wanted = address.strip().lower()
        if self._images is None:
            raise RuntimeError("aucun endroit où retenir cet expéditeur")
        if not wanted or "@" not in wanted or len(wanted) > 320:
            raise ValueError("adresse invalide")
        kept = tuple(a for a in self._images.mail_images() if a != wanted)
        await self._images.save_mail_images(((wanted,) if shown else ()) + kept[:IMAGES_FROM_MAX - 1])

    # ── état ──
    async def test(self, account: str) -> tuple[bool, str]:
        acc = self._account(account)
        if acc.microsoft:  # sans jeton, ni la lecture ni l'envoi ne peuvent s'essayer : on le dit d'abord
            try:
                await self._bearer(account, acc)
            except OAuthError as exc:
                said = f"connexion Microsoft : {_why(exc)}"
                self._cache.note(account, at=self._at(), error=said)
                return False, said[:1].upper() + said[1:] + "."

        def run() -> tuple[bool, str]:
            parts, ok = [], True
            if acc.imap_host and acc.user:
                try:
                    with self._session(account, acc) as s:
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
                    self._smtp_check(acc, self._bearers.get(account, ""))
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
    def _smtp_check(acc: MailAccount, token: str = "") -> None:
        if acc.smtp_security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(acc.smtp_host, acc.smtp_port, timeout=15,
                                                    context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(acc.smtp_host, acc.smtp_port, timeout=15)
        try:
            if acc.smtp_security == "starttls":
                server.starttls(context=ssl.create_default_context())
            _smtp_login(server, acc, token)
        finally:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass

    def status(self, account: str) -> AccountStatus:
        return self._cache.status(account)

    # ── la connexion Microsoft (ADR 0166) ──
    def signin(self, account: str) -> SignIn | None:
        found = self._accounts().get(account)
        if found is None or not found.microsoft:
            return None
        return self._microsoft.state(account, found)

    async def start_signin(self, account: str) -> SignIn:
        acc = self._account(account)
        if not acc.microsoft:
            raise ValueError("cette boîte entre par mot de passe, pas par un compte Microsoft")
        return await self._microsoft.start(account, acc)

    def close(self) -> None:
        self._microsoft.close()
        self._cache.close()


def _smtp_login(server: smtplib.SMTP, acc: MailAccount, token: str) -> None:
    """S'identifier auprès du serveur d'envoi : ``XOAUTH2`` pour une boîte Microsoft, sinon le mot de passe (s'il y en
    a un)."""
    user = acc.smtp_user or acc.user
    if acc.microsoft:
        if not token:
            raise smtplib.SMTPAuthenticationError(530, "pas de jeton Microsoft pour cette boîte")
        server.ehlo_or_helo_if_needed()
        server.auth("XOAUTH2", answer(user, token))
        return
    password = acc.smtp_password or acc.password
    if user and password:
        server.login(user, password)


#: ce qui se dit d'une boîte sans dossier de ce rôle
_ROLE_MISSING = {"archive": "ce compte n'a pas de dossier d'archives", "trash": "ce compte n'a pas de corbeille"}


def _why(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    return text[:200]
