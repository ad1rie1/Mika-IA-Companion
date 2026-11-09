"""La boîte : les comptes, leurs dossiers, ce qui y est — et ce qu'elle en a remarqué.

On navigue entre comptes et dossiers par des puces (le nombre de non-lus à
côté) ; la liste vient du cache de l'adaptateur (jamais un relevé à
l'affichage). Un dossier qu'elle ne relève pas se relit à la demande
(« Relire ce dossier »).
"""

from __future__ import annotations

from typing import Any

from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    ActionSlot,
    Badge,
    Block,
    Column,
    InspectContext,
    Nav,
    NavItem,
    Note,
    Pager,
    Param,
    Ref,
    Row,
    Table,
    Text,
    When,
    is_table_choice,
)
from mika.plugins.email import EMAIL, EmailParams, EmailState, name_of, params_of
from mika.plugins.email.console.common import (
    BOX_PAGE,
    SECTION,
    VIEWS,
    WHOSE,
    YOURS,
    account_scope,
    add_account,
    answered,
    clip,
    fresh_important,
    her_badge,
    important,
    mail_key,
    owner_name,
    scoped,
    state_badge,
    to_answer,
    unread,
    view_link,
    whose,
    workspace,
)
from mika.ports.mail import MailQuery

#: ce qu'on filtre ; « non lus » : par toi (le drapeau du serveur), pas par elle (ADR 0175)
STATES = (("non_lus", "non lus"), ("importants", "importants, non lus"), ("a_traiter", "à traiter (réponse attendue)"),
          ("suivis", "suivis (drapeau)"), ("remarques", "remarqués"), ("pas_remarques", "pas remarqués"))
INBOX = "INBOX"


def _in_box(port: Any, keys: list[str], folder: str) -> int:
    """Combien de mails le cache de la boîte garde dans ce dossier (« * » : tous ses dossiers),
    selon les comptes que tient l'adaptateur (sans rien relire)."""
    wanted = None if folder == "*" else (folder or INBOX)
    return sum(f.total for key in keys for f in port.folders(key) if wanted is None or f.name == wanted)


def _list(s: EmailState, ctx: InspectContext, p: EmailParams, port: Any, account: str, folder: str,
          several: bool, total: int) -> tuple[Table, int]:
    """La liste du dossier, et combien de mails ont été relus du cache pour la faire."""
    state, query, sender = ctx.value("etat") or "", ctx.value("q") or "", ctx.value("de") or ""
    marked = tuple(s.mails)
    refs: tuple[str, ...] | None = None
    if state == "importants":
        refs = tuple(k for k, m in s.mails.items() if important(m, p))
    elif state == "a_traiter":  # répondu ailleurs : le serveur le sait, même quand elle l'avait déjà lu
        refs = tuple(k for k, m in s.mails.items() if to_answer(m) and not answered(port, k))
    elif state == "remarques":
        refs = marked
    exclude = marked if state == "pas_remarques" else ()
    request = ctx.pager(size=BOX_PAGE)
    result = port.messages_page(MailQuery(account=account, folder="" if folder == "*" else (folder or INBOX),
        text=query, sender=sender, seen=False if state in ("non_lus", "importants") else None,
        flagged=True if state == "suivis" else None, refs=refs, exclude=exclude), request.number, request.size)
    page = [(m, s.mails.get(m.ref)) for m in result.items]
    pager = Pager(number=result.number, size=result.size, total=result.total)
    context_values = {k: v for k, v in ctx.params.items()
                      if k in ("compte", "dossier", "etat", "de", "q", "page", "taille", WHOSE)}
    context_values.update((k, v) for k, v in ctx.params.items() if is_table_choice(k, v))
    if "page" in context_values:
        context_values["page"] = str(pager.number)
    context = tuple(context_values.items())
    back = view_link("reception", "", context)
    rows = []
    for m, seen in page:
        label = port.account(m.account)
        sender_label = name_of(m.sender) or m.address
        cells: list[Any] = [Text(clip(m.subject, 180) or "(sans objet)", secondary=clip(m.body, 160),
                                emphasis=unread(m, seen)),
                           Text(sender_label, secondary=label.name if label and several else m.address)]
        cells += [When(m.date) if m.date else None,
                  Text("★ Suivi · " + ("Non lu" if unread(m, seen) else "Lu")) if m.flagged else state_badge(seen, m, p),
                  her_badge(seen), Badge("réponse attendue", "warn") if to_answer(seen) and not m.answered else None]
        ref = Ref.subject("mail", mail_key(m.ref), m.subject or "(sans objet)")
        rows.append(Row(tuple(cells), href=Ref(ref.kind, ref.key, ref.text, context, back)))
    columns: list[Any] = [Column("Message", role="title"), "Expéditeur", Column("Date", "fit"), Column("État", "fit", role="badge"),
                          Column("Elle", "fit", role="badge"), Column("Son tri", "fit", role="badge")]
    filtered = state or query or sender
    if state in VIEWS:  # une vue de la barre de côté (« À traiter », « Suivis ») : son nom
        where = VIEWS[state]
    elif folder == "*":
        where = "Tous les dossiers"
    elif account:
        where = next((f.label for f in port.folders(account) if f.name == (folder or INBOX)), folder or "Réception")
    else:
        where = "Réception" if folder in ("", INBOX) else folder
    caption = "Messages synchronisés · ouvre un message pour le lire et y répondre."
    return Table(tuple(columns), tuple(rows), title=where, pager=pager,
                 empty="aucun mail ne correspond à ces filtres" if filtered else "rien dans ce dossier",
                 caption=caption, layout="list", link_label="Lire le message"), result.total


@EMAIL.inspect("reception", title="Réception", section=SECTION, order=10, badge=fresh_important,
               description="Lis et traite les messages de toutes tes boîtes, ou choisis un compte et un dossier.",
               params=[Param("compte", "Boîte", kind="hidden"), Param("dossier", "Dossier", kind="hidden"),
                       Param("etat", "État", kind="select", choices=STATES),
                       Param("de", "Expéditeur", placeholder="nom ou adresse"),
                       Param("q", "Recherche", placeholder="objet, expéditeur, texte")])
def _box(s: EmailState, frame: Frame, ctx: InspectContext) -> list[Block]:
    port = scoped(ctx.ports.get("mail"), ctx)
    p = params_of(frame)
    filters = (Param("etat", "Afficher", kind="select", choices=STATES),
               Param("de", "Expéditeur", placeholder="nom ou adresse"),
               Param("q", "Recherche", placeholder="objet ou contenu du message"))
    if port is not None and not port.accounts() and whose(ctx):  # personne : rien de ses boîtes, le sélecteur reste
        name = owner_name(frame, "" if whose(ctx) == YOURS else whose(ctx))
        return [workspace(port, ctx, [Note(f"Aucune boîte n'est à {name}. Dans Courrier › Paramètres, une boîte se "
                                           "donne à quelqu'un par « À qui ».", title="Aucune boîte"),
                                      Nav((NavItem("Ajouter un compte", add_account()),))], state=s, frame=frame)]
    if port is None or not port.accounts():
        return [workspace(port, ctx, [Note("Ajoute une boîte aux lettres dans Courrier › Paramètres (en haut "
                                           "à droite) pour recevoir et envoyer des messages.",
                                           title="Aucun compte de messagerie"),
                                      Nav((NavItem("Ajouter un compte", add_account()),))], state=s)]
    account = account_scope(port, ctx)
    if account and port.account(account) is None:
        return [workspace(port, ctx, [Note("Ce compte n'existe plus. Choisis une boîte dans la liste.", tone="warn")],
                          state=s, frame=frame)]
    folder = ctx.param("dossier") or INBOX
    total = _in_box(port, [account] if account else [a.key for a in port.accounts()], folder)
    table, _ = _list(s, ctx, p, port, account, folder, not account and len(port.accounts()) > 1, total)
    # ranger ce qu'on a coché (la boîte dessinée en fait des cases sur chaque ligne et une barre au-dessus), puis,
    # au bout de la liste, remonter plus loin dans un dossier
    items: list[Block] = [ActionSlot("email.ranger", title="Ranger la sélection"), table]
    chosen = port.account(account) if account else None
    if chosen is not None and chosen.ready and folder != "*" and ctx.value("etat") not in VIEWS:
        items.append(ActionSlot("email.historique", (("compte", account), ("dossier", folder)),
                                title="Charger des messages plus anciens", presentation="button"))
    return [workspace(port, ctx, items, filters=filters, folders=True, state=s, frame=frame)]
