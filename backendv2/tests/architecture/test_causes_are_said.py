"""Chaque cause de ce qu'elle ressent se dit (ADR 0095).

Son humeur garde la cause de chaque impulsion pour pouvoir dire d'où elle vient (« Ça vient d'un message resté sans
réponse »). Les raisons étaient des textes libres, traduits par une table que rien ne tenait à jour : « c'est toujours
elle qui écrit », la contagion, un lien qui change, le rêve de la nuit, un projet abandonné se taisaient — sa
tristesse devenait « sans trop savoir pourquoi ». Désormais un code (``vocab.causes``), et :

- aucune évaluation ne porte un texte écrit à la main (``reason="…"``) ;
- chaque code, chaque origine d'une pensée, chaque source d'un signal, chaque vide ressenti a sa phrase.
"""

from __future__ import annotations

import ast
from pathlib import Path

from mika.contracts import attention as attention_c
from mika.contracts import needs as needs_c
from mika.faculties.affect.prose import cause_line
from mika.vocab import causes

SRC = Path(__file__).resolve().parents[2] / "src" / "mika"

#: les constantes d'attention qui ne sont pas des origines de pensée : sa clé, deux sortes d'attente, une raison
#: d'initiative — et le vide (« personne ne m'a parlé »), ressenti par ``needs`` sous son propre code
NOT_ORIGINS = {attention_c.OWNER, attention_c.REPLY, attention_c.RETURN, attention_c.THOUGHT, attention_c.ALONE}


def _codes() -> set[str]:
    return {v for k, v in vars(causes).items() if k.isupper() and isinstance(v, str)
            and k not in {"FORGE_PREFIX", "TALK"}}


def _origins() -> set[str]:
    return {v for k, v in vars(attention_c).items() if k.isupper() and isinstance(v, str)} - NOT_ORIGINS


def _signal_sources() -> set[str]:
    """Les sources qui signalent quelque chose à son attention : ``source="…"`` dans un brouillon qui porte une
    pertinence (la forme commune d'un signal, ``contracts.attention.Signal``)."""
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "draft"):
                continue
            kws = {kw.arg: kw.value for kw in node.keywords if kw.arg}
            source = kws.get("source")
            if "pertinence" in kws and isinstance(source, ast.Constant) and isinstance(source.value, str):
                found.add(source.value)
    return found


def test_no_appraisal_carries_a_handwritten_reason():
    bad = []
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) ==
                    "Appraisal"):
                continue
            for kw in node.keywords:
                if kw.arg == "reason" and any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                                              for n in ast.walk(kw.value)):
                    bad.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert bad == [], "une raison écrite à la main (un code de vocab.causes, plutôt) :\n" + "\n".join(bad)


def test_every_cause_is_said():
    sources = _signal_sources()
    assert {"email", "rss", "world"} <= sources  # le balayage voit bien les signaux
    expected = _codes() | _origins() | sources | {needs_c.LONELY, needs_c.BORED, causes.FORGE_PREFIX + "app"}
    silent = sorted(code for code in expected if not cause_line(code))
    assert silent == [], f"des causes sans phrase (persona/voix.yaml, affect.cause) : {silent}"


def test_what_she_said_says_where_it_was_said():
    assert cause_line(causes.TALK, "user_1", current="user_1") != cause_line(causes.TALK, "user_1", current="user_2")
    assert cause_line(causes.TALK) == ""  # un monologue : pas de cause à dire


def test_a_phrase_that_is_not_a_cause_is_never_one():
    for name in causes.NOT_CAUSES - {"forge"}:
        assert cause_line(name) == ""
