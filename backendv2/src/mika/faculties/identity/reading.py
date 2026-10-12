"""Lire les messages à leur arrivée : revendications, démentis, recoupements.

Un recoupement se gagne en deux temps, jamais dans le message où elle se
présente : un premier souvenir recoupé est noté (``SHARED_HINT``, sans poids),
un second, sur un autre message au moins ``proof_spacing_us`` plus tard et sur
un autre souvenir, le confirme (``SHARED_MEMORY``) — pourvu que l'un des deux
s'appuie sur un détail rare. La revendication s'éteint au bout de son délai :
une revendication éteinte ne se recoupe plus.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select

from mika.contracts import identity as c
from mika.contracts import memory as memory_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.identity import corroboration
from mika.faculties.identity.detection import detect
from mika.faculties.identity.faculty import (
    IDENTITY,
    Claim,
    Handle,
    IdentityState,
    _name_of,
    _params,
    aims_elsewhere,
    denial_target,
    handles_of,
    live_claim,
    resolve_target,
)
from mika.kernel.events import Content, Draft
from mika.kernel.frame import Frame
from mika.vocab import privacy
from mika.vocab.people import is_identifiable, same_name
from mika.vocab.privacy import ChannelTrust


def _candidates(store: Any, s: IdentityState, person: str,
                exclude: frozenset[int] = frozenset()) -> list[corroboration.Candidate]:
    """Ce que seule ``person`` pouvait savoir (voir ``corroboration``)."""
    own = set(handles_of(s, person)) | {person}
    v = memory_c.KNOWLEDGE
    rows = store.query_mind(
        select(v.c.id, v.c.text, v.c.sources)
        .where(memory_c.concerning(v, [person]), v.c.sensitivity >= int(privacy.Sensitivity.PERSONAL),
               v.c.status == "active", v.c.kind.in_([memory_c.SOUVENIR, memory_c.BELIEF])).order_by(v.c.id))
    rows = [r for r in rows if int(r[0]) not in exclude]
    if not rows:
        return []
    sources = {int(i): [int(x) for x in json.loads(src or "[]")] for i, _t, src in rows}
    wanted = sorted({x for xs in sources.values() for x in xs})
    origin: dict[int, tuple[str, str | None]] = {}
    t = transcript_c.thread_table()
    for start in range(0, len(wanted), 500):
        chunk = wanted[start:start + 500]
        for mid, who, room in store.query_mind(select(t.c.id, t.c.person, t.c.room).where(t.c.id.in_(chunk))):
            origin[int(mid)] = (who, room)
    ids = [int(i) for i, _t, _s in rows]
    r = memory_c.RETOLD
    told = store.query_mind(select(r.c.item, r.c.handle).where(r.c.item.in_(ids)))
    retold = {int(item) for item, handle in told if handle not in own}
    out = []
    for i, text, _src in rows:
        srcs = sources[int(i)]
        first_hand = bool(srcs) and all(x in origin and origin[x][0] in own and origin[x][1] is None for x in srcs)
        if first_hand and int(i) not in retold:
            out.append(corroboration.Candidate(int(i), text))
    return out


def _corpus(store: Any) -> list[str]:
    """Sa mémoire vivante (les plus récents d'abord, bornée) : la rareté d'un mot s'y mesure."""
    v = memory_c.KNOWLEDGE
    rows = store.query_mind(select(v.c.text).where(v.c.status == "active",
                                                   v.c.kind.in_([memory_c.SOUVENIR, memory_c.BELIEF]))
                            .order_by(v.c.id.desc()).limit(corroboration.CORPUS_MAX))
    return [str(r[0]) for r in rows]


def _corroborate(s: IdentityState, frame: Frame, ev: Any, h: Handle, claim: Claim, text: str,
                 store: Any) -> Draft[Any] | None:
    """Un souvenir recoupé : la première moitié d'une preuve, ou sa seconde."""
    d = ev.data
    hinted = frozenset(x.item for x in claim.hints)
    target = claim.target or ""
    hit = corroboration.corroborating(text, _candidates(store, s, target, hinted),
                                      names=(claim.name, _name_of(s, target), h.name), corpus=_corpus(store))
    if hit is None:
        return None
    spacing = _params(frame.env.params_of("identity", frame.root)).proof_spacing_us
    rare = bool(hit.rare)
    earlier = [x for x in claim.hints if x.item != hit.id and x.message != ev.seq and ev.at - x.at >= spacing]
    complete = bool(earlier) and (rare or any(x.rare for x in earlier))
    return c.EVIDENCE.draft(handle=d.handle, kind=c.SHARED_MEMORY if complete else c.SHARED_HINT, item=hit.id,
                            message=ev.seq, rare=rare, about=(target,))


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
        # un démenti ne compte que contre un nom sous lequel elle connaît la personne ;
        # le nom démenti est gardé à part (l'oubli l'atteint), ce qu'il vise est jugé ici
        denies = denial_target(h, found.denial, frame.now, _name_of(s, h.person) if h.person else "")
        if denies:
            about = (h.person,) if denies == c.DENIES_BINDING and h.person else \
                ((h.claim.target,) if denies == c.DENIES_CLAIM and h.claim and h.claim.target else ())
            drafts.append(c.EVIDENCE.draft(handle=d.handle, kind=c.DENIED, denies=denies, message=ev.seq,
                                           name=Content.of(found.denial, level=int(privacy.Sensitivity.ANODYNE)),
                                           about=tuple(a for a in about if a and a != d.handle)))
    if found.claim and not (h.person and same_name(found.claim, h.name)):
        target = resolve_target(s, d.handle, found.claim)
        drafts.append(c.CLAIMED.draft(handle=d.handle, name=found.claim, target=target, message=ev.seq,
                                      public=bool(d.public or d.room)))
    if found.claim:
        return drafts  # jamais de recoupement dans le message où elle se présente
    claim = live_claim(h, frame.now)
    # un recoupement ne se cherche qu'en privé, sur un compte qui se prouve, pour une revendication vivante
    if (claim is None or not aims_elsewhere(h, d.handle, claim) or d.public or d.room is not None
            or h.trust is not ChannelTrust.ACCOUNT or c.SHARED_MEMORY in claim.used):
        return drafts
    store = ports.get("store")
    if store is None:
        return drafts
    draft = _corroborate(s, frame, ev, h, claim, text, store)
    if draft is not None:
        drafts.append(draft)
    return drafts
