"""Le cache de Teams (la base ``teams``, déclarée dans ``models`` : SQLite pour les tests, MariaDB en production —
ADR 0101) : ce que l'extension de chaque compte a poussé (conversations, messages), ses brouillons et la file de ce
qui doit repartir.

- **Un compte, son monde** (ADR 0186) : chaque ligne porte son compte. Un lot poussé, une file relevée, un accusé ne
  concernent que le compte de la clé ; une conversation se lit sous son compte (deux personnes d'un même groupe en
  ont chacune une), un brouillon part du compte de la conversation à laquelle il répond.

- **Un message se désigne par sa référence**, attribuée ici (``ports.teams.message_ref``) : la même pour un même
  message, qu'il arrive par le réseau ou par la base locale du client, rejoué ou retouché (un message modifié dans
  Teams garde sa référence, son texte suit).
- **Les messages de la personne du compte** sont gardés pour le fil, jamais rendus comme « reçus ». Ce sont eux qui disent qu'un brouillon posé est parti : un message de la personne dans la conversation,
  après qu'il a été posé, qui lui ressemble — retouché s'il n'est pas identique ; s'il ne lui ressemble pas, la
  personne a écrit autre chose, et le brouillon n'a pas servi.
- **Ce qui part est ce qui a été montré** : le texte final (signature comprise) est figé à la mise en file, avec
  son condensé ; l'extension relève ce texte-là.
"""

from __future__ import annotations

import difflib
import hashlib
import threading
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from sqlalchemy import and_, delete, false, func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from mika.adapters.database import Target, as_target
from mika.adapters.teams.config import HER, TeamsConfig
from mika.adapters.teams.models import (
    ACCOUNT_MAX,
    AUTHOR_MAX,
    CONVERSATION_MAX,
    REF_MAX,
    AccountRow,
    ConversationRow,
    DraftRow,
    MessageRow,
    fit,
)
from mika.ports.paging import fold_text
from mika.ports.sql import TEAMS
from mika.ports.teams import (
    ACCEPTED,
    CONFLICT,
    DISCARDED,
    DRAFT,
    FAILED,
    GONE,
    MISSING,
    OPEN_STATES,
    PLACED,
    QUEUED,
    SEND,
    SENDING,
    UNUSED,
    WRITTEN,
    AccountInfo,
    Conversation,
    Draft,
    InboxBatch,
    Message,
    OutboxItem,
    Preview,
    Settled,
    Stored,
    Voice,
    message_ref,
    plain,
    to_fill,
)

#: au plus tant de messages gardés par conversation (les plus récents)
KEEP_PER_CONVERSATION = 1000
#: un message de la personne compte pour un brouillon posé s'il est écrit au plus tant avant qu'on le sache posé
#: (deux horloges : celle du navigateur, celle du serveur)
CLOCK_SLACK = 120 * 1_000_000
#: à partir de cette ressemblance, le message de la personne est le brouillon (retouché ou non)
SIMILAR = 0.5
#: un message Teams est coupé à cette longueur par l'extension : au-delà, on compare ce qui en reste
CUT_AT = 3990

#: ce qu'on lit d'un message, d'une conversation, d'un brouillon (dans l'ordre des champs de ``Message``,
#: ``Conversation`` — son nombre de messages compté à part, puis son compte —, ``Draft``)
_MESSAGE = (MessageRow.ref, MessageRow.conversation, MessageRow.author, MessageRow.author_id, MessageRow.at,
            MessageRow.text, MessageRow.own, MessageRow.mentions_me, MessageRow.account)
_CONVERSATION = (ConversationRow.id, ConversationRow.title, ConversationRow.kind, ConversationRow.last_at)
_DRAFT = (DraftRow.draft_id, DraftRow.conversation, DraftRow.body, DraftRow.reply_to, DraftRow.author,
          DraftRow.created, DraftRow.updated, DraftRow.state, DraftRow.mode, DraftRow.digest, DraftRow.final,
          DraftRow.expires_at, DraftRow.placed_at, DraftRow.sent_at, DraftRow.sent_text, DraftRow.edited,
          DraftRow.edited_by, DraftRow.reason, DraftRow.account)
#: un tête-à-tête se reconnaît aussi à son identifiant (``19:a_b@unq.gbl.spaces``)
_DM_SUFFIX = "@unq.gbl.spaces"


def _now_us() -> int:
    return time.time_ns() // 1000


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, plain(a), plain(b)).ratio()


def _edited(sent: str, d: Draft) -> bool:
    """Ce qui est parti diffère-t-il de ce qu'elle avait écrit ? (Un message long arrive coupé : on compare ce qui
    en reste.)"""
    got = plain(sent)
    if got in (plain(d.final), plain(d.body)):
        return False
    return not (len(sent) >= CUT_AT and (plain(d.final).startswith(got) or plain(d.body).startswith(got)))


def _conversation(row: Any) -> Conversation:
    return Conversation(row[0], row[1] or "", row[2] or "other", int(row[3] or 0), int(row[4] or 0), row[5])


def _draft(row: Any) -> Draft:
    d = Draft(*row)
    return d if d.state else replace(d, state=WRITTEN)


def _count(result: Any) -> int:
    """Combien de lignes une suppression a touchées."""
    return int(getattr(result, "rowcount", 0) or 0)


def _counted() -> Any:
    """Le nombre de messages d'une conversation (corrélée à la requête qui l'appelle)."""
    return select(func.count(MessageRow.id)).where(MessageRow.account == ConversationRow.account,
                                                   MessageRow.conversation == ConversationRow.id).scalar_subquery()


def _account_key(account: str) -> str:
    """La clé d'un compte telle qu'elle est rangée (une clé trop longue ne désigne rien : ``Key`` la refuse)."""
    return fit(account, ACCOUNT_MAX)


def _in_accounts(column: Any, accounts: Sequence[str] | None) -> list[Any]:
    """La condition « de ces comptes » (``None`` : tous)."""
    return [] if accounts is None else [column.in_([_account_key(a) for a in accounts])]


class TeamsStore:
    """Le port ``teams`` : le cache et la file d'envoi, compte par compte. ``config`` est relue à chaque usage (ses
    comptes, leur signature, leur nom).

    Le cache a une seule connexion, partagée sous ``_lock`` : chaque méthode publique ouvre une session courte
    (``begin`` pour écrire, validée à la sortie) ; les aides internes reçoivent la sienne (``s``) — deux sessions à
    la fois sur la même connexion se marcheraient dessus."""

    def __init__(self, config: Callable[[], TeamsConfig], path: Path | Target, *,
                 now: Callable[[], int] = _now_us) -> None:
        self._config = config
        self._now = now
        self._lock = threading.RLock()
        target = as_target(path)
        target.ensure()
        self._engine = target.engine(shared=True)
        TEAMS.create_all(self._engine)
        self._session = sessionmaker(self._engine, expire_on_commit=False)

    # ── ses comptes ──
    @staticmethod
    def _account_in(s: Session, account: str) -> AccountRow | None:
        return s.get(AccountRow, _account_key(account))

    def accounts(self) -> list[AccountInfo]:
        """Ses comptes réglés (dans l'ordre de leur clé), avec ce que leur extension en a dit."""
        cfg = self._config()
        with self._lock, self._session() as s:
            rows = {r.key: r for r in s.scalars(select(AccountRow))}
        out = []
        for key, a in sorted(cfg.accounts.items()):
            row = rows.get(_account_key(key))
            out.append(AccountInfo(key, a.label, a.owner, int(row.last_batch or 0) if row else 0,
                                   str(row.self_id or "") if row else "", str(row.self_name or "") if row else "",
                                   enabled=a.enabled))
        return out

    def account(self, key: str) -> AccountInfo | None:
        return next((a for a in self.accounts() if a.key == key), None)

    def configured(self, account: str = "") -> bool:
        """L'extension de ce compte (vide : d'un compte au moins) a déjà poussé quelque chose."""
        where = [AccountRow.last_batch > 0]
        if account:
            where.append(AccountRow.key == _account_key(account))
        with self._lock, self._session() as s:
            return s.scalar(select(func.count()).select_from(AccountRow).where(*where)) > 0

    def last_batch(self, account: str) -> int:
        """Le dernier lot poussé par l'extension de ce compte (µs, 0 : jamais)."""
        with self._lock, self._session() as s:
            row = self._account_in(s, account)
            return int(row.last_batch or 0) if row is not None else 0

    def owner(self, account: str) -> tuple[str, str]:
        with self._lock, self._session() as s:
            row = self._account_in(s, account)
            return (str(row.self_id or ""), str(row.self_name or "")) if row is not None else ("", "")

    def _voice_in(self, s: Session, account: str) -> Voice:
        row = self._account_in(s, account)
        return self._config().voice(account, fallback_name=str(row.self_name or "") if row is not None else "")

    def voice(self, account: str) -> Voice:
        with self._lock, self._session() as s:
            return self._voice_in(s, account)

    # ── ce que pousse l'extension ──
    @staticmethod
    def _conversation_row(s: Session, seen: dict[str, ConversationRow], account: str, cid: str) -> ConversationRow:
        """La conversation de ce lot (créée vide si on ne la connaissait pas)."""
        row = seen.get(cid) or s.get(ConversationRow, (account, cid))
        if row is None:
            row = ConversationRow(account=account, id=cid, title="", kind="other", last_at=0)
            s.add(row)
        seen[cid] = row
        return row

    def store_batch(self, account: str, batch: InboxBatch, now: int) -> Stored:
        """Un lot poussé par l'extension de ce compte : rangé sous lui seul."""
        new = known = 0
        replied: dict[str, int] = {}
        settled: list[Settled] = []
        key = _account_key(account)
        with self._lock, self._session.begin() as s:
            row = self._account_in(s, key)
            if row is None:
                row = AccountRow(key=key, last_batch=0, self_id="", self_name="")
                s.add(row)
            if batch.self_id:
                row.self_id = batch.self_id
            if batch.self_name:
                row.self_name = batch.self_name
            row.last_batch = now
            seen: dict[str, ConversationRow] = {}
            for c in batch.conversations:
                found = self._conversation_row(s, seen, key, fit(c.id, CONVERSATION_MAX))
                if c.title:  # un titre vide ou un genre inconnu n'efface pas ce qu'on savait
                    found.title = c.title
                if c.kind != "other":
                    found.kind = c.kind
            for m in sorted(batch.messages, key=lambda m: m.time_ms):
                ref = message_ref(m.conversation, m.id, key)
                at = m.time_ms * 1000
                row = s.scalars(select(MessageRow).where(MessageRow.ref == ref)).first()
                if m.deleted:  # supprimé dans Teams : son texte part du cache (jamais remarqué s'il ne l'était pas)
                    if row is not None:
                        known += 1
                        row.text, row.acked = "", True
                    continue
                if row is not None:  # déjà connu (rejoué, ou retouché dans Teams : son texte suit)
                    known += 1
                    if row.text != m.text:
                        row.text = m.text
                    continue
                new += 1
                conv = fit(m.conversation, CONVERSATION_MAX)
                s.add(MessageRow(ref=ref, account=key, conversation=conv, external_id=m.id, author=m.author,
                                 author_id=m.author_id, author_key=fit(m.author_id.strip().lower(), AUTHOR_MAX), at=at,
                                 text=m.text, own=m.own, mentions_me=m.mentions_me, received=now, acked=m.own))
                found = self._conversation_row(s, seen, key, conv)
                found.last_at = max(found.last_at or 0, at)
                if m.own:
                    replied[conv] = max(replied.get(conv, 0), at)
                    settled.extend(self._answered_by_owner(s, key, conv, at, m.text, now))
            if new:
                self._prune(s)
        return Stored(new=new, known=known, replied=tuple(sorted(replied.items())), settled=tuple(settled))

    def _answered_by_owner(self, s: Session, account: str, conversation: str, at: int, text: str,
                           now: int) -> list[Settled]:
        """La personne du compte a écrit dans cette conversation : un brouillon posé (ou en file pour être posé) qui
        ressemble à ce qu'elle a écrit est parti ; sinon, il n'a pas servi. Un envoi encore en file (validation,
        autonome) n'est réglé que s'il lui ressemble (l'extension l'a envoyé, et son accusé s'est perdu)."""
        out: list[Settled] = []
        rows = s.execute(select(*_DRAFT).where(DraftRow.account == account, DraftRow.conversation == conversation,
                                               DraftRow.state.in_((QUEUED, SENDING, PLACED)))
                         .order_by(DraftRow.id)).all()
        for d in (_draft(r) for r in rows):
            since = (d.placed_at or d.updated) - CLOCK_SLACK
            if at < since:
                continue
            similar = max(_ratio(text, d.final), _ratio(text, d.body)) >= SIMILAR
            if similar:
                edited = _edited(text, d)
                self._write(s, replace(d, state=GONE, sent_at=now, sent_text=text, edited=edited))
                out.append(Settled(d.id, GONE, edited=edited))
            elif d.mode == DRAFT:
                reason = "tu as écrit autre chose" if d.state == PLACED else "tu as répondu toi-même"
                self._write(s, replace(d, state=UNUSED, reason=reason))
                out.append(Settled(d.id, UNUSED, reason=reason))
        return out

    @staticmethod
    def _prune(s: Session) -> None:
        """Au plus ``KEEP_PER_CONVERSATION`` messages par conversation, les plus récents. Les messages en trop se
        lisent d'abord, puis partent (MariaDB refuse de supprimer d'une table en relisant la même dans la
        condition)."""
        ranked = select(MessageRow.id, func.row_number().over(
            partition_by=(MessageRow.account, MessageRow.conversation),
            order_by=(MessageRow.at.desc(), MessageRow.id.desc())
        ).label("rank")).subquery()
        beyond = s.scalars(select(ranked.c.id).where(ranked.c.rank > KEEP_PER_CONVERSATION)).all()
        if beyond:
            s.execute(delete(MessageRow).where(MessageRow.id.in_(beyond)))

    # ── ce qu'elle remarque ──
    async def fetch_new(self, limit: int, *, accounts: Sequence[str] | None = None) -> list[Message]:
        with self._lock, self._session() as s:
            rows = s.execute(select(*_MESSAGE).where(MessageRow.acked == false(), MessageRow.own == false(),
                                                     *_in_accounts(MessageRow.account, accounts))
                             .order_by(MessageRow.at, MessageRow.id).limit(max(0, limit))).all()
        return [Message(*r) for r in rows]

    def ack(self, refs: Sequence[str]) -> None:
        if not refs:
            return
        with self._lock, self._session.begin() as s:
            s.execute(update(MessageRow).where(MessageRow.ref.in_(list(refs))).values(acked=True))

    def message(self, ref: str) -> Message | None:
        with self._lock, self._session() as s:
            row = s.execute(select(*_MESSAGE).where(MessageRow.ref == ref)).first()
        return Message(*row) if row else None

    def thread(self, account: str, conversation: str, limit: int, *, before: int = 0) -> list[Message]:
        where = [MessageRow.account == _account_key(account),
                 MessageRow.conversation == fit(conversation, CONVERSATION_MAX)]
        if before:
            where.append(MessageRow.at < before)
        with self._lock, self._session() as s:
            rows = s.execute(select(*_MESSAGE).where(*where).order_by(MessageRow.at.desc(), MessageRow.id.desc())
                             .limit(max(0, limit))).all()
        return [Message(*r) for r in reversed(rows)]

    @staticmethod
    def _conversation_in(s: Session, account: str, conversation: str) -> Conversation | None:
        row = s.execute(select(*_CONVERSATION, _counted(), ConversationRow.account)
                        .where(ConversationRow.account == _account_key(account),
                               ConversationRow.id == fit(conversation, CONVERSATION_MAX))).first()
        return _conversation(row) if row else None

    def conversation(self, account: str, conversation: str) -> Conversation | None:
        with self._lock, self._session() as s:
            return self._conversation_in(s, account, conversation)

    def conversations(self, limit: int, *, text: str = "", accounts: Sequence[str] | None = None) \
            -> list[Conversation]:
        """Les conversations où quelque chose a été écrit (de ces comptes ; ``None`` : de tous), la plus récente
        d'abord ; ``text`` cherché dans le titre et l'identifiant, casse et accents ignorés (les deux côtés
        repliés, comparés par ``instr`` : pareil sur les deux moteurs, ``%`` et ``_`` n'y sont que des
        caractères)."""
        where = [ConversationRow.last_at > 0, *_in_accounts(ConversationRow.account, accounts)]
        if folded := fold_text(text.strip()):
            where.append(or_(func.instr(ConversationRow.title_fold, folded) > 0,
                             func.instr(ConversationRow.id_fold, folded) > 0))
        with self._lock, self._session() as s:
            rows = s.execute(select(*_CONVERSATION, _counted(), ConversationRow.account).where(*where)
                             .order_by(ConversationRow.last_at.desc(), ConversationRow.account, ConversationRow.id)
                             .limit(max(0, limit))).all()
        return [_conversation(r) for r in rows]

    def _title_in(self, s: Session, account: str, conversation: str) -> str:
        found = self._conversation_in(s, account, conversation)
        if found is not None and found.title:
            return found.title
        name = s.scalar(select(MessageRow.author)
                        .where(MessageRow.account == _account_key(account),
                               MessageRow.conversation == fit(conversation, CONVERSATION_MAX),
                               MessageRow.own == false(), MessageRow.author != "")
                        .order_by(MessageRow.at.desc(), MessageRow.id.desc()).limit(1))
        return str(name) if name else ""

    def title(self, account: str, conversation: str) -> str:
        """Le nom d'une conversation : celui de Teams, sinon (un tête-à-tête) l'autre personne."""
        with self._lock, self._session() as s:
            return self._title_in(s, account, conversation)

    # ── ses brouillons ──
    @staticmethod
    def _write(s: Session, d: Draft) -> Draft:
        """Écrit un brouillon tout entier : la ligne d'avant part, la nouvelle prend le numéro suivant (l'ordre de la
        dernière écriture, qui départage deux brouillons du même instant)."""
        key = fit(d.id, REF_MAX)
        s.execute(delete(DraftRow).where(DraftRow.draft_id == key))
        s.add(DraftRow(draft_id=key, account=_account_key(d.account), conversation=fit(d.conversation, CONVERSATION_MAX),
                       body=d.body,
                       reply_to=d.reply_to, author=d.author, created=d.created, updated=d.updated, state=d.state,
                       mode=d.mode, digest=d.digest, final=d.final, expires_at=d.expires_at, placed_at=d.placed_at,
                       sent_at=d.sent_at, sent_text=d.sent_text, edited=d.edited, edited_by=d.edited_by,
                       reason=d.reason))
        return d

    def save_draft(self, d: Draft) -> Draft:
        now = self._now()
        if not d.id:
            d = replace(d, id=f"t{uuid.uuid4().hex[:12]}", created=now)
        with self._lock, self._session.begin() as s:
            return self._write(s, replace(d, updated=now))

    @staticmethod
    def _draft_in(s: Session, draft_id: str) -> Draft | None:
        row = s.execute(select(*_DRAFT).where(DraftRow.draft_id == fit(draft_id, REF_MAX))).first()
        return _draft(row) if row else None

    def draft(self, draft_id: str) -> Draft | None:
        with self._lock, self._session() as s:
            return self._draft_in(s, draft_id)

    def drafts(self, limit: int, *, state: str = "", accounts: Sequence[str] | None = None) -> list[Draft]:
        where = [*([DraftRow.state == state] if state else []), *_in_accounts(DraftRow.account, accounts)]
        with self._lock, self._session() as s:
            rows = s.execute(select(*_DRAFT).where(*where).order_by(DraftRow.updated.desc(), DraftRow.id.desc())
                             .limit(max(0, limit))).all()
        return [_draft(r) for r in rows]

    def discard_draft(self, draft_id: str) -> None:
        with self._lock, self._session.begin() as s:
            found = self._draft_in(s, draft_id)
            if found is not None and found.state == WRITTEN:
                self._write(s, replace(found, state=DISCARDED, updated=self._now()))

    def _final(self, s: Session, d: Draft, her: str) -> str:
        signature = self._voice_in(s, d.account).signature.replace(HER, her.strip() or "son IA")
        return f"{d.body.strip()}\n\n{signature}" if signature else d.body.strip()

    def _preview_in(self, s: Session, draft_id: str, her: str) -> Preview | None:
        d = self._draft_in(s, draft_id)
        if d is None:
            return None
        text = d.final if d.state != WRITTEN and d.final else self._final(s, d, her)
        digest = hashlib.sha256(f"{d.conversation}\n{text}".encode()).hexdigest()[:32]
        blocked = ""
        if d.state != WRITTEN:
            blocked = "il n'est plus à envoyer (déjà en file, parti ou abandonné)"
        elif to_fill(d.body):
            blocked = "il reste des passages [À COMPLÉTER] à remplir"
        elif not d.body.strip():
            blocked = "il est vide"
        return Preview(d.conversation, self._title_in(s, d.account, d.conversation), text, digest, blocked)

    def preview(self, draft_id: str, *, her: str = "") -> Preview | None:
        with self._lock, self._session() as s:
            return self._preview_in(s, draft_id, her)

    # ── la file ──
    def enqueue(self, draft_id: str, *, mode: str, digest: str, expires_at: int, now: int, her: str = "") -> str:
        with self._lock, self._session.begin() as s:
            d = self._draft_in(s, draft_id)
            if d is None:
                return "ce brouillon n'existe plus"
            if d.state in (QUEUED, PLACED, GONE) and d.digest == digest:
                return ""  # déjà fait : rejoué après un arrêt
            shown = self._preview_in(s, draft_id, her)
            if shown is None or d.state != WRITTEN:
                return "il n'est plus à envoyer"
            if digest and shown.digest != digest:
                return "il a changé depuis qu'on l'a montré"
            if shown.blocked and (mode == SEND or not to_fill(d.body)):
                return shown.blocked  # posé dans Teams, un « à compléter » se remplit ; envoyé, jamais
            self._write(s, replace(d, state=QUEUED, mode=mode, digest=shown.digest, final=shown.text,
                                   expires_at=expires_at, updated=now))
        return ""

    def outbox(self, account: str, now: int) -> list[OutboxItem]:
        """Ce que l'extension de ce compte doit poser ou envoyer (jamais ce qui part d'un autre compte)."""
        out = []
        with self._lock, self._session() as s:
            # un envoi réservé n'est plus offert : le navigateur qui l'a réservé l'envoie, aucun autre
            rows = s.execute(select(*_DRAFT).where(DraftRow.account == _account_key(account),
                                                   DraftRow.state.in_((QUEUED, PLACED)))
                             .order_by(DraftRow.updated, DraftRow.id)).all()
            for d in (_draft(r) for r in rows):
                if d.expires_at and d.expires_at <= now:
                    continue
                found = self._conversation_in(s, d.account, d.conversation)
                out.append(OutboxItem(d.id, d.conversation, self._title_in(s, d.account, d.conversation),
                                      found.kind if found is not None else "other", d.mode,
                                      "placed" if d.state == PLACED else "queued", d.final, d.updated // 1000,
                                      d.expires_at // 1000))
        return out

    def settle(self, draft_id: str, result: str, *, now: int, text: str = "", reason: str = "",
               account: str = "") -> tuple[str, Settled | None]:
        with self._lock, self._session.begin() as s:
            d = self._draft_in(s, draft_id)
            if d is None or (d.state not in (*OPEN_STATES, GONE, FAILED, UNUSED)):
                return MISSING, None
            if account and d.account != _account_key(account):
                return MISSING, None  # le brouillon d'un autre compte : l'extension de celui-ci ne le connaît pas
            if result == "sending":
                if d.state != QUEUED or d.mode != SEND:
                    return CONFLICT, None  # déjà réservé (ailleurs, ou par un essai d'avant), réglé, ou à poser
                self._write(s, replace(d, state=SENDING, updated=now))
                return ACCEPTED, None
            if result == "placed":
                if d.state == PLACED:
                    return ACCEPTED, None
                if d.state != QUEUED or d.mode != DRAFT:
                    return CONFLICT, None
                done = Settled(d.id, PLACED)
                self._write(s, replace(d, state=PLACED, placed_at=now))
            elif result == "sent":
                if d.state == GONE:
                    return ACCEPTED, None
                # un accusé tardif (après l'échéance) dit la vérité : il est parti
                if d.state not in (*OPEN_STATES, FAILED, UNUSED):
                    return CONFLICT, None
                edited = bool(text) and _edited(text, d)
                done = Settled(d.id, GONE, edited=edited)
                self._write(s, replace(d, state=GONE, sent_at=now, sent_text=text or d.final, edited=edited))
            elif result == "failed":
                if d.state == FAILED:
                    return ACCEPTED, None
                if d.state not in OPEN_STATES:
                    return CONFLICT, None
                why = reason.strip()[:300] or "l'extension n'a pas pu le faire"
                done = Settled(d.id, FAILED, reason=why)
                self._write(s, replace(d, state=FAILED, reason=why))
            elif result == "expired":
                if d.state not in OPEN_STATES:
                    return ACCEPTED, None
                if d.state == SENDING:
                    done = Settled(d.id, FAILED, reason="incertain : l'envoi a commencé sans qu'on sache s'il est parti "
                                                         "(à vérifier dans Teams)")
                    self._write(s, replace(d, state=FAILED, reason=done.reason))
                elif d.mode == SEND:
                    done = Settled(d.id, FAILED, reason="jamais envoyé : l'extension ne l'a pas relevé à temps")
                    self._write(s, replace(d, state=FAILED, reason=done.reason))
                else:
                    done = Settled(d.id, UNUSED, reason="personne ne l'a envoyé à temps")
                    self._write(s, replace(d, state=UNUSED, reason=done.reason))
            else:
                return CONFLICT, None
        return ACCEPTED, done

    # ── l'oubli ──
    def drop_account(self, account: str) -> int:
        """Un compte supprimé des réglages (ADR 0186) : ses conversations, ses messages, ses brouillons et ce que son
        extension en avait dit s'effacent ; le nombre de lignes effacées."""
        key = _account_key(account)
        with self._lock, self._session.begin() as s:
            n = 0
            for row in (DraftRow, MessageRow, ConversationRow):
                n += _count(s.execute(delete(row).where(row.account == key)))
            n += _count(s.execute(delete(AccountRow).where(AccountRow.key == key)))
        return n

    async def forget(self, subject: str) -> int:
        """Oublier quelqu'un (``teams:<identifiant>``), dans tous les comptes : ses messages, et ses tête-à-tête
        entiers (ce qui y a été écrit, les brouillons qui y répondaient, la conversation elle-même)."""
        if not subject.startswith("teams:"):
            return 0
        author = subject[len("teams:"):].strip().lower()
        if not author:
            return 0
        key = fit(author, AUTHOR_MAX)
        with self._lock, self._session.begin() as s:
            # ses tête-à-tête : le genre que Teams leur donne, ou leur identifiant (le suffixe comparé ici, en
            # minuscules, pareil sur les deux moteurs)
            pairs = s.execute(select(MessageRow.account, MessageRow.conversation, ConversationRow.kind).distinct()
                              .join_from(MessageRow, ConversationRow,
                                         and_(ConversationRow.account == MessageRow.account,
                                              ConversationRow.id == MessageRow.conversation), isouter=True)
                              .where(MessageRow.author_key == key)).all()
            convs = sorted({(account, conv) for account, conv, kind in pairs
                            if kind == "dm" or conv.lower().endswith(_DM_SUFFIX)})
            # les réponses à ses messages, ailleurs (un groupe) : elles citent ce qu'il a écrit
            n = _count(s.execute(delete(DraftRow).where(
                DraftRow.reply_to.in_(select(MessageRow.ref).where(MessageRow.author_key == key)))))
            n += _count(s.execute(delete(MessageRow).where(MessageRow.author_key == key)))
            for account, conv in convs:
                n += _count(s.execute(delete(MessageRow).where(MessageRow.account == account,
                                                               MessageRow.conversation == conv)))
                n += _count(s.execute(delete(DraftRow).where(DraftRow.account == account,
                                                             DraftRow.conversation == conv)))
                s.execute(delete(ConversationRow).where(ConversationRow.account == account,
                                                        ConversationRow.id == conv))
        return n

    def close(self) -> None:
        with self._lock:
            self._engine.dispose()
