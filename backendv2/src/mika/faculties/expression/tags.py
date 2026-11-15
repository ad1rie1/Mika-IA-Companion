"""Ses balises, ce qu'elle écrit en fin de réponse et qui ne part pas : la balise à facettes
``[EMOTION: sad 0.6, love 0.3]`` (ADR 0093 ; l'ancienne forme ``[EMOTION:sad:0.6]`` est encore lue), sa lecture de la
personne ``[EN_FACE: …]`` et sa marque de mensonge ``[MENSONGE: …]`` (ADR 0108). ``parse`` les retire du texte et les
garde en annotations de l'énoncé, avec le fait qu'elle ait posé une question ; ``reannotate`` recalcule ce qui décrit
la forme sur le message récrit par l'autrice ; ``_plain`` : sa parole sans balise ni jeton de voix."""

from __future__ import annotations

import re
from collections.abc import Mapping

from mika.contracts import expression as c
from mika.vocab import reading
from mika.vocab.tag import parse_tag, strip_prosody
from mika.vocab.words import stems

#: sa marque d'un mensonge, où qu'elle l'écrive, fermée ou non (une marque coupée en fin de réponse ne doit pas
#: partir : ce qu'elle y écrit peut dire ce qu'elle cache)
LIE_MARK = re.compile(r"\[\s*(?:MENSONGE|MENTI|LIE)\b\s*:?([^\]]*)(?:\]|$)", re.IGNORECASE)
_SENTENCE = re.compile(r"[^.!?…]+[.!?…]*")
#: une ligne qui ouvre ses balises de fin (« [EMOTION: … », « [EN_FACE: … », « [EN FACE : … », « [MENSONGE: … ») —
#: la graphie d'EN_FACE est celle que ``reading.TAG`` lit (tiret bas, espace, tiret ou rien)
_TRAILER = re.compile(r"^[ \t]*\[\s*(?:EMOTION|EN[\s_\-]?FACE|MENSONGE|MENTI|LIE)\b", re.IGNORECASE | re.MULTILINE)
_BRACKETS = re.compile(r"\[[^\]\n]*\]?")
#: une phrase : des mots jusqu'à une ponctuation forte — ce qui, après une ligne de balise, est encore sa parole
_SPOKEN = re.compile(r"\w[^.!?…\n]*[.!?…]")


def closing(text: str) -> str:
    """Ce qu'elle dit, puis ses balises de fin : passé la première ligne de balises qui suit sa parole, seules les
    balises comptent. Un texte écrit après n'est pas à dire (2026-10-14 : « Correction de balise : [EN_FACE: …] »
    arrivait à la personne). Une balise en tête de réponse ne coupe rien. Et si ce qui suit la ligne de balises
    contient encore une phrase (elle a posé sa balise au milieu de son message, puis repris), tout compte : ses
    balises se lisent où qu'elles soient, rien de ce qu'elle a dit ne tombe."""
    m = next((m for m in _TRAILER.finditer(text) if text[:m.start()].strip()), None)
    if m is None:
        return text
    tail = text[m.start():]
    if _SPOKEN.search(_BRACKETS.sub(" ", tail)):
        return text
    return text[:m.start()] + " ".join(_BRACKETS.findall(tail))


def lied(text: str, mark: str) -> tuple[int, int] | None:
    """Le passage faux de ce qu'elle a dit (``début``, ``fin``) : la phrase qui partage le plus de mots avec sa
    marque, pourvu qu'elle en porte au moins la moitié ; toute la réponse quand la marque ne cite rien
    (« [mensonge] »). ``None`` quand la marque cite une phrase que cette réponse ne contient pas — celle d'un message
    précédent, qu'elle croit après coup avoir inventée (ADR 0108) : ce n'est pas un mensonge de cette réponse, rien
    n'est désigné. La marque elle-même n'est jamais gardée."""
    wanted = stems(mark)
    if not wanted:
        return 0, len(text)
    best, span = 0, None
    for m in _SENTENCE.finditer(text):
        shared = len(stems(m.group()) & wanted)
        if shared > best and m.group().strip():
            best, span = shared, (m.start() + len(m.group()) - len(m.group().lstrip()), m.end())
    return span if 2 * best >= len(wanted) else None


def parse(text: str, speaker: str = "") -> tuple[str, dict[str, str]]:
    """Le texte sans balise, ce qu'elle a déclaré, ce qu'elle a lu de la personne (sa balise ``[EN_FACE: …]``,
    retirée, ADR 0093), si elle a posé une question, et si elle a menti (sa marque ``[MENSONGE: …]``, retirée : seul
    le passage faux est désigné). ``speaker`` : son nom (celui de sa persona) — un « Nom : » recopié en tête de
    réponse se retire."""
    text = closing(text or "")
    marks = [m.group(1) or "" for m in LIE_MARK.finditer(text)]
    unread, their = reading.read(LIE_MARK.sub("", text))
    tag = parse_tag(unread, speaker)
    annotations: dict[str, str] = {}
    if their is not None:
        annotations[c.READING_ANNOTATION] = their.encode()
    span = lied(tag.text, " ".join(marks)) if marks and tag.text.strip() else None
    if span is not None:
        annotations[c.LIE_ANNOTATION] = f"{span[0]}:{span[1]}"
    if tag.declared is not None:
        annotations[c.EMOTION_ANNOTATION] = tag.declared.encode()
    elif tag.unknown:
        annotations[c.UNKNOWN_EMOTION_ANNOTATION] = tag.unknown[:40]
    if "?" in tag.text:
        annotations[c.QUESTION_ANNOTATION] = "1"
    return tag.text, annotations


def reannotate(draft: str, annotations: Mapping[str, str], text: str) -> dict[str, str]:
    """Les annotations de sa réponse récrite par l'autrice (``text``, ADR 0114) : ce qu'elle ressent, ce qu'elle a lu
    de la personne et le fait d'avoir menti restent ceux du premier jet (``draft``) ; ce qui décrit la forme du texte se
    recalcule sur le message envoyé — une question qu'il pose (le premier jet finissait sur une question, le message
    envoyé non), et le passage faux, retrouvé dans le texte récrit (le texte entier quand il ne s'y retrouve pas : elle
    a menti quand même)."""
    out = {k: v for k, v in annotations.items() if k not in (c.QUESTION_ANNOTATION, c.LIE_ANNOTATION)}
    if "?" in text:
        out[c.QUESTION_ANNOTATION] = "1"
    lie = annotations.get(c.LIE_ANNOTATION)
    if lie is not None:
        start, _, end = lie.partition(":")
        passage = draft[int(start):int(end)] if start.isdigit() and end.isdigit() else ""
        span = (lied(text, passage) if passage.strip() else None) or (0, len(text))
        out[c.LIE_ANNOTATION] = f"{span[0]}:{span[1]}"
    return out


def _plain(text: str) -> str:
    """Sa parole sans balise ni jeton de voix."""
    return " ".join(strip_prosody(_BRACKETS.sub(" ", text or "")).split())
