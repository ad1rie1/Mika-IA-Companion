"""Le plugin ``imaging`` : ses réglages, sa tranche, ses réducteurs (ADR 0063).

La tranche garde chaque dessin demandé (``Job``) : pour qui, ce qu'on attend (proportion, qualité), où il en est
— en cours, prêt, montré, raté, raté et dit. Un dessin est **montré** quand un message l'emporte (ses octets
partent avec, ``Utterance.attachments``), qu'il vienne de l'initiative due ou d'une réponse ; un échec est **dit**
quand l'initiative qui le porte a parlé, ou qu'elle a répondu à la personne pendant qu'elle le savait.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict

from mika.contracts import imaging as c
from mika.contracts import runtime as rt
from mika.kernel.clock import DAY, HOUR
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.frame import Frame
from mika.kernel.state import FrozenDict
from mika.vocab.episodes import Kind

#: les dessins gardés en mémoire (les plus anciens, finis, partent d'abord)
JOBS_KEPT = 200
#: un sujet d'épisode qui porte un dessin (``dessin:<job>``)
SUBJECT_PREFIX = "dessin:"
QUALITIES = (("draft", "brouillon (≈ 2 min)"), ("normal", "normale (≈ 5 min)"), ("high", "haute (≈ 10 min)"))


class ImagingParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    default_quality: Annotated[Literal["draft", "normal", "high"], Knob(
        label="Qualité par défaut", group="Dessiner", choices=QUALITIES,
        help="Quand on ne demande rien de particulier. La qualité haute n'est prise que si on la demande "
             "expressément. Les durées valent pour le serveur local (une RTX 3060) ; un service hébergé va plus "
             "vite.")] = "draft"
    allow_high: Annotated[bool, Knob(
        label="Accepter la qualité haute", group="Dessiner",
        help="Quand quelqu'un la demande. Décoché : elle dessine au plus en qualité normale.")] = True
    per_day: Annotated[int, Knob(
        label="Dessins par personne et par jour", group="Dessiner", lo=0, hi=100,
        help="Pour qui n'est pas sa propriétaire (elle, sans limite), sur 24 heures glissantes. 0 : elle ne "
             "dessine que pour sa propriétaire.")] = 5
    max_waiting: Annotated[int, Knob(
        label="Dessins en cours par personne", group="Dessiner", lo=1, hi=10,
        help="Au-delà, elle finit d'abord ceux qu'elle a commencés.")] = 2
    look: Annotated[bool, Knob(
        label="Regarder son dessin", group="Dessiner",
        help="Une fois prêt, elle le fait décrire (rôle « décrire une image ») pour pouvoir en parler sans "
             "l'avoir sous les yeux. Un appel de modèle de plus par dessin.")] = True
    deliver_evidence: Annotated[float, Knob(
        label="Preuve d'un dessin prêt", group="Montrer", lo=0.0, hi=17.0, step=0.5,
        help="Au-dessus du seuil d'initiative (9) pour le montrer dès qu'il est prêt, sous la barre de réveil (15) "
             "pour attendre qu'elle se réveille.")] = 12.0
    too_late_us: Annotated[int, Knob(
        label="Plus la peine de le montrer après", group="Montrer", lo=HOUR, hi=30 * DAY,
        help="Un dessin resté sans occasion d'être montré (personne de joignable) n'est plus annoncé passé ce "
             "délai ; il reste dans la console.")] = 3 * DAY


def params(p: ImagingParams | None) -> ImagingParams:
    return p if p is not None else ImagingParams()


def params_of(frame: Frame) -> ImagingParams:
    return params(frame.env.params_of(c.OWNER, frame.root))


@dataclass(frozen=True, slots=True)
class Job:
    job: str
    target: str
    person: str
    at: int
    aspect: str
    quality: str
    adult: bool
    owner: bool
    prompt_ref: str
    status: str = c.WAITING
    file: str = ""
    done_at: int = 0
    outcome: str = ""
    name_ref: str = ""
    caption_ref: str = ""
    reason_ref: str = ""
    backend: str = ""
    seconds: float = 0.0
    cost_usd: float = 0.0
    #: le message qui l'a montré (``seq``)
    message: int = 0

    @property
    def finished(self) -> bool:
        return self.status in (c.SHOWN, c.TOLD)


@dataclass(frozen=True, slots=True)
class ImagingState:
    jobs: FrozenDict[str, Job] = field(default_factory=FrozenDict)
    #: l'épisode (corrélation) qui montre ou dit un dessin → (dessin, but)
    running: FrozenDict[str, tuple[str, str]] = field(default_factory=FrozenDict)


IMAGING = Faculty(c.OWNER, state=ImagingState, init=lambda p: ImagingState(), params=ImagingParams)
IMAGING.declare(*c.ALL)
IMAGING.bundle(c.BUNDLE, "dessiner pour la personne (une image qui prend quelques minutes), montrer un dessin prêt")


def _set(s: ImagingState, j: Job) -> ImagingState:
    jobs = s.jobs.set(j.job, j)
    if len(jobs) > JOBS_KEPT:  # les plus anciens finis s'en vont d'abord
        old = sorted((x for x in jobs.values() if x.finished or x.status == c.MISSED), key=lambda x: x.at)
        for x in old[:len(jobs) - JOBS_KEPT]:
            jobs = jobs.delete(x.job)
    return replace(s, jobs=jobs)


@IMAGING.reducer(c.REQUESTED)
def _requested(s: ImagingState, e: Any, cx: Any) -> ImagingState:
    d = e.data
    if d.job in s.jobs:
        return s
    return _set(s, Job(job=d.job, target=d.target, person=d.person or d.target, at=e.at, aspect=d.aspect,
                       quality=d.quality, adult=d.adult, owner=d.owner, prompt_ref=d.prompt.ref or ""))


@IMAGING.reducer(c.DRAWN)
def _drawn(s: ImagingState, e: Any, cx: Any) -> ImagingState:
    d = e.data
    j = s.jobs.get(d.job)
    if j is None or j.status != c.WAITING:
        return s
    return _set(s, replace(j, status=c.READY, file=d.file, done_at=e.at, name_ref=d.name.ref or "",
                           caption_ref=(d.caption.ref or "") if d.caption is not None else "", backend=d.backend,
                           seconds=d.seconds, cost_usd=d.cost_usd))


@IMAGING.reducer(c.FAILED)
def _failed(s: ImagingState, e: Any, cx: Any) -> ImagingState:
    d = e.data
    j = s.jobs.get(d.job)
    if j is None or j.status != c.WAITING:
        return s
    return _set(s, replace(j, status=c.MISSED, done_at=e.at, outcome=d.outcome,
                           reason_ref=(d.reason.ref or "") if d.reason is not None else ""))


@IMAGING.reducer(rt.EPISODE_STARTED)
def _started(s: ImagingState, e: Any, cx: Any) -> ImagingState:
    """Une initiative qui porte un dessin (``dessin:<job>``) : son message le montrera, ou dira qu'il a raté."""
    d = e.data
    if d.kind != Kind.INITIATIVE or not d.subject or not d.subject.startswith(SUBJECT_PREFIX):
        return s
    job = d.subject.removeprefix(SUBJECT_PREFIX)
    purpose = c.COULD_NOT if c.COULD_NOT in d.reason.split(",") else c.DELIVER
    return replace(s, running=s.running.set(e.correlation, (job, purpose))) if job in s.jobs else s


@IMAGING.reducer(rt.UTTERANCE)
def _uttered(s: ImagingState, e: Any, cx: Any) -> ImagingState:
    """Un message qui emporte un dessin le montre ; l'initiative d'un échec, ou une réponse à la personne pendant
    qu'elle le savait (la section le lui disait), le dit."""
    d = e.data
    run = s.running.get(e.correlation)
    if run is not None:
        s = replace(s, running=s.running.delete(e.correlation))
    if not d.visible:
        return s
    files = set(d.attachments)
    for j in list(s.jobs.values()):
        if j.status == c.READY and j.file and j.file in files:
            s = _set(s, replace(j, status=c.SHOWN, message=e.seq))
        elif j.status == c.MISSED and ((run is not None and run == (j.job, c.COULD_NOT))
                                       or (d.target and d.target == j.target and e.at > j.done_at)):
            s = _set(s, replace(j, status=c.TOLD, message=e.seq))
    return s


@IMAGING.fact(c.STATUS)
def _status(s: ImagingState, cx: Any, job: str) -> str:
    j = s.jobs.get(job)
    return j.status if j is not None else ""


def of_person(s: ImagingState, person: str, handles: tuple[str, ...] = ()) -> list[Job]:
    """Les dessins de cette personne (par sa clé, ou l'une de ses adresses), du plus ancien au plus récent."""
    keys = {person, *handles}
    return sorted((j for j in s.jobs.values() if j.person in keys or j.target in keys), key=lambda j: (j.at, j.job))


def subject_of(job: str) -> str:
    return f"{SUBJECT_PREFIX}{job}"
