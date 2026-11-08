"""Réglages › Comptes : qui se connecte (son espace, le téléphone, un écran), et qui pilote la console.

Une liste paginée ; ajouter un compte et en modifier un se font chacun sur leur
page (``?nouveau=utilisateur|operateur``, ``?compte=<id>``). Un utilisateur parle
avec elle (son espace web, le téléphone) sans ouvrir la console ; un opérateur l'ouvre aussi.
Chaque compte est une personne dès sa création (``register_accounts``, prévenu par
``Accounts.on_change``). Leurs règles ne sont pas celles d'un
formulaire de réglages : un mot de passe se vérifie (``password_problems``), on
ne retire jamais le dernier opérateur actif, un mot de passe ne se réaffiche
jamais. Chaque geste est audité (``runtime.operated``, sans contenu) et paraît dans
le journal des modifications. La liste dit la dernière connexion de chaque compte
(``Accounts.last_seen``) et mène à ses droits exacts.

La page d'un compte est la vue d'un objet (ADR 0176) : le nom affiché et ses étiquettes
(opérateur ou utilisateur, actif ou désactivé), ce qu'il ouvre, ses faits — son identifiant,
sa fiche, ses comptes (l'onglet de sa fiche qui les réunit, la source : rien n'est recopié
ici), ses droits exacts (Réglages › Droits, ``?qui=``), sa dernière connexion —, puis le
formulaire. Ses **connexions web** : combien de sessions sont ouvertes et la plus récente,
« Fermer ses sessions » (confirmé ; ses jetons restent). Ses **applications connectées**
(ADR 0062) : les jetons de client natif (le téléphone, un moteur de jeu), d'où ils viennent
et quand ils ont servi — jamais leur secret —, chacun révocable (ses connexions se ferment ;
un téléphone révoqué ne la laisse plus écrire à la personne absente). « Nouveau jeton » en
crée un (un nom, ce qu'il ouvre) : donné par la console (``SOURCE_CONSOLE``), il ne tombe pas
avec le mot de passe, et ne se montre qu'une fois, à l'opératrice qui l'a créé (``UI.reveal``).
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
    CLIENT_SCREEN,
    SESSION_TTL_S,
    SOURCE_CONSOLE,
    SOURCE_LOGIN,
    Account,
    ClientToken,
    password_problems,
)
from mika.contracts import identity as identity_c
from mika.inspector import render
from mika.inspector.catalog import Panel
from mika.inspector.pages.subjects import fiche_url
from mika.inspector.pages.tabs import TABS
from mika.inspector.ui import PREFIX, secure
from mika.kernel.clock import DAY
from mika.kernel.inspect import Badge, Column, Ref, Row, Stat, Stats, Table, Text, When, paginate
from mika.runtime import operations
from mika.vocab.access import PRIVATE, WEB

URL = f"{PREFIX}/reglages/comptes"
#: les droits exacts d'une personne (Réglages › Droits) : ceux qu'un compte mène à lire, par son chat web en privé
RIGHTS = f"{PREFIX}/reglages/droits"
RIGHTS_CANAL = f"{WEB}:{PRIVATE}"
#: les onglets de la fiche d'une personne qui réunissent ce qui est à elle (ADR 0185, 0186) — Comptes : ses boîtes,
#: ses comptes Teams, ses services et ses partages ; sans boîte, Teams est un onglet à lui — et ce que leur lien en dit
OWNED_TABS = (("boites", "ses boîtes, ses comptes Teams, ses services et ses partages"), ("teams", "ses comptes Teams"))
BAD_TOKEN = ("danger", "Jeton de formulaire invalide : recharge la page.")
US = 1_000_000
_SOURCES = {SOURCE_LOGIN: "connexion (identifiant et mot de passe)", SOURCE_CONSOLE: "console"}
#: ce qu'ouvre un jeton créé ici (``client``) : ce que la page en dit, et comment s'en servir (montré avec lui)
CLIENTS = {CLIENT_SCREEN: "Un écran ou un moteur de jeu", CLIENT_MOBILE: "Le téléphone (l'application Android)"}
TOKEN_USE = {
    CLIENT_SCREEN: "À donner au moteur de jeu ou à l'écran : il le présente dans l'en-tête « Authorization: Bearer … », "
                   "sans Origin, sur /ws/world (le monde) ou /ws (le chat). Il n'y lit que si la personne est là.",
    CLIENT_MOBILE: "Pour l'application du téléphone en version de débogage (« Utiliser un jeton ») ; sinon, elle "
                   "obtient le sien en se connectant. Tant qu'il vit, elle peut écrire à cette personne absente.",
}
#: le nom d'un jeton (``ClientTokenRow.label``) : au-delà, il est coupé
TOKEN_LABEL_MAX = 60
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


def rights_url(frame: Any, person: str) -> str:
    """Ses droits exacts (Réglages › Droits), par son chat web en privé : une de ses propriétaires s'y lit « toi »,
    toute autre personne qui a un compte par sa clé (``p:<clé>``)."""
    who = "toi" if frame.get(identity_c.IS_OWNER(person)) else f"p:{person}"
    return f"{RIGHTS}?{urlencode({'qui': who, 'canal': RIGHTS_CANAL})}"


def _owned_tab(ui: Any, person: str) -> tuple[str, str] | None:
    """L'onglet de sa fiche qui réunit ce qui est à elle (son texte, son adresse) ; rien quand sa fiche n'en a pas."""
    shown = {t.name for t in ui.inspection.tabs("person", person)}
    return next(((text, fiche_url("person", person, name)) for name, text in OWNED_TABS if name in shown), None)


def _seen(at: int | None) -> Any:
    """Une dernière connexion, en cellule : « — » quand rien n'en reste."""
    return When(at * US) if at else Text("—", "muted")


@TABS.tab("reglages.comptes", title="Comptes", group="Comptes", order=2000,
          description="Qui peut se connecter au frontend (un compte = une personne qu'elle reconnaît), et qui "
                      "administre : un opérateur ouvre la console, décide des approbations et des apps.")
async def comptes(ui: Any, request: Request) -> Any:
    return await page(ui, request, {})


def _account_page(ui: Any, request: Request, found: Account, accounts: list[Account],
                  messages: list[Any]) -> dict[str, Any]:
    """La page d'un compte, vue d'un objet (ADR 0176) : son nom et ses étiquettes, ce qu'il ouvre, ses faits ; puis le
    formulaire, ses connexions web et ses applications connectées — un jeton qu'on vient de créer, montré une fois."""
    query = request.query_params
    deps, env, frame = ui.deps, ui.env(), ui.kernel.mind.frame()
    person, name = ui.names.person_of(found.handle), found.display_name
    tokens = list(reversed(deps.accounts.tokens(found.id)))
    apps, apps_pager = paginate(tokens, ui.inspection.context(query).pager("page_apps", size=12))
    sessions = deps.accounts.sessions(found.id)
    seen = deps.accounts.last_seen().get(found.id)
    facts = [("identifiant", found.username), ("personne", Ref.subject("person", person, name))]
    owned = _owned_tab(ui, person)
    if owned is not None:
        facts.append(("ses comptes", Ref("local", owned[1], owned[0])))
    facts += [("droits", Ref("local", rights_url(frame, person), "ses droits exacts")),
              ("dernière connexion", ui.when(seen * US) if seen else "—")]
    operator = ui.operator(request)
    if not found.active:
        intro = f"Désactivé : {name} ne peut plus se connecter. Ce qu'elle sait de cette personne reste."
    elif found.operator:
        intro = f"{name} se connecte à son espace (le web, le téléphone) et ouvre aussi la console : un opérateur " \
                "compte parmi ses propriétaires."
    else:
        intro = f"{name} se connecte à son espace (le web, le téléphone) et parle avec elle, sans ouvrir la console."
    return {"blocks": [], "messages": messages, "crumbs": [(name, "")],
            "panel": Panel("handmade/reglages/compte.html", {
                "mode": "edit", "action": URL, "account": found,
                # la vue d'un objet : son nom, ses étiquettes, ce qu'il ouvre, ses faits (``page.html`` les lit)
                "page_heading": name, "page_subtitle": intro,
                "head_badges": [{"text": "opérateur", "tone": "ok"} if found.operator else
                                {"text": "utilisateur", "tone": "muted"},
                                {"text": "actif", "tone": "ok"} if found.active else
                                {"text": "désactivé", "tone": "muted"}],
                "facts": [{"label": k, "cell": render.cell(v, env)} for k, v in facts],
                "operators": sum(1 for a in accounts if a.operator and a.active),
                "sessions": {"count": len(sessions), "last": ui.when(sessions[0].created_at * US) if sessions else "",
                             "until": ui.when(max(x.expires_at for x in sessions) * US) if sessions else "",
                             "days": SESSION_TTL_S // (DAY // US), "mine": operator is not None and
                             operator.id == found.id},
                "apps": [_app_row(ui, t) for t in apps], "apps_total": len(tokens),
                "apps_pager": render._pager(apps_pager, query), "clients": list(CLIENTS.items()),
                "label_max": TOKEN_LABEL_MAX,
                # un jeton neuf, à l'opératrice qui vient de le créer, une seule fois (jamais dans l'adresse)
                "shown": ui.pop_reveal(str(query.get("montrer", "")), operator.handle if operator else "")})}


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
        # le fil : la rubrique et la destination (« Réglages / Comptes »), puis cette page
        return {"blocks": [], "messages": messages, "crumbs": [(heading, "")],
                "panel": Panel("handmade/reglages/compte.html", {
                    "mode": "create", "action": URL, "page_heading": heading, "role": role,
                    "operator_role": role == OPERATOR, "values": state.get("values") or {},
                    "switch": _account_url(nouveau=USER if role == OPERATOR else OPERATOR)})}
    if editing:
        found = next((a for a in accounts if str(a.id) == editing), None)
        if found is not None:
            return _account_page(ui, request, found, accounts, messages)
        messages.append(("warn", "Ce compte n'existe pas."))
    window, pager = paginate(accounts, ctx.pager(size=25))
    frame, seen = ui.kernel.mind.frame(), ui.deps.accounts.last_seen()
    rows = tuple(Row((
        Ref("local", _account_url(compte=str(a.id)), a.username), a.full_name or Text("—", "muted"),
        Ref.subject("person", a.handle, a.display_name),
        Badge("opérateur", "ok") if a.operator else Badge("utilisateur", "muted"),
        Badge("actif", "ok") if a.active else Badge("désactivé", "muted"), _seen(seen.get(a.id)),
        Ref("local", rights_url(frame, ui.names.person_of(a.handle)), "ses droits exacts")),
        href=Ref("local", _account_url(compte=str(a.id)), ""), tone="" if a.active else "muted") for a in window)
    # les deux boutons d'ajout : les actions de la page, à droite de son titre (ADR 0176)
    add = Panel("handmade/reglages/compte.html", {"mode": "list", "page_links": [
        ("＋ Ajouter un utilisateur", _account_url(nouveau=USER)),
        ("＋ Ajouter un opérateur", _account_url(nouveau=OPERATOR))]})
    return {"messages": messages, "panel": add, "blocks": [
        Stats((Stat("Comptes", len(accounts)), Stat("Opérateurs actifs", sum(1 for a in accounts
                                                                               if a.operator and a.active)),
               Stat("Utilisateurs", sum(1 for a in accounts if not a.operator)),
               Stat("Désactivés", sum(1 for a in accounts if not a.active)))),
        Table((Column("identifiant", role="title"), "nom affiché", Column("personne", "fit"),
               Column("rôle", role="badge"), Column("état", role="badge"), Column("dernière connexion", "fit"),
               Column("droits", "fit")), rows,
              title=f"Comptes ({len(accounts)})", pager=pager, empty="Aucun compte.",
              layout="list", link_label="Modifier le compte",
              caption="Chaque compte est une personne qu'elle connaît dès sa création, sous son nom affiché ; "
                      "sa fiche réunit tout ce qu'elle en sait. La dernière connexion : l'ouverture de sa session "
                      "web la plus récente encore gardée, ou le dernier usage d'une de ses applications — une "
                      "déconnexion efface sa session.")]}


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
    if data.get("action") == "create_token":
        return await _create_token(ui, data, account, account_id)
    if data.get("action") == "close_sessions":
        if not any(a.id == account_id for a in deps.accounts.all()):
            return None, {"messages": [("danger", "Ce compte n'existe pas.")]}, 400
        closed = await deps.accounts.close_sessions(account_id)
        if not closed:
            return _done(ui, "info", "Aucune session web n'était ouverte.", compte=str(account_id)), {}, 303
        await operations.audit(ui.kernel, "console.comptes.sessions", by=account.handle, subject_kind="compte",
                               subject=f"user_{account_id}")
        return _done(ui, "ok", f"{closed} session{'s' if closed > 1 else ''} web fermée{'s' if closed > 1 else ''} : "
                               "ses pages ouvertes se déconnectent dans les secondes qui suivent ; ses applications "
                               "restent.", compte=str(account_id)), {}, 303
    refused = await deps.accounts.update(account_id, operator=data.get("operator") == "on",
                                         active=data.get("active") == "on", password=data.get("password") or None,
                                         full_name=data.get("full_name") if "full_name" in data else None)
    if refused:
        return None, {"editing": str(account_id), "messages": [("danger", refused)]}, 400
    await operations.audit(ui.kernel, "console.comptes.modifier", by=account.handle, subject_kind="compte",
                           subject=f"user_{account_id}")
    return _done(ui, "ok", "Compte modifié."), {}, 303


async def _create_token(ui: Any, data: Mapping[str, Any], by: Account,
                        account_id: int) -> tuple[Response | None, dict[str, Any], int]:
    """« Nouveau jeton » : un nom, ce qu'il ouvre ; donné par la console (``SOURCE_CONSOLE`` : il ne tombe pas avec le
    mot de passe), audité, montré une seule fois à qui l'a créé."""
    label = " ".join(str(data.get("label", "")).split())[:TOKEN_LABEL_MAX]
    client = str(data.get("client", ""))
    problem = "" if label else "Donne un nom au jeton (« Unity du salon ») : c'est lui qu'on reconnaîtra dans la liste."
    if client not in CLIENTS:
        problem = "Choisis ce qu'il ouvre : un écran ou un moteur de jeu, ou le téléphone."
    if problem:
        return None, {"editing": str(account_id), "messages": [("danger", problem)]}, 400
    try:
        info, raw = await ui.deps.accounts.create_token(account_id, label, client=client, source=SOURCE_CONSOLE)
    except ValueError as exc:  # un compte inconnu ou désactivé : pas de jeton
        return None, {"editing": str(account_id), "messages": [("danger", str(exc))]}, 400
    await operations.audit(ui.kernel, "console.comptes.jeton", by=by.handle, subject_kind="compte",
                           subject=f"user_{account_id}")
    shown = ui.reveal(by.handle, {"title": f"Le jeton « {info.label} »", "token": raw, "use": TOKEN_USE[client]})
    return _done(ui, "ok", f"Jeton créé : « {info.label} » ({CLIENTS[client].lower()}).", compte=str(account_id),
                 montrer=shown), {}, 303


def _done(ui: Any, tone: str, message: str, **query: str) -> Response:
    token = _secrets.token_urlsafe(9)
    ui.flash(token, tone, message)
    return secure(RedirectResponse(_account_url(**query, flash=token), status_code=303))
