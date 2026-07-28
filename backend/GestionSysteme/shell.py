"""Coquille de page — contexte commun à tous les gabarits.

Construit le menu (statique + espaces de modules découverts à chaud), les
compteurs de badges et les indicateurs de la barre supérieure.

**Toute lecture est isolée.** Un sous-système en panne fait disparaître son
compteur, jamais la page : cette interface est précisément l'endroit où on
vient constater qu'une chose est cassée, elle ne peut pas tomber avec.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.urls import reverse

from GestionSysteme import formatting as fmt
from GestionSysteme.nav import NAV, NavItem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModuleSpace:
    """Un module disposant d'un espace dans l'interface."""
    name: str
    label: str
    icon: str
    running: bool
    panel_count: int
    has_config: bool


@dataclass(frozen=True)
class SpaceLink:
    """Une entrée du groupe « Espaces » du menu.

    Le gabarit itère des liens, pas des modules : toutes les entrées de ce
    groupe ne correspondent pas à un module (cf. « Forge apps »), et une
    condition sur un nom de module dans un gabarit est exactement le genre
    de connaissance qui n'a rien à y faire.
    """
    key: str
    label: str
    icon: str
    url: str
    alert: str = ""            # texte court de la pastille ("" = aucune)
    alert_title: str = ""


# ── Compteurs de badges ─────────────────────────────────────────────────

def sidebar_counts() -> dict[str, int]:
    """Compteurs affichés en pastille dans le menu et les onglets.

    Ne compte que ce qui **attend une action ou signale un problème** : une
    pastille qui affiche la taille d'une table est un chiffre que personne ne
    lit deux fois. Les volumes vivent sur la page concernée.
    """
    counts: dict[str, int] = {}

    def safe(key: str, fn) -> None:
        try:
            value = int(fn())
        except Exception:
            logger.debug("compteur %s indisponible", key, exc_info=True)
            return
        if value:
            counts[key] = value

    def _identity_claims() -> int:
        from identity.models import IdentityClaim
        return IdentityClaim.objects.filter(status="pending").count()

    def _observations() -> int:
        from conscience.models import Observation
        return Observation.objects.filter(status="pending").count()

    def _ruminations() -> int:
        from conscience.models import Rumination
        return Rumination.objects.filter(status="active").count()

    def _commitments() -> int:
        from memory.models import Commitment
        return Commitment.objects.filter(status="pending").count()

    def _pending_actions() -> int:
        from projects.models import ProjectPendingAction
        return ProjectPendingAction.objects.filter(status="pending").count()

    def _degradations() -> int:
        from utils.degradation import degradations
        return len(degradations.snapshot())

    def _modules_down() -> int:
        """Modules activés qui ne tournent pas — le seul état à signaler.

        Un module volontairement désactivé n'est pas une anomalie ; un module
        activé et arrêté l'est.
        """
        from modules.manager import module_manager
        return sum(
            1 for info in module_manager.list_all()
            if info.get("enabled") and not info.get("running")
            and not info.get("system")
        )

    safe("identity", _identity_claims)
    safe("claims", _identity_claims)
    safe("observations", _observations)
    safe("ruminations", _ruminations)
    safe("commitments", _commitments)
    safe("pending_actions", _pending_actions)
    safe("degradations", _degradations)
    safe("modules_down", _modules_down)
    return counts


# ── Indicateurs de la barre supérieure ──────────────────────────────────

def vitals() -> dict[str, str]:
    """Valeurs de la barre supérieure, déjà mises en forme.

    Rendues côté serveur au premier affichage puis rafraîchies par
    ``gestion.js``. Le format est identique dans les deux cas — un seul
    endroit décide comment une humeur s'écrit.
    """
    out = {
        "status": "hors ligne",
        "phase": "—",
        "energy": "—",
        "mood": "—",
        "sleep": "—",
    }
    try:
        from config.personality import personality
        from emotion import circadian, pad
        from emotion.engine import emotion_engine
        from drives.engine import drive_engine
        from memory.sleep import sleep_cycle

        label, intensity = pad.pad_to_label(
            emotion_engine.global_mood.dynamic.position
        )
        drive_engine.update()
        state = circadian.current_state(profile=personality.circadian_profile)

        out.update({
            "status": "en ligne",
            "phase": _PHASE_FR.get(state.phase.value, state.phase.value),
            "energy": fmt.pct(drive_engine.energy_level()),
            "mood": f"{fmt.emotion_fr(label.value)} {fmt.pct(intensity)}",
            "sleep": _SLEEP_FR.get(sleep_cycle.phase, sleep_cycle.phase),
        })
    except Exception:
        logger.debug("indicateurs vitaux indisponibles", exc_info=True)
    return out


_PHASE_FR = {
    "morning": "matin",
    "afternoon": "après-midi",
    "evening": "soirée",
    "night": "nuit",
}

_SLEEP_FR = {
    "awake": "éveillée",
    "light_sleep": "sommeil léger",
    "rem": "sommeil paradoxal",
    "deep_sleep": "sommeil profond",
}


# ── Espaces de modules ──────────────────────────────────────────────────

def module_spaces() -> list[ModuleSpace]:
    """Modules ayant droit à un espace, découverts à chaque rendu.

    Un module apparaît dès qu'il est **enregistré**, pas seulement quand il
    tourne : le cas qui compte est précisément celui d'un module arrêté qu'on
    vient configurer pour qu'il démarre. L'ancienne interface ne montrait que
    les modules en marche, donc la page de réglages d'un module en panne était
    inatteignable depuis le menu.
    """
    from GestionSysteme.panels import collect_spaces
    try:
        return collect_spaces()
    except Exception:
        logger.exception("découverte des espaces de modules impossible")
        return []


FORGE_MODULE = "forge"


def sidebar_spaces() -> list[SpaceLink]:
    """Le groupe « Espaces » du menu : un lien par module, plus Forge apps.

    « Forge apps » se glisse **juste après la Forge** : l'atelier d'abord, ce
    qui en sort ensuite. C'est la seule entrée du groupe qui ne soit pas un
    module, et elle ne peut pas en être une — les apps forgées sont écrites à
    l'exécution, aucune destination ne peut être déclarée à l'avance pour
    chacune. D'où une page qui les liste, et un espace par app derrière.
    """
    links: list[SpaceLink] = []
    for space in module_spaces():
        arrete = not space.running
        links.append(SpaceLink(
            key=space.name,
            label=space.label,
            icon=space.icon,
            url=reverse("gestionsysteme:module-space", args=[space.name]),
            alert="!" if arrete else "",
            alert_title=("activé mais arrêté" if arrete else ""),
        ))
        if space.name == FORGE_MODULE:
            links.append(_forge_apps_link())
    return links


def _forge_apps_link() -> SpaceLink:
    casses = 0
    try:
        from modules.manager import module_manager
        host = module_manager.get_registered(FORGE_MODULE)
        if host is not None:
            casses = sum(
                1 for i in host.module_infos()
                if i.get("status") in ("cassé", "désactivé")
            )
    except Exception:
        logger.exception("comptage des apps forgées impossible")
    return SpaceLink(
        key="forge_apps",
        label="Forge apps",
        icon="◫",
        url=reverse("gestionsysteme:forge-apps"),
        alert=str(casses) if casses else "",
        alert_title="app(s) désactivée(s) ou cassée(s)" if casses else "",
    )


# ── Contexte de page ────────────────────────────────────────────────────

def page_context(
    request,
    *,
    item: NavItem | None = None,
    active_key: str = "",
    active_tab: str = "",
    title: str = "",
    description: str = "",
    module_space: str = "",
    active_space: str = "",
    **extra,
) -> dict:
    """Contexte partagé par tous les gabarits de l'interface.

    ``item`` fournit titre, description et onglets ; ``title`` et
    ``description`` ne servent qu'à les surcharger (page de détail par
    exemple, où le titre est le nom de l'objet).
    """
    counts = sidebar_counts()

    ctx = {
        "nav": NAV,
        "nav_counts": counts,
        "spaces": sidebar_spaces(),
        "active_key": active_key or (item.key if item else ""),
        # ``module_space`` reste le nom du module pour les espaces de modules ;
        # une entrée qui n'en est pas un (Forge apps) passe ``active_space``.
        "active_space": active_space or module_space,
        "active_tab": active_tab,
        "nav_item": item,
        "tabs": item.tabs if item else (),
        "page_title": title or (item.label if item else "Gestion Système"),
        "page_description": description or (item.description if item else ""),
        "vitals": vitals(),
        "vitals_url": reverse("gestionsysteme:api-vitals"),
    }
    ctx.update(extra)
    return ctx
