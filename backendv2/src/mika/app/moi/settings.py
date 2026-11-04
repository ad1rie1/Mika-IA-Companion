"""Paramètres, pour qui est connecté (ADR 0187) : son compte (son nom, son mot de passe), ses boîtes aux lettres (les
ajouter, les régler, les tester, les connecter à Microsoft, les retirer), ses comptes Teams (les ajouter, les régler,
la clé de leur extension).

Ce qu'une personne branche est à elle (ADR 0185, 0186) : à son nom (``personne:<clé>``), ou « à toi » si elle est une
de ses propriétaires — jamais à quelqu'un d'autre ; le partager est une délégation (ADR 0188), pas un changement de
propriétaire. Une ressource qui n'est pas à elle n'existe pas ici. Les secrets ne repartent jamais : un mot de passe
laissé vide reste celui qui est gardé. Ce qui se dérive d'une boîte ou d'un compte (à qui, actif) est rejournalisé
aussitôt (``reconfigure``), comme depuis la console.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from typing import Any

from pydantic import ValidationError
from starlette.routing import Route

from mika.adapters.mail.config import MICROSOFT, MailAccount, MailConfig
from mika.adapters.teams import TeamsAccount, TeamsConfig
from mika.app.moi import OWN_MAX, Call, Denied, MeApi, done, form, missing
from mika.app.moi import mail as mail_moi
from mika.app.moi import teams as teams_moi
from mika.app.moi.hosts import LOCAL, local_host
from mika.kernel import forms
from mika.ports.mail import ACCOUNT_KEY
from mika.runtime.operations import audit
from mika.vocab.access import PERSON

#: ce qu'une personne règle d'une boîte (``owner`` n'y est pas : une boîte reste à qui l'a branchée)
MAIL_FIELDS = ("label", "address", "enabled", "auth", "imap_host", "imap_port", "imap_ssl", "user", "password",
               "folders", "sync_all", "since_days", "oauth_client_id", "oauth_tenant", "smtp_host", "smtp_port",
               "smtp_security", "smtp_user", "smtp_password", "save_sent", "voice", "display_name", "sender_name",
               "tone", "instructions", "signature")
#: ses secrets : jamais rendus, laissés vides ils restent
MAIL_SECRETS = ("password", "smtp_password")
#: ce qu'une personne règle d'un compte Teams
TEAMS_FIELDS = ("label", "enabled", "display_name", "tone", "instructions", "sign", "signature")
#: la connexion d'une boîte : quand elle change, ses secrets se redonnent (ils ne partent jamais vers un autre hôte)
IMAP_CONNECTION = ("auth", "imap_host", "imap_port", "imap_ssl", "user", "oauth_client_id", "oauth_tenant")
SMTP_CONNECTION = ("smtp_host", "smtp_port", "smtp_security", "smtp_user")
#: les serveurs qu'une boîte fait joindre
HOSTS = ("imap_host", "smtp_host")
#: ce qui vise chacun : changer son port ou sa sécurité, c'est viser un autre service de cet hôte
TARGETS = {"imap_host": ("imap_host", "imap_port", "imap_ssl"),
           "smtp_host": ("smtp_host", "smtp_port", "smtp_security")}
#: les serveurs de Microsoft : le seul endroit où le jeton d'une boîte Microsoft se présente (ADR 0166)
MICROSOFT_HOSTS = (".office365.com", ".outlook.com")
#: ce que dit un serveur refusé à une boîte Microsoft
NOT_MICROSOFT = "un serveur de Microsoft (outlook.office365.com, smtp.office365.com…)"


def _owner_for(call: Call) -> str:
    """À qui est ce qu'elle branche : « à toi » pour une de ses propriétaires, sinon à son nom."""
    return "" if call.me.owner else PERSON + call.me.person


def _settings(call: Call) -> Any:
    settings = call.api.settings
    if settings is None:
        raise Denied(503, "Les réglages ne sont pas branchés.")
    return settings


async def _rejournal(call: Call) -> None:
    if call.api.reconfigure is not None:
        await call.api.reconfigure()


def _slug(text: str, taken: set[str]) -> str:
    """Une clé neuve (minuscules, chiffres, - ou _) tirée d'un nom ou d'une adresse, suivie d'un suffixe tiré au
    hasard et libre parmi ``taken`` : une clé ne sert jamais deux fois, car le courrier gardé, ses pièces et ce
    qu'elle en sait restent rangés sous la clé d'une boîte retirée (une boîte neuve ne les rouvre pas)."""
    flat = unicodedata.normalize("NFKD", text.split("@", 1)[0].lower())
    base = re.sub(r"[^a-z0-9_-]+", "-", "".join(ch for ch in flat if not unicodedata.combining(ch))).strip("-_")[:30]
    base = base if base and ACCOUNT_KEY.fullmatch(base) else "boite"
    while True:
        key = f"{base}-{secrets.token_hex(3)}"
        if key not in taken:
            return key


def _traces(call: Call) -> set[str]:
    """Les clés de boîte dont sa vie garde une trace (ses mails remarqués, ses envois, ses brouillons, ses demandes)."""
    s = mail_moi._state(call)
    return {*(m.account for m in s.mails.values()), *(x.account for x in s.sent.values()),
            *(d.account for d in s.drafts.values()), *(a.account for a in s.asked.values())}


async def _public_hosts(call: Call, hosts: dict[str, Any]) -> None:
    """Une personne qui n'est pas opératrice ne fait joindre que des serveurs sur Internet. Seuls comptent les
    serveurs qu'elle vise (une boîte neuve ; un serveur, son port ou sa sécurité changés) : une boîte réglée par une
    opératrice sur la machine (DavMail) ou le réseau local se règle encore, tant qu'on n'en change pas la cible."""
    if call.me.operator:
        return
    bad = {f: LOCAL for f, host in hosts.items() if isinstance(host, str) and await local_host(host)}
    if bad:
        raise Denied(400, "Un serveur sur Internet seulement.", bad)


def _microsoft_host(host: str) -> bool:
    name = host.strip().rstrip(".").lower()
    return any(name.endswith(suffix) for suffix in MICROSOFT_HOSTS)


def _own_room(call: Call, mine: int) -> None:
    """Une personne qui n'est pas opératrice branche au plus ``OWN_MAX`` ressources de chaque sorte."""
    if not call.me.operator and mine >= OWN_MAX:
        raise Denied(409, f"Tu en as déjà {OWN_MAX} : retires-en une avant d'en brancher une autre.")


def _changed(before: Any, values: dict[str, Any], fields: tuple[str, ...]) -> bool:
    return any(f in values and str(values[f]) != str(getattr(before, f)) for f in fields)


def _values(call: Call, allowed: tuple[str, ...]) -> dict[str, Any]:
    raw = call.data.get("values")
    if not isinstance(raw, dict):
        raise Denied(400, "« values » : un objet.")
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        raise Denied(400, f"« {unknown[0]} » ne se règle pas ici.")
    return dict(raw)


def _refused(exc: ValidationError) -> Denied:
    return Denied(400, "Le formulaire a des erreurs.", forms.errors_fr(exc))


# ── son compte ──


async def account_name(call: Call) -> dict[str, Any]:
    name = " ".join(call.arg("name", limit=120).split())
    if not name:
        raise Denied(400, "Un nom.", {"name": "valeur requise"})
    problem = await call.api.accounts.update(call.me.account.id, full_name=name)
    if problem:
        raise Denied(400, problem)
    await audit(call.kernel, "moi.nom", by=call.me.handle, subject_kind="compte", subject=call.me.account.username)
    return {"ok": True, "message": "C'est ton nom, maintenant : elle t'appellera ainsi."}


async def account_password(call: Call) -> dict[str, Any]:
    """Changer son mot de passe : l'ancien d'abord. Toutes ses sessions se ferment, et les jetons obtenus par
    l'ancien mot de passe tombent : on se reconnecte."""
    me, throttle = call.me, call.api.password_tries
    tries = f"compte:{me.account.id}"
    if throttle.blocked(tries):
        raise Denied(429, "Trop d'essais : attends une minute avant de réessayer.")
    throttle.fail(tries)  # compté d'avance : des essais lancés ensemble ne passent pas tous avant le premier échec
    if await call.api.accounts.verify(me.account.username, call.arg("current", limit=200)) is None:
        raise Denied(400, "Ce n'est pas ton mot de passe actuel.", {"current": "mot de passe incorrect"})
    throttle.forgive(tries)
    problem = await call.api.accounts.update(me.account.id, password=call.arg("password", limit=200))
    if problem:
        raise Denied(400, problem, {"password": problem})
    await audit(call.kernel, "moi.mot_de_passe", by=me.handle, subject_kind="compte", subject=me.account.username)
    return {"ok": True, "message": "Mot de passe changé : reconnecte-toi.", "relogin": True}


# ── ses boîtes ──


def _box_settings(key: str, a: MailAccount) -> dict[str, Any]:
    values = {f: getattr(a, f) for f in MAIL_FIELDS if f not in MAIL_SECRETS}
    values["folders"] = list(a.folders)
    return {"box": key, "values": values, "secrets": {f: bool(getattr(a, f)) for f in MAIL_SECRETS},
            "ready": a.ready, "can_send": a.can_send, "microsoft": a.microsoft}


async def box_get(call: Call) -> dict[str, Any]:
    key = call.arg("box", limit=40)
    mail_moi.owned(call, key)
    found = _settings(call).email().accounts.get(key)
    if found is None:
        raise missing()
    got = _box_settings(key, found)
    port = call.port("mail")
    signin = port.signin(key) if port is not None and found.microsoft else None
    got["signin"] = {"state": signin.state, "code": signin.code, "url": signin.url, "until": signin.until // 1000,
                     "error": signin.error} if signin is not None else None
    return got


def _kept_secrets(before: MailAccount, values: dict[str, Any]) -> None:
    """Un secret laissé vide reste — sauf si sa connexion change : il ne part jamais vers un autre serveur. L'envoi
    laissé sans mot de passe se sert de celui de la lecture (``smtp_password or password``) : changer le serveur
    d'envoi le redemande aussi, à moins de le redonner pour lire dans le même envoi. Une connexion qu'on retire (son
    serveur vidé : une boîte qui ne fait que lire) ne redemande rien : rien ne part plus."""
    given = {s for s in MAIL_SECRETS if values.get(s)}
    microsoft = values.get("auth", before.auth) == MICROSOFT
    for secret, connection, host in (("password", IMAP_CONNECTION, "imap_host"),
                                     ("smtp_password", SMTP_CONNECTION, "smtp_host")):
        if secret in given:
            continue
        if not str(values.get(host, getattr(before, host)) or "").strip():
            values[secret] = getattr(before, secret)  # plus de serveur (une boîte qui ne fait que lire) : il reste
            continue
        # ce qui partirait vers cette connexion : son secret, ou pour l'envoi sans le sien, celui de la lecture
        outgoing = getattr(before, secret) or (secret == "smtp_password" and "password" not in given
                                                and before.password)
        if outgoing and _changed(before, values, connection):
            if microsoft:
                values[secret] = ""  # une boîte Microsoft n'a pas de mot de passe (lire ni envoyer) : il part
                continue
            raise Denied(400, "La connexion a changé : redonne le mot de passe.",
                         {secret: "à redonner pour cette connexion"})
        values[secret] = getattr(before, secret)


async def box_save(call: Call) -> dict[str, Any]:
    """Créer une boîte (sans ``box``), ou régler une des siennes. Elle est à qui la branche ; ses secrets laissés
    vides restent, tant que sa connexion ne change pas. Une création redite avec la même clé d'envoi ne refait
    rien."""
    if call.arg("box", limit=40):
        return await _box_save(call)
    return await call.once(lambda: _box_save(call))


async def _box_save(call: Call) -> dict[str, Any]:
    settings = _settings(call)
    cfg = settings.email()
    values = _values(call, MAIL_FIELDS)
    key = call.arg("box", limit=40)
    before: MailAccount | None = None
    if key:
        mail_moi.owned(call, key)
        if key not in cfg.accounts:
            raise missing()
        before = cfg.accounts[key]
        _kept_secrets(before, values)
        merged = {**before.model_dump(), **values, "owner": before.owner, "shares": before.shares}
        hosts = {host: merged.get(host) for host, parts in TARGETS.items() if _changed(before, values, parts)}
        # une boîte Microsoft ne présente son jeton qu'aux serveurs de Microsoft : à vérifier quand ils changent, ou
        # quand elle le devient
        microsoft = hosts if before.microsoft else {f: merged.get(f) for f in HOSTS}
    else:
        _own_room(call, sum(1 for a in cfg.accounts.values() if a.owner == _owner_for(call)))
        key = _slug(str(values.get("label") or values.get("address") or ""), set(cfg.accounts) | _traces(call))
        merged = {**values, "owner": _owner_for(call)}
        hosts = microsoft = {f: merged.get(f) for f in HOSTS}
    await _public_hosts(call, hosts)
    if merged.get("auth") == MICROSOFT:
        bad = {f: NOT_MICROSOFT for f, host in microsoft.items() if host and not _microsoft_host(str(host))}
        if bad:
            raise Denied(400, "Une boîte Microsoft ne joint que les serveurs de Microsoft : son jeton ne se présente "
                              "nulle part ailleurs.", bad)
    bounds = forms.within(forms.describe(MailAccount), merged)  # les bornes de la console (un port, une fenêtre)
    if bounds:
        raise Denied(400, "Le formulaire a des erreurs.", bounds)
    try:
        account = MailAccount.model_validate(merged)
    except ValidationError as exc:
        raise _refused(exc) from None
    # relues puis réécrites d'un seul tenant : ce qu'une autre personne vient d'enregistrer reste (les serveurs, plus
    # longs à vérifier, l'ont été avant)
    async with settings.writing:
        cfg = settings.email()
        if before is not None:
            if key not in cfg.accounts:
                raise missing()
            if cfg.accounts[key] != before:
                raise Denied(409, "Cette boîte vient d'être réglée ailleurs : rouvre-la, puis recommence.")
        else:
            _own_room(call, sum(1 for a in cfg.accounts.values() if a.owner == _owner_for(call)))
            if key in cfg.accounts:
                key = _slug(str(values.get("label") or values.get("address") or ""), set(cfg.accounts) | _traces(call))
        try:
            new = MailConfig(accounts={**cfg.accounts, key: account})
        except ValidationError as exc:
            raise _refused(exc) from None
        await settings.save_email(new)
        await _rejournal(call)
    await audit(call.kernel, "moi.boite", by=call.me.handle, subject_kind="compte", subject=key)
    return {"ok": True, "message": "Boîte enregistrée.", "box": key, "ready": account.ready}


async def box_remove(call: Call) -> dict[str, Any]:
    """Retirer une de ses boîtes : elle n'est plus relevée ; ce qu'elle en a appris reste dans sa vie."""
    settings = _settings(call)
    key = call.arg("box", limit=40)
    mail_moi.owned(call, key)
    async with settings.writing:
        cfg = settings.email()
        if key not in cfg.accounts:
            raise missing()
        await settings.save_email(MailConfig(accounts={k: a for k, a in cfg.accounts.items() if k != key}))
        await _rejournal(call)
    await audit(call.kernel, "moi.boite_retiree", by=call.me.handle, subject_kind="compte", subject=key)
    return {"ok": True, "message": "Boîte retirée."}


async def box_test(call: Call) -> dict[str, Any]:
    key = call.arg("box", limit=40)
    mail_moi.owned(call, key)
    call.probe()
    return done(await call.act("email.tester", form(), subject=key))


async def box_microsoft(call: Call) -> dict[str, Any]:
    """Connecter une boîte Microsoft (ADR 0166) : un code à entrer chez Microsoft ; ``GET …/mail/box`` dit ensuite
    où en est la connexion."""
    key = call.arg("box", limit=40)
    mail_moi.owned(call, key)
    return done(await call.act("email.microsoft", form(), subject=key))


# ── ses comptes Teams ──


def _teams_settings(key: str, a: TeamsAccount, call: Call) -> dict[str, Any]:
    keys = call.port("teams_keys")
    state = keys.key_state(key) if keys is not None else None
    return {"account": key, "values": {f: getattr(a, f) for f in TEAMS_FIELDS},
            "extension_key": {"hint": state.hint, "created_at": state.created_at // 1000} if state is not None else None}


async def teams_get(call: Call) -> dict[str, Any]:
    key = call.arg("account", limit=40)
    teams_moi.owned(call, key)
    found = _settings(call).teams().accounts.get(key)
    if found is None:
        raise missing()
    return _teams_settings(key, found, call)


async def teams_save(call: Call) -> dict[str, Any]:
    """Créer un compte Teams (sans ``account``), ou régler un des siens : il est à qui le branche. Une création
    redite avec la même clé d'envoi ne refait rien."""
    if call.arg("account", limit=40):
        return await _teams_save(call)
    return await call.once(lambda: _teams_save(call))


async def _teams_save(call: Call) -> dict[str, Any]:
    settings = _settings(call)
    async with settings.writing:  # relus puis réécrits d'un seul tenant (``Settings.writing``)
        return await _teams_write(call, settings)


async def _teams_write(call: Call, settings: Any) -> dict[str, Any]:
    cfg = settings.teams()
    values = _values(call, TEAMS_FIELDS)
    key = call.arg("account", limit=40)
    if key:
        teams_moi.owned(call, key)
        if key not in cfg.accounts:
            raise missing()
        merged = {**cfg.accounts[key].model_dump(), **values, "owner": cfg.accounts[key].owner,
                  "shares": cfg.accounts[key].shares}
    else:
        _own_room(call, sum(1 for a in cfg.accounts.values() if a.owner == _owner_for(call)))
        s = teams_moi._state(call)
        traces = {*(d.account for d in s.drafts.values()), *(m.account for m in s.messages.values()),
                  *(a.account for a in s.asked.values())}
        key = _slug(str(values.get("label") or call.me.name or "teams"), set(cfg.accounts) | traces)
        merged = {**values, "owner": _owner_for(call)}
    bounds = forms.within(forms.describe(TeamsAccount), merged)
    if bounds:
        raise Denied(400, "Le formulaire a des erreurs.", bounds)
    try:
        account = TeamsAccount.model_validate(merged)
        new = cfg.model_copy(update={"accounts": {**cfg.accounts, key: account}})
        TeamsConfig.model_validate(new.model_dump())
    except ValidationError as exc:
        raise _refused(exc) from None
    await settings.save_teams(new)
    await _rejournal(call)
    await audit(call.kernel, "moi.compte_teams", by=call.me.handle, subject_kind="compte_teams", subject=key)
    return {"ok": True, "message": "Compte Teams enregistré.", "account": key}


async def teams_remove(call: Call) -> dict[str, Any]:
    """Retirer un de ses comptes Teams (ADR 0186) : sa clé part avec lui, et ce que son extension avait apporté
    (conversations, messages, brouillons) s'efface ; ce qu'elle en a appris reste dans sa vie."""
    settings = _settings(call)
    key = call.arg("account", limit=40)
    teams_moi.owned(call, key)
    async with settings.writing:
        cfg = settings.teams()
        if key not in cfg.accounts:
            raise missing()
        await settings.save_teams(cfg.model_copy(update={"accounts": {k: a for k, a in cfg.accounts.items()
                                                                      if k != key}}))
        store = call.port("teams")
        if store is not None:
            store.drop_account(key)
        await _rejournal(call)
    await audit(call.kernel, "moi.compte_teams_retire", by=call.me.handle, subject_kind="compte_teams", subject=key)
    return {"ok": True, "message": "Compte Teams retiré."}


async def teams_key(call: Call) -> dict[str, Any]:
    """Une clé neuve pour l'extension d'un de ses comptes, montrée cette fois seulement ; l'ancienne ne vaut plus."""
    key = call.arg("account", limit=40)
    keys = call.port("teams_keys")
    teams_moi.owned(call, key)
    if keys is None:
        raise missing()
    try:
        fresh = await keys.new_key(key, call.me.handle)
    except ValueError as exc:
        raise Denied(409, str(exc)) from None
    await audit(call.kernel, "teams.cle", by=call.me.handle, subject_kind="compte_teams", subject=key)
    return {"ok": True, "message": "Clé neuve : colle-la dans l'extension de ce compte (elle ne sera plus montrée).",
            "key": fresh}


async def teams_revoke(call: Call) -> dict[str, Any]:
    key = call.arg("account", limit=40)
    keys = call.port("teams_keys")
    teams_moi.owned(call, key)
    if keys is None:
        raise missing()
    if not await keys.revoke_key(key, call.me.handle):
        raise Denied(409, "Ce compte n'avait pas de clé.")
    await audit(call.kernel, "teams.retirer_cle", by=call.me.handle, subject_kind="compte_teams", subject=key)
    return {"ok": True, "message": "Clé retirée : son extension est refusée jusqu'à une clé neuve."}


def routes(api: MeApi) -> list[Route]:
    r = api.route
    return [r("/account/name", account_name, write=True), r("/account/password", account_password, write=True),
            r("/mail/box", box_get), r("/mail/box/save", box_save, write=True),
            r("/mail/box/remove", box_remove, write=True), r("/mail/box/test", box_test, write=True),
            r("/mail/box/microsoft", box_microsoft, write=True),
            r("/teams/account", teams_get), r("/teams/account/save", teams_save, write=True),
            r("/teams/account/key", teams_key, write=True), r("/teams/account/revoke", teams_revoke, write=True),
            r("/teams/account/remove", teams_remove, write=True)]
