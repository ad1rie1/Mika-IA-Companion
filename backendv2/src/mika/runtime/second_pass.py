"""La seconde passe et l'autrice d'un brouillon (ADR 0112, 0114, 0124).

Un appel de plus sur un texte déjà prêt, par le modèle du rôle ``polish`` seulement, sans outil, en un tour :

- **la seconde passe** (``SecondPass.polish``) récrit sa réponse au vu du fil, rendue naturelle, sans rien y ajouter ;
  ``reannotate`` recalcule ce qui décrit la forme du texte récrit ;
- **l'autrice d'un brouillon** (``SecondPass.author_draft``) récrit un brouillon d'outil (un courriel, un message
  Teams, un SMS) dans les codes de l'autrice de son flux ;
- ``authored`` dit si une parole de cette sorte passe par l'autrice, ``author`` qui est l'autrice d'un flux.

Une panne, rien rendu, un silence, une récriture qui dérive en longueur ou qui perd un fait du premier jet : le premier
jet part tel quel. Chaque passe tient dans l'échéance de l'épisode (``extra_pass``) et laisse sa trace dans celle de
l'épisode (``naturel``, ``autrice``). Le pipeline d'épisode (``runtime/pipeline.py``) construit la seconde passe et
l'appelle entre l'analyse et le prélude ; elle ne connaît pas l'épisode vivant, seulement sa trace et son échéance.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from mika.kernel.clock import Clock
from mika.ports.llm import LLMGateway, LLMRequest, Message, PersonaRender
from mika.runtime.boundary import Failed, acall, call, describe
from mika.runtime.kept_facts import keeps_facts
from mika.runtime.reply_text import is_silence
from mika.runtime.tools import LoopResult, ToolContext, run_tool_loop
from mika.vocab import flows
from mika.vocab.episodes import Role
from mika.vocab.flows import Author
from mika.vocab.phrasebook import phrase

#: La seconde passe sur une parole : (sa réponse, les messages de son appel, ce que la personne vient de dire, sa persona
#: rendue, l'autrice du chat, le texte de chaque section de son prompt par clé) → (consigne, message, ce qu'on garde de
#: ce que l'appel a écrit) d'un appel qui récrit sa réponse, ou ``None`` : rien à reprendre.
Polisher = Callable[[str, Sequence[Message], str, "PersonaRender | None", "Author | None", Mapping[str, str]],
                    "tuple[str, str, Callable[[str], str]] | None"]
#: La passe d'une autrice sur un brouillon d'outil (ADR 0124) : (son flux, le premier jet, ce à quoi il répond,
#: l'autrice) → (consigne, message) d'un appel qui le récrit, ou ``None`` : cette forme ne se récrit pas.
DraftPolisher = Callable[[str, str, str, Author], "tuple[str, str] | None"]
#: l'autrice d'un flux (``vocab.flows``), ou ``None`` : aucune n'y écrit
AuthorOf = Callable[[str], "Author | None"]
#: Les annotations d'une parole récrite par la seconde passe : (son premier jet, ses annotations, le texte récrit) →
#: celles du texte récrit (ce qui décrit la forme du texte — une question, un passage — suit le message envoyé).
Reannotator = Callable[[str, Mapping[str, str], str], Mapping[str, str]]
#: une réponse récrite plus longue que ``_POLISH_GROWTH`` fois le premier jet (plus ``_POLISH_SLACK`` caractères) a
#: dérivé : on garde le premier jet (l'autrice peut envoyer en plusieurs bulles ce qu'un « ah merde. » disait seul)
_POLISH_GROWTH, _POLISH_SLACK = 2.0, 120
#: … pour un brouillon (un courriel a sa formule d'appel et sa formule de politesse) : plus de marge
_DRAFT_SLACK = 400
#: sans réglage des autrices, le chat a l'autrice livrée « Message » : son nom et ses codes, qui portent la forme
#: (ADR 0124, 0140) — sans eux, rien ne dirait comment on écrit dans un chat
_CHAT_AUTHOR = Author(flows.CHAT, phrase("expression.author.defaults.message.name"),
                      phrase("expression.author.defaults.message.codes"))
#: un brouillon que le modèle a mis entre trois accents graves
_FENCED = re.compile(r"^```[\w-]*\n(.*)\n```$", re.S)
#: ce qu'une passe de plus (la seconde passe) laisse de l'échéance de l'épisode, en secondes, pour écrire la
#: réponse : passé ce point, elle s'arrête et le premier jet part
_PASS_SPARE_S = 5.0


def _no_tools(spec: Any, call_id: str) -> ToolContext:
    """Le contexte d'outil d'une passe qui n'en offre aucun : jamais demandé."""
    raise RuntimeError("une passe sans outil n'appelle pas d'outil")


class SecondPass:
    """La seconde passe sur sa parole et l'autrice d'un brouillon d'outil, pour un pipeline d'épisode. ``parse`` :
    ce qui tire d'un texte récrit (et du nom de qui parle) le texte livrable, comme pour le premier jet."""

    def __init__(
        self,
        gateway: LLMGateway | None,
        clock: Clock,
        parse: Callable[[str, str], tuple[str, Mapping[str, str]]],
        *,
        polishers: Sequence[Polisher],
        polished: Sequence[str],
        reannotators: Sequence[Reannotator],
        authors: AuthorOf | None,
        draft_polishers: Sequence[DraftPolisher],
    ) -> None:
        self.gateway = gateway
        self.clock = clock
        self.parse = parse
        self.polishers = list(polishers)
        #: les sortes d'épisode dont la parole passe une seconde fois, pour être rendue naturelle (``polishers``)
        self.polished = frozenset(polished)
        #: ce qui recalcule les annotations d'une parole récrite par la seconde passe (``Reannotator``)
        self.reannotators = list(reannotators)
        #: l'autrice de chaque flux (ADR 0124) ; ``None`` : le chat garde son autrice d'avant elles, un brouillon n'en a
        #: pas
        self.authors = authors
        #: ce qui écrit la passe d'une autrice sur un brouillon d'outil (``DraftPolisher``)
        self.draft_polishers = list(draft_polishers)

    @staticmethod
    async def extra_pass(deadline: asyncio.Timeout | None, fn: Callable[[], Awaitable[LoopResult]], *,
                         label: str) -> LoopResult | Failed:
        """Un appel de plus sur un texte déjà prêt (seconde passe, autrice), rangé dans l'échéance de l'épisode
        moins de quoi écrire la réponse (``_PASS_SPARE_S``) : s'il n'y tient pas, c'est une panne comme une autre et le
        premier jet part — jamais l'échéance de l'épisode qui tomberait pendant lui et jetterait la réponse prête."""
        if deadline is None or (when := deadline.when()) is None:
            return await acall(fn, label=label)
        try:
            async with asyncio.timeout_at(when - _PASS_SPARE_S):
                return await acall(fn, label=label)
        except TimeoutError as exc:
            return Failed(exc)

    def authored(self, kind: str) -> bool:
        """Sa parole de cette sorte passe par l'autrice : un polisseur, cette sorte, une autrice au chat, et un modèle
        au rôle ``polish``."""
        serving = getattr(self.gateway, "serving", None)
        return (bool(self.polishers) and kind in self.polished and callable(serving)
                and bool(serving(str(Role.POLISH))) and self.author(flows.CHAT) is not None)

    def author(self, flow: str) -> Author | None:
        """L'autrice d'un flux (``authors``). Sans réglage des autrices, le chat garde la sienne d'avant elles (le
        cadre seul) et un brouillon n'en a pas."""
        if self.authors is None:
            return _CHAT_AUTHOR if flow == flows.CHAT else None
        got = call(self.authors, flow, label="l'autrice d'un flux")
        return got if isinstance(got, Author) else None

    async def polish(self, seen: dict[str, Any], deadline: asyncio.Timeout | None, eid: str, llm_req: LLMRequest,
                     text: str, heard: str, persona: PersonaRender | None, bodies: Mapping[str, str]) -> str:
        """Sa réponse récrite (``polishers``) par le modèle du rôle ``polish`` — seulement si l'opératrice lui en a
        donné un : sans repli, une installation ne paie pas un second appel de sa voix sans l'avoir choisi. Le
        polisseur dit ce qu'on garde de ce que l'appel a écrit (l'autrice écrit aussi la réponse de l'autre, ADR 0114).
        ``bodies`` : le texte de chaque section de son prompt, par clé (``ChatPrompt.bodies``). Une panne, rien gardé,
        un silence, ou une réponse qui dérive en longueur : le premier jet part tel quel. ``seen`` : la trace de
        l'épisode, où elle laisse la sienne (``naturel``) ; ``deadline`` : l'échéance de l'épisode."""
        gateway = self.gateway
        serving = getattr(gateway, "serving", None)
        if gateway is None or not callable(serving) or not serving(str(Role.POLISH)):
            return text
        name = persona.name if persona is not None else ""
        author = self.author(flows.CHAT)
        if author is None:
            return text
        asked = None
        for polisher in self.polishers:
            got = call(polisher, text, llm_req.messages, heard, persona, author, bodies,
                       label="seconde passe sur la réponse")
            if isinstance(got, tuple):
                asked = got
                break
        if asked is None:
            return text
        system, message, keep = asked
        req = LLMRequest(role=str(Role.POLISH), call_id=f"{eid}#naturel", system_stable=system,
                         messages=(Message("user", message),), max_tokens=llm_req.max_tokens, lane=llm_req.lane,
                         priority=llm_req.priority, deadline_s=llm_req.deadline_s,
                         meta={**dict(llm_req.meta), "passe": "naturel"})
        # ce qu'elle a lu et ce qu'elle a rendu, gardés dans la trace quelle que soit l'issue (« pourquoi a-t-elle dit
        # ça ? ») ; écartée, la raison dit pourquoi le premier jet est parti
        natural: dict[str, Any] = {"premier_jet": text, "autrice": author.key, "systeme": system, "message": message}
        seen["naturel"] = natural
        again = await self.extra_pass(
            deadline, lambda: run_tool_loop(gateway, req, {}, _no_tools, max_turns=1, clock=self.clock.now),
            label="seconde passe : appel du modèle")
        if isinstance(again, Failed):
            natural["ecartee"] = f"panne : {describe(again.error)}"
            return text
        natural["reponse"] = again.text
        kept = call(keep, again.text, label="seconde passe : ses messages")
        if isinstance(kept, Failed):
            natural["ecartee"] = "ses messages illisibles"
            return text
        polished, _annotations = self.parse(kept, name)
        polished = polished.strip()
        if not polished or is_silence(polished):
            natural["ecartee"] = "rien rendu"
            return text
        if len(polished) > len(text) * _POLISH_GROWTH + _POLISH_SLACK:
            natural["ecartee"] = "plus longue que le premier jet"
            return text
        if not keeps_facts(text, polished):
            # l'autrice n'a pas vu les résultats des outils : une température, une heure, un lien du premier jet
            # qui manquent au texte récrit, et c'est le premier jet qui part
            natural["ecartee"] = "faits du premier jet perdus"
            return text
        return polished

    async def author_draft(self, seen: dict[str, Any], deadline: asyncio.Timeout | None, eid: str,
                           llm_req: LLMRequest, flow: str, text: str, about: str) -> str:
        """Un brouillon d'outil (un courriel, un message Teams, un SMS à la place de la personne) récrit par l'autrice
        de son flux (ADR 0124), comme la seconde passe de sa parole : par le modèle du rôle ``polish`` seulement, sans
        outil, en un tour. Pas d'autrice, pas de modèle, une panne, rien rendu, un silence, ou un texte qui dérive en
        longueur : le premier jet est posé tel quel. ``seen`` : la trace de l'épisode, où chaque brouillon récrit
        laisse la sienne (``autrice``) ; ``deadline`` : l'échéance de l'épisode."""
        gateway = self.gateway
        serving = getattr(gateway, "serving", None)
        author = self.author(flow)
        if gateway is None or author is None or not callable(serving) or not serving(str(Role.POLISH)):
            return text
        asked = None
        for polisher in self.draft_polishers:
            got = call(polisher, flow, text, about, author, label="autrice d'un brouillon")
            if isinstance(got, tuple):
                asked = got
                break
        if asked is None:
            return text
        system, message = asked
        done = seen.setdefault("autrice", [])
        req = LLMRequest(role=str(Role.POLISH), call_id=f"{eid}#autrice{len(done)}", system_stable=system,
                         messages=(Message("user", message),), max_tokens=llm_req.max_tokens, lane=llm_req.lane,
                         priority=llm_req.priority, deadline_s=llm_req.deadline_s,
                         meta={**dict(llm_req.meta), "passe": "autrice", "flux": flow})
        again = await self.extra_pass(
            deadline, lambda: run_tool_loop(gateway, req, {}, _no_tools, max_turns=1, clock=self.clock.now),
            label="autrice d'un brouillon : appel du modèle")
        if isinstance(again, Failed):
            return text
        written = again.text.strip()
        fenced = _FENCED.match(written)
        written = fenced.group(1).strip() if fenced else written
        if not written or is_silence(written) or len(written) > len(text) * _POLISH_GROWTH + _DRAFT_SLACK \
                or not keeps_facts(text, written):
            return text
        done.append({"flux": flow, "autrice": author.key, "premier_jet": text})
        return written

    def reannotate(self, draft: str, annotations: Mapping[str, str], text: str) -> dict[str, str]:
        """Les annotations du texte récrit (``reannotators``) ; une panne garde celles qu'on avait."""
        out = dict(annotations)
        for reannotator in self.reannotators:
            got = call(reannotator, draft, out, text, label="annotations de la réponse récrite")
            if not isinstance(got, Failed):
                out = dict(got)
        return out
