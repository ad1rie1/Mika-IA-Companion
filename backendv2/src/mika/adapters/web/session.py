"""La session d'une requête : ses deux cookies, le compte qu'elle porte, son jeton CSRF.

``account_of`` sert les routes HTTP du transport web qui ne veulent que le compte. Les WebSocket (``/ws``,
``/ws/camera``, ``/ws/world``) et les routes qui ont besoin de l'identifiant du jeton (``whoami`` d'un client natif,
``DELETE /auth/token``, ``/auth/push``, ``/api/phone/…``) lisent encore ``Accounts`` elles-mêmes : une règle ajoutée à
``account_of`` ne les atteint pas. Ce qui fait qu'une session ou un jeton vaut (sa durée, sa révocation, un compte
actif) est dans ``Accounts.session`` et ``Accounts.token``, que tous ces chemins lisent.

Un client natif présente un jeton de son compte, **seulement sans** ``Origin`` ; un navigateur, sa session. Les routes
qui écrivent exigent en plus le jeton CSRF à double soumission (cookie ``csrftoken`` lisible, en-tête ``X-CSRFToken``),
qu'un client natif n'a pas : rien n'est élargi.
"""

from __future__ import annotations

import secrets
from typing import Any

from starlette.requests import Request

from mika.adapters.web.accounts import Account, Accounts

SESSION_COOKIE = "sessionid"
CSRF_COOKIE = "csrftoken"


def bearer(header: str | None) -> str:
    """Le jeton d'un en-tête ``Authorization: Bearer …`` (vide sans en-tête, ou pour un autre schéma)."""
    scheme, _, value = (header or "").strip().partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def native_token(headers: Any) -> str:
    """Le jeton porteur d'un client natif : seulement **sans** ``Origin`` (avec une, c'est un navigateur, et seule
    sa session compte — une page ne peut pas faire valoir un jeton volé à côté de ses cookies)."""
    if headers.get("origin") is not None:
        return ""
    return bearer(headers.get("authorization"))


def account_of(request: Request, accounts: Accounts) -> Account | None:
    """Le compte d'une requête : son jeton de client natif (sans ``Origin``), sinon sa session."""
    token = native_token(request.headers)
    if token:
        found = accounts.token(token)
        return found[0] if found is not None else None
    return accounts.session(request.cookies.get(SESSION_COOKIE))


def csrf_header_ok(request: Request) -> bool:
    """Le jeton CSRF de l'en-tête est celui du cookie, et il y en a un."""
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get("x-csrftoken", "")
    return bool(cookie) and secrets.compare_digest(cookie, header)
