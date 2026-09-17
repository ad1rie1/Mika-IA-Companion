"""Budget d'appels de fond et disjoncteur par provider (REF-06, OPS-09).

Chaque mécanisme de la vie intérieure calculait son propre rythme et rien ne
les sommait ; un Ollama figé coûtait 120 s à chaque tour avant le texte de
repli. Ce fichier épingle les deux instruments du routeur qui répondent à ça :
un compteur glissant par heure, par provider, que seuls les appels *de fond*
consomment et qui refuse sans bruit ; et un disjoncteur qui coupe court après
k pannes de transport consécutives.

Les tests du routeur construisent un ``AIRouter`` par ``__new__`` et dictent
plafonds, réglages et horloge : ce qui est mesuré est la mécanique, pas le
chemin de lecture de la configuration (couvert à part, sur le registre).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.urls import reverse

from ai.cadence import (
    ROLES_AU_SERVICE_D_UN_HUMAIN,
    BudgetDeFondEpuise,
    CadenceDeFond,
    Disjoncteurs,
    ProviderIndisponible,
    _comptes,
    _de_fond,
    en_fond,
    est_panne_de_transport,
)
from ai.quota import QuotaExceeded, _usage_ctx
from ai.router import ROLES_DE_FOND, AIRole, AIRouter, UnconfiguredRoleError
from utils.degradation import degradations


class _Horloge:
    """Une horloge qu'on avance à la main."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def avancer(self, s: float) -> None:
        self.t += s


@pytest.fixture(autouse=True)
def _contexte_vierge():
    """Ni relevé d'usage, ni marqueur de fond, ni compte hérité d'un test."""
    _usage_ctx.set(None)
    _de_fond.set(False)
    _comptes.set(frozenset())
    yield
    _usage_ctx.set(None)
    _de_fond.set(False)
    _comptes.set(frozenset())


@pytest.fixture
def horloge():
    return _Horloge()


@pytest.fixture
def instruments(monkeypatch, horloge):
    """Un compteur et des disjoncteurs neufs, branchés sur le routeur."""
    from ai import router as router_module

    cadence = CadenceDeFond(horloge=horloge)
    disj = Disjoncteurs(horloge=horloge)
    monkeypatch.setattr(router_module, "cadence_de_fond", cadence)
    monkeypatch.setattr(router_module, "disjoncteurs", disj)
    traqueur = MagicMock()
    traqueur.record.return_value = 0.0
    monkeypatch.setattr(router_module, "quota_tracker", traqueur)
    return cadence, disj


def _routeur_nu(provider: str = "ollama", *, budgets: dict | None = None,
                seuil: int = 3, repos_s: float = 60.0) -> AIRouter:
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
    budgets = budgets if budgets is not None else {"ollama": 2}
    r._budget_de_fond = lambda name: budgets.get(name, 0)
    r._reglage_disjoncteur = lambda name: (seuil, repos_s)
    return r


async def _ok(provider, model, temperature, max_tokens):
    return "réponse", "réponse"


# ===================================================================
# 1. Le compteur glissant
# ===================================================================


class TestFenetreGlissante:

    def test_un_appel_de_plus_d_une_heure_sort_de_la_fenetre(self, horloge):
        c = CadenceDeFond(horloge=horloge)
        assert c.reserver("ollama", "memory_extraction", plafond=1)
        assert not c.disponible("ollama", plafond=1)
        horloge.avancer(3599)
        assert not c.disponible("ollama", plafond=1)
        horloge.avancer(2)
        assert c.disponible("ollama", plafond=1)
        assert c.utilises("ollama") == 0

    def test_le_plafond_est_par_provider(self, horloge):
        c = CadenceDeFond(horloge=horloge)
        assert c.reserver("ollama", "r", plafond=1)
        assert not c.reserver("ollama", "r", plafond=1)
        # Un autre provider a son propre compteur.
        assert c.reserver("claude", "r", plafond=1)

    def test_zero_est_illimite(self, horloge):
        c = CadenceDeFond(horloge=horloge)
        for _ in range(500):
            assert c.reserver("claude", "r", plafond=0)
        assert c.disponible("claude", plafond=0)

    def test_un_refus_est_compte_sans_consommer(self, horloge):
        c = CadenceDeFond(horloge=horloge)
        assert c.reserver("ollama", "memory_extraction", plafond=1)
        assert not c.reserver("ollama", "signal_interpretation", plafond=1)
        c.refuser("ollama", "conversation_tools")
        snap = c.snapshot(plafond=lambda n: 1)
        (ligne,) = snap["providers"]
        assert (ligne["utilises"], ligne["refuses"], ligne["sature"]) == (1, 2, True)
        par_role = {(r["role"], r["provider"]): r for r in snap["roles"]}
        assert par_role[("memory_extraction", "ollama")]["utilises"] == 1
        assert par_role[("signal_interpretation", "ollama")]["refuses"] == 1
        assert par_role[("conversation_tools", "ollama")]["refuses"] == 1

    def test_le_snapshot_liste_aussi_les_providers_muets(self, horloge):
        """Un plafond se lit même quand il n'a pas encore servi."""
        c = CadenceDeFond(horloge=horloge)
        snap = c.snapshot(plafond=lambda n: 30 if n == "ollama" else 0,
                          providers=("claude", "ollama"))
        assert [p["provider"] for p in snap["providers"]] == ["claude", "ollama"]
        assert snap["providers"][1]["plafond"] == 30
        assert snap["roles"] == []


# ===================================================================
# 2. Les rôles de fond dérivent de l'énumération
# ===================================================================


class TestRolesDeFond:

    def test_chaque_membre_est_classe_une_fois(self):
        humains = {r for r in AIRole if r.value in ROLES_AU_SERVICE_D_UN_HUMAIN}
        assert humains | ROLES_DE_FOND == set(AIRole)
        assert not (humains & ROLES_DE_FOND)

    def test_chaque_valeur_humaine_nomme_un_membre(self):
        """Une faute de frappe rangerait un rôle humain parmi les rôles de
        fond sans rien dire."""
        assert ROLES_AU_SERVICE_D_UN_HUMAIN <= {r.value for r in AIRole}

    def test_les_roles_qui_servent_un_humain_qui_attend(self):
        assert {r.value for r in AIRole} - {r.value for r in ROLES_DE_FOND} == {
            "conversation", "conversation_tools", "vision_caption", "preparation",
        }

    def test_un_pas_de_chantier_n_est_pas_reconnu_par_son_role(self):
        """`conversation_tools` sert aussi la conversation : c'est l'appelant
        qui pose le marqueur."""
        assert AIRole.CONVERSATION_TOOLS not in ROLES_DE_FOND
        assert not AIRouter._est_appel_de_fond(AIRole.CONVERSATION_TOOLS)
        with en_fond():
            assert AIRouter._est_appel_de_fond(AIRole.CONVERSATION_TOOLS)
        assert not AIRouter._est_appel_de_fond(AIRole.CONVERSATION_TOOLS)


# ===================================================================
# 3. Le routeur applique le budget
# ===================================================================


class TestBudgetAuRouteur:

    async def test_un_appel_de_fond_au_dessus_du_plafond_est_refuse_avant_l_appel(
        self, instruments,
    ):
        cadence, _ = instruments
        r = _routeur_nu(budgets={"ollama": 2})
        invoke = AsyncMock(side_effect=_ok)

        for _ in range(2):
            await r._metered_call(AIRole.MEMORY_EXTRACTION, "s", "u", invoke)
        with pytest.raises(BudgetDeFondEpuise) as exc:
            await r._metered_call(AIRole.MEMORY_EXTRACTION, "s", "u", invoke)

        assert invoke.await_count == 2
        assert isinstance(exc.value, QuotaExceeded)
        assert exc.value.provider == "ollama"
        assert cadence.utilises("ollama") == 2

    async def test_un_tour_de_conversation_n_est_jamais_refuse(self, instruments):
        """Provider saturé ou non : quelqu'un attend."""
        cadence, _ = instruments
        r = _routeur_nu(budgets={"ollama": 1})
        await r._metered_call(AIRole.MEMORY_EXTRACTION, "s", "u", _ok)
        assert not cadence.disponible("ollama", 1)

        invoke = AsyncMock(side_effect=_ok)
        for role in (AIRole.CONVERSATION, AIRole.CONVERSATION_TOOLS,
                     AIRole.VISION_CAPTION, AIRole.PREPARATION):
            await r._metered_call(role, "s", "u", invoke)
        assert invoke.await_count == 4
        # Et ils ne consomment pas le budget de fond.
        assert cadence.utilises("ollama") == 1

    async def test_le_marqueur_en_fond_fait_compter_un_tour_outille(self, instruments):
        cadence, _ = instruments
        r = _routeur_nu(budgets={"ollama": 1})
        with en_fond():
            await r._metered_call(AIRole.CONVERSATION_TOOLS, "s", "u", _ok)
            with pytest.raises(BudgetDeFondEpuise):
                await r._metered_call(AIRole.CONVERSATION_TOOLS, "s", "u", _ok)
        assert cadence.utilises("ollama") == 1

    async def test_un_appel_imbrique_est_compte_une_fois(self, instruments):
        """Un outil qui relance le modèle depuis la boucle tourne DANS
        l'appel déjà compté — comme il partage déjà son créneau."""
        cadence, _ = instruments
        r = _routeur_nu(budgets={"ollama": 1})
        interne = AsyncMock(side_effect=_ok)

        async def externe(provider, model, temperature, max_tokens):
            # files_analyze_image depuis un pas de chantier : rôle humain,
            # mais le marqueur de l'appelant suit l'await.
            await r._metered_call(AIRole.VISION_CAPTION, "s", "u", interne)
            return "ok", "ok"

        with en_fond():
            await r._metered_call(AIRole.CONVERSATION_TOOLS, "s", "u", externe)

        assert interne.await_count == 1
        assert cadence.utilises("ollama") == 1
        # Le compte est rendu à la sortie : l'appel suivant est bien refusé.
        with en_fond(), pytest.raises(BudgetDeFondEpuise):
            await r._metered_call(AIRole.CONVERSATION_TOOLS, "s", "u", _ok)

    async def test_un_refus_est_compte_au_registre_et_au_compteur(self, instruments):
        cadence, _ = instruments
        r = _routeur_nu(budgets={"ollama": 0, "claude": 1})
        r._resolve = lambda role: ("claude", "m", 0.7, "i")
        avant = degradations.count_for("ai.router: appel de fond refusé")

        await r._metered_call(AIRole.EMAIL_TRIAGE, "s", "u", _ok)
        with pytest.raises(BudgetDeFondEpuise):
            await r._metered_call(AIRole.EMAIL_TRIAGE, "s", "u", _ok)

        assert degradations.count_for("ai.router: appel de fond refusé") == avant + 1
        (ligne,) = cadence.snapshot(plafond=lambda n: 1)["providers"]
        assert (ligne["provider"], ligne["utilises"], ligne["refuses"]) == ("claude", 1, 1)

    async def test_zero_est_illimite_au_routeur(self, instruments):
        r = _routeur_nu(budgets={"ollama": 0})
        invoke = AsyncMock(side_effect=_ok)
        for _ in range(50):
            await r._metered_call(AIRole.MEMORY_EXTRACTION, "s", "u", invoke)
        assert invoke.await_count == 50


class TestVerificationPrealable:
    """`budget_de_fond_disponible` : ce qu'un consommateur consulte avant de
    bâtir un prompt cher."""

    def test_repond_non_et_compte_le_report(self, instruments):
        cadence, _ = instruments
        r = _routeur_nu(budgets={"ollama": 1})
        cadence.reserver("ollama", "memory_extraction", plafond=1)
        avant = degradations.count_for("ai.router: appel de fond différé")

        assert r.budget_de_fond_disponible(AIRole.CONVERSATION_TOOLS) is False

        assert degradations.count_for("ai.router: appel de fond différé") == avant + 1
        (ligne,) = cadence.snapshot(plafond=lambda n: 1)["providers"]
        assert ligne["refuses"] == 1
        # Consulter ne consomme pas.
        assert ligne["utilises"] == 1

    def test_repond_oui_sous_le_plafond_sans_consommer(self, instruments):
        cadence, _ = instruments
        r = _routeur_nu(budgets={"ollama": 3})
        assert r.budget_de_fond_disponible(AIRole.CONVERSATION_TOOLS) is True
        assert cadence.utilises("ollama") == 0

    def test_un_role_non_mappe_repond_oui(self, instruments):
        """L'appel réel dira pourquoi il échoue, avec sa vraie raison."""
        r = _routeur_nu()

        def _leve(role):
            raise UnconfiguredRoleError("aucun", role=role)

        r._resolve = _leve
        assert r.budget_de_fond_disponible(AIRole.SIGNAL_INTERPRETATION) is True


# ===================================================================
# 4. Un pas de chantier refusé ne réserve pas de pas
# ===================================================================


def _engine():
    from conscience.engine import ConscienceEngine

    e = ConscienceEngine.__new__(ConscienceEngine)
    e._threshold = 0.5
    return e


@pytest.mark.django_db(transaction=True)
class TestPasDeChantier:

    @pytest.fixture(autouse=True)
    def _purger(self):
        from conscience.models import Travail
        Travail.objects.all().delete()
        yield
        Travail.objects.all().delete()

    async def test_un_pas_refuse_ne_reserve_rien_et_n_appelle_pas(self):
        from django.utils import timezone as tz

        from conscience.models import Travail

        row = await sync_to_async(Travail.objects.create)(
            titre="lire ce qui se dit sur les modèles de diffusion",
            origine=Travail.Origine.OBSERVATION, reference="7",
            envie=0.8, ancre_envie=tz.now(), pas_max=3,
        )
        e = _engine()
        faux = AsyncMock()
        with patch.object(type(e), "_appeler_le_modele", faux), \
                patch("conscience.travaux.ai_router.budget_de_fond_disponible",
                      return_value=False) as verif:
            assert await e._faire_un_pas(row.pk) is False

        verif.assert_called_once_with(AIRole.CONVERSATION_TOOLS)
        faux.assert_not_awaited()
        row = await sync_to_async(Travail.objects.get)(pk=row.pk)
        assert row.pas_effectues == 0
        assert row.dernier_pas_le is None
        # Et pas de pas au mémo horaire du moteur non plus.
        assert getattr(e, "_pas_faits", []) == []


class TestActeDifere:

    async def test_un_acte_sans_budget_ne_paie_rien_et_ne_compte_pas(self):
        """Ni trousse, ni brief, ni destinataire, ni rappel mémoire — et un
        résultat qui n'est ni un acte ni une panne."""
        from conscience.acte import act

        e = _engine()
        appel = AsyncMock()
        trousse = MagicMock()
        with patch.object(type(e), "_appeler_le_modele", appel), \
                patch.object(type(e), "_preparer_trousse", trousse), \
                patch.object(type(e), "_tirer_gigue_cooldown", MagicMock()), \
                patch("conscience.acte.ai_router.budget_de_fond_disponible",
                      return_value=False):
            resultat = await act(e, MagicMock(), "idle")

        assert resultat.differe is True
        assert resultat.dit == ""
        assert resultat.ai_failed is False
        assert resultat.sans_audience is False
        appel.assert_not_awaited()
        trousse.assert_not_called()
        # Le cooldown est posé : les tentatives, gratuites, sont espacées.
        assert e._last_action_time > 0


class TestInterpretationDiferee:

    async def test_le_signal_est_interprete_par_heuristique(self):
        from conscience.interpreter import SignalInterpreter
        from modules.types import ModuleEvent

        event = ModuleEvent(
            event_type="email.received", source_module="email",
            data={"subject": "x"},
        )
        interp = SignalInterpreter()
        llm = AsyncMock()
        with patch.object(interp, "_interpret_with_llm", llm), \
                patch("conscience.interpreter.ai_router.budget_de_fond_disponible",
                      return_value=False):
            signal = await interp.interpret(event)

        llm.assert_not_awaited()
        assert signal.category == "system"
        assert 0.0 < signal.pertinence < 1.0

    async def test_un_quota_pendant_l_appel_retombe_aussi_sur_l_heuristique(self):
        from conscience.interpreter import SignalInterpreter
        from modules.types import ModuleEvent

        event = ModuleEvent(
            event_type="email.received", source_module="email", data={},
        )
        interp = SignalInterpreter()
        with patch("conscience.interpreter.ai_router.budget_de_fond_disponible",
                   return_value=True), \
                patch("conscience.interpreter.ai_router.complete",
                      AsyncMock(side_effect=BudgetDeFondEpuise("ollama", "r", 3, 3))):
            signal = await interp.interpret(event)
        assert signal.category == "system"


class TestNotifyDifere:

    async def test_un_notify_sans_budget_rend_le_silence(self):
        from modules.notify import notify_ai
        from modules.types import ModuleNotification

        notif = ModuleNotification(
            source_module="rss", summary="titre", details="", urgency="low",
        )
        with patch("ai.router.ai_router.budget_de_fond_disponible",
                   return_value=False), \
                patch("pipeline.router.perceive", AsyncMock()) as perceive:
            decision = await notify_ai(notif)
        perceive.assert_not_awaited()
        assert decision.response_text == ""

    async def test_un_notify_part_en_fond(self):
        from modules.notify import notify_ai
        from modules.types import ModuleNotification

        vu = []

        async def _perceive(perception):
            vu.append(_de_fond.get())
            return None

        notif = ModuleNotification(
            source_module="rss", summary="titre", details="", urgency="low",
        )
        with patch("ai.router.ai_router.budget_de_fond_disponible",
                   return_value=True), \
                patch("pipeline.router.perceive", _perceive):
            await notify_ai(notif)
        assert vu == [True]
        assert _de_fond.get() is False


# ===================================================================
# 5. Le disjoncteur
# ===================================================================


async def _timeout(provider, model, temperature, max_tokens):
    await asyncio.sleep(10)
    return "jamais", "jamais"


class TestDisjoncteur:

    async def test_trois_timeouts_puis_le_quatrieme_n_attend_pas(
        self, instruments, horloge,
    ):
        _, disj = instruments
        r = _routeur_nu(budgets={}, seuil=3, repos_s=60.0)
        for _ in range(3):
            with pytest.raises(asyncio.TimeoutError):
                await r._metered_call(
                    AIRole.CONVERSATION, "s", "u", _timeout, timeout=0.01,
                )
        assert disj.est_ouvert("ollama")

        invoke = AsyncMock(side_effect=_timeout)
        with pytest.raises(ProviderIndisponible) as exc:
            await r._metered_call(
                AIRole.CONVERSATION, "s", "u", invoke, timeout=5.0,
            )
        invoke.assert_not_awaited()
        # Un TimeoutError : la branche que chaque consommateur sait traiter.
        assert isinstance(exc.value, asyncio.TimeoutError)
        assert exc.value.provider == "ollama"
        assert 0 < exc.value.reste_s <= 60.0

    async def test_apres_le_repos_un_essai_passe_et_un_succes_referme(
        self, instruments, horloge,
    ):
        _, disj = instruments
        r = _routeur_nu(budgets={}, seuil=3, repos_s=60.0)
        for _ in range(3):
            with pytest.raises(asyncio.TimeoutError):
                await r._metered_call(
                    AIRole.CONVERSATION, "s", "u", _timeout, timeout=0.01,
                )
        horloge.avancer(61)

        invoke = AsyncMock(side_effect=_ok)
        assert await r._metered_call(AIRole.CONVERSATION, "s", "u", invoke) == "réponse"
        invoke.assert_awaited_once()
        assert not disj.est_ouvert("ollama")
        (ligne,) = disj.snapshot(reglage=lambda n: (3, 60.0))
        assert (ligne["etat"], ligne["echecs"], ligne["ouvertures"]) == ("ferme", 0, 1)

    async def test_un_essai_rate_rouvre_pour_un_repos(self, instruments, horloge):
        _, disj = instruments
        r = _routeur_nu(budgets={}, seuil=3, repos_s=60.0)
        for _ in range(3):
            with pytest.raises(asyncio.TimeoutError):
                await r._metered_call(
                    AIRole.CONVERSATION, "s", "u", _timeout, timeout=0.01,
                )
        horloge.avancer(61)
        with pytest.raises(asyncio.TimeoutError) as exc:
            await r._metered_call(
                AIRole.CONVERSATION, "s", "u", _timeout, timeout=0.01,
            )
        assert not isinstance(exc.value, ProviderIndisponible)
        with pytest.raises(ProviderIndisponible):
            await r._metered_call(AIRole.CONVERSATION, "s", "u", _ok)
        (ligne,) = disj.snapshot(reglage=lambda n: (3, 60.0))
        assert ligne["ouvertures"] == 2

    async def test_un_seul_essai_a_la_fois(self, instruments, horloge):
        _, disj = instruments
        r = _routeur_nu(budgets={}, seuil=1, repos_s=10.0)
        with pytest.raises(asyncio.TimeoutError):
            await r._metered_call(AIRole.CONVERSATION, "s", "u", _timeout, timeout=0.01)
        horloge.avancer(11)

        parti = asyncio.Event()

        async def lent(provider, model, temperature, max_tokens):
            parti.set()
            await asyncio.sleep(0.05)
            return "ok", "ok"

        essai = asyncio.create_task(r._metered_call(AIRole.CONVERSATION, "s", "u", lent))
        await parti.wait()
        with pytest.raises(ProviderIndisponible):
            await r._metered_call(AIRole.CONVERSATION, "s", "u", _ok)
        assert await essai == "ok"
        assert not disj.est_ouvert("ollama")

    async def test_une_reponse_du_provider_rompt_la_serie(self, instruments):
        """Une 400, une réponse vide, un quota : le provider a RÉPONDU."""
        _, disj = instruments
        r = _routeur_nu(budgets={}, seuil=3, repos_s=60.0)
        for _ in range(2):
            with pytest.raises(asyncio.TimeoutError):
                await r._metered_call(
                    AIRole.CONVERSATION, "s", "u", _timeout, timeout=0.01,
                )

        async def quatre_cents(provider, model, temperature, max_tokens):
            raise ValueError("temperature non supportée")

        with pytest.raises(ValueError):
            await r._metered_call(AIRole.CONVERSATION, "s", "u", quatre_cents)
        for _ in range(2):
            with pytest.raises(asyncio.TimeoutError):
                await r._metered_call(
                    AIRole.CONVERSATION, "s", "u", _timeout, timeout=0.01,
                )
        assert not disj.est_ouvert("ollama")
        (ligne,) = disj.snapshot(reglage=lambda n: (3, 60.0))
        assert ligne["echecs"] == 2

    async def test_un_creneau_jamais_obtenu_compte_comme_une_panne(
        self, instruments,
    ):
        """Le scénario OPS-09 : un Ollama figé tient le seul créneau."""
        _, disj = instruments
        r = _routeur_nu(budgets={}, seuil=2, repos_s=60.0)
        r._concurrency_limit = lambda name: 1

        tenu = asyncio.Event()

        async def fige(provider, model, temperature, max_tokens):
            tenu.set()
            await asyncio.sleep(10)
            return "jamais", "jamais"

        premier = asyncio.create_task(
            r._metered_call(AIRole.CONVERSATION, "s", "u", fige, timeout=0.3)
        )
        await tenu.wait()
        with pytest.raises(asyncio.TimeoutError):
            await r._metered_call(AIRole.CONVERSATION, "s", "u", _ok, timeout=0.01)
        with pytest.raises(asyncio.TimeoutError):
            await premier
        assert disj.est_ouvert("ollama")

    async def test_seuil_zero_ne_coupe_jamais(self, instruments):
        _, disj = instruments
        r = _routeur_nu(budgets={}, seuil=0, repos_s=60.0)
        for _ in range(5):
            with pytest.raises(asyncio.TimeoutError):
                await r._metered_call(
                    AIRole.CONVERSATION, "s", "u", _timeout, timeout=0.01,
                )
        assert not disj.est_ouvert("ollama")

    async def test_un_provider_ouvert_ne_consomme_pas_le_budget_de_fond(
        self, instruments,
    ):
        cadence, disj = instruments
        r = _routeur_nu(budgets={"ollama": 5}, seuil=1, repos_s=60.0)
        with pytest.raises(asyncio.TimeoutError):
            await r._metered_call(
                AIRole.MEMORY_EXTRACTION, "s", "u", _timeout, timeout=0.01,
            )
        assert disj.est_ouvert("ollama")
        for _ in range(3):
            with pytest.raises(ProviderIndisponible):
                await r._metered_call(AIRole.MEMORY_EXTRACTION, "s", "u", _ok)
        assert cadence.utilises("ollama") == 1


class TestPanneDeTransport:

    @pytest.mark.parametrize("exc", [
        asyncio.TimeoutError(), TimeoutError(), ConnectionRefusedError(),
        ConnectionError("reset"),
        type("APIConnectionError", (Exception,), {})("sdk"),
        type("ConnectError", (type("TransportError", (Exception,), {}),), {})("httpx"),
    ])
    def test_ce_qui_dit_que_le_transport_a_lache(self, exc):
        assert est_panne_de_transport(exc)

    @pytest.mark.parametrize("exc", [
        ValueError("temperature"), RuntimeError("réponse vide"),
        QuotaExceeded("role:x:daily", 1, 1),
        UnconfiguredRoleError("aucun"),
        BudgetDeFondEpuise("ollama", "r", 3, 3),
        ProviderIndisponible("ollama", 10.0),
        type("BadRequestError", (Exception,), {})("400"),
    ])
    def test_ce_qui_est_une_reponse(self, exc):
        assert not est_panne_de_transport(exc)


# ===================================================================
# 6. Santé
# ===================================================================


@pytest.mark.django_db
class TestSante:

    @pytest.fixture(autouse=True)
    def _portail_ouvert(self, settings):
        settings.DASHBOARD_REQUIRE_AUTH = False

    def test_la_page_rend_les_appels_de_fond_et_les_disjoncteurs(
        self, client, instruments, horloge,
    ):
        cadence, disj = instruments
        cadence.reserver("ollama", "memory_extraction", plafond=30)
        cadence.reserver("ollama", "memory_extraction", plafond=30)
        cadence.refuser("ollama", "conversation_tools")
        disj.echec("claude", ConnectionError("refusée"), seuil=1, repos_s=60.0)

        reponse = client.get(reverse("gestionsysteme:system-tab", args=["sante"]))
        assert reponse.status_code == 200
        html = reponse.content.decode()
        assert "Appels de fond (dernière heure)" in html
        assert "Disjoncteurs" in html
        assert "memory_extraction" in html
        assert "conversation_tools" in html
        assert "badge-danger\">ouvert" in html
        assert "ConnectionError: refusée" in html

    def test_la_page_survit_a_un_routeur_muet(self, client, monkeypatch):
        from ai.router import ai_router

        monkeypatch.setattr(
            ai_router, "cadence_stats", MagicMock(side_effect=RuntimeError("boom")),
        )
        reponse = client.get(reverse("gestionsysteme:system-tab", args=["sante"]))
        assert reponse.status_code == 200
        assert "Appels de fond (dernière heure)" in reponse.content.decode()


# ===================================================================
# 7. Le schéma : les clés existent pour les six providers
# ===================================================================


class TestSchema:

    def test_chaque_provider_declare_ses_trois_cles(self):
        from ai.router import _PROVIDER_CLASSES
        from configs.registry import registry

        declared = {i.key for i in registry.all_items()}
        manquantes = [
            f"ai.{name}.{suffixe}"
            for name in _PROVIDER_CLASSES
            for suffixe in ("appels_de_fond_par_heure", "disjoncteur.echecs",
                            "disjoncteur.repos_s")
            if f"ai.{name}.{suffixe}" not in declared
        ]
        assert not manquantes

    @pytest.mark.parametrize("provider,attendu", [
        ("claude", 0), ("openai", 0), ("gemini", 0), ("glm", 0),
        ("ollama", 30), ("ollama_cloud", 0),
    ])
    def test_seul_le_serveur_local_est_plafonne_par_defaut(self, provider, attendu):
        from configs.registry import registry

        item = registry.get(f"ai.{provider}.appels_de_fond_par_heure")
        assert item is not None
        assert item.default == attendu
        assert item.min == 0  # « illimité » doit rester exprimable

    def test_les_replis_valent_les_defauts_declares(self):
        """Le repli d'un site de lecture et le défaut du schéma sont la même
        valeur écrite deux fois — elles doivent être égales (les clés sont
        des f-strings, le scanner de ``test_config_rapatriement`` ne les
        voit pas)."""
        from ai.cadence import DISJONCTEUR_ECHECS, DISJONCTEUR_REPOS_S
        from ai.router import _PROVIDER_CLASSES, _PROVIDER_FALLBACK_BUDGET_DE_FOND
        from configs.registry import registry

        for name in _PROVIDER_CLASSES:
            assert registry.get(f"ai.{name}.appels_de_fond_par_heure").default \
                == _PROVIDER_FALLBACK_BUDGET_DE_FOND.get(name, 0)
            assert registry.get(f"ai.{name}.disjoncteur.echecs").default \
                == DISJONCTEUR_ECHECS
            assert registry.get(f"ai.{name}.disjoncteur.repos_s").default \
                == DISJONCTEUR_REPOS_S

    @pytest.mark.usefixtures("config_hors_base")
    def test_le_chemin_de_lecture_sert_le_defaut_declare(self):
        from ai.router import ai_router

        assert ai_router._budget_de_fond("ollama") == 30
        assert ai_router._budget_de_fond("claude") == 0
        assert ai_router._reglage_disjoncteur("ollama") == (3, 60.0)
