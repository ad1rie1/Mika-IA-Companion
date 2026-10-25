"""Réglages › Comptes opérateurs : qui peut se connecter, et qui administre.

Une liste paginée ; ajouter un compte et en modifier un se font chacun sur leur
page (``?nouveau=utilisateur|operateur``, ``?compte=<id>``). Un utilisateur parle
avec elle (chat, téléphone) sans ouvrir la console ; un opérateur l'ouvre aussi.
Chaque compte est une personne dès sa création (``register_accounts``, prévenu par
``Accounts.on_change``). Leurs règles ne sont pas celles d'un
formulaire de réglages : un mot de passe se vérifie (``password_problems``), on
ne retire jamais le dernier opérateur actif, un mot de passe ne se réaffiche
jamais. Chaque création ou modification est auditée (``runtime.operated``, sans
contenu) et paraît dans le journal des modifications.

La page d'un compte montre aussi ses **applications connectées** (ADR 0062) : les
jetons de client natif (le téléphone, un moteur de jeu), d'où ils viennent et
quand ils ont servi — jamais leur secret —, chacun révocable (ses connexions se
ferment ; un téléphone révoqué ne la laisse plus écrire à la personne absente).
"""

from __future__ import annotations

import secrets as _secrets
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from mika.adapters.web.accounts import (
    CLIENT_MOBILE,
    SOURCE_CONSOLE,
    SOURCE_LOGIN,
    ClientToken,
    password_problems,
)
from mika.inspector import render
from mika.inspector.catalog import Panel
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX, secure
from mika.kernel.inspect import Badge, Column, Ref, Row, Stat, Stats, Table, Text, paginate
from mika.runtime import operations

URL = f"{PREFIX}/reglages/comptes"
BAD_TOKEN = ("danger", "Jeton de formulaire invalide : recharge la page.")
US = 1_000_000
_SOURCES = {SOURCE_LOGIN: "connexion (identifiant et mot de passe)", SOURCE_CONSOLE: "console"}
#: les deux sortes de compte qu'on ajoute (``?nouveau=``, le champ ``role``) : ce que dit la page de chacune
OPERATOR, USER = "operateur", "utilisateur"
ROLES = {OPERATOR: ("Ajouter un opérateur", "Opérateur ajouté"),
         USER: ("Ajouter un utilisateur", "Utilisateur ajouté")}


def _role(raw: str) -> str:
    """La sorte demandée ; une ancienne adresse (``?nouveau=1``) ajoute un utilisateur, comme la case décochée."""
    return OPERATOR if raw == OPERATOR else USER


def _app_row(ui: Any, t: ClientToken) -> dict[str, Any]:
    """Une application connectée telle que la page la montre (jamais le secret)."""
    return {"id": t.id, "label": t.label or "sans nom",
            "kind": ("Téléphone (notifié fermé)" if t.push else "Téléphone (sans notifications)")
            if t.client == CLIENT_MOBILE else "Écran ou moteur",
            "source": _SOURCES.get(t.source, "ligne de commande"),
            "created": ui.when(t.created_at * US), "last_used": ui.when((t.last_used or 0) * US),
            "revoked": t.revoked}


def _account_url(**query: str) -> str:
    return URL + ("?" + urlencode(query) if query else "")


@TABS.tab("reglages.comptes", title="Comptes", group="Comptes opérateurs", order=2000,
          description="Qui peut se connecter au frontend (un compte = une personne qu'elle reconnaît), et qui "
                      "administre : un opérateur ouvre la console, décide des approbations et des apps.")
async def comptes(ui: Any, request: Request) -> Any:
    return await page(ui, request, {})


async def page(ui: Any, request: Request, state: Mapping[str, Any]) -> dict[str, Any]:
    accounts = ui.deps.accounts.all()
    query = request.query_params
    ctx = ui.inspection.context(query)
    editing = str(state.get("editing") or query.get("compte", "") or "")
    creating = bool(state.get("creating")) or bool(query.get("nouveau"))
    messages = list(state.get("messages") or [])
    if creating:
        role = _role(str(state.get("role") or query.get("nouveau", "")))
        heading = ROLES[role][0]
        return {"blocks": [], "messages": messages, "crumbs": [("Comptes", URL), (heading, "")],
                "panel": Panel("handmade/reglages/compte.html", {
                    "mode": "create", "action": URL, "page_heading": heading, "role": role,
                    "operator_role": role == OPERATOR, "values": state.get("values") or {},
                    "switch": _account_url(nouveau=USER if role == OPERATOR else OPERATOR)})}
    if editing:
        found = next((a for a in accounts if str(a.id) == editing), None)
        if found is not None:
            tokens = list(reversed(ui.deps.accounts.tokens(found.id)))
            apps, apps_pager = paginate(tokens, ctx.pager("page_apps", size=12))
            return {"blocks": [], "messages": messages, "crumbs": [("Comptes", URL), (found.username, "")],
                    "panel": Panel("handmade/reglages/compte.html", {"mode": "edit", "action": URL, "account": found,
                                                     "page_heading": f"Modifier · {found.username}",
                                                     "person_url": render.href(Ref.subject("person", found.handle,
                                                                                           found.display_name)),
                                                     "operators": sum(1 for a in accounts if a.operator and a.active),
                                                     "apps": [_app_row(ui, t) for t in apps], "apps_total": len(tokens),
                                                     "apps_pager": render._pager(apps_pager, query)})}
        messages.append(("warn", "Ce compte n'existe pas."))
    window, pager = paginate(accounts, ctx.pager(size=25))
    rows = tuple(Row((
        Ref("local", _account_url(compte=str(a.id)), a.username), a.full_name or Text("—", "muted"),
        Ref.subject("person", a.handle, a.display_name),
        Badge("opérateur", "ok") if a.operator else Badge("utilisateur", "muted"),
        Badge("actif", "ok") if a.active else Badge("désactivé", "muted")),
        href=Ref("local", _account_url(compte=str(a.id)), ""), tone="" if a.active else "muted") for a in window)
    # les deux boutons d'ajout, au-dessus des chiffres et de la liste
    add = Panel("handmade/reglages/compte.html", {"mode": "list", "add_user": _account_url(nouveau=USER),
                                                  "add_operator": _account_url(nouveau=OPERATOR)})
    return {"messages": messages, "panel": add, "blocks": [
        Stats((Stat("Comptes", len(accounts)), Stat("Opérateurs actifs", sum(1 for a in accounts
                                                                               if a.operator and a.active)),
               Stat("Utilisateurs", sum(1 for a in accounts if not a.operator)),
               Stat("Désactivés", sum(1 for a in accounts if not a.active)))),
        Table((Column("identifiant", role="title"), "nom affiché", Column("personne", "fit"), Column("rôle", role="badge"), Column("état", role="badge")), rows,
              title=f"Comptes ({len(accounts)})", pager=pager, empty="Aucun compte.",
              layout="list", link_label="Modifier le compte",
              caption="Chaque compte est une personne qu'elle connaît dès sa création, sous son nom affiché ; "
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
        # la sorte vient du bouton qui a ouvert la page ; la case « Opérateur » d'avant vaut encore
        role = OPERATOR if data.get("role") == OPERATOR or data.get("operator") == "on" else USER
        problems = password_problems(password, username)
        if not username:
            problems.insert(0, "Donne un identifiant.")
        elif deps.accounts.by_name(username) is not None:
            problems.insert(0, "Cet identifiant existe déjà.")
        if problems:
            return None, {"creating": True, "role": role, "values": {"username": username, "full_name": full_name},
                          "messages": [("danger", p) for p in problems]}, 400
        created = await deps.accounts.create(username, password, operator=role == OPERATOR, full_name=full_name)
        await operations.audit(ui.kernel, "console.comptes.creer", by=account.handle, subject_kind="compte",
                               subject=created.handle)
        # la création en a fait une personne (``Accounts.on_change``) : sa fiche existe déjà, la page du compte y mène
        return _done(ui, "ok", f"{ROLES[role][1]} : {created.display_name} ({created.username}), désormais une "
                               f"personne qu'elle connaît ({created.handle}).", compte=str(created.id)), {}, 303
    try:
        account_id = int(data.get("account", "0"))
    except ValueError:
        account_id = 0
    if data.get("action") == "revoke_token":
        try:
            token_id = int(data.get("token", "0"))
        except ValueError:
            token_id = 0
        owned = next((t for t in deps.accounts.tokens(account_id) if t.id == token_id), None)
        if owned is None:
            return None, {"editing": str(account_id), "messages": [("danger", "Ce jeton n'est pas à ce compte.")]}, 400
        if not await deps.accounts.revoke_token(token_id):
            return None, {"editing": str(account_id), "messages": [("warn", "Ce jeton était déjà révoqué.")]}, 400
        await operations.audit(ui.kernel, "console.comptes.revoquer_jeton", by=account.handle, subject_kind="compte",
                               subject=f"user_{account_id}")
        return _done(ui, "ok", f"Application révoquée : {owned.label or 'sans nom'}.", compte=str(account_id)), {}, 303
    refused = await deps.accounts.update(account_id, operator=data.get("operator") == "on",
                                         active=data.get("active") == "on", password=data.get("password") or None,
                                         full_name=data.get("full_name") if "full_name" in data else None)
    if refused:
        return None, {"editing": str(account_id), "messages": [("danger", refused)]}, 400
    await operations.audit(ui.kernel, "console.comptes.modifier", by=account.handle, subject_kind="compte",
                           subject=f"user_{account_id}")
    return _done(ui, "ok", "Compte modifié."), {}, 303


def _done(ui: Any, tone: str, message: str, **query: str) -> Response:
    token = _secrets.token_urlsafe(9)
    ui.flash(token, tone, message)
    return secure(RedirectResponse(_account_url(**query, flash=token), status_code=303))
