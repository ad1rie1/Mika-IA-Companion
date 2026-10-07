"""Fournisseur stable-diffusion.cpp (``sd-server``), par son API native asynchrone.

Le serveur local de Mika (``services/mika-images``) parle aussi la langue
d'OpenAI ; l'API native est préférée parce qu'elle dit tout explicitement :

- une demande devient une **tâche** (``POST /sdcpp/v1/img_gen`` → 202), suivie
  jusqu'à son terme (``GET /sdcpp/v1/jobs/{id}``) ; annulée côté Mika (la
  conversation préempte un dessin de fond), la tâche est annulée côté serveur
  si elle attend encore — une génération commencée, elle, va jusqu'au bout
  (le serveur ne sait pas l'interrompre) ;
- le **nombre de pas suit la qualité** (brouillon, normale, haute ; l'ordonnanceur est celui du serveur,
  ``simple`` dans ``services/mika-images``, sans quoi l'image porte une grille fine), la taille
  suit la proportion (multiples de 64) ; prompt négatif, graine et images de
  référence (retouche) passent tels quels ;
- **aucun paramètre caché** : l'API native ne lit rien dans le prompt (seules
  les API de compatibilité le font), et le prompt comme le prompt négatif
  passent quand même par ``clean_prompt`` — la garantie ne dépend pas de la
  version du serveur ; aucune métadonnée dans le PNG
  (``embed_image_metadata`` faux : le prompt ne voyage pas avec l'image) ;
- un fond transparent se demande par le prompt, dans la forme que recommande
  Qwen-Image 2.1.

Une erreur lève ``ImagingError`` en français ; un serveur local ne refuse rien
pour raison de contenu.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from collections.abc import Mapping
from typing import Any

import httpx

from mika.adapters.imaging.errors import ImagingError
from mika.adapters.imaging.openai_images import clean_prompt, is_loopback
from mika.adapters.imaging.sizes import dimensions, pixels, sniff
from mika.ports.imaging import MAX_IMAGE_BYTES, OK, ImageCaps, ImageRequest, ImageResult, Picture

log = logging.getLogger("mika.imaging.sdcpp")

#: les pas par qualité (mesurés sur une RTX 3060 en Vulkan : ≈ 11 s par pas à 1024², ≈ 6 s à 768², easycache en
#: saute la moitié) ; moins de 25, la grille fine de Qwen-Image 2.1 sous stable-diffusion.cpp revient (issue #2041)
DEFAULT_STEPS: Mapping[str, int] = {"draft": 16, "normal": 25, "high": 40}
#: les images de référence d'une retouche (le modèle en accepte dix ; chacune coûte de la mémoire)
MAX_REFS = 4
#: l'intervalle entre deux lectures de l'état d'une tâche (secondes)
POLL_S = 1.0
HTTP_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
#: la forme que Qwen-Image 2.1 recommande pour une image à fond transparent
TRANSPARENT = ("This is an RGBA image with transparency. {prompt}. The image has alpha channel and the background "
               "is transparent.")


class SdCppBackend:
    def __init__(self, base_url: str, *, name: str = "sdcpp", model: str = "", adult: bool = False,
                 steps: Mapping[str, int] | None = None, client: httpx.AsyncClient | None = None,
                 poll_s: float = POLL_S) -> None:
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self.steps = {**DEFAULT_STEPS, **{k: v for k, v in (steps or {}).items() if v and v > 0}}
        self.caps = ImageCaps(edit=True, max_refs=MAX_REFS, transparent=True, negative=True, seed=True,
                              adult=adult, local=is_loopback(self.base_url))
        self.poll_s = poll_s
        self._http = client or httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False)
        self._own = client is None

    def status(self) -> dict[str, Any]:
        return {"pas": dict(self.steps)}

    async def aclose(self) -> None:
        if self._own:
            await self._http.aclose()

    def body(self, req: ImageRequest) -> dict[str, Any]:
        w, h = pixels(req.aspect, req.quality)
        text = clean_prompt(req.prompt)
        prompt = TRANSPARENT.format(prompt=text.strip().rstrip(".")) if req.transparent else text
        return {"prompt": prompt, "negative_prompt": clean_prompt(req.negative), "width": w, "height": h,
                "seed": req.seed if req.seed is not None else -1, "batch_count": 1,
                "ref_images": [base64.b64encode(p.data).decode() for p in req.refs],
                "sample_params": {"sample_steps": self.steps.get(req.quality, self.steps["normal"])},
                "embed_image_metadata": False, "output_format": "png"}

    async def generate(self, req: ImageRequest) -> ImageResult:
        body = self.body(req)
        size, quality = f"{body['width']}x{body['height']}", f"{body['sample_params']['sample_steps']} pas"
        job = await self._submit(body)
        try:
            images = await self._wait(job)
        except asyncio.CancelledError:
            await self._cancel(job)
            raise
        return ImageResult(OK, images, backend=self.name, model=self.model, size=size, quality=quality)

    async def _submit(self, body: dict[str, Any]) -> str:
        try:
            response = await self._http.post(f"{self.base_url}/sdcpp/v1/img_gen", json=body)
        except httpx.ConnectError:
            raise ImagingError("connexion impossible (le serveur d'images est-il lancé ?)") from None
        except httpx.HTTPError as exc:
            raise ImagingError(f"échange impossible ({type(exc).__name__})") from None
        if response.status_code == 429:
            raise ImagingError("la file du serveur d'images est pleine")
        if response.status_code >= 400:
            raise ImagingError(f"demande refusée par le serveur d'images ({response.status_code} : "
                               f"{_message(response)})")
        job = _json(response).get("id")
        if not isinstance(job, str) or not job:
            raise ImagingError("réponse inattendue du serveur d'images")
        return job

    async def _wait(self, job: str) -> tuple[Picture, ...]:
        while True:
            try:
                response = await self._http.get(f"{self.base_url}/sdcpp/v1/jobs/{job}")
            except httpx.HTTPError as exc:
                raise ImagingError(f"le serveur d'images ne répond plus ({type(exc).__name__})") from None
            if response.status_code in (404, 410):
                raise ImagingError("la tâche a disparu du serveur d'images (redémarré ?)")
            if response.status_code >= 400:
                raise ImagingError(f"le serveur d'images a répondu {response.status_code}")
            state = _json(response)
            status = state.get("status")
            if status == "completed":
                return self._pictures(state.get("result"))
            if status in ("failed", "cancelled"):
                error = state.get("error") if isinstance(state.get("error"), dict) else {}
                raise ImagingError(f"génération {'annulée' if status == 'cancelled' else 'échouée'} : "
                                   f"{str(error.get('message') or 'sans détail')[:200]}")
            await asyncio.sleep(self.poll_s)

    async def _cancel(self, job: str) -> None:
        """Une tâche dont Mika ne veut plus : annulée si elle attend encore (une génération commencée va au
        bout, le serveur ne sait pas l'interrompre). Au mieux, brièvement : on ne retient pas l'annulation."""
        try:
            await asyncio.wait_for(self._http.post(f"{self.base_url}/sdcpp/v1/jobs/{job}/cancel"), 3.0)
        except (TimeoutError, httpx.HTTPError):
            log.info("images : la tâche %s n'a pas pu être annulée", job)

    def _pictures(self, result: Any) -> tuple[Picture, ...]:
        items = result.get("images") if isinstance(result, dict) else None
        out = []
        for item in items if isinstance(items, list) else ():
            encoded = item.get("b64_json") if isinstance(item, dict) else None
            if not isinstance(encoded, str) or not encoded:
                continue
            if len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 4:
                raise ImagingError("image trop lourde")
            try:
                data = base64.b64decode(encoded)
            except (binascii.Error, ValueError):
                raise ImagingError("image illisible") from None
            mime = sniff(data)
            if not mime:
                raise ImagingError("le serveur n'a pas rendu une image")
            w, h = dimensions(data)
            out.append(Picture(mime, data, w, h))
        if not out:
            raise ImagingError("réponse sans image")
        return tuple(out)


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        raise ImagingError("réponse illisible du serveur d'images") from None
    return data if isinstance(data, dict) else {}


def _message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return "sans détail"
    error = data.get("error") if isinstance(data, dict) else None
    text = error.get("message") if isinstance(error, dict) else (error if isinstance(error, str) else "")
    return " ".join(str(text or "sans détail").split())[:200]
