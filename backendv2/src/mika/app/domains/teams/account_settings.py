"""Les réglages d'un compte Teams, pour qui est connecté (ADR 0187, 0186, 0310) : l'ajouter, le régler, la clé de son
extension, le retirer — ses routes, que ``api.py`` ajoute aux siennes.

Un compte qu'une personne branche est à elle (ADR 0186) : à son nom (``personne:<clé>``), ou « à toi » si elle est une
de ses propriétaires — jamais à quelqu'un d'autre ; le partager est une délégation (ADR 0188), pas un changement de
propriétaire. Un compte qui n'est pas à elle n'existe pas ici. Ce qui se dérive d'un compte (à qui, actif, la règle de
son canal) est rejournalisé aussitôt (``reconfigure``), comme depuis la console. Le cadre de ces réglages est dans
``app/me/settings.py`` : son compte, comment part ce qu'elle prépare (la règle de son canal, ADR 0207), et les aides
qu'une boîte et un compte Teams se partagent.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from starlette.routing import Route

from mika.adapters.teams import TeamsAccount, TeamsConfig
from mika.app.domains.teams import api as teams_me
from mika.app.me import settings as settings_me
from mika.app.me.api import Call, Denied, MeApiBase, missing, refused
from mika.app.me.common import own_room, settings_of
from mika.kernel import forms
from mika.ports.teams import ACCOUNT_KEY
from mika.runtime.operations import audit
from mika.vocab.access import TEAMS

#: ce qu'une personne règle d'un compte Teams
TEAMS_FIELDS = ("label", "enabled", "display_name", "tone", "instructions", "sign", "signature")


def _teams_settings(key: str, a: TeamsAccount, call: Call) -> dict[str, Any]:
    keys = call.port("teams_keys")
    state = keys.key_state(key) if keys is not None else None
    return {"account": key, "values": {f: getattr(a, f) for f in TEAMS_FIELDS},
            "extension_key": {"hint": state.hint, "created_at": state.created_at // 1000} if state is not None else None}


async def teams_get(call: Call) -> dict[str, Any]:
    key = call.arg("account", limit=40)
    teams_me.owned(call, key)
    found = settings_of(call).named("teams").teams().accounts.get(key)
    if found is None:
        raise missing()
    return {**_teams_settings(key, found, call), "rules": settings_me._rules_json(call, f"{TEAMS}:{key}")}


async def teams_save(call: Call) -> dict[str, Any]:
    """Créer un compte Teams (sans ``account``), ou régler un des siens : il est à qui le branche. Une création
    redite avec la même clé d'envoi ne refait rien."""
    if call.arg("account", limit=40):
        return await _teams_save(call)
    return await call.once(lambda: _teams_save(call))


async def _teams_save(call: Call) -> dict[str, Any]:
    settings = settings_of(call)
    async with settings.writing:  # relus puis réécrits d'un seul tenant (``Settings.writing``)
        return await _teams_write(call, settings)


async def _teams_write(call: Call, settings: Any) -> dict[str, Any]:
    cfg = settings.named("teams").teams()
    values = settings_me._values(call, TEAMS_FIELDS)
    key = call.arg("account", limit=40)
    if key:
        teams_me.owned(call, key)
        if key not in cfg.accounts:
            raise missing()
        merged = {**cfg.accounts[key].model_dump(), **values, "owner": cfg.accounts[key].owner,
                  "shares": cfg.accounts[key].shares}
    else:
        own_room(call, sum(1 for a in cfg.accounts.values() if a.owner == settings_me._owner_for(call)))
        s = teams_me.state(call)
        traces = {*(d.account for d in s.drafts.values()), *(m.account for m in s.messages.values()),
                  *(a.account for a in s.asked.values())}
        key = settings_me._slug(str(values.get("label") or call.me.name or "teams"), set(cfg.accounts) | traces,
                                ACCOUNT_KEY)
        merged = {**values, "owner": settings_me._owner_for(call)}
    bounds = forms.within(forms.describe(TeamsAccount), merged)
    if bounds:
        raise Denied(400, "Le formulaire a des erreurs.", bounds)
    try:
        account = TeamsAccount.model_validate(merged)
        new = cfg.model_copy(update={"accounts": {**cfg.accounts, key: account}})
        TeamsConfig.model_validate(new.model_dump())
    except ValidationError as exc:
        raise refused(exc) from None
    await settings.named("teams").save_teams(new)
    await settings_me._rejournal(call)
    await audit(call.kernel, "moi.compte_teams", by=call.me.handle, subject_kind="compte_teams", subject=key)
    return {"ok": True, "message": "Compte Teams enregistré.", "account": key}


async def teams_remove(call: Call) -> dict[str, Any]:
    """Retirer un de ses comptes Teams (ADR 0186) : sa clé part avec lui, et ce que son extension avait apporté
    (conversations, messages, brouillons) s'efface ; ce qu'elle en a appris reste dans sa vie."""
    settings = settings_of(call)
    key = call.arg("account", limit=40)
    teams_me.owned(call, key)
    async with settings.writing:
        cfg = settings.named("teams").teams()
        if key not in cfg.accounts:
            raise missing()
        await settings.named("teams").save_teams(cfg.model_copy(update={"accounts": {k: a for k, a in cfg.accounts.items()
                                                                      if k != key}}))
        store = call.port("teams")
        if store is not None:
            store.drop_account(key)
        await settings_me._rejournal(call)
    await audit(call.kernel, "moi.compte_teams_retire", by=call.me.handle, subject_kind="compte_teams", subject=key)
    return {"ok": True, "message": "Compte Teams retiré."}


async def teams_key(call: Call) -> dict[str, Any]:
    """Une clé neuve pour l'extension d'un de ses comptes, montrée cette fois seulement ; l'ancienne ne vaut plus."""
    key = call.arg("account", limit=40)
    keys = call.port("teams_keys")
    teams_me.owned(call, key)
    if keys is None:
        raise missing()
    try:
        fresh = await keys.new_key(key, call.me.handle)
    except ValueError as exc:
        raise Denied(409, str(exc)) from None
    # ce que fait l'action « teams.cle » de la console, ici depuis son espace : sa clé d'audit le dit (« moi. »)
    await audit(call.kernel, "moi.teams.cle", by=call.me.handle, subject_kind="compte_teams", subject=key)
    return {"ok": True, "message": "Clé neuve : colle-la dans l'extension de ce compte (elle ne sera plus montrée).",
            "key": fresh}


async def teams_revoke(call: Call) -> dict[str, Any]:
    key = call.arg("account", limit=40)
    keys = call.port("teams_keys")
    teams_me.owned(call, key)
    if keys is None:
        raise missing()
    if not await keys.revoke_key(key):
        raise Denied(409, "Ce compte n'avait pas de clé.")
    await audit(call.kernel, "moi.teams.retirer_cle", by=call.me.handle, subject_kind="compte_teams", subject=key)
    return {"ok": True, "message": "Clé retirée : son extension est refusée jusqu'à une clé neuve."}


def routes(api: MeApiBase) -> list[Route]:
    r = api.route
    return [r("/teams/account", teams_get), r("/teams/account/save", teams_save, write=True),
            r("/teams/account/key", teams_key, write=True), r("/teams/account/revoke", teams_revoke, write=True),
            r("/teams/account/remove", teams_remove, write=True)]
