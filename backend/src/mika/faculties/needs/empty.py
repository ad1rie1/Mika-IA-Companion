"""Le vide : quand plus rien ne se passe depuis quatre heures, éveillée, elle ressent de l'ennui, ou de la solitude
quand c'est de compagnie qu'elle manque — un vide qui se creuse avec la durée (le processus ``needs.empty``) ; et le
premier message de quelqu'un qu'elle connaît, après un vide ressenti, lui fait du bien (``needs.reunited``)."""

from __future__ import annotations

from typing import Any

from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import needs as c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.faculties.needs.faculty import NEEDS, NeedsState, busy
from mika.faculties.needs.params import NeedsParams, params
from mika.kernel.clock import HOUR
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.kernel.guards import Guard
from mika.vocab import causes
from mika.vocab.affect import Appraisal, Emotion
from mika.vocab.people import is_identifiable


def empty_since(s: NeedsState, lonely: bool) -> int:
    """Depuis quand le vide court : pour l'ennui, depuis que rien ne s'est passé ; pour la solitude, depuis que
    personne ne lui a parlé, qu'elle n'a parlé à personne ni ne s'est absorbée dans son travail (ADR 0098)."""
    return (s.lonely_since or s.idle_since) if lonely else s.idle_since


def emptiness(s: NeedsState, now: int, p: NeedsParams, lonely: bool = False) -> float:
    """Ce que pèse le vide maintenant : un peu au début, davantage avec chaque
    heure qui passe, jamais plus que le plafond."""
    beyond = max(0.0, (now - empty_since(s, lonely) - p.idle_before_empty_us) / HOUR) if s.idle_since else 0.0
    return round(min(p.empty_max, p.empty_intensity + p.empty_growth_per_h * beyond), 3)


@NEEDS.process("needs.empty", wake_on=[rt.PERCEPTION_RECEIVED, rt.UTTERANCE, rt.EPISODE_STARTED, rt.EPISODE_ENDED,
                                       c.FELT, *body_c.ALL],
               catch_up=CatchUp.SKIP, max_quantum_s=3600)
class Empty:
    """Quatre heures sans rien : un vide ressenti à intervalles tant
    qu'il dure (un état tenu, pas une dent de scie), qui se creuse avec la
    durée. Travailler l'occupe : pas de vide pendant une séance (ADR 0098)."""

    def next_due(self, state: NeedsState, frame: Frame, last_run: int | None) -> int | None:
        if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE or not state.idle_since:
            return None
        if busy(state, frame.now):
            return None  # elle travaille : la fin de la séance la réveillera
        p = params(frame.env.params_of("needs", frame.root))
        lonely = frame.get(c.NEEDS).social >= p.lonely_from
        return max(empty_since(state, lonely) + p.idle_before_empty_us, state.felt_at + p.empty_every_us)

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: NeedsState = ctx.state
        if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE or busy(state, frame.now):
            return
        p = params(frame.env.params_of("needs", frame.root))
        lonely = frame.get(c.NEEDS).social >= p.lonely_from
        if frame.now - empty_since(state, lonely) < p.idle_before_empty_us:
            return
        feeling = c.LONELY if lonely else c.BORED
        await ctx.emit(c.FELT.draft(feeling=feeling, intensity=emptiness(state, frame.now, p, lonely)),
                       guard=Guard("toujours le vide", reads=(c.NEEDS,)))


@NEEDS.appraisal(c.FELT)
def _empty_felt(e, cx) -> Appraisal:
    emotion = Emotion.LONELY if e.data.feeling == c.LONELY else Emotion.BORED
    return Appraisal(emotion, e.data.intensity, reason=e.data.feeling)


@NEEDS.interpret(rt.PERCEPTION_RECEIVED)
def _reunited(s: NeedsState, frame: Frame, ev: Any, ports: Any) -> list[Any]:
    """Le premier message de quelqu'un qu'elle connaît après un vide ressenti (depuis que quelqu'un lui a parlé
    pour la dernière fois) : ça lui fait du bien, d'autant plus que le vide pesait, au cran de leur lien
    (``reunited_by_closeness``, ADR 0150). Le rendez-vous de chaque soir après une journée creuse, pas seulement le
    retour de quelqu'un qui manquait (HUM-5)."""
    d = ev.data
    if not d.addressed or not is_identifiable(d.handle) or s.heard_at != ev.at:
        return []
    if not s.felt or s.felt_at <= s.heard_before:
        return []  # pas de vide ressenti depuis la dernière fois qu'on lui a parlé
    if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
        return []  # un message de nuit attend son réveil : ce n'est pas un moment partagé
    person = frame.get(identity_c.PERSON(d.handle))
    p = params(frame.env.params_of("needs", frame.root))
    share = p.reunited_by_closeness.get(frame.get(social_c.CLOSENESS(person)), 0.0)
    intensity = round(min(1.0, p.reunited_gain * s.felt_level * share), 3)
    if intensity <= 0:
        return []
    return [c.REUNITED.draft(person=person, handle=d.handle, message=ev.seq, after=s.felt, intensity=intensity)]


@NEEDS.appraisal(c.REUNITED)
def _reunited_felt(e, cx) -> Appraisal:
    """Après la solitude, un soulagement ; après l'ennui, de la joie : sa compagnie lui fait du bien."""
    emotion = Emotion.RELIEVED if e.data.after == c.LONELY else Emotion.HAPPY
    return Appraisal(emotion, e.data.intensity, reason=causes.COMPANY, relational=True)  # suit la contagion (ADR 0100)
