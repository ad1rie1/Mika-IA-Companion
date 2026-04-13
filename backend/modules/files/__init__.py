"""FilesModule — gestion des fichiers uploadés.

Les fichiers sont sauvegardés sur le disque (UPLOADS_ROOT).
Les métadonnées sont stockées en BDD (UploadedFile).
Claude peut lire, analyser, déplacer et supprimer les fichiers via des outils MCP.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
from pathlib import Path

from modules.base import BaseModule
from modules.types import ModuleTool, ToolParameter, ToolParameterType

logger = logging.getLogger(__name__)


class FilesModule(BaseModule):
    """Module de gestion des fichiers uploadés par les utilisateurs."""

    def __init__(self):
        super().__init__("files")
        # In-memory registry for synchronous get_context()
        # {str(file_id): {id, name, type, category, size, path, person_id}}
        self._registry: dict[str, dict] = {}

    # ── Lifecycle ──────────────────────────────────────────────────

    async def instantiate(self) -> None:
        """Crée le dossier uploads et charge les fichiers existants en mémoire."""
        from django.conf import settings

        uploads_dir = Path(settings.PROJECT_ROOT) / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info("FilesModule: dossier uploads = %s", uploads_dir)

        # Load active files from DB into memory
        from asgiref.sync import sync_to_async
        files = await sync_to_async(self._load_from_db)()
        for f in files:
            self._register_in_memory(f)
        self.logger.info("FilesModule: %d fichier(s) chargé(s) depuis la BDD", len(files))

    async def shutdown(self) -> None:
        self._registry.clear()

    # ── Context injection ──────────────────────────────────────────

    def get_context(self) -> str:
        active = [r for r in self._registry.values() if not r.get("deleted")]
        if not active:
            return ""
        lines = [f"Fichiers disponibles sur le serveur ({len(active)}) :"]
        for r in sorted(active, key=lambda x: x["uploaded_at"], reverse=True):
            lines.append(
                f"  - ID={r['id']}  nom={r['name']}  type={r['category']}  taille={r['size_label']}"
            )
        lines.append("Utilise les outils files_* pour lire, analyser, déplacer ou supprimer ces fichiers.")
        return "\n".join(lines)

    # ── Tools ──────────────────────────────────────────────────────

    def return_tools(self) -> list[ModuleTool]:
        return [
            ModuleTool(
                name="files_list",
                description="Liste tous les fichiers disponibles sur le serveur avec leurs métadonnées.",
                parameters=[],
                handler=self._handle_list,
            ),
            ModuleTool(
                name="files_read",
                description=(
                    "Lit le contenu texte d'un fichier (text/plain, JSON, CSV…). "
                    "Ne fonctionne pas pour les images ou l'audio — utilise files_analyze_image pour les images."
                ),
                parameters=[
                    ToolParameter("file_id", ToolParameterType.STRING, "ID UUID du fichier à lire"),
                ],
                handler=self._handle_read,
            ),
            ModuleTool(
                name="files_analyze_image",
                description=(
                    "Analyse une image avec la vision IA et retourne une description détaillée."
                ),
                parameters=[
                    ToolParameter("file_id", ToolParameterType.STRING, "ID UUID de l'image"),
                    ToolParameter(
                        "question",
                        ToolParameterType.STRING,
                        "Question spécifique sur l'image (optionnel)",
                        required=False,
                        default="",
                    ),
                ],
                handler=self._handle_analyze_image,
            ),
            ModuleTool(
                name="files_move",
                description=(
                    "Déplace un fichier vers un sous-dossier de uploads/ "
                    "(ex: 'images/', 'documents/2024/'). Crée le dossier si nécessaire."
                ),
                parameters=[
                    ToolParameter("file_id", ToolParameterType.STRING, "ID UUID du fichier"),
                    ToolParameter(
                        "destination",
                        ToolParameterType.STRING,
                        "Chemin de destination relatif à uploads/ (ex: 'images/')",
                    ),
                ],
                handler=self._handle_move,
            ),
            ModuleTool(
                name="files_delete",
                description="Supprime un fichier du disque et le marque comme supprimé en BDD.",
                parameters=[
                    ToolParameter("file_id", ToolParameterType.STRING, "ID UUID du fichier"),
                ],
                handler=self._handle_delete,
            ),
        ]

    # ── Tool handlers ──────────────────────────────────────────────

    async def _handle_list(self, params: dict) -> dict:
        active = [r for r in self._registry.values() if not r.get("deleted")]
        if not active:
            return {"files": [], "message": "Aucun fichier disponible."}
        return {
            "files": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "type": r["type"],
                    "category": r["category"],
                    "size": r["size_label"],
                    "path": r["path"],
                }
                for r in sorted(active, key=lambda x: x["uploaded_at"], reverse=True)
            ]
        }

    async def _handle_read(self, params: dict) -> dict:
        record = self._get_record(params.get("file_id", ""))
        if not record:
            return {"error": "Fichier introuvable."}
        if record.get("deleted"):
            return {"error": "Fichier supprimé."}
        if record["category"] not in ("text", "unknown"):
            return {"error": f"Ce fichier est de type '{record['category']}' — non lisible comme texte."}
        try:
            with open(record["path"], "rb") as f:
                content = f.read().decode("utf-8", errors="replace")
            if len(content) > 10_000:
                content = content[:10_000] + "\n[...tronqué]"
            return {"content": content, "name": record["name"]}
        except Exception as e:
            return {"error": f"Erreur de lecture : {e}"}

    async def _handle_analyze_image(self, params: dict) -> dict:
        record = self._get_record(params.get("file_id", ""))
        if not record:
            return {"error": "Fichier introuvable."}
        if record["category"] != "image":
            return {"error": f"Ce fichier n'est pas une image (catégorie: {record['category']})."}
        try:
            with open(record["path"], "rb") as f:
                data = base64.b64encode(f.read()).decode()

            from pipeline.media import MediaAttachment
            att = MediaAttachment(
                name=record["name"],
                media_type=record["type"],
                data=data,
                category="image",
            )

            question = params.get("question") or "Décris cette image en détail."
            from ai.client import ai_client
            description = await ai_client.complete(
                system_prompt="Tu es un assistant qui analyse des images avec précision et détail.",
                user_prompt=question,
                attachments=[att],
            )
            return {"description": description, "file_id": record["id"], "name": record["name"]}
        except Exception as e:
            logger.exception("analyze_image failed for %s", record["id"])
            return {"error": f"Analyse échouée : {e}"}

    async def _handle_move(self, params: dict) -> dict:
        record = self._get_record(params.get("file_id", ""))
        if not record:
            return {"error": "Fichier introuvable."}
        if record.get("deleted"):
            return {"error": "Fichier supprimé."}

        from django.conf import settings
        uploads_root = Path(settings.PROJECT_ROOT) / "uploads"
        destination = params.get("destination", "").strip().lstrip("/")

        if not destination:
            return {"error": "Destination vide."}

        dest_dir = (uploads_root / destination).resolve()
        # Security: must stay within uploads_root
        if not str(dest_dir).startswith(str(uploads_root.resolve())):
            return {"error": "Destination non autorisée (hors de uploads/)."}

        dest_dir.mkdir(parents=True, exist_ok=True)
        src_path = Path(record["path"])
        new_path = dest_dir / src_path.name

        try:
            shutil.move(str(src_path), str(new_path))
            record["path"] = str(new_path)

            from asgiref.sync import sync_to_async
            await sync_to_async(self._update_db_path)(record["id"], str(new_path))

            return {"success": True, "new_path": str(new_path), "file_id": record["id"]}
        except Exception as e:
            return {"error": f"Déplacement échoué : {e}"}

    async def _handle_delete(self, params: dict) -> dict:
        record = self._get_record(params.get("file_id", ""))
        if not record:
            return {"error": "Fichier introuvable."}

        try:
            path = Path(record["path"])
            if path.exists():
                path.unlink()
            record["deleted"] = True

            from asgiref.sync import sync_to_async
            await sync_to_async(self._mark_deleted_in_db)(record["id"])

            return {"success": True, "file_id": record["id"], "name": record["name"]}
        except Exception as e:
            return {"error": f"Suppression échouée : {e}"}

    # ── Public API (called from save_attachments) ──────────────────

    def register_file(self, record: dict) -> None:
        """Enregistre un fichier en mémoire (appelé après sauvegarde disque+BDD)."""
        self._registry[str(record["id"])] = record

    # ── Internal helpers ───────────────────────────────────────────

    def _get_record(self, file_id: str) -> dict | None:
        return self._registry.get(str(file_id))

    @staticmethod
    def _load_from_db():
        from modules.files.models import UploadedFile
        return list(UploadedFile.objects.filter(is_deleted=False))

    def _register_in_memory(self, db_obj) -> None:
        from modules.files.models import UploadedFile
        obj: UploadedFile = db_obj
        self._registry[str(obj.file_id)] = {
            "id": str(obj.file_id),
            "name": obj.original_name,
            "type": obj.media_type,
            "category": obj.category,
            "size_label": obj.size_label,
            "path": obj.disk_path,
            "person_id": obj.person_id,
            "uploaded_at": obj.uploaded_at.isoformat() if obj.uploaded_at else "",
            "deleted": False,
        }

    @staticmethod
    def _update_db_path(file_id: str, new_path: str) -> None:
        from modules.files.models import UploadedFile
        UploadedFile.objects.filter(file_id=file_id).update(disk_path=new_path)

    @staticmethod
    def _mark_deleted_in_db(file_id: str) -> None:
        from modules.files.models import UploadedFile
        UploadedFile.objects.filter(file_id=file_id).update(is_deleted=True)
