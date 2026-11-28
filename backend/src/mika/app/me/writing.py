"""Écrire : « Corriger » (ADR 0307), les fautes d'un texte que tu écris dans Mail ou dans Teams, sans changer ses mots.

Un appel au modèle du rôle ``correct`` (``Role.CORRECT``, sans persona : ce n'est pas elle qui parle), au premier plan
— tu attends —, avec sa consigne (``correct.system``, ``persona/voix.yaml``). Le rôle est facultatif : sans modèle,
« Corriger » reste éteint (``GET /api/moi`` le dit, ``correct``) et la route refuse (409). Une correction à la fois par
compte, vingt par minute. Rien n'est gardé : ni au journal, ni ailleurs que dans le registre des appels de modèle.

**Les mots ne changent pas, quoi que le modèle rende** (``merged``) : sa réponse est alignée sur ton texte, mot par mot,
et seules s'appliquent les corrections qui ne touchent pas aux mots — les accents, la casse, la ponctuation et ses
espaces, un mot collé ou coupé par erreur, un mot redoublé, un mot remplacé par une forme proche (« renvoi » →
« renvoie », « sa » → « ça », « ses » → « c'est »). Un mot ajouté ou retiré, un chiffre changé, un mot remplacé par un
autre (« lundi » → « mardi », « refuse » → « accepte ») sont écartés, et comptés (``refused``) : ton texte reste ce que
tu as écrit à ces endroits. Une réponse incomplète (un refus du fournisseur, un plafond atteint) n'est jamais posée.
"""

from __future__ import annotations

import asyncio
import difflib
import re
import unicodedata
from typing import Any

from starlette.routing import Route

from mika.app.me.api import Call, Denied, MeApiBase, spend
from mika.kernel.prompt import PromptBudgetError
from mika.ports.llm import LLMRequest, Message
from mika.runtime.boundary import Failed, acall
from mika.vocab.episodes import Role
from mika.vocab.phrasebook import phrase

#: le plus long texte qu'on corrige d'un coup (un long mail)
TEXT_MAX = 20_000
#: un mot remplacé par une forme plus éloignée que ceci (sans accents ni casse) n'est plus une correction : écarté
NEAR_MIN = 0.5
#: au plus tant de mots d'un côté d'un remplacement (« quelque soit » → « quel que soit ») ; au-delà, écarté
GROUP_MAX = 3
#: les lettres d'une élision : « ses » → « c'est », un mot de plus permis quand c'en est une
ELISIONS = frozenset({"c", "d", "j", "l", "m", "n", "s", "t", "qu"})
#: le délai de la correction, sous ceux des clients (l'application attend une minute) : un texte qu'un modèle met plus
#: longtemps à corriger se dit trop long
DEADLINE_S = 50.0
NO_MODEL = "Aucun modèle ne corrige : un opérateur en choisit un dans Réglages › Intelligence (« corriger les fautes »)."
TOO_LONG = "Ton texte est trop long pour être corrigé d'un coup : corrige-le en plusieurs fois."
REFUSED = "Le modèle n'a pas voulu corriger ce texte : rien n'a été changé."
FAILED = "La correction n'a pas abouti : réessaie dans un instant."
BUSY = "Une correction est déjà en cours : attends qu'elle finisse."
_FENCE = re.compile(r"^```[^\n]*\n(?P<body>.*)\n```\s*$", re.S)
_TOKEN = re.compile(r"\w+|\s+|[^\w\s]")
#: une phrase, ou une ligne : jusqu'à sa ponctuation finale ou son retour à la ligne, et les blancs qui suivent
_CHUNK = re.compile(r"[^.!?…\n]*(?:[.!?…]+\s*|\n\s*|$)")
#: au-delà de tant de comparaisons (longueur × longueur), un passage s'aligne de proche en proche (``_greedy``,
#: linéaire) plutôt qu'au mieux (``difflib``, quadratique) : une phrase de vingt mille signes ne tient pas le serveur
EXACT_MAX = 250_000
#: de proche en proche : jusqu'où chercher où les deux textes se rejoignent, et sur combien de signes égaux
WINDOW, ANCHOR = 12, 3
_QUOTES = (("«", "»"), ('"', '"'), ("“", "”"))


def available(call: Call) -> bool:
    """Un modèle corrige-t-il ? Le rôle est facultatif (``OPTIONAL_ROLES``) : sans modèle, « Corriger » est éteint."""
    serving = getattr(call.kernel.deps.gateway, "serving", None)
    return callable(serving) and bool(serving(str(Role.CORRECT)))


def _fold(text: str) -> str:
    """Sans accents ni casse : ce qu'une correction d'accents ou de majuscules ne change pas."""
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return plain.lower()


def cleaned(answer: str, text: str) -> str:
    """Ce que le modèle a rendu, sans ce qu'il a pu ajouter autour — un bloc de code ou des guillemets qui enveloppent
    tout, quand ton texte ne commençait pas par l'un ni par les autres —, entre les blancs de bord de ton texte."""
    out = answer.strip()
    core = text.strip()
    fence = _FENCE.match(out)
    if fence is not None and not core.startswith("```"):
        out = fence.group("body").strip()
    if core and core[0] not in {q for pair in _QUOTES for q in pair}:
        for left, right in _QUOTES:
            inner = out[len(left):-len(right)] if len(out) > 1 and out.startswith(left) and out.endswith(right) else ""
            # une paire qui enveloppe tout, et rien qu'elle : pas deux citations (« Oui » … « non »)
            if inner and left not in inner and right not in inner:
                out = inner.strip()
                break
    if not core or not out:
        return out
    start = text.index(core[0])
    return text[:start] + out + text[start + len(core):]


def _words(tokens: list[str]) -> list[str]:
    return [_fold(t) for t in tokens if t[:1].isalnum() or t[:1] == "_"]


def _allowed(old: list[str], new: list[str], beside: tuple[str, str]) -> bool:
    """Un endroit où la réponse diffère de ton texte : la correction en est-elle une (elle ne touche pas aux mots) ?
    ``beside`` : les mots de ton texte juste avant et juste après cet endroit (un mot redoublé se retire)."""
    a, b = _words(old), _words(new)
    if a == b:
        return True  # ponctuation, espaces
    joined_a, joined_b = "".join(a), "".join(b)
    if any(ch.isdigit() for ch in joined_a + joined_b):
        return joined_a == joined_b  # « 14h » → « 14 h » ; jamais un chiffre changé
    if not b:
        return all(w in beside for w in a)  # « le le » → « le » ; jamais un mot retiré
    if not a or len(a) > GROUP_MAX or len(b) > GROUP_MAX:
        return False  # un mot ajouté, une phrase réécrite
    if joined_a == joined_b:
        return True  # un mot collé ou coupé par erreur
    if len(a) == len(b):  # chaque mot par une forme proche de lui (« renvoi » → « renvoie », « sa » → « ça »)
        return all(_near(x, y) for x, y in zip(a, b, strict=True))
    # un mot de plus d'un côté : seulement une élision (« ses » → « c'est »), jamais « bonjour » → « bien sûr »
    longer, shorter = (b, a) if len(b) > len(a) else (a, b)
    return len(longer) == len(shorter) + 1 and any(w in ELISIONS for w in longer) and _near(joined_a, joined_b)


def _near(x: str, y: str) -> bool:
    return difflib.SequenceMatcher(None, x, y, autojunk=False).ratio() >= NEAR_MIN


def _word(token: str) -> bool:
    return token[:1].isalnum() or token[:1] == "_"


def _greedy(a: list[str], b: list[str]) -> list[tuple[str, int, int, int, int]]:
    """Un alignement de proche en proche, linéaire : les signes égaux avancent ensemble ; ailleurs, le plus proche
    endroit où les deux suites se rejoignent sur ``ANCHOR`` signes, à ``WINDOW`` au plus de chaque côté. Faute de
    rejoindre, tout le reste est un seul changement — qui touchera aux mots, et restera tel que tu l'as écrit."""
    ops: list[tuple[str, int, int, int, int]] = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i0, j0 = i, j
            while i < len(a) and j < len(b) and a[i] == b[j]:
                i, j = i + 1, j + 1
            ops.append(("equal", i0, i, j0, j))
            continue
        found = next(((di, dj) for step in range(1, 2 * WINDOW + 1)
                      for di in range(max(0, step - WINDOW), min(step, WINDOW) + 1)
                      for dj in (step - di,)
                      if i + di < len(a) and j + dj < len(b) and a[i + di:i + di + ANCHOR] == b[j + dj:j + dj + ANCHOR]),
                     None)
        if found is None:
            break
        di, dj = found
        ops.append(("replace" if di and dj else "delete" if di else "insert", i, i + di, j, j + dj))
        i, j = i + di, j + dj
    if i < len(a) or j < len(b):
        ops.append(("replace" if i < len(a) and j < len(b) else "delete" if i < len(a) else "insert",
                    i, len(a), j, len(b)))
    return ops


def _opcodes(a: list[str], b: list[str]) -> list[tuple[str, int, int, int, int]]:
    """L'alignement de deux suites : au mieux quand elles sont courtes, de proche en proche sinon (``EXACT_MAX``)."""
    if len(a) * len(b) > EXACT_MAX:
        return _greedy(a, b)
    return difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()


def _tokens(a: list[str], b: list[str]) -> tuple[list[str], int, int]:
    """Un passage de ton texte et le même passage de la réponse, en signes (mots, blancs, ponctuation) : le passage
    avec les seules corrections permises, combien, combien d'écartées."""
    out: list[str] = []
    applied = refused = 0
    for op, i1, i2, j1, j2 in _opcodes([_fold(t) for t in a], [_fold(t) for t in b]):
        if op == "equal":
            out.extend(b[j1:j2])  # les mêmes mots : leurs accents et leur casse corrigés
            applied += sum(1 for x, y in zip(a[i1:i2], b[j1:j2], strict=True) if x != y)
            continue
        before = next((_fold(t) for t in reversed(a[:i1]) if _word(t)), "")
        after = next((_fold(t) for t in a[i2:] if _word(t)), "")
        if _allowed(a[i1:i2], b[j1:j2], (before, after)):
            out.extend(b[j1:j2])
            applied += 1
        else:
            out.extend(a[i1:i2])
            refused += 1
    return out, applied, refused


def merged(text: str, fixed: str) -> tuple[str, int, int]:
    """Ton texte, avec les seules corrections de ``fixed`` qui ne touchent pas aux mots : (le texte, combien de
    corrections, combien de changements écartés). Aligné phrase par phrase, puis mot par mot dans chaque phrase : un
    long mail ne fait jamais aligner tout le texte d'un bloc."""
    a = [c for c in _CHUNK.findall(text) if c]
    b = [c for c in _CHUNK.findall(fixed) if c]
    out: list[str] = []
    applied = refused = 0
    for op, i1, i2, j1, j2 in _opcodes([" ".join(_fold(c).split()) for c in a],
                                       [" ".join(_fold(c).split()) for c in b]):
        if op in ("equal", "replace") and i2 - i1 == j2 - j1:
            pairs = list(zip(a[i1:i2], b[j1:j2], strict=True))  # chaque phrase et sa correction
        else:
            pairs = [("".join(a[i1:i2]), "".join(b[j1:j2]))]  # des phrases fondues, coupées, ajoutées, retirées
        for old, new in pairs:
            got, n, m = _tokens(_TOKEN.findall(old), _TOKEN.findall(new))
            out.extend(got)
            applied, refused = applied + n, refused + m
    result = "".join(out)
    # plus d'écarté que de corrigé : la réponse n'est pas une correction de ce texte (une réécriture, une réponse au
    # message) — rien n'en est posé, pas même sa ponctuation
    if refused > applied or result == text:
        return text, 0, refused
    return result, applied, refused


async def correct(call: Call) -> dict[str, Any]:
    """« Corriger » : le texte, ses fautes corrigées sans changer ses mots ; ``changes`` : combien de corrections (0 :
    rien à corriger, ou rien qui ne touchait pas aux mots) ; ``refused`` : combien de changements du modèle ont été
    écartés parce qu'ils touchaient aux mots."""
    text = call.arg("text", limit=TEXT_MAX)
    if not text.strip():
        raise Denied(400, "Rien à corriger.", {"text": "vide"})
    if not available(call):
        raise Denied(409, NO_MODEL)
    account = call.me.account.id
    if account in call.api.correcting:
        raise Denied(429, BUSY)
    if not spend(call.api.corrections, call.me.account):
        raise Denied(429, "Trop de corrections d'affilée : attends une minute.")
    call.api.correcting.add(account)
    try:
        mind = call.kernel.mind
        req = LLMRequest(role=str(Role.CORRECT), call_id=f"corriger#{mind.ids.new(mind.clock.now())}",
                         system_stable=phrase("correct.system"), messages=(Message("user", text),),
                         max_tokens=min(16_000, 256 + len(text) // 2), lane="conversation", priority=0,
                         deadline_s=DEADLINE_S)
        got = await acall(call.kernel.deps.gateway.call, req, label="corriger")
    finally:
        call.api.correcting.discard(account)
    if isinstance(got, Failed):
        raise Denied(413 if isinstance(got.error, PromptBudgetError | TimeoutError) else 502,
                     TOO_LONG if isinstance(got.error, PromptBudgetError | TimeoutError) else FAILED)
    if got.stop == "max_tokens":
        raise Denied(413, TOO_LONG)
    if got.stop != "end" or not got.text.strip():
        raise Denied(422, REFUSED)  # un refus garde ce qu'il avait écrit : jamais posé, même en partie
    # l'alignement mot par mot ne tient pas la boucle du serveur (un long mail : quelques secondes)
    fixed, changes, refused = await asyncio.to_thread(merged, text, cleaned(got.text, text))
    return {"text": fixed, "changes": changes, "refused": refused}


def routes(api: MeApiBase) -> list[Route]:
    return [api.route("/correct", correct, write=True)]
