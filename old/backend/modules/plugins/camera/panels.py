"""Panneau du module caméra — ce qui est branché, et ce que ça coûte.

Le module ne déclarait ni configuration ni panneau : il n'avait donc aucun
espace dans GestionSystème, et un device qui envoyait des frames n'était
visible nulle part. C'est pourtant le poste de dépense LLM le plus lourd du
moteur, et le seul dont l'état vit entièrement en RAM — rien en base ne permet
de reconstituer après coup ce qu'il a analysé, ni pourquoi il s'est tu.

Un seul panneau, parce qu'il n'y a qu'une question : « qu'est-ce qui est
branché, qu'est-ce qu'elle en voit, et à quelle cadence ». Le verdict
« l'analyse tourne-t-elle en ce moment » est demandé au module lui-même
(``_analysis_allowed``) plutôt que recalculé ici : une seconde implémentation
est la façon dont un écran et la boucle qu'il décrit commencent à diverger.
Seules les *entrées* de ce verdict sont affichées à côté.

Aucune frame n'est rendue : ce panneau décrit un flux vidéo, il ne le rejoue
pas.
"""
from __future__ import annotations

import time

from old.backend.GestionSysteme import tables
from old.backend.GestionSysteme.formatting import ago_span, clip, duration, display_text
from old.backend.GestionSysteme import panels as P

# Repli de ``camera.panel_observation_chars`` — même valeur que le ``default``
# déclaré dans ``config_schema.py``. Troncature d'affichage seulement.
OBSERVATION_MAX = 200


def devices(request):
    from old.backend.modules.manager import module_manager

    module = module_manager.get_registered("camera")
    if module is None:
        return P.Note("Module caméra non enregistré.", tone="warn")

    conf = module._settings_sync()
    now = time.time()
    etats = sorted(module._devices.values(), key=lambda s: s.label.lower())

    page = tables.paginate(request, etats, per_page=25)
    table = _tableau(page.rows, now)
    table.page = page
    table.caption = f"Caméras · retrait après {duration(conf.device_stale_timeout)} sans image"
    return P.Blocks(items=[_boucle(module, conf), table, P.Disclosure(
        title="Connecter une caméra", items=[P.Note(
            "Le client caméra envoie ses images au WebSocket ws/camera?device=<identifiant>&label=<nom>. "
            "Chaque appareil utilise un identifiant distinct ; il apparaît ici à la réception de ses images. "
            "Le panneau affiche les observations, pas la vidéo.")])])


# ── Blocs ───────────────────────────────────────────────────────────────

def _boucle(module, conf) -> P.Fields:
    """État de la boucle d'analyse : ce qu'elle a le droit de faire, et si
    elle le fait en ce moment."""
    actif = module.is_running and conf.proactive_enabled and module._analysis_allowed(conf)

    if not module.is_running:
        etat, ton = "module arrêté", "warn"
    elif not conf.proactive_enabled:
        etat, ton = "désactivée", "warn"
    elif actif:
        etat, ton = "autorisée", "ok"
    else:
        etat, ton = "suspendue (sommeil ou inactivité)", "info"

    return P.Fields(
        title="Boucle d'analyse",
        items=[
            P.Field("Analyse proactive", etat, kind="badge", tone=ton),
            P.Field("Intervalle entre deux analyses", duration(conf.analysis_interval)),
            P.Field(
                "Pause après inactivité",
                duration(conf.idle_pause) if conf.idle_pause > 0 else "jamais",
            ),
            P.Field("Silence actuel", _inactivite()),
            P.Field("Phase de sommeil", _phase()),
            P.Field(
                "Interruptions",
                "autorisées" if conf.notify_enabled else "supprimées",
                kind="badge", tone="ok" if conf.notify_enabled else "warn",
            ),
            P.Field("Délai entre deux interruptions", duration(conf.notify_cooldown)),
        ],
    )


def _tableau(etats, now: float) -> P.Table:
    from old.backend.configs.runtime import cfg_int
    from old.backend.modules.plugins.camera import CameraModule

    obs_max = cfg_int("camera.panel_observation_chars", OBSERVATION_MAX,
                      mini=40, maxi=5000)
    seuil_vivant = CameraModule._max_frame_age()

    rows = []
    for state in etats:
        frame_age = now - state.frame_ts
        vivant = frame_age <= seuil_vivant
        rows.append(P.Row(cells=(
            P.text(state.label),
            P.mono(state.device_id),
            P.badge("en ligne" if vivant else "silencieux",
                    tone="ok" if vivant else "warn"),
            P.text(ago_span(frame_age)),
            P.text(_depuis(state.last_analysis_ts, now)),
            P.text(_depuis(state.last_notify_ts, now)),
            P.text(clip(state.observation, obs_max) or "—"),
            P.text(state.notable_reason or "—", clamp=True),
        ), detail=P.Blocks([
            P.Prose(display_text(state.observation or "Aucune observation.", limit=100_000), title="Observation complète"),
            P.Prose(display_text(state.notable_reason or "Aucun motif notable.", limit=20_000), title="Motif notable"),
        ])))

    return P.Table(
        columns=[
            P.Column("Caméra", align="fit"),
            P.Column("Identifiant"),
            P.Column("Flux", align="fit"),
            P.Column("Dernière frame", align="fit"),
            P.Column("Dernière analyse", align="fit"),
            P.Column("Dernière interruption", align="fit"),
            P.Column("Observation"),
            P.Column("Motif notable"),
        ],
        rows=rows,
        empty="Aucune caméra connectée.",
    )


# ── Lectures d'état, jamais bloquantes ──────────────────────────────────

def _phase() -> str:
    """Brute et en anglais, comme la valeur canonique : c'est la même chaîne
    que celle que la boucle compare, et un écran de diagnostic doit montrer
    ce qui est comparé."""
    try:
        from old.backend.memory.sleep import sleep_cycle
        return sleep_cycle.phase
    except Exception:
        return "—"


def _inactivite() -> str:
    try:
        from old.backend.conscience.engine import conscience_engine
        return ago_span(conscience_engine.get_idle_seconds())
    except Exception:
        return "—"


def _depuis(ts: float, now: float) -> str:
    return f"il y a {ago_span(now - ts)}" if ts > 0 else "jamais"


# ── Déclaration ─────────────────────────────────────────────────────────

def get_panels() -> list:
    return [
        P.ModulePanel(
            key="devices", label="Caméras", icon="◉", order=10,
            handler=devices,
            description=(
                "Caméras connectées, dernière observation produite pour "
                "chacune, et état de la boucle d'analyse."
            ),
        ),
    ]
