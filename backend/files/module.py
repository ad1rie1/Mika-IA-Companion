"""Module facade for the files service.

Thin adapter: every call forwards to the ``files_service`` singleton.
Exists so Claude's MCP tool inventory and the system prompt's module
context block still include file operations, using the existing plugin
bus rather than a parallel registration path.

The service itself lives in ``files.service`` and can be imported
directly by any consumer that does not want to round-trip through
ModuleManager.
"""

from __future__ import annotations

from modules.base import BaseModule
from modules.types import ModuleTool, ToolParameter, ToolParameterType


class FilesModule(BaseModule):
    """MCP + prompt-context adapter around ``files_service``."""

    def __init__(self) -> None:
        super().__init__("files")

    def get_models(self) -> list:
        from files.models import UploadedFile
        return [UploadedFile]

    async def instantiate(self) -> None:
        from files.service import files_service
        await files_service.ensure_loaded()

    async def shutdown(self) -> None:
        from files.service import files_service
        files_service.shutdown()

    def get_context(self) -> str:
        from files.service import files_service
        return files_service.list_today_context()

    def return_tools(self) -> list[ModuleTool]:
        from files.service import files_service

        async def _list(params: dict) -> dict:
            return await files_service.op_list(
                date_filter=(params.get("date") or "").strip(),
                category=(params.get("category") or "").strip().lower(),
            )

        async def _read(params: dict) -> dict:
            return await files_service.op_read(params.get("file_id", ""))

        async def _analyze_image(params: dict) -> dict:
            return await files_service.op_analyze_image(
                params.get("file_id", ""),
                params.get("question") or "",
            )

        async def _move(params: dict) -> dict:
            return await files_service.op_move(
                params.get("file_id", ""),
                params.get("destination", ""),
            )

        async def _transcribe(params: dict) -> dict:
            return await files_service.op_transcribe(params.get("file_id", ""))

        async def _delete(params: dict) -> dict:
            return await files_service.op_delete(params.get("file_id", ""))

        return [
            ModuleTool(
                name="files_list",
                description=(
                    "Liste les fichiers disponibles sur le serveur. "
                    "Par défaut liste tous les fichiers. "
                    "Filtre optionnel par date (ex: '2024-01-15') ou catégorie ('image', 'audio', 'text')."
                ),
                parameters=[
                    ToolParameter("date", ToolParameterType.STRING, "Filtrer par date YYYY-MM-DD (optionnel)", required=False, default=""),
                    ToolParameter("category", ToolParameterType.STRING, "Filtrer par catégorie: image|audio|text|unknown (optionnel)", required=False, default=""),
                ],
                handler=_list,
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
                handler=_read,
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
                handler=_analyze_image,
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
                handler=_move,
            ),
            ModuleTool(
                name="files_transcribe",
                description=(
                    "Transcrit un fichier audio en texte via Whisper (nécessite OPENAI_API_KEY). "
                    "Fonctionne avec mp3, wav, ogg, webm."
                ),
                parameters=[
                    ToolParameter("file_id", ToolParameterType.STRING, "ID UUID du fichier audio"),
                ],
                handler=_transcribe,
            ),
            ModuleTool(
                name="files_delete",
                description="Supprime un fichier du disque et le marque comme supprimé en BDD.",
                parameters=[
                    ToolParameter("file_id", ToolParameterType.STRING, "ID UUID du fichier"),
                ],
                handler=_delete,
            ),
        ]
