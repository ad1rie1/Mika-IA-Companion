"""WebSocket channel — flux caméra dédié.

Connexion : ws://host/ws/camera?device=bureau&label=Bureau&token=...
  - device : identifiant technique unique du device (requis)
  - label  : nom lisible pour le contexte IA (optionnel, défaut = device)
  - token  : jeton de device (requis dès que ``camera.device_token`` est réglé)

Admission — même politique que le consumer principal, par un autre moyen. Une
frame n'est pas un flux passif : le modèle vision la transcrit, la description
entre dans ``--- CONTEXTE MODULES ---`` à chaque tour pendant dix minutes
(``MAX_OBSERVATION_AGE``), et une observation notable ouvre un tour de pipeline
complet. Qui ouvre cette socket écrit donc dans l'invite système et dépense des
tokens ; une image contenant du texte en fait un vecteur d'injection direct.
``OriginValidator`` ne suffit pas — un en-tête ``Origin`` se falsifie hors
navigateur, et ``API_HOST=0.0.0.0`` est un mode supporté.

Deux voies d'admission, parce qu'un device caméra n'a pas de session Django :
une session authentifiée (une page du frontend qui pousse sa webcam), ou le
jeton ``camera.device_token`` comparé au paramètre ``token``. Sans l'une des
deux, la connexion est refusée quand ``CONSUMER_REQUIRE_AUTH`` est actif —
et acceptée sinon, explicitement et en le disant dans le journal.

Protocole (frames JSON) :
  Client → Serveur :
    {"type": "frame", "data": "<base64>", "mime": "image/jpeg"}

  Serveur → Client :
    {"type": "ack", "changed": true/false}
    {"type": "ack", "changed": false, "status": "rate_limited"}
    {"type": "error", "message": "..."}

Les frames binaires brutes (JPEG bytes) sont aussi acceptées.
"""

import base64
import hmac
import json
import logging
import time
from urllib.parse import parse_qs  # FIX #10 : URL-decoding correct

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

logger = logging.getLogger(__name__)

MAX_FRAME_B64_LEN = 2 * 1024 * 1024    # ~1.5 MB image
MAX_FRAME_BYTES_LEN = 1536 * 1024

# Fenêtre glissante par connexion, même forme que WebSocketConsumer. Une frame
# n'est jamais gratuite (décodage image pour le hash perceptuel) et rien ne
# bornait ce qu'un device pouvait pousser. 2 frames/s est déjà large : le
# module n'analyse au mieux qu'une frame toutes les MIN_ANALYSIS_INTERVAL (30 s).
RATE_LIMIT_MAX_FRAMES = 20
RATE_LIMIT_WINDOW_SECONDS = 10.0


class CameraConsumer(AsyncWebsocketConsumer):
    """Consumer WebSocket dédié au flux caméra."""

    # Défaut immuable : _is_rate_limited() le rebinde sur une liste d'instance.
    _frame_timestamps: tuple[float, ...] | list[float] = ()

    async def connect(self):
        self._frame_timestamps: list[float] = []

        # FIX #10 : parse_qs gère le URL-decoding (label=Mon%20Bureau → "Mon Bureau")
        query = self.scope.get("query_string", b"").decode()
        params = {k: v[0] for k, v in parse_qs(query).items()}

        self.device_id = params.get("device", "").strip()
        self.label = params.get("label", self.device_id).strip()

        # FIX #1 : accept() en premier, puis close() si invalide
        # Ne pas appeler close() avant accept() — le handshake HTTP n'est pas terminé
        if not self.device_id:
            logger.warning("CameraConsumer: connexion rejetée — paramètre 'device' manquant")
            await self.accept()
            await self.close(code=4000)
            return

        if not await self._is_authorized(params.get("token", "")):
            logger.warning(
                "CameraConsumer: connexion refusée (device='%s') — ni session "
                "authentifiée ni jeton valide. Réglez 'Jeton des devices "
                "caméra' dans Configuration → Modules · Caméra.",
                self.device_id,
            )
            # Le device_id est effacé avant le refus : receive() s'en sert
            # comme garde (FIX #2), et une frame peut arriver entre l'accept
            # et le close.
            self.device_id = ""
            await self.accept()
            await self.close(code=4401)
            return

        await self.accept()
        logger.info(
            "CameraConsumer: device='%s' label='%s' connecté",
            self.device_id, self.label,
        )

    async def disconnect(self, close_code):
        logger.info(
            "CameraConsumer: device='%s' déconnecté (code=%s)",
            getattr(self, "device_id", "?"), close_code,
        )

    async def receive(self, text_data=None, bytes_data=None):
        # FIX #2 : guard si connect() a fermé sans accepter proprement
        if not getattr(self, "device_id", ""):
            return

        if text_data is not None:
            await self._handle_text(text_data)
        elif bytes_data is not None:
            await self._handle_binary(bytes_data)

    # ── Handlers ──────────────────────────────────────────────────

    async def _handle_text(self, text_data: str) -> None:
        try:
            data = json.loads(text_data)
        except (json.JSONDecodeError, TypeError):
            await self._send_error("Message JSON invalide.")
            return

        if data.get("type") != "frame":
            return

        frame_b64 = data.get("data", "")
        mime = data.get("mime", "image/jpeg")

        if not isinstance(frame_b64, str) or not frame_b64:
            await self._send_error("Champ 'data' manquant ou vide.")
            return

        if len(frame_b64) > MAX_FRAME_B64_LEN:
            await self._send_error("Frame trop volumineuse (max ~1.5 MB).")
            return

        if self._is_rate_limited():
            await self.send(json.dumps({
                "type": "ack", "changed": False, "status": "rate_limited",
            }))
            return

        changed = await self._push_frame(frame_b64, mime)
        await self.send(json.dumps({"type": "ack", "changed": changed}))

    async def _handle_binary(self, bytes_data: bytes) -> None:
        if len(bytes_data) > MAX_FRAME_BYTES_LEN:
            return
        # Chemin binaire : aucun ack n'est prévu, un refus n'a rien à répondre.
        if self._is_rate_limited():
            return
        frame_b64 = base64.b64encode(bytes_data).decode()
        await self._push_frame(frame_b64, "image/jpeg")

    # ── Admission ─────────────────────────────────────────────────

    async def _is_authorized(self, token: str) -> bool:
        """Une session authentifiée, ou le jeton de device, ou la politique."""
        user = self.scope.get("user")
        if user is not None and getattr(user, "is_authenticated", False):
            return True

        expected = await sync_to_async(self._device_token)()
        if expected:
            # compare_digest : la comparaison ne doit rien dire sur le préfixe
            # commun d'un jeton essayé au hasard. Encodé des deux côtés — sur
            # deux str, compare_digest lève dès qu'un caractère sort de l'ASCII,
            # et le jeton essayé vient de l'extérieur.
            return hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))

        # Aucun jeton réglé : c'est la politique globale qui tranche, comme
        # pour le consumer principal. Ouvert, mais plus jamais implicitement.
        return not getattr(settings, "CONSUMER_REQUIRE_AUTH", False)

    @staticmethod
    def _device_token() -> str:
        """Lecture du jeton — passe par l'ORM, donc jamais depuis la coroutine.

        ``config_service.get`` avale l'erreur d'accès synchrone à l'ORM et
        retomberait sur le défaut vide, c'est-à-dire sur « pas de jeton
        réglé » : appelée directement, cette lecture désarmerait le contrôle
        qu'elle sert. Même raison que ``CameraModule._settings_sync``.
        """
        from configs.service import config_service

        try:
            value = config_service.get("camera.device_token", default="")
        except Exception:
            # Une configuration illisible ne vaut pas une autorisation.
            logger.debug("CameraConsumer: jeton de device illisible", exc_info=True)
            return ""
        return (value or "").strip()

    # ── Helpers ───────────────────────────────────────────────────

    async def _push_frame(self, data: str, mime: str) -> bool:
        """Transmet la frame au CameraModule. Retourne True si la frame a changé."""
        try:
            from modules.manager import module_manager
            cam = module_manager.get_module("camera")
            if cam is not None:
                return await cam.register_frame(self.device_id, self.label, data, mime)
        except Exception:
            logger.exception(
                "CameraConsumer: erreur lors de l'enregistrement de la frame (device=%s)",
                self.device_id,
            )
        return False

    def _is_rate_limited(self) -> bool:
        """Fenêtre glissante : borne le nombre de frames par connexion."""
        now = time.monotonic()
        window_start = now - RATE_LIMIT_WINDOW_SECONDS
        self._frame_timestamps = [
            t for t in self._frame_timestamps if t >= window_start
        ]
        if len(self._frame_timestamps) >= RATE_LIMIT_MAX_FRAMES:
            # debug et non warning : un device mal réglé dépasse à chaque frame,
            # et le refus est déjà dit au client dans l'ack.
            logger.debug(
                "CameraConsumer: debit trop eleve (device=%s) — frame ignoree",
                getattr(self, "device_id", "?"),
            )
            return True
        self._frame_timestamps.append(now)
        return False

    async def _send_error(self, message: str) -> None:
        await self.send(json.dumps({"type": "error", "message": message}))
