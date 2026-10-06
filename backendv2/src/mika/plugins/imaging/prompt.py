"""Ce qu'elle sait de ses dessins en parlant, et ce qui la pousse à les montrer (ADR 0063).

- La section « TES DESSINS » (réponse et initiative, pour la personne en face) : ce qu'elle dessine en ce moment
  pour elle (« en cours depuis 3 min »), ce qui est prêt (« montre-le avec show_drawing »), ce qui a raté (à dire).
- L'initiative due : un dessin prêt se montre (``DELIVER``), un dessin raté se dit (``COULD_NOT``) — comme un
  rappel, ce n'est pas « prendre la parole » (``agency.OWED``). Elle part vers l'adresse où la personne est
  maintenant (connectée, sinon joignable), sinon celle d'où venait la demande ; une garde l'annule si le dessin a
  été montré entre-temps (sa réponse l'a emporté).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mika.contracts import identity as identity_c
from mika.contracts import imaging as c
from mika.contracts import presence as presence_c
from mika.kernel.arbitration import Candidate
from mika.kernel.clock import MINUTE
from mika.kernel.faculty import Zone
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard, floor
from mika.kernel.prompt import SectionBody
from mika.kernel.state import FrozenDict
from mika.plugins.imaging.faculty import IMAGING, ImagingState, Job, of_person, params_of, subject_of
from mika.vocab.episodes import CONVERSATIONAL, Kind
from mika.vocab.phrasebook import phrase
from mika.vocab.privacy import Sensitivity

#: au plus tant de dessins dans la section
SHOWN_MAX = 3


def _person_of(frame: Frame) -> tuple[str, tuple[str, ...]] | None:
    ep = frame.episode
    if ep is None or not ep.target:
        return None
    person = frame.get(identity_c.PERSON(ep.target)) or ep.target
    return person, tuple(frame.get(identity_c.HANDLES(person)) or (ep.target,))


def _relevant(s: ImagingState, frame: Frame) -> list[Job]:
    who = _person_of(frame)
    if who is None:
        return []
    jobs = [j for j in of_person(s, *who) if j.status in (c.WAITING, c.READY, c.MISSED)]
    return jobs[-SHOWN_MAX:]


@IMAGING.enricher("dessins", episodes=CONVERSATIONAL, deadline_ms=300)
async def _texts(s: ImagingState, frame: Frame, ports: Mapping[str, Any]) -> dict[str, str] | None:
    store = ports.get("store")
    jobs = _relevant(s, frame)
    if store is None or not jobs:
        return None
    return store.content([r for j in jobs for r in (j.prompt_ref, j.caption_ref, j.reason_ref) if r])


def _ago(us: int) -> str:
    minutes = max(1, us // MINUTE)
    return phrase("projects.duration.minutes", n=minutes) if minutes < 120 else \
        phrase("projects.duration.hours", n=minutes // 60)


def line(j: Job, texts: Mapping[str, str], now: int) -> str:
    what = texts.get(j.prompt_ref, "")
    what = phrase("imaging.section.quoted", prompt=f"{what[:160]}{'…' if len(what) > 160 else ''}") if what else ""
    if j.status == c.WAITING:
        return "- " + phrase("imaging.section.drawing", what=what, ago=_ago(now - j.at))
    if j.status == c.READY:
        seen = texts.get(j.caption_ref, "")
        return "- " + phrase("imaging.section.ready", what=what,
                             seen=phrase("imaging.section.seen", caption=seen) if seen else "")
    reason = texts.get(j.reason_ref, "")
    return "- " + phrase("imaging.section.missed", what=what,
                         reason=phrase("imaging.section.reason", reason=reason) if reason else "")


@IMAGING.section("dessins", zone=Zone.VOLATILE, episodes=CONVERSATIONAL, trim_rank=20,
                 title=phrase("imaging.section.title"),
                 untrusted=True, reads=[identity_c.PERSON, identity_c.HANDLES])
def _section(s: ImagingState, frame: Frame, enrich: Mapping[str, Any]) -> SectionBody | None:
    jobs = _relevant(s, frame)
    if not jobs:
        return None
    texts = enrich.get("dessins") or {}
    lines = [line(j, texts, frame.now) for j in jobs]
    # ce qu'elle a demandé, pour elle-même : témoin (ce qu'on peut entendre de soi), jamais devant un salon (l'outil
    # n'y est pas offert, la section ne vise que la personne de l'épisode)
    return SectionBody(phrase("imaging.section.head") + "\n" + "\n".join(lines),
                       level=int(Sensitivity.PERSONAL), witness=True)


def _still(job: str, wanted: str) -> Guard:
    """L'épisode ne vaut que tant que le dessin est dans cet état (montré entre-temps : plus rien à faire)."""
    return Guard("dessin", predicate=lambda view, j=job, w=wanted: view.get(c.STATUS(j)) == w)


def _address(frame: Frame, j: Job) -> str:
    """Où le montrer : là où la personne est maintenant (connectée, sinon joignable), sinon d'où venait la
    demande."""
    handles = frame.get(identity_c.HANDLES(j.person)) or (j.target,)
    present = [h for h in frame.get(presence_c.PRESENT) if h in handles]
    if present:
        return present[0]
    reachable = frame.get(identity_c.REACHABLE(j.person))
    return reachable[0] if reachable else j.target


def _who(frame: Frame, j: Job) -> str:
    name = frame.get(identity_c.IDENTITY(j.person)).name if j.person else ""
    return f"« {name} »" if name else phrase("expression.person.unnamed")


@IMAGING.propose(kinds=[Kind.INITIATIVE], reasons={c.DELIVER: (0.0, 17.0), c.COULD_NOT: (0.0, 17.0)},
                 reads=[c.STATUS, identity_c.HANDLES, identity_c.REACHABLE, presence_c.PRESENT, identity_c.IDENTITY])
def _owed(s: ImagingState, frame: Frame) -> list[Candidate]:
    p = params_of(frame)
    out = []
    for j in sorted(s.jobs.values(), key=lambda j: (j.done_at, j.job)):
        if j.status not in (c.READY, c.MISSED) or frame.now - j.done_at > p.too_late_us:
            continue
        address = _address(frame, j)
        who = _who(frame, j)
        if j.status == c.READY:
            reason, brief = c.DELIVER, phrase("imaging.brief.ready", who=who)
        else:
            reason, brief = c.COULD_NOT, phrase("imaging.brief.missed", who=who)
        out.append(Candidate(
            Kind.INITIATIVE, address, reason, p.deliver_evidence, resources=frozenset({floor(address)}),
            guards=(_still(j.job, j.status),),
            args=FrozenDict({"brief:imaging": brief, "subject": subject_of(j.job), "bundles": (c.BUNDLE,)})))
    return out
