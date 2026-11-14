"""Ce que la consolidation lit de la réponse du modèle (``memory.extraction``) : une réponse invalide ou coupée ne
valide jamais une fenêtre, un élément invalide n'emporte pas les bons, rien n'est plafonné en douce, et les noms
se relient exactement, une mention inconnue restant propre à qui la fait."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from mika.faculties.memory.extraction import Extraction, People, Speaker, parse
from mika.ports.llm import LLMResponse, ToolCall


def test_names_are_exact_and_unknown_mentions_are_scoped():
    alice = People.of([Speaker("P1", "user_2", "Alice Dupont")], {})
    bob = People.of([Speaker("P1", "user_3", "Bob")], {})
    assert alice.one("Alice") == alice.one("Alice Dupont") == "user_2"
    assert alice.one("Alice Martin") != "user_2"
    assert alice.one("Alex") != bob.one("Alex")
    assert alice.one("Alex") == People.of([Speaker("P9", "user_2", "Alice Dupont")], {}).one("Alex")


@pytest.mark.parametrize("text", ['{"error":"context too long"}',
                                  '{"souvenirs":42}', '{}'])
def test_invalid_extraction_never_validates_a_window(text):
    assert parse(LLMResponse(text)) is None


def test_explicit_empty_tool_result_is_valid_but_truncated_result_is_not():
    response = LLMResponse("", tool_calls=(ToolCall("x", "record_memories", {}),), stop="tool_use")
    assert parse(response) == Extraction()
    assert parse(replace(response, stop="max_tokens")) is None


def test_valid_extraction_does_not_drop_promises_above_the_old_cap():
    raw = {"promesses": [{"texte": f"Promesse numéro {i}", "envers": "Alice"} for i in range(20)]}
    assert len(parse(LLMResponse(json.dumps(raw))).promesses) == 20


def test_invalid_item_keeps_good_evidence_and_reports_the_rejected_item():
    result = parse(LLMResponse(json.dumps({'croyances': [
        {'texte': 'Alice aime le jardinage'},
        {'texte': 'Alice est voisine de Bob', 'relations': [
            {'subject': 'Alice', 'other': 'Bob', 'kind': 'voisin'}]},
    ]})))
    assert [r.texte for r in result.croyances] == ['Alice aime le jardinage']
    assert result.issues and 'croyances[1]' in result.issues[0]
