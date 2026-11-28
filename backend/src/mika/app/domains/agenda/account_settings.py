"""Les comptes d'agenda, pour qui est connecté (ADR 0309, lot 4 ; 0310) — Paramètres › Agendas : ses comptes (son
compte du système, ceux qu'elle branche : Google, Microsoft, CalDAV, iCal), les brancher, les régler, essayer un
serveur CalDAV, les connecter à Google ou à Microsoft, les synchroniser, les déconnecter, les retirer ; un agenda neuf,
et un de ses agendas réglé — ses routes, que ``api.py`` ajoute aux siennes.

Un compte qu'elle branche est à elle : à son nom (``personne:<clé>``), ou « à toi » si elle est une de ses
propriétaires (la règle du courrier) ; un compte d'une autre n'existe pas ici (404). Sa clé ne vient jamais de son
adresse. Un secret laissé vide reste celui qui est gardé, tant que le serveur ne change pas ; pour qui n'est pas
opératrice, un serveur sur Internet seulement. Ce qui se règle (un compte, un agenda) l'est dans les réglages, sous
leur verrou, rejournalisé aussitôt (``reconfigure``) et audité ``moi.<geste>`` ; synchroniser, créer un agenda, le
renommer passent par les actions du plugin. Ce qu'une personne a de ses agendas, et comment un agenda se montre, est
dans ``reach.py``. Le contrat : ``docs/protocole-moi.md``, § 13.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from html import escape
from typing import Any

from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from mika.adapters.agenda import SERVICES, AgendaAccount, AgendaConfig, server_host
from mika.adapters.agenda.config import ACCOUNT_KEY, COLORS
from mika.adapters.web.session import account_of
from mika.app.connections import ConnectionSettings
from mika.app.domains.agenda.reach import (
    account_kind,
    agenda_ports,
    agenda_settings,
    calendar_json,
    done_with_made,
    mine,
    must_own_account,
    owned_calendar,
)
from mika.app.domains.agenda.settings import AgendaSettings
from mika.app.me.api import NO_STORE, OWN_MAX, Call, Denied, MeApiBase, done, form, missing, refused
from mika.app.me.common import millis, own_room, settings_of
from mika.app.me.hosts import public_only
from mika.plugins.agenda import params_of
from mika.plugins.agenda.actions import account_level
from mika.ports.agenda import (
    CALDAV,
    GOOGLE,
    ICAL,
    KIND_WORDS,
    MICROSOFT,
    REMINDERS,
    AgendaError,
    Calendar,
    Connection,
    split_calendar_key,
    system_account,
    system_person,
)
from mika.ports.signin import SIGNED_IN
from mika.runtime.operations import audit
from mika.vocab.access import PERSON
from mika.vocab.ownership import OWNED
from mika.vocab.words import fold

#: ce qu'on dit d'une sorte qui se branche ici (le système existe sans rien faire)
PLUGGABLE = (GOOGLE, MICROSOFT, CALDAV, ICAL)
#: ce qu'une personne règle d'un compte
ACCOUNT_FIELDS = ("label", "enabled", "url", "username", "password", "address", "oauth_client_id", "oauth_tenant")
NO_GOOGLE_APP = "L'application Google de ce serveur n'est pas réglée : demande-le à qui s'occupe d'elle."


def _signin(call: Call, key: str, kind: str, conn: Connection | None) -> dict[str, Any] | None:
    _store, providers = agenda_ports(call)
    provider = providers.of(kind)
    signin = getattr(provider, "signin", None)
    if signin is None:
        return None
    got = signin.state(key) if kind == GOOGLE else signin.state(key, conn) if conn is not None else None
    if got is None:
        return None
    return {"state": got.state, "code": got.code, "url": got.url, "until": millis(got.until), "error": got.error}


def _account_json(call: Call, key: str, a: AgendaAccount, held: Mapping[str, tuple[Calendar, str]],
                  cfg: AgendaConfig) -> dict[str, Any]:
    store, providers = agenda_ports(call)
    state = store.account(key)
    conn = providers.connection(key)
    provider = providers.of(a.kind)
    abilities = provider.abilities(conn) if provider is not None and conn is not None else None
    cals = [calendar_json(call, cal, lv, cfg) for cal, lv in held.values() if cal.account == key]
    cals.sort(key=lambda c: (not c["primary"], fold(c["name"])))
    system = bool(system_person(key))
    return {"key": key, "kind": a.kind, "kind_label": KIND_WORDS.get(a.kind, a.kind),
            "label": a.label or ("Ce serveur" if system else key), "system": system, "address": a.address,
            "enabled": a.enabled, "url": a.url if a.kind == CALDAV else "",
            "url_set": bool(a.url) if a.kind == ICAL else False, "username": a.username,
            "secrets": {"password": bool(a.password)}, "oauth_client_id": a.oauth_client_id,
            "oauth_tenant": a.oauth_tenant if a.kind == MICROSOFT else "",
            "synced_at": millis(state.synced_at) if state is not None else 0,
            "tried_at": millis(state.tried_at) if state is not None else 0,
            "failures": state.failures if state is not None else 0,
            "error": state.error if state is not None and not system else "",
            "signin": _signin(call, key, a.kind, conn) if a.kind in (GOOGLE, MICROSOFT) else None,
            "abilities": {"write": bool(abilities and abilities.write),
                          "calendars": bool(abilities and abilities.calendars)},
            "calendars": cals}


async def accounts(call: Call) -> dict[str, Any]:
    """Ses comptes d'agenda : son compte du système d'abord, puis ceux qu'elle a branchés ; ce que le serveur sait
    brancher (l'application Google, celle de Microsoft, les aides CalDAV) et les bornes."""
    settings = settings_of(call)
    cfg = settings.of(AgendaSettings).agenda()
    held = mine(call)
    p = params_of(call.frame)
    own = system_account(call.me.person)
    keys = [own, *sorted(k for k in cfg.accounts if not system_person(k)
                         and account_level(p, call.frame, call.me.person, k) == OWNED)]
    found = []
    for key in keys:
        a = cfg.account(key)
        if a is not None:
            found.append(_account_json(call, key, a, held, cfg))
    _store, providers = agenda_ports(call)
    google = getattr(providers.of(GOOGLE), "signin", None)
    return {"plugged": True, "accounts": found,
            "google": {"app": settings.of(ConnectionSettings).google_application() is not None,
                       "direct": bool(google is not None and google.direct())},
            "microsoft_app": bool(settings.of(ConnectionSettings).microsoft_application()),
            "kinds": [{"code": k, "label": KIND_WORDS[k]} for k in PLUGGABLE],
            "services": [{"key": x.key, "name": x.name, "url": x.url, "help": x.help} for x in SERVICES],
            "colors": [{"code": c, "label": w} for c, w in COLORS],
            "reminders": [{"code": c, "label": w} for c, w in REMINDERS],
            "max": None if call.me.operator else OWN_MAX}


def _owner_for(call: Call) -> str:
    """À qui est ce qu'elle branche : « à toi » pour une de ses propriétaires, sinon à son nom (la règle du
    courrier)."""
    return "" if call.me.owner else PERSON + call.me.person


def _account_key(call: Call, label: str, kind: str, taken: set[str]) -> str:
    """La clé d'un compte branché : son nom affiché (sinon sa sorte), puis la fin d'un identifiant de l'``IdGen`` —
    jamais son adresse, ni un nom qui en est une : ses réglages, ses agendas et l'audit sont journalisés, et l'oubli
    d'une adresse ne les atteint pas. Un compte déjà branché garde la sienne."""
    said = "" if "@" in label else label
    base = re.sub(r"[^a-z0-9_-]+", "-", fold(said or KIND_WORDS[kind])).strip("-_")[:30].strip("-_")
    base = base if base and ACCOUNT_KEY.fullmatch(base) else "agenda"
    mind = call.kernel.mind
    while True:
        key = f"{base}-{mind.ids.new(mind.clock.now())[-6:].lower()}"
        if key not in taken:
            return key


def _mine_count(call: Call, cfg: AgendaConfig) -> int:
    return sum(1 for k, a in cfg.accounts.items() if not system_person(k) and a.owner == _owner_for(call))


def _values(call: Call) -> dict[str, Any]:
    raw = call.data.get("values", {})
    if not isinstance(raw, dict):
        raise Denied(400, "« values » : un objet.")
    unknown = sorted(set(raw) - set(ACCOUNT_FIELDS))
    if unknown:
        raise Denied(400, f"« {unknown[0]} » ne se règle pas ici.", {unknown[0]: "inconnu"})
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k == "enabled":
            out[k] = v is True
        elif not isinstance(v, str) or len(v) > 2000:
            raise Denied(400, f"« {k} » : une chaîne de 2 000 caractères au plus.", {k: "une chaîne"})
        else:
            out[k] = v.strip()
    return out


async def _rejournal(call: Call) -> None:
    if call.api.reconfigure is not None:
        await call.api.reconfigure()


async def account_save(call: Call) -> dict[str, Any]:
    """Brancher un compte (sans ``account`` : sa sorte, ``kind``) ou régler un des siens. Un secret laissé vide reste
    celui qui est gardé, tant que le serveur ne change pas ; pour qui n'est pas opératrice, un serveur sur Internet
    seulement. Une création redite avec la même clé d'envoi ne refait rien."""
    if call.arg("account", limit=200):
        return await _account_save(call)
    return await call.once(lambda: _account_save(call))


async def _account_save(call: Call) -> dict[str, Any]:
    settings = agenda_settings(call)
    cfg = settings.agenda()
    values = _values(call)
    key = call.arg("account", limit=200)
    before: AgendaAccount | None = None
    if key:
        must_own_account(call, key)
        before = cfg.account(key)
        assert before is not None
        if system_person(key):
            values = {k: v for k, v in values.items() if k == "label"}
        merged = {**before.model_dump(), **values, "owner": before.owner, "kind": before.kind,
                  "calendars": before.calendars}
        moved = before.url != merged.get("url", before.url) or before.username != merged.get("username",
                                                                                              before.username)
        if not values.get("password") and before.password and not moved:
            merged["password"] = before.password
        elif not values.get("password") and before.password and moved and before.kind == CALDAV:
            raise Denied(400, "Le serveur change : redonne son mot de passe.", {"password": "à redonner"})
        if before.kind == ICAL and not values.get("url"):
            merged["url"] = before.url
        targets = {"url": merged.get("url")} if moved or (before.kind == ICAL and values.get("url")) else {}
    else:
        kind = call.arg("kind", limit=20)
        if kind not in PLUGGABLE:
            raise Denied(400, "« kind » : google, microsoft, caldav ou ical.", {"kind": "une sorte de compte"})
        own_room(call, _mine_count(call, cfg))
        key = _account_key(call, str(values.get("label") or "").strip(), kind, set(cfg.accounts))
        merged = {**values, "kind": kind, "owner": _owner_for(call)}
        if kind in (CALDAV, ICAL) and not merged.get("url"):
            raise Denied(400, "Son adresse, d'abord.", {"url": "valeur requise"})
        targets = {"url": merged.get("url")}
    if merged.get("kind") in (GOOGLE, MICROSOFT):
        merged["url"] = merged["password"] = ""
        targets = {}
    await public_only(call, {f: server_host(str(v or "")) for f, v in targets.items() if v})
    # son serveur revérifié sur Internet à chaque connexion, pas seulement ici (une opératrice vise ce qu'elle veut)
    merged["internet"] = not call.me.operator and merged.get("kind") in (CALDAV, ICAL)
    try:
        account = AgendaAccount.model_validate(merged)
    except ValidationError as exc:
        raise refused(exc) from None
    async with settings.writing:
        cfg = settings.agenda()
        if before is not None:
            if cfg.account(key) != before:
                raise Denied(409, "Ce compte vient d'être réglé ailleurs : rouvre-le, puis recommence.")
        else:
            own_room(call, _mine_count(call, cfg))
        try:
            await settings.save_agenda(AgendaConfig(accounts={**cfg.accounts, key: account}))
        except ValidationError as exc:
            raise refused(exc) from None
        await _rejournal(call)
    await audit(call.kernel, "moi.agenda_compte", by=call.me.handle, subject_kind="compte_agenda", subject=key)
    if account.kind in (CALDAV, ICAL) and account.enabled:
        await call.act("agenda.synchroniser", form(fixed={"account": key}), part="sync")
    return {"ok": True, "message": "Compte d'agenda enregistré.", "account": key}


async def account_remove(call: Call) -> dict[str, Any]:
    """Retirer un compte branché : ses agendas et leur copie partent ; ce que Mika en a appris reste."""
    settings = agenda_settings(call)
    key = call.arg("account", limit=200)
    must_own_account(call, key)
    if system_person(key):
        raise Denied(409, "Ton agenda du système reste : on ne le retire pas.")
    async with settings.writing:
        cfg = settings.agenda()
        if key not in cfg.accounts:
            raise missing()
        await settings.save_agenda(AgendaConfig(accounts={k: a for k, a in cfg.accounts.items() if k != key}))
        await _rejournal(call)
    store, _providers = agenda_ports(call)
    store.drop_account(key)
    await audit(call.kernel, "moi.agenda_compte_retire", by=call.me.handle, subject_kind="compte_agenda", subject=key)
    return {"ok": True, "message": "Compte d'agenda retiré."}


async def account_try(call: Call) -> dict[str, Any]:
    """Essayer un serveur CalDAV (son adresse, son identifiant, son mot de passe ; ou un compte déjà branché, dont le
    mot de passe gardé sert tant que le serveur ne change pas) : les agendas qu'il propose, sans rien enregistrer."""
    _store, providers = agenda_ports(call)
    key = call.arg("account", limit=200)
    url, user, password = call.arg("url", limit=1000).strip(), call.arg("username", limit=300).strip(), \
        call.arg("password", limit=300)
    if key:
        must_own_account(call, key)
        a = agenda_settings(call).agenda().account(key)
        if a is None or a.kind != CALDAV:
            raise Denied(409, "Seul un compte CalDAV s'essaie ainsi.")
        url, user = url or a.url, user or a.username
        if not password and url == a.url and user == a.username:
            password = a.password
    if not url:
        raise Denied(400, "Son adresse, d'abord.", {"url": "valeur requise"})
    await public_only(call, {"url": server_host(url)})
    call.probe()
    provider = providers.of(CALDAV)
    if provider is None:
        raise Denied(503, "CalDAV n'est pas branché sur ce serveur.")
    conn = Connection(key=key or "essai", kind=CALDAV, url=url, username=user, secret=password,
                      internet=not call.me.operator)
    try:
        found = await provider.calendars(conn)
    except AgendaError as exc:
        return {"ok": False, "message": str(exc)[:300] or "Le serveur a refusé.", "calendars": []}
    except Exception as exc:  # noqa: BLE001 — un serveur en panne, quelle qu'elle soit, se dit en mots
        return {"ok": False, "message": f"Le serveur n'a pas répondu : {type(exc).__name__}", "calendars": []}
    return {"ok": True, "message": f"{len(found)} agenda{'s' if len(found) > 1 else ''} trouvé"
                                   f"{'s' if len(found) > 1 else ''}.",
            "calendars": [{"local": split_calendar_key(c.key)[1], "name": c.name, "color": c.color,
                           "writable": c.writable, "primary": c.primary, "selected": c.selected} for c in found]}


def _connectable(call: Call, kind: str) -> tuple[str, Any, Connection]:
    key = call.arg("account", limit=200)
    must_own_account(call, key)
    _store, providers = agenda_ports(call)
    conn = providers.connection(key)
    signin = getattr(providers.of(kind), "signin", None)
    if conn is None or conn.kind != kind or signin is None:
        raise Denied(409, f"Ce compte n'entre pas par {KIND_WORDS[kind]}.")
    return key, signin, conn


async def google_start(call: Call) -> dict[str, Any]:
    """Commencer la connexion Google d'un compte : l'adresse de consentement à ouvrir ; on finit en collant l'adresse
    de la page qui n'a pas pu s'ouvrir (ou son code), ou la redirection revient seule (``direct``)."""
    key, signin, conn = _connectable(call, GOOGLE)
    if settings_of(call).of(ConnectionSettings).google_application() is None:
        raise Denied(409, NO_GOOGLE_APP)
    origin = call.request.headers.get("origin") or str(call.request.base_url).rstrip("/")
    try:
        got = signin.start(key, who=call.me.handle, origin=origin, hint=conn.address)
    except AgendaError as exc:
        raise Denied(409, str(exc)[:300]) from None
    return {"ok": True, "url": got.url, "until": millis(got.until), "direct": signin.direct()}


async def _connected(call: Call, key: str, kind: str) -> None:
    """Après une connexion : l'adresse du compte (pour y reconnaître ses invitations), puis une synchronisation."""
    settings = agenda_settings(call)
    _store, providers = agenda_ports(call)
    provider, conn = providers.of(kind), providers.connection(key)
    address = ""
    try:
        address = await provider.whoami(conn) if provider is not None and conn is not None else ""
    except Exception:  # noqa: BLE001 — l'adresse est un surcroît : la connexion, elle, est faite
        address = ""
    if address:
        async with settings.writing:
            cfg = settings.agenda()
            a = cfg.accounts.get(key)
            if a is not None and a.address != address:
                await settings.save_agenda(AgendaConfig(accounts={
                    **cfg.accounts, key: a.model_copy(update={"address": address})}))
                await _rejournal(call)
    await call.act("agenda.synchroniser", form(fixed={"account": key}), part="sync")


async def google_finish(call: Call) -> dict[str, Any]:
    """Finir la connexion Google : l'adresse collée (ou son code)."""
    key, signin, _conn = _connectable(call, GOOGLE)
    text = call.arg("text", limit=4000).strip()
    if not text:
        raise Denied(400, "Colle l'adresse de la page qui n'a pas pu s'ouvrir.", {"text": "valeur requise"})
    try:
        await signin.finish(text, key=key, who=call.me.handle)
    except AgendaError as exc:
        raise Denied(400, str(exc)[:300], {"text": str(exc)[:200]}) from None
    await _connected(call, key, GOOGLE)
    await audit(call.kernel, "moi.agenda_connexion", by=call.me.handle, subject_kind="compte_agenda", subject=key)
    return {"ok": True, "message": "Connecté à Google : l'agenda se synchronise."}


def _page(title: str, text: str, address: str = "") -> HTMLResponse:
    shown = f"<p><code style=\"word-break:break-all\">{escape(address)}</code></p>" if address else ""
    body = (f"<!doctype html><meta charset=utf-8><meta name=viewport content=\"width=device-width\">"
            f"<title>{escape(title)}</title><h1>{escape(title)}</h1><p>{escape(text)}</p>{shown}")
    return HTMLResponse(body, headers={**NO_STORE, "Content-Security-Policy": "default-src 'none'",
                                       "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})


#: le retour de Google dans un navigateur sans session (celui du téléphone, où l'application l'a ouvert)
PASTE_HERE = ("Copie l'adresse de cette page, puis colle-la dans l'application, là où tu as lancé la connexion "
              "(Paramètres › Agendas). Elle seule la finit, pour ton compte.")


def _return_route(api: MeApiBase) -> Route:
    """La redirection directe de Google. Avec une session, le parcours se finit ici, pour qui l'a commencé. Sans (le
    navigateur du téléphone, où l'application a ouvert le consentement), une page en mots dit de copier son adresse et
    de la coller dans l'application : le ``state`` seul ne dit pas qui revient — un parcours commencé par une
    personne et consenti par une autre rattacherait l'agenda Google de la seconde au compte de la première."""
    inner = api.route("/agenda/google/retour", google_return, raw=True)

    async def endpoint(request: Request) -> Response:
        if account_of(request, api.accounts) is None:
            return _page("Encore une étape", PASTE_HERE, str(request.url))
        return await inner.endpoint(request)

    return Route(inner.path, endpoint, methods=["GET"])


async def google_return(call: Call) -> HTMLResponse:
    """La redirection directe de Google (une « Application Web » du serveur) : le parcours se finit ici, pour qui l'a
    commencé ; une page dit ce qui s'est passé (le client l'apprend par le direct)."""
    _store, providers = agenda_ports(call)
    signin = getattr(providers.of(GOOGLE), "signin", None)
    if signin is None:
        raise missing()
    try:
        key = await signin.finish("?" + call.request.url.query, who=call.me.handle)
    except AgendaError as exc:
        return _page("Google Agenda n'est pas connecté", str(exc)[:300])
    await _connected(call, key, GOOGLE)
    await audit(call.kernel, "moi.agenda_connexion", by=call.me.handle, subject_kind="compte_agenda", subject=key)
    return _page("Google Agenda est connecté", "Tu peux fermer cette page : l'agenda se synchronise.")


async def microsoft_start(call: Call) -> dict[str, Any]:
    """Connecter un compte Outlook.com / Microsoft 365 : un code à entrer chez Microsoft ; la fin de l'attente est
    poussée en direct (``agenda``), puis ``…/account/sync`` relit le compte."""
    key, signin, conn = _connectable(call, MICROSOFT)
    try:
        got = await signin.start(key, conn)
    except (OSError, RuntimeError, ValueError) as exc:
        raise Denied(409, f"La connexion n'a pas pu commencer : {exc}"[:300]) from None
    return {"ok": True, "code": got.code, "url": got.url, "until": millis(got.until), "state": got.state,
            "error": got.error}


async def account_sync(call: Call) -> dict[str, Any]:
    """Synchroniser maintenant un de ses comptes (un compte Google ou Microsoft connecté retrouve d'abord son
    adresse)."""
    key = call.arg("account", limit=200)
    must_own_account(call, key)
    if system_person(key):
        return {"ok": True, "message": "Ton agenda du système est toujours à jour.", "deduped": False}
    kind = account_kind(call, key)
    a = agenda_settings(call).agenda().accounts.get(key)
    if kind in (GOOGLE, MICROSOFT) and a is not None and not a.address:
        signed = _signin(call, key, kind, agenda_ports(call)[1].connection(key))
        if signed is not None and signed["state"] == SIGNED_IN:
            await _connected(call, key, kind)
            return {"ok": True, "message": "Synchronisation demandée.", "deduped": False}
    return done(await call.act("agenda.synchroniser", form(fixed={"account": key})))


async def account_disconnect(call: Call) -> dict[str, Any]:
    """Déconnecter un compte Google ou Microsoft : sa connexion est retirée (chez Google aussi) et oubliée ; le compte
    reste, « à reconnecter »."""
    settings = agenda_settings(call)
    key = call.arg("account", limit=200)
    must_own_account(call, key)
    kind = account_kind(call, key)
    if kind not in (GOOGLE, MICROSOFT):
        raise Denied(409, "Ce compte n'a pas de connexion à retirer : retire le compte.")
    signin = getattr(agenda_ports(call)[1].of(kind), "signin", None)
    if signin is not None:
        if kind == GOOGLE:
            try:
                await signin.revoke(key)
            except (AgendaError, OSError, RuntimeError, ValueError):
                pass  # Google injoignable : la connexion part quand même d'ici
        signin.drop(key)
    await settings.drop_agenda_grant(key)
    await audit(call.kernel, "moi.agenda_deconnexion", by=call.me.handle, subject_kind="compte_agenda", subject=key)
    return {"ok": True, "message": "Déconnecté."}


async def calendar_new(call: Call) -> dict[str, Any]:
    account = call.arg("account", limit=200) or system_account(call.me.person)
    must_own_account(call, account)
    return done_with_made(await call.act("agenda.nouvel_agenda", form(fixed={"account": account},
                                                                      name=call.arg("name", limit=200))))


async def calendar_save(call: Call) -> dict[str, Any]:
    """Régler un de ses agendas : son nom (``agenda.renommer``), sa couleur, masqué (Mika ne s'en sert plus), « Mika
    te le rappelle », suivi."""
    settings = agenda_settings(call)
    key = call.arg("calendar", limit=200)
    owned_calendar(call, key)
    account, local_ = split_calendar_key(key)
    renamed = None
    if "name" in call.data:
        renamed = await call.act("agenda.renommer", form(fixed={"calendar": key}, name=call.arg("name", limit=200)))
        if not renamed.ok or not ({"color", "hidden", "reminder", "followed"} & set(call.data)):
            return done(renamed)
    changes: dict[str, Any] = {}
    if "color" in call.data:
        changes["color"] = call.arg("color", limit=20)
    if "hidden" in call.data:
        changes["hidden"] = call.data["hidden"] is True
    if "reminder" in call.data:
        changes["reminder"] = call.arg("reminder", limit=10)
    if "followed" in call.data:
        raw = call.data["followed"]
        if raw is not None and not isinstance(raw, bool):
            raise Denied(400, "« followed » : vrai, faux ou null.", {"followed": "vrai, faux ou null"})
        changes["followed"] = raw
    if not changes:
        raise Denied(409, "Rien à changer.")
    async with settings.writing:
        cfg = settings.agenda()
        found = cfg.account(account)
        if found is None:
            raise missing()
        try:
            setting = found.setting(local_).model_validate({**found.setting(local_).model_dump(), **changes})
            changed = found.model_copy(update={"calendars": {**found.calendars, local_: setting}})
            await settings.save_agenda(AgendaConfig(accounts={**cfg.accounts, account: changed}))
        except ValidationError as exc:
            raise refused(exc) from None
        await _rejournal(call)
    await audit(call.kernel, "moi.agenda_reglage", by=call.me.handle, subject_kind="agenda", subject=key)
    return {"ok": True, "message": "Agenda réglé."}


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    return [r("/agenda/accounts", accounts), r("/agenda/account/save", account_save, write=True),
            r("/agenda/account/remove", account_remove, write=True),
            r("/agenda/account/try", account_try, write=True),
            r("/agenda/account/sync", account_sync, write=True),
            r("/agenda/account/disconnect", account_disconnect, write=True),
            r("/agenda/account/google/start", google_start, write=True),
            r("/agenda/account/google/finish", google_finish, write=True),
            _return_route(api),
            r("/agenda/account/microsoft/start", microsoft_start, write=True),
            r("/agenda/calendar/new", calendar_new, write=True),
            r("/agenda/calendar/save", calendar_save, write=True)]
