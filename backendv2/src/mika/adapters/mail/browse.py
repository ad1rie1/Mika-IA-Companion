"""Consultation SQL du courrier : filtrer et compter avant de lire les corps.

Les conversations, contacts et envoyés parcourent tout le cache. Seule la
page demandée devient des objets Python. Les CTE des historiques ne portent
que les en-têtes, jamais tous les corps ou toutes les pièces jointes.
"""

from __future__ import annotations

import json
from typing import Any

from mika.ports.mail import Contact, MailHit, MailQuery, mail_ref, split_ref
from mika.ports.paging import Page, fold_text

# Les messages reçus et les envois locaux peuvent décrire le même mail.
# La copie locale fait autorité pour les envois ; INBOX pour les autres copies.
INDEX = """
WITH RECURSIVE candidates AS (
  SELECT rowid AS rid, 0 AS local, account, message_id, subject, date, sender, address,
         dest, cc, mail_mid(in_reply_to) AS parent, (folder='INBOX') AS priority,
         (EXISTS(SELECT 1 FROM folders f WHERE f.account=messages.account AND f.name=messages.folder
                 AND f.role='sent') OR lower(folder) IN ('sent','sent items','envoyés')) AS is_sent
  FROM messages
  UNION ALL
  SELECT rowid, 1, account, mail_mid(message_id), subject, date, '', '', dest, cc,
         mail_mid(in_reply_to), 2, 1 FROM envoyes
), ranked AS (
  SELECT *, MAX(is_sent) OVER(PARTITION BY account,message_id) AS sent,
         ROW_NUMBER() OVER(PARTITION BY account,message_id ORDER BY priority DESC,date DESC,rid DESC) AS rank
  FROM candidates
), letters AS (SELECT * FROM ranked WHERE rank=1)
"""


def conditions(query: MailQuery) -> tuple[str, list[Any]]:
    clauses, args = [], []
    for name, value in (("account", query.account), ("folder", query.folder)):
        if value:
            clauses.append(f"{name}=?")
            args.append(value)
    for name, value in (("seen", query.seen), ("flagged", query.flagged)):
        if value is not None:
            clauses.append(f"{name}=?")
            args.append(int(value))
    for expr, value in (("subject || ' ' || sender || ' ' || body", query.text),
                        ("sender || ' ' || address", query.sender)):
        if value:
            clauses.append(f"instr(fold({expr}),?)>0")
            args.append(fold_text(value))
    for refs, negate in ((query.refs, False), (query.exclude, True)):
        if refs is not None and (refs or not negate):
            clauses.append(f"mail_ref(account,message_id) {'NOT IN' if negate else 'IN'} (SELECT value FROM json_each(?))")
            args.append(json.dumps(refs))
    return " AND ".join(clauses) or "1", args


class Browse:
    def __init__(self, cache):
        self.cache, self.db = cache, cache._db

    def page(self, sql: str, args, select: str, order: str, load, page: int, size: int):
        total = int(self.db.execute(sql + " SELECT COUNT(*) FROM result", args).fetchone()[0])
        page, size, offset = Page.bounds(total, page, size)
        rows = self.db.execute(sql + f" SELECT {select} FROM result ORDER BY {order} LIMIT ? OFFSET ?",
                               (*args, size, offset)).fetchall()
        return Page(tuple(load(row) for row in rows), total, page, size)

    def messages(self, query: MailQuery, page: int, size: int):
        where, args = conditions(query)
        return self.page(f"WITH result AS (SELECT rowid AS rid,date FROM messages WHERE {where})", args,
                         "rid", "date DESC,rid DESC", lambda r: self.cache.at_row(r[0]), page, size)

    def outgoing(self, query: MailQuery, page: int, size: int):
        clauses, args = ["sent=1"], []
        if query.account:
            clauses.append("account=?")
            args.append(query.account)
        if query.text:
            clauses.append("instr(fold(subject || ' ' || dest || ' ' || CASE WHEN local=1 THEN "
                           "(SELECT body FROM envoyes WHERE rowid=letters.rid) ELSE "
                           "(SELECT body FROM messages WHERE rowid=letters.rid) END),?)>0")
            args.append(fold_text(query.text))
        sql = INDEX + ", result AS (SELECT * FROM letters WHERE " + " AND ".join(clauses) + ")"
        return self.page(sql, args, "rid,local", "date DESC,account,message_id",
                         lambda r: (self.cache.at_row(r[0], sent=bool(r[1])), bool(r[1])), page, size)

    def hits(self, text: str, limit: int, offset: int, *, count: bool = False):
        # Recherche dans tout le contenu ; on ne matérialise que les en-têtes de la page.
        sql = INDEX + " SELECT account,message_id,subject,date,sender,dest,sent FROM letters WHERE " \
            "instr(fold(subject || ' ' || sender || ' ' || dest || ' ' || CASE WHEN local=1 THEN " \
            "(SELECT body FROM envoyes WHERE rowid=letters.rid) ELSE " \
            "(SELECT body FROM messages WHERE rowid=letters.rid) END),?)>0 " \
            "ORDER BY date DESC,account,message_id LIMIT ? OFFSET ?"
        if count:
            return self.db.execute("SELECT COUNT(*) FROM (" + sql.rsplit("ORDER BY date DESC,account,message_id", 1)[0] + ")",
                                    (fold_text(text),)).fetchone()[0]
        return [self.hit(r) for r in self.db.execute(sql, (fold_text(text), max(1, min(100, limit)), max(0, offset)))]

    def search_count(self, text: str):
        return self.hits(text, 1, 0, count=True)

    @staticmethod
    def hit(r):
        account, mid, subject, date, sender, dest, sent = r
        return MailHit(mail_ref(account, mid), mid, account, subject or "", date or 0,
                       f"à {dest}" if sent else sender or "", bool(sent))

    def thread(self, ref: str, page: int, size: int):
        selected = self.cache.one(ref) or self.cache.sent_one(ref)
        if selected is None:
            return Page((), 0)
        account, mid = selected.account, split_ref(selected.message_id)[1]
        sql = INDEX + """, scoped AS (SELECT * FROM letters WHERE account=?),
        edges AS (SELECT message_id a,parent b FROM scoped WHERE parent!=''
                  UNION SELECT parent a,message_id b FROM scoped WHERE parent!=''),
        connected(id) AS (VALUES(?) UNION SELECT e.b FROM edges e JOIN connected c ON e.a=c.id),
        result AS (SELECT * FROM scoped WHERE message_id IN (SELECT id FROM connected))"""
        return self.page(sql, (account, mid), "account,message_id,subject,date,sender,dest,sent",
                         "date,account,message_id", self.hit, page, size)

    def contacts(self, account: str, text: str, own: tuple[str, ...], page: int, size: int):
        sql = INDEX + """, scoped AS (SELECT * FROM letters WHERE (?='' OR account=?)),
        addresses AS (
          SELECT lower(address) address, sender name, 1 received, 0 sent, date FROM scoped WHERE sent=0
          UNION ALL
          SELECT json_extract(j.value,'$[1]'), json_extract(j.value,'$[0]'),0,1,date FROM scoped,
                 json_each(mail_addresses(trim(COALESCE(dest,'') || ',' || COALESCE(cc,''), ','))) j WHERE sent=1
        ), grouped AS (
          SELECT address,MAX(name) name,SUM(received) received,SUM(sent) sent,MAX(date) last FROM addresses
          WHERE instr(address,'@')>0 AND address NOT IN (SELECT value FROM json_each(?)) GROUP BY address
        ), result AS (SELECT * FROM grouped WHERE instr(fold(name || ' ' || address),?)>0)"""
        return self.page(sql, (account, account, json.dumps([a.lower() for a in own]), fold_text(text)), "*",
                         "last DESC,address", lambda r: Contact(*r), page, size)

    def drafts(self, text: str, page: int, size: int):
        sql = "WITH result AS (SELECT rowid AS rid,updated FROM drafts WHERE instr(fold(subject || ' ' || dest),?)>0)"
        return self.page(sql, (fold_text(text),), "rid", "updated DESC,rid DESC",
                         lambda r: self.cache.draft_at_row(r[0]), page, size)
