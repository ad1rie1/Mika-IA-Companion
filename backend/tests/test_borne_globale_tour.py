"""Borne globale du tour + terme « outils » du budget.

Deux trous qui se tenaient : ``tools_chars`` était un paramètre mort (aucun
appelant ne le passait, donc la soustraction valait toujours 0), et la SOMME
des blocs n'était mesurée nulle part — chacun portait son plafond, personne
ne portait le total. Au-delà de la fenêtre, un provider tronque **par la
tête** : le préfixe stable, c'est-à-dire la personnalité.

Les chiffres ici sont volontairement des chiffres. Un smoke test qui vérifie
« ça ne plante pas » n'aurait rien dit du seul fait qui compte : le pire cas
assemblé tient-il, oui ou non, dans la fenêtre de repli de 16 384.
"""

from __future__ import annotations

import pytest

import ai.budget as budget_mod
from ai.budget import (
    _TRIM_ORDER,
    ContextBudget,
    build_budget,
    conversation_l3_chars,
    default_window_tokens,
    fit_turn,
    measure_turn,
    tool_weight,
    tools_prompt_chars,
)
from ai.chat import SUMMARY_MAX_CHARS, ChatPrompt, VolatileBlock


@pytest.fixture(autouse=True)
def _releve_vierge():
    """``tool_weight`` est un singleton de process : un test qui le remplit
    ne doit pas dimensionner le suivant."""
    tool_weight._chars.clear()
    yield
    tool_weight._chars.clear()


@pytest.fixture()
def ratio_fixe(monkeypatch):
    """``usage_ratio`` est un réglage : le figer isole l'arithmétique."""
    monkeypatch.setattr(budget_mod, "_usage_ratio", lambda: 0.5)


class _Tool:
    def __init__(self, name, description, schema):
        self.name = name
        self.description = description
        self._schema = schema

    def to_json_schema(self):
        return self._schema


# ---------------------------------------------------------------------------
# 1. Le poids des déclarations d'outils
# ---------------------------------------------------------------------------


class TestPoidsOutils:

    def test_compte_nom_description_et_schema(self):
        tool = _Tool("memory_search", "cherche", {"type": "object"})
        expected = len("memory_search") + len("cherche") + len('{"type": "object"}')
        assert tools_prompt_chars([tool]) == expected

    def test_un_objet_exotique_ne_casse_pas_le_dimensionnement(self):
        class Bancal:
            name = "x"
            description = "y"

            def to_json_schema(self):
                raise RuntimeError("boom")

        # Ce que le schéma illisible coûte est perdu, le reste est compté :
        # un dimensionnement ne s'interrompt pas sur un outil bancal.
        assert tools_prompt_chars([Bancal(), _Tool("a", "b", {})]) == (
            len("x") + len("y") + len("a") + len("b") + len("{}")
        )

    def test_aucun_outil_vaut_zero(self):
        assert tools_prompt_chars([]) == 0
        assert tools_prompt_chars(None) == 0

    def test_parite_avec_l_estimation_du_routeur(self):
        """Le routeur porte la même arithmétique pour le contrôle de quota.
        Tant que les deux coexistent, elles doivent rendre la même valeur."""
        from ai.router import _tools_prompt_chars

        tools = [
            _Tool("memory_search", "cherche des souvenirs",
                  {"type": "object", "properties": {"q": {"type": "string"}}}),
            _Tool("forge_write_module", "écrit un module", {"type": "object"}),
        ]
        assert tools_prompt_chars(tools) == _tools_prompt_chars(tools)


class TestReleveOutils:

    def test_le_releve_est_soustrait_du_budget(self, monkeypatch, ratio_fixe):
        from ai import router as router_mod
        from ai.router import AIRole

        monkeypatch.setattr(
            router_mod.ai_router, "resolve",
            lambda role: ("claude", "model-x", 0.7, "x"),
        )
        monkeypatch.setattr(
            router_mod.ai_router, "_get_declared_models",
            lambda: {"x": {"context_window": 200_000, "max_tokens": 8_000}},
        )
        sans = budget_mod.budget_for(AIRole.CONVERSATION)
        tool_weight.note(AIRole.CONVERSATION.value, 26_000)
        avec = budget_mod.budget_for(AIRole.CONVERSATION)
        assert avec.tools_tokens == 6_500
        assert sans.usable_tokens - avec.usable_tokens == 6_500

    def test_un_zero_explicite_ignore_le_releve(self, monkeypatch, ratio_fixe):
        from ai import router as router_mod
        from ai.router import AIRole

        monkeypatch.setattr(
            router_mod.ai_router, "resolve",
            lambda role: ("claude", "model-x", 0.7, "x"),
        )
        monkeypatch.setattr(
            router_mod.ai_router, "_get_declared_models",
            lambda: {"x": {"context_window": 200_000, "max_tokens": 8_000}},
        )
        tool_weight.note(AIRole.CONVERSATION.value, 26_000)
        assert budget_mod.budget_for(
            AIRole.CONVERSATION, tools_chars=0,
        ).tools_tokens == 0

    def test_un_role_jamais_mesure_vaut_zero(self):
        from ai.router import AIRole

        tool_weight.note(AIRole.CONVERSATION.value, 26_000)
        assert tool_weight.chars_for(AIRole.MEMORY_EXTRACTION.value) == 0


class TestL3AvecOutils:
    """Le chiffre qui montre que le terme n'est plus mort."""

    def test_le_budget_l3_recule_du_poids_des_outils(self, ratio_fixe):
        from ai.router import AIRole

        assert default_window_tokens() == 16_384
        # 16384×0.5 − 4096 sortie − 819 marge = 3277 utilisables ; ×0.60 ×4.
        assert conversation_l3_chars() == 7_864

        tool_weight.note(AIRole.CONVERSATION.value, 26_000)
        # −6 500 tokens d'outils : plus rien d'utilisable, le plancher reprend.
        assert conversation_l3_chars() == 4_000

    def test_un_zero_explicite_reste_sans_outils(self, ratio_fixe):
        from ai.router import AIRole

        tool_weight.note(AIRole.CONVERSATION.value, 26_000)
        assert conversation_l3_chars(0) == 7_864


# ---------------------------------------------------------------------------
# 2. Les blocs volatils restent séparables de leur en-tête
# ---------------------------------------------------------------------------


class TestInvariantBlocsVolatiles:

    def test_render_reproduit_le_rendu_des_couches(self):
        from pipeline.prompt import _LAYERS, _render_layer

        for layer in _LAYERS:
            block = VolatileBlock(
                field=layer.field, value="valeur",
                header=layer.header, footer=layer.footer,
            )
            assert block.render() == _render_layer(layer, "valeur")

    def test_un_header_absent_rend_la_valeur_brute(self):
        assert VolatileBlock("memory_context", "brut").render() == "brut"

    def test_la_concatenation_des_blocs_est_le_volatile(self):
        blocks = [
            VolatileBlock("person_context", "p", "--- P ---"),
            VolatileBlock("memory_context", "m"),
        ]
        prompt = ChatPrompt(
            system_stable="S",
            system_volatile="\n\n".join(b.render() for b in blocks),
            volatile_blocks=blocks,
            message="m",
        )
        assert prompt.system_volatile == "--- P ---\np\n--- FIN ---\n\nm"


# ---------------------------------------------------------------------------
# 3. La borne elle-même
# ---------------------------------------------------------------------------


def _blocks(**values) -> list[VolatileBlock]:
    return [
        VolatileBlock(field=f, value=v, header=f"--- {f.upper()} ---")
        for f, v in values.items()
    ]


def _prompt(blocks, *, summary="", message="question ?") -> ChatPrompt:
    return ChatPrompt(
        system_stable="PERSONNALITE",
        system_volatile="\n\n".join(b.render() for b in blocks),
        history=[{"role": "user", "content": "salut"}],
        message=message,
        conversation_summary=summary,
        volatile_blocks=list(blocks),
    )


class TestFitTurn:

    def test_un_tour_qui_tient_n_est_pas_touche(self, ratio_fixe):
        prompt = _prompt(_blocks(memory_context="m" * 100))
        out, fit = fit_turn(prompt, build_budget(200_000, max_tokens=4_000))
        assert fit.trimmed == ()
        assert fit.overflow_tokens == 0
        assert out is prompt

    def test_l_ordre_declare_est_respecte(self, ratio_fixe):
        blocks = _blocks(
            module_context="a" * 4_000,
            person_context="b" * 4_000,
            memory_context="c" * 4_000,
        )
        prompt = _prompt(blocks)
        # Place juste insuffisante : un seul cran de l'ordre doit suffire.
        budget = ContextBudget(
            window_tokens=10_000, usable_tokens=1_000, chars_per_token=4.0,
            max_tokens=6_800, tools_tokens=0,
        )
        out, fit = fit_turn(prompt, budget)
        assert fit.trimmed == ("module_context",)
        by_field = {b.field: b.value for b in out.volatile_blocks}
        assert by_field["module_context"] == ""
        assert by_field["person_context"] == "b" * 4_000
        assert by_field["memory_context"] == "c" * 4_000

    def test_la_memoire_est_coupee_en_dernier_et_jamais_sous_son_plancher(self, ratio_fixe):
        blocks = _blocks(
            module_context="a" * 8_000,
            person_context="b" * 8_000,
            project_context="c" * 8_000,
            memory_context="d" * 8_000,
        )
        prompt = _prompt(blocks, summary="r" * SUMMARY_MAX_CHARS)
        budget = ContextBudget(
            window_tokens=10_000, usable_tokens=500, chars_per_token=4.0,
            max_tokens=9_000, tools_tokens=0,
        )
        out, fit = fit_turn(prompt, budget)
        assert fit.trimmed[-1] == "memory_context"
        by_field = {b.field: b.value for b in out.volatile_blocks}
        assert len(by_field["memory_context"]) == 1_200
        assert len(by_field["person_context"]) == 400
        assert len(out.conversation_summary) == 2_000

    def test_le_prefixe_stable_et_le_message_survivent_a_tout(self, ratio_fixe):
        prompt = _prompt(
            _blocks(memory_context="d" * 50_000, module_context="a" * 50_000),
            summary="r" * SUMMARY_MAX_CHARS,
            message="ma question",
        )
        budget = ContextBudget(
            window_tokens=1_000, usable_tokens=0, chars_per_token=4.0,
            max_tokens=900, tools_tokens=0,
        )
        out, fit = fit_turn(prompt, budget)
        assert out.system_stable == "PERSONNALITE"
        assert out.message == "ma question"
        assert out.history == prompt.history
        # Coupé jusqu'aux planchers, ça ne tient toujours pas : c'est dit,
        # ce n'est pas silencieusement rogné plus bas.
        assert fit.overflow_tokens > 0

    def test_le_prompt_d_entree_n_est_pas_mute(self, ratio_fixe):
        blocks = _blocks(module_context="a" * 8_000, memory_context="d" * 8_000)
        prompt = _prompt(blocks, summary="r" * 6_000)
        avant_volatile = prompt.system_volatile
        avant_resume = prompt.conversation_summary
        budget = ContextBudget(
            window_tokens=10_000, usable_tokens=500, chars_per_token=4.0,
            max_tokens=9_000, tools_tokens=0,
        )
        out, _ = fit_turn(prompt, budget)
        assert prompt.system_volatile == avant_volatile
        assert prompt.conversation_summary == avant_resume
        assert prompt.volatile_blocks[0].value == "a" * 8_000
        assert out.system_volatile != avant_volatile

    def test_sans_blocs_seul_le_resume_bouge(self, ratio_fixe):
        prompt = ChatPrompt(
            system_stable="PERSONNALITE",
            system_volatile="--- M ---\n" + "d" * 40_000 + "\n--- FIN ---",
            message="q",
            conversation_summary="r" * SUMMARY_MAX_CHARS,
        )
        budget = ContextBudget(
            window_tokens=10_000, usable_tokens=500, chars_per_token=4.0,
            max_tokens=9_000, tools_tokens=0,
        )
        out, fit = fit_turn(prompt, budget)
        # Couper à l'aveugle dans un volatile déjà rendu laisserait un
        # en-tête sans sa fin : on ne touche rien, on rapporte.
        assert fit.trimmed == ("conversation_summary",)
        assert out.system_volatile == prompt.system_volatile
        assert fit.overflow_tokens > 0

    def test_le_depassement_de_usable_est_rapporte_sans_etre_agi(self, ratio_fixe):
        prompt = _prompt(_blocks(memory_context="m" * 20_000))
        # Fenêtre large, `usable_tokens` volontairement minuscule.
        budget = ContextBudget(
            window_tokens=200_000, usable_tokens=10, chars_per_token=4.0,
            max_tokens=4_000, tools_tokens=0,
        )
        out, fit = fit_turn(prompt, budget)
        assert fit.trimmed == ()
        assert fit.soft_overflow_tokens > 0
        assert fit.overflow_tokens == 0
        assert out is prompt

    def test_un_budget_absent_laisse_le_tour_intact(self, ratio_fixe):
        prompt = _prompt(_blocks(memory_context="m" * 20_000))
        out, fit = fit_turn(prompt, None)
        assert out is prompt
        assert fit.trimmed == () and fit.overflow_tokens == 0

    def test_ne_leve_jamais(self, ratio_fixe):
        class Bidon:
            chars_per_token = 4.0

            def window_room(self):
                raise RuntimeError("budget cassé")

        prompt = _prompt(_blocks(memory_context="m" * 100))
        out, fit = fit_turn(prompt, Bidon())
        assert out is prompt
        assert fit.trimmed == ()

    def test_l_ordre_declare_finit_par_la_memoire(self):
        assert _TRIM_ORDER[-1][0] == "memory_context"
        assert dict(_TRIM_ORDER)["memory_context"] == 1_200


class TestMeasureTurn:

    def test_mesure_le_rendu_pas_les_champs(self):
        prompt = ChatPrompt(
            system_stable="S" * 400,
            system_volatile="V" * 400,
            history=[{"role": "user", "content": "h" * 400}],
            message="m" * 400,
        )
        rendu = len(prompt.system_stable) + sum(
            len(m["content"]) for m in prompt.chat_messages()
        )
        assert measure_turn(prompt) == int(rendu / 4.0)

    def test_le_clip_par_message_est_compte_une_fois_clippe(self):
        from ai.chat import HISTORY_MSG_MAX_CHARS

        prompt = ChatPrompt(
            system_stable="",
            history=[{"role": "user", "content": "x" * 100_000}],
            message="",
        )
        assert measure_turn(prompt) <= int(HISTORY_MSG_MAX_CHARS / 4.0) + 1


# ---------------------------------------------------------------------------
# 4. Le pire cas, contre la fenêtre de repli de 16 384
# ---------------------------------------------------------------------------


# Plafonds des blocs qui n'en déclarent pas un dans le code (leur taille est
# celle de leur gabarit rempli). Généreux : c'est un pire cas.
_CAPS_LIBRES = {
    "person_context": 2_500,
    "user_mood_hint": 300,
    "circadian_context": 300,
    "fatigue_fog": 400,
    "rumination_context": 1_200,
    # 3 en-cours (titre ≤140 + habillage) + 2 aboutis du jour + l'intro.
    "travaux_context": 1_200,
    "dream_context": 600,
    "journal_context": 700,
    "emotion_context": 900,
    "note_de_focus": 400,
}


def _pire_cas() -> ChatPrompt:
    """Le tour le plus lourd que le pipeline puisse assembler aujourd'hui,
    construit à partir des plafonds RÉELS de chaque bloc."""
    from config.personality import personality
    from memory.retrieval.retriever import MemoryRetriever
    from pipeline.context import (
        _MODULE_CONTEXT_MAX_CHARS,
        _PROJECT_LIST_ITEMS_MAX,
        _PROJECT_TEXT_MAX_CHARS,
        _SELF_CONCEPT_MAX_CHARS,
    )
    from pipeline.prompt import _LAYERS, _STABLE_LAYER_COUNT

    caps = dict(_CAPS_LIBRES)
    caps["module_context"] = _MODULE_CONTEXT_MAX_CHARS
    caps["project_context"] = _PROJECT_TEXT_MAX_CHARS * (2 + 2 * _PROJECT_LIST_ITEMS_MAX)
    caps["memory_context"] = MemoryRetriever.MAX_CONTEXT_CHARS

    stable = personality.to_system_prompt()
    stable += "\n\n--- QUI TU ES DEVENUE ---\n" + "s" * _SELF_CONCEPT_MAX_CHARS + "\n--- FIN ---"
    stable += "\n\n--- QUI TU AS EN FACE ---\n" + "i" * 900 + "\n--- FIN ---"

    blocks = [
        VolatileBlock(
            field=layer.field, value="x" * caps[layer.field],
            header=layer.header, footer=layer.footer,
        )
        for layer in _LAYERS[_STABLE_LAYER_COUNT:]
    ]
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "h" * 400}
        for i in range(conversation_l3_chars() // 400)
    ]
    return ChatPrompt(
        system_stable=stable,
        system_volatile="\n\n".join(b.render() for b in blocks),
        history=history,
        message="m" * 500,
        conversation_summary="r" * SUMMARY_MAX_CHARS,
        volatile_blocks=blocks,
    )


class TestPireCas16384:
    """L'arithmétique du constat, rejouée contre le correctif.

    Le budget PHYSIQUE compte toujours les outils : les ~26 000 caractères de
    déclarations partent sur le fil que le budget les ait comptés ou non.
    Ce que le relevé change, c'est la part d'historique que L3 accorde.
    """

    def _budget(self):
        return build_budget(16_384, tools_chars=26_000)

    def test_la_place_physique_est_de_4969_tokens(self, ratio_fixe):
        # 16384 − 4096 (sortie) − 6500 (outils) − 819 (marge 5 %) = 4969.
        assert self._budget().window_room() == 4_969

    def test_le_pire_cas_deborde_avant_la_borne(self, ratio_fixe):
        from ai.router import AIRole

        tool_weight.note(AIRole.CONVERSATION.value, 26_000)
        budget = self._budget()
        avant = measure_turn(_pire_cas(), chars_per_token=budget.chars_per_token)
        assert avant > budget.window_room()
        assert budget.window_overflow(avant) > 0

    def test_apres_la_borne_le_pire_cas_tient_et_la_memoire_survit(self, ratio_fixe):
        from ai.router import AIRole

        tool_weight.note(AIRole.CONVERSATION.value, 26_000)
        budget = self._budget()
        out, fit = fit_turn(_pire_cas(), budget)
        assert fit.overflow_tokens == 0
        assert fit.prompt_tokens_after <= budget.window_room()
        # La mémoire ferme l'ordre de coupe : elle n'est pas atteinte.
        assert "memory_context" not in fit.trimmed
        memoire = {b.field: b.value for b in out.volatile_blocks}["memory_context"]
        assert len(memoire) == 4_000

    def test_sans_le_terme_outils_la_borne_doit_manger_la_memoire(self, ratio_fixe):
        """(a) et (b) sont nécessaires ensemble.

        Relevé à 0 : L3 accorde 7 864 caractères d'historique au lieu de
        4 000, pour la même place physique. La coupe descend alors jusqu'au
        dernier cran et rogne le rappel mémoire — le bloc qu'on protège.
        """
        budget = self._budget()
        out, fit = fit_turn(_pire_cas(), budget)
        assert "memory_context" in fit.trimmed
        memoire = {b.field: b.value for b in out.volatile_blocks}["memory_context"]
        assert len(memoire) == 1_200


# ---------------------------------------------------------------------------
# 5. Le câblage : la borne s'applique au tour que le pipeline assemble
# ---------------------------------------------------------------------------
#
# Les quatre sections précédentes mesurent `ai.budget` en isolation. Elles
# passaient toutes pendant que la borne était INERTE : `tools_chars` n'avait
# aucun appelant et `volatile_blocks` arrivait vide, donc `fit_turn` ne
# pouvait couper que le résumé et se contentait de rapporter le dépassement.
# Ce qui suit part du seul objet qui compte — le `ChatPrompt` que
# `build_chat_prompt` remet au provider.


# Les modules qui déclarent des outils, construits depuis leurs CLASSES et non
# via `module_manager` : la charge à mesurer est celle du code embarqué, pas
# celle des modules qu'un environnement de test aurait démarrés (aucun).
_MODULES_OUTILLES = (
    ("memory.module", "MemoryToolsModule"),
    ("conscience.module", "ConscienceToolsModule"),
    ("identity.module", "IdentityToolsModule"),
    ("projects.tools", "ProjectToolsModule"),
    ("files.module", "FilesModule"),
    ("modules.plugins.forge.module", "ForgeModule"),
    ("modules.plugins.rss.module", "RSSModule"),
    ("modules.plugins.wake.module", "WakeModule"),
)


def _outils_reels() -> list:
    import importlib

    tools: list = []
    for path, cls_name in _MODULES_OUTILLES:
        module = importlib.import_module(path)
        tools.extend(getattr(module, cls_name)().return_tools())
    return tools


def _contexte_charge(tools: list):
    """Un tour lourd mais réel : chaque couche à SON plafond de production.

    Rien d'inventé ici — les valeurs viennent de `pipeline.context` et du
    retriever. C'est le tour d'une conversation installée : profil rempli,
    projet actif, rappel mémoire dense, fil long, résumé de compaction.
    """
    from memory.retrieval.retriever import MemoryRetriever
    from pipeline.context import (
        _MODULE_CONTEXT_MAX_CHARS,
        _PROJECT_LIST_ITEMS_MAX,
        _PROJECT_TEXT_MAX_CHARS,
        _SELF_CONCEPT_MAX_CHARS,
        ConversationContext,
    )

    caps = dict(_CAPS_LIBRES)
    caps["module_context"] = _MODULE_CONTEXT_MAX_CHARS
    caps["project_context"] = _PROJECT_TEXT_MAX_CHARS * (2 + 2 * _PROJECT_LIST_ITEMS_MAX)
    caps["memory_context"] = MemoryRetriever.MAX_CONTEXT_CHARS

    return ConversationContext(
        self_concept="s" * _SELF_CONCEPT_MAX_CHARS,
        identity_context="i" * 900,
        tools=tools,
        history=[
            {"role": "user" if i % 2 == 0 else "assistant", "content": "h" * 400}
            for i in range(40)
        ],
        conversation_summary="r" * SUMMARY_MAX_CHARS,
        **{field: "x" * n for field, n in caps.items()},
    )


def _tour_sans_borne(context) -> ChatPrompt:
    """Le tour tel qu'il partait AVANT ce câblage.

    L'historique était déjà borné, mais par un budget L3 aveugle aux outils
    (le relevé n'avait aucun alimentateur, donc valait 0), et rien ne mesurait
    la somme.
    """
    from pipeline.prompt import _trim_history_to_l3, build_prompt_parts

    stable, volatile = build_prompt_parts(context)
    history, _ = _trim_history_to_l3(
        list(context.history), conversation_l3_chars(0),
    )
    return ChatPrompt(
        system_stable=stable,
        system_volatile=volatile,
        history=history,
        message="m" * 500,
        conversation_summary=context.conversation_summary,
    )


@pytest.fixture()
def fenetre_16k(monkeypatch, ratio_fixe):
    """Rôle conversation derrière un modèle de 16 384 jetons.

    C'est la fenêtre de repli du moteur, et celle d'un 8B local — le cas où
    la troncature par la tête est certaine. Figé ici plutôt que lu de
    l'install : la calibration chars→jetons est un EMA de process.
    """
    from ai import router as router_mod
    from ai.calibration import calibration

    monkeypatch.setattr(
        router_mod.ai_router, "resolve",
        lambda role: ("claude", "model-16k", 0.7, "x"),
    )
    monkeypatch.setattr(
        router_mod.ai_router, "_get_declared_models",
        lambda: {"x": {"context_window": 16_384, "max_tokens": 4_096}},
    )
    monkeypatch.setattr(calibration, "ratio", lambda provider: 4.0)


class TestCablagePipeline:
    """Le tour assemblé par `build_chat_prompt`, contre 16 384 jetons."""

    @staticmethod
    def _budget(tools):
        return build_budget(
            16_384, max_tokens=4_096, tools_chars=tools_prompt_chars(tools),
        )

    def test_les_declarations_reelles_pesent_un_quart_de_la_fenetre(self):
        chars = tools_prompt_chars(_outils_reels())
        # ~19 600 caractères aujourd'hui, soit ~4 900 jetons. Le plancher est
        # large à dessein : la valeur exacte bouge à chaque description
        # d'outil retouchée, le fait qu'elle pèse un quart de la fenêtre non.
        assert chars >= 15_000
        assert (chars / 4) / default_window_tokens() > 0.25

    def test_le_tour_reclamait_plus_que_la_fenetre_entiere(self, fenetre_16k):
        """Le constat S9, rejoué sur le tour que le pipeline assemble vraiment.

        Ce qu'un tour réclame = prompt + déclarations d'outils + la sortie
        qu'il faut bien pouvoir écrire dans la même fenêtre.
        """
        tools = _outils_reels()
        avant = _tour_sans_borne(_contexte_charge(tools))
        budget = self._budget(tools)
        demande = measure_turn(avant) + budget.tools_tokens + budget.max_tokens
        # ~18 900 depuis que la part L5 vaut 0,04 (DEF-14) ; l'ordre de
        # grandeur — plus que la fenêtre entière — est ce qui compte.
        assert demande > 18_000
        assert demande / 16_384 > 1.15
        assert budget.window_overflow(measure_turn(avant)) > 0

    def test_le_meme_tour_tient_desormais(self, fenetre_16k):
        from pipeline.prompt import build_chat_prompt

        tools = _outils_reels()
        prompt = build_chat_prompt(_contexte_charge(tools), "m" * 500)
        budget = self._budget(tools)
        apres = measure_turn(prompt, chars_per_token=budget.chars_per_token)
        assert apres <= budget.window_room()
        assert budget.window_overflow(apres) == 0

    def test_ce_que_la_coupe_epargne(self, fenetre_16k):
        """Exactement ce que la troncature par la tête aurait détruit."""
        from pipeline.prompt import _assemble, build_chat_prompt

        tools = _outils_reels()
        context = _contexte_charge(tools)
        stable_attendu, _ = _assemble(context)
        prompt = build_chat_prompt(context, "ma question")

        assert prompt.system_stable == stable_attendu
        assert prompt.message == "ma question"
        blocs = {b.field: b.value for b in prompt.volatile_blocks}
        assert blocs["memory_context"] == context.memory_context
        assert blocs["person_context"] == context.person_context

    def test_la_coupe_suit_l_ordre_declare_sans_sauter_de_cran(self, fenetre_16k):
        from pipeline.prompt import build_chat_prompt

        tools = _outils_reels()
        context = _contexte_charge(tools)
        prompt = build_chat_prompt(context, "m" * 500)

        apres = {b.field: b.value for b in prompt.volatile_blocks}
        ordre = [f for f, _ in _TRIM_ORDER if f in apres]
        coupes = [f for f in ordre if len(apres[f]) < len(getattr(context, f))]
        assert coupes, "aucune couche coupée : le tour tenait déjà, le test ne dit rien"
        assert coupes == ordre[:len(coupes)]

    def test_la_coupe_se_voit(self, fenetre_16k, caplog):
        """Une troncature silencieuse est ce que l'audit reproche partout.

        Deux traces : le journal nomme les couches réduites et les leviers,
        et un bloc coupé *sans* disparaître porte sa marque dans le prompt.
        """
        import logging

        from pipeline.prompt import build_chat_prompt

        with caplog.at_level(logging.WARNING, logger="ai.budget"):
            prompt = build_chat_prompt(_contexte_charge(_outils_reels()), "m" * 500)

        message = "\n".join(r.getMessage() for r in caplog.records)
        assert "Tour trop large pour la fenêtre" in message
        assert "module_context" in message
        assert "ai.conversation_tool_modules" in message
        assert "[coupé faute de place]" in prompt.conversation_summary

    def test_sans_les_blocs_la_borne_n_a_presque_pas_de_prise(self, fenetre_16k):
        """Non-vacuité du geste (b) : sans les `VolatileBlock`, le même tour
        déborde encore une fois le résumé coupé — couper à l'aveugle dans un
        volatile déjà rendu laisserait un en-tête sans sa fin."""
        tools = _outils_reels()
        prompt = _tour_sans_borne(_contexte_charge(tools))
        assert prompt.volatile_blocks == []
        out, fit = fit_turn(prompt, self._budget(tools))
        assert fit.trimmed == ("conversation_summary",)
        assert fit.overflow_tokens > 0

    def test_sans_le_terme_outils_la_borne_croit_que_le_tour_tient(self, fenetre_16k):
        """Non-vacuité du geste (a) : une place calculée sans les outils est
        un mensonge de ~4 900 jetons, et la borne laisse passer un tour qui
        réclame 1,2× la fenêtre."""
        tools = _outils_reels()
        avant = measure_turn(_tour_sans_borne(_contexte_charge(tools)))
        assert build_budget(
            16_384, max_tokens=4_096, tools_chars=0,
        ).window_overflow(avant) == 0
        assert self._budget(tools).window_overflow(avant) > 0

    def test_le_poids_des_outils_borne_l_historique(self, fenetre_16k):
        """Geste (a) côté L3 : le fil vivant recule du poids des outils."""
        from pipeline.prompt import build_chat_prompt

        tools = _outils_reels()
        context = _contexte_charge(tools)
        avec = build_chat_prompt(context, "m" * 500)
        sans = _tour_sans_borne(context)
        # L'hystérésis d'élagage (PIPE-04) ramène chaque fil à la moitié de
        # sa borne : 4 000 → ≤ 2 000 avec les outils, 7 864 → ~3 900 sans.
        # L'écart entre les deux est ce que ce test mesure.
        poids_avec = sum(len(m["content"]) for m in avec.history)
        poids_sans = sum(len(m["content"]) for m in sans.history)
        assert poids_avec <= 4_000
        assert poids_sans > 3_000
        assert poids_sans > poids_avec

    def test_le_releve_est_depose_pour_la_compaction(self, fenetre_16k):
        """La compaction décide *quand* replier le fil et appelle
        `conversation_l3_chars()` sans argument : sans ce dépôt elle viserait
        7 864 caractères pendant que le rendu en enverrait 4 000."""
        from ai.router import AIRole
        from pipeline.prompt import build_chat_prompt

        tools = _outils_reels()
        build_chat_prompt(_contexte_charge(tools), "m")
        assert tool_weight.chars_for(AIRole.CONVERSATION.value) == tools_prompt_chars(tools)
        assert conversation_l3_chars() == conversation_l3_chars(tools_prompt_chars(tools))

    def test_un_tour_sans_outils_n_ecrase_pas_le_releve(self, fenetre_16k):
        """Un tour de conscience (`include_tools=False`) ne dit rien du poids
        d'un tour outillé — il ne doit pas faire osciller le watermark."""
        from ai.router import AIRole
        from pipeline.context import ConversationContext
        from pipeline.prompt import build_chat_prompt

        tool_weight.note(AIRole.CONVERSATION.value, 19_000)
        build_chat_prompt(ConversationContext(memory_context="rien"), "m")
        assert tool_weight.chars_for(AIRole.CONVERSATION.value) == 19_000

    def test_le_volatile_rendu_est_celui_que_la_borne_recompose(self, fenetre_16k):
        """`prompt.py` assemble les blocs, `fit_turn` les recompose après
        coupe : les deux formes doivent être la même, sinon un tour coupé ne
        ressemble plus à un tour intact."""
        from ai.budget import _rendered_volatile
        from pipeline.prompt import build_chat_prompt

        prompt = build_chat_prompt(_contexte_charge(_outils_reels()), "m" * 500)
        assert prompt.system_volatile == _rendered_volatile(prompt.volatile_blocks)


class TestOrdreDeCoupeEtTableDesCouches:
    """`_TRIM_ORDER` (ai/budget) et `_LAYERS` (pipeline/prompt) nomment les
    mêmes champs. Une couche renommée d'un côté rendrait l'entrée de l'autre
    silencieusement morte — soit une couche jamais coupée, soit un cran de
    l'ordre sans effet, dans les deux cas une coupe qui tombe ailleurs."""

    @staticmethod
    def _champs_volatils() -> list[str]:
        from pipeline.prompt import _LAYERS, _STABLE_LAYER_COUNT

        return [layer.field for layer in _LAYERS[_STABLE_LAYER_COUNT:]]

    def test_chaque_cran_nomme_une_couche_volatile_ou_le_resume(self):
        connus = set(self._champs_volatils()) | {"conversation_summary"}
        for field, _ in _TRIM_ORDER:
            assert field in connus, f"_TRIM_ORDER nomme '{field}', qui n'est pas une couche"

    def test_chaque_couche_volatile_a_son_cran(self):
        crans = {field for field, _ in _TRIM_ORDER}
        for field in self._champs_volatils():
            assert field in crans, (
                f"la couche '{field}' n'a pas de cran de coupe : la borne ne "
                f"peut pas la réduire et coupera plus fort ailleurs"
            )

    def test_les_couches_stables_ne_sont_jamais_coupables(self):
        """La personnalité, le self-concept et l'identité sont exactement ce
        que la troncature par la tête détruit."""
        from pipeline.prompt import _LAYERS, _STABLE_LAYER_COUNT

        crans = {field for field, _ in _TRIM_ORDER}
        for layer in _LAYERS[:_STABLE_LAYER_COUNT]:
            assert layer.field not in crans
