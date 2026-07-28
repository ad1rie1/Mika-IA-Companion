"""Vie intérieure — émotions, pulsions, ruminations, rythme.

Cinq onglets sur une seule destination. Dans l'ancien menu c'étaient quatre
entrées de premier niveau au même poids visuel que « Souvenirs » ou
« Messages », alors qu'elles répondent toutes à la même question : *comment
va-t-elle en ce moment, hors conversation ?*
"""
from __future__ import annotations

import logging

from django.shortcuts import render

from GestionSysteme import formatting as fmt, tables
from GestionSysteme.nav import item_for
from GestionSysteme.shell import page_context

logger = logging.getLogger(__name__)

_DRIVE_FR = {
    "curiosity": "Curiosité", "social": "Social",
    "expression": "Expression", "rest": "Repos",
}
_PHASE_FR = {
    "morning": "matin", "afternoon": "après-midi",
    "evening": "soirée", "night": "nuit",
}
_SLEEP_FR = {
    "awake": "éveillée", "light_sleep": "sommeil léger",
    "rem": "sommeil paradoxal", "deep_sleep": "sommeil profond",
}


def inner(request, tab: str | None = None):
    item = item_for("inner")
    current = item.tab(tab)
    ctx = page_context(
        request, item=item, active_key="inner", active_tab=current.key,
    )

    builder = {
        "emotions": _emotions,
        "drives": _drives,
        "ruminations": _ruminations,
        "rythme": _rhythm,
        "historique": _history,
    }[current.key]
    ctx.update(builder(request))

    return render(request, f"gestion/inner/{current.key}.html", ctx)


# ── Émotions ────────────────────────────────────────────────────────────

def _emotions(request) -> dict:
    from config.personality import personality
    from emotion import pad
    from emotion.engine import emotion_engine

    position = emotion_engine.global_mood.dynamic.position
    label, intensity = pad.pad_to_label(position)

    # Les humeurs par personne vivent en RAM, pas en base : elles se
    # paginent comme une liste ordinaire.
    people = []
    for person_id, mood in emotion_engine.person_moods.items():
        p_label, p_intensity = pad.pad_to_label(mood.dynamic.position)
        people.append({
            "person_id": person_id,
            "emotion": p_label.value,
            "intensity": p_intensity,
            "velocity": pad.norm(mood.dynamic.velocity),
            "pad": [round(x, 3) for x in mood.dynamic.position],
            "last_interaction": getattr(mood, "last_interaction", None),
            "history_size": len(getattr(mood, "history", ()) or ()),
        })
    people.sort(key=lambda r: r["intensity"], reverse=True)

    try:
        analytics = emotion_engine.get_analytics()
    except Exception:
        logger.debug("analyses émotionnelles indisponibles", exc_info=True)
        analytics = {}

    return {
        "global_mood": {
            "label": label.value,
            "intensity": intensity,
            "blend": [
                {"emotion": e.value, "weight": w}
                for e, w in pad.pad_to_blend(position, top_k=3)
            ],
            "pad": [round(x, 3) for x in position],
            "velocity": pad.norm(emotion_engine.global_mood.dynamic.velocity),
        },
        "temperament": {
            "default_mood": personality.temperament.default_mood.value,
            "volatility": personality.temperament.volatility,
            "intensity_base": personality.temperament.intensity_base,
            "recovery_speed": personality.temperament.recovery_speed,
            "global_bleed": personality.temperament.global_bleed,
        },
        "people_page": tables.paginate(request, people, default_per_page=25),
        "analytics": analytics,
    }


# ── Pulsions ────────────────────────────────────────────────────────────

def _drives(request) -> dict:
    import time

    from drives.engine import drive_engine
    from drives.state import DEFAULT_PARAMS

    drive_engine.update()
    # `last_satisfied` est un horodatage epoch (``time.time()``), pas un
    # datetime : l'état des pulsions vit en mémoire vive, sans ORM derrière.
    # On convertit ici plutôt que de rendre le filtre d'ancienneté
    # polymorphe — un flottant pourrait être n'importe quoi.
    now = time.time()
    dominant = drive_engine.get_dominant()
    dominant_kind = dominant.kind if dominant else None

    rows = []
    for kind, state in drive_engine.states.items():
        params = DEFAULT_PARAMS[kind]
        rows.append({
            "kind": kind.value,
            "label": _DRIVE_FR.get(kind.value, kind.value),
            "tension": state.tension,
            "tone": fmt.tone_for_ratio(state.tension, invert=True),
            "dominant": kind == dominant_kind,
            "growth_rate": params.growth_rate,
            "decay_on_satisfy": params.decay_on_satisfy,
            "weight": params.weight,
            "satisfy_threshold": params.satisfy_threshold,
            "satisfied_ago": max(0.0, now - state.last_satisfied),
        })

    try:
        bonus, label = drive_engine.conscience_contribution()
    except Exception:
        bonus, label = 0.0, ""

    return {
        "drives": rows,
        "energy": drive_engine.energy_level(),
        "contribution": bonus,
        "contribution_label": label,
    }


# ── Ruminations ─────────────────────────────────────────────────────────

def _ruminations(request) -> dict:
    from conscience.models import Rumination

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    status = fs.add(tables.select_filter(
        request, "statut", "État",
        (("active", "active"), ("resolved", "résolue"), ("faded", "estompée")),
    ))

    qs = Rumination.objects.order_by("-intensity", "-created_at")
    if status.value:
        qs = qs.filter(status=status.value)

    return {
        "filterset": fs,
        "page": tables.paginate(request, qs, per_page=fs.per_page),
        "status_tones": {"active": "warn", "resolved": "ok", "faded": ""},
    }


# ── Rythme ──────────────────────────────────────────────────────────────

def _rhythm(request) -> dict:
    from config.personality import personality
    from drives.engine import drive_engine
    from emotion import circadian
    from memory.sleep import sleep_cycle

    state = circadian.current_state(profile=personality.circadian_profile)
    energy = drive_engine.energy_level()
    profile = personality.circadian_profile

    return {
        "phase": state.phase.value,
        "phase_fr": _PHASE_FR.get(state.phase.value, state.phase.value),
        "hour": state.hour,
        "circadian_energy": state.energy,
        "energy": energy,
        "energy_tone": fmt.tone_for_ratio(energy),
        "fatigued": energy < 0.5,
        "sleep_phase": sleep_cycle.phase,
        "sleep_phase_fr": _SLEEP_FR.get(sleep_cycle.phase, sleep_cycle.phase),
        "asleep": sleep_cycle.phase != "awake",
        "profile": profile,
        # Émotion vers laquelle la phase courante tire l'humeur de repos.
        # ``phase_bias()`` renvoie le vecteur PAD ; c'est ``bias_anchor`` qui
        # porte l'émotion nommée, donc affichable.
        "bias_anchor": state.bias_anchor.value,
        "phase_anchors": [
            (_PHASE_FR.get(phase.value, phase.value), emotion.value)
            for phase, emotion in profile.phase_anchors.items()
        ],
    }


# ── Historique affectif ─────────────────────────────────────────────────

def _history(request) -> dict:
    from memory.models import EmotionalSummary, EmotionSnapshot

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    person = fs.add(tables.search_filter(
        request, "personne", "Personne", placeholder="identifiant de personne",
    ))

    snapshots = EmotionSnapshot.objects.order_by("-created_at")
    if person.value:
        snapshots = snapshots.filter(person_id__icontains=person.value)

    summaries = EmotionalSummary.objects.order_by("-period_start")
    if person.value:
        summaries = summaries.filter(person_id__icontains=person.value)

    return {
        "filterset": fs,
        # Deux paginations indépendantes sur le même écran : chacune a son
        # propre paramètre d'URL, donc naviguer dans l'une ne déplace pas
        # l'autre.
        "snapshots_page": tables.paginate(
            request, snapshots, per_page=fs.per_page, page_param="p_instantanes",
        ),
        "summaries_page": tables.paginate(
            request, summaries, per_page=25, page_param="p_resumes",
        ),
    }
