"""Le protocole du frontend, en fonctions pures : trames sortantes, validation
des trames entrantes, limites. Le contrat est celui que lit le code du
frontend (``frontend/src/types/messages.ts``, ``network/WebSocketClient.ts``).

Invariants tenus ici : ``emotion`` est l'un des 29 noms ; ``emotion_blend``
est toujours un tableau ; ``voice_profile`` n'est jamais nul ; les
identifiants de messages sont les ``seq`` du journal, partagés par questions
et réponses ; toute trame ``inner_state`` porte ``sleep_phase``.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from mika.contracts import affect as affect_c
from mika.contracts import body as body_c
from mika.contracts import identity as identity_c
from mika.contracts import needs as needs_c
from mika.contracts import self_ as self_c
from mika.contracts.entry import HistoryRow
from mika.kernel.frame import Frame
from mika.ports.delivery import TOO_LATE, Delivery
from mika.vocab import privacy, voice
from mika.vocab.affect import Emotion, emotion_of
from mika.vocab.people import is_identifiable

MAX_MESSAGE_CHARS = 2000
MAX_ATTACHMENTS = 5
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_REJECTED_REPORTED = 10
MAX_CLIENT_MSG_ID = 64
HISTORY_INITIAL = 50
HISTORY_MAX = 200
CHAT_RATE = (20, 10.0)
CONTROL_RATE = (12, 10.0)
MAX_FRAME_BYTES = MAX_ATTACHMENTS * MAX_FILE_BYTES * 4 // 3 + 1024 * 1024
FILENAME_MAX = 80

_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


class RateLimiter:
    """Fenêtre glissante : au plus ``n`` événements par ``window`` secondes."""

    def __init__(self, n: int, window: float) -> None:
        self.n = n
        self.window = window
        self._hits: deque[float] = deque()

    def allow(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        while self._hits and now - self._hits[0] >= self.window:
            self._hits.popleft()
        if len(self._hits) >= self.n:
            return False
        self._hits.append(now)
        return True


def sanitize_filename(name: Any) -> str:
    text = _CONTROL.sub(" ", str(name or "")).strip()
    return (" ".join(text.split()) or "fichier")[:FILENAME_MAX]


@dataclass(frozen=True, slots=True)
class Attachment:
    name: str
    mime: str
    data: bytes

    @property
    def kind(self) -> str:
        major = self.mime.split("/", 1)[0]
        return {"image": "image", "audio": "audio"}.get(major, "file")


def validate_attachments(raw: Any) -> tuple[list[Attachment], list[dict[str, str]]]:
    """Ce qui passe, et ce qui est écarté (avec la raison) — les deux, pour que
    l'expéditeur sache ce que Mika a réellement reçu."""
    kept: list[Attachment] = []
    rejected: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return kept, rejected
    for item in raw:
        name = sanitize_filename(item.get("name") if isinstance(item, dict) else "")
        if len(kept) >= MAX_ATTACHMENTS:
            rejected.append({"name": name, "reason": "too_many"})
            continue
        if not isinstance(item, dict) or not isinstance(item.get("data"), str):
            rejected.append({"name": name, "reason": "invalid"})
            continue
        data = item["data"]
        if data.startswith("data:") and "," in data:
            data = data.split(",", 1)[1]
        if len(data) * 3 // 4 > MAX_FILE_BYTES + 3:
            rejected.append({"name": name, "reason": "too_large"})
            continue
        try:
            blob = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            rejected.append({"name": name, "reason": "invalid"})
            continue
        if len(blob) > MAX_FILE_BYTES:
            rejected.append({"name": name, "reason": "too_large"})
            continue
        mime = str(item.get("type") or "application/octet-stream")[:100]
        kept.append(Attachment(name, mime, blob))
    return kept, rejected[:MAX_REJECTED_REPORTED]


# ── Trames sortantes ──────────────────────────────────────────────────────


def ack(client_msg_id: str, status: str, rejected: Sequence[dict[str, str]] = ()) -> dict[str, Any]:
    frame: dict[str, Any] = {"type": "ack", "client_msg_id": client_msg_id, "status": status}
    if rejected:
        frame["rejected_attachments"] = list(rejected)[:MAX_REJECTED_REPORTED]
    return frame


def history_item(row: HistoryRow) -> dict[str, Any]:
    try:
        attachments = json.loads(row.attachments) if row.attachments else []
    except ValueError:
        attachments = []
    emotion = emotion_of(row.emotion)
    return {
        "id": row.id,
        "role": row.role,
        "text": row.text,
        "ts": row.at // 1000,
        "source": row.source,
        "emotion": emotion.value if emotion else "",
        "emotion_intensity": float(row.emotion_intensity or 0.0),
        "attachments": attachments if isinstance(attachments, list) else [],
    }


def history(mode: str, rows: Sequence[HistoryRow], *, after_id: int = 0, truncated: bool = False) -> dict[str, Any]:
    return {
        "type": "history",
        "mode": mode,
        "messages": [history_item(r) for r in rows],
        "last_id": rows[-1].id if rows else after_id,
        "truncated": bool(truncated),
    }


def _blend(parts: Sequence[tuple[str, float]]) -> list[dict[str, Any]]:
    out = []
    for name, weight in parts:
        e = emotion_of(name)
        if e is not None:
            out.append({"emotion": e.value, "weight": round(float(weight), 2)})
    return out


#: la voix d'un autre onglet de la même personne : un seul écran parle, sinon l'écho
OTHER_TAB = "other_tab"


def speech(d: Delivery, *, present: bool = True, muted: bool = False, voiced: bool = True) -> dict[str, Any]:
    """Une parole ou une pensée. Une pensée à voix haute (persona ``inner``) n'est
    pas dans le fil : ``message_id`` nul (le client la range après son curseur et
    ne l'avance pas). ``voiced`` faux : un autre écran de la même personne parle."""
    decision = voice.decide(voice.SCREEN, hour=d.local_hour, sleep_phase=d.sleep_phase, present=present,
                            muted=muted, persona=d.persona)
    emotion = emotion_of(d.emotion.emotion) or Emotion.NEUTRAL
    inner = d.persona == voice.INNER
    return {
        "type": "speech",
        "text": d.text,
        "emotion": emotion.value,
        "emotion_intensity": round(float(d.emotion.intensity), 2),
        "emotion_state": dict(d.emotion.state),
        "emotion_blend": _blend(d.emotion.blend),
        "source": d.source,
        "person_id": d.target,
        "speak": decision.speak and voiced,
        "voice_reason": decision.reason if voiced or not decision.speak else OTHER_TAB,
        "voice_persona": d.persona,
        "voice_profile": voice.profile_for(d.persona).to_dict(),
        "message_id": None if inner else d.message_id,
        "user_message_id": None if inner else d.reply_to,
        "client_msg_id": None if inner else d.client_msg_id,
    }


#: la raison d'une trame sans texte quand elle dort : la réponse viendra à son réveil
ASLEEP = "asleep"


def silence(handle: str, face: affect_c.Face, *, user_message_id: int | None,
            client_msg_id: str | None, reason: str = "silence") -> dict[str, Any]:
    """Elle a choisi de ne pas répondre (ou elle dort, ``reason`` = ``ASLEEP`` : la réponse
    attend son réveil) : une trame ``speech`` sans texte. Le client cesse d'afficher
    « Mika écrit… », rattache sa bulle au message enregistré, et le visage garde ce qu'il
    montrait (son visage du moment, pas un neutre)."""
    blend = [{"emotion": e.value, "weight": round(w, 2)} for e, w in face.blend]
    return {
        "type": "speech", "text": "", "emotion": face.emotion.value,
        "emotion_intensity": round(float(face.intensity), 2), "emotion_state": face_state(face),
        "emotion_blend": blend, "source": "reply", "person_id": handle, "speak": False,
        "voice_reason": reason, "voice_persona": voice.SPEAKING,
        "voice_profile": voice.profile_for(voice.SPEAKING).to_dict(), "message_id": None,
        "user_message_id": user_message_id, "client_msg_id": client_msg_id,
    }


def face_signature(face: affect_c.Face) -> tuple[str, float, tuple[str, ...]]:
    return face.emotion.value, face.intensity, tuple(e.value for e, _ in face.blend)


def face_state(face: affect_c.Face) -> dict[str, Any]:
    return {
        "person": {"emotion": face.person[0].value, "intensity": face.person[1]},
        "global": {"emotion": face.mood[0].value, "intensity": face.mood[1]},
        "message": {"emotion": face.emotion.value, "intensity": face.intensity,
                    "blend": [{"emotion": e.value, "weight": round(w, 2)} for e, w in face.blend]},
    }


def emotion_update(person_id: str, face: affect_c.Face) -> dict[str, Any]:
    return {
        "type": "emotion_update",
        "person_id": person_id,
        "emotion": face.emotion.value,
        "emotion_intensity": face.intensity,
        "emotion_blend": [{"emotion": e.value, "weight": round(w, 2)} for e, w in face.blend],
        "emotion_state": face_state(face),
    }


def inner_state(frame: Frame, handle: str | None, panel: dict[str, Any] | None = None) -> dict[str, Any]:
    """L'état intérieur que montre le panneau ; ``person_scope`` dit si la
    trame concerne quelqu'un (sinon ses clés personnelles ne disent rien)."""
    local = frame.local()
    rhythm = frame.get(body_c.RHYTHM)
    phase = frame.get(body_c.PHASE)
    energy = frame.get(body_c.ENERGY)
    out: dict[str, Any] = {
        "sleep_phase": frame.get(body_c.SLEEP).value,
        "energy": round(energy, 3),
        "circadian": {"phase": phase.value, "hour": local.hour, "energy": round(energy, 3),
                      "bias_emotion": rhythm.tints[phase].value},
        "ruminations": [],
        "person_scope": bool(handle) and is_identifiable(handle),
    }
    needs = frame.get(needs_c.NEEDS)
    out["drives"] = {name: {"tension": round(value, 3), "last_satisfied": 0}
                     for name, value in (("social", needs.social), ("expression", needs.expression),
                                         ("curiosity", needs.curiosity))}
    out["estime"] = round(frame.get(self_c.ESTEEM), 3)
    if handle and is_identifiable(handle):
        view = frame.get(identity_c.IDENTITY(handle))
        out["identity"] = {
            "known_as": view.name,
            "certainty": round(view.certainty, 2),
            "level": privacy.describe_fr(view.certainty, view.trust, view.name),
            "trust": view.trust.value,
            "pending_claims": [],
        }
        if panel:
            out.update(panel)  # identité détaillée, et la fiche si elle est ouverte
    return out


def inner_state_update(frame: Frame, handle: str | None, panel: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "inner_state_update", "inner_state": inner_state(frame, handle, panel)}


FAILED_OUTCOMES = frozenset({"failed", "timeout"})
ABSTAINED_OUTCOME = "abstained"
#: le statut d'``ack`` qui dit qu'une question acceptée n'aura pas de réponse : le client
#: passe la bulle en échec, avec sa raison (« Mika est saturée, réessaie dans un instant »)
REPLY_FAILED_STATUS = "overloaded"
#: …et celui d'une question abandonnée parce que trop vieille (une reprise au démarrage, des heures
#: plus tard) : ce n'est pas une saturation, « trop tard pour répondre — repose ta question »
TOO_LATE_STATUS = "too_late"
UNCONFIGURED = "UnconfiguredRole"


def fallback_text(detail: str) -> str:
    if UNCONFIGURED in detail:
        return ("Je n'ai pas encore de modèle pour répondre : il faut en configurer un "
                "(python -m mika llm …).")
    return "Désolée, je n'arrive pas à te répondre là tout de suite… Réessaie dans un instant ?"


def fallback_speech(handle: str, detail: str, *, user_message_id: int | None, client_msg_id: str | None,
                    persona: str = voice.SPEAKING) -> dict[str, Any]:
    """Une réponse ratée se dit, sans voix et sans émotion : ce n'est pas elle
    qui parle, c'est la machine. Rien n'est journalisé (``message_id`` nul :
    le curseur du client n'avance pas). Avec un ``client_msg_id``, l'échec se dit
    plutôt par un second ``ack`` (``reply_failed_frames``) : une bulle sans
    identifiant et sans pensée restait épinglée en bas du fil pour toujours."""
    return {
        "type": "speech", "text": fallback_text(detail), "emotion": Emotion.NEUTRAL.value, "emotion_intensity": 0.0,
        "emotion_state": {}, "emotion_blend": [], "source": "error", "person_id": handle, "speak": False,
        "voice_reason": "error_fallback_muted", "voice_persona": persona,
        "voice_profile": voice.profile_for(persona).to_dict(), "message_id": None,
        "user_message_id": None if persona == voice.INNER else user_message_id,
        "client_msg_id": None if persona == voice.INNER else client_msg_id,
    }


def reply_failed_frames(handle: str, detail: str, face: affect_c.Face, *, user_message_id: int | None,
                        client_msg_id: str | None) -> list[dict[str, Any]]:
    """Ce que voit l'écran quand la réponse ne viendra pas : d'abord une trame sans
    texte (« Mika écrit… » disparaît, le regard « je réfléchis » cesse, la bulle se
    rattache à son message), puis un second ``ack`` qui passe la bulle en échec
    avec sa raison. Une installation sans modèle le dit en plus, en note (une
    pensée : rangée à sa place, jamais épinglée). Un client sans identifiant de
    message reçoit l'ancienne trame de repli."""
    if not client_msg_id:
        return [fallback_speech(handle, detail, user_message_id=user_message_id, client_msg_id=None)]
    status = TOO_LATE_STATUS if detail.startswith(TOO_LATE) else REPLY_FAILED_STATUS
    frames = [silence(handle, face, user_message_id=user_message_id, client_msg_id=client_msg_id),
              ack(client_msg_id, status)]
    if UNCONFIGURED in detail:
        frames.append(fallback_speech(handle, detail, user_message_id=user_message_id, client_msg_id=None,
                                      persona=voice.INNER))
    return frames
