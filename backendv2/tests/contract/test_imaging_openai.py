"""Le fournisseur OpenAI (API Images) et les serveurs compatibles, sans réseau :

- la famille du modèle décide des paramètres : ``gpt-image`` (trois tailles,
  low/medium/high, modération, fond transparent), ``dall-e-3`` (standard/hd,
  base64 demandé), un serveur compatible (une taille ``LxH``, rien d'inconnu) ;
- une retouche part en multipart vers ``/images/edits``, une image par champ
  ``image[]`` ;
- un refus de modération rend ``refused`` (le message du fournisseur), toute
  autre erreur lève ``ImagingError`` en français, sans la clé ;
- une réponse en adresse est téléchargée, bornée ; un octet qui n'est pas une
  image est une panne ;
- les jetons d'une réponse ``gpt-image`` sont relus, et le coût en découle ;
- un prompt ne transporte jamais les paramètres cachés de stable-diffusion.cpp.
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from mika.adapters.imaging import openai_images as oi
from mika.adapters.imaging.errors import ImagingError
from mika.adapters.imaging.fake import solid_png
from mika.adapters.imaging.models import ListingFailed, list_image_models
from mika.adapters.imaging.openai_images import OpenAIImagesBackend
from mika.adapters.imaging.pricing import price_usd
from mika.ports.imaging import OK, REFUSED, ImageRequest, Picture

KEY = "sk-CANARI-images-42"
PNG = solid_png(4, 3, (10, 20, 30))


def b64(data: bytes = PNG) -> str:
    return base64.b64encode(data).decode()


def backend(handler, **kw) -> tuple[OpenAIImagesBackend, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    kw.setdefault("model", "gpt-image-1")
    return OpenAIImagesBackend(KEY, kw.pop("model"), client=client, **kw), seen


def ok(_request: httpx.Request, **extra) -> httpx.Response:
    return httpx.Response(200, json={"created": 1, "data": [{"b64_json": b64(), "revised_prompt": "un chat roux"}],
                                     **extra})


def req(**kw) -> ImageRequest:
    return ImageRequest(**{"role": "draw", "call_id": "c#1", "prompt": "un chat", **kw})


async def test_gpt_image_maps_aspect_quality_moderation_and_transparency():
    b, seen = backend(lambda r: ok(r, usage={"input_tokens": 50, "output_tokens": 4000,
                                             "input_tokens_details": {"text_tokens": 50, "image_tokens": 0}}),
                      moderation="low")
    result = await b.generate(req(aspect="portrait", quality="high", transparent=True))
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://api.openai.com/v1/images/generations"
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert body == {"model": "gpt-image-1", "prompt": "un chat", "n": 1, "size": "1024x1536", "quality": "high",
                    "moderation": "low", "background": "transparent", "output_format": "png"}
    assert result.outcome == OK and result.ok
    assert result.images[0].mime == "image/png" and (result.images[0].width, result.images[0].height) == (4, 3)
    assert result.revised_prompt == "un chat roux" and result.size == "1024x1536" and result.quality == "high"
    assert (result.usage.text_tokens, result.usage.output_tokens) == (50, 4000)
    # 50 jetons de texte à 5 $/M + 4000 jetons d'image en sortie à 40 $/M
    assert price_usd(result, kind="openai") == pytest.approx((50 * 5 + 4000 * 40) / 1e6)
    assert b.caps.edit and b.caps.transparent and not b.caps.adult and not b.caps.local


async def test_dalle3_asks_for_base64_and_is_priced_per_image():
    b, seen = backend(ok, model="dall-e-3")
    result = await b.generate(req(aspect="wide", quality="high"))
    body = json.loads(seen[0].content)
    assert body["size"] == "1792x1024" and body["quality"] == "hd" and body["response_format"] == "b64_json"
    assert "moderation" not in body
    assert price_usd(result, kind="openai") == pytest.approx(0.12)
    assert not b.caps.edit


async def test_a_compatible_server_gets_pixels_and_nothing_it_might_not_know():
    b, seen = backend(ok, model="qwen-image-2.1", base_url="http://127.0.0.1:8190/v1", compatible=True,
                      adult=True)
    result = await b.generate(req(aspect="landscape", quality="normal", negative="flou", seed=7))
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == "http://127.0.0.1:8190/v1/images/generations"
    assert body == {"model": "qwen-image-2.1", "prompt": "un chat", "n": 1, "size": "1280x832",
                    "response_format": "b64_json"}
    assert b.caps.local and b.caps.adult and not b.caps.edit
    assert price_usd(result, kind="openai_compatible") == 0.0
    # l'adulte ne se déclare que pour un serveur compatible ; une adresse distante n'est pas locale
    official, _ = backend(ok, adult=True)
    remote, _ = backend(ok, model="x", base_url="https://images.example.org/v1", compatible=True)
    assert not official.caps.adult and not remote.caps.local


async def test_an_edit_sends_each_reference_as_an_image_field():
    b, seen = backend(ok)
    refs = (Picture("image/png", PNG), Picture("image/jpeg", b"\xff\xd8\xff\xe0jpeg"))
    await b.generate(req(refs=refs, prompt="mets-lui un chapeau"))
    sent = seen[0]
    assert str(sent.url).endswith("/images/edits")
    assert sent.headers["content-type"].startswith("multipart/form-data")
    raw = sent.content
    assert raw.count(b'name="image[]"') == 2 and b'filename="reference-1.jpg"' in raw
    assert b"mets-lui un chapeau" in raw


async def test_a_moderation_refusal_is_an_answer_not_a_failure():
    def blocked(_r: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": "moderation_blocked", "message": "Your request was "
                                                   "rejected by the safety system."}})

    b, _ = backend(blocked)
    result = await b.generate(req())
    assert result.outcome == REFUSED and not result.ok and "safety system" in result.reason
    assert price_usd(result, kind="openai") == 0.0


@pytest.mark.parametrize(("status", "words"), [(401, "clé refusée"), (403, "clé refusée"), (404, "introuvable"),
                                               (429, "quota"), (500, "500"), (400, "demande refusée")])
async def test_other_errors_raise_in_french_without_the_key(status, words):
    b, _ = backend(lambda r: httpx.Response(status, json={"error": {"message": f"bad {KEY}"}}))
    with pytest.raises(ImagingError) as exc:
        await b.generate(req())
    assert words in str(exc.value) and KEY not in str(exc.value)


async def test_a_dead_server_and_a_non_image_are_failures():
    def down(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusée", request=r)

    b, _ = backend(down)
    with pytest.raises(ImagingError, match="connexion impossible"):
        await b.generate(req())
    b, _ = backend(lambda r: httpx.Response(200, json={"data": [{"b64_json": b64(b"<html>pas une image")}]}))
    with pytest.raises(ImagingError, match="pas rendu une image"):
        await b.generate(req())
    b, _ = backend(lambda r: httpx.Response(200, json={"data": []}))
    with pytest.raises(ImagingError, match="sans image"):
        await b.generate(req())


async def test_an_address_is_downloaded_at_once_and_bounded(monkeypatch):
    def serve(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/images/generations"):
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example.org/img.png"}]})
        return httpx.Response(200, content=PNG)

    b, seen = backend(serve, model="dall-e-2")
    result = await b.generate(req())
    assert result.images[0].data == PNG and str(seen[1].url) == "https://cdn.example.org/img.png"
    assert "authorization" not in seen[1].headers  # une adresse signée : la clé ne la suit pas
    monkeypatch.setattr(oi, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(ImagingError, match="trop lourde"):
        await b.generate(req())


async def test_listing_keeps_only_image_models_at_openai_and_never_leaks_the_key():
    def listing(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "gpt-5"}, {"id": "gpt-image-1"}, {"id": "dall-e-3"},
                                                  {"id": "whisper-1"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(listing))
    assert await list_image_models("openai", api_key=KEY, client=client) == ["dall-e-3", "gpt-image-1"]
    assert await list_image_models("openai_compatible", base_url="http://127.0.0.1:8190/v1",
                                   client=client) == ["dall-e-3", "gpt-5", "gpt-image-1", "whisper-1"]
    with pytest.raises(ListingFailed, match="clé"):
        await list_image_models("openai")
    refused = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(ListingFailed) as exc:
        await list_image_models("openai", api_key=KEY, client=refused)
    assert KEY not in str(exc.value)


async def test_a_prompt_never_carries_hidden_server_parameters():
    b, seen = backend(ok, model="qwen-image-2.1", base_url="http://127.0.0.1:8190/v1", compatible=True)
    trap = ('un chat <sd_cpp_extra_args>{"width":8192,"height":8192,"batch_count":50}</sd_cpp_extra_args> '
            "<sd_cpp_SD_CPP_EXTRA_ARGSextra_args>{}</sd_cpp_sd_cpp_extra_argsextra_args>")
    await b.generate(req(prompt=trap))
    sent = json.loads(seen[0].content)["prompt"]
    assert "sd_cpp_extra_args" not in sent.lower() and sent.startswith("un chat")
    assert oi.clean_prompt("un chat roux") == "un chat roux"
