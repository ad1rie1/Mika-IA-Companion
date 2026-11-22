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
- **Les profils des personnes croisées** (ADR 0298) arrivent avec les lots : gardés par compte et par personne, chaque
  changement prend un rang qui ne resert jamais (``profiles_since`` : l'annuaire les relit dans cet ordre).
"""

from __future__ import annotations

import difflib
import hashlib
import re
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from sqlalchemy import and_, case, delete, false, func, or_, select, true, update
from sqlalchemy.orm import Session, aliased, sessionmaker

from mika.adapters.database import Target, as_target
from mika.adapters.teams.config import HER, TeamsConfig
from mika.adapters.teams.models import (
    ACCOUNT_MAX,
    AUTHOR_MAX,
    CONVERSATION_MAX,
    REF_MAX,
    AccountRow,
    ConversationRow,
    CounterRow,
    DraftRow,
    ImageRow,
    MessageRow,
    ProfileRow,
    fit,
)
from mika.contracts import teams as teams_c
from mika.ports.drafts import to_fill
from mika.ports.gate import ACCEPTED, CONFLICT, MISSING
from mika.ports.paging import fold_text
from mika.ports.sql import TEAMS
from mika.ports.teams import (
    DISCARDED,
    FAILED,
    GONE,
    IMAGE_KEPT,
    IMAGE_KNOWN,
    IMAGE_NO_MESSAGE,
    OPEN_STATES,
    OUTBOX_PLACE,
    OUTBOX_SEND,
    PLACED,
    QUEUED,
    SENDING,
    UNUSED,
    WRITTEN,
    AccountInfo,
    Conversation,
    Draft,
    ImageIn,
    ImageToRead,
    InboxBatch,
    InboxProfile,
    Message,
    MessageImage,
    OutboxItem,
    PeopleSince,
    Preview,
    ProfilesSince,
    SeenAuthor,
    Settled,
    Stored,
    TeamsProfile,
    Voice,
    message_ref,
    plain,
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
#: un même message sous deux identifiants (sa version en attente dans Teams puis celle du service, ou deux sources de
#: l'extension : le worker de Teams, sa base locale, l'historique) : même conversation, même auteur, même texte, à
#: moins de tant de µs l'un de l'autre — le second est un jumeau, laissé de côté (ADR 0251)
TWIN_WINDOW = 120 * 1_000_000


#: les images (ADR 0258) : la place des images d'un compte, au plus — les plus
#: anciennes partent au-delà ; un message aux images annoncées attend au plus tant (µs) avant d'être remarqué ; une
#: image que la lecture n'a pas pu regarder (un échec passager) est retentée tant de fois ; ce que Mika y a vu tient
#: dans le texte du message en tant de caractères au plus
IMAGES_PER_ACCOUNT_BYTES = 500 * 1024 * 1024
IMAGE_HOLD = 3 * 60 * 1_000_000
IMAGE_TRIES = 3
IMAGE_SEEN_IN_TEXT = 500
#: « [image] » dans le texte d'un message, ou « [image : ce qu'elle y a vu] »
_IMAGE_MARK = re.compile(r"\[image(?: : [^\]\n]*)?\]")


def described(text: str, seen: Mapping[int, str]) -> str:
    """Le texte d'un message, où la n-ième image (``seen`` : son rang → ce que Mika y a vu) se dit « [image : …] ».
    Une image vue sans marque à son rang (une version d'avant de l'extension) s'ajoute à la fin."""
    marks = list(_IMAGE_MARK.finditer(text))
    out, last = [], 0
    for rank, mark in enumerate(marks):
        out.append(text[last:mark.start()])
        said = " ".join(seen.get(rank, "").replace("]", ")").split())[:IMAGE_SEEN_IN_TEXT]
        out.append(f"[image : {said}]" if said else mark.group(0))
        last = mark.end()
    out.append(text[last:])
    extra = [" ".join(v.replace("]", ")").split())[:IMAGE_SEEN_IN_TEXT] for k, v in sorted(seen.items())
             if k >= len(marks) and v.strip()]
    return "".join(out) + "".join(f" [image : {e}]" for e in extra)


#: l'historique n'est rangé « déjà lu » qu'au-delà de la fenêtre du direct (µs) : un message plus récent, arrivé
#: d'abord par un paquet d'historique, se range comme du direct (elle le remarque, il règle ses brouillons)
HISTORY_LIVE_WINDOW = 24 * 3600 * 1_000_000
#: le compteur des rangs des profils (ADR 0298, ``counters``)
PROFILES_COUNTER = "profiles"
#: ce qu'un profil garde, dans l'ordre de ``TeamsProfile`` (après le compte et l'identifiant)
_PROFILE_FIELDS = ("name", "email", "title", "company", "department", "tenant", "phones")


def id_kind(external_id: str) -> str:
    """La sorte d'un identifiant de message Teams : ``service`` (l'heure d'arrivée en ms, 13 chiffres — 16 au plus),
    ``client`` (celui que le client lui donne tant qu'il attend, plus long), ``empreinte`` (« h… », tirée du contenu
    par l'extension faute d'identifiant), ``autre``."""
    if external_id.isdigit():
        return "service" if len(external_id) <= 16 else "client"
    return "empreinte" if external_id.startswith("h") else "autre"


def maybe_same_message(a: str, b: str) -> bool:
    """Deux identifiants qui peuvent nommer le même message : de sortes différentes parmi le service, le client et
    l'empreinte (``id_kind``). Deux identifiants de la même sorte sont deux messages : un « ok » redit dans la minute
    n'est pas un doublon, deux empreintes non plus."""
    ka, kb = id_kind(a), id_kind(b)
    return a != b and ka != kb and "autre" not in (ka, kb)

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

#: un identifiant de personne de Teams, quelle que soit sa forme (« 8:orgid:<uuid> », « orgid:<uuid> », une adresse qui
#: finit par « /contacts/8:orgid:<uuid> »…)
_ORGID = re.compile(r"orgid:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.IGNORECASE)


def same_person(author_id: str, self_id: str) -> bool:
    """Deux identifiants de Teams désignent la même personne : le même uuid d'organisation, sinon la même chaîne."""
    a, b = _ORGID.search(author_id or ""), _ORGID.search(self_id or "")
    if a and b:
        return a.group(1).lower() == b.group(1).lower()
    return bool(author_id.strip()) and author_id.strip().lower() == (self_id or "").strip().lower()


def written_by_self(author_id: str, author: str, self_id: str, self_name: str) -> bool:
    """Un message de la personne du compte, que l'extension l'ait dit ou non : son identifiant, ou — sans identifiant —
    son nom tel que Teams l'affiche. L'extension ne reconnaissait plus ses messages captés en direct (ADR 0251) quand
    leur auteur n'avait pas la forme exacte attendue : le serveur, qui connaît le compte, ne s'y fie plus seul. Ce qui
    avait été rangé de travers ne se convertit pas : on l'efface (``mika teams purge``) et on recharge l'historique."""
    if self_id and author_id and same_person(author_id, self_id):
        return True
    return not (author_id or "").strip() and bool(self_name.strip()) and author.strip() == self_name.strip()
#: un groupe où l'on échange vraiment (``exchanged``, ADR 0298) : au plus tant d'auteurs, la personne du compte comprise
EXCHANGE_GROUP_MAX = 8


def _one_to_one(kind: str | None, conversation: str) -> bool:
    """Un tête-à-tête : le genre que Teams lui donne, ou son identifiant (le suffixe comparé en minuscules)."""
    return kind == "dm" or conversation.lower().endswith(_DM_SUFFIX)


def _is_one_to_one() -> Any:
    """La même règle dans une requête, sur la conversation qu'elle lit (pareil sur les deux moteurs)."""
    return or_(ConversationRow.kind == "dm", func.lower(ConversationRow.id).like(f"%{_DM_SUFFIX}"))


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


def _named() -> Any:
    """Le nom d'une conversation (corrélé à la requête qui l'appelle), celui que rend ``title`` : pour un
    tête-à-tête, le dernier à y avoir écrit qui n'est pas la personne du compte, sinon ce que Teams en dit ; pour
    toute autre, celui de Teams, sinon rien — dans la requête de la liste, pas une de plus par ligne."""
    other = (select(MessageRow.author)
             .where(MessageRow.account == ConversationRow.account, MessageRow.conversation == ConversationRow.id,
                    MessageRow.own == false(), MessageRow.author != "")
             .order_by(MessageRow.at.desc(), MessageRow.id.desc()).limit(1).scalar_subquery())
    teams = func.nullif(ConversationRow.title, "")
    return func.coalesce(case((_is_one_to_one(), func.coalesce(other, teams)), else_=teams), "")


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
        """Un lot poussé par l'extension de ce compte : rangé sous lui seul. Un message se reconnaît à sa référence
        (sa conversation et son identifiant) ou à son alias : déjà là, il est connu (son texte suit une retouche) ;
        sinon, un jumeau — le même message déjà rangé sous un autre identifiant (``_twin``) — n'est pas rangé une
        seconde fois : sa référence devient l'alias de la ligne, et une retouche ou une suppression qui arrive sous
        elle la retrouve. L'historique (``batch.history``) se range déjà lu, sans régler de brouillon, au-delà de la
        fenêtre du direct (``HISTORY_LIVE_WINDOW``) : en deçà, il se range comme du direct."""
        new = known = twins = recent = 0
        touched: set[str] = set()
        replied: dict[str, int] = {}
        settled: list[Settled] = []
        key = _account_key(account)
        with self._lock, self._session.begin() as s:
            acct = self._account_in(s, key)
            if acct is None:
                acct = AccountRow(key=key, last_batch=0, self_id="", self_name="")
                s.add(acct)
            if batch.self_id:
                acct.self_id = batch.self_id
            if batch.self_name:
                acct.self_name = batch.self_name
            acct.last_batch = now
            self_id, self_name = acct.self_id or "", acct.self_name or ""
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
                row = s.scalars(select(MessageRow).where(or_(MessageRow.ref == ref, MessageRow.alias == ref))).first()
                if m.deleted:  # supprimé dans Teams : son texte part du cache (jamais remarqué s'il ne l'était pas)
                    if row is not None:
                        known += 1
                        row.text, row.acked = "", True
                    continue
                own = m.own or written_by_self(m.author_id, m.author, self_id, self_name)
                if row is not None:  # déjà connu (rejoué, ou retouché dans Teams : son texte suit)
                    known += 1
                    text = self._with_images(s, row.ref, m.text)
                    if row.text != text:
                        row.text = text
                    continue
                conv = fit(m.conversation, CONVERSATION_MAX)
                author_key = fit(m.author_id.strip().lower(), AUTHOR_MAX)
                twin = self._twin(s, key, conv, author_key, at, m.id, m.text)
                if twin is not None:
                    twin.alias = ref
                    twins += 1
                    continue
                live = not batch.history or at >= now - HISTORY_LIVE_WINDOW
                new += 1
                recent += live
                touched.add(conv)
                s.add(MessageRow(ref=ref, account=key, conversation=conv, external_id=m.id, author=m.author,
                                 author_id=m.author_id, author_key=author_key, at=at, text=m.text, own=own,
                                 mentions_me=m.mentions_me, received=now, acked=own or not live,
                                 images_pending=max(0, min(m.images, 8))))
                found = self._conversation_row(s, seen, key, conv)
                found.last_at = max(found.last_at or 0, at)
                if own and live:
                    replied[conv] = max(replied.get(conv, 0), at)
                    settled.extend(self._answered_by_owner(s, key, conv, at, m.text, now))
            if touched:
                self._prune(s, key, touched)
            profiles = self._keep_profiles(s, key, batch.profiles, now) if batch.profiles else 0
        return Stored(new=new, known=known, replied=tuple(sorted(replied.items())), settled=tuple(settled),
                      twins=twins, recent=recent, profiles=profiles)

    # ── les profils des personnes croisées (l'annuaire, ADR 0298) ──
    @staticmethod
    def _profile_counter(s: Session) -> CounterRow:
        """Le compteur des rangs : jamais sous le plus haut rang gardé (une base d'avant ce compteur, une ligne
        perdue)."""
        row = s.get(CounterRow, PROFILES_COUNTER)
        if row is None:
            row = CounterRow(name=PROFILES_COUNTER, value=0)
            s.add(row)
        row.value = max(int(row.value or 0), int(s.scalar(select(func.max(ProfileRow.seq))) or 0))
        return row

    def _keep_profiles(self, s: Session, account: str, profiles: Sequence[InboxProfile], now: int) -> int:
        """Les profils d'un lot, sous son compte : un profil neuf, ou qui a changé, prend le rang suivant (et
        ``updated`` : maintenant) ; redit tel quel, rien ne bouge. Le dernier d'une même personne dans le lot
        l'emporte. Rend combien ont changé."""
        latest: dict[str, InboxProfile] = {}
        for p in profiles:
            if (found := fit(p.id.strip().lower(), AUTHOR_MAX)):
                latest[found] = p
        counter: CounterRow | None = None
        changed = 0
        for person, p in sorted(latest.items()):
            values = {"name": p.name, "email": p.email, "title": p.title, "company": p.company,
                      "department": p.department, "tenant": p.tenant, "phones": "\n".join(p.phones)}
            row = s.get(ProfileRow, (account, person))
            if row is not None and all((getattr(row, k) or "") == v for k, v in values.items()):
                continue
            counter = counter or self._profile_counter(s)
            counter.value = int(counter.value) + 1
            if row is None:
                row = ProfileRow(account=account, key=person, **values)
                s.add(row)
            else:
                for k, v in values.items():
                    setattr(row, k, v)
            row.updated, row.seq = now, counter.value
            changed += 1
        return changed

    def profiles_since(self, cursor: int, limit: int) -> ProfilesSince:
        """Les profils de rang au-delà de ``cursor``, dans l'ordre des rangs. Un curseur au-delà du compteur (une
        base ``teams`` revenue d'une sauvegarde plus ancienne) repart du compteur : les profils qui changeront ensuite
        ne sont pas sautés."""
        limit = max(1, min(5000, int(limit)))
        # son dernier message dans ce compte : ce que le profil atteste (l'heure de Teams, pas celle de sa réception)
        said = (select(func.max(MessageRow.at)).where(MessageRow.account == ProfileRow.account,
                                                      MessageRow.author_key == ProfileRow.key)
                .scalar_subquery().label("said_at"))
        with self._lock, self._session() as s:
            top = s.scalar(select(CounterRow.value).where(CounterRow.name == PROFILES_COUNTER))
            top = max(int(top or 0), int(s.scalar(select(func.max(ProfileRow.seq))) or 0))
            after = min(max(0, int(cursor)), top)
            rows = s.execute(select(ProfileRow.account, ProfileRow.key, *(getattr(ProfileRow, f) for f in
                                                                          _PROFILE_FIELDS),
                                    ProfileRow.updated, ProfileRow.seq, said)
                             .where(ProfileRow.seq > after).order_by(ProfileRow.seq).limit(limit)).all()
        found = tuple(TeamsProfile(r.account, r.key, r.name or "", r.email or "", r.title or "", r.company or "",
                                   r.department or "", r.tenant or "",
                                   tuple(n for n in (r.phones or "").split("\n") if n), int(r.updated or 0),
                                   int(r.seq), int(r.said_at or 0)) for r in rows)
        return ProfilesSince(found, found[-1].seq if found else after, len(rows) == limit)

    @staticmethod
    def _twin(s: Session, account: str, conversation: str, author_key: str, at: int, external_id: str,
              text: str) -> MessageRow | None:
        """La ligne du même message, déjà rangé sous un autre identifiant : même conversation, même auteur, même
        texte (aux espaces près), à moins de ``TWIN_WINDOW``, des identifiants de sortes différentes
        (``maybe_same_message``), et pas encore d'alias — une ligne qui a déjà trouvé son jumeau n'en prend pas un
        second : le même « ok » redit depuis un autre appareil reste un message."""
        wanted = " ".join(text.split())
        rows = s.scalars(select(MessageRow).where(
            MessageRow.account == account, MessageRow.conversation == conversation,
            MessageRow.author_key == author_key, MessageRow.alias == "", MessageRow.at >= at - TWIN_WINDOW,
            MessageRow.at <= at + TWIN_WINDOW).order_by(MessageRow.at, MessageRow.id)).all()
        return next((r for r in rows if maybe_same_message(r.external_id, external_id)
                     and " ".join(r.text.split()) == wanted), None)

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
            elif d.mode == OUTBOX_PLACE:
                reason = "tu as écrit autre chose" if d.state == PLACED else "tu as répondu toi-même"
                self._write(s, replace(d, state=UNUSED, reason=reason))
                out.append(Settled(d.id, UNUSED, reason=reason))
        return out

    @staticmethod
    def _prune(s: Session, account: str, conversations: set[str]) -> None:
        """Au plus ``KEEP_PER_CONVERSATION`` messages par conversation, les plus récents, pour les conversations qu'un
        lot vient de toucher (les autres n'ont pas grandi). Les messages en trop se lisent d'abord, puis partent
        (MariaDB refuse de supprimer d'une table en relisant la même dans la condition)."""
        ranked = select(MessageRow.id, func.row_number().over(
            partition_by=(MessageRow.account, MessageRow.conversation),
            order_by=(MessageRow.at.desc(), MessageRow.id.desc())
        ).label("rank")).where(MessageRow.account == account,
                               MessageRow.conversation.in_(sorted(conversations))).subquery()
        beyond = s.scalars(select(ranked.c.id).where(ranked.c.rank > KEEP_PER_CONVERSATION)).all()
        if beyond:
            gone = s.scalars(select(MessageRow.ref).where(MessageRow.id.in_(beyond))).all()
            s.execute(delete(ImageRow).where(ImageRow.ref.in_(gone)))
            s.execute(delete(MessageRow).where(MessageRow.id.in_(beyond)))

    # ── les images (ADR 0258) ──
    @staticmethod
    def _with_images(s: Session, ref: str, text: str) -> str:
        """Le texte d'un message, avec ce que Mika a vu de ses images."""
        seen = {pos: v for pos, v in s.execute(select(ImageRow.position, ImageRow.seen).where(
            ImageRow.ref == ref, ImageRow.seen != "")).all()}
        return described(text, seen) if seen else text

    def keep_image(self, account: str, image: ImageIn, now: int) -> str:
        """Garder une image de ce message (retrouvé par sa référence ou son alias) ; la même image redite n'en fait
        qu'une ; au-delà de la place du compte, les plus anciennes partent."""
        key = _account_key(account)
        ref = message_ref(image.conversation, image.message_id, key)
        with self._lock, self._session.begin() as s:
            row = s.scalars(select(MessageRow).where(MessageRow.account == key,
                                                     or_(MessageRow.ref == ref, MessageRow.alias == ref))).first()
            if row is None:
                return IMAGE_NO_MESSAGE
            if s.scalars(select(ImageRow.id).where(ImageRow.ref == row.ref, ImageRow.image == image.image)).first():
                return IMAGE_KNOWN
            s.add(ImageRow(ref=row.ref, account=key, image=image.image, position=image.position, mime=image.mime,
                           size=len(image.data), data=image.data, at=now, seen="", read=False, sensitive=False, tries=0))
            if row.images_pending > 0:
                row.images_pending -= 1
            s.flush()
            self._prune_images(s, key)
        return IMAGE_KEPT

    @staticmethod
    def _prune_images(s: Session, account: str) -> None:
        """La place des images d'un compte : au-delà de ``IMAGES_PER_ACCOUNT_BYTES``, les plus anciennes partent."""
        rows = s.execute(select(ImageRow.id, ImageRow.size).where(ImageRow.account == account)
                         .order_by(ImageRow.at.desc(), ImageRow.id.desc())).all()
        total, beyond = 0, []
        for image_id, size in rows:
            total += size or 0
            if total > IMAGES_PER_ACCOUNT_BYTES:
                beyond.append(image_id)
        if beyond:
            s.execute(delete(ImageRow).where(ImageRow.id.in_(beyond)))

    def image_to_read(self) -> ImageToRead | None:
        with self._lock, self._session() as s:
            row = s.execute(select(ImageRow.id, ImageRow.ref, ImageRow.image, ImageRow.mime, ImageRow.data)
                            .where(ImageRow.read == false()).order_by(ImageRow.at, ImageRow.id).limit(1)).first()
        return ImageToRead(*row) if row else None

    def image_read(self, image_id: int, *, seen: str, sensitive: bool, read: bool) -> str:
        """Ce que Mika a vu d'une image ; un échec passager (``read`` faux) la laisse à regarder, ``IMAGE_TRIES``
        fois au plus (puis elle est tenue pour lue, sans rien). Le texte de son message suit."""
        with self._lock, self._session.begin() as s:
            row = s.get(ImageRow, image_id)
            if row is None:
                return ""
            row.tries += 1
            if read or row.tries >= IMAGE_TRIES:
                row.read = True
                row.seen = seen if read else ""
                row.sensitive = sensitive
            message = s.scalars(select(MessageRow).where(MessageRow.ref == row.ref)).first()
            if message is not None and row.read and row.seen:
                s.flush()
                message.text = self._with_images(s, row.ref, message.text)
            return row.ref

    def images_of(self, refs: Sequence[str]) -> list[MessageImage]:
        if not refs:
            return []
        with self._lock, self._session() as s:
            rows = s.execute(select(ImageRow.ref, ImageRow.image, ImageRow.position, ImageRow.mime, ImageRow.size,
                                    ImageRow.seen, ImageRow.read).where(ImageRow.ref.in_(list(refs)))
                             .order_by(ImageRow.ref, ImageRow.position, ImageRow.id)).all()
        return [MessageImage(*r) for r in rows]

    def image_bytes(self, ref: str, image: str) -> tuple[str, bytes] | None:
        with self._lock, self._session() as s:
            row = s.execute(select(ImageRow.mime, ImageRow.data).where(ImageRow.ref == ref,
                                                                       ImageRow.image == image)).first()
        return (row[0], bytes(row[1])) if row else None

    # ── ce qu'elle remarque ──
    async def fetch_new(self, limit: int, *, accounts: Sequence[str] | None = None) -> list[Message]:
        """Les messages à remarquer ; un message dont des images sont annoncées et pas arrivées, ou arrivées et pas
        encore regardées, attend (``IMAGE_HOLD`` au plus) : elle le remarque déjà décrit (ADR 0258)."""
        unread = select(ImageRow.id).where(ImageRow.ref == MessageRow.ref, ImageRow.read == false()).exists()
        waiting = and_(or_(MessageRow.images_pending > 0, unread), MessageRow.received > self._now() - IMAGE_HOLD)
        with self._lock, self._session() as s:
            rows = s.execute(select(*_MESSAGE).where(MessageRow.acked == false(), MessageRow.own == false(),
                                                     *_in_accounts(MessageRow.account, accounts), ~waiting)
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

    def last_messages(self, conversations: Sequence[tuple[str, str]]) -> dict[tuple[str, str], Message]:
        """Le dernier message de chacune de ces conversations (compte, identifiant) — celui que rendrait
        ``thread(…, 1)`` —, en une seule requête quel que soit leur nombre. Une conversation sans message n'y est pas."""
        asked = {(_account_key(account), fit(cid, CONVERSATION_MAX)): (account, cid) for account, cid in conversations}
        if not asked:
            return {}
        newest = aliased(MessageRow)
        last = (select(newest.id)
                .where(newest.account == ConversationRow.account, newest.conversation == ConversationRow.id)
                .order_by(newest.at.desc(), newest.id.desc()).limit(1).correlate(ConversationRow).scalar_subquery())
        wanted = or_(*(and_(ConversationRow.account == account, ConversationRow.id == cid) for account, cid in asked))
        with self._lock, self._session() as s:
            rows = s.execute(select(*_MESSAGE).select_from(ConversationRow)
                             .join(MessageRow, MessageRow.id == last).where(wanted)).all()
        return {asked[(m.account, m.conversation)]: m for m in (Message(*r) for r in rows)}

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
        d'abord, chacune sous son nom (``title`` : l'autre personne d'un tête-à-tête, celui de Teams pour les autres —
        rien pour un groupe sans titre —, comme ``title()``) ; ``text`` cherché dans ce nom et l'identifiant, casse et
        accents ignorés (les deux côtés repliés, comparés par ``instr`` : pareil sur les deux moteurs, ``%`` et ``_``
        n'y sont que des caractères ; le nom d'un tête-à-tête se replie ici, la base ne le garde pas replié).

        ``conversation()``, lui, rend le titre de Teams tel quel : le tri y lit le nom qu'une règle d'envoi peut
        désigner (``triage.where_of``), pas l'auteur du dernier message."""
        where = [ConversationRow.last_at > 0, *_in_accounts(ConversationRow.account, accounts)]
        named = _named()
        with self._lock, self._session() as s:
            if folded := fold_text(text.strip()):
                # le nom d'un tête-à-tête (l'autre personne) n'est pas gardé replié ; son titre de Teams (ses membres,
                # toi compris) ne se cherche pas : ton nom ferait sortir tous tes tête-à-tête
                one_to_one = s.execute(select(ConversationRow.account, ConversationRow.id, named).where(
                    *where, _is_one_to_one())).all()
                by_account: dict[str, list[str]] = {}
                for account, cid, name in one_to_one:
                    if folded in fold_text(name or ""):
                        by_account.setdefault(account, []).append(cid)
                where.append(or_(and_(~_is_one_to_one(), func.instr(ConversationRow.title_fold, folded) > 0),
                                 func.instr(ConversationRow.id_fold, folded) > 0,
                                 *(and_(ConversationRow.account == account, ConversationRow.id.in_(ids))
                                   for account, ids in by_account.items())))
            rows = s.execute(select(ConversationRow.id, named, ConversationRow.kind, ConversationRow.last_at,
                                    _counted(), ConversationRow.account).where(*where)
                             .order_by(ConversationRow.last_at.desc(), ConversationRow.account, ConversationRow.id)
                             .limit(max(0, limit))).all()
        return [_conversation(r) for r in rows]

    def _title_in(self, s: Session, account: str, conversation: str) -> str:
        found = self._conversation_in(s, account, conversation)
        if found is None:  # inconnue (une conversation part toujours avec ses messages)
            return ""
        if not _one_to_one(found.kind, found.id):
            # un groupe, un canal, une réunion sans titre : jamais le nom de qui y a parlé en dernier
            return found.title or ""
        # un tête-à-tête ne se renomme pas dans Teams : son « titre » y est la liste de ses membres, toi compris
        name = s.scalar(select(MessageRow.author)
                        .where(MessageRow.account == _account_key(account),
                               MessageRow.conversation == fit(conversation, CONVERSATION_MAX),
                               MessageRow.own == false(), MessageRow.author != "")
                        .order_by(MessageRow.at.desc(), MessageRow.id.desc()).limit(1))
        return str(name) if name else found.title or ""

    def title(self, account: str, conversation: str) -> str:
        """Le nom d'une conversation. Un tête-à-tête : l'autre personne (la dernière à y avoir écrit), sinon ce que
        Teams en dit (la liste de ses membres : il ne se renomme pas). Toute autre : celui de Teams ; vide pour un
        groupe, un canal ou une réunion sans titre — le nom de qui y a parlé en dernier changerait à chaque auteur,
        et le confondrait avec le tête-à-tête de cette personne. Celui de la liste (``_named``), de l'aperçu, de la
        file que relève l'extension."""
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
        if d.author:  # écrit par la personne elle-même (ADR 0189) : sous son nom, sans la signature de son IA
            return d.body.strip()
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
            if shown.blocked and (mode == OUTBOX_SEND or not to_fill(d.body)):
                return shown.blocked  # posé dans Teams, un « à compléter » se remplit ; envoyé, jamais
            self._write(s, replace(d, state=QUEUED, mode=mode, digest=shown.digest, final=shown.text,
                                   expires_at=expires_at, updated=now))
        return ""

    def expire_written(self, account: str, now: int) -> int:
        """Ce que la personne a écrit elle-même (``author``, ADR 0189) et que personne n'a envoyé à temps : passé son
        échéance, en file ou posé, il ne part plus (``inutilise``) ; réservé par une extension qui n'a jamais rendu
        compte, on ne sait pas s'il est parti (``echec``). Ses propositions à elle ont leur échéance au journal
        (``teams.expire``) ; celles-ci n'y sont pas. Rend combien ont été réglés."""
        settled = 0
        with self._lock, self._session.begin() as s:
            rows = s.execute(select(*_DRAFT).where(DraftRow.account == _account_key(account),
                                                   DraftRow.state.in_((QUEUED, PLACED, SENDING)))).all()
            for d in (_draft(r) for r in rows):
                if not d.author or not d.expires_at or d.expires_at > now:
                    continue
                late = d.state == SENDING
                self._write(s, replace(d, state=FAILED if late else UNUSED, updated=now,
                                       reason="envoi sans nouvelles de l'extension" if late else "pas parti à temps"))
                settled += 1
        return settled

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
                if d.state != QUEUED or d.mode != OUTBOX_SEND:
                    return CONFLICT, None  # déjà réservé (ailleurs, ou par un essai d'avant), réglé, ou à poser
                self._write(s, replace(d, state=SENDING, updated=now))
                return ACCEPTED, None
            if result == "placed":
                if d.state == PLACED:
                    return ACCEPTED, None
                if d.state != QUEUED or d.mode != OUTBOX_PLACE:
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
                elif d.mode == OUTBOX_SEND:
                    done = Settled(d.id, FAILED, reason="jamais envoyé : l'extension ne l'a pas relevé à temps")
                    self._write(s, replace(d, state=FAILED, reason=done.reason))
                else:
                    done = Settled(d.id, UNUSED, reason="personne ne l'a envoyé à temps")
                    self._write(s, replace(d, state=UNUSED, reason=done.reason))
            else:
                return CONFLICT, None
        return ACCEPTED, done

    # ── qui elle lit (l'annuaire, ADR 0298) ──
    def people_since(self, cursor: tuple[int, int], limit: int) -> PeopleSince:
        """Les auteurs des ``limit`` messages suivants dans l'ordre d'arrivée (``MessageRow.id`` : l'historique chargé
        compte comme le reste), par compte et par auteur, hors des messages de la personne du compte. Le curseur est le
        dernier message parcouru et son arrivée (``received``, µs) : sous SQLite, un numéro libéré en haut (les
        derniers messages effacés : un oubli, un compte supprimé) resservira au suivant — un message du curseur parti
        ou remplacé fait relire aussi ce qui est arrivé depuis, quel que soit son numéro. Rien de neuf n'est sauté."""
        limit = max(1, min(5000, int(limit)))
        last_id, last_received = (max(0, int(c)) for c in cursor)
        with self._lock, self._session() as s:
            after = min(last_id, int(s.scalar(select(func.max(MessageRow.id))) or 0))
            where: Any = MessageRow.id > after
            if after:
                at_cursor = s.scalar(select(MessageRow.received).where(MessageRow.id == after))
                if at_cursor is None or (last_received and int(at_cursor) != last_received):
                    where = or_(MessageRow.id > after, MessageRow.received > last_received)
            rows = s.execute(select(MessageRow.id, MessageRow.account, MessageRow.author_key, MessageRow.author_id,
                                    MessageRow.author, MessageRow.at, MessageRow.own, MessageRow.received)
                             .where(where).order_by(MessageRow.id).limit(limit)).all()
        seen: dict[tuple[str, str], list[Any]] = {}
        for r in rows:
            if r.own or not r.author_key:
                continue
            got = seen.get((r.account, r.author_key))
            if got is None:
                seen[(r.account, r.author_key)] = [r.author_id or r.author_key, r.author or "", 1, r.at, r.at, r.at]
                continue
            got[2] += 1
            got[3], got[4] = min(got[3], r.at), max(got[4], r.at)
            if r.at >= got[5]:  # le nom et l'identifiant du plus récent
                got[5] = r.at
                got[0] = r.author_id or got[0]
                got[1] = r.author or got[1]
        people = tuple(SeenAuthor(account, v[0], v[1], v[2], v[3], v[4]) for (account, _), v in sorted(seen.items()))
        end = (int(rows[-1].id), int(rows[-1].received or 0)) if rows else (after, last_received)
        return PeopleSince(people, end, len(rows) == limit)

    def written_in(self, authors: Sequence[str], limit: int, *, accounts: Sequence[str] | None = None) \
            -> list[tuple[Conversation, int, int]]:
        """Les conversations où ces personnes ont écrit (``author_key`` : leur identifiant en minuscules), par compte,
        la plus récente d'abord, chacune sous son nom (``_named``, comme la liste), avec combien de leurs messages et le
        dernier ; leurs messages se comptent en une requête, chaque conversation se nomme par la sienne (``limit`` au
        plus, 50)."""
        keys = sorted({fit(a.strip().lower(), AUTHOR_MAX) for a in authors if a and a.strip()})
        limit = max(0, min(50, int(limit)))
        if not keys or not limit or (accounts is not None and not accounts):
            return []
        last = func.max(MessageRow.at)
        with self._lock, self._session() as s:
            found = s.execute(select(MessageRow.account, MessageRow.conversation, func.count(MessageRow.id), last)
                              .where(MessageRow.author_key.in_(keys), MessageRow.own == false(),
                                     *_in_accounts(MessageRow.account, accounts))
                              .group_by(MessageRow.account, MessageRow.conversation)
                              .order_by(last.desc(), MessageRow.account, MessageRow.conversation).limit(limit)).all()
            out = []
            for account, cid, n, at in found:
                row = s.execute(select(ConversationRow.id, _named(), ConversationRow.kind, ConversationRow.last_at,
                                       _counted(), ConversationRow.account)
                                .where(ConversationRow.account == account, ConversationRow.id == cid)).first()
                if row is not None:
                    out.append((_conversation(row), int(n or 0), int(at or 0)))
        return out

    def exchanged(self, since: int, *, limit: int = 2000, accounts: Sequence[str] | None = None) \
            -> list[tuple[str, str, int, int]]:
        """Les auteurs avec qui la personne du compte échange depuis ``since`` : en tête-à-tête (elle y a écrit
        depuis) ; dans un petit groupe (``EXCHANGE_GROUP_MAX`` auteurs au plus, elle comprise ; jamais un canal), un
        message auquel elle a répondu (elle a écrit après) ou qui la mentionne quand elle y a écrit. Une requête groupée
        par (compte, auteur) : un grand canal où elle a écrit une fois ne fait de personne quelqu'un avec qui elle
        échange."""
        limit = max(0, min(5000, int(limit)))
        if not limit or (accounts is not None and not accounts):
            return []
        mine, people = aliased(MessageRow), aliased(MessageRow)
        theirs, conv = MessageRow, ConversationRow
        here = and_(mine.account == theirs.account, mine.conversation == theirs.conversation, mine.own == true(),
                    mine.at >= int(since))
        replied = select(mine.id).where(here).exists()
        answered = select(mine.id).where(here, mine.at > theirs.at).exists()
        # combien d'auteurs a chaque conversation (elle comprise), comptés une fois par lecture, pas par message
        sizes = (select(people.account.label("account"), people.conversation.label("conversation"),
                        func.count(func.distinct(people.author_key)).label("n"))
                 .where(people.author_key != "").group_by(people.account, people.conversation).subquery("sizes"))
        kind = func.coalesce(conv.kind, "other")  # une conversation que Teams n'a pas décrite : « other »
        one_to_one = or_(kind == "dm", func.lower(theirs.conversation).like(f"%{_DM_SUFFIX}"))
        small = and_(kind != "channel", func.coalesce(sizes.c.n, 0) <= EXCHANGE_GROUP_MAX,
                     or_(answered, and_(theirs.mentions_me == true(), replied)))
        last = func.max(theirs.at)
        with self._lock, self._session() as s:
            rows = s.execute(select(theirs.account, theirs.author_key, func.count(theirs.id), last)
                             .select_from(theirs)
                             .join(conv, and_(conv.account == theirs.account, conv.id == theirs.conversation),
                                   isouter=True)
                             .join(sizes, and_(sizes.c.account == theirs.account,
                                               sizes.c.conversation == theirs.conversation), isouter=True)
                             .where(theirs.own == false(), theirs.author_key != "", theirs.at >= int(since),
                                    or_(and_(one_to_one, replied), and_(~one_to_one, small)),
                                    *_in_accounts(theirs.account, accounts))
                             .group_by(theirs.account, theirs.author_key)
                             .order_by(last.desc(), theirs.account, theirs.author_key).limit(limit)).all()
        return [(account, key, int(n or 0), int(at or 0)) for account, key, n, at in rows]

    def authored(self, authors: Sequence[str], *, since: int = 0, limit: int = 30,
                 accounts: Sequence[str] | None = None) -> list[Message]:
        keys = sorted({fit(a.strip().lower(), AUTHOR_MAX) for a in authors if a and a.strip()})
        limit = max(0, min(200, int(limit)))
        if not keys or not limit or (accounts is not None and not accounts):
            return []
        with self._lock, self._session() as s:
            rows = s.execute(select(*_MESSAGE).where(MessageRow.author_key.in_(keys), MessageRow.own == false(),
                                                     MessageRow.at >= int(since),
                                                     *_in_accounts(MessageRow.account, accounts))
                             .order_by(MessageRow.at.desc(), MessageRow.id.desc()).limit(limit)).all()
        return [Message(*r) for r in rows]

    # ── l'oubli ──
    def drop_account(self, account: str) -> int:
        """Un compte supprimé des réglages (ADR 0186) : ses conversations, ses messages, ses brouillons, les profils
        qu'il a reçus et ce que son extension en avait dit s'effacent ; le nombre de lignes effacées."""
        key = _account_key(account)
        with self._lock, self._session.begin() as s:
            n = 0
            for row in (DraftRow, ImageRow, MessageRow, ConversationRow, ProfileRow):
                n += _count(s.execute(delete(row).where(row.account == key)))
            n += _count(s.execute(delete(AccountRow).where(AccountRow.key == key)))
        return n

    async def forget(self, subject: str) -> int:
        """Oublier quelqu'un (``teams:<identifiant>``), dans tous les comptes : ses messages, son profil, et ses
        tête-à-tête entiers (ce qui y a été écrit, les brouillons qui y répondaient, la conversation elle-même)."""
        if not subject.startswith(teams_c.HANDLE_PREFIX):
            return 0
        author = subject[len(teams_c.HANDLE_PREFIX):].strip().lower()
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
            convs = sorted({(account, conv) for account, conv, kind in pairs if _one_to_one(kind, conv)})
            # les réponses à ses messages, ailleurs (un groupe) : elles citent ce qu'il a écrit ; ses images aussi
            n = _count(s.execute(delete(DraftRow).where(
                DraftRow.reply_to.in_(select(MessageRow.ref).where(MessageRow.author_key == key)))))
            n += _count(s.execute(delete(ImageRow).where(
                ImageRow.ref.in_(select(MessageRow.ref).where(MessageRow.author_key == key)))))
            n += _count(s.execute(delete(MessageRow).where(MessageRow.author_key == key)))
            n += _count(s.execute(delete(ProfileRow).where(ProfileRow.key == key)))
            for account, conv in convs:
                n += _count(s.execute(delete(ImageRow).where(ImageRow.ref.in_(select(MessageRow.ref).where(
                    MessageRow.account == account, MessageRow.conversation == conv)))))
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
