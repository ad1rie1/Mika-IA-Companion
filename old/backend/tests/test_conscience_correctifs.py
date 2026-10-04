"""Quatre trous connus, refermés.

Chacun avait été identifié puis laissé de côté par un lot précédent, avec sa
raison. Ils sont regroupés ici parce qu'ils partagent une propriété : aucun ne
faisait tomber quoi que ce soit — ils rendaient le système *faux en silence*.
"""

import ast
import inspect
import textwrap
import time
from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone as tz


def _engine():
    from old.backend.conscience.engine import ConscienceEngine

    e = ConscienceEngine.__new__(ConscienceEngine)
    e._threshold = 0.5
    e._last_activity = time.time()
    return e


# ===========================================================================
# 1. Le murmure sait quand elle travaille
# ===========================================================================

@pytest.mark.django_db(transaction=True)
class TestModeProfessionnel:

    @pytest.mark.asyncio
    async def test_un_projet_en_mode_pro_coupe_le_murmure(self):
        """`gather_context` SAUTE la détection pour les person_id internes, et
        `conscience_mika` en est un : un acte spontané n'était donc jamais
        reconnu comme professionnel, et elle marmonnait affectivement au milieu
        d'un projet dont toute la raison d'être est qu'elle n'en fait rien.
        """
        from old.backend.projects.models import Project

        await sync_to_async(Project.objects.create)(
            title="migration du serveur", status=Project.Status.ACTIVE,
            emotion_policy=Project.EmotionPolicy.OFF,
            keywords=["migration", "serveur"],
        )
        e = _engine()
        assert await e._mode_professionnel("avancer la migration du serveur") is True

    @pytest.mark.asyncio
    async def test_hors_projet_elle_murmure(self):
        e = _engine()
        assert await e._mode_professionnel("dire bonjour") is False

    @pytest.mark.asyncio
    async def test_sans_intention_rien_n_est_interroge(self):
        """Une requête par acte, jamais par tick — et jamais pour rien."""
        e = _engine()
        with patch("projects.detection.detect_project_for_message") as det:
            assert await e._mode_professionnel("") is False
            det.assert_not_called()

    def test_l_intention_est_calculee_une_seule_fois(self):
        """Le murmure et la détection lisent la MÊME intention : deux calculs
        pourraient diverger, et elle se tairait pour un projet que le murmure
        ne mentionne pas."""
        from old.backend.conscience.engine import ConscienceEngine

        source = textwrap.dedent(
            inspect.getsource(ConscienceEngine._decide_inner))
        arbre = ast.parse(source)
        appels = [
            n for n in ast.walk(arbre)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_intention_de_lacte"
        ]
        assert len(appels) == 1


# ===========================================================================
# 2. Le silence se souvient d'un redémarrage
# ===========================================================================

@pytest.mark.django_db(transaction=True)
class TestInactiviteRestauree:

    @pytest.mark.asyncio
    async def test_elle_retrouve_depuis_quand_personne_ne_lui_a_parle(self):
        """`_last_activity` repartait de `time.time()` : au boot elle croyait
        qu'on venait de lui parler, pendant que les pulsions rejouaient trois
        jours d'absence. Deux mesures du même silence qui se contredisaient."""
        from old.backend.memory.models import Conversation, Message

        conv = await sync_to_async(Conversation.objects.create)()
        msg = await sync_to_async(Message.objects.create)(
            conversation=conv, role="user", content="tu es là ?",
            person_id="web_abc",
        )
        vieux = tz.now() - tz.timedelta(hours=5) if hasattr(tz, "timedelta") else None
        from datetime import timedelta
        vieux = tz.now() - timedelta(hours=5)
        await sync_to_async(
            lambda: Message.objects.filter(pk=msg.pk).update(created_at=vieux))()

        e = _engine()
        await e._restaurer_inactivite()
        assert 4.5 * 3600 < e.get_idle_seconds() < 5.5 * 3600

    @pytest.mark.asyncio
    async def test_ses_propres_repliques_ne_comptent_pas(self):
        """`ConscienceLog` serait le pire choix : il date ses propres
        monologues, donc elle conclurait que le silence vient d'être rompu par
        elle-même. Le rôle « assistant » et les person_id internes non plus."""
        from datetime import timedelta

        from old.backend.memory.models import Conversation, Message

        conv = await sync_to_async(Conversation.objects.create)()
        for role, pid in (("assistant", "web_abc"), ("user", "conscience_mika")):
            m = await sync_to_async(Message.objects.create)(
                conversation=conv, role=role, content="x", person_id=pid,
            )
            await sync_to_async(
                lambda pk=m.pk: Message.objects.filter(pk=pk).update(
                    created_at=tz.now() - timedelta(minutes=1)))()

        e = _engine()
        avant = e._last_activity
        await e._restaurer_inactivite()
        assert e._last_activity == avant, "aucun vrai message : rien à restaurer"

    @pytest.mark.asyncio
    async def test_l_inactivite_restauree_est_plafonnee(self):
        """Trois jours ou trois mois donnent le même facteur, déjà au plafond :
        au-delà la mesure ne dit plus rien d'utile."""
        from datetime import timedelta

        from old.backend.memory.models import Conversation, Message

        conv = await sync_to_async(Conversation.objects.create)()
        m = await sync_to_async(Message.objects.create)(
            conversation=conv, role="user", content="il y a longtemps",
            person_id="web_abc",
        )
        await sync_to_async(
            lambda: Message.objects.filter(pk=m.pk).update(
                created_at=tz.now() - timedelta(days=400)))()

        e = _engine()
        await e._restaurer_inactivite()
        assert e.get_idle_seconds() <= 72 * 3600 + 5


# ===========================================================================
# 3. L'envie a enfin un objet
# ===========================================================================

class TestSujetsProposes:

    def test_un_module_qui_ne_propose_rien_n_a_rien_a_ecrire(self):
        """Opt-in, comme tous les autres crochets."""
        from old.backend.modules.base import BaseModule

        assert BaseModule.propose_sujets(object()) == []

    def test_un_module_qui_leve_est_compte_et_saute(self):
        """Une curiosité ne doit pas tomber parce qu'un flux est cassé."""
        from old.backend.modules.collectors import ModuleCollectors

        class _Casse:
            name = "casse"
            def propose_sujets(self):
                raise RuntimeError("flux injoignable")

        class _Sain:
            name = "sain"
            def propose_sujets(self):
                return ["lire un truc"]

        registre = type("R", (), {"running": lambda s: [_Casse(), _Sain()]})()
        c = ModuleCollectors.__new__(ModuleCollectors)
        c._registry = registre
        assert c.sujets() == [("sain", "lire un truc")]

    def test_seules_les_pulsions_fecondes_sollicitent_les_modules(self):
        """Curiosité ET expression sollicitent (les deux `PULSIONS_FECONDES`) :
        la forge propose « réparer mon application », qui est une offre pour
        l'expression, pas pour la curiosité. Le social veut une personne, le
        repos ne veut rien entreprendre — eux restent muets."""
        from old.backend.drives.state import DriveKind

        e = _engine()
        with patch("modules.manager.module_manager") as mm:
            mm.collect_sujets.return_value = [("rss", "lire un article")]
            rien = e._graines_des_modules(DriveKind.SOCIAL, [("social", 0.9)])
            assert rien == []
            quelque = e._graines_des_modules(
                DriveKind.CURIOSITY, [("curiosity", 0.9)])
            aussi = e._graines_des_modules(
                DriveKind.EXPRESSION, [("expression", 0.9)])
        assert [g.intitule for g in quelque] == ["lire un article"]
        assert [g.intitule for g in aussi] == ["lire un article"]

    def test_un_sujet_propose_emporte_son_module(self):
        """La trousse du chantier se fige à la récolte : le module qui propose
        un sujet est celui dont chaque pas aura besoin — y compris après que
        le premier pas réussi a fait retomber la pulsion (`on_act`, −0.5)."""
        from old.backend.drives.state import DriveKind

        e = _engine()
        with patch("modules.manager.module_manager") as mm:
            mm.collect_sujets.return_value = [("forge", "réparer mon application « meteo »")]
            graines = e._graines_des_modules(
                DriveKind.EXPRESSION, [("expression", 0.9)])
        assert graines[0].modules == ("forge",)

    def test_sous_la_porte_rien_n_est_demande(self):
        from old.backend.drives.state import DriveKind

        e = _engine()
        with patch("modules.manager.module_manager") as mm:
            assert e._graines_des_modules(
                DriveKind.CURIOSITY, [("curiosity", 0.1)]) == []
            mm.collect_sujets.assert_not_called()

    def test_le_meme_sujet_ne_rouvre_pas_un_chantier(self):
        """La référence porte module + sujet, ce qui suffit à la
        déduplication : sans elle, chaque cycle rouvrirait le même titre."""
        from old.backend.drives.state import DriveKind

        e = _engine()
        with patch("modules.manager.module_manager") as mm:
            mm.collect_sujets.return_value = [("rss", "lire un article")]
            a = e._graines_des_modules(DriveKind.CURIOSITY, [("curiosity", 0.9)])
            b = e._graines_des_modules(DriveKind.CURIOSITY, [("curiosity", 0.9)])
        assert a[0].reference == b[0].reference

    def test_le_module_rss_propose_ses_titres_sans_requete(self):
        """Même source RAM que `get_context` : lisible depuis la boucle."""
        from old.backend.modules.plugins.rss.module import RSSModule

        m = RSSModule.__new__(RSSModule)
        m._headlines = [{"feed": "hn", "title": "Un nouveau modèle de diffusion"}]
        sujets = m.propose_sujets()
        assert len(sujets) == 1
        assert "diffusion" in sujets[0]

        m._headlines = []
        assert m.propose_sujets() == []
