"""Écrire : « Corriger » (ADR 0307), les fautes d'un texte que tu écris dans Mail ou dans Teams, sans changer ses mots.

Un appel au modèle du rôle ``correct`` (``Role.CORRECT``, sans persona : ce n'est pas elle qui parle), au premier plan
— tu attends —, avec sa consigne (``correct.system``, ``persona/voix.yaml``). Le rôle est facultatif : sans modèle,
« Corriger » reste éteint (``GET /api/moi`` le dit, ``correct``) et la route refuse (409). Rien n'est gardé : ni au
journal, ni ailleurs que dans le registre des appels de modèle.

Ce qui revient est relu avant de te le rendre : une réponse qui ajoute, retire ou remplace trop de choses (un modèle
qui reformule, qui répond au texte au lieu de le corriger) est refusée plutôt que de remplacer ce que tu as écrit.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

from starlette.routing import Route

from mika.app.me.api import Call, Denied, MeApiBase, spend
from mika.ports.llm import LLMRequest, Message
from mika.runtime.boundary import Failed, acall
from mika.vocab.episodes import Role
from mika.vocab.phrasebook import phrase

#: le plus long texte qu'on corrige d'un coup (un long mail)
TEXT_MAX = 20_000
#: en dessous, la réponse ne ressemble plus assez au texte (comparés sans accents ni casse) : ce n'est plus une
#: correction — refusée
SAME_MIN = 0.75
NO_MODEL = "Aucun modèle ne corrige : un opérateur en choisit un dans Réglages › Intelligence (« corriger les fautes »)."
TOO_MUCH = "La correction changeait trop ton texte : rien n'a été changé."
_FENCE = re.compile(r"^```[^\n]*\n(?P<body>.*)\n```\s*$", re.S)


def available(call: Call) -> bool:
    """Un modèle corrige-t-il ? Le rôle est facultatif (``OPTIONAL_ROLES``) : sans modèle, « Corriger » est éteint."""
    serving = getattr(call.kernel.deps.gateway, "serving", None)
    return callable(serving) and bool(serving(str(Role.CORRECT)))


def _folded(text: str) -> str:
    """Le texte sans accents ni casse ni espaces doublés : ce qu'une correction d'accents ou de majuscules ne change
    pas, pour juger si elle a changé autre chose."""
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return " ".join(plain.lower().split())


def cleaned(answer: str, text: str) -> str:
    """Ce que le modèle a rendu, sans ce qu'il a pu ajouter autour (un bloc de code ou des guillemets qui enveloppent
    tout, si le texte ne l'était pas), entre les blancs de bord du texte tel que tu l'as écrit."""
    out = answer.strip()
    fence = _FENCE.match(out.strip())
    if fence is not None and not text.lstrip().startswith("```"):
        out = fence.group("body")
    for left, right in (("«", "»"), ('"', '"'), ("“", "”")):
        inner = out.strip()
        if len(inner) > 1 and inner.startswith(left) and inner.endswith(right) and not (
                text.strip().startswith(left) and text.strip().endswith(right)):
            out = inner[len(left):-len(right)].strip()
    core = text.strip()
    if not core or not out.strip():
        return out.strip()
    start = text.index(core[0])
    return text[:start] + out.strip() + text[start + len(core):]


def changes(text: str, fixed: str) -> int:
    """Combien de corrections : les endroits où le texte diffère (un mot, un signe, un blanc, une suite d'entre eux)."""
    a, b = re.findall(r"\w+|\s+|[^\w\s]", text), re.findall(r"\w+|\s+|[^\w\s]", fixed)
    return sum(1 for op, *_ in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op != "equal")


def faithful(text: str, fixed: str) -> bool:
    """La réponse est-elle encore ce texte, corrigé ? Comparée sans accents ni casse, elle lui ressemble assez."""
    return difflib.SequenceMatcher(None, _folded(text), _folded(fixed), autojunk=False).ratio() >= SAME_MIN


async def correct(call: Call) -> dict[str, Any]:
    """« Corriger » : le texte, ses fautes corrigées, et combien (``changes`` ; 0 : rien à corriger)."""
    text = call.arg("text", limit=TEXT_MAX)
    if not text.strip():
        raise Denied(400, "Rien à corriger.", {"text": "vide"})
    if not available(call):
        raise Denied(409, NO_MODEL)
    if not spend(call.api.corrections, call.me.account):
        raise Denied(429, "Trop de corrections d'affilée : attends une minute.")
    mind = call.kernel.mind
    req = LLMRequest(role=str(Role.CORRECT), call_id=f"corriger#{mind.ids.new(mind.clock.now())}",
                     system_stable=phrase("correct.system"), messages=(Message("user", text),),
                     max_tokens=min(16_000, 256 + len(text) // 2), lane="conversation", priority=0)
    got = await acall(call.kernel.deps.gateway.call, req, label="corriger")
    if isinstance(got, Failed):
        raise Denied(502, "La correction n'a pas abouti : réessaie dans un instant.")
    fixed = cleaned(got.text, text)
    if got.stop == "max_tokens" or not fixed.strip() or not faithful(text, fixed):
        raise Denied(422, TOO_MUCH)
    n = changes(text, fixed)
    return {"text": fixed if n else text, "changes": n}


def routes(api: MeApiBase) -> list[Route]:
    return [api.route("/correct", correct, write=True)]
