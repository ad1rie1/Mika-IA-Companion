"""Le ton de ses bonjours : quand elle salue quelqu'un qui arrive, les petits mots qui ouvrent ses salutations
(d'après sa persona), jamais une phrase à recopier ; à une inconnue, un bonjour simple."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import social as social_c
from mika.faculties.self.faculty import SELF, SelfState
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable
from mika.vocab.phrasebook import phrase


@SELF.section("greeting_tone", zone=Zone.VOLATILE, episodes=[Kind.INITIATIVE], trim_rank=50,
              title=phrase("self.greeting.title"), reads=[identity_c.PERSON, social_c.CLOSENESS])
def _greeting_tone(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> str | None:
    """Quand elle salue quelqu'un qui arrive : le ton de ses bonjours, d'après sa
    persona — des exemples, jamais à recopier (elle les redirait chaque soir, mot
    pour mot, et ils parlent d'une humeur ou d'une heure qui ne sont pas les
    siennes ce jour-là). Ses bonjours d'amie supposent qu'on se connaît : à une
    inconnue, un bonjour simple (sonde réelle du 2026-10-03 : « Heeey ~ alors,
    raconte-moi tout » à quelqu'un qui arrivait pour la première fois)."""
    ep = frame.episode
    if ep is None or social_c.GREETING not in (ep.attrs.get("reasons") or ()) or not s.persona.greetings:
        return None
    person = frame.get(identity_c.PERSON(ep.target)) if ep.target else ""
    if not is_identifiable(person) or frame.get(social_c.CLOSENESS(person)) in ("", social_c.STRANGER):
        return phrase("self.greeting.first")  # un premier bonjour : simple, sans la familiarité d'une amie
    # jamais une phrase entière : montrée « pour le ton seulement », un modèle la recopiait quand même, et en faisait
    # tout son message (sonde finale du 2026-10-02 : « Yooo, te revoilà ! » cinq soirs sur six ; sonde du
    # 2026-10-03 : « Heeey ~ alors, raconte-moi tout. » pour trois initiatives sur dix) — ses petits mots, oui
    words = interjections(s.persona.greetings)
    if words:
        return phrase("self.greeting.known", words=", ".join(words))
    return phrase("self.greeting.known_plain")


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
