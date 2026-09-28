"""REF-01 — la divulgation humaine, graduée.

Le couple binaire (``may_disclose_private_context`` pour la fiche,
``disclose_others: bool`` pour la mémoire des autres) devient, côté mémoire
des autres, un **niveau** : chaque souvenir / connaissance porte une
sensibilité (``anodin`` / ``personnel`` / ``confidence``, notée par
l'extracteur), et le tour porte un niveau divulgable (``identity.divulgation``)
calculé une fois au bord à partir de la certitude, du canal, de la proximité,
de la chaleur de l'ancre et du témoignage. Au-dessus du niveau : retiré ; en
dessous mais pas anodin : rendu **tagué** pour que Mika arbitre.

La fiche de l'interlocuteur lui-même reste régie par ``may_disclose`` — et la
calibration des preuves (``self_declared + shared_memory == 0,70``) ne bouge
pas (``test_identity_trust.py``).
"""

from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async

from identity.divulgation import (
    FERME, TOUT, Divulgation, DivulgationTuning, Niveau, decider, niveau_divulgable,
)
from identity.trust import ChannelTrust
from memory import sensibilite

_BACKEND = pathlib.Path(__file__).resolve().parent.parent


# ══════════════════════════════════════════════════════════════════════
# 1. La fonction pure : la matrice niveau × relation × canal
# ══════════════════════════════════════════════════════════════════════

class TestMatriceDuNiveau:

    # (certitude, canal, closeness, chaleur, temoin, attendu)
    _MATRICE = [
        # Salle publique : jamais plus qu'anodin, quoi qu'il en soit.
        (1.0, ChannelTrust.PUBLIC, "close", 1.0, True, Niveau.ANODIN),
        (0.70, ChannelTrust.PUBLIC, "friend", 0.0, False, Niveau.ANODIN),
        # Sous la barre sur un compte : anodin, même pour un proche.
        (0.45, ChannelTrust.ACCOUNT, "close", 1.0, True, Niveau.ANODIN),
        (0.69, ChannelTrust.ACCOUNT, "friend", 0.0, False, Niveau.ANODIN),
        # À la barre, sans lien : anodin.
        (0.70, ChannelTrust.ACCOUNT, "stranger", 0.0, False, Niveau.ANODIN),
        (0.70, ChannelTrust.ACCOUNT, "acquaintance", 0.1, False, Niveau.ANODIN),
        # À la barre, avec lien : personnel.
        (0.70, ChannelTrust.ACCOUNT, "friend", 0.0, False, Niveau.PERSONNEL),
        (0.70, ChannelTrust.ACCOUNT, "stranger", 0.5, False, Niveau.PERSONNEL),
        (0.70, ChannelTrust.ACCOUNT, "stranger", 0.0, True, Niveau.PERSONNEL),
        # Un proche à 0,70 n'a pas encore la confidence : il faut 0,85.
        (0.70, ChannelTrust.ACCOUNT, "close", 1.0, False, Niveau.PERSONNEL),
        (0.85, ChannelTrust.ACCOUNT, "close", 0.0, False, Niveau.CONFIDENCE),
        (0.85, ChannelTrust.ACCOUNT, "friend", 0.0, False, Niveau.PERSONNEL),
        (0.85, ChannelTrust.ACCOUNT, "stranger", 0.0, True, Niveau.CONFIDENCE),
        # Authentifié (1,0) : le canal ne donne pas le lien, la relation oui.
        (1.0, ChannelTrust.AUTHENTICATED, "stranger", 0.0, False, Niveau.ANODIN),
        (1.0, ChannelTrust.AUTHENTICATED, "friend", 0.0, False, Niveau.PERSONNEL),
        (1.0, ChannelTrust.AUTHENTICATED, "close", 0.0, False, Niveau.CONFIDENCE),
        # Interne : personne n'écoute.
        (0.0, ChannelTrust.INTERNAL, "", 0.0, False, Niveau.CONFIDENCE),
    ]

    @pytest.mark.parametrize("certitude,canal,closeness,chaleur,temoin,attendu", _MATRICE)
    def test_matrice(self, certitude, canal, closeness, chaleur, temoin, attendu):
        assert niveau_divulgable(
            certitude, canal, closeness=closeness, chaleur=chaleur,
            proximite_avec_concerne=temoin,
        ) is attendu

    def test_l_anecdote_sort_chez_l_ami_proche_sur_compte_a_0_70(self):
        assert niveau_divulgable(0.70, ChannelTrust.ACCOUNT, closeness="close") \
            is Niveau.PERSONNEL
        assert Divulgation(Niveau.PERSONNEL, Niveau.PERSONNEL).admet("personnel")

    def test_la_confidence_ne_sort_pas_chez_l_ami_proche_en_salle_publique(self):
        niveau = niveau_divulgable(
            1.0, ChannelTrust.ACCOUNT, closeness="close", chaleur=1.0,
            proximite_avec_concerne=True, audience_publique=True,
        )
        assert niveau is Niveau.ANODIN
        assert not Divulgation(niveau, niveau).admet("confidence", temoin=True)
        assert not Divulgation(niveau, niveau).admet("personnel")

    def test_la_confidence_sort_pour_la_personne_concernee_en_prive_a_0_85(self):
        assert niveau_divulgable(
            0.85, ChannelTrust.ACCOUNT, closeness="stranger",
            proximite_avec_concerne=True,
        ) is Niveau.CONFIDENCE

    def test_anodin_passe_partout_sauf_rien(self):
        for n in (Niveau.ANODIN, Niveau.PERSONNEL, Niveau.CONFIDENCE):
            assert Divulgation(n, n).admet("anodin")
        assert not FERME.admet("anodin")
        assert FERME.ferme and not TOUT.ferme

    def test_sous_0_70_rien_de_personnel(self):
        for certitude in (0.0, 0.25, 0.45, 0.699):
            n = niveau_divulgable(
                certitude, ChannelTrust.ACCOUNT, closeness="close", chaleur=1.0,
                proximite_avec_concerne=True,
            )
            assert n is Niveau.ANODIN, certitude

    def test_un_anon_tombe_sur_anodin(self):
        """Un ``anon_*`` est résolu PUBLIC à certitude nulle."""
        assert niveau_divulgable(0.0, ChannelTrust.PUBLIC) is Niveau.ANODIN

    def test_la_fonction_pure_ne_rend_jamais_rien(self):
        for canal in ChannelTrust:
            for c in (0.0, 0.7, 0.85, 1.0):
                assert niveau_divulgable(c, canal) is not Niveau.RIEN

    def test_le_tuning_est_lu_et_les_defauts_sont_la_calibration(self):
        from identity.trust import PRIVATE_CONTEXT_THRESHOLD, Certainty
        d = DivulgationTuning()
        assert d.barre_personnel == PRIVATE_CONTEXT_THRESHOLD
        assert d.barre_confidence == float(Certainty.BOUND)
        # Une barre plus basse ouvre plus tôt ; pure, aucune lecture de registre.
        bas = DivulgationTuning(barre_personnel=0.4, barre_confidence=0.6, chaleur_min=0.1)
        assert niveau_divulgable(0.6, ChannelTrust.ACCOUNT, chaleur=0.15, tuning=bas) \
            is Niveau.PERSONNEL
        assert niveau_divulgable(0.6, ChannelTrust.ACCOUNT, closeness="close", tuning=bas) \
            is Niveau.CONFIDENCE

    def test_decider_rend_les_deux_facettes_et_la_fiche(self):
        d = decider(0.70, ChannelTrust.ACCOUNT, closeness="stranger", fiche_ouverte=True)
        assert d.niveau is Niveau.ANODIN
        assert d.avec_temoin is Niveau.PERSONNEL
        assert d.fiche_ouverte is True
        assert d.admet("personnel", temoin=True) and not d.admet("personnel")

    def test_la_calibration_des_preuves_est_intacte(self):
        from identity.trust import EVIDENCE_WEIGHTS, PRIVATE_CONTEXT_THRESHOLD
        assert EVIDENCE_WEIGHTS["self_declared"] + EVIDENCE_WEIGHTS["shared_memory"] \
            == pytest.approx(PRIVATE_CONTEXT_THRESHOLD)
        assert PRIVATE_CONTEXT_THRESHOLD == DivulgationTuning().barre_personnel


# ══════════════════════════════════════════════════════════════════════
# 2. L'extracteur note la sensibilité ; la fiche la remonte, jamais ne la descend
# ══════════════════════════════════════════════════════════════════════

class TestSensibiliteExtraite:

    def test_la_quatrieme_ligne_est_lue_et_bornee(self):
        for brut, attendu in (
            ("anodin", "anodin"), (" Confidence ", "confidence"),
            ("personnel", "personnel"), ("secret", "personnel"),
            (3, "personnel"), (None, "personnel"),
        ):
            assert sensibilite.sensibilite_extraite(
                {"sensibilite": brut}, a_une_personne=True) == attendu

    def test_sans_personne_le_defaut_est_anodin(self):
        assert sensibilite.sensibilite_extraite({}, a_une_personne=False) == "anodin"
        assert sensibilite.sensibilite_extraite(
            {"sensibilite": "confidence"}, a_une_personne=False) == "confidence"

    def test_le_gabarit_demande_la_sensibilite(self):
        from memory.extraction.extractor import EXTRACTION_PROMPT_TEMPLATE as t
        assert '"sensibilite"' in t and "confidence" in t and "anodin" in t

    def test_plus_sensible_ne_descend_jamais(self):
        assert sensibilite.plus_sensible("confidence", "anodin") == "confidence"
        assert sensibilite.plus_sensible("anodin", "personnel") == "personnel"
        assert sensibilite.plus_sensible("n'importe quoi", "anodin") == "personnel"

    def test_la_surcharge_par_sujet_sensible_remonte_a_confidence(self):
        entites = [(1, "Alice", "person", ["santé mentale", "rechute"])]
        q = sensibilite.qualifier("Alice m'a dit qu'elle a rechuté", "anodin", entites)
        assert q is not None and q.sensibilite == "confidence"
        # Hors sujet : la sensibilité stockée reste.
        q = sensibilite.qualifier("Alice aime le café", "anodin", entites)
        assert q.sensibilite == "anodin"

    def test_la_surcharge_ne_descend_jamais(self):
        entites = [(1, "Alice", "person", [])]
        q = sensibilite.qualifier("Alice aime le café", "confidence", entites)
        assert q.sensibilite == "confidence"

    def test_qualifier_reconnait_l_interlocuteur_par_nom_ou_par_pk(self):
        entites = [(1, "Thomas", "person", []), (2, "Alice", "person", [])]
        q = sensibilite.qualifier("x", "personnel", entites, soi_nom="thomas")
        assert q.temoin is True and q.autres == ("Alice",)
        q = sensibilite.qualifier("x", "personnel", entites, soi_pk=1)
        assert q.temoin is True and q.autres == ("Alice",)
        seul = sensibilite.qualifier("x", "personnel", [(1, "Thomas", "person", [])], soi_pk=1)
        assert seul is None, "ne concerne aucun tiers"
        assert sensibilite.qualifier("x", "personnel", [(9, "Lyon", "place", [])]) is None

    def test_les_tags(self):
        q = sensibilite.Qualification(("Alice",), "personnel", False)
        assert sensibilite.tag(q) == " (confié en privé par Alice — pas à répéter à n'importe qui)"
        q = sensibilite.Qualification(("Alice", "Bob"), "confidence", True)
        assert sensibilite.tag(q) == " (une confidence de Alice et Bob — seulement parce que tu es en confiance)"
        assert sensibilite.tag(sensibilite.Qualification(("Alice",), "anodin", False)) == ""
        assert sensibilite.tag(None) == ""


@pytest.mark.django_db(transaction=True)
class TestSensibiliteEnBase:

    @pytest.fixture(autouse=True)
    def _isole(self):
        from memory.models import Connaissance, Entity, PersonProfile, Souvenir
        for m in (PersonProfile, Souvenir, Connaissance, Entity):
            m.objects.all().delete()
        yield
        for m in (PersonProfile, Souvenir, Connaissance, Entity):
            m.objects.all().delete()

    @staticmethod
    def _conso():
        from memory.storage.consolidator import MemoryConsolidator
        c = MemoryConsolidator(MagicMock(), MagicMock())
        c._index = AsyncMock(return_value=None)
        c._check_contradictions = AsyncMock(return_value=None)
        # Le dédoublonnage interroge ChromaDB (un MagicMock ici, truthy) :
        # sans ce court-circuit toute connaissance passerait pour un doublon.
        c._find_similar_souvenir = AsyncMock(return_value=None)
        c._find_similar_connaissance = AsyncMock(return_value=None)
        return c

    async def test_le_consolidateur_ecrit_la_sensibilite(self):
        from memory.models import Connaissance, Souvenir
        c = self._conso()
        await c.store_extractions([
            {"type": "souvenir", "content": "Alice m'a dit qu'elle a rechuté",
             "emotion": "sad", "importance": 0.8, "sensibilite": "confidence",
             "entities": [{"name": "Alice", "type": "person"}]},
            {"type": "souvenir", "content": "J'ai regardé la pluie",
             "emotion": "neutral", "importance": 0.2},
            {"type": "connaissance", "content": "Alice aime le café",
             "sensibilite": "anodin",
             "entities": [{"name": "Alice", "type": "person"}]},
            {"type": "connaissance", "content": "Alice cherche un boulot",
             "entities": [{"name": "Alice", "type": "person"}]},
        ], interlocutors=[])
        lire = lambda m, c: sync_to_async(  # noqa: E731
            lambda: m.objects.get(content=c).sensibilite)()
        assert await lire(Souvenir, "Alice m'a dit qu'elle a rechuté") == "confidence"
        assert await lire(Souvenir, "J'ai regardé la pluie") == "anodin", "sans personne"
        assert await lire(Connaissance, "Alice aime le café") == "anodin"
        assert await lire(Connaissance, "Alice cherche un boulot") == "personnel", "défaut"

    async def test_un_souvenir_redit_ne_devient_jamais_plus_leger(self):
        from django.utils import timezone
        from memory.models import Souvenir
        s = await Souvenir.objects.acreate(
            content="Alice a rechuté", sensibilite="confidence",
            importance=0.5, occurred_at=timezone.now())
        c = self._conso()
        c._find_similar_souvenir = AsyncMock(return_value=s)
        await c.store_extractions([
            {"type": "souvenir", "content": "Alice a rechuté", "sensibilite": "anodin"},
        ], interlocutors=[])
        await sync_to_async(s.refresh_from_db)()
        assert s.sensibilite == "confidence"

    async def test_la_fiche_remonte_a_la_lecture_sans_reecrire_la_ligne(self):
        """La surcharge par ``sensitive_topics`` se lit au point de lecture :
        la fiche est régénérée, ses sujets bougent, et une ligne réécrite ne
        redescendrait jamais. La base garde la valeur de l'extracteur."""
        from django.utils import timezone
        from memory import read
        from memory.models import Entity, PersonProfile, Souvenir
        alice = await Entity.objects.acreate(name="Alice", entity_type="person")
        await PersonProfile.objects.acreate(entity=alice, sensitive_topics=["rechute"])
        s = await Souvenir.objects.acreate(
            content="Alice m'a parlé de sa rechute", sensibilite="anodin",
            importance=0.5, occurred_at=timezone.now())
        await sync_to_async(s.entities.add)(alice)
        q = await read.qualifications(Souvenir, [s.pk], entity_id=None)
        assert q[s.pk].sensibilite == "confidence"
        await sync_to_async(s.refresh_from_db)()
        assert s.sensibilite == "anodin"


# ══════════════════════════════════════════════════════════════════════
# 3. Le retriever retire au-dessus du niveau, tague en dessous — trois voies
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(transaction=True)
class TestRetrieverGradue:

    @pytest.fixture(autouse=True)
    def _isole(self):
        from memory.models import Connaissance, Entity, Souvenir, Theme
        for m in (Souvenir, Connaissance, Theme, Entity):
            m.objects.all().delete()
        yield
        for m in (Souvenir, Connaissance, Theme, Entity):
            m.objects.all().delete()

    @staticmethod
    def _retriever():
        from memory.retrieval.retriever import MemoryRetriever
        r = MemoryRetriever(MagicMock())
        r.vector_store.remove_souvenir = MagicMock()
        return r

    async def _alice(self):
        from memory.models import Entity
        return await Entity.objects.acreate(name="Alice", entity_type="person")

    async def _souvenir(self, content, sens, *entites, importance=0.9):
        from django.utils import timezone
        from memory.models import Souvenir
        s = await Souvenir.objects.acreate(
            content=content, sensibilite=sens, importance=importance,
            occurred_at=timezone.now())
        for e in entites:
            await sync_to_async(s.entities.add)(e)
        return s

    @staticmethod
    def _hit(s):
        return {"id": str(s.pk), "content": s.content, "distance": 0.1,
                "metadata": {"confidence": 0.9}}

    async def _trio(self):
        alice = await self._alice()
        return (
            await self._souvenir("Alice aime le café", "anodin", alice),
            await self._souvenir("Alice cherche un boulot", "personnel", alice),
            await self._souvenir("Alice a rechuté", "confidence", alice),
        )

    async def test_voie_directe_retire_au_dessus_et_tague_en_dessous(self):
        anodin, perso, conf = await self._trio()
        r = self._retriever()
        hits = [self._hit(anodin), self._hit(perso), self._hit(conf)]
        d = Divulgation(Niveau.PERSONNEL, Niveau.PERSONNEL)
        out = await r._enrich_souvenirs(hits, boost_name="Thomas", divulgation=d)
        assert [s["id"] for s in out] == [anodin.pk, perso.pk]
        assert out[0]["tag"] == ""
        assert "confié en privé par Alice" in out[1]["tag"]
        # La ligne rendue porte le tag ; la ligne retirée est vivante (pas orpheline).
        assert "pas à répéter" in r._souvenir_line(out[1])
        r.vector_store.remove_souvenir.assert_not_called()

    async def test_au_niveau_confidence_tout_sort_tague(self):
        anodin, perso, conf = await self._trio()
        r = self._retriever()
        out = await r._enrich_souvenirs(
            [self._hit(conf)], boost_name="Thomas",
            divulgation=Divulgation(Niveau.CONFIDENCE, Niveau.CONFIDENCE))
        assert len(out) == 1 and "une confidence de Alice" in out[0]["tag"]

    async def test_rien_retire_meme_l_anodin(self):
        anodin, _, _ = await self._trio()
        r = self._retriever()
        assert await r._enrich_souvenirs([self._hit(anodin)], divulgation=FERME) == []

    async def test_ce_qui_concerne_l_interlocuteur_ou_personne_n_est_jamais_tague(self):
        alice = await self._alice()
        mien = await self._souvenir("Alice et moi avons ri", "confidence", alice)
        seule = await self._souvenir("Il pleuvait", "confidence")
        r = self._retriever()
        out = await r._enrich_souvenirs(
            [self._hit(mien), self._hit(seule)], boost_name="Alice", divulgation=FERME)
        assert [s["tag"] for s in out] == ["", ""]

    async def test_connaissances_filtrees_et_taguees_pareil(self):
        from memory.models import Connaissance
        alice = await self._alice()
        c1 = await Connaissance.objects.acreate(content="Alice aime le café", sensibilite="anodin")
        c2 = await Connaissance.objects.acreate(content="Alice cherche un boulot", sensibilite="personnel")
        c3 = await Connaissance.objects.acreate(content="Alice a rechuté", sensibilite="confidence")
        for c in (c1, c2, c3):
            await sync_to_async(c.entities.add)(alice)
        r = self._retriever()
        out = await r._enrich_connaissances(
            [self._hit(c1), self._hit(c2), self._hit(c3)], boost_name="Thomas",
            divulgation=Divulgation(Niveau.PERSONNEL, Niveau.PERSONNEL))
        assert [c["content"] for c in out] == ["Alice aime le café", "Alice cherche un boulot"]
        assert out[1]["tag"] and not out[0]["tag"]
        bloc = r._format_context(out, [])
        assert "(concerne: Alice) [probable] (confié en privé par Alice" in bloc

    async def test_les_voies_non_lexicales_suivent_le_niveau(self):
        from memory.models import Theme
        alice = await self._alice()
        theme, _ = await sync_to_async(Theme.objects.get_or_create)(name="cafe")
        anodin = await self._souvenir("Alice aime le café", "anodin", alice, importance=0.9)
        conf = await self._souvenir("Alice a rechuté", "confidence", alice, importance=0.95)
        for s in (anodin, conf):
            await sync_to_async(s.themes.add)(theme)
        r = self._retriever()
        ancre = [{"id": 999_999, "themes": ["cafe"], "entities": []}]
        d = Divulgation(Niveau.ANODIN, Niveau.ANODIN)
        with patch("configs.service.config_service.get", lambda k, *a, **kw: {
                "memory.assoc_expansion_enabled": True, "memory.assoc_expansion_max": 1,
                "memory.assoc_min_importance": 0.5}.get(k, kw.get("default"))):
            assoc = await r._associative_expansion(ancre, set(), boost_name="Thomas", divulgation=d)
        assert [a["id"] for a in assoc] == [anodin.pk], "le plus important est retiré, l'anodin sort"
        with patch("configs.service.config_service.get", lambda k, *a, **kw: {
                "memory.intrusion_enabled": True, "memory.intrusion_charge_threshold": 0.0,
                "memory.intrusion_min_importance": 0.5}.get(k, kw.get("default"))):
            intr = await r._importance_intrusion(set(), 1.0, boost_name="Thomas", divulgation=d)
        assert [a["id"] for a in intr] == [anodin.pk]

    async def test_la_voie_episodique_est_tout_ou_rien(self):
        """La voie chaude (SON verbatim) suit la fiche ; les échanges du plan
        (verbatim d'autrui) ne sortent qu'à ``confidence``."""
        from memory.episodic.api import ExchangeHit
        r = self._retriever()
        search = AsyncMock(return_value=[])
        with patch("identity.resolver.identity_resolver.handles_for_person",
                   AsyncMock(return_value=[{"person_id": "tg_42"}])), \
             patch("memory.episodic.api.search_exchanges", search):
            fermee = Divulgation(Niveau.CONFIDENCE, Niveau.CONFIDENCE, fiche_ouverte=False)
            assert await r._episodic_lane("q", "tg_42", divulgation=fermee) == []
            search.assert_not_called()
            ouverte = Divulgation(Niveau.ANODIN, Niveau.ANODIN, fiche_ouverte=True)
            await r._episodic_lane("q", "tg_42", divulgation=ouverte)
            search.assert_called_once()

        du_plan = ExchangeHit("5", "Alice: secret", "tg_9", 1, 5, 6, 0.0, 0.2)
        vals = {"memory.retrieval_souvenirs": 5, "memory.retrieval_connaissances": 5,
                "memory.min_importance": 0.3, "memory.retrieval_fetch_multiplier": 3,
                "memory.retrieval_exchanges": 3}
        r.vector_store.search_souvenirs = MagicMock(return_value=[])
        r.vector_store.search_connaissances = MagicMock(return_value=[])
        with patch("configs.service.config_service.get",
                   lambda k, *a, **kw: vals.get(k, kw.get("default", 0))), \
             patch.object(r, "_episodic_lane", AsyncMock(return_value=[])), \
             patch.object(r, "_person_boost_name", AsyncMock(return_value="")):
            perso = await r.retrieve_multi(
                ["q"], person_id="tg_42", extra_exchanges=[du_plan],
                divulgation=Divulgation(Niveau.PERSONNEL, Niveau.PERSONNEL, fiche_ouverte=True))
            conf = await r.retrieve_multi(
                ["q"], person_id="tg_42", extra_exchanges=[du_plan],
                divulgation=Divulgation(Niveau.CONFIDENCE, Niveau.CONFIDENCE, fiche_ouverte=True))
        assert "secret" not in perso and "secret" in conf

    async def test_une_base_en_panne_ne_sert_le_brut_qu_a_confidence(self):
        r = self._retriever()
        hit = {"id": "4242", "content": "Alice a rechuté", "distance": 0.2, "metadata": {}}
        with patch.object(type(r), "_load_by_pk", AsyncMock(return_value=None)):
            assert await r._enrich_souvenirs(
                [hit], divulgation=Divulgation(Niveau.PERSONNEL, Niveau.PERSONNEL)) == []
            assert len(await r._enrich_souvenirs([hit], divulgation=TOUT)) == 1


# ══════════════════════════════════════════════════════════════════════
# 4. L'outil memory_search : refus par ligne, tags pareils
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(transaction=True)
class TestMemorySearchGradue:

    @pytest.fixture(autouse=True)
    def _isole(self):
        from memory.models import Entity, Souvenir
        from pipeline.tracing import set_current_person_id
        Souvenir.objects.all().delete()
        Entity.objects.all().delete()
        set_current_person_id("tg_7")
        yield
        set_current_person_id("")
        Souvenir.objects.all().delete()
        Entity.objects.all().delete()

    async def _lignes(self):
        from django.utils import timezone
        from memory.models import Entity, Souvenir
        alice = await Entity.objects.acreate(name="Alice", entity_type="person")
        out = []
        for content, sens in (("Alice aime le café", "anodin"),
                              ("Alice cherche un boulot", "personnel"),
                              ("Alice a rechuté", "confidence")):
            s = await Souvenir.objects.acreate(
                content=content, sensibilite=sens, importance=0.9,
                occurred_at=timezone.now())
            await sync_to_async(s.entities.add)(alice)
            out.append(s)
        return out

    async def _chercher(self, niveau):
        from memory.module import MemoryToolsModule, _Perimetre
        lignes = await self._lignes()
        tool = next(t for t in MemoryToolsModule().return_tools() if t.name == "memory_search")
        perimetre = _Perimetre(False, False, None, niveau=Divulgation(niveau, niveau))
        with patch("memory.manager.memory_manager") as mm, \
             patch("memory.module._perimetre", new=AsyncMock(return_value=perimetre)):
            mm.search_related_souvenirs = AsyncMock(return_value=[
                {"id": str(s.pk), "content": s.content, "metadata": {}} for s in lignes])
            mm.search_related_connaissances = AsyncMock(return_value=[])
            return await tool.handler({"query": "Alice"})

    async def test_refus_par_ligne_et_tags(self):
        out = await self._chercher(Niveau.PERSONNEL)
        contenus = [s["content"] for s in out["souvenirs"]]
        assert contenus == [
            "Alice aime le café",
            "Alice cherche un boulot (confié en privé par Alice — pas à répéter à n'importe qui)",
        ]

    async def test_rien_donne_le_refus_poli(self):
        out = await self._chercher(Niveau.RIEN)
        assert "souvenirs" not in out and "en face" in out["message"]

    async def test_a_confidence_tout_sort(self):
        out = await self._chercher(Niveau.CONFIDENCE)
        assert len(out["souvenirs"]) == 3
        assert "une confidence de Alice" in out["souvenirs"][2]["content"]


# ══════════════════════════════════════════════════════════════════════
# 5. Le journal d'hier : rédigé sous ``personnel``, complet à partir de là
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db(transaction=True)
class TestJournalGradue:

    async def test_redaction_des_tiers_sous_personnel(self):
        from memory.models import DailyJournal
        from memory.read import yesterday
        from pipeline.context_blocks import _fetch_journal_context
        hier = yesterday()
        await sync_to_async(DailyJournal.objects.update_or_create)(
            date=hier, defaults=dict(
                narrative="Thomas m'a raconte que sa mere etait hospitalisee.",
                persons_interacted=["Thomas"], dominant_emotion="sad"))
        try:
            rien = await _fetch_journal_context(niveau=Niveau.RIEN)
            anodin = await _fetch_journal_context(niveau=Niveau.ANODIN)
            perso = await _fetch_journal_context(niveau=Niveau.PERSONNEL)
            conf = await _fetch_journal_context(niveau=Niveau.CONFIDENCE)
        finally:
            await sync_to_async(lambda: DailyJournal.objects.filter(date=hier).delete())()
        for bloc in (rien, anodin):
            assert "Thomas" not in bloc and "quelqu'un" in bloc and "hospitalisee" in bloc
        for bloc in (perso, conf):
            assert "Thomas" in bloc and "Tu avais interagi avec" in bloc


# ══════════════════════════════════════════════════════════════════════
# 6. Le bord : le niveau calculé une fois par tour
# ══════════════════════════════════════════════════════════════════════

class TestLeBord:

    @staticmethod
    def _ctx(**kw):
        base = dict(person_id="tg_1", is_internal=False, entity_id=None,
                    certainty=0.70, trust=ChannelTrust.ACCOUNT, may_disclose=True)
        base.update(kw)
        return SimpleNamespace(**base)

    async def test_un_tour_interne_porte_sa_memoire_entiere(self):
        from pipeline.context_blocks import divulgation_du_tour
        assert await divulgation_du_tour(self._ctx(is_internal=True)) is TOUT

    async def test_les_cinq_entrees_sont_lues(self):
        from pipeline import context_blocks as cb
        with patch("memory.read.closeness_of", new=AsyncMock(return_value="close")) as clo, \
             patch.object(cb.emotion_engine, "chaleur_envers",
                          new=AsyncMock(return_value=0.0)) as cha:
            d = await cb.divulgation_du_tour(self._ctx(entity_id=4, certainty=0.85))
        assert clo.await_args.args == (4,)
        assert cha.await_args.args == ("tg_1",)
        assert d.niveau is Niveau.CONFIDENCE and d.fiche_ouverte is True

    async def test_la_chaleur_seule_ouvre_le_personnel(self):
        from pipeline import context_blocks as cb
        with patch("memory.read.closeness_of", new=AsyncMock(return_value="")), \
             patch.object(cb.emotion_engine, "chaleur_envers", new=AsyncMock(return_value=0.5)):
            d = await cb.divulgation_du_tour(self._ctx())
        assert d.niveau is Niveau.PERSONNEL

    async def test_un_anon_tombe_sur_anodin(self):
        from pipeline import context_blocks as cb
        with patch("memory.read.closeness_of", new=AsyncMock(return_value="")), \
             patch.object(cb.emotion_engine, "chaleur_envers", new=AsyncMock(return_value=0.0)):
            d = await cb.divulgation_du_tour(self._ctx(
                person_id="anon_x", certainty=0.0, trust=ChannelTrust.PUBLIC,
                may_disclose=False))
        assert d.niveau is Niveau.ANODIN and d.avec_temoin is Niveau.ANODIN
        assert d.fiche_ouverte is False

    async def test_une_panne_ferme(self):
        from pipeline import context_blocks as cb
        from utils.degradation import degradations
        degradations.reset()
        with patch("memory.read.closeness_of", new=AsyncMock(side_effect=RuntimeError("locked"))):
            d = await cb.divulgation_du_tour(self._ctx(entity_id=4))
        assert d is FERME
        assert degradations.count_for("prompt: niveau de divulgation") == 1

    async def test_gather_context_porte_le_niveau_et_le_passe_au_rappel(self):
        from pipeline import context as ctx_mod
        niveau = Divulgation(Niveau.PERSONNEL, Niveau.PERSONNEL, fiche_ouverte=True)
        identity_ctx = self._ctx()
        with patch.object(ctx_mod.identity_resolver, "resolve_context",
                          new=AsyncMock(return_value=identity_ctx)), \
             patch.object(ctx_mod, "divulgation_du_tour",
                          new=AsyncMock(return_value=niveau)), \
             patch.object(ctx_mod, "memory_manager") as mm, \
             patch.object(ctx_mod, "_fetch_self_concept", new=AsyncMock(return_value="")), \
             patch.object(ctx_mod, "_fetch_person_context", new=AsyncMock(return_value="")), \
             patch.object(ctx_mod, "_fil_de_conversation", new=AsyncMock(return_value=([], ""))), \
             patch.object(ctx_mod, "_etat_cognitif", new=AsyncMock(return_value="")), \
             patch.object(ctx_mod, "_fetch_rumination_context", new=AsyncMock(return_value="")), \
             patch.object(ctx_mod, "_fetch_travaux_context", new=AsyncMock(return_value="")), \
             patch.object(ctx_mod, "_reve_et_journal", new=AsyncMock(return_value=("", None, ""))) as rj, \
             patch.object(ctx_mod, "_projet_du_tour", new=AsyncMock(return_value=("", False, None))), \
             patch.object(ctx_mod, "_launch_preparation", return_value=(None, 0.0)), \
             patch.object(ctx_mod, "_humeur_et_pulsions", return_value=""), \
             patch.object(ctx_mod, "_contexte_modules", return_value=""), \
             patch.object(ctx_mod, "_format_identity_block", return_value=""):
            mm.get_memory_context = AsyncMock(return_value="")
            mm.recall_unavailable = False
            out = await ctx_mod.gather_context("salut", "tg_1", include_tools=False)
        assert out.niveau_divulgation is niveau
        assert mm.get_memory_context.await_args.kwargs["divulgation"] is niveau
        assert rj.await_args.args[1] is Niveau.PERSONNEL

    def test_le_contexte_vide_est_ferme(self):
        from pipeline.context import ConversationContext
        assert ConversationContext().niveau_divulgation is FERME

    async def test_le_bridge_de_la_conscience_passe_le_niveau_du_destinataire(self):
        from conscience.memory_bridge import MemoryBridge
        niveau = Divulgation(Niveau.ANODIN, Niveau.PERSONNEL)
        with patch("memory.manager.memory_manager") as mm, \
             patch("identity.resolver.identity_resolver.resolve_context",
                   new=AsyncMock(return_value=SimpleNamespace(may_disclose=False))), \
             patch("pipeline.context_blocks.divulgation_du_tour",
                   new=AsyncMock(return_value=niveau)):
            mm.get_memory_context_multi = AsyncMock(return_value="")
            await MemoryBridge().recall_for_context(["q"], person_id="tg_42", channel="telegram")
        assert mm.get_memory_context_multi.await_args.kwargs["divulgation"] is niveau

    async def test_la_chaleur_vit_dans_le_moteur_emotionnel(self):
        """``_chaleur_pour`` (conscience) délègue ; ``pipeline`` n'importe
        pas ``conscience`` pour la lire."""
        from conscience.memory_bridge import MemoryBridge, _CHALEUR_POIDS
        with patch("emotion.engine.emotion_engine.chaleur_envers",
                   new=AsyncMock(side_effect=[0.2, 0.6])):
            assert await MemoryBridge()._chaleur_pour(["a", "b"]) == pytest.approx(
                1.0 + _CHALEUR_POIDS * 0.6)
        src = (_BACKEND / "pipeline" / "context_blocks.py").read_text(encoding="utf-8")
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "divulgation_du_tour")
        modules = {
            n.module for n in ast.walk(fn) if isinstance(n, ast.ImportFrom) and n.module
        } | {a.name for n in ast.walk(fn) if isinstance(n, ast.Import) for a in n.names}
        assert modules and not any(m.split(".")[0] == "conscience" for m in modules), modules

    async def test_chaleur_envers_lit_l_ancre(self):
        from emotion.engine import EmotionEngine
        e = EmotionEngine.__new__(EmotionEngine)
        e.person_moods = {"p": SimpleNamespace(anchor=(0.4, 0.1, 0.0)),
                          "froid": SimpleNamespace(anchor=(-0.3, 0.0, 0.0))}
        with patch.object(EmotionEngine, "ensure_person_loaded", new=AsyncMock()):
            assert await e.chaleur_envers("p") == pytest.approx(0.4)
            assert await e.chaleur_envers("froid") == 0.0
            assert await e.chaleur_envers("inconnu") == 0.0


# ══════════════════════════════════════════════════════════════════════
# 7. Le tableau de bord montre le niveau, et l'ancien booléen n'existe plus
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.django_db
class TestTableauDeBord:

    def test_la_fiche_personne_annonce_le_niveau(self, client, settings):
        from django.urls import reverse
        from memory.models import Entity, PersonProfile
        from identity.models import Identity, IdentityHandle
        settings.DASHBOARD_REQUIRE_AUTH = False
        alice = Entity.objects.create(name="Alice", entity_type="person")
        PersonProfile.objects.create(entity=alice, closeness="close")
        ident = Identity.objects.create(entity=alice, certainty=0.85, display_name="Alice")
        IdentityHandle.objects.create(identity=ident, person_id="tg_alice", channel="telegram",
                                      trust="account")
        r = client.get(reverse("gestionsysteme:person-detail-tab", args=[alice.pk, "synthese"]))
        assert r.status_code == 200
        d = r.context["divulgation"]
        assert d["niveau"] == "confidence" and d["closeness"] == "close"
        assert d["certitude"] == pytest.approx(0.85)
        assert "Divulgation graduée" in r.content.decode()

    def test_les_listes_portent_la_sensibilite(self, client, settings):
        from django.urls import reverse
        from django.utils import timezone
        from memory.models import Connaissance, Entity, Souvenir
        settings.DASHBOARD_REQUIRE_AUTH = False
        alice = Entity.objects.create(name="Alice", entity_type="person")
        s = Souvenir.objects.create(content="Alice a rechuté", sensibilite="confidence",
                                    occurred_at=timezone.now())
        s.entities.add(alice)
        c = Connaissance.objects.create(content="Alice aime le café", sensibilite="anodin")
        c.entities.add(alice)
        html = client.get(reverse("gestionsysteme:person-detail-tab",
                                  args=[alice.pk, "souvenirs"])).content.decode()
        assert ">Confidence<" in html
        html = client.get(reverse("gestionsysteme:person-detail-tab",
                                  args=[alice.pk, "connaissances"])).content.decode()
        assert ">Anodin<" in html


class TestNettoyage:

    @staticmethod
    def _noms(tree):
        for n in ast.walk(tree):
            if isinstance(n, ast.arg):
                yield n.arg
            elif isinstance(n, ast.keyword) and n.arg:
                yield n.arg
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield n.name
            elif isinstance(n, ast.Attribute):
                yield n.attr
            elif isinstance(n, ast.Name):
                yield n.id

    def test_le_booleen_n_existe_plus_nulle_part(self):
        """``disclose_others`` (paramètre, mot-clé, attribut) et les deux
        filtres ensemblistes qu'il pilotait ont disparu du backend, tests
        compris — sur l'AST, jamais sur le texte (les commentaires racontent
        ce qui ne doit plus être fait)."""
        disparus = {"disclose_others", "sans_confidences_d_autrui",
                    "rows_mentioning_others", "_sans_les_autres", "_peut_divulguer"}
        restes = {}
        for path in _BACKEND.rglob("*.py"):
            if any(part in ("migrations", "__pycache__", "node_modules") for part in path.parts):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            trouves = disparus & set(self._noms(tree))
            if trouves:
                restes[str(path.relative_to(_BACKEND))] = trouves
        assert not restes, restes
