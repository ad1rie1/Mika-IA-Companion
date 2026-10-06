"""Le recueil de ses phrases (``mika.vocab.phrasebook``, ADR 0071) : lire, remplir, refuser en le disant."""

from __future__ import annotations

import pytest

from mika.vocab import phrasebook
from mika.vocab.phrasebook import VoiceError, family, phrase, phrases

VOICE = """\
self:
  nature:
    embodied: >-
      Tu es toi,
      avec ton histoire.
dream:
  system: "Tu rêves. Ton du rêve : {tone}."
expression:
  cues:
    - pfff
    - oooh
affect:
  mood:
    happy: contente
    angry: en colère
"""


@pytest.fixture
def voice(tmp_path, monkeypatch):
    path = tmp_path / "voix.yaml"
    path.write_text(VOICE, encoding="utf-8")
    monkeypatch.setenv(phrasebook.ENV, str(path))
    phrasebook.reset()
    yield path
    phrasebook.reset()


def test_a_phrase_a_list_a_family(voice):
    assert phrase("self.nature.embodied") == "Tu es toi, avec ton histoire."
    assert phrase("dream.system", tone="doux, lumineux") == "Tu rêves. Ton du rêve : doux, lumineux."
    assert phrases("expression.cues") == ("pfff", "oooh")
    assert dict(family("affect.mood")) == {"happy": "contente", "angry": "en colère"}


def test_holes_are_strict(voice):
    with pytest.raises(VoiceError, match="manquants : tone"):
        phrase("dream.system")
    with pytest.raises(VoiceError, match="en trop : name"):
        phrase("dream.system", tone="x", name="y")


def test_an_absent_key_says_which(voice):
    with pytest.raises(VoiceError, match="« self.nature.ai » n'existe pas"):
        phrase("self.nature.ai")
    with pytest.raises(VoiceError, match="est une liste"):
        phrase("expression.cues")


def test_a_broken_file_says_where(tmp_path, monkeypatch):
    path = tmp_path / "voix.yaml"
    path.write_text("self:\n  nature: [ouvert\n", encoding="utf-8")
    monkeypatch.setenv(phrasebook.ENV, str(path))
    phrasebook.reset()
    with pytest.raises(VoiceError, match="ligne"):
        phrasebook.catalog()
    path.write_text("Self:\n  x: y\n", encoding="utf-8")
    phrasebook.reset()
    with pytest.raises(VoiceError, match="minuscules"):
        phrasebook.catalog()
    path.write_text("self:\n  x: 3\n", encoding="utf-8")
    phrasebook.reset()
    with pytest.raises(VoiceError, match="ni une phrase"):
        phrasebook.catalog()
    phrasebook.reset()


def test_a_missing_file_names_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv(phrasebook.ENV, str(tmp_path / "absent.yaml"))
    phrasebook.reset()
    with pytest.raises(VoiceError, match="introuvable"):
        phrasebook.catalog()
    phrasebook.reset()
