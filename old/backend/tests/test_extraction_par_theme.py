"""Extraction par thème — le découpage d'une grosse fenêtre de consolidation.

Le regroupement thématique vivait dans la réorganisation nocturne, qui
extrayait au-dessus du checkpoint du consolidateur sans le faire avancer :
chaque nuit produisait les jumelles de ce que le tick suivant réextrayait.
Il vit maintenant dans ``MemoryConsolidator._extract_and_store`` (via
``memory/themes.py``), et ces tests pinent ce que le déplacement doit
garantir :

- une petite fenêtre (le tick de 60 s) reste linéaire et ne lit pas le
  vector store ;
- une grosse fenêtre part par thème, chronologique dans chaque thème ;
- ce que l'indexeur épisodique n'a pas encore découpé part dans une tranche
  résiduelle — chaque message atteint exactement un appel ;
- le checkpoint suit des tranches non contiguës sans rien réputer extrait.
"""

from __future__ import annotations

from collections import Counter
from unittest.mock import AsyncMock, MagicMock

import pytest

from old.backend.memory.themes import (
    ThemeTuning,
    cluster_greedy,
    plan_by_theme,
    split_on_message_boundaries,
)


def _chunk(cid, embedding, ts=0.0, content="Lui: x\nMika: y", handle="web_a",
           first=1, last=2):
    return {
        "id": cid,
        "content": content,
        "embedding": embedding,
        "metadata": {
            "ts": ts, "handle": handle, "conversation_id": 1,
            "first_message_id": first, "last_message_id": last,
        },
    }


def _msg(i, content, role="user"):
    return {
        "id": i, "role": role, "content": content, "created_at": None,
        "person_id": "web_a", "source": "frontend",
    }


REGLAGE = ThemeTuning(similarity=0.8, max_clusters=20, min_cluster_chars=0)


def _fenetre_deux_themes():
    """Six messages entrelacés : A aux ids impairs, B aux ids pairs.

    Chaque chunk couvre un message ; A et B ont des embeddings orthogonaux.
    30 caractères par message, pour qu'une tranche de 100 sépare les cas.
    """
    messages = [
        _msg(1, "A1" * 15), _msg(2, "B1" * 15),
        _msg(3, "A2" * 15), _msg(4, "B2" * 15),
        _msg(5, "A3" * 15), _msg(6, "B3" * 15),
    ]
    chunks = [
        _chunk("1", [1.0, 0.0], ts=1, first=1, last=1),
        _chunk("2", [0.0, 1.0], ts=2, first=2, last=2),
        _chunk("3", [0.99, 0.05], ts=3, first=3, last=3),
        _chunk("4", [0.05, 0.99], ts=4, first=4, last=4),
        _chunk("5", [1.0, 0.0], ts=5, first=5, last=5),
        _chunk("6", [0.0, 1.0], ts=6, first=6, last=6),
    ]
    return messages, chunks


def _contenus(tranches):
    return [[m["content"] for m in t] for t in tranches]


# ═══════════════════════════════════════════════════════════════════
# 1. Le clustering, pur (venu de memory/reorg.py)
# ═══════════════════════════════════════════════════════════════════

class TestClustering:

    def test_similar_chunks_join_the_same_cluster(self):
        clusters = cluster_greedy([
            _chunk("1", [1.0, 0.0, 0.0], ts=1),
            _chunk("2", [0.99, 0.05, 0.0], ts=2),
            _chunk("3", [0.0, 1.0, 0.0], ts=3),
        ], threshold=0.8)
        sizes = sorted(len(c) for c in clusters)
        assert sizes == [1, 2]

    def test_deterministic_by_ts_order(self):
        chunks = [
            _chunk("b", [0.0, 1.0], ts=2),
            _chunk("a", [1.0, 0.0], ts=1),
        ]
        clusters = cluster_greedy(chunks, threshold=0.8)
        # Premier cluster = premier chunk chronologique.
        assert clusters[0][0]["id"] == "a"

    def test_chunks_without_embedding_are_skipped(self):
        clusters = cluster_greedy([_chunk("1", None)], threshold=0.5)
        assert clusters == []

    def test_au_plafond_un_chunk_rejoint_le_plus_proche_meme_sous_le_seuil(self):
        clusters = cluster_greedy([
            _chunk("1", [1.0, 0.0], ts=1),
            _chunk("2", [0.0, 1.0], ts=2),
            _chunk("3", [0.7, 0.7], ts=3),
        ], threshold=0.99, max_clusters=2)
        assert len(clusters) == 2


class TestDecoupeLineaire:

    def test_backlog_is_split_on_message_boundaries(self):
        messages = [{"content": "x" * 3000} for _ in range(5)]
        batches = split_on_message_boundaries(messages, 8000)
        assert [len(b) for b in batches] == [2, 2, 1]

    def test_one_giant_message_travels_alone(self):
        batches = split_on_message_boundaries(
            [{"content": "a"}, {"content": "x" * 20000}, {"content": "b"}], 8000,
        )
        assert [len(b) for b in batches] == [1, 1, 1]


# ═══════════════════════════════════════════════════════════════════
# 2. Le plan, pur
# ═══════════════════════════════════════════════════════════════════

class TestPlanParTheme:

    def test_les_messages_sont_groupes_par_theme_et_chronologiques_dans_le_theme(self):
        messages, chunks = _fenetre_deux_themes()

        plan = plan_by_theme(messages, chunks, max_chars=100, tuning=REGLAGE)

        assert _contenus(plan.tranches) == [
            ["A1" * 15, "A2" * 15, "A3" * 15],
            ["B1" * 15, "B2" * 15, "B3" * 15],
        ]
        assert plan.themes == 2
        assert plan.residuel == 0

    def test_un_message_sans_chunk_part_dans_la_tranche_residuelle_en_dernier(self):
        messages, chunks = _fenetre_deux_themes()
        messages.append(_msg(7, "R1" * 15))

        plan = plan_by_theme(messages, chunks, max_chars=100, tuning=REGLAGE)

        assert _contenus(plan.tranches)[-1] == ["R1" * 15]
        assert plan.residuel == 1

    def test_chaque_message_de_la_fenetre_atteint_exactement_une_tranche(self):
        messages, chunks = _fenetre_deux_themes()
        messages.append(_msg(7, "R1" * 15))
        messages.append(_msg(8, "R2" * 15))

        plan = plan_by_theme(messages, chunks, max_chars=100, tuning=REGLAGE)

        vus = Counter(m["id"] for t in plan.tranches for m in t)
        assert vus == Counter(m["id"] for m in messages)

    def test_un_theme_trop_petit_rejoint_la_tranche_residuelle(self):
        messages, chunks = _fenetre_deux_themes()
        # Un troisième thème d'un seul message minuscule.
        messages.append(_msg(7, "ok"))
        chunks.append(_chunk("7", [0.7, -0.7], ts=7, first=7, last=7))

        plan = plan_by_theme(
            messages, chunks, max_chars=100,
            tuning=ThemeTuning(similarity=0.8, max_clusters=20, min_cluster_chars=10),
        )

        assert plan.themes == 2
        assert _contenus(plan.tranches)[-1] == ["ok"]
        assert plan.residuel == 1

    def test_un_gros_theme_est_decoupe_aux_frontieres_de_messages(self):
        messages, chunks = _fenetre_deux_themes()

        plan = plan_by_theme(messages, chunks, max_chars=60, tuning=REGLAGE)

        # 3 × 30 caractères par thème, tranche de 60 → deux tranches par
        # thème, l'ordre chronologique conservé et jamais un message coupé.
        assert _contenus(plan.tranches) == [
            ["A1" * 15, "A2" * 15], ["A3" * 15],
            ["B1" * 15, "B2" * 15], ["B3" * 15],
        ]
        assert plan.themes == 2

    def test_sans_chunk_le_plan_est_le_decoupage_lineaire(self):
        messages, _ = _fenetre_deux_themes()

        plan = plan_by_theme(messages, [], max_chars=100, tuning=REGLAGE)

        assert plan.tranches == split_on_message_boundaries(messages, 100)
        assert plan.themes == 0
        assert plan.residuel == len(messages)

    def test_un_chunk_qui_deborde_de_la_fenetre_n_y_apporte_que_ses_messages(self):
        """Un chunk peut commencer sous la fenêtre (déjà extrait) : il n'en
        ramène pas les messages, seulement ceux de la fenêtre."""
        messages = [_msg(10, "A1" * 15), _msg(11, "A2" * 15), _msg(12, "B1" * 15)]
        chunks = [
            _chunk("1", [1.0, 0.0], ts=1, first=3, last=11),
            _chunk("2", [0.0, 1.0], ts=2, first=12, last=40),
        ]

        plan = plan_by_theme(messages, chunks, max_chars=100, tuning=REGLAGE)

        assert _contenus(plan.tranches) == [["A1" * 15, "A2" * 15], ["B1" * 15]]
        assert Counter(m["id"] for t in plan.tranches for m in t) == Counter([10, 11, 12])

    def test_une_fenetre_vide_donne_un_plan_vide(self):
        plan = plan_by_theme([], [], max_chars=100, tuning=REGLAGE)
        assert plan.tranches == []


# ═══════════════════════════════════════════════════════════════════
# 3. Le consolidateur : quand il découpe, comment il borne
# ═══════════════════════════════════════════════════════════════════

def _reussite():
    return {"souvenirs": 0, "connaissances": 0, "commitments": 0,
            "tentees": 1, "echouees": 0}


def _echec_total():
    return {"souvenirs": 0, "connaissances": 0, "commitments": 0,
            "tentees": 1, "echouees": 1}


def _conso(chunks=None, *, dernier_id=0):
    """Un consolidateur dont le store rend ``chunks`` et dont l'extraction
    rend, par tranche, un souvenir portant le contenu du premier message —
    ce qui permet à ``store_extractions`` de savoir quelle tranche il sert."""
    from old.backend.memory.storage.consolidator import MemoryConsolidator

    c = MemoryConsolidator(MagicMock(), MagicMock())
    c._last_processed_id = dernier_id
    c.vector_store = MagicMock()
    c.vector_store.get_exchanges_for_messages = MagicMock(return_value=list(chunks or []))
    c.extractor = MagicMock()
    c.extractor.analyze_messages = AsyncMock(
        side_effect=lambda msgs, **kw: [
            {"type": "souvenir", "content": msgs[0]["content"]},
        ],
    )
    c.store_extractions = AsyncMock(side_effect=lambda *a, **k: _reussite())
    c._resolve_interlocutors = AsyncMock(return_value=[])
    return c


def _tranches_appelees(c):
    return [
        [m["content"] for m in appel.args[0]]
        for appel in c.extractor.analyze_messages.await_args_list
    ]


def _echoue_sur(prefixe):
    async def _store(extractions, **kw):
        if extractions[0]["content"].startswith(prefixe):
            return _echec_total()
        return _reussite()
    return _store


@pytest.mark.django_db
class TestConsolidateurParTheme:

    @pytest.fixture(autouse=True)
    def _grosse_fenetre(self, monkeypatch):
        """Une tranche de 100 caractères : six messages de 30 la dépassent."""
        import old.backend.memory.storage.consolidator as consolidator_mod
        monkeypatch.setattr(consolidator_mod, "EXTRACTION_MAX_CHARS", 100)
        # Réglage déterministe, indépendant de la base de config.
        monkeypatch.setattr(consolidator_mod, "theme_tuning", lambda: REGLAGE)
        yield

    async def test_une_petite_fenetre_reste_lineaire_sans_lecture_vectorielle(self, monkeypatch):
        import old.backend.memory.storage.consolidator as consolidator_mod
        # La valeur déclarée : rien n'écrase la tranche, le tick ordinaire.
        monkeypatch.setattr(
            consolidator_mod, "EXTRACTION_MAX_CHARS",
            consolidator_mod._EXTRACTION_MAX_CHARS_DEFAUT,
        )
        c = _conso()
        messages = [_msg(1, "salut"), _msg(2, "ça va ?", role="assistant"), _msg(3, "oui")]

        _counts, borne = await c._extract_and_store(messages)

        assert _tranches_appelees(c) == [["salut", "ça va ?", "oui"]]
        c.vector_store.get_exchanges_for_messages.assert_not_called()
        assert borne == 3

    async def test_une_grosse_fenetre_part_par_theme(self):
        messages, chunks = _fenetre_deux_themes()
        c = _conso(chunks)

        _counts, borne = await c._extract_and_store(messages)

        c.vector_store.get_exchanges_for_messages.assert_called_once()
        assert _tranches_appelees(c) == [
            ["A1" * 15, "A2" * 15, "A3" * 15],
            ["B1" * 15, "B2" * 15, "B3" * 15],
        ]
        assert borne == 6

    async def test_les_messages_sans_chunk_partent_dans_la_tranche_residuelle(self):
        messages, chunks = _fenetre_deux_themes()
        messages.append(_msg(7, "R1" * 15))
        c = _conso(chunks)

        _counts, borne = await c._extract_and_store(messages)

        appels = _tranches_appelees(c)
        assert len(appels) == 3
        assert appels[-1] == ["R1" * 15]
        assert Counter(x for t in appels for x in t) == Counter(m["content"] for m in messages)
        assert borne == 7

    async def test_les_interlocuteurs_sont_resolus_par_tranche(self):
        messages, chunks = _fenetre_deux_themes()
        c = _conso(chunks)

        await c._extract_and_store(messages)

        vus = [[m["content"] for m in appel.args[0]]
               for appel in c._resolve_interlocutors.await_args_list]
        assert vus == _tranches_appelees(c)

    async def test_un_echec_partiel_borne_le_checkpoint_au_premier_id_rate(self):
        """A (1, 3, 5) réussit, B (2, 4, 6) échoue : rien au-dessus de 1 n'est
        réputé extrait — le 2 ne l'a pas été. Le 3 et le 5 seront relus, ce
        que le dédoublonnage-renforcement absorbe."""
        messages, chunks = _fenetre_deux_themes()
        c = _conso(chunks)
        c.store_extractions = AsyncMock(side_effect=_echoue_sur("B"))

        _counts, borne = await c._extract_and_store(messages)

        assert borne == 1

    async def test_un_provider_mort_arrete_la_passe_et_compte_le_reste_en_echec(self):
        messages, chunks = _fenetre_deux_themes()
        messages.append(_msg(7, "R1" * 15))
        c = _conso(chunks)
        c.extractor.analyze_messages = AsyncMock(side_effect=[
            [{"type": "souvenir", "content": "A"}], None,
        ])

        _counts, borne = await c._extract_and_store(messages)

        # B a tué la passe ; le résiduel n'a pas été tenté, et compte comme
        # non extrait : la borne est sous B, pas sous le résiduel.
        assert c.extractor.analyze_messages.await_count == 2
        assert borne == 1

    async def test_le_checkpoint_ne_descend_jamais_sous_le_precedent(self):
        """Garde-fou : une fenêtre dont le plus petit id est sous le
        checkpoint courant ne peut pas le faire reculer."""
        messages, chunks = _fenetre_deux_themes()
        c = _conso(chunks, dernier_id=4)
        c.store_extractions = AsyncMock(side_effect=_echoue_sur("B"))

        _counts, borne = await c._extract_and_store(messages)

        assert borne == 4

    async def test_un_echec_de_toutes_les_tranches_gele_la_fenetre(self):
        messages, chunks = _fenetre_deux_themes()
        c = _conso(chunks)
        c.store_extractions = AsyncMock(side_effect=lambda *a, **k: _echec_total())

        _counts, borne = await c._extract_and_store(messages)

        assert borne is None

    async def test_un_provider_mort_des_la_premiere_tranche_gele_la_fenetre(self):
        messages, chunks = _fenetre_deux_themes()
        c = _conso(chunks)
        c.extractor.analyze_messages = AsyncMock(return_value=None)

        _counts, borne = await c._extract_and_store(messages)

        assert borne is None
        assert c.extractor.analyze_messages.await_count == 1

    async def test_un_store_en_panne_retombe_en_lineaire_et_compte(self):
        from old.backend.utils.degradation import degradations

        messages, _ = _fenetre_deux_themes()
        c = _conso()
        c.vector_store.get_exchanges_for_messages = MagicMock(
            side_effect=RuntimeError("chroma down"))
        degradations.reset()

        _counts, borne = await c._extract_and_store(messages)

        assert _tranches_appelees(c) == [
            [m["content"] for m in t]
            for t in split_on_message_boundaries(messages, 100)
        ]
        assert borne == 6
        assert degradations.count_for("consolidator: chunks de la fenetre") == 1
        degradations.reset()

    async def test_sans_vector_store_le_plan_est_lineaire(self):
        messages, _ = _fenetre_deux_themes()
        c = _conso()
        c.vector_store = None

        _counts, borne = await c._extract_and_store(messages)

        assert len(_tranches_appelees(c)) == len(split_on_message_boundaries(messages, 100))
        assert borne == 6


# ═══════════════════════════════════════════════════════════════════
# 4. La passe entière : un checkpoint qui n'avance pas ne s'écrit pas
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.django_db(transaction=True)
class TestPasseSansAvancee:

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        import old.backend.memory.storage.consolidator as consolidator_mod
        from old.backend.memory.models import ConsolidationLog, Conversation, Message, Souvenir
        Message.objects.all().delete()
        ConsolidationLog.objects.all().delete()
        Souvenir.objects.all().delete()
        Conversation.objects.all().delete()
        monkeypatch.setattr(consolidator_mod, "EXTRACTION_MAX_CHARS", 100)
        monkeypatch.setattr(consolidator_mod, "theme_tuning", lambda: REGLAGE)
        yield

    async def test_le_residuel_en_echec_au_ras_du_checkpoint_n_ecrit_rien(self):
        """Le premier message de la fenêtre n'a pas de chunk (indexeur en
        retard) et sa tranche résiduelle échoue : les thèmes ont abouti, mais
        la borne vaut le checkpoint courant. Pas de ligne, pas de recul."""
        from asgiref.sync import sync_to_async

        from old.backend.memory.models import ConsolidationLog, Conversation, Message
        from old.backend.memory.storage.consolidator import MemoryConsolidator

        conv = await Conversation.objects.acreate()
        pks = []
        for contenu in ["R1" * 15, "A1" * 15, "B1" * 15, "A2" * 15, "B2" * 15]:
            m = await Message.objects.acreate(
                conversation=conv, role="user", source="frontend",
                content=contenu, person_id="web_a",
            )
            pks.append(m.pk)
        r1, a1, b1, a2, b2 = pks
        chunks = [
            _chunk("a1", [1.0, 0.0], ts=1, first=a1, last=a1),
            _chunk("b1", [0.0, 1.0], ts=2, first=b1, last=b1),
            _chunk("a2", [1.0, 0.0], ts=3, first=a2, last=a2),
            _chunk("b2", [0.0, 1.0], ts=4, first=b2, last=b2),
        ]

        c = MemoryConsolidator.__new__(MemoryConsolidator)
        c._last_processed_id = r1 - 1
        c.vector_store = MagicMock()
        c.vector_store.get_exchanges_for_messages = MagicMock(return_value=chunks)
        c.extractor = MagicMock()
        c.extractor.analyze_messages = AsyncMock(
            side_effect=lambda msgs, **kw: [
                {"type": "souvenir", "content": msgs[0]["content"]},
            ],
        )
        c.store_extractions = AsyncMock(side_effect=_echoue_sur("R"))
        c._resolve_interlocutors = AsyncMock(return_value=[])
        c._run_maintenance = AsyncMock()

        await c._consolidate()

        assert c.extractor.analyze_messages.await_count == 3
        assert c._last_processed_id == r1 - 1
        assert await sync_to_async(ConsolidationLog.objects.count)() == 0
        c._run_maintenance.assert_awaited_once_with(regenerate=True)
