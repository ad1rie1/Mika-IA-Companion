"""Un pas de chantier : muet, borné, et qui ne peut pas boucler.

Ce lot est le seul qui dépense un appel LLM en dehors de la parole. Tout ce qui
suit épingle donc soit une **borne** — un travail sans terme n'est pas un
travail — soit une **honnêteté** : ce qui est compté l'est parce que ça a eu
lieu.

`transaction=True` : les écritures passent par `sync_to_async` sur un thread
d'exécuteur, hors de la transaction de test.
"""

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone as tz


def _engine():
    from conscience.engine import ConscienceEngine

    e = ConscienceEngine.__new__(ConscienceEngine)
    e._threshold = 0.5
    return e


class _Sortie:
    """Ce que `process_message` rend, réduit à ce que le pas lui demande."""

    def __init__(self, text, ai_failed=False):
        self.text = text
        self.ai_failed = ai_failed
        self.tool_calls = []


def _reponse(texte, *, echec=False, outils=0, bilan=""):
    """Bouchon de `_appeler_le_modele` : (output, bilan, réussites)."""
    return AsyncMock(return_value=(_Sortie(texte, echec), bilan, outils))


async def _travail(**kw):
    from conscience.models import Travail

    champs = dict(
        titre="lire ce qui se dit sur les modèles de diffusion",
        origine=Travail.Origine.OBSERVATION, reference="7",
        envie=0.8, ancre_envie=tz.now(), pas_max=3,
    )
    champs.update(kw)
    return await sync_to_async(Travail.objects.create)(**champs)


@pytest.fixture(autouse=True)
def _purger():
    from conscience.models import Rumination, Travail
    Travail.objects.all().delete()
    Rumination.objects.all().delete()
    yield
    Travail.objects.all().delete()
    Rumination.objects.all().delete()


VERDICT_FINI = (
    "J'ai lu les trois articles et j'en retiens deux idées.\n\n"
    "--- VERDICT ---\n"
    '{"etat": "fini", "resume": "trois articles lus", "motif": "", "delai_s": 0}\n'
    "--- FIN VERDICT ---"
)
VERDICT_CONTINUE = (
    "J'ai commencé à lire.\n\n"
    "--- VERDICT ---\n"
    '{"etat": "continue", "resume": "premier article", "motif": "", "delai_s": 0}\n'
    "--- FIN VERDICT ---"
)


@pytest.mark.django_db(transaction=True)
class TestLePasEstMuet:

    @pytest.mark.asyncio
    async def test_un_pas_ne_diffuse_ni_ne_persiste(self):
        """Quatre travaux à cinq pas feraient vingt monologues par jour, et
        ceux-là passeraient HORS du frein quotidien des initiatives."""
        e = _engine()
        row = await _travail()
        faux = _reponse(VERDICT_CONTINUE)
        with patch.object(type(e), "_appeler_le_modele", faux):
            assert await e._faire_un_pas(row.pk) is True

        _, kwargs = faux.call_args
        assert kwargs["broadcast"] is False
        assert kwargs["persist"] is False
        assert kwargs["person_id"] == "conscience_mika"

    @pytest.mark.asyncio
    async def test_le_verdict_ne_se_dit_pas_a_voix_haute(self):
        """Sa comptabilité ne doit pas se retrouver dans son journal."""
        e = _engine()
        row = await _travail()
        with patch.object(type(e), "_appeler_le_modele", _reponse(VERDICT_FINI)):
            await e._faire_un_pas(row.pk)

        await sync_to_async(row.refresh_from_db)()
        assert "VERDICT" not in row.resultat
        assert "trois articles" in row.resultat or "deux idées" in row.resultat


@pytest.mark.django_db(transaction=True)
class TestLesBornes:

    @pytest.mark.asyncio
    async def test_le_pas_est_marque_avant_l_appel(self):
        """Compté à la PRISE, pas au succès.

        Un pas marqué au retour serait rejoué indéfiniment par un process qui
        meurt pendant l'appel — c'est la boucle de plantage que
        `resume_interrupted_turns` a déjà appris à éviter.
        """
        from conscience.models import Travail

        e = _engine()
        row = await _travail()
        vus = {}

        async def _pendant_l_appel(*a, **kw):
            vus["pas"] = (await sync_to_async(
                lambda: Travail.objects.get(pk=row.pk).pas_effectues
            )())
            return _Sortie(VERDICT_CONTINUE), "", 0

        with patch.object(type(e), "_appeler_le_modele", _pendant_l_appel):
            await e._faire_un_pas(row.pk)

        assert vus["pas"] == 1, "le crédit doit être consommé avant l'appel"

    @pytest.mark.asyncio
    async def test_un_appel_qui_echoue_rend_son_credit(self):
        """Sur une installation dont le rôle n'est pas mappé — et le dépôt
        démarre non configuré exprès — cinq échecs consommeraient les cinq pas
        et elle serait frustrée d'un travail jamais tenté."""
        e = _engine()
        row = await _travail()
        with patch.object(type(e), "_appeler_le_modele",
                          _reponse("", echec=True)):
            assert await e._faire_un_pas(row.pk) is False

        await sync_to_async(row.refresh_from_db)()
        assert row.pas_effectues == 0
        assert row.statut == row.Statut.EN_COURS

    @pytest.mark.asyncio
    async def test_les_pas_epuises_bloquent_le_chantier(self):
        """Un travail sans terme n'est pas un travail."""
        e = _engine()
        row = await _travail(pas_max=1)
        with patch.object(type(e), "_appeler_le_modele", _reponse(VERDICT_CONTINUE)):
            await e._faire_un_pas(row.pk)

        await sync_to_async(row.refresh_from_db)()
        assert row.statut == row.Statut.BLOQUEE
        assert "pas" in row.raison_blocage

    @pytest.mark.asyncio
    async def test_deux_cycles_concurrents_ne_prennent_pas_le_meme_chantier(self):
        """La prise est un test-and-set : `update()` filtré rend 0 au second."""
        from conscience.models import Travail

        row = await _travail()

        def _prendre():
            return Travail.objects.filter(
                pk=row.pk, statut=Travail.Statut.EN_COURS,
            ).update(pas_effectues=1, dernier_pas_le=tz.now())

        assert await sync_to_async(_prendre)() == 1
        # Le second cycle voit un chantier déjà bloqué → 0 ligne touchée.
        await sync_to_async(
            lambda: Travail.objects.filter(pk=row.pk).update(
                statut=Travail.Statut.BLOQUEE)
        )()
        assert await sync_to_async(_prendre)() == 0


@pytest.mark.django_db(transaction=True)
class TestLeVerdictPilote:

    @pytest.mark.asyncio
    async def test_fini_clot_le_chantier(self):
        e = _engine()
        row = await _travail()
        with patch.object(type(e), "_appeler_le_modele", _reponse(VERDICT_FINI)):
            await e._faire_un_pas(row.pk)

        await sync_to_async(row.refresh_from_db)()
        assert row.statut == row.Statut.ABOUTIE

    @pytest.mark.asyncio
    async def test_bloque_retient_le_motif(self):
        e = _engine()
        row = await _travail()
        texte = (
            "Je ne peux pas continuer.\n\n--- VERDICT ---\n"
            '{"etat": "bloque", "resume": "", "motif": "il me manque la clef API"}\n'
            "--- FIN VERDICT ---"
        )
        with patch.object(type(e), "_appeler_le_modele", _reponse(texte)):
            await e._faire_un_pas(row.pk)

        await sync_to_async(row.refresh_from_db)()
        assert row.statut == row.Statut.BLOQUEE
        assert "clef API" in row.raison_blocage

    @pytest.mark.asyncio
    async def test_un_chantier_ne_sachant_jamais_ou_il_en_est_finit_par_bloquer(self):
        """Un verdict illisible est un ÉTAT, pas une erreur : il se compte.

        Sans ce comptage, un modèle incapable de produire le bloc ferait
        tourner le chantier jusqu'à l'épuisement de ses pas sans qu'on sache
        jamais pourquoi.
        """
        e = _engine()
        row = await _travail(pas_max=20)
        with patch.object(type(e), "_appeler_le_modele",
                          _reponse("je réfléchis, mais je n'écris aucun verdict")):
            for _ in range(3):
                await e._faire_un_pas(row.pk)

        await sync_to_async(row.refresh_from_db)()
        assert row.statut == row.Statut.BLOQUEE
        assert "verdict" in row.raison_blocage.lower()

    @pytest.mark.asyncio
    async def test_l_envie_et_son_ancre_s_ecrivent_ensemble(self):
        """Écrire la valeur sans avancer l'ancre re-facture le même temps au
        tour suivant ; l'ancre sans la valeur efface la décroissance. C'est ce
        qui est arrivé à `Connaissance`, ancrée sur un `auto_now` que Django ne
        rafraîchit pas sous `update_fields`."""
        e = _engine()
        row = await _travail()
        ancre_avant, envie_avant = row.ancre_envie, row.envie

        with patch.object(type(e), "_appeler_le_modele", _reponse(VERDICT_CONTINUE)):
            await e._faire_un_pas(row.pk)

        await sync_to_async(row.refresh_from_db)()
        assert row.ancre_envie > ancre_avant
        assert row.envie <= envie_avant

    @pytest.mark.asyncio
    async def test_un_chantier_ne_d_une_pensee_la_resout_en_aboutissant(self):
        """La boucle du regret refermée par l'autre côté : elle n'oublie pas
        parce que le temps passe, elle oublie parce qu'elle a fait la chose."""
        from conscience.models import Rumination, Travail

        pensee = await sync_to_async(Rumination.objects.create)(
            summary="Thomas n'a pas eu sa réponse", intensity=0.6, status="active",
        )
        e = _engine()
        row = await _travail(
            origine=Travail.Origine.PENSEE, reference=str(pensee.pk),
        )
        with patch.object(type(e), "_appeler_le_modele", _reponse(VERDICT_FINI)):
            await e._faire_un_pas(row.pk)

        await sync_to_async(pensee.refresh_from_db)()
        assert pensee.status == "resolved"


@pytest.mark.django_db(transaction=True)
class TestRepriseAuBoot:

    @pytest.mark.asyncio
    async def test_un_chantier_coupe_en_vol_ne_repart_pas_indefiniment(self):
        """On ne rend PAS le crédit au redémarrage.

        Le rendre rouvrirait exactement la boucle de plantage que
        `resume_interrupted_turns` évite : un pas qui tue le process deux fois
        doit finir par coûter ses pas, pas les regagner.
        """
        e = _engine()
        row = await _travail(pas_max=2)
        await sync_to_async(
            lambda: type(row).objects.filter(pk=row.pk).update(pas_effectues=2)
        )()

        await e._reprendre_travaux()

        await sync_to_async(row.refresh_from_db)()
        assert row.statut == row.Statut.BLOQUEE
        assert "interrompu" in row.raison_blocage

    @pytest.mark.asyncio
    async def test_un_chantier_sain_n_est_pas_touche(self):
        e = _engine()
        row = await _travail(pas_max=5)
        await e._reprendre_travaux()

        await sync_to_async(row.refresh_from_db)()
        assert row.statut == row.Statut.EN_COURS


@pytest.mark.django_db(transaction=True)
class TestLePromptDuTravail:

    @pytest.mark.asyncio
    async def test_il_ne_reutilise_pas_le_prompt_de_parole(self):
        """`_build_action_prompt` répond à « pourquoi je parle maintenant ».

        Le réutiliser ferait arriver dans un travail silencieux les
        salutations, l'auto-évaluation des relances ignorées et l'injonction à
        être brève — tout ce qui n'a de sens que devant quelqu'un.
        """
        import ast
        import inspect
        import textwrap

        from conscience import travaux

        # La méthode du moteur est un délégué d'une ligne ; la propriété est
        # portée par `travaux.faire_un_pas`, qui orchestre à travers la
        # surface du moteur.
        arbre = ast.parse(textwrap.dedent(
            inspect.getsource(travaux.faire_un_pas)
        ))
        appels = {
            n.func.attr for n in ast.walk(arbre)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert "_build_work_prompt" in appels
        assert "_build_action_prompt" not in appels

    @pytest.mark.asyncio
    async def test_le_journal_du_chantier_est_reinjecte_sans_prosodie(self):
        """Les `[SIGH]` d'un pas précédent finiraient sinon dans les souvenirs :
        le processeur ne nettoie que le texte destiné à une voix."""
        e = _engine()
        row = await _travail()
        row.resultat = "j'ai lu le premier article [SIGH] et c'était dense"
        await sync_to_async(row.save)()

        prompt = await e._build_work_prompt(row)
        assert "premier article" in prompt
        assert "[SIGH]" not in prompt

    @pytest.mark.asyncio
    async def test_la_consigne_de_verdict_est_dans_le_prompt(self):
        from conscience.verdict import CONSIGNE_VERDICT

        e = _engine()
        row = await _travail()
        prompt = await e._build_work_prompt(row)
        assert CONSIGNE_VERDICT.strip()[:40] in prompt
