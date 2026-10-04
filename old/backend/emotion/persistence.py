"""Relevés et résumés : ce que l'état émotionnel garde d'un processus à l'autre.

Lecture et écriture des ``EmotionSnapshot`` / ``EmotionalSummary`` pour le
moteur — restauration au démarrage, hydratation paresseuse d'une personne,
relevé de tour, sauvegarde à l'arrêt. Chaque question a UNE implémentation :

- un seul écrivain de relevé (``_ecrire_releve``), que le relevé d'un tour
  et la ligne d'arrêt appellent tous deux ;
- un seul chargeur relevés → humeur (``mood_from_rows``), servi au boot
  comme à l'hydratation paresseuse — les deux portaient chacun leur copie
  (ancre, repos propre, vieillissement), et une correction touchait l'une
  sans l'autre ;
- un seul lecteur de résumé quotidien (``moods_from_summaries``), pour
  toutes les personnes au boot ou pour une seule à l'hydratation.

Les fonctions prennent le moteur en premier argument et passent par SA
surface (``_home_vector``, ``_person_home``, ``_person_impulse_params``,
``_get_person_mood``) : c'est elle que les tests patchent. Les modèles sont
importés dans les fonctions — ce module est importé par le moteur, lui-même
importé avant que le registre d'applications Django soit prêt.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

from asgiref.sync import sync_to_async

from old.backend.configs.runtime import cfg_int
from old.backend.emotion import physics
from old.backend.emotion.pad import Vec3
from old.backend.emotion.state import PersonMood
from old.backend.emotion.types import Emotion, EmotionData
from old.backend.identity.trust import is_identifiable_person
from old.backend.emotion import dynamics, pad
from old.backend.utils.degradation import degradations

logger = logging.getLogger(__name__)

#: Combien de relevés récents nourrissent l'ancre d'une personne.
ANCHOR_SAMPLE = 20


# ----------------------------------------------------------------------
# Écriture
# ----------------------------------------------------------------------

async def _ecrire_releve(
    conversation, person_id: str,
    p_label: Emotion, p_intensity: float,
    g_label: Emotion, g_intensity: float,
    *, declared: bool,
) -> None:
    """Le seul ``EmotionSnapshot.objects.create`` du moteur."""
    from old.backend.memory.models import EmotionSnapshot

    await sync_to_async(EmotionSnapshot.objects.create)(
        conversation=conversation,
        person_id=person_id,
        primary_emotion=p_label.value,
        primary_intensity=p_intensity,
        global_emotion=g_label.value,
        global_intensity=g_intensity,
        declared=declared,
    )


async def save_all(engine) -> None:
    """Persist current state as (label, intensity) snapshots per person + global.

    ``declared=False`` partout : une ligne d'arrêt EST une position, pas une
    balise — la restauration ne lui applique pas le cliquet.
    """
    from old.backend.memory.manager import memory_manager

    conversation = memory_manager.conversation
    if not conversation:
        return

    try:
        g_label, g_intensity = pad.pad_to_label(engine.global_mood.dynamic.position)
        await _ecrire_releve(
            conversation, "__global__", g_label, g_intensity, g_label, g_intensity,
            declared=False,
        )
        for pid, mood in engine.snapshot_moods():
            if not is_identifiable_person(pid):
                continue
            p_label, p_intensity = pad.pad_to_label(mood.dynamic.position)
            await _ecrire_releve(
                conversation, pid, p_label, p_intensity, g_label, g_intensity,
                declared=False,
            )
        logger.info(
            "Saved emotion state: global=%s(%.2f), %d person mood(s)",
            g_label.value, g_intensity, len(engine.person_moods),
        )
    except Exception:
        logger.exception("Failed to save emotion state")


async def save_person_snapshot(
    engine, person_id: str, declared: EmotionData | None = None,
) -> bool:
    """Persist a single EmotionSnapshot for one person + current global mood.

    Returns whether a row was actually written. Ce qui est écrit nourrit
    l'ancre (``physics.fold_anchor``), pour que l'ancre et le relevé
    racontent la même histoire — la balise quand le tour en a déclaré une.
    """
    from old.backend.memory.manager import memory_manager

    conversation = memory_manager.conversation
    if not conversation:
        return False

    person = engine._get_person_mood(person_id)
    if declared is not None:
        p_label, p_intensity = declared.emotion, declared.intensity
    else:
        p_label, p_intensity = pad.pad_to_label(person.dynamic.position)
    # The background mood is never what a turn declared: it stays read off
    # the global oscillator.
    g_label, g_intensity = pad.pad_to_label(engine.global_mood.dynamic.position)

    try:
        await _ecrire_releve(
            conversation, person_id, p_label, p_intensity, g_label, g_intensity,
            declared=declared is not None,
        )
    except Exception as exc:
        degradations.record("emotion.persistence.save_person_snapshot", exc)
        logger.debug("Failed to save snapshot for %s", person_id, exc_info=True)
        return False

    physics.fold_anchor(
        person, pad.label_to_pad(p_label, p_intensity), engine._home_vector(),
    )
    return True


# ----------------------------------------------------------------------
# Lecture : d'un relevé à une humeur
# ----------------------------------------------------------------------

async def recent_rows(person_id: str, *, aliases=()) -> list:
    """Les derniers relevés d'une personne, le plus récent en tête.

    Une requête, servie par l'index (person_id, -created_at) : la tête donne
    la position, la queue donne l'ancre personnelle.
    """
    from old.backend.memory.models import EmotionSnapshot

    echantillon = cfg_int("emotion.anchor_sample", ANCHOR_SAMPLE, mini=1)
    return await sync_to_async(
        lambda: list(
            EmotionSnapshot.objects
            .filter(person_id__in=[person_id, *aliases])
            .order_by("-created_at")[:echantillon]
        )
    )()


def position_du_releve(engine, snap, home: Vec3) -> Vec3:
    """La position que le relevé décrit, au moment où il a été écrit.

    Une ligne de tour porte la BALISE déclarée (``declared=True``), pas la
    position : l'impulsion ne parcourt qu'une part du chemin (le gain,
    ~51 % au tempérament par défaut), donc restaurer ``angry 0.8`` tel
    quel ramenait une position que l'oscillateur vivant n'avait jamais
    atteinte (0,46). On rejoue le cliquet depuis le repos — le pas qu'un
    tour provoque au minimum. Une ligne d'arrêt (``declared=False``) EST
    une position et se prend telle quelle.
    """
    try:
        label = Emotion(snap.primary_emotion)
    except ValueError:
        return home
    cible = pad.label_to_pad(label, snap.primary_intensity)
    if not getattr(snap, "declared", False):
        return cible
    return dynamics.apply_impulse(home, cible, engine._person_impulse_params(cible))


def mood_from_rows(engine, person_id: str, rows: list, now_ts: float) -> PersonMood:
    """L'humeur qu'un jeu de relevés (non vide, le plus récent en tête) décrit.

    L'ancre AVANT la position : sans elle, le relevé était ramené vers le
    repos commun jusqu'à la première lecture, et ``_apply_decay`` tirait la
    stance d'un ami vers le repos d'un inconnu. Des relevés qui ne donnent
    aucune ancre lisible posent le repos commun plutôt que ``None`` — le
    contrat de ``backfill_anchor`` — sinon chaque lecture rejouerait la
    requête. Puis le relevé de tête est VIEILLI par l'oscillateur lui-même
    (``physics.aged_position``) du temps écoulé depuis son écriture : l'état
    est celui que la boucle aurait atteint si le processus n'avait pas cessé.
    """
    snap = rows[0]
    elapsed = max(0.0, now_ts - snap.created_at.timestamp())
    home = engine._home_vector()
    mood = PersonMood(person_id=person_id)
    mood.last_interaction = snap.created_at.timestamp()
    ancre = physics.anchor_from_rows(rows, home)
    mood.anchor = ancre if ancre is not None else home
    repos = engine._person_home(mood, home)
    mood.dynamic.position = physics.aged_position(
        position_du_releve(engine, snap, repos), repos, elapsed, engine._person_params,
    )
    return mood


async def backfill_anchor(engine, mood: PersonMood) -> None:
    """Recalcule l'ancre d'une humeur déjà en RAM mais sans ancre.

    Une seule requête, une seule fois par personne et par processus : au
    retour, ``mood.anchor`` n'est plus ``None`` (même si les relevés ne
    donnent rien, on pose le repos circadien courant plutôt que de rejouer
    la requête à chaque tour).
    """
    try:
        rows = await recent_rows(mood.person_id)
        home = engine._home_vector()
        ancre = physics.anchor_from_rows(rows, home) if rows else None
        mood.anchor = ancre if ancre is not None else home
    except Exception as exc:
        degradations.record("emotion.persistence.backfill_anchor", exc)
        mood.anchor = engine._home_vector()


async def ensure_person_loaded(engine, person_id: str, *, aliases=()) -> None:
    """Hydrate a person's mood from DB if they are not currently in RAM.

    La question « est-ce une vraie personne ? » a un seul domicile,
    ``identity/trust.py`` : la redire ici l'avait déjà fait diverger
    (``conscience_mika``, ``""`` et tout le préfixe ``anon_*`` passaient
    au travers). Un handle éphémère est un uuid frappé quelques secondes
    plus tôt : il ne peut par construction porter ni relevé ni résumé, et
    chaque socket anonyme payait deux requêtes garanties vides.

    Dès qu'un relevé existe, c'est lui qui répond — jamais le résumé
    quotidien, plus vieux et plus grossier. Retomber sur le résumé quand le
    relevé a « trop vieilli » ressuscitait l'émotion dominante de la veille
    pour quelqu'un dont l'oscillateur s'était justement apaisé.
    """
    if not is_identifiable_person(person_id):
        return
    existante = engine.person_moods.get(person_id)
    if existante is not None:
        # ``restore_state`` peuplait ``person_moods`` sans ancre, et cette
        # fonction est la seule à savoir la recalculer. Un simple « déjà en
        # RAM » la rendait irrécupérable pour toute la durée du processus :
        # ce qui distingue un ami d'un troll était remis à zéro par le
        # moindre redémarrage. On comble l'ancre manquante — jamais la
        # position, qui est vivante.
        if existante.anchor is None:
            await backfill_anchor(engine, existante)
        return

    try:
        rows = await recent_rows(person_id, aliases=aliases)
        if rows:
            mood = mood_from_rows(engine, person_id, rows, time.time())
            engine.person_moods[person_id] = mood
            logger.debug(
                "Lazy-loaded mood for %s: %s from snapshot (aged to %s)",
                person_id, rows[0].primary_emotion,
                pad.pad_to_label(mood.dynamic.position)[0].value,
            )
            return

        seeded = await moods_from_summaries(engine, person_id=person_id)
        mood = seeded.get(person_id)
        if mood is not None:
            engine.person_moods[person_id] = mood
            logger.debug(
                "Lazy-loaded mood for %s from EmotionalSummary", person_id,
            )
    except Exception as exc:
        degradations.record("emotion.persistence.ensure_person_loaded", exc)
        logger.debug("Failed to lazy-load mood for %s", person_id, exc_info=True)


# ----------------------------------------------------------------------
# Lecture : les résumés quotidiens, quand aucun relevé ne reste
# ----------------------------------------------------------------------

def summary_decay_days(engine) -> int:
    """Horizon d'exploitation d'un ``EmotionalSummary``, en jours.

    L'attribut de classe reste le repli. ``_SNAPSHOT_DECAY_DAYS``, lui,
    est déjà chargé une fois à l'``initialize()`` : c'est une rétention
    de table, pas un curseur qu'on essaie en regardant l'humeur bouger.
    """
    return cfg_int(
        "emotion.summary_retention_days", engine._SUMMARY_DECAY_DAYS, mini=1,
    )


def faded_mood(
    period_start: date, dominant_emotion: str, dominant_intensity: float,
    horizon: int,
) -> tuple[Emotion, float] | None:
    """``(emotion, intensity)`` faded by the age of a daily summary row.

    ``horizon`` est lu une fois par l'appelant : le seuil et le ratio doivent
    parler du même horizon, y compris si le réglage change entre deux lignes.
    """
    age_days = (date.today() - period_start).days
    if age_days >= horizon:
        return None
    intensity = dominant_intensity * max(0.0, 1.0 - age_days / horizon)
    if intensity < 0.05:
        return None
    try:
        emotion = Emotion(dominant_emotion)
    except ValueError:
        return None
    return emotion, intensity


async def moods_from_summaries(
    engine, *, person_id: str | None = None, exclude: set[str] = frozenset(),
) -> dict[str, PersonMood]:
    """Les humeurs que les résumés quotidiens permettent encore de poser.

    Une seule requête, servie par l'index (person_id, -period_start) : les
    lignes arrivent groupées par personne, la plus récente en tête, donc la
    première rencontrée est celle qu'on veut. Au-delà de l'horizon, une
    ligne ne produit plus aucune humeur : la borne appartient au WHERE, pas
    à une boucle Python qui aurait d'abord fait grouper tout l'historique.
    ``person_id`` restreint à une seule personne (hydratation paresseuse),
    ``exclude`` écarte celles qu'un relevé vient de charger (démarrage).
    Vide, jamais une exception : la dégradation est comptée.
    """
    from old.backend.memory.models import EmotionalSummary

    try:
        horizon = summary_decay_days(engine)
        cutoff = date.today() - timedelta(days=horizon)
        requete = (
            EmotionalSummary.objects
            .filter(period_type="daily", period_start__gt=cutoff)
            .order_by("person_id", "-period_start")
        )
        if person_id is not None:
            requete = requete.filter(person_id=person_id)
        if exclude:
            requete = requete.exclude(person_id__in=exclude)
        rows = await sync_to_async(
            lambda: list(requete.values(
                "person_id", "period_start", "dominant_emotion", "dominant_intensity",
            ))
        )()

        moods: dict[str, PersonMood] = {}
        for row in rows:
            pid = row["person_id"]
            if pid in moods or not is_identifiable_person(pid):
                continue
            result = faded_mood(
                row["period_start"], row["dominant_emotion"],
                row["dominant_intensity"], horizon,
            )
            if result is None:
                continue
            label, intensity = result
            mood = PersonMood(person_id=pid)
            mood.dynamic.position = pad.label_to_pad(label, intensity)
            moods[pid] = mood
        return moods
    except Exception as exc:
        degradations.record("emotion.persistence.moods_from_summaries", exc)
        logger.debug("Failed to read EmotionalSummary rows", exc_info=True)
        return {}


# ----------------------------------------------------------------------
# Démarrage
# ----------------------------------------------------------------------

async def _derniers_releves() -> list:
    """Le relevé le plus récent de chaque ``person_id`` (``__global__`` compris)."""
    from django.db.models import Max
    from old.backend.memory.models import EmotionSnapshot

    latest_ids = await sync_to_async(
        lambda: list(
            EmotionSnapshot.objects
            .values("person_id")
            .annotate(latest_id=Max("id"))
            .values_list("latest_id", flat=True)
        )
    )()
    if not latest_ids:
        return []
    return await sync_to_async(
        lambda: list(EmotionSnapshot.objects.filter(id__in=latest_ids))
    )()


def _restaurer_le_fond(engine, snapshots: list, home: Vec3, now_ts: float, max_age: float) -> None:
    """L'humeur de fond, depuis le relevé le plus récent de QUI QUE CE SOIT.

    L'humeur de fond n'a qu'un écrivain dédié, ``save_all``, à l'arrêt
    PROPRE : après un crash, un OOM ou un SIGKILL la seule ligne
    ``__global__`` datait de la veille (ou n'existait pas) et le fond
    repartait de l'origine — pas même du repos. Or chaque relevé de tour
    porte ``global_emotion`` : le plus récent de tous, quelle que soit la
    personne, est la lecture la plus fraîche du fond qu'on ait.
    """
    plus_recent = max(snapshots, key=lambda r: r.created_at)
    elapsed = now_ts - plus_recent.created_at.timestamp()
    if elapsed > max_age:
        return
    try:
        g_label = Emotion(plus_recent.global_emotion)
    except ValueError:
        return
    engine.global_mood.dynamic.position = physics.aged_position(
        pad.label_to_pad(g_label, plus_recent.global_intensity),
        home, elapsed, engine._global_params,
    )
    engine.global_mood.dynamic.velocity = pad.zero()


async def restore_state(engine) -> bool:
    """Restore state from snapshots (+summary fallback). Lossy reconstruction.

    Chaque personne dont le relevé de tête est encore dans la rétention
    passe par le même chargeur que l'hydratation paresseuse
    (``mood_from_rows``) ; les autres sont laissées à
    ``moods_from_summaries``, comme avant, plutôt qu'inscrites dans
    l'ensemble d'exclusion.
    """
    max_age_seconds = engine._SNAPSHOT_DECAY_DAYS * 86400

    try:
        now_ts = time.time()
        home = engine._home_vector()
        engine.global_mood.home = home
        snapshots = await _derniers_releves()

        persons_from_snapshots: set[str] = set()
        if snapshots:
            _restaurer_le_fond(engine, snapshots, home, now_ts, max_age_seconds)
            for snap in snapshots:
                # Une seule règle pour « est-ce une personne ? » : les
                # relevés d'``anon_*`` et de ``conscience_mika`` écrits
                # avant la garde de ``save_snapshot`` ne sont pas rechargés
                # (``__global__`` non plus).
                if not is_identifiable_person(snap.person_id):
                    continue
                if now_ts - snap.created_at.timestamp() > max_age_seconds:
                    continue
                rows = await recent_rows(snap.person_id)
                if not rows:
                    continue
                engine.person_moods[snap.person_id] = mood_from_rows(
                    engine, snap.person_id, rows, now_ts,
                )
                persons_from_snapshots.add(snap.person_id)

        depuis_resumes = await moods_from_summaries(engine, exclude=persons_from_snapshots)
        engine.person_moods.update(depuis_resumes)
        restored_persons = len(persons_from_snapshots) + len(depuis_resumes)

        if (
            restored_persons == 0
            and pad.distance(engine.global_mood.dynamic.position, home) < 0.05
        ):
            return False

        g_label, g_intensity = pad.pad_to_label(engine.global_mood.dynamic.position)
        logger.info(
            "Restored emotion state: global=%s(%.2f), %d person(s) "
            "[snapshots: %d, summaries: %d]",
            g_label.value, g_intensity, restored_persons,
            len(persons_from_snapshots), len(depuis_resumes),
        )
        return True

    except Exception:
        logger.exception("Failed to restore emotion state")
        return False
