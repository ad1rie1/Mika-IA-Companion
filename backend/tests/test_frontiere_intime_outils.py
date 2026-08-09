"""La frontiere intime, cote OUTILS.

Le prompt gate deja la fiche d'une personne derriere
``identity.trust.may_disclose_private_context``. Les outils MCP memoire, eux,
etaient statiques : aucune notion d'interlocuteur ni de certitude. Un inconnu
a 0.25 demandait « que t'a dit Thomas sur sa sante ? » et l'outil ressortait
mot pour mot ce que la gate du prompt venait de retenir.

Ces tests posent le ContextVar de personne EXPLICITEMENT. Sans lui,
``current_person_id()`` vaut "" — un appelant interne — et tout est autorise :
un test qui l'oublie est vacueux.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async

from memory.module import MemoryToolsModule
from pipeline.tracing import set_current_person_id


def _tools():
    return {t.name: t for t in MemoryToolsModule().return_tools()}


@pytest.mark.django_db(transaction=True)
class TestFrontiereIntimeOutils:

    @pytest.fixture(autouse=True)
    def _isole(self):
        from identity.models import Identity, IdentityClaim, IdentityHandle
        from memory.models import Commitment, DailyJournal, Entity, Souvenir
        from utils.degradation import degradations

        for model in (Commitment, DailyJournal, Souvenir, IdentityClaim,
                      IdentityHandle, Identity, Entity):
            model.objects.all().delete()
        degradations.reset()
        yield
        set_current_person_id("")
        degradations.reset()

    # ── Fixtures de scenario ──────────────────────────────────────

    async def _entite(self, nom: str):
        from memory.models import Entity
        return await Entity.objects.acreate(name=nom, entity_type="person")

    async def _souvenir(self, contenu: str, *entites):
        from django.utils import timezone
        from memory.models import Souvenir
        s = await Souvenir.objects.acreate(
            content=contenu, importance=0.9, occurred_at=timezone.now(),
        )
        for e in entites:
            await sync_to_async(s.entities.add)(e)
        return s

    async def _inconnu_telegram(self, handle="tg_999"):
        from identity.resolver import identity_resolver
        from identity.trust import ChannelTrust
        await identity_resolver.link_handle(
            handle, "telegram", kind="account", trust=ChannelTrust.ACCOUNT,
        )
        set_current_person_id(handle)

    async def _authentifie_lie(self, handle="user_3", nom="Adrien"):
        from identity.resolver import identity_resolver
        from identity.trust import ChannelTrust
        await identity_resolver.link_handle(
            handle, "web", kind="session", trust=ChannelTrust.AUTHENTICATED,
        )
        await identity_resolver.bind_authenticated(handle, "web", nom)
        set_current_person_id(handle)
        from memory.models import Entity
        return await Entity.objects.aget(name=nom, entity_type="person")

    # ── Le refus principal : engagements + journal ─────────────────

    async def test_un_inconnu_ne_lit_ni_les_engagements_ni_le_journal(self):
        from datetime import date
        from memory.models import Commitment, DailyJournal

        thomas = await self._entite("Thomas")
        await Commitment.objects.acreate(
            description="Envoyer les resultats a Thomas",
            person=thomas, status="pending",
        )
        await DailyJournal.objects.acreate(
            date=date.today(), narrative="Longue discussion avec Thomas.",
            persons_interacted=["Thomas"],
        )
        await self._inconnu_telegram()

        engagements = await _tools()["memory_list_commitments"].handler({})
        assert "message" in engagements
        assert "engagements" not in engagements

        journal = await _tools()["memory_read_journal"].handler({})
        assert "message" in journal
        assert "journaux" not in journal

    async def test_une_recherche_ecarte_ce_qui_parle_de_quelqu_un_d_autre(self):
        thomas = await self._entite("Thomas")
        prive = await self._souvenir("Thomas m'a parle de sa sante", thomas)
        general = await self._souvenir("On a parle de musique baroque")
        await self._inconnu_telegram()

        with patch("memory.manager.memory_manager") as mm:
            mm.search_related_souvenirs = AsyncMock(return_value=[
                {"id": str(prive.pk), "content": prive.content, "metadata": {}},
                {"id": str(general.pk), "content": general.content, "metadata": {}},
            ])
            mm.search_related_connaissances = AsyncMock(return_value=[])
            resultat = await _tools()["memory_search"].handler({"query": "sante"})

        contenus = [s["content"] for s in resultat["souvenirs"]]
        assert contenus == ["On a parle de musique baroque"]

    async def _reconnu_en_salon_public(self, handle="tg_grp_5", nom="Adrien"):
        """Quelqu'un que Mika reconnait, mais dans une piece pleine de monde :
        l'entite est liee, la divulgation reste fermee."""
        from identity.resolver import identity_resolver
        from identity.trust import ChannelTrust
        await identity_resolver.link_handle(
            handle, "telegram_group", kind="account", trust=ChannelTrust.PUBLIC,
        )
        await identity_resolver.link_entity(handle, nom)
        set_current_person_id(handle)
        from memory.models import Entity
        return await Entity.objects.aget(name=nom, entity_type="person")

    async def test_un_souvenir_partage_avec_un_tiers_est_ecarte(self):
        """Le cas que la forme ORM naive laissait passer : Django exclut toute
        ligne ayant AU MOINS une entite egale, donc un souvenir liant
        l'interlocuteur ET un tiers ressortait a l'interlocuteur."""
        moi = await self._reconnu_en_salon_public()
        thomas = await self._entite("Thomas")
        partage = await self._souvenir("Thomas et toi vous etes disputes", moi, thomas)
        mien = await self._souvenir("Tu m'as montre ta guitare", moi)

        with patch("memory.manager.memory_manager") as mm:
            mm.search_related_souvenirs = AsyncMock(return_value=[
                {"id": str(partage.pk), "content": partage.content, "metadata": {}},
                {"id": str(mien.pk), "content": mien.content, "metadata": {}},
            ])
            mm.search_related_connaissances = AsyncMock(return_value=[])
            resultat = await _tools()["memory_search"].handler({"query": "dispute"})

        contenus = [s["content"] for s in resultat["souvenirs"]]
        assert contenus == ["Tu m'as montre ta guitare"]

    async def test_la_lecture_de_perimetre_ne_se_laisse_pas_piper_par_l_orm(self):
        """``rows_mentioning_others`` en direct : c'est la ou vit le piege.
        ``.filter(entities__entity_type="person").exclude(entities__id=<pk>)``
        rend {solo_tiers} au lieu de {solo_tiers, partage}."""
        from memory import read
        from memory.models import Souvenir

        moi = await self._entite("Adrien")
        thomas = await self._entite("Thomas")
        mien = await self._souvenir("ta guitare", moi)
        partage = await self._souvenir("vous deux", moi, thomas)
        solo_tiers = await self._souvenir("Thomas seul", thomas)
        anonyme = await self._souvenir("il pleuvait")

        pks = [mien.pk, partage.pk, solo_tiers.pk, anonyme.pk]
        autrui = await read.rows_mentioning_others(
            Souvenir, pks, entity_id=moi.pk,
        )
        assert autrui == {partage.pk, solo_tiers.pk}

        # Personne non liee : toute entite-personne compte comme autrui.
        sans_lien = await read.rows_mentioning_others(
            Souvenir, pks, entity_id=None,
        )
        assert sans_lien == {mien.pk, partage.pk, solo_tiers.pk}

    async def test_tout_ecarte_donne_un_refus_poli(self):
        thomas = await self._entite("Thomas")
        prive = await self._souvenir("Thomas m'a confie un secret", thomas)
        await self._inconnu_telegram()

        with patch("memory.manager.memory_manager") as mm:
            mm.search_related_souvenirs = AsyncMock(return_value=[
                {"id": str(prive.pk), "content": prive.content, "metadata": {}},
            ])
            mm.search_related_connaissances = AsyncMock(return_value=[])
            resultat = await _tools()["memory_search"].handler({"query": "secret"})

        assert "souvenirs" not in resultat
        assert "en face" in resultat["message"]

    # ── Les internes ne perdent rien ──────────────────────────────

    async def test_les_appelants_internes_gardent_tout(self):
        from datetime import date
        from memory.models import Commitment, DailyJournal

        thomas = await self._entite("Thomas")
        await Commitment.objects.acreate(
            description="Envoyer les resultats a Thomas",
            person=thomas, status="pending",
        )
        await DailyJournal.objects.acreate(
            date=date.today(), narrative="Longue discussion avec Thomas.",
        )
        souvenir = await self._souvenir("Thomas m'a parle de sa sante", thomas)

        for interne in ("conscience_mika", ""):
            set_current_person_id(interne)

            engagements = await _tools()["memory_list_commitments"].handler({})
            assert len(engagements["engagements"]) == 1, interne

            journal = await _tools()["memory_read_journal"].handler({})
            assert len(journal["journaux"]) == 1, interne

            recents = await _tools()["memory_recent_souvenirs"].handler({})
            assert len(recents["souvenirs"]) == 1, interne

            with patch("memory.manager.memory_manager") as mm:
                mm.search_related_souvenirs = AsyncMock(return_value=[
                    {"id": str(souvenir.pk), "content": souvenir.content,
                     "metadata": {}},
                ])
                mm.search_related_connaissances = AsyncMock(return_value=[])
                trouve = await _tools()["memory_search"].handler({"query": "sante"})
            assert len(trouve["souvenirs"]) == 1, interne

    # ── Au-dessus de la barre : le perimetre, pas le tout ──────────

    async def test_un_authentifie_lie_voit_ses_engagements_et_les_orphelins(self):
        from memory.models import Commitment

        moi = await self._authentifie_lie()
        thomas = await self._entite("Thomas")
        await Commitment.objects.acreate(
            description="Te renvoyer le lien", person=moi, status="pending",
        )
        await Commitment.objects.acreate(
            description="Faire cette recette", person=None, status="pending",
        )
        await Commitment.objects.acreate(
            description="Rappeler Thomas", person=thomas, status="pending",
        )

        resultat = await _tools()["memory_list_commitments"].handler({})
        descriptions = {c["description"] for c in resultat["engagements"]}
        assert descriptions == {"Te renvoyer le lien", "Faire cette recette"}

    # ── Ecriture : un id hors perimetre ne se resout pas ───────────

    async def test_un_inconnu_ne_resout_pas_l_engagement_d_un_tiers(self):
        from memory.models import Commitment

        thomas = await self._entite("Thomas")
        engagement = await Commitment.objects.acreate(
            description="Rappeler Thomas", person=thomas, status="pending",
        )
        await self._inconnu_telegram()

        resultat = await _tools()["memory_resolve_commitment"].handler(
            {"commitment_id": engagement.pk}
        )
        assert "success" not in resultat

        intact = await Commitment.objects.aget(pk=engagement.pk)
        assert intact.status == "pending"
        assert intact.resolved_at is None

    async def test_un_authentifie_ne_resout_pas_l_engagement_d_un_tiers(self):
        """Hors perimetre, la reponse est celle d'un id inexistant : confirmer
        la ligne serait deja une fuite."""
        from memory.models import Commitment

        await self._authentifie_lie()
        thomas = await self._entite("Thomas")
        engagement = await Commitment.objects.acreate(
            description="Rappeler Thomas", person=thomas, status="pending",
        )

        resultat = await _tools()["memory_resolve_commitment"].handler(
            {"commitment_id": engagement.pk}
        )
        assert "introuvable" in resultat["error"]

        intact = await Commitment.objects.aget(pk=engagement.pk)
        assert intact.status == "pending"

    # ── Panne de la couche identite : on ferme ─────────────────────

    async def test_une_panne_de_la_couche_identite_ferme_la_porte(self):
        from datetime import date
        from memory.models import DailyJournal
        from utils.degradation import degradations

        await DailyJournal.objects.acreate(
            date=date.today(), narrative="Journee calme.",
        )
        set_current_person_id("tg_777")

        with patch("identity.resolver.identity_resolver.resolve_context",
                   AsyncMock(side_effect=RuntimeError("identite morte"))):
            resultat = await _tools()["memory_read_journal"].handler({})

        assert "message" in resultat
        assert "journaux" not in resultat
        assert degradations.count_for("outils memoire: perimetre") == 1
