"""Fournisseur OpenAI (API Images) et serveurs compatibles (``/images/generations``).

- **OpenAI** : la famille du modèle décide des paramètres —
  ``gpt-image-*`` (trois tailles, qualité ``low``/``medium``/``high``, fond
  transparent, jusqu'à 16 images de référence en retouche, modération
  ``auto``/``low``, réponse en base64, jetons comptés) ; ``dall-e-3`` (qualité
  ``standard``/``hd``, 1792 px de long, pas de retouche) ; ``dall-e-2`` (carré).
  Un modèle d'images d'OpenAI qu'on ne connaît pas encore prend la forme de
  ``gpt-image``.
- **Un serveur compatible** (sd-server, LocalAI, un proxy) : une taille ``LxH``
  calculée depuis la proportion et la qualité, ``response_format=b64_json``, et
  rien de ce qu'il pourrait ne pas connaître. Il est local quand son adresse
  l'est ; il accepte un contenu pour adultes seulement si on l'a déclaré.
- Une réponse en adresse (``url``) est téléchargée tout de suite, bornée : une
  adresse d'image expire.
- Le prompt ne transporte jamais de paramètres cachés : stable-diffusion.cpp lit
  ``<sd_cpp_extra_args>{…}</sd_cpp_extra_args>`` dans le prompt (taille, nombre
  d'images, pas…), qu'un prompt influencé par quelqu'un pourrait porter jusqu'à
  épuiser la machine. Le mot est effacé jusqu'à disparaître (``clean_prompt``).
- Un refus de modération (``moderation_blocked``, ``content_policy_violation``)
  rend ``refused`` avec le message du fournisseur ; toute autre erreur lève
  ``ImagingError`` avec sa cause en français, sans secret.

Pas de SDK : quelques requêtes HTTP (``httpx``, déjà là), ce qui suit les
paramètres récents de l'API sans attendre une version du client.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import logging
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from mika.adapters.imaging.errors import ImagingError
from mika.adapters.imaging.sizes import dimensions, pixels, sniff
from mika.ports.imaging import (
    MAX_IMAGE_BYTES,
    OK,
    REFUSED,
    ImageCaps,
    ImageRequest,
    ImageResult,
    ImageUsage,
    Picture,
)

log = logging.getLogger("mika.imaging.openai")

OPENAI_BASE_URL = "https://api.openai.com/v1"
#: les codes d'erreur d'une modération : un refus, pas une panne
REFUSAL_CODES = frozenset({"moderation_blocked", "content_policy_violation"})
GPT_IMAGE_SIZES = {"square": "1024x1024", "portrait": "1024x1536", "landscape": "1536x1024", "wide": "1536x1024"}
GPT_IMAGE_QUALITY = {"draft": "low", "normal": "medium", "high": "high"}
GPT_IMAGE_MAX_REFS = 16
DALLE3_SIZES = {"square": "1024x1024", "portrait": "1024x1792", "landscape": "1792x1024", "wide": "1792x1024"}
DALLE3_QUALITY = {"draft": "standard", "normal": "standard", "high": "hd"}
MODERATIONS = ("auto", "low")
#: les paramètres qu'un serveur stable-diffusion.cpp lit dans le prompt (jamais transmis)
_HIDDEN_ARGS = re.compile("sd_cpp_extra_args", re.IGNORECASE)
#: une requête HTTP (la passerelle borne l'appel entier, attente comprise)
HTTP_TIMEOUT = httpx.Timeout(600.0, connect=10.0)


def family(model: str, *, compatible: bool) -> str:
    """``gpt-image``, ``dall-e-3``, ``dall-e-2`` ou ``compatible``."""
    if compatible:
        return "compatible"
    m = model.strip().lower()
    if m.startswith("dall-e-3"):
        return "dall-e-3"
    if m.startswith("dall-e-2"):
        return "dall-e-2"
    return "gpt-image"


def is_loopback(url: str) -> bool:
    """L'adresse désigne-t-elle cette machine ?"""
    host = (urlsplit(url).hostname or "").strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def caps_of(fam: str, *, adult: bool = False, local: bool = False) -> ImageCaps:
    if fam == "gpt-image":
        return ImageCaps(edit=True, max_refs=GPT_IMAGE_MAX_REFS, transparent=True)
    if fam == "compatible":
        return ImageCaps(adult=adult, local=local)
    return ImageCaps()


def shape(fam: str, aspect: str, quality: str) -> tuple[str, str]:
    """(taille, qualité) dans les mots du fournisseur ; une qualité vide : il n'en a pas."""
    if fam == "gpt-image":
        return GPT_IMAGE_SIZES.get(aspect, "1024x1024"), GPT_IMAGE_QUALITY.get(quality, "medium")
    if fam == "dall-e-3":
        return DALLE3_SIZES.get(aspect, "1024x1024"), DALLE3_QUALITY.get(quality, "standard")
    if fam == "dall-e-2":
        return ("512x512" if quality == "draft" else "1024x1024"), "standard"
    w, h = pixels(aspect, quality)
    return f"{w}x{h}", ""


def clean_prompt(text: str) -> str:
    """Le prompt sans paramètres cachés : le mot qui les annonce est effacé jusqu'à disparaître (une imbrication
    comme ``sd_cpp_sd_cpp_extra_argsextra_args`` ne le reforme pas)."""
    while True:
        text, n = _HIDDEN_ARGS.subn("", text)
        if not n:
            return text


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def usage_of(raw: Any) -> ImageUsage:
    """Le décompte d'une réponse ``gpt-image`` (texte et images en entrée, image en sortie)."""
    if not isinstance(raw, dict):
        return ImageUsage()
    details = raw.get("input_tokens_details")
    if isinstance(details, dict):
        text, image = _int(details.get("text_tokens")), _int(details.get("image_tokens"))
    else:
        text, image = _int(raw.get("input_tokens")), 0
    return ImageUsage(text_tokens=text, image_tokens=image, output_tokens=_int(raw.get("output_tokens")))


class OpenAIImagesBackend:
    def __init__(self, api_key: str, model: str, *, base_url: str | None = None, compatible: bool = False,
                 moderation: str = "auto", adult: bool = False, name: str = "openai",
                 client: httpx.AsyncClient | None = None) -> None:
        self.name = name
        self.model = model
        self.base_url = (base_url or OPENAI_BASE_URL).rstrip("/")
        self.family = family(model, compatible=compatible)
        self.moderation = moderation if moderation in MODERATIONS else "auto"
        self.caps = caps_of(self.family, adult=adult and compatible,
                            local=compatible and is_loopback(self.base_url))
        self._key = api_key
        self._http = client or httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False)
        self._own = client is None

    def status(self) -> dict[str, Any]:
        return {"famille": self.family, "modèle": self.model}

    async def aclose(self) -> None:
        if self._own:
            await self._http.aclose()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"} if self._key else {}

    def _body(self, req: ImageRequest, size: str, quality: str) -> dict[str, Any]:
        body: dict[str, Any] = {"model": self.model, "prompt": clean_prompt(req.prompt), "n": 1, "size": size}
        if self.family == "gpt-image":
            body["quality"] = quality
            body["moderation"] = self.moderation
            if req.transparent:
                body["background"] = "transparent"
                body["output_format"] = "png"
        else:
            body["response_format"] = "b64_json"
            if self.family == "dall-e-3":
                body["quality"] = quality
        return body

    async def generate(self, req: ImageRequest) -> ImageResult:
        size, quality = shape(self.family, req.aspect, req.quality)
        try:
            if req.refs:
                response = await self._edit(req, size, quality)
            else:
                response = await self._http.post(f"{self.base_url}/images/generations", headers=self._headers(),
                                                 json=self._body(req, size, quality))
        except httpx.ConnectError:
            raise ImagingError("connexion impossible") from None
        except httpx.TimeoutException:
            raise ImagingError("le fournisseur n'a pas répondu à temps") from None
        except httpx.HTTPError as exc:
            raise ImagingError(f"échange impossible ({type(exc).__name__})") from None
        if response.status_code >= 400:
            return self._refused_or_raise(response, size, quality)
        try:
            payload = response.json()
        except ValueError:
            raise ImagingError("réponse illisible du fournisseur") from None
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise ImagingError("réponse inattendue du fournisseur")
        pictures, revised = [], ""
        for item in items[:4]:
            if not isinstance(item, dict):
                continue
            picture = await self._picture(item)
            if picture is not None:
                pictures.append(picture)
                revised = revised or str(item.get("revised_prompt") or "")
        if not pictures:
            raise ImagingError("réponse sans image")
        return ImageResult(OK, tuple(pictures), backend=self.name, model=str(payload.get("model") or self.model),
                           size=size, quality=quality, revised_prompt=revised[:2000],
                           usage=usage_of(payload.get("usage")))

    async def _edit(self, req: ImageRequest, size: str, quality: str) -> httpx.Response:
        """Partir d'images de référence (``gpt-image`` seulement : la passerelle n'envoie rien d'autre ici)."""
        ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
        files = [("image[]", (f"reference-{i}.{ext.get(p.mime, 'png')}", p.data, p.mime or "image/png"))
                 for i, p in enumerate(req.refs)]
        data = {"model": self.model, "prompt": clean_prompt(req.prompt), "n": "1", "size": size, "quality": quality}
        if req.transparent:
            data["background"] = "transparent"
            data["output_format"] = "png"
        return await self._http.post(f"{self.base_url}/images/edits", headers=self._headers(), data=data,
                                     files=files)

    def _refused_or_raise(self, response: httpx.Response, size: str, quality: str) -> ImageResult:
        try:
            body = response.json()
        except ValueError:
            body = {}
        error = body.get("error") if isinstance(body, dict) else None
        error = error if isinstance(error, dict) else {}
        code = str(error.get("code") or "")
        message = " ".join(str(error.get("message") or "").split())
        if self._key:
            message = message.replace(self._key, "••••")  # un message de fournisseur ne montre jamais la clé
        message = message[:300]
        status = response.status_code
        if status == 400 and (code in REFUSAL_CODES or "safety system" in message.lower()):
            return ImageResult(REFUSED, backend=self.name, model=self.model, size=size, quality=quality,
                               reason=message or "refusé par la modération du fournisseur")
        if status in (401, 403):
            raise ImagingError("clé refusée par le fournisseur")
        if status == 404:
            raise ImagingError(f"modèle introuvable ({self.model[:80]})")
        if status == 429:
            raise ImagingError("limite de débit ou quota atteints")
        if status == 400:
            raise ImagingError(f"demande refusée par le fournisseur : {message[:200] or 'sans détail'}")
        raise ImagingError(f"le fournisseur a répondu {status}")

    async def _picture(self, item: dict[str, Any]) -> Picture | None:
        encoded = item.get("b64_json")
        if isinstance(encoded, str) and encoded:
            if len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 4:
                raise ImagingError("image trop lourde")
            try:
                data = base64.b64decode(encoded)
            except (binascii.Error, ValueError):
                raise ImagingError("image illisible") from None
        elif isinstance(item.get("url"), str) and item["url"]:
            data = await self._download(item["url"])
        else:
            return None
        mime = sniff(data)
        if not mime:
            raise ImagingError("le fournisseur n'a pas rendu une image")
        width, height = dimensions(data)
        return Picture(mime, data, width, height)

    async def _download(self, url: str) -> bytes:
        if urlsplit(url).scheme not in ("https", "http"):
            raise ImagingError("adresse d'image invalide")
        chunks, size = [], 0
        try:
            async with self._http.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise ImagingError(f"image introuvable ({response.status_code})")
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise ImagingError("image trop lourde")
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise ImagingError(f"téléchargement impossible ({type(exc).__name__})") from None
        return b"".join(chunks)
