"""Le cache de Teams, déclaré (ADR 0101) : la base ``teams`` (``teams.db`` sous SQLite, ``mika_teams`` sous MariaDB).

**Chaque ligne porte son compte** (ADR 0186, ``account`` : la clé du compte dans les réglages) ; ce qui était là avant
est au compte ``principal`` (la migration ``a3c71e5d9b20``).

- ``accounts`` : ce qu'on sait de l'extension de chaque compte (son dernier lot, l'identifiant et le nom que Teams
  donne à sa personne) ;
- ``conversations`` : une conversation, sous son compte et son identifiant Teams (deux personnes d'un même groupe ont
  chacune la sienne) ;
- ``messages`` : un message, sous sa référence (``ports.teams.message_ref``, unique entre les comptes) ; ``id`` dit
  l'ordre d'arrivée (il départage deux messages du même instant, et l'élagage par conversation le lit) ;
- ``drafts`` : ses brouillons et la file d'envoi ; ``id`` dit l'ordre de la **dernière écriture** — un brouillon
  réécrit (mis en file, posé, parti) prend un nouveau numéro, et départage ainsi deux brouillons du même instant.

**Les recherches comparent des textes repliés à l'écriture** (``fold_text`` : casse et accents ignorés, ``%`` et
``_`` de simples caractères), dans des colonnes à part (``title_fold``, ``id_fold``), recalculées par l'entité à chaque
écriture du titre ou de l'identifiant : la même réponse sur les deux moteurs (``LIKE`` et ``lower`` n'y disent pas la
même chose). L'auteur d'un message est aussi gardé en minuscules (``author_key``), comme l'oubli le désigne
(``teams:<identifiant>``).

**Un identifiant venu de Teams qui dépasse sa borne** (une conversation, un auteur) est ramené à sa borne par
``fit`` — son début et son empreinte, de façon déterministe : deux identifiants distincts restent distincts, et une
lecture par l'identifiant entier retrouve la ligne (elle passe par ``fit`` aussi). La porte (``app/teams``) borne
déjà ce qu'elle admet sous ces bornes : ``fit`` ne sert qu'à ce qui arriverait autrement. Une référence cherchée
(un message, un brouillon) trop longue ne désigne rien, sans lever.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, validates

from mika.ports.paging import fold_text
from mika.ports.sql import Id, Key, LongText, TeamsBase, fit, table_args
from mika.ports.teams import DEFAULT_ACCOUNT

#: la clé d'un compte (``ports.teams.ACCOUNT_KEY`` : 40 au plus)
ACCOUNT_MAX = 40
#: un identifiant de conversation (la porte en admet 304 : ``ports.teams.CONVERSATION_ID``)
CONVERSATION_MAX = 320
#: une référence de message (``t`` et douze chiffres hexadécimaux) ou de brouillon
REF_MAX = 32
#: l'identifiant d'un auteur, en minuscules (la porte en admet 200)
AUTHOR_MAX = 200
#: l'état d'un brouillon (``ports.teams`` : ``brouillon``, ``en_file``…)
STATE_MAX = 16




def _account() -> Any:
    """La colonne du compte d'une ligne : ``principal`` pour ce qui était là avant (ADR 0186)."""
    return mapped_column(Key(ACCOUNT_MAX), default=DEFAULT_ACCOUNT, server_default=DEFAULT_ACCOUNT)


class AccountRow(TeamsBase):
    """Ce qu'on sait de l'extension d'un compte."""

    __tablename__ = "accounts"

    key: Mapped[str] = mapped_column(Key(ACCOUNT_MAX), primary_key=True)
    #: le dernier lot poussé par son extension (µs, l'horloge du serveur ; 0 : jamais)
    last_batch: Mapped[int] = mapped_column(default=0)
    self_id: Mapped[str] = mapped_column(LongText, default="")
    self_name: Mapped[str] = mapped_column(LongText, default="")


class ConversationRow(TeamsBase):
    __tablename__ = "conversations"

    account: Mapped[str] = mapped_column(Key(ACCOUNT_MAX), primary_key=True, default=DEFAULT_ACCOUNT,
                                         server_default=DEFAULT_ACCOUNT)
    id: Mapped[str] = mapped_column(Key(CONVERSATION_MAX), primary_key=True)
    title: Mapped[str] = mapped_column(LongText, default="")
    kind: Mapped[str] = mapped_column(LongText, default="other")
    #: l'heure Teams (µs) de son dernier message ; 0 : aucun (une conversation seulement annoncée)
    last_at: Mapped[int] = mapped_column(default=0)
    #: le titre et l'identifiant repliés (la recherche)
    title_fold: Mapped[str] = mapped_column(LongText, default="")
    id_fold: Mapped[str] = mapped_column(LongText, default="")

    @validates("title")
    def _fold_title(self, _key: str, value: str) -> str:
        self.title_fold = fold_text(value or "")
        return value

    @validates("id")
    def _fold_id(self, _key: str, value: str) -> str:
        self.id_fold = fold_text(value or "")
        return value


class MessageRow(TeamsBase):
    __tablename__ = "messages"
    __table_args__ = table_args(
        UniqueConstraint("ref", name="uq_messages_ref"),
        Index("ix_messages_conversation_at", "account", "conversation", "at"),
        Index("ix_messages_pending", "acked", "own", "at"),
        Index("ix_messages_author_key", "author_key"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    ref: Mapped[str] = mapped_column(Key(REF_MAX))
    account: Mapped[str] = _account()
    conversation: Mapped[str] = mapped_column(Key(CONVERSATION_MAX))
    #: l'identifiant que Teams lui donne (gardé, jamais une clé : la référence l'est)
    external_id: Mapped[str] = mapped_column(LongText, default="")
    author: Mapped[str] = mapped_column(LongText, default="")
    author_id: Mapped[str] = mapped_column(LongText, default="")
    #: ``author_id`` en minuscules (l'oubli de ``teams:<identifiant>``)
    author_key: Mapped[str] = mapped_column(Key(AUTHOR_MAX), default="")
    at: Mapped[int] = mapped_column(default=0)
    text: Mapped[str] = mapped_column(LongText, default="")
    own: Mapped[bool] = mapped_column(default=False)
    mentions_me: Mapped[bool] = mapped_column(default=False)
    #: quand il est arrivé (µs, l'horloge du serveur)
    received: Mapped[int] = mapped_column(default=0)
    #: déjà remarqué (ou à elle : jamais rendu comme reçu)
    acked: Mapped[bool] = mapped_column(default=False)


class DraftRow(TeamsBase):
    __tablename__ = "drafts"
    __table_args__ = table_args(
        UniqueConstraint("draft_id", name="uq_drafts_draft_id"),
        Index("ix_drafts_open", "account", "state", "conversation"),
    )

    #: l'ordre de la dernière écriture
    id: Mapped[int] = mapped_column(Id, primary_key=True)
    #: l'identifiant du brouillon (``Draft.id``)
    draft_id: Mapped[str] = mapped_column(Key(REF_MAX))
    account: Mapped[str] = _account()
    conversation: Mapped[str] = mapped_column(Key(CONVERSATION_MAX), default="")
    body: Mapped[str] = mapped_column(LongText, default="")
    reply_to: Mapped[str] = mapped_column(LongText, default="")
    author: Mapped[str] = mapped_column(LongText, default="")
    created: Mapped[int] = mapped_column(default=0)
    updated: Mapped[int] = mapped_column(default=0)
    state: Mapped[str] = mapped_column(Key(STATE_MAX), default="")
    mode: Mapped[str] = mapped_column(LongText, default="")
    digest: Mapped[str] = mapped_column(LongText, default="")
    final: Mapped[str] = mapped_column(LongText, default="")
    expires_at: Mapped[int] = mapped_column(default=0)
    placed_at: Mapped[int] = mapped_column(default=0)
    sent_at: Mapped[int] = mapped_column(default=0)
    sent_text: Mapped[str] = mapped_column(LongText, default="")
    edited: Mapped[bool] = mapped_column(default=False)
    edited_by: Mapped[str] = mapped_column(LongText, default="")
    reason: Mapped[str] = mapped_column(LongText, default="")


__all__ = [
    "ACCOUNT_MAX", "AUTHOR_MAX", "CONVERSATION_MAX", "REF_MAX", "STATE_MAX",
    "AccountRow", "ConversationRow", "DraftRow", "MessageRow", "fit",
]
