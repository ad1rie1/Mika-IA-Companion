"""Ce qu'un fournisseur dit de ses modèles (ADR 0136), sans réseau :

- la liste de l'API Claude donne la fenêtre et la plus longue réponse de chaque modèle ;
- le modèle choisi se lit chez son fournisseur : ``/v1/models/{id}`` (Claude), ``/api/show`` (Ollama, local et
  Cloud), la liste d'un compatible OpenAI qui le dit ; Claude Code n'est jamais interrogé ; un nombre douteux
  n'est pas cru ; une panne lève ``ListingFailed`` en français, sans la clé ;
- la fiche garde ce qui a été lu pour son modèle : le contexte et la sortie max. y sont ramenés, jamais relevés ;
  au-delà pour un modèle lu, refusés ; un autre modèle oublie ce qui a été lu ;
- ``settle_limits`` ne demande que les modèles pas encore lus, et dit ce qu'il a lu ou changé.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from mika.adapters.llm.config import BackendSpec, LLMConfig, ModelLimits
from mika.adapters.llm.models import ListingFailed, list_models, model_limits, settle_limits

KEY = "sk-ant-CANARI-fenetre-42"


def client(handler, seen: list[httpx.Request] | None = None) -> httpx.AsyncClient:
    def record(r: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(r)
        return handler(r)

    return httpx.AsyncClient(transport=httpx.MockTransport(record))


def claude(**kw) -> BackendSpec:
    return BackendSpec(**{"kind": "claude", "model": "claude-sonnet-5-5", "api_key": KEY, **kw})


def ollama(**kw) -> BackendSpec:
    return BackendSpec(**{"kind": "ollama", "model": "gemma3:4b", **kw})


async def test_the_claude_listing_says_the_window_and_the_longest_reply_of_each_model():
    payload = {"data": [{"id": "claude-sonnet-5-5", "max_input_tokens": 1_000_000, "max_tokens": 128_000},
                        {"id": "claude-haiku-4-5", "max_input_tokens": 200_000, "max_tokens": 64_000},
                        {"id": "ancien"}]}
    seen: list[httpx.Request] = []
    got = await list_models(claude(), client=client(lambda r: httpx.Response(200, json=payload), seen))
    assert got == [("ancien", ModelLimits()), ("claude-haiku-4-5", ModelLimits(200_000, 64_000)),
                   ("claude-sonnet-5-5", ModelLimits(1_000_000, 128_000))]
    assert seen[0].headers["x-api-key"] == KEY
    assert [name for name, _ in await list_models(BackendSpec(kind="claude_code", model=""))] == \
        ["fable", "haiku", "opus", "sonnet"]


async def test_the_chosen_claude_model_is_read_at_its_own_address():
    seen: list[httpx.Request] = []
    http = client(lambda r: httpx.Response(200, json={"id": "claude-sonnet-5-5", "max_input_tokens": 1_000_000,
                                                      "max_tokens": 128_000}), seen)
    assert await model_limits(claude(), client=http) == ModelLimits(1_000_000, 128_000)
    assert seen[0].method == "GET" and seen[0].url.path == "/v1/models/claude-sonnet-5-5"
    # un nom ne sort jamais de son segment d'adresse
    await model_limits(claude(model="a/../b"), client=http)
    assert seen[1].url.raw_path.endswith(b"/v1/models/a%2F..%2Fb")


async def test_ollama_says_the_window_in_its_model_card_local_and_cloud():
    seen: list[httpx.Request] = []
    card = {"model_info": {"general.architecture": "gemma3", "gemma3.context_length": 131_072,
                           "gemma3.embedding_length": 2560}}
    http = client(lambda r: httpx.Response(200, json=card), seen)
    assert await model_limits(ollama(), client=http) == ModelLimits(window=131_072)
    assert seen[0].method == "POST" and str(seen[0].url) == "http://localhost:11434/api/show"
    assert json.loads(seen[0].content) == {"model": "gemma3:4b"} and "authorization" not in seen[0].headers
    await model_limits(BackendSpec(kind="ollama_cloud", model="gpt-oss:120b", api_key=KEY), client=http)
    assert str(seen[1].url) == "https://ollama.com/api/show" and seen[1].headers["authorization"] == f"Bearer {KEY}"
    # une carte sans fenêtre : rien de lu, sans panne
    bare = client(lambda r: httpx.Response(200, json={"model_info": {"llama.block_count": 32}}))
    assert await model_limits(ollama(), client=bare) == ModelLimits()


async def test_an_openai_compatible_server_says_it_in_its_listing_or_says_nothing():
    router = {"data": [{"id": "autre", "context_length": 8_192},
                       {"id": "qwen/qwen3", "context_length": 262_144,
                        "top_provider": {"max_completion_tokens": 32_768}}]}
    vllm = {"data": [{"id": "qwen/qwen3", "max_model_len": 40_960}]}
    openai = {"data": [{"id": "qwen/qwen3", "owned_by": "openai"}]}
    spec = BackendSpec(kind="openai", model="qwen/qwen3", api_key=KEY, base_url="http://127.0.0.1:8000/v1")
    assert await model_limits(spec, client=client(lambda r: httpx.Response(200, json=router))) == \
        ModelLimits(262_144, 32_768)
    assert await model_limits(spec, client=client(lambda r: httpx.Response(200, json=vllm))) == ModelLimits(40_960)
    assert await model_limits(spec, client=client(lambda r: httpx.Response(200, json=openai))) == ModelLimits()


async def test_claude_code_is_never_asked_and_a_doubtful_number_is_not_believed():
    seen: list[httpx.Request] = []
    http = client(lambda r: httpx.Response(200, json={}), seen)
    assert await model_limits(BackendSpec(kind="claude_code", model="sonnet"), client=http) == ModelLimits()
    assert seen == []
    for doubtful in (True, -5, 0, 50_000_000, "200000", 1.5e5):
        answer = {"max_input_tokens": doubtful, "max_tokens": doubtful}
        assert await model_limits(claude(), client=client(lambda r, a=answer: httpx.Response(200, json=a))) == \
            ModelLimits()


async def test_a_provider_that_fails_says_why_in_french_without_the_key():
    with pytest.raises(ListingFailed, match="clé"):
        await model_limits(claude(api_key=""))
    for status, said in ((401, "Clé refusée"), (404, "répondu 404")):
        with pytest.raises(ListingFailed, match=said) as exc:
            await model_limits(claude(), client=client(lambda r, s=status: httpx.Response(s)))
        assert KEY not in str(exc.value)

    def down(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refusé", request=r)

    with pytest.raises(ListingFailed, match="injoignable"):
        await model_limits(ollama(), client=client(down))
    with pytest.raises(ListingFailed, match="illisible"):
        await model_limits(ollama(), client=client(lambda r: httpx.Response(200, text="<html>")))


def test_the_spec_keeps_what_was_read_and_lowers_never_raises():
    big = claude(context_tokens=40_000, max_output_tokens=8_000)
    fitted, said = big.fitted(ModelLimits(1_000_000, 128_000))
    assert (fitted.context_tokens, fitted.max_output_tokens) == (40_000, 8_000) and said == []
    assert (fitted.detected_window, fitted.detected_output, fitted.detected_for) == \
        (1_000_000, 128_000, "claude:claude-sonnet-5-5")
    small, said = ollama(context_tokens=24_000, max_output_tokens=12_000).fitted(ModelLimits(8_192))
    assert (small.context_tokens, small.max_output_tokens) == (8_192, 4_096)
    assert said == ["contexte ramené à 8 192 jetons, la fenêtre du modèle", "sortie max. ramenée à 4 096 jetons"]
    capped, said = ollama(context_tokens=24_000, max_output_tokens=12_000).fitted(ModelLimits(131_072, 4_096))
    assert (capped.context_tokens, capped.max_output_tokens) == (24_000, 4_096)
    # une fenêtre plus petite que ce qu'elle peut déclarer n'est pas gardée : le contexte ne descend pas dessous
    tiny, said = ollama().fitted(ModelLimits(1_024))
    assert tiny.detected_window == 0 and tiny.context_tokens == 24_000 and "trop petite" in said[0]


def test_a_read_model_refuses_more_and_another_model_forgets_what_was_read():
    read, _ = ollama(context_tokens=8_000).fitted(ModelLimits(8_192))
    raw = read.model_dump()
    with pytest.raises(ValidationError, match="dépasse la fenêtre de ce modèle"):
        BackendSpec.model_validate({**raw, "context_tokens": 9_000})
    other = BackendSpec.model_validate({**raw, "model": "qwen3:8b", "context_tokens": 40_000})
    assert (other.detected_window, other.detected_for, other.context_tokens) == (0, "", 40_000)
    # le même nom chez un autre type de fournisseur n'est pas le même modèle
    cloud = BackendSpec.model_validate({**raw, "kind": "ollama_cloud"})
    assert cloud.detected_window == 0 and cloud.detected_for == ""
    with pytest.raises(ValidationError, match="plus longue réponse"):
        BackendSpec.model_validate({**claude().fitted(ModelLimits(1_000_000, 4_096))[0].model_dump(),
                                    "max_output_tokens": 8_000})


async def test_settling_asks_only_the_models_not_yet_read_and_says_what_it_did():
    asked: list[str] = []

    async def read(spec: BackendSpec) -> ModelLimits:
        asked.append(spec.model)
        if spec.kind == "ollama_cloud":
            raise ListingFailed("Fournisseur injoignable (ConnectError).")
        return {"gemma3:4b": ModelLimits(8_192), "claude-sonnet-5-5": ModelLimits(1_000_000, 128_000)}.get(
            spec.model, ModelLimits())

    known, _ = claude(model="claude-opus-5-5").fitted(ModelLimits(1_000_000, 128_000))
    cfg = LLMConfig(backends={"local": ollama(), "api": claude(), "deja": known,
                              "cli": BackendSpec(kind="claude_code", model="sonnet"),
                              "loin": BackendSpec(kind="ollama_cloud", model="gpt-oss:120b", api_key=KEY)})
    settled, notes = await settle_limits(cfg, read)
    assert sorted(asked) == ["claude-sonnet-5-5", "gemma3:4b", "gpt-oss:120b", "sonnet"]
    assert settled.backends["local"].context_tokens == 8_192
    assert settled.backends["api"].context_tokens == 40_000  # jamais relevé jusqu'au million
    assert settled.backends["cli"].detected_for == "claude_code:sonnet"  # demandé : il ne le dit pas
    assert settled.backends["loin"].detected_for == ""  # pas lu : redemandé la prochaine fois
    assert notes == ["« local » : fenêtre du modèle 8 192 jetons ; contexte ramené à 8 192 jetons, la fenêtre du "
                     "modèle.",
                     "« api » : fenêtre du modèle 1 000 000 jetons, réponse 128 000.",
                     "« loin » : fenêtre du modèle non lue (Fournisseur injoignable (ConnectError)) ; elle le sera "
                     "au prochain enregistrement."]
    asked.clear()
    again, notes = await settle_limits(settled, read)
    assert asked == ["gpt-oss:120b"] and again.backends["local"] == settled.backends["local"]
