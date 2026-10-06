"""Le prétraitement réel des pièces jointes.

- **Documents** : texte, Markdown, CSV, JSON, code… décodés ; HTML lu en une
  passe linéaire (``ports.preprocess.html_text``, entrée bornée), sans
  scripts ni styles ; PDF par ``pypdf`` (pages et taille bornées). Le travail
  tourne dans un fil, jamais sur la boucle ; le texte est coupé à un budget.
- **Images** : décrites par le rôle utilitaire ``caption`` de la passerelle
  (un modèle qui voit), en deux ou trois phrases.
- **Audio** : transcrit si un service de transcription est branché ; sinon
  elle le dit.
- Plusieurs pièces jointes se lisent **ensemble**, sous un délai par pièce et
  un délai pour le tout : trois photos ne font pas attendre trois fois.

Rien ne lève vers l'appelant : un échec devient une phrase. Le texte rendu
est brut : c'est ``ports.preprocess.render`` qui le cite.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

import httpx

from mika.ports.llm import Image, LLMRequest, Message
from mika.ports.preprocess import Perceived, Upload, html_text, tidy
from mika.vocab.phrasebook import phrase

try:  # optionnel : sans lui, un PDF se dit illisible
    import pypdf
except ImportError:  # pragma: no cover - dépend de l'installation
    pypdf = None  # type: ignore[assignment]

log = logging.getLogger("mika.preprocess")

TEXT_EXTENSIONS = frozenset({"txt", "md", "markdown", "csv", "tsv", "json", "xml", "yaml", "yml", "toml", "ini",
                             "cfg", "log", "py", "js", "ts", "css", "sh", "sql", "c", "h", "cpp", "java", "rs",
                             "go"})
TEXT_MIMES = frozenset({"application/json", "application/xml", "application/x-yaml", "application/javascript",
                        "application/csv", "application/sql"})
#: un PDF plus gros que ceci n'est pas ouvert (pypdf lit en Python pur)
PDF_MAX_BYTES = 8_000_000
#: un document texte n'est décodé que jusque-là
TEXT_MAX_BYTES = 2_000_000

#: une transcription ; ``None`` : aucun service n'est branché
Transcriber = Callable[[bytes, str, str], Awaitable[str | None]]


def _decode(data: bytes) -> str:
    data = data[:TEXT_MAX_BYTES]
    try:
        return data.decode("utf-8").strip()
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace").strip()


def _html(data: bytes) -> str:
    return html_text(_decode(data))


def _pdf(data: bytes, max_pages: int) -> tuple[str, str | None]:
    if pypdf is None:
        return "", phrase("preprocess.failed.no_pdf")
    if len(data) > PDF_MAX_BYTES:
        return "", phrase("preprocess.failed.big_pdf")
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "") for p in reader.pages[:max_pages]]
    except Exception as exc:  # un PDF corrompu est une information, pas une panne
        return "", phrase("preprocess.failed.bad_pdf", error=type(exc).__name__)
    text = tidy("\n".join(t.strip() for t in pages if t.strip()))
    return (text, None) if text else ("", phrase("preprocess.failed.scanned_pdf"))


def extract(name: str, mime: str, data: bytes, max_pages: int = 20) -> tuple[str, str | None]:
    """(texte, raison de l'échec)."""
    if not data:
        return "", phrase("preprocess.failed.empty")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    mime = mime.lower().split(";")[0].strip()
    if mime == "text/html" or ext in ("html", "htm"):
        text = _html(data)
        return (text, None) if text else ("", phrase("preprocess.failed.no_text_page"))
    if mime.startswith("text/") or mime in TEXT_MIMES or ext in TEXT_EXTENSIONS:
        return _decode(data), None
    if mime == "application/pdf" or ext == "pdf":
        return _pdf(data, max_pages)
    return "", phrase("preprocess.failed.format")


class LocalPreprocessor:
    def __init__(self, gateway: Any = None, *, transcribe: Transcriber | None = None, max_chars: int = 8000,
                 timeout_s: float = 30.0, total_s: float = 45.0) -> None:
        self.gateway = gateway
        self.transcribe = transcribe
        self.max_chars = max_chars
        self.timeout_s = timeout_s
        self.total_s = total_s

    async def perceive(self, uploads: Sequence[Upload]) -> list[Perceived]:
        """Toutes les pièces jointes ensemble, chacune sous son délai, le tout sous un délai global :
        ce qui n'est pas lu à temps le dit."""
        tasks = [asyncio.ensure_future(self._one(u)) for u in uploads]
        if not tasks:
            return []
        done, pending = await asyncio.wait(tasks, timeout=self.total_s)
        for t in pending:
            t.cancel()
        out = []
        for u, t in zip(uploads, tasks, strict=True):
            if t in done and not t.cancelled() and t.exception() is None:
                out.append(t.result())
            else:
                out.append(Perceived(u.name, u.kind, phrase("preprocess.failed.too_long"), False, "délai dépassé"))
        return out

    async def _one(self, u: Upload) -> Perceived:
        try:
            async with asyncio.timeout(self.timeout_s):
                if u.kind == "image":
                    return await self._image(u)
                if u.kind == "audio":
                    return await self._audio(u)
                return await self._file(u)
        except TimeoutError:
            return Perceived(u.name, u.kind, phrase("preprocess.failed.too_long"), False, "délai dépassé")
        except Exception as exc:  # une pièce jointe ne fait jamais tomber un message
            log.warning("pièce jointe %s : %r", u.name, exc)
            return Perceived(u.name, u.kind, phrase("preprocess.failed.broken"), False, type(exc).__name__)

    async def _file(self, u: Upload) -> Perceived:
        # dans un fil : la boucle continue de répondre (pings, accusés de réception) pendant la lecture
        text, why = await asyncio.to_thread(extract, u.name, u.mime, u.data)
        if not text:
            return Perceived(u.name, "file", why or phrase("preprocess.failed.unreadable"), False, why)
        if len(text) > self.max_chars:
            text = text[: self.max_chars].rstrip() + phrase("preprocess.seen.cut")
        return Perceived(u.name, "file", text, True)

    async def _image(self, u: Upload) -> Perceived:
        if self.gateway is None:
            return Perceived(u.name, "image", phrase("preprocess.failed.no_vision"), False, "sans modèle de vision")
        req = LLMRequest(role="caption", call_id=f"caption:{u.name}:{len(u.data)}",
                         system_stable=phrase("preprocess.caption.system"),
                         messages=(Message("user", phrase("preprocess.caption.ask"),
                                           images=(Image(u.mime, base64.b64encode(u.data).decode()),)),),
                         max_tokens=300, lane="conversation", priority=0)
        resp = await self.gateway.call(req)
        text = " ".join((resp.text or "").split())
        if not text:
            return Perceived(u.name, "image", phrase("preprocess.failed.blind"), False, "description vide")
        return Perceived(u.name, "image", phrase("preprocess.seen.image", text=text[:1200]), True)

    async def _audio(self, u: Upload) -> Perceived:
        if self.transcribe is None:
            return Perceived(u.name, "audio", phrase("preprocess.failed.no_ears"), False, "sans transcription")
        heard = await self.transcribe(u.data, u.name, u.mime)
        if heard is None:
            return Perceived(u.name, "audio", phrase("preprocess.failed.no_ears"), False, "sans transcription")
        text = " ".join(heard.split())
        if not text:
            return Perceived(u.name, "audio", phrase("preprocess.failed.unclear"), False, "transcription vide")
        return Perceived(u.name, "audio", phrase("preprocess.seen.audio", text=text[:self.max_chars]), True)


def whisper(config: Callable[[], Mapping[str, str]]) -> Transcriber:
    """Une transcription par un point d'accès compatible ``/audio/transcriptions``
    (configuration relue à chaque appel ; non configuré → ``None``)."""

    async def transcribe(data: bytes, name: str, mime: str) -> str | None:
        cfg = config()
        if not cfg.get("base_url") or not cfg.get("api_key"):
            return None
        async with httpx.AsyncClient(timeout=60.0) as http:
            resp = await http.post(f"{cfg['base_url'].rstrip('/')}/audio/transcriptions",
                                   headers={"Authorization": f"Bearer {cfg['api_key']}"},
                                   data={"model": cfg.get("model") or "whisper-1", "language": "fr"},
                                   files={"file": (name, data, mime)})
            resp.raise_for_status()
            return str(resp.json().get("text") or "")

    return transcribe
