"""Le tour AVEC outils consomme la forme structurée, plus l'aplatissement.

Le chemin sans outil était déjà structuré partout ; le chemin outillé, lui,
retombait sur ``ChatPrompt.legacy_pair()`` chez tous les providers sauf
Claude — seul à exposer ``complete_chat_with_tools`` à l'époque où le routeur
détectait cette capacité par ``hasattr``.

C'est pourtant le tour le plus cher du système : les déclarations d'outils
pèsent ~6 500 jetons et repartent à CHAQUE aller-retour de la boucle. Amorcée
sur deux chaînes, la boucle présentait un préfixe différent à chaque
itération — cache de préfixe annulé, historique privé de ses rôles
(« Assistant: … » redevient du texte que rien ne distingue de ce qu'un
utilisateur aurait tapé).

Ces tests pinnent, pour OpenAI, GLM et Ollama : la forme envoyée au premier
appel, le fait que le préfixe ne bouge pas d'un aller-retour à l'autre, que
la boucle d'outils marche toujours de bout en bout, et que l'aplatissement
n'est plus jamais calculé.
"""

from __future__ import annotations

import ast
import asyncio
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ai.chat import CONTEXT_HEADER, ChatPrompt

_BACKEND = Path(__file__).resolve().parent.parent


# ── Le tour de référence ─────────────────────────────────────────
# Deux locuteurs et plusieurs tours : le tampon court terme est partagé, donc
# un tour d'Alice arrive dans le prompt de Thomas et doit rester attribuable
# après traduction chez chaque provider.

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
        message="tu peux regarder mes mails ?",
    )


def _prompt(**overrides) -> ChatPrompt:
    return ChatPrompt(**{**_champs(), **overrides})


_ROLES_ATTENDUS = ["system", "user", "assistant", "user", "assistant", "user"]


class _PromptSansAplatissement(ChatPrompt):
    """Un tour dont l'aplatissement explose.

    Le seul témoin qui distingue « le provider rend la bonne forme » de
    « le provider rend la bonne forme mais calcule l'ancienne au passage ».
    """

    def legacy_pair(self):
        raise AssertionError("legacy_pair() appelé sur le chemin outillé")


# ── L'outil ──────────────────────────────────────────────────────

class _Outil:
    """Surface minimale d'un ``ModuleTool``."""

    def __init__(self, name: str = "list_recent_emails"):
        self.name = name
        self.description = "liste les derniers mails"
        self.recu: list = []

    def to_json_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    async def handler(self, args):
        self.recu.append(args)
        return {"mails": 2}


# ── Clients mockés ───────────────────────────────────────────────

def _fige(kwargs: dict) -> dict:
    """Photographie d'un appel.

    La boucle empile ses allers-retours dans une seule liste : sans copie,
    les deux requêtes enregistrées seraient le même objet et « le préfixe
    n'a pas bougé » serait vrai par construction.
    """
    fige = dict(kwargs)
    fige["messages"] = [dict(m) for m in kwargs.get("messages", [])]
    return fige


def _appel_openai(identifiant: str, nom: str, arguments: str):
    return SimpleNamespace(
        id=identifiant,
        type="function",
        function=SimpleNamespace(name=nom, arguments=arguments),
    )


def _reponse_openai(texte: str = "", tool_calls=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content=texte, tool_calls=tool_calls or [],
        ))],
        usage=SimpleNamespace(prompt_tokens=1234, completion_tokens=56),
    )


class _FakeOpenAIClient:
    """Surface minimale de ``AsyncOpenAI`` : rejoue un script, note les appels."""

    def __init__(self, reponses=None):
        self.requests: list[dict] = []
        self._reponses = list(reponses or [])

        async def create(**kwargs):
            self.requests.append(_fige(kwargs))
            if self._reponses:
                return self._reponses.pop(0)
            return _reponse_openai("ok")

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


def _appel_ollama(nom: str, arguments):
    return SimpleNamespace(function=SimpleNamespace(name=nom, arguments=arguments))


def _reponse_ollama(texte: str = "", tool_calls=None):
    return SimpleNamespace(
        message=SimpleNamespace(content=texte, tool_calls=tool_calls or []),
        prompt_eval_count=1234,
        eval_count=56,
    )


class _FakeOllamaClient:
    def __init__(self, reponses=None):
        self.requests: list[dict] = []
        self._reponses = list(reponses or [])

    async def chat(self, **kwargs):
        self.requests.append(_fige(kwargs))
        if self._reponses:
            return self._reponses.pop(0)
        return _reponse_ollama("ok")


def _openai(client=None):
    """Provider sans identifiants — ``__init__`` lit la configuration."""
    from ai.providers.openai_provider import OpenAIProvider

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._client = client or _FakeOpenAIClient()
    return provider


def _glm(client=None):
    from ai.providers.glm_provider import GLMProvider

    provider = GLMProvider.__new__(GLMProvider)
    provider._client = client or _FakeOpenAIClient()
    return provider


def _ollama(client=None):
    from ai.providers.ollama_provider import OllamaProvider

    provider = OllamaProvider.__new__(OllamaProvider)
    provider._host = "http://localhost:11434"
    provider._client = client or _FakeOllamaClient()
    return provider


def _config(valeurs: dict):
    """Patche le service de configuration dont Ollama tire sa politique."""
    def fake_get(key, default=None):
        if key in valeurs:
            return valeurs[key]
        raise KeyError(key)

    return patch("configs.service.config_service.get", side_effect=fake_get)


_POLITIQUE_OLLAMA = {
    "ai.ollama.thinking": False,
    "ai.ollama.max_reply_tokens": 768,
}


def _politique_ollama(provider):
    """Ollama lit sa politique de génération avant chaque appel."""
    from ai.providers.ollama_provider import OllamaProvider

    if isinstance(provider, OllamaProvider):
        return _config(_POLITIQUE_OLLAMA)
    return nullcontext()


def _lance(provider, prompt, tools, **kwargs):
    """Un tour outillé structuré, quel que soit le provider."""
    async def _tour():
        return await provider.complete_chat_with_tools(
            prompt, model="modele-x", tools=tools, **kwargs,
        )

    with _politique_ollama(provider):
        return asyncio.run(_tour())


def _messages_envoyes(provider, index: int = 0) -> list[dict]:
    return provider._client.requests[index]["messages"]


# =================================================================
# La forme envoyée — identique chez les trois
# =================================================================

@pytest.mark.parametrize("fabrique", [_openai, _glm, _ollama], ids=["openai", "glm", "ollama"])
class TestLaFormeDuPremierAppel:

    def test_un_tour_systeme_puis_de_vrais_tours(self, fabrique):
        provider = fabrique()
        texte, appeles = _lance(provider, _prompt(), [_Outil()])

        assert (texte, appeles) == ("ok", [])
        messages = _messages_envoyes(provider)
        assert messages[0] == {
            "role": "system", "content": _champs()["system_stable"],
        }
        assert [m["role"] for m in messages] == _ROLES_ATTENDUS
        # Rien n'est aplati : « Assistant: » comme texte est exactement ce que
        # la forme à deux chaînes produisait.
        assert not any("Assistant:" in m["content"] for m in messages)

    def test_le_tiers_reste_nomme_dans_son_tour(self, fabrique):
        provider = fabrique()
        _lance(provider, _prompt(), [_Outil()])

        messages = _messages_envoyes(provider)
        assert messages[3] == {"role": "user", "content": "Alice: moi c'est Alice"}

    def test_l_etat_volatil_voyage_dans_le_dernier_tour_user(self, fabrique):
        provider = fabrique()
        _lance(provider, _prompt(), [_Outil()])

        messages = _messages_envoyes(provider)
        volatile = _champs()["system_volatile"]
        assert messages[-1]["role"] == "user"
        assert CONTEXT_HEADER in messages[-1]["content"]
        assert volatile in messages[-1]["content"]
        assert _champs()["message"] in messages[-1]["content"]
        # Hors du système, sinon l'état du tour invalide le préfixe cacheable
        # à chaque tour — et la frontière ne sert plus à rien.
        assert volatile not in messages[0]["content"]
        assert not any(CONTEXT_HEADER in m["content"] for m in messages[:-1])

    def test_les_outils_declares_partent_avec(self, fabrique):
        provider = fabrique()
        _lance(provider, _prompt(), [_Outil()])

        declares = provider._client.requests[0]["tools"]
        assert [d["function"]["name"] for d in declares] == ["list_recent_emails"]


# =================================================================
# La boucle elle-même — toujours fonctionnelle
# =================================================================

class TestLaBoucleTourneEncore:
    """Un ``tool_call`` exécuté, son résultat réinjecté, la réponse finale
    et les noms d'outils remontés."""

    def test_openai(self):
        outil = _Outil()
        client = _FakeOpenAIClient([
            _reponse_openai("", [_appel_openai("tc_1", outil.name, '{"limite": 3}')]),
            _reponse_openai("tu as 2 mails"),
        ])
        provider = _openai(client)

        texte, appeles = _lance(provider, _prompt(), [outil])

        assert texte == "tu as 2 mails"
        assert appeles == [outil.name]
        assert outil.recu == [{"limite": 3}]
        deuxieme = _messages_envoyes(provider, 1)
        assert deuxieme[-2]["role"] == "assistant"
        assert deuxieme[-1] == {
            "role": "tool", "tool_call_id": "tc_1", "content": '{"mails": 2}',
        }

    def test_glm(self):
        outil = _Outil()
        client = _FakeOpenAIClient([
            _reponse_openai("", [_appel_openai("tc_9", outil.name, "{}")]),
            _reponse_openai("voilà"),
        ])
        provider = _glm(client)

        texte, appeles = _lance(provider, _prompt(), [outil])

        assert (texte, appeles) == ("voilà", [outil.name])
        assert _messages_envoyes(provider, 1)[-1]["role"] == "tool"

    def test_ollama(self):
        outil = _Outil()
        client = _FakeOllamaClient([
            _reponse_ollama("", [_appel_ollama(outil.name, {"limite": 3})]),
            _reponse_ollama("tu as 2 mails"),
        ])
        provider = _ollama(client)

        texte, appeles = _lance(provider, _prompt(), [outil])

        assert texte == "tu as 2 mails"
        assert appeles == [outil.name]
        assert outil.recu == [{"limite": 3}]
        assert _messages_envoyes(provider, 1)[-1] == {
            # ``tool_name`` : le champ du SDK ollama — ``name`` était
            # silencieusement jeté par pydantic, résultat anonyme pour le modèle.
            "role": "tool", "tool_name": outil.name, "content": '{"mails": 2}',
        }

    @pytest.mark.parametrize(
        "fabrique, client, reponses",
        [
            (_openai, _FakeOpenAIClient, [
                _reponse_openai("", [_appel_openai("tc_1", "list_recent_emails", "{}")]),
                _reponse_openai("fini"),
            ]),
            (_glm, _FakeOpenAIClient, [
                _reponse_openai("", [_appel_openai("tc_1", "list_recent_emails", "{}")]),
                _reponse_openai("fini"),
            ]),
            (_ollama, _FakeOllamaClient, [
                _reponse_ollama("", [_appel_ollama("list_recent_emails", {})]),
                _reponse_ollama("fini"),
            ]),
        ],
        ids=["openai", "glm", "ollama"],
    )
    def test_le_prefixe_ne_bouge_pas_d_un_aller_retour_a_l_autre(
        self, fabrique, client, reponses,
    ):
        """La raison d'être du correctif : la boucle rappelle le modèle une
        fois par outil, et un préfixe qui change à chaque itération refacture
        les ~6 500 jetons de déclarations à chaque fois."""
        provider = fabrique(client(reponses))
        _lance(provider, _prompt(), [_Outil()])

        premier = _messages_envoyes(provider, 0)
        deuxieme = _messages_envoyes(provider, 1)
        assert deuxieme[: len(premier)] == premier
        assert len(deuxieme) > len(premier)


# =================================================================
# L'objectif lui-même : plus un provider ne consomme l'aplatissement
# =================================================================

class TestPlusDAplatissement:

    def test_les_trois_exposent_complete_chat_with_tools(self):
        """C'est ce que le routeur appelle — sans lui, aucun des tests
        ci-dessus ne dit quoi que ce soit du chemin réel."""
        from ai.providers.glm_provider import GLMProvider
        from ai.providers.ollama_cloud_provider import OllamaCloudProvider
        from ai.providers.ollama_provider import OllamaProvider
        from ai.providers.openai_provider import OpenAIProvider

        for cls in (OpenAIProvider, GLMProvider, OllamaProvider, OllamaCloudProvider):
            assert hasattr(cls, "complete_chat_with_tools"), cls.__name__

    @pytest.mark.parametrize(
        "fabrique", [_openai, _glm, _ollama], ids=["openai", "glm", "ollama"],
    )
    def test_le_chemin_outille_n_appelle_pas_l_aplatissement(self, fabrique):
        prompt = _PromptSansAplatissement(**_champs())
        texte, _ = _lance(fabrique(), prompt, [_Outil()])
        assert texte == "ok"

    def test_aucun_module_provider_ne_nomme_legacy_pair(self):
        offenders = []
        for chemin in sorted((_BACKEND / "ai" / "providers").glob("*.py")):
            tree = ast.parse(chemin.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                nommé = (
                    isinstance(node, ast.Attribute) and node.attr == "legacy_pair"
                ) or (
                    isinstance(node, ast.Name) and node.id == "legacy_pair"
                )
                if nommé:
                    offenders.append(f"{chemin.name}:{node.lineno}")
        assert offenders == []

    def test_un_seul_corps_de_boucle_compatible_openai(self):
        """Une amorce, un corps : la boucle vit dans ``_tool_loop`` et ce
        module n'y branche qu'un adaptateur — il ne recopie ni l'appel
        (c'est ``create_chat_completion`` qui rejoue une requête refusée pour
        ``max_tokens`` ou ``temperature``), ni l'itération."""
        source = ast.parse(
            (_BACKEND / "ai" / "providers" / "_openai_tools.py").read_text("utf-8")
        )
        corps = {
            fonction.name for fonction in ast.walk(source)
            if isinstance(fonction, ast.AsyncFunctionDef)
            and any(
                isinstance(noeud, ast.Call)
                and ast.unparse(noeud.func).endswith("chat.completions.create")
                for noeud in ast.walk(fonction)
            )
        }
        assert corps == {"create_chat_completion"}
        appeler = next(
            f for f in ast.walk(source)
            if isinstance(f, ast.AsyncFunctionDef) and f.name == "appeler"
        )
        appelle = {
            ast.unparse(n.func).rsplit(".", 1)[-1]
            for n in ast.walk(appeler) if isinstance(n, ast.Call)
        }
        assert "create_chat_completion" in appelle


# =================================================================
# Ollama : la politique de génération vaut aussi sur ce chemin
# =================================================================

class TestPolitiqueOllama:

    def test_le_plafond_de_jetons_s_applique(self):
        """Le plus gros consommateur du système est aussi celui où la corde de
        4096 jetons par aller-retour coûte le plus cher."""
        provider = _ollama()
        with _config(_POLITIQUE_OLLAMA):
            asyncio.run(provider.complete_chat_with_tools(
                _prompt(), model="gemma4:12b", tools=[_Outil()], max_tokens=4096,
            ))

        kwargs = provider._client.requests[0]
        assert kwargs["options"]["num_predict"] == 768
        assert kwargs["think"] is False

    def test_un_budget_appelant_plus_petit_gagne_toujours(self):
        provider = _ollama()
        with _config(_POLITIQUE_OLLAMA):
            asyncio.run(provider.complete_chat_with_tools(
                _prompt(), model="gemma4:12b", tools=[_Outil()], max_tokens=100,
            ))

        assert provider._client.requests[0]["options"]["num_predict"] == 100

    def test_une_configuration_illisible_plafonne_quand_meme(self):
        provider = _ollama()
        with patch("configs.service.config_service.get",
                   side_effect=RuntimeError("db down")):
            asyncio.run(provider.complete_chat_with_tools(
                _prompt(), model="gemma4:12b", tools=[_Outil()], max_tokens=4096,
            ))

        kwargs = provider._client.requests[0]
        assert kwargs["options"]["num_predict"] == 768
        assert kwargs["think"] is False

    def test_ollama_cloud_lit_ses_propres_clés(self):
        """Le provider hébergé hérite de la boucle ; il ne doit pas hériter du
        plafond calibré pour une RTX 3060."""
        from ai.providers.ollama_cloud_provider import OllamaCloudProvider

        provider = OllamaCloudProvider.__new__(OllamaCloudProvider)
        provider._host = "https://ollama.com"
        provider._client = _FakeOllamaClient()
        with _config({"ai.ollama_cloud.thinking": False,
                      "ai.ollama_cloud.max_reply_tokens": 2048}):
            asyncio.run(provider.complete_chat_with_tools(
                _prompt(), model="gpt-oss:120b", tools=[_Outil()], max_tokens=4096,
            ))

        assert provider._client.requests[0]["options"]["num_predict"] == 2048


# =================================================================
# Bout en bout par le routeur, sans y toucher
# =================================================================

@pytest.fixture()
def routeur(monkeypatch):
    """Routeur réduit à sa mécanique d'appel, sans configuration ni quota."""
    from ai import router as router_mod

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
    """Bout en bout : ``AIRouter.chat_with_tools`` tend la forme structurée."""

    @pytest.mark.parametrize(
        "fabrique", [_openai, _glm, _ollama], ids=["openai", "glm", "ollama"],
    )
    def test_le_provider_recoit_de_vrais_tours(self, fabrique, routeur, monkeypatch):
        r, router_mod = routeur
        provider = fabrique()
        monkeypatch.setattr(
            router_mod.AIRouter, "_get_provider", lambda self, name: provider,
        )

        async def _tour():
            return await r.chat_with_tools(
                router_mod.AIRole.CONVERSATION_TOOLS, _prompt(), [_Outil()],
            )

        if fabrique is _ollama:
            with _config(_POLITIQUE_OLLAMA):
                texte, appeles = asyncio.run(_tour())
        else:
            texte, appeles = asyncio.run(_tour())

        assert (texte, appeles) == ("ok", [])
        assert [m["role"] for m in _messages_envoyes(provider)] == _ROLES_ATTENDUS
