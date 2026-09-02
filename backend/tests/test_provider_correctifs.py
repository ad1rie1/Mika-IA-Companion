"""Quatre défauts des providers, confirmés par audit.

- OpenAI-compatibles (OpenAI, GLM, boucle d'outils partagée) : un modèle de
  raisonnement refuse ``max_tokens`` (« use max_completion_tokens ») et
  ``temperature`` en 400, sans aucune reprise — chaque rôle mappé dessus
  échouait à chaque appel.
- Claude, boucle d'outils : un ``stop_reason == "max_tokens"`` tombé en plein
  bloc ``tool_use`` sortait de la boucle comme une fin de tour ordinaire,
  et l'appel disparaissait sans un mot ; un ``refusal`` ne laissait aucune
  trace de sa catégorie.
- Ollama : le tour ``tool`` partait sous ``name`` alors que le champ du SDK
  est ``tool_name`` — pydantic l'ignorait en silence.
- Ollama : ``_chat`` rejouait la génération entière sur *n'importe quelle*
  exception, la garde « pas de think → relever » étant morte (think est
  toujours envoyé).
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from ai.quota import _usage_ctx


@pytest.fixture(autouse=True)
def _usage_vierge():
    _usage_ctx.set(None)
    yield
    _usage_ctx.set(None)


class _Outil:
    """Un ``ModuleTool`` minimal : nom, description, schéma, handler."""

    def __init__(self, name="lire", result=None):
        self.name = name
        self.description = "outil de test"
        self.calls: list = []
        self._result = result if result is not None else {"ok": True}

    def to_json_schema(self):
        return {"type": "object", "properties": {}}

    async def handler(self, args):
        self.calls.append(args)
        return self._result


# ===================================================================
# OpenAI-compatibles : reprise mémorisée sur 400
# ===================================================================

def _bad_request(message: str):
    from openai import BadRequestError

    resp = httpx.Response(400, request=httpx.Request("POST", "http://test"))
    return BadRequestError(message, response=resp, body=None)


_REFUS_MAX_TOKENS = (
    "Unsupported parameter: 'max_tokens' is not supported with this model. "
    "Use 'max_completion_tokens' instead."
)
_REFUS_TEMPERATURE = (
    "Unsupported value: 'temperature' does not support 0.7 with this model. "
    "Only the default (1) value is supported."
)


def _reponse_openai(text="ok", tool_calls=None):
    msg = SimpleNamespace(content=text, tool_calls=tool_calls or [])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg)],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2),
    )


def _client_openai(scenario):
    """``scenario`` : liste d'exceptions ou de réponses, consommée dans l'ordre."""
    client = MagicMock()
    client.requests = []
    file = list(scenario)

    async def create(**kwargs):
        client.requests.append(kwargs)
        item = file.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    client.chat.completions.create = create
    return client


class TestRepriseOpenAICompatible:

    async def test_max_tokens_refuse_est_repris_en_max_completion_tokens(self):
        from ai.providers._openai_tools import ParamMemo, create_chat_completion

        client = _client_openai([_bad_request(_REFUS_MAX_TOKENS), _reponse_openai()])
        memo = ParamMemo()
        resp = await create_chat_completion(
            client, memo, model="o4-mini", messages=[], max_tokens=300, temperature=0.7,
        )
        assert resp.choices[0].message.content == "ok"
        assert len(client.requests) == 2
        # Premier essai : le nom commun — les serveurs tiers ne connaissent
        # souvent que lui.
        assert client.requests[0]["max_tokens"] == 300
        assert "max_completion_tokens" not in client.requests[0]
        # Reprise : renommé, jamais les deux à la fois.
        assert client.requests[1]["max_completion_tokens"] == 300
        assert "max_tokens" not in client.requests[1]
        assert memo.token_param["o4-mini"] == "max_completion_tokens"

    async def test_le_refus_est_memorise_par_modele(self):
        """Le second appel du même modèle ne paie plus la requête condamnée."""
        from ai.providers._openai_tools import ParamMemo, create_chat_completion

        memo = ParamMemo()
        c1 = _client_openai([_bad_request(_REFUS_MAX_TOKENS), _reponse_openai()])
        await create_chat_completion(
            c1, memo, model="gpt-5", messages=[], max_tokens=100, temperature=0.7,
        )
        c2 = _client_openai([_reponse_openai()])
        await create_chat_completion(
            c2, memo, model="gpt-5", messages=[], max_tokens=100, temperature=0.7,
        )
        assert len(c2.requests) == 1
        assert c2.requests[0]["max_completion_tokens"] == 100
        # Un autre modèle sur la même instance garde le premier essai.
        c3 = _client_openai([_reponse_openai()])
        await create_chat_completion(
            c3, memo, model="gpt-4o", messages=[], max_tokens=100, temperature=0.7,
        )
        assert c3.requests[0]["max_tokens"] == 100

    async def test_temperature_refusee_est_retiree_et_memorisee(self):
        from ai.providers._openai_tools import ParamMemo, create_chat_completion

        memo = ParamMemo()
        client = _client_openai([_bad_request(_REFUS_TEMPERATURE), _reponse_openai()])
        await create_chat_completion(
            client, memo, model="o3", messages=[], max_tokens=100, temperature=0.7,
        )
        assert "temperature" in client.requests[0]
        assert "temperature" not in client.requests[1]
        assert "o3" in memo.no_temperature

    async def test_un_modele_de_raisonnement_refuse_les_deux_en_serie(self):
        """Le cas réel de la série o : d'abord max_tokens, puis temperature.
        Trois requêtes, pas une boucle."""
        from ai.providers._openai_tools import ParamMemo, create_chat_completion

        client = _client_openai([
            _bad_request(_REFUS_MAX_TOKENS),
            _bad_request(_REFUS_TEMPERATURE),
            _reponse_openai(),
        ])
        await create_chat_completion(
            client, ParamMemo(), model="o3", messages=[], max_tokens=100, temperature=0.7,
        )
        assert len(client.requests) == 3
        derniere = client.requests[2]
        assert derniere["max_completion_tokens"] == 100
        assert "temperature" not in derniere

    async def test_un_autre_400_remonte_intact_sans_reprise(self):
        from ai.providers._openai_tools import ParamMemo, create_chat_completion
        from openai import BadRequestError

        client = _client_openai([_bad_request("Invalid 'messages[0].role'")])
        with pytest.raises(BadRequestError):
            await create_chat_completion(
                client, ParamMemo(), model="gpt-4o", messages=[], max_tokens=100, temperature=0.7,
            )
        assert len(client.requests) == 1

    async def test_une_erreur_qui_n_est_pas_un_400_remonte_intacte(self):
        from ai.providers._openai_tools import ParamMemo, create_chat_completion

        client = _client_openai([RuntimeError("réseau")])
        with pytest.raises(RuntimeError):
            await create_chat_completion(
                client, ParamMemo(), model="gpt-4o", messages=[], max_tokens=100, temperature=0.7,
            )

    async def test_la_reprise_n_est_tentee_qu_une_fois_par_parametre(self):
        """Un serveur qui refuse aussi ``max_completion_tokens`` ne fait pas
        tourner la reprise en rond."""
        from ai.providers._openai_tools import ParamMemo, create_chat_completion
        from openai import BadRequestError

        client = _client_openai([
            _bad_request(_REFUS_MAX_TOKENS),
            _bad_request("Unknown parameter: 'max_completion_tokens'. Did you mean max_tokens?"),
        ])
        with pytest.raises(BadRequestError):
            await create_chat_completion(
                client, ParamMemo(), model="bizarre", messages=[], max_tokens=100, temperature=0.7,
            )
        assert len(client.requests) == 2


class TestReprisesBranchees:
    """La reprise couvre l'appel simple, le tour structuré, la boucle
    d'outils — chez OpenAI comme chez GLM — et le mémo est celui du
    provider, donc partagé entre ces chemins."""

    @staticmethod
    def _openai(client):
        from ai.providers.openai_provider import OpenAIProvider

        p = OpenAIProvider.__new__(OpenAIProvider)
        p._client = client
        return p

    @staticmethod
    def _glm(client):
        from ai.providers.glm_provider import GLMProvider

        p = GLMProvider.__new__(GLMProvider)
        p._client = client
        return p

    @pytest.mark.parametrize("fabrique", [_openai, _glm])
    async def test_complete_reprend_puis_memorise(self, fabrique):
        client = _client_openai([
            _bad_request(_REFUS_MAX_TOKENS), _reponse_openai("un"), _reponse_openai("deux"),
        ])
        p = fabrique.__func__(client)
        assert await p.complete("sys", "usr", model="o3", max_tokens=50) == "un"
        assert await p.complete("sys", "usr", model="o3", max_tokens=50) == "deux"
        assert [("max_completion_tokens" in r) for r in client.requests] == [False, True, True]

    @pytest.mark.parametrize("fabrique", [_openai, _glm])
    async def test_complete_chat_reprend_aussi(self, fabrique):
        from ai.chat import ChatPrompt

        client = _client_openai([_bad_request(_REFUS_TEMPERATURE), _reponse_openai("ok")])
        p = fabrique.__func__(client)
        prompt = ChatPrompt(system_stable="stable", history=[], message="coucou")
        assert await p.complete_chat(prompt, model="o3") == "ok"
        assert "temperature" not in client.requests[1]

    @pytest.mark.parametrize("fabrique", [_openai, _glm])
    async def test_la_boucle_d_outils_ne_repaie_pas_le_refus_a_chaque_iteration(self, fabrique):
        """Deux itérations : le 400 tombe à la première, la seconde part
        directement avec le bon paramètre."""
        outil = _Outil("lire")
        appel = SimpleNamespace(
            id="c1",
            function=SimpleNamespace(name="lire", arguments=json.dumps({"q": 1})),
        )
        client = _client_openai([
            _bad_request(_REFUS_MAX_TOKENS),
            _reponse_openai("", tool_calls=[appel]),
            _reponse_openai("fini"),
        ])
        p = fabrique.__func__(client)
        texte, appeles = await p.complete_with_tools(
            "sys", "usr", model="o3", tools=[outil], max_tokens=64,
        )
        assert (texte, appeles) == ("fini", ["lire"])
        assert outil.calls == [{"q": 1}]
        assert len(client.requests) == 3
        assert "max_completion_tokens" in client.requests[2]
        assert "max_tokens" not in client.requests[2]


# ===================================================================
# Claude : max_tokens / refusal en plein appel d'outil
# ===================================================================

def _bloc_texte(text):
    return SimpleNamespace(type="text", text=text)


def _bloc_outil(name="lire", id="t1"):
    return SimpleNamespace(type="tool_use", id=id, name=name, input={"q": 1})


def _reponse_claude(stop_reason, *content, stop_details=None):
    return SimpleNamespace(
        content=list(content), stop_reason=stop_reason,
        usage=None, stop_details=stop_details,
    )


def _claude(scenario):
    from ai.providers.claude import ClaudeProvider

    p = ClaudeProvider.__new__(ClaudeProvider)
    p._no_temperature_models = set()
    client = MagicMock()
    client.requests = []
    file = list(scenario)

    async def create(**kwargs):
        client.requests.append(kwargs)
        return file.pop(0)

    client.messages.create = create
    p._client = client
    return p, client


class TestClaudeArretsDeBoucle:

    async def test_tronque_en_plein_appel_d_outil_est_rejoue_avec_un_plafond_double(self):
        outil = _Outil("lire")
        p, client = _claude([
            _reponse_claude("max_tokens", _bloc_texte("je vais"), _bloc_outil()),
            _reponse_claude("tool_use", _bloc_outil()),
            _reponse_claude("end_turn", _bloc_texte("fini")),
        ])
        texte, appeles = await p.complete_with_tools(
            "sys", "usr", model="claude-opus-5", tools=[outil], max_tokens=1000,
        )
        assert appeles == ["lire"]
        assert outil.calls == [{"q": 1}]
        assert texte == "fini"
        assert [r["max_tokens"] for r in client.requests] == [1000, 2000, 2000]
        assert "tronquée" not in texte

    async def test_tronque_deux_fois_finit_par_le_dire(self):
        from ai.providers.claude import _TRUNCATED_TOOL_CALL_MARKER

        outil = _Outil("lire")
        p, client = _claude([
            _reponse_claude("max_tokens", _bloc_texte("je vais"), _bloc_outil()),
            _reponse_claude("max_tokens", _bloc_texte("je vais encore"), _bloc_outil()),
        ])
        texte, appeles = await p.complete_with_tools(
            "sys", "usr", model="claude-opus-5", tools=[outil], max_tokens=1000,
        )
        assert appeles == []
        assert outil.calls == []
        assert len(client.requests) == 2
        # Le texte de l'essai tronqué n'est pas gardé, celui du second oui,
        # et le marqueur ferme la réponse.
        assert texte == "je vais encore\n\n" + _TRUNCATED_TOOL_CALL_MARKER

    async def test_le_second_essai_est_borne(self):
        """Au plafond, doubler n'achète rien : le marqueur, tout de suite."""
        from ai.providers.claude import _TOOL_CALL_CAP_CEILING, _TRUNCATED_TOOL_CALL_MARKER

        p, client = _claude([
            _reponse_claude("max_tokens", _bloc_outil()),
        ])
        texte, _ = await p.complete_with_tools(
            "sys", "usr", model="claude-opus-5", tools=[_Outil()],
            max_tokens=_TOOL_CALL_CAP_CEILING,
        )
        assert len(client.requests) == 1
        assert _TRUNCATED_TOOL_CALL_MARKER in texte

    async def test_le_doublement_s_arrete_au_plafond(self):
        from ai.providers.claude import _TOOL_CALL_CAP_CEILING

        p, client = _claude([
            _reponse_claude("max_tokens", _bloc_outil()),
            _reponse_claude("end_turn", _bloc_texte("ok")),
        ])
        await p.complete_with_tools(
            "sys", "usr", model="claude-opus-5", tools=[_Outil()],
            max_tokens=_TOOL_CALL_CAP_CEILING - 1,
        )
        assert client.requests[1]["max_tokens"] == _TOOL_CALL_CAP_CEILING

    async def test_max_tokens_sans_appel_d_outil_reste_une_fin_ordinaire(self):
        """Une réponse simplement longue n'est pas rejouée."""
        p, client = _claude([
            _reponse_claude("max_tokens", _bloc_texte("long...")),
        ])
        texte, _ = await p.complete_with_tools(
            "sys", "usr", model="claude-opus-5", tools=[_Outil()], max_tokens=1000,
        )
        assert texte == "long..."
        assert len(client.requests) == 1

    async def test_un_refus_est_journalise_avec_sa_categorie(self, caplog):
        details = SimpleNamespace(type="refusal", category="cyber", explanation="…")
        outil = _Outil("lire")
        p, client = _claude([
            _reponse_claude("refusal", _bloc_outil(), stop_details=details),
        ])
        with caplog.at_level(logging.WARNING, logger="ai.providers.claude"):
            texte, appeles = await p.complete_with_tools(
                "sys", "usr", model="claude-opus-5", tools=[outil], max_tokens=1000,
            )
        assert appeles == []
        assert outil.calls == []
        assert len(client.requests) == 1
        avert = [r for r in caplog.records if "refus" in r.getMessage()]
        assert avert, "le refus doit laisser une trace"
        assert "cyber" in avert[0].getMessage()


# ===================================================================
# Ollama : le tour ``tool`` et la reprise de ``think``
# ===================================================================

def _ollama():
    from ai.providers.ollama_provider import OllamaProvider

    p = OllamaProvider.__new__(OllamaProvider)
    p._host = "http://localhost:11434"
    p._client = MagicMock()
    return p


def _reponse_ollama(text, tool_calls=None):
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = tool_calls or []
    resp = MagicMock()
    resp.message = msg
    return resp


def _config_ollama():
    values = {"ai.ollama.thinking": False, "ai.ollama.max_reply_tokens": 768}

    def fake_get(key, default=None):
        if key in values:
            return values[key]
        raise KeyError(key)

    return patch("configs.service.config_service.get", side_effect=fake_get)


class TestOllamaTourOutil:

    def test_le_tour_tool_porte_tool_name_et_jamais_un_contenu_vide(self):
        from ai.providers.ollama_provider import _tool_message

        msg = _tool_message("lire", "")
        assert msg["role"] == "tool"
        assert msg["tool_name"] == "lire"
        assert "name" not in msg
        assert msg["content"]

    def test_le_nom_survit_a_la_validation_du_sdk(self):
        """Le vrai juge : ce que pydantic garde. ``name`` était jeté sans
        un mot ; ``tool_name`` arrive au serveur."""
        from ollama._types import Message

        from ai.providers.ollama_provider import _tool_message

        serialise = Message.model_validate(_tool_message("lire", "x")).model_dump(
            exclude_none=True,
        )
        assert serialise.get("tool_name") == "lire"

    async def test_la_boucle_envoie_le_resultat_sous_tool_name(self):
        outil = _Outil("lire", result={"ok": True})
        appel = SimpleNamespace(function=SimpleNamespace(name="lire", arguments={"q": 1}))
        p = _ollama()
        p._client.chat = AsyncMock(side_effect=[
            _reponse_ollama("", tool_calls=[appel]),
            _reponse_ollama("fini"),
        ])
        with _config_ollama(), patch("ai.providers.ollama_provider._record_ollama_usage"):
            texte, appeles = await p.complete_with_tools(
                "sys", "usr", model="qwen3", tools=[outil],
            )
        assert (texte, appeles) == ("fini", ["lire"])
        fil = p._client.chat.await_args_list[1].kwargs["messages"]
        tours_outil = [m for m in fil if m["role"] == "tool"]
        assert len(tours_outil) == 1
        assert tours_outil[0]["tool_name"] == "lire"
        assert "name" not in tours_outil[0]
        assert tours_outil[0]["content"] == json.dumps({"ok": True}, ensure_ascii=False)


class TestOllamaRepriseDeThink:

    async def test_une_erreur_qui_ne_designe_pas_think_remonte_sans_rejouer(self):
        """Une connexion refusée n'est pas un refus du paramètre : avant, la
        génération repartait une seconde fois et seule la seconde erreur
        remontait."""
        p = _ollama()
        p._client.chat = AsyncMock(side_effect=ConnectionError("connexion refusée"))
        with _config_ollama(), pytest.raises(ConnectionError):
            await p.complete("sys", "coucou", model="gemma4:12b")
        assert p._client.chat.await_count == 1

    async def test_un_400_du_serveur_est_repris_sans_think(self):
        from ollama import ResponseError

        p = _ollama()
        p._client.chat = AsyncMock(side_effect=[
            ResponseError("invalid request", 400),
            _reponse_ollama("ok"),
        ])
        with _config_ollama(), patch("ai.providers.ollama_provider._record_ollama_usage"):
            assert await p.complete("sys", "coucou", model="gemma4:12b") == "ok"
        assert p._client.chat.await_count == 2
        assert "think" not in p._client.chat.await_args_list[1].kwargs

    async def test_un_404_modele_absent_remonte_tel_quel(self):
        from ollama import ResponseError

        p = _ollama()
        p._client.chat = AsyncMock(side_effect=ResponseError("model not found", 404))
        with _config_ollama(), pytest.raises(ResponseError):
            await p.complete("sys", "coucou", model="absent")
        assert p._client.chat.await_count == 1

    async def test_un_message_qui_nomme_le_parametre_est_repris(self):
        p = _ollama()
        p._client.chat = AsyncMock(side_effect=[
            ValueError("this model does not support thinking"),
            _reponse_ollama("ok"),
        ])
        with _config_ollama(), patch("ai.providers.ollama_provider._record_ollama_usage"):
            assert await p.complete("sys", "coucou", model="llama3") == "ok"
        assert p._client.chat.await_count == 2
