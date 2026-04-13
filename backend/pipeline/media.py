"""Media attachment processing — validation, sauvegarde disque + BDD.

Flux :
  1. validate_attachments(raw_list)  → list[MediaAttachment]   (parse + garde-fous)
  2. save_attachments(validated, person_id)  → list[UploadedFile]  (disque + BDD + module)

Catégories :
  image   → vision IA via files_analyze_image
  audio   → transcription Whisper via files_transcribe (TODO)
  text    → lecture via files_read
  unknown → fichier brut disponible
"""

from __future__ import annotations

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


def _categorize(media_type: str) -> str:
    if media_type in ALLOWED_IMAGE_TYPES:
        return "image"
    if media_type in ALLOWED_AUDIO_TYPES:
        return "audio"
    if media_type in ALLOWED_TEXT_TYPES or media_type.startswith("text/"):
        return "text"
    return "unknown"


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


def validate_attachments(raw_list: list) -> list[MediaAttachment]:
    """Parse et valide les pièces jointes du message WebSocket."""
    if not raw_list or not isinstance(raw_list, list):
        return []
    result = []
    for raw in raw_list[:MAX_ATTACHMENTS]:
        if not isinstance(raw, dict):
            continue
        try:
            att = MediaAttachment.from_ws_dict(raw)
            if att.size_bytes() > MAX_FILE_SIZE_BYTES:
                logger.warning("Pièce jointe ignorée (trop grande) : %s (%d o)", att.name, att.size_bytes())
                continue
            result.append(att)
        except Exception:
            logger.warning("Pièce jointe invalide ignorée", exc_info=True)
    return result


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
    uploads_root.mkdir(parents=True, exist_ok=True)

    saved = []
    for att in attachments:
        try:
            file_uuid = uuid.uuid4()
            ext = _ext_for(att.media_type, att.name)
            filename = f"{file_uuid}{ext}"
            disk_path = uploads_root / filename

            # Écriture sur disque
            data_bytes = att.decoded_bytes()
            disk_path.write_bytes(data_bytes)

            # Création enregistrement BDD
            db_record = await sync_to_async(_create_db_record)(
                file_id=file_uuid,
                original_name=att.name,
                media_type=att.media_type,
                category=att.category,
                file_size=len(data_bytes),
                disk_path=str(disk_path),
                person_id=person_id,
            )

            # Enregistrement dans le module (mémoire → get_context())
            _register_in_module(db_record)

            saved.append(db_record)
            logger.info(
                "Fichier sauvegardé : %s → %s (id=%s)",
                att.name, disk_path.name, file_uuid,
            )
        except Exception:
            logger.exception("Erreur lors de la sauvegarde de %s", att.name)

    return saved


def _create_db_record(
    file_id, original_name, media_type, category, file_size, disk_path, person_id
):
    from modules.files.models import UploadedFile
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
    """Enregistre le fichier dans le FilesModule en mémoire."""
    try:
        from modules.manager import module_manager
        files_module = module_manager._modules.get("files")
        if files_module is None:
            return
        files_module.register_file({
            "id": str(db_obj.file_id),
            "name": db_obj.original_name,
            "type": db_obj.media_type,
            "category": db_obj.category,
            "size_label": db_obj.size_label,
            "path": db_obj.disk_path,
            "person_id": db_obj.person_id,
            "uploaded_at": db_obj.uploaded_at.isoformat() if db_obj.uploaded_at else "",
            "deleted": False,
        })
    except Exception:
        logger.warning("Impossible d'enregistrer le fichier dans FilesModule", exc_info=True)
