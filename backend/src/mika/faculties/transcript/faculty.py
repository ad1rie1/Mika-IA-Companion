"""La faculté ``transcript`` : ses réglages, son état, ses réducteurs et ses faits — le dernier message de chacun
et vers chacun, les résumés des longs fils, et ce qu'en efface l'oubli d'une personne."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Annotated

from pydantic import BaseModel, ConfigDict

from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as c
from mika.faculties.transcript.marks import MARK_AFTER
from mika.kernel.builtin import SUBJECT_FORGOTTEN
from mika.kernel.clock import DAY, MINUTE
from mika.kernel.faculty import Faculty
from mika.kernel.forms import Knob
from mika.kernel.state import FrozenDict

#: Messages relus au plus pour composer l'historique (le budget coupe ensuite).
THREAD_WINDOW = 320
#: Le début de cette fenêtre avance par paquets de tant de messages.
WINDOW_STEP = 20


class TranscriptParams(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    window: Annotated[int, Knob(
        label="Messages relus pour l'historique", group="Fil", lo=5, hi=500,
        help="Combien de messages du fil (après le dernier résumé) sont relus pour composer l'historique d'un "
             "tour ; le budget du prompt en coupe ensuite le début s'il le faut.")] = THREAD_WINDOW
    window_step: Annotated[int, Knob(
        label="Le début de l'historique avance par paquets de (messages)", group="Fil", lo=1, hi=250,
        help="Le début de l'historique ne glisse pas à chaque message : il avance par paquets de tant de messages "
             "(au plus la moitié de la fenêtre), si bien que le début du prompt reste identique d'un tour à "
             "l'autre et reste en cache. 1 : il glisse à chaque message.")] = WINDOW_STEP
    mark_after_us: Annotated[int, Knob(
        label="Repère de temps après un silence de", group="Fil", lo=5 * MINUTE, hi=DAY,
        help="Dans l'historique, un message qui arrive après un tel silence est précédé d'un repère de temps "
             "(« [25 minutes plus tard] », « [plus tard, vers 17h] », « [le lendemain, mardi 14h13] ») : elle sait "
             "quand chaque chose a été dite, et depuis combien de temps on ne s'était pas parlé.")] = MARK_AFTER
    #: au-delà de tant de messages depuis le dernier résumé, le début se replie…
    compact_after: Annotated[int, Knob(
        label="Résumer au-delà de (messages)", group="Résumé des longs fils", lo=20, hi=2000,
        help="Quand le fil avec quelqu'un compte plus de messages que cela depuis son dernier résumé, son début "
             "(déjà relu par la mémoire) se replie en un résumé : un appel au modèle.")] = 120
    #: … en gardant les derniers tels quels
    keep: Annotated[int, Knob(
        label="Messages gardés tels quels", group="Résumé des longs fils", lo=10, hi=1000,
        help="Les derniers messages que le résumé laisse intacts ; un repli n'a lieu que s'il reste assez de "
             "messages à replier au-delà (ci-dessous).")] = 60
    compact_min_fold: Annotated[int, Knob(
        label="Messages à replier au moins", group="Résumé des longs fils", lo=2, hi=500,
        help="Un repli n'a lieu que s'il y a au moins tant de messages déjà relus par la mémoire à replier : pas "
             "un appel au modèle pour trois phrases.")] = 10
    compact_batch: Annotated[int, Knob(
        label="Messages repliés par appel", group="Résumé des longs fils", lo=20, hi=2000,
        help="Un appel replie au plus tant de messages, les plus anciens d'abord ; un retard se rattrape en "
             "plusieurs passages plutôt qu'en un prompt démesuré.")] = 200
    compact_retry_us: Annotated[int, Knob(
        label="Réessayer un repli après", group="Résumé des longs fils", lo=MINUTE, hi=DAY,
        help="Si l'appel au modèle échoue, le repli suivant attend ce délai : pas de rafale d'appels.")] = 10 * MINUTE
    compact_max_tokens: Annotated[int, Knob(
        label="Longueur d'un résumé (jetons)", group="Résumé des longs fils", lo=200, hi=4000,
        help="La réponse du modèle qui résume est bornée à tant de jetons.")] = 800


@dataclass(frozen=True, slots=True)
class TranscriptState:
    head: int = 0
    last_from: FrozenDict[str, int] = field(default_factory=FrozenDict)
    last_to: FrozenDict[str, int] = field(default_factory=FrozenDict)
    #: personne → (dernier message résumé, référence du texte du résumé)
    summaries: FrozenDict[str, tuple[int, str]] = field(default_factory=FrozenDict)
    #: fil → qui parlait dans ce qu'il replie, et les messages qu'il tait (ADR 0082) ; vide : un résumé d'avant
    speakers: FrozenDict[str, tuple[str, ...]] = field(default_factory=FrozenDict)
    withheld: FrozenDict[str, tuple[int, ...]] = field(default_factory=FrozenDict)


#: v2 : un résumé sait qui parlait (l'oubli de l'un l'efface) et ce qu'il tait ; un secret déclaré après coup le fait
#: refaire (ADR 0082)
TRANSCRIPT = Faculty("transcript", state=TranscriptState, init=lambda p: TranscriptState(), params=TranscriptParams,
                     state_version=2)
TRANSCRIPT.declare(c.COMPACTED, c.SUMMARY_RESET, c.JUDGED, c.STRAND_SET, c.EFFORT_SET)


def params(p: TranscriptParams | None) -> TranscriptParams:
    return p if p is not None else TranscriptParams()


@TRANSCRIPT.reducer(c.COMPACTED)
def _compacted(s: TranscriptState, e, cx) -> TranscriptState:
    d = e.data
    ref = d.summary.ref or ""
    withheld = (*s.withheld.get(d.person, ()), *d.withheld)
    return replace(s, summaries=s.summaries.set(d.person, (d.upto, ref)),
                   speakers=s.speakers.set(d.person, tuple(sorted({*s.speakers.get(d.person, ()), *d.speakers}))),
                   withheld=s.withheld.set(d.person, tuple(sorted(set(withheld)))) if withheld else s.withheld)


def _without(s: TranscriptState, person: str) -> TranscriptState:
    return replace(s, summaries=s.summaries.delete(person), speakers=s.speakers.delete(person),
                   withheld=s.withheld.delete(person))


@TRANSCRIPT.reducer(c.SUMMARY_RESET)
def _reset(s: TranscriptState, e, cx) -> TranscriptState:
    return _without(s, e.data.person)


# ── L'oubli d'une personne, l'expiration d'une inconnue de passage (audit du 2026-10-26) ──────────────


@TRANSCRIPT.reducer(SUBJECT_FORGOTTEN)
def _speaker_forgotten(s: TranscriptState, e, cx) -> TranscriptState:
    """L'oubli de quelqu'un qui parlait dans un salon efface le résumé de ce salon (son texte, déjà, par ses sujets) ;
    un résumé de salon d'avant, qui ne dit pas qui parlait, aussi — dans le doute (ADR 0082)."""
    who = e.data.subject
    for person in [p for p in s.summaries if p.startswith("room:")
                   and (who in s.speakers.get(p, ()) or not s.speakers.get(p))]:
        s = _without(s, person)
    # et le résumé de son propre fil (son texte est déjà effacé par ses sujets) ; son dernier message et le dernier
    # vers elle restent : un compte qui existe garde son fil (audit du 2026-10-26)
    return _without(s, who)


@TRANSCRIPT.reducer(identity_c.EXPIRED)
def _stranger_expired(s: TranscriptState, e, cx) -> TranscriptState:
    """Une inconnue de passage oubliée : plus de dernier message d'elle ni vers elle, plus de résumé de son fil."""
    person = e.data.person
    return replace(_without(s, person), last_from=s.last_from.delete(person), last_to=s.last_to.delete(person))


# ── Les messages reçus et dits ──────────────────────────────────────────────


@TRANSCRIPT.reducer(rt.PERCEPTION_RECEIVED)
def _received(s: TranscriptState, e, cx) -> TranscriptState:
    return replace(s, head=e.seq, last_from=s.last_from.set(e.data.handle, e.at))


@TRANSCRIPT.reducer(rt.UTTERANCE)
def _uttered(s: TranscriptState, e, cx) -> TranscriptState:
    if not e.data.visible:
        return s
    s = replace(s, head=e.seq)
    if e.data.target:
        s = replace(s, last_to=s.last_to.set(e.data.target, e.at))
    return s


@TRANSCRIPT.fact(c.LAST_FROM)
def _last_from(s: TranscriptState, cx, handle: str) -> int:
    return s.last_from.get(handle, 0)


@TRANSCRIPT.fact(c.LAST_TO)
def _last_to(s: TranscriptState, cx, handle: str) -> int:
    return s.last_to.get(handle, 0)


@TRANSCRIPT.fact(c.HEAD)
def _head(s: TranscriptState, cx) -> int:
    return s.head
