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

# Plafond d'entrées listées inline dans le prompt système. Le bloc repart à
# chaque tour — et à chaque itération de la boucle d'outils : sans plafond,
# une journée de tri de documents y ajoutait une ligne par fichier déposé,
# de façon permanente. Le détail complet reste joignable par files_list,
# exactement comme pour les fichiers plus anciens.
MAX_TODAY_LINES = 6

# Plafonds de la réponse de files_list. Un résultat d'outil ne coûte pas un
# tour : il reste dans l'historique de la boucle d'outils et repart au modèle
# à *chaque* itération suivante du même tour. Une entrée pèse ~60 tokens (UUID
# et horodatage ISO se tokenisent très mal), donc « tous les fichiers » finit
# par peser plus lourd que le prompt système lui-même. La troncature est dite,
# pas subie : la réponse porte `total` à côté de `shown` et la façon d'aller
# chercher la suite.
DEFAULT_LIST_LIMIT = 25
MAX_LIST_LIMIT = 50

# Plafond de chargement du registre en mémoire au démarrage. Le registre sert
# aussi de table de résolution à files_read / analyze / move / delete : la
# borne est donc large — elle empêche une base pathologique de tout charger en
# RAM, pas l'usage normal.
MAX_REGISTRY_LOAD = 2000


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


def _as_int(raw: Any, default: int, minimum: int, maximum: int) -> int:
    """Ramène dans ses bornes un argument numérique fourni par le modèle.

    Un LLM envoie aussi bien ``50`` que ``"50"`` ou ``"toutes"`` : une valeur
    illisible vaut le défaut, jamais une exception au milieu d'un tour.
    """
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


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
        if len(files) >= MAX_REGISTRY_LOAD:
            logger.warning(
                "FilesService: registre plafonné à %d entrées — les fichiers plus "
                "anciens ne sont plus résolus par leur ID.",
                MAX_REGISTRY_LOAD,
            )
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

        Only today's most recent uploads are listed inline; the rest,
        like anything older, is surfaced via the files_list tool.
        """
        from datetime import date
        today = date.today().isoformat()
        today_files = [
            r for r in self._registry.values()
            if not r.get("deleted") and r.get("uploaded_at", "").startswith(today)
        ]
        if not today_files:
            return ""
        recents = sorted(today_files, key=lambda x: x["uploaded_at"], reverse=True)
        lines = [f"Fichiers uploadés aujourd'hui ({len(today_files)}) :"]
        # L'UUID est indispensable pour appeler les outils, la catégorie dit
        # lequel appeler ; la taille ne sert à aucune décision et coûte un
        # tiers de la ligne.
        for r in recents[:MAX_TODAY_LINES]:
            lines.append(
                f'  - ID={r["id"]}  nom="{_as_data(r.get("name"))}"'
                f"  type={r['category']}"
            )
        reste = len(recents) - MAX_TODAY_LINES
        if reste > 0:
            pluriel = "s" if reste > 1 else ""
            lines.append(
                f"  … et {reste} autre{pluriel} fichier{pluriel} aujourd'hui"
                " — utilise files_list pour les voir."
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

    async def op_list(
        self,
        date_filter: str = "",
        category: str = "",
        limit: Any = None,
        offset: Any = None,
    ) -> dict:
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

        total = len(files)
        limit = _as_int(limit, DEFAULT_LIST_LIMIT, 1, MAX_LIST_LIMIT)
        offset = _as_int(offset, 0, 0, total)
        page = sorted(files, key=lambda x: x["uploaded_at"], reverse=True)[
            offset : offset + limit
        ]

        resultat: dict = {
            "files": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "type": r["type"],
                    "category": r["category"],
                    "size": r["size_label"],
                    "uploaded_at": r["uploaded_at"],
                }
                for r in page
            ],
            "shown": len(page),
            "offset": offset,
            "total": total,
        }
        if len(page) < total:
            pluriel = "s" if len(page) > 1 else ""
            suite = offset + len(page)
            message = (
                f"{len(page)} fichier{pluriel} affiché{pluriel} sur {total}"
                f" (du plus récent au plus ancien, à partir du rang {offset})"
                " — affine avec date ou category"
            )
            message += (
                f", ou rappelle files_list avec offset={suite} pour la suite."
                if suite < total else "."
            )
            resultat["message"] = message
        return resultat

    async def op_read(self, file_id: str) -> dict:
        record = self.get(file_id)
        if not record or not self._may_access(record):
            return {"error": "Fichier introuvable."}
        if record.get("deleted"):
            return {"error": "Fichier supprimé."}
        if record["category"] not in ("text", "unknown"):
            return {"error": f"Ce fichier est de type '{record['category']}' — non lisible comme texte."}

        # Même extracteur que le préprocesseur : la catégorie "unknown" couvre
        # application/pdf et les .docx, et décoder leurs octets en utf-8 rendait
        # le flux compressé du PDF — des milliers de U+FFFD ayant la forme d'un
        # succès, que le modèle enchaînait à « résumer ». Un fichier lu par
        # l'outil et le même fichier arrivé en pièce jointe doivent donner le
        # même texte. Extraction en thread : parser un PDF de 5 Mo est du CPU
        # synchrone qui ne doit pas figer la boucle WebSocket.
        from pipeline.preprocessors.files import _extract

        name = record.get("name") or "fichier"
        mime = (record.get("type") or "application/octet-stream").lower().split(";")[0].strip()
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        try:
            def _read_and_extract():
                data = Path(record["path"]).read_bytes()
                return _extract(data, name=name, mime=mime, ext=ext)
            content, method = await asyncio.to_thread(_read_and_extract)
        except Exception as e:
            degradations.record("files.service.op_read", e)
            return {"error": f"Erreur de lecture : {e}"}
        if not content:
            # La raison est nommée par l'extracteur ("pypdf non installé",
            # "PDF sans texte extractible (scanné ?)", "format non supporté") :
            # un échec dit pourquoi plutôt que de rendre du bruit.
            return {"error": f"Contenu non extractible ({method})."}
        if len(content) > 10_000:
            content = content[:10_000] + "\n[...tronqué]"
        return {"content": content, "name": record["name"]}

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

        # Relation de chemin, pas préfixe de chaîne : "../uploads_sauvegarde"
        # se résout hors de uploads/ tout en commençant par la même chaîne.
        uploads_resolved = uploads_root.resolve()
        dest_dir = (uploads_root / destination).resolve()
        if not dest_dir.is_relative_to(uploads_resolved):
            return {"error": "Destination non autorisée (hors de uploads/)."}

        dest_dir.mkdir(parents=True, exist_ok=True)
        src_path = Path(record["path"])
        new_path = dest_dir / src_path.name
        # Un lien symbolique déjà présent sous ce nom sortirait encore du
        # confinement : shutil.move suit la cible sur un autre système de fichiers.
        if not new_path.resolve().is_relative_to(uploads_resolved):
            return {"error": "Destination non autorisée (hors de uploads/)."}

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
        # Même réponse que op_read / op_move : un succès rendu sur un fichier
        # déjà supprimé se lit comme « je viens de le supprimer », et le modèle
        # l'annonce une seconde fois à l'interlocuteur.
        if record.get("deleted"):
            return {"error": "Fichier supprimé."}
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
        # ``Meta.ordering`` trie déjà du plus récent au plus ancien : la borne
        # garde les N derniers, les seuls qu'une conversation cite encore.
        return list(UploadedFile.objects.filter(is_deleted=False)[:MAX_REGISTRY_LOAD])

    def _register_in_memory(self, db_obj: Any) -> None:
        self._registry[str(db_obj.file_id)] = {
            "id": str(db_obj.file_id),
            "name": db_obj.original_name,
            "type": db_obj.media_type,
            "category": db_obj.category,
            "size_label": db_obj.size_label,
            "path": db_obj.disk_path,
            "person_id": db_obj.person_id,
            "uploaded_at": db_obj.uploaded_at_local_iso,
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
