"""Quatre boucles que rien ne refermait.

1. **Une graine survit à son chantier.** La déduplication ne se lisait que sur
   les chantiers vivants ; une Observation reste « en attente » trente
   minutes, une Rumination des heures — le même chantier fini ou bloqué se
   rouvrait au cycle suivant, avec à chaque tour un appel LLM, un souvenir,
   une fierté et +0.05 d'estime (ou une frustration et une rumination).
2. **Un rendez-vous dont l'appel IA échoue était retenté toutes les 30 s**,
   `tentatives` restant à zéro : l'échec propre (`output.ai_failed`) rentrait
   avant le compteur, et une priorité ≥ 0.8 levait le cooldown et le veto de
   sommeil à chaque cycle.
3. **L'audit d'après-coup écrivait une pensée par réponse chargée** : douze
   tours, pression 1.0, Facteur 10 cloué à +0.30 pendant ~9 h.
4. **Le relief des pensées après un acte** lisait, calculait en RAM et
   réécrivait — la course exacte que `_decay_ruminations` documente.

`transaction=True` : les écritures passent par `sync_to_async` sur un thread
d'exécuteur, hors de la transaction de test.
"""

import ast
import inspect
import textwrap
import time as _t
from datetime import timedelta
from unittest.mock import patch

from old.backend.utils.tool_results import BilanOutils
from old.backend.utils.tool_trace import JournalOutils

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone as tz

from old.backend.conscience.trousse import Trousse
from old.backend.conscience.types import DecisionContext


class _MemoireMuette:
    async def recall_for_context(self, queries, **kw):
        return ""


class _Sortie:
    def __init__(self, text="j'ai regardé", ai_failed=False):
        self.text = text
        self.ai_failed = ai_failed
        self.tool_calls = []


def _engine():
    from old.backend.conscience.engine import ConscienceEngine

    e = ConscienceEngine.__new__(ConscienceEngine)
    e._threshold = 0.5
    e._last_action_time = 0.0
    e._salutation_en_attente = None
    e.memory = None
    return e


def _ctx(**kw) -> DecisionContext:
    base = dict(
        pending_observations=[], global_mood="curious", global_intensity=0.3,
        idle_seconds=600, in_cooldown=False, max_pertinence=0.0,
        weighted_urgency=0.0, rumination_lignes=[], rumination_pressure=0.0,
    )
    base.update(kw)
    return DecisionContext(**base)


def _patches_acte(e, sortie):
    """Les doubles d'un `_act` qui ne mesure que ce qu'il écrit en base."""
    return (
        patch.object(type(e), "_appeler_le_modele", return_value=(sortie, BilanOutils(JournalOutils()), 0)),
        patch.object(type(e), "_select_recipient", return_value=None),
        patch.object(type(e), "_preparer_trousse", return_value=Trousse()),
        patch.object(type(e), "_composer_vecu", return_value=""),
        patch.object(type(e), "_resolve_ruminations_after_act"),
    )


async def _acte(e, ctx, sortie):
    a, b, c, d, f = _patches_acte(e, sortie)
    with a, b, c, d, f:
        e.memory = _MemoireMuette()
        return await e._act(ctx, "test")


@pytest.fixture(autouse=True)
def _purger():
    from old.backend.conscience.models import (
        ConscienceLog, Observation, Rumination, ScheduledAction, Travail,
    )
    modeles = (Travail, Rumination, Observation, ScheduledAction, ConscienceLog)
    for m in modeles:
        m.objects.all().delete()
    yield
    for m in modeles:
        m.objects.all().delete()


# ---------------------------------------------------------------------------
# 1. Une graine ne ressert pas
# ---------------------------------------------------------------------------


async def _observation(pertinence=0.9):
    from old.backend.conscience.models import Observation

    return await sync_to_async(Observation.objects.create)(
        source="rss", event_type="rss.new_entry",
        summary="un article sur les modèles de diffusion",
        pertinence=pertinence, themes=["ia"], status="pending",
    )


async def _un_cycle_de_semis(e, ctx):
    """Ce que `_decide_inner` fait d'une amorce, sans parler ni faire de pas."""
    from old.backend.conscience.conduite import choisir_conduite

    travaux, semees = await e._travaux_en_cours(tz.now())
    graines = e._recolter(ctx, semees)
    d = choisir_conduite(
        score=0.2, seuil=0.5, travaux=travaux, graines=graines,
        maintenant=tz.now(), tuning=e._conduite_tuning(),
    )
    if d.conduite.value == "ouvrir":
        await e._ouvrir_travail(d.cible)
    return d.conduite.value


@pytest.mark.django_db(transaction=True)
class TestUneGraineNeRessertPas:

    @pytest.mark.parametrize("statut", ["aboutie", "bloquee", "abandonnee"])
    @pytest.mark.asyncio
    async def test_un_chantier_clos_ne_rouvre_pas_la_meme_amorce(self, statut):
        """Cycle N : OUVRIR. N+1 : verdict terminal. N+2 : la même amorce
        — l'observation est toujours « en attente » trente minutes — ne doit
        PAS rouvrir un chantier. Avant : `semees` ne se lisait que sur les
        chantiers `en_cours`, donc un chantier fini rouvrait l'identique."""
        from old.backend.conscience.models import Travail

        e = _engine()
        obs = await _observation()
        ctx = _ctx(pending_observations=[obs])

        assert await _un_cycle_de_semis(e, ctx) == "ouvrir"
        await sync_to_async(
            lambda: Travail.objects.update(statut=statut)
        )()

        for _ in range(3):
            conduite = await _un_cycle_de_semis(e, ctx)
            assert conduite != "ouvrir", "la même amorce rouvre un chantier"

        n = await sync_to_async(Travail.objects.count)()
        assert n == 1, f"{n} chantiers pour une seule amorce"

    @pytest.mark.asyncio
    async def test_les_amorces_semees_couvrent_les_chantiers_clos(self):
        """La clé de déduplication porte tout chantier né dans la fenêtre,
        pas seulement les vivants — et `vivants` reste `en_cours` seul."""
        from old.backend.conscience.models import Travail

        e = _engine()
        for statut, ref in (("aboutie", "11"), ("bloquee", "12"),
                            ("en_cours", "13")):
            await sync_to_async(Travail.objects.create)(
                titre=f"chantier {ref}", origine=Travail.Origine.OBSERVATION,
                reference=ref, statut=statut, envie=0.8,
                ancre_envie=tz.now(),
            )

        vivants, semees = await e._travaux_en_cours(tz.now())

        assert {(o, r) for o, r in semees} >= {
            ("observation", "11"), ("observation", "12"), ("observation", "13"),
        }
        assert [v.titre for v in vivants] == ["chantier 13"]

    @pytest.mark.asyncio
    async def test_un_chantier_vieux_d_un_jour_libere_son_amorce(self):
        """La mémoire des semis est une fenêtre, pas une éternité : un
        chantier clos hier ne bloque plus le même sujet demain."""
        from old.backend.conscience.models import Travail

        e = _engine()
        row = await sync_to_async(Travail.objects.create)(
            titre="vieux", origine=Travail.Origine.PULSION,
            reference="rss:un titre", statut="aboutie", envie=0.8,
        )
        await sync_to_async(
            lambda: Travail.objects.filter(pk=row.pk).update(
                created_at=tz.now() - timedelta(hours=30),
            )
        )()

        _, semees = await e._travaux_en_cours(tz.now())
        assert ("pulsion", "rss:un titre") not in semees

    @pytest.mark.asyncio
    async def test_l_observation_semee_est_traitee(self):
        """Ouvrir un chantier consomme la graine : l'observation a reçu sa
        réponse — le chantier — et ne pèse plus dans l'urgence, ne se fait
        plus promouvoir en pensée, ne ressert plus d'amorce."""
        e = _engine()
        obs = await _observation()

        await _un_cycle_de_semis(e, _ctx(pending_observations=[obs]))

        await sync_to_async(obs.refresh_from_db)()
        assert obs.status == "acted"
        assert "chantier" in obs.action_response

    @pytest.mark.asyncio
    async def test_une_pensee_dont_le_chantier_bloque_s_apaise(self):
        """Seul le FINI résolvait la pensée : bloqué, le chantier laissait la
        rumination entière, au-dessus de la porte des graines, prête à
        rouvrir l'identique. Bloqué = divisée par deux, pas résolue — elle
        n'a pas fait la chose, elle a essayé."""
        from old.backend.conscience.models import Rumination, Travail
        from old.backend.conscience.verdict import EtatVerdict, Verdict

        e = _engine()
        r = await sync_to_async(Rumination.objects.create)(
            summary="le concert de samedi", intensity=0.8, status="active",
        )
        row = await sync_to_async(Travail.objects.create)(
            titre="organiser le concert", origine=Travail.Origine.PENSEE,
            reference=str(r.pk), envie=0.8, ancre_envie=tz.now(), pas_max=3,
        )

        await e._appliquer_verdict(
            row.pk,
            Verdict(etat=EtatVerdict.BLOQUE, motif_blocage="pas de salle"),
            "je n'ai pas trouvé de salle", "",
        )

        await sync_to_async(r.refresh_from_db)()
        assert r.status == "active"
        assert r.intensity == pytest.approx(0.4, abs=0.01)

    @pytest.mark.asyncio
    async def test_une_pensee_dont_le_chantier_s_essouffle_s_apaise(self):
        """L'abandon est terminal aussi : la pensée qui l'avait ouvert cesse
        d'insister au moment même où la lecture des travaux l'abandonne."""
        from old.backend.conscience.models import Rumination, Travail

        e = _engine()
        r = await sync_to_async(Rumination.objects.create)(
            summary="relire ce papier", intensity=0.6, status="active",
        )
        await sync_to_async(Travail.objects.create)(
            titre="relire ce papier", origine=Travail.Origine.PENSEE,
            reference=str(r.pk), envie=0.8,
            ancre_envie=tz.now() - timedelta(days=2),
        )

        vivants, _ = await e._travaux_en_cours(tz.now())

        assert vivants == []
        await sync_to_async(r.refresh_from_db)()
        assert r.intensity == pytest.approx(0.3, abs=0.01)


# ---------------------------------------------------------------------------
# 2. Un rendez-vous qui échoue se compte, et attend avant de revenir
# ---------------------------------------------------------------------------


async def _action(priority=0.9, **kw):
    from old.backend.conscience.models import ScheduledAction

    champs = dict(
        scheduled_at=tz.now() - timedelta(minutes=1),
        prompt="rappelle à Adrien le rendez-vous", priority=priority,
        source="test",
    )
    champs.update(kw)
    return await sync_to_async(ScheduledAction.objects.create)(**champs)


@pytest.mark.django_db(transaction=True)
class TestUnRendezVousQuiEchoue:

    @pytest.mark.asyncio
    async def test_un_echec_propre_compte_une_tentative_et_differe(self):
        """`output.ai_failed` est l'échec ORDINAIRE (rôle non mappé, quota,
        timeout) et il rentrait avant `_compter_tentative`, réservé à
        l'exception : `tentatives` restait à zéro pour toujours. Compté, et
        l'action n'est plus « due » avant son délai — donc plus rien à
        remonter pour lever le cooldown ou le veto de sommeil."""
        from old.backend.conscience.agenda import _SCHEDULED_REESSAI_S

        e = _engine()
        action = await _action()
        avant = tz.now()

        resultat = await _acte(
            e, _ctx(scheduled_actions=[action]), _Sortie("", ai_failed=True),
        )
        assert resultat.ai_failed is True

        await sync_to_async(action.refresh_from_db)()
        assert action.status == "pending"
        assert action.tentatives == 1
        assert action.reessayer_le is not None
        assert action.reessayer_le >= avant + timedelta(
            seconds=_SCHEDULED_REESSAI_S - 5)

        assert await e._poll_scheduled_actions() == [], (
            "une action qui vient d'échouer ne doit plus être due : c'est "
            "ce que le scoring lit pour lever le cooldown"
        )

    @pytest.mark.asyncio
    async def test_le_delai_croit_avec_les_tentatives(self):
        """5 min × n, et l'action reste `pending` tant que le plafond tient."""
        from old.backend.conscience.agenda import _SCHEDULED_REESSAI_S

        e = _engine()
        action = await _action()
        await e._compter_tentative([action])
        await e._compter_tentative([action])

        await sync_to_async(action.refresh_from_db)()
        assert action.tentatives == 2
        assert action.status == "pending"
        assert action.reessayer_le >= tz.now() + timedelta(
            seconds=2 * _SCHEDULED_REESSAI_S - 5)

    @pytest.mark.asyncio
    async def test_trois_echecs_propres_abandonnent_l_action(self):
        """Le plafond `tentatives_max` s'applique enfin à l'échec ordinaire."""
        from old.backend.conscience.models import ScheduledAction

        e = _engine()
        action = await _action()
        for _ in range(3):
            frais = await sync_to_async(
                lambda: ScheduledAction.objects.get(pk=action.pk))()
            await _acte(
                e, _ctx(scheduled_actions=[frais]), _Sortie("", ai_failed=True),
            )

        await sync_to_async(action.refresh_from_db)()
        assert action.status == "failed"
        assert action.tentatives == 3
        assert "3" in action.raison_echec

    @pytest.mark.asyncio
    async def test_le_poll_respecte_le_delai_de_reessai(self):
        """Différée = pas due ; délai passé ou absent = due comme avant."""
        e = _engine()
        differee = await _action(reessayer_le=tz.now() + timedelta(minutes=10))
        revenue = await _action(reessayer_le=tz.now() - timedelta(seconds=1))
        neuve = await _action()

        dues = {a.pk for a in await e._poll_scheduled_actions()}

        assert differee.pk not in dues
        assert dues >= {revenue.pk, neuve.pk}

    @pytest.mark.asyncio
    async def test_une_action_reussie_ne_garde_pas_de_delai(self):
        """Le chemin du succès est inchangé : exécutée, une tentative."""
        e = _engine()
        action = await _action()

        await _acte(e, _ctx(scheduled_actions=[action]), _Sortie("fait"))

        await sync_to_async(action.refresh_from_db)()
        assert action.status == "executed"
        assert action.tentatives == 1


# ---------------------------------------------------------------------------
# 3. L'audit d'après-coup ne déborde pas
# ---------------------------------------------------------------------------


async def _audits_actifs() -> int:
    from old.backend.conscience.models import Rumination

    return await sync_to_async(
        lambda: Rumination.objects.filter(
            status="active", observation__isnull=True, themes=[],
        ).count()
    )()


@pytest.mark.django_db(transaction=True)
class TestLAuditNeDebordePas:

    def _moteur(self):
        from old.backend.conscience.engine import ConscienceEngine

        return ConscienceEngine()

    @pytest.mark.asyncio
    async def test_douze_tours_charges_n_ecrivent_qu_une_pensee(self):
        """Douze réponses à 0.8 pour la même personne en une minute : UNE
        micro-rumination. Avant, douze — pression 1.0, Facteur 10 cloué."""
        e = self._moteur()
        for i in range(12):
            await e.post_action_audit(
                f"tu vas voir, ça va être énorme ({i})", "excited", 0.8,
                "web_alice",
            )
        assert await _audits_actifs() == 1

    @pytest.mark.asyncio
    async def test_l_espacement_est_par_personne(self):
        e = self._moteur()
        await e.post_action_audit("je suis désolée", "sad", 0.8, "web_alice")
        await e.post_action_audit("je suis désolée", "sad", 0.8, "tg_bob")
        assert await _audits_actifs() == 2

    @pytest.mark.asyncio
    async def test_la_fenetre_ecoulee_rouvre_l_audit(self):
        e = self._moteur()
        await e.post_action_audit("c'était trop", "angry", 0.8, "web_alice")
        e._audits_recents["web_alice"] = _t.monotonic() - 86400
        await e.post_action_audit("c'était trop", "angry", 0.8, "web_alice")
        assert await _audits_actifs() == 2

    @pytest.mark.asyncio
    async def test_un_tour_tiede_ne_consomme_pas_la_fenetre(self):
        """Le mémo se pose à la tentative d'ÉCRITURE, pas à l'appel : une
        réponse sous le seuil ne doit pas voler la fenêtre de la suivante."""
        e = self._moteur()
        await e.post_action_audit("ok", "happy", 0.2, "web_alice")
        await e.post_action_audit("c'était énorme", "excited", 0.8, "web_alice")
        assert await _audits_actifs() == 1

    @pytest.mark.asyncio
    async def test_le_plafond_fane_la_plus_faible(self):
        """Trois pensées d'audit actives, une quatrième arrive : la plus
        faible se fane (jamais supprimée — la nuit la relit), le total reste
        au plafond, et la nouvelle est là."""
        from old.backend.conscience.ruminations import _AUDIT_ACTIVES_MAX
        from old.backend.conscience.models import Rumination

        e = self._moteur()
        anciennes = []
        for i, intensite in enumerate((0.3, 0.2, 0.4)):
            anciennes.append(await sync_to_async(Rumination.objects.create)(
                summary=f"vieux rejeu {i}", intensity=intensite,
                emotion="anxious", themes=[], observation=None, status="active",
            ))
        assert await _audits_actifs() == _AUDIT_ACTIVES_MAX

        await e.post_action_audit("j'ai été trop loin", "angry", 0.9, "web_alice")

        assert await _audits_actifs() == _AUDIT_ACTIVES_MAX
        await sync_to_async(anciennes[1].refresh_from_db)()
        assert anciennes[1].status == "faded", "la plus faible cède sa place"
        await sync_to_async(anciennes[2].refresh_from_db)()
        assert anciennes[2].status == "active"
        neuve = await sync_to_async(
            lambda: Rumination.objects.filter(status="active")
            .exclude(pk__in=[a.pk for a in anciennes]).count()
        )()
        assert neuve == 1

    @pytest.mark.asyncio
    async def test_le_plafond_ne_touche_pas_les_pensees_a_thème(self):
        """Une pensée promue d'une observation, ou née d'un chantier à
        thèmes, n'est pas un rejeu : le plafond de l'audit ne la fane pas."""
        from old.backend.conscience.models import Rumination

        e = self._moteur()
        autre = await sync_to_async(Rumination.objects.create)(
            summary="Je bloque sur « lire ce papier »", intensity=0.1,
            emotion="frustrated", themes=["ia"], status="active",
        )
        for i in range(3):
            await sync_to_async(Rumination.objects.create)(
                summary=f"rejeu {i}", intensity=0.3, themes=[], status="active",
            )

        await e.post_action_audit("j'ai été trop loin", "angry", 0.9, "web_alice")

        await sync_to_async(autre.refresh_from_db)()
        assert autre.status == "active"

    def test_les_replis_valent_les_defauts_declares(self):
        """Une seule vérité par bouton — la garde AST de
        `test_config_rapatriement` le vérifie sur tous les sites ; ici on
        épingle que les trois clés neuves existent bien."""
        from old.backend.configs.registry import registry
        from old.backend.conscience.agenda import _SCHEDULED_REESSAI_S
        from old.backend.conscience.ruminations import _AUDIT_ACTIVES_MAX, _AUDIT_ESPACEMENT_S

        assert registry.get("conscience.audit.espacement_s").default \
            == _AUDIT_ESPACEMENT_S
        assert registry.get("conscience.audit.actives_max").default \
            == _AUDIT_ACTIVES_MAX
        assert registry.get("conscience.scheduled.reessai_s").default \
            == _SCHEDULED_REESSAI_S


# ---------------------------------------------------------------------------
# 4. Le relief des pensées ne court plus contre les autres écrivains
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestLeReliefDesPenseesNeCourtPlus:

    @pytest.mark.asyncio
    async def test_une_pensee_fanee_pendant_le_relief_n_est_pas_ressuscitee(self):
        """Lire, diviser en RAM, réécrire : entre les deux `await`, la
        digestion nocturne fanait une ligne que le `bulk_update` remettait
        `active`. On rejoue la course : un écrivain passe juste après le
        premier aller-retour en base. Avant, la ligne ressuscitait."""
        from old.backend.conscience import ruminations as moteur_module
        from old.backend.conscience.engine import ConscienceEngine
        from old.backend.conscience.models import Rumination

        r = await sync_to_async(Rumination.objects.create)(
            summary="encore là", intensity=0.8, status="active", themes=["audit"],
        )
        vrai = moteur_module.sync_to_async
        appels: list = []

        def _fader():
            Rumination.objects.filter(pk=r.pk).update(status="faded")

        def espion(fn, **kw):
            async def _run(*a, **k):
                res = await vrai(fn, **kw)(*a, **k)
                appels.append(fn)
                if len(appels) == 1:
                    await vrai(_fader)()
                return res
            return _run

        e = ConscienceEngine()
        with patch.object(moteur_module, "sync_to_async", espion):
            await e._resolve_ruminations_after_act(themes=["audit"])

        await sync_to_async(r.refresh_from_db)()
        assert r.status == "faded", "le relief a ressuscité une pensée fanée"

    def test_le_relief_tient_dans_un_seul_aller_retour(self):
        """Aucun `bulk_update` et un seul `sync_to_async` : par l'AST, jamais
        par le texte — les commentaires de ce dépôt nomment ce qu'il ne faut
        pas faire."""
        from old.backend.conscience import ruminations

        arbre = ast.parse(textwrap.dedent(
            inspect.getsource(ruminations.resolve_ruminations_after_act)))
        noms = [
            (n.func.attr if isinstance(n.func, ast.Attribute) else
             getattr(n.func, "id", None))
            for n in ast.walk(arbre) if isinstance(n, ast.Call)
        ]
        assert "bulk_update" not in noms
        assert noms.count("sync_to_async") == 1

    @pytest.mark.asyncio
    async def test_le_relief_divise_et_resout_comme_avant(self):
        """Le comportement observable ne bouge pas : 0.8 → 0.4 active,
        0.15 → 0.075 résolue."""
        from old.backend.conscience.engine import ConscienceEngine
        from old.backend.conscience.models import Rumination

        forte = await sync_to_async(Rumination.objects.create)(
            summary="forte", intensity=0.8, status="active", themes=["audit"])
        faible = await sync_to_async(Rumination.objects.create)(
            summary="faible", intensity=0.15, status="active", themes=["audit"])

        await ConscienceEngine()._resolve_ruminations_after_act(themes=["audit"])

        await sync_to_async(forte.refresh_from_db)()
        await sync_to_async(faible.refresh_from_db)()
        assert forte.intensity == pytest.approx(0.4, abs=0.01)
        assert forte.status == "active"
        assert faible.status == "resolved"
