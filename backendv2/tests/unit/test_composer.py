"""Preuve M0 — composeur : zone stable identique à l'octet quand l'humeur
change, coupe de l'historique avec hystérésis, section trop sensible bloquée."""

from __future__ import annotations

from mika.kernel.faculty import SectionSpec, Zone
from mika.kernel.prompt import Budget, ChatTurn, Composer, SectionBody


def spec(key: str, zone: Zone, *, rank: int = 50, floor: int = 0, tags=(), title=None) -> SectionSpec:
    return SectionSpec("toy", key, zone, frozenset({"REPLY"}), lambda *a: None, trim_rank=rank,
                       floor_chars=floor, tags=frozenset(tags), title=title)


PERSONA = spec("persona", Zone.STABLE, title="QUI TU ES")
MOOD = spec("mood", Zone.VOLATILE, title="TON HUMEUR", tags=("affective",))
SECRET = spec("secret", Zone.VOLATILE, title="CONFIDENCE")
HISTORY = spec("history", Zone.HISTORY)


def test_stable_zone_is_byte_identical_while_mood_changes():
    c = Composer()
    budget = Budget(max_tokens=4000)
    hashes = set()
    volatiles = set()
    for turn in range(100):
        blocks = [
            (PERSONA, SectionBody("Tu es Mika, curieuse et chaleureuse.")),
            (MOOD, SectionBody(f"humeur n°{turn % 7} — intensité {turn / 100:.2f}")),
            (HISTORY, SectionBody(tuple(ChatTurn("user", f"message {i}", id=i + 1) for i in range(turn % 5)))),
        ]
        prompt, trace = c.compose(blocks, kind="REPLY", audience_level=0, muted_tags=frozenset(),
                                  message=f"question {turn}", budget=budget)
        hashes.add(trace.stable_hash)
        volatiles.add(prompt.system_volatile)
    assert len(hashes) == 1
    assert len(volatiles) > 1


def test_history_trim_is_hysteretic():
    c = Composer()
    budget = Budget(max_tokens=200, chars_per_token=4.0, history_share=0.8, history_low_ratio=0.5)
    turns: list[ChatTurn] = []
    firsts = []
    for i in range(1, 80):
        turns.append(ChatTurn("user" if i % 2 else "assistant", "x" * 40, id=i))
        prompt, _ = c.compose([(PERSONA, SectionBody("Mika.")), (HISTORY, SectionBody(tuple(turns[-60:])))],
                              kind="REPLY", audience_level=0, muted_tags=frozenset(), message="?",
                              budget=budget, thread_key="alice")
        firsts.append(prompt.history[0].id if prompt.history else None)
    changes = sum(1 for a, b in zip(firsts, firsts[1:], strict=False) if a != b)
    # Sans hystérésis, le premier tour conservé bougerait à chaque nouveau message.
    assert changes < len(firsts) / 3, (changes, firsts)


def test_confidence_blocked_for_lower_audience_and_affect_muted_in_work_mode():
    c = Composer()
    blocks = [
        (PERSONA, SectionBody("Mika.")),
        (SECRET, SectionBody("Léa part à Reykjavik", level=2)),
        (MOOD, SectionBody("joyeuse")),
    ]
    prompt, trace = c.compose(blocks, kind="REPLY", audience_level=1, muted_tags=frozenset({"affective"}),
                              message="?", budget=Budget(max_tokens=2000))
    assert "Reykjavik" not in prompt.system_volatile + prompt.system_stable
    assert ("secret", "trop sensible pour l'audience") in trace.dropped
    assert "joyeuse" not in prompt.system_volatile
    prompt2, _ = c.compose(blocks, kind="REPLY", audience_level=2, muted_tags=frozenset(),
                           message="?", budget=Budget(max_tokens=2000))
    assert "Reykjavik" in prompt2.system_volatile


def test_volatile_trim_by_rank_with_floor():
    c = Composer()
    low = spec("low", Zone.VOLATILE, rank=10, title="BAS")
    high = spec("high", Zone.VOLATILE, rank=90, floor=100, title="HAUT")
    blocks = [(PERSONA, SectionBody("Mika.")), (low, SectionBody("a" * 3000)), (high, SectionBody("b" * 3000))]
    prompt, trace = c.compose(blocks, kind="REPLY", audience_level=0, muted_tags=frozenset(),
                              message="?", budget=Budget(max_tokens=900, chars_per_token=4.0))
    assert "low" in trace.trimmed or ("low", "hors budget") in trace.dropped
    assert "b" * 100 in prompt.system_volatile
