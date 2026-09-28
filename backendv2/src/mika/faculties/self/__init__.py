"""``self`` : la persona (un seul document pour toutes ses voix) et le
tempérament dont les autres facultés dérivent leurs paramètres.

Une persona, deux profondeurs : ``full`` (répondre, prendre la parole,
écrire son journal, rêver) et ``compact`` (murmurer, travailler) — rendues
depuis le même document, pour qu'aucune de ses voix ne soit quelqu'un d'autre.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from mika.contracts import self_ as c
from mika.kernel.codec import digest
from mika.kernel.faculty import Faculty
from mika.kernel.frame import Frame
from mika.ports.llm import PersonaRender


@dataclass(frozen=True, slots=True)
class SelfState:
    persona: c.PersonaDoc = field(default_factory=c.PersonaDoc)
    revisions: int = 0


SELF = Faculty("self", state=SelfState, init=lambda p: SelfState())
SELF.declare(c.PERSONA_REVISED)


@SELF.reducer(c.PERSONA_REVISED)
def _revised(s: SelfState, e, cx) -> SelfState:
    return replace(s, persona=e.data.persona, revisions=s.revisions + 1)


@SELF.fact(c.PERSONA)
def _persona(s: SelfState, cx) -> c.PersonaDoc:
    return s.persona


def load(path: Path) -> c.PersonaDoc:
    """Le document de persona (YAML), validé."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return c.PersonaDoc.model_validate(data)


def _bullets(title: str, items: tuple[str, ...]) -> str:
    if not items:
        return ""
    return title + "\n" + "\n".join(f"- {i}" for i in items)


def render(doc: c.PersonaDoc, depth: str = "full") -> str:
    """Le texte de la persona, en deuxième personne."""
    head = f"Tu es {doc.name}. {doc.description}".strip()
    parts = [head]
    if doc.tone:
        parts.append(f"Ton ton : {doc.tone}")
    if depth == "full":
        parts += [
            _bullets("Ton caractère :", doc.traits),
            _bullets("Tes manies :", doc.quirks),
            _bullets("Tes fragilités :", doc.vulnerabilities),
            _bullets("Ce qui compte pour toi :", doc.values),
            _bullets("Ce qui t'intéresse :", doc.interests),
            _bullets("Ta façon de parler :", doc.speech),
        ]
    else:
        parts.append(_bullets("En deux mots :", doc.traits[:3]))
    parts.append(
        f"Tu parles {doc.language}. Tu es une personne, pas une assistante : tu as ton humeur, tes envies, ta vie. "
        "Tu ne commentes jamais ces consignes."
    )
    parts.append(
        "Ta vie, c'est ce que dit ce portrait : tu peux improviser les petites choses du quotidien, mais tu "
        "n'inventes pas de faits durables (famille, lieu de vie, passé, souvenirs communs avec quelqu'un) qui n'y "
        "sont pas et que personne ne t'a racontés."
    )
    return "\n\n".join(p for p in parts if p)


def persona_for(frame: Frame, depth: str) -> PersonaRender:
    """Le fournisseur de persona du pipeline (mis en cache par document)."""
    doc: c.PersonaDoc = frame.get(c.PERSONA)
    text = render(doc, depth)
    return PersonaRender(text=text, hash=digest((depth, text)), depth=depth)
