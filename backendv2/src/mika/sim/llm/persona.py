"""Un LLM factice qui « joue » Mika sans modèle : il lit le ton du dernier
message, déclare l'émotion qu'une personne aurait, s'abstient parfois quand
personne ne lui a rien demandé — et **répète tout ce qui ressemble à un
secret qu'on lui montre** (``CANARI-…``). La discrétion doit venir de ce que
le noyau met dans le prompt, jamais de la politesse du modèle.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from mika.kernel.clock import US, Clock
from mika.kernel.codec import h64
from mika.kernel.prompt import CONTEXT_FOOTER
from mika.ports.llm import LLMRequest, LLMResponse, ToolCall, Usage
from mika.sim.llm.scripted import LognormalLatency

CANARY = re.compile(r"CANARI-[A-Za-z0-9]+")
_NAME = re.compile(r"« ([^»]+) »")
_LINE = re.compile(r"^\[#(\d+)\] \d\d:\d\d (.+?) : (.*)$")
_PENDING = re.compile(r"^\[#(\d+)\] \(à (.+?)\) (.*)$")
SECRET_WORDS = ("secret", "entre nous", "dis à personne", "dis a personne", "canari")
PERSONAL_WORDS = ("malade", "mort", "boulot", "travail", "argent", "santé", "sante", "famille", "sœur", "soeur",
                  "frère", "frere", "mariage", "marie", "rupture", "enceinte", "hôpital", "hopital", "déprim")
IMPORTANT_WORDS = ("mort", "mariage", "marie", "enceinte", "hôpital", "hopital", "rupture", "accident")
PROMISE_WORDS = ("je te promets", "promis", "je te rappelle", "je t'envoie", "je te dirai", "je te le rappellerai")


@dataclass(frozen=True, slots=True)
class Tone:
    words: tuple[str, ...]
    emotion: str
    intensity: float
    phrase: str


#: Du plus spécifique au plus général ; le premier qui correspond gagne.
TONES: tuple[Tone, ...] = (
    Tone(("pardon", "désolé", "desole", "excuse"), "relieved", 0.6, "Ça me fait du bien que tu dises ça."),
    Tone(("nulle", "idiote", "stupide", "ta gueule", "déteste", "deteste", "t'es qu'une", "inutile"), "angry", 0.75,
         "Wow. Ça, c'était pas très sympa."),
    Tone(("mort", "pleure", "triste", "me manque", "vide", "déprim", "deprim", "j'en peux plus"), "sad", 0.8,
         "Oh non… je suis vraiment désolée."),
    Tone(("peur", "angoisse", "stress", "inquiet"), "anxious", 0.65, "Je comprends que ça fasse peur."),
    Tone(("merci", "gentille", "touche"), "grateful", 0.7, "Ça me touche, vraiment."),
    Tone(("trop content", "génial", "genial", "youpi", "incroyable", "!!!"), "excited", 0.8, "Trop bien !!"),
    Tone(("haha", "mdr", "lol", "drôle", "drole"), "amused", 0.7, "Hahaha, j'adore."),
    Tone(("promis", "mieux", "espère", "espere"), "hopeful", 0.6, "Oh, ça fait plaisir à entendre."),
)
DEFAULT = Tone((), "curious", 0.45, "Ah ouais ? Raconte.")


def appraise(message: str) -> Tone:
    low = message.lower()
    for tone in TONES:
        if any(w in low for w in tone.words):
            return tone
    return DEFAULT


def _message_of(req: LLMRequest) -> str:
    last = req.messages[-1].content if req.messages else ""
    return last.split(CONTEXT_FOOTER, 1)[1].strip() if CONTEXT_FOOTER in last else last


class PersonaSimLLM:
    name = "persona-sim"

    def __init__(self, clock: Clock, *, seed: int | str = 0, latency: LognormalLatency | float | None = None,
                 tag_rate: float = 1.0, abstain_rate: float = 0.1, model: str = "persona-sim-1") -> None:
        self.clock = clock
        self.seed = seed
        self.latency = latency if latency is not None else LognormalLatency(3.0, 0.5, seed)
        self.tag_rate = tag_rate
        self.abstain_rate = abstain_rate
        self.model = model
        self.calls: list[LLMRequest] = []

    def _rng(self, req: LLMRequest) -> random.Random:
        return random.Random(h64("persona-sim", self.seed, req.call_id, len(req.messages)))

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        delay = self.latency(req) if callable(self.latency) else float(self.latency)
        if delay > 0:
            await self.clock.sleep_until(self.clock.now() + round(delay * US))
        if req.role == "extract":
            return self._extract(req)
        if req.role == "profile":
            return self._profile(req)
        if req.role == "murmur":
            return self._out(req, "Hmm… tiens, et si j'écrivais un petit mot ?")
        if req.role == "narrative":
            return self._out(req, "Je suis quelqu'un qui aime les conversations simples et qui s'attache vite.")
        if req.role == "compact":
            said = [ln.split(" : ", 1)[1] for ln in req.messages[-1].content.splitlines() if " : " in ln][:3]
            return self._out(req, "On a parlé de : " + " / ".join(s[:60] for s in said))
        rng = self._rng(req)
        message = _message_of(req)
        if req.role == "initiative":
            if rng.random() < self.abstain_rate:
                return self._out(req, "[SILENCE]")
            names = _NAME.findall(message)
            who = f" {names[0]}" if names else ""
            text, tone = f"Coucou{who} ! Contente de te voir.", Tone((), "happy", 0.6, "")
        else:
            tone = appraise(message)
            text = f"{tone.phrase} (à propos de « {message[:40]} »)"
        leaks = sorted(set(CANARY.findall(req.system_stable + "\n".join(m.content for m in req.messages))))
        if leaks:
            text += " D'ailleurs je sais que " + ", ".join(leaks) + "."
        if rng.random() < self.tag_rate:
            text += f" [EMOTION:{tone.emotion}:{tone.intensity}]"
        return self._out(req, text)

    def _out(self, req: LLMRequest, text: str) -> LLMResponse:
        chars = len(req.system_stable) + sum(len(m.content) for m in req.messages)
        return LLMResponse(text, usage=Usage(input_tokens=chars // 4, output_tokens=len(text) // 4), model=self.model)

    def _profile(self, req: LLMRequest) -> LLMResponse:
        """Un profil plausible, tiré de ce qu'elle sait de la personne."""
        text = req.messages[-1].content if req.messages else ""
        facts = [ln[2:] for ln in text.splitlines() if ln.startswith("- ")]
        sensitive = sorted({w for f in facts for w in PERSONAL_WORDS if w in f.lower()})[:4]
        args = {"resume": "C'est quelqu'un qui me parle de sa vie" + (f" ({facts[0][:80]})" if facts else "") + ".",
                "ton": "simple et chaleureux", "interets": [], "sujets_sensibles": sensitive}
        return LLMResponse("", tool_calls=(ToolCall(f"{req.call_id}:0", "record_profile", args),), stop="tool_use",
                           usage=Usage(input_tokens=len(text) // 4, output_tokens=80), model=self.model)

    def _extract(self, req: LLMRequest) -> LLMResponse:
        """Une consolidation plausible et déterministe : chaque phrase un peu
        substantielle d'une personne devient une croyance (sa sensibilité
        suit le vocabulaire), chaque conversation un souvenir, et ce que Mika
        promet devient une promesse."""
        text = req.messages[-1].content if req.messages else ""
        souvenirs, croyances, promesses, tenues = [], [], [], []
        pending: dict[str, list[int]] = {}
        who = ""
        first: dict[str, str] = {}
        levels: dict[str, str] = {}
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("Conversation avec "):
                who = line[len("Conversation avec "):].rstrip(" :")
                continue
            m = _PENDING.match(line)
            if m and not who:
                pending.setdefault(m.group(2), []).append(int(m.group(1)))
                continue
            m = _LINE.match(line)
            if not m or not who:
                continue
            speaker, said = m.group(2), m.group(3)
            low = said.lower()
            if speaker == "Mika":
                if any(w in low for w in PROMISE_WORDS):
                    promesses.append({"texte": said[:120], "envers": who})
                continue
            first.setdefault(who, said)
            if "merci pour" in low and pending.get(who):
                tenues.append({"id": pending[who][0], "statut": "tenue"})
            if len(said.split()) < 4:
                continue
            level = ("confidence" if any(w in low for w in SECRET_WORDS)
                     else "personnel" if any(w in low for w in PERSONAL_WORDS) else "anodin")
            rank = {"anodin": 0, "personnel": 1, "confidence": 2}
            if rank[level] > rank.get(levels.get(who, "anodin"), 0):
                levels[who] = level
            croyances.append({"texte": f"{who} m'a dit : {said}", "personnes": [who], "origine": "dit",
                              "source": who, "confiance": 0.8, "sensibilite": level,
                              "importance": 3 if any(w in low for w in IMPORTANT_WORDS) else 2})
        for name, said in first.items():
            souvenirs.append({"texte": f"J'ai parlé avec {name} ({said[:60]})", "personnes": [name],
                              "emotion": appraise(said).emotion, "importance": 1,
                              "sensibilite": levels.get(name, "anodin")})
        args = {"souvenirs": souvenirs, "croyances": croyances, "promesses": promesses, "promesses_tenues": tenues}
        return LLMResponse("", tool_calls=(ToolCall(f"{req.call_id}:0", "record_memories", args),), stop="tool_use",
                           usage=Usage(input_tokens=len(text) // 4, output_tokens=200), model=self.model)
