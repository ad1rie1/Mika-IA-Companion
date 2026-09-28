"""Le prompt comme projection.

Chaque faculté déclare des sections (clé, zone, types d'épisode, ancres
avant/après, rang de coupe, plancher, étiquettes) ; le composeur, générique :

1. filtre — type d'épisode, étiquettes coupées par l'épisode (p. ex. l'affect
   en mode travail), sensibilité au-dessus du niveau de l'audience ;
2. ordonne — l'ordre du registre (tri topologique des ancres) ;
3. budgète — coupe par rang croissant jusqu'aux planchers ; l'historique est
   coupé avec hystérésis (jusqu'à un niveau bas) pour que le préfixe en cache
   ne bouge pas à chaque tour ;
4. rend un ``ChatPrompt`` : préfixe stable, historique en vrais tours, bloc
   volatile en tête du dernier tour utilisateur.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from mika.kernel.codec import digest
from mika.kernel.faculty import SectionSpec, Zone

TRIM_MARK = " …[coupé faute de place]"
CONTEXT_HEADER = "--- ETAT INTERNE ---"
CONTEXT_FOOTER = "--- FIN ETAT INTERNE ---"
RESUME_MARKER = "(reprise de la conversation)"


@dataclass(frozen=True, slots=True)
class ChatTurn:
    role: str  # "user" | "assistant"
    content: str
    speaker: str = ""
    id: int = 0  # identifiant du message (seq) : repère stable de la coupe


@dataclass(frozen=True, slots=True)
class SectionBody:
    content: str | tuple[ChatTurn, ...]
    level: int = 0
    provenance: tuple[str, ...] = ()
    title: str | None = None


@dataclass(frozen=True, slots=True)
class ChatPrompt:
    system_stable: str
    system_volatile: str = ""
    history: tuple[ChatTurn, ...] = ()
    message: str = ""

    def chat_messages(self) -> list[dict[str, str]]:
        msgs: list[dict[str, str]] = []
        for t in self.history:
            content = t.content.strip()
            if t.role not in ("user", "assistant") or not content:
                continue
            if t.speaker:
                content = f"{t.speaker}: {content}"
            msgs.append({"role": t.role, "content": content})
        if msgs and msgs[0]["role"] == "assistant":
            msgs.insert(0, {"role": "user", "content": RESUME_MARKER})
        final = self.message
        if self.system_volatile:
            final = f"{CONTEXT_HEADER}\n{self.system_volatile}\n{CONTEXT_FOOTER}\n\n{self.message}"
        msgs.append({"role": "user", "content": final})
        return msgs

    def chars(self) -> int:
        return len(self.system_stable) + sum(len(m["content"]) for m in self.chat_messages())


@dataclass(frozen=True, slots=True)
class Budget:
    max_tokens: int
    chars_per_token: float = 3.6
    history_low_ratio: float = 0.5
    history_share: float = 0.6

    @property
    def max_chars(self) -> int:
        return int(self.max_tokens * self.chars_per_token)


class PromptBudgetError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ComposeTrace:
    included: tuple[str, ...]
    dropped: tuple[tuple[str, str], ...]
    trimmed: tuple[str, ...]
    stable_hash: str
    chars: int
    history_turns: int
    provenance: tuple[str, ...] = ()


@dataclass(slots=True)
class _Block:
    spec: SectionSpec
    body: SectionBody
    text: str = ""
    turns: tuple[ChatTurn, ...] = ()
    trimmed: bool = False


@dataclass(slots=True)
class Composer:
    header_fmt: str = "--- {title} ---"
    _history_cut: dict[str, int] = field(default_factory=dict)

    def render_block(self, spec: SectionSpec, body: SectionBody, text: str) -> str:
        title = body.title or spec.title
        if not title:
            return text
        return f"{self.header_fmt.format(title=title)}\n{text}"

    def compose(
        self,
        blocks: Sequence[tuple[SectionSpec, SectionBody]],
        *,
        kind: str,
        audience_level: int,
        muted_tags: frozenset[str],
        message: str,
        budget: Budget,
        thread_key: str = "",
    ) -> tuple[ChatPrompt, ComposeTrace]:
        kept: list[_Block] = []
        dropped: list[tuple[str, str]] = []
        for spec, body in blocks:
            if kind not in spec.episodes:
                continue
            if spec.tags & muted_tags:
                dropped.append((spec.key, "coupée pour cet épisode"))
                continue
            if body.level > audience_level:
                dropped.append((spec.key, "trop sensible pour l'audience"))
                continue
            b = _Block(spec, body)
            if isinstance(body.content, tuple):
                b.turns = body.content
            else:
                b.text = body.content.strip()
                if not b.text:
                    continue
            kept.append(b)

        stable = [b for b in kept if b.spec.zone is Zone.STABLE]
        volatile = [b for b in kept if b.spec.zone is Zone.VOLATILE]
        history = [b for b in kept if b.spec.zone is Zone.HISTORY]

        stable_text = "\n\n".join(self.render_block(b.spec, b.body, b.text) for b in stable)
        limit = budget.max_chars - len(message)
        if len(stable_text) > limit:
            raise PromptBudgetError(f"la zone stable ({len(stable_text)} car.) dépasse le budget ({limit})")

        # Historique : coupe avec hystérésis, repérée par identifiant de message
        # (la fenêtre du fil glisse ; un index ne serait pas stable).
        turns: list[ChatTurn] = [t for b in history for t in b.turns]
        hist_budget = int((limit - len(stable_text)) * budget.history_share)
        first_id = self._history_cut.get(thread_key, 0)
        cut = next((i for i, t in enumerate(turns) if t.id >= first_id), len(turns))
        if _turn_chars(turns[cut:]) > hist_budget:
            low = int(hist_budget * budget.history_low_ratio)
            cut = len(turns)
            size = 0
            for i in range(len(turns) - 1, -1, -1):
                size += len(turns[i].content) + len(turns[i].speaker) + 2
                if size > low:
                    break
                cut = i
            self._history_cut[thread_key] = turns[cut].id if cut < len(turns) else (turns[-1].id + 1 if turns else 0)
        turns = turns[cut:]

        # Zone volatile : coupe par rang croissant jusqu'aux planchers.
        trimmed: list[str] = []
        room = limit - len(stable_text) - _turn_chars(turns) - len(CONTEXT_HEADER) - len(CONTEXT_FOOTER) - 4

        def vol_size() -> int:
            return sum(len(self.render_block(b.spec, b.body, b.text)) + 2 for b in volatile)

        if vol_size() > room:
            for b in sorted(volatile, key=lambda b: (b.spec.trim_rank, b.spec.key)):
                excess = vol_size() - room
                if excess <= 0:
                    break
                floor = b.spec.floor_chars
                target = max(floor, len(b.text) - excess - len(TRIM_MARK))
                if target <= 0 and floor == 0:
                    dropped.append((b.spec.key, "hors budget"))
                    b.text = ""
                elif target < len(b.text):
                    b.text = b.text[:target].rstrip() + TRIM_MARK
                    b.trimmed = True
                    trimmed.append(b.spec.key)
            volatile = [b for b in volatile if b.text]

        volatile_text = "\n\n".join(self.render_block(b.spec, b.body, b.text) for b in volatile)
        prompt = ChatPrompt(stable_text, volatile_text, tuple(turns), message)
        provenance = tuple(p for b in kept for p in b.body.provenance)
        included = tuple(b.spec.key for b in stable + history + volatile)
        trace = ComposeTrace(
            included=included,
            dropped=tuple(dropped),
            trimmed=tuple(trimmed),
            stable_hash=digest(stable_text),
            chars=prompt.chars(),
            history_turns=len(turns),
            provenance=provenance,
        )
        return prompt, trace


def _turn_chars(turns: Sequence[ChatTurn]) -> int:
    return sum(len(t.content) + len(t.speaker) + 2 for t in turns)
