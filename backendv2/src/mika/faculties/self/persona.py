"""La persona : un seul document pour toutes ses voix, écrit par l'opératrice. Deux profondeurs : ``full``
(répondre, prendre la parole, se raconter) et ``compact`` (murmurer, travailler) — rendues depuis le même document,
pour qu'aucune de ses voix ne soit quelqu'un d'autre. Elle est une IA et le sait, ou une personne incarnée (``nature``)
; ses bonjours donnent un ton, jamais une phrase à recopier. Son tempérament, trait par trait avec sa mesure (ADR
0100), est dans les deux profondeurs hors conversation — murmurer, travailler, un réveil, un brouillon, son journal,
ses rêves, son récit. En conversation (répondre, prendre la parole), il règle sa physique émotionnelle par les
facultés, mais ne se dit pas au modèle : dit trait par trait, elle jouait ses traits au lieu de parler."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml

from mika.contracts import self_ as c
from mika.faculties.self.character import temperament_in_words, temperament_text
from mika.faculties.self.faculty import SELF, SelfState
from mika.kernel.codec import digest
from mika.kernel.frame import Frame
from mika.ports.llm import PersonaRender
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.phrasebook import phrase


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


def nature_of(doc: c.PersonaDoc) -> str:
    """Ce qu'on lui dit de sa nature : une IA qui le sait (``self.nature.ai``), ou elle-même, incarnée
    (``self.nature.embodied`` : rien n'y parle d'IA, de personnage ni de rôle — ADR 0070)."""
    return phrase("self.nature.embodied") if doc.nature == c.EMBODIED else phrase("self.nature.ai")


def life_rule(doc: c.PersonaDoc) -> str:
    """La règle de sa vie : avec une vie rédigée, ce qu'elle raconte de son quotidien reste compatible avec elle et
    ses goûts ne bougent pas (``self.life.lived``) ; sans, la règle d'alors (``self.life.sketched``)."""
    return phrase("self.life.lived") if doc.life or doc.tastes or doc.facts else phrase("self.life.sketched")


def render(doc: c.PersonaDoc, depth: str = "full", *, chat: bool = False) -> str:
    """Le texte de la persona, en deuxième personne. Sa vie (ce qu'elle fait à sa
    façon, ses goûts, ce qui est vrai d'elle) en profondeur ``full`` : c'est là
    qu'on lui demande « t'as mangé quoi ? », « c'est quoi ton plat préféré ? ».
    ``chat`` : elle parle à quelqu'un — ses exemples en conversation montrent sa
    voix (décrite, elle sonnait comme un assistant : 2026-10-14) ; jamais dans un
    mail, un travail ou son journal, qui ne s'écrivent pas comme un chat. En
    conversation, son tempérament ne se dit pas : trait par trait, il lui faisait
    jouer chaque trait au lieu de parler (banc de recherche, 2026-10-15 : sans le
    bloc, 7,0/10 d'humanité ; avec, 5,2 ; avec les seuls traits marqués, 5,7)."""
    head = phrase("self.persona.head", name=c.name_of(doc), description=doc.description).strip()
    parts = [head]
    if doc.tone:
        parts.append(phrase("self.persona.tone", tone=doc.tone))
    if depth == "full":
        parts += [
            _bullets(phrase("self.persona.traits"), doc.traits),
            _bullets(phrase("self.persona.quirks"), doc.quirks),
            _bullets(phrase("self.persona.vulnerabilities"), doc.vulnerabilities),
            _bullets(phrase("self.persona.values"), doc.values),
            _bullets(phrase("self.persona.interests"), doc.interests),
            _bullets(phrase("self.persona.speech"), doc.speech),
            _bullets(phrase("self.persona.samples"), doc.samples) if chat else "",
            _bullets(phrase("self.persona.life"), doc.life),
            _bullets(phrase("self.persona.tastes"), doc.tastes),
            _bullets(phrase("self.persona.facts"), doc.facts),
        ]
    else:
        parts.append(_bullets(phrase("self.persona.in_short"), doc.traits[:3]))
    # hors conversation (son journal, ses rêves, son récit, son travail), le bloc ; en conversation, ses traits marqués
    # en mots (banc de recherche, 2026-10-15)
    parts.append(temperament_in_words(doc.temperament) if chat else temperament_text(doc.temperament))
    parts.append(phrase("self.persona.language", language=doc.language, nature=nature_of(doc)))
    parts.append(life_rule(doc))
    return "\n\n".join(p for p in parts if p)


def persona_for(frame: Frame, depth: str) -> PersonaRender:
    """Le fournisseur de persona du pipeline (mis en cache par document)."""
    doc: c.PersonaDoc = frame.get(c.PERSONA)
    ep = frame.episode
    text = render(doc, depth, chat=ep is not None and ep.kind in CONVERSATIONAL)
    return PersonaRender(text=text, hash=digest((depth, text)), depth=depth, name=c.name_of(doc))
