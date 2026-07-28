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

from pipeline.context import ConversationContext
from pipeline.prompt import _LAYERS, build_system_prompt


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
        from pipeline.prompt import _Layer

        bad = _Layer("does_not_exist", "--- X ---")
        with pytest.raises(AttributeError):
            getattr(ConversationContext(), bad.field)

    def test_no_field_is_layered_twice(self):
        fields = [layer.field for layer in _LAYERS]
        assert len(fields) == len(set(fields))

    def test_only_the_emotion_layer_is_project_muted(self):
        muted = [layer.field for layer in _LAYERS if layer.muted_by_project]
        assert muted == ["emotion_context"]

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

    def test_memory_comes_last(self):
        prompt = self._full()
        assert prompt.rstrip().endswith("<memory_context>")

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


# ---------------------------------------------------------------------------
# 4. The caller no longer transcribes the context field by field
# ---------------------------------------------------------------------------


def test_response_passes_the_context_object():
    import inspect

    from pipeline import response

    src = inspect.getsource(response.call_ai_and_parse)
    assert "build_system_prompt(context)" in src
    assert "emotion_context=context.emotion_context" not in src
