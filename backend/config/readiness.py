"""État de démarrage du processus et readiness de `/health`.

`/health` répondait toujours ``ok`` : une sonde de vivacité sans readiness.
Un processus qui charge encore son modèle d'embedding, une boucle de fond
morte, un rôle ``conversation`` non mappé — tout cela répondait exactement
comme une installation en bonne santé. Ce module donne à la vue de quoi
répondre *vrai* :

- ``etat_processus`` — la phase du lifespan ASGI, posée par
  ``config.asgi.LifespanWrapper`` (``starting`` → ``started`` →
  ``stopping``). ``absent`` = aucun lifespan n'a tourné (client de test,
  serveur de développement WSGI) ; ce n'est pas un état bloquant, le
  processus sert ce qu'il sait servir.
- ``readiness()`` — le bilan : ``ready`` dit si le processus peut prendre un
  tour ; ``status`` nuance (``ok`` / ``degraded`` / ``starting`` /
  ``stopping`` / ``failed``) ; ``checks`` détaille pour l'exploitant.

Bloquant (``ready = False``) : le lifespan en cours de démarrage ou d'arrêt,
la mémoire longue encore en chargement ou refusée. Dégradant seulement : un
rôle ``conversation`` non mappé (le tour répond un texte de repli, le
processus n'est pas cassé), une boucle de fond arrêtée ou en retard, la
mémoire longue en repli explicite, la file de tours absente.

Ne lit ni base ni réseau : une sonde systemd l'interroge toutes les quelques
secondes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# Une boucle dont le dernier tick réussi remonte à plus de N intervalles est
# « en retard » — la même règle que la page Santé du tableau de bord.
FACTEUR_RETARD_BOUCLE = 10


@dataclass
class EtatProcessus:
    """Phase du lifespan ASGI, écrite par ``LifespanWrapper`` seulement."""

    phase: str = "absent"
    depuis: float = field(default_factory=time.time)
    # Renseigné quand un composant a demandé l'arrêt du processus (mémoire
    # longue refusée) : `/health` répond `failed` jusqu'à la fin.
    echec_fatal: str = ""

    def passer_a(self, phase: str) -> None:
        self.phase = phase
        self.depuis = time.time()


etat_processus = EtatProcessus()


def _check_processus() -> dict:
    phase = etat_processus.phase
    return {
        "ok": phase in ("started", "absent") and not etat_processus.echec_fatal,
        "phase": phase,
        "depuis_s": round(time.time() - etat_processus.depuis, 1),
        "echec_fatal": etat_processus.echec_fatal,
    }


def _check_memoire_longue() -> dict:
    try:
        from memory.manager import memory_manager
        etat = memory_manager.etat_memoire_longue
    except Exception as exc:  # pragma: no cover - import cassé = pas prêt
        return {"ok": False, "etat": "failed", "erreur": str(exc)}
    return {"ok": etat == "ready", "etat": etat}


def _check_boucles() -> dict:
    try:
        from utils.periodic import active_loops
        boucles = active_loops()
    except Exception as exc:
        return {"ok": False, "erreur": str(exc), "actives": 0}
    now = time.time()
    arretees, en_retard = [], []
    for boucle in boucles:
        if not boucle.is_running:
            arretees.append(boucle.name)
            continue
        age = None if boucle.last_success_at is None else now - boucle.last_success_at
        if age is not None and age > FACTEUR_RETARD_BOUCLE * max(boucle.interval, 1):
            en_retard.append(boucle.name)
    return {
        "ok": not arretees and not en_retard,
        "actives": len(boucles) - len(arretees),
        "arretees": arretees,
        "en_retard": en_retard,
    }


def _check_file_de_tours() -> dict:
    try:
        from pipeline.turns import turn_queue
        return {
            "ok": bool(turn_queue.is_running),
            "en_attente": int(turn_queue.pending),
        }
    except Exception as exc:
        return {"ok": False, "erreur": str(exc)}


def _check_role_conversation() -> dict:
    try:
        from ai.router import AIRole, ai_router
        return {
            "ok": True,
            "provider": ai_router.get_provider_name(AIRole.CONVERSATION),
            "model": ai_router.get_model(AIRole.CONVERSATION),
        }
    except Exception as exc:
        return {"ok": False, "erreur": str(exc)}


def readiness() -> dict:
    """Le bilan servi par `/health`. Ne lève jamais."""
    checks = {
        "processus": _check_processus(),
        "memoire_longue": _check_memoire_longue(),
        "boucles": _check_boucles(),
        "file_de_tours": _check_file_de_tours(),
        "role_conversation": _check_role_conversation(),
    }
    phase = checks["processus"]["phase"]
    memoire = checks["memoire_longue"]["etat"]

    if checks["processus"]["echec_fatal"] or memoire == "failed":
        status, ready = "failed", False
    elif phase in ("stopping", "stopped"):
        status, ready = "stopping", False
    elif phase == "starting" or memoire == "starting":
        status, ready = "starting", False
    elif all(c["ok"] for c in checks.values()):
        status, ready = "ok", True
    else:
        status, ready = "degraded", True

    return {"status": status, "ready": ready, "checks": checks}
