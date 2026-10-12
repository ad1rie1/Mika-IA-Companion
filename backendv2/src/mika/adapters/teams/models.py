"""Le cache de Teams, déclaré (ADR 0101) : la base ``teams`` (``teams.db`` sous SQLite, ``mika_teams`` sous MariaDB).

- ``meta`` : ce qu'on sait de l'extension (``last_batch``, ``self_id``, ``self_name``), clé et valeur ;
- ``conversations`` : une conversation, sous son identifiant Teams ;
- ``messages`` : un message, sous sa référence (``ports.teams.message_ref``) ; ``id`` dit l'ordre d'arrivée (il
  départage deux messages du même instant, et l'élagage par conversation le lit) ;
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

from sqlalchemy import Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, validates

from mika.ports.paging import fold_text
from mika.ports.sql import Id, Key, LongText, TeamsBase, fit, table_args

#: un nom de ``meta``
META_NAME_MAX = 32
#: un identifiant de conversation (la porte en admet 304 : ``ports.teams.CONVERSATION_ID``)
CONVERSATION_MAX = 320
#: une référence de message (``t`` et douze chiffres hexadécimaux) ou de brouillon
REF_MAX = 32
#: l'identifiant d'un auteur, en minuscules (la porte en admet 200)
AUTHOR_MAX = 200
#: l'état d'un brouillon (``ports.teams`` : ``brouillon``, ``en_file``…)
STATE_MAX = 16




class MetaRow(TeamsBase):
    """Ce qu'on sait de l'extension : une petite table clé/valeur."""

    __tablename__ = "meta"

    name: Mapped[str] = mapped_column(Key(META_NAME_MAX), primary_key=True)
    value: Mapped[str] = mapped_column(LongText, default="")


class ConversationRow(TeamsBase):
    __tablename__ = "conversations"

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
        Index("ix_messages_conversation_at", "conversation", "at"),
        Index("ix_messages_pending", "acked", "own", "at"),
        Index("ix_messages_author_key", "author_key"),
    )

    id: Mapped[int] = mapped_column(Id, primary_key=True)
    ref: Mapped[str] = mapped_column(Key(REF_MAX))
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
        Index("ix_drafts_open", "state", "conversation"),
    )

    #: l'ordre de la dernière écriture
    id: Mapped[int] = mapped_column(Id, primary_key=True)
    #: l'identifiant du brouillon (``Draft.id``)
    draft_id: Mapped[str] = mapped_column(Key(REF_MAX))
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
    "AUTHOR_MAX", "CONVERSATION_MAX", "META_NAME_MAX", "REF_MAX", "STATE_MAX",
    "ConversationRow", "DraftRow", "MessageRow", "MetaRow", "fit",
]
