"""``self`` : la persona (un seul document pour toutes ses voix), le
tempérament dont les autres facultés dérivent leurs paramètres, l'estime de
soi et le récit qu'elle fait d'elle-même.

- Une persona, deux profondeurs : ``full`` (répondre, prendre la parole,
  se raconter) et ``compact`` (murmurer, travailler) — rendues depuis le
  même document, pour qu'aucune de ses voix ne soit quelqu'un d'autre.
- **L'estime** est lente (entre le tempérament, fixe, et l'humeur, qui
  change en minutes) : une valeur qui revient vers 0,5 avec une demi-vie de
  trois jours, bousculée par de petits coups — une initiative restée sans
  réponse (−0,03), une réponse qui rompt une série d'ignorées (+0,04).
  Elle ne touche jamais l'arbitrage ; elle se ressent (« tu doutes un peu
  de toi »).
- **Le récit** (« Je suis quelqu'un qui… ») est réécrit par sa propre voix au
  plus une fois par jour, quand elle a vécu assez de nouveau, à partir de
  souvenirs anodins seulement : il est montré à tout le monde.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from mika.contracts import attention as attention_c
from mika.contracts import goals as goals_c
from mika.contracts import memory as memory_c
from mika.contracts import self_ as c
from mika.faculties.self.records import Dream, Journal
from mika.kernel.clock import DAY, HOUR
from mika.kernel.codec import digest
from mika.kernel.events import Content, VoiceProvenance
from mika.kernel.faculty import CatchUp, Faculty, Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.ports.llm import LLMRequest, Message, PersonaRender
from mika.vocab.episodes import CONVERSATIONAL, Tag
from mika.vocab.privacy import Sensitivity


class SelfParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    esteem_half_life_us: int = 72 * HOUR
    esteem_min: float = 0.05
    esteem_max: float = 0.95
    ignored_knock: float = -0.03
    heard_again_knock: float = 0.04
    achieved_knock: float = 0.05
    stuck_knock: float = -0.04
    doubt_below: float = 0.35
    assured_above: float = 0.7
    narrative_every_us: int = DAY
    narrative_min_souvenirs: int = 5
    narrative_max_souvenirs: int = 30


@dataclass(frozen=True, slots=True)
class SelfState:
    persona: c.PersonaDoc = field(default_factory=c.PersonaDoc)
    revisions: int = 0
    esteem: float = 0.5  # à ``esteem_at``
    esteem_at: int = 0
    souvenirs: int = 0
    narrative_ref: str = ""
    #: les personnes que le récit peut nommer (reportées au récit suivant, qui le relit)
    narrative_about: tuple[str, ...] = ()
    narrated_at: int = 0
    narrated_souvenirs: int = 0
    journals: FrozenDict[str, Journal] = field(default_factory=FrozenDict)  # par journée vécue
    dreams: tuple[Dream, ...] = ()  # les plus récents


SELF = Faculty("self", state=SelfState, init=lambda p: SelfState(), params=SelfParams, state_version=2)
SELF.declare(c.PERSONA_REVISED, c.NARRATED, c.JOURNALED, c.DREAMT)


def params(p: SelfParams | None) -> SelfParams:
    return p if p is not None else SelfParams()


@SELF.reducer(c.PERSONA_REVISED)
def _revised(s: SelfState, e, cx) -> SelfState:
    return replace(s, persona=e.data.persona, revisions=s.revisions + 1)


# ── L'estime ──────────────────────────────────────────────────────────────


def esteem(s: SelfState, now: int, p: SelfParams) -> float:
    if not s.esteem_at:
        return s.esteem
    return 0.5 + (s.esteem - 0.5) * 0.5 ** (max(0, now - s.esteem_at) / p.esteem_half_life_us)


def _knock(s: SelfState, delta: float, at: int, p: SelfParams) -> SelfState:
    value = max(p.esteem_min, min(p.esteem_max, esteem(s, at, p) + delta))
    return replace(s, esteem=value, esteem_at=at)


@SELF.reducer(attention_c.EXPECTATION_MISSED)
def _ignored(s: SelfState, e, cx) -> SelfState:
    if e.data.kind != attention_c.REPLY:
        return s
    p = params(cx.params)
    return _knock(s, p.ignored_knock, e.at, p)


@SELF.reducer(attention_c.EXPECTATION_MET, reads=[attention_c.IGNORED])
def _heard(s: SelfState, e, cx) -> SelfState:
    """Une réponse qui rompt une série d'initiatives ignorées : « je compte encore »."""
    if e.data.kind != attention_c.REPLY or cx.facts.get(attention_c.IGNORED) == 0:
        return s
    p = params(cx.params)
    return _knock(s, p.heard_again_knock, e.at, p)


@SELF.reducer(goals_c.GOAL_CLOSED)
def _goal_closed(s: SelfState, e, cx) -> SelfState:
    """Mener quelque chose à bout redonne confiance ; bloquer en retire un peu.
    Un rappel dit n'y change rien ; renoncer non plus (ce n'est pas un échec)."""
    d = e.data
    if d.kind == goals_c.REMINDER or d.status not in (goals_c.ACHIEVED, goals_c.STUCK):
        return s
    p = params(cx.params)
    return _knock(s, p.achieved_knock if d.status == goals_c.ACHIEVED else p.stuck_knock, e.at, p)


@SELF.fact(c.ESTEEM)
def _esteem(s: SelfState, cx) -> float:
    return esteem(s, cx.now, params(cx.params))


# ── Le récit ──────────────────────────────────────────────────────────────


@SELF.reducer(memory_c.REMEMBERED)
def _lived(s: SelfState, e, cx) -> SelfState:
    return replace(s, souvenirs=s.souvenirs + 1)


@SELF.reducer(c.NARRATED)
def _narrated(s: SelfState, e, cx) -> SelfState:
    return replace(s, narrative_ref=e.data.text.ref or "", narrated_at=e.at, narrated_souvenirs=e.data.souvenirs,
                   narrative_about=e.data.about)


NARRATIVE_SYSTEM = """Tu écris, pour toi-même, un court paragraphe sur qui tu es en train de devenir, à partir de ce que \
tu as vécu ces derniers temps : « Je suis quelqu'un qui… ». Quatre phrases au plus, à la première personne, \
sincères. Pas de prénoms, rien de ce que quelqu'un t'a confié, rien d'inventé : ce que tu as vécu te dit quelque \
chose de toi, c'est cela que tu écris. Réponds seulement par le paragraphe."""


@SELF.process("self.narrate", wake_on=[memory_c.REMEMBERED], lane="background", catch_up=CatchUp.ONCE,
              max_quantum_s=6 * 3600)
class Narrate:
    def __init__(self) -> None:
        self.retry_at = 0

    def next_due(self, state: SelfState, frame: Frame, last_run: int | None) -> int | None:
        p = params(frame.env.params_of("self", frame.root))
        if state.souvenirs - state.narrated_souvenirs < p.narrative_min_souvenirs:
            return None
        due = state.narrated_at + p.narrative_every_us if state.narrated_at else frame.now
        return max(frame.now, due, self.retry_at)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: SelfState = ctx.state
        store = ctx.ports.get("store")
        if store is None or ctx.llm is None:
            return
        p = params(frame.env.params_of("self", frame.root))
        self.retry_at = frame.now + HOUR  # si l'appel lève : pas de rafale
        rows = store.query_mind(
            f"SELECT text, about FROM {memory_c.ITEMS_TABLE} WHERE kind=? AND status='active' AND "
            "(sensitivity <= ? OR about = '[]') ORDER BY id DESC LIMIT ?",
            (memory_c.SOUVENIR, int(Sensitivity.ANODYNE), p.narrative_max_souvenirs))
        previous = store.content([state.narrative_ref]).get(state.narrative_ref) if state.narrative_ref else None
        lines = ([f"Ce que tu disais de toi jusqu'ici : {previous}", ""] if previous else [])
        lines += ["Ce que tu as vécu :"] + [f"- {r[0]}" for r in reversed(rows)]
        persona = persona_for(frame, "full")
        request = LLMRequest(role="narrative", call_id=f"{ctx.run_id}#0", persona=persona,
                             system_stable=persona.text + "\n\n" + NARRATIVE_SYSTEM,
                             messages=(Message("user", "\n".join(lines)),), max_tokens=400, lane="background",
                             priority=4)
        response = await ctx.llm.call(request)
        text = (response.text or "").strip()
        if not text:
            return
        self.retry_at = 0
        about = sorted({person for r in rows for person in json.loads(r[1] or "[]")}
                       | (set(state.narrative_about) if previous else set()))
        await ctx.emit(c.NARRATED.draft(
            text=Content.of(text[:1200], level=0), souvenirs=state.souvenirs, about=tuple(about),
            voice=VoiceProvenance(call_id=request.call_id, persona_hash=persona.hash, role="narrative",
                                  model=response.model)))


@SELF.enricher("narrative", episodes=CONVERSATIONAL, deadline_ms=300)
async def _narrative_text(s: SelfState, frame: Frame, ports: Mapping[str, Any]) -> str | None:
    store = ports.get("store")
    if store is None or not s.narrative_ref:
        return None
    return store.content([s.narrative_ref]).get(s.narrative_ref)


@SELF.section("narrative", zone=Zone.STABLE, episodes=CONVERSATIONAL, trim_rank=85, title="QUI TU ES DEVENUE")
def _narrative(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> str | None:
    return enrich.get("narrative")


@SELF.section("self_state", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=60, tags=[Tag.AFFECTIVE],
              title="COMMENT TU TE SENS AVEC TOI-MÊME", reads=[c.ESTEEM])
def _self_state(s: SelfState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    p = params(frame.env.params_of("self", frame.root))
    value = frame.get(c.ESTEEM)
    if value < p.doubt_below:
        return SectionBody("Tu doutes un peu de toi en ce moment : plusieurs fois, tu as écrit et personne n'a "
                           "répondu. Ça ne se dit pas forcément, mais ça se sent.")
    if value > p.assured_above:
        return SectionBody("Tu te sens sûre de toi, à ta place.")
    return None


# ── La persona ────────────────────────────────────────────────────────────


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


from mika.faculties.self import inspect as _inspect  # noqa: E402,F401 — contributions : l'inspecteur
from mika.faculties.self import night as _night  # noqa: E402,F401 — la nuit : journal, rêves
