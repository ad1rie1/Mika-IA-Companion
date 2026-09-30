"""Ce que partagent toutes les pages de la console : l'accès (opérateurs
seulement), le jeton CSRF à double soumission, les en-têtes de sécurité, le
rendu (Jinja2, échappement automatique), la navigation et ses badges, les
vitaux."""

from __future__ import annotations

import json
import secrets
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mika.adapters.web.accounts import Account, Accounts
from mika.contracts import runtime as rt
from mika.inspector import render
from mika.inspector.catalog import Builtin, Destination, NavGroup, SettingsSection, SettingsTab, builtin_keys
from mika.kernel.clock import US
from mika.kernel.inspect import Vital
from mika.runtime import health
from mika.runtime.bootstrap import Kernel
from mika.runtime.effects import with_content
from mika.runtime.inspection import Inspection

PREFIX = render.PREFIX
CSRF_COOKIE = "csrftoken"
SESSION_COOKIE = "sessionid"
TEMPLATES = Path(__file__).parent / "templates"
STATIC = Path(__file__).parent / "static"
ASSET_VERSION = "2"

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self' data:; "
                               "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Cache-Control": "no-store",
}


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
    tz: ZoneInfo | None = None
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
    #: la carte de la console (``app/console.py``)
    navigation: Sequence[NavGroup] = field(default_factory=tuple)
    #: les séries mesurées : ``sampler(clé, depuis, jusqu'à, points)``
    sampler: Callable[..., list[tuple[int, float]]] | None = None
    #: les sections de réglages (``app/reglages.py``) et leurs onglets
    sections: Sequence[SettingsSection] = field(default_factory=tuple)
    settings_tabs: Sequence[SettingsTab] = field(default_factory=tuple)
    #: les paramètres internes des facultés (``runtime/params.Parameters``)
    parameters: Any = None
    #: les sauvegardes : ``fn() -> {sauvegarde, verification, archives}`` (``app/backup.overview``)
    backups: Callable[[], Mapping[str, Any]] | None = None
    #: Configuration › Comportement : (famille, facultés) et le nom lisible de chacune
    param_families: Sequence[tuple[str, Sequence[str]]] = field(default_factory=tuple)
    faculty_labels: Mapping[str, str] = field(default_factory=dict)


env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(default=True),
                  trim_blocks=True, lstrip_blocks=True)
env.globals.update(PREFIX=PREFIX, ASSET_VERSION=ASSET_VERSION)


class UI:
    def __init__(self, deps: InspectorDeps, builtins: Mapping[str, Builtin], *, cookie_secure: bool = False) -> None:
        self.deps = deps
        self.kernel = deps.kernel
        self.cookie_secure = cookie_secure
        self.builtins = builtins
        #: le moteur des réglages déclarés (``pages/settings_form.py``), posé par ``app.routes``
        self.settings_forms: Any = None
        sampler = deps.sampler or getattr(getattr(deps.kernel, "series", None), "read", None)
        self.inspection = Inspection(deps.kernel, sampler=sampler)
        self.sampler = sampler
        self._tz: tuple[int, ZoneInfo] | None = None
        #: les messages d'après une action, lus une fois (clé : le jeton du formulaire)
        self._flash: dict[str, tuple[str, str]] = {}

    def flash(self, key: str, tone: str, text: str) -> None:
        self._flash[key] = (tone, text)
        while len(self._flash) > 200:
            self._flash.pop(next(iter(self._flash)))

    def pop_flash(self, key: str) -> tuple[str, str] | None:
        return self._flash.pop(key, None) if key else None

    # ── temps ──
    @property
    def tz(self) -> ZoneInfo:
        """Le fuseau de sa persona (celui qu'elle vit), sinon celui des dépendances."""
        if self.deps.tz is not None:
            return self.deps.tz
        head = self.kernel.mind.head
        if self._tz is None or self._tz[0] != head:
            frame = self.kernel.mind.frame()
            self._tz = (head, frame.env.tz_of(frame.root))
        return self._tz[1]

    def when(self, t: int) -> str:
        if not t:
            return "—"
        return datetime.fromtimestamp(t / US, self.tz).strftime("%d/%m %H:%M")

    def when_long(self, t: int) -> str:
        if not t:
            return "—"
        return datetime.fromtimestamp(t / US, self.tz).strftime("%d/%m/%Y %H:%M:%S")

    def now(self) -> int:
        return self.kernel.mind.clock.now()

    def stamp(self, t: int, span: int) -> str:
        """Une graduation : l'heure sur un jour, la date au-delà."""
        fmt = "%H:%M" if span <= 2 * 86_400 * US else "%d/%m"
        return datetime.fromtimestamp(t / US, self.tz).strftime(fmt)

    def env(self) -> render.Env:
        return render.Env(when=self.when_long, now=self.now(), stamp=self.stamp)

    # ── navigation ──
    def destination_badge(self, d: Destination) -> int:
        total = 0
        for v in self.inspection.in_section(d.key):
            b = self.inspection.badge(v)
            total += b[0] if b else 0
        for key in builtin_keys(d, self.builtins):
            b = self.builtins.get(key)
            if b is not None and b.badge is not None:
                total += int(b.badge(self) or 0)
        return total

    def attention_items(self) -> list[dict[str, Any]]:
        """Ce qui demande une action, onglet par onglet : ``{label, count, hint, href}``
        (le tableau de bord en fait des cadres qui mènent à la bonne page)."""
        out: list[dict[str, Any]] = []
        for g in self.deps.navigation:
            for d in g.items:
                base = f"{PREFIX}/" if d.key == "accueil" else f"{PREFIX}/{d.key}"
                for key in builtin_keys(d, self.builtins):
                    b = self.builtins.get(key)
                    if b is None or b.badge is None:
                        continue
                    n = int(b.badge(self) or 0)
                    if n:
                        out.append({"label": f"{d.label} › {b.title}", "count": n, "hint": "",
                                    "href": f"{base}/{b.slug}"})
                for v in self.inspection.in_section(d.key):
                    got = self.inspection.badge(v)
                    if got and got[0]:
                        out.append({"label": f"{d.label} › {v.title}", "count": got[0],
                                    "hint": got[1] if len(got) > 1 else "", "href": f"{base}/{v.name}"})
        return out

    def nav(self, active: str) -> list[dict[str, Any]]:
        groups = []
        for g in self.deps.navigation:
            items = []
            for d in g.items:
                url = f"{PREFIX}/" if d.key == "accueil" else f"{PREFIX}/{d.key}"
                items.append({"key": d.key, "label": d.label, "icon": d.icon, "href": url, "on": d.key == active,
                              "badge": self.destination_badge(d)})
            groups.append({"label": g.label, "items": items})
        return groups

    def vitals(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        report = health.report(self.kernel)
        states = {"ok": ("ok", "en forme"), "degraded": ("warn", "répond moins bien"), "ko": ("danger", "en panne")}
        dot, text = states.get(report.status, ("muted", report.status))
        out.append({"label": "Santé", "text": text, "dot": dot, "href": f"{PREFIX}/systeme/sante"})
        for spec, v in self.inspection.vitals():
            out.append(self._vital(spec.label, v))
        pending = len(self.kernel.mind.frame().get(rt.PENDING_EFFECTS))
        if pending:
            out.append({"label": "À approuver", "text": str(pending), "dot": "warn",
                        "href": f"{PREFIX}/approbations"})
        waiting = sum(self.kernel.lanes.pending(lane) for lane in self.kernel.lanes.capacities)
        if waiting:
            out.append({"label": "En file", "text": str(waiting), "dot": "info",
                        "href": f"{PREFIX}/decisions/episodes"})
        gateway = self.kernel.deps.gateway
        if not getattr(gateway, "configured", gateway is not None):
            out.append({"label": "Modèles", "text": "aucun", "dot": "danger", "href": f"{PREFIX}/reglages/modeles"})
        out.append({"label": "Heure", "text": datetime.fromtimestamp(self.now() / US, self.tz).strftime("%H:%M"),
                    "optional": True})
        return out

    @staticmethod
    def _vital(label: str, v: Vital) -> dict[str, Any]:
        return {"label": label, "text": v.text, "dot": render.tone(v.tone) if v.tone else "",
                "hint": v.hint, "href": render.href(v.href) if v.href else "",
                "swatch": v.swatch.key if v.swatch else "",
                "ratio": None if v.ratio is None else round(min(1.0, max(0.0, v.ratio)), 3)}

    # ── rendu ──
    def csrf(self, request: Request) -> str:
        """Le jeton de formulaire de cette requête (le cookie, ou un nouveau posé par la réponse)."""
        token = request.cookies.get(CSRF_COOKIE) or getattr(request.state, "csrf", "")
        if not token:
            token = secrets.token_urlsafe(32)
            request.state.csrf = token
        return token

    def page(self, request: Request, name: str, title: str, *, status: int = 200, active: str = "",
             **ctx: Any) -> Response:
        token = self.csrf(request)
        account = self.operator(request)
        html = env.get_template(name).render(
            title=title, csrf=token, nav=self.nav(active), vitals=self.vitals(),
            who=account.display_name if account else "", **ctx)
        response = HTMLResponse(html, status_code=status)
        if not request.cookies.get(CSRF_COOKIE):
            response.set_cookie(CSRF_COOKIE, token, httponly=False, samesite="lax", secure=self.cookie_secure)
        return secure(response)

    def fragment(self, name: str, **ctx: Any) -> Response:
        return secure(HTMLResponse(env.get_template(name).render(**ctx)))

    def bare(self, request: Request, name: str, title: str, *, status: int = 200, **ctx: Any) -> Response:
        """Une page sans le cadre (connexion)."""
        token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        response = HTMLResponse(env.get_template(name).render(title=title, csrf=token, **ctx), status_code=status)
        if not request.cookies.get(CSRF_COOKIE):
            response.set_cookie(CSRF_COOKIE, token, httponly=False, samesite="lax", secure=self.cookie_secure)
        return secure(response)

    # ── accès ──
    def operator(self, request: Request) -> Account | None:
        acc = self.deps.accounts.session(request.cookies.get(SESSION_COOKIE))
        return acc if acc is not None and acc.operator else None

    async def form(self, request: Request) -> dict[str, str] | None:
        """Le formulaire, si son jeton correspond au cookie ; sinon ``None``."""
        got = await self.form_lists(request)
        return None if got is None else got[0]

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
                if request.url.path.startswith(PREFIX + "/_"):
                    return secure(Response(status_code=401))
                return secure(RedirectResponse(PREFIX + "/connexion", status_code=303))
            return await fn(request)

        return wrapper

    # ── journal ──
    def decode(self, stored: Any) -> Any:
        return with_content(self.kernel.mind, self.kernel.mind.decode(stored))

    @staticmethod
    def show(e: Any, limit: int = 4000) -> str:
        return json.dumps(json.loads(e.data.model_dump_json()), ensure_ascii=False, indent=1)[:limit]


def secure(response: Response) -> Response:
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response
