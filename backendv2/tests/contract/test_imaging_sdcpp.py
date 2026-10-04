"""Le fournisseur stable-diffusion.cpp (``sd-server``, API native), contre un faux serveur :

- une demande devient une tâche, suivie jusqu'à son terme ; la taille suit la proportion, les pas
  suivent la qualité ; prompt négatif, graine, références passent ; aucune métadonnée dans le PNG ;
- un fond transparent se demande dans la forme recommandée par Qwen-Image 2.1 ;
- une tâche échouée, disparue, une file pleine ou un serveur éteint lèvent en français ;
- annulée côté Mika, la tâche est annulée côté serveur ;
- il se déclare local, retouche, et n'accepte le contenu pour adultes que si on l'a dit ;
- la configuration le construit avec ses pas, et liste son modèle par sa route compatible.
"""

from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from mika.adapters.imaging.config import ImageBackendSpec, ImagingConfig, build_backend
from mika.adapters.imaging.errors import ImagingError
from mika.adapters.imaging.fake import solid_png
from mika.adapters.imaging.models import list_image_models
from mika.adapters.imaging.pricing import price_usd
from mika.adapters.imaging.sdcpp import SdCppBackend
from mika.ports.imaging import ImageRequest, Picture

PNG = solid_png(8, 12, (200, 100, 50))


class FakeSdServer:
    """Un sd-server : une tâche passe par ``queued`` puis ``generating`` avant sa fin."""

    def __init__(self, *, end: str = "completed", submit: int = 202, polls_before_end: int = 2) -> None:
        self.end, self.submit, self.polls_before_end = end, submit, polls_before_end
        self.requests: list[httpx.Request] = []
        self.polls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/sdcpp/v1/img_gen":
            if self.submit != 202:
                return httpx.Response(self.submit, json={"error": {"message": "queue full"}})
            return httpx.Response(202, json={"id": "job_1", "status": "queued", "poll_url": "/sdcpp/v1/jobs/job_1"})
        if path == "/sdcpp/v1/jobs/job_1/cancel":
            return httpx.Response(200, json={"id": "job_1", "status": "cancelled"})
        if path == "/sdcpp/v1/jobs/job_1":
            self.polls += 1
            if self.end == "gone":
                return httpx.Response(410)
            if self.polls <= self.polls_before_end:
                return httpx.Response(200, json={"id": "job_1", "status": "generating" if self.polls > 1 else "queued"})
            if self.end == "completed":
                return httpx.Response(200, json={"id": "job_1", "status": "completed", "result": {
                    "output_format": "png", "images": [{"index": 0, "b64_json": base64.b64encode(PNG).decode()}]}})
            return httpx.Response(200, json={"id": "job_1", "status": "failed", "error": {
                "code": "generation_failed", "message": "generate_image returned empty results"}})
        if path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen-image-2.1-UC-Q4_K_M"}]})
        return httpx.Response(404)


def backend(server: FakeSdServer, **kw) -> SdCppBackend:
    client = httpx.AsyncClient(transport=httpx.MockTransport(server))
    return SdCppBackend(kw.pop("base_url", "http://127.0.0.1:8190/v1"), client=client, poll_s=0.0, **kw)


def req(**kw) -> ImageRequest:
    return ImageRequest(**{"role": "draw", "call_id": "c#1", "prompt": "un chat", **kw})


async def test_a_request_becomes_a_job_followed_to_its_end():
    server = FakeSdServer()
    b = backend(server, model="qwen-image-2.1", steps={"draft": 8})
    result = await b.generate(req(aspect="portrait", quality="draft", negative="flou", seed=7,
                                  refs=(Picture("image/png", PNG),)))
    sent = json.loads(server.requests[0].content)
    assert str(server.requests[0].url) == "http://127.0.0.1:8190/sdcpp/v1/img_gen"  # /v1 retiré de l'adresse
    assert (sent["width"], sent["height"]) == (640, 960) and sent["sample_params"] == {"sample_steps": 8}
    assert sent["negative_prompt"] == "flou" and sent["seed"] == 7 and sent["batch_count"] == 1
    assert sent["ref_images"] == [base64.b64encode(PNG).decode()] and sent["embed_image_metadata"] is False
    assert result.ok and result.images[0].data == PNG and (result.images[0].width, result.images[0].height) == (8, 12)
    assert result.size == "640x960" and result.quality == "8 pas" and server.polls == 3
    assert price_usd(result, kind="sdcpp") == 0.0
    plain = FakeSdServer()
    await backend(plain).generate(req())
    body = json.loads(plain.requests[0].content)
    assert body["seed"] == -1 and body["sample_params"]["sample_steps"] == 25 and body["ref_images"] == []


async def test_a_transparent_background_is_asked_in_the_recommended_form():
    server = FakeSdServer()
    await backend(server).generate(req(prompt="un logo de chat.", transparent=True))
    prompt = json.loads(server.requests[0].content)["prompt"]
    assert prompt == ("This is an RGBA image with transparency. un logo de chat. The image has alpha channel and "
                      "the background is transparent.")


@pytest.mark.parametrize(("server", "words"), [
    (FakeSdServer(end="failed"), "génération échouée : generate_image returned empty results"),
    (FakeSdServer(end="gone"), "disparu"),
    (FakeSdServer(submit=429), "file du serveur d'images est pleine"),
    (FakeSdServer(submit=400), "demande refusée par le serveur d'images (400 : queue full)"),
])
async def test_failures_are_said_in_french(server, words):
    with pytest.raises(ImagingError) as exc:
        await backend(server).generate(req())
    assert words in str(exc.value)


async def test_a_server_that_is_off_says_so():
    def down(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusée", request=r)

    b = SdCppBackend("http://127.0.0.1:8190", client=httpx.AsyncClient(transport=httpx.MockTransport(down)))
    with pytest.raises(ImagingError, match="serveur d'images est-il lancé"):
        await b.generate(req())


async def test_a_request_cancelled_by_mika_is_cancelled_on_the_server():
    server = FakeSdServer(polls_before_end=10_000)
    b = backend(server)
    b.poll_s = 0.01
    task = asyncio.create_task(b.generate(req()))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert server.requests[-1].url.path == "/sdcpp/v1/jobs/job_1/cancel"


async def test_capabilities_configuration_and_listing():
    b = backend(FakeSdServer(), adult=True)
    assert b.caps.local and b.caps.edit and b.caps.adult and b.caps.negative and b.caps.seed
    remote = SdCppBackend("https://images.example.org", adult=False)
    assert not remote.caps.local and not remote.caps.adult
    await remote.aclose()
    spec = ImageBackendSpec(kind="sdcpp", model="qwen-image-2.1", base_url="http://127.0.0.1:8190", adult=True,
                            steps_draft=10, steps_high=40)
    built = build_backend("maison", spec)
    assert isinstance(built, SdCppBackend) and built.steps == {"draft": 10, "normal": 25, "high": 40}
    assert built.caps.adult and spec.local
    await built.aclose()
    shown = spec.redacted()
    assert shown["steps_draft"] == 10 and "moderation" not in shown and shown["adult"] is True
    assert "steps_draft" not in ImageBackendSpec(kind="openai", model="gpt-image-1", api_key="k").redacted()
    assert any("n'a pas d'adresse" in p
               for p in ImagingConfig(backends={"m": spec.model_copy(update={"base_url": ""})}).problems())
    client = httpx.AsyncClient(transport=httpx.MockTransport(FakeSdServer()))
    assert await list_image_models("sdcpp", base_url="http://127.0.0.1:8190", client=client) == \
        ["qwen-image-2.1-UC-Q4_K_M"]
