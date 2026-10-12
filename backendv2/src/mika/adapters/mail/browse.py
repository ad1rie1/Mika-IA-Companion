"""Consultation SQL du courrier : filtrer et compter avant de lire les corps.

Les conversations, contacts et envoyés parcourent tout le cache. Seule la
page demandée devient des objets Python. Les CTE des historiques ne portent
que les en-têtes, jamais tous les corps ou toutes les pièces jointes : un
texte cherché dans un corps se lit ligne par ligne, par son ``id``.

Tout est écrit avec les requêtes de SQLAlchemy, sur les colonnes que le cache
calcule à l'écriture (``models``) : les textes repliés (comparés avec
``instr`` : sans casse ni accents, pareil sur les deux moteurs), le
Message-ID nu du parent, les personnes nommées (``recipients``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import and_, case, exists, func, literal, or_, select, true, union, union_all

from mika.adapters.mail.models import (
    ACCOUNT,
    ADDRESS,
    FOLDER,
    FROM,
    MESSAGE,
    MID,
    REF,
    SENT,
    TO,
    DraftRow,
    FolderRow,
    MessageRow,
    RecipientRow,
    SentRow,
    fit,
)
from mika.ports.mail import Contact, MailHit, MailQuery, mail_ref, split_ref
from mika.ports.paging import Page, fold_text

M, S, F, R, D = MessageRow, SentRow, FolderRow, RecipientRow, DraftRow


def index() -> Any:
    """Les lettres : une par (compte, référence). Les messages reçus et les envois locaux peuvent décrire le même
    mail ; la copie locale fait autorité pour les envois, INBOX pour les autres copies. ``local`` dit de quelle table
    vient la ligne (0 : ``messages``, 1 : ``sent``), ``rid`` son ``id`` ; ``sent`` : la lettre est un envoi."""
    is_sent = or_(exists().where(F.account == M.account, F.name == M.folder, F.role == "sent"), M.sent_name)
    candidates = union_all(
        select(M.id.label("rid"), literal(MESSAGE).label("local"), M.account, M.message_id, M.ref, M.subject, M.date,
               M.sender, M.dest, M.parent, case((M.folder == "INBOX", 1), else_=0).label("priority"),
               case((is_sent, 1), else_=0).label("is_sent")),
        select(S.id, literal(SENT), S.account, S.local, S.ref, S.subject, S.date, literal(""), S.dest, S.parent,
               literal(2), literal(1)),
    ).cte("candidates")
    c = candidates.c
    ranked = select(
        candidates,
        func.max(c.is_sent).over(partition_by=(c.account, c.ref)).label("sent"),
        func.row_number().over(partition_by=(c.account, c.ref),
                               order_by=(c.priority.desc(), c.date.desc(), c.rid.desc())).label("nth"),
    ).cte("ranked")
    return select(ranked).where(ranked.c.nth == 1).cte("letters")


def _contains(text: Any, value: str) -> Any:
    return func.instr(text, fold_text(value)) > 0


def _text_of(letters: Any, message: Callable[[], Any], sent: Callable[[], Any]) -> Any:
    """Le texte replié d'une lettre, lu dans sa table par son ``id`` (les corps ne passent pas par les CTE)."""
    return case((letters.c.local == SENT, select(sent()).where(S.id == letters.c.rid).scalar_subquery()),
                else_=select(message()).where(M.id == letters.c.rid).scalar_subquery())


def conditions(query: MailQuery) -> list[Any]:
    where: list[Any] = []
    if query.account:
        where.append(M.account == fit(query.account, ACCOUNT))
    if query.folder:
        where.append(M.folder == fit(query.folder, FOLDER))
    for col, value in ((M.seen, query.seen), (M.flagged, query.flagged)):
        if value is not None:
            where.append(col == bool(value))
    if query.text:
        where.append(_contains(M.fold_subject + " " + M.fold_sender + " " + M.fold_body, query.text))
    if query.sender:
        where.append(_contains(M.fold_who, query.sender))
    if query.refs is not None:
        where.append(M.ref.in_([fit(r, REF) for r in query.refs]))
    if query.exclude:
        where.append(M.ref.not_in([fit(r, REF) for r in query.exclude]))
    return where


class Browse:
    def __init__(self, cache):
        self.cache = cache

    def page(self, result: Any, columns: Sequence[str], order: Callable[[Any], Sequence[Any]], load, page: int,
             size: int):
        """Une page de ``result`` (une requête nommée) : compter, borner, puis ne lire que ses lignes."""
        with self.cache._use(write=False) as s:
            total = int(s.scalar(select(func.count()).select_from(result)) or 0)
            page, size, offset = Page.bounds(total, page, size)
            rows = s.execute(select(*(result.c[name] for name in columns)).order_by(*order(result.c))
                             .limit(size).offset(offset)).all()
            return Page(tuple(load(row) for row in rows), total, page, size)

    def messages(self, query: MailQuery, page: int, size: int):
        result = select(M.id.label("rid"), M.date).where(*conditions(query)).subquery("result")
        return self.page(result, ("rid",), lambda c: (c.date.desc(), c.rid.desc()),
                         lambda r: self.cache.at_row(r.rid), page, size)

    def outgoing(self, query: MailQuery, page: int, size: int):
        letters = index()
        where = [letters.c.sent == 1]
        if query.account:
            where.append(letters.c.account == fit(query.account, ACCOUNT))
        if query.text:
            where.append(_contains(_text_of(letters, lambda: M.fold_subject + " " + M.fold_dest + " " + M.fold_body,
                                            lambda: S.fold_subject + " " + S.fold_dest + " " + S.fold_body),
                                   query.text))
        result = select(letters).where(*where).cte("result")
        return self.page(result, ("rid", "local"), lambda c: (c.date.desc(), c.account, c.message_id),
                         lambda r: (self.cache.at_row(r.rid, sent=r.local == SENT), r.local == SENT), page, size)

    def _hits(self, text: str) -> Any:
        letters = index()
        found = _text_of(letters, lambda: M.fold_subject + " " + M.fold_sender + " " + M.fold_dest + " " + M.fold_body,
                         lambda: S.fold_subject + "  " + S.fold_dest + " " + S.fold_body)
        c = letters.c
        return select(c.account, c.message_id, c.subject, c.date, c.sender, c.dest, c.sent, c.ref) \
            .where(_contains(found, text))

    def hits(self, text: str, limit: int, offset: int, *, count: bool = False):
        # Recherche dans tout le contenu ; on ne matérialise que les en-têtes de la page.
        query = self._hits(text)
        with self.cache._use(write=False) as s:
            if count:
                return int(s.scalar(select(func.count()).select_from(query.subquery())) or 0)
            c = query.selected_columns
            rows = s.execute(query.order_by(c.date.desc(), c.account, c.message_id)
                             .limit(max(1, min(100, limit))).offset(max(0, offset))).all()
        return [self.hit(r) for r in rows]

    def search_count(self, text: str):
        return self.hits(text, 1, 0, count=True)

    @staticmethod
    def hit(r):
        account, mid, subject, date, sender, dest, sent, ref = r
        return MailHit(ref or mail_ref(account, mid), mid, account, subject or "", date or 0,
                       f"à {dest}" if sent else sender or "", bool(sent))

    def thread(self, ref: str, page: int, size: int):
        selected = self.cache.one(ref) or self.cache.sent_one(ref)
        if selected is None:
            return Page((), 0)
        account, mid = fit(selected.account, ACCOUNT), fit(split_ref(selected.message_id)[1], MID)
        letters = index()
        scoped = select(letters).where(letters.c.account == account).cte("scoped")
        sc = scoped.c
        edges = union(select(sc.message_id.label("a"), sc.parent.label("b")).where(sc.parent != ""),
                      select(sc.parent, sc.message_id).where(sc.parent != "")).cte("edges")
        # l'ancre vient d'une colonne (pas d'un paramètre) : sous MariaDB, le type d'une CTE récursive est celui de
        # son ancre
        connected = select(sc.message_id.label("id")).where(sc.message_id == mid).cte("connected", recursive=True)
        reached = connected.alias("reached")
        connected = connected.union(select(edges.c.b).where(edges.c.a == reached.c.id))
        result = select(scoped).where(sc.message_id.in_(select(connected.c.id))).cte("result")
        return self.page(result, ("account", "message_id", "subject", "date", "sender", "dest", "sent", "ref"),
                         lambda c: (c.date, c.account, c.message_id), self.hit, page, size)

    def contacts(self, account: str, text: str, own: tuple[str, ...], page: int, size: int):
        letters = index()
        scoped = select(letters).where(letters.c.account == fit(account, ACCOUNT) if account else true()) \
            .cte("scoped")
        sc = scoped.c
        # l'expéditeur d'une lettre reçue, les destinataires (copies comprises) d'une lettre partie
        parties = select(R.address, R.name, R.fold_who, case((sc.sent == 0, 1), else_=0).label("received"),
                         case((sc.sent == 1, 1), else_=0).label("sent"), sc.date) \
            .select_from(scoped).join(R, and_(R.kind == sc.local, R.owner == sc.rid)) \
            .where(or_(and_(sc.sent == 0, R.role == FROM), and_(sc.sent == 1, R.role == TO)),
                   R.address.not_in(sorted({fit(a.lower(), ADDRESS) for a in own}))).cte("parties")
        p = parties.c
        grouped = select(p.address, func.max(p.name).label("name"), func.sum(p.received).label("received"),
                         func.sum(p.sent).label("sent"), func.max(p.date).label("last")) \
            .group_by(p.address).cte("grouped")
        # le nom montré est le plus grand ; on cherche dans ce nom-là (et l'adresse), repliés à l'écriture
        named = select(p.address, p.fold_who, func.row_number().over(partition_by=p.address, order_by=p.name.desc())
                       .label("pick")).cte("named")
        result = select(grouped).join(named, named.c.address == grouped.c.address) \
            .where(named.c.pick == 1, _contains(named.c.fold_who, text)).cte("result")
        return self.page(result, ("address", "name", "received", "sent", "last"), lambda c: (c.last.desc(), c.address),
                         lambda r: Contact(r.address, r.name, int(r.received), int(r.sent), int(r.last)), page, size)

    def drafts(self, text: str, page: int, size: int):
        result = select(D.id.label("rid"), D.updated).where(_contains(D.fold_search, text)).subquery("result")
        return self.page(result, ("rid",), lambda c: (c.updated.desc(), c.rid.desc()),
                         lambda r: self.cache.draft_at_row(r.rid), page, size)
