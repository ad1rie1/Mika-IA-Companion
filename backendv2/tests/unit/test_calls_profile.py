"""Le profil d'un fournisseur (Réglages › Fournisseurs, son détail) : ce qu'il a fait depuis un instant — le tout, rôle
par rôle, ses temps de réponse sur ses appels réussis (médiane, 95 %), l'attente d'un créneau, son dernier échec ; les
autres fournisseurs et les appels plus anciens n'y comptent pas."""

from __future__ import annotations

from mika.adapters.llm.calls import CallLog
from mika.adapters.llm.gateway import LLMTrace
from tests.unit.test_calls_correlation import store_at

S = 1_000_000


def trace(at: int, role: str, backend: str = "ollama", *, latency_s: float = 1.0, outcome: str = "ok",
          tokens: tuple[int, int] = (100, 10), wait_s: float = 0.0, cost: float = 0.0) -> LLMTrace:
    return LLMTrace(at=at, role=role, backend=backend, model="m", lane="conversation", priority=0,
                    latency_us=int(latency_s * S), wait_us=int(wait_s * S), input_tokens=tokens[0],
                    output_tokens=tokens[1], outcome=outcome, call_id=f"c{at}", cost_usd=cost)


async def test_a_backend_profile_counts_its_own_recent_calls(tmp_path):
    store = store_at(tmp_path)
    await store.open()
    calls = CallLog(store)
    await calls.open()
    for t in (trace(5, "reply", latency_s=9.0),  # trop ancien
              trace(100, "reply", latency_s=1.0, wait_s=1.0, cost=0.5), trace(110, "reply", latency_s=2.0),
              trace(120, "reply", latency_s=3.0), trace(130, "extract", latency_s=4.0, tokens=(1000, 50)),
              trace(140, "extract", latency_s=30.0, outcome="timeout"), trace(150, "reply", "claude", latency_s=7.0)):
        calls.record(t)
    await calls.flush()
    got = calls.profile("ollama", since=50)
    assert got is not None and got.total.calls == 5 and got.total.failures == 1
    assert got.total.input_tokens == 100 * 4 + 1000 and got.total.cost_usd == 0.5
    assert [(u.key, u.calls, u.failures) for u in got.by_role] == [("reply", 3, 0), ("extract", 2, 1)]
    # les temps de réponse : sur les appels réussis seulement (l'échec à 30 s n'y entre pas)
    assert got.median_s == 3.0
    assert got.slow_s == 4.0 and got.wait_avg_s == 0.2
    assert got.last_failure_at == 140 and got.last_failure_role == "extract"
    assert calls.profile("ollama", since=1_000) is None  # rien depuis
    assert calls.profile("personne", since=0) is None
    await store.close()
