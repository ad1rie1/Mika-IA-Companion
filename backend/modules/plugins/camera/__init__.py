"""CameraModule — pipeline de perception visuelle proactive.

Chaque device (bureau, salon, mobile…) envoie des frames via ws/camera?device=xxx.
Le module analyse les frames en arrière-plan, produit des observations texte,
et les injecte dans le prompt de Claude via get_context().
Claude n'est jamais bloqué sur une image brute — il reçoit du texte contextualisé.

Flux :
  1. CameraConsumer.register_frame(device_id, label, data, mime)
  2. worker_cron() → détection changement (frame_changed_since_analysis) → analyse vision async
  3. _analyze_device() → CameraObservation { description, notable }
  4a. get_context()  → texte injecté dans le prompt système
  4b. si notable    → notify_ai() → Conscience → réaction spontanée

Ce que ça coûte, et ce qui le borne : chaque analyse transporte une frame
complète vers le modèle vision, et chaque notification ouvre un tour de
pipeline entier. Les deux cadences sont donc réglables depuis le tableau de
bord (``config_schema.py``) et relues à chaque tour — tous les réglages sont
marqués « à chaud ».
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import time
from dataclasses import dataclass

from modules.base import BaseModule
from modules.types import (
    ModuleCapability,
    ModuleNotification,
    ModuleTool,
    ToolParameter,
    ToolParameterType,
)
from utils.degradation import degradations

logger = logging.getLogger(__name__)

# Valeurs de repli, identiques aux défauts déclarés dans config_schema.py.
# Elles ne servent que si la configuration est illisible — jamais comme
# réglage en dur : ce sont ces trois nombres qui faisaient du module le seul
# poste de dépense LLM du moteur qu'on ne pouvait ni voir ni borner.
#
# Intervalle minimum entre deux analyses vision pour un même device (secondes)
MIN_ANALYSIS_INTERVAL = 120
# Délai minimum entre deux interruptions déclenchées par un même device (s)
NOTIFY_COOLDOWN_S = 300
# Silence au-delà duquel l'analyse de fond s'arrête (secondes)
IDLE_PAUSE_S = 900
# Délai minimum entre deux regards actifs (camera_see) sur un même device (s)
SEE_MIN_INTERVAL_S = 10
# Âge max d'une observation pour qu'elle soit injectée dans le contexte (secondes)
MAX_OBSERVATION_AGE = 600  # 10 min
# Âge max d'une frame pour déclencher une analyse (secondes)
MAX_FRAME_AGE_FOR_ANALYSIS = 60
# Délai avant de supprimer un device inactif (secondes)
DEVICE_STALE_TIMEOUT = 600  # 10 min

# Hash perceptuel — taille de la miniature et pas de quantification
_THUMB_SIZE = 16    # 16×16 px après resize
_QUANTIZE_STEP = 16  # absorbe le bruit ±8 niveaux de gris (ex: variations d'exposition auto)


@dataclass
class DeviceState:
    """État courant d'un device caméra."""

    device_id: str
    label: str                            # nom lisible : "bureau", "salon", "mobile"
    frame_data: str                       # base64 de la dernière frame reçue
    frame_mime: str
    frame_ts: float                       # timestamp de la frame
    frame_hash: str                       # MD5 pour la détection de changement

    # FIX #3 : flag explicite pour éviter les analyses redondantes
    frame_changed_since_analysis: bool = True  # True = nouvelle frame à analyser

    observation: str = ""                 # dernière description produite par la vision
    observation_ts: float = 0.0           # timestamp de cette observation
    notable_reason: str = ""             # pourquoi c'est notable (vide si pas notable)

    last_analysis_ts: float = 0.0         # timestamp de la dernière analyse vision
    analysis_pending: bool = False        # évite les analyses parallèles sur le même device
    last_notify_ts: float = 0.0           # timestamp de la dernière interruption émise


@dataclass
class CameraObservation:
    """Résultat d'une analyse vision."""
    description: str
    notable: bool
    reason: str = ""


@dataclass
class CameraSettings:
    """Les réglages d'un tour de boucle, lus en une fois.

    Relus à chaque tour plutôt que mémorisés au démarrage : tous les réglages
    sont marqués « à chaud » dans le tableau de bord, ce qui doit vouloir dire
    quelque chose.
    """
    proactive_enabled: bool = True
    analysis_interval: int = MIN_ANALYSIS_INTERVAL
    idle_pause: int = IDLE_PAUSE_S
    notify_enabled: bool = True
    notify_cooldown: int = NOTIFY_COOLDOWN_S
    see_min_interval: int = SEE_MIN_INTERVAL_S


class CameraModule(BaseModule):
    """Pipeline de perception visuelle proactive multi-device."""

    CRON_INTERVAL = 10  # tick toutes les 10s pour la détection de changement

    def __init__(self):
        super().__init__("camera")
        self._devices: dict[str, DeviceState] = {}

    # ── Lifecycle ──────────────────────────────────────────────────

    async def instantiate(self) -> None:
        self.logger.info("CameraModule prêt — ws/camera?device=<id>&label=<nom>")

    async def shutdown(self) -> None:
        self._devices.clear()

    def config_schema(self):
        from modules.plugins.camera.config_schema import CONFIG_SCHEMA
        return CONFIG_SCHEMA

    def get_panels(self) -> list:
        from modules.plugins.camera.panels import get_panels
        return get_panels()

    # ── Réglages ───────────────────────────────────────────────────

    async def _settings(self) -> CameraSettings:
        from asgiref.sync import sync_to_async
        return await sync_to_async(self._settings_sync)()

    @staticmethod
    def _settings_sync() -> CameraSettings:
        """Lecture groupée. Passe par l'ORM, donc jamais depuis une coroutine.

        ``config_service.get`` avale l'erreur d'accès synchrone à l'ORM et
        retombe silencieusement sur le défaut du schéma : appelé directement
        depuis le cron asynchrone, il rendrait donc la valeur d'usine en
        ignorant ce que l'utilisateur a réglé. D'où le passage obligé par
        ``sync_to_async``.
        """
        from configs.service import config_service

        def lire(key, default):
            try:
                value = config_service.get(key, default=default)
            except Exception:
                return default
            return default if value is None else value

        return CameraSettings(
            proactive_enabled=bool(lire("camera.proactive_enabled", True)),
            analysis_interval=int(lire("camera.analysis_interval_s", MIN_ANALYSIS_INTERVAL)),
            idle_pause=int(lire("camera.idle_pause_s", IDLE_PAUSE_S)),
            notify_enabled=bool(lire("camera.notify_enabled", True)),
            notify_cooldown=int(lire("camera.notify_cooldown_s", NOTIFY_COOLDOWN_S)),
            see_min_interval=int(lire("camera.see_min_interval_s", SEE_MIN_INTERVAL_S)),
        )

    # ── Public API (appelée par CameraConsumer) ────────────────────

    async def register_frame(
        self,
        device_id: str,
        label: str,
        data: str,
        mime: str = "image/jpeg",
    ) -> bool:
        """Enregistre une frame. Retourne True si la frame a changé.

        Le hash perceptuel décode l'image : il part dans un thread, sinon il
        s'exécute sur l'unique boucle d'événements du processus, appelé depuis
        `receive()` du socket caméra. Même arbitrage que les écritures disque de
        pipeline/media.py — quelques dizaines de millisecondes par frame gèlent
        tout le trafic WS (donc le keepalive), la TurnQueue, l'ordonnancement
        des `sync_to_async` et les six boucles de fond.
        """
        new_hash = await asyncio.to_thread(_perceptual_hash, data)

        existing = self._devices.get(device_id)
        if existing:
            changed = existing.frame_hash != new_hash
            existing.frame_data = data
            existing.frame_mime = mime
            existing.frame_ts = time.time()
            existing.frame_hash = new_hash
            # FIX #3 : marquer uniquement si la frame a réellement changé
            if changed:
                existing.frame_changed_since_analysis = True
            return changed

        self._devices[device_id] = DeviceState(
            device_id=device_id,
            label=label,
            frame_data=data,
            frame_mime=mime,
            frame_ts=time.time(),
            frame_hash=new_hash,
            frame_changed_since_analysis=True,
        )
        self.logger.info("Nouveau device caméra enregistré : %s (%s)", device_id, label)
        return True

    # ── Cron — détection de changement + déclenchement analyse ────

    async def worker_cron(self) -> None:
        now = time.time()

        # FIX #7 : nettoyage des devices inactifs
        stale = [d for d, s in self._devices.items() if now - s.frame_ts > DEVICE_STALE_TIMEOUT]
        for device_id in stale:
            del self._devices[device_id]
            self.logger.info("Device caméra supprimé (inactif) : %s", device_id)

        # Rien à regarder : pas la peine de payer une lecture de configuration
        # toutes les 10 s pour un module enregistré sur toutes les installations.
        if not self._devices:
            return

        conf = await self._settings()
        if not conf.proactive_enabled:
            return
        if not self._analysis_allowed(conf):
            return

        for device_id, state in list(self._devices.items()):
            # Ne pas analyser une frame trop ancienne (device en pause)
            if now - state.frame_ts > MAX_FRAME_AGE_FOR_ANALYSIS:
                continue
            # FIX #3 : analyser seulement si la frame a changé depuis la dernière analyse
            if not state.frame_changed_since_analysis:
                continue
            # Respecter l'intervalle minimum entre analyses
            if now - state.last_analysis_ts < conf.analysis_interval:
                continue
            # Pas d'analyse parallèle sur le même device
            if state.analysis_pending:
                continue

            state.analysis_pending = True
            asyncio.create_task(self._analyze_device(device_id, conf))

    def _analysis_allowed(self, conf: CameraSettings) -> bool:
        """L'analyse de fond a-t-elle une raison de tourner maintenant ?

        Deux gardes du même ordre que celles du cycle de sommeil et de la
        conscience, que la boucle ignorait : elle analysait à l'identique
        pendant que Mika dormait et pendant les heures où personne ne lui
        parlait. Or une observation expire au bout de MAX_OBSERVATION_AGE ;
        produite après une heure de silence, elle est jetée sans qu'aucune
        invite ne l'ait jamais lue — un appel vision par frame, pour rien.

        Les deux gardes s'appliquent à l'analyse *de fond* seulement :
        ``camera_see`` regarde quand on le lui demande, y compris la nuit.

        Une lecture qui échoue n'interrompt pas la perception : c'est le
        garde-fou qui est indisponible, pas la caméra.
        """
        try:
            from memory.sleep import SleepPhase, sleep_cycle
            if sleep_cycle.phase != SleepPhase.AWAKE:
                return False
        except Exception as exc:
            degradations.record("camera: lecture de la phase de sommeil", exc)

        # 0 : garde désactivée — une caméra de surveillance regarde une pièce
        # vide, c'est un choix qui se règle et qui se paie.
        if conf.idle_pause <= 0:
            return True
        try:
            from conscience.engine import conscience_engine
            return conscience_engine.get_idle_seconds() < conf.idle_pause
        except Exception as exc:
            degradations.record("camera: lecture du temps d'inactivité", exc)
        return True

    # ── Pipeline d'analyse vision ──────────────────────────────────

    async def _analyze_device(self, device_id: str, conf: CameraSettings) -> None:
        state = self._devices.get(device_id)
        if not state:
            return

        # FIX #6 : snapshot de la frame avant tout await
        frame_data = state.frame_data
        frame_mime = state.frame_mime

        try:
            obs = await self._run_vision(state, frame_data, frame_mime)
            state.observation = obs.description
            state.observation_ts = time.time()
            state.notable_reason = obs.reason if obs.notable else ""
            state.last_analysis_ts = time.time()
            # FIX #3 : réinitialiser le flag après analyse
            state.frame_changed_since_analysis = False

            self.logger.info(
                "[%s/%s] Observation : %s%s",
                state.device_id, state.label,
                obs.description[:80],
                f" — NOTABLE: {obs.reason}" if obs.notable else "",
            )

            if obs.notable:
                await self._maybe_notify(state, obs, conf)

        except Exception:
            self.logger.exception("Analyse vision échouée pour device %s", device_id)
        finally:
            if device_id in self._devices:
                self._devices[device_id].analysis_pending = False

    async def _maybe_notify(
        self,
        state: DeviceState,
        obs: CameraObservation,
        conf: CameraSettings,
    ) -> None:
        """Interrompt Mika, si le droit et le délai de garde le permettent.

        Une interruption est un tour de pipeline complet — invite système,
        déclaration de tous les outils, historique, persistance, impulsion
        émotionnelle, extraction mémoire en aval. Or le modèle vision juge
        « notable » un simple changement d'attitude : sur une webcam pointée
        vers quelqu'un qui travaille, le critère se déclenchait plusieurs fois
        par minute. Même borne que la Forge (``forge.notify_cooldown_s``),
        appliquée par device.

        L'observation, elle, reste enregistrée dans tous les cas : se taire
        n'est pas oublier, et ``get_context()`` la portera au prochain tour.
        """
        if not conf.notify_enabled or not self._notify_ai:
            return

        now = time.time()
        if conf.notify_cooldown > 0 and now - state.last_notify_ts < conf.notify_cooldown:
            self.logger.debug(
                "[%s] Interruption supprimée (délai de garde, %ds restants)",
                state.device_id,
                int(conf.notify_cooldown - (now - state.last_notify_ts)),
            )
            return

        # Daté avant l'appel : un tour lent ne doit pas laisser passer un
        # second déclenchement pendant qu'il se déroule.
        state.last_notify_ts = now
        await self._notify_ai(ModuleNotification(
            source_module="camera",
            summary=f"Changement notable détecté sur la caméra '{state.label}'",
            details=(
                f"Device: {state.label} ({state.device_id})\n"
                f"Observation: {obs.description}\n"
                f"Raison: {obs.reason}"
            ),
            urgency="normal",
            suggested_action="Réagis naturellement si pertinent pour la conversation.",
        ))

    async def _run_vision(
        self,
        state: DeviceState,
        frame_data: str,   # FIX #6 : snapshot passé explicitement, pas lu depuis state
        frame_mime: str,
    ) -> CameraObservation:
        from ai.client import ai_client
        from ai.router import AIRole
        from pipeline.media import MediaAttachment

        att = MediaAttachment(
            name=f"camera_{state.device_id}.jpg",
            media_type=frame_mime,
            data=frame_data,
            category="image",
        )

        previous = f'\nObservation précédente : "{state.observation}"' if state.observation else ""

        system_prompt = (
            "Tu es un système de perception visuelle pour un assistant IA personnel. "
            "Analyse cette image de webcam et retourne un JSON strict (aucun texte autour) :\n"
            '{"description": "...", "notable": true/false, "reason": "..."}\n\n'
            "- description : ce que tu vois en 1-2 phrases naturelles en français\n"
            "- notable : true si changement significatif vs observation précédente, "
            "nouvelle personne, changement d'état émotionnel fort, événement inhabituel\n"
            "- reason : explication courte si notable, sinon chaîne vide"
        )

        user_prompt = (
            f"Caméra : {state.label}{previous}\n"
            "Analyse cette image."
        )

        # VISION_CAPTION, et pas SIGNAL_INTERPRETATION : ce dernier est le rôle
        # que la Conscience mappe pour interpréter du *texte* d'événement, donc
        # en pratique le modèle le moins cher déclaré, typiquement aveugle. Or
        # un modèle sans capacité vision n'échoue pas — Ollama ignore purement
        # et simplement le champ `images` — il lit l'invite système, l'ancienne
        # observation injectée dans `previous`, et rend un JSON parfaitement
        # formé décrivant une scène qu'il n'a jamais vue. `_parse_observation`
        # l'accepte, get_context() la porte dans le prompt de chaque tour et un
        # `notable` déclenche un tour de pipeline entier, sans une trace
        # d'erreur nulle part. VISION_CAPTION est le rôle que l'opérateur mappe
        # déjà sur un modèle multimodal, et le seul dont l'absence se voit
        # (UnconfiguredRoleError) au lieu de se deviner.
        raw = await ai_client.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            role=AIRole.VISION_CAPTION,
            attachments=[att],
        )

        return self._parse_observation(raw)

    @staticmethod
    def _parse_observation(raw: str) -> CameraObservation:
        """Parse la réponse JSON du modèle vision. Robuste aux artefacts."""
        try:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
                return CameraObservation(
                    description=str(data.get("description", raw.strip())),
                    notable=bool(data.get("notable", False)),
                    reason=str(data.get("reason", "")),
                )
        except json.JSONDecodeError:  # FIX #8 : KeyError impossible avec .get()
            pass
        return CameraObservation(description=raw.strip(), notable=False)

    # ── Context injection ──────────────────────────────────────────

    def get_context(self, person_id: str = "") -> str:
        now = time.time()
        lines = []
        for state in self._devices.values():
            if not state.observation:
                continue
            age = now - state.observation_ts
            if age > MAX_OBSERVATION_AGE:
                continue
            age_str = _format_age(age)
            notable_tag = f" ⚠ {state.notable_reason}" if state.notable_reason else ""
            lines.append(
                f"Caméra '{state.label}' ({age_str}) : {state.observation}{notable_tag}"
            )
        if not lines:
            return ""
        return "Observations caméra en direct :\n" + "\n".join(f"  - {l}" for l in lines)

    # ── Capabilities ───────────────────────────────────────────────

    def get_capabilities(self) -> list[ModuleCapability]:
        if not self._devices:
            return []
        return [
            ModuleCapability(
                description="Regarder une caméra spécifique pour analyser la scène en détail",
                tool_names=["camera_see"],
            )
        ]

    # ── Tools ──────────────────────────────────────────────────────

    def return_tools(self) -> list[ModuleTool]:
        return [
            ModuleTool(
                name="camera_see",
                description=(
                    "Regarde activement une caméra et répond à une question précise. "
                    "Utilise cet outil pour une attention focalisée quand get_context() "
                    "ne suffit pas (ex: 'qu\\'est-ce qu\\'il y a sur le bureau ?')."
                ),
                parameters=[
                    ToolParameter(
                        "device_id",
                        ToolParameterType.STRING,
                        "ID du device caméra (laisser vide pour le premier disponible)",
                        required=False,
                        default="",
                    ),
                    ToolParameter(
                        "question",
                        ToolParameterType.STRING,
                        "Question précise sur l'image",
                        required=False,
                        default="",
                    ),
                ],
                handler=self._handle_see,
            ),
            ModuleTool(
                name="camera_list_devices",
                description="Liste les caméras actives et leurs dernières observations.",
                parameters=[],
                handler=self._handle_list_devices,
            ),
        ]

    async def _handle_see(self, params: dict) -> dict:
        device_id = params.get("device_id", "").strip()
        state = self._get_device(device_id)
        if not state:
            available = list(self._devices.keys())
            return {"error": "Aucune caméra disponible.", "available": available}

        now = time.time()
        age = now - state.frame_ts
        if age > MAX_FRAME_AGE_FOR_ANALYSIS:
            return {"error": f"La frame de '{state.label}' est trop ancienne ({int(age)}s)."}

        # Un regard demandé n'était borné que par « pas deux analyses en
        # parallèle » : rien n'empêchait le modèle d'enchaîner les appels
        # vision dans une même boucle d'outils. Le plancher est bien plus
        # court que l'intervalle de l'analyse de fond — regarder parce qu'on
        # le lui demande vaut plus qu'un balayage périodique — mais il existe.
        conf = await self._settings()
        depuis = now - state.last_analysis_ts
        if conf.see_min_interval > 0 and depuis < conf.see_min_interval:
            refus = {
                "error": (
                    f"'{state.label}' vient d'être analysée il y a {int(depuis)}s. "
                    f"Réessaie dans {int(conf.see_min_interval - depuis) + 1}s."
                ),
            }
            # La dernière description reste utile : elle date de quelques
            # secondes et évite un « je ne peux pas regarder » stérile.
            if state.observation:
                refus["derniere_observation"] = state.observation
            return refus

        # FIX #4 : protéger contre l'analyse parallèle avec _analyze_device
        if state.analysis_pending:
            return {"error": "Analyse déjà en cours sur ce device, réessaie dans un instant."}
        state.analysis_pending = True

        # FIX #6 : snapshot avant l'await
        frame_data = state.frame_data
        frame_mime = state.frame_mime

        try:
            obs = await self._run_vision(state, frame_data, frame_mime)
        finally:
            state.analysis_pending = False

        state.observation = obs.description
        state.observation_ts = time.time()
        state.notable_reason = obs.reason if obs.notable else ""
        state.last_analysis_ts = time.time()
        state.frame_changed_since_analysis = False

        return {
            "device": state.label,
            "description": obs.description,
            "notable": obs.notable,
            "reason": obs.reason,
        }

    async def _handle_list_devices(self, _params: dict) -> dict:
        now = time.time()
        # FIX #11 : filtrer les devices inactifs
        devices = []
        for state in self._devices.values():
            frame_age = int(now - state.frame_ts)
            if frame_age > MAX_FRAME_AGE_FOR_ANALYSIS:
                continue  # device déconnecté, ne pas polluer la liste
            devices.append({
                "device_id": state.device_id,
                "label": state.label,
                "frame_age_s": frame_age,
                "observation": state.observation or "(pas encore analysé)",
                # FIX #9 : comparaison explicite plutôt que truthy sur 0.0
                "observation_age_s": int(now - state.observation_ts) if state.observation_ts > 0 else None,
            })
        return {"devices": devices, "count": len(devices)}

    # ── Helpers ────────────────────────────────────────────────────

    def _get_device(self, device_id: str) -> DeviceState | None:
        if device_id and device_id in self._devices:
            return self._devices[device_id]
        now = time.time()
        for state in self._devices.values():
            if now - state.frame_ts <= MAX_FRAME_AGE_FOR_ANALYSIS:
                return state
        return None


def _perceptual_hash(b64_data: str) -> str:
    """Hash perceptuel insensible au bruit capteur.

    Algorithme :
      1. Décode la frame base64
      2. draft() demande à libjpeg de décoder au 1/8 de résolution : la cible
         étant 16×16, charger un 1080p en pleine résolution coûtait 20 à 40 ms
         de CPU pour rien. Sans effet sur la stabilité du hash, et no-op sur
         les formats qui ne savent pas décoder à l'échelle (PNG…).
      3. Resize à 16×16 px en niveaux de gris (LANCZOS — moyennage, lisse le bruit)
      4. Quantifie chaque pixel au multiple de 16 le plus proche
         → absorbe les variations d'exposition/balance des blancs (±8 niveaux)
      5. MD5 des 256 bytes quantifiés

    Résultat : stable pour une scène statique même avec bruit capteur,
    mais change significativement si quelqu'un bouge ou entre dans le champ.
    """
    from PIL import Image

    raw = base64.b64decode(b64_data + "==")
    img = Image.open(io.BytesIO(raw))
    img.draft("L", (_THUMB_SIZE, _THUMB_SIZE))
    img = img.convert("L").resize((_THUMB_SIZE, _THUMB_SIZE), Image.LANCZOS)
    quantized = bytes((p // _QUANTIZE_STEP) * _QUANTIZE_STEP for p in img.tobytes())
    return hashlib.md5(quantized).hexdigest()


def _format_age(seconds: float) -> str:
    if seconds < 60:
        return f"il y a {int(seconds)}s"
    if seconds < 3600:
        return f"il y a {int(seconds // 60)}min"
    return f"il y a {int(seconds // 3600)}h"
