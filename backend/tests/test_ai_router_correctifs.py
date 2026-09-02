"""Trois défauts du routeur IA, confirmés par audit.

1. ``ai.role.project_work`` n'était pas lu au démarrage : la table des clés
   de rôle était recopiée à la main et listait dix rôles sur onze, donc le
   lanceur de projets retombait sur ``memory_extraction`` à chaque
   redémarrage, sans rien dire.
2. Les jetons consommés par un appel en timeout ou en erreur n'étaient
   jamais comptés : les deux branches ``except`` relevaient l'exception sans
   relever l'usage, qui restait dans le ContextVar jusqu'à l'appel suivant.
3. Un appel routé *imbriqué* (un outil MCP relançant le modèle depuis la
   boucle d'outils) remettait le relevé à zéro et effaçait ce que la boucle
   englobante avait déjà cumulé.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from ai.quota import (
    _reset_usage,
    _restore_usage,
    _take_usage,
    _usage_ctx,
    set_usage,
)
from ai.router import AIRole, AIRouter


@pytest.fixture(autouse=True)
def _usage_vierge():
    """Aucun test ne doit hériter — ni léguer — un relevé d'usage."""
    _usage_ctx.set(None)
    yield
    _usage_ctx.set(None)


def _routeur_nu(provider: str = "claude") -> AIRouter:
    """Un routeur construit sans lire la configuration.

    Ce qui est testé est la comptabilité autour de ``invoke`` ; la
    résolution, le provider, la borne et le plafond sont dictés ici.
    """
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


# ===================================================================
# 1. Les clés de rôle dérivent de l'énumération
# ===================================================================

class TestRolesLusAuDemarrage:

    def test_chaque_role_de_l_enumeration_a_sa_cle_declaree(self):
        """Le tableau de bord déclare une clé par rôle — sans exception."""
        from ai.config_schema import CONFIG_SCHEMA

        cles = {getattr(item, "key", None) for item in CONFIG_SCHEMA}
        manquants = [r.value for r in AIRole if f"ai.role.{r.value}" not in cles]
        assert manquants == []

    def test_chaque_cle_de_role_declaree_nomme_un_membre(self):
        """L'inverse : une clé ``ai.role.*`` sans membre serait un réglage
        que le routeur ne pourrait jamais lire."""
        from ai.config_schema import CONFIG_SCHEMA

        valeurs = {r.value for r in AIRole}
        orphelines = [
            item.key for item in CONFIG_SCHEMA
            if getattr(item, "key", "").startswith("ai.role.")
            and item.key.removeprefix("ai.role.") not in valeurs
        ]
        assert orphelines == []

    def _routeur_avec(self, valeurs: dict[str, str]) -> AIRouter:
        from configs.service import config_service

        def _get(key, default=""):
            return valeurs.get(key, default)

        with patch.object(config_service, "get", side_effect=_get), \
             patch.object(config_service, "on_change"):
            return AIRouter()

    def test_project_work_est_lu_au_demarrage(self):
        """Le défaut confirmé : mappé dans le tableau de bord, ignoré au boot."""
        r = self._routeur_avec({"ai.role.project_work": "atelier"})
        assert r._role_to_internal.get(AIRole.PROJECT_WORK) == "atelier"

    def test_tous_les_roles_mappes_sont_lus_au_demarrage(self):
        """Un nouveau membre de l'énumération est lu sans qu'on y pense."""
        valeurs = {f"ai.role.{r.value}": f"m-{r.value}" for r in AIRole}
        r = self._routeur_avec(valeurs)
        assert r._role_to_internal == {r_: f"m-{r_.value}" for r_ in AIRole}

    def test_un_role_non_mappe_reste_absent(self):
        r = self._routeur_avec({"ai.role.conversation": "principal"})
        assert AIRole.PROJECT_WORK not in r._role_to_internal


# ===================================================================
# 2. L'usage d'un appel raté est comptabilisé
# ===================================================================

class TestUsagePartielComptabilise:

    async def test_une_exception_apres_generation_compte_ses_jetons(self, monkeypatch):
        """Le provider a remonté son usage, puis quelque chose a levé (un
        handler hors boucle, un 4xx au second tour) : ces jetons ont été
        facturés et doivent atteindre le quota."""
        from ai import router as router_module

        traqueur = _traqueur()
        monkeypatch.setattr(router_module, "quota_tracker", traqueur)
        r = _routeur_nu()

        async def invoke(provider, model, temperature, max_tokens):
            set_usage(100, 10)
            raise RuntimeError("second tour en erreur")

        with pytest.raises(RuntimeError):
            await r._metered_call(AIRole.CONVERSATION, "s", "u", invoke)

        assert traqueur.record.call_count == 1
        kw = traqueur.record.call_args.kwargs
        assert (kw["tokens_in"], kw["tokens_out"]) == (100, 10)
        assert kw["role"] == AIRole.CONVERSATION.value
        # Et rien ne traîne pour l'appel suivant.
        assert _usage_ctx.get() is None

    async def test_un_timeout_compte_les_iterations_deja_payees(self, monkeypatch):
        """Une boucle d'outils qui a répondu deux fois avant la borne."""
        from ai import router as router_module

        traqueur = _traqueur()
        monkeypatch.setattr(router_module, "quota_tracker", traqueur)
        r = _routeur_nu()

        async def invoke(provider, model, temperature, max_tokens):
            set_usage(400, 40)
            set_usage(500, 50)
            try:
                await asyncio.sleep(10)
            finally:
                # Le provider Claude relève dans un ``finally`` — la
                # remontée à l'annulation est ce qu'on veut voir comptée.
                set_usage(0, 3)
            return "jamais", "jamais"

        with pytest.raises(asyncio.TimeoutError):
            await r._metered_call(
                AIRole.CONVERSATION_TOOLS, "s", "u", invoke, timeout=0.05,
            )

        assert traqueur.record.call_count == 1
        kw = traqueur.record.call_args.kwargs
        assert (kw["tokens_in"], kw["tokens_out"]) == (900, 93)

    async def test_un_echec_sans_usage_n_enregistre_rien(self, monkeypatch):
        """Un appel mort avant toute réponse n'a rien consommé : pas de ligne
        fantôme, et surtout pas une estimation."""
        from ai import router as router_module

        traqueur = _traqueur()
        monkeypatch.setattr(router_module, "quota_tracker", traqueur)
        r = _routeur_nu()

        async def invoke(provider, model, temperature, max_tokens):
            raise ConnectionError("refusée")

        with pytest.raises(ConnectionError):
            await r._metered_call(AIRole.CONVERSATION, "s", "u", invoke)
        traqueur.record.assert_not_called()

    async def test_la_comptabilite_ne_masque_jamais_l_erreur_d_origine(self, monkeypatch):
        from ai import router as router_module

        traqueur = _traqueur()
        traqueur.record.side_effect = RuntimeError("base verrouillée")
        monkeypatch.setattr(router_module, "quota_tracker", traqueur)
        r = _routeur_nu()

        async def invoke(provider, model, temperature, max_tokens):
            set_usage(10, 1)
            raise ValueError("l'erreur qui compte")

        with pytest.raises(ValueError, match="l'erreur qui compte"):
            await r._metered_call(AIRole.CONVERSATION, "s", "u", invoke)


# ===================================================================
# 3. Le relevé est une fenêtre, pas une remise à zéro
# ===================================================================

class TestFenetreDeReleve:

    def test_refermer_la_fenetre_rend_le_releve_englobant(self):
        set_usage(100, 10)
        jeton = _reset_usage()
        set_usage(5, 5)
        assert _take_usage() == {"in": 5, "out": 5}
        _restore_usage(jeton)
        assert _usage_ctx.get() == {"in": 100, "out": 10}

    def test_refermer_sans_jeton_est_sans_effet(self):
        set_usage(1, 1)
        _restore_usage(None)
        assert _usage_ctx.get()["in"] == 1

    async def test_un_appel_imbrique_n_efface_pas_le_cumul_de_son_appelant(self, monkeypatch):
        """Le scénario réel : la boucle d'outils a déjà cumulé une itération,
        un outil relance le routeur, la boucle continue et cumule encore. Le
        tour doit facturer les trois, pas seulement ce qui suit l'outil."""
        from ai import router as router_module

        traqueur = _traqueur()
        monkeypatch.setattr(router_module, "quota_tracker", traqueur)
        r = _routeur_nu()

        async def interne(provider, model, temperature, max_tokens):
            set_usage(5, 5)
            return "interne", "interne"

        async def externe(provider, model, temperature, max_tokens):
            set_usage(100, 10)
            await r._metered_call(AIRole.VISION_CAPTION, "s", "u", interne)
            set_usage(1, 1)
            return "externe", "externe"

        await r._metered_call(AIRole.CONVERSATION_TOOLS, "s", "u", externe)

        par_role = {
            c.kwargs["role"]: (c.kwargs["tokens_in"], c.kwargs["tokens_out"])
            for c in traqueur.record.call_args_list
        }
        assert par_role[AIRole.VISION_CAPTION.value] == (5, 5)
        assert par_role[AIRole.CONVERSATION_TOOLS.value] == (101, 11)
        assert _usage_ctx.get() is None
