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
    # ce qui lui était adressé (dans un groupe, elle entend aussi ce qui ne l'est pas)
    perceptions = {e.seq: e for e in events if e.type.name == rt.PERCEPTION_RECEIVED.name and e.data.addressed}
    utterances = [e for e in events if e.type.name == rt.UTTERANCE.name]
    ended = [e for e in events if e.type.name == rt.EPISODE_ENDED.name]
    started = [e for e in events if e.type.name == rt.EPISODE_STARTED.name]
    # une réponse règle tout le tour de la personne (``answers``) ; un journal plus ancien, son seul ``reply_to``
    replies: dict[int, list[Any]] = defaultdict(list)
    for u in utterances:
        for s in (u.data.answers or ((u.data.reply_to,) if u.data.reply_to is not None else ())):
            replies[s].append(u)
    outcomes = Counter((e.data.kind, e.data.outcome) for e in ended)
    latencies = sorted((replies[s][0].at - p.at) / US for s, p in perceptions.items() if replies.get(s))
    # ce qu'une fin a laissé sans réponse, en le disant (``unanswered``) ; avant, un échec sur ``reply_to``
    closed: dict[int, tuple[str, str]] = {}
    for e in ended:
        if e.data.unanswered is not None:
            seqs: tuple[int, ...] = e.data.unanswered
        else:
            seqs = (e.data.reply_to,) if e.data.reply_to is not None and e.data.outcome == "failed" else ()
        for s in seqs:
            closed[s] = (e.data.outcome, e.data.detail)
    abandoned = {s: detail for s, (outcome, detail) in closed.items() if outcome != "abstained"}
    transport = driver.transport
    assert transport is not None
    heard_keys = {h.key for h in transport.heard}
    return {
        "perceptions": len(perceptions),
        "answered": sum(1 for s in perceptions if replies.get(s)),
        "answered_twice": sum(1 for v in replies.values() if len(v) > 1),
        "unanswered": sorted(s for s in perceptions if not replies.get(s) and s not in closed),
        "abandoned": abandoned,
        "abstained": sorted(s for s, (outcome, _d) in closed.items() if outcome == "abstained"),
        "replies": len({u.seq for v in replies.values() for u in v}),
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
        "consolidations": sum(1 for e in events if e.type.name == "memory.consolidated"),
        "retained": sum(1 for e in events if e.type.name in ("memory.remembered", "memory.believed")),
        "reinforced": sum(1 for e in events if e.type.name == "memory.reinforced"),
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


def duplicate_items(driver: Driver) -> list[tuple[str, str]]:
    """Des éléments retenus en double (même sorte, même texte) — une panne
    entre l'appel du modèle et l'enregistrement ne doit jamais en créer."""
    assert driver.kernel is not None
    rows = driver.kernel.mind.store.query_mind(
        "SELECT kind, text, COUNT(*) FROM memory_items GROUP BY kind, text HAVING COUNT(*) > 1")
    return [(k, t) for k, t, _n in rows]
