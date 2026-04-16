"""WebSocket channel — flux caméra dédié.

Connexion : ws://host/ws/camera?device=bureau&label=Bureau
  - device : identifiant technique unique du device (requis)
  - label  : nom lisible pour le contexte IA (optionnel, défaut = device)

Protocole (frames JSON) :
  Client → Serveur :
    {"type": "frame", "data": "<base64>", "mime": "image/jpeg"}

  Serveur → Client :
    {"type": "ack", "changed": true/false}
    {"type": "error", "message": "..."}

Les frames binaires brutes (JPEG bytes) sont aussi acceptées.
"""

import base64
import json
import logging
from urllib.parse import parse_qs  # FIX #10 : URL-decoding correct

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)

MAX_FRAME_B64_LEN = 2 * 1024 * 1024    # ~1.5 MB image
MAX_FRAME_BYTES_LEN = 1536 * 1024


class CameraConsumer(AsyncWebsocketConsumer):
    """Consumer WebSocket dédié au flux caméra."""

    async def connect(self):
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

        changed = self._push_frame(frame_b64, mime)
        await self.send(json.dumps({"type": "ack", "changed": changed}))

    async def _handle_binary(self, bytes_data: bytes) -> None:
        if len(bytes_data) > MAX_FRAME_BYTES_LEN:
            return
        frame_b64 = base64.b64encode(bytes_data).decode()
        self._push_frame(frame_b64, "image/jpeg")

    # ── Helpers ───────────────────────────────────────────────────

    def _push_frame(self, data: str, mime: str) -> bool:
        """Transmet la frame au CameraModule. Retourne True si la frame a changé."""
        try:
            from modules.manager import module_manager
            cam = module_manager.get_module("camera")
            if cam is not None:
                return cam.register_frame(self.device_id, self.label, data, mime)
        except Exception:
            logger.exception(
                "CameraConsumer: erreur lors de l'enregistrement de la frame (device=%s)",
                self.device_id,
            )
        return False

    async def _send_error(self, message: str) -> None:
        await self.send(json.dumps({"type": "error", "message": message}))
