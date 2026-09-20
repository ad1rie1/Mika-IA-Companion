"""Suggestions de saisie : sources fermées, recherche et réponse bornées.

Le plafond porte sur les suggestions d'une recherche, jamais sur les valeurs
acceptées par un filtre. On peut donc retrouver une valeur au-delà des vingt
premières sans charger un inventaire complet dans chaque page.
"""
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from GestionSysteme.tables import read_text
from GestionSysteme.formatting import person_reference

LIMIT = 20


def _themes(query):
    from memory.models import Theme
    return [{"value": name, "label": name} for name in
            Theme.objects.filter(name__icontains=query).order_by("name")
            .values_list("name", flat=True)[:LIMIT + 1]]


def _persons(query):
    from memory.models import Entity
    qs = Entity.objects.filter(entity_type="person")
    if query.startswith("#") and query[1:].isascii() and query[1:].isdecimal():
        pk = int(query[1:])
        qs = qs.filter(pk=pk) if 0 < pk < 2**63 else qs.none()
    else:
        qs = qs.filter(name__icontains=query)
    return [{"value": person_reference(entity), "label": person_reference(entity)}
            for entity in qs.order_by("name", "pk")[:LIMIT + 1]]


def _handles(query):
    from identity.models import IdentityHandle
    from memory.models import EmotionalSummary, EmotionSnapshot
    from GestionSysteme.views.inner import GLOBAL_PERSON_ID

    # L'historique peut survivre à la suppression d'un handle d'identité.
    # L'union conserve ces références ; la recherche par nom aide à découvrir
    # les handles sans connaître leur identifiant de transport.
    named = IdentityHandle.objects.filter(
        Q(identity__display_name__icontains=query) |
        Q(identity__entity__name__icontains=query)
    ).order_by().values("person_id")
    condition = Q(person_id__icontains=query) | Q(person_id__in=named)
    snapshots = EmotionSnapshot.objects.exclude(person_id=GLOBAL_PERSON_ID).filter(condition).order_by().values_list("person_id", flat=True)
    summaries = EmotionalSummary.objects.exclude(person_id=GLOBAL_PERSON_ID).filter(condition).order_by().values_list("person_id", flat=True)
    values = list(snapshots.union(summaries).order_by("person_id")[:LIMIT + 1])
    labels = {}
    for handle in IdentityHandle.objects.filter(person_id__in=values).select_related("identity__entity").order_by("pk"):
        identity = handle.identity
        name = identity.entity.name if identity.entity_id else identity.display_name
        labels.setdefault(handle.person_id, f"{name} · {handle.person_id}" if name else handle.person_id)
    return [{"value": value, "label": labels.get(value, value)} for value in values]


def _forge_modules(query):
    from modules.plugins.forge.models import ForgeLog
    return [{"value": name, "label": name} for name in
            ForgeLog.objects.filter(module_name__icontains=query).exclude(module_name="")
            .order_by("module_name").values_list("module_name", flat=True).distinct()[:LIMIT + 1]]


SOURCES = {"themes": _themes, "personnes": _persons, "handles": _handles, "forge-modules": _forge_modules}


@require_GET
@never_cache
def suggestions(request, kind):
    source = SOURCES.get(kind)
    if source is None:
        raise Http404("Source de suggestions inconnue")
    results = source(read_text(request, "q", max_length=220))
    return JsonResponse({"results": results[:LIMIT], "more": len(results) > LIMIT})
