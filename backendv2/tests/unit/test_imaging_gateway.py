"""La passerelle des images (fournisseurs factices) :

- un rôle sans fournisseur retombe sur « dessiner » ; rien de branché : ``unconfigured`` ;
- seuls les candidats capables sont appelés (références, adulte) ; aucun : ``unsupported``,
  sans appel ;
- un refus de modération ne repart pas ailleurs — sauf, quand la demande le permet, vers
  un serveur local de la chaîne, jamais vers un autre service hébergé ;
- une panne, une réponse vide ou un délai passent au repli avec le temps qui reste ;
- une annulation se propage ; à un seul créneau, la conversation interrompt un dessin de
  fond ;
- chaque appel laisse une trace (rôle, fournisseur, issue, coût, corrélation).
"""

from __future__ import annotations

import asyncio

import pytest

from mika.adapters.imaging import gateway as gateway_mod
from mika.adapters.imaging.fake import FakeImageBackend
from mika.adapters.imaging.gateway import ImageGateway, ImageTrace
from mika.kernel.clock import ManualClock
from mika.kernel.slots import PREEMPTED
from mika.ports.imaging import (
    FAILED,
    OK,
    REFUSED,
    TIMEOUT,
    UNCONFIGURED,
    UNSUPPORTED,
    ImageCaps,
    ImageRequest,
    ImageResult,
    Picture,
)

HOSTED = ImageCaps(edit=True, max_refs=16, transparent=True)
DALLE = ImageCaps()
LOCAL = ImageCaps(adult=True, local=True)


def gw(backends: dict, routes: dict, **kw) -> tuple[ImageGateway, list[ImageTrace]]:
    traces: list[ImageTrace] = []
    return ImageGateway(backends, routes, clock=ManualClock(), on_trace=traces.append, **kw), traces


def req(**kw) -> ImageRequest:
    return ImageRequest(**{"role": "draw", "call_id": "ep-1#1", "prompt": "un chat", **kw})


REF = Picture("image/png", b"\x89PNG\r\n\x1a\n")


async def test_nothing_plugged_in_means_unconfigured_and_roles_fall_back_on_draw():
    empty, _ = gw({}, {})
    result = await empty.generate(req())
    assert result.outcome == UNCONFIGURED and "dessiner" not in result.reason and "draw" in result.reason
    assert not empty.can("draw")
    a, b = FakeImageBackend("a"), FakeImageBackend("b")
    g, _ = gw({"a": a, "b": b}, {"draw": "a", "edit": "b"})
    assert g.resolve("own") == "a" and g.resolve("edit") == "b"
    await g.generate(req(role="own"))
    await g.generate(req(role="edit", refs=(REF,)))
    assert len(a.requests) == 1 and len(b.requests) == 1
    assert g.resolution(("draw", "edit", "own")) == {"draw": "a", "edit": "b", "own": "a"}


async def test_only_capable_candidates_are_called():
    dalle = FakeImageBackend("dalle", caps=DALLE)
    hosted = FakeImageBackend("hosted", caps=HOSTED)
    g, _ = gw({"dalle": dalle, "hosted": hosted}, {"draw": "dalle"}, backend_fallbacks={"dalle": "hosted"})
    result = await g.generate(req(refs=(REF,)))  # dall-e ne sait pas partir d'une image : son repli, oui
    assert result.ok and result.backend == "hosted" and not dalle.requests
    alone, _ = gw({"dalle": dalle}, {"draw": "dalle"})
    refused = await alone.generate(req(refs=(REF,)))
    assert refused.outcome == UNSUPPORTED and "partir d'une image" in refused.reason and not dalle.requests
    assert alone.can("draw") and not alone.can("draw", refs=1)
    too_many = await g.generate(req(refs=(REF,) * 17))
    assert too_many.outcome == UNSUPPORTED


async def test_adult_content_only_reaches_a_provider_that_accepts_it():
    hosted = FakeImageBackend("hosted", caps=HOSTED)
    local = FakeImageBackend("local", caps=LOCAL)
    g, _ = gw({"hosted": hosted, "local": local}, {"draw": "hosted"}, backend_fallbacks={"hosted": "local"})
    result = await g.generate(req(adult=True))
    assert result.ok and result.backend == "local" and not hosted.requests
    assert g.can("draw", adult=True)
    no_local, _ = gw({"hosted": hosted}, {"draw": "hosted"})
    assert (await no_local.generate(req(adult=True))).outcome == UNSUPPORTED and not hosted.requests
    assert not no_local.can("draw", adult=True)


async def test_a_refusal_is_an_answer_never_shopped_around_another_hosted_service():
    strict = FakeImageBackend("strict", caps=HOSTED, refuse=("chat",))
    other = FakeImageBackend("other", caps=HOSTED)
    local = FakeImageBackend("local", caps=LOCAL)
    g, traces = gw({"strict": strict, "other": other, "local": local}, {"draw": "strict"},
                   backend_fallbacks={"strict": "other", "other": "local"})
    result = await g.generate(req())
    assert result.outcome == REFUSED and result.backend == "strict" and not other.requests and not local.requests
    assert [t.outcome for t in traces] == ["refused"]
    # permis par la demande : seulement vers le local, jamais vers l'autre service hébergé
    allowed = await g.generate(req(refusal_fallback=True))
    assert allowed.ok and allowed.backend == "local" and not other.requests
    # sans local dans la chaîne, le refus reste la réponse
    g2, _ = gw({"strict": strict, "other": other}, {"draw": "strict"}, backend_fallbacks={"strict": "other"})
    assert (await g2.generate(req(refusal_fallback=True))).outcome == REFUSED and not other.requests


async def test_a_failure_or_an_empty_answer_falls_back_and_says_why():
    broken = FakeImageBackend("broken", caps=HOSTED, fail="clé refusée par le fournisseur")
    backup = FakeImageBackend("backup", caps=HOSTED)
    g, traces = gw({"broken": broken, "backup": backup}, {"draw": "broken"}, backend_fallbacks={"broken": "backup"})
    result = await g.generate(req())
    assert result.ok and result.backend == "backup"
    assert [(t.backend, t.outcome) for t in traces] == [("broken", "error:ImagingError"), ("backup", "ok")]
    alone, _ = gw({"broken": broken}, {"draw": "broken"})
    failed = await alone.generate(req())
    assert failed.outcome == FAILED and failed.reason == "clé refusée par le fournisseur"

    class Empty(FakeImageBackend):
        async def generate(self, r: ImageRequest) -> ImageResult:
            return ImageResult(OK)

    g3, _ = gw({"empty": Empty("empty"), "backup": backup}, {"draw": "empty"}, backend_fallbacks={"empty": "backup"})
    assert (await g3.generate(req())).backend == "backup"
    alone3, _ = gw({"empty": Empty("empty")}, {"draw": "empty"})
    assert (await alone3.generate(req())).reason == "réponse sans image"


async def test_a_slow_provider_times_out_and_the_fallback_gets_the_time_left(monkeypatch):
    monkeypatch.setattr(gateway_mod, "MIN_RETRY_S", 0.0)
    slow = FakeImageBackend("slow", caps=HOSTED, latency=30.0)
    quick = FakeImageBackend("quick", caps=HOSTED)
    g, traces = gw({"slow": slow, "quick": quick}, {"draw": "slow"}, backend_fallbacks={"slow": "quick"},
                   deadlines={"background": 0.3})
    result = await g.generate(req())
    assert result.ok and result.backend == "quick" and traces[0].outcome == "timeout"
    alone, _ = gw({"slow": slow}, {"draw": "slow"}, deadlines={"background": 0.1})
    assert (await alone.generate(req())).outcome == TIMEOUT


async def test_cancellation_propagates_and_the_conversation_preempts_a_background_drawing():
    local = FakeImageBackend("local", caps=LOCAL, latency=5.0)
    g, traces = gw({"local": local}, {"draw": "local"}, slots={"local": 1}, preempt=frozenset({"local"}))
    background = asyncio.create_task(g.generate(req(role="own", priority=2, call_id="fond#1")))
    await asyncio.sleep(0.01)
    local.latency = 0.0
    answer = await g.generate(req(priority=0, lane="conversation", call_id="conv#1"))
    assert answer.ok
    with pytest.raises(asyncio.CancelledError) as exc:
        await background
    assert PREEMPTED in exc.value.args
    assert {t.call_id: t.outcome for t in traces} == {"fond#1": "preempted", "conv#1": "ok"}
    slow = FakeImageBackend("slow", latency=5.0)
    g2, _ = gw({"slow": slow}, {"draw": "slow"})
    task = asyncio.create_task(g2.generate(req()))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_each_call_leaves_a_trace_with_its_episode_and_cost():
    paid = FakeImageBackend("paid", caps=HOSTED, model="dall-e-3")
    g, traces = gw({"paid": paid}, {"draw": "paid"}, kinds={"paid": "openai"})
    result = await g.generate(req(quality="high", aspect="square", meta={"episode": "ep-42"}))
    # « high » n'est pas un mot de dall-e et la taille factice n'est pas 1024x1024 : le tarif standard hors carré
    assert result.cost_usd == pytest.approx(0.08)
    tr = traces[0]
    assert (tr.role, tr.backend, tr.model, tr.outcome, tr.correlation) == ("draw", "paid", "dall-e-3", "ok", "ep-42")
    assert tr.cost_usd == result.cost_usd
    free, ftraces = gw({"local": FakeImageBackend("local", caps=LOCAL)}, {"draw": "local"}, kinds={"local": "fake"})
    assert (await free.generate(req())).cost_usd == 0.0 and ftraces[0].correlation == "ep-1"
