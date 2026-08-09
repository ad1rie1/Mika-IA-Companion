"""Découpage des messages en chunks d'échange — pur, sans I/O.

L'unité d'indexation est la **paire d'échange** : le(s) message(s) d'une
personne suivi(s) de la réponse de Mika. Un chunk porte exactement UN handle
transport (métadonnée scalaire → filtrage par personne trivial côté Chroma) ;
les paires consécutives du même interlocuteur dans la même conversation sont
fusionnées jusqu'à ``max_chars``.

Contraintes qui ont dicté la forme :

- L'encodeur (MiniLM multilingue) ne voit ~que 128 tokens (~450 caractères
  de français) : au-delà de ``max_chars`` le texte n'améliore plus l'embedding.
  Une paire déjà trop grosse n'est **jamais coupée** — la localisabilité du
  verbatim prime, et le deux-temps (vecteur localise → SQL cite) fournit la
  citation exacte de toute façon.
- La queue non appariée (question encore sans réponse) est **retenue** : le
  checkpoint de l'indexeur recule devant elle et la relit au tick suivant,
  pour que la paire s'indexe entière. Après ``flush_age_s`` sans réponse,
  elle est indexée seule (Mika n'a pas répondu — c'est un fait, pas un bug).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from identity.trust import is_internal_person

# Un message individuel démesuré (collage) est borné dans le *document*
# indexé : le SQL garde l'intégralité, le deux-temps la restitue.
MESSAGE_TEXT_CAP = 2000
_CAP_MARK = " …[tronqué]"


@dataclass(frozen=True)
class ExchangeChunk:
    """Un chunk prêt à indexer. ``ts`` = epoch du premier message."""

    conversation_id: int
    first_message_id: int
    last_message_id: int
    handle: str
    ts: float
    text: str

    @property
    def chunk_id(self) -> str:
        # Un message appartient à au plus un chunk → le pk du premier message
        # est un id stable et unique, cohérent avec la convention du store
        # (ids = str(pk ORM)).
        return str(self.first_message_id)


class _Pair:
    __slots__ = ("conversation_id", "handle", "msgs", "answered")

    def __init__(self, conversation_id: int, handle: str, msg: dict):
        self.conversation_id = conversation_id
        self.handle = handle
        self.msgs = [msg]
        self.answered = False

    @property
    def first(self) -> dict:
        return self.msgs[0]

    @property
    def last(self) -> dict:
        return self.msgs[-1]


def _clip(content: str) -> str:
    content = (content or "").strip()
    if len(content) <= MESSAGE_TEXT_CAP:
        return content
    return content[: MESSAGE_TEXT_CAP - len(_CAP_MARK)].rstrip() + _CAP_MARK


def _pair_text(pair: _Pair) -> str:
    lines = []
    for m in pair.msgs:
        label = "Mika" if m.get("role") == "assistant" else "Lui"
        content = _clip(m.get("content") or "")
        if content:
            lines.append(f"{label}: {content}")
    return "\n".join(lines)


def _handle_of(msg: dict) -> str:
    """Handle transport du message — "" pour les identifiants internes.

    Un id interne (``conscience_mika``, ``__global__``…) n'est pas une
    personne : le chunk reste indexé (c'est du vécu de Mika) mais ne doit
    jamais matcher un filtre par personne.
    """
    handle = msg.get("person_id") or ""
    if handle and is_internal_person(handle):
        return ""
    return handle


def _ts_of(msg: dict) -> float:
    dt = msg.get("created_at")
    if isinstance(dt, datetime):
        return dt.timestamp()
    return 0.0


def build_chunks(
    messages: list[dict],
    *,
    max_chars: int = 600,
    flush_age_s: int = 600,
    now: datetime,
) -> tuple[list[ExchangeChunk], int | None]:
    """Découpe une fenêtre de messages en chunks.

    ``messages`` : dicts ``{id, role, content, created_at, source, person_id,
    conversation_id}`` ordonnés chronologiquement, déjà filtrés par
    ``memory.storage.window.user_facing_messages``.

    Retourne ``(chunks, consumed_up_to_id)`` — ``consumed_up_to_id`` vaut
    ``None`` quand toute la fenêtre est consommée, sinon l'id jusqu'auquel le
    checkpoint peut avancer (la queue non appariée retenue est relue au tick
    suivant).
    """
    pairs: list[_Pair] = []
    open_pair: _Pair | None = None

    for m in messages:
        role = m.get("role")
        conv = int(m.get("conversation_id") or 0)
        if role == "user":
            handle = _handle_of(m)
            if open_pair is not None and (
                open_pair.answered
                or open_pair.handle != handle
                or open_pair.conversation_id != conv
            ):
                # Question restée sans réponse avant qu'un autre parle, ou
                # changement d'interlocuteur/de fil : la paire se ferme telle
                # quelle.
                pairs.append(open_pair)
                open_pair = None
            if open_pair is None:
                open_pair = _Pair(conv, handle, m)
            else:
                # Double message du même interlocuteur : même paire.
                open_pair.msgs.append(m)
        elif role == "assistant":
            if open_pair is not None and open_pair.conversation_id == conv:
                open_pair.msgs.append(m)
                open_pair.answered = True
                pairs.append(open_pair)
                open_pair = None
            else:
                if open_pair is not None:
                    pairs.append(open_pair)
                    open_pair = None
                # Initiative de Mika (salutation, tour de conscience adressé) :
                # paire autonome, handle = destinataire s'il est réel.
                pairs.append(_Pair(conv, _handle_of(m), m))
                pairs[-1].answered = True
        # Autres rôles : ignorés (le flatteur historique les ignorait aussi).

    consumed_up_to: int | None = None
    if open_pair is not None:
        age = (now - open_pair.last["created_at"]).total_seconds()
        if age >= flush_age_s:
            pairs.append(open_pair)
        else:
            consumed_up_to = int(open_pair.first["id"]) - 1

    # Fusion avant : paires consécutives, même handle, même conversation.
    chunks: list[ExchangeChunk] = []
    for pair in pairs:
        text = _pair_text(pair)
        if not text:
            continue
        if chunks:
            prev = chunks[-1]
            if (
                prev.handle == pair.handle
                and prev.conversation_id == pair.conversation_id
                and len(prev.text) + 1 + len(text) <= max_chars
            ):
                chunks[-1] = ExchangeChunk(
                    conversation_id=prev.conversation_id,
                    first_message_id=prev.first_message_id,
                    last_message_id=int(pair.last["id"]),
                    handle=prev.handle,
                    ts=prev.ts,
                    text=f"{prev.text}\n{text}",
                )
                continue
        chunks.append(ExchangeChunk(
            conversation_id=pair.conversation_id,
            first_message_id=int(pair.first["id"]),
            last_message_id=int(pair.last["id"]),
            handle=pair.handle,
            ts=_ts_of(pair.first),
            text=text,
        ))

    return chunks, consumed_up_to
