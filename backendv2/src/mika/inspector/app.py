"""L'inspecteur : voir ce qu'elle vit, et pourquoi.

Des vues génériques sur le journal et l'état — rien n'y est propre à une
faculté : une faculté ajoutée y apparaît seule. Réservé aux opérateurs
(session du frontend ou formulaire de connexion ici), formulaires protégés
par jeton CSRF à double soumission.

- vue d'ensemble : tête du journal, humeur, rythme, modèles branchés ;
- chronologie : les événements, filtrables ;
- épisode : la chaîne d'un épisode (départ, énoncé, issue, garde qui l'a
  supplanté, appels de modèle) — « pourquoi a-t-elle dit ça ? » ;
- décisions : les lignes de l'arbitre, en direct, et les derniers choix ;
- état : la tranche de chaque faculté ;
- modèles : fournisseurs, clés (jamais réaffichées), rôles.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from jinja2 import DictLoader, Environment, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from mika.adapters.llm.config import BackendSpec, LLMConfig
from mika.adapters.web.accounts import Account, Accounts
from mika.contracts import affect as affect_c
from mika.contracts import body as body_c
from mika.kernel.clock import US
from mika.runtime.bootstrap import Kernel
from mika.runtime.effects import with_content
from mika.vocab.affect import FR
from mika.vocab.episodes import VOICE_ROLES, Role

PREFIX = "/inspecteur"
CSRF_COOKIE = "csrftoken"


@dataclass(slots=True)
class InspectorDeps:
    kernel: Kernel
    accounts: Accounts
    settings: Any  # .llm() -> LLMConfig ; await .save_llm(cfg)
    reload: Callable[[], Awaitable[list[str]]]
    traces: list[Any]
    tz: ZoneInfo = ZoneInfo("Europe/Paris")


_BASE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{{ title }} — inspecteur</title>
<style>
:root{--bg:#fbfaf8;--fg:#1d1c1a;--mut:#6b6760;--line:#e4e0da;--acc:#7a4bd1;--ok:#1f7a44;--ko:#b3261e}
@media (prefers-color-scheme: dark){:root{--bg:#161514;--fg:#ecebe8;--mut:#a29d95;--line:#302d2a;--acc:#b595f5;--ok:#6fcf97;--ko:#f28b82}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0}
nav{display:flex;gap:1rem;flex-wrap:wrap;padding:.8rem 1rem;border-bottom:1px solid var(--line)}
nav a{color:var(--fg);text-decoration:none}nav a.on{color:var(--acc);font-weight:600}
main{padding:1rem;max-width:1200px;margin:auto}h1{font-size:1.3rem}h2{font-size:1.05rem;margin-top:1.6rem}
table{border-collapse:collapse;width:100%;font-size:13.5px}td,th{border-bottom:1px solid var(--line);padding:.35rem .5rem;text-align:left;vertical-align:top}
th{color:var(--mut);font-weight:500}code,pre{font:12.5px/1.45 ui-monospace,monospace}pre{white-space:pre-wrap;word-break:break-word;margin:0}
.mut{color:var(--mut)}.ok{color:var(--ok)}.ko{color:var(--ko)}.card{border:1px solid var(--line);border-radius:8px;padding:.8rem 1rem;margin:.6rem 0}
input,select{font:inherit;padding:.3rem .45rem;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg)}
button{font:inherit;padding:.35rem .8rem;border-radius:6px;border:1px solid var(--acc);background:var(--acc);color:#fff;cursor:pointer}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.6rem}
@media (max-width:640px){td,th{padding:.3rem}.hide-sm{display:none}}
</style></head><body>
<nav>{% for href, label in menu %}<a href="{{ href }}" class="{{ 'on' if href == here else '' }}">{{ label }}</a>{% endfor %}</nav>
<main><h1>{{ title }}</h1>{% block body %}{% endblock %}</main></body></html>"""

_TEMPLATES = {
    "base.html": _BASE,
    "login.html": """{% extends "base.html" %}{% block body %}
<form method="post" class="card"><input type="hidden" name="csrf" value="{{ csrf }}">
<p><input name="username" placeholder="identifiant" autocomplete="username"></p>
<p><input name="password" type="password" placeholder="mot de passe" autocomplete="current-password"></p>
{% if error %}<p class="ko">{{ error }}</p>{% endif %}<button>Se connecter</button></form>{% endblock %}""",
    "overview.html": """{% extends "base.html" %}{% block body %}
<div class="grid">
<div class="card"><div class="mut">Journal</div><b>{{ head }}</b> événements · {{ boots }} démarrage(s)</div>
<div class="card"><div class="mut">Humeur</div><b>{{ mood }}</b></div>
<div class="card"><div class="mut">Rythme</div><b>{{ rhythm }}</b></div>
<div class="card"><div class="mut">Modèles</div>{% if routes %}{% for r, b in routes %}<div>{{ r }} → {{ b }}</div>{% endfor %}{% else %}<span class="ko">aucun</span>{% endif %}</div>
</div>
{% if tainted %}<p class="ko">Tranches corrompues : {{ tainted }}</p>{% endif %}
<h2>Derniers épisodes</h2><table><tr><th>quand</th><th>type</th><th>cible</th><th>issue</th><th class="hide-sm">détail</th></tr>
{% for e in episodes %}<tr><td class="mut">{{ e.when }}</td><td><a href="{{ prefix }}/episode/{{ e.corr }}">{{ e.kind }}</a></td><td>{{ e.target or "—" }}</td><td class="{{ 'ok' if e.outcome == 'done' else 'ko' if e.outcome in ('failed','timeout') else '' }}">{{ e.outcome }}</td><td class="hide-sm mut">{{ e.detail }}</td></tr>{% endfor %}</table>
{% endblock %}""",
    "timeline.html": """{% extends "base.html" %}{% block body %}
<form class="card"><input name="type" value="{{ kind }}" placeholder="type (ex. episode.)"> <button>Filtrer</button></form>
<table><tr><th>seq</th><th>quand</th><th>type</th><th>corrélation</th><th>données</th></tr>
{% for e in events %}<tr><td>{{ e.seq }}</td><td class="mut">{{ e.when }}</td><td>{{ e.type }}</td><td><a href="{{ prefix }}/episode/{{ e.corr }}">{{ e.corr[:18] }}</a></td><td><pre>{{ e.data }}</pre></td></tr>{% endfor %}</table>
{% if older %}<p><a href="?before={{ older }}&type={{ kind }}">Plus ancien →</a></p>{% endif %}{% endblock %}""",
    "episode.html": """{% extends "base.html" %}{% block body %}
<table><tr><th>seq</th><th>quand</th><th>type</th><th>données</th></tr>
{% for e in events %}<tr><td>{{ e.seq }}</td><td class="mut">{{ e.when }}</td><td>{{ e.type }}</td><td><pre>{{ e.data }}</pre></td></tr>{% endfor %}</table>
{% if traces %}<h2>Appels de modèle</h2><table><tr><th>rôle</th><th>fournisseur</th><th>modèle</th><th>attente</th><th>durée</th><th>jetons</th><th>issue</th></tr>
{% for t in traces %}<tr><td>{{ t.role }}</td><td>{{ t.backend }}</td><td>{{ t.model }}</td><td>{{ '%.1f'|format(t.wait_us/1e6) }} s</td><td>{{ '%.1f'|format(t.latency_us/1e6) }} s</td><td>{{ t.input_tokens }} → {{ t.output_tokens }}</td><td>{{ t.outcome }}</td></tr>{% endfor %}</table>{% endif %}
{% endblock %}""",
    "decisions.html": """{% extends "base.html" %}{% block body %}
<p class="mut">Les preuves (log-odds) se cumulent par type et cible ; déclenchement à taux λ·σ(score).</p>
<h2>En ce moment</h2><table><tr><th>ligne</th><th>preuves</th><th>décalage</th><th>vetos</th><th>score</th><th>taux (/h)</th></tr>
{% for r in rows %}<tr><td>{{ r.key }}</td><td><pre>{% for s, reason, v in r.parts %}{{ s }}·{{ reason }} {{ '%+.2f'|format(v) }}
{% endfor %}</pre></td><td>{{ '%+.2f'|format(r.shift) }}</td><td>{{ r.vetoes or '' }}</td><td>{{ '%.2f'|format(r.score) }}</td><td>{{ '%.3f'|format(r.hazard * 3600) }}</td></tr>{% else %}<tr><td colspan="6" class="mut">aucune ligne (personne de présent, rien qui pousse à parler)</td></tr>{% endfor %}</table>
<h2>Derniers choix</h2><table><tr><th>seq</th><th>quand</th><th>choisi</th><th>tirage</th></tr>
{% for s in selections %}<tr><td>{{ s.seq }}</td><td class="mut">{{ s.when }}</td><td>{{ s.fired }}</td><td>{{ '%.3f'|format(s.draw) }}</td></tr>{% endfor %}</table>{% endblock %}""",
    "state.html": """{% extends "base.html" %}{% block body %}
{% for owner, text, changed in slices %}<div class="card"><b>{{ owner }}</b> <span class="mut">modifiée au seq {{ changed }}</span><pre>{{ text }}</pre></div>{% endfor %}{% endblock %}""",
    "models.html": """{% extends "base.html" %}{% block body %}
{% for p in problems %}<p class="ko">{{ p }}</p>{% endfor %}{% if saved %}<p class="ok">Enregistré et rechargé.</p>{% endif %}
<h2>Fournisseurs</h2><table><tr><th>nom</th><th>type</th><th>modèle</th><th>clé</th><th>hôte / URL</th><th>créneaux</th></tr>
{% for name, b in backends %}<tr><td>{{ name }}</td><td>{{ b.kind }}</td><td>{{ b.model }}</td><td>{{ '••••' if b.api_key else '—' }}</td><td>{{ b.host or b.base_url or '—' }}</td><td>{{ b.slots or 'défaut' }}</td></tr>{% endfor %}</table>
<form method="post" class="card"><input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="action" value="backend">
<b>Déclarer ou modifier</b><div class="grid">
<input name="name" placeholder="nom (ex. claude)" required><select name="kind">{% for k in kinds %}<option>{{ k }}</option>{% endfor %}</select>
<input name="model" placeholder="modèle" required><input name="api_key" type="password" placeholder="clé (vide : inchangée)">
<input name="host" placeholder="hôte Ollama / URL de base"><input name="slots" type="number" min="0" value="0"></div><p><button>Enregistrer</button></p></form>
<h2>Rôles</h2><form method="post" class="card"><input type="hidden" name="csrf" value="{{ csrf }}"><input type="hidden" name="action" value="routes">
<div class="grid">{% for role in roles %}<label>{{ role }} <select name="route_{{ role }}"><option value="">—</option>{% for name, b in backends %}<option value="{{ name }}" {{ 'selected' if routes.get(role) == name else '' }}>{{ name }}</option>{% endfor %}</select></label>{% endfor %}</div>
<p>Contexte : <input name="context" type="number" min="2000" value="{{ context }}"> jetons</p><p><button>Enregistrer</button></p></form>{% endblock %}""",
}

_env = Environment(loader=DictLoader(_TEMPLATES), autoescape=select_autoescape(default=True))


def _menu() -> list[tuple[str, str]]:
    return [(PREFIX + "/", "Vue d'ensemble"), (PREFIX + "/chronologie", "Chronologie"),
            (PREFIX + "/decisions", "Décisions"), (PREFIX + "/etat", "État"), (PREFIX + "/modeles", "Modèles")]


def routes(deps: InspectorDeps, *, cookie_secure: bool = False) -> list[Route]:
    kernel = deps.kernel

    def when(t: int) -> str:
        return datetime.fromtimestamp(t / US, deps.tz).strftime("%d/%m %H:%M:%S")

    def page(request: Request, name: str, title: str, **ctx: Any) -> Response:
        token = request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)
        html = _env.get_template(name).render(title=title, menu=_menu(), here=request.url.path, prefix=PREFIX,
                                              csrf=token, **ctx)
        response = HTMLResponse(html)
        if not request.cookies.get(CSRF_COOKIE):
            response.set_cookie(CSRF_COOKIE, token, httponly=False, samesite="lax", secure=cookie_secure)
        return response

    def operator(request: Request) -> Account | None:
        acc = deps.accounts.session(request.cookies.get("sessionid"))
        return acc if acc is not None and acc.operator else None

    async def form(request: Request) -> dict[str, str] | None:
        data = await request.form()
        token = str(data.get("csrf") or "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not cookie or not secrets.compare_digest(token, cookie):
            return None
        return {k: str(v) for k, v in data.items()}

    def guarded(fn: Callable[..., Awaitable[Response]]) -> Callable[[Request], Awaitable[Response]]:
        async def wrapper(request: Request) -> Response:
            if operator(request) is None:
                return RedirectResponse(PREFIX + "/connexion", status_code=303)
            return await fn(request)

        return wrapper

    def decode(stored: Any) -> Any:
        return with_content(kernel.mind, kernel.mind.decode(stored))

    def show(e: Any) -> str:
        return json.dumps(json.loads(e.data.model_dump_json()), ensure_ascii=False, indent=1)[:4000]

    async def login(request: Request) -> Response:
        error = ""
        if request.method == "POST":
            data = await form(request)
            if data is None:
                error = "Jeton de formulaire invalide : recharge la page."
            else:
                acc = deps.accounts.authenticate(data.get("username", ""), data.get("password", ""))
                if acc is None or not acc.operator:
                    error = "Identifiants invalides, ou compte non opérateur."
                else:
                    key = await deps.accounts.open_session(acc)
                    response = RedirectResponse(PREFIX + "/", status_code=303)
                    response.set_cookie("sessionid", key, httponly=True, samesite="lax", secure=cookie_secure)
                    return response
        return page(request, "login.html", "Connexion", error=error)

    async def overview(request: Request) -> Response:
        frame = kernel.mind.frame()
        mood = frame.get(affect_c.MOOD)
        felt = "au repos" if mood.felt_intensity < 0.1 else f"{FR[mood.felt]} ({mood.felt_intensity:.2f})"
        rhythm = f"{frame.get(body_c.PHASE).value}, énergie {frame.get(body_c.ENERGY):.0%}"
        ended = [decode(s) for s in kernel.mind.store.read(types={"episode.ended"})][-25:]
        episodes = [{"when": when(e.at), "corr": e.correlation, "kind": e.data.kind, "target": e.data.target,
                     "outcome": e.data.outcome, "detail": (e.data.detail or "")[:120]} for e in reversed(ended)]
        declared = getattr(kernel.deps.gateway, "routes", {})
        routes_ = sorted((declared() if callable(declared) else declared).items())
        return page(request, "overview.html", "Mika", head=kernel.mind.head, mood=felt, rhythm=rhythm,
                    boots=kernel.mind.root.slices["kernel"].boots, routes=routes_, episodes=episodes,
                    tainted=dict(kernel.mind.root.tainted.items()))

    async def timeline(request: Request) -> Response:
        kind = request.query_params.get("type", "")
        try:
            before = int(request.query_params.get("before", "0")) or None
        except ValueError:
            before = None
        rows = [s for s in kernel.mind.store.read() if (not kind or s.type.startswith(kind))
                and (before is None or s.seq < before)][-200:]
        events = [{"seq": s.seq, "when": when(s.at), "type": s.type, "corr": s.correlation,
                   "data": show(decode(s))} for s in reversed(rows)]
        older = rows[0].seq if len(rows) == 200 else None
        return page(request, "timeline.html", "Chronologie", events=events, kind=kind, older=older)

    async def episode(request: Request) -> Response:
        corr = request.path_params["corr"]
        rows = [s for s in kernel.mind.store.read() if s.correlation == corr]
        events = [{"seq": s.seq, "when": when(s.at), "type": s.type, "data": show(decode(s))} for s in rows]
        traces = [t for t in deps.traces if str(getattr(t, "call_id", "")).startswith(corr)]
        return page(request, "episode.html", f"Épisode {corr[:26]}", events=events, traces=traces)

    async def decisions(request: Request) -> Response:
        frame = kernel.mind.frame()
        rows = kernel.arbiter.rows(frame)
        chosen = [decode(s) for s in kernel.mind.store.read(types={"kernel.selected"})][-30:]
        selections = [{"seq": e.seq, "when": when(e.at), "fired": ", ".join(e.data.fired), "draw": e.data.draw}
                      for e in reversed(chosen)]
        return page(request, "decisions.html", "Décisions", rows=rows, selections=selections)

    async def state(request: Request) -> Response:
        root = kernel.mind.root
        slices = [(owner, repr(root.slices[owner])[:6000], root.changed.get(owner, 0)) for owner in root.slices]
        return page(request, "state.html", "État", slices=slices)

    async def models(request: Request) -> Response:
        cfg: LLMConfig = deps.settings.llm()
        problems: list[str] = []
        saved = False
        if request.method == "POST":
            data = await form(request)
            if data is None:
                problems = ["Jeton de formulaire invalide : recharge la page."]
            else:
                backends = dict(cfg.backends)
                routes_ = dict(cfg.routes)
                context = cfg.context_tokens
                try:
                    if data.get("action") == "backend":
                        name = data["name"].strip()
                        previous = backends.get(name)
                        key = data.get("api_key") or (previous.api_key if previous else "")
                        backends[name] = BackendSpec(kind=data["kind"], model=data["model"].strip(), api_key=key,
                                                     host=data.get("host", "").strip() if data["kind"].startswith("ollama") else "",
                                                     base_url=data.get("host", "").strip() if data["kind"] == "openai" else "",
                                                     slots=int(data.get("slots") or 0))
                    else:
                        routes_ = {r: data[f"route_{r}"] for r in (str(x) for x in Role) if data.get(f"route_{r}")}
                        context = int(data.get("context") or context)
                    cfg = LLMConfig(backends=backends, routes=routes_, context_tokens=context)
                    await deps.settings.save_llm(cfg)
                    problems = await deps.reload()
                    saved = not problems
                except (ValueError, KeyError) as exc:
                    problems = [str(exc)]
        return page(request, "models.html", "Modèles", backends=sorted(cfg.backends.items()), routes=cfg.routes,
                    roles=[str(r) for r in Role], context=cfg.context_tokens, problems=problems, saved=saved,
                    kinds=["claude", "openai", "ollama", "ollama_cloud"], voice=sorted(str(r) for r in VOICE_ROLES))

    return [
        Route(PREFIX + "/connexion", login, methods=["GET", "POST"]),
        Route(PREFIX + "/", guarded(overview)),
        Route(PREFIX + "/chronologie", guarded(timeline)),
        Route(PREFIX + "/episode/{corr:str}", guarded(episode)),
        Route(PREFIX + "/decisions", guarded(decisions)),
        Route(PREFIX + "/etat", guarded(state)),
        Route(PREFIX + "/modeles", guarded(models), methods=["GET", "POST"]),
    ]
