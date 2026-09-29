"""Lire les messages à leur arrivée : revendications, démentis, recoupements."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from mika.contracts import identity as c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.identity import corroboration
from mika.faculties.identity.detection import detect
from mika.faculties.identity.faculty import (
    IDENTITY,
    Claim,
    IdentityState,
    _name_of,
    handles_of,
    resolve_target,
)
from mika.kernel.events import Draft
from mika.kernel.frame import Frame
from mika.vocab import privacy
from mika.vocab.people import is_identifiable, same_name
from mika.vocab.privacy import ChannelTrust


def _candidates(store: Any, s: IdentityState, person: str) -> list[corroboration.Candidate]:
    """Ce que seule ``person`` pouvait savoir (voir ``corroboration``)."""
    own = set(handles_of(s, person)) | {person}
    rows = store.query_mind(
        f"SELECT id, text, sources FROM {memory_c.ITEMS_TABLE} WHERE about LIKE ? AND sensitivity >= ? "
        "AND status='active' AND kind IN (?, ?) ORDER BY id", (f'%"{person}"%', int(privacy.Sensitivity.PERSONAL),
                                                               memory_c.SOUVENIR, memory_c.BELIEF))
    if not rows:
        return []
    sources = {int(i): [int(x) for x in json.loads(src or "[]")] for i, _t, src in rows}
    wanted = sorted({x for xs in sources.values() for x in xs})
    origin: dict[int, tuple[str, str | None]] = {}
    for start in range(0, len(wanted), 500):
        chunk = wanted[start:start + 500]
        marks = ",".join("?" * len(chunk))
        for mid, who, room in store.query_mind(
                f"SELECT id, person, room FROM {transcript_c.THREAD_TABLE} WHERE id IN ({marks})", tuple(chunk)):
            origin[int(mid)] = (who, room)
    ids = [int(i) for i, _t, _s in rows]
    marks = ",".join("?" * len(ids))
    told = store.query_mind(f"SELECT item, handle FROM {memory_c.TOLD_TABLE} WHERE item IN ({marks})", tuple(ids))
    retold = {int(item) for item, handle in told if handle not in own}
    out = []
    for i, text, _src in rows:
        srcs = sources[int(i)]
        first_hand = bool(srcs) and all(x in origin and origin[x][0] in own and origin[x][1] is None for x in srcs)
        if first_hand and int(i) not in retold:
            out.append(corroboration.Candidate(int(i), text))
    return out


@IDENTITY.interpret(rt.PERCEPTION_RECEIVED)
def _read(s: IdentityState, frame: Frame, ev: Any, ports: Mapping[str, Any]) -> list[Draft[Any]]:
    d = ev.data
    h = s.handles.get(d.handle)
    if h is None or h.authenticated or not is_identifiable(d.handle):
        return []
    text = d.text.text or ""
    found = detect(text)
    drafts: list[Draft[Any]] = []
    if found.denial:
        drafts.append(c.EVIDENCE.draft(handle=d.handle, kind=c.DENIED, name=found.denial, message=ev.seq))
    claim = h.claim
    if found.claim and not (h.person and same_name(found.claim, h.name)):
        target = resolve_target(s, d.handle, found.claim)
        drafts.append(c.CLAIMED.draft(handle=d.handle, name=found.claim, target=target, message=ev.seq,
                                      public=bool(d.public or d.room)))
        if target in (None, d.handle):
            claim = None
        else:
            claim = Claim(found.claim, target, 0.0, ev.at)
    # un recoupement ne se cherche qu'en privé, sur un compte qui se prouve
    if (claim is not None and claim.target and claim.target != d.handle and not d.public and d.room is None
            and h.trust is ChannelTrust.ACCOUNT and c.SHARED_MEMORY not in claim.used):
        store = ports.get("store")
        if store is not None:
            hit = corroboration.corroborating(text, _candidates(store, s, claim.target),
                                              names=(claim.name, _name_of(s, claim.target), h.name))
            if hit is not None:
                drafts.append(c.EVIDENCE.draft(handle=d.handle, kind=c.SHARED_MEMORY, item=hit.id,
                                               message=ev.seq))
    return drafts
