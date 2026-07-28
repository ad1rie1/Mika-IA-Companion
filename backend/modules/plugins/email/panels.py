"""Panneaux du module email pour GestionSystème.

Remplacent les ``ModuleView`` de l'ancien ``dashboard``, supprimées avec lui.

Trois différences avec les anciennes vues :

- **Un sélecteur de compte.** Une installation à plusieurs boîtes voyait tout
  mélangé : rien ne permettait de répondre à « qu'est-ce qui est arrivé sur
  *cette* adresse ». C'est le premier filtre, et il gouverne aussi les
  contacts (``Contact.accounts`` est un M2M, un contact peut appartenir à
  plusieurs boîtes).
- **Pas de panneau « Comptes ».** Les comptes s'éditent dans l'onglet
  Configuration de l'espace, qui écrit dans la même table
  (``EmailAccount``, via l'adaptateur ``email.accounts``). Les afficher aussi
  en lecture seule créait deux entrées « Comptes » côte à côte pour une seule
  chose.
- **Le détail est une URL.** Cliquer un message ajoute ``?message=<id>`` :
  l'écran se partage, et le retour arrière ferme la fiche.

Tout est rendu par le serveur à partir de cellules typées : ce module ne
produit aucun balisage, y compris pour un corps d'e-mail — qui est
précisément le contenu hostile que l'ancien rendu par ``innerHTML``
injectait tel quel.
"""
from __future__ import annotations

from GestionSysteme import panels as P
from GestionSysteme import tables

MAX_CORPS = 20_000


# ── Filtres partagés ────────────────────────────────────────────────────

def _comptes() -> list[tuple[str, str]]:
    from modules.plugins.email.models import EmailAccount

    return [
        (str(pk), nom or adresse)
        for pk, nom, adresse in EmailAccount.objects.order_by("name").values_list(
            "id", "name", "email_address",
        )
    ]


def _filtre_compte(fs, request):
    """Le sélecteur de compte. Absent quand il n'y a qu'une boîte : proposer
    de filtrer sur l'unique valeur possible est du bruit."""
    comptes = _comptes()
    if len(comptes) < 2:
        return None
    return fs.add(tables.select_filter(
        request, "compte", "Compte", comptes, all_label="Tous les comptes",
    ))


# ── Boîte de réception ──────────────────────────────────────────────────

def inbox(request):
    from modules.plugins.email.models import Email

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    compte = _filtre_compte(fs, request)
    sens = fs.add(tables.select_filter(
        request, "sens", "Sens",
        [("inbound", "reçus"), ("outbound", "envoyés")],
    ))
    etat = fs.add(tables.select_filter(
        request, "etat", "État", [("non_lus", "non lus"), ("lus", "lus")],
    ))
    recherche = fs.add(tables.search_filter(
        request, "q", "Recherche", placeholder="sujet, expéditeur, corps",
    ))

    qs = Email.objects.select_related("account")
    if compte is not None and compte.value:
        qs = qs.filter(account_id=compte.value)
    if sens.value:
        qs = qs.filter(direction=sens.value)
    if etat.value == "non_lus":
        qs = qs.filter(is_read=False)
    elif etat.value == "lus":
        qs = qs.filter(is_read=True)
    if recherche.value:
        from django.db.models import Q
        qs = qs.filter(
            Q(subject__icontains=recherche.value)
            | Q(from_address__icontains=recherche.value)
            | Q(body_text__icontains=recherche.value)
        )
    qs = qs.order_by("-email_date", "-id")

    page = tables.paginate(request, qs, per_page=fs.per_page)

    blocs = []
    fiche = _fiche_message(request)
    if fiche is not None:
        blocs.extend(fiche)

    blocs.append(P.Table(
        caption="Messages",
        filters=fs,
        columns=[
            P.Column("Date", align="fit"),
            P.Column("De"),
            P.Column("Sujet"),
            P.Column("Compte", align="fit"),
            P.Column("Priorité", align="fit"),
            P.Column("Lu", align="fit"),
        ],
        rows=[_ligne_message(request, e) for e in page.rows],
        page=page,
        empty="Aucun message ne correspond à ces filtres.",
    ))
    return P.Blocks(items=blocs)


def _ligne_message(request, e) -> P.Row:
    return P.Row(
        # Le lien conserve les filtres courants : ouvrir une fiche puis la
        # fermer doit ramener exactement la liste qu'on regardait.
        href=_lien_avec(request, message=e.pk),
        cells=(
            P.mono(_date(e.email_date), title=str(e.email_date or "")),
            P.text(e.from_address or "—", clamp=True),
            P.text(e.subject or "(sans sujet)", clamp=True),
            P.badge(e.account.name if e.account_id else "—"),
            P.badge(e.priority or "—", tone=_ton_priorite(e.priority)),
            P.boolean(e.is_read, yes="lu", no="non lu"),
        ),
    )


def _ton_priorite(priorite: str | None) -> str:
    return {"high": "danger", "urgent": "danger", "low": ""}.get(
        (priorite or "").lower(), "",
    )


def _fiche_message(request):
    """Fiche d'un message, quand ``?message=<id>`` est présent."""
    from modules.plugins.email.models import Email

    brut = (request.GET.get("message") or "").strip()
    if not brut.isdigit():
        return None

    e = Email.objects.select_related("account").filter(pk=int(brut)).first()
    if e is None:
        return [P.Note("Ce message n'existe plus.", tone="warn")]

    champs = [
        P.Field("De", e.from_address or "—"),
        P.Field("À", e.to_addresses or "—"),
    ]
    if e.cc_addresses:
        champs.append(P.Field("Copie", e.cc_addresses))
    champs += [
        P.Field("Sujet", e.subject or "(sans sujet)"),
        P.Field("Date", _date(e.email_date)),
        P.Field("Compte", e.account.name if e.account_id else "—", kind="badge"),
        P.Field("Priorité", e.priority or "—", kind="badge",
                tone=_ton_priorite(e.priority)),
        P.Field("Lu", "oui" if e.is_read else "non"),
        P.Field("Pièces jointes", "oui" if e.has_attachments else "non"),
        P.Field("Fermer la fiche", "retour à la liste", kind="link",
                href=_lien_avec(request, message=None)),
    ]

    blocs = [P.Fields(title="Message", items=champs)]

    # Seul le texte est affiché, jamais ``body_html`` : un corps d'e-mail est
    # du contenu hostile par défaut, et le rendu par cellules typées est ce
    # qui garantit qu'il ne peut pas devenir du balisage.
    corps = (e.body_text or "").strip()
    if corps:
        blocs.append(P.Prose(title="Corps", text=corps[:MAX_CORPS]))
    elif e.body_html:
        blocs.append(P.Note(
            "Ce message n'a qu'une version HTML ; elle n'est pas affichée ici.",
            tone="info",
        ))
    return blocs


# ── Contacts ────────────────────────────────────────────────────────────

def contacts(request):
    from modules.plugins.email.models import Contact

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    compte = _filtre_compte(fs, request)
    recherche = fs.add(tables.search_filter(
        request, "q", "Recherche", placeholder="adresse ou nom",
    ))

    qs = Contact.objects.prefetch_related("accounts")
    if compte is not None and compte.value:
        # M2M : un contact peut appartenir à plusieurs boîtes.
        qs = qs.filter(accounts__id=compte.value).distinct()
    if recherche.value:
        from django.db.models import Q
        qs = qs.filter(
            Q(email_address__icontains=recherche.value)
            | Q(display_name__icontains=recherche.value)
        )
    qs = qs.order_by("-last_seen")

    page = tables.paginate(request, qs, per_page=fs.per_page)

    return P.Table(
        caption="Contacts",
        filters=fs,
        columns=[
            P.Column("Adresse"),
            P.Column("Nom"),
            P.Column("Reçus", align="num"),
            P.Column("Envoyés", align="num"),
            P.Column("Comptes"),
            P.Column("Dernier contact", align="fit"),
        ],
        rows=[
            P.Row(cells=(
                P.mono(c.email_address),
                P.text(c.display_name or "—"),
                P.num(c.emails_received),
                P.num(c.emails_sent),
                P.text(", ".join(a.name for a in c.accounts.all()) or "—"),
                P.mono(_date(c.last_seen), title=str(c.last_seen or "")),
            ))
            for c in page.rows
        ],
        page=page,
        empty="Aucun contact ne correspond à ces filtres.",
    )


# ── Actions ─────────────────────────────────────────────────────────────

def marquer_tout_lu(request):
    from modules.plugins.email.models import Email

    n = Email.objects.filter(direction="inbound", is_read=False).update(is_read=True)
    if not n:
        return P.Note("Aucun message non lu.", tone="info")
    return P.Note(f"{n} message(s) marqué(s) comme lu(s).", tone="ok")


# ── Déclaration ─────────────────────────────────────────────────────────

def _date(valeur) -> str:
    from GestionSysteme.formatting import dt
    return dt(valeur)


def _lien_avec(request, **params) -> str:
    return tables.url_with(request, **params)


def get_panels() -> list:
    return [
        P.ModulePanel(
            key="reception", label="Boîte de réception", icon="✉", order=10,
            handler=inbox,
            description="Messages récupérés par le relevé IMAP.",
            actions=(
                P.PanelAction(
                    key="tout_lu", label="Tout marquer comme lu",
                    handler=marquer_tout_lu,
                    confirm="Marquer tous les messages reçus comme lus ?",
                ),
            ),
        ),
        P.ModulePanel(
            key="contacts", label="Contacts", icon="☻", order=20,
            handler=contacts,
            description="Adresses vues dans les échanges, avec leur volume.",
        ),
    ]
