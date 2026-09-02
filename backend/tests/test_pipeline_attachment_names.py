"""Le nom d'une pièce jointe est borné partout où il entre dans le tour.

Le nom est fourni par l'émetteur (payload WebSocket, ``file_name`` Telegram).
Il partait tel quel dans ``Part.metadata``, d'où les préprocesseurs
l'interpolaient dans le tour utilisateur — hors de ``MAX_MESSAGE_LENGTH`` —
et d'où ``attachments_meta`` le persistait, puis l'expédiait dans chaque
trame ``history``. Une pièce jointe au nom de 10 Mo faisait un tour de
10 Mo, une ligne de 10 Mo et une trame de 10 Mo. ``save_attachments``
assainissait déjà, mais seulement le nom gardé pour le disque.
"""
from __future__ import annotations

import pytest

# Multi-ligne et démesuré : les deux propriétés que le nom ne doit pas garder.
ENORME = "x" * 5_000 + "\n" + "y" * 5_000
PLAFOND = 80


def _borne(nom: str) -> bool:
    return len(nom) <= PLAFOND and "\n" not in nom


class TestLeNomEstBorneALEntree:

    def test_from_ws_dict_ramene_le_nom_a_une_ligne_bornee(self):
        from pipeline.media import MediaAttachment

        att = MediaAttachment.from_ws_dict(
            {"name": ENORME, "type": "text/plain", "data": "aGVsbG8="},
        )
        assert _borne(att.name)

    def test_un_media_attachment_lifte_en_part_porte_un_nom_borne(self):
        """Le chemin Telegram construit ``MediaAttachment`` directement :
        c'est à la Perception que tous les chemins convergent."""
        from pipeline.media import MediaAttachment
        from pipeline.perception import _part_from_attachment

        att = MediaAttachment(
            name=ENORME, media_type="text/plain", data="aGVsbG8=",
            category="text",
        )
        assert _borne(_part_from_attachment(att).metadata["name"])

    def test_un_dict_brut_porte_un_nom_borne(self):
        from pipeline.perception import Perception

        p = Perception.from_mixed(
            text="tiens",
            attachments=[{
                "kind": "file", "content": "aGVsbG8=",
                "mime_type": "text/plain", "name": ENORME,
            }],
            source="frontend", person_id="web_x",
        )
        assert _borne(p.parts[1].metadata["name"])

    def test_un_nom_vide_reste_vide(self):
        """Les lecteurs choisissent leur libellé (« fichier », « image ») ;
        l'assainissement ne leur impose pas le sien."""
        from pipeline.media import MediaAttachment
        from pipeline.perception import _part_from_attachment

        att = MediaAttachment(
            name="", media_type="image/png", data="aGVsbG8=", category="image",
        )
        assert _part_from_attachment(att).metadata["name"] == ""

    def test_un_nom_ordinaire_est_conserve(self):
        from pipeline.media import MediaAttachment

        att = MediaAttachment.from_ws_dict(
            {"name": "rapport final.pdf", "type": "application/pdf",
             "data": "aGVsbG8="},
        )
        assert att.name == "rapport final.pdf"

    @pytest.mark.asyncio
    async def test_le_preprocesseur_fichiers_n_interpole_pas_un_nom_demesure(self):
        """Même une Part bâtie ailleurs que par ``from_mixed`` ne fait pas
        gonfler le tour : le préprocesseur borne aussi."""
        from pipeline.perception import Part
        from pipeline.preprocessors import files

        part = Part(
            kind="file", content=b"bonjour", mime_type="text/plain",
            metadata={"name": ENORME},
        )
        out = await files.process(part)

        assert "x" * 100 not in out.content
        assert len(out.content) < 400

    @pytest.mark.asyncio
    async def test_le_nom_telegram_est_borne(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from communication.channels.telegram import TelegramChannel

        tg_file = SimpleNamespace(
            download_as_bytearray=AsyncMock(return_value=bytearray(b"txt")),
        )
        media = SimpleNamespace(
            mime_type="text/plain", file_name=ENORME, file_size=3,
            get_file=AsyncMock(return_value=tg_file),
        )
        msg = SimpleNamespace(
            voice=None, audio=None, photo=None, document=media,
            reply_text=AsyncMock(),
        )
        att = await TelegramChannel()._download_media(msg)

        assert att is not None
        assert _borne(att.name)


class TestAttachmentsMetaEstUneListeFermee:
    """Ce qui est persisté — puis expédié dans chaque trame ``history`` —
    est une liste fermée de clés, pas « tout sauf deux »."""

    @staticmethod
    def _perception(metadata):
        from pipeline.perception import Intent, Modality, Part, Perception

        return Perception(
            modality=Modality.MIXED, intent=Intent.REQUEST_RESPONSE,
            parts=[Part(kind="text", content="[fichier joint]",
                        metadata=metadata)],
            source="frontend", person_id="web_x",
        )

    def test_une_cle_inconnue_n_est_pas_persistee(self):
        from pipeline.processor import _serialize_attachments_meta

        [meta] = _serialize_attachments_meta(self._perception({
            "name": "a.txt",
            "original_kind": "file", "original_mime_type": "text/plain",
            "preprocessor": "files", "extracted": True,
            "extract_method": "texte", "truncated": False,
            "evil": "z" * 10_000, "blob": {"a": 1},
        }))

        assert meta == {
            "kind": "file", "mime_type": "text/plain", "name": "a.txt",
            "preprocessor": "files", "extracted": True,
            "extract_method": "texte", "truncated": False,
        }

    def test_une_valeur_demesuree_est_bornee(self):
        from pipeline.processor import _serialize_attachments_meta

        [meta] = _serialize_attachments_meta(self._perception({
            "name": "z" * 10_000, "original_kind": "file",
        }))
        assert len(meta["name"]) <= 255

    def test_le_marqueur_d_echec_survit(self):
        """Le placeholder d'un préprocesseur en échec porte ``error`` : un
        fichier a été envoyé, et ça s'est mal passé — les deux comptent."""
        from pipeline.processor import _serialize_attachments_meta

        [meta] = _serialize_attachments_meta(self._perception({
            "original_kind": "image", "error": True,
        }))
        assert meta["kind"] == "image"
        assert meta["error"] is True
