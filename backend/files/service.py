"""File storage service — the core, always-on implementation.

Consumers:
  - pipeline.media calls ``files_service.register_file(...)`` right
    after persisting a user attachment.
  - FilesModule (the MCP wrapper) calls into this service for every
    tool handler.
  - Any plugin module can import ``files_service`` directly to query
    or manipulate uploaded files — no reaching into ModuleManager.

Les ``op_*`` sont la surface *outil* : elles filtrent sur la personne du
tour en cours (``pipeline.tracing.current_person_id``) et ne rendent que
ses propres fichiers, sauf pour le propriétaire. Un consommateur interne
qui doit ignorer ce filtre passe par ``get()`` / le registre, pas par un
``op_*``.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import shutil
from pathlib import Path
from typing import Any

from asgiref.sync import sync_to_async
from utils.degradation import degradations

logger = logging.getLogger(__name__)

# Plafond de rendu du nom de fichier dans le prompt système. pipeline.media
# borne déjà le nom à l'écriture ; ce plafond couvre les enregistrements
# antérieurs à cette borne (le max_length du modèle n'est pas appliqué par
# SQLite). Volontairement pas importé de pipeline.media : le rendu se défend
# seul, même si l'écriture change.
MAX_NAME_CHARS = 80


def _as_data(raw: Any) -> str:
    """Neutralise une valeur tierce destinée à une ligne du prompt système.

    Le nom vient de l'émetteur du fichier, pas du propriétaire : collé nu au
    milieu d'une ligne d'instructions, un nom multi-ligne se lit comme une
    consigne. On le ramène à une ligne unique, bornée, sans guillemet double
    pour qu'il reste enfermé dans son encadrement.
    """
    text = "".join(c if c.isprintable() else " " for c in str(raw or ""))
    text = " ".join(text.split()).replace('"', "'")
    if len(text) > MAX_NAME_CHARS:
        text = text[: MAX_NAME_CHARS - 3].rstrip() + "..."
    return text


class FilesService:
    """Singleton. All file handling lives here."""

    def __init__(self) -> None:
        # In-memory registry for synchronous get_context()
        # {str(file_id): {id, name, type, category, size_label,
        #                 path, person_id, uploaded_at, deleted}}
        self._registry: dict[str, dict] = {}
        self._loaded = False

    # ── Lifecycle ─────────────────────────────────────────────────

    async def ensure_loaded(self) -> None:
        """Make sure the on-disk uploads dir exists and the in-memory
        registry mirrors the DB. Safe to call more than once."""
        if self._loaded:
            return
        from django.conf import settings

        uploads_dir = Path(settings.PROJECT_ROOT) / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        logger.info("FilesService: uploads dir = %s", uploads_dir)

        files = await sync_to_async(self._load_from_db)()
        for f in files:
            self._register_in_memory(f)
        logger.info("FilesService: %d file(s) loaded from DB", len(files))
        self._loaded = True

    def shutdown(self) -> None:
        self._registry.clear()
        self._loaded = False

    # ── Public API ────────────────────────────────────────────────

    def register_file(self, record: dict) -> None:
        """Called by pipeline.media right after a successful save."""
        self._registry[str(record["id"])] = record

    def get(self, file_id: str) -> dict | None:
        return self._registry.get(str(file_id))

    def list_today_context(self) -> str:
        """Text block injected into the system prompt.

        Only today's uploads are listed inline; anything older is
        surfaced via the files_list tool.
        """
        from datetime import date
        today = date.today().isoformat()
        today_files = [
            r for r in self._registry.values()
            if not r.get("deleted") and r.get("uploaded_at", "").startswith(today)
        ]
        if not today_files:
            return ""
        lines = [f"Fichiers uploadés aujourd'hui ({len(today_files)}) :"]
        for r in sorted(today_files, key=lambda x: x["uploaded_at"], reverse=True):
            lines.append(
                f'  - ID={r["id"]}  nom="{_as_data(r.get("name"))}"'
                f"  type={r['category']}  taille={r['size_label']}"
            )
        lines.append(
            "Utilise les outils files_* pour lire, analyser, déplacer ou supprimer ces fichiers."
        )
        lines.append("Pour les fichiers plus anciens, utilise files_list.")
        return "\n".join(lines)

    # ── Contrôle d'accès ──────────────────────────────────────────

    def _may_access(self, record: dict) -> bool:
        """Le tour en cours a-t-il le droit de toucher ce fichier ?

        Les outils files_* sont exposés à *toutes* les conversations, alors
        que le bloc de contexte du module, lui, est réservé au propriétaire
        (``ModuleCollectors.context`` saute les modules ``CONTEXT_VISIBILITY
        == "owner"``). Sans ce filtre, un contact Telegram ou un invité web
        atteint par les outils ce que le prompt lui refuse.

        Un ``person_id`` vide (boucle de fond, tick cron) signifie « aucune
        personne en portée » : pas de propriétaire, pas de possesseur, donc
        aucun accès — jamais « accès total ».

        Un refus se dit « Fichier introuvable. », comme un ID inexistant :
        confirmer l'existence de l'ID serait déjà une fuite.
        """
        from modules.collectors import is_owner
        from pipeline.tracing import current_person_id

        person_id = current_person_id()
        if is_owner(person_id):
            return True
        if not person_id:
            return False
        return (record.get("person_id") or "") == person_id

    # ── Tool-facing operations (async) ────────────────────────────

    async def op_list(self, date_filter: str = "", category: str = "") -> dict:
        files = [
            r for r in self._registry.values()
            if not r.get("deleted") and self._may_access(r)
        ]
        if date_filter:
            files = [r for r in files if r.get("uploaded_at", "").startswith(date_filter)]
        if category:
            files = [r for r in files if r.get("category") == category]
        if not files:
            return {"files": [], "message": "Aucun fichier correspondant."}
        return {
            "files": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "type": r["type"],
                    "category": r["category"],
                    "size": r["size_label"],
                    "uploaded_at": r["uploaded_at"],
                }
                for r in sorted(files, key=lambda x: x["uploaded_at"], reverse=True)
            ],
            "total": len(files),
        }

    async def op_read(self, file_id: str) -> dict:
        record = self.get(file_id)
        if not record or not self._may_access(record):
            return {"error": "Fichier introuvable."}
        if record.get("deleted"):
            return {"error": "Fichier supprimé."}
        if record["category"] not in ("text", "unknown"):
            return {"error": f"Ce fichier est de type '{record['category']}' — non lisible comme texte."}
        try:
            def _read():
                return Path(record["path"]).read_bytes().decode("utf-8", errors="replace")
            content = await asyncio.to_thread(_read)
            if len(content) > 10_000:
                content = content[:10_000] + "\n[...tronqué]"
            return {"content": content, "name": record["name"]}
        except Exception as e:
            degradations.record("files.service.op_read", e)
            return {"error": f"Erreur de lecture : {e}"}

    async def op_analyze_image(self, file_id: str, question: str = "") -> dict:
        record = self.get(file_id)
        if not record or not self._may_access(record):
            return {"error": "Fichier introuvable."}
        if record["category"] != "image":
            return {"error": f"Ce fichier n'est pas une image (catégorie: {record['category']})."}
        try:
            def _read_img():
                return base64.b64encode(Path(record["path"]).read_bytes()).decode()
            data = await asyncio.to_thread(_read_img)

            from pipeline.media import MediaAttachment
            att = MediaAttachment(
                name=record["name"],
                media_type=record["type"],
                data=data,
                category="image",
            )

            q = question or "Décris cette image en détail."
            from ai.client import ai_client
            description = await ai_client.complete(
                system_prompt="Tu es un assistant qui analyse des images avec précision et détail.",
                user_prompt=q,
                attachments=[att],
            )
            return {"description": description, "file_id": record["id"], "name": record["name"]}
        except Exception as e:
            logger.exception("analyze_image failed for %s", record["id"])
            return {"error": f"Analyse échouée : {e}"}

    async def op_transcribe(self, file_id: str) -> dict:
        record = self.get(file_id)
        if not record or not self._may_access(record):
            return {"error": "Fichier introuvable."}
        if record["category"] != "audio":
            return {"error": f"Ce fichier n'est pas un audio (catégorie: {record['category']})."}
        try:
            from ai.router import ai_router
            try:
                # Router cache: a credential rotation evicts the instance,
                # a fresh OpenAIProvider() here would pin the old key.
                provider = ai_router.provider_by_name("openai")
            except (ValueError, ImportError) as e:
                return {"error": f"Transcription indisponible — {e}"}
            audio_bytes = await asyncio.to_thread(Path(record["path"]).read_bytes)
            text = await provider.transcribe_audio(audio_bytes, record["name"])
            return {"transcription": text, "file_id": record["id"], "name": record["name"]}
        except Exception as e:
            logger.exception("Transcription échouée pour %s", record["id"])
            return {"error": f"Transcription échouée : {e}"}

    async def op_move(self, file_id: str, destination: str) -> dict:
        record = self.get(file_id)
        if not record or not self._may_access(record):
            return {"error": "Fichier introuvable."}
        if record.get("deleted"):
            return {"error": "Fichier supprimé."}

        from django.conf import settings
        uploads_root = Path(settings.PROJECT_ROOT) / "uploads"
        destination = (destination or "").strip().lstrip("/")
        if not destination:
            return {"error": "Destination vide."}

        dest_dir = (uploads_root / destination).resolve()
        if not str(dest_dir).startswith(str(uploads_root.resolve())):
            return {"error": "Destination non autorisée (hors de uploads/)."}

        dest_dir.mkdir(parents=True, exist_ok=True)
        src_path = Path(record["path"])
        new_path = dest_dir / src_path.name

        try:
            await asyncio.to_thread(shutil.move, str(src_path), str(new_path))
            record["path"] = str(new_path)
            await sync_to_async(self._update_db_path)(record["id"], str(new_path))
            return {"success": True, "new_path": str(new_path), "file_id": record["id"]}
        except Exception as e:
            degradations.record("files.service.op_move", e)
            return {"error": f"Déplacement échoué : {e}"}

    async def op_delete(self, file_id: str) -> dict:
        record = self.get(file_id)
        if not record or not self._may_access(record):
            return {"error": "Fichier introuvable."}
        try:
            path = Path(record["path"])
            await asyncio.to_thread(lambda: path.unlink(missing_ok=True))
            await sync_to_async(self._mark_deleted_in_db)(record["id"])
            record["deleted"] = True
            return {"success": True, "file_id": record["id"], "name": record["name"]}
        except Exception as e:
            degradations.record("files.service.op_delete", e)
            return {"error": f"Suppression échouée : {e}"}

    # ── DB helpers ────────────────────────────────────────────────

    @staticmethod
    def _load_from_db():
        from files.models import UploadedFile
        return list(UploadedFile.objects.filter(is_deleted=False))

    def _register_in_memory(self, db_obj: Any) -> None:
        self._registry[str(db_obj.file_id)] = {
            "id": str(db_obj.file_id),
            "name": db_obj.original_name,
            "type": db_obj.media_type,
            "category": db_obj.category,
            "size_label": db_obj.size_label,
            "path": db_obj.disk_path,
            "person_id": db_obj.person_id,
            "uploaded_at": db_obj.uploaded_at.isoformat() if db_obj.uploaded_at else "",
            "deleted": False,
        }

    @staticmethod
    def _update_db_path(file_id: str, new_path: str) -> None:
        from files.models import UploadedFile
        UploadedFile.objects.filter(file_id=file_id).update(disk_path=new_path)

    @staticmethod
    def _mark_deleted_in_db(file_id: str) -> None:
        from files.models import UploadedFile
        UploadedFile.objects.filter(file_id=file_id).update(is_deleted=True)


files_service = FilesService()
