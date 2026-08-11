"""Le moteur doit dire vrai sur ce qu'il a fait.

Trois mensonges réparés ici, tous de la même famille : le système marquait des
choses comme faites au seul motif qu'un appel n'avait pas planté.

`transaction=True` : les écritures passent par `sync_to_async`, hors de la
transaction de test.
"""

import ast
import inspect
import textwrap
from unittest.mock import patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone as tz

from conscience.trousse import Trousse
from conscience.types import DecisionContext


class _MemoireMuette:
    """Le rappel mémoire ne rend rien : ce n'est pas ce qu'on mesure ici."""

    async def recall_for_context(self, queries):
        return ""


class _Sortie:
    def __init__(self, text="j'ai regardé", ai_failed=False):
        self.text = text
        self.ai_failed = ai_failed
        self.tool_calls = []


def _engine():
    from conscience.engine import ConscienceEngine

    e = ConscienceEngine.__new__(ConscienceEngine)
    e._threshold = 0.5
    e._last_action_time = 0.0
    e._salutation_en_attente = None
    e.memory = None
    return e


async def _observations(n: int):
    from conscience.models import Observation

    return [
        await sync_to_async(Observation.objects.create)(
            source="rss", event_type="rss.new_entry",
            summary=f"observation {i}", pertinence=0.6, status="pending",
        )
        for i in range(n)
    ]


async def _actions(n: int):
    from conscience.models import ScheduledAction

    return [
        await sync_to_async(ScheduledAction.objects.create)(
            scheduled_at=tz.now(), prompt=f"rendez-vous {i}",
            priority=0.5, source="test",
        )
        for i in range(n)
    ]


def _ctx(observations=(), actions=()) -> DecisionContext:
    return DecisionContext(
        pending_observations=list(observations), global_mood="curious",
        global_intensity=0.3, idle_seconds=600, in_cooldown=False,
        max_pertinence=0.6, weighted_urgency=0.3,
        scheduled_actions=list(actions),
    )


@pytest.fixture(autouse=True)
def _purger():
    from conscience.models import ConscienceLog, Observation, ScheduledAction
    for m in (Observation, ScheduledAction, ConscienceLog):
        m.objects.all().delete()
    yield
    for m in (Observation, ScheduledAction, ConscienceLog):
        m.objects.all().delete()


@pytest.mark.django_db(transaction=True)
class TestOnNeClotQueCeQuiAEteMontre:

    @pytest.mark.asyncio
    async def test_les_observations_non_montrees_restent_en_attente(self):
        """Le prompt en montrait cinq et l'acte en clôturait vingt.

        Le surplus était estampillé « traité » par une réponse qui ne le
        mentionnait même pas, et devenait inéligible à la promotion en pensée —
        qui ne relit que les observations « écartées ».
        """
        from conscience.models import Observation

        e = _engine()
        obs = await _observations(12)
        ctx = _ctx(observations=obs)

        with patch.object(type(e), "_appeler_le_modele",
                          return_value=(_Sortie(), "", 0)), \
             patch.object(type(e), "_select_recipient", return_value=None), \
             patch.object(type(e), "_preparer_trousse", return_value=Trousse()), \
             patch.object(type(e), "_composer_vecu", return_value=""), \
             patch.object(type(e), "_resolve_ruminations_after_act"):
            e.memory = _MemoireMuette()
            resultat = await e._act(ctx, "test")

        assert resultat.dit
        closes = await sync_to_async(
            lambda: Observation.objects.filter(status="acted").count())()
        attente = await sync_to_async(
            lambda: Observation.objects.filter(status="pending").count())()
        assert closes == 5, f"{closes} closes — seules les montrées doivent l'être"
        assert attente == 7, "le surplus doit rester en attente, pas être avalé"

    @pytest.mark.asyncio
    async def test_les_rendez_vous_non_montres_ne_sont_pas_executes(self):
        """Dix étaient marqués « exécutés » alors que trois figuraient au
        prompt : sept intentions disparaissaient à chaque acte, et le journal
        annonçait « Executed 10 scheduled action(s) »."""
        from conscience.models import ScheduledAction

        e = _engine()
        actions = await _actions(8)
        ctx = _ctx(actions=actions)

        with patch.object(type(e), "_appeler_le_modele",
                          return_value=(_Sortie(), "", 0)), \
             patch.object(type(e), "_select_recipient", return_value=None), \
             patch.object(type(e), "_preparer_trousse", return_value=Trousse()), \
             patch.object(type(e), "_composer_vecu", return_value=""), \
             patch.object(type(e), "_resolve_ruminations_after_act"):
            e.memory = _MemoireMuette()
            await e._act(ctx, "test")

        faites = await sync_to_async(
            lambda: ScheduledAction.objects.filter(status="executed").count())()
        restantes = await sync_to_async(
            lambda: ScheduledAction.objects.filter(status="pending").count())()
        assert faites == 3
        assert restantes == 5

    @pytest.mark.asyncio
    async def test_une_action_executee_porte_son_resultat(self):
        """« Exécutée » sans résultat ne prouve rien : le statut ne disait que
        « l'appel IA n'a pas planté »."""
        from conscience.models import ScheduledAction

        e = _engine()
        await _actions(1)
        actions = await sync_to_async(lambda: list(ScheduledAction.objects.all()))()

        with patch.object(type(e), "_appeler_le_modele",
                          return_value=(_Sortie("voilà, c'est relu"), "", 0)), \
             patch.object(type(e), "_select_recipient", return_value=None), \
             patch.object(type(e), "_preparer_trousse", return_value=Trousse()), \
             patch.object(type(e), "_composer_vecu", return_value=""), \
             patch.object(type(e), "_resolve_ruminations_after_act"):
            e.memory = _MemoireMuette()
            await e._act(_ctx(actions=actions), "test")

        row = await sync_to_async(lambda: ScheduledAction.objects.first())()
        assert row.status == "executed"
        assert "relu" in row.resultat
        assert row.tentatives == 1


@pytest.mark.django_db(transaction=True)
class TestLeRetourDeLActe:

    def test_la_veracite_se_lit_sur_le_texte_et_non_sur_l_objet(self):
        """Un dataclass est TOUJOURS vrai.

        Tester l'objet ferait journaliser « act » sur un acte échoué : cela
        gonflerait `acts_today` et, ne pouvant recevoir aucune réponse,
        compterait comme un acte ignoré — trois pannes suffiraient à brider la
        conscience pour la journée.
        """
        from conscience.engine import ActeResultat, ConscienceEngine

        assert bool(ActeResultat(ai_failed=True)) is True, (
            "c'est précisément le piège : l'objet vide est truthy"
        )

        source = textwrap.dedent(
            inspect.getsource(ConscienceEngine._decide_inner))
        arbre = ast.parse(source)
        # L'appel à `_act` doit être suivi d'un test sur un ATTRIBUT.
        tests_sur_attribut = [
            n for n in ast.walk(arbre)
            if isinstance(n, ast.If) and isinstance(n.test, ast.Attribute)
            and n.test.attr == "dit"
        ]
        assert tests_sur_attribut, "la véracité doit se lire sur `.dit`"

    @pytest.mark.asyncio
    async def test_un_acte_echoue_ne_dit_rien(self):
        e = _engine()
        with patch.object(type(e), "_appeler_le_modele",
                          return_value=(_Sortie("", ai_failed=True), "", 0)), \
             patch.object(type(e), "_select_recipient", return_value=None), \
             patch.object(type(e), "_preparer_trousse", return_value=Trousse()), \
             patch.object(type(e), "_composer_vecu", return_value=""):
            e.memory = _MemoireMuette()
            resultat = await e._act(_ctx(), "test")

        assert resultat.dit == ""
        assert resultat.ai_failed is True


@pytest.mark.django_db(transaction=True)
class TestLeJournalDitTout:

    @pytest.mark.asyncio
    async def test_le_score_a_sa_colonne_et_n_est_plus_interpole(self):
        """Il n'existait qu'à l'intérieur de `reason`, en texte."""
        from conscience.models import ConscienceLog

        e = _engine()
        await e._log_decision(_ctx(), "skip", "no_signal", 0.42, [])

        row = await sync_to_async(lambda: ConscienceLog.objects.first())()
        assert row.score == pytest.approx(0.42)
        assert "score=" not in row.reason, (
            "le motif redevient une phrase de diagnostic, pas un transport"
        )

    @pytest.mark.asyncio
    async def test_un_acte_journalise_ce_qu_elle_a_dit_et_a_qui(self):
        from conscience.engine import ActeResultat
        from conscience.models import ConscienceLog

        e = _engine()
        await e._log_decision(
            _ctx(), "act", "idle(90m)", 0.62, [],
            conduite="parler",
            resultat=ActeResultat(
                dit="tiens, il fait nuit", person_id="web_abc",
                outils="memory_search ok", trousse=("memory_tools",),
            ),
        )

        row = await sync_to_async(lambda: ConscienceLog.objects.first())()
        assert row.texte == "tiens, il fait nuit"
        assert row.person_id == "web_abc"
        assert row.outils == "memory_search ok"
        assert row.trousse == ["memory_tools"]
        assert row.conduite == "parler"

    @pytest.mark.asyncio
    async def test_le_score_reste_nul_quand_il_n_a_pas_ete_mesure(self):
        """`null` et non 0.0 : écrire zéro dans les lignes déjà en base
        affirmerait un fait faux — le mensonge que ces colonnes retirent."""
        from conscience.models import ConscienceLog

        row = await sync_to_async(ConscienceLog.objects.create)(decision="skip")
        assert row.score is None
        assert row.acts_today is None


@pytest.mark.django_db(transaction=True)
class TestLaContentionSeVoit:

    @pytest.mark.asyncio
    async def test_trop_de_cycles_sautes_finit_par_lever(self):
        """Un `return` nu laissait la boucle marquer le tick en succès :
        « figée » et « en bonne santé » étaient indiscernables."""
        import asyncio

        e = _engine()
        e._decision_lock = asyncio.Lock()
        e._cycles_sautes = 0

        async with e._decision_lock:
            for _ in range(5):
                await e._decide()          # sauté, sans lever
            with pytest.raises(RuntimeError, match="cycles sautés"):
                await e._decide()

    @pytest.mark.asyncio
    async def test_un_cycle_qui_passe_remet_le_compteur_a_zero(self):
        import asyncio

        e = _engine()
        e._decision_lock = asyncio.Lock()
        e._cycles_sautes = 4

        with patch.object(type(e), "_decide_inner", return_value=None):
            await e._decide()
        assert e._cycles_sautes == 0
