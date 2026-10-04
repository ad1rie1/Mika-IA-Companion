"""Configurer les images :

- rien de branché : la génération d'images n'existe pas (``configured`` faux, toute demande
  ``unconfigured``) ;
- le premier fournisseur déclaré sert « dessiner » d'office, un choix explicite est gardé ;
- une configuration qui a un problème (route vers un inconnu, repli sur soi, OpenAI sans clé,
  serveur sans adresse) est refusée en le disant, et rien n'est gardé ;
- la clé est scellée dans ``mind.db``, jamais en clair, jamais réaffichée ;
- un serveur local a un créneau (la conversation interrompt un dessin de fond), un service
  hébergé deux ;
- ``mika images`` déclare, montre et fait un essai qui écrit l'image ;
- tailles, formats et tarifs.
"""

from __future__ import annotations

import asyncio
import json
import struct

import pytest

from mika.adapters.imaging import config as config_mod
from mika.adapters.imaging import pricing as pricing_mod
from mika.adapters.imaging.config import ImageBackendSpec, ImagingConfig, LiveImaging, build_gateway
from mika.adapters.imaging.fake import FakeImageBackend, solid_png
from mika.adapters.imaging.pricing import price_usd
from mika.adapters.imaging.sizes import dimensions, pixels, sniff
from mika.adapters.store_sqlite import SqliteStore
from mika.app import cli
from mika.app.settings import IMAGING_KEY, SecretBox, Settings
from mika.kernel.clock import ManualClock
from mika.ports.imaging import ASPECTS, OK, UNCONFIGURED, ImageRequest, ImageResult, ImageUsage, Picture

KEY = "sk-CANARI-images-7"


def openai(**kw) -> ImageBackendSpec:
    return ImageBackendSpec(**{"kind": "openai", "model": "gpt-image-1", "api_key": KEY, **kw})


def local(**kw) -> ImageBackendSpec:
    return ImageBackendSpec(**{"kind": "openai_compatible", "model": "qwen-image-2.1",
                               "base_url": "http://127.0.0.1:8190/v1", "adult": True, **kw})


async def test_nothing_plugged_in_means_no_image_generation_at_all():
    cfg = ImagingConfig()
    assert not cfg.enabled and cfg.problems() == [] and cfg.routes == {}
    live = LiveImaging()
    assert not live.configured and live.serving("draw") == "" and not live.can("draw")
    result = await live.generate(ImageRequest(role="draw", call_id="x", prompt="un chat"))
    assert result.outcome == UNCONFIGURED and not result.ok
    assert live.status() == [] and live.resolution() == {"draw": "", "edit": "", "own": ""}


def test_the_first_provider_serves_draw_and_an_explicit_choice_is_kept():
    cfg = ImagingConfig(backends={"oa": openai(), "maison": local()})
    assert cfg.routes == {"draw": "oa"} and cfg.enabled
    chosen = ImagingConfig(backends={"oa": openai(), "maison": local()}, routes={"draw": "maison", "own": "maison"})
    assert chosen.routes == {"draw": "maison", "own": "maison"}


def test_problems_are_said_in_french():
    cfg = ImagingConfig(backends={"oa": openai(api_key="", fallback="oa"), "srv": local(base_url="", model=" "),
                                  "x": openai(fallback="fantome")},
                        routes={"draw": "oa", "edit": "inconnu", "peindre": "oa"})
    text = " | ".join(cfg.problems())
    for words in ("« peindre » n'existe pas", "vise un fournisseur inconnu : inconnu", "son propre repli",
                  "(OpenAI) n'a pas de clé", "« srv » n'a pas d'adresse", "« srv » n'a pas de modèle",
                  "se replie sur un inconnu : fantome"):
        assert words in text, words


def test_the_key_is_masked_and_only_useful_fields_are_shown():
    shown = openai().redacted()
    assert shown["api_key"] == "••••" and KEY not in json.dumps(shown)
    assert "base_url" not in shown and "adult" not in shown and shown["moderation"] == "auto"
    srv = local().redacted()
    assert srv["base_url"] == "http://127.0.0.1:8190/v1" and srv["adult"] is True and "moderation" not in srv


async def test_a_local_server_has_one_slot_and_preempts_a_hosted_service_two():
    made: dict[str, FakeImageBackend] = {}

    def make(name: str, spec: ImageBackendSpec) -> FakeImageBackend:
        real = config_mod.build_backend(name, spec)
        made[name] = FakeImageBackend(name, caps=real.caps)
        return made[name]

    cfg = ImagingConfig(backends={"oa": openai(fallback="maison"), "maison": local()})
    g = build_gateway(cfg, ManualClock(), make=make)
    assert {s["name"]: s["slots"] for s in g.status()} == {"maison": 1, "oa": 2}
    assert g.preempt == frozenset({"maison"}) and g.kinds == {"oa": "openai", "maison": "openai_compatible"}
    assert g.can("draw", adult=True) and g.chain("oa") == ["oa", "maison"]
    result = await g.generate(ImageRequest(role="draw", call_id="c", prompt="nu artistique", adult=True))
    assert result.backend == "maison" and not made["oa"].requests


async def test_settings_seal_the_key_and_refuse_a_broken_configuration(tmp_path):
    store = SqliteStore(tmp_path / "mind.db", tmp_path / "views.db", threaded=False)
    await store.open()
    try:
        settings = Settings(store, SecretBox.for_data(tmp_path))
        await settings.open()
        assert not settings.imaging().enabled
        saved = await settings.save_imaging(ImagingConfig(backends={"oa": openai()}))
        assert saved.routes == {"draw": "oa"}
        raw = json.dumps(settings._get(IMAGING_KEY))
        assert KEY not in raw and "api_key_sealed" in raw
        assert settings.imaging().backends["oa"].api_key == KEY
        with pytest.raises(ValueError, match="pas de clé"):
            await settings.save_imaging(ImagingConfig(backends={"oa": openai(api_key="")}))
        assert settings.imaging().backends["oa"].api_key == KEY  # rien n'a changé
        # un rôle qui n'existe plus est ignoré à la lecture, jamais bloquant
        await settings._put(IMAGING_KEY, {**settings._get(IMAGING_KEY), "routes": {"draw": "oa", "vieux": "oa"}})
        assert settings.imaging().routes == {"draw": "oa"}
    finally:
        await store.close()


def test_the_command_line_declares_shows_and_makes_a_trial_image(tmp_path, capsys, monkeypatch):
    data = tmp_path / "data"

    def run(*argv: str) -> tuple[int, dict]:
        code = cli.main(["--data", str(data), "images", *argv])
        return code, json.loads(capsys.readouterr().out)

    code, out = run("show")
    assert code == 0 and out["activée"] is False and out["backends"] == {}
    code, out = run("backend", "oa", "--kind", "openai", "--model", "gpt-image-1")
    assert code == 1 and any("pas de clé" in p for p in out["problems"])
    code, out = run("backend", "oa", "--kind", "openai", "--model", "gpt-image-1", "--api-key", KEY)
    assert code == 0 and out["activée"] and out["routes"] == {"draw": "oa"} and KEY not in json.dumps(out)
    code, out = run("backend", "oa", "--kind", "openai", "--model", "gpt-image-1-mini")  # la clé est gardée
    assert code == 0 and out["backends"]["oa"]["api_key"] == "••••"

    real = config_mod.build_gateway
    monkeypatch.setattr(cli, "build_image_gateway",
                        lambda cfg, clock: real(cfg, clock, make=lambda n, s: FakeImageBackend(n)))
    code, out = run("essai", "un chat roux", "--out", str(tmp_path / "essai"), "--aspect", "portrait")
    assert code == 0 and out["issue"] == "ok" and out["fournisseur"] == "oa"
    written = tmp_path / "essai.png"
    assert out["fichiers"] == [str(written)] and sniff(written.read_bytes()) == "image/png"
    w, h = dimensions(written.read_bytes())
    assert h > w  # un portrait
    code, out = run("remove", "oa")
    assert code == 0 and not out["activée"]
    code, out = run("essai", "un chat", "--out", str(tmp_path / "rien.png"))
    assert code == 1 and "aucun fournisseur" in out["problems"][0]


def test_sizes_formats_and_dimensions():
    for aspect, ratio in ASPECTS.items():
        for quality in ("draft", "normal", "high"):
            w, h = pixels(aspect, quality)
            assert w % 64 == 0 and h % 64 == 0 and abs(w / h - ratio) < 0.12
    assert pixels("square", "normal") == (1024, 1024) and pixels("portrait", "normal") == (832, 1280)
    png = solid_png(30, 20, (0, 0, 0))
    assert sniff(png) == "image/png" and dimensions(png) == (30, 20)
    jpeg = b"\xff\xd8\xff\xe0" + struct.pack(">H", 4) + b"JF" + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 600, 800) \
        + b"\x00" * 12
    assert sniff(jpeg) == "image/jpeg" and dimensions(jpeg) == (800, 600)
    webp = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"VP8X" + b"\x00" * 8 + (639).to_bytes(3, "little") \
        + (479).to_bytes(3, "little")
    assert sniff(webp) == "image/webp" and dimensions(webp) == (640, 480)
    assert sniff(b"<html>") == "" and dimensions(b"<html>") == (0, 0)


def test_prices_match_exact_or_dated_ids_never_a_mere_prefix(monkeypatch):
    def ok(model: str, **kw) -> ImageResult:
        return ImageResult(OK, (Picture("image/png", b"x"),), model=model, **kw)

    # le journal est lu à la source : ailleurs dans la suite, la configuration des journaux peut le détourner
    said: list[tuple] = []
    monkeypatch.setattr(pricing_mod, "_unpriced_warned", set())
    monkeypatch.setattr(pricing_mod.log, "warning", lambda *args: said.append(args))
    usage = ImageUsage(text_tokens=1_000_000)
    assert price_usd(ok("gpt-image-1-2025-04-23", usage=usage), kind="openai") == pytest.approx(5.0)
    assert price_usd(ok("gpt-image-1-mini", usage=usage), kind="openai") == pytest.approx(2.0)
    assert price_usd(ok("gpt-image-1.5", usage=usage), kind="openai") == 0.0  # inconnu : pas le tarif d'un autre
    assert price_usd(ok("gpt-image-1.5", usage=usage), kind="openai") == 0.0
    assert len(said) == 1 and "gpt-image-1.5" in said[0]  # dit une fois
    assert price_usd(ok("dall-e-3", quality="hd", size="1024x1024"), kind="openai") == pytest.approx(0.08)
    assert price_usd(ok("dall-e-2", quality="standard", size="512x512"), kind="openai") == pytest.approx(0.018)
    assert price_usd(ok("gpt-image-1", usage=usage), kind="openai_compatible") == 0.0
    assert price_usd(ImageResult("refused", model="gpt-image-1", usage=usage), kind="openai") == 0.0


def test_the_live_imaging_can_be_swapped_without_restarting():
    live = LiveImaging()
    g = build_gateway(ImagingConfig(backends={"f": openai()}), ManualClock(),
                      make=lambda n, s: FakeImageBackend(n))
    live.set(g)
    assert live.configured and live.serving("edit") == "f" and live.routes() == {"draw": "f"}
    result = asyncio.run(live.generate(ImageRequest(role="own", call_id="c", prompt="x")))
    assert result.ok and result.backend == "f"
    live.set(None)
    assert not live.configured
