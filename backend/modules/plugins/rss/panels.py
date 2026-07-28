"""Panneaux du module RSS pour GestionSystème.

Le module n'en déclarait aucun : son espace se réduisait à « État » et à une
configuration d'un seul champ. Les articles relevés n'étaient visibles nulle
part — ils n'existaient que comme empreintes de déduplication, alors que
c'est tout l'intérêt d'un module de veille.

Deux panneaux, parce qu'il y a deux questions distinctes :

- **Articles** — « qu'est-ce qui est arrivé ». Filtré par flux, catégorie,
  état de lecture ; la fiche s'ouvre dans l'URL (``?article=<id>``), donc elle
  se partage et le retour arrière la referme en gardant les filtres.
- **Flux** — « est-ce que ça marche ». Un flux mort ressemblait exactement à
  un flux calme : ici l'erreur, sa date et le nombre d'échecs consécutifs sont
  des colonnes.

Le résumé d'un article est du HTML fourni par un tiers. Il est réduit en
texte au moment du relevé (``parser.clean_text``) et rendu par cellules
typées : il ne peut redevenir du balisage à aucune étape.
"""
from __future__ import annotations

from GestionSysteme import panels as P
from GestionSysteme import tables

RESUME_MAX = 8_000


# ── Filtres partagés ────────────────────────────────────────────────────

def _feeds() -> list:
    from modules.plugins.rss.models import RSSFeed
    return list(RSSFeed.objects.all())


def _filtre_flux(fs, request, feeds):
    """Sélecteur de flux. Masqué sous deux flux : proposer de filtrer sur
    l'unique valeur possible est du bruit."""
    if len(feeds) < 2:
        return None
    return fs.add(tables.select_filter(
        request, "flux", "Flux",
        [(str(f.pk), f.name) for f in feeds],
        all_label="Tous les flux",
    ))


def _filtre_categorie(fs, request, feeds):
    cats = sorted({f.category for f in feeds if f.category})
    if len(cats) < 2:
        return None
    return fs.add(tables.select_filter(
        request, "categorie", "Catégorie",
        [(c, c) for c in cats], all_label="Toutes",
    ))


# ── Articles ────────────────────────────────────────────────────────────

def articles(request):
    from django.db.models import Q
    from modules.plugins.rss.models import RSSEntry

    feeds = _feeds()
    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    flux = _filtre_flux(fs, request, feeds)
    categorie = _filtre_categorie(fs, request, feeds)
    etat = fs.add(tables.select_filter(
        request, "etat", "État",
        [("non_lus", "non lus"), ("lus", "lus"), ("signales", "signalés")],
    ))
    recherche = fs.add(tables.search_filter(
        request, "q", "Recherche", placeholder="titre, résumé, auteur",
    ))

    qs = RSSEntry.objects.select_related("feed")
    if flux is not None and flux.value:
        qs = qs.filter(feed_id=flux.value)
    if categorie is not None and categorie.value:
        qs = qs.filter(feed__category=categorie.value)
    if etat.value == "non_lus":
        qs = qs.filter(is_read=False)
    elif etat.value == "lus":
        qs = qs.filter(is_read=True)
    elif etat.value == "signales":
        qs = qs.filter(is_notable=True)
    if recherche.value:
        qs = qs.filter(
            Q(title__icontains=recherche.value)
            | Q(summary__icontains=recherche.value)
            | Q(author__icontains=recherche.value)
        )

    page = tables.paginate(request, qs, per_page=fs.per_page)

    blocs = []
    if not feeds:
        blocs.append(P.Note(
            "Aucun flux n'est suivi. Ajoute-en dans l'onglet Configuration : "
            "colle l'adresse d'un flux RSS ou Atom, le nom se remplit tout seul.",
            tone="warn", title="Rien à relever",
        ))

    fiche = _fiche_article(request)
    if fiche is not None:
        blocs.extend(fiche)

    blocs.append(P.Table(
        caption="Articles relevés",
        filters=fs,
        columns=[
            P.Column("Date", align="fit", hint="Date du flux, à défaut celle du relevé"),
            P.Column("Flux", align="fit"),
            P.Column("Titre"),
            P.Column("Auteur"),
            P.Column("", align="fit", hint="Signalé par un mot-clé d'alerte"),
            P.Column("Lu", align="fit"),
        ],
        rows=[_ligne_article(request, e) for e in page.rows],
        page=page,
        empty=(
            "Aucun article ne correspond à ces filtres."
            if feeds else
            "Aucun article : commence par déclarer un flux."
        ),
    ))
    return P.Blocks(items=blocs)


def _ligne_article(request, e) -> P.Row:
    return P.Row(
        # Le lien conserve les filtres : ouvrir une fiche puis la fermer doit
        # ramener exactement la liste qu'on regardait.
        href=tables.url_with(request, article=e.pk),
        cells=(
            P.mono(_date(e.dated), title=str(e.published or e.dated or "")),
            P.badge(e.feed.name),
            P.text(e.title, clamp=True),
            P.muted(e.author or "—"),
            P.badge("★", tone="warn") if e.is_notable else P.text(""),
            P.boolean(e.is_read, yes="lu", no="non lu"),
        ),
    )


def _fiche_article(request):
    """Fiche d'un article, quand ``?article=<id>`` est présent."""
    from modules.plugins.rss.models import RSSEntry

    brut = (request.GET.get("article") or "").strip()
    if not brut.isdigit():
        return None

    e = RSSEntry.objects.select_related("feed").filter(pk=int(brut)).first()
    if e is None:
        return [P.Note("Cet article n'est plus en base (élagué ou flux supprimé).",
                       tone="warn")]

    champs = [
        P.Field("Titre", e.title),
        P.Field("Flux", e.feed.name, kind="badge"),
    ]
    if e.feed.category:
        champs.append(P.Field("Catégorie", e.feed.category, kind="badge"))
    champs += [
        P.Field("Date", _date(e.dated)),
        P.Field("Auteur", e.author or "—"),
    ]
    if e.link:
        # Le seul lien sortant de la page : c'est l'article lui-même, et le
        # module n'aspire volontairement pas le contenu des pages visées.
        champs.append(P.Field("Lien", e.link, kind="link", href=e.link))
    champs += [
        P.Field("Lu", "oui" if e.is_read else "non"),
        P.Field("Signalé", "oui" if e.is_notable else "non"),
        P.Field("Fermer la fiche", "retour à la liste", kind="link",
                href=tables.url_with(request, article=None)),
    ]

    blocs = [P.Fields(title="Article", items=champs)]
    resume = (e.summary or "").strip()
    if resume:
        blocs.append(P.Prose(title="Résumé", text=resume[:RESUME_MAX]))
    else:
        blocs.append(P.Note(
            "Ce flux ne publie pas de résumé — seul le titre et le lien sont disponibles.",
            tone="info",
        ))
    return blocs


# ── Flux ────────────────────────────────────────────────────────────────

def flux(request):
    from django.db.models import Count, Q
    from modules.plugins.rss.models import RSSFeed

    feeds = _feeds()
    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    categorie = _filtre_categorie(fs, request, feeds)
    etat = fs.add(tables.select_filter(
        request, "etat", "État",
        [("actifs", "actifs"), ("suspendus", "suspendus"), ("erreur", "en erreur")],
    ))

    # ``annotate`` regroupe, ce qui perd l'ordre déclaré au modèle — et une
    # pagination sur un queryset non ordonné rend des pages incohérentes.
    qs = RSSFeed.objects.annotate(
        nb=Count("entries"),
        nb_non_lus=Count("entries", filter=Q(entries__is_read=False)),
    ).order_by("category", "name", "id")
    if categorie is not None and categorie.value:
        qs = qs.filter(category=categorie.value)
    if etat.value == "actifs":
        qs = qs.filter(is_active=True)
    elif etat.value == "suspendus":
        qs = qs.filter(is_active=False)
    elif etat.value == "erreur":
        qs = qs.filter(error_count__gt=0)

    page = tables.paginate(request, qs, per_page=fs.per_page)

    blocs = [_synthese(feeds)]
    blocs.append(P.Table(
        caption="Flux suivis",
        filters=fs,
        columns=[
            P.Column("Flux"),
            P.Column("Catégorie", align="fit"),
            P.Column("Articles", align="num"),
            P.Column("Non lus", align="num"),
            P.Column("Dernier relevé", align="fit"),
            P.Column("État"),
        ],
        rows=[_ligne_flux(f) for f in page.rows],
        page=page,
        empty="Aucun flux. Ajoute-en dans l'onglet Configuration.",
    ))
    blocs.append(P.Note(
        "Les flux s'ajoutent, se renomment et se suspendent dans l'onglet "
        "Configuration de cet espace — la liste ci-dessus lit la même table.",
        tone="info",
    ))
    return P.Blocks(items=blocs)


def _ligne_flux(f) -> P.Row:
    if not f.is_active:
        etat = P.badge("suspendu")
    elif f.error_count:
        etat = P.badge(f"{f.error_count} échec(s) · {f.last_error[:60]}", tone="danger")
    elif f.last_success_at:
        etat = P.badge("ok", tone="ok")
    else:
        etat = P.badge("jamais relevé", tone="warn")

    return P.Row(
        # Cliquer un flux ouvre ses articles : c'est la question suivante.
        href=f"{_url_articles()}?flux={f.pk}",
        cells=(
            P.link(f.name, f.url, title=f.url),
            P.badge(f.category or "—"),
            P.num(f.nb),
            P.num(f.nb_non_lus),
            P.mono(_date(f.last_polled), title=str(f.last_polled or "")),
            etat,
        ),
    )


def _synthese(feeds) -> P.Stats:
    from modules.plugins.rss.models import RSSEntry

    actifs = sum(1 for f in feeds if f.is_active)
    casses = sum(1 for f in feeds if f.is_active and f.error_count)
    non_lus = RSSEntry.objects.filter(is_read=False).count()
    total = RSSEntry.objects.count()

    return P.Stats(items=[
        P.Stat(label="Flux actifs", value=str(actifs),
               sub=f"sur {len(feeds)} déclaré(s)"),
        P.Stat(label="En erreur", value=str(casses),
               sub="au dernier relevé" if casses else "aucun",
               tone="danger" if casses else "ok"),
        P.Stat(label="Articles non lus", value=str(non_lus)),
        P.Stat(label="Articles en base", value=str(total),
               sub="élagués au-delà du plafond par flux"),
    ])


# ── Actions ─────────────────────────────────────────────────────────────

def relever(request) -> P.Note:
    """Relève tous les flux actifs immédiatement.

    Passe par l'instance enregistrée plutôt que par une copie neuve : c'est
    elle qui porte les compteurs lus par la page d'état. Et le relevé
    fonctionne module arrêté — on ouvre justement cette page quand quelque
    chose ne tourne pas.
    """
    from asgiref.sync import async_to_sync
    from modules.manager import module_manager

    module = module_manager.get_registered("rss")
    if module is None:
        return P.Note("Module RSS introuvable.", tone="danger")

    report = async_to_sync(module.poll)()
    if not report.feeds:
        return P.Note("Aucun flux actif à relever.", tone="warn")

    morceaux = [f"{report.feeds} flux relevé(s)"]
    morceaux.append(
        f"{report.new_entries} nouvel(les) entrée(s)" if report.new_entries
        else "rien de nouveau"
    )
    if report.unchanged:
        morceaux.append(f"{report.unchanged} inchangé(s)")
    if report.failed:
        detail = ", ".join(report.errors[:3])
        return P.Note(
            f"{' · '.join(morceaux)} — {report.failed} en erreur ({detail}).",
            tone="warn",
        )
    return P.Note(" · ".join(morceaux) + ".", tone="ok")


def tout_lu(request) -> P.Note:
    from modules.plugins.rss.models import RSSEntry

    n = RSSEntry.objects.filter(is_read=False).update(is_read=True)
    _oublier_titres()
    if not n:
        return P.Note("Aucun article non lu.", tone="info")
    return P.Note(f"{n} article(s) marqué(s) comme lu(s).", tone="ok")


def _oublier_titres() -> None:
    """Vide l'instantané d'invite après un marquage en masse.

    Il est tenu en RAM par le module (voir ``module.get_context``) : sans ça,
    Mika continuerait à annoncer des nouveautés qu'on vient de solder.
    """
    from modules.manager import module_manager

    module = module_manager.get_registered("rss")
    if module is not None:
        module._headlines = []
        module._unread_total = 0


# ── Déclaration ─────────────────────────────────────────────────────────

def _date(valeur) -> str:
    from GestionSysteme.formatting import dt
    return dt(valeur)


def _url_articles() -> str:
    from django.urls import reverse
    return reverse("gestionsysteme:module-panel", args=["rss", "articles"])


_RELEVER = P.PanelAction(
    key="relever", label="Relever maintenant", handler=relever,
)


def get_panels() -> list:
    return [
        P.ModulePanel(
            key="articles", label="Articles", icon="⌁", order=10,
            handler=articles,
            description="Ce que les flux ont publié depuis le dernier relevé.",
            actions=(
                _RELEVER,
                P.PanelAction(
                    key="tout_lu", label="Tout marquer comme lu",
                    handler=tout_lu,
                    confirm="Marquer tous les articles comme lus ?",
                ),
            ),
        ),
        P.ModulePanel(
            key="flux", label="Flux", icon="≋", order=20,
            handler=flux,
            description="État de chaque flux : dernier relevé, volume, erreurs.",
            actions=(_RELEVER,),
        ),
    ]
