"""Se faire une idée de quelqu'un (théorie de l'esprit).

Quand assez de nouveau est su d'une personne (au plus une fois par jour), le
modèle (rôle ``profile``) relit ce qu'elle en sait — seulement ce qui ne
concerne qu'elle : un profil ne doit pas mêler ce que d'autres ont confié
sur elle — et dit qui elle est, comment lui parler, ce qui l'intéresse, ce
qui est délicat. La proximité, elle, ne se juge pas : elle se vit
(``faculty.lived``).
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mika.contracts import affect as affect_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as memory_c
from mika.contracts import social as c
from mika.faculties.social.faculty import SOCIAL, SocialState, params
from mika.kernel.clock import DAY
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.ports.llm import LLMRequest, LLMResponse, Message, ToolDecl
from mika.vocab.privacy import Sensitivity

TOOL_NAME = "record_profile"
LEVEL_FR = {c.STRANGER: "inconnue", c.ACQUAINTANCE: "une connaissance", c.FRIEND: "une amie ou un ami",
            c.CLOSE: "quelqu'un de proche"}


class XProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    resume: str = Field(min_length=3, max_length=900)
    ton: str = Field(default="", max_length=300)
    interets: list[str] = Field(default_factory=list)
    sujets_sensibles: list[str] = Field(default_factory=list)


def tool() -> ToolDecl:
    return ToolDecl(TOOL_NAME, "Enregistre ce que Mika pense de cette personne.", XProfile.model_json_schema())


SYSTEM = """Tu aides Mika à se faire une idée de quelqu'un qu'elle connaît, à partir de ce qu'elle en sait. Écris \
comme ses propres notes, à la troisième personne (« C'est quelqu'un qui… »).
- resume : qui est cette personne pour Mika, en 2 à 4 phrases ; n'invente rien, ne répète pas les détails intimes.
- ton : comment lui parler (une phrase).
- interets : ce qui l'intéresse (quelques mots chacun, au plus 6).
- sujets_sensibles : les sujets délicats avec elle ou lui (au plus 6), sinon une liste vide.
Réponds uniquement en appelant l'outil record_profile."""


def parse(resp: LLMResponse) -> XProfile | None:
    raw: Any = None
    for call in resp.tool_calls:
        if call.name == TOOL_NAME:
            raw = dict(call.args)
            break
    if raw is None:
        match = re.search(r"\{.*\}", resp.text or "", re.DOTALL)
        if not match:
            return None
        try:
            raw = json.loads(match.group(0))
        except ValueError:
            return None
    try:
        return XProfile.model_validate(raw)
    except ValidationError:
        return None


def _short(values: list[str], limit: int = 6) -> tuple[str, ...]:
    out = []
    for v in values:
        v = " ".join(str(v).split())[:60]
        if v and v not in out:
            out.append(v)
    return tuple(out[:limit])


def _due(s: SocialState, now: int, p: Any) -> list[tuple[int, str]]:
    """Les personnes dont assez de nouveau est su (les plus en retard d'abord)."""
    out = []
    for person, count in s.mentions.items():
        if person.startswith("name:"):
            continue
        profile = s.profiles.get(person)
        new = count - (profile.mentions_at if profile else 0)
        if new < p.profile_min_items:
            continue
        if profile is not None and now - profile.revised_at < p.profile_interval_us:
            continue
        out.append((-new, person))
    return sorted(out)


@SOCIAL.process("social.profile", wake_on=[memory_c.CONSOLIDATED], lane="background", catch_up=CatchUp.ONCE,
                max_quantum_s=3600)
class Revise:
    def __init__(self) -> None:
        self.retry_at = 0
        #: personne → nombre de mentions lors de la dernière tentative (rien à
        #: relire tant que ça ne bouge pas : jamais de boucle à vide)
        self.tried: dict[str, int] = {}

    def _todo(self, state: SocialState, now: int, p: Any) -> list[tuple[int, str]]:
        return [(n, person) for n, person in _due(state, now, p)
                if self.tried.get(person) != state.mentions.get(person, 0)]

    def next_due(self, state: SocialState, frame: Frame, last_run: int | None) -> int | None:
        p = params(frame.env.params_of("social", frame.root))
        if self._todo(state, frame.now, p):
            return max(frame.now, self.retry_at)
        waiting = [pr.revised_at + p.profile_interval_us for person, pr in state.profiles.items()
                   if state.mentions.get(person, 0) - pr.mentions_at >= p.profile_min_items
                   and pr.revised_at + p.profile_interval_us > frame.now]
        return min(waiting) if waiting else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: SocialState = ctx.state
        store = ctx.ports.get("store")
        if store is None or ctx.llm is None:
            return
        p = params(frame.env.params_of("social", frame.root))
        self.retry_at = frame.now + p.profile_retry_us  # si l'appel lève : pas de rafale
        for _neg, person in self._todo(state, frame.now, p)[: p.profile_per_run]:
            self.tried[person] = state.mentions.get(person, 0)
            items = store.query_mind(
                f"SELECT id, text, importance FROM {memory_c.ITEMS_TABLE} WHERE about=? AND status='active' "
                "AND kind IN (?, ?) ORDER BY importance DESC, id DESC LIMIT ?",
                (json.dumps([person], ensure_ascii=False), memory_c.SOUVENIR, memory_c.BELIEF, p.profile_max_items))
            if not items:
                continue
            prompt = self._prompt(frame, state, person, items, store)
            request = LLMRequest(role="profile", call_id=f"{ctx.run_id}#{person}", system_stable=SYSTEM,
                                 messages=(Message("user", prompt),), tools=(tool(),), max_tokens=900,
                                 lane="background", priority=3)
            response = await ctx.llm.call(request)
            got = parse(response)
            if got is None:
                continue
            await ctx.emit(c.PROFILE_REVISED.draft(
                person=person, summary=Content.of(got.resume.strip(), level=Sensitivity.PERSONAL),
                tone=got.ton.strip()[:300], interests=_short(got.interets), sensitive=_short(got.sujets_sensibles),
                upto=max(int(i) for i, _t, _imp in items), call_id=request.call_id, model=response.model))
        self.retry_at = 0

    def _prompt(self, frame: Frame, state: SocialState, person: str, items: list[tuple[Any, ...]], store: Any) -> str:
        view = frame.get(identity_c.IDENTITY(person))
        reading = frame.get(c.CONTACT(person))
        warmth = frame.get(affect_c.WARMTH(person))
        known = max(0, (frame.now - (view.first_seen or reading.first_in or frame.now)) // DAY)
        feeling = ("beaucoup de chaleur" if warmth >= 0.5 else "de la sympathie" if warmth >= 0.2
                   else "rien de particulier")
        lines = [f"Personne : {view.name or 'sans nom connu'}.",
                 f"Vous vous connaissez depuis {known} jours ; elle ou il t'a écrit {reading.inbound} messages, "
                 f"sur {reading.days} jours différents.",
                 f"Ce que Mika ressent pour elle ou lui : {feeling}."]
        previous = state.profiles.get(person)
        if previous is not None:
            text = store.content([previous.summary_ref]).get(previous.summary_ref) if previous.summary_ref else None
            if text:
                lines.append(f"Ce qu'elle en pensait jusqu'ici : {text}")
        lines.append("")
        lines.append("Ce que Mika sait d'elle ou lui :")
        lines += [f"- {text}" for _i, text, _imp in items]
        return "\n".join(lines)


def describe_level(level: str) -> str:
    return LEVEL_FR.get(level, LEVEL_FR[c.STRANGER])
