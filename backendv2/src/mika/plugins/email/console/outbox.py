"""Ce qui est parti de ses boîtes (écrit par elle après accord, ou depuis la
console) et les adresses de ses échanges."""

from __future__ import annotations

from typing import Any

from mika.contracts import email as c
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Column,
    InspectContext,
    Note,
    Pager,
    Param,
    Ref,
    Row,
    Table,
    Text,
    When,
)
from mika.plugins.email import EMAIL, EmailState, name_of
from mika.plugins.email.console.common import (
    NO_PORT,
    PAGE,
    SECTION,
    account_scope,
    author,
    clip,
    fold,
    mail_key,
    workspace,
)
from mika.ports.mail import MailQuery, mail_ref, split_ref


def _pending_note(frame: Frame, account: str) -> Note | None:
    waiting = sum(1 for d in frame.get(c.DRAFTS) if not account or d.account == account)
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
    account = account_scope(port, ctx)
    pending = _pending_note(frame, account)
    if pending is not None:
        blocks.append(pending)
    if port is None:
        return [*blocks, Note(NO_PORT, tone="muted")]
    query = fold(ctx.value("q") or "")
    request = ctx.pager(size=PAGE)
    result = port.outgoing_page(MailQuery(account=account, text=query), request.number, request.size)
    page = result.items
    pager = Pager(number=result.number, size=result.size, total=result.total)
    several = len(port.accounts()) > 1
    rows = []
    for m, local in page:
        answered = port.cached_one(mail_ref(m.account, split_ref(m.in_reply_to)[1])) if m.in_reply_to else None
        d = port.draft(m.draft) if local and m.draft else None
        edited = d is not None and bool(d.edited_by)
        by = d.edited_by if d is not None and edited else m.by if local else ""
        cells: list[Any] = [Text(clip(m.subject) or "(sans objet)", secondary=clip(m.body, 140)), Text(clip(m.to, 80))]
        if several:
            cells.append(Text(m.account, "muted"))
        cells += [When(m.date) if m.date else None, author(frame, by, edited=edited) if local else Badge("Synchronisé", "muted"),
                  Ref.subject("mail", mail_key(answered.ref), clip(answered.subject, 60)) if answered is not None
                  else "—"]
        rows.append(Row(tuple(cells), href=Ref.subject("mail", mail_key(m.ref), clip(m.subject) or "(sans objet)")))
    columns: list[Any] = ["objet", "à"] + ([Column("boîte", "fit")] if several else [])
    columns += [Column("parti", "fit"), Column("écrit par", "fit"), "en réponse à"]
    blocks.append(Table(tuple(columns), tuple(rows), title="Envoyés", pager=pager,
                        empty="aucun envoi ne correspond" if query else "rien n'est encore parti de sa boîte",
                        caption="Tous les envois conservés et les messages synchronisés du dossier Envoyés."))
    return [workspace(port, ctx, blocks, view="envoyes", filters=(Param("q", "Recherche", placeholder="objet, destinataire, texte"),))]


@EMAIL.inspect("contacts", title="Contacts", section=SECTION, order=40,
               description="Les adresses de ses échanges, avec leur volume ; écrire à l'une d'elles.",
               params=[Param("compte", "Boîte", kind="hidden"), Param("q", "Recherche", placeholder="nom ou adresse")])
def _contacts(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mail")
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    account = account_scope(port, ctx)
    query = fold(ctx.value("q") or "")
    request = ctx.pager(size=PAGE)
    result = port.contacts_page(account, query, request.number, request.size)
    page = [dict(address=e.address, name=name_of(e.name), received=e.received, sent=e.sent, last=e.last) for e in result.items]
    pager = Pager(number=result.number, size=result.size, total=result.total)
    rows = tuple(Row((Text(clip(e["name"], 60) or "—"), Text(e["address"], "mono"), Text(str(e["received"]), "num"),
                      Text(str(e["sent"]), "num"), When(e["last"]) if e["last"] else "—"),
                     href=Ref("local", f"/inspecteur/{SECTION}/reception", "",
                              tuple((k, v) for k, v in (("compte", account), ("dossier", "*"), ("de", e["address"]))
                                    if v)),
                     detail=(ActionSlot("email.ecrire", (("to", e["address"]),) + ((("account", account),) if account
                                                                                   else ()),
                                        title=f"Écrire à {e['address']}", compact=True),))
                 for e in page)
    return [workspace(port, ctx, [Table(("nom", "adresse", Column("reçus", "num"), Column("envoyés", "num"), Column("dernier échange", "fit")),
                  rows, title="Contacts", pager=pager,
                  empty="aucun contact ne correspond" if query else "aucun échange encore",
                  caption="Comptés sur tous les messages synchronisés et les envois conservés. Un clic ouvre les échanges ; déplie une ligne pour écrire.")], view="contacts", filters=(Param("q", "Recherche", placeholder="nom ou adresse"),))]
