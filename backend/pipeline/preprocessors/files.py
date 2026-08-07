"""File preprocessor — documents → extracted text.

Turns a file Part into a text Part carrying the document's actual
content (truncated to prompt budget), so Mika can read what she is
sent instead of acknowledging an opaque blob.

Formats:
  - text-like (txt/md/csv/json/xml/yaml/code/...) → decoded in place
  - text/html → tags stripped, entities unescaped
  - application/pdf → pypdf (declared dependency), page-capped
  - .docx → python-docx when installed, graceful descriptor otherwise
  - anything else → descriptor placeholder with the reason

Parsing is sync CPU work, so it runs in a thread — a 5 MB PDF must not
stall the event loop that carries WebSocket traffic and the background
loops. Failures degrade to a descriptor placeholder; they never raise
into the router.
"""
from __future__ import annotations

import asyncio
import logging

from pipeline.perception import Part

logger = logging.getLogger(__name__)


# Ceiling on extracted text injected into the prompt.
MAX_EXTRACT_CHARS = 8000
# PDF pages beyond this are skipped (each page is an extraction pass).
MAX_PDF_PAGES = 20
# Échéance de l'extraction. `asyncio.to_thread` n'est pas annulable : un PDF
# pathologique fait tourner pypdf dans un thread que plus rien ne reprend.
# Le wait_for ne libère pas le thread, il libère le *tour* — c'est ce qui
# comptait, sinon l'attente est indéfinie et aucune borne amont ne la couvre.
# 20 s couvrent largement 20 pages d'un fichier plafonné à 5 Mo.
EXTRACT_TIMEOUT_SECONDS = 20

# Extensions decoded as plain text when the MIME type is generic.
_TEXT_EXTENSIONS = {
    "txt", "md", "markdown", "csv", "tsv", "json", "xml",
    "yaml", "yml", "toml", "ini", "cfg", "log",
    "py", "js", "ts", "css", "sh", "sql", "c", "h", "cpp", "java", "rs", "go",
}

_TEXT_MIME_EXACT = {
    "application/json", "application/xml", "application/x-yaml",
    "application/javascript", "application/csv", "application/sql",
}


async def process(part: Part) -> Part:
    """Convert a file Part into a text Part with the extracted content
    (or a descriptor placeholder when extraction is impossible)."""
    name = part.metadata.get("name") or "fichier"
    mime = (part.mime_type or "application/octet-stream").lower().split(";")[0].strip()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    data = _decode_bytes(part.content)
    try:
        extracted, method = await asyncio.wait_for(
            asyncio.to_thread(_extract, data, name=name, mime=mime, ext=ext),
            timeout=EXTRACT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("Extraction fichier trop longue (%s, %s)", name, mime)
        extracted, method = "", "extraction trop longue"

    truncated = False
    if extracted:
        if len(extracted) > MAX_EXTRACT_CHARS:
            extracted = extracted[:MAX_EXTRACT_CHARS].rstrip() + "\n[...tronqué]"
            truncated = True
        content = (
            f"[fichier joint: {name} ({mime}) — contenu ci-dessous]\n"
            f"{extracted}\n"
            f"[fin du fichier {name}]"
        )
    else:
        content = f"[fichier joint: {name} ({mime}) — contenu non extractible ({method})]"

    logger.debug(
        "File processed name=%s mime=%s method=%s chars=%d",
        name, mime, method, len(extracted),
    )

    return Part(
        kind="text",
        content=content,
        metadata={
            **part.metadata,
            "original_kind": part.kind,
            "original_mime_type": part.mime_type,
            "preprocessor": "files",
            "extracted": bool(extracted),
            "extract_method": method,
            "truncated": truncated,
        },
    )


# ── Internals (sync — run in a thread) ────────────────────────


def _extract(data: bytes, *, name: str, mime: str, ext: str) -> tuple[str, str]:
    """Dispatch to a format-specific extractor.

    Returns (text, method) on success, ("", reason) on failure — the
    reason surfaces in the placeholder so silence is never mysterious.
    """
    if not data:
        return "", "contenu vide"

    if mime == "text/html" or ext in ("html", "htm"):
        return _extract_html(data)
    if mime.startswith("text/") or mime in _TEXT_MIME_EXACT or ext in _TEXT_EXTENSIONS:
        return _decode_text(data), "texte"
    if mime == "application/pdf" or ext == "pdf":
        return _extract_pdf(data, name=name)
    if ext == "docx" or mime.endswith("wordprocessingml.document"):
        return _extract_docx(data, name=name)
    return "", "format non supporté"


def _decode_text(data: bytes) -> str:
    """UTF-8 first; latin-1 as the accents-preserving fallback (it cannot
    fail, and mis-decoded Windows files still read better than U+FFFD soup)."""
    try:
        return data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace").strip()


def _extract_html(data: bytes) -> tuple[str, str]:
    """Strip tags/scripts and unescape entities — enough for an article
    or an exported page; layout fidelity is not the goal."""
    import html as html_lib
    import re

    raw = _decode_text(data)
    if not raw:
        return "", "HTML vide"
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    return (text, "html") if text else ("", "HTML sans texte")


def _extract_pdf(data: bytes, *, name: str) -> tuple[str, str]:
    try:
        import pypdf
    except ImportError:
        logger.info("pypdf absent — extraction PDF indisponible")
        return "", "pypdf non installé"

    import io
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        total_pages = len(reader.pages)
        chunks = []
        for page in reader.pages[:MAX_PDF_PAGES]:
            chunks.append(page.extract_text() or "")
        text = "\n".join(chunks).strip()
        if not text:
            return "", "PDF sans texte extractible (scanné ?)"
        if total_pages > MAX_PDF_PAGES:
            text += f"\n[...{total_pages - MAX_PDF_PAGES} pages non lues]"
        return text, "pdf"
    except Exception:
        logger.warning("Extraction PDF échouée (%s)", name, exc_info=True)
        return "", "PDF illisible"


def _extract_docx(data: bytes, *, name: str) -> tuple[str, str]:
    try:
        import docx
    except ImportError:
        return "", "python-docx non installé"

    import io
    try:
        document = docx.Document(io.BytesIO(data))
        text = "\n".join(p.text for p in document.paragraphs).strip()
        return (text, "docx") if text else ("", "document vide")
    except Exception:
        logger.warning("Extraction DOCX échouée (%s)", name, exc_info=True)
        return "", "DOCX illisible"


def _decode_bytes(content) -> bytes:
    """Part content arrives as raw bytes or a base64 string."""
    if isinstance(content, bytes):
        return content
    if isinstance(content, str) and content:
        import base64
        try:
            padding = 4 - len(content) % 4
            return base64.b64decode(content + "=" * (padding % 4))
        except Exception:
            logger.debug("File: content is neither bytes nor valid base64")
            return b""
    return b""
