from __future__ import annotations

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET"])
def drives(request):
    from drives.engine import drive_engine
    from drives.state import DEFAULT_PARAMS

    drive_engine.update()
    rows = []
    for kind, state in drive_engine.states.items():
        params = DEFAULT_PARAMS[kind]
        rows.append({
            "kind": kind.value,
            "tension": round(state.tension, 3),
            "last_update": state.last_update,
            "last_satisfied": state.last_satisfied,
            "params": {
                "growth_rate": params.growth_rate,
                "decay_on_satisfy": params.decay_on_satisfy,
                "weight": params.weight,
                "satisfy_threshold": params.satisfy_threshold,
            },
        })
    dominant = drive_engine.get_dominant()
    bonus, label = drive_engine.conscience_contribution()
    return JsonResponse({
        "drives": rows,
        "dominant": dominant.kind.value if dominant else None,
        "energy": round(drive_engine.energy_level(), 3),
        "conscience_contribution": round(bonus, 3),
        "conscience_label": label,
    })
