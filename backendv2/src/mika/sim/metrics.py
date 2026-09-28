"""Les mesures d'une course, calculées après coup sur le journal."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.kernel.clock import US
from mika.sim.world import Driver


def log_metrics(events: Sequence[Any], driver: Driver) -> dict[str, Any]:
    perceptions = {e.seq: e for e in events if e.type.name == rt.PERCEPTION_RECEIVED.name}
    utterances = [e for e in events if e.type.name == rt.UTTERANCE.name]
    ended = [e for e in events if e.type.name == rt.EPISODE_ENDED.name]
    started = [e for e in events if e.type.name == rt.EPISODE_STARTED.name]
    replies: dict[int, list[Any]] = defaultdict(list)
    for u in utterances:
        if u.data.reply_to is not None:
            replies[u.data.reply_to].append(u)
    outcomes = Counter((e.data.kind, e.data.outcome) for e in ended)
    latencies = sorted((replies[s][0].at - p.at) / US for s, p in perceptions.items() if replies.get(s))
    abandoned = {e.data.reply_to: e.data.detail for e in ended if e.data.reply_to is not None and e.data.outcome == "failed"}
    transport = driver.transport
    assert transport is not None
    heard_keys = {h.key for h in transport.heard}
    return {
        "perceptions": len(perceptions),
        "answered": sum(1 for s in perceptions if replies.get(s)),
        "answered_twice": sum(1 for v in replies.values() if len(v) > 1),
        "unanswered": sorted(s for s in perceptions if not replies.get(s) and s not in abandoned),
        "abandoned": abandoned,
        "latency_max_s": latencies[-1] if latencies else None,
        "latency_median_s": latencies[len(latencies) // 2] if latencies else None,
        "initiatives_started": sum(1 for e in started if e.data.kind == "INITIATIVE"),
        "initiatives_said": sum(1 for u in utterances if u.data.kind == "INITIATIVE"),
        "greetings": sum(1 for e in started if e.data.kind == "INITIATIVE" and "greeting" in e.data.reason.split(",")),
        "outcomes": {f"{k}:{o}": n for (k, o), n in sorted(outcomes.items())},
        "utterances": len(utterances),
        "heard": len(transport.heard),
        "undelivered_online": sum(1 for u in utterances if u.id not in heard_keys and u.data.visible
                                  and u.data.target in driver.online),
        "repeats": transport.repeats,
        "transport_failures": transport.failures,
        "crashes": driver.crashes,
        "boots": driver.boots,
    }


def thread_consistent(driver: Driver, events: Sequence[Any]) -> tuple[bool, str]:
    """La projection du fil est-elle exactement le pli du journal ?"""
    assert driver.kernel is not None
    expected = {e.seq for e in events if e.type.name == rt.PERCEPTION_RECEIVED.name}
    expected |= {e.seq for e in events if e.type.name == rt.UTTERANCE.name and e.data.visible}
    rows = {r[0] for r in driver.kernel.mind.store.query_mind(f"SELECT id FROM {transcript_c.THREAD_TABLE}")}
    missing, extra = expected - rows, rows - expected
    return not missing and not extra, f"manquants {sorted(missing)[:5]}, en trop {sorted(extra)[:5]}"
