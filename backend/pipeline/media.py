"""Media attachment processing — validation, sauvegarde disque + BDD.

Flux :
  1. validate_attachments(raw_list)  → (retenues, écartées)      (parse + garde-fous)
  2. save_attachments(validated, person_id)  → list[UploadedFile]  (disque + BDD + module)

Catégories :
  image   → vision IA (préprocesseur vision + files_analyze_image)
  audio   → transcription Whisper (préprocesseur audio + files_transcribe)
  text    → lecture (préprocesseur files + files_read)
  unknown → extraction tentée par le préprocesseur files (pdf/docx), sinon brut
"""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_AUDIO_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg",
    "audio/webm", "audio/mp4", "audio/x-wav",
}
ALLOWED_TEXT_TYPES = {
    "text/plain", "text/csv", "text/markdown", "text/html",
    "application/json", "application/xml",
}

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 Mo décodé
MAX_ATTACHMENTS = 5

# Le nom d'un fichier est fourni par l'émetteur (payload WebSocket,
# `file_name` Telegram) et finit dans le prompt système du propriétaire via
# files_service.list_today_context(). Multi-ligne et sans plafond, il s'y lit
# comme une consigne. On le ramène donc à une ligne unique et bornée avant
# toute persistance — même convention que MAX_CAPTION_CHARS côté vision.
# Le max_length=255 du modèle ne protège pas : SQLite n'applique pas les
# longueurs de varchar et objects.create() ne passe pas par full_clean().
MAX_FILENAME_CHARS = 80


@dataclass
class MediaAttachment:
    """Pièce jointe validée en mémoire (transitoire — avant sauvegarde disque)."""
    name: str
    media_type: str
    data: str       # base64, sans préfixe data-URI
    category: str   # image | audio | text | unknown

    @classmethod
    def from_ws_dict(cls, raw: dict) -> "MediaAttachment":
        name = str(raw.get("name", "fichier"))
        media_type = str(raw.get("type", "application/octet-stream")).lower().split(";")[0].strip()
        data = str(raw.get("data", ""))
        if "," in data:
            data = data.split(",", 1)[1]
        return cls(name=name, media_type=media_type, data=data, category=_categorize(media_type))

    def decoded_bytes(self) -> bytes:
        padding = 4 - len(self.data) % 4
        return base64.b64decode(self.data + "=" * (padding % 4))

    def size_bytes(self) -> int:
        return len(self.data) * 3 // 4


@dataclass
class RejectedAttachment:
    """Pièce jointe écartée à la validation — nom + raison, pour l'accusé.

    La validation ne retournait que les survivants : au-delà de
    MAX_ATTACHMENTS ou de MAX_FILE_SIZE_BYTES, un fichier disparaissait dans
    un `logger.warning` et n'existait plus nulle part — ni dans
    `attachments_meta`, ni dans l'historique, ni dans l'accusé. L'expéditeur
    recevait `accepted` pour un envoi partiel et croyait avoir transmis ce
    que Mika n'a jamais vu. C'est la même divergence que le message tronqué
    en silence, refusée au même titre.
    """
    name: str
    reason: str  # too_many | too_large | invalid


def _categorize(media_type: str) -> str:
    if media_type in ALLOWED_IMAGE_TYPES:
        return "image"
    if media_type in ALLOWED_AUDIO_TYPES:
        return "audio"
    if media_type in ALLOWED_TEXT_TYPES or media_type.startswith("text/"):
        return "text"
    return "unknown"


def sanitize_filename(raw: str) -> str:
    """Ramène un nom de fichier tiers à une ligne unique, imprimable et bornée.

    Les caractères de contrôle (dont les sauts de ligne) et les marques de
    direction Unicode deviennent des espaces, les blancs consécutifs sont
    fusionnés, et le résultat est tronqué à MAX_FILENAME_CHARS.
    """
    name = "".join(c if c.isprintable() else " " for c in str(raw))
    name = " ".join(name.split())
    if len(name) > MAX_FILENAME_CHARS:
        name = name[: MAX_FILENAME_CHARS - 3].rstrip() + "..."
    return name or "fichier"


def _ext_for(media_type: str, original_name: str) -> str:
    """Déduit l'extension à partir du MIME type ou du nom de fichier original."""
    ext_map = {
        "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp",
        "audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
        "audio/ogg": ".ogg", "audio/webm": ".webm", "audio/mp4": ".m4a",
        "text/plain": ".txt", "text/csv": ".csv", "text/markdown": ".md",
        "application/json": ".json", "application/xml": ".xml",
    }
    if media_type in ext_map:
        return ext_map[media_type]
    # Fallback: use original extension
    suffix = Path(original_name).suffix
    return suffix if suffix else ".bin"


def _raw_name(raw) -> str:
    """Nom déclaré par l'émetteur, assaini — il repart dans l'accusé."""
    declared = raw.get("name", "fichier") if isinstance(raw, dict) else "fichier"
    return sanitize_filename(declared)


def validate_attachments(
    raw_list: list,
) -> tuple[list[MediaAttachment], list[RejectedAttachment]]:
    """Parse et valide les pièces jointes du message WebSocket.

    Retourne (retenues, écartées). Les écartées sont nommées et non
    seulement journalisées : c'est la seule chose qui permet au canal de
    dire à l'expéditeur ce qui n'est pas passé (cf. RejectedAttachment).
    """
    if not raw_list or not isinstance(raw_list, list):
        return [], []
    result: list[MediaAttachment] = []
    rejected: list[RejectedAttachment] = []
    for raw in raw_list[:MAX_ATTACHMENTS]:
        if not isinstance(raw, dict):
            rejected.append(RejectedAttachment(name="fichier", reason="invalid"))
            continue
        try:
            att = MediaAttachment.from_ws_dict(raw)
            if att.size_bytes() > MAX_FILE_SIZE_BYTES:
                logger.warning("Pièce jointe ignorée (trop grande) : %s (%d o)", att.name, att.size_bytes())
                rejected.append(
                    RejectedAttachment(name=sanitize_filename(att.name), reason="too_large")
                )
                continue
            result.append(att)
        except Exception:
            logger.warning("Pièce jointe invalide ignorée", exc_info=True)
            rejected.append(RejectedAttachment(name=_raw_name(raw), reason="invalid"))
    # Le surplus au-delà du plafond : `raw_list[:MAX_ATTACHMENTS]` le coupait
    # sans que personne ne l'apprenne.
    for raw in raw_list[MAX_ATTACHMENTS:]:
        rejected.append(RejectedAttachment(name=_raw_name(raw), reason="too_many"))
    return result, rejected


async def save_attachments(
    attachments: list[MediaAttachment],
    person_id: str = "anonymous",
) -> list:
    """Sauvegarde les pièces jointes sur disque et en BDD.

    Enregistre également chaque fichier dans le FilesModule (mémoire).
    Retourne la liste des objets UploadedFile créés.
    """
    if not attachments:
        return []

    from django.conf import settings
    from asgiref.sync import sync_to_async

    uploads_root = Path(settings.PROJECT_ROOT) / "uploads"
    await asyncio.to_thread(uploads_root.mkdir, parents=True, exist_ok=True)

    saved = []
    for att in attachments:
        # Assaini ici, au point de convergence de tous les canaux : c'est ce
        # nom-là qui est persisté puis injecté dans le prompt système.
        safe_name = sanitize_filename(att.name)
        file_uuid = uuid.uuid4()
        ext = _ext_for(att.media_type, safe_name)
        disk_path = uploads_root / f"{file_uuid}{ext}"
        data_bytes = att.decoded_bytes()

        try:
            # 1. Écriture disque — hors de la boucle: jusqu'à 5 Mo × 5 pièces
            # jointes, et une écriture synchrone ici gèlerait tout le trafic
            # WebSocket ainsi que chaque boucle de fond pendant l'upload.
            await asyncio.to_thread(disk_path.write_bytes, data_bytes)

            # 2. Enregistrement BDD — si ça échoue, nettoyer le fichier
            try:
                db_record = await sync_to_async(_create_db_record)(
                    file_id=file_uuid,
                    original_name=safe_name,
                    media_type=att.media_type,
                    category=att.category,
                    file_size=len(data_bytes),
                    disk_path=str(disk_path),
                    person_id=person_id,
                )
            except Exception:
                disk_path.unlink(missing_ok=True)  # évite les orphelins disque
                raise

            # 3. Mémoire module
            _register_in_module(db_record)
            saved.append(db_record)
            logger.info("Fichier sauvegardé : %s → %s (id=%s)", safe_name, disk_path.name, file_uuid)

        except Exception:
            logger.exception("Erreur lors de la sauvegarde de %s", safe_name)

    return saved


def _create_db_record(
    file_id, original_name, media_type, category, file_size, disk_path, person_id
):
    from files.models import UploadedFile
    return UploadedFile.objects.create(
        file_id=file_id,
        original_name=original_name,
        media_type=media_type,
        category=category,
        file_size=file_size,
        disk_path=disk_path,
        person_id=person_id,
    )


def _register_in_module(db_obj) -> None:
    """Publish the new file to the core files service's in-memory index."""
    try:
        from files.service import files_service
        files_service.register_file({
            "id": str(db_obj.file_id),
            "name": db_obj.original_name,
            "type": db_obj.media_type,
            "category": db_obj.category,
            "size_label": db_obj.size_label,
            "path": db_obj.disk_path,
            "person_id": db_obj.person_id,
            "uploaded_at": db_obj.uploaded_at_local_iso,
            "deleted": False,
        })
    except Exception:
        logger.warning("Impossible d'enregistrer le fichier auprès du service files", exc_info=True)
