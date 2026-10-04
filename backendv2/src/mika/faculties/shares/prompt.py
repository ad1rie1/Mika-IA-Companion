"""Ce qu'elle lui a déjà envoyé : les derniers fichiers partis avec ses messages (ADR 0062).

Sans cette section, elle renvoyait la même liste à chaque « tu peux me la redonner ? » sans savoir qu'elle l'avait
déjà fait, ou proposait un fichier qu'elle venait d'envoyer. Les noms se lisent dans leurs contenus (un nom oublié
ne se dit plus) ; seulement en tête-à-tête, et seulement ce qui est réellement parti.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.faculties.shares.faculty import SHARES, SharesState
from mika.kernel.clock import DAY
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.vocab.days import when_fr
from mika.vocab.episodes import CONVERSATIONAL

#: les derniers fichiers partis, au plus tant, sur tant de jours
SHOWN = 3
SHOWN_DAYS = 30


def _target(frame: Frame) -> str | None:
    ep = frame.episode
    return ep.target if ep is not None else None


@SHARES.enricher("sent_files", episodes=CONVERSATIONAL, deadline_ms=500)
async def _names(s: SharesState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    target = _target(frame)
    store = ports.get("store")
    if not target or store is None:
        return None
    files = [v for v in s.sent.get(target, ()) if v.message and frame.now - v.at <= SHOWN_DAYS * DAY][-SHOWN:]
    if not files:
        return None
    return {"files": files, "names": store.content([v.name_ref for v in files if v.name_ref])}


@SHARES.section("sent_files", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=35,
                title="CE QUE TU LUI AS DÉJÀ ENVOYÉ")
def _sent_section(s: SharesState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("sent_files")
    aud = frame.audience
    if not got or aud is None or aud.public:
        return None
    names: Mapping[str, str] = got.get("names") or {}
    tz = frame.env.tz_of(frame.root)
    lines = [f"- « {names[v.name_ref]} », {when_fr(v.at, frame.now, tz)}" for v in reversed(got["files"])
             if names.get(v.name_ref)]
    if not lines:
        return None
    return SectionBody("\n".join(lines) + "\n(Partis avec tes messages : ne les renvoie pas, sauf si on te le "
                       "redemande.)", level=0)
