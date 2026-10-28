"""Ses petits mots pour dire bonjour : quand elle salue quelqu'un qui arrive, les mots qui ouvrent ses salutations
(d'après sa persona) — un fait sur elle, jamais une phrase à recopier, ni une manière de saluer. Qu'elle connaisse
ou non la personne se dit ailleurs, une fois (« CE QUI VOUS LIE », ``social``) : ce qu'elle en fait est à elle."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from mika.contracts import social as social_c
from mika.faculties.self.faculty import SELF, SelfState
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.vocab.episodes import Kind
from mika.vocab.phrasebook import phrase


@SELF.section("greeting_tone", zone=Zone.VOLATILE, episodes=[Kind.INITIATIVE], trim_rank=50,
              title=phrase("self.greeting.title"))
def _greeting_tone(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> str | None:
    """Quand elle salue quelqu'un qui arrive : ses petits mots, d'après sa persona — jamais une phrase entière :
    montrée « pour le ton seulement », un modèle la recopiait quand même, et en faisait tout son message (sonde
    finale du 2026-10-02 : « Yooo, te revoilà ! » cinq soirs sur six ; sonde du 2026-10-03 : « Heeey ~ alors,
    raconte-moi tout. » pour trois initiatives sur dix)."""
    ep = frame.episode
    if ep is None or social_c.GREETING not in (ep.attrs.get("reasons") or ()) or not s.persona.greetings:
        return None
    words = interjections(s.persona.greetings)
    return phrase("self.greeting.known", words=", ".join(words)) if words else None


#: le petit mot qui ouvre une salutation (« Heeey ~ », « Yooo »), jusqu'à la première ponctuation
_INTERJECTION = re.compile(r"^\s*([^\W\d_][\w'’]*(?:\s*~)?)")


def interjections(greetings: Sequence[str]) -> list[str]:
    """Les petits mots qui ouvrent ses salutations (« hey », « yooo », « heeey ~ »), sans doublon : de quoi donner
    son ton sans lui tendre une phrase à recopier."""
    out: list[str] = []
    for g in greetings:
        m = _INTERJECTION.match(g)
        word = m.group(1).strip().lower() if m else ""
        if word and word not in out:
            out.append(word)
    return out[:4]
