"""Les pages de réglages encore à part : les apps forgées (en attendant leur
espace déclaré) et les comptes. Les autres réglages sont déclarés
(``app/reglages.py``) et rendus par ``pages/settings_form.py``.

Formulaires POST protégés par jeton ; un refus dit pourquoi et ne change rien.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.adapters.web.accounts import password_problems
from mika.contracts import forge as forge_c
from mika.inspector.ui import PREFIX, UI

BAD_TOKEN = ("ko", "Jeton de formulaire invalide : recharge la page.")


def _done(path: str, what: str) -> Response:
    return RedirectResponse(f"{PREFIX}{path}?ok={what}", status_code=303)


def _ok_message(request: Request, labels: dict[str, str]) -> list[tuple[str, str]]:
    key = request.query_params.get("ok", "")
    return [("ok", labels[key])] if key in labels else []


TAB_TITLES = (("modeles", "Modèles"), ("personnalite", "Personnalité"), ("parametres", "Paramètres internes"),
              ("canaux", "Canaux"), ("sens", "Sens"), ("apps", "Apps forgées"), ("comptes", "Comptes"),
              ("journal", "Journal de configuration"))


def _tabs(current: str) -> list[dict[str, object]]:
    return [{"title": t, "href": f"{PREFIX}/reglages/{s}", "on": s == current} for s, t in TAB_TITLES]


def routes(ui: UI) -> list[Route]:
    kernel = ui.kernel
    deps = ui.deps
    settings = deps.settings

    # ── apps forgées ──
    async def forge(request: Request) -> Response:
        messages = _ok_message(request, {"config": "Réglages de l'app enregistrés (lus au prochain appel).",
                                         "switch": "Décision enregistrée."})
        port = kernel.ports.get("forge")
        if request.method == "POST":
            data = await ui.form(request)
            app = (data or {}).get("app", "")
            known = port is not None and port.info(app) is not None
            if data is None:
                messages = [BAD_TOKEN]
            elif not known:
                messages = [("ko", "App inconnue.")]
            elif data.get("action") == "switch" and deps.forge_switch is not None:
                state = data.get("state", "")
                if state not in ("enabled", "disabled", "promoted", "demoted"):
                    messages = [("ko", "Décision inconnue.")]
                else:
                    await deps.forge_switch(app, state)
                    return _done("/reglages/apps", "switch")
            elif data.get("action") == "config":
                info = port.info(app)
                defaults = dict(getattr(info, "config", ()) or ())
                values: dict[str, Any] = {}
                for key, default in defaults.items():
                    raw = data.get(f"cfg_{key}")
                    if raw is None or raw == "":
                        continue
                    try:
                        values[key] = (raw == "on") if isinstance(default, bool) else type(default)(raw)
                    except ValueError:
                        messages = [("ko", f"« {key} » attend une valeur du type {type(default).__name__}.")]
                        break
                else:
                    await settings.save_forge_config(app, values)
                    return _done("/reglages/apps", "config")
        views = {a.name: a for a in kernel.mind.frame().get(forge_c.APPS)}
        apps = []
        for info in (port.apps() if port is not None else []):
            overrides = settings.forge_config(info.name)
            defaults = dict(getattr(info, "config", ()) or ())
            apps.append({"info": info, "view": views.get(info.name), "config": [
                (k, v, overrides.get(k, ""), isinstance(v, bool)) for k, v in defaults.items()]})
        return ui.page(request, "legacy/forge.html", active="reglages", tabs=_tabs("apps"), heading="Réglages", title="Apps forgées", apps=apps, available=port is not None,
                       messages=messages)

    # ── comptes ──
    async def comptes(request: Request) -> Response:
        messages = _ok_message(request, {"created": "Compte créé.", "updated": "Compte modifié."})
        if request.method == "POST":
            data = await ui.form(request)
            if data is None:
                messages = [BAD_TOKEN]
            elif data.get("action") == "create":
                username, password = data.get("username", "").strip(), data.get("password", "")
                problems = password_problems(password, username)
                if not username:
                    problems.insert(0, "Donne un identifiant.")
                elif deps.accounts.by_name(username) is not None:
                    problems.insert(0, "Cet identifiant existe déjà.")
                if problems:
                    messages = [("ko", p) for p in problems]
                else:
                    await deps.accounts.create(username, password, operator=data.get("operator") == "on",
                                               full_name=data.get("full_name", "").strip())
                    return _done("/reglages/comptes", "created")
            else:
                try:
                    account_id = int(data.get("account", "0"))
                except ValueError:
                    account_id = 0
                refused = await deps.accounts.update(
                    account_id, operator=data.get("operator") == "on", active=data.get("active") == "on",
                    password=data.get("password") or None)
                if refused:
                    messages = [("ko", refused)]
                else:
                    return _done("/reglages/comptes", "updated")
        return ui.page(request, "legacy/accounts.html", active="reglages", tabs=_tabs("comptes"), heading="Réglages", title="Comptes", accounts=deps.accounts.all(), messages=messages)

    return [
        Route(PREFIX + "/reglages/apps", ui.guarded(forge), methods=["GET", "POST"]),
        Route(PREFIX + "/reglages/comptes", ui.guarded(comptes), methods=["GET", "POST"]),
    ]
