"""Messenger et Instagram : l'export Meta « Télécharger vos informations » (JSON).

Deux formes :

- l'export classique, ``messages/inbox/<fil>/message_N.json`` : ``participants`` [{name}],
  ``messages`` [{sender_name, timestamp_ms, content, photos, …}], ``title``,
  ``thread_path``. Meta y encode l'UTF-8 octet par octet (« Ã© » pour « é ») : on répare ;
- l'export des discussions chiffrées de bout en bout (messenger.com) : ``participants``
  [noms], ``threadName``, ``messages`` [{senderName, timestamp, text, media, type}].

Un fil coupé en ``message_1.json``, ``message_2.json``… garde la même clé (le dossier
du fil) : la base le recoud. L'export chiffré range souvent **tous** les fils dans un même
dossier, un fichier par fil : la clé est alors le fichier, jamais le dossier seul (sinon toutes
ses discussions se fondraient en une). Dans un fil à deux, le titre est le nom de l'autre : le
participant qui ne le porte pas, c'est elle. Le nom de la titulaire de l'export se lit
aussi dans ``profile_information.json`` quand il est là.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from twin.readers import ReadContext, head
from twin.records import INSTAGRAM, MESSENGER, Attachment, Author, Conversation, Item, Message
from twin.timing import US, Origin, Temps


def fix_mojibake(text: str) -> str:
    """« Ã©tÃ© » → « été » ; un texte déjà juste est rendu tel quel."""
    if not text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _fix(obj: Any) -> Any:
    if isinstance(obj, str):
        return fix_mojibake(obj)
    if isinstance(obj, list):
        return [_fix(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _fix(v) for k, v in obj.items()}
    return obj


def _channel(path: Path, data: dict[str, Any]) -> str:
    probe = " ".join([*(p.lower() for p in path.parts), str(data.get("thread_path", "")).lower()])
    return INSTAGRAM if "instagram" in probe else MESSENGER


@lru_cache(maxsize=64)
def _owner_name(start: Path) -> str:
    """Le nom de la titulaire, lu dans son profil quelque part au-dessus du fil."""
    for parent in [start, *start.parents][:8]:
        for rel in ("personal_information/profile_information/profile_information.json",
                    "profile_information/profile_information.json",
                    "personal_information/personal_information.json"):
            f = parent / rel
            if f.is_file():
                try:
                    data = _fix(json.loads(f.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    continue
                profile = data.get("profile_v2") or data.get("profile") or {}
                name = (profile.get("name") or {}).get("full_name") or ""
                if name:
                    return name
    return ""


def _conversation_key(path: Path) -> str:
    """Le dossier pour un fil découpé en ``message_N.json`` ; sinon le fichier lui-même (``dossier/fichier``)."""
    if re.fullmatch(r"message_\d+", path.stem):
        return path.parent.name
    return f"{path.parent.name}/{path.stem}"  # le numéro final d'un nom de fichier chiffré est celui du fil


class MetaReader:
    name = "meta"
    label = "Messenger / Instagram (export Meta JSON)"
    version = 2

    def detect(self, path: Path) -> int:
        if path.suffix.lower() != ".json":
            return 0
        h = head(path, 4096)
        if '"participants"' in h and ('"sender_name"' in h or '"senderName"' in h or '"messages"' in h):
            return 95
        return 0

    def read(self, path: Path, ctx: ReadContext) -> Iterator[Item]:
        data = _fix(json.loads(path.read_text(encoding="utf-8")))
        channel = _channel(path, data)
        e2ee = "threadName" in data or any("senderName" in m for m in data.get("messages", [])[:5])
        participants = [p if isinstance(p, str) else p.get("name", "") for p in data.get("participants", [])]
        participants = [p for p in participants if p]
        title = data.get("title") or data.get("threadName") or ""
        conv_key = str(data.get("thread_path") or _conversation_key(path))
        group = len(participants) > 2 or data.get("thread_type") == "RegularGroup"
        yield Conversation(channel, conv_key, title=title, group=group, members=tuple(participants))

        owner = _owner_name(path.parent)
        for p in participants:
            me: bool | None = None
            reason = ""
            if owner:
                me = p == owner
                reason = "titulaire de l'export (profil)" if me else "n'est pas la titulaire de l'export"
            elif not group and title and len(participants) == 2:
                me = p != title
                reason = "fil à deux : le titre nomme l'autre" if me else "porte le titre du fil"
            yield Author(channel, p, name=p, me=me, me_reason=reason)

        msgs = data.get("messages", [])
        for m in msgs:
            sender = (m.get("senderName") if e2ee else m.get("sender_name")) or ""
            if sender and sender not in participants:
                participants.append(sender)
                yield Author(channel, sender, name=sender)
        # l'export classique range du plus récent au plus ancien : le rang suit le temps
        ordered = sorted(msgs, key=lambda m: m.get("timestamp_ms") or m.get("timestamp") or 0)
        for rank, m in enumerate(ordered):
            item = self._message(m, channel, conv_key, rank, e2ee)
            if item is not None:
                yield item
            else:
                ctx.warn(f"{path.name} : message sans date ignoré")

    def _message(self, m: dict[str, Any], channel: str, conv: str, rank: int, e2ee: bool) -> Message | None:
        ms = m.get("timestamp") if e2ee else m.get("timestamp_ms")
        if not ms:
            return None
        sender = (m.get("senderName") if e2ee else m.get("sender_name")) or ""
        text = (m.get("text") if e2ee else m.get("content")) or ""
        atts: list[Attachment] = []
        for key in ("photos", "videos", "audio_files", "files", "gifs", "media"):
            for a in m.get(key) or []:
                uri = a.get("uri", "") if isinstance(a, dict) else str(a)
                atts.append(Attachment(Path(uri).name or key))
        if m.get("sticker"):
            atts.append(Attachment("sticker"))
        share = m.get("share") or {}
        if share.get("link") and share["link"] not in text:
            text = f"{text}\n{share['link']}".strip()
        kind = {"Call": "appel", "Unsubscribe": "systeme", "Subscribe": "systeme"}.get(m.get("type", ""), "message")
        if m.get("is_unsent"):
            kind = "supprime"
        at_us = int(ms) * (US // 1000)  # millisecondes → microsecondes
        return Message(channel, conv, sender, text, Temps.exact(at_us, Origin.SOURCE), rank, kind=kind,
                       attachments=tuple(atts))


READER = MetaReader()
