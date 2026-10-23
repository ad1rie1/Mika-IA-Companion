"""Ce que partagent toutes les pages de la console : l'accès (opérateurs
seulement), le jeton CSRF à double soumission, les en-têtes de sécurité, le
rendu (Jinja2, échappement automatique), la navigation et ses badges, les
vitaux."""

from __future__ import annotations

import dataclasses
import json
import logging
import secrets
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from mika.adapters.web.accounts import Account, Accounts
from mika.adapters.web.app import LoginThrottle
from mika.contracts import runtime as rt
from mika.contracts import self_ as self_c
from mika.inspector import render
from mika.inspector.catalog import (
    Builtin,
    Labels,
    MenuGroup,
    NavGroup,
    SettingsSection,
    SettingsTab,
    builtin_keys,
)
from mika.inspector.names import Names
from mika.kernel import forms
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
ASSET_VERSION = "25"

log = logging.getLogger("mika.console")

#: échecs de connexion tolérés par identifiant et adresse IP, puis par adresse IP seule, sur la fenêtre
LOGIN_FAILURES = 5
LOGIN_FAILURES_PER_IP = 20
LOGIN_WINDOW_S = 60.0

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
    #: les derniers appels de modèle (en mémoire)
    traces: Sequence[Any]
    #: le menu de l'opératrice (``app/console_menu.py``) : la navigation de la console
    menu: Sequence[MenuGroup]
    tz: ZoneInfo | None = None
    #: le port d'entrée (décider d'un effet, santé)
    port: Any = None
    #: le registre durable des appels de modèle (``adapters/llm/calls.py``)
    calls: Any = None
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
    #: les sauvegardes : ``fn() -> {sauvegarde, tentative, verification, archives}`` (``app/backup.overview``)
    backups: Callable[[], Mapping[str, Any]] | None = None
    #: Réglages › Paramètres avancés : (famille, facultés) et le nom lisible de chacune
    param_families: Sequence[tuple[str, Sequence[str]]] = field(default_factory=tuple)
    faculty_labels: Mapping[str, str] = field(default_factory=dict)
    #: les noms en français de ce que déclarent les facultés (sections, raisons, vetos, processus…)
    labels: Labels | None = None
    #: le relais MCP du moteur Claude Code (« Prêter à un agent » : ses sessions ouvertes)
    relay: Any = None
    #: ses outils prêtés à un agent (``app/lending.py``, ADR 0122) : ce que chaque point sert, ses derniers appels
    lending: Any = None
    #: les clients du monde (``/ws/world``, ADR 0051) : ``overview()`` dit qui est connecté, qui tient le bail
    #: d'hôte, ce qui manque au moteur (Système › Écrans du monde)
    world: Any = None
    #: les vues d'ensemble dessinées à la main, par type d'objet (ADR 0121) : le premier onglet de sa fiche, ouvert
    #: par défaut (voir ``Overview``)
    overviews: Mapping[str, Any] = field(default_factory=dict)
    #: les onglets des destinations dessinés à la main, par « destination/onglet » (ADR 0121, voir ``Drawn``)
    drawn: Mapping[str, Any] = field(default_factory=dict)
    #: les propriétaires dont les vues gardent le rendu de la console, bloc par bloc (leur interface est un contrat :
    #: les apps de la Forge) ; les autres pages se dessinent dans le vocabulaire des pages dessinées
    plain_owners: frozenset[str] = frozenset()


def wants_table(query: Mapping[str, str]) -> bool:
    """La page demande une liste en tableau (``vue_<table>=table``) : un onglet dessiné rend alors la main aux blocs
    de sa faculté, et à leur tableau (ADR 0121)."""
    return any(k.startswith("vue_") and v == "table" for k, v in query.items())


class Forms(dict[str, Any]):
    """Les formulaires que la console a préparés pour les actions d'un onglet, par emplacement (leur jeton, leurs
    champs, leur retour) ; ``of(blocs rendus, sujet)`` prépare ceux d'autres blocs pour un objet — une fiche que
    l'onglet ouvre dans la page (un message dans la liseuse du courrier). ``csrf`` : le jeton de la page, pour un
    formulaire que le dessin écrit lui-même (relancer un effet de la file de sortie)."""

    def __init__(self, page: Mapping[str, Any], of: Callable[[Sequence[Any], str], dict[str, Any]],
                 csrf: str = "") -> None:
        super().__init__(page)
        self.of = of
        self.csrf = csrf


class Drawn:
    """Un onglet d'une destination, dessiné par la composition (ADR 0121) : les mêmes données que sa faculté (ses
    blocs), une autre forme. ``render`` reçoit aussi les formulaires que la console a préparés pour les actions de
    ces blocs (``forms`` : ``Forms``) ; il rend son HTML (déjà échappé), un couple (HTML, blocs
    que la console rend après), ou ``None`` : ses blocs, tels quels. ``styles`` et ``scripts`` : ce que ses gabarits
    demandent (sous ``static/``). ``last`` : son HTML vient après les blocs et le panneau de la console (un onglet
    qui ne redessine que sa liste, sous les chiffres et les boutons qui restent à la console). ``panel`` : la console
    garde le panneau de l'onglet ; faux, le dessin dit ce qu'il disait."""

    styles: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()
    last: bool = False
    panel: bool = True

    def render(self, ui: UI, blocks: Sequence[Any], query: Mapping[str, str],
               forms: Mapping[str, Any] | None = None) -> Any:
        raise NotImplementedError


class Overview:
    """Ce qu'une vue d'ensemble offre à la fiche d'un type d'objet (ADR 0121) : la composition la dessine à la main
    en croisant les facultés ; la console n'en sait que l'onglet (``slug``, ``title``, ``description``). ``render``
    rend son HTML, déjà échappé (un gabarit de la console), ou ``None`` : la fiche retombe sur ses onglets. ``head``
    dessine l'en-tête de la fiche sur tous ses onglets (son titre principal compris) — la console y ajoute ses
    actions ; ``None`` : l'en-tête de la faculté qui déclare l'objet."""

    slug = "ensemble"
    title = "Vue d'ensemble"
    description = ""
    #: les feuilles et les scripts de la console (sous ``static/``) que ses gabarits demandent
    styles: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()
    #: les onglets des facultés que la vue d'ensemble résume : rangés au bout de la barre, sous ``folded_title``
    folded: tuple[str, ...] = ()
    folded_title = "Le détail"
    #: les onglets des facultés qu'elle dessine (``render_tab``) : leurs données restent celles de la faculté
    tabs: tuple[str, ...] = ()

    def render(self, ui: UI, key: str) -> Any:
        raise NotImplementedError

    def head(self, ui: UI, key: str) -> Any:
        return None

    def links(self, ui: UI, key: str) -> Sequence[tuple[str, str]]:
        """Des liens (texte, adresse) posés avec les actions de l'en-tête, à droite : ses réglages, par exemple."""
        return ()

    def render_tab(self, ui: UI, key: str, tab: str, blocks: Sequence[Any], query: Mapping[str, str],
                   forms: Mapping[str, Any] | None = None) -> Any:
        """Un onglet d'une faculté, dessiné : ``blocks`` sont ceux que la faculté a rendus (ses lignes, ses
        cellules, sa pagination), ``query`` les paramètres de la page, ``forms`` les formulaires que la console a
        préparés pour leurs actions (``Forms``). ``None`` : ses blocs, tels quels ; un couple (HTML, blocs) : ce
        qu'elle a dessiné, puis des blocs que la console rend après."""
        return None


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
        labels = deps.labels or Labels()
        if not labels.faculties and deps.faculty_labels:
            labels = dataclasses.replace(labels, faculties=dict(deps.faculty_labels))
        #: le nom affiché de tout (``names.py``)
        self.names = Names(deps.kernel, labels)
        self._tz: tuple[int, ZoneInfo] | None = None
        #: les messages d'après une action, lus une fois (clé : le jeton du formulaire)
        self._flash: dict[str, tuple[str, str]] = {}
        #: un secret neuf (un jeton) montré à la page d'après, une seule fois : (pour quel compte, quoi), par clé
        self._reveals: dict[str, tuple[str, dict[str, str]]] = {}
        #: la connexion à la console : le même étranglement que /auth/login (identifiant et IP), plus
        #: un plafond par IP (qui essaierait cent identifiants)
        self.login_throttle = LoginThrottle(LOGIN_FAILURES, LOGIN_WINDOW_S)
        self.ip_throttle = LoginThrottle(LOGIN_FAILURES_PER_IP, LOGIN_WINDOW_S)

    def login_blocked(self, ip: str, username: str) -> bool:
        # l'adresse IP d'abord : une IP déjà bloquée ne fait plus naître d'entrée par identifiant tapé
        return self.ip_throttle.blocked(ip) or self.login_throttle.blocked(f"{ip}:{username.casefold()}")

    def login_failed(self, ip: str, username: str) -> None:
        """Un échec compté et journalisé (le nom tapé, borné et sans caractère de contrôle ; jamais le
        mot de passe)."""
        self.login_throttle.fail(f"{ip}:{username.casefold()}")
        self.ip_throttle.fail(ip)
        shown = "".join(c for c in username if c.isprintable())[:60]
        log.warning("console : connexion refusée pour « %s » depuis %s", shown, ip)

    def flash(self, key: str, tone: str, text: str) -> None:
        self._flash[key] = (tone, text)
        while len(self._flash) > 200:
            self._flash.pop(next(iter(self._flash)))

    def pop_flash(self, key: str) -> tuple[str, str] | None:
        return self._flash.pop(key, None) if key else None

    def reveal(self, handle: str, shown: dict[str, str]) -> str:
        """Un jeton neuf à montrer une seule fois, à l'opératrice qui l'a créé : la clé qui le retrouve (jamais le
        jeton dans une adresse)."""
        key = secrets.token_urlsafe(12)
        self._reveals[key] = (handle, shown)
        while len(self._reveals) > 50:
            self._reveals.pop(next(iter(self._reveals)))
        return key

    def pop_reveal(self, key: str, handle: str) -> dict[str, str] | None:
        """Ce que ``reveal`` a gardé, une fois, pour cette même opératrice."""
        got = self._reveals.pop(key, None) if key else None
        return got[1] if got is not None and got[0] == handle else None

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
    def attention_items(self) -> list[dict[str, Any]]:
        """Ce qui demande une action, onglet par onglet : ``{label, count, hint, href}``
        (l'accueil en fait des cadres qui mènent à la bonne page)."""
        out: list[dict[str, Any]] = []
        for g in self.deps.navigation:
            for d in g.items:
                base = f"{PREFIX}/{d.key}"
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

    def nav(self, active: str, path: str) -> list[dict[str, Any]]:
        """Le menu de l'opératrice : résout la rubrique la plus précise, y compris sur les fiches.

        Les nombres restent sur les entrées : deux vues peuvent montrer une
        même demande. Le groupe signale sa présence sans additionner ces nombres.
        """
        links = [(gi, li, link) for gi, group in enumerate(self.deps.menu)
                 for li, link in enumerate(group.items)]

        def locate(target: str) -> tuple[int, int] | None:
            matches = [(len(route), gi, li) for gi, li, link in links
                       for route in (link.target, *link.also)
                       if target == route or (route and (target.startswith(route + "/")
                                                         or target.startswith(route + "-")))]
            if not matches:
                return None
            _, gi, li = max(matches)
            return gi, li

        current = locate(path.split("?", 1)[0].removeprefix(PREFIX).strip("/"))
        if current is None and active:
            current = locate("" if active == "accueil" else active)
        if current is None and active:
            current = next(((gi, li) for gi, li, link in links if link.target.split("/")[0] == active), None)
        badges: dict[tuple[int, int], int] = {}
        for item in self.attention_items():
            key = locate(item["href"].removeprefix(PREFIX).strip("/"))
            if key is not None:
                badges[key] = badges.get(key, 0) + item["count"]
        groups = []
        for gi, group in enumerate(self.deps.menu):
            items = [{"label": link.label, "href": f"{PREFIX}/{link.target}", "icon": group.icon,
                      "on": current == (gi, li), "badge": badges.get((gi, li), 0)}
                     for li, link in enumerate(group.items)]
            groups.append({"label": self.her_name() if group.her else group.label, "icon": group.icon,
                           "items": items,
                           "active": current is not None and current[0] == gi,
                           "badge": any(i["badge"] for i in items)})
        return groups

    def her_name(self) -> str:
        """Son nom, celui de sa persona en vigueur : la console ne l'écrit jamais en dur (ADR 0070)."""
        return self_c.name_of(self.kernel.mind.frame().get(self_c.PERSONA))

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
            out.append({"label": "Modèles", "text": "aucun", "dot": "danger", "href": f"{PREFIX}/reglages/fournisseurs"})
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
        # ``menu_path`` : la page que le menu allume, quand ce n'est pas celle-ci (une fiche ouverte depuis une liste)
        menu_path = ctx.pop("menu_path", "") or request.url.path
        html = env.get_template(name).render(
            title=title, csrf=token, nav=self.nav(active, menu_path), vitals=self.vitals(), her=self.her_name(), posted=request.method == "POST",
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

    async def form(self, request: Request) -> dict[str, Any] | None:
        """Le formulaire, si son jeton correspond au cookie ; sinon ``None``."""
        got = await self.form_lists(request)
        return None if got is None else got[0]

    async def form_lists(self, request: Request) -> tuple[dict[str, Any], dict[str, list[Any]]] | None:
        """Comme ``form``, avec les champs répétés (cases à cocher) ; un fichier envoyé arrive en ``Upload``."""
        data = await request.form()
        token = str(data.get("csrf") or "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not cookie or not secrets.compare_digest(token, cookie):
            return None
        lists: dict[str, list[Any]] = {}
        for k, v in data.multi_items():
            lists.setdefault(k, []).append(await _upload(v) if isinstance(v, UploadFile) else str(v))
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


async def _upload(file: UploadFile) -> forms.Upload:
    """Un fichier envoyé, lu au plus ``UPLOAD_MAX`` octets (au-delà : marqué trop gros, pas gardé)."""
    data = await file.read(forms.UPLOAD_MAX + 1)
    await file.close()
    if len(data) > forms.UPLOAD_MAX:
        return forms.Upload(name=file.filename or "", too_big=True)
    return forms.Upload(name=file.filename or "", data=data)
