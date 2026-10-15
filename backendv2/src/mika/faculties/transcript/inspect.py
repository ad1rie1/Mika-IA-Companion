"""Ses réponses jugées par son opératrice (ADR 0113) : ce qu'on lui avait écrit, ce qu'elle a répondu, l'avis et ce
qu'elle aurait dû dire — les exemples concrets de sa voix, du plus récent au plus ancien."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from mika.contracts import transcript as c
from mika.faculties.transcript import (
    FORGOTTEN,
    INSPECT_CHARS,
    TEXT_CAP,
    TRANSCRIPT,
    TranscriptState,
    _no_store,
    _page,
    _who,
)
from mika.kernel.frame import Frame
from mika.kernel.inspect import (
    Badge,
    Block,
    Column,
    InspectContext,
    Param,
    Prose,
    Ref,
    Row,
    Table,
    Text,
    When,
)

VERDICT = Param("avis", "avis", kind="select", choices=(("", "tous"), (c.VERDICT_KO, "pas adaptées"),
                                                        (c.VERDICT_OK, "adaptées")))

COLUMNS = (Column("quand", "fit"), Column("avis", "fit"), "avec", Column("on lui avait écrit", role="body"),
           Column("sa réponse", role="body"), Column("ce qu'elle aurait dû dire", role="body"),
           Column("n°", "fit", detail=True))


def _heard(store: Any, rows: list[dict[str, Any]]) -> dict[int, str]:
    """Pour chaque réponse, le message auquel elle répondait (son texte)."""
    t = c.thread_table()
    asked = sorted({int(r["reply_to"]) for r in rows if r["reply_to"] is not None})
    if not asked:
        return {}
    return {int(i): str(text or "") for i, text in store.query_mind(select(t.c.id, t.c.text).where(t.c.id.in_(asked)))}


@TRANSCRIPT.inspect("jugees", title="Ses réponses jugées", section="fil", order=15, params=[VERDICT],
                    description="Ses réponses que tu as jugées depuis le chat, avec ce qu'elle aurait dû dire.")
def _judged(s: TranscriptState, frame: Frame, ctx: InspectContext) -> list[Block]:
    store = ctx.store
    if store is None:
        return _no_store()
    t = c.thread_table()
    wanted = str(ctx.value("avis") or "")
    clauses: list[Any] = [t.c.role == "assistant", t.c.verdict.is_not(None)]
    if wanted:
        clauses.append(t.c.verdict == wanted)
    rows, pager = _page(store, clauses, ctx.int_param("avant", 0) or None)
    heard = _heard(store, rows)
    out = []
    for r in rows:
        ok = r["verdict"] == c.VERDICT_OK
        asked = heard.get(int(r["reply_to"])) if r["reply_to"] is not None else None
        out.append(Row((
            When(r["at"]), Badge("adaptée", "ok") if ok else Badge("pas adaptée", "warn"), _who(frame, r["person"]),
            Text((asked or "—")[:TEXT_CAP], clamp=INSPECT_CHARS),
            Text((r["text"] or FORGOTTEN)[:TEXT_CAP], clamp=INSPECT_CHARS),
            Text(r["verdict_note"] or "—", clamp=INSPECT_CHARS),
            Ref("event", str(r["id"]), str(r["id"])),
        ), href=Ref.why(int(r["id"])), detail=(Prose(r["text"] or FORGOTTEN, title="Sa réponse", reading=True),)))
    return [Table(COLUMNS, tuple(out), title="Ses réponses jugées", pager=pager, layout="feed",
                  link_label="Pourquoi cette réponse ?", filters=("avis",),
                  empty="aucune réponse jugée : dans le chat, 👍 ou 👎 sous une de ses réponses")]
