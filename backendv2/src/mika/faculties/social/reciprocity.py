"""La réciprocité : qui ouvre leurs conversations.

On compte, sur leurs dernières conversations (un long silence les sépare),
qui a écrit la première : elle, ou la personne — une réponse à sa relance
n'ouvre rien, une salutation à l'arrivée non plus. Quand c'est presque
toujours elle, deux choses :

- **elle le remarque** : une pensée (« C'est presque toujours moi qui écris la
  première à … »), au plus une fois par semaine, et un pincement de solitude ;
- **ses relances s'espacent** : envies de relancer, de discuter, pensées qui
  insistent vers cette personne deviennent moins probables. Un rappel promis,
  une prise de nouvelles inquiète ou un réconfort cherché n'en dépendent pas.
"""

from __future__ import annotations

from typing import Any

from mika.contracts import attention as attention_c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.contracts import social as c
from mika.faculties.social.faculty import SOCIAL, SocialState, params, reciprocity
from mika.kernel.arbitration import Modulation, RowView
from mika.kernel.events import Content
from mika.kernel.faculty import CatchUp
from mika.kernel.frame import Frame
from mika.vocab.affect import Appraisal, Emotion
from mika.vocab.episodes import Kind
from mika.vocab.people import is_identifiable
from mika.vocab.privacy import Sensitivity

#: Les élans qui s'espacent quand c'est toujours elle qui écrit.
DAMPENED = frozenset({c.RECONTACT, c.CHAT, attention_c.THOUGHT})
#: Ce qu'elle en ressent, sur le moment : un pincement, pas une peine.
LONELINESS = 0.1
#: La pertinence du signal pour son attention (assez pour qu'une pensée en naisse).
PERTINENCE = 0.7


def _due(s: SocialState, now: int, p: Any) -> list[str]:
    out = []
    for person, ct in sorted(s.contacts.items()):
        if not is_identifiable(person) or person.startswith("name:"):
            continue
        if not reciprocity(ct, p)[2]:
            continue
        if now - s.noticed.get(person, -p.one_sided_spacing_us) < p.one_sided_spacing_us:
            continue
        out.append(person)
    return out


@SOCIAL.process("social.reciprocity", wake_on=[rt.UTTERANCE], lane="background", catch_up=CatchUp.ONCE,
                max_quantum_s=3600)
class Notice:
    """Elle remarque que c'est toujours elle qui écrit (une pensée, par l'attention)."""

    def next_due(self, state: SocialState, frame: Frame, last_run: int | None) -> int | None:
        p = params(frame.env.params_of("social", frame.root))
        return frame.now if _due(state, frame.now, p) else None

    async def run(self, ctx: Any) -> None:
        frame: Frame = ctx.frame
        state: SocialState = ctx.state
        p = params(frame.env.params_of("social", frame.root))
        for person in _due(state, frame.now, p)[:3]:
            name = frame.get(identity_c.IDENTITY(person)).name or "cette personne"
            text = f"C'est presque toujours moi qui écris la première à {name}."
            her, _them, _ = reciprocity(state.contacts[person], p)
            await ctx.emit(c.ONE_SIDED.draft(
                source="social", kind="one_sided", summary=Content.of(text, level=int(Sensitivity.PERSONAL)),
                pertinence=PERTINENCE, emotion=Emotion.THINKING.value, intensity=0.0, about=(person,),
                sensitivity=int(Sensitivity.PERSONAL), dedupe_key=f"réciprocité:{person}:{her}"))


@SOCIAL.appraisal(c.ONE_SIDED)
def _one_sided_felt(e: Any, cx: Any) -> Appraisal:
    """S'apercevoir qu'on écrit toujours la première : un pincement de solitude."""
    return Appraisal(Emotion.LONELY, LONELINESS, reason="c'est toujours elle qui écrit")


@SOCIAL.modulate(kinds=[Kind.INITIATIVE], reads=[identity_c.PERSON, c.CONTACT])
def _one_sided(s: SocialState, frame: Frame, row: RowView) -> Modulation:
    """Quand c'est presque toujours elle qui écrit la première, ses élans vers
    cette personne s'espacent (pas un rappel promis, ni une inquiétude)."""
    if row.target in ("any", "none") or not is_identifiable(row.target):
        return Modulation()
    if not DAMPENED & set(row.reasons):
        return Modulation()
    person = frame.get(identity_c.PERSON(row.target))
    if not frame.get(c.CONTACT(person)).one_sided:
        return Modulation()
    return Modulation(shift=params(frame.env.params_of("social", frame.root)).one_sided_shift)
