"""La page de réglages encore à part : les comptes (leurs règles — mot de
passe, jamais sans opérateur — ne sont pas celles d'un formulaire de réglages). Les autres réglages sont déclarés
(``app/reglages.py``) et rendus par ``pages/settings_form.py``.

Formulaires POST protégés par jeton ; un refus dit pourquoi et ne change rien.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from mika.adapters.web.accounts import password_problems
from mika.inspector.ui import PREFIX, UI

BAD_TOKEN = ("ko", "Jeton de formulaire invalide : recharge la page.")


def _done(path: str, what: str) -> Response:
    return RedirectResponse(f"{PREFIX}{path}?ok={what}", status_code=303)


def _ok_message(request: Request, labels: dict[str, str]) -> list[tuple[str, str]]:
    key = request.query_params.get("ok", "")
    return [("ok", labels[key])] if key in labels else []


TAB_TITLES = (("modeles", "Modèles"), ("personnalite", "Personnalité"), ("parametres", "Paramètres internes"),
              ("canaux", "Canaux"), ("sens", "Sens"), ("comptes", "Comptes"),
              ("journal", "Journal de configuration"))


def _tabs(current: str) -> list[dict[str, object]]:
    return [{"title": t, "href": f"{PREFIX}/reglages/{s}", "on": s == current} for s, t in TAB_TITLES]


def routes(ui: UI) -> list[Route]:
    deps = ui.deps

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
        Route(PREFIX + "/reglages/comptes", ui.guarded(comptes), methods=["GET", "POST"]),
    ]
