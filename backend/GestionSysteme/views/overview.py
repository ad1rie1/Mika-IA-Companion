"""Vue d'ensemble — l'état de Mika en un écran.

L'ancienne page du même nom tenait en 88 lignes de JavaScript et n'agrégeait
presque rien : c'était une grille de compteurs. Ici on répond à trois
questions dans cet ordre, parce que c'est l'ordre dans lequel on les pose :

1. **Est-ce que quelque chose m'attend ?** (approbations, revendications
   d'identité, modules arrêtés, pannes silencieuses) — en haut, et absent
   quand il n'y a rien.
2. **Comment va-t-elle ?** humeur, énergie, drives, sommeil.
3. **De quoi est faite sa mémoire ?** volumes, en dernier, parce qu'un total
   de souvenirs ne se lit pas deux fois par jour.
"""
from __future__ import annotations

import logging

from django.shortcuts import render
from django.urls import reverse

from GestionSysteme import formatting as fmt
from GestionSysteme.nav import item_for
from GestionSysteme.shell import page_context

logger = logging.getLogger(__name__)


def overview(request):
    ctx = page_context(request, item=item_for("overview"), active_key="overview")
    ctx.update({
        "attention": _attention(),
        "mood": _mood(),
        "drives": _drives(),
        "rhythm": _rhythm(),
        "sleep": _sleep(),
        "narrative": _narrative(),
        "volumes": _volumes(),
        "loops": _loops(),
    })
    return render(request, "gestion/overview.html", ctx)


def _safe(fn, default=None):
    """Isole chaque bloc : la page reste affichable si l'un échoue.

    C'est l'écran qu'on ouvre pour constater qu'une chose est cassée — il ne
    peut pas tomber avec elle.
    """
    try:
        return fn()
    except Exception:
        logger.debug("bloc de la vue d'ensemble indisponible", exc_info=True)
        return default


# ── Ce qui attend une décision ──────────────────────────────────────────

def _attention() -> list[dict]:
    """Uniquement ce qui **attend un humain** ou signale une panne."""
    items: list[dict] = []

    def add(count, label, href, tone="warn"):
        if count:
            items.append({"count": count, "label": label, "href": href, "tone": tone})

    def _pending_actions():
        from projects.models import ProjectPendingAction
        return ProjectPendingAction.objects.filter(status="pending").count()

    def _claims():
        from identity.models import IdentityClaim
        return IdentityClaim.objects.filter(status="pending").count()

    def _observations():
        from conscience.models import Observation
        return Observation.objects.filter(status="pending").count()

    def _modules_down():
        from modules.manager import module_manager
        return sum(
            1 for i in module_manager.list_all()
            if i.get("enabled") and not i.get("running") and not i.get("system")
        )

    def _degradations():
        from utils.degradation import degradations
        return len(degradations.snapshot())

    add(_safe(_pending_actions, 0), "action(s) de projet en attente de ton accord",
        reverse("gestionsysteme:projects-tab", args=["attente"]), tone="warn")
    add(_safe(_claims, 0), "revendication(s) d'identité non tranchée(s)",
        reverse("gestionsysteme:social-tab", args=["demandes"]), tone="warn")
    add(_safe(_observations, 0), "observation(s) en attente de traitement",
        reverse("gestionsysteme:conscience-tab", args=["observations"]), tone="info")
    add(_safe(_modules_down, 0), "module(s) activé(s) mais arrêté(s)",
        reverse("gestionsysteme:modules"), tone="danger")
    add(_safe(_degradations, 0), "site(s) de dégradation silencieuse",
        reverse("gestionsysteme:system-tab", args=["sante"]), tone="info")
    return items


# ── Comment va-t-elle ───────────────────────────────────────────────────

def _mood() -> dict | None:
    def build():
        from config.personality import personality
        from emotion import pad
        from emotion.engine import emotion_engine

        position = emotion_engine.global_mood.dynamic.position
        label, intensity = pad.pad_to_label(position)
        blend = pad.pad_to_blend(position, top_k=3)
        return {
            "label": label.value,
            "intensity": intensity,
            "blend": [
                {"emotion": e.value, "weight": w}
                for e, w in blend
            ],
            "default_mood": personality.temperament.default_mood.value,
            "is_default": label.value == personality.temperament.default_mood.value,
            "velocity": pad.norm(emotion_engine.global_mood.dynamic.velocity),
            "tracked_persons": len(emotion_engine.person_moods),
        }
    return _safe(build)


def _drives() -> list[dict]:
    def build():
        from drives.engine import drive_engine
        drive_engine.update()
        dominant = drive_engine.get_dominant()
        dominant_kind = dominant.kind if dominant else None
        return [
            {
                "kind": kind.value,
                "label": _DRIVE_FR.get(kind.value, kind.value),
                "tension": state.tension,
                "tone": fmt.tone_for_ratio(state.tension, invert=True),
                "dominant": kind == dominant_kind,
            }
            for kind, state in drive_engine.states.items()
        ]
    return _safe(build, []) or []


_DRIVE_FR = {
    "curiosity": "Curiosité",
    "social": "Social",
    "expression": "Expression",
    "rest": "Repos",
}


def _rhythm() -> dict | None:
    def build():
        from config.personality import personality
        from drives.engine import drive_engine
        from emotion import circadian

        state = circadian.current_state(profile=personality.circadian_profile)
        energy = drive_engine.energy_level()
        return {
            "phase": state.phase.value,
            "phase_fr": _PHASE_FR.get(state.phase.value, state.phase.value),
            "hour": state.hour,
            "circadian_energy": state.energy,
            "energy": energy,
            "energy_tone": fmt.tone_for_ratio(energy),
            # Sous 0,5 la conscience applique une pénalité de fatigue et le
            # prompt bascule sur un ton « brouillard cognitif ».
            "fatigued": energy < 0.5,
        }
    return _safe(build)


_PHASE_FR = {
    "morning": "matin", "afternoon": "après-midi",
    "evening": "soirée", "night": "nuit",
}


def _sleep() -> dict | None:
    def build():
        from asgiref.sync import async_to_sync
        from memory import read
        from memory.sleep import sleep_cycle

        journal = async_to_sync(read.latest_journal)()
        dream = async_to_sync(read.dream_of_last_night)()
        return {
            "phase": sleep_cycle.phase,
            "phase_fr": _SLEEP_FR.get(sleep_cycle.phase, sleep_cycle.phase),
            "asleep": sleep_cycle.phase != "awake",
            "journal": journal,
            "dream": dream,
        }
    return _safe(build)


_SLEEP_FR = {
    "awake": "éveillée", "light_sleep": "sommeil léger",
    "rem": "sommeil paradoxal", "deep_sleep": "sommeil profond",
}


def _narrative():
    def build():
        from memory.models import SelfNarrative
        return SelfNarrative.objects.order_by("-created_at").first()
    return _safe(build)


# ── De quoi est faite sa mémoire ────────────────────────────────────────

def _volumes() -> list[dict]:
    def build():
        from datetime import timedelta

        from django.utils import timezone

        from conscience.models import Observation
        from memory.models import (
            Connaissance, Entity, Message, Souvenir,
        )
        from projects.models import Project

        last_24h = timezone.now() - timedelta(hours=24)
        return [
            {
                "label": "Messages (24 h)",
                "value": Message.objects.filter(created_at__gte=last_24h).count(),
                "sub": f"{Message.objects.count()} au total",
                "href": reverse("gestionsysteme:memory-tab", args=["messages"]),
            },
            {
                "label": "Souvenirs",
                "value": Souvenir.objects.count(),
                "sub": "épisodes vécus",
                "href": reverse("gestionsysteme:memory-tab", args=["souvenirs"]),
            },
            {
                "label": "Connaissances",
                "value": Connaissance.objects.filter(is_valid=True).count(),
                "sub": f"{Connaissance.objects.filter(is_valid=False).count()} invalidée(s)",
                "href": reverse("gestionsysteme:memory-tab", args=["connaissances"]),
            },
            {
                "label": "Personnes",
                "value": Entity.objects.filter(entity_type="person").count(),
                "sub": "entités de type personne",
                "href": reverse("gestionsysteme:social-tab", args=["personnes"]),
            },
            {
                "label": "Projets actifs",
                "value": Project.objects.filter(status="active").count(),
                "sub": f"{Project.objects.count()} au total",
                "href": reverse("gestionsysteme:projects"),
            },
            {
                "label": "Observations",
                "value": Observation.objects.count(),
                "sub": "signaux interprétés",
                "href": reverse("gestionsysteme:conscience-tab", args=["observations"]),
            },
        ]
    return _safe(build, []) or []


def _loops() -> list[dict]:
    """Dernier passage de chaque boucle de fond.

    Six boucles écrivent en continu sans superviseur : si l'une s'est arrêtée,
    rien ne le dit ailleurs. La date du dernier passage est le seul témoin
    disponible sans instrumenter les boucles elles-mêmes.
    """
    def build():
        from conscience.models import ConscienceLog
        from memory.models import ConsolidationLog
        from projects.models import ProjectLog

        rows = []

        consolidation = ConsolidationLog.objects.order_by("-ran_at").first()
        rows.append({
            "label": "Consolidation mémoire",
            "at": consolidation.ran_at if consolidation else None,
            "detail": (
                f"{consolidation.messages_processed} message(s), "
                f"{consolidation.souvenirs_created} souvenir(s)"
                if consolidation else "aucun passage enregistré"
            ),
        })

        decision = ConscienceLog.objects.order_by("-created_at").first()
        rows.append({
            "label": "Décision de conscience",
            "at": decision.created_at if decision else None,
            "detail": (
                f"« {decision.decision} » — {fmt.clip(decision.reason, 80)}"
                if decision else "aucun passage enregistré"
            ),
        })

        project_log = ProjectLog.objects.order_by("-created_at").first()
        rows.append({
            "label": "Exécution de projet",
            "at": project_log.created_at if project_log else None,
            "detail": fmt.clip(getattr(project_log, "summary", "") or "—", 80)
                      if project_log else "aucun passage enregistré",
        })
        return rows
    return _safe(build, []) or []
