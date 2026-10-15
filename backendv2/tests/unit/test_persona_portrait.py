"""Son portrait en prose (banc de recherche, 2026-10-15) : en conversation, il remplace la description, le ton et les
listes, que le modèle jouait une à une ; ailleurs (son journal, son travail), les listes restent."""

from __future__ import annotations

from pathlib import Path

from mika.contracts import self_ as self_c
from mika.faculties.self.character import temperament_in_words
from mika.faculties.self.persona import load, render
from mika.vocab import temperament as T
from mika.vocab.phrasebook import phrase

SHIPPED = Path(__file__).resolve().parents[2] / "persona" / "mika.yaml"


def test_in_conversation_her_portrait_replaces_the_lists_and_elsewhere_the_lists_stay():
    doc = self_c.PersonaDoc(name="Mika", description="Une fille attentive.", traits=("À l'écoute",),
                            portrait="Tu es Mika. Tu lis beaucoup.", samples=("« salut » → « coucou »",),
                            facts=("C'est une IA",))
    chat = render(doc, "full", chat=True)
    assert chat.startswith("Tu es Mika. Tu lis beaucoup.")
    assert "À l'écoute" not in chat and "Une fille attentive." not in chat
    assert "« salut » → « coucou »" in chat and "C'est une IA" in chat
    assert phrase("self.temperament.title") not in chat  # en conversation, son tempérament se dit en mots
    tsundere = doc.model_copy(update={"temperament": T.apply_profile(T.Temperament(), "tsundere")})
    assert temperament_in_words(tsundere.temperament) in render(tsundere, "full", chat=True)
    for depth, is_chat in (("full", False), ("compact", True), ("compact", False)):
        other = render(doc, depth, chat=is_chat)
        assert "Tu lis beaucoup." not in other and "Une fille attentive." in other


def test_without_a_portrait_nothing_changes():
    doc = self_c.PersonaDoc(name="Mika", description="Une fille attentive.", traits=("À l'écoute",))
    assert render(doc, "full", chat=True).startswith(phrase("self.persona.head", name="Mika",
                                                             description="Une fille attentive.").strip())
    assert "À l'écoute" in render(doc, "full", chat=True)


def test_her_shipped_persona_has_a_portrait_and_samples_that_rarely_ask():
    """Son portrait ne dit pas son tempérament (c'est son profil qui le dit : écrit ici, il l'emportait sur les
    curseurs), et ses exemples ne finissent presque jamais par une question."""
    doc = load(SHIPPED)
    assert doc.portrait.strip() and "réfléchie" not in doc.portrait
    asking = [s for s in doc.samples if s.rstrip(" »").endswith("?")]
    assert len(asking) <= len(doc.samples) // 4, asking
