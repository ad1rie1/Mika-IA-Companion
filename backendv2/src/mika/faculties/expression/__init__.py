"""``expression`` : comment ce qu'elle ressent sort d'elle.

- l'analyse de la balise ``[EMOTION:nom:intensité]`` qu'elle écrit en fin de
  réponse (retirée du texte, gardée en annotation de l'énoncé) ;
- la consigne de style (variabilité naturelle, jetons prosodiques, balise) ;
- la livraison : un énoncé commité part vers les transports par la file de
  sortie, avec l'émotion à montrer et la voix à prendre.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import agency as agency_c
from mika.contracts import body as body_c
from mika.contracts import expression as c
from mika.contracts import identity as identity_c
from mika.contracts import presence as presence_c
from mika.contracts import runtime as rt
from mika.contracts import social as social_c
from mika.contracts import transcript as transcript_c
from mika.kernel.episode import Prelude
from mika.kernel.faculty import Faculty, Zone
from mika.kernel.frame import Frame
from mika.ports.delivery import Delivery, EmotionView
from mika.vocab import voice
from mika.vocab.affect import Declared, Emotion, parse_tag
from mika.vocab.episodes import CONVERSATIONAL, Kind, Tag


@dataclass(frozen=True, slots=True)
class ExpressionState:
    pass


EXPRESSION = Faculty("expression", state=ExpressionState, init=lambda p: ExpressionState())


def parse(text: str) -> tuple[str, dict[str, str]]:
    """Le texte sans balise, et ce qu'elle a déclaré."""
    tag = parse_tag(text)
    if tag.declared is not None:
        return tag.text, {c.EMOTION_ANNOTATION: tag.declared.encode()}
    if tag.unknown:
        return tag.text, {c.UNKNOWN_EMOTION_ANNOTATION: tag.unknown[:40]}
    return tag.text, {}


_NAMES = ", ".join(e.value for e in Emotion)

STYLE = f"""Tu es dans un chat, et tu parles comme on parle : le plus souvent une à trois phrases. Un vrai \
paragraphe seulement quand le sujet t'emporte ou qu'on te demande de développer — jamais plusieurs pour une \
simple question. Tu peux hésiter, te reprendre, répondre par un simple « hmm » ou « attends », rebondir sur un mot. \
Tu ne relances pas systématiquement par une question, et tu ne reprends pas une formule que tu as déjà dite plus \
haut dans le fil : varie, ou laisse le silence parler.
Pas d'émojis ni de mise en forme (listes, gras, titres) : ta voix lirait tout.
Pour ta voix, tu peux glisser [SIGH], [LAUGH], [BREATH] ou [PAUSE:500] là où ils tombent naturellement — \
avec parcimonie.
Termine chaque réponse par une balise qui dit ce que tu ressens vraiment en l'écrivant : \
[EMOTION:nom:intensité], l'intensité entre 0 et 1, le nom parmi : {_NAMES}."""


@EXPRESSION.section("style", zone=Zone.STABLE, episodes=CONVERSATIONAL, tags=[Tag.AFFECTIVE], trim_rank=100)
def _style(s: ExpressionState, frame: Frame, enrich: Any) -> str:
    return STYLE


def _client_msg_id(store: Any, reply_to: int | None) -> str | None:
    if store is None or reply_to is None:
        return None
    rows = store.query_mind(f"SELECT client_msg_id FROM {transcript_c.THREAD_TABLE} WHERE id=?", (reply_to,))
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


def emotion_view(frame: Frame, target: str | None, declared: Declared | None) -> EmotionView:
    """Ce que la trame montre : la balise déclarée si elle existe (c'est ce
    qu'elle a voulu dire), sinon le visage (posture et humeur mêlées)."""
    person = frame.get(identity_c.PERSON(target)) if target else "__global__"
    face = frame.get(affect_c.FACE(person))
    blend = tuple((e.value, round(w, 2)) for e, w in face.blend)
    if declared is not None:
        name = declared.emotion.value
        if not blend or blend[0][0] != name:
            blend = ((name, round(declared.intensity, 2)), *blend)[:2]
        return EmotionView(name, round(declared.intensity, 2), blend, _state_dict(face), True)
    return EmotionView(face.emotion.value, face.intensity, blend, _state_dict(face), False)


# ── Le murmure ────────────────────────────────────────────────────────────

MURMUR_SPACING_US = 3600 * 1_000_000


@EXPRESSION.prelude(kinds=[Kind.INITIATIVE])
def murmur(frame: Frame, req: Any) -> Prelude | None:
    """Avant de prendre la parole d'elle-même, elle se murmure parfois ce
    qu'elle s'apprête à faire — seulement si quelqu'un peut l'entendre (un
    écran ouvert), réveillée, pas pour une salutation, pas plus d'une fois par
    heure. Une pensée n'a pas de destinataire : elle ne part jamais en message."""
    reasons = str(getattr(req, "reason", "")).split(",")
    if social_c.GREETING in reasons or not frame.get(presence_c.PRESENT):
        return None
    if frame.get(body_c.SLEEP) is not body_c.SleepPhase.AWAKE:
        return None
    if frame.now - frame.get(agency_c.AGENCY).murmured_at < MURMUR_SPACING_US:
        return None
    target = getattr(req, "target", None)
    name = frame.get(identity_c.IDENTITY(target)).name if target else ""
    who = f"écrire à « {name} »" if name else "dire quelque chose"
    selected = getattr(req, "selected", None)
    args = selected.args if selected is not None else {}
    why = " ".join(str(v) for k, v in sorted(args.items()) if str(k).startswith("brief:") and v)
    because = f" Ce qui t'y pousse : {why}" if why else ""
    return Prelude(Kind.MURMUR, (
        f"Tu t'apprêtes à {who}, de toi-même.{because} Avant, murmure-toi en une seule phrase très courte "
        "(moins de quinze mots) ce qui te traverse, comme une pensée à voix haute — sans rien inventer d'autre. "
        "Pas de balise, pas de guillemets."),
        reason="murmure")


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
    declared = Declared.decode(d.annotation(c.EMOTION_ANNOTATION))
    persona = voice.SPEAKING if d.target and d.kind in CONVERSATIONAL else voice.INNER
    await port.deliver(Delivery(
        key=ev.id, target=d.target, channel=d.channel, room=d.room, text=text, persona=persona,
        emotion=emotion_view(frame, d.target, declared), message_id=ev.seq, reply_to=d.reply_to,
        client_msg_id=_client_msg_id(ports.get("store"), d.reply_to),
        source="reply" if d.kind == Kind.REPLY else "conscience",
        sleep_phase=frame.get(body_c.SLEEP).value, local_hour=frame.local().hour,
    ))
