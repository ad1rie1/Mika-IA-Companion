"""Ce qui est parti de ses boîtes (écrit par elle après accord, ou depuis la
console) et les adresses de ses échanges."""

from __future__ import annotations

from typing import Any

from mika.kernel.frame import Frame
from mika.kernel.inspect import (
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
from mika.plugins.email import EMAIL, EmailState
from mika.plugins.email.inspect.common import (
    BOX_PAGE,
    NO_PORT,
    SECTION,
    account_scope,
    author,
    clip,
    fold,
    mail_key,
    scoped,
    workspace,
)
from mika.ports.mail import MailQuery, mail_ref, split_ref


@EMAIL.inspect("envoyes", title="Envoyés", section=SECTION, order=30,
               description="Ce qui est parti de ses boîtes : écrit par elle (après accord) ou depuis la console.",
               params=[Param("compte", "Boîte", kind="hidden"),
                       Param("q", "Recherche", placeholder="objet, destinataire, texte")])
def _outbox(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = scoped(ctx.ports.get("mail"), ctx)
    blocks: list[Block] = []
    account = account_scope(port, ctx)
    if port is None:
        return [Note(NO_PORT, tone="muted")]
    query = fold(ctx.value("q") or "")
    request = ctx.pager(size=BOX_PAGE)
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
    columns: list[Any] = [Column("Objet", role="title"), "À"] + ([Column("Boîte", "fit")] if several else [])
    columns += [Column("Envoyé", "fit"), Column("Écrit par", "fit", role="badge"), "En réponse à"]
    blocks.append(Table(tuple(columns), tuple(rows), title="Envoyés", pager=pager,
                        empty="aucun envoi ne correspond" if query else "rien n'est encore parti de sa boîte",
                        caption="Tous les envois conservés et les messages synchronisés du dossier Envoyés.",
                        layout="list", link_label="Lire le message"))
    return [workspace(port, ctx, blocks, view="envoyes", filters=(Param("q", "Recherche", placeholder="objet, destinataire, texte"),),
                      state=s, frame=frame)]
