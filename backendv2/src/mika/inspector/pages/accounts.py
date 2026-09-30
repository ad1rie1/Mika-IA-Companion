"""Configuration › Accès › Comptes : qui peut se connecter, et qui administre.

Une liste paginée ; créer un compte et en modifier un se font chacun sur leur
page (``?nouveau=1``, ``?compte=<id>``). Leurs règles ne sont pas celles d'un
formulaire de réglages : un mot de passe se vérifie (``password_problems``), on
ne retire jamais le dernier opérateur actif, un mot de passe ne se réaffiche
jamais. Chaque création ou modification est auditée (``runtime.operated``, sans
contenu) et paraît dans le journal des modifications.
"""

from __future__ import annotations

import secrets as _secrets
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.adapters.web.accounts import password_problems
from mika.inspector.catalog import Panel
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX, secure
from mika.kernel.inspect import Badge, Column, Ref, Row, Stat, Stats, Table, Text, paginate
from mika.runtime import operations

URL = f"{PREFIX}/reglages/comptes"
BAD_TOKEN = ("danger", "Jeton de formulaire invalide : recharge la page.")


def _account_url(**query: str) -> str:
    return URL + ("?" + urlencode(query) if query else "")


@TABS.tab("reglages.comptes", title="Comptes", group="Accès", order=2000,
          description="Qui peut se connecter au frontend (un compte = une personne qu'elle reconnaît), et qui "
                      "administre : un opérateur ouvre la console, décide des approbations et des apps.")
async def comptes(ui: Any, request: Request) -> Any:
    return await page(ui, request, {})


async def page(ui: Any, request: Request, state: Mapping[str, Any]) -> dict[str, Any]:
    accounts = ui.deps.accounts.all()
    query = request.query_params
    editing = str(state.get("editing") or query.get("compte", "") or "")
    creating = bool(state.get("creating")) or query.get("nouveau") == "1"
    messages = list(state.get("messages") or [])
    if creating:
        return {"blocks": [], "messages": messages, "crumbs": [("Comptes", URL), ("Créer un compte", "")],
                "panel": Panel("accounts.html", {"mode": "create", "action": URL,
                                                 "values": state.get("values") or {}})}
    if editing:
        found = next((a for a in accounts if str(a.id) == editing), None)
        if found is not None:
            return {"blocks": [], "messages": messages, "crumbs": [("Comptes", URL), (found.username, "")],
                    "panel": Panel("accounts.html", {"mode": "edit", "action": URL, "account": found,
                                                     "operators": sum(1 for a in accounts if a.operator and a.active)})}
        messages.append(("warn", "Ce compte n'existe pas."))
    ctx = ui.inspection.context(query)
    window, pager = paginate(accounts, ctx.pager(size=25))
    rows = tuple(Row((
        Ref("local", _account_url(compte=str(a.id)), a.username), a.full_name or Text("—", "muted"),
        Ref.subject("person", a.handle, a.handle),
        Badge("opérateur", "ok") if a.operator else Text("frontend seulement", "muted"),
        Badge("actif", "ok") if a.active else Badge("désactivé", "muted")),
        href=Ref("local", _account_url(compte=str(a.id)), ""), tone="" if a.active else "muted") for a in window)
    return {"messages": messages, "blocks": [
        Stats((Stat("Comptes", len(accounts)), Stat("Opérateurs actifs", sum(1 for a in accounts
                                                                               if a.operator and a.active)),
               Stat("Désactivés", sum(1 for a in accounts if not a.active)),
               Stat("Créer un compte", "＋", href=Ref("local", _account_url(nouveau="1"), "créer")))),
        Table((Column("identifiant"), "nom affiché", Column("personne", "fit"), "rôle", "état"), rows,
              title=f"Comptes ({len(accounts)})", pager=pager, empty="Aucun compte.",
              caption="La personne d'un compte (user_<n>) est celle qu'elle reconnaît quand ce compte lui parle ; "
                      "sa fiche réunit tout ce qu'elle en sait.")]}


async def post(ui: Any, request: Request) -> tuple[Response | None, dict[str, Any], int]:
    deps = ui.deps
    data = await ui.form(request)
    account = ui.operator(request)
    if data is None or account is None:
        return None, {"messages": [BAD_TOKEN]}, 403
    if data.get("action") == "create":
        username, password = data.get("username", "").strip(), data.get("password", "")
        full_name = data.get("full_name", "").strip()
        problems = password_problems(password, username)
        if not username:
            problems.insert(0, "Donne un identifiant.")
        elif deps.accounts.by_name(username) is not None:
            problems.insert(0, "Cet identifiant existe déjà.")
        if problems:
            return None, {"creating": True, "values": {"username": username, "full_name": full_name,
                                                       "operator": data.get("operator") == "on"},
                          "messages": [("danger", p) for p in problems]}, 400
        created = await deps.accounts.create(username, password, operator=data.get("operator") == "on",
                                             full_name=full_name)
        await operations.audit(ui.kernel, "console.comptes.creer", by=account.handle, subject_kind="compte",
                               subject=created.handle)
        return _done(ui, "ok", f"Compte créé : {created.username} ({created.handle})."), {}, 303
    try:
        account_id = int(data.get("account", "0"))
    except ValueError:
        account_id = 0
    refused = await deps.accounts.update(account_id, operator=data.get("operator") == "on",
                                         active=data.get("active") == "on", password=data.get("password") or None)
    if refused:
        return None, {"editing": str(account_id), "messages": [("danger", refused)]}, 400
    await operations.audit(ui.kernel, "console.comptes.modifier", by=account.handle, subject_kind="compte",
                           subject=f"user_{account_id}")
    return _done(ui, "ok", "Compte modifié."), {}, 303


def _done(ui: Any, tone: str, message: str) -> Response:
    token = _secrets.token_urlsafe(9)
    ui.flash(token, tone, message)
    return secure(RedirectResponse(f"{URL}?flash={token}", status_code=303))
