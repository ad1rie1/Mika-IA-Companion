"""Ce qu'elle sait des agendas en parlant (ADR 0309, lot 3a).

- **« SA JOURNÉE DANS SES AGENDAS »** (``agenda_day``) : en tête-à-tête avec une personne reconnue, quand elle lui
  répond ou lui écrit d'elle-même — ce qui l'attend aujourd'hui et demain dans ses agendas à elle que le tableau laisse
  lire ici (``rights.here_all``), avec ce qui est en cours maintenant : l'heure, le titre, le lieu, avec qui ; sans
  agenda à elle (son « Mon agenda » naît à son premier usage), pas de section. Bornée ;
  tout y vient du dehors : la section est citée en entier (``untrusted``). Un agenda qu'on lui partage n'est pas sa
  journée : elle le lit par ses outils quand on le lui demande. Ce qu'elle en garde suit la ligne qui l'a laissé lire
  (``floor``, ``unkept``). Ses phrases sont dans sa voix (``agenda.day``), avec la consigne courte qui l'accompagne :
  un rendez-vous décidé dans la conversation, elle peut proposer de l'ajouter, sans insister.
- **« CE QUE TU AS PROPOSÉ DANS SES AGENDAS »** (``agenda_writes``) : ses écritures pour la personne en face — ce qui
  attend un accord, et ce qui est fait, refusé ou raté (les mots du fournisseur, cités) ; ce qui est tombé parce que
  la personne a répondu elle-même, ou parce que le rendez-vous a commencé (lot 3b). Ce que son prompt lui montrait
  quand elle a parlé est réputé dit (``agenda:<proposition>``).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import social as social_c
from mika.kernel.clock import HOUR, local
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.prompt import SectionBody
from mika.plugins.agenda import (
    AGENDA,
    APPROVED,
    DONE,
    ELSEWHERE,
    EXPIRED,
    FAILED,
    FINAL,
    PROVENANCE,
    REFUSED,
    WAITING,
    AgendaState,
    Written,
)
from mika.plugins.agenda.rights import here_all
from mika.plugins.agenda.when import hm, local_span, midnight
from mika.ports.agenda import Occurrence, masked
from mika.ports.preprocess import cite, inert
from mika.vocab.access import KEEP_FLOORS
from mika.vocab.circadian import day_fr
from mika.vocab.episodes import CONVERSATIONAL
from mika.vocab.ownership import shared_with
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity
from mika.vocab.words import elided

#: au plus tant d'événements par jour, de caractères d'un titre, d'un lieu, d'un nom, de participantes nommées
DAY_SHOWN, TITLE_SHOWN, PLACE_SHOWN, NAME_SHOWN, PEOPLE_SHOWN = 12, 120, 100, 60, 4
#: ses écritures montrées au plus ; ce qui est revenu ne se dit plus passé ce délai (µs)
WRITES_SHOWN = 4
TOO_LATE = 6 * HOUR
#: les mots d'un échec, au plus
WHY_CHARS = 300
#: ce qu'on lit des facts pour savoir qui est en face et à qui le dire
READS = [identity_c.PERSON, identity_c.HANDLES, identity_c.IDENTITY, identity_c.OWNERS, identity_c.REACHABLE,
         presence_c.PRESENT, social_c.CLOSENESS]


def _line(o: Occurrence, owned: bool, tz: Any, now: int) -> str:
    """Une occurrence en une ligne : l'heure (ou « toute la journée »), son titre (« Occupé » sans), son lieu, avec qui
    — rendus inertes."""
    e = masked(o.event) if o.event.private and not owned else o.event
    title = inert(e.title, TITLE_SHOWN) if e.title.strip() else phrase("agenda.words.busy")
    if o.span.all_day:
        head = phrase("agenda.day.all_day")
    else:
        start, end = local(o.span.start, tz), local(o.span.end, tz)
        head = phrase("agenda.day.hours", start=hm(start), end=hm(end))
    parts = [head, phrase("agenda.words.title", title=title)]
    if e.location.strip():
        parts.append(phrase("agenda.words.where", place=inert(e.location, PLACE_SHOWN)))
    names = [inert(p.name or p.address or p.person, NAME_SHOWN) for p in e.participants if not p.me]
    if names:
        parts.append(phrase("agenda.words.with", who=", ".join(names[:PEOPLE_SHOWN])))
    if e.response:
        parts.append(phrase(f"agenda.words.answer.{e.response}"))
    lo, hi = local_span(o.span, tz)
    if lo <= now < hi and not o.span.all_day:
        parts.append(phrase("agenda.day.now"))
    return "- " + " · ".join(parts)


@AGENDA.enricher("agenda", episodes=CONVERSATIONAL, deadline_ms=500, reads=READS)
async def _gather(s: AgendaState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, Any] | None:
    """Ce que ses sections lisent : la journée de la personne en face (aujourd'hui et demain, dans ses agendas à elle
    que le tableau laisse lire ici) et les mots de ses écritures (leurs contenus)."""
    out: dict[str, Any] = {"day": None, "texts": {}}
    store = ports.get("agenda")
    kind = frame.episode.kind if frame.episode is not None else ""
    person = getattr(frame.audience, "person", "") or ""
    if store is not None and person and shared_with(frame.audience, kind):
        # ses agendas qui existent (son « Mon agenda » naît à son premier usage : sans agenda, pas de section)
        known = {c.key for c in store.calendars()}
        mine = {k: h for k, h in here_all(frame, sorted(known)).items() if h.owned and k in known}
        if mine:
            tz = frame.env.tz_of(frame.root)
            today = frame.local().date()
            days = [today, today + timedelta(days=1)]
            found = store.period(list(mine), midnight(today, tz), midnight(today + timedelta(days=2), tz))
            by_day: dict[date, list[str]] = {d: [] for d in days}
            for o in found:
                lo, hi = local_span(o.span, tz)
                if hi <= frame.now and not o.span.all_day:
                    continue  # déjà passé
                for d in days:
                    if lo < midnight(d + timedelta(days=1), tz) and hi > midnight(d, tz):
                        by_day[d].append(_line(o, True, tz, frame.now))
            keeps = [h.keep for h in mine.values()]
            out["day"] = {"days": [(d, by_day[d]) for d in days],
                          "floor": max((KEEP_FLOORS.get(k, 0) for k in keeps), default=0),
                          "unkept": "rien" in keeps}
    refs = [r for w in _relevant(s, frame) for r in (w.summary_ref, w.why_ref) if r]
    content = ports.get("store")
    if content is not None and refs:
        out["texts"] = content.content(refs)
    return out if out["day"] is not None or refs else None


@AGENDA.section("agenda_day", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=25,
                title=phrase("agenda.day.title"), untrusted=True, reads=READS)
def _day(s: AgendaState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Sa journée, dans ses agendas à elle : aujourd'hui et demain, ce qui est en cours maintenant (cité)."""
    got = (enrich.get("agenda") or {}).get("day")
    if not got:
        return None
    blocks = []
    for i, (d, lines) in enumerate(got["days"]):
        when = phrase("agenda.day.today", day=day_fr(d)) if i == 0 else phrase("agenda.day.tomorrow", day=day_fr(d))
        if not lines:
            blocks.append(when + " " + phrase("agenda.day.empty"))
            continue
        more = len(lines) - DAY_SHOWN
        blocks.append("\n".join([when, *lines[:DAY_SHOWN],
                                 *([phrase("agenda.day.more", n=more)] if more > 0 else [])]))
    return SectionBody("\n".join([phrase("agenda.day.head"), *blocks, phrase("agenda.day.propose")]),
                       level=int(Sensitivity.PERSONAL), witness=True, floor=got["floor"], unkept=got["unkept"])


# ── ce qu'elle a proposé d'écrire ─────────────────────────────────────────


def _handles(frame: Frame) -> set[str]:
    ep = frame.episode
    if ep is None or not ep.target:
        return set()
    person = frame.get(identity_c.PERSON(ep.target)) or ep.target
    return set(frame.get(identity_c.HANDLES(person)) or (ep.target,)) | {ep.target}


def _relevant(s: AgendaState, frame: Frame) -> list[Written]:
    handles = _handles(frame)
    if not handles:
        return []
    out = [w for w in s.writes.values() if w.target in handles
           and (w.status in (WAITING, APPROVED) or (w.status in FINAL and not w.told and frame.now - w.done_at
                                                    <= TOO_LATE))]
    return sorted(out, key=lambda w: w.proposal)[-WRITES_SHOWN:]


def _who(frame: Frame, w: Written) -> str:
    if not w.decider:
        return phrase("agenda.writes.by_operator")
    if w.decider == w.target:
        return phrase("agenda.writes.by_chat")
    person = str(frame.get(identity_c.PERSON(w.decider)) or w.decider)
    name = identity_c.person_name(frame, person) or phrase("agenda.words.someone")
    return phrase("agenda.writes.by_owner", of=elided(name, "de"))


def write_line(frame: Frame, w: Written, texts: Mapping[str, str]) -> str:
    """Où en est une écriture : ses mots à elle (son résumé) ; les mots du fournisseur d'un échec, cités dessous."""
    what = texts.get(w.summary_ref, "") or phrase("agenda.write.lost")
    if w.status == WAITING:
        return "- " + phrase("agenda.writes.waiting", what=what, who=_who(frame, w))
    if w.status == APPROVED:
        return "- " + phrase("agenda.writes.sent", what=what)
    if w.status == DONE:
        if w.edited:  # ajoutée par la personne, avec ses changements
            return "- " + phrase("agenda.writes.edited", what=what)
        return "- " + phrase("agenda.writes.done", what=what)
    if w.status == FAILED:
        why = texts.get(w.why_ref, "")
        head = "- " + phrase("agenda.writes.failed", what=what)
        return head + ("\n" + cite(why, WHY_CHARS) if why.strip() else "")
    assert w.status == REFUSED
    if w.by == ELSEWHERE:
        return "- " + phrase("agenda.writes.elsewhere", what=what)
    if w.by == EXPIRED:
        return "- " + phrase("agenda.writes.begun", what=what)
    return "- " + phrase("agenda.writes.refused", what=what)


@AGENDA.section("agenda_writes", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=20,
                title=phrase("agenda.writes.title"), reads=READS)
def _writes(s: AgendaState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    """Ce qu'elle a proposé d'écrire dans un agenda pour la personne en face, et ce que c'est devenu."""
    shown = _relevant(s, frame)
    if not shown:
        return None
    texts = (enrich.get("agenda") or {}).get("texts") or {}
    told = tuple(f"{PROVENANCE}{w.proposal}" for w in shown if w.status in FINAL)
    return SectionBody(phrase("agenda.writes.head") + "\n" + "\n".join(write_line(frame, w, texts) for w in shown),
                       level=int(Sensitivity.PERSONAL), witness=True, provenance=told)


__all__ = ["DAY_SHOWN", "WRITES_SHOWN", "write_line"]
