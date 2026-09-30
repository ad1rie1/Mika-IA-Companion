"""La boîte : les comptes, leurs dossiers, ce qui y est — et ce qu'elle en a remarqué.

On navigue entre comptes et dossiers par des puces (le nombre de non-lus à
côté) ; la liste vient du cache de l'adaptateur (jamais un relevé à
l'affichage). Un dossier qu'elle ne relève pas se relit à la demande
(« Relire ce dossier »).
"""

from __future__ import annotations

from typing import Any

from mika.contracts import email as c
from mika.kernel.clock import HOUR, MINUTE
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Block,
    Cell,
    Column,
    Disclosure,
    Fields,
    InspectContext,
    Nav,
    NavItem,
    Note,
    Param,
    Ref,
    Row,
    Stat,
    Stats,
    Table,
    Text,
    When,
    paginate,
)
from mika.plugins.email import EMAIL, KEEP, EmailParams, EmailState, name_of, params_of
from mika.plugins.email.console.common import (
    CACHE_SHOWN,
    PAGE,
    SECTION,
    TODAY_MAX,
    add_account,
    box_link,
    box_note,
    clip,
    day_start,
    fold,
    fresh_important,
    important,
    mail_key,
    pertinence,
    since,
    state_badge,
    unread,
)

STATES = (("non_lus", "non lus"), ("importants", "importants, non lus"), ("suivis", "suivis (drapeau)"),
          ("remarques", "remarqués"), ("pas_remarques", "pas remarqués"))
INBOX = "INBOX"


def _in_box(port: Any, keys: list[str], folder: str) -> int:
    """Combien de mails le cache de la boîte garde dans ce dossier (« * » : tous ses dossiers),
    selon les comptes que tient l'adaptateur (sans rien relire)."""
    wanted = None if folder == "*" else (folder or INBOX)
    return sum(f.total for key in keys for f in port.folders(key) if wanted is None or f.name == wanted)


def _in_box_value(total: int, read: int) -> Cell:
    """Le vrai total du dossier ; s'il n'est pas connu (moins que ce qui a été relu), ce qui a été
    relu — « 500+ » quand la relecture a buté sur sa borne."""
    if total >= read:
        return total
    return f"{read}+" if read >= CACHE_SHOWN else read


def _stats(s: EmailState, frame: Frame, ctx: InspectContext, p: EmailParams, in_box: Cell = 0) -> Stats:
    waiting = frame.get(c.UNREAD)
    urgent = sum(1 for m in waiting if m.importance >= p.mention_from)
    today = since(ctx, c.NOTICED, day_start(frame), TODAY_MAX)
    last = max((m.at for m in s.mails.values()), default=0)
    drafts = len(frame.get(c.DRAFTS))
    return Stats((
        Stat("non lus", len(waiting), sub=f"dont {urgent} important(s)" if waiting else "remarqués, pas encore lus",
             tone="warn" if urgent else ""),
        Stat("remarqués aujourd'hui", f"{len(today)}+" if len(today) >= TODAY_MAX else len(today)),
        Stat("brouillons à décider", drafts, tone="warn" if drafts else "",
             href=Ref("local", f"/inspecteur/{SECTION}/brouillons", "") if drafts else None),
        Stat("dernier mail remarqué", When(last) if last else "jamais",
             sub=f"relève toutes les {p.poll_every_us // MINUTE} min, éveillée"),
        Stat("dans la boîte", in_box, sub="gardés par le relevé"),
    ))


def _navigation(port: Any, account: str, folder: str) -> list[Block]:
    accounts = port.accounts()
    out: list[Block] = []
    if len(accounts) > 1:
        items = [NavItem("Toutes", box_link("Toutes", folder=folder if folder != INBOX else ""), active=not account)]
        for a in accounts:
            inbox = next((f for f in port.folders(a.key) if f.role == "inbox"), None)
            items.append(NavItem(a.name, box_link(a.name, account=a.key), count=inbox.unseen if inbox and inbox.unseen
                                 else None, active=account == a.key, tone="" if a.ready else "warn"))
        out.append(Nav(tuple(items), title="Boîtes"))
    key = account or (accounts[0].key if len(accounts) == 1 else "")
    if key or len(accounts) == 1:
        folders = port.folders(key)
        items = [NavItem(f.label, box_link(f.label, account=account, folder=f.name), count=f.unseen or None,
                         active=(folder or INBOX) == f.name) for f in folders]
        items.append(NavItem("Tous les dossiers", box_link("Tous", account=account, folder="*"), active=folder == "*"))
        out.append(Nav(tuple(items), title="Dossiers"))
    return out


def _keep(state: str, m: Any, seen: Any, p: EmailParams) -> bool:
    if state == "non_lus":
        return unread(m, seen)
    if state == "importants":
        return seen is not None and unread(m, seen) and important(seen, p)
    if state == "suivis":
        return m.flagged
    if state == "remarques":
        return seen is not None
    if state == "pas_remarques":
        return seen is None
    return True


def _quick(m: Any, seen: Any) -> tuple[Block, ...]:
    """Les gestes rapides d'une ligne (sur le serveur, et elle le sait quand ça la concerne)."""
    ref = m.ref
    slots = [ActionSlot("email.ranger", (("mail", ref), ("geste", "non_lu" if not unread(m, seen) else "lu"),
                                         ("_bouton", "Marquer non lu" if not unread(m, seen) else "Marquer lu")),
                        compact=True),
             ActionSlot("email.ranger", (("mail", ref), ("geste", "ne_plus_suivre" if m.flagged else "suivre"),
                                         ("_bouton", "Ne plus suivre" if m.flagged else "Suivre")), compact=True),
             ActionSlot("email.ranger", (("mail", ref), ("geste", "archiver"), ("_bouton", "Archiver")), compact=True),
             ActionSlot("email.ranger", (("mail", ref), ("geste", "corbeille"), ("_bouton", "Corbeille")),
                        compact=True)]
    return tuple(slots)


def _list(s: EmailState, ctx: InspectContext, p: EmailParams, port: Any, account: str, folder: str,
          several: bool, total: int) -> tuple[Table, int]:
    """La liste du dossier, et combien de mails ont été relus du cache pour la faire."""
    cached = port.cached(CACHE_SHOWN, account=account, folder="" if folder == "*" else (folder or INBOX))
    state, query, sender = ctx.value("etat") or "", fold(ctx.value("q") or ""), fold(ctx.value("de") or "")
    kept = []
    for m in cached:
        seen = s.mails.get(m.ref)
        if not _keep(state, m, seen, p):
            continue
        if query and query not in fold(f"{m.subject} {m.sender} {m.body[:2000]}"):
            continue
        if sender and sender not in fold(f"{m.sender} {m.address}"):
            continue
        kept.append((m, seen))
    page, pager = paginate(kept, ctx.pager(size=PAGE))
    rows = []
    for m, seen in page:
        cells: list[Any] = [Text(clip(m.subject) or "(sans objet)"), Text(clip(m.sender, 80))]
        if several:
            cells.append(Text(f"{m.account} · {m.folder}", "muted"))
        cells += [When(m.date) if m.date else None, state_badge(seen, m, p), pertinence(seen),
                  Text("★ suivi", tone="warn") if m.flagged else ""]
        rows.append(Row(tuple(cells), href=Ref.subject("mail", mail_key(m.ref), clip(m.subject) or "(sans objet)"),
                        tone="warn" if seen is not None and unread(m, seen) and important(seen, p) else "",
                        detail=_quick(m, seen)))
    columns: list[Any] = ["objet", "de"]
    if several:
        columns.append(Column("où", "fit"))
    columns += [Column("reçu", "fit"), Column("état", "fit"), Column("pertinence", "fit"), Column("", "fit")]
    filtered = state or query or sender
    if folder == "*":
        where = "Tous les dossiers"
    elif account:
        where = next((f.label for f in port.folders(account) if f.name == (folder or INBOX)), folder or "Réception")
    else:
        where = "Réception" if folder in ("", INBOX) else folder
    if len(cached) < CACHE_SHOWN:
        caption = "« voir les détails » : lu/non lu, suivre, archiver, corbeille."
    elif total > len(cached):
        caption = f"Seuls les {CACHE_SHOWN} plus récents des {total} mails du cache sont relus ici (filtres, pages)."
    else:
        caption = f"Seuls les {CACHE_SHOWN} mails les plus récents du cache sont relus ici (filtres, pages)."
    return Table(tuple(columns), tuple(rows), title=f"{where} ({len(kept)})", pager=pager,
                 empty="aucun mail ne correspond à ces filtres" if filtered else "rien dans ce dossier",
                 caption=caption), len(cached)


def _noticed(s: EmailState, ctx: InspectContext, p: EmailParams) -> Table:
    noticed, pager = paginate(sorted(s.mails.items(), key=lambda kv: -kv[1].seq),
                              ctx.pager("page_remarques", size=PAGE))
    texts = ctx.store.content([m.summary_ref for _, m in noticed if m.summary_ref])
    rows = tuple(Row((Text(clip(name_of(m.sender), 60)), When(m.at), Text(texts.get(m.summary_ref, "—"), clamp=200),
                      pertinence(m), "oui" if m.needs_reply else "non", state_badge(m, None, p),
                      Ref("event", str(m.seq), f"#{m.seq}")),
                     href=Ref.subject("mail", mail_key(k), clip(name_of(m.sender), 60), tab="remarque"))
                 for k, m in noticed)
    return Table(("de", Column("remarqué", "fit"), "ce qu'elle en a retenu", Column("pertinence", "fit"),
                  Column("réponse attendue", "fit"), Column("état", "fit"), Column("journal", "fit")), rows,
                 title="Ce qu'elle a remarqué", empty="elle n'a encore remarqué aucun mail", pager=pager,
                 caption=f"Elle garde les {KEEP} derniers mails remarqués, du plus récent au plus ancien.")


@EMAIL.inspect("reception", title="Boîte", section=SECTION, order=10, badge=fresh_important,
               description="Ses boîtes, leurs dossiers, ce qui y arrive — et ce qu'elle en a remarqué.",
               params=[Param("compte", "Boîte", kind="hidden"), Param("dossier", "Dossier", kind="hidden"),
                       Param("etat", "État", kind="select", choices=STATES),
                       Param("de", "Expéditeur", placeholder="nom ou adresse"),
                       Param("q", "Recherche", placeholder="objet, expéditeur, texte")])
def _box(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = ctx.ports.get("mail")
    p = params_of(frame)
    blocks: list[Block] = [box_note(port, p)]
    if port is None:
        return [*blocks, _stats(s, frame, ctx, p), _noticed(s, ctx, p)]
    accounts = port.accounts()
    if not accounts:
        return [*blocks, Fields((("pour commencer", add_account()),)), _stats(s, frame, ctx, p),
                _noticed(s, ctx, p)]
    account = ctx.value("compte") or ""
    if account and account not in {a.key for a in accounts}:
        blocks.append(Note(f"Boîte inconnue : « {clip(account, 40)} ».", tone="warn"))
        account = ""
    folder = ctx.value("dossier") or ""
    key = account or (accounts[0].key if len(accounts) == 1 else "")
    total = _in_box(port, [key] if key else [a.key for a in accounts], folder)
    table, read = _list(s, ctx, p, port, key, folder, len(accounts) > 1, total)
    blocks.append(_stats(s, frame, ctx, p, _in_box_value(total, read)))
    blocks += _navigation(port, account, folder)
    blocks.append(table)
    known = {f.name: f for f in port.folders(key)} if key else {}
    chosen = known.get(folder or INBOX)
    if key and chosen is not None and not chosen.polled:
        blocks.append(Note("Elle ne relève pas ce dossier : ce qui s'y trouve ne lui est jamais signalé.",
                           tone="muted"))
    if key and folder != "*":
        blocks.append(ActionSlot("email.relire", (("compte", key), ("dossier", folder or INBOX),
                                                  ("_bouton", "Relire ce dossier")), compact=True))
    # replié, sauf quand on y tourne les pages
    blocks.append(Disclosure("Ce qu'elle a remarqué", (_noticed(s, ctx, p),),
                             open=ctx.int_param("page_remarques", 1) > 1))
    blocks.append(Disclosure("Comment elle relève", (Fields((
        ("cadence", f"toutes les {p.poll_every_us // MINUTE} min, quand elle est éveillée"),
        ("à chaque relevé", f"{p.per_poll} mails au plus, dont {p.triage_per_poll} triés par le modèle"),
        ("important à partir de", f"{p.mention_from:.2f} de pertinence"),
        ("le dire à sa propriétaire", f"dans les {p.mention_within_us // HOUR} h, si elle est là"),
        ("ce qu'elle écrit attend un accord", "oui" if p.send_needs_approval else "non"),
        ("réponses préparées d'elle-même", ", ".join(p.autodraft) or "sur aucun compte"),
        ("ce que tu écris ici", "part tout de suite ; elle le sait"),
    )),)))
    return blocks
