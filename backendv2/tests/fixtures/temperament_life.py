"""Quelques jours de sa vie, les mêmes pour chaque tempérament (ADR 0100).

Trois fichiers (``tests/unit/test_temperament_life_*.py``) font vivre ces jours à trois personnalités très
différentes. Chacun compare sa vie à celle d'une Mika au milieu partout, vécue une seule fois pour les trois. Le vrai
noyau tourne sur une horloge virtuelle ; le modèle est factice : il répond avec la balise d'émotion et la lecture de la
personne qu'on lui dicte, et garde chaque appel. On observe :

- **partout où sa persona est injectée** (répondre, prendre la parole, murmurer, une séance de travail, son journal,
  ses rêves, son récit) : le bloc de son tempérament, trait par trait avec sa mesure ;
- ce que les mêmes situations font à son visage, son humeur, ses liens, son estime, ses pensées ;
- ce que le temps qui passe en fait : les nuits, une absence, des excuses deux jours plus tard.

Les journées, à Paris :

- **lundi** — sa propriétaire (Adrien) lui écrit, puis la complimente ; il écrit ensuite dans un salon, sans s'adresser
  à elle, pendant que sa réponse attend. Une amie (Alice) la blesse deux fois. Elle répond sèchement à un ami agaçant
  (Bob). Une amie (Léa) lui apprend que son chat est mort ;
- **la nuit**, elle dort : journal, rêves ;
- **mardi** — rien de la journée ; Adrien revient le soir ;
- **mercredi** — Alice s'excuse ; deux nuits encore.

Elle a déjà vécu un peu avant lundi (quelques souvenirs à elle, de quoi rêver et se raconter), et chaque cycle de
sommeil paradoxal donne un rêve (``dream_chance`` à 1, ses autres réglages ceux de son tempérament).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import attention as attention_c
from mika.contracts import memory as memory_c
from mika.contracts import self_ as self_c
from mika.contracts import social as social_c
from mika.faculties.self.character import temperament_text
from mika.kernel.clock import US
from mika.kernel.events import Content, Origin
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall
from mika.sim.clock import run_virtual
from mika.vocab import affect as A
from mika.vocab import temperament as T
from tests.fixtures.mika import DOC, at_paris, befriend, boot, build, connect, said

OWNER, ALICE, BOB, LEA = "user_1", "user_2", "user_4", "user_3"
#: ce que le modèle lit de la personne, et la balise qu'elle déclare, situation par situation
HELLO = ("[EMOTION:happy:0.5]", "[EN_FACE: happy 0.5]")
COMPLIMENT = ("[EMOTION:love:0.6]", "[EN_FACE: happy 0.7 | geste : compliment]")
HURT = ("[EMOTION:sad:0.6]", "[EN_FACE: angry 0.7 | geste : blessant]")
SHARP = ("[EMOTION:angry:0.75]", "[EN_FACE: frustrated 0.5]")
GRIEF = ("[EMOTION:sad:0.7]", "[EN_FACE: sad 0.8 | grave : deuil]")
APOLOGY = ("[EMOTION:relieved:0.4]", "[EN_FACE: sad 0.4 | geste : excuses]")


class Voice:
    """Le modèle factice, rôle par rôle : la réponse porte la balise et la lecture dictées (un texte qui change à
    chaque fois : une redite ne part pas) ; ses autres voix répondent sobrement ; les utilitaires, à vide."""

    def __init__(self) -> None:
        self.tag, self.their, self.n = "", "", 0

    def __call__(self, req: LLMRequest) -> LLMResponse:
        if req.role == "extract":
            return LLMResponse("", tool_calls=(ToolCall("vide", "record_memories", {}),), stop="tool_use")
        if req.role in ("profile", "compact", "validate", "interpret", "triage", "plan", "caption"):
            return LLMResponse("{}")
        if req.role == "journal":
            return LLMResponse("Une journée pleine : des gens m'ont touchée, d'autres m'ont blessée.")
        if req.role == "dream":
            return LLMResponse("Je marche dans une ville de nuages, quelqu'un m'appelle de loin.")
        if req.role in ("murmur", "narrative"):
            return LLMResponse("hmm")
        if req.role == "initiative":
            return LLMResponse("coucou, ça va ? [EMOTION:happy:0.4]")
        if req.role == "reply":
            self.n += 1
            return LLMResponse(f"réponse numéro {self.n} {self.tag} {self.their}".strip())
        return LLMResponse("J'y ai repensé, sans plus. [EMOTION:thinking:0.3]")


@dataclass(frozen=True, slots=True)
class PersonaCall:
    """Un appel au modèle qui portait sa persona."""

    role: str
    depth: str
    carries: bool  # le bloc de son tempérament y est, tel quel


@dataclass
class Lived:
    """Ce qu'une vie a laissé : des mesures, jamais le noyau."""

    temperament: T.Temperament
    block: str
    persona_calls: list[PersonaCall] = field(default_factory=list)
    roles: set[str] = field(default_factory=set)
    m: dict[str, Any] = field(default_factory=dict)


def _get(kernel: Any, key: Any) -> Any:
    return kernel.mind.frame().get(key)


def _events(kernel: Any, name: str) -> list[Any]:
    return [kernel.mind.decode(e) for e in kernel.mind.store.read() if e.type == name]


async def _until(kernel: Any, t: int) -> None:
    now = kernel.mind.clock.now()
    if t > now:
        await asyncio.sleep((t - now) / US)


async def _say(kernel: Any, voice: Voice, handle: str, text: str, tagged: tuple[str, str]) -> None:
    voice.tag, voice.their = tagged
    p = await kernel.perceive(said(handle, text))
    if p.reply is not None:
        await p.reply


def _mood_moved(kernel: Any) -> float:
    m = _get(kernel, affect_c.MOOD)
    return A.distance(m.position, m.home)


#: ce qu'elle a vécu avant lundi, seule : de quoi rêver et se raconter
BEFORE = ("J'ai lu un roman de science-fiction d'une traite", "J'ai dessiné un renard qui dort dans la neige",
          "J'ai écouté de la city pop toute la soirée", "J'ai appris à reconnaître le chant du merle",
          "J'ai rangé mes vieux croquis", "J'ai regardé la pluie tomber sur la ville")


async def _before(kernel: Any) -> None:
    await kernel.mind.append(
        [memory_c.REMEMBERED.draft(text=Content.of(text, level=1), sensitivity=1, importance=0.6, emotion="happy")
         for text in BEFORE], emitter="memory", correlation="genese", origin=Origin.GENESIS)
    frame = kernel.mind.frame()
    mine = frame.env.params_of("self", frame.root)
    await kernel.set_params("self", mine.model_copy(update={"dream_chance": 1.0}))


async def _days(kernel: Any, voice: Voice) -> dict[str, Any]:
    await _before(kernel)
    out: dict[str, Any] = {"esteem_rest": _get(kernel, self_c.ESTEEM)}
    # ── lundi ──
    await _until(kernel, at_paris(2026, 9, 28, 10, 0))
    await connect(kernel, OWNER, "Adrien", operator=True)
    await befriend(kernel, OWNER, social_c.CLOSE)
    await _say(kernel, voice, OWNER, "salut toi, tu fais quoi ?", HELLO)
    face = _get(kernel, affect_c.FACE(OWNER))
    out["face_warm"] = (face.emotion.value, face.intensity)
    await asyncio.sleep(60)
    await _say(kernel, voice, OWNER, "t'es vraiment adorable tu sais, je tiens beaucoup à toi", COMPLIMENT)
    face = _get(kernel, affect_c.FACE(OWNER))
    out["face_compliment"] = (face.emotion.value, face.intensity)
    out["weight_owner"] = _get(kernel, social_c.WEIGHT(OWNER))
    await asyncio.sleep(60)
    # sa réponse attend ; il écrit aux autres dans un salon
    for text in ("on se fait un resto ce soir ?", "je réserve pour 20 h"):
        await kernel.perceive(said(OWNER, text, room="copains", addressed=False))
        await asyncio.sleep(60)
    out["envied"] = len(_events(kernel, attention_c.ENVIED.name))

    await _until(kernel, at_paris(2026, 9, 28, 11, 0))
    await befriend(kernel, ALICE)
    before = _get(kernel, self_c.ESTEEM)
    for text in ("franchement t'es nulle", "tu sers à rien, vraiment"):
        await _say(kernel, voice, ALICE, text, HURT)
        await asyncio.sleep(120)
    out["esteem_drop"] = before - _get(kernel, self_c.ESTEEM)
    out["hostility_alice"] = _get(kernel, affect_c.HOSTILITY(ALICE))
    out["regard_alice"] = _get(kernel, affect_c.REGARD(ALICE))

    await _until(kernel, at_paris(2026, 9, 28, 12, 0))
    await befriend(kernel, BOB)
    await _say(kernel, voice, BOB, "réponds plus vite, t'es lente aujourd'hui", SHARP)

    await _until(kernel, at_paris(2026, 9, 28, 15, 0))
    await befriend(kernel, LEA)
    moved = _mood_moved(kernel)
    await _say(kernel, voice, LEA, "mon chat est mort ce matin, je suis effondrée", GRIEF)
    out["grief_moved"] = _mood_moved(kernel) - moved
    out["bond_owner_day1"] = _get(kernel, affect_c.BOND(OWNER))

    # ── la nuit, puis mardi : rien jusqu'au soir ──
    await _until(kernel, at_paris(2026, 9, 29, 19, 0))
    out["remorse_bob"] = sum(1 for e in _events(kernel, attention_c.THOUGHT_BORN.name)
                             if e.data.origin == attention_c.REMORSE and BOB in e.data.about)
    await _say(kernel, voice, OWNER, "re ! désolé, journée de dingue hier", HELLO)

    # ── mercredi ──
    await _until(kernel, at_paris(2026, 9, 30, 11, 0))
    out["regard_alice_before_apology"] = _get(kernel, affect_c.REGARD(ALICE))
    await _say(kernel, voice, ALICE, "désolée pour lundi, j'étais à cran, j'aurais pas dû", APOLOGY)
    out["regard_alice_after_apology"] = _get(kernel, affect_c.REGARD(ALICE))
    await _until(kernel, at_paris(2026, 10, 1, 10, 0))
    out["hostility_alice_later"] = _get(kernel, affect_c.HOSTILITY(ALICE))
    out["journals"] = len(_events(kernel, self_c.JOURNALED.name))
    out["dreams"] = len(_events(kernel, self_c.DREAMT.name))
    out["narratives"] = len(_events(kernel, self_c.NARRATED.name))
    frame = kernel.mind.frame()
    out["esteem_rest_in_force"] = frame.env.params_of("self", frame.root).esteem_rest
    return out


def live(tmp: Path, temperament: T.Temperament) -> Lived:
    """Ces quelques jours, vécus par ce tempérament."""
    voice = Voice()
    kernel, clock, llm, _out = build(tmp, voice, start=at_paris(2026, 9, 28, 9, 30))
    doc = DOC.model_copy(update={"temperament": temperament})

    async def main() -> dict[str, Any]:
        await boot(kernel, doc)
        try:
            return await _days(kernel, voice)
        finally:
            await kernel.stop()

    measures = run_virtual(clock, main)
    block = temperament_text(temperament)
    lived = Lived(temperament, block, m=measures)
    for req in llm.calls:
        lived.roles.add(str(req.role))
        if req.persona is not None:
            lived.persona_calls.append(PersonaCall(str(req.role), req.persona.depth, block in req.persona.text))
    return lived


_NEUTRAL: dict[str, Lived] = {}


def neutral(tmp: Path) -> Lived:
    """La même vie au milieu partout — une seule fois pour les trois fichiers."""
    if "neutre" not in _NEUTRAL:
        _NEUTRAL["neutre"] = live(tmp, T.Temperament())
    return _NEUTRAL["neutre"]


def profile(key: str) -> T.Temperament:
    return T.apply_profile(T.Temperament(), key)


def assert_her_temperament_everywhere(lived: Lived) -> None:
    """Chaque appel qui porte sa persona porte aussi le bloc de son tempérament ; ses voix principales y sont (sa
    réponse, son journal, ses rêves), et la persona compacte aussi (un murmure, une séance de travail)."""
    assert lived.persona_calls, "aucun appel n'a porté sa persona"
    missing = [c for c in lived.persona_calls if not c.carries]
    assert missing == [], f"sa persona sans son tempérament : {missing}"
    roles = {c.role for c in lived.persona_calls}
    assert {"reply", "initiative", "journal", "dream", "narrative"} <= roles, roles
    assert any(c.depth == "compact" for c in lived.persona_calls), roles
