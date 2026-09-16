"""Section MEM de l'audit du 2026-09-16 (docs/audit-2026-09-16.md).

- MEM-01 : `memory_search` retrouve un souvenir endormi.
- MEM-02 : l'extracteur voit le prénom de l'interlocuteur ; une connaissance
  qui ne nomme personne est reliée à l'interlocuteur identifié.
- MEM-03 : une entité se résout sans égard à la casse.
- MEM-04 / MEM-10 : une fenêtre part mûre ou calme, jamais sur une question
  dont la réponse est attendue ; le plafond suit ce qui part.
- MEM-05 : un souvenir redit se renforce, un engagement redit ne se double pas.
- MEM-06 : le renforcement d'une connaissance repose l'ancre de décroissance.
- MEM-07 : un échec d'indexation est compté ; les manquants sont rattrapés.
- MEM-08 : une fenêtre interne fait avancer un checkpoint ÉCRIT.
- MEM-09 : le rappel d'un acte spontané passe par la porte de divulgation.
- MEM-11 : un monologue sans destinataire n'est pas extrait ; le souvenir
  réflexif n'est écrit qu'une fois ; l'importance d'un travail suit `notable`.
- MEM-12 : la sélection des fiches est horaire.
- MEM-15 / MEM-16 : rétention et types.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone


def _make_consolidator(last_id=0, extractions=None):
    from memory.storage.consolidator import MemoryConsolidator

    c = MemoryConsolidator.__new__(MemoryConsolidator)
    c.vector_store = MagicMock()
    c.vector_store.search_souvenirs = MagicMock(return_value=[])
    c.vector_store.search_connaissances = MagicMock(return_value=[])
    c.extractor = MagicMock()
    c.extractor.analyze_messages = AsyncMock(return_value=extractions or [])
    c._last_processed_id = last_id
    return c


async def _conv():
    from memory.models import Conversation

    return await sync_to_async(Conversation.objects.create)()


async def _msg(conv, content, *, role="user", person_id="", age_s=0, source="frontend"):
    from memory.models import Message

    m = await sync_to_async(Message.objects.create)(
        conversation=conv, role=role, content=content, person_id=person_id,
        source=source,
    )
    if age_s:
        await sync_to_async(
            lambda: Message.objects.filter(pk=m.pk).update(
                created_at=timezone.now() - timedelta(seconds=age_s),
            )
        )()
    return m


def _rows(*specs):
    """``(role, age_s)`` → dicts tels que ``_select_window`` les lit."""
    now = timezone.now()
    return [
        {"id": i + 1, "role": role, "content": f"m{i}",
         "created_at": now - timedelta(seconds=age), "source": "frontend",
         "person_id": "web_x"}
        for i, (role, age) in enumerate(specs)
    ]


# ===================================================================
# MEM-04 / MEM-10 — la cadence d'extraction (pure)
# ===================================================================


class TestCadenceDExtraction:

    def _c(self):
        c = _make_consolidator()
        c._cadence_extraction = True
        return c

    def test_une_question_fraiche_sans_reponse_est_retenue(self):
        c = self._c()
        rows = _rows(("user", 400), ("assistant", 390), ("user", 5))
        kept, plafond = c._borner_la_cadence(rows, 3, force=False)
        assert [m["id"] for m in kept] == [1, 2]
        assert plafond == 2  # le checkpoint ne saute pas la question retenue

    def test_une_question_ancienne_sans_reponse_part(self):
        c = self._c()
        rows = _rows(("user", 900), ("assistant", 890), ("user", 700))
        kept, plafond = c._borner_la_cadence(rows, 3, force=False)
        assert [m["id"] for m in kept] == [1, 2, 3] and plafond == 3

    def test_une_petite_fenetre_fraiche_attend(self):
        c = self._c()
        rows = _rows(("user", 60), ("assistant", 50))
        assert c._borner_la_cadence(rows, 2, force=False) == ([], None)

    def test_une_petite_fenetre_calme_part(self):
        c = self._c()
        rows = _rows(("user", 900), ("assistant", 890))
        kept, plafond = c._borner_la_cadence(rows, 2, force=False)
        assert len(kept) == 2 and plafond == 2

    def test_une_fenetre_mure_part_meme_fraiche(self):
        c = self._c()
        rows = _rows(*[("user" if i % 2 == 0 else "assistant", 30) for i in range(6)])
        kept, _ = c._borner_la_cadence(rows, 6, force=False)
        assert len(kept) == 6

    def test_force_ignore_la_maturite_mais_pas_la_question_en_attente(self):
        c = self._c()
        rows = _rows(("user", 60), ("assistant", 50), ("user", 5))
        kept, plafond = c._borner_la_cadence(rows, 3, force=True)
        assert [m["id"] for m in kept] == [1, 2] and plafond == 2

    def test_une_fenetre_qui_n_est_qu_une_question_fraiche_attend(self):
        c = self._c()
        assert c._borner_la_cadence(_rows(("user", 5)), 1, force=True) == ([], None)

    @pytest.mark.django_db(transaction=True)
    async def test_de_bout_en_bout_la_reponse_part_avec_sa_question(self):
        from memory.models import Message

        await sync_to_async(Message.objects.all().delete)()
        conv = await _conv()
        await _msg(conv, "tu connais Zelda ?", age_s=10)
        c = self._c()
        await c._consolidate()
        c.extractor.analyze_messages.assert_not_awaited()
        assert c._last_processed_id == 0

        await _msg(conv, "oui ! on y joue ?", role="assistant", age_s=5)
        await c._consolidate(force=True)
        sent = c.extractor.analyze_messages.await_args[0][0]
        assert [m["content"] for m in sent] == ["tu connais Zelda ?", "oui ! on y joue ?"]


# ===================================================================
# MEM-08 — la fenêtre interne écrit son checkpoint
# ===================================================================


@pytest.mark.django_db(transaction=True)
class TestCheckpointInterne:

    async def test_un_brief_interne_seul_ecrit_un_checkpoint(self):
        from memory.models import ConsolidationLog, Message

        await sync_to_async(Message.objects.all().delete)()
        await sync_to_async(ConsolidationLog.objects.all().delete)()
        conv = await _conv()
        brief = await sync_to_async(Message.objects.create)(
            conversation=conv, role="user", content="Accueille-le.",
            is_internal=True, source="web_connect",
        )
        c = _make_consolidator()
        await c._consolidate()
        assert c._last_processed_id == brief.pk
        dernier = await sync_to_async(
            lambda: ConsolidationLog.objects.order_by("-pk").first()
        )()
        assert dernier is not None and dernier.last_message_id == brief.pk


# ===================================================================
# MEM-02 — locuteurs nommés, connaissance reliée
# ===================================================================


class TestLocuteursNommes:

    async def test_le_texte_soumis_porte_le_prenom(self):
        from memory.extraction.extractor import MemoryExtractor

        e = MemoryExtractor()
        vu = {}

        async def _capture(prompt, role):
            vu["prompt"] = prompt
            return '{"extractions": []}'

        with patch.object(e, "_query_model", new=_capture), \
             patch("config.personality.personality") as perso:
            perso.name = "Mika"
            perso.description = "d"
            perso.tone = "t"
            perso.traits = []
            await e.analyze_messages([
                {"role": "user", "content": "je bosse pas en banque", "speaker": "Thomas"},
                {"role": "assistant", "content": "ah bon ?"},
                {"role": "user", "content": "salut", "speaker": ""},
            ])
        assert "PERSONNES DANS LA CONVERSATION: Thomas" in vu["prompt"]
        assert "Thomas: je bosse pas en banque" in vu["prompt"]
        assert "Mika: ah bon ?" in vu["prompt"]
        assert "User: salut" in vu["prompt"]

    def test_la_regle_est_dans_le_gabarit(self):
        from memory.extraction.extractor import EXTRACTION_PROMPT_TEMPLATE

        assert "l'utilisateur" in EXTRACTION_PROMPT_TEMPLATE
        assert "PRENOM" in EXTRACTION_PROMPT_TEMPLATE

    @pytest.mark.django_db(transaction=True)
    async def test_une_connaissance_sans_personne_est_reliee_a_l_interlocuteur(self):
        from memory.models import Connaissance, Entity

        await sync_to_async(Connaissance.objects.all().delete)()
        thomas = await sync_to_async(Entity.objects.create)(name="Thomas", entity_type="person")
        c = _make_consolidator()
        c._find_similar_connaissance = AsyncMock(return_value=None)
        c._check_contradictions = AsyncMock()
        await c.store_extractions(
            [{"type": "connaissance", "store": True,
              "content": "Ne travaille pas dans une banque", "themes": [], "entities": []}],
            interlocutors=[thomas],
        )
        row = await sync_to_async(Connaissance.objects.get)(content__startswith="Ne travaille")
        noms = await sync_to_async(lambda: [e.name for e in row.entities.all()])()
        assert noms == ["Thomas"]

    @pytest.mark.django_db(transaction=True)
    async def test_une_connaissance_qui_nomme_quelqu_un_d_autre_n_est_pas_reliee(self):
        from memory.models import Connaissance, Entity

        await sync_to_async(Connaissance.objects.all().delete)()
        thomas = await sync_to_async(Entity.objects.create)(name="Thomas", entity_type="person")
        c = _make_consolidator()
        c._find_similar_connaissance = AsyncMock(return_value=None)
        c._check_contradictions = AsyncMock()
        await c.store_extractions(
            [{"type": "connaissance", "store": True, "content": "Alice aime le café",
              "themes": [], "entities": [{"name": "Alice", "type": "person"}]}],
            interlocutors=[thomas],
        )
        row = await sync_to_async(Connaissance.objects.get)(content="Alice aime le café")
        noms = await sync_to_async(lambda: sorted(e.name for e in row.entities.all()))()
        assert noms == ["Alice"]


# ===================================================================
# MEM-03 — casse des entités
# ===================================================================


@pytest.mark.django_db(transaction=True)
class TestEntitesSansEgardALaCasse:

    async def test_adrien_minuscule_retrouve_adrien(self):
        from memory.models import Entity

        await sync_to_async(Entity.objects.all().delete)()
        original = await sync_to_async(Entity.objects.create)(name="Adrien", entity_type="person")
        c = _make_consolidator()
        _, entities = await c._resolve_tags(
            {"themes": [], "entities": [{"name": "adrien", "type": "person"}]}
        )
        assert [e.pk for e in entities] == [original.pk]
        assert await sync_to_async(Entity.objects.filter(name__iexact="adrien").count)() == 1

    async def test_la_commande_fusionne_les_doublons_existants(self):
        from django.core.management import call_command

        from memory.models import Connaissance, Entity, Souvenir

        await sync_to_async(Entity.objects.all().delete)()
        maj = await sync_to_async(Entity.objects.create)(name="Adrien", entity_type="person")
        minu = await sync_to_async(Entity.objects.create)(name="adrien", entity_type="person")
        s = await sync_to_async(Souvenir.objects.create)(
            content="x", importance=0.5, occurred_at=timezone.now(),
        )
        await sync_to_async(s.entities.add)(minu)
        k = await sync_to_async(Connaissance.objects.create)(content="y")
        await sync_to_async(k.entities.add)(minu)

        await sync_to_async(call_command)("fusionner_entites")

        assert await sync_to_async(Entity.objects.filter(name__iexact="adrien").count)() == 1
        restant = await sync_to_async(Entity.objects.get)(name__iexact="adrien")
        # La ligne la plus riche (un souvenir) est gardée ; le NOM garde sa
        # majuscule, quelle que soit la ligne survivante.
        assert restant.pk == minu.pk and restant.name == "Adrien"
        assert await sync_to_async(lambda: list(s.entities.values_list("pk", flat=True)))() == [restant.pk]
        assert await sync_to_async(lambda: list(k.entities.values_list("pk", flat=True)))() == [restant.pk]
        assert not await sync_to_async(Entity.objects.filter(pk=maj.pk).exists)()


# ===================================================================
# MEM-05 — dédup à l'écriture
# ===================================================================


@pytest.mark.django_db(transaction=True)
class TestDedupALEcriture:

    async def test_un_souvenir_redit_se_renforce(self):
        from memory.models import Souvenir

        await sync_to_async(Souvenir.objects.all().delete)()
        existant = await sync_to_async(Souvenir.objects.create)(
            content="On a vu un requin projecteur", importance=0.4,
            occurred_at=timezone.now(), emotion="amused",
        )
        c = _make_consolidator()
        c.vector_store.search_souvenirs = MagicMock(return_value=[
            {"id": str(existant.pk), "distance": 0.05, "content": existant.content, "metadata": {}},
        ])
        counts = await c.store_extractions(
            [{"type": "souvenir", "store": True, "content": "On a vu un requin projecteur !",
              "emotion": "amused", "importance": 0.5, "themes": [], "entities": []}],
            interlocutors=[],
        )
        assert counts["souvenirs"] == 0
        assert await sync_to_async(Souvenir.objects.count)() == 1
        await sync_to_async(existant.refresh_from_db)()
        assert existant.importance == pytest.approx(0.55)
        assert existant.decayed_at is not None

    async def test_un_souvenir_different_est_cree(self):
        from memory.models import Souvenir

        await sync_to_async(Souvenir.objects.all().delete)()
        existant = await sync_to_async(Souvenir.objects.create)(
            content="On a vu un requin", importance=0.4, occurred_at=timezone.now(),
        )
        c = _make_consolidator()
        c.vector_store.search_souvenirs = MagicMock(return_value=[
            {"id": str(existant.pk), "distance": 0.4, "content": "", "metadata": {}},
        ])
        counts = await c.store_extractions(
            [{"type": "souvenir", "store": True, "content": "On a parlé de Zelda",
              "emotion": "happy", "themes": [], "entities": []}],
            interlocutors=[],
        )
        assert counts["souvenirs"] == 1
        assert await sync_to_async(Souvenir.objects.count)() == 2

    async def test_un_engagement_redit_ne_se_double_pas(self):
        from memory.models import Commitment

        await sync_to_async(Commitment.objects.all().delete)()
        await sync_to_async(Commitment.objects.create)(
            description="Lui envoyer le lien du concert", status="pending",
        )
        c = _make_consolidator()
        counts = await c.store_extractions(
            [{"type": "commitment", "store": True,
              "content": "Lui envoyer le lien du concert !", "person": ""}],
            interlocutors=[],
        )
        assert counts["commitments"] == 0
        assert await sync_to_async(Commitment.objects.count)() == 1

    async def test_un_engagement_different_est_cree(self):
        from memory.models import Commitment

        await sync_to_async(Commitment.objects.all().delete)()
        await sync_to_async(Commitment.objects.create)(
            description="Lui envoyer le lien du concert", status="pending",
        )
        c = _make_consolidator()
        counts = await c.store_extractions(
            [{"type": "commitment", "store": True,
              "content": "Lui préparer une playlist pour dimanche", "person": ""}],
            interlocutors=[],
        )
        assert counts["commitments"] == 1


# ===================================================================
# MEM-06 — l'ancre de décroissance suit le renforcement
# ===================================================================


@pytest.mark.django_db(transaction=True)
class TestAncreDeRenforcement:

    async def test_renforcer_une_connaissance_repose_decayed_at(self):
        from memory.models import Connaissance

        await sync_to_async(Connaissance.objects.all().delete)()
        vieille = timezone.now() - timedelta(days=30)
        row = await sync_to_async(Connaissance.objects.create)(
            content="Thomas aime le café", confidence=0.6,
        )
        await sync_to_async(
            lambda: Connaissance.objects.filter(pk=row.pk).update(decayed_at=vieille)
        )()
        c = _make_consolidator()
        await sync_to_async(row.refresh_from_db)()
        c._find_similar_connaissance = AsyncMock(return_value=row)
        await c.store_extractions(
            [{"type": "connaissance", "store": True, "content": "Thomas aime le café",
              "themes": [], "entities": []}],
            interlocutors=[],
        )
        await sync_to_async(row.refresh_from_db)()
        assert row.confidence == pytest.approx(0.7)
        assert (timezone.now() - row.decayed_at).total_seconds() < 60


# ===================================================================
# MEM-07 — indexation comptée et rattrapée
# ===================================================================


class TestIndexationComptee:

    async def test_un_echec_d_index_est_compte_au_ledger(self):
        from memory.storage.consolidator import MemoryConsolidator
        from utils.degradation import degradations

        avant = degradations.total()

        def casse(**kw):
            raise RuntimeError("chroma down")

        await MemoryConsolidator._index(casse, "souvenir", 1, souvenir_id=1)
        # `vector_call` compte déjà de son côté : ce qui compte est que le
        # site d'indexation ait SA ligne au registre — avant, un warning seul.
        assert degradations.total() >= avant + 1
        assert any("indexation chromadb" in str(site) for site in degradations.snapshot())

    @pytest.mark.django_db(transaction=True)
    async def test_les_souvenirs_sans_vecteur_sont_repousses(self):
        from memory.models import Souvenir

        await sync_to_async(Souvenir.objects.all().delete)()
        a = await sync_to_async(Souvenir.objects.create)(
            content="indexé", importance=0.5, occurred_at=timezone.now(),
        )
        b = await sync_to_async(Souvenir.objects.create)(
            content="perdu", importance=0.5, occurred_at=timezone.now(),
        )
        c = _make_consolidator()
        c.vector_store.souvenir_ids_present = MagicMock(return_value=[a.pk])
        c.vector_store.add_souvenirs = MagicMock()
        c._last_reindex = 0.0
        await c._reindex_missing()
        c.vector_store.add_souvenirs.assert_called_once()
        entrees = c.vector_store.add_souvenirs.call_args[0][0]
        assert [e["souvenir_id"] for e in entrees] == [b.pk]
        assert entrees[0]["content"] == "perdu"

    def test_le_store_repond_quels_ids_il_tient(self):
        from memory.storage.vector_store import VectorStore

        store = VectorStore.__new__(VectorStore)
        store._souvenirs = MagicMock()
        store._souvenirs.get = MagicMock(return_value={"ids": ["3", "7"]})
        assert store.souvenir_ids_present([3, 5, 7]) == [3, 7]
        assert store.souvenir_ids_present([]) == []


# ===================================================================
# MEM-01 — la recherche délibérée retrouve un souvenir endormi
# ===================================================================


class TestRechercheDeliberee:

    async def test_l_outil_demande_sans_plancher_d_importance(self):
        from memory.module import MemoryToolsModule

        tool = next(t for t in MemoryToolsModule().return_tools() if t.name == "memory_search")
        with patch("memory.manager.memory_manager") as mm, \
             patch("memory.module._perimetre", new=AsyncMock(
                 return_value=MagicMock(interne=True, divulgation=True))):
            mm.search_related_souvenirs = AsyncMock(return_value=[])
            mm.search_related_connaissances = AsyncMock(return_value=[])
            await tool.handler({"query": "requin"})
        assert mm.search_related_souvenirs.await_args.kwargs["min_importance"] == 0.0

    async def test_le_manager_transmet_le_plancher_au_store(self):
        from memory.manager import MemoryManager

        m = MemoryManager.__new__(MemoryManager)
        m.vector_store = MagicMock()
        m.vector_store.search_souvenirs = MagicMock(return_value=[])
        await m.search_related_souvenirs("requin", n=3, min_importance=0.0)
        assert m.vector_store.search_souvenirs.call_args.kwargs == {"n": 3, "min_importance": 0.0}
        await m.search_related_souvenirs("requin", n=3)
        assert m.vector_store.search_souvenirs.call_args.kwargs == {"n": 3}


# ===================================================================
# MEM-09 — la porte de divulgation sur le rappel d'un acte
# ===================================================================


class TestDivulgationDuRappelSpontane:

    async def test_sans_destinataire_les_confidences_d_autrui_sont_retenues(self):
        from conscience.memory_bridge import MemoryBridge

        with patch("memory.manager.memory_manager") as mm:
            mm.get_memory_context_multi = AsyncMock(return_value="")
            await MemoryBridge().recall_for_context(["zelda"])
        assert mm.get_memory_context_multi.await_args.kwargs["disclose_others"] is False

    async def test_un_pas_de_chantier_garde_toute_sa_memoire(self):
        from conscience.memory_bridge import MemoryBridge

        with patch("memory.manager.memory_manager") as mm:
            mm.get_memory_context_multi = AsyncMock(return_value="")
            await MemoryBridge().recall_for_context(["zelda"], interne=True)
        assert mm.get_memory_context_multi.await_args.kwargs["disclose_others"] is True

    async def test_un_destinataire_identifie_suit_la_certitude_d_identite(self):
        from types import SimpleNamespace

        from conscience.memory_bridge import MemoryBridge

        with patch("memory.manager.memory_manager") as mm, \
             patch("identity.resolver.identity_resolver.resolve_context",
                   new=AsyncMock(return_value=SimpleNamespace(may_disclose=True))) as rc:
            mm.get_memory_context_multi = AsyncMock(return_value="")
            await MemoryBridge().recall_for_context(
                ["zelda"], person_id="tg_42", channel="telegram",
            )
        assert rc.await_args.kwargs["channel"] == "telegram"
        assert mm.get_memory_context_multi.await_args.kwargs["disclose_others"] is True

    async def test_une_panne_d_identite_ferme_la_porte(self):
        from conscience.memory_bridge import MemoryBridge

        with patch("memory.manager.memory_manager") as mm, \
             patch("identity.resolver.identity_resolver.resolve_context",
                   new=AsyncMock(side_effect=RuntimeError("db locked"))):
            mm.get_memory_context_multi = AsyncMock(return_value="")
            await MemoryBridge().recall_for_context(["zelda"], person_id="tg_42")
        assert mm.get_memory_context_multi.await_args.kwargs["disclose_others"] is False

    def test_l_acte_rappelle_apres_avoir_choisi_le_destinataire(self):
        """AST : dans `_act`, l'appel à `recall_for_context` suit l'appel à
        `_select_recipient` et lui passe `person_id`."""
        import ast
        import inspect

        from conscience import engine

        tree = ast.parse(inspect.getsource(engine))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "_act")
        lignes = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("_select_recipient", "recall_for_context"):
                    lignes[node.func.attr] = node.lineno
                    if node.func.attr == "recall_for_context":
                        assert any(k.arg == "person_id" for k in node.keywords)
        assert lignes["_select_recipient"] < lignes["recall_for_context"]


# ===================================================================
# MEM-11 — monologues, souvenir réflexif, importance d'un travail
# ===================================================================


@pytest.mark.django_db(transaction=True)
class TestPollutionParLesActes:

    async def test_un_monologue_sans_destinataire_n_est_pas_extrait(self):
        from memory.models import Message
        from memory.storage.window import user_facing_messages

        await sync_to_async(Message.objects.all().delete)()
        conv = await _conv()
        await _msg(conv, "tiens, un requin projecteur", role="assistant",
                   source="conscience", person_id="conscience_mika")
        adresse = await _msg(conv, "Alice, regarde ça", role="assistant",
                             source="conscience", person_id="tg_alice")
        ids = await sync_to_async(
            lambda: list(user_facing_messages(Message.objects.all()).values_list("pk", flat=True))
        )()
        assert ids == [adresse.pk]

    async def test_le_souvenir_reflexif_n_est_ecrit_qu_une_nuit(self):
        from conscience.models import Rumination
        from memory.models import Souvenir
        from memory.sleep import SleepCycle

        await sync_to_async(Rumination.objects.all().delete)()
        await sync_to_async(Souvenir.objects.all().delete)()
        r = await sync_to_async(Rumination.objects.create)(
            summary="je me suis emportée avec Alice", emotion="anxious",
            intensity=0.9, status="active",
        )
        await sync_to_async(
            lambda: Rumination.objects.filter(pk=r.pk).update(
                created_at=timezone.now() - timedelta(hours=4),
            )
        )()
        s = SleepCycle()
        await s._digest_ruminations()
        await s._digest_ruminations()  # « la nuit suivante »
        assert await sync_to_async(Souvenir.objects.count)() == 1
        await sync_to_async(r.refresh_from_db)()
        assert r.reflechie_le is not None and r.status == "active"

    async def test_l_importance_d_un_travail_suit_le_notable(self):
        from conscience.memory_bridge import MemoryBridge

        with patch("memory.manager.memory_manager") as mm:
            mm.create_souvenir = AsyncMock(return_value=None)
            await MemoryBridge().remember_completed_work("lire un article", "", notable=0.2)
            faible = mm.create_souvenir.await_args.kwargs["importance"]
            await MemoryBridge().remember_completed_work("lire un article", "", notable=1.0)
            fort = mm.create_souvenir.await_args.kwargs["importance"]
        assert faible == pytest.approx(0.33) and fort == pytest.approx(0.65)


# ===================================================================
# MEM-12 — sélection des fiches horaire
# ===================================================================


class TestSelectionDesFichesHoraire:

    async def test_deux_cycles_rapproches_ne_selectionnent_qu_une_fois(self):
        from memory.person_profile import PersonProfileGenerator

        g = PersonProfileGenerator()
        g._derniere_selection = 0.0
        with patch.object(PersonProfileGenerator, "select_due_entities",
                          new=AsyncMock(return_value=[])) as sel:
            await g.run_cycle()
            await g.run_cycle()
        assert sel.await_count == 1


# ===================================================================
# MEM-15 / MEM-16 / clés
# ===================================================================


class TestRetentionEtTypes:

    def test_les_trois_tables_ont_une_politique(self):
        from memory.retention import POLICIES

        noms = {(p.app_label, p.model_name) for p in POLICIES}
        assert {("memory", "Dream"), ("memory", "EmotionalSummary"),
                ("memory", "SelfNarrative")} <= noms

    def test_le_checkpoint_episodique_est_un_big_integer(self):
        from django.db import models

        from memory.models import EpisodicIndexLog

        champ = EpisodicIndexLog._meta.get_field("last_message_id")
        assert isinstance(champ, models.BigIntegerField)

    def test_l_index_sur_le_nom_en_minuscules_existe(self):
        from memory.models import Entity

        assert any(i.name == "memory_entity_name_lower" for i in Entity._meta.indexes)

    def test_les_cles_de_cadence_sont_declarees(self):
        from configs.types import ConfigItem
        from memory.config_schema import CONFIG_SCHEMA
        from memory.storage.consolidator import (
            EXTRACTION_MIN_MESSAGES, EXTRACTION_QUIET_S, MAX_CONTRADICTION_CHECKS,
        )

        def item(k):
            return next(i for i in CONFIG_SCHEMA if isinstance(i, ConfigItem) and i.key == k)

        assert item("memory.extraction_min_messages").default == EXTRACTION_MIN_MESSAGES == 6
        assert item("memory.extraction_quiet_seconds").default == EXTRACTION_QUIET_S == 300
        assert item("memory.max_contradiction_checks").default == MAX_CONTRADICTION_CHECKS == 1
        assert item("memory.profile_check_interval_s").default == 3600
