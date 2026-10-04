"""GLM et Gemini consomment le tour structuré, plus l'aplatissement.

Les deux back-ends ont une vraie API de conversation, mais aucun des deux
n'exposait ``complete_chat`` : le routeur, qui bascule sur ``hasattr``, les
faisait retomber sur ``ChatPrompt.legacy_pair()``. L'historique y perdait
ses rôles (« Assistant: … » redevient du texte que rien ne distingue d'un
utilisateur qui l'aurait tapé) et le découpage stable/volatil — la seule
raison d'être de la frontière de cache — ne servait à rien.

Ces tests pinnent la forme envoyée à chacune des deux API, et le fait que
le chemin de conversation des deux providers ne touche plus l'aplatissement.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from old.backend.ai.chat import CONTEXT_HEADER, ChatPrompt

_BACKEND = Path(__file__).resolve().parent.parent


# ── Le tour de référence ─────────────────────────────────────────
# Deux locuteurs et plusieurs tours : le tampon court terme est partagé,
# donc un tour d'Alice arrive dans le prompt de Thomas et doit rester
# attribuable après traduction chez chaque provider.

def _champs() -> dict:
    return dict(
        system_stable=(
            "Tu es Mika.\n--- QUI TU ES DEVENUE ---\nUne présence têtue."
        ),
        system_volatile="--- TON ETAT EMOTIONNEL ACTUEL ---\ncurieuse (0.6)",
        history=[
            {"role": "user", "content": "salut Mika", "speaker": "Thomas"},
            {"role": "assistant", "content": "coucou Thomas !"},
            {"role": "user", "content": "moi c'est Alice", "speaker": "Alice"},
            {"role": "assistant", "content": "enchantée Alice"},
        ],
        message="tu te rappelles de quoi on parlait ?",
    )


def _prompt(**overrides) -> ChatPrompt:
    return ChatPrompt(**{**_champs(), **overrides})


class _PromptSansAplatissement(ChatPrompt):
    """Un tour dont l'aplatissement explose.

    Le seul témoin qui distingue « le provider rend la bonne forme » de
    « le provider rend la bonne forme mais calcule l'ancienne au passage ».
    """

    def legacy_pair(self):
        raise AssertionError("legacy_pair() appelé sur le chemin de conversation")


# ── Clients mockés ───────────────────────────────────────────────

class _FakeOpenAIClient:
    """Surface minimale de ``AsyncOpenAI`` : enregistre les appels."""

    def __init__(self):
        self.requests: list[dict] = []

        async def create(**kwargs):
            self.requests.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=SimpleNamespace(prompt_tokens=1234, completion_tokens=56),
            )

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


class _FakeGeminiClient:
    """Surface minimale de ``genai.Client().aio`` : enregistre les appels."""

    def __init__(self):
        self.requests: list[dict] = []

        async def generate_content(**kwargs):
            self.requests.append(kwargs)
            return SimpleNamespace(
                text="ok",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=1234, candidates_token_count=56,
                ),
            )

        self.aio = SimpleNamespace(
            models=SimpleNamespace(generate_content=generate_content),
        )


def _glm(client=None):
    """Provider GLM sans identifiants — ``__init__`` lit la configuration."""
    from old.backend.ai.providers.glm_provider import GLMProvider

    provider = GLMProvider.__new__(GLMProvider)
    provider._client = client or _FakeOpenAIClient()
    return provider


def _gemini(client=None):
    from old.backend.ai.providers.gemini_provider import GeminiProvider

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._client = client or _FakeGeminiClient()
    return provider


def _textes(content) -> str:
    return "".join(part.text or "" for part in content.parts)


def _usage_de(provider, model: str) -> dict | None:
    """Usage relevé par l'appel, lu depuis SA tâche.

    ``set_usage`` écrit dans un ContextVar : lu depuis la tâche appelante,
    l'écriture faite dans la tâche de ``asyncio.run`` serait invisible — et
    le test échouerait pour une raison qui n'a rien à voir avec le provider.
    """
    from old.backend.ai.quota import _reset_usage, _take_usage

    async def _tour():
        _reset_usage()
        await provider.complete_chat(_prompt(), model=model)
        return _take_usage()

    return asyncio.run(_tour())


# =================================================================
# GLM — endpoint compatible OpenAI
# =================================================================

class TestGLMChatNatif:

    def test_un_tour_systeme_puis_de_vrais_tours(self):
        provider = _glm()
        out = asyncio.run(provider.complete_chat(_prompt(), model="glm-4"))

        assert out == "ok"
        messages = provider._client.requests[0]["messages"]
        assert messages[0] == {
            "role": "system", "content": _champs()["system_stable"],
        }
        assert [m["role"] for m in messages[1:]] == [
            "user", "assistant", "user", "assistant", "user",
        ]
        # Rien n'est aplati : « Assistant: » comme texte est exactement ce
        # que la forme à deux chaînes produisait.
        assert not any("Assistant:" in m["content"] for m in messages)

    def test_le_tiers_reste_nomme_dans_son_tour(self):
        provider = _glm()
        asyncio.run(provider.complete_chat(_prompt(), model="glm-4"))

        messages = provider._client.requests[0]["messages"]
        assert messages[3] == {"role": "user", "content": "Alice: moi c'est Alice"}

    def test_l_etat_volatil_voyage_dans_le_dernier_tour_user(self):
        provider = _glm()
        asyncio.run(provider.complete_chat(_prompt(), model="glm-4"))

        messages = provider._client.requests[0]["messages"]
        volatile = _champs()["system_volatile"]
        assert CONTEXT_HEADER in messages[-1]["content"]
        assert volatile in messages[-1]["content"]
        assert _champs()["message"] in messages[-1]["content"]
        # Hors du préfixe cacheable, sinon l'état du tour l'invalide à chaque
        # tour et la frontière ne sert à rien.
        assert volatile not in messages[0]["content"]
        assert not any(CONTEXT_HEADER in m["content"] for m in messages[:-1])

    def test_les_parametres_de_generation_partent_avec(self):
        provider = _glm()
        asyncio.run(provider.complete_chat(
            _prompt(), model="glm-4.6", max_tokens=1024, temperature=0.3,
        ))

        request = provider._client.requests[0]
        assert request["model"] == "glm-4.6"
        assert request["max_tokens"] == 1024
        assert request["temperature"] == 0.3

    def test_l_usage_natif_remonte_au_quota(self):
        assert _usage_de(_glm(), "glm-4") == {"in": 1234, "out": 56}


# =================================================================
# Gemini — system_instruction + contents
# =================================================================

class TestGeminiChatNatif:

    def test_le_prefixe_stable_devient_system_instruction(self):
        provider = _gemini()
        out = asyncio.run(provider.complete_chat(_prompt(), model="gemini-2.5-pro"))

        assert out == "ok"
        config = provider._client.requests[0]["config"]
        assert config.system_instruction == _champs()["system_stable"]
        assert _champs()["system_volatile"] not in (config.system_instruction or "")

    def test_le_role_assistant_est_traduit_en_model(self):
        provider = _gemini()
        asyncio.run(provider.complete_chat(_prompt(), model="gemini-2.5-pro"))

        contents = provider._client.requests[0]["contents"]
        assert [c.role for c in contents] == [
            "user", "model", "user", "model", "user",
        ]
        assert _textes(contents[1]) == "coucou Thomas !"

    def test_contents_n_ouvre_jamais_sur_un_tour_model(self):
        """Gemini refuse un ``contents`` commençant par ``model``.

        ``chat_messages()`` porte déjà la garde (marqueur de reprise) : ce
        test dit qu'elle traverse bien la traduction des rôles, pour qu'une
        garde en double ne soit pas rajoutée ici « au cas où ».
        """
        from old.backend.ai.chat import _RESUME_MARKER

        provider = _gemini()
        asyncio.run(provider.complete_chat(
            _prompt(history=[{"role": "assistant", "content": "tiens, salut"}]),
            model="gemini-2.5-pro",
        ))

        contents = provider._client.requests[0]["contents"]
        assert contents[0].role == "user"
        assert _textes(contents[0]) == _RESUME_MARKER
        assert contents[1].role == "model"

    def test_l_etat_volatil_voyage_dans_le_dernier_tour(self):
        provider = _gemini()
        asyncio.run(provider.complete_chat(_prompt(), model="gemini-2.5-pro"))

        contents = provider._client.requests[0]["contents"]
        dernier = _textes(contents[-1])
        assert CONTEXT_HEADER in dernier
        assert _champs()["system_volatile"] in dernier
        assert not any(CONTEXT_HEADER in _textes(c) for c in contents[:-1])

    def test_les_parametres_de_generation_partent_avec(self):
        provider = _gemini()
        asyncio.run(provider.complete_chat(
            _prompt(), model="gemini-2.5-flash", max_tokens=1024, temperature=0.3,
        ))

        request = provider._client.requests[0]
        assert request["model"] == "gemini-2.5-flash"
        assert request["config"].max_output_tokens == 1024
        assert request["config"].temperature == 0.3

    def test_l_usage_natif_remonte_au_quota(self):
        assert _usage_de(_gemini(), "gemini-2.5-pro") == {"in": 1234, "out": 56}


# =================================================================
# L'objectif lui-même : plus un provider ne consomme l'aplatissement
# =================================================================

class TestPlusDAplatissement:

    def test_les_deux_exposent_complete_chat(self):
        """C'est ce que le routeur appelle — sans lui, aucun des tests
        ci-dessus ne dit quoi que ce soit du chemin réel."""
        from old.backend.ai.providers.gemini_provider import GeminiProvider
        from old.backend.ai.providers.glm_provider import GLMProvider

        for cls in (GLMProvider, GeminiProvider):
            assert hasattr(cls, "complete_chat"), cls.__name__

    @pytest.mark.parametrize("provider_factory", [_glm, _gemini])
    def test_le_chemin_de_conversation_n_appelle_pas_l_aplatissement(
        self, provider_factory,
    ):
        prompt = _PromptSansAplatissement(**_champs())
        provider = provider_factory()
        assert asyncio.run(provider.complete_chat(prompt, model="m")) == "ok"

    def test_aucun_des_deux_modules_ne_nomme_legacy_pair(self):
        offenders = []
        for relative in (
            "ai/providers/glm_provider.py",
            "ai/providers/gemini_provider.py",
        ):
            tree = ast.parse((_BACKEND / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                nommé = (
                    isinstance(node, ast.Attribute) and node.attr == "legacy_pair"
                ) or (
                    isinstance(node, ast.Name) and node.id == "legacy_pair"
                )
                if nommé:
                    offenders.append(f"{relative}:{node.lineno}")
        assert offenders == []


# =================================================================
# Bout en bout par le routeur, sans y toucher
# =================================================================

@pytest.fixture()
def routeur(monkeypatch):
    """Routeur réduit à sa mécanique d'appel, sans configuration ni quota."""
    from old.backend.ai import router as router_mod

    r = router_mod.AIRouter.__new__(router_mod.AIRouter)
    r._providers = {}
    r._role_to_internal = {}
    r._semaphore_loop = None
    r._semaphores = {}
    r._declared_models = {
        "stub": {
            "provider": "stub", "model_id": "model-x",
            "temperature": 0.7, "max_tokens": 2048,
        },
    }
    monkeypatch.setattr(
        router_mod.AIRouter, "_resolve",
        lambda self, role: ("stub", "model-x", 0.7, "stub"),
    )
    monkeypatch.setattr(
        router_mod.AIRouter, "_call_timeout", lambda self, o: 5.0,
    )
    monkeypatch.setattr(router_mod.quota_tracker, "check", lambda **kw: None)
    monkeypatch.setattr(router_mod.quota_tracker, "record", lambda **kw: 0.0)
    return r, router_mod


class TestRouteurDonneLaFormeStructuree:
    """Bout en bout : ces deux tours passent par ``AIRouter.chat``."""

    def test_glm_recoit_de_vrais_tours(self, routeur, monkeypatch):
        r, router_mod = routeur
        provider = _glm()
        monkeypatch.setattr(
            router_mod.AIRouter, "_get_provider", lambda self, name: provider,
        )

        out = asyncio.run(r.chat(router_mod.AIRole.CONVERSATION, _prompt()))

        assert out == "ok"
        messages = provider._client.requests[0]["messages"]
        assert [m["role"] for m in messages] == [
            "system", "user", "assistant", "user", "assistant", "user",
        ]

    def test_gemini_recoit_de_vrais_tours(self, routeur, monkeypatch):
        r, router_mod = routeur
        provider = _gemini()
        monkeypatch.setattr(
            router_mod.AIRouter, "_get_provider", lambda self, name: provider,
        )

        out = asyncio.run(r.chat(router_mod.AIRole.CONVERSATION, _prompt()))

        assert out == "ok"
        request = provider._client.requests[0]
        assert request["config"].system_instruction == _champs()["system_stable"]
        assert [c.role for c in request["contents"]] == [
            "user", "model", "user", "model", "user",
        ]
