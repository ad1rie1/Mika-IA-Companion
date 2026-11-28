"""La persona : un seul document pour toutes ses voix, écrit par l'opératrice. Deux profondeurs : ``full``
(répondre, prendre la parole, se raconter : son portrait en prose) et ``compact`` (murmurer, travailler, écrire pour
elle hors d'une conversation : sa description) — rendues depuis le même document, avec ce qui est vrai d'elle, son
caractère, sa nature et la règle de sa vie dans les deux, pour qu'aucune de ses voix ne soit quelqu'un d'autre
(ADR 0152). Qui elle est s'écrit une fois, dans le portrait (ADR 0138) ; ce qu'elle ressent, c'est son tempérament
qui le dit — par le texte que le modèle en a écrit (``self.character``, ADR 0139). Elle est une IA et le sait, ou une
personne incarnée (``nature``). En mode pro (ADR 0116, la profondeur ``pro``), qui elle est et rien de sa voix de chat
ni de son caractère. Un appel qui écrit pour elle hors du pipeline des épisodes lit le même texte par le fait
``self.portrayed``."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml

from mika.contracts import self_ as c
from mika.faculties.self.character import current
from mika.faculties.self.faculty import SELF, SelfState
from mika.kernel.codec import digest
from mika.kernel.frame import Frame
from mika.ports.llm import PersonaRender
from mika.vocab.episodes import CONVERSATIONAL, PRO
from mika.vocab.phrasebook import phrase


@SELF.reducer(c.PERSONA_REVISED)
def _revised(s: SelfState, e, cx) -> SelfState:
    return replace(s, persona=e.data.persona, revisions=s.revisions + 1)


@SELF.fact(c.PERSONA)
def _persona(s: SelfState, cx) -> c.PersonaDoc:
    return s.persona


@SELF.fact(c.PORTRAYED)
def _portrayed(s: SelfState, cx, depth: str) -> str:
    return render(s.persona, depth, character=current(s))


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
    """La règle de sa vie : avec un portrait ou des faits rédigés, ce qu'elle raconte de son quotidien reste
    compatible avec eux et ses goûts ne bougent pas (``self.life.lived``) ; sans, la règle d'alors
    (``self.life.sketched``)."""
    return phrase("self.life.lived") if doc.portrait.strip() or doc.facts else phrase("self.life.sketched")


def render(doc: c.PersonaDoc, depth: str = "full", *, chat: bool = False, character: str = "") -> str:
    """Le texte de la persona, en deuxième personne. En profondeur ``full``, son portrait en prose — le seul texte
    qui la décrit (ADR 0138 ; écrites en listes, ses qualités se jouaient une à une : banc de recherche du
    2026-10-15) — puis, quand elle parle à quelqu'un (``chat``), ses exemples en conversation (décrite, sa voix
    sonnait comme un assistant : 2026-10-14), ailleurs ses centres d'intérêt. En ``compact``, sa description. Dans
    les deux, ce qui est vrai d'elle, son caractère (``character``, le texte que le modèle en a écrit, ADR 0139 :
    rien ne le remplace tant qu'il n'est pas écrit), sa langue, sa nature et la règle de sa vie. ``pro`` : le mode
    pro (``_pro``), sans caractère."""
    if depth == PRO:
        return _pro(doc)
    portrait = doc.portrait.strip()
    head = phrase("self.persona.head", name=c.name_of(doc), description=doc.description).strip()
    parts = [portrait if portrait and depth == "full" else head]
    if depth == "full":
        parts.append(_bullets(phrase("self.persona.samples"), doc.samples) if chat
                     else _bullets(phrase("self.persona.interests"), doc.interests))
    parts.append(_bullets(phrase("self.persona.facts"), doc.facts))
    parts.append(phrase("self.character.frame", text=character.strip()) if character.strip() else "")
    parts.append(phrase("self.persona.language", language=doc.language, nature=nature_of(doc)))
    parts.append(life_rule(doc))
    return "\n\n".join(p for p in parts if p)


def _pro(doc: c.PersonaDoc) -> str:
    """En mode pro (ADR 0116) : qui elle est (son nom, sa description), ce qui est vrai d'elle, sa langue et sa
    nature — ni son portrait, ni sa voix de chat (ton, façon de parler, exemples), ni son tempérament. Un travail
    demandé dans le chat ne se joue pas en personnage : la consigne du mode dit comment le rendre."""
    parts = [phrase("self.persona.head", name=c.name_of(doc), description=doc.description).strip(),
             _bullets(phrase("self.persona.facts"), doc.facts),
             phrase("self.persona.language", language=doc.language, nature=nature_of(doc))]
    return "\n\n".join(p for p in parts if p)


def persona_for(frame: Frame, depth: str) -> PersonaRender:
    """Le fournisseur de persona du pipeline (mis en cache par document)."""
    doc: c.PersonaDoc = frame.get(c.PERSONA)
    ep = frame.episode
    text = render(doc, depth, chat=ep is not None and ep.kind in CONVERSATIONAL, character=frame.get(c.CHARACTER))
    return PersonaRender(text=text, hash=digest((depth, text)), depth=depth, name=c.name_of(doc),
                         reference=doc.reference_thread.strip())
