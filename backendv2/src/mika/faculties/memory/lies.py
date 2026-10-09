"""Ce qu'elle a affirmé de faux (ADR 0076).

Elle a le droit de mentir — pour botter en touche, garder ce qu'on lui a confié, ne pas blesser — et elle le marque
(``[MENSONGE: …]``, retiré du texte par ``expression.parse`` ; l'énoncé n'en garde que la place du passage faux).
Chaque mensonge devient un souvenir étiqueté (``lie``, origine ``LIED``) : ce qu'on lui a demandé et ce qu'elle a
répondu de faux, deux choses que la personne a entendues — jamais ce qu'elle cachait, que la marque pouvait dire.

Il ne ressort que devant la personne à qui elle a menti, en privé (secret, ``about`` elle seule, confié par
personne) : pour ne pas se contredire, ou pour avouer si elle le juge bon. Il ne se laisse pas deviner ailleurs (pas
de ligne vague). La gêne, elle, est une pensée (``attention``, origine ``LIE``).
"""

from __future__ import annotations

import json
from typing import Any

from mika.contracts import expression as expression_c
from mika.contracts import identity as identity_c
from mika.contracts import memory as c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.memory.faculty import LIE_MARK, MEMORY, MemoryState
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.vocab.affect import Emotion, strip_prosody
from mika.vocab.people import clean_display_name
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

#: ce qu'un souvenir de mensonge cite au plus, de la question et de sa réponse (en caractères)
QUOTE_MAX = 200
#: le poids d'un souvenir de mensonge : il compte, sans écraser ce qu'elle a vécu de marquant
LIE_IMPORTANCE = 0.5


def clip(text: str, limit: int = QUOTE_MAX) -> str:
    """Une citation : sur une ligne, bornée, sans son point final (la phrase qui la cite a le sien)."""
    text = " ".join(strip_prosody(text or "").split())
    text = text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
    return text[:-1] if text.endswith(".") and not text.endswith("..") else text


def false_part(text: str, span: str | None) -> str:
    """Le passage faux (``début:fin`` de l'annotation) ; toute la réponse si la place est illisible."""
    try:
        start, end = (int(v) for v in (span or "").split(":"))
    except ValueError:
        return text
    part = text[max(0, start):max(0, end)].strip()
    return part or text


@MEMORY.process("memory.lies", wake_on=[rt.UTTERANCE, c.REMEMBERED], lane="background", catch_up=CatchUp.ONCE,
                max_quantum_s=600)
class Lies:
    def __init__(self) -> None:
        self.skipped: set[int] = set()

    def next_due(self, state: MemoryState, frame: Frame, last_run: int | None) -> int | None:
        return frame.now if any(seq not in self.skipped for seq in state.lies) else None

    async def run(self, ctx: Any) -> None:
        state: MemoryState = ctx.state
        frame: Frame = ctx.frame
        store = ctx.ports.get("store")
        if store is None:
            return
        pending = [seq for seq in state.lies if seq not in self.skipped]
        events = {e.seq: e for e in store.get_events(pending)}
        drafts = []
        for seq in pending:
            draft = self._souvenir(frame, store, seq, events.get(seq))
            if draft is None:
                self.skipped.add(seq)  # effacé (oubli), ou plus rien à citer : rien à retenir
                continue
            drafts.append(draft)
        if drafts:
            await ctx.emit(*drafts)

    @staticmethod
    def _souvenir(frame: Frame, store: Any, seq: int, event: Any) -> Any:
        if event is None or event.type != rt.UTTERANCE.name:
            return None
        data = json.loads(event.data)
        handle = data.get("target")
        ref = (data.get("text") or {}).get("ref")
        said = store.content([ref]).get(ref) if ref else None
        if not handle or not said:
            return None
        span = next((v for k, v in data.get("annotations") or () if k == expression_c.LIE_ANNOTATION), None)
        said = clip(false_part(said, span))
        person = frame.get(identity_c.PERSON(handle)) or handle
        who = clean_display_name(frame.get(identity_c.IDENTITY(person)).name) or phrase("memory.lie.someone")
        asked = ""
        if data.get("reply_to"):
            rows = store.query_mind(f"SELECT text FROM {transcript_c.THREAD_TABLE} WHERE id=?", (data["reply_to"],))
            asked = clip(rows[0][0]) if rows and rows[0][0] else ""
        text = phrase("memory.lie.asked", who=who, asked=asked, said=said) if asked else \
            phrase("memory.lie.souvenir", who=who, said=said)
        mark = f"{LIE_MARK}:{seq}"
        level = int(Sensitivity.PERSONAL)
        return c.REMEMBERED.draft(text=Content.of(text, level=level), about=(person,), sensitivity=level,
                                  importance=LIE_IMPORTANCE, emotion=Emotion.EMBARRASSED.value, sources=(seq,),
                                  told_by=(), heard_by=(person,), secret=True, lie=True, call_id=mark,
                                  dedupe_key=mark)
