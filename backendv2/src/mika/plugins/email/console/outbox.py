"""Ce qui est parti de ses boîtes (écrit par elle après accord, ou depuis la
console) et les adresses de ses échanges."""

from __future__ import annotations

import email.utils
from typing import Any

from mika.contracts import email as c
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Block,
    Column,
    InspectContext,
    Nav,
    NavItem,
    Note,
    Param,
    Ref,
    Row,
    Table,
    Text,
    When,
    paginate,
)
from mika.plugins.email import EMAIL, EmailState, name_of
from mika.plugins.email.console.common import (
    CACHE_SHOWN,
    NO_PORT,
    PAGE,
    SECTION,
    author,
    clip,
    fold,
    gone,
    mail_key,
)


def _accounts_nav(port: Any, account: str, view: str) -> list[Block]:
    accounts = port.accounts()
    if len(accounts) < 2:
        return []
    base = f"/inspecteur/{SECTION}/{view}"
    items = [NavItem("Toutes", Ref("local", base, "Toutes"), active=not account)]
    items += [NavItem(a.name, Ref("local", base, a.name, (("compte", a.key),)), active=account == a.key)
              for a in accounts]
    return [Nav(tuple(items), title="Boîtes")]


def _pending_note(frame: Frame) -> Note | None:
    waiting = len(frame.get(c.DRAFTS))
    if not waiting:
        return None
    return Note(f"{waiting} brouillon(s) d'elle attend(ent) ton accord : voir l'onglet Brouillons.", tone="warn")


@EMAIL.inspect("envoyes", title="Envoyés", section=SECTION, order=30,
               description="Ce qui est parti de ses boîtes : écrit par elle (après accord) ou depuis la console.",
               params=[Param("compte", "Boîte", kind="hidden"),
                       Param("q", "Recherche", placeholder="objet, destinataire, texte")])
def _outbox(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mail")
    blocks: list[Block] = []
    pending = _pending_note(frame)
    if pending is not None:
        blocks.append(pending)
    if port is None:
        return [*blocks, Note(NO_PORT, tone="muted")]
    account = ctx.value("compte") or ""
    blocks += _accounts_nav(port, account, "envoyes")
    query = fold(ctx.value("q") or "")
    sent = [m for m in gone(port, account=account)
            if not query or query in fold(f"{m.subject} {m.to} {m.body[:2000]}")]
    page, pager = paginate(sent, ctx.pager(size=PAGE))
    several = len(port.accounts()) > 1
    rows = []
    for m in page:
        answered = port.cached_one(m.in_reply_to) if m.in_reply_to else None
        d = port.draft(m.draft) if m.draft else None
        edited = d is not None and bool(d.edited_by)
        by = d.edited_by if d is not None and edited else m.by
        cells: list[Any] = [Text(clip(m.subject) or "(sans objet)"), Text(clip(m.to, 80))]
        if several:
            cells.append(Text(m.account, "muted"))
        cells += [When(m.date) if m.date else None, author(frame, by, edited=edited),
                  Ref.subject("mail", mail_key(answered.ref), clip(answered.subject, 60)) if answered is not None
                  else "—"]
        rows.append(Row(tuple(cells), href=Ref.subject("mail", mail_key(m.message_id), clip(m.subject) or "(sans objet)")))
    columns: list[Any] = ["objet", "à"] + ([Column("boîte", "fit")] if several else [])
    columns += [Column("parti", "fit"), Column("écrit par", "fit"), "en réponse à"]
    blocks.append(Table(tuple(columns), tuple(rows), title=f"Envoyés ({len(sent)})", pager=pager,
                        empty="aucun envoi ne correspond" if query else "rien n'est encore parti de sa boîte"))
    return blocks


def _book(port: Any, account: str) -> list[dict[str, Any]]:
    book: dict[str, dict[str, Any]] = {}
    own = {a.address for a in port.accounts()}
    for m in port.cached(CACHE_SHOWN, account=account):
        if not m.address or m.address in own:
            continue
        entry = book.setdefault(m.address, {"address": m.address, "name": "", "received": 0, "sent": 0, "last": 0})
        entry["received"] += 1
        entry["name"] = entry["name"] or name_of(m.sender)
        entry["last"] = max(entry["last"], m.date)
    for m in gone(port, account=account):
        for name, address in email.utils.getaddresses([m.to]):
            address = address.lower()
            if "@" not in address or address in own:
                continue
            entry = book.setdefault(address, {"address": address, "name": "", "received": 0, "sent": 0, "last": 0})
            entry["sent"] += 1
            entry["name"] = entry["name"] or name
            entry["last"] = max(entry["last"], m.date)
    return sorted(book.values(), key=lambda e: (-e["last"], e["address"]))


@EMAIL.inspect("contacts", title="Contacts", section=SECTION, order=40,
               description="Les adresses de ses échanges, avec leur volume ; écrire à l'une d'elles.",
               params=[Param("compte", "Boîte", kind="hidden"), Param("q", "Recherche", placeholder="nom ou adresse")])
def _contacts(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mail")
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    account = ctx.value("compte") or ""
    query = fold(ctx.value("q") or "")
    book = [e for e in _book(port, account) if not query or query in fold(f"{e['name']} {e['address']}")]
    page, pager = paginate(book, ctx.pager(size=PAGE))
    rows = tuple(Row((Text(clip(e["name"], 60) or "—"), Text(e["address"], "mono"), Text(str(e["received"]), "num"),
                      Text(str(e["sent"]), "num"), When(e["last"]) if e["last"] else "—"),
                     href=Ref("local", f"/inspecteur/{SECTION}/reception", "",
                              tuple((k, v) for k, v in (("compte", account), ("dossier", "*"), ("de", e["address"]))
                                    if v)),
                     detail=(ActionSlot("email.ecrire", (("to", e["address"]),) + ((("account", account),) if account
                                                                                   else ()),
                                        title=f"Écrire à {e['address']}", compact=True),))
                 for e in page)
    return [*_accounts_nav(port, account, "contacts"),
            Table(("nom", "adresse", Column("reçus", "num"), Column("envoyés", "num"), Column("dernier échange", "fit")),
                  rows, title=f"Contacts ({len(book)})", pager=pager,
                  empty="aucun contact ne correspond" if query else "aucun échange encore",
                  caption="Un clic ouvre ses mails ; « voir les détails » pour lui écrire.")]
