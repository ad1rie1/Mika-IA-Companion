"""Ce qu'elle lui a déjà envoyé : les derniers fichiers partis avec ses messages (ADR 0062).

Sans cette section, elle renvoyait la même liste à chaque « tu peux me la redonner ? » sans savoir qu'elle l'avait
déjà fait, ou proposait un fichier qu'elle venait d'envoyer. Les noms se lisent dans leurs contenus (un nom oublié
ne se dit plus) ; seulement en tête-à-tête, et seulement ce qui est réellement parti.

Le dernier texte qu'elle a écrit pour cette adresse, parti depuis moins de ``reread_hours``, s'y relit aussi (son
début, borné) : « rajoute du pain et enlève le vin » se fait sur la liste envoyée, pas sur une liste refaite de
mémoire. Ses octets se lisent dans le port : retiré ou oublié, il n'y a plus rien à lire. Plus ancien, il se relit
avec ``reread_sent_file``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import shares as c
from mika.faculties.shares.faculty import PORT, SHARES, SharesState, params_of, reread
from mika.kernel.clock import DAY, HOUR
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.vocab.days import when_fr
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.phrasebook import phrase

#: les derniers fichiers partis, au plus tant, sur tant de jours
SHOWN = 3
SHOWN_DAYS = 30
#: le dernier texte écrit, relu dans la section : au plus tant de caractères
REREAD_SHOWN_CHARS = 1_500



def _target(frame: Frame) -> str | None:
    ep = frame.episode
    return ep.target if ep is not None else None


@SHARES.enricher("sent_files", episodes=CONVERSATIONAL, deadline_ms=500)
async def _names(s: SharesState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    target = _target(frame)
    store = ports.get("store")
    if not target or store is None:
        return None
    sent = [v for v in s.sent.get(target, ()) if v.message]
    files = [v for v in sent if frame.now - v.at <= SHOWN_DAYS * DAY][-SHOWN:]
    if not files:
        return None
    fresh, text = None, None
    aud = frame.audience
    if aud is not None and not aud.public:  # lu seulement là où il peut se montrer
        window = params_of(frame).reread_hours * HOUR
        fresh = next((v for v in reversed(sent) if v.origin == c.WRITTEN and frame.now - v.at < window), None)
        text = await reread(ports.get(PORT), fresh.file, REREAD_SHOWN_CHARS) if fresh is not None else None
    if not text:
        fresh = None
    named = [*files, fresh] if fresh is not None else files
    return {"files": files, "names": store.content([v.name_ref for v in named if v.name_ref]), "fresh": fresh,
            "text": text}


@SHARES.section("sent_files", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=35,
                title=phrase("shares.sent.title"))
def _sent_section(s: SharesState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    got = enrich.get("sent_files")
    aud = frame.audience
    if not got or aud is None or aud.public:
        return None
    names: Mapping[str, str] = got.get("names") or {}
    tz = frame.env.tz_of(frame.root)
    shown = [v for v in reversed(got["files"]) if names.get(v.name_ref)]
    if not shown:
        return None
    lines = [f"- « {names[v.name_ref]} », {when_fr(v.at, frame.now, tz)}" for v in shown]
    fresh = got.get("fresh")
    fresh_name = names.get(fresh.name_ref) if fresh is not None else None
    written = bool(fresh_name) or any(v.origin == c.WRITTEN for v in shown)
    body = "\n".join(lines) + "\n" + (phrase("shares.sent.written_note") if written else phrase("shares.sent.note"))
    if fresh_name:
        # ce qu'elle a écrit elle-même, à la fin : faute de place, c'est ce qui se coupe d'abord
        body += "\n" + phrase("shares.sent.written", name=fresh_name) + "\n" + got["text"]
    return SectionBody(body, level=0)
