"""La livraison : un énoncé commité part vers les transports par la file de sortie (l'effet sur ``rt.UTTERANCE``),
avec l'émotion à montrer (``emotion_view`` : sa balise, ou son visage tel qu'elle le laisse voir) et la voix à prendre
(sa parole, ou sa voix intérieure pour un murmure)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select

from mika.contracts import affect as affect_c
from mika.contracts import body as body_c
from mika.contracts import expression as c
from mika.contracts import identity as identity_c
from mika.contracts import runtime as rt
from mika.contracts import transcript as transcript_c
from mika.faculties.expression.faculty import EXPRESSION
from mika.kernel.frame import Frame
from mika.ports.delivery import Delivery, EmotionView
from mika.vocab import voice
from mika.vocab.affect import Declared, Emotion
from mika.vocab.episodes import CONVERSATIONAL, Kind


def _client_msg_id(store: Any, reply_to: int | None) -> str | None:
    if store is None or reply_to is None:
        return None
    t = transcript_c.thread_table()
    rows = store.query_mind(select(t.c.client_msg_id).where(t.c.id == reply_to))
    return rows[0][0] if rows else None


def _state_dict(face: affect_c.Face) -> dict[str, Any]:
    return {
        "person": {"emotion": face.person[0].value, "intensity": face.person[1]},
        "global": {"emotion": face.mood[0].value, "intensity": face.mood[1]},
        "message": {
            "emotion": face.emotion.value, "intensity": face.intensity,
            "blend": [{"emotion": e.value, "weight": round(w, 2)} for e, w in face.blend],
        },
    }


def emotion_view(frame: Frame, target: str | None, declared: Declared | None, *, toward: bool = False
                 ) -> EmotionView:
    """Ce que la trame montre : la balise déclarée si elle existe (c'est ce
    qu'elle a voulu dire) — ses deux premières facettes quand elle en a dit
    plusieurs (son ambivalence, jugée par le modèle, ADR 0093) —, sinon le
    visage (posture et humeur mêlées). Une réplique à quelqu'un (``toward`` : sa balise est déjà dans sa posture
    envers lui) montre son visage tel qu'elle le laisse voir à cette personne — son expressivité, son masque, sa
    défense, refermée ou non (ADR 0100) : ce que l'écran garde ensuite pendant qu'elle parle."""
    person = frame.get(identity_c.PERSON(target)) if target else "__global__"
    face = frame.get(affect_c.FACE(person))
    blend = tuple((e.value, round(w, 2)) for e, w in face.blend)
    if declared is not None and toward and target and declared.emotion is not Emotion.NEUTRAL:
        return EmotionView(face.emotion.value, face.intensity, blend, _state_dict(face), True)
    if declared is not None:
        name = declared.emotion.value
        if declared.facets:
            blend = tuple((e, round(x, 2)) for e, x in declared.facets[:2])
        elif not blend or blend[0][0] != name:
            blend = ((name, round(declared.intensity, 2)), *blend)[:2]
        return EmotionView(name, round(declared.intensity, 2), blend, _state_dict(face), True)
    return EmotionView(face.emotion.value, face.intensity, blend, _state_dict(face), False)


@EXPRESSION.effect(rt.UTTERANCE)
async def _deliver(ev: Any, ports: Mapping[str, Any]) -> None:
    d = ev.data
    if d.kind not in CONVERSATIONAL and d.kind != Kind.MURMUR:
        return
    port = ports.get("delivery")
    text = d.text.text
    if port is None or text is None:
        return
    frame: Frame = ports["frame"]()
    target = d.target
    if d.kind == Kind.MURMUR:
        # une pensée à mi-voix : sur les écrans de la personne à qui elle allait écrire, voix intérieure — jamais
        # à tout le monde (sans destinataire connu, elle ne part pas)
        target = frame.state("expression").murmurs.get(ev.correlation)
        if not target:
            return
    declared = Declared.decode(d.annotation(c.EMOTION_ANNOTATION))
    persona = voice.SPEAKING if d.target and d.kind in CONVERSATIONAL else voice.INNER
    await port.deliver(Delivery(
        key=ev.id, target=target, channel=d.channel, room=d.room, text=text, persona=persona,
        emotion=emotion_view(frame, target, declared, toward=d.kind in CONVERSATIONAL),
        message_id=ev.seq, reply_to=d.reply_to,
        client_msg_id=_client_msg_id(ports.get("store"), d.reply_to),
        source="reply" if d.kind == Kind.REPLY else "conscience",
        sleep_phase=frame.get(body_c.SLEEP).value, local_hour=frame.local().hour,
        answers=tuple(d.answers) if persona == voice.SPEAKING else (),
        # ce qui part avec la parole (des références opaques ici) ; jamais avec une pensée à voix haute
        attachments=tuple(d.attachments) if persona == voice.SPEAKING else (),
        mode=d.mode if persona == voice.SPEAKING else "",
        strand=d.strand if persona == voice.SPEAKING else None,
    ))
