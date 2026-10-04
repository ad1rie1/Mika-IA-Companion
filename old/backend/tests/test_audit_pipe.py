"""Section PIPE de l'audit du 2026-09-16 (docs/audit-2026-09-16.md).

Chaque classe pinne un id de la section « Pipeline et couche IA » :

- PIPE-01 : une seule borne temporelle, celle du routeur ; l'usage d'un appel
  annulé de l'extérieur est compté.
- PIPE-02 : ``conversation_tools`` non mappé retombe sur ``conversation`` ; le
  texte de repli nomme le rôle manquant.
- PIPE-03 : le budget se calcule sur le rôle qui sert le tour.
- PIPE-04 : hystérésis d'élagage → le préfixe du payload Claude au tour N+1
  est celui du tour N.
- PIPE-05 : TTL du cache configurable ; agrégat de relecture par rôle.
- PIPE-07 : la réponse part avant l'état intérieur ; le délai cosmétique
  vit hors du worker, dans l'ordre.
- PIPE-09 : pas de calibration chars→tokens avec pièces jointes.
- PIPE-10 : les dates d'historique ne sont relues qu'une fois.
- PIPE-11 : une persistance qui échoue n'est pas une panne d'IA.
- DEF-14 / DEF-15 : les défauts revus.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from old.backend.ai.quota import _usage_ctx, set_usage
from old.backend.ai.router import AIRole, AIRouter, UnconfiguredRoleError


@pytest.fixture(autouse=True)
def _usage_vierge():
    _usage_ctx.set(None)
    yield
    _usage_ctx.set(None)


def _routeur_nu(provider: str = "claude") -> AIRouter:
    r = AIRouter.__new__(AIRouter)
    r._providers = {}
    r._role_to_internal = {}
    r._declared_models = None
    r._semaphores = {}
    r._semaphore_loop = None
    r._concurrency_limit = lambda name: 0
    r._resolve = lambda role: (provider, "modele-test", 0.7, "interne")
    r._get_provider = lambda name: MagicMock()
    r._call_timeout = lambda override: float(override) if override else 30.0
    return r


def _traqueur() -> MagicMock:
    t = MagicMock()
    t.record.return_value = 0.0
    return t


def _fake_context(**kw):
    from old.backend.pipeline.context import ConversationContext

    base = dict(memory_context="", emotion_context="", module_context="",
                history=[], tools=[], tool_names=[])
    base.update(kw)
    return ConversationContext(**base)


# ===================================================================
# PIPE-01 — une seule borne, et l'annulation compte
# ===================================================================


class TestUneSeuleBorne:

    def test_le_processeur_ne_pose_plus_de_wait_for_autour_de_l_appel(self):
        """AST, pas texte : les commentaires du fichier nomment ``wait_for``
        précisément pour dire qu'il ne doit plus y être."""
        from old.backend.pipeline import processor

        tree = ast.parse(inspect.getsource(processor))
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "process_message"
        )
        appels = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "wait_for"
        ]
        assert appels == [], "process_message pose encore sa propre borne"

    async def test_une_annulation_exterieure_compte_les_jetons_deja_payes(self, monkeypatch):
        from old.backend.ai import router as router_module

        traqueur = _traqueur()
        monkeypatch.setattr(router_module, "quota_tracker", traqueur)
        r = _routeur_nu()

        async def invoke(provider, model, temperature, max_tokens):
            set_usage(400, 40)
            set_usage(500, 50)
            await asyncio.sleep(10)
            return "jamais", "jamais"

        # Un ``wait_for`` PLUS COURT chez l'appelant : c'était le cas du
        # processeur, et la branche n'existait pas.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                r._metered_call(AIRole.CONVERSATION_TOOLS, "s", "u", invoke, timeout=30),
                timeout=0.05,
            )

        assert traqueur.record.call_count == 1
        kw = traqueur.record.call_args.kwargs
        assert (kw["tokens_in"], kw["tokens_out"]) == (900, 90)
        assert _usage_ctx.get() is None

    async def test_le_timeout_du_routeur_devient_le_texte_de_repli(self):
        """Le processeur mappe toujours le ``TimeoutError`` — celui du routeur,
        maintenant — sur la phrase d'attente."""
        from old.backend.configs.service import config_service
        from old.backend.pipeline import processor
        from old.backend.pipeline.perception import Perception

        async def timeout(*a, **kw):
            raise asyncio.TimeoutError()

        with patch.object(config_service, "get", return_value=60), \
             patch.object(processor, "call_ai_and_parse", new=timeout), \
             patch.object(processor, "gather_context", new=AsyncMock(return_value=_fake_context())), \
             patch.object(processor.emotion_engine, "ensure_person_loaded", new=AsyncMock()), \
             patch.object(processor, "persist_user_message", new=AsyncMock(return_value=1)), \
             patch.object(processor, "persist_assistant_message", new=AsyncMock(return_value=2)), \
             patch.object(processor, "emit_communication_event", new=AsyncMock()), \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            out = await processor.process_message(
                Perception.from_text("hey", source="frontend", person_id="web_pipe01")
            )
        assert out.ai_failed and "instant" in out.text.lower()


# ===================================================================
# PIPE-02 — repli conversation_tools → conversation
# ===================================================================


class TestRepliDuRoleOutille:

    def _routeur_avec(self, mapping: dict) -> AIRouter:
        r = AIRouter.__new__(AIRouter)
        r._providers = {}
        r._role_to_internal = dict(mapping)
        r._declared_models = {
            "chat": {"provider": "claude", "model_id": "claude-sonnet-5",
                     "temperature": 0.7, "max_tokens": None, "context_window": None},
        }
        r._semaphores = {}
        r._semaphore_loop = None
        return r

    def test_conversation_tools_non_mappe_prend_le_modele_de_conversation(self):
        r = self._routeur_avec({AIRole.CONVERSATION: "chat"})
        provider, model, _, interne = r._resolve(AIRole.CONVERSATION_TOOLS)
        assert (provider, model, interne) == ("claude", "claude-sonnet-5", "chat")

    def test_conversation_tools_mappe_garde_son_propre_modele(self):
        r = self._routeur_avec({AIRole.CONVERSATION: "chat", AIRole.CONVERSATION_TOOLS: "chat"})
        r._declared_models["outils"] = dict(r._declared_models["chat"], model_id="claude-opus-5")
        r._role_to_internal[AIRole.CONVERSATION_TOOLS] = "outils"
        assert r._resolve(AIRole.CONVERSATION_TOOLS)[1] == "claude-opus-5"

    def test_les_deux_absents_nomment_le_role_demande(self):
        r = self._routeur_avec({})
        with pytest.raises(UnconfiguredRoleError) as exc:
            r._resolve(AIRole.CONVERSATION_TOOLS)
        assert exc.value.role is AIRole.CONVERSATION_TOOLS
        assert "conversation_tools" in str(exc.value)

    def test_un_autre_role_non_mappe_ne_retombe_sur_rien(self):
        r = self._routeur_avec({AIRole.CONVERSATION: "chat"})
        with pytest.raises(UnconfiguredRoleError) as exc:
            r._resolve(AIRole.MEMORY_EXTRACTION)
        assert exc.value.role is AIRole.MEMORY_EXTRACTION

    async def test_le_texte_de_repli_nomme_le_role_manquant(self):
        from old.backend.configs.service import config_service
        from old.backend.pipeline import processor
        from old.backend.pipeline.perception import Perception

        async def non_configure(*a, **kw):
            raise UnconfiguredRoleError("aucun", role=AIRole.CONVERSATION_TOOLS)

        with patch.object(config_service, "get", return_value=60), \
             patch.object(processor, "call_ai_and_parse", new=non_configure), \
             patch.object(processor, "gather_context", new=AsyncMock(return_value=_fake_context())), \
             patch.object(processor.emotion_engine, "ensure_person_loaded", new=AsyncMock()), \
             patch.object(processor, "persist_user_message", new=AsyncMock(return_value=1)), \
             patch.object(processor, "persist_assistant_message", new=AsyncMock(return_value=2)), \
             patch.object(processor, "emit_communication_event", new=AsyncMock()), \
             patch.object(processor, "broadcast_to_websocket", new=AsyncMock()):
            out = await processor.process_message(
                Perception.from_text("hey", source="frontend", person_id="web_pipe02")
            )
        assert out.ai_failed
        assert "conversation_tools" in out.text


# ===================================================================
# PIPE-03 — le budget suit le rôle qui sert le tour
# ===================================================================


class TestBudgetSurLeRoleEffectif:

    def _outil(self):
        t = MagicMock()
        t.name = "memory_search"
        t.description = "cherche"
        t.to_json_schema.return_value = {"type": "object", "properties": {}}
        return t

    def test_avec_outils_le_budget_est_celui_de_conversation_tools(self, monkeypatch):
        from old.backend.ai import budget as budget_module
        from old.backend.pipeline.prompt import build_chat_prompt

        roles_budget: list = []
        roles_l3: list = []

        def faux_budget_for(role, *, tools_chars=None):
            roles_budget.append(role)
            return None

        def faux_l3(tools_chars=None, role=None):
            roles_l3.append(role)
            return 100_000

        monkeypatch.setattr(budget_module, "budget_for", faux_budget_for)
        monkeypatch.setattr(budget_module, "conversation_l3_chars", faux_l3)
        build_chat_prompt(_fake_context(tools=[self._outil()]), "salut")
        assert roles_budget == [AIRole.CONVERSATION_TOOLS]
        assert roles_l3 == [AIRole.CONVERSATION_TOOLS]

    def test_sans_outils_le_budget_reste_celui_de_conversation(self, monkeypatch):
        from old.backend.ai import budget as budget_module
        from old.backend.pipeline.prompt import build_chat_prompt

        roles: list = []
        monkeypatch.setattr(
            budget_module, "budget_for",
            lambda role, *, tools_chars=None: roles.append(role),
        )
        monkeypatch.setattr(
            budget_module, "conversation_l3_chars",
            lambda tools_chars=None, role=None: 100_000,
        )
        build_chat_prompt(_fake_context(), "salut")
        assert roles == [AIRole.CONVERSATION]

    def test_le_poids_des_outils_est_note_sous_les_deux_roles(self, monkeypatch):
        """Le compactor lit la clé ``conversation`` ; le budget du tour lit
        la sienne. Les deux doivent parler du même chiffre."""
        from old.backend.ai import budget as budget_module
        from old.backend.ai.budget import ToolWeight
        from old.backend.pipeline.prompt import build_chat_prompt

        releve = ToolWeight()
        monkeypatch.setattr(budget_module, "tool_weight", releve)
        monkeypatch.setattr(
            budget_module, "conversation_l3_chars",
            lambda tools_chars=None, role=None: 100_000,
        )
        monkeypatch.setattr(budget_module, "budget_for", lambda *a, **kw: None)
        build_chat_prompt(_fake_context(tools=[self._outil()]), "salut")
        assert releve.chars_for("conversation") > 0
        assert releve.chars_for("conversation_tools") == releve.chars_for("conversation")


# ===================================================================
# PIPE-04 — stabilité inter-tours du payload Claude
# ===================================================================


def _sans_marqueurs(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        content = m["content"]
        if isinstance(content, list):
            content = [{k: v for k, v in b.items() if k != "cache_control"} for b in content]
        out.append({"role": m["role"], "content": content})
    return out


class TestPrefixeStableEntreDeuxTours:

    def test_le_prefixe_du_tour_suivant_est_le_payload_du_tour_precedent(self):
        """Ce que le cache de prompt exige, et que seuls les allers-retours
        INTRA-boucle pinaient : le tour N+1 doit commencer, octet pour octet,
        par le système et l'historique du tour N (hors marqueurs)."""
        from old.backend.ai.chat import ChatPrompt
        from old.backend.ai.providers.claude import ClaudeProvider

        historique = [
            {"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"}, {"role": "assistant", "content": "a2"},
        ]
        tour_n = ChatPrompt(
            system_stable="PERSONNALITE", system_volatile="etat A",
            history=list(historique), message="m3",
        )
        tour_n1 = ChatPrompt(
            system_stable="PERSONNALITE", system_volatile="etat B (a changé)",
            history=historique + [
                {"role": "user", "content": "m3"}, {"role": "assistant", "content": "r3"},
            ],
            message="m4",
        )
        sys_n, msgs_n = ClaudeProvider._chat_payload(tour_n)
        sys_n1, msgs_n1 = ClaudeProvider._chat_payload(tour_n1)

        assert _sans_marqueurs_sys(sys_n) == _sans_marqueurs_sys(sys_n1)
        prefixe = len(msgs_n) - 1  # tout sauf le dernier tour user (volatil)
        assert _sans_marqueurs(msgs_n1[:prefixe]) == _sans_marqueurs(msgs_n[:prefixe])
        # Et le point de cache du tour N (dernier tour d'historique) est bien
        # DANS ce préfixe, donc relu au tour N+1.
        marque_n = next(
            i for i, m in enumerate(msgs_n)
            if isinstance(m["content"], list) and "cache_control" in m["content"][0]
        )
        assert marque_n < prefixe

    def test_apres_une_coupe_hysteretique_le_prefixe_tient_plusieurs_tours(self):
        """Le fil déborde une fois ; les tours suivants gardent le même
        messages[0] tant que le fil ne déborde pas à nouveau."""
        from old.backend.pipeline.prompt import _trim_history_to_l3

        fil = [{"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 100}
               for i in range(20)]
        kept, dropped = _trim_history_to_l3(fil, 1000, low_ratio=0.5)
        assert dropped > 0
        tete = kept[0]
        fil = list(kept)
        tours_stables = 0
        for i in range(4):  # 4 × 100 = 400 : 500 + 400 < 1000
            fil.append({"role": "user" if i % 2 == 0 else "assistant", "content": "y" * 100})
            kept_n, dropped_n = _trim_history_to_l3(fil, 1000, low_ratio=0.5)
            if dropped_n == 0 and kept_n[0] is tete:
                tours_stables += 1
        assert tours_stables == 4


def _sans_marqueurs_sys(system: list[dict]) -> list[dict]:
    return [{k: v for k, v in b.items() if k != "cache_control"} for b in system]


# ===================================================================
# PIPE-05 — TTL et agrégat cache
# ===================================================================


class TestCacheTtlEtAgregat:

    def test_le_marqueur_nu_par_defaut(self):
        from old.backend.ai.providers import claude as claude_module
        from old.backend.configs.service import config_service

        with patch.object(config_service, "get", return_value="5m"):
            assert claude_module._cache_mark() == {"type": "ephemeral"}

    def test_une_heure_ajoute_le_ttl(self):
        from old.backend.ai.providers import claude as claude_module
        from old.backend.configs.service import config_service

        with patch.object(config_service, "get", return_value="1h"):
            assert claude_module._cache_mark() == {"type": "ephemeral", "ttl": "1h"}

    def test_une_valeur_inconnue_retombe_sur_le_marqueur_nu(self):
        """Un TTL que l'API refuse ferait échouer chaque requête : mieux vaut
        un cache court qu'aucune réponse."""
        from old.backend.ai.providers import claude as claude_module
        from old.backend.configs.service import config_service

        with patch.object(config_service, "get", return_value="2d"):
            assert claude_module._cache_mark() == {"type": "ephemeral"}

    def test_la_cle_est_declaree_avec_ses_deux_choix(self):
        from old.backend.ai.config_schema import CONFIG_SCHEMA
        from old.backend.configs.types import ConfigItem, choice_values

        item = next(
            i for i in CONFIG_SCHEMA
            if isinstance(i, ConfigItem) and i.key == "ai.claude.cache_ttl"
        )
        assert item.default == "5m" and item.hot_reload
        assert set(choice_values(item.choices)) == {"5m", "1h"}

    def test_l_agregat_calcule_le_taux_de_relecture(self):
        from old.backend.ai.router import CacheStats

        stats = CacheStats()
        stats.record("conversation_tools", tokens_in=100, cache_read=900, cache_write=0)
        stats.record("conversation_tools", tokens_in=100, cache_read=0, cache_write=900)
        stats.record("inner_voice", tokens_in=50, cache_read=0, cache_write=0)
        lignes = {l["role"]: l for l in stats.snapshot()}
        assert lignes["conversation_tools"]["calls"] == 2
        assert lignes["conversation_tools"]["hit_ratio"] == pytest.approx(900 / 2000)
        assert lignes["inner_voice"]["hit_ratio"] == 0.0

    async def test_un_appel_reussi_alimente_l_agregat(self, monkeypatch):
        from old.backend.ai import router as router_module
        from old.backend.ai.router import CacheStats

        stats = CacheStats()
        monkeypatch.setattr(router_module, "cache_stats", stats)
        monkeypatch.setattr(router_module, "quota_tracker", _traqueur())
        r = _routeur_nu()

        async def invoke(provider, model, temperature, max_tokens):
            set_usage(10, 5, cache_read_tokens=300, cache_write_tokens=20)
            return "ok", "ok"

        await r._metered_call(AIRole.CONVERSATION, "s", "u", invoke)
        (ligne,) = stats.snapshot()
        assert (ligne["role"], ligne["cache_read"], ligne["cache_write"]) == ("conversation", 300, 20)


# ===================================================================
# PIPE-07 — la diffusion différée hors du worker, dans l'ordre
# ===================================================================


class TestChaineDeDiffusion:

    async def test_deux_diffusions_gardent_leur_ordre_malgre_des_delais_inverses(self):
        from old.backend.pipeline import processor

        recu: list[str] = []

        async def faux_broadcast(output, source, person_id=None):
            recu.append(output)

        chaine = processor._BroadcastChain()
        with patch.object(processor, "broadcast_to_websocket", new=faux_broadcast):
            chaine.schedule(0.05, "premiere (lente)", "frontend", "web_x")
            chaine.schedule(0.0, "seconde (rapide)", "frontend", "web_x")
            await chaine.flush()
        assert recu == ["premiere (lente)", "seconde (rapide)"]

    async def test_une_diffusion_qui_leve_ne_casse_pas_la_suivante(self):
        from old.backend.pipeline import processor

        recu: list[str] = []

        async def faux_broadcast(output, source, person_id=None):
            if output == "casse":
                raise RuntimeError("couche de canaux morte")
            recu.append(output)

        chaine = processor._BroadcastChain()
        with patch.object(processor, "broadcast_to_websocket", new=faux_broadcast):
            chaine.schedule(0.0, "casse", "frontend", "web_x")
            chaine.schedule(0.0, "suivante", "frontend", "web_x")
            await chaine.flush()
        assert recu == ["suivante"]

    async def test_le_tour_rend_la_main_avant_la_diffusion_differee(self):
        """Le worker ne dort plus le délai « réflexion » : ``process_message``
        revient, la diffusion suit toute seule."""
        from old.backend.configs.service import config_service
        from old.backend.pipeline import processor
        from old.backend.pipeline.perception import Perception

        diffuse = AsyncMock()
        with patch.object(config_service, "get", return_value=60), \
             patch.object(processor, "call_ai_and_parse",
                          new=AsyncMock(return_value=("salut toi", None, []))), \
             patch.object(processor, "gather_context", new=AsyncMock(return_value=_fake_context())), \
             patch.object(processor.emotion_engine, "ensure_person_loaded", new=AsyncMock()), \
             patch.object(processor.emotion_engine, "save_snapshot", new=AsyncMock()), \
             patch.object(processor, "persist_user_message", new=AsyncMock(return_value=1)), \
             patch.object(processor, "persist_assistant_message", new=AsyncMock(return_value=2)), \
             patch.object(processor, "emit_communication_event", new=AsyncMock()), \
             patch.object(processor, "publish_turn_completed", new=AsyncMock()), \
             patch.object(processor, "_compute_thinking_delay", return_value=0.05), \
             patch.object(processor, "broadcast_to_websocket", new=diffuse):
            out = await processor.process_message(
                Perception.from_text("hey", source="frontend", person_id="web_pipe07")
            )
            assert not out.ai_failed
            diffuse.assert_not_called()          # rendu la main AVANT
            await processor.flush_delayed_broadcasts()
            diffuse.assert_called_once()         # … et diffusé quand même


# ===================================================================
# PIPE-09 — pas de calibration avec pièces jointes
# ===================================================================


class TestCalibrationSansImage:

    async def test_complete_avec_attachments_desactive_la_calibration(self):
        r = _routeur_nu()
        vu: dict = {}

        async def faux_metered(role, s, u, invoke, timeout=None, extra_prompt_chars=0, calibrate=True):
            vu["calibrate"] = calibrate
            return "ok"

        r._metered_call = faux_metered
        await r.complete(AIRole.VISION_CAPTION, "s", "u", attachments=[MagicMock()])
        assert vu["calibrate"] is False

    async def test_complete_sans_attachments_calibre(self):
        r = _routeur_nu()
        vu: dict = {}

        async def faux_metered(role, s, u, invoke, timeout=None, extra_prompt_chars=0, calibrate=True):
            vu["calibrate"] = calibrate
            return "ok"

        r._metered_call = faux_metered
        await r.complete(AIRole.MEMORY_EXTRACTION, "s", "u")
        assert vu["calibrate"] is True


# ===================================================================
# PIPE-10 — les dates d'historique sont mémorisées
# ===================================================================


@pytest.mark.django_db(transaction=True)
class TestDatesDHistoriqueMemorisees:

    async def _deux_messages_espaces(self):
        from datetime import timedelta

        from django.utils import timezone

        from old.backend.memory.models import Conversation, Message

        conv = await Conversation.objects.acreate()
        ids = []
        for i, (texte, il_y_a) in enumerate((("avant", 0), ("apres", 3))):
            msg = await Message.objects.acreate(
                conversation=conv, role="user", content=texte,
            )
            await Message.objects.filter(pk=msg.pk).aupdate(
                created_at=timezone.now() - timedelta(days=3 - il_y_a),
            )
            ids.append(msg.pk)
        return ids

    async def test_le_second_appel_ne_relit_pas_la_base(self):
        from old.backend.pipeline import context_history as ctx_module

        ids = await self._deux_messages_espaces()
        for pk in ids:
            ctx_module._MESSAGE_DATES.pop(pk, None)
        history = [
            {"id": ids[0], "role": "user", "content": "avant"},
            {"id": ids[1], "role": "user", "content": "apres"},
        ]
        premier = await ctx_module._stamp_history_gaps(history)
        assert premier[1]["content"].startswith("[il y a")

        from old.backend.memory.models import Message

        with patch.object(Message.objects, "filter",
                          side_effect=AssertionError("relecture interdite")):
            second = await ctx_module._stamp_history_gaps(history)
        assert second == premier

    async def test_le_memo_reste_borne(self):
        from old.backend.pipeline import context_history as ctx_module

        ctx_module._MESSAGE_DATES.update({i: None for i in range(1, ctx_module._MESSAGE_DATES_MAX + 50)})
        ctx_module._prune_message_dates()
        assert len(ctx_module._MESSAGE_DATES) == ctx_module._MESSAGE_DATES_MAX
        assert 1 not in ctx_module._MESSAGE_DATES  # les plus anciens partent
        ctx_module._MESSAGE_DATES.clear()


# ===================================================================
# PIPE-11 — une persistance qui échoue n'est pas une panne d'IA
# ===================================================================


class TestPersistanceIsoleeDeLIA:

    def _patches(self, processor, question, reponse, ia):
        from old.backend.configs.service import config_service

        return [
            patch.object(config_service, "get", return_value=60),
            patch.object(processor, "call_ai_and_parse", new=ia),
            patch.object(processor, "gather_context", new=AsyncMock(return_value=_fake_context())),
            patch.object(processor.emotion_engine, "ensure_person_loaded", new=AsyncMock()),
            patch.object(processor.emotion_engine, "save_snapshot", new=AsyncMock()),
            patch.object(processor, "persist_user_message", new=question),
            patch.object(processor, "persist_assistant_message", new=reponse),
            patch.object(processor, "emit_communication_event", new=AsyncMock()),
            patch.object(processor, "publish_turn_completed", new=AsyncMock()),
            patch.object(processor, "_compute_thinking_delay", return_value=0.0),
            patch.object(processor, "broadcast_to_websocket", new=AsyncMock()),
        ]

    async def test_la_question_non_persistee_n_empeche_pas_la_reponse(self):
        from old.backend.pipeline import processor
        from old.backend.pipeline.perception import Perception
        from old.backend.utils.degradation import degradations

        ia = AsyncMock(return_value=("je réponds quand même", None, []))
        question = AsyncMock(side_effect=RuntimeError("database is locked"))
        reponse = AsyncMock(return_value=2)
        avant = degradations.total()
        with _stack(self._patches(processor, question, reponse, ia)):
            out = await processor.process_message(
                Perception.from_text("hey", source="frontend", person_id="web_pipe11")
            )
        assert not out.ai_failed and out.text == "je réponds quand même"
        ia.assert_awaited_once()
        assert out.user_message_id is None
        assert degradations.total() > avant

    async def test_la_reponse_non_persistee_n_est_pas_une_panne(self):
        from old.backend.pipeline import processor
        from old.backend.pipeline.perception import Perception

        ia = AsyncMock(return_value=("je réponds", None, []))
        question = AsyncMock(return_value=1)
        reponse = AsyncMock(side_effect=RuntimeError("database is locked"))
        with _stack(self._patches(processor, question, reponse, ia)):
            out = await processor.process_message(
                Perception.from_text("hey", source="frontend", person_id="web_pipe11b")
            )
        assert not out.ai_failed and out.text == "je réponds"
        assert out.message_id is None and out.user_message_id == 1


class _stack:
    def __init__(self, patches):
        self._patches = patches

    def __enter__(self):
        for p in self._patches:
            p.__enter__()

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.__exit__(*exc)


# ===================================================================
# DEF-14 / DEF-15 — les défauts revus
# ===================================================================


class TestDefautsRevus:

    def test_part_l5_a_quatre_pour_cent(self):
        from old.backend.ai.budget import L5_RECALL_SHARE
        from old.backend.ai.config_schema import CONFIG_SCHEMA
        from old.backend.configs.types import ConfigItem

        item = next(i for i in CONFIG_SCHEMA
                    if isinstance(i, ConfigItem) and i.key == "ai.context.l5_recall_share")
        assert L5_RECALL_SHARE == 0.04 == item.default

    def test_deadline_de_preparation_a_2500_ms(self):
        from old.backend.ai.config_schema import CONFIG_SCHEMA
        from old.backend.configs.types import ConfigItem

        item = next(i for i in CONFIG_SCHEMA
                    if isinstance(i, ConfigItem) and i.key == "ai.preparation.deadline_ms")
        assert item.default == 2500

    def test_hysteresis_declaree_et_egale_au_repli(self):
        from old.backend.ai.config_schema import CONFIG_SCHEMA
        from old.backend.configs.types import ConfigItem
        from old.backend.pipeline.prompt import _L3_TRIM_LOW_RATIO

        item = next(i for i in CONFIG_SCHEMA
                    if isinstance(i, ConfigItem) and i.key == "ai.context.l3_trim_low_ratio")
        assert item.default == _L3_TRIM_LOW_RATIO == 0.5
