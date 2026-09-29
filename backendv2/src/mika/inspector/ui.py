"""Ce que partagent toutes les pages de l'inspecteur : l'accès (opérateurs
seulement), le jeton CSRF à double soumission, le rendu (Jinja2, échappement
automatique) et le menu."""

from __future__ import annotations

import json
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mika.adapters.web.accounts import Account, Accounts
from mika.kernel.clock import US
from mika.kernel.inspect import Fields, Note, Prose, Ref, Table
from mika.runtime.bootstrap import Kernel
from mika.runtime.effects import with_content

PREFIX = "/inspecteur"
CSRF_COOKIE = "csrftoken"
SESSION_COOKIE = "sessionid"
TEMPLATES = Path(__file__).parent / "templates"


@dataclass(slots=True)
class InspectorDeps:
    kernel: Kernel
    accounts: Accounts
    #: réglages d'exploitation (``app/settings.py``)
    settings: Any
    #: recharge les modèles après un changement ; rend les problèmes
    reload: Callable[[], Awaitable[list[str]]]
    #: les derniers appels de modèle (en mémoire)
    traces: Sequence[Any]
    tz: ZoneInfo = field(default_factory=lambda: ZoneInfo("Europe/Paris"))
    #: le port d'entrée (décider d'un effet, santé)
    port: Any = None
    #: le registre durable des appels de modèle (``adapters/llm/calls.py``)
    calls: Any = None
    #: rejournalise la persona et les paramètres (persona, tempérament, surcharges)
    reconfigure: Callable[[], Awaitable[list[str]]] | None = None
    #: redémarre le robot Telegram après un changement de réglages
    restart_telegram: Callable[[], Awaitable[None]] | None = None
    #: après une décision d'approbation (rafraîchit les panneaux du frontend)
    after_decision: Callable[[], Awaitable[Any]] | None = None
    #: les rapports de simulation (``mika sim run --report``)
    reports: Path | None = None
    #: une décision d'opérateur sur une app forgée : ``(app, état)``
    forge_switch: Callable[[str, str], Awaitable[None]] | None = None


MENU: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("Vivre", (("/", "Vue d'ensemble"), ("/chronologie", "Chronologie"), ("/decisions", "Décisions"),
               ("/facultes", "Facultés"), ("/approbations", "Approbations"))),
    ("Comprendre", (("/etat", "État et faits"), ("/contributions", "Contributions"))),
    ("Exploiter", (("/sante", "Santé"), ("/appels", "Appels de modèle"), ("/rapports", "Simulations"))),
    ("Régler", (("/modeles", "Modèles"), ("/persona", "Persona"), ("/parametres", "Paramètres"),
                ("/canaux", "Canaux"), ("/sens", "Sens"), ("/forge", "Apps forgées"), ("/comptes", "Comptes"))),
)

env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(default=True),
                  trim_blocks=True, lstrip_blocks=True)


def href(ref: Ref) -> str:
    """L'adresse d'un lien de vue (les clés viennent du code des facultés,
    jamais d'un texte extérieur ; elles sont quand même encodées)."""
    if ref.kind == "episode":
        return f"{PREFIX}/episode/{quote(ref.key, safe='')}"
    if ref.kind == "event":
        return f"{PREFIX}/evenement/{quote(ref.key, safe='')}"
    owner, _, name = ref.key.partition("/")
    query = ("?" + urlencode(ref.params)) if ref.params else ""
    return f"{PREFIX}/facultes/{quote(owner, safe='')}/{quote(name, safe='')}{query}"


def block_kind(block: Any) -> str:
    return {Table: "table", Fields: "fields", Note: "note", Prose: "prose"}.get(type(block), "note")


def cell(value: Any) -> dict[str, Any]:
    """Une cellule prête pour le gabarit : texte, ou lien."""
    if isinstance(value, Ref):
        return {"text": value.text, "href": href(value)}
    if value is None:
        return {"text": "—"}
    if isinstance(value, bool):
        return {"text": "oui" if value else "non"}
    if isinstance(value, float):
        return {"text": f"{value:.3g}"}
    return {"text": str(value)}


env.globals.update(block_kind=block_kind, cell=cell, PREFIX=PREFIX)


class UI:
    def __init__(self, deps: InspectorDeps, *, cookie_secure: bool = False) -> None:
        self.deps = deps
        self.kernel = deps.kernel
        self.cookie_secure = cookie_secure

    # ── rendu ──
    def when(self, t: int) -> str:
        if not t:
            return "—"
        return datetime.fromtimestamp(t / US, self.deps.tz).strftime("%d/%m %H:%M:%S")

    def page(self, request: Request, name: str, title: str, *, status: int = 200, **ctx: Any) -> Response:
        token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        here = request.url.path.removeprefix(PREFIX) or "/"
        html = env.get_template(name).render(title=title, menu=MENU, here=here, csrf=token, **ctx)
        response = HTMLResponse(html, status_code=status)
        if not request.cookies.get(CSRF_COOKIE):
            response.set_cookie(CSRF_COOKIE, token, httponly=False, samesite="lax", secure=self.cookie_secure)
        return response

    # ── accès ──
    def operator(self, request: Request) -> Account | None:
        acc = self.deps.accounts.session(request.cookies.get(SESSION_COOKIE))
        return acc if acc is not None and acc.operator else None

    async def form(self, request: Request) -> dict[str, str] | None:
        """Le formulaire, si son jeton correspond au cookie ; sinon ``None``."""
        data = await request.form()
        token = str(data.get("csrf") or "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not cookie or not secrets.compare_digest(token, cookie):
            return None
        return {k: str(v) for k, v in data.multi_items()}

    async def form_lists(self, request: Request) -> tuple[dict[str, str], dict[str, list[str]]] | None:
        """Comme ``form``, avec les champs répétés (cases à cocher)."""
        data = await request.form()
        token = str(data.get("csrf") or "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not cookie or not secrets.compare_digest(token, cookie):
            return None
        lists: dict[str, list[str]] = {}
        for k, v in data.multi_items():
            lists.setdefault(k, []).append(str(v))
        return {k: vs[-1] for k, vs in lists.items()}, lists

    def guarded(self, fn: Callable[[Request], Awaitable[Response]]) -> Callable[[Request], Awaitable[Response]]:
        async def wrapper(request: Request) -> Response:
            if self.operator(request) is None:
                return RedirectResponse(PREFIX + "/connexion", status_code=303)
            return await fn(request)

        return wrapper

    # ── journal ──
    def decode(self, stored: Any) -> Any:
        return with_content(self.kernel.mind, self.kernel.mind.decode(stored))

    @staticmethod
    def show(e: Any, limit: int = 4000) -> str:
        return json.dumps(json.loads(e.data.model_dump_json()), ensure_ascii=False, indent=1)[:limit]
