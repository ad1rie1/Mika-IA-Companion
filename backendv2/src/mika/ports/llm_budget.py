"""Budgets d'un fournisseur, partagés par le composeur et tous les appels LLM.

Le comptage en caractères est une estimation configurable, pas un tokenizer. Les
enveloppes de messages, les schémas, les images et la sortie ont leur réserve.
Une extraction trop longue échoue explicitement : on ne tronque jamais ses preuves.
Seuls les résultats d'outils, accompagnés d'un marqueur de coupe, peuvent être réduits.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import TypeVar

from mika.kernel.prompt import Budget, PromptBudgetError
from mika.ports.llm import LLMRequest

TOOL_CUT = "\n[résultat abrégé pour le contexte ; préciser la recherche pour la suite]"

T = TypeVar("T")


def fits_context(gateway, req: LLMRequest) -> bool:
    """Préparer des lots de preuves complets avec le budget du rôle effectivement routé."""
    budget_of = getattr(gateway, "budget", None)
    if budget_of is None:
        return True
    budget = budget_of(req.role, req.max_tokens)
    counter = LLMLimits(chars_per_token=budget.chars_per_token)
    return counter.size(req) <= budget.max_chars


def halved(items: Sequence[T], times: int, *, least: int = 0) -> list[T]:
    """Les premiers éléments, leur nombre divisé par deux ``times`` fois (jamais moins de ``least``)."""
    return list(items[:max(least, len(items) >> times)])


def fit_by_halving(gateway, build: Callable[[int], tuple[LLMRequest, bool]]) -> tuple[LLMRequest, int]:
    """La première requête qui tient dans le contexte du rôle routé. ``build(n)`` la construit avec ce qui est
    facultatif divisé par deux ``n`` fois (``halved``), et dit s'il en reste à diviser ; quand il n'en reste plus, la
    dernière est rendue même trop longue — à l'appelant de le voir (``fits_context``). Rend la requête et ``n``."""
    times = 0
    while True:
        request, more = build(times)
        if not more or fits_context(gateway, request):
            return request, times
        times += 1


@dataclass(frozen=True, slots=True)
class LLMLimits:
    context_tokens: int = 24_000
    max_output_tokens: int = 0
    chars_per_token: float = 3.6
    image_tokens: int = 2048

    def output(self, requested: int) -> int:
        return min(requested, self.max_output_tokens) if self.max_output_tokens else requested

    def reserve(self, requested: int, effective: int | None = None) -> int:
        """La sortie à réserver dans le contexte : le plafond demandé (borné par ``max_output_tokens``), relevé jusqu'au
        plafond que le fournisseur enverra vraiment (``effective`` : un modèle qui réfléchit a son plancher) — sans
        jamais prendre plus de la moitié du contexte, pour qu'un fournisseur à petite fenêtre déclarée (24 000 par
        défaut) garde de quoi lire son prompt ; au-delà, c'est ``context_tokens`` qu'il faut relever."""
        asked = self.output(requested)
        if effective is None or effective <= asked:
            return asked
        return max(asked, min(effective, self.context_tokens // 2))

    def budget(self, requested: int, effective: int | None = None) -> Budget:
        return Budget(max_tokens=max(0, self.context_tokens - self.reserve(requested, effective)),
                      chars_per_token=self.chars_per_token)

    def overhead(self, req: LLMRequest) -> int:
        # Marge de sérialisation, en plus du texte, commune au premier appel et aux suites.
        return round((64 + 16 * len(req.messages) + self.image_tokens * sum(
            len(m.images) for m in req.messages)) * self.chars_per_token)

    def size(self, req: LLMRequest) -> int:
        tools = sum(len(t.name) + len(t.description) + len(json.dumps(t.schema, ensure_ascii=False))
                    for t in req.tools)
        calls = sum(len(c.id) + len(c.name) + len(json.dumps(dict(c.args), ensure_ascii=False))
                    for m in req.messages for c in m.tool_calls)
        return (len(req.system_stable) + len(req.system_volatile) + tools + calls + self.overhead(req)
                + sum(len(m.content) + len(m.tool_call_id or "") + len(m.name or "") for m in req.messages))

    def fit(self, req: LLMRequest, effective: int | None = None) -> LLMRequest:
        """``effective`` : le plafond de sortie que le fournisseur enverra vraiment (un modèle qui réfléchit a un
        plancher au-dessus de ``req.max_tokens``) — la sortie est réservée dessus, jamais sur le seul plafond demandé."""
        req = replace(req, max_tokens=self.output(req.max_tokens))
        ceiling = self.budget(req.max_tokens, effective).max_chars
        excess = self.size(req) - ceiling
        if excess <= 0:
            return req
        messages = list(req.messages)
        # D'abord les anciens résultats ; ni les appels ni leurs identifiants ne disparaissent.
        for i, message in enumerate(messages):
            if message.role != "tool" or len(message.content) <= len(TOOL_CUT):
                continue
            keep = max(0, len(message.content) - excess - len(TOOL_CUT))
            content = message.content[:keep].rstrip() + TOOL_CUT
            excess -= len(message.content) - len(content)
            messages[i] = replace(message, content=content)
            if excess <= 0:
                break
        req = replace(req, messages=tuple(messages))
        if self.size(req) > ceiling:
            raise PromptBudgetError("requête trop longue pour le contexte du fournisseur (sortie réservée)")
        return req
