"""Son portrait en prose (banc de recherche du 2026-10-15, ADR 0138) : le seul texte qui la décrit, lu partout —
en conversation comme dans son journal, son travail, ses rêves. Les listes qu'il remplaçait n'existent plus : le
modèle les jouait une à une, et chacune redisait un curseur du tempérament, le portrait ou la consigne de style."""

from __future__ import annotations

from pathlib import Path

from mika.contracts import self_ as self_c
from mika.faculties.self.character import temperament_in_words
from mika.faculties.self.persona import load, render
from mika.vocab import temperament as T
from mika.vocab.phrasebook import phrase

SHIPPED = Path(__file__).resolve().parents[2] / "persona" / "mika.yaml"
DOC = self_c.PersonaDoc(name="Mika", description="Une fille attentive.", portrait="Tu es Mika. Tu lis beaucoup.",
                        samples=("« salut » → « coucou »",), facts=("C'est une IA",), interests=("Le dessin",))


def test_her_portrait_opens_every_full_persona_and_her_description_the_compact_one():
    chat, other = render(DOC, "full", chat=True), render(DOC, "full")
    for text in (chat, other):
        assert text.startswith("Tu es Mika. Tu lis beaucoup.") and "Une fille attentive." not in text
        assert "C'est une IA" in text
    # sa voix en chat, en conversation seulement ; ses centres d'intérêt, hors conversation (le portrait les dit)
    assert "« salut » → « coucou »" in chat and "Le dessin" not in chat
    assert "« salut » → « coucou »" not in other and "Le dessin" in other
    assert phrase("self.temperament.title") not in chat  # en conversation, son tempérament se dit en mots
    tsundere = DOC.model_copy(update={"temperament": T.apply_profile(T.Temperament(), "tsundere")})
    assert temperament_in_words(tsundere.temperament) in render(tsundere, "full", chat=True)
    for is_chat in (True, False):
        compact = render(DOC, "compact", chat=is_chat)
        assert "Tu lis beaucoup." not in compact and compact.startswith("Tu es Mika. Une fille attentive.")


def test_without_a_portrait_her_description_opens():
    doc = self_c.PersonaDoc(name="Mika", description="Une fille attentive.")
    head = phrase("self.persona.head", name="Mika", description="Une fille attentive.").strip()
    assert render(doc, "full", chat=True).startswith(head) and render(doc, "full").startswith(head)


#: ce que le portrait ne dit plus : c'est un curseur (l'intérêt pour les autres, la persévérance, sa défense quand
#: on la touche) ou la consigne de style
SLIDER_WORDS = ("réfléchie", "intervieweuse", "finis jamais", "compliments", "comme on texte", "registre")


def test_her_shipped_persona_has_a_portrait_that_leaves_her_temperament_to_the_sliders():
    """Son portrait ne dit ni son tempérament (écrit ici, il l'emportait sur les curseurs) ni comment on écrit dans
    un chat (la consigne de style le dit) ; ses exemples demandent parfois ce que vit l'autre (ADR 0137), sans en
    faire une intervieweuse : au plus un tiers finissent par une question."""
    doc = load(SHIPPED)
    assert doc.portrait.strip() and not any(w in doc.portrait.lower() for w in SLIDER_WORDS)
    asking = [s for s in doc.samples if s.rstrip(" »").endswith("?")]
    assert asking and len(asking) <= len(doc.samples) // 3, asking
    assert doc.temperament.defense == "laugh" and "compliments" in doc.temperament.notes["defense"]
