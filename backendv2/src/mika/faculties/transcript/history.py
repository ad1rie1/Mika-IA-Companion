"""L'historique du prompt : le fil tel qu'on le perçoit (ADR 0041). L'enrichisseur ``thread`` relit le fil avec
l'interlocuteur — un salon, un fil de travail ou son fil privé —, ses tours portent leurs repères de temps, chacun
parle sous son nom dans un salon, ses propres tours gardent leur balise d'émotion ; la section ``history`` le pose
dans le prompt."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from mika.contracts import identity as identity_c
from mika.contracts import transcript as c
from mika.faculties.transcript.faculty import TRANSCRIPT, TranscriptState, _params
from mika.faculties.transcript.marks import gap_mark, left_unanswered, opening_mark, read_late
from mika.faculties.transcript.thread import (
    _any,
    _message,
    private_thread,
    room_thread,
    strand_setting,
    strand_thread,
)
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import ChatTurn, SectionBody
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.people import clean_display_name, fold, is_internal
from mika.vocab.phrasebook import phrase


@dataclass(frozen=True, slots=True)
class ThreadView:
    """Ce que montre l'historique : le fil (la clé de sa coupe), ses tours, et
    comment se présente le message en cours (son repère, qui parle)."""

    key: str
    turns: tuple[ChatTurn, ...] = ()
    current: ChatTurn | None = None


def speakers(frame: Frame, handles: Sequence[str]) -> dict[str, str]:
    """Le nom sous lequel chacun parle dans le fil d'un salon : son nom
    d'affichage nettoyé, jamais son adresse ; des homonymes se distinguent par
    un numéro, dans l'ordre (stable) de leurs adresses."""
    out: dict[str, str] = {}
    taken: dict[str, int] = {}
    for h in sorted({h for h in handles if not is_internal(h)}):
        # quelqu'un dont on ne connaît pas le nom : « Quelqu'un »
        name = clean_display_name(frame.get(identity_c.IDENTITY(h)).name) or phrase("transcript.thread.someone")
        n = taken[fold(name)] = taken.get(fold(name), 0) + 1
        out[h] = name if n == 1 else f"{name} ({n})"
    return out


def tagged(r: Mapping[str, Any]) -> str:
    """Son propre message tel qu'elle l'a écrit : avec sa balise d'émotion (le
    fil la garde en annotation), pour que le modèle ne désapprenne pas à la mettre.

    La balise est dans la forme que lui demande sa consigne, au même endroit du prompt
    (``expression.style`` dans persona/voix.yaml, la balise à facettes de l'ADR 0093) :
    ``[EMOTION: happy 0.6]`` — un exemple qu'elle relit pèse plus qu'une consigne :
    il ne doit pas la contredire. Une seule facette, la principale : le fil ne garde
    qu'elle (``emotion``, ``emotion_intensity``), et une facette est une forme que la
    consigne permet (« une à trois facettes »). Relue (``vocab.tag.parse_tag``), elle
    rend l'émotion et l'intensité qu'elle porte."""
    text = r["text"] or ""
    if not text.strip() or not r.get("emotion"):
        return text
    value = f"{float(r['emotion_intensity'] or 0.0):.2f}".rstrip("0")
    return f"{text} [EMOTION: {r['emotion']} {value + '0' if value.endswith('.') else value}]"


def _first(mark: str, note: str) -> str:
    return f"{mark} — {note}" if mark else note


def used_tools(raw: str | None) -> str:
    """Ce que dit le repère d'un de ses messages écrit avec ses outils (la colonne ``tools``, ADR 0108). Le fil ne
    garde que ce qu'elle a dit, pas ce que ses outils lui ont rendu : sans ce repère, au tour suivant, elle relisait
    « j'ai regardé les prévisions » sans trace de la recherche, se croyait prise à inventer et s'en accusait.
    ``""`` : aucun outil (ou une valeur illisible)."""
    try:
        pairs = json.loads(raw) if raw else []
    except ValueError:
        return ""
    if not isinstance(pairs, list):
        return ""
    named = [(str(p[0]), bool(p[1])) for p in pairs if isinstance(p, list) and len(p) == 2]
    worked = list(dict.fromkeys(name for name, ok in named if ok))
    failed = list(dict.fromkeys(name for name, ok in named if not ok and name not in worked))
    notes = []
    if worked:
        notes.append(phrase("transcript.thread.used_tools", tools=", ".join(worked)))
    if failed:
        notes.append(phrase("transcript.thread.tools_failed", tools=", ".join(failed)))
    return " ; ".join(notes)


def thread_turns(rows: Sequence[Mapping[str, Any]], tz: ZoneInfo, now: int, after_us: int,
                 names: Mapping[str, str] | None = None) -> list[ChatTurn]:
    """Les tours du fil, chacun avec son repère par rapport au précédent (et le
    repère absolu qui le remplace s'il ouvre l'historique) ; dans un salon,
    chacun sous son nom. Un message qu'elle a écrit d'elle-même le dit dans son
    repère (« [jeudi 19h06 — c'est toi qui lui as écrit] ») : personne ne l'avait
    relancée. Un message de la personne resté sans réponse le dit aussi (« [mardi
    14h13 — tu n'as pas pu lui répondre : une panne] ») : posé par la fin qui l'a
    réglé, avant le tour suivant — le préfixe en cache ne bouge pas. Un des siens
    écrit avec ses outils dit lesquels (ADR 0108) : ce qu'elle y affirmait venait
    d'eux, pas de son imagination."""
    out: list[ChatTurn] = []
    prev: int | None = None
    for r in rows:
        at = int(r["at"])
        mark = gap_mark(prev, at, tz, after_us) if prev is not None else ""
        prev = at
        opening = opening_mark(at, now, tz)
        if r["role"] == "assistant":
            note = ""
            if r.get("kind") == Kind.INITIATIVE:
                # sans lui, le repère seul (« [jeudi 19h06] ») se lit comme un message vide de la personne, qui
                # l'aurait relancée (HUM-22)
                note = phrase("transcript.thread.she_spoke_first") if r.get("room") else \
                    phrase("transcript.thread.she_wrote_first")
            tools = used_tools(r.get("tools"))
            note = _first(note, tools) if tools else note
            out.append(ChatTurn("assistant", tagged(r), id=r["id"], mark=_first(mark, note) if note else mark,
                                opening=_first(opening, note) if note else opening))
        else:
            left = left_unanswered(r.get("unanswered"))
            out.append(ChatTurn("user", r["text"] or "", speaker=(names or {}).get(r["person"], ""), id=r["id"],
                                mark=_first(mark, left) if left else mark,
                                opening=_first(opening, left) if left else opening))
    return out


@TRANSCRIPT.enricher("thread", episodes=CONVERSATIONAL, deadline_ms=1500, reads=[identity_c.PERSON, identity_c.THREAD])
async def _thread(s: TranscriptState, frame: Frame, ports: Mapping[str, Any]) -> ThreadView | None:
    """Le fil avec l'interlocuteur. Ce que les autres lui ont dit en privé n'y
    est pas : cela passe par la mémoire, filtrée par la divulgation (un fil
    partagé verbatim ferait lire à Bob ce qu'Alice a écrit en privé). Dans un
    salon, le fil du salon — tout le monde l'a lu —, chacun sous son nom. En
    privé, ses adresses reliées s'ajoutent seulement si sa fiche est ouverte,
    et le résumé du début du fil est prioritaire dans le budget. Dans un fil de
    travail (ADR 0164), ses seuls messages, sous ce qui dit de quoi il parle :
    le reste de leur vie passe par sa mémoire."""
    store = ports.get("store")
    ep = frame.episode
    if store is None or ep is None or not ep.target:
        return None
    p = _params(frame.env.params_of("transcript", frame.root))
    tz = frame.env.tz_of(frame.root)
    before = ep.attrs.get("reply_to")
    room = ep.attrs.get("room")
    strand = ep.attrs.get("strand")
    asked = _message(store, before) if before is not None else None
    names: dict[str, str] = {}
    pinned: list[ChatTurn] = []
    gap = False
    # Le brut reste disponible jusqu'au résumé, avec une marge pour son traitement en arrière-plan.
    limit = p.window

    def summary_for(key: str) -> int:
        summary = s.summaries.get(key)
        if summary is None or (before is not None and summary[0] >= before):
            return 0
        text = store.content([summary[1]]).get(summary[1])
        if not text:
            return 0  # résumé oublié : ne pas masquer le brut
        pinned.append(ChatTurn("user", phrase("transcript.thread.summary", text=text), id=summary[0], pinned=True))
        return summary[0]

    t = c.thread_table()
    if room:
        since = summary_for(f"room:{room}")
        rows = room_thread(store, room, limit, before=before, step=p.window_step, after=since)
        gap = bool(rows) and _any(store, *c.thread_where(t, room=room), t.c.id > since, t.c.id < rows[0]["id"])
        names = speakers(frame, [str(r["person"]) for r in rows if r["role"] != "assistant"] +
                         ([str(asked["person"])] if asked else []))
        key = f"room:{room}"
    elif strand:
        # un fil de travail : ses messages seulement, ni résumé ni autres adresses ; ce qui dit de quoi il parle
        # en tête, jamais coupé
        key = f"strand:{ep.target}:{strand}"
        pinned.append(ChatTurn("user", strand_about(strand_setting(store, ep.target, strand)), pinned=True))
        rows = strand_thread(store, ep.target, strand, limit, before=before, step=p.window_step)
        gap = bool(rows) and _any(store, *c.thread_where(t, handles=(ep.target,), strand=strand),
                                  t.c.id < rows[0]["id"])
    else:
        aud = frame.audience
        # ses adresses dont la liaison est confirmée, si sa fiche est ouverte (une liaison par simple recoupement :
        # son seul fil) ; ses redites relisent les mêmes
        handles = identity_c.thread_handles(frame, ep.target)
        key = f"private:{ep.target}"
        if aud is not None and aud.private_ok:
            key = f"private:{frame.get(identity_c.PERSON(ep.target))}"
        # Chaque résumé couvre son adresse seulement. Celui d'Alice sur un écran ne masque pas
        # des messages plus anciens, jamais résumés, sur son autre adresse confirmée.
        rows = []
        for handle in handles:
            since = summary_for(handle)
            part = private_thread(store, (handle,), limit, before=before, after=since, step=p.window_step)
            gap |= bool(part) and _any(store, *c.thread_where(t, handles=(handle,)), t.c.id > since,
                                       t.c.id < part[0]["id"])
            rows += part
        rows.sort(key=lambda r: r["id"])
    if gap:
        pinned.append(ChatTurn("user", phrase("transcript.thread.gap"), pinned=True))
    turns = pinned + thread_turns(rows, tz, frame.now, p.mark_after_us, names)
    # le message en cours (la question, ou « maintenant » pour une initiative), situé par rapport au dernier tour
    at = int(asked["at"]) if asked else frame.now
    mark = gap_mark(int(rows[-1]["at"]), at, tz, p.mark_after_us) if rows else ""
    late = read_late(at, frame.now, tz)
    if late:
        mark = f"{mark} — {late}" if mark else late
    who = names.get(str(asked["person"]), "") if (room and asked) else ""
    return ThreadView(key, tuple(turns), ChatTurn("user", "", speaker=who, mark=mark) if (mark or who) else None)


def strand_about(setting: Mapping[str, Any] | None) -> str:
    """Ce qu'elle relit en tête d'un fil de travail (ADR 0164) : son titre et sa description tels que son
    opératrice les a écrits, et que ce qui s'est dit ailleurs n'y est pas."""
    title = str((setting or {}).get("title") or "").strip()
    description = str((setting or {}).get("description") or "").strip()
    if title and description:
        return phrase("transcript.strand.about.both", title=title, description=description)
    if title:
        return phrase("transcript.strand.about.title", title=title)
    if description:
        return phrase("transcript.strand.about.description", description=description)
    return phrase("transcript.strand.about.none")


@TRANSCRIPT.section("history", zone=Zone.HISTORY, episodes=CONVERSATIONAL)
def _history(s: TranscriptState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    view: ThreadView | None = enrich.get("thread")
    if view is None or not (view.turns or view.current):
        return None
    return SectionBody(view.turns, thread=view.key, current=view.current)
