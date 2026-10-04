"""Vie intérieure — émotions, pulsions, ruminations, rythme.

Cinq onglets sur une seule destination. Dans l'ancien menu c'étaient quatre
entrées de premier niveau au même poids visuel que « Souvenirs » ou
« Messages », alors qu'elles répondent toutes à la même question : *comment
va-t-elle en ce moment, hors conversation ?*
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.shortcuts import render

from old.backend.GestionSysteme import tables
from old.backend.GestionSysteme.nav import item_for
from old.backend.GestionSysteme.shell import page_context
from old.backend.GestionSysteme import formatting as fmt
from old.backend.utils.degradation import degraded

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
#: États d'une ``Rumination``. Une seule table pour les deux usages — les
#: libellés du filtre et ceux de la colonne — sinon l'un se traduit et pas
#: l'autre, et on filtre sur « résolue » pour obtenir des lignes « resolved ».
_RUMINATION_FR = {
    "active": "active", "resolved": "résolue", "faded": "estompée",
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
        "chantiers": _travaux,
        "rythme": _rhythm,
        "historique": _history,
    }[current.key]
    ctx.update(builder(request))

    return render(request, f"gestion/inner/{current.key}.html", ctx)


# ── Émotions ────────────────────────────────────────────────────────────

def _emotions(request) -> dict:
    from old.backend.emotion import pad
    from old.backend.emotion.engine import emotion_engine

    position = emotion_engine.global_mood.dynamic.position
    label, intensity = pad.pad_to_label(position)
    # L'écart au repos : le nom que le prompt et les portes lisent.
    felt_label, felt_intensity = emotion_engine.global_mood.felt()

    # Les humeurs par personne vivent en RAM, pas en base : elles se
    # paginent comme une liste ordinaire.
    people = []
    # Copie instantanée : ce thread lit pendant que la boucle asyncio insère
    # et évince (« dictionary changed size during iteration »).
    for person_id, mood in emotion_engine.snapshot_moods():
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
    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    search = fs.add(tables.search_filter(request, "q", "Identifiant", placeholder="identifiant de transport"))
    if search.value:
        people = [p for p in people if search.value.casefold() in p["person_id"].casefold()]
    people_page = tables.paginate(request, people, per_page=fs.per_page)
    bound = _bound_entities([p["person_id"] for p in people_page.rows])
    for person in people_page.rows:
        entity = bound.get(person["person_id"])
        person["entity_id"] = entity[0] if entity else None
        person["entity_name"] = entity[1] if entity else ""

    try:
        analytics = emotion_engine.get_analytics()
    except Exception as exc:
        from old.backend.utils.degradation import degradations
        degradations.record("gestion.inner._emotions.analytics", exc)
        analytics = {}

    return {
        "global_mood": {
            "label": label.value,
            "intensity": intensity,
            "felt": felt_label.value,
            "felt_intensity": felt_intensity,
            "blend": [
                {"emotion": e.value, "weight": w}
                for e, w in pad.pad_to_blend(position, top_k=3)
            ],
            "pad": [round(x, 3) for x in position],
            "velocity": pad.norm(emotion_engine.global_mood.dynamic.velocity),
        },
        "people_page": people_page,
        "filterset": fs,
        "analytics": _analytics_view(analytics),
        # Le tempérament s'édite maintenant en Configuration ; la carte qui le
        # recopiait ici est partie avec. On garde le lien : c'est ce qui règle
        # le point de repos de l'oscillateur affiché juste au-dessus, donc la
        # première chose qu'on veut toucher quand cette humeur ne va pas.
        "temperament_url": _config_url("emotion"),
    }


def _config_url(section: str) -> str:
    from django.urls import reverse

    return reverse("gestionsysteme:config-section", args=[section])


def _analytics_view(analytics: dict) -> dict:
    """Les analyses, en valeurs affichables plutôt qu'en dictionnaire brut.

    ``get_analytics`` renvoie une ``distribution`` — un dictionnaire — que la
    page rendait avec ``{{ value }}``, c'est-à-dire le ``repr`` Python d'un
    dict, accolades et guillemets compris, au milieu d'une liste de
    définitions. Elle porte pourtant la seule information intéressante de la
    carte : la part de chaque émotion.
    """
    if not analytics:
        return {}
    distribution = analytics.get("distribution") or {}
    return {
        "total_interactions": analytics.get("total_interactions", 0),
        "persons_tracked": analytics.get("persons_tracked", 0),
        "dominant_emotion": analytics.get("dominant_emotion"),
        "distribution": sorted(
            ({"emotion": name, "weight": weight}
             for name, weight in distribution.items()),
            key=lambda r: r["weight"], reverse=True,
        ),
    }


# ── Pulsions ────────────────────────────────────────────────────────────

def _drives(request) -> dict:
    import time

    from old.backend.drives.engine import drive_engine
    # ``params_for`` et non ``DEFAULT_PARAMS`` : la table est le repli, pas ce
    # qui tourne. Lire la table afficherait les défauts déclarés pendant que le
    # moteur applique les valeurs réglées dans « Pulsions ».
    from old.backend.drives.state import params_for

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
        params = params_for(kind)
        rows.append({
            "kind": kind.value,
            "label": _DRIVE_FR.get(kind.value, kind.value),
            "tension": state.tension,
            "tone": fmt.tone_for_ratio(state.tension, invert=True),
            "dominant": kind == dominant_kind,
            "growth_rate": params.growth_rate,
            "growth_horizon": params.growth_horizon,
            "growth_tau": params.growth_tau,
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
    from old.backend.conscience.models import Rumination

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    status = fs.add(tables.select_filter(
        request, "statut", "État", tuple(_RUMINATION_FR.items()),
    ))

    qs = Rumination.objects.order_by("-intensity", "-created_at")
    if status.value:
        qs = qs.filter(status=status.value)

    return {
        "filterset": fs,
        "page": tables.paginate(request, qs, per_page=fs.per_page),
        "status_tones": {"active": "warn", "resolved": "ok", "faded": ""},
        "status_labels": _RUMINATION_FR,
    }


# ── Chantiers ───────────────────────────────────────────────────────────

_TRAVAIL_FR = {
    "en_cours": "en cours",
    "aboutie": "menée au bout",
    "bloquee": "bloquée",
    "abandonnee": "abandonnée",
}
_TRAVAIL_TONS = {
    "en_cours": "warn", "aboutie": "ok", "bloquee": "danger", "abandonnee": "",
}
_ORIGINE_FR = {
    "observation": "le dehors",
    "pensee": "une pensée qui insiste",
    "pulsion": "une envie",
}


def _travaux(request) -> dict:
    """Ce qu'elle a entrepris, et où ça en est.

    L'envie affichée est **calculée**, jamais celle stockée en base : cette
    dernière n'est qu'un couple (valeur, ancre) dont la valeur seule est
    périmée dès la seconde suivante. Montrer le champ brut ferait dire à
    l'écran l'inverse de ce que le moteur applique — un chantier « à 0,80 »
    que la boucle vient d'abandonner.
    """
    from old.backend.conscience.conduite import TravailEnCours, envie_courante
    from old.backend.conscience.models import Travail
    from django.utils import timezone as tz

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    statut = fs.add(tables.select_filter(
        request, "statut", "État", tuple(_TRAVAIL_FR.items()),
    ))

    search = fs.add(tables.search_filter(request, "q", "Recherche", placeholder="titre du chantier"))
    qs = Travail.objects.order_by("-updated_at", "-pk")
    if search.value:
        qs = qs.filter(titre__icontains=search.value)
    if statut.value:
        qs = qs.filter(statut=statut.value)

    page = tables.paginate(request, qs, per_page=fs.per_page)

    maintenant = tz.now()
    lignes = []
    for row in page.rows:
        vue = TravailEnCours(
            identifiant=row.pk, titre=row.titre, envie=row.envie,
            ancre_envie=row.ancre,
        )
        # Le repli est la valeur stockée : périmée, mais lisible. Laisser la
        # variable non liée ferait tomber la page entière sur un seul chantier
        # dont l'ancre serait malformée.
        courante = row.envie
        with degraded("gestion: envie courante d'un chantier"):
            courante = envie_courante(vue, maintenant)
        lignes.append({
            "row": row,
            "envie": courante,
            "progression": (
                row.pas_effectues / row.pas_max if row.pas_max else 0.0
            ),
        })

    return {
        "filterset": fs,
        "page": page,
        "lignes": lignes,
        "statut_labels": _TRAVAIL_FR,
        "statut_tones": _TRAVAIL_TONS,
        "origine_labels": _ORIGINE_FR,
        "en_cours": Travail.objects.filter(statut="en_cours").count(),
        "en_attente": Travail.objects.filter(statut="en_cours", en_attente_de_reponse=True).count(),
    }


# ── Rythme ──────────────────────────────────────────────────────────────

def _rhythm(request) -> dict:
    from old.backend.config.personality import personality
    from old.backend.drives.engine import drive_engine
    from old.backend.emotion import circadian
    from old.backend.memory.sleep import sleep_cycle

    state = circadian.current_state(profile=personality.circadian_profile)
    energy = drive_engine.energy_level()
    profile = personality.circadian_profile

    # L'estime de soi — la valeur COURANTE, décrue vers le neutre, jamais le
    # champ stocké (le couple valeur/ancre est faux une heure plus tard).
    # L'écran lit ce que le moteur lit.
    estime_valeur = 0.5
    with degraded("gestion: estime de soi"):
        from django.utils import timezone as tz

        from old.backend.conscience.estime import valeur_courante
        from old.backend.conscience.models import EstimeDeSoi

        ligne = EstimeDeSoi.objects.first()
        if ligne is not None:
            estime_valeur = valeur_courante(
                ligne.valeur, ligne.ancre or ligne.updated_at, tz.now(),
            )

    return {
        "estime": estime_valeur,
        "estime_tone": fmt.tone_for_ratio(estime_valeur),
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
#
# Deux tables brutes ne font pas un historique. ``EmotionSnapshot`` écrit une
# ligne **par personne suivie plus une pour ``__global__``**, toutes au même
# instant (``emotion/engine.py::_save_state``) : listées à plat, quatre lignes
# consécutives portent le même horodatage, la même émotion et la même
# intensité, et la colonne « humeur globale » y répète la même valeur autant
# de fois. On y lisait surtout la mécanique d'écriture, jamais l'évolution.
#
# La page répond donc à trois questions séparées :
#   1. comment son humeur à elle a bougé      → série ``__global__``, en frise
#   2. ce qu'elle ressent envers quelqu'un    → une ligne par relevé, avec
#      l'écart au global du même instant (la seule comparaison informative)
#   3. ce qu'il en reste une fois agrégé      → les résumés, répartition
#      comprise — le champ le plus riche du modèle n'était pas affiché.

#: Identifiant réservé sous lequel sa propre humeur est enregistrée. Ce n'est
#: pas une personne : il ne doit jamais apparaître dans une colonne « qui ».
GLOBAL_PERSON_ID = "__global__"

#: Nombre de relevés dans la frise. Au-delà les barres deviennent une bouillie
#: d'un pixel ; en deçà on ne voit plus de tendance.
TIMELINE_POINTS = 72

_PERIOD_FR = {"daily": "jour", "weekly": "semaine"}


def _handle_kind(person_id: str) -> str:
    """``interne`` / ``éphémère`` / ``""`` — la nature d'un handle.

    Un identifiant est opaque (``web_6f3e22ccb0ae``) et tous ne désignent pas
    un interlocuteur : ``conscience_mika`` est sa propre boucle de décision.
    Le dire évite de lire « aucune fiche » là où il n'y a personne à ficher.
    Règle unique, servie par ``identity/trust.py``.
    """
    from old.backend.identity.trust import is_ephemeral_person, is_internal_person

    if is_internal_person(person_id):
        return "interne"
    if is_ephemeral_person(person_id):
        return "éphémère"
    return ""


def _bound_entities(person_ids) -> dict[str, tuple[int, str]]:
    """handle → (id d'entité, nom), pour les seuls handles réellement liés.

    Même règle que ``identity_resolver.entity_for_person`` — handle le plus
    récemment vu, entité obligatoire — mais en une requête pour toute la page
    plutôt qu'une par ligne. Aucune résolution par égalité de nom : c'est
    précisément le bug que la couche identité remplace.
    """
    from old.backend.identity.models import IdentityHandle

    ids = [p for p in person_ids if p and p != GLOBAL_PERSON_ID]
    if not ids:
        return {}

    out: dict[str, tuple[int, str]] = {}
    rows = (
        IdentityHandle.objects
        .filter(person_id__in=ids, identity__entity__isnull=False)
        .select_related("identity__entity")
        .order_by("-last_seen")
    )
    for handle in rows:
        out.setdefault(
            handle.person_id,
            (handle.identity.entity_id, handle.identity.entity.name),
        )
    return out


def _history(request) -> dict:
    from old.backend.memory.models import EmotionalSummary, EmotionSnapshot

    fs = tables.FilterSet(per_page=tables.read_per_page(request))
    person = fs.add(tables.search_filter(request, "personne", "Personne ou identifiant", placeholder="Nom, tg_123, user_7…", suggestions="handles"))
    fs.preserve(request, page_param="p_instantanes")
    fs.hidden = [(k, v) for k, v in fs.hidden if k != "p_resumes"]

    # ``__global__`` a sa propre carte : le laisser dans le tableau des
    # personnes, c'est présenter son humeur à elle comme un interlocuteur.
    snapshots = (
        EmotionSnapshot.objects
        .exclude(person_id=GLOBAL_PERSON_ID)
        .order_by("-created_at")
    )
    # Le consolidateur produit les deux granularités et elles se recouvrent :
    # entrelacées par date, une ligne « semaine » atterrit au milieu de ses
    # propres jours et se lit comme un doublon. On en montre une à la fois.
    period = tables.read_choice(
        request, "periode", ("daily", "weekly"), default="weekly",
    )
    summaries = EmotionalSummary.objects.filter(
        period_type=period,
    ).order_by("-period_start", "person_id")
    if person.value:
        snapshots = snapshots.filter(person_id=person.value)
        summaries = summaries.filter(person_id=person.value)

    snapshots_page = tables.paginate(
        request, snapshots, per_page=fs.per_page, page_param="p_instantanes",
    )
    summaries_page = tables.paginate(
        request, summaries, per_page=25, page_param="p_resumes",
    )

    bound = _bound_entities(
        {s.person_id for s in snapshots_page.rows}
        | {s.person_id for s in summaries_page.rows}
    )

    return {
        "filterset": fs,
        "global_timeline": _global_timeline(),
        "global_page": tables.paginate(request,
            EmotionSnapshot.objects.filter(person_id=GLOBAL_PERSON_ID).order_by("-created_at", "-pk"),
            per_page=25, page_param="p_global"),
        "snapshot_rows": [_snapshot_row(s, bound) for s in snapshots_page.rows],
        "summary_rows": [_summary_row(s, bound) for s in summaries_page.rows],
        # Deux paginations indépendantes sur le même écran : chacune a son
        # propre paramètre d'URL, donc naviguer dans l'une ne déplace pas
        # l'autre.
        "snapshots_page": snapshots_page,
        "summaries_page": summaries_page,
        "retention_days": _snapshot_retention_days(),
        "period": period,
    }


def _global_timeline() -> dict:
    """La série ``__global__`` remise dans l'ordre du temps.

    C'est l'unique endroit de l'interface où l'on voit son humeur *bouger* :
    partout ailleurs on lit une valeur instantanée. Les relevés sont rendus
    dans l'ordre chronologique (la base les sert du plus récent au plus
    ancien), une barre par relevé, hauteur = intensité, couleur = émotion.
    """
    from old.backend.memory.models import EmotionSnapshot

    rows = list(
        EmotionSnapshot.objects
        .filter(person_id=GLOBAL_PERSON_ID)
        .order_by("-created_at")[:TIMELINE_POINTS]
    )
    rows.reverse()
    if not rows:
        return {"points": [], "count": 0}

    points = [
        {
            "emotion": s.global_emotion,
            "intensity": s.global_intensity,
            "at": s.created_at,
        }
        for s in rows
    ]

    # Part de chaque émotion dans la fenêtre affichée : la légende de la
    # frise, et de quoi lire « majoritairement sereine » d'un coup d'œil.
    share: dict[str, int] = {}
    for p in points:
        share[p["emotion"]] = share.get(p["emotion"], 0) + 1
    legend = sorted(
        (
            {"emotion": name, "count": n, "share": n / len(points)}
            for name, n in share.items()
        ),
        key=lambda r: r["count"], reverse=True,
    )

    return {
        "points": points,
        "count": len(points),
        "first_at": points[0]["at"],
        "last_at": points[-1]["at"],
        "current": points[-1],
        "legend": legend,
        "truncated": len(rows) == TIMELINE_POINTS,
    }


def _snapshot_row(snap, bound: dict) -> dict:
    """Un relevé, augmenté de ce qui le rend lisible.

    ``delta`` est l'écart entre ce qu'elle ressent envers cette personne et
    son humeur générale *au même instant* — les deux colonnes « Intensité »
    d'avant ne disaient pas laquelle était laquelle, et la seconde répétait la
    même valeur sur toutes les lignes d'un même relevé.
    """
    entity = bound.get(snap.person_id)
    return {
        "at": snap.created_at,
        "person_id": snap.person_id,
        "kind": _handle_kind(snap.person_id),
        "entity_id": entity[0] if entity else None,
        "entity_name": entity[1] if entity else None,
        "emotion": snap.primary_emotion,
        "intensity": snap.primary_intensity,
        "global_emotion": snap.global_emotion,
        "global_intensity": snap.global_intensity,
        "delta": snap.primary_intensity - snap.global_intensity,
        "same_as_global": snap.primary_emotion == snap.global_emotion,
    }


def _summary_row(summary, bound: dict) -> dict:
    entity = bound.get(summary.person_id)
    trend_fr, trend_tone = fmt.TREND_LABELS.get(
        summary.trend, (summary.trend or "—", ""),
    )
    distribution = summary.emotion_distribution or {}
    return {
        "period_start": summary.period_start,
        # ``period_start`` d'une ligne hebdomadaire porte le **lundi** de la
        # semaine ISO. Affiché seul il se lit comme une date isolée : « le 27 »
        # au lieu de « la semaine du 27 ».
        "period_end": (
            summary.period_start + timedelta(days=6)
            if summary.period_type == "weekly" else None
        ),
        "period_fr": _PERIOD_FR.get(summary.period_type, summary.period_type),
        "person_id": summary.person_id,
        "kind": _handle_kind(summary.person_id),
        "entity_id": entity[0] if entity else None,
        "entity_name": entity[1] if entity else None,
        "dominant_emotion": summary.dominant_emotion,
        "dominant_intensity": summary.dominant_intensity,
        "trend_fr": trend_fr,
        "trend_tone": trend_tone,
        "snapshot_count": summary.snapshot_count,
        "distribution": sorted(
            ({"emotion": k, "weight": v} for k, v in distribution.items()),
            key=lambda r: r["weight"], reverse=True,
        ),
    }


def _snapshot_retention_days():
    """Depuis quand les relevés existent encore — la page se date elle-même.

    Sans cela, une frise courte se lit « elle n'a rien ressenti » alors qu'elle
    dit « le consolidateur a élagué au-delà de N jours ».
    """
    try:
        from old.backend.configs.service import config_service
        return config_service.get("emotion.snapshot_retention_days")
    except Exception as exc:
        from old.backend.utils.degradation import degradations
        degradations.record("gestion.inner._snapshot_retention_days", exc)
        return None
