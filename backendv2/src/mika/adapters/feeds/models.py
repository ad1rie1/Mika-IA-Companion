"""Le cache des flux, déclaré (ADR 0101) : la base ``feeds`` (``feeds.db`` sous SQLite, ``mika_feeds`` sous MariaDB).

- ``entries`` : un article relevé. Son identifiant est une empreinte (``_key`` de l'adaptateur : le flux et le
  ``guid``), 24 caractères ; ``n`` dit l'ordre d'arrivée (il départage deux articles du même instant) ; ``handed`` :
  déjà rendu par un relevé ; ``seen_at`` : la dernière fois que son flux le listait (l'horizon du cache).
- ``feeds`` : ce que le dernier relevé de chaque flux a donné (la console dit quel flux ne répond plus).

**La recherche compare des textes repliés à l'écriture** (``fold_text`` : casse et accents ignorés), dans des
colonnes à part (``feed_fold``, ``text_fold``) : aucune fonction Python dans le SQL, et la même réponse sur les deux
moteurs (``LIKE`` et la collation n'y disent pas la même chose).

**Une valeur venue d'ailleurs qui dépasse sa borne** : une adresse de flux (une clé) est ramenée à sa borne par
``fit`` — son début et son empreinte, de façon déterministe : deux adresses distinctes restent deux clés, la même
retrouve toujours sa ligne (une lecture par l'adresse passe par ``fit`` aussi) ; l'adresse montrée, elle, vient
toujours des réglages, jamais d'ici. Le nom d'un flux (un texte qu'on montre) est coupé à sa borne. Un identifiant
d'article cherché trop long ne désigne rien (une lecture ne lève pas, ``Key`` ne borne que les écritures).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index
from sqlalchemy.orm import Mapped, mapped_column

from mika.ports.paging import fold_text
from mika.ports.sql import FeedsBase, Key, LongText, fit, table_args

#: un identifiant d'article : l'empreinte que l'adaptateur calcule (``_key``)
ENTRY_ID_MAX = 24
#: une adresse de flux, comme clé (au-delà : ``fit``)
URL_MAX = 512
#: le nom d'un flux, tel qu'on le montre et qu'on compte par flux (au-delà : coupé)
FEED_NAME_MAX = 300




class EntryRow(FeedsBase):
    """Un article relevé."""

    __tablename__ = "entries"
    __table_args__ = table_args(
        # le relevé (ce qui reste à rendre) et la console (les plus récents) sans parcourir tout le cache
        Index("ix_entries_to_hand", "handed", "published"),
        Index("ix_entries_published", "published"),
        # la santé d'un flux (ce que le cache en garde) et l'horizon (par flux)
        Index("ix_entries_feed_url", "feed_url"),
    )

    id: Mapped[str] = mapped_column(Key(ENTRY_ID_MAX), primary_key=True)
    feed_url: Mapped[str] = mapped_column(Key(URL_MAX))
    #: le titre du flux (ou son adresse montrable, jamais son jeton)
    feed: Mapped[str] = mapped_column(Key(FEED_NAME_MAX), default="")
    title: Mapped[str] = mapped_column(LongText, default="")
    link: Mapped[str] = mapped_column(LongText, default="")
    summary: Mapped[str] = mapped_column(LongText, default="")
    published: Mapped[int] = mapped_column(default=0)
    handed: Mapped[bool] = mapped_column(default=False)
    n: Mapped[int] = mapped_column(default=0)
    seen_at: Mapped[int] = mapped_column(default=0)
    #: ``feed`` replié (la recherche par flux)
    feed_fold: Mapped[str] = mapped_column(LongText, default="")
    #: le titre et le résumé repliés (la recherche dans le texte)
    text_fold: Mapped[str] = mapped_column(LongText, default="")


def entry_values(*, id: str, feed_url: str, feed: str, title: str, link: str, summary: str, published: int,
                 handed: bool, n: int, seen_at: int) -> dict[str, Any]:
    """Les colonnes d'un article à insérer : la clé de son flux ramenée à sa borne, son nom coupé, et ses textes
    repliés calculés ici (la seule façon d'écrire un article)."""
    name = feed[:FEED_NAME_MAX]
    return {"id": id, "feed_url": fit(feed_url, URL_MAX), "feed": name, "title": title, "link": link,
            "summary": summary, "published": published, "handed": handed, "n": n, "seen_at": seen_at,
            "feed_fold": fold_text(name), "text_fold": fold_text(f"{title} {summary}")}


class FeedRow(FeedsBase):
    """Ce que le dernier relevé d'un flux a donné."""

    __tablename__ = "feeds"

    url: Mapped[str] = mapped_column(Key(URL_MAX), primary_key=True)
    #: relevé au moins une fois avec succès (son premier relevé n'hérite pas des archives)
    polled: Mapped[bool] = mapped_column(default=False)
    attempted_at: Mapped[int] = mapped_column(default=0)
    ok_at: Mapped[int] = mapped_column(default=0)
    error: Mapped[str] = mapped_column(LongText, default="")
    #: les échecs d'affilée
    failures: Mapped[int] = mapped_column(default=0)
    #: les articles lus au dernier relevé, et les nouveaux
    items: Mapped[int] = mapped_column(default=0)
    added: Mapped[int] = mapped_column(default=0)


__all__ = ["ENTRY_ID_MAX", "FEED_NAME_MAX", "URL_MAX", "EntryRow", "FeedRow", "entry_values", "fit"]
