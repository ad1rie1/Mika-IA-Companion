"""Sa persona, par ses intentions.

- elle est une IA et le sait : demandé sincèrement, elle ne le cache pas et
  ne se prétend pas humaine — sans en faire un sujet ni une excuse ;
- ses manies sont des manies, pas une signature : de temps en temps, jamais
  deux fois dans la même conversation ; rien n'est « toujours » ;
- un fuseau inconnu est refusé à l'entrée (accepté, il mettait en panne la
  console et la conversation) ; un journal écrit avant cette règle se rejoue.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mika.contracts import self_ as self_c
from mika.faculties.self import render
from mika.kernel.codec import canonical_json
from tests.fixtures.mika import DOC
from tests.fixtures.mika import PERSONA_PATH as PATH


def test_she_knows_she_is_an_ai_and_does_not_make_it_a_topic():
    for depth in ("full", "compact"):
        text = render(DOC, depth)
        assert "Tu es une IA" in text and "tu ne prétends pas être humaine" in text
        assert "jamais « en tant qu'IA »" in text and "jamais d'avertissement" in text
        assert "Tu es une personne" not in text  # contrôle : l'ancienne phrase lui faisait nier sa nature


def test_her_quirks_are_occasional_and_nothing_is_always():
    text = render(DOC, "full")
    assert "Tes manies — de temps en temps, jamais deux fois dans la même conversation :" in text
    raw = PATH.read_text(encoding="utf-8").split("\n# Huit curseurs")[0]
    document = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("#"))
    assert "toujours" not in document.lower()  # une tendance, jamais une obligation
    assert "digression" in DOC.tone and "le reste du temps" in DOC.tone  # elle digresse quand ça l'emballe


@pytest.mark.parametrize("zone", ["Pas/UnFuseau", "", "../etc/passwd", "Europe/", "europe/paris"])
def test_an_unknown_timezone_is_refused(zone):
    with pytest.raises(ValidationError, match="fuseau horaire inconnu"):
        self_c.PersonaDoc(timezone=zone)


def test_a_known_timezone_is_kept_trimmed():
    assert self_c.PersonaDoc(timezone=" America/Montreal ").timezone == "America/Montreal"


def test_a_persona_journaled_before_the_rule_still_replays():
    """Un journal d'avant la validation peut porter un fuseau illisible : le
    rejeu ne casse pas, il retombe sur le fuseau par défaut — et un fuseau
    valide est gardé tel quel."""
    old = {"persona": {**DOC.model_dump(mode="json"), "timezone": "Pas/UnFuseau"}}
    raw = self_c.PERSONA_REVISED.upcast(1, old)
    assert self_c.PersonaRevised.model_validate(raw).persona.timezone == self_c.DEFAULT_ZONE
    kept = self_c.PERSONA_REVISED.upcast(1, {"persona": {**DOC.model_dump(mode="json"),
                                                         "timezone": "Asia/Tokyo"}})
    assert self_c.PersonaRevised.model_validate(kept).persona.timezone == "Asia/Tokyo"
    assert canonical_json(self_c.PersonaRevised.model_validate(kept).persona.temperament) == \
        canonical_json(DOC.temperament)
