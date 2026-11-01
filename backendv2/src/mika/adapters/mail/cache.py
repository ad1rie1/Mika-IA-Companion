"""Le cache du courrier (``mail.db`` ; son schéma vaut aussi pour la base ``mika_mail`` de MariaDB, ADR 0101) : ce qui est
arrivé, par compte et par dossier ; les dossiers et leur curseur IMAP ; ce qui a déjà été rendu (et ce qui l'a été
sans être encore accusé) ; les brouillons ; ce qui est parti ; l'état de chaque compte. Les tables sont déclarées
dans ``models`` ; ce qui se cherche (textes repliés, Message-ID du parent, références, personnes nommées) y est
calculé à l'écriture, si bien que le SQL n'appelle aucune fonction Python et se lit pareil sur les deux moteurs.

Une ligne par (compte, dossier, UID) : les UID ne valent que dans leur
dossier (et leur UIDVALIDITY). **Un mail se désigne par sa référence**
(colonne ``ref``), attribuée ici à son arrivée — jamais choisie par
l'expéditeur : le premier mail d'un Message-ID garde la forme historique
``compte:Message-ID``, une copie du même mail (un autre dossier, même
contenu) la partage, un autre mail qui porte le même Message-ID en reçoit
une autre (``…#2``) et les deux sont marqués (``twin``). Un mail qui se dit
l'un de ses envois sans être rangé dans « Envoyés » est traité de même. Ce
qui a été rendu se retient par référence : un mail qui change de dossier
n'est pas rendu deux fois, un faux qui imite un vrai l'est (on le remarque).

Oublier un correspondant (``forget``) efface ses mails, ce qui lui a été écrit
et ce qui lui répondait ; ses mails restent sur le serveur, leur empreinte est
retenue (``forgotten``) pour qu'une relecture ne les ramène pas.

**Les pièces d'un mail sont gardées avec lui** (ADR 0172) : ses pièces jointes et
ses images intégrées (``parts``), leurs octets à part, une fois par contenu
(``blobs``). Elles partent avec leur mail, quelle qu'en soit la raison (oubli,
élagage, mail rangé ailleurs) ; des octets qu'aucune pièce ne désigne plus
s'effacent avec elle. Une pièce de plus de ``PART_MAX`` reste sur le serveur ;
au-delà de ``KEPT_MAX`` en tout, les pièces des mails les plus anciens cèdent
leurs octets : elles se relisent sur le serveur, à la demande.

Les accès passent sous un verrou, par une seule connexion : une écriture est une transaction (validée à la sortie),
une lecture faite pendant une écriture la voit.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from sqlalchemy import and_, bindparam, case, delete, exists, func, insert, literal, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from mika.adapters.database import Target, as_target
from mika.adapters.mail.browse import Browse
from mika.adapters.mail.models import (
    ACCOUNT,
    ADDRESS,
    CHUNK,
    DRAFT,
    DRAFTED,
    FOLDER,
    LOCAL,
    MESSAGE,
    MID,
    REF,
    REF_KEY,
    SENT,
    TO,
    WORD,
    BlobRow,
    DraftRow,
    FolderRow,
    ForgottenRow,
    HandedRow,
    MessageRow,
    OfferedRow,
    PartRow,
    RecipientRow,
    SentRow,
    StatusRow,
    content_print,
    draft_values,
    first_ref,
    fit,
    message_values,
    people,
    sent_name,
    sent_values,
)
from mika.adapters.mail.parse import Part
from mika.ports.mail import (
    AccountStatus,
    Attachment,
    Draft,
    File,
    Folder,
    Mail,
    Sent,
    assigned_ref,
    mail_ref,
    split_ref,
)
from mika.ports.paging import words_of
from mika.ports.sql import MAIL, insert_ignore

#: limite d'une purge de maintenance explicite ; la synchronisation ne purge pas l'historique
KEEP_PER_FOLDER = 2000
#: au plus, une pièce gardée ; au-delà, elle reste sur le serveur (relue à la demande)
PART_MAX = 25 * 1024 * 1024
#: au plus, les octets de toutes les pièces gardées ; au-delà, les mails les plus anciens cèdent les leurs (jusqu'aux
#: neuf dixièmes, pour ne pas recommencer au mail suivant)
KEPT_MAX = 4 * 1024 ** 3
#: au plus, les images intégrées d'un mail rendues à sa lecture ; au-delà, leur texte de remplacement
INLINE_MAX = 8 * 1024 * 1024
#: les images intégrées qu'un cadre montre (ce qu'un navigateur lit sans risque dans un ``<img>``)
INLINE_TYPES = frozenset(("image/png", "image/gif", "image/jpeg", "image/jpg", "image/webp", "image/bmp"))

M, F, S, D, R, P, B = MessageRow, FolderRow, SentRow, DraftRow, RecipientRow, PartRow, BlobRow
_MESSAGES = MessageRow.__table__
#: ce qu'on lit d'un mail (``_mail``)
_MAIL = (M.account, M.folder, M.uid, M.message_id, M.sender, M.address, M.reply_to, M.dest, M.cc, M.subject, M.date,
         M.body, M.has_html, M.attachments, M.in_reply_to, M.refs, M.bulk, M.seen, M.flagged, M.answered, M.html,
         M.complete, M.ref, M.twin, M.parts_kept)
_SENT = (S.message_id, S.dest, S.subject, S.body, S.date, S.in_reply_to, S.author, S.account, S.draft, S.cc,
         S.attachments)
_DRAFT = (D.draft_id, D.account, D.dest, D.cc, D.subject, D.body, D.reply_to, D.quote, D.author, D.created, D.updated,
          D.state, D.sent_id, D.edited_by, D.original_body)
#: un extrait de corps, dans une page (sans la source HTML)
_EXCERPT = 400


def _short(columns: tuple[Any, ...]) -> list[Any]:
    """Les colonnes d'une ligne de page : le corps réduit à un extrait, la source HTML laissée de côté."""
    out = []
    for col in columns:
        if col.key == "body":
            out.append(func.substr(col, 1, _EXCERPT).label("body"))
        elif col.key == "html":
            out.append(literal("").label("html"))
        else:
            out.append(col)
    return out


def _files(text: str) -> tuple[Attachment, ...]:
    try:
        return tuple(Attachment(str(a[0]), str(a[1]), int(a[2])) for a in json.loads(text or "[]"))
    except (ValueError, TypeError, IndexError):
        return ()


class MailCache:
    def __init__(self, path: Path | Target) -> None:
        target = as_target(path)
        target.ensure()
        self._engine = target.engine(shared=True)
        MAIL.create_all(self._engine)
        self._session = sessionmaker(self._engine, expire_on_commit=False)
        self._lock = threading.RLock()
        #: la session en cours (une lecture faite pendant une écriture, ou une page qui charge ses lignes, la reprend)
        self._current: Session | None = None
        self._writing = False

    # ── les sessions ──
    @contextmanager
    def _use(self, write: bool) -> Iterator[Session]:
        """La session de l'appel, sous le verrou : celle en cours s'il y en a une (une écriture ne commence jamais
        dans une lecture), sinon une neuve — validée à la sortie pour une écriture, abandonnée pour une lecture."""
        with self._lock:
            if self._current is not None:
                if write and not self._writing:
                    raise RuntimeError("courrier : une écriture demandée au milieu d'une lecture")
                yield self._current
                return
            opened = self._session.begin() if write else self._session()
            with opened as s:
                self._current, self._writing = s, write
                try:
                    yield s
                finally:
                    self._current, self._writing = None, False

    @staticmethod
    def _drop_messages(s: Session, *where: Any) -> int:
        """Efface les mails qui répondent à ``where``, les personnes qu'ils nommaient et leurs pièces."""
        ids = list(s.scalars(select(M.id).where(*where)))
        if not ids:
            return 0
        s.execute(delete(R).where(R.kind == MESSAGE, R.owner.in_(ids)))
        _collect(s, _drop_parts(s, ids))
        return int(s.execute(delete(M).where(M.id.in_(ids))).rowcount or 0)

    @staticmethod
    def _relink(s: Session, kind: int, owner: int, rows: list[dict[str, Any]]) -> None:
        """Les personnes nommées par une ligne, réécrites."""
        s.execute(delete(R).where(R.kind == kind, R.owner == owner))
        if rows:
            s.execute(insert(R), rows)

    # ── références ──
    @staticmethod
    def _print(address: str, subject: str, date: int, body: str) -> str:
        """L'empreinte d'un contenu : deux copies du même mail (deux dossiers) ont la même."""
        return content_print(address, subject, date, body)

    def _assign(self, s: Session, account: str, folder: str, message_id: str, fingerprint: str) -> tuple[str, bool]:
        """La référence d'un mail qui arrive (et s'il a un jumeau) : celle d'une copie du même contenu
        s'il en a une ; la forme historique s'il est le premier de ce Message-ID ; sinon une
        référence numérotée — et l'autre mail est marqué lui aussi."""
        mid = fit(message_id, MID)
        rows = s.execute(select(M.ref, M.twin, M.fingerprint)
                         .where(M.account == account, M.message_id == mid, M.ref != "").order_by(M.id)).all()
        for row in rows:
            if row.fingerprint == fingerprint:
                return row.ref, bool(row.twin)
        if not rows and not self._claims_hers(s, account, folder, message_id):
            return first_ref(account, message_id), False
        taken = {r.ref for r in rows}
        rank = 2
        while fit(assigned_ref(account, message_id, rank), REF) in taken:
            rank += 1
        if rows:
            s.execute(update(M).where(M.account == account, M.message_id == mid).values(twin=True))
        return fit(assigned_ref(account, message_id, rank), REF), True

    @staticmethod
    def _claims_hers(s: Session, account: str, folder: str, message_id: str) -> bool:
        """Un mail qui reprend le Message-ID de l'un de ses envois sans être rangé dans « Envoyés » : un imitateur."""
        filed = exists().where(F.account == account, F.name == fit(folder, FOLDER), F.role == "sent")
        return s.scalar(
            select(S.id).where(S.message_id.in_([fit(message_id, MID), fit(mail_ref(account, message_id), MID)]),
                               or_(S.account == account, S.account == ""), ~filed).limit(1)) is not None

    # ── mails ──
    @staticmethod
    def _mail(r: Any) -> Mail:
        return Mail(message_id=r.message_id, sender=r.sender or "", address=r.address or "",
                    subject=r.subject or "", date=r.date or 0, body=r.body or "", to=r.dest or "",
                    in_reply_to=r.in_reply_to or "", bulk=bool(r.bulk), account=r.account,
                    folder=r.folder, cc=r.cc or "", reply_to=r.reply_to or "", references=r.refs or "",
                    seen=bool(r.seen), flagged=bool(r.flagged), answered=bool(r.answered),
                    attachments=_files(r.attachments), has_html=bool(r.has_html), html=r.html or "",
                    complete=bool(r.complete), key=r.ref or "", twin=bool(r.twin), parts_kept=bool(r.parts_kept))

    def store(self, m: Mail, uid: int, parts: Iterable[Part] | None = None) -> Mail:
        """Garde un mail à sa place (compte, dossier, UID) et rend ce qui est gardé, avec sa référence :
        celle qu'il avait déjà à cette place (ou à sa place provisoire, s'il vient d'être déplacé),
        sinon celle que lui attribue ``_assign``. Un mail oublié (``forget``) n'est pas gardé de nouveau :
        il est rendu tel quel. ``parts`` : ses pièces, lues de son message entier (``parse.parse_parts``), qui
        remplacent celles qu'il avait ; sans elles, il garde les siennes."""
        fingerprint = self._print(m.address, m.subject, m.date, m.body)
        account, folder, mid = fit(m.account, ACCOUNT), fit(m.folder, FOLDER), fit(m.message_id, MID)
        with self._use(write=True) as s:
            if s.get(ForgottenRow, (account, fingerprint)) is not None:
                return m  # une relecture du serveur ne ramène pas ce qui a été oublié
            # sa place, et les places provisoires de ce mail dans ce dossier, en une lecture
            found = s.execute(select(M.id, M.uid, M.message_id, M.ref, M.twin)
                              .where(M.account == account, M.folder == folder,
                                     or_(M.uid == uid, and_(M.uid <= 0, M.message_id == mid)))
                              .order_by(M.uid.desc())).all()
            place = next((r for r in found if r.uid == uid), None)
            known = next((r for r in found if r.message_id == mid and r.ref), None)
            # un mail déplacé d'ici attendait son vrai UID (une place provisoire, négative) : il l'a
            gone = [r.id for r in found if r.uid <= 0]
            if known is not None:
                ref, twin = str(known.ref), bool(known.twin)
            else:
                if place is not None:  # cette place change d'occupant
                    gone.append(place.id)
                    place = None
                ref, twin = self._assign(s, account, m.folder, m.message_id, fingerprint)
            if gone:
                self._drop_messages(s, M.id.in_(gone))
            # la ligne passe en paramètres d'une requête sur la table (``values(**…)`` coûte autant que l'écriture)
            values = message_values(m, uid, ref, twin)
            if parts is not None:
                values["parts_kept"] = True
            if place is None:
                row_id = int(s.execute(insert(_MESSAGES), values).inserted_primary_key[0])
            else:
                row_id = int(place.id)
                s.execute(update(_MESSAGES).where(_MESSAGES.c.id == bindparam("row")), {**values, "row": row_id})
                s.execute(delete(R).where(R.kind == MESSAGE, R.owner == row_id))
            linked = people(MESSAGE, row_id, to=m.to, cc=m.cc, sender=m.sender, address=m.address)
            if linked:
                s.execute(insert(R), linked)
            if parts is not None:
                before = _drop_parts(s, [row_id])
                fresh = _keep_parts(s, row_id, parts)
                _collect(s, before)  # après : relu à l'identique, il garde ses octets sans les réécrire
                if fresh:
                    _bound(s)
        return replace(m, key=ref, twin=twin, parts_kept=values["parts_kept"])

    @staticmethod
    def _where_ref(ref: str) -> Any:
        """Où chercher une référence : exactement elle ; sans compte (un ancien journal), le premier mail
        de ce Message-ID, jamais un jumeau arrivé après."""
        account, local = split_ref(ref)
        exact = fit(ref, REF)
        if account:
            first = first_ref(account, local)
            return and_(M.account == account,
                        or_(M.ref == exact, and_(M.message_id == fit(local, MID), M.ref == first, M.ref != exact)))
        return and_(M.message_id == fit(local, MID), M.historic)

    def _best(self, s: Session, ref: str) -> Any:
        return s.execute(select(*_MAIL, M.id).where(self._where_ref(ref))
                         .order_by(case((M.ref == fit(ref, REF), 1), else_=0).desc(),
                                   case((M.folder == "INBOX", 1), else_=0).desc(), M.date.desc(), M.id)
                         .limit(1)).first()

    def one(self, ref: str) -> Mail | None:
        with self._use(write=False) as s:
            row = self._best(s, ref)
        return self._mail(row) if row is not None else None

    def at_row(self, rowid: int, *, sent: bool = False):
        with self._use(write=False) as s:
            if sent:
                return self._sent(s.execute(select(*_short(_SENT)).where(S.id == rowid)).one())
            return self._mail(s.execute(select(*_short(_MAIL)).where(M.id == rowid)).one())

    def draft_at_row(self, rowid: int):
        with self._use(write=False) as s:
            return self._draft(s.execute(select(*_DRAFT).where(D.id == rowid)).one())

    def browse(self, method: str, *args):
        with self._use(write=False):
            return getattr(Browse(self), method)(*args)

    # ── ses pièces ──
    def _owners(self, s: Session, ref: str) -> list[int]:
        """Les lignes de ce mail (ses copies comprises), la meilleure d'abord (comme ``_best``)."""
        return [int(i) for i in s.scalars(
            select(M.id).where(self._where_ref(ref))
            .order_by(case((M.ref == fit(ref, REF), 1), else_=0).desc(), case((M.folder == "INBOX", 1), else_=0).desc(),
                      M.date.desc(), M.id))]

    def part(self, ref: str, position: int) -> File | None:
        """Une pièce jointe gardée, à son rang ; ``None`` : ses octets ne sont pas ici (le serveur les a)."""
        with self._use(write=False) as s:
            for owner in self._owners(s, ref):
                row = s.execute(select(P.name, P.mime, P.size, P.digest)
                                .where(P.owner == owner, P.position == position, P.digest != "")).first()
                data = _blob(s, row.digest, row.size) if row is not None else None
                if data is not None:
                    return File(row.name, row.mime, data)
        return None

    def files(self, ref: str, count: int) -> tuple[File, ...] | None:
        """Ses ``count`` pièces jointes, toutes gardées, dans leur ordre ; ``None`` s'il en manque une."""
        out = []
        for position in range(count):
            found = self.part(ref, position)
            if found is None:
                return None
            out.append(found)
        return tuple(out)

    def inline(self, ref: str, limit: int = INLINE_MAX) -> tuple[tuple[str, str, bytes], ...]:
        """Ses images intégrées gardées, (Content-ID, type, octets), jusqu'à ``limit`` octets en tout."""
        out: dict[str, tuple[str, str, bytes]] = {}
        left = limit
        with self._use(write=False) as s:
            for owner in self._owners(s, ref):
                rows = s.execute(select(P.content_id, P.mime, P.size, P.digest)
                                 .where(P.owner == owner, P.content_id != "", P.digest != "")
                                 .order_by(P.id)).all()
                for row in rows:
                    if row.content_id in out or row.mime.lower() not in INLINE_TYPES or row.size > left:
                        continue
                    data = _blob(s, row.digest, row.size)
                    if data is not None:
                        out[row.content_id] = (row.content_id, row.mime.lower(), data)
                        left -= len(data)
        return tuple(out.values())

    def located(self, ref: str) -> tuple[Mail, int] | None:
        """Le mail et son UID dans son dossier."""
        with self._use(write=False) as s:
            row = self._best(s, ref)
        return (self._mail(row), int(row.uid)) if row is not None else None

    def located_all(self, refs: Iterable[str]) -> list[tuple[Mail, int]]:
        """Chaque mail (et son UID) de ces références, sans doublon."""
        out: list[tuple[Mail, int]] = []
        seen: set[tuple[str, str, int]] = set()
        with self._use(write=False):
            for ref in refs:
                found = self.located(ref)
                if found is not None and (found[0].account, found[0].folder, found[1]) not in seen:
                    seen.add((found[0].account, found[0].folder, found[1]))
                    out.append(found)
        return out

    def recent(self, limit: int, *, account: str = "", folder: str = "") -> list[Mail]:
        where = []
        if account:
            where.append(M.account == fit(account, ACCOUNT))
        if folder:
            where.append(M.folder == fit(folder, FOLDER))
        with self._use(write=False) as s:
            rows = s.execute(select(*_MAIL).where(*where).order_by(M.date.desc(), M.id.desc())
                             .limit(max(0, limit))).all()
        return [self._mail(r) for r in rows]

    def search(self, text: str, limit: int, *, account: str = "") -> list[Mail]:
        """Les mails dont l'objet, l'expéditeur ou le corps contiennent chaque mot de ``text`` (sans casse ni
        accents, dans n'importe quel ordre)."""
        words = words_of(text) or [""]
        found = M.fold_subject + " " + M.fold_sender + " " + M.fold_body
        where = [and_(*(func.instr(found, w) > 0 for w in words))]
        if account:
            where.append(M.account == fit(account, ACCOUNT))
        with self._use(write=False) as s:
            rows = s.execute(select(*_MAIL).where(*where).order_by(M.date.desc(), M.id.desc())
                             .limit(max(0, limit))).all()
        return [self._mail(r) for r in rows]

    def uids(self, account: str, folder: str, limit: int) -> list[tuple[int, str, bool]]:
        """Les derniers ``(uid, référence, lu)`` d'un dossier."""
        with self._use(write=False) as s:
            rows = s.execute(select(M.uid, M.ref, M.seen)
                             .where(M.account == fit(account, ACCOUNT), M.folder == fit(folder, FOLDER), M.uid > 0)
                             .order_by(M.uid.desc()).limit(max(0, limit))).all()
        return [(int(u), str(r), bool(seen)) for u, r, seen in rows]

    def oldest_uid(self, account: str, folder: str) -> int:
        with self._use(write=False) as s:
            return int(s.scalar(select(func.coalesce(func.min(M.uid), 0))
                                .where(M.account == fit(account, ACCOUNT), M.folder == fit(folder, FOLDER),
                                       M.uid > 0)) or 0)

    def folder_count(self, account: str, folder: str) -> int:
        with self._use(write=False) as s:
            return int(s.scalar(select(func.count()).select_from(M)
                                .where(M.account == fit(account, ACCOUNT), M.folder == fit(folder, FOLDER))) or 0)

    def find_ref(self, key: str) -> str | None:
        """La référence derrière une clé imprimable (``reference_key``) : un mail gardé, sinon un envoi — sans
        charger aucun corps."""
        wanted = fit(key, REF_KEY)
        with self._use(write=False) as s:
            found = s.scalar(select(M.ref).where(M.ref_key == wanted).limit(1))
            if found is None:
                found = s.scalar(select(S.ref).where(or_(S.ref_key == wanted, S.mid_key == wanted)).limit(1))
        return str(found) if found is not None else None

    def missing_html(self, account: str, folder: str, limit: int) -> list[int]:
        """Les mails gardés sans leur source HTML (un mail qui en a une) ; relecture explicite seulement."""
        with self._use(write=False) as s:
            return [int(u) for u in s.scalars(
                select(M.uid).where(M.account == fit(account, ACCOUNT), M.folder == fit(folder, FOLDER), M.uid > 0,
                                    M.has_html, M.html == "")
                .order_by(M.date.desc(), M.id.desc()).limit(max(0, limit)))]

    def set_flags(self, account: str, folder: str, uid: int, *, seen: bool | None = None,
                  flagged: bool | None = None, answered: bool | None = None) -> None:
        values = {name: bool(value) for name, value in (("seen", seen), ("flagged", flagged), ("answered", answered))
                  if value is not None}
        if not values:
            return
        with self._use(write=True) as s:
            s.execute(update(M).where(M.account == fit(account, ACCOUNT), M.folder == fit(folder, FOLDER),
                                      M.uid == uid).values(**values))

    def forget_uids(self, account: str, folder: str, uids: Iterable[int]) -> None:
        wanted = sorted({int(u) for u in uids})
        if not wanted:
            return
        with self._use(write=True) as s:
            self._drop_messages(s, M.account == fit(account, ACCOUNT), M.folder == fit(folder, FOLDER),
                                M.uid.in_(wanted))

    def relocate(self, account: str, folder: str, uid: int, dest: str, new_uid: int | None) -> None:
        """Un mail déplacé : il change de dossier (et d'UID, s'il est connu ; sinon une place provisoire, négative,
        qu'aucun autre mail de ce dossier n'occupe). Le mail qui occupait déjà sa nouvelle place s'en va."""
        account, there = fit(account, ACCOUNT), fit(dest, FOLDER)
        with self._use(write=True) as s:
            moving = s.scalar(select(M.id).where(M.account == account, M.folder == fit(folder, FOLDER),
                                                 M.uid == uid))
            if moving is None:
                return
            if new_uid is None:
                lowest = s.scalar(select(func.min(M.uid)).where(M.account == account, M.folder == there))
                new_uid = min(0, int(lowest or 0)) - 1
            self._drop_messages(s, M.account == account, M.folder == there, M.uid == new_uid, M.id != moving)
            s.execute(update(M).where(M.id == moving).values(folder=there, uid=new_uid, sent_name=sent_name(dest)))

    def reset_folder(self, account: str, folder: str) -> None:
        with self._use(write=True) as s:
            self._drop_messages(s, M.account == fit(account, ACCOUNT), M.folder == fit(folder, FOLDER))

    def prune(self, account: str, folder: str, keep: int = KEEP_PER_FOLDER) -> None:
        """Ne garde que les ``keep`` mails les plus récents d'un dossier : lit d'abord le premier à partir, puis
        efface à partir de lui."""
        here = (M.account == fit(account, ACCOUNT), M.folder == fit(folder, FOLDER))
        with self._use(write=True) as s:
            edge = s.execute(select(M.date, M.id).where(*here).order_by(M.date.desc(), M.id.desc())
                             .offset(max(0, keep)).limit(1)).first()
            if edge is not None:
                self._drop_messages(s, *here, or_(M.date < edge.date, and_(M.date == edge.date, M.id <= edge.id)))

    # ── rendus une fois ──
    def handed(self, account: str, message_id: str) -> bool:
        with self._use(write=False) as s:
            return s.get(HandedRow, (fit(account, ACCOUNT), fit(message_id, LOCAL))) is not None

    def hand(self, account: str, message_id: str) -> None:
        with self._use(write=True) as s:
            insert_ignore(s, HandedRow, {"account": fit(account, ACCOUNT), "local": fit(message_id, LOCAL)})

    def offer(self, account: str, ref: str) -> None:
        """Rendu par un relevé, pas encore accusé : chaque relevé le rend encore tant qu'il ne l'est pas
        (le curseur IMAP, lui, est déjà passé)."""
        with self._use(write=True) as s:
            insert_ignore(s, OfferedRow, {"account": fit(account, ACCOUNT), "ref": fit(ref, REF)})

    def offered(self, account: str, limit: int) -> list[Mail]:
        """Les mails rendus et pas encore accusés de ce compte, les plus anciens d'abord ; un mail sorti du
        cache entre-temps (supprimé, rangé ailleurs par un autre client) n'est plus à rendre."""
        out: list[Mail] = []
        account = fit(account, ACCOUNT)
        with self._use(write=True) as s:
            for ref in list(s.scalars(select(OfferedRow.ref).where(OfferedRow.account == account)
                                      .order_by(OfferedRow.id))):
                if len(out) >= limit:
                    break
                mail = self.one(ref)
                if mail is None:
                    s.execute(delete(OfferedRow).where(OfferedRow.account == account, OfferedRow.ref == ref))
                else:
                    out.append(mail)
        return out

    def ack(self, refs: Iterable[str]) -> None:
        """Ces mails ont été remarqués : rendus pour de bon, plus jamais rendus."""
        with self._use(write=True) as s:
            for ref in refs:
                account, local = split_ref(ref)
                account = fit(account, ACCOUNT)
                insert_ignore(s, HandedRow, {"account": account, "local": fit(local, LOCAL)})
                s.execute(delete(OfferedRow).where(OfferedRow.account == account, OfferedRow.ref == fit(ref, REF)))

    # ── dossiers ──
    @staticmethod
    def _folder(r: FolderRow, polled: frozenset[str]) -> Folder:
        return Folder(r.account, r.name, r.role or "", r.name in polled, r.total or 0, r.unseen or 0, r.last_sync or 0)

    def folders(self, account: str, polled: Iterable[str] = ()) -> list[Folder]:
        chosen = frozenset(fit(name, FOLDER) for name in polled)
        with self._use(write=False) as s:
            rows = list(s.scalars(select(F).where(F.account == fit(account, ACCOUNT))))
        known = {r.name for r in rows}
        out = [self._folder(r, chosen) for r in rows]
        out += [Folder(account, name, "inbox" if name.upper() == "INBOX" else "", True) for name in sorted(chosen)
                if name not in known]
        order = {"inbox": 0, "drafts": 1, "sent": 2, "archive": 3, "": 4, "junk": 5, "trash": 6}
        return sorted(out, key=lambda f: (order.get(f.role, 4), f.name.lower()))

    def cursor(self, account: str, folder: str) -> tuple[int, int] | None:
        """``(uidvalidity, uidnext)`` d'un dossier déjà relu."""
        with self._use(write=False) as s:
            row = s.get(F, (fit(account, ACCOUNT), fit(folder, FOLDER)))
            return (int(row.uidvalidity or 0), int(row.uidnext or 0)) if row is not None else None

    def save_folder(self, account: str, name: str, *, role: str | None = None, uidvalidity: int | None = None,
                    uidnext: int | None = None, total: int | None = None, unseen: int | None = None,
                    last_sync: int | None = None) -> None:
        with self._use(write=True) as s:
            key = (fit(account, ACCOUNT), fit(name, FOLDER))
            row = s.get(F, key)
            if row is None:
                row = F(account=key[0], name=key[1], role="", uidvalidity=0, uidnext=0, total=0, unseen=0,
                        last_sync=0)
                s.add(row)
            if role is not None:
                row.role = fit(role, WORD)
            for col, value in (("uidvalidity", uidvalidity), ("uidnext", uidnext), ("total", total),
                               ("unseen", unseen), ("last_sync", last_sync)):
                if value is not None:
                    setattr(row, col, value)

    def keep_folders(self, account: str, names: Iterable[str]) -> None:
        """La liste des dossiers vient d'être relue : ceux qui n'existent plus s'en vont."""
        kept = sorted({fit(n, FOLDER) for n in names})
        with self._use(write=True) as s:
            s.execute(delete(F).where(F.account == fit(account, ACCOUNT), F.name.not_in(kept)))

    def role_folder(self, account: str, role: str) -> str | None:
        with self._use(write=False) as s:
            found = s.scalar(select(F.name).where(F.account == fit(account, ACCOUNT), F.role == fit(role, WORD))
                             .order_by(F.name).limit(1))
        return str(found) if found is not None else None

    def recount(self, account: str, folder: str) -> None:
        with self._use(write=True) as s:
            total, unseen = s.execute(
                select(func.count(), func.coalesce(func.sum(case((M.seen, 0), else_=1)), 0))
                .where(M.account == fit(account, ACCOUNT), M.folder == fit(folder, FOLDER))).one()
            self.save_folder(account, folder, total=int(total), unseen=int(unseen))

    # ── envoyés ──
    def remember_sent(self, s: Sent, source: bytes | None = None) -> None:
        values = sent_values(s, source)
        with self._use(write=True) as db:
            row = db.scalar(select(S).where(S.message_id == values["message_id"]))
            if row is None:
                row = S(**values)
                db.add(row)
            else:
                for name, value in values.items():
                    setattr(row, name, value)
            db.flush()
            self._relink(db, SENT, row.id, people(SENT, row.id, to=s.to, cc=s.cc))

    def _sent_where(self, ref: str) -> list[Any]:
        account, mid = split_ref(ref)
        where = [S.message_id.in_([fit(ref, MID), fit(mid, MID)])]
        if account:
            where.append(S.account == fit(account, ACCOUNT))
        return where

    def sent_source(self, ref: str) -> bytes | None:
        with self._use(write=False) as s:
            row = s.execute(select(S.source).where(*self._sent_where(ref)).order_by(S.id).limit(1)).first()
        return row.source if row is not None else None

    @staticmethod
    def _sent(r: Any) -> Sent:
        return Sent(r.message_id, r.dest or "", r.subject or "", r.body or "", r.date or 0, r.in_reply_to or "",
                    r.author or "", r.account or "", r.draft or "", r.cc or "",
                    tuple(Attachment(*a) for a in json.loads(r.attachments or "[]")))

    def sent(self, limit: int, *, account: str = "") -> list[Sent]:
        where = [S.account == fit(account, ACCOUNT)] if account else []
        with self._use(write=False) as s:
            rows = s.execute(select(*_SENT).where(*where).order_by(S.date.desc(), S.id.desc())
                             .limit(max(0, limit))).all()
        return [self._sent(r) for r in rows]

    def sent_one(self, message_id: str) -> Sent | None:
        with self._use(write=False) as s:
            row = s.execute(select(*_SENT).where(*self._sent_where(message_id)).order_by(S.id).limit(1)).first()
        return self._sent(row) if row is not None else None

    # ── brouillons ──
    @staticmethod
    def _draft(r: Any) -> Draft:
        return Draft(id=r.draft_id, account=r.account or "", to=r.dest or "", subject=r.subject or "",
                     body=r.body or "", cc=r.cc or "", reply_to=r.reply_to or "", quote=bool(r.quote),
                     author=r.author or "", created=r.created or 0, updated=r.updated or 0,
                     state=r.state or "brouillon", sent_id=r.sent_id or "", edited_by=r.edited_by or "",
                     original_body=r.original_body or "")

    def save_draft(self, d: Draft) -> Draft:
        values = draft_values(d)
        with self._use(write=True) as s:
            row = s.scalar(select(D).where(D.draft_id == values["draft_id"]))
            if row is None:
                row = D(**values)
                s.add(row)
            else:
                for name, value in values.items():
                    setattr(row, name, value)
            s.flush()
            self._relink(s, DRAFTED, row.id, people(DRAFTED, row.id, to=d.to, cc=d.cc))
        return d

    def draft(self, draft_id: str) -> Draft | None:
        with self._use(write=False) as s:
            row = s.execute(select(*_DRAFT).where(D.draft_id == fit(draft_id, DRAFT))).first()
        return self._draft(row) if row is not None else None

    def drafts(self, limit: int, *, state: str = "") -> list[Draft]:
        where = [D.state == fit(state, WORD)] if state else []
        with self._use(write=False) as s:
            rows = s.execute(select(*_DRAFT).where(*where).order_by(D.updated.desc(), D.id.desc())
                             .limit(max(0, limit))).all()
        return [self._draft(r) for r in rows]

    def recent_edits(self, account: str, limit: int) -> list[Draft]:
        """Ses brouillons de ce compte partis après une retouche, le plus récent d'abord."""
        with self._use(write=False) as s:
            rows = s.execute(select(*_DRAFT).where(D.account == fit(account, ACCOUNT), D.state == "envoye",
                                                   D.sent_id != "", D.edited_by != "", D.original_body != "")
                             .order_by(D.updated.desc(), D.id.desc()).limit(max(0, limit))).all()
        return [self._draft(r) for r in rows]

    def mark_draft(self, draft_id: str, *, state: str, sent_id: str = "") -> None:
        with self._use(write=True):
            found = self.draft(draft_id)
            if found is not None:
                self.save_draft(replace(found, state=state, sent_id=sent_id or found.sent_id))

    # ── l'oubli ──
    def forget(self, address: str) -> int:
        """Oublier un correspondant, par son adresse : les mails qu'il a écrits ; ce qui lui a été écrit
        (brouillons, envois, leurs copies dans « Envoyés ») ; ce qui répondait à ses mails (ça les cite).
        Ses mails restent sur le serveur : leur empreinte est retenue, pour qu'une relecture ne les
        ramène pas. Rend combien de lignes ont été effacées."""
        address = address.strip().lower()
        if not address:
            return 0
        wanted = fit(address, ADDRESS)

        def to_them(kind: int, owner: Any) -> Any:
            return exists().where(R.kind == kind, R.owner == owner, R.role == TO, R.address == wanted)

        in_sent = or_(exists().where(F.account == M.account, F.name == M.folder, F.role == "sent"), M.sent_name)
        with self._use(write=True) as s:
            rows = s.execute(select(M.id, M.account, M.folder, M.ref, M.message_id, M.address, M.fingerprint)
                             .where(or_(M.address == address, and_(to_them(MESSAGE, M.id), in_sent)))).all()
            # ce qui leur répondait les désigne par référence (ou par Message-ID)
            theirs = sorted({k for r in rows if r.address == address for k in (r.ref, r.message_id) if k})
            drafts = list(s.scalars(select(D.id).where(or_(to_them(DRAFTED, D.id), D.reply_to.in_(theirs)))))
            sent = list(s.scalars(select(S.id).where(or_(to_them(SENT, S.id), S.in_reply_to.in_(theirs)))))
            n = 0
            for kind, entity, ids in ((DRAFTED, D, drafts), (SENT, S, sent)):
                if ids:
                    s.execute(delete(R).where(R.kind == kind, R.owner.in_(ids)))
                    n += int(s.execute(delete(entity).where(entity.id.in_(ids))).rowcount or 0)
            for r in rows:
                insert_ignore(s, ForgottenRow, {"account": r.account, "fingerprint": r.fingerprint})
                s.execute(delete(OfferedRow).where(OfferedRow.account == r.account, OfferedRow.ref == r.ref))
            n += self._drop_messages(s, M.id.in_([r.id for r in rows])) if rows else 0
            for account, folder in sorted({(r.account, r.folder) for r in rows}):
                self.recount(account, folder)
        return n

    # ── état des comptes ──
    def status(self, account: str) -> AccountStatus:
        with self._use(write=False) as s:
            row = s.get(StatusRow, fit(account, ACCOUNT))
            return AccountStatus(account, int(row.last_poll or 0), row.error or "", int(row.error_at or 0)) \
                if row is not None else AccountStatus(account)

    def note(self, account: str, *, at: int, error: str = "", polled: bool = False) -> None:
        with self._use(write=True) as s:
            row = s.get(StatusRow, fit(account, ACCOUNT))
            if row is None:
                row = StatusRow(account=fit(account, ACCOUNT), last_poll=0, error="", error_at=0)
                s.add(row)
            if polled:
                row.last_poll = at
            if error:
                row.error, row.error_at = error[:300], at
            elif polled:
                row.error = ""

    def close(self) -> None:
        with self._lock:
            self._engine.dispose()


def ref_of(m: Mail) -> str:
    return m.ref


# ── les pièces et leurs octets ──
def _keep_parts(s: Session, owner: int, parts: Iterable[Part]) -> bool:
    """Les pièces d'un mail, et leurs octets s'ils sont lisibles et pas trop gros ; rend s'il en a écrit de nouveaux."""
    rows, fresh = [], False
    for part in parts:
        digest = ""
        if part.data is not None and len(part.data) <= PART_MAX:
            digest = hashlib.sha256(part.data).hexdigest()
            if s.scalar(select(B.chunk).where(B.digest == digest).limit(1)) is None:
                data = part.data
                s.execute(insert(B), [{"digest": digest, "chunk": n, "data": data[at:at + CHUNK]}
                                      for n, at in enumerate(range(0, max(1, len(data)), CHUNK))])
                fresh = True
        rows.append({"owner": owner, "position": part.position, "content_id": part.content_id[:1000],
                     "name": part.name[:1000], "mime": part.mime[:200],
                     "size": len(part.data) if part.data is not None else 0, "digest": digest})
    if rows:
        s.execute(insert(P), rows)
    return fresh


def _drop_parts(s: Session, owners: list[int]) -> list[str]:
    """Efface les pièces de ces mails ; rend les empreintes qu'elles désignaient (``_collect`` les ramasse)."""
    digests = sorted(set(s.scalars(select(P.digest).where(P.owner.in_(owners), P.digest != ""))))
    s.execute(delete(P).where(P.owner.in_(owners)))
    return digests


def _collect(s: Session, digests: list[str]) -> None:
    """Efface les octets de ces empreintes qu'aucune pièce ne désigne plus."""
    if not digests:
        return
    used = set(s.scalars(select(P.digest).where(P.digest.in_(digests))))
    gone = [d for d in digests if d not in used]
    if gone:
        s.execute(delete(B).where(B.digest.in_(gone)))


def _blob(s: Session, digest: str, size: int) -> bytes | None:
    """Les octets d'une empreinte, recollés ; ``None`` s'ils manquent ou ne font pas la taille attendue."""
    data = b"".join(s.scalars(select(B.data).where(B.digest == digest).order_by(B.chunk)))
    return data if len(data) == size else None


def _bound(s: Session) -> None:
    """Au-delà de ``KEPT_MAX``, les pièces dont le dernier mail est le plus ancien cèdent leurs octets (jusqu'aux
    neuf dixièmes) : leurs lignes restent, sans empreinte, et se relisent sur le serveur."""
    kept = select(P.digest, func.max(P.size).label("size")).where(P.digest != "").group_by(P.digest).subquery()
    total = int(s.scalar(select(func.coalesce(func.sum(kept.c.size), 0))) or 0)
    if total <= KEPT_MAX:
        return
    last = func.max(M.date)
    rows = s.execute(select(P.digest, func.max(P.size).label("size"), last.label("last"))
                     .join(M, M.id == P.owner).where(P.digest != "").group_by(P.digest)
                     .order_by(last, P.digest)).all()
    gone = []
    for row in rows:
        if total <= KEPT_MAX * 9 // 10:
            break
        gone.append(row.digest)
        total -= int(row.size or 0)
    for at in range(0, len(gone), 500):
        batch = gone[at:at + 500]
        s.execute(update(P).where(P.digest.in_(batch)).values(digest=""))
        s.execute(delete(B).where(B.digest.in_(batch)))
