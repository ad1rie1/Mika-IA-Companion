"""Gemini : le tour outillé consomme la forme structurée, plus l'aplatissement.

Gemini exposait ``complete_chat`` mais pas ``complete_chat_with_tools`` — et
c'est sur ce second ``hasattr`` que ``AIRouter.chat_with_tools`` bascule. Son
tour outillé, le plus cher du système (les déclarations repartent à CHAQUE
aller-retour de la boucle), retombait donc sur ``ChatPrompt.legacy_pair()`` :
un préfixe différent à chaque itération, et un historique privé de ses rôles
(« Assistant: … » redevient du texte que rien ne distingue de ce qu'un
utilisateur aurait tapé).

Ces tests pinnent la forme envoyée au premier appel, la stabilité du préfixe
d'un aller-retour à l'autre, la boucle de bout en bout, et le fait que
l'aplatissement n'est plus jamais calculé.

Le client est mocké : aucun appel réseau, mais les objets ``google.genai.types``
sont les vrais — c'est le SDK qui refuse un ``contents`` mal formé, pas nous.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai.chat import CONTEXT_HEADER, ChatPrompt

_BACKEND = Path(__file__).resolve().parent.parent


# ── Le tour de référence ─────────────────────────────────────────
# Deux locuteurs et plusieurs tours : le tampon court terme est partagé, donc
# un tour d'Alice arrive dans le prompt de Thomas et doit rester attribuable
# après traduction chez Gemini.

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


# Gemini nomme « model » ce que le dépôt appelle « assistant ».
_ROLES_ATTENDUS = ["user", "model", "user", "model", "user"]


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


# ── Client mocké ─────────────────────────────────────────────────

def _fige_part(part) -> tuple:
    """Une part réduite à des données inertes."""
    call = getattr(part, "function_call", None)
    if call is not None:
        return ("call", call.name, dict(call.args or {}))
    reponse = getattr(part, "function_response", None)
    if reponse is not None:
        return ("response", reponse.name, dict(reponse.response or {}))
    return ("text", part.text)


def _fige(kwargs: dict) -> dict:
    """Photographie d'un appel.

    La boucle empile ses allers-retours dans une seule liste : notée par
    référence, les deux requêtes enregistrées seraient le même objet et
    « le préfixe n'a pas bougé » serait vrai par construction. On projette
    donc chaque ``Content`` sur des tuples, sans lien avec les objets vivants.
    """
    config = kwargs.get("config")
    return {
        "model": kwargs.get("model"),
        "system_instruction": getattr(config, "system_instruction", None),
        "tools": getattr(config, "tools", None),
        "contents": [
            (c.role, [_fige_part(p) for p in (c.parts or [])])
            for c in kwargs.get("contents", [])
        ],
    }


def _appel_gemini(nom: str, args: dict):
    from google.genai import types

    return types.FunctionCall(name=nom, args=args)


def _reponse(texte: str = "", function_calls=None):
    """Surface minimale d'une ``GenerateContentResponse``."""
    from google.genai import types

    candidates = []
    if function_calls:
        candidates = [SimpleNamespace(content=types.Content(
            role="model",
            parts=[types.Part(function_call=fc) for fc in function_calls],
        ))]
    return SimpleNamespace(
        text=texte,
        function_calls=function_calls or [],
        candidates=candidates,
        usage_metadata=SimpleNamespace(
            prompt_token_count=1234, candidates_token_count=56,
        ),
    )


class _FakeGeminiClient:
    """Surface minimale de ``genai.Client`` : rejoue un script, note les appels."""

    def __init__(self, reponses=None):
        self.requests: list[dict] = []
        self._reponses = list(reponses or [])

        async def generate_content(**kwargs):
            self.requests.append(_fige(kwargs))
            if self._reponses:
                return self._reponses.pop(0)
            return _reponse("ok")

        self.aio = SimpleNamespace(
            models=SimpleNamespace(generate_content=generate_content),
        )


def _gemini(client=None):
    """Provider sans identifiants — ``__init__`` lit la configuration."""
    from ai.providers.gemini_provider import GeminiProvider

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._client = client or _FakeGeminiClient()
    return provider


def _lance(provider, prompt, tools, **kwargs):
    async def _tour():
        return await provider.complete_chat_with_tools(
            prompt, model="gemini-2.0-flash", tools=tools, **kwargs,
        )

    return asyncio.run(_tour())


def _contenus(provider, index: int = 0) -> list:
    return provider._client.requests[index]["contents"]


# =================================================================
# La forme envoyée
# =================================================================

class TestLaFormeDuPremierAppel:

    def test_le_prefixe_stable_part_en_system_instruction(self):
        provider = _gemini()
        texte, appeles = _lance(provider, _prompt(), [_Outil()])

        assert (texte, appeles) == ("ok", [])
        assert provider._client.requests[0]["system_instruction"] == (
            _champs()["system_stable"]
        )

    def test_de_vrais_tours_avec_assistant_devenu_model(self):
        provider = _gemini()
        _lance(provider, _prompt(), [_Outil()])

        contenus = _contenus(provider)
        assert [role for role, _ in contenus] == _ROLES_ATTENDUS
        # Rien n'est aplati : « Assistant: » comme texte est exactement ce que
        # la forme à deux chaînes produisait.
        textes = [p[1] for _, parts in contenus for p in parts if p[0] == "text"]
        assert not any("Assistant:" in t for t in textes)

    def test_le_premier_tour_n_est_jamais_un_tour_model(self):
        """Gemini refuse un ``contents`` ouvrant sur ``model`` — et le tampon
        court terme ouvre sur Mika dès qu'elle a parlé la première (accueil,
        initiative de la conscience)."""
        provider = _gemini()
        _lance(
            provider,
            _prompt(history=[{"role": "assistant", "content": "coucou !"}]),
            [_Outil()],
        )

        assert _contenus(provider)[0][0] == "user"

    def test_le_tiers_reste_nomme_dans_son_tour(self):
        provider = _gemini()
        _lance(provider, _prompt(), [_Outil()])

        assert _contenus(provider)[2] == ("user", [("text", "Alice: moi c'est Alice")])

    def test_l_etat_volatil_voyage_dans_le_dernier_tour_user(self):
        provider = _gemini()
        _lance(provider, _prompt(), [_Outil()])

        requete = provider._client.requests[0]
        volatile = _champs()["system_volatile"]
        role, parts = requete["contents"][-1]
        dernier = parts[0][1]

        assert role == "user"
        assert CONTEXT_HEADER in dernier
        assert volatile in dernier
        assert _champs()["message"] in dernier
        # Hors du système, sinon l'état du tour invalide le préfixe cacheable
        # à chaque tour — et la frontière ne sert plus à rien.
        assert volatile not in requete["system_instruction"]
        assert CONTEXT_HEADER not in requete["system_instruction"]
        assert not any(
            CONTEXT_HEADER in p[1]
            for _, parts in requete["contents"][:-1] for p in parts if p[0] == "text"
        )

    def test_les_outils_declares_partent_avec(self):
        provider = _gemini()
        _lance(provider, _prompt(), [_Outil()])

        declares = provider._client.requests[0]["tools"]
        assert [
            d.name for t in declares for d in t.function_declarations
        ] == ["list_recent_emails"]


# =================================================================
# La boucle elle-même
# =================================================================

class TestLaBoucleTourneEncore:

    def _client_avec_un_outil(self, outil):
        return _FakeGeminiClient([
            _reponse("", [_appel_gemini(outil.name, {"limite": 3})]),
            _reponse("tu as 2 mails"),
        ])

    def test_un_appel_execute_et_son_resultat_reinjecte(self):
        outil = _Outil()
        provider = _gemini(self._client_avec_un_outil(outil))

        texte, appeles = _lance(provider, _prompt(), [outil])

        assert texte == "tu as 2 mails"
        assert appeles == [outil.name]
        assert outil.recu == [{"limite": 3}]

        deuxieme = _contenus(provider, 1)
        # Le tour du modèle rejoué, puis les résultats en function_response.
        assert deuxieme[-2] == ("model", [("call", outil.name, {"limite": 3})])
        assert deuxieme[-1] == ("user", [("response", outil.name, {"mails": 2})])

    def test_le_prefixe_ne_bouge_pas_d_un_aller_retour_a_l_autre(self):
        """La raison d'être du correctif : la boucle rappelle le modèle une
        fois par outil, et un préfixe qui change à chaque itération refacture
        les déclarations à chaque fois."""
        outil = _Outil()
        provider = _gemini(self._client_avec_un_outil(outil))
        _lance(provider, _prompt(), [outil])

        premier = provider._client.requests[0]
        deuxieme = provider._client.requests[1]

        assert deuxieme["system_instruction"] == premier["system_instruction"]
        assert deuxieme["contents"][: len(premier["contents"])] == premier["contents"]
        assert len(deuxieme["contents"]) > len(premier["contents"])

    def test_un_outil_inconnu_revient_au_modele_comme_erreur(self):
        provider = _gemini(_FakeGeminiClient([
            _reponse("", [_appel_gemini("outil_fantome", {})]),
            _reponse("désolée"),
        ]))

        texte, appeles = _lance(provider, _prompt(), [_Outil()])

        assert (texte, appeles) == ("désolée", [])
        role, parts = _contenus(provider, 1)[-1]
        assert role == "user"
        assert "unknown tool" in parts[0][2]["error"]


# =================================================================
# L'objectif lui-même : plus d'aplatissement chez Gemini
# =================================================================

class TestPlusDAplatissement:

    def test_gemini_expose_complete_chat_with_tools(self):
        """C'est sur ce ``hasattr`` que le routeur bascule — sans lui, aucun
        des tests ci-dessus ne dit quoi que ce soit du chemin réel."""
        from ai.providers.gemini_provider import GeminiProvider

        assert hasattr(GeminiProvider, "complete_chat_with_tools")

    def test_le_chemin_outille_n_appelle_pas_l_aplatissement(self):
        prompt = _PromptSansAplatissement(**_champs())
        texte, _ = _lance(_gemini(), prompt, [_Outil()])
        assert texte == "ok"

    def test_le_module_gemini_ne_nomme_plus_legacy_pair(self):
        source = (_BACKEND / "ai" / "providers" / "gemini_provider.py").read_text("utf-8")
        offenders = [
            f"gemini_provider.py:{node.lineno}"
            for node in ast.walk(ast.parse(source))
            if (isinstance(node, ast.Attribute) and node.attr == "legacy_pair")
            or (isinstance(node, ast.Name) and node.id == "legacy_pair")
        ]
        assert offenders == []

    def test_un_seul_corps_de_boucle(self):
        """Deux amorces, un corps : les deux amorces délèguent, elles ne
        recopient pas la boucle (c'est ainsi que les deux dérivent)."""
        source = ast.parse(
            (_BACKEND / "ai" / "providers" / "gemini_provider.py").read_text("utf-8")
        )
        corps = {
            fonction.name for fonction in ast.walk(source)
            if isinstance(fonction, ast.AsyncFunctionDef)
            and any(
                isinstance(noeud, ast.Call)
                and ast.unparse(noeud.func).endswith("generate_content")
                for noeud in ast.walk(fonction)
            )
        }
        # ``complete`` et ``complete_chat`` sont des appels simples, sans
        # boucle ; le seul corps outillé est ``_tool_loop``.
        assert corps == {"complete", "complete_chat", "_tool_loop"}

    def test_l_amorce_a_deux_chaines_marche_toujours(self):
        """Signature inchangée : ``AIRouter.complete_with_tools`` ne connaît
        que deux chaînes, et des tests existants l'appellent ainsi."""
        outil = _Outil()
        provider = _gemini(_FakeGeminiClient([
            _reponse("", [_appel_gemini(outil.name, {})]),
            _reponse("voilà"),
        ]))

        texte, appeles = asyncio.run(provider.complete_with_tools(
            system_prompt="tu es Mika",
            user_prompt="mes mails ?",
            model="gemini-2.0-flash",
            tools=[outil],
        ))

        assert (texte, appeles) == ("voilà", [outil.name])
        requete = provider._client.requests[0]
        assert requete["system_instruction"] == "tu es Mika"
        assert requete["contents"] == [("user", [("text", "mes mails ?")])]


# =================================================================
# Le protocole : une capacité, pas une obligation
# =================================================================

class TestLeProtocole:

    def test_les_six_providers_satisfont_les_deux_capacites(self):
        from ai.providers.claude import ClaudeProvider
        from ai.providers.gemini_provider import GeminiProvider
        from ai.providers.glm_provider import GLMProvider
        from ai.providers.ollama_cloud_provider import OllamaCloudProvider
        from ai.providers.ollama_provider import OllamaProvider
        from ai.providers.openai_provider import OpenAIProvider

        for cls in (
            ClaudeProvider, GeminiProvider, GLMProvider,
            OllamaProvider, OllamaCloudProvider, OpenAIProvider,
        ):
            assert hasattr(cls, "complete_chat"), cls.__name__
            assert hasattr(cls, "complete_chat_with_tools"), cls.__name__

    def test_le_tour_structure_reste_hors_du_socle(self):
        """Un membre de Protocol n'est pas optionnel : exiger ``complete_chat``
        dans ``AIProvider`` rendrait le ``hasattr`` du routeur toujours vrai —
        une détection de capacité qui ne détecte plus rien."""
        from ai.providers import AIProvider, ChatNativeProvider, ChatToolsProvider

        socle = set(AIProvider.__protocol_attrs__)
        assert "complete_chat" not in socle
        assert "complete_chat_with_tools" not in socle
        assert ChatNativeProvider.__protocol_attrs__ == {"complete_chat"}
        assert ChatToolsProvider.__protocol_attrs__ == {"complete_chat_with_tools"}

    def test_un_provider_sans_tour_structure_reste_un_provider(self):
        """Le socle est ce que TOUT provider tient ; la capacité se teste à
        part, et son absence n'invalide pas le provider."""
        from ai.providers import AIProvider, ChatNativeProvider, ChatToolsProvider

        class _Minimal:
            async def complete(self, *a, **k): return ""
            async def complete_with_tools(self, *a, **k): return "", []
            async def list_models(self): return []
            async def test(self): return {"ok": True, "model_count": 0}

        minimal = _Minimal()
        assert isinstance(minimal, AIProvider)
        assert not isinstance(minimal, ChatNativeProvider)
        assert not isinstance(minimal, ChatToolsProvider)

    def test_gemini_satisfait_les_deux_capacites_structurellement(self):
        from ai.providers import ChatNativeProvider, ChatToolsProvider

        provider = _gemini()
        assert isinstance(provider, ChatNativeProvider)
        assert isinstance(provider, ChatToolsProvider)


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
            "provider": "gemini", "model_id": "gemini-2.0-flash",
            "temperature": 0.7, "max_tokens": 2048,
        },
    }
    monkeypatch.setattr(
        router_mod.AIRouter, "_resolve",
        lambda self, role: ("gemini", "gemini-2.0-flash", 0.7, "stub"),
    )
    monkeypatch.setattr(
        router_mod.AIRouter, "_call_timeout", lambda self, o: 5.0,
    )
    monkeypatch.setattr(router_mod.quota_tracker, "check", lambda **kw: None)
    monkeypatch.setattr(router_mod.quota_tracker, "record", lambda **kw: 0.0)
    return r, router_mod


class TestRouteurDonneLaFormeStructuree:
    """Le correctif doit suffire *sans* toucher au routeur : c'est
    ``hasattr(provider, "complete_chat_with_tools")`` qui décide."""

    def test_le_provider_recoit_de_vrais_tours(self, routeur, monkeypatch):
        r, router_mod = routeur
        provider = _gemini()
        monkeypatch.setattr(
            router_mod.AIRouter, "_get_provider", lambda self, name: provider,
        )

        async def _tour():
            return await r.chat_with_tools(
                router_mod.AIRole.CONVERSATION_TOOLS, _prompt(), [_Outil()],
            )

        texte, appeles = asyncio.run(_tour())

        assert (texte, appeles) == ("ok", [])
        assert [role for role, _ in _contenus(provider)] == _ROLES_ATTENDUS
        assert provider._client.requests[0]["system_instruction"] == (
            _champs()["system_stable"]
        )
