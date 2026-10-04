"""The declarative prompt-layer table (`pipeline.prompt._LAYERS`).

`build_system_prompt` was thirteen keyword parameters and twelve copies of
``if x: system += "--- TITRE ---" + x + "--- FIN ---"``, called by a function
that transcribed a thirteen-field dataclass into thirteen identically-named
arguments. Adding a block meant four edits; the docstring that documented
the order had already drifted from the code.

Replacing that with a table trades four edit sites for one, and introduces
one new failure mode in exchange: a field name that does not exist would
read as "empty block" and vanish from every prompt silently. These tests
cover the trade — the ordering the table now encodes, and the guard that
makes a bad entry loud.
"""

from __future__ import annotations

import dataclasses

import pytest

from old.backend.pipeline.context import ConversationContext
from old.backend.pipeline.prompt import _LAYERS, build_system_prompt


def _positions(prompt: str, *markers: str) -> list[int]:
    found = []
    for m in markers:
        idx = prompt.find(m)
        assert idx != -1, f"bloc absent du prompt : {m}"
        found.append(idx)
    return found


# ---------------------------------------------------------------------------
# 1. The table is well-formed
# ---------------------------------------------------------------------------


class TestTableIntegrity:

    def test_every_layer_names_a_real_context_field(self):
        """The failure the table could introduce: a typo'd field silently
        drops its block from every prompt, forever, with no error."""
        known = {f.name for f in dataclasses.fields(ConversationContext)}
        for layer in _LAYERS:
            assert layer.field in known, (
                f"_LAYERS references '{layer.field}', which is not a "
                f"ConversationContext field"
            )

    def test_a_bogus_field_raises_rather_than_disappearing(self):
        """Strict getattr, no default — the guard is in the code, not only
        in the test above."""
        from old.backend.pipeline.prompt import _Layer

        bad = _Layer("does_not_exist", "--- X ---")
        with pytest.raises(AttributeError):
            getattr(ConversationContext(), bad.field)

    def test_no_field_is_layered_twice(self):
        fields = [layer.field for layer in _LAYERS]
        assert len(fields) == len(set(fields))

    def test_professional_mode_mutes_every_affective_layer(self):
        # Le pin change : le mode professionnel coupait 1 canal affectif sur 6
        # (l'état émotionnel) pendant que la fatigue, les ruminations, le rêve
        # et la lecture du ton de l'interlocuteur restaient dans le prompt, à
        # quelques lignes d'une directive « ton factuel et posé uniquement ».
        # Le rythme et le fil d'hier restent : ce sont des faits, pas de
        # l'affect.
        muted = [layer.field for layer in _LAYERS if layer.muted_by_project]
        assert muted == [
            "user_mood_hint",
            "fatigue_fog",
            "rumination_context",
            "travaux_context",
            "dream_context",
            "emotion_context",
        ]

    def test_only_memory_is_appended_raw(self):
        """The retriever formats its own block; everything else is wrapped."""
        raw = [layer.field for layer in _LAYERS if layer.header is None]
        assert raw == ["memory_context"]


# ---------------------------------------------------------------------------
# 2. Ordering — attention is positional, so this is behaviour
# ---------------------------------------------------------------------------


class TestLayerOrdering:
    """Slow layers (who she is, who she's talking to) lead; layers recomputed
    every turn come last, where recency biases recall."""

    @staticmethod
    def _full() -> str:
        """A context where every layered field carries a marker.

        Driven off ``_LAYERS`` rather than off the dataclass's declared
        types: ``field.type`` is a string or a class depending on whether
        the module uses postponed annotations, and a helper that silently
        selected nothing produced an empty prompt in which every ordering
        assertion below still "passed" its find().
        """
        return build_system_prompt(ConversationContext(**{
            layer.field: f"<{layer.field}>" for layer in _LAYERS
        }))

    def test_identity_precedes_what_she_knows_about_them(self):
        """"Here is Thomas's history" reads very differently after "someone
        *claims* to be Thomas"."""
        ident, person = _positions(
            self._full(),
            "--- QUI TU AS EN FACE ---",
            "--- CE QUE TU SAIS DE CETTE PERSONNE ---",
        )
        assert ident < person

    def test_self_concept_leads(self):
        prompt = self._full()
        first = prompt.find("--- QUI TU ES DEVENUE ---")
        others = [
            prompt.find(layer.header)
            for layer in _LAYERS
            if layer.header and layer.header != "--- QUI TU ES DEVENUE ---"
        ]
        assert all(first < o for o in others)

    def test_project_precedes_emotion(self):
        """An active project's tone directive must dominate the emotional
        expression, not the other way around."""
        project, emotion = _positions(
            self._full(),
            "--- PROJET EN COURS ---",
            "--- TON ETAT EMOTIONNEL ACTUEL ---",
        )
        assert project < emotion

    def test_memory_comes_last_before_the_focus_note(self):
        """La mémoire ferme le bloc d'état ; seule la pensée du tour (note
        de focus, passe de préparation) passe après elle — la récence est la
        position qui pèse le plus, et cette couche parle de CE tour."""
        prompt = self._full()
        assert prompt.rstrip().endswith("--- FIN ---")
        assert prompt.find("<memory_context>") < prompt.find("<note_de_focus>")
        after_memory = prompt[prompt.find("<memory_context>"):]
        assert "--- CE QUI TE VIENT A L'ESPRIT ---" in after_memory

    def test_table_order_is_the_prompt_order(self):
        """The table *is* the documentation — pinned so it stays true."""
        prompt = self._full()
        headers = [layer.header for layer in _LAYERS if layer.header]
        positions = [prompt.find(h) for h in headers]
        assert positions == sorted(positions), (
            "l'ordre des blocs rendus ne suit plus l'ordre de _LAYERS"
        )


# ---------------------------------------------------------------------------
# 3. Rendering rules
# ---------------------------------------------------------------------------


class TestRendering:

    def test_an_empty_layer_is_skipped_entirely(self):
        prompt = build_system_prompt(ConversationContext(journal_context=""))
        assert "TON FIL D'HIER" not in prompt

    def test_a_present_layer_is_wrapped_with_its_own_footer(self):
        """Footers are deliberately inconsistent across layers; the refactor
        reproduced them verbatim rather than tidying the model's input."""
        prompt = build_system_prompt(ConversationContext(module_context="3 mails"))
        assert "--- CONTEXTE MODULES ---\n3 mails\n--- FIN CONTEXTE MODULES ---" in prompt

    def test_default_footer(self):
        prompt = build_system_prompt(ConversationContext(journal_context="hier"))
        assert "--- TON FIL D'HIER ---\nhier\n--- FIN ---" in prompt

    def test_memory_is_appended_without_markup(self):
        prompt = build_system_prompt(ConversationContext(memory_context="MEM"))
        assert prompt.endswith("\n\nMEM")

    def test_professional_mode_drops_the_emotion_block(self):
        prompt = build_system_prompt(ConversationContext(
            emotion_context="tu te sens excited",
            project_context="Titre : rapport",
            project_suppresses_emotion=True,
        ))
        assert "TON ETAT EMOTIONNEL" not in prompt
        assert "PROJET EN COURS" in prompt

    def test_a_project_that_keeps_emotions_keeps_the_block(self):
        prompt = build_system_prompt(ConversationContext(
            emotion_context="tu te sens excited",
            project_context="Titre : rapport",
        ))
        assert "TON ETAT EMOTIONNEL" in prompt

    def test_an_empty_context_is_valid(self):
        """`ConversationContext()` says nothing, which is a thing a context
        is allowed to say — the prompt is then personality alone."""
        prompt = build_system_prompt(ConversationContext())
        assert prompt
        for layer in _LAYERS:
            if layer.header:
                assert layer.header not in prompt


class TestProfessionalModeCutsEveryAffectiveChannel:
    """`emotion_policy=OFF` coupait un canal sur six.

    Restaient la fatigue (« laisse-toi etre moins parfaite »), le rêve (« tu
    peux le mentionner »), les ruminations (« colorent subtilement ton
    humeur »), la lecture du ton de l'interlocuteur — et les marqueurs
    `[angry]` du rendu mémoire, à trois lignes d'une directive « ton factuel
    et posé uniquement », dans la zone de récence qui pèse le plus.
    """

    @staticmethod
    def _pro(**kwargs) -> str:
        return build_system_prompt(ConversationContext(
            project_context="Titre : audit",
            project_suppresses_emotion=True,
            **kwargs,
        ))

    def test_every_affective_header_is_gone(self):
        prompt = self._pro(
            user_mood_hint="il a l'air a cran",
            fatigue_fog="tu es clairement fatiguee",
            rumination_context="tu repenses a la reunion",
            dream_context="tu as reve d'un train",
            emotion_context="tu te sens excited",
            circadian_context="il est 14h",
            journal_context="hier tu as avance sur le rapport",
        )
        for header in (
            "--- CE QUE TU PERCOIS DE SON ETAT ---",
            "--- ETAT COGNITIF ---",
            "--- CE QUI TE TROTTE DANS LA TETE ---",
            "--- CE QUE TU AS REVE CETTE NUIT ---",
            "--- TON ETAT EMOTIONNEL ACTUEL ---",
        ):
            assert header not in prompt
        # Le rythme et le fil d'hier sont des faits, pas de l'affect.
        assert "--- TON RYTHME ---" in prompt
        assert "--- TON FIL D'HIER ---" in prompt

    def test_memory_emotion_tags_are_stripped(self):
        prompt = self._pro(memory_context=(
            "  - (hier) [angry] il a crie\n"
            "  - (hier) [excited] on a fete ca"
        ))
        assert "[angry]" not in prompt
        assert "[excited]" not in prompt
        assert "il a crie" in prompt
        assert "on a fete ca" in prompt

    def test_memory_emotion_tags_survive_outside_professional_mode(self):
        prompt = build_system_prompt(ConversationContext(
            memory_context="  - (hier) [angry] il a crie",
        ))
        assert "[angry]" in prompt

    def test_confidence_labels_are_not_mistaken_for_emotions(self):
        prompt = self._pro(memory_context="  - un fait [certain]")
        assert "[certain]" in prompt

    def test_section_headers_are_not_stripped(self):
        prompt = self._pro(memory_context=(
            "[Quelque chose te revient]\n  - (hier) [sad] x"
        ))
        assert "[Quelque chose te revient]" in prompt
        assert "[sad]" not in prompt


# ---------------------------------------------------------------------------
# 4. La table produit aussi la décomposition du volatil
# ---------------------------------------------------------------------------


class TestBlocsVolatilesEmis:
    """`_assemble` rend le volatil ET ses blocs.

    La borne globale du tour (`ai.budget.fit_turn`) doit pouvoir vider une
    couche *nommée* sans laisser un « --- CE QUE TU SAIS DE CETTE PERSONNE
    --- » sans sa fin. Elle recevait `volatile_blocks=[]` : elle ne pouvait
    couper que le résumé et se contentait de constater le dépassement.
    Reconstruire les blocs ailleurs aurait fait deux tables d'ordre à tenir
    d'accord — c'est ce que `_LAYERS` existe pour éviter.
    """

    @staticmethod
    def _plein() -> ConversationContext:
        return ConversationContext(**{
            layer.field: f"<{layer.field}>" for layer in _LAYERS
        })

    def test_les_couches_volatiles_sortent_en_blocs_dans_l_ordre_de_la_table(self):
        from old.backend.pipeline.prompt import _STABLE_LAYER_COUNT, _assemble

        _, blocks = _assemble(self._plein())
        assert [b.field for b in blocks] == [
            layer.field for layer in _LAYERS[_STABLE_LAYER_COUNT:]
        ]

    def test_les_couches_stables_restent_dans_le_prefixe(self):
        """Personnalité + self-concept + identité : la zone cacheable, et
        exactement ce qu'une troncature par la tête détruit."""
        from old.backend.pipeline.prompt import _STABLE_LAYER_COUNT, _assemble

        stable, blocks = _assemble(self._plein())
        for layer in _LAYERS[:_STABLE_LAYER_COUNT]:
            assert layer.header in stable
            assert layer.field not in {b.field for b in blocks}

    def test_un_bloc_porte_son_entete_et_son_pied(self):
        from old.backend.pipeline.prompt import _assemble

        _, blocks = _assemble(ConversationContext(module_context="3 mails"))
        assert len(blocks) == 1
        assert blocks[0].render() == (
            "--- CONTEXTE MODULES ---\n3 mails\n--- FIN CONTEXTE MODULES ---"
        )

    def test_le_rendu_des_blocs_est_le_volatil_de_build_prompt_parts(self):
        """L'émission des blocs est une sortie SUPPLÉMENTAIRE, pas une
        réécriture du rendu : le prompt système ne bouge pas d'un octet."""
        from old.backend.pipeline.prompt import _assemble, _render_volatile, build_prompt_parts

        context = self._plein()
        stable, volatile = build_prompt_parts(context)
        stable_bis, blocks = _assemble(context)
        assert stable_bis == stable
        assert _render_volatile(blocks) == volatile
        assert build_system_prompt(context) == f"{stable}\n\n{volatile}"

    def test_une_couche_muette_ne_produit_pas_de_bloc(self):
        """Sinon la couche supprimée reviendrait par la recomposition d'après
        coupe, en mode professionnel précisément."""
        from old.backend.pipeline.prompt import _assemble

        _, blocks = _assemble(ConversationContext(
            emotion_context="tu te sens excited",
            project_context="Titre : audit",
            project_suppresses_emotion=True,
        ))
        assert "emotion_context" not in {b.field for b in blocks}
        assert "project_context" in {b.field for b in blocks}

    def test_le_bloc_memoire_porte_la_valeur_deja_nettoyee(self):
        """La coupe re-rend `block.value` : si le bloc gardait les marqueurs
        `[angry]`, ils reviendraient dans un tour tronqué."""
        from old.backend.pipeline.prompt import _assemble

        _, blocks = _assemble(ConversationContext(
            memory_context="  - (hier) [angry] il a crie",
            project_context="Titre : audit",
            project_suppresses_emotion=True,
        ))
        memoire = {b.field: b.value for b in blocks}["memory_context"]
        assert "[angry]" not in memoire
        assert "il a crie" in memoire

    def test_un_bloc_vide_disparait_avec_son_entete(self):
        """C'est ce que fait la borne d'un cran à plancher 0 : le rendu ne
        doit pas laisser une balise ouverte sur rien."""
        from old.backend.ai.chat import VolatileBlock
        from old.backend.pipeline.prompt import _render_volatile

        blocks = [
            VolatileBlock("module_context", "", "--- CONTEXTE MODULES ---"),
            VolatileBlock("memory_context", "MEM"),
        ]
        assert _render_volatile(blocks) == "MEM"


# ---------------------------------------------------------------------------
# 5. The caller no longer transcribes the context field by field
# ---------------------------------------------------------------------------


def test_response_passes_the_context_object():
    import inspect

    from old.backend.pipeline import response

    src = inspect.getsource(response.call_ai_and_parse)
    assert "build_chat_prompt(context" in src
    assert "emotion_context=context.emotion_context" not in src
