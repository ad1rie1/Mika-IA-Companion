"""Mémoire — souvenirs, connaissances, thèmes, entités, messages, nuits, récit.

Sept onglets pour une seule destination : ce sont sept vues d'une même chose,
et l'ancien menu en faisait sept entrées de premier niveau.
"""
from __future__ import annotations

from django.db.models import Count

from django.shortcuts import render

from GestionSysteme import tables
from GestionSysteme.nav import item_for
from GestionSysteme.shell import page_context


def memory(request, tab: str | None = None):
    item = item_for("memory")
    current = item.tab(tab)
    ctx = page_context(
        request, item=item, active_key="memory", active_tab=current.key,
    )
    ctx.update({
        "souvenirs": _souvenirs,
        "connaissances": _connaissances,
        "themes": _themes,
        "entites": _entities,
        "messages": _messages,
        "journaux": _nights,
        "recit": _narrative,
    }[current.key](request))
    return render(request, f"gestion/memory/{current.key}.html", ctx)


# ── Souvenirs ───────────────────────────────────────────────────────────

_SOUVENIR_ORDERS = {
    "-occurred_at": "Plus récents",
    "-importance": "Plus importants",
    "-created_at": "Derniers extraits",
    "importance": "Moins importants",
}


def _souvenirs(request) -> dict:
    from memory.models import Souvenir, Theme

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    search = fs.add(tables.search_filter(
        request, "q", "Recherche", placeholder="dans le contenu",
    ))
    theme = fs.add(tables.select_filter(
        request, "theme", "Thème",
        [(t, t) for t in Theme.objects.order_by("name").values_list("name", flat=True)[:200]],
    ))
    order = fs.add(tables.select_filter(
        request, "tri", "Tri", list(_SOUVENIR_ORDERS.items()),
        default="-occurred_at", all_label="Plus récents",
    ))

    qs = Souvenir.objects.prefetch_related("themes", "entities")
    if search.value:
        qs = qs.filter(content__icontains=search.value)
    if theme.value:
        qs = qs.filter(themes__name=theme.value)
    qs = qs.distinct().order_by(order.value or "-occurred_at")

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}


# ── Connaissances ───────────────────────────────────────────────────────

def _connaissances(request) -> dict:
    from memory.models import Connaissance, Theme

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    search = fs.add(tables.search_filter(request, "q", "Recherche", placeholder="dans le contenu"))
    theme = fs.add(tables.select_filter(
        request, "theme", "Thème",
        [(t, t) for t in Theme.objects.order_by("name").values_list("name", flat=True)[:200]],
    ))
    validity = fs.add(tables.select_filter(
        request, "validite", "Validité",
        [("valides", "valides seulement"), ("invalides", "invalidées seulement")],
        all_label="Toutes",
    ))

    qs = Connaissance.objects.prefetch_related("themes", "entities")
    if search.value:
        qs = qs.filter(content__icontains=search.value)
    if theme.value:
        qs = qs.filter(themes__name=theme.value)
    if validity.value == "valides":
        qs = qs.filter(is_valid=True)
    elif validity.value == "invalides":
        qs = qs.filter(is_valid=False)
    qs = qs.distinct().order_by("-confidence", "-updated_at")

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}


# ── Thèmes ──────────────────────────────────────────────────────────────

def _themes(request) -> dict:
    from memory.models import Theme

    fs = tables.FilterSet(per_page=tables.read_per_page(request, default=50))
    search = fs.add(tables.search_filter(request, "q", "Recherche", placeholder="nom du thème"))

    qs = Theme.objects.annotate(
        n_souvenirs=Count("souvenirs", distinct=True),
        n_connaissances=Count("connaissances", distinct=True),
    )
    if search.value:
        qs = qs.filter(name__icontains=search.value)
    qs = qs.order_by("-n_souvenirs", "name")

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}


# ── Entités ─────────────────────────────────────────────────────────────

def _entities(request) -> dict:
    from memory.models import Entity

    types = list(
        Entity.objects.order_by("entity_type")
        .values_list("entity_type", flat=True).distinct()
    )

    fs = tables.FilterSet(per_page=tables.read_per_page(request, default=50))
    search = fs.add(tables.search_filter(request, "q", "Recherche", placeholder="nom"))
    kind = fs.add(tables.select_filter(
        request, "type", "Type", [(t, t) for t in types if t],
    ))

    qs = Entity.objects.annotate(
        n_souvenirs=Count("souvenirs", distinct=True),
        n_connaissances=Count("connaissances", distinct=True),
    )
    if search.value:
        qs = qs.filter(name__icontains=search.value)
    if kind.value:
        qs = qs.filter(entity_type=kind.value)
    qs = qs.order_by("-n_souvenirs", "name")

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}


# ── Messages ────────────────────────────────────────────────────────────

def _messages(request) -> dict:
    from memory.models import Message

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    search = fs.add(tables.search_filter(request, "q", "Recherche", placeholder="dans le contenu"))
    role = fs.add(tables.select_filter(
        request, "role", "Rôle", [("user", "utilisateur"), ("assistant", "Mika")],
    ))
    person = fs.add(tables.search_filter(request, "personne", "Personne", placeholder="person_id"))
    scaffolding = fs.add(tables.select_filter(
        request, "interne", "Échafaudage",
        [("oui", "interne seulement"), ("non", "conversation seulement")],
        all_label="Tout",
    ))

    qs = Message.objects.order_by("-created_at")
    if search.value:
        qs = qs.filter(content__icontains=search.value)
    if role.value:
        qs = qs.filter(role=role.value)
    if person.value:
        qs = qs.filter(person_id__icontains=person.value)
    if scaffolding.value == "oui":
        qs = qs.filter(is_internal=True)
    elif scaffolding.value == "non":
        qs = qs.filter(is_internal=False)

    return {"filterset": fs, "page": tables.paginate(request, qs, per_page=fs.per_page)}


# ── Journaux & rêves ────────────────────────────────────────────────────

def _nights(request) -> dict:
    """Les deux productions nocturnes, côte à côte.

    Un journal est daté du jour qu'il **couvre**, pas du moment où il est
    écrit : le sommeil léger le rédige tard le soir même. C'est pourquoi le
    plus récent peut porter la date du jour.
    """
    from memory.models import DailyJournal, Dream

    return {
        "journals_page": tables.paginate(
            request, DailyJournal.objects.order_by("-date"),
            per_page=15, page_param="p_journaux",
        ),
        "dreams_page": tables.paginate(
            request, Dream.objects.order_by("-night_of", "-created_at"),
            per_page=15, page_param="p_reves",
        ),
    }


# ── Récit de soi ────────────────────────────────────────────────────────

def _narrative(request) -> dict:
    from memory.models import SelfNarrative

    qs = SelfNarrative.objects.order_by("-created_at")
    page = tables.paginate(request, qs, per_page=10)
    return {"page": page, "current": page.rows[0] if page.rows else None}
